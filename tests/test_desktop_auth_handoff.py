"""Separate browser cookie jars; no browser, listener, credentials or user database."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from flask import Flask

class DesktopHandoffTests(unittest.TestCase):
    def setUp(self):
        self.home=tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        p=patch.dict(os.environ, HOME=self.home.name); p.start(); self.addCleanup(p.stop)
        from backend.api import auth
        from backend import desktop_handoff
        self.auth=auth; self.handoff=desktop_handoff; desktop_handoff._pending.clear()
        self.app=Flask(__name__); self.app.secret_key='synthetic-only'; self.app.register_blueprint(auth.bp,url_prefix='/api')
        self.desktop=self.app.test_client(); self.browser=self.app.test_client()
        self.user=SimpleNamespace(user_id='fixture',email='fixture@example.test',full_name='Fixture',role='user',last_login=None)
        service=SimpleNamespace(get_user_by_email=lambda email:self.user,get_user_by_id=lambda user_id:self.user)
        for obj,name,value in [(auth,'get_user_service',lambda:service),(auth,'_build_login_report_payload',lambda *a,**k:None),(auth,'_canonical_oauth_start',lambda p:None),(auth,'_oauth_redirect_uri',lambda p:'http://localhost/api/auth/oauth/callback'),(auth,'exchange_oauth_token',lambda *a:{'access_token':'test-only'}),(auth,'get_oauth_user_info',lambda *a:{'email':self.user.email}),(auth.auth_runtime_config,'provider_config',lambda p:{'enabled':True,'available':True,'client_id':'fixture'})]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
    def prepare(self):
        r=self.desktop.post('/api/auth/desktop/prepare',json={'provider':'google'},headers={'Origin':'http://localhost'})
        self.assertEqual(r.status_code,200);return {k:r.json[k] for k in ('transactionId','verifier')}
    def callback(self,h,error=False):
        r=self.browser.get('/api/auth/desktop/start/'+h['transactionId']);self.assertEqual(r.status_code,302)
        r=self.browser.get(r.location);state=parse_qs(urlsplit(r.location).query)['state'][0]
        return self.browser.get('/api/auth/oauth/callback',query_string={'state':state, **({'error':'access_denied'} if error else {'code':'fixture-code'})})
    def redeem(self,h,client=None):
        return (client or self.desktop).post('/api/auth/desktop/redeem',json=h,headers={'Origin':'http://localhost'})
    def test_separate_cookie_jars_complete_once_only_initiator(self):
        h=self.prepare();self.assertEqual(self.redeem(h).status_code,202)
        self.assertEqual(self.callback(h).status_code,200)
        self.assertEqual(self.browser.get('/api/auth/oauth/user').status_code,404)
        self.assertEqual(self.redeem(h,self.browser).status_code,401)
        self.assertEqual(self.redeem({**h,'verifier':'wrong'}).status_code,401)
        self.assertEqual(self.redeem(h).status_code,200)
        self.assertEqual(self.redeem(h).status_code,401)
        with self.desktop.session_transaction() as s:self.assertEqual(s['user_id'],'fixture')
    def test_expired_handoff_fails(self):
        h=self.prepare();self.handoff._pending[h['transactionId']]['expires']=0
        self.assertEqual(self.redeem(h).status_code,401)
    def test_denial_is_bound_and_consumed(self):
        h=self.prepare();self.callback(h,error=True)
        self.assertEqual(self.redeem(h).status_code,403)
        self.assertEqual(self.redeem(h).status_code,401)
    def test_logout_and_cancel_reject_late_callback(self):
        for route in ('/api/auth/logout','/api/auth/desktop/cancel'):
            h=self.prepare()
            r=self.browser.get('/api/auth/desktop/start/'+h['transactionId']);r=self.browser.get(r.location)
            state=parse_qs(urlsplit(r.location).query)['state'][0]
            self.desktop.post(route,headers={'Origin':'http://localhost'})
            r=self.browser.get('/api/auth/oauth/callback',query_string={'state':state,'code':'fixture'})
            self.assertEqual(r.status_code,409)
            self.assertEqual(self.redeem(h).status_code,401)
    def test_wrong_origin_and_invalid_state_do_not_complete(self):
        self.assertEqual(self.desktop.post('/api/auth/desktop/prepare',json={'provider':'google'}).status_code,403)
        h=self.prepare();r=self.browser.get('/api/auth/oauth/callback?error=access_denied&state=wrong')
        self.assertIn('invalid_state',r.location);self.assertEqual(self.redeem(h).status_code,202)
    def test_reprepare_invalidates_previous_and_restart_fails_closed(self):
        h=self.prepare();fresh=self.prepare();self.assertEqual(self.redeem(h).status_code,401)
        self.handoff._pending.clear();self.assertEqual(self.redeem(fresh).status_code,401)
    def test_bounded_states_preserves_handoff(self):
        h=self.prepare();self.browser.get('/api/auth/desktop/start/'+h['transactionId']);self.browser.get('/api/auth/oauth/google')
        with self.browser.session_transaction() as s:
            state=next(iter(s['oauth_states'].values()));self.assertEqual(state['desktop_transaction'],h['transactionId'])
    def test_canonical_browser_origin_precedes_state_cookie(self):
        h=self.prepare()
        with patch.object(self.auth,'_oauth_redirect_uri',return_value='http://127.0.0.1/api/auth/oauth/callback'):
            r=self.browser.get('/api/auth/desktop/start/'+h['transactionId'])
            self.assertEqual(r.location,'http://127.0.0.1/api/auth/desktop/start/'+h['transactionId'])
            self.assertEqual(self.handoff._pending[h['transactionId']]['state'],'pending')
    def test_provider_failure_completes_without_session(self):
        h=self.prepare()
        with patch.object(self.auth,'exchange_oauth_token',return_value=None):
            self.callback(h)
        self.assertEqual(self.redeem(h).status_code,403)
    def test_signup_proof_is_server_validated_and_retained(self):
        proof={'intent':'signup','consent_versions':{d['key']:d['version'] for d in self.auth._cleanhouse_auth_docs()},'turnstile_verified':True}
        with patch.object(self.auth,'_validate_signup_intent',return_value=(proof,None),create=True) as validate:
            r=self.desktop.post('/api/auth/desktop/prepare',json={'provider':'google','intent':'signup'},headers={'Origin':'http://localhost'})
            validate.assert_called_once();h=r.json
        self.browser.get('/api/auth/desktop/start/'+h['transactionId']);self.browser.get('/api/auth/oauth/google')
        with self.browser.session_transaction() as session:
            self.assertEqual(next(iter(session['oauth_states'].values()))['signup_proof'],proof)
    def test_recovery_between_callback_and_redemption_rejects_old_proof(self):
        self.user.credential_generation='before-reset'
        h=self.prepare();self.callback(h)
        self.user.credential_generation='after-reset'
        self.assertEqual(self.redeem(h).status_code,401)
        with self.desktop.session_transaction() as session:self.assertNotIn('user_id',session)

    def test_unknown_desktop_signin_returns_signup_required_without_creation(self):
        from unittest.mock import Mock
        service=Mock();service.get_user_by_email.return_value=None
        h=self.prepare()
        with patch.object(self.auth,'get_user_service',return_value=service):
            response=self.callback(h)
        self.assertIn('signup_required',response.location);service.create_user.assert_not_called()
        self.assertEqual(self.redeem(h).status_code,403)

    def test_real_html_provider_buttons_call_exported_handlers(self):
        import subprocess
        from pathlib import Path
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const context = {console:{log(){},debug(){},error(){}}, URLSearchParams,
 window:{location:{search:''},addEventListener(){}},
 document:{addEventListener(){},getElementById(){return null;},querySelectorAll(){return [];},querySelector(){return null;}},
 setInterval(){return 1;},clearInterval(){},setTimeout(){},
 fetch:async()=>({ok:true,json:async()=>({})})};
vm.createContext(context);
vm.runInContext(fs.readFileSync('frontend/js/auth.js','utf8'),context);
const start=context.openOAuthProvider, poll=context.waitForDesktopOAuth;
const calls=[];context.openOAuthProvider = provider => calls.push(provider);
for(const page of ['login','signup']) {
 const html=fs.readFileSync('frontend/'+page+'.html','utf8');
 const buttons=[...html.matchAll(/data-provider="([^"]+)" onclick="([^"(]+)\(\)"/g)];
 assert.equal(buttons.length,4);
 for(const [,provider,name] of buttons) {
   assert.equal(typeof context[name],'function',name);
   context[name]();assert.equal(calls.pop(),provider);
 }
}
(async()=>{
 context.openOAuthProvider=start;
 let prepared=0, release;
 context.window.pywebview={api:{openOAuthUrl:async()=>({success:true}),activateExistingWindow:async()=>{throw Error('focus denied');}}};
 context.fetch=async()=>{prepared++;return {ok:true,json:async()=>({success:true,transactionId:'fixture',verifier:'fixture'})};};
 context.showSuccess=()=>{};context.showOAuthLoading=()=>{};context.showError=()=>{};
 context.waitForDesktopOAuth=()=>new Promise(resolve=>{release=resolve;});
 const first=start('google');
 for(let i=0;i<10&&!release;i++)await Promise.resolve();
 assert.equal(typeof release,'function');
 await start('google');assert.equal(prepared,1);release();await first;
 context.waitForDesktopOAuth=poll;
 context.setTimeout=fn=>fn();
 context.fetch=async()=>({ok:true,status:200,json:async()=>({success:true,user:{id:'fixture'}})});
 let admitted=0;context.completeAuth=()=>{admitted++;};
 vm.runInContext("desktopHandoff={transactionId:'fixture',verifier:'fixture'}",context);
 await vm.runInContext('waitForDesktopOAuth(desktopHandoff)',context);
 assert.equal(admitted,1,'OS focus refusal must not discard validated session');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_wrapper_accepts_only_identifier_and_reuses_window(self):
        from desktop import wrapper
        host=wrapper.DesktopAuthApi('127.0.0.1',3333)
        with patch.object(wrapper.webbrowser,'open',return_value=True) as opened:
            self.assertFalse(host.openOAuthUrl('https://evil.test')['success']);opened.assert_not_called()
            self.assertTrue(host.openOAuthUrl('a'*43)['success']);self.assertEqual(opened.call_args.args[0],'http://127.0.0.1:3333/api/auth/desktop/start/'+'a'*43)
        from unittest.mock import Mock
        window=Mock()
        with patch.object(wrapper,'WEBVIEW_AVAILABLE',True),patch.object(wrapper,'webview',SimpleNamespace(windows=[window])):
            self.assertTrue(host.activateExistingWindow()['success']);window.restore.assert_called_once();window.show.assert_called_once()

if __name__=='__main__':unittest.main()
