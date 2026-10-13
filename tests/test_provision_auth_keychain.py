import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "provision-auth-keychain.py"
SPEC = importlib.util.spec_from_file_location("cleanhouse_provision_auth_keychain", SCRIPT)
provision = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(provision)


class ProvisionAuthKeychainTests(unittest.TestCase):
    def test_secret_is_sent_only_over_stdin(self):
        secret = "fixture-secret-never-argv"
        observed = []

        def runner(args, **kwargs):
            observed.append({
                "args": list(args),
                "input": kwargs.get("input"),
                "capture_output": kwargs.get("capture_output"),
            })
            return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            provision, "INSTALLED_KEYCHAIN_HELPER", Path(tmp) / "keychain-helper"
        ), patch.object(provision.os, "chmod"):
            provision.store_keychain_secret(secret, runner=runner)
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(secret not in call["args"] for call in observed))
        self.assertTrue(all(secret not in " ".join(call["args"]) for call in observed))
        self.assertTrue(all(call["capture_output"] for call in observed))
        self.assertIsNone(observed[0]["input"])
        self.assertEqual(json.loads(observed[1]["input"])["value"], secret)
        self.assertEqual(observed[0]["args"][-1], observed[1]["args"][0])

    def test_helper_output_never_contains_secret(self):
        secret = "fixture-secret-never-output"
        completed = SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")

        def runner(args, **kwargs):
            return completed

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            provision, "INSTALLED_KEYCHAIN_HELPER", Path(tmp) / "keychain-helper"
        ), patch.object(provision.os, "chmod"):
            provision.store_keychain_secret(secret, runner=runner)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(secret, completed.stderr)


if __name__ == "__main__":
    unittest.main()
