# CleanHouse Network Acceptance Ledger

**ID:** `network-acceptance-2026-10-15-reconciliation-01`  
**Status:** MILESTONE-2 PASS — NOT PROMOTED

| Gate | Status | Pass condition |
|---|---|---|
| Table evidence | PASS | Normalized Wireshark evidence renders as deduplicated connection identities; acceptance sample was 120 rows / 120 unique identities |
| Incremental Table flow | PASS | Live fanout is bounded and does not wait for retained projection queries |
| Findings retention | PASS | Independent bounded priority queue remains distinct from Table and exposes its coverage limit |
| Findings interactions | PASS | Authenticated view rendered priority findings and selection/ctrl remained evidence-bound |
| Trend | PASS | Real observed connection samples populate canonical ranges with honest empty buckets and coverage |
| Distribution | PASS | Packet-backed shares render separately from the open-GUI inventory |
| Timeline | PASS | Notable events and continuity gaps render; routine packets stay excluded |
| Refresh / continuity | PASS | Refresh preserved the 120-row/120-identity Table sample; replay and stale-cursor gaps are focused-test covered |
| Permanent attribution | PASS | `Powered by Wireshark — verified` remained visible from provider evidence and was not downgraded by projection payloads |
| Runtime ownership | PASS | One LaunchAgent supervisor and one owned listener; canonical operator readiness satisfied 11/11 checks |
| Large-DB behavior | PASS WITH BOUNDS | Interactive paths use UTC time bounds and per-view history caps; no unbounded synchronous event scan is used |
| Responsive / accessibility | PASS | Desktop and 390x844 mobile had no horizontal overflow; navigation and status remained named; visible keyboard focus retained |
| Console / requests | PASS | No unexpected console warnings or errors; focused live endpoints returned successful evidence-backed states |
| Source/staged parity | PASS | The five changed runtime source files matched the staged runtime at acceptance |

## 2026-10-15 recovery receipt

- Persistence happens before fanout: the shared SQLite OVVAULTS outbox accepts the normalized record before the bounded event-spine queue and subscribers. Cursor/gap evidence remains explicit when a bounded queue cannot accept a record.
- The collector coalesces matching connection observations inside a one-second window while preserving raw packet counts and provenance. A dropped duplicate does not advance the retained event timestamp.
- Short windows use the bounded boot-local normalized stream. Retained projections query `[start,end)` UTC ranges and cap every view's history input; the largest cap is 1,500 rows.
- Findings uses an independent bounded retained queue with `coverage_state=bounded_retained_queue`. Timeline excludes routine packets. Distribution labels packet evidence and open GUI inventory as different sources.
- Successful ordinary snapshot/provider evidence clears stale capture-only reasons; unrelated live projection payloads cannot downgrade verified provider attribution.
- The event writer can recover to a healthy live state after an earlier failure while retaining cumulative failure/drop/retry counters as historical evidence.
- Authenticated browser acceptance passed Table, Findings, Trend, Distribution, and Timeline; refresh, selection/ctrl, long-window reads, desktop and mobile rendering; and console review.
- Current preservation truth is intentionally not promoted to healthy: OVVAULTS authentication and receipts succeed, the worker is live, and the material historical backlog is still reported as degraded.
- The shared OVVAULTS reader no longer holds the process-state lock during WAL backlog/status scans, and retained Network reads use the existing source/type/id indexes before applying the `[start,end)` UTC window in memory. Post-repair observation advanced capture and persistence together with an empty local persistence queue and sub-second ingestion latency while the historical remote backlog continued draining independently.

## Proof retained by this pass

- Protected-surface verifier: 11/11 before and after.
- Focused capture, core, API, persistence, projection, auth, runtime, and Node resilience suites.
- Authenticated five-view browser proof plus refresh, selection/ctrl, long-window, desktop/mobile, and console review.
- Canonical health/readiness/status probes, source/staged hashes, and bounded PID/listener observation.
- Clean diff checks with the original index left byte-identical and no staged paths.

Static tests did not upgrade runtime behavior; the PASS is backed by the authenticated live runtime. This ledger does not authorize promotion, packaging, deployment, cleanup, or a claim that the OVVAULTS backlog is cleared.
