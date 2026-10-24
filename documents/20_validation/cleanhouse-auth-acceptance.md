# CleanHouse authentication acceptance — 2026-10-13

## Verdict

The product-native CleanHouse authentication implementation is aligned to the
lowercase `auth` Python/Flask/SQLite profile and passes the focused backend and
browser acceptance exercised in this campaign. The implementation is not a
claim that live Google OAuth or live recovery-email delivery has been accepted;
those two provider interactions still require their configured credentials and
registered endpoints.

The `auth` wizard is transient. CleanHouse contains no `.auth-kit`,
`.auth-runtime`, auth daemon, adapter, copied auth package, or continuing auth
control plane.

## Authority routing

| Finding or behavior | Canonical authority |
| --- | --- |
| Python/Flask/SQLite discovery, assessment, and reusable security profile | `auth` |
| Signup, signin, session UI, errors, and recovery screens | CleanHouse |
| Server sessions, OAuth state/PKCE seams, logout, and recovery persistence | `auth` contract; CleanHouse-native implementation |
| Google client credentials and registered callback | Google/provider and owner-controlled configuration |
| Resend/SMTP credentials, sender, and domain | Email provider and owner-controlled configuration |
| Port 3333 interpreter selection, supervision, health, and readiness | Start |
| Distribution, DNS, deployment, and SEO | drbt; excluded |
| AUTO and MCP | Excluded from the authentication critical path |

## Implemented contract

- Browser identity is held by a server-owned HttpOnly Flask session; browser
  authentication does not depend on a JWT in `localStorage`.
- Bearer verification remains available only for explicit API/native-client
  use.
- OAuth state is session-bound, expiring, and consumed once. PKCE material is
  bound to the same server-side record.
- Logout clears the current browser Flask session only. It does not delete shared
  saved desktop files or invalidate another browser session. The UI clears local
  identity and redirects only after an HTTP success with JSON `success: true`;
  failure retains identity and enables a visible retry.
- Recovery tokens are random, SHA-256 hashed at rest, expiring, and single-use.
  Issuing a new token invalidates the prior unused token for that user.
- Recovery requests return an enumeration-resistant public response. Resend is
  primary and SMTP is the documented fallback; raw recovery tokens are neither
  logged nor persisted.
- Public provider configuration reports availability only; the obsolete client
  identifier preview endpoint was removed.
- Public errors are stable and non-sensitive while detailed failures remain in
  protected logs.
- Existing user records are preserved; no automatic identity migration or
  deletion is performed.

## Evidence

### Focused automated verification

- CleanHouse authentication, recovery, configuration, interpreter, and launch
  contract suites: **43/43 passed**.
- `auth` native wizard suite: **12/12 passed**.
- Python syntax compilation for the changed backend modules passed.
- A clean `git archive` of `HEAD` with only the bounded authentication and
  Start-runtime files overlaid passed the same **43/43** focused tests and
  syntax checks without sibling-repository dependencies.
- Scoped `git diff --check` passed.
- The documents-tree verifier passed after regenerating the file index.
- `auth native assess` classified CleanHouse as `COMPATIBLE` on the
  Python/Flask/SQLite stack, reported all eight profile probes, found no
  persistent auth artifact, and routed only CleanHouse-owned seams as
  `AGENT_INTEGRATION_REQUIRED`.

### Browser acceptance

An isolated CleanHouse runtime and temporary home/database proved:

- signin reaches the authenticated product route;
- the `cleanhouse_session` cookie is HttpOnly and SameSite=Lax;
- no authentication token or user record is stored in browser local storage;
- the session survives navigation and refresh;
- logout removes the session and a protected-route attempt returns to signin;
- an unknown recovery address receives the same success response as a known
  address;
- mismatched signup passwords produce a visible deterministic validation error;
- the recovery surface fits a 390 px viewport without horizontal overflow and
  exposes keyboard-focusable controls;
- the Google control is conditional on complete runtime provider availability.

The isolated runtime and browser tab were stopped after acceptance.

### Start-owned runtime evidence

Start now resolves an explicit `CLEANHOUSE_PYTHON`, then the managed runtime at
`~/.cleanhouse/runtime/python/bin/python3`, before active or repository-local
environments. The staged runtime contained byte-identical copies of every
changed authentication backend and frontend file checked. During the bounded
observation window, port 3333 remained reachable and `/health`,
`/cleanhouse/status?ready=1`, `/login`, `/signup`, and `/account-recovery`
returned HTTP 200.

The Codex execution host could not bootstrap the macOS LaunchAgent and could not
read process command lines through `ps`; direct Start-supervisor observation
therefore recorded `supervisor_pid_not_owned` even while the listener,
heartbeat, readiness probe, and resource guard were live. This is retained as
Start evidence and is not represented as a clean LaunchAgent acceptance.

The listener left on port 3333 was started before the final removal of the
obsolete desktop-token endpoint. Its staged source now matches the final source,
but the already-loaded Python process still exposes the prior route until the
next Start-owned restart. A final-source isolated runtime proved that route
returns HTTP 404. The Codex host was denied permission to signal the existing
3333 process, so this document does not represent the currently loaded 3333
process image as final-source acceptance.

## Provider-controlled acceptance still required

1. Register the deployed Google callback and perform one interactive Google
   signin using the intended production client.
2. Provision a verified Resend sender/domain or SMTP account and perform one
   real recovery delivery.
3. Run the password-reset UI with that delivered link; the backend token,
   password replacement, single-use, and old-password rejection contract is
   covered by focused tests, but the final credential-changing browser action
   was not automated.

These are deployment/provider proofs, not permission to install an auth runtime
or to introduce AUTO, MCP, or drbt into this path.

## Product-owned automatic regression gate — 2026-10-17

Run `python scripts/run-auth-regression.py` from the product checkout. Install
`Flask==3.1.3` and `requests==2.32.5` into that Python environment and provide
Node.js 22 on PATH (minimum 20). CI provisions Python 3.12 and Node 22 and uses
this identical command. The runner returns the suite's nonzero exit on failure;
missing dependencies and execution/90-second timeout failures return 2.

The runner invokes only `tests.test_auth_api_validation`: 22 existing validation
cases plus three isolated regression wrappers. These wrappers exercise two real
Flask tests and seven distinct Node UI cases (the missing-state case is also
run alone). They verify independent browser jars for the same and different
accounts, preserved saved-file sentinels, repeated logout and relogin, and failed
logout requests retaining identity with retry instead of false success.

Tests use a temporary HOME, synthetic signing secret, mocked user/report
services, and in-process Flask clients. No live provider, browser, service port,
user database, AUTH daemon, or wizard network request participates. Python
bytecode writes are disabled. The runner does not preserve inherited provider
credentials or Python import overrides in the test subprocess. No application
runtime behavior is changed by installing the gate.

`.github/workflows/authentication-regression.yml` runs on every push and pull
request, plus manual dispatch, with no path filters. Actions are commit-pinned,
permissions are read-only, checkout credential persistence is disabled, and the
job is time-bounded. This source installation does not execute remote CI or set
branch protection. A repository writer can omit/replace a local gate; an external
required status check is necessary to prevent merging without its result.

Source regression acceptance requires the clean suite to pass and disposable
restoration of each old backend/shared-file deletion, frontend premature clear,
and frontend false-success behavior to fail through this exact runner. Unrelated
file changes must leave the gate passing. Missing Flask/requests or Node must
fail explicitly. No product baseline is advanced by these tests.

This gate is focused source proof, not live provider acceptance, stolen-cookie
revocation proof, a full-product test suite, or proof of a deployed repair. The
historical evidence above remains tied to its original run. The existing live
runtime is not restarted or modified by this installation.


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

## Run 2 authentication acceptance — 2026-10-20

- Product gate: PASS, 85 focused tests plus the 11-of-11 protected-surface
  verifier.
- CSRF: password signin fetches the auth CSRF token and sends it in
  `X-CSRF-Token`; missing and forged values return 403/`CSRF_FAILED`.
- Session lifecycle: isolated browser proof covered creation, reload
  persistence, authenticated Settings state, independent logout/revocation, and
  protected-route redirect after logout. Store tests cover rotation, expiry,
  revocation, and multiple devices.
- Magic and providers: focused tests cover intent, expiry, replay, delivery
  failure revocation, GitHub PKCE/state, verified-primary-email enforcement,
  and stable provider binding. No live email or GitHub transaction was claimed.
- Settings boundaries: focused tests cover recent reauthentication, personal
  token one-time display/digest storage/revocation/expiry, and rejection of API
  tokens for sensitive browser-auth administration.
- External evidence: canonical AUTH commit
  `56c701ed3fc5af3c5215d11a603bb4dc76767645` returned VERIFIED in all seven
  lanes. Altered input evidence, invalid binding, and missing spec are rejected.
- Mutation sensitivity: removing the frontend CSRF header caused the ordinary
  product gate to fail; restoration returned it to PASS. AUTH was not rerun for
  that injected regression.
- Runtime scope: disposable loopback server and hidden browser only. `/health`
  passed; readiness truthfully remained false without Start supervision. Port
  3333, staged files, existing databases, and existing sessions were untouched.

Result: authentication source is locally complete and regression-sensitive.
Safe controlled live activation is **NO** until the staged runtime is rebuilt,
Start-supervised readiness is proven, and real email/GitHub provider acceptance
is completed.

## Disposable activation-package and recovery proof — 2026-10-20

The bounded activation delta contains 24 runtime paths: the accepted Settings
shell/assets plus the existing authentication backend, browser, recovery, and
account surfaces. Canonical `launch_agent.stage_runtime` supplied the unchanged
dependency closure (`access_control`, `models`, legal documents, and the
owner-only Keychain helper). Advanced Monitor remained `/advanced` backed by
`frontend/dashboard.html`; it was neither substituted for Settings nor included
as a Settings implementation.

Twenty-three activation paths were byte-identical from source to the disposable
stage. `config/auth-runtime.json` was the only intentional transformation: its
public/allowed origin was changed from canonical port 3333 to isolated loopback
port 43345. The manifest SHA-256 was
`4512207b1bfb78192d00381b4cb86f8af0680e11b3d8a26659ad7b4b67e7140e`.

The staged app ran under `backend.runtime_supervisor supervise` with isolated
HOME, runtime, data, auth database, origin, and port. `/health` and
`/cleanhouse/status?ready=1` passed with operator readiness. Hidden-browser
acceptance proved password/CSRF login, canonical protected product identity,
Settings account/consent state, reload persistence, independent device logout,
reauthenticated Settings API boundaries, and no console warnings or errors.
Service restart returned to readiness while preserving the browser session,
auth database, and a data sentinel. Atomic staged rollback restored the exact
preimage sentinel while leaving runtime data intact.

The ordinary 85-test build passed before and after the proving run. Canonical
AUTH commit `56c701ed3fc5af3c5215d11a603bb4dc76767645` returned VERIFIED for all
seven lanes with a bound candidate revision receipt. AUTH was not rerun to
evaluate either injected mutation; it was rerun only after
restoration and the permanent ordinary-gate repair. Removing the frontend CSRF header
failed the ordinary gate. A first Settings-route substitution exposed a missing
route-content assertion; the focused product-surface test was repaired, and the
same substitution then failed the ordinary gate. Restoration returned the gate
to PASS.

The restricted Codex host could not let `runtime_supervisor stop` authenticate
the disposable supervisor through `ps`, so the stop receipt retained
`supervisor_pid_not_owned`; exact disposable PIDs were terminated separately.
This is a sandbox observation, not live Start/launchd proof. Live port 3333,
staged runtime, databases, sessions, browser windows, and provider configuration
were untouched. Real email delivery and live GitHub acceptance remain external.

# MFA readiness addendum — 2026-10-22

The authoritative CleanHouse MFA source contract is
`documents/00_start-here/cleanhouse-mfa.md`. This bounded pass implements the
product-native adapter without activating it against the canonical runtime or
live authentication database. Manual-test readiness requires a configured
`CLEANHOUSE_MFA_ENCRYPTION_KEY`, an isolated database migration, focused
service/API/UI tests, and then separately authorized browser acceptance.

Ordinary Terms acceptance remains independent and idempotent. It must not
request password, provider, magic-email, or MFA proof. If the session itself
requires MFA admission, that admission completes once before consent and the
bounded pending action resumes once without an authentication/consent loop.
