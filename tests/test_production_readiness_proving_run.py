import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


def _load_gate_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "production_readiness_proving_run.py"
    spec = importlib.util.spec_from_file_location("production_readiness_proving_run", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


class ProductionReadinessProvingRunTests(unittest.TestCase):
    def test_unsupported_claims_are_reported_as_gaps(self):
        gaps = gate.build_unsupported_claim_gaps()
        claims = {gap["claim"]: gap for gap in gaps}

        self.assertIn("universal_filesystem_coverage", claims)
        self.assertIn("native_process_lineage", claims)
        self.assertIn("native_network_packet_or_dns_capture", claims)
        self.assertIn("native_cloud_sync_provider_state", claims)
        self.assertIn("universal_background_service_correlation", claims)
        self.assertTrue(all(gap["status"] == "gap" for gap in gaps))
        self.assertTrue(all(gap["evidence_level"] == "unknown" for gap in gaps))

    def test_performance_thresholds_fail_when_measurement_exceeds_budget(self):
        result = gate.evaluate_performance(
            {
                "startup_seconds": 3.0,
                "workload_seconds": 1.0,
            },
            {
                "startup_seconds": 2.0,
                "workload_seconds": 5.0,
            },
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["measurements"]["startup_seconds"]["status"], "fail")
        self.assertEqual(result["measurements"]["workload_seconds"]["status"], "pass")
        self.assertIn("startup_seconds 3.0s exceeded 2.0s", result["failures"])

    def test_condition_workload_exercises_local_surfaces_without_native_sync_claim(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-proving-test-") as tmp:
            result = gate.run_condition_workload(
                workspace=Path(tmp) / "repo",
                python_exe=sys.executable,
                host=gate.DEFAULT_HOST,
                duration_seconds=0.2,
                iterations=1,
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["checks"]["filesystem_mutations_created"])
        self.assertTrue(result["checks"]["developer_agentic_command_exit_zero"])
        self.assertTrue(result["checks"]["loopback_port_opened"])
        self.assertTrue(result["checks"]["loopback_network_round_trips"])
        self.assertTrue(result["checks"]["sync_like_mirror_updated"])
        self.assertFalse(result["sync_like"]["native_provider_claimed"])
        self.assertGreaterEqual(result["duration_seconds"], result["requested_duration_seconds"])

    def test_duration_restart_schedule_and_workload_iterations_support_sixty_minute_gate(self):
        self.assertEqual(gate._restart_schedule(3600, 900), [900.0, 1800.0, 2700.0, 3600.0])
        self.assertEqual(gate._restart_schedule(0, 0), [0.0])
        self.assertGreaterEqual(gate._workload_iterations_for_duration(900, gate.DEFAULT_WORKLOAD_ITERATIONS), 180)
        self.assertEqual(gate._workload_iterations_for_duration(900, 7), 7)

    def test_readiness_measurement_reports_p95_against_budget(self):
        report = gate._readiness_measurement_report(
            [
                {"label": "startup", "readiness_ms": 20, "status_separation": "ok"},
                {"label": "restart-1", "readiness_ms": 30, "status_separation": "ok"},
                {"label": "restart-2", "readiness_ms": 40, "status_separation": "ok"},
            ],
            readiness_budget_ms=250,
        )

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["p95_under_budget"])
        self.assertEqual(report["p95_ms"], 40)
        self.assertEqual(gate.PROVING_READINESS_P95_BUDGET_MS, 250.0)

    def test_script_contract_is_no_browser_api_proof(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "production_readiness_proving_run.py"
        content = script.read_text(encoding="utf-8")

        self.assertIn("No-browser CleanHouse production-readiness proving run", content)
        self.assertIn("--duration-seconds", content)
        self.assertIn("--restart-interval-seconds", content)
        self.assertIn("continuous_workload", content)
        self.assertIn('"browser_automation_used": False', content)
        self.assertIn('"method": "http-api"', content)
        self.assertNotIn("playwright", content.lower())
        self.assertNotIn("selenium", content.lower())
        self.assertNotIn("webbrowser", content.lower())


if __name__ == "__main__":
    unittest.main()
