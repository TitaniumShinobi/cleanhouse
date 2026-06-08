#!/usr/bin/env python3
"""No-browser CleanHouse production-readiness proving run."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate_a_runtime_smoke import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_DASHBOARD_BUDGET_MS,
    DEFAULT_FULL_STATUS_BUDGET_MS,
    DEFAULT_READINESS_BUDGET_MS,
    _check_dependencies,
    _default_python,
    _free_port,
    _port_open,
    _request,
    _start_server,
    _stop_server,
    _tail,
    _wait_for_runtime,
)


DEFAULT_WORKLOAD_SECONDS = 2.0
DEFAULT_WORKLOAD_ITERATIONS = 5
PROVING_READINESS_P95_BUDGET_MS = 250.0
DEFAULT_THRESHOLDS = {
    "startup_seconds": 20.0,
    "workload_seconds": 10.0,
    "receipt_seconds": 5.0,
    "bundle_seconds": 5.0,
    "restart_seconds": 20.0,
    "total_seconds": 60.0,
    "api_max_seconds": 5.0,
}


@dataclass
class TimedHttpClient:
    base_url: str
    calls: list[dict[str, Any]]

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        label: str = "",
    ) -> Any:
        started = time.monotonic()
        try:
            code, body, _headers = _request(self.base_url, method, path, payload)
            decoded = body.decode("utf-8", errors="replace")
            response = json.loads(decoded or "{}")
            if code >= 400:
                raise RuntimeError(f"{method} {path} failed with HTTP {code}: {response}")
        except Exception as exc:
            duration = round(time.monotonic() - started, 3)
            self.calls.append({
                "method": method,
                "path": path,
                "label": label or path,
                "duration_seconds": duration,
                "status": "error",
                "error": str(exc),
            })
            raise
        duration = round(time.monotonic() - started, 3)
        response_status = response.get("status") if isinstance(response, dict) else ""
        self.calls.append({
            "method": method,
            "path": path,
            "label": label or path,
            "duration_seconds": duration,
            "status": "ok",
            "response_status": response_status,
        })
        return response

    def max_duration(self) -> float:
        if not self.calls:
            return 0.0
        return max(float(call.get("duration_seconds", 0.0)) for call in self.calls)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _terminate_process(process: subprocess.Popen | None) -> int | None:
    if process is None:
        return None
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return process.returncode


def _wait_for_file(path: Path, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def _wait_for_port_closed(host: str, port: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _port_open(host, port):
            return True
        time.sleep(0.1)
    return not _port_open(host, port)


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return round(ordered[min(rank - 1, len(ordered) - 1)], 3)


def _readiness_sample(label: str, startup: dict[str, Any]) -> dict[str, Any]:
    performance = startup.get("performance", {}) if isinstance(startup, dict) else {}
    raw_readiness_ms = performance.get("readiness_ms")
    try:
        readiness_ms = round(float(raw_readiness_ms), 3)
    except (TypeError, ValueError):
        readiness_ms = None
    status_separation = startup.get("status_separation", {}) if isinstance(startup, dict) else {}
    return {
        "label": label,
        "status": startup.get("status") if isinstance(startup, dict) else "unknown",
        "readiness_ms": readiness_ms,
        "status_separation": status_separation.get("status") if isinstance(status_separation, dict) else "unknown",
        "low_overhead": startup.get("low_overhead", {}).get("status") if isinstance(startup, dict) else "unknown",
    }


def _readiness_measurement_report(
    samples: list[dict[str, Any]],
    *,
    readiness_budget_ms: float,
) -> dict[str, Any]:
    values = [
        float(sample["readiness_ms"])
        for sample in samples
        if sample.get("readiness_ms") is not None
    ]
    p95_ms = _nearest_rank_percentile(values, 95.0)
    max_ms = round(max(values), 3) if values else 0.0
    status_separation_ok = all(
        sample.get("status_separation") in {"ok", "skipped", None}
        for sample in samples
    )
    p95_under_budget = bool(values) and p95_ms <= float(readiness_budget_ms)
    return {
        "status": "ok" if values and p95_under_budget and status_separation_ok else "failed",
        "sample_count": len(values),
        "samples": samples,
        "p95_ms": p95_ms,
        "max_ms": max_ms,
        "budget_ms": float(readiness_budget_ms),
        "p95_under_budget": p95_under_budget,
        "status_separation_ok": status_separation_ok,
        "method": "nearest-rank",
    }


def _restart_schedule(duration_seconds: float, restart_interval_seconds: float) -> list[float]:
    if duration_seconds <= 0 or restart_interval_seconds <= 0:
        return [0.0]
    scheduled: list[float] = []
    next_restart_after = min(float(restart_interval_seconds), float(duration_seconds))
    while next_restart_after <= float(duration_seconds) + 0.000001:
        scheduled.append(round(next_restart_after, 3))
        next_restart_after += float(restart_interval_seconds)
    return scheduled or [round(float(duration_seconds), 3)]


def _start_background_writer(
    *,
    python_exe: str,
    workspace: Path,
    duration_seconds: float,
    interval_seconds: float = 0.15,
) -> subprocess.Popen:
    target = workspace / "background" / "heartbeat.txt"
    code = """
import pathlib
import sys
import time

target = pathlib.Path(sys.argv[1])
duration = float(sys.argv[2])
interval = max(float(sys.argv[3]), 0.05)
target.parent.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + duration
index = 0
while time.monotonic() < deadline:
    target.write_text(f"heartbeat {index}\\n", encoding="utf-8")
    index += 1
    time.sleep(interval)
target.write_text(f"complete {index}\\n", encoding="utf-8")
"""
    return subprocess.Popen(
        [
            python_exe,
            "-c",
            code,
            str(target),
            str(duration_seconds),
            str(interval_seconds),
            "codex-agentic-background-service",
        ],
        cwd=str(workspace),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _start_loopback_server(
    *,
    python_exe: str,
    host: str,
    port: int,
    marker_path: Path,
    duration_seconds: float,
) -> subprocess.Popen:
    code = """
import pathlib
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
marker = pathlib.Path(sys.argv[3])
duration = float(sys.argv[4])
marker.parent.mkdir(parents=True, exist_ok=True)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((host, port))
sock.listen(8)
sock.settimeout(0.2)
marker.write_text("ready\\n", encoding="utf-8")
deadline = time.monotonic() + duration
while time.monotonic() < deadline:
    try:
        conn, _addr = sock.accept()
    except TimeoutError:
        continue
    with conn:
        conn.recv(1024)
        conn.sendall(b"cleanhouse-proving-run-ok")
sock.close()
"""
    return subprocess.Popen(
        [
            python_exe,
            "-c",
            code,
            host,
            str(port),
            str(marker_path),
            str(duration_seconds),
            "cleanhouse-loopback-port-network-service",
        ],
        cwd=str(marker_path.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def prepare_workload_workspace(workspace: Path) -> dict[str, str]:
    workspace.mkdir(parents=True, exist_ok=True)
    paths = {
        "scope_file": "scope/owned.txt",
        "outside_file": "outside/drift.txt",
        "sync_source": "sync/source/shared.txt",
        "sync_mirror": "sync/mirror/shared.txt",
        "background_file": "background/heartbeat.txt",
        "developer_command_file": "background/developer-command.txt",
    }
    (workspace / "scope").mkdir(parents=True, exist_ok=True)
    (workspace / "outside").mkdir(parents=True, exist_ok=True)
    (workspace / "sync" / "source").mkdir(parents=True, exist_ok=True)
    (workspace / "sync" / "mirror").mkdir(parents=True, exist_ok=True)
    (workspace / "background").mkdir(parents=True, exist_ok=True)
    (workspace / paths["scope_file"]).write_text("before\n", encoding="utf-8")
    (workspace / paths["sync_source"]).write_text("sync-before\n", encoding="utf-8")
    (workspace / paths["sync_mirror"]).write_text("sync-before\n", encoding="utf-8")
    return paths


def _loopback_round_trip(host: str, port: int, payload: bytes = b"cleanhouse") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0) as conn:
            conn.sendall(payload)
            return conn.recv(1024) == b"cleanhouse-proving-run-ok"
    except OSError:
        return False


def run_condition_workload(
    *,
    workspace: Path,
    python_exe: str,
    host: str,
    duration_seconds: float,
    iterations: int,
) -> dict[str, Any]:
    started = time.monotonic()
    paths = prepare_workload_workspace(workspace)
    requested_duration = max(float(duration_seconds), 0.01)
    requested_iterations = max(int(iterations), 1)
    sleep_interval = max(0.01, requested_duration / requested_iterations)
    background_interval = min(max(sleep_interval, 0.15), 5.0)
    loopback_port = _free_port(host)
    marker_path = workspace / "background" / "loopback-ready.txt"
    background = _start_background_writer(
        python_exe=python_exe,
        workspace=workspace,
        duration_seconds=max(requested_duration, 1.0),
        interval_seconds=background_interval,
    )
    loopback = _start_loopback_server(
        python_exe=python_exe,
        host=host,
        port=loopback_port,
        marker_path=marker_path,
        duration_seconds=max(requested_duration, 1.0) + 2.0,
    )
    marker_ready = _wait_for_file(marker_path, timeout_seconds=5.0)
    port_ready = marker_ready and _port_open(host, loopback_port)
    developer_command = subprocess.run(
        [
            python_exe,
            "-c",
            "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('developer command observed\\n', encoding='utf-8')",
            str(workspace / paths["developer_command_file"]),
            "codex-agentic-developer-command",
        ],
        cwd=str(workspace),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    network_successes = 0
    mutation_count = 0
    try:
        for index in range(requested_iterations):
            (workspace / paths["scope_file"]).write_text(f"owned iteration {index}\n", encoding="utf-8")
            (workspace / paths["outside_file"]).write_text(f"outside drift {index}\n", encoding="utf-8")
            source = workspace / paths["sync_source"]
            mirror = workspace / paths["sync_mirror"]
            source.write_text(f"sync iteration {index}\n", encoding="utf-8")
            shutil.copyfile(source, mirror)
            (workspace / "background" / f"pulse-{index}.txt").write_text(
                f"pulse {index}\n",
                encoding="utf-8",
            )
            mutation_count += 5
            if _loopback_round_trip(host, loopback_port, f"iteration {index}".encode("utf-8")):
                network_successes += 1
            time.sleep(sleep_interval)
    finally:
        background_returncode = _terminate_process(background)
        loopback_returncode = _terminate_process(loopback)

    elapsed = round(time.monotonic() - started, 3)
    source_text = (workspace / paths["sync_source"]).read_text(encoding="utf-8")
    mirror_text = (workspace / paths["sync_mirror"]).read_text(encoding="utf-8")
    checks = {
        "filesystem_mutations_created": mutation_count >= requested_iterations * 5,
        "background_process_started": background.pid is not None,
        "background_process_cleaned_up": background_returncode in {0, -15, -9},
        "developer_agentic_command_exit_zero": developer_command.returncode == 0,
        "loopback_port_opened": port_ready,
        "loopback_network_round_trips": network_successes == requested_iterations,
        "sync_like_mirror_updated": source_text == mirror_text and source_text.startswith("sync iteration"),
    }
    return {
        "status": "ok" if all(checks.values()) else "failed",
        "duration_seconds": elapsed,
        "requested_duration_seconds": round(requested_duration, 3),
        "iterations": requested_iterations,
        "background_interval_seconds": round(background_interval, 3),
        "checks": checks,
        "paths": paths,
        "mutation_count": mutation_count,
        "background_process": {
            "pid": background.pid,
            "returncode": background_returncode,
            "heartbeat_exists": (workspace / paths["background_file"]).exists(),
        },
        "developer_agentic_process": {
            "returncode": developer_command.returncode,
            "artifact": paths["developer_command_file"],
        },
        "port_network": {
            "host": host,
            "port": loopback_port,
            "port_ready": port_ready,
            "round_trips": network_successes,
        },
        "sync_like": {
            "source": paths["sync_source"],
            "mirror": paths["sync_mirror"],
            "native_provider_claimed": False,
        },
    }


def _workload_iterations_for_duration(duration_seconds: float, requested_iterations: int) -> int:
    iterations = max(int(requested_iterations), 1)
    if duration_seconds <= 30 or iterations != DEFAULT_WORKLOAD_ITERATIONS:
        return iterations
    return max(iterations, min(720, int(math.ceil(float(duration_seconds) / 5.0))))


def build_unsupported_claim_gaps() -> list[dict[str, Any]]:
    return [
        {
            "claim": "universal_filesystem_coverage",
            "status": "gap",
            "evidence_level": "unknown",
            "reason": "The proving run mutates and watches its controlled local workspace; it does not prove OS-wide file mutation coverage outside configured roots.",
            "required_native_capability": "system-wide file event authorization and durable root coverage",
        },
        {
            "claim": "native_process_lineage",
            "status": "gap",
            "evidence_level": "unknown",
            "reason": "The run starts owned subprocesses and records process evidence; it does not prove kernel-level PID/PPID lineage for unrelated processes.",
            "required_native_capability": "native process audit lineage or equivalent OS event stream",
        },
        {
            "claim": "native_network_packet_or_dns_capture",
            "status": "gap",
            "evidence_level": "unknown",
            "reason": "The run opens a loopback port and performs local network round trips; it does not prove native packet capture, DNS capture, or all-process network attribution.",
            "required_native_capability": "native network extension, packet capture, or system flow attribution",
        },
        {
            "claim": "native_cloud_sync_provider_state",
            "status": "gap",
            "evidence_level": "unknown",
            "reason": "The run performs deterministic sync-like local mirroring; it does not inspect iCloud, Dropbox, Google Drive, or other native sync provider state.",
            "required_native_capability": "provider-specific sync status APIs or filesystem extension evidence",
        },
        {
            "claim": "universal_background_service_correlation",
            "status": "gap",
            "evidence_level": "unknown",
            "reason": "The run correlates harness-owned background services; it does not claim universal correlation for arbitrary launch agents, daemons, or external editors.",
            "required_native_capability": "system service inventory plus event correlation for non-owned processes",
        },
    ]


def evaluate_performance(
    measurements: dict[str, float],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for key, threshold in thresholds.items():
        value = round(float(measurements.get(key, 0.0)), 3)
        passed = value <= float(threshold)
        rows[key] = {
            "value": value,
            "threshold": float(threshold),
            "status": "pass" if passed else "fail",
        }
        if not passed:
            failures.append(f"{key} {value}s exceeded {float(threshold)}s")
    return {
        "status": "pass" if not failures else "fail",
        "measurements": rows,
        "failures": failures,
    }


def _bundle_verification_ok(verification: dict[str, Any]) -> bool:
    return all(
        verification.get(key) is True
        for key in (
            "bundle_hash_match",
            "manifest_hash_match",
            "timeline_hash_match",
            "replay_hash_match",
            "signature_verified",
        )
    )


def _changed_paths(diff: dict[str, Any], receipt: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for item in diff.get("changes", []):
        if isinstance(item, dict):
            value = item.get("path")
        else:
            value = item
        if value:
            paths.add(str(value))
    for item in receipt.get("scope_analysis", {}).get("changed_paths", []):
        if item:
            paths.add(str(item))
    return paths


def _restart_artifact_checks(
    *,
    client: TimedHttpClient,
    session_id: str,
    receipt_id: str,
) -> dict[str, Any]:
    receipt_qs = urllib.parse.urlencode({"receipt_id": receipt_id})
    session_qs = urllib.parse.urlencode({"session_id": session_id})
    replay = client.request("GET", f"/cleanhouse/receipt-replay?{receipt_qs}", label="restart-replay")
    bundle = client.request("GET", f"/cleanhouse/receipt-bundle?{receipt_qs}", label="restart-bundle")
    imported = client.request(
        "POST",
        "/cleanhouse/receipt-bundle/import",
        {"bundle": bundle.get("bundle", {})},
        label="restart-bundle-import",
    )
    workstation = client.request("GET", f"/cleanhouse/workstation?{session_qs}", label="restart-workstation")
    receipts = client.request("GET", f"/cleanhouse/receipts?{session_qs}", label="restart-receipts")
    verification = bundle.get("verification", {}) if isinstance(bundle, dict) else {}
    import_verification = imported.get("verification", {}) if isinstance(imported, dict) else {}
    checks = {
        "receipt_replay_loaded_after_restart": replay.get("status") == "ok",
        "receipt_bundle_loaded_after_restart": bundle.get("status") == "ok",
        "receipt_bundle_imported_after_restart": imported.get("status") == "ok",
        "receipt_bundle_signature_verified_after_restart": _bundle_verification_ok(verification),
        "receipt_bundle_import_signature_verified_after_restart": _bundle_verification_ok(import_verification),
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


def _run_restart_orchestration(
    *,
    process: subprocess.Popen | None,
    client: TimedHttpClient,
    active: dict[str, Any],
    python_exe: str,
    host: str,
    port: int,
    base_url: str,
    workspace: Path,
    home_dir: Path,
    watch_dir: Path,
    log_dir: Path,
    timeout_seconds: float,
    workload_iterations: int,
    duration_seconds: float,
    restart_interval_seconds: float,
) -> tuple[subprocess.Popen | None, dict[str, Any], dict[str, Any]]:
    schedule = _restart_schedule(duration_seconds, restart_interval_seconds)
    cycles: list[dict[str, Any]] = []
    orchestration_started = time.monotonic()
    current_process = process
    last_artifact: dict[str, Any] = {
        "status": "skipped",
        "reason": "restart cycle did not run",
    }

    for index, scheduled_after in enumerate(schedule, start=1):
        sleep_until = orchestration_started + float(scheduled_after)
        sleep_seconds = max(0.0, sleep_until - time.monotonic())
        continuous_workload: dict[str, Any] = {
            "status": "skipped",
            "reason": "no wait window before restart",
            "duration_seconds": 0.0,
        }
        if sleep_seconds:
            continuous_iterations = _workload_iterations_for_duration(sleep_seconds, workload_iterations)
            continuous_workload = run_condition_workload(
                workspace=workspace / "continuous" / f"cycle-{index}",
                python_exe=python_exe,
                host=host,
                duration_seconds=sleep_seconds,
                iterations=continuous_iterations,
            )

        cycle_started = time.monotonic()
        _stop_server(current_process)
        current_process = None
        if not _wait_for_port_closed(host, port, timeout_seconds=5.0):
            blocker = f"port did not release before restart: {host}:{port}"
            cycle = {
                "cycle": index,
                "status": "blocked",
                "blocker": blocker,
                "scheduled_after_seconds": float(scheduled_after),
                "sleep_seconds": round(sleep_seconds, 3),
                "continuous_workload": continuous_workload,
                "duration_seconds": round(time.monotonic() - cycle_started, 3),
            }
            cycles.append(cycle)
            blocked_artifact = {
                "status": "blocked",
                "reason": blocker,
            }
            orchestration = {
                "status": "blocked",
                "blocker": blocker,
                "mode": "duration" if duration_seconds > 0 else "single",
                "duration_seconds": float(duration_seconds),
                "restart_interval_seconds": float(restart_interval_seconds),
                "scheduled_restart_count": len(schedule),
                "attempted_restart_count": len(cycles),
                "restart_count": 0,
                "successful_restart_count": 0,
                "cycles": cycles,
                "max_cycle_seconds": 0.0,
                "total_cycle_seconds": round(time.monotonic() - orchestration_started, 3),
                "status_separation_ok": False,
            }
            return current_process, orchestration, blocked_artifact

        restart_log_path = log_dir / ("server-restart.log" if index == 1 else f"server-restart-{index}.log")
        current_process = _start_server(
            python_exe=python_exe,
            host=host,
            port=port,
            home_dir=home_dir,
            workspace_dir=watch_dir,
            log_path=restart_log_path,
        )
        restart_startup = _wait_for_runtime(
            base_url=base_url,
            process=current_process,
            log_path=restart_log_path,
            timeout_seconds=timeout_seconds,
            readiness_budget_ms=PROVING_READINESS_P95_BUDGET_MS,
            dashboard_budget_ms=DEFAULT_DASHBOARD_BUDGET_MS,
            full_status_budget_ms=DEFAULT_FULL_STATUS_BUDGET_MS,
        )
        last_artifact = _restart_artifact_checks(
            client=client,
            session_id=active["session_id"],
            receipt_id=active["receipt"]["id"],
        )
        continuous_ok = continuous_workload.get("status") in {"ok", "skipped"}
        cycle_status = (
            "ok"
            if restart_startup.get("status") == "ok" and last_artifact.get("status") == "ok" and continuous_ok
            else "failed"
        )
        cycle = {
            "cycle": index,
            "status": cycle_status,
            "scheduled_after_seconds": float(scheduled_after),
            "sleep_seconds": round(sleep_seconds, 3),
            "duration_seconds": round(time.monotonic() - cycle_started, 3),
            "continuous_workload": continuous_workload,
            "startup": restart_startup,
            "artifact_retrieval": last_artifact,
            "readiness_ms": restart_startup.get("performance", {}).get("readiness_ms"),
            "status_separation": restart_startup.get("status_separation", {}).get("status"),
        }
        cycles.append(cycle)
        if cycle_status != "ok":
            break

    successful_restart_count = sum(1 for cycle in cycles if cycle.get("status") == "ok")
    status_separation_ok = all(
        cycle.get("status_separation") in {"ok", "skipped", None}
        for cycle in cycles
        if cycle.get("status") != "blocked"
    )
    max_cycle_seconds = max((float(cycle.get("duration_seconds", 0.0)) for cycle in cycles), default=0.0)
    workload_statuses = [
        cycle.get("continuous_workload", {}).get("status")
        for cycle in cycles
        if isinstance(cycle.get("continuous_workload"), dict)
    ]
    continuous_workload_ok = bool(workload_statuses) and all(status in {"ok", "skipped"} for status in workload_statuses)
    orchestration_status = "ok" if cycles and successful_restart_count == len(schedule) else "failed"
    orchestration = {
        "status": orchestration_status,
        "mode": "duration" if duration_seconds > 0 else "single",
        "duration_seconds": float(duration_seconds),
        "restart_interval_seconds": float(restart_interval_seconds),
        "scheduled_restart_count": len(schedule),
        "attempted_restart_count": len(cycles),
        "restart_count": len(cycles),
        "successful_restart_count": successful_restart_count,
        "cycles": cycles,
        "max_cycle_seconds": round(max_cycle_seconds, 3),
        "total_cycle_seconds": round(time.monotonic() - orchestration_started, 3),
        "status_separation_ok": status_separation_ok,
        "continuous_workload_ok": continuous_workload_ok,
    }
    return current_process, orchestration, last_artifact


def _run_receipt_spine(
    *,
    client: TimedHttpClient,
    workspace: Path,
    python_exe: str,
    host: str,
    workload: dict[str, Any],
) -> dict[str, Any]:
    session_id = f"prod-ready-{uuid.uuid4().hex[:12]}"
    objective_id = f"objective-{session_id}"
    prepare_workload_workspace(workspace)
    prompt = client.request(
        "POST",
        "/cleanhouse/prompt",
        {
            "text": "CleanHouse production readiness proving run",
            "context": (
                "No-browser proving run covering local workload, agentic filesystem/process/"
                "port/network/sync-like/background conditions, approvals, rollback, replay, "
                "signed bundle import, restart, and performance thresholds."
            ),
            "scope": "scope/",
            "repo_path": str(workspace),
            "tool_identity": "codex",
            "session_id": session_id,
            "objective_id": objective_id,
        },
        label="prompt",
    )
    session = client.request(
        "POST",
        "/cleanhouse/session/start",
        {
            "session_id": session_id,
            "objective_id": objective_id,
            "summary": "production-readiness proving run",
            "metadata": {"harness": "production_readiness_proving_run"},
        },
        label="session-start",
    )
    client.request(
        "POST",
        "/cleanhouse/objective/start",
        {
            "session_id": session_id,
            "objective_id": objective_id,
            "objective": "prove local runtime accountability without browser automation",
        },
        label="objective-start",
    )
    before = client.request(
        "POST",
        "/cleanhouse/snapshot",
        {"repo_path": str(workspace), "label": "before-workload", "session_id": session_id},
        label="snapshot-before",
    )
    workload_result = run_condition_workload(
        workspace=workspace,
        python_exe=python_exe,
        host=host,
        duration_seconds=float(workload["duration_seconds"]),
        iterations=int(workload["iterations"]),
    )
    tool_event = client.request(
        "POST",
        "/cleanhouse/tool-event",
        {
            "tool_identity": "codex",
            "command": "production-readiness-proving-run",
            "args": [
                "production-readiness-proving-run",
                "--no-browser",
                "--filesystem-process-port-network-sync-background",
            ],
            "exit_code": 0 if workload_result.get("status") == "ok" else 1,
            "cwd": str(workspace),
            "session_id": session_id,
            "objective_id": objective_id,
            "duration": workload_result.get("duration_seconds"),
        },
        label="tool-event",
    )
    after = client.request(
        "POST",
        "/cleanhouse/snapshot",
        {"repo_path": str(workspace), "label": "after-workload", "session_id": session_id},
        label="snapshot-after",
    )
    diff = client.request(
        "POST",
        "/cleanhouse/diff",
        {"before_id": before.get("id"), "after_id": after.get("id"), "session_id": session_id},
        label="diff",
    )

    client.request("POST", "/cleanhouse/correlate", {"session_id": session_id}, label="correlate")
    timeline = client.request("POST", "/cleanhouse/timeline", {"session_id": session_id}, label="timeline")
    client.request("POST", "/cleanhouse/classify", {"session_id": session_id}, label="classify")
    alerts = client.request("POST", "/cleanhouse/alerts", {"session_id": session_id}, label="alerts")
    receipt_started = time.monotonic()
    receipt = client.request("POST", "/cleanhouse/receipt", {"session_id": session_id}, label="receipt")
    receipt_seconds = time.monotonic() - receipt_started
    receipt_id = str(receipt.get("id") or "")

    drift_approval = client.request(
        "POST",
        "/cleanhouse/approval-queue",
        {
            "session_id": session_id,
            "requested_action": "reject out-of-scope proving-run drift",
            "reason": "proving run intentionally mutated outside/ to verify visible scope gap handling",
            "prompt_id": prompt.get("id"),
            "objective_id": objective_id,
            "evidence_refs": [
                f"local://cleanhouse/diff/{diff.get('id', '')}",
                f"local://cleanhouse/receipt/{receipt_id}",
            ],
            "reviewer": "production_readiness_proving_run",
            "metadata": {"receipt_id": receipt_id, "policy_id": "proving_run_out_of_scope"},
        },
        label="approval-drift-create",
    )
    drift_approval_id = drift_approval.get("approval", {}).get("id", "")
    drift_resolution = client.request(
        "POST",
        f"/cleanhouse/approval-queue/{urllib.parse.quote(drift_approval_id, safe='')}",
        {
            "status": "rejected",
            "note": "intentional out-of-scope mutation rejected by no-browser proving run",
            "reviewer": "production_readiness_proving_run",
        },
        label="approval-drift-resolve",
    ) if drift_approval_id else {"status": "blocked", "message": "drift approval id missing"}

    replay = client.request(
        "GET",
        "/cleanhouse/receipt-replay?" + urllib.parse.urlencode({"receipt_id": receipt_id}),
        label="receipt-replay",
    )
    bundle_started = time.monotonic()
    bundle = client.request(
        "GET",
        "/cleanhouse/receipt-bundle?" + urllib.parse.urlencode({"receipt_id": receipt_id}),
        label="receipt-bundle",
    )
    imported = client.request(
        "POST",
        "/cleanhouse/receipt-bundle/import",
        {"bundle": bundle.get("bundle", {})},
        label="receipt-bundle-import",
    )
    bundle_seconds = time.monotonic() - bundle_started
    rollback_request = client.request(
        "POST",
        "/cleanhouse/rollback/request",
        {
            "session_id": session_id,
            "objective_id": objective_id,
            "receipt_id": receipt_id,
            "snapshot_id": before.get("id"),
            "path": "scope/owned.txt",
            "repo_path": str(workspace),
            "evidence_refs": [
                f"local://cleanhouse/diff/{diff.get('id', '')}",
                f"local://cleanhouse/receipt/{receipt_id}",
            ],
            "metadata": {"harness": "production_readiness_proving_run", "receipt_id": receipt_id},
        },
        label="rollback-request",
    )
    rollback_id = rollback_request.get("rollback", {}).get("id")
    rollback_execute = client.request(
        "POST",
        "/cleanhouse/rollback/execute",
        {"rollback_id": rollback_id, "repo_path": str(workspace)},
        label="rollback-execute",
    ) if rollback_id else {"status": "blocked", "message": "rollback id missing"}
    rollback_file_restored = (workspace / "scope" / "owned.txt").read_text(encoding="utf-8") == "before\n"
    rollback_approval = client.request(
        "POST",
        "/cleanhouse/approval-queue",
        {
            "session_id": session_id,
            "requested_action": "approve verified rollback evidence",
            "reason": "rollback restored the in-scope file to the before snapshot hash",
            "prompt_id": prompt.get("id"),
            "objective_id": objective_id,
            "evidence_refs": [
                f"local://cleanhouse/receipt/{receipt_id}",
                f"local://cleanhouse/rollback/{rollback_id}",
            ],
            "reviewer": "production_readiness_proving_run",
            "metadata": {"receipt_id": receipt_id, "policy_id": "proving_run_rollback"},
        },
        label="approval-rollback-create",
    )
    rollback_approval_id = rollback_approval.get("approval", {}).get("id", "")
    rollback_resolution = client.request(
        "POST",
        f"/cleanhouse/approval-queue/{urllib.parse.quote(rollback_approval_id, safe='')}",
        {
            "status": "approved",
            "note": "rollback verification accepted by no-browser proving run",
            "reviewer": "production_readiness_proving_run",
        },
        label="approval-rollback-resolve",
    ) if rollback_approval_id else {"status": "blocked", "message": "rollback approval id missing"}
    client.request(
        "POST",
        "/cleanhouse/objective/end",
        {
            "session_id": session_id,
            "objective_id": objective_id,
            "summary": "production-readiness proving run complete",
        },
        label="objective-end",
    )
    event_rows: list[dict[str, Any]] = []
    for _ in range(10):
        events = client.request(
            "GET",
            "/events?" + urllib.parse.urlencode({"session_id": session_id, "limit": 250}),
            label="events",
        )
        if isinstance(events, list):
            event_rows = events
        if event_rows:
            break
        time.sleep(0.1)

    paths = _changed_paths(diff, receipt)
    expected_paths = {
        "scope/owned.txt",
        "outside/drift.txt",
        "sync/source/shared.txt",
        "sync/mirror/shared.txt",
        "background/heartbeat.txt",
        "background/developer-command.txt",
    }
    bundle_verification = bundle.get("verification", {}) if isinstance(bundle, dict) else {}
    import_verification = imported.get("verification", {}) if isinstance(imported, dict) else {}
    checks = {
        "prompt_session_objective_visible": prompt.get("status") == "ok" and session.get("status") == "ok",
        "workload_conditions_ok": workload_result.get("status") == "ok",
        "expected_changed_paths_visible": expected_paths.issubset(paths),
        "timeline_visible": timeline.get("entry_count", 0) > 0,
        "events_visible": len(event_rows) > 0,
        "scope_gap_visible": receipt.get("scope_analysis", {}).get("out_of_scope_count", 0) > 0,
        "alerts_visible": len(alerts.get("alerts", [])) > 0,
        "rollback_executed_verified": rollback_execute.get("rollback", {}).get("status") == "executed_verified",
        "rollback_file_restored": rollback_file_restored,
        "drift_approval_rejected": drift_resolution.get("approval", {}).get("status") == "rejected",
        "rollback_approval_approved": rollback_resolution.get("approval", {}).get("status") == "approved",
        "receipt_root_hash_visible": bool(receipt.get("integrity", {}).get("root_hash")),
        "replay_hash_visible": bool(replay.get("integrity", {}).get("replay_hash")),
        "bundle_export_signature_verified": _bundle_verification_ok(bundle_verification),
        "bundle_import_signature_verified": _bundle_verification_ok(import_verification),
    }
    return {
        "status": "ok" if all(checks.values()) else "failed",
        "session_id": session_id,
        "objective_id": objective_id,
        "checks": checks,
        "workload": workload_result,
        "counts": {
            "events": len(event_rows),
            "timeline_entries": timeline.get("entry_count", 0),
            "alerts": len(alerts.get("alerts", [])),
            "changed_paths": len(paths),
            "api_calls": len(client.calls),
        },
        "changed_paths": sorted(paths),
        "missing_expected_paths": sorted(expected_paths - paths),
        "rollback": rollback_execute.get("rollback", rollback_execute),
        "approvals": {
            "drift": drift_resolution.get("approval", drift_resolution),
            "rollback": rollback_resolution.get("approval", rollback_resolution),
        },
        "receipt": {
            "id": receipt_id,
            "root_hash": receipt.get("integrity", {}).get("root_hash"),
            "scope_classification": receipt.get("scope_analysis", {}).get("classification"),
            "scope_weight": receipt.get("scope_analysis", {}).get("scope_weight"),
            "gap_count": len(receipt.get("gaps", [])),
        },
        "replay": {
            "status": replay.get("status"),
            "replay_hash": replay.get("integrity", {}).get("replay_hash"),
        },
        "bundle": {
            "status": bundle.get("status"),
            "bundle_hash": bundle.get("bundle", {}).get("integrity", {}).get("bundle_hash"),
            "signature_verified": bundle_verification.get("signature_verified"),
            "import_status": imported.get("status"),
            "import_signature_verified": import_verification.get("signature_verified"),
        },
        "timings": {
            "receipt_seconds": round(receipt_seconds, 3),
            "bundle_seconds": round(bundle_seconds, 3),
        },
        "bundle_payload": bundle.get("bundle", {}),
    }


def run_production_readiness_proving_run(
    *,
    base_url: str,
    python_exe: str,
    host: str,
    port: int,
    no_start: bool,
    keep_running: bool,
    timeout_seconds: float,
    workload_seconds: float,
    workload_iterations: int,
    duration_seconds: float,
    restart_interval_seconds: float,
    thresholds: dict[str, float],
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    total_started = time.monotonic()
    dependencies = _check_dependencies(python_exe)
    if dependencies.get("missing_required"):
        result = {
            "schema": "cleanhouse.production_readiness_proving_run.v1",
            "status": "blocked",
            "base_url": base_url,
            "blocker": "missing required runtime dependencies",
            "dependencies": dependencies,
            "no_browser_automation": True,
            "browser_automation_used": False,
            "unsupported_claim_gaps": build_unsupported_claim_gaps(),
        }
        if artifact_dir:
            _write_json(artifact_dir / "production_readiness_proving_run.json", result)
        return result

    process: subprocess.Popen | None = None
    owned_process = not no_start
    client = TimedHttpClient(base_url=base_url, calls=[])
    with contextlib.ExitStack() as stack:
        home_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="prod-ready-home-"))).resolve()
        watch_dir = home_dir / "watch"
        workspace = watch_dir / "repo"
        watch_dir.mkdir(parents=True, exist_ok=True)
        log_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="prod-ready-runtime-"))).resolve()
        log_path = log_dir / "server.log"

        if owned_process:
            if _port_open(host, port):
                result = {
                    "schema": "cleanhouse.production_readiness_proving_run.v1",
                    "status": "blocked",
                    "base_url": base_url,
                    "blocker": f"port already in use: {host}:{port}",
                    "dependencies": dependencies,
                    "no_browser_automation": True,
                    "browser_automation_used": False,
                    "unsupported_claim_gaps": build_unsupported_claim_gaps(),
                }
                if artifact_dir:
                    _write_json(artifact_dir / "production_readiness_proving_run.json", result)
                return result
            process = _start_server(
                python_exe=python_exe,
                host=host,
                port=port,
                home_dir=home_dir,
                workspace_dir=watch_dir,
                log_path=log_path,
            )

        try:
            startup_started = time.monotonic()
            startup = _wait_for_runtime(
                base_url=base_url,
                process=process if owned_process else None,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
                readiness_budget_ms=PROVING_READINESS_P95_BUDGET_MS,
                dashboard_budget_ms=DEFAULT_DASHBOARD_BUDGET_MS,
                full_status_budget_ms=DEFAULT_FULL_STATUS_BUDGET_MS,
            )
            startup_seconds = time.monotonic() - startup_started
            active = _run_receipt_spine(
                client=client,
                workspace=workspace,
                python_exe=python_exe,
                host=host,
                workload={
                    "duration_seconds": workload_seconds,
                    "iterations": workload_iterations,
                },
            )

            restart_orchestration = {
                "status": "skipped",
                "reason": "runtime was not started by this harness",
                "mode": "external",
                "duration_seconds": float(duration_seconds),
                "restart_interval_seconds": float(restart_interval_seconds),
                "scheduled_restart_count": 0,
                "attempted_restart_count": 0,
                "restart_count": 0,
                "successful_restart_count": 0,
                "cycles": [],
                "max_cycle_seconds": 0.0,
                "total_cycle_seconds": 0.0,
                "status_separation_ok": True,
                "continuous_workload_ok": True,
            }
            restart = {
                "status": "skipped",
                "reason": "runtime was not started by this harness",
            }
            if owned_process:
                process, restart_orchestration, restart = _run_restart_orchestration(
                    process=process,
                    client=client,
                    active=active,
                    python_exe=python_exe,
                    host=host,
                    port=port,
                    base_url=base_url,
                    workspace=workspace,
                    home_dir=home_dir,
                    watch_dir=watch_dir,
                    log_dir=log_dir,
                    timeout_seconds=timeout_seconds,
                    workload_iterations=workload_iterations,
                    duration_seconds=duration_seconds,
                    restart_interval_seconds=restart_interval_seconds,
                )
                if restart_orchestration.get("status") == "blocked":
                    result = {
                        "schema": "cleanhouse.production_readiness_proving_run.v1",
                        "status": "blocked",
                        "base_url": base_url,
                        "blocker": restart_orchestration.get("blocker", "restart orchestration blocked"),
                        "dependencies": dependencies,
                        "log_tail": _tail(log_path),
                        "startup": {
                            **startup,
                            "duration_seconds": round(startup_seconds, 3),
                        },
                        "active_receipt_spine": {
                            key: value
                            for key, value in active.items()
                            if key != "bundle_payload"
                        },
                        "restart_orchestration": restart_orchestration,
                        "restart_artifact_retrieval": restart,
                        "no_browser_automation": True,
                        "browser_automation_used": False,
                        "unsupported_claim_gaps": build_unsupported_claim_gaps(),
                    }
                    if artifact_dir:
                        _write_json(artifact_dir / "production_readiness_proving_run.json", result)
                    return result

            total_seconds = time.monotonic() - total_started
            readiness_samples = [_readiness_sample("startup", startup)]
            for cycle in restart_orchestration.get("cycles", []):
                if isinstance(cycle, dict) and isinstance(cycle.get("startup"), dict):
                    readiness_samples.append(_readiness_sample(f"restart-{cycle.get('cycle')}", cycle["startup"]))
            readiness_measurement = _readiness_measurement_report(
                readiness_samples,
                readiness_budget_ms=PROVING_READINESS_P95_BUDGET_MS,
            )
            performance = evaluate_performance(
                {
                    "startup_seconds": startup_seconds,
                    "workload_seconds": active.get("workload", {}).get("duration_seconds", 0.0),
                    "receipt_seconds": active.get("timings", {}).get("receipt_seconds", 0.0),
                    "bundle_seconds": active.get("timings", {}).get("bundle_seconds", 0.0),
                    "restart_seconds": restart_orchestration.get("max_cycle_seconds", 0.0),
                    "total_seconds": total_seconds,
                    "api_max_seconds": client.max_duration(),
                },
                thresholds,
            )
            performance["readiness_measurement"] = readiness_measurement
            unsupported_claim_gaps = build_unsupported_claim_gaps()
            checks = {
                "startup_ready": startup.get("status") == "ok" and startup.get("status_ready") is True,
                "startup_status_separation_ok": startup.get("status_separation", {}).get("status") == "ok",
                "active_receipt_spine_ok": active.get("status") == "ok",
                "restart_orchestration_ok": restart_orchestration.get("status") == "ok" or (
                    not owned_process and restart_orchestration.get("status") == "skipped"
                ),
                "restart_status_separation_ok": restart_orchestration.get("status_separation_ok") is True,
                "continuous_workload_ok": restart_orchestration.get("continuous_workload_ok") is True,
                "restart_artifact_retrieval_ok": restart.get("status") == "ok" or (
                    not owned_process and restart.get("status") == "skipped"
                ),
                "readiness_p95_under_budget": readiness_measurement.get("p95_under_budget") is True,
                "performance_thresholds_ok": performance.get("status") == "pass",
                "unsupported_universal_native_claims_reported_as_gaps": len(unsupported_claim_gaps) >= 5,
                "no_browser_automation": True,
                "browser_automation_used": False,
            }
            passed = (
                all(value for key, value in checks.items() if not key.endswith("browser_automation_used"))
                and not checks["browser_automation_used"]
            )
            result = {
                "schema": "cleanhouse.production_readiness_proving_run.v1",
                "status": "ok" if passed else "failed",
                "base_url": base_url,
                "port": port,
                "duration_seconds": float(duration_seconds),
                "restart_interval_seconds": float(restart_interval_seconds),
                "restart_count": restart_orchestration.get("restart_count", 0),
                "dependencies": dependencies,
                "startup": {
                    **startup,
                    "duration_seconds": round(startup_seconds, 3),
                },
                "active_receipt_spine": {
                    key: value
                    for key, value in active.items()
                    if key != "bundle_payload"
                },
                "restart_orchestration": restart_orchestration,
                "restart_artifact_retrieval": restart,
                "performance": performance,
                "checks": checks,
                "api_calls": client.calls,
                "unsupported_claim_gaps": unsupported_claim_gaps,
                "operator_verification": {
                    "method": "http-api",
                    "no_browser_automation": True,
                    "browser_automation_used": False,
                },
                "remaining_risks": [
                    gap["claim"]
                    for gap in unsupported_claim_gaps
                    if gap.get("status") == "gap"
                ],
            }
            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                _write_json(artifact_dir / "production_readiness_proving_run.json", result)
                bundle_payload = active.get("bundle_payload")
                if isinstance(bundle_payload, dict) and bundle_payload:
                    _write_json(artifact_dir / "production-readiness-bundle.json", bundle_payload)
                    if isinstance(bundle_payload.get("manifest"), dict):
                        _write_json(artifact_dir / "production-readiness-manifest.json", bundle_payload["manifest"])
                    if isinstance(bundle_payload.get("manifest", {}).get("signer"), dict):
                        _write_json(artifact_dir / "production-readiness-public-key.json", bundle_payload["manifest"]["signer"])
                    if isinstance(bundle_payload.get("manifest_signature"), dict):
                        (artifact_dir / "production-readiness-manifest.sig").write_text(
                            str(bundle_payload["manifest_signature"].get("signature_b64", "")) + "\n",
                            encoding="utf-8",
                        )
            return result
        except Exception as exc:
            result = {
                "schema": "cleanhouse.production_readiness_proving_run.v1",
                "status": "blocked",
                "base_url": base_url,
                "blocker": str(exc),
                "dependencies": dependencies,
                "log_tail": _tail(log_path),
                "no_browser_automation": True,
                "browser_automation_used": False,
                "unsupported_claim_gaps": build_unsupported_claim_gaps(),
            }
            if artifact_dir:
                _write_json(artifact_dir / "production_readiness_proving_run.json", result)
            return result
        finally:
            if not keep_running:
                _stop_server(process)


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.duration_seconds > 0 and getattr(args, "max_total_seconds", None) is None:
        thresholds["total_seconds"] = max(
            thresholds["total_seconds"],
            float(args.duration_seconds) + DEFAULT_THRESHOLDS["total_seconds"],
        )
    for key in DEFAULT_THRESHOLDS:
        value = getattr(args, f"max_{key}", None)
        if value is not None:
            thresholds[key] = float(value)
    return thresholds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--python", default="")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--workload-seconds", type=float, default=DEFAULT_WORKLOAD_SECONDS)
    parser.add_argument("--workload-iterations", type=int, default=DEFAULT_WORKLOAD_ITERATIONS)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--restart-interval-seconds", type=float, default=0.0)
    for key, _default in DEFAULT_THRESHOLDS.items():
        option = "--max-api-seconds" if key == "api_max_seconds" else f"--max-{key.replace('_', '-')}"
        parser.add_argument(
            option,
            dest=f"max_{key}",
            type=float,
            default=None,
        )
    args = parser.parse_args()

    if args.workload_iterations < 1:
        print("--workload-iterations must be at least 1", file=sys.stderr)
        return 2
    if args.workload_seconds <= 0:
        print("--workload-seconds must be greater than 0", file=sys.stderr)
        return 2
    if args.duration_seconds < 0:
        print("--duration-seconds must be greater than or equal to 0", file=sys.stderr)
        return 2
    if args.restart_interval_seconds < 0:
        print("--restart-interval-seconds must be greater than or equal to 0", file=sys.stderr)
        return 2
    if (args.duration_seconds > 0) != (args.restart_interval_seconds > 0):
        print("--duration-seconds and --restart-interval-seconds must be provided together", file=sys.stderr)
        return 2

    if args.no_start and not args.base_url and not args.port:
        port = 3333
    else:
        port = args.port or _free_port(args.host)
    base_url = args.base_url or f"http://{args.host}:{port}"
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or args.host
    if host in {"localhost", "::1"}:
        host = DEFAULT_HOST
    port = parsed.port or port
    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None

    result = run_production_readiness_proving_run(
        base_url=base_url,
        python_exe=args.python or _default_python(),
        host=host,
        port=port,
        no_start=args.no_start,
        keep_running=args.keep_running,
        timeout_seconds=args.timeout,
        workload_seconds=args.workload_seconds,
        workload_iterations=args.workload_iterations,
        duration_seconds=args.duration_seconds,
        restart_interval_seconds=args.restart_interval_seconds,
        thresholds=_thresholds_from_args(args),
        artifact_dir=artifact_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
