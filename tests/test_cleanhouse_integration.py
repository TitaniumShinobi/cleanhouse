"""
I1 acceptance coverage for v1.
Exercises the minimum full chain and failure boundaries:
- collector success path
- partial collector outage
- full collector outage
- unauthorized scope expansion
"""

import unittest
import sys
import types
import tempfile
import json
import plistlib
import os
import time
from pathlib import Path
from unittest.mock import patch

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")

    class _Blueprint:
        def __init__(self, name, import_name):
            self.name = name
            self.import_name = import_name

        def route(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def after_request(self, func):
            return func

    flask_stub.Blueprint = _Blueprint
    flask_stub.Response = lambda payload="", mimetype=None, **kwargs: {"payload": payload, "mimetype": mimetype, **kwargs}
    flask_stub.jsonify = lambda obj=None, **kwargs: obj if obj is not None else kwargs
    flask_stub.send_file = lambda path, mimetype=None, **kwargs: {"path": path, "mimetype": mimetype, **kwargs}
    flask_stub.request = types.SimpleNamespace(args={}, headers={})
    sys.modules["flask"] = flask_stub

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
from corefiles.collectors.command_observer import get_observer
from corefiles import config


class CleanHouseIntegrationTests(unittest.TestCase):

    def setUp(self):
        self._data_tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        config.DATA_DIR = Path(self._data_tmp.name) / "data"
        get_observer().drain()

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        self._data_tmp.cleanup()

    def _assert_local_evidence(self, refs):
        self.assertGreater(len(refs), 0)
        for ref in refs:
            if isinstance(ref, dict):
                uri = ref.get("uri", "")
            else:
                uri = str(ref)
            self.assertIsInstance(uri, str)
            self.assertTrue(
                uri.startswith("local://cleanhouse/"),
                f"evidence ref {uri} does not start with local://cleanhouse/",
            )

    def _stub_network_with_suspicious_event(self):
        tracer_trace_data = {
            "network_connections": [],
            "suspicious_connections": [
                {
                    "timestamp": "2026-05-22T00:00:00",
                    "process": "curl",
                    "pid": "7777",
                    "process_info": {"pid": "7777", "command": "curl", "user": "dev"},
                    "connection_type": "TCP",
                    "host": "203.0.113.1",
                    "port": 443,
                    "domain": "evil-telemetry.example.com",
                    "address": "203.0.113.1:443",
                    "suspicious": True,
                    "suspicious_reason": "telemetry:telemetry",
                },
            ],
            "unusual_patterns": [],
            "dns_queries": [],
            "process_network_map": {},
            "data_transfer_patterns": [],
            "certificate_info": [],
            "summary": {},
        }

        class DataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                self.trace_data = dict(tracer_trace_data)
                self.monitor_duration = monitor_duration

            def scan_network_connections(self):
                pass

            def scan_dns_queries(self):
                pass

        return DataFlowTracerStub

    def _load_avatar_fixture(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "avatar_runtime_drift_probe.json"
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_app_security_center_is_app_first_and_preserves_advanced_dashboard(self):
        repo_root = Path(__file__).resolve().parents[1]
        html = (repo_root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        js = (repo_root / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")
        dashboard_html = (repo_root / "frontend" / "dashboard.html").read_text(encoding="utf-8")
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")
        cleanhouse_py = (repo_root / "backend" / "api" / "cleanhouse.py").read_text(encoding="utf-8")

        self.assertIn("@app.route('/investigations')", server_py)
        self.assertIn("@app.route('/applications')", server_py)
        self.assertIn("@app.route('/network')", server_py)
        self.assertIn("@app.route('/files')", server_py)
        self.assertIn("@app.route('/custom-scan')", server_py)
        self.assertIn('@bp.route("/cleanhouse/applications"', cleanhouse_py)
        self.assertIn('@bp.route("/cleanhouse/scan/system"', cleanhouse_py)
        self.assertIn('@bp.route("/cleanhouse/network/wireshark"', cleanhouse_py)
        self.assertIn('@bp.route("/cleanhouse/investigations/application"', cleanhouse_py)
        self.assertIn("<title>CleanHouse App Security Center</title>", html)
        self.assertIn("Scan your Mac and prove what your apps are doing.", html)
        self.assertIn('id="system-scan-btn"', html)
        self.assertIn(">Scan</button>", html)
        self.assertIn("Custom scan", html)
        for area in ("Applications", "Files", "Processes", "Network", "Communications"):
            self.assertIn(area, html)
        self.assertIn('id="app-grid"', html)
        self.assertIn('class="app-grid"', html)
        self.assertIn('id="app-dashboard"', html)
        self.assertIn("Scan App", html)
        self.assertIn("App custom scan", html)
        self.assertIn("Scan Selected", html)
        self.assertIn('id="app-custom-scan-toggle"', html)
        self.assertIn('id="app-custom-scan-panel"', html)
        self.assertIn('id="app-custom-process-list"', html)
        self.assertIn("Inside Applications", html)
        self.assertIn("Wireshark evidence engine", html)
        self.assertIn("Scan Network", html)
        self.assertIn("Scan Files", html)
        self.assertIn("Select apps or filters", html)
        self.assertIn("Communication apps", html)
        self.assertIn('aria-label="Overview"', html)
        self.assertIn('class="corner-actions"', html)
        self.assertIn('class="notification-center-button"', html)
        self.assertIn('id="notification-center-button"', html)
        self.assertIn('id="notification-center-menu"', html)
        self.assertIn('id="notification-list"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertNotIn('href="/dashboard#notification-tray-panel"', html)
        self.assertIn('id="notification-center-badge"', html)
        self.assertIn('id="app-route-context"', html)
        self.assertIn('id="network-route-context"', html)
        self.assertIn('id="files-route-context"', html)
        self.assertIn('class="sidebar-brand"', html)
        self.assertIn('/assets/fourstars.svg', html)
        self.assertIn('class="sr-only">CleanHouse security overview</h1>', html)
        self.assertNotIn('<h1>CleanHouse</h1>', html)
        self.assertNotIn('<span class="brand-mark"', html)
        self.assertIn('aria-label="Applications"', html)
        self.assertIn('aria-label="Network"', html)
        self.assertIn('aria-label="Files"', html)
        self.assertIn('aria-label="Advanced"', html)
        self.assertIn('data-label="Overview"', html)
        self.assertNotIn('title="Overview"', html)
        self.assertNotIn('title="Applications"', html)
        self.assertNotIn('title="Network"', html)
        self.assertNotIn('title="Files"', html)
        self.assertNotIn('title="Advanced"', html)
        self.assertNotIn('class="nav-link" href="#custom-scan"', html)
        for first_screen_label in ("Incidents", "Reports", "History"):
            self.assertNotIn(first_screen_label, html)
        self.assertNotIn("What do you want to check?", html)
        self.assertNotIn("Why is Terminal busy?", html)
        self.assertNotIn('id="investigation-question"', html)
        self.assertNotIn("What seems wrong?", html)
        self.assertNotIn("Investigate Selected", html)
        self.assertNotIn("Observed applications and processes", html)
        self.assertNotIn("No action yet", html)
        self.assertNotIn("investigation-cards", html)
        self.assertNotIn("investigation-card", html)
        self.assertNotIn("Question ->", html)

        self.assertIn("getApplications", js)
        self.assertIn("renderApplications", js)
        self.assertIn("openAppDashboard", js)
        self.assertIn("scanSelectedApp", js)
        self.assertIn("scanSelectedProcesses", js)
        self.assertIn("toggleAppCustomScan", js)
        self.assertIn("processRows(selectedApp, false)", js)
        self.assertIn("processRows(selectedApp, true)", js)
        self.assertIn("runSystemScan", js)
        self.assertIn("loadWireshark", js)
        self.assertIn("loadNotificationBadge", js)
        self.assertIn("renderNotificationCenter", js)
        self.assertIn("routeForNotification", js)
        self.assertIn("openNotification", js)
        self.assertIn("findAppForNotification", js)
        self.assertIn("ackNotification", js)
        self.assertIn("getRuntime", js)
        self.assertIn("customFilterMatch", js)
        self.assertIn("runApplicationInvestigation", js)
        self.assertIn("target: selectedApp.path", js)
        self.assertIn("evidence_artifact_path", js)
        self.assertIn("receipt_artifact_path", js)
        self.assertIn(".liquid-sidebar", css)
        self.assertIn("grid-template-columns: 64px minmax(0, 1fr)", css)
        self.assertIn(".nav-icon", css)
        self.assertIn("background: transparent", css)
        self.assertIn("box-shadow: none", css)
        self.assertIn(".nav-link.active::before", css)
        self.assertIn("content: attr(data-label)", css)
        self.assertIn(".corner-actions", css)
        self.assertIn(".notification-center-button", css)
        self.assertIn(".notification-dropdown", css)
        self.assertIn(".notification-item", css)
        self.assertIn(".route-context", css)
        self.assertIn(".notification-center-badge", css)
        self.assertIn(".sidebar-brand", css)
        self.assertNotIn("blur(28px) saturate(160%)", css)
        self.assertNotIn("grid-template-columns: 230px minmax(0, 1fr)", css)
        self.assertIn(".truth-panel", css)
        self.assertIn(".app-grid", css)
        self.assertIn(".app-card", css)
        self.assertIn(".app-icon", css)
        self.assertIn(".app-badge", css)
        self.assertIn(".scan-button", css)
        self.assertIn(".process-row", css)
        self.assertIn(".app-scan-actions", css)
        self.assertIn(".inline-scan-link", css)
        self.assertIn(".app-custom-scan-panel", css)
        self.assertIn(".case-file", css)
        self.assertNotIn(".question-panel", css)
        self.assertNotIn(".example-button", css)
        self.assertNotIn(".investigation-card", css)
        self.assertNotIn(".investigation-cards", css)
        self.assertNotIn(".report-actions", css)
        self.assertNotIn(".history-list", css)

        self.assertIn('href="/investigations"', dashboard_html)
        self.assertIn('href="/dashboard" aria-label="Advanced"', html)
        self.assertNotIn("QPB Action Queue", html)
        self.assertNotIn("Runtime Spine", html)
        self.assertNotIn("Collector Manifest", html)
        self.assertNotIn("Mediator Queue", html)

    def test_application_inventory_auto_adopts_apps_with_badge_contract(self):
        from backend.api import cleanhouse as cleanhouse_module

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_dir = root / "Example.app"
            contents = app_dir / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleName": "Example",
                "CFBundleDisplayName": "Example",
                "CFBundleIdentifier": "com.example.cleanhouse",
                "CFBundleShortVersionString": "1.2.3",
            }))
            state_path = root / "state" / "apps.json"
            with patch.object(cleanhouse_module, "APPLICATION_SEARCH_ROOTS", (root,)), patch.object(cleanhouse_module, "APPLICATION_TARGETS", {}), patch.object(cleanhouse_module, "_load_process_rows", return_value=[]), patch.dict("os.environ", {"CLEANHOUSE_APP_INVENTORY_PATH": str(state_path)}):
                first = cleanhouse_module.list_applications_payload(refresh=True)
                second = cleanhouse_module.list_applications_payload(refresh=True)

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["apps"][0]["name"], "Example")
        self.assertEqual(first["apps"][0]["bundle_id"], "com.example.cleanhouse")
        self.assertEqual(first["apps"][0]["version"], "1.2.3")
        self.assertIn("/cleanhouse/applications/", first["apps"][0]["icon_url"])
        self.assertEqual(first["apps"][0]["badge"], "New")
        self.assertEqual(first["apps"][0]["badge_count"], 1)
        self.assertEqual(second["apps"][0]["badge"], "")
        self.assertEqual(second["apps"][0]["badge_count"], 0)

    def test_wireshark_status_contract_is_explicit(self):
        from backend.api.cleanhouse import _wireshark_status_payload

        payload = _wireshark_status_payload()
        self.assertEqual(payload["engine"], "wireshark")
        self.assertIn(payload["status"], {"available", "missing"})
        self.assertIn("tshark", payload["message"].lower())
        self.assertIn("fallback", payload)

    def test_terminal_investigation_generates_openable_finding_with_artifacts(self):
        repo_root = Path(__file__).resolve().parents[1]
        html = (repo_root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        js = (repo_root / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")

        self.assertIn('id="app-finding-list"', html)
        self.assertIn('id="app-scan-result"', html)
        self.assertIn('id="evidence"', html)
        self.assertIn("Scan App", html)
        self.assertIn("renderAppScan", js)
        self.assertIn("renderEvidence", js)
        self.assertIn("scanSelectedApp", js)
        self.assertIn("Status", js)
        self.assertIn("Evidence Strength", js)
        self.assertIn("evidence_artifact_path", js)
        self.assertIn("receipt_artifact_path", js)
        self.assertIn(".operator-finding-card", css)
        self.assertIn(".finding-meta", css)

        from backend.api.cleanhouse import run_application_investigation

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"CLEANHOUSE_INVESTIGATION_DIR": tmpdir}):
            report = run_application_investigation({
                "session_id": "finding-proof-session",
                "question": "Why is Terminal busy?",
                "target": "terminal",
            })
            evidence_path = Path(report["evidence"]["evidence_artifact_path"])
            receipt_path = Path(report["evidence"]["receipt_artifact_path"])
            self.assertTrue(evidence_path.exists())
            self.assertTrue(receipt_path.exists())
            evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIn("finding_objects", evidence_payload)
            self.assertIn("finding_objects", receipt_payload)

        self.assertEqual(report["status"], "ok")
        self.assertGreaterEqual(len(report["finding_objects"]), 1)
        finding = report["finding_objects"][0]
        required_keys = {
            "id",
            "title",
            "status",
            "severity",
            "confidence",
            "evidence_strength",
            "timestamp",
            "timeline_anchor",
            "observed",
            "inferred",
            "unknown",
            "evidence_refs",
            "receipt_ref",
            "next_action",
        }
        self.assertTrue(required_keys.issubset(finding.keys()))
        self.assertTrue(finding["title"])
        self.assertNotIn(finding["title"], {"Terminal Runtime Activity", "Process Activity", "Application Behavior"})
        self.assertIn(
            finding["title"],
            {
                "Long-running Node Process",
                "Node Process Running Under Terminal",
                "Unexpected Child Process Spawned",
                "Repeated File Access Pattern",
                "Active Network Connection During Idle State",
                "Persistent Background Activity Detected",
                "Terminal Activity Could Not Be Confirmed",
            },
        )
        self.assertEqual(finding["status"], "open")
        self.assertIn(finding["severity"], {"Low", "Medium", "High"})
        self.assertIsInstance(finding["confidence"], int)
        self.assertIn(finding["evidence_strength"], {"Limited", "Moderate", "Strong"})
        self.assertTrue(finding["evidence_strength_basis"])
        self.assertTrue(finding["timestamp"])
        self.assertTrue(finding["timeline_anchor"])
        self.assertGreaterEqual(len(finding["observed"]), 1)
        self.assertTrue(finding["evidence_refs"])
        self.assertTrue(finding["receipt_ref"])
        self.assertTrue(finding["next_action"])

    def test_status_ready_reflects_runtime_self_deviation(self):
        from backend.api import cleanhouse as cleanhouse_module
        from backend import runtime_supervisor

        runtime_payload = {
            "runtime_state": "unhealthy",
            "operator_ready": False,
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
            "resource_guard": {
                "status": "blocked",
                "action": "hard_stop",
                "reason_codes": ["runtime_memory_ceiling_exceeded"],
            },
            "self_deviation": {
                "id": "runtime_self_deviation:test",
                "evidence_artifact_path": "/tmp/evidence.json",
                "receipt_artifact_path": "/tmp/receipt.json",
            },
        }
        with patch.object(cleanhouse_module, "request", types.SimpleNamespace(args={"ready": "1"})), patch.object(
            cleanhouse_module, "jsonify", side_effect=lambda payload=None, **kwargs: payload if payload is not None else kwargs
        ), patch.object(runtime_supervisor, "current_runtime_payload", return_value=runtime_payload), patch.object(
            cleanhouse_module, "_event_spine_payload", return_value={"status": "ok", "degradation": {"degraded": False, "reasons": []}}
        ):
            payload = cleanhouse_module.status()

        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["ready"])
        self.assertIn("runtime_memory_ceiling_exceeded", payload["reason_codes"])
        self.assertIn("CleanHouse is unhealthy", payload["operator_warning"])
        self.assertEqual(payload["runtime"]["self_deviation"]["id"], "runtime_self_deviation:test")

    def test_application_investigation_timeout_records_runtime_self_deviation(self):
        from backend.api import cleanhouse as cleanhouse_module

        def slow_investigation(payload):
            time.sleep(0.05)
            return {"status": "ok"}

        with tempfile.TemporaryDirectory() as runtime_dir, patch.dict(
            os.environ,
            {
                "CLEANHOUSE_RUNTIME_DIR": runtime_dir,
                "CLEANHOUSE_INVESTIGATION_TIMEOUT_SECONDS": "0.001",
            },
        ), patch.object(cleanhouse_module, "run_application_investigation", side_effect=slow_investigation):
            report = cleanhouse_module.run_application_investigation_with_timeout({
                "session_id": "timeout-proof-session",
                "question": "Why did Terminal hang?",
                "target": "terminal",
            })

        self.assertEqual(report["status"], "degraded")
        self.assertIn("investigation_timeout", report["reason_codes"])
        self.assertEqual(report["self_deviation"]["comparison_result"], "Investigation Timeout")
        self.assertEqual(report["self_deviation"]["mitigation_action"], "investigation_pause")
        self.assertTrue(report["next_action"])
        evidence_path = Path(report["evidence"]["evidence_artifact_path"])
        receipt_path = Path(report["evidence"]["receipt_artifact_path"])
        self.assertTrue(evidence_path.is_file())
        self.assertTrue(receipt_path.is_file())
        evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence_payload["comparison_result"], "Investigation Timeout")
        self.assertEqual(receipt_payload["id"], report["self_deviation"]["id"])

    def test_official_signup_uses_cleanhouse_auth_canon(self):
        repo_root = Path(__file__).resolve().parents[1]
        auth_root = repo_root.parent / "auth"
        signup_html = (repo_root / "frontend" / "signup.html").read_text(encoding="utf-8")
        auth_js = (repo_root / "frontend" / "js" / "auth.js").read_text(encoding="utf-8")
        auth_css = (repo_root / "frontend" / "css" / "auth.css").read_text(encoding="utf-8")
        auth_api = (repo_root / "backend" / "api" / "auth.py").read_text(encoding="utf-8")
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")
        simple_webview_auth = (repo_root / "ui" / "simple_webview_auth.py").read_text(encoding="utf-8")
        cleanhouse_config_path = auth_root / "config" / "cleanhouse.json"
        cleanhouse_auth_config = json.loads(cleanhouse_config_path.read_text(encoding="utf-8"))

        self.assertIn('class="official-signup-form"', signup_html)
        self.assertIn('id="turnstile-widget"', signup_html)
        self.assertIn('id="turnstile-helper"', signup_html)
        self.assertIn('/legal/terms', signup_html)
        self.assertIn('/legal/privacy', signup_html)
        self.assertIn('/legal/eeccd', signup_html)
        self.assertIn("Continue with Google", signup_html)
        self.assertIn("Continue with Microsoft", signup_html)
        self.assertIn("Continue with Apple", signup_html)
        self.assertIn("Continue with GitHub", signup_html)
        self.assertIn('id="oauth-google" onclick="signInWithGoogle()" disabled aria-disabled="true"', signup_html)
        self.assertIn('id="oauth-microsoft" onclick="signInWithMicrosoft()" disabled aria-disabled="true"', signup_html)
        self.assertIn('id="oauth-apple" onclick="signInWithApple()" disabled aria-disabled="true"', signup_html)
        self.assertIn('id="oauth-github" onclick="signInWithGithub()" disabled aria-disabled="true"', signup_html)
        self.assertNotIn('id="role"', signup_html)
        self.assertNotIn("Select your role", signup_html)

        self.assertIn("TURNSTILE_SCRIPT_SRC", auth_js)
        self.assertIn("postAuth('/createAccount'", auth_js)
        self.assertIn("turnstileToken", auth_js)
        self.assertIn("consent: consentPayload()", auth_js)
        self.assertIn("loadAuthConfig()", auth_js)
        self.assertIn("function updateSignupOauthState()", auth_js)
        self.assertIn("button.disabled = !accepted", auth_js)
        self.assertIn("addEventListener('change', updateSignupOauthState)", auth_js)
        self.assertIn(".official-signup-form", auth_css)
        self.assertIn(".consent-group", auth_css)
        self.assertIn("appearance: none", auth_css)
        self.assertIn("min-height: 46px", auth_css)
        self.assertIn(".oauth-btn:disabled", auth_css)

        self.assertIn("@app.route('/legal/terms')", server_py)
        self.assertIn("@app.route('/legal/privacy')", server_py)
        self.assertIn("@app.route('/legal/eeccd')", server_py)
        self.assertIn("CLEANHOUSE_TERMS_OF_SERVICE.md", server_py)
        self.assertIn("CLEANHOUSE_PRIVACY_NOTICE.md", server_py)
        self.assertIn("CLEANHOUSE_EUROPEAN_ELECTRONIC_COMMUNICATIONS_CODE_DISCLOSURE.md", server_py)

        self.assertIn("_verify_turnstile_token", auth_api)
        self.assertIn("TURNSTILE_SECRET_KEY", auth_api)
        self.assertIn("turnstileToken", auth_api)
        self.assertIn("cleanhouse:terms", auth_api)
        self.assertIn("cleanhouse:privacy", auth_api)
        self.assertIn("cleanhouse:eeccd", auth_api)

        self.assertIn("/legal/terms", simple_webview_auth)
        self.assertIn("/legal/privacy", simple_webview_auth)
        self.assertIn("/legal/eeccd", simple_webview_auth)
        self.assertIn("turnstileToken", simple_webview_auth)
        self.assertNotIn("Turnstile disabled", simple_webview_auth)
        self.assertNotIn("AI-friendly signup", simple_webview_auth)
        self.assertNotIn('id="role"', simple_webview_auth)
        self.assertNotIn("Select your role", simple_webview_auth)

        self.assertEqual(cleanhouse_auth_config["app"]["id"], "cleanhouse")
        self.assertEqual(cleanhouse_auth_config["redirects"]["postLoginPath"], "/dashboard")
        self.assertIn("http://localhost:3333", cleanhouse_auth_config["allowedOrigins"])
        self.assertIn("http://127.0.0.1:3333", cleanhouse_auth_config["allowedOrigins"])
        self.assertTrue(cleanhouse_auth_config["turnstile"]["required"])
        self.assertTrue(cleanhouse_auth_config["turnstile"]["enabled"])
        doc_keys = {doc["key"] for doc in cleanhouse_auth_config["docs"]}
        self.assertEqual(doc_keys, {"cleanhouse:terms", "cleanhouse:privacy", "cleanhouse:eeccd"})
        provider_ids = {provider["provider"] for provider in cleanhouse_auth_config["providers"]}
        self.assertEqual(provider_ids, {"google", "microsoft", "apple", "github"})

    def test_dashboard_receipt_scope_panel_exposes_receipt_evidence(self):
        repo_root = Path(__file__).resolve().parents[1]
        login_html = (repo_root / "frontend" / "login.html").read_text(encoding="utf-8")
        html = (repo_root / "frontend" / "dashboard.html").read_text(encoding="utf-8")
        js = (repo_root / "frontend" / "js" / "dashboard.js").read_text(encoding="utf-8")
        api_js = (repo_root / "frontend" / "js" / "api-client.js").read_text(encoding="utf-8")
        auth_js = (repo_root / "frontend" / "js" / "auth.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        auth_css = (repo_root / "frontend" / "css" / "auth.css").read_text(encoding="utf-8")
        runtime_gate = (repo_root / "scripts" / "tier1_runtime_gate.py").read_text(encoding="utf-8")
        legacy_signup_py = (repo_root / "ui" / "signup.py").read_text(encoding="utf-8")
        legacy_signup_webview_py = (repo_root / "ui" / "signup_webview.py").read_text(encoding="utf-8")
        legacy_simple_webview_auth_py = (repo_root / "ui" / "simple_webview_auth.py").read_text(encoding="utf-8")
        legacy_webview_auth_py = (repo_root / "ui" / "webview_auth.py").read_text(encoding="utf-8")
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")

        self.assertIn('id="receipt-scope-panel"', html)
        self.assertIn('class="brand-wordmark"', login_html)
        self.assertIn('/assets/cleanhouse.png', login_html)
        self.assertNotIn("Test API Connection", login_html)
        self.assertIn('id="scope-cluster-count"', html)
        self.assertIn('id="receipt-scope-body"', html)
        self.assertIn('id="operator-workstation"', html)
        self.assertIn('id="session-bar"', html)
        self.assertIn('id="operator-session-input"', html)
        self.assertIn('id="objective-declaration-form"', html)
        self.assertIn('id="objective-text"', html)
        self.assertIn("const AUTH_BASE_PATH = '/api/auth'", auth_js)
        self.assertIn("postAuth('/login'", auth_js)
        self.assertIn("/oauth/${encodeURIComponent(provider)}", auth_js)
        self.assertNotIn("showError('Authentication backend unavailable. Enable auth routes and retry.');", auth_js)
        self.assertIn("os.environ.get('CLEANHOUSE_ENABLE_AUTH', '1')", server_py)
        self.assertIn("{'0', 'false', 'no', 'off'}", server_py)
        self.assertIn('id="objective-scope"', html)
        self.assertIn('id="objective-context"', html)
        self.assertIn('id="objective-tool"', html)
        self.assertIn('id="declare-objective-btn"', html)
        self.assertIn('id="operational-presence-panel"', html)
        self.assertIn('id="operational-presence-state"', html)
        self.assertIn('id="operational-presence-body"', html)
        self.assertIn('id="active-context-panel"', html)
        self.assertIn('id="active-context-state"', html)
        self.assertIn('id="active-context-body"', html)
        self.assertIn('id="active-context-follow-btn"', html)
        self.assertIn('id="native-report-panel"', html)
        self.assertIn('id="native-report-count"', html)
        self.assertIn('id="native-report-body"', html)
        self.assertIn('id="runtime-presence-panel"', html)
        self.assertIn('id="runtime-presence-count"', html)
        self.assertIn('id="runtime-presence-body"', html)
        self.assertIn('id="continuity-provenance-panel"', html)
        self.assertIn('id="continuity-provenance-state"', html)
        self.assertIn('id="continuity-provenance-body"', html)
        self.assertIn('placeholder="Describe the requested change"', html)
        self.assertIn('placeholder="Allowed path or scope"', html)
        self.assertIn('placeholder="Session context"', html)
        self.assertNotIn("Update only the requested avatar target", html)
        self.assertNotIn("assets/avatars/requested", html)
        self.assertNotIn("avatar substitution UX verification", html)
        self.assertIn("Enable Browser Notifications", html)
        self.assertIn("Dashboard Notifications", html)
        self.assertIn('id="objective-feed-panel"', html)
        self.assertIn('id="mutation-stream-panel"', html)
        self.assertIn('id="deviation-alert-panel"', html)
        self.assertIn('id="approval-required-panel"', html)
        self.assertIn('id="receipt-replay-panel"', html)
        self.assertIn('id="notification-tray"', html)
        self.assertIn('id="collector-manifest-panel"', html)
        self.assertIn('id="lineage-graph-panel"', html)
        self.assertIn('id="rollback-replay-panel"', html)
        self.assertIn('id="operator-verification-panel"', html)
        self.assertIn('id="collector-manifest-body"', html)
        self.assertIn('id="lineage-graph-body"', html)
        self.assertIn('id="rollback-replay-body"', html)
        self.assertIn('id="operator-verification-body"', html)

        self.assertIn("fetchReceiptScope(currentSessionId)", js)
        self.assertIn("fetchWorkstation(currentSessionId)", js)
        self.assertIn("fetchNativeReports()", js)
        self.assertIn("fetchRuntime()", js)
        self.assertIn("function renderWorkstation(data)", js)
        self.assertIn("function renderRuntime(runtime)", js)
        self.assertIn("function focusRuntimeNotification(notificationId)", js)
        self.assertIn("function renderOperationalPresence(presence)", js)
        self.assertIn("function renderNativeReports(reports)", js)
        self.assertIn("function openStoredReport(reportId)", js)
        self.assertIn("login_report_id", js)
        self.assertIn("function renderPresenceIntervention(intervention", js)
        self.assertIn("function renderContinuityProvenance(provenance)", js)
        self.assertIn("data.continuity_provenance", js)
        self.assertIn("Accept Continuity", js)
        self.assertIn("Ignore", js)
        self.assertIn("Search Deeper", js)
        self.assertIn("Pin Canonical Context", js)
        self.assertIn("function acceptContinuity()", js)
        self.assertIn("function ignoreContinuity()", js)
        self.assertIn("function searchContinuityDeeper()", js)
        self.assertIn("function pinCanonicalContext()", js)
        self.assertIn("recordContinuityDecision", js)
        self.assertIn("pinContinuityContext", js)
        self.assertIn("searchContinuity(sessionId", js)
        self.assertIn("Review Evidence", js)
        self.assertIn("Stabilize", js)
        self.assertIn("Copy Correction", js)
        self.assertIn("function reviewPresenceEvidence()", js)
        self.assertIn("function stabilizePrimaryIntervention()", js)
        self.assertIn("function copyPrimaryCorrection()", js)
        self.assertIn("resolveApprovalQueueItem", js)
        self.assertIn("prompt_type: 'stabilization'", js)
        self.assertIn("parent_intervention_id", js)
        self.assertIn("data.operational_presence", js)
        self.assertIn("function declareObjective(event)", js)
        self.assertIn("window.CleanHouseAPI.submitPrompt", js)
        self.assertIn("window.CleanHouseAPI.startObjective", js)
        self.assertIn("function startSelectedSession()", js)
        self.assertIn("startOperatorSession", js)
        self.assertIn("function renderObjectiveFeed(objectives)", js)
        self.assertIn("function renderMutationStream(mutations)", js)
        self.assertIn("function renderDeviationPanel(deviationSignals, evidenceSummaries)", js)
        self.assertIn("function renderApprovalRequired(approvals)", js)
        self.assertIn("function renderWorkstationReplay(receipts, replays)", js)
        self.assertIn("function renderNotificationTray(notifications)", js)
        self.assertIn("fetchTier1Surfaces(currentSessionId)", js)
        self.assertIn("function fetchTier1Surfaces(sessionId)", js)
        self.assertIn("function renderCollectorManifest(manifest)", js)
        self.assertIn("function renderLineageGraph(graph)", js)
        self.assertIn("function renderRollbackReplayState(state)", js)
        self.assertIn("function renderOperatorVerification(verification)", js)
        self.assertIn("function renderTier1Unavailable(message)", js)
        self.assertIn("getCollectorManifest(false)", js)
        self.assertIn("getLineageGraph(sessionId)", js)
        self.assertIn("getRollbackReplayState(sessionId)", js)
        self.assertIn("getOperatorVerification(sessionId)", js)
        self.assertIn("function requestDashboardNotificationPermission()", js)
        self.assertIn("Notification.permission", js)
        self.assertIn("Notification.requestPermission", js)
        self.assertIn("function maybeSendBrowserNotifications(notifications)", js)
        self.assertIn("new URLSearchParams(window.location.search", js)
        self.assertIn("function focusDashboardNotification(notification)", js)
        self.assertIn("function focusNotificationRow(notificationId)", js)
        self.assertIn("function applyPendingDashboardFocus()", js)
        self.assertIn("notification.onclick", js)
        self.assertIn("data-notification-id", js)
        self.assertNotIn("simulate drift", js.lower())
        self.assertNotIn("simulate drift", html.lower())
        self.assertNotIn("browser automation", js.lower())
        self.assertNotIn("browser automation", html.lower())
        self.assertNotIn("personality continuity", js.lower())
        self.assertNotIn("personality continuity", html.lower())
        self.assertNotIn("persistent identity", js.lower())
        self.assertNotIn("persistent identity", html.lower())
        render_continuity_chunk = js.split("function renderContinuityProvenance", 1)[1].split("function renderObjectiveFeed", 1)[0]
        refresh_chunk = js.split("async function refreshAll()", 1)[1].split("async function fetchTimeline", 1)[0]
        self.assertNotIn("window.CleanHouseAPI.searchContinuity", render_continuity_chunk)
        self.assertNotIn("searchContinuity", refresh_chunk)
        self.assertNotIn("Copy deterministic receipt summary", js)
        self.assertIn("function renderReceiptScope(receipts", js)
        self.assertIn("function renderReceiptApprovalActions(receipt, approval)", js)
        self.assertIn("function handleReceiptApprovalAction(receiptId, action)", js)
        self.assertIn("function handleWorkstationApprovalAction(approvalId, action)", js)
        self.assertIn("function fetchReceiptReplays(receipts)", js)
        self.assertIn("function renderApprovalHistory(approval)", js)
        self.assertIn("function renderReceiptReplay(replay)", js)
        self.assertIn("function getReceiptReviewNote(receiptId)", js)
        self.assertIn("analysis.scope_weight", js)
        self.assertIn("analysis.path_clusters", js)
        self.assertIn("collectReceiptEvidenceRows(receipt)", js)
        self.assertIn("getReceiptReplay", js)
        self.assertIn("createApprovalQueueItem", js)
        self.assertIn("resolveApprovalQueueItem", js)
        self.assertIn("Needs review", js)
        self.assertIn("Reviewer note", js)
        self.assertIn("State Replay", js)
        self.assertIn("receiptApprovalEvidenceRefs(receipt)", js)
        self.assertIn("receipt.evidence_index", js)
        self.assertIn("Clustered Paths", js)
        self.assertIn("Evidence Refs", js)
        self.assertIn("scope_weight", js)

        self.assertIn("async getReceiptReplay(receiptId)", api_js)
        self.assertIn("async submitPrompt(text", api_js)
        self.assertIn("async startObjective(sessionId", api_js)
        self.assertIn("options = {}", api_js)
        self.assertIn("payload.prompt_type", api_js)
        self.assertIn("payload.parent_intervention_id", api_js)
        self.assertIn("payload.evidence_refs", api_js)
        self.assertIn("payload.metadata", api_js)
        self.assertIn("/cleanhouse/receipt-replay", api_js)
        self.assertIn("async getReceiptBundle(receiptId)", api_js)
        self.assertIn("async importReceiptBundle(bundle)", api_js)
        self.assertIn("async startOperatorSession(sessionId", api_js)
        self.assertIn("/cleanhouse/session/start", api_js)
        self.assertIn("async stopOperatorSession(sessionId", api_js)
        self.assertIn("/cleanhouse/session/stop", api_js)
        self.assertIn("async getWorkstation(sessionId", api_js)
        self.assertIn("/cleanhouse/workstation", api_js)
        self.assertIn("async getActiveContext(refresh", api_js)
        self.assertIn("/cleanhouse/active-context", api_js)
        self.assertIn("async setActiveContextFollow(enabled)", api_js)
        self.assertIn("async ignoreActiveContext(dedupeKey", api_js)
        self.assertIn("async getContinuity(sessionId", api_js)
        self.assertIn("/cleanhouse/continuity", api_js)
        self.assertIn("async pinContinuityContext(sessionId", api_js)
        self.assertIn("/cleanhouse/continuity/pins", api_js)
        self.assertIn("async recordContinuityDecision(sessionId", api_js)
        self.assertIn("/cleanhouse/continuity/decision", api_js)
        self.assertIn("async searchContinuity(sessionId", api_js)
        self.assertIn("/cleanhouse/continuity/search", api_js)
        self.assertIn("async getStatus(refresh", api_js)
        self.assertIn("async getRuntime()", api_js)
        self.assertIn("async getCollectorManifest(refresh", api_js)
        self.assertIn("function cleanHouseHttpOrigin()", api_js)
        self.assertIn("window.location.origin", api_js)
        self.assertIn("async getLineageGraph(sessionId", api_js)
        self.assertIn("async getRollbackReplayState(sessionId", api_js)
        self.assertIn("async getOperatorVerification(sessionId", api_js)
        self.assertIn("function buildLineageGraph(workstation", api_js)
        self.assertIn("function collectorSectionAlias(name)", api_js)
        self.assertIn("/cleanhouse/status", api_js)
        self.assertIn("async ackNotification(notificationId)", api_js)
        self.assertIn("/cleanhouse/notifications/", api_js)
        self.assertIn("/cleanhouse/receipt-bundle", api_js)
        self.assertIn("/cleanhouse/receipt-bundle/import", api_js)
        self.assertIn("reviewer_note", api_js)
        self.assertIn("reviewer", api_js)
        self.assertIn("async buildLoginReport(userId", api_js)
        self.assertIn("/cleanhouse/login-report", api_js)
        self.assertIn("dashboardRedirectWithLoginReport", auth_js)
        self.assertIn("data.login_report", auth_js)
        self.assertIn("AUTH_UNAVAILABLE_MESSAGE", auth_js)
        self.assertNotIn("admin@cleanhouse.local' && password === 'admin123'", auth_js)

        self.assertIn("#receipt-scope-panel", css)
        self.assertIn("backdrop-filter: blur(28px) saturate(145%)", auth_css)
        self.assertIn(".brand-wordmark", auth_css)
        self.assertIn(".workstation", css)
        self.assertIn(".presence-panel", css)
        self.assertIn(".active-context-panel", css)
        self.assertIn(".continuity-panel", css)
        self.assertIn(".continuity-row", css)
        self.assertIn(".continuity-actions", css)
        self.assertIn(".continuity-claim", css)
        self.assertIn(".continuity-failure", css)
        self.assertIn(".continuity-search", css)
        self.assertIn(".presence-row", css)
        self.assertIn(".presence-metrics", css)
        self.assertIn(".presence-actions", css)
        self.assertIn(".presence-highlight", css)
        self.assertIn(".session-bar", css)
        self.assertIn(".objective-declaration", css)
        self.assertIn(".objective-actions", css)
        self.assertIn(".workstation-panel", css)
        self.assertIn(".why-flagged-row", css)
        self.assertIn(".notification-row", css)
        self.assertIn(".receipt-card", css)
        self.assertIn(".receipt-review-actions", css)
        self.assertIn(".receipt-review-note", css)
        self.assertIn(".approval-history", css)
        self.assertIn(".native-report-row", css)
        self.assertIn(".receipt-replay-hash", css)
        self.assertIn(".receipt-action.approve", css)
        self.assertIn(".receipt-action.reject", css)
        self.assertIn(".receipt-action.review", css)
        self.assertIn(".scope-cluster", css)
        self.assertIn(".scope-weight-bar", css)
        self.assertIn(".receipt-evidence-row", css)
        self.assertIn(".tier1-panel", css)
        self.assertIn(".tier1-row", css)
        self.assertIn(".tier1-node", css)
        self.assertIn(".lineage-edge", css)
        self.assertIn(".rollback-row", css)
        self.assertIn(".verification-check", css)

        self.assertIn("Tier 1 runtime gate using CleanHouse HTTP APIs only", runtime_gate)
        self.assertIn("def run_gate(base_url", runtime_gate)
        self.assertIn("def collector_manifest(status", runtime_gate)
        self.assertIn("def lineage_graph(workstation", runtime_gate)
        self.assertIn('"/cleanhouse/status?ready=1"', runtime_gate)
        self.assertIn('"/cleanhouse/status?refresh=1"', runtime_gate)
        self.assertNotIn('STATUS_READY_PATH + "&refresh=1"', runtime_gate)
        self.assertIn('"/cleanhouse/workstation', runtime_gate)
        self.assertIn('"/cleanhouse/receipt-replay?', runtime_gate)
        self.assertIn('"/cleanhouse/receipt-bundle?', runtime_gate)
        self.assertIn('"no_browser_operator_verification": True', runtime_gate)
        self.assertIn('"browser_automation_used": False', runtime_gate)

        self.assertNotIn("Fallback simulation", legacy_signup_py)
        self.assertNotIn("Fallback simulation", legacy_simple_webview_auth_py)
        self.assertNotIn("simulate a successful login", legacy_webview_auth_py)
        self.assertNotIn("simulate success", legacy_signup_webview_py)
        self.assertIn("Authentication backend unavailable", legacy_signup_py)
        self.assertIn("Authentication backend unavailable", legacy_simple_webview_auth_py)

    def test_acceptance_chain_success_declared_prompt_command_diff_network(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        intent_result = adapter.submit_intent(
            "pipeline acceptance test", scope="src/", tool_identity="CleanHouse"
        )
        self.assertEqual(intent_result["status"], "ok")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "pipeline-step"], capture_output=True)
        get_observer().run(["echo", "pipeline-step-2"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("v1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "main.py").write_text("v2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            diff_result = adapter.compute_diff(
                before["id"], after["id"], session_id=intent_id
            )
            self.assertEqual(diff_result["status"], "ok")

        with patch(
            "backend.api.cleanhouse_monitoring.DataFlowTracer",
            self._stub_network_with_suspicious_event(),
        ):
            network_result = adapter.get_network(refresh=True)

        self.assertEqual(network_result["status"], "warning")
        self.assertEqual(len(network_result["issues"]), 1)
        self._assert_local_evidence(network_result["issues"][0]["evidence_refs"])

        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")
        self.assertGreaterEqual(timeline["entry_count"], 3)
        event_types = [e["event_type"] for e in timeline["entries"]]
        self.assertIn("intent", event_types)
        self.assertIn("command", event_types)
        self.assertIn("diff", event_types)

        corr = adapter.correlate(session_id=intent_id)
        self.assertEqual(corr["status"], "ok")
        self.assertGreaterEqual(corr["edge_count"], 2)

        signals = adapter.classify(session_id=intent_id)
        self.assertEqual(signals["status"], "ok")
        self.assertGreaterEqual(signals["signal_count"], 0)

        alerts = adapter.generate_alerts(session_id=intent_id)
        self.assertEqual(alerts["status"], "ok")
        self.assertGreaterEqual(alerts["alert_count"], 0)

        receipt = adapter.build_receipt(session_id=intent_id)
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["session_id"], intent_id)
        self.assertIn("metadata", receipt)
        self.assertIn("summary", receipt)
        self.assertIn("events", receipt)
        self.assertIn("alerts", receipt)
        self.assertIn("evidence_index", receipt)
        self.assertIn("integrity", receipt)
        self.assertGreaterEqual(len(receipt["events"]), 3)
        self.assertGreater(len(receipt["evidence_index"]), 0)
        for entry in receipt["evidence_index"]:
            self.assertIn("ref", entry)
            self.assertTrue(
                entry["ref"].startswith("local://cleanhouse/"),
                f"evidence ref {entry['ref']} does not start with local://cleanhouse/",
            )

        report = adapter.build_report(
            session_id=intent_id,
            report_type="audit",
            contact="ops@example.com",
            target="staging",
            context="pipeline test",
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["report_type"], "audit")
        self.assertGreater(len(report["evidence_links"]), 0)
        for link in report["evidence_links"]:
            self.assertTrue(
                link.startswith("local://cleanhouse/"),
                f"evidence link {link} does not start with local://cleanhouse/",
            )
        self.assertIn("receipt", report)
        self.assertIn("integrity", report)
        self.assertIn("root_hash", report["integrity"])

    def test_avatar_substitution_fixture_records_scope_deviation(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt_result = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="avatar substitution incident canonical fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="avatar-substitution",
            objective_id="objective-avatar-substitution",
        )
        self.assertEqual(prompt_result["status"], "ok")
        session_id = prompt_result["session_id"]

        get_observer().run(["echo", "avatar-substitution-action"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested_dir = root / "assets" / "avatars" / "requested"
            substituted_dir = root / "assets" / "avatars" / "substituted"
            requested_dir.mkdir(parents=True)
            substituted_dir.mkdir(parents=True)
            (requested_dir / "avatar.png").write_text("requested-v1")
            (substituted_dir / "avatar.png").write_text("substitute-v1")

            before = adapter.create_snapshot(
                repo_path=str(root),
                label="before-avatar",
                session_id=session_id,
            )
            (substituted_dir / "avatar.png").write_text("substitute-v2")
            after = adapter.create_snapshot(
                repo_path=str(root),
                label="after-avatar",
                session_id=session_id,
            )
            diff = adapter.compute_diff(before["id"], after["id"], session_id=session_id)

        self.assertEqual(diff["status"], "ok")
        self.assertEqual(diff["modified_count"], 1)
        approval = adapter.create_approval_queue_item({
            "session_id": session_id,
            "requested_action": "review avatar substitution mutation",
            "reason": "observed changed path outside declared avatar target scope",
            "prompt_id": prompt_result["id"],
            "objective_id": "objective-avatar-substitution",
            "evidence_refs": [f"local://cleanhouse/diff/{diff['id']}"],
            "metadata": {"fixture": "avatar_substitution"},
        })
        self.assertEqual(approval["status"], "ok")

        timeline = adapter.build_timeline(session_id=session_id)
        self.assertEqual(timeline["status"], "ok")
        event_types = [entry["event_type"] for entry in timeline["entries"]]
        self.assertIn("prompt", event_types)
        self.assertIn("command", event_types)
        self.assertIn("diff", event_types)
        self.assertIn("approval_queue", event_types)

        corr = adapter.correlate(session_id=session_id)
        self.assertEqual(corr["status"], "ok")

        signals = adapter.classify(session_id=session_id)
        deviations = [
            signal for signal in signals["signals"]
            if signal["signal_class"] == "deviation" and signal["source"] == "diff"
        ]
        self.assertGreaterEqual(len(deviations), 1)
        self.assertEqual(deviations[0]["observed_vs_expected"]["status"], "unexpected")
        self.assertIn("outside declared scope", deviations[0]["description"])

        alerts = adapter.generate_alerts(session_id=session_id)
        scope_alerts = [
            alert for alert in alerts["alerts"]
            if alert["alert_type"] == "scope_expansion"
        ]
        self.assertGreaterEqual(len(scope_alerts), 1)

        receipt = adapter.build_receipt(session_id=session_id)
        self.assertEqual(receipt["status"], "ok")
        receipt_event_types = [entry["event_type"] for entry in receipt["events"]]
        self.assertIn("prompt", receipt_event_types)
        self.assertIn("approval_queue", receipt_event_types)
        self.assertEqual(receipt["metadata"]["objective_id"], "objective-avatar-substitution")
        self.assertGreater(len(receipt["evidence_index"]), 0)
        fixture = self._load_avatar_fixture()["scenarios"]["out-of-scope-traversal"]
        scope_analysis = receipt["scope_analysis"]
        self.assertEqual(scope_analysis["classification"], fixture["classification"])
        self.assertEqual(scope_analysis["scope_weight"], fixture["scope_weight"])
        self.assertEqual(scope_analysis["changed_paths"], fixture["changed_paths"])
        self.assertEqual(scope_analysis["out_of_scope_count"], 1)
        self.assertEqual(
            scope_analysis["path_clusters"][0]["cluster"],
            fixture["path_clusters"][0]["cluster"],
        )
        self.assertEqual(
            scope_analysis["path_clusters"][0]["relation"],
            fixture["path_clusters"][0]["relation"],
        )
        self.assertIn("declared scope prefix", scope_analysis["path_clusters"][0]["explanation"])

    def test_avatar_expected_mutation_fixture_records_zero_scope_weight(self):
        fixture = self._load_avatar_fixture()["scenarios"]["expected-mutation"]
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt_result = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="avatar expected mutation canonical fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="avatar-expected-mutation",
            objective_id="objective-avatar-expected",
        )
        session_id = prompt_result["session_id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested_dir = root / "assets" / "avatars" / "requested"
            requested_dir.mkdir(parents=True)
            requested_file = requested_dir / "avatar.png"
            requested_file.write_text("requested-v1")

            before = adapter.create_snapshot(
                repo_path=str(root),
                label="before-avatar",
                session_id=session_id,
            )
            requested_file.write_text("requested-v2")
            after = adapter.create_snapshot(
                repo_path=str(root),
                label="after-avatar",
                session_id=session_id,
            )
            adapter.compute_diff(before["id"], after["id"], session_id=session_id)

        adapter.build_timeline(session_id=session_id)
        adapter.correlate(session_id=session_id)
        signals = adapter.classify(session_id=session_id)
        diff_deviations = [
            signal for signal in signals["signals"]
            if signal["signal_class"] == "deviation" and signal["source"] == "diff"
        ]
        self.assertEqual(diff_deviations, [])

        receipt = adapter.build_receipt(session_id=session_id)
        scope_analysis = receipt["scope_analysis"]
        self.assertEqual(scope_analysis["classification"], fixture["classification"])
        self.assertEqual(scope_analysis["scope_weight"], fixture["scope_weight"])
        self.assertEqual(scope_analysis["changed_paths"], fixture["changed_paths"])
        self.assertEqual(scope_analysis["out_of_scope_count"], 0)
        self.assertEqual(
            scope_analysis["path_clusters"][0]["cluster"],
            fixture["path_clusters"][0]["cluster"],
        )
        self.assertEqual(
            scope_analysis["path_clusters"][0]["relation"],
            fixture["path_clusters"][0]["relation"],
        )

    def test_acceptance_partial_collector_outage_keeps_timeline(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("partial outage test", scope="src/")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "partial-outage"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("v1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "main.py").write_text("v2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        class FailingDataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                self.monitor_duration = monitor_duration

            def scan_network_connections(self):
                raise RuntimeError("network scan denied")

            def scan_dns_queries(self):
                pass

        with patch(
            "backend.api.cleanhouse_monitoring.DataFlowTracer",
            FailingDataFlowTracerStub,
        ):
            status = adapter.get_status(refresh=True)

        self.assertEqual(status["status"], "critical")
        network_section = status["data"]["sections"]["network"]
        self.assertEqual(network_section["event_counts"]["collector_failures"], 1)
        self.assertGreaterEqual(network_section["event_counts"]["total"], 1)

        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")
        event_types = [e["event_type"] for e in timeline["entries"]]
        self.assertIn("intent", event_types)
        self.assertIn("command", event_types)
        self.assertIn("diff", event_types)

    def test_acceptance_full_collector_outage_no_timeline_suppression(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("full outage test", scope="src/")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "full-outage"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("v1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "main.py").write_text("v2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        with patch.object(
            adapter,
            "_collect_processes",
            side_effect=RuntimeError("process collector down"),
        ), patch.object(
            adapter, "_collect_network", side_effect=RuntimeError("network collector down")
        ), patch.object(
            adapter, "_collect_ai_activity", side_effect=RuntimeError("ai activity down")
        ), patch.object(
            adapter, "_collect_anomalies", side_effect=RuntimeError("anomalies collector down")
        ), patch.object(
            adapter, "_collect_integrity", side_effect=RuntimeError("integrity down")
        ), patch.object(
            adapter, "_collect_commands", side_effect=RuntimeError("commands collector down")
        ), patch.object(
            adapter, "_collect_cloud_usage", side_effect=RuntimeError("cloud usage down")
        ), patch.object(
            adapter,
            "_collect_tool_events",
            side_effect=RuntimeError("tool events down"),
        ):
            status = adapter.get_status(refresh=True)

        self.assertEqual(status["status"], "critical")
        for section_name in [
            "processes",
            "network",
            "ai_activity",
            "anomalies",
            "integrity",
            "command",
            "cloud_usage",
            "tool_events",
        ]:
            section = status["data"]["sections"][section_name]
            self.assertEqual(
                section["event_counts"]["collector_failures"],
                1,
                f"missing collector failure in {section_name}",
            )

        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")
        event_types = [e["event_type"] for e in timeline["entries"]]
        self.assertIn("intent", event_types)
        self.assertIn("command", event_types)
        self.assertIn("diff", event_types)

    def test_acceptance_scope_expansion_has_evidence_and_confidence_bounds(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("unauthorized scope expansion", scope="src/")
        intent_id = intent_result["id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("v1")
            (root / "config.ini").write_text("setting=1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "main.py").write_text("v2")
            (root / "config.ini").write_text("setting=2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        adapter.build_timeline(session_id=intent_id)
        adapter.correlate(session_id=intent_id)
        adapter.classify(session_id=intent_id)
        alerts = adapter.generate_alerts(session_id=intent_id)

        scope_alerts = [
            alert for alert in alerts["alerts"] if alert["alert_type"] == "scope_expansion"
        ]
        self.assertGreater(len(scope_alerts), 0)
        alert = scope_alerts[0]
        self.assertEqual(alert["alert_type"], "scope_expansion")
        self.assertEqual(alert["source"], "diff")
        self.assertGreaterEqual(alert["confidence"], 0.0)
        self.assertLessEqual(alert["confidence"], 1.0)
        self._assert_local_evidence(alert["evidence_refs"])
