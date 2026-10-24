#!/usr/bin/env python3
"""Host-local runtime notification probe for CleanHouse."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from backend.api import cleanhouse_monitoring as monitoring_module
from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter


def _notification_snapshot(notification: dict[str, Any]) -> dict[str, Any]:
    metadata = notification.get("metadata", {}) if isinstance(notification.get("metadata"), dict) else {}
    native = metadata.get("native_delivery_result", {}) if isinstance(metadata.get("native_delivery_result"), dict) else {}
    visibility = metadata.get("visibility", {}) if isinstance(metadata.get("visibility"), dict) else {}
    return {
        "id": notification.get("id"),
        "notification_type": notification.get("notification_type"),
        "session_id": notification.get("session_id"),
        "severity": notification.get("severity"),
        "summary": notification.get("summary"),
        "evidence_refs": notification.get("evidence_refs", []),
        "click_url": metadata.get("click_url"),
        "native_delivery_result": native,
        "native_backend": native.get("backend"),
        "native_status": native.get("status"),
        "visibility": visibility,
    }


def _latest_by_type(adapter: CleanHouseMonitoringAdapter, session_id: str, notification_type: str) -> dict[str, Any] | None:
    notifications = adapter.get_operator_notifications(session_id=session_id).get("notifications", [])
    for notification in notifications:
        if notification.get("notification_type") == notification_type:
            return notification
    return None


def _iter_probe_notifications(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []
    for result in results:
        items = result.get("notifications", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                notifications.append(item)
    return notifications


def _native_result(notification: dict[str, Any]) -> dict[str, Any]:
    native = notification.get("native_delivery_result", {})
    return native if isinstance(native, dict) else {}


def _dual_backend_fanout_detected(results: list[dict[str, Any]]) -> bool:
    for notification in _iter_probe_notifications(results):
        native = _native_result(notification)
        attempt_backends: set[str] = set()
        attempts = native.get("attempts", [])
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict):
                    backend = str(attempt.get("backend", "") or "").strip()
                    if backend:
                        attempt_backends.add(backend)
        backend = str(native.get("backend", "") or "").strip()
        if backend:
            attempt_backends.add(backend)
        if len(attempt_backends) >= 2:
            return True
    return False


def _hard_interrupt_reminder_capped(results: list[dict[str, Any]]) -> bool:
    for notification in _iter_probe_notifications(results):
        visibility = notification.get("visibility", {}) if isinstance(notification.get("visibility"), dict) else {}
        if visibility.get("reminder_suppressed") and visibility.get("suppressed_reason") == "max_native_reminders_reached":
            return True
    return False


def _scope_drift_duplicate_suppressed(results: list[dict[str, Any]]) -> bool:
    for result in results:
        if result.get("trigger_action") != "scope_drift_duplicate_emit_paths":
            continue
        first_id = str(result.get("first_id", "") or "")
        second_id = str(result.get("second_id", "") or "")
        notifications = result.get("notifications", [])
        scope_drift_count = 0
        if isinstance(notifications, list):
            for item in notifications:
                if isinstance(item, dict) and str(item.get("notification_type", "") or "").strip() == "scope_drift_detected":
                    scope_drift_count += 1
        if first_id and first_id == second_id and scope_drift_count == 1:
            return True
    return False


def run_probe(output_path: Path, *, allow_native_notifications: bool = False) -> dict[str, Any]:
    os.environ["CLEANHOUSE_NATIVE_NOTIFICATIONS"] = "1" if allow_native_notifications else "0"
    adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
    adapter.update_settings(
        {
            "notification_policy": {
                "fanout_all_backends": False,
                "hard_interrupt_reminder_seconds": 300,
                "max_native_reminders_per_notification": 2,
                "cooldown_bypass_types": [],
            }
        }
    )
    results: list[dict[str, Any]] = []
    run_nonce = uuid.uuid4().hex[:8]

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        requested = root / "assets" / "avatars" / "requested"
        substituted = root / "assets" / "avatars" / "substituted"
        requested.mkdir(parents=True)
        substituted.mkdir(parents=True)

        drift_session = f"probe-drift-session-{run_nonce}"
        prompt = adapter.submit_prompt(
            text="Mutate only requested avatar scope",
            context="native notification probe",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id=drift_session,
            objective_id="objective-probe-drift",
        )
        (requested / "avatar.png").write_text("requested-v1", encoding="utf-8")
        deleted_target = substituted / "avatar.png"
        deleted_target.write_text("substituted-v1", encoding="utf-8")
        before = adapter.create_snapshot(str(root), "before-probe", session_id=drift_session)
        deleted_target.unlink()
        after = adapter.create_snapshot(str(root), "after-probe", session_id=drift_session)
        adapter.compute_diff(before["id"], after["id"], session_id=drift_session)
        adapter.build_timeline(drift_session)
        adapter.correlate(drift_session)
        adapter.classify(drift_session)
        adapter.generate_alerts(drift_session)
        workstation = adapter.get_workstation(drift_session)
        receipt = adapter.build_receipt(drift_session)

        results.append({
            "trigger_action": "scope_drift_and_critical_mutation",
            "session_id": drift_session,
            "prompt_id": prompt.get("id"),
            "receipt_id": receipt.get("id"),
            "notifications": [
                _notification_snapshot(item)
                for item in workstation.get("notifications", [])
                if item.get("notification_type") in {"scope_drift_detected", "critical_filesystem_mutation", "rollback_needed"}
            ],
        })

    previous_pickup_failure = os.environ.get("CLEANHOUSE_CONTINUITY_PICKUP_FAILURE")
    os.environ["CLEANHOUSE_CONTINUITY_PICKUP_FAILURE"] = "pickup_runtime_failure_probe"
    continuity_session = f"probe-continuity-session-{run_nonce}"
    adapter.start_operator_session(
        {
            "session_id": continuity_session,
            "objective_id": "objective-probe-continuity",
            "summary": "continuity native probe",
        }
    )
    continuity_workstation = adapter.get_workstation(continuity_session)
    continuity_notification = _latest_by_type(adapter, continuity_session, "continuity_degraded")
    results.append(
        {
            "trigger_action": "continuity_recovery_failure",
            "session_id": continuity_session,
            "notifications": [
                _notification_snapshot(continuity_notification) if continuity_notification else None,
            ],
            "workstation_status": continuity_workstation.get("status"),
        }
    )
    if previous_pickup_failure is None:
        os.environ.pop("CLEANHOUSE_CONTINUITY_PICKUP_FAILURE", None)
    else:
        os.environ["CLEANHOUSE_CONTINUITY_PICKUP_FAILURE"] = previous_pickup_failure

    bundle_session = f"probe-bundle-session-{run_nonce}"
    adapter.submit_prompt(
        text="bundle verification probe",
        context="native replay signature failure probe",
        scope="src/",
        tool_identity="Codex",
        session_id=bundle_session,
        objective_id="objective-probe-bundle",
    )
    adapter.build_timeline(bundle_session)
    bundle_receipt = adapter.build_receipt(bundle_session)
    exported = adapter.export_receipt_timeline_bundle(bundle_receipt["id"])
    tampered = json.loads(json.dumps(exported["bundle"]))
    tampered["integrity"]["bundle_hash"] = "tampered"
    verification = adapter.verify_receipt_timeline_bundle(tampered)
    replay_failure_notification = _latest_by_type(adapter, bundle_session, "replay_or_signature_failure")
    results.append(
        {
            "trigger_action": "replay_signature_verification_failure",
            "session_id": bundle_session,
            "verification_status": verification.get("status"),
            "notifications": [
                _notification_snapshot(replay_failure_notification) if replay_failure_notification else None,
            ],
        }
    )

    duplicate_scope_session = f"probe-drift-duplicate-session-{run_nonce}"
    shared_scope_refs = [
        f"local://cleanhouse/receipt/receipt:probe-scope-duplicate-{run_nonce}",
        f"local://cleanhouse/diff/diff:probe-scope-duplicate-{run_nonce}",
    ]
    scope_from_workstation = adapter._ensure_operator_notification(  # noqa: SLF001
        notification_type="scope_drift_detected",
        session_id=duplicate_scope_session,
        objective_id="objective-probe-scope-drift-duplicate",
        severity="warning",
        summary="scope drift duplicate probe workstation path",
        evidence_refs=shared_scope_refs,
        source="workstation",
        metadata={"receipt_id": f"receipt:probe-scope-duplicate-{run_nonce}"},
    )
    scope_from_alert = adapter._ensure_operator_notification(  # noqa: SLF001
        notification_type="scope_drift_detected",
        session_id=duplicate_scope_session,
        objective_id="objective-probe-scope-drift-duplicate",
        severity="warning",
        summary="scope drift duplicate probe alert path",
        evidence_refs=list(reversed(shared_scope_refs)),
        source="alert",
        metadata={"alert_id": f"alert:probe-scope-duplicate-{run_nonce}"},
    )
    duplicate_scope_notifications = adapter.get_operator_notifications(session_id=duplicate_scope_session).get("notifications", [])
    results.append(
        {
            "trigger_action": "scope_drift_duplicate_emit_paths",
            "session_id": duplicate_scope_session,
            "first_id": scope_from_workstation.id if scope_from_workstation else "",
            "second_id": scope_from_alert.id if scope_from_alert else "",
            "notifications": [
                _notification_snapshot(item)
                for item in duplicate_scope_notifications
                if item.get("notification_type") == "scope_drift_detected"
            ],
        }
    )

    adapter.update_settings(
        {
            "notification_policy": {
                "fanout_all_backends": False,
                "hard_interrupt_reminder_seconds": 15,
                "max_native_reminders_per_notification": 1,
                "cooldown_bypass_types": ["codex_prompt_sent"],
                "codex_activity_native_enabled": True,
            }
        }
    )
    reminder_session = f"probe-reminder-session-{run_nonce}"
    reminder_created = adapter._ensure_operator_notification(  # noqa: SLF001
        notification_type="codex_prompt_sent",
        session_id=reminder_session,
        objective_id="objective-probe-reminder-cap",
        severity="info",
        summary="hard interrupt reminder cap probe",
        evidence_refs=[f"local://cleanhouse/reminder/{run_nonce}/prompt"],
        source="probe",
    )
    if reminder_created is not None:
        metadata = dict(reminder_created.metadata)
        visibility = dict(metadata.get("visibility", {}))
        visibility["next_reminder_at"] = "2000-01-01T00:00:00"
        metadata["visibility"] = visibility
        due = monitoring_module.OperatorNotificationRecord(
            id=reminder_created.id,
            notification_type=reminder_created.notification_type,
            session_id=reminder_created.session_id,
            objective_id=reminder_created.objective_id,
            severity=reminder_created.severity,
            summary=reminder_created.summary,
            evidence_refs=reminder_created.evidence_refs,
            created_at=reminder_created.created_at,
            acknowledged=reminder_created.acknowledged,
            acknowledged_at=reminder_created.acknowledged_at,
            source=reminder_created.source,
            metadata=metadata,
        )
        adapter._operator_notifications[due.id] = due  # noqa: SLF001
        adapter._run_notification_visibility_cycle()  # noqa: SLF001
        first_pass = adapter.get_operator_notifications(reminder_session).get("notifications", [])
        first_pass_notification = first_pass[0] if first_pass else None
        if isinstance(first_pass_notification, dict):
            metadata2 = dict(first_pass_notification.get("metadata", {}))
            visibility2 = dict(metadata2.get("visibility", {}))
            visibility2["next_reminder_at"] = "2000-01-01T00:00:00"
            metadata2["visibility"] = visibility2
            due_again = monitoring_module.OperatorNotificationRecord(
                id=str(first_pass_notification.get("id", "")),
                notification_type=str(first_pass_notification.get("notification_type", "")),
                session_id=str(first_pass_notification.get("session_id", "")),
                objective_id=first_pass_notification.get("objective_id"),
                severity=str(first_pass_notification.get("severity", "info")),
                summary=str(first_pass_notification.get("summary", "")),
                evidence_refs=tuple(first_pass_notification.get("evidence_refs", [])),
                created_at=str(first_pass_notification.get("created_at", "")),
                acknowledged=bool(first_pass_notification.get("acknowledged", False)),
                acknowledged_at=first_pass_notification.get("acknowledged_at"),
                source=str(first_pass_notification.get("source", "")),
                metadata=metadata2,
            )
            adapter._operator_notifications[due_again.id] = due_again  # noqa: SLF001
            adapter._run_notification_visibility_cycle()  # noqa: SLF001
    reminder_notifications = adapter.get_operator_notifications(session_id=reminder_session).get("notifications", [])
    results.append(
        {
            "trigger_action": "hard_interrupt_reminder_cap",
            "session_id": reminder_session,
            "notifications": [
                _notification_snapshot(item)
                for item in reminder_notifications
                if item.get("notification_type") == "codex_prompt_sent"
            ],
        }
    )

    adapter._ensure_collector_failure_notifications(  # noqa: SLF001
        {
            "surfaces": {
                "filesystem_watcher": {
                    "collector_status": "failure",
                }
            }
        }
    )
    collector_name = f"runtime_event_writer_{run_nonce}"
    first = adapter._ensure_operator_notification(  # noqa: SLF001
        notification_type="collector_failure",
        session_id="runtime-global",
        objective_id=None,
        severity="critical",
        summary="collector failure probe",
        evidence_refs=[f"local://cleanhouse/collector/probe/{collector_name}/a"],
        source="probe",
        metadata={"collector_name": collector_name, "collector_status": "failure"},
    )
    second = adapter._ensure_operator_notification(  # noqa: SLF001
        notification_type="collector_failure",
        session_id="runtime-global",
        objective_id=None,
        severity="critical",
        summary="collector failure probe",
        evidence_refs=[f"local://cleanhouse/collector/probe/{collector_name}/b"],
        source="probe",
        metadata={"collector_name": collector_name, "collector_status": "failure"},
    )
    results.append(
        {
            "trigger_action": "collector_failure_and_cooldown",
            "session_id": "runtime-global",
            "notifications": [
                _notification_snapshot(first.to_dict()) if first else None,
                _notification_snapshot(second.to_dict()) if second else None,
            ],
            "cooldown_suppressed": bool(
                second and second.metadata.get("native_delivery_result", {}).get("status") == "skipped"
            ),
        }
    )

    payload = {
        "status": "ok",
        "native_notifications_enabled": os.getenv("CLEANHOUSE_NATIVE_NOTIFICATIONS", "1"),
        "results": results,
        "dual_backend_fanout_detected": _dual_backend_fanout_detected(results),
        "hard_interrupt_reminder_capped": _hard_interrupt_reminder_capped(results),
        "scope_drift_duplicate_suppressed": _scope_drift_duplicate_suppressed(results),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(Path("/tmp/cleanhouse-native-notification-probe.json")),
    )
    parser.add_argument(
        "--allow-native-notifications",
        action="store_true",
        help="Enable desktop notifications during probe (default is disabled).",
    )
    args = parser.parse_args()
    payload = run_probe(
        Path(args.output).expanduser().resolve(),
        allow_native_notifications=bool(args.allow_native_notifications),
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
