# CleanHouse Network Product Contract

Status: Locked  
Effective: 2026-07-12

## Authority

This document is the normative source of truth for observable Network product
behavior and evidence guarantees. It supersedes conflicting Network semantics
in earlier documentation, validation artifacts, tests, and implementation.

Raw packet evidence outranks any conflicting CleanHouse-derived normalization,
translation, or interpretation.

## Product Story

Network tells one evidence-backed story from five perspectives:

- what communications were observed;
- what those communications mean;
- how activity changed;
- where activity is concentrated;
- which moments deserve review.

No tab outranks another as a product perspective. Each answers a distinct
operator question. No tab derives truth from another tab's rendered rows or UI
state.

## Evidence Contract

### Wireshark Evidence

Wireshark/tshark supplies observed packet facts: capture time, capture-scoped
packet identity, length, protocol, visible source and destination endpoints,
ports, flags, and protocol metadata actually present in captured evidence.
Direction is a Wireshark fact only when capture metadata establishes it;
otherwise direction is a CleanHouse-derived inference or remains unknown.

These packet facts are immutable. CleanHouse must never rewrite, invent, or
silently reinterpret them.

### CleanHouse-Derived Information

CleanHouse may add:

- operator-visible communication records;
- app/process attribution;
- destination and service names;
- inferred direction;
- packet and byte totals;
- plain-language Translation;
- confidence and evidence level;
- findings, trend measurements, distribution aggregates, and timeline events.
- versioned Strength, Vulnerability, and Threat assessments.

Every derived value must remain traceable to its supporting evidence and
distinguish `observed`, `inferred`, and `unknown`.

### Product Layers

- **Raw evidence:** unchanged Wireshark packet facts.
- **Normalized observation:** CleanHouse organization of packet evidence for
  operator use.
- **Translation:** plain-language explanation of observed facts.
- **Interpretation:** review priority, risk meaning, and recommended attention.

Translation must not masquerade as raw evidence. Interpretation belongs
primarily to Findings.

### Shared assessment truth

The backend-owned `cleanhouse.security_assessment.v1` contract supplies one
stable assessment identity, category, rule version, subject, and bounded set of
evidence references to every Network projection. Category is exactly Strength,
Vulnerability, or Threat and remains independent from severity, confidence,
lifecycle, owner disposition, provider health, and runtime health.

The browser may select, filter, group, and render shared assessments. It must
not classify evidence independently. An operational state such as warming,
degraded, offline, retrying, blocked, unavailable, permission failure, or a
continuity gap is never a security category.

## Connections Contract

The visible product label is **Connections**. Existing implementation, API,
URL, storage, replay, and test identifiers may remain `table`; that compatible
internal name does not change the operator-facing contract.

### Operator Question

> What communication occurred, between whom, how, and what observable evidence
> supports it?

### What Is One Row?

A Connections row presents one operator-visible communication record.

A Connections row exists only when it is reproducible from immutable Wireshark packet
evidence.

A Connections row is not:

- an installed or open application;
- a socket inventory entry;
- a security finding;
- an unsupported summary;
- synthetic or fallback evidence presented as captured traffic.

The Product Contract does not select the implementation representation or
identity of a row.

### What Creates a Row?

A Connections row is created only after real Wireshark packet evidence makes the
operator-visible communication reproducible.

Derived labels, app inventory, socket state, or presentation convenience alone
must never create a Connections row.

The mechanics used to decide that evidence belongs in a new row are
intentionally deferred.

### What Updates a Row?

A Connections row may be enriched by newly observed evidence but must never rewrite
previously observed packet facts.

An update may visibly add or revise derived information such as:

- the most recent observed time;
- packet and byte totals;
- inbound, outbound, or unknown activity;
- newly visible protocol facts;
- supporting evidence references;
- app, service, or destination attribution;
- Translation, confidence, or evidence level.

Every update must remain traceable to evidence. Derived revisions must remain
distinguishable from observed facts.

The mechanics used to attribute new evidence to an existing row are
intentionally deferred.

### What Completes a Row?

Completion must be visible to the operator and distinguished as either:

- **observed**, when direct evidence establishes that the represented
  communication ended; or
- **inferred**, when the end is derived from an approved rule rather than
  directly observed.

Once a row is presented as complete, later evidence must not silently rewrite
the earlier record as though the end had never occurred.

The evidence rules and mechanics that establish completion are intentionally
deferred.

### What Interrupts a Row?

A row is interrupted when capture continuity or completeness becomes
unknowable.

Interruption must be visible to the operator and must identify continuity as
unknown. CleanHouse must not silently bridge an evidence gap or present later
evidence as proof that the gap did not occur.

The mechanics used to detect and represent interruption are intentionally
deferred.

### What Removes a Row?

A row may leave visible Connections when it no longer belongs to the declared
visible scope or when an operator filter excludes it.

Removal from visible Connections must never silently delete or break access to
the row's supporting evidence while that evidence remains retained under an
approved policy.

Visibility, retention, and removal mechanics are intentionally deferred.

### Default Ordering

The default order is the most recently observed communication first.

Ties must resolve deterministically from evidence-backed values. Selecting a
row must not silently change the underlying order.

The deterministic tie-breaking mechanism is intentionally deferred.

### Translation

Translation explains an operator-visible communication record in plain
language, including:

- who or what appears to be communicating;
- where the communication appears to be going;
- which service or protocol is visible;
- whether the communication appears local or external;
- how much activity was observed when that information is displayed;
- what remains unknown.

Translation may simplify technical names and combine supported facts. It must
distinguish observed facts, labeled inferences, and unknowns. It must not invent
intent, claim contents that were not visible, manufacture ownership, or declare
a threat.

## Tab Perspectives

All tabs examine authoritative Network evidence independently: immutable packet
observations, capture-state and continuity-gap records, and explicitly labeled
CleanHouse derivations. They may examine overlapping evidence, but each must
preserve its own question, displayed record, allowed evidence, and exclusions.

| Tab | Operator question | Record shown | Allowed evidence | Forbidden evidence |
|---|---|---|---|---|
| **Connections** | What communication is occurring or recently occurred? | One operator-visible communication record | Immutable Wireshark packet evidence plus clearly labeled attribution, Translation, and shared assessment references | Rows that are not reproducible from packet evidence, app inventory, findings presented as facts, hidden continuity gaps |
| **Findings** | What deserves review, and why? | One grouped semantic finding | Underlying packets, communication records, the shared assessment contract, attribution confidence, validated policy/context | Raw packet flooding, repeated equivalent findings, browser-local reclassification, unsupported intent or threat claims |
| **Trend** | How are active Connections, Strengths, Vulnerabilities, or Threats changing over time? | One evidence-backed time point or bucket for the selected graph metric | Observed activity and shared assessment lifecycles with visible gaps | Synthetic bars, prose/table substitution, current inventory presented as history, interpolation presented as observation |
| **Distribution** | Which apps or services account for observed network activity? | One evidence-backed app/service share in one donut and its matching owner list | Attributable observed communication with an explicit Unknown category | Installed/open-app inventory, duplicate application lists, zero-evidence entities, uncertain ownership presented as fact |
| **Timeline** | What notable network events, assessment transitions, and evidence gaps occurred, and when? | One notable event, assessment transition, or explicit gap | Observable Network activity, shared assessment changes, spikes, capture start/stop/interruption | Every routine packet, trend buckets masquerading as events, grouped markers bound to one arbitrary finding, fabricated continuity |

## Graph / Chart duplicate navigation

`Graph` selects Trend and `Chart` selects Distribution. The compact control is
visible on both visual tabs, uses Distribution as the placement reference, and
never switches between two Trend render modes. Trend remains a graph; Findings
and `ctrl` own explanatory text.

## Powered by Wireshark Invariants

Because Network claims **Powered by Wireshark**:

1. Every Connections row MUST be reproducible from immutable Wireshark packet evidence.
2. Every displayed packet fact must remain individually traceable and
   reviewable from its Connections row while the evidence is retained under an
   approved policy.
3. Packet identities, timestamps, lengths, endpoints, protocols, and captured
   metadata must remain unchanged.
4. Displayed packet and byte totals must be reproducible from the underlying
   packet evidence.
5. Capture scope, unavailable interfaces, permission limits, dropped evidence,
   and continuity gaps must remain visible.
6. CleanHouse Translation, organization, attribution, and findings must be
   identified as CleanHouse-derived, not as Wireshark conclusions.
7. Open apps, installed apps, socket snapshots, and synthetic fixtures must
   never create Connections rows or be presented as Wireshark evidence.
8. If Wireshark evidence is unavailable, Connections must show unavailable, warming,
   interrupted, or empty truth. It must not substitute fallback evidence while
   retaining the Wireshark claim.
9. Every relationship claimed between a Connections row and packet evidence must
   remain traceable, reviewable, and reproducible.
10. No usability decision may destroy evidence integrity.

## Product vs Implementation Boundary

The Product Contract defines observable operator behavior and evidence
guarantees. It intentionally does not prescribe implementation strategy.
Multiple implementations may satisfy this contract provided operator-visible
behavior and evidence integrity remain unchanged.

## Deferred Implementation

Implementation intentionally deferred.

The Product Contract does not answer:

- row representation or identity;
- creation, update, completion, or interruption mechanics;
- protocol-specific behavior;
- timeout or visible-window values;
- storage or retention mechanics;
- APIs or schemas;
- collectors or live transports;
- SSE, caching, pagination, or browser rendering;
- algorithms or data structures.

These decisions belong exclusively to a separately approved implementation
contract.

## Contract Lock

This contract is locked as the source of truth for observable Network product
behavior and evidence guarantees. It supersedes conflicting product semantics
in earlier documentation, validation artifacts, tests, and implementation.

The following product decisions are authoritative:

- the Connections operator question and observable row behavior, with `table`
  retained as the internal compatibility identifier;
- creation, enrichment, completion, interruption, removal, and ordering as
  experienced by the operator;
- Translation boundaries;
- tab questions and evidence boundaries;
- Wireshark evidence guarantees.
- the shared assessment identity/category contract;
- Graph/Chart duplicate navigation;
- Trend's selectable graph metrics;
- Distribution's single donut and matching owner list.

Implementation remains intentionally deferred.
