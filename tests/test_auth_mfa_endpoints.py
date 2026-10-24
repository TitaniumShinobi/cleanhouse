from __future__ import annotations

import base64
import os
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from backend import auth_context
from backend.api import auth as auth_api


class _User:
    user_id = id = 'mfa-owner'
    email = 'mfa-owner@example.test'
    full_name = 'MFA Owner'
    role = 'owner'
    is_active = True


class _Users:
    def get_user_by_id(self, user_id=None, **_kwargs):
        return _User() if str(user_id) == _User.user_id else None

    def get_user_by_email(self, email):
        return _User() if str(email).lower() == _User.email else None

    def authenticate_user(self, email, password):
        return _User() if email == _User.email and password == 'correct-password' else None


class CleanHouseMfaEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.env = patch.dict(os.environ, {
            'CLEANHOUSE_AUTH_DB': str(Path(self.temp.name) / 'auth.sqlite3'),
            'CLEANHOUSE_PUBLIC_ORIGIN': 'http://localhost:3333',
            'CLEANHOUSE_MFA_ENCRYPTION_KEY': '22' * 32,
            'CLEANHOUSE_ENABLE_AUTH': '1', 'CLEANHOUSE_REQUIRE_LOGIN': '1',
        }, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        auth_context.reset_store_cache()
        auth_api._mfa_service = auth_api._mfa_path = None
        self.users = patch.object(auth_api, 'get_user_service', return_value=_Users())
        self.users.start(); self.addCleanup(self.users.stop)
        self.app = Flask(__name__)
        self.app.secret_key = 'mfa-endpoint-tests'
        self.app.register_blueprint(auth_api.bp, url_prefix='/api')
        self.app.after_request(auth_context.finalize_response)
        with patch('atexit.register'):
            from backend import server
        self.server = server

        @self.app.before_request
        def protect():
            if auth_api.request.path == '/network':
                return self.server._require_auth_for_app_pages()

        @self.app.get('/network')
        def network():
            return 'network'

        self.app.testing = True
        self.client = self.app.test_client()
        self.store = auth_context.get_store()
        issued = self.store.issue_session(_User.user_id, auth_method='magic_email', now=self.now)
        auth_api.get_mfa().mark_primary(_User.user_id, issued.id, self.now)
        self.client.set_cookie(auth_context.DEVICE_COOKIE, issued.secret, domain='localhost')

    def tearDown(self):
        auth_context.reset_store_cache()
        auth_api._mfa_service = auth_api._mfa_path = None

    def csrf(self):
        return self.client.get('/api/auth/csrf', base_url='http://localhost:3333').get_json()['csrfToken']

    def post(self, path, payload, *, at=None):
        context = patch('backend.auth_mfa._utcnow', return_value=at) if at else patch('backend.auth_mfa._utcnow', wraps=auth_api.datetime.now)
        with context:
            return self.client.post(path, json=payload, base_url='http://localhost:3333',
                                    headers={'Origin': 'http://localhost:3333', 'X-CSRF-Token': self.csrf()})

    @staticmethod
    def code(uri, at):
        encoded = urllib.parse.parse_qs(urllib.parse.urlsplit(uri).query)['secret'][0]
        secret = base64.b32decode(encoded + '=' * ((8 - len(encoded) % 8) % 8))
        return auth_api.get_mfa()._totp(secret, int(at.timestamp()) // 30)

    def enroll_and_confirm(self, at=None, proof=''):
        at = at or self.now
        enrolled = self.post('/api/auth/mfa/enroll', {'label': 'Phone', 'proof': proof}, at=at)
        self.assertEqual(enrolled.status_code, 200, enrolled.get_json())
        payload = enrolled.get_json()
        confirmed = self.post('/api/auth/mfa/confirm', {'factorId': payload['factorId'], 'code': self.code(payload['provisioningUri'], at)}, at=at)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        return payload, confirmed.get_json()

    def verify(self, operation, target, factor_id, uri, at):
        challenge = self.post('/api/auth/mfa/challenge', {'operation': operation, 'target': target}, at=at)
        self.assertEqual(challenge.status_code, 200, challenge.get_json())
        verified = self.post('/api/auth/mfa/verify', {
            'challengeId': challenge.get_json()['challengeId'], 'factorId': factor_id, 'code': self.code(uri, at),
        }, at=at)
        self.assertEqual(verified.status_code, 200, verified.get_json())
        return verified.get_json()

    def test_full_endpoint_lifecycle_rotates_cookie_rebinds_grants_and_manages_recovery(self):
        original_cookie = self.client.get_cookie(auth_context.DEVICE_COOKIE).value
        first, activated = self.enroll_and_confirm(self.now)
        rotated_cookie = self.client.get_cookie(auth_context.DEVICE_COOKIE).value
        self.assertNotEqual(original_cookie, rotated_cookie)
        self.assertEqual(len(activated['recoveryCodes']), 10)
        listed = self.client.get('/api/auth/mfa/factors', base_url='http://localhost:3333').get_json()
        self.assertTrue(listed['admissionAuthorized'])
        self.assertEqual([first['factorId']], [row['factor_id'] for row in listed['factors']])

        add_at = self.now + timedelta(seconds=30)
        add = self.verify('factor.add', '', first['factorId'], first['provisioningUri'], add_at)
        second, _ = self.enroll_and_confirm(add_at, add['proof'])
        remove_at = self.now + timedelta(seconds=60)
        remove = self.verify('factor.remove', first['factorId'], second['factorId'], second['provisioningUri'], remove_at)
        removed = self.post('/api/auth/mfa/remove', {'factorId': first['factorId'], 'proof': remove['proof']}, at=remove_at)
        self.assertEqual(removed.status_code, 200)

        rotate_at = self.now + timedelta(seconds=90)
        recovery = self.verify('recovery.rotate', '', second['factorId'], second['provisioningUri'], rotate_at)
        rotated = self.post('/api/auth/mfa/recovery/rotate', {'proof': recovery['proof']}, at=rotate_at)
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(len(rotated.get_json()['recoveryCodes']), 10)

    def test_endpoint_failure_codes_cover_401_403_429_and_503(self):
        anonymous = self.app.test_client().get('/api/auth/mfa/factors', base_url='http://localhost:3333')
        self.assertEqual(anonymous.status_code, 401)
        with patch('backend.auth_runtime_config.mfa_encryption_key', return_value=''):
            unavailable = self.post('/api/auth/mfa/enroll', {'label': 'Phone'}, at=self.now)
        self.assertEqual(unavailable.status_code, 503)

        self.enroll_and_confirm(self.now)
        forbidden = self.post('/api/auth/mfa/remove', {'factorId': 'missing', 'proof': 'wrong'}, at=self.now + timedelta(seconds=30))
        self.assertEqual(forbidden.status_code, 403)
        for index in range(5):
            response = self.post('/api/auth/mfa/challenge', {'operation': 'authenticate', 'target': ''}, at=self.now + timedelta(seconds=30 + index))
            self.assertEqual(response.status_code, 200)
        limited = self.post('/api/auth/mfa/challenge', {'operation': 'authenticate', 'target': ''}, at=self.now + timedelta(seconds=36))
        self.assertEqual(limited.status_code, 429)

    def test_protected_route_resumes_once_and_consent_acceptance_never_invokes_auth_methods(self):
        first, _ = self.enroll_and_confirm(self.now)
        other = self.store.issue_session(_User.user_id, auth_method='oauth:google', now=self.now)
        auth_api.get_mfa().mark_primary(_User.user_id, other.id, self.now)
        self.client.set_cookie(auth_context.DEVICE_COOKIE, other.secret, domain='localhost')
        with patch.object(auth_api, 'user_has_current_consent', return_value=True):
            blocked = self.client.get('/network', base_url='http://localhost:3333')
            self.assertEqual(blocked.status_code, 302)
            self.assertIn('mfa=required', blocked.location)
            admitted = self.verify('authenticate', '', first['factorId'], first['provisioningUri'], self.now + timedelta(seconds=30))
            self.assertTrue(admitted['verified'])
            resumed = self.client.get('/network', base_url='http://localhost:3333')
            self.assertEqual(resumed.status_code, 200)
            self.assertNotIn('mfa=required', resumed.get_data(as_text=True))

        with (
            patch.object(auth_api, 'get_mfa', side_effect=AssertionError('consent must not invoke MFA')),
            patch.object(_Users, 'authenticate_user', side_effect=AssertionError('consent must not invoke password')),
            patch.object(auth_api, 'oauth', side_effect=AssertionError('consent must not invoke OAuth')),
            patch.object(auth_api, 'request_magic_email', side_effect=AssertionError('consent must not invoke magic email')),
        ):
            accepted = self.post('/api/auth/consent', {'accept_current': True}, at=self.now + timedelta(seconds=31))
        self.assertEqual(accepted.status_code, 200, accepted.get_json())


if __name__ == '__main__':
    unittest.main()
