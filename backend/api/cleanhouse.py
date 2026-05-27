"""
CleanHouse monitoring API endpoints.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request
from backend import events

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter

bp = Blueprint("cleanhouse", __name__)
LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_SESSION_ID_LENGTH = 128
MAX_PATH_LENGTH = 4096

_adapter: CleanHouseMonitoringAdapter | None = None
DEFAULT_SESSION_ID = "default-session"


def get_cleanhouse_monitoring_adapter() -> CleanHouseMonitoringAdapter:
    global _adapter
    if _adapter is None:
        _adapter = CleanHouseMonitoringAdapter()
    return _adapter


def _parse_json_payload():
    payload = request.get_json(silent=True)
    if payload is None:
        return None, ({"status": "error", "message": "Request body must be valid JSON."}, 400)
    if not isinstance(payload, dict):
        return None, ({"status": "error", "message": "Request body must be a JSON object."}, 400)
    return payload, None


def _error_response(message: str):
    return {"status": "error", "message": message}, 400


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


@bp.route("/cleanhouse/status", methods=["GET"])
def status():
    if request.args.get("ready", "").lower() in {"1", "true", "yes", "on"}:
        return jsonify({"status": "ok", "ready": True})

    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_status(refresh=_refresh_flag()))


@bp.route("/cleanhouse/processes", methods=["GET"])
def processes():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_processes(refresh=_refresh_flag()))


@bp.route("/cleanhouse/network", methods=["GET"])
def network():
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_network(refresh=_refresh_flag()))


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


@bp.route("/cleanhouse/objective/start", methods=["POST"])
def start_objective():
    data, error = _parse_json_payload()
    if error:
        return error
    objective_id, error = _require_string(data.get("objective_id"), "objective_id", required=False, max_len=256)
    if error:
        return error
    if not objective_id:
        objective_id = str(uuid.uuid4())
    session_id, error = _resolve_session_id(data.get("session_id"), required=False)
    if error:
        return error
    summary = _objective_text_from_payload(data)

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
    return jsonify(adapter.get_intents())


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
    prompt_type, error = _require_string(data.get("prompt_type"), "prompt_type", required=False, allow_empty=True, max_len=64)
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
        objective_id=objective_id or None,
        prompt_type=prompt_type or "objective",
        parent_intervention_id=parent_intervention_id or None,
        evidence_refs=evidence_refs,
        metadata=metadata,
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
    return jsonify(adapter.start_operator_session({
        "session_id": session_id,
        "objective_id": objective_id or None,
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
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_workstation(session_id=session_id))


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


@bp.route("/cleanhouse/notifications/<notification_id>/ack", methods=["POST"])
def ack_notification(notification_id):
    notification_id, error = _require_string(notification_id, "notification_id", max_len=256)
    if error:
        return error
    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.ack_operator_notification(notification_id))


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
    return jsonify(adapter.get_approval_queue(session_id=session_id, status=status or None))


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
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_receipts(session_id=session_id))


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
    return jsonify(get_cleanhouse_monitoring_adapter().build_login_report(
        user_id=user_id or "",
        email=email or "",
        previous_login_at=previous_login_at or None,
        current_login_at=current_login_at or None,
        trigger=trigger or "api/login-report",
    ))


@bp.route("/cleanhouse/reports", methods=["GET"])
def get_reports():
    adapter = get_cleanhouse_monitoring_adapter()
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(adapter.get_reports(session_id=session_id))


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


@bp.route("/events", methods=["GET"])
def get_events():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return _error_response("limit must be an integer")
    if limit < 1:
        return _error_response("limit must be greater than 0")
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    return jsonify(events.list_events(limit=limit, session_id=session_id))


@bp.route("/receipts", methods=["GET"])
def get_receipts_list():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return _error_response("limit must be an integer")
    if limit < 1:
        return _error_response("limit must be greater than 0")

    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error

    if session_id is not None:
        events.ensure_latest_receipt(session_id=session_id)
    return jsonify(events.list_receipts(limit=limit, session_id=session_id))
