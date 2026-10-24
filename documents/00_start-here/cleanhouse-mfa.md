# CleanHouse product-owned MFA adapter

Status: source implementation complete; canonical live activation and browser acceptance not authorized.

Authority: CleanHouse consumer implementation of AUTH `life.auth.mfa/1`, pinned to `AUTH_MFA_PROFILE.md` SHA-256 `1161c6afad4a54b5a3b90073b54267642a6fa5d814cd334b39c7fb2198f166b8` and normalized AUTH patch SHA-256 `17779c99c036437eaa858e8e5beedbdd4d55d177dacedf849d9d0a69bab8ba6f`.

## Product boundary

CleanHouse owns this Python/Flask/SQLite adapter. It does not run an AUTH daemon, Node sidecar, or shared service. `backend/auth_mfa.py` implements TOTP, recovery codes, challenges, grants, rate reservations, audit events, session admission, and additive schema in the existing CleanHouse authentication database. `backend/api/auth.py` owns the HTTP adapter. `frontend/js/settings.js` owns the Settings > Security management experience.

The preferred custody path is macOS Keychain service `com.life.cleanhouse.auth.mfa`, account `encryption-key`. The canonical background runtime may use the owner-only file `~/.cleanhouse/auth/mfa-encryption-key` through `CLEANHOUSE_MFA_ENCRYPTION_KEY_FILE` when Keychain access is unavailable to the LaunchAgent; the file must be owned by the current user and must not grant group or other permissions. `CLEANHOUSE_MFA_ENCRYPTION_KEY` (or the compatible `AUTH_MFA_ENCRYPTION_KEY`) is an isolated-development fallback. The value must be a product-managed 32-byte key encoded as 64 hexadecimal characters and distinct from the signing secret. Missing or invalid encryption configuration fails enrollment and proof verification closed with `503`; it never creates plaintext factor material.

## Factors, codes, and storage

- TOTP is RFC 6238 SHA-1, 160-bit secret, six digits, 30-second steps, and a ±1-step window.
- The accepted counter must strictly increase, preventing proof replay even during concurrent requests.
- AES-256-GCM encrypts factor secrets with owner/factor associated data.
- Recovery creates ten random 128-bit codes. Codes are displayed only on first activation or explicit rotation; only SHA-256 digests persist.
- Recovery codes are single-use and leave enrolled factors active.
- Five active factors are permitted. The last active factor cannot be removed until a replacement is activated.
- Factor and recovery responses are no-store and never enter browser storage.

## Routes

All mutations require JSON, an exact same-origin request, and the established CSRF token.

| Route | Behavior |
| --- | --- |
| `GET /api/auth/mfa/factors` | Lists active factor IDs, labels, timestamps, and current-session admission only. |
| `POST /api/auth/mfa/enroll` | Creates a five-minute owner/session-bound pending factor. Additional factors require a `factor.add` proof. |
| `POST /api/auth/mfa/confirm` | Activates the factor, admits and rotates the initiating session, and returns initial recovery codes once. |
| `POST /api/auth/mfa/challenge` | Creates a five-minute server-policy operation/target challenge. |
| `POST /api/auth/mfa/verify` | Atomically consumes one TOTP counter or recovery code, admits and rotates the initiating session, and returns one five-minute operation proof. |
| `POST /api/auth/mfa/remove` | Consumes an exact `factor.remove` proof and removes a non-final factor. |
| `POST /api/auth/mfa/recovery/rotate` | Consumes an exact `recovery.rotate` proof and replaces all recovery codes. |

Supported server-owned operations use these exact target rules: `authenticate`, `factor.add`, and `recovery.rotate` require an empty target; `factor.remove` requires the exact factor ID; `account.delete` requires `delete`; `provider.manage` requires the exact provider ID; `token.manage` requires the exact token ID (or `create` for issuance); and `session.manage` requires the exact session ID (or `others` for bulk revocation). A request cannot invent a risk policy or target. Existing sensitive Settings operations consume matching one-use proofs when factors exist and otherwise retain established password or verified-email reauthentication.

## Session and identity behavior

Password, OAuth provider, and magic-email authentication all mark the issued opaque device session as primary-authenticated. No password is invented or requested for passwordless identities. Enrollment requires primary authentication within five minutes; a successful established reauthentication refreshes that timestamp.

If an owner has an active factor, a newly authenticated session reports `mfaRequired: true` and `admissionAuthorized: false`. `/api/auth/me` reports the same state. Protected application routes reject or redirect until that exact session completes `authenticate`. Settings remains reachable for enrollment and challenge completion. MFA success rotates only the initiating opaque session while preserving its absolute expiry; MFA admission and unconsumed proof binding move to the replacement. Other sessions remain stored but are not admitted implicitly. Logout and revocation remain authoritative because a revoked device session cannot resolve identity.

## Consent separation and continuation

Ordinary policy acceptance remains a separate, idempotent authenticated action. `/api/auth/consent` does not request or invoke password, OAuth, magic email, or MFA. Admission enforcement precedes consent enforcement on protected routes. An independently required MFA step-up completes once and resumes only the bounded pending route; consent acceptance then records only missing current document digests and resumes its bounded return once. No consent receipt is created by MFA enrollment, verification, recovery, or management.

## Failure, rates, audit, and lifecycle

Invalid or replayed proof returns `401`; missing primary authentication or matching step-up returns `403`; last-factor removal returns `409`; exhausted per-account enrollment, challenge, or proof buckets return `429`; missing cryptographic infrastructure returns `503`. Five attempts per account per minute are reserved in separate buckets. Failed proof reservations commit independently of the failed proof transaction.

Append-only `mfa_audit` rows contain owner ID, event, timestamp, optional session ID, and bounded non-secret metadata. Provisioning URIs, codes, cookies, encryption keys, and operation proofs are never audited. Cleanup/retention and encryption-key rotation remain operational procedures not implemented by this bounded source pass.

## Additive migration and rollback

Initialization creates only `mfa_*` tables and one append-only audit trigger; it does not modify identity IDs, consent receipts, existing device sessions, API tokens, provider bindings, or user data. No live migration was run. Source rollback consists of removing the product adapter/routes/UI while leaving additive empty tables harmlessly present; populated MFA state must be preserved for reviewed forward recovery and must not be silently deleted.

## Validation criteria and limitations

Focused proof must cover passwordless enrollment, encrypted secret persistence, single-use TOTP and recovery, exact action/target grants, initiating-session rotation binding, parallel-session non-admission, primary-auth expiry, missing-key failure, persistent failed-attempt rate reservations, existing auth regression, JavaScript syntax, protected surfaces, and document integrity.

Not verified by this source pass: canonical runtime activation, migration of the live authentication database, browser interaction, real OAuth/email delivery, QR rendering, encryption-key rotation, external audit preservation, or production ingress/IP rate limiting.
