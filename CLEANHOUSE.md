# CleanHouse

## Core

**Product:** CleanHouse  
**Document class:** Master product canon  
**Authority:** Owner-controlled  
**Product priority:** LIFE Technology priority 1  
**Class:** Local-first security observability, evidence, mediation, and control  
**Primary experience:** Browser-based security operations on the local machine  
**Canonical landing surface:** `/overview`  
**Canonical local service:** `127.0.0.1:3333`  

This contract defines what CleanHouse is, what it must become, what it may truthfully claim, and how it can be reconstructed without erasing intended surfaces. It is the first product-level authority for CleanHouse. Implementation evidence may refine status; it may not silently narrow the product.

The human owner is the only authorized handler of the canonical product and its protected evidence.

CleanHouse provides runtime accountability for the human owner of a computing environment. It is not merely a dashboard, antivirus scanner, process viewer, packet viewer, file watcher, policy engine, agent launcher, or archive. Those are capabilities inside a larger evidence and accountability product.

CleanHouse answers:

1. What is happening?
2. What changed?
3. What evidence proves it?
4. Does it match the owner's approved intent and scope?
5. What safe response is available now?

### Governing evidence lifecycle

```text
OBJECTIVE
    ↓
ACTIONS
    ↓
OBSERVATIONS
    ↓
MUTATIONS
    ↓
FINDINGS
    ↓
MEDIATION
    ↓
RECEIPTS
    ↓
PRESERVATION
    ↓
REVIEW / ROLLBACK
```

### Evidence classifications

| Classification | Definition |
|---|---|
| Observed | Directly supported by retained evidence |
| Derived | Computed from identified evidence using a named, reproducible rule |
| Inferred | Bounded conclusion with explicit uncertainty |
| Unknown | Not proven |
| Approved | Explicitly accepted by the authorized handler under a recorded scope |
| Authorized | Permitted by a valid authorization envelope |
| Executed | Control action actually performed and receipted |

**Rules**

- Observation is not approval.
- Identity is not authorization.
- Configuration is not operation.
- A suggested remediation is not an executed remediation.
- A successful scan does not establish authorized intent.
- Evidence determines factual claims.
- Authorization determines permitted action.
- Receipts establish execution history.

### Product architecture

CleanHouse is a network of independently degrading product nodes sharing an evidence spine.

```text
                         CLEANHOUSE
                              │
                    SECURITY EVIDENCE
                              │
       ┌──────────────┬───────┴────────┬──────────────┐
       │              │                │              │
   Applications     Network           Files        Identity
       │              │                │              │
       └──────────────┼────────────────┼──────────────┘
                      │                │
                    Zaelith          Reports
                      │                │
                      └────────┬───────┘
                               │
                            MEDIATION
                               │
                            RECEIPTS
                               │
                           PRESERVATION
```

Subsystems remain independently useful when other nodes degrade.

**Failure behavior**

- Optional integrations fail locally and visibly.
- Read-only surfaces remain available when a mutation provider is unavailable.
- Local evidence capture continues during remote preservation outages when safe storage remains available.
- Remote preservation backlogs remain explicit and durable.
- Network collector failure does not disable Files.
- Wazuh failure does not erase watchdog evidence.
- VVAULT failure does not rewrite local history.
- Authentication failure blocks protected access without corrupting retained evidence.
- Recovery replays durable cursors, outboxes, and receipts.
- No subsystem may fabricate continuity or upgrade product health claims.

---

# Product Surface Map

## Canonical browser model

CleanHouse operates through a browser.

The desktop wrapper may provide a native entry point. It must render or open the same product contract.

**Authenticated landing route:** `/overview`

## Permanent surfaces

| Surface | Purpose |
|---|---|
| Overview | Security at a glance |
| Applications | Application evidence and controls |
| Network | Packet, connection, and network findings |
| Files | Filesystem evidence and integrity |
| Zaelith | Intent, authorization, and prompt accountability |
| Identity | External account and identity-risk monitoring |
| Reports | Receipt ledgers and legal-technology workflows |
| Allowed Threats | Explicitly acknowledged security conditions |
| Help | Operator guidance and safe diagnostic packaging |
| Advanced Monitor | Detailed evidence workstation |
| Zaelith Connect | Provider connection workflow |
| Custom Scan | Scoped scanning |
| Incident Receipt | Focused case review and action |
| Account and legal flows | Identity, consent, account, and legal operations |

**Primary navigation**

```text
Overview
Applications
Network
Files
Zaelith
Identity
Reports
```

**Shared utilities**

```text
Help
Advanced Monitor
Notifications
Sign Out
ctrl
Mediation
```

Every permanent surface must remain present.

An unfinished capability exposes its actual state. It does not disappear, change identity, or become an unrelated substitute.

## Shared shell behavior

- Accurate page titles.
- Current-page indication.
- Keyboard-reachable navigation.
- Visible focus.
- Accessible names and labels.
- Meaningful status announcements.
- Contextual actions bound to selected evidence.
- Right-click and contextual actions remain relevant to the selected evidence and current surface; generic or misleading context menus are prohibited.
- Stationary underlying page during overlays.
- Truthful loading and failure states.
- Explicit distinction between observation, proposal, authorization, and execution.

### Shared UI states

```text
empty
loading
warming
unavailable
degraded
offline
partial-failure
error
retrying
recovered
```

These are distinct states.

Controls must disclose their actual capabilities.

No control may imply success before its receipt exists.

Protected diagnostics, raw secrets, credentials, private URLs, and sensitive filesystem paths remain outside ordinary UI.

---

# CSS Rubric

**Direction:** Simple CSS  
**Status:** Canonical direction; final objective styling rubric planned

The final visual contract must be a verbatim implementation rubric comparable in specificity, not content, to the Chatty UI legacy scheme and `GRID.md`. It must express exact color, typography, spacing, sizing, alignment, border, radius, shadow, motion, breakpoint, focus, hover, selected, disabled, loading, error, and responsive values as accepted evidence becomes available.

## Established styling

| Element | Established requirement |
|---|---|
| Overall visual language | Dark, restrained security-operations presentation |
| Page headers | League Spartan |
| Overview home control | Permanent FourStar mark |
| FourStar treatment | Standalone logo |
| FourStar active state | No ordinary active-navigation highlight |
| FourStar duplication | No duplicated shield row |
| Navigation | Stable placement |
| Notifications | Stable position across pages |
| Evidence tables | Dense and readable |
| State colors | Semantic and legible |
| Selected evidence | Distinct selected-state treatment |
| Affected evidence | Distinct affected-state treatment |
| Overlays | Underlying page remains stationary |
| Contextual tools | Placed within the surface they control |
| Provider controls | Relevant to their owning surface |
| General design | Simple CSS without approximate behavior |

League Spartan applies to visible page titles, including the Overview hero title and Applications, Network, and Files section headers.

League Spartan is not the default card-title or body typeface.

## Unresolved style categories

No canonical token identifiers are established. Required specification categories remain descriptive until accepted evidence establishes exact names and values.

| Category | Status |
|---|---|
| Backgrounds and surfaces | NOT ENOUGH EVIDENCE |
| Primary, secondary, and muted text | NOT ENOUGH EVIDENCE |
| Borders and elevation | NOT ENOUGH EVIDENCE |
| Accent and semantic state colors | NOT ENOUGH EVIDENCE |
| Selected and affected treatments | Existing treatments established; exact values unresolved |
| Overlays, shadows, radii, and focus rings | NOT ENOUGH EVIDENCE |

## Typography

| Role | Typeface | Size | Weight | Line height |
|---|---|---|---|---|
| Page title | League Spartan | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Section heading | League Spartan where established | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Card title | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Body | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Table heading | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Table body | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Evidence metadata | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |
| Status label | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |

## Geometry and spacing

| Specification | Value |
|---|---|
| Shell header height | NOT ENOUGH EVIDENCE |
| Shell footer height | NOT ENOUGH EVIDENCE |
| Navigation width | NOT ENOUGH EVIDENCE |
| Panel minimum width | NOT ENOUGH EVIDENCE |
| Panel maximum width | NOT ENOUGH EVIDENCE |
| Panel gutter | NOT ENOUGH EVIDENCE |
| Card gutter | NOT ENOUGH EVIDENCE |
| Table row height | NOT ENOUGH EVIDENCE |
| Header padding | NOT ENOUGH EVIDENCE |
| Footer padding | NOT ENOUGH EVIDENCE |
| Overlay width | NOT ENOUGH EVIDENCE |
| Overlay maximum height | NOT ENOUGH EVIDENCE |
| Border width | NOT ENOUGH EVIDENCE |
| Border radius | NOT ENOUGH EVIDENCE |
| Shadow geometry | NOT ENOUGH EVIDENCE |

## Shell components requiring exact specifications

```text
SHELL
├── Navigation
├── Header
├── Footer
├── Main content
├── Contextual panels
├── ctrl
├── Mediation
├── Notifications
└── Overlays
```

## Interaction states

```text
default
hover
focus
focus-visible
selected
affected
disabled
loading
warming
success
warning
error
degraded
offline
unavailable
unknown
```

## Responsive contract

Required:

- Desktop layouts.
- Mobile layouts.
- Scalable text.
- Keyboard navigation.
- Accessible constrained tables.
- No hidden essential controls.
- Reduced-motion support.
- Focus restoration after overlays.
- Non-color-only status communication.

**Breakpoints:** NOT ENOUGH EVIDENCE  
**Motion durations:** NOT ENOUGH EVIDENCE  
**Opacity values:** NOT ENOUGH EVIDENCE  
**Exact responsive dimensions:** NOT ENOUGH EVIDENCE

---

# Security Authority Index

**Security is a cross-cutting CleanHouse requirement.**

Security validation authority: **K.A.T.A.N.A.**  
Product authorization authority: **Human owner**  
Action authorization integration: **Zaelith**

## Universal security requirements

- Bind the local service to loopback unless explicitly changed through an approved distribution contract.
- Authenticate protected reads.
- Authenticate all mutations.
- Apply same-origin and CSRF controls.
- Validate external destinations.
- Require HTTPS except approved loopback development.
- Bound timeouts, retries, queues, response sizes, and retained windows.
- Protect credentials and secrets.
- Verify bundled dependencies.
- Preserve licensing and source-compliance requirements.
- Isolate provider failures.
- Reject malformed or unauthenticated evidence.
- Reject wrong-agent and wrong-scope evidence.
- Reject stale and incompatible evidence.
- Preserve raw provenance.
- Keep secret material out of logs, errors, browser payloads, staged public files, and command arguments.
- Require authorization for destructive actions.
- Fail closed on contradictory security evidence.

CleanHouse does not claim antivirus behavior, proprietary malware heuristics, omniscient attribution, or universal prevention.

Future heuristics remain a separately versioned interface requiring evidence, licensing review, and security review.

## Security requirements by capability

| Capability | Security requirement |
|---|---|
| Runtime | Listener ownership, heartbeat, readiness, bounded recovery |
| Authentication | Protected routes, sessions, MFA, recovery, CSRF |
| Overview | Scoped scans and guarded process controls |
| Applications | Evidence-backed controls and bounded metadata mutations |
| Network | Authentic capture provenance and truthful connection state |
| Files | Authenticated Wazuh evidence, integrity generations, reconciliation |
| Zaelith | Actor evidence, approval envelopes, scope authorization |
| Identity | Official providers, consent, credential protection |
| Reports | Redaction-aware exports and receipt integrity |
| Allowed Threats | Explicit acknowledgment, authorization, immutable receipt |
| Insights | Evidence-bound inference and bounded provider context |
| Mediation | Non-execution without authority |
| Preservation | Authenticated, additive, idempotent delivery |
| VPN | Reviewed cryptography, routing, leak protection, recovery |
| Distribution | No accidental exposure of local administrative interfaces |

---

# Overview

**Purpose:** Security at a glance  
**Owner:** CleanHouse  
**Route:** `/overview`  
**Status:** Partial

## Capabilities

- FullHouse Scan.
- Process Monitor.
- Process Scan.
- Current threats.
- Allowed threats.
- Last scan.
- Scan duration.
- Evidence counts.
- LLMs scanned.
- Files scanned.
- Ports scanned.
- Processes scanned.
- Applications scanned.
- Relevant providers scanned.
- Subsystem health.
- Evidence freshness.
- Contextual `ctrl`.
- Shared Mediation.

Every aggregate must link to underlying evidence.

## FullHouse Scan

**Purpose:** Coordinate available security scanners and collectors.

**Inputs**

- Selected scan scope.
- Included subsystems.
- Excluded subsystems.
- Available collectors.
- Authorized execution context.

**Behavior**

```text
Declare scope
    ↓
Identify available collectors
    ↓
Execute permitted scans
    ↓
Collect observations
    ↓
Identify findings
    ↓
Record partial failures
    ↓
Produce subsystem receipts
    ↓
Present evidence-backed result
```

**Requirements**

- Declare included and excluded scopes before execution.
- Tolerate unavailable optional subsystems.
- Report partial completion.
- Preserve per-subsystem receipts.
- Separate observations from findings.
- Do not fabricate unavailable scanner counts.
- Do not infer authorization from scan cleanliness.

## Process controls

**Force quit:** High-impact action.

Required before execution:

- Live process identity.
- Executable evidence.
- Owner-visible target confirmation.
- Authorization validation.
- Scope validation.
- PID reuse protection.
- Pre-action snapshot.

Required after execution:

- Actual result.
- Post-action receipt.
- Truthful failure state.
- Explicit rollback limitations.

## Acceptance

- FullHouse Scan produces scoped, receipted results.
- Process Monitor and Process Scan operate.
- Partial subsystem failure remains visible.
- Evidence links resolve correctly.
- `ctrl` and Mediation remain truthful and functional.

---

# Applications

**Purpose:** Per-application security workspace  
**Owner:** CleanHouse  
**Status:** Partial

## Evidence

Each application combines:

- Process evidence.
- Metadata evidence.
- Network evidence.
- File evidence.
- Zaelith evidence where applicable.
- Current findings.
- Historical receipts.

## Application inventory

Required:

- Installed application inventory.
- Running application inventory.
- Application icons.
- Metadata.
- Evidence provenance.
- Source availability.

An application card does not establish application health.

Classification labels such as system, developer, creative, network, files, and AI describe metadata. They are not security judgments.

## Scanning

```text
APPLICATION
├── Process Scan
├── Metadata Scan
├── Network Scan
├── File Scan
└── Zaelith Scan
```

Zaelith scanning applies when its evidence and authorization contracts are available.

## Orange

**Purpose:** Metadata verification and bounded patch proposals  
**Status:** Planned

Required workflow:

```text
Observe metadata
    ↓
Verify
    ↓
Identify discrepancy
    ↓
Prepare bounded proposal
    ↓
Preview
    ↓
Authorize
    ↓
Apply
    ↓
Verify
    ↓
Receipt
```

## Controls

- Application-level `ctrl`.
- Shared Mediation.
- Evidence links to originating collectors.
- Explicit unavailable states.
- Scoped authorization.
- Immutable receipts.

## Acceptance

- Application evidence sources combine without losing provenance.
- Unavailable providers remain explicit.
- Orange verification is truthful.
- Actions require scope and authorization.
- Results produce receipts.

---

# Network

**Purpose:** Network observability, evidence, findings, and control  
**Owner:** CleanHouse  
**Evidence authority:** Wireshark-derived packet and flow evidence

**Status**

- Network Core: implemented — verified
- Full Wireshark packaging: incomplete
- Live browser visualization: implemented — unverified
- Contextual controls: partial
- Integrated acceptance: incomplete
- Software VPN: planned

## Evidence contract

- Raw packet evidence originates from a reviewed Wireshark capture path.
- Flow evidence originates from reviewed capture evidence.
- Translation and enrichment are derived layers.
- Synthetic events are not Wireshark evidence.
- Socket inventories are not Wireshark packet evidence.
- Process lists are not Wireshark packet evidence.
- Application guesses are not Wireshark packet evidence.

## Powered by Wireshark

`Powered by Wireshark` is the permanent Network architecture and provider attribution.

CleanHouse earns and preserves the attribution through this baseline:

- Wireshark `tshark` and `dumpcap` provide packet-capture execution.
- Capture evidence records the engine identity, engine version, capture interface, capture generation, packet sequence, and timestamps.
- Connections, Findings, Trend, Distribution, and Timeline derive from traceable Wireshark capture evidence. `Connections` is the visible product label; `table` remains the compatible internal view and API contract.
- Translation, application attribution, and enrichment retain references to their source capture evidence.
- Collector and capture failures produce explicit verifying, degraded, blocked, or unavailable state without fabricated packets.
- Provider attribution remains present while operational state changes independently.
- A watchdog validates the provider components, capture provenance, five views, visual baseline, and source-to-runtime integrity.
- Deterministic drift triggers bounded repair, revalidation, notification, and an append-only receipt without waiting for routine owner intervention.

### Provider stamp baseline

- Text: `Powered by`
- Provider mark: Wireshark logo from `/assets/wireshark-logo.png`
- Position: fixed at the bottom of the Network surface and centered between the shell rails.
- Horizontal anchors: `96px` from the left and right.
- Vertical anchor: `-8px` from the bottom.
- Layout: centered inline flex row.
- Gap: `6px`.
- Text size: `11px`.
- Text weight: `850`.
- Logo width: `91px`.
- Logo treatment: inverted, `0.72` opacity, translated upward `4px`.
- Operational state: existing Network status indicators expose verifying, verified, degraded, blocked, and unavailable state independently of the provider stamp.
- Visibility: permanent on the Network surface; runtime failure changes status and never removes attribution.
- Regression: missing attribution, altered geometry, altered provider mark, untraceable data, or an empty/broken view fails Network acceptance.

## Views

| View | Purpose |
|---|---|
| Connections | Exact network observations; internal view identifier `table` |
| Findings | Review-worthy network conditions |
| Trend | Connections, Strengths, Vulnerabilities, or Threats over time as selectable graph metrics |
| Distribution | Activity across applications, endpoints, protocols, and dimensions |
| Timeline | Ordered notable network events |

## Network Connections

**Compatibility:** The visible label is `Connections`. Existing DOM, URL,
storage, API, replay, and test identifiers may remain `table`; that internal
name is not user-facing canon.

**Row identity:** One deduplicated active connection.

A visible row is not a raw packet.

### Connection identity

```text
Application
+ Source
+ Destination
+ Protocol
+ Port
= Normalized Connection Identity
```

Repeated packet evidence updates:

- Last seen.
- Packet count.
- Bounded details.
- Raw-evidence references.

Raw packets remain accessible in Technical Details.

### Connections behavior

- Header count and visible active rows update together.
- Active selected row remains cyan.
- Active selected row remains pinned first.
- Selected connection leaving the live set remains pinned.
- Stale selected connection displays explicit stale state.
- Stale selection uses the established affected-state treatment.
- Unselecting stale evidence removes the stale row.
- Unselecting active evidence restores ordinary live ordering.

### Selected snapshot

The same immutable selected-connection snapshot supplies:

```text
ctrl
Copy
Export
Insight
Actions
```

### Background behavior

- Hidden pages buffer bounded state.
- Background pages do not render every packet.
- Returning to the foreground renders one fresh deduplicated snapshot.
- Buffered events do not produce an interaction-blocking replay.

### Unresolved Connections contracts

- Capture-generation boundary: NOT ENOUGH EVIDENCE.
- Observed-versus-inferred completion: NOT ENOUGH EVIDENCE.
- Interruption semantics: NOT ENOUGH EVIDENCE.
- Long-duration retention: NOT ENOUGH EVIDENCE.
- Bounded-row omission disclosure: NOT ENOUGH EVIDENCE.

These require approval and testing before release acceptance.

## Network Findings

**Purpose:** Stable priority queue of retained review-worthy evidence.

**Behavior**

- Priority outranks freshness.
- Routine low-priority traffic cannot displace higher-priority findings.
- Findings remain collapsed by default.
- Native scroll-snap behavior remains.
- Fade behavior remains.
- No artificial four-row limit.
- Duplicate packet rows are avoided.
- Wheel and trackpad gestures advance one section deterministically.
- Open sections preserve deterministic navigation.

Top finding changes when:

1. It closes.
2. It is invalidated.
3. It is superseded.
4. A more important finding appears.

Findings is not the live Connections feed.

Findings owns plain-language security assessment explanation. Each assessment
shows its Strength, Vulnerability, or Threat category independently from
severity, confidence, lifecycle, and owner disposition. Findings retains the
stable assessment identity, rule and version, rationale, subject, and bounded
evidence references supplied by the shared assessment contract. It does not
reclassify Network evidence in the browser.

## Shared security assessments

Network uses the backend-owned `cleanhouse.security_assessment.v1` contract.
The same assessment identity and category travel through the header,
Connections, Findings, Trend, Distribution, Timeline, and `ctrl`; each view
presents that shared truth for its own operator question.

- **Strength** means evidence of a verified protection or favorable security
  condition.
- **Vulnerability** means an evidenced weakness, exposure, uncertainty, or
  visibility gap that could permit harm.
- **Threat** means evidence of an active harmful condition or attempt.
- Severity, confidence, lifecycle, and owner disposition are separate fields;
  none changes the category.
- Operational state such as warming, degraded, offline, retrying, blocked, or
  unavailable is never a Strength, Vulnerability, or Threat.
- Raw evidence is immutable. Assessment revisions are append-only and retain
  their evidence references and named rule version.

Initial reviewed rules classify an unknown externally active application and
a missing destination identity as Vulnerabilities. An unusual port, new
destination, volume change, or repeated attempt remains a neutral indicator
unless corroborating evidence satisfies a reviewed assessment rule. Verified
encryption, attribution, authorization, or effective containment may support a
Strength. Verified malware, a malicious endpoint, active exfiltration,
unauthorized inbound access, exploitation, or containment bypass may support a
Threat. An allowed or contained Threat remains a Threat; lifecycle and owner
disposition describe its treatment.

## Network Trend

**Measurements:** Selectable active Connections, Strengths, Vulnerabilities,
or Threats over time. Connections remains the default graph metric.

**Windows**

```text
5s
1m
30m
1h
24h
7d
1mo
3mo
12mo
```

**Rules**

- Empty buckets remain empty.
- One sample produces one occupied bucket.
- Axis endpoints reflect the selected real time window.
- Retained samples are bounded.
- Connection-row timestamps do not substitute for sampled activity.
- Category metrics count distinct assessments active at the bucket boundary.
- A coverage gap remains a gap and never becomes a zero.
- Every category point retains the same assessment IDs and evidence references
  used by Findings, Timeline, the header summary, and `ctrl`.

**Canonical copy**

`Observed {metric} over last {range}`

**Explanation**

`The graph shows evidence-backed {metric} over the selected range. Gaps are not zeros.`

Trend remains a graph and never becomes a prose rationalization, table, or
second Findings surface. A metric selector chooses `Connections`, `Strengths`,
`Vulnerabilities`, or `Threats` without changing the selected range or the
underlying assessment identity.

### Graph / Chart duplicate navigation

`Graph` selects Trend. `Chart` selects Distribution. The control remains
visible on both visual tabs and uses Distribution as the placement reference.
It never switches between two Trend render modes.

## Network Distribution

Distribution shows observed activity as one donut and one matching owner list.
It does not maintain a second Open Applications inventory.

### Observed network activity

- Pie slices represent observed network evidence.
- Totals represent observed network evidence.
- Zero-event applications do not appear as activity slices.
- The owner list and donut consume exactly the same rows, totals, colors, and
  evidence references.
- Only software with observed Network activity appears.
- Names are normalized consistently while Code and Codex retain separate
  identities.
- Unattributed evidence remains visible as `Unknown`; uncertain ownership is
  never presented as fact.
- At compact landscape widths the wheel is left aligned with the list on its
  right. At larger widths the wheel is centered and the matching list is
  layered below it.

## Network Timeline

**Purpose:** Prioritized chronological network evidence.

Includes:

- Notable events.
- Assessment lifecycle transitions.
- Evidence gaps.
- Continuity evidence.

Timeline does not duplicate Connections or treat every packet as notable.
Selecting an interval exposes each contained event individually and never
binds a grouped marker to one arbitrary finding.

## Header hierarchy

```text
NETWORK TITLE
    ↓
STATUS / STATE / REASON
    ↓
CANONICAL COUNT
    ↓
VIEW TABS
    ↓
SELECTED VIEW
```

### Status vocabulary

```text
OBSERVING
QUIET
LOCAL ONLY
OFFLINE
```

### State vocabulary

```text
HEALTHY
DEGRADED
CRITICAL
UNKNOWN
```

One status and one state appear together.

Reason appears only for `DEGRADED` or `CRITICAL`.

Reason labels:

- Use reviewed evidence-mapped codes.
- Contain five words or fewer.
- Do not grow dynamically from raw text.
- Do not appear for healthy state.

Detailed explanations belong in plain-language copy.

Operational status/state/reason is separate from the shared posture summary of
Threats, Vulnerabilities, and Strengths. Unknown attribution and other
Vulnerabilities never appear as red Threat reasons.

`LIVE TRAFFIC` is not an acceptable substitute for a precise reason.

## Canonical counts

| View | Copy |
|---|---|
| Connections | `{0} active connections.` |
| Findings | `{0} findings.` |
| Trend | `{0} {metric} in the last {timeview}.` |
| Distribution | `{0} active apps.` |
| Timeline | `{0} events in the last {timeview}.` |

There is no duplicated count/status row immediately above the visualization.

Changing a hydrated view or time range redraws immediately from shared render-ready state.

Background hydration may continue without blanking or freezing the interaction path.

## Network ctrl

- Toggle retains established `ctrl`/`Actions` copy.
- Toggle does not become `Close actions`.
- Outside-click dismissal is capture-phase and close-only.
- Dismissal does not click through to evidence selection.
- Dismissal does not trigger routing, refresh, Insight, or heavy rerendering.
- Opening `ctrl` does not automatically run inference.
- Insight requires explicit operator action.
- Insight binds to the current evidence key.
- Unavailable inference returns an honest unavailable state.
- Every Connections row, finding, Trend bucket, Distribution share, and
  Timeline event binds `ctrl` to the same evidence and assessment IDs used by
  its source projection.
- `More actions` exposes only existing authorized capabilities and never grants
  new execution authority.

## Network Core

**Status:** Implemented — verified

Owns:

- Server-owned collector lifecycle.
- Bounded replay.
- Bounded subscriber queues.
- Subscriber-gap receipts.
- Persistence before fan-out.
- Ordered delivery.
- Bounded refresh.
- Bounded retry.
- Watchdog restart.
- Clean stop and join.
- Local event-spine history.

## Capture unavailable

```text
Network State: degraded
Reason: capture_engine_unavailable
```

Required behavior:

- No crash loop.
- No invalid capture process.
- No fabricated packets.
- No operational capture claim.
- Other available product surfaces remain ready.

## Destination

- Accurate live visualizations.
- Network `ctrl`.
- Shared Mediation.
- Real Time Security Suite.
- Reviewed capture packaging.
- Optional remote preservation.
- Local collection independent of remote synchronization.

---

# CleanHouse Software VPN

**Owner:** CleanHouse  
**Status:** Planned

## Purpose

Provide a software VPN capability controlled by the owner.

## Behavior

- Starts with the system when enabled.
- Remains compatible with an ordinary ISP gateway.
- Adapts to performance-sensitive workloads.
- Supports gaming-oriented routing requirements.
- May use a TP-Link Archer device as an optional hardware endpoint.

The router is not required.

Router presence does not prove tunnel protection.

## Required security contract

- Reviewed threat model.
- Selected protocol.
- Reviewed cryptography.
- Key lifecycle.
- Credential lifecycle.
- Adaptive routing.
- Split routing.
- Per-application routing.
- Gaming-routing rules.
- Kill-switch behavior.
- DNS leak protection.
- Other leak protection.
- Explicit IPv4 behavior.
- Explicit IPv6 behavior.
- Endpoint health.
- Bounded reconnect.
- Bounded recovery.
- Intentional local-LAN access.
- Evidence and receipts.
- Authorization boundaries.
- Platform constraints.
- Network observation integration.
- Allowed Threats integration.

## Performance measurements

Required budgets:

- Latency.
- Jitter.
- Loss.
- Throughput.
- Reconnect.

**Accepted values:** NOT ENOUGH EVIDENCE

## States

```text
starting
connecting
protected
degraded
bypassed
reconnecting
failed
stopped
```

## Unresolved

- Implementation: NOT ENOUGH EVIDENCE.
- Provider: NOT ENOUGH EVIDENCE.
- Protocol: NOT ENOUGH EVIDENCE.
- Deployment infrastructure: NOT ENOUGH EVIDENCE.
- Routing policy: NOT ENOUGH EVIDENCE.
- Hardware support details: NOT ENOUGH EVIDENCE.
- Performance budgets: NOT ENOUGH EVIDENCE.

No zero-latency, zero-overhead, universal-anonymity, or universal-protection claim is permitted.

---

# Files

**Purpose:** Filesystem evidence, integrity, reconciliation, and mediation  
**Owner:** CleanHouse  
**Evidence authority:** Authenticated Wazuh evidence and explicitly labeled local fallback

**Status**

- Bounded Wazuh evidence core: implemented — verified
- Agent package supply-chain closure: implemented — verified
- Complete installation/enrollment: incomplete
- Authoritative owner-environment reconciliation: incomplete
- Browser acceptance: implemented — unverified
- Zaelith authorization: partial/planned

## Views

```text
Changes
Findings
Integrity
Locations
Timeline
```

## Changes

The Changes table prioritizes the complete file path.

- Full path receives adequate width.
- Duplicate Location columns are unnecessary.
- Generic Status columns are prohibited when they merely repeat an event or imply an unsupported conclusion.

## Actor and Source

**Source:** Evidence provider or observation channel.

Examples:

- Wazuh.
- Local watchdog fallback.

**Actor:** Entity believed to have caused an observed change.

Examples include:

- Human users.
- Codex.
- Cline.
- Kiro.
- VS Code.
- Terminal processes.
- Extensions.
- Other agents.
- Unknown software.
- Malicious tooling.

Actor identity is open-ended.

Examples do not form a hard allowlist.

Actor identity never establishes authorization.

Zaelith must compare the specific action, file, operation, timing, and scope against an approval envelope.

## Wazuh

### Package

The Wazuh agent is bundled for offline installation.

Required package properties:

- Pinned.
- Cryptographically verified.
- Signature-checked.
- Notarization-checked.
- Licensing material included.
- Source-compliance material included.

### Lifecycle

```text
packaged
installed
enrolled
connected
scanning
degraded
unavailable
```

### Operational branding

`powered_by_wazuh=true` requires at least one authenticated, agent-scoped Wazuh event successfully committed to the local append-only event spine.

Visible `Powered by Wazuh` branding follows the same evidence requirement.

Package presence does not prove operation.

Configuration does not prove operation.

Historical authenticated proof remains historical proof after a later outage.

Current provider health is separate from historical provenance.

## Files evidence model

**Contract:** `cleanhouse.files.v2`

Compatible earlier fields remain supported.

### Required provider state

- Collector provider.
- Lifecycle.
- Evidence-authentication state.
- Package version.
- Agent version.
- Connection health.
- Monitored scope.
- Last event.
- Ingestion latency.
- Durable cursor.
- Gap state.
- Fallback reason.
- Historical Wazuh proof.
- Integrity generation.
- Integrity authority.
- Preservation backlog.
- Preservation result.

### UI states

```text
live
warming
degraded
unavailable
fallback
no-data
```

### Normalized events

```text
create
modify
delete
move/rename
metadata
owner
group
permission
inode
size
modification time
available hashes
```

Raw provider identifiers remain preserved.

Canonical payload hashes remain preserved.

Event insertion and cursor advancement are atomic.

Reconnect and restart must not duplicate or skip evidence.

Matching Wazuh and watchdog observations may be correlated in projections.

Their raw records and provenance remain separate.

## Watchdog fallback

**Purpose:** Local continuity for known watched paths.

**Status:** Fallback evidence, not Wazuh evidence.

Rules:

- Explicit fallback labeling.
- Preservation of local watcher provenance.
- Partial reconciliation.
- No authoritative Wazuh baseline from fallback evidence.
- No false Wazuh branding.

## Integrity

**Model:** Immutable generation chain.

Each observed change advances an immutable delta generation.

### Checkpoints

Contain:

- Complete SHA-256 projection.
- Metadata projection.

### Current generation

Exposes:

- Root hash.
- Entry count.
- Checkpoint time.
- Authority.
- Gaps.
- Drift.
- Reconciliation receipt.

Historical generations remain available.

Observed or handler-accepted events are not automatically authorized.

## Reconciliation

### Authenticated Wazuh

When authenticated Wazuh inventory is live:

```text
Authenticated inventory
    ↓
Compare current state
    ↓
Identify drift
    ↓
Create authoritative generation
    ↓
Write reconciliation receipt
```

Authority label:

`authenticated_wazuh`

### Watchdog fallback

Reconciliation is limited to known watched paths.

Authority label:

`observed_fallback`

### Full baseline rebuild

- Recovery operation.
- Adds a new generation.
- Preserves historical generations.
- Never overwrites history.

## Files destination

Complete proof remains required for:

- Installed macOS agent behavior.
- Enrolled macOS agent behavior.
- Authenticated manager ingestion.
- Authoritative inventory reconciliation.
- Orange metadata verification.
- Orange patching.
- Files `ctrl`.
- Shared Mediation.
- Integrated browser acceptance.

---

# Zaelith

**The binding Lasso of Truth**

**Purpose:** Intent, authorization, and prompt accountability  
**Owner:** CleanHouse / Zaelith integration  
**Identity:** Not-a-Lie Detector  
**Class:** Tethered observability and remediation AI Wizard  
**Status:** Partial / planned

## Capabilities

- Continuous 24/7 watchdog.
- Manual text analysis.
- Screenshot analysis.
- Official provider connection GUIX through MCP where supported.
- Open-ended actor identity.
- Actor-confidence evidence.
- Approval envelopes.
- Per-action scope validation.
- Authorization classification.
- Prompt insights.
- Universal-remote controls.
- Shared Mediation.
- Guarded preventive enforcement.
- Agentic and MCP workflow observation.
- Original-request and authorized-scope binding.
- Evidence-backed drift detection.
- Same-thread remediation receipts.
- Verified correction and resume.

## Tethered remediation

Zaelith observes agentic work as one evidence-bearing continuity chain:

```text
Original owner request
    ↓
Authorized scope and acceptance gates
    ↓
Originating thread and executor
    ↓
Delegated instructions, tool actions, mutations, tests, and claims
    ↓
Zaelith evaluation
    ↓
Continue
    OR
Pause and return a remediation receipt to the originating thread
    ↓
Originating executor repairs the bounded divergence
    ↓
Zaelith verifies correction and resumes the original objective
```

Zaelith is not a second competing implementation agent. Many agents may inspect, advise, or validate, but only one tethered executor holds the write lease for a task at a time. The originating thread remains the execution owner unless the authorized handler explicitly reassigns it.

Zaelith detects globally and corrects visibly. It does not silently replace instructions, rewrite conversation history, modify repository state behind the active executor, or allow another agent to overwrite work from a stale interpretation.

When observable evidence proves misunderstanding, hallucinated evidence, scope drift, destructive change, regression, stalled repetition, or false completion, Zaelith may pause the affected work, suspend its write lease, and send an append-only remediation receipt into the originating thread. The original request, incorrect interpretation, contrary evidence, and corrected direction remain visible.

Within an existing authorization envelope, a safe and reversible correction does not require routine owner intervention. Zaelith must return to the authorized handler before remediation that would:

- Change the original requested outcome.
- Expand the authorized scope.
- Choose between materially different owner interpretations.
- Perform a destructive or irreversible action.
- Override an explicit owner decision.

If the originating thread cannot resume, Zaelith prepares an explicit handoff containing the complete objective, verified state, divergence, remediation receipt, and next bounded action. It does not silently continue in another thread.

## Remediation receipt

Every remediation receipt records:

- Original owner request and immutable objective reference.
- Authorized scope, protected surfaces, and acceptance gates.
- Originating thread and current executor.
- Detected divergence and its classification.
- Exact contradicted requirement.
- Evidence establishing the conflict.
- Affected files, runtime state, and preserved work.
- Required revert or repair boundary.
- Corrected direction and next bounded action.
- Required verification.
- Last verified resume checkpoint.
- Authorization basis and any required owner decision.

The originating executor must acknowledge the remediation receipt before another write. Resume means continuing the same owner-authorized objective after repairing the specific divergence; it never means starting a newly inferred objective.

## Authorization classification

```text
authorized
unknown
unauthorized
```

Classification must be reproducible from evidence and approved scope.

## Provider connections

Requirements:

- Official interfaces.
- Explicit owner consent.
- Accurate provider state.
- Protected credentials.
- Supported MCP paths where available.

Prohibited:

- Unsupported scraping.
- Silent account access.
- Embedded credentials.
- Fabricated provider connectivity.
- Exposure of hidden model reasoning.

## Enforcement

Preventive enforcement is available only when:

- Authority exists.
- A guarded control exists.
- Scope is valid.
- The action is safe.
- Verification is available.
- A receipt can be retained.

Zaelith evaluates observable prompts, actions, scopes, evidence, and outcomes.

It does not claim omniscient intent detection.

---

# Identity

**Purpose:** External account and identity-risk monitoring  
**Owner:** CleanHouse  
**Status:** Planned  
**Current surface:** Intentional placeholder

## Capabilities

- Bring-your-own-provider monitoring.
- Social-media monitoring.
- Account-compromise detection.
- Impersonation detection.
- Duplicate-account detection.
- Credential-risk signals.
- Account-takeover signals.
- Account-integrity monitoring.
- Auth-aligned identity lifecycle.
- Orange metadata verification and patching.
- drbt-aligned SEO and distribution coordination.
- Identity `ctrl`.
- Shared Mediation.

## Authentication coordination

auth-aligned behavior includes:

- Authentication.
- Identity verification.
- MFA.
- Enrollment.
- Session trust.
- Recovery.
- Reverification.

## Identity Privacy Score

**Purpose:** Evidence-backed identity privacy and security assessment.

**Status:** Planned

The Identity Privacy Score receives prominent placement in Identity.

It is analogous in product prominence to Chatty Finance's credit-score concept, but specific to CleanHouse identity privacy and security.

Required outputs:

- Contributing factors.
- History.
- Active risks.
- Prioritized recommendations.
- Supporting evidence links.
- Confidence.
- Unknowns.
- Evidence freshness.
- Provider coverage.

Measured inputs remain distinct from derived conclusions.

Missing evidence is an unknown or coverage gap.

Missing evidence does not imply good posture.

### Unresolved methodology

| Specification | Status |
|---|---|
| Scoring methodology | NOT ENOUGH EVIDENCE |
| Weights | NOT ENOUGH EVIDENCE |
| Update cadence | NOT ENOUGH EVIDENCE |
| Authoritative sources | NOT ENOUGH EVIDENCE |
| Accepted measurements | NOT ENOUGH EVIDENCE |

Until methodology is reviewed and versioned, the UI may show a planned or unavailable score state.

It must not emit a synthetic numeric score.

## Provider security

- Official channels.
- Explicit consent.
- No credential scraping.
- No silent third-party access.
- No provider-security bypass.
- No invented score inputs.
- No invented measurements or conclusions.

---

# Reports

**Purpose:** Human-readable CleanHouse receipt ledgers  
**Owner:** CleanHouse  
**Status:** Partial

Basic stored report history exists.

The complete receipt-ledger and legal-technology product remains unfinished.

## Records

- Local remediations.
- Cloud remediations.
- Other-environment remediations.
- Submitted complaints.
- Incident receipts.
- Login summaries.
- Session summaries.
- Objective receipts.
- Mutation receipts.
- Approval receipts.
- Rollback receipts.
- Mediation receipts.
- Preservation state.
- Delivery state.

## Controls

- Filtering.
- Search.
- Preserved receipt replay.
- Redaction-aware export.
- Legal-technology insights through `ctrl`.
- Shared Mediation.

## Legal-technology boundary

CleanHouse distinguishes:

```text
Generated report
Submitted complaint
Legally effective filing
```

These are not interchangeable.

CleanHouse provides evidence organization and legal-technology assistance.

It does not provide legal representation or guarantee legal conclusions.

---

# Allowed Threats

**Purpose:** Record explicitly acknowledged conditions  
**Owner:** CleanHouse

## Record

- Acknowledging actor.
- Scope.
- Time.
- Rationale.
- Expiry or review rule.
- Related evidence.

An allowed threat remains part of history.

Acknowledgment does not erase evidence or establish harmlessness.

## Mutations

Require:

- Authentication.
- Authorization.
- CSRF protection.
- Immutable receipt.

---

# Help

**Purpose:** Operator guidance and troubleshooting  
**Owner:** CleanHouse

## Capabilities

- Operator guidance.
- Truthful troubleshooting.
- Safe retry instructions.
- Selected evidence packaging.
- Redacted developer-review material.

## Security

- No credential leakage.
- No protected diagnostic leakage.
- No unrelated user data.
- Bounded evidence selection.

---

# Advanced Monitor

**Purpose:** Detailed security evidence workstation  
**Owner:** CleanHouse

## Capabilities

- Operational presence.
- Active context.
- Objective feeds.
- Mutation streams.
- Approvals.
- Deviations.
- Receipt replay.
- Collector state.
- Continuity.
- Ports.
- File lineage.
- Rollback.
- Evidence gaps.

Advanced Monitor uses the same evidence truth and authentication rules as the primary shell.

It does not replace the primary product navigation or application surfaces.

---

# Incident Receipt

**Purpose:** Focused case review and action  
**Owner:** CleanHouse

## Requirements

- Preserve the complete case evidence chain.
- Maintain provenance.
- Show observations and findings.
- Show authorization state.
- Show proposed actions.
- Show executed actions only after receipt.
- Preserve related decisions.
- Support safe review.

A suggested action does not become executed without authorization and verified execution.

---

# ctrl

**Purpose:** Shared contextual control center  
**Owner:** CleanHouse

## Surface ownership

| Surface | ctrl capability |
|---|---|
| Overview | Process insights and bounded process controls |
| Applications | Application insights and controls |
| Network | Network insights and controls |
| Files | File insights and controls |
| Zaelith | Prompt insights and universal remote |
| Identity | Cybersecurity insights and controls |
| Reports | State and federal legal-technology insights |

## States

```text
no-selection
evidence-detail
```

The detail back control returns to no selection.

No product-wide `ctrl` home page is inferred without an owner-defined contract.

## Layout rules

- Detail menus belong in the panel header.
- Destination, Event, and Finding links belong in their section headers.
- Explanatory bodies remain plain language.
- Controls follow current evidence context.
- Controls preserve the selected object and scope and emit immutable receipts.

## Action contract

Available:

- Mark Read.
- Mark Unread.
- Copy Evidence.
- Export Evidence.
- Observe.

These actions require:

- Backend-authoritative availability.
- Idempotent request identity.
- Verification.
- Receipt-safe preservation state.

## Guarded enforcement

Actions remain disabled until the complete enforcement contract exists:

```text
Block
Restrict
Quarantine
Terminate
Force Quit
```

Required:

- Guarded local enforcement provider.
- Valid authorization scope.
- Confirmation.
- Post-action verification.
- Immutable receipt.

Disabled actions expose the real reason.

---

# CleanHouse Insights

**Purpose:** Cross-platform evidence-backed inference  
**Owner:** CleanHouse

## Status

| Contract | Status |
|---|---|
| Cross-platform CleanHouse Insights | Canonical |
| macOS Apple Intelligence/Foundation Models helper artifacts | Implemented — unverified |
| macOS live provider acceptance | NOT ENOUGH EVIDENCE |
| macOS helper composition and evidence actions | Experimental |
| Windows Copilot provider | Planned |
| Android Copilot provider | Planned |
| Linux provider | NOT ENOUGH EVIDENCE |

## Platform names

| Platform | Visible name | Inference provider |
|---|---|---|
| macOS | Apple Intelligence Insights | Apple Foundation Models |
| Windows | Copilot Insights | Microsoft Copilot |
| Android | Copilot Insights | Microsoft Copilot |
| Linux | NOT ENOUGH EVIDENCE | NOT ENOUGH EVIDENCE |

## CleanHouse ownership

CleanHouse owns:

- Evidence selection.
- Bounded context.
- Permissions.
- Routing.
- Input schemas.
- Output schemas.
- Confidence.
- Limitations.
- User experience.
- Lifecycle states.
- Receipts.
- Preservation.
- Validation.
- Fallback.

The platform provider supplies inference.

The provider does not own evidence truth, product authorization, or CleanHouse behavior.

## Insight contract

Each insight:

- Binds to an evidence key.
- Identifies evidence.
- Distinguishes evidence from inference.
- Exposes confidence and limitations.
- Identifies unsupported or unavailable operation.
- Preserves its receipt and provenance.

Provider logos, assets, labels, helper processes, and generic integration references do not prove operational inference.

---

# Mediation

**Purpose:** Shared security decision and review taskboard  
**Owner:** CleanHouse  
**Execution authority:** Zaelith authorization and enforcement

## Surfaces

Mediation is shared across:

```text
Overview
Applications
Network
Files
Zaelith
Identity
Reports
```

## Four-lane model

```text
QUEUE
    ↓
IN PROGRESS
    ↓
READY
    ↓
LEDGER
```

## Requirements

- Durable queue state.
- Evidence references.
- Explicit scope.
- Immutable transition receipts.
- Searchable Ledger.
- Replayable history.
- Preservation of every decision.

## Attention counts

Count:

- Unacknowledged suggestions.
- Ready reviews.
- Conflicts.
- Failures.

Routine in-progress work does not inflate attention counts.

## Execution boundary

Until Zaelith provides authorization envelopes and enforcement:

`unavailable_until_zaelith`

Mediation cannot execute an unauthorized action.

---

# Runtime & Readiness

**Owner:** CleanHouse  
**Methodology:** Start-aligned  
**Status:** Implemented — verified bounded foundation

## Canonical startup

```text
CleanHouse Launcher
    ↓
macOS LaunchAgent
    ↓
Supervisor
    ↓
Managed Application Runtime
    ↓
CleanHouse Backend
    ↓
127.0.0.1:3333
```

Direct ad hoc background servers are not canonical runtime authority.

## Runtime requirements

- Stage a source-current isolated application runtime.
- Prefer the managed runtime interpreter.
- Survive invoking-shell exit.
- Own exactly one listener.
- Maintain fresh heartbeat.
- Separate liveness from readiness.
- Reconcile persisted and live state.
- Reject stale state.
- Detect foreign listeners.
- Detect duplicate listeners.
- Detect missing listeners.
- Detect PID mismatch.
- Bound restart attempts.
- Surface recovery and blocked states.
- Preserve startup evidence.
- Preserve self-deviation evidence.
- Stop and join owned collectors cleanly.

## Liveness

**Endpoint:** `GET /health`  
**Contract:** `cleanhouse.backend_liveness.v1`

Purpose: backend liveness only.

It does not establish operator readiness.

## Operator readiness

**Endpoint:** `GET /cleanhouse/status?ready=1`

**Behavior:** Fail closed.

Readiness requires:

- Valid runtime state contract.
- Warm startup phase.
- Healthy runtime.
- Alive supervisor.
- Alive backend.
- Fresh heartbeat.
- Passing bounded liveness probe.
- Exactly one expected listener.
- Listener ownership agreement.
- Backend PID agreement.
- No foreign listener.
- No duplicate listener.
- No self-deviation restart block.
- No hard resource block.

Bootstrap timestamp, loaded LaunchAgent, open port, responsive backend, or historical success alone is insufficient.

Optional collector degradation remains visible without automatically invalidating overall readiness unless the canonical runtime contract identifies that collector as readiness-critical.

---

# Authentication & Trust

**Owner:** CleanHouse  
**Methodology:** auth-aligned  
**Status:** Implemented and focused-tested foundation; live provider acceptance remains separate

## Identity lifecycle

- Enrollment.
- Authentication.
- Identity verification.
- MFA.
- Sign-in.
- Sessions.
- Recovery.
- Trust.
- Reverification.
- Related identity handshakes.

auth supplies methodology.

CleanHouse owns its product implementation and session contract.

## Required behavior

- Protected routes fail closed.
- `/overview` is the post-authentication landing page.
- Provider availability reflects real configuration.
- Unconfigured providers remain hidden or unavailable.
- OAuth state is session-bound.
- OAuth state expires.
- OAuth state is single-use.
- PKCE is used where supported.
- Callback validation is exact.
- Origin validation is exact.
- Callback failures are sanitized.
- Browser identity is server-owned.
- Browser identity uses cookie-backed sessions.
- Canonical session truth comes from the authenticated identity endpoint.
- Logout clears and invalidates the complete product session.
- Recovery tokens are hashed.
- Recovery tokens expire.
- Recovery tokens are single-use.
- Recovery does not enumerate accounts.
- Account deletion and other sensitive mutations require reverification and CSRF protection.
- Desktop authentication uses the system browser and the same product session contract.

## Secrets

Secrets remain in approved secure storage.

Prohibited destinations:

```text
client code
plist values
argv
logs
staged public configuration
```

## Provider dependencies

- Turnstile.
- External authentication providers.
- Owner-controlled configuration.

Missing provider configuration produces an intentional unavailable state.

It does not disable authentication or create a fabricated test account.

No task may invent credentials, guess passwords, create unauthorized accounts, weaken protected routes, or silently replace the authentication architecture.

---

# Evidence & Findings

## Evidence authority

Every evidence record retains its source and provenance.

Derived records identify their source evidence and reproducible derivation.

Inferred findings identify uncertainty.

Unknown evidence remains unknown.

## Findings

A finding is an evidence-backed condition requiring attention.

A finding does not inherently mean malicious or unauthorized.

## Deviations

A deviation is an observed departure from a baseline, expected state, or approved scope.

Examples:

- File integrity changed.
- Process runtime changed.
- Action exceeded approved scope.
- Collector stopped producing evidence.
- Provider state contradicted its contract.

Maliciousness and authorization remain separate judgments.

---

# Receipts & Preservation

## Receipts

Every consequential action and transition produces a durable receipt.

Covered events:

- Actions.
- State transitions.
- Reconciliation.
- Approval.
- Rejection.
- Rollback.
- Preservation attempts.
- Provider handoffs.

## Receipt fields

- What happened.
- When it happened.
- Evidence involved.
- Scope.
- Observed actor, if available.
- Authorization basis, if any.
- Result.
- Originating surface.
- Preservation state.
- Prior receipt or generation where continuity matters.

Receipts are append-only.

Corrections add evidence.

They do not erase previous records.

## Local storage

**Purpose:** Hot evidence cache and durable offline outbox.

Stores:

- Append-only events.
- Cursors.
- Integrity generations.
- Mediation state.
- Receipts.
- Provider-preservation state.

Local state survives restart.

Mutable projections may be rebuilt from immutable records.

Immutable history is not replaced by a latest-state row.

## OVVAULTS

**Purpose:** Canonical long-term preservation  
**Authority:** OVVAULTS  
**Access:** Authenticated VVAULT routes

### Requirements

- Additive.
- Authenticated.
- Idempotent.
- Bounded.
- Replayable.
- Durable local outbox.
- Explicit backlog.
- Oldest pending evidence.
- Last success.
- Last error.

Local unauthenticated port failure does not establish canonical OVVAULTS unavailability.

Local VVAULT runtime health and authenticated preservation truth remain distinct.

VVAULT does not replace CleanHouse's local session store or product database.

It does not authorize a second CleanHouse application database.

## Data minimization

- Collect minimum necessary evidence.
- Exclude hidden reasoning.
- Exclude unrelated user content.
- Exclude credentials.
- Exclude bearer tokens.
- Exclude private keys.
- Exclude enrollment secrets.
- Exclude administrator passwords.
- Redact diagnostics before export.
- Retention and pruning are receipted policy actions.
- Retention and pruning never silently rewrite history.

---

# External Integrations

## Wireshark

**Purpose:** Packet evidence and derived network views.

**Provider attribution:** `Powered by Wireshark` remains permanently visible on the Network surface.

**Validation:** Operational state is verified from the installed Wireshark engine, capture provenance, packet sequence, and source-linked derived views.

**Failure:** Degraded Network state without fabricated packets.

## Wazuh

**Purpose:** File integrity, inventory, hashes, ownership, permissions, and reconciliation.

**Installation:** Bundled, verified agent.

**Privilege:** One explicit macOS administrator prompt. No silent elevation.

### Hosted topology

Manager-only Wazuh on the existing VVAULT host.

Does not introduce:

- New Droplet.
- Container.
- Indexer.
- Dashboard.
- Filebeat service.
- PostgreSQL database.
- OVVAULTS schema.

Manager operational state is not a second CleanHouse application database.

## VVAULT / OVVAULTS

**Purpose:** Authenticated preservation and replay.

**Boundary:** Least-privileged routes. No unrestricted index or database access.

**Failure:** Durable local backlog and explicit preservation degradation.

## Zaelith

**Purpose:** Actor confidence, approval envelopes, scope authorization, and enforcement.

Identity never equals permission.

Unavailable authorization keeps Mediation non-executing.

## Orange

**Purpose:** Metadata verification and bounded patching  
**Status:** Planned

Applies to:

- Applications.
- Files.
- Identity.

Metadata repair requires evidence, preview, approval, and receipt.

## Chronos

**Purpose:** Chronological campaign continuity

Includes:

- Milestones.
- Schedules.
- Pending actions.
- Recurring automation.
- Historical reconstruction.

**Present:** Agent-facing AI Wizard.  
**Future:** Human-facing Chatty application.

Chronos remains a separate product authority. CleanHouse integrates it without absorbing or redefining it. Chronos does not become CleanHouse's security evidence authority.

---

# Product Ownership & Wizards

## Ownership map

| Concern | Owner |
|---|---|
| Product canon | Human owner |
| Startup/runtime methodology | Start |
| Authentication methodology | auth |
| Deterministic orchestration methodology | AUTO |
| Distribution and SEO methodology | drbt |
| Chronological continuity | Chronos |
| Security validation | K.A.T.A.N.A. |
| Product implementation | CleanHouse |
| Packet evidence | Wireshark |
| File-integrity evidence | Wazuh / labeled fallback |
| Long-term preservation | OVVAULTS |
| Authorization integration | Zaelith |
| Metadata verification | Orange |

## Wizard boundaries

### Start

Question: Can the product run?

Owns methodology for startup, runtime health, readiness, and supervision.

### auth

Question: Who can use it, and under which identity and trust rules?

Owns authentication methodology, not CleanHouse's runtime session.

### AUTO

Question: How should product changes be safely orchestrated?

Owns deterministic orchestration direction.

### drbt

Question: How does CleanHouse become packaged, deployed, published, discoverable, and reachable?

Owns distribution, stores, domains, DNS, and SEO methodology.

### Chronos

Question: What happened, what happens next, and how is continuity preserved?

Present agent-facing AI Wizard.

Future human-facing application belongs to Chatty.

Wizards do not become persistent CleanHouse dependencies or override owner decisions.

---

# K.A.T.A.N.A.

**Identity:** Cross-cutting security specialist and validation authority  
**Organization:** Hydro team  
**Class:** Security authority, not Wizard  
**Authorization:** Human owner retains final authority

**Status**

- Authority contract: canonical
- Automated validation pipeline direction: planned
- Implemented automated validation pipeline: NOT ENOUGH EVIDENCE
- Accepted live security pipeline: NOT ENOUGH EVIDENCE

## Responsibilities

- Security validation.
- Automated repeatable security checks.
- Adversarial testing.
- Finding intake.
- Bounty intake.
- Classification.
- Evidence collection.
- Adaptation to new evidence.
- Remediation-design boundaries.
- Fix verification.
- Regression tests.
- Receipts.
- Provenance.
- Unresolved findings.
- Risk acceptance.
- Fail-closed decisions.
- Continuous improvement without canon drift.

## Bounty-adaptation lifecycle

Security findings remain evidence-bearing until verified.

New evidence may modify classification and remediation proposals.

K.A.T.A.N.A. defines validation and remediation boundaries.

It does not:

- Silently authorize destructive actions.
- Rewrite product canon.
- Erase contrary evidence.
- Convert unresolved risks into accepted risks.

Risk acceptance requires:

1. Authorized human handler.
2. Explicit acceptance.
3. Durable receipt.

---

# Accessibility

**Owner:** CleanHouse  
**Applies to:** Every permanent surface

## Requirements

- Keyboard-only navigation.
- Visible focus.
- Semantic headings.
- Landmarks.
- Accessible icon names.
- Accessible control names.
- Current-page state.
- Selected-tab state.
- Meaningful live-region announcements.
- Non-color-only status.
- Reduced motion.
- Readable contrast.
- Scalable text.
- Desktop and mobile support.
- No hidden essential controls.
- Understandable constrained tables.
- Clear subsystem errors.
- Safe retry path.

## Overlays

- Focus entry.
- Focus containment where appropriate.
- Escape/close behavior.
- Focus restoration.

ARIA presence alone does not prove accessibility.

Acceptance is behavioral.

---

# Performance & Resources

## Resource ceiling

**Development and verification RAM ceiling:** 10 GB

## Runtime requirements

- Bounded memory.
- Bounded queues.
- Bounded retained windows.
- Bounded subscriber buffers.
- Bounded response sizes.
- No collector busy loops.
- Bounded retries.
- Explicit retry reasons.
- Optional services do not indefinitely block startup.
- UI hydration does not load unbounded history.
- Slow preservation creates a durable backlog.

Evidence-heavy views use:

- Pagination.
- Cursors.
- Aggregation.
- Bounded windows.

Process and listener ownership must be verified before control operations.

---

# Configuration & Installation

## Configuration

Checked-in configuration contains public contracts and secure-reference metadata only.

Secrets remain in approved secure storage or owner-controlled deployment configuration.

Environment settings:

- Namespaced.
- Documented.
- Consistent across development and managed runtime paths.

Configuration presence does not establish provider health.

## Installation

- Runtime staged from reviewed artifacts.
- Dependencies staged from reviewed artifacts.
- No silent ordinary-runtime Wazuh download.
- No silent ordinary-runtime Wireshark download.
- Privileged installation uses normal OS authorization UI.
- Installers accept fixed verified package paths.
- Temporary secret-bearing materials are owner-only.
- Secret-bearing materials stay out of logs.
- Temporary secrets are removed after successful use.
- Failed installations retain non-secret state for idempotent retry.

---

# Platform & Distribution

**Methodology:** drbt-aligned

## Distribution boundary

Distribution requires separate review.

Local administrative interfaces must not be exposed merely for deployment convenience.

## Platform roadmap

1. macOS product completion.
2. Final repository rematerialization test.
3. Windows.
4. Linux.
5. Android and iOS.

All ports preserve:

- Evidence truth.
- Authorization.
- Accessibility.
- Truthfulness.

Collectors and packaging may be platform-native.

---

# Verification

**Method:** Focused, risk-proportionate proof.

Repository-wide test runs and bulk evidence generation are not routine requirements.

## Required evidence as applicable

- Compilation and import closure from committed or candidate state without dirty overlays.
- Focused unit tests.
- Shared-seam regression tests.
- Failure behavior.
- Timeout behavior.
- Retry behavior.
- Recovery.
- Degraded states.
- Authentication.
- Authorization.
- Append-only persistence.
- Deduplication.
- Cursor recovery.
- Outbox replay.
- Process ownership.
- Listener ownership.
- Heartbeat.
- Readiness.
- Browser routing.
- Session continuity.
- Console.
- Network.
- Desktop/mobile.
- Accessibility.
- Package checksums.
- Signatures.
- Notarization.
- Manifests.
- Secret exclusion.
- Private-content exclusion.
- Documentation congruence.
- Changed-path scope.
- Preservation of unrelated work.

Fixture acceptance does not establish live-provider operation.

Screenshots are acceptance evidence only when:

- Fresh backend responses are used.
- Authentication state is known.
- The tested surface corresponds to current behavior.

---

# Capability Status Ledger

## Status definitions

| Status | Meaning |
|---|---|
| Canonical | Required behavior or boundary |
| Implemented — verified | Focused evidence supports an accepted implementation |
| Implemented — unverified | Code/UI exists without focused acceptance of current composition |
| Partial | Coherent implementation with missing required behavior |
| Planned | Canonical destination without accepted implementation |
| Experimental | Exploratory work outside accepted contract |
| Provider action required | Owner/external provider action remains |
| Superseded / historical | Historical evidence, not current authority |
| Contradicted | Artifacts disagree |
| NOT ENOUGH EVIDENCE | Evidence insufficient to determine a fact or value |

Evidence-bearing claims include:

```text
healthy
ready
live
operational
authenticated
authorized
verified
powered by
complete
```

None may be inferred from appearance, configuration, process presence, cached pages, or historical success.

## Implemented — verified

- Product-native authentication foundation.
- Provider availability and secure runtime configuration.
- Sessions, recovery, logout, and focused auth validation.
- LaunchAgent and supervisor foundation.
- Fail-closed readiness with separate liveness.
- Managed runtime staging and bounded recovery.
- Network Core lifecycle, replay, fan-out, gaps, persistence, watchdog, and shutdown.
- Network capture-engine-unavailable degradation.
- Bounded Wazuh evidence core.
- Authenticated-provider classification.
- Wazuh normalization, cursors, and failure states.
- Pinned macOS Wazuh supply-chain closure.
- Local append-only evidence.
- Shared Network/Files durable OVVAULTS outbox.
- Receipt-validation foundation.

Live authenticated preservation delivery remains a separate gate.

## Implemented — unverified

- Shared browser shell.
- Navigation.
- Overview presentation.
- Applications inventory and cards.
- Network Table and visualizations.
- Files tabs.
- Files reconciliation control.
- Wazuh branding gate.
- Mediation panel and board.
- Zaelith pages.
- Provider-connection pages.
- Identity placeholder.
- Reports history.
- Allowed Threats.
- Help.
- Advanced Monitor.
- Custom Scan.
- Incident Receipt.
- Contextual `ctrl`.
- macOS Insights helper artifacts.
- Shared evidence, provider, control, notification, approval, receipt, rollback, and report APIs.

These overlap substantial unreviewed working changes.

## Partial

- FullHouse and Process operational scans.
- Application combined scanning and controls.
- Live Wireshark capture packaging and accepted visualization.
- Owner-environment authoritative Wazuh reconciliation.
- Shared Mediation across all surfaces.
- Zaelith identity, authorization, providers, watchdog, and enforcement.
- Reports receipt repositories and legal controls.
- Advanced Monitor primary-shell integration.
- Allowed Threats mutation acceptance.
- Integrated authenticated browser acceptance.

## Planned

- Orange metadata verification and patching.
- Identity providers and social monitoring.
- Identity Privacy Score contract.
- drbt SEO and distribution.
- Windows Copilot Insights.
- Android Copilot Insights.
- CleanHouse VPN.
- K.A.T.A.N.A. automated pipeline.
- Final CSS rubric.
- Network Real Time Security Suite.
- Complete contextual `ctrl`.
- Final repository rematerialization.
- Windows, Linux, Android, and iOS products.

## Provider action required

- Signed-in VVAULT pairing and credential rotation.
- Flush existing Files verification row.
- Flush exactly one bounded Network verification row.
- Verify immutable authenticated receipts in `ovvaults.vault_files`.
- Complete owner-controlled Google configuration.
- Complete Turnstile configuration.
- Complete recovery-email configuration.
- Complete Wazuh enrollment/manager acceptance.
- Complete other applicable external-provider acceptance.

Preservation cannot report `live` until matching authenticated receipts exist.

## Experimental

- macOS Apple Intelligence Insights helper composition.
- Evidence actions not yet live-provider accepted.
- Unaccepted provider/orchestration helpers.
- Visualization prototypes.
- Resilience prototypes.
- Low-processing prototypes.

## Superseded / historical

- `/health` recursively determining readiness.
- Readiness from liveness alone.
- Readiness from timestamps or LaunchAgent presence alone.
- Unmanaged production servers.
- Browser-local bearer-token session truth.
- Integrity inferred from a recent event window.
- Wazuh branding from installation/configuration.
- Actor identity as authorization.
- Duplicated Files Status/Location columns.
- Raw-packet primary Network Table.
- Local mirrors/in-memory delivery treated as canonical preservation proof.

---

# Contradictions

## Product shell

**Conflict:** Product pages exist while some accepted boundaries excluded UI.

**Rule:** Canon preserves pages. Implementation acceptance must catch up.

## Network branding

**Architecture:** Wireshark is the permanent Network capture provider and attribution.

**Rule:** Provider attribution remains visible. Independent `VERIFYING`, `VERIFIED`, and `DEGRADED` state communicates live validation truth.

## Files Wazuh history

**Conflict:** Historical Wazuh records coexist with degraded/fallback current health.

**Rule:** Historical proof and current health remain separate.

## Authentication

**Conflict:** Focused tests pass while interactive provider acceptance is blocked.

**Rule:** Focused implementation does not prove live provider acceptance.

## Runtime

**Conflict:** Runtime healthy while optional collector degraded.

**Rule:** Show degradation without changing readiness semantics.

## OVVAULTS

**Conflict:** Transport tests pass while canonical preservation remains warming/degraded/unavailable.

**Rule:** Authenticated matching receipts establish canonical delivery.

## Historical documentation

**Conflict:** Older documents describe reduced or differently named surfaces.

**Rule:** Current master canon controls destination.

## Network selected-row ordering

**Conflict:** Later owner decision pins selected row first; earlier Network Product Contract prohibited selection-driven reordering.

**Rule:** Later owner decision controls destination. Preserve conflict, migration effects, and tests until reconciliation.

## Network release acceptance

**Conflict:** Browserless tests prove substantial mechanics; later audit identifies row-identity, lifecycle, omission accounting, document-integrity, and release-gate failures.

**Rule:** Verified Network Core does not upgrade full Network UI to release-accepted.

---

# NOT ENOUGH EVIDENCE

## CSS

- Colors and semantic state values.
- Final token values.
- Typography measurements.
- Alignment and sizing measurements.
- Spacing.
- Shell dimensions.
- Panel dimensions.
- Borders.
- Radii.
- Opacity.
- Shadows.
- Breakpoints.
- Interaction measurements.
- Motion values.
- Objective accepted styling rubric.

## Network

- Capture-generation boundary.
- Observed-versus-inferred completion.
- Interruption semantics.
- Long-duration retention.
- Bounded-row omission disclosure.

## CleanHouse Insights

- Linux provider.

## Identity

- Score methodology.
- Weights.
- Cadence.
- Sources.
- Accepted measurements.

## VPN

- Provider.
- Protocol.
- Infrastructure.
- Routing policy.
- Hardware details.
- Performance budgets.
- Accepted implementation.

## K.A.T.A.N.A.

- Implemented automation pipeline.
- Accepted live security pipeline.

---

# Reconstruction Order

1. Preserve user data, credentials, sessions, databases, evidence, transcripts, and complete working tree.
2. Establish canon and identify contradictions.
3. Restore runtime authority, managed interpreter, LaunchAgent, supervisor, liveness, heartbeat, listener ownership, and readiness.
4. Restore authentication and owner session without inventing credentials.
5. Restore complete shell and every permanent route.
6. Restore append-only evidence, receipts, cursors, outboxes, and integrity.
7. Restore Network Core and truthful capture state.
8. Restore Files/Wazuh and truthful fallback state.
9. Restore Overview and Applications.
10. Restore `ctrl` and Mediation without unauthorized execution.
11. Restore Zaelith, Identity, Reports, Allowed Threats, Help, Advanced Monitor, and Incident Receipt.
12. Reconnect OVVAULTS and verify nonduplicating replay.
13. Run focused clean-source and browser acceptance.
14. Run final repository rematerialization.

No broad reset, cleanup, or reduced shell is a valid shortcut.

Missing implementations preserve their routes and expose their actual states.

---

# Definition of Done

## Product-wide

Release requires:

- Canonical startup.
- Runtime survival after shell exit.
- Exactly one owned listener.
- Complete fail-closed readiness.
- Live authentication and session acceptance.
- All permanent routes.
- No fabricated evidence or claims.
- Useful Overview under subsystem degradation.
- Authorized and receipted controls.
- Durable evidence across restart.
- Durable integrity and cursors.
- Recoverable preservation.
- Desktop/mobile accessibility acceptance.
- No unexpected console, asset, or route regressions.
- Protected secrets and diagnostics.
- Documentation congruence.
- Cleanup of all temporary test processes, ports, and artifacts without touching user data.
- Reconstructable accepted changes.

## Overview

- FullHouse Scan operational.
- Process Monitor/Scan operational.
- Partial results explicit.
- Aggregates linked to evidence.
- `ctrl` functional.
- Mediation functional.

## Applications

- Combined process, metadata, Network, Files, and applicable Zaelith evidence.
- Truthful Orange availability.
- Authorized and receipted actions.

## Network

- Genuine Wireshark evidence.
- Distinct Connections, Findings, Trend, Distribution, Timeline behavior.
- Shared assessment identity and category across the Network header, all five
  views, and `ctrl` without browser-side reclassification.
- Graph/Chart duplicate navigation remains visible on Trend and Distribution.
- Distribution presents one evidence-backed donut and one matching owner list.
- Safe degraded capture.
- Real Time Security Suite.
- `ctrl`.
- Mediation.

## Files

- Installed and enrolled Wazuh agent.
- Connected and scanning provider.
- Authenticated scoped evidence.
- Earned Wazuh branding.
- Verified hashes, ownership, permissions, metadata, cursors, deduplication, and preservation.
- Authoritative reconciliation.
- Labeled partial fallback.
- `ctrl`, Orange, and Mediation.

## Zaelith

- Evidence-backed actor confidence.
- Working approval envelopes.
- Working scope validation.
- Reproducible authorization classification.
- Official provider consent.
- Bounded and receipted controls.

## Identity

- Official operational providers.
- Traceable account risk evidence.
- Auth-aligned identity lifecycle.
- Orange boundaries.
- drbt coordination.
- Identity Privacy Score evidence contract before numeric scoring.

## Reports

- Receipt-ledger coverage.
- Local/cloud/other-environment distinction.
- Complete redaction-aware export.
- Independently reviewable evidence.
- No overstated legal effect.

---

# Change Control

**Authority:** Human owner

Canon changes require:

1. Exact existing requirement.
2. Proposed replacement.
3. Reason implementation cannot satisfy current canon.
4. Affected surfaces, data, routes, integrations, and users.
5. Migration and rollback.
6. Required acceptance evidence.
7. Historical receipt/data meaning changes.
8. Explicit owner approval.

The following do not constitute approval:

- Broad implementation prompts.
- Passing tests after deleting product surfaces.
- Cleanup recommendations.
- Temporary bounded exclusions.
- Stale documentation.
- Generated scaffolds.
- Agent assumptions.

When implementation and canon disagree:

```text
Preserve evidence
    ↓
Identify contradiction
    ↓
Label implementation status
    ↓
Repair toward canon
       OR
Request explicit owner decision
    ↓
Receipt
```

No page, workflow, named integration, or product promise may be removed, renamed, hidden, substituted, or reduced merely because implementation is incomplete.

---

# Product Direction

CleanHouse's near-term work is to finish the evidence-backed macOS product without turning unfinished integrations into architectural blockers.

## Priorities

1. Preserve shell, runtime, and authentication foundations.
2. Finish Overview and Applications.
3. Complete Wireshark-backed Network.
4. Complete Wazuh installation, enrollment, reconciliation, and Files.
5. Complete Mediation and `ctrl`.
6. Complete Zaelith authorization and universal remote.
7. Complete Identity providers and Orange coordination, with drbt distribution/SEO.
8. Complete Reports and legal-technology workflows.
9. Define and implement CleanHouse VPN.
10. Close CSS rubric against accepted visual evidence.
11. Pass final repository rematerialization.
12. Expand to Windows, Linux, Android, and iOS.

**Operating principle:** Observable, independently degradable, owner-controlled, reconstructable security capabilities backed by evidence and receipts.

---

