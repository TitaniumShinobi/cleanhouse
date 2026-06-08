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
        self.session = {}
        auth_api.session = self.session
        auth_api.request = types.SimpleNamespace(
            get_json=lambda silent=True: None,
            headers={},
            form={},
            method="GET",
        )

    def tearDown(self):
        auth_api.request = self._original_request
        auth_api.session = self._original_session

    def _set_request_json(self, payload):
        auth_api.request = types.SimpleNamespace(
            get_json=lambda silent=True: payload,
            headers={},
            form={},
            method="POST",
        )

    def _set_request_headers(self, headers):
        auth_api.request = types.SimpleNamespace(
            get_json=lambda silent=True: None,
            headers=headers,
            form={},
            method="GET",
        )

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

    def test_launch_desktop_rejects_invalid_payload(self):
        self._set_request_json({"token": 123, "user": "not-a-dict"})
        response = auth_api.launch_desktop()
        self._assert_bad_request(response, "must be")

    def test_me_rejects_invalid_authorization_header(self):
        self._set_request_headers({"Authorization": "bad header"})
        response = auth_api.get_current_user()
        self.assertIsInstance(response, tuple)
        body, status = response
        self.assertEqual(status, 401)
        self.assertIn("Bearer <token>", body.get("message", ""))

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
            auth_api, "generate_jwt_token", return_value="jwt-token"
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
            auth_api, "generate_jwt_token", return_value="jwt-token"
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
            auth_api, "generate_jwt_token", return_value="jwt-token"
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
                headers={"Authorization": "Bearer token"},
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

            with patch.dict(auth_api.os.environ, {"CLEANHOUSE_VVAULT_ROOT": str(vvault_root)}, clear=False), patch.object(
                auth_api, "get_user_from_token", return_value={
                    "user_id": "cleanhouse-local-user",
                    "email": "user@example.com",
                    "full_name": "Clean User",
                    "role": "user",
                }
            ), patch.object(auth_api, "get_user_service", return_value=service), patch.object(
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

        with patch("backend.api.cleanhouse.get_cleanhouse_monitoring_adapter", return_value=_Adapter()):
            result = auth_api._build_login_report_payload(
                {"user_id": "user-1", "email": "user@example.com"},
                previous_login_at="2026-05-26T09:00:00",
                current_login_at="2026-05-26T11:00:00",
                trigger="auth/login",
            )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["job"]["state"], "queued")
        self.assertEqual(calls[0]["wait_timeout_seconds"], 2.0)
