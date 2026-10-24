# Network View Data-Only Audit

Date: 2026-06-29

Scope: Static data-flow audit of CleanHouse Network view modes only: Table,
Findings, Trend, Distribution, and Timeline. Visual layout, screenshots,
browser automation, and manual DOM/runtime inspection are excluded.

## VERDICT

PASS WITH RISKS for Table, Findings, Distribution, and Timeline data routing.

BLOCKED for release of Trend live-mode truthfulness.

## FINDINGS

### Finding 1

- Severity: High
- Area: Frontend/Data
- Problem: Live Trend samples still derive `connectionCount` from the
  accumulated live event list, not a current active-connection observation.
- Evidence: `appendNetworkLiveEvent()` prepends each live packet/event payload to
  `currentNetworkData.events` and then calls
  `appendNetworkTrendSample(currentNetworkData.events, currentNetworkData)` in
  `frontend/js/investigations.js:1409-1444`; `appendNetworkTrendSample()` stores
  `connectionCount: visibleEvents.length` in
  `frontend/js/investigations.js:197-205`.
- Why it matters: Snapshot refreshes are sampled observations, but live mode can
  still make the Trend count accumulated event rows instead of observed active
  connections.
- Required fix: In live mode, pass a current active-connection snapshot or live
  batch summary into `appendNetworkTrendSample()`; do not use the accumulated
  event history as `connectionCount`.

### Finding 2

- Severity: Medium
- Area: UX/Data
- Problem: Filtered current-row views can render empty data without an explicit
  filtered-empty state.
- Evidence: `renderNetworkDisplay()` computes `filteredEvents` in
  `frontend/js/investigations.js:1658-1661`, but the empty guard checks only
  unfiltered `events.length` in `frontend/js/investigations.js:1662-1668` before
  rendering the active view with `filteredEvents` in
  `frontend/js/investigations.js:1669-1676`.
- Why it matters: Table, Findings, Distribution, and Timeline can look like they
  have no data without telling the user the active action filter removed all
  rows.
- Required fix: Add a filtered-empty branch when `networkActionFilterReason` is
  active and `filteredEvents.length === 0`.

### Finding 3

- Severity: Low
- Area: Evidence
- Problem: Runtime persistence and live/fallback sampling behavior are not
  proven by tests.
- Evidence: The verified commands are syntax and diff checks only; no unit
  harness exercises localStorage recovery, range bucketing, one-sample rendering,
  or live/fallback sample creation.
- Why it matters: The static code supports the intended path, but regressions in
  browser state and live event ordering remain unproven.
- Required fix: Add a focused non-browser test harness for trend sample
  normalization, pruning, bucketing, and sample append inputs.

## VERIFICATION MATRIX

| Flow | Status | Evidence |
|---|---|---|
| Network view controls exist for all five modes | PASS | `frontend/investigations.html:223-228` |
| View mode dispatch routes to five renderers | PASS | `frontend/js/investigations.js:1669-1676` |
| Table uses current connection rows | PASS | `renderNetworkDisplay()` passes `filteredEvents` from `currentNetworkData.events` to `renderNetworkTable()` at `frontend/js/investigations.js:1642-1676` |
| Findings use current connection rows | PASS | `renderNetworkDisplay()` dispatches `filteredEvents` to `renderNetworkFindings()` at `frontend/js/investigations.js:1669-1676` |
| Distribution uses current connection rows | PASS | `renderNetworkPie(events)` groups the provided row set by app at `frontend/js/investigations.js:2082-2119` |
| Timeline uses current/notable events | PASS | `renderNetworkTimeline(events)` filters current rows by selected range and notable priority at `frontend/js/investigations.js:2273-2280` |
| Trend renderer reads samples instead of event timestamps | PASS | `renderNetworkBarGraph()` calls `networkTrendBuckets(networkTrendSamples, ...)` at `frontend/js/investigations.js:2042-2045` |
| Trend buckets use sample timestamps and selected real window | PASS | `networkSelectedRangeWindow()` and `networkTrendBuckets()` at `frontend/js/investigations.js:1851-1859` and `1914-1944` |
| Trend localStorage load/persist fallback exists | PASS | `loadNetworkTrendSamples()` and `persistNetworkTrendSamples()` at `frontend/js/investigations.js:177-195` |
| Snapshot refresh appends a sample | PASS | `renderNetworkCapture()` calls `appendNetworkTrendSample(events, data)` at `frontend/js/investigations.js:1588-1597` |
| Live update appends a sample | PASS | `appendNetworkLiveEvent()` calls `appendNetworkTrendSample()` at `frontend/js/investigations.js:1409-1444` |
| Live sample is a true active-connection observation | FAIL | Live `connectionCount` is accumulated `currentNetworkData.events.length` at `frontend/js/investigations.js:1409-1444` and `197-205` |
| No samples in selected Trend range shows honest empty state | PASS | `renderNetworkBarGraph()` renders `No sampled network observations exist for this selected range.` when `observedSamples.length` is zero at `frontend/js/investigations.js:2049-2068` |
| One Trend sample renders one honest non-empty bucket | PASS | Buckets start empty and only the bucket receiving the sample is non-empty at `frontend/js/investigations.js:1925-1943` |
| Empty current rows are honest for non-Trend views | PASS | `renderNetworkDisplay()` renders `No network events are visible right now.` when no current rows exist at `frontend/js/investigations.js:1662-1668` |
| Empty filtered rows are honest | FAIL | No separate guard for `filteredEvents.length === 0` at `frontend/js/investigations.js:1658-1676` |
| Browser reload localStorage proof | UNVERIFIED | Static localStorage code exists; no runtime proof recorded |
| EventSource/fallback runtime ordering | UNVERIFIED | Static handlers exist; no live runtime proof recorded |

## DATA-ONLY SCORES

| View | Source truth | State flow | Empty data | Interaction data | Evidence | Data verdict |
|---|---:|---:|---:|---:|---:|---|
| Table | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Findings | 3 | 3 | 2 | 2 | 2 | Pass with risk |
| Trend | 2 | 3 | 3 | 3 | 2 | Blocked for live mode |
| Distribution | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Timeline | 3 | 3 | 2 | 3 | 2 | Pass with risk |

## MISSING EVIDENCE

- Runtime proof that localStorage survives browser reload with existing samples.
- Runtime proof that fallback polling appends one sample per snapshot without
  clearing trend history.
- Runtime proof that live EventSource payloads represent active connections
  rather than packet events.
- Automated test proof for `networkTrendBuckets()` across all selected ranges.
- Automated test proof for no-sample and one-sample Trend states.

## FINAL RELEASE CALL

DO NOT RELEASE
