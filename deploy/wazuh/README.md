# VVAULT-hosted Wazuh manager for CleanHouse Files

CleanHouse uses the existing VVAULT DigitalOcean host and canonical OVVAULTS
database. It does **not** provision another Droplet, container, indexer,
dashboard, Filebeat instance, OpenSearch service, or database.

The topology is:

```text
CleanHouse macOS agent
        |
        v
Wazuh manager on the existing VVAULT host
        |
        v
Authenticated VVAULT Files routes
        |
        v
ovvaults.vault_files
        |
        v
CleanHouse /files
```

The manager necessarily maintains its own operational state under
`/var/ossec`; that is part of Wazuh itself, not a new hosted database.
Normalized evidence and receipts are appended to the existing
`ovvaults.vault_files` authority.

## Components deliberately omitted

- Wazuh Indexer
- Wazuh Dashboard
- Filebeat
- NGINX Wazuh gateway
- Docker or another container runtime
- A second PostgreSQL database or OVVAULTS schema
- Direct CleanHouse access to Wazuh administration

VVAULT reads the manager-local JSON stream at
`/var/ossec/logs/alerts/alerts.json` and queries the loopback-only manager API
for the enrolled agent's FIM inventory. CleanHouse authenticates to VVAULT,
not to the manager.

## Approval boundaries

These remain separate operator-approved operations:

1. Stage the pinned official Wazuh 4.14.7 manager package on the existing
   VVAULT host.
2. Run `scripts/deploy-wazuh-stack.sh` as root on that host.
3. Configure the manager enrollment secret in the host secret store.
4. Install and enroll the bundled macOS agent through the normal administrator
   prompt.
5. Run the end-to-end FIM smoke test.

The repository changes alone perform none of those operations.

## Manager installation gate

The installer accepts only an explicitly staged official `wazuh-manager`
4.14.7 Debian package and a pinned SHA-512:

```bash
sudo CLEANHOUSE_WAZUH_MANAGER_PACKAGE=/secure/stage/wazuh-manager_4.14.7-1_amd64.deb \
  CLEANHOUSE_WAZUH_MANAGER_SHA512='<official-or-independently-pinned-sha512>' \
  VVAULT_REPO=/opt/vvault-public \
  VVAULT_SERVICE=vvault-backend.service \
  VVAULT_SERVICE_USER=vvault \
  /secure/stage/deploy-wazuh-stack.sh
```

The script fails closed when a Wazuh indexer, dashboard, or Filebeat package is
already present. It binds the manager API to loopback, grants the existing
VVAULT service account read access through the Wazuh group, and restarts the
existing VVAULT backend. It does not download packages or create secrets.

## VVAULT configuration

Configure these values in the existing VVAULT host secret environment:

```text
VVAULT_WAZUH_ALERTS_PATH=/var/ossec/logs/alerts/alerts.json
VVAULT_WAZUH_MANAGER_API_URL=https://127.0.0.1:55000
VVAULT_WAZUH_MANAGER_CA_CERT=/var/ossec/api/configuration/ssl/server.crt
VVAULT_WAZUH_AGENT_ID=<enrolled-mac-agent-id>
VVAULT_WAZUH_MANAGER_TOKEN=<short-lived-or-rotated-manager-api-token>
VVAULT_CLEANHOUSE_INSTANCE_ID=zen-001
```

The manager token is never returned to CleanHouse. VVAULT exposes these
owner-scoped authenticated routes:

- `POST /api/cleanhouse/files/evidence`
- `GET /api/cleanhouse/files/wazuh/events`
- `GET /api/cleanhouse/files/wazuh/inventory`
- `GET /api/cleanhouse/files/wazuh/status`

## CleanHouse configuration

CleanHouse uses the existing VVAULT service credential and owner identity:

```text
CLEANHOUSE_VVAULT_URL=https://vvault.thewreck.org
CLEANHOUSE_VVAULT_SERVICE_TOKEN=<protected-service-token>
CLEANHOUSE_VVAULT_USER_EMAIL=<canonical-owner-email>
CLEANHOUSE_VVAULT_USER_ID=<optional-canonical-owner-uuid>
CLEANHOUSE_VVAULT_INSTANCE_ID=zen-001
```

`powered_by_wazuh` remains false until CleanHouse receives an authenticated
VVAULT Wazuh feed item and commits it to its append-only local event spine.
OVVAULTS synchronization state is reported independently so a preservation
backlog can never masquerade as fully preserved evidence.
