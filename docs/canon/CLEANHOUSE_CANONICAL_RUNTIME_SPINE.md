# CleanHouse Canonical Runtime Spine

Last updated: 2026-10-21
Status: Canonical operator lane

## Canonical launch lane

- Canonical entrypoint: `/bin/bash scripts/cleanhouse-up.sh`
- Canonical host and port: `127.0.0.1:3333`
- Readiness gate: `GET /cleanhouse/status?ready=1`
- Launcher readiness authority: the public readiness response must satisfy the
  complete nested `cleanhouse.runtime_operator_readiness.v1` contract. A 200,
  bare `ready=true`, partial check set, failed check, HTTP error, transport
  error, oversized body, malformed JSON, missing bootstrap readiness, or
  contradictory required-state metadata is not authoritative readiness.
- The accepted response is bounded to 64 KiB and requires literal
  `bootstrap_ready=true`, `runtime_state="healthy"`,
  `required_runtime_state="healthy"`, exact
  `required_startup_phases=["warm"]`, the exact eleven canonical checks all
  true, and empty `failed_checks`. Final diagnostics bound item count and text
  length and never print the raw response.
- `reason_codes` are bounded diagnostic history, not readiness authority. They
  may remain present on a healthy response; the nested contract's exact checks
  and `failed_checks` determine current operator readiness.
- The existing eleven-check contract binds `readiness_probe_ok` to the current
  backend generation: the last successful `/health` PID and non-empty boot ID
  must exactly match the tracked backend PID and boot ID. Missing or mismatched
  generation identity fails closed without changing the public check set.
- `/cleanhouse/runtime` is protected operator detail, not an unauthenticated
  launcher probe. The launcher does not weaken authentication to inspect it.
- First paint target: `http://localhost:3333/overview`
- Self-deviation acknowledgement is never implicit. A normal launcher run uses
  non-acknowledging observational preflight; that preflight may normalize and
  persist runtime state, clear proven-stale PID claims, or record that recovery
  is allowed. Only the explicit `--acknowledge-self-deviation` switch authorizes
  the acknowledgement mutation before activation.

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
- A failed start or readiness probe never authorizes the launcher to stop or
  unload a runtime. CleanHouse currently exposes no atomic,
  generation-conditional stop operation, so the launcher reports the bounded
  failure and leaves lifecycle authority with the existing supervisor.
- Acknowledging historical self-deviation does not itself make a live owned
  backend unhealthy and does not authorize a restart. The supervisor starts a
  replacement only when no valid owned generation survives. An exited prior
  supervised child does not override a different live, solely owned listener
  whose `/health` PID and boot ID match the adopted state; that survivor keeps
  the restart counter stable. With no valid survivor, backend death or explicit
  ownership loss remains restart-eligible. Adoption records the listener's
  `/health` PID and boot ID before operator readiness can succeed.

## START disposable verification lane

- `start.isolated-launcher.json` is the product declaration for
  `life-start-isolated-launcher/v1` version `1.0.0`. It is source-bound to the
  declared revision and the deterministic digest produced by
  `scripts/start_isolated_runtime.py`. The declaration is evidence supplied to
  START; it does not grant execution, signal, cleanup, or PASS authority.
- The exact product entry is
  `cleanhouse_env/bin/python3 scripts/start_isolated_runtime.py` from the
  repository root. START must supply an invocation nonce, a noncanonical
  ephemeral loopback port, a task root, state root, data root, mode-0600 auth
  configuration, mode-0600 ephemeral signing credentials, and a bootstrap
  `HOME` contained by the task root.
- Interpreter provenance is lexical and dependency-bearing: the harness must
  be invoked through the exact repository virtualenv path and preserves that
  path across `execve`. It must not resolve the virtualenv symlink to the base
  Command Line Tools interpreter, because doing so loses the virtualenv prefix
  and CleanHouse dependencies. Flask, Flask-CORS, and cryptography availability
  are checked before execution.
- The entrypoint fails closed before process creation when the source digest,
  nonce, credential binding, path containment, file permissions, loopback
  host, or port occupancy is invalid. Port `3333`, the repository, the user's
  `.cleanhouse` tree, and the canonical CleanHouse data tree are forbidden
  isolation roots. Canonical-home detection uses the operating-system account
  record rather than the caller's task-scoped `HOME`, preventing a legitimate
  bootstrap home from being mistaken for canonical user storage while still
  rejecting a bootstrap home outside the START task root.
- On success the entrypoint replaces itself with the real
  `backend.runtime_supervisor` command. The supervisor launches the real Flask
  backend in START's existing process group. Canonical supervision retains its
  separate-session behavior; only `CLEANHOUSE_START_ISOLATED=1` changes this
  relationship.
- The entrypoint derives a generation identifier from the invocation nonce and
  source-content digest as the run ID; every backend birth retains a distinct
  boot/generation identity. Isolated-only `/health`, readiness, and runtime state
  expose nonce, generation, source digest, PID, parent PID, process-group ID,
  session ID, boot ID, and observation time under
  `cleanhouse.start_isolation_evidence.v1`. Every evidence object is bound with
  HMAC-SHA256 using START's ephemeral signing secret. Wrong/replayed nonces,
  stale generations, source drift, stale observations, and altered process
  identity therefore fail validation.
- Each isolated health or readiness request requires a fresh START challenge.
  The challenge is part of the signed evidence and is checked with a maximum
  ten-second observation age. The product probe disables redirects, retains at
  most 64 KiB, and requires exact equality between signed evidence, outer HTTP
  fields, and the captured state identity. Readiness returns HTTP 503 with
  `ready=false` when unsatisfied; isolated health/readiness responses use
  `Cache-Control: no-store`.
- Signed phase is restricted to the declared startup phases. Signed state
  revision is a non-boolean integer from zero through `2^63-1`. For the same
  backend generation it may only move forward within an eight-revision bounded
  transition window. The probe rereads state after the response and requires
  the signed phase/revision to reconcile with that forward transition; phase
  regression, revision regression/overflow, or concurrent uncertainty fails
  closed.
- During the narrow interval in which the listener is accepting requests but
  the initial state-file publication is not readable, backend evidence reports
  the truthful initial `booting` phase with revision zero. It must not emit a
  signed `null` phase: START correctly rejects that malformed transitional
  observation and closes the finite observation session.
- Isolated runtime classification does not call global `ps` or `lsof`.
  Supervisor/backend liveness uses signals only against the two captured PIDs;
  listener ownership requires a fresh signed health response whose PID, boot
  ID, nonce, generation, source digest, direct parent, process group, and
  session agree with the captured supervisor/backend ledger. The product never
  infers extinction from a live response. START must independently prove the
  captured PIDs, process group, and listener extinct after shutdown.
  Product-signed fields establish correlation and integrity only. Runtime state
  labels independent listener/process ownership `NOT_INDEPENDENTLY_ESTABLISHED`
  and never promotes that product claim into START signal authority.
- The isolated server does not load repository `.env`, authentication is
  disabled with an ephemeral signing secret, and product integrations that can
  access Keychain, canonical databases, VVAULT, Wazuh, filesystem watchers,
  network capture, browser state, or native notifications are not initialized.
  The real supervisor, Flask server, runtime state machine, heartbeat,
  `/health`, and `/cleanhouse/status?ready=1` paths remain exercised.
- START owns allocation, direct-child/process-group/listener binding, bounded
  recovery and shutdown, descendant extinction, disposal, and the seven
  `life-start-final-verification/v2` lanes. CleanHouse never converts its own
  declaration or test result into a START completion claim. Until the trusted
  START adapter consumes this declaration and proves those properties, actual
  START lifecycle execution remains `NOT_ESTABLISHED`.
- The declaration's seven lanes are finite `DECLARED_NOT_VERIFIED` records,
  not lane-name or PASS assertions. Build/regression/security commands have
  exact argv, timeouts, output limits, source binding, and expected outcomes;
  behavioral/integration/recovery/acceptance lanes define bounded predicates,
  freshness, and expected results. START must execute and independently
  evaluate them before changing any lane to PASS.
  Every lane also carries a proposed finite adapter ID, predicate version, and
  exact operation ID. The build lane redirects Python cache/artifacts under
  `START_BUILD_ROOT` and requires a fresh task-owned artifact; regression and
  security test sources participate in the source-content digest. These are
  admission proposals only and remain unsupported/NOT_VERIFIED until START
  independently registers and executes the adapters.

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
