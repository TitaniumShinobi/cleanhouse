#!/usr/bin/env bash

# Rebind these from this repo after any alias-mutating command
# (repo_make_aliases, repo_up, etc.).
SCRIPT_REF="${BASH_SOURCE[0]-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_REF}")" && pwd)"

cleanhouse_up_cmd="${SCRIPT_DIR}/cleanhouse-up.sh"
cleanhouse_raw_cmd="${SCRIPT_DIR}/cleanhouse-raw.sh"

if command -v unalias >/dev/null 2>&1; then
  unalias cleanhouse 2>/dev/null || true
  unalias cleanhouse-raw 2>/dev/null || true
fi

unset -f cleanhouse cleanhouse-raw 2>/dev/null || true

cleanhouse() {
  "${cleanhouse_up_cmd}" "$@"
}

cleanhouse-raw() {
  "${cleanhouse_raw_cmd}" "$@"
}
