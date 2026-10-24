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
2. The intended provider topology is a Wazuh macOS agent sending FIM evidence
   to a manager-only Wazuh service on the existing VVAULT host. Deployment and
   enrollment are not part of this boundary and are not claimed complete.
   No indexer, dashboard, Filebeat, container, or new database is introduced.
3. When the provider route is configured, CleanHouse authenticates to
   owner-scoped VVAULT routes, never to Wazuh administration. Each accepted
   alert keeps its provider identifier, agent, manager, rule, timestamp,
   canonical payload hash, and evidence references.
4. Event insertion and cursor advancement share one SQLite transaction. A
   provider source key prevents replay duplicates without rewriting raw
   provenance.
5. Every committed file observation advances an immutable hash-chain
   generation. Authoritative inventory reconciliation remains a separately
   guarded mutation boundary and is not exposed by this closure.
6. Normalized evidence is mirrored locally and queued in a durable OVVAULTS
   outbox. A batch is marked synced only when OVVAULTS returns a receipt that
   echoes the SHA-256 batch ID and every accepted evidence ID. Remote failure
   or an incomplete receipt remains visible as preservation backlog.
7. Watchdog remains a labeled local fallback. Its observations are never
   relabeled as Wazuh evidence.

## Files v2 contract

The read-only `cleanhouse.files.v2` snapshot provides:

- `collector`: provider, lifecycle, authenticated evidence state, version,
  connection health, monitored scope, event time, latency, cursor, and fallback
  reason and an explicit `operational` Boolean.
- `powered_by_wazuh`: true only after an authenticated poll and a successfully
  committed Wazuh event.
- `integrity`: generation, state root, chain hash, checkpoint, entry count,
  current immutable local projection.
- `preservation`: local mirror, authenticated remote state, backlog, oldest
  pending evidence, and last success/error.

The explicit product states are `live`, `warming`, `degraded`, `unavailable`,
`fallback`, and `no_data`. SSE event IDs are durable event cursors; reconnects
honor `Last-Event-ID` and receive state changes even without a new file event.

This boundary intentionally returns empty mediation, suggestion, finding, and
attention projections. Their state-changing routes remain deferred rather than
being exposed without a complete authorization contract.

## Security and release rubric

| Area | Required proof |
| --- | --- |
| Package | Exact pinned SHA-512 and trusted Apple package signature |
| Privilege | One normal macOS administrator prompt; no silent elevation |
| Enrollment | Secret stored in Keychain, temporary file mode `0600`, no logs |
| Transport | HTTPS except explicit loopback development; owner-scoped credentials; bounded timeout and response size |
| Replay | Atomic event/cursor commit and unique provider source key |
| Integrity | Immutable chain, full checkpoints, stable state root |
| Preservation | Idempotent evidence IDs, durable offline outbox, honest backlog |
| Branding | No Wazuh powered state before authenticated committed evidence |
| Authorization | Deferred to Zaelith; never inferred from actor or observation |

## Current implementation boundary

The local collector now starts as an optional server-owned evidence service.
Missing credentials or enrolled-agent identity leave it `unavailable`;
configured but unproven transport is `warming`; failed acquisition is
`degraded`; a running installed agent with authenticated transport and no
events is `no_data`; and the same complete lifecycle with current evidence is
`live`. `powered_by_wazuh` is durable historical truth only after authenticated
evidence was committed; later outages degrade current health without rewriting
that provenance. Current authentication and operational status also expire
when the manager-status attestation or feed is stale, or when the bounded
collector worker is no longer alive. Files reports continuous monitoring only
while either that current Wazuh observer or the labeled watchdog fallback is
actually running. Optional provider failure is recorded in startup diagnostics
without blocking the local CleanHouse runtime.

Remote acquisition accepts HTTPS destinations only, with plain HTTP reserved
for explicit loopback development. Credential-bearing endpoints must share the
configured VVAULT origin and redirects are rejected. Requests have a fixed
timeout, response bodies are size-bounded before JSON parsing, embedded URL
credentials and URL fragments are rejected, and failures expose stable reason codes rather than
response bodies, tokens, or private destination URLs. Retry waits and inventory
pagination are bounded and interruptible.

The server-owned OVVAULTS preservation worker is Files-scoped. It does not
activate or drain Network evidence; Network remote synchronization remains a
separate deferred boundary.

This closure contains authenticated read-only snapshot, SSE, and Wazuh-status
routes. It contains no new browser UI or state-changing route. Provider setup,
reconciliation, mediation, and the remaining mixed Files UI work stay deferred.

The following remain provider/operator actions and must not be represented as
complete until separately approved and evidenced:

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
