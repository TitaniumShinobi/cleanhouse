"""Shared durable authenticated OVVAULTS evidence transport.

Files and Network both enqueue into one SQLite outbox. The filesystem mirror
is only a local cache; a surface becomes live only after an owner-scoped,
authenticated receipt proving a commit to ``ovvaults.vault_files``.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import platform
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend import vvault_preservation


SCHEMA = "cleanhouse.files_evidence.batch.v1"
DEFAULT_VVAULT_URL = "https://vvault.thewreck.org"
KEYCHAIN_SERVICE = "org.cleanhouse.vvault.files"
KEYCHAIN_ACCOUNT = "zen-001"
VALID_SURFACES = {"files", "network"}
MAX_BATCH_SIZE = 50
RETRY_BASE_SECONDS = 2
RETRY_MAX_SECONDS = 300
DEGRADED_BACKLOG_COUNT = 100
DEGRADED_PENDING_AGE_SECONDS = 60
KEYCHAIN_READ_TIMEOUT_SECONDS = 15
REMOTE_TIMEOUT_SECONDS = 10
MAX_REMOTE_RESPONSE_BYTES = 2 * 1024 * 1024
_LOCK = threading.RLock()
_DB_INIT_IDENTITIES: dict[str, tuple[int, int]] = {}
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_KEYCHAIN_CACHE: dict[str, Any] = {"loaded_at": 0.0, "payload": {}}


def _now_datetime() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _now() -> str:
    return _now_datetime().isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _replay_equivalent_payload(value: Any) -> Any:
    """Remove non-evidence transport metrics before replay comparison."""
    if isinstance(value, dict):
        return {
            str(key): _replay_equivalent_payload(item)
            for key, item in value.items()
            if str(key) != "ingestion_latency_ms"
        }
    if isinstance(value, list):
        return [_replay_equivalent_payload(item) for item in value]
    return value


def _surface(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if candidate not in VALID_SURFACES:
        raise ValueError("surface must be files or network")
    return candidate


def _db_path() -> Path:
    configured = os.getenv("CLEANHOUSE_FILES_OUTBOX_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    runtime_dir = Path(os.getenv("CLEANHOUSE_RUNTIME_DIR", Path.home() / ".cleanhouse" / "runtime")).expanduser()
    return runtime_dir / "files" / "preservation.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=2000")
    return conn


@contextmanager
def _managed_connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create or migrate the original Files outbox without replacing rows."""
    path = _db_path()
    path_key = str(path)
    try:
        identity = (int(path.stat().st_dev), int(path.stat().st_ino))
    except OSError:
        identity = None
    with _LOCK:
        if identity is not None and _DB_INIT_IDENTITIES.get(path_key) == identity:
            return
    with _LOCK, _managed_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files_outbox (
                evidence_id TEXT PRIMARY KEY,
                surface TEXT NOT NULL DEFAULT 'files',
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT NOT NULL DEFAULT '',
                next_attempt_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                last_error_at TEXT NOT NULL DEFAULT '',
                synced_at TEXT,
                receipt_id TEXT,
                remote_receipt_json TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(files_outbox)").fetchall()}
        additions = {
            "surface": "TEXT NOT NULL DEFAULT 'files'",
            "last_attempt_at": "TEXT NOT NULL DEFAULT ''",
            "next_attempt_at": "TEXT NOT NULL DEFAULT ''",
            "last_error_at": "TEXT NOT NULL DEFAULT ''",
            "receipt_id": "TEXT",
            "remote_receipt_json": "TEXT",
        }
        for column, definition in additions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE files_outbox ADD COLUMN {column} {definition}")
        conn.execute("UPDATE files_outbox SET surface = 'files' WHERE surface IS NULL OR surface = ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_receipts (
                receipt_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL UNIQUE,
                surface TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                storage_owner TEXT NOT NULL,
                receipt_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS files_outbox_pending_surface_idx "
            "ON files_outbox(surface, synced_at, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS files_outbox_pending_idx "
            "ON files_outbox(synced_at, created_at, evidence_id)"
        )
    final_stat = path.stat()
    with _LOCK:
        _DB_INIT_IDENTITIES[path_key] = (int(final_stat.st_dev), int(final_stat.st_ino))


def _keychain_credentials(*, allow_refresh: bool = True) -> dict[str, str]:
    if sys.platform != "darwin" or not Path("/usr/bin/security").is_file():
        return {}
    now = time.monotonic()
    with _LOCK:
        loaded_at = float(_KEYCHAIN_CACHE.get("loaded_at") or 0.0)
        if loaded_at > 0 and now - loaded_at < 30:
            return dict(_KEYCHAIN_CACHE.get("payload") or {})
    if not allow_refresh:
        return {}
    service = (os.getenv("CLEANHOUSE_VVAULT_KEYCHAIN_SERVICE") or KEYCHAIN_SERVICE).strip()
    account = (os.getenv("CLEANHOUSE_VVAULT_KEYCHAIN_ACCOUNT") or KEYCHAIN_ACCOUNT).strip()
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_READ_TIMEOUT_SECONDS,
        )
        raw = (result.stdout or "").strip() if result.returncode == 0 else ""
        payload = json.loads(raw) if raw else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    credentials = {
        "token": str(payload.get("token") or "").strip(),
        "email": str(payload.get("email") or "").strip().lower(),
        "user_id": str(payload.get("user_id") or "").strip(),
        "instance_id": str(payload.get("instance_id") or account or KEYCHAIN_ACCOUNT).strip().lower(),
        "auth_type": str(payload.get("auth_type") or "service_token").strip().lower(),
    }
    if not credentials["token"] or not credentials["email"]:
        credentials = {}
    with _LOCK:
        _KEYCHAIN_CACHE.update({"loaded_at": now, "payload": credentials})
    return dict(credentials)


def _config(*, allow_keychain_read: bool = True) -> tuple[str, str]:
    keychain = _keychain_credentials(allow_refresh=allow_keychain_read)
    explicit_url = (
        os.getenv("CLEANHOUSE_VVAULT_FILES_EVIDENCE_URL")
        or os.getenv("CLEANHOUSE_VVAULT_PICKUP_URL")
        or os.getenv("VVAULT_PICKUP_URL")
        or ""
    ).strip()
    base_url = (os.getenv("CLEANHOUSE_VVAULT_URL") or os.getenv("VVAULT_URL") or DEFAULT_VVAULT_URL).strip().rstrip("/")
    url = explicit_url or (f"{base_url}/api/cleanhouse/files/evidence" if base_url else "")
    token = (
        os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN")
        or os.getenv("VVAULT_SERVICE_TOKEN")
        or keychain.get("token")
        or ""
    ).strip()
    return url, token


def remote_base_url() -> str:
    """Return the configured authenticated VVAULT origin.

    Files preservation and Wazuh transport intentionally share one owner-bound
    credential.  Keeping origin and header construction here prevents a second
    environment-only authentication path from drifting away from pairing.
    """
    return (
        os.getenv("CLEANHOUSE_VVAULT_URL")
        or os.getenv("VVAULT_URL")
        or DEFAULT_VVAULT_URL
    ).strip().rstrip("/")


def authenticated_headers(token_override: str | None = None) -> dict[str, str]:
    """Build owner-scoped VVAULT headers without exposing credential values.

    The dedicated CleanHouse pairing token is transported only in
    ``X-CleanHouse-Key``.  Legacy service credentials retain their existing
    bounded compatibility headers.
    """
    _url, configured_token = _config()
    token = str(token_override or configured_token or "").strip()
    identity = _owner_identity()
    if not token or not identity["email"]:
        return {}
    headers = {
        "X-Chatty-User": identity["email"],
        "X-CleanHouse-Instance": identity["instance_id"],
    }
    if _credential_type() == "cleanhouse_files_pairing":
        headers["X-CleanHouse-Key"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Chatty-Key"] = token
    if identity["user_id"]:
        headers["X-Chatty-User-Id"] = identity["user_id"]
    return headers


def _owner_identity(*, allow_keychain_read: bool = True) -> dict[str, str]:
    keychain = _keychain_credentials(allow_refresh=allow_keychain_read)
    email = (
        os.getenv("CLEANHOUSE_VVAULT_USER_EMAIL")
        or os.getenv("VVAULT_USER_EMAIL")
        or keychain.get("email")
        or ""
    ).strip().lower()
    user_id = (os.getenv("CLEANHOUSE_VVAULT_USER_ID") or keychain.get("user_id") or "").strip()
    instance_id = (
        os.getenv("CLEANHOUSE_VVAULT_INSTANCE_ID") or keychain.get("instance_id") or KEYCHAIN_ACCOUNT
    ).strip().lower()
    return {"email": email, "user_id": user_id, "instance_id": instance_id}


def _credential_type(*, allow_keychain_read: bool = True) -> str:
    if os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN") or os.getenv("VVAULT_SERVICE_TOKEN"):
        return "service_token"
    return str(
        _keychain_credentials(allow_refresh=allow_keychain_read).get("auth_type") or "service_token"
    ).strip().lower()


def _safe_remote_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        return False
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _remote_origin(url: str) -> tuple[str, str, int] | None:
    parsed = urllib.parse.urlparse(url)
    if not _safe_remote_url(url):
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme.lower(), str(parsed.hostname or "").lower(), port


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


def _open_remote(request: urllib.request.Request):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirectHandler(),
    )
    return opener.open(request, timeout=REMOTE_TIMEOUT_SECONDS)


def enqueue(
    evidence_id: str,
    payload: dict[str, Any],
    *,
    surface: str = "files",
    preserve_local_cache: bool = True,
) -> dict[str, Any]:
    """Idempotently append evidence to the shared durable outbox."""
    evidence_id = str(evidence_id or "").strip()
    if not evidence_id:
        raise ValueError("evidence_id is required")
    scoped_surface = _surface(surface)
    init_db()
    created_at = str(payload.get("timestamp") or payload.get("created_at") or _now())
    canonical_payload = _canonical_json(payload)
    if preserve_local_cache:
        local = vvault_preservation.preserve_json(
            relative_dir=f"evidence/{scoped_surface}",
            artifact_id=evidence_id,
            artifact_type=f"{scoped_surface}_evidence",
            data=payload,
            source=f"cleanhouse-{scoped_surface}",
            timestamp=created_at,
            evidence_refs=list(payload.get("evidence_refs") or []),
        )
    else:
        # High-rate Network evidence is already committed to the local event
        # spine before it reaches this durable SQLite outbox. Rewriting the
        # artifact, manifest, and secondary JSON indexes for every packet can
        # make capture fall permanently behind. The outbox remains the local
        # durable replay boundary and OVVAULTS remains canonical preservation.
        local = {
            "status": "outbox_only",
            "state": "durable_outbox",
            "schema": SCHEMA,
        }
    inserted = False
    with _LOCK, _managed_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO files_outbox "
            "(evidence_id, surface, created_at, payload_json) VALUES (?, ?, ?, ?)",
            (evidence_id, scoped_surface, created_at, canonical_payload),
        )
        inserted = cursor.rowcount == 1
        if not inserted:
            existing = conn.execute(
                "SELECT surface, payload_json FROM files_outbox WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
            existing_payload = json.loads(existing["payload_json"]) if existing else None
            if (
                not existing
                or existing["surface"] != scoped_surface
                or _canonical_json(_replay_equivalent_payload(existing_payload))
                != _canonical_json(_replay_equivalent_payload(payload))
            ):
                raise ValueError(f"OVVAULTS evidence ID collision: {evidence_id}")
    with _LOCK:
        worker_alive = _THREAD is not None and _THREAD.is_alive()
    if not worker_alive:
        start_service(surface=scoped_surface)
    return {
        "status": "queued" if inserted else "existing",
        "evidence_id": evidence_id,
        "surface": scoped_surface,
        "local_cache": local,
    }


def _pending(*, surface: str | None = None, limit: int = MAX_BATCH_SIZE, due_only: bool = True) -> list[dict[str, Any]]:
    init_db()
    clauses = ["synced_at IS NULL"]
    params: list[Any] = []
    if surface is not None:
        clauses.append("surface = ?")
        params.append(_surface(surface))
    if due_only:
        clauses.append("(next_attempt_at = '' OR next_attempt_at <= ?)")
        params.append(_now())
    params.append(max(1, min(int(limit), 200)))
    # WAL readers must not hold the process-state lock.  Capture callbacks use
    # that lock for their short outbox writes, so serializing a backlog scan
    # behind it can stop stdout consumption and eventually stall tshark.
    with _managed_connection() as conn:
        rows = conn.execute(
            "SELECT evidence_id, surface, created_at, payload_json, attempts FROM files_outbox WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at, evidence_id LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "evidence_id": row["evidence_id"],
            "surface": row["surface"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"]),
            "attempts": int(row["attempts"] or 0),
        }
        for row in rows
    ]


def _default_transport(url: str, token: str, body: bytes) -> dict[str, Any]:
    if _remote_origin(url) != _remote_origin(remote_base_url()):
        raise RuntimeError("OVVAULTS endpoint must share the authenticated VVAULT origin")
    batch_id = hashlib.sha256(body).hexdigest()
    identity = _owner_identity()
    if not identity["email"]:
        raise RuntimeError("Canonical VVAULT owner email is not configured")
    headers = {
        **authenticated_headers(token),
        "Content-Type": "application/json",
        "Idempotency-Key": batch_id,
        "X-CleanHouse-Batch-Id": batch_id,
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _open_remote(request) as response:
            if response.status >= 400:
                raise RuntimeError(f"OVVAULTS endpoint returned HTTP {response.status}")
            raw_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            try:
                content_length = int(raw_length) if raw_length is not None else None
            except (TypeError, ValueError):
                content_length = None
            if content_length is not None and content_length > MAX_REMOTE_RESPONSE_BYTES:
                raise RuntimeError("OVVAULTS response exceeded the size limit")
            raw_payload = response.read(MAX_REMOTE_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            raise RuntimeError("OVVAULTS endpoint redirect was rejected") from None
        raise RuntimeError(f"OVVAULTS endpoint returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("OVVAULTS endpoint is unreachable") from None
    except TimeoutError:
        raise RuntimeError("OVVAULTS endpoint timed out") from None
    if len(raw_payload) > MAX_REMOTE_RESPONSE_BYTES:
        raise RuntimeError("OVVAULTS response exceeded the size limit")
    try:
        payload = json.loads(raw_payload.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("OVVAULTS endpoint returned malformed JSON") from None
    if not isinstance(payload, dict):
        raise RuntimeError("OVVAULTS returned an invalid preservation receipt")
    return payload


def _validated_receipt(receipt: Any, *, batch_id: str, expected_ids: set[str]) -> dict[str, Any]:
    identity = _owner_identity()
    if not isinstance(receipt, dict):
        raise RuntimeError("OVVAULTS returned an invalid preservation receipt")
    accepted = {str(value) for value in receipt.get("accepted_evidence_ids") or []}
    required = {
        "receipt_id": str(receipt.get("receipt_id") or "").strip(),
        "batch_id": str(receipt.get("batch_id") or "").strip(),
        "owner_user_id": str(receipt.get("owner_user_id") or "").strip(),
        "instance_id": str(receipt.get("instance_id") or "").strip().lower(),
        "storage_owner": str(receipt.get("storage_owner") or "").strip(),
        "committed_at": str(receipt.get("committed_at") or "").strip(),
    }
    if (
        not required["receipt_id"]
        or required["batch_id"] != batch_id
        or not expected_ids.issubset(accepted)
        or not required["owner_user_id"]
        or required["instance_id"] != identity["instance_id"]
        or required["storage_owner"] != "ovvaults.vault_files"
        or not required["committed_at"]
    ):
        raise RuntimeError("OVVAULTS did not return a complete canonical authenticated receipt")
    return {**receipt, **required, "accepted_evidence_ids": sorted(accepted)}


def flush_once(
    *, surface: str | None = None,
    transport: Callable[[str, str, bytes], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Flush one surface-specific batch and durably record its receipt."""
    url, token = _config()
    if not url or not token:
        return {"status": "unavailable", "reason": "missing_authenticated_endpoint"}
    if transport is None and not _owner_identity()["email"]:
        return {"status": "unavailable", "reason": "missing_canonical_owner_identity"}
    if not _safe_remote_url(url):
        return {"status": "unavailable", "reason": "secure_endpoint_required"}
    if _remote_origin(url) != _remote_origin(remote_base_url()):
        return {"status": "unavailable", "reason": "credential_origin_mismatch"}
    requested_surface = _surface(surface) if surface is not None else None
    candidates = _pending(surface=requested_surface, limit=MAX_BATCH_SIZE, due_only=True)
    if not candidates:
        backlog = _pending(surface=requested_surface, limit=1, due_only=False)
        return {"status": "retrying" if backlog else "idle", "synced": 0}
    batch_surface = requested_surface or candidates[0]["surface"]
    batch = [item for item in candidates if item["surface"] == batch_surface][:MAX_BATCH_SIZE]
    outbound = {
        "schema": SCHEMA,
        "events": [
            {"evidence_id": item["evidence_id"], "created_at": item["created_at"], "payload": item["payload"]}
            for item in batch
        ],
    }
    body = _canonical_json(outbound).encode("utf-8")
    batch_id = hashlib.sha256(body).hexdigest()
    attempted_at = _now()
    try:
        receipt = _validated_receipt(
            (transport or _default_transport)(url, token, body),
            batch_id=batch_id,
            expected_ids={item["evidence_id"] for item in batch},
        )
        receipt_json = _canonical_json(receipt)
        received_at = _now()
        with _LOCK, _managed_connection() as conn:
            existing = conn.execute(
                "SELECT receipt_json FROM evidence_receipts WHERE receipt_id = ? OR batch_id = ?",
                (receipt["receipt_id"], batch_id),
            ).fetchone()
            if existing and existing["receipt_json"] != receipt_json:
                raise RuntimeError("OVVAULTS receipt identity collision")
            conn.execute(
                "INSERT OR IGNORE INTO evidence_receipts "
                "(receipt_id, batch_id, surface, committed_at, received_at, owner_user_id, instance_id, storage_owner, receipt_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt["receipt_id"], batch_id, batch_surface, receipt["committed_at"], received_at,
                    receipt["owner_user_id"], receipt["instance_id"], receipt["storage_owner"], receipt_json,
                ),
            )
            conn.executemany(
                "UPDATE files_outbox SET synced_at = ?, receipt_id = ?, last_attempt_at = ?, "
                "next_attempt_at = '', last_error = '', last_error_at = '', remote_receipt_json = ? "
                "WHERE evidence_id = ? AND synced_at IS NULL",
                [
                    (received_at, receipt["receipt_id"], attempted_at, receipt_json, item["evidence_id"])
                    for item in batch
                ],
            )
        return {
            "status": "ok", "surface": batch_surface, "synced": len(batch), "synced_at": received_at,
            "receipt_id": receipt["receipt_id"], "batch_id": batch_id,
        }
    except Exception as exc:
        message = "ovvaults_sync_failed"
        error_at = _now()
        with _LOCK, _managed_connection() as conn:
            for item in batch:
                next_attempt = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** min(item["attempts"], 8)))
                conn.execute(
                    "UPDATE files_outbox SET attempts = attempts + 1, last_attempt_at = ?, next_attempt_at = ?, "
                    "last_error = ?, last_error_at = ? WHERE evidence_id = ? AND synced_at IS NULL",
                    (
                        attempted_at, (_now_datetime() + timedelta(seconds=next_attempt)).isoformat(),
                        message, error_at, item["evidence_id"],
                    ),
                )
        return {
            "status": "degraded", "surface": batch_surface, "reason": "sync_failed",
            "error": type(exc).__name__, "pending": len(batch),
        }


def _age_seconds(value: str) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (_now_datetime() - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def status(surface: str | None = None, *, allow_keychain_read: bool = True) -> dict[str, Any]:
    """Return aggregate or surface-scoped canonical preservation readiness."""
    init_db()
    scoped_surface = _surface(surface) if surface is not None else None
    where = "WHERE synced_at IS NULL" + (" AND surface = ?" if scoped_surface else "")
    params: tuple[Any, ...] = (scoped_surface,) if scoped_surface else ()
    receipt_where = "WHERE surface = ?" if scoped_surface else ""
    # Status is a read-only projection.  Let SQLite's WAL snapshot isolate it
    # instead of blocking high-rate evidence writes on the process-state lock.
    with _managed_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS pending, MIN(created_at) AS oldest, MAX(attempts) AS max_attempts "
            "FROM files_outbox " + where,
            params,
        ).fetchone()
        error_row = conn.execute(
            "SELECT last_error, last_error_at FROM files_outbox " + where
            + " AND last_error != '' ORDER BY last_error_at DESC LIMIT 1",
            params,
        ).fetchone()
        receipt_row = conn.execute(
            "SELECT * FROM evidence_receipts " + receipt_where + " ORDER BY received_at DESC LIMIT 1",
            params,
        ).fetchone()
    url, token = _config(allow_keychain_read=allow_keychain_read)
    identity = _owner_identity(allow_keychain_read=allow_keychain_read)
    keychain = _keychain_credentials(allow_refresh=allow_keychain_read)
    configured = bool(
        url
        and token
        and identity["email"]
        and _safe_remote_url(url)
        and _remote_origin(url) == _remote_origin(remote_base_url())
    )
    pending = int(row["pending"] or 0)
    oldest_pending_at = str(row["oldest"] or "")
    oldest_age = _age_seconds(oldest_pending_at)
    has_error = bool(error_row and str(error_row["last_error"] or ""))
    last_error = "ovvaults_sync_failed" if has_error else ""
    authenticated = bool(receipt_row)
    backlog_degraded = pending >= DEGRADED_BACKLOG_COUNT or oldest_age >= DEGRADED_PENDING_AGE_SECONDS
    if not configured:
        sync_state = "unavailable"
        authentication_state = "unavailable"
    elif last_error or backlog_degraded:
        sync_state = "degraded"
        authentication_state = "failed" if last_error else ("authenticated" if authenticated else "unverified")
    elif authenticated:
        sync_state = "live"
        authentication_state = "authenticated"
    else:
        sync_state = "warming"
        authentication_state = "unverified"
    local_available = vvault_preservation.preservation_available()
    receipt = json.loads(receipt_row["receipt_json"]) if receipt_row else {}
    return {
        "provider": "ovvaults", "surface": scoped_surface or "all", "state": sync_state,
        "sync_state": sync_state, "status": sync_state, "ready": sync_state == "live",
        "authenticated_endpoint_configured": configured, "remote_sync_configured": configured,
        "remote_sync_state": sync_state, "evidence_authenticated": authenticated,
        "authentication_state": authentication_state,
        "credential_source": "environment" if (
            os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN") or os.getenv("VVAULT_SERVICE_TOKEN")
        ) else ("keychain" if keychain.get("token") else "unavailable"),
        "credential_type": _credential_type(allow_keychain_read=allow_keychain_read) if configured else "unavailable",
        "owner_identity_configured": bool(identity["email"]), "instance_id": identity["instance_id"],
        "pending": pending, "backlog_depth": pending, "oldest_pending_at": oldest_pending_at,
        "oldest_pending_age_seconds": oldest_age,
        "last_success_at": str(receipt_row["received_at"] or "") if receipt_row else "",
        "last_error": last_error,
        "last_error_at": str(error_row["last_error_at"] or "") if error_row else "",
        "last_receipt": receipt,
        "receipt_identity": {
            key: receipt.get(key) for key in (
                "receipt_id", "batch_id", "owner_user_id", "instance_id", "committed_at", "storage_owner"
            ) if receipt.get(key)
        },
        "worker_alive": bool(_THREAD and _THREAD.is_alive()),
        "local_cache": {"available": local_available, "state": "live" if local_available else "unavailable", "canonical": False},
        "local_mirror_available": local_available, "local_preservation": local_available,
        "local_state": "live" if local_available else "unavailable",
    }


def _worker(surface: str | None = None) -> None:
    while not _STOP.is_set():
        result = flush_once(surface=surface)
        _STOP.wait(1 if result.get("status") == "ok" else 2)


def start_service(*, surface: str | None = None) -> dict[str, Any]:
    """Start the single shared outbox worker and report the requested surface.

    The worker must remain unscoped so Files starting first cannot strand
    Network rows (or vice versa).  ``flush_once`` still preserves one surface
    per authenticated batch and stores surface-specific receipts.
    """
    global _THREAD
    scoped_surface = _surface(surface) if surface is not None else None
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(
                target=_worker,
                args=(None,),
                name="cleanhouse-ovvaults-evidence-sync",
                daemon=True,
            )
            _THREAD.start()
    return status(scoped_surface)


def stop_service(timeout: float = 5) -> dict[str, Any]:
    global _THREAD
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=max(0, timeout))
    stopped = thread is None or not thread.is_alive()
    if stopped:
        _THREAD = None
    return {"state": "stopped" if stopped else "stopping"}


def _pairing_private_key_path() -> Path:
    runtime_dir = Path(os.getenv("CLEANHOUSE_RUNTIME_DIR", Path.home() / ".cleanhouse" / "runtime")).expanduser()
    return runtime_dir / "pairing" / "cleanhouse-vvault-private.pem"


def begin_pairing() -> dict[str, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = _pairing_private_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, private_bytes)
    finally:
        os.close(descriptor)
    temporary.replace(path)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return {
        "status": "ready", "instance_id": KEYCHAIN_ACCOUNT, "algorithm": "RSA-OAEP-3072-SHA256",
        "public_key_pem": public_pem,
        "pairing_url": f"{DEFAULT_VVAULT_URL}/api/cleanhouse/files/pair",
    }


def _keychain_libraries():
    security = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
    core = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
    ]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    core.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core


def _store_keychain_payload(payload: dict[str, Any]) -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("macOS Keychain is required")
    security, core = _keychain_libraries()
    service = KEYCHAIN_SERVICE.encode("utf-8")
    account = KEYCHAIN_ACCOUNT.encode("utf-8")
    secret = _canonical_json(payload).encode("utf-8")
    item = ctypes.c_void_p()
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    found = security.SecKeychainFindGenericPassword(
        None, len(service), service, len(account), account,
        ctypes.byref(password_length), ctypes.byref(password_data), ctypes.byref(item),
    )
    if found == 0:
        security.SecKeychainItemFreeContent(None, password_data)
        result = security.SecKeychainItemModifyAttributesAndData(item, None, len(secret), secret)
    else:
        result = security.SecKeychainAddGenericPassword(
            None, len(service), service, len(account), account, len(secret), secret, ctypes.byref(item)
        )
    if item:
        core.CFRelease(item)
    if result != 0:
        raise RuntimeError(f"macOS Keychain returned OSStatus {result}")
    with _LOCK:
        _KEYCHAIN_CACHE.update({"loaded_at": 0.0, "payload": {}})


def complete_pairing(response: dict[str, Any]) -> dict[str, Any]:
    if (
        str(response.get("credential_type") or "") != "cleanhouse_files_pairing"
        or str(response.get("algorithm") or "") != "RSA-OAEP-3072-SHA256"
        or str(response.get("instance_id") or "").lower() != KEYCHAIN_ACCOUNT
    ):
        raise ValueError("VVAULT pairing response contract is invalid")
    path = _pairing_private_key_path()
    private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 3072:
        raise ValueError("CleanHouse pairing private key is invalid")
    try:
        ciphertext = base64.b64decode(str(response.get("ciphertext") or ""), validate=True)
        token = private_key.decrypt(
            ciphertext,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        ).decode("utf-8")
        if not token.startswith("chf_v1_") or not 48 <= len(token) <= 256:
            raise ValueError("VVAULT pairing credential is invalid")
        existing = _keychain_credentials()
        email = str(existing.get("email") or os.getenv("CLEANHOUSE_VVAULT_USER_EMAIL") or "").strip().lower()
        if not email:
            raise ValueError("Canonical VVAULT owner email is unavailable")
        _store_keychain_payload({
            "token": token, "email": email, "user_id": str(existing.get("user_id") or ""),
            "instance_id": KEYCHAIN_ACCOUNT, "auth_type": "cleanhouse_files_pairing",
        })
    finally:
        if path.exists():
            path.unlink()
    return {
        "status": "paired", "credential_type": "cleanhouse_files_pairing",
        "instance_id": KEYCHAIN_ACCOUNT, "credential_source": "keychain",
    }


def enqueue_network_verification() -> dict[str, Any]:
    evidence_id = "network-preservation-verification:2026-08-22"
    payload = {
        "schema": "cleanhouse.network_preservation_verification.v1",
        "event_type": "network_preservation_verification", "surface": "network",
        "timestamp": "2026-08-22T23:00:00+00:00", "bounded": True, "synthetic": True,
        "purpose": "prove shared authenticated OVVAULTS evidence transport",
    }
    return enqueue(evidence_id, payload, surface="network")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pair-begin")
    subparsers.add_parser("pair-complete")
    verify_parser = subparsers.add_parser("enqueue-verification")
    verify_parser.add_argument("--surface", choices=["network"], required=True)
    flush_parser = subparsers.add_parser("flush")
    flush_parser.add_argument("--surface", choices=sorted(VALID_SURFACES))
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--surface", choices=sorted(VALID_SURFACES))
    args = parser.parse_args(argv)
    if args.command == "pair-begin":
        result = begin_pairing()
    elif args.command == "pair-complete":
        result = complete_pairing(json.load(sys.stdin))
    elif args.command == "enqueue-verification":
        result = enqueue_network_verification()
    elif args.command == "flush":
        result = flush_once(surface=args.surface)
    else:
        result = status(surface=args.surface)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") not in {"unavailable", "degraded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
