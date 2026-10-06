#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOST="${CLEANHOUSE_HOST:-127.0.0.1}"
PORT="${CLEANHOUSE_PORT:-3333}"
URL="http://localhost:${PORT}/dashboard"
READY_ENDPOINT="http://127.0.0.1:${PORT}/cleanhouse/status?ready=1"
RUNTIME_ENDPOINT="http://127.0.0.1:${PORT}/cleanhouse/runtime"
STARTUP_TIMEOUT_SECONDS="${CLEANHOUSE_STARTUP_TIMEOUT_SECONDS:-30}"
RUNTIME_DIR="${CLEANHOUSE_RUNTIME_DIR:-$HOME/.cleanhouse/runtime}"
LAUNCH_LOG="${RUNTIME_DIR}/launcher.log"

resolve_bootstrap_python() {
  if [ -n "${CLEANHOUSE_PYTHON:-}" ] && [ -x "${CLEANHOUSE_PYTHON}" ]; then
    printf '%s\n' "${CLEANHOUSE_PYTHON}"
    return 0
  fi
  if [ -x "${RUNTIME_DIR}/python/bin/python3" ]; then
    printf '%s\n' "${RUNTIME_DIR}/python/bin/python3"
    return 0
  fi
  if [ -x "${REPO_ROOT}/cleanhouse_env/bin/python3" ]; then
    printf '%s\n' "${REPO_ROOT}/cleanhouse_env/bin/python3"
    return 0
  fi
  if [ -x "${REPO_ROOT}/.venv/bin/python3" ]; then
    printf '%s\n' "${REPO_ROOT}/.venv/bin/python3"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

BOOTSTRAP_PYTHON="$(resolve_bootstrap_python || true)"
if [ -z "${BOOTSTRAP_PYTHON}" ] || [ ! -x "${BOOTSTRAP_PYTHON}" ]; then
  echo "cleanhouse-up: bootstrap python3 executable not found." >&2
  exit 1
fi

CLEANHOUSE_PYTHON="$(cd "${REPO_ROOT}" && "${BOOTSTRAP_PYTHON}" -m backend.runtime_env print-path 2>/dev/null || true)"
if [ -z "${CLEANHOUSE_PYTHON}" ] || [ ! -x "${CLEANHOUSE_PYTHON}" ]; then
  CLEANHOUSE_PYTHON="${BOOTSTRAP_PYTHON}"
fi

case "${PORT}" in
  ''|*[!0-9]*)
    echo "cleanhouse-up: invalid CLEANHOUSE_PORT value: ${PORT}" >&2
    exit 1
    ;;
esac
if [ "${PORT}" -lt 1024 ] || [ "${PORT}" -gt 65535 ]; then
  echo "cleanhouse-up: invalid CLEANHOUSE_PORT value: ${PORT} (must be 1024-65535)." >&2
  exit 1
fi

cd "${REPO_ROOT}"
mkdir -p "${RUNTIME_DIR}"

probe_json() {
  local target="$1"
  local timeout="${2:-2}"
  "${CLEANHOUSE_PYTHON}" - "$target" "$timeout" <<'PY'
import json
import sys
from urllib.request import urlopen

url = sys.argv[1]
timeout = float(sys.argv[2])
with urlopen(url, timeout=timeout) as response:
    if response.getcode() != 200:
        raise SystemExit(1)
    json.loads(response.read().decode("utf-8") or "{}")
PY
}

open_local() {
  local target="$1"
  if command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1 || true
  fi
}

echo "$(date -u +%FT%T%z) cleanhouse-up: ensuring supervised runtime on ${HOST}:${PORT}" >>"${LAUNCH_LOG}"
START_STATUS=0
if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/launchctl ]; then
  "${CLEANHOUSE_PYTHON}" -m backend.launch_agent install \
    --interpreter "${CLEANHOUSE_PYTHON}" \
    --host "${HOST}" \
    --port "${PORT}" >>"${LAUNCH_LOG}" 2>&1 || START_STATUS=$?
else
  "${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor start \
    --host "${HOST}" \
    --port "${PORT}" \
    --timeout "${STARTUP_TIMEOUT_SECONDS}" >>"${LAUNCH_LOG}" 2>&1 || START_STATUS=$?
fi
if [ "${START_STATUS}" -ne 0 ]; then
  echo "cleanhouse-up: supervised runtime did not become authoritative." >&2
  echo "Runtime endpoint: ${RUNTIME_ENDPOINT}" >&2
  echo "Last 60 lines of ${LAUNCH_LOG}:" >&2
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

READY_DEADLINE=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
while ! probe_json "${READY_ENDPOINT}" 2; do
  if [ "${SECONDS}" -ge "${READY_DEADLINE}" ]; then
    break
  fi
  sleep 0.2
done
if ! probe_json "${READY_ENDPOINT}" 2; then
  echo "cleanhouse-up: readiness endpoint unavailable after supervisor start: ${READY_ENDPOINT}" >&2
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

if ! probe_json "${RUNTIME_ENDPOINT}" 4; then
  echo "cleanhouse-up: runtime endpoint unavailable after supervisor start: ${RUNTIME_ENDPOINT}" >&2
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

open_local "${URL}"
echo "cleanhouse is running at ${URL}"
