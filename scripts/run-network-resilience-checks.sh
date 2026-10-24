#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/cleanhouse_env/bin/python3"
STATIC_ONLY=0
RUN_LIVE="${CLEANHOUSE_NETWORK_RESILIENCE_LIVE:-0}"
REPEAT="${CLEANHOUSE_NETWORK_RESILIENCE_REPEAT:-1}"
BASE_URL="${CLEANHOUSE_NETWORK_BASE_URL:-http://127.0.0.1:3333}"
SMOKE_ITERATIONS="${CLEANHOUSE_NETWORK_RESILIENCE_ITERATIONS:-6}"
SMOKE_SLEEP_SECONDS="${CLEANHOUSE_NETWORK_RESILIENCE_SLEEP_SECONDS:-1.0}"
SMOKE_LATENCY_THRESHOLD_MS="${CLEANHOUSE_NETWORK_RESILIENCE_LATENCY_THRESHOLD_MS:-1200}"
SMOKE_SPIKE_BUDGET="${CLEANHOUSE_NETWORK_RESILIENCE_SPIKE_BUDGET:-2}"

if [ -x "${VENV_PYTHON}" ]; then
  PYTHON_BIN="${VENV_PYTHON}"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "run-network-resilience-checks: python3 executable not found" >&2
  exit 1
fi

NODE_BIN="$(command -v node || true)"
if [ -z "${NODE_BIN}" ]; then
  echo "run-network-resilience-checks: node executable not found" >&2
  exit 1
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --static-only)
      STATIC_ONLY=1
      RUN_LIVE=0
      shift
      ;;
    --live)
      RUN_LIVE=1
      shift
      ;;
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --base-url=*)
      BASE_URL="${1#*=}"
      shift
      ;;
    --repeat)
      REPEAT="${2:-}"
      shift 2
      ;;
    --repeat=*)
      REPEAT="${1#*=}"
      shift
      ;;
    --iterations)
      SMOKE_ITERATIONS="${2:-}"
      shift 2
      ;;
    --iterations=*)
      SMOKE_ITERATIONS="${1#*=}"
      shift
      ;;
    --sleep-seconds)
      SMOKE_SLEEP_SECONDS="${2:-}"
      shift 2
      ;;
    --sleep-seconds=*)
      SMOKE_SLEEP_SECONDS="${1#*=}"
      shift
      ;;
    --latency-threshold-ms)
      SMOKE_LATENCY_THRESHOLD_MS="${2:-}"
      shift 2
      ;;
    --latency-threshold-ms=*)
      SMOKE_LATENCY_THRESHOLD_MS="${1#*=}"
      shift
      ;;
    --spike-budget)
      SMOKE_SPIKE_BUDGET="${2:-}"
      shift 2
      ;;
    --spike-budget=*)
      SMOKE_SPIKE_BUDGET="${1#*=}"
      shift
      ;;
    *)
      echo "run-network-resilience-checks: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "${REPEAT}" in
  ''|*[!0-9]*)
    echo "run-network-resilience-checks: --repeat must be a positive integer" >&2
    exit 2
    ;;
esac

if [ "${REPEAT}" -lt 1 ]; then
  echo "run-network-resilience-checks: --repeat must be a positive integer" >&2
  exit 2
fi

cd "${REPO_ROOT}"

run_static_checks() {
  "${PYTHON_BIN}" -m unittest tests.test_network_header_static
  "${NODE_BIN}" --test tests/network_resilience_node.test.mjs
}

run_live_smoke() {
  "${PYTHON_BIN}" scripts/network_resilience_smoke.py \
    --base-url "${BASE_URL}" \
    --iterations "${SMOKE_ITERATIONS}" \
    --sleep-seconds "${SMOKE_SLEEP_SECONDS}" \
    --latency-threshold-ms "${SMOKE_LATENCY_THRESHOLD_MS}" \
    --spike-budget "${SMOKE_SPIKE_BUDGET}"
}

for run_number in $(seq 1 "${REPEAT}"); do
  echo "network-resilience: static stale-state checks ${run_number}/${REPEAT}"
  run_static_checks
  if [ "${STATIC_ONLY}" -eq 0 ] && [ "${RUN_LIVE}" = "1" ]; then
    echo "network-resilience: live endpoint smoke ${run_number}/${REPEAT} ${BASE_URL}"
    run_live_smoke
  fi
done

echo "network-resilience: pass"
