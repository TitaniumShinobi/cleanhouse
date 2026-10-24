import sys
import types
import unittest
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch


if "flask" not in sys.modules:
    flask_module = types.ModuleType("flask")
    sys.modules["flask"] = flask_module
else:
    flask_module = sys.modules["flask"]


def _dummy_route(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


def _dummy_after_request(func=None):
    def decorator(wrapper):
        return wrapper

    if func is None:
        return decorator
    return func


if not hasattr(flask_module, "Blueprint"):
    class _Blueprint:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return _dummy_route(*args, **kwargs)

        def after_request(self, *args, **kwargs):
            if args and callable(args[0]):
                return args[0]
            return _dummy_after_request(*args, **kwargs)

    flask_module.Blueprint = _Blueprint

if not hasattr(flask_module, "jsonify"):
    flask_module.jsonify = lambda obj=None, **kwargs: obj if obj is not None else kwargs
if not hasattr(flask_module, "Response"):
    flask_module.Response = lambda payload="", mimetype=None, **kwargs: {"payload": payload, "mimetype": mimetype, **kwargs}
if not hasattr(flask_module, "send_file"):
    flask_module.send_file = lambda path, mimetype=None, **kwargs: {"path": path, "mimetype": mimetype, **kwargs}
if not hasattr(flask_module, "redirect"):
    flask_module.redirect = lambda value: value
if not hasattr(flask_module, "url_for"):
    flask_module.url_for = lambda endpoint: endpoint
if not hasattr(flask_module, "abort"):
    def _abort(status, description=None):
        raise RuntimeError(description or f"abort {status}")
    flask_module.abort = _abort
if not hasattr(flask_module, "session"):
    flask_module.session = {}


if not hasattr(flask_module, "request"):
    flask_module.request = types.SimpleNamespace(
        get_json=lambda silent=True: None,
        headers={},
        form={},
        method="GET",
    )

if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")
    requests_module.post = lambda *args, **kwargs: None
    requests_module.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_module

if "jwt" not in sys.modules:
    jwt_module = types.ModuleType("jwt")

    class _JwtError(Exception):
        pass

    jwt_module.ExpiredSignatureError = _JwtError
    jwt_module.InvalidTokenError = _JwtError
    jwt_module.encode = lambda payload, secret, algorithm=None: "stub-jwt"
    jwt_module.decode = lambda token, secret, algorithms=None: {}
    sys.modules["jwt"] = jwt_module

import backend.api.auth as auth_api


class AuthApiValidationTests(unittest.TestCase):
    def setUp(self):
        self._original_request = auth_api.request
        self._original_session = auth_api.session
        self._original_context_request = auth_api.auth_context.request
        self._original_context_session = auth_api.auth_context.session
        self._original_context_g = auth_api.auth_context.g
        class _Session(dict):
            modified = False

        self.session = _Session()
        auth_api.session = self.session
        request = types.SimpleNamespace(
            get_json=lambda silent=True: None,
            headers={},
            cookies={},
            form={},
            method="GET",
            remote_addr="127.0.0.1",
        )
        auth_api.request = request
        auth_api.auth_context.request = request
        auth_api.auth_context.session = self.session
        auth_api.auth_context.g = types.SimpleNamespace()

    def tearDown(self):
        auth_api.request = self._original_request
        auth_api.session = self._original_session
        auth_api.auth_context.request = self._original_context_request
        auth_api.auth_context.session = self._original_context_session
        auth_api.auth_context.g = self._original_context_g

    def _set_request_json(self, payload):
        request = types.SimpleNamespace(
            get_json=lambda silent=True: payload,
            headers={},
            cookies={},
            form={},
            method="POST",
            remote_addr="127.0.0.1",
        )
        auth_api.request = request
        auth_api.auth_context.request = request

    def _set_request_headers(self, headers):
        request = types.SimpleNamespace(
            get_json=lambda silent=True: None,
            headers=headers,
            cookies={},
            form={},
            method="GET",
            remote_addr="127.0.0.1",
        )
        auth_api.request = request
        auth_api.auth_context.request = request

    def _cleanhouse_consent(self):
        return {
            "cleanhouse:terms": True,
            "cleanhouse:privacy": True,
            "cleanhouse:eeccd": True,
        }

    def _assert_bad_request(self, response, expected_reason):
        self.assertIsInstance(response, tuple, response)
        body, status = response
        self.assertEqual(status, 400, response)
        self.assertIn(expected_reason, body.get("message", ""))

    def test_create_account_rejects_non_json_body(self):
        self._set_request_json("bad")
        response = auth_api.create_account()
        self._assert_bad_request(response, "JSON object")

    def test_create_account_rejects_wrong_type_payload(self):
        self._set_request_json({
            "email": 1,
            "password": 2,
            "fullName": "Ada",
            "role": "user",
            "consent": self._cleanhouse_consent(),
        })
        response = auth_api.create_account()
        self._assert_bad_request(response, "must be a string")

    def test_login_rejects_non_json_body(self):
        self._set_request_json(["bad"])
        response = auth_api.login()
        self._assert_bad_request(response, "JSON object")

    def test_auth_config_reports_resolved_provider_availability(self):
        with patch.object(auth_api.auth_runtime_config, "public_config_payload", return_value={
            "providers": [{
                "provider": "google",
                "label": "Continue with Google",
                "enabled": True,
                "available": False,
            }]
        }):
            response = auth_api.auth_config()
        self.assertFalse(response["data"]["providers"][0]["available"])

    def test_unconfigured_google_redirects_to_intentional_login_error(self):
        auth_api.request = types.SimpleNamespace(
            method="GET", args={}, form={}, headers={}, host_url="http://localhost:3333/"
        )
        with patch.object(auth_api, "_oauth_redirect_uri", return_value="http://localhost:3333/api/auth/google/callback"), patch.object(
            auth_api.auth_runtime_config,
            "provider_config",
            return_value={"enabled": True, "available": False},
        ):
            response = auth_api.oauth("google")
        self.assertEqual(response, "/login?error=provider_unavailable&provider=google")

    def test_oauth_start_redirects_to_callback_origin_before_creating_state(self):
        auth_api.request = types.SimpleNamespace(
            method="GET", args={}, form={}, headers={}, host_url="http://127.0.0.1:3333/"
        )
        with patch.object(auth_api, "_oauth_redirect_uri", return_value="http://localhost:3333/api/auth/google/callback"):
            response = auth_api.oauth("google")

        self.assertEqual(response, "http://localhost:3333/api/auth/oauth/google")
        self.assertNotIn("oauth_states", self.session)

    def test_oauth_start_bounds_pending_cookie_state(self):
        auth_api.request = types.SimpleNamespace(
            method="GET", args={}, form={}, headers={}, host_url="http://localhost:3333/"
        )
        states = [f"state-{index}" for index in range(8)]
        with patch.object(
            auth_api.auth_runtime_config,
            "provider_config",
            return_value={
                "enabled": True,
                "available": True,
                "client_id": "client-id",
                "callback_url": "http://localhost:3333/api/auth/google/callback",
            },
        ), patch.object(
            auth_api, "generate_pkce", return_value=("verifier", "challenge")
        ), patch.object(auth_api.secrets, "token_urlsafe", side_effect=states):
            for _ in states:
                auth_api.oauth("google")

        self.assertEqual(list(self.session["oauth_states"]), states[-4:][::-1])
        self.assertLess(len(json.dumps(self.session)), 4093)

    def test_oauth_callback_keeps_only_compact_login_report_reference(self):
        class _User:
            id = "user-1"
            user_id = "user-1"
            email = "user@example.com"
            full_name = "Clean User"
            role = "user"
            last_login = None

        self.session["oauth_states"] = {
            "valid": {
                "provider": "google",
                "code_verifier": "verifier",
                "created_at": 9_999_999_999,
            }
        }
        auth_api.request = types.SimpleNamespace(
            method="GET", args={"code": "code", "state": "valid"}, form={}, headers={}
        )
        service = type("S", (), {
            "get_user_by_email": lambda self, email: _User(),
            "_update_last_login": lambda self, user_id: None,
            "user_registry": None,
        })()
        report = {"id": "report:oauth", "evidence_refs": ["x" * 256] * 40}

        with patch.object(auth_api, "exchange_oauth_token", return_value={"access_token": "provider-token"}), patch.object(
            auth_api, "get_oauth_user_info", return_value={"id": "provider-fixture", "email": "user@example.com", "name": "Clean User"}
        ), patch.object(auth_api, "get_user_service", return_value=service), patch.object(
            auth_api, "_build_login_report_payload", return_value=report
        ):
            store = types.SimpleNamespace(external_identity=lambda *a: None, bind_external_identity=lambda *a, **kw: None,
                                          issue_session=lambda *a, **kw: types.SimpleNamespace(secret="synthetic-session"))
            with patch.object(auth_api, "get_store", return_value=store):
                response = auth_api.oauth_callback()

        self.assertEqual(response, "/overview")
        self.assertNotIn("oauth_login_report", self.session)
        self.assertNotIn("evidence_refs", json.dumps(self.session))
        self.assertLess(len(json.dumps(self.session)), 4093)

    def test_obsolete_desktop_token_endpoint_is_removed(self):
        self.assertFalse(hasattr(auth_api, "launch_desktop"))

    def test_oauth_callback_rejects_and_consumes_expired_state(self):
        self.session["oauth_states"] = {
            "expired": {"provider": "google", "code_verifier": "verifier", "created_at": 0}
        }
        auth_api.request = types.SimpleNamespace(
            method="GET", args={"code": "code", "state": "expired"}, form={}, headers={}
        )

        response = auth_api.oauth_callback()

        self.assertEqual(response, "/login?error=expired_state")
        self.assertNotIn("expired", self.session["oauth_states"])

    def test_oauth_callback_replay_fails_after_one_time_state_consumption(self):
        self.session["oauth_states"] = {
            "once": {"provider": "google", "code_verifier": "", "created_at": 9_999_999_999}
        }
        auth_api.request = types.SimpleNamespace(
            method="GET", args={"code": "code", "state": "once"}, form={}, headers={}
        )

        first = auth_api.oauth_callback()
        second = auth_api.oauth_callback()

        self.assertEqual(first, "/login?error=invalid_state")
        self.assertEqual(second, "/login?error=invalid_state")

    def test_me_rejects_invalid_authorization_header(self):
        self._set_request_headers({"Authorization": "bad header"})
        response = auth_api.get_current_user()
        self.assertIsInstance(response, tuple)
        body, status = response
        self.assertEqual(status, 401)
        self.assertIn("Invalid or expired", body.get("message", ""))

    def test_login_accepts_valid_payload(self):
        class _User:
            id = "user-1"
            user_id = "user-1"
            email = "user@example.com"
            full_name = "Clean User"
            role = "user"
            last_login = None

        self._set_request_json({"email": "user@example.com", "password": "pass", "fullName": "Clean User"})

        with patch.object(auth_api, "get_user_service") as get_user_service, patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ), patch.object(
            auth_api, "_issue_session_response", side_effect=lambda user, payload, **kwargs: payload
        ), patch.object(
            auth_api, "_consent_payload_for", return_value={"current": False, "missing": []}
        ), patch.object(auth_api, "_build_login_report_payload", return_value={"status": "ok", "id": "report:login"}):
            get_user_service.return_value = type("S", (), {"authenticate_user": lambda self, email, password: _User()})()
            response = auth_api.login()

        self.assertIsInstance(response, (dict, tuple))
        if isinstance(response, tuple):
            self.assertEqual(response[1], 200)
            response_body = response[0]
        else:
            response_body = response
        self.assertTrue(response_body.get("success"))
        self.assertEqual(response_body.get("login_report", {}).get("id"), "report:login")
        self.assertNotIn("token", response_body)
        self.assertNotIn("user_id", self.session)

    def test_logout_clears_session(self):
        class _Response(dict):
            def __init__(self, payload):
                super().__init__(payload)
                self.headers = {}

        self.session.update({"user_id": "user-1", "email": "user@example.com"})
        with tempfile.TemporaryDirectory() as root, patch.object(auth_api.Path, "home", return_value=Path(root)), patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ), patch.object(auth_api, "_current_identity", return_value=None), patch.object(
            auth_api, "jsonify", side_effect=lambda payload: _Response(payload)
        ):
            response = auth_api.logout()
        self.assertTrue(response.get("success"))
        self.assertEqual(self.session, {})

    def test_recovery_request_is_enumeration_resistant(self):
        self._set_request_json({"email": "missing@example.com"})
        service = type("S", (), {"get_user_by_email": lambda self, email: None})()
        with patch.object(auth_api, "get_user_service", return_value=service), patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ):
            response = auth_api.request_recovery()
        self.assertTrue(response.get("success"))

    def test_reset_requires_valid_single_use_token(self):
        self._set_request_json({"token": "expired", "password": "new-password"})
        with patch.object(auth_api, "consume_recovery", return_value=None), patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ):
            body, status = auth_api.reset_password()
        self.assertEqual(status, 400)
        self.assertEqual(body.get("code"), "INVALID_RECOVERY_TOKEN")

    def test_create_account_accepts_valid_payload(self):
        class _User:
            id = "user-1"
            user_id = "user-1"
            email = "user@example.com"
            full_name = "Clean User"
            role = "user"

        self._set_request_json({
            "email": "user@example.com",
            "password": "pass",
            "fullName": "Clean User",
            "consent": self._cleanhouse_consent(),
        })

        with patch.dict(auth_api.os.environ, {"CLEANHOUSE_TURNSTILE_REQUIRED": "0"}, clear=False), patch.object(
            auth_api, "get_user_service"
        ) as get_user_service, patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ), patch.object(auth_api, "_record_current_consent", return_value=None), patch.object(
            auth_api, "_issue_session_response", side_effect=lambda user, payload, **kwargs: payload
        ), patch.object(
            auth_api, "_build_login_report_payload", return_value={"status": "ok", "id": "report:create"}
        ):
            get_user_service.return_value = type("S", (), {"create_user": lambda self, full_name, email, password, role="user": _User()})()
            response = auth_api.create_account()

        self.assertIsInstance(response, (dict, tuple))
        if isinstance(response, tuple):
            self.assertEqual(response[1], 200)
            response_body = response[0]
        else:
            response_body = response
        self.assertTrue(response_body.get("success"))
        self.assertEqual(response_body.get("login_report", {}).get("id"), "report:create")

    def test_create_account_rejects_missing_turnstile_when_required(self):
        self._set_request_json({
            "email": "user@example.com",
            "password": "password123",
            "fullName": "Clean User",
            "confirmPassword": "password123",
            "consent": self._cleanhouse_consent(),
        })

        with patch.dict(
            auth_api.os.environ,
            {
                "CLEANHOUSE_TURNSTILE_REQUIRED": "1",
                "TURNSTILE_SITE_KEY": "site-key",
                "TURNSTILE_SECRET_KEY": "secret-key",
            },
            clear=False,
        ):
            response = auth_api.create_account()

        self._assert_bad_request(response, "Turnstile verification is required")

    def test_create_account_rejects_invalid_turnstile(self):
        self._set_request_json({
            "email": "user@example.com",
            "password": "password123",
            "fullName": "Clean User",
            "confirmPassword": "password123",
            "consent": self._cleanhouse_consent(),
            "turnstileToken": "bad-token",
        })

        with patch.dict(
            auth_api.os.environ,
            {
                "CLEANHOUSE_TURNSTILE_REQUIRED": "1",
                "TURNSTILE_SITE_KEY": "site-key",
                "TURNSTILE_SECRET_KEY": "secret-key",
            },
            clear=False,
        ), patch.object(auth_api, "_verify_turnstile_token", return_value=False):
            response = auth_api.create_account()

        self._assert_bad_request(response, "Turnstile verification failed")

    def test_create_account_accepts_mocked_turnstile(self):
        class _User:
            id = "user-1"
            user_id = "user-1"
            email = "user@example.com"
            full_name = "Clean User"
            role = "user"

        self._set_request_json({
            "email": "user@example.com",
            "password": "password123",
            "fullName": "Clean User",
            "confirmPassword": "password123",
            "consent": self._cleanhouse_consent(),
            "turnstileToken": "valid-token",
        })

        with patch.dict(
            auth_api.os.environ,
            {
                "CLEANHOUSE_TURNSTILE_REQUIRED": "1",
                "TURNSTILE_SITE_KEY": "site-key",
                "TURNSTILE_SECRET_KEY": "secret-key",
            },
            clear=False,
        ), patch.object(auth_api, "_verify_turnstile_token", return_value=True), patch.object(
            auth_api, "get_user_service"
        ) as get_user_service, patch.object(
            auth_api, "_require_cookie_mutation", return_value=None
        ), patch.object(auth_api, "_record_current_consent", return_value=None), patch.object(
            auth_api, "_issue_session_response", side_effect=lambda user, payload, **kwargs: payload
        ), patch.object(
            auth_api, "_build_login_report_payload", return_value={"status": "ok", "id": "report:create"}
        ):
            get_user_service.return_value = type("S", (), {"create_user": lambda self, full_name, email, password, role="user": _User()})()
            response = auth_api.create_account()

        self.assertIsInstance(response, (dict, tuple))
        response_body = response[0] if isinstance(response, tuple) else response
        self.assertTrue(response_body.get("success"))
        self.assertEqual(response_body.get("login_report", {}).get("id"), "report:create")

    def test_delete_account_clears_local_user_and_vvault_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vvault_root = Path(temp_dir) / "vvault"
            vvault_root.mkdir()
            (vvault_root / "users.json").write_text(json.dumps({
                "users": {
                    "life-user-1": {
                        "id": "life-user-1",
                        "email": "user@example.com",
                        "name": "Clean User",
                    },
                    "other-user": {
                        "id": "other-user",
                        "email": "other@example.com",
                    },
                }
            }), encoding="utf-8")

            security_db = vvault_root / "security.db"
            conn = sqlite3.connect(security_db)
            conn.execute("create table access_controls (user_id text primary key, permissions text)")
            conn.execute("insert into access_controls values (?, ?)", ("life-user-1", "{}"))
            conn.execute("insert into access_controls values (?, ?)", ("other-user", "{}"))
            conn.commit()
            conn.close()

            audit_dir = vvault_root / "vvault" / "data"
            audit_dir.mkdir(parents=True)
            audit_db = audit_dir / "audit.db"
            conn = sqlite3.connect(audit_db)
            conn.execute("create table audit_events (event_id text primary key, user_id text not null)")
            conn.execute("insert into audit_events values (?, ?)", ("event-1", "life-user-1"))
            conn.execute("insert into audit_events values (?, ?)", ("event-2", "other-user"))
            conn.commit()
            conn.close()

            auth_api.request = types.SimpleNamespace(
                get_json=lambda silent=True: {"confirmation": "user@example.com"},
                headers={},
                cookies={},
                form={},
                method="DELETE",
            )

            class _Service:
                def __init__(self):
                    self.deleted_user_id = None

                def delete_user(self, user_id=None, legacy_id=None):
                    self.deleted_user_id = user_id
                    return True

            service = _Service()

            identity = types.SimpleNamespace(
                user_id="cleanhouse-local-user",
                credential_id="session-1",
                kind="session",
                consent_current=True,
                user={
                    "user_id": "cleanhouse-local-user",
                    "email": "user@example.com",
                    "full_name": "Clean User",
                    "role": "user",
                },
            )
            store = types.SimpleNamespace(revoke_all_sessions=lambda *args, **kwargs: 1)

            with patch.dict(auth_api.os.environ, {"CLEANHOUSE_VVAULT_ROOT": str(vvault_root)}, clear=False), patch.object(
                auth_api, "_require_cookie_mutation", return_value=None
            ), patch.object(auth_api, "_current_identity", return_value=identity), patch.object(
                auth_api, "_require_sensitive", return_value=None
            ), patch.object(auth_api, "get_store", return_value=store), patch.object(
                auth_api, "get_user_service", return_value=service
            ), patch.object(
                auth_api, "_write_account_deletion_marker", return_value="/tmp/account-delete-marker.json"
            ):
                response = auth_api.delete_account()

            response_body = response[0] if isinstance(response, tuple) else response
            self.assertTrue(response_body.get("success"))
            self.assertEqual(service.deleted_user_id, "cleanhouse-local-user")
            self.assertEqual(response_body["archive_policy"]["company_side_retention_years"], 7)
            self.assertEqual(response_body["vvault_cleanup"]["users_json_removed"], 1)
            self.assertEqual(response_body["vvault_cleanup"]["sqlite_rows_removed"], 2)

            users = json.loads((vvault_root / "users.json").read_text(encoding="utf-8"))["users"]
            self.assertNotIn("life-user-1", users)
            self.assertIn("other-user", users)

            conn = sqlite3.connect(security_db)
            self.assertEqual(conn.execute("select count(*) from access_controls where user_id = ?", ("life-user-1",)).fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from access_controls where user_id = ?", ("other-user",)).fetchone()[0], 1)
            conn.close()

            conn = sqlite3.connect(audit_db)
            self.assertEqual(conn.execute("select count(*) from audit_events where user_id = ?", ("life-user-1",)).fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from audit_events where user_id = ?", ("other-user",)).fetchone()[0], 1)
            conn.close()

    def test_build_login_report_payload_waits_two_seconds_and_accepts_queued_job(self):
        calls = []

        class _Adapter:
            def submit_login_report(self, **kwargs):
                calls.append(kwargs)
                return {
                    "status": "accepted",
                    "job_id": "login_report_job:queued",
                    "job": {"state": "queued"},
                }

        cleanhouse_api = types.ModuleType("backend.api.cleanhouse")
        cleanhouse_api.get_cleanhouse_monitoring_adapter = lambda: _Adapter()
        with patch.dict(sys.modules, {"backend.api.cleanhouse": cleanhouse_api}):
            result = auth_api._build_login_report_payload(
                {"user_id": "user-1", "email": "user@example.com"},
                previous_login_at="2026-05-26T09:00:00",
                current_login_at="2026-05-26T11:00:00",
                trigger="auth/login",
            )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["job"]["state"], "queued")
        self.assertEqual(calls[0]["wait_timeout_seconds"], 2.0)


# Separate processes keep the legacy module's Flask stubs out of real-cookie tests.
class LogoutIsolationRegressionTests(unittest.TestCase):
    def _run_isolated(self, argv):
        import os
        import subprocess
        with tempfile.TemporaryDirectory(prefix="cleanhouse-logout-test-") as home:
            root = Path(__file__).resolve().parents[1]
            env = {"PATH": os.environ.get("PATH", ""), "HOME": home,
                   "PYTHONDONTWRITEBYTECODE": "1", "JWT_SECRET_KEY": "synthetic-test-secret",
                   "CLEANHOUSE_LOGOUT_TEST_ROOT": str(root)}
            result = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_flask_logout_isolation(self):
        self._run_isolated([sys.executable, "-c", _REAL_FLASK_LOGOUT_TESTS])

    def test_logout_ui_failure_and_retry(self):
        self._run_isolated(["node", "--input-type=module", "-e", _LOGOUT_UI_TESTS])

    def test_logout_ui_requires_auth_state(self):
        self._run_isolated(["node", "--test-name-pattern=missing auth-state", "--input-type=module", "-e", _LOGOUT_UI_TESTS])


_REAL_FLASK_LOGOUT_TESTS = r'''"""Real Flask cookie-jar logout isolation; no live accounts or storage."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask

ROOT = Path(os.environ['CLEANHOUSE_LOGOUT_TEST_ROOT']) if os.environ.get('CLEANHOUSE_LOGOUT_TEST_ROOT') else Path(__file__).resolve().parents[1]


class LogoutIsolationTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix='cleanhouse-logout-home-')
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {'HOME': self.home.name, 'JWT_SECRET_KEY': 'synthetic-test-secret-not-production', 'CLEANHOUSE_AUTH_DB': str(Path(self.home.name) / 'auth.sqlite3')})
        self.env.start()
        self.addCleanup(self.env.stop)
        sys.path.insert(0, str(ROOT))
        self.addCleanup(lambda: sys.path.remove(str(ROOT)))
        spec = importlib.util.spec_from_file_location('logout_isolation_actual_auth', ROOT / 'backend/api/auth.py')
        self.auth = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.auth)
        self.users = {key: SimpleNamespace(user_id=key, email=f'{key}@example.test', full_name=key, role='user') for key in ('owner-a', 'owner-b')}
        service = SimpleNamespace(
            get_user_by_id=lambda user_id: self.users.get(user_id),
            authenticate_user=lambda email, password: next((u for u in self.users.values() if u.email == email and password == 'fixture-password'), None),
        )
        for name, value in [('get_user_service', lambda: service), ('_build_login_report_payload', lambda *a, **kw: {'id': 'synthetic-report'})]:
            p = patch.object(self.auth, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='synthetic-cookie-key')
        self.app.register_blueprint(self.auth.bp, url_prefix='/api')
        self.app.after_request(self.auth.auth_context.finalize_response)
        self.auth.auth_context.reset_store_cache()
        self.addCleanup(self.auth.auth_context.reset_store_cache)
        saved = Path(self.home.name) / '.cleanhouse'
        saved.mkdir()
        self.sentinels = {saved / '.auth_token': b'fixture-native-token', saved / '.auth_user.json': b'{"id":"fixture-native-owner"}'}
        for path, data in self.sentinels.items():
            path.write_bytes(data)

    def post(self, client, path, **kwargs):
        csrf = client.get('/api/auth/csrf', base_url='http://localhost:3333').get_json()['csrfToken']
        return client.post(path, base_url='http://localhost:3333', headers={'Origin': 'http://localhost:3333', 'X-CSRF-Token': csrf}, **kwargs)

    def login(self, client, owner):
        response = self.post(client, '/api/auth/login', json={'email': self.users[owner].email, 'password': 'fixture-password'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['user']['id'], owner)

    def exercise_isolation(self, other_owner):
        a, b = self.app.test_client(), self.app.test_client()
        self.login(a, 'owner-a')
        self.login(b, other_owner)
        self.assertEqual(a.get('/api/auth/me', base_url='http://localhost:3333').status_code, 200)
        response = self.post(a, '/api/auth/logout')
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.get_json()['success'], True)
        self.assertEqual(a.get('/api/auth/me', base_url='http://localhost:3333').status_code, 401)
        self.assertEqual(b.get('/api/auth/me', base_url='http://localhost:3333').get_json()['user']['id'], other_owner)
        for path, data in self.sentinels.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.post(a, '/api/auth/logout').status_code, 200)
        self.assertEqual(a.get('/api/auth/me', base_url='http://localhost:3333').status_code, 401)
        self.login(a, 'owner-a')
        self.assertEqual(a.get('/api/auth/me', base_url='http://localhost:3333').get_json()['user']['id'], 'owner-a')
        self.assertEqual(b.get('/api/auth/me', base_url='http://localhost:3333').status_code, 200)

    def test_same_account_independent_cookie_jars(self):
        self.exercise_isolation('owner-a')

    def test_different_accounts_independent_cookie_jars(self):
        self.exercise_isolation('owner-b')


if __name__ == '__main__':
    unittest.main()
'''

_LOGOUT_UI_TESTS = r'''import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { test } from 'node:test';

const root = process.env.CLEANHOUSE_LOGOUT_TEST_ROOT || process.cwd();
const stateSource = fs.readFileSync(path.join(root, 'frontend/js/auth-state.js'), 'utf8');
const controlsSource = fs.readFileSync(path.join(root, 'frontend/js/session-controls.js'), 'utf8');
function host() {
  const listeners = new Map();
  const button = { disabled: false, addEventListener: (name, fn) => listeners.set(name, fn) };
  const errors = [];
  const redirects = [];
  const elements = new Map([['cleanhouse-logout', button]]);
  const document = {
    readyState: 'loading', addEventListener() {},
    getElementById: id => elements.get(id) || null,
    createElement: () => ({ setAttribute() {}, textContent: '' }),
    body: { appendChild(element) { elements.set(element.id, element); } },
  };
  button.insertAdjacentElement = (_where, element) => elements.set(element.id, element);
  button.parentNode = { appendChild(element) { elements.set(element.id, element); } };
  const window = { location: { assign: value => redirects.push(value) }, alert: value => errors.push(value) };
  const context = vm.createContext({ window, document, alert: window.alert, console: { error() {} }, fetch: async () => ({ ok: true, json: async () => ({ success: true }) }) });
  vm.runInContext(stateSource, context);
  vm.runInContext(controlsSource, context);
  window.authState.setUser({ id: 'fixture-user' });
  return { context, window, button, errors, redirects, elements, click: () => listeners.get('click')() };
}
for (const [name, fetch] of [
  ['HTTP failure', async () => ({ ok: false, status: 500, json: async () => ({ success: false }) })],
  ['network failure', async () => { throw Error('synthetic outage'); }],
  ['malformed response', async () => ({ ok: true, json: async () => { throw Error('synthetic bad JSON'); } })],
  ['negative success response', async () => ({ ok: true, json: async () => ({ success: false }) })],
  ['missing success response', async () => ({ ok: true, json: async () => ({}) })],
  ['nonboolean success response', async () => ({ ok: true, json: async () => ({ success: 'true' }) })],
]) {
  test(`${name} preserves client state, stays on page and permits successful retry`, async () => {
    const h = host();
    h.context.fetch = fetch;
    await h.click();
    assert.equal(h.window.authState.getUser().id, 'fixture-user');
    assert.deepEqual(h.redirects, []);
    assert.equal(h.button.disabled, false);
    assert.ok(h.errors.length || [...h.elements.values()].some(e => e.textContent), 'failure must be visible');
    h.context.fetch = async (url, options) => {
      if (url === '/api/auth/csrf') return { ok: true, json: async () => ({ csrfToken: 'synthetic-csrf' }) };
      assert.equal(options.headers['X-CSRF-Token'], 'synthetic-csrf');
      assert.equal(url, '/api/auth/logout');
      assert.equal(options.method, 'POST');
      assert.equal(options.credentials, 'include');
      return { ok: true, json: async () => ({ success: true }) };
    };
    await h.click();
    assert.equal(h.window.authState.getUser(), null);
    assert.deepEqual(h.redirects, ['/login']);
  });
}
test('missing auth-state cannot masquerade as successful logout', async () => {
  const h = host();
  h.window.authState = undefined;
  await h.click();
  assert.deepEqual(h.redirects, []);
  assert.equal(h.button.disabled, false);
});
'''
