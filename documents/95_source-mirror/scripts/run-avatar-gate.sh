#!/usr/bin/env bash

set -euo pipefail

SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/cleanhouse_env/bin/python3"
GATE_SCRIPT="${SCRIPT_DIR}/avatar_receipt_regression_gate.py"

if [ -x "${VENV_PYTHON}" ]; then
  PYTHON_BIN="${VENV_PYTHON}"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "run-avatar-gate: python3 executable not found" >&2
  exit 1
fi

if [ ! -r "${GATE_SCRIPT}" ]; then
  echo "run-avatar-gate: regression gate not found: ${GATE_SCRIPT}" >&2
  exit 1
fi

has_artifact_dir=0
for arg in "$@"; do
  case "${arg}" in
    --artifact-dir|--artifact-dir=*)
      has_artifact_dir=1
      ;;
  esac
done

extra_args=()
if [ "${has_artifact_dir}" -eq 0 ] && [ -n "${CLEANHOUSE_AVATAR_GATE_ARTIFACT_DIR:-}" ]; then
  extra_args=(--artifact-dir "${CLEANHOUSE_AVATAR_GATE_ARTIFACT_DIR}")
fi

cd "${REPO_ROOT}"
if [ "${#extra_args[@]}" -gt 0 ]; then
  exec "${PYTHON_BIN}" "${GATE_SCRIPT}" "$@" "${extra_args[@]}"
fi
exec "${PYTHON_BIN}" "${GATE_SCRIPT}" "$@"
