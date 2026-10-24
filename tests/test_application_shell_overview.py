from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from backend.api import cleanhouse


ROOT = Path(__file__).resolve().parents[1]


class OverviewApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            key: os.environ.get(key)
            for key in ("CLEANHOUSE_ENABLE_AUTH", "CLEANHOUSE_REQUIRE_LOGIN")
        }
        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "0"
        os.environ["CLEANHOUSE_REQUIRE_LOGIN"] = "0"
        app = Flask(__name__)
        app.secret_key = "overview-focused-test"
        app.register_blueprint(cleanhouse.bp)
        app.testing = True
        self.client = app.test_client()

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @staticmethod
    def files_payload(state="live", **overrides):
        collector = {
            "health": state,
            "provider": "wazuh" if state in {"live", "no_data"} else "none",
            "lifecycle": "scanning" if state == "live" else state,
            "configured": state not in {"unavailable", "fallback"},
            "operational": state in {"live", "no_data"},
            "evidence_authenticated": state in {"live", "no_data"},
            "fallback": {"active": state == "fallback", "reason": "wazuh_not_operational"},
        }
        collector.update(overrides.pop("collector", {}))
        return {
            "status": state,
            "collector": collector,
            "powered_by_wazuh": bool(overrides.pop("powered_by_wazuh", state == "live")),
            "events": overrides.pop("events", []),
            **overrides,
        }

    def test_complete_contract_reports_live_without_exposing_raw_diagnostics(self):
        runtime = {
            "ready": True,
            "runtime_state": "warm",
            "reason_codes": [],
            "secret": "do-not-return",
        }
        network = {"state": "running", "reason_code": "", "private_path": "/Users/private"}
        files = self.files_payload(
            "live",
            events=[{"path": "/Users/private/file", "token": "bearer-secret"}],
            collector={"manager": "https://private.invalid"},
        )
        with patch.object(cleanhouse, "_runtime_readiness_payload", return_value=runtime), patch.object(
            cleanhouse.network_runtime, "network_collector_health", return_value=network
        ), patch.object(cleanhouse, "_files_snapshot", return_value=files):
            response = self.client.get("/cleanhouse/overview")

        payload = response.get_json()
        serialized = json.dumps(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["schema"], "cleanhouse.overview.v1")
        self.assertEqual(payload["state"], "live")
        self.assertTrue(payload["runtime"]["ready"])
        self.assertTrue(payload["network"]["operational"])
        self.assertTrue(payload["files"]["evidence_authenticated"])
        self.assertTrue(payload["files"]["powered_by_wazuh"])
        self.assertNotIn("/Users/private", serialized)
        self.assertNotIn("bearer-secret", serialized)
        self.assertNotIn("private.invalid", serialized)
        self.assertNotIn("do-not-return", serialized)

    def test_capture_engine_absence_and_files_unavailable_are_degraded(self):
        with patch.object(cleanhouse, "_runtime_readiness_payload", return_value={
            "ready": True,
            "runtime_state": "warm",
            "reason_codes": [],
        }), patch.object(
            cleanhouse.network_runtime,
            "network_collector_health",
            return_value={"state": "degraded", "reason_code": "capture_engine_unavailable"},
        ), patch.object(cleanhouse, "_files_snapshot", return_value=self.files_payload("unavailable")):
            payload = self.client.get("/cleanhouse/overview").get_json()

        self.assertEqual(payload["state"], "degraded")
        self.assertEqual(payload["network"]["state"], "degraded")
        self.assertEqual(payload["network"]["reason_code"], "capture_engine_unavailable")
        self.assertFalse(payload["network"]["operational"])
        self.assertEqual(payload["files"]["state"], "unavailable")
        self.assertFalse(payload["files"]["operational"])
        self.assertFalse(payload["files"]["powered_by_wazuh"])

    def test_files_fallback_prevents_overall_live_claim(self):
        with patch.object(cleanhouse, "_runtime_readiness_payload", return_value={
            "ready": True,
            "runtime_state": "warm",
            "reason_codes": [],
        }), patch.object(
            cleanhouse.network_runtime,
            "network_collector_health",
            return_value={"state": "running", "reason_code": ""},
        ), patch.object(cleanhouse, "_files_snapshot", return_value=self.files_payload("fallback")):
            payload = self.client.get("/cleanhouse/overview").get_json()

        self.assertEqual(payload["state"], "degraded")
        self.assertEqual(payload["files"]["state"], "fallback")
        self.assertTrue(payload["files"]["fallback_active"])
        self.assertFalse(payload["files"]["powered_by_wazuh"])

    def test_runtime_readiness_remains_authoritative(self):
        with patch.object(cleanhouse, "_runtime_readiness_payload", return_value={
            "ready": False,
            "runtime_state": "recovering",
            "reason_codes": ["heartbeat_stale"],
        }), patch.object(
            cleanhouse.network_runtime,
            "network_collector_health",
            return_value={"state": "running", "reason_code": ""},
        ), patch.object(cleanhouse, "_files_snapshot", return_value=self.files_payload("live")):
            payload = self.client.get("/cleanhouse/overview").get_json()

        self.assertEqual(payload["state"], "warming")
        self.assertFalse(payload["runtime"]["ready"])
        self.assertEqual(payload["runtime"]["reason_codes"], ["heartbeat_stale"])

    def test_independent_status_failures_fail_closed_without_breaking_route(self):
        with patch.object(cleanhouse, "_runtime_readiness_payload", return_value={
            "ready": True,
            "runtime_state": "warm",
            "reason_codes": [],
        }), patch.object(
            cleanhouse.network_runtime, "network_collector_health", side_effect=RuntimeError("private network response")
        ), patch.object(cleanhouse, "_files_snapshot", side_effect=RuntimeError("private files response")):
            response = self.client.get("/cleanhouse/overview")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["state"], "degraded")
        self.assertEqual(payload["network"]["reason_code"], "network_status_unavailable")
        self.assertEqual(payload["files"]["fallback_reason"], "files_status_unavailable")
        self.assertNotIn("private network response", json.dumps(payload))
        self.assertNotIn("private files response", json.dumps(payload))

    def test_overview_status_requires_existing_session_contract(self):
        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "1"
        os.environ["CLEANHOUSE_REQUIRE_LOGIN"] = "1"
        response = self.client.get("/cleanhouse/overview")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "Authentication required")


class ApplicationShellStaticTests(unittest.TestCase):
    def test_shell_has_only_proven_primary_destinations(self):
        html = (ROOT / "frontend" / "investigations.html").read_text(encoding="utf-8")
        for destination in ("/overview", "/applications", "/network", "/files", "/dashboard"):
            self.assertIn(f'href="{destination}"', html)
        for excluded in ("/zaelith", "/identity", "/reports", "/help", "/allowed-threats"):
            self.assertNotIn(f'href="{excluded}"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn('/js/overview.js?v=1', html)
        self.assertIn('/css/overview.css?v=1', html)

    def test_overview_copy_starts_unknown_and_does_not_fabricate_findings(self):
        html = (ROOT / "frontend" / "investigations.html").read_text(encoding="utf-8")
        self.assertIn("Loading CleanHouse status", html)
        self.assertNotIn("No active threats detected", html)
        self.assertNotIn("Ready to check", html)
        self.assertIn("Powered by Wireshark", html)
        self.assertNotIn("Powered by Wazuh", html)

    def test_overview_route_is_canonical_in_client_history(self):
        script = (ROOT / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        self.assertIn("if (view === 'home') history.replaceState(null, '', '/overview');", script)
        self.assertNotIn("if (view === 'home') history.replaceState(null, '', '/investigations');", script)
        self.assertIn("aria-current", script)
        self.assertIn("popstate", script)

    def test_primary_navigation_uses_real_routes(self):
        script = (ROOT / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        self.assertNotIn("document.querySelectorAll('[data-view]').forEach(link", script)

    def test_notification_routing_lazily_loads_applications(self):
        script = (ROOT / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        self.assertIn("if (!applications.length && window.CleanHouseAPI?.getApplications)", script)
        self.assertIn("await loadApplications(false);", script)
        self.assertLess(script.index("await loadApplications(false);"), script.index("const route = routeForNotification(notification);", script.index("async function openNotification")))

    def test_mobile_notification_control_clears_sticky_navigation(self):
        stylesheet = (ROOT / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")
        mobile = stylesheet[stylesheet.index("@media (max-width: 980px)"):]
        self.assertIn(".corner-actions {", mobile)
        self.assertIn("top: 66px;", mobile)
        self.assertIn("z-index: 6;", mobile)

    def test_missing_click_trace_asset_is_not_requested_by_auth_pages(self):
        for name in ("login.html", "signup.html", "account-delete.html"):
            html = (ROOT / "frontend" / name).read_text(encoding="utf-8")
            self.assertNotIn("click-trace.js", html)

    def test_auth_font_contract_is_self_contained(self):
        stylesheet = (ROOT / "frontend" / "css" / "fonts.css").read_text(encoding="utf-8")
        self.assertIn("--title-font", stylesheet)
        self.assertNotIn("url(", stylesheet)

    def test_authenticated_root_and_login_redirect_to_overview(self):
        server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(server.count("if _has_cleanhouse_session():"), 2)
        self.assertGreaterEqual(server.count("return redirect('/overview', code=302)"), 2)

    def test_desktop_wrapper_opens_canonical_overview(self):
        wrapper = (ROOT / "desktop" / "wrapper.py").read_text(encoding="utf-8")
        self.assertIn('def cleanhouse_url(path: str = "/overview")', wrapper)
        self.assertIn('cleanhouse_url("/overview")', wrapper)
        self.assertNotIn('cleanhouse_url("/dashboard")', wrapper)

    def test_overview_script_bounds_requests_and_sanitizes_rendering(self):
        script = (ROOT / "frontend" / "js" / "overview.js").read_text(encoding="utf-8")
        self.assertIn("AbortController", script)
        self.assertIn("5000", script)
        self.assertIn("response.ok", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("console.", script)


if __name__ == "__main__":
    unittest.main()
