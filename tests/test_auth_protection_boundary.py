from __future__ import annotations

import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class AuthProtectionBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = patch.dict(
            os.environ,
            {
                "CLEANHOUSE_ENABLE_AUTH": "1",
                "CLEANHOUSE_REQUIRE_LOGIN": "1",
                "FLASK_SECRET_KEY": "focused-protection-boundary",
            },
            clear=False,
        )
        cls.env.start()
        with patch("atexit.register"):
            cls.server = importlib.import_module("backend.server")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.env.stop()

    def _evaluate(self, path: str, *, method: str = "GET", identity=None):
        with self.server.app.test_request_context(path, method=method, base_url="http://localhost:3333"):
            with patch.object(self.server, "_has_cleanhouse_session", return_value=identity):
                return self.server._require_auth_for_app_pages()

    def test_unauthenticated_pages_redirect_and_control_apis_deny(self):
        page = self._evaluate("/overview")
        api = self._evaluate("/cleanhouse/files/snapshot")
        self.assertEqual(page.status_code, 302)
        self.assertTrue(page.headers["Location"].endswith("/login"))
        self.assertEqual(api[1], 401)
        self.assertEqual(api[0].get_json()["code"], "authentication_required")

    def test_only_a_signed_stale_consent_marker_labels_login_as_consent_required(self):
        with self.server.app.test_request_context("/overview", base_url="http://localhost:3333"):
            self.server.session["pending_consent_return"] = "/network?range=30m"
            with patch.object(self.server, "_has_cleanhouse_session", return_value=None):
                response = self.server._require_auth_for_app_pages()
            self.assertEqual(response.headers["Location"], "/login?consent=required")
            self.assertEqual(self.server.session["pending_consent_return"], "/network?range=30m")

    def test_only_health_and_canonical_readiness_are_public_control_routes(self):
        self.assertIsNone(self._evaluate("/health"))
        self.assertIsNone(self._evaluate("/cleanhouse/status?ready=1"))
        self.assertEqual(self._evaluate("/cleanhouse/status")[1], 401)

    def test_disabled_auth_returns_before_importing_auth_service(self):
        with (
            self.server.app.test_request_context("/overview", base_url="http://localhost:3333"),
            patch.object(self.server, "_auth_enabled", return_value=False),
            patch("builtins.__import__", side_effect=AssertionError("auth import must not run")),
        ):
            self.assertIsNone(self.server._require_auth_for_app_pages())

    def test_auth_import_failure_preserves_public_routes_and_protected_fail_closed(self):
        real_import = __import__

        def reject_auth(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "backend.api" and "auth" in fromlist:
                raise ImportError("focused auth import failure")
            return real_import(name, globals, locals, fromlist, level)

        for path, method in (("/health", "GET"), ("/cleanhouse/status?ready=1", "GET"), ("/network", "OPTIONS")):
            with self.subTest(path=path, method=method):
                with (
                    self.server.app.test_request_context(path, method=method, base_url="http://localhost:3333"),
                    patch("builtins.__import__", side_effect=reject_auth),
                ):
                    self.assertIsNone(self.server._require_auth_for_app_pages())

        with (
            self.server.app.test_request_context("/network", base_url="http://localhost:3333"),
            patch.object(self.server, "_has_cleanhouse_session", return_value=None),
            patch("builtins.__import__", side_effect=reject_auth),
        ):
            self.server.session["pending_consent_return"] = "/network"
            protected = self.server._require_auth_for_app_pages()
            self.assertEqual(protected.status_code, 302)
            self.assertEqual(protected.headers["Location"], "/login")
            self.assertNotIn("pending_consent_return", self.server.session)

    def test_stale_consent_can_reach_settings_but_not_antivirus_evidence(self):
        identity = SimpleNamespace(kind="session", consent_current=False)
        self.assertIsNone(self._evaluate("/settings", identity=identity))
        redirected = self._evaluate("/network?range=30m", identity=identity)
        self.assertEqual(redirected.status_code, 302)
        self.assertIn("/network?range=30m&consent=required", redirected.headers["Location"])
        self.assertIn("return_to=%2Fnetwork%3Frange%3D30m", redirected.headers["Location"])
        self.assertIsNone(
            self._evaluate(
                "/network?range=30m&consent=required&return_to=%2Fnetwork%3Frange%3D30m",
                identity=identity,
            )
        )
        blocked = self._evaluate("/cleanhouse/network", identity=identity)
        self.assertEqual(blocked[1], 428)
        self.assertEqual(blocked[0].get_json()["code"], "consent_required")

    def test_dismissal_cannot_unlock_protected_routes(self):
        identity = SimpleNamespace(kind="session", consent_current=False)
        for path in ("/cleanhouse/network", "/cleanhouse/files/snapshot", "/cleanhouse/applications"):
            response = self._evaluate(path, identity=identity)
            self.assertEqual(response[1], 428)
            self.assertEqual(response[0].get_json()["code"], "consent_required")
        reloaded = self._evaluate("/network", identity=identity)
        self.assertEqual(reloaded.status_code, 302)
        self.assertIn("consent=required", reloaded.headers["Location"])

    def test_cookie_mutation_requires_csrf_but_pat_product_operation_does_not(self):
        session_identity = SimpleNamespace(kind="session", consent_current=True)
        pat_identity = SimpleNamespace(kind="api_token", consent_current=True)
        with patch("backend.auth_context.cookie_mutation_allowed", return_value=False):
            blocked = self._evaluate("/cleanhouse/settings", method="POST", identity=session_identity)
        self.assertEqual(blocked[1], 403)
        self.assertIsNone(self._evaluate("/cleanhouse/settings", method="POST", identity=pat_identity))


if __name__ == "__main__":
    unittest.main()
