#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOST="${CLEANHOUSE_HOST:-localhost}"
PORT="${CLEANHOUSE_PORT:-3333}"
URL="http://${HOST}:${PORT}/overview"
READY_ENDPOINT="http://${HOST}:${PORT}/cleanhouse/status?ready=1"
RUNTIME_ENDPOINT="http://${HOST}:${PORT}/cleanhouse/runtime"
STARTUP_TIMEOUT_SECONDS="${CLEANHOUSE_STARTUP_TIMEOUT_SECONDS:-5}"
RUNTIME_DIR="${CLEANHOUSE_RUNTIME_DIR:-$HOME/.cleanhouse/runtime}"
LAUNCH_LOG="${RUNTIME_DIR}/launcher.log"
CLEANHOUSE_OPEN_BROWSER="${CLEANHOUSE_OPEN_BROWSER:-1}"
ACKNOWLEDGE_SELF_DEVIATION=0

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --acknowledge-self-deviation)
      ACKNOWLEDGE_SELF_DEVIATION=1
      shift
      ;;
    *)
      echo "cleanhouse-up: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

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
from urllib.error import URLError
from urllib.request import urlopen

url = sys.argv[1]
timeout = float(sys.argv[2])
try:
    with urlopen(url, timeout=timeout) as response:
        if response.getcode() != 200:
            raise SystemExit(1)
        json.loads(response.read().decode("utf-8") or "{}")
except (OSError, URLError, json.JSONDecodeError):
    # Connection refusal is expected for a bounded moment after launchd
    # replaces the supervised process. Keep readiness retries quiet; the
    # launcher emits a concise diagnostic only if the deadline expires.
    raise SystemExit(1)
PY
}

probe_runtime_safe() {
  local target="$1"
  local timeout="${2:-4}"
  "${CLEANHOUSE_PYTHON}" - "$target" "$timeout" <<'PY'
import json
import sys
from urllib.request import urlopen

url = sys.argv[1]
timeout = float(sys.argv[2])
with urlopen(url, timeout=timeout) as response:
    if response.getcode() != 200:
        print(f"runtime endpoint returned HTTP {response.getcode()}", file=sys.stderr)
        raise SystemExit(1)
    payload = json.loads(response.read().decode("utf-8") or "{}")

resource_guard = payload.get("resource_guard") if isinstance(payload.get("resource_guard"), dict) else {}
self_deviation = payload.get("self_deviation") if isinstance(payload.get("self_deviation"), dict) else {}
finding = self_deviation.get("finding") if isinstance(self_deviation.get("finding"), dict) else {}
runtime_state = payload.get("runtime_state") or payload.get("status")
guard_status = resource_guard.get("status") or "unknown"
operator_ready = bool(payload.get("operator_ready"))
unsafe_runtime_states = {"unhealthy", "stale_pid", "orphaned_listener"}
if operator_ready and runtime_state not in unsafe_runtime_states and guard_status == "ok":
    raise SystemExit(0)

print("Runtime safety check failed.", file=sys.stderr)
print(f"Runtime state: {runtime_state or 'unknown'}", file=sys.stderr)
print(f"Operator ready: {operator_ready}", file=sys.stderr)
print(f"Resource guard: {guard_status}", file=sys.stderr)
reason_codes = payload.get("reason_codes") or resource_guard.get("reason_codes") or []
if reason_codes:
    print(f"Reason codes: {', '.join(str(reason) for reason in reason_codes)}", file=sys.stderr)
usage = resource_guard.get("usage") if isinstance(resource_guard.get("usage"), dict) else {}
if usage:
    rss = usage.get("rss_mb")
    cpu = usage.get("cpu_percent")
    pid = usage.get("pid")
    print(f"Usage: pid={pid or 'unknown'} rss_mb={rss if rss is not None else 'unknown'} cpu_percent={cpu if cpu is not None else 'unknown'}", file=sys.stderr)
if finding.get("title") or self_deviation.get("title"):
    print(f"Finding: {finding.get('title') or self_deviation.get('title')}", file=sys.stderr)
if self_deviation.get("next_action") or finding.get("next_action"):
    print(f"Next action: {self_deviation.get('next_action') or finding.get('next_action')}", file=sys.stderr)
if self_deviation.get("evidence_artifact_path"):
    print(f"Evidence: {self_deviation['evidence_artifact_path']}", file=sys.stderr)
if self_deviation.get("receipt_artifact_path"):
    print(f"Receipt: {self_deviation['receipt_artifact_path']}", file=sys.stderr)
raise SystemExit(1)
PY
}

open_local() {
  local target="$1"
  if [ "${CLEANHOUSE_OPEN_BROWSER}" = "0" ]; then
    return 0
  fi
  if command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1 || true
  fi
}

render_blocked_preflight() {
  local payload="$1"
  "${CLEANHOUSE_PYTHON}" - "$payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
status = payload.get("status")
if status == "blocked_self_deviation":
    self_deviation = payload.get("self_deviation") or {}
    finding = self_deviation.get("finding") or {}
    print("cleanhouse-up: current runtime state is unsafe; refusing automatic restart.", file=sys.stderr)
    if finding.get("title") or self_deviation.get("title"):
        print(f"Finding: {finding.get('title') or self_deviation.get('title')}", file=sys.stderr)
    if self_deviation.get("next_action") or payload.get("next_action"):
        print(f"Next action: {self_deviation.get('next_action') or payload.get('next_action')}", file=sys.stderr)
    if self_deviation.get("evidence_artifact_path"):
        print(f"Evidence: {self_deviation['evidence_artifact_path']}", file=sys.stderr)
    if self_deviation.get("receipt_artifact_path"):
        print(f"Receipt: {self_deviation['receipt_artifact_path']}", file=sys.stderr)
    print("Resolve the current port/process condition, then try cleanhouse again.", file=sys.stderr)
elif status == "foreign_listener_blocked":
    listener = payload.get("listener") or {}
    print("cleanhouse-up: port is already owned by another process; refusing to start.", file=sys.stderr)
    print(f"Foreign listener pids: {listener.get('foreign_pids') or []}", file=sys.stderr)
    print(f"Next action: {payload.get('next_action')}", file=sys.stderr)
else:
    print(f"cleanhouse-up: startup preflight failed: {status or 'unknown'}", file=sys.stderr)
    if payload.get("error"):
        print(f"Error: {payload['error']}", file=sys.stderr)
    print(f"Next action: {payload.get('next_action') or 'Inspect runtime state before restarting.'}", file=sys.stderr)
PY
}

render_startup_warning() {
  local payload="$1"
  case "${CLEANHOUSE_SHOW_RECOVERABLE_SELF_DEVIATION:-}" in
    1|true|TRUE|yes|YES|on|ON) ;;
    *) return 0 ;;
  esac
  "${CLEANHOUSE_PYTHON}" - "$payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1] or "{}")
warning = payload.get("startup_warning") if isinstance(payload.get("startup_warning"), dict) else {}
if warning.get("type") != "recoverable_self_deviation":
    raise SystemExit(0)
self_deviation = warning.get("self_deviation") if isinstance(warning.get("self_deviation"), dict) else {}
finding = self_deviation.get("finding") if isinstance(self_deviation.get("finding"), dict) else {}
message = self_deviation.get("message") or warning.get("message") or "Previous CleanHouse runtime self-deviation remains available for review; startup is allowed."
print(f"cleanhouse-up: {message}", file=sys.stderr)
if finding.get("title") or self_deviation.get("title"):
    print(f"Finding: {finding.get('title') or self_deviation.get('title')}", file=sys.stderr)
if self_deviation.get("evidence_artifact_path"):
    print(f"Evidence: {self_deviation['evidence_artifact_path']}", file=sys.stderr)
if self_deviation.get("receipt_artifact_path"):
    print(f"Receipt: {self_deviation['receipt_artifact_path']}", file=sys.stderr)
PY
}

render_runtime_failure_payload() {
  local payload="$1"
  "${CLEANHOUSE_PYTHON}" - "$payload" <<'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1] or "{}")
except json.JSONDecodeError:
    raise SystemExit(1)

if not isinstance(payload, dict) or not payload:
    raise SystemExit(1)

resource_guard = payload.get("resource_guard") if isinstance(payload.get("resource_guard"), dict) else {}
self_deviation = payload.get("self_deviation") if isinstance(payload.get("self_deviation"), dict) else {}
finding = self_deviation.get("finding") if isinstance(self_deviation.get("finding"), dict) else {}
print(f"Runtime state: {payload.get('runtime_state') or payload.get('status') or 'unknown'}", file=sys.stderr)
reason_codes = payload.get("reason_codes") or resource_guard.get("reason_codes") or []
if reason_codes:
    print(f"Reason codes: {', '.join(str(reason) for reason in reason_codes)}", file=sys.stderr)
if resource_guard:
    print(f"Resource guard: {resource_guard.get('status') or 'unknown'}", file=sys.stderr)
    usage = resource_guard.get("usage") if isinstance(resource_guard.get("usage"), dict) else {}
    if usage:
        print(
            "Usage: "
            f"pid={usage.get('pid') or 'unknown'} "
            f"rss_mb={usage.get('rss_mb') if usage.get('rss_mb') is not None else 'unknown'} "
            f"cpu_percent={usage.get('cpu_percent') if usage.get('cpu_percent') is not None else 'unknown'}",
            file=sys.stderr,
        )
if finding.get("title") or self_deviation.get("title"):
    print(f"Finding: {finding.get('title') or self_deviation.get('title')}", file=sys.stderr)
if self_deviation.get("next_action") or finding.get("next_action"):
    print(f"Next action: {self_deviation.get('next_action') or finding.get('next_action')}", file=sys.stderr)
if self_deviation.get("evidence_artifact_path"):
    print(f"Evidence: {self_deviation['evidence_artifact_path']}", file=sys.stderr)
if self_deviation.get("receipt_artifact_path"):
    print(f"Receipt: {self_deviation['receipt_artifact_path']}", file=sys.stderr)
PY
}

echo "$(date -u +%FT%T%z) cleanhouse-up: ensuring supervised runtime on ${HOST}:${PORT}" >>"${LAUNCH_LOG}"
PREFLIGHT_ARGS=(preflight --host "${HOST}" --port "${PORT}")
if [ "${ACKNOWLEDGE_SELF_DEVIATION}" = "1" ]; then
  PREFLIGHT_ARGS+=(--acknowledge-self-deviation)
fi

PREFLIGHT_JSON=""
set +e
PREFLIGHT_JSON="$("${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor "${PREFLIGHT_ARGS[@]}" 2>>"${LAUNCH_LOG}")"
PREFLIGHT_STATUS=$?
set -e
printf '%s\n' "${PREFLIGHT_JSON}" >>"${LAUNCH_LOG}"
if [ "${PREFLIGHT_STATUS}" -ne 0 ]; then
  render_blocked_preflight "${PREFLIGHT_JSON}"
  # Preflight is observational.  A blocked restart must not unload an existing
  # LaunchAgent or stop a live runtime that this invocation did not start.
  exit 1
fi
render_startup_warning "${PREFLIGHT_JSON}"

START_JSON=""
set +e
if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/launchctl ]; then
  START_JSON="$("${CLEANHOUSE_PYTHON}" -m backend.launch_agent install \
    --interpreter "${CLEANHOUSE_PYTHON}" \
    --host "${HOST}" \
    --port "${PORT}" 2>>"${LAUNCH_LOG}")"
else
  START_JSON="$("${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor start \
    --host "${HOST}" \
    --port "${PORT}" \
    --timeout "${STARTUP_TIMEOUT_SECONDS}" 2>>"${LAUNCH_LOG}")"
fi
START_STATUS=$?
set -e
printf '%s\n' "${START_JSON}" >>"${LAUNCH_LOG}"
if [ "${START_STATUS}" -ne 0 ]; then
  echo "cleanhouse-up: supervised runtime did not become authoritative." >&2
  echo "Runtime endpoint: ${RUNTIME_ENDPOINT}" >&2
  render_runtime_failure_payload "${START_JSON}" || true
  if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/launchctl ]; then
    "${CLEANHOUSE_PYTHON}" -m backend.launch_agent stop >>"${LAUNCH_LOG}" 2>&1 || true
  else
    "${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor stop --host "${HOST}" --port "${PORT}" >>"${LAUNCH_LOG}" 2>&1 || true
  fi
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
  if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/launchctl ]; then
    "${CLEANHOUSE_PYTHON}" -m backend.launch_agent stop >>"${LAUNCH_LOG}" 2>&1 || true
  else
    "${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor stop --host "${HOST}" --port "${PORT}" >>"${LAUNCH_LOG}" 2>&1 || true
  fi
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

SAFETY_OUTPUT=""
set +e
SAFETY_OUTPUT="$(probe_runtime_safe "${RUNTIME_ENDPOINT}" 4 2>&1)"
SAFETY_STATUS=$?
set -e
if [ "${SAFETY_STATUS}" -ne 0 ]; then
  echo "cleanhouse-up: runtime failed safety check after supervisor start." >&2
  if [ -n "${SAFETY_OUTPUT}" ]; then
    printf '%s\n' "${SAFETY_OUTPUT}" >&2
  else
    echo "Runtime endpoint: ${RUNTIME_ENDPOINT}" >&2
  fi
  "${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor stop --host "${HOST}" --port "${PORT}" >>"${LAUNCH_LOG}" 2>&1 || true
  exit 1
fi

open_local "${URL}"
echo "cleanhouse is running at ${URL}"
