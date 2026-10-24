#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PYTHON_BIN=${CLEANHOUSE_PYTHON:-cleanhouse_env/bin/python}
export PYTHONPYCACHEPREFIX=${PYTHONPYCACHEPREFIX:-/private/tmp/cleanhouse_codex_action_pycache}

echo "[1/4] JavaScript syntax"
node --check frontend/js/api-client.js
node --check frontend/js/investigations.js

echo "[2/4] Python syntax"
"$PYTHON_BIN" -m py_compile backend/api/cleanhouse.py backend/evidence_context.py backend/vvault_preservation.py

echo "[3/4] Action menu and live table harness"
node --test tests/network_table_ctrl_resilience_node.test.mjs tests/network_resilience_node.test.mjs

echo "[4/4] Backend action, lifecycle, and VVAULT harness"
"$PYTHON_BIN" -m unittest \
  tests.test_network_header_static \
  tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_network_evidence_resolver_supports_all_actions_panel_sources \
  tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_evidence_actions_execute_with_idempotency_verification_and_vvault_receipts \
  tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_network_trend_projection_uses_vvault_history_when_local_cache_empty \
  tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_network_trend_projection_dedupes_local_and_vvault_ticks_by_tick_id \
  tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_network_contract_tags_are_shared_fixed_vocabulary

echo "PASS: Codex CLI action execution harness"
