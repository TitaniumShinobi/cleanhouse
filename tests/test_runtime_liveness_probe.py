import json
import os
import unittest
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


class RuntimeLivenessProbeTests(unittest.TestCase):
    def test_readiness_evaluator_failures_are_fail_closed(self):
        cases = (
            RuntimeError("unavailable"),
            {"ready": True},
        )
        for result in cases:
            with self.subTest(result=result):
                effect = {"return_value": result}
                if isinstance(result, Exception):
                    effect = {"side_effect": result}
                with patch.object(runtime_supervisor, "readiness_payload", **effect):
                    payload = cleanhouse_module._runtime_readiness_payload()

                self.assertFalse(payload["ready"])
                self.assertEqual(payload["status"], "degraded")
                self.assertEqual(payload["reason_codes"], ["runtime_supervisor_unavailable"])
                self.assertEqual(
                    payload["readiness_contract"]["failed_checks"],
                    ["evaluation_available"],
                )

    def test_readiness_probe_does_not_load_subsystem_metadata(self):
        canonical = {
            "ready": True,
            "readiness_contract": {
                "schema": "cleanhouse.runtime_operator_readiness.v1",
                "satisfied": True,
                "checks": {},
                "failed_checks": [],
            },
        }
        with patch.object(runtime_supervisor, "readiness_payload", return_value=canonical), patch.object(
            cleanhouse_module, "network_collector_health", return_value={"state": "running"}
        ) as collector, patch.object(
            cleanhouse_module, "_network_vvault_readiness", return_value={"state": "live"}
        ) as preservation:
            payload = cleanhouse_module._runtime_readiness_payload()

        self.assertTrue(payload["ready"])
        collector.assert_not_called()
        preservation.assert_not_called()

    def test_health_is_liveness_only(self):
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

    def test_supervisor_probe_uses_liveness_endpoint(self):
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            return _ProbeResponse({
                "schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA,
                "status": "ok",
                "alive": True,
                "pid": 100,
                "boot_id": "backend-boot",
            })

        with patch.object(runtime_supervisor, "urlopen", side_effect=fake_urlopen):
            payload = runtime_supervisor._probe_ready("127.0.0.1", 3333, timeout=0.5)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pid"], 100)
        self.assertEqual(payload["boot_id"], "backend-boot")
        self.assertEqual(observed["url"], "http://127.0.0.1:3333/health")
        self.assertEqual(observed["timeout"], 0.5)

    def test_supervisor_probe_rejects_weaker_payloads(self):
        cases = (
            {"ready": True},
            {"schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA, "status": "ok", "alive": False},
            {"schema": "wrong", "status": "ok", "alive": True},
            {"schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA, "status": "ok", "alive": True},
            {"schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA, "status": "ok", "alive": True, "pid": 100, "boot_id": ""},
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
