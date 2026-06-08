#!/usr/bin/env python3
"""HTTP-only CleanHouse runtime stabilization soak gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from backend import runtime_env

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3333


def _python() -> str:
    resolved = runtime_env.resolve_interpreter(REPO_ROOT)
    selected = str(resolved.get("selected_path") or "").strip()
    return selected or sys.executable


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(body or "{}")
        except json.JSONDecodeError:
            decoded = {"status": "error", "message": body[:500]}
        return exc.code, decoded


def _request_text(base_url: str, path: str, *, timeout: float = 10.0) -> tuple[int, str]:
    url = base_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.getcode(), response.read().decode("utf-8", errors="replace")


def _ensure_runtime(host: str, port: int, timeout: float) -> dict[str, Any]:
    env = os.environ.copy()
    env["CLEANHOUSE_HOST"] = host
    env["CLEANHOUSE_PORT"] = str(port)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    completed = subprocess.run(
        [
            _python(),
            "-m",
            "backend.runtime_supervisor",
            "start",
            "--host",
            host,
            "--port",
            str(port),
            "--timeout",
            str(timeout),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout + 10,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    if completed.returncode != 0:
        raise RuntimeError(f"supervisor start failed: {completed.stderr[-1000:]} {completed.stdout[-1000:]}")
    return payload


def _post_login_report(base_url: str) -> dict[str, Any]:
    user_id = f"soak-{uuid.uuid4().hex[:12]}"
    code, payload = _request(
        base_url,
        "POST",
        "/cleanhouse/login-report",
        {
            "user_id": user_id,
            "email": f"{user_id}@cleanhouse.local",
            "previous_login_at": "2026-05-27T00:00:00+00:00",
            "trigger": "runtime_stabilization_soak",
        },
        timeout=12,
    )
    if code == 200:
        return payload
    if code not in {202, 429}:
        raise RuntimeError(f"login report POST failed HTTP {code}: {payload}")
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"login report did not return a job id: {payload}")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        poll_code, poll = _request(base_url, "GET", f"/cleanhouse/login-report/{urllib.parse.quote(job_id)}", timeout=5)
        if poll_code == 200 and poll.get("status") == "ok":
            return poll
        if poll_code not in {200, 202}:
            raise RuntimeError(f"login report poll failed HTTP {poll_code}: {poll}")
        time.sleep(1)
    raise RuntimeError(f"login report job did not complete: {job_id}")


def _create_notification_probe(base_url: str) -> dict[str, Any]:
    session_id = f"soak-session-{uuid.uuid4().hex[:10]}"
    code, payload = _request(
        base_url,
        "POST",
        "/cleanhouse/approval-queue",
        {
            "session_id": session_id,
            "requested_action": "runtime stabilization soak notification probe",
            "reason": "soak gate requires native delivery evidence",
            "objective_id": "runtime-stabilization-soak",
            "source": "runtime_stabilization_soak",
            "reviewer": "runtime_stabilization_soak",
            "evidence_refs": [f"local://cleanhouse/runtime-soak/{session_id}"],
        },
        timeout=10,
    )
    if code >= 400:
        raise RuntimeError(f"notification probe approval failed HTTP {code}: {payload}")
    return payload


def _stop_runtime(host: str, port: int) -> dict[str, Any]:
    completed = subprocess.run(
        [_python(), "-m", "backend.runtime_supervisor", "stop", "--host", host, "--port", str(port)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"status": "error", "message": completed.stderr[-500:]}


def run_soak(*, host: str, port: int, duration_seconds: float, no_start: bool, stop_after: bool, artifact_dir: Path | None) -> dict[str, Any]:
    base_url = f"http://{host}:{port}"
    startup = {"status": "skipped", "reason": "no-start"}
    if not no_start:
        startup = _ensure_runtime(host, port, timeout=30)

    code, ready = _request(base_url, "GET", "/cleanhouse/status?ready=1", timeout=2)
    if code != 200 or ready.get("ready") is not True:
        raise RuntimeError(f"readiness failed HTTP {code}: {ready}")
    dashboard_code, dashboard_text = _request_text(base_url, "/dashboard", timeout=5)
    if dashboard_code != 200 or "operator-workstation" not in dashboard_text:
        raise RuntimeError(f"dashboard failed HTTP {dashboard_code}")

    login_report = _post_login_report(base_url)
    notification_probe = _create_notification_probe(base_url)

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        runtime_code, runtime = _request(base_url, "GET", "/cleanhouse/runtime", timeout=5)
        reports_code, reports = _request(base_url, "GET", "/cleanhouse/reports?report_type=login_summary&limit=6&summary_only=1", timeout=5)
        samples.append({
            "runtime_http_status": runtime_code,
            "reports_http_status": reports_code,
            "runtime_state": runtime.get("runtime_state"),
            "reason_codes": runtime.get("reason_codes", []),
            "report_count": reports.get("count"),
        })
        if runtime_code != 200 or reports_code != 200:
            break
        time.sleep(min(5.0, max(0.5, duration_seconds / 12.0)))

    status_code, status = _request(base_url, "GET", "/cleanhouse/status?refresh=1", timeout=20)
    runtime_code, runtime = _request(base_url, "GET", "/cleanhouse/runtime", timeout=10)
    reports_code, reports = _request(base_url, "GET", "/cleanhouse/reports?report_type=login_summary&limit=6&summary_only=1", timeout=10)

    report_id = str(login_report.get("id") or "")
    report_visible = any(isinstance(item, dict) and item.get("id") == report_id for item in reports.get("reports", []))
    receipt = login_report.get("receipt", {}) if isinstance(login_report.get("receipt"), dict) else {}
    integrity = login_report.get("integrity", {}) if isinstance(login_report.get("integrity"), dict) else receipt.get("integrity", {})
    listener = runtime.get("listener", {}) if isinstance(runtime.get("listener"), dict) else {}
    notifications = runtime.get("notifications", {}) if isinstance(runtime.get("notifications"), dict) else {}
    checks = {
        "status_endpoint_ok": status_code == 200,
        "runtime_endpoint_ok": runtime_code == 200,
        "reports_endpoint_ok": reports_code == 200,
        "runtime_healthy": runtime.get("runtime_state") == "healthy",
        "backend_alive": runtime.get("backend", {}).get("alive") is True,
        "interpreter_metadata_present": bool(runtime.get("interpreter", {}).get("status")),
        "no_foreign_listeners": not listener.get("foreign_pids"),
        "no_stale_pid": runtime.get("runtime_state") != "stale_pid",
        "no_orphaned_listener": runtime.get("runtime_state") != "orphaned_listener",
        "login_report_visible": bool(report_id and report_visible),
        "receipt_integrity_present": bool(integrity.get("root_hash")),
        "notification_delivery_recorded": int(notifications.get("delivery_count", 0) or 0) >= 1,
        "notifications_not_degraded": notifications.get("status") == "ok",
    }
    result = {
        "status": "ok" if all(checks.values()) else "failed",
        "base_url": base_url,
        "duration_seconds": duration_seconds,
        "startup": startup,
        "login_report_id": report_id,
        "notification_probe": notification_probe,
        "final_runtime": runtime,
        "final_status": status,
        "final_reports": reports,
        "samples": samples,
        "checks": checks,
        "operator_verification": {
            "method": "http-api",
            "no_browser_automation": True,
            "browser_automation_used": False,
        },
    }
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "runtime_stabilization_soak.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    if stop_after:
        result["stop_after"] = _stop_runtime(host, port)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--duration-hours", type=float, default=0.0)
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--stop-after", action="store_true")
    parser.add_argument("--artifact-dir", default="")
    args = parser.parse_args()
    duration = args.duration_hours * 3600 if args.duration_hours else args.duration_seconds
    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
    try:
        result = run_soak(
            host=args.host,
            port=args.port,
            duration_seconds=duration,
            no_start=args.no_start,
            stop_after=args.stop_after,
            artifact_dir=artifact_dir,
        )
    except Exception as exc:
        result = {
            "status": "blocked",
            "blocker": str(exc),
            "operator_verification": {
                "method": "http-api",
                "no_browser_automation": True,
                "browser_automation_used": False,
            },
        }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
