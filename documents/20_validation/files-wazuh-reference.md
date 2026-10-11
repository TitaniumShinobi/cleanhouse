# CleanHouse Files evidence foundation

## Thesis

Files is an evidence system, not a file-browser animation. Wazuh supplies
authenticated endpoint File Integrity Monitoring evidence; CleanHouse
normalizes that evidence into its append-only spine, advances immutable
integrity generations, and preserves receipts through OVVAULTS. Zaelith later
decides identity, approval scope, and authorization. Observation alone never
means authorized.

## Research basis

Primary Wazuh references:

- File Integrity Monitoring: https://documentation.wazuh.com/current/user-manual/capabilities/file-integrity/index.html
- FIM settings: https://documentation.wazuh.com/current/user-manual/capabilities/file-integrity/basic-settings.html
- Architecture: https://documentation.wazuh.com/current/getting-started/architecture.html
- Official package list: https://documentation.wazuh.com/current/installation-guide/packages-list.html
- Wazuh license: https://github.com/wazuh/wazuh/blob/main/LICENSE

The pinned target is Wazuh Agent `4.14.7-1` for Apple silicon. Its shipping
closure is now vendored locally: the package, corresponding source archive,
manifest, upstream license, third-party notices, and source-compliance record.
The vendoring gate fails closed unless the fixed package and source SHA-512
pins match, `pkgutil --check-signature` confirms the exact Wazuh signer and
fingerprint, Apple notarization is trusted, and the source archive is readable.
Runtime bundle verification applies the same pinning boundary before use.
Administrator-authorized installation and remote deployment remain separate
operator-approved actions.

As of the 2026-08-22 validation, the official 4.14.7 ARM64 package and source
archive match their pinned SHA-512 values. In the staged LaunchAgent runtime,
`pkgutil --check-signature` verifies Developer ID Installer `Wazuh Inc
(KLZK8P68R5)`, fingerprint
`A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E`, a
trusted timestamp, and Apple notarization. A restricted sandbox can return an
`invalid signature` false negative because the Code Signing subsystem is not
available there; release verification must run in the same unsandboxed macOS
context that will invoke the installer. A prior manifest receipt remains audit
metadata only and can never substitute for that live Apple signature check.

## Architecture

1. `launchd` owns the long-running local supervisor through the current user's
   `org.cleanhouse.runtime` LaunchAgent. Runtime truth is still derived from
   live PID ownership, port ownership, readiness, and heartbeat evidence. The
   staged runtime includes the complete Wazuh shipping closure: package, source
   archive, manifest, license, third-party notices, and source-compliance
   record; focused LaunchAgent tests verify byte-for-byte staging.
2. The Wazuh macOS agent sends FIM evidence to a manager-only Wazuh service on
   the existing VVAULT host. No indexer, dashboard, Filebeat, container, or new
   database is deployed. Wazuh's required manager state remains under
   `/var/ossec`; canonical preserved evidence remains in `ovvaults.vault_files`.
3. The VVAULT backend reads the manager-local JSON alert stream and queries the
   loopback-only manager API for inventory. CleanHouse authenticates to
   owner-scoped VVAULT routes, never to Wazuh administration. Each raw Wazuh
   alert keeps its provider identifier, agent, manager, rule, timestamp,
   canonical payload hash, and evidence references.
4. Event insertion and cursor advancement share one SQLite transaction. A
   provider source key prevents replay duplicates without rewriting raw
   provenance.
5. Every committed file observation advances an immutable hash-chain
   generation. Periodic checkpoints hold a complete state projection; a
   reconcile compares Wazuh inventory and then advances another generation.
6. Normalized evidence is mirrored locally and queued in a durable OVVAULTS
   outbox. A batch is marked synced only when OVVAULTS returns a receipt that
   echoes the SHA-256 batch ID and every accepted evidence ID. Remote failure
   or an incomplete receipt remains visible as preservation backlog.
7. Watchdog remains a labeled fallback. Fallback reconcile only inspects paths
   already observed inside its configured scope and is explicitly partial.

## Files v2 contract

`cleanhouse.files.v2` retains v1 fields and adds:

- `collector`: provider, lifecycle, authenticated evidence state, version,
  connection health, monitored scope, event time, latency, cursor, and fallback
  reason.
- `powered_by_wazuh`: true only after an authenticated poll and a successfully
  committed Wazuh event.
- `integrity`: generation, state root, chain hash, checkpoint, entry count,
  drift state, and last reconciliation receipt.
- `preservation`: local mirror, authenticated remote state, backlog, oldest
  pending evidence, and last success/error.

The explicit product states are `live`, `warming`, `degraded`, `unavailable`,
`fallback`, and `no_data`. SSE event IDs are durable event cursors; reconnects
honor `Last-Event-ID` and receive state changes even without a new file event.

Mediation remains durable and non-executing. Queue and transition actions have
immutable receipts and evidence references, while every item reports
`execution_state: unavailable_until_zaelith`. Attention counts exclude routine
in-progress work.

## Security and release rubric

| Area | Required proof |
| --- | --- |
| Package | Exact pinned SHA-512 and trusted Apple package signature |
| Privilege | One normal macOS administrator prompt; no silent elevation |
| Enrollment | Secret stored in Keychain, temporary file mode `0600`, no logs |
| Transport | TLS; mTLS supported; least-privileged Wazuh credentials |
| Replay | Atomic event/cursor commit and unique provider source key |
| Integrity | Immutable chain, full checkpoints, stable state root |
| Preservation | Idempotent evidence IDs, durable offline outbox, honest backlog |
| Branding | No Wazuh powered state before authenticated committed evidence |
| Authorization | Deferred to Zaelith; never inferred from actor or observation |

## Current implementation boundary

The local code, contracts, packaging gate, runtime bundle verification, and
focused tests are complete without external side effects. The following remain
gated operations and must not be represented as complete until separately
approved and evidenced:

- stage and install the manager-only Wazuh package on the existing VVAULT host;
- invoke the administrator-authorized macOS agent installer;
- run the long-lived hosted smoke test and extended in-app-browser validation;
- configure CLA Assistant and required branch protection in GitHub;
- complete legal review of GPL, trademark, CLA, Wazuh redistribution, and
  corresponding-source obligations.

## Conclusion

The clean handoff to Zaelith begins only after collector identity, ingestion
authentication, cursor durability, integrity generations, reconciliation, and
preservation state are all truthful. Zaelith then adds open-ended actor
identity confidence, approval envelopes, scope validation, and unauthorized-
action classification without changing the evidence that Files already kept.
