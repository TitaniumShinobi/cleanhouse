"""Versioned file-integrity projection for the CleanHouse Files product.

Baseline history is append-only.  ``baseline_entries`` is a rebuildable hot
projection; every mutation is represented by an immutable generation whose
chain hash commits to its predecessor and canonical delta.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "cleanhouse.file_integrity.v1"
_LOCK = threading.RLock()
_CHAIN_CACHE: tuple[str, str, float, dict[str, Any]] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _db_path() -> Path:
    configured = os.getenv("CLEANHOUSE_FILES_INTEGRITY_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    runtime_dir = Path(os.getenv("CLEANHOUSE_RUNTIME_DIR", Path.home() / ".cleanhouse" / "runtime")).expanduser()
    return runtime_dir / "files" / "integrity.db"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
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
    with _LOCK, _managed_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS baseline_generations (
                generation INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                provider TEXT NOT NULL,
                previous_chain_hash TEXT NOT NULL,
                chain_hash TEXT NOT NULL UNIQUE,
                state_root_hash TEXT NOT NULL,
                delta_json TEXT NOT NULL,
                checkpoint_json TEXT,
                entry_count INTEGER NOT NULL,
                evidence_refs_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS baseline_entries (
                path TEXT PRIMARY KEY,
                metadata_json TEXT NOT NULL,
                generation INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconciliation_receipts (
                receipt_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                state TEXT NOT NULL,
                chain_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS integrity_observations (
                source_event_key TEXT PRIMARY KEY,
                generation INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def normalize_entry(value: dict[str, Any]) -> dict[str, Any]:
    path = str(value.get("path") or "").strip()
    if not path:
        raise ValueError("integrity entry path is required")
    hashes = value.get("hashes") if isinstance(value.get("hashes"), dict) else {}
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    return {
        "path": path,
        "hashes": {
            key: str(hashes.get(key) or "")
            for key in ("sha256", "sha1", "md5")
            if str(hashes.get(key) or "")
        },
        "metadata": {
            key: metadata.get(key)
            for key in ("size", "mode", "uid", "gid", "owner", "group", "mtime", "inode", "file_type")
            if metadata.get(key) is not None
        },
        "observed_at": str(value.get("observed_at") or _now()),
        "provider": str(value.get("provider") or "unknown"),
        "evidence_refs": sorted({str(item) for item in value.get("evidence_refs", []) if str(item)}),
    }


def _load_entries(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        str(row["path"]): json.loads(row["metadata_json"])
        for row in conn.execute("SELECT path, metadata_json FROM baseline_entries ORDER BY path")
    }


def _latest_generation(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM baseline_generations ORDER BY generation DESC LIMIT 1").fetchone()
    return dict(row) if row is not None else {}


def _state_root(entries: dict[str, dict[str, Any]]) -> str:
    # A state root commits to file state, not collection time or transport
    # provenance. Those fields remain preserved in the immutable generation.
    return _digest(
        [
            {
                "path": path,
                "hashes": entries[path].get("hashes") or {},
                "metadata": entries[path].get("metadata") or {},
            }
            for path in sorted(entries)
        ]
    )


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    return _digest({
        "path": entry.get("path"),
        "hashes": entry.get("hashes") or {},
        "metadata": entry.get("metadata") or {},
    })


def _append_generation(
    conn: sqlite3.Connection,
    *,
    reason: str,
    provider: str,
    delta: dict[str, Any],
    checkpoint: dict[str, dict[str, Any]] | None,
    evidence_refs: list[str],
) -> dict[str, Any]:
    entries = _load_entries(conn)
    previous = _latest_generation(conn)
    previous_hash = str(previous.get("chain_hash") or "0" * 64)
    created_at = _now()
    state_root = _state_root(entries)
    chain_payload = {
        "schema": SCHEMA,
        "created_at": created_at,
        "reason": reason,
        "provider": provider,
        "previous_chain_hash": previous_hash,
        "state_root_hash": state_root,
        "delta": delta,
        "entry_count": len(entries),
        "evidence_refs": sorted(set(evidence_refs)),
    }
    chain_hash = _digest(chain_payload)
    cursor = conn.execute(
        """
        INSERT INTO baseline_generations (
            created_at, reason, provider, previous_chain_hash, chain_hash,
            state_root_hash, delta_json, checkpoint_json, entry_count, evidence_refs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            reason,
            provider,
            previous_hash,
            chain_hash,
            state_root,
            _canonical(delta),
            _canonical(checkpoint) if checkpoint is not None else None,
            len(entries),
            _canonical(sorted(set(evidence_refs))),
        ),
    )
    generation = int(cursor.lastrowid)
    conn.execute("UPDATE baseline_entries SET generation = ? WHERE generation = 0", (generation,))
    return {
        "generation": generation,
        "created_at": created_at,
        "provider": provider,
        "reason": reason,
        "root_hash": state_root,
        "chain_hash": chain_hash,
        "previous_chain_hash": previous_hash,
        "entry_count": len(entries),
        "checkpoint": checkpoint is not None,
    }


def observe(normalized_event: dict[str, Any], *, checkpoint_interval: int = 100) -> dict[str, Any]:
    operation = str(normalized_event.get("operation") or normalized_event.get("event_type") or "modified").lower()
    provider = str(normalized_event.get("provider") or "unknown")
    path = str(normalized_event.get("path") or "").strip()
    old_path = str(normalized_event.get("old_path") or "").strip()
    evidence_refs = [str(item) for item in normalized_event.get("evidence_refs", []) if str(item)]
    source_event_key = str(normalized_event.get("source_event_key") or "").strip()
    if not source_event_key:
        source_event_key = "integrity-observation:" + _digest(
            {
                "operation": operation,
                "path": path,
                "old_path": old_path,
                "hashes": normalized_event.get("hashes") or {},
                "metadata": normalized_event.get("metadata") or {},
                "evidence_refs": evidence_refs,
            }
        )
    if not path and operation not in {"deleted", "delete"}:
        raise ValueError("normalized integrity event path is required")
    init_db()
    with _LOCK, _managed_connection() as conn:
        existing = conn.execute(
            "SELECT generation FROM integrity_observations WHERE source_event_key = ?",
            (source_event_key,),
        ).fetchone()
        if existing is not None:
            row = conn.execute(
                "SELECT generation, created_at, provider, reason, state_root_hash, chain_hash, "
                "previous_chain_hash, entry_count, checkpoint_json "
                "FROM baseline_generations WHERE generation = ?",
                (int(existing["generation"]),),
            ).fetchone()
            if row is not None:
                result = dict(row)
                result["root_hash"] = result.pop("state_root_hash")
                result["checkpoint"] = result.pop("checkpoint_json") is not None
                result["replayed"] = True
                return result
        latest = _latest_generation(conn)
        next_generation = int(latest.get("generation") or 0) + 1
        delta: dict[str, Any] = {"operation": operation, "path": path}
        if old_path:
            delta["old_path"] = old_path
            conn.execute("DELETE FROM baseline_entries WHERE path = ?", (old_path,))
        if operation in {"deleted", "delete", "removed"}:
            conn.execute("DELETE FROM baseline_entries WHERE path = ?", (path,))
        else:
            entry = normalize_entry({**normalized_event, "path": path})
            delta["entry"] = entry
            conn.execute(
                """
                INSERT INTO baseline_entries (path, metadata_json, generation)
                VALUES (?, ?, 0)
                ON CONFLICT(path) DO UPDATE SET metadata_json = excluded.metadata_json, generation = 0
                """,
                (path, _canonical(entry)),
            )
        entries = _load_entries(conn)
        checkpoint = entries if next_generation == 1 or next_generation % max(1, checkpoint_interval) == 0 else None
        result = _append_generation(
            conn,
            reason="automatic_observation",
            provider=provider,
            delta=delta,
            checkpoint=checkpoint,
            evidence_refs=evidence_refs,
        )
        conn.execute(
            "INSERT INTO integrity_observations (source_event_key, generation, created_at) VALUES (?, ?, ?)",
            (source_event_key, result["generation"], result["created_at"]),
        )
        conn.commit()
        return result


def rebuild(
    inventory: Iterable[dict[str, Any]],
    *,
    provider: str,
    reason: str = "full_rebuild",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    normalized = {entry["path"]: entry for entry in (normalize_entry(item) for item in inventory)}
    init_db()
    with _LOCK, _managed_connection() as conn:
        conn.execute("DELETE FROM baseline_entries")
        for path, entry in normalized.items():
            conn.execute(
                "INSERT INTO baseline_entries (path, metadata_json, generation) VALUES (?, ?, 0)",
                (path, _canonical(entry)),
            )
        result = _append_generation(
            conn,
            reason=reason,
            provider=provider,
            delta={"operation": "rebuild", "paths": len(normalized)},
            checkpoint=normalized,
            evidence_refs=evidence_refs or [],
        )
        conn.commit()
        return result


def reconcile(inventory: Iterable[dict[str, Any]], *, provider: str) -> dict[str, Any]:
    observed = {entry["path"]: entry for entry in (normalize_entry(item) for item in inventory)}
    init_db()
    with _LOCK, _managed_connection() as conn:
        baseline = _load_entries(conn)
        missing = sorted(set(baseline) - set(observed))
        added = sorted(set(observed) - set(baseline))
        changed = sorted(
            path for path in set(baseline).intersection(observed)
            if _entry_fingerprint(baseline[path]) != _entry_fingerprint(observed[path])
        )
        created_at = _now()
        payload = {
            "schema": "cleanhouse.file_reconciliation.v1",
            "reconciled_at": created_at,
            "provider": provider,
            "baseline_generation": int((_latest_generation(conn).get("generation") or 0)),
            "checked": len(observed),
            "present": len(observed) - len(added),
            "missing": len(missing),
            "added": len(added),
            "changed": len(changed),
            "unavailable": 0,
            "discrepancies": (missing + added + changed)[:200],
            "details": {"missing": missing[:200], "added": added[:200], "changed": changed[:200]},
        }
        receipt_id = "files-reconcile-" + uuid.uuid4().hex
        previous = conn.execute(
            "SELECT chain_hash FROM reconciliation_receipts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        previous_hash = str(previous[0]) if previous else "0" * 64
        payload["previous_receipt_hash"] = previous_hash
        receipt_hash = _digest({"previous": previous_hash, "payload": payload})
        conn.execute(
            "INSERT INTO reconciliation_receipts VALUES (?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                created_at,
                provider,
                "drift" if missing or added or changed else "matched",
                receipt_hash,
                _canonical(payload),
            ),
        )
        conn.commit()
    generation = rebuild(
        observed.values(),
        provider=provider,
        reason="automatic_reconciliation",
        evidence_refs=[receipt_id],
    )
    return {
        **payload,
        "receipt_id": receipt_id,
        "receipt_hash": receipt_hash,
        "advanced_generation": generation["generation"],
    }


def verify_chain(*, force: bool = False) -> dict[str, Any]:
    global _CHAIN_CACHE
    init_db()
    with _LOCK, _managed_connection() as conn:
        rows = conn.execute("SELECT * FROM baseline_generations ORDER BY generation").fetchall()
        latest_hash = str(rows[-1]["chain_hash"]) if rows else ""
        db_key = str(_db_path().expanduser().resolve())
        if (
            not force
            and _CHAIN_CACHE is not None
            and _CHAIN_CACHE[0] == db_key
            and _CHAIN_CACHE[1] == latest_hash
            and _CHAIN_CACHE[2] > time.monotonic()
        ):
            return dict(_CHAIN_CACHE[3])
        previous = "0" * 64
        for row in rows:
            payload = {
                "schema": SCHEMA,
                "created_at": row["created_at"],
                "reason": row["reason"],
                "provider": row["provider"],
                "previous_chain_hash": row["previous_chain_hash"],
                "state_root_hash": row["state_root_hash"],
                "delta": json.loads(row["delta_json"]),
                "entry_count": int(row["entry_count"]),
                "evidence_refs": json.loads(row["evidence_refs_json"]),
            }
            if row["previous_chain_hash"] != previous:
                result = {
                    "state": "degraded",
                    "valid": False,
                    "generations_checked": int(row["generation"]) - 1,
                    "first_error": f"generation {row['generation']} previous hash mismatch",
                }
                _CHAIN_CACHE = (db_key, latest_hash, time.monotonic() + 5.0, result)
                return dict(result)
            if _digest(payload) != row["chain_hash"]:
                result = {
                    "state": "degraded",
                    "valid": False,
                    "generations_checked": int(row["generation"]) - 1,
                    "first_error": f"generation {row['generation']} chain hash mismatch",
                }
                _CHAIN_CACHE = (db_key, latest_hash, time.monotonic() + 5.0, result)
                return dict(result)
            if row["checkpoint_json"]:
                checkpoint = json.loads(row["checkpoint_json"])
                if _state_root(checkpoint) != row["state_root_hash"] or len(checkpoint) != int(row["entry_count"]):
                    result = {
                        "state": "degraded",
                        "valid": False,
                        "generations_checked": int(row["generation"]) - 1,
                        "first_error": f"generation {row['generation']} checkpoint mismatch",
                    }
                    _CHAIN_CACHE = (db_key, latest_hash, time.monotonic() + 5.0, result)
                    return dict(result)
            previous = str(row["chain_hash"])
        result = {
            "state": "verified" if rows else "no_data",
            "valid": True,
            "generations_checked": len(rows),
            "first_error": "",
        }
        _CHAIN_CACHE = (db_key, latest_hash, time.monotonic() + 5.0, result)
        return dict(result)


def verify_reconciliation_receipts() -> dict[str, Any]:
    init_db()
    with _LOCK, _managed_connection() as conn:
        rows = conn.execute("SELECT * FROM reconciliation_receipts ORDER BY rowid").fetchall()
        previous = "0" * 64
        for index, row in enumerate(rows, start=1):
            payload = json.loads(row["payload_json"])
            if payload.get("previous_receipt_hash") != previous:
                return {
                    "state": "degraded",
                    "valid": False,
                    "receipts_checked": index - 1,
                    "first_error": f"receipt {row['receipt_id']} previous hash mismatch",
                }
            expected = _digest({"previous": previous, "payload": payload})
            if expected != row["chain_hash"]:
                return {
                    "state": "degraded",
                    "valid": False,
                    "receipts_checked": index - 1,
                    "first_error": f"receipt {row['receipt_id']} hash mismatch",
                }
            previous = str(row["chain_hash"])
        return {
            "state": "verified" if rows else "no_data",
            "valid": True,
            "receipts_checked": len(rows),
            "first_error": "",
        }


def snapshot() -> dict[str, Any]:
    init_db()
    with _LOCK, _managed_connection() as conn:
        latest = _latest_generation(conn)
        receipt = conn.execute(
            "SELECT receipt_id, created_at, provider, state, chain_hash, payload_json "
            "FROM reconciliation_receipts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        latest_receipt = {}
        if receipt is not None:
            latest_receipt = dict(receipt)
            latest_receipt["payload"] = json.loads(latest_receipt.pop("payload_json"))
        result = {
            "schema": SCHEMA,
            "state": "observed" if latest else "no_data",
            "authorization_state": "not_evaluated_until_zaelith",
            "generation": int(latest.get("generation") or 0),
            "root_hash": str(latest.get("state_root_hash") or ""),
            "chain_hash": str(latest.get("chain_hash") or ""),
            "checkpoint_at": str(latest.get("created_at") or ""),
            "entry_count": int(latest.get("entry_count") or 0),
            "provider": str(latest.get("provider") or ""),
            "last_reconciliation": latest_receipt,
        }
    result["chain_verification"] = verify_chain()
    result["reconciliation_chain_verification"] = verify_reconciliation_receipts()
    if not result["chain_verification"]["valid"] or not result["reconciliation_chain_verification"]["valid"]:
        result["state"] = "degraded"
    return result
