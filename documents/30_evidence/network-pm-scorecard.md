# CleanHouse Network PM Scorecard

**PM:** CodeGPT / Zenith coordination surface  
**Opened:** 2026-10-15T18:10:26-0400  
**Milestone:** Restore and validate authentic visual data across all five Network views  
**Release state:** VISUAL RECOVERY ACCEPTED — PERFORMANCE/PRESERVATION FOLLOW-UP OPEN

**Runtime-wide follow-up:** START owns the newly observed cross-page data-hydration regression. Network remains a protected recovered baseline.

## Dispatch register

| Receipt | Thread ID | Exact title | Role | Assignment | State |
|---|---|---|---|---|---|
| NET-IMPL-001 | `01a015d3-6de3-7131-a257-d2774b95c8c3` | `Read AGENTS instructions` | Implementation | Finish Network Table, Findings, Trend, Distribution, and Timeline from canon and runtime evidence. Preserve protected behavior and produce authenticated browser proof. | COMPLETE — owner observed |
| NET-QC-001 | `01a1373f-9c14-7972-9920-7e6ffbc1e65c` | `Audit CleanHouse runtime commit` | Independent QC | Validate every Network completion gate without implementing fixes. Reject unsupported completion claims. | FAILED — dependency closure |
| NET-OPS-001 | `01a13ad4-c766-7051-8a27-c2cd61d4c010` | `Morning App Readiness` | Runtime operations | Verify single-owner runtime stability, collectors, projections, staging parity, logs, database conditions, and resource limits. | DISPATCHED |
| NET-OPS-002 | `01a13617-d195-7cc0-bb6f-b0f6874b8c57` | `Use start/ to diagnose and repair cleanhouse/.` | Runtime operations fallback | Run the same bounded read-only runtime verification because NET-OPS-001 stopped at an approval boundary. | COMPLETE — performance failed |

The exact assignment prompts are preserved in their destination threads. Thread IDs are the receipt keys for every follow-up, result, and correction.

## Milestone gates

| Gate | Required evidence | State |
|---|---|---|
| Protected surfaces | No regression to authentication, navigation, `ctrl`, Files, Applications, or Findings | OPEN |
| Table authenticity | Visible rows trace to authentic Wireshark-derived capture evidence | PASS — owner observed live rows |
| Table latency | First authentic row renders within one second under normal local load | OPEN |
| Findings | Retained queue, priority, expansion, scrolling, and evidence behavior preserved | PASS — 12 retained findings owner observed |
| Trend | Every canonical window renders real samples, explicit gaps, and honest empty buckets | PASS — live five-second graph owner observed |
| Distribution | Packet-observed traffic remains distinct from open-application inventory | PASS — packet chart and zero-evidence app inventory owner observed separately |
| Timeline | Notable evidence events, continuity boundaries, and gaps render without routine packet noise | PASS — live event timeline owner observed |
| Attribution | Permanent established `Powered by Wireshark` visual baseline remains present | PASS — visible on every supplied view |
| Runtime ownership | One healthy runtime/supervisor ownership chain with no restart loop | PASS — bounded operations window |
| Resource ceiling | Validation remains below the 10 GB RAM ceiling | PASS — approximately 221.5 MiB combined supervisor/backend/tshark RSS |
| Large-database behavior | Live capture and navigation remain responsive while historical projections are bounded | OPEN |
| Source/staged parity | Relevant source and staged assets match by hash | PASS — five checked assets |
| Browser acceptance | Authenticated proof covers all five views, refresh, reload, restart, selection, `ctrl`, scrolling, and navigation | PASS — implementation receipt plus owner screenshots |

## PM operating rules

1. The PM assigns work, tracks receipts, routes failed gates, and maintains continuity. The PM does not implement product code.
2. No implementation claim becomes complete until independent QC and runtime evidence agree.
3. A stopped thread, static test pass, or agent summary is not completion.
4. Routine implementation and repair continue without asking Devon for ceremonial approval.
5. Escalation is reserved for destructive, irreversible, credential, legal, security-policy, or product-ownership decisions.
6. Every prompt, follow-up, blocker, verdict, and supersession is appended to this scorecard.

## Active control loop

1. Monitor all three dispatched threads.
2. Record raw receipts and exact failed gates here.
3. Return each failed gate to the implementation thread with QC or runtime evidence.
4. Repeat until every gate is independently verified.
5. Close the milestone only after QC and runtime operations both issue evidence-backed acceptance.

## Follow-up register

| Time | Receipt | Direction | Result |
|---|---|---|---|
| 2026-10-15T18:12:00-0400 | NET-OPS-001-F1 | Continue all available read-only checks; treat a permission-blocked probe as one unverified datum, not a reason to stop the operations pass. | DELIVERED |
| 2026-10-15T18:16:00-0400 | NET-OPS-002 | Reassigned the operations gate to an existing START-diagnostic thread after NET-OPS-001 remained stopped at an approval boundary. | DELIVERED |
| 2026-10-15T18:20:00-0400 | NET-QC-001-R1 | QC found the proposed historical four-path boundary was not dependency-closed: unconditional imports depended on untracked Apple Intelligence/evidence-context files, and Network VVAULT preservation depended on dirty `corefiles/config.py` helpers. The current repository had no staged candidate. Findings were routed to implementation without authorizing reset or worktree destruction. | FAIL ROUTED |
| 2026-10-15T18:20:00-0400 | NET-OPS-002-R1 | Singular runtime, listener, collector, RAM, source/stage parity, and protected surfaces passed. Projection performance and VVAULT preservation backlog failed. Exact measurements were routed to implementation. | PARTIAL PASS ROUTED |
| 2026-10-15T20:46:00-0400 | NET-IMPL-001-R1 | Implementation reported 288 focused checks, protected-surface verification, source/runtime provenance parity, and authenticated desktop/mobile acceptance across all five views. | COMPLETE |
| 2026-10-15T20:46:00-0400 | OWNER-NETWORK-RECOVERY-001 | Devon supplied authenticated screenshots showing live Table rows, 12 Findings, populated Trend, packet-backed Distribution separated from application inventory, populated Timeline, and permanent `Powered by Wireshark` attribution. | VISUAL RECOVERY ACCEPTED |
| 2026-10-15T21:12:00-0400 | OWNER-SCOPE-CORRECTION-001 | Devon corrected the apparent Files regression: data-loading latency affects pages across CleanHouse and belongs to `start/`, not Files or Network feature scope. | CANONICAL SCOPE |
| 2026-10-15T21:13:00-0400 | START-HYDRATION-001 | Existing START diagnostic thread `01a13617-d195-7cc0-bb6f-b0f6874b8c57` was assigned runtime-wide hydration diagnosis and bounded repair with per-page before/after timing proof. | DISPATCHED |
| 2026-10-15T21:15:00-0400 | START-HYDRATION-001-D1 | START isolated the root defect: `frontend/js/investigations.js` starts a Network snapshot every second even when the previous request remains in flight. Browser aborts leave server-side `lsof`/SQLite work executing, producing concurrent work, approximately 81% CPU, readiness stalls, and cross-page hydration delays. | ROOT CAUSE VERIFIED |
| 2026-10-15T21:16:00-0400 | START-HYDRATION-001-F1 | Removed the artificial permitted-file stop. START was directed to implement bounded single-flight/coalesced Network polling in `frontend/js/investigations.js`, add minimum focused tests, restage canonically, and produce cross-page before/after timing proof. | REPAIR AUTHORIZED AND DISPATCHED |
| 2026-10-15T21:36:00-0400 | START-HYDRATION-001-R1 | START implemented and deployed the two-file causal repair: single-flight snapshots, refresh coalescing, lifecycle teardown, stale-work retirement, and bounded 1–30 second automatic retry backoff; manual refresh remains immediate. | IMPLEMENTED |
| 2026-10-15T21:36:00-0400 | START-HYDRATION-001-V1 | Reported evidence: lifecycle `18/18`, Network ctrl/table `27/27`, protected surfaces `11/11`, canonical restage success, source/stage JS hash `d9e2e553…0411435`, one listener/supervisor, health `200`, readiness true, zero automatic snapshots over 35 seconds, CPU reduced from `89.1%` to `2.5–4.9%`, persistence queue zero, authenticated Network and Files hydration successful, `/api/auth/me` `200`. | IMPLEMENTATION PROOF RECEIVED |
| 2026-10-15T21:37:00-0400 | START-HYDRATION-QC-001 | Sent the exact two-file repair and acceptance claims to independent QC thread `01a1373f-9c14-7972-9920-7e6ffbc1e65c`. | QC DISPATCHED |
| 2026-10-15T23:35:00-0400 | OWNER-CONNECTIONS-LAYOUT-001 | Devon established the next Network UI contract: rename `Table` to `Connections`; center a fluid portrait/landscape evidence viewport with explicit minimum/maximum bounds and left-aligned content; keep permanent `Powered by Wireshark` attribution visible at the application bottom. | CANONICAL UI SCOPE |
| 2026-10-15T23:37:00-0400 | CONNECTIONS-LAYOUT-001 | Existing Network implementation thread `01a015d3-6de3-7131-a257-d2774b95c8c3` was assigned the bounded responsive Connections layout, internal scrolling, permanent footer, resize acceptance, and preservation gates. | DISPATCHED |

## Connections layout acceptance gates

| Gate | Requirement | State |
|---|---|---|
| Label | Visible primary tab name is `Connections` | OPEN |
| Width | Centered evidence viewport expands and contracts within explicit minimum and maximum bounds | OPEN |
| Height | Viewport consumes available application height and uses internal row scrolling | OPEN |
| Orientation | Portrait, standard landscape, wide landscape, and constrained desktop layouts remain usable | OPEN |
| Alignment | Headers and row text remain left-aligned | OPEN |
| Attribution | `Powered by Wireshark` remains visible at the application bottom on every Network tab | OPEN |
| Stability | Window resizing does not reset evidence or cause unnecessary refetching | OPEN |
| Preservation | Network semantics, single-flight polling, Findings, other projections, ctrl, navigation, and auth remain unchanged | OPEN |
| Canonical documentation | Subordinate Network contract exactly mirrors implemented dimensions, responsive rules, behavior, boundaries, state transitions, commands, validation, and known limitations; `CLEANHOUSE.md` remains untouched | OPEN |

## Permanent documentation gate

1. Implementation and canonical subordinate documentation change in the same pass.
2. Documentation specifies the resulting system; it is not a retrospective report or completion summary.
3. The complete implemented contract is recorded: architecture, behavior, boundaries, commands, states and transitions, exact values and dimensions, validation criteria, and known limitations.
4. Existing explicit master-receipt canon is referenced. Missing implementation detail is resolved in the appropriate subordinate canonical contract.
5. `CLEANHOUSE.md` is owner-controlled and may not be edited unless Devon explicitly authorizes that file.
6. Documentation drift blocks completion even when code and tests pass.

| Time | Receipt | Direction | Result |
|---|---|---|---|
| 2026-10-15T23:40:00-0400 | OWNER-DOCUMENTATION-GATE-001 | Devon made concurrent canonical subordinate documentation mandatory for every implementation and prohibited direct `CLEANHOUSE.md` edits without explicit authorization. Reports do not satisfy the gate. | CANONICAL PROCESS RULE |
| 2026-10-15T23:41:00-0400 | CONNECTIONS-LAYOUT-DOC-001 | Active implementation thread was directed to document exact dimensions and the complete resulting Connections specification, and to encode the permanent rule in `AGENTS.md`. | DELIVERED |
| 2026-10-16T00:30:00-0400 | OWNER-CONNECTIONS-LAYOUT-CORRECTION-001 | Devon observed the butterfly effect from ambiguous “centered” wording. Canon now requires horizontal centering only and fixes the Connections viewport directly beneath the tab/Refresh row. Vertical centering is superseded. | CANONICAL CORRECTION |
| 2026-10-16T00:32:00-0400 | CONNECTIONS-LAYOUT-002 | Implementation was directed to remove vertical-centering drift, preserve bottom attribution, and update the subordinate contract with exact top anchoring and gap geometry. Audit was notified not to accept the superseded layout. | IMPLEMENTATION AND QC DISPATCHED |
| 2026-10-16T00:40:00-0400 | CONNECTIONS-LAYOUT-002-R1 | Vertical drift repair completed: `align-self:start`, legacy 18px toolbar margin removed, exact 8px tab-to-Connections gap, horizontal-only centering, surplus height below the viewport, permanent 44px attribution row preserved. | IMPLEMENTED |
| 2026-10-16T00:40:00-0400 | CONNECTIONS-LAYOUT-002-V1 | Four-size geometry measured without page overflow; static tests `33/33`, Network Node tests `45/45`, protected surfaces `11/11`, zero browser warnings/errors, and source/runtime HTML+CSS parity reported. Canonical authenticated resize proof remains open because the available canonical browser session is at `/login`. | IMPLEMENTATION PROOF RECEIVED |
| 2026-10-16T00:41:00-0400 | CONNECTIONS-LAYOUT-002-QC | Corrected implementation and measurements routed to independent Audit. | QC REDISPATCHED |
| 2026-10-16T00:46:00-0400 | OWNER-CONNECTIONS-LAYOUT-CORRECTION-002 | Devon observed the second contract gap: Connections is top-anchored but the 620px cap prevents it from expanding through the available window height. | CANONICAL CORRECTION |
| 2026-10-16T00:48:00-0400 | CONNECTIONS-LAYOUT-003 | Implementation was directed to fill the complete results row from the 8px tab gap to immediately above the permanent 44px attribution row, remove the 620px tall-window cap, retain internal scrolling, and update exact subordinate documentation. Audit was told not to accept the capped layout. | IMPLEMENTATION AND QC DISPATCHED |
| 2026-10-16T00:51:00-0400 | CONNECTIONS-LAYOUT-003-QC0 | Audit correctly failed the still-capped pre-correction source and preserved the exact remediation gate. | BASELINE FAIL |
| 2026-10-16T00:53:00-0400 | CONNECTIONS-LAYOUT-003-R1 | Fixed-cap removal completed. Connections now fills 100% of the available results row with 240px minimum, exact 8px top/bottom gaps, internal row/column scrolling, and permanent 44px attribution. Subordinate contract updated; CLEANHOUSE.md untouched. | IMPLEMENTED |
| 2026-10-16T00:53:00-0400 | CONNECTIONS-LAYOUT-003-V1 | Reported geometry: 593px at 768x1024, 311px at 1024x640, 558px at 1440x900, and 764.15625px at 1728x1117. Tests `33/33`, Network `45/45`, protected surfaces `11/11`, zero browser errors, and CSS source/runtime parity reported. | IMPLEMENTATION PROOF RECEIVED |
| 2026-10-16T00:54:00-0400 | CONNECTIONS-LAYOUT-003-QC1 | Completed correction and exact geometry routed back to Audit for final independent verdict. | QC REDISPATCHED |
| 2026-10-16T00:55:00-0400 | CONNECTIONS-LAYOUT-003-QC2 | Audit independently verified source, tests, subordinate documentation, deployed HTML/CSS parity, absence of an equivalent tall-window cap, exact 8px boundaries, 100% results-row fill, internal scrolling, 44px provider row, singular listener, and untouched CLEANHOUSE.md. | PASS WITH FOLLOW-UP |

## Latest operations receipt

- Runtime: supervisor PID `40720`, backend PID `40773`, TShark PID `40881`, listener `127.0.0.1:3333`; stable over the bounded observation window.
- Capture: Wireshark/TShark `4.6.6`, sequence advancing, no collector restart or persistence failure.
- Databases: canonical events database approximately 40 GiB; staged runtime database approximately 32 GiB.
- Projection timings: Findings `4.47s` cold and `12.26s` later; Trend `0.77s` then `3.37s`; Distribution `3.26s` then `4.34s`; Timeline `2.54s` then `4.45s`.
- Table sample: `0.93s`, but returned zero events while the capture sequence advanced; the visible first-authentic-row gate remains open.
- Preservation: VVAULT queue approximately `35,975` and rising; preservation is degraded even though capture is healthy.
- Source/live-stage hashes matched for the five checked Network/runtime assets. Protected surfaces passed `11/11`.
### CONNECTIONS-LAYOUT-004 — owner polish correction (2026-10-16)

- Owner correction: preserve the established 8px gap below the Network tab row, but finish the Connections window 10px higher than LAYOUT-003.
- Required result: 18px total clearance beneath the Connections window, leaving a clean visible gap from the `ctrl` control while preserving the permanent 44px `Powered by Wireshark` footer row.
- Preserve: horizontal centering, responsive portrait/landscape growth, left-aligned content, internal table scrolling, live evidence behavior, and all protected Network surfaces.
- Documentation gate: record exact geometry and responsive behavior in the subordinate Network implementation contract; do not modify `CLEANHOUSE.md`.
- Dispatched to implementation thread `01a015d3-6de3-7131-a257-d2774b95c8c3` and audit thread `01a1373f-9c14-7972-9920-7e6ffbc1e65c`.
- Implementation: PASS. The table height is `calc(100% - 10px)`, preserving the 8px top gap and producing 18px bottom clearance. Exact rendered heights: 583px at 768×1024; 301px at 1024×640; 548px at 1440×900; 754.15625px at 1728×1117. Ctrl clearance is 14px in portrait and 6px at the three landscape sizes; overlap is false.
- Verification: Python 33/33, Node 45/45, protected surfaces 11/11, JavaScript syntax, scoped diff check, no browser console warnings/errors, and source/runtime CSS parity at SHA-256 `0cb8964875e2804ff0e6e54d56004787a45eafc1db03600fc065ebe16766b20d`.
- Audit verdict: PASS — CONNECTIONS-LAYOUT-004. Permanent 44px Wireshark footer, table-local scrolling, no page overflow, and `CLEANHOUSE.md` preservation verified.
- Runtime follow-up: canonical restage exposed a pre-existing supervisor replacement race that exhausted the restart budget. START recovered the canonical LaunchAgent without code changes: supervisor PID 18570, backend/listener PID 18613, exactly one listener on `127.0.0.1:3333`, `/health` 200, canonical readiness `ready: true`, authenticated Safari session preserved, and restart count stable during observation.

