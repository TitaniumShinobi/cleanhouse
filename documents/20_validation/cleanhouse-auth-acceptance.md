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
- Logout clears Flask session identity and removes obsolete saved desktop OAuth
  state so it cannot silently restore a logged-out browser.
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
