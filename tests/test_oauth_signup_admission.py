"""Real OAuth handlers with controlled provider and identity fixtures."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlparse, parse_qs
from flask import Flask

class OAuthSignupAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.home=tempfile.TemporaryDirectory();self.addCleanup(self.home.cleanup)
        p=patch.dict(os.environ,HOME=self.home.name,JWT_SECRET_KEY='synthetic-signup-key-32-bytes-long',GOOGLE_REDIRECT_URI='http://localhost/api/auth/google/callback');p.start();self.addCleanup(p.stop)
        from backend.api import auth
        self.auth=auth;self.app=Flask(__name__);self.app.secret_key='synthetic-cookie';self.app.register_blueprint(auth.bp,url_prefix='/api');self.client=self.app.test_client()
        self.user=SimpleNamespace(user_id='fixture',email='fixture@example.test',full_name='Fixture',role='user',last_login=None)
        self.service=Mock();self.service.get_user_by_email.return_value=None;self.service.create_user.return_value=self.user
        for obj,name,value in [(auth,'get_user_service',lambda:self.service),(auth,'exchange_oauth_token',lambda *args:{'access_token':'fixture'}),(auth,'get_oauth_user_info',lambda *args:{'email':self.user.email,'name':'Fixture'}),(auth,'_build_login_report_payload',lambda *a,**k:{'id':'fixture'}),(auth.auth_runtime_config,'provider_config',lambda *a:{'enabled':True,'available':True,'client_id':'fixture','callback_url':'http://localhost/api/auth/google/callback'}),(auth,'_turnstile_config',lambda:{'required':True,'enabled':True}),(auth,'_verify_turnstile_token',lambda *a:True)]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.data={'intent':'signup','consent':{d['key']:True for d in auth._cleanhouse_auth_docs()},'consentVersions':{d['key']:d['version'] for d in auth._cleanhouse_auth_docs()},'turnstileToken':'fixture'}

    def start(self, signup=True):
        if signup:
            r=self.client.post('/api/auth/oauth/google',json=self.data,headers={'Origin':'http://localhost'});self.assertEqual(r.status_code,200,r.json);url=r.json['authorizationUrl']
        else:
            r=self.client.get('/api/auth/oauth/google');self.assertEqual(r.status_code,302);url=r.location
        return parse_qs(urlparse(url).query)['state'][0]

    def callback(self,state):return self.client.get('/api/auth/google/callback',query_string={'code':'fixture','state':state})

    def test_unknown_signin_cannot_create_or_admit(self):
        r=self.callback(self.start(False));self.assertIn('signup_required',r.location);self.service.create_user.assert_not_called()
        with self.client.session_transaction() as s:self.assertNotIn('oauth_success',s);self.assertNotIn('user_id',s)

    def test_verified_signup_creates_once_and_replay_fails(self):
        state=self.start();self.assertIn('oauth_success=1',self.callback(state).location);self.service.create_user.assert_called_once()
        self.assertIn('invalid_state',self.callback(state).location);self.service.create_user.assert_called_once()

    def test_missing_consent_or_versions_or_turnstile_rejected(self):
        for key in ('consent','consentVersions','turnstileToken'):
            data=dict(self.data);data.pop(key)
            self.assertEqual(self.client.post('/api/auth/oauth/google',json=data,headers={'Origin':'http://localhost'}).status_code,400)
        self.service.create_user.assert_not_called()

    def test_failed_or_unavailable_verification_rejected(self):
        with patch.object(self.auth,'_verify_turnstile_token',return_value=False):
            self.assertEqual(self.client.post('/api/auth/oauth/google',json=self.data,headers={'Origin':'http://localhost'}).status_code,400)
        with patch.object(self.auth,'_turnstile_config',return_value={'required':True,'enabled':False}):
            self.assertEqual(self.client.post('/api/auth/oauth/google',json=self.data,headers={'Origin':'http://localhost'}).status_code,503)

    def test_changed_documents_require_new_signup_transaction(self):
        state=self.start()
        with patch.dict(os.environ,LEGAL_VERSION_CLEANHOUSE_TERMS='changed'):
            self.assertIn('signup_required',self.callback(state).location)
        self.service.create_user.assert_not_called()

    def test_returning_signin_and_existing_signup_reuse_identity(self):
        self.service.get_user_by_email.return_value=self.user
        for signup in (False,True):self.assertIn('oauth_success=1',self.callback(self.start(signup)).location)
        self.service.create_user.assert_not_called()

    def test_cross_origin_signup_rejected(self):
        self.assertEqual(self.client.post('/api/auth/oauth/google',json=self.data,headers={'Origin':'https://evil.test'}).status_code,403)
