"""Durable, device-local authentication state for CleanHouse.

The sharded user registry remains the identity authority.  This module stores
only authentication state that must survive browser, CleanHouse, and macOS
restarts.  Browser/API secrets are returned once and are represented in SQLite
only by SHA-256 digests.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


SESSION_ABSOLUTE_LIFETIME = timedelta(days=30)
SESSION_IDLE_LIFETIME = timedelta(days=7)
SESSION_ROTATION_INTERVAL = timedelta(days=1)
MAGIC_CHALLENGE_LIFETIME = timedelta(minutes=15)
API_TOKEN_DEFAULT_LIFETIME = timedelta(days=30)
API_TOKEN_MAX_LIFETIME = timedelta(days=90)
REAUTH_LIFETIME = timedelta(minutes=10)
LAST_USE_WRITE_INTERVAL = timedelta(minutes=5)
MAX_METADATA_BYTES = 16 * 1024
MAX_LIST_LIMIT = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    value = value or _utcnow()
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("stored timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _digest(secret: str) -> str:
    if not isinstance(secret, str) or len(secret) < 20:
        raise ValueError("secret is malformed")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _json(value: Mapping[str, Any] | None) -> str:
    encoded = json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError("metadata exceeds the bounded storage limit")
    return encoded


def _secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class IssuedCredential:
    id: str
    secret: str
    expires_at: str
    display_prefix: str | None = None


@dataclass(frozen=True)
class CredentialResult:
    status: str
    record: dict[str, Any] | None = None
    replacement: IssuedCredential | None = None


class AuthStore:
    """Small SQLite authority for revocable local authentication state."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = os.getenv("CLEANHOUSE_AUTH_DB", "").strip()
        self.path = Path(path or configured or Path.home() / ".cleanhouse" / "auth" / "auth.sqlite3").expanduser()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 3000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_sessions (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    auth_method TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    last_rotated_at TEXT NOT NULL,
                    idle_expires_at TEXT NOT NULL,
                    absolute_expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    replaced_by_session_id TEXT,
                    legacy_migrated INTEGER NOT NULL DEFAULT 0 CHECK (legacy_migrated IN (0,1)),
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON device_sessions(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS session_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_session_events_user ON session_events(user_id, event_id DESC);

                CREATE TABLE IF NOT EXISTS consent_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    document TEXT NOT NULL,
                    document_digest TEXT NOT NULL,
                    acceptance_method TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    UNIQUE(user_id, document, document_digest, transaction_id)
                );
                CREATE INDEX IF NOT EXISTS idx_consent_user ON consent_receipts(user_id, document, accepted_at DESC);

                CREATE TABLE IF NOT EXISTS magic_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT,
                    normalized_email TEXT NOT NULL,
                    intent TEXT NOT NULL CHECK (intent IN ('signin','signup')),
                    purpose TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_challenges(normalized_email, created_at DESC);

                CREATE TABLE IF NOT EXISTS external_identity_bindings (
                    binding_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_subject TEXT NOT NULL,
                    verified_email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(provider, provider_subject),
                    UNIQUE(user_id, provider)
                );

                CREATE TABLE IF NOT EXISTS api_tokens (
                    token_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    display_prefix TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at TEXT,
                    replaced_by_token_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS reauth_grants (
                    grant_id TEXT PRIMARY KEY,
                    grant_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pending_enrollments (
                    enrollment_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    normalized_email TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TRIGGER IF NOT EXISTS session_events_no_update
                BEFORE UPDATE ON session_events BEGIN SELECT RAISE(ABORT, 'session events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS session_events_no_delete
                BEFORE DELETE ON session_events BEGIN SELECT RAISE(ABORT, 'session events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS consent_receipts_no_update
                BEFORE UPDATE ON consent_receipts BEGIN SELECT RAISE(ABORT, 'consent receipts are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS consent_receipts_no_delete
                BEFORE DELETE ON consent_receipts BEGIN SELECT RAISE(ABORT, 'consent receipts are append-only'); END;
                PRAGMA user_version = 1;
                """
            )
        if self.path.exists():
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        event_type: str,
        occurred_at: datetime,
        session_id: str | None = None,
        transaction_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO session_events(session_id,user_id,event_type,occurred_at,transaction_id,data_json) "
            "VALUES(?,?,?,?,?,?)",
            (session_id, user_id, event_type, _iso(occurred_at), transaction_id or str(uuid.uuid4()), _json(data)),
        )

    def issue_session(
        self,
        user_id: str,
        *,
        auth_method: str,
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        legacy_migrated: bool = False,
    ) -> IssuedCredential:
        now = _as_utc(now)
        raw = _secret("chs_")
        session_id = str(uuid.uuid4())
        absolute = now + SESSION_ABSOLUTE_LIFETIME
        idle = min(now + SESSION_IDLE_LIFETIME, absolute)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO device_sessions(id,token_hash,user_id,auth_method,created_at,last_used_at,"
                "last_rotated_at,idle_expires_at,absolute_expires_at,legacy_migrated,metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id, _digest(raw), user_id, auth_method, _iso(now), _iso(now), _iso(now),
                    _iso(idle), _iso(absolute), int(legacy_migrated), _json(metadata),
                ),
            )
            self._event(connection, user_id=user_id, event_type="session_issued", occurred_at=now,
                        session_id=session_id, data={"auth_method": auth_method, "legacy_migrated": legacy_migrated})
        return IssuedCredential(session_id, raw, _iso(absolute))

    def _session_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "user_id": row["user_id"], "auth_method": row["auth_method"],
            "created_at": row["created_at"], "last_used_at": row["last_used_at"],
            "last_rotated_at": row["last_rotated_at"], "idle_expires_at": row["idle_expires_at"],
            "absolute_expires_at": row["absolute_expires_at"], "revoked_at": row["revoked_at"],
            "replaced_by_session_id": row["replaced_by_session_id"],
            "legacy_migrated": bool(row["legacy_migrated"]), "metadata": json.loads(row["metadata_json"]),
        }

    def validate_session(
        self, raw: str, *, now: datetime | None = None, rotate_if_due: bool = True
    ) -> CredentialResult:
        now = _as_utc(now)
        try:
            token_hash = _digest(raw)
        except ValueError:
            return CredentialResult("malformed")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM device_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
            if row is None:
                return CredentialResult("unknown")
            record = self._session_record(row)
            if row["revoked_at"] is not None:
                return CredentialResult("replayed" if row["replaced_by_session_id"] else "revoked", record)
            if _parse(row["absolute_expires_at"]) <= now or _parse(row["idle_expires_at"]) <= now:
                connection.execute("UPDATE device_sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                                   (_iso(now), row["id"]))
                self._event(connection, user_id=row["user_id"], event_type="session_expired", occurred_at=now,
                            session_id=row["id"])
                record["revoked_at"] = _iso(now)
                return CredentialResult("expired", record)
            if rotate_if_due and _parse(row["last_rotated_at"]) + SESSION_ROTATION_INTERVAL <= now:
                return self._rotate_session_in_transaction(connection, row, now)
            if _parse(row["last_used_at"]) + LAST_USE_WRITE_INTERVAL <= now:
                idle = min(now + SESSION_IDLE_LIFETIME, _parse(row["absolute_expires_at"]))
                connection.execute(
                    "UPDATE device_sessions SET last_used_at = ?, idle_expires_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (_iso(now), _iso(idle), row["id"]),
                )
                record["last_used_at"], record["idle_expires_at"] = _iso(now), _iso(idle)
            return CredentialResult("valid", record)

    def refresh_session(self, raw: str, *, now: datetime | None = None) -> CredentialResult:
        now = _as_utc(now)
        try:
            token_hash = _digest(raw)
        except ValueError:
            return CredentialResult("malformed")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM device_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
            if row is None:
                return CredentialResult("unknown")
            if row["revoked_at"] is not None:
                return CredentialResult("replayed" if row["replaced_by_session_id"] else "revoked", self._session_record(row))
            if _parse(row["absolute_expires_at"]) <= now or _parse(row["idle_expires_at"]) <= now:
                connection.execute("UPDATE device_sessions SET revoked_at = ? WHERE id = ?", (_iso(now), row["id"]))
                self._event(connection, user_id=row["user_id"], event_type="session_expired", occurred_at=now,
                            session_id=row["id"])
                return CredentialResult("expired", self._session_record(row))
            return self._rotate_session_in_transaction(connection, row, now)

    def _rotate_session_in_transaction(
        self, connection: sqlite3.Connection, old: sqlite3.Row, now: datetime
    ) -> CredentialResult:
        raw = _secret("chs_")
        new_id = str(uuid.uuid4())
        absolute = _parse(old["absolute_expires_at"])
        idle = min(now + SESSION_IDLE_LIFETIME, absolute)
        inserted = connection.execute(
            "INSERT INTO device_sessions(id,token_hash,user_id,auth_method,created_at,last_used_at,last_rotated_at,"
            "idle_expires_at,absolute_expires_at,legacy_migrated,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, _digest(raw), old["user_id"], old["auth_method"], old["created_at"], _iso(now), _iso(now),
             _iso(idle), _iso(absolute), old["legacy_migrated"], old["metadata_json"]),
        )
        updated = connection.execute(
            "UPDATE device_sessions SET revoked_at = ?, replaced_by_session_id = ? WHERE id = ? AND revoked_at IS NULL",
            (_iso(now), new_id, old["id"]),
        )
        if inserted.rowcount != 1 or updated.rowcount != 1:
            raise sqlite3.IntegrityError("session rotation lost atomic ownership")
        self._event(connection, user_id=old["user_id"], event_type="session_rotated", occurred_at=now,
                    session_id=old["id"], data={"replacement_session_id": new_id})
        new_row = connection.execute("SELECT * FROM device_sessions WHERE id = ?", (new_id,)).fetchone()
        return CredentialResult("rotated", self._session_record(new_row), IssuedCredential(new_id, raw, _iso(absolute)))

    def revoke_session(self, session_id: str, user_id: str, *, now: datetime | None = None) -> bool:
        now = _as_utc(now)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE device_sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                (_iso(now), session_id, user_id),
            )
            if changed.rowcount:
                self._event(connection, user_id=user_id, event_type="session_revoked", occurred_at=now,
                            session_id=session_id)
            return changed.rowcount == 1

    def revoke_other_sessions(self, user_id: str, current_session_id: str, *, now: datetime | None = None) -> int:
        now = _as_utc(now)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM device_sessions WHERE user_id = ? AND id != ? AND revoked_at IS NULL",
                (user_id, current_session_id),
            ).fetchall()
            for row in rows:
                connection.execute("UPDATE device_sessions SET revoked_at = ? WHERE id = ?", (_iso(now), row["id"]))
                self._event(connection, user_id=user_id, event_type="session_revoked", occurred_at=now,
                            session_id=row["id"], data={"reason": "revoke_others"})
            return len(rows)

    def revoke_all_sessions(self, user_id: str, *, now: datetime | None = None, reason: str = "security_event") -> int:
        now = _as_utc(now)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM device_sessions WHERE user_id = ? AND revoked_at IS NULL", (user_id,)
            ).fetchall()
            for row in rows:
                connection.execute("UPDATE device_sessions SET revoked_at = ? WHERE id = ?", (_iso(now), row["id"]))
                self._event(connection, user_id=user_id, event_type="session_revoked", occurred_at=now,
                            session_id=row["id"], data={"reason": reason})
            return len(rows)

    def list_sessions(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM device_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        return [self._session_record(row) for row in rows]

    def record_consent(
        self, user_id: str, document: str, document_digest: str, acceptance_method: str, *,
        transaction_id: str, now: datetime | None = None
    ) -> str:
        now = _as_utc(now)
        if len(document_digest) != 64 or any(c not in "0123456789abcdef" for c in document_digest.lower()):
            raise ValueError("document digest must be SHA-256 hex")
        receipt_id = str(uuid.uuid4())
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO consent_receipts(receipt_id,user_id,document,document_digest,acceptance_method,"
                "accepted_at,transaction_id) VALUES(?,?,?,?,?,?,?)",
                (receipt_id, user_id, document, document_digest.lower(), acceptance_method, _iso(now), transaction_id),
            )
        return receipt_id

    def consent_status(self, user_id: str, required: Mapping[str, str]) -> dict[str, Any]:
        accepted: dict[str, str] = {}
        with self._connection() as connection:
            for document, digest in required.items():
                row = connection.execute(
                    "SELECT document_digest,accepted_at FROM consent_receipts WHERE user_id = ? AND document = ? "
                    "AND document_digest = ? ORDER BY accepted_at DESC LIMIT 1",
                    (user_id, document, digest.lower()),
                ).fetchone()
                if row:
                    accepted[document] = row["accepted_at"]
        missing = sorted(set(required) - set(accepted))
        return {"current": not missing, "accepted": accepted, "missing": missing}

    def issue_magic_challenge(
        self, email: str, *, intent: str, purpose: str, origin: str, user_id: str | None = None,
        metadata: Mapping[str, Any] | None = None, now: datetime | None = None
    ) -> IssuedCredential:
        if intent not in {"signin", "signup"}:
            raise ValueError("magic challenge intent must be signin or signup")
        now = _as_utc(now)
        raw = _secret("chm_")
        challenge_id, expires = str(uuid.uuid4()), now + MAGIC_CHALLENGE_LIFETIME
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO magic_challenges(challenge_id,token_hash,user_id,normalized_email,intent,purpose,origin,"
                "created_at,expires_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (challenge_id, _digest(raw), user_id, email.strip().lower(), intent, purpose, origin, _iso(now),
                 _iso(expires), _json(metadata)),
            )
        return IssuedCredential(challenge_id, raw, _iso(expires))

    def recent_magic_challenge_count(
        self, email: str, *, since: datetime, intent: str | None = None
    ) -> int:
        since = _as_utc(since)
        query = "SELECT COUNT(*) FROM magic_challenges WHERE normalized_email = ? AND created_at >= ?"
        values: list[Any] = [email.strip().lower(), _iso(since)]
        if intent:
            query += " AND intent = ?"
            values.append(intent)
        with self._connection() as connection:
            row = connection.execute(query, values).fetchone()
        return int(row[0] if row else 0)

    def revoke_magic_challenge(self, challenge_id: str, *, now: datetime | None = None) -> bool:
        now = _as_utc(now)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE magic_challenges SET revoked_at = ? WHERE challenge_id = ? AND consumed_at IS NULL "
                "AND revoked_at IS NULL", (_iso(now), challenge_id)
            )
            return changed.rowcount == 1

    def consume_magic_challenge(
        self, raw: str, *, purpose: str, origin: str, now: datetime | None = None
    ) -> CredentialResult:
        now = _as_utc(now)
        try:
            digest = _digest(raw)
        except ValueError:
            return CredentialResult("malformed")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM magic_challenges WHERE token_hash = ?", (digest,)).fetchone()
            if row is None:
                return CredentialResult("unknown")
            record = {key: row[key] for key in ("challenge_id", "user_id", "normalized_email", "intent", "purpose", "origin")}
            record["metadata"] = json.loads(row["metadata_json"])
            if row["consumed_at"] is not None:
                return CredentialResult("replayed", record)
            if row["revoked_at"] is not None:
                return CredentialResult("revoked", record)
            if _parse(row["expires_at"]) <= now:
                return CredentialResult("expired", record)
            if not secrets.compare_digest(row["purpose"], purpose) or not secrets.compare_digest(row["origin"], origin):
                return CredentialResult("binding_mismatch")
            changed = connection.execute(
                "UPDATE magic_challenges SET consumed_at = ? WHERE challenge_id = ? AND consumed_at IS NULL "
                "AND revoked_at IS NULL", (_iso(now), row["challenge_id"])
            )
            if changed.rowcount != 1:
                return CredentialResult("replayed", record)
            return CredentialResult("consumed", record)

    def bind_external_identity(
        self, user_id: str, provider: str, provider_subject: str, *, verified_email: str | None = None,
        now: datetime | None = None
    ) -> str:
        now = _as_utc(now)
        binding_id = str(uuid.uuid4())
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM external_identity_bindings WHERE provider = ? AND provider_subject = ?",
                (provider, provider_subject),
            ).fetchone()
            if existing:
                if existing["user_id"] != user_id:
                    raise ValueError("provider identity is already bound to another user")
                return existing["binding_id"]
            connection.execute(
                "INSERT INTO external_identity_bindings(binding_id,user_id,provider,provider_subject,verified_email,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (binding_id, user_id, provider, provider_subject, verified_email.lower() if verified_email else None,
                 _iso(now), _iso(now)),
            )
        return binding_id

    def external_identity(self, provider: str, provider_subject: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM external_identity_bindings WHERE provider = ? AND provider_subject = ?",
                (provider, provider_subject),
            ).fetchone()
        return dict(row) if row else None

    def list_external_identities(self, user_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM external_identity_bindings WHERE user_id = ? ORDER BY provider", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def unbind_external_identity(self, user_id: str, provider: str) -> bool:
        with self._transaction() as connection:
            changed = connection.execute(
                "DELETE FROM external_identity_bindings WHERE user_id = ? AND provider = ?", (user_id, provider)
            )
            return changed.rowcount == 1

    def issue_api_token(
        self, user_id: str, *, label: str, lifetime_days: int = 30,
        metadata: Mapping[str, Any] | None = None, now: datetime | None = None
    ) -> IssuedCredential:
        if not 1 <= int(lifetime_days) <= API_TOKEN_MAX_LIFETIME.days:
            raise ValueError("API token lifetime must be between 1 and 90 days")
        now = _as_utc(now)
        raw = _secret("chpat_")
        token_id, expires = str(uuid.uuid4()), now + timedelta(days=int(lifetime_days))
        display = raw[:12]
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO api_tokens(token_id,token_hash,user_id,display_prefix,label,created_at,expires_at,"
                "metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                (token_id, _digest(raw), user_id, display, label[:120], _iso(now), _iso(expires), _json(metadata)),
            )
        return IssuedCredential(token_id, raw, _iso(expires), display)

    def validate_api_token(self, raw: str, *, now: datetime | None = None) -> CredentialResult:
        now = _as_utc(now)
        try:
            digest = _digest(raw)
        except ValueError:
            return CredentialResult("malformed")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM api_tokens WHERE token_hash = ?", (digest,)).fetchone()
            if row is None:
                return CredentialResult("unknown")
            record = {key: row[key] for key in row.keys() if key not in {"token_hash", "metadata_json"}}
            record["metadata"] = json.loads(row["metadata_json"])
            if row["revoked_at"] is not None:
                return CredentialResult("replayed" if row["replaced_by_token_id"] else "revoked", record)
            if _parse(row["expires_at"]) <= now:
                connection.execute("UPDATE api_tokens SET revoked_at = ? WHERE token_id = ?", (_iso(now), row["token_id"]))
                record["revoked_at"] = _iso(now)
                return CredentialResult("expired", record)
            if row["last_used_at"] is None or _parse(row["last_used_at"]) + LAST_USE_WRITE_INTERVAL <= now:
                connection.execute("UPDATE api_tokens SET last_used_at = ? WHERE token_id = ?", (_iso(now), row["token_id"]))
                record["last_used_at"] = _iso(now)
            return CredentialResult("valid", record)

    def rotate_api_token(self, token_id: str, user_id: str, *, now: datetime | None = None) -> IssuedCredential | None:
        now = _as_utc(now)
        with self._transaction() as connection:
            old = connection.execute(
                "SELECT * FROM api_tokens WHERE token_id = ? AND user_id = ? AND revoked_at IS NULL", (token_id, user_id)
            ).fetchone()
            if not old:
                return None
            raw, new_id = _secret("chpat_"), str(uuid.uuid4())
            remaining = max(timedelta(seconds=1), _parse(old["expires_at"]) - now)
            expires = now + min(remaining, API_TOKEN_DEFAULT_LIFETIME)
            display = raw[:12]
            connection.execute(
                "INSERT INTO api_tokens(token_id,token_hash,user_id,display_prefix,label,created_at,expires_at,"
                "metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                (new_id, _digest(raw), user_id, display, old["label"], _iso(now), _iso(expires), old["metadata_json"]),
            )
            changed = connection.execute(
                "UPDATE api_tokens SET revoked_at = ?, replaced_by_token_id = ? WHERE token_id = ? AND revoked_at IS NULL",
                (_iso(now), new_id, token_id),
            )
            if changed.rowcount != 1:
                raise sqlite3.IntegrityError("API token rotation lost atomic ownership")
            return IssuedCredential(new_id, raw, _iso(expires), display)

    def revoke_api_token(self, token_id: str, user_id: str, *, now: datetime | None = None) -> bool:
        now = _as_utc(now)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE api_tokens SET revoked_at = ? WHERE token_id = ? AND user_id = ? AND revoked_at IS NULL",
                (_iso(now), token_id, user_id),
            )
            return changed.rowcount == 1

    def list_api_tokens(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT token_id,user_id,display_prefix,label,created_at,expires_at,last_used_at,revoked_at,"
                "replaced_by_token_id FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def issue_reauth_grant(
        self, user_id: str, session_id: str, scope: str, *, now: datetime | None = None
    ) -> IssuedCredential:
        now = _as_utc(now)
        raw, grant_id, expires = _secret("chr_"), str(uuid.uuid4()), now + REAUTH_LIFETIME
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO reauth_grants(grant_id,grant_hash,user_id,session_id,scope,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (grant_id, _digest(raw), user_id, session_id, scope, _iso(now), _iso(expires)),
            )
        return IssuedCredential(grant_id, raw, _iso(expires))

    def consume_reauth_grant(
        self, raw: str, *, user_id: str, session_id: str, scope: str, now: datetime | None = None
    ) -> bool:
        now = _as_utc(now)
        try:
            digest = _digest(raw)
        except ValueError:
            return False
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM reauth_grants WHERE grant_hash = ?", (digest,)).fetchone()
            if not row or row["consumed_at"] or row["revoked_at"] or _parse(row["expires_at"]) <= now:
                return False
            if not (secrets.compare_digest(row["user_id"], user_id)
                    and secrets.compare_digest(row["session_id"], session_id)
                    and secrets.compare_digest(row["scope"], scope)):
                return False
            changed = connection.execute(
                "UPDATE reauth_grants SET consumed_at = ? WHERE grant_id = ? AND consumed_at IS NULL",
                (_iso(now), row["grant_id"]),
            )
            return changed.rowcount == 1

    def issue_pending_enrollment(
        self, kind: str, *, email: str | None = None, payload: Mapping[str, Any] | None = None,
        lifetime: timedelta = MAGIC_CHALLENGE_LIFETIME, now: datetime | None = None
    ) -> IssuedCredential:
        now = _as_utc(now)
        raw, enrollment_id, expires = _secret("che_"), str(uuid.uuid4()), now + lifetime
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO pending_enrollments(enrollment_id,token_hash,kind,normalized_email,created_at,expires_at,"
                "payload_json) VALUES(?,?,?,?,?,?,?)",
                (enrollment_id, _digest(raw), kind, email.strip().lower() if email else None, _iso(now), _iso(expires),
                 _json(payload)),
            )
        return IssuedCredential(enrollment_id, raw, _iso(expires))

    def consume_pending_enrollment(
        self, raw: str, *, kind: str, now: datetime | None = None
    ) -> CredentialResult:
        now = _as_utc(now)
        try:
            digest = _digest(raw)
        except ValueError:
            return CredentialResult("malformed")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM pending_enrollments WHERE token_hash = ?", (digest,)).fetchone()
            if not row:
                return CredentialResult("unknown")
            record = {"id": row["enrollment_id"], "kind": row["kind"], "email": row["normalized_email"],
                      "payload": json.loads(row["payload_json"])}
            if row["consumed_at"]:
                return CredentialResult("replayed", record)
            if row["revoked_at"]:
                return CredentialResult("revoked", record)
            if _parse(row["expires_at"]) <= now:
                return CredentialResult("expired", record)
            if not secrets.compare_digest(row["kind"], kind):
                return CredentialResult("binding_mismatch")
            changed = connection.execute(
                "UPDATE pending_enrollments SET consumed_at = ? WHERE enrollment_id = ? AND consumed_at IS NULL",
                (_iso(now), row["enrollment_id"]),
            )
            return CredentialResult("consumed" if changed.rowcount == 1 else "replayed", record)


def get_auth_store(path: str | Path | None = None) -> AuthStore:
    """Construct the store from the current runtime configuration."""

    return AuthStore(path)
