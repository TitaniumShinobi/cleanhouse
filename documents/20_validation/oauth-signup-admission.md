# OAuth signup admission

OAuth GET starts returning-user sign-in. An unknown verified provider identity
receives `/signup?error=signup_required`; it creates neither an account nor a
session. Returning identities retain the existing login path.

Signup uses a same-origin JSON POST to the existing provider start endpoint,
with intent=signup, consent booleans, exact consentVersions and turnstileToken.
Existing legal-document and Turnstile policy helpers decide admission. Missing
verification fails; required but unconfigured verification returns 503. The
response supplies authorizationUrl for browser navigation, never provider tokens.
A callback-origin mismatch returns 409 rather than silently losing POST intent.

The signed pending OAuth transaction retains only successful verification,
current document versions and existing state/PKCE metadata. The callback checks
current document versions and applicable verification again before new-account
creation. No browser flag or direct GET substitutes for this proof. Existing
identities are reused. Expired or consumed state cannot authorize new creation.
Desktop handoff carries the same validated signup proof, not a separate policy.

Focused proof: tests.test_oauth_signup_admission, synthetic provider/registry.
No live provider configuration, Turnstile settings or account data is changed.
