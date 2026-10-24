# CleanHouse Canonical Runtime Spine

Last updated: 2026-05-28
Status: Canonical operator lane

## Canonical launch lane

- Canonical entrypoint: `/bin/bash scripts/cleanhouse-up.sh`
- Canonical host and port: `127.0.0.1:3333`
- Readiness gate: `GET /cleanhouse/status?ready=1`
- Runtime gate: `GET /cleanhouse/runtime`
- First paint target: `http://localhost:3333/dashboard`

## Continuous operator loop

1. Objective declaration is bound to one canonical `objective_id`.
2. Prompt/action/mutation events are persisted with evidence refs.
3. Receipts are generated and replayable.
4. Approval queue carries evidence-linked review records.
5. Notifications deep-link to runtime/session evidence.
6. Replay closes the loop with objective -> actions -> mutations -> receipts -> approval -> notification lineage.

## Runtime truth rules

- Runtime state is authoritative from supervisor payload + runtime subsystem status.
- `operator_ready=true` only when runtime is healthy and required runtime subsystems are not degraded.
- Notification delivery metadata is transport evidence, not guaranteed OS-visible interruption proof.
- Degraded and unknown states remain visible; no hidden recovery claims.

## Notification probe runbook

Canonical probe command:

```bash
python3 -m scripts.native_notification_runtime_probe --output /tmp/cleanhouse-native-notification-probe.json
```

Required checks in the probe artifact:

- `runtime_status.status == "ok"`
- Runtime notification records include local `evidence_refs`
- `click_url` points at `/dashboard` with deep-link params
- Cooldown and burst controls are represented in native delivery metadata
- `native_delivery_result.status` is interpreted as transport-only unless operator acknowledgement confirms visibility
