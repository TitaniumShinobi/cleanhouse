# CleanHouse Notification Spam Test Report

Date: 2026-05-28
Scope: Documentation lane C for notification-spam test phase only.
Evidence boundary: This report documents command outputs and probe artifacts. It does not claim operator-visible confirmation beyond transport/dispatch metadata.

## Commands Executed

```bash
python3 -m pytest -q tests/test_cleanhouse_monitoring_api.py -k "notification or scope_drift or cooldown or burst or reminder"
python3 -m scripts.native_notification_runtime_probe --output /tmp/cleanhouse-native-notification-probe.json
```

## Test Outcomes

- Pytest result: `41 passed, 115 deselected in 4.14s`
- Probe output file: `/tmp/cleanhouse-native-notification-probe.json`
- Probe top-level status: `ok`

## Acceptance Gate Checklist

- [x] `dual_backend_fanout_detected == false`
  - Observed: `false`
- [x] `hard_interrupt_reminder_capped == true`
  - Observed: `true`
- [x] `scope_drift_duplicate_suppressed == true`
  - Observed: `true`
- [x] Skipped native dispatch includes explicit reason + timestamp
  - Observed skipped dispatch record includes:
    - `reason: cooldown_active`
    - `timestamp: 2026-05-28T16:25:12.428154`

## Evidence Notes (Non-Overclaim)

- Results show single-backend behavior under defaults in this probe run (`dual_backend_fanout_detected: false`).
- Reminder cap behavior is present in probe metadata (`hard_interrupt_reminder_capped: true`) with suppression markers in visibility metadata.
- Scope-drift duplicate suppression is present for shared-evidence emit paths (`scope_drift_duplicate_suppressed: true`).
- Skipped dispatch evidence is transport-layer metadata (`status: skipped`, reason, timestamp) and should not be interpreted as desktop visibility confirmation.
