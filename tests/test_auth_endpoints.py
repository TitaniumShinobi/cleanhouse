from __future__ import annotations

import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify

from backend import auth_context
from backend.api import auth as auth_api


class _User:
    def __init__(self, user_id: str = "user-1", email: str = "owner@example.test") -> None:
        self.user_id = user_id
        self.id = user_id
        self.email = email
        self.full_name = "CleanHouse Owner"
        self.role = "owner"
        self.is_active = True
        self.last_login = None


class _UserService:
    def __init__(self) -> None:
        self.user = _User()

    def authenticate_user(self, email, password):
        return self.user if email == self.user.email and password == "correct-password" else None

    def get_user_by_id(self, user_id=None, **_kwargs):
        return self.user if str(user_id) == self.user.user_id else None

    def get_user_by_email(self, email):
        return self.user if str(email).lower() == self.user.email else None


class _LegacyUserService(_UserService):
    def __init__(self) -> None:
        self.user = _User("7")

    def get_user_by_id(self, user_id=None, legacy_id=None, **_kwargs):
        if legacy_id == 7:
            return self.user
        return None


class AuthEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "CLEANHOUSE_AUTH_DB": str(Path(self.temp.name) / "auth.sqlite3"),
                "CLEANHOUSE_PUBLIC_ORIGIN": "http://localhost:3333",
                "CLEANHOUSE_TURNSTILE_REQUIRED": "0",
            },
            clear=False,
        )
        self.env.start()
        auth_context.reset_store_cache()
        auth_api._magic_rate_events.clear()
        auth_api._login_rate_events.clear()
        self.service = _UserService()
        self.service_patch = patch.object(auth_api, "get_user_service", return_value=self.service)
        self.service_patch.start()
        self.report_patch = patch.object(auth_api, "_build_login_report_payload", return_value={"status": "ok"})
        self.report_patch.start()

        self.app = Flask(__name__)
        self.app.secret_key = "focused-auth-endpoints"
        self.app.register_blueprint(auth_api.bp, url_prefix="/api")

        @self.app.get("/product")
        def product():
            identity = auth_api._current_identity(allow_api_token=True)
            if not identity or not identity.consent_current:
                return jsonify({"success": False}), 401
            return jsonify({"success": True, "kind": identity.kind, "user_id": identity.user_id})

        @self.app.after_request
        def finalize(response):
            return auth_context.finalize_response(response)

        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.report_patch.stop()
        self.service_patch.stop()
        auth_context.reset_store_cache()
        auth_api._magic_rate_events.clear()
        auth_api._login_rate_events.clear()
        self.env.stop()
        self.temp.cleanup()

    def test_current_user_resolves_legacy_sqlite_identity_from_device_session(self):
        self.service = _LegacyUserService()
        auth_api.get_user_service.return_value = self.service
        issued = auth_context.get_store().issue_session("7", auth_method="password")
        self.client.set_cookie(auth_context.DEVICE_COOKIE, issued.secret, domain="localhost")

        response = self.client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["id"], "7")

    def test_denied_callback_requires_and_consumes_state(self):
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            state["oauth_states"] = {"once": {"provider": "github", "code_verifier": "fixture-verifier",
                "created_at": int(auth_api.datetime.now(auth_api.timezone.utc).timestamp())}}
        path = "/api/auth/github/callback?error=access_denied&state=once"
        with patch.object(auth_api, "exchange_oauth_token") as exchange:
            first = self.client.get(path, base_url="http://localhost:3333")
            second = self.client.get(path, base_url="http://localhost:3333")
            self.assertEqual(first.location, "/login?error=access_denied")
            self.assertEqual(second.location, "/login?error=invalid_state")
            exchange.assert_not_called()

    def test_denial_without_state_cannot_complete_callback(self):
        response = self.client.get("/api/auth/github/callback?error=access_denied", base_url="http://localhost:3333")
        self.assertEqual(response.location, "/login?error=invalid_callback")

    def test_state_budget_preserves_authenticated_link_and_signup_bindings(self):
        now = int(auth_api.datetime.now(auth_api.timezone.utc).timestamp())
        state = {"once": {"provider": "github", "code_verifier": "fixture-verifier", "created_at": now,
                         "intent": "link", "user_id": "owner-fixture", "consent": {"terms": "version"}}}
        bounded = auth_api._bounded_oauth_states(state)["once"]
        self.assertEqual(bounded["user_id"], "owner-fixture")
        self.assertEqual(bounded["intent"], "link")
        self.assertEqual(bounded["consent"], {"terms": "version"})

    def _csrf(self, client=None) -> str:
        response = (client or self.client).get("/api/auth/csrf", base_url="http://localhost:3333")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrfToken"]

    def _post(self, path: str, payload: dict, *, client=None, csrf=None, headers=None):
        active = client or self.client
        merged = {"Origin": "http://localhost:3333", "X-CSRF-Token": csrf or self._csrf(active)}
        merged.update(headers or {})
        return active.post(path, json=payload, headers=merged, base_url="http://localhost:3333")

    def _login(self):
        response = self._post(
            "/api/auth/login",
            {"email": self.service.user.email, "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response

    def _accept_consent(self):
        response = self._post("/api/auth/consent", {"accept_current": True})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_password_login_issues_opaque_cookie_without_browser_token(self):
        response = self._login()
        payload = response.get_json()
        cookie = response.headers.get("Set-Cookie", "")

        self.assertTrue(payload["success"])
        self.assertNotIn("token", payload)
        self.assertIn("cleanhouse_device_session=chs_", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_password_login_rejects_missing_and_forged_csrf(self):
        payload = {"email": self.service.user.email, "password": "correct-password"}
        missing = self.client.post(
            "/api/auth/login",
            json=payload,
            headers={"Origin": "http://localhost:3333"},
            base_url="http://localhost:3333",
        )
        self._csrf()
        forged = self.client.post(
            "/api/auth/login",
            json=payload,
            headers={"Origin": "http://localhost:3333", "X-CSRF-Token": "forged"},
            base_url="http://localhost:3333",
        )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(missing.get_json()["code"], "CSRF_FAILED")
        self.assertEqual(forged.get_json()["code"], "CSRF_FAILED")

    def test_consent_receipts_gate_personal_token_and_pat_operates_product_only(self):
        self._login()
        before = self.client.get("/api/auth/consent", base_url="http://localhost:3333").get_json()
        self.assertFalse(before["current"])
        self._accept_consent()

        grant_response = self._post(
            "/api/auth/reauth",
            {"password": "correct-password", "scope": "token_manage"},
        )
        grant = grant_response.get_json()["reauthToken"]
        created = self._post(
            "/api/auth/tokens",
            {"label": "local automation", "expires_in_days": 30},
            headers={"X-CleanHouse-Reauth": grant},
        )
        self.assertEqual(created.status_code, 200)
        raw = created.get_json()["token"]
        self.assertTrue(raw.startswith("chpat_"))

        listed = self.client.get("/api/auth/tokens", base_url="http://localhost:3333").get_json()
        self.assertNotIn("token", listed["tokens"][0])
        product = self.app.test_client().get(
            "/product",
            headers={"Authorization": f"Bearer {raw}"},
            base_url="http://localhost:3333",
        )
        self.assertEqual(product.status_code, 200)
        self.assertEqual(product.get_json()["kind"], "api_token")
        self.assertEqual(
            self.app.test_client().get(
                "/api/auth/tokens",
                headers={"Authorization": f"Bearer {raw}"},
                base_url="http://localhost:3333",
            ).status_code,
            401,
        )

    def test_refresh_is_atomic_and_replayed_old_cookie_fails(self):
        self._login()
        old = self.client.get_cookie(auth_context.DEVICE_COOKIE).value
        csrf = self._csrf()
        refreshed = self._post("/api/auth/session/refresh", {}, csrf=csrf)
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(self.client.get_cookie(auth_context.DEVICE_COOKIE).value, old)

        replay = self.app.test_client()
        replay.set_cookie(auth_context.DEVICE_COOKIE, old, domain="localhost")
        self.assertEqual(replay.get("/api/auth/me", base_url="http://localhost:3333").status_code, 401)

    def test_magic_signin_requires_post_and_is_single_use(self):
        captured = {}

        def deliver(_email, *, subject, text):
            captured["subject"] = subject
            captured["text"] = text

        with patch.object(auth_api, "deliver_auth_email", side_effect=deliver):
            requested = self._post(
                "/api/auth/magic/request",
                {"email": self.service.user.email, "intent": "signin"},
            )
        self.assertEqual(requested.status_code, 200)
        link = next(part for part in captured["text"].split() if part.startswith("http://"))
        fragment = urllib.parse.parse_qs(urllib.parse.urlsplit(link).fragment)
        token = fragment["token"][0]

        first = self._post("/api/auth/magic/verify", {"token": token, "intent": "signin"})
        second = self._post("/api/auth/magic/verify", {"token": token, "intent": "signin"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)

    def test_recovery_mutations_require_exact_origin_and_csrf(self):
        denied = self.client.post(
            "/api/auth/recovery/request",
            json={"email": "missing@example.test"},
            base_url="http://localhost:3333",
        )
        self.assertEqual(denied.status_code, 403)
        allowed = self._post(
            "/api/auth/recovery/request",
            {"email": "missing@example.test"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertNotIn("missing@example.test", allowed.get_data(as_text=True))

    def test_magic_request_rate_limit_uses_only_bounded_digests(self):
        decisions = [
            auth_api._magic_request_rate_allowed("owner@example.test", "signin", "127.0.0.1")
            for _ in range(6)
        ]
        self.assertEqual(decisions, [True, True, True, True, True, False])
        self.assertTrue(all("owner@example.test" not in key and "127.0.0.1" not in key for key in auth_api._magic_rate_events))

    def test_password_rate_limit_is_bounded_hashed_and_explicit(self):
        decisions = [
            auth_api._password_attempt_rate_allowed("owner@example.test", "127.0.0.1")
            for _ in range(11)
        ]
        self.assertEqual(decisions, ([True] * 10) + [False])
        self.assertTrue(all("owner@example.test" not in key and "127.0.0.1" not in key for key in auth_api._login_rate_events))

        auth_api._login_rate_events.clear()
        for _ in range(10):
            response = self._post(
                "/api/auth/login",
                {"email": self.service.user.email, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)
        limited = self._post(
            "/api/auth/login",
            {"email": self.service.user.email, "password": "wrong-password"},
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.get_json()["code"], "RATE_LIMITED")

    def test_successful_password_signin_clears_failure_counters(self):
        for _ in range(9):
            response = self._post(
                "/api/auth/login",
                {"email": self.service.user.email, "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)
        self.assertEqual(
            self._post(
                "/api/auth/login",
                {"email": self.service.user.email, "password": "correct-password"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self._post(
                "/api/auth/login",
                {"email": self.service.user.email, "password": "wrong-password"},
            ).status_code,
            401,
        )

    def test_magic_delivery_failure_revokes_challenge_without_disclosing_eligibility(self):
        issued = {}
        original = auth_api.get_store().issue_magic_challenge

        def capture(*args, **kwargs):
            credential = original(*args, **kwargs)
            issued["credential"] = credential
            return credential

        with patch.object(auth_api.get_store(), "issue_magic_challenge", side_effect=capture), patch.object(
            auth_api, "deliver_auth_email", side_effect=RuntimeError("delivery unavailable")
        ):
            response = self._post(
                "/api/auth/magic/request",
                {"email": self.service.user.email, "intent": "signin"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.service.user.email, response.get_data(as_text=True))
        result = auth_api.get_store().consume_magic_challenge(
            issued["credential"].secret,
            purpose="auth_magic:signin",
            origin="http://localhost:3333",
        )
        self.assertEqual(result.status, "revoked")

    def test_magic_reauthentication_is_session_scope_bound_and_single_use(self):
        self._login()
        captured = {}

        def deliver(_email, *, subject, text):
            captured["subject"] = subject
            captured["text"] = text

        with patch.object(auth_api, "deliver_auth_email", side_effect=deliver):
            requested = self._post(
                "/api/auth/reauth",
                {"method": "magic_email_request", "scope": "session_manage"},
            )
        self.assertEqual(requested.status_code, 200)
        link = next(part for part in captured["text"].split() if part.startswith("http://"))
        fragment = urllib.parse.parse_qs(urllib.parse.urlsplit(link).fragment)
        token = fragment["reauth"][0]

        wrong_scope = self._post(
            "/api/auth/reauth",
            {"method": "magic_email_verify", "scope": "account", "token": token},
        )
        self.assertEqual(wrong_scope.status_code, 401)
        verified = self._post(
            "/api/auth/reauth",
            {"method": "magic_email_verify", "scope": "session_manage", "token": token},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertTrue(verified.get_json()["reauthToken"].startswith("chr_"))
        replay = self._post(
            "/api/auth/reauth",
            {"method": "magic_email_verify", "scope": "session_manage", "token": token},
        )
        self.assertEqual(replay.status_code, 401)

    def test_github_start_uses_exact_callback_state_and_s256_pkce(self):
        provider = {
            "enabled": True,
            "available": True,
            "client_id": "public-client-id",
            "client_secret": "withheld-secret",
            "callback_url": "http://localhost:3333/api/auth/github/callback",
        }
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value=provider), patch.object(
            auth_api, "generate_pkce", return_value=("verifier", "challenge")
        ):
            response = self.client.get(
                "/api/auth/oauth/github?intent=login",
                base_url="http://localhost:3333",
            )
        self.assertEqual(response.status_code, 302)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers["Location"]).query)
        self.assertEqual(query["redirect_uri"], ["http://localhost:3333/api/auth/github/callback"])
        self.assertEqual(query["code_challenge"], ["challenge"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["scope"], ["read:user user:email"])
        self.assertNotIn("client_secret", query)

    def test_provider_specific_callback_rejects_cross_provider_state(self):
        with self.client.session_transaction() as state:
            state["oauth_states"] = {
                "state-token": {
                    "provider": "google",
                    "intent": "login",
                    "code_verifier": "verifier",
                    "created_at": int(__import__("time").time()),
                }
            }
        with patch.object(auth_api, "exchange_oauth_token") as exchange:
            response = self.client.get(
                "/api/auth/github/callback?code=provider-code&state=state-token",
                base_url="http://localhost:3333",
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login?error=invalid_state"))
        exchange.assert_not_called()

    def test_github_email_resolution_requires_primary_and_verified(self):
        class _Response:
            def __init__(self, payload):
                self.status_code = 200
                self.content = b"{}"
                self._payload = payload

            def json(self):
                return self._payload

        unverified = [
            _Response({"id": 7, "login": "owner"}),
            _Response([{"email": "owner@example.test", "primary": True, "verified": False}]),
        ]
        with patch.object(auth_api.requests, "get", side_effect=unverified):
            self.assertIsNone(auth_api.get_oauth_user_info("github", "provider-token"))

        verified = [
            _Response({"id": 7, "login": "owner"}),
            _Response([{"email": "owner@example.test", "primary": True, "verified": True}]),
        ]
        with patch.object(auth_api.requests, "get", side_effect=verified):
            result = auth_api.get_oauth_user_info("github", "provider-token")
        self.assertEqual(result["id"], "7")
        self.assertEqual(result["email"], "owner@example.test")
        self.assertEqual(result["avatar_url"], "")

    def test_google_picture_is_mapped_to_oauth_avatar(self):
        class _Response:
            status_code = 200
            content = b"{}"

            def json(self):
                return {"id": "google-subject", "email": "owner@example.test",
                        "picture": "https://lh3.googleusercontent.com/a/owner"}

        with patch.object(auth_api.requests, "get", return_value=_Response()):
            result = auth_api.get_oauth_user_info("google", "provider-token")
        self.assertEqual(result["avatar_url"], "https://lh3.googleusercontent.com/a/owner")

    def test_photo_refresh_updates_current_authenticated_session(self):
        issued = auth_api.get_store().issue_session(self.service.user.user_id, auth_method="password")
        self.client.set_cookie(auth_context.DEVICE_COOKIE, issued.secret, domain="localhost")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "google-subject", verified_email=self.service.user.email,
        )
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            started = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(started.status_code, 200)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, pending)] = state["oauth_states"].items()
            self.assertEqual(pending["session_id"], issued.id)
        avatar = "https://lh3.googleusercontent.com/a/owner"
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "google-subject", "email": self.service.user.email, "avatar_url": avatar,
            }),
        ):
            callback = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
        self.assertIn("photo_refreshed=google", callback.location)
        profile = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(profile.get_json()["user"]["avatar_url"], avatar)

    def test_avatar_url_accepts_only_expected_https_provider_hosts(self):
        self.assertEqual(
            auth_api._oauth_avatar_url("google", "https://lh3.googleusercontent.com/a/owner"),
            "https://lh3.googleusercontent.com/a/owner",
        )
        self.assertEqual(auth_api._oauth_avatar_url("google", "http://lh3.googleusercontent.com/a/owner"), "")
        self.assertEqual(auth_api._oauth_avatar_url("google", "https://localhost/private"), "")


if __name__ == "__main__":
    unittest.main()
