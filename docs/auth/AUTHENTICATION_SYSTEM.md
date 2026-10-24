# CleanHouse authentication system

CleanHouse owns a product-native Python/Flask authentication implementation aligned by the transient lowercase `auth` wizard. No `auth` runtime, adapter, daemon, copied package, or control plane remains installed in CleanHouse.

## Browser lifecycle

`signup → server session → overview`

`signin → server session → overview`

`Google authorization code + S256 PKCE → one-time session-bound callback → server session → overview`

`recovery request → single-use expiring emailed token → password reset → signin`

`logout → clear server session and obsolete saved desktop state → signin`

Browser identity uses the `HttpOnly`, `SameSite=Lax` `cleanhouse_session` cookie. Bearer JWT verification remains available for explicitly authorized native/API clients; browser JavaScript does not persist authentication tokens in local storage.

## Configuration and ownership

- `config/auth-runtime.json` contains public product-owned provider metadata.
- Provider secrets come from the protected environment or macOS Keychain.
- Google is shown only when its client ID, client secret, and callback are all available.
- Recovery uses Resend when `EMAIL_SERVICE=resend`; SMTP is the supported fallback.
- Start owns port 3333, startup, staging, and readiness truth.
- auth owns reusable authentication assessment and standards. CleanHouse owns its UI, data, deployment configuration, sessions, and provider credentials.

Account recovery tokens are stored only as SHA-256 digests, expire after 30 minutes, and are single-use. Public recovery responses do not reveal whether an email address exists.

## Known external requirements

Live Google acceptance requires an owner-controlled client secret and the registered callback `http://localhost:3333/api/auth/google/callback`. Live recovery delivery requires a verified sender plus Resend or SMTP credentials. Local and automated tests do not substitute for those provider interactions.
