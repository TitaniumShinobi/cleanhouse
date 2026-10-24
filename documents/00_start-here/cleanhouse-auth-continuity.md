# CleanHouse authentication continuity checkpoint

## Canonical boundaries

- **Start** owns MDBO capability generation, startup, and runtime health.
- **auth** owns authentication discovery, assessment, native creation, alignment, verification, repair, and explicit migration.
- **drbt** owns distribution, stores, hosting/domain integration, and SEO.
- **AUTO** is a separate conversational/plugin wizard and is not required for ordinary CleanHouse development.
- MCP is not part of the CleanHouse signup/signin critical path.

The public product is lowercase `auth`. It is transient and target-native: it must leave no `.auth-runtime`, `.auth-kit`, adapter, daemon, copied package, workflow, or continuing control plane in CleanHouse.

## CleanHouse acceptance contract

CleanHouse must prove signup, signin, Google OAuth, HttpOnly server sessions, complete logout, single-use account recovery, stable validation/errors, frontend/backend agreement, and Start-owned readiness. Provider credentials and callback registration remain owner/provider actions. No mock-only result is a production-readiness claim.

OAuth transactions stored in the signed browser session are fresh, well formed,
and bounded to four pending states. The callback consumes its state once and
stores only the durable login-report identifier—not the report payload—in the
session cookie. This keeps the callback cookie below browser limits so a valid
provider callback cannot be discarded and misreported as a missing OAuth user.

Current implementation authority is the Python/Flask/SQLite alignment profile in `auth`; product-specific UI, persistence, and configuration remain owned by CleanHouse.

Start resolves the supervised interpreter by preferring an explicit
`CLEANHOUSE_PYTHON`, then the managed runtime at
`~/.cleanhouse/runtime/python/bin/python3`, before active or repository-local
environments. Readiness is not established until the supervised listener answers
the canonical status contract.


## Active-source completion — 2026-10-20

This section supersedes the older implementation description, not its historical
acceptance receipts. Source completion is not runtime activation. No runtime
restart, provider provisioning, browser session, or release approval is included.

The product-owned SQLite AuthStore supplies opaque digest-only device sessions,
rotation, expiry, revocation, purpose-bound single-use magic challenges, provider
subject bindings, append-only document-version receipts, and personal API tokens.
Existing signed browser identities are validated against the user service before
a device session is issued; user records and other browser sessions are preserved.
New authentication still requires current consent before protected product access.
The signed Flask cookie retains only short-lived OAuth/CSRF state. Four pending
OAuth transactions retain their intent, owner linkage and consent and are consumed
once. Denial callbacks also validate/consume state. Unknown OAuth login identities
receive an explicit signup/link disposition; GitHub requires verified primary email
and stable provider subject. Provider configuration only exposes availability.

Magic-email GET displays confirmation; only the protected POST consumes the
challenge. Signin/signup intent, expiry/replay, failed delivery revocation and
rate limits are enforced. Actual delivery requires configured Resend/SMTP.
Session logout revokes only the requesting device credential and clears its
cookie; shared saved files and other clients remain intact. The UI obtains CSRF
and clears identity only after successful logout; failures remain visible/retryable.

Settings supplies Providers/API/Security/Account controls through the existing
product UI. API tokens are shown once, stored as digests, revocable/expiring, and
cannot perform sensitive browser-auth administration. Sensitive changes require
recent session-bound reauthentication. Other Settings tabs report unavailability
explicitly. Existing Help and Advanced navigation remain present.

Normal local/CI command: `python -B scripts/build-check.py`. On this Mac select
`~/.cleanhouse/runtime/python/bin/python3`; no automatic iCloud interpreter.
The gate runs isolated auth/logout and store/provider/magic/Settings tests,
protected surfaces, dependency checks, and gate controls with a temporary HOME.
The generated wrapper emits an optional M4 witness after success, strips witness
authority from children, and needs no running auth wizard. External M4 receipts
remain outside the product. Full-server and live-provider acceptance are separate
from this source gate; no remote protection or baseline is advanced.

## Authentication-only verification receipt — 2026-10-20

Run 2 treated the Settings modal as stable and changed no authentication
product behavior. It added regression coverage proving that password signin
first fetches `/api/auth/csrf`, submits the returned value in
`X-CSRF-Token`, and that missing or forged values fail with HTTP 403 and
`CSRF_FAILED`.

The source gate passed 85 tests. A disposable full server on loopback proved
password login, protected-route return, persistent reload, authenticated
Settings account state, independent logout, and post-logout protection in a
hidden browser with no console warnings or errors. The disposable runtime used
an isolated HOME, database, configuration, port, and synthetic account; it did
not modify the staged runtime, the listener on port 3333, or any existing user
or browser session. Direct-server `/health` was live; Start-owned readiness
correctly remained false because the disposable server had no supervisor
heartbeat.

The external AUTH lane was extracted from and bound to commit
`56c701ed3fc5af3c5215d11a603bb4dc76767645` and returned VERIFIED across build,
regression, behavioral, security, recovery, integration, and acceptance lanes.
Tampered input evidence, an invalid revision binding, and a missing verification
specification are rejection cases. A disposable removal of the UI CSRF header
made the ordinary product gate fail; restoring it made the gate pass again,
without rerunning AUTH for the negative regression proof.

This is source and isolated-runtime proof only. Controlled live activation is
not authorized by this receipt. Real email delivery and interactive GitHub
provider acceptance remain provider-controlled work, and the staged/canonical
runtime must be rebuilt and Start-supervised before any live claim.
