"""Recovery revokes only the recovered account's pre-reset credentials."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask


class RecoveryGenerationTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        env = patch.dict(os.environ, HOME=self.home.name, JWT_SECRET_KEY='synthetic-recovery-secret-32-bytes-only')
        env.start(); self.addCleanup(env.stop)
        from models.user_model import UserService
        from backend.api import auth
        from backend.utils import jwt_utils
        self.UserService, self.auth, self.jwt = UserService, auth, jwt_utils
        self.service = UserService(Path(self.home.name)/'accounts')
        from access_control.access_control import access_control
        with patch.object(access_control, 'is_access_allowed', return_value=True):
            self.a = self.service.create_user('A', 'a@example.test', 'old-password')
            self.b = self.service.create_user('B', 'b@example.test', 'old-password')
        p = patch.object(auth, 'get_user_service', lambda:self.service); p.start(); self.addCleanup(p.stop)
        p = patch.object(auth, '_build_login_report_payload', return_value={}); p.start(); self.addCleanup(p.stop)
        self.app = Flask(__name__); self.app.secret_key='synthetic-cookie'; self.app.register_blueprint(auth.bp,url_prefix='/api')
        from backend.api_admission import require_cleanhouse_api_admission
        @self.app.before_request
        def admission():
            from flask import request
            if request.path == '/cleanhouse/protected': return require_cleanhouse_api_admission()
        self.app.add_url_rule('/cleanhouse/protected', view_func=lambda:'ok')
        self.client=self.app.test_client()

    def login(self, client, email='a@example.test', password='old-password'):
        r=client.post('/api/auth/login',json={'email':email,'password':password})
        self.assertEqual(r.status_code,200,r.json);return r.json['token']

    def test_reset_endpoint_revokes_cookies_tokens_and_preserves_other_account(self):
        token=self.login(self.client); other=self.app.test_client(); other_token=self.login(other,'b@example.test')
        with patch.object(self.auth,'consume_recovery',return_value={'user_id':self.a.user_id}):
            reset=self.app.test_client().post('/api/auth/recovery/reset',json={'token':'synthetic','password':'new-password'})
        self.assertEqual(reset.status_code,200)
        for path in ['/api/auth/me','/cleanhouse/protected']:
            self.assertEqual(self.client.get(path).status_code,401)
            self.assertEqual(other.get(path).status_code,200)
        self.assertIsNone(self.jwt.verify_jwt_token(token))
        self.assertIsNone(self.jwt.refresh_jwt_token(token))
        self.assertIsNotNone(self.jwt.verify_jwt_token(other_token))
        fresh=self.login(self.client,password='new-password'); self.assertIsNotNone(self.jwt.verify_jwt_token(fresh))
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)

    def test_legacy_cookie_and_token_only_survive_never_reset_accounts(self):
        with self.client.session_transaction() as session: session['user_id']=self.a.user_id
        payload={'user_id':self.a.user_id,'exp':9999999999}
        token=self.jwt._fallback_encode(payload,self.jwt.JWT_SECRET_KEY)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.assertIsNotNone(self.jwt.verify_jwt_token(token))
        self.assertTrue(self.service.set_password(self.a.user_id,'new-password'))
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertIsNone(self.jwt.verify_jwt_token(token))

    def test_pending_oauth_cannot_launder_old_generation(self):
        with self.client.session_transaction() as session:
            session['oauth_success']=True
            session['oauth_user']={'user_id':self.a.user_id,'email':self.a.email,'credential_generation':'0'}
        self.assertTrue(self.service.set_password(self.a.user_id,'new-password'))
        self.assertEqual(self.client.get('/api/auth/oauth/user').status_code,401)
        self.assertEqual(self.client.get('/cleanhouse/protected').status_code,401)
        with self.app.test_request_context():
            from flask import session
            session['user_id']=self.a.user_id
            self.assertIsNone(self.auth.current_browser_user())

    def test_restart_reads_generation_and_failed_replace_preserves_both_fields(self):
        path=self.service.shard_manager.get_user_path(self.a.user_id)/'identity/auth.json'
        old=path.read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('synthetic storage failure')):
            self.assertFalse(self.service.set_password(self.a.user_id,'new-password'))
        self.assertEqual(path.read_bytes(),old)
        self.assertFalse(list(path.parent.glob('.auth-reset-*')))
        self.assertTrue(self.service.set_password(self.a.user_id,'new-password'))
        generation=json.loads(path.read_text())['credential_generation']
        self.assertNotEqual(generation,'0')
        restarted=self.UserService(Path(self.home.name)/'accounts')
        self.assertEqual(restarted.get_user_by_id(self.a.user_id).credential_generation,generation)
        self.assertIsNone(restarted.authenticate_user(self.a.email,'old-password'))
        self.assertIsNotNone(restarted.authenticate_user(self.a.email,'new-password'))

    def test_storage_corruption_denies_cookie_and_bearer(self):
        token=self.login(self.client)
        path=self.service.shard_manager.get_user_path(self.a.user_id)/'identity/auth.json'
        path.write_text('{broken')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.assertIsNone(self.jwt.verify_jwt_token(token))

    def test_login_metadata_writer_cannot_restore_pre_reset_generation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        path=self.service.shard_manager.get_user_path(self.a.user_id)/'identity/auth.json'
        entered, release = Event(), Event()
        original_hash=self.service._hash_password
        def delayed_hash(password):
            entered.set()
            self.assertTrue(release.wait(5))
            return original_hash(password)
        with patch.object(self.service, '_hash_password', side_effect=delayed_hash):
            with ThreadPoolExecutor(max_workers=2) as pool:
                reset=pool.submit(self.service.set_password,self.a.user_id,'new-password')
                self.assertTrue(entered.wait(5))
                update=pool.submit(self.service._update_last_login,self.a.user_id)
                self.assertFalse(update.done())
                release.set()
                self.assertTrue(reset.result(5));update.result(5)
        current=json.loads(path.read_text())
        self.assertNotEqual(current['credential_generation'],'0')
        self.assertTrue(self.service._verify_password('new-password',current['password_hash']))
        self.assertIsNotNone(current.get('last_login'))

    def test_logout_remains_browser_local(self):
        other=self.app.test_client(); token=self.login(self.client);self.login(other)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(other.get('/api/auth/me').status_code,200)
        self.assertIsNotNone(self.jwt.verify_jwt_token(token))


if __name__=='__main__': unittest.main()
