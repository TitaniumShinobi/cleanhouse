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

Current implementation authority is the Python/Flask/SQLite alignment profile in `auth`; product-specific UI, persistence, and configuration remain owned by CleanHouse.

Start resolves the supervised interpreter by preferring an explicit
`CLEANHOUSE_PYTHON`, then the managed runtime at
`~/.cleanhouse/runtime/python/bin/python3`, before active or repository-local
environments. Readiness is not established until the supervised listener answers
the canonical status contract.
