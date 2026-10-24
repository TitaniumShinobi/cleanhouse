"""Minimal server lifecycle adapter for the bounded Network collector.

The capture-engine bundle is intentionally outside this boundary.  Until that
separate package is reviewed and connected, the runtime reports an exact
degraded state and the collector watchdog retries with bounded backoff.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any

from backend import events
from backend.network_collector import CaptureEngineUnavailable, NetworkCollectorSupervisor


_LOCK = threading.RLock()
_COLLECTOR: NetworkCollectorSupervisor | None = None
_HISTORY_STATE: dict[str, Any] = {
    "status": "stopped",
    "reason_code": "network_history_stopped",
    "retention": "local_event_spine",
}


def _capture_command_factory() -> dict[str, Any]:
    raise CaptureEngineUnavailable(
        "reviewed capture-engine bundle is not installed in this Network Core boundary"
    )


def _parse_capture_line(line: str, interface: str) -> dict[str, Any] | None:
    """Parse a future reviewed engine's JSON line without inventing packets."""
    text = str(line or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("interface", interface)
    return payload


def _enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(event)
    enriched.setdefault("provider", "network_core")
    enriched.setdefault("capture_authenticated", False)
    return enriched


def _persist_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    envelope_type = str(envelope.get("type") or "collector.receipt")
    event = envelope.get("event") if isinstance(envelope.get("event"), dict) else {}
    cursor = str(envelope.get("cursor") or event.get("cursor") or uuid.uuid4().hex)
    is_packet = envelope_type == "network.event"
    events.insert_event(
        event_type="network_packet" if is_packet else "network_collector_receipt",
        path="network://collector",
        summary=(
            "Network packet observed by the reviewed capture engine"
            if is_packet
            else f"Network collector receipt: {envelope_type}"
        ),
        source_surface="network_collector",
        actor_type="system",
        evidence_level="observed",
        collector_status=str(event.get("state") or "observed"),
        scope_relation="network_core",
        source_event_key=f"network-core:{cursor}:{envelope_type}",
        provider="network_core",
        data={"envelope": envelope},
    )
    return envelope


def _new_collector() -> NetworkCollectorSupervisor:
    return NetworkCollectorSupervisor(
        command_factory=_capture_command_factory,
        parse_line=_parse_capture_line,
        enrich_event=_enrich_event,
        persist_event=_persist_envelope,
        persist_receipt=_persist_envelope,
        boot_id=os.environ.get("CLEANHOUSE_BOOT_ID", "").strip() or uuid.uuid4().hex,
        replay_size=2048,
        subscriber_queue_size=256,
        watchdog_backoff_seconds=1.0,
    )


def start_network_history_service() -> dict[str, Any]:
    """Initialize the existing local event spine used for Network history."""
    global _HISTORY_STATE
    events.init_db()
    with _LOCK:
        _HISTORY_STATE = {
            "status": "running",
            "reason_code": "",
            "retention": "local_event_spine",
        }
        return dict(_HISTORY_STATE)


def stop_network_history_service() -> dict[str, Any]:
    global _HISTORY_STATE
    with _LOCK:
        _HISTORY_STATE = {
            "status": "stopped",
            "reason_code": "network_history_stopped",
            "retention": "local_event_spine",
        }
        return dict(_HISTORY_STATE)


def network_history_status() -> dict[str, Any]:
    with _LOCK:
        return dict(_HISTORY_STATE)


def start_network_collector_service(*, startup_timeout: float = 1.0) -> dict[str, Any]:
    """Start once and return the collector's bounded initial lifecycle result."""
    global _COLLECTOR
    with _LOCK:
        if _COLLECTOR is None:
            _COLLECTOR = _new_collector()
        collector = _COLLECTOR
    collector.start()
    health = collector.wait_for_initial_state(timeout=startup_timeout)
    if health.get("state") == "starting":
        health = dict(health)
        health["status"] = "degraded"
        health["reason_code"] = "capture_start_timeout"
        return health
    health = dict(health)
    health["status"] = str(health.get("state") or "degraded")
    return health

def stop_network_collector_service(*, timeout: float = 5.0) -> dict[str, Any]:
    global _COLLECTOR
    with _LOCK:
        collector = _COLLECTOR
        _COLLECTOR = None
    if collector is None:
        return {"status": "stopped", "joined": True, "reason_code": ""}
    receipt = collector.stop(timeout=timeout)
    event = receipt.get("event") if isinstance(receipt.get("event"), dict) else {}
    return {
        "status": str(event.get("state") or "stopped"),
        "joined": bool(event.get("joined")),
        "reason_code": "" if event.get("joined") else "collector_stop_timeout",
    }


def network_collector_health() -> dict[str, Any]:
    with _LOCK:
        collector = _COLLECTOR
    if collector is None:
        return {
            "status": "stopped",
            "state": "stopped",
            "reason_code": "collector_not_started",
            "thread_alive": False,
        }
    health = dict(collector.health())
    health["status"] = str(health.get("state") or "degraded")
    return health

# Capture-engine packaging intentionally remains a separate reviewed boundary.
