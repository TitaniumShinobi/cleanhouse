import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import runtime_supervisor
from corefiles import config


class RuntimeSupervisorTests(unittest.TestCase):
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

    def _classify(self, previous, *, listeners=None, alive=None, owned=True, ready=True, heartbeat=True):
        listeners = listeners if listeners is not None else [previous.get("backend_pid", 100)]
        alive = alive or {}

        def pid_alive(pid):
            if pid is None:
                return False
            return alive.get(int(pid), True)

        def pid_info(pid):
            return {
                "pid": pid,
                "alive": pid_alive(pid),
                "command": f"python {runtime_supervisor.REPO_ROOT}/backend/server.py" if owned else "/usr/bin/python other.py",
                "cwd": str(runtime_supervisor.REPO_ROOT) if owned else "/tmp",
            }

        with patch.object(runtime_supervisor, "listener_pids", return_value=list(listeners)), patch.object(
            runtime_supervisor, "_pid_alive", side_effect=pid_alive
        ), patch.object(runtime_supervisor, "_pid_info", side_effect=pid_info), patch.object(
            runtime_supervisor, "_probe_ready", return_value={"status": "ok" if ready else "failed"}
        ), patch.object(
            runtime_supervisor, "_heartbeat_fresh", return_value=heartbeat
        ):
            return runtime_supervisor.classify_state(previous, host="127.0.0.1", port=3333)

    def test_classifies_healthy_runtime(self):
        state = self._classify({
            "supervisor_pid": 200,
            "backend_pid": 100,
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
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
        })
        with patch.object(runtime_supervisor, "classify_state", return_value={
            "runtime_state": "healthy",
            "reason_codes": [],
            "supervisor_pid": 200,
            "backend_pid": 100,
            "supervisor_alive": True,
            "backend_alive": True,
            "boot_id": "boot",
            "start_time": "2026-05-27T00:00:00+00:00",
            "restart_count": 0,
            "listener_pids": [100],
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "listeners": [],
            "heartbeat_at": "2026-05-27T00:00:00+00:00",
            "heartbeat_sequence": 1,
            "heartbeat_fresh": True,
            "last_probe": {"status": "ok"},
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
        }), patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok"}), patch.object(
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
        }), patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok"}), patch.object(
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
