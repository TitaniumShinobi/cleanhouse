#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOST="${CLEANHOUSE_HOST:-127.0.0.1}"
PORT="${CLEANHOUSE_PORT:-3333}"
BROWSER_HOST="${CLEANHOUSE_BROWSER_HOST:-localhost}"
URL="http://${BROWSER_HOST}:${PORT}/overview"
READY_ENDPOINT="http://${HOST}:${PORT}/cleanhouse/status?ready=1"
# Full operator readiness includes the bounded collectors and preservation
# warmup. A cold managed runtime can legitimately need around two minutes;
# stopping it after 30 seconds creates a false restart loop while it is healthy.
STARTUP_TIMEOUT_SECONDS="${CLEANHOUSE_STARTUP_TIMEOUT_SECONDS:-180}"
RUNTIME_DIR="${CLEANHOUSE_RUNTIME_DIR:-$HOME/.cleanhouse/runtime}"
WATCH_DIR="${CLEANHOUSE_WATCH_DIR:-${REPO_ROOT}}"
LAUNCH_LOG="${RUNTIME_DIR}/launcher.log"
CLEANHOUSE_OPEN_BROWSER="${CLEANHOUSE_OPEN_BROWSER:-1}"
# Running this operator command is the explicit manual confirmation required
# after a preserved self-deviation. Port/process safety is still enforced by
# preflight before any restart is attempted.
ACKNOWLEDGE_SELF_DEVIATION=0

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export CLEANHOUSE_RUNTIME_DIR="${RUNTIME_DIR}"
# Source-side preflight and the staged LaunchAgent must persist receipts under
# the same macOS-safe application-data root. Without this export, an
# acknowledgement falls back to Documents and fails under background privacy.
export CLEANHOUSE_DATA_ROOT="${CLEANHOUSE_DATA_ROOT:-${RUNTIME_DIR}/data}"

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

probe_readiness() {
  local target="$1"
  local timeout="${2:-2}"
  local diagnostic="${3:-0}"
  "${CLEANHOUSE_PYTHON}" - "$target" "$timeout" "$diagnostic" <<'PY'
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

url = sys.argv[1]
timeout = float(sys.argv[2])
diagnostic = sys.argv[3] == "1"
max_response_bytes = 64 * 1024
max_diagnostic_items = 8
max_diagnostic_text = 160
required_checks = {
    "runtime_healthy",
    "startup_warm",
    "backend_alive",
    "supervisor_alive",
    "heartbeat_fresh",
    "readiness_probe_ok",
    "single_owned_listener",
    "listener_matches_backend",
    "no_foreign_listener",
    "no_self_deviation_block",
    "no_resource_guard_block",
}
try:
    with urlopen(url, timeout=timeout) as response:
        if response.getcode() != 200:
            raise SystemExit(1)
        raw = response.read(max_response_bytes + 1)
        if len(raw) > max_response_bytes:
            if diagnostic:
                print("Readiness probe failed: response exceeded 65536 bytes", file=sys.stderr)
            raise SystemExit(1)
        payload = json.loads(raw.decode("utf-8") or "{}")
except (HTTPError, OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    # Connection refusal is expected for a bounded moment after launchd
    # replaces the supervised process. Keep readiness retries quiet; the
    # launcher emits a concise diagnostic only if the deadline expires.
    if diagnostic:
        print(f"Readiness probe failed: {exc.__class__.__name__}", file=sys.stderr)
    raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)
contract = payload.get("readiness_contract")
checks = contract.get("checks") if isinstance(contract, dict) else None
failed_checks = contract.get("failed_checks") if isinstance(contract, dict) else None
reason_codes = payload.get("reason_codes")
valid = (
    payload.get("status") == "ok"
    and payload.get("ready") is True
    and payload.get("bootstrap_ready") is True
    and payload.get("runtime_state") == "healthy"
    and isinstance(reason_codes, list)
    and all(isinstance(reason, str) for reason in reason_codes)
    and isinstance(contract, dict)
    and contract.get("schema") == "cleanhouse.runtime_operator_readiness.v1"
    and contract.get("satisfied") is True
    and contract.get("required_runtime_state") == "healthy"
    and contract.get("required_startup_phases") == ["warm"]
    and isinstance(checks, dict)
    and set(checks) == required_checks
    and all(checks.get(name) is True for name in required_checks)
    and failed_checks == []
)
if valid:
    raise SystemExit(0)
if diagnostic:
    def bounded_items(value):
        if not isinstance(value, list):
            return ["invalid"]
        return [str(item)[:max_diagnostic_text] for item in value[:max_diagnostic_items]]

    print("Canonical readiness contract was not satisfied.", file=sys.stderr)
    print(f"Runtime state: {str(payload.get('runtime_state') or 'unknown')[:max_diagnostic_text]}", file=sys.stderr)
    print(f"Failed checks: {bounded_items(failed_checks)}", file=sys.stderr)
    if reason_codes:
        print(f"Reason codes: {bounded_items(reason_codes)}", file=sys.stderr)
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
    --port "${PORT}" \
    --watch-root "${WATCH_DIR}" 2>>"${LAUNCH_LOG}")"
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
  echo "Readiness endpoint: ${READY_ENDPOINT}" >&2
  render_runtime_failure_payload "${START_JSON}" || true
  # The start command did not establish ownership of a new generation.  It may
  # have observed or rolled back to a pre-existing runtime, so do not stop it.
  echo "Last 60 lines of ${LAUNCH_LOG}:" >&2
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

READY_DEADLINE=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
while ! probe_readiness "${READY_ENDPOINT}" 2; do
  if [ "${SECONDS}" -ge "${READY_DEADLINE}" ]; then
    break
  fi
  sleep 0.2
done
if ! probe_readiness "${READY_ENDPOINT}" 2; then
  echo "cleanhouse-up: readiness endpoint unavailable after supervisor start: ${READY_ENDPOINT}" >&2
  probe_readiness "${READY_ENDPOINT}" 2 1 || true
  # Readiness failure is observational. The launcher has no atomic,
  # generation-conditional stop API, so leave lifecycle decisions to the
  # existing supervisor rather than risk stopping a replacement generation.
  tail -n 60 "${LAUNCH_LOG}" >&2 || true
  exit 1
fi

open_local "${URL}"
echo "cleanhouse is running at ${URL}"
