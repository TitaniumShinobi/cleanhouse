#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RAW_LAUNCHER="${SCRIPT_DIR}/cleanhouse-raw.sh"
LAUNCH_LOG="${TMPDIR:-/tmp}/cleanhouse-standalone.log"

HOST="${CLEANHOUSE_HOST:-127.0.0.1}"
PORT="${CLEANHOUSE_PORT:-3333}"
URL="http://localhost:${PORT}/dashboard"
READY_ENDPOINT="http://127.0.0.1:${PORT}/cleanhouse/status?ready=1"
RETRY_COUNT=40
RETRY_DELAY=0.5
STARTUP_TIMEOUT_SECONDS=30
READY_ERROR="ready endpoint unavailable"
READY_TIMEOUT_SECONDS=8

probe_endpoint() {
  local target="$1"
  local timeout="${2:-$READY_TIMEOUT_SECONDS}"
  local output

if output="$(python3 - "$target" "$timeout" <<'PY' 2>&1
import sys
import json
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

url = sys.argv[1]
timeout = float(sys.argv[2])
try:
    with urlopen(url, timeout=timeout) as response:
        if response.getcode() != 200:
            raise RuntimeError(f"bad status {response.getcode()}")
        payload = response.read()
        json.loads(payload.decode("utf-8"))
except (URLError, HTTPError, RuntimeError) as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
sys.exit(0)
PY
)"; then
    return 0
  fi

  if [ -n "$output" ]; then
    echo "$output"
  fi
  return 1
}

cleanhouse_ready() {
  local endpoint_output

  if endpoint_output="$(probe_endpoint "${READY_ENDPOINT}" "${READY_TIMEOUT_SECONDS}")"; then
    return 0
  fi

  if [ -n "${endpoint_output}" ]; then
    READY_ERROR="${endpoint_output}"
  else
    READY_ERROR="ready endpoint unavailable"
  fi
  return 1
}

check_listening() {
  local host="$1"
  local port="$2"
  local output

if output="$(python3 - "$host" "$port" <<'PY' 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.25)
    if sock.connect_ex((host, port)) != 0:
        raise SystemExit(1)
PY
)"; then
    return 0
  fi

  if [ -n "$output" ]; then
    READY_ERROR="$output"
  else
    READY_ERROR="port ${host}:${port} is not listening"
  fi
  return 1
}

wait_for_readiness() {
  local launcher_pid="${1-}"
  local attempt=0

  while [ "${attempt}" -lt "${RETRY_COUNT}" ]; do
    if ! check_listening "${HOST}" "${PORT}"; then
      attempt=$((attempt + 1))
      sleep "${RETRY_DELAY}"
      continue
    fi

    if [ -n "${launcher_pid}" ] && ! kill -0 "${launcher_pid}" >/dev/null 2>&1; then
      local launch_rc=1
      wait "${launcher_pid}" || launch_rc=$?
      READY_ERROR="launch command exited before readiness (status=${launch_rc})"
      return 1
    fi

    if cleanhouse_ready; then
      return 0
    fi

    attempt=$((attempt + 1))
    sleep "${RETRY_DELAY}"
  done

  READY_ERROR="startup timed out after ${STARTUP_TIMEOUT_SECONDS}s waiting for ${READY_ENDPOINT}"
  return 2
}

start_raw_launcher() {
  echo "$(date -u +%FT%T%z) cleanhouse-up: launching ${RAW_LAUNCHER}" >>"${LAUNCH_LOG}"
  nohup "${RAW_LAUNCHER}" >>"${LAUNCH_LOG}" 2>&1 < /dev/null &
  LAUNCH_PID=$!
  disown "${LAUNCH_PID}" >/dev/null 2>&1 || true
}

report_tail() {
  if [ -f "${LAUNCH_LOG}" ]; then
    tail -n 40 "${LAUNCH_LOG}" >&2
  fi
}

fail_with_log() {
  local reason="$1"
  if [ -n "${READY_ERROR}" ]; then
    echo "${reason}: ${READY_ERROR}" >&2
  else
    echo "${reason}" >&2
  fi
  echo "Last 40 lines of ${LAUNCH_LOG}:" >&2
  report_tail
  exit 1
}

open_local() {
  local target="$1"
  if command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m webbrowser "$target" >/dev/null 2>&1 || true
  fi
}

if check_listening "${HOST}" "${PORT}"; then
  if wait_for_readiness ""; then
    open_local "${URL}"
    echo "cleanhouse is running at ${URL}"
    exit 0
  fi
  fail_with_log "cleanhouse-up: existing process on ${HOST}:${PORT} is not serving ${READY_ENDPOINT}"
fi

start_raw_launcher

if [ -z "${LAUNCH_PID-}" ]; then
  echo "cleanhouse-up: failed to start launcher process." >&2
  exit 1
fi

if wait_for_readiness "${LAUNCH_PID}"; then
  open_local "${URL}"
  echo "cleanhouse is running at ${URL}"
  exit 0
fi
wait_rc=$?

if [ "${wait_rc}" -eq 1 ]; then
  fail_with_log "cleanhouse-up: launch command exited before readiness"
elif [[ "${READY_ERROR}" == launch\ command\ exited* ]]; then
  fail_with_log "cleanhouse-up: launch command exited before readiness"
else
  fail_with_log "cleanhouse-up: startup timed out after ${STARTUP_TIMEOUT_SECONDS}s"
fi
