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

The runner invokes `tests.test_auth_api_validation` (22 existing validation
cases plus three isolated regression wrappers), followed in a separate process
by `tests.test_api_admission` (15 API admission cases). These wrappers exercise two real
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

## API admission — source repair

The application guard no longer exempts the entire `/cleanhouse/` prefix when
both `CLEANHOUSE_ENABLE_AUTH` and `CLEANHOUSE_REQUIRE_LOGIN` are enabled. Existing
page redirects and explicit auth-disable modes remain unchanged. API denial is
JSON: 401 `AUTHENTICATION_REQUIRED`, 403 `REQUEST_ORIGIN_REJECTED`, or 503
`AUTHENTICATION_UNAVAILABLE` on identity/store failure. No protected handler runs
on denial. Existing stricter Files and connected-account guards remain in place.

Browser admission resolves the existing signed session user in the current
product registry. During the existing OAuth completion transition, a signed
`oauth_success=true` plus consistent `oauth_user` identity can resolve that same
registry user without consuming/changing the pending completion. An arbitrary
pending object or nonexistent user is insufficient. The existing completion
endpoint still establishes `session.user_id` normally.

Native admission reuses the existing bearer parser and signature verifier and
requires a nonempty user ID, finite unexpired `exp`, and matching registry user.
Malformed/invalid bearer headers never fall back to an otherwise valid cookie.
No new credential format, refresh mechanism, or session storage is introduced.
Logout remains browser-local; it does not revoke independent existing native
bearers or other browser sessions.

Cookie-authenticated non-read requests require exact request-origin equality
and the existing origin allowlist, or `Sec-Fetch-Site: same-origin` when Origin
is absent. Another localhost port is not the same origin. Missing/cross-origin
context is denied. Native bearer requests do not require browser-origin headers.
OPTIONS continues to pass for preflight; existing endpoint methods/policies
still apply. No origins or provider settings are changed.

Unauthenticated readiness is limited to GET/HEAD `/cleanhouse/status?ready=1`
(with that sole query parameter) and GET/HEAD `/cleanhouse/runtime` (no query),
from an actual loopback peer and loopback Host. Browser Origin/Referer, non-none
fetch-site, and any Authorization header disqualify this exception. Forwarded
identity headers are not trusted. Existing launcher commands and payloads remain
unchanged. `/health` keeps its existing public behavior. These local readiness
responses are an intentional operational exception, not private account access.

Run `python scripts/run-auth-regression.py`: both suites execute separately with
temporary HOME and synthetic credentials. New tests use actual server admission
functions, Flask cookie jars, existing login/logout/OAuth completion handlers,
and existing JWT implementations with a synthetic user registry. They verify
handler non-execution on denial, cross-origin rejection, exact readiness bounds,
legacy auth toggles, stricter bearer endpoints, and independent sessions.
This is source-only acceptance, not live provider or deployment verification.

## Shared build and release gate

`python scripts/build-check.py` is the canonical source build/check command.
It runs the auth suites (including the real imported Flask server and blueprint
registration), protected surfaces and their dependency tests, then parses the
three auth/server modules. Any failed suite, missing dependency, timeout or
syntax error exits nonzero. It uses a temporary HOME and does not start a listener.
This is a source check, not a native application compiler or deployment command.
The full-server suite isolates user storage, reporting and collector startup;
it does not replace Flask routing, authentication handlers or admission hooks.

The authentication-regression CI job invokes this same command on all pushes,
PRs and merge groups. The manually dispatched release-check workflow is limited
to master and packages the exact committed source only after the gate passes.
It emits the commit and archive SHA-256; it does not deploy or publish a release.
CODEOWNERS requires owner review of gate changes when remote protection is active.
Remote required checks and tag restrictions are separately installed and read back;
source workflow files alone do not establish remote enforcement. Administrators
can change repository rules; these controls do not protect against a malicious
repository administrator. Release tag creation remains blocked until a reviewed
release publisher identity can enforce the same candidate-bound gate.
