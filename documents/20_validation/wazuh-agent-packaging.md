# CleanHouse Wazuh Agent Packaging

## Scope

This contract covers only the locally vendored macOS Apple Silicon Wazuh Agent
bundle used by CleanHouse. It does not authorize agent installation,
enrollment, manager deployment, remote service operation, VVAULT integration,
or evidence persistence.

## Shipping closure

The bundle at `bundled/wazuh/darwin-arm64/` ships exactly these artifacts:

| Artifact | Purpose |
| --- | --- |
| `wazuh-agent-4.14.7-1.arm64.pkg` | Pinned Wazuh Agent installer package. |
| `wazuh-4.14.7-source.tar.gz` | Corresponding source archive. |
| `manifest.json` | Immutable package, source, and signer receipt. |
| `LICENSE` | Upstream license text. |
| `THIRD_PARTY_NOTICES.md` | Third-party notice record. |
| `SOURCE_COMPLIANCE.md` | Source-compliance record. |

## Fixed provenance gates

The bundle is Wazuh Agent `4.14.7` for `darwin-arm64`. Vendoring accepts only:

- package SHA-512:
  `9d1dbf1a0e440d8a1f6f75d44a30a395442926b01208ee8b88821e6d21a6b1ea5b885fd0c389df999a089bebda741e1af76cf9f773d552612430664da9428b11`;
- source SHA-512:
  `d6182330f74ff249bfd8ff2f6a6f7934b6c5df9c53a8e5955cd42c0aa36fb25cabaef2dce2dd6241f6eb979b85fc6f87067e9f5c19069eea940aa6f127e61c09`;
- Developer ID Installer signer `Wazuh Inc (KLZK8P68R5)`;
- signer fingerprint
  `A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E`;
- an Apple-notarization-trusted `pkgutil --check-signature` result; and
- a readable source archive (`tar -tzf`).

`scripts/vendor-wazuh-agent.sh` validates all of those conditions in temporary
storage. The checksum published by Wazuh, the downloaded package, and the
downloaded source archive must independently match CleanHouse's established
pins. The first Developer ID Installer identity must be the exact pinned Wazuh
signer, and the pinned fingerprint must occur in that signer's certificate
block. The script publishes the package, source, license, and manifest only
after every gate succeeds; its exit trap removes staged artifacts on every
failure path.

## Runtime and staged-runtime contract

`backend.wazuh_runtime.verify_bundle()` requires the fixed package and source
hashes plus a live `pkgutil` signature verification before reporting the agent
bundle as packaged. When iCloud provenance metadata causes the checked-in path
to fail that live check, runtime verification creates a temporary byte-identical
copy only after the package hash matches the pin, removes provenance from that
copy, rechecks its hash, signer, fingerprint, and notarization, and always
deletes it. The checked-in package is never mutated. A historical manifest
receipt is audit metadata and never overrides the live signature gate.

The CleanHouse LaunchAgent stages the complete six-artifact closure
byte-for-byte into its isolated runtime when the local bundle is present. The
normal macOS operator context has verified the checked-in bundle as packaged,
checksum/source-verified, signed by the pinned signer and fingerprint, and
Apple-notarization trusted.

## Focused verification

```bash
bash -n scripts/vendor-wazuh-agent.sh
PYTHONDONTWRITEBYTECODE=1 cleanhouse_env/bin/python3 -m unittest -v \
  tests.test_wazuh_packaging \
  tests.test_wazuh_runtime \
  tests.test_launch_agent
```

The focused LaunchAgent contract verifies byte-for-byte staging of all six
shipping artifacts while excluding `.env` from the staged runtime.

## Deferred operator gates

The following work is deliberately outside this packaging baseline and needs
separate authorization: administrator-authorized agent installation and
enrollment, Wazuh manager deployment and configuration, hosted smoke testing,
legal/release review, and all VVAULT/OVVAULTS work.
