# CleanHouse Daily Use Readiness Assessment

Date: 2026-05-29
Status basis: Thesis assumed proven from multi-chain runtime validation.
Scope: Identify blockers to daily operation only.

## CURRENT CAPABILITIES

- Real runtime chain mediation works across independent runs (`modified`, `new`, `missing`) with varied decisions and preserved IDs/hashes:
  - [runtime_chain_validation](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/runtime_chain_validation)
- Runtime chain captures are structured and tamper-indexed (`manifest.json` with SHA-256):
  - [capture_runtime_chain_validation.py](/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/capture_runtime_chain_validation.py)
- Notification spam controls and suppression logic are present and tested:
  - [CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:22](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:22)
- Supervisor-based launcher and readiness probing exist for local startup:
  - [cleanhouse-up.sh](/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh)

## DAILY-USE BLOCKERS

- Collector reliability is environment-sensitive (`Operation not permitted`, missing dependencies), producing partial/unknown runtime truth.
- Coverage remains explicitly incomplete in core domains (filesystem universality, lineage, packet/DNS depth, cloud provider state).
- Operator still performs manual prep and verification to trust runtime state.
- Deployment remains local/manual with recurring troubleshooting paths and environment toggles.
- Trust posture remains local-only with partial chain-of-custody and non-guaranteed operator-visible notifications.

## RELIABILITY GAPS

What currently works:
- Runtime chains and receipt flow execute in controlled runs:
  - [test_output example](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/runtime_chain_validation/20260529T231942Z_domain_event_06bda7311b974be4/test_output.txt:6)

What still breaks:
- Queue drops, unclosed DB warnings, and permission failures are observed:
  - [CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:75](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:75)

What still requires manual intervention:
- Integrity baseline prep appears in each validated run (`baseline_rc=0`):
  - [test_output.txt:3](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/runtime_chain_validation/20260529T231942Z_domain_event_06bda7311b974be4/test_output.txt:3)

What prevents daily usage:
- Runtime truth quality degrades when collectors are blocked/unsupported.

Evidence proving the problem:
- `watchdog` missing and observer disabled in audited environment:
  - [CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:82](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:82)
  - [CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:83](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md:83)

## COVERAGE GAPS

What currently works:
- `process_file_integrity_suspicion` provides actionable process+file correlation for observed cases.

What still breaks:
- Universal coverage claims are intentionally marked as gaps/unknown in readiness tests:
  - [test_production_readiness_proving_run.py:22](/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_production_readiness_proving_run.py:22)

What still requires manual intervention:
- Explicit mutation setup is still required in validation runs to produce evidence.

What prevents daily usage:
- Gaps persist in universal filesystem coverage, native process lineage, packet/DNS capture depth, cloud sync state, and background correlation.

Evidence proving the problem:
- Unsupported claims are explicitly asserted in test gate:
  - [test_production_readiness_proving_run.py:26](/Users/devonwoodson/Documents/GitHub/cleanhouse/tests/test_production_readiness_proving_run.py:26)

## OPERATOR EXPERIENCE GAPS

What currently works:
- Incident card decision path executes with clear state transitions (`quarantined`, `purge_pending`, `blessed`, `rejected`):
  - [outcome.json example](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/runtime_chain_validation/20260529T231953Z_domain_event_77f6db2f8902f91f/outcome.json:3)

What still breaks:
- Notification evidence is transport-level and does not prove visible interruption.

What still requires manual intervention:
- Operator screenshot capture is required as artifact input:
  - [capture_runtime_chain_validation.py:156](/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/capture_runtime_chain_validation.py:156)

What prevents daily usage:
- Operator must still audit technical artifacts to verify what was seen and acted on.

Evidence proving the problem:
- Notification report explicitly limits visibility claims:
  - [CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:5)
  - [CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:38](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/CLEANHOUSE_NOTIFICATION_SPAM_TEST_REPORT.md:38)

## DEPLOYMENT GAPS

What currently works:
- Canonical startup path exists with supervisor health checks.

What still breaks:
- Frequent dependency and environment troubleshooting remains normal.

What still requires manual intervention:
- Manual venv setup, dependency install, optional extraction scripts, port remap, alias repair.

What prevents daily usage:
- "Run it daily and forget machinery exists" is not reliable under local environment drift.

Evidence proving the problem:
- Manual setup and troubleshooting requirements are explicit:
  - [README.md:20](/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:20)
  - [README.md:270](/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:270)
  - [README.md:285](/Users/devonwoodson/Documents/GitHub/cleanhouse/README.md:285)
  - [QUICK_START.md:47](/Users/devonwoodson/Documents/GitHub/cleanhouse/QUICK_START.md:47)

## TRUST GAPS

What currently works:
- Signed/offline verification tooling exists for bundle integrity.

What still breaks:
- Trust boundary remains explicitly local-first with partial chain-of-custody.

What still requires manual intervention:
- Out-of-band trust and fingerprint interpretation.

What prevents daily usage:
- No current basis for full external trust authority or complete chain-of-custody claims.

Evidence proving the problem:
- Known limitations explicitly state trust constraints:
  - [known_limitations.json:2](/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/beta_proof_bundle/known_limitations.json:2)

## TOP 10 DAILY-USE PROBLEMS

1. Collector dependency/permission failures create partial runtime truth.
2. `watchdog` dependency gaps disable parts of filesystem observation.
3. Integrity baseline initialization is not automatic/guaranteed for daily runs.
4. Unsupported coverage domains remain intentional unknowns.
5. Notification delivery does not guarantee operator-visible interruption.
6. Deployment requires manual environment maintenance and troubleshooting.
7. Incident lifecycle can remain open/in-review for non-final decisions.
8. Evidence capture still depends on manual screenshot workflow.
9. External trust authority and full chain-of-custody are not established.
10. Runtime health confidence still depends on reading technical artifacts.

## PRIORITIZED FIX ORDER

1. Reliability hardening first: eliminate collector dependency/permission fragility and queue-drop conditions.
2. Baseline automation second: ensure integrity baseline and watcher prerequisites are initialized or surfaced as hard blockers before runtime.
3. Coverage closure third: reduce unsupported-gap set in production-readiness tests.
4. Operator visibility fourth: make notification visibility proof operator-verifiable, not transport-only.
5. Deployment stabilization fifth: reduce startup and dependency drift friction to one-command deterministic operation.
6. Trust closure last: improve chain-of-custody and trust-anchor posture after daily operation is stable.

## COMPLETION CRITERIA

- Clean startup and continuous runtime over repeated days without manual environment repair.
- No recurring collector dependency/permission failures in normal operation.
- Integrity and watcher lanes initialize by default or fail fast with explicit blocker state.
- Production-readiness unsupported-gap set is reduced to an accepted minimal set with explicit operator impact.
- Notification pathway includes verifiable operator-visible acknowledgement evidence.
- Operator can run daily without crafting mutation setups or manually curating evidence artifacts.

## ASSUMPTIONS

- Thesis remains proven and out of scope for further validation in this phase.
- Assessment is constrained to current repository evidence and captured runtime validation artifacts.
- No new architecture or feature invention is included; only operational blockers and fix order.
