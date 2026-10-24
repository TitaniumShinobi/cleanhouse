# CleanHouse Evidence-First Conclusion

Date: 2026-05-25

Doctrine: Runtime truth outranks tone. Evidence outranks confidence.

## Conclusion

CleanHouse should be defined as a local-first runtime accountability and
coordination system for delegated execution environments. Its product claim is
not that it understands why a human, coding tool, automation pipeline, shell
process, background service, or cloud/runtime connector acted. Its product claim
is that local execution can be made answerable when every observed action is
attached to a declared objective, every mutation is traced to available runtime
evidence, every missing segment is marked unknown, every approval is recorded
against evidence references, and every session can produce a receipt.

The thesis and research converge on one operational position: existing systems
observe fragments, but they do not give the local operator one grounded chain
from delegated work to runtime mutation. Observability products trace services.
Endpoint tools record process, file, and network events. Policy systems evaluate
defined control points. Approval systems review merges, deploys, tickets, or
plans. Coding-agent platforms produce worklogs and pull requests. Provenance
systems trace artifacts. CleanHouse's product lane is the missing local
coordination layer that binds those fragments under the operator's objective.

That lane is only credible if CleanHouse remains evidence-first. If a process is
seen, CleanHouse reports the process record. If a file hash changes, CleanHouse
reports the hash mismatch or file event. If a command runs through an owned
wrapper, CleanHouse reports command metadata. If a tool submits an event,
CleanHouse records that tool boundary. If a port or network connection is seen,
CleanHouse records the observed endpoint data. If the link between those facts is
only time-adjacent, CleanHouse labels it inferred. If the link is missing,
CleanHouse labels it unknown. Confidence can rank a claim, but it cannot replace
runtime evidence.

## Stabilized Product Spine

The stabilized CleanHouse spine is:

```text
objective -> actions -> mutations -> receipts -> approval/rollback
```

Each spine segment has a strict evidence role.

### Objective

The objective is the local boundary of work. It records the session, requested
outcome, scoped path or runtime surface, expected output, and known exclusion
zones. It is not proof of purpose. It is the baseline used to compare observed
runtime changes against the declared work boundary.

Current evidence anchors:

- `backend/api/cleanhouse.py:288-343` records objective start and end events.
- `backend/events.py:551-653` selects receipt windows around objective segments.
- `backend/api/cleanhouse_monitoring.py:1117-1200` computes scope analysis from
  file diffs and declared scope.

### Actions

Actions are the observable execution boundaries that may move the machine:
prompt/context submission, command execution, process creation, tool events,
automation hooks, plugin metadata, and service activity. CleanHouse should
record actions only when they pass through an owned surface or are visible to a
collector.

Current evidence anchors:

- `corefiles/collectors/command_observer.py:23-106` captures command metadata for routed subprocess
  execution.
- `backend/api/cleanhouse_monitoring.py:1483-1568` records prompt/context and
  session records.
- `backend/api/cleanhouse_monitoring.py:678-700` defines tool event records.
- `backend/api/cleanhouse_monitoring.py:1352-1417` accepts tool events and emits
  evidence refs.

### Mutations

Mutations are runtime changes: filesystem events, hash mismatches, snapshot
diffs, process state changes, local port/network observations, and service queue
state. A mutation is not automatically good or bad. It is a runtime fact that
must be attached to evidence and compared against the objective.

Current evidence anchors:

- `backend/events.py:743-776` emits file create, modify, and delete events for
  watched paths when watchdog is available.
- `corefiles/integrity.py:223-379` generates file baselines and reports hash
  differences.
- `corefiles/collectors/process_monitor.py:78-163` records process inventory and deterministic
  pattern matches.
- `corefiles/collectors/data_flow_tracer.py:175-260` records local network connection snapshots with
  process, PID, host, port, and timestamp.

### Receipts

Receipts are the product-level artifact. A receipt aggregates the objective,
actions, mutations, evidence refs, timeline entries, scope analysis, approval
state, visible gaps, and integrity metadata. A receipt is not a reassuring
summary. It is the replayable local record of what CleanHouse could and could not
prove.

Current evidence anchors:

- `backend/api/cleanhouse_monitoring.py:591-623` defines session receipt fields.
- `backend/api/cleanhouse_monitoring.py:3288-3513` builds receipts from timeline,
  alerts, gaps, evidence index, scope analysis, and hash chain.
- `backend/api/cleanhouse_monitoring.py:3536-3650` replays receipt state and
  exports receipt timeline bundles.

### Approval/Rollback

Approval is an evidence-scoped review state. It records what action required
review, why review was requested, what evidence refs support the request, who
resolved it, and how that resolution appears during replay.

Rollback is not yet fulfilled product behavior unless it is tied to an owned,
tested recovery route. In the stabilized product spine, rollback is therefore a
receipt-backed recovery lane: the receipt must identify what changed, what
previous state exists, what recovery action was requested, what approval state
applies, and whether recovery evidence exists. If recovery cannot be performed or
verified, CleanHouse must say so.

Current evidence anchors:

- `backend/api/cleanhouse_monitoring.py:225-294` defines approval history and
  approval queue records.
- `backend/api/cleanhouse_monitoring.py:2271-2454` creates and resolves approval
  queue items.
- `backend/api/cleanhouse.py:479-566` exposes approval queue creation, listing,
  and resolution.
- `../canon/CLEANHOUSE_EVIDENCE_AUDIT.md:53-65` identifies current restore-related code
  as placeholder behavior, so rollback must not be described as complete.

## Infrastructure Versus Fulfilled Product Behavior

CleanHouse has infrastructure that can support the product, but infrastructure is
not the same thing as fulfilled product behavior.

Infrastructure includes:

- Flask routes;
- pywebview launcher path;
- SQLite event persistence;
- frontend dashboard files;
- command wrappers;
- collector adapters;
- approval queue records;
- timeline and receipt schemas;
- scripts and launch aliases.

Fulfilled product behavior requires evidence that those pieces work together as
the accountable spine:

```text
declared objective
-> captured action
-> observed mutation
-> hydrated timeline
-> receipt with evidence refs and gaps
-> approval state
-> replayable record
```

A server that starts is infrastructure. A route that returns JSON is
infrastructure. A dashboard that renders cards is infrastructure. A watcher that
increments file-event counts is infrastructure. The fulfilled product behavior is
the end-to-end session record that proves which objective was active, which
actions occurred, which mutations followed, which links were observed or
inferred, which links were unknown, and which approval or recovery state applied.

This distinction matters because CleanHouse can otherwise look complete while the
actual product layer remains missing. Runtime truth must therefore be measured by
objective-scoped receipts and timeline hydration, not by launch success or UI
presence alone.

## Tier 1 MVP Definition

Tier 1 is the smallest operational version of CleanHouse that proves the product
spine locally.

Tier 1 MVP:

```text
process monitoring
+ file integrity
+ prompt/context ingestion
+ objective receipts
+ approval mediation
+ timeline hydration
```

### Tier 1 Scope

| Capability | Tier 1 requirement | Evidence boundary |
|---|---|---|
| Process monitoring | Capture local process records and deterministic platform/pattern matches | `corefiles/collectors/process_monitor.py`; `/cleanhouse/processes` |
| File integrity | Generate baseline, compare current files, report hash mismatches and file diffs | `corefiles/integrity.py`; snapshot/diff routes |
| Prompt/context ingestion | Record declared request, scope, repo path, tool identity, and session | prompt/context adapter routes |
| Objective receipts | Produce one receipt per session with events, evidence index, gaps, and scope analysis | receipt builder and event store |
| Approval mediation | Create and resolve evidence-scoped approval items with append-only history | approval queue routes |
| Timeline hydration | Render ordered session entries from prompt, command/tool action, diff, correlation, and approval records | timeline provider |

### Tier 1 Exclusions

Tier 1 does not require:

- complete parent-child process ancestry unless collected and tested;
- global shell capture outside owned wrappers;
- deep packet inspection;
- route enforcement outside owned execution paths;
- verified rollback execution;
- remote model-state visibility;
- vendor-cloud evidence storage;
- broad compliance claims;
- all third-party agent integrations.

Those may become later layers, but Tier 1 succeeds only when the local spine is
observable and receipt-backed.

## Operational Problem Solved

Delegated execution has changed the operational shape of software work. A single
objective can now move through a human operator, an agentic coding tool, an IDE,
a shell command, a package manager, a local server, a background watcher, a CI
pipeline, a cloud API, and a runtime service. Each surface may keep its own log,
but no single surface owns the whole story.

That fragmentation creates practical failures:

- a prompt can say one boundary while a command touches another;
- an agentic tool can produce a pull request while local services mutate state;
- a shell process can open a port or call a cloud API outside the visible code
  diff;
- a background service can modify files while the operator is focused on a
  different task;
- an approval can apply to a merge or deploy while the underlying local mutation
  path remains unreviewed;
- rollback can be discussed as if it exists while no verifiable recovery evidence
  is present.

CleanHouse solves this by making runtime mutation accountability the central
unit. The question is not "did the actor sound compliant?" The question is:

- What objective was active?
- What action boundary was observed?
- What mutation happened?
- What evidence ref supports it?
- Was it inside the declared scope?
- What link is observed, inferred, or unknown?
- What receipt records the session?
- What approval or recovery state applies?

This problem exists across humans, agents, automation pipelines, shell processes,
background services, and cloud/runtime ecosystems because all of them can move
state. The shared operational need is not a better story after the fact. It is a
local, interpretable record of state movement as evidence.

## Why Interpretable Execution Lineage Matters

Interpretable execution lineage is the difference between a log pile and an
accountable session.

A log pile says:

```text
process ran
file changed
network connection opened
approval requested
receipt created
```

An interpretable lineage says:

```text
objective O was declared
prompt P opened session S
tool event T ran command C
command C produced process P1
process P1 touched file F
file F changed outside declared scope
approval A was requested with evidence refs E1..En
receipt R preserved the observed, inferred, and unknown segments
```

That structure lets the operator distinguish:

- action from mutation;
- mutation from explanation;
- observed fact from inferred link;
- missing evidence from successful completion;
- approval record from enforcement;
- rollback request from rollback proof.

Without interpretable lineage, a delegated system can produce plausible status
messages while the operator has no grounded way to compare the task boundary with
runtime reality. With interpretable lineage, every claim has a path back to local
evidence or a visible unknown.

## Why Universal Runtime Mutation Accountability Matters

Universal runtime mutation accountability means CleanHouse treats every local
state-moving surface as relevant:

- files;
- processes;
- shell commands;
- tool events;
- local ports;
- network connections;
- prompt/context boundaries;
- approval decisions;
- background service events;
- receipt and replay artifacts.

The point is not that Tier 1 already observes every possible surface. The point
is that the product contract must require every surface to be one of three
states:

- observed;
- explicitly out of scope for this tier;
- unknown because a collector or route is missing.

This is how CleanHouse avoids confidence theater. It does not hide unsupported
surfaces behind positive wording. It shows which runtime surfaces were observed,
which were not, and what that means for the receipt.

## Cloud And Runtime Ecosystem Fit

CleanHouse is local-first, but it must still account for cloud and runtime
ecosystems because local delegated work often crosses those boundaries. The
right boundary is evidence, not ownership.

CleanHouse can locally observe:

- a shell command that invokes a cloud CLI;
- a process that opens an outbound connection;
- a tool event that records a cloud operation;
- a file change that updates deployment configuration;
- a prompt/context record that declares cloud-impacting work;
- an approval item that marks a cloud-impacting action for review.

CleanHouse cannot claim full visibility inside the remote system unless the
remote system supplies evidence. For cloud/runtime ecosystems, the correct
CleanHouse behavior is therefore:

```text
local action observed
remote target or API endpoint observed when available
remote result recorded only when evidence is returned
missing remote state marked unknown
receipt preserves the boundary
```

This keeps operator sovereignty intact. The operator owns the local evidence and
can export it deliberately, while remote claims remain bounded by what the local
runtime and explicit integrations actually prove.

## Product Definition

CleanHouse is a local-first runtime accountability and coordination system that
records objective-scoped delegated execution, observes local action and mutation
surfaces, hydrates interpretable timelines, mediates evidence-scoped approvals,
and emits replayable receipts that separate observed facts, inferred links, and
unknown gaps.

It is not merely:

- a process monitor;
- a file integrity checker;
- a dashboard;
- a launcher;
- a policy engine;
- a coding agent;
- a forensic log archive;
- a hosted observability tool.

Those categories supply useful mechanisms, but CleanHouse's fulfilled behavior
is the accountable execution chain:

```text
objective
-> observed action boundary
-> observed runtime mutation
-> interpreted lineage edge
-> timeline entry
-> receipt
-> approval or recovery state
-> replay evidence
```

## Non-Negotiable Constraints

CleanHouse must remain constrained by these rules:

1. Runtime evidence outranks user-facing tone.
2. Evidence refs outrank confidence scores.
3. Prompt/context is a boundary artifact, not proof of purpose.
4. Pattern matches are pattern matches, not identity claims.
5. Missing collectors produce unknowns, not success labels.
6. Receipts must include gaps.
7. Approval mediation must not imply route enforcement unless CleanHouse owns the
   route.
8. Rollback must not be claimed without tested recovery evidence.
9. Infrastructure must not be reported as fulfilled product behavior.
10. Every capability claim must trace to local code, local evidence, or an
    explicitly labeled future requirement.

## Final Operating Standard

CleanHouse is ready to claim Tier 1 product behavior only when a local session can
prove this chain:

```text
objective recorded
prompt/context recorded
process or command/tool action observed
file integrity or diff evidence observed
timeline hydrated
receipt generated
approval item created/resolved when review is required
unknowns preserved
replay verifies the receipt state
```

Until that chain passes end to end, CleanHouse should be described as having
runtime accountability infrastructure, not a complete runtime accountability
product.

The rigorous conclusion is therefore narrow and durable: CleanHouse matters
because delegated execution now moves local and remote state through many
semi-independent actors and tools, while existing products leave the operator to
reconstruct the chain after the fact. CleanHouse's product is the chain itself:
local objective, observed action, observed mutation, evidence-backed timeline,
receipt, approval state, and replay. Anything less is substrate. Anything more
must be earned by runtime proof.
