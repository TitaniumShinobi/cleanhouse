# CLEANHOUSE PRODUCT REALITY REPORT

Date: 2026-05-30  
Method: Operator-perspective UI walkthrough + route availability probe + screenshot evidence

## 1) Walkthrough Scope (Visible Screens)

Captured operator-visible screens:

1. Login screen (`/login`)  
   Evidence: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/screenshots/login.png`
2. Signup screen (`/signup`)  
   Evidence: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/screenshots/signup.png`
3. Dashboard screen (`/dashboard`)  
   Evidence: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/screenshots/dashboard.png`
4. Incident Receipt screen (`/incident-receipt`)  
   Evidence: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/screenshots/incident-receipt.png`

Supporting probe artifacts:

- Route probe: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/route_probe.txt`
- Fixture API run log: `/Users/devonwoodson/Documents/GitHub/cleanhouse/docs/evidence/product_reality/walkthrough_fixture_api.jsonl`

## 2) What Is Product-Accessible Through UI

Directly visible and operator-addressable in product UI:

- Auth surface:
  - Login form + OAuth entry points (`/login`)
  - Signup form + terms gate (`/signup`)
- Dashboard shell and control affordances:
  - Session controls (Start/Stop/Finalize)
  - Objective declaration controls
  - Report and Settings panels
  - Operational Presence, Active Context, Continuity, Queue/Approval, Receipt Replay, Notification panels
- Incident receipt shell:
  - Incident load/create controls
  - Action path framing (Quarantine/Purge/Bless)

## 3) Product Reality Failures (Operator Blocking)

Observed in runtime probe (same run):

- HTML pages return `200` and render.
- Core operator API surfaces timeout/unavailable:
  - `/cleanhouse/status` timeout (no response body within probe timeout window)
  - `/cleanhouse/runtime` timeout
  - `/cleanhouse/workstation?...` timeout
  - `/cleanhouse/receipts?...` timeout
  - `/cleanhouse/incident-receipt` timeout
- Objective start route returned `ok` once, while prompt/session start calls timed out in the same lane.

Operator impact:

- The UI exists, but core operator workflows are degraded because the dashboard depends on API surfaces that are not consistently reachable.
- Current state is infrastructure-forward with partial product accessibility, not full operator-ready product behavior.

## 4) Implemented Capability Classification

### Product (UI-Accessible)

- Auth screens and form/OAuth entry points.
- Dashboard shell with operator control affordances.
- Incident receipt shell and decision-path UI.

### Infrastructure (Implemented but not operator-reliable in this run)

- Runtime/collector/status envelopes.
- Workstation aggregation pipeline (timeline/signals/alerts/receipts/approvals/replays).
- Receipt/replay/bundle integrity spine.
- Actor/channel/trust attribution propagation.
- Scope enforcement/deviation evidence chain.

### Missing (for product reality)

- Deterministic, low-latency operator API responsiveness for `/cleanhouse/status`, `/cleanhouse/runtime`, and `/cleanhouse/workstation`.
- A fully reliable end-to-end operator journey where dashboard controls consistently act on live state.
- UI exposure of scope-enforcement/deviation outcomes as explicit first-class operator cards (not just backend records).

## 5) Product vs Infrastructure Determination

Current determination: **Product-degraded / Infrastructure-heavy**.

Reason:

- Operator-visible UI surfaces exist and were captured.
- Core operator data/control APIs are not consistently responsive in this walkthrough, preventing dependable product operation.

## 6) Remediation Priority Driven by This Walkthrough

1. Restore deterministic response behavior for `status/runtime/workstation` operator APIs (highest product blocker).
2. Ensure dashboard can complete start/declare/monitor/receipt loop without timeout-driven degradation.
3. Promote scope enforcement deviation records into explicit operator UI panels with actionable mediation context.
