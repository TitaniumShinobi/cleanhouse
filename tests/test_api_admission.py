"""Real cookie/JWT admission against actual server guard; no listener or real DB."""
import ast
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, g, jsonify, request, session, redirect

ROOT = Path(__file__).resolve().parents[1]


class ApiAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        env = patch.dict(os.environ, {'HOME': self.home.name, 'JWT_SECRET_KEY':'synthetic-admission-only-key-32-bytes-minimum', 'CLEANHOUSE_ENABLE_AUTH':'1','CLEANHOUSE_REQUIRE_LOGIN':'1'})
        env.start(); self.addCleanup(env.stop)
        from backend.api import auth
        from backend.utils import jwt_utils
        self.auth, self.jwt = auth, jwt_utils
        self.users = {u:SimpleNamespace(user_id=u,email=u+'@example.test',full_name=u,role='user',last_login=None) for u in ('a','b')}
        service = SimpleNamespace(get_user_by_id=lambda user_id:self.users.get(user_id),authenticate_user=lambda email,password: next((u for u in self.users.values() if u.email==email and password=='fixture'),None))
        for target,name,value in [(auth,'get_user_service',lambda:service),(auth,'_build_login_report_payload',lambda *a,**k:{'id':'fixture'})]:
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        # Execute the actual existing origin and stricter bearer helpers without importing collectors.
        source=ast.parse((ROOT/'backend/api/cleanhouse.py').read_text())
        self.api=ModuleType('backend.api.cleanhouse')
        self.api.__dict__.update(os=os,re=re,LOCAL_ORIGIN_RE=re.compile(r'^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$'),request=request,get_user_from_token=jwt_utils.get_user_from_token,_auth_error_response=lambda message:(jsonify({'error':message}),401))
        names={'_require_allowed_origin','_extract_authenticated_user_id'}
        exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'cleanhouse-origin-helpers','exec'),self.api.__dict__)
        p=patch.dict(sys.modules,{'backend.api.cleanhouse':self.api});p.start();self.addCleanup(p.stop)
        self.app=Flask(__name__);self.app.secret_key='synthetic-cookie-only';self.app.register_blueprint(auth.bp,url_prefix='/api')
        ns=dict(os=os,app=self.app,request=request,session=session,redirect=redirect)
        names={'_auth_enabled','_requires_login','_has_cleanhouse_session','_require_auth_for_app_pages'}
        server=ast.parse((ROOT/'backend/server.py').read_text())
        exec(compile(ast.Module(body=[n for n in server.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual-server-guard','exec'),ns)
        self.hits=[]
        def handler():
            self.hits.append(request.path);return jsonify({'ok':True,'user_id':getattr(g,'cleanhouse_api_user_id',None)})
        for i,path in enumerate(['/cleanhouse/reports','/cleanhouse/allowed-threats/x','/cleanhouse/zaelith/analyze','/cleanhouse/status','/cleanhouse/runtime','/reports']):
            self.app.add_url_rule(path,str(i),handler,methods=['GET','POST','DELETE','OPTIONS'])
        def strict():
            uid,error=self.api._extract_authenticated_user_id()
            return error or jsonify({'user_id':uid})
        self.app.add_url_rule('/cleanhouse/accounts','strict',strict)
        self.client=self.app.test_client()

    def login(self,client=None,user='a'):
        r=(client or self.client).post('/api/auth/login',json={'email':user+'@example.test','password':'fixture'})
        self.assertEqual(r.status_code,200,r.json);return r.json['token']

    def test_anonymous_reads_and_mutations_stop_before_handler(self):
        for method,path in [('get','/cleanhouse/reports'),('post','/cleanhouse/zaelith/analyze'),('delete','/cleanhouse/allowed-threats/x')]:
            r=getattr(self.client,method)(path);self.assertEqual(r.status_code,401);self.assertEqual(r.json['code'],'AUTHENTICATION_REQUIRED')
        self.assertEqual(self.hits,[])

    def test_real_login_session_me_and_same_origin_mutation(self):
        self.login();self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.assertEqual(self.client.get('/cleanhouse/reports').json['user_id'],'a')
        self.assertEqual(self.client.post('/cleanhouse/zaelith/analyze',headers={'Origin':'http://localhost'}).status_code,200)
        self.assertEqual(self.client.delete('/cleanhouse/allowed-threats/x',headers={'Sec-Fetch-Site':'same-origin'}).status_code,200)

    def test_cookie_mutations_reject_cross_origin_and_missing_context(self):
        self.login()
        for headers in [{},{'Origin':'http://localhost:9000'},{'Origin':'https://evil.test'},{'Origin':'null'},{'Origin':'http://localhost:9000','Sec-Fetch-Site':'same-origin'},{'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual(self.client.post('/cleanhouse/zaelith/analyze',headers=headers).status_code,403)
        self.assertEqual(self.hits,[])

    def test_valid_native_bearer_without_origin(self):
        token=self.login();client=self.app.test_client()
        for method in ['get','post','delete']:
            self.assertEqual(getattr(client,method)('/cleanhouse/reports',headers={'Authorization':'Bearer '+token}).status_code,200)

    def test_existing_fallback_jwt_backend_still_validates(self):
        with patch.object(self.jwt,'pyjwt',None):
            token=self.login()
            self.assertEqual(self.client.get('/cleanhouse/reports',headers={'Authorization':'Bearer '+token}).status_code,200)
            self.assertEqual(self.client.get('/cleanhouse/reports',headers={'Authorization':'Bearer '+token[:-5]+'wrong'}).status_code,401)

    def test_invalid_bearer_never_falls_back_to_cookie(self):
        token=self.login()
        for header in ['', 'Basic value','Bearer bad','Bearer '+token[:-5]+'wrong']:
            self.assertEqual(self.client.get('/cleanhouse/reports',headers={'Authorization':header}).status_code,401)
        self.assertEqual(self.hits,[])

    def test_expired_missing_expiry_and_missing_subject_tokens_fail(self):
        for payload in [{'user_id':'a','exp':0},{'user_id':'a'},{'exp':9999999999}]:
            token=self.jwt._fallback_encode(payload,self.jwt.JWT_SECRET_KEY)
            self.assertEqual(self.client.get('/cleanhouse/reports',headers={'Authorization':'Bearer '+token}).status_code,401)

    def test_logout_leaves_other_browser_and_native_session_untouched(self):
        token=self.login();other=self.app.test_client();self.login(other)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/cleanhouse/reports').status_code,401)
        self.assertEqual(other.get('/cleanhouse/reports').status_code,200)
        self.assertEqual(self.client.get('/cleanhouse/reports',headers={'Authorization':'Bearer '+token}).status_code,200)

    def test_oauth_transition_is_verified_without_consuming_it(self):
        with self.client.session_transaction() as s:s.update(oauth_success=True,oauth_user={'id':'a','user_id':'a','email':'a@example.test'})
        self.assertEqual(self.client.get('/cleanhouse/reports').status_code,200)
        self.assertEqual(self.client.get('/api/auth/oauth/user').status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)

    def test_arbitrary_pending_or_unknown_identity_is_not_admission(self):
        for state in [{'oauth_user':{'user_id':'a'}},{'oauth_success':True,'oauth_user':{'user_id':'missing'}},{'oauth_success':True,'oauth_user':{'id':'b','user_id':'a'}},{'user_id':'missing'}]:
            with self.client.session_transaction() as s:s.clear();s.update(state)
            self.assertEqual(self.client.get('/cleanhouse/reports').status_code,401)
        self.assertEqual(self.hits,[])

    def test_identity_store_failure_is_unavailable_not_admitted(self):
        self.login()
        with patch.object(self.auth,'get_user_service',side_effect=RuntimeError('secret must not escape')):
            r=self.client.get('/cleanhouse/reports');self.assertEqual(r.status_code,503);self.assertNotIn('secret',r.get_data(as_text=True))
        self.assertEqual(self.hits,[])

    def test_local_launcher_readiness_exact_contract(self):
        for path in ['/cleanhouse/status?ready=1','/cleanhouse/runtime']:
            for method in ['get','head']:self.assertEqual(getattr(self.client,method)(path).status_code,200)
        for path in ['/cleanhouse/status','/cleanhouse/status?ready=1&full=1','/cleanhouse/status?ready=1&ready=0','/cleanhouse/runtime?full=1']:
            self.assertEqual(self.client.get(path).status_code,401)

    def test_readiness_cannot_be_spoofed_or_used_to_mutate(self):
        for kwargs in [{'environ_overrides':{'REMOTE_ADDR':'203.0.113.7'}},{'headers':{'Host':'evil.test'}},{'headers':{'Origin':'http://localhost'}},{'headers':{'Referer':'http://localhost/'}},{'headers':{'Sec-Fetch-Site':'cross-site'}},{'headers':{'Authorization':'Bearer bad'}}]:
            self.assertEqual(self.client.get('/cleanhouse/runtime',**kwargs).status_code,401)
        self.assertEqual(self.client.post('/cleanhouse/runtime').status_code,401)
        self.assertEqual(self.client.get('/cleanhouse/runtime',environ_overrides={'REMOTE_ADDR':'203.0.113.7'},headers={'X-Forwarded-For':'127.0.0.1'}).status_code,401)

    def test_existing_stricter_account_bearer_requirement_survives(self):
        token=self.login();self.assertEqual(self.client.get('/cleanhouse/accounts').status_code,401)
        self.assertEqual(self.client.get('/cleanhouse/accounts',headers={'Authorization':'Bearer '+token}).status_code,200)

    def test_toggles_preflight_and_page_redirect_unchanged(self):
        self.assertEqual(self.client.get('/reports').status_code,302)
        self.assertEqual(self.client.options('/cleanhouse/reports').status_code,200)
        for flag in ['CLEANHOUSE_ENABLE_AUTH','CLEANHOUSE_REQUIRE_LOGIN']:
            with patch.dict(os.environ,{flag:'0'}):self.assertEqual(self.client.get('/cleanhouse/reports').status_code,200)

if __name__=='__main__':unittest.main()
