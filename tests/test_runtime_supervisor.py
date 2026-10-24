import json
import os
import tempfile
import unittest
import threading
import time
from pathlib import Path
from unittest.mock import patch

from backend import runtime_supervisor
from corefiles import config


class RuntimeSupervisorTests(unittest.TestCase):
    def test_supervisor_boot_replaces_stale_cached_interpreter(self):
        stale = {
            "interpreter": {
                "path": "/protected/source/cleanhouse_env/bin/python3",
                "runnable": True,
                "supervisor_compatible": True,
                "backend_compatible": True,
            }
        }
        resolved = {
            "status": "runnable",
            "selected_path": "/Users/devon/.cleanhouse/runtime/python/bin/python3",
            "selected_source": "active_sys_executable",
            "runnable": True,
            "supervisor_compatible": True,
            "backend_compatible": True,
            "attempts": [],
            "failures": [],
        }
        with patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value=resolved):
            current = runtime_supervisor._resolve_supervisor_boot_interpreter(stale)

        self.assertEqual(current["path"], resolved["selected_path"])
        self.assertNotEqual(current["path"], stale["interpreter"]["path"])

    def setUp(self):
        self._data_tmp = tempfile.TemporaryDirectory()
        self._runtime_tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        self._old_runtime_dir = os.environ.get("CLEANHOUSE_RUNTIME_DIR")
        config.DATA_DIR = Path(self._data_tmp.name) / "data"
        os.environ["CLEANHOUSE_RUNTIME_DIR"] = self._runtime_tmp.name

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        if self._old_runtime_dir is None:
            os.environ.pop("CLEANHOUSE_RUNTIME_DIR", None)
        else:
            os.environ["CLEANHOUSE_RUNTIME_DIR"] = self._old_runtime_dir
        self._data_tmp.cleanup()
        self._runtime_tmp.cleanup()

    def test_stale_supervisor_write_cannot_regress_completed_warmup(self):
        runtime_supervisor.write_state({
            "runtime_state": "healthy",
            "backend_pid": 4242,
            "startup_phase": "warm",
            "warmup_ready_at": "2026-10-15T15:00:00+00:00",
            "startup_details": {"heartbeat": {"status": "ok"}},
        })

        result = runtime_supervisor.write_state({
            "runtime_state": "healthy",
            "backend_pid": 4242,
            "startup_phase": "warming",
            "warmup_ready_at": None,
        })

        self.assertEqual(result["startup_phase"], "warm")
        self.assertEqual(result["warmup_ready_at"], "2026-10-15T15:00:00+00:00")
        self.assertEqual(result["startup_details"], {"heartbeat": {"status": "ok"}})

    def _classify(self, previous, *, listeners=None, alive=None, owned=True, ready=True, heartbeat=True):
        listeners = listeners if listeners is not None else [previous.get("backend_pid", 100)]
        alive = alive or {}
        supervisor_pid = previous.get("supervisor_pid")
        backend_pid = previous.get("backend_pid")

        def pid_alive(pid):
            if pid is None:
                return False
            return alive.get(int(pid), True)

        def pid_info(pid):
            is_supervisor = supervisor_pid is not None and int(pid) == int(supervisor_pid)
            command = (
                f"python {runtime_supervisor.REPO_ROOT}/backend/runtime_supervisor.py"
                if is_supervisor and owned
                else f"python {runtime_supervisor.REPO_ROOT}/backend/server.py"
                if owned
                else "/usr/bin/python other.py"
            )
            return {
                "pid": pid,
                "alive": pid_alive(pid),
                "command": command,
                "cwd": str(runtime_supervisor.REPO_ROOT) if owned else "/tmp",
            }

        def pid_owned_by_cleanhouse(pid, expected_supervisor=False):
            if not pid_alive(pid):
                return False
            if expected_supervisor:
                return bool(owned and supervisor_pid is not None and int(pid) == int(supervisor_pid))
            return bool(owned and (
                (backend_pid is not None and int(pid) == int(backend_pid))
                or int(pid) in {int(item) for item in listeners if item is not None}
            ))

        with patch.object(runtime_supervisor, "listener_pids", return_value=list(listeners)), patch.object(
            runtime_supervisor, "_pid_alive", side_effect=pid_alive
        ), patch.object(runtime_supervisor, "_pid_info", side_effect=pid_info), patch.object(
            runtime_supervisor, "_pid_owned_by_cleanhouse", side_effect=pid_owned_by_cleanhouse
        ), patch.object(
            runtime_supervisor,
            "_probe_ready",
            return_value={"status": "ok", "pid": listeners[0], "boot_id": "backend-boot"}
            if ready and listeners
            else {"status": "failed"},
        ), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=heartbeat
        ):
            return runtime_supervisor.classify_state(previous, host="127.0.0.1", port=3333)

    def test_classifies_healthy_runtime(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
        })
        self.assertEqual(state["runtime_state"], "healthy")
        self.assertEqual(state["reason_codes"], [])

    def test_classifies_degraded_when_heartbeat_is_stale(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
        }, heartbeat=False)
        self.assertEqual(state["runtime_state"], "degraded")
        self.assertIn("heartbeat_stale", state["reason_codes"])

    def test_classifies_stale_backend_pid(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
        }, listeners=[], alive={100: False, 200: True})
        self.assertEqual(state["runtime_state"], "stale_pid")
        self.assertIn("backend_pid_not_alive", state["reason_codes"])

    def test_classifies_orphaned_listener_without_claiming_ownership(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
        }, listeners=[333], owned=False)
        self.assertEqual(state["runtime_state"], "orphaned_listener")
        self.assertEqual(state["foreign_listener_pids"], [333])
        self.assertIn("foreign_listener_present", state["reason_codes"])

    def test_classifies_single_owned_listener_as_authoritative_backend(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": None,
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
        }, listeners=[333], owned=True)
        self.assertEqual(state["runtime_state"], "healthy")
        self.assertEqual(state["backend_pid"], 333)
        self.assertEqual(state["owned_listener_pids"], [333])
        self.assertNotIn("listener_pid_mismatch", state["reason_codes"])

    def test_classifies_recovering_backend_without_listener(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
        }, listeners=[])
        self.assertEqual(state["runtime_state"], "recovering")
        self.assertIn("listener_not_ready", state["reason_codes"])

    def test_classifies_unhealthy_when_nothing_is_running(self):
        state = self._classify({}, listeners=[], alive={})
        self.assertEqual(state["runtime_state"], "unhealthy")
        self.assertIn("backend_not_running", state["reason_codes"])

    def test_atomic_state_write_round_trips_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir)
            payload = runtime_supervisor.write_state(
                {"runtime_state": "healthy", "host": "127.0.0.1", "port": 3333},
                runtime_dir,
            )
            raw = runtime_supervisor.state_path(runtime_dir).read_text(encoding="utf-8")
            self.assertEqual(json.loads(raw)["runtime_state"], "healthy")
            self.assertEqual(payload["schema"], "cleanhouse.runtime_state.v1")
            self.assertFalse(list(runtime_dir.glob("*.tmp")))

    def test_backend_env_uses_runtime_local_events_db(self):
        runtime_dir = Path(self._runtime_tmp.name)
        env = runtime_supervisor._backend_env("127.0.0.1", 3333, runtime_dir, "boot-id")
        self.assertEqual(env["CLEANHOUSE_RUNTIME_DIR"], str(runtime_dir))
        self.assertEqual(env["CLEANHOUSE_EVENTS_DB"], str(runtime_dir / "events" / "events.db"))
        self.assertEqual(env["CLEANHOUSE_SUPERVISED"], "1")

    def test_runtime_recovery_receipt_hash_detects_tamper(self):
        receipt = runtime_supervisor.persist_runtime_recovery(
            action="backend_restart",
            previous_state={"runtime_state": "stale_pid", "backend_pid": 111},
            final_state={"runtime_state": "healthy", "backend_pid": 222},
            reason_codes=["backend_pid_not_alive"],
            evidence={"backend_pid": 222},
        )
        self.assertEqual(receipt["status"], "ok")
        root_hash = receipt["integrity"]["root_hash"]
        tampered = dict(receipt)
        tampered["action"] = "tampered"
        recalculated = runtime_supervisor._canonical_hash({
            key: value for key, value in tampered.items()
            if key not in {"status", "id", "integrity"}
        })
        self.assertNotEqual(root_hash, recalculated)
        stored = config.DATA_DIR / "runtime_recoveries" / "v1" / f"{receipt['id']}.json"
        self.assertTrue(stored.is_file())

    def test_ensure_runtime_blocks_foreign_listener_with_receipt(self):
        state = {
            "runtime_state": "orphaned_listener",
            "reason_codes": ["listener_pid_mismatch", "foreign_listener_present"],
            "foreign_listener_pids": [444],
            "owned_listener_pids": [],
            "listeners": [{"pid": 444, "command": "/usr/bin/python other.py", "cwd": "/tmp"}],
        }
        interpreter = {
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [{"path": "/usr/bin/python3", "status": "runnable"}],
            "failures": [],
        }
        with patch.object(runtime_supervisor, "classify_state", return_value=dict(state)), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value=interpreter
        ):
            result = runtime_supervisor.ensure_runtime(timeout_seconds=0.01)
        self.assertEqual(result["runtime_state"], "orphaned_listener")
        self.assertEqual(result["blocked_recovery"]["type"], "foreign_listener_blocked")
        self.assertGreaterEqual(len(result["recent_recovery_receipts"]), 1)

    def test_ensure_runtime_interpreter_resolution_failure_is_degraded_and_recorded(self):
        interpreter = {
            "status": "unavailable",
            "selected_path": None,
            "selected_source": None,
            "supervisor_compatible": False,
            "backend_compatible": False,
            "runnable": False,
            "attempts": [],
            "failures": [{"path": "/missing/python3", "reason": "missing_executable"}],
        }
        with patch.object(runtime_supervisor, "classify_state", return_value={"runtime_state": "unhealthy", "reason_codes": ["backend_not_running"]}), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value=interpreter
        ):
            result = runtime_supervisor.ensure_runtime(timeout_seconds=0.01)
        self.assertEqual(result["runtime_state"], "degraded")
        self.assertIn("interpreter_resolution_failed", result["reason_codes"])
        self.assertEqual(result["blocked_recovery"]["type"], "interpreter_resolution_failed")
        self.assertEqual(result["last_start_attempt"]["status"], "blocked")
        self.assertGreaterEqual(len(result["recent_recovery_receipts"]), 1)

    def test_delayed_warmup_does_not_block_bootstrap_thread(self):
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_ENABLE_AUTH": "0",
                "FLASK_SECRET_KEY": "runtime-supervisor-test-key",
            },
        ):
            from backend import server

        bootstrap_seen = threading.Event()
        init_started = threading.Event()
        init_release = threading.Event()
        warmup_complete = threading.Event()
        original_thread = server._EVENTS_START_THREAD
        original_started = server._EVENTS_SERVICES_STARTED

        def slow_init_db():
            init_started.set()
            init_release.wait(2)

        try:
            server._EVENTS_SERVICES_STARTED = False
            server._EVENTS_START_THREAD = None
            with patch.object(server, "_wait_for_listener_ready", return_value=True), patch.object(
                server.cleanhouse_events, "init_db", side_effect=slow_init_db
            ), patch.object(
                server.cleanhouse_events, "start_event_writer", return_value={"status": "running"}
            ), patch.object(
                server.cleanhouse_events, "start_watcher", return_value=None
            ), patch.object(server, "start_network_collector_service", return_value={"status": "starting"}), patch.object(
                server, "start_network_history_service", return_value=None
            ), patch.object(server, "_start_runtime_heartbeat", return_value=None), patch.object(
                server.runtime_supervisor, "mark_backend_bootstrap_ready", side_effect=lambda *args, **kwargs: bootstrap_seen.set()
            ), patch.object(
                server.runtime_supervisor, "mark_backend_warmup_started", return_value={}
            ), patch.object(
                server.runtime_supervisor, "mark_backend_warmup_complete", side_effect=lambda *args, **kwargs: warmup_complete.set()
            ):
                started_at = time.monotonic()
                server._start_events_services_background()
                self.assertLess(time.monotonic() - started_at, 0.1)
                self.assertTrue(bootstrap_seen.wait(1.0))
                self.assertTrue(init_started.wait(1.0))
                self.assertFalse(warmup_complete.is_set())
                init_release.set()
                self.assertTrue(warmup_complete.wait(1.0))
                if server._EVENTS_START_THREAD is not None:
                    server._EVENTS_START_THREAD.join(timeout=1.0)
        finally:
            init_release.set()
            server._EVENTS_START_THREAD = original_thread
            server._EVENTS_SERVICES_STARTED = original_started

    def test_operator_ready_requires_healthy_warm_contract(self):
        state = {
            "runtime_state": "healthy",
            "backend_alive": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "bootstrap_started_at": "2026-08-18T16:40:00+00:00",
            "bootstrap_ready_at": "2026-08-18T16:40:01+00:00",
            "startup_phase": "warm",
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "listener_pids": [100],
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "backend-boot"},
        }
        self.assertTrue(runtime_supervisor._launch_ready(state))

        for runtime_state in ("recovering", "degraded"):
            with self.subTest(runtime_state=runtime_state):
                state["runtime_state"] = runtime_state
                self.assertFalse(runtime_supervisor._launch_ready(state))

    def test_bootstrap_timestamp_alone_does_not_make_runtime_operator_ready(self):
        state = {
            "runtime_state": "recovering",
            "backend_alive": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "bootstrap_ready_at": "2026-08-18T16:40:01+00:00",
            "startup_phase": "bootstrap_ready",
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "backend-boot"},
        }
        contract = runtime_supervisor._operator_readiness_contract(state)
        self.assertFalse(contract["satisfied"])
        self.assertIn("runtime_healthy", contract["failed_checks"])
        self.assertIn("startup_warm", contract["failed_checks"])

    def test_ensure_runtime_timeout_persists_receipt(self):
        interpreter = {
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [{"path": "/usr/bin/python3", "status": "runnable"}],
            "failures": [],
        }
        state = {
            "runtime_state": "recovering",
            "reason_codes": ["listener_not_ready"],
            "supervisor_pid": 333,
            "backend_pid": 222,
        }
        runtime_supervisor.write_state(state)
        with patch.object(runtime_supervisor, "classify_state", return_value=dict(state)), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value=interpreter
        ), patch.object(runtime_supervisor, "_pid_alive", return_value=True):
            result = runtime_supervisor.ensure_runtime(timeout_seconds=0.01)
        self.assertEqual(result["runtime_state"], "unhealthy")
        self.assertIn("ensure_timeout", result["reason_codes"])
        self.assertEqual(result["blocked_recovery"]["type"], "ensure_timeout")
        self.assertGreaterEqual(len(result["recent_recovery_receipts"]), 1)

    def test_runtime_payload_exposes_operator_ready(self):
        runtime_supervisor.write_state({
            "runtime_state": "healthy",
            "reason_codes": [],
            "host": "127.0.0.1",
            "port": 3333,
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "startup_phase": "warm",
            "bootstrap_started_at": "2026-05-27T00:00:00+00:00",
            "bootstrap_ready_at": "2026-05-27T00:00:01+00:00",
            "warmup_started_at": "2026-05-27T00:00:01+00:00",
            "warmup_ready_at": "2026-05-27T00:00:02+00:00",
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
        })
        with patch.object(runtime_supervisor, "classify_state", return_value={
            "runtime_state": "healthy",
            "reason_codes": [],
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "supervisor_alive": True,
            "backend_alive": True,
            "boot_id": "boot",
            "start_time": "2026-05-27T00:00:00+00:00",
            "startup_phase": "warm",
            "bootstrap_started_at": "2026-05-27T00:00:00+00:00",
            "bootstrap_ready_at": "2026-05-27T00:00:01+00:00",
            "warmup_started_at": "2026-05-27T00:00:01+00:00",
            "warmup_ready_at": "2026-05-27T00:00:02+00:00",
            "restart_count": 0,
            "listener_pids": [100],
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "listeners": [],
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
            "heartbeat_sequence": 1,
            "heartbeat_fresh": True,
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "backend-boot"},
            "interpreter": {},
            "last_start_attempt": {},
            "blocked_recovery": {},
            "recent_recovery_receipts": [],
            "updated_at": "2026-05-27T00:00:00+00:00",
        }), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            payload = runtime_supervisor.current_runtime_payload("127.0.0.1", 3333)
        self.assertTrue(payload["operator_ready"])
        self.assertTrue(payload["readiness_contract"]["satisfied"])

    def test_readiness_detects_listener_loss_from_cached_state(self):
        runtime_supervisor.write_state({
            "runtime_state": "healthy",
            "reason_codes": [],
            "host": "127.0.0.1",
            "port": 3333,
            "supervisor_pid": 200,
            "backend_pid": 100,
            "startup_phase": "warm",
            "bootstrap_ready_at": "2026-05-27T00:00:01+00:00",
            "warmup_ready_at": "2026-05-27T00:00:02+00:00",
            "heartbeat_at": "2026-05-27T00:00:02+00:00",
            "last_probe": {"status": "ok"},
        })
        with patch.object(runtime_supervisor, "_pid_alive", return_value=True), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=True
        ), patch.object(runtime_supervisor, "listener_pids", return_value=[]):
            payload = runtime_supervisor.readiness_payload("127.0.0.1", 3333)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["runtime_state"], "degraded")
        self.assertIn("listener_not_ready", payload["reason_codes"])
        self.assertIn("operator_readiness_single_owned_listener", payload["reason_codes"])

    def test_heartbeat_start_failure_resets_flag_and_allows_retry(self):
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_ENABLE_AUTH": "0",
                "FLASK_SECRET_KEY": "runtime-supervisor-test-key",
            },
        ):
            from backend import server

        original = server._RUNTIME_HEARTBEAT_STARTED
        try:
            server._RUNTIME_HEARTBEAT_STARTED = False
            with patch.object(
                server.runtime_supervisor,
                "start_backend_heartbeat",
                side_effect=[RuntimeError("thread start failed"), None],
            ) as start:
                with self.assertRaisesRegex(RuntimeError, "heartbeat not started"):
                    server._start_runtime_heartbeat()
                self.assertFalse(server._RUNTIME_HEARTBEAT_STARTED)
                server._start_runtime_heartbeat()
                self.assertTrue(server._RUNTIME_HEARTBEAT_STARTED)
                self.assertEqual(start.call_count, 2)
        finally:
            server._RUNTIME_HEARTBEAT_STARTED = original

    def test_events_warmup_records_degraded_state_when_heartbeat_fails(self):
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_ENABLE_AUTH": "0",
                "FLASK_SECRET_KEY": "runtime-supervisor-test-key",
            },
        ):
            from backend import server

        original_started = server._EVENTS_SERVICES_STARTED
        recorded: dict[str, object] = {}
        try:
            server._EVENTS_SERVICES_STARTED = False
            with patch.object(server, "_wait_for_listener_ready", return_value=True), patch.object(
                server.cleanhouse_events, "init_db", return_value=None
            ), patch.object(
                server.cleanhouse_events, "start_event_writer", return_value={"status": "running"}
            ), patch.object(
                server.cleanhouse_events, "start_watcher", return_value={"status": "running"}
            ), patch.object(
                server, "_start_runtime_heartbeat", side_effect=RuntimeError("heartbeat unavailable")
            ), patch.object(
                server.runtime_supervisor, "mark_backend_bootstrap_ready", return_value={}
            ), patch.object(
                server.runtime_supervisor, "mark_backend_warmup_started", return_value={}
            ), patch.object(
                server.runtime_supervisor,
                "mark_backend_warmup_complete",
                side_effect=lambda *args, **kwargs: recorded.update(kwargs),
            ):
                server._start_events_services()
        finally:
            server._EVENTS_SERVICES_STARTED = original_started

        self.assertEqual(recorded["runtime_state"], "degraded")
        self.assertIn("heartbeat_start_failed", recorded["reason_codes"])
        self.assertEqual(recorded["details"]["event_writer"]["status"], "running")
        self.assertEqual(recorded["details"]["heartbeat"]["status"], "failed")

    def test_wrapper_rejects_degraded_label_without_operator_readiness(self):
        from desktop import wrapper

        runtime = {
            "runtime_state": "degraded",
            "operator_ready": False,
            "reason_codes": ["heartbeat_start_failed"],
        }
        with patch.object(wrapper, "WEBVIEW_AVAILABLE", True), patch.object(
            wrapper.sys, "platform", "linux"
        ), patch.object(
            wrapper.runtime_supervisor, "ensure_runtime", return_value=runtime
        ), patch.object(wrapper, "webview", create=True) as webview:
            with self.assertRaises(SystemExit):
                wrapper.main()
        webview.create_window.assert_not_called()

    def test_runtime_memory_ceiling_blocks_restart_and_persists_self_finding(self):
        previous = {
            "runtime_state": "healthy",
            "supervisor_pid": 200,
            "backend_pid": 100,
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "host": "127.0.0.1",
            "port": 3333,
        }
        interpreter = {
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [{"path": "/usr/bin/python3", "status": "runnable"}],
            "failures": [],
        }
        with patch.object(runtime_supervisor, "listener_pids", return_value=[100]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", return_value={
            "pid": 100,
            "alive": True,
            "command": f"python {runtime_supervisor.REPO_ROOT}/backend/server.py",
            "cwd": str(runtime_supervisor.REPO_ROOT),
        }), patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok", "pid": 100, "boot_id": "backend-boot"}), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=True
        ), patch.object(runtime_supervisor, "_pid_resource_usage", return_value={
            "status": "observed",
            "pid": 100,
            "rss_kb": 21 * 1024 * 1024,
            "rss_mb": 21 * 1024,
            "cpu_percent": 12.0,
            "process_state": "R",
            "elapsed": "01:00:00",
            "command": "python backend/server.py",
        }):
            classified = runtime_supervisor.classify_state(previous, host="127.0.0.1", port=3333)

        self.assertEqual(classified["runtime_state"], "unhealthy")
        self.assertIn("runtime_memory_ceiling_exceeded", classified["reason_codes"])
        recorded = runtime_supervisor._record_self_deviation_and_state(
            classified,
            action="runtime_memory_ceiling_exceeded",
            previous_state=previous,
            reason_codes=classified["reason_codes"],
            evidence={
                "resource_guard": classified["resource_guard"],
                "observed_behavior": "CleanHouse backend consumed about 21 GB RSS.",
            },
        )
        self.assertEqual(recorded["blocked_recovery"]["type"], "runtime_memory_ceiling_exceeded")
        self.assertGreaterEqual(len(recorded["recent_recovery_receipts"]), 1)
        self_deviation = recorded["self_deviation"]
        self.assertTrue(Path(self_deviation["evidence_artifact_path"]).is_file())
        self.assertTrue(Path(self_deviation["receipt_artifact_path"]).is_file())
        self.assertEqual(self_deviation["finding"]["title"], "CleanHouse became the suspicious process")

        with patch.object(runtime_supervisor, "classify_state", return_value=dict(recorded)), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value=interpreter
        ):
            refused = runtime_supervisor.ensure_runtime(timeout_seconds=0.01)
        self.assertEqual(refused["last_start_attempt"]["status"], "blocked")
        self.assertIn("runtime_self_deviation_restart_blocked", refused["reason_codes"])

    def test_ensure_runtime_hard_stops_ready_backend_over_memory_ceiling(self):
        runtime_supervisor.write_state({
            "runtime_state": "healthy",
            "supervisor_pid": 200,
            "backend_pid": 100,
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "host": "127.0.0.1",
            "port": 3333,
        })
        interpreter = {
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }
        with patch.object(runtime_supervisor, "listener_pids", return_value=[100]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", return_value={
            "pid": 100,
            "alive": True,
            "command": f"python {runtime_supervisor.REPO_ROOT}/backend/server.py",
            "cwd": str(runtime_supervisor.REPO_ROOT),
        }), patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok", "pid": 100, "boot_id": "backend-boot"}), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=True
        ), patch.object(runtime_supervisor, "_pid_resource_usage", return_value={
            "status": "observed",
            "pid": 100,
            "rss_kb": 4 * 1024 * 1024,
            "rss_mb": 4 * 1024,
            "cpu_percent": 10.0,
            "process_state": "R",
            "elapsed": "00:02:00",
            "command": "python backend/server.py",
        }), patch.object(runtime_supervisor, "_terminate_pid_if_owned", return_value=True), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value=interpreter
        ):
            result = runtime_supervisor.ensure_runtime("127.0.0.1", 3333, timeout_seconds=0.01)

        self.assertEqual(result["runtime_state"], "unhealthy")
        self.assertIn("runtime_memory_ceiling_exceeded", result["reason_codes"])
        self.assertEqual(result["blocked_recovery"]["type"], "runtime_memory_ceiling_exceeded")
        self.assertEqual(result["self_deviation"]["finding"]["title"], "CleanHouse became the suspicious process")
        self.assertTrue(Path(result["self_deviation"]["evidence_artifact_path"]).is_file())
        self.assertTrue(Path(result["self_deviation"]["receipt_artifact_path"]).is_file())

    def test_stop_runtime_terminates_owned_orphan_listener_without_touching_foreign_listener(self):
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "backend_pid": None,
            "supervisor_pid": None,
            "host": "127.0.0.1",
            "port": 3333,
        })

        def pid_info(pid):
            if pid == 111:
                return {
                    "pid": 111,
                    "alive": True,
                    "command": f"python {runtime_supervisor.REPO_ROOT}/backend/server.py",
                    "cwd": str(runtime_supervisor.REPO_ROOT),
                }
            return {
                "pid": pid,
                "alive": True,
                "command": "/usr/bin/python other.py",
                "cwd": "/tmp",
            }

        terminated: list[int] = []

        def terminate(pid, *, expected_supervisor=False):
            if pid is not None:
                terminated.append(int(pid))
            return pid == 111

        with patch.object(runtime_supervisor, "listener_pids", return_value=[111, 222]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", side_effect=pid_info), patch.object(
            runtime_supervisor, "_terminate_pid_if_owned", side_effect=terminate
        ):
            result = runtime_supervisor.stop_runtime("127.0.0.1", 3333)

        self.assertEqual(result["runtime_state"], "unhealthy")
        self.assertIn("runtime_stop_requested", result["reason_codes"])
        self.assertIn(111, terminated)
        self.assertNotIn(222, terminated)

    def test_runtime_payload_exposes_resource_guard_self_deviation(self):
        self_deviation = {
            "id": "runtime_self_deviation:test",
            "evidence_artifact_path": "/tmp/evidence.json",
            "receipt_artifact_path": "/tmp/receipt.json",
        }
        resource_guard = {
            "status": "blocked",
            "action": "hard_stop",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
        }
        classified = {
            "runtime_state": "unhealthy",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "supervisor_alive": True,
            "backend_alive": False,
            "boot_id": "boot",
            "start_time": "2026-06-07T00:00:00+00:00",
            "restart_count": 0,
            "listener_pids": [],
            "owned_listener_pids": [],
            "foreign_listener_pids": [],
            "listeners": [],
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "heartbeat_sequence": 1,
            "heartbeat_fresh": False,
            "last_probe": {"status": "failed"},
            "interpreter": {},
            "last_start_attempt": {},
            "blocked_recovery": {"type": "runtime_memory_ceiling_exceeded"},
            "recent_recovery_receipts": ["runtime_recovery:test"],
            "resource_guard": resource_guard,
            "self_deviation": self_deviation,
            "updated_at": "2026-06-07T00:00:00+00:00",
        }
        with patch.object(runtime_supervisor, "classify_state", return_value=dict(classified)), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
                "status": "runnable",
                "selected_path": "/usr/bin/python3",
                "selected_source": "system_python3",
                "supervisor_compatible": True,
                "backend_compatible": True,
                "runnable": True,
                "attempts": [],
                "failures": [],
            }
        ):
            payload = runtime_supervisor.current_runtime_payload("127.0.0.1", 3333)
        self.assertFalse(payload["operator_ready"])
        self.assertEqual(payload["resource_guard"]["status"], "blocked")
        self.assertEqual(payload["self_deviation"]["id"], "runtime_self_deviation:test")
        self.assertEqual(payload["self_deviation"]["review_status"], "needs_review")
        self.assertEqual(payload["self_deviation"]["runtime_impact"], "active_blocking")
        self.assertTrue(payload["self_deviation"]["blocks_investigations"])

    def test_healthy_runtime_keeps_open_self_deviation_historical(self):
        self_deviation = {
            "id": "runtime_self_deviation:history",
            "status": "open",
            "reason_codes": ["heartbeat_stale", "runtime_stuck_watchdog"],
            "finding": {
                "title": "CleanHouse became the suspicious process",
                "reason_codes": ["heartbeat_stale", "runtime_stuck_watchdog"],
            },
            "evidence_artifact_path": "/tmp/history-evidence.json",
            "receipt_artifact_path": "/tmp/history-receipt.json",
        }
        classified = {
            "runtime_state": "healthy",
            "reason_codes": [],
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "supervisor_alive": True,
            "backend_alive": True,
            "boot_id": "boot",
            "start_time": "2026-06-07T00:00:00+00:00",
            "startup_phase": "warm",
            "bootstrap_ready_at": "2026-06-07T00:00:01+00:00",
            "warmup_ready_at": "2026-06-07T00:00:02+00:00",
            "restart_count": 0,
            "listener_pids": [100],
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "listeners": [],
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "heartbeat_sequence": 1,
            "heartbeat_fresh": True,
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "backend-boot"},
            "interpreter": {},
            "last_start_attempt": {},
            "blocked_recovery": {},
            "recent_recovery_receipts": [],
            "resource_guard": {"status": "ok", "action": "none", "reason_codes": []},
            "self_deviation": self_deviation,
            "updated_at": "2026-06-07T00:00:00+00:00",
        }
        with patch.object(runtime_supervisor, "classify_state", return_value=dict(classified)):
            payload = runtime_supervisor.current_runtime_payload("127.0.0.1", 3333)

        self.assertTrue(payload["operator_ready"])
        self.assertEqual(payload["self_deviation"]["id"], "runtime_self_deviation:history")
        self.assertEqual(payload["self_deviation"]["runtime_impact"], "monitoring")
        self.assertFalse(payload["self_deviation"]["blocks_startup"])
        self.assertFalse(payload["self_deviation"]["blocks_investigations"])

    def test_runtime_cpu_breach_records_self_deviation(self):
        previous = {
            "runtime_state": "healthy",
            "supervisor_pid": 200,
            "backend_pid": 100,
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
            "resource_guard": {"cpu_degraded_samples": 2},
        }
        with patch.object(runtime_supervisor, "listener_pids", return_value=[100]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", return_value={
            "pid": 100,
            "alive": True,
            "command": f"python {runtime_supervisor.REPO_ROOT}/backend/server.py",
            "cwd": str(runtime_supervisor.REPO_ROOT),
        }), patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok", "pid": 100, "boot_id": "backend-boot"}), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=True
        ), patch.object(runtime_supervisor, "_pid_resource_usage", return_value={
            "status": "observed",
            "pid": 100,
            "rss_kb": 300 * 1024,
            "rss_mb": 300,
            "cpu_percent": 275.0,
            "process_state": "R",
            "elapsed": "00:03:00",
            "command": "python backend/server.py",
        }):
            classified = runtime_supervisor.classify_state(previous, host="127.0.0.1", port=3333)

        self.assertIn("runtime_cpu_sustained_exceeded", classified["reason_codes"])
        recorded = runtime_supervisor._record_self_deviation_and_state(
            classified,
            action="runtime_cpu_sustained_exceeded",
            previous_state=previous,
            reason_codes=classified["reason_codes"],
            evidence={
                "resource_guard": classified["resource_guard"],
                "observed_behavior": "CleanHouse backend CPU stayed above the sustained threshold.",
            },
        )
        self_deviation = recorded["self_deviation"]
        self.assertEqual(recorded["blocked_recovery"]["type"], "runtime_cpu_sustained_exceeded")
        self.assertEqual(self_deviation["comparison_result"], "CPU Threshold Breach")
        self.assertEqual(self_deviation["mitigation_action"], "investigation_pause")
        self.assertTrue(Path(self_deviation["evidence_artifact_path"]).is_file())
        self.assertTrue(Path(self_deviation["receipt_artifact_path"]).is_file())

    def test_stuck_worker_records_self_deviation(self):
        previous = {
            "runtime_state": "healthy",
            "supervisor_pid": 200,
            "backend_pid": 100,
            "heartbeat_at": "2026-06-07T00:00:00+00:00",
        }
        classified = self._classify(previous, heartbeat=False)
        self.assertIn("runtime_stuck_watchdog", classified["resource_guard"]["reason_codes"])
        recorded = runtime_supervisor._record_self_deviation_and_state(
            classified,
            action="runtime_stuck_watchdog",
            previous_state=previous,
            reason_codes=classified["reason_codes"],
            evidence={
                "resource_guard": classified["resource_guard"],
                "heartbeat_at": classified.get("heartbeat_at"),
                "observed_behavior": "CleanHouse heartbeat became stale while backend work was expected to progress.",
            },
        )
        self_deviation = recorded["self_deviation"]
        self.assertEqual(recorded["blocked_recovery"]["type"], "runtime_stuck_watchdog")
        self.assertEqual(self_deviation["comparison_result"], "Stuck Worker")
        self.assertEqual(self_deviation["mitigation_action"], "investigation_pause")
        self.assertTrue(Path(self_deviation["evidence_artifact_path"]).is_file())
        self.assertTrue(Path(self_deviation["receipt_artifact_path"]).is_file())

    def test_restart_loop_records_self_deviation_and_blocks_restart(self):
        previous = {"runtime_state": "recovering", "reason_codes": ["readiness_probe_failed"]}
        state = {
            "runtime_state": "unhealthy",
            "reason_codes": ["readiness_probe_failed", "restart_budget_exhausted"],
            "host": "127.0.0.1",
            "port": 3333,
            "recent_recovery_receipts": [],
            "last_start_attempt": {"status": "blocked", "failure_reason": "restart_budget_exhausted"},
        }
        recorded = runtime_supervisor._record_self_deviation_and_state(
            state,
            action="restart_budget_exhausted",
            previous_state=previous,
            reason_codes=state["reason_codes"],
            evidence={
                "restart_times": [1.0, 2.0, 3.0],
                "restart_window_seconds": runtime_supervisor.RESTART_WINDOW_SECONDS,
                "max_restarts_per_window": runtime_supervisor.MAX_RESTARTS_PER_WINDOW,
            },
        )
        self_deviation = recorded["self_deviation"]
        self.assertEqual(recorded["blocked_recovery"]["type"], "restart_budget_exhausted")
        self.assertEqual(self_deviation["comparison_result"], "Restart Loop")
        self.assertEqual(self_deviation["mitigation_action"], "manual_approval_required")

        with patch.object(runtime_supervisor, "classify_state", return_value=dict(recorded)), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
                "status": "runnable",
                "selected_path": "/usr/bin/python3",
                "selected_source": "system_python3",
                "supervisor_compatible": True,
                "backend_compatible": True,
                "runnable": True,
                "attempts": [],
                "failures": [],
            }
        ):
            refused = runtime_supervisor.ensure_runtime(timeout_seconds=0.01)
        self.assertEqual(refused["last_start_attempt"]["status"], "blocked")
        self.assertIn("runtime_self_deviation_restart_blocked", refused["reason_codes"])

    def test_unresponsive_runtime_records_self_deviation(self):
        previous = {"runtime_state": "recovering", "reason_codes": ["readiness_probe_failed"]}
        state = {
            "runtime_state": "degraded",
            "reason_codes": ["readiness_probe_failed", "runtime_unresponsive"],
            "host": "127.0.0.1",
            "port": 3333,
            "last_probe": {"status": "failed", "error": "timed out"},
        }
        recorded = runtime_supervisor._record_self_deviation_and_state(
            state,
            action="runtime_unresponsive",
            previous_state=previous,
            reason_codes=state["reason_codes"],
            evidence={
                "last_probe": state["last_probe"],
                "observed_behavior": "CleanHouse readiness probe failed repeatedly while the backend process was alive.",
            },
        )
        self_deviation = recorded["self_deviation"]
        self.assertEqual(recorded["blocked_recovery"]["type"], "runtime_unresponsive")
        self.assertEqual(self_deviation["comparison_result"], "Unresponsive Runtime")
        self.assertEqual(self_deviation["mitigation_action"], "degraded_state")
        self.assertTrue(Path(self_deviation["evidence_artifact_path"]).is_file())
        self.assertTrue(Path(self_deviation["receipt_artifact_path"]).is_file())

    def test_acknowledged_restart_does_not_disable_future_self_deviation(self):
        state = {
            "runtime_state": "unhealthy",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
            "blocked_recovery": {"type": "runtime_memory_ceiling_exceeded"},
            "self_deviation": {
                "id": "runtime_self_deviation:test",
                "status": "open",
                "next_action": "Review evidence.",
            },
        }
        acknowledged = runtime_supervisor._acknowledge_self_deviation_for_restart(dict(state))
        self.assertEqual(acknowledged["self_deviation"]["status"], "acknowledged_for_restart")
        self.assertEqual(acknowledged["self_deviation"]["id"], "runtime_self_deviation:test")
        self.assertEqual(acknowledged["blocked_recovery"], {})

        future = dict(acknowledged)
        future["blocked_recovery"] = {"type": "runtime_cpu_sustained_exceeded"}
        future["self_deviation"] = {"id": "runtime_self_deviation:future", "status": "open"}
        self.assertTrue(runtime_supervisor._self_deviation_block_active(future))

    def test_acknowledging_live_owned_generation_preserves_health_and_restart_count(self):
        healthy = {
            "runtime_state": "healthy",
            "status": "healthy",
            "reason_codes": [],
            "restart_count": 7,
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "backend_alive": True,
            "backend_owned": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "startup_phase": "warm",
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "backend-boot"},
            "self_deviation": {"id": "runtime_self_deviation:test", "status": "open"},
            "blocked_recovery": {"type": "runtime_unresponsive"},
        }
        with patch.object(runtime_supervisor, "classify_state", return_value=dict(healthy)):
            acknowledged = runtime_supervisor.acknowledge_self_deviation(
                "127.0.0.1", 3333, runtime_dir=Path(self._runtime_tmp.name)
            )

        self.assertEqual(acknowledged["runtime_state"], "healthy")
        self.assertEqual(acknowledged["restart_count"], 7)
        self.assertTrue(acknowledged["operator_ready"])
        self.assertFalse(runtime_supervisor._backend_restart_required(acknowledged))

    def test_restart_eligibility_tracks_generation_loss_not_health_label(self):
        self.assertTrue(runtime_supervisor._backend_restart_required({
            "runtime_state": "unhealthy",
            "backend_alive": True,
        }))
        self.assertTrue(runtime_supervisor._backend_restart_required({
            "runtime_state": "healthy",
            "backend_alive": False,
        }))
        self.assertTrue(runtime_supervisor._backend_restart_required({
            "runtime_state": "healthy",
            "backend_alive": True,
        }, backend_dead=True))
        survivor = {
            "runtime_state": "healthy",
            "backend_pid": 100,
            "backend_boot_id": "survivor-boot",
            "backend_alive": True,
            "backend_owned": True,
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "survivor-boot"},
        }
        for child_dead in (False, True):
            self.assertFalse(runtime_supervisor._backend_restart_required(survivor, backend_dead=child_dead))
        for invalid_ownership in (None, False, "true", 1):
            for child_dead in (False, True):
                with self.subTest(backend_owned=invalid_ownership, backend_dead=child_dead):
                    survivor["backend_owned"] = invalid_ownership
                    self.assertTrue(runtime_supervisor._backend_restart_required(survivor, backend_dead=child_dead))
        survivor["backend_owned"] = True

    def test_supervisor_does_not_respawn_when_exited_child_has_valid_owned_survivor(self):
        class StopLoop(Exception):
            pass

        class ExitedChild:
            pid = 300

            @staticmethod
            def poll():
                return 1

        interpreter = {
            "path": "/usr/bin/python3",
            "status": "runnable",
            "runnable": True,
            "supervisor_compatible": True,
            "backend_compatible": True,
        }
        missing = {
            "runtime_state": "unhealthy",
            "status": "unhealthy",
            "reason_codes": ["backend_not_running"],
            "restart_count": 0,
            "backend_pid": None,
            "backend_alive": False,
            "backend_owned": False,
            "supervisor_alive": True,
            "owned_listener_pids": [],
            "foreign_listener_pids": [],
            "last_probe": {"status": "skipped"},
            "resource_guard": {},
            "self_deviation": {},
        }
        survivor = {
            "runtime_state": "healthy",
            "status": "healthy",
            "reason_codes": [],
            "restart_count": 1,
            "backend_pid": 100,
            "backend_boot_id": "survivor-boot",
            "backend_alive": True,
            "backend_owned": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "startup_phase": "warm",
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok", "pid": 100, "boot_id": "survivor-boot"},
            "resource_guard": {},
            "self_deviation": {},
        }
        writes = []

        def capture_write(payload, runtime_dir=None):
            writes.append(dict(payload))
            return payload

        def stop_after_survivor(_seconds):
            if writes and writes[-1].get("runtime_state") == "healthy":
                raise StopLoop()

        with patch.object(runtime_supervisor, "read_state", return_value={}), patch.object(
            runtime_supervisor, "write_state", side_effect=capture_write
        ), patch.object(
            runtime_supervisor, "classify_state", side_effect=[dict(missing), dict(survivor), dict(survivor)]
        ), patch.object(
            runtime_supervisor, "_resolve_supervisor_boot_interpreter", return_value=dict(interpreter)
        ), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
                "status": "runnable",
                "selected_path": "/usr/bin/python3",
                "selected_source": "test",
                "runnable": True,
                "supervisor_compatible": True,
                "backend_compatible": True,
                "attempts": [],
                "failures": [],
            }
        ), patch.object(
            runtime_supervisor, "_start_backend", return_value=ExitedChild()
        ) as start_backend, patch.object(
            runtime_supervisor, "persist_runtime_recovery", return_value={"id": "runtime_recovery:test"}
        ), patch.object(runtime_supervisor.time, "sleep", side_effect=stop_after_survivor):
            with self.assertRaises(StopLoop):
                runtime_supervisor.supervisor_loop("127.0.0.1", 3333, Path(self._runtime_tmp.name))

        self.assertEqual(start_backend.call_count, 1)
        survivor_writes = [state for state in writes if state.get("runtime_state") == "healthy"]
        self.assertEqual(len(survivor_writes), 1)
        self.assertEqual(survivor_writes[0]["backend_pid"], 100)
        self.assertEqual(survivor_writes[0]["restart_count"], 1)
        self.assertFalse(any(state.get("restart_count") == 2 for state in writes))

    def test_adoption_records_liveness_generation_and_mismatch_fails_closed(self):
        adopted = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 999,
            "backend_boot_id": "stale-boot",
        }, listeners=[100], alive={999: False})
        self.assertEqual(adopted["backend_pid"], 100)
        self.assertEqual(adopted["backend_boot_id"], "backend-boot")
        self.assertEqual(adopted["last_probe"]["pid"], 100)
        self.assertEqual(adopted["runtime_state"], "healthy")

        mismatched = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
            "backend_boot_id": "expected-boot",
        })
        self.assertEqual(mismatched["last_probe"]["status"], "failed")
        self.assertEqual(mismatched["last_probe"]["failure_reason"], "liveness_boot_id_mismatch")
        self.assertIn("liveness_boot_id_mismatch", mismatched["reason_codes"])
        self.assertFalse(runtime_supervisor._launch_ready(mismatched))

    def test_operator_readiness_rejects_missing_liveness_generation(self):
        state = {
            "runtime_state": "healthy",
            "backend_alive": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "startup_phase": "warm",
            "backend_pid": 100,
            "backend_boot_id": "backend-boot",
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "last_probe": {"status": "ok"},
        }
        contract = runtime_supervisor._operator_readiness_contract(state)
        self.assertFalse(contract["satisfied"])
        self.assertIn("readiness_probe_ok", contract["failed_checks"])

    def test_startup_preflight_handles_block_ack_and_foreign_listener(self):
        self_deviation = {
            "id": "runtime_self_deviation:test",
            "status": "open",
            "finding": {"title": "CleanHouse became the suspicious process"},
            "next_action": "Review evidence before restart.",
            "evidence_artifact_path": "/tmp/evidence.json",
            "receipt_artifact_path": "/tmp/receipt.json",
        }
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
            "backend_pid": 999001,
            "supervisor_pid": 999002,
            "self_deviation": self_deviation,
            "blocked_recovery": {"type": "runtime_memory_ceiling_exceeded"},
        })

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=False
        ), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            allowed = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(allowed["status"], "ready_to_start")
        self.assertTrue(allowed["should_start"])
        self.assertEqual(allowed["self_deviation"]["id"], "runtime_self_deviation:test")
        self.assertEqual(allowed["startup_warning"]["type"], "recoverable_self_deviation")
        self.assertEqual(allowed["stale_pids_cleared"], {"backend_pid": 999001, "supervisor_pid": 999002})
        cleaned = runtime_supervisor.read_state()
        self.assertIsNone(cleaned.get("backend_pid"))
        self.assertIsNone(cleaned.get("supervisor_pid"))

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=False
        ), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            acknowledged = runtime_supervisor.startup_preflight(
                "127.0.0.1",
                3333,
                acknowledge_self_deviation_restart=True,
            )

        self.assertIn(acknowledged["status"], {"ready_to_start", "stale_state_cleaned"})
        self.assertTrue(acknowledged["should_start"])
        self.assertEqual(runtime_supervisor.read_state()["self_deviation"]["status"], "acknowledged_for_restart")

        runtime_supervisor.write_state({"runtime_state": "unhealthy", "reason_codes": []})
        with patch.object(runtime_supervisor, "listener_pids", return_value=[444]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", return_value={
            "pid": 444,
            "alive": True,
            "command": "/usr/bin/python other.py",
            "cwd": "/tmp",
        }), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            foreign = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(foreign["status"], "foreign_listener_blocked")
        self.assertFalse(foreign["should_start"])
        self.assertEqual(foreign["listener"]["foreign_pids"], [444])

    def test_startup_preflight_clears_reused_backend_pid(self):
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "reason_codes": ["listener_not_ready"],
            "backend_pid": 2116,
            "supervisor_pid": None,
        })

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=True
        ), patch.object(runtime_supervisor, "_pid_info", return_value={
            "pid": 2116,
            "alive": True,
            "command": "/usr/libexec/proactived",
            "cwd": "/System/Library",
        }), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            allowed = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(allowed["status"], "stale_state_cleaned")
        self.assertEqual(allowed["stale_pids_cleared"], {"backend_pid": 2116})
        self.assertIsNone(runtime_supervisor.read_state().get("backend_pid"))

    def test_startup_preflight_recovers_soft_self_deviation_without_clearing_evidence(self):
        self_deviation = {
            "id": "runtime_self_deviation:soft",
            "status": "open",
            "finding": {
                "title": "CleanHouse became the suspicious process",
                "reason_codes": [
                    "readiness_probe_failed",
                    "runtime_memory_degraded_threshold_exceeded",
                    "runtime_unresponsive",
                ],
                "mitigation_action": "degraded_state",
            },
            "next_action": "Mark runtime degraded and avoid starting more investigations until readiness recovers.",
            "evidence_artifact_path": "/tmp/soft-evidence.json",
            "receipt_artifact_path": "/tmp/soft-receipt.json",
            "reason_codes": [
                "readiness_probe_failed",
                "runtime_memory_degraded_threshold_exceeded",
                "runtime_unresponsive",
            ],
            "mitigation_action": "degraded_state",
        }
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "reason_codes": ["backend_not_running", "runtime_stop_requested"],
            "backend_pid": None,
            "supervisor_pid": None,
            "self_deviation": self_deviation,
            "blocked_recovery": {"type": "runtime_unresponsive"},
        })

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=False
        ), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            preflight = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(preflight["status"], "ready_to_start")
        self.assertTrue(preflight["should_start"])
        self.assertEqual(preflight["startup_warning"]["type"], "recoverable_self_deviation")
        self.assertEqual(preflight["startup_warning"]["self_deviation"]["id"], "runtime_self_deviation:soft")
        stored = runtime_supervisor.read_state()
        self.assertEqual(stored["self_deviation"]["status"], "open")
        self.assertEqual(stored["self_deviation"]["evidence_artifact_path"], "/tmp/soft-evidence.json")
        self.assertEqual(stored["self_deviation"]["receipt_artifact_path"], "/tmp/soft-receipt.json")
        self.assertEqual(stored["startup_recovery_allowed"]["self_deviation_id"], "runtime_self_deviation:soft")

        class FakeProcess:
            pid = 123456

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=False
        ), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }), patch.object(runtime_supervisor, "_spawn_supervisor_process", return_value=FakeProcess()):
            ensured = runtime_supervisor.ensure_runtime("127.0.0.1", 3333, timeout_seconds=0.01)

        self.assertNotEqual(ensured.get("last_start_attempt", {}).get("failure_reason"), "runtime_self_deviation_restart_blocked")
        self.assertNotIn("runtime_self_deviation_restart_blocked", ensured.get("reason_codes", []))

    def test_startup_preflight_allows_historical_self_deviation_when_port_clear(self):
        self_deviation = {
            "id": "runtime_self_deviation:hard",
            "status": "open",
            "finding": {
                "title": "CleanHouse became the suspicious process",
                "reason_codes": ["runtime_memory_ceiling_exceeded"],
                "mitigation_action": "runtime_stop",
            },
            "next_action": "Review evidence before restart.",
            "evidence_artifact_path": "/tmp/hard-evidence.json",
            "receipt_artifact_path": "/tmp/hard-receipt.json",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
        }
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "reason_codes": ["backend_not_running"],
            "self_deviation": self_deviation,
            "blocked_recovery": {"type": "runtime_memory_ceiling_exceeded"},
        })

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", return_value=False
        ), patch.object(runtime_supervisor.runtime_env, "resolve_interpreter", return_value={
            "status": "runnable",
            "selected_path": "/usr/bin/python3",
            "selected_source": "system_python3",
            "supervisor_compatible": True,
            "backend_compatible": True,
            "runnable": True,
            "attempts": [],
            "failures": [],
        }):
            preflight = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(preflight["status"], "ready_to_start")
        self.assertTrue(preflight["should_start"])
        self.assertEqual(preflight["self_deviation"]["id"], "runtime_self_deviation:hard")
        self.assertEqual(preflight["self_deviation"]["review_status"], "needs_review")
        self.assertEqual(preflight["self_deviation"]["runtime_impact"], "historical_record")
        self.assertFalse(preflight["self_deviation"]["blocks_startup"])
        self.assertEqual(preflight["startup_warning"]["type"], "recoverable_self_deviation")
        self.assertEqual(preflight["startup_warning"]["self_deviation"]["id"], "runtime_self_deviation:hard")
        stored = runtime_supervisor.read_state()
        self.assertEqual(stored["self_deviation"]["status"], "open")
        self.assertEqual(stored["self_deviation"]["evidence_artifact_path"], "/tmp/hard-evidence.json")
        self.assertEqual(stored["self_deviation"]["receipt_artifact_path"], "/tmp/hard-receipt.json")
        self.assertEqual(stored["startup_recovery_allowed"]["self_deviation_id"], "runtime_self_deviation:hard")

    def test_startup_preflight_allows_self_deviation_when_port_clear_with_lingering_pids(self):
        self_deviation = {
            "id": "runtime_self_deviation:runtime",
            "status": "open",
            "finding": {
                "title": "CleanHouse became the suspicious process",
                "reason_codes": ["readiness_probe_failed", "runtime_unresponsive"],
                "mitigation_action": "degraded_state",
            },
            "next_action": "Mark runtime degraded and avoid starting more investigations until readiness recovers.",
            "evidence_artifact_path": "/tmp/runtime-evidence.json",
            "receipt_artifact_path": "/tmp/runtime-receipt.json",
            "reason_codes": ["readiness_probe_failed", "runtime_unresponsive"],
        }
        runtime_supervisor.write_state({
            "runtime_state": "unhealthy",
            "backend_pid": 94716,
            "supervisor_pid": 94701,
            "reason_codes": ["listener_not_ready", "runtime_stop_requested"],
            "blocked_recovery": {"type": "runtime_unresponsive"},
            "self_deviation": self_deviation,
            "interpreter": {
                "path": "/usr/bin/python3",
                "source": "system_python3",
                "status": "runnable",
                "supervisor_compatible": True,
                "backend_compatible": True,
                "runnable": True,
            },
        })

        def fake_pid_alive(pid):
            return int(pid or 0) in {94716, 94701}

        def fake_pid_owned_by_cleanhouse(pid, expected_supervisor=False):
            return int(pid or 0) in {94716, 94701}

        with patch.object(runtime_supervisor, "listener_pids", return_value=[]), patch.object(
            runtime_supervisor, "_pid_alive", side_effect=fake_pid_alive
        ), patch.object(runtime_supervisor, "_pid_owned_by_cleanhouse", side_effect=fake_pid_owned_by_cleanhouse), patch.object(
            runtime_supervisor.runtime_env, "resolve_interpreter", side_effect=AssertionError("preflight should not probe interpreters")
        ):
            preflight = runtime_supervisor.startup_preflight("127.0.0.1", 3333)

        self.assertEqual(preflight["status"], "ready_to_start")
        self.assertTrue(preflight["should_start"])
        self.assertEqual(preflight["runtime_state"], "recovering")
        self.assertEqual(preflight["self_deviation"]["id"], "runtime_self_deviation:runtime")
        self.assertEqual(preflight["self_deviation"]["runtime_impact"], "monitoring")
        self.assertFalse(preflight["self_deviation"]["blocks_startup"])
        self.assertEqual(preflight["startup_warning"]["type"], "recoverable_self_deviation")
        stored = runtime_supervisor.read_state()
        self.assertEqual(stored["startup_recovery_allowed"]["self_deviation_id"], "runtime_self_deviation:runtime")
        self.assertEqual(stored["interpreter"]["path"], "/usr/bin/python3")

    def test_startup_preflight_allows_healthy_owned_runtime_with_preserved_self_deviation(self):
        self_deviation = {
            "id": "runtime_self_deviation:recovered",
            "status": "open",
            "reason_codes": ["runtime_unresponsive"],
            "mitigation_action": "degraded_state",
        }
        state = {
            "runtime_state": "healthy",
            "backend_alive": True,
            "supervisor_alive": True,
            "listener_pids": [25895],
            "owned_listener_pids": [25895],
            "foreign_listener_pids": [],
            "reason_codes": ["runtime_self_deviation_restart_blocked"],
            "blocked_recovery": {"type": "runtime_unresponsive"},
            "self_deviation": self_deviation,
        }

        classification = runtime_supervisor._startup_self_deviation_classification(state)

        self.assertEqual(classification["status"], "recoverable")
        self.assertEqual(classification["reason_codes"], ["runtime_unresponsive"])
        self.assertFalse(runtime_supervisor._self_deviation_summary(state)["blocks_startup"])

    def test_record_recovery_state_embeds_actionability(self):
        previous = {"runtime_state": "recovering", "reason_codes": ["readiness_probe_failed"]}
        state = {
            "runtime_state": "unhealthy",
            "reason_codes": ["restart_budget_exhausted"],
            "host": "127.0.0.1",
            "port": 3333,
            "recent_recovery_receipts": [],
        }
        updated = runtime_supervisor._record_recovery_and_state(
            state,
            action="restart_budget_exhausted",
            previous_state=previous,
            reason_codes=["restart_budget_exhausted"],
            evidence={"actionability": {"runtime_evidence_ref": "local://cleanhouse/runtime/test"}},
        )
        self.assertEqual(updated["blocked_recovery"]["type"], "restart_budget_exhausted")
        self.assertIn("actionability", updated["blocked_recovery"]["details"])
        self.assertIn("recovery_receipt_id", updated["blocked_recovery"]["details"]["actionability"])


if __name__ == "__main__":
    unittest.main()
