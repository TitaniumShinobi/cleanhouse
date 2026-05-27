import sys
import types
import unittest
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
        self._set_request_json({"email": 1, "password": 2, "fullName": "Ada", "role": "user"})
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

        self._set_request_json({"email": "user@example.com", "password": "pass", "fullName": "Clean User"})

        with patch.object(auth_api, "get_user_service") as get_user_service, patch.object(
            auth_api, "generate_jwt_token", return_value="jwt-token"
        ), patch.object(auth_api, "_build_login_report_payload", return_value={"status": "ok", "id": "report:create"}):
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
