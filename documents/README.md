# CleanHouse Documents Tree

Operator-ready and audit-ready documentation package.

## Primary Paths

- `00_start-here/` for first use.
- `10_runbooks/` for operations.
- `20_validation/` for proving and gates.
- `30_evidence/` for doctrine/audits/artifacts.
- `90_reference-archive/` for non-daily references.
- `95_source-mirror/` for exact source coverage.

## Audit Artifacts

- `DOCUMENTS_MANIFEST.json` (coverage + commit metadata)
- `SOURCE_COVERAGE.json` (path-level source->mirror mapping and sha match)
- `FILE_INDEX.json` (tree integrity index)
- `verify_documents_tree.py` (deterministic verifier)

## Status

This tree includes complete source coverage for current `docs/**`, root markdown entrypoints, and executable scripts (`*.py`, `*.sh`) under `scripts/`.
