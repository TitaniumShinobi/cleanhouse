# Network Truthfulness State Model Pass

## Thesis

Network must not use machine status as user-facing diagnosis. `NO_DATA` can remain an API/result state, but the Network surface has to describe the runtime truth, source readiness, tab readiness, and settled empty data separately.

## Research

The Network page had a hydration coordinator, snapshot requests, projection requests, live packet updates, tab renderers, and header tags. The failure was not a missing transport state; it was collapsed UI copy. Empty arrays from warmup, reload, projection placeholders, and genuinely settled empty tabs all converged into generic copy.

## Conclusion

Network now has coordinator-owned page and tab view states for starting, reconnecting, refreshing, waiting, loading, degraded, empty, and ready. Each tab owns its copy:

- Table: live/current packets vs no visible recent connections
- Findings: grouped findings loading vs no grouped findings
- Trend: saved/live trend loading vs no trend points for the selected range
- Distribution: app distribution loading vs no active apps in the selected snapshot
- Timeline: event history loading vs no events in the selected window

## Rubrication

Network is the model for future truthful loading/empty/degraded states across CleanHouse. Keep machine contracts stable, keep UI copy stateful, and keep tab state local to its source precedence.

## Audit

Changed surface:

- `frontend/investigations.html`
- `frontend/js/investigations.js`
- `tests/network_resilience_node.test.mjs`
- `tests/test_network_header_static.py`

No Overview, Applications, Files, Zaelith, Identity, Reports, Help, or Settings behavior was changed.

## Plan

Future page passes should follow this layering:

1. Machine status: transport/API result fields.
2. Runtime status: backend/live collector health.
3. Source status: snapshot, saved projection, live stream, or event history readiness.
4. UI view state: user-facing copy for the active surface and tab.

## Implement

The Network hydration coordinator now tracks page phase and tab view states. Snapshot placeholders and projection placeholders no longer render as generic `NO_DATA` diagnosis. Timeline settled empty state no longer borrows live snapshot or last-good rows.

Follow-up correction from live restart review: the backend now keeps empty Network packet probes in `WARMING` during the initial backend boot window. A freshly restarted server can be runtime-healthy before Network packet sources have yielded a post-restart snapshot, so the UI must keep saying reconnecting/loading instead of settled empty copy.

## Test

Added and updated browserless Network resilience tests for manual refresh, restart warmup, stale projection races, tab-local loading/empty states, and timeline source isolation.
