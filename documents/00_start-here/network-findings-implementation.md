# Network Findings implementation contract

## Approved boundary: CONNECTIONS-FINDINGS-LAYOUT-001

This is the authoritative subordinate contract for the implemented Network
Findings checkpoint. Code and this contract move together. A report or final
summary is not a substitute for this file.

The checkpoint implements the responsive Findings results window while
preserving the established grouped, priority-retained review queue. The owner
explicitly authorized the corresponding Network-only corrections in
`CLEANHOUSE.md`; non-Network canon, authentication, and runtime readiness stay
outside this boundary.

## Product boundary and truth

Findings answers: **which retained Network conditions currently warrant
review?** It is not the live Connections feed, a packet list, an open-socket
inventory, a list of running applications, a malware verdict, or proof that a
condition is authorized or malicious.

- A visible finding is a derived review item backed by retained Network
  evidence.
- Every finding consumes the backend-owned
  `cleanhouse.security_assessment.v1` identity and category; browser code does
  not reclassify evidence.
- Repeated related events may be grouped into one semantic finding; the
  originating and related evidence identifiers remain attached.
- Priority outranks freshness. Routine traffic cannot displace a retained
  higher-priority item.
- The headline count is the number of grouped findings returned for display,
  not the number of packets, sockets, or raw events.
- Capture health and retained Findings availability are independent. A
  degraded collector may coexist with retained findings; the header still
  reports the collector failure truthfully.
- An HTTP or projection failure is an unavailable/degraded result, never a
  successful empty queue.
- `Powered by Wireshark` remains permanent provider attribution. It does not
  by itself claim that capture is currently operational.

## Architecture and data provenance

```text
reviewed Wireshark capture evidence
    -> normalized Network event spine
    -> bounded retained events
    -> open/review-worthy filter
    -> semantic signature grouping
    -> priority ordering
    -> bounded Findings projection
    -> Network render coordinator
    -> Findings window
```

The browser requests:

```text
GET /cleanhouse/network/projection?view=findings&range={selected-range}
```

through `CleanHouseAPI.getNetworkProjection()`. The endpoint starts or checks
the existing collector, performs a bounded refresh only when explicitly
requested, attaches collector cursor/high-water evidence, and returns the
existing Network UI contract. The browser stores only a render-ready copy in
the existing coordinator/cache; it does not invent findings locally.

The backend projection is intentionally a retained queue rather than a narrow
time-series view:

- evidence lookback: at most `50,000` retained events;
- Findings lookback: at most `10,000` retained events;
- projection history ceiling: the established `12mo` retained window;
- visible grouped result cap: `100` findings;
- cache lifetime: `15s`;
- retained related-event identifiers per finding: at most `8`;
- retained related destinations per finding: at most `8`.

Review-worthiness comes from the shared assessment contract and retained
evidence. A finding renders category, severity, confidence, lifecycle, owner
disposition, rule/version, rationale, subject, and bounded evidence references.
Category remains Strength, Vulnerability, or Threat while severity, confidence,
lifecycle, and owner disposition vary independently. Operational collector or
provider health never becomes a category. The highest-priority representative
remains visible while bounded related evidence is retained.

Initial reviewed Network classification preserves these distinctions:

- unknown externally active application: Vulnerability;
- missing destination identity: Vulnerability;
- unusual port, new destination, traffic volume, or repeated attempt alone:
  neutral indicator;
- verified encryption, attribution, authorization, or effective containment:
  eligible Strength evidence;
- verified malware, malicious endpoint, active exfiltration, unauthorized
  inbound access, exploitation, or containment bypass: eligible Threat
  evidence.

An allowed, acknowledged, blocked, or contained Threat remains a Threat;
lifecycle and owner disposition explain its treatment.

Ordering is deterministic by severity, confidence, system impact, suspicious
signal, first-seen time, and stable event identifier. Closed, dismissed,
invalidated, resolved, or superseded findings are not shown as open findings.

## Exact implementation selectors

The Network shell remains the existing bounded five-row grid: heading, status,
toolbar, results, and the permanent `44px` Wireshark provider row. Findings
uses these selectors:

```css
#network #network-results:has(.network-findings-window) {
    align-content: stretch;
    grid-template-rows: minmax(250px, 1fr);
    overflow: hidden;
}

.network-findings-window {
    align-self: start;
    height: calc(100% - 10px);
    margin: 0 auto;
    max-width: 1280px;
    min-height: 240px;
    overflow: hidden;
    text-align: left;
    width: 100%;
}

.network-findings-feed {
    height: 100%;
    max-height: none;
    overflow: auto;
    overscroll-behavior: contain;
    scrollbar-gutter: stable;
}
```

The `250px` results-row minimum preserves a `240px` Findings window and the
internal `10px` bottom clearance. The ordinary Network grid gap adds another
`8px`, so Findings ends `18px` above the permanent provider row. Its top edge
is exactly `8px` below the toolbar. The effective geometry is:

```text
Findings height = Network results-row height - 10px
Findings top    = Network toolbar bottom + 8px
Findings bottom = provider row top - 18px
```

The window is horizontally centered at the Network shell's responsive width
and capped at `1280px`. At widths up to `980px`, the existing single-column
Network shell supplies the portrait layout without moving Findings, the
provider, or `ctrl` into a different document flow.

The responsive width is `min(100%, 1280px)`. There is no artificial fixed
minimum width; the existing `minmax(0, 1fr)` Network shell permits portrait
contraction. The accepted minimum height is `240px`. There is no artificial
maximum height: the window expands with the available results row.

Each finding has `12px 14px` padding. Its summary is `17px` with `1.25` line
height. Fade geometry uses `72px` transitions and `144px` bottom scroll
padding.

## Rendered components and controls

| Component | Selector / function | Contract |
|---|---|---|
| Results row | `#network #network-results:has(.network-findings-window)` | Owns the available Findings region and clips page-level overflow. |
| Window | `.network-findings-window` | Horizontally centered, responsive, left aligned, and bounded below the toolbar. |
| Local scroller | `.network-findings-feed` | Sole vertical scroll owner; preserves snap and fade cues. |
| Finding | `.network-finding-item` / `renderNetworkFindings()` | Native collapsed `<details>` with category, summary, priority, confidence, lifecycle, rule, rationale, context, and evidence action. |
| Priority | `.network-priority-tag` / `networkFindingPriority()` | Critical, High, Medium, or Low from normalized severity. |
| Evidence binding | `networkEvidenceAttributes(event, 'findings')` | Preserves entity, raw reference, source view, and related IDs for `ctrl`. |
| Evidence action | `.network-findings-body-action-link` | Keyboard/click action opens `ctrl` for that exact finding; it does not execute remediation. |
| Scroll state | `bindNetworkFindingsWindow()` / `updateNetworkFindingsFade()` | One stable resize callback resolves the current feed and updates top/bottom fades without reloading data or retaining detached feeds. |

Native `<details>` owns expand/collapse. Findings are collapsed by default.
The summary remains keyboard operable. The evidence action handles click,
Enter, and Space; it prevents the same event from toggling the surrounding
details element or clicking through to another surface.

## Scrolling and interaction ownership

- The application page and Network main canvas remain non-scrolling bounded
  frames.
- `#network-results` clips Findings overflow.
- `.network-findings-window` clips decorative overflow.
- `.network-findings-feed` alone owns vertical Findings scrolling.
- `overscroll-behavior: contain` prevents a wheel or trackpad gesture from
  escaping into the page.
- `scrollbar-gutter: stable` prevents width shifts when the scrollbar appears.
- Findings text, priority labels, reason, context, and evidence links remain
  left aligned.
- Native `<details>` expansion, retained ordering, severity/priority labels,
  evidence attributes, the body link to `ctrl`, fade cues, and scroll snapping
  remain unchanged.
- Resize handling updates only the existing fade state. It does not refresh,
  reproject, reorder, or discard evidence.
- Empty, loading, unavailable, degraded, and retained states continue to come
  from the established Network render model; layout never upgrades state.

## State and transition contract

```text
select Findings
    -> render existing settled projection or Findings placeholder
    -> loading / refreshing copy while request is active
    -> ready with grouped findings
       OR evidence-backed empty
       OR degraded/unavailable with exact capture reason
```

- Initial copy: `Grouped findings will load when Findings opens.`
- Loading copy: `Loading grouped network findings.`
- Refresh copy: `Refreshing grouped network findings.`
- Empty copy: `No grouped findings.`
- Rendered empty body: `No review-worthy network findings are visible in this window.`
- Capture reasons remain the established `engine_unavailable`,
  `permission_blocked`, `capture_failed`, `capture_backlog`, and
  `continuity_gap` mappings.
- Retained findings remain visible during capture degradation when the
  projection succeeds.
- Request aborts caused by a newer view, range, or epoch are dropped rather
  than rendered as failures.
- A non-abort projection exception renders the established unavailable state.
- Manual `Refresh Network` synchronizes the snapshot and active Findings
  projection, invalidates bounded projection caches, and does not duplicate or
  erase retained findings.
- Resize updates only the fade state. It does not refresh, regroup, reorder,
  or discard evidence.

## Verified responsive geometry

The required browser viewports are `768x1024`, `1024x640`, `1440x900`, and
`1728x1117`. Absolute height depends on status wrapping; every size must prove
the invariant `8px` toolbar gap, `18px` provider clearance, permanent `44px`
provider row, no Findings/`ctrl` collision, and no page-level overflow.

The measurements below are the historical receipt for the earlier responsive
layout checkpoint. They used fresh, real local Network evidence in an isolated
auth-disabled harness and did not use synthetic findings. They are not proof
of the current shared-assessment candidate; that candidate requires fresh
browser acceptance before closure.

| Viewport | Findings height | Toolbar gap | Provider gap | Provider row | `ctrl` gap | Page overflow |
|---|---:|---:|---:|---:|---:|---|
| `768x1024` | `583px` | `8px` | `18px` | `44px` | `14px` | none |
| `1024x640` | `301px` | `8px` | `18px` | `44px` | `6px` | none |
| `1440x900` | `548px` | `8px` | `18px` | `44px` | `6px` | none |
| `1728x1117` | `754.15625px` | `8px` | `18px` | `44px` | `6px` | none |

All four viewports proved `max-width: 1280px`, `min-height: 240px`, left
alignment, no Findings/`ctrl` overlap, no `ctrl`/provider overlap, and no
horizontal or vertical page overflow. At `1024x640`, the feed measured
`301px` client height and `407px` scroll height, proving local scrolling.
Opening the first finding kept all `9` findings, preserved its evidence entity
and one `ctrl` action, increased local scroll height to `474px`, and still
produced no page overflow.

Browser console errors and warnings were both zero. The isolated test process
was stopped and its port was released after measurement.

## Validation

Run only focused proof:

```bash
cleanhouse_env/bin/python3 -m unittest -v \
  tests.test_network_header_static tests.test_ctrl_panel_static
node --test \
  tests/network_resilience_node.test.mjs \
  tests/network_table_ctrl_resilience_node.test.mjs
node --check frontend/js/investigations.js
cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py
git diff --check -- \
  frontend/css/investigations.css \
  tests/test_network_header_static.py \
  documents/00_start-here/network-findings-implementation.md
```

Browser acceptance measures the four required viewports against the canonical
authenticated runtime. If owner-controlled authentication is unavailable, the
same source is measured in an isolated auth-disabled local harness and that
limitation is reported; auth is never bypassed on the canonical runtime.

Historical proof for the earlier responsive-layout checkpoint (not proof of
the current shared-assessment implementation):

- Python focused tests: `34/34` passed.
- Node focused tests: `45/45` passed.
- JavaScript syntax: passed.
- Protected surfaces: `11/11` passed.
- Browser console errors/warnings: `0/0`.
- Source/runtime stylesheet SHA-256:
  `08b73d2f5d03669e66c9643b9b32f2732015d57a9681ee329bcffe150418f70f`.
- Canonical runtime: one owned listener on `127.0.0.1:3333`, liveness `ok`,
  operator readiness satisfied, all `11/11` readiness checks true.

## Failure states and operator interpretation

| Condition | Findings behavior |
|---|---|
| No review-worthy retained evidence | Evidence-backed empty copy; count `0 findings.` |
| Projection loading or refreshing | Explicit loading/refreshing copy; no fabricated items. |
| Capture engine unavailable | Header remains degraded/offline with exact reason; retained findings may remain reviewable. |
| Permission blocked | Explicit capture permission failure; no operational-capture claim. |
| Capture backlog | Explicit delayed-ingestion state; existing evidence is not rewritten as current. |
| Continuity gap | Explicit gap reason; no continuous-coverage claim. |
| Projection request fails | Unavailable/error presentation, never a successful empty queue. |
| Newer request supersedes an older request | Older response is discarded by epoch/request identity. |
| Content exceeds window | Local feed scroll and fades; shell, provider row, and `ctrl` remain stationary. |

## Known limitations and exclusions

- Findings uses the bounded `12mo` retained review queue. It does not inherit
  Trend's selected range, and its response labels the source as a bounded
  retained priority queue rather than presenting the caller's range as the
  Findings window. A narrower Findings time filter is not implemented by this
  checkpoint.
- Only the first `100` grouped findings are rendered; the current UI does not
  yet disclose omitted grouped-result counts.
- Below the verified `1024x640` desktop or `768x1024` portrait windows, the
  shell remains bounded but complete operator usability is not claimed.
- Authenticated canonical browser acceptance remains owner-session dependent;
  this checkpoint used isolated browser geometry plus canonical source/runtime
  parity without changing authentication.
- Layout does not install, configure, or imply operational packet capture.
- Shared assessment identity is additive to Connections, Trend, Distribution,
  Timeline, and Network `ctrl`; their established view meanings and provider
  truth remain unchanged.
- No staging, commit, push, deployment, data deletion, evidence cleanup, or
  product-surface removal belongs to this checkpoint.
- The Network section of `CLEANHOUSE.md` contains the owner's explicit canon
  corrections for the visible Connections label, shared taxonomy, Trend
  metrics, Graph/Chart duplicate navigation, and one-list Distribution.
  Non-Network canon remains unchanged.

## Bounded resize lifecycle repair — 2026-10-21

`updateNetworkFindingsFade()` is the stable scroll/resize listener identity.
`bindNetworkFindingsWindow()` can run after every render without accumulating
window resize listeners: the DOM deduplicates the same callback/capture pair.
The callback queries the current Findings window at event time and returns
when no Findings feed is mounted. It does not retain previous DOM nodes,
load data, change ordering, or alter details, selection, evidence, or consent.
Existing width/height/toolbar geometry, native snapping, and fade thresholds
remain exactly as specified above.

Focused lifecycle proof: `node --test tests/network_findings_resize_node.test.mjs`.
It covers repeated bindings, replacement feeds, unmounted Findings, and both
fade boundaries using isolated event targets. This is source-level proof;
no browser opening, live activation, or pixel-geometry acceptance belongs to
this pass. Historical browser measurements above remain historical.
