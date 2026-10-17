# Recovery credential invalidation

Password recovery atomically replaces the account's password hash and a random credential generation in its existing sharded `identity/auth.json`. No separate revocation database is introduced. New login/OAuth sessions and native JWTs retain the generation of their authenticated identity. Protected page, API, current-user, OAuth completion, bearer and refresh paths validate it against current account storage.

Credentials without a generation are legacy generation `0`: they remain valid only for never-reset accounts. A reset invalidates old browser cookies and native tokens for that account, including intermediate OAuth completion cookies. Other accounts and browser-local logout remain unchanged. A new sign-in obtains current credentials. Missing/corrupt account auth storage denies authentication. Restart reads the persisted generation.

An account-scoped OS file lock serializes reset and login-metadata writers across processes, preventing a concurrent last-login update from restoring revoked credentials. Atomic replacement prevents exposing a new password with the old generation. Unique temporary files prevent competing resets from sharing a temp path; the last completed reset wins and earlier credentials are invalidated. Already-admitted in-flight operations are not retroactively cancelled. Legacy SQLite-only password recovery remains unsupported by the pre-existing `set_password` path and fails rather than reporting success.

Run `python -B -m unittest -v tests.test_recovery_generation` in an isolated environment. Tests use temporary account storage and synthetic identities only; no provider, deployment or user session is exercised.
