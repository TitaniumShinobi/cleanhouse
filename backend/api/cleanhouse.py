"""
CleanHouse monitoring API endpoints.
"""

from __future__ import annotations

import os
import re
import uuid
import hashlib
import json
import plistlib
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file, session, stream_with_context
from backend import events, file_integrity, vvault_sync, wazuh_files
from backend.utils.jwt_utils import get_user_from_token

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter, LOGIN_REPORT_WAIT_SECONDS

bp = Blueprint("cleanhouse", __name__)
LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_SESSION_ID_LENGTH = 128
MAX_PATH_LENGTH = 4096

_adapter: CleanHouseMonitoringAdapter | None = None
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
APPLICATION_CATEGORY_RULES = {
    "communications": ("messages", "facetime", "mail", "slack", "discord", "zoom", "teams", "telegram", "signal", "whatsapp"),
    "developer": ("terminal", "codex", "cursor", "xcode", "visual studio", "code", "kiro", "github", "docker"),
    "files": ("finder", "preview", "textedit", "pages", "numbers", "keynote", "word", "excel", "pdf", "cleanmymac"),
    "network": ("safari", "chrome", "firefox", "arc", "atlas", "vpn", "wireshark"),
}


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


def _app_icon_cache_dir() -> Path:
    return Path(
        os.getenv(
            "CLEANHOUSE_APP_ICON_CACHE_DIR",
            Path.home() / "Documents" / "CleanHouse" / "Data" / "app_icons",
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


def _running_application_keys(process_rows: list[dict[str, Any]]) -> set[str]:
    running: set[str] = set()
    apps = [_application_identity_from_path(path) for path in _discover_application_paths()]
    for app in apps:
        app_path = str(app.get("path", "")).lower()
        app_name = str(app.get("name", "")).lower()
        bundle_id = str(app.get("bundle_id", "")).lower()
        for row in process_rows:
            text = json.dumps(row, default=str).lower()
            if app_path and app_path in text or app_name and app_name in text or bundle_id and bundle_id in text:
                running.add(str(app["id"]))
                break
    return running


def _application_processes(app: dict[str, Any], process_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    app_path = str(app.get("path", "")).lower()
    app_name = str(app.get("name", "")).lower()
    bundle_id = str(app.get("bundle_id", "")).lower()
    matched = []
    for row in process_rows:
        text = json.dumps(row, default=str).lower()
        if app_path and app_path in text or app_name and app_name in text or bundle_id and bundle_id in text:
            matched.append(row)
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
    running_ids = _running_application_keys(process_rows)
    state = _read_app_inventory_state()
    known = state.get("apps", {}) if isinstance(state.get("apps"), dict) else {}
    apps = []
    for app_path in _discover_application_paths():
        app = _application_identity_from_path(app_path)
        previous = known.get(app["id"]) if isinstance(known.get(app["id"]), dict) else None
        first_seen = str(previous.get("first_seen_at")) if previous else discovered_at
        app["first_seen_at"] = first_seen
        app["last_seen_at"] = discovered_at
        app["adopted"] = True
        app["badge"] = "" if previous else "New"
        app["badge_count"] = 0 if previous else 1
        app["running"] = app["id"] in running_ids
        app["audit_status"] = "new" if not previous else "adopted"
        app["processes"] = _application_processes(app, process_rows)
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
    if (
        str(self_deviation.get("status") or "") == "open"
        or str(blocked.get("type") or "") in runtime_supervisor.SELF_DEVIATION_BLOCK_TYPES
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


def _event_spine_payload() -> dict[str, Any]:
    try:
        payload = events.get_runtime_status()
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


def _fast_runtime_payload() -> dict[str, Any]:
    try:
        from backend import runtime_supervisor

        payload = runtime_supervisor.current_runtime_payload()
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
    event_spine = _event_spine_payload()
    payload["event_spine"] = event_spine
    payload["event_writer"] = event_spine.get("writer", {})
    payload["filesystem_watcher"] = event_spine.get("watcher", {})
    payload["notification_policy_contract"] = _notification_policy_contract()
    payload["response_mode"] = "fast"
    return payload


def _fast_status_payload() -> dict[str, Any]:
    runtime = _fast_runtime_payload()
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
        receipts = adapter.get_receipts(session_id=session_id).get("receipts", [])
        alerts = adapter.get_alerts(session_id=session_id).get("alerts", [])
        approvals = adapter.get_approval_queue(session_id=session_id).get("approval_queue", [])
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
    runtime = _fast_runtime_payload()
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
        return dict(payload)
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
        event_spine = _event_spine_payload()
        event_surfaces = _event_spine_surfaces(event_spine)
        collector_health = _event_spine_collector_health(event_surfaces)
        payload["operator_warning"] = (
            "CleanHouse is unhealthy: runtime memory ceiling exceeded. Backend stopped. Evidence and receipt available."
            if "runtime_memory_ceiling_exceeded" in set(runtime_payload.get("reason_codes", []))
            else ""
        )
        payload["event_spine"] = {
            "status": event_spine.get("status", "unknown"),
            "queue": event_spine.get("queue", {}),
            "last_event_at": event_spine.get("last_event_at"),
            "last_event_id": event_spine.get("last_event_id"),
            "last_event_type": event_spine.get("last_event_type"),
            "surfaces": event_surfaces,
            "collector_health": collector_health,
            "degradation": event_spine.get("degradation", {"degraded": False, "reasons": []}),
        }
        payload["notification_policy_contract"] = _notification_policy_contract()
        return jsonify(payload)
    if _fast_operator_api_enabled() and not _truthy_arg("full"):
        return jsonify(_fast_status_payload())

    adapter = get_cleanhouse_monitoring_adapter()
    return jsonify(adapter.get_status(refresh=_refresh_flag()))


@bp.route("/cleanhouse/runtime", methods=["GET"])
def runtime():
    if _fast_operator_api_enabled() and not _truthy_arg("full"):
        return jsonify(_fast_runtime_payload())
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


@bp.route("/cleanhouse/scan/system", methods=["POST"])
def system_scan():
    apps = list_applications_payload(refresh=True)
    processes_payload = get_cleanhouse_monitoring_adapter().get_processes(refresh=True)
    network_payload = get_cleanhouse_monitoring_adapter().get_network(refresh=True)
    process_data = processes_payload.get("data", {}) if isinstance(processes_payload, dict) else {}
    network_data = network_payload.get("data", {}) if isinstance(network_payload, dict) else {}
    finding_count = int(apps.get("new_count", 0) or 0)
    finding_count += len(process_data.get("issues", []) if isinstance(process_data.get("issues"), list) else [])
    finding_count += len(network_data.get("issues", []) if isinstance(network_data.get("issues"), list) else [])
    scan_id = "system-scan-" + _artifact_id(_now_iso(), str(apps.get("count", 0)), str(finding_count))
    return jsonify({
        "status": "ok",
        "scan_id": scan_id,
        "scope": "whole_system",
        "summary": "Whole system scan completed with app inventory, process, and network evidence.",
        "finding_count": finding_count,
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


def _wireshark_status_payload() -> dict[str, Any]:
    tshark = shutil.which("tshark")
    wireshark = shutil.which("wireshark") or shutil.which("Wireshark")
    dumpcap = shutil.which("dumpcap")
    status = "available" if tshark else "missing"
    message = "Wireshark/tshark capture support is available." if tshark else "tshark is not available; install Wireshark CLI tools to enable packet-backed network evidence."
    return {
        "status": status,
        "engine": "wireshark",
        "tshark_path": tshark or "",
        "wireshark_path": wireshark or "",
        "dumpcap_path": dumpcap or "",
        "permission_state": "unknown" if tshark else "setup_required",
        "message": message,
        "fallback": "Existing CleanHouse network metadata remains available but is not the final network evidence authority.",
    }


@bp.route("/cleanhouse/network/wireshark", methods=["GET"])
def wireshark_status():
    return jsonify(_wireshark_status_payload())


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
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    return jsonify(adapter.get_domain_events(
        domain=domain or None,
        surface=surface or None,
        severity=severity or None,
        status=status or None,
        limit=limit or 200,
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
    limit, error = _optional_positive_int_arg("limit")
    if error:
        return error
    return jsonify(adapter.get_reports(
        session_id=session_id,
        report_type=report_type or None,
        limit=limit,
        summary_only=_truthy_arg("summary_only"),
    ))


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


FILES_WATCHER_SOURCE = "filesystem_watcher"
FILES_WAZUH_SOURCE = "wazuh_fim"


def _files_event_epoch(row: dict[str, Any]) -> float | None:
    value = str(row.get("timestamp") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _files_presentable_event(row: dict[str, Any]) -> bool:
    path = Path(str(row.get("path") or ""))
    if not str(path):
        return False
    if set(path.parts).intersection({".git", "__pycache__", "node_modules", "cleanhouse_env"}):
        return False
    return path.name != ".DS_Store" and path.suffix.lower() not in {".pyc", ".pyo", ".swp", ".tmp"}


def _files_correlated(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Prefer live Wazuh projection while retaining raw provider rows durably."""
    projected: list[dict[str, Any]] = []
    for original in rows:
        if not _files_presentable_event(original):
            continue
        row = dict(original)
        path = str(row.get("path") or "")
        event_type = str(row.get("event_type") or "")
        provider = str(row.get("provider") or row.get("source_surface") or "")
        timestamp = _files_event_epoch(row)
        matched = None
        for index, existing in enumerate(projected):
            if str(existing.get("path") or "") != path or str(existing.get("event_type") or "") != event_type:
                continue
            existing_provider = str(existing.get("provider") or existing.get("source_surface") or "")
            existing_timestamp = _files_event_epoch(existing)
            if existing_provider == provider or timestamp is None or existing_timestamp is None:
                continue
            if abs(timestamp - existing_timestamp) <= 5:
                matched = index
                break
        if matched is not None:
            existing = projected[matched]
            existing_provider = str(existing.get("provider") or existing.get("source_surface") or "")
            providers = sorted({provider, existing_provider})
            if provider == "wazuh" and existing_provider != "wazuh":
                row["correlated_providers"] = providers
                projected[matched] = row
            else:
                existing["correlated_providers"] = providers
            continue
        row["correlated_providers"] = [provider] if provider else []
        projected.append(row)
        if len(projected) >= limit:
            break
    return projected


def _files_snapshot(limit: int = 200) -> dict[str, Any]:
    bounded_limit = min(max(1, int(limit)), 500)
    source_rows = events.list_events_by_sources({
        FILES_WATCHER_SOURCE: min(max(500, bounded_limit * 4), 1000),
        FILES_WAZUH_SOURCE: min(max(500, bounded_limit * 4), 1000),
    })
    candidates = sorted(
        [*source_rows.get(FILES_WAZUH_SOURCE, []), *source_rows.get(FILES_WATCHER_SOURCE, [])],
        key=lambda row: int(row.get("id") or 0),
        reverse=True,
    )
    projected = _files_correlated(candidates, limit=bounded_limit)
    watcher = events.get_watcher_status()
    wazuh = wazuh_files.status()
    preservation = vvault_sync.status(surface="files")
    current_wazuh_live = bool(wazuh.get("operational")) and wazuh.get("health") in {"live", "no_data"}
    fallback_active = not current_wazuh_live and watcher.get("status") == "running"
    if current_wazuh_live:
        state = str(wazuh.get("health") or "live")
        provider = "wazuh"
    elif fallback_active:
        state = "fallback"
        provider = "watchdog"
    elif wazuh.get("configured"):
        state = "degraded" if wazuh.get("last_error") else "warming"
        provider = "none"
    else:
        state = "unavailable"
        provider = "none"
    cursor = max([int(row.get("id") or 0) for row in projected] or [0])
    collector = {
        "provider": provider,
        "health": state,
        "lifecycle": str(wazuh.get("lifecycle") or "unavailable"),
        "configured": bool(wazuh.get("configured")),
        "operational": bool(wazuh.get("operational")),
        "evidence_authenticated": bool(wazuh.get("authenticated")),
        "powered_by_wazuh": bool(wazuh.get("powered_by_wazuh")),
        "historical_wazuh_proof": bool(wazuh.get("historical_wazuh_proof")),
        "agent_id": wazuh.get("agent_id") or None,
        "manager": wazuh.get("manager") or None,
        "manager_version": wazuh.get("manager_version") or None,
        "monitored_scope": wazuh.get("monitored_scope") or watcher.get("watch_dir"),
        "last_event_at": wazuh.get("last_event_at") or (projected[0].get("timestamp") if projected else None),
        "ingestion_latency_ms": wazuh.get("ingestion_latency_ms"),
        "cursor": wazuh.get("cursor") or "",
        "gap_state": wazuh.get("gap_state") or "unknown",
        "fallback": {
            "active": fallback_active,
            "provider": "watchdog",
            "status": watcher.get("status") or "unknown",
            "reason": "wazuh_not_operational" if fallback_active else "inactive",
        },
        "last_error": wazuh.get("last_error") or "",
    }
    return {
        "status": "ok" if state in {"live", "no_data", "fallback"} else state,
        "schema": "cleanhouse.files.v2",
        "cursor": cursor,
        "collector": collector,
        "powered_by_wazuh": collector["powered_by_wazuh"],
        "monitoring": {
            "always_on": bool(current_wazuh_live or fallback_active),
            "status": state,
            "provider": provider,
            "watch_dir": collector["monitored_scope"],
            "fallback": collector["fallback"],
        },
        "events": projected,
        "findings": [],
        "integrity": file_integrity.snapshot(),
        "locations": [],
        "mediations": [],
        "suggestions": [],
        "attention_count": 0,
        "attention": [],
        "reconciliation": {},
        "preservation": preservation,
    }


def _files_sse_event(event: str, payload: dict[str, Any], *, event_id: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), default=str)
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


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
        last_signature = ""
        last_keepalive = time.monotonic()
        while True:
            snapshot = _files_snapshot(200)
            cursor = int(snapshot.get("cursor") or 0)
            signature = hashlib.sha256(json.dumps({
                "collector": snapshot.get("collector"),
                "integrity": snapshot.get("integrity"),
                "preservation": snapshot.get("preservation"),
            }, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            if cursor != last_cursor or signature != last_signature:
                yield _files_sse_event("files-snapshot", snapshot, event_id=str(cursor))
                last_cursor = cursor
                last_signature = signature
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


@bp.route("/events", methods=["GET"])
def get_events():
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error
    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error
    rows = events.list_events(limit=limit or 100, session_id=session_id)
    schema_error = _validate_events_rows_payload(rows)
    if schema_error:
        return schema_error
    return jsonify(rows)


@bp.route("/receipts", methods=["GET"])
def get_receipts_list():
    limit, error = _optional_positive_int_arg("limit", max_value=1000)
    if error:
        return error

    session_id, error = _validate_session_id(request.args.get("session_id"), required=False)
    if error:
        return error

    if session_id is not None:
        events.ensure_latest_receipt(session_id=session_id)
    rows = events.list_receipts(limit=limit or 100, session_id=session_id)
    schema_error = _validate_receipts_rows_payload(rows)
    if schema_error:
        return schema_error
    return jsonify(rows)


def _allowed_threats_path() -> Path:
    return Path(
        os.getenv(
            "CLEANHOUSE_ALLOWED_THREATS_PATH",
            Path.home() / "Documents" / "CleanHouse" / "Data" / "allowed_threats" / "allowed_threats.json",
        )
    )

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
