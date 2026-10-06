import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import wazuh_runtime


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_SCRIPT = REPO_ROOT / "scripts" / "vendor-wazuh-agent.sh"


class WazuhPackagingTests(unittest.TestCase):
    def setUp(self):
        wazuh_runtime._VERIFY_CACHE = None

    def test_vendor_script_uses_canonical_pins_and_staged_publication(self):
        source = VENDOR_SCRIPT.read_text(encoding="utf-8")

        for value in (
            wazuh_runtime.OFFICIAL_PACKAGE_SHA512,
            wazuh_runtime.OFFICIAL_SOURCE_SHA512,
            wazuh_runtime.OFFICIAL_SIGNER,
            wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT,
        ):
            self.assertIn(value, source)

        self.assertIn('tar -tzf "${SOURCE_STAGE}"', source)
        self.assertIn('notarization: trusted by the apple notary service', source)
        self.assertNotIn("CHECKSUM_URL=", source)
        self.assertIn('STAGE_DIR="$(mktemp -d)"', source)
        self.assertIn("trap cleanup EXIT", source)
        self.assertLess(
            source.index('mv "${PACKAGE_STAGE}"'),
            source.index('mv "${MANIFEST_STAGE}"'),
        )

    def test_vendor_script_bad_source_leaves_no_destination_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            curl = fake_bin / "curl"
            curl.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "destination=''\n"
                "for ((i = 1; i <= $#; i++)); do\n"
                "  if [ \"${!i}\" = '--output' ]; then\n"
                "    j=$((i + 1)); destination=${!j}\n"
                "  fi\n"
                "done\n"
                "case \"$*\" in\n"
                "  *wazuh-agent-4.14.7-1.arm64.pkg*) cp \"${TEST_PACKAGE}\" \"${destination}\" ;;\n"
                "  *LICENSE*) printf 'license' > \"${destination}\" ;;\n"
                "  *v4.14.7.tar.gz*) printf 'tampered source' > \"${destination}\" ;;\n"
                "  *) exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            destination = root / "bundled" / "wazuh" / "darwin-arm64"
            result = subprocess.run(
                ["bash", str(VENDOR_SCRIPT)],
                env={
                    **os.environ,
                    "CLEANHOUSE_WAZUH_REPO_ROOT": str(root),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "TEST_PACKAGE": str(wazuh_runtime.PACKAGE_PATH),
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pinned Wazuh source SHA-512 verification failed.", result.stderr)
        self.assertFalse(destination.exists())
        self.assertFalse(list(root.glob("**/*.partial.*")))

    def test_bundle_requires_package_source_checksum_and_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            package.write_bytes(b"official-package-fixture")
            source.write_bytes(b"matching-source-fixture")
            package_sha512 = hashlib.sha512(package.read_bytes()).hexdigest()
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "sha512": package_sha512,
                        "source_sha512": source_sha512,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "_package_signature", return_value={"verified": True, "status": "verified"}
            ), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ):
                result = wazuh_runtime.verify_bundle()

        self.assertTrue(result["packaged"])
        self.assertTrue(result["checksum_verified"])
        self.assertTrue(result["source_verified"])

    def test_bad_source_checksum_blocks_packaged_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            package.write_bytes(b"package")
            source.write_bytes(b"source")
            package_sha512 = hashlib.sha512(package.read_bytes()).hexdigest()
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "sha512": package_sha512,
                        "source_sha512": "0" * 128,
                    }
                ),
                encoding="utf-8",
            )
            wazuh_runtime._VERIFY_CACHE = None
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "_package_signature", return_value={"verified": True, "status": "verified"}
            ), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ):
                result = wazuh_runtime.verify_bundle()

        self.assertFalse(result["packaged"])
        self.assertFalse(result["source_verified"])

    def test_provenance_recovery_uses_byte_identical_copy_and_always_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            recovered = root / "recovered.pkg"
            package_bytes = b"pinned-package-with-provenance"
            package.write_bytes(package_bytes)
            source.write_bytes(b"pinned-source")
            package_sha512 = hashlib.sha512(package_bytes).hexdigest()
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps({"sha512": package_sha512, "source_sha512": source_sha512}),
                encoding="utf-8",
            )
            original_mode = package.stat().st_mode
            signature_paths = []

            def signature(path):
                path = Path(path)
                signature_paths.append(path)
                if path == package:
                    return {"verified": False, "status": "failed", "summary": "invalid signature"}
                self.assertEqual(path, recovered)
                self.assertEqual(path.read_bytes(), package_bytes)
                return {
                    "verified": True,
                    "status": "verified",
                    "signer": wazuh_runtime.OFFICIAL_SIGNER,
                    "sha256_fingerprint": wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT,
                }

            def copy_package(destination):
                Path(destination).write_bytes(package_bytes)

            fd = os.open(recovered, os.O_CREAT | os.O_RDWR, 0o600)
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ), patch.object(
                wazuh_runtime, "_package_signature", side_effect=signature
            ), patch.object(
                wazuh_runtime, "_copy_package_over_loopback", side_effect=copy_package
            ), patch.object(
                wazuh_runtime.tempfile, "mkstemp", return_value=(fd, str(recovered))
            ), patch.object(
                wazuh_runtime.subprocess,
                "run",
                return_value=Mock(returncode=0, stdout="", stderr=""),
            ) as run:
                result = wazuh_runtime.verify_bundle()

            self.assertTrue(result["packaged"])
            self.assertEqual(result["signature"]["verification_path"], "temporary_byte_identical_copy")
            self.assertTrue(result["signature"]["provenance_recovery"]["verified"])
            self.assertEqual(signature_paths, [package, recovered])
            self.assertFalse(recovered.exists())
            self.assertEqual(package.read_bytes(), package_bytes)
            self.assertEqual(package.stat().st_mode, original_mode)
            self.assertEqual(run.call_args.args[0][-1], str(recovered))
            self.assertNotEqual(run.call_args.args[0][-1], str(package))

    def test_provenance_recovery_cleans_up_failed_temporary_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            recovered = root / "recovered.pkg"
            package_bytes = b"pinned-but-untrusted-package"
            package.write_bytes(package_bytes)
            source.write_bytes(b"pinned-source")
            package_sha512 = hashlib.sha512(package_bytes).hexdigest()
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps({"sha512": package_sha512, "source_sha512": source_sha512}),
                encoding="utf-8",
            )

            def copy_package(destination):
                Path(destination).write_bytes(package_bytes)

            fd = os.open(recovered, os.O_CREAT | os.O_RDWR, 0o600)
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ), patch.object(
                wazuh_runtime,
                "_package_signature",
                return_value={"verified": False, "status": "failed"},
            ), patch.object(
                wazuh_runtime, "_copy_package_over_loopback", side_effect=copy_package
            ), patch.object(
                wazuh_runtime.tempfile, "mkstemp", return_value=(fd, str(recovered))
            ), patch.object(
                wazuh_runtime.subprocess,
                "run",
                return_value=Mock(returncode=0, stdout="", stderr=""),
            ):
                result = wazuh_runtime.verify_bundle()

            self.assertFalse(result["packaged"])
            self.assertTrue(result["signature"]["provenance_recovery"]["attempted"])
            self.assertFalse(result["signature"]["provenance_recovery"]["verified"])
            self.assertFalse(recovered.exists())
            self.assertEqual(package.read_bytes(), package_bytes)

    def test_package_signature_requires_signer_fingerprint_and_notarization(self):
        valid_output = "\n".join(
            [
                "Package Signature:",
                f"Developer ID Installer: {wazuh_runtime.OFFICIAL_SIGNER}",
                f"SHA-256 fingerprint: {wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT}",
                "Notarization: trusted by the Apple notary service",
            ]
        )
        cases = {
            "valid": (valid_output, 0, True),
            "missing signer": (
                valid_output.replace(wazuh_runtime.OFFICIAL_SIGNER, "Another Signer"),
                0,
                False,
            ),
            "missing fingerprint": (
                valid_output.replace(wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT, "0" * 64),
                0,
                False,
            ),
            "missing notarization": (
                valid_output.replace("trusted by the Apple notary service", "untrusted"),
                0,
                False,
            ),
            "pkgutil failure": (valid_output, 1, False),
        }
        with patch.object(wazuh_runtime.platform, "system", return_value="Darwin"):
            for label, (output, returncode, expected) in cases.items():
                with self.subTest(label=label), patch.object(
                    wazuh_runtime.subprocess,
                    "run",
                    return_value=Mock(returncode=returncode, stdout=output, stderr=""),
                ):
                    result = wazuh_runtime._package_signature(Path("fixture.pkg"))
                    self.assertEqual(result["verified"], expected)

    def test_pinned_vendoring_receipt_cannot_override_live_signature_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            package.write_bytes(b"pinned-package")
            source.write_bytes(b"pinned-source")
            package_sha512 = hashlib.sha512(package.read_bytes()).hexdigest()
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "vendored": True,
                        "sha512": package_sha512,
                        "source_sha512": source_sha512,
                        "signature": {
                            "developer_id_installer": wazuh_runtime.OFFICIAL_SIGNER,
                            "sha256_fingerprint": wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT,
                            "notarization": "trusted",
                            "verified_at_vendoring": "2026-08-22T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "_package_signature", return_value={"verified": False, "status": "failed"}
            ), patch.object(
                wazuh_runtime, "OFFICIAL_PACKAGE_SHA512", package_sha512
            ), patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ):
                result = wazuh_runtime.verify_bundle()

        self.assertFalse(result["packaged"])
        self.assertEqual(result["signature"]["status"], "failed")
        self.assertEqual(result["vendoring_signature_receipt"]["status"], "verified_at_vendoring")

    def test_vendoring_receipt_cannot_override_unpinned_package_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / wazuh_runtime.PACKAGE_NAME
            source = root / wazuh_runtime.SOURCE_ARCHIVE_NAME
            manifest = root / "manifest.json"
            package.write_bytes(b"tampered-package")
            source.write_bytes(b"pinned-source")
            source_sha512 = hashlib.sha512(source.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "vendored": True,
                        "sha512": hashlib.sha512(package.read_bytes()).hexdigest(),
                        "source_sha512": source_sha512,
                        "signature": {
                            "developer_id_installer": wazuh_runtime.OFFICIAL_SIGNER,
                            "sha256_fingerprint": wazuh_runtime.OFFICIAL_SIGNER_FINGERPRINT,
                            "notarization": "trusted",
                            "verified_at_vendoring": "2026-08-22T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(wazuh_runtime, "PACKAGE_PATH", package), patch.object(
                wazuh_runtime, "SOURCE_ARCHIVE_PATH", source
            ), patch.object(wazuh_runtime, "MANIFEST_PATH", manifest), patch.object(
                wazuh_runtime, "_package_signature", return_value={"verified": False, "status": "failed"}
            ) as signature, patch.object(
                wazuh_runtime, "_materialize_pinned_package"
            ) as materialize, patch.object(
                wazuh_runtime, "OFFICIAL_SOURCE_SHA512", source_sha512
            ):
                result = wazuh_runtime.verify_bundle()

        self.assertFalse(result["packaged"])
        self.assertFalse(result["checksum_verified"])
        signature.assert_not_called()
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
