# CleanHouse Tier 1 Runtime Accountability Audit

Date: 2026-05-25

Doctrine: Runtime truth outranks tone. Evidence outranks confidence.

Canonical references for this audit:

- `CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
- `CLEANHOUSE_RUNTIME_ACCOUNTABILITY_RESEARCH.md`
- `CLEANHOUSE_EVIDENCE_FIRST_CONCLUSION.md`
- current source and runtime checks in this checkout

## Audit Verdict

CleanHouse has a real runtime accountability substrate and one tested narrow
end-to-end receipt lane. It does not yet satisfy the Tier 1 MVP definition of
universal runtime mutation accountability.

The current system can demonstrate this owned fixture chain:

```text
prompt/context -> tool event -> snapshot diff -> timeline -> receipt -> approval -> replay bundle
```

The current system cannot yet prove this universal product chain:

```text
objective -> actions -> mutations -> receipts -> approval/rollback
```

The gap is not cosmetic. The implementation has routes, data classes, a
dashboard, launch scripts, event persistence, receipts, approval records, and
regression fixtures. Those are necessary infrastructure. Product fulfillment
requires those parts to account for runtime state movement across humans,
agents, automation pipelines, shell processes, background services, filesystem
changes, process lineage, port/network changes, and cloud/runtime edges with
explicit observed, inferred, and unknown boundaries.

## Evidence Collected

### Static Code Evidence

The audit reviewed the current implementation surfaces that map to the product
spine:

- objective routes in `backend/api/cleanhouse.py:288-343`
- prompt/context ingestion in `backend/api/cleanhouse.py:350-394` and
  `backend/api/cleanhouse_monitoring.py:1513-1567`
- operator session and workstation routes in `backend/api/cleanhouse.py:409-467`
- approval queue routes in `backend/api/cleanhouse.py:479-566`
- snapshot, diff, correlation, timeline, signals, alerts, receipts, replay, and
  bundle routes in `backend/api/cleanhouse.py:569-808`
- approval queue data structures in
  `backend/api/cleanhouse_monitoring.py:225-294`
- timeline and receipt structures in
  `backend/api/cleanhouse_monitoring.py:473-623`
- scope analysis in `backend/api/cleanhouse_monitoring.py:1117-1200`
- receipt and replay construction in
  `backend/api/cleanhouse_monitoring.py:3288-3747`
- process collection in `corefiles/collectors/process_monitor.py:78-163` and
  `backend/api/cleanhouse_monitoring.py:4407-4483`
- file baseline and hash comparison in `corefiles/integrity.py:223-380`
- optional filesystem event persistence in `backend/events.py:743-787`
- command wrapper capture in `corefiles/collectors/command_observer.py:23-106`
- network connection snapshots in `corefiles/collectors/data_flow_tracer.py:175-262`

### Runtime Checks

The following commands were run against the current checkout.

| Command | Result | Evidence |
|---|---|---|
| `python3 -m unittest tests.test_events_api tests.test_cleanhouse_monitoring_api tests.test_cleanhouse_integration tests.test_avatar_receipt_regression_gate` | pass | `Ran 118 tests in 13.041s`, `OK` |
| same unittest run | warning evidence | repeated `ResourceWarning: unclosed database`, one `Event write queue full; dropped record event`, and `Error getting processes: [Errno 1] Operation not permitted: 'ps'` |
| `python3 -m corefiles.collectors.process_monitor --once` in sandbox | partial | exited `0`, but process scan reported `Operation not permitted` and returned `0` processes |
| `python3 -m corefiles.collectors.process_monitor --once` outside sandbox | pass for inventory | reported `731` total processes, `50` displayed, `9` VS Code-platform matches, `1` Cursor-platform match, `11` agent-pattern matches |
| `python3 -m corefiles.collectors.agent_movement_monitor --once` in sandbox | partial | process scan failed with `Operation not permitted`, file/network activity still reported |
| `python3 -m corefiles.collectors.agent_movement_monitor --once` outside sandbox | pass for scan, weak semantics | active platforms `vscode, codex, cursor`, file activity `codex`, network activity `vscode, codex`, `123` agent-pattern matches |
| `python3 scripts/avatar_receipt_regression_gate.py --artifact-dir /private/tmp/cleanhouse-audit-avatar-gate` in sandbox | environment-limited | localhost runtime exited with `Operation not permitted` |
| same avatar gate outside sandbox | pass | status `ok`, no failures, expected mutation true negative, out-of-scope traversal true positive, action and diff evidence present, bundle export/import/repeat import verified |
| `python3 -c "import watchdog"` | fail | `ModuleNotFoundError: No module named 'watchdog'` |
| `python3 -c "from backend import events; ..."` | partial | `FileSystemEventHandler False`, `Observer False`, writer metrics all zero |
| `python3 -c "from corefiles.integrity import scan_integrity; print(scan_integrity()['status'])"` | partial | `no_baseline` |

No frontend browser automation was used.

## Canonical Product Spine

The finalized conclusion defines the product spine as:

```text
objective -> actions -> mutations -> receipts -> approval/rollback
```

This audit uses these meanings:

- Objective: declared local work boundary, scope, repo/runtime surface, expected
  output, and exclusions.
- Actions: prompt/context submission, tool events, commands, process starts,
  automation hooks, and service actions that can move local state.
- Mutations: filesystem changes, hash deltas, snapshot diffs, process changes,
  port/network changes, and service queue changes.
- Receipts: replayable evidence artifact containing objective, actions,
  mutations, evidence refs, timeline, gaps, scope analysis, approval state, and
  integrity data.
- Approval/rollback: evidence-scoped review and recovery state. Approval is not
  route ownership unless CleanHouse owns the route. Rollback is not complete
  without tested recovery evidence.

## Spine Comparison

### 1. Objective

Operational:

- `/cleanhouse/objective/start` and `/cleanhouse/objective/end` create objective
  events with `session_id`, `objective_id`, event type, and summary
  (`backend/api/cleanhouse.py:288-343`).
- `/cleanhouse/prompt` accepts `session_id`, `objective_id`, `scope`,
  `repo_path`, `context`, and `tool_identity`
  (`backend/api/cleanhouse.py:350-394`).
- operator sessions store `objective_id`, status, summary, evidence refs, and
  metadata (`backend/api/cleanhouse_monitoring.py:297-323`).

Substrate-only:

- Objective events in `backend/events.py` persist as
  `timestamp/session_id/event_type/path/summary`, not as a full objective
  contract (`backend/events.py:172-217`).
- SQLite objective receipt selection is based on event windows and objective
  marker paths (`backend/events.py:551-653`), not a required objective root for
  all runtime evidence.

Partially implemented:

- Prompt/context records carry the richest objective boundary, but they are not
  mandatory for every route or mutation source.
- Objective IDs are present in prompt and operator records, but not guaranteed
  on every process, network, file watcher, integrity, or shell event.

Missing:

- a required objective envelope for every session;
- canonical objective fields for allowed paths, excluded paths, repo/runtime
  surface, expected output, and route ownership;
- propagation of `objective_id` into every collector and every evidence ref;
- an explicit unknown state when actions/mutations occur without an objective.

Audit finding:

Objective support is usable for the owned prompt/fixture path. It is not yet the
root of every runtime trace.

### 2. Actions

Operational:

- `corefiles/collectors/command_observer.py` wraps owned subprocess execution and records command,
  args, cwd, user, return code, duration, timestamp, and output previews
  (`corefiles/collectors/command_observer.py:23-106`).
- tool events are represented as immutable records with tool identity, command,
  args, exit code, cwd, timestamp, session ID, and duration
  (`backend/api/cleanhouse_monitoring.py:678-700`).
- prompt/context ingestion records text, context, scope, repo path, tool
  identity, session ID, objective ID, timestamp, and source
  (`backend/api/cleanhouse_monitoring.py:200-222`).

Substrate-only:

- Process inventory reports currently running processes and substring/pattern
  matches (`corefiles/collectors/process_monitor.py:78-163`).
- Agent movement scanning records platform/file/network activity in its own log
  path, but it is not the same as objective-scoped action lineage.

Partially implemented:

- The command observer only sees commands routed through `get_observer().run`.
  Normal shell commands outside that wrapper are unknown to CleanHouse.
- Tool events work when an adapter submits them. They do not automatically
  capture third-party tools unless integrated.
- Process records lack parent PID in `corefiles/collectors/process_monitor.py`; the collector uses
  `ps aux`, which does not produce process ancestry.

Missing:

- universal shell activity capture or explicit unsupported-shell gaps;
- process start/exit lineage with PID, PPID, start time, command, user, and
  objective edge;
- background service action attribution beyond broad process snapshots;
- automation pipeline adapters that normalize task IDs, job IDs, and executed
  commands into CleanHouse actions.

Audit finding:

Action capture is credible for owned wrappers and submitted tool events. It is
not yet universal shell/process/delegation coverage.

### 3. Mutations

Operational:

- snapshot and diff routes can compare file trees and produce change records
  (`backend/api/cleanhouse.py:569-620`).
- `_build_scope_analysis()` classifies changed paths against declared scope and
  returns counts, clusters, relations, and weights
  (`backend/api/cleanhouse_monitoring.py:1117-1200`).
- `corefiles/integrity.py` can generate a hash baseline and compare current
  files against that baseline (`corefiles/integrity.py:223-380`).
- `corefiles/collectors/data_flow_tracer.py` can snapshot local network connections with process,
  PID, host, port, connection type, and timestamp (`corefiles/collectors/data_flow_tracer.py:175-262`).

Substrate-only:

- `backend/events.py` has optional filesystem event handlers, but the current
  Python environment reports `watchdog` missing. In this audit,
  `FileSystemEventHandler` and `Observer` were both `False`.
- `scan_integrity()` returned `no_baseline`, so current hash-diff integrity is
  available as code but not operationally initialized in this environment.
- file watcher events use `CLEANHOUSE_SESSION_ID` or `default-session`
  (`backend/events.py:771-776`), not the active objective unless externally
  wired.

Partially implemented:

- Snapshot diffs prove mutations only for paths explicitly snapshotted before
  and after the action.
- Filesystem watcher events, when available, record path and event type but do
  not record the process or command that caused the file change.
- Network observations are snapshots. They do not yet form a port-open/close
  timeline or a process-network lineage tied to objective IDs.
- Process inventory lists current process state, but not process lifetime
  mutations.

Missing:

- universal file mutation capture across the watched workspace with objective
  correlation;
- process-to-file attribution;
- process lineage and process lifetime events;
- local port open/close delta tracking;
- mutation records that include collector status and unknowns when a collector
  is absent;
- a single mutation event model shared by snapshots, diffs, watcher events,
  integrity scans, process changes, and network changes.

Audit finding:

Mutation evidence is strong in explicit snapshot/diff fixtures and weak for
universal unattended mutation accountability.

### 4. Receipts

Operational:

- `SessionReceipt` aggregates metadata, events, alerts, gaps, evidence index,
  scope analysis, and integrity (`backend/api/cleanhouse_monitoring.py:591-623`).
- `build_receipt()` builds a receipt from timeline entries, alerts,
  correlation gaps, scope analysis, evidence refs, and hash chains
  (`backend/api/cleanhouse_monitoring.py:3288-3513`).
- receipt replay exports approval state, approval history, evidence chain, and a
  replay hash (`backend/api/cleanhouse_monitoring.py:3536-3591`).
- receipt timeline bundles include receipt, timeline, approval, replay,
  evidence chain, bundle hash, timeline hash, receipt root hash, replay hash,
  manifest, and signature verification
  (`backend/api/cleanhouse_monitoring.py:3593-3747`).
- the avatar regression gate passed outside the sandbox, verifying expected
  mutation, out-of-scope traversal, action evidence, diff evidence, evidence ref
  counts, approval history, and deterministic export/import/repeat import.

Substrate-only:

- The separate SQLite receipt path in `backend/events.py:656-705` summarizes
  recent event tails. It is useful substrate but not the same as the richer
  `SessionReceipt` product artifact.
- Receipt construction can produce a verdict from available timeline entries,
  but absent collectors are not always represented as receipt gaps unless they
  are routed into timeline/correlation data.

Partially implemented:

- Receipt events are strong for prompts, commands, tool events, diffs, and
  generated correlations inside the adapter.
- Receipt events are weaker for process inventory, network snapshots,
  filesystem watcher events, and integrity scanner output unless those surfaces
  are explicitly included in the timeline path.
- The test suite proves a narrow fixture and mocked/stubbed cases. It does not
  prove universal workstation coverage.

Missing:

- receipt gaps for absent `watchdog`, missing integrity baseline, shell coverage
  outside owned wrappers, missing process lineage, and missing network deltas;
- receipts that identify which collectors ran, which failed, which were skipped,
  and which surfaces remain unknown;
- import/replay verification against a full local session that includes real
  process and network collectors, not only stubs or owned fixture events.

Audit finding:

Receipts are the strongest current product layer. They are not yet universal
runtime receipts because the upstream evidence coverage is incomplete.

### 5. Approval/Rollback

Operational:

- approval queue items are metadata-only records with status, requested action,
  reason, evidence refs, prompt ID, objective ID, history, reviewer, source, and
  metadata (`backend/api/cleanhouse_monitoring.py:256-294`).
- approval creation and resolution write append-only history entries
  (`backend/api/cleanhouse_monitoring.py:2271-2456`).
- approval queue routes exist for create, list, and resolve
  (`backend/api/cleanhouse.py:479-566`).
- receipt replay includes approval state and approval history
  (`backend/api/cleanhouse_monitoring.py:3544-3585`).
- the avatar gate produced traversal approval history count `2`, confirming
  created plus resolved approval state for that fixture.

Substrate-only:

- `ApprovalQueueItem` explicitly says it is metadata-only and never pauses or
  mutates work (`backend/api/cleanhouse_monitoring.py:256-258`).
- Approval records do not own shell, process, file, or cloud action routes.

Partially implemented:

- Approval mediation is replayable and evidence-scoped where an approval item is
  created.
- It is not automatic for every boundary-expanding mutation.
- It does not yet route or hold execution unless the action path is owned by
  CleanHouse.

Missing:

- policy for when approval is required;
- route ownership for actions that must wait for review;
- evidence-backed recovery execution;
- rollback receipts proving previous state, requested recovery action, approval
  state, recovery result, and verification.

Audit finding:

Approval mediation exists as accountable review state. Rollback is not fulfilled
product behavior.

## Operational Status By Tier 1 Capability

| Tier 1 capability | Current status | Evidence | Gap |
|---|---|---|---|
| Process monitoring | partial operational | `python3 -m corefiles.collectors.process_monitor --once` works outside sandbox and returned 731 processes | no PPID lineage, broad substring classification, no objective link |
| File integrity | substrate-only in current env | baseline/verify code exists; `scan_integrity()` returned `no_baseline` | no initialized baseline, no mandatory receipt gap, no universal file coverage |
| Prompt/context ingestion | operational for owned route | `/cleanhouse/prompt`; prompt records include context, scope, repo path, session, objective | not mandatory across all sessions/tools |
| Objective receipts | partial operational | receipts include metadata, events, gaps, evidence index, scope analysis, hashes | upstream evidence incomplete; absent collectors not always encoded as gaps |
| Approval mediation | operational as review state | approval queue create/resolve; replay approval state; avatar fixture approval history count 2 | metadata only; no owned-route execution mediation |
| Timeline hydration | partial operational | tests build timelines and workstation aggregate includes timeline/mutations/receipts/approvals | no proof of full live collector hydration across process/file/network surfaces |
| Universal mutation accountability | missing as product behavior | explicit snapshot/diff fixture passes | no universal file/process/shell/network mutation capture |

## Infrastructure Being Mistaken For Product Fulfillment

The following are infrastructure and must not be reported as product completion
by themselves:

- Flask route existence;
- dashboard HTML/CSS/JS selectors;
- launch scripts and readiness checks;
- SQLite event tables;
- event writer metrics;
- process list output;
- filesystem watcher code when `watchdog` is missing;
- integrity scanner code when no baseline exists;
- substring platform matches;
- approval queue records with no owned action route;
- receipt schemas without universal upstream evidence;
- historical "complete" files about GUI, auth, registry, or launcher work.

Concrete examples:

- `README.md:159-163` correctly says endpoint claims are observational and tied
  to local collectors. That wording is evidence-compatible, but endpoint
  existence still does not prove the full product spine.
- `../reports/FINAL_STATUS.md:1-6` and `../reports/FINAL_STATUS.md:127-136` claim UI refactor
  completion. That may describe UI architecture work, not Tier 1 runtime
  accountability.
- `../reports/COMPREHENSIVE_SUMMARY.md:14-18` and
  `../reports/COMPREHENSIVE_SUMMARY.md:192-205` describe auth and registry status. That is
  adjacent product infrastructure, not objective-scoped runtime lineage.
- `../canon/CLEANHOUSE_EVIDENCE_AUDIT.md:8-25` marks component availability as confirmed.
  Under the finalized thesis, component availability is not product fulfillment
  unless the component participates in an end-to-end objective receipt.

## Runtime Evidence That Contradicts Completion Claims

The current runtime evidence imposes these limits:

1. Filesystem watcher code exists, but current Python lacks `watchdog`.
   Runtime check: importing `watchdog` failed, and `events.FileSystemEventHandler`
   plus `events.Observer` were both `False`.

2. File integrity code exists, but the current environment has no initialized
   baseline.
   Runtime check: `scan_integrity()` returned `no_baseline`.

3. Process monitoring exists, but it is permission-sensitive and not lineage
   capture.
   Runtime check: sandboxed `python3 -m corefiles.collectors.process_monitor --once` returned zero processes
   due `Operation not permitted`; outside sandbox it listed process inventory but
   not parent-child ancestry.

4. Agent/process labels are pattern matches, not identity proof.
   Runtime check: the outside-sandbox process run tagged ordinary system names
   containing `agent`; the movement scanner produced `123` agent-pattern matches,
   many from platform/system names rather than delegated work records.

5. Localhost receipt regression passes only when the environment permits
   localhost runtime startup.
   Runtime check: the avatar gate failed in sandbox with `Operation not
   permitted`, then passed outside sandbox. The product must report environment
   limits as evidence, not hide them.

6. The test suite passes but exposes runtime hygiene issues.
   Runtime check: 118 tests passed, while output also contained unclosed SQLite
   connection warnings, a queue saturation drop, and a process scan permission
   error.

7. The strongest end-to-end proof is still a narrow fixture.
   Runtime check: the avatar gate proves expected mutation and out-of-scope
   traversal through prompt, action, diff, receipt, approval, and replay. It does
   not prove universal filesystem, shell, process, background service, and
   network accountability.

## Current Operational Surface

Operational enough to build on:

- prompt/context ingestion route;
- objective start/end event routes;
- command observer for owned subprocess calls;
- tool event submission;
- snapshot and diff generation;
- scope analysis by declared path prefix;
- timeline construction from adapter-held records;
- receipt generation with evidence refs and hash chain;
- receipt replay and signed bundle export/import verification;
- approval queue create/resolve with history;
- operator workstation aggregation in backend tests;
- narrow avatar receipt regression gate.

Partially operational:

- process inventory and platform/pattern matching;
- network snapshots;
- integrity scan if a baseline exists;
- filesystem event collection if `watchdog` exists and the watcher is started;
- dashboard controls as static-backed operator surface;
- collector failure reporting.

Substrate-only:

- launchers;
- dashboard presence;
- route registration;
- SQLite tables;
- versioned JSON artifact persistence;
- optional browser notification UI;
- old GUI/auth/modularization completion docs;
- old integrity counters and visual graphs.

Missing as Tier 1 product behavior:

- universal file mutation coverage;
- process lineage;
- shell coverage outside owned wrapper;
- objective propagation into every collector;
- port/network delta history;
- background service action correlation;
- receipt gaps for every unobserved required surface;
- approval requirement policy;
- owned-route mediation for review-required actions;
- evidence-backed rollback;
- one canonical event schema shared by every collector.

## Engineering Gap List

### P0: Lock The Evidence Event Contract

Current state:

- `backend/events.py` persists a minimal event row:
  `timestamp/session_id/event_type/path/summary`.
- `backend/api/cleanhouse_monitoring.py` has richer in-memory and persisted JSON
  records, but not every collector emits the same event shape.

Required Tier 1 contract:

Every event that can appear in a timeline or receipt must carry:

- `event_id`
- `session_id`
- `objective_id`
- `source_surface`
- `actor_type`
- `event_type`
- `timestamp`
- `evidence_level`
- `observed_vs_expected`
- `evidence_refs`
- `collector_status`
- `raw_evidence_ref`
- `scope_relation` where applicable

Completion gate:

Build one adapter path that emits this event shape for prompt, tool event,
command, snapshot diff, process observation, file integrity result, watcher file
event, network observation, approval event, and receipt event.

### P0: Make Missing Collectors Receipt-Visible

Current state:

- Receipt gaps are based on unknown timeline entries and unmatched correlations.
- Missing `watchdog`, missing integrity baseline, sandboxed `ps`, and unowned
  shell execution do not automatically become receipt gaps.

Required Tier 1 behavior:

If a collector required for Tier 1 is absent, disabled, permission-denied, or not
run, the receipt must include that gap.

Completion gate:

A receipt created in the current environment must explicitly report:

- filesystem watcher unavailable when `watchdog` is absent;
- integrity baseline missing when `scan_integrity()` returns `no_baseline`;
- process collector permission failure when `ps` is unavailable;
- shell collector unsupported for commands not routed through the wrapper;
- network collector status for each session.

### P0: Bind Objective ID To Every Mutation

Current state:

- prompt records and operator sessions can carry objective IDs.
- watcher events use `CLEANHOUSE_SESSION_ID` or `default-session`.
- process, network, and integrity collectors are not consistently objective
  scoped.

Required Tier 1 behavior:

Every mutation must be either:

- tied to the active objective;
- tied to a different objective;
- outside any active objective;
- unknown because the collector lacks that link.

Completion gate:

Run a session with an active objective, mutate an in-scope file, mutate an
out-of-scope file, start a child process, and open a local port. The receipt must
show objective relation for each mutation or mark the relation unknown.

### P0: Implement Process Lineage

Current state:

- `corefiles/collectors/process_monitor.py` uses `ps aux`, which captures PID, user, CPU, memory,
  start, and command, but not PPID.
- `corefiles/collectors/data_flow_tracer.py` captures PID for network connections but does not link
  PID to an objective lineage.

Required Tier 1 behavior:

Process records must include PID, PPID, user, command, args, start time, and
capture time. Lineage edges must be represented as observed when PID/PPID is
available and unknown when not.

Completion gate:

Run a parent command that starts a child process. Receipt must contain parent
PID, child PID, command ancestry, timestamps, and an evidence ref for the
lineage edge.

### P0: Initialize And Prove File Integrity

Current state:

- baseline generation and verification code exists.
- current scan status is `no_baseline`.

Required Tier 1 behavior:

The local operator must be able to initialize a baseline, verify it, record hash
changes, and feed those changes into timeline and receipt artifacts.

Completion gate:

Create a baseline for a fixture workspace, modify one file, add one file, delete
one file, run integrity verification, and confirm the receipt includes all three
changes with evidence refs and scope relation.

### P1: Unify Snapshot Diff, Watcher Events, And Integrity Deltas

Current state:

- snapshot/diff, watcher events, and integrity verification are separate paths.

Required Tier 1 behavior:

All file mutation evidence should normalize into one mutation event model with
source-specific raw evidence preserved.

Completion gate:

For the same file change, receipt can show whether it was observed by snapshot
diff, watcher event, integrity hash delta, or a combination. Missing sources
must be gaps, not silence.

### P1: Clarify Pattern Match Semantics In Runtime Output

Current state:

- process and movement scans use broad substring/regex matches.
- outside-sandbox scans showed high counts from names containing `agent`, many
  of which are system or platform processes.

Required Tier 1 behavior:

Every platform or agent-related label must be presented as a deterministic
pattern match with the exact matched pattern and no identity overclaim.

Completion gate:

Process and movement scan outputs expose matched pattern, matched field, source
command, and confidence boundary. Tests assert that common system process names
are not promoted beyond pattern-match wording.

### P1: Add Port/Network Delta Timeline

Current state:

- network collection snapshots connections from `lsof`.
- tests use stubs for suspicious network cases.

Required Tier 1 behavior:

CleanHouse needs a local port/network timeline: opened, still open, closed, and
unknown, with process/PID evidence where available.

Completion gate:

Start a local server during an objective. Receipt shows process/PID, local port,
open timestamp, close timestamp if observed, and objective relation.

### P1: Make Approval Policy Explicit

Current state:

- approvals can be created and resolved.
- CleanHouse does not yet define when an approval is required.

Required Tier 1 behavior:

Approval policy must be a deterministic rule over objective scope, mutation
surface, evidence level, and collector status. It must not imply execution
control unless CleanHouse owns the route.

Completion gate:

Out-of-scope file change creates an approval item with receipt and diff evidence
refs. In-scope expected change does not. Missing collector coverage creates a
review item only if policy says so and the receipt explains why.

### P1: Separate Rollback Request From Rollback Proof

Current state:

- approval/replay state exists.
- evidence-backed rollback is not implemented.

Required Tier 1 behavior:

Rollback status must be one of:

- not requested;
- requested, no recovery route;
- requested, recovery route available;
- executed, evidence verified;
- executed, verification failed.

Completion gate:

For a fixture workspace, restore a changed file from a known previous state and
include before hash, after hash, recovery action, approval state, and verification
result in the receipt.

### P2: Prove Operator Timeline Hydration Without Browser Automation

Current state:

- backend tests prove workstation aggregate data contains objectives, timeline,
  mutations, receipts, approvals, receipt replays, notifications, and evidence
  summaries.
- static tests prove dashboard selectors and functions exist.

Required Tier 1 behavior:

Human-operated dashboard verification must confirm that the local operator can
declare an objective, observe mutations, inspect why a receipt was flagged,
approve/reject, and replay evidence.

Completion gate:

Record a manual operator receipt from the dashboard with exact session ID,
objective ID, evidence refs, approval ID, receipt ID, and replay hash. No
browser automation is required or used.

## Minimal Tier 1 Acceptance Chain

Tier 1 should not be claimed until this exact chain passes in a fresh local
workspace:

1. Start CleanHouse from the canonical local launcher.
2. Declare one objective with scope, repo path, context, and expected output.
3. Submit prompt/context for that objective.
4. Route one command through the command observer.
5. Start one child process and capture PID/PPID lineage.
6. Mutate one in-scope file and one out-of-scope file.
7. Capture file evidence through snapshot diff and either watcher or integrity
   delta.
8. Open and close one local port and capture process/network evidence.
9. Build timeline with prompt, command, process, file, network, and approval
   entries.
10. Generate receipt with evidence refs, gaps, scope analysis, and hash chain.
11. Create and resolve approval for the out-of-scope mutation.
12. Replay receipt and verify receipt root hash, timeline hash, replay hash,
    approval history, and evidence ref count.
13. Export and re-import the receipt bundle.
14. Confirm every missing collector or unsupported route appears as a receipt
    gap.

## Current Product Boundary

CleanHouse can currently be claimed as:

> A local-first runtime accountability substrate with operational prompt/context
> ingestion, snapshot/diff mutation evidence, objective receipts, approval review
> records, replayable receipt bundles, process inventory, file integrity code,
> and optional local collector paths.

CleanHouse cannot yet be claimed as:

> A completed Tier 1 universal runtime accountability system across all local
> filesystem, process lineage, shell activity, port/network, prompt/context,
> background service, approval, rollback, and delegated execution surfaces.

The evidence-first conclusion is therefore:

CleanHouse is close enough to prove the shape of the product spine in controlled
owned routes. It is not yet complete because the upstream runtime coverage is
not universal, collector absence is not consistently receipted as a gap,
objective IDs do not bind every mutation, process lineage is missing, shell
coverage is wrapper-only, file integrity is not initialized in the current
environment, watcher support is unavailable in the current Python runtime, and
rollback has no verified recovery evidence.

Anything stronger than that would violate the doctrine:

```text
Runtime truth outranks tone.
Evidence outranks confidence.
```
