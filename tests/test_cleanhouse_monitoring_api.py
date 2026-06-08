import json
import base64
import hashlib
import hmac
import unittest
import sys
import types
import os
import tempfile
import threading
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
    flask_stub.jsonify = lambda obj=None, **kwargs: obj if obj is not None else kwargs
    flask_stub.request = types.SimpleNamespace(args={}, headers={})
    sys.modules["flask"] = flask_stub

if "jwt" not in sys.modules:
    jwt_stub = types.ModuleType("jwt")

    class _JwtError(Exception):
        pass

    jwt_stub.ExpiredSignatureError = _JwtError
    jwt_stub.InvalidTokenError = _JwtError
    jwt_stub.encode = lambda payload, secret, algorithm=None: "stub-jwt"
    jwt_stub.decode = lambda token, secret, algorithms=None: {"user_id": "stub-user"}
    sys.modules["jwt"] = jwt_stub

from backend.api import cleanhouse as cleanhouse_module
from backend.api import cleanhouse_monitoring as monitoring_module
from backend.api.cleanhouse_monitoring import (
    CleanHouseMonitoringAdapter,
    CleanHouseEvent,
    EvidenceRef,
    IntentRecord,
    LoginReportCoordinator,
    PersistenceBackend,
    SessionEnvelope,
)
from corefiles.collectors.command_observer import CommandResult, get_observer
from corefiles import config
from corefiles.notifications import NotificationManager


class FakeAdapter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_status(self, refresh=False):
        self.calls.append(("status", refresh))
        return self.payload["status"]

    def get_processes(self, refresh=False):
        self.calls.append(("processes", refresh))
        return self.payload["processes"]

    def get_network(self, refresh=False):
        self.calls.append(("network", refresh))
        return self.payload["network"]

    def get_ai_activity(self, refresh=False):
        self.calls.append(("ai_activity", refresh))
        return self.payload["ai_activity"]

    def get_anomalies(self, refresh=False):
        self.calls.append(("anomalies", refresh))
        return self.payload["anomalies"]

    def get_integrity(self, refresh=False):
        self.calls.append(("integrity", refresh))
        return self.payload.get("integrity", {"status": "safe", "issues": [], "data": {"integrity_scan": {"status": "no_baseline"}}})

    def get_commands(self, refresh=False):
        self.calls.append(("commands", refresh))
        return self.payload.get("commands", {"status": "safe", "issues": []})


class FakeDetector:
    instances = []

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.findings = {
            "timestamp": "2026-04-17T00:00:00",
            "system_info": {},
            "keyloggers": [],
            "screen_capture": [],
            "remote_access": [],
            "monitoring_software": [],
            "network_monitoring": [],
            "suspicious_files": [],
            "suspicious_processes": [],
            "suspicious_network_connections": [],
            "launch_agents": [],
            "browser_extensions": [],
            "system_modifications": [],
            "hidden_files": [],
            "audio_surveillance": [],
            "bluetooth_monitoring": [],
            "wifi_monitoring": [],
            "dns_hijacking": [],
            "arp_spoofing": [],
            "screen_sharing_active": [],
            "cloud_surveillance": [],
            "data_exfiltration": [],
            "summary": {},
        }
        self._save_results_called = False
        self._notification_called = False
        FakeDetector.instances.append(self)

    def _scan_filesystem(self):
        self.findings["suspicious_files"].append({"file": "/tmp/spy.txt", "severity": "medium"})

    def _scan_processes(self):
        self.findings["suspicious_processes"].append({"process": "spy", "severity": "high"})

    def _scan_network_connections(self):
        self.findings["suspicious_network_connections"].append({"process": "spy", "severity": "high"})

    def _scan_launch_agents(self):
        pass

    def _scan_browser_extensions(self):
        pass

    def _scan_system_modifications(self):
        pass

    def _scan_hidden_files(self):
        pass

    def _scan_audio_access(self):
        pass

    def _scan_bluetooth_connections(self):
        pass

    def _scan_wifi_security(self):
        pass

    def _scan_screen_sharing(self):
        pass

    def _scan_cloud_surveillance(self):
        pass

    def _scan_data_exfiltration(self):
        pass

    def _calculate_summary(self):
        self.findings["summary"] = {"total_findings": 2, "critical": 0, "high": 1, "medium": 1, "low": 0, "files_scanned": 1}

    def _save_results(self):
        self._save_results_called = True

    def _send_macos_notification(self, *args, **kwargs):
        self._notification_called = True


class CleanHouseMonitoringApiTests(unittest.TestCase):
    def setUp(self):
        self._data_tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        self._old_native_notifications = os.environ.get("CLEANHOUSE_NATIVE_NOTIFICATIONS")
        self._old_active_context_codex = os.environ.get("CLEANHOUSE_ACTIVE_CONTEXT_CODEX")
        self._old_presence_mode = os.environ.get("CLEANHOUSE_PRESENCE_MODE")
        config.DATA_DIR = Path(self._data_tmp.name) / "data"
        os.environ["CLEANHOUSE_NATIVE_NOTIFICATIONS"] = "0"
        os.environ["CLEANHOUSE_ACTIVE_CONTEXT_CODEX"] = "0"
        os.environ["CLEANHOUSE_PRESENCE_MODE"] = "0"
        cleanhouse_module.request = types.SimpleNamespace(
            args={},
            headers={},
            get_json=lambda silent=True: None,
        )

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        if self._old_native_notifications is None:
            os.environ.pop("CLEANHOUSE_NATIVE_NOTIFICATIONS", None)
        else:
            os.environ["CLEANHOUSE_NATIVE_NOTIFICATIONS"] = self._old_native_notifications
        if self._old_active_context_codex is None:
            os.environ.pop("CLEANHOUSE_ACTIVE_CONTEXT_CODEX", None)
        else:
            os.environ["CLEANHOUSE_ACTIVE_CONTEXT_CODEX"] = self._old_active_context_codex
        if self._old_presence_mode is None:
            os.environ.pop("CLEANHOUSE_PRESENCE_MODE", None)
        else:
            os.environ["CLEANHOUSE_PRESENCE_MODE"] = self._old_presence_mode
        self._data_tmp.cleanup()

    def _set_request_json(self, payload):
        cleanhouse_module.request = types.SimpleNamespace(
            args={},
            headers={},
            get_json=lambda silent=True: payload,
        )

    def _set_request_args(self, args):
        cleanhouse_module.request = types.SimpleNamespace(
            args=args,
            headers={},
            get_json=lambda silent=True: None,
        )

    def _set_request_headers(self, headers):
        cleanhouse_module.request = types.SimpleNamespace(
            args={},
            headers=headers,
            get_json=lambda silent=True: None,
        )

    def _assert_bad_request(self, response, reason):
        self.assertIsInstance(response, tuple, response)
        body, status = response
        self.assertEqual(status, 400)
        self.assertIn(reason, body.get("message", ""))

    def _unwrap_response_tuple(self, response):
        self.assertIsInstance(response, tuple, response)
        body, status = response
        if hasattr(body, "get_json"):
            body = body.get_json()
        return body, status

    def test_local_origin_cors_header_is_set(self):
        response = type("Resp", (), {"headers": {}})()
        self._set_request_headers({"Origin": "http://127.0.0.1:3000"})
        returned = cleanhouse_module._add_local_cors_headers(response)
        self.assertEqual(returned.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:3000")
        self.assertEqual(returned.headers["Access-Control-Allow-Headers"], "Content-Type, Authorization")

    def test_non_local_origin_cors_header_is_not_set(self):
        response = type("Resp", (), {"headers": {}})()
        self._set_request_headers({"Origin": "https://attacker.example"})
        returned = cleanhouse_module._add_local_cors_headers(response)
        self.assertNotIn("Access-Control-Allow-Origin", returned.headers)

    def test_status_route_returns_envelope(self):
        payload = {
            "status": {
                "status": "warning",
                "issues": [{"id": "processes:1", "source": "processes", "severity": "warning", "message": "status", "detectedAt": "2026-04-17T00:00:00"}],
                "data": {"sections": {
                    "processes": {"status": "safe", "issues": []},
                    "network": {"status": "safe", "issues": []},
                    "ai_activity": {"status": "safe", "issues": []},
                    "anomalies": {"status": "critical", "issues": [{"id": "anomalies:1", "source": "anomalies", "severity": "critical", "message": "anom", "detectedAt": "2026-04-17T00:00:00"}]},
                }},
            },
            "processes": {"status": "safe", "issues": [], "processes": []},
            "network": {"status": "safe", "issues": [], "connections": []},
            "ai_activity": {"status": "safe", "issues": [], "platform_activity": {}},
            "anomalies": {"status": "critical", "issues": [{"id": "anomalies:1", "source": "anomalies", "severity": "critical", "message": "anom", "detectedAt": "2026-04-17T00:00:00"}]},
        }
        fake = FakeAdapter(payload)
        self._set_request_args({"full": "1"})

        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=fake):
            response = cleanhouse_module.status()

        body = response
        self.assertIn(body["status"], {"safe", "warning", "critical"})
        self.assertIn("issues", body)
        self.assertIn("data", body)
        self.assertIn("sections", body["data"])
        self.assertEqual(fake.calls[0][0], "status")

    def test_status_fast_path_uses_runtime_supervisor_payload(self):
        self._set_request_args({})
        runtime_payload = {
            "status": "healthy",
            "runtime_state": "healthy",
            "operator_ready": True,
            "reason_codes": [],
            "supervisor": {"pid": 111},
            "backend": {"pid": 222},
            "listener": {"pids": [222]},
            "heartbeat": {"at": "2026-05-30T00:00:00Z"},
            "last_probe": {"status": "ok"},
            "interpreter": {},
            "last_start_attempt": {},
            "blocked_recovery": {},
            "recovery_receipts": ["runtime_recovery:abc123"],
            "state_path": "/tmp/state.json",
            "updated_at": "2026-05-30T00:00:00Z",
        }
        with patch("backend.runtime_supervisor.current_runtime_payload", return_value=runtime_payload):
            response = cleanhouse_module.status()

        self.assertIn(response["status"], {"safe", "warning"})
        self.assertEqual(response["response_mode"], "fast")
        self.assertEqual(response["data"]["runtime"]["runtime_state"], "healthy")
        self.assertEqual(response["data"]["runtime"]["recovery_receipts"][0]["id"], "runtime_recovery:abc123")
        self.assertIn("event_writer", response["data"]["collector_manifest"]["surfaces"])
        self.assertIn("filesystem_watcher", response["data"]["collector_manifest"]["surfaces"])
        self.assertEqual(
            response["data"]["collector_manifest"]["notification_policy_contract"]["codex_prompt_sent"],
            "persist_only",
        )

    def test_operator_fast_routes_degrade_without_adapter_when_supervisor_unavailable(self):
        def fail_if_adapter_constructed():
            raise AssertionError("fast operator routes must not construct monitoring adapter")

        with patch(
            "backend.runtime_supervisor.current_runtime_payload",
            side_effect=RuntimeError("supervisor down"),
        ), patch.object(
            cleanhouse_module,
            "get_cleanhouse_monitoring_adapter",
            side_effect=fail_if_adapter_constructed,
        ):
            self._set_request_args({})
            status_response = cleanhouse_module.status()
            runtime_response = cleanhouse_module.runtime()
            workstation_response = cleanhouse_module.workstation()

        self.assertEqual(status_response["response_mode"], "fast")
        self.assertEqual(status_response["status"], "critical")
        self.assertEqual(status_response["data"]["runtime"]["runtime_state"], "unhealthy")
        self.assertEqual(
            status_response["data"]["runtime"]["reason_codes"],
            ["runtime_supervisor_unavailable"],
        )

        self.assertEqual(runtime_response["response_mode"], "fast")
        self.assertEqual(runtime_response["status"], "unhealthy")
        self.assertEqual(runtime_response["runtime_state"], "unhealthy")
        self.assertFalse(runtime_response["operator_ready"])
        self.assertEqual(runtime_response["reason_codes"], ["runtime_supervisor_unavailable"])

        self.assertEqual(workstation_response["response_mode"], "fast")
        self.assertEqual(workstation_response["runtime_state"], "unhealthy")
        self.assertFalse(workstation_response["operator_ready"])
        self.assertEqual(workstation_response["deviation"]["status"], "degraded")
        self.assertEqual(
            workstation_response["deviation"]["reason_codes"],
            ["runtime_supervisor_unavailable"],
        )

    def test_ready_status_remains_readiness_only(self):
        self._set_request_args({"ready": "1"})

        response = cleanhouse_module.status()

        self.assertEqual(response["status"], "ok")
        self.assertTrue(response["ready"])
        self.assertIn("event_spine", response)
        self.assertIn("surfaces", response["event_spine"])
        self.assertIn("event_writer", response["event_spine"]["surfaces"])
        self.assertEqual(response["notification_policy_contract"]["codex_prompt_sent"], "persist_only")

    def test_status_full_path_exposes_runtime_health(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        def safe_section(refresh=False):
            return {"status": "safe", "issues": [], "data": {}}

        adapter.get_processes = safe_section
        adapter.get_network = safe_section
        adapter.get_ai_activity = safe_section
        adapter.get_anomalies = safe_section
        adapter.get_integrity = safe_section
        adapter.get_commands = safe_section
        adapter.get_cloud_usage = safe_section
        adapter.get_tool_events = safe_section

        result = adapter.get_status(refresh=True)
        data = result["data"]
        manifest = data["collector_manifest"]
        surfaces = manifest["surfaces"]

        self.assertIn("runtime", data)
        self.assertIn("collector_health", data)
        self.assertIn("degradation", data)
        self.assertIn("filesystem_watcher", surfaces)
        self.assertIn("event_writer", surfaces)
        self.assertIn("runtime_event_writer", surfaces)
        self.assertIn(surfaces["filesystem_watcher"]["support_status"], {"supported", "unsupported", "unknown"})
        self.assertIn("state", surfaces["filesystem_watcher"])
        self.assertIn("queue", surfaces["event_writer"])
        self.assertIn("metrics", surfaces["event_writer"])
        self.assertIn("degradation", surfaces["event_writer"])

    def test_login_report_coordinator_returns_bounded_timeout(self):
        blocker = threading.Event()

        def blocked_builder(**kwargs):
            blocker.wait(timeout=0.25)
            return {"status": "ok", "id": "late-report"}

        coordinator = LoginReportCoordinator(
            blocked_builder,
            max_queue_size=1,
            max_jobs=4,
            job_timeout_seconds=0.01,
        )

        accepted = coordinator.submit(user_id="timeout-user", wait_timeout_seconds=0.0)
        self.assertEqual(accepted["status"], "accepted")
        time.sleep(0.03)
        result = coordinator.poll(accepted["job_id"])

        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["message"])
        self.assertEqual(result["job"]["state"], "failed")
        self.assertIn(result["job"]["blocking_phase"], {"queue", "report_builder"})

    def test_runtime_and_workstation_do_not_force_active_context_refresh(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        calls: list[tuple[bool, bool]] = []

        def fake_active_context(*, refresh: bool = False, attach: bool = False):
            calls.append((refresh, attach))
            return {
                "status": "ok",
                "follow_enabled": False,
                "ignored_count": 0,
                "active_context": None,
                "updated_at": "2026-05-30T00:00:00Z",
            }

        with patch.object(adapter, "get_active_context", side_effect=fake_active_context):
            runtime = adapter.get_runtime()
            workstation = adapter.get_workstation()

        self.assertEqual(runtime["active_context"]["status"], "ok")
        self.assertEqual(workstation["active_context"]["status"], "ok")
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(refresh is False for refresh, _ in calls))

    def test_runtime_event_write_failure_is_status_visible(self):
        monitoring_module._reset_runtime_event_write_failures_for_tests()
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        def safe_section(refresh=False):
            return {"status": "safe", "issues": [], "data": {}}

        adapter.get_processes = safe_section
        adapter.get_network = safe_section
        adapter.get_ai_activity = safe_section
        adapter.get_anomalies = safe_section
        adapter.get_integrity = safe_section
        adapter.get_commands = safe_section
        adapter.get_cloud_usage = safe_section
        adapter.get_tool_events = safe_section

        try:
            with patch.object(monitoring_module.cleanhouse_events, "insert_event_async", side_effect=RuntimeError("db down")):
                monitoring_module._insert_runtime_event(
                    event_type="prompt_event",
                    path="/prompts/failure",
                    summary="prompt_event: failure",
                    session_id="session-runtime-failure",
                )

            result = adapter.get_status(refresh=True)
            surface = result["data"]["collector_manifest"]["surfaces"]["runtime_event_writer"]
            self.assertEqual(surface["collector_status"], "failure")
            self.assertEqual(surface["latest_failure"]["error_detail"], "db down")
            self.assertEqual(result["data"]["degradation"]["status"], "degraded")
            self.assertTrue(any(issue["source"] == "runtime" for issue in result["issues"]))
        finally:
            monitoring_module._reset_runtime_event_write_failures_for_tests()

    def test_submit_intent_rejects_non_json_payload(self):
        self._set_request_json([])
        response = cleanhouse_module.submit_intent()
        self._assert_bad_request(response, "JSON object")

    def test_submit_intent_rejects_repo_path_when_missing(self):
        self._set_request_json({"text": "check", "scope": "dev", "repo_path": 123})
        response = cleanhouse_module.submit_intent()
        self._assert_bad_request(response, "repo_path must")

    def test_create_snapshot_rejects_missing_repo_path(self):
        self._set_request_json({"label": "no repo"})
        response = cleanhouse_module.create_snapshot()
        self._assert_bad_request(response, "repo_path")

    def test_create_snapshot_rejects_non_string_repo_path(self):
        self._set_request_json({"repo_path": 123})
        response = cleanhouse_module.create_snapshot()
        self._assert_bad_request(response, "repo_path must be a string")

    def test_create_snapshot_rejects_nonexistent_repo_path(self):
        self._set_request_json({"repo_path": "/definitely/not/a/real/path"})
        response = cleanhouse_module.create_snapshot()
        self._assert_bad_request(response, "repo_path does not exist")

    def test_create_snapshot_rejects_non_directory_repo_path(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", delete=True) as tmp:
            self._set_request_json({"repo_path": tmp.name})
            response = cleanhouse_module.create_snapshot()
            self._assert_bad_request(response, "repo_path must be a directory")

    def test_diffs_rejects_malformed_session_id(self):
        self._set_request_args({"session_id": 123})
        response = cleanhouse_module.diffs()
        self._assert_bad_request(response, "session_id must be a string")

    def test_create_snapshot_rejects_symlink_path_outside_allowed_roots(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp_root:
            allowed_root = Path(tmp_root) / "allowed"
            allowed_root.mkdir()
            link_target_root = allowed_root / "repo"
            link_target_root.mkdir()
            escape_target = Path("/tmp")
            symlink_path = link_target_root / "outside"
            symlink_path.symlink_to(escape_target)

            with patch.dict(os.environ, {"CLEANHOUSE_ALLOWED_REPO_ROOTS": str(allowed_root)}):
                self._set_request_json({"repo_path": str(symlink_path)})
                response = cleanhouse_module.create_snapshot()
                self._assert_bad_request(response, "outside allowed repository roots")

    def test_build_timeline_rejects_malformed_session_id(self):
        self._set_request_json({"session_id": 123})
        response = cleanhouse_module.build_timeline()
        self._assert_bad_request(response, "session_id must be a string")

    def test_correlate_rejects_non_number_window(self):
        self._set_request_json({"session_id": "abc", "max_time_window_seconds": "30ms"})
        response = cleanhouse_module.correlate()
        self._assert_bad_request(response, "max_time_window_seconds must be a number")

    def test_api_imports_do_not_load_ui_modules(self):
        self.assertNotIn("pywebview", sys.modules)
        self.assertNotIn("webview", sys.modules)
        self.assertNotIn("tkinter", sys.modules)

    def test_processes_route_uses_adapter(self):
        payload = {"status": "safe", "issues": [], "processes": []}
        fake = FakeAdapter({
            "status": {"status": "safe", "issues": []},
            "processes": payload,
            "network": {"status": "safe", "issues": []},
            "ai_activity": {"status": "safe", "issues": []},
            "anomalies": {"status": "safe", "issues": []},
        })

        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=fake):
            response = cleanhouse_module.processes()

        self.assertEqual(response, payload)
        self.assertEqual(fake.calls, [("processes", False)])

    def test_process_events_include_platform_and_agent_evidence(self):
        mock_processes = [
            {"pid": "100", "user": "dev", "cpu": 5.0, "mem": 2.0, "command": "/Applications/Cursor.app/Contents/MacOS/Cursor"},
            {"pid": "200", "user": "dev", "cpu": 3.0, "mem": 1.0, "command": "node /usr/local/bin/copilot-language-server"},
            {"pid": "300", "user": "root", "cpu": 0.1, "mem": 0.2, "command": "kernel_task"},
        ]

        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                pass
            def get_processes(self):
                return mock_processes
            def identify_platform_detail(self, command):
                if "cursor" in command.lower() or "Cursor" in command:
                    return ("Cursor", "\033[92m", "cursor")
                return None
            def is_agent_process_detail(self, command):
                if "copilot" in command.lower():
                    return (True, "copilot")
                return (False, None)
            def is_system_process(self, command, user):
                return user == "root"

        with patch("backend.api.cleanhouse_monitoring.ProcessMonitor", ProcessMonitorStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_processes(refresh=True)

        self.assertEqual(len(payload["issues"]), 2)

        cursor_event = payload["issues"][0]
        ev = cursor_event["evidence"]
        self.assertEqual(ev["pid"], "100")
        self.assertEqual(ev["platform"], "Cursor")
        self.assertEqual(ev["platform_matched_pattern"], "cursor")
        self.assertEqual(ev["agent"], False)
        self.assertIsNone(ev["agent_matched_pattern"])
        self.assertIn("cpu", ev)
        self.assertIn("mem", ev)
        self.assertIn("command", ev)
        self.assertIn("system", ev)
        self.assertIsNotNone(cursor_event.get("message"))

        copilot_event = payload["issues"][1]
        ev2 = copilot_event["evidence"]
        self.assertEqual(ev2["pid"], "200")
        self.assertEqual(ev2["platform"], None)
        self.assertIsNone(ev2["platform_matched_pattern"])
        self.assertEqual(ev2["agent"], True)
        self.assertEqual(ev2["agent_matched_pattern"], "copilot")

    def test_process_monitor_includes_lineage_fields(self):
        from corefiles.collectors.process_monitor import ProcessMonitor

        ps_output = (
            "dev 123 1 1.5 0.2 100 200 ?? S Mon May 25 11:22:33 2026 "
            "0:01.23 /usr/bin/python script.py --flag\n"
        )
        completed = types.SimpleNamespace(returncode=0, stdout=ps_output)

        with patch("corefiles.collectors.process_monitor.platform.system", return_value="Darwin"):
            with patch("corefiles.collectors.process_monitor.subprocess.run", return_value=completed):
                processes = ProcessMonitor(show_all=True).get_processes()

        self.assertEqual(len(processes), 1)
        proc = processes[0]
        self.assertEqual(proc["pid"], "123")
        self.assertEqual(proc["ppid"], "1")
        self.assertEqual(proc["start_time"], "Mon May 25 11:22:33 2026")
        self.assertEqual(proc["args"], "/usr/bin/python script.py --flag")
        self.assertEqual(proc["source_command"], "/usr/bin/python script.py --flag")

    def test_network_route_uses_adapter(self):
        payload = {"status": "warning", "issues": [{"id": "network:1", "source": "network", "severity": "warning", "message": "net", "detectedAt": "2026-04-17T00:00:00"}], "connections": []}
        fake = FakeAdapter({
            "status": {"status": "safe", "issues": []},
            "processes": {"status": "safe", "issues": []},
            "network": payload,
            "ai_activity": {"status": "safe", "issues": []},
            "anomalies": {"status": "safe", "issues": []},
        })

        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=fake):
            response = cleanhouse_module.network()

        self.assertEqual(response, payload)
        self.assertEqual(fake.calls, [("network", False)])

    def test_network_events_include_endpoint_evidence(self):
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

        with patch("backend.api.cleanhouse_monitoring.DataFlowTracer", DataFlowTracerStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_network(refresh=True)

        self.assertEqual(len(payload["issues"]), 1)
        issue = payload["issues"][0]
        ev = issue["evidence"]

        self.assertEqual(ev["port"], 443)
        self.assertEqual(ev["connection_type"], "TCP")
        self.assertEqual(ev["endpoint_family"], "telemetry")
        self.assertEqual(ev["matched_pattern"], "telemetry")
        self.assertEqual(ev["process"], "curl")
        self.assertEqual(ev["pid"], "7777")
        self.assertEqual(ev["host"], "203.0.113.1")
        self.assertEqual(ev["domain"], "evil-telemetry.example.com")
        self.assertEqual(ev["reason"], "telemetry:telemetry")
        self.assertIn("process_info", ev)
        self.assertEqual(ev["process_info"]["command"], "curl")

        self.assertIn("matched endpoint pattern", issue["message"])

        self.assertGreaterEqual(len(issue["evidence_refs"]), 1)
        ref = issue["evidence_refs"][0]
        self.assertIsInstance(ref, dict)
        self.assertIn("uri", ref)
        self.assertTrue(ref["uri"].startswith("local://cleanhouse/network/"))

    def test_data_flow_tracer_connection_delta_primitives(self):
        from corefiles.collectors.data_flow_tracer import DataFlowTracer

        tracer = DataFlowTracer(monitor_duration=1)
        before = tracer.build_connection_snapshot([
            {"process": "curl", "pid": "10", "connection_type": "TCP", "host": "203.0.113.1", "port": 443, "address": "203.0.113.1:443"},
            {"process": "ssh", "pid": "11", "connection_type": "TCP", "host": "198.51.100.1", "port": 22, "address": "198.51.100.1:22"},
            {"process": "", "pid": "", "connection_type": "TCP", "host": "unknown", "port": 0, "address": "unknown"},
        ])
        after = tracer.build_connection_snapshot([
            {"process": "curl", "pid": "10", "connection_type": "TCP", "host": "203.0.113.1", "port": 443, "address": "203.0.113.1:443"},
            {"process": "python", "pid": "12", "connection_type": "TCP", "host": "192.0.2.1", "port": 8443, "address": "192.0.2.1:8443"},
        ])

        self.assertEqual(before["keys"], sorted(before["keys"]))
        delta = tracer.compute_connection_delta(before, after)

        self.assertEqual(delta["counts"], {"opened": 1, "still_open": 1, "closed": 1, "unknown": 1})
        self.assertEqual(delta["opened"][0]["process"], "python")
        self.assertEqual(delta["still_open"][0]["process"], "curl")
        self.assertEqual(delta["closed"][0]["process"], "ssh")
        self.assertEqual(delta["unknown"][0]["address"], "unknown")

    def test_ai_activity_route_uses_adapter(self):
        payload = {"status": "warning", "issues": [{"id": "ai-activity:1", "source": "ai-activity", "severity": "warning", "message": "ai", "detectedAt": "2026-04-17T00:00:00"}], "platform_activity": {}}
        fake = FakeAdapter({
            "status": {"status": "safe", "issues": []},
            "processes": {"status": "safe", "issues": []},
            "network": {"status": "safe", "issues": []},
            "ai_activity": payload,
            "anomalies": {"status": "safe", "issues": []},
        })

        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=fake):
            response = cleanhouse_module.ai_activity()

        self.assertEqual(response, payload)
        self.assertEqual(fake.calls, [("ai_activity", False)])

    def test_anomalies_adapter_avoids_notifications_and_writes(self):
        with patch("backend.api.cleanhouse_monitoring.SurveillanceDetector", FakeDetector):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_anomalies(refresh=True)

        self.assertEqual(payload["status"], "warning")
        self.assertFalse(FakeDetector.instances[0]._save_results_called)
        self.assertFalse(FakeDetector.instances[0]._notification_called)
        self.assertGreaterEqual(len(payload["issues"]), 1)
        self.assertEqual(payload["issues"][0]["source"], "anomalies")
        self.assertIn(payload["issues"][0]["severity"], {"warning", "critical"})
        self.assertIn("detectedAt", payload["issues"][0])

    def test_status_rollup_safe_warning_critical_and_mixed(self):
        warning_issue = {
            "id": "network:warning",
            "source": "network",
            "severity": "warning",
            "message": "warning issue",
            "detectedAt": "2026-04-17T00:00:00",
        }
        critical_issue = {
            "id": "anomalies:critical",
            "source": "anomalies",
            "severity": "critical",
            "message": "critical issue",
            "detectedAt": "2026-04-17T00:00:00",
        }

        cases = [
            ([], [], "safe"),
            ([warning_issue], [], "warning"),
            ([], [critical_issue], "critical"),
            ([warning_issue], [critical_issue], "critical"),
        ]

        for warning_issues, critical_issues, expected in cases:
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            adapter.get_processes = lambda refresh=False: {"status": "safe", "issues": []}
            adapter.get_network = lambda refresh=False, issues=warning_issues: {"status": "warning" if issues else "safe", "issues": issues}
            adapter.get_ai_activity = lambda refresh=False: {"status": "safe", "issues": []}
            adapter.get_anomalies = lambda refresh=False, issues=critical_issues: {"status": "critical" if issues else "safe", "issues": issues}
            adapter.get_integrity = lambda refresh=False: {"status": "safe", "issues": [], "data": {"integrity_scan": {"status": "no_baseline"}}}
            adapter.get_commands = lambda refresh=False: {"status": "safe", "issues": []}

            self.assertEqual(adapter.get_status(refresh=True)["status"], expected)

    def test_collector_failure_processes(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                pass
            def get_processes(self):
                raise PermissionError("process table unavailable")

        with patch("backend.api.cleanhouse_monitoring.ProcessMonitor", ProcessMonitorStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_processes(refresh=True)

        self.assertEqual(payload["status"], "critical")
        issue = payload["issues"][0]
        self.assertEqual(issue["source"], "processes")
        self.assertEqual(issue["severity"], "critical")
        self.assertIn("unable to execute processes", issue["message"])
        self.assertIn("process table unavailable", issue["message"])
        self.assertEqual(issue["evidence"]["status"], "unable to execute")
        self.assertIn("expected_context", issue["evidence"])

    def test_collector_failure_network(self):
        class DataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                pass
            def scan_network_connections(self):
                raise ConnectionError("network scan denied")
            def scan_dns_queries(self):
                pass
            trace_data = {"network_connections": [], "suspicious_connections": [],
                          "unusual_patterns": [], "dns_queries": []}

        with patch("backend.api.cleanhouse_monitoring.DataFlowTracer", DataFlowTracerStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_network(refresh=True)

        self.assertEqual(payload["status"], "critical")
        issue = payload["issues"][0]
        self.assertEqual(issue["source"], "network")
        self.assertEqual(issue["severity"], "critical")
        self.assertIn("unable to execute network", issue["message"])
        self.assertIn("network scan denied", issue["message"])
        self.assertEqual(issue["evidence"]["status"], "unable to execute")
        self.assertIn("expected_context", issue["evidence"])

    def test_collector_failure_ai_activity(self):
        class AgentMovementMonitorStub:
            def __init__(self, verbose=False):
                pass
            def scan_processes(self):
                raise RuntimeError("agent process scanner not available")
            def scan_file_access(self):
                return {}
            def scan_network_connections(self):
                return {}
            activity_log = {"platform_activity": {}}

        with patch("backend.api.cleanhouse_monitoring.AgentMovementMonitor", AgentMovementMonitorStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_ai_activity(refresh=True)

        self.assertEqual(payload["status"], "critical")
        issue = payload["issues"][0]
        self.assertEqual(issue["source"], "ai-activity")
        self.assertEqual(issue["severity"], "critical")
        self.assertIn("unable to execute ai_activity", issue["message"])
        self.assertIn("agent process scanner not available", issue["message"])
        self.assertEqual(issue["evidence"]["status"], "unable to execute")
        self.assertIn("expected_context", issue["evidence"])

    def test_collector_failure_anomalies(self):
        class SurveillanceDetectorStub:
            def __init__(self, verbose=False):
                pass
            def _scan_filesystem(self):
                raise OSError("filesystem access denied")
            def _scan_processes(self): pass
            def _scan_network_connections(self): pass
            def _scan_launch_agents(self): pass
            def _scan_browser_extensions(self): pass
            def _scan_system_modifications(self): pass
            def _scan_hidden_files(self): pass
            def _scan_audio_access(self): pass
            def _scan_bluetooth_connections(self): pass
            def _scan_wifi_security(self): pass
            def _scan_screen_sharing(self): pass
            def _scan_cloud_surveillance(self): pass
            def _scan_data_exfiltration(self): pass
            def _calculate_summary(self): pass
            findings = {}

        with patch("backend.api.cleanhouse_monitoring.SurveillanceDetector", SurveillanceDetectorStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            payload = adapter.get_anomalies(refresh=True)

        self.assertEqual(payload["status"], "critical")
        issue = payload["issues"][0]
        self.assertEqual(issue["source"], "anomalies")
        self.assertEqual(issue["severity"], "critical")
        self.assertIn("unable to execute anomalies", issue["message"])
        self.assertIn("filesystem access denied", issue["message"])
        self.assertEqual(issue["evidence"]["status"], "unable to execute")
        self.assertIn("expected_context", issue["evidence"])

    def test_adapter_cache_reuses_snapshot(self):
        calls = {"count": 0}

        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                pass

            def get_processes(self):
                calls["count"] += 1
                return [{"pid": "1", "user": "dev", "cpu": 1.0, "mem": 0.5, "command": "cursor"}]

            def identify_platform(self, command):
                return ("Cursor", "") if "cursor" in command.lower() else None

            def identify_platform_detail(self, command):
                return ("Cursor", "", "cursor") if "cursor" in command.lower() else None

            def is_agent_process(self, command):
                return True

            def is_agent_process_detail(self, command):
                return (True, "copilot")

            def is_system_process(self, command, user):
                return False

        with patch("backend.api.cleanhouse_monitoring.ProcessMonitor", ProcessMonitorStub):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=60.0)
            first = adapter.get_processes(refresh=True)
            second = adapter.get_processes()

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "warning")


    def test_event_schema_keys(self):
        from backend.api.cleanhouse_monitoring import _coerce_issue

        event_dict = _coerce_issue(
            category="process",
            severity="warning",
            title="test event",
            details="test details",
            source="processes",
        )

        required_keys = {
            "id", "event_id", "source", "severity", "message",
            "detectedAt", "timestamp", "confidence", "uncertainty",
            "evidence_refs", "evidence_level", "rationale",
            "observed_vs_expected",
        }
        present = set(event_dict.keys())
        missing = required_keys - present
        self.assertSetEqual(missing, set(), f"Missing keys: {missing}")

        for ref in event_dict["evidence_refs"]:
            self.assertIn("uri", ref)
            self.assertIn("evidence_level", ref)
            self.assertIn("description", ref)

    def test_evidence_level_normalization(self):
        from backend.api.cleanhouse_monitoring import _coerce_issue

        for valid_level in ("observed", "inferred", "unknown"):
            d = _coerce_issue(
                category="test", severity="warning", title="t",
                details="d", source="anomalies",
                evidence_level=valid_level,
            )
            self.assertEqual(d["evidence_level"], valid_level, f"failed for {valid_level}")
            self.assertEqual(d["observed_vs_expected"]["status"], valid_level)

        d = _coerce_issue(
            category="test", severity="warning", title="t",
            details="d", source="anomalies",
            evidence_level="INVALID_UPPERCASE",
        )
        self.assertEqual(d["evidence_level"], "observed")

        d = _coerce_issue(
            category="test", severity="warning", title="t",
            details="d", source="anomalies",
            evidence_level="",
        )
        self.assertEqual(d["evidence_level"], "observed")

    def test_event_immutability(self):
        ref = EvidenceRef(uri="local://test", evidence_level="observed")
        event = CleanHouseEvent(
            event_id="test:abc123",
            timestamp="2026-01-01T00:00:00",
            source="processes",
            severity="warning",
            confidence=0.8,
            uncertainty=0.2,
            evidence_refs=(ref,),
            observed_vs_expected={"status": "observed", "details": "test"},
            message="test",
            rationale="test",
            evidence_level="observed",
        )
        with self.assertRaises(Exception):
            event.event_id = "changed"

    def test_integrity_changed_file_detection(self):
        import tempfile
        from pathlib import Path
        from corefiles import config as corefiles_config
        from corefiles.integrity import generate_baseline, scan_integrity

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            baseline_file = tmpdir_path / "baseline.json"
            test_file = tmpdir_path / "test.py"
            test_file.write_text("print('hello')")

            with patch.object(corefiles_config, "INTEGRITY_BASELINE_FILE", baseline_file):
                generate_baseline(tmpdir_path)
                test_file.write_text("print('modified')")
                result = scan_integrity(tmpdir_path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["changes"]), 1)
        change = result["changes"][0]
        self.assertEqual(change["change_type"], "modified")
        self.assertEqual(change["rel_path"], "test.py")
        self.assertIsNotNone(change["baseline_hash"])
        self.assertIsNotNone(change["current_hash"])
        self.assertNotEqual(change["baseline_hash"], change["current_hash"])

    def test_integrity_duplicate_scan_stable(self):
        import tempfile
        from pathlib import Path
        from corefiles import config as corefiles_config
        from corefiles.integrity import generate_baseline, scan_integrity

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            baseline_file = tmpdir_path / "baseline.json"
            test_file = tmpdir_path / "stable.py"
            test_file.write_text("print('stable')")

            with patch.object(corefiles_config, "INTEGRITY_BASELINE_FILE", baseline_file):
                generate_baseline(tmpdir_path)
                result1 = scan_integrity(tmpdir_path)
                result2 = scan_integrity(tmpdir_path)

        self.assertEqual(result1["status"], "ok")
        self.assertEqual(result2["status"], "ok")
        self.assertEqual(len(result1["changes"]), 0)
        self.assertEqual(len(result2["changes"]), 0)

    def test_integrity_baseline_determinism(self):
        import tempfile
        import json
        from pathlib import Path
        from corefiles import config as corefiles_config
        from corefiles.integrity import generate_baseline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            baseline_file = tmpdir_path / "baseline.json"

            (tmpdir_path / "a.py").write_text("print('a')")
            (tmpdir_path / "b.py").write_text("print('b')")

            with patch.object(corefiles_config, "INTEGRITY_BASELINE_FILE", baseline_file):
                generate_baseline(tmpdir_path)
                with open(baseline_file) as f:
                    first = json.dumps(json.load(f), sort_keys=True)

                generate_baseline(tmpdir_path)
                with open(baseline_file) as f:
                    second = json.dumps(json.load(f), sort_keys=True)

            self.assertEqual(first, second)

    def test_command_event_with_exit_status_and_duration(self):
        from corefiles.collectors.command_observer import CommandObserver, CommandResult

        captured: list[CommandResult] = []
        observer = CommandObserver()
        observer.on_completed = captured.append

        proc = observer.run(["echo", "hello"], capture_output=True)

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(captured), 1)
        result = captured[0]
        self.assertEqual(result.command, "echo")
        self.assertEqual(result.args, ("echo", "hello"))
        self.assertEqual(result.returncode, 0)
        self.assertGreater(result.duration, 0.0)
        self.assertIsNotNone(result.user)
        self.assertIsInstance(result.user, str)
        self.assertGreater(len(result.user), 0)
        self.assertIn("hello", (result.stdout_preview or ""))

    def test_command_observer_missing_cwd_context(self):
        from corefiles.collectors.command_observer import CommandObserver, CommandResult

        captured: list[CommandResult] = []
        observer = CommandObserver()
        observer.on_completed = captured.append

        observer.run(["echo", "test"], capture_output=True)

        self.assertEqual(len(captured), 1)
        result = captured[0]
        self.assertIsNone(result.cwd)
        self.assertEqual(result.command, "echo")
        self.assertEqual(result.returncode, 0)
        self.assertGreater(result.duration, 0.0)

    def test_command_observer_records_session_objective_and_child_pid(self):
        from corefiles.collectors.command_observer import CommandObserver, CommandResult

        captured: list[CommandResult] = []
        observer = CommandObserver()
        observer.on_completed = captured.append

        env = dict(os.environ)
        env["CLEANHOUSE_SESSION_ID"] = "env-session"
        env["CLEANHOUSE_OBJECTIVE_ID"] = "env-objective"
        proc = observer.run(
            ["/bin/echo", "metadata"],
            capture_output=True,
            env=env,
            session_id="explicit-session",
        )

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(captured), 1)
        result = captured[0]
        self.assertEqual(result.session_id, "explicit-session")
        self.assertEqual(result.objective_id, "env-objective")
        self.assertIsInstance(result.child_pid, int)
        self.assertGreater(result.child_pid, 0)

    def test_intent_endpoint_persistence_and_retrieval(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_intent(
            text="fix login bug",
            scope="auth",
            repo_path="/Users/test/project",
            tool_identity="CleanHouse",
        )

        self.assertEqual(result["status"], "ok")
        self.assertIsNotNone(result["id"])
        self.assertTrue(result["id"].startswith("intent:"))

        intents = adapter.get_intents()
        self.assertEqual(intents["count"], 1)
        record = intents["intents"][0]
        self.assertEqual(record["text"], "fix login bug")
        self.assertEqual(record["scope"], "auth")
        self.assertEqual(record["repo_path"], "/Users/test/project")
        self.assertEqual(record["tool_identity"], "CleanHouse")
        self.assertEqual(record["source"], "ui")
        self.assertEqual(record["id"], result["id"])
        self.assertIn("timestamp", record)

    def test_intent_missing_text_unknown_state(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        result_empty = adapter.submit_intent(text="", scope="test")
        self.assertEqual(result_empty["status"], "unknown")
        self.assertIsNone(result_empty["id"])

        result_whitespace = adapter.submit_intent(text="   ", scope="test")
        self.assertEqual(result_whitespace["status"], "unknown")
        self.assertIsNone(result_whitespace["id"])

        intents = adapter.get_intents()
        self.assertEqual(intents["count"], 0)

    def test_prompt_context_persistence_and_timeline(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_prompt(
            text="Update the requested avatar only",
            context="avatar substitution incident fixture",
            scope="assets/avatars/requested/",
            repo_path="/Users/test/project",
            tool_identity="Codex",
            session_id="avatar-session",
            objective_id="objective-avatar",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["session_id"], "avatar-session")

        prompts = adapter.get_prompts(session_id="avatar-session")
        self.assertEqual(prompts["count"], 1)
        prompt = prompts["prompts"][0]
        self.assertEqual(prompt["text"], "Update the requested avatar only")
        self.assertEqual(prompt["context"], "avatar substitution incident fixture")
        self.assertEqual(prompt["scope"], "assets/avatars/requested/")
        self.assertEqual(prompt["objective_id"], "objective-avatar")

        timeline = adapter.build_timeline(session_id="avatar-session")
        self.assertEqual(timeline["status"], "ok")
        event_types = [entry["event_type"] for entry in timeline["entries"]]
        self.assertIn("prompt", event_types)
        self.assertIn("intent", event_types)

    def test_prompt_endpoint_rejects_missing_text(self):
        self._set_request_json({"context": "missing prompt text"})
        response = cleanhouse_module.submit_prompt()
        self._assert_bad_request(response, "text is required")

    def test_approval_queue_create_list_resolve(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.create_approval_queue_item({
            "session_id": "session-approval",
            "requested_action": "review avatar substitution before receipt",
            "reason": "out-of-scope avatar path observed",
            "evidence_refs": ["local://cleanhouse/timeline/tl:session-approval:3"],
            "prompt_id": "prompt:avatar",
            "objective_id": "objective-avatar",
            "reviewer_note": "hold for operator review",
            "reviewer": "dashboard",
            "metadata": {"fixture": "avatar_substitution"},
        })
        self.assertEqual(result["status"], "ok")
        approval = result["approval"]
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["reviewer_note"], "hold for operator review")
        self.assertEqual(approval["history"][0]["action"], "created")
        self.assertEqual(approval["mediation_proof"]["schema"], "cleanhouse.approval_mediation_proof.v1")
        self.assertEqual(approval["mediation_proof"]["approval_id"], approval["id"])
        self.assertEqual(approval["mediation_proof"]["history_count"], 1)
        created_proof_hash = approval["mediation_proof"]["proof_hash"]

        listed = adapter.get_approval_queue(session_id="session-approval", status="pending")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["approval_queue"][0]["id"], approval["id"])
        self.assertEqual(listed["approval_queue"][0]["mediation_proof"]["proof_hash"], created_proof_hash)

        resolved = adapter.resolve_approval_queue_item(
            approval_id=approval["id"],
            status="rejected",
            note="requested avatar target did not match observed mutation",
            reviewer="dashboard",
        )
        self.assertEqual(resolved["status"], "ok")
        self.assertEqual(resolved["approval"]["status"], "rejected")
        self.assertIsNotNone(resolved["approval"]["resolved_at"])
        self.assertEqual(resolved["approval"]["reviewer"], "dashboard")
        self.assertEqual(resolved["approval"]["reviewer_note"], "requested avatar target did not match observed mutation")
        self.assertEqual([h["action"] for h in resolved["approval"]["history"]], ["created", "rejected"])
        self.assertEqual(resolved["approval"]["mediation_proof"]["history_count"], 2)
        self.assertNotEqual(resolved["approval"]["mediation_proof"]["proof_hash"], created_proof_hash)

        stored = PersistenceBackend.read("approval", approval["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["data"]["approval"]["status"], "rejected")
        stored_proof = PersistenceBackend.read("approval_mediation_proof", approval["id"])
        self.assertIsNotNone(stored_proof)
        self.assertEqual(
            stored_proof["data"]["proof"]["proof_hash"],
            resolved["approval"]["mediation_proof"]["proof_hash"],
        )

    def test_receipt_state_replay_reconstructs_rejected_operator_decision(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="receipt replay fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="replay-avatar-session",
            objective_id="objective-replay-avatar",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested_dir = root / "assets" / "avatars" / "requested"
            substituted_dir = root / "assets" / "avatars" / "substituted"
            requested_dir.mkdir(parents=True)
            substituted_dir.mkdir(parents=True)
            (requested_dir / "avatar.png").write_text("requested-v1")
            substituted = substituted_dir / "avatar.png"
            substituted.write_text("substituted-v1")
            before = adapter.create_snapshot(
                repo_path=str(root),
                label="before-replay-avatar",
                session_id=prompt["session_id"],
            )
            substituted.write_text("substituted-v2")
            after = adapter.create_snapshot(
                repo_path=str(root),
                label="after-replay-avatar",
                session_id=prompt["session_id"],
            )
            diff = adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

        receipt = adapter.build_receipt(session_id=prompt["session_id"])
        approval = adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review receipt traversal",
            "reason": "receipt flagged path outside declared scope",
            "evidence_refs": [
                "local://cleanhouse/receipt/" + receipt["id"],
                "local://cleanhouse/diff/" + diff["id"],
            ],
            "prompt_id": prompt["id"],
            "objective_id": "objective-replay-avatar",
            "reviewer_note": "initial reviewer note",
            "reviewer": "dashboard",
            "metadata": {
                "receipt_id": receipt["id"],
                "fixture": "avatar_substitution",
            },
        })["approval"]
        resolved = adapter.resolve_approval_queue_item(
            approval_id=approval["id"],
            status="rejected",
            note="rejected due to substituted avatar traversal",
            reviewer="dashboard",
        )
        self.assertEqual(resolved["status"], "ok")

        replay = adapter.replay_receipt_state(receipt["id"])
        self.assertEqual(replay["status"], "ok")
        self.assertEqual(replay["state"]["status"], "rejected")
        self.assertEqual(replay["state"]["reviewer_note"], "rejected due to substituted avatar traversal")
        self.assertEqual([h["action"] for h in replay["approval_history"]], ["created", "rejected"])
        refs = [entry["ref"] for entry in replay["evidence_chain"]]
        self.assertIn("local://cleanhouse/receipt/" + receipt["id"], refs)
        self.assertIn("local://cleanhouse/diff/" + diff["id"], refs)
        self.assertTrue(any("/approval-queue/" in ref for ref in refs))

        replay_again = adapter.replay_receipt_state(receipt["id"])
        self.assertEqual(
            replay["integrity"]["replay_hash"],
            replay_again["integrity"]["replay_hash"],
        )
        stored_replay = PersistenceBackend.read("receipt_replay", replay["id"])
        self.assertIsNotNone(stored_replay)
        self.assertEqual(stored_replay["data"]["integrity"]["replay_hash"], replay["integrity"]["replay_hash"])

        exported = adapter.export_receipt_timeline_bundle(receipt["id"])
        self.assertEqual(exported["status"], "ok")
        bundle = exported["bundle"]
        self.assertEqual(bundle["integrity"]["replay_hash"], replay["integrity"]["replay_hash"])
        self.assertTrue(exported["verification"]["bundle_hash_match"])
        self.assertTrue(exported["verification"]["receipt_root_hash_match"])
        self.assertTrue(exported["verification"]["replay_hash_match"])
        self.assertTrue(exported["verification"]["manifest_hash_match"])
        self.assertTrue(exported["verification"]["signature_verified"])
        self.assertEqual(exported["verification"]["signature_status"], "verified")
        self.assertEqual(bundle["manifest"]["replay_hash"], replay["integrity"]["replay_hash"])
        self.assertEqual(bundle["manifest_signature"]["manifest_hash"], bundle["integrity"]["manifest_hash"])
        expected_custody_hash = monitoring_module._stable_json_hash(bundle["chain_of_custody"])
        self.assertEqual(bundle["manifest"]["chain_of_custody_hash"], expected_custody_hash)
        self.assertEqual(
            bundle["manifest"]["chain_of_custody_hop_count"],
            len(bundle["chain_of_custody"]["hops"]),
        )
        self.assertEqual(
            bundle["manifest"]["chain_of_custody_traceable_hop_count"],
            sum(
                1
                for hop in bundle["chain_of_custody"]["hops"]
                if str(hop.get("ref", "")).startswith("local://cleanhouse/")
            ),
        )
        self.assertTrue(exported["verification"]["chain_of_custody_hash_match"])
        self.assertTrue(exported["verification"]["chain_of_custody_hop_count_match"])
        self.assertTrue(exported["verification"]["chain_of_custody_traceable_hop_count_match"])
        self.assertEqual(
            bundle["manifest"]["signer"]["key_id"],
            exported["verification"]["signer_key_id"],
        )
        self.assertEqual(
            bundle["manifest"]["key_management"]["mode"],
            "local_unmanaged_ed25519_file",
        )
        self.assertIn(
            "bundled_public_key_requires_out_of_band_fingerprint_trust",
            bundle["manifest"]["key_management"]["limitations"],
        )
        self.assertEqual(
            exported["verification"]["key_management_status"],
            "local_unmanaged_ed25519_file",
        )
        self.assertTrue(exported["verification"]["key_management_label_match"])
        self.assertIn(
            "no_rotation_revocation_ca_or_hardware_backing_in_gate_a",
            exported["verification"]["key_management_limitations"],
        )

        exported_again = adapter.export_receipt_timeline_bundle(receipt["id"])
        self.assertEqual(
            exported["bundle"]["integrity"]["bundle_hash"],
            exported_again["bundle"]["integrity"]["bundle_hash"],
        )
        self.assertEqual(
            exported["bundle"]["integrity"]["replay_hash"],
            exported_again["bundle"]["integrity"]["replay_hash"],
        )
        self.assertEqual(
            exported["bundle"]["integrity"]["manifest_hash"],
            exported_again["bundle"]["integrity"]["manifest_hash"],
        )
        self.assertEqual(
            exported["bundle"]["manifest_signature"]["signature_b64"],
            exported_again["bundle"]["manifest_signature"]["signature_b64"],
        )

        offline_adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        offline_adapter.persistence_enabled = False
        imported = offline_adapter.import_receipt_timeline_bundle(bundle)
        self.assertEqual(imported["status"], "ok")
        self.assertEqual(imported["integrity"]["replay_hash"], replay["integrity"]["replay_hash"])
        self.assertTrue(imported["verification"]["bundle_hash_match"])
        self.assertTrue(imported["verification"]["timeline_hash_match"])
        self.assertTrue(imported["verification"]["manifest_hash_match"])
        self.assertTrue(imported["verification"]["signature_verified"])
        self.assertEqual(imported["verification"]["signature_status"], "verified")

        tampered = json.loads(json.dumps(bundle))
        tampered["receipt"]["scope_analysis"]["scope_weight"] = 0.0
        rejected = offline_adapter.import_receipt_timeline_bundle(tampered)
        self.assertEqual(rejected["status"], "failed")
        self.assertFalse(rejected["verification"]["bundle_hash_match"])
        self.assertFalse(rejected["verification"]["receipt_root_hash_match"])

        tampered_manifest = json.loads(json.dumps(bundle))
        tampered_manifest["manifest"]["evidence_refs"].append("local://cleanhouse/timeline/tampered")
        rejected_manifest = offline_adapter.import_receipt_timeline_bundle(tampered_manifest)
        self.assertEqual(rejected_manifest["status"], "failed")
        self.assertFalse(rejected_manifest["verification"]["manifest_hash_match"])
        self.assertFalse(rejected_manifest["verification"]["signature_verified"])

        tampered_signature = json.loads(json.dumps(bundle))
        sig = tampered_signature["manifest_signature"]["signature_b64"]
        tampered_signature["manifest_signature"]["signature_b64"] = ("A" if sig[:1] != "A" else "B") + sig[1:]
        rejected_signature = offline_adapter.import_receipt_timeline_bundle(tampered_signature)
        self.assertEqual(rejected_signature["status"], "failed")
        self.assertFalse(rejected_signature["verification"]["signature_verified"])

        tampered_key = json.loads(json.dumps(bundle))
        tampered_key["manifest"]["signer"]["public_key_b64"] = "A" * len(tampered_key["manifest"]["signer"]["public_key_b64"])
        rejected_key = offline_adapter.import_receipt_timeline_bundle(tampered_key)
        self.assertEqual(rejected_key["status"], "failed")
        self.assertFalse(rejected_key["verification"]["signature_verified"])

        tampered_custody_manifest = json.loads(json.dumps(bundle))
        tampered_custody_manifest["manifest"]["chain_of_custody_hash"] = "0" * 64
        rejected_custody_manifest = offline_adapter.import_receipt_timeline_bundle(tampered_custody_manifest)
        self.assertEqual(rejected_custody_manifest["status"], "failed")
        self.assertFalse(rejected_custody_manifest["verification"]["chain_of_custody_hash_match"])
        self.assertFalse(rejected_custody_manifest["verification"]["manifest_contents_match"])

        stripped_signed = json.loads(json.dumps(bundle))
        stripped_signed.pop("manifest", None)
        stripped_signed.pop("manifest_signature", None)
        rejected_stripped = offline_adapter.import_receipt_timeline_bundle(stripped_signed)
        self.assertEqual(rejected_stripped["status"], "failed")
        self.assertEqual(rejected_stripped["verification"]["signature_status"], "failed")
        self.assertIn(
            "integrity.manifest_hash present",
            rejected_stripped["verification"]["signature_error"],
        )

        legacy_unsigned = json.loads(json.dumps(bundle))
        legacy_unsigned.pop("manifest", None)
        legacy_unsigned.pop("manifest_signature", None)
        legacy_unsigned["integrity"].pop("manifest_hash", None)
        imported_legacy = offline_adapter.import_receipt_timeline_bundle(legacy_unsigned)
        self.assertEqual(imported_legacy["status"], "ok")
        self.assertEqual(imported_legacy["verification"]["signature_status"], "unavailable")
        self.assertFalse(imported_legacy["verification"]["signature_verified"])

    def test_approval_queue_endpoint_invalid_evidence_refs(self):
        self._set_request_json({
            "session_id": "session-approval",
            "requested_action": "review",
            "evidence_refs": "local://cleanhouse/timeline/1",
        })
        response = cleanhouse_module.create_approval_queue_item()
        self._assert_bad_request(response, "evidence_refs must be a list")

    def test_scope_approval_policy_receipt_specific(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Modify only requested avatar",
            context="receipt-scoped approval mediation",
            scope="assets/avatars/requested/",
            session_id="session-scope-approval-receipt-specific",
            objective_id="objective-scope-approval-receipt-specific",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            substituted_file = substituted / "avatar.png"
            substituted_file.write_text("substituted-v1")

            before_first = adapter.create_snapshot(
                repo_path=str(root),
                label="before-first",
                session_id=prompt["session_id"],
            )
            substituted_file.write_text("substituted-v2")
            after_first = adapter.create_snapshot(
                repo_path=str(root),
                label="after-first",
                session_id=prompt["session_id"],
            )
            adapter.compute_diff(before_first["id"], after_first["id"], session_id=prompt["session_id"])

            receipt_one = adapter.build_receipt(session_id=prompt["session_id"])

            before_second = adapter.create_snapshot(
                repo_path=str(root),
                label="before-second",
                session_id=prompt["session_id"],
            )
            substituted_file.write_text("substituted-v3")
            after_second = adapter.create_snapshot(
                repo_path=str(root),
                label="after-second",
                session_id=prompt["session_id"],
            )
            adapter.compute_diff(before_second["id"], after_second["id"], session_id=prompt["session_id"])

            receipt_two = adapter.build_receipt(session_id=prompt["session_id"])

        approval_one = receipt_one["approval_policy"]["approval_id"]
        approval_two = receipt_two["approval_policy"]["approval_id"]
        self.assertNotEqual(approval_one, approval_two)

        queue = adapter.get_approval_queue(session_id=prompt["session_id"])
        self.assertEqual(queue["count"], 2)

        replay_one = adapter.replay_receipt_state(receipt_one["id"])
        replay_two = adapter.replay_receipt_state(receipt_two["id"])
        self.assertEqual(replay_one["status"], "ok")
        self.assertEqual(replay_two["status"], "ok")
        self.assertEqual(replay_one["state"]["status"], "pending")
        self.assertEqual(replay_two["state"]["status"], "pending")
        self.assertEqual(replay_one["state"]["approval_id"], approval_one)
        self.assertEqual(replay_two["state"]["approval_id"], approval_two)
        self.assertEqual([entry["action"] for entry in replay_one["approval_history"]], ["created"])
        self.assertEqual([entry["action"] for entry in replay_two["approval_history"]], ["created"])

    def test_receipt_includes_prompt_and_approval_queue_entries(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="receipt prompt context test",
            context="approval metadata must appear in receipt timeline",
            scope="src/",
            session_id="session-receipt-approval",
        )
        approval = adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review generated receipt",
            "reason": "metadata-only queue fixture",
            "prompt_id": prompt["id"],
            "evidence_refs": ["local://cleanhouse/prompt/" + prompt["id"]],
        })
        self.assertEqual(approval["status"], "ok")

        receipt = adapter.build_receipt(session_id=prompt["session_id"])
        self.assertEqual(receipt["status"], "ok")
        event_types = [entry["event_type"] for entry in receipt["events"]]
        self.assertIn("prompt", event_types)
        self.assertIn("approval_queue", event_types)
        self.assertEqual(receipt["metadata"]["prompt_id"], prompt["id"])
        self.assertEqual(receipt["metadata"]["context"], "approval metadata must appear in receipt timeline")

    def test_replay_evidence_chain_includes_approval_mediation_proof_ref(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="replay mediation proof ref fixture",
            context="approval mediation proof must be chained in replay evidence",
            scope="src/",
            session_id="session-replay-mediation-proof",
            objective_id="objective-replay-mediation-proof",
        )
        receipt = adapter.build_receipt(session_id=prompt["session_id"])
        self.assertEqual(receipt["status"], "ok")

        approval_result = adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review replay mediation proof chain",
            "reason": "proof chain fixture",
            "evidence_refs": [f"local://cleanhouse/receipt/{receipt['id']}"],
            "prompt_id": prompt["id"],
            "objective_id": "objective-replay-mediation-proof",
            "metadata": {"receipt_id": receipt["id"]},
        })
        self.assertEqual(approval_result["status"], "ok")
        approval_id = approval_result["approval"]["id"]

        adapter.resolve_approval_queue_item(
            approval_id=approval_id,
            status="approved",
            note="proof chain approved",
            reviewer="dashboard",
        )
        replay = adapter.replay_receipt_state(receipt["id"])
        self.assertEqual(replay["status"], "ok")
        self.assertEqual(replay["state"]["approval_id"], approval_id)
        proof_ref = f"local://cleanhouse/approval-mediation-proof/{approval_id}"
        self.assertTrue(any(entry["ref"] == proof_ref for entry in replay["evidence_chain"]))

    def test_intervention_workflow_receipt_and_replay_chain(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        session_id = "session-intervention-workflow"
        adapter.submit_prompt(
            text="Only apply confirmed mediator changes",
            context="intervention workflow chain fixture",
            scope="workspace/",
            session_id=session_id,
            objective_id="objective-intervention-workflow",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "notes.txt"
            target.write_text("before", encoding="utf-8")

            created = adapter.create_operation_proposal({
                "session_id": session_id,
                "objective_id": "objective-intervention-workflow",
                "proposal_type": "mediator",
                "reason": "operator-reviewed write",
                "operations": [{"op": "write_file", "path": "notes.txt", "content": "after"}],
                "metadata": {"repo_path": str(root)},
                "evidence_refs": ["local://cleanhouse/workflow/notes-write"],
            })
            self.assertEqual(created["status"], "ok")
            proposal_id = created["proposal"]["id"]
            self.assertEqual(created["intervention_workflow"]["status"], "intervention_requested")
            approval_id = created["intervention_workflow"]["approval_id"]
            self.assertTrue(approval_id)

            resolved = adapter.resolve_operation_proposal(
                proposal_id,
                "approve",
                {"confirm": True, "repo_path": str(root), "actor": "dashboard", "approval_note": "approved for apply"},
            )
            self.assertEqual(resolved["status"], "ok")
            self.assertEqual(resolved["proposal"]["status"], "applied")
            self.assertEqual(resolved["intervention_workflow"]["status"], "outcome_enforced")
            self.assertEqual(resolved["intervention_workflow"]["approval_id"], approval_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "after")

            receipt = adapter.build_receipt(session_id=session_id)
            self.assertEqual(receipt["status"], "ok")
            self.assertGreaterEqual(len(receipt.get("intervention_workflows", [])), 1)
            workflow = receipt["intervention_workflows"][0]
            self.assertEqual(workflow["proposal_id"], proposal_id)
            self.assertEqual(workflow["approval_id"], approval_id)
            self.assertEqual(workflow["status"], "outcome_enforced")
            self.assertTrue(workflow["decision_recorded_at"])
            self.assertTrue(workflow["outcome_enforced_at"])
            self.assertEqual(workflow["receipt_id"], receipt["id"])
            self.assertIn("actor_attribution", workflow)
            self.assertEqual(workflow["actor_attribution"]["event_detected"]["actor_type"], "operator")
            self.assertEqual(workflow["actor_attribution"]["decision_recorded"]["actor_id"], "dashboard")
            self.assertEqual(workflow["actor_attribution"]["outcome_enforced"]["status"], "observed")
            self.assertTrue(workflow["actor_attribution"]["event_detected"]["attribution_id"].startswith("actor:"))
            self.assertRegex(workflow["actor_attribution"]["event_detected"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("channel_attribution", workflow)
            self.assertEqual(workflow["channel_attribution"]["event_detected"]["execution_channel"], "api")
            self.assertEqual(workflow["channel_attribution"]["decision_recorded"]["execution_channel"], "human")
            self.assertRegex(workflow["channel_attribution"]["decision_recorded"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("trust_attribution", workflow)
            self.assertEqual(workflow["trust_attribution"]["event_detected"]["trust_classification"], "trusted")
            self.assertEqual(workflow["trust_attribution"]["decision_recorded"]["trust_classification"], "trusted")
            self.assertRegex(workflow["trust_attribution"]["decision_recorded"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertTrue(
                any(ref == f"local://cleanhouse/operation-proposal/{proposal_id}" for ref in workflow["evidence_refs"])
            )
            self.assertTrue(
                any(ref == f"local://cleanhouse/approval-queue/{approval_id}" for ref in workflow["evidence_refs"])
            )
            self.assertIn("chain_of_custody", receipt)
            self.assertIn("hops", receipt["chain_of_custody"])
            receipt_hop_names = {hop["hop"] for hop in receipt["chain_of_custody"]["hops"]}
            self.assertEqual(
                receipt_hop_names,
                {"prompt", "objective", "event", "intervention", "decision", "enforcement", "receipt", "replay", "bundle"},
            )
            for hop in receipt["chain_of_custody"]["hops"]:
                self.assertIn("actor", hop)
                self.assertIn(hop["actor"]["status"], {"observed", "inferred", "unknown"})
                self.assertTrue(str(hop["actor"].get("attribution_id", "")).startswith("actor:"))
                self.assertRegex(str(hop["actor"].get("attribution_hash", "")), r"^[0-9a-f]{64}$")
                self.assertIn("channel", hop)
                self.assertIn(hop["channel"]["execution_channel"], {"human", "api", "cli", "agent", "process", "service", "unknown"})
                self.assertRegex(str(hop["channel"].get("attribution_hash", "")), r"^[0-9a-f]{64}$")
                self.assertIn("trust", hop)
                self.assertIn(hop["trust"]["trust_classification"], {"trusted", "untrusted", "unknown", "degraded"})
                self.assertRegex(str(hop["trust"].get("attribution_hash", "")), r"^[0-9a-f]{64}$")
            self.assertIn("replay", receipt["chain_of_custody"]["missing_hops"])
            self.assertIn("bundle", receipt["chain_of_custody"]["missing_hops"])
            self.assertIn("actor_attribution", receipt)
            self.assertEqual(receipt["actor_attribution"]["artifact_type"], "receipt")
            self.assertEqual(receipt["actor_attribution"]["artifact_id"], receipt["id"])
            self.assertEqual(receipt["actor_attribution"]["origin_actor"]["actor_id"], "dashboard")
            self.assertRegex(receipt["actor_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("channel_attribution", receipt)
            self.assertEqual(receipt["channel_attribution"]["artifact_type"], "receipt")
            self.assertEqual(receipt["channel_attribution"]["origin_channel"]["execution_channel"], "human")
            self.assertRegex(receipt["channel_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("trust_attribution", receipt)
            self.assertEqual(receipt["trust_attribution"]["artifact_type"], "receipt")
            self.assertEqual(receipt["trust_attribution"]["origin_trust"]["trust_classification"], "trusted")
            self.assertRegex(receipt["trust_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")

            replay = adapter.replay_receipt_state(receipt["id"])
            self.assertEqual(replay["status"], "ok")
            self.assertTrue(any(entry["ref"] == f"local://cleanhouse/intervention-workflow/{workflow['workflow_id']}" for entry in replay["evidence_chain"]))
            self.assertIn("chain_of_custody", replay)
            self.assertIn("actor_attribution", replay)
            self.assertEqual(replay["actor_attribution"]["artifact_type"], "replay")
            self.assertEqual(replay["actor_attribution"]["origin_actor"]["actor_id"], "dashboard")
            self.assertRegex(replay["actor_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("channel_attribution", replay)
            self.assertEqual(replay["channel_attribution"]["artifact_type"], "replay")
            self.assertEqual(replay["channel_attribution"]["origin_channel"]["execution_channel"], "human")
            self.assertRegex(replay["channel_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("trust_attribution", replay)
            self.assertEqual(replay["trust_attribution"]["artifact_type"], "replay")
            self.assertEqual(replay["trust_attribution"]["origin_trust"]["trust_classification"], "trusted")
            self.assertRegex(replay["trust_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            replay_hops = {hop["hop"]: hop for hop in replay["chain_of_custody"]["hops"]}
            self.assertEqual(replay_hops["replay"]["ref"], f"local://cleanhouse/receipt-replay/{receipt['id']}")
            self.assertIn("bundle", replay["chain_of_custody"]["missing_hops"])

            exported = adapter.export_receipt_timeline_bundle(receipt["id"])
            self.assertEqual(exported["status"], "ok")
            self.assertIn("chain_of_custody", exported["bundle"])
            self.assertTrue(exported["bundle"]["chain_of_custody"]["fully_traceable"])
            self.assertIn("actor_attribution", exported["bundle"])
            self.assertEqual(exported["bundle"]["actor_attribution"]["artifact_type"], "bundle")
            self.assertEqual(exported["bundle"]["actor_attribution"]["origin_actor"]["actor_id"], "dashboard")
            self.assertRegex(exported["bundle"]["actor_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("channel_attribution", exported["bundle"])
            self.assertEqual(exported["bundle"]["channel_attribution"]["artifact_type"], "bundle")
            self.assertEqual(exported["bundle"]["channel_attribution"]["origin_channel"]["execution_channel"], "human")
            self.assertRegex(exported["bundle"]["channel_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("trust_attribution", exported["bundle"])
            self.assertEqual(exported["bundle"]["trust_attribution"]["artifact_type"], "bundle")
            self.assertEqual(exported["bundle"]["trust_attribution"]["origin_trust"]["trust_classification"], "trusted")
            self.assertRegex(exported["bundle"]["trust_attribution"]["attribution_hash"], r"^[0-9a-f]{64}$")
            bundle_hops = {hop["hop"]: hop for hop in exported["bundle"]["chain_of_custody"]["hops"]}
            self.assertEqual(
                bundle_hops["bundle"]["ref"],
                f"local://cleanhouse/receipt-bundle/{exported['bundle']['receipt_id']}",
            )
            self.assertTrue(exported["verification"]["chain_of_custody_present"])
            self.assertTrue(exported["verification"]["chain_of_custody_hops_complete"])
            self.assertTrue(exported["verification"]["chain_of_custody_refs_traceable"])
            self.assertTrue(exported["verification"]["chain_of_custody_bundle_ref_match"])
            self.assertTrue(exported["verification"]["actor_attribution_hash_match"])
            self.assertTrue(exported["verification"]["channel_attribution_hash_match"])
            self.assertTrue(exported["verification"]["trust_attribution_hash_match"])

    def test_diff_temp_file_modification_simulation(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("original")
            (root / "b.py").write_text("stable")

            before = adapter.create_snapshot(repo_path=str(root), label="before")
            self.assertEqual(before["status"], "ok")
            self.assertEqual(before["file_count"], 2)
            before_id = before["id"]

            (root / "a.py").write_text("modified")
            (root / "c.py").write_text("new file")
            (root / "b.py").unlink()

            after = adapter.create_snapshot(repo_path=str(root), label="after")
            self.assertEqual(after["status"], "ok")
            self.assertEqual(after["file_count"], 2)
            after_id = after["id"]

            diff_result = adapter.compute_diff(before_id, after_id, session_id="intent:test")
            self.assertEqual(diff_result["status"], "ok")
            self.assertEqual(diff_result["created_count"], 1)
            self.assertEqual(diff_result["modified_count"], 1)
            self.assertEqual(diff_result["deleted_count"], 1)

            change_map = {c: t for c, t in [(r, r) for r in diff_result.get("changes", [])]}
            # Re-fetch via get_diffs to verify session link
            diffs = adapter.get_diffs(session_id="intent:test")
            self.assertEqual(diffs["count"], 1)
            first = diffs["diffs"][0]
            self.assertEqual(first["session_id"], "intent:test")
            self.assertEqual(first["created_count"], 1)
            self.assertEqual(first["modified_count"], 1)
            self.assertEqual(first["deleted_count"], 1)
            changes_by_path = {c["path"]: c["change_type"] for c in first["changes"]}
            self.assertEqual(changes_by_path["a.py"], "modified")
            self.assertEqual(changes_by_path["c.py"], "created")
            self.assertEqual(changes_by_path["b.py"], "deleted")

    def test_compute_diff_emits_file_mutation_runtime_events_for_timeline_and_receipt(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        session_id = "mutation-events-session"
        adapter.submit_prompt(
            text="Track file mutations",
            context="mutation tracking runtime event fixture",
            scope="src/",
            session_id=session_id,
            objective_id="objective-mutation-events",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir(parents=True)
            (src / "a.py").write_text("print('v1')", encoding="utf-8")
            (src / "b.py").write_text("print('keep')", encoding="utf-8")

            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=session_id)
            (src / "a.py").write_text("print('v2')", encoding="utf-8")
            (src / "c.py").write_text("print('new')", encoding="utf-8")
            (src / "b.py").unlink()
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=session_id)

            diff = adapter.compute_diff(before["id"], after["id"], session_id=session_id)
            self.assertEqual(diff["status"], "ok")

        timeline = adapter.build_timeline(session_id=session_id)
        self.assertEqual(timeline["status"], "ok")
        mutation_entries = [entry for entry in timeline["entries"] if entry.get("event_type") == "file_mutation"]
        self.assertGreaterEqual(len(mutation_entries), 3)
        mutation_types = {
            entry.get("data", {}).get("persisted_event_type")
            for entry in mutation_entries
            if isinstance(entry.get("data"), dict)
        }
        self.assertTrue({"created", "modified", "deleted"}.issubset(mutation_types))
        mutation_refs = {
            ref
            for entry in mutation_entries
            for ref in entry.get("evidence_refs", [])
            if isinstance(ref, str)
        }
        self.assertTrue(any(ref.startswith("local://cleanhouse/diff/") for ref in mutation_refs))

        receipt = adapter.build_receipt(session_id=session_id)
        self.assertEqual(receipt["status"], "ok")
        receipt_event_types = [entry.get("event_type") for entry in receipt["events"]]
        self.assertIn("file_mutation", receipt_event_types)

    def test_correlation_full_chain(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("edit a.py", scope="test")
        intent_id = intent_result["id"]
        self.assertEqual(intent_result["status"], "ok")

        observer = get_observer()
        observer.run(["echo", "correlation-test"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("original")

            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            self.assertEqual(before["status"], "ok")
            before_id = before["id"]

            (root / "a.py").write_text("modified")

            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            after_id = after["id"]

            diff_result = adapter.compute_diff(before_id, after_id, session_id=intent_id)
            self.assertEqual(diff_result["status"], "ok")
            self.assertEqual(diff_result["modified_count"], 1)

            corr = adapter.correlate(session_id=intent_id)
            self.assertEqual(corr["status"], "ok")
            self.assertGreaterEqual(corr["edge_count"], 2)

            rel_types = {e["relationship"] for e in corr["edges"]}
            target_types = {e["target_type"] for e in corr["edges"]}
            self.assertIn("temporal_proximity", rel_types)
            self.assertIn("session_link", rel_types)
            self.assertIn("command", target_types)
            self.assertIn("diff", target_types)

            for edge in corr["edges"]:
                self.assertGreaterEqual(edge["confidence"], 0.0)
                self.assertLessEqual(edge["confidence"], 1.0)
                self.assertIn(edge["observed_vs_expected"]["status"], {"matched", "unknown"})

            stored = adapter.get_correlations(session_id=intent_id)
            self.assertEqual(stored["count"], 1)
            self.assertEqual(stored["correlations"][0]["edge_count"], corr["edge_count"])

    def test_correlation_intent_no_command(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("query data", scope="read")
        intent_id = intent_result["id"]

        corr = adapter.correlate(session_id=intent_id)
        self.assertEqual(corr["status"], "ok")
        self.assertEqual(corr["edge_count"], 1)

        edge = corr["edges"][0]
        self.assertEqual(edge["source_type"], "intent")
        self.assertEqual(edge["target_type"], "unknown")
        self.assertEqual(edge["relationship"], "temporal_proximity")
        self.assertEqual(edge["confidence"], 0.0)
        self.assertEqual(edge["observed_vs_expected"]["status"], "unknown")

    def test_timeline_orders_events_chronologically(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("refactor module", scope="edit")
        intent_id = intent_result["id"]
        self.assertEqual(intent_result["status"], "ok")

        observer = get_observer()
        observer.run(["echo", "step-1"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text("v1")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "a.py").write_text("v2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["entry_count"], 3)

        entries = result["entries"]
        timestamps = [e["timestamp"] for e in entries]
        self.assertEqual(timestamps, sorted(timestamps))

        types = [e["event_type"] for e in entries]
        self.assertEqual(types[0], "intent")

        stored = adapter.get_timelines(session_id=intent_id)
        self.assertEqual(stored["count"], 1)
        self.assertEqual(stored["timelines"][0]["entry_count"], result["entry_count"])

    def test_timeline_unknown_session(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.build_timeline(session_id="nonexistent-session")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["entry_count"], 1)

        entry = result["entries"][0]
        self.assertEqual(entry["event_type"], "unknown")
        self.assertEqual(entry["status"], "unknown")
        self.assertEqual(entry["previous_event_id"], None)

    def test_classification_scope_expansion_deviation(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("edit src code", scope="src")
        intent_id = intent_result["id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            (src / "a.py").write_text("v1")
            (root / "config.ini").write_text("setting=1")

            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (src / "a.py").write_text("v2")
            (root / "config.ini").write_text("setting=2")

            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        adapter.build_timeline(session_id=intent_id)
        adapter.correlate(session_id=intent_id)
        result = adapter.classify(session_id=intent_id)

        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["signal_count"], 0)

        deviations = [s for s in result["signals"] if s["signal_class"] == "deviation"]
        self.assertGreater(len(deviations), 0, "Expected at least one deviation signal for scope expansion")
        dev = deviations[0]
        self.assertEqual(dev["source"], "diff")
        self.assertEqual(dev["observed_vs_expected"]["status"], "unexpected")

        drifts = [s for s in result["signals"] if s["signal_class"] == "drift"]
        self.assertGreater(len(drifts), 0, "Expected at least one drift signal")

        stored = adapter.get_signals(session_id=intent_id)
        self.assertEqual(stored["count"], result["signal_count"])

        dev_only = adapter.get_signals(session_id=intent_id, signal_class="deviation")
        self.assertEqual(dev_only["count"], len(deviations))

    def test_classification_noncritical_low_risk(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("run tests", scope="test")
        intent_id = intent_result["id"]

        get_observer().run(["false"], capture_output=True)

        adapter.build_timeline(session_id=intent_id)
        result = adapter.classify(session_id=intent_id)

        self.assertEqual(result["status"], "ok")

        command_signals = [s for s in result["signals"] if s["source"] == "command"]
        self.assertGreater(len(command_signals), 0)
        for sig in command_signals:
            self.assertEqual(sig["signal_class"], "deviation")
            self.assertLess(sig["confidence"], 0.9)
            self.assertGreater(sig["uncertainty"], 0.1)

        has_risk = any(s["signal_class"] == "risk" for s in result["signals"])
        self.assertFalse(has_risk, "Non-critical command mismatch should not produce risk signals")

    def test_alert_scope_expansion_low(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("edit code", scope="src")
        intent_id = intent_result["id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("ok")
            (root / "config.ini").write_text("setting=1")

            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "a.py").write_text("ok2")
            (root / "config.ini").write_text("setting=2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        adapter.build_timeline(session_id=intent_id)
        adapter.correlate(session_id=intent_id)
        adapter.classify(session_id=intent_id)
        result = adapter.generate_alerts(session_id=intent_id)

        self.assertEqual(result["status"], "ok")
        scope_alerts = [a for a in result["alerts"] if a["alert_type"] == "scope_expansion"]
        self.assertGreater(len(scope_alerts), 0)
        alert = scope_alerts[0]
        self.assertEqual(alert["severity"], "low")
        self.assertGreaterEqual(alert["confidence"], 0.45)

    def test_generate_alerts_autoclassifies_scope_expansion_without_manual_classify(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("edit code", scope="src")
        intent_id = intent_result["id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("ok")
            (root / "config.ini").write_text("setting=1")

            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "a.py").write_text("ok2")
            (root / "config.ini").write_text("setting=2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        adapter.build_timeline(session_id=intent_id)
        adapter.correlate(session_id=intent_id)
        result = adapter.generate_alerts(session_id=intent_id)

        self.assertEqual(result["status"], "ok")
        scope_alerts = [a for a in result["alerts"] if a["alert_type"] == "scope_expansion"]
        self.assertGreater(len(scope_alerts), 0)
        fallback_alerts = [
            a for a in result["alerts"]
            if a["alert_type"] == "endpoint_drift"
            and "No classified signals available for alert generation" in a.get("description", "")
        ]
        self.assertEqual(fallback_alerts, [])

    def test_alert_prompt_action_medium(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("run tests", scope="test")
        intent_id = intent_result["id"]

        for _ in range(2):
            get_observer().run(["false"], capture_output=True)

        adapter.build_timeline(session_id=intent_id)
        adapter.classify(session_id=intent_id)
        result = adapter.generate_alerts(session_id=intent_id)

        self.assertEqual(result["status"], "ok")
        mismatch_alerts = [a for a in result["alerts"] if a["alert_type"] == "prompt_action_mismatch"]
        self.assertGreater(len(mismatch_alerts), 0)
        alert = mismatch_alerts[0]
        self.assertEqual(alert["severity"], "medium")
        self.assertLess(alert["confidence"], 0.7)

    def test_alert_endpoint_drift_high(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("unknown task")
        intent_id = intent_result["id"]

        result = adapter.generate_alerts(session_id=intent_id)
        self.assertEqual(result["status"], "ok")

        drift_alerts = [a for a in result["alerts"] if a["alert_type"] == "endpoint_drift"]
        self.assertGreater(len(drift_alerts), 0)

        high_severity = [a for a in result["alerts"] if a["severity"] == "high"]
        self.assertGreater(len(high_severity), 0)

        worst = result["alerts"][0]
        self.assertEqual(worst["severity"], "high")
        self.assertEqual(worst["confidence"], 0.0)

        stored = adapter.get_alerts(session_id=intent_id)
        self.assertEqual(stored["count"], result["alert_count"])

        type_filtered = adapter.get_alerts(session_id=intent_id, alert_type="endpoint_drift")
        self.assertGreater(type_filtered["count"], 0)

    def test_receipt_from_complete_session(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("test complete session", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "ok"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("v1")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "a.py").write_text("v2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.build_receipt(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        self.assertIn("id", result)
        self.assertEqual(result["session_id"], intent_id)

        meta = result["metadata"]
        self.assertEqual(meta["session_id"], intent_id)
        self.assertIsNotNone(meta["duration_seconds"])
        self.assertGreaterEqual(meta["event_count"], 3)
        self.assertGreaterEqual(meta["alert_count"], 0)
        self.assertGreaterEqual(meta["gap_count"], 0)

        summary = result["summary"]
        self.assertIn(summary["verdict"], {"observed", "inferred", "unknown"})
        self.assertIn("test complete session", summary["text"])

        self.assertGreater(len(result["events"]), 0)
        self.assertGreater(len(result["evidence_index"]), 0)

        stored = adapter.get_receipts(session_id=intent_id)
        self.assertGreaterEqual(stored["count"], 1)
        self.assertEqual(stored["receipts"][0]["session_id"], intent_id)

    def test_receipt_with_partial_failures(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.build_receipt(session_id="nonexistent-session")
        self.assertEqual(result["status"], "ok")

        self.assertGreater(len(result["gaps"]), 0, "Expected at least one gap for unknown session")
        gap = result["gaps"][0]
        self.assertEqual(gap["label"], "unknown")

        summary = result["summary"]
        self.assertEqual(summary["verdict"], "unknown")

        meta = result["metadata"]
        self.assertGreaterEqual(meta["gap_count"], 1)

    def test_receipt_integrity_chain_determinism(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("integrity test", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "verify"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("v1")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "a.py").write_text("v2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.build_receipt(session_id=intent_id)
        integrity = result["integrity"]

        self.assertEqual(integrity["algorithm"], "sha-256")
        self.assertEqual(integrity["event_count"], len(result["events"]))
        self.assertEqual(len(integrity["event_hash_chain"]), integrity["event_count"])
        self.assertGreater(len(integrity["root_hash"]), 0)
        self.assertEqual(integrity["purpose"], "receipt integrity verification")

        # Rebuild — chain must be identical
        result2 = adapter.build_receipt(session_id=intent_id)
        self.assertEqual(result2["integrity"]["event_hash_chain"], integrity["event_hash_chain"])
        self.assertEqual(result2["integrity"]["root_hash"], integrity["root_hash"])

        # Verify each link corresponds to its event
        for i, event_hash in enumerate(integrity["event_hash_chain"]):
            self.assertIsInstance(event_hash, str)
            self.assertEqual(len(event_hash), 64)  # SHA-256 hex

    def test_receipt_integrity_tamper_detection(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("tamper test")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "tamper-check"], capture_output=True)

        result = adapter.build_receipt(session_id=intent_id)
        original_integrity = result["integrity"]
        original_events = result["events"]

        # Simulate tampering: modify first event's label
        tampered_events = list(original_events)
        if tampered_events:
            ev = dict(tampered_events[0])
            ev["label"] = "TAMPERED_" + ev.get("label", "")
            tampered_events[0] = ev

        # Recompute hash chain on tampered events
        import hashlib
        import json
        tampered_chain = []
        prev = ""
        for event in tampered_events:
            canonical = json.dumps(event, sort_keys=True, default=str)
            prev = hashlib.sha256((prev + canonical).encode()).hexdigest()
            tampered_chain.append(prev)

        self.assertNotEqual(
            tampered_chain,
            original_integrity["event_hash_chain"],
            "Tampered events should produce different hash chain",
        )

        # Verify original chain is unchanged
        verify_chain = []
        prev = ""
        for event in original_events:
            canonical = json.dumps(event, sort_keys=True, default=str)
            prev = hashlib.sha256((prev + canonical).encode()).hexdigest()
            verify_chain.append(prev)
        self.assertEqual(verify_chain, original_integrity["event_hash_chain"])

    def test_report_returns_payload_and_preserves_evidence_ids(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("report test", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "report-check"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("v1")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "a.py").write_text("v2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.build_report(
            session_id=intent_id,
            report_type="audit",
            contact="analyst@example.com",
            target="staging-1",
            context="weekly audit check",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["report_type"], "audit")
        self.assertEqual(result["contact"], "analyst@example.com")
        self.assertEqual(result["target"], "staging-1")
        self.assertEqual(result["context"], "weekly audit check")

        self.assertGreater(len(result["evidence_links"]), 0)
        for link in result["evidence_links"]:
            self.assertTrue(link.startswith("local://cleanhouse/timeline/"))

        receipt = result["receipt"]
        self.assertIn("id", receipt)
        self.assertIn("session_id", receipt)
        self.assertIn("metadata", receipt)
        self.assertIn("summary", receipt)
        self.assertIn("events", receipt)
        self.assertIn("alerts", receipt)
        self.assertIn("gaps", receipt)
        self.assertIn("evidence_index", receipt)
        self.assertIn("integrity", receipt)

        self.assertEqual(
            receipt["integrity"]["purpose"],
            "receipt integrity verification",
        )

        # Rebuild report with same session must also succeed
        result2 = adapter.build_report(session_id=intent_id)
        self.assertEqual(result2["status"], "ok")
        self.assertEqual(result2["report_type"], "incident")

    def test_report_missing_receipt_returns_not_found(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.build_report(session_id="no-such-session")
        self.assertEqual(result["status"], "not_found")

    def test_login_report_covers_events_since_previous_login_and_persists(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        events = [
            {
                "id": 1,
                "timestamp": "2026-05-26T08:59:59",
                "session_id": "before",
                "event_type": "modified",
                "summary": "before window",
                "evidence_refs": [],
            },
            {
                "id": 2,
                "timestamp": "2026-05-26T09:15:00",
                "session_id": "session-a",
                "event_type": "shell_event",
                "summary": "inside window",
                "evidence_refs": ["local://cleanhouse/command/demo"],
            },
            {
                "id": 3,
                "timestamp": "2026-05-26T11:01:00",
                "session_id": "after",
                "event_type": "modified",
                "summary": "after window",
                "evidence_refs": [],
            },
        ]

        with patch.object(monitoring_module.cleanhouse_events, "list_events", return_value=events), patch.object(
            monitoring_module.cleanhouse_events, "insert_event_async"
        ):
            result = adapter.build_login_report(
                user_id="user-1",
                email="user@example.com",
                previous_login_at="2026-05-26T09:00:00",
                current_login_at="2026-05-26T11:00:00",
                trigger="auth/login",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["report_type"], "login_summary")
        self.assertEqual(result["metadata"]["previous_login_at"], "2026-05-26T09:00:00")
        self.assertEqual(result["metadata"]["current_login_at"], "2026-05-26T11:00:00")
        self.assertEqual(result["receipt"]["summary"]["event_count"], 1)
        self.assertEqual(result["receipt"]["summary"]["event_type_counts"]["shell_event"], 1)
        self.assertIn("local://cleanhouse/event/2", result["evidence_links"])
        self.assertIn("local://cleanhouse/command/demo", result["evidence_links"])

        reloaded = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0).get_reports()
        self.assertTrue(
            any(report.get("id") == result["id"] for report in reloaded["reports"]),
            "persisted login report should load through get_reports",
        )

    def test_login_report_coordinator_accepts_two_queued_jobs_then_backpressures(self):
        started = threading.Event()
        release = threading.Event()

        def build_report(**payload):
            started.set()
            release.wait(timeout=2.0)
            return {
                "status": "ok",
                "id": f"report:{payload['user_id']}",
                "report_type": "login_summary",
            }

        coordinator = LoginReportCoordinator(build_report)
        first = coordinator.submit(user_id="user-1")
        self.assertEqual(first["status"], "accepted")
        self.assertTrue(started.wait(timeout=1.0), "worker should start the first job")

        second = coordinator.submit(user_id="user-2")
        third = coordinator.submit(user_id="user-3")
        fourth = coordinator.submit(user_id="user-4")

        self.assertEqual(second["status"], "accepted")
        self.assertEqual(third["status"], "accepted")
        self.assertEqual(fourth["status"], "rate_limited")
        self.assertEqual(fourth["job"]["state"], "rejected")
        release.set()

    def test_submit_login_report_waits_and_poll_returns_completed_job(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.object(monitoring_module.cleanhouse_events, "list_events", return_value=[]), patch.object(
            monitoring_module.cleanhouse_events, "insert_event_async"
        ):
            result = adapter.submit_login_report(
                user_id="user-1",
                email="user@example.com",
                previous_login_at="2026-05-26T09:00:00",
                current_login_at="2026-05-26T11:00:00",
                trigger="auth/login",
                wait_timeout_seconds=1.0,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["report_type"], "login_summary")
        self.assertEqual(result["job"]["state"], "succeeded")

        polled = adapter.poll_login_report(result["job_id"])
        self.assertEqual(polled["status"], "ok")
        self.assertEqual(polled["id"], result["id"])
        self.assertEqual(polled["job"]["state"], "succeeded")

    def test_get_reports_filters_limits_and_summarizes_login_reports(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        events = [
            {
                "id": 2,
                "timestamp": "2026-05-26T09:15:00",
                "session_id": "session-a",
                "event_type": "shell_event",
                "summary": "inside window",
                "evidence_refs": ["local://cleanhouse/command/demo"],
            },
        ]

        with patch.object(monitoring_module.cleanhouse_events, "list_events", return_value=events), patch.object(
            monitoring_module.cleanhouse_events, "insert_event_async"
        ):
            result = adapter.build_login_report(
                user_id="user-1",
                email="user@example.com",
                previous_login_at="2026-05-26T09:00:00",
                current_login_at="2026-05-26T11:00:00",
                trigger="auth/login",
            )

        reports = adapter.get_reports(report_type="login_summary", limit=1, summary_only=True)
        self.assertEqual(reports["count"], 1)
        report = reports["reports"][0]
        self.assertEqual(report["id"], result["id"])
        self.assertEqual(report["report_type"], "login_summary")
        self.assertIn("summary", report["receipt"])
        self.assertNotIn("events", report["receipt"])
        self.assertNotIn("receipts", report["receipt"])
        self.assertNotIn("reports", report["receipt"])

    def test_login_report_route_status_codes_follow_job_state(self):
        self._set_request_json({"user_id": "user-1", "email": "user@example.com"})

        class RouteAdapter:
            def __init__(self, payload):
                self.payload = payload

            def submit_login_report(self, **kwargs):
                return self.payload

        cases = [
            ({"status": "ok", "id": "report:done", "job": {"state": "succeeded"}}, 200),
            ({"status": "accepted", "job_id": "job:queued", "job": {"state": "queued"}}, 202),
            ({"status": "rate_limited", "job_id": "job:full", "job": {"state": "rejected"}}, 429),
        ]
        for payload, expected_status in cases:
            with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=RouteAdapter(payload)):
                body, status = self._unwrap_response_tuple(cleanhouse_module.build_login_report())
            self.assertEqual(status, expected_status)
            self.assertEqual(body["status"], payload["status"])

    def test_poll_login_report_route_returns_queued_status(self):
        class RouteAdapter:
            def poll_login_report(self, job_id):
                return {"status": "accepted", "job_id": job_id, "job": {"state": "running"}}

        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=RouteAdapter()):
            body, status = self._unwrap_response_tuple(cleanhouse_module.poll_login_report("job:1"))

        self.assertEqual(status, 202)
        self.assertEqual(body["job"]["state"], "running")

    def test_zaelith_unavailable_returns_graceful_unknown(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch(
            "corefiles.zaelith_service.get_zaelith_service",
            side_effect=ImportError("no zaelith"),
        ):
            result = adapter.run_zaelith_inference(session_id="any-session")
        self.assertEqual(result["status"], "ok")
        inf = result["inference"]
        self.assertEqual(inf["status"], "unavailable")
        self.assertFalse(inf["zaelith_available"])
        self.assertEqual(inf["confidence"], 0.0)
        self.assertEqual(inf["confidence_level"], "unknown")
        self.assertEqual(inf["inference_label"], "inferred")
        self.assertIn("zaelith service import failed", inf["unknown_fields"])

    def test_zaelith_available_generates_inference(self):
        from corefiles.zaelith_service import get_zaelith_service

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("verify code integrity", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "all tests pass"], capture_output=True)

        result = adapter.run_zaelith_inference(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        inf = result["inference"]
        self.assertEqual(inf["status"], "available")
        self.assertTrue(inf["zaelith_available"])
        self.assertEqual(inf["inference_label"], "inferred")
        self.assertIsInstance(inf["confidence"], float)
        self.assertGreaterEqual(inf["confidence"], 0.0)
        self.assertLessEqual(inf["confidence"], 1.0)

    def test_persist_migration_from_old_schema(self):
        subdir = config.ARTIFACT_SUBDIRS["receipt"]
        v0_dir = config.DATA_DIR / subdir / "v0"
        v0_dir.mkdir(parents=True, exist_ok=True)
        old_data = {"foo": "bar", "count": 42}
        old_file = v0_dir / "old-receipt.json"
        old_file.write_text(
            json.dumps(old_data),
            encoding="utf-8",
        )
        try:
            result = PersistenceBackend.read("receipt", "old-receipt")
            self.assertIsNotNone(result)
            self.assertEqual(result["schema_version"], 0)
            self.assertTrue(result.get("v0_compat", False))
            self.assertEqual(result.get("foo"), "bar")
            self.assertEqual(result.get("count"), 42)
        finally:
            old_file.unlink(missing_ok=True)

    def test_persist_round_trip(self):
        subdir = config.ARTIFACT_SUBDIRS["receipt"]
        v1_dir = config.DATA_DIR / subdir / "v1"
        v1_dir.mkdir(parents=True, exist_ok=True)
        test_data = {"session_id": "test-session", "event_count": 3}
        try:
            result = PersistenceBackend.persist("receipt", "round-trip-test", test_data)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["schema_version"], 1)

            loaded = PersistenceBackend.read("receipt", "round-trip-test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["schema_version"], 1)
            self.assertEqual(loaded["artifact_type"], "receipt")
            self.assertEqual(loaded["data"]["session_id"], "test-session")
            self.assertEqual(loaded["data"]["event_count"], 3)
        finally:
            target = v1_dir / "round-trip-test.json"
            if target.exists():
                target.unlink()

    def test_prune_requires_confirm(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(config, "DATA_DIR", Path(tmpdir)):
                adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
                adapter.persistence_enabled = True

                # Without confirm → error
                result = adapter.prune_all_artifacts({})
                self.assertEqual(result["status"], "error")
                self.assertIn("confirm required", result["message"])

                # With confirm=true → ok
                result = adapter.prune_all_artifacts({"confirm": True})
                self.assertEqual(result["status"], "ok")
                self.assertIn("pruned", result)
                self.assertIn("retention_events_count", result)

    def test_prune_deterministic_auditable(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(config, "DATA_DIR", Path(tmpdir)):
                adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
                adapter.persistence_enabled = True

                # Create 3 snapshot artifacts
                snap_subdir = config.DATA_DIR / "snapshots" / "v1"
                snap_subdir.mkdir(parents=True, exist_ok=True)
                for i in range(3):
                    (snap_subdir / f"snap-{i}.json").write_text(
                        json.dumps({"id": f"snap-{i}"}), encoding="utf-8"
                    )

                # Create 3 diff artifacts
                diff_subdir = config.DATA_DIR / "diffs" / "v1"
                diff_subdir.mkdir(parents=True, exist_ok=True)
                for i in range(3):
                    (diff_subdir / f"diff-{i}.json").write_text(
                        json.dumps({"id": f"diff-{i}"}), encoding="utf-8"
                    )

                # Prune with confirm=true, max_count=1 for snapshots
                result = adapter.prune_all_artifacts({
                    "confirm": True,
                    "artifact_types": ["snapshot"],
                    "max_count": 1,
                })
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["pruned"], 2)  # 3 - 1 = 2 deleted
                self.assertEqual(result["retention_events_count"], 1)

                # Verify retention event recorded
                events = adapter.get_retention_events()
                self.assertEqual(events["count"], 1)
                ev = events["retention_events"][0]
                self.assertEqual(ev["artifact_type"], "snapshot")
                self.assertEqual(ev["before_count"], 3)
                self.assertEqual(ev["after_count"], 1)
                self.assertEqual(ev["deleted_count"], 2)
                self.assertEqual(ev["max_count"], 1)
                self.assertEqual(len(ev["deleted_files"]), 2)
                self.assertEqual(ev["operator"], "api")

                # Verify only 1 snapshot file remains
                remaining = list(snap_subdir.iterdir())
                self.assertEqual(len(remaining), 1)

    def test_tool_event_ingestion(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_tool_event({
            "tool_identity": "cursor",
            "command": "python3",
            "args": ["python3", "test.py"],
            "exit_code": 0,
            "session_id": "test-session",
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tool_identity"], "cursor")

        collected = adapter.get_tool_events(refresh=True)
        self.assertEqual(collected["status"], "safe")
        data = collected.get("data", {})
        event_list = data.get("tool_events", [])
        self.assertGreaterEqual(len(event_list), 1)
        self.assertEqual(event_list[0]["tool_identity"], "cursor")
        self.assertEqual(event_list[0]["command"], "python3")

        for issue in collected["issues"]:
            title = issue.get("message", "")
            self.assertIn("tool context captured", title)

    def test_tool_unknown_mapping(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_tool_event({
            "tool_identity": "some_random_ide",
            "command": "npm",
            "args": ["npm", "run", "build"],
            "exit_code": 0,
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tool_identity"], "tool_unknown")

        collected = adapter.get_tool_events(refresh=True)
        data = collected.get("data", {})
        event_list = data.get("tool_events", [])
        self.assertGreaterEqual(len(event_list), 1)
        self.assertEqual(event_list[0]["tool_identity"], "tool_unknown")

    def test_tool_event_only_receipt_includes_unsupported_shell_gap(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.submit_prompt(
            text="Observe external tool action",
            context="unsupported shell gap fixture",
            scope="src/",
            session_id="unsupported-shell-session",
            objective_id="objective-unsupported-shell",
        )
        adapter.submit_tool_event({
            "tool_identity": "cursor",
            "command": "npm run build",
            "args": ["npm", "run", "build"],
            "exit_code": 0,
            "session_id": "unsupported-shell-session",
            "objective_id": "objective-unsupported-shell",
        })
        receipt = adapter.build_receipt("unsupported-shell-session")
        self.assertEqual(receipt["status"], "ok")
        unsupported_shell_gaps = [
            gap for gap in receipt["gaps"]
            if gap.get("source") == "command_observer"
            and gap.get("label") == "unknown"
            and "unsupported-shell action observed outside owned command observer" in gap.get("description", "")
        ]
        self.assertEqual(len(unsupported_shell_gaps), 1)
        self.assertTrue(unsupported_shell_gaps[0]["event_id"].startswith("unsupported-shell:"))
        self.assertTrue(any(ref.startswith("local://cleanhouse/tool-event/") for ref in unsupported_shell_gaps[0].get("evidence_refs", [])))

    def test_tool_event_with_owned_command_observer_has_no_unsupported_shell_gap(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.submit_prompt(
            text="Observe owned command and tool action",
            context="owned shell command fixture",
            scope="src/",
            session_id="owned-shell-session",
            objective_id="objective-owned-shell",
        )
        adapter._on_command_completed(CommandResult(
            command="npm",
            args=("npm", "run", "build"),
            cwd=str(Path.cwd()),
            user="dev",
            returncode=0,
            duration=0.5,
            timestamp="2026-05-29T12:00:00",
            stdout_preview="ok",
            stderr_preview="",
            session_id="owned-shell-session",
            objective_id="objective-owned-shell",
            child_pid=32100,
        ))
        adapter.submit_tool_event({
            "tool_identity": "cursor",
            "command": "npm run build",
            "args": ["npm", "run", "build"],
            "exit_code": 0,
            "session_id": "owned-shell-session",
            "objective_id": "objective-owned-shell",
        })
        receipt = adapter.build_receipt("owned-shell-session")
        self.assertEqual(receipt["status"], "ok")
        unsupported_shell_gaps = [
            gap for gap in receipt["gaps"]
            if gap.get("source") == "command_observer"
            and "unsupported-shell action observed outside owned command observer" in gap.get("description", "")
        ]
        self.assertEqual(unsupported_shell_gaps, [])

    def test_cloud_usage_returns_adapter_status(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.get_cloud_usage(refresh=True)
        self.assertEqual(result["status"], "safe")
        self.assertIn("issues", result)
        data = result.get("data", {})
        adapters = data.get("cloud_usage_adapters", [])
        self.assertGreaterEqual(len(adapters), 5)
        for adp in adapters:
            self.assertIn(adp["status"], {"supported", "unsupported"}, f"provider={adp['provider']}")
            self.assertIsInstance(adp["observed_indicators"], list)
            self.assertIsInstance(adp["limitation"], str)
            self.assertGreater(len(adp["limitation"]), 0)

    def test_cloud_usage_unsupported_explicit_limitation(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.get_cloud_usage(refresh=True)
        data = result.get("data", {})
        adapters = data.get("cloud_usage_adapters", [])
        unsupported = [a for a in adapters if a["status"] == "unsupported"]
        self.assertGreater(len(unsupported), 0)
        for a in unsupported:
            self.assertEqual(len(a["observed_indicators"]), 0)
            self.assertIn("not inspected", a["limitation"].lower())

    def test_plugin_register_toggle_scope(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        result = adapter.register_plugin({
            "id": "test_adapter_v1",
            "name": "Test Adapter",
            "version": "1.0.0",
            "description": "Integration test plugin",
            "enabled": False,
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["plugin"]["id"], "test_adapter_v1")
        self.assertFalse(result["plugin"]["enabled"])

        listed = adapter.get_plugins()
        ids = [p["id"] for p in listed["plugins"]]
        self.assertIn("test_adapter_v1", ids)

        toggled = adapter.update_plugin("test_adapter_v1", {"enabled": True, "scope": "src"})
        self.assertEqual(toggled["status"], "ok")
        self.assertTrue(toggled["plugin"]["enabled"])
        self.assertEqual(toggled["plugin"]["scope"], "src")

    def test_plugin_unknown_id_warning(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.update_plugin("nonexistent_plugin", {"enabled": True})
        self.assertEqual(result["status"], "error")
        self.assertIn("Unknown plugin", result["message"])

    def test_settings_toggle_persistence(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        before = adapter.get_settings()
        self.assertEqual(before["status"], "ok")
        self.assertTrue(before["settings"]["collectors"]["process_monitor"])

        result = adapter.update_settings({"collectors": {"process_monitor": False}})
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["settings"]["collectors"]["process_monitor"])

        after = adapter.get_settings()
        self.assertFalse(after["settings"]["collectors"]["process_monitor"])

        result = adapter.update_settings({"collectors": {"process_monitor": True}})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["settings"]["collectors"]["process_monitor"])

    def test_settings_invalid_threshold_fallback(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.update_settings({"risk_thresholds": {"alert_signal_count": {"high": -1}}})
        self.assertEqual(result["status"], "error")
        self.assertIn("non-negative", result["message"])

        result = adapter.update_settings({"risk_thresholds": {"alert_confidence_min": 1.5}})
        self.assertEqual(result["status"], "error")
        self.assertIn("between 0 and 1", result["message"])

        original = adapter.get_settings()
        self.assertEqual(original["settings"]["risk_thresholds"]["alert_confidence_min"], 0.45)

    def test_notification_policy_settings_accepts_reminder_and_bypass_keys(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.update_settings({
            "notification_policy": {
                "max_native_reminders_per_notification": 3,
                "cooldown_bypass_types": ["approval_required"],
            }
        })
        self.assertEqual(result["status"], "ok")
        policy = result["settings"]["notification_policy"]
        self.assertEqual(policy["max_native_reminders_per_notification"], 3)
        self.assertEqual(policy["cooldown_bypass_types"], ["approval_required"])

        bad_int = adapter.update_settings({
            "notification_policy": {"max_native_reminders_per_notification": "3"}
        })
        self.assertEqual(bad_int["status"], "error")
        self.assertIn("must be a positive integer", bad_int["message"])

        bad_list = adapter.update_settings({
            "notification_policy": {"cooldown_bypass_types": "approval_required"}
        })
        self.assertEqual(bad_list["status"], "error")
        self.assertIn("must be a list", bad_list["message"])

    def test_notification_policy_defaults_cover_required_agent_notifications(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        policy = adapter.get_settings()["settings"]["notification_policy"]
        self.assertTrue(policy["fanout_all_backends"])
        self.assertEqual(policy["backend_order"], "osascript_first")
        self.assertFalse(policy["codex_activity_native_enabled"])
        self.assertEqual(
            set(policy["hard_interrupt_types"]),
            {
                "session_started",
                "session_ended",
                "scope_drift_detected",
            },
        )
        self.assertEqual(
            set(policy["cooldown_bypass_types"]),
            {
                "session_started",
                "session_ended",
                "scope_drift_detected",
            },
        )

    def test_scope_high_confidence_mismatch(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("fix auth module", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["cp", "/etc/passwd", "/tmp/backup"], capture_output=True)

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("v1")
            (root / "etc").mkdir()
            (root / "etc" / "hosts").write_text("x")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "etc" / "hosts").write_text("y")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.run_scope_alignment(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["session_id"], intent_id)

        ar = result["alignment_risk"]
        self.assertEqual(ar["level"], "high")
        self.assertTrue(ar["deterministic_drift"])
        self.assertGreaterEqual(ar["confidence"], 0.5)
        self.assertGreater(len(ar["evidence"]), 0)

        bmr = result["behavioral_mismatch_risk"]
        self.assertEqual(bmr["level"], "high")
        self.assertGreaterEqual(bmr["confidence"], 0.8)
        self.assertGreater(len(bmr["evidence"]), 0)

    def test_scope_partial_mismatch_medium_unknown(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("update documentation", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "no-op check"], capture_output=True)

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("v1")
            (root / "dist").mkdir()
            (root / "dist" / "bundle.js").write_text("v1")
            before = adapter.create_snapshot(repo_path=str(root), label="before", session_id=intent_id)
            (root / "src" / "main.py").write_text("v2")
            (root / "dist" / "bundle.js").write_text("v2")
            after = adapter.create_snapshot(repo_path=str(root), label="after", session_id=intent_id)
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        result = adapter.run_scope_alignment(session_id=intent_id)
        self.assertEqual(result["status"], "ok")

        ar = result["alignment_risk"]
        self.assertIn(ar["level"], ("medium", "high", "low"))
        if ar["semantic_drift"] is True:
            self.assertEqual(ar["level"], "medium")
        self.assertIsNotNone(ar["deterministic_drift"])

        bmr = result["behavioral_mismatch_risk"]
        self.assertEqual(bmr["level"], "medium")
        self.assertGreaterEqual(bmr["confidence"], 0.6)
        self.assertLess(bmr["confidence"], 0.7)
        self.assertGreater(len(bmr["evidence"]), 0)

    def test_scope_assessment_in_receipt(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("receipt scope test", scope="src")
        intent_id = intent_result["id"]

        result = adapter.build_receipt(session_id=intent_id)
        self.assertNotIn("scope_assessment", result)

        assessment = adapter.run_scope_alignment(session_id=intent_id)
        self.assertEqual(assessment["status"], "ok")
        self.assertIn("alignment_risk", assessment)
        self.assertIn("behavioral_mismatch_risk", assessment)

    def test_scope_assessment_no_scope_unknown(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("no scope declared")
        intent_id = intent_result["id"]

        result = adapter.run_scope_alignment(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["alignment_risk"]["level"], "unknown")
        self.assertEqual(result["alignment_risk"]["confidence"], 0.0)
        self.assertEqual(result["behavioral_mismatch_risk"]["level"], "unknown")
        self.assertEqual(result["behavioral_mismatch_risk"]["confidence"], 0.0)

    def test_zaelith_inference_in_receipt(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("receipt zaelith test", scope="src")
        intent_id = intent_result["id"]

        get_observer().run(["echo", "receipt inference check"], capture_output=True)

        result = adapter.build_receipt(session_id=intent_id)
        self.assertNotIn("zaelith_inference", result)

        inference = adapter.run_zaelith_inference(session_id=intent_id)
        self.assertEqual(inference["status"], "ok")
        inf = inference["inference"]
        self.assertEqual(inf["inference_label"], "inferred")
        if inf["status"] == "available":
            self.assertIsInstance(inf["confidence"], float)
            self.assertGreaterEqual(inf["confidence"], 0.0)
            self.assertLessEqual(inf["confidence"], 1.0)

    def test_integration_full_chain(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        # 1. Intent
        intent_result = adapter.submit_intent(
            "deploy api v2", scope="src/", tool_identity="CleanHouse"
        )
        self.assertEqual(intent_result["status"], "ok")
        intent_id = intent_result["id"]

        # 2. Commands
        get_observer().run(["echo", "build"], capture_output=True)
        get_observer().run(["echo", "test"], capture_output=True)

        # 3. Snapshot + diff with out-of-scope file
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "api.py").write_text("v1")
            (root / "config.json").write_text('{"key": "val"}')
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "api.py").write_text("v2")
            (root / "config.json").write_text('{"key": "val2"}')
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            diff_result = adapter.compute_diff(
                before["id"], after["id"], session_id=intent_id
            )
            self.assertEqual(diff_result["status"], "ok")

        # 4. Network events via stubbed tracer
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

        with patch(
            "backend.api.cleanhouse_monitoring.DataFlowTracer", DataFlowTracerStub
        ):
            network_result = adapter.get_network(refresh=True)
        self.assertEqual(len(network_result["issues"]), 1)
        self.assertGreaterEqual(len(network_result["issues"][0]["evidence_refs"]), 1)

        # 5. Build downstream artifacts
        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")
        self.assertGreaterEqual(timeline["entry_count"], 3)

        correlate_result = adapter.correlate(session_id=intent_id)
        self.assertEqual(correlate_result["status"], "ok")
        self.assertGreaterEqual(correlate_result["edge_count"], 2)

        classify_result = adapter.classify(session_id=intent_id)
        self.assertEqual(classify_result["status"], "ok")

        alert_result = adapter.generate_alerts(session_id=intent_id)
        self.assertEqual(alert_result["status"], "ok")
        self.assertGreaterEqual(alert_result["alert_count"], 1)

        # 6. Receipt
        receipt = adapter.build_receipt(session_id=intent_id)
        self.assertEqual(receipt["status"], "ok")
        self.assertIn("id", receipt)
        self.assertEqual(receipt["session_id"], intent_id)
        self.assertIn("metadata", receipt)
        self.assertIn("summary", receipt)
        self.assertIn("events", receipt)
        self.assertGreaterEqual(len(receipt["events"]), 3)
        self.assertIn("evidence_index", receipt)
        self.assertGreater(len(receipt["evidence_index"]), 0)
        for entry in receipt["evidence_index"]:
            self.assertIn("ref", entry)
            self.assertTrue(
                entry["ref"].startswith("local://cleanhouse/"),
                f"evidence ref {entry['ref']} does not start with local://cleanhouse/",
            )
        self.assertIn("integrity", receipt)
        self.assertIn("root_hash", receipt["integrity"])
        self.assertIn("event_hash_chain", receipt["integrity"])

        # 7. Report
        report = adapter.build_report(
            session_id=intent_id,
            report_type="audit",
            contact="auditor@example.com",
            target="staging-1",
            context="integration test",
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["report_type"], "audit")
        self.assertEqual(report["contact"], "auditor@example.com")
        self.assertEqual(report["target"], "staging-1")
        self.assertEqual(report["context"], "integration test")
        self.assertGreater(len(report["evidence_links"]), 0)
        for link in report["evidence_links"]:
            self.assertTrue(
                link.startswith("local://cleanhouse/"),
                f"evidence link {link} does not start with local://cleanhouse/",
            )
        self.assertIn("receipt", report)
        self.assertIn("integrity", report)

    def test_integration_collector_outage(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("test outage", scope="src/")
        intent_id = intent_result["id"]
        get_observer().run(["echo", "outage-test"], capture_output=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("v1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "test.py").write_text("v2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        class FailingDataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                self.monitor_duration = monitor_duration
            def scan_network_connections(self):
                raise RuntimeError("network scanner not available")
            def scan_dns_queries(self):
                pass

        with patch(
            "backend.api.cleanhouse_monitoring.DataFlowTracer",
            FailingDataFlowTracerStub,
        ):
            network_result = adapter.get_network(refresh=True)
            self.assertEqual(network_result["status"], "critical")
            self.assertEqual(len(network_result["issues"]), 1)
            issue = network_result["issues"][0]
            self.assertEqual(issue["source"], "network")
            self.assertEqual(issue["severity"], "critical")
            self.assertIn("unable to execute", issue["message"])
            self.assertEqual(
                issue["evidence"]["status"], "unable to execute"
            )

            adapter.get_processes = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}
            adapter.get_ai_activity = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}
            adapter.get_anomalies = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}
            adapter.get_integrity = lambda refresh=False: {"status": "safe", "issues": [], "data": {"integrity_scan": {"status": "no_baseline"}}}
            adapter.get_commands = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}
            adapter.get_cloud_usage = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}
            adapter.get_tool_events = lambda refresh=False: {"status": "safe", "issues": [], "data": {}}

            status = adapter.get_status(refresh=True)
        self.assertEqual(status["status"], "critical")
        net_section = status["data"]["sections"]["network"]
        self.assertEqual(
            net_section["event_counts"]["collector_failures"], 1
        )

        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")
        self.assertGreaterEqual(timeline["entry_count"], 3)
        event_types = [e["event_type"] for e in timeline["entries"]]
        self.assertIn("intent", event_types)
        self.assertIn("command", event_types)
        self.assertIn("diff", event_types)

    def test_integration_scope_expansion_alert(self):
        import tempfile
        from pathlib import Path

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        intent_result = adapter.submit_intent("edit code", scope="src/")
        intent_id = intent_result["id"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("v1")
            (root / "config.ini").write_text("setting=1")
            before = adapter.create_snapshot(
                repo_path=str(root), label="before", session_id=intent_id
            )
            (root / "src" / "a.py").write_text("v2")
            (root / "config.ini").write_text("setting=2")
            after = adapter.create_snapshot(
                repo_path=str(root), label="after", session_id=intent_id
            )
            adapter.compute_diff(before["id"], after["id"], session_id=intent_id)

        timeline = adapter.build_timeline(session_id=intent_id)
        self.assertEqual(timeline["status"], "ok")

        corr = adapter.correlate(session_id=intent_id)
        self.assertEqual(corr["status"], "ok")

        signals = adapter.classify(session_id=intent_id)
        self.assertEqual(signals["status"], "ok")

        result = adapter.generate_alerts(session_id=intent_id)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["alert_count"], 1)

        scope_alerts = [
            a for a in result["alerts"] if a["alert_type"] == "scope_expansion"
        ]
        self.assertGreater(len(scope_alerts), 0)
        alert = scope_alerts[0]
        self.assertEqual(alert["alert_type"], "scope_expansion")
        self.assertGreaterEqual(alert["confidence"], 0.0)
        self.assertLessEqual(alert["confidence"], 1.0)
        self.assertGreater(len(alert["evidence_refs"]), 0)
        for ref in alert["evidence_refs"]:
            self.assertIsInstance(ref, str)
            self.assertTrue(
                ref.startswith("local://cleanhouse/"),
                f"evidence ref {ref} does not start with local://cleanhouse/",
            )

    def test_status_full_collector_failure_records_failure_counts(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)

        with patch.object(
            adapter,
            "_collect_processes",
            side_effect=RuntimeError("process collector down"),
        ), patch.object(
            adapter, "_collect_network", side_effect=RuntimeError("network collector down")
        ), patch.object(
            adapter, "_collect_ai_activity", side_effect=RuntimeError("ai activity down")
        ), patch.object(
            adapter, "_collect_anomalies", side_effect=RuntimeError("anomalies down")
        ), patch.object(
            adapter, "_collect_integrity", side_effect=RuntimeError("integrity down")
        ), patch.object(
            adapter, "_collect_commands", side_effect=RuntimeError("commands down")
        ), patch.object(
            adapter, "_collect_cloud_usage", side_effect=RuntimeError("cloud usage down")
        ), patch.object(
            adapter,
            "_collect_tool_events",
            side_effect=RuntimeError("tool events down"),
        ):
            status = adapter.get_status(refresh=True)

        self.assertEqual(status["status"], "critical")
        self.assertEqual(
            status["data"]["sections"]["processes"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["network"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["ai_activity"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["anomalies"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["integrity"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["command"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["cloud_usage"]["event_counts"]["collector_failures"],
            1,
        )
        self.assertEqual(
            status["data"]["sections"]["tool_events"]["event_counts"]["collector_failures"],
            1,
        )

    def test_runtime_gaps_classify_known_collector_failures_without_unknown(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        manifest = {
            "surfaces": {
                "filesystem_watcher": {"collector_status": "dependency_missing"},
                "event_writer": {"collector_status": "inactive"},
                "integrity": {"collector_status": "no_baseline"},
                "network": {"collector_status": "permission_denied"},
                "commands": {"collector_status": "unknown"},
                "processes": {"collector_status": "ok"},
            }
        }

        gaps = adapter._runtime_gaps_from_manifest(manifest)
        by_source = {gap["source"]: gap for gap in gaps}

        self.assertEqual(by_source["filesystem_watcher"]["label"], "unsupported")
        self.assertEqual(by_source["event_writer"]["label"], "partial")
        self.assertEqual(by_source["integrity"]["label"], "partial")
        self.assertEqual(by_source["network"]["label"], "permission_blocked")
        self.assertEqual(by_source["commands"]["label"], "unknown")
        self.assertNotIn("processes", by_source)

    def test_collect_processes_emits_critical_issue_when_memory_budget_exceeded(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                self.show_all = show_all

            def get_processes(self):
                # RSS in KB (as returned by ps on macOS): total 11 GB.
                return [
                    {
                        "pid": "100",
                        "user": "dev",
                        "cpu": 1.0,
                        "mem": 0.5,
                        "rss": str(7 * 1024 * 1024),
                        "command": "codex run",
                    },
                    {
                        "pid": "101",
                        "user": "dev",
                        "cpu": 0.8,
                        "mem": 0.3,
                        "rss": str(4 * 1024 * 1024),
                        "command": "python worker.py",
                    },
                ]

            def identify_platform_detail(self, command):
                return None

            def is_agent_process_detail(self, command):
                return (False, None)

            def is_system_process(self, command, user):
                return False

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.object(monitoring_module, "_get_process_monitor_class", return_value=ProcessMonitorStub):
            payload = adapter.get_processes(refresh=True)
        issues = payload.get("issues", [])
        counts = payload.get("data", {}).get("counts", {})
        budget_issue = next(
            (
                item
                for item in issues
                if "process memory budget exceeded" in str(item.get("message", "")).lower()
            ),
            None,
        )
        self.assertIsNotNone(budget_issue)
        self.assertEqual(budget_issue.get("severity"), "critical")
        self.assertTrue(bool(counts.get("memory_budget_exceeded")))
        self.assertGreater(int(counts.get("over_budget_bytes", 0)), 0)

    def test_collect_processes_does_not_emit_budget_issue_when_under_cap(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                self.show_all = show_all

            def get_processes(self):
                # RSS in KB (as returned by ps on macOS): total 3 GB.
                return [
                    {
                        "pid": "200",
                        "user": "dev",
                        "cpu": 0.4,
                        "mem": 0.2,
                        "rss": str(3 * 1024 * 1024),
                        "command": "python monitor.py",
                    }
                ]

            def identify_platform_detail(self, command):
                return None

            def is_agent_process_detail(self, command):
                return (False, None)

            def is_system_process(self, command, user):
                return False

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.object(monitoring_module, "_get_process_monitor_class", return_value=ProcessMonitorStub):
            payload = adapter.get_processes(refresh=True)
        issues = payload.get("issues", [])
        counts = payload.get("data", {}).get("counts", {})
        budget_issue = next(
            (
                item
                for item in issues
                if "process memory budget exceeded" in str(item.get("message", "")).lower()
            ),
            None,
        )
        self.assertIsNone(budget_issue)
        self.assertFalse(bool(counts.get("memory_budget_exceeded")))
        self.assertEqual(int(counts.get("over_budget_bytes", 0)), 0)

    def test_collect_processes_preserves_quiet_terminal_process(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                self.show_all = show_all

            def get_processes(self):
                busy = [
                    {
                        "pid": str(3000 + index),
                        "user": "dev",
                        "cpu": 200 - index,
                        "mem": 0.1,
                        "rss": "100",
                        "command": f"/usr/bin/busy-{index}",
                    }
                    for index in range(101)
                ]
                busy.append({
                    "pid": "4242",
                    "user": "dev",
                    "cpu": 0.0,
                    "mem": 0.1,
                    "rss": "100",
                    "command": "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
                })
                return busy

            def identify_platform_detail(self, command):
                return None

            def is_agent_process_detail(self, command):
                return (False, None)

            def is_system_process(self, command, user):
                return False

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.object(monitoring_module, "_get_process_monitor_class", return_value=ProcessMonitorStub):
            payload = adapter.get_processes(refresh=True)
        rows = payload.get("data", {}).get("processes", [])
        self.assertGreater(len(rows), 100)
        self.assertTrue(any("Terminal.app" in row.get("command", "") for row in rows))

    def test_operator_session_start_stop_persistence(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        started = adapter.start_operator_session({
            "session_id": "operator-session",
            "objective_id": "objective-operator",
            "summary": "operator session start",
            "metadata": {"surface": "dashboard"},
        })
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["session"]["status"], "active")
        self.assertEqual(started["session"]["objective_id"], "objective-operator")
        self.assertIn("notification", started)

        stored = PersistenceBackend.read("operator_session", started["session"]["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["data"]["session"]["status"], "active")

        stopped = adapter.stop_operator_session({
            "session_id": "operator-session",
            "summary": "operator session stop",
        })
        self.assertEqual(stopped["status"], "ok")
        self.assertEqual(stopped["session"]["status"], "stopped")
        stored_after_stop = PersistenceBackend.read("operator_session", started["session"]["id"])
        self.assertEqual(stored_after_stop["data"]["session"]["status"], "stopped")

    def test_operator_notification_ack_and_local_evidence_requirement(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        no_ref = adapter.create_approval_queue_item({
            "session_id": "notification-no-ref",
            "requested_action": "review without refs",
            "evidence_refs": [],
        })
        self.assertEqual(no_ref["status"], "ok")
        self.assertNotIn("notification", no_ref)
        self.assertEqual(adapter.get_operator_notifications("notification-no-ref")["count"], 0)

        created = adapter.create_approval_queue_item({
            "session_id": "notification-local-ref",
            "requested_action": "review with refs",
            "reason": "local evidence requires review",
            "evidence_refs": ["local://cleanhouse/timeline/tl:notification-local-ref:1"],
        })
        self.assertEqual(created["status"], "ok")
        notification = created["notification"]
        self.assertEqual(notification["notification_type"], "approval_required")
        self.assertFalse(notification["acknowledged"])

        acked = adapter.ack_operator_notification(notification["id"])
        self.assertEqual(acked["status"], "ok")
        self.assertTrue(acked["notification"]["acknowledged"])
        stored = PersistenceBackend.read("operator_notification", notification["id"])
        self.assertTrue(stored["data"]["notification"]["acknowledged"])

    def test_operator_notifications_dedupe_by_type_session_and_evidence_refs(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        refs = [
            "local://cleanhouse/receipt/receipt:dedupe",
            "local://cleanhouse/diff/diff:dedupe",
        ]
        first = adapter.create_approval_queue_item({
            "session_id": "notification-dedupe",
            "requested_action": "review first",
            "reason": "first wording",
            "evidence_refs": refs,
        })
        second = adapter.create_approval_queue_item({
            "session_id": "notification-dedupe",
            "requested_action": "review second",
            "reason": "different wording should not duplicate notification",
            "evidence_refs": list(reversed(refs)),
        })

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(first["notification"]["id"], second["notification"]["id"])
        notifications = adapter.get_operator_notifications("notification-dedupe")
        self.assertEqual(notifications["count"], 1)

    def test_operator_notifications_dedupe_persists_across_timestamp_buckets(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        refs = ["local://cleanhouse/receipt/receipt:dedupe-time"]
        first = adapter._ensure_operator_notification(
            notification_type="approval_required",
            session_id="notification-dedupe-time",
            objective_id=None,
            severity="warning",
            summary="dedupe first",
            evidence_refs=refs,
            source="test",
            metadata={"timestamp": "2026-05-28T12:00:01Z"},
        )
        second = adapter._ensure_operator_notification(
            notification_type="approval_required",
            session_id="notification-dedupe-time",
            objective_id=None,
            severity="warning",
            summary="dedupe second later",
            evidence_refs=refs,
            source="test",
            metadata={"timestamp": "2026-05-28T12:02:35Z"},
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        notifications = adapter.get_operator_notifications("notification-dedupe-time")
        self.assertEqual(notifications["count"], 1)

    def test_notification_system_emits_supported_operator_types(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        emitted_approval = adapter._ensure_operator_notification(
            notification_type="approval_required",
            session_id="essential-types-session",
            objective_id=None,
            severity="warning",
            summary="approval should emit",
            evidence_refs=["local://cleanhouse/test/essential/suppressed"],
            source="test",
        )
        self.assertIsNotNone(emitted_approval)

        emitted = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="essential-types-session",
            objective_id=None,
            severity="warning",
            summary="scope drift should emit",
            evidence_refs=["local://cleanhouse/test/essential/emitted"],
            source="test",
        )
        self.assertIsNotNone(emitted)

    def test_stop_operator_session_emits_session_ended_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        started = adapter.start_operator_session({
            "session_id": "session-ended-notify",
            "objective_id": "objective-session-ended",
            "summary": "session started for ended notification test",
        })
        self.assertEqual(started["status"], "ok")
        stopped = adapter.stop_operator_session({
            "session_id": "session-ended-notify",
            "summary": "session ended for test",
            "finalize": True,
        })
        self.assertEqual(stopped["status"], "ok")
        ended = [item for item in stopped["notifications"] if item.get("notification_type") == "session_ended"]
        self.assertEqual(len(ended), 1)

    def test_operator_notification_creation_for_four_event_types(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="operator workstation fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="operator-four-events",
            objective_id="objective-four-events",
        )
        adapter.start_operator_session({
            "session_id": prompt["session_id"],
            "objective_id": "objective-four-events",
            "summary": "operator session started",
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            substituted_file = substituted / "avatar.png"
            substituted_file.write_text("substituted-v1")
            before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
            substituted_file.write_text("substituted-v2")
            after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
            diff = adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

        adapter.build_timeline(prompt["session_id"])
        adapter.correlate(prompt["session_id"])
        adapter.classify(prompt["session_id"])
        adapter.generate_alerts(prompt["session_id"])
        receipt = adapter.build_receipt(prompt["session_id"])
        adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review traversal",
            "reason": "scope drift requires operator review",
            "evidence_refs": [
                "local://cleanhouse/diff/" + diff["id"],
                "local://cleanhouse/receipt/" + receipt["id"],
            ],
            "metadata": {"receipt_id": receipt["id"]},
        })

        notifications = adapter.get_workstation(prompt["session_id"])["notifications"]
        notification_types = {item["notification_type"] for item in notifications}
        self.assertIn("session_started", notification_types)
        self.assertIn("scope_drift_detected", notification_types)
        self.assertIn("approval_required", notification_types)
        self.assertIn("receipt_finalized", notification_types)
        for notification in notifications:
            self.assertGreater(len(notification["evidence_refs"]), 0)
            for ref in notification["evidence_refs"]:
                self.assertTrue(ref.startswith("local://cleanhouse/"))

    def test_native_operator_notification_allowlist_is_noise_controlled_to_objective_and_drift(self):
        sent = []

        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                sent.append({
                    "title": title,
                    "message": message,
                    "level": level,
                    "metadata": metadata or {},
                    "click_url": click_url,
                })
                return {"status": "delivered", "backend": "fake-native", "timestamp": "2026-05-27T00:00:00"}

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        native_types = {
            "session_started",
            "session_ended",
            "scope_drift_detected",
        }
        non_native_types = {
            "excessive_traversal",
            "codex_prompt_sent",
            "approval_required",
            "destructive_command_attempt",
            "replay_or_signature_failure",
            "runtime_recovery_failure",
            "runtime_state_transition",
            "runtime_connection_lost",
            "runtime_connection_restored",
            "receipt_finalized",
        }
        all_types = native_types | non_native_types
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
                "CLEANHOUSE_NATIVE_DESKTOP_ALLOWLIST_ONLY": "1",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            for notification_type in sorted(all_types):
                metadata = {}
                source = "test"
                if notification_type == "codex_prompt_sent":
                    metadata["prompt_id"] = "prompt:native-allowlist"
                    source = "prompt"
                if notification_type == "scope_drift_detected":
                    metadata["alert_id"] = "alert:native-allowlist"
                created = adapter._ensure_operator_notification(
                    notification_type=notification_type,
                    session_id="native-allowlist",
                    objective_id="objective-native-allowlist",
                    severity="critical" if notification_type in {"scope_drift_detected", "excessive_traversal"} else "info",
                    summary=f"{notification_type} summary",
                    evidence_refs=[f"local://cleanhouse/test/{notification_type}"],
                    source=source,
                    metadata=metadata,
                )
                self.assertIsNotNone(created)

        sent_types = {item["metadata"]["notification_type"] for item in sent}
        self.assertEqual(sent_types, native_types)
        for item in sent:
            self.assertIn("localhost:3333/dashboard", item["click_url"])
            self.assertIn("notification_id=", item["click_url"])
            self.assertIn("session_id=native-allowlist", item["click_url"])

    def test_only_started_completed_and_drift_are_production_operator_dispatch(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        production_types = {
            "session_started",
            "session_ended",
            "scope_drift_detected",
        }
        sample_types = {
            "session_started",
            "session_ended",
            "scope_drift_detected",
            "codex_prompt_sent",
            "approval_required",
            "incident_action_required",
            "receipt_finalized",
        }

        dispatch_by_type = {}
        for notification_type in sorted(sample_types):
            created = adapter._ensure_operator_notification(
                notification_type=notification_type,
                session_id="production-dispatch-contract",
                objective_id="objective-production-dispatch-contract",
                severity="warning" if notification_type == "scope_drift_detected" else "info",
                summary=f"{notification_type} summary",
                evidence_refs=[f"local://cleanhouse/test/{notification_type}"],
                source="test",
                metadata={"event_id": f"event:{notification_type}"},
            )
            self.assertIsNotNone(created)
            dispatch_by_type[notification_type] = created.metadata.get("dispatch_class")

        for notification_type in production_types:
            self.assertEqual(dispatch_by_type.get(notification_type), "production_operator")
        for notification_type in sample_types - production_types:
            self.assertEqual(dispatch_by_type.get(notification_type), "persist_only")

    def test_active_context_attaches_prompt_session_and_survives_restart(self):
        class FakeActiveContextCollector:
            def collect(self, *, follow_enabled, ignored_keys=(), explicit_pickup=None):
                return {
                    "id": "active_context:restart",
                    "dedupe_key": "restart-key",
                    "source_type": "clipboard",
                    "source_labels": ["active_window_observed", "clipboard_observed"],
                    "truth_classification": "observed_context",
                    "frontmost_app": {"app_name": "ChatGPT", "window_title": "CleanHouse"},
                    "current_repo": str(Path.cwd()),
                    "current_objective": "Implement active context",
                    "active_prompt": "Implement active context",
                    "active_prompt_preview": "Implement active context",
                    "last_agent_action": "",
                    "session_id": "active-context-restart",
                    "objective_id": "objective-active-context-restart",
                    "tool_identity": "chatgpt",
                    "context": "clipboard-gated prompt",
                    "source_ref": "",
                    "evidence_refs": ["local://cleanhouse/active-context/active_context:restart"],
                    "metadata": {"active_context_source": "clipboard"},
                    "updated_at": "2026-05-28T12:00:00Z",
                    "attachable": True,
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._active_context_collector = FakeActiveContextCollector()
        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager") as notification_manager:
            result = adapter.set_active_context_follow(True)
            self.assertGreaterEqual(notification_manager.return_value.send_notification.call_count, 1)

        context = result["active_context"]
        self.assertEqual(result["follow_enabled"], True)
        self.assertTrue(context["attached"])
        self.assertTrue(context["prompt_id"].startswith("prompt:"))
        self.assertEqual(context["session_id"], "active-context-restart")
        self.assertEqual(context["session_status"], "active")

        prompt_records = adapter.get_prompts(session_id="active-context-restart")["prompts"]
        self.assertEqual(prompt_records[0]["source"], "active_context")
        self.assertEqual(prompt_records[0]["metadata"]["truth_classification"], "observed_context")

        restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        restarted._active_context_collector = FakeActiveContextCollector()
        restarted_context = restarted.get_active_context(refresh=True)["active_context"]
        self.assertEqual(restarted_context["prompt_id"], context["prompt_id"])
        self.assertEqual(restarted_context["session_id"], "active-context-restart")
        workstation = restarted.get_workstation("active-context-restart")
        self.assertEqual(workstation["active_context"]["active_context"]["id"], "active_context:restart")
        self.assertEqual(
            workstation["operational_presence"]["active_work_context"]["truth_classification"],
            "observed_context",
        )
        provenance = restarted.get_continuity_provenance("active-context-restart")
        self.assertEqual(provenance["continuity_truth"]["label"], "observed_context")
        self.assertIn("active_context", {claim["source_type"] for claim in provenance["claims"]})

    def test_active_context_notification_metadata_and_reconnect_dedupe(self):
        sent = []

        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                sent.append({"metadata": metadata or {}, "click_url": click_url})
                return {"status": "delivered", "backend": "fake-native", "timestamp": "2026-05-28T12:00:00Z"}

        class FakeActiveContextCollector:
            def collect(self, *, follow_enabled, ignored_keys=(), explicit_pickup=None):
                return {
                    "id": "active_context:metadata",
                    "dedupe_key": "metadata-key",
                    "source_type": "codex_artifact",
                    "source_labels": ["codex_session_index_observed", "codex_rollout_observed"],
                    "truth_classification": "observed_context",
                    "frontmost_app": {"app_name": "Codex", "window_title": "CleanHouse"},
                    "current_repo": str(Path.cwd()),
                    "current_objective": "Metadata linked context",
                    "active_prompt": "Metadata linked context",
                    "active_prompt_preview": "Metadata linked context",
                    "last_agent_action": "editing tests",
                    "session_id": "active-context-metadata",
                    "objective_id": "objective-active-context-metadata",
                    "tool_identity": "codex",
                    "context": "codex artifact context",
                    "source_ref": "local://cleanhouse/codex-session/active-context-metadata",
                    "evidence_refs": ["local://cleanhouse/active-context/active_context:metadata"],
                    "metadata": {"active_context_source": "codex_artifact"},
                    "updated_at": "2026-05-28T12:00:00Z",
                    "attachable": True,
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._active_context_collector = FakeActiveContextCollector()
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            active = adapter.get_active_context(refresh=True)["active_context"]
            created = adapter.create_approval_queue_item({
                "session_id": "active-context-metadata",
                "requested_action": "review active context linked approval",
                "reason": "approval-required notification should deep-link to context",
                "evidence_refs": ["local://cleanhouse/test/active-context-approval"],
                "metadata": {"receipt_id": "receipt:active-context"},
            })
            self.assertEqual(created["status"], "ok")
            notification = created["notification"]
            self.assertEqual(notification["metadata"]["active_context_id"], "active_context:metadata")
            self.assertEqual(notification["metadata"]["prompt_id"], active["prompt_id"])
            self.assertEqual(notification["metadata"]["objective_id"], "objective-active-context-metadata")
            self.assertIn("active_context_id=active_context%3Ametadata", notification["metadata"]["click_url"])
            self.assertIn("prompt_id=" + active["prompt_id"].replace(":", "%3A"), notification["metadata"]["click_url"])
            self.assertIn("receipt_id=receipt%3Aactive-context", notification["metadata"]["click_url"])
            self.assertGreaterEqual(len(sent), 1)

            restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            restarted._active_context_collector = FakeActiveContextCollector()
            restarted.get_active_context(refresh=True)
            duplicate = restarted.create_approval_queue_item({
                "session_id": "active-context-metadata",
                "requested_action": "review active context linked approval again",
                "reason": "same evidence should not redispatch",
                "evidence_refs": ["local://cleanhouse/test/active-context-approval"],
                "metadata": {"receipt_id": "receipt:active-context"},
            })
            self.assertEqual(duplicate["notification"]["id"], notification["id"])
            self.assertGreaterEqual(len(sent), 1)

    def test_active_context_reconnect_only_emits_when_agent_action_changes(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        previous_context = {
            "id": "active_context:reconnect-notify",
            "dedupe_key": "reconnect-notify-key",
            "prompt_id": "prompt:reconnect-notify",
            "session_id": "active-context-reconnect-notify",
            "objective_id": "objective-active-context-reconnect-notify",
            "last_agent_action": "editing tests",
        }
        unchanged_context = {
            "id": "active_context:reconnect-notify",
            "dedupe_key": "reconnect-notify-key",
            "session_id": "active-context-reconnect-notify",
            "objective_id": "objective-active-context-reconnect-notify",
            "last_agent_action": "editing tests",
        }
        changed_context = {
            "id": "active_context:reconnect-notify",
            "dedupe_key": "reconnect-notify-key",
            "session_id": "active-context-reconnect-notify",
            "objective_id": "objective-active-context-reconnect-notify",
            "last_agent_action": "running tests",
        }

        with patch.object(adapter, "_emit_codex_active_context_response_notification") as emit_mock:
            attached_unchanged = adapter._attach_active_context(unchanged_context, previous_context)  # noqa: SLF001
            self.assertTrue(attached_unchanged["attached"])
            self.assertEqual(attached_unchanged["prompt_id"], "prompt:reconnect-notify")
            emit_mock.assert_not_called()

            attached_changed = adapter._attach_active_context(changed_context, previous_context)  # noqa: SLF001
            self.assertTrue(attached_changed["attached"])
            self.assertEqual(attached_changed["prompt_id"], "prompt:reconnect-notify")
            emit_mock.assert_called_once()

    def test_notification_manager_returns_bounded_delivery_results(self):
        manager = NotificationManager()
        with patch.object(manager.notification_queue, "put") as put:
            queued = manager.send_notification(
                "Queued",
                "queued message",
                level="warning",
                metadata={"notification_id": "notification:queued", "notification_type": "approval_required"},
                click_url="http://localhost:3333/dashboard",
            )
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["backend"], "notification_queue")
        self.assertEqual(queued["notification_id"], "notification:queued")
        self.assertEqual(manager.get_latest_delivery_result()["status"], "queued")
        put.assert_called_once()

        delivered = {
            "status": "delivered",
            "backend": "fake-native",
            "notification_id": "notification:delivered",
            "timestamp": "2026-05-27T00:00:00",
        }
        with patch.object(manager, "_show_notification", return_value=delivered):
            result = manager.send_notification(
                "Delivered",
                "delivered message",
                metadata={"notification_id": "notification:delivered"},
                wait_for_delivery=True,
            )
        self.assertEqual(result, delivered)
        self.assertEqual(manager.get_latest_delivery_result(), delivered)

    def test_notification_manager_macos_fanout_records_attempts(self):
        manager = NotificationManager()
        with patch("corefiles.notifications.platform.system", return_value="Darwin"):
            with patch("corefiles.notifications.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                with patch("corefiles.notifications.subprocess.run") as run:
                    run.side_effect = [
                        types.SimpleNamespace(returncode=0),
                        types.SimpleNamespace(returncode=0),
                    ]
                    result = manager._show_macos_notification(  # noqa: SLF001
                        "Fanout",
                        "fanout test",
                        level="info",
                        metadata={"notification_id": "notification:fanout", "notification_type": "codex_prompt_sent"},
                        fanout_all_backends=True,
                    )
        self.assertEqual(result["status"], "delivered")
        attempts = result.get("attempts", [])
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["backend"], "terminal-notifier")
        self.assertEqual(attempts[1]["backend"], "osascript")

    def test_native_operator_notification_persists_delivery_result_metadata(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="approval_required",
                session_id="native-delivery-result",
                objective_id="objective-native-delivery",
                severity="warning",
                summary="approval requires native delivery evidence",
                evidence_refs=["local://cleanhouse/test/native-delivery"],
                source="test",
            )

        self.assertIsNotNone(created)
        delivery_result = created.metadata["native_delivery_result"]
        self.assertEqual(delivery_result["status"], "delivered")
        self.assertEqual(delivery_result["backend"], "fake-native")
        self.assertEqual(delivery_result["notification_id"], created.id)
        self.assertEqual(created.metadata["native_delivery"]["status"], "delivered")
        self.assertEqual(created.metadata["native_delivery"]["channel"], "fake-native")
        stored = PersistenceBackend.read("operator_notification", created.id)
        self.assertEqual(
            stored["data"]["notification"]["metadata"]["native_delivery_result"]["status"],
            "delivered",
        )

    def test_native_operator_notification_tracks_visibility_phases_and_ack(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.update_settings({"notification_policy": {"codex_activity_native_enabled": True}})
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id="visibility-phase-session",
                objective_id="objective-visibility-phase",
                severity="info",
                summary="codex prompt visibility phase test",
                evidence_refs=["local://cleanhouse/test/visibility-phase"],
                source="prompt",
                metadata={"prompt_id": "prompt:visibility-phase"},
            )
        self.assertIsNotNone(created)
        phases = created.metadata.get("delivery_phases", {})
        self.assertTrue(phases.get("dispatch_attempted"))
        self.assertTrue(phases.get("backend_accepted"))
        self.assertIn(created.metadata.get("visibility_state"), {"backend_accepted", "visibility_risk"})

        acked = adapter.ack_operator_notification(created.id)
        acked_meta = acked["notification"]["metadata"]
        acked_phases = acked_meta.get("delivery_phases", {})
        self.assertTrue(acked_phases.get("operator_acknowledged"))
        self.assertTrue(acked_phases.get("visibility_confirmed"))
        self.assertEqual(acked_meta.get("visibility_state"), "visibility_confirmed")

    def test_hard_interrupt_bypasses_generic_cooldown_when_allowlisted(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.update_settings({
            "notification_policy": {
                "codex_activity_native_enabled": True,
                "cooldown_bypass_types": ["codex_prompt_sent"],
            }
        })
        FakeNotificationManager.send_calls = 0
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id="cooldown-bypass-session",
                objective_id=None,
                severity="info",
                summary="codex prompt notification",
                evidence_refs=["local://cleanhouse/test/cooldown-bypass"],
                source="test",
                metadata={"prompt_id": "prompt:cooldown-bypass"},
            )
            resent = adapter._dispatch_native_operator_notification(created)  # noqa: SLF001
        self.assertEqual(FakeNotificationManager.send_calls, 2)
        self.assertEqual(resent.metadata.get("native_delivery_result", {}).get("status"), "delivered")

    def test_cooldown_bypass_types_controls_allowlist_behavior(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        FakeNotificationManager.send_calls = 0
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            default_created = adapter._ensure_operator_notification(
                notification_type="approval_required",
                session_id="cooldown-allowlist-default",
                objective_id=None,
                severity="warning",
                summary="cooldown default gate",
                evidence_refs=["local://cleanhouse/test/cooldown/default"],
                source="test",
            )
            default_redispatch = adapter._dispatch_native_operator_notification(default_created)  # noqa: SLF001
            self.assertEqual(default_redispatch.metadata["native_delivery_result"]["status"], "skipped")
            self.assertEqual(default_redispatch.metadata["native_delivery_result"]["reason"], "cooldown_active")
            self.assertEqual(FakeNotificationManager.send_calls, 1)

            adapter.update_settings({"notification_policy": {"cooldown_bypass_types": ["approval_required"]}})
            bypass_created = adapter._ensure_operator_notification(
                notification_type="approval_required",
                session_id="cooldown-allowlist-bypass",
                objective_id=None,
                severity="warning",
                summary="cooldown bypass gate",
                evidence_refs=["local://cleanhouse/test/cooldown/bypass"],
                source="test",
            )
            bypass_redispatch = adapter._dispatch_native_operator_notification(bypass_created)  # noqa: SLF001
            self.assertEqual(bypass_redispatch.metadata["native_delivery_result"]["status"], "delivered")
            self.assertEqual(FakeNotificationManager.send_calls, 3)

    def test_non_hard_interrupt_respects_burst_cap(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.update_settings({"notification_policy": {"burst_cap": 1, "burst_window_seconds": 60}})
        FakeNotificationManager.send_calls = 0
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            first = adapter._ensure_operator_notification(
                notification_type="approval_required",
                session_id="burst-cap-session",
                objective_id=None,
                severity="warning",
                summary="approval notification one",
                evidence_refs=["local://cleanhouse/test/burst-cap/1"],
                source="test",
                metadata={"timestamp": "2026-05-27T00:00:01"},
            )
            second = adapter._ensure_operator_notification(
                notification_type="approval_required",
                session_id="burst-cap-session",
                objective_id=None,
                severity="warning",
                summary="approval notification two",
                evidence_refs=["local://cleanhouse/test/burst-cap/2"],
                source="test",
                metadata={"timestamp": "2026-05-27T00:00:02"},
            )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(FakeNotificationManager.send_calls, 1)
        self.assertEqual(first.metadata["native_delivery_result"]["status"], "delivered")
        self.assertEqual(second.metadata["native_delivery_result"]["status"], "skipped")
        self.assertEqual(second.metadata["native_delivery_result"]["reason"], "burst_cap_active")

    def test_hard_interrupt_reminder_cycle_redispatches_until_ack(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.update_settings({
            "notification_policy": {
                "hard_interrupt_reminder_seconds": 15,
                "codex_activity_native_enabled": True,
                "cooldown_bypass_types": ["codex_prompt_sent"],
            }
        })
        FakeNotificationManager.send_calls = 0
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id="reminder-cycle-session",
                objective_id=None,
                severity="info",
                summary="reminder cycle test",
                evidence_refs=["local://cleanhouse/test/reminder-cycle"],
                source="test",
                metadata={"prompt_id": "prompt:reminder-cycle"},
            )
            metadata = dict(created.metadata)
            visibility = dict(metadata.get("visibility", {}))
            visibility["next_reminder_at"] = "2000-01-01T00:00:00"
            metadata["visibility"] = visibility
            stale = monitoring_module.OperatorNotificationRecord(
                id=created.id,
                notification_type=created.notification_type,
                session_id=created.session_id,
                objective_id=created.objective_id,
                severity=created.severity,
                summary=created.summary,
                evidence_refs=created.evidence_refs,
                created_at=created.created_at,
                acknowledged=created.acknowledged,
                acknowledged_at=created.acknowledged_at,
                source=created.source,
                metadata=metadata,
            )
            adapter._operator_notifications[stale.id] = stale  # noqa: SLF001
            adapter._run_notification_visibility_cycle()  # noqa: SLF001
        refreshed = adapter.get_operator_notifications("reminder-cycle-session")["notifications"][0]
        self.assertGreaterEqual(FakeNotificationManager.send_calls, 2)
        self.assertGreaterEqual(refreshed["metadata"]["visibility"].get("reminder_count", 0), 1)

    def test_reminder_cycle_suppresses_after_max_native_reminders(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter.update_settings({
            "notification_policy": {
                "hard_interrupt_reminder_seconds": 15,
                "max_native_reminders_per_notification": 1,
                "codex_activity_native_enabled": True,
                "cooldown_bypass_types": ["codex_prompt_sent"],
            }
        })
        FakeNotificationManager.send_calls = 0
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id="reminder-suppressed-session",
                objective_id=None,
                severity="info",
                summary="reminder suppression test",
                evidence_refs=["local://cleanhouse/test/reminder-suppressed"],
                source="test",
                metadata={"prompt_id": "prompt:reminder-suppressed"},
            )
            metadata = dict(created.metadata)
            visibility = dict(metadata.get("visibility", {}))
            visibility["next_reminder_at"] = "2000-01-01T00:00:00"
            metadata["visibility"] = visibility
            due = monitoring_module.OperatorNotificationRecord(
                id=created.id,
                notification_type=created.notification_type,
                session_id=created.session_id,
                objective_id=created.objective_id,
                severity=created.severity,
                summary=created.summary,
                evidence_refs=created.evidence_refs,
                created_at=created.created_at,
                acknowledged=created.acknowledged,
                acknowledged_at=created.acknowledged_at,
                source=created.source,
                metadata=metadata,
            )
            adapter._operator_notifications[due.id] = due  # noqa: SLF001
            adapter._run_notification_visibility_cycle()  # noqa: SLF001
            self.assertEqual(FakeNotificationManager.send_calls, 2)

            first_pass = adapter.get_operator_notifications("reminder-suppressed-session")["notifications"][0]
            metadata2 = dict(first_pass["metadata"])
            visibility2 = dict(metadata2.get("visibility", {}))
            visibility2["next_reminder_at"] = "2000-01-01T00:00:00"
            metadata2["visibility"] = visibility2
            due_again = monitoring_module.OperatorNotificationRecord(
                id=first_pass["id"],
                notification_type=first_pass["notification_type"],
                session_id=first_pass["session_id"],
                objective_id=first_pass.get("objective_id"),
                severity=first_pass["severity"],
                summary=first_pass["summary"],
                evidence_refs=tuple(first_pass["evidence_refs"]),
                created_at=first_pass["created_at"],
                acknowledged=first_pass["acknowledged"],
                acknowledged_at=first_pass.get("acknowledged_at"),
                source=first_pass["source"],
                metadata=metadata2,
            )
            adapter._operator_notifications[due_again.id] = due_again  # noqa: SLF001
            adapter._run_notification_visibility_cycle()  # noqa: SLF001

        suppressed = adapter.get_operator_notifications("reminder-suppressed-session")["notifications"][0]
        visibility = suppressed["metadata"]["visibility"]
        self.assertEqual(FakeNotificationManager.send_calls, 2)
        self.assertTrue(visibility.get("reminder_suppressed"))
        self.assertEqual(visibility.get("suppressed_reason"), "max_native_reminders_reached")

    def test_native_operator_notification_failure_creates_runtime_recovery_artifact(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                return {
                    "status": "failed",
                    "backend": "fake-native",
                    "reason": "fixture delivery failure",
                    "notification_id": metadata["notification_id"],
                    "timestamp": "2026-05-27T00:00:00",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_REMINDERS": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="runtime_recovery_failure",
                session_id="native-delivery-failure",
                objective_id="objective-native-failure",
                severity="critical",
                summary="runtime recovery failure requires native delivery evidence",
                evidence_refs=["local://cleanhouse/runtime/recovery-failure"],
                source="test",
            )

        self.assertIsNotNone(created)
        delivery_result = created.metadata["native_delivery_result"]
        self.assertEqual(delivery_result["status"], "failed")
        self.assertEqual(delivery_result["reason"], "fixture delivery failure")
        self.assertIn("runtime_recovery_artifact_id", delivery_result)
        self.assertIn("runtime_recovery_evidence_ref", delivery_result)

        artifact = PersistenceBackend.read("runtime_recovery", delivery_result["runtime_recovery_artifact_id"])
        self.assertIsNotNone(artifact)
        recovery = artifact["data"]
        self.assertEqual(recovery["failure_type"], "native_notification_delivery")
        self.assertEqual(recovery["action"], "native_notification_delivery")
        self.assertEqual(recovery["notification_id"], created.id)
        self.assertEqual(recovery["delivery_result"]["status"], "failed")
        self.assertEqual(recovery["final_state"]["status"], "failed")
        self.assertIn("local://cleanhouse/operator_notification/" + created.id, recovery["evidence_refs"])

    def test_operator_notification_preserves_unknown_persisted_type(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        notification_id = "notification:unknown-type"
        PersistenceBackend.persist("operator_notification", notification_id, {
            "status": "ok",
            "notification": {
                "id": notification_id,
                "notification_type": "future_notification_type",
                "session_id": "unknown-notification-session",
                "objective_id": None,
                "severity": "warning",
                "summary": "future notification",
                "evidence_refs": ["local://cleanhouse/test/future-notification"],
                "created_at": "2026-05-27T00:00:00",
                "acknowledged": False,
                "acknowledged_at": None,
                "source": "test",
                "metadata": {},
            },
        })

        restored = adapter._operator_notification_record(notification_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.notification_type, "future_notification_type")

    def test_destructive_command_attempt_notification_dedupes(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = monitoring_module.CommandResult(
            command="rm",
            args=("rm", "-rf", "build-output"),
            cwd="/tmp",
            user="dev",
            returncode=1,
            duration=0.01,
            timestamp="2026-05-27T00:00:00",
            stdout_preview="",
            stderr_preview="blocked",
            session_id="destructive-session",
            objective_id="objective-destructive",
            child_pid=123,
        )

        adapter._on_command_completed(result)
        adapter._on_command_completed(result)

        notifications = adapter.get_operator_notifications("destructive-session")["notifications"]
        destructive = [item for item in notifications if item["notification_type"] == "destructive_command_attempt"]
        self.assertEqual(len(destructive), 1)
        self.assertEqual(destructive[0]["severity"], "critical")
        self.assertTrue(all(ref.startswith("local://cleanhouse/") for ref in destructive[0]["evidence_refs"]))
        restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        restored_types = {
            item["notification_type"]
            for item in restarted.get_operator_notifications("destructive-session")["notifications"]
        }
        self.assertIn("destructive_command_attempt", restored_types)

    def test_runtime_transition_notification_dedupes_and_uses_runtime_focus(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        healthy = {
            "status": "healthy",
            "runtime_state": "healthy",
            "reason_codes": [],
            "blocked_recovery": {},
            "recovery_receipts": [],
            "notifications": {"status": "ok", "failure_count": 0},
            "report_executor": {"status": "ok"},
        }
        degraded = {
            "status": "degraded",
            "runtime_state": "degraded",
            "reason_codes": ["readiness_probe_failed"],
            "blocked_recovery": {"type": "readiness_probe_failed", "reason": "probe failed", "receipt_id": "runtime_recovery:abc"},
            "recovery_receipts": [{"id": "runtime_recovery:abc", "action": "backend_restart_blocked", "timestamp": "2026-05-27T00:00:00", "final_state": {"runtime_state": "degraded"}, "integrity": {}}],
            "notifications": {"status": "ok", "failure_count": 0},
            "report_executor": {"status": "ok"},
        }

        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}):
            with patch("backend.runtime_supervisor.current_runtime_payload", side_effect=[healthy, degraded, degraded]):
                first = adapter.get_runtime()
                second = adapter.get_runtime()
                third = adapter.get_runtime()

        self.assertEqual(first["runtime_state"], "healthy")
        self.assertEqual(second["runtime_state"], "degraded")
        runtime_notifications = adapter.get_operator_notifications("runtime-global")["notifications"]
        transitions = [item for item in runtime_notifications if item["notification_type"] == "runtime_state_transition"]
        self.assertEqual(len(transitions), 1)
        self.assertTrue(transitions[0]["incident_key"])
        self.assertEqual(transitions[0]["visibility_proof"], "transport_only")
        self.assertIn("runtime_focus=1", transitions[0]["metadata"]["click_url"])
        self.assertNotIn("session_id=", transitions[0]["metadata"]["click_url"])
        self.assertEqual(third["runtime_notifications"][0]["notification_type"], "runtime_state_transition")

    def test_runtime_payload_exposes_operator_ready_and_visibility_summary(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        healthy = {
            "status": "healthy",
            "runtime_state": "healthy",
            "reason_codes": [],
            "operator_ready": True,
            "blocked_recovery": {},
            "recovery_receipts": [],
            "notifications": {"status": "ok", "failure_count": 0},
            "report_executor": {"status": "ok"},
        }
        with patch("backend.runtime_supervisor.current_runtime_payload", return_value=healthy):
            runtime = adapter.get_runtime()
        self.assertTrue(runtime["operator_ready"])
        self.assertIn("visibility_proof_summary", runtime)
        self.assertIn("transport_only", runtime["visibility_proof_summary"])
        self.assertIn("operator_confirmed", runtime["visibility_proof_summary"])

    def test_runtime_restoration_notification_survives_restart(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        degraded = {
            "status": "degraded",
            "runtime_state": "degraded",
            "reason_codes": ["readiness_probe_failed"],
            "blocked_recovery": {},
            "recovery_receipts": [],
            "notifications": {"status": "ok", "failure_count": 0},
            "report_executor": {"status": "ok"},
        }
        healthy = {
            "status": "healthy",
            "runtime_state": "healthy",
            "reason_codes": [],
            "blocked_recovery": {},
            "recovery_receipts": [],
            "notifications": {"status": "ok", "failure_count": 0},
            "report_executor": {"status": "ok"},
        }
        with patch("backend.runtime_supervisor.current_runtime_payload", side_effect=[degraded, healthy]):
            adapter.get_runtime()
            adapter.get_runtime()

        restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        notifications = restarted.get_operator_notifications("runtime-global")["notifications"]
        restored = [item for item in notifications if item["notification_type"] == "runtime_connection_restored"]
        self.assertEqual(len(restored), 1)
        self.assertTrue(all(ref.startswith("local://cleanhouse/") for ref in restored[0]["evidence_refs"]))

    def test_excessive_traversal_notification_is_distinct_from_scope_drift(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Traverse only requested avatar path",
            context="excessive traversal notification fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="excessive-traversal-session",
            objective_id="objective-excessive-traversal",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            changed = substituted / "avatar.png"
            changed.write_text("substituted-v1")
            before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
            changed.write_text("substituted-v2")
            after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
            adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

        adapter.build_timeline(prompt["session_id"])
        adapter.correlate(prompt["session_id"])
        adapter.classify(prompt["session_id"])
        adapter.generate_alerts(prompt["session_id"])
        workstation = adapter.get_workstation(prompt["session_id"])
        notification_types = {item["notification_type"] for item in workstation["notifications"]}
        self.assertIn("scope_drift_detected", notification_types)
        self.assertIn("excessive_traversal", notification_types)
        traversal = [item for item in workstation["notifications"] if item["notification_type"] == "excessive_traversal"]
        self.assertEqual(len(traversal), 1)
        self.assertEqual(traversal[0]["severity"], "critical")
        self.assertEqual(traversal[0]["metadata"]["scope_relation"], "outside_declared_scope")

    def test_scope_drift_incident_key_reuses_same_evidence_refs(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        refs = [
            "local://cleanhouse/receipt/receipt:scope-drift",
            "local://cleanhouse/diff/diff:scope-drift",
        ]
        first_key = adapter._notification_incident_key(  # noqa: SLF001
            notification_type="scope_drift_detected",
            session_id="scope-drift-key-session",
            evidence_refs=refs,
            metadata={"timestamp": "2026-05-28T12:00:00Z"},
        )
        second_key = adapter._notification_incident_key(  # noqa: SLF001
            notification_type="scope_drift_detected",
            session_id="scope-drift-key-session",
            evidence_refs=list(reversed(refs)),
            metadata={"timestamp": "2026-05-28T12:00:00Z"},
        )
        self.assertEqual(first_key, second_key)

        first = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="scope-drift-key-session",
            objective_id=None,
            severity="critical",
            summary="scope drift first",
            evidence_refs=refs,
            source="test",
        )
        second = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="scope-drift-key-session",
            objective_id=None,
            severity="critical",
            summary="scope drift second",
            evidence_refs=list(reversed(refs)),
            source="test",
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)

    def test_scope_drift_dedupe_across_emit_paths_with_same_evidence_refs(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        refs = [
            "local://cleanhouse/receipt/receipt:scope-drift-emit-path",
            "local://cleanhouse/diff/diff:scope-drift-emit-path",
        ]
        first = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="scope-drift-emit-path-session",
            objective_id="objective-scope-drift-emit-path",
            severity="warning",
            summary="scope drift from workstation path",
            evidence_refs=refs,
            source="workstation",
            metadata={"receipt_id": "receipt:scope-drift-emit-path"},
        )
        second = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="scope-drift-emit-path-session",
            objective_id="objective-scope-drift-emit-path",
            severity="warning",
            summary="scope drift from alert path",
            evidence_refs=list(reversed(refs)),
            source="alert",
            metadata={"alert_id": "alert:scope-drift-emit-path"},
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, second.id)
        notifications = adapter.get_operator_notifications("scope-drift-emit-path-session")
        scoped = [item for item in notifications["notifications"] if item.get("notification_type") == "scope_drift_detected"]
        self.assertEqual(len(scoped), 1)

    def test_continuity_degraded_notification_has_local_evidence(self):
        with patch.dict(os.environ, {"CLEANHOUSE_CONTINUITY_PICKUP_FAILURE": "pickup_runtime_failure"}):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            adapter.start_operator_session({
                "session_id": "continuity-degraded-session",
                "objective_id": "objective-continuity-degraded",
                "summary": "continuity degraded session",
            })

            workstation = adapter.get_workstation("continuity-degraded-session")

        notifications = workstation["notifications"]
        degraded = [item for item in notifications if item["notification_type"] == "continuity_degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertGreater(len(degraded[0]["evidence_refs"]), 0)
        self.assertTrue(all(ref.startswith("local://cleanhouse/") for ref in degraded[0]["evidence_refs"]))

    def test_continuity_degraded_native_delivery_metadata(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T00:00:00",
                }

        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_CONTINUITY_PICKUP_FAILURE": "pickup_runtime_failure",
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            adapter.start_operator_session({
                "session_id": "continuity-native-session",
                "objective_id": "objective-continuity-native",
                "summary": "continuity native delivery session",
            })
            workstation = adapter.get_workstation("continuity-native-session")

        notifications = workstation["notifications"]
        degraded = [item for item in notifications if item["notification_type"] == "continuity_degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertEqual(degraded[0]["metadata"]["native_delivery_result"]["status"], "delivered")
        self.assertEqual(degraded[0]["metadata"]["native_delivery_result"]["backend"], "fake-native")

    def test_collector_failure_notifications_use_hard_interrupt_delivery(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T00:00:00",
                }

        FakeNotificationManager.send_calls = 0
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            first = adapter._ensure_operator_notification(
                notification_type="collector_failure",
                session_id="runtime-global",
                objective_id=None,
                severity="critical",
                summary="collector failure: filesystem_watcher status=failure",
                evidence_refs=["local://cleanhouse/collector/filesystem_watcher/failure/a"],
                source="test",
                metadata={"collector_name": "filesystem_watcher", "collector_status": "failure"},
            )
            second = adapter._ensure_operator_notification(
                notification_type="collector_failure",
                session_id="runtime-global",
                objective_id=None,
                severity="critical",
                summary="collector failure: filesystem_watcher status=failure",
                evidence_refs=["local://cleanhouse/collector/filesystem_watcher/failure/b"],
                source="test",
                metadata={"collector_name": "filesystem_watcher", "collector_status": "failure"},
            )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.metadata["native_delivery_result"]["status"], "delivered")
        self.assertEqual(second.metadata["native_delivery_result"]["status"], "skipped")
        self.assertEqual(second.metadata["native_delivery_result"].get("reason"), "cooldown_active")
        self.assertEqual(FakeNotificationManager.send_calls, 1)

    def test_hard_interrupt_delivery_persists_across_restart(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T00:00:00",
                }

        FakeNotificationManager.send_calls = 0
        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            adapter.update_settings({"notification_policy": {"cooldown_bypass_types": ["collector_failure"]}})
            first = adapter._ensure_operator_notification(
                notification_type="collector_failure",
                session_id="runtime-global",
                objective_id=None,
                severity="critical",
                summary="collector failure: runtime_event_writer status=failure",
                evidence_refs=["local://cleanhouse/collector/runtime_event_writer/failure/1"],
                source="test",
                metadata={"collector_name": "runtime_event_writer", "collector_status": "failure"},
            )
            restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            restarted.update_settings({"notification_policy": {"cooldown_bypass_types": ["collector_failure"]}})
            second = restarted._ensure_operator_notification(
                notification_type="collector_failure",
                session_id="runtime-global",
                objective_id=None,
                severity="critical",
                summary="collector failure: runtime_event_writer status=failure",
                evidence_refs=["local://cleanhouse/collector/runtime_event_writer/failure/2"],
                source="test",
                metadata={"collector_name": "runtime_event_writer", "collector_status": "failure"},
            )

        self.assertEqual(first.metadata["native_delivery_result"]["status"], "delivered")
        self.assertEqual(second.metadata["native_delivery_result"]["status"], "delivered")
        self.assertEqual(FakeNotificationManager.send_calls, 2)

    def test_critical_filesystem_mutation_notification_for_out_of_scope_delete(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T00:00:00",
                }

        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            prompt = adapter.submit_prompt(
                text="Only mutate requested avatar scope",
                context="critical filesystem mutation fixture",
                scope="assets/avatars/requested/",
                tool_identity="Codex",
                session_id="critical-mutation-session",
                objective_id="objective-critical-mutation",
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                requested = root / "assets" / "avatars" / "requested"
                substituted = root / "assets" / "avatars" / "substituted"
                requested.mkdir(parents=True)
                substituted.mkdir(parents=True)
                (requested / "avatar.png").write_text("requested-v1")
                deleted_target = substituted / "avatar.png"
                deleted_target.write_text("substituted-v1")
                before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
                deleted_target.unlink()
                after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
                adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])
            adapter.build_timeline(prompt["session_id"])
            adapter.correlate(prompt["session_id"])
            adapter.classify(prompt["session_id"])
            adapter.generate_alerts(prompt["session_id"])
            workstation = adapter.get_workstation(prompt["session_id"])

        notifications = workstation["notifications"]
        critical = [item for item in notifications if item["notification_type"] == "critical_filesystem_mutation"]
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0]["severity"], "critical")
        self.assertIn(critical[0]["metadata"]["scope_relation"], {"out_of_scope", "unknown"})
        self.assertEqual(critical[0]["metadata"]["mutation_change_type"], "deleted")
        self.assertEqual(critical[0]["metadata"]["native_delivery_result"]["status"], "delivered")

    def test_rollback_needed_notification_when_scope_policy_requires_review(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T00:00:00",
                }

        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            prompt = adapter.submit_prompt(
                text="Mutate only requested avatar scope",
                context="rollback needed fixture",
                scope="assets/avatars/requested/",
                tool_identity="Codex",
                session_id="rollback-needed-session",
                objective_id="objective-rollback-needed",
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                requested = root / "assets" / "avatars" / "requested"
                substituted = root / "assets" / "avatars" / "substituted"
                requested.mkdir(parents=True)
                substituted.mkdir(parents=True)
                (requested / "avatar.png").write_text("requested-v1")
                changed = substituted / "avatar.png"
                changed.write_text("substituted-v1")
                before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
                changed.write_text("substituted-v2")
                after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
                adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

            adapter.build_timeline(prompt["session_id"])
            adapter.correlate(prompt["session_id"])
            adapter.classify(prompt["session_id"])
            adapter.generate_alerts(prompt["session_id"])
            receipt = adapter.build_receipt(prompt["session_id"])
            notifications = adapter.get_operator_notifications(prompt["session_id"])["notifications"]

        self.assertEqual(receipt["status"], "ok")
        rollback_needed = [item for item in notifications if item["notification_type"] == "rollback_needed"]
        self.assertEqual(len(rollback_needed), 1)
        self.assertEqual(rollback_needed[0]["metadata"]["receipt_id"], receipt["id"])
        self.assertNotEqual(rollback_needed[0]["metadata"]["rollback_status"], "executed_verified")

    def test_scope_enforcement_generates_mediation_events_and_deviation_records(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Mutate only requested avatar scope",
            context="scope enforcement fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="scope-enforcement-session",
            objective_id="objective-scope-enforcement",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            changed = substituted / "avatar.png"
            changed.write_text("substituted-v1")
            before = adapter.create_snapshot(str(root), "before-scope-enforcement", session_id=prompt["session_id"])
            changed.write_text("substituted-v2")
            after = adapter.create_snapshot(str(root), "after-scope-enforcement", session_id=prompt["session_id"])
            adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

        receipt = adapter.build_receipt(prompt["session_id"])
        self.assertEqual(receipt["status"], "ok")
        self.assertIn("scope_enforcement", receipt)
        enforcement = receipt["scope_enforcement"]
        self.assertEqual(enforcement["policy_id"], "scope_enforcement_v1")
        self.assertEqual(enforcement["enforcement_status"], "blocked_pending_approval")
        self.assertGreaterEqual(len(enforcement["deviation_records"]), 3)
        boundary_status = {entry["boundary"]: entry["status"] for entry in enforcement["boundaries"]}
        self.assertEqual(boundary_status["declared_objective"], "exceeded")
        self.assertEqual(boundary_status["approved_scope"], "exceeded")
        self.assertEqual(boundary_status["authorization_boundary"], "exceeded")
        self.assertGreaterEqual(len(enforcement["mediation_events"]), 1)
        self.assertEqual(enforcement["mediation_events"][0]["event_type"], "scope_enforcement_mediation")
        self.assertTrue(enforcement["mediation_events"][0]["event_ref"].startswith("local://cleanhouse/scope-enforcement/"))
        for deviation in enforcement["deviation_records"]:
            self.assertEqual(deviation["record_type"], "scope_boundary_exceeded")
            self.assertTrue(deviation["enforceable"])
            self.assertTrue(any(ref.startswith("local://cleanhouse/") for ref in deviation["evidence_refs"]))
        self.assertIn("approval_policy", receipt)
        self.assertEqual(receipt["approval_policy"]["policy_id"], "scope_out_of_scope_v1")

        approvals = adapter.get_approval_queue(session_id=prompt["session_id"])
        self.assertEqual(approvals["count"], 1)
        approval = approvals["approval_queue"][0]
        self.assertTrue(approval["metadata"]["enforcement_required"])
        self.assertEqual(approval["metadata"]["enforcement_action"], "block_scope_expansion_until_review")
        self.assertEqual(approval["metadata"]["boundary_type"], "scope_authorization")

        timeline = adapter.get_timelines(session_id=prompt["session_id"])
        entries = timeline["timelines"][0]["entries"] if timeline["timelines"] else []
        enforcement_events = [entry for entry in entries if entry.get("event_type") == "scope_enforcement_mediation"]
        self.assertGreaterEqual(len(enforcement_events), 1)

        replay = adapter.replay_receipt_state(receipt["id"])
        self.assertEqual(replay["status"], "ok")
        self.assertIn("scope_enforcement", replay)
        self.assertEqual(
            len(replay["scope_enforcement"]["deviation_records"]),
            len(enforcement["deviation_records"]),
        )

        exported = adapter.export_receipt_timeline_bundle(receipt["id"])
        self.assertEqual(exported["status"], "ok")
        self.assertIn("scope_enforcement", exported["bundle"]["receipt"])
        self.assertEqual(
            len(exported["bundle"]["receipt"]["scope_enforcement"]["deviation_records"]),
            len(enforcement["deviation_records"]),
        )

    def test_replay_or_signature_failure_notification_from_tampered_bundle(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="bundle tamper fixture",
            context="receipt replay signature failure",
            scope="src/",
            tool_identity="Codex",
            session_id="bundle-failure-session",
            objective_id="objective-bundle-failure",
        )
        adapter.build_timeline(prompt["session_id"])
        receipt = adapter.build_receipt(prompt["session_id"])
        exported = adapter.export_receipt_timeline_bundle(receipt["id"])
        tampered = json.loads(json.dumps(exported["bundle"]))
        tampered["integrity"]["bundle_hash"] = "tampered"

        verified = adapter.verify_receipt_timeline_bundle(tampered)

        self.assertEqual(verified["status"], "failed")
        notifications = adapter.get_operator_notifications(prompt["session_id"])["notifications"]
        failures = [item for item in notifications if item["notification_type"] == "replay_or_signature_failure"]
        self.assertEqual(len(failures), 1)
        self.assertTrue(all(ref.startswith("local://cleanhouse/") for ref in failures[0]["evidence_refs"]))

    def test_runtime_recovery_failure_notification_from_failed_rollback(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        session_id = "rollback-failure-session"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "file.txt"
            target.write_text("v1")
            before = adapter.create_snapshot(str(root), "before-rollback-failure", session_id=session_id)
            target.write_text("v2")
            rollback = adapter.request_rollback({
                "session_id": session_id,
                "objective_id": "objective-rollback-failure",
                "path": "file.txt",
                "snapshot_id": before["id"],
                "repo_path": str(root),
                "evidence_refs": ["local://cleanhouse/diff/diff:rollback-failure"],
            })
            with adapter._lock:
                adapter._snapshot_contents[before["id"]]["file.txt"] = base64.b64encode(b"wrong-target").decode("ascii")
            executed = adapter.execute_rollback({
                "rollback_id": rollback["rollback"]["id"],
                "repo_path": str(root),
            })

        self.assertEqual(executed["rollback"]["status"], "executed_verification_failed")
        notifications = adapter.get_operator_notifications(session_id)["notifications"]
        failures = [item for item in notifications if item["notification_type"] == "runtime_recovery_failure"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["severity"], "critical")
        self.assertTrue(all(ref.startswith("local://cleanhouse/") for ref in failures[0]["evidence_refs"]))

    def test_workstation_aggregate_includes_evidence_spine(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="workstation aggregate fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="workstation-aggregate",
            objective_id="objective-workstation",
        )
        adapter.start_operator_session({
            "session_id": prompt["session_id"],
            "objective_id": "objective-workstation",
            "summary": "operator aggregate session",
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            substituted_file = substituted / "avatar.png"
            substituted_file.write_text("substituted-v1")
            before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
            substituted_file.write_text("substituted-v2")
            after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
            diff = adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

        adapter.build_timeline(prompt["session_id"])
        adapter.correlate(prompt["session_id"])
        adapter.classify(prompt["session_id"])
        receipt = adapter.build_receipt(prompt["session_id"])
        approval = adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review receipt traversal",
            "reason": "receipt flagged out-of-scope traversal",
            "evidence_refs": [
                "local://cleanhouse/receipt/" + receipt["id"],
                "local://cleanhouse/diff/" + diff["id"],
            ],
            "prompt_id": prompt["id"],
            "objective_id": "objective-workstation",
            "metadata": {"receipt_id": receipt["id"]},
        })
        self.assertEqual(approval["status"], "ok")

        workstation = adapter.get_workstation(prompt["session_id"])
        self.assertEqual(workstation["status"], "ok")
        self.assertEqual(workstation["session"]["status"], "active")
        self.assertEqual(workstation["operational_presence"]["state"], "attention_required")
        self.assertFalse(workstation["operational_presence"]["quiet"])
        self.assertGreaterEqual(workstation["operational_presence"]["open_counts"]["pending_approvals"], 1)
        self.assertGreater(len(workstation["operational_presence"]["evidence_refs"]), 0)
        primary = workstation["operational_presence"]["primary_intervention"]
        self.assertEqual(primary["type"], "approval")
        self.assertEqual(primary["approval_id"], approval["approval"]["id"])
        self.assertEqual(primary["receipt_id"], receipt["id"])
        self.assertGreater(len(primary["evidence_refs"]), 0)
        self.assertIn("Stabilize CleanHouse session", primary["draft_correction_prompt"])
        self.assertGreaterEqual(len(workstation["objectives"]), 1)
        self.assertGreaterEqual(len(workstation["timeline"]["entries"]), 1)
        self.assertGreaterEqual(len(workstation["mutations"]), 1)
        self.assertGreaterEqual(len(workstation["receipts"]), 1)
        self.assertGreaterEqual(len(workstation["approvals"]), 1)
        self.assertIn(receipt["id"], workstation["receipt_replays"])
        self.assertGreaterEqual(len(workstation["notifications"]), 1)
        drift_summaries = [
            item for item in workstation["evidence_summaries"]
            if item["summary_type"] == "scope_drift"
        ]
        self.assertGreaterEqual(len(drift_summaries), 1)
        self.assertEqual(drift_summaries[0]["scope_weight"], 1.0)
        self.assertGreater(len(drift_summaries[0]["evidence_refs"]), 0)

    def test_stabilization_prompt_persists_intervention_metadata_and_local_refs(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_prompt(
            text="Re-check scope before continuing",
            context="operator stabilization",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="stabilize-session",
            objective_id="objective-stabilize",
            prompt_type="stabilization",
            parent_intervention_id="approval:needs-review",
            evidence_refs=[
                "local://cleanhouse/receipt/receipt:stabilize",
                "https://example.invalid/not-local",
                "local://cleanhouse/diff/diff:stabilize",
            ],
            metadata={"source": "operational_presence", "approval_id": "approval:needs-review"},
        )
        self.assertEqual(result["status"], "ok")

        prompts = adapter.get_prompts(session_id="stabilize-session")
        self.assertEqual(prompts["count"], 1)
        prompt = prompts["prompts"][0]
        self.assertEqual(prompt["prompt_type"], "stabilization")
        self.assertEqual(prompt["parent_intervention_id"], "approval:needs-review")
        self.assertEqual(prompt["metadata"]["source"], "operational_presence")
        self.assertEqual(prompt["evidence_refs"], [
            "local://cleanhouse/receipt/receipt:stabilize",
            "local://cleanhouse/diff/diff:stabilize",
        ])

    def test_workstation_includes_continuity_provenance_with_classified_claims(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Recover the operator continuity provenance panel",
            context="thread context recovered by current session",
            scope="frontend/",
            tool_identity="Codex",
            session_id="continuity-workstation",
            objective_id="objective-continuity",
            evidence_refs=[
                "local://cleanhouse/prompt/original-thread",
                "https://example.invalid/not-local",
            ],
            metadata={"memory_refs": ["local://cleanhouse/memory/ref-1"]},
        )
        adapter.start_operator_session({
            "session_id": prompt["session_id"],
            "objective_id": "objective-continuity",
            "summary": "continuity fixture session",
        })

        workstation = adapter.get_workstation(prompt["session_id"])
        provenance = workstation["continuity_provenance"]
        self.assertIn(provenance["status"], {"ok", "ok_with_pickup_degraded", "degraded", "inferred", "unknown"})
        self.assertIn("continuity", workstation)
        self.assertIn(workstation["continuity"]["active_source_status"], {"ok", "degraded", "inferred", "unknown"})
        self.assertIn(workstation["continuity"]["pickup_channel_status"], {"ok", "degraded"})
        self.assertIn("active_source", provenance)
        self.assertIn("freshness", provenance)
        self.assertIn("confidence_basis", provenance)
        self.assertIn("actions_available", provenance)
        self.assertEqual(
            set(provenance["actions_available"]),
            {"accept", "ignore", "search_deeper", "pin_canonical_context"},
        )
        self.assertGreaterEqual(len(provenance["claims"]), 1)
        classifications = {claim["classification"] for claim in provenance["claims"]}
        self.assertTrue(classifications.issubset({"evidence_backed", "inferred", "degraded", "unknown"}))
        self.assertIn("evidence_backed", classifications)
        self.assertGreaterEqual(len(provenance["failed_pickups"]), 1)
        for claim in provenance["claims"]:
            for ref in claim.get("evidence_refs", []):
                self.assertTrue(ref.startswith("local://cleanhouse/"))

    def test_continuity_pins_decisions_searches_and_failures_survive_restart(self):
        search_file = Path(self._data_tmp.name) / "continuity-transcripts.txt"
        search_file.write_text(
            "operator continuity anchor: CleanHouse should expose recovered snippets\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {
            "CLEANHOUSE_CONTINUITY_SEARCH_PATHS": str(search_file),
            "CLEANHOUSE_CONTINUITY_PICKUP_FAILURE": "chatty_pickup_unavailable",
        }):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            prompt = adapter.submit_prompt(
                text="CleanHouse continuity anchor",
                context="search fixture",
                scope="frontend/",
                tool_identity="Codex",
                session_id="continuity-persist",
                objective_id="objective-continuity-persist",
            )
            pin = adapter.pin_continuity_context({
                "session_id": prompt["session_id"],
                "objective_id": "objective-continuity-persist",
                "text": "Canonical operator context: continuity is provenance.",
                "source_ref": "local://cleanhouse/prompt/" + prompt["id"],
                "evidence_refs": [
                    "local://cleanhouse/prompt/" + prompt["id"],
                    "https://example.invalid/not-local",
                ],
                "operator": "test",
            })
            self.assertEqual(pin["status"], "ok")
            decision = adapter.record_continuity_decision({
                "session_id": prompt["session_id"],
                "claim_id": pin["pin"]["claim_id"],
                "decision": "accept",
                "note": "pin accepted",
                "operator": "test",
            })
            self.assertEqual(decision["status"], "ok")
            search = adapter.search_continuity({
                "session_id": prompt["session_id"],
                "query": "continuity anchor",
                "operator": "test",
                "max_results": 3,
                "max_files": 2,
            })
            self.assertEqual(search["status"], "ok")
            self.assertEqual(search["search"]["result_count"], 1)
            self.assertIn("operator continuity anchor", search["search"]["results"][0]["snippet"])
            for ref in search["search"]["results"][0]["evidence_refs"]:
                self.assertTrue(ref.startswith("local://cleanhouse/"))

            restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            provenance = restarted.get_continuity_provenance(prompt["session_id"])
            self.assertEqual(provenance["active_source"]["id"], pin["pin"]["claim_id"])
            self.assertEqual(provenance["active_source"]["source_type"], "manual_pin")
            self.assertEqual(len(provenance["manual_pins"]), 1)
            self.assertEqual(len(provenance["decisions"]), 1)
            self.assertEqual(len(provenance["search_results"]), 1)
            self.assertTrue(any(item["reason"] == "chatty_pickup_unavailable" for item in provenance["failed_pickups"]))

    def test_continuity_search_records_visible_no_results_outcome(self):
        search_file = Path(self._data_tmp.name) / "continuity-empty.txt"
        search_file.write_text("unrelated local transcript line\n", encoding="utf-8")
        with patch.dict(os.environ, {"CLEANHOUSE_CONTINUITY_SEARCH_PATHS": str(search_file)}):
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            adapter.submit_prompt(
                text="continuity no result fixture",
                context="search fixture",
                scope="frontend/",
                tool_identity="Codex",
                session_id="continuity-no-result",
            )
            result = adapter.search_continuity({
                "session_id": "continuity-no-result",
                "query": "needle unavailable",
                "operator": "test",
            })
            self.assertEqual(result["status"], "no_results")
            self.assertEqual(result["search"]["result_count"], 0)
            self.assertEqual(result["search"]["searched_sources"], [str(search_file.resolve())])

            provenance = adapter.get_continuity_provenance("continuity-no-result")
            degraded_search_claims = [
                claim for claim in provenance["claims"]
                if claim["source_type"] == "transcript_search" and claim["classification"] == "degraded"
            ]
            self.assertEqual(len(degraded_search_claims), 1)
            self.assertIn("No additional continuity recovered", degraded_search_claims[0]["summary"])

    def test_persistence_restart_preserves_replay_spine(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Restart-safe persistence proof",
            context="prompt, approval, rollback, receipt, replay, bundle",
            scope="assets/avatars/requested/",
            repo_path="/Users/test/project",
            tool_identity="Codex",
            session_id="restart-proof-session",
            objective_id="objective-restart-proof",
        )
        adapter.start_operator_session({
            "session_id": prompt["session_id"],
            "objective_id": "objective-restart-proof",
            "summary": "restart proof session",
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requested = root / "assets" / "avatars" / "requested"
            substituted = root / "assets" / "avatars" / "substituted"
            requested.mkdir(parents=True)
            substituted.mkdir(parents=True)
            (requested / "avatar.png").write_text("requested-v1")
            substituted_file = substituted / "avatar.png"
            substituted_file.write_text("substituted-v1")

            before = adapter.create_snapshot(str(root), "before-restart", session_id=prompt["session_id"])
            substituted_file.write_text("substituted-v2")
            after = adapter.create_snapshot(str(root), "after-restart", session_id=prompt["session_id"])
            diff = adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])

            rollback = adapter.request_rollback({
                "session_id": prompt["session_id"],
                "objective_id": "objective-restart-proof",
                "path": "assets/avatars/substituted/avatar.png",
                "snapshot_id": before["id"],
                "repo_path": str(root),
                "evidence_refs": ["local://cleanhouse/diff/" + diff["id"]],
            })
            self.assertEqual(rollback["rollback"]["status"], "requested_route_available")
            executed = adapter.execute_rollback({
                "rollback_id": rollback["rollback"]["id"],
                "repo_path": str(root),
            })
            self.assertEqual(executed["rollback"]["status"], "executed_verified")

        adapter.build_timeline(prompt["session_id"])
        adapter.correlate(prompt["session_id"])
        adapter.classify(prompt["session_id"])
        adapter.generate_alerts(prompt["session_id"])
        receipt = adapter.build_receipt(prompt["session_id"])
        self.assertEqual(receipt["rollback_state"]["status"], "executed_verified")
        approval_id = receipt["approval_policy"]["approval_id"]
        resolved = adapter.resolve_approval_queue_item(
            approval_id=approval_id,
            status="rejected",
            note="restart proof rejected traversal",
            reviewer="dashboard",
        )
        self.assertEqual(resolved["approval"]["status"], "rejected")
        replay = adapter.replay_receipt_state(receipt["id"])
        bundle_export = adapter.export_receipt_timeline_bundle(receipt["id"])
        bundle = bundle_export["bundle"]
        stopped = adapter.stop_operator_session({
            "session_id": prompt["session_id"],
            "summary": "restart proof finalized",
            "finalize": True,
        })
        self.assertEqual(stopped["session"]["status"], "finalized")

        restarted = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompts = restarted.get_prompts(session_id=prompt["session_id"])
        self.assertEqual(prompts["count"], 1)
        self.assertEqual(prompts["prompts"][0]["id"], prompt["id"])
        intents = restarted.get_intents()
        self.assertTrue(any(item["id"] == prompt["session_id"] for item in intents["intents"]))

        workstation = restarted.get_workstation(prompt["session_id"])
        self.assertEqual(workstation["session"]["status"], "finalized")
        self.assertGreaterEqual(len(workstation["objectives"]), 1)
        self.assertIn(receipt["id"], workstation["receipt_replays"])

        approvals = restarted.get_approval_queue(session_id=prompt["session_id"])
        self.assertEqual(approvals["count"], 1)
        self.assertEqual(approvals["approval_queue"][0]["status"], "rejected")
        notifications = restarted.get_operator_notifications(session_id=prompt["session_id"])
        notification_types = {item["notification_type"] for item in notifications["notifications"]}
        self.assertIn("session_started", notification_types)
        self.assertIn("approval_required", notification_types)
        self.assertIn("receipt_finalized", notification_types)

        rollbacks = restarted.get_rollbacks(session_id=prompt["session_id"])
        self.assertEqual(rollbacks["count"], 1)
        self.assertEqual(rollbacks["rollbacks"][0]["status"], "executed_verified")
        receipts = restarted.get_receipts(session_id=prompt["session_id"])
        self.assertEqual(receipts["count"], 1)
        self.assertEqual(receipts["receipts"][0]["id"], receipt["id"])

        replay_after_restart = restarted.replay_receipt_state(receipt["id"])
        self.assertEqual(replay_after_restart["id"], replay["id"])
        self.assertEqual(
            replay_after_restart["integrity"]["replay_hash"],
            replay["integrity"]["replay_hash"],
        )
        self.assertEqual(replay_after_restart["state"]["status"], "rejected")
        self.assertEqual(
            replay_after_restart["replay"]["rollback_state"]["status"],
            "executed_verified",
        )
        self.assertIsNotNone(PersistenceBackend.read("receipt_replay", replay["id"]))

        stored_bundle = PersistenceBackend.read("receipt_bundle", bundle["bundle_id"])
        self.assertIsNotNone(stored_bundle)
        verified_stored = restarted.verify_receipt_timeline_bundle(stored_bundle["data"]["bundle"])
        self.assertEqual(verified_stored["status"], "ok")
        bundle_after_restart = restarted.export_receipt_timeline_bundle(receipt["id"])
        self.assertEqual(
            bundle_after_restart["bundle"]["integrity"]["bundle_hash"],
            bundle["integrity"]["bundle_hash"],
        )
        self.assertEqual(
            bundle_after_restart["bundle"]["integrity"]["manifest_hash"],
            bundle["integrity"]["manifest_hash"],
        )
        self.assertEqual(
            bundle_after_restart["bundle"]["manifest_signature"]["signature_b64"],
            bundle["manifest_signature"]["signature_b64"],
        )
        imported_after_restart = restarted.import_receipt_timeline_bundle(bundle)
        self.assertEqual(imported_after_restart["status"], "ok")
        self.assertEqual(imported_after_restart["receipt_id"], receipt["id"])

        restarted_again = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        stored_imported_bundle = PersistenceBackend.read("receipt_bundle", imported_after_restart["bundle_id"])
        self.assertIsNotNone(stored_imported_bundle)
        self.assertEqual(
            stored_imported_bundle["data"]["import"]["integrity"]["bundle_hash"],
            bundle["integrity"]["bundle_hash"],
        )
        verified_imported = restarted_again.verify_receipt_timeline_bundle(
            stored_imported_bundle["data"]["bundle"]
        )
        self.assertEqual(verified_imported["status"], "ok")

    def test_operator_session_routes_validate_payloads(self):
        self._set_request_json({"session_id": "route-session", "metadata": []})
        response = cleanhouse_module.start_operator_session()
        self._assert_bad_request(response, "metadata must be an object")

        self._set_request_json({"session_id": "route-session", "finalize": "yes"})
        response = cleanhouse_module.stop_operator_session()
        self._assert_bad_request(response, "finalize must be a boolean")

    def test_active_context_routes_validate_and_pickup(self):
        class PickupCollector:
            def collect(self, *, follow_enabled, ignored_keys=(), explicit_pickup=None):
                pickup = explicit_pickup or {}
                text = str(pickup.get("text") or pickup.get("context") or "route pickup")
                return {
                    "id": "active_context:route",
                    "dedupe_key": "route-key",
                    "source_type": "operator_pickup",
                    "source_labels": ["operator_pickup_observed"],
                    "truth_classification": "observed_context",
                    "frontmost_app": {"app_name": "Codex", "window_title": "route"},
                    "current_repo": str(pickup.get("repo_path") or ""),
                    "current_objective": str(pickup.get("objective") or text),
                    "active_prompt": text,
                    "active_prompt_preview": text,
                    "last_agent_action": "",
                    "session_id": str(pickup.get("session_id") or "active-context-route"),
                    "objective_id": str(pickup.get("objective_id") or "objective-active-context-route"),
                    "tool_identity": str(pickup.get("tool_identity") or "codex"),
                    "context": str(pickup.get("context") or ""),
                    "source_ref": str(pickup.get("source_ref") or ""),
                    "evidence_refs": ["local://cleanhouse/active-context/active_context:route"],
                    "metadata": {"active_context_source": "operator_pickup"},
                    "updated_at": "2026-05-28T12:00:00Z",
                    "attachable": bool(text),
                }

        old_adapter = cleanhouse_module._adapter
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._active_context_collector = PickupCollector()
        cleanhouse_module._adapter = adapter
        try:
            self._set_request_json({"enabled": "yes"})
            self._assert_bad_request(cleanhouse_module.active_context_follow(), "enabled must be a boolean")

            self._set_request_json({})
            self._assert_bad_request(cleanhouse_module.active_context_pickup(), "text or context is required")

            self._set_request_json({"text": "route pickup", "session_id": "bad session id"})
            self._assert_bad_request(cleanhouse_module.active_context_pickup(), "session_id format is invalid")

            self._set_request_json({"text": "route pickup", "repo_path": "/definitely/not/a/real/path"})
            self._assert_bad_request(cleanhouse_module.active_context_pickup(), "repo_path does not exist")

            self._set_request_json({"enabled": True})
            follow = cleanhouse_module.active_context_follow()
            self.assertEqual(follow["status"], "ok")
            self.assertTrue(follow["follow_enabled"])

            self._set_request_json({
                "text": "route pickup",
                "context": "approved route pickup",
                "repo_path": str(Path.cwd()),
                "session_id": "active-context-route",
                "objective_id": "objective-active-context-route",
                "source_ref": "local://cleanhouse/test/active-context-route",
            })
            pickup = cleanhouse_module.active_context_pickup()
            self.assertEqual(pickup["status"], "ok")
            self.assertEqual(pickup["active_context"]["source_type"], "operator_pickup")
            self.assertEqual(pickup["active_context"]["session_id"], "active-context-route")

            self._set_request_args({"refresh": "1"})
            active = cleanhouse_module.active_context()
            self.assertEqual(active["status"], "ok")
            self.assertEqual(active["active_context"]["id"], "active_context:route")

            self._set_request_json({"dedupe_key": "route-key"})
            ignored = cleanhouse_module.active_context_ignore()
            self.assertEqual(ignored["status"], "ok")
            self.assertEqual(ignored["ignored_key"], "route-key")
        finally:
            cleanhouse_module._adapter = old_adapter

    def test_domain_event_flow_creates_incident_policy_and_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        emitted = adapter.emit_domain_event({
            "domain": "coding_agents",
            "surface": "tool_events",
            "event_type": "unexpected_deletion",
            "severity": "critical",
            "session_id": "ambient-domain-event-session",
            "objective_id": "objective-ambient-domain-event",
            "actor": {"type": "agent", "name": "codex"},
            "resource": {"path": "assets/logo.svg"},
            "observed_vs_expected": {"status": "unexpected", "details": "delete outside scope"},
            "evidence_refs": ["local://cleanhouse/test/domain-event/unexpected-delete"],
        })
        self.assertEqual(emitted["status"], "ok")
        self.assertEqual(emitted["event"]["event_type"], "unexpected_deletion")
        self.assertEqual(emitted["incident"]["status"], "open")
        self.assertEqual(emitted["incident"]["notification_type"], "unexpected_deletion_detected")
        self.assertEqual(emitted["policy_decision"]["notification_type"], "unexpected_deletion_detected")

        incidents = adapter.get_incident_cases(session_id="ambient-domain-event-session")
        self.assertGreaterEqual(incidents["count"], 1)
        self.assertEqual(incidents["incidents"][0]["source_event_id"], emitted["event"]["id"])

        decisions = adapter.notification_policy_audit(limit=20)
        self.assertTrue(any(row.get("event_id") == emitted["event"]["id"] for row in decisions["decisions"]))

        deliveries = adapter.notification_delivery_audit(limit=20)
        self.assertGreaterEqual(deliveries["count"], 1)

    def test_workstation_includes_ambient_presence_sections(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        session_id = "ambient-workstation-session"
        adapter.start_operator_session({
            "session_id": session_id,
            "objective_id": "objective-ambient-workstation",
            "summary": "ambient workstation lane",
        })
        adapter.emit_domain_event({
            "domain": "local_runtime",
            "surface": "network",
            "event_type": "port_reopened_unknown_process",
            "severity": "critical",
            "session_id": session_id,
            "objective_id": "objective-ambient-workstation",
            "actor": {"type": "runtime", "name": "watcher"},
            "resource": {"port": 5050},
            "observed_vs_expected": {"status": "unexpected", "details": "port reopened"},
            "evidence_refs": ["local://cleanhouse/test/workstation/port-reopen"],
        })
        workstation = adapter.get_workstation(session_id)

        self.assertIn("domain_observer_matrix", workstation)
        self.assertIn("active_incident_queue", workstation)
        self.assertIn("notification_history", workstation)
        self.assertIn("action_history", workstation)
        self.assertIn("unresolved_gaps", workstation)
        self.assertGreaterEqual(len(workstation["active_incident_queue"]), 1)
        self.assertIn("observer_coverage", workstation["unresolved_gaps"])
        self.assertIn("runtime", workstation["unresolved_gaps"])

    def test_domain_events_route_validates_limit(self):
        self._set_request_args({"limit": "abc"})
        response = cleanhouse_module.domain_events()
        self._assert_bad_request(response, "limit must be an integer")

    def test_emit_domain_event_route_calls_adapter(self):
        class RouteAdapter:
            def __init__(self):
                self.payload = None

            def emit_domain_event(self, payload):
                self.payload = payload
                return {"status": "ok", "event": payload}

        adapter = RouteAdapter()
        payload = {
            "domain": "coding_agents",
            "surface": "tool_events",
            "event_type": "scope_drift_detected",
            "session_id": "ambient-route-session",
            "actor": {},
            "resource": {},
            "observed_vs_expected": {},
            "unknown_fields": [],
            "evidence_refs": [],
            "metadata": {},
        }
        self._set_request_json(payload)
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            response = cleanhouse_module.emit_domain_event()
        self.assertEqual(response["status"], "ok")
        self.assertEqual(adapter.payload["domain"], "coding_agents")
        self.assertEqual(adapter.payload["event_type"], "scope_drift_detected")

    def test_incident_action_route_calls_adapter(self):
        class RouteAdapter:
            def __init__(self):
                self.calls = []

            def update_incident_case(self, incident_id, action, note="", actor="operator"):
                self.calls.append((incident_id, action, note, actor))
                return {"status": "ok", "incident": {"id": incident_id, "status": "acknowledged"}}

        adapter = RouteAdapter()
        self._set_request_json({"note": "ack", "actor": "dashboard"})
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            response = cleanhouse_module.incident_action("incident:123", "ack")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(adapter.calls, [("incident:123", "ack", "ack", "dashboard")])

    def test_notification_probe_route_calls_adapter(self):
        class RouteAdapter:
            def __init__(self):
                self.calls = []

            def send_test_operator_notification(self, **kwargs):
                self.calls.append(kwargs)
                return {"status": "ok", "notification": {"id": "notification:probe"}}

        adapter = RouteAdapter()
        self._set_request_json({
            "session_id": "probe-session",
            "notification_type": "codex_prompt_sent",
            "severity": "info",
            "summary": "probe test",
        })
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            response = cleanhouse_module.notification_probe()
        self.assertEqual(response["status"], "ok")
        self.assertEqual(adapter.calls[0]["session_id"], "probe-session")
        self.assertEqual(adapter.calls[0]["notification_type"], "codex_prompt_sent")

    def test_notification_unack_and_snooze_routes_validate_and_call_adapter(self):
        class RouteAdapter:
            def __init__(self):
                self.unack_calls = []
                self.snooze_calls = []

            def set_operator_notification_acknowledged(self, notification_id, *, acknowledged):
                self.unack_calls.append((notification_id, acknowledged))
                return {"status": "ok", "notification": {"id": notification_id, "acknowledged": acknowledged}}

            def snooze_operator_notification(self, notification_id, *, minutes):
                self.snooze_calls.append((notification_id, minutes))
                return {"status": "ok", "notification": {"id": notification_id}}

        adapter = RouteAdapter()
        self._set_request_json({})
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            response = cleanhouse_module.unack_notification("notification:test")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(adapter.unack_calls, [("notification:test", False)])

        self._set_request_json({"minutes": 15})
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            response = cleanhouse_module.snooze_notification("notification:test")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(adapter.snooze_calls, [("notification:test", 15)])

        self._set_request_json({"minutes": 0})
        response = cleanhouse_module.snooze_notification("notification:test")
        self._assert_bad_request(response, "minutes must be a positive integer")

    def test_codex_prompt_sent_creates_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_prompt(
            text="Fix runtime drift",
            context="operator prompt",
            scope="backend/",
            tool_identity="codex",
            session_id="codex-prompt-notify-session",
            objective_id="objective-codex-prompt-notify",
        )
        self.assertEqual(result["status"], "ok")
        notifications = adapter.get_operator_notifications("codex-prompt-notify-session")["notifications"]
        codex_notifications = [item for item in notifications if item.get("notification_type") == "codex_prompt_sent"]
        self.assertEqual(len(codex_notifications), 1)
        self.assertIn("prompt sent to codex", codex_notifications[0]["summary"])

    def test_codex_prompt_notification_does_not_scan_active_context_history(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        events_db_path = str(Path(self._data_tmp.name) / "events.db")

        def list_artifacts_without_active_context(kind):
            if kind == "active_context":
                raise AssertionError("prompt notification hot path scanned active_context history")
            return []

        with patch.dict(os.environ, {"CLEANHOUSE_EVENTS_DB": events_db_path}), patch.object(
            PersistenceBackend,
            "list_artifacts",
            side_effect=list_artifacts_without_active_context,
        ):
            result = adapter.submit_prompt(
                text="Fix runtime drift without active context scan",
                context="operator prompt",
                scope="backend/",
                tool_identity="codex",
                session_id="codex-prompt-no-active-context-scan",
                objective_id="objective-codex-prompt-no-active-context-scan",
            )
            self.assertEqual(result["status"], "ok")
            notifications = adapter.get_operator_notifications("codex-prompt-no-active-context-scan")["notifications"]

        codex_notifications = [item for item in notifications if item.get("notification_type") == "codex_prompt_sent"]
        self.assertEqual(len(codex_notifications), 1)

    def test_required_agent_notification_classes_record_delivery_or_policy_skip(self):
        class FakeNotificationManager:
            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T12:00:00Z",
                    "attempts": [
                        {"backend": "terminal-notifier", "status": "delivered"},
                        {"backend": "osascript", "status": "delivered"},
                    ],
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "1",
                "CLEANHOUSE_NATIVE_CODEX_ACTIVITY": "1",
                "CLEANHOUSE_NATIVE_LIVE_ONLY": "0",
                "CLEANHOUSE_NATIVE_DESKTOP_ALLOWLIST_ONLY": "1",
            },
        ), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            prompt = adapter.submit_prompt(
                text="verify required classes",
                context="operator prompt",
                scope="backend/",
                tool_identity="codex",
                session_id="required-classes-default-session",
                objective_id="objective-required-classes-default",
            )
            self.assertEqual(prompt["status"], "ok")
            start = adapter._ensure_operator_notification(
                notification_type="session_started",
                session_id="required-classes-default-session",
                objective_id="objective-required-classes-default",
                severity="info",
                summary="agent started",
                evidence_refs=["local://cleanhouse/test/required/start"],
                source="test",
            )
            finish = adapter._ensure_operator_notification(
                notification_type="session_ended",
                session_id="required-classes-default-session",
                objective_id="objective-required-classes-default",
                severity="info",
                summary="agent finished",
                evidence_refs=["local://cleanhouse/test/required/finish"],
                source="test",
            )
            deviation = adapter._ensure_operator_notification(
                notification_type="scope_drift_detected",
                session_id="required-classes-default-session",
                objective_id="objective-required-classes-default",
                severity="warning",
                summary="scope drift detected",
                evidence_refs=["local://cleanhouse/test/required/deviation"],
                source="test",
            )
        self.assertIsNotNone(start)
        self.assertIsNotNone(finish)
        self.assertIsNotNone(deviation)
        notifications = adapter.get_operator_notifications("required-classes-default-session")["notifications"]
        required = {item["notification_type"]: item for item in notifications if item.get("notification_type") in {
            "codex_prompt_sent",
            "session_started",
            "session_ended",
            "scope_drift_detected",
        }}
        self.assertEqual(set(required.keys()), {"codex_prompt_sent", "session_started", "session_ended", "scope_drift_detected"})
        for item in required.values():
            result = item["metadata"]["native_delivery_result"]
            if item["notification_type"] in {"session_started", "session_ended", "scope_drift_detected"}:
                self.assertEqual(result["status"], "delivered")
                self.assertEqual(result["backend"], "fake-native")
                self.assertGreaterEqual(len(result.get("attempts", [])), 2)
            else:
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(result["backend"], "native_noise_control_policy")

    def test_codex_tool_event_creates_response_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.submit_tool_event({
            "tool_identity": "codex",
            "command": "codex apply patch",
            "args": ["codex", "apply", "patch"],
            "exit_code": 0,
            "cwd": str(Path.cwd()),
            "session_id": "codex-tool-notify-session",
            "objective_id": "objective-codex-tool-notify",
            "duration": 1.2,
        })
        self.assertEqual(result["status"], "ok")
        notifications = adapter.get_operator_notifications("codex-tool-notify-session")["notifications"]
        codex_notifications = [item for item in notifications if item.get("notification_type") == "codex_response_observed"]
        self.assertEqual(len(codex_notifications), 1)
        self.assertIn("codex responded", codex_notifications[0]["summary"])

    def test_codex_command_completion_creates_response_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._on_command_completed(CommandResult(
            command="codex",
            args=("codex", "exec", "task"),
            cwd=str(Path.cwd()),
            user="dev",
            returncode=0,
            duration=0.8,
            timestamp="2026-05-28T12:00:00",
            stdout_preview="ok",
            stderr_preview="",
            session_id="codex-command-notify-session",
            objective_id="objective-codex-command-notify",
            child_pid=12345,
        ))
        notifications = adapter.get_operator_notifications("codex-command-notify-session")["notifications"]
        codex_notifications = [item for item in notifications if item.get("notification_type") == "codex_response_observed"]
        self.assertEqual(len(codex_notifications), 1)
        self.assertIn("codex responded", codex_notifications[0]["summary"])

    def test_codex_active_context_response_creates_notification(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._emit_codex_active_context_response_notification(
            context={
                "id": "active_context:codex-response",
                "source_type": "codex_artifact",
                "tool_identity": "codex",
                "last_agent_action": "Applied patch to notification pipeline",
                "evidence_refs": ["local://cleanhouse/codex-session/test-thread"],
            },
            session_id="codex-active-context-session",
            objective_id="objective-codex-active-context",
            prompt_id="prompt:test",
        )
        notifications = adapter.get_operator_notifications("codex-active-context-session")["notifications"]
        codex_notifications = [item for item in notifications if item.get("notification_type") == "codex_response_observed"]
        self.assertEqual(len(codex_notifications), 1)
        self.assertIn("Applied patch to notification pipeline", codex_notifications[0]["summary"])

    def test_codex_native_notifications_can_be_suppressed_via_env_override(self):
        class FakeNotificationManager:
            send_calls = 0

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.send_calls += 1
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T12:00:00Z",
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        FakeNotificationManager.send_calls = 0
        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1", "CLEANHOUSE_NATIVE_CODEX_ACTIVITY": "0"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            created = adapter._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id="codex-native-suppressed-session",
                objective_id=None,
                severity="info",
                summary="codex prompt should be suppressed when codex native activity is disabled",
                evidence_refs=["local://cleanhouse/test/codex-native-suppressed"],
                source="prompt",
                metadata={"prompt_id": "prompt:test-codex-native-suppressed"},
            )
        self.assertIsNotNone(created)
        self.assertEqual(FakeNotificationManager.send_calls, 0)
        self.assertEqual(created.metadata["native_delivery_result"]["status"], "skipped")
        self.assertEqual(created.metadata["native_delivery_result"]["reason"], "codex_activity_native_disabled")

    def test_native_notification_fanout_defaults_all_backends(self):
        class FakeNotificationManager:
            fanout_flags = []

            def send_notification(self, title, message, level="info", metadata=None, click_url=None, wait_for_delivery=False, **kwargs):
                FakeNotificationManager.fanout_flags.append(bool(kwargs.get("fanout_all_backends", False)))
                return {
                    "status": "delivered",
                    "backend": "fake-native",
                    "notification_id": metadata["notification_id"],
                    "notification_type": metadata["notification_type"],
                    "timestamp": "2026-05-28T12:00:00Z",
                    "attempts": [
                        {"backend": "terminal-notifier", "status": "delivered"},
                        {"backend": "osascript", "status": "delivered"},
                    ],
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        FakeNotificationManager.fanout_flags = []
        with patch.dict(os.environ, {"CLEANHOUSE_NATIVE_NOTIFICATIONS": "1"}), patch.object(monitoring_module, "NotificationManager", FakeNotificationManager):
            first = adapter._ensure_operator_notification(
                notification_type="session_started",
                session_id="fanout-default-session",
                objective_id=None,
                severity="info",
                summary="fanout default should dispatch all backends",
                evidence_refs=["local://cleanhouse/test/fanout/default"],
                source="test",
            )
            self.assertIsNotNone(first)
            self.assertGreaterEqual(len(first.metadata.get("native_delivery_result", {}).get("attempts", [])), 2)
        self.assertEqual(FakeNotificationManager.fanout_flags, [True])

    def test_connected_account_lifecycle_connect_list_disconnect(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        started = adapter.start_connected_account_connect(
            cleanhouse_user_id="user-1",
            provider="github",
            connection_method="oauth",
            consent_version="v1",
        )
        self.assertEqual(started["status"], "ok")
        connected = adapter.complete_connected_account_connect(
            cleanhouse_user_id="user-1",
            provider="github",
            connection_method="oauth",
            connect_session_token=started["connect_session_token"],
            provider_account_id="octocat",
            scopes=["repo", "read:user"],
            access_token="gh-access-token",
            refresh_token="gh-refresh-token",
        )
        self.assertEqual(connected["status"], "ok")
        account_id = connected["account"]["account_id"]
        listed = adapter.list_connected_accounts(cleanhouse_user_id="user-1")
        self.assertEqual(listed["status"], "ok")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["accounts"][0]["account_id"], account_id)
        disconnected = adapter.disconnect_connected_account(cleanhouse_user_id="user-1", account_id=account_id)
        self.assertEqual(disconnected["status"], "ok")
        self.assertEqual(disconnected["account"]["status"], "disconnected")

    def test_connected_account_token_secrets_are_encrypted_and_not_exposed(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        connected = adapter.complete_connected_account_connect(
            cleanhouse_user_id="user-2",
            provider="github",
            connection_method="oauth",
            provider_account_id="octocat",
            scopes=["repo"],
            access_token="plain-access-token",
            refresh_token="plain-refresh-token",
            metadata={"lane": "test"},
        )
        self.assertEqual(connected["status"], "ok")
        account_id = connected["account"]["account_id"]
        artifact = PersistenceBackend.read("connected_account", account_id)
        payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
        row = payload.get("account", payload)
        self.assertIsInstance(row, dict)
        self.assertNotIn("plain-access-token", json.dumps(row, sort_keys=True))
        self.assertNotIn("plain-refresh-token", json.dumps(row, sort_keys=True))
        listed = adapter.list_connected_accounts(cleanhouse_user_id="user-2")
        public_row = listed["accounts"][0]
        self.assertNotIn("secrets", public_row)
        self.assertNotIn("access_token", json.dumps(public_row, sort_keys=True))

    def test_provider_event_import_dedupes_by_provider_and_provider_event_id(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        connected = adapter.complete_connected_account_connect(
            cleanhouse_user_id="user-3",
            provider="github",
            connection_method="oauth",
            provider_account_id="octocat",
            scopes=["repo"],
        )
        account_id = connected["account"]["account_id"]
        payload = [
            {"provider_event_id": "evt-1", "event_type": "prompt_submitted", "content": "hello world"},
            {"provider_event_id": "evt-1", "event_type": "prompt_submitted", "content": "hello world again"},
        ]
        first = adapter.import_provider_events(
            cleanhouse_user_id="user-3",
            provider="github",
            account_id=account_id,
            events=payload,
            capture_method="oauth",
        )
        self.assertEqual(first["accepted_count"], 1)
        self.assertEqual(first["dedupe_count"], 1)
        second = adapter.import_provider_events(
            cleanhouse_user_id="user-3",
            provider="github",
            account_id=account_id,
            events=payload,
            capture_method="oauth",
        )
        self.assertEqual(second["accepted_count"], 0)
        self.assertEqual(second["dedupe_count"], 2)

    def test_chatgpt_connector_signature_verification_rejects_bad_signature(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        connected = adapter.complete_connected_account_connect(
            cleanhouse_user_id="user-4",
            provider="chatgpt",
            connection_method="browser_connector",
            provider_account_id="chatgpt-user",
            connector_signing_secret="shared-secret",
        )
        account_id = connected["account"]["account_id"]
        events_batch = [{"provider_event_id": "evt-1", "event_type": "prompt_submitted", "content": "hello"}]
        rejected = adapter.import_provider_events(
            cleanhouse_user_id="user-4",
            provider="chatgpt",
            account_id=account_id,
            events=events_batch,
            signature="bad-signature",
            nonce="n-1",
            capture_method="browser_connector",
        )
        self.assertEqual(rejected["status"], "forbidden")
        accepted = adapter.import_provider_events(
            cleanhouse_user_id="user-4",
            provider="chatgpt",
            account_id=account_id,
            events=events_batch,
            signature=hmac.new(
                b"shared-secret",
                json.dumps(
                    {
                        "provider": "chatgpt",
                        "account_id": account_id,
                        "nonce": "n-1",
                        "events": events_batch,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii"),
                hashlib.sha256,
            ).hexdigest(),
            nonce="n-1",
            capture_method="browser_connector",
        )
        self.assertEqual(accepted["status"], "ok")
        self.assertEqual(accepted["accepted_count"], 1)

    def test_connected_accounts_routes_require_auth_and_scope_by_user(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        with patch.object(cleanhouse_module, "get_cleanhouse_monitoring_adapter", return_value=adapter):
            cleanhouse_module.request = types.SimpleNamespace(
                args={},
                headers={},
                get_json=lambda silent=True: {"provider": "github", "connection_method": "oauth"},
            )
            unauthorized = cleanhouse_module.connected_account_connect_start()
            self.assertEqual(unauthorized[1], 401)
            with patch.object(cleanhouse_module, "get_user_from_token", return_value={"user_id": "user-route"}):
                cleanhouse_module.request = types.SimpleNamespace(
                    args={},
                    headers={"Authorization": "Bearer token"},
                    get_json=lambda silent=True: {"provider": "github", "connection_method": "oauth"},
                )
                started = cleanhouse_module.connected_account_connect_start()
                self.assertEqual(started["status"], "ok")
                token = started["connect_session_token"]
                cleanhouse_module.request = types.SimpleNamespace(
                    args={},
                    headers={"Authorization": "Bearer token"},
                    get_json=lambda silent=True: {
                        "provider": "github",
                        "connection_method": "oauth",
                        "connect_session_token": token,
                        "provider_account_id": "octocat",
                        "access_token": "token-1",
                    },
                )
                connected = cleanhouse_module.connected_account_connect_callback()
                self.assertEqual(connected["status"], "ok")
                cleanhouse_module.request = types.SimpleNamespace(
                    args={},
                    headers={"Authorization": "Bearer token"},
                    get_json=lambda silent=True: None,
                )
                listed = cleanhouse_module.connected_accounts_list()
                self.assertEqual(listed["status"], "ok")
                self.assertEqual(listed["count"], 1)
