# CLEANHOUSE Notification Truth Inventory

## NOTIFICATION INVENTORY

| file | function | notification_type | trigger | runtime backing event | deep-link target | current behavior | classification |
|---|---|---|---|---|---|---|---|
| `backend/api/cleanhouse_monitoring.py:8088` | `_derive_workstation_notifications` | `scope_drift_detected` | runtime callsite | `receipt_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:8105` | `_derive_workstation_notifications` | `excessive_traversal` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8125` | `_derive_workstation_notifications` | `scope_drift_detected` | runtime callsite | `alert_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:8136` | `_derive_workstation_notifications` | `excessive_traversal` | runtime callsite | `alert_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8155` | `_derive_workstation_notifications` | `approval_required` | runtime callsite | `approval_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8169` | `_derive_workstation_notifications` | `receipt_finalized` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:2508` | `_emit_codex_active_context_response_notification` | `codex_response_observed` | runtime callsite | `prompt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:3355` | `_emit_runtime_transition_notification` | `<dynamic>` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:9896` | `_ensure_collector_failure_notifications` | `collector_failure` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8206` | `_ensure_continuity_degraded_notification` | `continuity_degraded` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8432` | `_ensure_critical_filesystem_mutation_notifications` | `critical_filesystem_mutation` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:7181` | `_ensure_operator_notification` | `session_ended` | runtime callsite | `domain_event_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:7219` | `_ensure_operator_notification` | `session_started` | runtime callsite | `domain_event_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:12015` | `_ensure_replay_or_signature_failure_notification` | `replay_or_signature_failure` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:10093` | `_ensure_rollback_needed_notification` | `rollback_needed` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:2709` | `_on_command_completed` | `destructive_command_attempt` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:2728` | `_on_command_completed` | `codex_response_observed` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:10650` | `advance_qpb_case` | `qpb_transition` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:11721` | `build_receipt` | `receipt_finalized` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:8539` | `create_approval_queue_item` | `approval_required` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:3861` | `emit_domain_event` | `<dynamic>` | runtime callsite | `domain_event_id` | `/incident-receipt` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:10332` | `execute_rollback` | `runtime_recovery_failure` | runtime callsite | `receipt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:9762` | `generate_alerts` | `scope_drift_detected` | runtime callsite | `alert_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:4837` | `send_test_operator_notification` | `<dynamic>` | runtime callsite | `missing` | `/dashboard` | validation_only (persisted, dispatch suppressed by default) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:4645` | `start_operator_session` | `session_started` | runtime callsite | `session_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:4691` | `stop_operator_session` | `session_ended` | runtime callsite | `session_id` | `/dashboard` | production_operator (runtime-backed) | **VALID** |
| `backend/api/cleanhouse_monitoring.py:4585` | `submit_prompt` | `codex_prompt_sent` | runtime callsite | `prompt_id` | `/dashboard` | persist_only (non-target type) | **REMOVE** |
| `backend/api/cleanhouse_monitoring.py:2844` | `submit_tool_event` | `codex_response_observed` | runtime callsite | `missing` | `/dashboard` | persist_only (non-target type) | **REMOVE** |

## CLICK FLOW INVENTORY

| emitter | click URL builder | UI handler | ack path | current behavior |
|---|---|---|---|---|
| _ensure_operator_notification -> _operator_notification_click_url | `backend/api/cleanhouse_monitoring.py::_operator_notification_click_url` | `frontend/js/dashboard.js::applyPendingDashboardFocus` | `frontend/js/dashboard.js::ackNotification -> POST /cleanhouse/notifications/<id>/ack` | open + auto-ack on deep-link resolution |
| _ensure_operator_notification -> _runtime_notification_click_url | `backend/api/cleanhouse_monitoring.py::_runtime_notification_click_url` | `frontend/js/dashboard.js::applyPendingDashboardFocus` | `frontend/js/dashboard.js::ackNotification -> POST /cleanhouse/notifications/<id>/ack` | open + auto-ack on deep-link resolution |
| incident_action_required deep-link | `backend/api/cleanhouse_monitoring.py::_operator_notification_click_url (/incident-receipt)` | `frontend/js/incident-receipt.js::loadIncidentCard` | `frontend/js/incident-receipt.js::ackDeepLinkNotificationIfNeeded -> POST /cleanhouse/notifications/<id>/ack` | open incident receipt + auto-ack |

## VALID

- `scope_drift_detected` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8088)
- `scope_drift_detected` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8125)
- `session_ended` via `_ensure_operator_notification` (backend/api/cleanhouse_monitoring.py:7181)
- `session_started` via `_ensure_operator_notification` (backend/api/cleanhouse_monitoring.py:7219)
- `scope_drift_detected` via `generate_alerts` (backend/api/cleanhouse_monitoring.py:9762)
- `session_started` via `start_operator_session` (backend/api/cleanhouse_monitoring.py:4645)
- `session_ended` via `stop_operator_session` (backend/api/cleanhouse_monitoring.py:4691)

## BROKEN

- none

## REMOVE

- `excessive_traversal` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8105) -> persist_only (non-target type)
- `excessive_traversal` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8136) -> persist_only (non-target type)
- `approval_required` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8155) -> persist_only (non-target type)
- `receipt_finalized` via `_derive_workstation_notifications` (backend/api/cleanhouse_monitoring.py:8169) -> persist_only (non-target type)
- `codex_response_observed` via `_emit_codex_active_context_response_notification` (backend/api/cleanhouse_monitoring.py:2508) -> persist_only (non-target type)
- `<dynamic>` via `_emit_runtime_transition_notification` (backend/api/cleanhouse_monitoring.py:3355) -> persist_only (non-target type)
- `collector_failure` via `_ensure_collector_failure_notifications` (backend/api/cleanhouse_monitoring.py:9896) -> persist_only (non-target type)
- `continuity_degraded` via `_ensure_continuity_degraded_notification` (backend/api/cleanhouse_monitoring.py:8206) -> persist_only (non-target type)
- `critical_filesystem_mutation` via `_ensure_critical_filesystem_mutation_notifications` (backend/api/cleanhouse_monitoring.py:8432) -> persist_only (non-target type)
- `replay_or_signature_failure` via `_ensure_replay_or_signature_failure_notification` (backend/api/cleanhouse_monitoring.py:12015) -> persist_only (non-target type)
- `rollback_needed` via `_ensure_rollback_needed_notification` (backend/api/cleanhouse_monitoring.py:10093) -> persist_only (non-target type)
- `destructive_command_attempt` via `_on_command_completed` (backend/api/cleanhouse_monitoring.py:2709) -> persist_only (non-target type)
- `codex_response_observed` via `_on_command_completed` (backend/api/cleanhouse_monitoring.py:2728) -> persist_only (non-target type)
- `qpb_transition` via `advance_qpb_case` (backend/api/cleanhouse_monitoring.py:10650) -> persist_only (non-target type)
- `receipt_finalized` via `build_receipt` (backend/api/cleanhouse_monitoring.py:11721) -> persist_only (non-target type)
- `approval_required` via `create_approval_queue_item` (backend/api/cleanhouse_monitoring.py:8539) -> persist_only (non-target type)
- `<dynamic>` via `emit_domain_event` (backend/api/cleanhouse_monitoring.py:3861) -> persist_only (non-target type)
- `runtime_recovery_failure` via `execute_rollback` (backend/api/cleanhouse_monitoring.py:10332) -> persist_only (non-target type)
- `<dynamic>` via `send_test_operator_notification` (backend/api/cleanhouse_monitoring.py:4837) -> validation_only (persisted, dispatch suppressed by default)
- `codex_prompt_sent` via `submit_prompt` (backend/api/cleanhouse_monitoring.py:4585) -> persist_only (non-target type)
- `codex_response_observed` via `submit_tool_event` (backend/api/cleanhouse_monitoring.py:2844) -> persist_only (non-target type)

## ROOT CAUSE

- Pre-existing notification lane mixed production and validation sources in the same dispatch surface.
- Non-target notification types were emitted as operator notifications instead of persist-only evidence records.
- Click completion lacked guaranteed open-time acknowledgement for deep-link entry points.

## TOP 3 PATCHES

1. Eliminate passive active-context auto-attach for GET polling (`attach` explicit only).
2. Enforce production dispatch gate + runtime-backing requirements (`event_id`, `incident_id` for incident action, `click_url`).
3. Route incident-backed notifications to `/incident-receipt` and auto-acknowledge on deep-link open.
