# Network View Audit Rubric

Date: 2026-06-29

Scope: CleanHouse Network view modes in `frontend/investigations.html` and
`frontend/js/investigations.js`: Table, Findings, Trend, Distribution, and
Timeline.

Evidence limits: Static repository audit only. No browser automation. Runtime
behavior, screenshots, localStorage persistence across reload, EventSource
behavior, and responsive layout remain unverified until checked manually or by a
non-browser runtime harness.

## Rubric

Each view is scored 0-4 per category.

| Score | Meaning |
|---|---|
| 0 | Missing, dead, or misleading |
| 1 | Renders but source/interaction is wrong or unverified |
| 2 | Works in a narrow path with visible gaps |
| 3 | Meets intended behavior with clear empty/error states |
| 4 | Product-ready with runtime proof and regression coverage |

Release gate: no view can pass if Truthfulness/Data Source or Primary Flow is
below 3.

### Required Categories

| Category | Audit question |
|---|---|
| Truthfulness/Data Source | Does the view use the correct source of truth and avoid overclaiming? |
| Primary Flow | Can the user reach, read, and use the view through the real controls? |
| Empty/Error State | Does the view tell the truth when no rows/samples/findings exist? |
| Interaction State | Do filters, ranges, tooltips, active tabs, and persistence stay coherent? |
| Accessibility | Are controls keyboard reachable with meaningful labels and focus behavior? |
| Regression Safety | Does the view avoid breaking adjacent views, current rows, or stored state? |
| Evidence | Is the behavior proven by tests, static checks, runtime output, or screenshots? |

## View-Specific Gates

### Table

- Uses `currentNetworkData.events` as current connection rows.
- Preserves table scroll and column widths during re-render.
- Filtering from the action sidebar either shows affected rows or an honest
  empty result.
- Raw metadata footer reflects the same current rows shown to the user.

### Findings

- Uses current connection rows, not trend samples.
- Prioritizes readable plain-language finding summaries.
- Does not show an empty feed without explanation when filters remove all rows.
- Finding copy names uncertainty as unknown/unavailable when data is missing.

### Trend

- Uses `networkTrendSamples`, not connection-row timestamps.
- Appends one observation per refresh/rendered live batch.
- Persists samples in localStorage when available and falls back to memory.
- Bounds sample history by time and max count.
- Buckets samples against the selected real time window from now minus range to
  now.
- One bar means one or more samples in that bucket.
- Empty buckets remain empty.
- No samples in range shows an honest empty state.
- Copy says observed sampled connections, not packet activity.

### Distribution

- Uses current connection rows only.
- Shows current concentration by app/destination/protocol as implemented.
- Empty current rows do not produce a misleading non-zero chart.
- Legend, slice labels, and total match the rendered row set.

### Timeline

- Uses current/notable network events only.
- Range controls apply to real event timestamps when available.
- Notable markers prioritize critical/degraded/unusual/high-volume activity.
- Empty notable windows state that no priority findings are visible.
- Timeline does not claim to be the sampled trend.

## Static Audit Findings

### Finding 1

- Severity: Medium
- Area: Evidence
- Problem: View behavior is only syntax/whitespace verified, not runtime
  verified.
- Evidence: Existing checks were `node --check frontend/js/investigations.js`
  and `git diff --check`; no screenshot, DOM, localStorage, EventSource, or
  manual runtime evidence is recorded in this audit.
- Why it matters: The view wiring can be syntactically valid while still failing
  interaction, persistence, or visual expectations.
- Required fix: Add a non-browser unit harness for the pure bucketing/sample
  functions and record manual UI verification for the five view modes.

## Resolved Static Findings

- Live Trend sampling no longer derives directly from accumulated live packet
  rows. Live packet events schedule a coalesced snapshot sample, and the snapshot
  is fetched through `getNetworkSnapshot(true)`.
- Filtered current-row views now render an explicit empty state when the selected
  action filter removes all visible rows.

## Current View Scores

| View | Truth | Flow | Empty/Error | Interaction | Accessibility | Regression | Evidence | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Table | 3 | 3 | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Findings | 3 | 3 | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Trend | 3 | 3 | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Distribution | 3 | 3 | 3 | 3 | 2 | 3 | 2 | Pass with risk |
| Timeline | 3 | 3 | 3 | 3 | 2 | 3 | 2 | Pass with risk |

## Verification Matrix

| Flow | Status | Evidence |
|---|---|---|
| Network view controls exist | PASS | `frontend/investigations.html:223-228` |
| View mode dispatch exists | PASS | `frontend/js/investigations.js:1724-1731` |
| Trend uses `networkTrendSamples` | PASS | `frontend/js/investigations.js:1969-1999`, `2097-2133` |
| Trend localStorage persistence exists | PASS | `frontend/js/investigations.js:181-199` |
| Snapshot sampling exists | PASS | `frontend/js/investigations.js:1630-1645`, `201-219` |
| Live sampling is semantically correct | PASS | Live events schedule `sampleNetworkLiveTrendSnapshot()`, which samples forced snapshot rows |
| Filtered empty state | PASS | `renderNetworkDisplay()` renders explicit filtered-empty copy before renderer dispatch |
| Desktop visual quality | UNVERIFIED | No screenshot/runtime artifact |
| Mobile visual quality | UNVERIFIED | No screenshot/runtime artifact |
| Reload persistence | UNVERIFIED | No runtime localStorage proof |

Final release call for the current audited state: RELEASE FOR DATA-ONLY PASS;
full visual/runtime release still requires runtime evidence.
