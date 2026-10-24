# Network Trend reproducibility receipt

## Result

This bundle is the durable reconstruction receipt for
`NETWORK-TREND-RATIONALIZATION-001`. It records the exact eleven reviewed
implementation and verification paths and the exact three excluded paths. It
does not stage, commit, deploy, restart, or modify CleanHouse runtime state.

The replay artifact is `TREND_DELTA.patch`. It changes seven paths. Four
additional paths are captured as byte-identical proof inputs because they were
part of the focused validation boundary but did not require a Trend-owned byte
change.

## Baseline identity and chain of custody

The repository identity at capture is recorded in `MANIFEST.json`. The shared
worktree was and remains dirty; therefore the accepted Git commit alone is not
a truthful pre-change image for these mixed files.

The stored `baseline/` directory is an explicit synthetic pre-Trend image:

- the four mixed product files preserve the current non-Trend work and reverse
  only the reviewed Trend hunks, using the managed-runtime comparison snapshot
  as the hunk-origin anchor;
- `documents/00_start-here/INDEX.md` preserves every non-Trend entry and omits
  only the Trend contract and receipt entries;
- the new Trend contract and focused interpretation test are absent;
- the four proof-only tests are byte-identical to their after-images.

This is not represented as an historical full-worktree snapshot. Its purpose
is narrower and auditable: provide exact bytes onto which only the Trend-owned
patch can be applied. The stored baseline hashes, after hashes, source-anchor
hashes, ownership method, and roles are recorded per path in `MANIFEST.json`.

## Deterministic replay

From the repository root:

```bash
python3 documents/20_validation/network-trend/verify_replay.py
```

The verifier creates an isolated temporary tree, copies `baseline/`, applies
`TREND_DELTA.patch` with two path components stripped, validates every replayed
SHA-256 against `after/` and `MANIFEST.json`, confirms the exact patch path set,
checks proof-only equality, and rejects any excluded path. It deletes the
temporary tree before returning.

The last machine-readable run is `replay-result.json`. Re-running the verifier
does not touch the product source, Git index, runtime, or browser.

`FOCUSED_VERIFICATION.json` records the accompanying 97-test focused result,
scoped Python and JavaScript compilation, product-surface verification, and the
intentional omission of browser work from this artifact-only corrective pass.

## Scope and limitations

- `after/` is an immutable receipt copy, not an alternate source tree.
- The canonical implementation remains the eleven paths listed in
  `included-paths.txt`; this directory is validation evidence only.
- The replay proves byte reconstruction and boundary isolation. Focused product
  tests and authenticated browser acceptance are separate gates documented by
  the subordinate implementation contract.
- The proof makes no claim that the three excluded files are globally unused by
  CleanHouse. It proves their dirty deltas are not part of this Trend patch.
- `CLEANHOUSE.md` is untouched.

See [`../../00_start-here/network-trend-implementation.md`](../../00_start-here/network-trend-implementation.md)
for behavior, states, controls, geometry, and validation criteria.
