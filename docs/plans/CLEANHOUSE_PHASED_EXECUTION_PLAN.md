# CleanHouse Phased Execution Plan

Date: 2026-05-25

Doctrine: Runtime truth outranks tone. Evidence outranks confidence.

## Canonical Inputs

This plan treats the following local documents as the controlling references:

- `../evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
- `../evidence/CLEANHOUSE_RUNTIME_ACCOUNTABILITY_RESEARCH.md`
- `../evidence/CLEANHOUSE_EVIDENCE_FIRST_CONCLUSION.md`
- `../evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md`
- current source and runtime checks in this checkout

The stabilized product spine is:

```text
objective -> actions -> mutations -> receipts -> approval/rollback
```

The current implementation is a stabilized runtime substrate with one narrow
tested receipt lane:

```text
prompt/context -> tool event -> snapshot diff -> timeline -> receipt -> approval -> replay bundle
```

The target is a mature local-first runtime accountability and coordination
platform for delegated execution environments. It must account for humans,
agents, automation systems, shell processes, background services, and
cloud/runtime ecosystems by recording observed runtime facts, labeling inferred
links, and preserving unknown gaps.

## Non-Negotiable Evaluation Rules

1. A capability is not complete because a route, class, dashboard element, table,
   launcher, script, or schema exists.
2. A capability is complete only when a fresh runtime session produces durable
   evidence that flows through the product spine.
3. Every phase must emit receipt-visible evidence for collector success,
   collector failure, skipped surfaces, unsupported routes, and unknown links.
4. Every claim in a receipt must carry an evidence level: observed, inferred, or
   unknown.
5. Approval mediation must be described as review state unless CleanHouse owns
   the execution route.
6. Rollback must be described as recovery state unless CleanHouse proves the
   prior state, recovery action, result, and verification evidence.
7. Operator trust is earned through replayable local evidence, not tone,
   confidence, naming, or UI presence.

## Current Boundary

### Substrate Already Present

- objective start and end routes;
- prompt/context ingestion;
- operator session records;
- command observer for owned subprocess execution;
- tool event records;
- snapshot and diff generation;
- file integrity baseline and scan code;
- optional filesystem watcher code;
- process inventory;
- network snapshot collector;
- approval queue and history records;
- timeline, receipt, replay, and bundle structures;
- dashboard and local launcher infrastructure.

### Fulfilled Product Behavior Already Proven

- owned prompt/context to tool event correlation in fixture tests;
- snapshot/diff mutation evidence in controlled fixture paths;
- receipt generation with evidence refs, gaps, scope analysis, and hashes;
- approval create and resolve history in the controlled receipt lane;
- deterministic replay bundle export/import verification for the avatar fixture.

### Not Yet Fulfilled

- universal filesystem mutation accountability;
- objective ID binding for every mutation source;
- PID/PPID process lineage;
- universal shell visibility outside owned wrappers;
- port/network open and close deltas;
- background service action correlation;
- receipt-visible gaps for every missing collector;
- initialized file integrity baseline in the active environment;
- approval policy over objective scope and mutation surfaces;
- verified rollback orchestration;
- operator timeline hydration proof without browser automation;
- cloud/runtime ecosystem correlation beyond local returned evidence.

## Phase 0: Evidence Contract Lock

Goal: define one canonical event contract that every collector, route, receipt,
and replay artifact must use.

Substrate Used:

- current event persistence;
- monitoring record dataclasses;
- receipt and replay builders;
- existing prompt, command, tool event, diff, process, network, approval, and
  integrity paths.

Fulfilled Product Behavior:

- every runtime fact that appears in a timeline or receipt uses the same minimum
  evidence envelope;
- every missing collector or missing link has a first-class event or gap record.

Engineering Milestones:

1. Define a canonical `CleanHouseEvidenceEvent` schema with:
   `event_id`, `session_id`, `objective_id`, `source_surface`, `actor_type`,
   `event_type`, `timestamp`, `evidence_level`, `observed_vs_expected`,
   `evidence_refs`, `collector_status`, `raw_evidence_ref`, and
   `scope_relation`.
2. Write adapters from each current substrate source into that schema.
3. Make receipts reject or mark incomplete any timeline entry that lacks the
   canonical fields.
4. Add collector health events for filesystem watcher, integrity, process,
   shell, port/network, prompt/context, approval, receipt, and replay surfaces.

Runtime Verification Gate:

- run a fresh session that emits one event from every existing source surface;
- export the receipt;
- verify every event has the canonical fields;
- verify missing `objective_id`, missing collector status, and unknown
  correlation appear as receipt-visible gaps;
- verify replay preserves the same event IDs and evidence refs.

Completion Inflation Control:

- schema definition alone is substrate;
- completion requires a receipt generated from live adapter output, not only
  unit-level object construction.

## Phase 1: Collector Readiness Baseline

Goal: make CleanHouse state exactly which collectors are operational,
permission-limited, uninitialized, or unsupported in the current environment.

Substrate Used:

- `corefiles/collectors/process_monitor.py`;
- file integrity baseline code;
- optional filesystem watcher imports;
- network snapshot collector;
- event writer metrics;
- receipt gap model.

Fulfilled Product Behavior:

- every session receipt states which runtime surfaces were actually watched and
  which surfaces were not available.

Engineering Milestones:

1. Add a collector readiness manifest per session.
2. Add readiness probes for filesystem watcher availability, integrity baseline
   status, process collector access, network collector access, command observer
   routing, approval queue availability, receipt storage, and replay export.
3. Feed readiness failures into timeline and receipt gaps.
4. Normalize permission errors, missing dependencies, missing baselines, empty
   collectors, and skipped collectors into stable evidence records.
5. Fix event writer resource hygiene so dropped events and unclosed database
   handles are visible and testable.

Runtime Verification Gate:

- run in the current local environment;
- receipt must report filesystem watcher state, integrity baseline state,
  process collector state, network collector state, command observer state, and
  event writer metrics;
- when `watchdog` is absent, the receipt must say filesystem watcher
  unavailable;
- when no integrity baseline exists, the receipt must say integrity baseline
  missing;
- when process access is permission-limited, the receipt must say process
  collector permission-limited.

Completion Inflation Control:

- a successful app launch or route response is not readiness;
- readiness is proven only by a receipt with collector statuses and gaps.

## Phase 2: Objective Envelope And Session Root

Goal: make the objective the required root of every accountable session.

Substrate Used:

- objective start and end routes;
- prompt/context records;
- operator session records;
- timeline and receipt builders.

Fulfilled Product Behavior:

- no action, mutation, approval, receipt, or replay artifact is treated as
  objective-scoped unless it carries an objective relation.

Engineering Milestones:

1. Define a canonical objective envelope with objective ID, session ID, summary,
   allowed paths, excluded paths, repo/runtime surface, expected output,
   operator identity if available, route ownership, and start/end timestamps.
2. Require objective relation on every adapter output:
   active objective, different objective, outside objective, or unknown.
3. Add objectiveless mutation handling that creates a visible unknown relation
   instead of silently attaching the mutation to a default session.
4. Make objective boundaries durable in receipt and replay manifests.

Runtime Verification Gate:

- start an objective with one allowed path and one excluded path;
- emit one prompt, one owned command, one in-scope file mutation, one
  out-of-scope file mutation, one process observation, one network observation,
  and one approval record;
- receipt must show objective relation for each item;
- objectiveless events must appear as unknown rather than defaulting to the
  active objective.

Completion Inflation Control:

- storing objective IDs on prompt records is not enough;
- completion requires objective relation across every mutation source.

## Phase 3: Universal Filesystem Mutation Accountability

Goal: account for file creation, modification, deletion, hash drift, and
snapshot deltas across the watched workspace.

Substrate Used:

- snapshot and diff routes;
- file integrity baseline and scan code;
- optional watcher path;
- scope analysis;
- receipt evidence index.

Fulfilled Product Behavior:

- every local file mutation is either observed by at least one file evidence
  source or reported as an evidence gap for that session.

Engineering Milestones:

1. Initialize fixture and workspace integrity baselines.
2. Normalize snapshot diff, watcher events, and integrity deltas into one file
   mutation model.
3. Preserve source-specific raw evidence refs for each file mutation.
4. Record create, modify, delete, rename when available, before hash, after
   hash, size, mtime, collector source, scope relation, and objective relation.
5. Add workspace watch boundaries and exclusion rules to the objective envelope.
6. Add tests for mutations caused by owned command, direct shell command,
   background service, and external editor path where available.

Runtime Verification Gate:

- create, modify, and delete files inside a fixture workspace during an active
  objective;
- perform one out-of-scope file mutation;
- receipt must include snapshot diff evidence and either watcher or integrity
  evidence for each file mutation;
- missing watcher or missing integrity evidence must appear as a collector gap;
- scope analysis must classify each mutation.

Completion Inflation Control:

- watcher code, integrity code, or snapshot code alone is substrate;
- completion requires a receipt showing file mutations from at least two
  evidence sources or explicit gaps for the missing sources.

## Phase 4: Process Lineage And Shell Activity

Goal: evolve from process inventory into objective-scoped process lineage and
owned shell activity records.

Substrate Used:

- process inventory collector;
- command observer;
- tool event ingestion;
- network process mapping;
- timeline and receipt builders.

Fulfilled Product Behavior:

- a command or process claim includes PID, PPID, command, args, user, start
  time, capture time, parent/child relation, objective relation, and evidence
  level when available.

Engineering Milestones:

1. Replace or extend `ps aux` parsing with a collector that captures PID, PPID,
   user, start time, command, and args.
2. Model process start, observed-running, and exit state when observable.
3. Correlate owned command observer records to process records.
4. Represent parent/child edges as observed when PPID is captured and unknown
   when not captured.
5. Add shell activity gap records for commands not routed through owned wrappers.
6. Record exact deterministic pattern matches without promoting them to actor
   identity proof.

Runtime Verification Gate:

- route a command through the command observer that starts a child process;
- receipt must include parent PID, child PID, PPID edge, command args, cwd, user
  if available, timestamps, and evidence refs;
- run a direct shell command outside the owned wrapper;
- receipt must show either observed collector evidence or an unsupported-shell
  gap without claiming full shell coverage.

Completion Inflation Control:

- process lists and substring matches are not lineage;
- completion requires parent/child evidence and explicit unknown edges.

## Phase 5: Port/Network Delta Timeline

Goal: convert network snapshots into objective-scoped port and connection
mutation evidence.

Substrate Used:

- `lsof`-based network snapshot collector;
- data flow tracer process mapping;
- process lineage model;
- timeline and receipt builders.

Fulfilled Product Behavior:

- port and network state changes appear as opened, still open, closed, or
  unknown, with process and objective relation where available.

Engineering Milestones:

1. Add delta computation between network snapshots.
2. Capture local port, remote host/domain when available, protocol, PID,
   process name, command, open timestamp, close timestamp, and collector status.
3. Link network deltas to process lineage when PID is known.
4. Add objective relation using active objective windows.
5. Preserve unknown relation when a connection cannot be tied to a process or
   objective.

Runtime Verification Gate:

- start a local server during an active objective;
- capture port open and close deltas;
- receipt must include PID, process name, local port, timestamps, objective
  relation, and evidence refs;
- if close is not observed, receipt must say still open or unknown.

Completion Inflation Control:

- a single network snapshot is not a port timeline;
- completion requires open/close delta evidence or explicit unknown state.

## Phase 6: Objective-Scoped Execution Lineage Graph

Goal: make the product spine queryable as an interpretable graph.

Substrate Used:

- canonical evidence event schema;
- objective envelope;
- file mutation model;
- process lineage model;
- port/network delta model;
- prompt/context records;
- tool event records;
- approval and receipt records.

Fulfilled Product Behavior:

- CleanHouse can explain a session as a graph from objective to actions to
  mutations to receipts to approval/rollback state, with observed, inferred, and
  unknown edges.

Engineering Milestones:

1. Define lineage node types:
   objective, prompt/context, tool event, command, process, file mutation,
   network delta, background service event, approval item, rollback request,
   receipt, replay bundle, and evidence gap.
2. Define edge types:
   caused_by_observed, correlated_by_time, correlated_by_scope,
   emitted_by_collector, reviewed_by_approval, captured_in_receipt,
   verified_by_replay, and unknown.
3. Add graph export to receipt bundle.
4. Add query paths for "what changed," "why was this flagged," "what evidence
   exists," "what is inferred," and "what is unknown."
5. Ensure every graph edge carries evidence refs or gap refs.

Runtime Verification Gate:

- run a session containing prompt, owned command, process child, file mutation,
  port delta, approval, receipt, and replay;
- export graph;
- verify every node is reachable from the objective or explicitly marked
  objective-unknown;
- verify every edge has evidence level and evidence refs or gap refs.

Completion Inflation Control:

- timeline ordering is not lineage;
- completion requires typed nodes, typed edges, and evidence-labeled links.

## Phase 7: Prompt/Context Ingestion And Delegated Execution Adapters

Goal: normalize delegation context across humans, agents, automation systems,
shell wrappers, background services, and cloud/runtime connectors.

Substrate Used:

- prompt/context route;
- tool event route;
- command observer;
- plugin metadata records;
- process and file collectors;
- operator session records.

Fulfilled Product Behavior:

- CleanHouse preserves the request boundary and delegation context without
  treating prompt text as proof of intent.

Engineering Milestones:

1. Define prompt/context record fields for source tool, human operator, task ID,
   objective ID, repo/runtime surface, allowed paths, excluded paths, expected
   output, prompt hash, context hash, and raw evidence ref.
2. Add adapter contracts for local agents, shell wrappers, automation jobs,
   background services, and cloud/runtime connectors.
3. Require adapters to emit action records with objective relation and evidence
   refs.
4. Add contextual correlation rules that label prompt-to-action links as
   observed when the adapter provides the link, inferred when time/scope
   correlation is used, and unknown when the relation is absent.
5. Add capability registry input as evidence metadata, not as a substitute for
   observed behavior.

Runtime Verification Gate:

- submit the same objective through human-entered context, owned shell wrapper,
  tool event adapter, and one automation job fixture;
- receipt must show source identity, prompt/context hash, action records,
  mutation records, and observed/inferred/unknown correlation states;
- prompt text alone must not satisfy mutation attribution.

Completion Inflation Control:

- collecting prompts is not contextual prompt correlation;
- completion requires prompt/context records linked to runtime actions and
  mutations with evidence-labeled edges.

## Phase 8: Approval Mediation And Runtime Governance

Goal: turn approval from optional metadata into deterministic evidence-scoped
review behavior.

Substrate Used:

- approval queue records;
- approval history;
- scope analysis;
- evidence refs;
- objective envelope;
- lineage graph.

Fulfilled Product Behavior:

- review-required runtime events create approval items with precise evidence
  refs, policy reason, objective relation, and replayable resolution history.

Engineering Milestones:

1. Define approval policy over scope relation, mutation type, evidence level,
   collector status, route ownership, and operator preference.
2. Add policy outcomes:
   no review required, review requested, review resolved approved, review
   resolved rejected, route-owned hold available, and route-owned hold absent.
3. Create approval items for out-of-scope file mutations, route-owned risky
   commands, unsupported collector gaps selected by policy, and rollback
   requests.
4. Keep approval mediation separate from execution control unless CleanHouse
   owns the route.
5. Preserve policy version and evaluation evidence in receipts.

Runtime Verification Gate:

- perform an in-scope file mutation and an out-of-scope file mutation;
- receipt must create approval for the out-of-scope mutation only under the
  configured policy;
- resolve approval;
- replay must show creation, reviewer, resolution, evidence refs, policy
  version, and final state;
- if CleanHouse did not own the action route, receipt must say review state only.

Completion Inflation Control:

- approval records are not mediation by themselves;
- completion requires deterministic policy evaluation and replayable approval
  history tied to evidence refs.

## Phase 9: Rollback Orchestration And Recovery Evidence

Goal: make rollback a receipt-backed recovery lane with verified evidence.

Substrate Used:

- snapshot and diff records;
- integrity hashes;
- approval queue;
- receipt and replay bundles;
- future owned recovery executor.

Fulfilled Product Behavior:

- CleanHouse can state whether rollback was not requested, requested without
  recovery route, requested with recovery route, executed with verified result,
  or executed with failed verification.

Engineering Milestones:

1. Define rollback request and rollback result record schemas.
2. Preserve before state with hash, size, mtime, and source evidence ref.
3. Require approval state before executing owned recovery actions selected by
   policy.
4. Implement fixture workspace file recovery from known previous state.
5. Verify recovery by comparing post-recovery hash and scope state.
6. Record recovery gaps when previous state, route ownership, permissions, or
   verification evidence are missing.

Runtime Verification Gate:

- modify a fixture file under an active objective;
- request rollback;
- approve rollback;
- execute owned recovery;
- receipt must include before hash, changed hash, recovery action, after hash,
  approval state, verification result, and replay hash;
- run a second case with no previous state and verify receipt reports requested,
  no recovery route or missing previous state.

Completion Inflation Control:

- a rollback button, request record, or plan is not rollback;
- completion requires verified recovery evidence in the receipt.

## Phase 10: Deterministic Receipts And Replay Verification

Goal: make receipts complete, deterministic, importable, replayable, and honest
about gaps.

Substrate Used:

- current receipt builder;
- replay builder;
- bundle export/import;
- evidence hash chains;
- approval state;
- canonical event schema.

Fulfilled Product Behavior:

- the same evidence bundle replays to the same receipt root hash, timeline hash,
  replay hash, approval history, evidence count, and collector gap list.

Engineering Milestones:

1. Version receipt schema and bundle manifest.
2. Include collector readiness manifest in every receipt.
3. Include lineage graph export in every bundle.
4. Add deterministic ordering for events, gaps, approvals, and evidence refs.
5. Add replay verification that compares hashes, counts, schema versions,
   policy versions, and unsupported surface declarations.
6. Add corruption, missing evidence, and duplicate import tests.

Runtime Verification Gate:

- run a full Tier 1 fixture session;
- export bundle;
- import bundle twice;
- replay both imports;
- verify identical root hash, timeline hash, replay hash, approval history,
  evidence count, graph count, and collector gap count;
- mutate the bundle and verify replay reports integrity failure.

Completion Inflation Control:

- a JSON export is not a deterministic receipt;
- completion requires repeat import and replay equality under a stable manifest.

## Phase 11: Contextual Drift Analysis

Goal: explain scope drift from objective and runtime evidence without claiming
hidden intent.

Substrate Used:

- objective envelope;
- prompt/context hashes;
- scope analysis;
- lineage graph;
- approval policy;
- receipt gaps.

Fulfilled Product Behavior:

- CleanHouse can explain why an action or mutation appears in-scope,
  out-of-scope, context-adjacent, unexplained, unsupported, or unknown.

Engineering Milestones:

1. Define drift categories based on declared objective, allowed paths, excluded
   paths, action source, mutation type, evidence level, and collector status.
2. Add drift reason records to timeline, approval items, receipts, and replay.
3. Separate observed drift evidence from inferred correlation and unknown gaps.
4. Add capability-registry context as explanatory metadata only.
5. Add fixture cases for expected mutation, out-of-scope traversal, background
   service mutation, unsupported shell action, missing collector, and
   cloud/runtime returned evidence.

Runtime Verification Gate:

- run fixture sessions for each drift category;
- each receipt must include drift category, reason, evidence refs, scope
  relation, objective relation, approval state when required, and unknown gaps;
- no drift reason may rely on prompt text alone.

Completion Inflation Control:

- a label is not drift analysis;
- completion requires evidence-backed reason records and replay-preserved
  explanations.

## Phase 12: Operator Trust Workflows

Goal: make the human operator workflow usable without diluting evidence rules.

Substrate Used:

- dashboard;
- workstation aggregate route;
- objective declaration;
- prompt/context ingestion;
- receipt list;
- approval queue;
- replay and bundle export.

Fulfilled Product Behavior:

- the operator can declare work, inspect runtime changes, understand evidence
  strength, resolve approvals, and replay receipts from local data.

Engineering Milestones:

1. Present collector readiness and evidence gaps before action review.
2. Show objective, actions, mutations, approvals, receipt hash, replay hash, and
   unknowns in one session timeline.
3. Make approval review show exact policy reason and evidence refs.
4. Make rollback review show requested state, available previous state, route
   ownership, and verification state.
5. Add manual verification protocol that does not use browser automation.
6. Record operator verification receipt with exact session ID, objective ID,
   approval ID, receipt ID, and replay hash.

Runtime Verification Gate:

- a human-operated local run declares an objective, emits prompt/context,
  performs an owned command, mutates in-scope and out-of-scope files, opens and
  closes a local port, resolves approval, exports receipt, and replays the
  bundle;
- final verification record includes exact IDs and hashes;
- no browser automation is used.

Completion Inflation Control:

- dashboard presence is not operator trust;
- completion requires a human-operated receipt with inspectable evidence and
  replay verification.

## Phase 13: Background Service And Automation Coordination

Goal: account for state changes caused by long-running services, scheduled
tasks, watchers, build tools, and local automation systems.

Substrate Used:

- process lineage;
- file mutation model;
- port/network deltas;
- prompt/context and automation adapter contracts;
- lineage graph.

Fulfilled Product Behavior:

- background service and automation activity is either tied to an objective,
  tied to a known scheduled task, outside an objective, or unknown.

Engineering Milestones:

1. Define background service identity records using process command, PID/PPID,
   service label, cwd, start time, and collector evidence.
2. Add automation job adapter fields for job ID, trigger source, task name,
   workspace, command, exit status, objective relation, and evidence refs.
3. Record service-caused file and port/network mutations as observed when
   process linkage exists, inferred when time/scope correlation is used, and
   unknown when linkage is absent.
4. Add receipt sections for concurrent background services active during an
   objective.
5. Add fixture service that mutates a file and opens a port during an objective.

Runtime Verification Gate:

- start a fixture background service;
- declare an objective;
- have the service mutate a file and open a local port;
- receipt must show service process evidence, mutation evidence, port evidence,
  objective relation, and edge evidence level;
- if process-to-file attribution is unavailable, receipt must label the link
  inferred or unknown.

Completion Inflation Control:

- seeing a process name is not service coordination;
- completion requires state movement attributed to service evidence or marked
  unknown.

## Phase 14: Cloud/Runtime Ecosystem Connectors

Goal: integrate cloud and runtime ecosystems without giving up local-first
operator sovereignty.

Substrate Used:

- prompt/context ingestion;
- tool event adapters;
- command observer;
- receipt bundle manifest;
- approval policy;
- local evidence store.

Fulfilled Product Behavior:

- cloud/runtime activity is represented by local requests, returned evidence,
  local command output, local file mutations, local ports, and explicit unknown
  remote state.

Engineering Milestones:

1. Define connector evidence records for local CLI command, API request summary,
   returned status, returned artifact ID, local file output, approval state, and
   unknown remote segments.
2. Hash local request/response summaries and artifact manifests without treating
   remote internals as locally observed facts.
3. Add connector-specific approval policies for deploy, migration, job launch,
   credential use, and artifact import where routes are owned.
4. Preserve operator-owned local evidence store as the receipt authority.
5. Add replay bundle support for connector records and unknown remote gaps.

Runtime Verification Gate:

- run a fixture connector that simulates a cloud/runtime job with local command
  output and returned artifact metadata;
- receipt must show local command evidence, returned metadata, produced file
  mutations, approval state if policy requires it, and unknown remote internals;
- replay must preserve connector evidence without claiming remote state that was
  not returned locally.

Completion Inflation Control:

- a connector SDK call or returned success status is not ecosystem
  accountability;
- completion requires local evidence records, returned artifacts, and unknown
  remote boundaries in the receipt.

## Phase 15: Mature Platform Hardening

Goal: graduate from Tier 1 MVP to a mature local-first runtime accountability
platform.

Substrate Used:

- all prior phases;
- regression fixtures;
- replay verification;
- manual operator verification receipts;
- local retention and export controls.

Fulfilled Product Behavior:

- CleanHouse can account for delegated execution across local files, processes,
  shell routes, ports, prompts, approvals, rollback, services, automation, and
  cloud/runtime connectors with replayable local receipts.

Engineering Milestones:

1. Build a fresh-workspace acceptance harness that runs the full product spine.
2. Add regression gates for collector absence, permission limits, queue drops,
   unclosed resources, missing baselines, unsupported shell paths, and unknown
   remote state.
3. Add migration and schema compatibility tests for receipts and replay bundles.
4. Add local retention controls for receipts, raw evidence refs, and exported
   bundles.
5. Add operator-facing status that separates operational, partial,
   substrate-only, unsupported, and unknown states.
6. Require every release note and status claim to point to runtime receipts.

Runtime Verification Gate:

- run the full fresh-workspace acceptance harness;
- receipt must include objective, prompt/context, owned command, child process
  lineage, in-scope file mutation, out-of-scope file mutation, file integrity
  delta, watcher or explicit watcher gap, port open/close delta, background
  service activity, approval history, rollback request and result, receipt
  hashes, replay hashes, bundle export/import, collector readiness, and unknown
  boundaries;
- all expected hashes and counts must match on repeat replay;
- manual operator verification receipt must match the harness receipt at the
  same product spine level.

Completion Inflation Control:

- maturity cannot be claimed from tests alone, docs alone, or UI alone;
- maturity requires repeated fresh-workspace runtime receipts that prove the
  product spine and preserve all gaps.

## Tiered Release Gates

### Tier 1 MVP Gate

Tier 1 can be claimed only when the following chain passes in a fresh local
workspace:

1. declare objective with scope, exclusions, repo/runtime surface, and expected
   output;
2. ingest prompt/context for that objective;
3. route one owned command;
4. capture process PID/PPID lineage for a child process;
5. capture in-scope and out-of-scope file mutations;
6. capture file mutation evidence through snapshot diff and watcher or
   integrity delta;
7. capture local port open and close delta;
8. create approval for the out-of-scope mutation under deterministic policy;
9. build receipt with evidence refs, gaps, scope analysis, collector readiness,
   and hash chain;
10. replay receipt and verify hashes;
11. export, import, and replay bundle twice with identical results;
12. record every missing collector or unsupported route as a receipt gap.

Tier 1 does not require universal cloud/runtime connectors, broad automation
adapter coverage, or full rollback beyond the fixture recovery lane.

### Tier 2 Coordination Gate

Tier 2 can be claimed only when CleanHouse adds:

- background service evidence;
- automation job adapters;
- contextual drift reason records;
- operator review workflow proof;
- rollback request and recovery evidence for owned fixture routes;
- deterministic lineage graph export;
- receipt-visible unknown states for unowned shell and remote surfaces.

### Tier 3 Mature Platform Gate

Tier 3 can be claimed only when CleanHouse adds:

- repeatable fresh-workspace acceptance harness;
- cloud/runtime connector evidence records;
- local retention and export controls;
- schema migration compatibility;
- release claim receipts;
- manual operator verification receipts that match automated harness evidence.

## Capability Scoreboard

| Capability | Current status | Phase that fulfills it | Required proof |
|---|---|---|---|
| Evidence event contract | partial | Phase 0 | Canonical event from every source in one receipt |
| Collector readiness | partial | Phase 1 | Receipt-visible collector manifest and gaps |
| Objective root | partial | Phase 2 | Objective relation on every event or unknown |
| Universal filesystem accountability | missing as product behavior | Phase 3 | Create/modify/delete evidence plus gaps |
| Process lineage | missing | Phase 4 | PID/PPID parent-child receipt evidence |
| Shell activity | wrapper-only | Phase 4 | Owned command proof plus unsupported-shell gap |
| Port/network changes | snapshot-only | Phase 5 | Open/close delta timeline |
| Execution lineage | partial timeline | Phase 6 | Typed evidence graph with observed/inferred/unknown edges |
| Prompt/context correlation | partial | Phase 7 | Prompt-to-action-to-mutation links with evidence levels |
| Approval mediation | review-state operational | Phase 8 | Deterministic policy and replayable approval history |
| Rollback | not fulfilled | Phase 9 | Verified fixture recovery evidence |
| Deterministic receipts | strong narrow lane | Phase 10 | Repeat import/replay equality |
| Drift analysis | partial scope analysis | Phase 11 | Evidence-backed drift reasons |
| Operator trust workflow | partial | Phase 12 | Manual no-browser-automation verification receipt |
| Background services | substrate/process-only | Phase 13 | Service activity tied to mutations or unknown |
| Cloud/runtime ecosystems | mostly missing | Phase 14 | Local returned evidence plus unknown remote gaps |
| Mature platform | not yet | Phase 15 | Fresh-workspace acceptance receipt and release claim proof |

## Completion Claim Rules

Allowed status labels:

- `operational`: proved by fresh runtime receipt evidence;
- `partial`: one or more surfaces work, but the product spine is incomplete;
- `substrate-only`: infrastructure exists without end-to-end receipt proof;
- `unsupported`: no current collector, adapter, or owned route exists;
- `unknown`: CleanHouse cannot determine the relation from available evidence.

Disallowed claim patterns:

- route exists, therefore product exists;
- test passed, therefore universal coverage exists;
- UI renders, therefore operator trust exists;
- collector code exists, therefore collection occurred;
- prompt said scope, therefore mutation belonged to scope;
- approval item exists, therefore execution was mediated;
- rollback was requested, therefore recovery happened;
- remote status returned success, therefore remote execution lineage is known.

## Final Acceptance Definition

CleanHouse becomes a mature local-first runtime accountability and coordination
platform only when a fresh local run can produce this receipt-backed chain:

```text
objective
-> prompt/context
-> owned and observed actions
-> process lineage
-> filesystem mutations
-> port/network deltas
-> background service or automation activity
-> cloud/runtime returned evidence where applicable
-> lineage graph
-> approval policy and history
-> rollback request/result where applicable
-> deterministic receipt
-> replay verification
-> explicit gaps for every unobserved surface
```

Until that chain is observable, imported, replayed, and manually inspected from
local evidence, CleanHouse remains a runtime accountability substrate with
partial product behavior.

Runtime truth outranks tone. Evidence outranks confidence.
