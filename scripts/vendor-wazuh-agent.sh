#!/usr/bin/env bash

set -euo pipefail

VERSION="4.14.7"
PACKAGE="wazuh-agent-${VERSION}-1.arm64.pkg"
SOURCE_ARCHIVE="wazuh-${VERSION}-source.tar.gz"
OFFICIAL_PACKAGE_SHA512="9d1dbf1a0e440d8a1f6f75d44a30a395442926b01208ee8b88821e6d21a6b1ea5b885fd0c389df999a089bebda741e1af76cf9f773d552612430664da9428b11"
OFFICIAL_SOURCE_SHA512="d6182330f74ff249bfd8ff2f6a6f7934b6c5df9c53a8e5955cd42c0aa36fb25cabaef2dce2dd6241f6eb979b85fc6f87067e9f5c19069eea940aa6f127e61c09"
OFFICIAL_SIGNER="Wazuh Inc (KLZK8P68R5)"
OFFICIAL_SIGNER_FINGERPRINT="A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E"
REPO_ROOT="${CLEANHOUSE_WAZUH_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DESTINATION="${REPO_ROOT}/bundled/wazuh/darwin-arm64"
PACKAGE_URL="https://packages.wazuh.com/4.x/macos/${PACKAGE}"
LICENSE_URL="https://raw.githubusercontent.com/wazuh/wazuh/v${VERSION}/LICENSE"
SOURCE_URL="https://github.com/wazuh/wazuh/archive/refs/tags/v${VERSION}.tar.gz"
STAGE_DIR="$(mktemp -d)"
PACKAGE_STAGE="${STAGE_DIR}/${PACKAGE}"
SOURCE_STAGE="${STAGE_DIR}/${SOURCE_ARCHIVE}"
LICENSE_STAGE="${STAGE_DIR}/LICENSE"
MANIFEST_STAGE="${STAGE_DIR}/manifest.json"

cleanup() {
  rm -rf "${STAGE_DIR}"
}
trap cleanup EXIT

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "Wazuh vendoring requires Apple-silicon macOS." >&2
  exit 1
fi

curl --fail --silent --show-error --location "${PACKAGE_URL}" --output "${PACKAGE_STAGE}"
curl --fail --silent --show-error --location "${LICENSE_URL}" --output "${LICENSE_STAGE}"
curl --fail --silent --show-error --location "${SOURCE_URL}" --output "${SOURCE_STAGE}"

# macOS provenance metadata can make a byte-identical downloaded PKG fail a
# repeatable signature check. It is not part of the official artifact bytes.
xattr -d com.apple.provenance "${PACKAGE_STAGE}" 2>/dev/null || true

actual_package_sha512="$(shasum -a 512 "${PACKAGE_STAGE}" | awk '{print tolower($1)}')"
if [ "${actual_package_sha512}" != "${OFFICIAL_PACKAGE_SHA512}" ]; then
  echo "Pinned Wazuh package SHA-512 verification failed." >&2
  exit 1
fi

actual_source_sha512="$(shasum -a 512 "${SOURCE_STAGE}" | awk '{print tolower($1)}')"
if [ "${actual_source_sha512}" != "${OFFICIAL_SOURCE_SHA512}" ]; then
  echo "Pinned Wazuh source SHA-512 verification failed." >&2
  exit 1
fi

tar -tzf "${SOURCE_STAGE}" >/dev/null

signature_output="$(/usr/sbin/pkgutil --check-signature "${PACKAGE_STAGE}")"
printf '%s\n' "${signature_output}"
if ! grep -Fq "Developer ID Installer: ${OFFICIAL_SIGNER}" <<<"${signature_output}"; then
  echo "Pinned Wazuh package signer verification failed." >&2
  exit 1
fi
if ! grep -Fq "${OFFICIAL_SIGNER_FINGERPRINT}" <<<"$(tr -d '[:space:]' <<<"${signature_output}" | tr '[:lower:]' '[:upper:]')"; then
  echo "Pinned Wazuh package signer fingerprint verification failed." >&2
  exit 1
fi
if ! grep -Fq "notarization: trusted by the apple notary service" <<<"$(tr '[:upper:]' '[:lower:]' <<<"${signature_output}")"; then
  echo "Wazuh package notarization verification failed." >&2
  exit 1
fi

MANIFEST_STAGE_LOCAL="${MANIFEST_STAGE}" python3 - <<'PY'
import json
import os

manifest = {
    "architecture": "darwin-arm64",
    "checksum_source": "pinned-in-cleanhouse-vendor-script",
    "license": "GPL-2.0-only",
    "name": "Wazuh Agent",
    "package": "wazuh-agent-4.14.7-1.arm64.pkg",
    "package_source": "https://packages.wazuh.com/4.x/macos/wazuh-agent-4.14.7-1.arm64.pkg",
    "powered_state_allowed": False,
    "schema": "cleanhouse.bundled_dependency.v1",
    "sha512": "9d1dbf1a0e440d8a1f6f75d44a30a395442926b01208ee8b88821e6d21a6b1ea5b885fd0c389df999a089bebda741e1af76cf9f773d552612430664da9428b11",
    "signature": {
        "developer_id_installer": "Wazuh Inc (KLZK8P68R5)",
        "notarization": "trusted",
        "sha256_fingerprint": "A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E",
    },
    "source_archive": "wazuh-4.14.7-source.tar.gz",
    "source_code": "https://github.com/wazuh/wazuh/tree/v4.14.7",
    "source_sha512": "d6182330f74ff249bfd8ff2f6a6f7934b6c5df9c53a8e5955cd42c0aa36fb25cabaef2dce2dd6241f6eb979b85fc6f87067e9f5c19069eea940aa6f127e61c09",
    "vendored": True,
    "version": "4.14.7",
}
with open(os.environ["MANIFEST_STAGE_LOCAL"], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

# Every artifact was verified before this point. Nothing is published to the
# bundle destination while a download or validation is still in progress.
mkdir -p "${DESTINATION}"
mv "${PACKAGE_STAGE}" "${DESTINATION}/${PACKAGE}"
mv "${SOURCE_STAGE}" "${DESTINATION}/${SOURCE_ARCHIVE}"
mv "${LICENSE_STAGE}" "${DESTINATION}/LICENSE"
mv "${MANIFEST_STAGE}" "${DESTINATION}/manifest.json"

echo "Vendored and verified ${PACKAGE}. Runtime powered state remains gated on authenticated event ingestion."
