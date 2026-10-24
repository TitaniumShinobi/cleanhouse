# CLEANHOUSE PRODUCT BOARD

Last verified: 2026-05-30
Verification method:
- Runtime spot checks: `python3 scripts/gate_a_observability.py --pretty`; `python3 -m scripts.native_notification_runtime_probe --output /tmp/cleanhouse-native-notification-probe.json`
- Targeted tests: `python3 -m pytest tests/test_events_api.py -q`; `python3 -m pytest tests/test_gate_a_observability.py -q`; `python3 -m pytest tests/test_production_readiness_proving_run.py -q`; `python3 -m pytest tests/test_cleanhouse_monitoring_api.py -q -k "prompt_context_persistence_and_timeline or approval_queue_create_list_resolve or notification_policy_defaults_cover_required_agent_notifications or native_operator_notification_allowlist_is_noise_controlled_to_objective_and_drift or integrity_baseline_determinism or integrity_changed_file_detection or receipt_includes_prompt_and_approval_queue_entries or replay_or_signature_failure_notification_from_tampered_bundle"`
- Product walkthrough (operator perspective):
  - `/login`, `/signup`, `/dashboard`, `/incident-receipt` screenshot capture
  - Route probe evidence at `docs/evidence/product_reality/route_probe.txt`
  - Product reality report: `docs/reports/CLEANHOUSE_PRODUCT_REALITY_REPORT_2026-05-30.md`

Calibration rubric:
- `[x]` requires `operational` with concrete proof.
- `[ ]` is used for `partial`, `substrate-only`, `unsupported`, or `unknown`.
- Status labels align with `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md:907`.

## PRODUCT REALITY DISTINCTION (2026-05-30)

### PRODUCT (OPERATOR-ACCESSIBLE NOW)
- [x] Login surface (`/login`) rendered and screenshot captured.
- [x] Signup surface (`/signup`) rendered and screenshot captured.
- [x] Dashboard surface (`/dashboard`) rendered and screenshot captured.
- [x] Incident receipt surface (`/incident-receipt`) rendered and screenshot captured.

### INFRASTRUCTURE (IMPLEMENTED, BUT NOT OPERATOR-RELIABLE IN THIS WALKTHROUGH)
- [ ] Runtime status/control APIs (`/cleanhouse/status`, `/cleanhouse/runtime`) timed out during probe.
- [ ] Workstation aggregation API (`/cleanhouse/workstation`) timed out during probe.
- [ ] Receipt/incident data APIs showed timeout/degraded accessibility in the same walkthrough lane.
- [ ] Attribution/enforcement subsystems (actor/channel/trust/scope) remain primarily backend evidence-chain capability until consistently visible and actionable in live UI.

### MISSING CAPABILITIES (PRODUCT GAP)
- [ ] Deterministic low-latency operator path for dashboard core APIs.
- [ ] Reliable end-to-end operator loop: start session -> declare objective -> monitor -> receipt/replay without route timeout degradation.
- [ ] First-class UI surfacing of scope enforcement deviation records and mediation outcomes.

## PROCESS MEDIATION
- [x] Objective ingestion — `operational` — refs: `backend/api/cleanhouse.py:362`, `backend/api/cleanhouse.py:396`, `tests/test_events_api.py:284`
- [x] Context ingestion — `operational` — refs: `backend/api/cleanhouse.py:429`, `backend/api/cleanhouse_monitoring.py:499`, `tests/test_cleanhouse_monitoring_api.py:1066`
- [x] Action tracking — `operational` — refs: `backend/api/cleanhouse_monitoring.py:9457`, `backend/api/cleanhouse_monitoring.py:10871`, `tests/test_cleanhouse_monitoring_api.py:2291`, `tests/test_cleanhouse_monitoring_api.py:2320`, `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md:314`
- [x] Mutation tracking — `operational` — refs: `backend/api/cleanhouse_monitoring.py:8405`, `backend/api/cleanhouse_monitoring.py:8445`, `tests/test_cleanhouse_monitoring_api.py:1474`, `/tmp/cleanhouse-mutation-runtime-proof.json`, `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md:314`
- [x] Approval queue — `operational` — refs: `backend/api/cleanhouse.py:1028`, `backend/api/cleanhouse.py:1092`, `tests/test_cleanhouse_monitoring_api.py:1099`
- [x] Deviation detection — `operational` — refs: `backend/api/cleanhouse_monitoring.py:9323`, `tests/test_cleanhouse_monitoring_api.py:1738`, `/tmp/cleanhouse-deviation-runtime-proof.json`
- [ ] Intervention workflow — `partial` — refs: `backend/api/cleanhouse_monitoring.py:10688`, `backend/api/cleanhouse_monitoring.py:9638`, `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md:896`

## FILE INTEGRITY
- [x] Baseline generation — `operational` — refs: `corefiles/integrity.py:205`, `tests/test_cleanhouse_monitoring_api.py:941`
- [x] Hash verification — `operational` — refs: `corefiles/integrity.py:187`, `corefiles/integrity.py:276`, `tests/test_cleanhouse_monitoring_api.py:893`
- [x] Change detection — `operational` — refs: `corefiles/integrity.py:365`, `backend/api/cleanhouse.py:1202`, `tests/test_cleanhouse_monitoring_api.py:1361`
- [ ] Chain of custody — `partial` — refs: `scripts/generate_beta_proof_bundle.py:152`, `scripts/generate_beta_proof_bundle.py:164`
- [ ] Retention lifecycle — `partial` — refs: `tests/test_cleanhouse_monitoring_api.py:2140`, `tests/test_cleanhouse_monitoring_api.py:2156`
- [ ] Evidence signing — `partial` — refs: `scripts/verify_bundle.py:2`, `scripts/verify_bundle.py:214`, `tests/test_cleanhouse_monitoring_api.py:4182`

## AGENT FIREWALL
- [ ] Actor identification — `partial` — refs: `backend/api/cleanhouse_monitoring.py:2779`, `backend/api/cleanhouse_monitoring.py:8539`
- [ ] Authority attribution — `partial` — refs: `backend/api/cleanhouse_monitoring.py:1944`, `backend/api/cleanhouse_monitoring.py:10878`
- [ ] Channel attribution — `partial` — refs: `backend/api/cleanhouse_monitoring.py:3248`, `backend/api/cleanhouse_monitoring.py:7500`
- [ ] Trust evaluation — `substrate-only` — refs: `backend/api/cleanhouse_monitoring.py:224`, `backend/api/cleanhouse_monitoring.py:5654`
- [ ] Scope enforcement — `partial` — refs: `backend/api/cleanhouse_monitoring.py:1944`, `backend/api/cleanhouse_monitoring.py:10728`, `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md:895`
- [x] Approval mediation — `operational` — refs: `backend/api/cleanhouse_monitoring.py:10675`, `tests/test_cleanhouse_monitoring_api.py:1336`, `tests/test_cleanhouse_monitoring_api.py:1139`

## OPERATOR LAYER
- [x] Start notification — `operational` — refs: `backend/api/cleanhouse_monitoring.py:4511`, `tests/test_cleanhouse_monitoring_api.py:4887`
- [x] End notification — `operational` — refs: `backend/api/cleanhouse_monitoring.py:4556`, `tests/test_cleanhouse_monitoring_api.py:2921`
- [x] Drift notification — `operational` — refs: `backend/api/cleanhouse_monitoring.py:9390`, `tests/test_cleanhouse_monitoring_api.py:3905`, `/tmp/cleanhouse-native-notification-probe.json`
- [x] Zero-spam guarantees — `operational` — refs: `backend/api/cleanhouse_monitoring.py:6562`, `tests/test_cleanhouse_monitoring_api.py:3947`, `tests/test_cleanhouse_monitoring_api.py:3584`, `/tmp/cleanhouse-native-notification-probe-live.json`

## INFRASTRUCTURE
- [x] Events API validation — `operational` — refs: `backend/api/cleanhouse.py:227`, `backend/api/cleanhouse.py:245`, `backend/api/cleanhouse.py:2019`, `tests/test_events_api.py:179`, `tests/test_events_api.py:277`
- [ ] Operational readiness — `partial` — refs: `backend/api/cleanhouse.py:249`, `scripts/tier1_runtime_gate.py:1`, `scripts/production_readiness_proving_run.py:1`
- [ ] Documentation alignment — `partial` — refs: `README.md:27`, `docs/canon/CLEANHOUSE_CANONICAL_RUNTIME_SPINE.md:5`, `docs/canon/CLEANHOUSE_CANONICAL_RUNTIME_SPINE.md:23`
- [x] Proof bundle automation — `operational` — refs: `scripts/generate_beta_proof_bundle.py:2`, `scripts/generate_beta_proof_bundle.py:148`, `tests/test_production_readiness_proving_run.py:1`

## PRODUCT SCOPE GUARDRAIL
Notifications, receipts, bundles, audits, and evidence are supporting systems.
They are not the destination.

## NOTIFICATION INTERRUPT POLICY
Notify only when:
- Objective Started
- Objective Completed
- Deviation Detected

Never notify for:
- Heartbeats
- Polls
- Healthy status
- Composer activity
- "Still alive" events

Operator interruption test for every new monitoring source (AWS, OpenAI, launchd, Homebrew, Docker, Cursor, Codex, local processes, network activity):
"Would Devon stop what he's doing because this requires attention right now?"

If the answer is no, it belongs in the timeline, evidence chain, or dashboard, not a desktop notification.

## NEXT-TO-CLOSE QUEUE (TOP 3)
1. Operator API responsiveness (`missing`) -> close `/cleanhouse/status`, `/cleanhouse/runtime`, `/cleanhouse/workstation` timeout behavior so dashboard controls are product-usable.
2. End-to-end operator loop reliability (`missing`) -> close session start/objective declaration/receipt path consistency under live runtime conditions.
3. Scope enforcement UI exposure (`missing`) -> close gap between backend deviation records and operator-visible actionable panel state.
