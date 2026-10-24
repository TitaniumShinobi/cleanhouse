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
import subprocess
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

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
        protected_js = (repo_root / "frontend" / "js" / "protected-routes.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")
        help_html = (repo_root / "frontend" / "help.html").read_text(encoding="utf-8")
        dashboard_html = (repo_root / "frontend" / "dashboard.html").read_text(encoding="utf-8")
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")
        launcher_sh = (repo_root / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        wrapper_py = (repo_root / "desktop" / "wrapper.py").read_text(encoding="utf-8")
        cleanhouse_py = (repo_root / "backend" / "api" / "cleanhouse.py").read_text(encoding="utf-8")

        self.assertIn("@app.route('/overview')", server_py)
        self.assertIn("@app.route('/investigations')", server_py)
        self.assertIn("@app.route('/applications')", server_py)
        self.assertIn("@app.route('/network')", server_py)
        self.assertIn("@app.route('/files')", server_py)
        self.assertIn("@app.route('/custom-scan')", server_py)
        self.assertIn("@app.route('/advanced')", server_py)
        self.assertIn("@app.route('/help')", server_py)
        self.assertIn("'/help'", protected_js)
        self.assertIn("return redirect('/advanced', code=302)", server_py)
        self.assertIn('URL="http://${HOST}:${PORT}/overview"', launcher_sh)
        self.assertIn('cleanhouse_url("/overview")', wrapper_py)
        self.assertNotIn('URL="http://localhost:${PORT}/dashboard"', launcher_sh)
        self.assertIn("backend.runtime_supervisor", launcher_sh)
        self.assertIn("PREFLIGHT_ARGS=(preflight", launcher_sh)
        self.assertIn("refusing automatic restart", launcher_sh)
        self.assertIn("backend.runtime_supervisor stop", launcher_sh)
        self.assertIn("--acknowledge-self-deviation", launcher_sh)
        self.assertIn("startup_preflight", (repo_root / "backend" / "runtime_supervisor.py").read_text(encoding="utf-8"))
        self.assertNotIn("CLEANHOUSE_RUNTIME_ALLOW_AFTER_SELF_DEVIATION", launcher_sh)
        self.assertIn('acknowledge_self_deviation', (repo_root / "backend" / "runtime_supervisor.py").read_text(encoding="utf-8"))
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
        self.assertIn("Reconcile Files", html)
        self.assertIn('id="files-mediation-toggle"', html)
        self.assertIn('id="files-mediation-panel"', html)
        self.assertIn('id="files-mediation-open-board"', html)
        self.assertIn('aria-controls="files-mediation-board"', html)
        self.assertIn('aria-expanded="false" title="Open full mediation board"', html)
        self.assertIn('id="files-mediation-board"', html)
        self.assertIn('data-testid="files-mediation-board" hidden inert', html)
        self.assertIn('data-testid="files-mediation-column-queue"', html)
        self.assertIn('data-testid="files-mediation-column-progress"', html)
        self.assertIn('data-testid="files-mediation-column-ready"', html)
        self.assertIn('data-testid="files-mediation-column-ledger"', html)
        self.assertIn("Suggestions are optional until added to the queue.", html)
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
        self.assertIn('aria-label="Help"', html)
        self.assertIn('href="/help"', html)
        self.assertIn('data-label="Help"', html)
        self.assertIn('aria-label="Advanced"', html)
        self.assertIn('data-label="Overview"', html)
        self.assertNotIn('title="Overview"', html)
        self.assertNotIn('title="Applications"', html)
        self.assertNotIn('title="Network"', html)
        self.assertNotIn('title="Files"', html)
        self.assertNotIn('title="Help"', html)
        self.assertNotIn('title="Advanced"', html)
        self.assertNotIn('class="nav-link" href="#custom-scan"', html)
        for first_screen_label in ("Incidents",):
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
        self.assertIn("setFilesMediationPanelOpen", js)
        self.assertIn("setFilesMediationBoardOpen", js)
        self.assertIn("syncFilesMediationView", js)
        self.assertIn("target: selectedApp.path", js)
        self.assertIn("evidence_artifact_path", js)
        self.assertIn("receipt_artifact_path", js)
        self.assertIn(".liquid-sidebar", css)
        self.assertIn("grid-template-columns: 64px minmax(0, 1fr)", css)
        self.assertIn(".nav-icon", css)
        self.assertIn("background: transparent", css)
        self.assertIn("box-shadow: none", css)
        self.assertIn(".nav-link.active::before", css)
        self.assertIn(".sidebar-utility", css)
        self.assertIn(".advanced-entry.active", css)
        self.assertIn("content: attr(data-label)", css)
        self.assertIn(".corner-actions", css)
        self.assertIn(".notification-center-button", css)
        self.assertIn(".notification-dropdown", css)
        self.assertIn(".notification-item", css)
        self.assertIn(".route-context", css)
        self.assertIn(".notification-center-badge", css)
        self.assertIn(".sidebar-brand", css)
        self.assertIn(".files-mediation-toggle", css)
        self.assertIn(".files-mediation-panel", css)
        self.assertIn(".files-mediation-board", css)
        self.assertIn(".files-mediation-board__columns", css)
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

        self.assertIn('href="/overview"', dashboard_html)
        self.assertIn("CleanHouse Advanced Monitor", dashboard_html)
        self.assertIn("<title>Help - CleanHouse</title>", help_html)
        self.assertIn('aria-label="Help"', help_html)
        self.assertIn('class="advanced-entry active" href="/help"', help_html)
        self.assertIn("Clean restart ladder", help_html)
        self.assertIn("Request Help", help_html)
        self.assertIn('href="/advanced" aria-label="Advanced"', html)
        self.assertNotIn("CleanHouse Local Monitor", dashboard_html)
        self.assertNotIn("QPB Action Queue", html)
        self.assertNotIn("Runtime Spine", html)
        self.assertNotIn("Collector Manifest", html)
        self.assertNotIn("Mediator Queue", html)

    def test_files_mediation_shell_matches_code_transition_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        html = (repo_root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        js = (repo_root / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")

        self.assertIn('id="files-mediation-toggle"', html)
        self.assertIn('aria-controls="files-mediation-panel"', html)
        self.assertGreater(html.index('id="files-mediation-toggle"'), html.index('</main>'))
        self.assertLess(html.index('id="files-mediation-toggle"'), html.index('id="files-mediation-panel"'))
        self.assertIn('id="files-mediation-panel"', html)
        self.assertIn('id="files-mediation-open-board"', html)
        self.assertIn('id="files-mediation-board"', html)
        self.assertIn('id="files-mediation-close-board"', html)
        for column in ("queue", "progress", "ready", "ledger"):
            self.assertIn(f'data-testid="files-mediation-column-{column}"', html)
        self.assertIn("Suggestions are optional until added to the queue.", html)
        self.assertNotIn("No mediations in progress", html)
        self.assertNotIn("No mediations ready for review", html)
        self.assertNotIn("No mediation history", html)
        self.assertIn('id="files-mediation-composer"', html)
        self.assertIn('id="files-mediation-request"', html)
        self.assertIn('id="files-mediation-add-evidence"', html)
        self.assertIn('id="files-mediation-scope"', html)
        self.assertIn('id="files-mediation-submit"', html)
        self.assertIn('id="files-mediation-panel-composer"', html)
        self.assertIn('id="files-mediation-panel-request"', html)
        self.assertIn('id="files-mediation-panel-add-evidence"', html)
        self.assertIn('id="files-mediation-panel-scope"', html)
        self.assertIn('id="files-mediation-panel-submit"', html)
        self.assertEqual(html.count("data-mediation-composer"), 2)
        self.assertNotIn('data-mediation-suggestion="Reconcile current file evidence"', html)
        self.assertNotIn("data-mediation-demo", html)
        quick_panel_html = html.split('id="files-mediation-panel"', 1)[1].split('id="files-mediation-board"', 1)[0]
        self.assertIn('class="files-mediation-summary"', quick_panel_html)
        self.assertNotIn("files-mediation-panel__section", quick_panel_html)
        self.assertNotIn("Recent ledger", quick_panel_html)
        queue_lane_html = html.split('data-testid="files-mediation-column-queue"', 1)[1].split('data-testid="files-mediation-column-progress"', 1)[0]
        ledger_lane_html = html.split('data-testid="files-mediation-column-ledger"', 1)[1].split('</section>', 1)[0]
        self.assertIn('class="files-mediation-summary"', queue_lane_html)
        self.assertIn('id="files-mediation-composer"', queue_lane_html)
        self.assertIn('id="files-mediation-search"', ledger_lane_html)

        self.assertIn("function setFilesMediationPanelOpen", js)
        self.assertIn("function setFilesMediationBoardOpen", js)
        self.assertIn("function syncFilesMediationView", js)
        self.assertIn("function handleFilesMediationOutsideClick", js)
        self.assertIn("board.hidden = !nextOpen", js)
        self.assertIn("board.inert = !nextOpen", js)
        self.assertIn("panel.inert = !panelInteractive", js)
        self.assertIn("panel.contains(document.activeElement)", js)
        self.assertIn("board.contains(document.activeElement)", js)
        self.assertIn("if (filesMediationBoardOpen)", js)
        self.assertIn("if (nextOpen && actionSidebarOpen)", js)
        self.assertIn("if (nextOpen && filesMediationBoardOpen)", js)
        self.assertIn("handleFilesMediationOutsideClick(event)", js)
        self.assertIn("function renderFilesMediationQueue", js)
        self.assertIn("function selectFilesMediationSuggestion", js)
        self.assertIn("function queueFilesMediationRequest", js)
        self.assertIn("function syncFilesMediationComposers", js)
        self.assertIn("let filesMediationDraft = ''", js)
        self.assertIn("(event.metaKey || event.ctrlKey) && event.key === 'Enter'", js)

        self.assertIn(".files-mediation-toggle", css)
        self.assertIn("left: calc(82px + max(0px, (100vw - 1390px) / 2))", css)
        self.assertIn("bottom: 26px", css)
        self.assertIn(".files-mediation-panel.is-open", css)
        mediation_panel_css = css.split(".files-mediation-panel {", 1)[1].split("}", 1)[0]
        control_panel_css = css.split(".action-sidebar {", 1)[1].split("}", 1)[0]
        for shared_rule in (
            "top: 96px",
            "bottom: 76px",
            "height: calc(100vh - 176px)",
            "width: min(360px, calc(100vw - 42px))",
            "border-radius: 12px",
            "box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42)",
            "transition: opacity 160ms ease, transform 160ms ease",
        ):
            self.assertIn(shared_rule, mediation_panel_css)
            self.assertIn(shared_rule, control_panel_css)
        self.assertIn("transform: translateX(calc(-100% - 36px))", mediation_panel_css)
        self.assertNotIn("body.files-mediation-panel-open .main-canvas", css)
        self.assertIn(".files-mediation-board", css)
        mediation_board_css = css.split(".files-mediation-board {", 1)[1].split("}", 1)[0]
        self.assertIn("--mediation-surface: linear-gradient", css)
        self.assertIn("--mediation-board-surface: linear-gradient", css)
        uniform_mediation_surface = "linear-gradient(180deg, rgba(22, 25, 31, 0.96) 0%, rgba(22, 25, 31, 0.96) 68%, rgba(0, 0, 0, 0.96) 100%)"
        self.assertIn(f"--mediation-surface: {uniform_mediation_surface}", css)
        self.assertIn(f"--mediation-board-surface: {uniform_mediation_surface}", css)
        self.assertIn("background: var(--mediation-surface)", mediation_panel_css)
        self.assertIn("background: var(--mediation-board-surface)", mediation_board_css)
        self.assertIn("backdrop-filter: blur(12px) saturate(108%)", mediation_panel_css)
        self.assertIn("backdrop-filter: blur(6px) saturate(106%)", mediation_board_css)
        for floating_rule in (
            "top: 96px",
            "right: 24px",
            "bottom: 76px",
            "left: calc(82px + max(0px, (100vw - 1390px) / 2))",
            "border-radius: 12px",
            "box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42)",
        ):
            self.assertIn(floating_rule, mediation_board_css)
        self.assertNotIn("inset: 0", mediation_board_css)
        self.assertNotIn("animation:", mediation_board_css)
        self.assertNotIn("@keyframes files-mediation-board-enter", css)
        self.assertIn("grid-template-columns: 358px repeat(3, minmax(0, 1fr))", css)
        self.assertIn(".files-mediation-column + .files-mediation-column", css)
        self.assertIn(".files-mediation-composer", css)
        self.assertIn(".files-mediation-composer--panel", css)
        self.assertIn(".files-mediation-suggestions", css)
        self.assertNotIn(".files-mediation-panel__section", css)
        self.assertNotIn(".files-mediation-panel__suggestions", css)

    def test_files_mediation_board_is_quick_panel_extension(self):
        repo_root = Path(__file__).resolve().parents[1]
        html = (repo_root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")

        board_html = html.split('id="files-mediation-board"', 1)[1].split('id="action-sidebar"', 1)[0]
        queue_lane_html = board_html.split('data-testid="files-mediation-column-queue"', 1)[1].split('data-testid="files-mediation-column-progress"', 1)[0]
        ledger_lane_html = board_html.split('data-testid="files-mediation-column-ledger"', 1)[1].split('</section>', 1)[0]

        self.assertEqual(board_html.count('data-testid="files-mediation-column-'), 4)
        self.assertIn('class="files-mediation-summary"', queue_lane_html)
        self.assertIn('files-mediation-composer--panel', queue_lane_html)
        self.assertIn('id="files-mediation-search"', ledger_lane_html)
        self.assertNotIn("files-mediation-board__filters", board_html)
        self.assertNotIn("No mediation", board_html)
        self.assertIn("grid-template-columns: 358px repeat(3, minmax(0, 1fr))", css)
        self.assertIn(".files-mediation-column + .files-mediation-column", css)
        self.assertIn("height: calc(100vh - 176px)", css.split(".files-mediation-board {", 1)[1].split("}", 1)[0])

    def test_files_lineage_tabs_render_from_current_file_evidence(self):
        repo_root = Path(__file__).resolve().parents[1]
        html = (repo_root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        js = (repo_root / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")

        self.assertIn('role="tablist" aria-label="File lineage views"', html)
        for view in ("changes", "findings", "integrity", "locations", "timeline"):
            self.assertIn(f'id="files-tab-{view}"', html)
            self.assertIn(f'data-files-view="{view}"', html)
        self.assertIn('id="files-search"', html)
        self.assertIn('id="reconcile-files-btn" class="files-refresh-pill"', html)
        self.assertNotIn('id="files-watched-locations"', html)

        self.assertIn("function filteredFileEvents", js)
        self.assertIn("function renderFileChanges", js)
        self.assertIn("function renderFileFindings", js)
        self.assertIn("function renderFileIntegrity", js)
        self.assertIn("function renderFileLocations", js)
        self.assertIn("function renderFileTimeline", js)
        self.assertIn("function selectFilesView", js)
        self.assertIn("filesSearchQuery = String(event.target?.value || '')", js)
        self.assertIn("selectFilesView(filesTabs[nextIndex].dataset.filesView", js)
        self.assertIn("<th>Time</th><th>Change</th><th>File</th><th>Actor</th><th>Source</th>", js)
        self.assertNotIn("<th>Location</th>", js)
        self.assertNotIn("<th>Status</th>", js)
        self.assertNotIn("files-row-status", js)

        self.assertIn(".files-display-controls", css)
        self.assertIn(".files-table-wrap", css)
        self.assertIn("overflow-wrap: anywhere", css.split(".files-table td small {", 1)[1].split("}", 1)[0])
        self.assertIn("white-space: normal", css.split(".files-table td small {", 1)[1].split("}", 1)[0])
        self.assertIn(".files-integrity-summary", css)
        self.assertIn(".files-location-row", css)
        self.assertIn(".files-timeline", css)

    def test_cleanhouse_launcher_refuses_open_self_deviation_without_starting(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            evidence_path = Path(home_tmp) / "evidence.json"
            receipt_path = Path(home_tmp) / "receipt.json"
            evidence_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text("{}", encoding="utf-8")
            fake_python = Path(home_tmp) / "fake-python"
            calls_path = Path(home_tmp) / "calls.log"
            fake_python.write_text(f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path(__file__).with_name("calls.log")
with calls.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["-"]:
    source = sys.stdin.read()
    sys.argv = sys.argv[1:]
    exec(compile(source, "<stdin>", "exec"))
if sys.argv[1:4] == ["-m", "backend.runtime_env", "print-path"]:
    print(__file__)
    raise SystemExit(0)
if sys.argv[1:4] == ["-m", "backend.runtime_supervisor", "preflight"]:
    print(json.dumps({{
        "schema": "cleanhouse.runtime_startup_preflight.v1",
        "status": "blocked_self_deviation",
        "should_start": False,
        "self_deviation": {{
            "id": "runtime_self_deviation:test",
            "status": "open",
            "finding": {{"title": "CleanHouse became the suspicious process"}},
            "next_action": "Review evidence before restart.",
            "evidence_artifact_path": {str(evidence_path)!r},
            "receipt_artifact_path": {str(receipt_path)!r},
        }},
        "next_action": "Resolve the current CleanHouse port/process condition, then try cleanhouse again.",
    }}))
    raise SystemExit(1)
raise SystemExit(1)
""", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home_tmp,
                "CLEANHOUSE_RUNTIME_DIR": runtime_tmp,
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_PORT": "45555",
                "CLEANHOUSE_PYTHON": str(fake_python),
                "PYTHONPATH": str(repo_root),
            }
            result = subprocess.run(
                ["/bin/bash", str(repo_root / "scripts" / "cleanhouse-up.sh")],
                cwd=str(repo_root),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            calls = calls_path.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current runtime state is unsafe; refusing automatic restart", result.stderr)
        self.assertIn("CleanHouse became the suspicious process", result.stderr)
        self.assertIn(str(evidence_path), result.stderr)
        self.assertIn(str(receipt_path), result.stderr)
        self.assertIn("backend.runtime_supervisor preflight", calls)
        self.assertNotIn("backend.launch_agent install", calls)
        self.assertNotIn("backend.runtime_supervisor start", calls)
        self.assertNotIn("/dashboard", result.stdout + result.stderr)
        self.assertNotIn("cleanhouse is running", result.stdout + result.stderr)

    def test_cleanhouse_launcher_does_not_refuse_recoverable_self_deviation(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home_tmp:
            fake_python = Path(home_tmp) / "fake-python"
            calls_path = Path(home_tmp) / "calls.log"
            fake_python.write_text("""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path(__file__).with_name("calls.log")
calls.write_text(calls.read_text() + " ".join(sys.argv[1:]) + "\\n" if calls.exists() else " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["-m", "backend.runtime_env", "print-path"]:
    print(__file__)
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "preflight":
    print(json.dumps({
        "schema": "cleanhouse.runtime_startup_preflight.v1",
        "status": "ready_to_start",
        "should_start": True,
        "startup_warning": {
            "type": "recoverable_self_deviation",
            "self_deviation": {"id": "runtime_self_deviation:soft"}
        }
    }))
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "start":
    print(json.dumps({"runtime_state": "unhealthy", "reason_codes": ["test_start_failed"]}))
    raise SystemExit(1)
if sys.argv[1:3] == ["-m", "backend.launch_agent"] and len(sys.argv) > 3 and sys.argv[3] == "install":
    print(json.dumps({"status": "error", "message": "test install stopped before lifecycle"}))
    raise SystemExit(1)
raise SystemExit(1)
""", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home_tmp,
                "CLEANHOUSE_RUNTIME_DIR": str(Path(home_tmp) / "runtime"),
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_PORT": "45556",
                "CLEANHOUSE_PYTHON": str(fake_python),
                "PYTHONPATH": str(repo_root),
            }
            result = subprocess.run(
                ["/bin/bash", str(repo_root / "scripts" / "cleanhouse-up.sh")],
                cwd=str(repo_root),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            calls = calls_path.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backend.runtime_supervisor preflight", calls)
        lifecycle_calls = [
            line for line in calls.splitlines()
            if "backend.runtime_supervisor start" in line or "backend.launch_agent install" in line
        ]
        self.assertEqual(len(lifecycle_calls), 1)
        if sys.platform == "darwin":
            self.assertIn("backend.launch_agent install", lifecycle_calls[0])
        else:
            self.assertIn("backend.runtime_supervisor start", lifecycle_calls[0])
        self.assertNotIn("runtime self-deviation is open; refusing automatic restart", result.stderr)
        self.assertNotIn("Previous CleanHouse self-deviation evidence", result.stderr)
        self.assertNotIn("Finding: CleanHouse became the suspicious process", result.stderr)
        self.assertNotIn("To try again after reviewing evidence", result.stderr)
        self.assertNotIn("/dashboard", result.stdout + result.stderr)

    def test_cleanhouse_launcher_darwin_readiness_failure_never_unloads_launch_agent(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home_tmp:
            fake_python = Path(home_tmp) / "fake-python"
            fake_bin = Path(home_tmp) / "bin"
            fake_bin.mkdir()
            fake_uname = fake_bin / "uname"
            fake_uname.write_text("#!/bin/sh\necho Darwin\n", encoding="utf-8")
            fake_uname.chmod(0o755)
            calls_path = Path(home_tmp) / "calls.log"
            evidence_path = Path(home_tmp) / "evidence.json"
            receipt_path = Path(home_tmp) / "receipt.json"
            evidence_path.write_text("{}", encoding="utf-8")
            receipt_path.write_text("{}", encoding="utf-8")
            fake_python.write_text(f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path(__file__).with_name("calls.log")
calls.write_text(calls.read_text() + " ".join(sys.argv[1:]) + "\\n" if calls.exists() else " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["-m", "backend.runtime_env", "print-path"]:
    print(__file__)
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "preflight":
    print(json.dumps({{
        "schema": "cleanhouse.runtime_startup_preflight.v1",
        "status": "ready_to_start",
        "should_start": True
    }}))
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.launch_agent"] and len(sys.argv) > 3 and sys.argv[3] == "install":
    print(json.dumps({{
        "status": "ok",
        "loaded": True,
        "runtime_root": "/tmp/fixture-runtime",
    }}))
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.launch_agent"] and len(sys.argv) > 3 and sys.argv[3] == "stop":
    print(json.dumps({{"status": "ok", "loaded": False}}))
    raise SystemExit(0)
if len(sys.argv) > 2 and sys.argv[1] == "-":
    target = sys.argv[2]
    if "/cleanhouse/status?ready=1" in target:
        if len(sys.argv) > 4 and sys.argv[4] == "1":
            print("Canonical readiness contract was not satisfied.", file=sys.stderr)
            print("Failed checks: ['heartbeat_fresh']", file=sys.stderr)
        print(json.dumps({{
            "status": "ok",
            "ready": True,
            "runtime_state": "healthy",
            "reason_codes": ["operator_readiness_heartbeat_fresh"],
            "readiness_contract": {{
                "schema": "cleanhouse.runtime_operator_readiness.v1",
                "satisfied": False,
                "checks": {{"runtime_healthy": True}},
                "failed_checks": ["heartbeat_fresh"],
            }},
        }}))
        raise SystemExit(1)
raise SystemExit(1)
""", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "HOME": home_tmp,
                "CLEANHOUSE_RUNTIME_DIR": str(Path(home_tmp) / "runtime"),
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_STARTUP_TIMEOUT_SECONDS": "1",
                "CLEANHOUSE_PORT": "45557",
                "CLEANHOUSE_PYTHON": str(fake_python),
                "PYTHONPATH": str(repo_root),
            }
            result = subprocess.run(
                ["/bin/bash", str(repo_root / "scripts" / "cleanhouse-up.sh")],
                cwd=str(repo_root),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            calls = calls_path.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backend.launch_agent install", calls)
        self.assertNotIn("backend.launch_agent stop", calls)
        self.assertIn("readiness endpoint unavailable", result.stderr)
        self.assertIn("Canonical readiness contract was not satisfied", result.stderr)
        self.assertIn("heartbeat_fresh", result.stderr)
        self.assertNotIn("cleanhouse is running", result.stdout + result.stderr)

    def test_cleanhouse_launcher_non_darwin_ignores_historical_spawn_metadata_on_readiness_failure(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as home_tmp:
            fake_python = Path(home_tmp) / "fake-python"
            fake_bin = Path(home_tmp) / "bin"
            fake_bin.mkdir()
            fake_uname = fake_bin / "uname"
            fake_uname.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
            fake_uname.chmod(0o755)
            calls_path = Path(home_tmp) / "calls.log"
            fake_python.write_text("""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path(__file__).with_name("calls.log")
calls.write_text(calls.read_text() + " ".join(sys.argv[1:]) + "\\n" if calls.exists() else " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["-m", "backend.runtime_env", "print-path"]:
    print(__file__)
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "preflight":
    print(json.dumps({
        "schema": "cleanhouse.runtime_startup_preflight.v1",
        "status": "ready_to_start",
        "should_start": True
    }))
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "start":
    print(json.dumps({
        "runtime_state": "healthy",
        "operator_ready": True,
        "last_start_attempt": {"status": "spawned", "supervisor_pid": 100},
    }))
    raise SystemExit(0)
if sys.argv[1:3] == ["-m", "backend.runtime_supervisor"] and len(sys.argv) > 3 and sys.argv[3] == "stop":
    print(json.dumps({"runtime_state": "unhealthy", "reason_codes": ["runtime_stop_requested"]}))
    raise SystemExit(0)
if len(sys.argv) > 2 and sys.argv[1] == "-":
    target = sys.argv[2]
    if "/cleanhouse/status?ready=1" in target:
        raise SystemExit(1)
raise SystemExit(1)
""", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "HOME": home_tmp,
                "CLEANHOUSE_RUNTIME_DIR": str(Path(home_tmp) / "runtime"),
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_STARTUP_TIMEOUT_SECONDS": "1",
                "CLEANHOUSE_PORT": "45558",
                "CLEANHOUSE_PYTHON": str(fake_python),
                "PYTHONPATH": str(repo_root),
            }
            result = subprocess.run(
                ["/bin/bash", str(repo_root / "scripts" / "cleanhouse-up.sh")],
                cwd=str(repo_root),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            calls = calls_path.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backend.runtime_supervisor start", calls)
        self.assertNotIn("backend.runtime_supervisor stop", calls)
        self.assertIn("readiness endpoint unavailable", result.stderr)
        self.assertNotIn("cleanhouse is running", result.stdout + result.stderr)

    def test_cleanhouse_bootstrap_reaches_ready_within_five_seconds(self):
        repo_root = Path(__file__).resolve().parents[1]
        port = 45678
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            runtime_dir = Path(runtime_tmp)
            stdout_path = runtime_dir / "server.stdout.log"
            stderr_path = runtime_dir / "server.stderr.log"
            stdout_handle = stdout_path.open("w", encoding="utf-8")
            stderr_handle = stderr_path.open("w", encoding="utf-8")
            env = {
                **os.environ,
                "HOME": home_tmp,
                "CLEANHOUSE_RUNTIME_DIR": runtime_tmp,
                "CLEANHOUSE_EVENTS_DB": str(runtime_dir / "events" / "events.db"),
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_ENABLE_AUTH": "0",
                "CLEANHOUSE_REQUIRE_LOGIN": "0",
                "CLEANHOUSE_NETWORK_HISTORY_ENABLED": "0",
                "CLEANHOUSE_HOST": "127.0.0.1",
                "CLEANHOUSE_PORT": str(port),
                "PYTHONPATH": str(repo_root),
            }
            proc = subprocess.Popen(
                [sys.executable, str(repo_root / "backend" / "server.py")],
                cwd=str(repo_root),
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
            stdout = ""
            stderr = ""
            ready_payload = None
            runtime_payload = None
            start = time.monotonic()
            deadline = start + 5.0
            try:
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        proc.wait(timeout=1)
                        stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
                        stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
                        self.fail(f"CleanHouse exited before readiness: rc={proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/cleanhouse/status?ready=1", timeout=0.5) as response:
                            ready_payload = json.loads(response.read().decode("utf-8") or "{}")
                        if ready_payload.get("ready") is True:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/cleanhouse/runtime", timeout=0.5) as response:
                                runtime_payload = json.loads(response.read().decode("utf-8") or "{}")
                            break
                    except Exception:
                        time.sleep(0.1)
                elapsed = time.monotonic() - start
                self.assertIsNotNone(ready_payload, msg=f"No readiness payload observed within 5s; rc={proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                self.assertTrue(ready_payload.get("ready"), msg=f"Readiness never became true; payload={ready_payload}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                self.assertLess(elapsed, 5.0)
                self.assertIsInstance(runtime_payload, dict)
                self.assertTrue(runtime_payload.get("operator_ready"))
                self.assertIn(runtime_payload.get("startup", {}).get("phase"), {"bootstrap_ready", "warming", "warm", "degraded", "booting"})
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                stdout_handle.close()
                stderr_handle.close()
                stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else stdout
                stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else stderr

    def test_runtime_status_allows_new_backend_before_first_heartbeat_without_probe(self):
        from backend import runtime_supervisor

        repo_root = Path(__file__).resolve().parents[1]
        previous = {
            "backend_pid": 123,
            "supervisor_pid": 456,
            "heartbeat_at": None,
            "heartbeat_sequence": 0,
        }

        def pid_alive(pid):
            try:
                return int(pid) in {123, 456}
            except (TypeError, ValueError):
                return False

        with patch.object(runtime_supervisor, "listener_pids", return_value=[123]), patch.object(
            runtime_supervisor,
            "_pid_alive",
            side_effect=pid_alive,
        ), patch.object(
            runtime_supervisor,
            "_pid_info",
            return_value={
                "pid": 123,
                "alive": True,
                "command": str(repo_root / "backend" / "server.py"),
                "cwd": str(repo_root),
            },
        ), patch.object(
            runtime_supervisor,
            "_pid_resource_usage",
            return_value={"status": "observed", "pid": 123, "rss_mb": 100.0, "cpu_percent": 0.0},
        ):
            state = runtime_supervisor.classify_state(previous, host="localhost", port=3333, probe=False)

        self.assertEqual(state["runtime_state"], "healthy")
        self.assertTrue(state["backend_alive"])
        self.assertEqual(state["resource_guard"]["status"], "ok")
        self.assertNotIn("listener_not_ready", state["reason_codes"])

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

    def test_application_investigation_allows_historical_self_deviation(self):
        from backend import runtime_supervisor
        from backend.api import cleanhouse as cleanhouse_module

        runtime_payload = {
            "runtime_state": "unhealthy",
            "reason_codes": ["runtime_stuck_watchdog"],
            "backend": {"alive": False},
            "supervisor": {"alive": False},
            "blocked_recovery": {"type": "runtime_stuck_watchdog"},
            "self_deviation": {
                "id": "runtime_self_deviation:history",
                "status": "open",
                "review_status": "needs_review",
                "runtime_impact": "historical_record",
                "blocks_investigations": False,
            },
        }
        with patch.object(runtime_supervisor, "current_runtime_payload", return_value=runtime_payload), patch.object(
            cleanhouse_module, "run_application_investigation", return_value={"status": "ok", "summary": "ran"}
        ):
            report = cleanhouse_module.run_application_investigation_with_timeout({"target": "terminal"})

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"], "ran")

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
        for provider in ("google", "microsoft", "apple", "github"):
            self.assertIn(f'id="oauth-{provider}"', signup_html)
            self.assertIn(f'data-provider="{provider}"', signup_html)
            self.assertIn(f'onclick="signInWith{provider.title()}()"', signup_html)
        self.assertEqual(signup_html.count('disabled aria-disabled="true"'), 4)
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
        self.assertIn("'/health'", server_py)
        self.assertIn("turnstileToken", simple_webview_auth)
        self.assertNotIn("Turnstile disabled", simple_webview_auth)
        self.assertNotIn("AI-friendly signup", simple_webview_auth)
        self.assertNotIn('id="role"', simple_webview_auth)
        self.assertNotIn("Select your role", simple_webview_auth)

        self.assertEqual(cleanhouse_auth_config["app"]["id"], "cleanhouse")
        self.assertEqual(cleanhouse_auth_config["redirects"]["postLoginPath"], "/overview")
        self.assertEqual(cleanhouse_auth_config["allowedOrigins"], ["http://localhost:3333"])
        self.assertTrue(cleanhouse_auth_config["turnstile"]["required"])
        self.assertTrue(cleanhouse_auth_config["turnstile"]["enabled"])
        doc_keys = {doc["key"] for doc in cleanhouse_auth_config["docs"]}
        self.assertEqual(doc_keys, {"cleanhouse:terms", "cleanhouse:privacy", "cleanhouse:eeccd"})
        provider_ids = {provider["provider"] for provider in cleanhouse_auth_config["providers"]}
        self.assertEqual(provider_ids, {"google"})

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

        empty_anomalies = {
            "status": "safe",
            "issues": [],
            "data": {},
        }
        with patch(
            "backend.api.cleanhouse_monitoring.DataFlowTracer",
            FailingDataFlowTracerStub,
        ), patch.object(
            adapter,
            "_collect_anomalies",
            return_value=empty_anomalies,
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

    def test_zaelith_manual_audit_ui_routes_to_report_ledger(self):
        repo_root = Path(__file__).resolve().parents[1]
        zaelith_html = (repo_root / "frontend" / "zaelith.html").read_text(encoding="utf-8")
        zaelith_js = (repo_root / "frontend" / "js" / "zaelith.js").read_text(encoding="utf-8")
        product_css = (repo_root / "frontend" / "css" / "product-pages.css").read_text(encoding="utf-8")
        investigations_css = (repo_root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")
        reports_html = (repo_root / "frontend" / "reports.html").read_text(encoding="utf-8")
        reports_js = (repo_root / "frontend" / "js" / "reports.js").read_text(encoding="utf-8")
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")

        self.assertIn("zaelith-monitor-stage", zaelith_html)
        self.assertIn("Connect Provider", zaelith_html)
        self.assertNotIn("zaelith-stage-icon", zaelith_html)
        self.assertIn("zaelith-notification-btn", zaelith_html)
        self.assertIn("zaelith-composer-row", zaelith_html)
        self.assertIn("data-testid=\"zaelith-message-input\"", zaelith_html)
        self.assertIn("placeholder=\"Not-A-Lie Detector\"", zaelith_html)
        self.assertIn("class=\"notification-center-button\"", zaelith_html)
        self.assertIn("class=\"zaelith-message-pair\" hidden", zaelith_html)
        self.assertNotIn("zaelith-composer-footer", zaelith_html)
        self.assertNotIn(">Ready</span>", zaelith_html)
        dock_block = product_css.split(".zaelith-composer-dock {", 1)[1].split("}", 1)[0]
        self.assertNotIn("background:", dock_block)
        self.assertNotIn("box-shadow:", dock_block)
        self.assertNotIn("border:", dock_block)
        for css in (product_css, investigations_css):
            shell_block = css.split(".app-shell {", 1)[1].split("}", 1)[0]
            body_block = css.split("}\n\nbody {\n", 1)[1].split("}", 1)[0]
            self.assertIn("overflow: hidden", body_block)
            self.assertIn("height: 100vh", shell_block)
            self.assertIn("overflow: hidden", shell_block)
        self.assertIn("overflow: auto", product_css.split(".page-canvas {", 1)[1].split("}", 1)[0])
        self.assertIn("overflow: auto", investigations_css.split(".main-canvas {", 1)[1].split("}", 1)[0])
        self.assertIn("href=\"/zaelith/connect\"", zaelith_html)
        self.assertIn("@app.route('/zaelith/connect')", server_py)
        self.assertIn("window.location.replace(`/reports?source=zaelith&open=", zaelith_js)
        self.assertIn("zaelith_audit", reports_html)
        self.assertIn("params.get('source') === 'zaelith'", reports_js)

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        long_text = "Model response. " * 80
        report = adapter.build_zaelith_report(
            analysis={
                "risk_level": "medium",
                "summary": {
                    "grade": "Review",
                    "analysis_confidence": "high",
                    "triggered_indicators": 2,
                    "total_indicators": 7,
                },
                "zaelith_report": {
                    "patronization": {"triggered": True, "evidence": ["obviously"]},
                    "drift": {"triggered": True, "evidence": ["topic shift"]},
                },
            },
            prompt="Manual Zaelith conversation audit",
            response=long_text,
            source="zaelith-page",
        )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["report_type"], "zaelith_audit")
        self.assertFalse(report["receipt"]["metadata"]["full_text_retained"])
        self.assertLess(len(report["receipt"]["metadata"]["response_preview"]), len(long_text))
        ledger = adapter.get_reports(report_type="zaelith_audit", summary_only=True)
        self.assertEqual(ledger["count"], 1)
        self.assertEqual(ledger["reports"][0]["id"], report["id"])

    def test_health_route_is_public_for_readiness_probes(self):
        repo_root = Path(__file__).resolve().parents[1]
        server_py = (repo_root / "backend" / "server.py").read_text(encoding="utf-8")
        self.assertIn("'/health'", server_py)
