# CleanHouse Enterprise Runtime Accountability Rubric

Date: 2026-05-25

Doctrine: "Runtime truth outranks tone. Evidence outranks confidence."

## Purpose

This rubric defines the measurable standard for CleanHouse to operate as LIFE
Technology's professional 24/7 runtime accountability and security platform
across users, devices, repositories, agents, cloud services, automation systems,
and operating environments.

The rubric exists to prevent completion inflation. A launcher, dashboard,
collector, route, schema, or receipt class is infrastructure. CleanHouse becomes
a dependable daily-use product only when those pieces continuously produce
observable runtime truth: universal mutation visibility where technically
available, interpretable execution lineage, deterministic receipts, signed
evidence, approval mediation, rollback state, and an always-on operational view
that users can trust.

## Required Evidence Vocabulary

Every CleanHouse claim must use one evidence level:

| Evidence level | Meaning | Product rule |
|---|---|---|
| `observed` | Captured directly by a CleanHouse collector, owned adapter, verified provider import, or signed event | May support product claims when replayable |
| `inferred` | Correlated by stated basis such as time window, PID, request ID, trace ID, file hash, session ID, or provider event ID | Must display the inference basis |
| `unknown` | Missing, unsupported, permission-blocked, collector-failed, ambiguous, or not retained | Must remain visible; cannot be described as success |

Every edge in the lineage graph must carry its own evidence level. A file change
can be observed while its relationship to a prompt remains inferred or unknown.

## Completion Labels

CleanHouse status must use these labels only:

| Label | Meaning |
|---|---|
| Substrate | Launchers, routes, schemas, collectors, UI panels, or persistence exist, but the end-to-end evidence loop is incomplete |
| Local Alpha | A local session can capture objective, action, mutation, timeline, receipt, gap state, and replay in a controlled path |
| Daily-Use Beta | CleanHouse starts automatically, runs continuously, exposes live health, captures core mutation surfaces, and produces replayable receipts under normal operator use |
| Professional Production | CleanHouse proves 24/7 reliability, low overhead, signed receipts, approval mediation, rollback state, notification quality, privacy controls, and failure visibility |
| Enterprise Scale | CleanHouse supports tenant policy, sharding, fleet health, governance workflows, provider integrations, signed verification, and billions-scale receipt architecture |

No document, UI, release note, or handoff may call CleanHouse complete unless
the relevant label's acceptance gates pass with current runtime evidence.

## Scoring Model

Each domain is scored from 0 to 4:

| Score | Meaning |
|---|---|
| 0 | Absent or only described in prose |
| 1 | Infrastructure exists but no end-to-end runtime proof |
| 2 | Works in a narrow local path with tests or controlled proof |
| 3 | Works continuously in daily use with visible gaps and recovery behavior |
| 4 | Production-grade: reliable, measurable, replayable, signed where required, and governed at enterprise scale |

Minimum release bars:

| Release level | Minimum score |
|---|---|
| Local Alpha | No critical domain below 2 |
| Daily-Use Beta | No critical domain below 3; no P0 gate failing |
| Professional Production | All critical domains at 4; non-critical domains at least 3 |
| Enterprise Scale | All domains at 4 with fleet and tenant evidence |

Critical domains are marked `P0`. A single P0 failure blocks completion claims.

## P0 Stop Conditions

CleanHouse cannot claim daily-use or production completion if any of these are
true:

- startup success is not proven by readiness checks;
- the background runtime dies silently;
- collector failure is hidden;
- unsupported observability surfaces are described as covered;
- receipts cannot be replayed;
- receipt tampering is not detected;
- approval prompts are not tied to evidence refs;
- rollback is claimed without recovery evidence;
- UI status labels imply protection without runtime proof;
- cloud, agent, SaaS, or automation claims exceed imported or observed evidence;
- tests prove only code paths, not runtime behavior.

## Domain Rubric

### 1. Product Truth And Anti-Inflation `P0`

Required standard:

- Every capability claim maps to current code, runtime output, test evidence, or
  an explicitly labeled future requirement.
- Infrastructure is labeled as infrastructure until it participates in an
  end-to-end evidence loop.
- All docs and UI avoid completion language unless gates pass.
- No claim depends on tone, confidence, or narrative summary without evidence.

Measurable acceptance:

- A product claim inventory exists with evidence path, proof command, evidence
  level, and last verification date.
- Every "complete", "protected", "secure", "always-on", "real-time", or
  "universal" label has a passing gate.
- Known gaps are displayed in docs and UI.

Failure examples:

- Calling a dashboard complete because it renders cards.
- Calling a receipt reliable because a schema exists.
- Calling collection universal when only watched paths are covered.

### 2. Instant Canonical Launch `P0`

Required standard:

- CleanHouse has one canonical local launch path.
- Launch completes fast enough to feel native.
- Duplicate servers, stale ports, missing dependencies, and blocked readiness
  produce actionable errors.

Measurable acceptance:

- Cold launch reaches readiness in a documented target window.
- Warm launch reuses or replaces the running instance deterministically.
- `/cleanhouse/status` and the dashboard route are verified against the running
  process.
- Failed launch produces a non-zero exit or explicit failure state.

Score 4 requires:

- Cross-platform launch strategy for macOS, Windows, and Linux.
- Signed or versioned launcher artifacts.
- Automated startup regression test.

### 3. 24/7 Background Persistence `P0`

Required standard:

- CleanHouse runs continuously as a supervised local utility.
- It starts on login or boot when configured.
- It restarts cleanly after crashes and reports degraded state.

Measurable acceptance:

- Supervisor exists: macOS LaunchAgent, Windows service/task, Linux user service,
  or equivalent.
- Runtime heartbeat is visible in the UI and API.
- Crash, restart, sleep/wake, network loss, and update handoff are tested.
- Logs rotate without unbounded growth.

Score 4 requires:

- 24-hour soak test with collector health, memory, CPU, receipt generation, and
  restart evidence.

### 4. Low-Overhead Continuous Monitoring `P0`

Required standard:

- Monitoring must be continuous without making the user's machine feel worse.
- Overhead budgets must be explicit and measured.

Measurable acceptance:

- CPU, memory, disk I/O, database write rate, and event queue depth are tracked.
- Backpressure is visible.
- Sampling and debounce rules are documented.
- Large repository, high-churn directory, and idle-machine tests pass.

Score 4 requires:

- Configurable overhead profiles.
- Bounded event queues.
- Loss and drop counters included in receipts and health views.

### 5. Universal Filesystem Observability `P0`

Required standard:

- CleanHouse accounts for filesystem mutation visibility across the operating
  environment as broadly as the host platform allows.
- Every file surface is covered, excluded, permission-blocked, unsupported, or
  unknown.

Measurable acceptance:

- Create, modify, delete, rename, move, permission change, and hash drift are
  observed for covered roots.
- Sync-provider and remote-origin changes are labeled when provider evidence is
  available.
- Coverage matrix lists watched roots, excluded roots, errors, and blind spots.
- Events include path, event type, timestamp, actor/process when available,
  hash when available, evidence ref, and receipt inclusion state.

Score 4 requires:

- OS-native watcher strategy per supported platform.
- High-churn and recursive-directory stress tests.
- File events appear in lineage and receipts with gaps preserved.

### 6. Process Lineage Observability `P0`

Required standard:

- CleanHouse observes process activity and preserves parent-child lineage where
  the platform exposes it.

Measurable acceptance:

- Process start, stop, PID, parent PID, command line, user, executable path,
  binary hash when available, start time, and evidence source are captured.
- Missing parentage is labeled unknown.
- Process events correlate to shell commands, ports, network connections, and
  file mutations when evidence supports the edge.

Score 4 requires:

- Parent/child lineage test.
- Long-running background process test.
- Process identity never upgraded into actor intent.

### 7. Port And Network Observability `P0`

Required standard:

- CleanHouse observes local port and network behavior with owning process
  context where available.

Measurable acceptance:

- Listening port open/close, outbound connection, protocol, local address,
  remote host, remote port, PID, process name, timestamp, and evidence source
  are captured.
- Network claims distinguish snapshot evidence from packet inspection.
- Unknown process ownership is visible.

Score 4 requires:

- Local port smoke test.
- Outbound connection smoke test.
- Process-to-network lineage included in receipts.

### 8. Contextual Prompt And Execution Lineage `P0`

Required standard:

- Prompt, ticket, objective, tool, agent, shell, process, filesystem, network,
  cloud, SaaS, and automation context must be correlated into interpretable
  execution lineage.

Measurable acceptance:

- Objective ID and session ID are present on captured actions.
- Prompt/context is stored as lineage context, not proof of intent.
- Correlation edges state basis: PID, parent PID, command ID, tool call ID,
  request ID, trace ID, file hash, timestamp window, or provider event ID.
- Each edge is labeled observed, inferred, or unknown.

Score 4 requires:

- End-to-end scenario: objective -> prompt -> tool or shell action -> process ->
  file/network mutation -> receipt -> replay.

### 9. Normalized Event Spine `P0`

Required standard:

- All collectors and adapters emit a shared event envelope.

Required fields:

```yaml
event_id: deterministic ID
timestamp: source timestamp
ingested_at: CleanHouse ingestion timestamp
source: collector, adapter, provider, tool, or manual import
session_id: session ID when available
objective_id: objective ID when available
actor: user, process, tool, agent, service, or unknown
authority: credential, permission, approval, role, or unknown
action: observed action
target: mutated or accessed target
mutation_type: create, modify, delete, execute, connect, grant, revoke, read
evidence_level: observed, inferred, or unknown
evidence_refs: one or more refs
correlation_basis: explicit basis or null
collector_health: healthy, degraded, failed, not_configured, or unknown
receipt_state: pending, included, excluded, or unknown
```

Measurable acceptance:

- Schema validation exists.
- Invalid event payloads fail closed.
- Legacy collector payloads normalize without losing raw refs.

### 10. Deterministic Receipts `P0`

Required standard:

- Receipts are the product proof artifact, not a summary card.

Measurable acceptance:

- Receipt includes objective, session, timeline, evidence index, approval state,
  gaps, collector health, rollback state, and root hash.
- Same input event set produces same receipt hash.
- Missing evidence is included in the receipt as a gap.
- Receipt generation is tested for determinism.

Score 4 requires:

- Receipt export bundle.
- Receipt import and replay.
- Tamper test changes verification result.

### 11. Replay Verification `P0`

Required standard:

- A later operator or auditor can reconstruct the receipt state without trusting
  the original narrative.

Measurable acceptance:

- Replay reconstructs timeline, evidence refs, approvals, gaps, and rollback
  state.
- Replay reports missing raw evidence instead of succeeding silently.
- Replay command or API is documented.

Score 4 requires:

- Replay bundle survives export/import.
- Verification result is machine-readable and human-readable.

### 12. Signed Evidence Integrity `P0`

Required standard:

- Evidence and receipts are tamper-evident.

Measurable acceptance:

- Receipt root hash covers timeline, evidence index, approvals, gaps, rollback
  state, and schema version.
- Signature or local signing plan exists for production.
- Key identity, rotation, and verification policy are documented.

Score 4 requires:

- Signed receipt verification.
- Redaction-aware integrity strategy.
- Enterprise countersignature or transparency-log compatible design.

### 13. Approval Mediation `P0`

Required standard:

- Approval is evidence-scoped and replayable.
- Approval does not imply enforcement unless CleanHouse owns the route.

Measurable acceptance:

- Approval item includes action, reason, requested mutation surface, evidence
  refs, reviewer, status, timestamp, history, and scope.
- States include pending, approved, rejected, exception, expired, and unknown.
- Approval prompts link to receipt or lineage.
- Denials and exceptions are included in replay.

Score 4 requires:

- Pre-execution approval for owned routes.
- Post-execution review for unowned routes.
- Policy-triggered approvals with quiet-failure handling.

### 14. Rollback Orchestration `P0`

Required standard:

- Rollback is never claimed without recovery evidence.

Measurable acceptance:

- Each mutation has rollback state: available, partial, unavailable, or unknown.
- Available rollback includes prior-state evidence, recovery method, authority,
  expected side effects, approval requirement, and verification command.
- Recovery result is captured as evidence.

Score 4 requires:

- Verified rollback for at least one file mutation path.
- Partial and unavailable rollback paths displayed without success language.

### 15. Desktop Notifications And Approval Prompts

Required standard:

- Notifications must be meaningful, evidence-linked, and low-noise.

Measurable acceptance:

- Native notification path exists per supported desktop platform.
- Notification severity is policy-driven.
- Notification opens the relevant event, lineage, approval, or receipt.
- Quiet hours, suppression, and rate limits exist.
- No generic "protected" or "all good" notifications appear without evidence.

Score 4 requires:

- Notification action buttons where supported: approve, reject, snooze, open
  receipt.
- Notification audit trail in receipts.

### 16. Always-On Operational View `P0`

Required standard:

- The dashboard answers what the system is doing now.

Measurable acceptance:

- UI shows runtime health, active collectors, gaps, recent mutations, active
  processes of interest, open ports, recent network activity, pending
  approvals, recent receipts, and stale-data state.
- Every card maps to a real API or event source.
- Empty state distinguishes no activity from disconnected or failed collection.

Score 4 requires:

- Live updates without manual refresh.
- Drill-down from summary to raw evidence and receipt.
- Human-readable lineage view.

### 17. Runtime Explainability

Required standard:

- CleanHouse explains what happened without inventing why it happened.

Measurable acceptance:

- Every explanation separates action, mutation, evidence, inference, unknown,
  approval, and rollback.
- Pattern matches are described as pattern matches.
- Prompt text is context, not intent proof.
- Cloud, agent, SaaS, and automation imports retain source boundary.

Score 4 requires:

- Explanation view can show "why this was flagged" using evidence refs and
  policy rules.

### 18. Operator Sovereignty And Privacy `P0`

Required standard:

- The operator owns the evidence boundary.

Measurable acceptance:

- Local-first storage by default.
- Explicit user action or policy is required for export or cloud sync.
- Retention, redaction, and deletion controls exist.
- Sensitive evidence is protected at rest.
- Elevated collection requires visible permission.
- Cloud confidence never replaces local evidence.

Score 4 requires:

- Tenant policy and personal policy can coexist without hiding local truth.
- Export is portable and verifiable.

### 19. Cloud, SaaS, Agent, And Automation Adapters

Required standard:

- Remote and third-party systems enter CleanHouse through explicit evidence
  contracts.

Measurable acceptance:

- Adapter contract preserves source event ID, actor, authority, target, action,
  timestamp, raw ref, evidence level, and provider boundary.
- Provider events are not treated as local observation.
- Missing provider data becomes unknown.

Score 4 requires:

- At least one cloud audit import, one agent/tool event import, and one
  automation/workflow import represented in receipts.

### 20. Scalability And Fleet Architecture

Required standard:

- CleanHouse must be architected for billions-scale usage without sacrificing
  local runtime truth.

Measurable acceptance:

- Tenant, device, repository, environment, and time-window partitioning model is
  documented.
- Local buffering handles offline operation.
- Backpressure and dropped-event counts are visible.
- Receipt IDs are globally unique or namespace-safe.
- Aggregation does not mutate local evidence.

Score 4 requires:

- Sharded event and receipt architecture.
- Fleet health reporting.
- Privacy-preserving search and redaction-aware verification.

### 21. Governance Maturity

Required standard:

- CleanHouse supports enterprise governance without becoming a static GRC
  checklist.

Measurable acceptance:

- Policy rules map to objective, actor, authority, action, target, mutation,
  evidence level, approval state, and rollback state.
- Exceptions have reviewer, reason, scope, expiry, and receipt linkage.
- Audit exports include receipts, evidence index, policy decision, approvals,
  and gaps.

Score 4 requires:

- Tenant-level policy distribution.
- Role-based access.
- Governance reports generated from receipts rather than prose summaries.

### 22. Reliability And Failure Visibility `P0`

Required standard:

- Failure is part of runtime truth.

Measurable acceptance:

- Collector failed, degraded, not configured, permission denied, stale data, and
  queue backpressure are first-class states.
- UI and receipts expose failures.
- No green status is shown when a critical collector is failed.
- Crash recovery preserves event consistency.

Score 4 requires:

- Failure-injection tests.
- Receipt records collector failures and data-loss windows.

### 23. User Experience And Trust Workflows

Required standard:

- CleanHouse must be usable by a daily operator, not only by its implementer.

Measurable acceptance:

- First screen shows live operational state, not marketing copy.
- Users can answer: what changed, what caused it, what needs approval, what is
  unknown, what receipt exists, and what recovery is possible.
- UI avoids placebo controls.
- Wording is concrete and evidence-backed.

Score 4 requires:

- Operator can complete daily review in one workflow: open app, inspect live
  state, resolve approvals, open receipt, export or replay evidence.

## Mandatory Acceptance Scenarios

CleanHouse must pass these scenarios before production claims:

1. Startup scenario

CleanHouse starts from the canonical launcher, proves readiness through the
status endpoint and dashboard, and reports actionable failure when startup is
blocked.

2. 24/7 scenario

CleanHouse runs under supervision for a documented soak period, survives
sleep/wake or restart conditions, and preserves health and receipt evidence.

3. Filesystem scenario

A file is created, modified, renamed, deleted, and hash-changed under a covered
root. Each mutation appears in events, lineage, receipt, and replay.

4. Process scenario

A parent process launches a child process. CleanHouse captures parent, child,
command, user, timing, and unknowns if any lineage segment is missing.

5. Port/network scenario

A process opens a listening port and makes an outbound connection. CleanHouse
captures process ownership where available and includes the event in receipt
lineage.

6. Prompt/execution scenario

An objective and prompt are recorded, a tool or command runs, runtime mutation
follows, and CleanHouse labels every lineage edge observed, inferred, or
unknown.

7. Approval scenario

A policy or review condition creates an approval item with evidence refs. The
operator approves or rejects it. Replay shows the decision and history.

8. Rollback scenario

A mutation with prior-state evidence is recovered. CleanHouse records the
rollback plan, approval state, execution result, and verification result.

9. Signed receipt scenario

CleanHouse exports a signed receipt bundle. Independent verification passes.
Manual tampering causes verification failure.

10. Failure scenario

A collector is disabled, permission is revoked, or an adapter import fails.
CleanHouse shows degraded or unknown state in API, UI, receipt, and replay.

11. Cloud/agent/automation scenario

An imported provider, agent, or workflow event is correlated with local runtime
evidence. CleanHouse preserves the provider boundary and does not overclaim
remote visibility.

12. Operator trust scenario

A user opens CleanHouse during normal machine use and can identify current
health, recent mutations, pending approvals, receipts, and unknown gaps without
reading raw logs.

## Completion Inflation Guardrails

These statements are prohibited unless their gates pass:

| Claim | Required proof |
|---|---|
| "Launches instantly" | Cold and warm launch timing plus readiness verification |
| "Runs 24/7" | Supervisor configuration plus soak and restart evidence |
| "Universal observability" | Coverage matrix plus unsupported/unknown states |
| "Real-time" | Latency target, measured event delay, and stale-state display |
| "Secure" | Specific security property and verification evidence |
| "Protected" | Enforcement route or explicit passive-observation wording |
| "Rollback supported" | Verified recovery path and post-recovery evidence |
| "Cloud-aware" | Provider event import or local evidence boundary |
| "Agent-aware" | Tool/agent event import or local process/command evidence |
| "Enterprise-grade" | Production scorecard plus governance and reliability evidence |

## Required Release Artifact

Every release or handoff must include this table:

| Domain | Score | Evidence command or artifact | Gaps | Last verified |
|---|---:|---|---|---|
| Launch |  |  |  |  |
| Background runtime |  |  |  |  |
| Filesystem observability |  |  |  |  |
| Process lineage |  |  |  |  |
| Port/network observability |  |  |  |  |
| Event spine |  |  |  |  |
| Execution lineage |  |  |  |  |
| Receipts |  |  |  |  |
| Replay |  |  |  |  |
| Signed evidence |  |  |  |  |
| Approval mediation |  |  |  |  |
| Rollback |  |  |  |  |
| Notifications |  |  |  |  |
| Operational view |  |  |  |  |
| Operator sovereignty |  |  |  |  |
| Cloud/agent/automation adapters |  |  |  |  |
| Scalability |  |  |  |  |
| Governance |  |  |  |  |
| Reliability/failure visibility |  |  |  |  |
| UX/trust workflow |  |  |  |  |

Blank scores are not allowed in a completion report. Unknowns must be written as
unknowns.

## Final Standard

CleanHouse is complete as LIFE Technology's professional runtime accountability
platform only when it can run continuously, observe supported runtime mutation
surfaces, preserve visible gaps, correlate objective-scoped execution lineage,
mediate approvals, emit deterministic and signed receipts, verify replay,
orchestrate rollback where evidence exists, scale under tenant governance, and
give the operator an always-on evidence-backed view of what the machine,
applications, agents, automations, cloud services, and background processes are
actually doing.

Anything less is substrate or partial product behavior.

Runtime truth outranks tone. Evidence outranks confidence.
