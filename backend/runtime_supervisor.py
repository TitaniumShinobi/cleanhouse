"""Authoritative local runtime supervisor for CleanHouse.

This module owns the localhost backend process state used by the operator
launcher. It intentionally keeps the contract local and evidence-oriented:
state is persisted atomically, PID/listener claims are reconciled before reuse,
and recovery actions produce deterministic receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:  # macOS/Linux lock path; tests can still run on platforms without fcntl.
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-posix fallback
    fcntl = None

from corefiles import config
from backend import runtime_env


VALID_RUNTIME_STATES = frozenset({
    "healthy",
    "degraded",
    "recovering",
    "unhealthy",
    "orphaned_listener",
    "stale_pid",
})

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 3333
LAUNCH_AGENT_LABEL = "org.cleanhouse.runtime"
HEARTBEAT_INTERVAL_SECONDS = 5.0
HEARTBEAT_STALE_SECONDS = 20.0
SUPERVISOR_POLL_SECONDS = 1.0
RESTART_WINDOW_SECONDS = 300.0
RESTART_BACKOFF_SECONDS = (1.0, 2.0, 5.0)
MAX_RESTARTS_PER_WINDOW = 3
DEFAULT_RUNTIME_DEGRADED_RSS_MB = 1536.0
DEFAULT_RUNTIME_MAX_RSS_MB = 3072.0
DEFAULT_RUNTIME_CPU_DEGRADED_PERCENT = 250.0
CPU_DEGRADED_SAMPLE_LIMIT = 3
DEFAULT_BACKEND_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKEND_LOG_BACKUPS = 3
OPERATOR_READY_RUNTIME_STATE = "healthy"
OPERATOR_READY_STARTUP_PHASES = frozenset({"warm"})
SELF_DEVIATION_BLOCK_TYPES = frozenset({
    "runtime_memory_ceiling_exceeded",
    "runtime_cpu_sustained_exceeded",
    "runtime_stuck_watchdog",
    "investigation_timeout",
    "restart_budget_exhausted",
    "readiness_recovery_exhausted",
    "ensure_timeout",
    "runtime_unresponsive",
})
STARTUP_HARD_SELF_DEVIATION_TYPES = frozenset({
    "runtime_memory_ceiling_exceeded",
    "runtime_cpu_sustained_exceeded",
    "restart_budget_exhausted",
    "readiness_recovery_exhausted",
    "manual_approval_required",
})
STARTUP_RECOVERABLE_SELF_DEVIATION_TYPES = frozenset({
    "runtime_unresponsive",
    "runtime_memory_degraded_threshold_exceeded",
    "readiness_probe_failed",
    "degraded_state",
})
SELF_DEVIATION_ACTIONS = {
    "runtime_memory_ceiling_exceeded": {
        "observed": "CleanHouse backend exceeded the hard memory ceiling.",
        "comparison_result": "Memory Threshold Breach",
        "mitigation_action": "runtime_stop",
        "next_action": "CleanHouse stopped the unsafe backend. Restart only after reviewing the evidence and confirming the runtime should continue.",
    },
    "runtime_memory_degraded_threshold_exceeded": {
        "observed": "CleanHouse backend exceeded the degraded memory threshold.",
        "comparison_result": "Memory Threshold Warning",
        "mitigation_action": "degraded_state",
        "next_action": "Review runtime resource evidence before starting more scans.",
    },
    "runtime_cpu_sustained_exceeded": {
        "observed": "CleanHouse backend CPU remained above the sustained CPU threshold.",
        "comparison_result": "CPU Threshold Breach",
        "mitigation_action": "investigation_pause",
        "next_action": "Pause investigations and review runtime evidence before continuing.",
    },
    "runtime_stuck_watchdog": {
        "observed": "CleanHouse heartbeat or active runtime work stopped progressing within the expected window.",
        "comparison_result": "Stuck Worker",
        "mitigation_action": "investigation_pause",
        "next_action": "Pause investigations, inspect the stuck runtime evidence, and restart only after confirmation.",
    },
    "investigation_timeout": {
        "observed": "CleanHouse investigation execution exceeded the bounded timeout.",
        "comparison_result": "Investigation Timeout",
        "mitigation_action": "investigation_pause",
        "next_action": "Stop this investigation path and restart CleanHouse only if the operator confirms.",
    },
    "restart_budget_exhausted": {
        "observed": "CleanHouse attempted too many runtime restarts in the recovery window.",
        "comparison_result": "Restart Loop",
        "mitigation_action": "manual_approval_required",
        "next_action": "Stop automatic recovery and require manual approval before another restart.",
    },
    "readiness_recovery_exhausted": {
        "observed": "CleanHouse repeatedly restarted while readiness probes failed.",
        "comparison_result": "Restart Loop",
        "mitigation_action": "manual_approval_required",
        "next_action": "Stop automatic recovery and inspect readiness evidence before restart.",
    },
    "ensure_timeout": {
        "observed": "CleanHouse runtime did not become ready within the startup timeout.",
        "comparison_result": "Unresponsive Runtime",
        "mitigation_action": "manual_approval_required",
        "next_action": "Do not continue unsafe execution; inspect readiness evidence before restart.",
    },
    "runtime_unresponsive": {
        "observed": "CleanHouse runtime responded slowly or failed readiness while the backend process was alive.",
        "comparison_result": "Unresponsive Runtime",
        "mitigation_action": "degraded_state",
        "next_action": "Mark runtime degraded and avoid starting more investigations until readiness recovers.",
    },
}

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SCRIPT = REPO_ROOT / "backend" / "server.py"

_HEARTBEAT_THREAD: threading.Thread | None = None
_HEARTBEAT_STOP = threading.Event()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _runtime_dir() -> Path:
    configured = os.getenv("CLEANHOUSE_RUNTIME_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cleanhouse" / "runtime"


def state_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or _runtime_dir()) / "state.json"


def lock_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or _runtime_dir()) / "runtime.lock"


def supervisor_log_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or _runtime_dir()) / "supervisor.log"


class _FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle is not None:
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
        self.handle = None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_state(runtime_dir: Path | None = None) -> dict[str, Any]:
    return _read_json(state_path(runtime_dir))


def write_state(payload: dict[str, Any], runtime_dir: Path | None = None) -> dict[str, Any]:
    rdir = runtime_dir or _runtime_dir()
    state = dict(payload)
    state.setdefault("schema", "cleanhouse.runtime_state.v1")
    state["updated_at"] = _now_iso()
    runtime_state = str(state.get("runtime_state") or "unhealthy")
    if runtime_state not in VALID_RUNTIME_STATES:
        state["runtime_state"] = "unhealthy"
        reasons = list(state.get("reason_codes") or [])
        reasons.append("invalid_runtime_state")
        state["reason_codes"] = sorted({str(reason) for reason in reasons if reason})
    with _FileLock(lock_path(rdir)):
        _atomic_write_json(state_path(rdir), state)
    return state


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ps_command(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _pid_cwd(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            text=True,
            capture_output=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return ""
    for line in completed.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def _pid_info(pid: int) -> dict[str, Any]:
    return {
        "pid": pid,
        "alive": _pid_alive(pid),
        "command": _ps_command(pid),
        "cwd": _pid_cwd(pid),
    }


def _pid_owned_by_cleanhouse(pid: Any, *, expected_supervisor: bool = False) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0 or not _pid_alive(value):
        return False
    info = _pid_info(value)
    if expected_supervisor:
        return "backend.runtime_supervisor" in str(info.get("command") or "")
    return _is_cleanhouse_owned_process(info)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def runtime_guard_config() -> dict[str, Any]:
    return {
        "degraded_rss_mb": _env_float("CLEANHOUSE_RUNTIME_DEGRADED_RSS_MB", DEFAULT_RUNTIME_DEGRADED_RSS_MB),
        "max_rss_mb": _env_float("CLEANHOUSE_RUNTIME_MAX_RSS_MB", DEFAULT_RUNTIME_MAX_RSS_MB),
        "cpu_degraded_percent": _env_float("CLEANHOUSE_RUNTIME_CPU_DEGRADED_PERCENT", DEFAULT_RUNTIME_CPU_DEGRADED_PERCENT),
        "cpu_degraded_sample_limit": CPU_DEGRADED_SAMPLE_LIMIT,
    }


def _pid_resource_usage(pid: Any) -> dict[str, Any]:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return {"status": "unknown", "reason": "invalid_pid"}
    if value <= 0 or not _pid_alive(value):
        return {"status": "unknown", "pid": value, "reason": "pid_not_alive"}
    try:
        completed = subprocess.run(
            ["ps", "-p", str(value), "-o", "rss=,%cpu=,stat=,etime=,command="],
            text=True,
            capture_output=True,
            timeout=1.5,
            check=False,
        )
    except Exception as exc:
        return {"status": "unknown", "pid": value, "reason": str(exc) or exc.__class__.__name__}
    line = completed.stdout.strip()
    if completed.returncode != 0 or not line:
        return {"status": "unknown", "pid": value, "reason": "ps_unavailable"}
    parts = line.split(None, 4)
    if len(parts) < 5:
        return {"status": "unknown", "pid": value, "reason": "ps_parse_failed", "raw": line}
    rss_kb_raw, cpu_raw, process_state, elapsed, command = parts
    try:
        rss_kb = int(float(rss_kb_raw))
    except ValueError:
        rss_kb = 0
    try:
        cpu_percent = float(cpu_raw)
    except ValueError:
        cpu_percent = 0.0
    return {
        "status": "observed",
        "pid": value,
        "rss_kb": rss_kb,
        "rss_mb": round(rss_kb / 1024.0, 2),
        "cpu_percent": round(cpu_percent, 2),
        "process_state": process_state,
        "elapsed": elapsed,
        "command": command,
    }


def _active_self_deviation_block_reasons(state: dict[str, Any] | None) -> set[str]:
    state = state or {}
    blocked = state.get("blocked_recovery")
    blocked_type = str(blocked.get("type") or "") if isinstance(blocked, dict) else ""
    resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
    reason_codes = {
        str(reason)
        for reason in [
            *(state.get("reason_codes") or []),
            *(resource_guard.get("reason_codes") or []),
            blocked_type,
        ]
        if str(reason)
    }
    active = set(reason_codes.intersection(SELF_DEVIATION_BLOCK_TYPES))
    if blocked_type in SELF_DEVIATION_BLOCK_TYPES:
        active.add(blocked_type)
    if resource_guard.get("action") in {"hard_stop", "block_restart"}:
        active.update(str(reason) for reason in resource_guard.get("reason_codes", []) if str(reason))
        if not active:
            active.add("runtime_resource_guard_block")
    return active


def _self_deviation_block_active(state: dict[str, Any] | None) -> bool:
    return bool(_active_self_deviation_block_reasons(state))


def _clear_stale_self_deviation_restart_block(state: dict[str, Any]) -> dict[str, Any]:
    if _self_deviation_block_active(state):
        return state
    reason_codes = [
        str(reason)
        for reason in state.get("reason_codes", [])
        if str(reason) and str(reason) != "runtime_self_deviation_restart_blocked"
    ]
    state["reason_codes"] = sorted(set(reason_codes))
    blocked = state.get("blocked_recovery")
    if isinstance(blocked, dict) and str(blocked.get("type") or "") == "runtime_self_deviation_restart_blocked":
        state["blocked_recovery"] = {}
    last_start = state.get("last_start_attempt")
    if isinstance(last_start, dict) and str(last_start.get("failure_reason") or "") == "runtime_self_deviation_restart_blocked":
        state["last_start_attempt"] = {
            "status": "cleared",
            "attempted_at": _now_iso(),
            "failure_reason": None,
        }
    return state


def _self_deviation_review_status(self_deviation: dict[str, Any]) -> str | None:
    if not self_deviation.get("id"):
        return None
    explicit = str(self_deviation.get("review_status") or "").strip()
    if explicit:
        return explicit
    status = str(self_deviation.get("status") or "open")
    if status in {"acknowledged", "acknowledged_for_restart"}:
        return "acknowledged"
    if status in {"resolved", "closed"}:
        return "resolved"
    return "needs_review"


def _self_deviation_runtime_impact(state: dict[str, Any] | None) -> str:
    state = state or {}
    self_deviation = state.get("self_deviation")
    if not isinstance(self_deviation, dict) or not self_deviation.get("id"):
        return "none"
    blocked = state.get("blocked_recovery")
    blocked_type = str(blocked.get("type") or "") if isinstance(blocked, dict) else ""
    resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
    reason_codes = {
        str(reason)
        for reason in [
            *(state.get("reason_codes") or []),
            *(resource_guard.get("reason_codes") or []),
            blocked_type,
        ]
        if str(reason)
    }
    if state.get("foreign_listener_pids"):
        return "port_blocked"
    listener_pids = list(state.get("listener_pids") or [])
    runtime_active = bool(state.get("backend_alive")) or bool(state.get("supervisor_alive"))
    current_blocking = (
        blocked_type in SELF_DEVIATION_BLOCK_TYPES
        or reason_codes.intersection(SELF_DEVIATION_BLOCK_TYPES)
        or resource_guard.get("action") in {"hard_stop", "block_restart"}
    )
    runtime_state = str(state.get("runtime_state") or "")
    if runtime_active and current_blocking and (listener_pids or runtime_state in {"degraded", "unhealthy"}):
        return "active_blocking"
    if runtime_active:
        return "monitoring"
    return "historical_record"


def _self_deviation_message(review_status: str | None, runtime_impact: str) -> str:
    if runtime_impact == "active_blocking":
        return "Current CleanHouse runtime state is unsafe; pause new investigations until the live process state is clean."
    if runtime_impact == "port_blocked":
        return "CleanHouse startup is blocked by the current port/process state, not by historical self-deviation evidence."
    if review_status == "acknowledged":
        return "CleanHouse self-deviation evidence has been acknowledged and remains available for history."
    if runtime_impact in {"historical_record", "monitoring"}:
        return "Previous CleanHouse self-deviation evidence remains available for review; it does not block clean startup while the port/process state is safe."
    return ""


def _self_deviation_summary(state: dict[str, Any] | None) -> dict[str, Any]:
    self_deviation = (state or {}).get("self_deviation")
    if not isinstance(self_deviation, dict):
        self_deviation = {}
    finding = self_deviation.get("finding")
    if not isinstance(finding, dict):
        finding = {}
    raw_status = self_deviation.get("status") or ("open" if self_deviation.get("id") else None)
    review_status = _self_deviation_review_status(self_deviation)
    runtime_impact = _self_deviation_runtime_impact(state)
    blocks_startup = runtime_impact in {"active_blocking", "port_blocked"}
    blocks_investigations = runtime_impact == "active_blocking"
    return {
        "id": self_deviation.get("id"),
        "status": raw_status,
        "raw_status": raw_status,
        "review_status": review_status,
        "runtime_impact": runtime_impact,
        "restart_policy": "ports_and_processes",
        "blocks_startup": blocks_startup,
        "blocks_investigations": blocks_investigations,
        "message": _self_deviation_message(review_status, runtime_impact),
        "finding": finding,
        "title": finding.get("title") or self_deviation.get("title"),
        "next_action": self_deviation.get("next_action") or finding.get("next_action"),
        "evidence_artifact_path": self_deviation.get("evidence_artifact_path"),
        "receipt_artifact_path": self_deviation.get("receipt_artifact_path"),
        "evidence_ref": self_deviation.get("evidence_ref"),
        "receipt_ref": self_deviation.get("receipt_ref"),
        "reason_codes": list(self_deviation.get("reason_codes") or (state or {}).get("reason_codes") or []),
        "acknowledged_at": self_deviation.get("acknowledged_at"),
    }


def _startup_self_deviation_classification(state: dict[str, Any]) -> dict[str, Any]:
    self_deviation = state.get("self_deviation")
    blocked_recovery = state.get("blocked_recovery")
    if not isinstance(self_deviation, dict) or not self_deviation.get("id"):
        return {"status": "none", "reason_codes": []}
    if str(self_deviation.get("status") or "open") != "open":
        return {"status": "none", "reason_codes": []}
    if not _self_deviation_block_active(state):
        return {"status": "none", "reason_codes": []}

    finding = self_deviation.get("finding") if isinstance(self_deviation.get("finding"), dict) else {}
    reason_codes = {
        str(reason)
        for reason in [
            *(state.get("reason_codes") or []),
            *(self_deviation.get("reason_codes") or []),
            *(finding.get("reason_codes") or []),
            str(self_deviation.get("mitigation_action") or ""),
            str(finding.get("mitigation_action") or ""),
        ]
        if str(reason)
    }
    if isinstance(blocked_recovery, dict):
        reason_codes.add(str(blocked_recovery.get("type") or ""))
    reason_codes.update(_active_self_deviation_block_reasons(state))

    startup_hard_types = {
        "manual_approval_required",
        "restart_budget_exhausted",
        "readiness_recovery_exhausted",
    }
    if reason_codes.intersection(startup_hard_types):
        return {"status": "hard_blocking", "reason_codes": sorted(reason_codes)}
    restart_cleanly_allowed = not bool(state.get("listener_pids")) and not bool(state.get("foreign_listener_pids"))
    if restart_cleanly_allowed:
        return {"status": "recoverable", "reason_codes": sorted(reason_codes)}
    return {"status": "hard_blocking", "reason_codes": sorted(reason_codes)}


def _startup_self_deviation_recovery_allowed(state: dict[str, Any]) -> bool:
    allowed = state.get("startup_recovery_allowed")
    self_deviation = state.get("self_deviation")
    if not isinstance(allowed, dict) or not isinstance(self_deviation, dict):
        return False
    if not allowed.get("self_deviation_id") or str(allowed.get("self_deviation_id")) != str(self_deviation.get("id") or ""):
        return False
    finding = self_deviation.get("finding") if isinstance(self_deviation.get("finding"), dict) else {}
    reason_codes = {
        str(reason)
        for reason in [
            *(allowed.get("reason_codes") or []),
            *(self_deviation.get("reason_codes") or []),
            *(finding.get("reason_codes") or []),
            str(self_deviation.get("mitigation_action") or ""),
            str(finding.get("mitigation_action") or ""),
        ]
        if str(reason)
    }
    return bool(reason_codes)


def _allow_self_deviation_restart() -> bool:
    return os.getenv("CLEANHOUSE_RUNTIME_ALLOW_AFTER_SELF_DEVIATION", "").strip().lower() in {"1", "true", "yes", "on"}


def _acknowledge_self_deviation_for_restart(state: dict[str, Any]) -> dict[str, Any]:
    self_deviation = state.get("self_deviation")
    if isinstance(self_deviation, dict) and self_deviation.get("id"):
        updated = dict(self_deviation)
        updated["status"] = "acknowledged_for_restart"
        updated["review_status"] = "acknowledged"
        updated["acknowledged_at"] = _now_iso()
        updated["next_action"] = "Restart confirmed by operator; continue monitoring for a new runtime self-deviation."
        finding = updated.get("finding")
        if isinstance(finding, dict):
            finding = dict(finding)
            finding["review_status"] = "acknowledged"
            updated["finding"] = finding
        state["self_deviation"] = updated
    if isinstance(state.get("blocked_recovery"), dict) and str(state["blocked_recovery"].get("type") or "") in SELF_DEVIATION_BLOCK_TYPES:
        state["blocked_recovery"] = {}
    return state


def _runtime_guard_from_usage(previous: dict[str, Any] | None, usage: dict[str, Any], reasons: set[str]) -> dict[str, Any]:
    config_payload = runtime_guard_config()
    previous_guard = (previous or {}).get("resource_guard") if isinstance((previous or {}).get("resource_guard"), dict) else {}
    cpu_samples = 0
    guard_reasons: list[str] = []
    action = "none"
    status = "ok"

    if usage.get("status") == "observed":
        rss_mb = float(usage.get("rss_mb") or 0.0)
        cpu_percent = float(usage.get("cpu_percent") or 0.0)
        if rss_mb >= float(config_payload["max_rss_mb"]):
            status = "blocked"
            action = "hard_stop"
            guard_reasons.append("runtime_memory_ceiling_exceeded")
        elif rss_mb >= float(config_payload["degraded_rss_mb"]):
            status = "degraded"
            guard_reasons.append("runtime_memory_degraded_threshold_exceeded")

        if cpu_percent >= float(config_payload["cpu_degraded_percent"]):
            cpu_samples = int(previous_guard.get("cpu_degraded_samples", 0) or 0) + 1
            if cpu_samples >= CPU_DEGRADED_SAMPLE_LIMIT:
                status = "blocked" if status == "blocked" else "degraded"
                action = "block_restart" if action == "none" else action
                guard_reasons.append("runtime_cpu_sustained_exceeded")
            else:
                status = "degraded" if status == "ok" else status
                guard_reasons.append("runtime_cpu_degraded_threshold_exceeded")
        else:
            cpu_samples = 0

    if "heartbeat_stale" in reasons:
        status = "degraded" if status == "ok" else status
        guard_reasons.append("runtime_stuck_watchdog")

    return {
        "schema": "cleanhouse.runtime_resource_guard.v1",
        "status": status if guard_reasons else "ok",
        "action": action,
        "reason_codes": sorted(set(guard_reasons)),
        "usage": usage,
        "thresholds": config_payload,
        "cpu_degraded_samples": cpu_samples,
        "expected_behavior": "CleanHouse stays idle and bounded unless an operator starts an investigation.",
        "updated_at": _now_iso(),
    }


def _is_cleanhouse_owned_process(info: dict[str, Any]) -> bool:
    command = str(info.get("command") or "")
    cwd = str(info.get("cwd") or "")
    repo = str(REPO_ROOT)
    if repo and repo in command:
        return True
    if repo and cwd.startswith(repo):
        return True
    return "backend/server.py" in command or "desktop/wrapper.py" in command or "backend.runtime_supervisor" in command


def listener_pids(port: int, host: str = DEFAULT_HOST) -> list[int]:
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            text=True,
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        if not line.startswith("p"):
            continue
        try:
            pid = int(line[1:])
        except ValueError:
            continue
        if pid not in pids:
            pids.append(pid)
    return pids


def _probe_port(host: str, port: int, timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, int(port))) == 0


def _probe_ready(host: str, port: int, timeout: float = 1.0) -> dict[str, Any]:
    url = f"http://{host}:{port}/cleanhouse/status?ready=1"
    started = time.monotonic()
    try:
        with urlopen(Request(url, headers={"User-Agent": "CleanHouse Runtime Supervisor"}), timeout=timeout) as response:
            body = response.read()
            payload = json.loads(body.decode("utf-8") or "{}")
            ok = response.getcode() == 200 and payload.get("ready") is True
            return {
                "status": "ok" if ok else "failed",
                "http_status": response.getcode(),
                "elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
                "url": url,
            }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "status": "failed",
            "error": str(exc) or exc.__class__.__name__,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 2),
            "url": url,
        }


def _heartbeat_fresh(state: dict[str, Any], now: float | None = None) -> bool:
    raw = state.get("heartbeat_at")
    if not raw:
        return False
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    now_ts = now if now is not None else time.time()
    return (now_ts - parsed.timestamp()) <= HEARTBEAT_STALE_SECONDS


def _base_state(host: str, port: int, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    return {
        "schema": "cleanhouse.runtime_state.v1",
        "runtime_state": previous.get("runtime_state", "unhealthy"),
        "reason_codes": list(previous.get("reason_codes") or []),
        "host": host,
        "port": int(port),
        "supervisor_pid": previous.get("supervisor_pid"),
        "backend_pid": previous.get("backend_pid"),
        "boot_id": previous.get("boot_id"),
        "start_time": previous.get("start_time"),
        "startup_phase": previous.get("startup_phase"),
        "startup_started_at": previous.get("startup_started_at"),
        "bootstrap_started_at": previous.get("bootstrap_started_at"),
        "bootstrap_ready_at": previous.get("bootstrap_ready_at"),
        "warmup_started_at": previous.get("warmup_started_at"),
        "warmup_ready_at": previous.get("warmup_ready_at"),
        "restart_count": int(previous.get("restart_count", 0) or 0),
        "heartbeat_at": previous.get("heartbeat_at"),
        "heartbeat_sequence": int(previous.get("heartbeat_sequence", 0) or 0),
        "last_probe": previous.get("last_probe", {}),
        "interpreter": dict(previous.get("interpreter") or {}),
        "last_start_attempt": dict(previous.get("last_start_attempt") or {}),
        "blocked_recovery": dict(previous.get("blocked_recovery") or {}),
        "startup_recovery_allowed": dict(previous.get("startup_recovery_allowed") or {}),
        "listener_pids": list(previous.get("listener_pids") or []),
        "listeners": list(previous.get("listeners") or []),
        "recent_recovery_receipts": list(previous.get("recent_recovery_receipts") or []),
        "resource_guard": dict(previous.get("resource_guard") or {}),
        "self_deviation": dict(previous.get("self_deviation") or {}),
    }


def _interpreter_summary(resolved: dict[str, Any] | None) -> dict[str, Any]:
    resolved = resolved or {}
    selected_path = str(resolved.get("selected_path") or "").strip()
    selected_attempt = {}
    for attempt in resolved.get("attempts") or []:
        if str(attempt.get("path") or "") == selected_path:
            selected_attempt = dict(attempt)
            break
    return {
        "path": selected_path or None,
        "source": resolved.get("selected_source"),
        "status": resolved.get("status", "unavailable"),
        "supervisor_compatible": bool(resolved.get("supervisor_compatible")),
        "backend_compatible": bool(resolved.get("backend_compatible")),
        "runnable": bool(resolved.get("runnable")),
        "failures": list(resolved.get("failures") or []),
        "attempt_count": len(list(resolved.get("attempts") or [])),
        "selected_attempt": selected_attempt,
    }


def _cached_interpreter_summary(state: dict[str, Any] | None) -> dict[str, Any]:
    interpreter = (state or {}).get("interpreter")
    return dict(interpreter) if isinstance(interpreter, dict) else {}


def _blocked_recovery_payload(kind: str, reason: str, *, details: dict[str, Any] | None = None, receipt_id: str | None = None) -> dict[str, Any]:
    payload = {
        "status": "blocked",
        "type": kind,
        "reason": reason,
        "timestamp": _now_iso(),
        "details": details or {},
    }
    if receipt_id:
        payload["receipt_id"] = receipt_id
    return payload


def _operator_readiness_contract(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    runtime_state = str(state.get("runtime_state") or "unknown")
    startup_phase = str(state.get("startup_phase") or "")
    backend_alive = bool(state.get("backend_alive"))
    supervisor_alive = bool(state.get("supervisor_alive"))
    heartbeat_fresh = bool(state.get("heartbeat_fresh"))
    active_block = _self_deviation_block_active(state)
    hard_resource_block = _runtime_guard_hard_stop_active(state)
    owned_listener_pids = [int(pid) for pid in state.get("owned_listener_pids", []) if str(pid).isdigit()]
    foreign_listener_pids = [int(pid) for pid in state.get("foreign_listener_pids", []) if str(pid).isdigit()]
    try:
        backend_pid = int(state.get("backend_pid"))
    except (TypeError, ValueError):
        backend_pid = None
    probe_status = str((state.get("last_probe") or {}).get("status") or "")
    checks = {
        "runtime_healthy": runtime_state == OPERATOR_READY_RUNTIME_STATE,
        "startup_warm": startup_phase in OPERATOR_READY_STARTUP_PHASES,
        "backend_alive": backend_alive,
        "supervisor_alive": supervisor_alive,
        "heartbeat_fresh": heartbeat_fresh,
        "readiness_probe_ok": probe_status == "ok",
        "single_owned_listener": len(owned_listener_pids) == 1,
        "listener_matches_backend": backend_pid is not None and owned_listener_pids == [backend_pid],
        "no_foreign_listener": not foreign_listener_pids,
        "no_self_deviation_block": not active_block,
        "no_resource_guard_block": not hard_resource_block,
    }
    failed = [name for name, satisfied in checks.items() if not satisfied]
    return {
        "schema": "cleanhouse.runtime_operator_readiness.v1",
        "satisfied": not failed,
        "required_runtime_state": OPERATOR_READY_RUNTIME_STATE,
        "required_startup_phases": sorted(OPERATOR_READY_STARTUP_PHASES),
        "checks": checks,
        "failed_checks": failed,
    }


def _launch_ready(state: dict[str, Any] | None) -> bool:
    return bool(_operator_readiness_contract(state).get("satisfied"))


def _same_blocked_recovery(previous_state: dict[str, Any] | None, action: str) -> bool:
    previous = previous_state or {}
    blocked = previous.get("blocked_recovery") if isinstance(previous.get("blocked_recovery"), dict) else {}
    return str(blocked.get("type") or "") == action


def _record_recovery_and_state(
    state: dict[str, Any],
    *,
    action: str,
    previous_state: dict[str, Any] | None,
    reason_codes: Iterable[str] = (),
    evidence: dict[str, Any] | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    receipt = persist_runtime_recovery(
        action=action,
        previous_state=previous_state,
        final_state=state,
        reason_codes=reason_codes,
        evidence=evidence,
    )
    state = _append_recovery_id(state, receipt)
    actionability = dict((evidence or {}).get("actionability") or {})
    actionability.setdefault("dashboard_target", "runtime")
    actionability.setdefault("recovery_receipt_id", str(receipt.get("id") or ""))
    state["blocked_recovery"] = _blocked_recovery_payload(
        action,
        ",".join(sorted({str(reason) for reason in reason_codes if reason})) or action,
        details={**(evidence or {}), "actionability": actionability},
        receipt_id=str(receipt.get("id") or ""),
    )
    return write_state(state, runtime_dir)


def persist_runtime_self_deviation(
    *,
    action: str,
    reason_codes: Iterable[str],
    evidence: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None,
    final_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    reasons = sorted({str(reason) for reason in reason_codes if reason})
    evidence_payload = evidence or {}
    action_contract = SELF_DEVIATION_ACTIONS.get(action, {})
    expected_behavior = "CleanHouse stays idle and bounded unless an operator starts an investigation."
    observed_behavior = evidence_payload.get("observed_behavior") or action_contract.get("observed") or "CleanHouse runtime exceeded its own safety threshold."
    comparison_result = evidence_payload.get("comparison_result") or action_contract.get("comparison_result") or "CleanHouse Runtime Deviation"
    mitigation_action = evidence_payload.get("mitigation_action") or action_contract.get("mitigation_action") or "degraded_state"
    next_action = evidence_payload.get("next_action") or action_contract.get("next_action") or "Stop or degrade the runtime, preserve evidence, and require restart or confirmation before continuing."
    finding = {
        "id": "",
        "title": "CleanHouse became the suspicious process",
        "status": "open",
        "review_status": "needs_review",
        "severity": "High",
        "confidence": 95,
        "evidence_strength": "Strong",
        "timestamp": now,
        "timeline_anchor": now,
        "expected": expected_behavior,
        "expected_behavior": expected_behavior,
        "observed": observed_behavior,
        "observed_behavior": observed_behavior,
        "comparison_result": comparison_result,
        "result": "cleanhouse_runtime_deviation",
        "reason_codes": reasons,
        "evidence_refs": [],
        "receipt_ref": "",
        "next_action": next_action,
        "mitigation_action": mitigation_action,
    }
    core = {
        "schema": "cleanhouse.runtime_self_deviation.v1",
        "created_at": now,
        "action": action,
        "finding": finding,
        "expected_behavior": expected_behavior,
        "observed_behavior": observed_behavior,
        "comparison_result": comparison_result,
        "result": finding["result"],
        "review_status": "needs_review",
        "runtime_impact": "active_blocking",
        "restart_policy": "ports_and_processes",
        "next_action": next_action,
        "mitigation_action": mitigation_action,
        "evidence": evidence_payload,
        "previous_state": {
            "runtime_state": (previous_state or {}).get("runtime_state"),
            "backend_pid": (previous_state or {}).get("backend_pid"),
            "reason_codes": list((previous_state or {}).get("reason_codes") or []),
        },
        "final_state": {
            "runtime_state": (final_state or {}).get("runtime_state"),
            "backend_pid": (final_state or {}).get("backend_pid"),
            "reason_codes": list((final_state or {}).get("reason_codes") or []),
        },
    }
    artifact_id = f"runtime_self_deviation:{hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"
    finding["id"] = artifact_id
    evidence_ref = f"local://cleanhouse/runtime-self-deviation/evidence/{artifact_id}"
    receipt_ref = f"local://cleanhouse/runtime-self-deviation/receipt/{artifact_id}"
    finding["evidence_refs"] = [evidence_ref]
    finding["receipt_ref"] = receipt_ref

    directory = config.DATA_DIR / "runtime_self_deviations" / "v1"
    evidence_dir = directory / "evidence"
    receipt_dir = directory / "receipts"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"{artifact_id}.json"
    receipt_path = receipt_dir / f"{artifact_id}.json"
    evidence_artifact = {
        "schema": "cleanhouse.runtime_self_deviation_evidence.v1",
        "created_at": now,
        "id": artifact_id,
        "finding": finding,
        "expected_behavior": core["expected_behavior"],
        "observed_behavior": core["observed_behavior"],
        "comparison_result": core["comparison_result"],
        "result": core["result"],
        "review_status": core["review_status"],
        "runtime_impact": core["runtime_impact"],
        "restart_policy": core["restart_policy"],
        "next_action": core["next_action"],
        "mitigation_action": core["mitigation_action"],
        "raw_evidence": evidence_payload,
    }
    receipt_artifact = {
        "schema": "cleanhouse.runtime_self_deviation_receipt.v1",
        "created_at": now,
        "id": artifact_id,
        "finding": finding,
        "expected_behavior": core["expected_behavior"],
        "observed_behavior": core["observed_behavior"],
        "comparison_result": core["comparison_result"],
        "result": core["result"],
        "review_status": core["review_status"],
        "runtime_impact": core["runtime_impact"],
        "restart_policy": core["restart_policy"],
        "next_action": core["next_action"],
        "mitigation_action": core["mitigation_action"],
        "evidence_artifact_path": str(evidence_path),
        "integrity": {
            "algorithm": "sha-256",
            "root_hash": _canonical_hash(core),
        },
    }
    evidence_path.write_text(json.dumps(evidence_artifact, indent=2, sort_keys=True, default=str), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt_artifact, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return {
        "id": artifact_id,
        "status": "open",
        "review_status": "needs_review",
        "runtime_impact": "active_blocking",
        "restart_policy": "ports_and_processes",
        "finding": finding,
        "evidence_ref": evidence_ref,
        "receipt_ref": receipt_ref,
        "evidence_artifact_path": str(evidence_path),
        "receipt_artifact_path": str(receipt_path),
        "reason_codes": reasons,
        "expected_behavior": expected_behavior,
        "observed_behavior": observed_behavior,
        "comparison_result": comparison_result,
        "next_action": next_action,
        "mitigation_action": mitigation_action,
    }


def _record_self_deviation_and_state(
    state: dict[str, Any],
    *,
    action: str,
    previous_state: dict[str, Any] | None,
    reason_codes: Iterable[str],
    evidence: dict[str, Any] | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    self_deviation = persist_runtime_self_deviation(
        action=action,
        previous_state=previous_state,
        final_state=state,
        reason_codes=reason_codes,
        evidence=evidence,
    )
    recovery_evidence = {
        **(evidence or {}),
        "self_deviation": self_deviation,
        "actionability": {
            **_runtime_actionability(action, reason_codes=reason_codes),
            "self_deviation_evidence_path": self_deviation["evidence_artifact_path"],
            "self_deviation_receipt_path": self_deviation["receipt_artifact_path"],
        },
    }
    receipt = persist_runtime_recovery(
        action=action,
        previous_state=previous_state,
        final_state=state,
        reason_codes=reason_codes,
        evidence=recovery_evidence,
    )
    state = _append_recovery_id(state, receipt)
    state["self_deviation"] = self_deviation
    state["blocked_recovery"] = _blocked_recovery_payload(
        action,
        ",".join(sorted({str(reason) for reason in reason_codes if reason})) or action,
        details=recovery_evidence,
        receipt_id=str(receipt.get("id") or ""),
    )
    return write_state(state, runtime_dir)


def record_runtime_self_deviation(
    *,
    action: str,
    reason_codes: Iterable[str] = (),
    evidence: dict[str, Any] | None = None,
    runtime_state: str = "degraded",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    rdir = runtime_dir or _runtime_dir()
    previous = read_state(rdir)
    state = _base_state(host, port, previous)
    state["runtime_state"] = runtime_state if runtime_state in VALID_RUNTIME_STATES else "degraded"
    state["status"] = state["runtime_state"]
    state["reason_codes"] = sorted(set([str(action), *[str(reason) for reason in reason_codes if str(reason)]]))
    state["operator_ready"] = False
    return _record_self_deviation_and_state(
        state,
        action=action,
        previous_state=previous,
        reason_codes=state["reason_codes"],
        evidence=evidence,
        runtime_dir=rdir,
    )


def _runtime_actionability(kind: str, *, reason_codes: Iterable[str] = ()) -> dict[str, Any]:
    reasons = ",".join(sorted({str(reason) for reason in reason_codes if reason}))
    runtime_evidence_ref = f"local://cleanhouse/runtime/{hashlib.sha256(f'{kind}:{reasons}'.encode('utf-8')).hexdigest()[:16]}"
    runtime_transition_ref = f"local://cleanhouse/runtime-transition/{hashlib.sha256(f'transition:{kind}:{reasons}'.encode('utf-8')).hexdigest()[:16]}"
    return {
        "dashboard_target": "runtime",
        "runtime_evidence_ref": runtime_evidence_ref,
        "runtime_transition_ref": runtime_transition_ref,
        "recovery_hint": "inspect runtime notification evidence refs and backend log",
    }


def classify_state(
    previous: dict[str, Any] | None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    probe: bool = True,
) -> dict[str, Any]:
    state = _base_state(host, port, previous)
    reasons: set[str] = set()
    backend_pid = state.get("backend_pid")
    supervisor_pid = state.get("supervisor_pid")
    backend_alive = _pid_alive(backend_pid)
    backend_owned = backend_alive and _pid_owned_by_cleanhouse(backend_pid)
    supervisor_alive = _pid_alive(supervisor_pid)
    supervisor_owned = supervisor_alive and _pid_owned_by_cleanhouse(supervisor_pid, expected_supervisor=True)
    runtime_state = "unhealthy"

    pids = listener_pids(port, host)
    listeners = [_pid_info(pid) for pid in pids]
    owned_listener_pids = [item["pid"] for item in listeners if _is_cleanhouse_owned_process(item)]
    foreign_listener_pids = [item["pid"] for item in listeners if not _is_cleanhouse_owned_process(item)]

    if (
        owned_listener_pids
        and not foreign_listener_pids
        and len(owned_listener_pids) == 1
        and (not backend_pid or not _pid_alive(backend_pid) or int(backend_pid) not in pids)
    ):
        backend_pid = owned_listener_pids[0]
        state["backend_pid"] = backend_pid
        backend_alive = _pid_alive(backend_pid)
        backend_owned = backend_alive and _pid_owned_by_cleanhouse(backend_pid)
    ready_probe = _probe_ready(host, port) if probe and pids else {"status": "skipped"}
    heartbeat_fresh = _heartbeat_fresh(state)

    if runtime_state != "stale_pid":
        if pids and (not backend_pid or int(backend_pid) not in pids):
            runtime_state = "orphaned_listener"
            reasons.add("listener_pid_mismatch")
            if owned_listener_pids:
                reasons.add("cleanhouse_owned_orphan_listener")
            if foreign_listener_pids:
                reasons.add("foreign_listener_present")
        elif backend_pid and not backend_alive:
            runtime_state = "stale_pid"
            reasons.add("backend_pid_not_alive")
        elif backend_pid and not backend_owned:
            runtime_state = "stale_pid"
            reasons.add("backend_pid_not_owned")
        elif supervisor_pid and not supervisor_alive:
            runtime_state = "stale_pid"
            reasons.add("supervisor_pid_not_alive")
        elif supervisor_pid and not supervisor_owned and backend_alive:
            runtime_state = "stale_pid"
            reasons.add("supervisor_pid_not_owned")
        elif backend_alive and backend_owned and pids and (
            ready_probe.get("status") == "ok"
            or (not probe and (heartbeat_fresh or not state.get("heartbeat_at")))
        ):
            if heartbeat_fresh or not state.get("heartbeat_at"):
                runtime_state = "healthy"
            else:
                runtime_state = "degraded"
                reasons.add("heartbeat_stale")
        elif backend_alive and backend_owned:
            runtime_state = "recovering"
            if not pids:
                reasons.add("listener_not_ready")
            if ready_probe.get("status") == "failed":
                reasons.add("readiness_probe_failed")
        elif not supervisor_alive and supervisor_pid:
            runtime_state = "stale_pid"
            reasons.add("supervisor_pid_not_alive")
        else:
            runtime_state = "unhealthy"
            reasons.add("backend_not_running")

    resource_usage = _pid_resource_usage(backend_pid) if backend_alive and backend_owned else {"status": "unknown", "reason": "backend_not_running"}
    resource_guard = _runtime_guard_from_usage(previous, resource_usage, reasons)
    guard_reasons = set(resource_guard.get("reason_codes") or [])
    if "runtime_memory_ceiling_exceeded" in guard_reasons:
        runtime_state = "unhealthy"
        reasons.add("runtime_memory_ceiling_exceeded")
    elif guard_reasons:
        if runtime_state == "healthy":
            runtime_state = "degraded"
        reasons.update(guard_reasons)

    state.update({
        "runtime_state": runtime_state,
        "status": runtime_state,
        "reason_codes": sorted(reasons),
        "backend_alive": backend_alive,
        "supervisor_alive": supervisor_alive,
        "heartbeat_fresh": heartbeat_fresh,
        "listener_pids": pids,
        "listeners": listeners,
        "owned_listener_pids": owned_listener_pids,
        "foreign_listener_pids": foreign_listener_pids,
        "last_probe": ready_probe,
        "resource_guard": resource_guard,
        "updated_at": _now_iso(),
    })
    return state


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def persist_runtime_recovery(
    *,
    action: str,
    previous_state: dict[str, Any] | None,
    final_state: dict[str, Any] | None,
    reason_codes: Iterable[str] = (),
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    previous_summary = {
        "runtime_state": (previous_state or {}).get("runtime_state"),
        "supervisor_pid": (previous_state or {}).get("supervisor_pid"),
        "backend_pid": (previous_state or {}).get("backend_pid"),
        "listener_pids": list((previous_state or {}).get("listener_pids") or []),
    }
    final_summary = {
        "runtime_state": (final_state or {}).get("runtime_state"),
        "supervisor_pid": (final_state or {}).get("supervisor_pid"),
        "backend_pid": (final_state or {}).get("backend_pid"),
        "listener_pids": list((final_state or {}).get("listener_pids") or []),
    }
    core = {
        "schema": "cleanhouse.runtime_recovery.v1",
        "timestamp": now,
        "action": action,
        "previous_state": previous_summary,
        "final_state": final_summary,
        "reason_codes": sorted({str(reason) for reason in reason_codes if reason}),
        "evidence": evidence or {},
    }
    receipt_id = f"runtime_recovery:{hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"
    result = {
        "status": "ok",
        "id": receipt_id,
        **core,
        "integrity": {
            "algorithm": "sha-256",
            "root_hash": _canonical_hash(core),
        },
    }
    subdir = config.ARTIFACT_SUBDIRS.get("runtime_recovery", "runtime_recovery")
    version = config.SCHEMA_VERSIONS.get("runtime_recovery", 1)
    directory = config.DATA_DIR / subdir / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": version,
        "artifact_type": "runtime_recovery",
        "created_at": now,
        "data": result,
    }
    filename = f"{receipt_id}.json"
    tmp_path = directory / f".{filename}.{os.getpid()}.tmp"
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp_path.replace(directory / filename)
    return result


def _append_recovery_id(state: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    ids = [str(item) for item in state.get("recent_recovery_receipts", []) if item]
    rid = str(receipt.get("id") or "")
    if rid:
        ids.insert(0, rid)
    state["recent_recovery_receipts"] = list(dict.fromkeys(ids))[:10]
    return state


def _terminate_owned_listeners(state: dict[str, Any]) -> dict[str, Any]:
    previous = dict(state)
    terminated: list[int] = []
    for pid in list(state.get("owned_listener_pids") or []):
        info = _pid_info(int(pid))
        if not _is_cleanhouse_owned_process(info):
            continue
        try:
            os.kill(int(pid), signal.SIGTERM)
            terminated.append(int(pid))
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
    if terminated:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not any(_pid_alive(pid) for pid in terminated):
                break
            time.sleep(0.1)
        for pid in terminated:
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    final_state = classify_state(previous, host=str(previous.get("host") or DEFAULT_HOST), port=int(previous.get("port") or DEFAULT_PORT))
    receipt = persist_runtime_recovery(
        action="terminate_owned_orphan_listener",
        previous_state=previous,
        final_state=final_state,
        reason_codes=previous.get("reason_codes", []),
        evidence={"terminated_pids": terminated},
    )
    return _append_recovery_id(final_state, receipt)


def _backend_env(host: str, port: int, runtime_dir: Path, boot_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["CLEANHOUSE_HOST"] = host
    env["CLEANHOUSE_PORT"] = str(port)
    env["CLEANHOUSE_RUNTIME_DIR"] = str(runtime_dir)
    env["CLEANHOUSE_EVENTS_DB"] = str(runtime_dir / "events" / "events.db")
    env["CLEANHOUSE_SUPERVISED"] = "1"
    env["CLEANHOUSE_BACKEND_BOOT_ID"] = boot_id
    # Safe default: keep native desktop notifications live-only and runtime-gated.
    env.setdefault("CLEANHOUSE_NATIVE_NOTIFICATIONS", "1")
    env.setdefault("CLEANHOUSE_NATIVE_CODEX_ACTIVITY", "1")
    env.setdefault("CLEANHOUSE_NATIVE_LIVE_ONLY", "1")
    env.setdefault("CLEANHOUSE_NATIVE_LIVE_MAX_AGE_SECONDS", "3")
    env.setdefault("CLEANHOUSE_NATIVE_REMINDERS", "0")
    env.setdefault("CLEANHOUSE_ACTIVE_CONTEXT_RESPONSE_NOTIFICATIONS", "1")
    env.setdefault("CLEANHOUSE_ACTIVE_CONTEXT_FOLLOW", "1")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    return env


def _rotate_backend_log_if_needed(log_path: Path) -> None:
    max_bytes = _env_int("CLEANHOUSE_BACKEND_LOG_MAX_BYTES", DEFAULT_BACKEND_LOG_MAX_BYTES)
    backups = _env_int("CLEANHOUSE_BACKEND_LOG_BACKUPS", DEFAULT_BACKEND_LOG_BACKUPS)
    if max_bytes <= 0 or backups <= 0:
        return
    for index in range(1, backups + 1):
        backup = log_path.with_name(f"{log_path.name}.{index}")
        tmp_path = None
        try:
            if not backup.exists() or backup.stat().st_size <= max_bytes:
                continue
            tmp_path = backup.with_suffix(backup.suffix + ".tmp")
            with backup.open("rb") as source:
                source.seek(-max_bytes, os.SEEK_END)
                tail = source.read(max_bytes)
            tmp_path.write_bytes(tail)
            tmp_path.replace(backup)
        except OSError:
            try:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
    try:
        if not log_path.exists() or log_path.stat().st_size < max_bytes:
            return
    except OSError:
        return
    oldest = log_path.with_name(f"{log_path.name}.{backups}")
    try:
        if oldest.exists():
            oldest.unlink()
    except OSError:
        pass
    for index in range(backups - 1, 0, -1):
        source = log_path.with_name(f"{log_path.name}.{index}")
        target = log_path.with_name(f"{log_path.name}.{index + 1}")
        try:
            if source.exists():
                source.replace(target)
        except OSError:
            continue
    try:
        log_path.replace(log_path.with_name(f"{log_path.name}.1"))
    except OSError:
        pass


def _start_backend(interpreter: str, host: str, port: int, runtime_dir: Path, boot_id: str) -> subprocess.Popen:
    log_path = runtime_dir / "backend.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_backend_log_if_needed(log_path)
    log = log_path.open("ab")
    process = subprocess.Popen(
        [interpreter, str(BACKEND_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=_backend_env(host, port, runtime_dir, boot_id),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    return process


def _supervisor_spawn_env(runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CLEANHOUSE_RUNTIME_DIR"] = str(runtime_dir)
    env["CLEANHOUSE_SUPERVISOR_BOOT_ID"] = uuid.uuid4().hex
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("CLEANHOUSE_RUNTIME_ALLOW_AFTER_SELF_DEVIATION", None)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) if not existing else f"{REPO_ROOT}{os.pathsep}{existing}"
    return env


def _spawn_supervisor_process(interpreter: str, host: str, port: int, runtime_dir: Path) -> subprocess.Popen:
    log = supervisor_log_path(runtime_dir).open("ab")
    process = subprocess.Popen(
        [
            interpreter,
            "-m",
            "backend.runtime_supervisor",
            "supervise",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=_supervisor_spawn_env(runtime_dir),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    return process


def _resolve_supervisor_boot_interpreter(_previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve against the supervisor's current runtime, never stale state."""
    return _interpreter_summary(runtime_env.resolve_interpreter(REPO_ROOT))


def supervisor_loop(host: str, port: int, runtime_dir: Path | None = None) -> int:
    rdir = runtime_dir or _runtime_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    boot_id = os.getenv("CLEANHOUSE_SUPERVISOR_BOOT_ID", uuid.uuid4().hex)
    backend_process: subprocess.Popen | None = None
    restart_times: list[float] = []
    stop_requested = False

    def _handle_stop(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    state = _base_state(host, port, read_state(rdir))
    state.update({
        "runtime_state": "recovering",
        "supervisor_pid": os.getpid(),
        "boot_id": boot_id,
        "start_time": state.get("start_time") or _now_iso(),
        "reason_codes": ["supervisor_starting"],
        "interpreter": _resolve_supervisor_boot_interpreter(state),
        "blocked_recovery": {},
    })
    write_state(state, rdir)

    try:
        while not stop_requested:
            previous = read_state(rdir)
            state = classify_state(previous, host=host, port=port)
            state["supervisor_pid"] = os.getpid()
            state["boot_id"] = boot_id
            state.setdefault("start_time", _now_iso())
            cached_interpreter = _cached_interpreter_summary(previous)
            if cached_interpreter.get("path") and cached_interpreter.get("supervisor_compatible"):
                state["interpreter"] = cached_interpreter
            else:
                resolved = runtime_env.resolve_interpreter(REPO_ROOT)
                state["interpreter"] = _interpreter_summary(resolved)
            state = _clear_stale_self_deviation_restart_block(state)
            resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
            guard_reasons = [str(reason) for reason in resource_guard.get("reason_codes", []) if str(reason)]

            if _self_deviation_block_active(state) and not _allow_self_deviation_restart() and not _startup_self_deviation_recovery_allowed(state):
                state["runtime_state"] = "unhealthy"
                state["status"] = "unhealthy"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["runtime_self_deviation_restart_blocked"]))
                state["last_start_attempt"] = {
                    "status": "blocked",
                    "attempted_at": _now_iso(),
                    "failure_reason": "runtime_self_deviation_restart_blocked",
                }
                write_state(state, rdir)
                time.sleep(SUPERVISOR_POLL_SECONDS)
                continue
            if _self_deviation_block_active(state) and _allow_self_deviation_restart():
                state = _acknowledge_self_deviation_for_restart(state)

            if resource_guard.get("action") == "hard_stop":
                stopped_backend = _terminate_pid_if_owned(state.get("backend_pid"))
                state["runtime_state"] = "unhealthy"
                state["status"] = "unhealthy"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + guard_reasons + ["runtime_memory_ceiling_exceeded"]))
                evidence = {
                    "resource_guard": resource_guard,
                    "stopped_backend": stopped_backend,
                    "backend_pid": state.get("backend_pid"),
                    "observed_behavior": f"CleanHouse backend exceeded {resource_guard.get('thresholds', {}).get('max_rss_mb')} MB RSS.",
                    "host": host,
                    "port": port,
                }
                if not _same_blocked_recovery(previous, "runtime_memory_ceiling_exceeded"):
                    state = _record_self_deviation_and_state(
                        state,
                        action="runtime_memory_ceiling_exceeded",
                        previous_state=previous,
                        reason_codes=state["reason_codes"],
                        evidence=evidence,
                        runtime_dir=rdir,
                    )
                else:
                    write_state(state, rdir)
                backend_process = None
                time.sleep(SUPERVISOR_POLL_SECONDS)
                continue

            if "runtime_cpu_sustained_exceeded" in guard_reasons and not _same_blocked_recovery(previous, "runtime_cpu_sustained_exceeded"):
                state["runtime_state"] = "degraded"
                state["status"] = "degraded"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + guard_reasons))
                state = _record_self_deviation_and_state(
                    state,
                    action="runtime_cpu_sustained_exceeded",
                    previous_state=previous,
                    reason_codes=state["reason_codes"],
                    evidence={
                        "resource_guard": resource_guard,
                        "backend_pid": state.get("backend_pid"),
                        "observed_behavior": f"CleanHouse backend CPU stayed above {resource_guard.get('thresholds', {}).get('cpu_degraded_percent')}%.",
                        "host": host,
                        "port": port,
                    },
                    runtime_dir=rdir,
                )

            if "runtime_stuck_watchdog" in guard_reasons and not _same_blocked_recovery(previous, "runtime_stuck_watchdog"):
                state["runtime_state"] = "degraded"
                state["status"] = "degraded"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + guard_reasons))
                state = _record_self_deviation_and_state(
                    state,
                    action="runtime_stuck_watchdog",
                    previous_state=previous,
                    reason_codes=state["reason_codes"],
                    evidence={
                        "resource_guard": resource_guard,
                        "backend_pid": state.get("backend_pid"),
                        "heartbeat_at": state.get("heartbeat_at"),
                        "heartbeat_fresh": state.get("heartbeat_fresh"),
                        "observed_behavior": "CleanHouse runtime heartbeat became stale while backend work was expected to progress.",
                        "host": host,
                        "port": port,
                    },
                    runtime_dir=rdir,
                )

            previous_reasons = set(previous.get("reason_codes", []) if isinstance(previous, dict) else [])
            current_reasons = set(state.get("reason_codes", []))
            if (
                "readiness_probe_failed" in current_reasons
                and "readiness_probe_failed" in previous_reasons
                and not _same_blocked_recovery(previous, "runtime_unresponsive")
            ):
                state["runtime_state"] = "degraded"
                state["status"] = "degraded"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["runtime_unresponsive"]))
                state = _record_self_deviation_and_state(
                    state,
                    action="runtime_unresponsive",
                    previous_state=previous,
                    reason_codes=state["reason_codes"],
                    evidence={
                        "last_probe": state.get("last_probe", {}),
                        "backend_pid": state.get("backend_pid"),
                        "observed_behavior": "CleanHouse readiness probe failed repeatedly while the backend process was alive.",
                        "host": host,
                        "port": port,
                    },
                    runtime_dir=rdir,
                )

            if state["runtime_state"] == "orphaned_listener":
                if state.get("owned_listener_pids"):
                    state = _terminate_owned_listeners(state)
                    state["supervisor_pid"] = os.getpid()
                    state["boot_id"] = boot_id
                    state["runtime_state"] = "recovering"
                    state["reason_codes"] = ["owned_orphan_listener_recovered"]
                    state["blocked_recovery"] = {}
                    write_state(state, rdir)
                    time.sleep(0.25)
                    continue
                write_state(state, rdir)
                time.sleep(SUPERVISOR_POLL_SECONDS)
                continue

            backend_dead = backend_process is not None and backend_process.poll() is not None
            if backend_dead:
                state["last_start_attempt"] = {
                    "status": "failed",
                    "attempted_at": _now_iso(),
                    "backend_pid": getattr(backend_process, "pid", None),
                    "interpreter_path": state["interpreter"].get("path"),
                    "returncode": backend_process.poll(),
                }
            needs_start = state["runtime_state"] in {"unhealthy", "stale_pid"} or backend_dead
            if needs_start:
                now = time.monotonic()
                restart_times = [item for item in restart_times if now - item <= RESTART_WINDOW_SECONDS]
                if not state["interpreter"].get("supervisor_compatible"):
                    state["runtime_state"] = "degraded"
                    state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["interpreter_resolution_failed"]))
                    state["last_start_attempt"] = {
                        "status": "blocked",
                        "attempted_at": _now_iso(),
                        "interpreter_path": state["interpreter"].get("path"),
                        "failure_reason": "interpreter_resolution_failed",
                    }
                    evidence = {
                        "interpreter": state["interpreter"],
                        "host": host,
                        "port": port,
                    }
                    if not _same_blocked_recovery(previous, "interpreter_resolution_failed"):
                        _record_recovery_and_state(
                            state,
                            action="interpreter_resolution_failed",
                            previous_state=previous,
                            reason_codes=state["reason_codes"],
                            evidence=evidence,
                            runtime_dir=rdir,
                        )
                    else:
                        write_state(state, rdir)
                    time.sleep(SUPERVISOR_POLL_SECONDS)
                    continue
                if not state["interpreter"].get("backend_compatible"):
                    state["runtime_state"] = "degraded"
                    state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["backend_dependencies_unavailable"]))
                    state["last_start_attempt"] = {
                        "status": "blocked",
                        "attempted_at": _now_iso(),
                        "interpreter_path": state["interpreter"].get("path"),
                        "failure_reason": "backend_dependencies_unavailable",
                    }
                    evidence = {
                        "interpreter": state["interpreter"],
                        "host": host,
                        "port": port,
                    }
                    if not _same_blocked_recovery(previous, "backend_dependencies_unavailable"):
                        _record_recovery_and_state(
                            state,
                            action="backend_dependencies_unavailable",
                            previous_state=previous,
                            reason_codes=state["reason_codes"],
                            evidence=evidence,
                            runtime_dir=rdir,
                        )
                    else:
                        write_state(state, rdir)
                    time.sleep(SUPERVISOR_POLL_SECONDS)
                    continue
                if len(restart_times) >= MAX_RESTARTS_PER_WINDOW:
                    state["runtime_state"] = "unhealthy"
                    exhausted_reason = "readiness_recovery_exhausted" if "readiness_probe_failed" in set(state.get("reason_codes", [])) else "restart_budget_exhausted"
                    state["reason_codes"] = sorted(set(state.get("reason_codes", []) + [exhausted_reason]))
                    state["last_start_attempt"] = {
                        "status": "blocked",
                        "attempted_at": _now_iso(),
                        "interpreter_path": state["interpreter"].get("path"),
                        "failure_reason": exhausted_reason,
                    }
                    if not _same_blocked_recovery(previous, exhausted_reason):
                        _record_self_deviation_and_state(
                            state,
                            action=exhausted_reason,
                            previous_state=previous,
                            reason_codes=state["reason_codes"],
                            evidence={
                                "restart_times": restart_times,
                                "restart_window_seconds": RESTART_WINDOW_SECONDS,
                                "max_restarts_per_window": MAX_RESTARTS_PER_WINDOW,
                                "observed_behavior": "CleanHouse exhausted its automatic restart budget.",
                            },
                            runtime_dir=rdir,
                        )
                    else:
                        write_state(state, rdir)
                    time.sleep(SUPERVISOR_POLL_SECONDS)
                    continue

                backoff = RESTART_BACKOFF_SECONDS[min(len(restart_times), len(RESTART_BACKOFF_SECONDS) - 1)]
                state["runtime_state"] = "recovering"
                state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["starting_backend"]))
                state["restart_count"] = int(state.get("restart_count", 0) or 0) + 1
                state["blocked_recovery"] = {}
                write_state(state, rdir)
                time.sleep(backoff)
                backend_boot_id = uuid.uuid4().hex
                try:
                    backend_process = _start_backend(str(state["interpreter"].get("path") or sys.executable), host, port, rdir, backend_boot_id)
                except Exception as exc:
                    backend_process = None
                    state["runtime_state"] = "degraded"
                    state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["backend_spawn_failed"]))
                    state["last_start_attempt"] = {
                        "status": "failed",
                        "attempted_at": _now_iso(),
                        "interpreter_path": state["interpreter"].get("path"),
                        "failure_reason": "backend_spawn_failed",
                        "error": str(exc) or exc.__class__.__name__,
                    }
                    if not _same_blocked_recovery(previous, "backend_spawn_failed"):
                        _record_recovery_and_state(
                            state,
                            action="backend_spawn_failed",
                            previous_state=previous,
                            reason_codes=state["reason_codes"],
                            evidence={"error": str(exc) or exc.__class__.__name__},
                            runtime_dir=rdir,
                        )
                    else:
                        write_state(state, rdir)
                    time.sleep(SUPERVISOR_POLL_SECONDS)
                    continue
                restart_times.append(time.monotonic())
                final_state = dict(state)
                final_state.update({
                    "backend_pid": backend_process.pid,
                    "backend_boot_id": backend_boot_id,
                    "runtime_state": "recovering",
                    "reason_codes": ["backend_spawned"],
                    "heartbeat_at": None,
                    "heartbeat_sequence": 0,
                    "blocked_recovery": {},
                    "last_start_attempt": {
                        "status": "spawned",
                        "attempted_at": _now_iso(),
                        "backend_pid": backend_process.pid,
                        "interpreter_path": state["interpreter"].get("path"),
                    },
                })
                receipt = persist_runtime_recovery(
                    action="backend_restart",
                    previous_state=previous,
                    final_state=final_state,
                    reason_codes=final_state["reason_codes"],
                    evidence={"backend_pid": backend_process.pid},
                )
                write_state(_append_recovery_id(final_state, receipt), rdir)
                continue

            if state["runtime_state"] in {"healthy", "recovering"}:
                state["blocked_recovery"] = {}
            write_state(state, rdir)
            time.sleep(SUPERVISOR_POLL_SECONDS)
    finally:
        previous = read_state(rdir)
        if backend_process is not None and backend_process.poll() is None:
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_process.kill()
        final_state = classify_state(previous, host=host, port=port, probe=False)
        final_state["runtime_state"] = "unhealthy"
        final_state["reason_codes"] = sorted(set(final_state.get("reason_codes", []) + ["supervisor_stopped"]))
        final_state["supervisor_pid"] = os.getpid()
        write_state(final_state, rdir)
    return 0


def _runtime_guard_hard_stop_active(state: dict[str, Any]) -> bool:
    resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
    reason_codes = {
        str(reason)
        for reason in [
            *(state.get("reason_codes") or []),
            *(resource_guard.get("reason_codes") or []),
        ]
        if str(reason)
    }
    return resource_guard.get("action") == "hard_stop" or "runtime_memory_ceiling_exceeded" in reason_codes


def _record_runtime_guard_hard_stop(
    state: dict[str, Any],
    *,
    previous_state: dict[str, Any],
    host: str,
    port: int,
    runtime_dir: Path,
) -> dict[str, Any]:
    resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
    guard_reasons = [str(reason) for reason in resource_guard.get("reason_codes", []) if str(reason)]
    stopped_backend = _terminate_pid_if_owned(state.get("backend_pid"))
    state["runtime_state"] = "unhealthy"
    state["status"] = "unhealthy"
    state["operator_ready"] = False
    state["reason_codes"] = sorted(set(state.get("reason_codes", []) + guard_reasons + ["runtime_memory_ceiling_exceeded", "runtime_self_deviation_restart_blocked"]))
    state["last_start_attempt"] = {
        "status": "blocked",
        "attempted_at": _now_iso(),
        "failure_reason": "runtime_memory_ceiling_exceeded",
    }
    evidence = {
        "resource_guard": resource_guard,
        "stopped_backend": stopped_backend,
        "backend_pid": state.get("backend_pid"),
        "observed_behavior": f"CleanHouse backend exceeded {resource_guard.get('thresholds', {}).get('max_rss_mb')} MB RSS.",
        "host": host,
        "port": port,
    }
    if not _same_blocked_recovery(previous_state, "runtime_memory_ceiling_exceeded"):
        return _record_self_deviation_and_state(
            state,
            action="runtime_memory_ceiling_exceeded",
            previous_state=previous_state,
            reason_codes=state["reason_codes"],
            evidence=evidence,
            runtime_dir=runtime_dir,
        )
    return write_state(state, runtime_dir)


def ensure_runtime(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout_seconds: float = 30.0) -> dict[str, Any]:
    rdir = _runtime_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    previous = read_state(rdir)
    current = classify_state(previous, host=host, port=port)
    current["interpreter"] = _interpreter_summary(runtime_env.resolve_interpreter(REPO_ROOT))
    current = _clear_stale_self_deviation_restart_block(current)
    if _runtime_guard_hard_stop_active(current):
        return _record_runtime_guard_hard_stop(current, previous_state=previous, host=host, port=port, runtime_dir=rdir)
    write_state(current, rdir)

    self_deviation_startup = _startup_self_deviation_classification(current)
    if _self_deviation_block_active(current) and self_deviation_startup["status"] == "recoverable":
        current["startup_recovery_allowed"] = {
            "self_deviation_id": (current.get("self_deviation") or {}).get("id"),
            "reason_codes": self_deviation_startup["reason_codes"],
            "issued_at": _now_iso(),
        }
        current["reason_codes"] = sorted(
            reason
            for reason in set(current.get("reason_codes", []))
            if reason != "runtime_self_deviation_restart_blocked"
        )
        write_state(current, rdir)
    elif _self_deviation_block_active(current) and _allow_self_deviation_restart():
        current = _acknowledge_self_deviation_for_restart(current)
        write_state(current, rdir)
    elif _self_deviation_block_active(current):
        current["runtime_state"] = "unhealthy"
        current["status"] = "unhealthy"
        current["reason_codes"] = sorted(set(current.get("reason_codes", []) + ["runtime_self_deviation_restart_blocked"]))
        current["operator_ready"] = False
        current["last_start_attempt"] = {
            "status": "blocked",
            "attempted_at": _now_iso(),
            "failure_reason": "runtime_self_deviation_restart_blocked",
        }
        return write_state(current, rdir)

    if current["runtime_state"] == "orphaned_listener" and current.get("foreign_listener_pids") and not current.get("owned_listener_pids"):
        current["reason_codes"] = sorted(set(current.get("reason_codes", []) + ["foreign_listener_blocked"]))
        evidence = {
            "foreign_listener_pids": current.get("foreign_listener_pids", []),
            "listener_details": current.get("listeners", []),
        }
        if not _same_blocked_recovery(current, "foreign_listener_blocked"):
            current = _record_recovery_and_state(
                current,
                action="foreign_listener_blocked",
                previous_state=read_state(rdir),
                reason_codes=current["reason_codes"],
                evidence=evidence,
                runtime_dir=rdir,
            )
        else:
            write_state(current, rdir)
        return current

    supervisor_pid = current.get("supervisor_pid")
    if not _pid_alive(supervisor_pid):
        interpreter_path = str(current.get("interpreter", {}).get("path") or "")
        if not current.get("interpreter", {}).get("supervisor_compatible") or not interpreter_path:
            current["runtime_state"] = "degraded"
            current["reason_codes"] = sorted(set(current.get("reason_codes", []) + ["interpreter_resolution_failed"]))
            current["last_start_attempt"] = {
                "status": "blocked",
                "attempted_at": _now_iso(),
                "interpreter_path": interpreter_path or None,
                "failure_reason": "interpreter_resolution_failed",
            }
            evidence = {
                "interpreter": current.get("interpreter", {}),
                "host": host,
                "port": port,
            }
            return _record_recovery_and_state(
                current,
                action="interpreter_resolution_failed",
                previous_state=read_state(rdir),
                reason_codes=current["reason_codes"],
                evidence=evidence,
                runtime_dir=rdir,
            )
        process = _spawn_supervisor_process(interpreter_path, host, port, rdir)
        current["supervisor_pid"] = process.pid
        current["runtime_state"] = "recovering"
        current["reason_codes"] = ["supervisor_spawned"]
        current["blocked_recovery"] = {}
        current["last_start_attempt"] = {
            "status": "spawned",
            "attempted_at": _now_iso(),
            "interpreter_path": interpreter_path,
            "supervisor_pid": process.pid,
        }
        receipt = persist_runtime_recovery(
            action="supervisor_spawn",
            previous_state=read_state(rdir),
            final_state=current,
            reason_codes=current["reason_codes"],
            evidence={"supervisor_pid": process.pid, "interpreter_path": interpreter_path},
        )
        current = _append_recovery_id(current, receipt)
        write_state(current, rdir)

    deadline = time.monotonic() + timeout_seconds
    last = current
    while time.monotonic() < deadline:
        previous = read_state(rdir)
        last = classify_state(previous, host=host, port=port)
        last["interpreter"] = _cached_interpreter_summary(previous)
        last = _clear_stale_self_deviation_restart_block(last)
        if _runtime_guard_hard_stop_active(last):
            return _record_runtime_guard_hard_stop(last, previous_state=previous, host=host, port=port, runtime_dir=rdir)
        last["operator_ready"] = _launch_ready(last)
        if last["runtime_state"] in {"healthy", "recovering"}:
            last["blocked_recovery"] = {}
        write_state(last, rdir)
        if _launch_ready(last) or last["runtime_state"] in {"healthy", "degraded"}:
            return last
        if last["runtime_state"] == "orphaned_listener" and last.get("foreign_listener_pids") and not last.get("owned_listener_pids"):
            return last
        if last["runtime_state"] == "unhealthy" and "restart_budget_exhausted" in set(last.get("reason_codes", [])):
            return last
        time.sleep(0.5)
    last["runtime_state"] = "unhealthy"
    last["reason_codes"] = sorted(set(last.get("reason_codes", []) + ["ensure_timeout"]))
    last["last_start_attempt"] = {
        "status": "failed",
        "attempted_at": _now_iso(),
        "interpreter_path": last.get("interpreter", {}).get("path"),
        "failure_reason": "ensure_timeout",
    }
    return _record_self_deviation_and_state(
        last,
        action="ensure_timeout",
        previous_state=read_state(rdir),
        reason_codes=last["reason_codes"],
        evidence={
            "timeout_seconds": timeout_seconds,
            "observed_behavior": f"CleanHouse runtime did not become ready within {timeout_seconds:g} seconds.",
        },
        runtime_dir=rdir,
    )


def _terminate_pid_if_owned(pid: Any, *, expected_supervisor: bool = False) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0 or not _pid_alive(value):
        return False
    info = _pid_info(value)
    command = str(info.get("command") or "")
    owned = "backend.runtime_supervisor" in command if expected_supervisor else _is_cleanhouse_owned_process(info)
    if not owned:
        return False
    try:
        os.kill(value, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(value):
            return True
        time.sleep(0.1)
    try:
        os.kill(value, signal.SIGKILL)
    except Exception:
        return False
    return True


def stop_runtime(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = classify_state(read_state(rdir), host=host, port=port, probe=False)
    stopped_backend = _terminate_pid_if_owned(previous.get("backend_pid"))
    stopped_supervisor = _terminate_pid_if_owned(previous.get("supervisor_pid"), expected_supervisor=True)
    stored_pids = {
        int(pid)
        for pid in (previous.get("backend_pid"), previous.get("supervisor_pid"))
        if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit())
    }
    stopped_owned_listeners: dict[str, bool] = {}
    for pid in previous.get("owned_listener_pids") or []:
        try:
            value = int(pid)
        except (TypeError, ValueError):
            continue
        if value in stored_pids:
            continue
        stopped_owned_listeners[str(value)] = _terminate_pid_if_owned(value)
    final = classify_state(read_state(rdir), host=host, port=port, probe=False)
    final["runtime_state"] = "unhealthy"
    final["status"] = "unhealthy"
    final["reason_codes"] = sorted(set(final.get("reason_codes", []) + ["runtime_stop_requested"]))
    receipt = persist_runtime_recovery(
        action="runtime_stop",
        previous_state=previous,
        final_state=final,
        reason_codes=final["reason_codes"],
        evidence={
            "stopped_backend": stopped_backend,
            "stopped_supervisor": stopped_supervisor,
            "stopped_owned_listeners": stopped_owned_listeners,
        },
    )
    final = _append_recovery_id(final, receipt)
    return write_state(final, rdir)


def acknowledge_self_deviation(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    rdir = runtime_dir or _runtime_dir()
    previous = classify_state(read_state(rdir), host=host, port=port, probe=False)
    acknowledged = _acknowledge_self_deviation_for_restart(dict(previous))
    acknowledged["runtime_state"] = "unhealthy"
    acknowledged["status"] = "unhealthy"
    acknowledged["operator_ready"] = False
    acknowledged["reason_codes"] = sorted(
        reason
        for reason in set(acknowledged.get("reason_codes", []))
        if reason not in SELF_DEVIATION_BLOCK_TYPES and reason != "runtime_self_deviation_restart_blocked"
    )
    acknowledged["reason_codes"].append("runtime_self_deviation_acknowledged")
    acknowledged["last_start_attempt"] = {
        "status": "operator_acknowledged_self_deviation",
        "attempted_at": _now_iso(),
        "failure_reason": None,
    }
    receipt = persist_runtime_recovery(
        action="runtime_self_deviation_acknowledge",
        previous_state=previous,
        final_state=acknowledged,
        reason_codes=acknowledged["reason_codes"],
        evidence={
            "self_deviation_id": (previous.get("self_deviation") or {}).get("id"),
            "evidence_artifact_path": (previous.get("self_deviation") or {}).get("evidence_artifact_path"),
            "receipt_artifact_path": (previous.get("self_deviation") or {}).get("receipt_artifact_path"),
        },
    )
    acknowledged = _append_recovery_id(acknowledged, receipt)
    return write_state(acknowledged, rdir)


def startup_preflight(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    acknowledge_self_deviation_restart: bool = False,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    """Classify user-facing startup before the launcher attempts any restart."""
    rdir = runtime_dir or _runtime_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    previous = read_state(rdir)
    if acknowledge_self_deviation_restart:
        previous = acknowledge_self_deviation(host, port, runtime_dir=rdir)

    stale_pids: dict[str, int] = {}

    def _clear_stale_pid(state: dict[str, Any], key: str, *, expected_supervisor: bool = False) -> None:
        raw = state.get(key)
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            return
        if pid <= 0:
            return
        if not _pid_alive(pid) or not _pid_owned_by_cleanhouse(pid, expected_supervisor=expected_supervisor):
            stale_pids[key] = pid
            state[key] = None

    cleaned_previous = dict(previous)
    _clear_stale_pid(cleaned_previous, "backend_pid")
    _clear_stale_pid(cleaned_previous, "supervisor_pid", expected_supervisor=True)
    if stale_pids:
        reasons = set(str(reason) for reason in cleaned_previous.get("reason_codes", []) if reason)
        reasons.update(f"{name}_stale_cleared" for name in stale_pids)
        reasons.add("stale_runtime_state_cleaned")
        cleaned_previous["reason_codes"] = sorted(reasons)
        cleaned_previous["runtime_state"] = cleaned_previous.get("runtime_state") or "unhealthy"
        cleaned_previous["status"] = cleaned_previous.get("runtime_state")
        previous = write_state(cleaned_previous, rdir)

    try:
        state = classify_state(previous, host=host, port=port, probe=False)
    except Exception as exc:
        invalid_state = {
            "schema": "cleanhouse.runtime_startup_preflight.v1",
            "status": "invalid_state",
            "should_start": False,
            "should_open_browser": False,
            "operator_ready": False,
            "host": host,
            "port": int(port),
            "reason_codes": ["startup_preflight_failed"],
            "error": str(exc) or exc.__class__.__name__,
            "state_path": str(state_path(rdir)),
            "updated_at": _now_iso(),
        }
        return invalid_state

    state["interpreter"] = _cached_interpreter_summary(state)
    if stale_pids:
        state["stale_pids_cleared"] = dict(stale_pids)
        state["reason_codes"] = sorted(set(state.get("reason_codes", []) + ["stale_runtime_state_cleaned"]))
    state = _clear_stale_self_deviation_restart_block(state)
    write_state(state, rdir)

    status = "ready_to_start"
    should_start = True
    should_open_browser = False
    next_action = "Start CleanHouse once and open the operator overview after readiness passes."
    startup_warning: dict[str, Any] = {}
    self_deviation_startup = _startup_self_deviation_classification(state)

    if state.get("runtime_state") == "orphaned_listener" and state.get("foreign_listener_pids") and not state.get("owned_listener_pids"):
        status = "foreign_listener_blocked"
        should_start = False
        next_action = "Stop the process already listening on the CleanHouse port, or choose another CLEANHOUSE_PORT."
    elif self_deviation_startup["status"] == "hard_blocking":
        status = "blocked_self_deviation"
        should_start = False
        next_action = "Resolve the current CleanHouse port/process condition, then try cleanhouse again."
    elif self_deviation_startup["status"] == "recoverable":
        state["startup_recovery_allowed"] = {
            "self_deviation_id": (state.get("self_deviation") or {}).get("id"),
            "reason_codes": self_deviation_startup["reason_codes"],
            "issued_at": _now_iso(),
        }
        write_state(state, rdir)
        startup_warning = {
            "type": "recoverable_self_deviation",
            "self_deviation": _self_deviation_summary(state),
            "reason_codes": self_deviation_startup["reason_codes"],
            "message": "Previous CleanHouse runtime self-deviation remains available for review; startup is allowed because the port/process state is clean.",
        }
    elif stale_pids:
        status = "stale_state_cleaned"

    return {
        "schema": "cleanhouse.runtime_startup_preflight.v1",
        "status": status,
        "should_start": should_start,
        "should_open_browser": should_open_browser,
        "operator_ready": False,
        "host": host,
        "port": int(port),
        "runtime_state": state.get("runtime_state"),
        "reason_codes": list(state.get("reason_codes") or []),
        "state_path": str(state_path(rdir)),
        "stale_pids_cleared": stale_pids,
        "self_deviation": _self_deviation_summary(state),
        "listener": {
            "pids": state.get("listener_pids", []),
            "owned_pids": state.get("owned_listener_pids", []),
            "foreign_pids": state.get("foreign_listener_pids", []),
            "details": state.get("listeners", []),
        },
        "last_start_attempt": state.get("last_start_attempt", {}),
        "blocked_recovery": state.get("blocked_recovery", {}),
        "startup_warning": startup_warning,
        "next_action": next_action,
        "updated_at": _now_iso(),
    }


def _launch_agent_observation() -> dict[str, Any]:
    if sys.platform != "darwin":
        return {"required": False, "installed": False, "loaded": False, "state": "not_applicable"}
    path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
    try:
        result = subprocess.run(
            ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        loaded = result.returncode == 0
        error = "" if loaded else (result.stderr or result.stdout).strip()[:512]
    except (OSError, subprocess.SubprocessError) as exc:
        loaded = False
        error = str(exc)[:512]
    installed = path.is_file()
    return {
        "required": True,
        "label": LAUNCH_AGENT_LABEL,
        "plist_path": str(path),
        "installed": installed,
        "loaded": loaded,
        "state": "loaded" if loaded else ("installed" if installed else "unavailable"),
        "error": error,
    }


def _runtime_payload_from_state(state: dict[str, Any], resolved_host: str, resolved_port: int) -> dict[str, Any]:
    readiness_contract = _operator_readiness_contract(state)
    operator_ready = bool(readiness_contract["satisfied"])
    runtime_state = str(state.get("runtime_state") or "unknown")
    return {
        "status": runtime_state,
        "runtime_state": runtime_state,
        "operator_ready": operator_ready,
        "bootstrap_ready": bool(state.get("bootstrap_ready_at")),
        "readiness_contract": readiness_contract,
        "valid_states": sorted(VALID_RUNTIME_STATES),
        "reason_codes": state.get("reason_codes", []),
        "supervisor": {
            "pid": state.get("supervisor_pid"),
            "alive": state.get("supervisor_alive"),
            "boot_id": state.get("boot_id"),
            "start_time": state.get("start_time"),
            "restart_count": state.get("restart_count", 0),
        },
        "launch_agent": state.get("launch_agent", {}),
        "backend": {
            "pid": state.get("backend_pid"),
            "alive": state.get("backend_alive"),
            "boot_id": state.get("backend_boot_id"),
            "host": resolved_host,
            "port": resolved_port,
        },
        "startup": {
            "phase": state.get("startup_phase"),
            "started_at": state.get("startup_started_at"),
            "bootstrap_started_at": state.get("bootstrap_started_at"),
            "bootstrap_ready_at": state.get("bootstrap_ready_at"),
            "warmup_started_at": state.get("warmup_started_at"),
            "warmup_ready_at": state.get("warmup_ready_at"),
        },
        "listener": {
            "pids": state.get("listener_pids", []),
            "owned_pids": state.get("owned_listener_pids", []),
            "foreign_pids": state.get("foreign_listener_pids", []),
            "details": state.get("listeners", []),
        },
        "heartbeat": {
            "at": state.get("heartbeat_at"),
            "sequence": state.get("heartbeat_sequence", 0),
            "fresh": state.get("heartbeat_fresh", False),
            "stale_after_seconds": HEARTBEAT_STALE_SECONDS,
        },
        "last_probe": state.get("last_probe", {}),
        "resource_guard": state.get("resource_guard", {}),
        "self_deviation": _self_deviation_summary(state),
        "interpreter": state.get("interpreter", {}),
        "last_start_attempt": state.get("last_start_attempt", {}),
        "blocked_recovery": state.get("blocked_recovery", {}),
        "recovery_receipts": state.get("recent_recovery_receipts", []),
        "state_path": str(state_path()),
        "updated_at": state.get("updated_at"),
    }


def _cached_state_for_probe(
    host: str | None = None,
    port: int | None = None,
) -> tuple[dict[str, Any], str, int]:
    stored = read_state()
    resolved_host = host or str(stored.get("host") or os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST) or DEFAULT_HOST)
    resolved_port = int(port or stored.get("port") or os.getenv("CLEANHOUSE_PORT", DEFAULT_PORT) or DEFAULT_PORT)
    state = _base_state(resolved_host, resolved_port, stored)
    reasons = {str(reason) for reason in state.get("reason_codes", []) if str(reason)}
    backend_alive = _pid_alive(state.get("backend_pid"))
    supervisor_alive = _pid_alive(state.get("supervisor_pid"))
    heartbeat_fresh = _heartbeat_fresh(state)
    pids = listener_pids(resolved_port, resolved_host)
    listeners = [_pid_info(pid) for pid in pids]
    owned_listener_pids = [item["pid"] for item in listeners if _is_cleanhouse_owned_process(item)]
    foreign_listener_pids = [item["pid"] for item in listeners if not _is_cleanhouse_owned_process(item)]
    resource_guard = state.get("resource_guard") if isinstance(state.get("resource_guard"), dict) else {}
    guard_reasons = {str(reason) for reason in resource_guard.get("reason_codes", []) if str(reason)}
    runtime_state = str(state.get("runtime_state") or "unhealthy")

    try:
        backend_pid = int(state.get("backend_pid"))
    except (TypeError, ValueError):
        backend_pid = None

    if not backend_alive:
        runtime_state = "unhealthy"
        reasons.add("backend_not_running")
    elif not supervisor_alive:
        runtime_state = "degraded"
        reasons.add("supervisor_not_running")
    elif not owned_listener_pids or backend_pid not in owned_listener_pids:
        runtime_state = "degraded"
        reasons.add("listener_not_ready")
    elif foreign_listener_pids:
        runtime_state = "degraded"
        reasons.add("foreign_listener_present")
    elif not heartbeat_fresh and state.get("heartbeat_at"):
        runtime_state = "degraded"
        reasons.add("heartbeat_stale")
    elif runtime_state not in {"degraded", "recovering"}:
        runtime_state = "healthy"

    if "runtime_memory_ceiling_exceeded" in guard_reasons:
        runtime_state = "unhealthy"
        reasons.add("runtime_memory_ceiling_exceeded")
    elif guard_reasons and runtime_state == "healthy":
        runtime_state = "degraded"
        reasons.update(guard_reasons)

    state.update({
        "runtime_state": runtime_state,
        "status": runtime_state,
        "reason_codes": sorted(reasons),
        "backend_alive": backend_alive,
        "supervisor_alive": supervisor_alive,
        "heartbeat_fresh": heartbeat_fresh,
        "listener_pids": pids,
        "listeners": listeners,
        "owned_listener_pids": owned_listener_pids,
        "foreign_listener_pids": foreign_listener_pids,
        "interpreter": _cached_interpreter_summary(stored),
        "updated_at": stored.get("updated_at"),
    })
    state = _clear_stale_self_deviation_restart_block(state)
    if state["runtime_state"] in {"healthy", "recovering"}:
        state["blocked_recovery"] = {}
    return state, resolved_host, resolved_port


def cached_runtime_payload(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    state, resolved_host, resolved_port = _cached_state_for_probe(host, port)
    return _runtime_payload_from_state(state, resolved_host, resolved_port)


def _read_only_runtime_state(
    host: str | None = None,
    port: int | None = None,
    *,
    probe: bool = False,
) -> tuple[dict[str, Any], str, int, dict[str, Any]]:
    stored = read_state()
    resolved_host = host or str(stored.get("host") or os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST) or DEFAULT_HOST)
    resolved_port = int(port or stored.get("port") or os.getenv("CLEANHOUSE_PORT", DEFAULT_PORT) or DEFAULT_PORT)
    state = classify_state(stored, host=resolved_host, port=resolved_port, probe=probe)
    state["launch_agent"] = _launch_agent_observation()
    state["interpreter"] = _cached_interpreter_summary(stored)
    state = _clear_stale_self_deviation_restart_block(state)
    if state["runtime_state"] in {"healthy", "recovering"}:
        state["blocked_recovery"] = {}
    return state, resolved_host, resolved_port, stored


def current_runtime_payload(
    host: str | None = None,
    port: int | None = None,
    *,
    probe: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    if not probe and not write:
        return cached_runtime_payload(host, port)
    state, resolved_host, resolved_port, _stored = _read_only_runtime_state(host, port, probe=probe)
    if write:
        write_state(state)
    return _runtime_payload_from_state(state, resolved_host, resolved_port)


def readiness_payload(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    state, resolved_host, resolved_port = _cached_state_for_probe(host, port)
    runtime_state = str(state.get("runtime_state") or "unknown")
    readiness_contract = _operator_readiness_contract(state)
    ready = bool(readiness_contract["satisfied"])
    runtime = _runtime_payload_from_state(state, resolved_host, resolved_port)
    reason_codes = sorted({
        *[str(reason) for reason in state.get("reason_codes", []) if str(reason)],
        *[f"operator_readiness_{name}" for name in readiness_contract["failed_checks"]],
    })
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "bootstrap_ready": bool(state.get("bootstrap_ready_at")),
        "runtime_state": runtime_state,
        "reason_codes": reason_codes,
        "readiness_contract": readiness_contract,
        "runtime": runtime,
        "backend": runtime.get("backend", {}),
        "supervisor": runtime.get("supervisor", {}),
        "listener": runtime.get("listener", {}),
        "heartbeat": runtime.get("heartbeat", {}),
        "resource_guard": runtime.get("resource_guard", {}),
        "self_deviation": runtime.get("self_deviation", {}),
        "state_path": str(state_path()),
        "updated_at": state.get("updated_at"),
    }


def register_backend_start(host: str, port: int) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = read_state(rdir)
    now = _now_iso()
    state = _base_state(host, port, previous)
    state.update({
        "runtime_state": "recovering",
        "reason_codes": ["backend_started"],
        "backend_pid": os.getpid(),
        "backend_boot_id": os.getenv("CLEANHOUSE_BACKEND_BOOT_ID", uuid.uuid4().hex),
        "host": host,
        "port": int(port),
        "startup_phase": "booting",
        "startup_started_at": previous.get("startup_started_at") or now,
        "bootstrap_started_at": previous.get("bootstrap_started_at") or now,
        "heartbeat_at": now,
        "heartbeat_sequence": int(previous.get("heartbeat_sequence", 0) or 0) + 1,
        "blocked_recovery": {},
    })
    state["interpreter"] = _cached_interpreter_summary(previous)
    return write_state(state, rdir)


def record_backend_heartbeat(host: str, port: int) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = read_state(rdir)
    state = _base_state(host, port, previous)
    state.update({
        "backend_pid": os.getpid(),
        "host": host,
        "port": int(port),
        "heartbeat_at": _now_iso(),
        "heartbeat_sequence": int(previous.get("heartbeat_sequence", 0) or 0) + 1,
    })
    state["interpreter"] = _cached_interpreter_summary(previous)
    return write_state(state, rdir)


def mark_backend_bootstrap_ready(host: str, port: int) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = read_state(rdir)
    now = _now_iso()
    state = _base_state(host, port, previous)
    state.update({
        "backend_pid": os.getpid(),
        "backend_alive": True,
        "host": host,
        "port": int(port),
        "startup_phase": "bootstrap_ready",
        "bootstrap_started_at": previous.get("bootstrap_started_at") or previous.get("startup_started_at") or now,
        "bootstrap_ready_at": previous.get("bootstrap_ready_at") or now,
    })
    state["interpreter"] = _cached_interpreter_summary(previous)
    state["operator_ready"] = _launch_ready(state)
    return write_state(state, rdir)


def mark_backend_warmup_started(host: str, port: int) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = read_state(rdir)
    now = _now_iso()
    state = _base_state(host, port, previous)
    state.update({
        "backend_pid": os.getpid(),
        "backend_alive": True,
        "host": host,
        "port": int(port),
        "startup_phase": "warming",
        "warmup_started_at": previous.get("warmup_started_at") or now,
    })
    state["interpreter"] = _cached_interpreter_summary(previous)
    state["operator_ready"] = _launch_ready(state)
    return write_state(state, rdir)


def mark_backend_warmup_complete(
    host: str,
    port: int,
    *,
    runtime_state: str = "healthy",
    reason_codes: Iterable[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rdir = _runtime_dir()
    previous = read_state(rdir)
    now = _now_iso()
    state = _base_state(host, port, previous)
    final_state = runtime_state if runtime_state in VALID_RUNTIME_STATES else "degraded"
    merged_reasons = sorted({str(reason) for reason in [*(state.get("reason_codes") or []), *reason_codes] if str(reason)})
    state.update({
        "backend_pid": os.getpid(),
        "backend_alive": True,
        "host": host,
        "port": int(port),
        "startup_phase": "warm" if final_state == "healthy" else "degraded",
        "warmup_started_at": previous.get("warmup_started_at") or previous.get("bootstrap_ready_at") or now,
        "warmup_ready_at": previous.get("warmup_ready_at") or now,
        "runtime_state": final_state,
        "status": final_state,
        "reason_codes": merged_reasons,
    })
    if details:
        state["startup_details"] = {str(key): value for key, value in details.items()}
    state["interpreter"] = _cached_interpreter_summary(previous)
    state["operator_ready"] = _launch_ready(state)
    return write_state(state, rdir)


def register_backend_stop(host: str, port: int) -> dict[str, Any]:
    previous = read_state()
    state = _base_state(host, port, previous)
    state.update({
        "runtime_state": "unhealthy",
        "reason_codes": ["backend_stopped"],
        "backend_pid": os.getpid(),
    })
    state["interpreter"] = _cached_interpreter_summary(previous)
    return write_state(state)


def start_backend_heartbeat(host: str, port: int) -> None:
    global _HEARTBEAT_THREAD
    if _HEARTBEAT_THREAD is not None and _HEARTBEAT_THREAD.is_alive():
        return
    _HEARTBEAT_STOP.clear()

    def _loop() -> None:
        while not _HEARTBEAT_STOP.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                record_backend_heartbeat(host, port)
            except Exception:
                continue

    state = read_state()
    if not state.get("startup_started_at") or not state.get("backend_pid"):
        register_backend_start(host, port)
    else:
        record_backend_heartbeat(host, port)
    candidate = threading.Thread(target=_loop, name="cleanhouse-runtime-heartbeat", daemon=True)
    try:
        candidate.start()
    except Exception:
        _HEARTBEAT_STOP.set()
        _HEARTBEAT_THREAD = None
        raise
    _HEARTBEAT_THREAD = candidate


def stop_backend_heartbeat(host: str, port: int) -> None:
    _HEARTBEAT_STOP.set()
    register_backend_stop(host, port)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "supervise", "status", "stop", "acknowledge-self-deviation", "preflight"):
        sp = sub.add_parser(name)
        sp.add_argument("--host", default=os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST) or DEFAULT_HOST)
        sp.add_argument("--port", type=int, default=int(os.getenv("CLEANHOUSE_PORT", DEFAULT_PORT) or DEFAULT_PORT))
    sub.choices["start"].add_argument("--timeout", type=float, default=5.0)
    sub.choices["preflight"].add_argument("--acknowledge-self-deviation", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "supervise":
        return supervisor_loop(args.host, args.port)
    if args.command == "start":
        payload = ensure_runtime(args.host, args.port, timeout_seconds=args.timeout)
        _print_json(payload)
        return 0 if payload.get("ready") is True or payload.get("operator_ready") is True else 1
    if args.command == "status":
        _print_json(current_runtime_payload(args.host, args.port))
        return 0
    if args.command == "stop":
        _print_json(stop_runtime(args.host, args.port))
        return 0
    if args.command == "acknowledge-self-deviation":
        _print_json(acknowledge_self_deviation(args.host, args.port))
        return 0
    if args.command == "preflight":
        payload = startup_preflight(
            args.host,
            args.port,
            acknowledge_self_deviation_restart=args.acknowledge_self_deviation,
        )
        _print_json(payload)
        return 0 if payload.get("should_start") is True else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
