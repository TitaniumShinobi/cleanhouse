# CleanHouse Evidence Publication Report
Date: 2026-05-30
Scope Rule: Repository-documented evidence only; no synthetic incidents; no speculative claims.

## 1. Executive Summary
- CleanHouse is documented as a local-first runtime accountability and coordination system whose doctrine is evidence-first (`observed | inferred | unknown`). [C01] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md:7-17)
- The Tier 1 audit verdict documents a real runtime-accountability substrate plus one tested narrow end-to-end receipt lane, and explicitly states Tier 1 universal runtime mutation accountability is not yet satisfied. [C02] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:16-18)
- Runtime-chain validation artifacts exist for five runs and are explicitly marked validation-only and not canonical proof artifacts. [C03] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:1-3)
- The current daily-use readiness assessment documents active blockers across reliability, coverage, operator workflow, deployment friction, and trust posture. [C04] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:20-25)

## 2. Current Capabilities (proven only)
- Runtime-chain captures are produced with a fixed artifact set (`chain_ids.json`, `outcome.json`, `evidence_refs.json`, `incident_receipt.json`, `test_output.txt`, `operator_screenshot.png`, `manifest.json`). [C05] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:13-21)
- The runtime-chain run catalog currently records five run folders with event/incident/receipt IDs. [C06] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.md:3-11)
- At least one captured run shows successful receipt creation (`receipt_create_http=200`, `receipt_create_status=ok`) and decision actions (`quarantine`, `purge`, `bless`) returning `http=200 status=ok`. [C07] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/test_output.txt:8-13)
- Captured outcomes show multiple decision states (`rejected`, `blessed`, `quarantined`, `purge_pending`) with stored `outcome_hash` values. [C08] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231953Z_domain_event_77f6db2f8902f91f/outcome.json:3-11)
- Notification spam test evidence records `41 passed, 115 deselected`, probe status `ok`, and all listed acceptance checks as satisfied in that run. [C09] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:16-32)
- The report API surface is implemented with `POST /cleanhouse/report` and `GET /cleanhouse/reports` routes. [C10] (/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:1930-1931)

## 3. Report Feature Definition (as currently documented)
- The documented report workflow is "Report Autonomous Behavior API + workflow" that exports a session receipt with contact/target metadata for manual filing. [C11] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md:381-384)
- The documented acceptance criteria require the report API to preserve evidence IDs and return a clear `not_found` state for missing receipts. [C12] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md:393-395)
- The implemented `/cleanhouse/report` route validates `session_id` and accepts optional `report_type`, `contact`, `target`, and `context`, defaulting `report_type` to `incident`. [C13] (/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:1930-1958)
- The implemented `/cleanhouse/reports` route supports retrieval by optional `session_id`, `report_type`, `limit`, and `summary_only`. [C14] (/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:2011-2028)

## 4. Runtime Proof Status
- Runtime-chain evidence storage is explicitly labeled "Not Canonical" and "validation_only". [C03] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:1-3)
- Each listed runtime-chain run manifest records `validation_only: true`, `artifact_count: 6`, and SHA-256 entries for each artifact. [C15] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/manifest.json:2-3)
- The run catalog table currently keeps `decision_state` as `None` for each run entry. [C16] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.md:7-11)
- The strongest documented end-to-end proof remains a narrow fixture lane, not universal workstation coverage. [C17] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:426-430)
- Runtime checks in the Tier 1 audit record environment-sensitive limits (e.g., sandbox permission failures, missing dependencies) alongside passing fixture lanes. [C18] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:76-84)

## 5. Reliability Findings
- Collector reliability is documented as environment-sensitive, including permission and dependency sensitivity. [C19] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:20)
- The Tier 1 audit records runtime hygiene warnings during passing tests, including unclosed database warnings, queue drops, and process-scan permission errors. [C20] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:421-424)
- The audited environment documented missing `watchdog` support and disabled watcher classes. [C21] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:396-399)
- The audited environment documented integrity status `no_baseline` for the referenced runtime check. [C22] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:400-403)
- The beta proof chain records degraded collector health with multiple surfaces marked `unknown` and filesystem watcher marked `unavailable` due to dependency status. [C23] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/beta_proof_chain.json:193-207)

## 6. Coverage Findings
- The Tier 1 audit states CleanHouse cannot yet prove the universal product chain and explicitly lists missing Tier 1 product behaviors (including process lineage, shell coverage outside owned wrapper, and universal mutation capture). [C24] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:469-481)
- Readiness test coverage gates explicitly require unsupported claims to be reported as `gap` with evidence level `unknown`. [C25] (/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_production_readiness_proving_run.py:22-33)
- The daily-use readiness assessment documents persistent coverage incompleteness in universal filesystem coverage, native lineage, packet/DNS depth, cloud-provider state, and background-service correlation. [C26] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:60-65)

## 7. Operator Experience Findings
- Operator decision-state transitions are evidenced in captured outcomes (`blessed`, `rejected`, `quarantined`, `purge_pending`). [C08] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231953Z_domain_event_77f6db2f8902f91f/outcome.json:3-11)
- Runtime-chain capture requires an operator-provided screenshot input (`--operator-screenshot-source`) and enforces PNG validation. [C27] (/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/capture_runtime_chain_validation.py:156-159)
- Notification evidence is explicitly bounded as transport/dispatch metadata and not guaranteed operator-visible interruption proof. [C28] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5)
- Notification inventory classifies a small set as `VALID`, many as `REMOVE`, and records no `BROKEN` entries in that inventory snapshot. [C29] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:44-57)

## 8. Deployment Findings
- Canonical documented startup is `/bin/bash scripts/cleanhouse-up.sh` with dashboard target at `http://localhost:3333/dashboard`. [C30] (/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:34-40)
- The launcher script enforces interpreter resolution, starts supervisor-managed runtime, verifies readiness/runtime endpoints, then opens the dashboard. [C31] (/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh:89-113)
- Deployment/troubleshooting instructions remain manual for dependency install, port remap, and frontend extraction scripts. [C32] (/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:270-291)
- The README explicitly scopes v1 delivery to deterministic local install/launch and explicitly excludes auto-update or remote distribution workflow. [C33] (/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:110)

## 9. Trust Findings
- Beta proof bundle limitations explicitly state local-first scope, partial chain-of-custody, and no notification visibility guarantee as trust authority. [C34] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/known_limitations.json:2-4)
- Runtime-chain validation storage is explicitly labeled non-canonical validation evidence. [C03] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:1-3)
- Scope gate defines CleanHouse as passive local observability/reporting and explicitly excludes intent/threat/governance claims. [C35] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/SCOPE_GATE.md:10)

## 10. Notification Truth Findings
- Notification spam report records probe status `ok` and all listed acceptance checks as met in that documented run. [C09] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:16-32)
- Notification report text explicitly states that skipped/transport metadata must not be interpreted as desktop visibility confirmation. [C28] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5)
- Notification inventory marks `session_started`, `session_ended`, and `codex_prompt_sent` as valid production operator notifications in that inventory snapshot. [C36] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:46-50)
- Notification inventory also marks multiple notification types as persist-only/validation-only and classified for removal in that same snapshot. [C37] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:58-80)

## 11. Open Blockers
- Tier 1 universal runtime mutation accountability is documented as not yet satisfied. [C02] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:16-18)
- Daily-use blockers remain documented for collector reliability sensitivity, explicit coverage incompleteness, manual trust verification burden, manual deployment friction, and local-only trust posture. [C04] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:20-25)
- Tier 1 audit documents missing product behaviors that block stronger completion claims (including process lineage, universal mutation coverage, owned-route mediation for review-required actions, and verified rollback evidence). [C24] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:469-481)
- Runtime-chain run catalog currently leaves `decision_state` unset (`None`) for all listed entries. [C16] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.md:7-11)

## 12. Completion Criteria
- Daily-use completion criteria currently require stable repeated startup/runtime without manual repair, no recurring collector dependency/permission failures, explicit watcher/integrity initialization or fail-fast blocker behavior, reduced unsupported-gap set, verifiable notification acknowledgement evidence, and reduced manual artifact curation burden. [C38] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:151-156)
- Canon rubric guardrails prohibit inflated completion language without matching proof and require unknowns to be explicitly written as unknowns in completion reporting. [C39] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:691-693)
- Canon final standard defines completion as continuous operation, supported-surface observation with visible gaps, objective-scoped execution lineage correlation, approval mediation, deterministic signed receipts, replay verification, rollback where evidence exists, and an always-on evidence-backed operator view. [C40] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:697-704)

## 13. Evidence Index (claim -> file path + line)
- C01 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md:7-17`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md:33-35`
- C02 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:16-18`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:744-767`
- C03 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:1-3`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:41-42`
- C04 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:20-25`
- C05 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:13-21`
- C06 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.md:3-11`
- C07 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/test_output.txt:8-13`
- C08 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/outcome.json:3-11`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231953Z_domain_event_77f6db2f8902f91f/outcome.json:3-11`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231835Z_domain_event_a1f6c050cbfb6bcb/outcome.json:3-11`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231957Z_domain_event_02e9a4cca08a4ce4/outcome.json:3-11`
- C09 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:16-32`
- C10 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:1930-1931`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:2011-2012`
- C11 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md:381-384`
- C12 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md:393-395`
- C13 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:1930-1958`
- C14 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/backend/api/cleanhouse.py:2011-2028`
- C15 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/manifest.json:2-3`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/20260529T231942Z_domain_event_06bda7311b974be4/manifest.json:35-37`
- C16 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.md:7-11`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.json:11-12`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/RUN_CATALOG.json:47-48`
- C17 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:287-289`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:426-430`
- C18 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:76-84`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:415-419`
- C19 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:20`
- C20 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:75`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:421-424`
- C21 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:82-83`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:396-399`
- C22 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:84`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:400-403`
- C23 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/beta_proof_chain.json:115-123`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/beta_proof_chain.json:182-190`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/beta_proof_chain.json:193-207`
- C24 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:26-30`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:469-481`
- C25 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_production_readiness_proving_run.py:22-33`
- C26 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:60-65`
- C27 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/capture_runtime_chain_validation.py:156-159`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/capture_runtime_chain_validation.py:194-197`
- C28 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:38`
- C29 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:44-57`
- C30 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:34-40`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/QUICK_START.md:15-22`
- C31 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh:17-35`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh:89-113`
- C32 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:270-291`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/QUICK_START.md:47-64`
- C33 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:110`
- C34 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/beta-proof-bundle/known_limitations.json:2-4`
- C35 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/SCOPE_GATE.md:10`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/SCOPE_GATE.md:53-56`
- C36 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:46-50`
- C37 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md:58-80`
- C38 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_DAILY_USE_READINESS_ASSESSMENT.md:151-156`
- C39 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:649-663`, `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:691-693`
- C40 -> `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:697-704`

## 14. Unknowns / Non-Claims
- UNKNOWN (EVIDENCE NOT FOUND): A non-empty completion score table covering all rubric release-artifact domains in the required tabular form. [C39] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/CLEANHOUSE_RUBRIC.md:691-693)
- UNKNOWN (EVIDENCE NOT FOUND): Canonical runtime-chain artifacts approved as official proof rather than validation-only evidence. [C03] (/Users/devonwoodson/Documents/GitHub/cleanhouse/documents/30_evidence/runtime-chain-validation/README.md:1-3)
- UNKNOWN (EVIDENCE NOT FOUND): Universal filesystem/process/network/shell mutation accountability proof in current Tier 1 evidence. [C24] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:469-481)
- UNKNOWN (EVIDENCE NOT FOUND): Operator-visible interruption proof for notifications beyond transport metadata and acknowledgement flow artifacts. [C28] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5)
- NON-CLAIM: This report does not claim intent inference, threat judgment, or enforcement behavior. [C35] (/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/canon/SCOPE_GATE.md:10)

REPORT_STATUS: COMPLETE
