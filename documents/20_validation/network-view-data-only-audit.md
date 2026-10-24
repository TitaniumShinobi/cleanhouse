# Network View Data-Only Audit

Date: 2026-06-29

Scope: Static data-flow audit of CleanHouse Network view modes only: Table,
Findings, Trend, Distribution, and Timeline. Visual layout, screenshots,
browser automation, and manual DOM/runtime inspection are excluded.

## VERDICT

PASS WITH RISKS for data flow.

The previous data blockers are resolved in static code evidence. Runtime
localStorage, EventSource, and fallback-poll behavior remain unverified.

## FINDINGS

### Finding 1

- Severity: Low
- Area: Evidence
- Problem: Runtime persistence and live/fallback sampling behavior are not
  proven by tests.
- Evidence: The verified commands are syntax and diff checks only; no unit
  harness exercises localStorage recovery, range bucketing, one-sample rendering,
  live snapshot sampling, or fallback sample creation.
- Why it matters: The static code supports the intended path, but browser state
  and live event ordering remain unproven.
- Required fix: Add a focused non-browser test harness for trend sample
  normalization, pruning, bucketing, and append inputs; record manual runtime
  proof separately if visual/runtime release is needed.

## RESOLVED FINDINGS

### Live Trend source

- Status: PASS
- Evidence: `appendNetworkLiveEvent()` now only updates live packet evidence and
  renders current data in `frontend/js/investigations.js:1458-1493`.
  Live Trend sampling is scheduled from live status/events in
  `frontend/js/investigations.js:912-930`, then samples forced snapshot rows via
  `getNetworkSnapshot(true)` in `frontend/js/investigations.js:995-1027`.
  The forced snapshot API is wired in `frontend/js/api-client.js:663-671`, and
  the backend honors `snapshot=1` without changing default network behavior in
  `backend/api/cleanhouse.py:2622-2630`.

### Filtered empty state

- Status: PASS
- Evidence: `renderNetworkDisplay()` now renders
  `No current network rows match the selected action filter.` before dispatching
  Table, Findings, Distribution, or Timeline when a filter removes all current
  rows in `frontend/js/investigations.js:1717-1723`.

## VERIFICATION MATRIX

| Flow | Status | Evidence |
|---|---|---|
| Network view controls exist for all five modes | PASS | `frontend/investigations.html:223-228` |
| View mode dispatch routes to five renderers | PASS | `frontend/js/investigations.js:1724-1731` |
| Table uses current connection rows | PASS | `renderNetworkDisplay()` passes `filteredEvents` from `currentNetworkData.events` to `renderNetworkTable()` at `frontend/js/investigations.js:1690-1731` |
| Findings use current connection rows | PASS | `renderNetworkDisplay()` dispatches `filteredEvents` to `renderNetworkFindings()` at `frontend/js/investigations.js:1724-1731` |
| Distribution uses current connection rows | PASS | `renderNetworkPie(events)` groups the provided row set by app |
| Timeline uses current/notable events | PASS | `renderNetworkTimeline(events)` filters current rows by selected range and notable priority |
| Trend renderer reads samples instead of event timestamps | PASS | `renderNetworkBarGraph()` calls `networkTrendBuckets(networkTrendSamples, ...)` |
| Trend buckets use sample timestamps and selected real window | PASS | `networkSelectedRangeWindow()` and `networkTrendBuckets()` |
| Trend localStorage load/persist fallback exists | PASS | `loadNetworkTrendSamples()` and `persistNetworkTrendSamples()` |
| Snapshot refresh appends a sample | PASS | `renderNetworkCapture()` calls `appendNetworkTrendSample(events, data)` |
| Live update appends Trend samples from active-connection snapshots | PASS | `sampleNetworkLiveTrendSnapshot()` calls `getNetworkSnapshot(true)` and samples returned snapshot `events` |
| Live event rows do not directly create Trend samples | PASS | `appendNetworkLiveEvent()` no longer calls `appendNetworkTrendSample()` |
| No samples in selected Trend range shows honest empty state | PASS | `renderNetworkBarGraph()` renders `No sampled network observations exist for this selected range.` when no samples are in range |
| One Trend sample renders one honest non-empty bucket | PASS | Buckets start empty and only the bucket receiving the sample is non-empty |
| Empty current rows are honest for non-Trend views | PASS | `renderNetworkDisplay()` renders `No network events are visible right now.` when no current rows exist |
| Empty filtered rows are honest | PASS | `renderNetworkDisplay()` renders explicit filtered-empty copy before renderer dispatch |
| Browser reload localStorage proof | UNVERIFIED | Static localStorage code exists; no runtime proof recorded |
| EventSource/fallback runtime ordering | UNVERIFIED | Static handlers exist; no live runtime proof recorded |

## DATA-ONLY SCORES

| View | Source truth | State flow | Empty data | Interaction data | Evidence | Data verdict |
|---|---:|---:|---:|---:|---:|---|
| Table | 3 | 3 | 3 | 3 | 2 | Pass with risk |
| Findings | 3 | 3 | 3 | 3 | 2 | Pass with risk |
| Trend | 3 | 3 | 3 | 3 | 2 | Pass with risk |
| Distribution | 3 | 3 | 3 | 3 | 2 | Pass with risk |
| Timeline | 3 | 3 | 3 | 3 | 2 | Pass with risk |

## MISSING EVIDENCE

- Runtime proof that localStorage survives browser reload with existing samples.
- Runtime proof that fallback polling appends one sample per snapshot without
  clearing trend history.
- Runtime proof that live EventSource packets trigger coalesced snapshot samples.
- Automated test proof for `networkTrendBuckets()` across all selected ranges.
- Automated test proof for no-sample and one-sample Trend states.

## FINAL RELEASE CALL

RELEASE FOR DATA-ONLY PASS; HOLD FOR FULL RUNTIME/VISUAL RELEASE UNTIL MISSING
EVIDENCE IS RECORDED.
