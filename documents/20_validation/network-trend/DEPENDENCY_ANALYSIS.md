# Trend exclusion analysis

This receipt fixes an eleven-path review boundary. Four paths are retained as
proof-only inputs and seven contain the replayed Trend delta. The patch changes
only those seven paths; the verifier rejects any additional patch path.

The following three paths are deliberately excluded:

| Path | Why it is not required by the Trend delta |
|---|---|
| `backend/vvault_sync.py` | Trend reads through the already-established `vvault_preservation` interface used by `backend/api/cleanhouse.py`. The replay does not change the sync transport, outbox, credentials, or preservation worker. The file name does not occur in `TREND_DELTA.patch`. |
| `documents/00_start-here/canon-runtime-spine.md` | Trend interpretation does not redefine startup, liveness, operator readiness, or supervision. The subordinate Trend contract explicitly leaves runtime readiness unchanged. |
| `tests/test_runtime_liveness_probe.py` | The Trend delta neither changes nor exercises the liveness endpoint. Runtime liveness remains an accepted external regression boundary, not a Trend implementation input. |

`backend/api/cleanhouse.py` has existing imports outside the Trend boundary.
Those pre-existing dependencies are part of the captured baseline, not changes
introduced by this patch. Excluding a path means the Trend replay neither
changes it nor depends on its dirty-worktree delta; it does not claim that the
full CleanHouse application has no runtime relationship to that module.

The machine check in `verify_replay.py` proves:

1. the included and excluded lists are exact;
2. the patch path set equals the seven declared delta paths;
3. none of the three excluded paths occurs in the patch or captured trees;
4. replayed bytes equal every recorded after-image SHA-256;
5. proof-only inputs remain byte-identical before and after.
