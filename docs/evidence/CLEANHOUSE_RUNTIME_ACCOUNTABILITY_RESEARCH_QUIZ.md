# CleanHouse Runtime Accountability Research Quiz

Date: 2026-06-10

Source: `docs/evidence/CLEANHOUSE_RUNTIME_ACCOUNTABILITY_RESEARCH.md`

Purpose: turn the deep research into a practical comprehension and product
alignment quiz for CleanHouse. The quiz checks whether a reviewer understands
the product thesis, evidence model, market gaps, approval requirements, and
validation gates without collapsing CleanHouse into a generic observability,
security, or agent platform.

## How To Use

- Use Part 1 for fast comprehension.
- Use Part 2 for product judgment and implementation review.
- Use Part 3 for scenario-based blocker triage.
- Score against the answer key at the bottom.

Recommended passing bar: 21 of 25.

## Part 1: Core Thesis

### 1. Multiple Choice

What is the research's central claim about CleanHouse's defensible lane?

A. CleanHouse should become a full SIEM for all enterprise event streams.
B. CleanHouse should act as a local evidence fabric for accountable execution on
the operator's machine.
C. CleanHouse should replace coding agents with a safer built-in agent.
D. CleanHouse should focus on cloud-only deployment approvals.

### 2. Short Answer

In one sentence, explain why CleanHouse starts with an operator objective
instead of an HTTP request, endpoint alert, or pull request.

### 3. Multiple Choice

Which chain best represents the required CleanHouse root of truth?

A. file hash -> endpoint alert -> dashboard -> incident ticket
B. pull request -> CI logs -> reviewer approval -> merge
C. operator objective -> prompt or delegated request -> action boundary -> local
runtime mutation -> evidence reference -> approval state -> receipt -> replay
D. service metric -> trace span -> log line -> SLO burn rate

### 4. Short Answer

Why is prompt context treated as evidence but not as proof of intent?

### 5. Multiple Choice

Which statement best describes "operator sovereignty" in the research?

A. The operator delegates all monitoring to a hosted vendor by default.
B. The operator owns local evidence storage, approval rules, scope boundaries,
and final review state.
C. The operator only reviews final pull requests.
D. The operator can ignore unknown states if confidence is high enough.

## Part 2: Market Gaps And Product Boundaries

### 6. Multiple Choice

Distributed observability tools are useful to CleanHouse mainly because they
provide:

A. ticket lifecycle rules
B. span IDs, parent-child relationships, and context propagation concepts
C. local-first prompt receipts by default
D. workstation filesystem approval gates

### 7. Short Answer

What do file integrity tools often know that CleanHouse should adopt, and what
important context do they usually lack?

### 8. Multiple Choice

Why are process lineage sensors necessary but insufficient for CleanHouse?

A. They cannot observe any process metadata.
B. They produce process evidence, but not work lineage tied to objective,
prompt, approval, and receipt context.
C. They are only useful for frontend rendering.
D. They already provide complete CleanHouse receipts.

### 9. Short Answer

Name two ways agentic coding platforms fail the CleanHouse target.

### 10. Multiple Choice

Which product category gives CleanHouse the best grammar for replayable lineage
but does not itself solve workstation-scale delegated execution?

A. Provenance systems
B. Generic ticketing systems
C. Marketing analytics
D. Static style guides

### 11. Short Answer

Why should CleanHouse not be positioned as "another coding agent"?

### 12. Multiple Choice

What is the correct posture when CleanHouse does not own a route or collector?

A. Enforce anyway.
B. Infer success from nearby timestamps.
C. Record review state and expose the gap.
D. Hide the missing collector from the operator.

## Part 3: Evidence Model And Correlation Rules

### 13. Multiple Choice

Which field group belongs in the minimum CleanHouse evidence model?

A. event ID, session ID, objective ID, actor, source surface, operation, target,
evidence level, evidence refs, approval ID, receipt ID, gap reason
B. brand slogan, color palette, marketing segment, hero copy
C. only process ID and timestamp
D. only pull request title and merge status

### 14. Short Answer

Define "universal mutation accountability" in practical CleanHouse terms.

### 15. Multiple Choice

Which correlation rule creates a process-lineage edge?

A. session ID match
B. prompt ID to tool event
C. PID/PPID
D. receipt evidence index

### 16. Short Answer

Why must every edge expose its evidence level?

### 17. Multiple Choice

Which label set matches the research's evidence-level discipline?

A. true, false, maybe
B. green, yellow, red
C. observed, inferred, unknown
D. safe, risky, blocked

### 18. Short Answer

Give one example of a gap that must remain visible instead of being converted
into success language.

## Part 4: Approval, Incidents, And Validation

### 19. Multiple Choice

Which actions should trigger approval mediation?

A. boundary-expanding, destructive, privileged, credential-bearing, or
network-impacting actions
B. only documentation edits
C. only successful commands
D. only cloud deployments

### 20. Short Answer

What should an approval object answer later during replay?

### 21. Multiple Choice

What CleanHouse lesson comes from the reported Replit/SaaStr incident?

A. A code freeze is only a chat preference.
B. Destructive operations need runtime proof and approval gates tied to the
operation path.
C. Rollback evidence can be assumed if an agent says it exists.
D. Local evidence is unnecessary for database operations.

### 22. Short Answer

What CleanHouse lesson comes from the reported Cursor/Claude/Railway incident?

### 23. Multiple Choice

In Gate 1 of the validation plan, what should happen when one file inside scope
and one file outside scope are modified?

A. The receipt should include only the in-scope file.
B. The receipt should include objective, diff, in-scope count, out-of-scope
count, evidence refs, and scope classification.
C. The receipt should mark the session green because at least one file was
inside scope.
D. The receipt should omit scope classification.

### 24. Short Answer

What is the expected result of the collector failure validation gate?

### 25. Scenario

A coding agent is asked to update one file in `frontend/`, but a later receipt
shows a shell command, one modified frontend file, one modified backend file,
and an unknown network collector state. Write the CleanHouse-style finding in
two or three sentences. Include observed, inferred, and unknown states.

## Answer Key

1. B
2. Expected answer: CleanHouse starts with the operator objective because its job
is to prove whether delegated local work stayed inside the declared task across
prompts, tools, commands, files, processes, approvals, and receipts.
3. C
4. Expected answer: A prompt records the declared boundary or delegation context,
but runtime evidence is needed to prove what actually happened and whether the
work stayed inside scope.
5. B
6. B
7. Expected answer: They often know file creation, modification, deletion,
hashes, user, PID, process name, and parent process details; they usually lack
objective, prompt, delegated-action, approval, and receipt context.
8. B
9. Expected answer: Any two: logs stop at platform boundaries; they do not
account for all local filesystem, shell, service, port, or automation mutations;
prompt context is not normalized across tools; approvals are platform-specific;
cloud isolation can weaken local operator sovereignty.
10. A
11. Expected answer: CleanHouse is the accountability layer around agents and
other local actors, binding their actions into evidence, approvals, and receipts
rather than generating code itself.
12. C
13. A
14. Expected answer: Every local mutation surface is either observed, routed
through an owned adapter, or reported as an explicit gap.
15. C
16. Expected answer: Evidence level prevents time proximity, confidence, or UI
state from being mistaken for proof; each relationship must show whether it is
observed, inferred, or unknown.
17. C
18. Expected answer: Examples include missing collector data, missing parent PID,
missing command wrapper coverage, unsupported OS surfaces, or unobserved network
activity.
19. A
20. Expected answer: It should answer what action was requested, why review was
needed, what evidence supported it, who resolved it, and what replay shows
later.
21. B
22. Expected answer: Prompt context was insufficient; evidence should connect
credential discovery, shell or API command, network destination, destructive
action, approval state, and separately verifiable backup or recovery evidence.
23. B
24. Expected answer: The UI or API must report unknown or gap state, not a green
status.
25. Expected answer: The modified frontend file and shell command are observed
inside the declared objective. The backend modification is observed
out-of-scope, so CleanHouse should classify it as a scope deviation and require
review or approval evidence. The network collector state remains unknown and
must be shown as a gap, not inferred safe from the rest of the receipt.

## Source Anchors

- Core thesis: "Research Finding", "CleanHouse Positioning", "Strategic
  Conclusion"
- Market boundaries: "Landscape Analysis", "Gap Matrix", "Product Failure
  Pattern Across The Market"
- Evidence model: "Minimum Evidence Model", "Required Correlation Rules",
  "Operator Sovereignty Requirements"
- Approval and replay: "Approval Mediation Workflows", "Replayable Evidence And
  Provenance Systems", "CleanHouse Product Requirements"
- Incident lessons: "Delegated Execution Drift Incidents"
- Validation: "Validation Plan"
