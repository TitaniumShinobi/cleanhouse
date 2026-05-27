"""
Filesystem event persistence and optional watcher runtime for CleanHouse.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:
    FileSystemEventHandler = None
    Observer = None

DEFAULT_SESSION_ID = "default-session"
DEFAULT_DB_NAME = "events.db"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / DEFAULT_DB_NAME
DEFAULT_WATCH_DIR = REPO_ROOT
DEFAULT_RECEIPT_WINDOW_SECONDS = 120
DEFAULT_OBJECTIVE_PATH_PREFIX = "/objectives/"

_WATCHER_LOCK = threading.Lock()
_DB_LOCK = threading.Lock()
_WRITER_LOCK = threading.Lock()
_WATCHER_STATE: dict[str, Any] = {
    "observer": None,
    "watch_dir": None,
    "last_error": None,
}
_EVENT_QUEUE: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=2000)
_WRITER_STATE: dict[str, Any] = {"thread": None, "queue": _EVENT_QUEUE, "last_error": None}
_WRITER_STOP_TOKEN = object()
_WRITER_STOP_EVENT = threading.Event()
_WRITER_STATS: dict[str, int] = {
    "enqueued": 0,
    "written": 0,
    "dropped": 0,
    "max_depth": 0,
    "write_retries": 0,
    "write_failures": 0,
}

_DB_CONNECT_TIMEOUT_SECONDS = 5.0
_DB_BUSY_TIMEOUT_MS = 2000
_DB_RETRY_LIMIT = 5
_DB_RETRY_DELAY_SECONDS = 0.05

_RECEIPT_EVENT_TYPES = {
    "prompt_event",
    "shell_event",
    "process_event",
    "tool_event",
    "created",
    "modified",
    "deleted",
    "objective_start",
    "objective_end",
    "approval_requested",
    "approval_resolved",
    "session_started",
    "scope_drift_detected",
    "approval_required",
    "receipt_finalized",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
}

_EVENT_JSON_FIELDS = {"observed_vs_expected", "evidence_refs", "data"}
_EVENT_METADATA_COLUMNS: dict[str, str] = {
    "objective_id": "TEXT",
    "source_surface": "TEXT",
    "actor_type": "TEXT",
    "evidence_level": "TEXT",
    "observed_vs_expected": "TEXT NOT NULL DEFAULT '{}'",
    "collector_status": "TEXT",
    "scope_relation": "TEXT",
    "evidence_refs": "TEXT NOT NULL DEFAULT '[]'",
    "raw_evidence_ref": "TEXT",
    "data": "TEXT NOT NULL DEFAULT '{}'",
}
_EVENT_DEFAULTS: dict[str, Any] = {
    "objective_id": None,
    "source_surface": None,
    "actor_type": None,
    "evidence_level": None,
    "observed_vs_expected": {},
    "collector_status": None,
    "scope_relation": None,
    "evidence_refs": [],
    "raw_evidence_ref": None,
    "data": {},
}


def _record_writer_metric(name: str, increment: int = 1) -> None:
    if increment <= 0:
        return
    with _WRITER_LOCK:
        _WRITER_STATS[name] = _WRITER_STATS.get(name, 0) + increment


def _track_queue_depth() -> None:
    with _WRITER_LOCK:
        depth = _EVENT_QUEUE.qsize()
        if depth > _WRITER_STATS["max_depth"]:
            _WRITER_STATS["max_depth"] = depth


def _resolve_db_path() -> Path:
    raw = os.getenv("CLEANHOUSE_EVENTS_DB")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_DB_PATH


def _ensure_db_directory(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=_DB_CONNECT_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {_DB_BUSY_TIMEOUT_MS}")
    return conn


def _now_iso_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _runtime_error_payload(source: str, exc: BaseException | str, **metadata: Any) -> dict[str, Any]:
    if isinstance(exc, BaseException):
        error_type = exc.__class__.__name__
        message = str(exc) or error_type
    else:
        error_type = "RuntimeError"
        message = str(exc)
    payload = {
        "source": source,
        "error_type": error_type,
        "message": message,
        "timestamp": _now_iso_timestamp(),
    }
    payload.update({key: value for key, value in metadata.items() if value is not None})
    return payload


def _record_watcher_error(source: str, exc: BaseException | str, **metadata: Any) -> None:
    with _WATCHER_LOCK:
        _WATCHER_STATE["last_error"] = _runtime_error_payload(source, exc, **metadata)


def record_event_write_failure(source: str, exc: BaseException | str, **metadata: Any) -> None:
    _record_writer_metric("write_failures")
    with _WRITER_LOCK:
        _WRITER_STATE["last_error"] = _runtime_error_payload(source, exc, **metadata)


def _run_with_retries(operation, db_path: Path, *, on_retry=None):
    last_exc: Exception | None = None
    for attempt in range(1, _DB_RETRY_LIMIT + 1):
        try:
            with _DB_LOCK:
                conn = _connect(db_path)
                try:
                    result = operation(conn)
                    conn.commit()
                    return result
                finally:
                    conn.close()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower() or attempt >= _DB_RETRY_LIMIT:
                break
            if callable(on_retry):
                on_retry()
            _record_writer_metric("write_retries")
            time.sleep(_DB_RETRY_DELAY_SECONDS * attempt)
        except Exception as exc:
            last_exc = exc
            break

    raise RuntimeError(f"sqlite operation failed: {last_exc}") from last_exc


def _configure_db(db_path: Path) -> None:
    def _set_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

    _run_with_retries(_set_pragmas, db_path)


def _ensure_receipt_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(receipts)").fetchall()
    }
    if "objective_id" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN objective_id TEXT")
    if "event_count" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN event_count INTEGER NOT NULL DEFAULT 0")
    if "shell_event_count" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN shell_event_count INTEGER NOT NULL DEFAULT 0")
    if "process_event_count" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN process_event_count INTEGER NOT NULL DEFAULT 0")
    if "affected_paths" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN affected_paths TEXT NOT NULL DEFAULT '[]'")
    if "objective_count" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN objective_count INTEGER NOT NULL DEFAULT 0")
    if "session_count" not in columns:
        conn.execute("ALTER TABLE receipts ADD COLUMN session_count INTEGER NOT NULL DEFAULT 0")


def _ensure_event_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(events)").fetchall()
    }
    for column, declaration in _EVENT_METADATA_COLUMNS.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE events ADD COLUMN {column} {declaration}")


def init_db() -> None:
    db_path = _resolve_db_path()
    _ensure_db_directory(db_path)

    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                path TEXT NOT NULL,
                summary TEXT NOT NULL,
                objective_id TEXT,
                source_surface TEXT,
                actor_type TEXT,
                evidence_level TEXT,
                observed_vs_expected TEXT NOT NULL DEFAULT '{}',
                collector_status TEXT,
                scope_relation TEXT,
                evidence_refs TEXT NOT NULL DEFAULT '[]',
                raw_evidence_ref TEXT,
                data TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                event_ids TEXT NOT NULL,
                objective_id TEXT,
                event_count INTEGER NOT NULL DEFAULT 0,
                shell_event_count INTEGER NOT NULL DEFAULT 0,
                process_event_count INTEGER NOT NULL DEFAULT 0,
                affected_paths TEXT NOT NULL DEFAULT '[]',
                objective_count INTEGER NOT NULL DEFAULT 0,
                session_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events (session_id, datetime(timestamp) DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_receipts_session_ts ON receipts (session_id, datetime(timestamp) DESC, id DESC)"
        )

    _run_with_retries(_create_schema, db_path)
    def _migrate(conn: sqlite3.Connection) -> None:
        _ensure_event_columns(conn)
        _ensure_receipt_columns(conn)

    _run_with_retries(_migrate, db_path)
    _configure_db(db_path)


def _json_dumps(value: Any, default: Any) -> str:
    if value is None:
        value = default
    try:
        return json.dumps(value)
    except TypeError:
        return json.dumps(default)


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default.copy() if isinstance(default, (dict, list)) else default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return default.copy() if isinstance(default, (dict, list)) else default
        return loaded
    return default.copy() if isinstance(default, (dict, list)) else default


def _normalize_event_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field, default in _EVENT_DEFAULTS.items():
        value = metadata.get(field, default)
        if field in _EVENT_JSON_FIELDS:
            normalized[field] = _json_dumps(value, default)
        elif value is None:
            normalized[field] = None
        else:
            normalized[field] = str(value)
    return normalized


def _hydrate_event_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    for field, default in _EVENT_DEFAULTS.items():
        if field in _EVENT_JSON_FIELDS:
            item[field] = _json_loads(item.get(field), default)
        else:
            item.setdefault(field, default)
    return item


def _insert_event_record(
    event_type: str,
    path: str,
    summary: str,
    session_id: str,
    timestamp: str,
    **metadata: Any,
) -> None:
    db_path = _resolve_db_path()
    event_metadata = _normalize_event_metadata(metadata)

    def _insert(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO events (
                timestamp,
                session_id,
                event_type,
                path,
                summary,
                objective_id,
                source_surface,
                actor_type,
                evidence_level,
                observed_vs_expected,
                collector_status,
                scope_relation,
                evidence_refs,
                raw_evidence_ref,
                data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                session_id,
                event_type,
                path,
                summary,
                event_metadata["objective_id"],
                event_metadata["source_surface"],
                event_metadata["actor_type"],
                event_metadata["evidence_level"],
                event_metadata["observed_vs_expected"],
                event_metadata["collector_status"],
                event_metadata["scope_relation"],
                event_metadata["evidence_refs"],
                event_metadata["raw_evidence_ref"],
                event_metadata["data"],
            ),
        )

    _run_with_retries(_insert, db_path)


def _insert_receipt_record(
    session_id: str,
    summary: str,
    event_ids: list[str],
    objective_id: str | None = None,
    event_count: int = 0,
    shell_event_count: int = 0,
    process_event_count: int = 0,
    affected_paths: list[str] | None = None,
    objective_count: int = 0,
    session_count: int = 0,
) -> int:
    db_path = _resolve_db_path()
    timestamp = _now_iso_timestamp()
    payload = json.dumps(sorted(set(affected_paths or [])))

    def _insert(conn: sqlite3.Connection) -> int:
        cursor = conn.execute(
            """
            INSERT INTO receipts (
                timestamp,
                session_id,
                summary,
                event_ids,
                objective_id,
                event_count,
                shell_event_count,
                process_event_count,
                affected_paths,
                objective_count,
                session_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                session_id,
                summary,
                json.dumps(event_ids),
                objective_id,
                int(event_count),
                int(shell_event_count),
                int(process_event_count),
                payload,
                int(objective_count),
                int(session_count),
            ),
        )
        return int(cursor.lastrowid)

    return int(_run_with_retries(_insert, db_path))


def _db_writer_loop(event_queue: "queue.Queue[dict[str, Any]]") -> None:
    while True:
        try:
            payload = event_queue.get(timeout=0.25)
        except queue.Empty:
            if _WRITER_STOP_EVENT.is_set():
                return
            continue
        try:
            if payload is _WRITER_STOP_TOKEN:
                if event_queue.empty():
                    return
                continue

            record_type = payload.get("record_type")
            if record_type == "event":
                _insert_event_record(
                    event_type=payload["event_type"],
                    path=payload["path"],
                    summary=payload["summary"],
                    session_id=payload["session_id"],
                    timestamp=payload["timestamp"],
                    objective_id=payload.get("objective_id"),
                    source_surface=payload.get("source_surface"),
                    actor_type=payload.get("actor_type"),
                    evidence_level=payload.get("evidence_level"),
                    observed_vs_expected=payload.get("observed_vs_expected"),
                    collector_status=payload.get("collector_status"),
                    scope_relation=payload.get("scope_relation"),
                    evidence_refs=payload.get("evidence_refs"),
                    raw_evidence_ref=payload.get("raw_evidence_ref"),
                    data=payload.get("data"),
                )
            elif record_type == "receipt":
                _insert_receipt_record(
                    session_id=payload["session_id"],
                    summary=payload["summary"],
                    event_ids=payload["event_ids"],
                    objective_id=payload.get("objective_id"),
                    event_count=payload.get("event_count", 0),
                    shell_event_count=payload.get("shell_event_count", 0),
                    process_event_count=payload.get("process_event_count", 0),
                    affected_paths=payload.get("affected_paths", []),
                    objective_count=payload.get("objective_count", 0),
                    session_count=payload.get("session_count", 0),
                )
            _record_writer_metric("written")
        except Exception as exc:
            record_type = payload.get("record_type") if isinstance(payload, dict) else None
            record_event_write_failure("db_writer", exc, record_type=record_type)
            logging.exception("Failed to persist %s record", record_type)
        finally:
            event_queue.task_done()


def _start_db_writer() -> None:
    with _WRITER_LOCK:
        thread = _WRITER_STATE.get("thread")
        if thread is not None and thread.is_alive():
            return

        event_queue = _EVENT_QUEUE
        thread = threading.Thread(
            target=_db_writer_loop,
            args=(event_queue,),
            name="cleanhouse-events-writer",
            daemon=True,
        )
        _WRITER_STATE["thread"] = thread
        _WRITER_STATE["queue"] = event_queue
        _WRITER_STOP_EVENT.clear()
        thread.start()


def _stop_db_writer() -> None:
    with _WRITER_LOCK:
        thread = _WRITER_STATE.get("thread")
        event_queue = _WRITER_STATE.get("queue") or _EVENT_QUEUE
        if thread is None or not thread.is_alive():
            _WRITER_STATE["thread"] = None
            _WRITER_STATE["queue"] = None
            return

    _WRITER_STOP_EVENT.set()
    stop_deadline = time.monotonic() + 2.0
    while time.monotonic() < stop_deadline:
        if event_queue.empty() and getattr(event_queue, "unfinished_tasks", 0) == 0:
            break
        time.sleep(0.05)

    try:
        event_queue.put(_WRITER_STOP_TOKEN, timeout=0.2)
    except queue.Full as exc:
        _record_writer_metric("dropped")
        record_event_write_failure(
            "writer_stop",
            exc,
            record_type="stop",
            queue_depth=event_queue.qsize(),
            queue_maxsize=event_queue.maxsize,
        )
        logging.warning("DB writer stop token dropped because queue is full")

    thread.join(timeout=2.5)
    with _WRITER_LOCK:
        if not thread.is_alive():
            _WRITER_STATE["thread"] = None
            _WRITER_STATE["queue"] = None
            _WRITER_STOP_EVENT.clear()
        else:
            logging.warning("DB writer stop timed out and did not exit cleanly")


def get_writer_metrics() -> dict[str, int]:
    with _WRITER_LOCK:
        return dict(_WRITER_STATS)


def get_writer_health() -> dict[str, Any]:
    with _WRITER_LOCK:
        thread = _WRITER_STATE.get("thread")
        metrics = dict(_WRITER_STATS)
        last_error = dict(_WRITER_STATE["last_error"]) if isinstance(_WRITER_STATE.get("last_error"), dict) else None
    running = thread is not None and thread.is_alive()
    queue_depth = _EVENT_QUEUE.qsize()
    queue_maxsize = _EVENT_QUEUE.maxsize
    queue_metrics = {
        "depth": queue_depth,
        "maxsize": queue_maxsize,
        "unfinished_tasks": int(getattr(_EVENT_QUEUE, "unfinished_tasks", 0)),
        "full": _EVENT_QUEUE.full(),
    }
    degradation_reasons: list[str] = []
    if metrics.get("write_failures", 0):
        degradation_reasons.append("write_failures")
    if metrics.get("dropped", 0):
        degradation_reasons.append("dropped_records")
    if metrics.get("write_retries", 0):
        degradation_reasons.append("write_retries")
    if queue_metrics["full"]:
        degradation_reasons.append("queue_full")

    if metrics.get("write_failures", 0) or metrics.get("dropped", 0):
        collector_status = "failure"
    elif metrics.get("write_retries", 0) or queue_metrics["full"]:
        collector_status = "degraded"
    elif running:
        collector_status = "ok"
    else:
        collector_status = "inactive"
    return {
        "status": "running" if running else "stopped",
        "state": "running" if running else "stopped",
        "collector_status": collector_status,
        "support_status": "supported",
        "unsupported_reason": None,
        "queue_depth": queue_depth,
        "queue_maxsize": queue_maxsize,
        "queue": queue_metrics,
        "stop_requested": _WRITER_STOP_EVENT.is_set(),
        "metrics": metrics,
        "last_error": last_error,
        "degradation": {
            "degraded": bool(degradation_reasons),
            "reasons": degradation_reasons,
        },
    }


def _queue_db_write(payload: dict[str, Any]) -> None:
    _start_db_writer()
    try:
        _EVENT_QUEUE.put(payload, timeout=0.2)
    except queue.Full as exc:
        _record_writer_metric("dropped")
        record_event_write_failure(
            "queue_full",
            exc,
            record_type=payload.get("record_type"),
            queue_depth=_EVENT_QUEUE.qsize(),
            queue_maxsize=_EVENT_QUEUE.maxsize,
        )
        logging.warning("Event write queue full; dropped record %s", payload.get("record_type"))
    else:
        _record_writer_metric("enqueued")
        _track_queue_depth()


def insert_event(
    event_type: str,
    path: str,
    summary: str,
    session_id: str = DEFAULT_SESSION_ID,
    timestamp: str | None = None,
    objective_id: str | None = None,
    source_surface: str | None = None,
    actor_type: str | None = None,
    evidence_level: str | None = None,
    observed_vs_expected: dict[str, Any] | None = None,
    collector_status: str | None = None,
    scope_relation: str | None = None,
    evidence_refs: list[Any] | None = None,
    raw_evidence_ref: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    init_db()
    if not session_id:
        session_id = DEFAULT_SESSION_ID
    event_timestamp = timestamp or _now_iso_timestamp()
    _insert_event_record(
        event_type=event_type,
        path=path,
        summary=summary,
        session_id=session_id,
        timestamp=event_timestamp,
        objective_id=objective_id,
        source_surface=source_surface,
        actor_type=actor_type,
        evidence_level=evidence_level,
        observed_vs_expected=observed_vs_expected,
        collector_status=collector_status,
        scope_relation=scope_relation,
        evidence_refs=evidence_refs,
        raw_evidence_ref=raw_evidence_ref,
        data=data,
    )


def insert_event_async(
    event_type: str,
    path: str,
    summary: str,
    session_id: str = DEFAULT_SESSION_ID,
    timestamp: str | None = None,
    objective_id: str | None = None,
    source_surface: str | None = None,
    actor_type: str | None = None,
    evidence_level: str | None = None,
    observed_vs_expected: dict[str, Any] | None = None,
    collector_status: str | None = None,
    scope_relation: str | None = None,
    evidence_refs: list[Any] | None = None,
    raw_evidence_ref: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    init_db()
    _queue_db_write(
        {
            "record_type": "event",
            "event_type": event_type,
            "path": path,
            "summary": summary,
            "session_id": session_id or DEFAULT_SESSION_ID,
            "timestamp": timestamp or _now_iso_timestamp(),
            "objective_id": objective_id,
            "source_surface": source_surface,
            "actor_type": actor_type,
            "evidence_level": evidence_level,
            "observed_vs_expected": observed_vs_expected,
            "collector_status": collector_status,
            "scope_relation": scope_relation,
            "evidence_refs": evidence_refs,
            "raw_evidence_ref": raw_evidence_ref,
            "data": data,
        }
    )


def list_events(limit: int = 100, session_id: str | None = None) -> list[dict[str, Any]]:
    db_path = _resolve_db_path()
    init_db()
    limit = max(1, int(limit))

    params: list[Any] = []
    query = """
        SELECT
            id,
            timestamp,
            session_id,
            event_type,
            path,
            summary,
            objective_id,
            source_surface,
            actor_type,
            evidence_level,
            observed_vs_expected,
            collector_status,
            scope_relation,
            evidence_refs,
            raw_evidence_ref,
            data
        FROM events
    """
    if session_id:
        query += " WHERE session_id = ?"
        params.append(session_id)
    query += """
        ORDER BY datetime(timestamp) DESC, id DESC
        LIMIT ?
    """
    params.append(limit)

    def _select(conn: sqlite3.Connection):
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]

    rows = _run_with_retries(_select, db_path)
    return [_hydrate_event_row(row) for row in rows]


def list_receipts(limit: int = 100, session_id: str | None = None) -> list[dict[str, Any]]:
    db_path = _resolve_db_path()
    init_db()
    limit = max(1, int(limit))
    columns = {"id", "timestamp", "session_id", "summary", "event_ids"}
    try:
        with _DB_LOCK:
            conn = _connect(db_path)
            try:
                columns |= {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(receipts)").fetchall()
                }
            finally:
                conn.close()
    except Exception:
        columns |= {
            "objective_id",
            "event_count",
            "shell_event_count",
            "process_event_count",
            "affected_paths",
        }

    params: list[Any] = []
    optional_columns = []
    for optional in (
        "objective_id",
        "event_count",
        "shell_event_count",
        "process_event_count",
        "affected_paths",
        "objective_count",
        "session_count",
    ):
        if optional in columns:
            optional_columns.append(optional)
    select_clause = ", ".join(["id", "timestamp", "session_id", "summary", "event_ids"] + optional_columns)

    query = f"""
        SELECT {select_clause}
        FROM receipts
    """
    if session_id:
        query += " WHERE session_id = ?"
        params.append(session_id)
    query += """
        ORDER BY datetime(timestamp) DESC, id DESC
        LIMIT ?
    """
    params.append(limit)

    def _select(conn: sqlite3.Connection):
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]

    rows = _run_with_retries(_select, db_path)
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_event_ids = item.get("event_ids")
        if isinstance(raw_event_ids, str):
            try:
                item["event_ids"] = json.loads(raw_event_ids)
            except json.JSONDecodeError:
                item["event_ids"] = []
        else:
            item["event_ids"] = []
        if item.get("affected_paths") is None:
            item["affected_paths"] = []
        elif isinstance(item["affected_paths"], str):
            try:
                item["affected_paths"] = json.loads(item["affected_paths"])
            except json.JSONDecodeError:
                item["affected_paths"] = []
        item.setdefault("objective_id", None)
        item.setdefault("event_count", len(item.get("event_ids", [])))
        item.setdefault("shell_event_count", 0)
        item.setdefault("process_event_count", 0)
        item.setdefault("objective_count", 0)
        item.setdefault("session_count", 0)
        result.append(item)
    return result


def _extract_objective_id(path: Any) -> str | None:
    if not isinstance(path, str):
        return None
    if not path.startswith(DEFAULT_OBJECTIVE_PATH_PREFIX):
        return None
    value = path[len(DEFAULT_OBJECTIVE_PATH_PREFIX) :].strip()
    return value or None


def _select_receipt_event_tail(
    rows: list[dict[str, Any]],
    *,
    objective_id: str | None = None,
    window_seconds: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    eligible = [event for event in rows if event["event_type"] in _RECEIPT_EVENT_TYPES]
    if not eligible:
        return []

    chronological = list(reversed(eligible))
    window = timedelta(seconds=max(1, window_seconds))

    def _trim_by_window(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        newest = _parse_iso_timestamp(events[-1]["timestamp"])
        cutoff = newest - window
        selected: list[dict[str, Any]] = []
        previous_ts: datetime | None = None
        for event in events:
            event_ts = _parse_iso_timestamp(event["timestamp"])
            if event_ts < cutoff:
                continue
            if previous_ts is not None and (event_ts - previous_ts) > window:
                break
            selected.append(event)
            previous_ts = event_ts
        return selected

    if objective_id is not None:
        return _build_objective_segment(chronological, objective_id=objective_id, window=window)

    objective_starts: list[tuple[str, int]] = []
    ended_ids: set[str] = set()
    for index, event in enumerate(chronological):
        event_objective = _extract_objective_id(event.get("path"))
        if event["event_type"] == "objective_end" and event_objective:
            ended_ids.add(event_objective)
            continue
        if event["event_type"] == "objective_start" and event_objective and event_objective not in ended_ids:
            objective_starts.append((event_objective, index))

    for candidate_id, start_index in reversed(objective_starts):
        segment = _build_objective_segment(chronological, objective_id=candidate_id, window=window, start_index=start_index)
        if segment:
            return segment

    anchor = 0
    for index, event in enumerate(chronological):
        if event["event_type"] == "prompt_event":
            anchor = index
            break
    return _trim_by_window(chronological[anchor:])


def _build_objective_segment(
    chronological_events: list[dict[str, Any]],
    *,
    objective_id: str,
    window: timedelta,
    start_index: int | None = None,
) -> list[dict[str, Any]]:
    if not chronological_events:
        return []

    start = start_index
    if start is None:
        start = None
        for index, event in enumerate(chronological_events):
            if (
                event["event_type"] == "objective_start"
                and _extract_objective_id(event.get("path")) == objective_id
            ):
                start = index
                break
    if start is None:
        return []

    end = None
    for index in range(start + 1, len(chronological_events)):
        event = chronological_events[index]
        if (
            event["event_type"] == "objective_end"
            and _extract_objective_id(event.get("path")) == objective_id
        ):
            end = index
            break

    segment = chronological_events[start : (end + 1 if end is not None else None)]
    if end is None:
        event_limit = []
        newest = _parse_iso_timestamp(segment[-1]["timestamp"])
        cutoff = newest - window
        for event in segment:
            event_ts = _parse_iso_timestamp(event["timestamp"])
            if event_ts >= cutoff:
                event_limit.append(event)
        return event_limit
    return segment


def build_receipt(
    session_id: str = DEFAULT_SESSION_ID,
    *,
    window_seconds: int = DEFAULT_RECEIPT_WINDOW_SECONDS,
    event_limit: int = 300,
    objective_id: str | None = None,
) -> int | None:
    init_db()
    session_id = session_id or DEFAULT_SESSION_ID
    rows = list_events(limit=event_limit, session_id=session_id)
    selected = _select_receipt_event_tail(
        rows,
        objective_id=objective_id,
        window_seconds=window_seconds,
    )
    if not selected:
        return None

    event_ids = [str(event["id"]) for event in selected if event.get("id") is not None]
    if not event_ids:
        return None
    objective = objective_id
    affected_paths: list[str] = []
    objective_ids: set[str] = set()
    session_ids: set[str] = set()
    shell_event_count = 0
    process_event_count = 0
    for event in selected:
        event_type = event.get("event_type")
        if event_type == "shell_event":
            shell_event_count += 1
        if event_type == "process_event":
            process_event_count += 1
        event_objective_id = event.get("objective_id") or _extract_objective_id(event.get("path"))
        if event_objective_id:
            objective_ids.add(str(event_objective_id))
        if event.get("event_type") == "objective_start":
            objective = objective or event_objective_id
        event_session_id = event.get("session_id")
        if event_session_id:
            session_ids.add(str(event_session_id))
        path = event.get("path")
        if isinstance(path, str):
            affected_paths.append(path)

    summary = " -> ".join(event["event_type"] for event in selected)
    if objective is not None:
        summary = f"objective={objective}: {summary}"
    return _insert_receipt_record(
        session_id=session_id,
        summary=summary,
        event_ids=event_ids,
        objective_id=objective,
        event_count=len(selected),
        shell_event_count=shell_event_count,
        process_event_count=process_event_count,
        affected_paths=sorted(set(affected_paths)),
        objective_count=len(objective_ids),
        session_count=len(session_ids),
    )


def ensure_latest_receipt(
    session_id: str = DEFAULT_SESSION_ID,
    *,
    window_seconds: int = DEFAULT_RECEIPT_WINDOW_SECONDS,
) -> int | None:
    init_db()
    session_id = session_id or DEFAULT_SESSION_ID

    receipts = list_receipts(limit=1, session_id=session_id)
    recent_events = list_events(limit=1, session_id=session_id)
    if not recent_events:
        return None

    if receipts:
        latest_receipt = receipts[0]
        referenced = {str(event_id) for event_id in latest_receipt.get("event_ids", [])}
        if str(recent_events[0]["id"]) in referenced:
            return int(latest_receipt["id"])

    objective_id = None
    objective_candidates = [
        _extract_objective_id(event.get("path"))
        for event in recent_events
        if _extract_objective_id(event.get("path")) is not None
    ]
    if objective_candidates:
        objective_id = objective_candidates[0]

    return build_receipt(
        session_id=session_id,
        window_seconds=window_seconds,
        objective_id=objective_id,
    )


if FileSystemEventHandler is not None and Observer is not None:
    class _CleanHouseFileHandler(FileSystemEventHandler):
        def __init__(self, db_path: Path, watch_dir: Path):
            super().__init__()
            self._db_path = db_path.resolve()
            self._watch_dir = watch_dir.resolve()

        @staticmethod
        def _is_file_event(event) -> bool:
            return not event.is_directory

        def on_created(self, event) -> None:  # noqa: N802
            self._handle(event, "created")

        def on_modified(self, event) -> None:  # noqa: N802
            self._handle(event, "modified")

        def on_deleted(self, event) -> None:  # noqa: N802
            self._handle(event, "deleted")

        def _handle(self, event, event_type: str) -> None:
            if not self._is_file_event(event):
                return
            event_path = Path(event.src_path).resolve()
            if event_path == self._db_path:
                return
            if ".git" in event_path.parts:
                return
            insert_event_async(
                event_type=event_type,
                path=str(event_path),
                summary=f"{event_type}: {event_path}",
                session_id=os.getenv("CLEANHOUSE_SESSION_ID", DEFAULT_SESSION_ID),
                source_surface="filesystem_watcher",
                actor_type="collector",
                evidence_level="observed",
                collector_status="ok",
                scope_relation="unknown",
                evidence_refs=[str(event_path)],
                raw_evidence_ref=str(event_path),
                data={"watch_dir": str(self._watch_dir)},
            )
else:
    class _CleanHouseFileHandler:
        def __init__(self, db_path: Path, watch_dir: Path):
            self._db_path = db_path
            self._watch_dir = watch_dir


def start_watcher() -> None:
    if FileSystemEventHandler is None or Observer is None:
        _record_watcher_error("watchdog_dependency", "watchdog dependency missing")
        logging.warning("watchdog is unavailable; filesystem events will not be collected")
        return

    watch_dir = Path(os.getenv("CLEANHOUSE_WATCH_DIR", str(DEFAULT_WATCH_DIR))).expanduser()
    try:
        watch_dir = watch_dir.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        _record_watcher_error("watch_dir", exc, watch_dir=str(watch_dir))
        logging.warning("Could not start filesystem watcher for %s: %s", watch_dir, exc)
        return

    if not watch_dir.is_dir():
        _record_watcher_error("watch_dir", "watch path is not a directory", watch_dir=str(watch_dir))
        logging.warning("Could not start filesystem watcher; not a directory: %s", watch_dir)
        return

    with _WATCHER_LOCK:
        if _WATCHER_STATE["observer"] is not None:
            if _WATCHER_STATE["observer"].is_alive():
                return
            _WATCHER_STATE["observer"] = None
            _WATCHER_STATE["watch_dir"] = None

        if _WATCHER_STATE["watch_dir"] == watch_dir:
            return

        try:
            init_db()
            db_path = _resolve_db_path()
            _ensure_db_directory(db_path)
            handler = _CleanHouseFileHandler(db_path=db_path, watch_dir=watch_dir)
            observer = Observer()
            observer.schedule(handler, str(watch_dir), recursive=True)
            observer.start()
        except Exception as exc:
            _WATCHER_STATE["observer"] = None
            _WATCHER_STATE["watch_dir"] = None
            _WATCHER_STATE["last_error"] = _runtime_error_payload("watcher_start", exc, watch_dir=str(watch_dir))
            logging.warning("Could not start filesystem watcher for %s: %s", watch_dir, exc)
            return
        _WATCHER_STATE["observer"] = observer
        _WATCHER_STATE["watch_dir"] = watch_dir
        _WATCHER_STATE["last_error"] = None
        logging.info("Started filesystem watcher for %s", watch_dir)


def get_watcher_status() -> dict[str, Any]:
    dependency_available = FileSystemEventHandler is not None and Observer is not None
    with _WATCHER_LOCK:
        observer = _WATCHER_STATE["observer"]
        watch_dir = _WATCHER_STATE["watch_dir"]
        last_error = dict(_WATCHER_STATE["last_error"]) if isinstance(_WATCHER_STATE.get("last_error"), dict) else None
        running = observer is not None and observer.is_alive()
    if not dependency_available:
        status = "unavailable"
        collector_status = "dependency_missing"
        support_status = "unsupported"
        unsupported_reason = "watchdog dependency missing"
    elif running:
        status = "running"
        collector_status = "ok"
        support_status = "supported"
        unsupported_reason = None
    elif last_error is not None:
        status = "stopped"
        collector_status = "error"
        support_status = "supported"
        unsupported_reason = None
    else:
        status = "stopped"
        collector_status = "inactive"
        support_status = "supported"
        unsupported_reason = None
    degradation_reasons: list[str] = []
    if collector_status != "ok":
        degradation_reasons.append(collector_status)
    return {
        "status": status,
        "state": status,
        "collector_status": collector_status,
        "dependency_available": dependency_available,
        "support_status": support_status,
        "unsupported_reason": unsupported_reason,
        "watch_dir": str(watch_dir) if watch_dir is not None else None,
        "last_error": last_error,
        "degradation": {
            "degraded": bool(degradation_reasons),
            "reasons": degradation_reasons,
        },
    }


def get_runtime_status() -> dict[str, Any]:
    watcher = get_watcher_status()
    writer = get_writer_health()
    reasons: list[dict[str, Any]] = []
    for name, state in (("watcher", watcher), ("writer", writer)):
        degradation = state.get("degradation")
        if isinstance(degradation, dict) and degradation.get("degraded"):
            reasons.append({
                "surface": name,
                "collector_status": state.get("collector_status", "unknown"),
                "reasons": list(degradation.get("reasons", [])),
            })
    return {
        "status": "degraded" if reasons else "ok",
        "watcher": watcher,
        "writer": writer,
        "queue": writer.get("queue", {}),
        "degradation": {
            "degraded": bool(reasons),
            "reasons": reasons,
        },
    }


def stop_watcher() -> None:
    with _WATCHER_LOCK:
        observer = _WATCHER_STATE["observer"]
        if observer is None:
            return
        if observer.is_alive():
            observer.stop()
            observer.join(timeout=2.0)
        _WATCHER_STATE["observer"] = None
        _WATCHER_STATE["watch_dir"] = None
        logging.info("Stopped filesystem watcher")


def stop_events_services() -> None:
    stop_watcher()
    _stop_db_writer()
