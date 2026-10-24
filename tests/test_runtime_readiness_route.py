import json
import os
import types
import unittest
from copy import deepcopy
from unittest.mock import patch

from backend import runtime_supervisor
from backend.api import cleanhouse as cleanhouse_module


class _ProbeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def getcode(self):
        return self._status

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class RuntimeReadinessRouteTests(unittest.TestCase):
    def setUp(self):
        self.ready_state = {
            "runtime_state": "healthy",
            "reason_codes": [],
            "host": "127.0.0.1",
            "port": 3333,
            "backend_pid": 100,
            "supervisor_pid": 200,
            "backend_alive": True,
            "supervisor_alive": True,
            "startup_phase": "warm",
            "bootstrap_ready_at": "2026-10-13T16:00:00+00:00",
            "warmup_ready_at": "2026-10-13T16:00:01+00:00",
            "heartbeat_at": "2026-10-13T16:00:02+00:00",
            "heartbeat_fresh": True,
            "last_probe": {"status": "ok"},
            "listener_pids": [100],
            "owned_listener_pids": [100],
            "foreign_listener_pids": [],
            "listeners": [],
            "blocked_recovery": {},
            "resource_guard": {"status": "ok", "reason_codes": []},
            "self_deviation": {},
        }

    def _status_payload(self, state):
        with patch.object(
            cleanhouse_module,
            "request",
            types.SimpleNamespace(args={"ready": "1"}),
        ), patch.object(
            cleanhouse_module,
            "jsonify",
            side_effect=lambda payload=None, **kwargs: payload if payload is not None else kwargs,
        ), patch.object(
            cleanhouse_module,
            "_event_spine_payload",
            return_value={"status": "ok", "degradation": {"degraded": False, "reasons": []}},
        ), patch.object(
            cleanhouse_module,
            "_event_spine_surfaces",
            return_value={},
        ), patch.object(
            cleanhouse_module,
            "_event_spine_collector_health",
            return_value={"status": "ok"},
        ), patch.object(
            runtime_supervisor,
            "_cached_state_for_probe",
            return_value=(deepcopy(state), "127.0.0.1", 3333),
        ):
            return cleanhouse_module.status()

    def _assert_failed(self, state, *failed_checks):
        payload = self._status_payload(state)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(
            payload["readiness_contract"]["schema"],
            "cleanhouse.runtime_operator_readiness.v1",
        )
        self.assertFalse(payload["readiness_contract"]["satisfied"])
        for failed_check in failed_checks:
            self.assertIn(failed_check, payload["readiness_contract"]["failed_checks"])
        return payload

    def test_ready_only_when_complete_canonical_contract_passes(self):
        payload = self._status_payload(self.ready_state)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["readiness_contract"]["satisfied"])
        self.assertEqual(payload["readiness_contract"]["failed_checks"], [])

    def test_bootstrap_only_and_warming_are_not_ready(self):
        cases = (
            ("bootstrap_only", "bootstrap_ready"),
            ("warming", "warming"),
        )
        for label, phase in cases:
            with self.subTest(label=label):
                state = deepcopy(self.ready_state)
                state["startup_phase"] = phase
                self._assert_failed(state, "startup_warm")

    def test_recovering_and_degraded_are_not_ready(self):
        for runtime_state in ("recovering", "degraded"):
            with self.subTest(runtime_state=runtime_state):
                state = deepcopy(self.ready_state)
                state["runtime_state"] = runtime_state
                self._assert_failed(state, "runtime_healthy")

    def test_missing_and_stale_heartbeat_are_not_ready(self):
        for label, heartbeat_at in (("missing", None), ("stale", "2026-10-13T15:00:00+00:00")):
            with self.subTest(label=label):
                state = deepcopy(self.ready_state)
                state["heartbeat_at"] = heartbeat_at
                state["heartbeat_fresh"] = False
                self._assert_failed(state, "heartbeat_fresh")

    def test_dead_backend_or_supervisor_is_not_ready(self):
        for field, failed_check in (
            ("backend_alive", "backend_alive"),
            ("supervisor_alive", "supervisor_alive"),
        ):
            with self.subTest(field=field):
                state = deepcopy(self.ready_state)
                state[field] = False
                self._assert_failed(state, failed_check)

    def test_invalid_listener_topologies_are_not_ready(self):
        cases = (
            ("missing", [], [], ("single_owned_listener", "listener_matches_backend")),
            ("foreign", [100], [300], ("no_foreign_listener",)),
            ("duplicate", [100, 101], [], ("single_owned_listener", "listener_matches_backend")),
            ("pid_mismatch", [101], [], ("listener_matches_backend",)),
        )
        for label, owned, foreign, failed_checks in cases:
            with self.subTest(label=label):
                state = deepcopy(self.ready_state)
                state["owned_listener_pids"] = owned
                state["foreign_listener_pids"] = foreign
                state["listener_pids"] = [*owned, *foreign]
                self._assert_failed(state, *failed_checks)

    def test_failed_readiness_probe_is_not_ready(self):
        state = deepcopy(self.ready_state)
        state["last_probe"] = {"status": "failed"}
        self._assert_failed(state, "readiness_probe_ok")

    def test_runtime_blocks_are_not_ready(self):
        self_deviation = deepcopy(self.ready_state)
        self_deviation["blocked_recovery"] = {"type": "runtime_unresponsive"}
        self._assert_failed(self_deviation, "no_self_deviation_block")

        hard_resource_block = deepcopy(self.ready_state)
        hard_resource_block["resource_guard"] = {
            "status": "blocked",
            "action": "hard_stop",
            "reason_codes": ["runtime_memory_ceiling_exceeded"],
        }
        self._assert_failed(
            hard_resource_block,
            "no_self_deviation_block",
            "no_resource_guard_block",
        )

    def test_canonical_evaluator_failure_is_fail_closed(self):
        with patch.object(
            cleanhouse_module,
            "request",
            types.SimpleNamespace(args={"ready": "1"}),
        ), patch.object(
            cleanhouse_module,
            "jsonify",
            side_effect=lambda payload=None, **kwargs: payload if payload is not None else kwargs,
        ), patch.object(
            cleanhouse_module,
            "_event_spine_payload",
            return_value={"status": "ok", "degradation": {"degraded": False, "reasons": []}},
        ), patch.object(
            cleanhouse_module,
            "_event_spine_surfaces",
            return_value={},
        ), patch.object(
            cleanhouse_module,
            "_event_spine_collector_health",
            return_value={"status": "ok"},
        ), patch.object(
            runtime_supervisor,
            "readiness_payload",
            side_effect=RuntimeError("unavailable"),
        ):
            payload = cleanhouse_module.status()

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["reason_codes"], ["runtime_supervisor_unavailable"])
        self.assertEqual(payload["readiness_contract"]["failed_checks"], ["evaluation_available"])

    def test_malformed_canonical_payload_is_fail_closed(self):
        with patch.object(runtime_supervisor, "readiness_payload", return_value={"ready": True}):
            payload = cleanhouse_module._runtime_readiness_payload()

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["reason_codes"], ["runtime_supervisor_unavailable"])

    def test_health_reports_liveness_without_evaluating_operator_readiness(self):
        with patch.object(
            cleanhouse_module,
            "jsonify",
            side_effect=lambda payload=None, **kwargs: payload if payload is not None else kwargs,
        ), patch.object(
            runtime_supervisor,
            "readiness_payload",
            side_effect=AssertionError("liveness must not evaluate operator readiness"),
        ):
            payload = cleanhouse_module.health()

        self.assertEqual(payload["schema"], runtime_supervisor.BACKEND_LIVENESS_SCHEMA)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["alive"])
        self.assertEqual(payload["pid"], os.getpid())
        self.assertNotIn("ready", payload)

    def test_supervisor_probe_uses_only_bounded_liveness_endpoint(self):
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            return _ProbeResponse({
                "schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA,
                "status": "ok",
                "alive": True,
            })

        with patch.object(runtime_supervisor, "urlopen", side_effect=fake_urlopen):
            payload = runtime_supervisor._probe_ready("127.0.0.1", 3333, timeout=0.5)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(observed["url"], "http://127.0.0.1:3333/health")
        self.assertNotIn("cleanhouse/status", observed["url"])
        self.assertEqual(observed["timeout"], 0.5)

    def test_supervisor_probe_rejects_weaker_or_malformed_responses(self):
        cases = (
            {"ready": True},
            {"schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA, "status": "ok", "alive": False},
            {"schema": "wrong", "status": "ok", "alive": True},
        )
        for response_payload in cases:
            with self.subTest(response_payload=response_payload), patch.object(
                runtime_supervisor,
                "urlopen",
                return_value=_ProbeResponse(response_payload),
            ):
                payload = runtime_supervisor._probe_ready("127.0.0.1", 3333)
                self.assertEqual(payload["status"], "failed")


if __name__ == "__main__":
    unittest.main()
