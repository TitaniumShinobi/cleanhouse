import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth_runtime_config


class AuthRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        auth_runtime_config._runtime = None

    def tearDown(self):
        auth_runtime_config._runtime = None

    def _files(self, root: Path):
        contract = root / "auth-runtime.json"
        overlay = root / "public.json"
        contract.write_text(json.dumps({
            "schema": "cleanhouse.auth-runtime.v1",
            "appId": "cleanhouse",
            "allowedOrigins": ["http://localhost:3333", "http://127.0.0.1:3333"],
            "publicOrigin": "http://localhost:3333",
            "providers": {"google": {
                "enabled": True,
                "label": "Continue with Google",
                "callbackPath": "/api/auth/google/callback",
                "clientIdEnvironment": "CLEANHOUSE_GOOGLE_CLIENT_ID",
                "clientSecretEnvironment": "CLEANHOUSE_GOOGLE_CLIENT_SECRET",
                "clientSecretKeychain": {"service": "service", "account": "account"},
            }},
        }), encoding="utf-8")
        overlay.write_text(json.dumps({
            "schema": "cleanhouse.auth-public.v1",
            "providers": {"google": {"clientId": "public-client-id"}},
        }), encoding="utf-8")
        return contract, overlay

    def test_managed_runtime_uses_public_overlay_and_keychain_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract, overlay = self._files(Path(tmp))
            config = auth_runtime_config.resolve_runtime_config({
                "CLEANHOUSE_AUTH_CONFIG_PATH": str(contract),
                "CLEANHOUSE_AUTH_PUBLIC_CONFIG_PATH": str(overlay),
                "CLEANHOUSE_LAUNCHD_OWNED": "1",
            }, keychain_reader=lambda service, account: "keychain-secret")
        google = config["providers"]["google"]
        self.assertTrue(google["available"])
        self.assertEqual(google["client_id"], "public-client-id")
        self.assertEqual(google["client_secret"], "keychain-secret")
        self.assertEqual(google["callback_url"], "http://localhost:3333/api/auth/google/callback")

    def test_missing_secret_reports_provider_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract, overlay = self._files(Path(tmp))
            config = auth_runtime_config.resolve_runtime_config({
                "CLEANHOUSE_AUTH_CONFIG_PATH": str(contract),
                "CLEANHOUSE_AUTH_PUBLIC_CONFIG_PATH": str(overlay),
                "CLEANHOUSE_LAUNCHD_OWNED": "1",
            }, keychain_reader=lambda service, account: "")
        self.assertFalse(config["providers"]["google"]["available"])

    def test_runtime_port_and_explicit_origins_extend_the_auth_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract, overlay = self._files(Path(tmp))
            config = auth_runtime_config.resolve_runtime_config({
                "CLEANHOUSE_AUTH_CONFIG_PATH": str(contract),
                "CLEANHOUSE_AUTH_PUBLIC_CONFIG_PATH": str(overlay),
                "CLEANHOUSE_PORT": "3334",
                "CLEANHOUSE_ALLOWED_ORIGINS": "http://127.0.0.1:3334,https://cleanhouse.example",
            }, keychain_reader=lambda service, account: "secret")

        self.assertEqual(config["public_origin"], "http://localhost:3334")
        self.assertIn("http://localhost:3334", config["allowed_origins"])
        self.assertIn("http://127.0.0.1:3334", config["allowed_origins"])
        self.assertIn("https://cleanhouse.example", config["allowed_origins"])
        self.assertEqual(
            config["providers"]["google"]["callback_url"],
            "http://localhost:3334/api/auth/google/callback",
        )

    def test_initialization_does_not_export_resolved_secret(self):
        resolved = {
            "providers": {"google": {
                "client_id": "public-client-id",
                "client_secret": "keychain-secret",
                "callback_url": "http://localhost:3333/api/auth/google/callback",
            }}
        }
        environment = {}
        with patch.object(auth_runtime_config, "resolve_runtime_config", return_value=resolved):
            auth_runtime_config.initialize_auth_runtime(environment)
        self.assertNotIn("CLEANHOUSE_GOOGLE_CLIENT_SECRET", environment)
        self.assertNotIn("GOOGLE_CLIENT_SECRET", environment)
        self.assertNotIn("keychain-secret", environment.values())
        self.assertEqual(environment["CLEANHOUSE_GOOGLE_CLIENT_ID"], "public-client-id")

    def test_public_payload_never_contains_credentials(self):
        runtime = {
            "app_id": "cleanhouse",
            "allowed_origins": ["http://localhost:3333"],
            "public_origin": "http://localhost:3333",
            "providers": {"google": {
                "provider": "google", "label": "Continue with Google",
                "enabled": True, "available": True,
                "client_id": "public-id", "client_secret": "private-value",
            }},
        }
        with patch.object(auth_runtime_config, "runtime_config", return_value=runtime):
            serialized = json.dumps(auth_runtime_config.public_config_payload())
        self.assertNotIn("public-id", serialized)
        self.assertNotIn("private-value", serialized)

    def test_helper_read_uses_anonymous_fd_and_never_subprocess_output(self):
        secret = "fixture-secret-over-anonymous-pipe"
        observed = {}

        def run(args, **kwargs):
            request = json.loads(kwargs["input"])
            observed.update(args=args, kwargs=kwargs, request=request)
            os.write(int(request["responseFd"]), secret.encode())
            return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}\n', "stderr": ""})()

        with patch.object(auth_runtime_config, "sys_platform", return_value="darwin"), patch.object(
            auth_runtime_config.subprocess, "run", side_effect=run
        ), patch.dict(os.environ, {"CLEANHOUSE_KEYCHAIN_HELPER_PATH": "/managed/keychain-helper"}, clear=False):
            value = auth_runtime_config._keychain_secret("service", "account")

        self.assertEqual(value, secret)
        self.assertEqual(observed["args"], ["/managed/keychain-helper"])
        self.assertNotIn(secret, " ".join(observed["args"]))
        self.assertNotIn(secret, observed["kwargs"]["input"])
        self.assertNotIn(secret, observed["kwargs"]["stdout"] if "stdout" in observed["kwargs"] else "")
        self.assertEqual(observed["kwargs"]["pass_fds"], (int(observed["request"]["responseFd"]),))

    def test_denied_helper_read_fails_closed(self):
        completed = type("Result", (), {"returncode": 1, "stdout": '{"ok":false}\n', "stderr": "denied"})()
        with patch.object(auth_runtime_config, "sys_platform", return_value="darwin"), patch.object(
            auth_runtime_config.subprocess, "run", return_value=completed
        ):
            self.assertEqual(auth_runtime_config._keychain_secret("service", "account"), "")


if __name__ == "__main__":
    unittest.main()
