"""Deterministic interpreter resolution for supervised CleanHouse runtime paths."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


def _candidate_entries(repo_root: Path | None = None) -> list[dict[str, str]]:
    root = repo_root or REPO_ROOT
    candidates = [
        {"source": "env_override", "path": os.getenv("CLEANHOUSE_PYTHON", "").strip()},
        {"source": "active_sys_executable", "path": (sys.executable or "").strip()},
        {"source": "repo_cleanhouse_env", "path": str(root / "cleanhouse_env" / "bin" / "python3")},
        {"source": "repo_dot_venv", "path": str(root / ".venv" / "bin" / "python3")},
        {"source": "system_python3", "path": shutil.which("python3") or ""},
    ]
    seen: set[str] = set()
    ordered: list[dict[str, str]] = []
    for item in candidates:
        raw = item["path"].strip()
        if not raw:
            continue
        normalized = str(Path(raw).expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append({"source": item["source"], "path": normalized})
    return ordered


def _probe_code(repo_root: Path) -> str:
    return (
        "import importlib, json, sys\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "result = {'runtime_supervisor_importable': False, 'flask_importable': False, 'backend_server_importable': False, 'errors': []}\n"
        "try:\n"
        "    importlib.import_module('backend.runtime_supervisor')\n"
        "    result['runtime_supervisor_importable'] = True\n"
        "except Exception as exc:\n"
        "    result['errors'].append({'component': 'backend.runtime_supervisor', 'error': f'{exc.__class__.__name__}: {exc}'})\n"
        "try:\n"
        "    importlib.import_module('flask')\n"
        "    result['flask_importable'] = True\n"
        "except Exception as exc:\n"
        "    result['errors'].append({'component': 'flask', 'error': f'{exc.__class__.__name__}: {exc}'})\n"
        "try:\n"
        "    importlib.import_module('backend.server')\n"
        "    result['backend_server_importable'] = True\n"
        "except Exception as exc:\n"
        "    result['errors'].append({'component': 'backend.server', 'error': f'{exc.__class__.__name__}: {exc}'})\n"
        "print(json.dumps(result, sort_keys=True))\n"
        "sys.stdout.flush()\n"
        "sys.stderr.flush()\n"
        "import os\n"
        "os._exit(0)\n"
    )


def probe_interpreter(path: str, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    entry: dict[str, Any] = {
        "path": str(Path(path).expanduser()),
        "exists": False,
        "executable": False,
        "status": "unusable",
        "runnable": False,
        "supervisor_compatible": False,
        "backend_compatible": False,
        "failure_reason": "",
        "errors": [],
    }
    candidate = Path(entry["path"])
    if not candidate.exists():
        entry["failure_reason"] = "missing_executable"
        return entry
    entry["exists"] = True
    if not os.access(candidate, os.X_OK):
        entry["failure_reason"] = "not_executable"
        return entry
    entry["executable"] = True
    timeout_seconds_raw = os.getenv("CLEANHOUSE_INTERPRETER_PROBE_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout_seconds = max(5.0, min(120.0, float(timeout_seconds_raw or "60")))
    except ValueError:
        timeout_seconds = 60.0
    try:
        completed = subprocess.run(
            [entry["path"], "-c", _probe_code(root)],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        entry["failure_reason"] = "probe_timeout"
        entry["errors"].append({"component": "probe", "error": "probe timed out"})
        return entry
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        entry["failure_reason"] = "probe_process_failed"
        if stderr:
            entry["errors"].append({"component": "probe", "error": stderr[-1000:]})
        elif stdout:
            entry["errors"].append({"component": "probe", "error": stdout[-1000:]})
        return entry
    try:
        payload = json.loads((completed.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        entry["failure_reason"] = "probe_output_invalid"
        if completed.stdout.strip():
            entry["errors"].append({"component": "probe", "error": completed.stdout.strip()[-1000:]})
        return entry
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    entry["errors"] = errors
    entry["supervisor_compatible"] = bool(payload.get("runtime_supervisor_importable"))
    entry["backend_compatible"] = bool(payload.get("flask_importable") and payload.get("backend_server_importable"))
    if entry["supervisor_compatible"] and entry["backend_compatible"]:
        entry["status"] = "runnable"
        entry["runnable"] = True
        entry["failure_reason"] = ""
    elif entry["supervisor_compatible"]:
        entry["status"] = "supervisor_only"
        entry["runnable"] = False
        entry["failure_reason"] = "backend_dependencies_unavailable"
    else:
        entry["status"] = "unusable"
        entry["runnable"] = False
        entry["failure_reason"] = "supervisor_import_failed"
    return entry


def resolve_interpreter(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for candidate in _candidate_entries(root):
        attempt = {"source": candidate["source"], **probe_interpreter(candidate["path"], root)}
        attempts.append(attempt)
        if selected is None and attempt["status"] in {"runnable", "supervisor_only"}:
            selected = attempt
        if attempt["status"] == "runnable":
            selected = attempt
            break
    failures = [
        {
            "source": item["source"],
            "path": item["path"],
            "reason": item["failure_reason"],
            "errors": item.get("errors", []),
        }
        for item in attempts
        if item["status"] == "unusable"
    ]
    status = "unavailable"
    if selected is not None:
        status = str(selected["status"])
    return {
        "status": status,
        "selected_path": selected.get("path") if selected else None,
        "selected_source": selected.get("source") if selected else None,
        "supervisor_compatible": bool(selected and selected.get("supervisor_compatible")),
        "backend_compatible": bool(selected and selected.get("backend_compatible")),
        "runnable": bool(selected and selected.get("runnable")),
        "attempts": attempts,
        "failures": failures,
    }


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve")
    sub.add_parser("print-path")
    args = parser.parse_args(argv)
    payload = resolve_interpreter()
    if args.command == "resolve":
        _print_payload(payload)
        return 0 if payload.get("supervisor_compatible") else 1
    if args.command == "print-path":
        selected = str(payload.get("selected_path") or "").strip()
        if not selected:
            return 1
        print(selected)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
