#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/cleanhouse_env/bin/python3"
WRAPPER_SCRIPT="${REPO_ROOT}/desktop/wrapper.py"

if [ ! -x "${VENV_PYTHON}" ]; then
  echo "cleanhouse-raw: virtualenv python3 executable not found: ${VENV_PYTHON}" >&2
  exit 1
fi

if [ ! -r "${WRAPPER_SCRIPT}" ]; then
  echo "cleanhouse-raw: desktop wrapper not found: ${WRAPPER_SCRIPT}" >&2
  exit 1
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
exec "${VENV_PYTHON}" "${WRAPPER_SCRIPT}" "$@"
