from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from backend import network_runtime


class NetworkRuntimeTests(unittest.TestCase):
    def tearDown(self):
        with patch.object(network_runtime, "_persist_envelope", side_effect=lambda item: item):
            network_runtime.stop_network_collector_service(timeout=0.5)
        network_runtime.stop_network_history_service()

    def test_default_runtime_is_explicitly_degraded_without_reviewed_engine(self):
        with patch.object(network_runtime, "_persist_envelope", side_effect=lambda item: item):
            status = network_runtime.start_network_collector_service(startup_timeout=0.5)

        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["reason_code"], "capture_engine_unavailable")
        self.assertEqual(status["last_packet_sequence"], 0)
        self.assertTrue(status["thread_alive"])

    def test_history_uses_only_existing_local_event_spine(self):
        with patch.object(network_runtime.events, "init_db") as init_db:
            status = network_runtime.start_network_history_service()

        init_db.assert_called_once_with()
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["retention"], "local_event_spine")
        self.assertEqual(network_runtime.network_history_status(), status)

    def test_persistence_writes_local_event_spine_before_fanout(self):
        envelope = {
            "type": "network.event",
            "cursor": "boot:1",
            "event": {"state": "observed", "payload": "bounded"},
        }
        with patch.object(network_runtime.events, "insert_event") as insert_event:
            result = network_runtime._persist_envelope(envelope)

        self.assertIs(result, envelope)
        kwargs = insert_event.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "network_packet")
        self.assertEqual(kwargs["source_surface"], "network_collector")
        self.assertEqual(kwargs["provider"], "network_core")
        self.assertEqual(kwargs["source_event_key"], "network-core:boot:1:network.event")


class NetworkServerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os

        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "0"
        from backend import server

        cls.server = server

    def setUp(self):
        self.server._EVENTS_SERVICES_STARTED = False

    def _run_startup(
        self,
        *,
        watcher=None,
        history=None,
        collector=None,
        heartbeat=None,
    ):
        watcher = watcher or Mock(return_value={"status": "running"})
        history = history or Mock(return_value={"status": "running", "reason_code": ""})
        collector = collector or Mock(return_value={"status": "running", "reason_code": ""})
        heartbeat = heartbeat or Mock()
        completion = Mock()
        with patch.dict(os.environ, {
            "CLEANHOUSE_NETWORK_COLLECTOR_AUTOSTART": "1",
            "CLEANHOUSE_NETWORK_HISTORY_ENABLED": "1",
        }), patch.object(
            self.server, "_wait_for_listener_ready", return_value=True
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_bootstrap_ready"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_started"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_complete", completion
        ), patch.object(
            self.server.cleanhouse_events, "init_db"
        ), patch.object(
            self.server.cleanhouse_events, "start_watcher", watcher
        ), patch.object(
            self.server.vvault_sync,
            "start_service",
            return_value={"sync_state": "unavailable", "status": "unavailable"},
        ), patch.object(
            self.server.wazuh_files,
            "start_service",
            return_value={"configured": False, "health": "unavailable", "operational": False},
        ), patch.object(
            self.server, "start_network_history_service", history
        ), patch.object(
            self.server, "start_network_collector_service", collector
        ), patch.object(
            self.server, "_start_runtime_heartbeat", heartbeat
        ):
            self.server._start_events_services()
        return completion.call_args.kwargs, watcher, history, collector, heartbeat

    def test_missing_engine_degrades_network_without_blocking_runtime_warmup(self):
        result, _, _, _, _ = self._run_startup(
            collector=Mock(
                return_value={
                    "status": "degraded",
                    "reason_code": "capture_engine_unavailable",
                }
            )
        )

        self.assertEqual(result["runtime_state"], "healthy")
        self.assertNotIn("network_capture_engine_unavailable", result["reason_codes"])
        self.assertEqual(
            result["details"]["network_collector"]["reason_code"],
            "capture_engine_unavailable",
        )
        self.assertEqual(
            result["details"]["network_collector"]["runtime_impact"],
            "subsystem_degraded",
        )

    def test_watcher_failure_does_not_skip_network_or_heartbeat(self):
        result, _, history, collector, heartbeat = self._run_startup(
            watcher=Mock(side_effect=RuntimeError("watcher failed"))
        )

        history.assert_called_once_with()
        collector.assert_called_once_with()
        heartbeat.assert_called_once_with()
        self.assertIn("filesystem_watcher_start_failed", result["reason_codes"])

    def test_history_failure_does_not_skip_collector_or_heartbeat(self):
        result, _, _, collector, heartbeat = self._run_startup(
            history=Mock(side_effect=RuntimeError("history failed"))
        )

        collector.assert_called_once_with()
        heartbeat.assert_called_once_with()
        self.assertIn("network_history_start_failed", result["reason_codes"])

    def test_collector_failure_does_not_skip_heartbeat(self):
        result, _, history, _, heartbeat = self._run_startup(
            collector=Mock(side_effect=RuntimeError("collector failed"))
        )

        history.assert_called_once_with()
        heartbeat.assert_called_once_with()
        self.assertIn("network_collector_start_failed", result["reason_codes"])

    def test_shutdown_is_ordered_and_exception_isolated(self):
        calls = []

        def collector_stop(**_kwargs):
            calls.append("collector")
            raise RuntimeError("collector stop failed")

        with patch.object(self.server.wazuh_files, "stop_service"), patch.object(
            self.server.vvault_sync, "stop_service"
        ), patch.object(
            self.server, "stop_network_collector_service", side_effect=collector_stop
        ), patch.object(
            self.server, "stop_network_history_service", side_effect=lambda: calls.append("history")
        ), patch.object(
            self.server.cleanhouse_events, "stop_events_services", side_effect=lambda: calls.append("events")
        ), patch.object(
            self.server.runtime_supervisor,
            "stop_backend_heartbeat",
            side_effect=lambda *_args: calls.append("heartbeat"),
        ):
            self.server._stop_events_services()

        self.assertEqual(calls, ["collector", "history", "events", "heartbeat"])


if __name__ == "__main__":
    unittest.main()
