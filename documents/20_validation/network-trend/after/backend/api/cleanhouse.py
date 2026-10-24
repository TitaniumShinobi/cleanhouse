"""
CleanHouse monitoring API endpoints.
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
import uuid
import hashlib
import ipaddress
import json
import logging
import plistlib
import subprocess
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file, session, stream_with_context
from backend import events
from backend import vvault_preservation
from backend import file_integrity, vvault_sync, wazuh_files, wazuh_runtime
from backend.apple_intelligence import AppleIntelligenceInsightService
from backend.utils.jwt_utils import get_user_from_token
from backend.evidence_context import EvidenceActionResolver, EvidenceContext
from backend.network_collector import CaptureEngineUnavailable, NetworkCollectorSupervisor

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter, LOGIN_REPORT_WAIT_SECONDS

bp = Blueprint("cleanhouse", __name__)
_LOG = logging.getLogger(__name__)
LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_SESSION_ID_LENGTH = 128
MAX_PATH_LENGTH = 4096

_adapter: CleanHouseMonitoringAdapter | None = None
_evidence_context_resolver: EvidenceActionResolver | None = None
_apple_intelligence_insight_service: AppleIntelligenceInsightService | None = None
_EVIDENCE_ACTION_REQUESTS: dict[str, dict[str, Any]] = {}
_EVIDENCE_ACTION_REQUEST_FINGERPRINTS: dict[str, str] = {}
_EVIDENCE_ACTION_REQUESTS_LOCK = threading.Lock()
DEFAULT_SESSION_ID = "default-session"
APPLICATION_TARGETS = {
    "terminal": Path("/System/Applications/Utilities/Terminal.app"),
    "safari": Path("/Applications/Safari.app"),
    "textedit": Path("/System/Applications/TextEdit.app"),
    "finder": Path("/System/Library/CoreServices/Finder.app"),
}
APPLICATION_SEARCH_ROOTS = (
    Path("/Applications"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
)
LOW_PROCESSING_RECEIPT_LIMIT = 5
LOW_PROCESSING_RECEIPT_MAX_LIMIT = 50
LOW_PROCESSING_EVENT_LIMIT = 20
LOW_PROCESSING_EVENT_MAX_LIMIT = 200
LOW_PROCESSING_DOMAIN_EVENT_LIMIT = 50
LOW_PROCESSING_DOMAIN_EVENT_MAX_LIMIT = 200
LOW_PROCESSING_REPORT_LIMIT = 10
LOW_PROCESSING_REPORT_MAX_LIMIT = 50
LOW_PROCESSING_INTENT_LIMIT = 10
LOW_PROCESSING_INTENT_MAX_LIMIT = 50
LOW_PROCESSING_APPROVAL_LIMIT = 5
LOW_PROCESSING_APPROVAL_MAX_LIMIT = 50
WIRESHARK_CAPTURE_DEFAULT_SECONDS = 3
WIRESHARK_CAPTURE_MAX_SECONDS = 10
WIRESHARK_CAPTURE_TIMEOUT_GRACE_SECONDS = 5
WIRESHARK_MAX_EVENTS = 200
NETWORK_EVIDENCE_RETENTION_DAYS = 365
NETWORK_EVIDENCE_LOOKBACK = int(os.environ.get("CLEANHOUSE_NETWORK_EVIDENCE_LOOKBACK", "50000"))
NETWORK_SERVER_BOOT_ID = os.getenv("CLEANHOUSE_BACKEND_BOOT_ID") or uuid.uuid4().hex
NETWORK_PROJECTION_LIMIT = 500
NETWORK_FINDINGS_CACHE_SECONDS = 15.0
NETWORK_FINDINGS_LOOKBACK = int(os.environ.get("CLEANHOUSE_NETWORK_FINDINGS_LOOKBACK", "10000"))
NETWORK_FINDINGS_RELATED_ID_LIMIT = 8
NETWORK_FINDINGS_DESTINATION_LIMIT = 8
NETWORK_TREND_BUCKET_EVENT_TYPE = "network_trend_bucket"
NETWORK_TREND_TICK_EVENT_TYPE = "network_trend_tick"
NETWORK_TREND_INTERPRETATION_SCHEMA = "cleanhouse.network.trend.interpretation.v1"
NETWORK_TREND_RULE_VERSION = "network-trend-rationalization.v1"
NETWORK_OBSERVATION_EVENT_TYPE = "network_observation"
NETWORK_TIMELINE_NOTABLE_EVENT_TYPE = "network_timeline_notable"
NETWORK_TIMELINE_GAP_EVENT_TYPE = "network_timeline_gap"
NETWORK_SYNC_EVENT_TYPE = "network_vvault_sync_status"
NETWORK_COLLECTOR_RECEIPT_EVENT_TYPE = "network_collector_receipt"
NETWORK_RUNTIME_WARMUP_SECONDS = float(os.environ.get("CLEANHOUSE_NETWORK_RUNTIME_WARMUP_SECONDS", "30"))
NETWORK_VVAULT_OUTBOX_MAXSIZE = 2000
NETWORK_VVAULT_BATCH_SIZE = 50
NETWORK_VVAULT_RETRY_SECONDS = 15
NETWORK_UI_STATES = {"READY", "CAPTURING", "NO_DATA", "WARMING", "ERROR", "CAPTURE_BLOCKED"}
NETWORK_PROJECTION_VIEWS = {"findings", "trend", "distribution", "timeline"}
NETWORK_TIME_RANGES_MS = {
    "5s": 5 * 1000,
    "1m": 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "1mo": 30 * 24 * 60 * 60 * 1000,
    "3mo": 90 * 24 * 60 * 60 * 1000,
    "12mo": 365 * 24 * 60 * 60 * 1000,
}
NETWORK_TREND_BUCKETS = {
    "5s": 12,
    "1m": 18,
    "30m": 24,
    "1h": 24,
    "24h": 30,
    "7d": 32,
    "1mo": 36,
    "3mo": 36,
    "12mo": 40,
}
NETWORK_SEVERITY_RANK = {"critical": 4, "high": 3, "warning": 2, "medium": 2, "low": 1, "info": 0}
NETWORK_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
_NETWORK_VVAULT_OUTBOX: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=NETWORK_VVAULT_OUTBOX_MAXSIZE)
_NETWORK_VVAULT_WORKER_LOCK = threading.Lock()
_NETWORK_VVAULT_WORKER_STARTED = False
_NETWORK_VVAULT_WORKER_THREAD: threading.Thread | None = None
_NETWORK_VVAULT_WORKER_STOP = threading.Event()
_NETWORK_VVAULT_STATE_LOCK = threading.Lock()
_NETWORK_VVAULT_SYNCED_IDS: set[str] = set()
_NETWORK_VVAULT_LAST_SUCCESS_AT = ""
_NETWORK_VVAULT_LAST_ERROR = ""
_NETWORK_STARTUP_RECONCILIATION_LOCK = threading.Lock()
_NETWORK_STARTUP_OPERATOR_RECORDS: dict[str, int] = {}
_NETWORK_STARTUP_OPERATOR_RECORDS_CREATED = 0
_NETWORK_STARTUP_OPERATOR_RECORDS_UPDATED = 0


def _network_startup_operator_identity(event: dict[str, Any]) -> str:
    values = (
        event.get("process") or event.get("app") or "Unknown app",
        event.get("source_display") or _network_endpoint(event.get("src_ip"), event.get("src_port")) or "Unknown source",
        event.get("destination_display") or _network_endpoint(event.get("dst_ip"), event.get("dst_port")) or "Unknown destination",
        event.get("protocol") or "Network connection",
        event.get("dst_port") or event.get("port") or "Unavailable",
    )
    return "|".join(str(value).strip().lower() for value in values)


def _log_network_startup_reconciliation(stage: str, **details: Any) -> None:
    message = json.dumps({"stage": stage, **details}, sort_keys=True, default=str)
    if stage in {"operator_record_reconciled", "snapshot_operator_record"}:
        _LOG.debug("network_startup_reconciliation %s", message)
    else:
        _LOG.info("network_startup_reconciliation %s", message)


def _log_network_history_io(stage: str, **details: Any) -> None:
    _LOG.info("network_history_io %s", json.dumps({"stage": stage, **details}, sort_keys=True, default=str))


def _log_network_vvault_save_result(
    artifact: str,
    artifact_id: Any,
    timestamp: Any,
    result: dict[str, Any],
) -> None:
    details = {
        "stage": "vvault_save",
        "artifact": artifact,
        "artifact_id": artifact_id,
        "timestamp": timestamp,
        "status": result.get("status"),
        "reason": result.get("reason") or result.get("message") or "",
    }
    message = json.dumps(details, sort_keys=True, default=str)
    if result.get("status") == "error":
        _LOG.warning("network_history_io %s", message)
    else:
        _LOG.debug("network_history_io %s", message)
_NETWORK_VVAULT_LAST_ERROR_AT = ""
_NETWORK_VVAULT_PENDING_COUNT = 0
_NETWORK_VVAULT_OLDEST_PENDING_AT = ""
_NETWORK_VVAULT_QUEUE_DROPS = 0
_NETWORK_LIVE_PERSIST_QUEUE: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=2000)
_NETWORK_LIVE_PERSIST_LOCK = threading.Lock()
_NETWORK_LIVE_PERSIST_WORKER_STARTED = False
_NETWORK_LIVE_PERSIST_WORKER_THREAD: threading.Thread | None = None
_NETWORK_LIVE_PERSIST_WORKER_STOP = threading.Event()
_NETWORK_LIVE_PERSIST_QUEUE_DROPS = 0
_NETWORK_LIVE_PERSIST_FAILURES = 0
_NETWORK_LIVE_PERSIST_LAST_ERROR = ""
_NETWORK_HISTORY_SERVICE_LOCK = threading.Lock()
_NETWORK_HISTORY_SERVICE_STOP = threading.Event()
_NETWORK_HISTORY_SERVICE_THREAD: threading.Thread | None = None
_NETWORK_COLLECTOR_LOCK = threading.Lock()
_NETWORK_COLLECTOR: NetworkCollectorSupervisor | None = None
_NETWORK_COLLECTOR_ENRICHMENT_LOCK = threading.Lock()
_NETWORK_COLLECTOR_ENRICHMENT: dict[str, dict[str, Any]] = {}
_NETWORK_COLLECTOR_ENRICHMENT_AT = 0.0
NETWORK_COLLECTOR_ENRICHMENT_INTERVAL_SECONDS = 15.0
NETWORK_CAPTURE_STALE_AFTER_MS = 15_000.0
_NETWORK_RUNNING_APPS_LOCK = threading.Lock()
_NETWORK_RUNNING_APPS: list[dict[str, Any]] = []
_NETWORK_RUNNING_APPS_AT = 0.0
_NETWORK_CANONICAL_EVENT_IDS_LOCK = threading.Lock()
_NETWORK_CANONICAL_EVENT_IDS: dict[str, None] = {}
_NETWORK_CANONICAL_EVENT_IDS_INITIALIZED = False
_NETWORK_CANONICAL_EVENT_IDS_LIMIT = 100000
_NETWORK_FINDINGS_CACHE_LOCK = threading.Lock()
_NETWORK_FINDINGS_CACHE: dict[str, Any] = {"payload": None, "cached_at": 0.0}
_NETWORK_PROJECTION_CACHE_LOCK = threading.Lock()
_NETWORK_PROJECTION_CACHE: dict[str, dict[str, Any]] = {}
_NETWORK_RECENT_OBSERVATIONS_LOCK = threading.Lock()
_NETWORK_RECENT_OBSERVATIONS: "deque[dict[str, Any]]" = deque(maxlen=5000)
_NETWORK_BACKEND_STARTED_AT = time.monotonic()
APPLICATION_CATEGORY_RULES = {
    "communications": (
        "messages", "facetime", "mail", "outlook", "phone", "contacts", "slack", "discord", "zoom", "teams",
        "telegram", "signal", "whatsapp",
    ),
    "developer": (
        "terminal", "codex", "cursor", "xcode", "visual studio", "code", "kiro", "github", "docker",
        "opencode", "script editor",
    ),
    "files": (
        "finder", "preview", "textedit", "pages", "numbers", "keynote", "word", "excel", "pdf", "cleanmymac",
        "dictionary", "font book", "print center",
    ),
    "network": (
        "safari", "chrome", "firefox", "arc", "atlas", "vpn", "wireshark", "warp", "airport utility",
        "screen sharing", "iphone mirroring",
    ),
    "creative": (
        "canva", "compressor", "creator studio", "final cut", "motion", "logic pro", "pixelmator", "photo booth",
        "photos", "image capture", "image playground", "quicktime", "digital color meter", "colorsync", "audio midi",
    ),
    "productivity": (
        "books", "calendar", "clock", "freeform", "home", "journal", "maps", "news", "notes", "podcasts",
        "reminders", "stocks", "music",
    ),
    "system": (
        "activity monitor", "app store", "apps", "automator", "bluetooth file exchange", "boot camp",
        "calculator", "console", "disk utility", "findmy", "games", "grapher", "magnifier", "migration assistant",
        "mission control", "passwords", "shortcuts", "siri", "stickies",
    ),
    "ai": ("chatgpt", "copilot"),
}


def get_cleanhouse_monitoring_adapter() -> CleanHouseMonitoringAdapter:
    global _adapter
    if _adapter is None:
        _adapter = CleanHouseMonitoringAdapter()
    return _adapter


def get_evidence_context_resolver() -> EvidenceActionResolver:
    global _evidence_context_resolver
    if _evidence_context_resolver is None:
        _evidence_context_resolver = EvidenceActionResolver()
    return _evidence_context_resolver


def get_apple_intelligence_insight_service() -> AppleIntelligenceInsightService:
    global _apple_intelligence_insight_service
    if _apple_intelligence_insight_service is None:
        _apple_intelligence_insight_service = AppleIntelligenceInsightService()
    return _apple_intelligence_insight_service


def _parse_json_payload():
    payload = request.get_json(silent=True)
    if payload is None:
        return None, ({"status": "error", "message": "Request body must be valid JSON."}, 400)
    if not isinstance(payload, dict):
        return None, ({"status": "error", "message": "Request body must be a JSON object."}, 400)
    return payload, None


def _error_response(message: str):
    return {"status": "error", "message": message}, 400


def _auth_error_response(message: str):
    return {"status": "error", "message": message}, 401


def _require_string(
    value: Any,
    field: str,
    *,
    max_len: int = 4096,
    required: bool = True,
    allow_empty: bool = False,
):
    if value is None:
        if required:
            return None, _error_response(f"{field} is required")
        return None, None
    if not isinstance(value, str):
        return None, _error_response(f"{field} must be a string")
    value = value.strip()
    if not value:
        if required:
            if allow_empty:
                return value, None
            return None, _error_response(f"{field} is required")
        if allow_empty:
            return value, None
        return None, _error_response(f"{field} must be a non-empty string")
    if len(value) > max_len:
        return None, _error_response(f"{field} exceeds maximum length")
    return value, None


def _require_dict(value: Any, field: str, *, required: bool = True):
    if value is None:
        if required:
            return None, _error_response(f"{field} is required")
        return None, None
    if not isinstance(value, dict):
        return None, _error_response(f"{field} must be an object")
    return value, None


def _validate_session_id(value: Any, *, required: bool = True):
    if value is None:
        if required:
            return None, _error_response("session_id is required")
        return None, None
    if not isinstance(value, str):
        return None, _error_response("session_id must be a string")
    value = value.strip()
    if not value:
        if required:
            return None, _error_response("session_id is required")
        return None, _error_response("session_id must be a non-empty string")
    if len(value) > MAX_SESSION_ID_LENGTH:
        return None, _error_response("session_id exceeds maximum length")
    if not SESSION_ID_RE.fullmatch(value):
        return None, _error_response("session_id format is invalid")
    return value, None


def _resolve_session_id(raw: Any, *, required: bool = False):
    if isinstance(raw, str) and not raw.strip():
        raw = None
    if raw is None:
        return os.getenv("CLEANHOUSE_SESSION_ID", DEFAULT_SESSION_ID), None
    return _validate_session_id(raw, required=required)


def _require_allowed_origin(origin: str | None) -> tuple[dict, bool]:
    if not origin:
        return {"status": "error", "message": "Origin missing"}, False

    if LOCAL_ORIGIN_RE.match(origin):
        return {}, True

    explicit = set()
    for env_name in ("CLEANHOUSE_ALLOWED_ORIGINS", "CLEANHOUSE_ALLOW_REMOTE_ORIGINS"):
        raw = os.getenv(env_name, "")
        if raw.strip():
            explicit.update(value.strip() for value in raw.split(",") if value.strip())

    if origin in explicit:
        return {}, True
    return {"status": "error", "message": "Origin not allowed"}, False


def _require_privileged_files_request(intent: str, *, allow_same_origin_get: bool = False):
    origin = request.headers.get("Origin")
    if origin:
        origin_error, allowed = _require_allowed_origin(origin)
        if not allowed:
            return origin_error, 403
    elif allow_same_origin_get:
        raw_host = str(getattr(request, "host", "") or "").lower()
        host = "::1" if raw_host.startswith("[::1]") else raw_host.split(":", 1)[0]
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return {"status": "error", "message": "Same-origin local host required"}, 403
    else:
        return {"status": "error", "message": "Origin missing"}, 403
    fetch_site = str(request.headers.get("Sec-Fetch-Site") or "same-origin").lower()
    if fetch_site not in {"same-origin", "same-site", "none"}:
        return {"status": "error", "message": "Cross-site request rejected"}, 403
    if request.headers.get("X-CleanHouse-Intent") != intent:
        return {"status": "error", "message": "Missing privileged intent header"}, 403
    auth_enabled = os.getenv("CLEANHOUSE_ENABLE_AUTH", "1").lower() not in {"0", "false", "no", "off"}
    require_login = os.getenv("CLEANHOUSE_REQUIRE_LOGIN", "1").lower() not in {"0", "false", "no", "off"}
    if auth_enabled and require_login and not (session.get("user_id") or session.get("oauth_user")):
        return {"status": "error", "message": "Authentication required"}, 401
    return None


def _require_files_read_request():
    """Protect path-bearing Files evidence without creating another auth model."""
    origin = request.headers.get("Origin")
    if origin:
        origin_error, allowed = _require_allowed_origin(origin)
        if not allowed:
            return origin_error, 403
    else:
        raw_host = str(getattr(request, "host", "") or "").lower()
        host = "::1" if raw_host.startswith("[::1]") else raw_host.split(":", 1)[0]
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return {"status": "error", "message": "Same-origin local host required"}, 403
    fetch_site = str(request.headers.get("Sec-Fetch-Site") or "same-origin").lower()
    if fetch_site not in {"same-origin", "same-site", "none"}:
        return {"status": "error", "message": "Cross-site request rejected"}, 403
    auth_enabled = os.getenv("CLEANHOUSE_ENABLE_AUTH", "1").lower() not in {"0", "false", "no", "off"}
    require_login = os.getenv("CLEANHOUSE_REQUIRE_LOGIN", "1").lower() not in {"0", "false", "no", "off"}
    if auth_enabled and require_login and not (session.get("user_id") or session.get("oauth_user")):
        return {"status": "error", "message": "Authentication required"}, 401
    return None


def _allowed_repo_roots():
    roots = [Path.home(), Path.cwd()]
    raw_roots = os.getenv("CLEANHOUSE_ALLOWED_REPO_ROOTS", "").strip()
    if raw_roots:
        roots.extend(
            Path(item.strip())
            for item in raw_roots.split(",")
            if item.strip()
        )
    normalized = []
    for root in roots:
        try:
            normalized.append(root.expanduser().resolve())
        except TypeError:
            continue
    seen = []
    for root in normalized:
        if root not in seen:
            seen.append(root)
    return seen


def _is_within_repo_root(candidate: Path) -> bool:
    for root in _allowed_repo_roots():
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _validate_repo_path(repo_path: Any):
    normalized, reason = _require_string(repo_path, "repo_path", max_len=MAX_PATH_LENGTH)
    if reason:
        return None, reason

    try:
        path = Path(normalized).expanduser()
        path = path if path.is_absolute() else Path.cwd() / path
        path = path.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, _error_response("repo_path is invalid")

    if not path.exists():
        return None, _error_response("repo_path does not exist")
    if not path.is_dir():
        return None, _error_response("repo_path must be a directory")
    if not _is_within_repo_root(path):
        return None, _error_response("repo_path is outside allowed repository roots")
    return path, None


def _refresh_flag() -> bool:
    return request.args.get("refresh", "").lower() in {"1", "true", "yes", "on"}


def _truthy_arg(name: str) -> bool:
    return request.args.get(name, "").lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_id(*parts: str) -> str:
    raw = "::".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _app_inventory_state_path() -> Path:
    return Path(
        os.getenv(
            "CLEANHOUSE_APP_INVENTORY_PATH",
            Path.home() / "Documents" / "CleanHouse" / "Data" / "app_inventory.json",
        )
    )


def _capture_duration() -> tuple[int | None, tuple[dict[str, Any], int] | None]:
    raw_duration = request.args.get("duration", "").strip()
    if not raw_duration:
        return WIRESHARK_CAPTURE_DEFAULT_SECONDS, None
    try:
        duration = int(raw_duration)
    except ValueError:
        return None, _bundled_wireshark_error("invalid_capture_duration", "Capture duration is invalid.")
    if duration < 1:
        return None, _bundled_wireshark_error("invalid_capture_duration", "Capture duration is invalid.")
    return min(duration, WIRESHARK_CAPTURE_MAX_SECONDS), None


def _network_runtime_probe_state(events_payload: list[dict[str, Any]]) -> str:
    # Data availability is not capture health. The collector lifecycle applied
    # by _network_apply_collector_truth is the sole authority for warming,
    # blocked, degraded, and operational capture states.
    return "CAPTURING" if events_payload else "NO_DATA"


def _app_icon_cache_dir() -> Path:
    return Path(
        os.getenv(
            "CLEANHOUSE_APP_ICON_CACHE_DIR",
            Path.home() / "Documents" / "CleanHouse" / "Data" / "app_icons",
        )
    )


def _allowed_threats_path() -> Path:
    return Path(
        os.getenv(
            "CLEANHOUSE_ALLOWED_THREATS_PATH",
            Path.home() / "Documents" / "CleanHouse" / "Data" / "allowed_threats" / "allowed_threats.json",
        )
    )


def _read_app_inventory_state() -> dict[str, Any]:
    path = _app_inventory_state_path()
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def _write_app_inventory_state(payload: dict[str, Any]) -> None:
    path = _app_inventory_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_allowed_threats_state() -> dict[str, Any]:
    path = _allowed_threats_path()
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                items = payload.get("allowed_threats", [])
                payload["allowed_threats"] = items if isinstance(items, list) else []
                return payload
            if isinstance(payload, list):
                return {"allowed_threats": payload}
    except Exception:
        return {"allowed_threats": []}
    return {"allowed_threats": []}


def _write_allowed_threats_state(payload: dict[str, Any]) -> None:
    path = _allowed_threats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _allowed_threat_string(payload: dict[str, Any], key: str, *, default: str = "Unavailable", max_len: int = 4096) -> str:
    value = payload.get(key)
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    return value[:max_len]


def _allowed_threat_evidence_refs(payload: dict[str, Any]) -> list[str]:
    refs = payload.get("evidence_refs", [])
    if not isinstance(refs, list):
        return []
    normalized = []
    for ref in refs[:20]:
        value = str(ref).strip()
        if value:
            normalized.append(value[:1024])
    return normalized


def _allowed_threat_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    seed = json.dumps(payload, sort_keys=True, default=str)
    allowed_id = "allowed-threat-" + _artifact_id(now, seed)
    return {
        "id": allowed_id,
        "created_at": now,
        "updated_at": now,
        "threat_name": _allowed_threat_string(payload, "threat_name"),
        "severity": _allowed_threat_string(payload, "severity"),
        "target_type": _allowed_threat_string(payload, "target_type"),
        "target_name": _allowed_threat_string(payload, "target_name"),
        "target_path": _allowed_threat_string(payload, "target_path"),
        "source": _allowed_threat_string(payload, "source"),
        "reason": _allowed_threat_string(payload, "reason"),
        "evidence_refs": _allowed_threat_evidence_refs(payload),
        "receipt_ref": _allowed_threat_string(payload, "receipt_ref", default=""),
        "status": "allowed",
    }


def _finding_text(payload: dict[str, Any], keys: tuple[str, ...], default: str = "Unavailable") -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _scan_finding_from_issue(issue: Any, *, source: str, fallback_name: str) -> dict[str, Any]:
    issue_payload = issue if isinstance(issue, dict) else {"summary": str(issue)}
    target_path = _finding_text(issue_payload, ("target_path", "path", "file_path", "process_path"), "")
    target_name = _finding_text(issue_payload, ("target_name", "app_name", "process_name", "name", "command", "host", "domain"), "")
    evidence_refs = issue_payload.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    return {
        "threat_name": _finding_text(issue_payload, ("threat_name", "title", "label", "summary", "name"), fallback_name),
        "severity": _finding_text(issue_payload, ("severity", "level", "status"), "Unavailable"),
        "target_type": _finding_text(issue_payload, ("target_type", "surface", "type"), source),
        "target_name": target_name,
        "target_path": target_path,
        "source": source,
        "reason": _finding_text(issue_payload, ("reason", "summary", "message", "description"), "Detected by CleanHouse scan."),
        "recommended_action": _finding_text(issue_payload, ("recommended_action", "next_action"), "Inspect details before taking action."),
        "evidence_refs": [str(ref) for ref in evidence_refs if str(ref).strip()],
        "receipt_ref": _finding_text(issue_payload, ("receipt_ref",), ""),
        "allowable": True,
    }


def _app_info_plist(app_path: Path) -> dict[str, Any]:
    info_path = app_path / "Contents" / "Info.plist"
    if not info_path.exists():
        return {}
    try:
        with info_path.open("rb") as fh:
            payload = plistlib.load(fh)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _application_identity_from_path(app_path: Path) -> dict[str, Any]:
    info = _app_info_plist(app_path)
    name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or app_path.stem
    bundle_id = info.get("CFBundleIdentifier") or f"local.app.{_artifact_id(str(app_path))}"
    app_id = _artifact_id(bundle_id, str(app_path))
    return {
        "id": app_id,
        "name": str(name),
        "bundle_id": str(bundle_id),
        "path": str(app_path),
        "version": str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "unknown"),
        "icon_url": f"/cleanhouse/applications/{app_id}/icon.png",
        "category": _application_category(str(name), str(bundle_id), str(app_path)),
    }


def _application_category(name: str, bundle_id: str, path: str) -> str:
    haystack = f"{name} {bundle_id} {path}".lower()
    for category, markers in APPLICATION_CATEGORY_RULES.items():
        if any(marker in haystack for marker in markers):
            return category
    return "other"


APPLICATION_INVENTORY_LIMIT = int(os.environ.get("CLEANHOUSE_APPLICATION_INVENTORY_LIMIT", "500"))
APPLICATION_PROCESS_MATCH_FIELDS = (
    "command",
    "args",
    "source_command",
    "process",
    "name",
    "path",
    "bundle_id",
)
APPLICATION_PROCESS_PAYLOAD_FIELDS = (
    "pid",
    "user",
    "cpu",
    "cpu_percent",
    "mem",
    "rss_bytes",
    "rss_kb",
    "command",
    "process",
    "name",
    "platform",
    "agent",
    "system",
)


def _discover_application_paths() -> list[Path]:
    apps: dict[str, Path] = {}
    for root in APPLICATION_SEARCH_ROOTS:
        try:
            if not root.exists() or not root.is_dir():
                continue
            for candidate in sorted(root.glob("*.app")):
                try:
                    resolved = candidate.resolve()
                except Exception:
                    resolved = candidate
                apps[str(resolved)] = resolved
        except Exception:
            continue
    for candidate in APPLICATION_TARGETS.values():
        if candidate.exists():
            try:
                apps[str(candidate.resolve())] = candidate.resolve()
            except Exception:
                apps[str(candidate)] = candidate
    return sorted(apps.values(), key=lambda item: item.stem.lower())


def _application_match_values(app: dict[str, Any]) -> list[str]:
    values = [
        str(app.get("path", "")),
        str(app.get("name", "")),
        str(app.get("bundle_id", "")),
    ]
    return [value.lower() for value in values if value]


def _running_gui_app_candidates() -> dict[str, dict[str, Any]]:
    if sys.platform != "darwin":
        return {}
    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(name: Any = "", bundle_id: Any = "", path: Any = "", pid: Any = None, source: str = "") -> None:
        record = {
            "name": str(name or "").strip(),
            "bundle_id": str(bundle_id or "").strip(),
            "path": str(path or "").strip(),
            "pid": str(pid or "").strip(),
            "source": source,
        }
        if not (record["name"] or record["bundle_id"] or record["path"]):
            return
        for key in (record["bundle_id"].lower(), record["path"].lower(), record["name"].lower()):
            if key:
                candidates[key] = record

    try:
        from AppKit import NSWorkspace  # type: ignore

        for app in NSWorkspace.sharedWorkspace().runningApplications():
            try:
                if int(app.activationPolicy()) != 0:
                    continue
                bundle_url = app.bundleURL()
                add_candidate(
                    app.localizedName(),
                    app.bundleIdentifier(),
                    bundle_url.path() if bundle_url else "",
                    app.processIdentifier(),
                    "nsworkspace",
                )
            except Exception:
                continue
    except Exception:
        pass
    if candidates:
        return candidates

    try:
        script = (
            'set AppleScript\'s text item delimiters to linefeed\n'
            'set rows to {}\n'
            'tell application "System Events"\n'
            '  repeat with proc in (application processes whose background only is false)\n'
            '    set procName to name of proc as text\n'
            '    set procBundle to ""\n'
            '    set procPid to ""\n'
            '    try\n'
            '      set procBundle to bundle identifier of proc as text\n'
            '    end try\n'
            '    try\n'
            '      set procPid to unix id of proc as text\n'
            '    end try\n'
            '    set end of rows to procName & tab & procBundle & tab & procPid\n'
            '  end repeat\n'
            'end tell\n'
            'return rows as text\n'
        )
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        if completed.returncode == 0:
            for line in completed.stdout.splitlines():
                parts = line.split("\t")
                if parts:
                    add_candidate(
                        parts[0] if len(parts) > 0 else "",
                        parts[1] if len(parts) > 1 else "",
                        "",
                        parts[2] if len(parts) > 2 else "",
                        "system_events",
                    )
    except Exception:
        pass
    return candidates


def _application_matches_process_text(app: dict[str, Any], text: str) -> bool:
    haystack = str(text or "").lower()
    if not haystack:
        return False
    path = str(app.get("path") or "").strip().lower()
    bundle_id = str(app.get("bundle_id") or "").strip().lower()
    name = str(app.get("name") or "").strip().lower()
    if path and path in haystack:
        return True
    if bundle_id and bundle_id in haystack:
        return True
    if name:
        escaped = re.escape(name)
        if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", haystack):
            return True
        if f"/{name}.app/" in haystack or f"/{name}.app " in haystack:
            return True
    return False


def _application_matches_gui_candidate(app: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> bool:
    if not candidates:
        return False
    for value in (app.get("bundle_id"), app.get("path"), app.get("name")):
        key = str(value or "").strip().lower()
        if key and key in candidates:
            return True
    return False


def _process_match_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in APPLICATION_PROCESS_MATCH_FIELDS:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            continue
        if isinstance(value, (list, tuple, set)):
            text = " ".join(str(item) for item in value)
        else:
            text = str(value)
        text = text.strip().lower()
        if text:
            parts.append(text[:2048])
    return "\n".join(parts)[:8192]


def _process_match_index(process_rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    index: list[tuple[str, dict[str, Any]]] = []
    for row in process_rows:
        if not isinstance(row, dict):
            continue
        text = _process_match_text(row)
        if text:
            index.append((text, row))
    return index


def _compact_application_process(row: dict[str, Any]) -> dict[str, Any]:
    compact = {}
    for key in APPLICATION_PROCESS_PAYLOAD_FIELDS:
        value = row.get(key)
        if value is None or value == "":
            continue
        compact[key] = value
    if "process" not in compact and compact.get("command"):
        compact["process"] = compact["command"]
    return compact


def _running_application_keys(
    process_rows: list[dict[str, Any]],
    apps: list[dict[str, Any]] | None = None,
    process_index: list[tuple[str, dict[str, Any]]] | None = None,
) -> set[str]:
    running: set[str] = set()
    apps = apps if apps is not None else [_application_identity_from_path(path) for path in _discover_application_paths()]
    gui_candidates = _running_gui_app_candidates()
    if gui_candidates:
        for app in apps:
            if _application_matches_gui_candidate(app, gui_candidates):
                running.add(str(app["id"]))
        return running
    process_index = process_index if process_index is not None else _process_match_index(process_rows)
    for app in apps:
        for text, _row in process_index:
            if _application_matches_process_text(app, text):
                running.add(str(app["id"]))
                break
    return running


def _application_processes(
    app: dict[str, Any],
    process_rows: list[dict[str, Any]],
    process_index: list[tuple[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    process_index = process_index if process_index is not None else _process_match_index(process_rows)
    matched = []
    for text, row in process_index:
        if _application_matches_process_text(app, text):
            matched.append(_compact_application_process(row))
    return matched[:20]


def _load_process_rows(refresh: bool = False) -> list[dict[str, Any]]:
    try:
        payload = get_cleanhouse_monitoring_adapter().get_processes(refresh=refresh)
    except Exception:
        return []
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rows = data.get("processes", []) if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def list_applications_payload(refresh: bool = False) -> dict[str, Any]:
    discovered_at = _now_iso()
    process_rows = _load_process_rows(refresh=refresh)
    process_index = _process_match_index(process_rows)
    discovered_apps = [_application_identity_from_path(path) for path in _discover_application_paths()]
    running_ids = _running_application_keys(process_rows, discovered_apps, process_index)
    state = _read_app_inventory_state()
    known = state.get("apps", {}) if isinstance(state.get("apps"), dict) else {}
    apps = []
    inventory_limit = max(1, APPLICATION_INVENTORY_LIMIT)
    for app in discovered_apps[:inventory_limit]:
        previous = known.get(app["id"]) if isinstance(known.get(app["id"]), dict) else None
        first_seen = str(previous.get("first_seen_at")) if previous else discovered_at
        app["first_seen_at"] = first_seen
        app["last_seen_at"] = discovered_at
        app["adopted"] = True
        app["badge"] = "" if previous else "New"
        app["badge_count"] = 0 if previous else 1
        app["running"] = app["id"] in running_ids
        app["audit_status"] = "new" if not previous else "adopted"
        app["processes"] = _application_processes(app, process_rows, process_index)
        apps.append(app)
        known[app["id"]] = {
            "name": app["name"],
            "bundle_id": app["bundle_id"],
            "path": app["path"],
            "first_seen_at": first_seen,
            "last_seen_at": discovered_at,
        }
    _write_app_inventory_state({"schema": "cleanhouse.application_inventory.v1", "updated_at": discovered_at, "apps": known})
    apps.sort(key=lambda item: (item.get("category") == "other", str(item.get("name", "")).lower()))
    return {
        "status": "ok",
        "schema": "cleanhouse.applications.v1",
        "discovered_at": discovered_at,
        "count": len(apps),
        "total_count": len(discovered_apps),
        "limit": inventory_limit,
        "truncated": len(discovered_apps) > len(apps),
        "new_count": sum(1 for app in apps if app.get("badge")),
        "apps": apps,
        "sources": [str(path) for path in APPLICATION_SEARCH_ROOTS],
    }


def _find_application_by_id(app_id: str, refresh: bool = False) -> dict[str, Any] | None:
    for app in list_applications_payload(refresh=refresh).get("apps", []):
        if app_id in {str(app.get("id")), str(app.get("bundle_id")), str(app.get("path")), str(app.get("name")).lower()}:
            return app
    return None


def _find_application_icon_subject(app_id: str) -> dict[str, Any] | None:
    target = str(app_id or "").strip()
    if not target:
        return None
    state = _read_app_inventory_state()
    known = state.get("apps", {}) if isinstance(state.get("apps"), dict) else {}
    for known_id, row in known.items():
        if not isinstance(row, dict):
            continue
        candidates = {
            str(known_id),
            str(row.get("bundle_id") or ""),
            str(row.get("path") or ""),
            str(row.get("name") or "").lower(),
        }
        if target in candidates:
            return {
                "id": str(known_id),
                "name": str(row.get("name") or "App"),
                "bundle_id": str(row.get("bundle_id") or ""),
                "path": str(row.get("path") or ""),
            }
    for app_path in _discover_application_paths():
        app = _application_identity_from_path(app_path)
        if target in {str(app.get("id")), str(app.get("bundle_id")), str(app.get("path")), str(app.get("name")).lower()}:
            return app
    return None


def _app_icon_file(app_path: Path) -> Path | None:
    info = _app_info_plist(app_path)
    resources = app_path / "Contents" / "Resources"
    raw_icon = info.get("CFBundleIconFile") or info.get("CFBundleIconName")
    candidates = []
    if raw_icon:
        icon_name = str(raw_icon)
        candidates.append(resources / icon_name)
        if not icon_name.endswith(".icns"):
            candidates.append(resources / f"{icon_name}.icns")
    try:
        candidates.extend(sorted(resources.glob("*.icns")))
    except Exception:
        pass
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _fallback_icon_svg(label: str) -> Response:
    initials = "".join(part[:1] for part in str(label or "App").split()[:2]).upper() or "A"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#8fd3c7"/><stop offset="1" stop-color="#5267f5"/></linearGradient></defs>
<rect width="128" height="128" rx="28" fill="url(#g)"/>
<text x="64" y="74" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="38" font-weight="700" fill="white">{initials}</text>
</svg>"""
    return Response(svg, mimetype="image/svg+xml")


def application_icon_response(app_id: str):
    app = _find_application_icon_subject(app_id)
    if not app:
        return _fallback_icon_svg("App")
    app_path = Path(str(app.get("path", "")))
    icon_file = _app_icon_file(app_path)
    if not icon_file:
        return _fallback_icon_svg(str(app.get("name", "App")))
    cache_dir = _app_icon_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    png_path = cache_dir / f"{app['id']}.png"
    if not png_path.exists() or png_path.stat().st_mtime < icon_file.stat().st_mtime:
        result = _run_local_command(["/usr/bin/sips", "-s", "format", "png", str(icon_file), "--out", str(png_path)], timeout=5.0)
        if result.get("returncode") != 0 or not png_path.exists():
            return send_file(str(icon_file), mimetype="image/icns")
    return send_file(str(png_path), mimetype="image/png")


def _run_local_command(args: list[str], timeout: float = 3.0) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "status": "observed",
            "args": args,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"status": "unknown", "args": args, "reason": "command not found"}
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "args": args, "reason": "command timed out"}
    except Exception as exc:
        return {"status": "unknown", "args": args, "reason": str(exc) or exc.__class__.__name__}


def _resolve_application_target(raw_target: Any) -> tuple[str, Path]:
    raw = str(raw_target or "terminal").strip()
    target = raw.lower()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.suffix == ".app":
            return _artifact_id(str(candidate)), candidate
    path = APPLICATION_TARGETS.get(target)
    if path is not None:
        return target, path
    for key, candidate in APPLICATION_TARGETS.items():
        if target in {candidate.name.lower(), candidate.stem.lower()}:
            return key, candidate
    app = _find_application_by_id(target)
    if app and app.get("path"):
        return str(app.get("id") or target), Path(str(app["path"]))
    return "terminal", APPLICATION_TARGETS["terminal"]


def _read_application_identity(app_key: str, app_path: Path) -> dict[str, Any]:
    info_path = app_path / "Contents" / "Info.plist"
    info: dict[str, Any] = {}
    if info_path.exists():
        try:
            with info_path.open("rb") as fh:
                info = plistlib.load(fh)
        except Exception:
            info = {}
    codesign = _run_local_command(["/usr/bin/codesign", "-dv", "--verbose=4", str(app_path)])
    signature_lines = [
        line.strip()
        for line in str(codesign.get("stderr", "")).splitlines()
        if line.strip().startswith(("Authority=", "TeamIdentifier=", "Signature=", "Runtime Version="))
    ]
    mdls = _run_local_command([
        "/usr/bin/mdls",
        "-raw",
        "-name",
        "kMDItemAppStoreHasReceipt",
        "-name",
        "kMDItemWhereFroms",
        str(app_path),
    ])
    install_source = "unknown"
    if mdls.get("status") == "observed" and mdls.get("returncode") == 0:
        stdout = str(mdls.get("stdout", "")).strip()
        if stdout and "(null)" not in stdout:
            install_source = stdout
    return {
        "name": info.get("CFBundleDisplayName") or info.get("CFBundleName") or app_path.stem,
        "target_key": app_key,
        "path": str(app_path),
        "version": info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "unknown",
        "bundle_id": info.get("CFBundleIdentifier") or "unknown",
        "code_signature": {
            "status": "observed" if codesign.get("returncode") == 0 else "unknown",
            "summary": signature_lines or ["codesign metadata unavailable"],
        },
        "install_source": install_source,
        "evidence": {
            "info_plist": str(info_path),
            "codesign": codesign,
            "mdls": mdls,
        },
    }


def _parse_ps_snapshot(app_path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    ps = _run_local_command(["/bin/ps", "-axo", "pid,ppid,%cpu,rss,lstart,comm,command"], timeout=4.0)
    bundle_id = str(identity.get("bundle_id", ""))
    app_stem = app_path.stem.lower()
    rows: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    if ps.get("status") == "observed" and ps.get("stdout"):
        lines = str(ps["stdout"]).splitlines()
        for line in lines[1:]:
            parts = line.split(None, 9)
            if len(parts) < 10:
                continue
            row = {
                "pid": parts[0],
                "ppid": parts[1],
                "cpu_percent": parts[2],
                "rss_kb": parts[3],
                "launch_time": " ".join(parts[4:9]),
                "comm": parts[9] if len(parts) == 10 else "",
                "command": parts[-1],
            }
            haystack = f"{row['comm']} {row['command']}".lower()
            if str(app_path).lower() in haystack or app_stem in haystack or bundle_id.lower() in haystack:
                rows.append(row)
        pids = {row["pid"] for row in rows}
        for line in lines[1:]:
            parts = line.split(None, 9)
            if len(parts) < 10:
                continue
            if parts[1] in pids and parts[0] not in pids:
                children.append({
                    "pid": parts[0],
                    "ppid": parts[1],
                    "cpu_percent": parts[2],
                    "rss_kb": parts[3],
                    "launch_time": " ".join(parts[4:9]),
                    "command": parts[-1],
                })
    return {
        "status": "observed" if rows else "unknown",
        "processes": rows,
        "child_processes": children,
        "evidence": ps,
    }


def _network_snapshot(runtime: dict[str, Any]) -> dict[str, Any]:
    process_pids = {str(row.get("pid")) for row in runtime.get("processes", [])}
    lsof = _run_local_command(["/usr/sbin/lsof", "-nP", "-iTCP"], timeout=4.0)
    rows: list[dict[str, Any]] = []
    if lsof.get("status") == "observed" and lsof.get("stdout"):
        for line in str(lsof["stdout"]).splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9:
                continue
            if parts[1] in process_pids:
                rows.append({
                    "command": parts[0],
                    "pid": parts[1],
                    "protocol": parts[7],
                    "connection": parts[8],
                    "state": parts[9] if len(parts) > 9 else "",
                })
    return {
        "status": "observed" if rows else "unknown",
        "connections": rows,
        "domains": [],
        "protocols": sorted({row["protocol"] for row in rows}),
        "evidence": lsof,
    }


def _file_activity_snapshot(identity: dict[str, Any], session_id: str) -> dict[str, Any]:
    app_name = str(identity.get("name", "")).lower()
    bundle_id = str(identity.get("bundle_id", "")).lower()
    try:
        event_rows = events.list_events(limit=200, session_id=session_id)
    except Exception:
        event_rows = []
    related = []
    for row in event_rows:
        text = json.dumps(row, default=str).lower()
        if app_name and app_name in text or bundle_id and bundle_id in text:
            related.append(row)
    return {
        "status": "observed" if related else "unknown",
        "files_read": [],
        "files_written": [
            row.get("path")
            for row in related
            if str(row.get("event_type", "")).lower() in {"created", "modified", "deleted"}
        ],
        "recent_modifications": related[:20],
        "unknown_reason": "" if related else "No app-specific file events found in the current CleanHouse event store.",
    }


def _permissions_snapshot(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "granted": [],
        "missing": [],
        "unknown": [
            {
                "permission": "macOS TCC permissions",
                "reason": "macOS does not expose a complete readable permission ledger to this local route.",
                "evidence_level": "unknown",
            },
            {
                "permission": "file-read access",
                "reason": "CleanHouse can observe some filesystem events, but cannot prove every file read for this app from current evidence.",
                "evidence_level": "unknown",
            },
        ],
    }


def _parse_process_launch_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(" ".join(str(value).split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _runtime_hours(processes: list[dict[str, Any]], created_at: str) -> float | None:
    launched = [
        parsed
        for parsed in (_parse_process_launch_time(str(row.get("launch_time", ""))) for row in processes)
        if parsed is not None
    ]
    if not launched:
        return None
    try:
        observed_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception:
        observed_at = datetime.now(timezone.utc)
    return max(0.0, (observed_at - min(launched)).total_seconds() / 3600.0)


def _human_runtime_duration(hours: float | None) -> str:
    if hours is None:
        return "an unknown duration"
    if hours >= 24:
        days = int(hours // 24)
        remaining_hours = int(hours % 24)
        return f"{days} day(s), {remaining_hours} hour(s)"
    if hours >= 1:
        return f"{hours:.1f} hour(s)"
    return f"{max(1, int(hours * 60))} minute(s)"


def _terminal_finding_title(
    identity: dict[str, Any],
    runtime: dict[str, Any],
    network: dict[str, Any],
    file_activity: dict[str, Any],
    runtime_hours: float | None,
) -> str:
    child_commands = [str(row.get("command", "")).lower() for row in runtime.get("child_processes", [])]
    if any("node" in command for command in child_commands):
        return "Long-running Node Process" if runtime_hours and runtime_hours >= 1 else "Node Process Running Under Terminal"
    if runtime.get("child_processes"):
        return "Unexpected Child Process Spawned"
    if network.get("connections"):
        return "Active Network Connection During Idle State"
    if file_activity.get("recent_modifications"):
        return "Repeated File Access Pattern"
    if runtime.get("processes"):
        return "Persistent Background Activity Detected"
    return f"{identity.get('name', 'Application')} Activity Could Not Be Confirmed"


def _terminal_finding_summary(
    identity: dict[str, Any],
    runtime: dict[str, Any],
    runtime_duration: str,
) -> str:
    child_count = len(runtime.get("child_processes", []))
    process_count = len(runtime.get("processes", []))
    if child_count:
        return f"{identity['name']} is running with {process_count} process record(s) and {child_count} child process(es) after {runtime_duration}."
    if process_count:
        return f"{identity['name']} is still running after {runtime_duration}."
    return f"{identity['name']} was identified, but no running process row was matched in this snapshot."


def _write_investigation_artifacts(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_root = Path(os.getenv("CLEANHOUSE_INVESTIGATION_DIR", Path.home() / "Documents" / "CleanHouse" / "Data" / "investigations"))
    evidence_dir = artifact_root / "evidence"
    receipt_dir = artifact_root / "receipts"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    investigation_id = payload["investigation_id"]
    evidence_path = evidence_dir / f"{investigation_id}.json"
    receipt_path = receipt_dir / f"{investigation_id}.json"
    evidence_ref = f"local://cleanhouse/application-investigation/evidence/{investigation_id}"
    receipt_ref = f"local://cleanhouse/application-investigation/receipt/{investigation_id}"
    for finding in payload.get("finding_objects", []):
        if not finding.get("evidence_refs"):
            finding["evidence_refs"] = [evidence_ref]
        if not finding.get("receipt_ref"):
            finding["receipt_ref"] = receipt_ref
    evidence_payload = {
        "schema": "cleanhouse.application_investigation_evidence.v1",
        "created_at": payload["created_at"],
        "investigation_id": investigation_id,
        "target": payload["identity"],
        "finding_objects": payload.get("finding_objects", []),
        "raw_evidence": payload["raw_evidence"],
    }
    receipt_payload = {
        "schema": "cleanhouse.application_investigation_receipt.v1",
        "created_at": payload["created_at"],
        "investigation_id": investigation_id,
        "question": payload["question"],
        "target": payload["identity"]["name"],
        "findings": payload["findings"],
        "finding_objects": payload.get("finding_objects", []),
        "next_action": payload["next_action"],
        "evidence_artifact_path": str(evidence_path),
    }
    evidence_path.write_text(json.dumps(evidence_payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt_payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return (
        {
            "path": str(evidence_path),
            "ref": evidence_ref,
        },
        {
            "path": str(receipt_path),
            "ref": receipt_ref,
        },
    )


def run_application_investigation(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    session_id, reason = _resolve_session_id(payload.get("session_id"), required=False)
    if reason:
        return reason[0]
    question = str(payload.get("question") or "Why is this application behaving this way?").strip()
    app_key, app_path = _resolve_application_target(payload.get("target") or payload.get("application"))
    created_at = _now_iso()
    identity = _read_application_identity(app_key, app_path)
    runtime = _parse_ps_snapshot(app_path, identity)
    network = _network_snapshot(runtime)
    file_activity = _file_activity_snapshot(identity, session_id)
    permissions = _permissions_snapshot(identity)
    observed = []
    inferred = []
    unknown = []
    observed.append(f"Identified {identity['name']} at {identity['path']} with bundle_id={identity['bundle_id']}.")
    if runtime["processes"]:
        observed.append(f"Observed {len(runtime['processes'])} running process record(s) for {identity['name']}.")
    else:
        unknown.append(f"No running process record was observed for {identity['name']} in the process snapshot.")
    if network["connections"]:
        observed.append(f"Observed {len(network['connections'])} network connection(s) owned by the target process.")
    else:
        unknown.append("No target-owned network connections were observed in this snapshot.")
    if file_activity["recent_modifications"]:
        observed.append(f"Observed {len(file_activity['recent_modifications'])} recent app-related filesystem event(s).")
    else:
        unknown.append(file_activity["unknown_reason"])
    inferred.append("Runtime behavior is inferred from process snapshot rows matched to the application path, name, or bundle identifier.")
    if not permissions["granted"]:
        unknown.append("Permission state is not fully observable from this local evidence path.")
    next_action = (
        "If the application still seems wrong, keep it open and rerun this investigation while reproducing the behavior."
        if runtime["processes"]
        else f"Open {identity['name']} and rerun the investigation while reproducing the behavior."
    )
    investigation_id = "appinv-" + _artifact_id(session_id, app_key, question, created_at)
    primary_observed = (
        f"Observed {len(runtime['processes'])} running process record(s) for {identity['name']}."
        if runtime["processes"]
        else f"No running process record was observed for {identity['name']} in the process snapshot."
    )
    runtime_age_hours = _runtime_hours(runtime["processes"], created_at)
    runtime_duration = _human_runtime_duration(runtime_age_hours)
    child_count = len(runtime["child_processes"])
    if child_count:
        observed.append(f"Observed {child_count} child process(es) spawned under {identity['name']}.")
    primary_severity = "Medium" if runtime["processes"] else "Low"
    primary_confidence = 82 if runtime["processes"] else 54
    evidence_strength = "Strong" if runtime["processes"] else "Limited"
    evidence_strength_basis = (
        "Matched process snapshot evidence to the Terminal application identity."
        if runtime["processes"]
        else "Application identity was observed, but no running process row was matched."
    )
    finding_title = _terminal_finding_title(identity, runtime, network, file_activity, runtime_age_hours)
    finding_summary = _terminal_finding_summary(identity, runtime, runtime_duration)
    finding_objects = [
        {
            "id": f"{investigation_id}-process-activity",
            "title": finding_title,
            "status": "open",
            "severity": primary_severity,
            "confidence": primary_confidence,
            "evidence_strength": evidence_strength,
            "evidence_strength_basis": evidence_strength_basis,
            "timestamp": created_at,
            "timeline_anchor": created_at,
            "summary": finding_summary,
            "observed": [
                f"Identified {identity['name']} at {identity['path']} with bundle_id={identity['bundle_id']}.",
                primary_observed,
                f"Runtime duration: {runtime_duration}.",
                f"Child processes observed: {child_count}.",
            ],
            "inferred": [
                "Runtime behavior is inferred from process snapshot rows matched to the application path, name, or bundle identifier.",
            ],
            "unknown": [
                item
                for item in (
                    None if runtime["processes"] else primary_observed,
                    "Permission state is not fully observable from this local evidence path.",
                    "No target-owned network connections were observed in this snapshot." if not network["connections"] else None,
                    file_activity["unknown_reason"] if not file_activity["recent_modifications"] else None,
                )
                if item
            ],
            "evidence_status": "Available",
            "evidence_refs": [],
            "receipt_ref": "",
            "next_action": next_action,
        }
    ]
    report = {
        "status": "ok",
        "investigation_id": investigation_id,
        "created_at": created_at,
        "session_id": session_id,
        "question": question,
        "type": "application",
        "identity": identity,
        "permissions": permissions,
        "runtime_activity": {
            "launch_time": runtime["processes"][0]["launch_time"] if runtime["processes"] else "unknown",
            "memory": runtime["processes"][0]["rss_kb"] + " KB" if runtime["processes"] else "unknown",
            "cpu": runtime["processes"][0]["cpu_percent"] + "%" if runtime["processes"] else "unknown",
            "child_processes": runtime["child_processes"],
            "processes": runtime["processes"],
        },
        "file_activity": file_activity,
        "network_activity": {
            "connections": network["connections"],
            "domains": network["domains"],
            "protocols": network["protocols"],
        },
        "findings": {
            "observed": observed,
            "inferred": inferred,
            "unknown": unknown,
        },
        "finding_objects": finding_objects,
        "next_action": next_action,
        "raw_evidence": {
            "identity": identity.get("evidence", {}),
            "runtime": runtime.get("evidence", {}),
            "network": network.get("evidence", {}),
            "file_activity": file_activity.get("recent_modifications", []),
        },
    }
    evidence_artifact, receipt_artifact = _write_investigation_artifacts(report)
    report["evidence"] = {
        "evidence_refs": [evidence_artifact["ref"], receipt_artifact["ref"]],
        "evidence_artifact_path": evidence_artifact["path"],
        "receipt_artifact_path": receipt_artifact["path"],
    }
    for finding in report["finding_objects"]:
        finding["evidence_refs"] = [evidence_artifact["ref"]]
        finding["receipt_ref"] = receipt_artifact["ref"]
    return report


def _investigation_timeout_seconds() -> float:
    raw = os.getenv("CLEANHOUSE_INVESTIGATION_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 30.0
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    return value if value > 0 else 30.0


def _application_investigation_timeout_payload(payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    from backend import runtime_supervisor

    created_at = _now_iso()
    target = str(payload.get("target") or payload.get("application") or "application")
    self_deviation_state = runtime_supervisor.record_runtime_self_deviation(
        action="investigation_timeout",
        reason_codes=["investigation_timeout"],
        runtime_state="degraded",
        evidence={
            "timeout_seconds": timeout_seconds,
            "target": target,
            "question": str(payload.get("question") or ""),
            "observed_behavior": f"CleanHouse application investigation exceeded {timeout_seconds:g} seconds.",
        },
    )
    self_deviation = self_deviation_state.get("self_deviation", {})
    finding = dict(self_deviation["finding"])
    return {
        "status": "degraded",
        "runtime_state": "degraded",
        "reason_codes": ["investigation_timeout"],
        "created_at": created_at,
        "type": "application",
        "target": target,
        "summary": f"Investigation timed out after {timeout_seconds:g} seconds.",
        "finding_objects": [finding],
        "evidence": {
            "evidence_refs": [self_deviation["evidence_ref"], self_deviation["receipt_ref"]],
            "evidence_artifact_path": self_deviation["evidence_artifact_path"],
            "receipt_artifact_path": self_deviation["receipt_artifact_path"],
        },
        "self_deviation": self_deviation,
        "next_action": self_deviation.get("next_action") or "Stop or restart CleanHouse before running this investigation again.",
    }


def _application_investigation_paused_payload(payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    created_at = _now_iso()
    target = str(payload.get("target") or payload.get("application") or "application")
    self_deviation = runtime.get("self_deviation") if isinstance(runtime.get("self_deviation"), dict) else {}
    finding = dict(self_deviation.get("finding") or {})
    evidence_refs = [
        ref for ref in (
            self_deviation.get("evidence_ref"),
            self_deviation.get("receipt_ref"),
        )
        if ref
    ]
    return {
        "status": "degraded",
        "runtime_state": str(runtime.get("runtime_state") or "degraded"),
        "reason_codes": sorted(set([str(reason) for reason in runtime.get("reason_codes", []) if str(reason)] + ["runtime_self_deviation_restart_blocked"])),
        "created_at": created_at,
        "type": "application",
        "target": target,
        "summary": "Investigation paused because CleanHouse runtime is unsafe.",
        "finding_objects": [finding] if finding else [],
        "evidence": {
            "evidence_refs": evidence_refs,
            "evidence_artifact_path": self_deviation.get("evidence_artifact_path"),
            "receipt_artifact_path": self_deviation.get("receipt_artifact_path"),
        },
        "self_deviation": self_deviation,
        "next_action": self_deviation.get("next_action") or "Review the runtime self-deviation before starting another investigation.",
    }


def run_application_investigation_with_timeout(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend import runtime_supervisor

    request_payload = payload or {}
    runtime = runtime_supervisor.current_runtime_payload(probe=False)
    self_deviation = runtime.get("self_deviation") if isinstance(runtime.get("self_deviation"), dict) else {}
    blocked = runtime.get("blocked_recovery") if isinstance(runtime.get("blocked_recovery"), dict) else {}
    backend_payload = runtime.get("backend") if isinstance(runtime.get("backend"), dict) else {}
    supervisor_payload = runtime.get("supervisor") if isinstance(runtime.get("supervisor"), dict) else {}
    runtime_active = bool(backend_payload.get("alive")) or bool(supervisor_payload.get("alive"))
    if (
        bool(self_deviation.get("blocks_investigations"))
        or (runtime_active and str(blocked.get("type") or "") in runtime_supervisor.SELF_DEVIATION_BLOCK_TYPES)
    ):
        return _application_investigation_paused_payload(request_payload, runtime)

    timeout_seconds = _investigation_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cleanhouse-app-investigation")
    future = executor.submit(run_application_investigation, request_payload)
    try:
        result = future.result(timeout=timeout_seconds)
    except TimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        return _application_investigation_timeout_payload(request_payload, timeout_seconds)
    finally:
        if future.done():
            executor.shutdown(wait=True, cancel_futures=False)
    return result


def _fast_operator_api_enabled() -> bool:
    return os.getenv("CLEANHOUSE_FAST_OPERATOR_API", "1").strip().lower() in {"1", "true", "yes", "on"}


def _event_spine_payload(*, include_latest: bool = False) -> dict[str, Any]:
    try:
        if include_latest:
            payload = events.get_runtime_status()
        else:
            watcher = events.get_watcher_status()
            writer = events.get_writer_health()
            reasons = []
            for name, state in (("watcher", watcher), ("writer", writer)):
                degradation = state.get("degradation") if isinstance(state, dict) else {}
                if isinstance(degradation, dict) and degradation.get("degraded"):
                    reasons.append({
                        "surface": name,
                        "collector_status": state.get("collector_status", "unknown"),
                        "reasons": list(degradation.get("reasons", [])),
                    })
            payload = {
                "status": "degraded" if reasons else "ok",
                "watcher": watcher,
                "writer": writer,
                "queue": writer.get("queue", {}) if isinstance(writer, dict) else {},
                "last_event_at": None,
                "last_event_id": None,
                "last_event_type": None,
                "last_event_error": None,
                "degradation": {"degraded": bool(reasons), "reasons": reasons},
            }
    except Exception as exc:
        return {
            "status": "degraded",
            "watcher": {"status": "unknown", "collector_status": "unknown"},
            "writer": {
                "status": "unknown",
                "collector_status": "failure",
                "queue_depth": None,
                "queue_maxsize": None,
                "queue": {},
                "metrics": {"dropped": 0, "write_failures": 1},
                "timestamps": {},
                "last_error": {"source": "event_spine", "message": str(exc) or exc.__class__.__name__},
            },
            "queue": {},
            "last_event_at": None,
            "last_event_id": None,
            "last_event_type": None,
            "last_event_error": {"source": "event_spine", "message": str(exc) or exc.__class__.__name__},
            "degradation": {
                "degraded": True,
                "reasons": [{"surface": "event_writer", "collector_status": "failure", "reasons": ["event_spine_unavailable"]}],
            },
        }
    return payload if isinstance(payload, dict) else {"status": "degraded", "degradation": {"degraded": True, "reasons": []}}


def _event_spine_surfaces(event_spine: dict[str, Any]) -> dict[str, dict[str, Any]]:
    watcher = event_spine.get("watcher", {}) if isinstance(event_spine.get("watcher"), dict) else {}
    writer = event_spine.get("writer", {}) if isinstance(event_spine.get("writer"), dict) else {}
    return {
        "filesystem_watcher": {
            "status": watcher.get("status", "unknown"),
            "state": watcher.get("state", watcher.get("status", "unknown")),
            "collector_status": watcher.get("collector_status", "unknown"),
            "dependency_available": watcher.get("dependency_available"),
            "support_status": watcher.get("support_status", "unknown"),
            "unsupported_reason": watcher.get("unsupported_reason"),
            "watch_dir": watcher.get("watch_dir"),
            "last_error": watcher.get("last_error"),
            "degradation": watcher.get("degradation", {"degraded": False, "reasons": []}),
        },
        "event_writer": {
            "status": writer.get("status", "unknown"),
            "state": writer.get("state", writer.get("status", "unknown")),
            "collector_status": writer.get("collector_status", "unknown"),
            "support_status": writer.get("support_status", "unknown"),
            "unsupported_reason": writer.get("unsupported_reason"),
            "queue_depth": writer.get("queue_depth"),
            "queue_maxsize": writer.get("queue_maxsize"),
            "queue": writer.get("queue", {}),
            "metrics": writer.get("metrics", {}),
            "timestamps": writer.get("timestamps", {}),
            "last_event_at": event_spine.get("last_event_at"),
            "last_event_id": event_spine.get("last_event_id"),
            "last_event_type": event_spine.get("last_event_type"),
            "last_error": writer.get("last_error") or event_spine.get("last_event_error"),
            "degradation": writer.get("degradation", {"degraded": False, "reasons": []}),
        },
    }


def _event_spine_collector_health(surfaces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    degraded: list[dict[str, Any]] = []
    unknown: list[str] = []
    unsupported: list[str] = []
    healthy_count = 0
    for name, surface in surfaces.items():
        collector_status = str(surface.get("collector_status", "unknown") or "unknown")
        support_status = str(surface.get("support_status", "unknown") or "unknown")
        degradation = surface.get("degradation") if isinstance(surface.get("degradation"), dict) else {}
        if support_status == "unsupported":
            unsupported.append(name)
        if collector_status in {"unknown", "inactive"}:
            unknown.append(name)
        if collector_status == "ok" and not degradation.get("degraded"):
            healthy_count += 1
            continue
        degraded.append({
            "surface": name,
            "status": surface.get("status", "unknown"),
            "collector_status": collector_status,
            "reasons": list(degradation.get("reasons", [])) or [collector_status],
        })
    return {
        "status": "degraded" if degraded else "ok",
        "surface_count": len(surfaces),
        "healthy_count": healthy_count,
        "degraded_count": len(degraded),
        "unknown": unknown,
        "unsupported": unsupported,
        "degraded_surfaces": degraded,
    }


def _notification_policy_contract() -> dict[str, Any]:
    return {
        "codex_prompt_sent": "persist_only",
        "hard_interrupt_types": ["session_started", "session_ended", "scope_drift_detected"],
        "native_dispatch_contract": "production_operator_only",
    }


def _fast_runtime_payload(*, probe: bool = False, write: bool = False) -> dict[str, Any]:
    try:
        from backend import runtime_supervisor

        payload = runtime_supervisor.current_runtime_payload(probe=probe, write=write)
    except Exception as exc:
        payload = {
            "status": "unhealthy",
            "runtime_state": "unhealthy",
            "operator_ready": False,
            "reason_codes": ["runtime_supervisor_unavailable"],
            "error": str(exc) or exc.__class__.__name__,
            "supervisor": {},
            "backend": {},
            "listener": {},
            "heartbeat": {},
            "last_probe": {},
            "resource_guard": {},
            "self_deviation": {},
            "interpreter": {},
            "last_start_attempt": {},
            "blocked_recovery": {
                "status": "blocked",
                "type": "runtime_supervisor_unavailable",
                "reason": str(exc) or exc.__class__.__name__,
            },
            "recovery_receipts": [],
            "state_path": "",
            "updated_at": "",
        }
    if not isinstance(payload, dict):
        payload = {}

    raw_recovery_receipts = payload.get("recovery_receipts", [])
    normalized_receipts: list[dict[str, Any]] = []
    if isinstance(raw_recovery_receipts, list):
        for item in raw_recovery_receipts[:10]:
            if isinstance(item, dict):
                normalized_receipts.append(item)
                continue
            value = str(item or "").strip()
            if value:
                normalized_receipts.append({"id": value})
    payload["recovery_receipts"] = normalized_receipts

    payload.setdefault("report_executor", {"status": "unknown"})
    payload.setdefault("resource_guard", {})
    payload.setdefault("self_deviation", {})
    payload.setdefault("notifications", {
        "status": "unknown",
        "delivery_count": 0,
        "failure_count": 0,
        "visibility_risk_count": 0,
        "recent": [],
    })
    payload.setdefault("runtime_notifications", [])
    payload.setdefault("visibility_proof_summary", {"transport_only": 0, "operator_confirmed": 0, "unknown": 0})
    payload.setdefault("visibility_state", {"risk_notifications": 0, "unacknowledged": 0})
    payload.setdefault("active_context", {
        "status": "unavailable",
        "follow_enabled": False,
        "ignored_count": 0,
        "active_context": None,
    })
    payload.setdefault("presence_mode", {"enabled": False, "loop_started": False, "last_domain_health_count": 0})
    payload.setdefault("domain_observer_matrix", {"generated_at": payload.get("updated_at", ""), "domains": {}})
    payload.setdefault("connected_accounts", {"status": "unknown", "count": 0, "entries": []})
    event_spine = _event_spine_payload(include_latest=False)
    payload["event_spine"] = event_spine
    payload["event_writer"] = event_spine.get("writer", {})
    payload["filesystem_watcher"] = event_spine.get("watcher", {})
    payload["notification_policy_contract"] = _notification_policy_contract()
    payload["response_mode"] = "fast"
    return payload


def _runtime_readiness_payload() -> dict[str, Any]:
    try:
        from backend import runtime_supervisor

        payload = runtime_supervisor.readiness_payload()
        if not isinstance(payload, dict):
            raise ValueError("runtime readiness payload is not an object")
        contract = payload.get("readiness_contract")
        if not isinstance(contract, dict):
            raise ValueError("runtime readiness contract is missing")
        if contract.get("schema") != "cleanhouse.runtime_operator_readiness.v1":
            raise ValueError("runtime readiness contract schema is invalid")
        if not isinstance(contract.get("satisfied"), bool):
            raise ValueError("runtime readiness contract result is invalid")
        if not isinstance(payload.get("ready"), bool):
            raise ValueError("runtime readiness result is invalid")
        if payload["ready"] is not contract["satisfied"]:
            raise ValueError("runtime readiness result disagrees with its contract")
    except Exception as exc:
        return {
            "status": "degraded",
            "ready": False,
            "bootstrap_ready": False,
            "runtime_state": "unavailable",
            "reason_codes": ["runtime_supervisor_unavailable"],
            "readiness_contract": {
                "schema": "cleanhouse.runtime_operator_readiness.v1",
                "satisfied": False,
                "checks": {"evaluation_available": False},
                "failed_checks": ["evaluation_available"],
            },
            "runtime": {
                "status": "unavailable",
                "runtime_state": "unavailable",
                "operator_ready": False,
                "reason_codes": ["runtime_supervisor_unavailable"],
            },
            "error": exc.__class__.__name__,
        }
    payload = dict(payload)
    payload["network_collector"] = network_collector_health(allow_keychain_read=False)
    payload["network_vvault"] = _network_vvault_readiness(allow_keychain_read=False)
    return payload


def _fast_status_payload() -> dict[str, Any]:
    runtime = _fast_runtime_payload(probe=False, write=False)
    runtime_state = str(runtime.get("runtime_state", "unknown") or "unknown")
    reason_codes = [str(code) for code in runtime.get("reason_codes", []) if str(code)]
    issues: list[dict[str, Any]] = []
    status = "safe"
    if runtime_state == "unhealthy":
        status = "critical"
        issues.append({
            "id": "runtime:unhealthy",
            "source": "runtime",
            "severity": "critical",
            "message": f"runtime unhealthy ({', '.join(reason_codes) or 'no reason codes'})",
            "evidence": {"status": "observed", "runtime_state": runtime_state, "reason_codes": reason_codes},
        })
    elif runtime_state != "healthy":
        status = "warning"
        issues.append({
            "id": "runtime:degraded",
            "source": "runtime",
            "severity": "warning",
            "message": f"runtime degraded ({', '.join(reason_codes) or 'no reason codes'})",
            "evidence": {"status": "observed", "runtime_state": runtime_state, "reason_codes": reason_codes},
        })

    event_spine = runtime.get("event_spine", {}) if isinstance(runtime.get("event_spine"), dict) else {}
    event_surfaces = _event_spine_surfaces(event_spine)
    event_health = _event_spine_collector_health(event_surfaces)
    for surface in event_health["degraded_surfaces"]:
        severity = "critical" if surface.get("collector_status") == "failure" else "warning"
        issues.append({
            "id": f"event-spine:{surface.get('surface', 'unknown')}",
            "source": "event_spine",
            "severity": severity,
            "message": f"{surface.get('surface', 'unknown')} degraded ({', '.join(surface.get('reasons', [])) or 'no reason codes'})",
            "evidence": {"status": "observed", **surface},
        })
        if status != "critical":
            status = "critical" if severity == "critical" else "warning"

    surfaces = {
        "runtime": {
            "status": runtime_state,
            "collector_status": "ok" if runtime_state == "healthy" else "failure" if runtime_state == "unhealthy" else "degraded",
            "issue_count": len(issues),
        },
        **event_surfaces,
    }
    degraded_surfaces = [] if not issues else [{
        "surface": "runtime",
        "status": runtime_state,
        "collector_status": surfaces["runtime"]["collector_status"],
        "reasons": reason_codes or [runtime_state],
    }] if runtime_state != "healthy" else []
    degraded_surfaces.extend(event_health["degraded_surfaces"])
    collector_health = {
        "status": "ok" if not degraded_surfaces else "degraded",
        "surface_count": len(surfaces),
        "healthy_count": sum(1 for surface in surfaces.values() if surface.get("collector_status") == "ok"),
        "degraded_count": len(degraded_surfaces),
        "unknown": event_health["unknown"],
        "unsupported": event_health["unsupported"],
        "degraded_surfaces": degraded_surfaces,
    }
    degradation = {
        "status": collector_health["status"],
        "degraded": bool(issues),
        "reasons": collector_health["degraded_surfaces"],
    }

    return {
        "status": status,
        "issues": issues,
        "data": {
            "sections": {},
            "runtime": runtime,
            "collector_manifest": {
                "schema": "cleanhouse.collector_manifest.v1",
                "generated_at": payload_ts(runtime),
                "surfaces": surfaces,
                "runtime": {"runtime_state": runtime_state, "reason_codes": reason_codes},
                "event_spine": event_spine,
                "notification_policy_contract": runtime.get("notification_policy_contract", {}),
                "collector_health": collector_health,
                "degradation": degradation,
            },
            "collector_health": collector_health,
            "degradation": degradation,
        },
        "response_mode": "fast",
    }


def payload_ts(runtime: dict[str, Any]) -> str:
    heartbeat = runtime.get("heartbeat", {}) if isinstance(runtime.get("heartbeat"), dict) else {}
    return str(runtime.get("updated_at") or heartbeat.get("at") or "")


def _fast_scope_evidence_payload(session_id: str | None) -> dict[str, Any]:
    empty = {
        "deviation_signals": {"signals": [], "alerts": [], "signal_count": 0, "alert_count": 0},
        "evidence_summaries": [],
        "receipts": [],
        "approvals": [],
        "scope_evidence_status": "not_requested",
    }
    if not session_id:
        return empty

    try:
        adapter = get_cleanhouse_monitoring_adapter()
        receipts = adapter.get_receipts(session_id=session_id, max_records=LOW_PROCESSING_RECEIPT_LIMIT).get("receipts", [])
        alerts = adapter.get_alerts(session_id=session_id).get("alerts", [])
        approvals = adapter.get_approval_queue(session_id=session_id, max_records=LOW_PROCESSING_APPROVAL_LIMIT).get("approval_queue", [])
        summaries = []
        summary_builder = getattr(adapter, "_build_workstation_evidence_summaries", None)
        if callable(summary_builder):
            summaries = summary_builder(
                session_id=session_id,
                receipts=receipts,
                alerts=alerts,
                approvals=approvals,
            )
        return {
            "deviation_signals": {
                "signals": [],
                "alerts": alerts,
                "signal_count": 0,
                "alert_count": len(alerts),
            },
            "evidence_summaries": summaries,
            "receipts": receipts,
            "approvals": approvals,
            "scope_evidence_status": "ok",
        }
    except Exception as exc:
        payload = dict(empty)
        payload["scope_evidence_status"] = "unavailable"
        payload["scope_evidence_error"] = str(exc) or exc.__class__.__name__
        return payload


def _fast_workstation_payload(session_id: str | None, *, include_scope_evidence: bool = False) -> dict[str, Any]:
    resolved_session_id = session_id or os.getenv("CLEANHOUSE_SESSION_ID", DEFAULT_SESSION_ID)
    runtime = _fast_runtime_payload(probe=False, write=False)
    runtime_state = str(runtime.get("runtime_state", "unknown") or "unknown")
    degraded = runtime_state != "healthy"
    scope_evidence = (
        _fast_scope_evidence_payload(resolved_session_id)
        if include_scope_evidence
        else {
            "deviation_signals": {"signals": [], "alerts": [], "signal_count": 0, "alert_count": 0},
            "evidence_summaries": [],
            "receipts": [],
            "approvals": [],
            "scope_evidence_status": "not_requested",
        }
    )
    return {
        "status": "ok",
        "session_id": resolved_session_id,
        "objective_id": "",
        "runtime_state": runtime_state,
        "operator_ready": bool(runtime.get("operator_ready", False)),
        "runtime": runtime,
        "alerts": scope_evidence["deviation_signals"]["alerts"],
        "timeline": [],
        "signals": scope_evidence["deviation_signals"]["signals"],
        "receipts": scope_evidence["receipts"],
        "approvals": scope_evidence["approvals"],
        "active_context": runtime.get("active_context", {}),
        "domain_observer_matrix": runtime.get("domain_observer_matrix", {"generated_at": payload_ts(runtime), "domains": {}}),
        "deviation": {
            "status": "degraded" if degraded else "ok",
            "degraded": degraded,
            "reason_codes": [str(code) for code in runtime.get("reason_codes", []) if str(code)],
        },
        "deviation_signals": scope_evidence["deviation_signals"],
        "evidence_summaries": scope_evidence["evidence_summaries"],
        "scope_evidence_status": scope_evidence["scope_evidence_status"],
        "response_mode": "fast",
    }


def _extract_authenticated_user_id():
    auth_header = str(request.headers.get("Authorization", "") or "").strip()
    match = re.fullmatch(r"Bearer\s+(\S+)", auth_header)
    if not match:
        return None, _auth_error_response("Authorization header must be in the format: Bearer <token>")
    token = match.group(1).strip()
    user = get_user_from_token(token)
    if not isinstance(user, dict):
        return None, _auth_error_response("Invalid or expired token")
    user_id = str(user.get("user_id", "") or "").strip()
    if not user_id:
        return None, _auth_error_response("Token does not include user_id")
    return user_id, None


def _optional_positive_int_arg(name: str, *, max_value: int = 500):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, _error_response(f"{name} must be an integer")
    if value < 1:
        return None, _error_response(f"{name} must be at least 1")
    if value > max_value:
        return None, _error_response(f"{name} exceeds maximum")
    return value, None


def _extract_evidence_request(payload: dict[str, Any] | None = None):
    if payload is None:
        get_param = lambda key: request.args.get(key)
    else:
        get_param = lambda key: payload.get(key)

    ref_raw = get_param("ref")
    ref, error = _require_string(ref_raw, "ref", required=False, allow_empty=True, max_len=2048)
    if error:
        return None, error

    source_view_raw = get_param("source_view")
    source_view, error = _require_string(source_view_raw, "source_view", required=False, allow_empty=True, max_len=64)
    if error:
        return None, error

    if ref:
        return {
            "mode": "ref",
            "surface": "network",
            "source_view": source_view or "",
            "ref": ref,
        }, None

    surface_raw = get_param("surface")
    surface, error = _require_string(surface_raw, "surface", max_len=64)
    if error:
        return None, _error_response("Either ref, or surface and entity_id are required")

    entity_id, error = _require_string(get_param("entity_id"), "entity_id", max_len=512)
    if error:
        return None, error

    return {
        "mode": "pair",
        "surface": surface,
        "entity_id": entity_id,
        "source_view": source_view or "",
    }, None


def _resolve_evidence_context(data: dict[str, Any]):
    resolver = get_evidence_context_resolver()
    source_view = data.get("source_view")
    if data.get("mode") == "ref":
        return resolver.resolve_from_ref(data["ref"], source_view=source_view)
    return resolver.resolve(data["surface"], data["entity_id"], source_view=source_view)


def _find_evidence_action(context, action_id: str):
    actions = get_evidence_context_resolver().actions(context)
    for action in actions:
        if action.get("id") == action_id:
            return action
    return None


_REPORTABLE_CTRL_ACTION_IDS = {
    "mark_read",
    "mark_unread",
    "observe",
    "restrict",
    "block",
    "quarantine",
    "terminate",
    "export",
    "copy",
    "allow",
}


def _normalize_action_origin(value: Any) -> str:
    candidate = (str(value or "") or "").strip().lower()
    return candidate if candidate in {"ctrl", "scan"} else ""


def _normalize_subject_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    name = str(value.get("name") or value.get("display_name") or value.get("displayName") or "").strip()
    subject_type = str(value.get("type") or value.get("subject_type") or value.get("subjectType") or "").strip()
    return {
        "name": name,
        "type": subject_type,
    }


def _normalize_optional_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {str(k): v for k, v in value.items()}


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, str):
            continue
        item_text = item.strip()
        if item_text and item_text not in normalized:
            normalized.append(item_text)
    return normalized


def _normalize_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _bounded_text(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    return text[:max_len] if text else ""


def _normalize_network_tags_override(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    tags: dict[str, Any] = {}
    for key in ("status", "state", "explanation"):
        text = _bounded_text(value.get(key), max_len=160)
        if text:
            tags[key] = text
    reasons = _normalize_string_list(value.get("reasons"))[:8]
    if reasons:
        tags["reasons"] = reasons
    return tags or None


def _merge_evidence_context_override(context: EvidenceContext, override: dict[str, Any] | None) -> EvidenceContext:
    if not override or context.source_surface != "network":
        return context
    source_entity_id = _bounded_text(override.get("source_entity_id"), max_len=512) or context.source_entity_id
    evidence_key = _bounded_text(override.get("evidence_key"), max_len=512)
    if not evidence_key and source_entity_id.startswith("network:"):
        evidence_key = source_entity_id
    if not evidence_key:
        evidence_key = context.evidence_key
    evidence_refs = _normalize_string_list(override.get("evidence_refs")) or list(context.evidence_refs)
    summary = _bounded_text(override.get("summary"), max_len=900) or context.summary
    severity = _bounded_text(override.get("severity"), max_len=64) or context.severity
    validation_state = _bounded_text(override.get("validation_state"), max_len=64) or context.validation_state
    timeline_event_id = _bounded_text(override.get("timeline_event_id"), max_len=512) or context.timeline_event_id
    network_reasons = _normalize_string_list(override.get("network_reasons"))[:8] or list(context.network_reasons)
    network_tags = _normalize_network_tags_override(override.get("network_tags")) or context.network_tags
    origin = _bounded_text(override.get("origin"), max_len=2048) or context.origin
    return EvidenceContext(
        evidence_key=evidence_key,
        source_surface=context.source_surface,
        source_view=_bounded_text(override.get("source_view"), max_len=64) or context.source_view,
        source_entity_id=source_entity_id,
        evidence_refs=evidence_refs,
        summary=summary,
        severity=severity,
        validation_state=validation_state,
        open_back_route=context.open_back_route,
        timeline_event_id=timeline_event_id,
        network_tags=network_tags,
        network_reasons=network_reasons,
        origin=origin,
        trace_id=context.trace_id,
    )


def _should_create_evidence_action_report(*, action_id: str, action_origin: str, create_report: bool) -> bool:
    normalized_origin = _normalize_action_origin(action_origin)
    normalized_action = str(action_id or "").strip()
    if not bool(create_report) or not normalized_action:
        return False
    return normalized_origin in {"ctrl", "scan"} and normalized_action in _REPORTABLE_CTRL_ACTION_IDS


def _persist_evidence_insight_audit(context, selected_action: dict[str, Any], result: dict[str, Any], *, invoker: str, role: str) -> dict[str, Any]:
    resolver = get_evidence_context_resolver()
    audit_entry = resolver.audit_entry(context, action_id="ask_insight", invoker=invoker, role=role)
    service = get_apple_intelligence_insight_service()
    audit_entry["outcome_type"] = "apple_intelligence_evidence_insight"
    audit_entry["voice_role"] = selected_action.get("voice_role") or "Insight"
    audit_entry["backend_roles"] = selected_action.get("backend_roles") or []
    audit_entry["capability_source"] = "apple_intelligence_foundation_models"
    audit_entry["apple_intelligence"] = result.get("apple_intelligence") or {}
    audit_entry["request_context"] = result.get("evidence_context") or {}
    audit_entry["response_summary"] = service.audit_summary(result)
    get_cleanhouse_monitoring_adapter()._persist_action_outcome(audit_entry)
    return audit_entry


def _validate_events_rows_payload(rows: Any):
    if not isinstance(rows, list):
        return _error_response("events payload schema invalid")
    required = ("id", "timestamp", "session_id", "event_type", "path", "summary")
    for row in rows:
        if not isinstance(row, dict):
            return _error_response("events payload schema invalid")
        if any(key not in row for key in required):
            return _error_response("events payload schema invalid")
        event_id = row.get("id")
        if not isinstance(event_id, (str, int)) or not str(event_id).strip():
            return _error_response("events payload schema invalid")
        for key in ("timestamp", "session_id", "event_type", "path", "summary"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                return _error_response("events payload schema invalid")
        if not isinstance(row.get("observed_vs_expected", {}), dict):
            return _error_response("events payload schema invalid")
        if not isinstance(row.get("evidence_refs", []), list):
            return _error_response("events payload schema invalid")
        for ref in row.get("evidence_refs", []):
            if not isinstance(ref, (str, dict)):
                return _error_response("events payload schema invalid")
        if not isinstance(row.get("data", {}), dict):
            return _error_response("events payload schema invalid")
    return None


def _validate_receipts_rows_payload(rows: Any):
    if not isinstance(rows, list):
        return _error_response("receipts payload schema invalid")
    required = ("id", "timestamp", "session_id", "summary", "event_ids")
    for row in rows:
        if not isinstance(row, dict):
            return _error_response("receipts payload schema invalid")
        if any(key not in row for key in required):
            return _error_response("receipts payload schema invalid")
        receipt_id = row.get("id")
        if not isinstance(receipt_id, (str, int)) or not str(receipt_id).strip():
            return _error_response("receipts payload schema invalid")
        for key in ("timestamp", "session_id", "summary"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                return _error_response("receipts payload schema invalid")
        if not isinstance(row.get("event_ids", []), list):
            return _error_response("receipts payload schema invalid")
        if any(
            not isinstance(event_id, (str, int)) or not str(event_id).strip()
            for event_id in row.get("event_ids", [])
        ):
            return _error_response("receipts payload schema invalid")
        if not isinstance(row.get("affected_paths", []), list):
            return _error_response("receipts payload schema invalid")
        if any(not isinstance(path, str) for path in row.get("affected_paths", [])):
            return _error_response("receipts payload schema invalid")
    return None


def _login_report_http_status(payload: dict[str, Any]) -> int:
    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
    state = job.get("state")
    if payload.get("status") == "rate_limited" or state == "rejected":
        return 429
    if payload.get("status") == "accepted" or state in {"queued", "running"}:
        return 202
    return 200


@bp.after_request
def _add_local_cors_headers(response):
    origin = request.headers.get("Origin")
    parsed = _require_allowed_origin(origin)
    if parsed[1]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@bp.route("/health", methods=["GET"])
def health():
    from backend import runtime_supervisor

    return jsonify({
        "schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA,
        "status": "ok",
        "alive": True,
        "pid": os.getpid(),
        "boot_id": os.getenv("CLEANHOUSE_BACKEND_BOOT_ID") or None,
    })


@bp.route("/cleanhouse/status", methods=["GET"])
def status():
    if request.args.get("ready", "").lower() in {"1", "true", "yes", "on"}:
        payload = _runtime_readiness_payload()
        runtime_payload = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        payload.setdefault("reason_codes", [str(code) for code in runtime_payload.get("reason_codes", []) if str(code)])
        payload["operator_warning"] = (
            "CleanHouse is unhealthy: runtime memory ceiling exceeded. Backend stopped. Evidence and receipt available."
            if "runtime_memory_ceiling_exceeded" in set(runtime_payload.get("reason_codes", []))
            else ""
        )
        return jsonify(payload)
    if _fast_operator_api_enabled() and not _truthy_arg("full"):
        return jsonify(_fast_status_payload())

    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_status(refresh=_refresh_flag()))


@bp.route("/cleanhouse/runtime", methods=["GET"])
def runtime():
    if _fast_operator_api_enabled() and not _truthy_arg("full"):
        return jsonify(_fast_runtime_payload(probe=False, write=False))
    return jsonify(get_cleanhouse_monitoring_adapter().get_runtime())


@bp.route("/cleanhouse/processes", methods=["GET"])
def processes():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_processes(refresh=_refresh_flag()))


@bp.route("/cleanhouse/applications", methods=["GET"])
def applications():
    return jsonify(list_applications_payload(refresh=_refresh_flag()))


@bp.route("/cleanhouse/applications/<app_id>/icon.png", methods=["GET"])
def application_icon(app_id: str):
    return application_icon_response(app_id)


@bp.route("/cleanhouse/allowed-threats", methods=["GET"])
def allowed_threats_list():
    state = _read_allowed_threats_state()
    items = state.get("allowed_threats", [])
    if not isinstance(items, list):
        items = []
    return jsonify({
        "status": "ok",
        "allowed_threats": items,
        "count": len(items),
    })


@bp.route("/cleanhouse/allowed-threats", methods=["POST"])
def allowed_threats_create():
    payload, error = _parse_json_payload()
    if error:
        return error
    state = _read_allowed_threats_state()
    items = state.get("allowed_threats", [])
    if not isinstance(items, list):
        items = []
    item = _allowed_threat_from_payload(payload)
    items.insert(0, item)
    state["allowed_threats"] = items
    state["updated_at"] = item["updated_at"]
    _write_allowed_threats_state(state)
    return jsonify({
        "status": "ok",
        "allowed_threat": item,
        "count": len(items),
    })


@bp.route("/cleanhouse/allowed-threats/<allowed_id>", methods=["DELETE"])
def allowed_threats_delete(allowed_id: str):
    state = _read_allowed_threats_state()
    items = state.get("allowed_threats", [])
    if not isinstance(items, list):
        items = []
    remaining = [item for item in items if not isinstance(item, dict) or str(item.get("id", "")) != allowed_id]
    if len(remaining) == len(items):
        return jsonify({"status": "error", "message": "Allowed threat not found"}), 404
    state["allowed_threats"] = remaining
    state["updated_at"] = _now_iso()
    _write_allowed_threats_state(state)
    return jsonify({
        "status": "ok",
        "allowed_threats": remaining,
        "count": len(remaining),
    })


@bp.route("/cleanhouse/scan/system", methods=["POST"])
def system_scan():
    apps = list_applications_payload(refresh=True)
    processes_payload = get_cleanhouse_monitoring_adapter().get_processes(refresh=True)
    network_payload = get_cleanhouse_monitoring_adapter().get_network(refresh=True)
    process_data = processes_payload.get("data", {}) if isinstance(processes_payload, dict) else {}
    network_data = network_payload.get("data", {}) if isinstance(network_payload, dict) else {}
    findings: list[dict[str, Any]] = []
    for app in apps.get("apps", []) if isinstance(apps.get("apps"), list) else []:
        if not isinstance(app, dict) or not app.get("badge"):
            continue
        findings.append({
            "threat_name": "New Application Detected",
            "severity": "info",
            "target_type": "application",
            "target_name": str(app.get("name", "") or "Unavailable"),
            "target_path": str(app.get("path", "") or ""),
            "source": "applications",
            "reason": "Application has not been previously adopted by CleanHouse.",
            "recommended_action": "Inspect application identity and activity.",
            "evidence_refs": [],
            "receipt_ref": "",
            "allowable": True,
        })
    for issue in process_data.get("issues", []) if isinstance(process_data.get("issues"), list) else []:
        findings.append(_scan_finding_from_issue(issue, source="processes", fallback_name="Process Finding"))
    for issue in network_data.get("issues", []) if isinstance(network_data.get("issues"), list) else []:
        findings.append(_scan_finding_from_issue(issue, source="network", fallback_name="Network Finding"))
    finding_count = len(findings)
    scan_id = "system-scan-" + _artifact_id(_now_iso(), str(apps.get("count", 0)), str(finding_count))
    return jsonify({
        "status": "ok",
        "scan_id": scan_id,
        "scope": "whole_system",
        "summary": "Whole system scan completed with app inventory, process, and network evidence.",
        "finding_count": finding_count,
        "findings": findings,
        "threats": findings,
        "evidence_ref": f"local://cleanhouse/system-scan/evidence/{scan_id}",
        "receipt_ref": f"local://cleanhouse/system-scan/receipt/{scan_id}",
        "next_action": "Review applications with badges or attention states first.",
        "areas": {
            "applications": {"status": "ok", "count": apps.get("count", 0), "new_count": apps.get("new_count", 0)},
            "processes": {"status": processes_payload.get("status", "unknown")},
            "network": {"status": network_payload.get("status", "unknown")},
            "communications": {"status": "covered_by_app_filters"},
            "files": {"status": "available"},
        },
    })


def _cleanhouse_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundled_wireshark_root() -> Path:
    return _cleanhouse_root() / "bundled" / "wireshark" / "darwin-arm64"


def _bundled_wireshark_paths() -> dict[str, Path]:
    root = _bundled_wireshark_root()
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "tshark": root / "bin" / "tshark",
        "dumpcap": root / "bin" / "dumpcap",
    }


NETWORK_STATUS_TAGS = {"OBSERVING", "QUIET", "LOCAL ONLY", "OFFLINE"}
NETWORK_STATE_TAGS = {"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"}
NETWORK_DEGRADED_REASONS = {
    "Destination name missing",
    "Unknown app active",
    "New destination seen",
    "Many destinations contacted",
    "High connection volume",
    "Unusual port used",
    "Unencrypted web request",
    "Capture engine limited",
    "Permission blocks capture",
    "Fallback mode active",
    "Interface changed",
    "Connection attempts failed",
    "Local traffic only",
}
NETWORK_CRITICAL_REASONS = {
    "Known malicious endpoint",
    "Blocked threat active",
    "Data exfiltration suspected",
    "Malware process active",
    "Suspicious listener exposed",
    "Repeated failed connections",
    "Unsigned app communicating",
    "Unexpected inbound access",
    "Privilege process online",
    "Quarantine bypass suspected",
}


def _network_tag_reason_from_summary(reason: str) -> str:
    mapping = {
        "permission_blocked": "Permission blocks capture",
        "capture_failed": "Capture engine limited",
        "engine_unavailable": "Capture engine limited",
        "capture_backlog": "Capture engine limited",
        "timeout": "Connection attempts failed",
        "fallback_mode": "Fallback mode active",
        "local_only": "Local traffic only",
    }
    return mapping.get(str(reason or ""), "")


def _network_event_critical_reason(event: dict[str, Any]) -> str:
    text = " ".join(str(event.get(key) or "") for key in ("reason", "severity", "category", "meaning", "summary")).lower()
    if event.get("known_malicious") or "known malicious" in text:
        return "Known malicious endpoint"
    if "blocked threat" in text:
        return "Blocked threat active"
    if "exfil" in text:
        return "Data exfiltration suspected"
    if "malware" in text:
        return "Malware process active"
    if "suspicious listener" in text:
        return "Suspicious listener exposed"
    if "unexpected inbound" in text:
        return "Unexpected inbound access"
    if "quarantine bypass" in text:
        return "Quarantine bypass suspected"
    return ""


def _network_event_degraded_reason(event: dict[str, Any]) -> str:
    if str(event.get("event_type") or "") == NETWORK_TIMELINE_GAP_EVENT_TYPE:
        return "Capture engine limited"
    external = bool(event.get("dst_ip")) and not _is_local_network_host(str(event.get("dst_ip") or ""))
    if event.get("suspicious") and _network_event_app(event) == "Unknown app":
        return "Unknown app active"
    if external and _network_event_app(event) == "Unknown app":
        return "Unknown app active"
    if external and not (event.get("dns_query") or event.get("http_host") or event.get("tls_sni")):
        return "Destination name missing"
    if external and str(event.get("dst_port") or "") == "80":
        return "Unencrypted web request"
    common_ports = {"", "22", "25", "53", "80", "123", "443", "465", "587", "993", "995", "5223", "5228", "5353"}
    if external and str(event.get("dst_port") or "") not in common_ports:
        return "Unusual port used"
    return ""


def _network_fixed_tags(ui_state: str, events_payload: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    reason = _network_tag_reason_from_summary(str(summary.get("reason") or ""))
    if ui_state in {"ERROR", "CAPTURE_BLOCKED"}:
        return _network_tags("OFFLINE", "DEGRADED", [reason or "Capture engine limited"], reason or "Capture engine limited")
    if ui_state == "WARMING":
        return _network_tags("QUIET", "DEGRADED", ["Restarting"], "Waiting for network capture after restart.")
    if not events_payload:
        if ui_state == "READY":
            return _network_tags("OBSERVING", "HEALTHY", [], "Capture is running and awaiting network traffic.")
        return _network_tags("QUIET", "HEALTHY", [], "No recent network activity is visible.")
    external = [
        item for item in events_payload
        if (item.get("dst_ip") and not _is_local_network_host(str(item.get("dst_ip") or "")))
        or int(item.get("externalOnlyCount") or 0) > 0
    ]
    status = "LOCAL ONLY" if not external else "OBSERVING"
    critical_reason = next((item for item in (_network_event_critical_reason(event) for event in events_payload) if item), "")
    if critical_reason:
        return _network_tags(status, "CRITICAL", [critical_reason], critical_reason)
    degraded_reason = next((item for item in (_network_event_degraded_reason(event) for event in events_payload) if item), "")
    if degraded_reason:
        return _network_tags(status, "DEGRADED", [degraded_reason], degraded_reason)
    if len(events_payload) >= 150:
        return _network_tags(status, "DEGRADED", ["High connection volume"], "High connection volume")
    return _network_tags(status, "HEALTHY", [], "Network activity is being observed.")


def _network_ui_contract(
    state: str,
    *,
    events: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    status_code: int = 200,
) -> tuple[dict[str, Any], int]:
    ui_state = state if state in NETWORK_UI_STATES else "ERROR"
    safe_events = events if isinstance(events, list) else []
    safe_summary = summary.copy() if isinstance(summary, dict) else {}
    if ui_state != "ERROR":
        safe_summary.setdefault("event_count", len(safe_events))
    return {
        "state": ui_state,
        "server_boot_id": NETWORK_SERVER_BOOT_ID,
        "vvault": _network_vvault_readiness(),
        "tags": _network_fixed_tags(ui_state, safe_events, safe_summary),
        "events": safe_events,
        "summary": safe_summary,
    }, status_code


def _network_collector_contract(health: dict[str, Any] | None) -> tuple[str, str]:
    """Map collector evidence onto the existing Network UI vocabulary."""
    safe_health = health if isinstance(health, dict) else {}
    collector_state = str(safe_health.get("state") or safe_health.get("status") or "stopped").lower()
    reason_code = str(safe_health.get("reason_code") or "").lower()
    last_error = str(safe_health.get("last_error") or "").lower()
    evidence = f"{reason_code} {last_error}"
    if collector_state == "running":
        return "CAPTURING", "events_observed" if int(safe_health.get("last_packet_sequence") or 0) > 0 else "no_data"
    if collector_state == "starting":
        return "WARMING", "waiting_for_capture"
    if collector_state == "blocked" or "permission" in evidence or "operation not permitted" in evidence:
        return "CAPTURE_BLOCKED", "permission_blocked"
    if "engine_unavailable" in evidence or "capture_engine_unavailable" in evidence:
        return "ERROR", "engine_unavailable"
    if collector_state in {"degraded", "stopped", "stopping"}:
        return "ERROR", "capture_failed"
    return "ERROR", "capture_failed"


def _network_apply_collector_truth(payload: dict[str, Any], health: dict[str, Any] | None) -> dict[str, Any]:
    """Keep request/data success separate from capture-engine health."""
    safe_health = dict(health) if isinstance(health, dict) else {}
    capture_state, capture_reason = _network_collector_contract(safe_health)
    events_payload = payload.get("events") if isinstance(payload.get("events"), list) else []
    summary = dict(payload.get("summary")) if isinstance(payload.get("summary"), dict) else {}
    summary["capture_state"] = str(safe_health.get("state") or safe_health.get("status") or "stopped").lower()
    ingestion_latency_ms = safe_health.get("ingestion_latency_ms")
    try:
        capture_backlogged = (
            capture_state == "CAPTURING"
            and ingestion_latency_ms is not None
            and float(ingestion_latency_ms) > NETWORK_CAPTURE_STALE_AFTER_MS
        )
    except (TypeError, ValueError):
        capture_backlogged = False
    if capture_backlogged:
        capture_reason = "capture_backlog"
    summary["capture_reason"] = capture_reason
    summary["data_state"] = "stale" if capture_backlogged else ("available" if events_payload else "no_data")
    if capture_state in {"ERROR", "CAPTURE_BLOCKED", "WARMING"}:
        summary["reason"] = capture_reason
    elif capture_backlogged:
        summary["reason"] = capture_reason
    elif events_payload:
        summary.setdefault("reason", "events_observed")
    else:
        summary["reason"] = "no_data"
    payload["state"] = capture_state
    payload["summary"] = summary
    payload["tags"] = _network_fixed_tags(capture_state, events_payload, summary)
    if capture_backlogged:
        payload["tags"] = _network_tags(
            payload["tags"].get("status") or "OBSERVING",
            "DEGRADED",
            ["Capture engine limited"],
            "Captured evidence is delayed while the bounded ingestion pipeline catches up.",
        )
    payload["collector"] = safe_health
    payload["powered_by_wireshark"] = bool(
        capture_state == "CAPTURING"
        and int(safe_health.get("last_packet_sequence") or 0) > 0
    )
    return payload


def _network_error_contract(reason: str, *, status_code: int = 400) -> tuple[dict[str, Any], int]:
    return _network_ui_contract(
        "ERROR",
        events=[],
        summary={"reason": reason},
        status_code=status_code,
    )


def _network_vvault_readiness(*, allow_keychain_read: bool = True) -> dict[str, Any]:
    return vvault_sync.status(surface="network", allow_keychain_read=allow_keychain_read)


def _network_vvault_required_error() -> tuple[dict[str, Any], int] | None:
    if not _truthy_arg("require_vvault") or _network_vvault_readiness()["ready"]:
        return None
    return _network_error_contract("vvault_persistence_unavailable", status_code=503)


def _network_capture_blocked_contract() -> tuple[dict[str, Any], int]:
    return _network_ui_contract(
        "CAPTURE_BLOCKED",
        events=[],
        summary={"reason": "permission_blocked"},
        status_code=200,
    )


def _bundled_wireshark_error(
    code: str,
    public_message: str,
    *,
    engine_state: str = "failed",
    reason: str = "Capture engine limited",
    explanation: str | None = None,
) -> tuple[dict[str, Any], int]:
    reason_map = {
        "engine_not_initialized": "engine_unavailable",
        "engine_failed": "capture_failed",
        "invalid_capture_duration": "capture_failed",
        "capture_timeout": "timeout",
        "capture_permission_denied": "permission_blocked",
        "capture_failed": "capture_failed",
    }
    safe_reason = reason_map.get(code, "capture_failed")
    if safe_reason == "permission_blocked":
        return _network_capture_blocked_contract()
    return _network_error_contract(safe_reason)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_bundled_wireshark_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not manifest_path.exists():
        return None, "missing_manifest"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, "invalid_manifest"
    if not isinstance(payload, dict):
        return None, "invalid_manifest"
    return payload, None


def _manifest_hash(manifest: dict[str, Any], relative_path: str) -> str | None:
    for section_name in ("components", "files"):
        section = manifest.get(section_name)
        if not isinstance(section, dict) or relative_path not in section:
            continue
        entry = section[relative_path]
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
            return entry["sha256"]
    return None


def _parse_dumpcap_interfaces(output: str) -> list[dict[str, str]]:
    interfaces = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\.\s+([^\s]+)(?:\s+\((.*)\))?$", line)
        if match:
            interface_id, name, label = match.groups()
            interfaces.append({
                "id": interface_id,
                "name": name,
                "label": label or name,
            })
        else:
            interfaces.append({
                "id": str(len(interfaces) + 1),
                "name": line,
                "label": line,
            })
    return interfaces


def _wireshark_permission_denied(stderr: str) -> bool:
    text = str(stderr or "").lower()
    return (
        "operation not permitted" in text
        or "permission denied" in text
        or "cannot open bpf" in text
        or "/dev/bpf" in text
    )


def _wireshark_capture_error(stderr: str) -> tuple[dict[str, Any], int]:
    if _wireshark_permission_denied(stderr):
        return _bundled_wireshark_error(
            "capture_permission_denied",
            "Packet capture permission is blocked.",
            reason="Permission blocks capture",
            explanation="macOS denied access to the packet capture device.",
        )
    return _bundled_wireshark_error("capture_failed", "Capture system unavailable.")


def _bundled_wireshark_engine_interfaces() -> tuple[list[dict[str, str]], tuple[dict[str, Any], int] | None]:
    paths = _bundled_wireshark_paths()
    manifest, manifest_error = _load_bundled_wireshark_manifest(paths["manifest"])
    if manifest_error:
        if manifest_error == "missing_manifest":
            return [], _bundled_wireshark_error(
                "engine_not_initialized",
                "Packet capture engine is not available.",
                engine_state="not_ready",
            )
        return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")

    for name in ("tshark", "dumpcap"):
        binary_path = paths[name]
        relative_path = f"bin/{name}"
        if not binary_path.exists():
            return [], _bundled_wireshark_error(
                "engine_not_initialized",
                "Packet capture engine is not available.",
                engine_state="not_ready",
            )
        if not binary_path.is_file():
            return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")
        if not os.access(binary_path, os.X_OK):
            return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")
        expected_hash = _manifest_hash(manifest or {}, relative_path)
        if not expected_hash:
            return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")
        actual_hash = _sha256_file(binary_path)
        if actual_hash.lower() != expected_hash.lower():
            return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")

    try:
        completed = subprocess.run(
            [str(paths["dumpcap"]), "-D"],
            cwd=str(paths["root"]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], _bundled_wireshark_error("engine_failed", "Capture system unavailable.")
    except OSError as exc:
        return [], _bundled_wireshark_error("engine_failed", "Network engine failed to start.")

    if completed.returncode != 0:
        return [], _bundled_wireshark_error("engine_failed", "Capture system unavailable.")

    return _parse_dumpcap_interfaces(completed.stdout), None


def _validate_bundled_wireshark_tools() -> tuple[dict[str, Any], int]:
    interfaces, error = _bundled_wireshark_engine_interfaces()
    if error:
        return error
    return _network_ui_contract(
        "READY",
        summary={
            "reason": "ready",
        },
    )


def _select_capture_interface(interfaces: list[dict[str, str]]) -> str | None:
    requested = request.args.get("interface", "").strip()
    if requested:
        for interface in interfaces:
            if requested in (interface.get("id"), interface.get("name")):
                return interface.get("name")
        return requested
    active_interfaces = _active_capture_interfaces()
    for interface in interfaces:
        name = interface.get("name", "")
        if name in active_interfaces:
            return name
    for preferred in ("en0", "en1"):
        for interface in interfaces:
            if interface.get("name") == preferred:
                return preferred
    for interface in interfaces:
        name = interface.get("name", "")
        if name and not name.startswith(("lo", "utun")):
            return name
    return interfaces[0].get("name") if interfaces else None


def _select_live_capture_interfaces(interfaces: list[dict[str, str]]) -> list[str]:
    requested = request.args.get("interface", "").strip()
    if requested:
        for interface in interfaces:
            if requested in (interface.get("id"), interface.get("name")):
                return [str(interface.get("name") or requested)]
        return [requested]

    available = [str(interface.get("name") or "").strip() for interface in interfaces]
    available = [name for name in available if name]
    active_interfaces = _active_capture_interfaces()
    selected: list[str] = []

    def add(name: str) -> None:
        if name and name in available and name not in selected:
            selected.append(name)

    add("lo0")
    for name in sorted(active_interfaces):
        if not name.startswith("utun"):
            add(name)
    for preferred in ("en0", "en1"):
        add(preferred)

    if selected:
        return selected
    single = _select_capture_interface(interfaces)
    return [single] if single else []


def _active_capture_interfaces() -> set[str]:
    active = set()
    try:
        completed = subprocess.run(
            ["ifconfig"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return active
    current = ""
    block: list[str] = []
    for line in completed.stdout.splitlines():
        if line and not line.startswith(("\t", " ")):
            if current and _ifconfig_block_is_active(block):
                active.add(current)
            current = line.split(":", 1)[0].strip()
            block = [line]
        else:
            block.append(line)
    if current and _ifconfig_block_is_active(block):
        active.add(current)
    return active


def _ifconfig_block_is_active(lines: list[str]) -> bool:
    text = "\n".join(lines).lower()
    return "status: active" in text and ("\n\tinet " in text or "\n inet " in text)


def _layer_value(layers: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = layers.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value:
            return value
    return ""


def _packet_protocol(layers: dict[str, Any]) -> str:
    for protocol in ("http", "dns", "tls", "tcp", "udp", "icmp", "icmpv6", "ipv6", "ip"):
        if protocol in layers:
            return protocol.upper()
    return "UNKNOWN"


def _protocol_from_frame_protocols(value: Any) -> str:
    protocols = str(value or "").lower()
    for protocol in ("http", "dns", "tls", "tcp", "udp", "icmpv6", "icmp", "ipv6", "ip"):
        if protocol in protocols.split(":"):
            return protocol.upper()
    return "UNKNOWN"


def _network_event_summary(event: dict[str, Any]) -> str:
    if event.get("dns_query"):
        return f"DNS lookup for {event['dns_query']}"
    if event.get("http_host"):
        return f"HTTP connection to {event['http_host']}"
    if event.get("tls_sni"):
        return f"TLS connection to {event['tls_sni']}"
    destination = event.get("dst_ip") or "unknown destination"
    protocol = event.get("protocol") or "network"
    port = f":{event['dst_port']}" if event.get("dst_port") else ""
    return f"{protocol} packet to {destination}{port}"


def _is_local_network_host(value: str) -> bool:
    host = str(value or "").strip().lower()
    normalized = host.strip("[]")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        address = None
    if address:
        local_ranges = (
            "10.0.0.0/8",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "224.0.0.0/4",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
            "ff00::/8",
        )
        return any(address in ipaddress.ip_network(cidr) for cidr in local_ranges)
    return (
        not host
        or host == "*"
        or host.startswith("127.")
        or host.startswith("[::1]")
        or host.startswith("::1")
        or host.startswith("localhost")
        or host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("172.16.")
        or host.startswith("[fe80:")
        or "->127." in host
        or "->[::1]" in host
        or "->10." in host
        or "->192.168." in host
        or "->172.16." in host
        or "->[fe80:" in host
    )


def _network_ip_is_multicast(value: Any) -> bool:
    try:
        return ipaddress.ip_address(str(value or "").strip().strip("[]")).is_multicast
    except ValueError:
        return False


def _network_ip_is_link_local(value: Any) -> bool:
    try:
        return ipaddress.ip_address(str(value or "").strip().strip("[]")).is_link_local
    except ValueError:
        return False


def _network_endpoint_is_cloudflare(value: Any) -> bool:
    return _network_ip_in_any_cidr(
        value,
        (
            "104.16.0.0/13",
            "162.158.0.0/15",
            "172.64.0.0/13",
            "2606:4700::/32",
        ),
    )


def _network_endpoint_is_apple_push(value: Any, port: Any) -> bool:
    return str(port or "").strip() == "5223" and _network_ip_in_any_cidr(value, ("17.0.0.0/8",))


def _network_is_mdns_or_bonjour(event: dict[str, Any]) -> bool:
    destination = str(event.get("dst_ip") or "").strip().lower()
    port = str(event.get("dst_port") or event.get("src_port") or "").strip()
    return port == "5353" or destination in {"224.0.0.251", "ff02::fb"} or ".local" in str(event.get("destination_display") or "").lower()


def _network_is_ipv6_neighbor_discovery(event: dict[str, Any]) -> bool:
    protocol = str(event.get("protocol") or "").upper()
    return protocol == "ICMPV6" and (
        _network_ip_is_link_local(event.get("src_ip"))
        or _network_ip_is_link_local(event.get("dst_ip"))
        or _network_ip_is_multicast(event.get("dst_ip"))
    )


def _network_is_routine_local_discovery(event: dict[str, Any]) -> bool:
    if event.get("suspicious") or event.get("known_malicious"):
        return False
    if _network_is_mdns_or_bonjour(event) or _network_is_ipv6_neighbor_discovery(event):
        return True
    app = _network_event_app(event).lower()
    return app == "rapportd" and (
        _network_ip_is_link_local(event.get("src_ip"))
        or _network_ip_is_link_local(event.get("dst_ip"))
    )


def _service_label(port: Any) -> str:
    try:
        value = int(port)
    except (TypeError, ValueError):
        return "Network connection"
    labels = {
        53: "DNS lookup",
        80: "Web request (HTTP)",
        443: "Secure web request (HTTPS)",
        5000: "Local service",
        5050: "Local service",
        5173: "Local app traffic",
        5223: "Apple Push notification channel",
        5228: "Push notification channel",
        5353: "Local device discovery",
        5432: "Local database",
        8000: "Local service",
    }
    return labels.get(value, "Network connection")


def _network_external_service_label(event: dict[str, Any]) -> str:
    destination = str(
        event.get("dns_query")
        or event.get("http_host")
        or event.get("tls_sni")
        or event.get("destination_display")
        or event.get("dst_ip")
        or ""
    ).strip().lower()
    if destination.endswith(".cloudfront.net") or ".cloudfront.net:" in destination:
        return "a CloudFront-hosted service"
    if "akamai" in destination or "akadns" in destination:
        return "an Akamai-hosted content delivery service"
    if _network_endpoint_is_cloudflare(event.get("dst_ip")) or _network_endpoint_is_cloudflare(event.get("src_ip")):
        return "a Cloudflare-hosted service"
    return "an external service"


def _network_external_activity_summary(app: str, event: dict[str, Any]) -> str:
    service = _network_external_service_label(event)
    port = str(event.get("dst_port") or "").strip()
    if port == "443":
        return f"{app} is securely communicating with {service}."
    if port == "80":
        return f"{app} is making an unencrypted web request to {service}."
    return f"{app} is communicating with {service}."


def _network_summary_exposes_raw_external_destination(event: dict[str, Any]) -> bool:
    summary = str(event.get("summary") or "").strip().lower()
    if not summary:
        return False
    destination_values = [
        event.get("destination_display"),
        event.get("dns_query"),
        event.get("http_host"),
        event.get("tls_sni"),
        event.get("dst_ip"),
    ]
    destinations = {str(value or "").strip().lower() for value in destination_values if str(value or "").strip()}
    destinations.update(
        _network_endpoint(value, event.get("dst_port")).lower()
        for value in destination_values
        if str(value or "").strip()
    )
    if " is connecting to " in summary and any(destination and destination in summary for destination in destinations):
        return True
    if ".cloudfront.net" in summary or "akamai" in summary or "akadns" in summary:
        return True
    return bool(re.search(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d+\b", summary))


def _clean_process_name(value: Any) -> str:
    text = str(value or "Unknown app").replace("\\x20", " ").strip()
    return text or "Unknown app"


def _network_endpoint(host: Any, port: Any) -> str:
    host_text = str(host or "").strip()
    if not host_text:
        return "Unavailable"
    port_text = str(port or "").strip()
    return f"{host_text}:{port_text}" if port_text and port_text != "0" else host_text


def _network_event_datetime(value: Any) -> datetime:
    if value is None or value == "":
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 100000000000:
            numeric = numeric / 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    text = str(value).strip()
    try:
        numeric = float(text)
        if numeric > 100000000000:
            numeric = numeric / 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _network_event_iso(value: Any) -> str:
    return _network_event_datetime(value).isoformat().replace("+00:00", "Z")


def _network_event_fingerprint(event: dict[str, Any]) -> str:
    seed = "|".join(
        str(event.get(key) or "")
        for key in (
            "timestamp",
            "packet_index",
            "process",
            "pid",
            "src_ip",
            "src_port",
            "dst_ip",
            "dst_port",
            "dns_query",
            "tls_sni",
            "http_host",
            "protocol",
        )
    )
    return "network:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _network_event_severity(event: dict[str, Any]) -> str:
    text = " ".join(str(event.get(key) or "") for key in ("severity", "reason", "category", "meaning", "summary")).lower()
    if event.get("known_malicious") or "known malicious" in text or "malware" in text or "exfil" in text:
        return "critical"
    if event.get("suspicious") or "suspicious" in text or "unusual" in text or "missing" in text:
        return "warning"
    if _network_event_app(event) == "Unknown app" and not _is_local_network_host(str(event.get("dst_ip") or "")):
        return "warning"
    if _network_is_routine_local_discovery(event):
        return "info"
    if _is_local_network_host(str(event.get("dst_ip") or "")):
        return "info"
    return "low"


def _network_event_confidence(event: dict[str, Any]) -> str:
    if event.get("process") and str(event.get("process")).lower() != "unknown app":
        return "high"
    if event.get("dns_query") or event.get("http_host") or event.get("tls_sni"):
        return "medium"
    return "low"


def _network_event_app(event: dict[str, Any]) -> str:
    app = str(event.get("process") or event.get("app") or event.get("application") or "").strip()
    return app if app and app.lower() not in {"unknown", "unknown app"} else "Unknown app"


def _network_app_name_is_internal_engine(name: Any) -> bool:
    return "wireshark" in str(name or "").strip().lower()


def _network_public_app_name(name: Any) -> str:
    text = str(name or "Unknown app").strip() or "Unknown app"
    return "Network capture subsystem" if _network_app_name_is_internal_engine(text) else text


def _network_app_identity_index(refresh: bool = False) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    try:
        payload = list_applications_payload(refresh=refresh)
    except Exception:
        return {}, []
    apps = payload.get("apps") if isinstance(payload, dict) else []
    index: dict[str, dict[str, Any]] = {}
    running_apps: list[dict[str, Any]] = []
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict):
            continue
        app_name = _network_public_app_name(app.get("name"))
        identity = {
            "process": app_name,
            "app": app_name,
            "app_bundle_id": str(app.get("bundle_id") or ""),
            "app_category": str(app.get("category") or "other"),
            "confidence": "high",
        }
        for value in (app.get("name"), app.get("bundle_id")):
            key = str(value or "").strip().lower()
            if key:
                index[key] = identity
        if app.get("running") and not _network_app_name_is_internal_engine(app.get("name")):
            running_apps.append({
                "name": identity["app"],
                "bundle_id": identity["app_bundle_id"],
                "category": identity["app_category"],
                "observed_network_events": 0,
            })
        for proc in app.get("processes", []) if isinstance(app.get("processes"), list) else []:
            if not isinstance(proc, dict):
                continue
            for value in (proc.get("pid"), proc.get("process"), proc.get("name"), proc.get("command")):
                key = str(value or "").strip().lower()
                if key:
                    index[key] = identity
    return index, running_apps


def _network_identity_from_process(process: Any, pid: Any, app_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for value in (pid, process):
        key = str(value or "").strip().lower()
        if key and key in app_index:
            return app_index[key]
    process_text = str(process or "").strip().lower()
    if process_text:
        for key, identity in app_index.items():
            if key and (key in process_text or process_text in key):
                return identity
    return None


def _network_ip_in_any_cidr(value: Any, cidrs: tuple[str, ...]) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip().strip("[]"))
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if address in ipaddress.ip_network(cidr):
                return True
        except ValueError:
            continue
    return False


def _network_identity_from_destination(event: dict[str, Any], app_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    dst_ip = event.get("dst_ip")
    src_ip = event.get("src_ip")
    cloudflare_ranges = (
        "104.16.0.0/13",
        "162.158.0.0/15",
        "172.64.0.0/13",
        "2606:4700::/32",
    )
    if _network_ip_in_any_cidr(dst_ip, cloudflare_ranges) or _network_ip_in_any_cidr(src_ip, cloudflare_ranges):
        for key, identity in app_index.items():
            if "cloudflare" in key or "warp" in key:
                return identity
    return None


def _network_enrichment_index(refresh: bool = False) -> dict[str, dict[str, Any]]:
    global _NETWORK_RUNNING_APPS, _NETWORK_RUNNING_APPS_AT
    app_index, running_apps = _network_app_identity_index(refresh=False)
    with _NETWORK_RUNNING_APPS_LOCK:
        _NETWORK_RUNNING_APPS = [dict(item) for item in running_apps]
        _NETWORK_RUNNING_APPS_AT = time.monotonic()
    index: dict[str, dict[str, Any]] = _network_lsof_enrichment_index(app_index)
    cloudflare_identity = next(
        (identity for key, identity in app_index.items() if "cloudflare" in key or "warp" in key),
        None,
    )
    if cloudflare_identity:
        index["_cloudflare_identity"] = cloudflare_identity
    if not refresh:
        return index
    try:
        snapshot = get_cleanhouse_monitoring_adapter().get_network(refresh=refresh)
    except Exception:
        return index
    data = snapshot.get("data") if isinstance(snapshot, dict) and isinstance(snapshot.get("data"), dict) else {}
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        process = _clean_process_name(conn.get("process"))
        identity = _network_identity_from_process(process, conn.get("pid"), app_index) or {}
        row = {
            "process": identity.get("process") or process,
            "app": identity.get("app") or process,
            "app_bundle_id": identity.get("app_bundle_id") or "",
            "app_category": identity.get("app_category") or ("system" if process == "System" else "other"),
            "pid": conn.get("pid"),
            "confidence": identity.get("confidence") or ("medium" if process != "Unknown app" else "low"),
        }
        local_host = str(conn.get("local_host") or "").strip()
        local_port = str(conn.get("local_port") or "").strip()
        remote_port = conn.get("remote_port") or conn.get("port")
        remote_port_text = str(remote_port or "").strip()
        if local_port:
            index[f"local_port:{local_port}"] = row
        if local_host and local_port:
            index[f"local:{local_host}:{local_port}"] = row
        for host_key in ("domain", "remote_host", "host", "address"):
            host = str(conn.get(host_key) or "").strip()
            if not host:
                continue
            index[host] = row
            if remote_port:
                index[f"{host}:{remote_port}"] = row
                index[f"remote:{host}:{remote_port}"] = row
            if local_host and local_port:
                index[f"flow:{local_host}:{local_port}->{host}:{remote_port_text}"] = row
    return index


def _network_lsof_enrichment_index(app_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lsof = Path("/usr/sbin/lsof")
    if not lsof.exists():
        return {}
    try:
        completed = subprocess.run(
            [str(lsof), "-nP", "-iTCP", "-iUDP"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode not in (0, 1):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for line in completed.stdout.splitlines()[1:]:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        command, pid, name = _clean_process_name(parts[0]), parts[1], parts[8]
        identity = _network_identity_from_process(command, pid, app_index) or {}
        process = _network_public_app_name(identity.get("process") or command)
        row = {
            "process": process,
            "app": identity.get("app") or process,
            "app_bundle_id": identity.get("app_bundle_id") or "",
            "app_category": identity.get("app_category") or "other",
            "pid": pid,
            "confidence": identity.get("confidence") or "medium",
        }
        endpoint = name.split(" (", 1)[0]
        local, remote = (endpoint.split("->", 1) + [""])[:2] if "->" in endpoint else (endpoint, "")
        local_host, local_port = _split_network_endpoint(local)
        remote_host, remote_port = _split_network_endpoint(remote)
        if local_port:
            index[f"local_port:{local_port}"] = row
        if local_host and local_port:
            index[f"local:{local_host}:{local_port}"] = row
        if remote_host and remote_port:
            index[f"remote:{remote_host}:{remote_port}"] = row
        if local_host and local_port and remote_host and remote_port:
            index[f"flow:{local_host}:{local_port}->{remote_host}:{remote_port}"] = row
    return index


def _split_network_endpoint(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    if text.startswith("[") and "]:" in text:
        host, port = text.rsplit(":", 1)
        return host.strip("[]"), port
    if ":" not in text:
        return text, ""
    host, port = text.rsplit(":", 1)
    return host.strip("[]"), port


def _network_process_command_index() -> dict[str, str]:
    ps = Path("/bin/ps")
    if not ps.exists():
        return {}
    try:
        completed = subprocess.run(
            [str(ps), "-axo", "pid=,command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    index: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, command = parts
        if pid and command:
            index[pid] = command
    return index


def _network_socket_owner_label(command: Any, pid: Any, process_commands: dict[str, str]) -> str:
    raw_command = str(command or "").replace("\\x20", " ").strip()
    pid_text = str(pid or "").strip()
    full_command = process_commands.get(pid_text, "")
    haystack = f"{raw_command} {full_command}".lower()
    if pid_text == str(os.getpid()) or "backend/server.py" in haystack:
        return "CleanHouse Backend"
    if "codex.app" in haystack or raw_command.lower().startswith("codex"):
        return "Codex"
    if "visual studio code.app" in haystack or raw_command.lower() == "code":
        return "Code"
    if "webkit.networking" in haystack:
        return "Safari/WebKit Networking"
    if "safari.app" in haystack or raw_command.lower() == "safari":
        return "Safari"
    if raw_command:
        return raw_command
    return "Unknown app"


def _network_lsof_state_and_endpoint(name: str) -> tuple[str, str]:
    text = str(name or "").strip()
    if text.endswith(")") and " (" in text:
        endpoint, state = text.rsplit(" (", 1)
        return state[:-1].strip(), endpoint.strip()
    return "", text


def _network_socket_event_from_lsof_line(
    line: str,
    *,
    timestamp: str,
    process_commands: dict[str, str],
) -> dict[str, Any] | None:
    parts = line.split(None, 8)
    if len(parts) < 9:
        return None
    command, pid, _user, fd, _fd_type, _device, _size, protocol, name = parts
    protocol = str(protocol or "").upper()
    if protocol not in {"TCP", "UDP"}:
        return None
    state, endpoint = _network_lsof_state_and_endpoint(name)
    local_endpoint, remote_endpoint = (endpoint.split("->", 1) + [""])[:2] if "->" in endpoint else (endpoint, "")
    local_host, local_port = _split_network_endpoint(local_endpoint)
    remote_host, remote_port = _split_network_endpoint(remote_endpoint)
    owner = _network_socket_owner_label(command, pid, process_commands)
    cleanhouse_port = str(os.getenv("CLEANHOUSE_PORT") or "3333")
    if str(command or "").lower().startswith(("python", "python3")) and cleanhouse_port in {str(local_port), str(remote_port)}:
        owner = "CleanHouse Backend"
    if remote_endpoint:
        source_display = _network_endpoint(local_host, local_port)
        destination_display = _network_endpoint(remote_host, remote_port)
        dst_ip = remote_host
        dst_port = remote_port
        role = "connection"
    else:
        source_display = _network_endpoint(local_host, local_port)
        destination_display = f"{state.lower()} on {source_display}" if state else source_display
        dst_ip = local_host
        dst_port = local_port
        role = "listener" if state == "LISTEN" else "socket"
    seed = "|".join([str(pid), fd, protocol, endpoint, state])
    event = {
        "timestamp": timestamp,
        "event_id": "network_socket:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
        "packet_index": None,
        "packet_length": None,
        "process": owner,
        "app": owner,
        "pid": pid,
        "src_ip": local_host,
        "src_port": local_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "protocol": protocol,
        "category": "Local traffic" if _is_local_network_host(str(dst_ip or "")) else "External connection",
        "meaning": "Active socket ownership observed from lsof.",
        "source_display": source_display or "Unavailable",
        "destination_display": destination_display or "Unavailable",
        "severity": "info" if _is_local_network_host(str(dst_ip or "")) else "low",
        "confidence": "high",
        "finding_status": "open",
        "socket_state": state,
        "socket_role": role,
        "socket_name": endpoint,
        "fd": fd,
    }
    semantics = _network_plain_language_semantics(event)
    event["category"] = semantics["category"]
    event["summary"] = semantics["summary"]
    event["meaning"] = semantics["meaning"]
    event["reason"] = semantics["reason"]
    event["system_impact"] = _network_event_system_impact(event)
    event["projection"] = {
        "finding_priority": NETWORK_SEVERITY_RANK.get(str(event["severity"]), 0),
        "system_impact": event["system_impact"],
        "timeline_anchor": timestamp,
    }
    return event


def _network_active_socket_events() -> list[dict[str, Any]]:
    lsof = Path("/usr/sbin/lsof")
    if not lsof.exists():
        return []
    try:
        completed = subprocess.run(
            [str(lsof), "-nP", "-iTCP", "-iUDP"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode not in (0, 1):
        return []
    timestamp = _now_iso()
    process_commands = _network_process_command_index()
    socket_events = []
    for line in completed.stdout.splitlines()[1:]:
        event = _network_socket_event_from_lsof_line(
            line,
            timestamp=timestamp,
            process_commands=process_commands,
        )
        if event:
            socket_events.append(event)
    socket_events.sort(key=lambda item: (str(item.get("process") or "").lower(), str(item.get("pid") or ""), str(item.get("socket_name") or "")))
    return socket_events


def _network_active_connection_count() -> int:
    return sum(1 for event in _network_active_socket_events() if str(event.get("socket_role") or "") == "connection")


def _network_match_enrichment(event: dict[str, Any], enrichment: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    src_ip = str(event.get("src_ip") or "").strip()
    src_port = str(event.get("src_port") or "").strip()
    dst_ip = str(event.get("dst_ip") or "").strip()
    dst_port = str(event.get("dst_port") or "").strip()
    destination = str(
        event.get("dns_query")
        or event.get("http_host")
        or event.get("tls_sni")
        or event.get("dst_ip")
        or ""
    ).strip()
    destination_with_port = _network_endpoint(destination, dst_port)
    keys = [
        f"flow:{src_ip}:{src_port}->{destination}:{dst_port}" if src_ip and src_port and destination else "",
        f"flow:{src_ip}:{src_port}->{dst_ip}:{dst_port}" if src_ip and src_port and dst_ip else "",
        f"local:{src_ip}:{src_port}" if src_ip and src_port else "",
        f"local_port:{src_port}" if src_port else "",
        f"remote:{destination}:{dst_port}" if destination and dst_port else "",
        f"remote:{dst_ip}:{dst_port}" if dst_ip and dst_port else "",
        destination_with_port,
        destination,
        dst_ip,
    ]
    for key in keys:
        if key and key in enrichment:
            return enrichment[key]
    cloudflare_identity = enrichment.get("_cloudflare_identity")
    if cloudflare_identity and (
        _network_ip_in_any_cidr(event.get("dst_ip"), ("104.16.0.0/13", "162.158.0.0/15", "172.64.0.0/13", "2606:4700::/32"))
        or _network_ip_in_any_cidr(event.get("src_ip"), ("104.16.0.0/13", "162.158.0.0/15", "172.64.0.0/13", "2606:4700::/32"))
    ):
        return cloudflare_identity
    return None


def _network_plain_language_semantics(event: dict[str, Any]) -> dict[str, str]:
    # Product contract: Findings copy must be semantic and human-readable here,
    # before the frontend renders it. Raw packet rows belong to Table.
    app = _network_event_app(event)
    destination = event.get("destination_display") or _network_endpoint(
        event.get("dns_query") or event.get("http_host") or event.get("tls_sni") or event.get("dst_ip"),
        event.get("dst_port"),
    )
    protocol = str(event.get("protocol") or "network").upper()
    dst_ip = event.get("dst_ip")
    dst_port = event.get("dst_port")
    if app.lower() == "rapportd" and (
        _network_ip_is_link_local(event.get("src_ip"))
        or _network_ip_is_link_local(dst_ip)
    ):
        return {
            "category": "Local device discovery",
            "summary": "rapportd is checking nearby Apple devices on the local network.",
            "meaning": "This is normal Apple Continuity traffic used for nearby-device features.",
            "reason": "Apple uses rapportd for local Continuity and nearby-device coordination.",
        }
    if _network_is_mdns_or_bonjour(event):
        return {
            "category": "Local device discovery",
            "summary": "Local devices are using Bonjour to discover services on this network.",
            "meaning": "This is normal local discovery traffic and does not leave your local network.",
            "reason": "Bonjour/mDNS traffic is expected for printers, AirPlay, sharing, and nearby services.",
        }
    if _network_is_ipv6_neighbor_discovery(event):
        return {
            "category": "Local device discovery",
            "summary": "This Mac or a nearby device is using IPv6 neighbor discovery on the local network.",
            "meaning": "This is routine local network housekeeping, not internet traffic.",
            "reason": "IPv6 link-local and multicast addresses are used to find nearby devices and routers.",
        }
    if _network_endpoint_is_apple_push(dst_ip, dst_port):
        return {
            "category": "Apple service traffic",
            "summary": "Apple Push notification service traffic was observed from this Mac.",
            "meaning": "This is commonly used by Apple and apps to keep notification channels open.",
            "reason": "The destination is an Apple network on the Apple Push notification port.",
        }
    if _network_endpoint_is_cloudflare(dst_ip) or _network_endpoint_is_cloudflare(event.get("src_ip")):
        if app != "Unknown app":
            summary = f"{app} is using Cloudflare/WARP network traffic."
        else:
            summary = "Cloudflare/WARP network traffic was observed from this Mac."
        return {
            "category": "Cloudflare network traffic",
            "summary": summary,
            "meaning": "This is secure Cloudflare network traffic.",
            "reason": "The destination is in a Cloudflare network range.",
        }
    if _is_local_network_host(str(dst_ip or "")):
        if app != "Unknown app":
            summary = f"{app} is communicating on the local network."
        else:
            summary = "Unresolved local network service traffic was observed."
        return {
            "category": "Local network traffic",
            "summary": summary,
            "meaning": "This traffic stays on this Mac or the local network.",
            "reason": "The destination is a local, private, link-local, or multicast address.",
        }
    if app == "Unknown app":
        return {
            "category": "Unknown external connection",
            "summary": f"An unknown process contacted an external server at {destination}.",
            "meaning": "CleanHouse could not identify the owning app or service for this external traffic.",
            "reason": "This is suspicious because CleanHouse could not identify the owning app or service.",
        }
    service = _service_label(dst_port)
    if service == "Network connection":
        service = protocol
    return {
        "category": "External connection",
        "summary": _network_external_activity_summary(app, event),
        "meaning": f"This appears to be {service.lower()} traffic outside this Mac.",
        "reason": "Review this if you did not expect this app to use this network service. The exact destination is preserved in metadata.",
    }


def _network_human_summary(event: dict[str, Any]) -> str:
    return _network_plain_language_semantics(event)["summary"]


def _network_event_system_impact(event: dict[str, Any]) -> int:
    score = 0
    local = _is_local_network_host(str(event.get("dst_ip") or ""))
    if local:
        score += 1
    else:
        score += 2
    if _network_event_app(event) == "Unknown app" and not local:
        score += 3
    if not (event.get("dns_query") or event.get("http_host") or event.get("tls_sni")) and not _is_local_network_host(str(event.get("dst_ip") or "")):
        score += 2
    if str(event.get("dst_port") or "") not in {"", "53", "80", "123", "443", "465", "587", "993", "995", "5223", "5228"}:
        score += 1
    if NETWORK_SEVERITY_RANK.get(str(event.get("severity") or ""), 0) >= NETWORK_SEVERITY_RANK["warning"]:
        score += 2
    return score


def _network_apply_enrichment(event: dict[str, Any], enrichment: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized = event.copy()
    enrichment = enrichment or {}
    match = _network_match_enrichment(normalized, enrichment)
    if match and _network_event_app(normalized) == "Unknown app":
        normalized["process"] = match.get("process") or "Unknown app"
        normalized["app"] = match.get("app") or normalized["process"]
        normalized["app_bundle_id"] = match.get("app_bundle_id") or normalized.get("app_bundle_id") or ""
        normalized["app_category"] = match.get("app_category") or normalized.get("app_category") or "other"
        if match.get("pid") and not normalized.get("pid"):
            normalized["pid"] = match.get("pid")
    normalized["timestamp"] = _network_event_iso(normalized.get("timestamp"))
    normalized["event_id"] = str(normalized.get("event_id") or _network_event_fingerprint(normalized))
    public_app = _network_public_app_name(_network_event_app(normalized))
    normalized["app"] = public_app
    normalized["process"] = public_app
    normalized["source_display"] = normalized.get("source_display") or _network_endpoint(normalized.get("src_ip"), normalized.get("src_port"))
    normalized["destination_display"] = normalized.get("destination_display") or _network_endpoint(
        normalized.get("dns_query") or normalized.get("http_host") or normalized.get("tls_sni") or normalized.get("dst_ip"),
        normalized.get("dst_port"),
    )
    semantics = _network_plain_language_semantics(normalized)
    normalized["category"] = semantics["category"]
    normalized["summary"] = semantics["summary"]
    normalized["meaning"] = semantics["meaning"]
    normalized["reason"] = semantics["reason"]
    normalized["suspicious"] = bool(normalized.get("suspicious") or semantics["category"] == "Unknown external connection")
    semantic_severity = _network_event_severity(normalized)
    existing_severity = str(normalized.get("severity") or "")
    if semantics["category"] == "Unknown external connection" and NETWORK_SEVERITY_RANK.get(existing_severity, 0) > NETWORK_SEVERITY_RANK.get(semantic_severity, 0):
        normalized["severity"] = existing_severity
    elif semantics["category"] in {"Unknown external connection", "Local device discovery", "Local network traffic"}:
        normalized["severity"] = semantic_severity
    else:
        normalized["severity"] = existing_severity or semantic_severity
    if semantics["category"] == "Unknown external connection":
        normalized["confidence"] = "low"
    else:
        normalized["confidence"] = str(normalized.get("confidence") or match.get("confidence") if match else normalized.get("confidence") or _network_event_confidence(normalized))
    normalized["finding_status"] = str(normalized.get("finding_status") or "open")
    normalized["system_impact"] = _network_event_system_impact(normalized)
    normalized["projection"] = {
        "finding_priority": NETWORK_SEVERITY_RANK.get(normalized["severity"], 0),
        "system_impact": normalized["system_impact"],
        "timeline_anchor": normalized["timestamp"],
    }
    normalized["trend_interpretation"] = _network_trend_interpretation_from_event(normalized)
    normalized.pop("interface", None)
    return normalized


def _network_public_event(event: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "event_id",
        "event_type",
        "receipt_type",
        "sequence",
        "cursor",
        "collector_sequence",
        "collector_cursor",
        "collector_generation",
        "server_boot_id",
        "timestamp",
        "packet_index",
        "packet_length",
        "process",
        "pid",
        "app",
        "app_bundle_id",
        "app_category",
        "src_ip",
        "src_port",
        "dst_ip",
        "dst_port",
        "dns_query",
        "tls_sni",
        "http_host",
        "protocol",
        "category",
        "summary",
        "meaning",
        "suspicious",
        "known_malicious",
        "reason",
        "source_display",
        "destination_display",
        "severity",
        "confidence",
        "system_impact",
        "finding_status",
        "projection",
        "bucket_key",
        "bucket_start",
        "bucket_end",
        "connectionCount",
        "degradedCount",
        "missingDestinationCount",
        "externalOnlyCount",
        "evidence_state",
        "interpretation_schema",
        "rule_version",
        "interpretation",
        "trend_interpretation",
        "capture_generations",
        "evidence_count",
        "contradiction_count",
        "source_event_id",
        "socket_state",
        "socket_role",
        "socket_name",
        "fd",
        "related_event_count",
        "related_event_ids",
        "related_destinations",
        "tick_id",
        "sealed_at",
        "immutable",
        "evidence_refs",
        "supersedes",
        "revision_of",
        "gap_start",
        "gap_end",
        "duration_seconds",
        "immutable",
        "state",
        "reason",
        "generation",
        "restart_count",
        "exit_code",
        "gap_from_sequence",
        "gap_to_sequence",
        "dropped_count",
        "lost_event_id",
        "tags",
    }
    return {key: event.get(key) for key in allowed if key in event}


def _network_stored_event_rows(
    event_type: str = NETWORK_OBSERVATION_EVENT_TYPE,
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    try:
        # The event spine already has a source/type/id index. Read only the
        # newest bounded slice through that index, then apply the UTC window in
        # memory. A datetime(timestamp) predicate forces SQLite to scan the
        # multi-gigabyte history when a short window contains no rows, which
        # can starve live capture and turn an honest empty state into timeout.
        rows = events.list_events(
            limit=limit,
            event_type=event_type,
            source_surface="network",
        )
        return [
            row for row in rows
            if (
                (not start or _network_event_datetime(row.get("timestamp")) >= start)
                and (not end or _network_event_datetime(row.get("timestamp")) < end)
            )
        ]
    except TypeError:
        return [
            row for row in events.list_events(limit=limit)
            if (
                row.get("event_type") == event_type
                and row.get("source_surface") == "network"
                and (not start or _network_event_datetime(row.get("timestamp")) >= start)
                and (not end or _network_event_datetime(row.get("timestamp")) < end)
            )
        ]
    except Exception:
        return []


def _network_projection_history_limit(range_key: str) -> int:
    if range_key == "5s":
        return min(NETWORK_EVIDENCE_LOOKBACK, 250)
    if range_key == "1m":
        return min(NETWORK_EVIDENCE_LOOKBACK, 500)
    if range_key in {"30m", "1h"}:
        return min(NETWORK_EVIDENCE_LOOKBACK, 1000)
    return min(NETWORK_EVIDENCE_LOOKBACK, 1500)


def _network_stored_observations(
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    observations = []
    for row in _network_stored_event_rows(NETWORK_OBSERVATION_EVENT_TYPE, limit, start=start, end=end):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        network = data.get("network") if isinstance(data.get("network"), dict) else {}
        if network:
            observations.append(network)
    return observations


def _network_event_already_stored(event_id: str) -> bool:
    for item in _network_stored_observations(limit=NETWORK_EVIDENCE_LOOKBACK):
        if str(item.get("event_id") or "") == event_id:
            return True
    return False


def _network_vvault_config() -> tuple[str, str]:
    url = os.getenv("CLEANHOUSE_VVAULT_NETWORK_EVIDENCE_URL") or os.getenv("CLEANHOUSE_VVAULT_PICKUP_URL") or os.getenv("VVAULT_PICKUP_URL") or ""
    token = os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN") or os.getenv("VVAULT_SERVICE_TOKEN") or ""
    return url.strip(), token.strip()


def _persist_network_queue_failure(queue_name: str, reason: str, network_event: dict[str, Any], **details: Any) -> None:
    timestamp = _now_iso()
    source_event_id = str(network_event.get("event_id") or "unknown")
    receipt_id = "network_queue:" + hashlib.sha256(
        f"{queue_name}:{reason}:{source_event_id}:{timestamp}".encode("utf-8")
    ).hexdigest()[:24]
    receipt = {
        "event_id": receipt_id,
        "event_type": NETWORK_COLLECTOR_RECEIPT_EVENT_TYPE,
        "receipt_type": "collector.failure",
        "timestamp": timestamp,
        "state": "degraded",
        "reason": reason,
        "queue": queue_name,
        "source_event_id": source_event_id,
        **details,
    }
    try:
        events.insert_event(
            event_type=NETWORK_COLLECTOR_RECEIPT_EVENT_TYPE,
            path=f"/network/collector/{receipt_id}",
            summary=f"Network {queue_name} queue degraded",
            session_id=DEFAULT_SESSION_ID,
            timestamp=timestamp,
            source_surface="network",
            actor_type="network_capture",
            evidence_level="observed",
            collector_status="error",
            scope_relation="runtime",
            data={"network_collector": receipt},
        )
    except Exception:
        # The in-memory health counters remain the fallback receipt when the
        # same storage failure prevents writing a durable one.
        return


def _network_vvault_worker() -> None:
    global _NETWORK_VVAULT_LAST_SUCCESS_AT, _NETWORK_VVAULT_LAST_ERROR
    global _NETWORK_VVAULT_LAST_ERROR_AT, _NETWORK_VVAULT_PENDING_COUNT
    global _NETWORK_VVAULT_OLDEST_PENDING_AT
    pending: list[dict[str, Any]] = []
    while not _NETWORK_VVAULT_WORKER_STOP.is_set():
        try:
            if not pending:
                try:
                    pending.append(_NETWORK_VVAULT_OUTBOX.get(timeout=0.5))
                except queue.Empty:
                    if _NETWORK_VVAULT_WORKER_STOP.is_set():
                        break
                    url, token = _network_vvault_config()
                    if not url or not token:
                        continue
                    for item in _network_stored_observations(limit=NETWORK_EVIDENCE_LOOKBACK):
                        event_id = str(item.get("event_id") or "")
                        if event_id and event_id not in _NETWORK_VVAULT_SYNCED_IDS:
                            pending.append({
                                "event_id": event_id,
                                "timestamp": item.get("timestamp"),
                                "network": item,
                                "_queue_owned": False,
                                "_enqueued_at": item.get("timestamp") or _now_iso(),
                            })
                        if len(pending) >= NETWORK_VVAULT_BATCH_SIZE:
                            break
                    if not pending:
                        _NETWORK_VVAULT_WORKER_STOP.wait(NETWORK_VVAULT_RETRY_SECONDS)
                        continue
            while len(pending) < NETWORK_VVAULT_BATCH_SIZE:
                try:
                    pending.append(_NETWORK_VVAULT_OUTBOX.get_nowait())
                except queue.Empty:
                    break
            with _NETWORK_VVAULT_STATE_LOCK:
                _NETWORK_VVAULT_PENDING_COUNT = len(pending)
                _NETWORK_VVAULT_OLDEST_PENDING_AT = str(pending[0].get("_enqueued_at") or "") if pending else ""
            url, token = _network_vvault_config()
            if not url or not token:
                _NETWORK_VVAULT_WORKER_STOP.wait(NETWORK_VVAULT_RETRY_SECONDS)
                continue
            outbound = [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in pending
            ]
            body = json.dumps({"schema": "cleanhouse.network_evidence.batch.v1", "events": outbound}).encode("utf-8")
            request_payload = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request_payload, timeout=5) as response:
                if response.status >= 400:
                    raise urllib.error.HTTPError(url, response.status, "sync failed", response.headers, None)
            synced_ids = [str(item.get("event_id") or "") for item in pending if str(item.get("event_id") or "")]
            _log_network_history_io(
                "vvault_remote_save",
                status="ok",
                count=len(synced_ids),
                oldest_enqueued_at=str(pending[0].get("_enqueued_at") or "") if pending else "",
            )
            _NETWORK_VVAULT_SYNCED_IDS.update(synced_ids)
            if synced_ids:
                sync_id = "network_sync:" + hashlib.sha256("|".join(sorted(synced_ids)).encode("utf-8")).hexdigest()[:24]
                events.insert_event(
                    event_type=NETWORK_SYNC_EVENT_TYPE,
                    path=f"/network/vvault-sync/{sync_id}",
                    summary="Network evidence sync completed",
                    session_id=DEFAULT_SESSION_ID,
                    timestamp=_now_iso(),
                    source_surface="network",
                    actor_type="cleanhouse",
                    evidence_level="observed",
                    data={"network_sync": {"event_id": sync_id, "synced_event_ids": synced_ids, "state": "synced"}},
                )
            for item in pending:
                if item.get("_queue_owned"):
                    _NETWORK_VVAULT_OUTBOX.task_done()
            with _NETWORK_VVAULT_STATE_LOCK:
                _NETWORK_VVAULT_LAST_SUCCESS_AT = _now_iso()
                _NETWORK_VVAULT_LAST_ERROR = ""
                _NETWORK_VVAULT_LAST_ERROR_AT = ""
                _NETWORK_VVAULT_PENDING_COUNT = 0
                _NETWORK_VVAULT_OLDEST_PENDING_AT = ""
            pending = []
        except Exception as exc:
            _LOG.warning(
                "network_history_io vvault_remote_save_failed count=%s error=%s",
                len(pending),
                exc,
            )
            with _NETWORK_VVAULT_STATE_LOCK:
                _NETWORK_VVAULT_LAST_ERROR = str(exc)[:1024]
                _NETWORK_VVAULT_LAST_ERROR_AT = _now_iso()
                _NETWORK_VVAULT_PENDING_COUNT = len(pending)
            _NETWORK_VVAULT_WORKER_STOP.wait(NETWORK_VVAULT_RETRY_SECONDS)

    for item in pending:
        if item.get("_queue_owned"):
            _NETWORK_VVAULT_OUTBOX.task_done()
    with _NETWORK_VVAULT_STATE_LOCK:
        _NETWORK_VVAULT_PENDING_COUNT = 0
        _NETWORK_VVAULT_OLDEST_PENDING_AT = ""


def _start_network_vvault_worker() -> None:
    # Retained as a compatibility hook. Delivery is owned by vvault_sync's
    # single SQLite-backed worker shared with Files.
    vvault_sync.start_service()


def _stop_network_vvault_worker(timeout: float = 5.0) -> dict[str, Any]:
    # The shared worker is stopped once by backend.server so stopping Network
    # cannot interrupt Files delivery.
    return {"service": "network_vvault_sync", "state": "retired", "joined": True}


def _enqueue_network_vvault_sync(network_event: dict[str, Any]) -> bool:
    event_id = str(network_event.get("event_id") or "").strip()
    if not event_id:
        return False
    try:
        result = vvault_sync.enqueue(
            event_id,
            {
                "event_type": NETWORK_OBSERVATION_EVENT_TYPE,
                "surface": "network",
                "timestamp": network_event.get("timestamp") or _now_iso(),
                "network": network_event,
            },
            surface="network",
            preserve_local_cache=False,
        )
        _LOG.debug(
            "network_history_io ovvaults_save status=%s artifact_id=%s",
            result.get("status"),
            event_id,
        )
        return True
    except Exception as exc:
        _persist_network_queue_failure(
            "vvault_sync",
            "durable_outbox_write_failed",
            network_event,
            error=str(exc)[:512],
        )
        return False


def _network_trend_bucket_key(timestamp: str, range_key: str = "5s") -> tuple[str, datetime, datetime]:
    dt = _network_event_datetime(timestamp)
    duration_ms = NETWORK_TIME_RANGES_MS.get(range_key, NETWORK_TIME_RANGES_MS["5s"])
    bucket_count = NETWORK_TREND_BUCKETS.get(range_key, NETWORK_TREND_BUCKETS["5s"])
    bucket_ms = max(int(duration_ms / bucket_count), 1)
    event_ms = int(dt.timestamp() * 1000)
    bucket_start_ms = event_ms // bucket_ms * bucket_ms
    start = datetime.fromtimestamp(bucket_start_ms / 1000.0, tz=timezone.utc)
    end = datetime.fromtimestamp((bucket_start_ms + bucket_ms) / 1000.0, tz=timezone.utc)
    return f"{range_key}:{bucket_start_ms}", start, end


def _stored_network_buckets(
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    buckets = []
    for row in _network_stored_event_rows(NETWORK_TREND_BUCKET_EVENT_TYPE, limit=limit, start=start, end=end):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        bucket = data.get("network_bucket") if isinstance(data.get("network_bucket"), dict) else {}
        if bucket:
            buckets.append(bucket)
    return buckets


def _vvault_network_buckets(
    range_key: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
) -> list[dict[str, Any]]:
    try:
        buckets = vvault_preservation.load_network_trend_buckets(range_key=range_key, start=start, end=end, limit=limit)
        _log_network_history_io("vvault_load", artifact="trend_buckets", range=range_key, count=len(buckets))
        return buckets
    except Exception as exc:
        _LOG.warning("network_history_io vvault_load_failed artifact=trend_buckets range=%s error=%s", range_key, exc)
        return []


def _network_trend_sample_from_event(network_event: dict[str, Any]) -> dict[str, Any]:
    public = _network_public_event(network_event)
    source_event_id = str(public.get("event_id") or network_event.get("event_id") or "")
    sample_id = "network_sample:" + hashlib.sha256(source_event_id.encode("utf-8")).hexdigest()[:24] if source_event_id else ""
    destination = (
        public.get("dns_query")
        or public.get("http_host")
        or public.get("tls_sni")
        or public.get("dst_ip")
        or public.get("destination_display")
        or ""
    )
    return {
        "sample_id": sample_id,
        "event_id": source_event_id,
        "source_event_id": source_event_id,
        "timestamp": public.get("timestamp") or _now_iso(),
        "app": public.get("app") or public.get("process") or "Unknown app",
        "process": public.get("process") or public.get("app") or "Unknown app",
        "destination": destination,
        "dst_ip": public.get("dst_ip") or "",
        "dst_port": public.get("dst_port") or "",
        "dns_query": public.get("dns_query") or "",
        "tls_sni": public.get("tls_sni") or "",
        "http_host": public.get("http_host") or "",
        "severity": public.get("severity") or "low",
        "confidence": public.get("confidence") or "low",
        "category": public.get("category") or "",
        "protocol": public.get("protocol") or "",
        "known_malicious": bool(public.get("known_malicious")),
        "suspicious": bool(public.get("suspicious")),
        "system_impact": int(public.get("system_impact") or 0),
        "collector_generation": public.get("collector_generation"),
        "server_boot_id": public.get("server_boot_id") or "",
        "evidence_refs": [f"local://cleanhouse/network/{source_event_id}"] if source_event_id else [],
    }


def _network_trend_interpretation_from_event(network_event: dict[str, Any]) -> dict[str, Any]:
    """Classify retained evidence without rewriting its factual record."""
    event = dict(network_event or {})
    app = str(event.get("app") or event.get("process") or "Unknown app").strip() or "Unknown app"
    destination = str(
        event.get("dns_query")
        or event.get("http_host")
        or event.get("tls_sni")
        or event.get("destination")
        or event.get("dst_ip")
        or ""
    ).strip()
    dst_ip = str(event.get("dst_ip") or destination or "").strip()
    dst_port = str(event.get("dst_port") or "").strip()
    protocol = str(event.get("protocol") or "").strip().upper()
    severity = str(event.get("severity") or "low").strip().lower()
    confidence = str(event.get("confidence") or "low").strip().lower()
    suspicious = bool(event.get("suspicious"))
    known_malicious = bool(event.get("known_malicious"))
    external = bool(dst_ip) and not _is_local_network_host(dst_ip)
    named_destination = str(event.get("dns_query") or event.get("http_host") or event.get("tls_sni") or "").strip()
    explicit_destination = str(event.get("destination") or "").strip()
    readable_destination = bool(named_destination or (explicit_destination and explicit_destination != dst_ip))
    source_event_id = str(event.get("source_event_id") or event.get("event_id") or event.get("sample_id") or "").strip()
    evidence_refs = list(dict.fromkeys(
        str(value).strip()
        for value in (event.get("evidence_refs") or ([f"local://cleanhouse/network/{source_event_id}"] if source_event_id else []))
        if str(value).strip()
    ))[:30]
    series = {
        "vulnerabilities": {"matched": False, "confidence": 0.0, "rationale": [], "signals": []},
        "threats": {"matched": False, "confidence": 0.0, "rationale": [], "signals": []},
        "strengths": {"matched": False, "confidence": 0.0, "rationale": [], "signals": []},
    }

    def mark(key: str, signal: str, rationale: str, weight: float) -> None:
        target = series[key]
        target["matched"] = True
        target["confidence"] = max(float(target["confidence"]), weight)
        if signal not in target["signals"]:
            target["signals"].append(signal)
        if rationale not in target["rationale"]:
            target["rationale"].append(rationale)

    if known_malicious:
        mark("threats", "known_malicious", "Reviewed evidence marks this observation as known malicious.", 1.0)
    if suspicious:
        mark("threats", "suspicious", "Retained evidence carries a suspicious review signal.", 0.85)
    severity_weight = {"critical": 0.95, "high": 0.85, "warning": 0.7, "medium": 0.65}.get(severity)
    if severity_weight:
        mark("threats", f"severity:{severity}", f"Retained evidence has {severity} review severity.", severity_weight)
    if external and app.lower() == "unknown app":
        mark("vulnerabilities", "unknown_external_owner", "External activity lacks a verified owning application.", 0.8)
    if external and not readable_destination:
        mark("vulnerabilities", "unresolved_external_destination", "External activity lacks a readable destination identity.", 0.7)
    if external and confidence == "low":
        mark("vulnerabilities", "low_attribution_confidence", "External attribution confidence is low.", 0.6)
    if protocol == "HTTP" or dst_port == "80":
        mark("vulnerabilities", "cleartext_http", "Observed service metadata indicates cleartext HTTP.", 0.85)
    if app.lower() != "unknown app" and confidence == "high":
        mark("strengths", "identified_owner", "Application ownership is identified with high confidence.", 0.85)
    if readable_destination:
        mark("strengths", "readable_destination", "The destination is represented by retained readable evidence.", 0.7)
    if protocol in {"TLS", "HTTPS", "QUIC"} or dst_port in {"443", "465", "853", "993", "995"}:
        mark("strengths", "encrypted_service", "Observed protocol or service metadata indicates encrypted transport.", 0.8)
    if dst_ip and not external:
        mark("strengths", "local_scope", "Observed traffic remains within a local or private network scope.", 0.65)
    matched = [key for key, value in series.items() if value["matched"]]
    return {
        "schema": NETWORK_TREND_INTERPRETATION_SCHEMA,
        "rule_version": NETWORK_TREND_RULE_VERSION,
        "evidence_state": "observed" if source_event_id else "unknown",
        "source_event_id": source_event_id,
        "evidence_refs": evidence_refs,
        "capture_generation": event.get("collector_generation"),
        "series": series,
        "contradictory": "strengths" in matched and bool({"vulnerabilities", "threats"}.intersection(matched)),
    }


def _network_trend_interpretation_buckets(range_key: str, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    deduplicated: dict[str, dict[str, Any]] = {}
    for sample in samples:
        identity = str(sample.get("source_event_id") or sample.get("event_id") or sample.get("sample_id") or "").strip()
        if identity:
            deduplicated.setdefault(identity, sample)
    for identity, sample in deduplicated.items():
        timestamp = str(sample.get("timestamp") or _now_iso())
        bucket_key, start, end = _network_trend_bucket_key(timestamp, range_key)
        interpretation = _network_trend_interpretation_from_event(sample)
        tick_id = "network_trend_interpretation:" + hashlib.sha256(
            f"{NETWORK_TREND_RULE_VERSION}:{bucket_key}".encode("utf-8")
        ).hexdigest()[:24]
        bucket = buckets.setdefault(bucket_key, {
            "event_id": tick_id,
            "tick_id": tick_id,
            "event_type": "network_trend_interpretation",
            "timestamp": timestamp,
            "bucket_key": bucket_key,
            "bucket_range": range_key,
            "bucket_start": start.isoformat().replace("+00:00", "Z"),
            "bucket_end": end.isoformat().replace("+00:00", "Z"),
            "sealed_at": end.isoformat().replace("+00:00", "Z"),
            "immutable": datetime.now(timezone.utc) >= end,
            "evidence_state": "observed",
            "interpretation_schema": NETWORK_TREND_INTERPRETATION_SCHEMA,
            "rule_version": NETWORK_TREND_RULE_VERSION,
            "interpretation": {
                key: {"value": 0, "confidence": None, "rationale": [], "signals": [], "evidence_refs": []}
                for key in ("vulnerabilities", "threats", "strengths")
            },
            "capture_generations": [],
            "evidence_count": 0,
            "contradiction_count": 0,
            "related_event_ids": [],
            "evidence_refs": [],
            "_confidence": {"vulnerabilities": [], "threats": [], "strengths": []},
        })
        bucket["timestamp"] = max(str(bucket.get("timestamp") or ""), timestamp)
        bucket["evidence_count"] += 1
        bucket["contradiction_count"] += 1 if interpretation.get("contradictory") else 0
        generation = interpretation.get("capture_generation")
        if generation is not None and generation not in bucket["capture_generations"]:
            bucket["capture_generations"].append(generation)
        if identity not in bucket["related_event_ids"] and len(bucket["related_event_ids"]) < 30:
            bucket["related_event_ids"].append(identity)
        for evidence_ref in interpretation.get("evidence_refs") or []:
            if evidence_ref not in bucket["evidence_refs"] and len(bucket["evidence_refs"]) < 30:
                bucket["evidence_refs"].append(evidence_ref)
        for key, result in interpretation["series"].items():
            if not result.get("matched"):
                continue
            target = bucket["interpretation"][key]
            target["value"] += 1
            bucket["_confidence"][key].append(float(result.get("confidence") or 0.0))
            for rationale in result.get("rationale") or []:
                if rationale not in target["rationale"] and len(target["rationale"]) < 8:
                    target["rationale"].append(rationale)
            for signal in result.get("signals") or []:
                if signal not in target["signals"] and len(target["signals"]) < 12:
                    target["signals"].append(signal)
            for evidence_ref in interpretation.get("evidence_refs") or []:
                if evidence_ref not in target["evidence_refs"] and len(target["evidence_refs"]) < 30:
                    target["evidence_refs"].append(evidence_ref)
    for bucket in buckets.values():
        for key, confidences in bucket.pop("_confidence").items():
            bucket["interpretation"][key]["confidence"] = (
                round(sum(confidences) / len(confidences), 3) if confidences else None
            )
    return sorted(buckets.values(), key=lambda item: (_network_event_datetime(item.get("bucket_start")), str(item.get("event_id") or "")))


def _preserve_network_trend_sample(network_event: dict[str, Any]) -> None:
    sample = _network_trend_sample_from_event(network_event)
    if not sample.get("sample_id"):
        return
    result = vvault_preservation.preserve_network_trend_sample(sample)
    _log_network_vvault_save_result("trend_sample", sample.get("sample_id"), sample.get("timestamp"), result)


def _preserve_network_trend_tick(tick: dict[str, Any]) -> None:
    result = vvault_preservation.preserve_network_trend_tick(tick)
    _log_network_vvault_save_result(
        "trend_tick",
        tick.get("tick_id") or tick.get("event_id"),
        tick.get("timestamp") or tick.get("sealed_at"),
        result,
    )


def _vvault_network_trend_samples(start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    try:
        samples = vvault_preservation.load_network_trend_samples(start=start, end=end, limit=limit)
        _log_network_history_io("vvault_load", artifact="trend_samples", count=len(samples))
        return samples
    except Exception as exc:
        _LOG.warning("network_history_io vvault_load_failed artifact=trend_samples error=%s", exc)
        return []


def _stored_network_trend_ticks(
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    ticks = []
    for row in _network_stored_event_rows(NETWORK_TREND_TICK_EVENT_TYPE, limit=limit, start=start, end=end):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        tick = data.get("network_tick") if isinstance(data.get("network_tick"), dict) else {}
        if tick:
            ticks.append(tick)
    return ticks


def _vvault_network_trend_ticks(range_key: str = "", start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    try:
        ticks = vvault_preservation.load_network_trend_ticks(range_key=range_key, start=start, end=end, limit=limit)
        _log_network_history_io("vvault_load", artifact="trend_ticks", range=range_key, count=len(ticks))
        return ticks
    except Exception as exc:
        _LOG.warning("network_history_io vvault_load_failed artifact=trend_ticks range=%s error=%s", range_key, exc)
        return []


def _network_trend_tick_from_event(network_event: dict[str, Any], range_key: str) -> dict[str, Any]:
    public = _network_public_event(network_event)
    source_event_id = str(public.get("event_id") or network_event.get("event_id") or "")
    timestamp = str(public.get("timestamp") or _now_iso())
    bucket_key, start, end = _network_trend_bucket_key(timestamp, range_key)
    seed = f"{source_event_id}:{range_key}:{timestamp}"
    tick_id = "network_tick:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    external = not _is_local_network_host(str(public.get("dst_ip") or ""))
    degraded = bool(public.get("suspicious")) or NETWORK_SEVERITY_RANK.get(str(public.get("severity") or ""), 0) >= NETWORK_SEVERITY_RANK["warning"]
    missing_destination = external and not (public.get("dns_query") or public.get("http_host") or public.get("tls_sni"))
    return {
        "event_id": tick_id,
        "tick_id": tick_id,
        "timestamp": timestamp,
        "sealed_at": timestamp,
        "immutable": True,
        "bucket_key": f"tick:{range_key}:{tick_id}",
        "bucket_range": range_key,
        "bucket_start": start.isoformat().replace("+00:00", "Z"),
        "bucket_end": end.isoformat().replace("+00:00", "Z"),
        "connectionCount": 1,
        "degradedCount": 1 if degraded else 0,
        "missingDestinationCount": 1 if missing_destination else 0,
        "externalOnlyCount": 1 if external else 0,
        "source_event_id": source_event_id,
        "related_event_ids": [source_event_id] if source_event_id else [],
        "evidence_refs": [f"local://cleanhouse/network/{source_event_id}"] if source_event_id else [],
        "app": public.get("app") or public.get("process") or "Unknown app",
        "process": public.get("process") or public.get("app") or "Unknown app",
        "dst_ip": public.get("dst_ip") or "",
        "dst_port": public.get("dst_port") or "",
        "severity": public.get("severity") or "low",
    }


def _network_trend_ticks_from_samples(range_key: str, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for sample in samples:
        source_event_id = str(sample.get("source_event_id") or sample.get("event_id") or sample.get("sample_id") or "")
        timestamp = str(sample.get("timestamp") or _now_iso())
        bucket_key, start, end = _network_trend_bucket_key(timestamp, range_key)
        tick_id = "network_tick:" + hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:24]
        external = not _is_local_network_host(str(sample.get("dst_ip") or sample.get("destination") or ""))
        degraded = bool(sample.get("suspicious")) or NETWORK_SEVERITY_RANK.get(str(sample.get("severity") or ""), 0) >= NETWORK_SEVERITY_RANK["warning"]
        missing_destination = external and not (sample.get("dns_query") or sample.get("http_host") or sample.get("tls_sni") or sample.get("destination"))
        identity = _network_startup_operator_identity(sample)
        bucket = buckets.setdefault(bucket_key, {
            "event_id": tick_id,
            "tick_id": tick_id,
            "timestamp": timestamp,
            "sealed_at": end.isoformat().replace("+00:00", "Z"),
            "immutable": datetime.now(timezone.utc) >= end,
            "bucket_key": bucket_key,
            "bucket_range": range_key,
            "bucket_start": start.isoformat().replace("+00:00", "Z"),
            "bucket_end": end.isoformat().replace("+00:00", "Z"),
            "connectionCount": 0,
            "degradedCount": 0,
            "missingDestinationCount": 0,
            "externalOnlyCount": 0,
            "source_event_id": source_event_id,
            "related_event_ids": [],
            "evidence_refs": [],
            "app": sample.get("app") or sample.get("process") or "Unknown app",
            "process": sample.get("process") or sample.get("app") or "Unknown app",
            "dst_ip": sample.get("dst_ip") or "",
            "dst_port": sample.get("dst_port") or "",
            "severity": sample.get("severity") or "low",
            "_connections": set(),
            "_degraded_connections": set(),
            "_missing_destination_connections": set(),
            "_external_connections": set(),
        })
        bucket["timestamp"] = max(str(bucket.get("timestamp") or ""), timestamp)
        bucket["_connections"].add(identity)
        if degraded:
            bucket["_degraded_connections"].add(identity)
        if missing_destination:
            bucket["_missing_destination_connections"].add(identity)
        if external:
            bucket["_external_connections"].add(identity)
        if source_event_id and source_event_id not in bucket["related_event_ids"] and len(bucket["related_event_ids"]) < 30:
            bucket["related_event_ids"].append(source_event_id)
        for evidence_ref in sample.get("evidence_refs") or ([f"local://cleanhouse/network/{source_event_id}"] if source_event_id else []):
            if evidence_ref not in bucket["evidence_refs"] and len(bucket["evidence_refs"]) < 30:
                bucket["evidence_refs"].append(evidence_ref)
    ticks = []
    for bucket in buckets.values():
        bucket["connectionCount"] = len(bucket.pop("_connections"))
        bucket["degradedCount"] = len(bucket.pop("_degraded_connections"))
        bucket["missingDestinationCount"] = len(bucket.pop("_missing_destination_connections"))
        bucket["externalOnlyCount"] = len(bucket.pop("_external_connections"))
        ticks.append(bucket)
    return sorted(ticks, key=lambda item: (_network_event_datetime(item.get("bucket_start")), str(item.get("tick_id") or "")))


def _all_network_trend_ticks(range_key: str, start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for tick in [*_stored_network_trend_ticks(limit=limit), *_vvault_network_trend_ticks(range_key, start, end, limit=limit)]:
        if tick.get("bucket_range") != range_key:
            continue
        event_dt = _network_event_datetime(tick.get("timestamp"))
        if start and event_dt < start:
            continue
        if end and event_dt > end:
            continue
        tick_id = str(tick.get("tick_id") or tick.get("event_id") or "")
        if tick_id:
            by_id.setdefault(tick_id, tick)
    samples = _all_network_trend_samples(start, end, limit=limit)
    for tick in _network_trend_ticks_from_samples(range_key, samples):
        tick_id = str(tick.get("tick_id") or tick.get("event_id") or "")
        if tick_id:
            by_id.setdefault(tick_id, tick)
            _preserve_network_trend_tick(tick)
    return sorted(by_id.values(), key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("tick_id") or item.get("event_id") or "")))


def _all_network_trend_samples(start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in _network_stored_observations(limit=limit):
        event_dt = _network_event_datetime(item.get("timestamp"))
        if start and event_dt < start:
            continue
        if end and event_dt > end:
            continue
        sample = _network_trend_sample_from_event(item)
        sample_id = str(sample.get("source_event_id") or sample.get("event_id") or sample.get("sample_id") or "")
        if sample_id:
            by_id[sample_id] = sample
    for sample in _vvault_network_trend_samples(start, end, limit=limit):
        sample_id = str(sample.get("source_event_id") or sample.get("event_id") or sample.get("sample_id") or "")
        if sample_id:
            by_id.setdefault(sample_id, sample)
    return sorted(by_id.values(), key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("sample_id") or "")))


def _all_network_buckets(range_key: str = "", start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for bucket in [*_stored_network_buckets(), *_vvault_network_buckets(range_key, start, end)]:
        if not bucket:
            continue
        bucket_id = str(bucket.get("event_id") or bucket.get("bucket_key") or "")
        if not bucket_id:
            continue
        current = by_id.get(bucket_id)
        if not current or _network_event_datetime(bucket.get("timestamp")) > _network_event_datetime(current.get("timestamp")):
            by_id[bucket_id] = bucket
    return list(by_id.values())


def _append_network_trend_ticks(network_event: dict[str, Any]) -> None:
    stored_tick_ids = {
        str(item.get("tick_id") or item.get("event_id") or "")
        for item in _stored_network_trend_ticks()
    }
    for range_key in NETWORK_TIME_RANGES_MS:
        tick = _network_trend_tick_from_event(network_event, range_key)
        tick_id = str(tick.get("tick_id") or tick.get("event_id") or "")
        if not tick_id:
            continue
        if tick_id in stored_tick_ids:
            _preserve_network_trend_tick(tick)
            continue
        events.insert_event(
            event_type=NETWORK_TREND_TICK_EVENT_TYPE,
            path=f"/network/trend/ticks/{tick_id}",
            summary=f"Network trend tick {tick_id}",
            session_id=DEFAULT_SESSION_ID,
            timestamp=str(tick.get("timestamp") or _now_iso()),
            source_surface="network",
            actor_type="cleanhouse",
            evidence_level="observed",
            data={"network_tick": tick},
        )
        stored_tick_ids.add(tick_id)
        _preserve_network_trend_tick(tick)


def _persist_network_observation(
    event: dict[str, Any],
    enrichment: dict[str, dict[str, Any]] | None = None,
    *,
    persist_trend: bool = True,
    check_existing: bool = True,
    enqueue_vvault: bool = True,
) -> dict[str, Any]:
    network_event = _network_apply_enrichment(event, enrichment)
    event_id = str(network_event.get("event_id") or "")
    if event_id and (not check_existing or not _network_event_already_stored(event_id)):
        events.insert_event(
            event_type=NETWORK_OBSERVATION_EVENT_TYPE,
            path=f"/network/events/{event_id}",
            summary=str(network_event.get("summary") or "Network event observed"),
            session_id=DEFAULT_SESSION_ID,
            timestamp=str(network_event.get("timestamp") or _now_iso()),
            source_surface="network",
            actor_type="network_capture",
            evidence_level="observed",
            observed_vs_expected={"status": "observed"},
            collector_status="ok",
            scope_relation="runtime",
            evidence_refs=[f"local://cleanhouse/network/{event_id}"],
            raw_evidence_ref=f"local://cleanhouse/network/{event_id}",
            data={"network": network_event, "vvault_sync": {"state": "pending"}},
        )
        if persist_trend:
            _preserve_network_trend_sample(network_event)
            _append_network_trend_ticks(network_event)
        if enqueue_vvault:
            _enqueue_network_vvault_sync(network_event)
    return _network_public_event(network_event)


def _network_live_persist_worker() -> None:
    global _NETWORK_LIVE_PERSIST_FAILURES, _NETWORK_LIVE_PERSIST_LAST_ERROR
    while not _NETWORK_LIVE_PERSIST_WORKER_STOP.is_set() or not _NETWORK_LIVE_PERSIST_QUEUE.empty():
        try:
            network_event = _NETWORK_LIVE_PERSIST_QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _persist_network_observation(
                network_event,
                persist_trend=False,
                check_existing=False,
                enqueue_vvault=False,
            )
        except Exception as exc:
            with _NETWORK_LIVE_PERSIST_LOCK:
                _NETWORK_LIVE_PERSIST_FAILURES += 1
                _NETWORK_LIVE_PERSIST_LAST_ERROR = str(exc)[:1024]
                failure_count = _NETWORK_LIVE_PERSIST_FAILURES
            _persist_network_queue_failure(
                "canonical_persistence",
                "persistence_worker_failed",
                network_event,
                failure_count=failure_count,
                error=str(exc)[:512],
            )
        finally:
            _NETWORK_LIVE_PERSIST_QUEUE.task_done()


def _start_network_live_persist_worker() -> None:
    global _NETWORK_LIVE_PERSIST_WORKER_STARTED, _NETWORK_LIVE_PERSIST_WORKER_THREAD
    if _NETWORK_LIVE_PERSIST_WORKER_STARTED and _NETWORK_LIVE_PERSIST_WORKER_THREAD and _NETWORK_LIVE_PERSIST_WORKER_THREAD.is_alive():
        return
    with _NETWORK_LIVE_PERSIST_LOCK:
        if _NETWORK_LIVE_PERSIST_WORKER_STARTED and _NETWORK_LIVE_PERSIST_WORKER_THREAD and _NETWORK_LIVE_PERSIST_WORKER_THREAD.is_alive():
            return
        _NETWORK_LIVE_PERSIST_WORKER_STOP.clear()
        _NETWORK_LIVE_PERSIST_WORKER_THREAD = threading.Thread(
            target=_network_live_persist_worker,
            daemon=True,
            name="cleanhouse-network-live-persist",
        )
        _NETWORK_LIVE_PERSIST_WORKER_THREAD.start()
        _NETWORK_LIVE_PERSIST_WORKER_STARTED = True


def _stop_network_live_persist_worker(timeout: float = 5.0) -> dict[str, Any]:
    global _NETWORK_LIVE_PERSIST_WORKER_STARTED, _NETWORK_LIVE_PERSIST_WORKER_THREAD
    _NETWORK_LIVE_PERSIST_WORKER_STOP.set()
    with _NETWORK_LIVE_PERSIST_LOCK:
        thread = _NETWORK_LIVE_PERSIST_WORKER_THREAD
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=max(0.0, float(timeout)))
    joined = thread is None or not thread.is_alive()
    if joined:
        with _NETWORK_LIVE_PERSIST_LOCK:
            _NETWORK_LIVE_PERSIST_WORKER_STARTED = False
            _NETWORK_LIVE_PERSIST_WORKER_THREAD = None
    return {"service": "network_live_persistence", "state": "stopped" if joined else "stopping", "joined": joined}


def _enqueue_network_live_persistence(network_event: dict[str, Any]) -> bool:
    global _NETWORK_LIVE_PERSIST_QUEUE_DROPS
    _start_network_live_persist_worker()
    try:
        _NETWORK_LIVE_PERSIST_QUEUE.put_nowait(network_event.copy())
        return True
    except queue.Full:
        with _NETWORK_LIVE_PERSIST_LOCK:
            _NETWORK_LIVE_PERSIST_QUEUE_DROPS += 1
            drops = _NETWORK_LIVE_PERSIST_QUEUE_DROPS
        _persist_network_queue_failure(
            "canonical_persistence",
            "persistence_queue_overflow",
            network_event,
            queue_depth=_NETWORK_LIVE_PERSIST_QUEUE.qsize(),
            queue_capacity=_NETWORK_LIVE_PERSIST_QUEUE.maxsize,
            drop_count=drops,
        )
        return False


def _snapshot_event_from_connection(conn: dict[str, Any]) -> dict[str, Any]:
    process = _clean_process_name(conn.get("process"))
    src_ip = conn.get("local_host")
    src_port = conn.get("local_port")
    dst_ip = conn.get("domain") or conn.get("remote_host") or conn.get("host") or conn.get("address") or "Unknown destination"
    dst_port = conn.get("remote_port") or conn.get("port")
    target = str(dst_ip)
    port = dst_port
    local = _is_local_network_host(target)
    suspicious = bool(conn.get("suspicious"))
    category = "Needs review" if suspicious else ("Local traffic" if local else "External connection")
    service = _service_label(port)
    destination = target if target != "*" else "local listeners"
    source_display = _network_endpoint(src_ip, src_port)
    destination_display = _network_endpoint(destination, port)
    return {
        "timestamp": _now_iso(),
        "packet_index": None,
        "packet_length": None,
        "process": process,
        "pid": conn.get("pid"),
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": target,
        "dst_port": port,
        "protocol": service,
        "category": category,
        "summary": f"{process} -> {destination_display} -> {service}",
        "meaning": "This is local app or device traffic." if local else "This app is communicating outside this Mac.",
        "source": "network_observation_snapshot",
        "suspicious": suspicious,
        "reason": conn.get("reason") or "",
        "source_display": source_display,
        "destination_display": destination_display,
    }


def _network_collector_snapshot_payload(refresh: bool = False, persist: bool = True) -> tuple[dict[str, Any], int]:
    adapter = get_cleanhouse_monitoring_adapter()
    snapshot = adapter.get_network(refresh=refresh)
    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    connections = data.get("connections") if isinstance(data.get("connections"), list) else []
    enrichment = _network_enrichment_index(refresh=refresh)
    raw_events = [_snapshot_event_from_connection(conn) for conn in connections if isinstance(conn, dict)]
    events = [
        _persist_network_observation(event, enrichment) if persist else _network_apply_enrichment(event, enrichment)
        for event in raw_events
    ]
    events.sort(key=lambda item: (not item.get("suspicious"), item.get("category") != "External connection", item.get("process", "")))
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    visible_count = min(len(events), WIRESHARK_MAX_EVENTS)
    return _network_ui_contract(
        "CAPTURING" if events else "NO_DATA",
        events=events[:WIRESHARK_MAX_EVENTS],
        summary={
            "reason": "snapshot",
            "event_count": visible_count,
            "counts": counts,
        },
    )


def _network_event_collector_sequence(event: dict[str, Any]) -> int:
    try:
        return max(0, int(event.get("collector_sequence") or event.get("sequence") or 0))
    except (TypeError, ValueError):
        return 0


def _network_snapshot_payload(refresh: bool = False) -> tuple[dict[str, Any], int]:
    collector = _get_network_collector()
    collector.start()
    if refresh:
        collector.refresh(timeout=2.0)
    boundary = collector.snapshot(include_events=False)
    high_water_sequence = int(boundary.get("high_water_sequence") or 0)
    events_payload = [
        _network_public_event(item)
        for item in _network_events_in_range("1m", limit=min(NETWORK_EVIDENCE_LOOKBACK, 200), enrich_unknown=False)[-WIRESHARK_MAX_EVENTS:]
        if not (
            str(item.get("server_boot_id") or "") == NETWORK_SERVER_BOOT_ID
            and _network_event_collector_sequence(item) > high_water_sequence
        )
    ]
    visible_count = len(events_payload)
    snapshot_identities: set[str] = set()
    for event in events_payload:
        identity = _network_startup_operator_identity(event)
        already_present = identity in snapshot_identities
        snapshot_identities.add(identity)
        _log_network_startup_reconciliation(
            "snapshot_operator_record",
            event_id=event.get("event_id"),
            identity=identity,
            outcome="updated_existing_table_record" if already_present else "created_new_table_record",
            reason="frontend_row_identity_matched_earlier_snapshot_event" if already_present else "first_snapshot_event_for_frontend_row_identity",
        )
    os_active_connection_count = _network_active_connection_count()
    payload, status_code = _network_ui_contract(
        _network_runtime_probe_state(events_payload),
        events=events_payload,
        summary={
            "reason": "snapshot",
            "event_count": visible_count,
            "counts": {
                "connections": visible_count,
                "os_active_connections": os_active_connection_count,
            },
            "source": "runtime_packet_buffer",
            "active_connection_source": "macos_lsof",
            "cursor": boundary["cursor"],
            "high_water_cursor": boundary["high_water_cursor"],
            "refresh": "synchronized" if refresh else "not_requested",
        },
    )
    collector_health = network_collector_health()
    payload.update({
        "cursor": boundary["cursor"],
        "high_water_cursor": boundary["high_water_cursor"],
        "high_water_sequence": high_water_sequence,
    })
    _network_apply_collector_truth(payload, collector_health)
    _log_network_startup_reconciliation(
        "startup_reconciliation_report",
        packets_captured=collector_health.get("startup_packets_captured", 0),
        packet_events_emitted=collector_health.get("startup_canonical_packet_events_emitted", 0),
        operator_visible_rows_created=len(_NETWORK_STARTUP_OPERATOR_RECORDS),
        snapshot_packet_records_returned=visible_count,
        snapshot_unique_operator_visible_rows=len(snapshot_identities),
        os_active_connections=os_active_connection_count,
        reduction_reason=(
            "os_active_connections_is_an_lsof_socket_snapshot; table_records_are_only_recent_tshark_packet_events; "
            "multiple_packet_events_with_the_same_frontend_row_identity_merge_into_one_table_row"
        ),
    )
    return payload, status_code


def _network_history_enabled() -> bool:
    return os.getenv("CLEANHOUSE_NETWORK_HISTORY_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def _network_history_interval_seconds() -> int:
    try:
        return max(10, int(os.getenv("CLEANHOUSE_NETWORK_HISTORY_INTERVAL_SECONDS", "30")))
    except ValueError:
        return 30


def _record_network_history_recovery_gap() -> None:
    last = _network_latest_history_timestamp()
    if not last:
        return
    now = datetime.now(timezone.utc)
    threshold = max(_network_history_interval_seconds() * 2, 120)
    if (now - last).total_seconds() > threshold:
        _persist_network_timeline_gap("history_interrupted", last, now)


def _record_network_history_sample() -> None:
    payload, _status = _network_snapshot_payload(refresh=True)
    sample_events = payload.get("events") if isinstance(payload.get("events"), list) else []
    if not sample_events:
        _log_network_history_io("runtime_sample", status="empty", count=0)
        return
    ranked = sorted(sample_events, key=_network_event_rank, reverse=True)
    for event in ranked[:10]:
        _preserve_network_trend_sample(event)
        if _network_is_timeline_notable(event):
            _persist_network_timeline_notable(event, "history")
    _log_network_history_io("runtime_sample", status="saved", count=min(len(ranked), 10))


def _network_history_service_loop() -> None:
    _record_network_history_recovery_gap()
    while not _NETWORK_HISTORY_SERVICE_STOP.is_set():
        try:
            _record_network_history_sample()
        except Exception:
            pass
        _NETWORK_HISTORY_SERVICE_STOP.wait(_network_history_interval_seconds())


def start_network_history_service() -> None:
    global _NETWORK_HISTORY_SERVICE_THREAD
    if not _network_history_enabled():
        return
    with _NETWORK_HISTORY_SERVICE_LOCK:
        if _NETWORK_HISTORY_SERVICE_THREAD and _NETWORK_HISTORY_SERVICE_THREAD.is_alive():
            return
        _NETWORK_HISTORY_SERVICE_STOP.clear()
        _NETWORK_HISTORY_SERVICE_THREAD = threading.Thread(
            target=_network_history_service_loop,
            daemon=True,
            name="cleanhouse-network-history",
        )
        _NETWORK_HISTORY_SERVICE_THREAD.start()


def stop_network_history_service(timeout: float = 5.0) -> dict[str, Any]:
    global _NETWORK_HISTORY_SERVICE_THREAD
    _NETWORK_HISTORY_SERVICE_STOP.set()
    with _NETWORK_HISTORY_SERVICE_LOCK:
        thread = _NETWORK_HISTORY_SERVICE_THREAD
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=max(0.0, float(timeout)))
    joined = thread is None or not thread.is_alive()
    if joined:
        with _NETWORK_HISTORY_SERVICE_LOCK:
            if _NETWORK_HISTORY_SERVICE_THREAD is thread:
                _NETWORK_HISTORY_SERVICE_THREAD = None
    return {
        "service": "network_history",
        "state": "stopped" if joined else "stopping",
        "joined": joined,
    }


def _event_from_tshark_packet(packet: dict[str, Any], interface: str) -> dict[str, Any] | None:
    layers = packet.get("_source", {}).get("layers", {})
    if not isinstance(layers, dict):
        return None
    frame = layers.get("frame", {}) if isinstance(layers.get("frame"), dict) else layers
    dst_port = _layer_value(layers.get("tcp", {}) if isinstance(layers.get("tcp"), dict) else {}, "tcp.dstport") \
        or _layer_value(layers.get("udp", {}) if isinstance(layers.get("udp"), dict) else {}, "udp.dstport")
    event = {
        "timestamp": _layer_value(frame, "frame.time_epoch"),
        "packet_index": _layer_value(frame, "frame.number") or None,
        "packet_length": _layer_value(frame, "frame.len") or None,
        "protocol": _packet_protocol(layers),
        "src_ip": _layer_value(layers.get("ip", {}) if isinstance(layers.get("ip"), dict) else {}, "ip.src")
            or _layer_value(layers.get("ipv6", {}) if isinstance(layers.get("ipv6"), dict) else {}, "ipv6.src"),
        "dst_ip": _layer_value(layers.get("ip", {}) if isinstance(layers.get("ip"), dict) else {}, "ip.dst")
            or _layer_value(layers.get("ipv6", {}) if isinstance(layers.get("ipv6"), dict) else {}, "ipv6.dst"),
        "src_port": _layer_value(layers.get("tcp", {}) if isinstance(layers.get("tcp"), dict) else {}, "tcp.srcport")
            or _layer_value(layers.get("udp", {}) if isinstance(layers.get("udp"), dict) else {}, "udp.srcport"),
        "dst_port": dst_port,
        "dns_query": _layer_value(layers.get("dns", {}) if isinstance(layers.get("dns"), dict) else {}, "dns.qry.name"),
        "tls_sni": _layer_value(layers.get("tls", {}) if isinstance(layers.get("tls"), dict) else {}, "tls.handshake.extensions_server_name"),
        "http_host": _layer_value(layers.get("http", {}) if isinstance(layers.get("http"), dict) else {}, "http.host"),
        "interface": interface,
        "source": "network_capture",
        "category": "Local traffic" if _is_local_network_host(
            _layer_value(layers.get("ip", {}) if isinstance(layers.get("ip"), dict) else {}, "ip.dst")
            or _layer_value(layers.get("ipv6", {}) if isinstance(layers.get("ipv6"), dict) else {}, "ipv6.dst")
        ) else "External connection",
        "meaning": "This is local app or device traffic." if _is_local_network_host(
            _layer_value(layers.get("ip", {}) if isinstance(layers.get("ip"), dict) else {}, "ip.dst")
            or _layer_value(layers.get("ipv6", {}) if isinstance(layers.get("ipv6"), dict) else {}, "ipv6.dst")
        ) else "This packet is communicating outside this Mac.",
    }
    if not any(event.get(key) for key in ("src_ip", "dst_ip", "dns_query", "tls_sni", "http_host")):
        return None
    event["summary"] = _network_event_summary(event)
    event["source_display"] = _network_endpoint(event.get("src_ip"), event.get("src_port"))
    event["destination_display"] = _network_endpoint(
        event.get("dns_query") or event.get("http_host") or event.get("tls_sni") or event.get("dst_ip"),
        event.get("dst_port"),
    )
    return event


def _tshark_json_command(paths: dict[str, Path], interface: str, duration: int | None = None, packet_limit: int | None = None) -> list[str]:
    command = [
        str(paths["tshark"]),
        "-l",
        "-n",
        "-i", interface,
    ]
    if duration is not None:
        command.extend(["-a", f"duration:{duration}"])
    if packet_limit is not None:
        command.extend(["-c", str(max(1, int(packet_limit)))])
    command.extend([
        "-T", "json",
        "-j", "frame",
        "-j", "ip",
        "-j", "ipv6",
        "-j", "tcp",
        "-j", "udp",
        "-j", "dns",
        "-j", "tls",
        "-j", "http",
    ])
    return command


def _network_live_capture_filter(server_port: str) -> str:
    port = str(server_port or "").strip()
    if not port.isdigit():
        return ""
    return f"not port {int(port)}"


def _tshark_live_fields_command(paths: dict[str, Path], interfaces: list[str] | str, capture_filter: str = "") -> list[str]:
    interface_names = [interfaces] if isinstance(interfaces, str) else list(interfaces)
    command = [
        str(paths["tshark"]),
        "-l",
        "-n",
    ]
    for interface in interface_names:
        command.extend(["-i", interface])
    if capture_filter:
        command.extend(["-f", capture_filter])
    command.extend([
        "-T", "fields",
        "-E", "header=n",
        "-E", "separator=|",
        "-E", "occurrence=f",
        "-e", "frame.time_epoch",
        "-e", "frame.number",
        "-e", "frame.len",
        "-e", "frame.protocols",
        "-e", "frame.interface_name",
        "-e", "ip.src",
        "-e", "ipv6.src",
        "-e", "ip.dst",
        "-e", "ipv6.dst",
        "-e", "tcp.srcport",
        "-e", "udp.srcport",
        "-e", "tcp.dstport",
        "-e", "udp.dstport",
        "-e", "dns.qry.name",
        "-e", "tls.handshake.extensions_server_name",
        "-e", "http.host",
    ])
    return command


def _event_from_tshark_fields_line(line: str, interface: str) -> dict[str, Any] | None:
    raw = str(line or "").rstrip("\n")
    if not raw:
        return None
    parts = raw.split("|")
    if len(parts) < 16:
        parts.extend([""] * (16 - len(parts)))
    (
        timestamp,
        packet_index,
        packet_length,
        frame_protocols,
        frame_interface,
        ip_src,
        ipv6_src,
        ip_dst,
        ipv6_dst,
        tcp_src_port,
        udp_src_port,
        tcp_dst_port,
        udp_dst_port,
        dns_query,
        tls_sni,
        http_host,
    ) = parts[:16]
    src_ip = ip_src or ipv6_src
    dst_ip = ip_dst or ipv6_dst
    src_port = tcp_src_port or udp_src_port
    dst_port = tcp_dst_port or udp_dst_port
    event = {
        "timestamp": timestamp,
        "packet_index": packet_index or None,
        "packet_length": packet_length or None,
        "protocol": _protocol_from_frame_protocols(frame_protocols),
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "dns_query": dns_query,
        "tls_sni": tls_sni,
        "http_host": http_host,
        "interface": frame_interface or interface,
        "source": "network_capture",
        "category": "Local traffic" if _is_local_network_host(dst_ip) else "External connection",
        "meaning": "This is local app or device traffic." if _is_local_network_host(dst_ip) else "This packet is communicating outside this Mac.",
    }
    if not any(event.get(key) for key in ("src_ip", "dst_ip", "dns_query", "tls_sni", "http_host")):
        return None
    event["summary"] = _network_event_summary(event)
    event["source_display"] = _network_endpoint(src_ip, src_port)
    event["destination_display"] = _network_endpoint(
        dns_query or http_host or tls_sni or dst_ip,
        dst_port,
    )
    return event


def _network_collector_server_interfaces(interfaces: list[dict[str, str]]) -> list[str]:
    requested = os.getenv("CLEANHOUSE_NETWORK_INTERFACE", "").strip()
    available = [str(item.get("name") or "").strip() for item in interfaces]
    available = [name for name in available if name]
    if requested:
        for item in interfaces:
            if requested in {str(item.get("id") or ""), str(item.get("name") or "")}:
                return [str(item.get("name") or requested)]
        return [requested]

    selected: list[str] = []

    def add(name: str) -> None:
        if name and name in available and name not in selected:
            selected.append(name)

    add("lo0")
    for name in sorted(_active_capture_interfaces()):
        if not name.startswith("utun"):
            add(name)
    for preferred in ("en0", "en1"):
        add(preferred)
    if selected:
        return selected
    return [available[0]] if available else []


def _network_collector_command_factory() -> dict[str, Any]:
    interfaces, engine_error = _bundled_wireshark_engine_interfaces()
    if engine_error:
        payload, _status_code = engine_error
        reason = str((payload.get("summary") or {}).get("reason") or "engine_unavailable")
        raise CaptureEngineUnavailable(reason)
    selected = _network_collector_server_interfaces(interfaces)
    if not selected:
        raise RuntimeError("capture interface unavailable")
    paths = _bundled_wireshark_paths()
    server_port = os.getenv("CLEANHOUSE_PORT", "3333")
    return {
        "command": _tshark_live_fields_command(
            paths,
            selected,
            _network_live_capture_filter(server_port),
        ),
        "cwd": str(paths["root"]),
        "interface": ",".join(selected),
    }


def _network_collector_enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    global _NETWORK_COLLECTOR_ENRICHMENT, _NETWORK_COLLECTOR_ENRICHMENT_AT
    now = time.monotonic()
    with _NETWORK_COLLECTOR_ENRICHMENT_LOCK:
        if (
            not _NETWORK_COLLECTOR_ENRICHMENT
            or now - _NETWORK_COLLECTOR_ENRICHMENT_AT >= NETWORK_COLLECTOR_ENRICHMENT_INTERVAL_SECONDS
        ):
            _NETWORK_COLLECTOR_ENRICHMENT = _network_enrichment_index(refresh=False)
            _NETWORK_COLLECTOR_ENRICHMENT_AT = time.monotonic()
        enrichment = _NETWORK_COLLECTOR_ENRICHMENT
    return _network_apply_enrichment(event, enrichment)


def _network_capture_sample_identity(event: dict[str, Any]) -> str:
    return "|".join(str(event.get(key) or "").strip().lower() for key in (
        "protocol",
        "src_ip",
        "src_port",
        "dst_ip",
        "dst_port",
        "dns_query",
        "tls_sni",
        "http_host",
    ))


def _persist_network_collector_event(envelope: dict[str, Any]) -> dict[str, Any]:
    global _NETWORK_CANONICAL_EVENT_IDS_INITIALIZED
    global _NETWORK_STARTUP_OPERATOR_RECORDS_CREATED, _NETWORK_STARTUP_OPERATOR_RECORDS_UPDATED
    event = envelope.get("event") if isinstance(envelope.get("event"), dict) else {}
    event_id = str(event.get("event_id") or "")
    with _NETWORK_CANONICAL_EVENT_IDS_LOCK:
        if not _NETWORK_CANONICAL_EVENT_IDS_INITIALIZED:
            for stored in _network_stored_observations(limit=NETWORK_EVIDENCE_LOOKBACK):
                stored_id = str(stored.get("event_id") or "")
                if stored_id:
                    _NETWORK_CANONICAL_EVENT_IDS[stored_id] = None
            while len(_NETWORK_CANONICAL_EVENT_IDS) > _NETWORK_CANONICAL_EVENT_IDS_LIMIT:
                _NETWORK_CANONICAL_EVENT_IDS.pop(next(iter(_NETWORK_CANONICAL_EVENT_IDS)))
            _NETWORK_CANONICAL_EVENT_IDS_INITIALIZED = True
        duplicate = bool(event_id and event_id in _NETWORK_CANONICAL_EVENT_IDS)
    if duplicate:
        _log_network_startup_reconciliation(
            "operator_record_reconciled",
            event_id=event_id,
            outcome="ignored",
            reason="duplicate_canonical_event_id",
        )
        duplicate_envelope = envelope.copy()
        duplicate_envelope["type"] = "collector.failure"
        duplicate_envelope["event"] = {
            "reason": "duplicate_event_id",
            "state": "degraded",
            "lost_event_id": event_id,
            "sequence": envelope.get("sequence"),
            "collector_sequence": envelope.get("sequence"),
            "cursor": envelope.get("cursor"),
            "collector_cursor": envelope.get("cursor"),
            "server_boot_id": NETWORK_SERVER_BOOT_ID,
        }
        return _persist_network_collector_receipt(duplicate_envelope)
    # The shared SQLite outbox is the bounded durable commit that precedes
    # fan-out. The multi-gigabyte event spine is updated by its bounded worker
    # so capture cannot be stalled by a per-packet history transaction.
    persisted = _network_public_event(event)
    if not _enqueue_network_vvault_sync(persisted):
        raise RuntimeError("network durable outbox write failed")
    if not _enqueue_network_live_persistence(persisted):
        raise RuntimeError("network event-spine queue overflow")
    # Projections must see the same authentic packet evidence immediately even
    # when the durable event database is large. This bounded boot-local window
    # supplements persistence; it never replaces or fabricates canonical rows.
    with _NETWORK_RECENT_OBSERVATIONS_LOCK:
        _NETWORK_RECENT_OBSERVATIONS.append(dict(persisted))
    # Live packet delivery updates Table and the in-browser trend tape
    # immediately. Retained projections keep their short bounded cache instead
    # of forcing multi-gigabyte history reads for every captured packet.
    identity = _network_startup_operator_identity(persisted)
    with _NETWORK_STARTUP_RECONCILIATION_LOCK:
        previous_count = _NETWORK_STARTUP_OPERATOR_RECORDS.get(identity, 0)
        _NETWORK_STARTUP_OPERATOR_RECORDS[identity] = previous_count + 1
        if previous_count:
            _NETWORK_STARTUP_OPERATOR_RECORDS_UPDATED += 1
            outcome = "updated_existing_table_record"
            reason = "frontend_row_identity_matched_existing_record"
        else:
            _NETWORK_STARTUP_OPERATOR_RECORDS_CREATED += 1
            outcome = "created_new_table_record"
            reason = "frontend_row_identity_not_previously_observed"
        created_count = _NETWORK_STARTUP_OPERATOR_RECORDS_CREATED
        updated_count = _NETWORK_STARTUP_OPERATOR_RECORDS_UPDATED
        unique_count = len(_NETWORK_STARTUP_OPERATOR_RECORDS)
    _log_network_startup_reconciliation(
        "operator_record_reconciled",
        event_id=event_id,
        collector_sequence=envelope.get("sequence"),
        identity=identity,
        outcome=outcome,
        reason=reason,
        operator_visible_rows_created=created_count,
        operator_visible_rows_updated=updated_count,
        current_unique_operator_visible_rows=unique_count,
    )
    if event_id:
        with _NETWORK_CANONICAL_EVENT_IDS_LOCK:
            _NETWORK_CANONICAL_EVENT_IDS[event_id] = None
            while len(_NETWORK_CANONICAL_EVENT_IDS) > _NETWORK_CANONICAL_EVENT_IDS_LIMIT:
                _NETWORK_CANONICAL_EVENT_IDS.pop(next(iter(_NETWORK_CANONICAL_EVENT_IDS)))
    result = envelope.copy()
    result["event"] = persisted
    return result


def _persist_network_collector_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    receipt_type = str(envelope.get("type") or "collector.receipt")
    sequence = int(envelope.get("sequence") or 0)
    receipt = dict(envelope.get("event") or {})
    receipt_id = str(receipt.get("event_id") or f"network_collector:{NETWORK_SERVER_BOOT_ID}:{sequence}:{receipt_type}")
    receipt.update({
        "event_id": receipt_id,
        "event_type": NETWORK_COLLECTOR_RECEIPT_EVENT_TYPE,
        "receipt_type": receipt_type,
        "timestamp": str(receipt.get("timestamp") or _now_iso()),
        "immutable": True,
    })
    events.insert_event(
        event_type=NETWORK_COLLECTOR_RECEIPT_EVENT_TYPE,
        path=f"/network/collector/{receipt_id}",
        summary=f"Network collector {receipt_type.rsplit('.', 1)[-1]}",
        session_id=DEFAULT_SESSION_ID,
        timestamp=receipt["timestamp"],
        source_surface="network",
        actor_type="network_capture",
        evidence_level="observed",
        collector_status="error" if receipt_type in {"collector.failure", "collector.gap"} else "ok",
        scope_relation="runtime",
        evidence_refs=[f"local://cleanhouse/network/collector/{receipt_id}"],
        raw_evidence_ref=f"local://cleanhouse/network/collector/{receipt_id}",
        data={"network_collector": receipt},
    )
    result = envelope.copy()
    result["event"] = _network_public_event(receipt)
    return result


def _network_collector_env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _network_collector_env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_network_collector() -> NetworkCollectorSupervisor:
    global _NETWORK_COLLECTOR
    if _NETWORK_COLLECTOR is not None:
        return _NETWORK_COLLECTOR
    with _NETWORK_COLLECTOR_LOCK:
        if _NETWORK_COLLECTOR is None:
            try:
                watchdog_backoff = max(0.1, float(os.getenv("CLEANHOUSE_NETWORK_WATCHDOG_BACKOFF_SECONDS", "1")))
            except (TypeError, ValueError):
                watchdog_backoff = 1.0
            _NETWORK_COLLECTOR = NetworkCollectorSupervisor(
                _network_collector_command_factory,
                _event_from_tshark_fields_line,
                _network_collector_enrich_event,
                _persist_network_collector_event,
                _persist_network_collector_receipt,
                boot_id=NETWORK_SERVER_BOOT_ID,
                replay_size=_network_collector_env_int("CLEANHOUSE_NETWORK_REPLAY_SIZE", 4096, 64),
                subscriber_queue_size=_network_collector_env_int("CLEANHOUSE_NETWORK_SUBSCRIBER_QUEUE_SIZE", 512, 2),
                watchdog_backoff_seconds=watchdog_backoff,
                event_identity=_network_capture_sample_identity,
                coalesce_window_seconds=_network_collector_env_float(
                    "CLEANHOUSE_NETWORK_SAMPLE_INTERVAL_SECONDS",
                    1.0,
                    0.05,
                ),
            )
    return _NETWORK_COLLECTOR


def start_network_collector_service() -> dict[str, Any]:
    return _get_network_collector().start()


def stop_network_collector_service(timeout: float = 5.0) -> dict[str, Any] | None:
    receipt = _NETWORK_COLLECTOR.stop(timeout=timeout) if _NETWORK_COLLECTOR is not None else None
    live_persistence = _stop_network_live_persist_worker(timeout=timeout)
    vvault_sync = _stop_network_vvault_worker(timeout=timeout)
    if receipt is not None and isinstance(receipt.get("event"), dict):
        receipt["event"]["workers"] = [live_persistence, vvault_sync]
    return receipt


def network_collector_health(*, allow_keychain_read: bool = True) -> dict[str, Any]:
    health = _get_network_collector().health()
    preservation = vvault_sync.status(surface="network", allow_keychain_read=allow_keychain_read)
    health.update({
        "persistence_queue_depth": _NETWORK_LIVE_PERSIST_QUEUE.qsize(),
        "persistence_queue_capacity": _NETWORK_LIVE_PERSIST_QUEUE.maxsize,
        "persistence_queue_drops": _NETWORK_LIVE_PERSIST_QUEUE_DROPS,
        "persistence_failures": health.get("persistence_failures", 0) + _NETWORK_LIVE_PERSIST_FAILURES,
        "persistence_last_error": _NETWORK_LIVE_PERSIST_LAST_ERROR or health.get("last_error", ""),
        "vvault_queue_depth": preservation.get("backlog_depth", 0),
        "vvault_queue_capacity": None,
        "vvault_queue_drops": 0,
        "vvault_state": preservation.get("state", "unavailable"),
        "vvault_worker_alive": bool(preservation.get("worker_alive")),
    })
    return health


def _is_loopback_packet_host(value: Any) -> bool:
    host = str(value or "").strip().strip("[]").lower()
    if host in {"localhost", "::1"} or host.startswith("127."):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_current_live_stream_packet(event: dict[str, Any], client_port: str, server_port: str) -> bool:
    if not client_port or not server_port:
        return False
    src_port = str(event.get("src_port") or "")
    dst_port = str(event.get("dst_port") or "")
    if {src_port, dst_port} != {client_port, server_port}:
        return False
    return _is_loopback_packet_host(event.get("src_ip")) and _is_loopback_packet_host(event.get("dst_ip"))


def _iter_tshark_json_packets(stdout: Any):
    buffer: list[str] = []
    capturing = False
    depth = 0
    in_string = False
    escaped = False

    while True:
        char = stdout.read(1)
        if not char:
            break

        if not capturing:
            if char == "{":
                buffer = [char]
                capturing = True
                depth = 1
                in_string = False
                escaped = False
            continue

        buffer.append(char)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw_packet = "".join(buffer)
                buffer = []
                capturing = False
                try:
                    packet = json.loads(raw_packet)
                except json.JSONDecodeError:
                    continue
                if isinstance(packet, dict):
                    yield packet


def _tshark_packets_from_json_text(value: str) -> list[dict[str, Any]]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _sse_event(event: str, payload: dict[str, Any], *, event_id: str = "") -> str:
    id_line = f"id: {event_id}\n" if event_id else ""
    return f"{id_line}event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _network_tags(status: str, state: str, reasons: list[str] | None = None, explanation: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "state": state,
        "reasons": reasons or [],
        "explanation": explanation,
    }


def _run_bundled_wireshark_capture() -> tuple[dict[str, Any], int]:
    interfaces, engine_error = _bundled_wireshark_engine_interfaces()
    if engine_error:
        return engine_error
    duration, duration_error = _capture_duration()
    if duration_error:
        return duration_error

    interface = _select_capture_interface(interfaces if isinstance(interfaces, list) else [])
    if not interface:
        return _bundled_wireshark_error("engine_failed", "Capture system unavailable.")

    paths = _bundled_wireshark_paths()
    command = _tshark_json_command(paths, interface, duration=duration, packet_limit=min(WIRESHARK_MAX_EVENTS, 5))
    events_payload = []
    enrichment = _network_enrichment_index(refresh=False)
    try:
        completed = subprocess.run(
            command,
            cwd=str(paths["root"]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=duration + WIRESHARK_CAPTURE_TIMEOUT_GRACE_SECONDS,
            check=False,
        )
        for packet in _tshark_packets_from_json_text(completed.stdout):
            event = _event_from_tshark_packet(packet, interface)
            if event:
                events_payload.append(_persist_network_observation(event, enrichment))
            if len(events_payload) >= WIRESHARK_MAX_EVENTS:
                break
    except subprocess.TimeoutExpired:
        return _bundled_wireshark_error("capture_timeout", "Network engine failed to start.")
    except OSError:
        return _bundled_wireshark_error("engine_failed", "Network engine failed to start.")

    stderr_text = completed.stderr
    if completed.returncode not in (0, -15) and not events_payload:
        return _wireshark_capture_error(stderr_text)

    return _network_ui_contract(
        "CAPTURING" if events_payload else "NO_DATA",
        events=events_payload,
        summary={
            "reason": "events_observed" if events_payload else "no_data",
            "event_count": len(events_payload),
        },
    )


@bp.route("/cleanhouse/network/wireshark", methods=["GET"])
def wireshark_status():
    payload, status_code = _validate_bundled_wireshark_tools()
    if payload.get("state") == "READY" and status_code == 200:
        return jsonify({"state": "READY"}), 200
    return jsonify({"state": "ERROR", "reason": "engine_unavailable"}), 400


@bp.route("/cleanhouse/network/live", methods=["GET"])
def network_live():
    collector = _get_network_collector()
    collector.start()
    # Native EventSource retains its original query string across reconnects
    # but advances Last-Event-ID, so the header is the authoritative cursor.
    after_cursor = str(request.headers.get("Last-Event-ID") or request.args.get("after") or "").strip()
    subscription = collector.subscribe(after_cursor=after_cursor or None)

    @stream_with_context
    def stream():
        try:
            health = network_collector_health()
            state_map = {
                "running": "CAPTURING",
                "starting": "WARMING",
                "blocked": "CAPTURE_BLOCKED",
                "degraded": "ERROR",
                "stopped": "ERROR",
                "stopping": "ERROR",
            }
            initial_state, initial_reason = _network_collector_contract(health)
            initial_cursor = subscription.initial_cursor
            yield _sse_event("status", {
                "state": initial_state,
                "tags": _network_fixed_tags(initial_state, [], {"reason": initial_reason}),
                "events": [],
                "summary": {
                    "reason": initial_reason,
                    "event_count": 0,
                    "cursor": initial_cursor,
                },
                "cursor": initial_cursor,
                "collector": health,
            }, event_id=initial_cursor)

            while True:
                try:
                    envelope = subscription.get(timeout=15.0)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if envelope is None:
                    return
                receipt_type = str(envelope.get("type") or "")
                cursor = str(envelope.get("cursor") or "")
                payload = dict(envelope.get("event") or {})
                payload.setdefault("sequence", envelope.get("sequence"))
                payload.setdefault("collector_sequence", envelope.get("sequence"))
                payload.setdefault("cursor", cursor)
                payload.setdefault("collector_cursor", cursor)
                payload.setdefault("receipt_type", receipt_type)
                if receipt_type == "network.event":
                    event_name = "network-event"
                elif receipt_type == "collector.gap":
                    event_name = "gap"
                elif receipt_type == "collector.failure":
                    event_name = "failure"
                    receipt_health = {
                        **network_collector_health(),
                        "state": payload.get("state") or "degraded",
                        "reason_code": payload.get("reason") or "",
                        "last_error": payload.get("error") or "",
                    }
                    capture_state, capture_reason = _network_collector_contract(receipt_health)
                    payload["state"] = capture_state
                    payload["summary"] = {"reason": capture_reason, "event_count": 0, "cursor": cursor}
                    payload["tags"] = _network_fixed_tags(capture_state, [], payload["summary"])
                else:
                    event_name = "status"
                    payload["collector"] = network_collector_health()
                    payload["state"] = state_map.get(str(payload.get("state") or ""), payload.get("state") or "WARMING")
                yield _sse_event(event_name, payload, event_id=cursor)
        finally:
            subscription.close()

    return Response(stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _network_projection_window(range_key: str) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    duration_ms = NETWORK_TIME_RANGES_MS.get(range_key, NETWORK_TIME_RANGES_MS["5s"])
    start = datetime.fromtimestamp((end.timestamp() * 1000 - duration_ms) / 1000, tz=timezone.utc)
    return start, end


def _network_retention_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=NETWORK_EVIDENCE_RETENTION_DAYS)


def _network_events_in_range(
    range_key: str,
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    enrich_unknown: bool = True,
) -> list[dict[str, Any]]:
    start, end = _network_projection_window(range_key)
    retention_start = _network_retention_start()
    if start < retention_start:
        start = retention_start
    by_id: dict[str, dict[str, Any]] = {}
    enrichment = None
    with _NETWORK_RECENT_OBSERVATIONS_LOCK:
        recent = [dict(item) for item in _NETWORK_RECENT_OBSERVATIONS]
    recent_in_window = [
        item for item in recent
        if start <= _network_event_datetime(item.get("timestamp")) < end
    ]
    if range_key in {"5s", "1m"} and recent_in_window:
        candidates = recent_in_window
    else:
        candidates = [*_network_stored_observations(limit=limit, start=start, end=end), *recent_in_window]
    for item in candidates:
        event_dt = _network_event_datetime(item.get("timestamp"))
        if start <= event_dt < end:
            projected = item
            if enrich_unknown and _network_event_app(projected) == "Unknown app":
                if enrichment is None:
                    enrichment = _network_enrichment_index(refresh=False)
                projected = _network_apply_enrichment(projected, enrichment)
            event_id = str(projected.get("event_id") or "")
            if event_id:
                by_id[event_id] = projected
    visible = list(by_id.values())
    visible.sort(key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("event_id") or "")))
    return visible


def _network_retained_events(limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    retention_start = _network_retention_start()
    retained = [
        item for item in _network_stored_observations(limit=limit, start=retention_start)
        if _network_event_datetime(item.get("timestamp")) >= retention_start
    ]
    retained.sort(key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("event_id") or "")))
    return retained


def _stored_network_timeline_notables(
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    notables = []
    for row in _network_stored_event_rows(NETWORK_TIMELINE_NOTABLE_EVENT_TYPE, limit=limit, start=start, end=end):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        notable = data.get("network_timeline_notable") if isinstance(data.get("network_timeline_notable"), dict) else {}
        if notable:
            notables.append(notable)
    return notables


def _stored_network_timeline_gaps(
    limit: int = NETWORK_EVIDENCE_LOOKBACK,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    gaps = []
    for row in _network_stored_event_rows(NETWORK_TIMELINE_GAP_EVENT_TYPE, limit=limit, start=start, end=end):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        gap = data.get("network_gap") if isinstance(data.get("network_gap"), dict) else {}
        if gap:
            gaps.append(gap)
    return gaps


def _vvault_network_timeline_notables(range_key: str = "", start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    try:
        notables = vvault_preservation.load_network_timeline_notables(range_key=range_key, start=start, end=end, limit=limit)
        _log_network_history_io("vvault_load", artifact="timeline_notables", range=range_key, count=len(notables))
        return notables
    except Exception as exc:
        _LOG.warning("network_history_io vvault_load_failed artifact=timeline_notables range=%s error=%s", range_key, exc)
        return []


def _vvault_network_timeline_gaps(range_key: str = "", start: datetime | None = None, end: datetime | None = None, limit: int = NETWORK_EVIDENCE_LOOKBACK) -> list[dict[str, Any]]:
    try:
        gaps = vvault_preservation.load_network_timeline_gaps(range_key=range_key, start=start, end=end, limit=limit)
        _log_network_history_io("vvault_load", artifact="timeline_gaps", range=range_key, count=len(gaps))
        return gaps
    except Exception as exc:
        _LOG.warning("network_history_io vvault_load_failed artifact=timeline_gaps range=%s error=%s", range_key, exc)
        return []


def _network_timeline_gap_event(reason: str, start: datetime, end: datetime) -> dict[str, Any]:
    duration_seconds = max(0, int((end - start).total_seconds()))
    seed = f"{reason}:{start.isoformat()}:{end.isoformat()}"
    return {
        "event_id": "network_gap:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
        "event_type": NETWORK_TIMELINE_GAP_EVENT_TYPE,
        "timestamp": end.isoformat().replace("+00:00", "Z"),
        "gap_start": start.isoformat().replace("+00:00", "Z"),
        "gap_end": end.isoformat().replace("+00:00", "Z"),
        "duration_seconds": duration_seconds,
        "process": "CleanHouse",
        "app": "CleanHouse",
        "protocol": "History gap",
        "category": "History gap",
        "summary": "CleanHouse network history was interrupted.",
        "meaning": "CleanHouse was not collecting network history during this interval.",
        "reason": reason,
        "severity": "warning",
        "confidence": "high",
        "system_impact": 2,
        "source": "network_history_service",
    }


def _network_timeline_event_already_stored(event_type: str, event_id: str) -> bool:
    for row in _network_stored_event_rows(event_type, limit=NETWORK_EVIDENCE_LOOKBACK):
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        for value in data.values():
            if isinstance(value, dict) and str(value.get("event_id") or "") == event_id:
                return True
    return False


def _persist_network_timeline_notable(event: dict[str, Any], range_key: str = "history") -> None:
    notable = _network_public_event(event)
    event_id = str(notable.get("event_id") or "")
    if not event_id or _network_timeline_event_already_stored(NETWORK_TIMELINE_NOTABLE_EVENT_TYPE, event_id):
        preservation = vvault_preservation.preserve_network_timeline_notable(notable, range_key)
        _log_network_vvault_save_result("timeline_notable", event_id, notable.get("timestamp"), preservation)
        return
    events.insert_event(
        event_type=NETWORK_TIMELINE_NOTABLE_EVENT_TYPE,
        path=f"/network/timeline/notable/{event_id}",
        summary=str(notable.get("summary") or "Network timeline notable"),
        session_id=DEFAULT_SESSION_ID,
        timestamp=str(notable.get("timestamp") or _now_iso()),
        source_surface="network",
        actor_type="cleanhouse",
        evidence_level="observed",
        data={"network_timeline_notable": notable},
    )
    preservation = vvault_preservation.preserve_network_timeline_notable(notable, range_key)
    _log_network_vvault_save_result("timeline_notable", event_id, notable.get("timestamp"), preservation)


def _persist_network_timeline_gap(reason: str, start: datetime, end: datetime) -> dict[str, Any]:
    gap = _network_timeline_gap_event(reason, start, end)
    event_id = str(gap.get("event_id") or "")
    if event_id and not _network_timeline_event_already_stored(NETWORK_TIMELINE_GAP_EVENT_TYPE, event_id):
        events.insert_event(
            event_type=NETWORK_TIMELINE_GAP_EVENT_TYPE,
            path=f"/network/timeline/gap/{event_id}",
            summary=str(gap.get("summary") or "Network timeline gap"),
            session_id=DEFAULT_SESSION_ID,
            timestamp=str(gap.get("timestamp") or _now_iso()),
            source_surface="network",
            actor_type="cleanhouse",
            evidence_level="observed",
            data={"network_gap": gap},
        )
    preservation = vvault_preservation.preserve_network_timeline_gap("history", reason, gap)
    _log_network_vvault_save_result("timeline_gap", event_id, gap.get("timestamp"), preservation)
    return gap


def _network_latest_history_timestamp() -> datetime | None:
    timestamps: list[datetime] = []
    for bucket in _all_network_buckets():
        value = bucket.get("bucket_end") or bucket.get("timestamp")
        if value:
            timestamps.append(_network_event_datetime(value))
    for notable in [*_stored_network_timeline_notables(), *_vvault_network_timeline_notables()]:
        if notable.get("timestamp"):
            timestamps.append(_network_event_datetime(notable.get("timestamp")))
    for gap in [*_stored_network_timeline_gaps(), *_vvault_network_timeline_gaps()]:
        value = gap.get("gap_end") or gap.get("timestamp")
        if value:
            timestamps.append(_network_event_datetime(value))
    if not timestamps:
        return None
    return max(timestamps)


def _network_projection_state(events_payload: list[dict[str, Any]]) -> str:
    return "CAPTURING" if events_payload else "NO_DATA"


def _network_event_rank(item: dict[str, Any]) -> tuple[int, int, int]:
    severity = NETWORK_SEVERITY_RANK.get(str(item.get("severity") or ""), 0)
    confidence = NETWORK_CONFIDENCE_RANK.get(str(item.get("confidence") or ""), 0)
    impact = int(item.get("system_impact") or 0)
    return severity, confidence, impact


def _network_finding_status(item: dict[str, Any]) -> str:
    return str(item.get("finding_status") or "open").strip().lower()


def _network_is_open_finding(item: dict[str, Any]) -> bool:
    return _network_finding_status(item) not in {
        "cleared",
        "closed",
        "dismissed",
        "invalid",
        "invalidated",
        "resolved",
        "superseded",
    }


def _network_is_review_worthy_finding(item: dict[str, Any]) -> bool:
    severity, _confidence, impact = _network_event_rank(item)
    if severity >= NETWORK_SEVERITY_RANK["warning"]:
        return True
    if _network_is_routine_local_discovery(item):
        return True
    if item.get("category") in {"Local device discovery", "Local network traffic", "Apple service traffic", "Cloudflare network traffic"}:
        return True
    if severity < NETWORK_SEVERITY_RANK["low"]:
        return False
    destination_text = str(
        item.get("dns_query")
        or item.get("http_host")
        or item.get("tls_sni")
        or item.get("destination_display")
        or item.get("dst_ip")
        or ""
    ).lower()
    if item.get("suspicious") or item.get("known_malicious"):
        return True
    if _network_event_app(item) == "Unknown app":
        return True
    if impact >= 6:
        return True
    destination = item.get("dns_query") or item.get("http_host") or item.get("tls_sni")
    common_port = str(item.get("dst_port") or "") in {"", "53", "80", "123", "443", "465", "587", "993", "995", "5223", "5228", "5353"}
    return not destination and not common_port


def _network_is_timeline_notable(item: dict[str, Any]) -> bool:
    severity, _confidence, _impact = _network_event_rank(item)
    return bool(
        item.get("suspicious")
        or item.get("known_malicious")
        or severity >= NETWORK_SEVERITY_RANK["warning"]
    )


def _network_finding_priority_key(item: dict[str, Any]) -> tuple[int, int, int, int, float, str]:
    severity, confidence, impact = _network_event_rank(item)
    suspicious = 1 if item.get("suspicious") or item.get("known_malicious") else 0
    first_seen = _network_event_datetime(item.get("first_seen") or item.get("detected_at") or item.get("timestamp")).timestamp()
    return (
        -severity,
        -confidence,
        -impact,
        -suspicious,
        first_seen,
        str(item.get("event_id") or ""),
    )


def _network_finding_signature(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    # Product contract: Findings collapse repeated evidence into one semantic
    # finding while preserving distinct meanings. Packet identity is not the
    # display identity for this tab.
    category = str(item.get("category") or "").strip()
    summary = str(item.get("summary") or "").strip().lower()
    reason = str(item.get("reason") or item.get("meaning") or "").strip().lower()
    if category in {"Local device discovery", "Local network traffic", "Apple service traffic", "Cloudflare network traffic"} and summary:
        return (
            str(item.get("severity") or "").strip().lower(),
            category.lower(),
            summary,
            reason,
            "",
        )
    destination = str(
        item.get("dns_query")
        or item.get("http_host")
        or item.get("tls_sni")
        or item.get("dst_ip")
        or item.get("destination_display")
        or ""
    ).strip().lower()
    return (
        str(item.get("severity") or "").strip().lower(),
        _network_event_app(item).strip().lower(),
        destination,
        str(item.get("dst_port") or "").strip(),
        str(item.get("protocol") or "").strip().upper(),
    )


def _network_merge_related_finding(target: dict[str, Any], related: dict[str, Any]) -> None:
    target["related_event_count"] = int(target.get("related_event_count") or 1) + 1
    ids = target.setdefault("related_event_ids", [str(target.get("event_id") or "")])
    related_id = str(related.get("event_id") or "")
    if related_id and related_id not in ids and len(ids) < NETWORK_FINDINGS_RELATED_ID_LIMIT:
        ids.append(related_id)
    destinations = target.setdefault("related_destinations", [])
    destination = str(related.get("destination_display") or related.get("dst_ip") or "").strip()
    if destination and destination not in destinations and len(destinations) < NETWORK_FINDINGS_DESTINATION_LIMIT:
        destinations.append(destination)


def _network_projection_summary(view: str, range_key: str, event_count: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = {
        "reason": "projection",
        "view": view,
        "range": range_key,
        "event_count": event_count,
        "retention_days": NETWORK_EVIDENCE_RETENTION_DAYS,
        "generated_at": _now_iso(),
    }
    if extra:
        summary.update(extra)
    return summary


def _network_findings_cache_get() -> dict[str, Any] | None:
    with _NETWORK_FINDINGS_CACHE_LOCK:
        payload = _NETWORK_FINDINGS_CACHE.get("payload")
        cached_at = float(_NETWORK_FINDINGS_CACHE.get("cached_at") or 0.0)
        if isinstance(payload, dict) and time.monotonic() - cached_at <= NETWORK_FINDINGS_CACHE_SECONDS:
            return json.loads(json.dumps(payload))
    return None


def _network_findings_cache_set(payload: dict[str, Any]) -> None:
    with _NETWORK_FINDINGS_CACHE_LOCK:
        _NETWORK_FINDINGS_CACHE["payload"] = json.loads(json.dumps(payload))
        _NETWORK_FINDINGS_CACHE["cached_at"] = time.monotonic()


NETWORK_PROJECTION_CACHE_SECONDS = 8.0


def _network_projection_cache_key(view: str, range_key: str) -> str:
    return f"{view}:{range_key}"


def _network_projection_cache_get(view: str, range_key: str) -> dict[str, Any] | None:
    cache_key = _network_projection_cache_key(view, range_key)
    with _NETWORK_PROJECTION_CACHE_LOCK:
        entry = _NETWORK_PROJECTION_CACHE.get(cache_key)
    if not isinstance(entry, dict):
        return None
    cached_at = float(entry.get("cached_at") or 0.0)
    if time.monotonic() - cached_at > NETWORK_PROJECTION_CACHE_SECONDS:
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    cached = json.loads(json.dumps(payload))
    summary = cached.get("summary") if isinstance(cached.get("summary"), dict) else {}
    cached["summary"] = {
        **summary,
        "cache": "hot",
        "generated_at": _now_iso(),
    }
    return cached


def _network_projection_cache_set(view: str, range_key: str, payload: dict[str, Any]) -> None:
    cache_key = _network_projection_cache_key(view, range_key)
    with _NETWORK_PROJECTION_CACHE_LOCK:
        _NETWORK_PROJECTION_CACHE[cache_key] = {
            "payload": json.loads(json.dumps(payload)),
            "cached_at": time.monotonic(),
        }


def _network_finding_needs_enrichment(item: dict[str, Any]) -> bool:
    if _network_event_app(item) == "Unknown app":
        return True
    if _network_summary_exposes_raw_external_destination(item):
        return True
    return not (item.get("summary") and item.get("reason") and item.get("category"))


def _network_running_app_summary(visible: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    global _NETWORK_RUNNING_APPS, _NETWORK_RUNNING_APPS_AT
    with _NETWORK_RUNNING_APPS_LOCK:
        cache_fresh = bool(_NETWORK_RUNNING_APPS) and (
            time.monotonic() - _NETWORK_RUNNING_APPS_AT < NETWORK_COLLECTOR_ENRICHMENT_INTERVAL_SECONDS
        )
        running_apps = [dict(item) for item in _NETWORK_RUNNING_APPS] if cache_fresh else []
    if not running_apps:
        _index, running_apps = _network_app_identity_index(refresh=False)
        with _NETWORK_RUNNING_APPS_LOCK:
            _NETWORK_RUNNING_APPS = [dict(item) for item in running_apps]
            _NETWORK_RUNNING_APPS_AT = time.monotonic()
    observed = {}
    for item in visible or []:
        name = _network_event_app(item)
        if name:
            observed[name] = observed.get(name, 0) + 1
    return [
        {
            "app_id": str(app.get("id") or app.get("bundle_id") or app.get("name") or ""),
            "name": str(app.get("name") or "Unknown app"),
            "category": str(app.get("category") or "other"),
            "observed_network_events": observed.get(str(app.get("name") or ""), 0),
            "source": "applications_running_gui_inventory",
        }
        for app in running_apps[:100]
    ]


def _network_projection_findings(range_key: str) -> tuple[dict[str, Any], int]:
    # Findings is the grouped, priority-preserving review surface. Do not make
    # this projection behave like the raw Table stream or Distribution donut.
    cached = _network_findings_cache_get()
    if cached is not None:
        cached_summary = cached.get("summary") if isinstance(cached.get("summary"), dict) else {}
        cached["summary"] = {
            **cached_summary,
            "range": range_key,
            "cache": "hot",
            "generated_at": _now_iso(),
        }
        return cached, 200
    enrichment = None
    seen_signatures: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    findings_limit = min(
        NETWORK_EVIDENCE_LOOKBACK,
        NETWORK_FINDINGS_LOOKBACK,
        _network_projection_history_limit("12mo"),
    )
    for item in _network_retained_events(limit=findings_limit):
        projected = item
        if _network_finding_needs_enrichment(item):
            if enrichment is None:
                enrichment = _network_enrichment_index(refresh=False)
            projected = _network_apply_enrichment(item, enrichment)
        if not (_network_is_open_finding(projected) and _network_is_review_worthy_finding(projected)):
            continue
        signature = _network_finding_signature(projected)
        existing = seen_signatures.get(signature)
        if existing:
            _network_merge_related_finding(existing, projected)
            if _network_finding_priority_key(projected) < _network_finding_priority_key(existing):
                replacement = projected.copy()
                replacement["related_event_count"] = existing.get("related_event_count", 1)
                replacement["related_event_ids"] = existing.get("related_event_ids", [])
                replacement["related_destinations"] = existing.get("related_destinations", [])
                seen_signatures[signature] = replacement
            continue
        finding = projected.copy()
        finding["related_event_count"] = 1
        finding["related_event_ids"] = [str(finding.get("event_id") or "")]
        destination = str(finding.get("destination_display") or finding.get("dst_ip") or "").strip()
        finding["related_destinations"] = [destination] if destination else []
        seen_signatures[signature] = finding
    deduped = sorted(seen_signatures.values(), key=_network_finding_priority_key)[:min(NETWORK_PROJECTION_LIMIT, 100)]
    events_payload = [_network_public_event(item) for item in deduped]
    payload, status_code = _network_ui_contract(
        _network_projection_state(events_payload),
        events=events_payload,
        summary=_network_projection_summary(
            "findings",
            range_key,
            len(events_payload),
            {
                "ordering": "priority_pinned",
                "projection_window": "12mo",
                "cache": "cold",
                "history_limit": findings_limit,
                "coverage_state": "bounded_retained_queue",
            },
        ),
    )
    _network_findings_cache_set(payload)
    return payload, status_code


def _network_projection_distribution(range_key: str) -> tuple[dict[str, Any], int]:
    # Distribution is packet-evidence projection, never a relabeled socket or
    # process inventory. Open applications remain a separate product dataset.
    visible = _network_events_in_range(
        range_key,
        limit=_network_projection_history_limit(range_key),
    )
    events_payload = [_network_public_event(item) for item in visible[:NETWORK_PROJECTION_LIMIT]]
    app_counts: dict[str, int] = {}
    unresolved = 0
    for item in visible:
        app = _network_event_app(item)
        app_counts[app] = app_counts.get(app, 0) + 1
        if app == "Unknown app":
            unresolved += 1
    open_applications = _network_running_app_summary(visible)
    return _network_ui_contract(
        _network_projection_state(events_payload),
        events=events_payload,
        summary=_network_projection_summary(
            "distribution",
            range_key,
            len(events_payload),
            {
                "classified_apps": app_counts,
                "unresolved_app_events": unresolved,
                "source": "retained_packet_evidence",
                "measurement_basis": "packet_supported_communications",
                "open_applications": open_applications,
                "open_applications_source": "applications_running_gui_inventory",
            },
        ),
    )


def _network_timeline_bucket_key(timestamp: Any, range_key: str) -> str:
    dt = _network_event_datetime(timestamp)
    if range_key in {"5s", "1m"}:
        return f"{range_key}:{int(dt.timestamp())}"
    if range_key in {"30m", "1h"}:
        return dt.strftime(f"{range_key}:%Y-%m-%dT%H:%M")
    if range_key == "24h":
        return dt.strftime("%Y-%m-%dT%H")
    if range_key in {"7d", "1mo"}:
        return dt.strftime("%Y-%m-%d")
    if range_key == "3mo":
        iso = dt.isocalendar()
        return f"{dt.year}-W{iso.week:02d}"
    return dt.strftime("%Y-%m")


def _network_timeline_min_rank(range_key: str) -> int:
    if range_key in {"5s", "1m"}:
        return NETWORK_SEVERITY_RANK["low"]
    if range_key in {"30m", "1h"}:
        return NETWORK_SEVERITY_RANK["low"]
    if range_key in {"24h", "7d"}:
        return NETWORK_SEVERITY_RANK["warning"]
    return NETWORK_SEVERITY_RANK["high"]


def _network_projection_timeline(range_key: str) -> tuple[dict[str, Any], int]:
    cached = _network_projection_cache_get("timeline", range_key)
    if cached is not None:
        return cached, 200
    start, end = _network_projection_window(range_key)
    history_limit = _network_projection_history_limit(range_key)
    visible = _network_events_in_range(range_key, limit=history_limit)
    min_rank = _network_timeline_min_rank(range_key)
    candidates = [
        item for item in visible
        if NETWORK_SEVERITY_RANK.get(str(item.get("severity") or ""), 0) >= min_rank
    ]
    bucketed: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = _network_timeline_bucket_key(item.get("timestamp"), range_key)
        current = bucketed.get(key)
        if not current or _network_event_rank(item) > _network_event_rank(current):
            bucketed[key] = item
    ledger = sorted(bucketed.values(), key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("event_id") or "")))
    events_payload = [_network_public_event(item) for item in ledger[-NETWORK_PROJECTION_LIMIT:]]
    by_id = {str(item.get("event_id") or ""): item for item in events_payload if str(item.get("event_id") or "")}
    local_notables = _stored_network_timeline_notables(limit=history_limit, start=start, end=end)
    vvault_notables = _vvault_network_timeline_notables(range_key, start, end, limit=history_limit)
    for item in [*local_notables, *vvault_notables]:
        event_dt = _network_event_datetime(item.get("timestamp"))
        if not (start <= event_dt < end):
            continue
        public = _network_public_event(item)
        event_id = str(public.get("event_id") or "")
        if event_id:
            by_id[event_id] = public
    gap_events = []
    local_gaps = _stored_network_timeline_gaps(limit=history_limit, start=start, end=end)
    vvault_gaps = _vvault_network_timeline_gaps(range_key, start, end, limit=history_limit)
    for gap in [*local_gaps, *vvault_gaps]:
        event_dt = _network_event_datetime(gap.get("timestamp") or gap.get("gap_end"))
        if start <= event_dt < end:
            gap_events.append(_network_public_event(gap))
    events_payload = sorted(
        [*by_id.values(), *gap_events],
        key=lambda item: (_network_event_datetime(item.get("timestamp")), str(item.get("event_id") or "")),
    )[-NETWORK_PROJECTION_LIMIT:]
    payload, status_code = _network_ui_contract(
        _network_projection_state(events_payload),
        events=events_payload,
        summary=_network_projection_summary(
            "timeline",
            range_key,
            len(events_payload),
            {
                "source_event_count": len(visible),
                "timeline_min_rank": min_rank,
                "gap_count": len(gap_events),
                "refresh_required": True,
                "history_limit": history_limit,
            },
        ),
    )
    _network_projection_cache_set("timeline", range_key, payload)
    _log_network_history_io(
        "timeline_hydration",
        range=range_key,
        event_count=len(events_payload),
        local_notable_count=len(local_notables),
        vvault_notable_count=len(vvault_notables),
        local_gap_count=len(local_gaps),
        vvault_gap_count=len(vvault_gaps),
        gap_count=len(gap_events),
    )
    return payload, status_code


def _network_projection_trend(range_key: str) -> tuple[dict[str, Any], int]:
    cached = _network_projection_cache_get("trend", range_key)
    if cached is not None:
        return cached, 200
    start, end = _network_projection_window(range_key)
    retention_start = _network_retention_start()
    if start < retention_start:
        start = retention_start
    history_limit = _network_projection_history_limit(range_key)
    history_sources = {
        "local_buckets": 0,
        "vvault_buckets": 0,
        "local_ticks": 0,
        "vvault_ticks": 0,
        "local_samples": 0,
        "recent_samples": 0,
        "vvault_samples": 0,
    }
    with _NETWORK_RECENT_OBSERVATIONS_LOCK:
        recent_sample_events = [
            dict(item) for item in _NETWORK_RECENT_OBSERVATIONS
            if start <= _network_event_datetime(item.get("timestamp")) < end
        ]
    recent_only = range_key in {"5s", "1m"} and bool(recent_sample_events)
    local_buckets = [
        bucket for bucket in _stored_network_buckets(limit=history_limit, start=start, end=end)
        if (
            (bucket.get("bucket_range") == range_key or str(bucket.get("bucket_key") or "").startswith(f"{range_key}:"))
            and _network_event_datetime(bucket.get("bucket_end") or bucket.get("timestamp")) >= start
            and _network_event_datetime(bucket.get("bucket_start") or bucket.get("timestamp")) < end
        )
    ] if not recent_only else []
    vvault_buckets = [] if recent_only else _vvault_network_buckets(range_key, start, end, limit=history_limit)
    history_sources["local_buckets"] = len(local_buckets)
    history_sources["vvault_buckets"] = len(vvault_buckets)
    local_ticks = [
        tick for tick in _stored_network_trend_ticks(limit=history_limit, start=start, end=end)
        if tick.get("bucket_range") == range_key and start <= _network_event_datetime(tick.get("timestamp")) < end
    ] if not recent_only else []
    vvault_ticks = [] if recent_only else _vvault_network_trend_ticks(range_key, start, end, limit=history_limit)
    history_sources["local_ticks"] = len(local_ticks)
    history_sources["vvault_ticks"] = len(vvault_ticks)
    local_sample_events = {
        str(item.get("event_id") or ""): item
        for item in ([] if recent_only else _network_stored_observations(limit=history_limit, start=start, end=end))
        if str(item.get("event_id") or "") and start <= _network_event_datetime(item.get("timestamp")) < end
    }
    for item in recent_sample_events:
        event_id = str(item.get("event_id") or "")
        if event_id:
            local_sample_events[event_id] = item
    local_samples = [_network_trend_sample_from_event(item) for item in local_sample_events.values()]
    vvault_samples = [] if recent_only else _vvault_network_trend_samples(start, end, limit=history_limit)
    history_sources["local_samples"] = len(local_samples)
    history_sources["recent_samples"] = len(recent_sample_events)
    history_sources["vvault_samples"] = len(vvault_samples)
    observed_samples = [*local_samples, *vvault_samples]
    ticks = _network_trend_interpretation_buckets(range_key, observed_samples)
    gap_count = max(NETWORK_TREND_BUCKETS.get(range_key, NETWORK_TREND_BUCKETS["5s"]) - len(ticks), 0)
    if not ticks and not local_samples and not vvault_samples:
        gap_event_id = "network_gap:" + hashlib.sha256(f"trend:{range_key}:{start.isoformat()}:{end.isoformat()}".encode("utf-8")).hexdigest()[:24]
        preservation = vvault_preservation.preserve_network_timeline_gap(
            f"trend:{range_key}",
            "no_retained_trend_history",
            {
                "event_id": gap_event_id,
                "event_type": NETWORK_TIMELINE_GAP_EVENT_TYPE,
                "timestamp": end.isoformat().replace("+00:00", "Z"),
                "gap_start": start.isoformat().replace("+00:00", "Z"),
                "gap_end": end.isoformat().replace("+00:00", "Z"),
                "source": "network_trend",
            },
        )
        _log_network_vvault_save_result("timeline_gap", gap_event_id, end, preservation)
    events_payload = [
        _network_public_event(tick)
        for tick in ticks[-NETWORK_PROJECTION_LIMIT:]
    ]
    observed_coverage_start = min(
        (_network_event_datetime(item.get("timestamp")) for item in observed_samples),
        default=None,
    )
    payload, status_code = _network_ui_contract(
        _network_projection_state(events_payload),
        events=events_payload,
        summary=_network_projection_summary(
            "trend",
            range_key,
            len(events_payload),
            {
                "bucket_count": len(events_payload),
                "bucket_scale": range_key,
                "history_sources": history_sources,
                "live_ticks": True,
                "gap_count": gap_count,
                "immutable_ticks": True,
                "interpretation_schema": NETWORK_TREND_INTERPRETATION_SCHEMA,
                "rule_version": NETWORK_TREND_RULE_VERSION,
                "series": ["vulnerabilities", "threats", "strengths"],
                "zero_means": "observed_bucket_without_matching_signal",
                "missing_means": "no_retained_evidence_for_bucket",
                "history_limit": history_limit,
                "coverage_state": (
                    "continuous" if observed_coverage_start and observed_coverage_start <= start
                    else "partial" if observed_coverage_start
                    else "unknown"
                ),
                "coverage_start": observed_coverage_start.isoformat().replace("+00:00", "Z") if observed_coverage_start else None,
            },
        ),
    )
    _network_projection_cache_set("trend", range_key, payload)
    _log_network_history_io(
        "trend_hydration",
        range=range_key,
        event_count=len(events_payload),
        history_sources=history_sources,
        gap_count=gap_count,
    )
    return payload, status_code


def _network_current_packet_payload() -> tuple[dict[str, Any], int]:
    # The default table API must stay cheap and CLI-probeable. Enrichment can
    # invoke process/socket collectors, so leave it to projections and refreshes.
    events_payload = [
        _network_public_event(item)
        for item in _network_events_in_range("1m", limit=min(NETWORK_EVIDENCE_LOOKBACK, 200), enrich_unknown=False)[-WIRESHARK_MAX_EVENTS:]
    ]
    ui_state = _network_runtime_probe_state(events_payload)
    collector = _get_network_collector()
    collector.start()
    boundary = collector.snapshot(include_events=False)
    payload, status_code = _network_ui_contract(
        ui_state,
        events=events_payload,
        summary={
            "reason": "events_observed" if events_payload else ("waiting_for_capture" if ui_state == "WARMING" else "no_data"),
            "event_count": len(events_payload),
            "source": "runtime_packet_buffer",
            "cursor": boundary["cursor"],
        },
    )
    collector_health = network_collector_health()
    payload.update({
        "cursor": boundary["cursor"],
        "high_water_cursor": boundary["high_water_cursor"],
        "high_water_sequence": boundary["high_water_sequence"],
    })
    _network_apply_collector_truth(payload, collector_health)
    return payload, status_code


@bp.route("/cleanhouse/network/projection", methods=["GET"])
def network_projection():
    vvault_error = _network_vvault_required_error()
    if vvault_error:
        return jsonify(vvault_error[0]), vvault_error[1]
    view = str(request.args.get("view") or "").strip().lower()
    range_key = str(request.args.get("range") or request.args.get("timeline") or "5s").strip()
    if view not in NETWORK_PROJECTION_VIEWS:
        return jsonify(_network_error_contract("capture_failed")[0]), 400
    if range_key not in NETWORK_TIME_RANGES_MS:
        range_key = "5s"
    projectors = {
        "findings": _network_projection_findings,
        "trend": _network_projection_trend,
        "distribution": _network_projection_distribution,
        "timeline": _network_projection_timeline,
    }
    collector = _get_network_collector()
    collector.start()
    if _refresh_flag():
        collector.refresh(timeout=2.0)
        with _NETWORK_FINDINGS_CACHE_LOCK:
            _NETWORK_FINDINGS_CACHE.update({"payload": None, "cached_at": 0.0})
        with _NETWORK_PROJECTION_CACHE_LOCK:
            _NETWORK_PROJECTION_CACHE.clear()
    payload, status_code = projectors[view](range_key)
    boundary = collector.snapshot(include_events=False)
    payload["cursor"] = boundary["cursor"]
    payload["high_water_cursor"] = boundary["high_water_cursor"]
    payload["high_water_sequence"] = boundary["high_water_sequence"]
    _network_apply_collector_truth(payload, network_collector_health())
    if isinstance(payload.get("summary"), dict):
        payload["summary"]["cursor"] = boundary["cursor"]
        payload["summary"]["refresh"] = "synchronized" if _refresh_flag() else "not_requested"
    return jsonify(payload), status_code


@bp.route("/cleanhouse/network", methods=["GET"])
def network():
    vvault_error = _network_vvault_required_error()
    if vvault_error:
        return jsonify(vvault_error[0]), vvault_error[1]
    if _truthy_arg("snapshot"):
        payload, status_code = _network_snapshot_payload(refresh=_refresh_flag())
        return jsonify(payload), status_code
    payload, status_code = _network_current_packet_payload()
    return jsonify(payload), status_code


@bp.route("/cleanhouse/ai-activity", methods=["GET"])
def ai_activity():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_ai_activity(refresh=_refresh_flag()))


@bp.route("/cleanhouse/anomalies", methods=["GET"])
def anomalies():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_anomalies(refresh=_refresh_flag()))


@bp.route("/cleanhouse/integrity", methods=["GET"])
def integrity():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_integrity(refresh=_refresh_flag()))


@bp.route("/cleanhouse/commands", methods=["GET"])
def commands():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_commands(refresh=_refresh_flag()))


@bp.route("/cleanhouse/intent", methods=["POST"])
def submit_intent():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()

    text, error = _require_string(data.get("text"), "text", required=False, allow_empty=True, max_len=8192)
    if error:
        return error
    scope, error = _require_string(data.get("scope"), "scope", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    repo_path = data.get("repo_path")
    if repo_path is not None:
        repo_path, error = _validate_repo_path(repo_path)
        if error:
            return error
        repo_path = str(repo_path)
    else:
        repo_path = None

    tool_identity, error = _require_string(data.get("tool_identity"), "tool_identity", required=False, allow_empty=True, max_len=64)
    if error:
        return error

    return jsonify(adapter.submit_intent(
        text or "",
        scope or "",
        repo_path,
        tool_identity or "CleanHouse",
    ))


def _objective_text_from_payload(payload: dict[str, Any]) -> str:
    for field in ("objective", "summary", "text"):
        if isinstance(payload.get(field), str):
            text = payload[field].strip()
            if text:
                return text
    return ""


def _bound_objective_id(
    adapter: CleanHouseMonitoringAdapter,
    *,
    session_id: str | None,
    objective_id: str | None,
    objective_text: str,
) -> str:
    explicit = objective_id.strip() if isinstance(objective_id, str) and objective_id.strip() else ""
    if explicit:
        return explicit
    if session_id and hasattr(adapter, "_objective_id_for_session"):
        existing = str(adapter._objective_id_for_session(session_id) or "").strip()  # type: ignore[attr-defined]
        if existing:
            return existing
    if session_id and objective_text:
        seed = f"{session_id}:{objective_text[:512]}"
        return f"objective:{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:24]}"
    return str(uuid.uuid4())


@bp.route("/cleanhouse/objective/start", methods=["POST"])
def start_objective():
    data, error = _parse_json_payload()
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, max_len=256)
    if error:
        return error
    session_id, error = _resolve_session_id(data.get("session_id"), required=False)
    if error:
        return error
    summary = _objective_text_from_payload(data)
    adapter = get_cleanhouse_monitoring_adapter()
    objective_id = _bound_objective_id(
        adapter,
        session_id=session_id or DEFAULT_SESSION_ID,
        objective_id=objective_id,
        objective_text=summary,
    )

    events.insert_event(
        event_type="objective_start",
        path=f"/objectives/{objective_id}",
        summary=summary,
        session_id=session_id or DEFAULT_SESSION_ID,
    )
    return jsonify({
        "status": "ok",
        "session_id": session_id or DEFAULT_SESSION_ID,
        "objective_id": objective_id,
        "event_type": "objective_start",
    })


@bp.route("/cleanhouse/objective/end", methods=["POST"])
def end_objective():
    data, error = _parse_json_payload()
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id")
    if error:
        return error
    session_id, error = _resolve_session_id(data.get("session_id"), required=False)
    if error:
        return error
    summary = _objective_text_from_payload(data)

    events.insert_event(
        event_type="objective_end",
        path=f"/objectives/{objective_id}",
        summary=summary,
        session_id=session_id or DEFAULT_SESSION_ID,
    )
    return jsonify({
        "status": "ok",
        "session_id": session_id or DEFAULT_SESSION_ID,
        "objective_id": objective_id,
        "event_type": "objective_end",
    })


@bp.route("/cleanhouse/intents", methods=["GET"])
def intents():
    adapter = get_cleanhouse_monitoring_adapter()
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_INTENT_MAX_LIMIT)
    if error:
        return error
    return jsonify(adapter.get_intents(limit=limit or LOW_PROCESSING_INTENT_LIMIT))


@bp.route("/cleanhouse/prompt", methods=["POST"])
def submit_prompt():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()

    text, error = _require_string(data.get("text"), "text", max_len=16384)
    if error:
        return error
    context, error = _require_string(data.get("context"), "context", required=False, allow_empty=True, max_len=32768)
    if error:
        return error
    scope, error = _require_string(data.get("scope"), "scope", required=False, allow_empty=True, max_len=1024)
    if error:
        return error

    repo_path = data.get("repo_path")
    if isinstance(repo_path, str) and not repo_path.strip():
        repo_path = None
    if repo_path is not None:
        repo_path, error = _validate_repo_path(repo_path)
        if error:
            return error
        repo_path = str(repo_path)

    tool_identity, error = _require_string(data.get("tool_identity"), "tool_identity", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    bound_objective_id = _bound_objective_id(
        adapter,
        session_id=session_id,
        objective_id=objective_id,
        objective_text=text,
    )
    prompt_type, error = _require_string(data.get("prompt_type"), "prompt_type", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    source, error = _require_string(data.get("source"), "source", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    parent_intervention_id, error = _require_string(data.get("parent_intervention_id"), "parent_intervention_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")

    return jsonify(adapter.submit_prompt(
        text=text,
        context=context or "",
        scope=scope or "",
        repo_path=repo_path,
        tool_identity=tool_identity or "CleanHouse",
        session_id=session_id,
        objective_id=bound_objective_id or None,
        prompt_type=prompt_type or "objective",
        parent_intervention_id=parent_intervention_id or None,
        evidence_refs=evidence_refs,
        metadata=metadata,
        source=source or "ui",
    ))


@bp.route("/cleanhouse/prompts", methods=["GET"])
def prompts():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    objective_id, error = _require_string(request.args.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    return jsonify(adapter.get_prompts(session_id=session_id, objective_id=objective_id or None))


@bp.route("/cleanhouse/session/start", methods=["POST"])
def start_operator_session():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    summary, error = _require_string(data.get("summary"), "summary", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    adapter = get_cleanhouse_monitoring_adapter()
    bound_objective_id = _bound_objective_id(
        adapter,
        session_id=session_id,
        objective_id=objective_id,
        objective_text=summary or "",
    )
    return jsonify(adapter.start_operator_session({
        "session_id": session_id,
        "objective_id": bound_objective_id or None,
        "summary": summary or "",
        "metadata": metadata,
    }))


@bp.route("/cleanhouse/session/stop", methods=["POST"])
def stop_operator_session():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    summary, error = _require_string(data.get("summary"), "summary", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    finalize = data.get("finalize", False)
    if not isinstance(finalize, bool):
        return _error_response("finalize must be a boolean")
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.stop_operator_session({
        "session_id": session_id,
        "summary": summary or "",
        "metadata": metadata,
        "finalize": finalize,
    }))


@bp.route("/cleanhouse/workstation", methods=["GET"])
def workstation():
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    if _fast_operator_api_enabled() and not _truthy_arg("full"):
        return jsonify(_fast_workstation_payload(session_id, include_scope_evidence=_truthy_arg("scope_evidence")))
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_workstation(session_id=session_id))


@bp.route("/cleanhouse/investigations/application", methods=["POST"])
def application_investigation():
    data, error = _parse_json_payload()
    if error:
        return error
    result = run_application_investigation_with_timeout(data)
    if result.get("status") == "degraded":
        return jsonify(result), 503
    return jsonify(result)


@bp.route("/cleanhouse/active-context", methods=["GET"])
def active_context():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_active_context(refresh=_refresh_flag(), attach=_truthy_arg("attach")))


@bp.route("/cleanhouse/active-context/follow", methods=["POST"])
def active_context_follow():
    data, error = _parse_json_payload()
    if error:
        return error
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return _error_response("enabled must be a boolean")
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.set_active_context_follow(enabled))


@bp.route("/cleanhouse/active-context/pickup", methods=["POST"])
def active_context_pickup():
    data, error = _parse_json_payload()
    if error:
        return error
    if data.get("text") is None and data.get("prompt") is not None:
        data["text"] = data.get("prompt")
    text, error = _require_string(data.get("text"), "text", required=False, allow_empty=True, max_len=16384)
    if error:
        return error
    context, error = _require_string(data.get("context"), "context", required=False, allow_empty=True, max_len=32768)
    if error:
        return error
    if not (text or context):
        return _error_response("text or context is required")
    repo_path = data.get("repo_path")
    if isinstance(repo_path, str) and not repo_path.strip():
        repo_path = None
    if repo_path is not None:
        repo_path, error = _validate_repo_path(repo_path)
        if error:
            return error
        repo_path = str(repo_path)
    tool_identity, error = _require_string(data.get("tool_identity"), "tool_identity", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    objective, error = _require_string(data.get("objective"), "objective", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    source_ref, error = _require_string(data.get("source_ref"), "source_ref", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    pickup = {
        "text": text or "",
        "context": context or "",
        "repo_path": repo_path or "",
        "tool_identity": tool_identity or "CleanHouse",
        "session_id": session_id or "",
        "objective_id": objective_id or "",
        "objective": objective or "",
        "source_ref": source_ref or "",
    }
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.pickup_active_context(pickup))


@bp.route("/cleanhouse/active-context/ignore", methods=["POST"])
def active_context_ignore():
    data, error = _parse_json_payload()
    if error:
        return error
    dedupe_key, error = _require_string(data.get("dedupe_key"), "dedupe_key", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.ignore_active_context(dedupe_key or None))


@bp.route("/cleanhouse/continuity", methods=["GET"])
def continuity_provenance():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_continuity_provenance(session_id=session_id))


@bp.route("/cleanhouse/continuity/pins", methods=["POST"])
def pin_continuity_context():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    text, error = _require_string(data.get("text"), "text", max_len=16384)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    source_ref, error = _require_string(data.get("source_ref"), "source_ref", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    operator, error = _require_string(data.get("operator"), "operator", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    return jsonify(get_cleanhouse_monitoring_adapter().pin_continuity_context({
        "session_id": session_id,
        "objective_id": objective_id or None,
        "text": text,
        "source_ref": source_ref or "",
        "operator": operator or "api",
        "evidence_refs": evidence_refs,
        "metadata": metadata,
    }))


@bp.route("/cleanhouse/continuity/decision", methods=["POST"])
def record_continuity_decision():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    claim_id, error = _require_string(data.get("claim_id"), "claim_id", max_len=512)
    if error:
        return error
    decision, error = _require_string(data.get("decision"), "decision", max_len=32)
    if error:
        return error
    decision = decision.lower()
    if decision not in {"accept", "ignore"}:
        return _error_response("decision must be accept or ignore")
    note, error = _require_string(data.get("note"), "note", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    operator, error = _require_string(data.get("operator"), "operator", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    return jsonify(get_cleanhouse_monitoring_adapter().record_continuity_decision({
        "session_id": session_id,
        "claim_id": claim_id,
        "decision": decision,
        "note": note or "",
        "operator": operator or "api",
        "evidence_refs": evidence_refs,
        "metadata": metadata,
    }))


@bp.route("/cleanhouse/continuity/search", methods=["POST"])
def search_continuity():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    query, error = _require_string(data.get("query"), "query", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    operator, error = _require_string(data.get("operator"), "operator", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    payload = {
        "session_id": session_id,
        "query": query or "",
        "operator": operator or "api",
    }
    for key in ("max_results", "max_files", "max_bytes"):
        if key in data:
            if not isinstance(data.get(key), int) or isinstance(data.get(key), bool):
                return _error_response(f"{key} must be an integer")
            payload[key] = data[key]
    return jsonify(get_cleanhouse_monitoring_adapter().search_continuity(payload))


@bp.route("/cleanhouse/accounts/connect/start", methods=["POST"])
def connected_account_connect_start():
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    data, error = _parse_json_payload()
    if error:
        return error
    provider, error = _require_string(data.get("provider"), "provider", max_len=64)
    if error:
        return error
    connection_method, error = _require_string(data.get("connection_method"), "connection_method", max_len=64)
    if error:
        return error
    consent_version, error = _require_string(data.get("consent_version"), "consent_version", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().start_connected_account_connect(
        cleanhouse_user_id=user_id,
        provider=provider,
        connection_method=connection_method,
        consent_version=consent_version or "v1",
    ))


@bp.route("/cleanhouse/accounts/connect/callback", methods=["POST"])
def connected_account_connect_callback():
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    data, error = _parse_json_payload()
    if error:
        return error
    provider, error = _require_string(data.get("provider"), "provider", max_len=64)
    if error:
        return error
    connection_method, error = _require_string(data.get("connection_method"), "connection_method", max_len=64)
    if error:
        return error
    connect_session_token, error = _require_string(data.get("connect_session_token"), "connect_session_token", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    provider_account_id, error = _require_string(data.get("provider_account_id"), "provider_account_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    consent_version, error = _require_string(data.get("consent_version"), "consent_version", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    access_token, error = _require_string(data.get("access_token"), "access_token", required=False, allow_empty=True, max_len=8192)
    if error:
        return error
    refresh_token, error = _require_string(data.get("refresh_token"), "refresh_token", required=False, allow_empty=True, max_len=8192)
    if error:
        return error
    connector_signing_secret, error = _require_string(
        data.get("connector_signing_secret"),
        "connector_signing_secret",
        required=False,
        allow_empty=True,
        max_len=8192,
    )
    if error:
        return error
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    scopes = data.get("scopes", [])
    if isinstance(scopes, str):
        scopes = [item.strip() for item in scopes.split(",") if item.strip()]
    if not isinstance(scopes, list):
        return _error_response("scopes must be a list or comma-separated string")
    return jsonify(get_cleanhouse_monitoring_adapter().complete_connected_account_connect(
        cleanhouse_user_id=user_id,
        provider=provider,
        connection_method=connection_method,
        connect_session_token=connect_session_token or "",
        provider_account_id=provider_account_id or "",
        scopes=[str(item) for item in scopes],
        consent_version=consent_version or "v1",
        access_token=access_token or "",
        refresh_token=refresh_token or "",
        connector_signing_secret=connector_signing_secret or "",
        metadata=metadata,
    ))


@bp.route("/cleanhouse/accounts", methods=["GET"])
def connected_accounts_list():
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    return jsonify(get_cleanhouse_monitoring_adapter().list_connected_accounts(cleanhouse_user_id=user_id))


@bp.route("/cleanhouse/accounts/<account_id>/disconnect", methods=["POST"])
def connected_account_disconnect(account_id: str):
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    account_id, error = _require_string(account_id, "account_id", max_len=256)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().disconnect_connected_account(
        cleanhouse_user_id=user_id,
        account_id=account_id,
    ))


@bp.route("/cleanhouse/accounts/<account_id>/sync", methods=["POST"])
def connected_account_sync(account_id: str):
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    account_id, error = _require_string(account_id, "account_id", max_len=256)
    if error:
        return error
    data, parse_error = _parse_json_payload()
    if parse_error:
        return parse_error
    events = data.get("events", [])
    if events is None:
        events = []
    if not isinstance(events, list):
        return _error_response("events must be a list")
    cursor, error = _require_string(data.get("cursor"), "cursor", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().sync_connected_account(
        cleanhouse_user_id=user_id,
        account_id=account_id,
        events=events,
        cursor=cursor or "",
    ))


@bp.route("/cleanhouse/provider-events/import", methods=["POST"])
def provider_events_import():
    user_id, auth_error = _extract_authenticated_user_id()
    if auth_error:
        return auth_error
    data, error = _parse_json_payload()
    if error:
        return error
    provider, error = _require_string(data.get("provider"), "provider", max_len=64)
    if error:
        return error
    account_id, error = _require_string(data.get("account_id"), "account_id", max_len=256)
    if error:
        return error
    signature, error = _require_string(data.get("signature"), "signature", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    nonce, error = _require_string(data.get("nonce"), "nonce", required=False, allow_empty=True, max_len=512)
    if error:
        return error
    imported_at, error = _require_string(data.get("imported_at"), "imported_at", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    capture_method, error = _require_string(data.get("capture_method"), "capture_method", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    cursor, error = _require_string(data.get("cursor"), "cursor", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    events_batch = data.get("events", [])
    if not isinstance(events_batch, list):
        return _error_response("events must be a list")
    return jsonify(get_cleanhouse_monitoring_adapter().import_provider_events(
        cleanhouse_user_id=user_id,
        provider=provider,
        account_id=account_id,
        events=events_batch,
        signature=signature or "",
        nonce=nonce or "",
        imported_at=imported_at or None,
        capture_method=capture_method or "",
        cursor=cursor or "",
    ))


@bp.route("/cleanhouse/notifications/<notification_id>/ack", methods=["POST"])
def ack_notification(notification_id):
    notification_id, error = _require_string(notification_id, "notification_id", max_len=256)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.ack_operator_notification(notification_id))


@bp.route("/cleanhouse/notifications/<notification_id>/unack", methods=["POST"])
def unack_notification(notification_id):
    notification_id, error = _require_string(notification_id, "notification_id", max_len=256)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.set_operator_notification_acknowledged(notification_id, acknowledged=False))


@bp.route("/cleanhouse/notifications/<notification_id>/snooze", methods=["POST"])
def snooze_notification(notification_id):
    notification_id, error = _require_string(notification_id, "notification_id", max_len=256)
    if error:
        return error
    data, parse_error = _parse_json_payload()
    if parse_error:
        return parse_error
    minutes = data.get("minutes", 10)
    if not isinstance(minutes, int) or minutes < 1:
        return _error_response("minutes must be a positive integer")
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.snooze_operator_notification(notification_id, minutes=minutes))


@bp.route("/cleanhouse/notifications/<notification_id>/timeline", methods=["GET"])
def notification_timeline(notification_id):
    notification_id, error = _require_string(notification_id, "notification_id", max_len=256)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.notification_visibility_timeline(notification_id))


@bp.route("/cleanhouse/notifications/probe", methods=["POST"])
def notification_probe():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    notification_type, error = _require_string(data.get("notification_type"), "notification_type", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    severity, error = _require_string(data.get("severity"), "severity", required=False, allow_empty=True, max_len=32)
    if error:
        return error
    summary, error = _require_string(data.get("summary"), "summary", required=False, allow_empty=True, max_len=512)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.send_test_operator_notification(
        session_id=session_id or "runtime-global",
        objective_id=objective_id or None,
        notification_type=notification_type or "codex_prompt_sent",
        severity=severity or "info",
        summary=summary or "CleanHouse test notification",
    ))


@bp.route("/cleanhouse/approval-queue", methods=["POST"])
def create_approval_queue_item():
    data, error = _parse_json_payload()
    if error:
        return error

    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    requested_action, error = _require_string(data.get("requested_action") or data.get("action"), "requested_action", max_len=4096)
    if error:
        return error
    reason, error = _require_string(data.get("reason"), "reason", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    prompt_id, error = _require_string(data.get("prompt_id"), "prompt_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    source, error = _require_string(data.get("source"), "source", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    reviewer_note, error = _require_string(data.get("reviewer_note"), "reviewer_note", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    reviewer, error = _require_string(data.get("reviewer"), "reviewer", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")

    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.create_approval_queue_item({
        "session_id": session_id,
        "requested_action": requested_action,
        "reason": reason or "",
        "evidence_refs": evidence_refs,
        "prompt_id": prompt_id or None,
        "objective_id": objective_id or None,
        "source": source or "api",
        "reviewer_note": reviewer_note or "",
        "reviewer": reviewer or source or "api",
        "metadata": metadata,
    }))


@bp.route("/cleanhouse/approval-queue", methods=["GET"])
def approval_queue():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    status, error = _require_string(request.args.get("status"), "status", required=False, allow_empty=True, max_len=32)
    if error:
        return error
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_APPROVAL_MAX_LIMIT)
    if error:
        return error
    return jsonify(adapter.get_approval_queue(
        session_id=session_id,
        status=status or None,
        max_records=limit or LOW_PROCESSING_APPROVAL_LIMIT,
    ))


@bp.route("/cleanhouse/approval-queue/<approval_id>", methods=["POST"])
def resolve_approval_queue_item(approval_id):
    data, error = _parse_json_payload()
    if error:
        return error
    approval_id, error = _require_string(approval_id, "approval_id", max_len=256)
    if error:
        return error
    status, error = _require_string(data.get("status"), "status", max_len=32)
    if error:
        return error
    note, error = _require_string(data.get("note"), "note", required=False, allow_empty=True, max_len=4096)
    if error:
        return error
    reviewer, error = _require_string(data.get("reviewer"), "reviewer", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.resolve_approval_queue_item(
        approval_id=approval_id,
        status=status,
        note=note or "",
        reviewer=reviewer or "api",
    ))


@bp.route("/cleanhouse/snapshot", methods=["POST"])
def create_snapshot():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()

    repo_path, error = _validate_repo_path(data.get("repo_path"))
    if error:
        return error

    label, error = _require_string(data.get("label"), "label", required=False, allow_empty=True, max_len=256)
    if error:
        return error

    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error

    return jsonify(adapter.create_snapshot(
        repo_path=str(repo_path),
        label=label or "",
        session_id=session_id,
    ))


@bp.route("/cleanhouse/diff", methods=["POST"])
def diff():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    before_id, error = _validate_session_id(data.get("before_id"))
    if error:
        return error
    after_id, error = _validate_session_id(data.get("after_id"))
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error

    window_value = data.get("max_time_window_seconds", 30.0)
    if not isinstance(window_value, (int, float)) or isinstance(window_value, bool):
        return _error_response("max_time_window_seconds must be a number")
    max_window = float(window_value)
    return jsonify(adapter.compute_diff(
        before_id=before_id,
        after_id=after_id,
        session_id=session_id,
        max_time_window_seconds=max_window,
    ))


@bp.route("/cleanhouse/diffs", methods=["GET"])
def diffs():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_diffs(session_id=session_id))


@bp.route("/cleanhouse/correlate", methods=["POST"])
def correlate():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error

    max_window = data.get("max_time_window_seconds", 30.0)
    if not isinstance(max_window, (int, float)) or isinstance(max_window, bool):
        return _error_response("max_time_window_seconds must be a number")

    return jsonify(adapter.correlate(
        session_id=session_id,
        max_time_window_seconds=float(max_window),
    ))


@bp.route("/cleanhouse/correlations", methods=["GET"])
def correlations():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_correlations(session_id=session_id))


@bp.route("/cleanhouse/timeline", methods=["POST"])
def build_timeline():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    return jsonify(adapter.build_timeline(session_id=session_id))


@bp.route("/cleanhouse/timelines", methods=["GET"])
def timelines():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_timelines(session_id=session_id))


@bp.route("/cleanhouse/classify", methods=["POST"])
def classify():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    return jsonify(adapter.classify(session_id=session_id))


@bp.route("/cleanhouse/signals", methods=["GET"])
def signals():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    signal_class = request.args.get("signal_class")
    return jsonify(adapter.get_signals(session_id=session_id, signal_class=signal_class))


@bp.route("/cleanhouse/alerts", methods=["POST"])
def generate_alerts():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    return jsonify(adapter.generate_alerts(session_id=session_id))


@bp.route("/cleanhouse/alerts", methods=["GET"])
def get_alerts():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    alert_type = request.args.get("alert_type")
    return jsonify(adapter.get_alerts(session_id=session_id, alert_type=alert_type))


@bp.route("/cleanhouse/infer", methods=["POST"])
def zaelith_infer():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    return jsonify(adapter.run_zaelith_inference(session_id=session_id))


@bp.route("/cleanhouse/zaelith/analyze", methods=["POST"])
def zaelith_analyze_text():
    data, error = _parse_json_payload()
    if error:
        return error
    text, error = _require_string(data.get("text"), "text", max_len=200000)
    if error:
        return error
    prompt, error = _require_string(
        data.get("prompt"),
        "prompt",
        required=False,
        allow_empty=True,
        max_len=4096,
    )
    if error:
        return error
    source, error = _require_string(
        data.get("source"),
        "source",
        required=False,
        allow_empty=True,
        max_len=128,
    )
    if error:
        return error
    try:
        from corefiles.zaelith_service import get_zaelith_service
        service = get_zaelith_service()
        result = service.analyze_text_interaction(
            prompt or "Manual Zaelith conversation audit",
            text,
            source=source or "zaelith-page",
            save_to_history=True,
        )
    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": f"Zaelith analysis failed: {exc}",
        }), 500
    status = "ok" if result.get("success") else "error"
    report = None
    if status == "ok":
        report = get_cleanhouse_monitoring_adapter().build_zaelith_report(
            analysis=result,
            prompt=prompt or "Manual Zaelith conversation audit",
            response=text,
            source=source or "zaelith-page",
        )
    return jsonify({
        "status": status,
        "analysis": result,
        "report": report,
        "boundaries": {
            "observed": "Pattern matches and evidence snippets from the submitted text.",
            "inferred": "Risk labels and confidence are heuristic summaries.",
            "unknown": "Speaker identity, hidden motive, and objective truth are not asserted.",
        },
    })


@bp.route("/cleanhouse/receipt", methods=["POST"])
def build_receipt():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error

    result = adapter.build_receipt(session_id=session_id)
    if data.get("zaelith", False) and result.get("status") == "ok":
        inference = adapter.run_zaelith_inference(session_id=session_id)
        inf = inference.get("inference", {})
        result["zaelith_inference"] = inf
        assessment = adapter.run_scope_alignment(session_id=session_id)
        result["scope_assessment"] = {
            k: v for k, v in assessment.items() if k != "status"
        }
    return jsonify(result)


@bp.route("/cleanhouse/assess", methods=["POST"])
def assess_scope():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    return jsonify(adapter.run_scope_alignment(session_id=session_id))


@bp.route("/cleanhouse/receipts", methods=["GET"])
def get_receipts():
    adapter = get_cleanhouse_monitoring_adapter()
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_RECEIPT_MAX_LIMIT)
    if error:
        return error
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_receipts(session_id=session_id, max_records=limit or LOW_PROCESSING_RECEIPT_LIMIT))


@bp.route("/cleanhouse/receipt-replay", methods=["GET"])
def receipt_replay():
    adapter = get_cleanhouse_monitoring_adapter()
    receipt_id, error = _require_string(request.args.get("receipt_id"), "receipt_id", max_len=256)
    if error:
        return error
    return jsonify(adapter.replay_receipt_state(receipt_id=receipt_id))


@bp.route("/cleanhouse/receipt-bundle", methods=["GET"])
def receipt_bundle():
    adapter = get_cleanhouse_monitoring_adapter()
    receipt_id, error = _require_string(request.args.get("receipt_id"), "receipt_id", max_len=256)
    if error:
        return error
    return jsonify(adapter.export_receipt_timeline_bundle(receipt_id=receipt_id))


@bp.route("/cleanhouse/receipt-bundle/import", methods=["POST"])
def import_receipt_bundle():
    data, error = _parse_json_payload()
    if error:
        return error
    payload = data.get("bundle") if isinstance(data.get("bundle"), dict) else data
    if not isinstance(payload, dict):
        return _error_response("bundle must be an object")
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.import_receipt_timeline_bundle(payload))


@bp.route("/cleanhouse/rollback/request", methods=["POST"])
def request_rollback():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    path, error = _require_string(data.get("path") or data.get("requested_path"), "path", max_len=2048)
    if error:
        return error
    payload = dict(data)
    payload["session_id"] = session_id
    payload["path"] = path
    if "evidence_refs" in payload and not isinstance(payload.get("evidence_refs"), list):
        return _error_response("evidence_refs must be a list")
    if "metadata" in payload and not isinstance(payload.get("metadata"), dict):
        return _error_response("metadata must be an object")
    return jsonify(adapter.request_rollback(payload))


@bp.route("/cleanhouse/rollback/execute", methods=["POST"])
def execute_rollback():
    data, error = _parse_json_payload()
    if error:
        return error
    rollback_id, error = _require_string(data.get("rollback_id"), "rollback_id", max_len=256)
    if error:
        return error
    payload = dict(data)
    payload["rollback_id"] = rollback_id
    return jsonify(get_cleanhouse_monitoring_adapter().execute_rollback(payload))


@bp.route("/cleanhouse/rollback", methods=["GET"])
def get_rollbacks():
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().get_rollbacks(session_id=session_id))


@bp.route("/cleanhouse/task-manager", methods=["GET"])
def task_manager_snapshot():
    return jsonify(get_cleanhouse_monitoring_adapter().get_task_manager_snapshot(refresh=_refresh_flag()))


@bp.route("/cleanhouse/port-monitor", methods=["GET"])
def port_monitor_snapshot():
    return jsonify(get_cleanhouse_monitoring_adapter().get_port_monitor_snapshot(refresh=_refresh_flag()))


@bp.route("/cleanhouse/domains", methods=["GET"])
def domain_observer_catalog():
    return jsonify(get_cleanhouse_monitoring_adapter().get_domain_observer_catalog())


@bp.route("/cleanhouse/domain-events", methods=["GET"])
def domain_events():
    adapter = get_cleanhouse_monitoring_adapter()
    domain, error = _require_string(request.args.get("domain"), "domain", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    surface, error = _require_string(request.args.get("surface"), "surface", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    severity, error = _require_string(request.args.get("severity"), "severity", required=False, allow_empty=True, max_len=32)
    if error:
        return error
    status, error = _require_string(request.args.get("status"), "status", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_DOMAIN_EVENT_MAX_LIMIT)
    if error:
        return error
    return jsonify(adapter.get_domain_events(
        domain=domain or None,
        surface=surface or None,
        severity=severity or None,
        status=status or None,
        limit=limit or LOW_PROCESSING_DOMAIN_EVENT_LIMIT,
    ))


@bp.route("/cleanhouse/domain-events", methods=["POST"])
def emit_domain_event():
    data, error = _parse_json_payload()
    if error:
        return error
    domain, error = _require_string(data.get("domain"), "domain", max_len=128)
    if error:
        return error
    surface, error = _require_string(data.get("surface"), "surface", max_len=128)
    if error:
        return error
    event_type, error = _require_string(data.get("event_type"), "event_type", max_len=128)
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"), required=False)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    observed_at, error = _require_string(data.get("observed_at"), "observed_at", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    severity, error = _require_string(data.get("severity"), "severity", required=False, allow_empty=True, max_len=32)
    if error:
        return error
    actor = data.get("actor", {})
    if not isinstance(actor, dict):
        return _error_response("actor must be an object")
    resource = data.get("resource", {})
    if not isinstance(resource, dict):
        return _error_response("resource must be an object")
    observed_vs_expected = data.get("observed_vs_expected", {})
    if not isinstance(observed_vs_expected, dict):
        return _error_response("observed_vs_expected must be an object")
    unknown_fields = data.get("unknown_fields", [])
    if not isinstance(unknown_fields, list):
        return _error_response("unknown_fields must be a list")
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    payload = {
        "domain": domain,
        "surface": surface,
        "event_type": event_type,
        "session_id": session_id,
        "objective_id": objective_id or None,
        "observed_at": observed_at or None,
        "severity": severity or None,
        "actor": actor,
        "resource": resource,
        "observed_vs_expected": observed_vs_expected,
        "unknown_fields": unknown_fields,
        "evidence_refs": evidence_refs,
        "metadata": metadata,
    }
    if "confidence" in data:
        payload["confidence"] = data.get("confidence")
    return jsonify(get_cleanhouse_monitoring_adapter().emit_domain_event(payload))


@bp.route("/cleanhouse/incidents", methods=["GET"])
def incident_cases():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    status, error = _require_string(request.args.get("status"), "status", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    severity, error = _require_string(request.args.get("severity"), "severity", required=False, allow_empty=True, max_len=32)
    if error:
        return error
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    return jsonify(adapter.get_incident_cases(
        session_id=session_id,
        status=status or None,
        severity=severity or None,
        limit=limit or 200,
    ))


@bp.route("/cleanhouse/incidents/<incident_id>/<action>", methods=["POST"])
def incident_action(incident_id, action):
    data, error = _parse_json_payload()
    if error:
        return error
    incident_id, error = _require_string(incident_id, "incident_id", max_len=256)
    if error:
        return error
    action, error = _require_string(action, "action", max_len=32)
    if error:
        return error
    note, error = _require_string(data.get("note"), "note", required=False, allow_empty=True, max_len=2048)
    if error:
        return error
    actor, error = _require_string(data.get("actor"), "actor", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().update_incident_case(
        incident_id,
        action,
        note=note or "",
        actor=actor or "operator",
    ))


@bp.route("/cleanhouse/notification-delivery", methods=["GET"])
def notification_delivery_audit():
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().notification_delivery_audit(limit=limit or 200))


@bp.route("/cleanhouse/notification-policy", methods=["GET"])
def notification_policy():
    adapter = get_cleanhouse_monitoring_adapter()
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    return jsonify({
        **adapter.notification_policy_config(),
        "decisions": adapter.notification_policy_audit(limit=limit or 200).get("decisions", []),
    })


@bp.route("/cleanhouse/action-outcomes", methods=["GET"])
def action_outcomes():
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().action_outcome_audit(limit=limit or 200))


@bp.route("/cleanhouse/evidence/context", methods=["GET"])
def evidence_context():
    data, error = _extract_evidence_request()
    if error:
        return error
    try:
        context = _resolve_evidence_context(data)
    except Exception:
        return _error_response("Unable to resolve evidence context.")
    return jsonify({"status": "ok", "context": context.to_dict()})


@bp.route("/cleanhouse/evidence/actions", methods=["GET"])
def evidence_actions():
    data, error = _extract_evidence_request()
    if error:
        return error
    try:
        context = _resolve_evidence_context(data)
    except Exception:
        return _error_response("Unable to resolve evidence actions.")
    resolver = get_evidence_context_resolver()
    actions = resolver.actions(context)
    return jsonify({"status": "ok", "context": context.to_dict(), "actions": actions})


@bp.route("/cleanhouse/evidence/actions", methods=["POST"])
def post_evidence_action():
    payload, error = _parse_json_payload()
    if error:
        return error
    data, error = _extract_evidence_request(payload=payload)
    if error:
        return error
    action_id, error = _require_string(payload.get("action_id"), "action_id", required=False, allow_empty=True, max_len=128)
    if error:
        return _error_response("action_id is required")
    if not action_id:
        return _error_response("action_id is required")
    action_origin = _normalize_action_origin(payload.get("action_origin"))
    action_subject = _normalize_subject_payload(payload.get("subject"))
    selection_receipt = _normalize_optional_dict(payload.get("selection_receipt"))
    insight_payload = _normalize_optional_dict(payload.get("insight_payload"))
    scan_payload = _normalize_optional_dict(payload.get("scan_payload"))
    evidence_links = _normalize_string_list(payload.get("evidence_links"))
    create_report = _normalize_boolish(payload.get("create_report"))
    action_request_id, error = _require_string(payload.get("action_request_id"), "action_request_id", required=False, allow_empty=True, max_len=160)
    if error:
        return error
    invoker, error = _require_string(payload.get("invoker"), "invoker", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    role, error = _require_string(payload.get("role"), "role", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    invoker = (invoker or "operator").strip()
    action_request_id = (action_request_id or uuid.uuid4().hex).strip()
    request_fingerprint = hashlib.sha256(json.dumps({
        "mode": data.get("mode"),
        "ref": data.get("ref"),
        "surface": data.get("surface"),
        "entity_id": data.get("entity_id"),
        "source_view": data.get("source_view"),
        "action_id": action_id.strip(),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    with _EVIDENCE_ACTION_REQUESTS_LOCK:
        previous_response = _EVIDENCE_ACTION_REQUESTS.get(action_request_id)
        previous_fingerprint = _EVIDENCE_ACTION_REQUEST_FINGERPRINTS.get(action_request_id)
    if previous_response:
        if previous_fingerprint != request_fingerprint:
            return _error_response("action_request_id was already used for a different action request.")
        return jsonify({**previous_response, "replayed": True})
    try:
        context = _resolve_evidence_context(data)
    except Exception:
        return _error_response("Unable to resolve evidence context for action.")
    selected_action = _find_evidence_action(context, action_id.strip())
    if not selected_action:
        return _error_response(f"Action '{action_id}' is not available for this evidence context.")
    if not selected_action.get("enabled"):
        disabled_reason = selected_action.get("disabled_reason") or "Action is currently disabled."
        return _error_response(disabled_reason)
    role = (role or selected_action.get("required_role") or "viewer").strip() or "viewer"
    adapter = get_cleanhouse_monitoring_adapter()
    resolved_action_origin = action_origin or ""
    audit_entry = get_evidence_context_resolver().audit_entry(
        context,
        action_id=action_id.strip(),
        invoker=invoker,
        role=role,
        action_origin=resolved_action_origin,
        action_subject=action_subject if action_subject else None,
        action_context={
            "source_view": context.source_view,
            "source_surface": context.source_surface,
            "source_entity_id": context.source_entity_id,
            "trace_id": context.trace_id,
        },
        selected_evidence_receipt=selection_receipt,
        report_intent=selected_action.get("intent") or "",
    )
    audit_entry["voice_role"] = selected_action.get("voice_role")
    audit_entry["backend_roles"] = selected_action.get("backend_roles") or []
    audit_entry["capability_source"] = selected_action.get("capability_source") or "evidence_command_center"
    adapter._persist_action_outcome(audit_entry)

    receipt_id = "evidence-action:" + hashlib.sha256(
        f"{action_request_id}|{context.evidence_key}|{action_id}".encode("utf-8")
    ).hexdigest()[:24]
    bounded_refs = list(context.evidence_refs)[:24]
    effect: dict[str, Any] = {"type": selected_action.get("intent") or "action"}
    if action_id == "copy":
        insight_payload = insight_payload if isinstance(insight_payload, dict) else {}
        live_context = insight_payload.get("evidence_context") if isinstance(insight_payload.get("evidence_context"), dict) else {}
        generated_insight = insight_payload.get("insight") if isinstance(insight_payload.get("insight"), dict) else {}
        summary = str(live_context.get("summary") or generated_insight.get("plain_language_summary") or context.summary or "").strip()
        app = str(live_context.get("app") or "").strip()
        source = str(live_context.get("source") or "").strip()
        destination = str(live_context.get("destination") or "").strip()
        protocol = str(live_context.get("protocol") or "").strip()
        event_time = str(live_context.get("event_time") or "").strip()
        detail = " · ".join(value for value in (app, source and destination and f"{source} → {destination}", protocol, event_time) if value)
        copy_refs = _normalize_string_list(live_context.get("evidence_refs")) or bounded_refs
        effect["copy_text"] = "\n".join(filter(None, [
            summary,
            detail,
            f"Source ID: {live_context.get('source_entity_id') or context.source_entity_id}",
            *copy_refs[:24],
        ]))[:12000]
    elif action_id == "export":
        export_payload = {
            "schema": "cleanhouse.evidence_export.v1",
            "receipt_id": receipt_id,
            "evidence_key": context.evidence_key,
            "summary": context.summary,
            "source_surface": context.source_surface,
            "source_view": context.source_view,
            "source_entity_id": context.source_entity_id,
            "evidence_refs": bounded_refs,
            "exported_at": _now_iso(),
        }
        preserved = vvault_preservation.preserve_local_artifact("receipt", receipt_id + "-export", export_payload)
        effect["artifact"] = preserved
    elif action_id in {"mark_read", "mark_unread"}:
        effect["review_state"] = "read" if action_id == "mark_read" else "unread"
    elif action_id == "observe":
        effect["monitoring_state"] = "observing"

    verification = {"status": "pending", "evidence_key": context.evidence_key}
    receipt = {
        "schema": "cleanhouse.evidence_action_receipt.v1",
        "receipt_id": receipt_id,
        "action_request_id": action_request_id,
        "action": action_id,
        "target": {
            "evidence_key": context.evidence_key,
            "source_entity_id": context.source_entity_id,
            "source_surface": context.source_surface,
            "source_view": context.source_view,
        },
        "effect": effect,
        "verification": verification,
        "actor": invoker,
        "backend_boot_id": NETWORK_SERVER_BOOT_ID,
        "timestamp": _now_iso(),
    }
    preservation = vvault_preservation.preserve_local_artifact("receipt", receipt_id, receipt)
    preservation_status = str(preservation.get("status") or "error") if isinstance(preservation, dict) else "error"
    verification.update({
        "status": "verified" if preservation_status == "ok" else "unverified",
        "receipt_id": receipt_id,
        "vvault_status": preservation_status,
    })
    receipt["verification"] = dict(verification)
    if preservation_status == "ok":
        preservation = vvault_preservation.preserve_local_artifact("receipt", receipt_id, receipt)

    report_response = None
    if _should_create_evidence_action_report(
        action_id=action_id,
        action_origin=resolved_action_origin,
        create_report=create_report,
    ):
        report_response = adapter.create_action_report(
            action_id=action_id.strip(),
            action_origin=resolved_action_origin,
            trace_id=context.trace_id,
            action_subject=action_subject,
            action_context={
                "selection": selection_receipt or {},
                "evidence_links_override": evidence_links,
                "selection_view": context.source_view,
            },
            selected_evidence_receipt=selection_receipt,
            evidence_links=evidence_links or list(context.evidence_refs),
            insight_payload=insight_payload,
            scan_payload=scan_payload,
            report_intent=selected_action.get("intent") or "",
        )

    response_body = {
        "status": "ok",
        "context": context.to_dict(),
        "action": selected_action,
        "audit": audit_entry,
        "target": receipt["target"],
        "effect": effect,
        "verification": verification,
        "action_request_id": action_request_id,
        "receipt_id": receipt_id,
        "vvault_receipt": preservation,
        "undo_available": False,
        "preservation": preservation,
        "message": f"{selected_action.get('label') or action_id} completed.",
    }
    if report_response and report_response.get("status") == "ok":
        response_body["report"] = report_response
    with _EVIDENCE_ACTION_REQUESTS_LOCK:
        _EVIDENCE_ACTION_REQUESTS[action_request_id] = dict(response_body)
        _EVIDENCE_ACTION_REQUEST_FINGERPRINTS[action_request_id] = request_fingerprint
        if len(_EVIDENCE_ACTION_REQUESTS) > 1000:
            oldest_request_id = next(iter(_EVIDENCE_ACTION_REQUESTS))
            _EVIDENCE_ACTION_REQUESTS.pop(oldest_request_id)
            _EVIDENCE_ACTION_REQUEST_FINGERPRINTS.pop(oldest_request_id, None)
    return jsonify(response_body)


@bp.route("/cleanhouse/evidence/roles/insight", methods=["POST"])
@bp.route("/cleanhouse/evidence/<path:evidence_key>/roles/insight", methods=["POST"])
def post_evidence_insight(evidence_key: str | None = None):
    payload, error = _parse_json_payload()
    if error:
        return error
    requested_key, error = _require_string(evidence_key or payload.get("evidence_key"), "evidence_key", max_len=512)
    if error:
        return error
    if not requested_key.startswith("network:"):
        return _error_response("Insight currently supports Network evidence only.")
    source_view, error = _require_string(payload.get("source_view"), "source_view", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    invoker, error = _require_string(payload.get("invoker"), "invoker", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    role, error = _require_string(payload.get("role"), "role", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    invoker = (invoker or "operator").strip()
    resolver = get_evidence_context_resolver()
    try:
        context = resolver.resolve_from_evidence_key(requested_key, source_view=source_view)
    except Exception:
        return _error_response("Unable to resolve evidence context for Insight.")
    context = _merge_evidence_context_override(
        context,
        _normalize_optional_dict(payload.get("evidence_context")),
    )
    if context.source_surface != "network":
        return _error_response("Insight currently supports Network evidence only.")
    selected_action = _find_evidence_action(context, "ask_insight")
    if not selected_action:
        return _error_response("Insight action is not available for this evidence context.")
    if not selected_action.get("enabled"):
        return _error_response(selected_action.get("disabled_reason") or "Insight action is currently disabled.")
    role = (role or selected_action.get("required_role") or "Insight").strip() or "Insight"
    result = get_apple_intelligence_insight_service().generate(context)
    audit_entry = _persist_evidence_insight_audit(context, selected_action, result, invoker=invoker, role=role)
    return jsonify({
        "status": "ok",
        "context": context.to_dict(),
        "action": selected_action,
        "audit": audit_entry,
        "insight_status": result.get("insight_status"),
        "apple_intelligence": result.get("apple_intelligence"),
        "insight": result.get("insight"),
    })


@bp.route("/cleanhouse/qpb/cases", methods=["GET"])
def qpb_cases():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    status, error = _require_string(request.args.get("status"), "status", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    return jsonify(adapter.get_qpb_cases(session_id=session_id, status=status or None))


@bp.route("/cleanhouse/qpb/cases", methods=["POST"])
def qpb_create_case():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    target_scope = data.get("target_scope", {})
    if not isinstance(target_scope, dict):
        return _error_response("target_scope must be an object")
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    actor, error = _require_string(data.get("actor"), "actor", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    evidence_refs = data.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        return _error_response("evidence_refs must be a list")
    return jsonify(get_cleanhouse_monitoring_adapter().create_qpb_case({
        "session_id": session_id,
        "target_scope": target_scope,
        "objective_id": objective_id or None,
        "actor": actor or "api",
        "metadata": metadata,
        "evidence_refs": evidence_refs,
        "source": "api",
    }))


@bp.route("/cleanhouse/qpb/cases/<case_id>/<action>", methods=["POST"])
def qpb_transition_case(case_id, action):
    data, error = _parse_json_payload()
    if error:
        return error
    case_id, error = _require_string(case_id, "case_id", max_len=256)
    if error:
        return error
    action, error = _require_string(action, "action", max_len=64)
    if error:
        return error
    actor, error = _require_string(data.get("actor"), "actor", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    payload = {
        "actor": actor or "api",
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        "evidence_refs": data.get("evidence_refs", []) if isinstance(data.get("evidence_refs"), list) else [],
        "confirm": bool(data.get("confirm", False)),
    }
    if "repo_path" in data and data.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
        if repo_error:
            return repo_error
        payload["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().advance_qpb_case(case_id, action, payload))


@bp.route("/cleanhouse/incident-receipt", methods=["GET"])
def standalone_incident_receipt_get():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    case_id, error = _require_string(request.args.get("case_id"), "case_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    return jsonify(adapter.get_standalone_incident_receipt(
        session_id=session_id or None,
        case_id=case_id or None,
    ))


@bp.route("/cleanhouse/incident-receipt", methods=["POST"])
def standalone_incident_receipt_create():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    payload: dict[str, Any] = {"session_id": session_id}
    signal_source, error = _require_string(data.get("signal_source"), "signal_source", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    if signal_source:
        payload["signal_source"] = signal_source
    signal_process, error = _require_string(data.get("signal_process"), "signal_process", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    if signal_process:
        payload["signal_process"] = signal_process
    suspicion_reason, error = _require_string(data.get("suspicion_reason"), "suspicion_reason", required=False, allow_empty=True, max_len=1024)
    if error:
        return error
    if suspicion_reason:
        payload["suspicion_reason"] = suspicion_reason
    target_path, error = _require_string(data.get("target_path"), "target_path", required=False, allow_empty=True, max_len=2048)
    if error:
        return error
    if target_path:
        payload["target_path"] = target_path
    incident_id, error = _require_string(data.get("incident_id"), "incident_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    if incident_id:
        payload["incident_id"] = incident_id
    if data.get("signal_pid") not in {None, ""}:
        payload["signal_pid"] = data.get("signal_pid")
    if "force_new" in data:
        payload["force_new"] = data.get("force_new")
    if "allow_synthetic" in data:
        payload["allow_synthetic"] = bool(data.get("allow_synthetic"))
    if "repo_path" in data and data.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
        if repo_error:
            return repo_error
        payload["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().create_standalone_incident_receipt(payload))


@bp.route("/cleanhouse/incident-receipt/<case_id>/<action>", methods=["POST"])
def standalone_incident_receipt_action(case_id, action):
    data, error = _parse_json_payload()
    if error:
        return error
    case_id, error = _require_string(case_id, "case_id", max_len=256)
    if error:
        return error
    action, error = _require_string(action, "action", max_len=64)
    if error:
        return error
    actor, error = _require_string(data.get("actor"), "actor", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    payload = {
        "actor": actor or "incident_receipt",
        "metadata": data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        "evidence_refs": data.get("evidence_refs", []) if isinstance(data.get("evidence_refs"), list) else [],
        "confirm": bool(data.get("confirm", False)),
    }
    if "repo_path" in data and data.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
        if repo_error:
            return repo_error
        payload["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().advance_standalone_incident_receipt(case_id, action, payload))


@bp.route("/cleanhouse/mediator/proposals", methods=["GET"])
def mediator_get_proposals():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    proposal_type, error = _require_string(request.args.get("proposal_type"), "proposal_type", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    status, error = _require_string(request.args.get("status"), "status", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    return jsonify(adapter.get_operation_proposals(
        session_id=session_id,
        proposal_type=proposal_type or None,
        status=status or None,
    ))


@bp.route("/cleanhouse/mediator/proposals", methods=["POST"])
def mediator_create_proposal():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    proposal_type, error = _require_string(data.get("proposal_type"), "proposal_type", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    reason, error = _require_string(data.get("reason"), "reason", required=False, allow_empty=True, max_len=2048)
    if error:
        return error
    operations = data.get("operations", [])
    if not isinstance(operations, list):
        return _error_response("operations must be a list")
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return _error_response("metadata must be an object")
    if "repo_path" in metadata and metadata.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(metadata.get("repo_path"))
        if repo_error:
            return repo_error
        metadata["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().create_operation_proposal({
        "session_id": session_id,
        "proposal_type": proposal_type or "mediator",
        "reason": reason or "",
        "objective_id": objective_id or None,
        "operations": operations,
        "target_scope": data.get("target_scope", {}) if isinstance(data.get("target_scope"), dict) else {},
        "metadata": metadata,
        "evidence_refs": data.get("evidence_refs", []) if isinstance(data.get("evidence_refs"), list) else [],
    }))


@bp.route("/cleanhouse/mediator/proposals/<proposal_id>/<decision>", methods=["POST"])
def mediator_resolve_proposal(proposal_id, decision):
    data, error = _parse_json_payload()
    if error:
        return error
    proposal_id, error = _require_string(proposal_id, "proposal_id", max_len=256)
    if error:
        return error
    decision, error = _require_string(decision, "decision", max_len=64)
    if error:
        return error
    payload = {"confirm": bool(data.get("confirm", False))}
    if "repo_path" in data and data.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
        if repo_error:
            return repo_error
        payload["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().resolve_operation_proposal(proposal_id, decision, payload))


@bp.route("/cleanhouse/mediator/proposals/<proposal_id>/undo", methods=["POST"])
def mediator_undo_proposal(proposal_id):
    data, error = _parse_json_payload()
    if error:
        return error
    proposal_id, error = _require_string(proposal_id, "proposal_id", max_len=256)
    if error:
        return error
    payload: dict[str, Any] = {}
    if "repo_path" in data and data.get("repo_path") not in {None, ""}:
        repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
        if repo_error:
            return repo_error
        payload["repo_path"] = str(repo_path)
    return jsonify(get_cleanhouse_monitoring_adapter().undo_operation_proposal(proposal_id, payload))


@bp.route("/cleanhouse/auto-sort/proposal", methods=["POST"])
def auto_sort_proposal():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
    if repo_error:
        return repo_error
    target_dir, error = _require_string(data.get("target_dir"), "target_dir", required=False, allow_empty=True, max_len=2048)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().create_auto_sort_proposal({
        "session_id": session_id,
        "repo_path": str(repo_path),
        "target_dir": target_dir or ".",
        "objective_id": objective_id or None,
    }))


@bp.route("/cleanhouse/cleaner/proposal", methods=["POST"])
def cleaner_proposal():
    data, error = _parse_json_payload()
    if error:
        return error
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    repo_path, repo_error = _validate_repo_path(data.get("repo_path"))
    if repo_error:
        return repo_error
    target_dir, error = _require_string(data.get("target_dir"), "target_dir", required=False, allow_empty=True, max_len=2048)
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    return jsonify(get_cleanhouse_monitoring_adapter().create_cleaner_proposal({
        "session_id": session_id,
        "repo_path": str(repo_path),
        "target_dir": target_dir or ".",
        "objective_id": objective_id or None,
    }))


@bp.route("/cleanhouse/report", methods=["POST"])
def build_report():
    data, error = _parse_json_payload()
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(data.get("session_id"))
    if error:
        return error
    report_type, error = _require_string(data.get("report_type"), "report_type", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    contact, error = _require_string(data.get("contact"), "contact", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    target, error = _require_string(data.get("target"), "target", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    context, error = _require_string(data.get("context"), "context", required=False, allow_empty=True, max_len=4096)
    if error:
        return error

    return jsonify(adapter.build_report(
        session_id=session_id,
        report_type=report_type or "incident",
        contact=contact or "",
        target=target or "",
        context=context or "",
    ))


@bp.route("/cleanhouse/login-report", methods=["POST"])
def build_login_report():
    data, error = _parse_json_payload()
    if error:
        return error
    user_id, error = _require_string(data.get("user_id"), "user_id", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    email, error = _require_string(data.get("email"), "email", required=False, allow_empty=True, max_len=256)
    if error:
        return error
    if not (user_id or email):
        return _error_response("user_id or email is required")
    previous_login_at, error = _require_string(data.get("previous_login_at"), "previous_login_at", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    current_login_at, error = _require_string(data.get("current_login_at"), "current_login_at", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    trigger, error = _require_string(data.get("trigger"), "trigger", required=False, allow_empty=True, max_len=128)
    if error:
        return error
    payload = get_cleanhouse_monitoring_adapter().submit_login_report(
        user_id=user_id or "",
        email=email or "",
        previous_login_at=previous_login_at or None,
        current_login_at=current_login_at or None,
        trigger=trigger or "api/login-report",
        wait_timeout_seconds=LOGIN_REPORT_WAIT_SECONDS,
    )
    response = jsonify(payload)
    status = _login_report_http_status(payload)
    if status == 429 and hasattr(response, "headers"):
        response.headers["Retry-After"] = "2"
    return response, status


@bp.route("/cleanhouse/login-report/<job_id>", methods=["GET"])
def poll_login_report(job_id):
    job_id, error = _require_string(job_id, "job_id", max_len=256)
    if error:
        return error
    payload = get_cleanhouse_monitoring_adapter().poll_login_report(job_id)
    status = 404 if payload.get("status") == "not_found" else _login_report_http_status(payload)
    response = jsonify(payload)
    if status == 429 and hasattr(response, "headers"):
        response.headers["Retry-After"] = "2"
    return response, status


@bp.route("/cleanhouse/reports", methods=["GET"])
def get_reports():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    report_type, error = _require_string(request.args.get("report_type"), "report_type", required=False, allow_empty=True, max_len=64)
    if error:
        return error
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_REPORT_MAX_LIMIT)
    if error:
        return error
    return jsonify(adapter.get_reports(
        session_id=session_id,
        report_type=report_type or None,
        limit=limit or LOW_PROCESSING_REPORT_LIMIT,
        summary_only=not _truthy_arg("full") or _truthy_arg("summary_only"),
    ))


@bp.route("/cleanhouse/reports/<path:report_id>", methods=["GET"])
def get_report(report_id):
    report_id, error = _require_string(report_id, "report_id", max_len=256)
    if error:
        return error
    if "/" in report_id or "\\" in report_id:
        return _error_response("report_id format is invalid")
    payload = get_cleanhouse_monitoring_adapter().get_report(report_id)
    status = 404 if payload.get("status") == "not_found" else 200
    return jsonify(payload), status


@bp.route("/cleanhouse/settings", methods=["GET"])
def get_settings():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_settings())


@bp.route("/cleanhouse/settings", methods=["POST"])
def update_settings():
    data, error = _parse_json_payload()
    if error:
        return error
    payload, error = _require_dict(data, "settings")
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.update_settings(payload))


@bp.route("/cleanhouse/plugins", methods=["GET"])
def get_plugins():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_plugins())


@bp.route("/cleanhouse/plugins", methods=["POST"])
def register_plugin():
    data, error = _parse_json_payload()
    if error:
        return error
    payload, error = _require_dict(data, "plugin")
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.register_plugin(payload))


@bp.route("/cleanhouse/plugins/<plugin_id>", methods=["POST"])
def update_plugin(plugin_id):
    data, error = _parse_json_payload()
    if error:
        return error
    payload, error = _require_dict(data, "plugin")
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.update_plugin(plugin_id, payload))


@bp.route("/cleanhouse/tool-event", methods=["POST"])
def tool_event():
    data, error = _parse_json_payload()
    if error:
        return error
    payload_data = data.get("event") if "event" in data else data
    payload, error = _require_dict(payload_data, "event")
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.submit_tool_event(payload))


@bp.route("/cleanhouse/persist/prune", methods=["POST"])
def prune_artifacts():
    data, error = _parse_json_payload()
    if error:
        return error
    payload, error = _require_dict(data, "payload")
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.prune_all_artifacts(payload))


@bp.route("/cleanhouse/retention-events", methods=["GET"])
def list_retention_events():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_retention_events())


FILES_MEDIATION_SOURCE = "files_mediation"
FILES_RECONCILIATION_SOURCE = "files_reconciliation"
FILES_WATCHER_SOURCE = "filesystem_watcher"
FILES_WAZUH_SOURCE = "wazuh_fim"
FILES_ATTENTION_SOURCE = "files_attention"
FILES_MEDIATION_STATES = {"queue", "in_progress", "ready", "completed", "cancelled"}
FILES_MEDIATION_TRANSITIONS = {
    "queue": {"in_progress", "cancelled"},
    "in_progress": {"ready", "cancelled"},
    "ready": {"completed", "in_progress", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _files_event_path(row: dict[str, Any]) -> str:
    return str(row.get("path") or "").strip()


def _files_event_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("timestamp") or "").strip()


def _files_event_data(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("data")
    return value if isinstance(value, dict) else {}


def _files_presentable_event(row: dict[str, Any]) -> bool:
    path = Path(_files_event_path(row))
    parts = set(path.parts)
    if parts.intersection({".git", "__pycache__", "node_modules", "cleanhouse_env"}):
        return False
    if path.suffix.lower() in {".pyc", ".pyo", ".swp", ".tmp"} or path.name == ".DS_Store":
        return False
    path_text = str(path)
    if "/bundled/wireshark/" in path_text and "/Resources/share/" in path_text:
        return False
    return True


def _files_event_epoch(row: dict[str, Any]) -> float | None:
    value = _files_event_timestamp(row)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _files_correlated(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Prefer Wazuh in the UI while retaining both provider rows durably."""
    projected: list[dict[str, Any]] = []
    for original in rows:
        if not _files_presentable_event(original):
            continue
        row = dict(original)
        path = _files_event_path(row)
        event_type = str(row.get("event_type") or "")
        timestamp = _files_event_epoch(row)
        provider = str(row.get("provider") or row.get("source_surface") or "")
        match_index = None
        for index, existing in enumerate(projected):
            if _files_event_path(existing) != path or str(existing.get("event_type") or "") != event_type:
                continue
            existing_provider = str(existing.get("provider") or existing.get("source_surface") or "")
            if existing_provider == provider:
                continue
            existing_timestamp = _files_event_epoch(existing)
            if timestamp is None or existing_timestamp is None or abs(timestamp - existing_timestamp) > 5:
                continue
            match_index = index
            break
        if match_index is not None:
            existing = projected[match_index]
            existing_provider = str(existing.get("provider") or existing.get("source_surface") or "")
            if provider == "wazuh" and existing_provider != "wazuh":
                row["correlated_providers"] = sorted({provider, existing_provider})
                projected[match_index] = row
            else:
                existing["correlated_providers"] = sorted({provider, existing_provider})
            continue
        row["correlated_providers"] = [provider] if provider else []
        projected.append(row)
        if len(projected) >= limit:
            break
    return projected


def _files_findings(rows: list[dict[str, Any]], reconciliation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    path_counts: dict[str, int] = {}
    latest_by_path: dict[str, dict[str, Any]] = {}
    protected_names = {".env", "package-lock.json", "requirements.txt", "runtime_supervisor.py", "auth.py"}

    for row in rows:
        path = _files_event_path(row)
        if not path:
            continue
        path_counts[path] = path_counts.get(path, 0) + 1
        latest_by_path.setdefault(path, row)
        event_type = str(row.get("event_type") or "observed").lower()
        name = Path(path).name
        category = ""
        severity = "notice"
        title = ""
        reason = ""
        suggestion = ""
        if event_type == "deleted":
            category, severity = "deletion", "review"
            title = f"Deleted file: {name}"
            reason = "A watched file disappeared and its lineage should be confirmed."
            suggestion = f"Review the deletion of {name} and restore it if it was unintended."
        elif name in protected_names or name.endswith((".lock", ".pem", ".key")):
            category, severity = "protected-change", "review"
            title = f"Protected file changed: {name}"
            reason = "A dependency, credential, or runtime control file changed."
            suggestion = f"Verify the latest {name} change against its intended source."
        if category:
            key = (category, path)
            groups[key] = {
                "id": f"{category}:{path}",
                "category": category,
                "title": title,
                "reason": reason,
                "context": path,
                "severity": severity,
                "confidence": "high",
                "event_count": path_counts[path],
                "latest_at": _files_event_timestamp(row),
                "paths": [path],
                "evidence_refs": list(row.get("evidence_refs") or []),
                "suggestion": suggestion,
            }

    for path, count in path_counts.items():
        if count < 5:
            continue
        row = latest_by_path[path]
        groups[("rapid-churn", path)] = {
            "id": f"rapid-churn:{path}",
            "category": "rapid-churn",
            "title": f"Repeated edits: {Path(path).name}",
            "reason": f"CleanHouse observed {count} recent changes to the same file.",
            "context": path,
            "severity": "notice",
            "confidence": "medium",
            "event_count": count,
            "latest_at": _files_event_timestamp(row),
            "paths": [path],
            "evidence_refs": list(row.get("evidence_refs") or []),
            "suggestion": f"Review the recent edit sequence for {Path(path).name}.",
        }

    if reconciliation_rows:
        latest = reconciliation_rows[0]
        data = _files_event_data(latest)
        discrepancies = list(data.get("discrepancies") or [])
        if discrepancies:
            groups[("reconciliation", "latest")] = {
                "id": "reconciliation:latest",
                "category": "reconciliation",
                "title": "Reconciliation found unresolved lineage",
                "reason": f"{len(discrepancies)} known path{'s' if len(discrepancies) != 1 else ''} could not be verified.",
                "context": "Known lineage index",
                "severity": "review",
                "confidence": "high",
                "event_count": len(discrepancies),
                "latest_at": _files_event_timestamp(latest),
                "paths": discrepancies[:20],
                "evidence_refs": discrepancies[:20],
                "suggestion": "Review unresolved paths from the latest reconciliation.",
            }

    severity_rank = {"critical": 3, "review": 2, "notice": 1}
    return sorted(
        groups.values(),
        key=lambda item: (severity_rank.get(item["severity"], 0), item.get("latest_at", "")),
        reverse=True,
    )[:20]


def _files_locations(rows: list[dict[str, Any]], findings: list[dict[str, Any]], watcher: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    unresolved_by_location: dict[str, int] = {}
    for finding in findings:
        for path in finding.get("paths", []):
            parent = str(Path(path).parent)
            unresolved_by_location[parent] = unresolved_by_location.get(parent, 0) + 1
    for row in rows:
        data = _files_event_data(row)
        location = str(data.get("watch_dir") or Path(_files_event_path(row)).parent or "Unavailable")
        current = grouped.setdefault(location, {
            "location": location,
            "event_count": 0,
            "latest_at": "",
            "sources": set(),
            "status": "watched" if location == watcher.get("watch_dir") else "observed",
        })
        current["event_count"] += 1
        current["latest_at"] = max(current["latest_at"], _files_event_timestamp(row))
        current["sources"].add(str(row.get("source_surface") or FILES_WATCHER_SOURCE))
    if watcher.get("watch_dir") and watcher["watch_dir"] not in grouped:
        grouped[watcher["watch_dir"]] = {
            "location": watcher["watch_dir"],
            "event_count": 0,
            "latest_at": "",
            "sources": {FILES_WATCHER_SOURCE},
            "status": "watched" if watcher.get("status") == "running" else "degraded",
        }
    result = []
    for location, item in grouped.items():
        item["sources"] = sorted(item["sources"])
        item["unresolved_findings"] = sum(
            count for path, count in unresolved_by_location.items() if path.startswith(location)
        )
        result.append(item)
    return sorted(result, key=lambda item: (item["latest_at"], item["event_count"]), reverse=True)


def _fold_file_mediations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = _files_event_data(row)
        mediation_id = str(data.get("mediation_id") or "").strip()
        if not mediation_id or mediation_id in folded:
            continue
        status = str(data.get("status") or "queue")
        folded[mediation_id] = {
            "id": mediation_id,
            "status": status if status in FILES_MEDIATION_STATES else "queue",
            "request": str(data.get("request") or row.get("summary") or "File mediation"),
            "scope": str(data.get("scope") or "all"),
            "evidence_names": list(data.get("evidence_names") or []),
            "created_at": str(data.get("created_at") or row.get("timestamp") or ""),
            "updated_at": str(row.get("timestamp") or ""),
            "execution_state": str(data.get("execution_state") or "unavailable_until_zaelith"),
            "transition_receipt": data.get("transition_receipt") if isinstance(data.get("transition_receipt"), dict) else {},
        }
    return sorted(folded.values(), key=lambda item: item["updated_at"], reverse=True)


def _acknowledged_files_attention(rows: list[dict[str, Any]]) -> set[str]:
    acknowledged: set[str] = set()
    for row in rows:
        data = _files_event_data(row)
        for item in data.get("attention_ids") or []:
            if str(item):
                acknowledged.add(str(item))
    return acknowledged


def _files_snapshot(limit: int = 200) -> dict[str, Any]:
    source_rows = events.list_events_by_sources({
        FILES_WATCHER_SOURCE: min(max(500, limit * 4), 1000),
        FILES_WAZUH_SOURCE: min(max(500, limit * 4), 1000),
        FILES_MEDIATION_SOURCE: 300,
        FILES_RECONCILIATION_SOURCE: 20,
        FILES_ATTENTION_SOURCE: 300,
    })
    candidate_rows = sorted(
        [*source_rows.get(FILES_WAZUH_SOURCE, []), *source_rows.get(FILES_WATCHER_SOURCE, [])],
        key=lambda row: int(row.get("id") or 0),
        reverse=True,
    )
    file_rows = _files_correlated(candidate_rows, limit=min(max(1, limit), 500))
    mediation_rows = source_rows.get(FILES_MEDIATION_SOURCE, [])
    reconciliation_rows = source_rows.get(FILES_RECONCILIATION_SOURCE, [])
    attention_rows = source_rows.get(FILES_ATTENTION_SOURCE, [])
    watcher = events.get_watcher_status()
    wazuh = wazuh_files.status()
    preservation = vvault_sync.status(surface="files")
    findings = _files_findings(file_rows, reconciliation_rows)
    locations = _files_locations(file_rows, findings, watcher)
    mediations = _fold_file_mediations(mediation_rows)
    suggestions = [
        {
            "id": finding["id"],
            "request": finding["suggestion"],
            "severity": finding["severity"],
            "finding_id": finding["id"],
        }
        for finding in findings
        if finding.get("suggestion")
    ][:8]
    acknowledged_attention = _acknowledged_files_attention(attention_rows)
    attention_items = [
        {
            "id": f"suggestion:{suggestion['id']}",
            "kind": "suggestion",
            "reference_id": suggestion["id"],
        }
        for suggestion in suggestions
    ]
    attention_items.extend(
        {
            "id": f"mediation:{item['id']}:{item['status']}",
            "kind": "ready_review" if item["status"] == "ready" else "mediation_failure",
            "reference_id": item["id"],
        }
        for item in mediations
        if item["status"] == "ready" or item.get("transition_state") in {"conflict", "failed"}
    )
    for item in attention_items:
        item["acknowledged"] = item["id"] in acknowledged_attention
    for suggestion in suggestions:
        suggestion["acknowledged"] = f"suggestion:{suggestion['id']}" in acknowledged_attention
    latest_reconciliation = reconciliation_rows[0] if reconciliation_rows else None
    reconciliation_data = _files_event_data(latest_reconciliation or {})
    attention_count = sum(1 for item in attention_items if not item["acknowledged"])
    cursor = max(
        [int(row.get("id") or 0) for row in file_rows + mediation_rows + reconciliation_rows + attention_rows] or [0]
    )
    integrity_projection = file_integrity.snapshot()
    projection_state = str(integrity_projection.get("state") or "no_data")
    integrity = {
        **integrity_projection,
        "state": "degraded" if projection_state == "degraded" else ("review" if findings else projection_state),
        "drift_state": str((integrity_projection.get("last_reconciliation") or {}).get("state") or "not_reconciled"),
        "gap_state": "collector_interrupted" if wazuh.get("last_error") else "none_observed",
        "mutation_count": len(file_rows),
        "finding_count": len(findings),
        "evidence_ref_count": sum(len(row.get("evidence_refs") or []) for row in file_rows),
        "last_reconciled_at": _files_event_timestamp(latest_reconciliation or {}),
        "reconciliation": reconciliation_data,
    }
    powered_by_wazuh = bool(wazuh.get("powered_by_wazuh"))
    wazuh_runtime_status = wazuh.get("runtime") if isinstance(wazuh.get("runtime"), dict) else {}
    wazuh_bundle = (
        wazuh_runtime_status.get("bundle")
        if isinstance(wazuh_runtime_status.get("bundle"), dict)
        else {}
    )
    wazuh_signature = (
        wazuh_bundle.get("signature")
        if isinstance(wazuh_bundle.get("signature"), dict)
        else {}
    )
    current_wazuh_live = bool(wazuh.get("operational")) and wazuh.get("health") in {"live", "no_data"}
    fallback_active = not current_wazuh_live and watcher.get("status") == "running"
    watcher_error = watcher.get("last_error") if isinstance(watcher.get("last_error"), dict) else {}
    if fallback_active:
        fallback_reason = "wazuh_not_authenticated"
    elif watcher.get("collector_status") == "error":
        fallback_reason = str(watcher_error.get("source") or "watchdog_error")
    elif watcher.get("status") == "unavailable":
        fallback_reason = str(watcher.get("unsupported_reason") or "watchdog_unavailable")
    else:
        fallback_reason = "watchdog_inactive"
    if powered_by_wazuh and wazuh.get("health") == "live":
        files_state = "live"
    elif fallback_active:
        files_state = "fallback"
    elif wazuh.get("authenticated") and wazuh.get("health") == "no_data":
        files_state = "no_data"
    elif wazuh.get("health") == "warming":
        files_state = "warming"
    elif wazuh.get("configured"):
        files_state = "degraded"
    else:
        files_state = "unavailable"
    collector = {
        "provider": "wazuh" if current_wazuh_live else ("watchdog" if fallback_active else "none"),
        "lifecycle": wazuh.get("lifecycle", "unavailable"),
        "health": files_state,
        "connection_health": str(wazuh.get("health") or files_state),
        "operational": bool(wazuh.get("operational")),
        "evidence_authenticated": bool(wazuh.get("authenticated")),
        "evidence_authentication": "authenticated" if wazuh.get("authenticated") else "unavailable",
        "powered_by_wazuh": powered_by_wazuh,
        "package_version": wazuh_bundle.get("version"),
        "package_status": wazuh_bundle.get("status") or "unavailable",
        "package_verified": bool(wazuh_bundle.get("packaged")),
        "package_checksum_verified": bool(wazuh_bundle.get("checksum_verified")),
        "package_signature_verified": bool(wazuh_signature.get("verified")),
        "agent_version": (wazuh.get("runtime") or {}).get("installed_version") or None,
        "agent_id": wazuh.get("agent_id") or None,
        "manager": wazuh.get("manager") or None,
        "last_event_at": wazuh.get("last_event_at") or (_files_event_timestamp(file_rows[0]) if file_rows else None),
        "ingestion_latency_ms": wazuh.get("ingestion_latency_ms"),
        "cursor": wazuh.get("cursor") or "",
        "stream_identity": wazuh.get("stream_identity") or "",
        "stream_generation": wazuh.get("stream_generation") or "",
        "gap_state": wazuh.get("gap_state") or "unknown",
        "manager_version": wazuh.get("manager_version") or None,
        "historical_wazuh_proof": bool(wazuh.get("historical_wazuh_proof")),
        "monitored_scope": wazuh.get("monitored_scope") or watcher.get("watch_dir"),
        "fallback": {
            "active": fallback_active,
            "provider": "watchdog",
            "status": watcher.get("status") or "unknown",
            "reason": fallback_reason,
            "last_error": watcher_error,
        },
        "fallback_reason": fallback_reason,
        "last_error": wazuh.get("last_error") or "",
    }
    return {
        "status": "ok" if files_state in {"live", "fallback", "no_data"} else files_state,
        "schema": "cleanhouse.files.v2",
        "cursor": cursor,
        "collector": collector,
        "powered_by_wazuh": powered_by_wazuh,
        "monitoring": {
            "always_on": bool(current_wazuh_live or fallback_active),
            "status": files_state,
            "legacy_status": watcher.get("status") or "unknown",
            "watch_dir": collector["monitored_scope"],
            "last_event_at": collector["last_event_at"],
            "provider": collector["provider"],
            "fallback": collector["fallback"],
        },
        "events": file_rows,
        "findings": findings,
        "integrity": integrity,
        "locations": locations,
        "mediations": mediations,
        "suggestions": suggestions,
        "attention_count": min(attention_count, 100),
        "attention": attention_items,
        "reconciliation": reconciliation_data,
        "preservation": preservation,
    }


def _files_sse_event(event: str, payload: dict[str, Any], *, event_id: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), default=str)
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


@bp.route("/cleanhouse/files/attention/acknowledge", methods=["POST"])
def acknowledge_files_attention():
    guard = _require_privileged_files_request("files-attention-acknowledge")
    if guard is not None:
        return guard
    payload, error = _parse_json_payload()
    if error:
        return error
    snapshot = _files_snapshot(200)
    available = {str(item.get("id")) for item in snapshot.get("attention", []) if item.get("id")}
    requested = payload.get("attention_ids") or []
    if payload.get("all") is True:
        attention_ids = sorted(available)
    elif isinstance(requested, list):
        attention_ids = sorted({str(item) for item in requested if str(item) in available})
    else:
        return _error_response("attention_ids must be an array")
    if not attention_ids:
        return _error_response("no current attention items matched")
    acknowledged_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt_core = {"attention_ids": attention_ids, "acknowledged_at": acknowledged_at}
    receipt_id = "files-attention:" + hashlib.sha256(
        json.dumps(receipt_core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    receipt = {
        "id": receipt_id,
        **receipt_core,
        "execution_state": "acknowledgement_only",
    }
    events.insert_event(
        event_type="file_attention_acknowledged",
        path="/files/attention",
        summary=f"Acknowledged {len(attention_ids)} Files attention item(s)",
        source_surface=FILES_ATTENTION_SOURCE,
        provider="cleanhouse",
        actor_type="operator",
        evidence_level="declared",
        collector_status="ok",
        evidence_refs=attention_ids,
        source_event_key=receipt_id,
        data={"attention_ids": attention_ids, "transition_receipt": receipt},
    )
    vvault_sync.enqueue(receipt_id, {"event_type": "file_attention_acknowledged", **receipt})
    return jsonify({"status": "ok", "receipt": receipt, "snapshot": _files_snapshot(200)})


@bp.route("/cleanhouse/files/snapshot", methods=["GET"])
def get_files_snapshot():
    guard = _require_files_read_request()
    if guard is not None:
        return guard
    limit, error = _optional_positive_int_arg("limit", max_value=500)
    if error:
        return error
    return jsonify(_files_snapshot(limit or 200))


@bp.route("/cleanhouse/files/live", methods=["GET"])
def stream_files_live():
    guard = _require_files_read_request()
    if guard is not None:
        return guard
    raw_after = request.args.get("after") or request.headers.get("Last-Event-ID") or "0"
    try:
        initial_cursor = max(0, int(raw_after))
    except (TypeError, ValueError):
        initial_cursor = 0

    @stream_with_context
    def generate():
        last_cursor = initial_cursor
        last_attention = -1
        last_state_signature = ""
        last_keepalive = time.monotonic()
        while True:
            snapshot = _files_snapshot(200)
            cursor = int(snapshot.get("cursor") or 0)
            attention = int(snapshot.get("attention_count") or 0)
            state_signature = hashlib.sha256(json.dumps({
                "collector": snapshot.get("collector"),
                "integrity": snapshot.get("integrity"),
                "preservation": snapshot.get("preservation"),
            }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            if cursor != last_cursor or attention != last_attention or state_signature != last_state_signature:
                yield _files_sse_event("files-snapshot", snapshot, event_id=str(cursor))
                last_cursor = cursor
                last_attention = attention
                last_state_signature = state_signature
                last_keepalive = time.monotonic()
            elif time.monotonic() - last_keepalive >= 15:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()
            time.sleep(0.5)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@bp.route("/cleanhouse/files/wazuh/status", methods=["GET"])
def get_files_wazuh_status():
    guard = _require_files_read_request()
    if guard is not None:
        return guard
    return jsonify(wazuh_files.status())


@bp.route("/cleanhouse/files/wazuh/setup", methods=["POST"])
def setup_files_wazuh():
    guard = _require_privileged_files_request("wazuh-setup")
    if guard is not None:
        return guard
    payload, error = _parse_json_payload()
    if error:
        return error
    manager, error = _require_string(payload.get("manager"), "manager", max_len=253)
    if error:
        return error
    agent_name, error = _require_string(
        payload.get("agent_name") or "CleanHouse",
        "agent_name",
        max_len=128,
    )
    if error:
        return error
    monitored_scope, error = _require_string(
        payload.get("monitored_scope") or str(events.DEFAULT_WATCH_DIR),
        "monitored_scope",
        max_len=4096,
    )
    if error:
        return error
    bundle = wazuh_runtime.verify_bundle()
    if not bundle.get("packaged"):
        return {
            "status": "error",
            "message": "The pinned Wazuh agent and source bundle have not passed package verification.",
            "bundle": bundle,
        }, 503
    try:
        enrollment = wazuh_files.enroll_agent(
            manager=manager,
            agent_name=agent_name,
            monitored_scope=monitored_scope,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": "Authenticated VVAULT Wazuh enrollment failed.",
            "reason": str(exc)[:512],
        }, 503
    keychain = wazuh_runtime.store_enrollment_key(enrollment["client_key"])
    if not keychain.get("stored"):
        return {"status": "error", "message": "Could not store the Wazuh client key in Keychain"}, 503
    result = wazuh_runtime.install_with_authorization(
        manager=manager,
        agent_name=agent_name,
        agent_id=enrollment["agent_id"],
        monitored_scope=monitored_scope,
    )
    result["enrollment"] = {
        key: value for key, value in enrollment.items() if key != "client_key"
    }
    status_code = 200 if result.get("status") == "ok" else 503
    return jsonify(result), status_code


@bp.route("/cleanhouse/files/reconcile", methods=["POST"])
def reconcile_files():
    collector = wazuh_files.status()
    provider = "wazuh"
    strategy = "wazuh_fim_inventory"
    partial = False
    try:
        inventory = wazuh_files.inventory()
    except Exception as exc:
        provider = "watchdog"
        strategy = "known_watcher_paths_partial"
        partial = True
        watcher = events.get_watcher_status()
        scope = Path(str(watcher.get("watch_dir") or events.DEFAULT_WATCH_DIR)).expanduser().resolve()
        known_rows = [
            row for row in events.list_events_by_sources({FILES_WATCHER_SOURCE: 1000}).get(FILES_WATCHER_SOURCE, [])
            if _files_presentable_event(row)
        ][:500]
        known_paths = list(dict.fromkeys(_files_event_path(row) for row in known_rows if _files_event_path(row)))[:250]
        inventory = []
        unavailable: list[str] = []
        for raw_path in known_paths:
            try:
                path = Path(raw_path).expanduser().resolve(strict=True)
                if not path.is_file() or (path != scope and scope not in path.parents):
                    continue
                stat = path.stat()
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                inventory.append({
                    "path": str(path),
                    "provider": "watchdog",
                    "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "hashes": {"sha256": digest.hexdigest()},
                    "metadata": {
                        "size": stat.st_size,
                        "mode": oct(stat.st_mode & 0o7777),
                        "uid": stat.st_uid,
                        "gid": stat.st_gid,
                        "mtime": stat.st_mtime_ns,
                        "inode": stat.st_ino,
                        "file_type": "file",
                    },
                    "evidence_refs": [f"watchdog-path://{path}"],
                })
            except (OSError, RuntimeError):
                unavailable.append(raw_path)
        if unavailable:
            collector = {**collector, "fallback_inventory_error": str(exc)[:512], "unavailable_paths": unavailable[:50]}
    data = file_integrity.reconcile(inventory, provider=provider)
    data.update({"strategy": strategy, "partial": partial, "collector": collector.get("health")})
    events.insert_event(
        event_type="file_reconciliation",
        path=str(collector.get("monitored_scope") or events.DEFAULT_WATCH_DIR),
        summary=f"Reconciled {data['checked']} file integrity entries via {provider}",
        source_surface=FILES_RECONCILIATION_SOURCE,
        provider=provider,
        actor_type="operator",
        evidence_level="authenticated" if provider == "wazuh" else "observed_partial",
        collector_status="ok" if not partial else "fallback",
        evidence_refs=[data["receipt_id"], *data.get("discrepancies", [])[:20]],
        source_event_key=f"files-reconciliation:{data['receipt_id']}",
        data=data,
    )
    vvault_sync.enqueue(data["receipt_id"], {"event_type": "file_reconciliation", **data})
    snapshot = _files_snapshot(200)
    snapshot["reconciliation_receipt"] = data
    return jsonify(snapshot)


@bp.route("/cleanhouse/files/baseline/rebuild", methods=["POST"])
def rebuild_files_baseline():
    guard = _require_privileged_files_request("baseline-rebuild")
    if guard is not None:
        return guard
    try:
        inventory = wazuh_files.inventory()
    except Exception as exc:
        return {
            "status": "degraded",
            "message": "A full baseline rebuild requires the authenticated Wazuh FIM inventory.",
            "reason": str(exc)[:512],
        }, 503
    generation = file_integrity.rebuild(
        inventory,
        provider="wazuh",
        reason="handler_requested_full_rebuild",
        evidence_refs=["wazuh-fim-inventory"],
    )
    receipt_id = f"files-baseline:{generation['chain_hash']}"
    events.insert_event(
        event_type="file_baseline_rebuilt",
        path=str(wazuh_files.status().get("monitored_scope") or events.DEFAULT_WATCH_DIR),
        summary=f"Rebuilt Files baseline generation {generation['generation']}",
        source_surface=FILES_RECONCILIATION_SOURCE,
        provider="wazuh",
        actor_type="operator",
        evidence_level="authenticated",
        collector_status="ok",
        evidence_refs=[receipt_id],
        source_event_key=receipt_id,
        data={"baseline": generation, "authorization_state": "not_evaluated_until_zaelith"},
    )
    vvault_sync.enqueue(receipt_id, {"event_type": "file_baseline_rebuilt", **generation})
    snapshot = _files_snapshot(200)
    snapshot["baseline_receipt"] = {"id": receipt_id, **generation}
    return jsonify(snapshot)


@bp.route("/cleanhouse/files/mediations", methods=["POST"])
def queue_file_mediation():
    payload, error = _parse_json_payload()
    if error:
        return error
    mediation_request, error = _require_string(payload.get("request"), "request", max_len=2000)
    if error:
        return error
    scope = str(payload.get("scope") or "all").strip()
    if scope not in {"all", "current"}:
        return _error_response("scope must be all or current")
    raw_evidence = payload.get("evidence_names") or []
    if not isinstance(raw_evidence, list):
        return _error_response("evidence_names must be an array")
    evidence_names = [str(item).strip()[:255] for item in raw_evidence if str(item).strip()][:20]
    mediation_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data = {
        "mediation_id": mediation_id,
        "status": "queue",
        "request": mediation_request,
        "scope": scope,
        "evidence_names": evidence_names,
        "created_at": now,
        "execution_state": "unavailable_until_zaelith",
    }
    receipt_id = "files-mediation:" + hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    data["transition_receipt"] = {
        "id": receipt_id,
        "from": None,
        "to": "queue",
        "created_at": now,
        "execution_state": "unavailable_until_zaelith",
    }
    events.insert_event(
        event_type="file_mediation_queued",
        path=f"/files/mediations/{mediation_id}",
        summary=mediation_request,
        source_surface=FILES_MEDIATION_SOURCE,
        actor_type="operator",
        evidence_level="declared",
        collector_status="ok",
        evidence_refs=evidence_names,
        source_event_key=receipt_id,
        provider="cleanhouse",
        data=data,
    )
    vvault_sync.enqueue(receipt_id, {"event_type": "file_mediation_queued", **data})
    snapshot = _files_snapshot(200)
    return jsonify({"status": "ok", "mediation": next(item for item in snapshot["mediations"] if item["id"] == mediation_id), "snapshot": snapshot}), 201


@bp.route("/cleanhouse/files/mediations/<mediation_id>/transition", methods=["POST"])
def transition_file_mediation(mediation_id: str):
    if not re.fullmatch(r"[A-Fa-f0-9]{32}", mediation_id):
        return _error_response("invalid mediation id")
    payload, error = _parse_json_payload()
    if error:
        return error
    next_status = str(payload.get("status") or "").strip()
    if next_status not in FILES_MEDIATION_STATES:
        return _error_response("invalid mediation status")
    mediation_rows = events.list_events_by_sources({FILES_MEDIATION_SOURCE: 300}).get(FILES_MEDIATION_SOURCE, [])
    current = next((item for item in _fold_file_mediations(mediation_rows) if item["id"] == mediation_id), None)
    if current is None:
        return {"status": "error", "message": "mediation not found"}, 404
    if next_status not in FILES_MEDIATION_TRANSITIONS[current["status"]]:
        return _error_response(f"cannot transition {current['status']} to {next_status}")
    data = {
        "mediation_id": mediation_id,
        "status": next_status,
        "request": current["request"],
        "scope": current["scope"],
        "evidence_names": current["evidence_names"],
        "created_at": current["created_at"],
        "execution_state": "unavailable_until_zaelith",
    }
    transitioned_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt_payload = {
        "mediation_id": mediation_id,
        "from": current["status"],
        "to": next_status,
        "created_at": transitioned_at,
        "evidence_refs": current["evidence_names"],
        "execution_state": "unavailable_until_zaelith",
    }
    receipt_id = "files-mediation:" + hashlib.sha256(
        json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    receipt_payload["id"] = receipt_id
    data["transition_receipt"] = receipt_payload
    events.insert_event(
        event_type=f"file_mediation_{next_status}",
        path=f"/files/mediations/{mediation_id}",
        summary=f"{next_status.replace('_', ' ')}: {current['request']}",
        source_surface=FILES_MEDIATION_SOURCE,
        actor_type="operator",
        evidence_level="verified",
        collector_status="ok",
        evidence_refs=current["evidence_names"],
        source_event_key=receipt_id,
        provider="cleanhouse",
        data=data,
    )
    vvault_sync.enqueue(receipt_id, {"event_type": f"file_mediation_{next_status}", **data})
    return jsonify({"status": "ok", "transition_receipt": receipt_payload, "snapshot": _files_snapshot(200)})


@bp.route("/events", methods=["GET"])
def get_events():
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_EVENT_MAX_LIMIT)
    if error:
        return error
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    rows = events.list_events(limit=limit or LOW_PROCESSING_EVENT_LIMIT, session_id=session_id)
    schema_error = _validate_events_rows_payload(rows)
    if schema_error:
        return schema_error
    return jsonify(rows)


@bp.route("/receipts", methods=["GET"])
def get_receipts_list():
    limit, error = _optional_positive_int_arg("limit", max_value=LOW_PROCESSING_RECEIPT_MAX_LIMIT)
    if error:
        return error

    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error

    if session_id is not None:
        events.ensure_latest_receipt(session_id=session_id)
    rows = events.list_receipts(limit=limit or LOW_PROCESSING_RECEIPT_LIMIT, session_id=session_id)
    schema_error = _validate_receipts_rows_payload(rows)
    if schema_error:
        return schema_error
    return jsonify(rows)
