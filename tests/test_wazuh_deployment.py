import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "deploy-wazuh-stack.sh"
README = ROOT / "deploy" / "wazuh" / "README.md"
OBSOLETE_CONFIG = ROOT / "deploy" / "wazuh" / "config.yml"
OBSOLETE_NGINX = ROOT / "deploy" / "wazuh" / "nginx.conf"


class WazuhDeploymentArtifactTests(unittest.TestCase):
    def test_installer_is_manager_only_on_existing_vvault_host(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('VVAULT_REPO="${VVAULT_REPO:-/opt/vvault-public}"', script)
        self.assertIn('"${package_name}" = "wazuh-manager"', script)
        self.assertIn('WAZUH_VERSION="4.14.7"', script)
        self.assertIn("CLEANHOUSE_WAZUH_MANAGER_SHA512", script)
        self.assertIn("sha512sum", script)
        self.assertIn('dpkg -i "${MANAGER_PACKAGE}"', script)
        self.assertNotIn("wazuh-install.sh", script)
        self.assertNotIn("--wazuh-indexer", script)
        self.assertNotIn("docker", script.lower())

    def test_installer_fails_closed_on_separate_data_plane(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("for forbidden_package in wazuh-indexer wazuh-dashboard filebeat", script)
        self.assertIn("assert_loopback_listener 55000", script)
        self.assertNotIn("assert_loopback_listener 9200", script)
        self.assertNotIn("nginx", script.lower())
        self.assertNotIn("createdb", script.lower())
        self.assertNotIn("psql", script.lower())

    def test_installer_connects_existing_vvault_service_without_new_runtime(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('usermod -a -G wazuh "${VVAULT_SERVICE_USER}"', script)
        self.assertIn('systemctl restart "${VVAULT_SERVICE}"', script)
        self.assertIn("/var/ossec/logs/alerts/alerts.json", script)
        self.assertIn("no indexer, dashboard, Filebeat, container, or database was created", script)

    def test_obsolete_indexer_gateway_artifacts_are_removed(self):
        self.assertFalse(OBSOLETE_CONFIG.exists())
        self.assertFalse(OBSOLETE_NGINX.exists())

    def test_runbook_preserves_approval_and_powered_state_gates(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("existing VVAULT DigitalOcean host", readme)
        self.assertIn("does **not** provision another Droplet", readme)
        self.assertIn("ovvaults.vault_files", readme)
        self.assertIn("These remain separate operator-approved operations", readme)
        self.assertIn("`powered_by_wazuh` remains false", readme)


if __name__ == "__main__":
    unittest.main()
