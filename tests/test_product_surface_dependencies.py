"""Bounded page/asset/handler tests; no server startup or live account state."""
import ast
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from typing import Any, Dict

from flask import Flask, Blueprint, jsonify, request, redirect, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('zaelith', 'zaelith-connect', 'identity', 'reports', 'allowed-threats', 'help')


def selected(path, names, namespace, parent=None):
    tree = ast.parse((ROOT / path).read_text())
    nodes = tree.body if parent is None else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == parent).body
    chosen = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in chosen} == set(names)
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(ROOT / path), 'exec'), namespace)


class SurfaceDependenciesTests(unittest.TestCase):
    def test_pages_and_transitive_static_assets_exist(self):
        queue = ['frontend/'+p+'.html' for p in PAGES]; seen = set()
        while queue:
            path = queue.pop()
            if path in seen: continue
            seen.add(path)
            text = (ROOT/path).read_text()
            for pair in re.findall(r'(?:src|href)=["\'](/[^"\']+)|url\(["\']?(/[^)"\']+)', text):
                url = next(v for v in pair if v).split('?')[0]
                if not url.startswith(('/assets/', '/js/', '/css/')): continue
                target = ROOT/('frontend'+url)
                if url.startswith('/assets/') and not target.exists(): target = ROOT/url.lstrip('/')
                self.assertTrue(target.is_file(), url)
                if target.suffix in ('.css', '.js'): queue.append(str(target.relative_to(ROOT)))

    def test_real_flask_page_routes_and_legacy_redirect(self):
        app = Flask(__name__)
        ns = dict(app=app, FRONTEND_DIR=ROOT/'frontend', send_from_directory=send_from_directory, redirect=redirect)
        selected('backend/server.py', ['dashboard_redirect','advanced','settings','zaelith','zaelith_connect','identity','reports','allowed_threats','help_page'], ns)
        client = app.test_client()
        for route in (*PAGES, 'advanced'):
            response = client.get('/'+route.replace('zaelith-connect','zaelith/connect'))
            self.assertEqual(response.status_code, 200, route)
            self.assertIn(b'<!DOCTYPE html>', response.data)
            response.close()
        self.assertEqual(client.get('/dashboard').location, '/advanced')
        settings_response = client.get('/settings')
        self.assertEqual(settings_response.status_code, 200)
        self.assertIn(b'id="settings-modal"', settings_response.data)
        self.assertNotIn(b'CleanHouse Advanced Monitor', settings_response.data)
        settings_response.close()

    def test_overview_keeps_old_views_and_links_existing_new_pages(self):
        source = (ROOT/'frontend/investigations.html').read_text()
        for view in ('home','applications','network','files','custom'):
            self.assertIn('data-view-panel="'+view+'"', source)
        for route in ('zaelith','identity','reports','help','advanced'):
            self.assertIn('href="/'+route+'"', source)

    def test_allowed_threats_handlers_use_only_disposable_storage(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CLEANHOUSE_ALLOWED_THREATS_PATH': str(Path(tmp)/'allowed.json')}):
            bp = Blueprint('fixture', __name__)
            ns = dict(bp=bp,Path=Path,os=os,json=json,Any=Any,datetime=datetime,timezone=timezone,hashlib=hashlib,jsonify=jsonify,request=request)
            selected('backend/api/cleanhouse.py', ['_now_iso','_artifact_id','_allowed_threats_path','_read_allowed_threats_state','_write_allowed_threats_state','_allowed_threat_string','_allowed_threat_evidence_refs','_allowed_threat_from_payload','allowed_threats_list','allowed_threats_create','allowed_threats_delete'],ns)
            ns['_parse_json_payload']=lambda: (request.get_json(),None)
            app=Flask(__name__);app.register_blueprint(bp);client=app.test_client()
            self.assertEqual(client.get('/cleanhouse/allowed-threats').json['count'],0)
            created=client.post('/cleanhouse/allowed-threats',json={'threat_name':'fixture'}).json['allowed_threat']
            self.assertEqual(client.get('/cleanhouse/allowed-threats').json['count'],1)
            self.assertEqual(client.delete('/cleanhouse/allowed-threats/'+created['id']).json['count'],0)
            self.assertEqual(client.delete('/cleanhouse/allowed-threats/missing').status_code,404)

    def test_zaelith_report_constructor_and_readback(self):
        ns=dict(dataclass=dataclass,field=field,Dict=Dict,Any=Any,copy=copy,datetime=datetime,hashlib=hashlib,json=json)
        selected('backend/api/cleanhouse_monitoring.py',['SessionReport','_now_iso','_fingerprint'],ns)
        selected('backend/api/cleanhouse_monitoring.py',['build_zaelith_report','get_report'],ns,parent='CleanHouseMonitoringAdapter')
        adapter=SimpleNamespace(_lock=threading.RLock(),_reports={},persistence_enabled=False)
        report=ns['build_zaelith_report'](adapter,analysis={'success':True,'summary':{},'zaelith_report':{}},response='fixture '*100)
        self.assertEqual(report['status'],'ok');self.assertEqual(report['report_type'],'zaelith_audit')
        self.assertEqual(report['concern_letter'],{})
        self.assertEqual(ns['get_report'](adapter,report['id'])['id'],report['id'])
        self.assertEqual(ns['get_report'](adapter,'../outside')['status'],'error')
        self.assertEqual(ns['get_report'](adapter,'missing')['status'],'not_found')
        self.assertFalse(report['receipt']['metadata']['full_text_retained'])

    def test_client_methods_and_backend_routes_are_present(self):
        source=(ROOT/'frontend/js/api-client.js').read_text()
        for method in ['getReport','getReports','listConnectedAccounts','startAccountConnect','analyzeZaelithText','getAllowedThreats','deleteAllowedThreat']:
            self.assertIn('async '+method+'(',source)
        server=(ROOT/'backend/api/cleanhouse.py').read_text()
        for route in ['/cleanhouse/reports/<path:report_id>','/cleanhouse/zaelith/analyze','/cleanhouse/accounts','/cleanhouse/accounts/connect/start','/cleanhouse/allowed-threats','/cleanhouse/allowed-threats/<allowed_id>']:
            self.assertIn('"'+route+'"',server)

if __name__ == '__main__': unittest.main()
