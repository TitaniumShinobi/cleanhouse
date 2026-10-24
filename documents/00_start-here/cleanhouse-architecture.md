# CleanHouse Architecture

Status: supervised architecture spine draft. Network product semantics are locked in the [Network Product Contract](network-product-contract.md); this document does not redefine them.

## Shared CSS

Pending supervised documentation.

## Shared Features & Behaviors

Pending supervised documentation.

## Role Architecture

CleanHouse uses specialist evidence roles, but it does not turn every role into a frontend chatbot. User-facing voices are limited and evidence-bound; backend roles provide discovery, validation, synthesis, command discipline, and preservation.

### User-Facing Voices

- Insight is the Actions voice. Insight explains selected evidence, why it matters, and the next available steps from the Evidence Command Center.
- Valorie is the validation voice for Zaelith and proof language. Valorie explains confidence, gaps, and whether a claim is supported by evidence.
- Aurora is the reports clerk. Aurora turns validated evidence into reports, report narratives, exports, and letters of concern.

### Backend Synthesis Roles

- Auditor, Quality Control, and Valorie synthesize report-grade review across system, network, files, applications, LLM audit results, and other evidence surfaces.
- CLICK and Day-Day synthesize Network behavior. CLICK preserves command/action discipline, while Day-Day owns network data continuity, trend, timeline, gaps, and network interpretation inputs.
- Clean applies everywhere as the organization, preservation, hygiene, and consistency layer.
- Scout owns Files discovery and file evidence context.

### Role Boundaries

- Zaelith is a tool surface, not a conversational voice: text in, audit out.
- No role may create unsupported claims. User-visible role output must be anchored to `evidence_key`, `evidence_refs`, and traceable action context.
- The Actions panel is the shared evidence command surface. It may show role ownership metadata, but it must not invent disconnected AI summaries.

## Storage And Preservation

CleanHouse has two storage responsibilities that must not be confused.

Runtime/local storage is the operational cache and live working state. It may use SQLite, local JSON artifacts, retry queues, and browser UI preferences to keep the current app running.

VVAULT is the long-term preserved user memory for trust records. Anything needed for year-plus history, reports, receipts, Trend, Timeline, findings history, security evidence, or audit continuity belongs in the user-scoped VVAULT tree.

Canonical CleanHouse VVAULT root:

`/vvault_files/users/shard_0000/{userID}/cleanhouse/`

V1 preservation is mirror-only. It must not move, delete, or replace existing local DB rows or local JSON artifacts.

### Preservation Rules

- Browser localStorage is UI preference state only, not durable evidence.
- Local SQLite event rows are runtime evidence cache, not the final preservation layer.
- Local JSON artifacts remain valid local artifacts, but selected trust records must be mirrored to VVAULT.
- Preservation failure must not break live runtime writes.
- If VVAULT root or user id is unavailable, preservation is explicitly disabled and must not fake a write.
- Preserved artifacts use stable JSON envelopes with `id`, `type`, `schema_version`, `timestamp`, `source`, `local_ref`, and `evidence_refs`.
- Trend is a market-style chart: preserved history loads first, then current observations extend it.
- Timeline is an audit ledger: runtime interruptions are preserved as explicit gaps with start, end, duration, and reason.
- Projection reads must not create history; only runtime collection and recovery code may write preserved network history.

### VVAULT Tree

- `network/trend/samples/`
- `network/trend/buckets/`
- `network/trend/summaries/`
- `network/timeline/notable_events/`
- `network/timeline/incidents/`
- `network/timeline/gaps/`
- `network/findings/open/`
- `network/findings/resolved/`
- `network/findings/superseded/`
- `network/distribution/socket_snapshots/`
- `network/packets/retained_windows/`
- `network/packets/capture_receipts/`
- `reports/security_reports/`
- `reports/scan_reports/`
- `reports/network_reports/`
- `reports/letters_of_concern/`
- `reports/exports/`
- `evidence/process/`
- `evidence/network/`
- `evidence/files/`
- `evidence/applications/`
- `evidence/runtime/`
- `receipts/scans/`
- `receipts/investigations/`
- `receipts/runtime/`
- `receipts/user_actions/`
- `indexes/by_time/`
- `indexes/by_app/`
- `indexes/by_severity/`
- `indexes/by_report/`
- `indexes/manifest.json`

## Overview

### Purpose & Functions

Overview is the operator entry point for CleanHouse. It summarizes current system posture, highlights high-priority review items, and gives the user a fast path into the major investigation surfaces without requiring them to inspect every page first.

Overview should function as a control surface, not a decorative landing page. Its job is to answer:

- What does CleanHouse currently see?
- What needs attention first?
- Which surface should the operator open next?

### Page Details

- Presents the current CleanHouse posture using concise status, notification, and investigation summaries.
- The top-left CleanHouse logo is the navigation control back to Overview.
- Primary product page navigation lives in the shared sidebar, not uniquely on Overview.
- Should avoid inventing health or risk states not backed by local CleanHouse evidence.
- Should preserve evidence-first language: if a source is unavailable, the page should say so rather than filling with placeholder conclusions.

## Applications

### Purpose & Functions

Applications is the app inventory and app-level investigation surface. It tracks installed applications, observed running state where available, and app-linked evidence such as process rows, app metadata, and user-facing investigation details.

Applications should answer:

- Which applications are known to CleanHouse?
- Which apps are running or recently observed?
- What process evidence is associated with a selected app?
- Which app should the operator inspect first?

### Page Details

- Uses local application inventory evidence and process evidence.
- App details may include name, bundle identifier, path, category, version, running state, and matched process rows.
- Running state is evidence-driven and can be incomplete if the system source cannot observe a process or GUI app.
- Application identity must not be used to fake Network activity. An app can be installed or open while producing zero observed network/socket evidence.

## Network

Network is the network investigation surface. The [Network Product Contract](network-product-contract.md) is the normative source of truth for Network row semantics, tab questions, evidence boundaries, Translation, and the “Powered by Wireshark” invariants. If this architecture spine, an earlier document, a test, or implementation behavior conflicts with that contract, the contract controls.

### Purpose & Functions

Network shows local network evidence in human-readable form. Its tabs examine overlapping authoritative evidence without deriving from one another's presentation.

Current product rule:

- Table presents operator-visible communication records reproducible from immutable Wireshark packet evidence.
- Findings is the grouped semantic review view.
- Trend is the evidence-backed measurement-over-time view.
- Distribution is the evidence-backed app/service concentration view, with uncertainty preserved.
- Timeline is the notable event and evidence-gap view.
- The Network header tag row is page-level posture shared by all five tabs.

### Page Details

#### Network Page Tags

The Network page header must always communicate one combined Network posture across Table, Findings, Trend, Distribution, and Timeline. The active tab may explain its own details, but it must not invent separate top-level tags.

The header format is:

`STATUS | STATE | optional REASON`

`REASON` appears only when `STATE` is `DEGRADED` or `CRITICAL`. `HEALTHY` and `UNKNOWN` do not render a reason tag.

Status tags are fixed:

- `OBSERVING`: monitoring is active and traffic is being watched
- `QUIET`: monitoring is active, but no recent traffic is visible
- `LOCAL ONLY`: only local, LAN, or loopback traffic is visible
- `OFFLINE`: no usable network path or interface is visible

State tags are fixed:

- `HEALTHY`: no review conditions detected
- `DEGRADED`: reduced confidence, reduced capability, or review-worthy evidence
- `CRITICAL`: urgent user attention required
- `UNKNOWN`: not enough evidence to classify state

Degraded reason tags are fixed:

- `Destination name missing`
- `Unknown app active`
- `New destination seen`
- `Many destinations contacted`
- `High connection volume`
- `Unusual port used`
- `Unencrypted web request`
- `Capture engine limited`
- `Permission blocks capture`
- `Fallback mode active`
- `Interface changed`
- `Connection attempts failed`
- `Local traffic only`

Critical reason tags are fixed:

- `Known malicious endpoint`
- `Blocked threat active`
- `Data exfiltration suspected`
- `Malware process active`
- `Suspicious listener exposed`
- `Repeated failed connections`
- `Unsigned app communicating`
- `Unexpected inbound access`
- `Privilege process online`
- `Quarantine bypass suspected`

Expected normal examples:

- `OBSERVING | HEALTHY`
- `QUIET | HEALTHY`
- `LOCAL ONLY | HEALTHY`

Expected review examples:

- `OBSERVING | DEGRADED | Destination name missing`
- `OBSERVING | DEGRADED | Capture engine limited`
- `OFFLINE | DEGRADED | Capture engine limited`
- `OBSERVING | CRITICAL | Known malicious endpoint`

Tag boundaries:

- Do not render vague tags such as `LIVE TRAFFIC`.
- Do not render reason tags for `HEALTHY`.
- Do not generate dynamic tag labels.
- Put dynamic details in explanatory copy, metadata, or the action sidebar.
- Keep tag labels fixed, evidence-mapped, and deterministic.

The five Network tabs contribute evidence to one shared posture:

- Table contributes evidence-backed communication activity, capture state, and continuity.
- Findings contributes highest review severity and semantic risk.
- Trend contributes quiet, spike, and high-volume evidence.
- Distribution contributes observed app/service concentration and attribution confidence.
- Timeline contributes recent notable or critical events.
- Timeline does not use a `5s` view; its shortest audit-ledger range is `1m`. The `5s` view belongs to Trend/live charting.

#### Table

Table is the operator-visible communication record view defined by the [Network Product Contract](network-product-contract.md). Every Table row must be reproducible from immutable Wireshark packet evidence.

Table is not:

- a socket ownership projection
- a Distribution data source
- a snapshot fallback view
- a fake/demo packet list
- an app or socket inventory presented as captured traffic
- a product-level commitment to any specific row representation

A Table row may be enriched by newly observed evidence but must never rewrite previously observed packet facts. Derived attribution and Translation remain visibly distinct from observed evidence.

Rows default to the most recently observed communication first, with deterministic ordering. Selection must not silently alter that order. A row leaving the visible Table must not silently delete or break access to its supporting evidence.

Completion must visibly distinguish directly observed evidence from inference. Interruption must remain visible whenever capture continuity or completeness becomes unknowable.

Translation may explain supported evidence in plain language, but it remains a CleanHouse-derived layer. It must distinguish observed, inferred, and unknown information and must not manufacture intent, content, ownership, or threat conclusions.

#### Table Implementation Boundary

The Product Contract defines observable operator behavior and evidence guarantees. It intentionally does not prescribe implementation strategy. Multiple implementations may satisfy the contract provided operator-visible behavior and evidence integrity remain unchanged.

Implementation intentionally deferred. Possible strategies and unresolved decisions belong only in the draft, non-authoritative [Network Table Implementation Proposal](network-table-implementation-proposal.md).

#### Findings

Findings is the semantic review surface for network evidence. It should read like plain-language security findings, not a raw packet feed, not a socket table, and not a scary list of undeciphered addresses.

Findings is not:

- the Table operator-visible communication record view
- the Distribution app/service-share view
- a raw address dump
- a four-row viewport limit
- a duplicate packet list
- a Dock/open-app inventory

Findings rows are grouped by meaning. Repeated Apple Push, Bonjour, Cloudflare/WARP, local discovery, or similar routine evidence should appear as one finding with metadata such as `related_event_count`, not as repeated identical rows. Distinct meanings must remain distinct findings.

Plain-language rules:

- Known local/discovery traffic must be named as local/discovery traffic.
- `rapportd` link-local traffic is Apple Continuity or nearby-device traffic.
- Bonjour/mDNS traffic is local service discovery.
- IPv6 link-local and multicast traffic is local network housekeeping.
- Apple `17.*` traffic on port `5223` is Apple Push notification service traffic.
- Cloudflare/WARP ranges are Cloudflare/WARP network traffic when supported by endpoint evidence.
- Truly unresolved external traffic remains `Unknown app` or `unknown process` and is suspicious.

The top finding is priority-preserving. It must not change merely because the page reloaded. It can move only when the finding is cleared/resolved/superseded/invalidated or when more important current evidence appears.

#### Findings Data Flow

1. Backend retained network evidence is enriched with process/PID/socket evidence when available.
2. Backend `_network_plain_language_semantics()` assigns `category`, `summary`, `meaning`, and `reason`.
3. Backend `_network_projection_findings()` keeps open, review-worthy findings, sorts them by stable priority, and groups repeated semantic evidence.
4. Frontend `renderNetworkFindings(events)` renders the backend `summary` and `reason`.
5. The metadata drawer keeps raw event details available without making the main list unreadable.

#### Findings Regression Rules

Do not drive Findings from:

- raw live Table ticks
- Distribution donut totals
- browser/Dock open-app inventory
- fake/demo/synthetic rows
- a hard four-item limit

Do not change the Findings scroll/fade behavior without explicit product approval. The current product shape is the invisible window, native row snapping, top/bottom fade, collapsed rows by default, and no custom wheel handler.

Color coding may reflect severity, but it must not change row order, grouping, scroll snapping, row height rules, or plain-language semantics.

#### Distribution

Distribution shows which apps or services account for observed network activity in the selected evidence window. Each share must be backed by attributable packet-supported communication, and uncertain ownership must remain in an explicit `Unknown` category.

Distribution is not:

- a Dock/open-app list
- a list of every installed application
- a zero-count app inventory
- an active-socket inventory
- a process inventory presented as network activity
- a simulated network dashboard

Distribution must preserve the June 28 visual structure:

- title: `Network activity by app`
- donut chart on the left
- one connected owner list on the right
- event metadata drawer below
- no second program list
- no zero-count rows

The donut and the right-side list are the same evidence-backed dataset. Every right-side row must correspond to a donut slice/color. The displayed total and each share must state their measured basis and be reproducible from the supporting observed communication.

#### Distribution Architecture Boundary

Distribution must preserve these boundaries:

- only observed, packet-backed communications contribute activity
- app/service attribution is CleanHouse-derived and confidence-labeled
- uncertain attribution contributes to `Unknown`, not a guessed owner
- installed apps, open apps, listening sockets, and zero-evidence entities do not contribute shares
- all displayed totals and shares use one declared evidence window and measurement basis
- visual aggregation never erases traceability to supporting observed Network evidence
- capture gaps and unavailable evidence are visible rather than silently normalized away

This section intentionally does not lock aggregation APIs, schema, storage, attribution implementation, or the evidence-backed share used for a given view.

## Files

Pending supervised documentation.

## Zaelith

Zaelith is locked by `uren-tal-arsenal.md`.

For CleanHouse architecture, Zaelith means the Uren'Tal Arsenal Lasso of Truth: a text-based lie detector whose primary workflow is manual text upload or direct manual text entry followed by truth/deception analysis.

Zaelith is not a generic evidence interpreter. CleanHouse evidence may become input text for Zaelith, but that does not change Zaelith's identity or function.

## Identity

Pending supervised documentation.

## Reports

Pending supervised documentation.
