# Documents Manifest

This tree is complete and auditable for the current repository state.

## Layout

- `00_start-here`: operator entrypoint docs.
- `10_runbooks`: execution runbooks and helper scripts.
- `20_validation`: gate/proving lanes.
- `30_evidence`: doctrine, audits, and validation artifacts.
- `90_reference-archive`: reference-only legal/auth/legacy material.
- `95_source-mirror`: exact-path mirror of source docs/root markdown/scripts.

## Coverage Contract

- Source sets:
  - `docs/**` (excluding `.DS_Store`)
  - `README.md`
  - `QUICK_START.md`
  - `RULES.md`
  - `scripts/*.{py,sh}`
- Mirror root:
  - `documents/95_source-mirror/`
- Coverage manifests:
  - `DOCUMENTS_MANIFEST.json`
  - `SOURCE_COVERAGE.json`

## Integrity Contract

- `FILE_INDEX.json` contains SHA-256 + byte size for files under `documents/`.
- `FILE_INDEX.json` excludes `FILE_INDEX.json` and `FILE_INDEX.json.sha256` from hash scope.
- `FILE_INDEX.json.sha256` is the detached checksum attestation for the index file.

## Deterministic Verify

```bash
./verify_documents_tree.py
```
