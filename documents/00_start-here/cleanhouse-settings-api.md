# CleanHouse Settings and personal API contract

## Product boundary

CleanHouse Settings belongs to the main security product. Its browser dashboard
is the current local control interface; VVAULT is an optional, separate paired data
product, not a replacement for CleanHouse's account, session store, or product
database. Local-first operation does not mean local-only storage. The reusable
[product ↔ VVAULT onboarding contract](product-vvault-onboarding-consent.md)
defines separate account/consent boundaries and explicit storage authorization.
CleanHouse signup and product consent stand alone: intended local collectors,
scans, and local data access do not require a VVAULT account. Only optional
VVAULT-backed storage, synchronization, and continuity require separate opt-in,
VVAULT signup/consent, and the explicit revocable handshake. That contract is a
specified destination, not a claim of implemented linking. CleanHouse's intended
default file-storage plane is the on-device filesystem. The reusable contract
does not generalize that physical location to other products: their default
plane may be a user-managed drive/NAS, product cloud, or hybrid, with capacity
and entitlement declared by each product's capability profile. VVAULT remains
an optional additional plane, not a replacement for the default plane. No
included quota, free allowance, or paid-tier entitlement is established here.
`/settings` opens the
same shared Settings modal used by the dashboard; it is a deep link, not a
second settings page or a public website account center.

The modal contains these stable tabs:

- General
- Providers
- API
- Notifications
- Personalization
- Schedules
- Billing
- Data
- Security
- Account
- Advanced

## Shell, route, and modal state

`GET /settings` serves the canonical `investigations.html` product shell, never
the Advanced Monitor. On first paint the ordinary Overview panel remains the
stationary underlay while the Settings dialog opens. The existing Settings
utility opens the same dialog in place and records a `settings` query state;
closing it restores the exact pre-modal local route. A direct `/settings` close
returns to `/overview` unless a validated local `return_to` path was supplied.

The dialog states are `hidden`, `opening/loading`, `ready`, `unavailable`, and
`error/retry`. It has nonzero bounded dimensions: desktop width is at most
980px/94vw and height at most 88vh; at 760px and below it uses 96% width and
94vh. The document body does not scroll while the dialog is open. Escape,
the close control, and backdrop activation close it. Tab is contained within
the dialog, arrow/Home/End keys move among tabs, and focus returns to the
opening control when that control still exists.

When current consent is missing, protected page navigation returns to the
requested product route with `consent=required` and a bounded `return_to`
parameter. A compact policy-review dialog opens over that route; it does not
force-open the full Settings modal. `return_to` is accepted only as a
same-origin absolute path (a leading `/`, never `//`, and never a Settings
loop). The dialog provides direct standalone Terms of Service, Privacy Notice,
and EECCD links, a required unchecked confirmation box, and an Accept action
that remains disabled until the box is checked. Escape, the close control, and
Review later dismiss only the popup and leave the blocked product surface
truthful. Successful owner acceptance returns to the originally requested
protected route; failure remains visible in the popup. Settings → Account still
shows consent status and history when the owner intentionally opens Settings.

The compact popup covers CleanHouse Terms, Privacy Notice, and EECCD acceptance
only. It must not imply VVAULT signup, VVAULT policy acceptance, or permission
to transfer evidence. Cross-product storage linking requires its own explicit
review and receipt under the linked onboarding contract. Provider identity
linking in the Providers tab is also distinct from a VVAULT storage link.

### Policy and standalone legal presentation

The policy popup uses only `.policy-consent-*` scoped styling: a 460px maximum
desktop width, 28px padding, an 18px radius, a 24–28px heading with 1.15 line
height, and a dark translucent overlay over the requested product page. At
560px and below it remains a bottom-aligned panel with 10px outer spacing,
28px/22px/22px padding, a 16px radius, and stacked full-width actions. Its
scrollable height remains bounded to the viewport. Empty error/status space
is hidden; actual errors retain their live status region. Primary actions and
the checkbox use desaturated green `#8dbb9c`; disabled acceptance remains at
40% opacity. Secondary actions use a faint green surface and border. The
existing keyboard focus ring, checkbox gating, dismissal, redirect, and
Google-only account behavior remain unchanged.

Only `/legal/terms`, `/legal/privacy`, and `/legal/eeccd` load `legal.css`.
They retain the existing 1100px document shell, 850px article, 40–70px editorial
title, section headings, lists, dividers, original legal text and update date,
and Print control. The dark void and faint top-left illumination remain.
The updated date is an inline tag with 5px/10px padding, a 6px radius, a
24%-opacity green border, an 8%-opacity green background, and `#a3c9af` text.
At 720px and below the existing narrower document spacing applies. Print
uses dark text, including the tag and links, on white.

Validation commands: `cleanhouse_env/bin/python3 -m unittest
tests.test_policy_consent_modal tests.test_legal_pages_ui
tests.test_auth_protection_boundary` and
`node --test tests/settings_reauth_node.test.mjs`; rerun
`cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py`.
Acceptance requires an unchecked initial checkbox, disabled Accept until
checked, protected data still denied after dismissal/reload, no password
prompt for Google-only accounts, readable desktop/mobile presentation, and
unchanged legal wording. These presentation edits are repository source only;
the canonical runtime is not restarted or activated by this work. Isolated
rendering and focused tests do not establish live Safari/session acceptance.

Providers, API, Security, Account, and Advanced are functional in this
boundary. Other tabs render explicit unavailable states and must not expose
controls that imply an unimplemented service.

## Functional tabs

### Providers

Providers reports Google and GitHub configuration and connection status without
revealing client identifiers, secrets, provider access tokens, or protected
diagnostics. Connecting starts the product's state/PKCE flow. Linking an
identity requires a current device session and recent human reauthentication.
The fresh proof uses a viable non-provider human method before unlinking, so a
provider cannot remove the user's last usable authentication method.

### API

Personal tokens use the `chpat_` prefix. A newly generated secret is displayed
exactly once. Lists contain only identifier, short prefix, name, creation,
expiry, last-use, and revocation status. Token storage contains only a digest
and the display prefix.

The default lifetime is 30 days and the maximum is 90 days. Rotation creates a
replacement and atomically revokes the old token. Every request rechecks the
current user's active status, role, legal consent, token expiry, and revocation.
Last-use writes are coalesced.

A PAT has full product-operation parity with its owner's current CleanHouse
role, but cannot create, rotate, list, or revoke API tokens; manage sessions or
authentication methods; link or unlink providers; accept legal policy; delete
an account; or satisfy recent-human-reauthentication requirements.

### Security

Security lists the current Mac/browser session and other durable device
sessions using non-secret administrative UUIDs without exposing cookie or
session-secret material. It supports revoke-one and revoke-others. Session-wide actions require recent human
reauthentication. Revoked, expired, rotated, or replayed identifiers fail
closed.

### Account

Account displays the CleanHouse identity and current Terms, Privacy, and EECCD
consent state. It supports re-consent, logout, and the existing deletion
workflow. Consent is a human session operation and is unavailable to PATs.

Recent reauthentication is provider-aware. `GET /api/auth/reauth` reports only
bounded capability metadata for the current session and identity. A password
field is rendered only when password-authentication evidence exists for that
identity. Google-only and other provider-only identities are never told to
enter a nonexistent local password; they use verified-email confirmation when
delivery is configured. Mixed identities may use every supported verified
human method. Linked OAuth providers remain visible as identity context, but
are not presented as reauthentication actions until a provider reauthentication
flow is implemented. If capability discovery or email delivery is unavailable,
Settings shows that failure explicitly and does not fall back to a password
prompt. Existing session, provider binding, consent, and account data remain
unchanged.

### Advanced

Advanced preserves the established runtime and antivirus controls. Each field
must state whether it is persisted, session-only, or unavailable. Settings must
not claim a control is durable when the backend retains it only in memory.

## API surface

The protected local interface is:

- `GET /api/auth/csrf`
- `POST /api/auth/session/refresh`
- `GET /api/auth/sessions`
- `DELETE /api/auth/sessions/{id}`
- `POST /api/auth/sessions/revoke-others`
- `POST /api/auth/reauth`
- `GET /api/auth/reauth`
- `GET /api/auth/consent`
- `POST /api/auth/consent`
- `POST /api/auth/magic/request`
- `POST /api/auth/magic/verify`
- `GET /api/auth/providers`
- provider start/callback routes with `login`, `signup`, and `link` intent
- `GET /api/auth/tokens`
- `POST /api/auth/tokens`
- `POST /api/auth/tokens/{id}/rotate`
- `DELETE /api/auth/tokens/{id}`

Sensitive responses use `Cache-Control: no-store`. Cookie mutations require an
exact local Origin and CSRF. Bearer PATs do not use cookie CSRF, but they cannot
call sensitive-auth endpoints. Request bodies, remote timeouts, retries,
response sizes, and retained auth events are bounded.

## Accessibility and responsive behavior

The modal is a labelled dialog with focus containment, Escape/close behavior,
focus restoration, keyboard-operable tabs, visible focus, accessible status
announcements, and a single logical heading. Desktop and narrow mobile layouts
must preserve every tab, action label, warning, and unavailable state without
horizontal page overflow.

## Current external gates

Live GitHub connection remains unavailable until the owner registers
`http://localhost:3333/api/auth/github/callback` and provisions the GitHub
client ID/secret through the established Keychain path. Live magic-email
acceptance remains unavailable until Turnstile and Resend or SMTP are
configured. These external gates never authorize fake availability or storing
secrets in Settings.

## Run-1 validation boundary

Focused proof uses `tests.test_auth_settings_ui`,
`tests.test_auth_protection_boundary`, the protected-surface verifier, and an
isolated full server plus bounded headless rendering. The canonical listener on
port 3333, live sessions/databases, provider flows, login, OAuth, magic email,
logout, CSRF behavior, and staged runtime remain unchanged. Source proof is not
live activation.

## Activation gate — 2026-10-20

The ordinary product gate now executes the `/settings` Flask route and requires
the canonical investigations shell's `settings-modal` marker while rejecting
the Advanced Monitor page. This closes the gap where static Settings assets
could pass while `/settings` served the wrong protected surface. The accepted
route remains `frontend/investigations.html`; `/advanced` remains independently
backed by `frontend/dashboard.html`.

## Consent-blocked data and shared appearance — 2026-10-20

A same-origin HTTP 428 response with `code=consent_required` is access evidence,
never evidence of a failed collector. The shared HTTP client retains a
page-lifetime consent-required flag and emits `cleanhouse:consent-required`.
Applications, Files (all five views), and Network (all five views) show
“Policy consent required” with a Settings → Account review link preserving the
current local pathname. Network reports ACCESS BLOCKED / CONSENT REQUIRED;
posture counts and Files location counts are unknown, never zero. Overview
shows the same access explanation instead of asserting no active threats.
Pending snapshot/projection results cannot replace this state with empty data
or capture errors. Network and Files event streams close and cannot restart
while this flag is set. Data load/refresh entry points stop while blocked.
The latch clears on full navigation; policy acceptance already reloads the
return route. Consent accepted in another browser tab requires a reload here.
No consent is inferred from clicking a navigation link or from collector health.
Other HTTP failures retain their existing behavior. The server access gate,
required policy versions, and human acceptance operation are unchanged.

Settings uses the existing shell tokens: --bg, --panel, --panel-strong, --ink,
--muted, --line, --line-soft, --accent, --accent-ink, and --warn, with matching
fallback values for the Advanced shell. Charcoal surfaces, mint primary
controls and focus rings, inherited body typography, muted metadata, and
restrained amber consent notices replace the separate blue palette. Generic
modal/button selectors are scoped to .settings-overlay to preserve other
surfaces. All eleven tabs, focus management, close behavior, dimensions, and
unavailable states remain. Reauthentication controls wrap on narrow screens;
consent text explicitly distinguishes blocked data from collector failure.

Validation: run `node --test tests/consent_access_node.test.mjs` and
`cleanhouse_env/bin/python3 -m unittest tests.test_auth_settings_ui`; rerun
`cleanhouse_env/bin/python3 scripts/verify-product-surfaces.py`. Rendered QA
uses an isolated headless browser with intercepted fixture responses at desktop
and mobile sizes. Fixture proof is not authenticated live-provider acceptance.
Runtime activation must preserve unrelated live overlays; source verification
alone does not establish live deployment or consent acceptance.

### Activation and validation receipt

The dedicated `.consent-review-link` also uses the shell accent and a visible
focus ring. On 2026-10-20, 14 focused Node assertions (consent access and Network
completion), 9 Settings contract checks, and the 11-surface preservation gate
passed. Headless rendered QA was attempted but could not launch: macOS denied
Chromium's MachPortRendezvousServer registration. Desktop/mobile screenshots,
visual fit, and browser interaction acceptance remain NOT_VERIFIED.

The four changed assets (`api-client.js`, `investigations.js`, `settings.js`,
`settings.css`) were activated in the existing managed runtime without a
restart. All four public HTTP asset responses on localhost:3333 matched the
repository bytes. Before activation, the three auth/Settings asset baselines
matched HEAD; the investigations difference contained only this task's patch.
Original runtime files and SHA-256 receipt are recoverable under
`/private/tmp/cleanhouse-consent-activation-20261020/` (temporary local storage).
This verifies served source, not authenticated visual behavior or provider
recovery. Reload is required for an already-open page. No consent, sessions,
backend files, or provider configuration were changed.
