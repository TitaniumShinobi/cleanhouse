# Network Trend implementation contract

## Approved boundary: NETWORK-TREND-RATIONALIZATION-001

This is the authoritative subordinate contract for the implemented Network
Trend checkpoint. Code and this contract move together. It does not modify the
master `CLEANHOUSE.md` canon, factual Timeline receipts, collection,
authentication, runtime readiness, Distribution, Findings, or Connections.

The owner has clarified Trend as **interpreted bias and rationalization over
time**. Timeline remains the factual chronology. The older master sentence
describing Trend only as observed activity is therefore a canon-reconciliation
candidate, but is not edited by this checkpoint because master-canon changes
require an explicit owner instruction naming that file.

## Product question and boundaries

Trend answers:

> How do the current versioned interpretation rules rationalize retained
> Network evidence across time, and where does evidence coverage stop?

Trend is not a packet counter, socket inventory, factual event log, malware
verdict, authorization decision, interpolated forecast, or replacement for
Timeline. Raw observed connection counts are not presented as meaningful Trend.
An interpretation never rewrites the retained observation that supports it.

Three independently visible series are implemented:

- **Vulnerabilities** — conditions that reduce confidence or expose a weakness;
- **Threats** — retained review signals indicating suspicious, malicious, or
  elevated-severity evidence;
- **Strengths** — retained evidence supporting identified ownership, readable
  destination context, encrypted service, or local/private scope.

The same item may support Strengths and an opposing series. Such contradictory
evidence is preserved and counted; signals are never netted into a single
verdict.

## Architecture and provenance

```text
immutable Network observation
    -> bounded local event spine and authenticated OVVAULTS sample history
    -> source-event deduplication
    -> network-trend-rationalization.v1 rules
    -> half-open UTC bucket [start, end)
    -> interpretation aggregate with evidence links
    -> GET /cleanhouse/network/projection?view=trend&range={range}
    -> one shared filtered dataset
    -> Graph or Chart presentation
```

The endpoint retains the established ranges: `5s`, `1m`, `30m`, `1h`, `24h`,
`7d`, `1mo`, `3mo`, and `12mo`. Reads remain bounded by the existing projection
history limit and `NETWORK_PROJECTION_LIMIT`. The projection cache remains the
existing bounded Network cache. Buckets are aligned to UTC epoch boundaries at
the configured range duration divided by its bucket count; the `5s` range keeps
its subsecond resolution instead of silently widening buckets to one second.

Old count-only trend ticks and legacy connection-count buckets remain preserved
as factual historical artifacts. They are intentionally not projected as
interpreted Trend because they lack the versioned rule result required by this
contract. No record is deleted or rewritten.

## Versioned interpretation schema

Every returned bucket uses:

```json
{
  "interpretation_schema": "cleanhouse.network.trend.interpretation.v1",
  "rule_version": "network-trend-rationalization.v1",
  "evidence_state": "observed",
  "bucket_range": "1m",
  "bucket_start": "UTC timestamp",
  "bucket_end": "UTC timestamp",
  "capture_generations": [4],
  "evidence_count": 2,
  "contradiction_count": 1,
  "related_event_ids": ["immutable source ids"],
  "evidence_refs": ["local:// or provider references"],
  "interpretation": {
    "vulnerabilities": {
      "value": 1,
      "confidence": 0.8,
      "rationale": ["human-readable rule rationale"],
      "signals": ["stable signal ids"],
      "evidence_refs": ["supporting references"]
    },
    "threats": {},
    "strengths": {}
  }
}
```

`value` is the number of distinct retained evidence items matching that series
inside the bucket. `confidence` is the mean confidence of matching rules for
the series, rounded to three decimals. Source IDs, evidence references,
capture generations, rule version, signal IDs, and rationales make the result
traceable. A zero is valid only in an **observed bucket** whose evidence matched
no rule for that series. An absent bucket is a **gap**, never zero.

## `network-trend-rationalization.v1` rules

Rules are deterministic and independently additive. Within one evidence item,
multiple reasons for the same series produce one series value and retain all
bounded rationales/signals.

| Series | Stable signal | Evidence condition | Confidence |
|---|---|---|---:|
| Threats | `known_malicious` | Reviewed source marks evidence known malicious | 1.00 |
| Threats | `suspicious` | Retained source has a suspicious review signal | 0.85 |
| Threats | `severity:{level}` | Critical, high, warning, or medium severity | 0.95 / 0.85 / 0.70 / 0.65 |
| Vulnerabilities | `unknown_external_owner` | External traffic lacks identified application ownership | 0.80 |
| Vulnerabilities | `unresolved_external_destination` | External traffic lacks DNS, HTTP host, TLS SNI, or another distinct readable destination | 0.70 |
| Vulnerabilities | `low_attribution_confidence` | External attribution confidence is low | 0.60 |
| Vulnerabilities | `cleartext_http` | Protocol is HTTP or destination port is 80 | 0.85 |
| Strengths | `identified_owner` | Application is identified with high confidence | 0.85 |
| Strengths | `readable_destination` | Retained evidence includes a readable destination distinct from an IP-only fallback | 0.70 |
| Strengths | `encrypted_service` | TLS, HTTPS, QUIC, or reviewed encrypted service port | 0.80 |
| Strengths | `local_scope` | Destination is local/private network scope | 0.65 |

Reclassification occurs only by publishing a new rule version and recomputing
the derived projection. Factual observations and prior evidence references
remain unchanged. This checkpoint does not persist an interpretation back into
the factual Timeline.

## State and gap contract

- **Loading / refreshing:** established Network request state and copy remain
  authoritative.
- **Observed bucket:** has one or more deduplicated retained evidence items and
  may contain zero for a particular series.
- **Gap:** no retained evidence covers that bucket. Graph renders a labeled,
  hatched gap; Chart renders an em dash and `Gap` evidence state.
- **Partial coverage:** summary exposes `gap_count`, coverage state/start,
  history source counts, rule version, and zero/missing meanings.
- **No data:** projection has no interpreted buckets and preserves a durable
  gap receipt through the existing preservation path.
- **Unavailable/degraded:** the exact collector/capture reason remains visible;
  retained interpreted buckets may still render when the projection succeeds.
- **Contradiction:** `contradiction_count` records evidence supporting Strengths
  and either Vulnerabilities or Threats in the same source item.

No interpolation occurs. No absent bucket is drawn as a value. HTTP failure is
not converted into an empty successful projection.

## Controls, ordering, and parity

The Trend range toolbar retains all nine established windows. Trend adds:

- Graph/Chart toggle in `.network-graph-toggle` using
  `[data-network-trend-display]` and `aria-pressed`;
- series filter buttons using `[data-network-trend-series]` and
  `aria-pressed`;
- series order selector `[data-network-trend-sort]` with `canonical`,
  `value_desc`, and `alphabetical` options;
- the existing `Refresh Network` action.

At least one series must remain visible. Canonical order is Vulnerabilities,
Threats, Strengths. Highest-signal order uses the aggregate value over the
selected range with an alphabetical tie break. Sorting changes series order,
never chronological bucket order.

Graph and Chart are two renderings of `networkTrendDataset(events)`. They share
the same selected range, filtered series, ordering, bucket boundaries, values,
gaps, evidence references, rule version, and rationales. Graph uses grouped
series bars and explicit hatched gaps. Chart uses one chronological row per
bucket. Controls persist in URL/local storage without altering evidence.

All controls are native keyboard-operable elements. Focus-visible outlines are
required. Bars are buttons with accessible series/value/range names. Tooltips
show rationale, confidence, contradiction notice, rule version, and time range.
Selecting evidence continues to bind the exact bucket to `ctrl`; no remediation
is executed.

## Responsive geometry and selectors

The Network shell remains the five-row grid with the permanent `44px`
Wireshark provider row. Trend uses:

```css
#network #network-results:has(.network-trend-window) {
    grid-template-rows: minmax(250px, 1fr);
    overflow: hidden;
}

.network-trend-window {
    height: calc(100% - 10px);
    margin: 0 auto;
    max-width: 1280px;
    min-height: 240px;
    overflow: hidden;
    width: 100%;
}

.network-trend-content {
    overflow: auto;
    overscroll-behavior: contain;
}
```

The effective geometry is:

```text
Trend top    = toolbar bottom + 8px
Trend height = results-row height - 10px
Trend bottom = provider row top - 18px
Provider     = permanent 44px row
```

The window is centered, responsive, and left aligned. Page-level Network
overflow remains hidden. The Trend content area alone owns local overflow.
Graph has a `640px` local minimum; Chart has a `660px` local minimum, so portrait
layouts scroll inside the Trend window instead of moving the shell, provider,
or `ctrl`. At `980px` and below, the header stacks and controls remain left
aligned.

## Implementation paths

- `backend/api/cleanhouse.py`
- `frontend/investigations.html`
- `frontend/js/investigations.js`
- `frontend/css/investigations.css`
- `tests/test_network_trend_interpretation.py`
- `tests/test_network_header_static.py`
- `tests/network_resilience_node.test.mjs`
- this document

## Validation commands

The reproducibility receipt for this boundary is
[`../20_validation/network-trend/README.md`](../20_validation/network-trend/README.md).
Its manifest fixes the eleven reviewed implementation and verification paths,
records the three excluded runtime/preservation paths, and proves the Trend-only
delta by replaying it in an isolated temporary tree. The receipt is validation
evidence; it does not expand this implementation contract or modify master
canon.

```bash
cleanhouse_env/bin/python3 -m unittest -v \
  tests.test_network_trend_interpretation \
  tests.test_network_header_static \
  tests.test_network_capture_truth
node --test tests/network_resilience_node.test.mjs
node --test tests/network_table_ctrl_resilience_node.test.mjs
node --check frontend/js/investigations.js
cleanhouse_env/bin/python3 -m py_compile backend/api/cleanhouse.py tests/test_network_trend_interpretation.py
cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py
```

Browser acceptance must cover `768x1024`, `1024x640`, `1440x900`, and
`1728x1117`, all range controls, Graph/Chart parity, each series filter, each
sort order, refresh/reload continuity, keyboard traversal, `ctrl` evidence
binding, exact `8px`/`18px`/`44px` geometry, no page overflow, no unexpected
console errors, and no failed asset/API requests. Source/runtime hashes must
match before live claims.

## Failure and limitations

- Capture-provider absence remains an explicit degraded state; retained Trend
  interpretation does not upgrade collector health.
- Interpretation quality is limited to retained fields. It does not infer
  actor intent, authorization, exploitability, or malware verdicts.
- IP-only destination evidence does not earn readable-destination Strength.
- Existing count-only historical buckets remain preserved but are not migrated
  or displayed as interpreted Trend.
- `1mo`, `3mo`, and `12mo` use the existing fixed-duration Network range
  contract; this checkpoint does not introduce calendar-month semantics.
- Authenticated browser acceptance requires an existing approved owner session;
  this checkpoint does not create accounts, alter providers, or bypass auth.
