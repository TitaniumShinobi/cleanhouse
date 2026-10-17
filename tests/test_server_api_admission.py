"""Import real server and blueprints; isolate only runtime services and storage."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock, patch


class ServerAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, HOME=cls.home.name,
            FLASK_SECRET_KEY='synthetic-server-cookie-key', JWT_SECRET_KEY='synthetic-server-token-key-32-bytes',
            CLEANHOUSE_ENABLE_AUTH='1', CLEANHOUSE_REQUIRE_LOGIN='1')
        cls.env.start()
        cls.external = patch.dict(sys.modules, {'backend.vvault_sync': ModuleType('backend.vvault_sync')})
        cls.external.start()
        from backend import auth_runtime_config
        with patch.object(auth_runtime_config, 'initialize_auth_runtime'):
            from backend import server
        cls.server = server
        cls.start = patch.object(server, '_start_events_services_background')
        cls.start.start()
        # Unregister the real shutdown hook: this process never starts services.
        import atexit
        atexit.unregister(server._stop_events_services)

    @classmethod
    def tearDownClass(cls):
        cls.start.stop(); cls.external.stop(); cls.env.stop(); cls.home.cleanup()

    def setUp(self):
        from backend.api import auth, cleanhouse
        self.auth, self.api = auth, cleanhouse
        user = SimpleNamespace(user_id='fixture', email='fixture@example.test',full_name='Fixture',role='user',last_login=None)
        service = SimpleNamespace(get_user_by_id=lambda user_id: user if user_id=='fixture' else None,
            authenticate_user=lambda email,password: user if email==user.email and password=='fixture' else None)
        for obj,name,value in [(auth,'get_user_service',lambda:service),
            (auth,'_build_login_report_payload',lambda *a,**k:{'id':'fixture'}),
            (cleanhouse,'_runtime_readiness_payload',lambda:{'ready':True}),
            (cleanhouse,'_event_spine_payload',lambda:{}),
            (cleanhouse,'_notification_policy_contract',lambda:{}),
            (cleanhouse,'_fast_runtime_payload',lambda:{'ready':True})]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.adapter=Mock();self.adapter.get_reports.return_value={'reports':[]}
        p=patch.object(cleanhouse,'get_cleanhouse_monitoring_adapter',return_value=self.adapter)
        self.factory=p.start();self.addCleanup(p.stop)
        self.client=self.server.app.test_client()

    def login(self, client):
        self.assertEqual(client.post('/api/auth/login',json={'email':'fixture@example.test','password':'fixture'}).status_code,200)

    def test_real_registration_denies_before_handlers(self):
        for method,path in [('get','/cleanhouse/reports'),('post','/cleanhouse/zaelith/analyze'),('delete','/cleanhouse/allowed-threats/x')]:
            self.assertEqual(getattr(self.client,method)(path).status_code,401)
        self.factory.assert_not_called()

    def test_real_login_api_logout_preserves_other_session(self):
        other=self.server.app.test_client();self.login(self.client);self.login(other)
        self.assertEqual(self.client.get('/cleanhouse/reports').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/cleanhouse/reports').status_code,401)
        self.assertEqual(other.get('/cleanhouse/reports').status_code,200)

    def test_real_readiness_and_login_routes(self):
        for path in ['/cleanhouse/status?ready=1','/cleanhouse/runtime','/login']:
            response=self.client.get(path);self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.client.get('/cleanhouse/status?ready=1&extra=1').status_code,401)
