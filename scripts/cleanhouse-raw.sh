#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOST="${CLEANHOUSE_HOST:-127.0.0.1}"
PORT="${CLEANHOUSE_PORT:-3333}"

resolve_bootstrap_python() {
  if [ -n "${CLEANHOUSE_PYTHON:-}" ] && [ -x "${CLEANHOUSE_PYTHON}" ]; then
    printf '%s\n' "${CLEANHOUSE_PYTHON}"
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
  echo "cleanhouse-raw: bootstrap python3 executable not found." >&2
  exit 1
fi

CLEANHOUSE_PYTHON="$(cd "${REPO_ROOT}" && "${BOOTSTRAP_PYTHON}" -m backend.runtime_env print-path 2>/dev/null || true)"
if [ -z "${CLEANHOUSE_PYTHON}" ] || [ ! -x "${CLEANHOUSE_PYTHON}" ]; then
  CLEANHOUSE_PYTHON="${BOOTSTRAP_PYTHON}"
fi

if [ -n "${CLEANHOUSE_PORT+x}" ]; then
  case "${CLEANHOUSE_PORT}" in
    ''|*[!0-9]*)
      echo "cleanhouse-raw: invalid CLEANHOUSE_PORT value: ${CLEANHOUSE_PORT}" >&2
      exit 1
      ;;
  esac

  if [ "${CLEANHOUSE_PORT}" -lt 1024 ] || [ "${CLEANHOUSE_PORT}" -gt 65535 ]; then
    echo "cleanhouse-raw: invalid CLEANHOUSE_PORT value: ${CLEANHOUSE_PORT} (must be 1024-65535)." >&2
    exit 1
  fi
fi

cd "${REPO_ROOT}"
exec "${CLEANHOUSE_PYTHON}" -m backend.runtime_supervisor supervise --host "${HOST}" --port "${PORT}" "$@"
