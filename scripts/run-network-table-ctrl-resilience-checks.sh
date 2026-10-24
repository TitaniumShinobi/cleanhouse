#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/cleanhouse_env/bin/python3"

if [ -x "${VENV_PYTHON}" ]; then
  PYTHON_BIN="${VENV_PYTHON}"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "run-network-table-ctrl-resilience-checks: python3 executable not found" >&2
  exit 1
fi

NODE_BIN="$(command -v node || true)"
if [ -z "${NODE_BIN}" ]; then
  echo "run-network-table-ctrl-resilience-checks: node executable not found" >&2
  exit 1
fi

cd "${REPO_ROOT}"

"${NODE_BIN}" --check frontend/js/investigations.js
"${PYTHON_BIN}" -m unittest tests.test_network_header_static tests.test_ctrl_panel_static
"${NODE_BIN}" --test tests/network_table_ctrl_resilience_node.test.mjs

echo "network-table-ctrl-resilience: pass"
