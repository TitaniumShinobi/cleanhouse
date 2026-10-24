# CleanHouse Network Core Runtime

This boundary establishes the server-owned Network collector lifecycle. It is
not the complete Network product and does not claim operational packet capture.

## Implemented contract

- One collector supervisor owns at most one capture process.
- A canonical envelope is persisted to CleanHouse's local event spine before
  it is published to subscribers.
- Replay and every subscriber queue are bounded. Overflow, cursor mismatch,
  replay eviction, persistence failure, and capture interruption produce
  explicit `collector.gap` receipts rather than silently implying continuity.
- Fan-out preserves collector sequence order. Collection and persistence do
  not depend on a subscriber being connected.
- Refresh synchronizes the health and persistence boundary without restarting
  the capture process.
- The watchdog retries failed capture with exponential backoff capped at 30
  seconds. Shutdown interrupts that wait, terminates capture, joins the
  watchdog, and closes subscribers.
- Network history uses the existing local append-only event spine and has an
  independent startup and shutdown seam.

## Startup and readiness

Backend warmup records independent results for the filesystem watcher, local
Network history, Network collector, and heartbeat. A failure in one block does
not prevent the later blocks from reporting their own state.

The stable failure codes are:

- `filesystem_watcher_unavailable`
- `filesystem_watcher_start_failed`
- `network_history_unavailable`
- `network_history_start_failed`
- `network_capture_engine_unavailable`
- `network_collector_start_timeout`
- `network_collector_unavailable`
- `network_collector_start_failed`

Any of these warmup failures makes the canonical runtime state degraded, so
the existing fail-closed operator-readiness contract cannot report ready.

## Capture engine absent

Capture-engine packaging is a separate reviewed boundary. In this boundary no
system-installed executable and no unreviewed bundle is accepted. The default
collector therefore reports `degraded` with the exact reason
`capture_engine_unavailable`, emits continuity receipts only, creates no packet
events, and retries using bounded watchdog backoff. This is an expected honest
installation state, not an operational capture claim or a crash loop.

## Assessment boundary

Collector envelopes and gap receipts are evidence inputs, not security
categories. The shared `cleanhouse.security_assessment.v1` projection may
derive a versioned Strength, Vulnerability, or Threat only through a reviewed
backend rule with bounded evidence references. Capture warming, degradation,
retry, permission failure, engine unavailability, and continuity gaps remain
operational or evidence-coverage states; they never fabricate an assessment.

## Explicitly deferred

The following are not part of Network Core: capture-engine binaries or
packaging, frontend views, Apple Intelligence or Insight, evidence-action
orchestration, VVAULT synchronization, allowed-threat mutation, whole-system
scans, broad application inventory, Zaelith, Files/Wazuh behavior, additional
page routes, and `Powered by Wireshark` or equivalent operational branding.
