# CleanHouse: Evidence-First Runtime Accountability Thesis

Doctrine: "Runtime truth outranks tone. Evidence outranks confidence."

## Thesis

CleanHouse is a local-first runtime accountability and coordination system. Its
purpose is to make local execution answerable: what was requested, what boundary
was declared, which local action paths moved, what evidence exists, where the
chain is incomplete, who or what delegated the work, what approval state applied,
and how the resulting record can be replayed.

The product claim is not that CleanHouse knows why a human, agent-labeled tool,
automation script, or background service acted. The claim is that CleanHouse
must observe local runtime surfaces, normalize them into interpretable execution
lineage, and produce receipts that separate observed facts from inferred links
and unknown gaps.

Universal observation in this thesis means every local action surface is in
scope for evidence capture: filesystem mutations, process identity and lineage,
shell execution, tool-boundary events, port and network changes, objective
boundaries, approval state, delegated execution, and background service activity.
It does not mean omniscience. When CleanHouse cannot see a surface, the correct
output is an evidence gap, not a confident story.

## Core Doctrine

1. Runtime truth outranks tone. A polished explanation is invalid if the runtime
   evidence contradicts it.
2. Evidence outranks confidence. A confidence score may rank a claim, but it
   cannot replace an observed event, hash, command record, process record,
   network record, approval entry, or receipt.
3. Every claim must carry an evidence level: observed, inferred, or unknown.
4. Unknown is a first-class result. Missing data, collector failure, and broken
   correlation must remain visible.
5. CleanHouse records local execution, not remote model internals or hidden
   reasoning state.
6. Actor labels are attribution metadata, not proof of agency. Humans, agents,
   automation tools, and background services are all local runtime participants
   only when a local event identifies them.
7. Approval mediation is evidence-scoped. Unless CleanHouse owns the execution
   route, an approval item records and coordinates review; it does not silently
   mutate the action path.

## Product Definition

CleanHouse turns "work happened" into an auditable local record:

```text
objective boundary
-> prompt or delegated request
-> shell/tool/process event
-> filesystem/network/port observation
-> correlation edge
-> timeline entry
-> approval state
-> receipt
-> replay bundle
```

This is the product distinction. CleanHouse is not merely a process list, file
hash scanner, API endpoint, or dashboard. Those are collectors and substrate.
The product layer is the accountable execution chain that explains local runtime
actions through evidence references, objective boundaries, receipt integrity,
operator review, and replayable state.

## Evidence Surfaces

### Filesystem Mutations

CleanHouse must treat filesystem creation, modification, deletion, baseline
drift, and snapshot differences as primary runtime evidence.

Current evidence:

- `backend/events.py:743-776` defines a watchdog-backed file handler that emits
  `created`, `modified`, and `deleted` events into local event persistence.
- `backend/api/cleanhouse_monitoring.py:359-424` defines immutable snapshot and
  diff record structures for file entries and file changes.
- `backend/api/cleanhouse.py:569-620` exposes snapshot and diff endpoints.
- `corefiles/integrity.py:223-258` generates hash baselines.
- `corefiles/integrity.py:294-379` verifies current files against a baseline and
  reports changed paths.

Acceptance rule: a file claim is valid only when it resolves to an event,
snapshot, diff, baseline mismatch, or explicit collector gap.

### Process Identity And Lineage

CleanHouse must observe process execution as local runtime evidence and evolve
from process inventory toward parent-child lineage.

Current evidence:

- `corefiles/collectors/process_monitor.py:78-121` collects `ps aux` output into process records.
- `corefiles/collectors/process_monitor.py:123-163` performs deterministic platform and
  agent-pattern matching against process command strings.
- `backend/api/cleanhouse_monitoring.py:4407-4484` normalizes process collector
  output into local evidence references.
- `corefiles/collectors/data_flow_tracer.py:126-153` resolves additional per-PID process information
  for network records.

Current boundary: the repository supports process inventory and process-pattern
classification. Full lineage requires explicit parent PID, process start time,
and command ancestry capture before it can be claimed as complete.

Acceptance rule: process lineage must be represented as a chain of observed
process records. If parentage is missing, the lineage segment is unknown.

### Shell Activity

CleanHouse must observe shell execution when commands are routed through owned
wrappers or instrumented adapters.

Current evidence:

- `corefiles/collectors/command_observer.py:23-35` defines immutable command result metadata.
- `corefiles/collectors/command_observer.py:48-106` wraps `subprocess.run`, captures command args,
  cwd, user, return code, duration, timestamp, stdout preview, and stderr
  preview, then emits completion callbacks.
- `backend/api/cleanhouse_monitoring.py:1285-1305` turns completed commands into
  `process_event` records.
- `backend/api/cleanhouse_monitoring.py:4855-4890` exposes buffered command
  execution as local evidence.

Current boundary: CleanHouse can prove commands it routes or receives. It cannot
claim global shell coverage for commands executed outside owned wrappers.

Acceptance rule: a shell claim must include command, args, cwd, user if known,
exit code, timestamp, and evidence reference.

### Port And Network Changes

CleanHouse must observe local network and port state as runtime evidence and
tie it to process identity where possible.

Current evidence:

- `corefiles/collectors/data_flow_tracer.py:175-260` scans `lsof -i -P -n`, extracts process, PID,
  connection type, host, port, domain, and timestamp, and maintains a
  process-network map.
- `corefiles/collectors/agent_movement_monitor.py:316-384` scans network connections for configured
  platform process names and endpoint patterns.
- `backend/api/cleanhouse_monitoring.py:4485-4605` normalizes network
  observations into evidence records.
- `backend/api/cleanhouse.py:215-218` exposes `/cleanhouse/network`.

Current boundary: the code observes snapshots of local connection state. It is
not packet capture, traffic inspection, or an enforcement boundary.

Acceptance rule: a network claim must include process, PID when available, host
or domain, port, source command or collector, timestamp, and evidence level.

### Objective Boundaries

CleanHouse must make the declared work boundary explicit before comparing any
runtime delta against that boundary.

Current evidence:

- `backend/api/cleanhouse.py:288-314` records objective start events.
- `backend/api/cleanhouse.py:317-343` records objective end events.
- `backend/api/cleanhouse_monitoring.py:1117-1200` computes scope analysis over
  diff records, including in-boundary counts, out-of-boundary counts, path
  clusters, classification, and weight.
- `backend/events.py:551-653` selects receipt event windows around objective
  segments.

Acceptance rule: no boundary claim is valid without the declared objective,
session ID, evidence window, and changed-path evidence.

### Delegated Execution

CleanHouse must treat delegated execution as a first-class source of evidence
when a human asks a tool, agent-labeled process, automation script, plugin, or
service to act.

Current evidence:

- `backend/api/cleanhouse_monitoring.py:653-675` stores plugin metadata without
  importing or executing plugin code.
- `backend/api/cleanhouse_monitoring.py:678-700` defines immutable tool command
  boundary events.
- `backend/api/cleanhouse_monitoring.py:1352-1417` accepts tool events and emits
  local evidence references.
- `backend/api/cleanhouse.py:899-910` exposes `/cleanhouse/tool-event`.

Current boundary: delegated execution is provable only when the delegate emits a
tool event, runs through an observed command path, or appears in another local
collector. Otherwise it is an unknown gap.

Acceptance rule: every delegated action must carry tool identity, command or
action label, args when available, cwd when available, exit code or status,
session ID when available, timestamp, and evidence reference.

### Background Services

CleanHouse must observe background service behavior through local process,
filesystem, network, and event-writer evidence rather than through assumptions
about purpose.

Current evidence:

- `backend/events.py:335-349` starts a daemon event-writer thread.
- `backend/events.py:380-394` exposes writer metrics for queued, written,
  dropped, retry, and max-depth counts.
- `corefiles/collectors/process_monitor.py:49-54` includes configured patterns for background service
  command strings.

Acceptance rule: background service claims must be grounded in process,
filesystem, network, command, queue, or receipt evidence.

## Execution Lineage Model

CleanHouse lineage is a graph of local evidence. Each node must be durable
enough to survive replay, and each edge must state whether it is observed,
inferred, or unknown.

Required node types:

- Objective node: declared boundary, session, start/end time.
- Prompt or request node: user-facing request text and context when provided.
- Actor node: human, tool identity, process identity, plugin identity, or
  service label when locally observed.
- Command node: shell or tool command boundary.
- Process node: PID, command, user, platform-pattern match if any.
- Filesystem node: file event, snapshot, diff, path, hash where available.
- Network node: process, PID, host/domain, port, connection type.
- Correlation node: relationship between evidence records.
- Timeline node: ordered execution step with previous event pointer.
- Approval node: requested action, reason, reviewer state, history.
- Receipt node: summary, evidence index, gaps, scope analysis, integrity chain.
- Replay node: receipt-root hash, approval state, evidence chain.

Required edge rules:

- Same-session edges require a shared session ID.
- Time-adjacent edges require timestamps and a documented window.
- Process-network edges require PID or process metadata.
- File-boundary edges require changed paths and declared objective scope.
- Approval edges require explicit evidence refs.
- Receipt and replay edges require stable hashes.
- If an edge cannot be proven, it is unknown. It must not be silently omitted.

Current evidence:

- `backend/api/cleanhouse_monitoring.py:94-147` defines evidence refs and
  immutable event objects with evidence level, rationale, confidence,
  uncertainty, and observed-vs-expected fields.
- `backend/api/cleanhouse_monitoring.py:427-470` defines correlation edges with
  confidence, uncertainty, time delta, and observed-vs-expected metadata.
- `backend/api/cleanhouse_monitoring.py:473-514` defines immutable timeline
  entries and timeline records.
- `backend/api/cleanhouse_monitoring.py:2752-2933` builds chronological session
  timelines from prompts, commands, tool actions, diffs, correlations, and
  approval history.

## Receipts

A CleanHouse receipt is the evidence-first answer to "what happened here?"

It must include:

- session metadata;
- objective boundary and declared scope where available;
- ordered timeline events;
- evidence index;
- visible gaps;
- boundary analysis;
- approval state if review was requested;
- hash chain over receipt events;
- root hash over the replay-relevant record.

Current evidence:

- `backend/api/cleanhouse_monitoring.py:591-623` defines deterministic session
  receipt fields.
- `backend/api/cleanhouse_monitoring.py:3288-3513` builds session receipts from
  timelines, alerts, gaps, evidence index, scope analysis, and hash chains.
- `backend/events.py:656-705` builds local SQLite receipt records from selected
  objective/session events.
- `backend/api/cleanhouse.py:738-778` exposes receipt creation and listing.

Receipt doctrine: a receipt is not a narrative. It is a replayable evidence
artifact with explicit gaps. If the evidence chain is incomplete, the receipt
must say so.

## Approval Mediation

CleanHouse approval mediation exists to make review explicit and traceable.

Current evidence:

- `backend/api/cleanhouse_monitoring.py:225-253` defines append-only approval
  history entries.
- `backend/api/cleanhouse_monitoring.py:256-294` defines approval queue items
  and states that the queue is metadata-only and never pauses or mutates work.
- `backend/api/cleanhouse_monitoring.py:2271-2359` creates approval queue items
  with evidence refs and notification records.
- `backend/api/cleanhouse_monitoring.py:2388-2454` resolves approval queue items
  with reviewer, status, note, and history.
- `backend/api/cleanhouse.py:479-566` exposes approval queue creation, listing,
  and resolution.

Approval doctrine: mediation is valid when it records the requested action,
reason, evidence refs, reviewer action, and replay state. Enforcement requires
owned execution routes and must not be implied by documentation alone.

## Replayable Evidence

Replay is the test that keeps CleanHouse from becoming a confidence engine.
The system must be able to rebuild the relevant state from persisted receipt,
timeline, approval, and evidence refs.

Current evidence:

- `backend/api/cleanhouse_monitoring.py:3536-3591` replays receipt state from
  receipt ID, approval state, approval history, evidence chain, and replay hash.
- `backend/api/cleanhouse_monitoring.py:3593-3650` exports a receipt timeline
  bundle with receipt, timeline, approval, replay, evidence chain, integrity
  hashes, manifest, and signature.
- `backend/api/cleanhouse_monitoring.py:3682-3749` verifies receipt timeline
  bundles.
- `backend/api/cleanhouse.py:781-808` exposes receipt replay, bundle export, and
  bundle import.

Replay doctrine: if a later reader cannot reconstruct what evidence supported a
claim, the claim is not CleanHouse-valid.

## Coordination Model

CleanHouse coordinates runtime work by making boundaries and evidence explicit:

1. Start an objective.
2. Record prompt or delegated request context.
3. Observe shell, tool, process, filesystem, and network surfaces.
4. Build snapshots, diffs, correlations, and timelines.
5. Mark boundary drift, collector gaps, and unknown segments.
6. Request approval when review is needed.
7. Resolve approval with append-only history.
8. Finalize receipt.
9. Export or replay receipt bundle.

This coordination model applies across humans, agent-labeled tools, automation
scripts, plugins, and services because CleanHouse uses local evidence contracts
rather than trust in the actor's explanation.

## Current Capability Map

| Capability | Current evidence | Thesis status |
|---|---|---|
| Filesystem event persistence | `backend/events.py:743-776` | Implemented for watched paths when watchdog is available |
| File snapshot and diff | `backend/api/cleanhouse.py:569-620`; `backend/api/cleanhouse_monitoring.py:359-424` | Implemented as API-backed evidence artifact |
| File integrity baseline | `corefiles/integrity.py:223-379` | Implemented, but wording must avoid overclaiming beyond hash comparison |
| Process inventory | `corefiles/collectors/process_monitor.py:78-163` | Implemented as local `ps aux` inventory and pattern matching |
| Process lineage | partial evidence in process/PID records | Required gap: parent-child lineage chain |
| Shell command evidence | `corefiles/collectors/command_observer.py:23-106` | Implemented for routed subprocess execution |
| Global shell coverage | no universal collector evidence | Required gap: owned shell wrapper or terminal integration |
| Network and port snapshot | `corefiles/collectors/data_flow_tracer.py:175-260` | Implemented as `lsof` snapshot evidence |
| Objective boundaries | `backend/api/cleanhouse.py:288-343`; `backend/events.py:551-653` | Implemented as events and receipt-window selection |
| Delegated tool events | `backend/api/cleanhouse_monitoring.py:678-700`; `backend/api/cleanhouse.py:899-910` | Implemented when tools submit events |
| Approval queue | `backend/api/cleanhouse_monitoring.py:225-294`; `backend/api/cleanhouse.py:479-566` | Implemented as metadata and history, not route enforcement |
| Timeline | `backend/api/cleanhouse_monitoring.py:473-514`; `backend/api/cleanhouse_monitoring.py:2752-2933` | Implemented for captured session artifacts |
| Receipt | `backend/api/cleanhouse_monitoring.py:591-623`; `backend/api/cleanhouse_monitoring.py:3288-3513` | Implemented as evidence artifact with gaps and hash chain |
| Replay bundle | `backend/api/cleanhouse_monitoring.py:3536-3650` | Implemented for receipt replay/export |

## Acceptance Gates

CleanHouse should not claim this thesis as complete until these gates pass with
local evidence:

1. Filesystem gate: create, modify, and delete a file under the watched path;
   verify persisted events, timeline inclusion, receipt inclusion, and replay
   evidence refs.
2. Process lineage gate: run a parent command that launches a child process;
   verify parent PID, child PID, command ancestry, timestamp, and receipt
   inclusion. If parentage is missing, the result must be unknown.
3. Shell gate: route a command through the command observer; verify args, cwd,
   user, return code, duration, stdout/stderr preview, timeline entry, and
   receipt hash chain.
4. Network/port gate: open and close a local listening port or outbound
   connection; verify process, PID, host/domain, port, timestamp, and
   evidence-level labeling.
5. Objective gate: declare a scope, modify files inside and outside it, compute
   diff, build scope analysis, and verify in-boundary and out-of-boundary counts
   in the receipt.
6. Delegation gate: submit a `/cleanhouse/tool-event` for a tool command; verify
   tool identity, command, args, exit code, timeline action, and receipt
   evidence ref.
7. Approval gate: create and resolve an approval queue item with evidence refs;
   verify append-only history and replay state.
8. Replay gate: export, import, and verify a receipt timeline bundle; verify
   receipt root hash, timeline hash, replay hash, evidence refs, manifest, and
   signature verification.
9. Gap gate: disable or fail a collector; verify the output reports unknown or
   gap state instead of success language.

## Anti-Overclaim Boundary

CleanHouse must not claim any of the following unless future code provides
direct runtime evidence:

- knowledge of hidden reasoning state;
- knowledge of why an actor acted;
- complete visibility into remote services;
- global shell capture outside owned wrappers;
- full process ancestry before parent-child collection exists;
- network enforcement or packet inspection;
- automatic approval enforcement outside routes CleanHouse owns;
- actor identity beyond locally observed process, user, tool, plugin, or service
  metadata;
- completion when collectors failed, evidence is missing, or replay cannot
  reconstruct the claim.

The rigorous version of CleanHouse is therefore stricter than a dashboard. It is
a local runtime accountability layer where every explanation is downstream of
observable execution, every gap remains visible, every approval is traceable,
and every final claim can be replayed from evidence.
