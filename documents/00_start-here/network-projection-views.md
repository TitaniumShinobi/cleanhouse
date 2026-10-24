# Network Distribution, Timeline, and ctrl contract

## Authority and boundary

This subordinate contract owns the three Network projections that share
selected evidence outside Connections, Findings, and Trend. It implements the
Network canon in `CLEANHOUSE.md` and the shared assessment taxonomy; it does
not classify evidence independently.

## Distribution

Distribution answers:

> Which attributable software owners account for the currently observed
> Network activity?

- One donut and one matching owner list consume the same bounded packet-backed
  rows.
- Slice/list identity, order, normalized name, color, total, proportion, and
  evidence references agree exactly.
- Only software with observed Network activity appears. Installed, running, or
  GUI-open inventory does not create an owner share.
- Unattributed evidence remains visible as `Unknown app`; uncertain ownership is
  never presented as fact.
- Code and Codex remain distinct normalized identities.
- Empty packet evidence produces an evidence-backed empty state, never a
  populated application inventory.
- The wheel stays left-aligned at every viewport. The same list sits to its
  right when the result window has room for the 190px wheel, 28px gap, and
  240px list basis; otherwise it wraps underneath at the same left edge.
  Long owner names wrap without pushing counts outside the result window.
- The existing duplicate Open Applications section remains absent. Its
  packet-backed compatibility alias is not rendered as a second dataset;
  installed/running inventory cannot populate the wheel or list.
- `summary.owners` is authoritative even when empty. Only positive, finite,
  safe integer observed-event counts form shares. Ordering is descending
  count with name/identity tie breaks. Display normalization trims and
  collapses whitespace; collector-provided identity and evidence stay intact.
  It does not infer a product from a process substring or merge Code/Codex.
- For legacy payloads without `summary.owners`, group only supplied projection
  events by their observed owner name, retaining event and assessment refs.
  This compatibility path never consults an application inventory.
- Counts are observed network events, not active connections. Both matching
  slice and list item expose the owner and event count as an accessible name;
  the SVG group exposes its keyboard-selectable slices. Existing click,
  Enter/Space selection and paired hover/focus behavior remain unchanged.

`Graph` selects Trend and `Chart` selects Distribution. This duplicate
navigation remains visible on both visual tabs and has identical placement.

## Timeline

Timeline answers:

> Which notable events, assessment transitions, and continuity gaps occurred,
> and what exact evidence belongs to each moment?

- Events retain stable identity, evidence time, ingest time, generation,
  sequence/cursor, source classification, assessment references, and bounded
  raw evidence references.
- Routine packets are not promoted into notable events merely to populate the
  line.
- Gaps are explicit events and never interpolated away.
- A marker may group a display interval, but selecting it exposes every
  contained event individually in deterministic order.
- A grouped marker never binds `ctrl` to one arbitrary finding.
- Refresh aligns with Connections and Findings and cannot erase retained
  history or duplicate replayed events.

## ctrl

`ctrl` is a selected-evidence context and control surface, not a classifier.

- A selected Connections row binds its connection and assessment references.
- A selected Finding binds its stable assessment and grouped evidence.
- A selected Trend bucket binds all bounded evidence and assessment IDs for
  that bucket and selected metric.
- A selected Distribution share binds the exact owner rows represented by its
  donut slice/list item. The selection uses the projection's stable
  `network-owner:<digest>` identity (with `distribution:<owner>` accepted only
  for compatibility) and carries bounded evidence and assessment references
  as separate fields; it never
  resolves through one arbitrary packet reference or inherits that packet's
  destination as the aggregate subject.
- A selected Timeline event binds that exact event; an interval first exposes
  its individual events for selection.
- Rationale comes from the shared backend assessment. `ctrl` never rewrites a
  category.
- `More actions` exposes only existing authorized capabilities. Selection does
  not execute remediation or grant new authority.
- Opening `ctrl` does not automatically invoke inference.

## Shared failure and accessibility behavior

- Loading, empty, warming, unavailable, degraded, offline, partial-failure,
  error, retrying, and recovered remain distinct.
- Runtime readiness and capture health remain separate.
- Retained projections may remain readable while capture is degraded, with the
  exact provider state still visible.
- Controls are keyboard reachable, use visible focus, expose accessible names,
  announce state changes, and never rely on category color alone.
- Each result window remains directly below the toolbar, horizontally centered,
  left-text-aligned, internally scrollable, and clear of the provider and
  `ctrl` rails.

## Focused acceptance

Acceptance proves:

1. Distribution donut/list identity and zero-evidence exclusion.
2. Graph/Chart visibility and navigation on Trend and Distribution.
3. Timeline interval expansion exposes every event and binds exact selection.
4. Replay is idempotent and gaps remain explicit.
5. `ctrl` receives the same evidence and assessment IDs as the selected source.
6. Refresh preserves retained evidence and does not duplicate records.
7. Desktop, portrait, landscape, and mobile layouts preserve internal scrolling,
   focus, labels, announcements, provider attribution, and rails.

### Distribution slice verification (2026-10-22)

Focused frontend command:
`node --test tests/network_distribution_slice_node.test.mjs tests/network_completion_node.test.mjs tests/network_trend_slice_node.test.mjs`.
The Distribution test covers authoritative empty owners, invalid/zero counts,
stable matching identities and evidence, legacy packet fallback, accessible
event labels, and single-owner geometry. Existing backend Distribution tests
verify the packet-only source and shared owner/compatibility dataset.

Source and synthetic tests cannot establish authenticated canonical rendering
or real capture. An unaccepted-policy gate must remain fail-closed; browser
acceptance behind that gate remains a human-only boundary. No consent, auth,
runtime lifecycle, backend classification, Timeline, or ctrl action changes
belong to this slice. Staging/activation require their own exact-byte receipts.
