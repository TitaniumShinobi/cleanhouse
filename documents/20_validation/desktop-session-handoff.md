# Desktop OAuth session handoff

The native webview prepares a same-origin POST transaction before opening the system browser. It retains the returned verifier in memory; only a random transaction identifier reaches the browser URL. The wrapper accepts identifiers only, builds a fixed local route, and never accepts an arbitrary redirect URL.

The browser canonicalizes to the configured callback origin before setting its OAuth state cookie. Existing provider state/PKCE validation and account admission run unchanged. Completion is retained server-side; it does not authenticate the shared system-browser session. The initiating webview redeems with its own signed cookie identity and secret verifier. Redemption invokes existing OAuth session completion, then restores/shows the existing window and navigates its existing view to Overview. No new window is created.

Transactions expire after five minutes, are bounded to 128 live entries, and are consumed under a process lock. Cancellation, replacement, or logout invalidates the pending transaction. Wrong cookies/verifiers, expired transactions and replay fail. Process restart discards pending handoffs: the user retries the same flow, never falls back to polling another browser's cookie. This is a single-runtime-process mechanism; deployments with multiple workers require shared authoritative transaction storage before enabling this path.

Provider denial validates/consumes its OAuth state before marking the matching handoff denied. Transport/provider failure returns a bounded terminal state or timeout. Returned verifier is no-store, memory-only, absent from URLs and logs. Ordinary browser OAuth still uses its original session path.

Run `python -m unittest -v tests.test_desktop_auth_handoff` with the configured isolated test Python. Tests use separate Flask cookie jars and mocks for provider transport and user storage, not live credentials. OS foreground behavior needs separate user-authorized desktop acceptance; window-show calls are not evidence the OS granted focus.
