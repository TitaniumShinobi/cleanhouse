# CleanHouse Canonical Runtime Spine

Last updated: 2026-10-13
Status: Canonical operator lane

## Canonical launch lane

- Canonical entrypoint: `/bin/bash scripts/cleanhouse-up.sh`
- Canonical host and port: `127.0.0.1:3333`
- Readiness gate: `GET /cleanhouse/status?ready=1`
- Runtime gate: `GET /cleanhouse/runtime`
- First paint target: `http://localhost:3333/overview`

## Continuous operator loop

1. Objective declaration is bound to one canonical `objective_id`.
2. Prompt/action/mutation events are persisted with evidence refs.
3. Receipts are generated and replayable.
4. Approval queue carries evidence-linked review records.
5. Notifications deep-link to runtime/session evidence.
6. Replay closes the loop with objective -> actions -> mutations -> receipts -> approval -> notification lineage.

## Runtime truth rules

- Runtime state is authoritative from the live supervisor payload and runtime subsystem status.
- `bootstrap_ready_at` records that the HTTP bootstrap milestone was reached. It is historical evidence, not operator readiness.
- `operator_ready=true` only when the explicit `cleanhouse.runtime_operator_readiness.v1` contract is satisfied: runtime state is `healthy`; startup phase is `warm`; the backend and supervisor are alive; exactly one CleanHouse-owned listener matches the backend PID; no foreign listener exists; the heartbeat is fresh; the last readiness probe passed; and no self-deviation or hard resource block is active.
- `recovering` and `degraded` are never operator-ready, even when a bootstrap timestamp exists.
- Heartbeat startup failure propagates into warmup, resets the retry flag, and records degraded state with `heartbeat_start_failed`.
- The durable event writer starts during warmup instead of waiting for the first filesystem event. Writer startup failure remains visible in `/cleanhouse/status` as an `event_writer` failure; it is never converted into a healthy or inactive success state.
- Interpreter compatibility is proven by importing `backend.server`, including its transitive launch imports, in the candidate interpreter.
- LaunchAgent `RunAtLoad`/`KeepAlive` proves persistence intent only; it does not satisfy the operator-readiness contract.
- The launcher gives both endpoint availability and the canonical operator-safety gate the same bounded startup window (30 seconds by default, configurable with `CLEANHOUSE_STARTUP_TIMEOUT_SECONDS`). A transient not-ready result is retried within that window; expiration remains a failed launch and never weakens readiness.
- Optional collector and preservation metadata may annotate the readiness response only after canonical evaluation. Readiness probes use already-cached metadata and never wait for Keychain interaction or remote synchronization; those subsystem states remain separately visible as healthy, degraded, or unavailable.
- Staged application source and monitored repository are independent. `CLEANHOUSE_SOURCE_REPO_ROOT` identifies the clean source used to construct the running application, while `CLEANHOUSE_WATCH_DIR` identifies the operator repository observed by Files. Exact-commit staging must not redirect Files monitoring into a temporary export.
- The staged application is dependency-closed for browser authentication: its required `access_control` package is copied with backend, models, core files, frontend, and assets so signup and signin do not borrow code from the dirty source tree.
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
- `click_url` points at `/overview` with deep-link params
- Cooldown and burst controls are represented in native delivery metadata
- `native_delivery_result.status` is interpreted as transport-only unless operator acknowledgement confirms visibility
