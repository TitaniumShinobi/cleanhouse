from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify, request, session

from backend import auth_context


class _User:
    def __init__(self, user_id: str = "user-1") -> None:
        self.user_id = user_id
        self.id = user_id
        self.email = "owner@example.test"
        self.full_name = "Owner"
        self.role = "owner"
        self.is_active = True


class AuthContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "auth.sqlite3")
        self.env = patch.dict(
            os.environ,
            {
                "CLEANHOUSE_AUTH_DB": self.db,
                "CLEANHOUSE_AUTH_CONFIG": str(Path(self.temp.name) / "missing-auth-config.json"),
            },
            clear=False,
        )
        self.env.start()
        auth_context.reset_store_cache()
        self.app = Flask(__name__)
        self.app.secret_key = "focused-auth-context"

        @self.app.get("/identity")
        def identity():
            resolved = auth_context.resolve_identity(
                lambda user_id: _User(user_id),
                lambda user_id: user_id == "user-1",
            )
            if not resolved:
                return jsonify({"authenticated": False}), 401
            return jsonify({
                "authenticated": True,
                "kind": resolved.kind,
                "user_id": resolved.user_id,
                "consent_current": resolved.consent_current,
            })

        @self.app.post("/mutation")
        def mutation():
            return jsonify({"allowed": auth_context.cookie_mutation_allowed()})

        @self.app.after_request
        def finalize(response):
            return auth_context.finalize_response(response)

        self.client = self.app.test_client()

    def tearDown(self) -> None:
        auth_context.reset_store_cache()
        self.env.stop()
        self.temp.cleanup()

    def _set_device_cookie(self, value: str) -> None:
        self.client.set_cookie(auth_context.DEVICE_COOKIE, value, domain="localhost")

    def test_opaque_session_survives_store_reopen_and_cookie_never_contains_identity(self):
        issued = auth_context.get_store().issue_session("user-1", auth_method="password")
        self.assertNotIn("user-1", issued.secret)
        self._set_device_cookie(issued.secret)

        first = self.client.get("/identity")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["kind"], "session")

        auth_context.reset_store_cache()
        second = self.client.get("/identity")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["user_id"], "user-1")

    def test_ordinary_parallel_requests_do_not_rotate_and_revoke_the_shared_cookie(self):
        issued_at = datetime.now(timezone.utc) - timedelta(days=2)
        issued = auth_context.get_store().issue_session("user-1", auth_method="password", now=issued_at)
        self._set_device_cookie(issued.secret)

        first = self.client.get("/identity")
        second = self.client.get("/identity")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotIn("Set-Cookie", first.headers)

    def test_legacy_signed_session_migrates_once_to_opaque_cookie(self):
        with self.client.session_transaction() as legacy:
            legacy["user_id"] = "user-1"
            legacy["email"] = "owner@example.test"

        response = self.client.get("/identity")

        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn(auth_context.DEVICE_COOKIE + "=chs_", cookie)
        self.assertIn("HttpOnly", cookie)
        with self.client.session_transaction() as migrated:
            self.assertNotIn("user_id", migrated)
            self.assertNotIn("email", migrated)

    def test_personal_api_token_is_a_separate_identity_and_malformed_bearer_fails_closed(self):
        issued = auth_context.get_store().issue_api_token("user-1", label="automation")
        valid = self.client.get("/identity", headers={"Authorization": f"Bearer {issued.secret}"})
        malformed = self.client.get("/identity", headers={"Authorization": "Bearer not-a-cleanhouse-token"})

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.get_json()["kind"], "api_token")
        self.assertEqual(malformed.status_code, 401)

    def test_cookie_mutation_requires_exact_local_origin_and_csrf(self):
        with self.client.session_transaction() as state:
            state["csrf_token"] = "known-csrf-token"

        with patch.object(
            auth_context.auth_runtime_config,
            "runtime_config",
            return_value={"allowed_origins": ["http://localhost:3333"]},
        ):
            valid = self.client.post(
                "/mutation",
                base_url="http://localhost:3333",
                headers={"Origin": "http://localhost:3333", auth_context.CSRF_HEADER: "known-csrf-token"},
            )
            foreign = self.client.post(
                "/mutation",
                base_url="http://localhost:3333",
                headers={"Origin": "http://evil.invalid", auth_context.CSRF_HEADER: "known-csrf-token"},
            )
            missing = self.client.post(
                "/mutation",
                base_url="http://localhost:3333",
                headers={"Origin": "http://localhost:3333"},
            )

        self.assertTrue(valid.get_json()["allowed"])
        self.assertFalse(foreign.get_json()["allowed"])
        self.assertFalse(missing.get_json()["allowed"])


if __name__ == "__main__":
    unittest.main()
