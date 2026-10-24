# CleanHouse security-assessment taxonomy contract

## Authority and boundary

This is the authoritative subordinate contract for the shared
Strength/Vulnerability/Threat assessment model implemented first by Network.
It implements the owner canon in `CLEANHOUSE.md`; it does not independently
change that canon. Raw evidence remains authoritative and immutable.

The contract prevents a page or tab from reclassifying the same evidence for
presentation convenience. One assessment identity may appear in the Network
header, Connections, Findings, Trend, Distribution, Timeline, and `ctrl`, but
every projection retains the same category, rule version, subject, and evidence
references.

## Assessment schema

The canonical schema name is `cleanhouse.security_assessment.v1`.

Required fields:

| Field | Contract |
|---|---|
| `assessment_id` | Stable identity for this assessment lifecycle. |
| `assessment_key` | Deterministic lifecycle key derived from rule and stable subject identity. Bounded evidence references remain provenance and do not create duplicate assessment lifecycles. |
| `category` | Exactly `strength`, `vulnerability`, or `threat`. |
| `severity` | Impact/urgency independent from category. |
| `confidence` | Evidence confidence independent from category. |
| `assessment_state` | Lifecycle state such as active, resolved, contained, superseded, or unknown. |
| `owner_disposition` | Separate owner acknowledgment/authorization state; never a category rewrite. |
| `subject_type` / `subject_id` | Stable entity being assessed. |
| `rule_id` / `rule_version` | Named reproducible rule that produced the assessment. |
| `rationale` | Concise explanation grounded in referenced evidence. |
| `first_seen` / `last_seen` | UTC evidence-time bounds. |
| `evidence_refs` | Bounded immutable source identifiers. |
| `continuity` | Continuous, gap, unknown, or recovering coverage truth. |
| `generation` / `source_cursor` | Source stream identity and replay position where applicable. |

Additional projection metadata may be additive. Missing, malformed, or
unsupported required values fail closed; a consumer may not infer a category
from color, severity, provider health, or copy.

## Category meanings

### Strength

A Strength is evidence of a verified protection or favorable security
condition. Examples include verified encrypted transport, verified
application/destination attribution, a destination explicitly authorized by
the owner, and effective containment established by a receipt.

Port `443`, a provider name, or configured protection alone is not proof of a
Strength.

### Vulnerability

A Vulnerability is an evidenced weakness, exposure, uncertainty, or visibility
gap that could permit harm. Initial Network rules classify:

- an unknown application with externally observed activity;
- a missing destination identity.

An unusual port, new destination, traffic-volume change, or repeated attempt
is a neutral indicator until corroborating evidence satisfies a reviewed
Vulnerability or Threat rule.

### Threat

A Threat requires evidence of an active harmful condition or attempt. Examples
include verified malware, a verified malicious endpoint, active exfiltration,
unauthorized inbound access, exploitation, and containment bypass.

An allowed, acknowledged, blocked, or contained Threat remains a Threat.
Lifecycle and owner disposition describe its treatment without rewriting the
category or raw evidence.

## Independent dimensions

These dimensions are never aliases:

```text
category             strength | vulnerability | threat
severity             impact and urgency
confidence           evidence confidence
assessment_state     lifecycle
owner_disposition    acknowledgment/authorization
operational_health   capture/runtime/provider health
evidence_class       observed | derived | inferred | unknown
```

Warming, degraded, unavailable, blocked, retrying, offline, capture failure,
permission failure, and continuity gaps are operational or evidence-coverage
states. They never become security categories. The UI may present them beside a
posture summary, but it must not color or count them as Threats.

## Identity, persistence, and replay

- Raw evidence is never rewritten by assessment creation or transition.
- Assessment creation and transitions are append-only, idempotent, and
  committed before publication.
- Retried evidence produces the same assessment key and does not inflate
  projections.
- Lifecycle transitions preserve the assessment ID, earlier states, rule
  version, and evidence provenance.
- Evidence references and related identifiers remain bounded by the owning
  Network retention contract.
- Cursor advancement and assessment persistence are atomic where the provider
  supports a durable cursor.
- A stale cursor or continuity gap is explicit and cannot imply continuous
  coverage.

## Projection contract

Existing Network responses remain compatible and may add:

```text
assessments
assessment_refs
assessment_summary
assessment_filter
assessment_rule_version
assessment_coverage
assessment_gap
```

The backend is the only classification authority. Browser code selects,
filters, groups, and renders assessments; it never assigns or changes a
category.

### Header

Shows operational status/state/reason separately from a posture summary of
Strengths, Vulnerabilities, and Threats.

### Connections

Retains bounded assessment references for each evidence-backed connection. The
visible label is Connections while the compatible internal identifier remains
`table`.

### Findings

Owns plain-language rationale and the retained priority queue. It renders the
shared category, severity, confidence, lifecycle, rule, subject, and evidence
references.

### Trend

Remains a graph. It supports metrics `connections`, `strengths`,
`vulnerabilities`, and `threats`; Connections is the default. Category points
count distinct assessments active at a half-open bucket boundary. A covered
bucket with none is zero. Missing coverage is a gap, not zero.

### Distribution

Remains a packet-backed activity visualization. Its donut and single matching
owner list use the same rows, totals, colors, names, and evidence references.
Distribution may expose assessment references but does not reclassify them.

### Timeline

Shows factual notable events, assessment transitions, and continuity gaps.
Selecting a grouped interval exposes every contained event individually.

### ctrl

Uses the selected surface's exact evidence and assessment IDs. It may explain
the shared rationale and offer existing authorized actions; it does not grant
new execution authority.

## Visual and accessibility contract

- Strength uses the established local teal/green treatment.
- Vulnerability uses the established local amber treatment.
- Threat uses the established local red/pink treatment.
- Operational and lifecycle states use their independent neutral/status
  treatments.
- Text category labels and accessible names accompany color.
- Color never supplies the only category or state signal.

## Focused acceptance

The minimum deterministic fixtures prove:

1. Unknown external application plus missing destination plus unusual port,
   without harmful corroboration, yields two Vulnerabilities, zero Threats, and
   one neutral indicator.
2. Port `443` alone yields no encryption Strength.
3. Verified encrypted transport yields a Strength.
4. A verified malicious endpoint yields a Threat and may coexist with an
   independent encryption Strength.
5. Capture failure changes operational health without fabricating an
   assessment.
6. Replay retains IDs and does not duplicate assessment counts.
7. Header, Connections, Findings, Trend, Distribution, Timeline, and `ctrl`
   expose the same assessment IDs and categories.
8. Gaps remain gaps in Trend and Timeline.

Completion requires schema validation, focused persistence/replay tests,
Network projection tests, browserless UI contract tests, the protected-surface
verifier, and clean isolated browser acceptance. A test that passes by hiding
or removing a protected product surface is invalid.
