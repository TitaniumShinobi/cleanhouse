#!/usr/bin/env python3
"""Gate A no-browser startup and runtime smoke harness."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tier1_runtime_gate import run_active_spine


DEFAULT_HOST = "127.0.0.1"
DEFAULT_CLEANHOUSE_PORT = 3333
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_READINESS_BUDGET_MS = 1000.0
DEFAULT_DASHBOARD_BUDGET_MS = 1000.0
DEFAULT_FULL_STATUS_BUDGET_MS = 15000.0


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[int, bytes, dict[str, str]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.getcode(), response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    code, body, _headers = _request(base_url, method, path, payload, timeout=timeout)
    decoded = body.decode("utf-8", errors="replace")
    try:
        result = json.loads(decoded or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path} returned non-JSON HTTP {code}: {decoded[:500]}") from exc
    if code >= 400:
        raise RuntimeError(f"{method} {path} failed with HTTP {code}: {result}")
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object JSON payload")
    return result


def _request_text(base_url: str, path: str, *, timeout: float = 10.0) -> tuple[int, str]:
    code, body, _headers = _request(base_url, "GET", path, timeout=timeout)
    return code, body.decode("utf-8", errors="replace")


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000.0, 2)


def _timed_request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[dict[str, Any], float]:
    start = time.monotonic()
    result = _request_json(base_url, method, path, payload, timeout=timeout)
    return result, _elapsed_ms(start)


def _timed_request_text(base_url: str, path: str, *, timeout: float = 10.0) -> tuple[int, str, float]:
    start = time.monotonic()
    code, text = _request_text(base_url, path, timeout=timeout)
    return code, text, _elapsed_ms(start)


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _free_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _default_python() -> str:
    local_python = REPO_ROOT / "cleanhouse_env" / "bin" / "python3"
    if local_python.is_file():
        return str(local_python)
    return sys.executable


def _check_dependencies(python_exe: str) -> dict[str, Any]:
    check_code = """
import importlib.util
import json
import sys

required = ["flask", "flask_cors"]
optional = ["watchdog"]
result = {
    "python": sys.executable,
    "required": {name: importlib.util.find_spec(name) is not None for name in required},
    "optional": {name: importlib.util.find_spec(name) is not None for name in optional},
}
result["missing_required"] = [name for name, ok in result["required"].items() if not ok]
result["missing_optional"] = [name for name, ok in result["optional"].items() if not ok]
print(json.dumps(result, sort_keys=True))
raise SystemExit(1 if result["missing_required"] else 0)
"""
    completed = subprocess.run(
        [python_exe, "-c", check_code],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=10,
    )
    stdout = completed.stdout.strip()
    try:
        result = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        result = {
            "python": python_exe,
            "missing_required": ["dependency-check"],
            "stderr": completed.stderr.strip(),
            "stdout": stdout,
        }
    result["returncode"] = completed.returncode
    result.setdefault("missing_required", [])
    result.setdefault("missing_optional", [])
    result["status"] = "ok" if not result["missing_required"] else "blocked"
    return result


def _tail(path: Path, max_lines: int = 80) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _status_shape_probe(base_url: str, *, full_status_budget_ms: float) -> dict[str, Any]:
    readiness, readiness_ms = _timed_request_json(
        base_url,
        "GET",
        "/cleanhouse/status?ready=1",
        timeout=1.0,
    )
    full_status, full_status_ms = _timed_request_json(
        base_url,
        "GET",
        "/cleanhouse/status?refresh=1",
        timeout=max(1.0, full_status_budget_ms / 1000.0),
    )
    readiness_keys = sorted(readiness.keys())
    full_data = full_status.get("data", {})
    full_manifest = full_data.get("collector_manifest", {}) if isinstance(full_data, dict) else {}
    runtime_status = full_data.get("runtime", {}) if isinstance(full_data, dict) else {}
    checks = {
        "readiness_status_ok": readiness.get("status") == "ok" and readiness.get("ready") is True,
        "readiness_payload_minimal": readiness_keys == ["ready", "status"],
        "readiness_omits_full_status": not any(key in readiness for key in ("data", "issues", "settings", "plugins")),
        "full_status_has_data": isinstance(full_data, dict) and bool(full_data),
        "full_status_has_collector_manifest": isinstance(full_manifest, dict) and bool(full_manifest.get("surfaces")),
        "full_status_has_runtime": isinstance(runtime_status, dict) and bool(runtime_status),
    }
    return {
        "status": "ok" if all(checks.values()) else "failed",
        "checks": checks,
        "readiness": {
            "source": "/cleanhouse/status?ready=1",
            "keys": readiness_keys,
            "status": readiness.get("status"),
            "ready": readiness.get("ready"),
        },
        "full_status": {
            "source": "/cleanhouse/status?refresh=1",
            "status": full_status.get("status", "unknown"),
            "collector_surface_count": len(full_manifest.get("surfaces", {})) if isinstance(full_manifest, dict) else 0,
            "runtime_keys": sorted(runtime_status.keys()) if isinstance(runtime_status, dict) else [],
        },
        "performance": {
            "readiness_ms": readiness_ms,
            "full_status_ms": full_status_ms,
            "full_status_budget_ms": full_status_budget_ms,
            "full_status_under_budget": full_status_ms <= full_status_budget_ms,
        },
    }


def _port_conflict_probe(host: str) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        conflict_port = int(sock.getsockname()[1])
        detected = _port_open(host, conflict_port)
        return {
            "status": "ok" if detected else "failed",
            "host": host,
            "port": conflict_port,
            "conflict_detected": detected,
            "server_start_attempted": False,
        }


def _start_server(
    *,
    python_exe: str,
    host: str,
    port: int,
    home_dir: Path,
    workspace_dir: Path,
    log_path: Path,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["CLEANHOUSE_HOST"] = host
    env["CLEANHOUSE_PORT"] = str(port)
    env["CLEANHOUSE_ENABLE_AUTH"] = "0"
    env["CLEANHOUSE_EVENTS_DB"] = str(home_dir / "events.db")
    env["CLEANHOUSE_WATCH_DIR"] = str(workspace_dir)
    env["CLEANHOUSE_ALLOWED_REPO_ROOTS"] = ",".join([str(home_dir), str(REPO_ROOT)])
    env["PYTHONUNBUFFERED"] = "1"
    log = log_path.open("ab")
    process = subprocess.Popen(
        [python_exe, "backend/server.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    log.close()
    return process


def _stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_runtime(
    *,
    base_url: str,
    process: subprocess.Popen | None,
    log_path: Path,
    timeout_seconds: float,
    readiness_budget_ms: float,
    dashboard_budget_ms: float,
    full_status_budget_ms: float,
) -> dict[str, Any]:
    startup_start = time.monotonic()
    deadline = time.monotonic() + timeout_seconds
    last_error = "runtime not yet reachable"
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                "CleanHouse server exited before readiness "
                f"(status={process.returncode})\n{_tail(log_path)}"
            )
        try:
            status, readiness_ms = _timed_request_json(
                base_url,
                "GET",
                "/cleanhouse/status?ready=1",
                timeout=1.0,
            )
            code, dashboard, dashboard_ms = _timed_request_text(base_url, "/dashboard", timeout=1.0)
            if code == 200 and "operator-workstation" in dashboard:
                runtime_ready_ms = _elapsed_ms(startup_start)
                status_shape = _status_shape_probe(
                    base_url,
                    full_status_budget_ms=full_status_budget_ms,
                )
                performance = {
                    "runtime_ready_ms": runtime_ready_ms,
                    "startup_with_full_status_probe_ms": _elapsed_ms(startup_start),
                    "readiness_ms": readiness_ms,
                    "dashboard_ms": dashboard_ms,
                    "full_status_ms": status_shape.get("performance", {}).get("full_status_ms"),
                    "budgets_ms": {
                        "readiness": readiness_budget_ms,
                        "dashboard": dashboard_budget_ms,
                        "full_status": full_status_budget_ms,
                    },
                }
                low_overhead_checks = {
                    "readiness_under_budget": readiness_ms <= readiness_budget_ms,
                    "dashboard_under_budget": dashboard_ms <= dashboard_budget_ms,
                    "readiness_payload_minimal": status_shape.get("checks", {}).get("readiness_payload_minimal") is True,
                }
                return {
                    "status": "ok",
                    "status_ready": status.get("ready") is True and status.get("status") == "ok",
                    "dashboard_http_status": code,
                    "dashboard_contains_operator_workstation": True,
                    "status_separation": status_shape,
                    "performance": performance,
                    "low_overhead": {
                        "status": "ok" if all(low_overhead_checks.values()) else "failed",
                        "checks": low_overhead_checks,
                    },
                }
            last_error = f"dashboard unavailable or unexpected (status={code})"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(
        f"CleanHouse runtime did not become ready at {base_url}: {last_error}\n{_tail(log_path)}"
    )


def _run_active_gate(base_url: str) -> dict[str, Any]:
    original_cwd = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        return run_active_spine(base_url)
    finally:
        os.chdir(original_cwd)


def _post_active_checks(base_url: str, active: dict[str, Any]) -> dict[str, Any]:
    session_id = str(active.get("session_id") or "")
    objective_id = str(active.get("objective_id") or "")
    receipt_id = str(active.get("receipt", {}).get("id") or "")
    session = _request_json(base_url, "POST", "/cleanhouse/session/start", {
        "session_id": session_id,
        "objective_id": objective_id,
        "summary": "Gate A runtime smoke session",
        "metadata": {"gate": "A", "harness": "gate_a_runtime_smoke"},
    })
    approval = _request_json(base_url, "POST", "/cleanhouse/approval-queue", {
        "session_id": session_id,
        "requested_action": "review Gate A runtime smoke receipt",
        "reason": "runtime smoke validates approval persistence and resolution",
        "objective_id": objective_id,
        "evidence_refs": [f"local://cleanhouse/receipt/{receipt_id}"] if receipt_id else [],
        "reviewer": "gate_a_runtime_smoke",
        "metadata": {"receipt_id": receipt_id, "gate": "A"},
    })
    approval_id = str(approval.get("approval", {}).get("id") or "")
    resolved = {}
    if approval_id:
        resolved = _request_json(
            base_url,
            "POST",
            f"/cleanhouse/approval-queue/{urllib.parse.quote(approval_id, safe='')}",
            {
                "status": "approved",
                "note": "Gate A runtime smoke approved harness-generated review item.",
                "reviewer": "gate_a_runtime_smoke",
            },
        )
    approvals = _request_json(
        base_url,
        "GET",
        "/cleanhouse/approval-queue?" + urllib.parse.urlencode({"session_id": session_id}),
    )
    workstation = _request_json(
        base_url,
        "GET",
        "/cleanhouse/workstation?" + urllib.parse.urlencode({"session_id": session_id}),
    )
    return {
        "session_start": session,
        "approval": approval,
        "approval_resolution": resolved,
        "approval_count": len(approvals.get("approval_queue", [])),
        "workstation_status": workstation.get("status"),
    }


def _restart_artifact_checks(base_url: str, active: dict[str, Any]) -> dict[str, Any]:
    session_id = str(active.get("session_id") or "")
    receipt_id = str(active.get("receipt", {}).get("id") or "")
    if not session_id or not receipt_id:
        return {
            "status": "failed",
            "checks": {
                "session_id_available": bool(session_id),
                "receipt_id_available": bool(receipt_id),
            },
        }

    receipt_qs = urllib.parse.urlencode({"receipt_id": receipt_id})
    session_qs = urllib.parse.urlencode({"session_id": session_id})
    replay = _request_json(base_url, "GET", f"/cleanhouse/receipt-replay?{receipt_qs}")
    bundle = _request_json(base_url, "GET", f"/cleanhouse/receipt-bundle?{receipt_qs}")
    imported = _request_json(base_url, "POST", "/cleanhouse/receipt-bundle/import", {
        "bundle": bundle.get("bundle", {}),
    })
    workstation = _request_json(base_url, "GET", f"/cleanhouse/workstation?{session_qs}")
    receipts = _request_json(base_url, "GET", f"/cleanhouse/receipts?{session_qs}")
    checks = {
        "receipt_replay_loaded_after_restart": replay.get("status") == "ok",
        "receipt_bundle_loaded_after_restart": bundle.get("status") == "ok",
        "receipt_bundle_imported_after_restart": imported.get("status") == "ok",
        "session_workstation_loaded_after_restart": workstation.get("status") == "ok",
        "receipt_visible_after_restart": any(
            item.get("id") == receipt_id
            for item in receipts.get("receipts", [])
            if isinstance(item, dict)
        ),
    }
    return {
        "status": "ok" if all(checks.values()) else "failed",
        "checks": checks,
        "receipt_id": receipt_id,
        "session_id": session_id,
        "replay_hash": replay.get("integrity", {}).get("replay_hash"),
        "bundle_hash": bundle.get("bundle", {}).get("integrity", {}).get("bundle_hash"),
        "import_status": imported.get("status"),
    }


def _write_artifact(artifact_dir: Path | None, payload: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "gate_a_runtime_smoke.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _blocked_result(
    *,
    base_url: str,
    reason: str,
    dependencies: dict[str, Any] | None = None,
    log_tail: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "base_url": base_url,
        "blocker": reason,
        "operator_verification": {
            "method": "http-api",
            "no_browser_automation": True,
            "browser_automation_used": False,
        },
    }
    if dependencies is not None:
        result["dependencies"] = dependencies
    if log_tail:
        result["log_tail"] = log_tail
    return result


def run_gate_a_runtime_smoke(
    *,
    base_url: str,
    python_exe: str,
    host: str,
    port: int,
    no_start: bool,
    keep_running: bool,
    timeout_seconds: float,
    readiness_budget_ms: float = DEFAULT_READINESS_BUDGET_MS,
    dashboard_budget_ms: float = DEFAULT_DASHBOARD_BUDGET_MS,
    full_status_budget_ms: float = DEFAULT_FULL_STATUS_BUDGET_MS,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    dependencies = _check_dependencies(python_exe)
    if dependencies.get("missing_required"):
        result = _blocked_result(
            base_url=base_url,
            reason="missing required runtime dependencies",
            dependencies=dependencies,
        )
        _write_artifact(artifact_dir, result)
        return result

    owned_process = not no_start
    process: subprocess.Popen | None = None
    restart_process: subprocess.Popen | None = None
    with contextlib.ExitStack() as stack:
        home_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="gate-a-home-"))).resolve()
        workspace_dir = home_dir / "gate-a-workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        log_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="gate-a-runtime-"))).resolve()
        log_path = log_dir / "server.log"
        port_conflict = _port_conflict_probe(host)

        if owned_process:
            if _port_open(host, port):
                result = _blocked_result(
                    base_url=base_url,
                    reason=f"port already in use: {host}:{port}",
                    dependencies=dependencies,
                )
                _write_artifact(artifact_dir, result)
                return result
            process = _start_server(
                python_exe=python_exe,
                host=host,
                port=port,
                home_dir=home_dir,
                workspace_dir=workspace_dir,
                log_path=log_path,
            )

        try:
            startup = _wait_for_runtime(
                base_url=base_url,
                process=process if owned_process else None,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
                readiness_budget_ms=readiness_budget_ms,
                dashboard_budget_ms=dashboard_budget_ms,
                full_status_budget_ms=full_status_budget_ms,
            )
            active_start = time.monotonic()
            active = _run_active_gate(base_url)
            active_elapsed_ms = _elapsed_ms(active_start)
            post_active = _post_active_checks(base_url, active)
            restart = {
                "status": "skipped",
                "reason": "runtime was not started by this harness",
            }
            restart_startup = {
                "status": "skipped",
                "reason": "runtime was not started by this harness",
            }
            if owned_process:
                _stop_server(process)
                process = None
                restart_log_path = log_dir / "server-restart.log"
                if _port_open(host, port):
                    result = _blocked_result(
                        base_url=base_url,
                        reason=f"port did not release before restart: {host}:{port}",
                        dependencies=dependencies,
                        log_tail=_tail(log_path),
                    )
                    _write_artifact(artifact_dir, result)
                    return result
                restart_process = _start_server(
                    python_exe=python_exe,
                    host=host,
                    port=port,
                    home_dir=home_dir,
                    workspace_dir=workspace_dir,
                    log_path=restart_log_path,
                )
                restart_startup = _wait_for_runtime(
                    base_url=base_url,
                    process=restart_process,
                    log_path=restart_log_path,
                    timeout_seconds=timeout_seconds,
                    readiness_budget_ms=readiness_budget_ms,
                    dashboard_budget_ms=dashboard_budget_ms,
                    full_status_budget_ms=full_status_budget_ms,
                )
                restart = _restart_artifact_checks(base_url, active)
            startup_separation = startup.get("status_separation", {})
            restart_separation = restart_startup.get("status_separation", {})
            checks = {
                "alternate_port_used": (not owned_process) or port != DEFAULT_CLEANHOUSE_PORT,
                "port_conflict_detected": port_conflict.get("status") == "ok",
                "startup_dashboard_ready": startup.get("status") == "ok",
                "startup_status_separation": startup_separation.get("status") == "ok",
                "startup_low_overhead": startup.get("low_overhead", {}).get("status") == "ok",
                "active_runtime_gate_ok": active.get("status") == "ok",
                "session_start_visible": post_active.get("session_start", {}).get("status") == "ok",
                "approval_created": bool(post_active.get("approval", {}).get("approval", {}).get("id")),
                "approval_resolved": post_active.get("approval_resolution", {}).get("approval", {}).get("status") == "approved",
                "restart_runtime_ready": restart_startup.get("status") in {"ok", "skipped"},
                "restart_status_separation": restart_separation.get("status") in {"ok", None},
                "restart_low_overhead": restart_startup.get("low_overhead", {}).get("status") in {"ok", None},
                "restart_artifact_retrieval": restart.get("status") in {"ok", "skipped"},
                "no_browser_operator_verification": True,
                "browser_automation_used": False,
            }
            browser_flags = {
                key: value
                for key, value in checks.items()
                if key.endswith("browser_automation_used")
            }
            passed = (
                all(value for key, value in checks.items() if not key.endswith("browser_automation_used"))
                and not any(browser_flags.values())
            )
            result = {
                "status": "ok" if passed else "failed",
                "base_url": base_url,
                "port": port,
                "port_mode": "alternate" if port != DEFAULT_CLEANHOUSE_PORT else "default",
                "port_conflict_probe": port_conflict,
                "dependencies": dependencies,
                "startup": startup,
                "active_runtime_gate": active,
                "post_active_checks": post_active,
                "restart_startup": restart_startup,
                "restart_artifact_retrieval": restart,
                "performance": {
                    "active_runtime_gate_ms": active_elapsed_ms,
                    "startup": startup.get("performance", {}),
                    "restart": restart_startup.get("performance", {}),
                },
                "operator_verification": {
                    "method": "http-api",
                    "checks": checks,
                    "no_browser_automation": True,
                    "browser_automation_used": False,
                },
            }
            _write_artifact(artifact_dir, result)
            return result
        except Exception as exc:
            result = _blocked_result(
                base_url=base_url,
                reason=str(exc),
                dependencies=dependencies,
                log_tail=_tail(log_path),
            )
            _write_artifact(artifact_dir, result)
            return result
        finally:
            if not keep_running:
                _stop_server(process)
                _stop_server(restart_process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--python", default="")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--readiness-budget-ms", type=float, default=DEFAULT_READINESS_BUDGET_MS)
    parser.add_argument("--dashboard-budget-ms", type=float, default=DEFAULT_DASHBOARD_BUDGET_MS)
    parser.add_argument("--full-status-budget-ms", type=float, default=DEFAULT_FULL_STATUS_BUDGET_MS)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    port = args.port or _free_port(args.host)
    base_url = args.base_url or f"http://{args.host}:{port}"
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or args.host
    if host in {"localhost", "::1"}:
        host = DEFAULT_HOST
    port = parsed.port or port
    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None

    result = run_gate_a_runtime_smoke(
        base_url=base_url,
        python_exe=args.python or _default_python(),
        host=host,
        port=port,
        no_start=args.no_start,
        keep_running=args.keep_running,
        timeout_seconds=args.timeout,
        readiness_budget_ms=args.readiness_budget_ms,
        dashboard_budget_ms=args.dashboard_budget_ms,
        full_status_budget_ms=args.full_status_budget_ms,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
