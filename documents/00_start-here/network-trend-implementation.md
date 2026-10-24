# Network Trend graph contract

## Authority and boundary

This subordinate contract records the restored Network Trend behavior. It
implements the owner canon in `CLEANHOUSE.md`; it does not change that canon.

Trend answers two related, selectable questions:

> How many distinct active connections were observed over the selected range?

> How many distinct Strength, Vulnerability, or Threat assessments were active
> at each covered bucket boundary?

Trend remains a graph. Connections is the default metric; Strengths,
Vulnerabilities, and Threats are selectable active-posture metrics over the
same windows and bucket boundaries. Trend is not an
interpretation panel, finding narrative, threat verdict, packet fabrication,
or second Findings view. Plain-language analysis belongs in **Findings** and
the selected-evidence **ctrl** panel.

## Graph/Chart duplicate navigation

The compact `Graph / Chart` control intentionally duplicates the primary
Network navigation:

- **Graph** selects **Trend** (`bar`).
- **Chart** selects **Distribution** (`pie`).

The control is visible in Trend and Distribution so the owner can move between
the two visual views without returning to the primary navigation. It does not
switch between two renderings of Trend.

## Trend evidence contract

Trend uses retained and current Network observations to build bounded,
half-open UTC buckets for `5s`, `1m`, `30m`, `1h`, `24h`, `7d`, `1mo`, `3mo`,
and `12mo`.

Each point exposes:

- a stable bucket identity and time bounds;
- `connectionCount`, counted from unique source/destination/protocol tuples;
- bounded related event IDs and evidence references;
- explicit degraded, missing-destination, and external-only counts when the
  source evidence provides them.
- for category metrics, the distinct active assessment IDs and bounded evidence
  references counted at the bucket boundary.

Duplicate observations of the same connection in one bucket do not inflate the
displayed connection count. A zero means a covered bucket with zero observed
connections. A missing bucket means no retained evidence covered that bucket;
the summary reports the coverage gap rather than inventing a zero.

Category metrics use the backend-owned `cleanhouse.security_assessment.v1`
contract. The browser never derives a category from severity, color, copy, or
operational health. Assessment lifecycle boundaries determine whether an
assessment is active in a half-open bucket. Replay retains assessment identity
and does not inflate category counts.

The `5s` range retains subsecond bucket resolution. Reads, result size, cached
projections, related IDs, and evidence references remain bounded by the
existing Network limits.

## Visual behavior

Trend renders the established connection-count graph with:

- chronological bars;
- the selected time window;
- Y-axis choices `100`, `250`, `500`, and `1000`;
- an accessible `Network connection trend` label;
- evidence selection that binds the selected observation to `ctrl` without
  executing remediation.

A metric selector chooses `connections`, `strengths`, `vulnerabilities`, or
`threats` without changing the selected range. Connections continues to use
the established count bars. Category selections use the same graph frame and
plot distinct active assessments. Empty covered buckets are zero; uncovered
buckets remain visible gaps.

The graph remains truthful when capture is unavailable: retained observations
may be displayed, while capture health continues to show its exact degraded or
blocked state. General runtime readiness never upgrades capture health.

Distribution remains the separate application-activity visualization defined
by the Network product contract. The Chart button navigates there; it does not
replace the Trend graph.

## Explicit exclusions

This boundary does not:

- add narrative Vulnerabilities, Threats, or Strengths to Trend;
- classify evidence in the browser;
- move Findings text into Trend;
- change Findings or ctrl behavior;
- change capture packaging or provider health;
- modify authentication, runtime readiness, Files/Wazuh, or other product
  surfaces;
- delete historical validation evidence.

## Implementation paths

- `backend/api/cleanhouse.py`
- `frontend/investigations.html`
- `frontend/js/investigations.js`
- `frontend/css/investigations.css`
- `tests/test_network_trend_interpretation.py`
- `tests/test_network_header_static.py`
- `tests/network_resilience_node.test.mjs`
- this document

The test filename is retained for worktree continuity even though the rejected
Trend-interpretation behavior is no longer part of the product.

## Focused verification

```bash
cleanhouse_env/bin/python3 -m unittest -v \
  tests.test_network_trend_interpretation \
  tests.test_network_header_static \
  tests.test_network_active_connection_count \
  tests.test_network_capture_truth
node --test tests/network_resilience_node.test.mjs
node --test tests/network_table_ctrl_resilience_node.test.mjs
node --check frontend/js/investigations.js
cleanhouse_env/bin/python3 -m py_compile \
  backend/api/cleanhouse.py \
  tests/test_network_trend_interpretation.py
cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py
git diff --check
```

Completion requires the Graph/Chart navigation, the actual Trend graph, the
connection and active-assessment projections, coverage/gap behavior, and this
contract to agree. A passing test achieved by removing or hiding a protected
surface is invalid.

## Trend-only correctness and placement repair — 2026-10-22

- Explicit `gap` or `coverage_state: gap` buckets render the noninteractive
  missing-coverage marker, with an accessible name explaining unavailable
  evidence. They never become observed zero-valued selectable bars.
- Covered zero buckets retain their evidence selection and render a 2px
  baseline. Positive values retain the established minimum-height treatment
  and fixed-axis ceiling. Selectable bars have accessible metric/count and
  interval names, using “1 vulnerability” and “0 vulnerabilities”/“9 vulnerabilities”.
  Enter and Space on selectable bars invoke the same evidence descriptor as
  pointer selection and prevent the default keyboard action. Rebinding does
  not duplicate handlers. The metric selector is a labelled group of native buttons
  with exactly one pressed state.
- Bucket exclusion respects half-open selected windows: buckets ending at
  the start or starting at the end are excluded.
- In Trend only, the existing toolbar context element moves after the shared
  navigation/action groups and occupies a full-width wrapping row. Graph/Chart
  and Refresh retain the same first-row content as Distribution. On leaving
  Trend the context returns to its original action-group position; Distribution
  markup and behavior are unchanged. Current pixel equivalence remains subject
  to rendered verification, not inferred from these source rules.
- Changing a metric preserves the selected time range; repeating the selected
  metric or supplying an invalid metric does not issue another projection load.
  Settled coordinator records are keyed by range and metric. A metric switch
  immediately aborts and invalidates the prior projection request and clears the
  unkeyed Trend fallback, preventing old counts from being relabelled during
  the deferred request. Existing records for other metrics remain reusable.
  Metric and range buttons are bound when the toolbar is rendered, including
  loading, empty, and unavailable results; they do not require plotted data.
  Range changes also invalidate the active Trend request synchronously before
  rendering the new label. Unkeyed settled/current/base fallbacks are cleared;
  only records whose own range and metric match may supply retained values.
  Otherwise the new range shows an honest loading placeholder (or matching
  range live connection ticks). Late responses must still match request ID,
  epoch, active view, selected range, effective range, and captured metric
  before entering any cache, settled record, or base. An explicitly conflicting
  response range/metric is rejected. Missing response scope fields are bound
  to the validated request, never inferred from later UI selection.
  Backend assessment classification, capture state, evidence selection, and
  retained history mechanisms are unchanged by this frontend repair.

Additional focused verification:
`node --test tests/network_trend_slice_node.test.mjs`.
This repair is repository-source-only until separately staged and verified.
Fresh browser acceptance must exercise metric changes, covered zero, gaps,
errors, Graph/Chart navigation, responsive placement against Distribution,
and resize behavior. Neither the earlier Findings synthetic geometry receipt
nor source tests establish current Trend browser or live-data acceptance.
