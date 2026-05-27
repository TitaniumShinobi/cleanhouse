# CleanHouse Master Implementation Plan (Evidence-First, v1.0)

Last updated: 2026-05-22
Status: Draft-to-Execution

## Hard execution constraints
- Local-first execution only.
- Observe → correlate → explain → cite evidence.
- Evidence must be distinguished as `observed | inferred | unknown`.
- No claims about intent, maliciousness, or AGI-governance.
- No silent defaults, no hidden actions.
- No broad refactors during sequence.

## Evidence contract anchors
- Canonical doctrine documents:
  - `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
  - `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md`
- Audit baseline input:
  - `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_EVIDENCE_AUDIT.md`

## Execution model
All work is a chain of **self-contained implementation prompts**. Each prompt is isolated, deterministic, and gated by tests before the next prompt.

Template for each prompt:
- Goal
- Required files
- Dependencies
- Architectural constraints
- Acceptance tests
- Anti-overclaim checks
- Regression boundaries
- Completion criteria

## Phase A — Baseline hardening and scope lock

### Prompt A0 — Contract lock (mandatory)
Goal:
- Lock executable product scope for this run so implementation cannot drift into AGI governance or intent-judgment semantics.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_EVIDENCE_AUDIT.md`
Dependencies:
- none
Architectural constraints:
- No wording changes in code unless required by later prompts.
Acceptance tests:
- Manual review: each subsequent prompt references the term list in `docs/canon/CLEANHOUSE_RUBRIC.md` and does not introduce forbidden terms.
- Verify all prompts are tagged with explicit scope.
Anti-overclaim checks:
- Do not use wording: intent inference, AGI governance, motive, malicious actor framing, omniscient detection.
Regression boundaries:
- Preserve existing docs, keep user-facing feature claims unchanged until implementation evidence supports change.
Completion criteria:
- Scope lock note added to plan (done in this prompt) and used as gate text for future prompts.

### Prompt A1 — Baseline inventory freeze
Goal:
- Freeze and checksum runtime-facing modules to prevent accidental target drift.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/server.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/monitor.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/integrity.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/collectors/process_monitor.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/collectors/agent_movement_monitor.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/collectors/data_flow_tracer.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_cleanhouse_monitoring_api.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/desktop/wrapper.py`
Dependencies:
- existing audit and rubric files
Architectural constraints:
- Do not modify behavior yet; this is inventory only.
- Do not rename endpoints before their contracts are stabilized.
Acceptance tests:
- Run one command to generate a frozen file list (manual artifact for team handoff).
Regression boundaries:
- Existing endpoint names unchanged by this step.
Completion criteria:
- Baseline file list captured for every subsequent prompt.

## Phase B — Backend and observability foundation

### Prompt B1 — Canonical event schema v1.0
Goal:
- Define one normalized `CleanHouseEvent` + one normalized `EvidenceRef` + one `SessionEnvelope` used by collectors and reporting.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- `backend` existing event handling
Architectural constraints:
- Must include `event_id`, `timestamp`, `source`, `severity`, `confidence`, `uncertainty`, `evidence_refs`, `observed_vs_expected`.
- All fields must be immutable once emitted.
Acceptance tests:
- Add/adjust tests in `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_cleanhouse_monitoring_api.py`:
  - validates schema keys.
  - validates `evidence_level` normalization to `observed|inferred|unknown`.
Anti-overclaim checks:
- No field may imply intent or motive.
Regression boundaries:
- Existing API response keys used by current UI must remain backwards compatible.
Completion criteria:
- Stable event schema and schema-validated emission from `cleanhouse_monitoring.py`.

### Prompt B2 — Collector status contract
Goal:
- Emit deterministic collector status events whenever any observer fails to run.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- B1
Architectural constraints:
- Collector failures become first-class event payloads, not hidden exceptions.
Acceptance tests:
- Add negative tests for at least one simulated collector failure per source type.
Anti-overclaim checks:
- Status text must be: unable to execute, reason, missing context.
Regression boundaries:
- Existing alert counts should not decrement silently.
Completion criteria:
- `/api/cleanhouse/status` and internal aggregation expose collector failure evidence.

### Prompt B3 — Process collector normalization
Goal:
- Normalize process events into canonical event schema, including platform tagging and agent-pattern classification.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/collectors/process_monitor.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1
Architectural constraints:
- Keep local process-only scanning semantics.
- No process list mutation.
Acceptance tests:
- Mock command list and validate platform and is_agent flags are attached in emitted event evidence.
Anti-overclaim checks:
- Event language must stay process-pattern-based, not identity-based.
Regression boundaries:
- Existing process endpoint response shape not reduced.
Completion criteria:
- Process events are consistently emitted and traceable to PID/command.

### Prompt B4 — Network observer normalization
Goal:
- Normalize connection observations and DNS/service tags into canonical events.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/collectors/data_flow_tracer.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1
Architectural constraints:
- No deep packet inspection in v1.
- Record endpoint family, protocol metadata, pid/command linkage when available.
Acceptance tests:
- Add deterministic unit fixture for suspicious endpoint tagging.
- Verify event has reproducible `evidence_refs` path.
Anti-overclaim checks:
- Report observable network pattern, not intent.
Regression boundaries:
- Existing network endpoint (`/cleanhouse/network`) not removed.
Completion criteria:
- Network collector emits reproducible event references and anomaly summary.

### Prompt B5 — File integrity collector status and hash pipeline hardening
Goal:
- Bring integrity baseline + change detection into one v1 path that emits explicit evidence refs.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/integrity.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1
Architectural constraints:
- Integrity check remains local file-system based.
- Expose unauthorized diff summary and count deltas.
Acceptance tests:
- Add tests for changed file detection, duplicate scan, and baseline generation determinism.
Anti-overclaim checks:
- Never phrase file hash mismatch as user intent violation.
Regression boundaries:
- Existing integrity baseline file path remains unchanged unless migration documented.
Completion criteria:
- Integrity path produces evidence envelopes with stable IDs and scope tags.

### Prompt B6 — Shell/command observer adapter
Goal:
- Add observable wrapper for command execution used by CleanHouse itself (internal wrappers first, then optional external hook points).
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/server.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- B1
Architectural constraints:
- Capture command, args, cwd, user context, exit status, duration.
- Do not intercept third-party code execution without explicit scope and opt-in consent.
Acceptance tests:
- Add one unit test for command event with exit status + duration.
- Add one test for command observer with missing cwd context.
Anti-overclaim checks:
- Capture only execution metadata; do not infer action quality.
Regression boundaries:
- Existing cleanhouse API endpoints remain unchanged in payload shape for unaffected paths.
Completion criteria:
- At least one command observer source emits events with full required command fields.

### Prompt B7 — Prompt observer adapter
Goal:
- Capture declared user intent text and scope in a local session-scoped table (UI-origin only for v1).
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1
Architectural constraints:
- Persist scope string + repo path + tool identity.
- Store no hidden remote context.
Acceptance tests:
- API test for prompt endpoint persistence and retrieval.
- UI test for missing prompt text producing explicit unknown state.
Anti-overclaim checks:
- Prompt is treated as declared intent text; no claimed truth/intent extraction.
Regression boundaries:
- Do not alter unrelated auth/session behavior.
Completion criteria:
- Each session can associate commands and file/network events with nearest prior prompt.

### Prompt B8 — Diff observer
Goal:
- Capture before/after filesystem deltas scoped to repo/session.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_cleanhouse_monitoring_api.py`
Dependencies:
- B5, B6, B7
Architectural constraints:
- Diff summaries only for files under repository scope; no sensitive path exfiltration.
Acceptance tests:
- Modify-temp-file simulation and verify created/modified/deleted event entries.
Anti-overclaim checks:
- Diff is content-change evidence, not behavior motive evidence.
Regression boundaries:
- Existing security scan and log writing behavior unaffected.
Completion criteria:
- Diff summary is linked by `session_id` and retrievable in timeline.

## Phase C — Correlation, timeline, and risk scoring

### Prompt C1 — Event correlation engine
Goal:
- Build deterministic correlation pass connecting prompt -> command -> diff -> network/process edges.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1, B3, B4, B5, B6, B7, B8
Architectural constraints:
- Keep correlation explainable and deterministic.
- If correlation confidence is low, set `observed_vs_expected` unknowns.
Acceptance tests:
- Fixture where one prompt maps to one command and one file diff.
- Fixture where mapping missing command/intent -> unknown gap recorded.
Anti-overclaim checks:
- Output must not use causal language beyond observable sequence.
Regression boundaries:
- Keep anomaly feed and status endpoint behavior stable.
Completion criteria:
- Correlated graph edges stored and retrievable for each session.

### Prompt C2 — Session timeline provider
Goal:
- Emit immutable chronological per-session timeline with strict event ordering and nearest-event linkage.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- C1
Architectural constraints:
- Append-only semantics, no in-place timeline mutation.
Acceptance tests:
- Test two events out of order are ordered by timestamp.
- Test unknown collector still appears in timeline with explicit status.
Anti-overclaim checks:
- Timeline labels event status only by evidence quality.
Regression boundaries:
- No timeline pagination regressions for existing consumers.
Completion criteria:
- Timeline endpoint returns deterministic sequence from session origin.

### Prompt C3 — Drift and deviation scoring rubric
Goal:
- Convert correlation outputs into `drift`, `deviation`, and `risk` classes with confidence and unknown fields.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- C1, C2
Architectural constraints:
- Inference only from observed data + optional hints.
- Unknown state must remain explicit and non-zero.
Acceptance tests:
- Scope expansion scenario emits deviation signal.
- Non-critical command mismatch with low confidence remains low-risk.
Anti-overclaim checks:
- Never emit maliciousness labels.
Regression boundaries:
- Existing anomaly endpoint keeps current schema keys with additive fields only.
Completion criteria:
- Deviation outputs include confidence+unknown and evidence refs.

### Prompt C4 — Runtime accountability signal layer
Goal:
- Add canonical signal matrix for prompt/action mismatch, scope expansion, and service endpoint drift as first-level alerts.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- C2, C3
Architectural constraints:
- Alert severity must map only to evidence strength and gap size.
Acceptance tests:
- Scenario tests for all severities: low/medium/high.
Anti-overclaim checks:
- Alerts avoid certainty language when evidence is partial.
Regression boundaries:
- Preserve any existing alert naming used by current UI.
Completion criteria:
- Alert list always has reproducible event references and rationale.

## Phase D — Receipt and reporting workflows

### Prompt D1 — Receipt model and builder
Goal:
- Create one deterministic receipt artifact per session with metadata, events, alerts, gaps, and evidence index.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- C2, C4
Architectural constraints:
- Machine-readable section + concise human summary.
- Must include unresolved gaps and unknowns explicitly.
Acceptance tests:
- Build receipt from fixture with no failures.
- Build receipt with partial failures and missing sources.
Anti-overclaim checks:
- Receipt uses observed/inferred/assumption/unknown labels.
Regression boundaries:
- Existing status and anomaly endpoints still function.
Completion criteria:
- Receipt returns a stable JSON object by session.

### Prompt D2 — Receipt signing/hash-linking
Goal:
- Add hash-chain or signature metadata so each receipt line can be traced integrity-wise.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- D1
Architectural constraints:
- Use deterministic local hash algorithm (e.g., SHA-256).
- Store hash in same local artifact.
Acceptance tests:
- Tampering a receipt event changes chain/hash deterministically.
- Rebuild check validates chain.
Anti-overclaim checks:
- Label integrity check as receipt integrity, not truth claims.
Regression boundaries:
- Do not enable encryption or remote signing in v1.
Completion criteria:
- Receipt object contains reproducible chain/hash metadata.

### Prompt D3 — Report Autonomous Behavior API + workflow
Goal:
- Implement explicit report action that exports session receipt with contact/target metadata for manual filing.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
Dependencies:
- D1
Architectural constraints:
- Never redact evidence links.
- Report includes only observed artifacts and declared unknowns.
Acceptance tests:
- API returns report payload and preserves evidence IDs.
- Missing receipt returns clear `not_found` failure state.
Anti-overclaim checks:
- Report language remains neutral and evidence-first.
Regression boundaries:
- Do not affect login/session routing.
Completion criteria:
- Single-click report path produces reproducible machine-readable output.

## Phase E — Zaelith integration and policy posture

### Prompt E1 — Zaelith runtime adapter contract
Goal:
- Adapt Zaelith to consume selected evidence slices only; keep it optional and non-blocking.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/zaelith_service.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- D1, C3
Architectural constraints:
- Optional fallback when Zaelith module absent.
- Never mix Zaelith output into raw event evidence store.
Acceptance tests:
- Zaelith unavailable path returns graceful unknown-state.
- Zaelith available path generates inference with explicit confidence + unknown fields.
Anti-overclaim checks:
- Zaelith outputs remain recommendations/summaries only.
Regression boundaries:
- Manual prompt-response analysis flow must remain operational.
Completion criteria:
- Zaelith inference appears as separate section in receipt and is clearly labeled inferred.

### Prompt E2 — Prompt/action mismatch rationale
Goal:
- Add a minimal Zaelith-style explanation that contrasts declared prompt scope vs observed command/file deltas.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/zaelith_service.py`
Dependencies:
- E1, C3
Architectural constraints:
- No deterministic assertion of bad faith.
- Unknowns surfaced when linkages are missing.
Acceptance tests:
- High-confidence prompt-action mismatch case.
- Partial mismatch case emits medium confidence + unknown.
Anti-overclaim checks:
- Output field names: `alignment_risk`, `behavioral_mismatch_risk` only.
Regression boundaries:
- Keep raw alert text format backward compatible if currently used by UI.
Completion criteria:
- Mismatch signal appears only as evidence-based inference.

## Phase F — UI and operator workflows

### Prompt F1 — Timeline and alert display
Goal:
- Show ordered timeline + alert list with severity, confidence, and evidence links.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/index.html` (or equivalent frontend entry)
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/desktop/wrapper.py`
Dependencies:
- C2, C4, D1
Architectural constraints:
- No speculation text in UI; unknown is first-class state.
Acceptance tests:
- UI request renders at least three states: clear, unknown, degraded-collector.
- Alert entry includes `event_id` link.
Anti-overclaim checks:
- Replace any “found a threat” language with “Observed behavior pattern.”
Regression boundaries:
- Existing app launch and wrapper behavior unaffected.
Completion criteria:
- Timeline and alerts appear from live session payload.

### Prompt F2 — Receipt viewer + report button
Goal:
- Add in-app “Report Autonomous Behavior” action with review panel for evidence refs.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/index.html`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/desktop/wrapper.py`
Dependencies:
- D3, F1
Architectural constraints:
- Preserve copy of raw refs in view; do not redact links.
Acceptance tests:
- Generate report and verify evidence refs count is non-zero for triggered event.
- Manual review panel handles empty report gracefully.
Anti-overclaim checks:
- UI copy: “Observed”, “Inferred”, “Unknown”.
Regression boundaries:
- Report action must not trigger network calls outside local host.
Completion criteria:
- Report flow usable in one click.

### Prompt F3 — Settings and preferences
Goal:
- Add scoped controls for collectors, risk thresholds, retention, and evidence depth.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/frontend/js/api-client.js`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
Dependencies:
- F1, D1
Architectural constraints:
- Defaults conservative and deterministic.
- No collector can be force-disabled globally without explicit local setting record.
Acceptance tests:
- Toggle persistence test.
- Invalid threshold fallback test.
Anti-overclaim checks:
- Settings names aligned with CleanHouse terminology only.
Regression boundaries:
- Existing auth/session defaults remain stable.
Completion criteria:
- Settings apply to observability pipeline and reflected in status output.

### Prompt F4 — Plugin registry (observability outputs)
Goal:
- Define lightweight plugin metadata for source adapters only (no code exec plugins in v1).
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- F3
Architectural constraints:
- Plugin metadata must not execute code by default.
- Must include enable/disable + scope.
Acceptance tests:
- Unknown plugin config handled as explicit warning.
Regression boundaries:
- No dynamic import changes at launch without config migration.
Completion criteria:
- Plugin list visible in status and persisted per session profile.

## Phase G — Third-party integrations and contracts

### Prompt G1 — Service contract adapters (read-only)
Goal:
- Add local read-only adapters for AWS/iCloud/OpenAI/T-Mobile/Google Cloud usage indicators.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/cloud.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
Dependencies:
- B1, F4
Architectural constraints:
- No token harvesting or credential decryption in v1.
- Capture only observed endpoint and usage metadata when present.
Acceptance tests:
- Adapter emits adapter_status with supported/unsupported states.
- Unsupported provider reports explicit limitation instead of fail.
Anti-overclaim checks:
- Adapter output is “observed request target”, not compliance verdict.
Regression boundaries:
- Keep existing credential handling in other modules unchanged.
Completion criteria:
- Contract adapter registry returns per-provider evidence refs or explicit unsupported state.

### Prompt G2 — External tool bridge hooks
Goal:
- Add explicit event hooks for Cursor/OpenCode/Codex/Copilot CLI command boundaries only.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse_monitoring.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/desktop/wrapper.py`
Dependencies:
- B6, G1
Architectural constraints:
- Hooking is declarative and opt-in.
- No direct subprocess replacement.
Acceptance tests:
- Simulated external tool event ingestion test.
- Unknown tool mapping handled as `tool_unknown`.
Anti-overclaim checks:
- Output should say “tool context captured”, not “tool trust reduced.”
Regression boundaries:
- Local desktop launcher behavior remains unchanged.
Completion criteria:
- Tool context appears in event stream with provenance.

## Phase H — Local persistence and schema migration

### Prompt H1 — Evidence store schema migration
Goal:
- Establish local persistence path and schema versions for events/timelines/receipts.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- C2, D1
Architectural constraints:
- Backward-compatible read for old event files.
- No silent data loss.
Acceptance tests:
- Migration test from old schema to v1.
Regression boundaries:
- Existing logs remain readable by current readers.
Completion criteria:
- Versioned event and receipt artifacts persist with retention policy.

### Prompt H2 — Retention, cleanup, and purge policy
Goal:
- Implement predictable retention and safe cleanup controls for evidence directories.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/corefiles/config.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- H1
Architectural constraints:
- Evidence removal must require explicit operator action.
- Cleanup records a retention event.
Acceptance tests:
- Retention prune reduces old events deterministically.
- Cleanup emits event for every deletion action.
Anti-overclaim checks:
- Report that cleanup occurred; do not infer disappearance reasons.
Regression boundaries:
- Local logs path fallback behavior unchanged.
Completion criteria:
- Configurable retention with auditable cleanup receipts.

## Phase I — QA, security, and release hardening

### Prompt I1 — Test expansion
Goal:
- Add one minimal full-chain test suite for v1 acceptance boundaries.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_cleanhouse_monitoring_api.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_cleanhouse_integration.py` (create)
Dependencies:
- H2, C1-C4
Architectural constraints:
- Tests must cover collector success, partial failure, full failure.
Acceptance tests:
- Session with declared prompt + command + diff + network events.
- Collector outage yields explicit degraded session status and no timeline suppression.
- Unauthorized scope expansion generates alert with evidence refs and confidence.
Anti-overclaim checks:
- Tests assert evidence refs are present where required.
Regression boundaries:
- Do not alter baseline API test semantics unless intentionally changed and updated.
Completion criteria:
- `pytest` run includes integration path for timeline→receipt→report.

### Prompt I2 — Security and reliability hardening
Goal:
- Harden for local exposure limits, CORS/session settings, input validation, and filesystem boundaries.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/server.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/auth.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py`
Dependencies:
- I1 (self)
Architectural constraints:
- No telemetry beyond local host by default.
- Validate all inputs before processing.
Acceptance tests:
- Invalid input payloads return explicit `400` + reason.
- Session IDs reject malformed entries.
Anti-overclaim checks:
- Never describe security controls as complete guarantees; describe as observed safeguards.
Regression boundaries:
- Existing valid auth flows and local sessions remain operational.
Completion criteria:
- Reduced undefined behavior under malformed requests.

### Prompt I3 — Packaging and distribution
Goal:
- Produce deterministic local packaging bundle for one executable entry path (python runtime launcher + desktop wrapper).
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/desktop/wrapper.py`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/requirements.txt`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md`
Dependencies:
- I2
Architectural constraints:
- Keep one canonical launch path.
- Preserve zero-browser-automation constraint for operators.
Acceptance tests:
- Start sequence from wrapper succeeds.
- Smoke path: local dashboard loads and displays existing session status.
Anti-overclaim checks:
- Packaging deliverable claims are limited to install/run capability.
Regression boundaries:
- Do not alter architecture by adding remote-updater dependency in v1.
Completion criteria:
- Production-prep runbook with reproducible launch command.

### Prompt I4 — Release documentation and public/internal congruency
Goal:
- Align product wording across README, rubric, and endpoint docs; remove over-claims.
Required files:
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md`
- `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
Dependencies:
- I3
Architectural constraints:
- Terminology only from approved canon.
- Any capability mention must cite local evidence path.
Acceptance tests:
- Terminology audit script/manual pass confirms no forbidden terms.
- Internal/external docs have same core claim boundaries.
Anti-overclaim checks:
- Remove “detection” language that implies prevention or authority.
Regression boundaries:
- No endpoint docs removed.
Completion criteria:
- Congruent docs and release notes describing current implemented v1 behavior.

## Global acceptance criteria before planning/feature expansion
- One executable path runs.
- All prompt, command, file, process, and network events persist in session timeline.
- Every alert has reproducible event IDs and evidence refs.
- Collector failure is visible in session status and timeline.
- Report workflow emits observed/inferred/unknown breakdown with raw evidence links.
- No module asserts intent, malice, or AGI-level control.
- Local persistence supports deterministic rerender of incident evidence.
- v1 can be repeatedly replayed from fixtures.

## Release hardening checklist (must pass before v1 release)
- [ ] Evidence-first rubric parity pass against code.
- [ ] All deprecated placeholder logic either removed or explicitly gated with explicit unsupported states.
- [ ] At least one failure-path test per collector.
- [ ] Timeline integrity checksums stable across reruns.
- [ ] Report output is machine-replayable.
- [ ] Runtime launch and first-paint behavior verified without browser automation.
