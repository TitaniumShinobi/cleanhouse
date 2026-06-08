# CleanHouse Enterprise-Scale Current State Audit

Date: 2026-05-25

Doctrine: "Runtime truth outranks tone. Evidence outranks confidence."

## Verdict

CleanHouse currently has a credible local runtime accountability substrate and a
controlled end-to-end local evidence lane. It is not a dependable 24/7
professional-grade runtime accountability platform, and it is not enterprise or
billion-user SaaS ready.

The strongest observable proof is narrow:

```text
local Flask server -> dashboard HTML -> prompt/session APIs -> snapshot/diff
-> rollback route -> timeline -> receipt -> replay -> signed bundle verification
```

The platform-level claim is still unproven:

```text
all filesystem, process, port, network, shell, prompt, cloud, agent, subscription,
automation, and background runtime mutations -> continuously correlated lineage
-> deterministic receipts -> mediated approval/rollback -> signed governance
at fleet scale
```

No audited enterprise-scale subsystem is production-capable. Several are
operational in local controlled paths, many are substrate-only, and global-scale
claims remain aspirational until CleanHouse proves continuous operation,
complete collector coverage, durable lineage, governed identity, native
notifications, signed key lifecycle, and fleet architecture under measured load.

## Evidence Snapshot

Runtime checks were run without browser automation.

| Evidence | Result |
|---|---|
| `python3 backend/server.py` | failed with `ModuleNotFoundError: No module named 'flask'` under default Python |
| `cleanhouse_env/bin/python backend/server.py` with `CLEANHOUSE_PORT=3344` | launched local Flask development server on `127.0.0.1:3344` |
| server startup log | emitted Flask warning: development server is not for production deployment |
| `GET /dashboard` | HTTP 200, `8989` bytes of HTML |
| `GET /cleanhouse/status?ready=1` | `{"status":"ok","ready":true}` |
| `GET /cleanhouse/status?refresh=1` | returned `status=critical` and sections for processes/network/ai_activity/anomalies/integrity/command/cloud_usage/tool_events |
| watched filesystem mutation under `/tmp/cleanhouse-audit-watch` | `3` event rows appeared for `mutation.txt`: `created`, `modified`, `modified` |
| prompt/session workflow | session start and prompt ingestion returned `ok` |
| tool event workflow | submitted generic tool event returned `error: command is required` |
| approval workflow | approval item created with `pending` review state |
| snapshot/diff workflow | two snapshots returned `ok`; diff found `1` modified file |
| rollback workflow | rollback route was available and execution returned `executed_verified`; target file content restored to `before` |
| receipt workflow | receipt returned `ok`, `6` hash-chain events, root hash present, `2` gaps |
| replay workflow | replay returned `ok`, replay hash present |
| signed bundle workflow | bundle returned `ok`; Ed25519 manifest verification returned `verified`; import returned `ok` |
| `python3 -m corefiles.collectors.process_monitor --once --all` | ran and listed `775` processes, but matched Codex processes as `VS Code` because of broad substring matching |
| `python3 -m corefiles.collectors.agent_movement_monitor --once --quiet` | ran and reported active platforms `vscode, codex, cursor`, file activity `codex`, network activity `vscode, codex`, and `129` agent detections |
| `python3 -m corefiles.collectors.data_flow_tracer --duration 1 --output /tmp/...` | ran and reported `43` connections, `13` processes, `0` suspicious connections |
| focused unit tests | `tests/test_events_api.py`, `tests/test_cleanhouse_monitoring_api.py`, and `tests/test_cleanhouse_integration.py` passed individually |
| full unittest discovery | `191` tests ran; failed with `14` errors, mostly Flask `jsonify` calls outside application context |

## Classification Summary

| Area | Classification | Evidence-based reason |
|---|---|---|
| Universal filesystem observability | operational but immature | watchdog-backed file events work for one configured watch root, but coverage is not universal, does not attribute actor/process, ignores `.git`, and only captures create/modify/delete file events |
| Process observability | operational but immature | `ps` snapshot collector works, but it is polling/snapshot based, not durable process lifecycle lineage; platform classification produced visible false positives |
| Port/network observability | substrate-only | `lsof` snapshots work, but there is no continuous socket lifecycle, packet flow, per-process causality, firewall mediation, or durable port-open/port-close accounting |
| Runtime persistence | substrate-only | SQLite events and artifact persistence exist, but core adapter state is in-memory dicts/deques and restart durability is incomplete |
| Startup reliability | unstable | launch works only with the project virtual environment in this audit; default `python3` failed; runtime uses Flask development server and no service supervisor |
| Contextual prompt and execution lineage ingestion | operational but immature | prompt/session/objective APIs exist and produce receipt evidence, but ingestion is not universal across all tools, shells, agents, or cloud automations |
| Deterministic receipts | operational but immature | receipts include root hashes and event hash chains, but receipt IDs are timestamp-derived and receipts include gaps; determinism is not yet independently proven across restarts/fleet boundaries |
| Replay verification | operational but immature | replay hashes and import verification work locally, but replay is scoped to stored local artifacts and does not reconstruct all runtime truth |
| Signed evidence integrity | operational but immature | signed Ed25519 manifests verify locally, but the private signing key is an unencrypted local JSON file, with no rotation, hardware-backed storage, tenant trust, revocation, or audit authority |
| Approval mediation | operational but immature | approval records and review states exist, but route ownership is review-state-only; approvals do not enforce execution control across shell, agents, filesystem, network, or cloud providers |
| Rollback orchestration | operational but immature | narrow file snapshot rollback worked and verified, but rollback is not universal, not policy-mediated, and not integrated with provider/cloud/process rollback chains |
| Desktop notification delivery | misleadingly represented | backend creates notification records and dashboard uses browser Notification API; adapter header explicitly says no macOS notifications |
| Operator trust workflows | operational but immature | dashboard panels exist and auto-refresh every 2 seconds, but hardcoded localhost port, readiness-stub status calls in the frontend, avatar-specific default objective text, and browser-only notifications weaken trust |
| Runtime explainability | operational but immature | timelines, alerts, lineage graphs, drift reasons, gaps, and receipt scope exist, but several edges are inferred/unknown and false-positive-prone collectors reduce explanatory reliability |
| Low-overhead continuous monitoring | substrate-only | polling, 10-second cache, bounded event queue, and limits exist; there is no measured CPU/memory overhead, soak test, backpressure recovery proof, or 24/7 failure envelope |
| Governance maturity | substrate-only | settings, retention events, plugins, approvals, reports, and signed bundles exist, but there is no tenant policy, RBAC, audit administration, compliance workflow, or fleet governance |
| User experience | operational but immature | dashboard is usable locally, but it is not an instant daily-use product surface; runtime health and evidence gaps require interpretation |
| Cloud/runtime interoperability | aspirational | read-only cloud usage indicators exist for selected providers, but most provider states are unsupported indicators rather than verified provider event ingestion |
| Scalability assumptions | aspirational | local SQLite, in-memory queues, local files, and single-process Flask do not support multi-tenant global scale |
| Universal mutation accountability | aspirational | current proof covers selected local events, not all device, app, process, port, sync provider, subscription, repository, agent, cloud, or automation mutations |

## Subsystem Findings

### 1. Filesystem Observability

Classification: operational but immature.

Evidence:

- `backend/events.py` defines optional `watchdog` imports and returns inactive
  behavior when unavailable.
- the runtime watcher uses `CLEANHOUSE_WATCH_DIR` or repo root as a single
  recursive watch root.
- file handler records only `created`, `modified`, and `deleted`.
- directories are skipped, `.git` paths are skipped, and evidence refs are path
  strings, not signed file-content proofs.
- runtime smoke captured `3` events for a watched temp file.

Gaps:

- no universal machine-wide watch coverage;
- no process/PID attribution for file mutations;
- no rename/move/permission/xattr/link/change-owner semantics;
- no sync-provider causality;
- no file-content capture policy, redaction policy, or privacy boundary;
- no queue overflow recovery beyond dropped-record metrics.

### 2. Process, Port, and Network Observability

Classification: process observability is operational but immature; port/network
observability is substrate-only.

Evidence:

- `corefiles/collectors/process_monitor.py` reads `ps axww` and normalizes user, PID, PPID, CPU,
  memory, start time, elapsed time, and command.
- `corefiles/collectors/data_flow_tracer.py` reads `lsof -i -P -n`.
- `corefiles/collectors/agent_movement_monitor.py` reads `ps aux` and `lsof -i -P -n`.
- runtime process scan listed `775` total processes.
- runtime data-flow scan listed `43` network connections.

Gaps:

- polling does not prove lifecycle continuity;
- exited processes can be missed between polls;
- process labels are substring based and visibly wrong in this audit;
- Codex app processes were displayed as `VS Code`;
- no binary hash, code-signing identity, executable provenance, or parent/child
  tree persistence beyond snapshots;
- no kernel-level event stream, Endpoint Security integration, eBPF equivalent,
  or firewall-owned enforcement;
- network evidence does not prove request purpose or user intent.

### 3. Prompt, Objective, Shell, and Execution Lineage

Classification: operational but immature.

Evidence:

- session start returned `ok`;
- prompt ingestion returned `ok`;
- receipt generation included prompt/session lineage and hash-chain events;
- command observer can insert shell and process runtime events when its owned
  wrapper observes completed commands.

Gaps:

- generic tool event submission failed with `command is required`, showing the
  tool boundary schema is strict but not ergonomically universal;
- shell observation is wrapper-bound, not system-wide shell mediation;
- no guaranteed capture of prompts from Cursor, Codex, Copilot, hosted AI
  services, browser agents, cloud automations, or CI systems unless they call
  CleanHouse explicitly;
- contextual prompt lineage is not cryptographically bound to every mutation.

### 4. Receipts, Replay, and Signed Evidence

Classification: operational but immature.

Evidence:

- receipt build returned `ok`;
- receipt contained `6` hash-chain events and a root hash;
- replay returned `ok` and produced replay hash;
- signed receipt bundle verification returned Ed25519 `verified`;
- receipt import returned `ok`.

Gaps:

- receipt ID is timestamp-derived, so identical event sets do not produce a
  stable artifact identity;
- receipt still carried `2` gaps in the local proof;
- signed manifest verifies local bundle contents, not universal runtime truth;
- private key is stored as unencrypted raw Ed25519 material in a local JSON file;
- no hardware-backed key, KMS, tenant trust root, key rotation, revocation,
  transparency log, or independent verifier CLI is proven;
- local artifact persistence does not satisfy fleet retention or legal-grade
  chain of custody.

### 5. Approval Mediation and Rollback

Classification: operational but immature.

Evidence:

- approval item was created and remained `pending`;
- rollback request found a snapshot route;
- rollback execution restored file content and returned `executed_verified`.

Gaps:

- approval is review state, not execution enforcement;
- CleanHouse does not block unapproved shell/file/network/cloud actions;
- rollback works only for captured file snapshot content under a supplied repo
  path;
- no rollback chain for processes, ports, credentials, cloud resources,
  subscription changes, sync provider replication, or repository remote state;
- no required approval-to-execution gate before mutation.

### 6. Notifications and Operator Workflow

Classification: notification delivery is misleadingly represented; operator
workflow is operational but immature.

Evidence:

- adapter header says there are no macOS notifications.
- dashboard calls `Notification.requestPermission()` and creates browser
  notifications.
- backend creates notification records and the dashboard shows a tray.
- dashboard auto-refreshes every 2 seconds.

Gaps:

- no native desktop notification daemon;
- no background notification delivery when the dashboard/webview is closed;
- no notification reliability queue with retry/ack timeout/escalation;
- hardcoded `http://127.0.0.1:3333` in frontend HTTP mode conflicts with
  alternate runtime ports;
- dashboard default objective text is avatar-specific and not enterprise
  neutral;
- the frontend status helper uses `?ready=1` for its default status call, which
  returns only a readiness stub and can leave dashboard-derived collector
  manifest views empty unless a full refresh path is used.

### 7. Runtime Persistence, Reliability, and Startup

Classification: startup reliability is unstable; persistence is substrate-only.

Evidence:

- default `python3 backend/server.py` failed because Flask was unavailable;
- virtualenv server launched successfully;
- server emitted Flask development-server warning;
- routes responded after launch;
- watchdog started for the configured temp watch directory;
- full unittest discovery failed with `14` Flask app-context errors.

Gaps:

- no launchd service, supervisor, crash recovery, restart state reconciliation,
  or 24/7 soak proof;
- no durable rehydration for all adapter state;
- core operational state uses in-memory deques and dicts;
- async DB writer can drop records under queue pressure;
- `_insert_runtime_event` catches broad exceptions and suppresses evidence write
  failures;
- runtime uses local development server semantics, not production service
  semantics.

### 8. Governance, SaaS Scale, and Cloud Interoperability

Classification: aspirational.

Evidence:

- settings, retention event surfaces, plugin metadata, cloud usage observers,
  approvals, reports, signed bundles, and local routes exist.
- cloud usage observer is explicitly read-only and inspects indicators such as
  env var names, config directory existence, process lines, and network
  destinations.

Gaps:

- no tenants, organizations, RBAC, policy bundles, fleet health, sharding,
  multi-region storage, quota model, data retention enforcement, customer key
  management, billing boundary, or admin audit workflow;
- no verified imports from AWS CloudTrail, GitHub audit logs, Google Workspace,
  Microsoft Graph, OpenAI organization logs, identity providers, EDR products,
  endpoint management systems, or SaaS subscriptions;
- no billion-user load model, receipt volume model, storage cost model, or
  failure-domain design;
- local SQLite and local JSON artifact persistence are incompatible with the
  advertised scale.

## Production-Capability Gate

Current release label under the enterprise rubric: Local Alpha substrate with a
controlled evidence lane.

Blocked labels:

| Label | Status | Blocking reason |
|---|---|---|
| Daily-Use Beta | blocked | no automatic 24/7 service, no native notifications, no durable continuous monitoring proof, no universal mutation coverage |
| Professional Production | blocked | no production server/supervisor, no low-overhead measurements, no enforcement-grade approval mediation, no signed key lifecycle |
| Enterprise Scale | blocked | no multi-tenant SaaS architecture, no fleet collectors, no governance plane, no provider integrations, no scaling proof |

## Exact Engineering Gaps

1. Replace single-root watchdog proof with a platform-specific collector plan
   that explicitly covers files, directories, renames, permissions, ownership,
   symlinks, sync-provider events, and actor attribution.
2. Add durable process lifecycle capture with PID, PPID, executable hash,
   code-signing identity, command line, launch time, exit time, parent chain,
   and session/objective correlation.
3. Add durable port/network lifecycle capture with open/close transitions,
   process identity, local/remote endpoints, DNS basis, and uncertainty labels.
4. Convert shell/tool observation from opt-in wrapper evidence into explicit
   mediated execution paths with visible unsupported states for non-mediated
   shells/tools.
5. Persist and rehydrate adapter state across restarts for prompts, sessions,
   approvals, notifications, snapshots, diffs, timelines, receipts, rollbacks,
   reports, tool events, and settings.
6. Replace silent event-write failure handling with surfaced collector failure
   records and dashboard-visible health.
7. Make receipt identity deterministic over stable receipt content and preserve
   timestamps as metadata, not artifact identity.
8. Add independent receipt verifier tooling and documented bundle trust rules.
9. Replace local raw signing key storage with a real key lifecycle: generation,
   storage, rotation, revocation, export policy, and tenant trust roots.
10. Turn approval mediation into enforceable gates for CleanHouse-owned command,
    file, network, rollback, and provider actions.
11. Broaden rollback from one-file snapshot restore to versioned rollback chains
    with policy approval and post-action verification.
12. Implement native desktop notifications with background delivery,
    deduplication, retry, ack, and escalation semantics.
13. Remove hardcoded frontend port assumptions and derive runtime origin from
    the active launch context.
14. Replace broad substring platform/agent matching with signed app identity,
    bundle IDs, executable paths, process ancestry, and explicit confidence
    labels.
15. Add continuous overhead benchmarks, queue saturation tests, 24-hour soak
    tests, restart recovery tests, and permission-denial tests.
16. Add production service packaging: launchd/service supervision, health
    endpoints, log rotation, controlled shutdown, crash recovery, and upgrade
    safety.
17. Add governance primitives: tenants, users, roles, policies, audit exports,
    retention controls, privacy controls, and admin review workflows.
18. Add provider integrations as verified imports, not inferred local
    indicators.
19. Define a fleet data plane for event ingestion, receipt storage, sharding,
    tenant isolation, signed verification, rate limits, and backpressure.
20. Keep all unsupported surfaces visible as `unknown`, not silently omitted.

## Accountability Blind Spots

- file mutations outside the configured watch root;
- file mutations whose actor cannot be attributed;
- process launch/exit between polling intervals;
- network connections that open and close between polling intervals;
- remote SaaS/cloud mutations not imported from provider audit logs;
- browser extension behavior and web-app delegated actions;
- sync-provider replication and conflict resolution;
- subscription, billing, account, and identity mutations;
- unmediated shell commands;
- automation systems that never call CleanHouse APIs;
- prompt lineage from tools that do not expose prompts;
- rollback paths not backed by stored snapshots;
- notification delivery when the UI is closed;
- evidence write failures swallowed by broad exception handling;
- high-volume queue overflow.

## Final Audit Position

CleanHouse should be represented as a local-first runtime accountability
substrate with a working narrow receipt/replay/rollback lane. It should not be
represented as a professional 24/7 platform, global SaaS governance plane, or
universal runtime accountability layer yet.

The next credible product milestone is not more thesis language. It is a
measured Daily-Use Beta gate:

```text
auto-start service -> continuous collectors -> visible health -> durable state
-> actor-attributed mutations -> prompt/tool correlation -> deterministic
receipt -> signed replay bundle -> native notification -> approval/rollback
-> restart recovery -> overhead and soak proof
```

Until that gate passes with current runtime evidence, all enterprise-scale
positioning must remain aspirational.
