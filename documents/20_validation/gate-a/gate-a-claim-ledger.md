# CleanHouse Gate A Claim Ledger And Verification Checklist

Date: 2026-05-25
Owner: Audit subagent
Scope: docs/test gate artifact only; no backend, UI, launcher, or runtime logic
changes.

## Gate A Boundary

Gate A is a contract and evidence-inventory gate. It can lock terminology,
separate infrastructure from product behavior, and define the proof required for
later phases. It does not make runtime behavior true.

Controlling inputs:

- `docs/canon/CLEANHOUSE_RUBRIC.md`
- `docs/canon/SCOPE_GATE.md`
- `docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md`
- `docs/canon/CLEANHOUSE_EVIDENCE_AUDIT.md`
- `docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md`
- `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md`
- `docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md`

Evidence levels remain `observed`, `inferred`, and `unknown`. Capability labels
remain `operational`, `partial`, `substrate-only`, `unsupported`, and `unknown`.

## Claim Ledger

| ID | Claim or surface | Current label | Evidence basis | Gate A decision |
|---|---|---|---|---|
| GA-01 | Canonical scope documents exist and define the evidence-first contract. | `substrate-only` / `observed` | Rubric, scope gate, thesis, audit, master plan, phased plan are present in this checkout. | Use as contract input only; document presence is not product behavior. |
| GA-02 | Phase A has a defined contract-lock prompt and baseline-inventory prompt. | `substrate-only` / `observed` | `docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md` Phase A, Prompt A0 and Prompt A1. | Gate A may enforce scope and inventory expectations; it does not prove runtime capture. |
| GA-03 | A product claim inventory exists. | `partial` / `observed` | This file starts a small ledger; `docs/plans/CLEANHOUSE_PRODUCTION_READINESS_EXECUTION_PLAN.md` requires a full inventory. | Full pass requires every product claim term to map to evidence, a future requirement, or a blocked status. |
| GA-04 | Baseline inventory is frozen for runtime-facing modules. | `partial` / `unknown` | Prompt A1 lists target files, but this artifact does not create a checksum ledger. | Gate A remains incomplete until the A1 file list and hashes are captured without changing runtime code. |
| GA-05 | Launchers, routes, schemas, collectors, dashboard panels, SQLite tables, and receipt classes exist. | `substrate-only` / `observed` | Evidence audit, phased plan current boundary, and Tier 1 audit. | These are infrastructure until a fresh runtime receipt proves the product spine. |
| GA-06 | The narrow controlled lane can connect prompt/context, tool event, snapshot diff, timeline, receipt, approval review, and replay bundle. | `partial` / `observed` from docs, not re-verified here | `docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md` current boundary and `docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md`. | May be described as a narrow controlled lane only; do not generalize to Tier 1 completion. |
| GA-07 | Universal filesystem, process lineage, shell, and port/network accountability are fulfilled. | `unsupported` or `missing as product behavior` | Phased plan capability scoreboard and Tier 1 audit gaps. | Block any universal or daily-use completion claim until the Tier 1 runtime chain passes. |
| GA-08 | Operator timeline hydration is proven in normal use. | `partial` / `unknown` for live operator proof | Tier 1 audit says timeline hydration is partial and lacks full live collector proof. | Requires manual, no-browser-automation operator verification before product fulfillment language. |
| GA-09 | Rollback is fulfilled product behavior. | `unsupported` beyond narrow fixture state | Tier 1 audit states approval is review state and rollback is not fulfilled product behavior. | Recovery claims require prior state, recovery action, result, and verification evidence. |
| GA-10 | Cloud/runtime ecosystem correlation is fulfilled. | `mostly missing` / `unknown` | Phased plan lists cloud/runtime ecosystems as mostly missing. | Remote or provider claims stay bounded to imported or returned local evidence. |

## Verification Checklist

### A0 - Contract Lock

Pass threshold:

- canonical input files exist;
- no runtime code is modified by the Gate A audit artifact;
- Gate A output uses only approved evidence levels and capability labels;
- every product claim is either evidence-backed, marked future, or blocked;
- no infrastructure object is described as fulfilled product behavior by itself.

Suggested commands:

```sh
test -f docs/canon/CLEANHOUSE_RUBRIC.md
test -f docs/canon/SCOPE_GATE.md
test -f docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md
test -f docs/canon/CLEANHOUSE_EVIDENCE_AUDIT.md
test -f docs/canon/CLEANHOUSE_MASTER_IMPLEMENTATION_PLAN.md
test -f docs/plans/CLEANHOUSE_PHASED_EXECUTION_PLAN.md
test -f docs/evidence/CLEANHOUSE_TIER1_RUNTIME_ACCOUNTABILITY_AUDIT.md
git diff --name-only -- backend frontend corefiles ui desktop scripts
```

Expected result: all file checks pass, and the runtime-code diff command prints
nothing for this Gate A artifact.

### A1 - Baseline Inventory Freeze

Pass threshold:

- every Prompt A1 runtime-facing file exists or is marked missing;
- each existing Prompt A1 file has a captured SHA-256 hash;
- the inventory records the command, timestamp, checkout path, and missing files;
- subsequent implementation prompts compare against this inventory before
  touching runtime-facing modules.

Suggested command pattern:

```sh
shasum -a 256 \
  backend/api/cleanhouse.py \
  backend/api/cleanhouse_monitoring.py \
  backend/server.py \
  corefiles/config.py \
  corefiles/monitor.py \
  corefiles/integrity.py \
  corefiles/collectors/process_monitor.py \
  corefiles/collectors/agent_movement_monitor.py \
  corefiles/collectors/data_flow_tracer.py \
  tests/test_cleanhouse_monitoring_api.py \
  frontend/js/api-client.js \
  desktop/wrapper.py
```

Expected result: every listed file has either a hash or an explicit missing-file
entry. A hash list alone is still substrate; it only becomes useful when later
prompts compare against it.

### Product Behavior Gate

Fulfilled product behavior cannot be claimed until a fresh local run proves the
plan's product spine:

```text
objective -> actions -> mutations -> receipts -> approval/rollback
```

Minimum measurable proof before Tier 1 language:

- objective declared with scope, exclusions, repo/runtime surface, and expected
  output;
- prompt/context ingested for that objective;
- one owned command routed;
- child process PID/PPID lineage captured;
- in-scope and out-of-scope file mutations captured;
- mutation evidence appears through snapshot diff and watcher or explicit
  watcher/integrity gap;
- local port open and close delta captured;
- approval created and resolved for the out-of-scope mutation;
- receipt includes evidence refs, gaps, scope analysis, collector readiness, and
  hash chain;
- replay, export, import, and second replay preserve hashes and evidence refs;
- every missing collector or unsupported route appears as a receipt gap.

Gate A status: this checklist is ready for use as a contract artifact. Broad
CleanHouse runtime accountability remains `substrate-only` or `partial` until
the runtime gates above pass in a fresh local workspace.
