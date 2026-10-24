# CleanHouse Production-Readiness Execution Plan

Date: 2026-05-25

Doctrine: "Runtime truth outranks tone. Evidence outranks confidence."

## Purpose

This plan defines the engineering path from the current stabilized CleanHouse
runtime substrate to a dependable enterprise-grade 24/7 runtime accountability
platform. It is intentionally gate-driven. A route, watcher, dashboard panel,
schema, queue, or receipt object remains substrate until it participates in a
measured runtime evidence loop that survives restart, exposes failure, produces
replayable receipts, and gives the operator accurate live state.

The target product behavior is:

```text
auto-start local runtime
-> continuous low-overhead collectors
-> universal mutation visibility where technically available
-> actor and context correlation
-> evidence-labeled lineage
-> deterministic receipt
-> signed replay verification
-> notification and approval mediation
-> rollback or explicit no-rollback state
-> operator-facing live truth
-> fleet-scale governance
```

## Current Boundary

CleanHouse can currently be treated as a Local Alpha substrate with a controlled
local evidence lane. It has local routes, dashboard panels, file event storage,
snapshot/diff flows, approval records, receipts, replay, signed bundles, and
rollback proof for a narrow file path.

CleanHouse cannot yet be represented as a professional 24/7 platform or
enterprise-scale SaaS runtime accountability layer because the audited runtime
still lacks automatic persistence, universal observability, native background
notifications, durable process/network lineage, production supervision,
enforcement-grade approval mediation, fleet architecture, and measured
reliability.

## Completion Labels

| Label | Product meaning | Required evidence |
|---|---|---|
| Substrate | Code paths and UI surfaces exist | Static route/schema/panel proof only |
| Local Alpha | A controlled local session proves objective, mutation, receipt, replay, and rollback state | Headless runtime proof plus focused tests |
| Daily-Use Beta | CleanHouse auto-starts, runs continuously, captures core host mutation surfaces, and exposes live gaps | 24-hour local soak plus restart and sleep/wake proof |
| Professional Production | CleanHouse has supervised service behavior, low overhead, native notifications, signed evidence, durable receipts, approval mediation, rollback state, and privacy controls | 30-day reliability trial plus production packaging and incident drills |
| Enterprise Scale | CleanHouse supports tenants, fleets, provider imports, policy governance, sharded evidence, signed verification, and billions-scale receipt architecture | Multi-tenant load, chaos, provider, and governance evidence |

No phase may advance if unsupported surfaces are hidden or described as covered.

## Workstream Priority Map

| Priority | Workstream | Why it comes first |
|---|---|---|
| P0 | Runtime service foundation | A platform that does not start and stay alive cannot be trusted |
| P0 | Durable normalized evidence stream | Receipts, lineage, governance, and UI require one durable truth model |
| P0 | Core host observability | Files, processes, ports, network, and shell are the local accountability base |
| P0 | Receipt determinism and replay | Evidence must be independently verifiable, not just displayed |
| P0 | Failure visibility | Hidden collector failure is worse than no collector |
| P1 | Approval, notification, and rollback mediation | Operator sovereignty requires action paths, not passive logs |
| P1 | Operator workstation UX | Daily use depends on opening the app and understanding live state quickly |
| P1 | Low-overhead performance | Always-on monitoring must not degrade the machine |
| P2 | Provider and cloud interoperability | Enterprise truth requires verified external evidence imports |
| P2 | Fleet and tenant governance | Billion-user scale requires separated tenants, policy, sharding, and audit |

## Phase 0 - Contract Lock And Product Truth Gate

Objective: prevent completion inflation before adding more infrastructure.

Engineering work:

1. Create a product claim inventory for every use of "secure", "protected",
   "always-on", "real-time", "universal", "production", "enterprise", and
   "complete".
2. Map each claim to code path, runtime proof command, evidence level, owner,
   last verification time, and current label.
3. Add a build-time documentation check that fails when unsupported claims lack
   evidence references.
4. Add visible UI labels for unsupported, degraded, permission-blocked,
   unavailable, and unknown collector states.

Runtime verification gates:

| Gate | Pass threshold |
|---|---|
| Claim inventory | 100 percent of product claims mapped to evidence or marked future |
| Unsupported surfaces | 100 percent visible as `unknown`, `unsupported`, or `degraded` |
| Completion wording | No production/enterprise wording unless the matching phase gate passes |
| Evidence levels | Every event and lineage edge carries `observed`, `inferred`, or `unknown` |

Exit status: Local Alpha claims may remain. Daily-use, production, and
enterprise claims stay blocked.

## Phase 1 - Canonical Runtime Service

Objective: make CleanHouse launch reliably and remain alive as a supervised
background utility.

Engineering work:

1. Replace default ad hoc `python3 backend/server.py` behavior with one canonical
   launcher that resolves dependencies deterministically.
2. Package a local background service:
   - macOS LaunchAgent first;
   - Windows service or scheduled task;
   - Linux user systemd service.
3. Separate development server mode from production local service mode.
4. Add service heartbeat, PID, version, uptime, restart count, collector status,
   queue depth, DB state, signing key state, and active watch scope to
   `/cleanhouse/status`.
5. Add crash restart, sleep/wake resume, port conflict handling, stale lock
   cleanup, and controlled shutdown.
6. Add log rotation and bounded local artifact storage.
7. Remove hardcoded frontend origin assumptions and derive runtime origin from
   the active launch context.

Runtime verification gates:

| Gate | Pass threshold |
|---|---|
| Cold launch | Ready in <= 5 seconds on supported local profile |
| Warm launch | Existing instance reused or replaced deterministically in <= 2 seconds |
| Readiness | `/cleanhouse/status` and dashboard both verified against same running PID |
| Service restart | Forced process kill recovers within <= 10 seconds and records restart evidence |
| Sleep/wake | Runtime resumes collectors within <= 15 seconds after wake |
| Port conflict | Explicit non-zero failure or deterministic alternate-port handoff |
| Dependency failure | Missing dependency produces actionable failure, not ambiguous startup |

Product behavior after exit:

CleanHouse may claim dependable local startup only after the service gate passes
on the supported OS profile.

## Phase 2 - Durable Normalized Evidence Stream

Objective: make every runtime fact enter one durable event model before it is
displayed, correlated, approved, rolled back, or receipted.

Engineering work:

1. Promote the event schema into the canonical write path for all collectors and
   adapters.
2. Persist prompts, sessions, objectives, approvals, notifications, snapshots,
   diffs, timelines, receipts, rollbacks, tool events, reports, settings, and
   collector health with restart rehydration.
3. Replace broad silent exception handling for event writes with visible
   collector failure events.
4. Add append-only event IDs, monotonic sequence numbers, stable source IDs,
   collector IDs, observed timestamps, ingest timestamps, host IDs, and schema
   versions.
5. Add bounded queue backpressure with loss counters, retry counts, durable
   spooling, and explicit receipt gaps when evidence is dropped.
6. Add privacy and redaction policy hooks before evidence persistence.

Runtime verification gates:

| Gate | Pass threshold |
|---|---|
| Restart rehydration | 100 percent of active sessions, approvals, notifications, receipts, and settings survive restart |
| Event write failure | 100 percent surfaced in status and dashboard within <= 2 seconds |
| Queue saturation | Dropped or delayed records appear in health and receipts |
| Schema migration | Existing event DB migrates without data loss in test fixtures |
| Evidence durability | Controlled local workflow can be replayed after service restart |

Product behavior after exit:

The dashboard may trust persisted runtime state instead of in-memory session
state. Receipts must include event loss and collector degradation.

## Phase 3 - Universal Host Observability

Objective: cover core host mutation surfaces continuously with explicit
observed, inferred, and unknown boundaries.

### Filesystem

Engineering work:

1. Replace single-root watcher assumptions with configurable host scopes:
   repository roots, user-selected folders, app support folders, desktop,
   documents, downloads, cloud sync roots, and protected unsupported paths.
2. Capture create, modify, delete, rename, move, chmod, chown, xattr, symlink,
   hardlink, and directory events where the OS allows.
3. Attach file hashes, size, inode/file ID when available, bundle or process
   attribution when available, and privacy-safe content policy metadata.
4. Distinguish local edits, sync-provider writes, agent writes, package-manager
   writes, system writes, and unknown writes using evidence-labeled basis.
5. Add permission-denied and scope-excluded events as first-class gaps.

Verification gates:

| Gate | Pass threshold |
|---|---|
| File event matrix | 95 percent or greater capture for supported event types in controlled test roots |
| Rename/move | Rename preserves lineage from old path to new path |
| Permission denial | Denied paths appear as visible gaps |
| Actor attribution | Every mutation has actor status: observed, inferred, or unknown |
| High churn | 10,000 file events/minute processed without silent loss; any loss is counted |

### Process

Engineering work:

1. Add durable process lifecycle capture: start, exec, fork/child, exit, parent
   chain, user, command, executable path, code-signing identity, binary hash,
   environment policy hash, working directory, and terminal/session link where
   available.
2. Replace broad substring platform detection with signed app identity, bundle
   ID, executable path, process ancestry, and explicit confidence.
3. Correlate process events to file, network, shell, prompt, objective, and
   approval events by PID, parent PID, timestamp, session ID, and request IDs.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Lifecycle capture | 99 percent or greater capture in controlled process spawn/exit test |
| Parent chain | Parent/child relation preserved for spawned shell and tool commands |
| False positive budget | Known app classification false positives below 1 percent in fixture corpus |
| Process gaps | Missed or permission-blocked attribution visible as `unknown` |

### Ports And Network

Engineering work:

1. Capture port open, listen, accept, connect, close, DNS basis, protocol,
   process identity, local endpoint, remote endpoint, and duration.
2. Preserve request purpose only when observed from an owned adapter or imported
   provider event; otherwise mark inferred or unknown.
3. Add network baseline, anomaly model, and allowlist/denylist policy with
   evidence basis.
4. Add firewall or network extension mediation only after passive evidence is
   reliable.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Port lifecycle | Controlled local server open/close captured within <= 2 seconds |
| Short connection capture | Connections lasting >= 250 ms captured in supported profile |
| Process correlation | 95 percent or greater of controlled connections linked to process identity |
| DNS basis | DNS name, reverse lookup, or unknown state recorded for each remote endpoint |
| Unsupported traffic | Unsupported encrypted/application-layer semantics remain visible as unknown |

Product behavior after exit:

CleanHouse may claim core host observability only for tested host scopes and OS
profiles. Unsupported surfaces must remain visible.

## Phase 4 - Prompt, Agent, Shell, And Automation Lineage

Objective: bind delegated execution context to runtime mutations without
inventing intent.

Engineering work:

1. Define an SDK and CLI contract for prompt, objective, tool, command,
   automation, and provider events.
2. Add official adapters for Codex, Cursor, Copilot, OpenCode, CI runners, local
   shell wrappers, and scheduled automations where integration points exist.
3. Require every delegated execution event to include tool identity, operator
   identity, objective ID, prompt/context hash, working directory, command or
   action, declared scope, approval state, and evidence refs.
4. Keep non-integrated tools visible as process/file/network facts with
   `unknown` prompt lineage.
5. Add correlation rules that show basis: PID, session ID, request ID, timestamp
   window, path hash, tool event ID, or provider event ID.

Runtime verification gates:

| Gate | Pass threshold |
|---|---|
| Owned shell lane | Command -> process -> file/network mutation -> receipt is replayable after restart |
| Prompt lineage | Integrated tool prompt hash appears in receipt and lineage graph |
| Non-integrated tool | Mutations remain visible with `unknown prompt lineage` |
| Scope drift | Out-of-scope mutation creates alert and approval item within <= 2 seconds |
| Correlation explainability | Every lineage edge displays its evidence basis |

Product behavior after exit:

CleanHouse may claim contextual execution lineage for integrated tools only.
Non-integrated surfaces remain observable where host collectors see them but not
prompt-attributed unless evidence exists.

## Phase 5 - Deterministic Receipts, Replay, And Signed Integrity

Objective: make receipts stable, tamper-evident, independently verifiable, and
replayable across restarts and exports.

Engineering work:

1. Make receipt IDs deterministic over stable receipt content. Keep timestamps
   as metadata, not artifact identity.
2. Canonicalize event ordering, event hashes, lineage graph, collector manifest,
   gaps, approval state, rollback state, and evidence refs.
3. Add independent verifier CLI that verifies receipt root hash, event hash
   chain, replay hash, signature, schema version, and missing evidence gaps.
4. Replace raw local signing-key JSON with a key lifecycle:
   - local secure storage or hardware-backed key when available;
   - key creation event;
   - rotation;
   - revocation;
   - public trust metadata;
   - export and backup policy;
   - tenant roots for enterprise mode.
5. Add signed bundle transparency hooks for fleet mode.
6. Add deterministic receipt fixture tests across process restart and clean
   machine re-import.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Receipt determinism | Same canonical event set produces same receipt root and receipt ID |
| Tamper detection | Modified event, gap, approval, rollback, or manifest fails verification |
| Restart replay | Receipt generated before restart verifies after restart |
| External verifier | Verifier CLI validates exported bundle without running dashboard |
| Key security | Private signing key never stored as raw unencrypted JSON in production mode |
| Signature verification | 100 percent of signed bundles pass; known tampered bundles fail |

Product behavior after exit:

CleanHouse may claim deterministic, replayable, signed local receipts for
supported evidence lanes.

## Phase 6 - Approval Mediation, Notifications, And Rollback

Objective: convert operator sovereignty from a review queue into actionable
governance workflows.

### Approval Mediation

Engineering work:

1. Classify routes as observed-only, review-required, or enforceable.
2. Add approval gates for CleanHouse-owned execution paths: command wrappers,
   high-risk file operations, rollback actions, provider actions, automation
   actions, and policy exceptions.
3. Bind approvals to evidence refs, requested action, scope, risk basis,
   rollback state, operator identity, timestamp, and receipt ID.
4. Preserve rejection and needs-review states as first-class execution outcomes.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Evidence-bound prompt | 100 percent of approvals include evidence refs and action basis |
| Enforced route | Unapproved owned high-risk action is blocked in controlled test |
| Review-only route | Non-enforceable route is labeled review-only, not protected |
| Audit history | Approval history survives restart and appears in receipt replay |

### Native Notifications

Engineering work:

1. Implement native desktop notification delivery for the supervised service.
2. Add notification queue, dedupe, throttle, retry, ack timeout, escalation, and
   quiet hours.
3. Deliver notifications when dashboard/webview is closed.
4. Tie every notification to evidence refs, lineage state, approval item,
   receipt, or recovery action.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Delivery latency | Critical notification appears within <= 2 seconds of event |
| Background delivery | Notification delivered while dashboard closed |
| Deduplication | Repeated event storm produces bounded notification count |
| Ack state | Ack survives restart and appears in workstation state |
| Evidence link | Notification opens exact evidence, approval, or receipt context |

### Rollback Orchestration

Engineering work:

1. Expand rollback from one-file snapshot restore to versioned rollback chains.
2. Support file restore, directory restore, config restore, provider rollback
   hooks, repository rollback instructions, and explicit no-route states.
3. Require approval for rollback execution unless policy allows auto-rollback.
4. Verify post-rollback state with content hash, metadata, provider event ID, or
   explicit unknown state.

Verification gates:

| Gate | Pass threshold |
|---|---|
| File rollback | Controlled file restore verified by hash |
| Directory rollback | Multi-file restore preserves expected tree and hash manifest |
| No-route transparency | Unsupported rollback returns explicit no-route state |
| Approval binding | Rollback execution records approval or policy exemption |
| Receipt binding | Rollback request and execution appear in receipt/replay |

Product behavior after exit:

CleanHouse may claim operator mediation only where an owned route is enforced or
truthfully labeled review-only.

## Phase 7 - Operator Trust Workstation

Objective: make the first screen a trustworthy live operational view.

Engineering work:

1. Replace placeholder/default objective text with neutral current-session
   state.
2. Show service health, collector health, event rate, queue depth, drop count,
   last event time, active session, active objective, notification state,
   signing state, and receipt state above the fold.
3. Split observed facts, inferred correlations, and unknown gaps visually.
4. Add operator workflows:
   - start/resume session;
   - declare objective;
   - inspect mutation;
   - inspect lineage basis;
   - approve/reject/needs review;
   - request rollback;
   - verify receipt;
   - export evidence bundle.
5. Add degraded-state UX that is honest and actionable.
6. Add no-browser/headless verification commands for every major UI claim.

UX expectations:

| Surface | Expected behavior |
|---|---|
| First open | User sees whether CleanHouse is alive, collecting, degraded, or blind |
| Live state | New runtime facts appear within <= 2 seconds under normal load |
| Gaps | Unsupported or failed collectors are visible, not hidden |
| Receipts | Receipt root, replay state, signature, gaps, and approval state visible |
| Approvals | Operator can understand why approval is requested before deciding |
| Rollback | Operator sees route available, no route, or executed verified |

Verification gates:

| Gate | Pass threshold |
|---|---|
| Headless UI data proof | API state matches dashboard-rendered counts and labels |
| Hardcoded origin | No static localhost port assumption in runtime frontend |
| Degraded mode | Simulated collector failure appears in status, dashboard, and receipt gap |
| First-paint truth | Initial dashboard state matches current API state without misleading placeholders |

Product behavior after exit:

CleanHouse may claim daily-use operator visibility after headless and manual
operator acceptance gates pass.

## Phase 8 - Low-Overhead Continuous Monitoring

Objective: prove CleanHouse can stay on without harming everyday work.

Engineering work:

1. Add performance telemetry for CleanHouse itself:
   CPU, memory, disk I/O, DB write latency, queue depth, dropped events,
   notification count, receipt build time, collector latency, and scan interval.
2. Add profiles:
   idle, balanced, high-fidelity, privacy-reduced, and incident mode.
3. Add adaptive sampling and debounce rules for high-churn directories.
4. Add soak harnesses for idle machine, active development, high file churn,
   high process churn, network churn, sleep/wake, restart, and DB compaction.

Performance constraints:

| Metric | Daily-use target | Production target |
|---|---|---|
| Idle CPU | <= 1 percent average | <= 0.5 percent average |
| Active CPU | <= 5 percent average during normal dev work | <= 3 percent average |
| Memory | <= 250 MB resident local service | <= 200 MB resident steady state |
| Event UI latency | <= 2 seconds normal load | <= 1 second for critical events |
| Receipt build | <= 5 seconds for normal local session | <= 2 seconds p95 |
| Queue loss | 0 silent loss | 0 silent loss; counted loss only under configured overload |
| Local DB growth | bounded by retention policy | bounded, compacted, and observable |

Verification gates:

| Gate | Pass threshold |
|---|---|
| 24-hour soak | No crash, no silent collector failure, no unbounded memory growth |
| High churn | Backpressure visible; no hidden data loss |
| Idle profile | Meets CPU/memory budget for 24 hours |
| Receipt under load | Receipts include collector health and loss counters |

Product behavior after exit:

CleanHouse may claim low-overhead always-on monitoring only for measured
profiles and supported OS versions.

## Phase 9 - Incident Recovery And Resilience

Objective: make failure modes recoverable and auditable.

Engineering work:

1. Define incident states:
   collector down, DB locked, queue saturated, signing unavailable, notification
   failed, service crashed, watcher permission denied, disk full, provider import
   failed, verifier failed, and rollback failed.
2. Add incident records with severity, evidence refs, start time, recovery time,
   affected surfaces, dropped evidence counts, operator action, and receipt
   impact.
3. Add automatic recovery where safe:
   restart collector, rotate logs, reopen DB, replay spool, resume watcher,
   rebuild derived timeline, and retry notification.
4. Add manual recovery workflows:
   export diagnostics, reset service, rotate key, repair DB, prune artifacts,
   reauthorize collector, and mark no-route rollback.

Reliability thresholds:

| Metric | Daily-use target | Production target |
|---|---|---|
| Service availability | 99.5 percent local uptime over 7 days | 99.9 percent over 30 days |
| Crash recovery | <= 10 seconds | <= 5 seconds |
| Collector recovery | <= 30 seconds or visible degraded state | <= 15 seconds or visible degraded state |
| Evidence spool recovery | 100 percent replay of durable spool | 100 percent replay or signed loss record |
| Incident visibility | <= 2 seconds to status/dashboard | <= 1 second for critical incidents |

Verification gates:

| Gate | Pass threshold |
|---|---|
| Crash drill | Kill service, verify restart, incident record, and no hidden state loss |
| DB lock drill | DB lock appears as degraded and recovers or records failure |
| Disk pressure drill | Storage limit produces bounded failure and visible incident |
| Signing failure drill | Receipts show unsigned/degraded state and block signed claims |
| Notification failure drill | Failed notification appears in incident log and dashboard |

Product behavior after exit:

CleanHouse may claim resilient daily-use behavior only after incident drills
pass and failures become visible artifacts.

## Phase 10 - Cloud, SaaS, Identity, And Automation Interoperability

Objective: extend runtime accountability beyond local inference into verified
provider evidence.

Engineering work:

1. Define provider evidence import contracts:
   provider, tenant, actor, action, resource, timestamp, request ID, event ID,
   source signature or API proof, raw evidence ref, normalized event, and
   retention policy.
2. Add read-only imports first:
   GitHub audit logs, cloud provider audit logs, identity provider sign-in and
   token events, SaaS admin events, CI logs, automation scheduler events, and AI
   platform organization logs where available.
3. Preserve provider limitations as visible gaps.
4. Correlate provider events to local runtime by repository, commit, branch,
   request ID, tool event ID, actor, timestamp, and device identity.
5. Add provider action mediation only after read-only evidence quality is
   proven.

Verification gates:

| Gate | Pass threshold |
|---|---|
| Provider import | Imported event retains provider event ID and raw evidence ref |
| Replay | Provider event appears in receipt and verifier output |
| Correlation basis | Every local-to-cloud edge states basis and evidence level |
| Unsupported provider | Unsupported or unauthorized provider is visible as gap |
| No credential leakage | Secrets are never persisted in receipts or UI |

Product behavior after exit:

CleanHouse may claim cloud/runtime interoperability only per verified provider
adapter and imported event type.

## Phase 11 - Fleet, Tenant, And Billion-User Scale Architecture

Objective: make the architecture viable beyond a single local machine.

Engineering work:

1. Define tenant and fleet model:
   organization, workspace, user, device, repository, agent, provider, policy,
   collector, receipt, and evidence object.
2. Add local-first agent architecture with optional enterprise sync:
   local collection, local receipt generation, encrypted evidence export,
   tenant policy import, and fleet health reporting.
3. Design sharded ingestion:
   event partitioning by tenant/device/session/time, durable queues, backpressure
   policy, idempotent event IDs, schema registry, and replay windows.
4. Design receipt storage:
   content-addressed receipts, signed manifests, retention tiers, customer keys,
   legal hold, deletion policy, and transparency logs.
5. Add governance plane:
   RBAC, policy bundles, approval workflows, incident dashboards, audit exports,
   provider connector administration, and evidence access logs.
6. Add privacy model:
   local redaction, field-level encryption, minimization profiles, consent,
   retention, data residency, and customer-managed keys.

Scale verification gates:

| Gate | Pass threshold |
|---|---|
| Synthetic fleet | 10,000 devices simulated with event ingestion and health summaries |
| Multi-tenant isolation | Cross-tenant evidence access impossible in automated tests |
| Idempotency | Duplicate events do not create duplicate receipt facts |
| Shard failure | One shard failure degrades only affected partitions and records incident |
| Receipt volume model | Cost, storage, retention, and verification latency documented |
| Governance audit | Admin action produces signed audit event and receipt trail |

Enterprise-scale thresholds:

| Dimension | Minimum architecture target |
|---|---|
| Users | billions-scale identity model, not local-user assumptions |
| Devices | fleet-scoped device IDs, health, keys, and policies |
| Events | partitioned append-only ingestion with backpressure |
| Receipts | content-addressed, signed, replayable, tenant-isolated |
| Policies | centrally managed, locally enforceable where routes are owned |
| Verification | independent verifier works without dashboard trust |

Product behavior after exit:

CleanHouse may claim enterprise scale only after tenant isolation, fleet
ingestion, signed governance, and sharded receipt verification are proven under
load.

## Runtime Verification Matrix

| Domain | Daily-use gate | Production gate | Enterprise gate |
|---|---|---|---|
| Startup | cold/warm launch proven | supervised signed package | fleet deployment and update evidence |
| Background service | 24-hour soak | 30-day reliability trial | fleet health and staged rollout |
| Filesystem | supported scope event matrix | actor-attributed high-churn proof | policy-governed fleet collectors |
| Process | lifecycle test | code-signing and parent chain proof | device-wide process fleet summaries |
| Ports/network | local port lifecycle proof | process-correlated network proof | policy and provider network integration |
| Prompt lineage | integrated tool lane | multiple owned adapters | provider and automation event imports |
| Receipts | deterministic local receipt | signed independent verification | sharded content-addressed receipts |
| Replay | restart replay | external verifier | fleet-scale verifier and transparency |
| Approval | evidence-bound review | enforced owned routes | tenant policy workflows |
| Rollback | file rollback proof | directory/provider no-route matrix | governed rollback workflows |
| Notifications | native delivery | incident-grade retry/ack | fleet policy and escalation |
| UX | truthful first screen | operator workflow acceptance | admin and fleet dashboards |
| Performance | 24-hour overhead proof | 30-day budgets | fleet cost and capacity model |
| Governance | local settings and audit | RBAC and retention | tenant, policy, compliance, and audit |

## Incident Recovery Workflows

Each workflow must produce an incident event, operator-visible state, receipt
gap or recovery evidence, and a final recovered/degraded/failed status.

| Incident | Recovery path | Required evidence |
|---|---|---|
| Collector crash | restart collector, mark gap window | crash time, restart time, affected surface, lost count |
| Event queue saturation | spool, throttle, expose loss | queue depth, dropped count, policy profile |
| DB locked/corrupt | retry, checkpoint, repair, export diagnostics | DB state, repair action, surviving event count |
| Signing unavailable | block signed claims, continue unsigned if allowed | key state, receipt unsigned status, operator notice |
| Notification failure | retry, surface missed notification | notification ID, attempts, final state |
| Rollback failed | stop execution, preserve before/after evidence | requested path/action, failure reason, verification hash |
| Permission denied | mark collector gap, guide permission action | path/surface, OS denial, affected collector |
| Provider import failed | retry and mark provider degraded | provider, API status, last good event ID |

## Operational Success Criteria

CleanHouse is production-ready only when all criteria below are satisfied with
current runtime evidence.

1. One canonical launch path starts the service and exposes readiness.
2. The service restarts after crash and resumes after sleep/wake.
3. Core collectors run continuously and expose health.
4. Files, processes, ports, network, shell/tool activity, prompts, approvals,
   receipts, rollback, notifications, and provider imports enter one durable
   event model.
5. Unsupported, failed, or permission-blocked surfaces are visible as gaps.
6. Operator can open CleanHouse and understand current runtime state in the
   first viewport.
7. Every mutation in supported scope has actor status and lineage status.
8. Receipts are deterministic, signed where required, replayable, and externally
   verifiable.
9. Approval prompts are evidence-bound and enforce owned routes.
10. Rollback either verifies recovery or explicitly records no route.
11. Native notifications deliver without the dashboard being open.
12. Performance stays within measured overhead budgets.
13. Incident recovery is tested and evidenced.
14. Privacy, redaction, retention, and key management are enforced.
15. Tenant and fleet architecture is proven before enterprise claims.

## Final Execution Order

1. Lock product truth and claim inventory.
2. Build the supervised canonical runtime service.
3. Make the normalized evidence stream durable and restart-safe.
4. Upgrade host collectors for filesystem, process, port, and network coverage.
5. Add prompt/tool/shell/automation lineage contracts.
6. Make receipts deterministic and externally verifiable.
7. Harden signed evidence key lifecycle.
8. Turn approvals, notifications, and rollback into evidence-bound workflows.
9. Rebuild the operator workstation around live truth and gap visibility.
10. Prove low overhead with soak and churn tests.
11. Add incident recovery drills and failure-state receipts.
12. Add provider imports with verified evidence refs.
13. Add tenant, fleet, policy, sharding, and governance architecture.
14. Run release gates in order: Local Alpha, Daily-Use Beta, Professional
    Production, Enterprise Scale.

## Non-Negotiable Release Rule

CleanHouse is not complete because infrastructure exists. It is complete only
when the runtime can prove what happened, what did not happen, what is unknown,
who or what was involved, what evidence supports the claim, what approval state
applies, what rollback state exists, and whether the receipt can be replayed and
verified after restart.

Until those gates pass, the correct status is:

```text
stabilized substrate with controlled local accountability lanes
```

The final product status becomes:

```text
dependable 24/7 runtime accountability platform
```

only after the measured runtime gates in this plan pass under current evidence.
