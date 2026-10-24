from __future__ import annotations

import os
import importlib
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

        with patch("atexit.register"):
            self.server = importlib.import_module("backend.server")

        @self.app.before_request
        def protect_product_page():
            if auth_api.request.path == "/network":
                return self.server._require_auth_for_app_pages()

        @self.app.get("/network")
        def network_page():
            return "network"

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

    def _use_session(self, auth_method: str):
        issued = auth_api.get_store().issue_session(self.service.user.user_id, auth_method=auth_method)
        self.client.set_cookie(auth_context.DEVICE_COOKIE, issued.secret, domain="localhost")
        return issued

    def _prime_stale_consent_return(self, path: str = "/network?range=30m"):
        issued = self._use_session("oauth:google")
        gated = self.client.get(path, base_url="http://localhost:3333")
        self.assertEqual(gated.status_code, 302)
        self.assertIn("consent=required", gated.location)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            self.assertEqual(state["pending_consent_return"], path)
        self.assertTrue(auth_api.get_store().revoke_session(issued.id, self.service.user.user_id))
        return issued

    def _reauth_capabilities(self):
        response = self.client.get("/api/auth/reauth", base_url="http://localhost:3333")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["reauthentication"]

    def test_password_login_issues_opaque_cookie_without_browser_token(self):
        response = self._login()
        payload = response.get_json()
        cookie = response.headers.get("Set-Cookie", "")

        self.assertTrue(payload["success"])
        self.assertNotIn("token", payload)
        self.assertIn("cleanhouse_device_session=chs_", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_reauthentication_capabilities_are_provider_aware(self):
        with patch.dict(os.environ, {"EMAIL_SERVICE": "resend", "FROM_EMAIL": "auth@example.test", "RESEND_API_KEY": "configured"}):
            self._login()
            password_only = self._reauth_capabilities()
            self.assertTrue(password_only["password"]["available"])
            self.assertEqual(password_only["providers"], [])

            auth_api.get_store().bind_external_identity(
                self.service.user.user_id, "google", "google-subject", verified_email=self.service.user.email,
            )
            self._use_session("oauth:google")
            mixed = self._reauth_capabilities()
            self.assertTrue(mixed["password"]["available"])
            self.assertTrue(mixed["verified_email"]["available"])
            self.assertEqual(mixed["providers"][0]["id"], "google")
            self.assertFalse(mixed["providers"][0]["available"])

    def test_google_only_identity_never_offers_or_accepts_password_reauthentication(self):
        with patch.dict(os.environ, {"EMAIL_SERVICE": "resend", "FROM_EMAIL": "auth@example.test", "RESEND_API_KEY": "configured"}):
            auth_api.get_store().bind_external_identity(
                self.service.user.user_id, "google", "google-only-subject", verified_email=self.service.user.email,
            )
            self._use_session("oauth:google")
            capabilities = self._reauth_capabilities()
            self.assertFalse(capabilities["password"]["available"])
            self.assertTrue(capabilities["verified_email"]["available"])
            rejected = self._post(
                "/api/auth/reauth",
                {"method": "password", "password": "correct-password", "scope": "account"},
            )
            self.assertEqual(rejected.status_code, 409)
            self.assertEqual(rejected.get_json()["code"], "REAUTHENTICATION_METHOD_UNAVAILABLE")

    def test_unavailable_provider_and_email_delivery_are_reported_without_fake_method(self):
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "unavailable-subject", verified_email=self.service.user.email,
        )
        self._use_session("oauth:google")
        with patch.dict(os.environ, {"FROM_EMAIL": "", "RESEND_API_KEY": "", "EMAIL_HOST": ""}), patch.object(
            auth_api.auth_runtime_config, "provider_config", return_value={"available": False}
        ):
            capabilities = self._reauth_capabilities()
        self.assertFalse(capabilities["password"]["available"])
        self.assertFalse(capabilities["verified_email"]["available"])
        self.assertFalse(capabilities["providers"][0]["configured"])
        self.assertFalse(capabilities["providers"][0]["available"])

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

    def test_stale_consent_uses_valid_session_without_step_up_and_is_idempotent(self):
        self._use_session("oauth:google")
        before = self.client.get("/api/auth/consent", base_url="http://localhost:3333")
        self.assertEqual(before.status_code, 200)
        self.assertFalse(before.get_json()["current"])
        first = self._post("/api/auth/consent", {"accept_current": True})
        self.assertEqual(first.status_code, 200)
        with auth_api.get_store()._connection() as connection:
            first_count = connection.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0]
        self.assertEqual(first_count, len(auth_api._required_consent_digests()))
        duplicate = self._post("/api/auth/consent", {"accept_current": True})
        self.assertEqual(duplicate.status_code, 200)
        with auth_api.get_store()._connection() as connection:
            duplicate_count = connection.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0]
        self.assertEqual(duplicate_count, first_count)

    def test_expired_session_and_signed_pending_return_are_bounded(self):
        expired = self._post("/api/auth/consent", {"accept_current": True})
        self.assertEqual(expired.status_code, 401)
        with auth_api.get_store()._connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0], 0)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            state["pending_consent_return"] = "/network?range=30m"
        resumed = self._login().get_json()
        self.assertEqual(resumed["return_to"], "/network?range=30m")
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            self.assertNotIn("pending_consent_return", state)
        clean_client = self.app.test_client()
        with clean_client.session_transaction(base_url="http://localhost:3333") as state:
            state["pending_consent_return"] = "//attacker.example/consent"
        rejected = self._post(
            "/api/auth/login",
            {"email": self.service.user.email, "password": "correct-password"},
            client=clean_client,
        ).get_json()
        self.assertNotIn("return_to", rejected)

    def test_protected_stale_consent_return_resumes_once_after_password_login(self):
        self._prime_stale_consent_return()
        expired = self.client.get("/network?range=30m", base_url="http://localhost:3333")
        self.assertEqual(expired.location, "/login?consent=required")
        resumed = self._login().get_json()
        self.assertEqual(resumed["return_to"], "/network?range=30m")
        again = self._login().get_json()
        self.assertNotIn("return_to", again)

    def test_protected_stale_consent_return_resumes_once_after_magic_login(self):
        self._prime_stale_consent_return()
        challenge = auth_api.get_store().issue_magic_challenge(
            self.service.user.email,
            intent="signin",
            purpose="auth_magic:signin",
            origin="http://localhost:3333",
            user_id=self.service.user.user_id,
        )
        resumed = self._post(
            "/api/auth/magic/verify",
            {"token": challenge.secret, "intent": "signin"},
        ).get_json()
        self.assertEqual(resumed["return_to"], "/network?range=30m")
        self.assertEqual(
            auth_api.get_store().consume_magic_challenge(
                challenge.secret,
                purpose="auth_magic:signin",
                origin="http://localhost:3333",
            ).status,
            "replayed",
        )

    def test_protected_stale_consent_return_resumes_once_after_oauth_callback(self):
        self._prime_stale_consent_return()
        now = int(auth_api.datetime.now(auth_api.timezone.utc).timestamp())
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            state["oauth_states"] = {"state-once": {
                "provider": "google",
                "intent": "login",
                "code_verifier": "verified-pkce",
                "created_at": now,
            }}
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "bounded"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "google-subject", "email": self.service.user.email, "name": self.service.user.full_name,
            }),
        ):
            resumed = self.client.get(
                "/api/auth/google/callback?code=once&state=state-once",
                base_url="http://localhost:3333",
            )
        self.assertEqual(resumed.location, "/network?range=30m")
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            self.assertNotIn("pending_consent_return", state)

    def test_oauth_avatar_reaches_authenticated_profile_response(self):
        for provider in ("google", "github"):
            with self.subTest(provider=provider):
                subject = f"{provider}-avatar-subject"
                avatar = (f"https://lh3.googleusercontent.com/a/{subject}" if provider == "google"
                          else f"https://avatars.githubusercontent.com/u/{subject}")
                auth_api.get_store().bind_external_identity(
                    self.service.user.user_id, provider, subject,
                    verified_email=self.service.user.email,
                )
                with self.client.session_transaction(base_url="http://localhost:3333") as state:
                    state["oauth_states"] = {f"{provider}-avatar-state": {
                        "provider": provider,
                        "intent": "login",
                        "code_verifier": "verified-pkce",
                        "created_at": int(auth_api.datetime.now(auth_api.timezone.utc).timestamp()),
                    }}
                with (
                    patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
                    patch.object(auth_api, "get_oauth_user_info", return_value={
                        "id": subject, "email": self.service.user.email,
                        "name": self.service.user.full_name, "avatar_url": avatar,
                    }),
                ):
                    callback = self.client.get(
                        f"/api/auth/{provider}/callback?code=once&state={provider}-avatar-state",
                        base_url="http://localhost:3333",
                    )
                self.assertEqual(callback.status_code, 302)
                self.assertIn("cleanhouse_device_session=chs_", callback.headers.get("Set-Cookie", ""))
                profile = self.client.get("/api/auth/me", base_url="http://localhost:3333")
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.get_json()["user"]["avatar_url"], avatar)
                self.assertEqual(profile.headers["Cache-Control"], "no-store")
                refreshed = self._post("/api/auth/session/refresh", {})
                self.assertEqual(refreshed.status_code, 200)
                after_refresh = self.client.get("/api/auth/me", base_url="http://localhost:3333")
                self.assertEqual(after_refresh.get_json()["user"]["avatar_url"], avatar)

    def test_provider_photo_refresh_updates_existing_session_without_relogin(self):
        issued = self._use_session("oauth:google")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "existing-google-subject",
            verified_email=self.service.user.email,
        )
        before = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(before.get_json()["user"]["avatar_url"], "")
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            started = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.get_json()["authorization_url"].startswith("https://accounts.google.com/"))
        self.assertNotIn("access_type=offline", started.get_json()["authorization_url"])
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, pending)] = state["oauth_states"].items()
            self.assertEqual(pending["intent"], "photo")
            self.assertEqual(pending["user_id"], self.service.user.user_id)
            self.assertEqual(pending["session_id"], issued.id)
        avatar = "https://lh3.googleusercontent.com/a/existing-google-subject"
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "existing-google-subject", "email": self.service.user.email,
                "name": self.service.user.full_name, "avatar_url": avatar,
            }),
        ):
            callback = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
        self.assertEqual(callback.status_code, 302)
        self.assertIn("/settings?settings=providers&photo_refreshed=google", callback.location)
        self.assertNotIn("cleanhouse_device_session", callback.headers.get("Set-Cookie", ""))
        original = auth_api.get_store().validate_session(issued.secret, rotate_if_due=False)
        self.assertEqual(original.status, "valid")
        self.assertEqual(original.record["metadata"]["avatar_url"], avatar)
        profile = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(profile.get_json()["user"]["avatar_url"], avatar)

        refreshed = self._post("/api/auth/session/refresh", {})
        self.assertEqual(refreshed.status_code, 200)
        after_refresh = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(after_refresh.get_json()["user"]["avatar_url"], avatar)

    def test_provider_photo_refresh_updates_only_the_current_password_session(self):
        current = self._use_session("password")
        other_device = auth_api.get_store().issue_session(self.service.user.user_id, auth_method="password")
        other_user = auth_api.get_store().issue_session("another-user", auth_method="oauth:google")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "existing-google-subject",
            verified_email=self.service.user.email,
        )
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            started = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(started.status_code, 200)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, pending)] = state["oauth_states"].items()
            self.assertEqual(pending["session_id"], current.id)
        avatar = "https://lh3.googleusercontent.com/a/existing-google-subject"
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "existing-google-subject", "email": self.service.user.email,
                "avatar_url": avatar,
            }),
        ):
            callback = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
        self.assertIn("photo_refreshed=google", callback.location)
        self.assertNotIn("cleanhouse_device_session", callback.headers.get("Set-Cookie", ""))
        store = auth_api.get_store()
        self.assertEqual(store.validate_session(current.secret, rotate_if_due=False).record["metadata"]["avatar_url"], avatar)
        self.assertNotIn("avatar_url", store.validate_session(other_device.secret, rotate_if_due=False).record["metadata"])
        self.assertNotIn("avatar_url", store.validate_session(other_user.secret, rotate_if_due=False).record["metadata"])
        profile = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(profile.get_json()["user"]["avatar_url"], avatar)
        refreshed = self._post("/api/auth/session/refresh", {})
        self.assertEqual(refreshed.status_code, 200)
        after_refresh = self.client.get("/api/auth/me", base_url="http://localhost:3333")
        self.assertEqual(after_refresh.get_json()["user"]["avatar_url"], avatar)

    def test_cancelled_photo_refresh_keeps_session_and_returns_to_settings(self):
        current = self._use_session("password")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "existing-google-subject",
            verified_email=self.service.user.email,
        )
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            self.assertEqual(self._post("/api/auth/oauth/google?intent=photo", {}).status_code, 200)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, _)] = state["oauth_states"].items()
        with patch.object(auth_api, "exchange_oauth_token") as exchange:
            cancelled = self.client.get(
                f"/api/auth/google/callback?error=access_denied&state={oauth_state}",
                base_url="http://localhost:3333",
            )
            replay = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
            exchange.assert_not_called()
        self.assertEqual(cancelled.location, "/settings?settings=providers&error=photo_denied")
        self.assertEqual(replay.location, "/login?error=invalid_state")
        self.assertEqual(auth_api.get_store().validate_session(current.secret, rotate_if_due=False).status, "valid")

    def test_photo_refresh_cannot_connect_or_use_a_different_provider_identity(self):
        issued = self._use_session("oauth:google")
        missing = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.get_json()["code"], "PROVIDER_NOT_CONNECTED")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "original-subject",
            verified_email=self.service.user.email,
        )
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            started = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(started.status_code, 200)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, _)] = state["oauth_states"].items()
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "different-subject", "email": self.service.user.email,
                "avatar_url": "https://lh3.googleusercontent.com/a/different-subject",
            }),
        ):
            callback = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
        self.assertIn("error=photo_identity_mismatch", callback.location)
        self.assertIsNone(auth_api.get_store().external_identity("google", "different-subject"))
        self.assertEqual(auth_api.get_store().validate_session(issued.secret, rotate_if_due=False).status, "valid")
        self.assertEqual(self.client.get("/api/auth/me", base_url="http://localhost:3333").get_json()["user"]["avatar_url"], "")

    def test_photo_refresh_callback_requires_the_original_device_session(self):
        original = self._use_session("oauth:google")
        auth_api.get_store().bind_external_identity(
            self.service.user.user_id, "google", "same-subject",
            verified_email=self.service.user.email,
        )
        with patch.object(auth_api.auth_runtime_config, "provider_config", return_value={
            "enabled": True, "available": True, "client_id": "fixture-client",
        }):
            started = self._post("/api/auth/oauth/google?intent=photo", {})
        self.assertEqual(started.status_code, 200)
        with self.client.session_transaction(base_url="http://localhost:3333") as state:
            [(oauth_state, _)] = state["oauth_states"].items()
        replacement = auth_api.get_store().issue_session(self.service.user.user_id, auth_method="oauth:google")
        self.client.set_cookie(auth_context.DEVICE_COOKIE, replacement.secret, domain="localhost")
        with (
            patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "fixture-token"}),
            patch.object(auth_api, "get_oauth_user_info", return_value={
                "id": "same-subject", "email": self.service.user.email,
                "avatar_url": "https://lh3.googleusercontent.com/a/same-subject",
            }),
        ):
            callback = self.client.get(
                f"/api/auth/google/callback?code=once&state={oauth_state}",
                base_url="http://localhost:3333",
            )
        self.assertIn("error=photo_identity_mismatch", callback.location)
        self.assertEqual(auth_api.get_store().validate_session(original.secret, rotate_if_due=False).record["metadata"].get("avatar_url"), None)
        self.assertEqual(auth_api.get_store().validate_session(replacement.secret, rotate_if_due=False).record["metadata"].get("avatar_url"), None)

    def test_untrusted_avatar_url_is_not_added_to_sessions(self):
        self.assertEqual(auth_api._oauth_avatar_url("google", "http://lh3.googleusercontent.com/a/a"), "")
        self.assertEqual(auth_api._oauth_avatar_url("google", "https://localhost/private"), "")
        self.assertEqual(auth_api._oauth_avatar_url("github", "https://lh3.googleusercontent.com/a/a"), "")

    def test_local_return_validator_rejects_unsafe_and_loop_targets(self):
        unsafe = [
            "//attacker.example/path",
            "/\\attacker.example/path",
            "/%2fattacker.example/path",
            "/%5cattacker.example/path",
            "/safe%0apath",
            "/login",
            "/login/",
            "/login/?next=/network",
            "/login%2f?next=/network",
            "/signup?next=/network",
            "/signup/",
            "/signup%2f",
            "/safe/../login",
            "/" + ("a" * 2048),
        ]
        for candidate in unsafe:
            with self.subTest(candidate=candidate[:80]):
                self.assertEqual(auth_api.validate_local_return(candidate), "")
        self.assertEqual(
            auth_api.validate_local_return("/network?range=30m#active"),
            "/network?range=30m#active",
        )
        self.assertEqual(auth_api.validate_local_return("/..example"), "/..example")

    def test_consent_never_invokes_reauth_for_magic_or_mfa_sessions(self):
        for method in ("magic_email", "mfa"):
            client = self.app.test_client()
            issued = auth_api.get_store().issue_session(self.service.user.user_id, auth_method=method)
            client.set_cookie(auth_context.DEVICE_COOKIE, issued.secret, domain="localhost")
            with patch.object(auth_api, "_require_sensitive") as sensitive:
                accepted = self._post("/api/auth/consent", {"accept_current": True}, client=client)
                self.assertEqual(accepted.status_code, 200)
                sensitive.assert_not_called()

    def test_mfa_auth_method_does_not_override_independent_password_capability(self):
        auth_api.get_store().issue_session(self.service.user.user_id, auth_method="password")
        self._use_session("mfa")
        capabilities = self._reauth_capabilities()
        self.assertTrue(capabilities["password"]["available"])

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
            _Response({"id": 7, "login": "owner", "avatar_url": "https://avatars.githubusercontent.com/u/7"}),
            _Response([{"email": "owner@example.test", "primary": True, "verified": True}]),
        ]
        with patch.object(auth_api.requests, "get", side_effect=verified):
            result = auth_api.get_oauth_user_info("github", "provider-token")
        self.assertEqual(result["id"], "7")
        self.assertEqual(result["email"], "owner@example.test")
        self.assertEqual(result["avatar_url"], "https://avatars.githubusercontent.com/u/7")

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


if __name__ == "__main__":
    unittest.main()
