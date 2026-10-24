import base64
import os
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.auth_mfa import CleanHouseMFA, MfaError
from backend.auth_store import AuthStore


class CleanHouseMfaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = patch.dict(os.environ, {'CLEANHOUSE_MFA_ENCRYPTION_KEY': '11' * 32})
        self.key.start()
        self.addCleanup(self.key.stop)
        self.mfa = CleanHouseMFA(Path(self.tmp.name) / 'auth.sqlite3')
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mfa.mark_primary('owner', 'session-a', self.now)

    def enroll(self, session='session-a', now=None):
        now = now or self.now
        result = self.mfa.enroll('owner', session, 'CleanHouse', now=now)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(result['provisioningUri']).query)
        encoded = query['secret'][0]
        secret = base64.b32decode(encoded + '=' * ((8 - len(encoded) % 8) % 8))
        code = self.mfa._totp(secret, int(now.timestamp()) // 30)
        confirmed = self.mfa.confirm('owner', session, result['factorId'], code, now=now)
        return result, confirmed, secret

    def test_passwordless_primary_session_can_enroll_and_receives_recovery_once(self):
        enrollment, confirmed, _ = self.enroll()
        self.assertTrue(confirmed['verified'])
        self.assertEqual(len(confirmed['recoveryCodes']), 10)
        self.assertNotIn('provisioningUri', self.mfa.factors('owner')[0])
        self.assertTrue(self.mfa.admitted('owner', 'session-a'))
        self.assertFalse(self.mfa.admitted('owner', 'parallel-session'))
        self.assertEqual(enrollment['factorId'], self.mfa.factors('owner')[0]['factor_id'])

    def test_totp_is_single_use_and_grant_is_action_target_bound(self):
        enrollment, _, secret = self.enroll()
        later = self.now + timedelta(seconds=30)
        challenge = self.mfa.challenge('owner', 'session-a', 'factor.remove', enrollment['factorId'], later)
        code = self.mfa._totp(secret, int(later.timestamp()) // 30)
        verified = self.mfa.verify('owner', 'session-a', challenge['challengeId'], enrollment['factorId'], code, None, later)
        self.assertFalse(self.mfa.consume_grant('owner', 'session-a', 'factor.remove', 'wrong', verified['proof']))
        self.assertTrue(self.mfa.consume_grant('owner', 'session-a', 'factor.remove', enrollment['factorId'], verified['proof']))
        self.assertFalse(self.mfa.consume_grant('owner', 'session-a', 'factor.remove', enrollment['factorId'], verified['proof']))

    def test_recovery_code_is_single_use_and_session_rotation_preserves_only_initiator(self):
        _, confirmed, _ = self.enroll()
        recovery = confirmed['recoveryCodes'][0]
        later = self.now + timedelta(seconds=30)
        challenge = self.mfa.challenge('owner', 'session-a', 'authenticate', '', later)
        verified = self.mfa.verify('owner', 'session-a', challenge['challengeId'], None, None, recovery, later)
        self.mfa.rebind_rotated_session('owner', 'session-a', 'session-b')
        self.assertTrue(self.mfa.admitted('owner', 'session-b'))
        self.assertTrue(self.mfa.consume_grant('owner', 'session-b', 'authenticate', '', verified['proof']))
        replay = self.mfa.challenge('owner', 'session-b', 'authenticate', '', later + timedelta(seconds=1))
        with self.assertRaisesRegex(MfaError, 'invalid'):
            self.mfa.verify('owner', 'session-b', replay['challengeId'], None, None, recovery, later + timedelta(seconds=1))

    def test_expired_primary_auth_and_missing_key_fail_closed(self):
        with self.assertRaises(MfaError) as caught:
            self.mfa.enroll('owner', 'session-a', 'CleanHouse', now=self.now + timedelta(minutes=6))
        self.assertEqual(caught.exception.code, 'PRIMARY_AUTH_REQUIRED')
        with patch('backend.auth_runtime_config.mfa_encryption_key', return_value=''):
            with self.assertRaises(MfaError) as missing:
                self.mfa.enroll('owner', 'session-a', 'CleanHouse', now=self.now)
        self.assertEqual(missing.exception.status, 503)
        with patch('backend.auth_runtime_config.mfa_encryption_key', return_value='not-hex'):
            with self.assertRaises(MfaError) as invalid:
                self.mfa.validate_configuration()
        self.assertEqual(invalid.exception.code, 'MFA_CONFIGURATION_INVALID')

    def test_failed_proofs_persist_rate_reservations(self):
        enrollment, _, secret = self.enroll()
        later = self.now + timedelta(seconds=30)
        for index in range(4):
            challenge = self.mfa.challenge('owner', 'session-a', 'authenticate', '', later + timedelta(seconds=index))
            with self.assertRaises(MfaError):
                self.mfa.verify('owner', 'session-a', challenge['challengeId'], enrollment['factorId'], '000000', None, later + timedelta(seconds=index))
        challenge = self.mfa.challenge('owner', 'session-a', 'authenticate', '', later + timedelta(seconds=5))
        valid = self.mfa._totp(secret, int((later + timedelta(seconds=5)).timestamp()) // 30)
        with self.assertRaises(MfaError) as limited:
            self.mfa.verify('owner', 'session-a', challenge['challengeId'], enrollment['factorId'], valid, None, later + timedelta(seconds=5))
        self.assertEqual(limited.exception.status, 429)

    def test_additive_initialization_preserves_sessions_and_zero_consent_receipts(self):
        path = Path(self.tmp.name) / 'upgrade.sqlite3'
        store = AuthStore(path)
        issued = store.issue_session('owner', auth_method='magic_email', now=self.now)
        before = store.validate_session(issued.secret, now=self.now, rotate_if_due=False)
        self.assertEqual(before.status, 'valid')
        CleanHouseMFA(path)
        AuthStore(path)
        after = store.validate_session(issued.secret, now=self.now, rotate_if_due=False)
        self.assertEqual(after.status, 'valid')
        with store._connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consent_receipts').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mfa_%'")}
        self.assertIn('mfa_factors', names)
        self.assertIn('mfa_audit', names)


if __name__ == '__main__':
    unittest.main()
