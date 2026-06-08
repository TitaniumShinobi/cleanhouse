# CleanHouse Daily-Use Completion Conclusion

Date: 2026-05-25

Doctrine: "Runtime truth outranks tone. Evidence outranks confidence."

## Grounded Conclusion

CleanHouse should be completed as a reliable professional-grade runtime
accountability platform, not as another status dashboard or scanner. The finished
product must launch instantly, stay alive continuously in the background, observe
the operating environment as broadly as the host platform allows, and give the
operator a trustworthy live view of what the machine is doing.

The product is complete only when a user can open CleanHouse at any moment and
see evidence-backed answers to these questions:

- what files changed;
- what processes ran;
- what ports opened or closed;
- what network activity appeared;
- what shell or tool activity moved state;
- what agent, automation, app, cloud service, or background process was involved;
- what approval or notification state applied;
- what receipt records the mutation;
- what lineage links are observed, inferred, or unknown;
- what recovery or rollback evidence exists.

The current stabilized substrate is valuable, but it is still substrate. Flask
routes, a local dashboard, a pywebview wrapper, event persistence, receipt
schemas, approval records, collector adapters, launch scripts, and replay
helpers are necessary foundations. They are not the daily-use product until they
work together continuously as an always-on runtime evidence loop:

```text
instant launch
-> persistent background runtime
-> universal mutation observation where technically available
-> normalized event stream
-> live lineage hydration
-> deterministic receipts
-> real-time notification and approval mediation
-> replayable operational view
-> verified rollback or explicit no-rollback state
```

CleanHouse should therefore be described today as a stabilized runtime
accountability foundation moving toward a daily-use product. The remaining work
is not cosmetic. It is the engineering required to make runtime truth available
continuously, locally, and intelligibly.

## Completion Standard

The dependable daily-use product standard is:

```text
CleanHouse starts fast enough to feel native.
CleanHouse stays running without manual babysitting.
CleanHouse observes all supported mutation surfaces.
CleanHouse marks unsupported or failed collectors as gaps.
CleanHouse correlates mutations into interpretable execution lineage.
CleanHouse produces deterministic receipts for runtime changes.
CleanHouse notifies the operator only when action or awareness matters.
CleanHouse asks for approval when the route is owned or review is required.
CleanHouse preserves local evidence and operator control.
CleanHouse can be opened at any time to understand live machine state.
```

Anything less is not failure, but it must be labeled correctly. A launchable app
is not a 24/7 accountability platform. A watcher count is not universal mutation
visibility. A receipt schema is not a receipt-backed operational workflow. A
notification is not meaningful unless it points to evidence, lineage, approval,
or recovery.

## Current Product Boundary

CleanHouse can credibly claim a runtime-accountability direction when it anchors
claims to existing evidence surfaces:

- objective and prompt/context records;
- approval queue records and append-only approval history;
- receipt and replay structures;
- file event, snapshot, diff, and integrity evidence;
- process inventory and deterministic pattern matching;
- network and port snapshot evidence;
- command/tool-event boundaries when activity is routed through owned adapters;
- local dashboard and launcher substrate.

CleanHouse should not yet claim complete daily-use coverage until the end-to-end
loop is proven under continuous operation. The strict boundary remains:

- observed facts are reported as observed;
- correlations are labeled as inferred unless causality is proven;
- unsupported surfaces are labeled unsupported;
- collector failures are visible;
- rollback is not claimed without verified recovery evidence;
- route enforcement is not claimed unless CleanHouse owns the route.

## Remaining Engineering Priorities

### 1. Instant, Canonical Launch

CleanHouse needs one canonical launch path that starts quickly, reports readiness
clearly, and fails with actionable errors. The launcher must avoid duplicate
servers, stale ports, hidden background failures, and ambiguous "started" states.

Required outcome:

- one supported desktop/local launch command;
- bounded readiness checks;
- clear failure output;
- visible runtime URL or window state;
- no fallback into placebo mode;
- startup smoke proof through `/cleanhouse/status` and the dashboard route.

### 2. 24/7 Background Runtime

Daily use requires CleanHouse to run like a local utility, not a temporary dev
server. It needs a supervised background process that survives normal operator
workflows, reconnects cleanly, and exposes health without noise.

Required outcome:

- macOS LaunchAgent, Windows service/task, and Linux user service strategy;
- process supervision and restart policy;
- local log rotation;
- graceful shutdown and update handoff;
- collector heartbeat;
- visible degraded state when any runtime component fails.

### 3. Universal Mutation Visibility

CleanHouse must expand from watched-path and adapter-based visibility toward
whole-environment mutation accounting. Universal visibility means every
filesystem, process, port, and network surface is either covered, explicitly
unsupported, permission-blocked, or unknown. It does not mean omniscience.

Required outcome:

- OS-native filesystem coverage for broad watched roots;
- process start, stop, parent, command, user, and binary evidence;
- port open/close evidence with owning process where available;
- network connection evidence with process, PID, endpoint, protocol, and time;
- sync-provider and background-service attribution where exposed;
- collector coverage matrix visible in the UI;
- no silent blind spots.

### 4. Normalized Event Spine

The product needs one normalized runtime event model across collectors and
adapters. Without that spine, the dashboard remains a collection of panels
rather than an accountability system.

Required outcome:

- stable event IDs;
- evidence refs;
- session/objective IDs;
- actor, authority, action, target, mutation type;
- observed/inferred/unknown evidence level;
- correlation basis;
- collector health;
- receipt inclusion state;
- raw-source references where retained.

### 5. Interpretable Execution Lineage

CleanHouse must turn event streams into lineage the operator can understand.
The operator should not have to infer causality from timestamps and raw logs.

Required outcome:

- objective-to-action-to-mutation graph;
- process ancestry where available;
- command/tool-to-file correlation;
- process-to-network correlation;
- cloud/tool/agent context when imported;
- explicit inferred and unknown edges;
- timeline hydration that explains why each item appears.

### 6. Deterministic Receipts

Receipts are the proof artifact. Every meaningful runtime mutation should be
eligible for inclusion in a deterministic receipt with evidence refs and gaps.

Required outcome:

- content-addressed evidence index;
- hash-linked timeline;
- receipt root hash;
- approval history hash;
- gap and collector-health section;
- replay command or API;
- tamper-detection test;
- exportable receipt bundle.

### 7. Desktop Notifications And Approval Prompts

CleanHouse needs meaningful operator interrupts, not noisy alerts. Notifications
should appear only when the operator needs awareness, approval, or review.

Required outcome:

- native desktop notification path;
- severity and quiet-hours policy;
- notification links to evidence and lineage;
- approval prompts tied to evidence refs;
- "approve", "reject", "snooze", and "open receipt" actions where supported;
- no generic "protected" or "all good" language without evidence.

### 8. Always-On Operational View

The dashboard must become a live operations surface. It should answer "what is
my machine doing right now?" with evidence-backed state, not decorative cards.

Required outcome:

- runtime health summary;
- active collectors and gaps;
- recent mutations;
- active processes of interest;
- open ports and recent network activity;
- pending approvals;
- recent receipts;
- lineage timeline;
- rollback/recovery state;
- clear stale-data and disconnected states.

### 9. Cloud, Agent, SaaS, And Automation Adapters

CleanHouse cannot fully understand cloud services, SaaS products, agents, or
automation systems without explicit integrations. Local observation can show
commands, connections, files, and processes; remote state requires provider
evidence.

Required outcome:

- adapter contract for imported provider events;
- GitHub/CI workflow evidence;
- cloud audit event imports;
- AI tool and agent event imports;
- SaaS subscription/app activity imports where available;
- strict labels for local observed, provider observed, inferred, and unknown.

### 10. Rollback Orchestration

Rollback must become evidence-backed recovery, not a promise. CleanHouse should
identify what changed, whether previous state exists, and whether recovery can
be verified.

Required outcome:

- mutation-to-recovery mapping;
- snapshot or prior-state evidence;
- inverse-action plan when safe;
- approval requirement for recovery;
- verification after recovery;
- rollback state: available, partial, unavailable, or unknown.

### 11. Security, Privacy, And Operator Sovereignty

CleanHouse is only trustworthy if the operator owns the evidence boundary.
Always-on monitoring must be transparent, inspectable, and controllable.

Required outcome:

- local-first evidence storage;
- clear retention controls;
- redaction controls;
- encrypted sensitive evidence at rest;
- export without vendor lock-in;
- tenant policy without hiding local truth;
- explicit permission prompts for elevated collection;
- no cloud claim replacing local evidence.

### 12. Continuous Verification

CleanHouse needs acceptance gates that run repeatedly, not one-time demos.

Required outcome:

- launch readiness test;
- 24/7 supervisor test;
- filesystem create/modify/delete test;
- process lineage test;
- port and network test;
- command/tool adapter test;
- notification and approval test;
- receipt replay and tamper test;
- collector failure/gap test;
- dashboard stale-state test.

## Daily-Use Product Acceptance Gate

CleanHouse is ready for daily professional use only when this scenario passes:

```text
1. The user logs in or starts the machine.
2. CleanHouse starts automatically and reports readiness.
3. The user opens the dashboard and sees live collector health.
4. A file changes anywhere in a covered root.
5. A process starts, opens a port, and makes a network connection.
6. A tool or agent performs a delegated action.
7. CleanHouse records events, lineage, and evidence levels.
8. A meaningful notification appears if the action crosses policy.
9. The operator approves, rejects, or reviews the action with evidence refs.
10. CleanHouse emits a deterministic receipt.
11. Replay reconstructs the receipt state.
12. Unsupported or failed coverage is visible as a gap.
```

If any step fails, the product should not hide it. The correct daily-use
behavior is to show the failure as part of the runtime truth.

## Final Conclusion

The path to completing CleanHouse is clear: finish the continuous evidence loop.

CleanHouse does not become professional-grade because it has a launcher, a
dashboard, routes, or schemas. It becomes professional-grade when those pieces
operate continuously as one accountable system that observes runtime activity,
correlates mutations into lineage, asks for review when action matters, records
deterministic receipts, preserves replay, and tells the operator what is known,
what is inferred, and what is unknown.

The dependable product people can trust is an always-on operational view of the
machine: files, processes, ports, network activity, agents, applications,
automations, cloud-connected actions, and background services made visible
through evidence instead of tone.

That is the completion bar.

Runtime truth outranks tone. Evidence outranks confidence.
