#!/usr/bin/env bash

set -euo pipefail
umask 077

WAZUH_VERSION="4.14.7"
MANAGER_PACKAGE="${CLEANHOUSE_WAZUH_MANAGER_PACKAGE:-}"
MANAGER_SHA512="${CLEANHOUSE_WAZUH_MANAGER_SHA512:-}"
VVAULT_REPO="${VVAULT_REPO:-/opt/vvault-public}"
VVAULT_SERVICE="${VVAULT_SERVICE:-vvault-backend.service}"
VVAULT_SERVICE_USER="${VVAULT_SERVICE_USER:-vvault}"
API_CONFIG="/var/ossec/api/configuration/api.yaml"
ALERTS_JSON="/var/ossec/logs/alerts/alerts.json"

fail() {
  printf 'deploy-wazuh-stack: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

assert_loopback_listener() {
  local port="$1"
  local listeners
  listeners="$(ss -H -lnt "sport = :${port}" 2>/dev/null || true)"
  [ -n "${listeners}" ] || fail "expected listener on TCP ${port} is absent"
  if printf '%s\n' "${listeners}" | awk '{print $4}' | grep -Ev '^(127\.0\.0\.1|\[::1\]):' >/dev/null; then
    fail "TCP ${port} is exposed beyond loopback"
  fi
}

[ "$(uname -s)" = "Linux" ] || fail "the existing VVAULT Linux host is required"
[ "${EUID}" -eq 0 ] || fail "run explicitly as root on the approved VVAULT host"
[ -d "${VVAULT_REPO}" ] || fail "the existing VVAULT repository is absent"

for command_name in awk dpkg dpkg-deb dpkg-query getent grep id sed sha512sum ss systemctl usermod; do
  require_command "${command_name}"
done

for forbidden_package in wazuh-indexer wazuh-dashboard filebeat; do
  if dpkg-query -W -f='${Status}' "${forbidden_package}" 2>/dev/null | grep -Fq 'install ok installed'; then
    fail "forbidden separate data-plane package is installed: ${forbidden_package}"
  fi
done

[ -n "${MANAGER_PACKAGE}" ] || fail "CLEANHOUSE_WAZUH_MANAGER_PACKAGE is required"
[ -f "${MANAGER_PACKAGE}" ] || fail "the staged official Wazuh manager package does not exist"
[ -n "${MANAGER_SHA512}" ] || fail "CLEANHOUSE_WAZUH_MANAGER_SHA512 is required"

actual_sha512="$(sha512sum "${MANAGER_PACKAGE}" | awk '{print tolower($1)}')"
expected_sha512="$(printf '%s' "${MANAGER_SHA512}" | tr 'A-F' 'a-f')"
[ "${actual_sha512}" = "${expected_sha512}" ] || fail "Wazuh manager package checksum mismatch"

package_name="$(dpkg-deb -f "${MANAGER_PACKAGE}" Package)"
package_version="$(dpkg-deb -f "${MANAGER_PACKAGE}" Version)"
[ "${package_name}" = "wazuh-manager" ] || fail "staged package is not wazuh-manager"
[ "${package_version%%-*}" = "${WAZUH_VERSION}" ] || fail "staged wazuh-manager is not ${WAZUH_VERSION}"

installed_status="$(dpkg-query -W -f='${Status}' wazuh-manager 2>/dev/null || true)"
installed_version="$(dpkg-query -W -f='${Version}' wazuh-manager 2>/dev/null || true)"
if [ "${installed_status}" = "install ok installed" ]; then
  [ "${installed_version%%-*}" = "${WAZUH_VERSION}" ] || fail "installed wazuh-manager version does not match ${WAZUH_VERSION}"
elif [ -n "${installed_status}" ]; then
  fail "a partial wazuh-manager installation already exists"
else
  dpkg -i "${MANAGER_PACKAGE}"
fi

[ -f "${API_CONFIG}" ] || fail "Wazuh manager API configuration is missing"
if grep -Eq '^[[:space:]#]*host:[[:space:]]*' "${API_CONFIG}"; then
  sed -i -E "0,/^[[:space:]#]*host:[[:space:]].*/s//host: ['127.0.0.1']/" "${API_CONFIG}"
else
  printf "\nhost: ['127.0.0.1']\n" >>"${API_CONFIG}"
fi

id "${VVAULT_SERVICE_USER}" >/dev/null 2>&1 || fail "VVAULT service user does not exist"
getent group wazuh >/dev/null 2>&1 || fail "wazuh group does not exist"
usermod -a -G wazuh "${VVAULT_SERVICE_USER}"

systemctl enable wazuh-manager
systemctl restart wazuh-manager
systemctl is-active --quiet wazuh-manager || fail "wazuh-manager is not active"
assert_loopback_listener 55000
[ -e "${ALERTS_JSON}" ] || fail "Wazuh JSON alert stream is absent"

systemctl restart "${VVAULT_SERVICE}"
systemctl is-active --quiet "${VVAULT_SERVICE}" || fail "VVAULT backend is not active"

printf '%s\n' \
  "deploy-wazuh-stack: Wazuh manager ${WAZUH_VERSION} is running on the existing VVAULT host" \
  "deploy-wazuh-stack: no indexer, dashboard, Filebeat, container, or database was created" \
  "deploy-wazuh-stack: manager API 55000 is loopback-only" \
  "deploy-wazuh-stack: VVAULT can read manager evidence through its wazuh group membership"
