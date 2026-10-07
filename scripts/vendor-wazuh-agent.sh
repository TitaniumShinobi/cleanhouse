#!/usr/bin/env bash

set -euo pipefail

VERSION="4.14.7"
PACKAGE="wazuh-agent-${VERSION}-1.arm64.pkg"
SOURCE_ARCHIVE="wazuh-${VERSION}-source.tar.gz"
OFFICIAL_PACKAGE_SHA512="9d1dbf1a0e440d8a1f6f75d44a30a395442926b01208ee8b88821e6d21a6b1ea5b885fd0c389df999a089bebda741e1af76cf9f773d552612430664da9428b11"
OFFICIAL_SOURCE_SHA512="d6182330f74ff249bfd8ff2f6a6f7934b6c5df9c53a8e5955cd42c0aa36fb25cabaef2dce2dd6241f6eb979b85fc6f87067e9f5c19069eea940aa6f127e61c09"
OFFICIAL_SIGNER="Wazuh Inc (KLZK8P68R5)"
OFFICIAL_SIGNER_FINGERPRINT="A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E"
OFFICIAL_NOTARIZATION="trusted by the Apple notary service"
REPO_ROOT="${CLEANHOUSE_WAZUH_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DESTINATION="${REPO_ROOT}/bundled/wazuh/darwin-arm64"
PACKAGE_URL="https://packages.wazuh.com/4.x/macos/${PACKAGE}"
CHECKSUM_URL="https://packages.wazuh.com/4.x/checksums/wazuh/${VERSION}/${PACKAGE}.sha512"
LICENSE_URL="https://raw.githubusercontent.com/wazuh/wazuh/v${VERSION}/LICENSE"
SOURCE_URL="https://github.com/wazuh/wazuh/archive/refs/tags/v${VERSION}.tar.gz"

STAGE_DIR=""
PACKAGE_STAGE=""

cleanup() {
  if [ -n "${STAGE_DIR}" ]; then
    rm -rf -- "${STAGE_DIR}"
  fi
}

verify_signature_file() {
  local signature_path="$1"
  local pkgutil_status="$2"
  local first_signer notarization signer_block compact_block

  if [ "${pkgutil_status}" -ne 0 ]; then
    echo "Wazuh package signature verification failed." >&2
    return 1
  fi

  first_signer="$(sed -n 's/^[[:space:]]*[0-9][0-9]*\. Developer ID Installer: //p' "${signature_path}" | head -n 1)"
  if [ "${first_signer}" != "${OFFICIAL_SIGNER}" ]; then
    echo "Pinned Wazuh package signer verification failed." >&2
    return 1
  fi

  notarization="$(sed -n 's/^[[:space:]]*Notarization: //p' "${signature_path}" | head -n 1)"
  if [ "${notarization}" != "${OFFICIAL_NOTARIZATION}" ]; then
    echo "Wazuh package notarization verification failed." >&2
    return 1
  fi

  signer_block="$(awk '
    /^[[:space:]]*[0-9][0-9]*\. Developer ID Installer:/ { if (!capture) capture = 1 }
    capture { print }
    capture && /----------/ { exit }
  ' "${signature_path}")"
  compact_block="$(printf '%s' "${signer_block}" | tr -d '[:space:]')"
  if [[ "${compact_block}" != *"SHA256Fingerprint:${OFFICIAL_SIGNER_FINGERPRINT}"* ]]; then
    echo "Pinned Wazuh package signer fingerprint verification failed." >&2
    return 1
  fi
}

verify_staged_artifacts() {
  local package_path="$1"
  local checksum_path="$2"
  local source_path="$3"
  local signature_path="$4"
  local pkgutil_status="$5"
  local published_package_sha512 actual_package_sha512 actual_source_sha512

  published_package_sha512="$(tr 'A-F' 'a-f' < "${checksum_path}" | grep -Eo '[0-9a-f]{128}' | sed -n '1p' || true)"
  if [ "${published_package_sha512}" != "${OFFICIAL_PACKAGE_SHA512}" ]; then
    echo "Published Wazuh package SHA-512 does not match the CleanHouse pin." >&2
    return 1
  fi

  actual_package_sha512="$(shasum -a 512 "${package_path}" | awk '{print tolower($1)}')"
  if [ "${actual_package_sha512}" != "${OFFICIAL_PACKAGE_SHA512}" ]; then
    echo "Pinned Wazuh package SHA-512 verification failed." >&2
    return 1
  fi

  actual_source_sha512="$(shasum -a 512 "${source_path}" | awk '{print tolower($1)}')"
  if [ "${actual_source_sha512}" != "${OFFICIAL_SOURCE_SHA512}" ]; then
    echo "Pinned Wazuh source SHA-512 verification failed." >&2
    return 1
  fi
  if ! tar -tzf "${source_path}" >/dev/null; then
    echo "Pinned Wazuh source archive is unreadable." >&2
    return 1
  fi

  verify_signature_file "${signature_path}" "${pkgutil_status}"
}

write_manifest() {
  local manifest_path="$1"
  MANIFEST_STAGE_LOCAL="${manifest_path}" \
  PACKAGE_SHA512_LOCAL="${OFFICIAL_PACKAGE_SHA512}" \
  SOURCE_SHA512_LOCAL="${OFFICIAL_SOURCE_SHA512}" \
  SIGNER_LOCAL="${OFFICIAL_SIGNER}" \
  SIGNER_FINGERPRINT_LOCAL="${OFFICIAL_SIGNER_FINGERPRINT}" \
  CHECKSUM_URL_LOCAL="${CHECKSUM_URL}" \
  python3 - <<'PY'
import datetime
import json
import os

manifest = {
    "architecture": "darwin-arm64",
    "checksum_source": os.environ["CHECKSUM_URL_LOCAL"],
    "license": "GPL-2.0-only",
    "name": "Wazuh Agent",
    "package": "wazuh-agent-4.14.7-1.arm64.pkg",
    "package_source": "https://packages.wazuh.com/4.x/macos/wazuh-agent-4.14.7-1.arm64.pkg",
    "powered_state_allowed": False,
    "schema": "cleanhouse.bundled_dependency.v1",
    "sha512": os.environ["PACKAGE_SHA512_LOCAL"],
    "signature": {
        "developer_id_installer": os.environ["SIGNER_LOCAL"],
        "notarization": "trusted",
        "sha256_fingerprint": os.environ["SIGNER_FINGERPRINT_LOCAL"],
        "verified_at_vendoring": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    },
    "source_archive": "wazuh-4.14.7-source.tar.gz",
    "source_code": "https://github.com/wazuh/wazuh/tree/v4.14.7",
    "source_sha512": os.environ["SOURCE_SHA512_LOCAL"],
    "vendored": True,
    "version": "4.14.7",
}
with open(os.environ["MANIFEST_STAGE_LOCAL"], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

main() {
  if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "Wazuh vendoring requires Apple-silicon macOS." >&2
    return 1
  fi

  STAGE_DIR="$(mktemp -d)"
  PACKAGE_STAGE="${STAGE_DIR}/${PACKAGE}"
  local source_stage license_stage checksum_stage manifest_stage signature_stage pkgutil_status
  source_stage="${STAGE_DIR}/${SOURCE_ARCHIVE}"
  license_stage="${STAGE_DIR}/LICENSE"
  checksum_stage="${STAGE_DIR}/${PACKAGE}.sha512"
  manifest_stage="${STAGE_DIR}/manifest.json"
  signature_stage="${STAGE_DIR}/package-signature.txt"
  trap cleanup EXIT

  curl --fail --silent --show-error --location "${PACKAGE_URL}" --output "${PACKAGE_STAGE}"
  curl --fail --silent --show-error --location "${CHECKSUM_URL}" --output "${checksum_stage}"
  curl --fail --silent --show-error --location "${LICENSE_URL}" --output "${license_stage}"
  curl --fail --silent --show-error --location "${SOURCE_URL}" --output "${source_stage}"

  # macOS provenance metadata is not part of the official artifact bytes.
  # Remove it only from the disposable staged download.
  xattr -d com.apple.provenance "${PACKAGE_STAGE}" 2>/dev/null || true

  pkgutil_status=0
  /usr/sbin/pkgutil --check-signature "${PACKAGE_STAGE}" >"${signature_stage}" 2>&1 || pkgutil_status=$?
  cat "${signature_stage}"
  verify_staged_artifacts \
    "${PACKAGE_STAGE}" \
    "${checksum_stage}" \
    "${source_stage}" \
    "${signature_stage}" \
    "${pkgutil_status}"

  write_manifest "${manifest_stage}"

# Every artifact was verified before this point. Nothing is published to the
# bundle destination while a download or validation is still in progress.
  mkdir -p "${DESTINATION}"
  mv "${PACKAGE_STAGE}" "${DESTINATION}/${PACKAGE}"
  mv "${source_stage}" "${DESTINATION}/${SOURCE_ARCHIVE}"
  mv "${license_stage}" "${DESTINATION}/LICENSE"
  mv "${manifest_stage}" "${DESTINATION}/manifest.json"

  echo "Vendored and verified ${PACKAGE}. Runtime powered state remains gated on authenticated event ingestion."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
