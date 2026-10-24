# Network Table Implementation Proposal

> This document implements the Network Product Contract.

Status: Draft with approved bounded implementation receipts  
Approval: Partial; only explicitly identified receipts are approved  
Authority: Subordinate implementation contract under the locked Network Product Contract

## Purpose

This document is the separate home for possible implementation strategies for
the Network Table. It does not define or modify product behavior. The locked
[Network Product Contract](network-product-contract.md) defines WHAT operators
must experience and which evidence guarantees must remain true.

This proposal defines HOW only after its decisions are explicitly approved.
Until then, every undecided implementation area remains `TBD`.

## Authority Boundary

The implementation is free to choose algorithms, storage, APIs, collectors,
live transports, SSE events, caching, pagination, lifecycle mechanics, browser
behavior, and data structures so long as every observable behavior satisfies
the locked Network Product Contract.

This proposal may compare multiple implementation strategies and tradeoffs. It
must not lock a strategy, select a default, or reinterpret the Product
Contract while its approval remains pending.

## Decision Register

| Implementation area | Status | Approval requirement |
|---|---|---|
| Table row representation | `TBD` | Demonstrate that the proposed representation satisfies every observable Table requirement without redefining the product |
| Row identity mechanics | `TBD` | Prove deterministic evidence attribution and protection against unsupported merging or splitting |
| Row creation mechanics | `TBD` | Prove that no row can exist without reproducible immutable Wireshark packet evidence |
| Row enrichment mechanics | `TBD` | Prove additive enrichment without rewriting observed packet facts |
| Completion mechanics | `TBD` | Preserve visible observed-versus-inferred completion semantics |
| Interruption mechanics | `TBD` | Preserve visible continuity-unknown semantics without bridging evidence gaps |
| Removal and visibility mechanics | `TBD` | Preserve access to supporting evidence after a row leaves the visible Table |
| Protocol-specific behavior | `TBD` | Demonstrate contract-equivalent observable behavior across supported protocols |
| Timeout and visible-window values | `TBD` | Document operator-visible effects and evidence consequences before approval |
| Storage and retention implementation | `TBD` | Preserve immutability, traceability, reviewability, and reproducibility |
| APIs and schemas | `TBD` | Expose every contract-required observable state without making derived data appear observed |
| Collectors and live transports | `TBD` | Preserve capture scope, limitations, interruptions, and dropped-evidence truth |
| SSE and other update transports | `TBD` | Preserve observable ordering, enrichment, completion, and interruption behavior |
| Caching and pagination | `TBD` | Prevent hidden evidence loss, fabricated continuity, or selection-driven reordering |
| Browser rendering and update behavior | `APPROVED: CONNECTIONS-LAYOUT-004` | Preserve the Table's observable contract under live updates and operator interaction |
| Algorithms and data structures | `TBD` | Remain replaceable without changing operator-visible behavior or evidence guarantees |
| Verification and rollout | `TBD` | Produce a section-by-section compliance report against the locked Product Contract |

## Strategy Evaluation Rules

Any candidate strategy must be evaluated only by asking whether its observable
behavior satisfies the Product Contract.

Candidate strategies may differ internally. Approval requires proof that they:

- reproduce every Table row from immutable Wireshark packet evidence;
- preserve observed packet facts unchanged;
- keep derived information traceable and explicitly distinguished;
- expose completion, interruption, removal, ordering, and Translation exactly
  as the Product Contract requires;
- never substitute app inventory, socket snapshots, synthetic fixtures, or
  fallback evidence for Wireshark evidence;
- leave other Network tabs and product contracts outside the Table
  implementation scope.

## Approved implementation receipt: CONNECTIONS-LAYOUT-004

This receipt retains `CONNECTIONS-LAYOUT-003`'s fluid tall-window behavior and
supersedes its table-to-provider clearance. It also retains the earlier removal
of `CONNECTIONS-LAYOUT-001`'s fixed `620px` cap.

### Scope and compatibility

- The primary visible Network tab label is **Connections**.
- Product semantics remain the locked Network Product Contract's Table
  perspective. Existing DOM, URL, storage, API, render, replay, selection, and
  test identifiers remain `table`; `network_view=table` remains compatible.
- Findings, Trend, Distribution, Timeline, Network header truth, refresh/live
  update behavior, row selection, `ctrl`, and capture-state semantics are not
  changed by this receipt.

### Application shell and viewport geometry

When `#network` is visible, the application shell is a `100vh` bounded frame
with zero desktop bottom padding. Its Network main canvas has `height: 100%`,
`min-height: 0`, and `overflow: hidden`. The Network section is centered and
uses:

```css
width: min(1280px, calc(100vw - 146px));
grid-template-rows: auto auto auto minmax(0, 1fr) 44px;
padding: clamp(20px, 5vh, 58px) 0 0;
gap: 8px;
```

The rows are, in order: heading, evidence-backed status, tab/refresh toolbar,
scrollable results, and permanent provider attribution. The section and main
canvas both clip page-level overflow; Network content scrolls only inside the
owning results or Connections table viewport.

The Connections viewport is horizontally centered, `width: 100%`, and has an
explicit `1280px` maximum width. It is never vertically centered. Its top edge
is anchored at the start of the results row, exactly one ordinary `8px`
Network grid gap beneath the tab/Refresh row. Its height is:

```css
grid-template-rows: minmax(250px, 1fr); /* 240px table + 10px clearance */
height: calc(100% - 10px);              /* table fills row minus clearance */
align-self: start;
min-height: 240px;
```

There is no fixed tall-window maximum. The Connections bottom edge equals the
results-row bottom minus `10px`. The final ordinary `8px` grid gap then
separates the results row from the permanent `44px` provider row, producing
`18px` of total table-to-provider clearance and breathing room for the
bottom-right `ctrl` control. The effective relationship is:

```text
Connections height = Network results-row height - 10px
Connections top    = Network toolbar bottom + 8px
Connections bottom = provider row top - 18px
```

At widths up to and including `980px`, the shell changes to one column with
`grid-template-rows: auto minmax(0, 1fr)`, `14px` shell padding, and a
horizontally scrollable navigation row. The `250px` results-row minimum
preserves a `240px` minimum Connections viewport plus the `10px` internal
clearance without viewport-coordinate branching or moving the provider row.

The minimum verified desktop application window is `1024 × 640`, and
`768 × 1024` is the verified portrait window. Below either tested minimum, the
shell remains bounded but complete operator usability is outside this receipt.

Browser-computed geometry for the approved formula is:

| Application viewport | Connections height | Toolbar-to-Connections gap | Connections-to-provider gap |
|---|---:|---:|---:|
| `768 × 1024` | `583px` | `8px` | `18px` |
| `1024 × 640` | `301px` | `8px` | `18px` |
| `1440 × 900` | `548px` | `8px` | `18px` |
| `1728 × 1117` | `754.15625px` | `8px` | `18px` |

These measurements use the same rendered Network status sample at each size;
status wrapping may change the absolute result-row height, but the formula,
`8px` top gap, and `18px` final bottom clearance remain invariant. The last
pair proves that increasing available application height grows Connections
beyond the superseded `620px` cap.

### Overflow and alignment

- The result region is centered, `width: 100%`, `max-width: 1280px`, and owns
  any non-table vertical overflow. When it contains Connections, its single
  `minmax(250px, 1fr)` row gives the table the full available results height
  minus the exact `10px` internal clearance. The table remains aligned to the
  row's top edge; its bottom stays `18px` above the provider row after the
  ordinary grid gap. Result-level overflow is clipped so only the table's
  internal scrollers can move rows or columns.
- The Connections table has `min-width: 1180px`. When the window is narrower,
  horizontal scrolling belongs to `.network-table-wrap`; page-level horizontal
  overflow is prohibited.
- The table body height is `calc(100% - 34px)` and owns vertical row scrolling.
  The header stays visible in the table shell.
- Column headers and cells remain left-aligned. Column widths, ordering,
  selected/affected row treatments, sorting, and resize controls remain
  unchanged.

### Permanent Wireshark attribution

`#network-provider` occupies the final `44px` Network grid row with
`position: relative`, `width: 100%`, and centered content. It is never table
content and never overlays rows. The provider remains visible on Connections,
Findings, Trend, Distribution, and Timeline at all verified sizes. Its
`data-provider-state` and accessible label continue to disclose verifying,
verified, or unavailable truth; layout never upgrades provider state.

### Resize, evidence, and interaction invariants

- Resizing is CSS-only. It does not change `networkViewMode`, URL state,
  selected rows, pinned-row evidence, `ctrl` subjects, replay cursors, polling,
  or live buffers and does not initiate an evidence request.
- Refresh Network remains the only operator refresh control and keeps its
  existing evidence lifecycle.
- Native tab buttons, table rows, sort controls, resizers, navigation, Refresh
  Network, and `ctrl` remain keyboard reachable with their existing visible
  focus behavior and accessible names.
- The same HTML/CSS contract applies in the browser and the desktop wrapper;
  no screenshot coordinates or wrapper-only geometry are used.
- Capture unavailable/degraded/warming/no-data/offline/retrying/recovered
  states remain evidence-derived. General application readiness never becomes
  capture health, and layout never fabricates packets or availability.

### Validation contract

Focused source gates:

```text
cleanhouse_env/bin/python3 -m unittest -v tests.test_network_header_static tests.test_ctrl_panel_static
node --test tests/network_resilience_node.test.mjs tests/network_table_ctrl_resilience_node.test.mjs
node --check frontend/js/investigations.js
cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py
git diff --check -- frontend/investigations.html frontend/css/investigations.css tests/test_network_header_static.py documents/00_start-here/network-table-implementation-proposal.md AGENTS.md
```

Authenticated resize acceptance verifies `768 × 1024`, `1024 × 640`,
`1440 × 900`, and `1728 × 1117`. At each size it checks page
identity, all five tabs, Connections header/cell alignment, internal scroll
ownership, absence of horizontal page overflow, footer visibility and
non-collision, retained selection/view state, request stability during resize,
console health, and one interaction state change.

### Known limitations

- Below `1024 × 640` for desktop orientation or `768 × 1024` for portrait, the
  shell remains bounded but this receipt does not claim complete operator
  usability.
- Connections intentionally keeps an `1180px` table minimum for readable
  columns, so narrower windows require table-local horizontal scrolling.
- This receipt does not redesign evidence semantics or authorize a different
  row identity, retention policy, capture provider, or Network mutation.

## Approval Gate

This draft authorizes no implementation choice except the exact bounded
receipts identified as approved above.

Before application code is written, each required decision must move from
`TBD` to an explicitly approved implementation contract. Approval of an
implementation decision does not amend the Product Contract.
