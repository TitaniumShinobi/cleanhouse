import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def _load_gate_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "gate_a_observability.py"
    spec = importlib.util.spec_from_file_location("gate_a_observability", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


class GateAObservabilityTests(unittest.TestCase):
    def test_filesystem_watcher_dependency_gap_is_visible(self):
        with patch.object(gate.cleanhouse_events, "FileSystemEventHandler", None), patch.object(
            gate.cleanhouse_events, "Observer", None
        ):
            result = gate.verify_filesystem_watcher(timeout_seconds=0.1)

        self.assertEqual(result["name"], "filesystem_watcher")
        self.assertEqual(result["status"], "gap")
        self.assertTrue(result["visible_gap"])
        self.assertEqual(result["collector_status"], "dependency_missing")
        self.assertEqual(result["watcher_status"]["status"], "unavailable")

    def test_process_snapshot_gate_uses_existing_process_monitor_shape(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                self.show_all = show_all

            def get_processes(self):
                return [
                    {
                        "pid": "123",
                        "ppid": "1",
                        "user": "dev",
                        "cpu": 1.2,
                        "mem": 0.4,
                        "command": "python worker.py",
                        "start_time": "Mon May 25 11:22:33 2026",
                        "args": "python worker.py",
                        "source_command": "python worker.py",
                    }
                ]

        result = gate.verify_process_snapshot(monitor_factory=ProcessMonitorStub)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["coverage_proven"])
        self.assertEqual(result["collector_status"], "ok")
        self.assertEqual(result["process_count"], 1)
        self.assertTrue(result["lineage_fields_present"])
        self.assertEqual(result["sample_pid"], "123")

    def test_process_snapshot_reports_partial_gap_when_probe_is_missing(self):
        class ProcessMonitorStub:
            def __init__(self, show_all=True):
                self.show_all = show_all

            def get_processes(self):
                return [
                    {
                        "pid": "123",
                        "ppid": "1",
                        "user": "dev",
                        "cpu": 1.2,
                        "mem": 0.4,
                        "command": "python worker.py",
                        "start_time": "Mon May 25 11:22:33 2026",
                        "args": "python worker.py",
                        "source_command": "python worker.py",
                    }
                ]

        probe = {"pid": "999", "marker": gate.PROCESS_PROBE_MARKER}
        with patch.object(gate, "_local_process_probe", return_value=contextlib.nullcontext(probe)):
            result = gate.verify_process_snapshot(
                monitor_factory=ProcessMonitorStub,
                probe_process=True,
            )

        self.assertEqual(result["status"], "gap")
        self.assertFalse(result["coverage_proven"])
        self.assertTrue(result["visible_gap"])
        self.assertEqual(result["collector_status"], "probe_not_observed")
        self.assertEqual(result["probe_pid"], "999")

    def test_data_flow_tracer_records_network_port_snapshot_and_delta(self):
        from corefiles.collectors.data_flow_tracer import DataFlowTracer

        lsof_output = (
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "curl 777 dev 3u IPv4 0xabc 0t0 TCP 203.0.113.2:53122->198.51.100.8:443\n"
            "python 778 dev 4u IPv4 0xdef 0t0 TCP 127.0.0.1:3333\n"
        )
        completed = SimpleNamespace(returncode=0, stdout=lsof_output)
        tracer = DataFlowTracer(monitor_duration=1)

        with patch("corefiles.collectors.data_flow_tracer.platform.system", return_value="Darwin"), patch(
            "corefiles.collectors.data_flow_tracer.subprocess.run", return_value=completed
        ), patch.object(
            tracer, "resolve_ip_to_domain", return_value="api.example.test"
        ), patch.object(
            tracer, "get_process_info", return_value={"pid": "777", "command": "curl", "user": "dev"}
        ):
            tracer.scan_network_connections()

        ports = {conn["port"] for conn in tracer.trace_data["network_connections"]}
        self.assertEqual(ports, {443, 3333})
        self.assertEqual(len(tracer.trace_data["network_snapshots"]), 1)
        self.assertEqual(tracer.trace_data["network_deltas"][0]["counts"]["opened"], 2)
        snapshot = tracer.trace_data["network_snapshots"][0]
        self.assertEqual(snapshot["keys"], sorted(snapshot["keys"]))
        self.assertTrue(all("snapshot_key" in conn for conn in snapshot["connections"].values()))

    def test_network_port_gate_reports_visible_gap_without_ports(self):
        class DataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                self.monitor_duration = monitor_duration
                self.trace_data = {
                    "network_connections": [],
                    "network_snapshots": [{"keys": [], "connections": {}, "unknown": []}],
                    "network_deltas": [],
                }

            def scan_network_connections(self):
                pass

        result = gate.verify_network_port_snapshot(tracer_factory=DataFlowTracerStub)

        self.assertEqual(result["name"], "network_port_snapshot")
        self.assertEqual(result["status"], "gap")
        self.assertFalse(result["coverage_proven"])
        self.assertTrue(result["visible_gap"])
        self.assertEqual(result["collector_status"], "no_ports_observed")

    def test_network_port_gate_requires_local_probe_port_when_enabled(self):
        class DataFlowTracerStub:
            def __init__(self, monitor_duration=1):
                self.monitor_duration = monitor_duration
                self.trace_data = {
                    "network_connections": [
                        {
                            "pid": "777",
                            "process": "Python",
                            "host": "127.0.0.1",
                            "port": 4444,
                            "address": "127.0.0.1:4444",
                        }
                    ],
                    "network_snapshots": [{"keys": ["sample"], "connections": {}, "unknown": []}],
                    "network_deltas": [],
                }

            def scan_network_connections(self):
                pass

        probe = {"host": "127.0.0.1", "port": 5555, "pid": "777"}
        with patch.object(gate, "_local_tcp_probe", return_value=contextlib.nullcontext(probe)):
            result = gate.verify_network_port_snapshot(
                tracer_factory=DataFlowTracerStub,
                local_probe=True,
            )

        self.assertEqual(result["status"], "gap")
        self.assertFalse(result["coverage_proven"])
        self.assertTrue(result["visible_gap"])
        self.assertEqual(result["collector_status"], "probe_port_not_observed")
        self.assertEqual(result["probe_port"], 5555)

    def test_unsupported_and_runtime_gap_behavior_is_visible(self):
        class AdapterStub:
            def __init__(self, cache_ttl_seconds=0.0):
                self.cache_ttl_seconds = cache_ttl_seconds

            def _build_collector_manifest(self):
                return {
                    "surfaces": {
                        "filesystem_watcher": {
                            "status": "unavailable",
                            "collector_status": "dependency_missing",
                        },
                        "event_writer": {
                            "status": "stopped",
                            "collector_status": "inactive",
                        },
                    }
                }

            def _runtime_gaps_from_manifest(self, manifest):
                return [
                    {
                        "source": "filesystem_watcher",
                        "collector_status": "dependency_missing",
                        "evidence_refs": ["local://cleanhouse/collector/filesystem_watcher"],
                    },
                    {
                        "source": "event_writer",
                        "collector_status": "inactive",
                        "evidence_refs": ["local://cleanhouse/collector/event_writer"],
                    }
                ]

            def get_cloud_usage(self, refresh=False):
                return {
                    "data": {
                        "cloud_usage_adapters": [
                            {
                                "provider": "aws",
                                "status": "unsupported",
                                "observed_indicators": [],
                                "limitation": "No AWS usage indicators observed. Credential values not inspected in v1.",
                            }
                        ]
                    }
                }

        result = gate.verify_unsupported_gap_visibility(adapter_factory=AdapterStub)

        self.assertEqual(result["status"], "gap")
        self.assertFalse(result["coverage_proven"])
        self.assertTrue(result["visible_gap"])
        self.assertEqual(result["collector_status"], "native_runtime_gaps_visible")
        self.assertTrue(result["runtime_gap_visibility_proven"])
        self.assertEqual(result["unsupported_count"], 1)
        self.assertEqual(result["runtime_gap_count"], 2)
        self.assertEqual(result["filesystem_watcher_status"], "dependency_missing")
        self.assertEqual(result["runtime_gaps"][0]["truth_label"], "unsupported")
        self.assertEqual(result["runtime_gaps"][1]["truth_label"], "partial")

    def test_unsupported_cloud_adapters_without_runtime_gap_do_not_force_partial(self):
        class AdapterStub:
            def __init__(self, cache_ttl_seconds=0.0):
                self.cache_ttl_seconds = cache_ttl_seconds

            def _build_collector_manifest(self):
                return {
                    "surfaces": {
                        "filesystem_watcher": {
                            "status": "running",
                            "collector_status": "ok",
                        },
                        "event_writer": {
                            "status": "running",
                            "collector_status": "ok",
                        },
                    }
                }

            def _runtime_gaps_from_manifest(self, manifest):
                return []

            def get_cloud_usage(self, refresh=False):
                return {
                    "data": {
                        "cloud_usage_adapters": [
                            {
                                "provider": "aws",
                                "status": "unsupported",
                                "observed_indicators": [],
                                "limitation": "No AWS usage indicators observed. Credential values not inspected in v1.",
                            }
                        ]
                    }
                }

        result = gate.verify_unsupported_gap_visibility(adapter_factory=AdapterStub)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["coverage_proven"])
        self.assertEqual(result["unsupported_count"], 1)
        self.assertEqual(result["runtime_gap_count"], 0)

    def test_run_gate_reports_partial_when_visible_gaps_are_present(self):
        with patch.object(
            gate,
            "verify_filesystem_watcher",
            return_value=gate._component(
                "filesystem_watcher",
                "gap",
                collector_status="dependency_missing",
                visible_gap=True,
            ),
        ), patch.object(
            gate,
            "verify_process_snapshot",
            return_value=gate._component("process_snapshot", "pass", collector_status="ok"),
        ), patch.object(
            gate,
            "verify_network_port_snapshot",
            return_value=gate._component("network_port_snapshot", "pass", collector_status="ok"),
        ), patch.object(
            gate,
            "verify_unsupported_gap_visibility",
            return_value=gate._component(
                "unsupported_gap_visibility",
                "pass",
                collector_status="ok",
            ),
        ):
            result = gate.run_gate()

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage_status"], "partial")
        self.assertEqual(len(result["visible_gaps"]), 1)


if __name__ == "__main__":
    unittest.main()
