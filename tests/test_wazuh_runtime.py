import hashlib
import base64
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from backend import wazuh_agent_configure, wazuh_runtime


class WazuhRuntimeTests(unittest.TestCase):
    def test_unverified_bundle_never_invokes_installer(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            wazuh_runtime.platform, "system", return_value="Darwin"
        ), patch.object(
            wazuh_runtime, "verify_bundle", return_value={"packaged": False}
        ), patch.object(wazuh_runtime.subprocess, "run") as run:
            result = wazuh_runtime.install_with_authorization(
                manager="wazuh.example",
                agent_name="zen-001",
                agent_id="001",
                monitored_scope=tmp,
            )

        self.assertEqual(result["status"], "error")
        run.assert_not_called()

    def test_client_key_import_validates_enrolled_identity(self):
        line = b"001 zen-001 any deadbeef\n"
        encoded = base64.b64encode(line).decode("ascii")

        decoded = wazuh_agent_configure._client_key_line(
            encoded, agent_id="001", agent_name="zen-001"
        )

        self.assertEqual(decoded, line)
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            wazuh_agent_configure._client_key_line(
                encoded, agent_id="002", agent_name="zen-001"
            )

    def test_lifecycle_does_not_claim_scanning_without_committed_event(self):
        with patch.object(
            wazuh_runtime,
            "verify_bundle",
            return_value={"package_present": True, "packaged": True, "version": "4.14.7"},
        ), patch.object(wazuh_runtime, "INSTALL_ROOT") as install_root:
            install_root.is_dir.return_value = False
            result = wazuh_runtime.lifecycle_status(
                ingestion={"authenticated": True, "authenticated_event_count": 0}
            )

        self.assertFalse(result["scanning"])
        self.assertEqual(result["lifecycle"], "connected")

    def test_lifecycle_progresses_installed_enrolled_connected_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Ossec"
            (root / "etc").mkdir(parents=True)
            bundle = {"package_present": True, "packaged": True, "version": "4.14.7"}
            with patch.object(wazuh_runtime, "INSTALL_ROOT", root), patch.object(
                wazuh_runtime, "verify_bundle", return_value=bundle
            ), patch.object(wazuh_runtime, "_agent_status", return_value={"running": True}):
                self.assertEqual(wazuh_runtime.lifecycle_status()["lifecycle"], "installed")
                (root / "etc" / "client.keys").write_text("enrolled", encoding="utf-8")
                self.assertEqual(wazuh_runtime.lifecycle_status()["lifecycle"], "enrolled")
                self.assertEqual(
                    wazuh_runtime.lifecycle_status(
                        ingestion={"authenticated": True, "authenticated_event_count": 0}
                    )["lifecycle"],
                    "connected",
                )
                self.assertEqual(
                    wazuh_runtime.lifecycle_status(
                        ingestion={"authenticated": True, "authenticated_event_count": 1}
                    )["lifecycle"],
                    "scanning",
                )

    def test_materialized_package_is_rehashed_and_resigned(self):
        package_bytes = b"verified-loopback-package"
        package_sha512 = hashlib.sha512(package_bytes).hexdigest()

        def write_package(path):
            Path(path).write_bytes(package_bytes)

        with patch.object(
            wazuh_runtime, "_copy_package_over_loopback", side_effect=write_package
        ), patch.object(
            wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
        ), patch.object(
            wazuh_runtime, "_package_signature", return_value={"verified": True, "status": "verified"}
        ), patch.object(
            wazuh_runtime.subprocess,
            "run",
            return_value=Mock(returncode=0, stdout="", stderr=""),
        ):
            path = wazuh_runtime._materialize_verified_package()

        try:
            self.assertEqual(path.read_bytes(), package_bytes)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            path.unlink(missing_ok=True)

    def test_materialized_package_is_removed_when_signature_fails(self):
        package_bytes = b"unsigned-loopback-package"
        package_sha512 = hashlib.sha512(package_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "materialized.pkg"
            fd = os.open(destination, os.O_CREAT | os.O_RDWR, 0o600)

            def write_package(path):
                Path(path).write_bytes(package_bytes)

            with patch.object(
                wazuh_runtime.tempfile, "mkstemp", return_value=(fd, str(destination))
            ), patch.object(
                wazuh_runtime, "_copy_package_over_loopback", side_effect=write_package
            ), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "_package_signature", return_value={"verified": False, "status": "failed"}
            ), patch.object(
                wazuh_runtime.subprocess,
                "run",
                return_value=Mock(returncode=0, stdout="", stderr=""),
            ):
                with self.assertRaisesRegex(RuntimeError, "signature verification failed"):
                    wazuh_runtime._materialize_verified_package()

            self.assertFalse(destination.exists())

    def test_installer_uses_only_materialized_verified_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "verified.pkg"
            package.write_bytes(b"verified")
            completed = Mock(returncode=0, stdout="", stderr="")
            with patch.object(wazuh_runtime.platform, "system", return_value="Darwin"), patch.object(
                wazuh_runtime, "verify_bundle", return_value={"packaged": True}
            ), patch.object(
                wazuh_runtime, "_load_enrollment_key", return_value="enrollment-client-key"
            ), patch.object(
                wazuh_runtime, "_materialize_verified_package", return_value=package
            ), patch.object(
                wazuh_runtime, "lifecycle_status", return_value={"lifecycle": "installed"}
            ), patch.object(
                wazuh_runtime, "delete_enrollment_key", return_value={"status": "ok", "deleted": True}
            ), patch.object(
                wazuh_runtime.subprocess, "run", return_value=completed
            ) as run:
                result = wazuh_runtime.install_with_authorization(
                    manager="wazuh.example",
                    agent_name="zen-001",
                    agent_id="001",
                    monitored_scope=tmp,
                )

            self.assertEqual(result["status"], "ok")
            command = run.call_args.args[0]
            self.assertEqual(command[:2], ["/usr/bin/osascript", "-e"])
            self.assertIn(str(package), command[2])
            self.assertNotIn(str(wazuh_runtime.PACKAGE_PATH), command[2])
            self.assertNotIn("enrollment-client-key", command[2])
            self.assertNotIn("WAZUH_REGISTRATION_PASSWORD", command[2])
            self.assertFalse(package.exists())


if __name__ == "__main__":
    unittest.main()
