# Scope Gate — CleanHouse

**Gate text for all prompts and implementation decisions.**
*Do not proceed without passing this gate.*

---

## Project Identity

CleanHouse observes local processes, file integrity, and network connections. It reports deterministic pattern matches against hardcoded lists. It does not infer intent, detect threats, judge behavior, or govern AI systems.

---

## Forbidden Output Language

| Term | Reason |
|---|---|
| "unauthorized" (change detection) | Cannot distinguish authorized vs. not — reports *any* change equally |
| "malicious", "threat", "attack" | No security enforcement mechanism exists |
| "agent detected" | Reports process name substring matches, not agent identity |
| "AGI", "alignment", "AI safety" | No ML, no model access, no governance mechanism |
| "intent", "motive", "suspicious", "anomalous" | No semantic analysis capability |
| "prevent", "block", "protect" | Read-only observability only — no enforcement |
| "real-time" | Polling intervals are 2-5 seconds minimum |

---

## Approved Output Language

| Phrase | When to Use |
|---|---|
| "matched pattern [X]" | A regex or substring pattern hit (process name, network address, file content) |
| "hash mismatch" | SHA-256 differs from baseline for a tracked file |
| "platform [name] process running" | Process command matched a `CODING_PLATFORMS` entry |
| "network connection to [address]" | `lsof` returned a connection to a monitored endpoint |
| "file change detected: [path]" | Baseline hash differs, or new file appeared in monitored directory |

---

## Pre-Flight Check

Before accepting any prompt or writing any code, ask:

> **"Does this prompt require forbidden terminology to describe the work?"**

- If YES → reject the prompt. Redirect to an approved framing before proceeding.
- If NO → proceed with approved language only.

---

## Implementation Constraints

1. **All detection is deterministic.** Every result is a direct function of (input + pattern list). No probabilistic inference, scoring, or weighting outside the existing Zaelith module.
2. **All collection is passive.** OS-available reads only (`ps`, `lsof`, filesystem `stat`). No kernel modules, system hooks, instrumentation.
3. **All telemetry is local.** Zero data leaves the machine without explicit user action.
4. **All patterns remain hardcoded until replaced by user-configurable files.** No data-driven pattern loading without explicit scope expansion.
5. **Every observation must be timestamped** (ISO 8601) and cite its OS source command.

---

## Document Hierarchy

| Document | Purpose | Authority |
|---|---|---|
| `docs/canon/CLEANHOUSE_RUBRIC.md` | Product boundaries, terminology, doctrine | Canonical — all other docs derive from it |
| `docs/evidence/CLEANHOUSE_EVIDENCE_FIRST_THESIS.md` | Grounded thesis with code citations | Educational — explains what and why |
| `docs/canon/CLEANHOUSE_EVIDENCE_AUDIT.md` | Repository vs. standards cross-reference | Diagnostic — identifies gaps |
| `docs/canon/SCOPE_GATE.md` (this file) | Gate text for prompt acceptance | Operational — enforces boundaries per-prompt |

---

## Amendment Rules

This gate may be amended only when:
1. New code evidence demonstrates a capability not listed here, AND
2. The amendment adds precise description of what the code actually does (not what it could mean), AND
3. No forbidden terminology is introduced.

*Initial version: 2026-05-22*
