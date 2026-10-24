from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.api import cleanhouse
from backend.network_collector import CaptureEngineUnavailable


class NetworkCaptureTruthTests(unittest.TestCase):
    def setUp(self):
        readiness = patch.object(
            cleanhouse,
            "_network_vvault_readiness",
            return_value={"state": "unavailable", "authenticated": False},
        )
        readiness.start()
        self.addCleanup(readiness.stop)

    def test_runtime_readiness_does_not_determine_capture_state(self):
        with patch.object(cleanhouse, "_runtime_readiness_payload", side_effect=AssertionError("must not be called")):
            self.assertEqual(cleanhouse._network_runtime_probe_state([]), "NO_DATA")
            self.assertEqual(cleanhouse._network_runtime_probe_state([{"event_id": "packet-1"}]), "CAPTURING")

    def test_collector_contract_distinguishes_lifecycle_failures(self):
        cases = [
            ({"state": "running", "last_packet_sequence": 0}, ("CAPTURING", "no_data")),
            ({"state": "starting"}, ("WARMING", "waiting_for_capture")),
            ({"state": "blocked", "reason_code": "capture_permission_blocked"}, ("CAPTURE_BLOCKED", "permission_blocked")),
            ({"state": "degraded", "reason_code": "capture_engine_unavailable"}, ("ERROR", "engine_unavailable")),
            ({"state": "degraded", "reason_code": "capture_failed"}, ("ERROR", "capture_failed")),
        ]
        for health, expected in cases:
            with self.subTest(health=health):
                self.assertEqual(cleanhouse._network_collector_contract(health), expected)

    def test_degraded_capture_preserves_retained_projection_evidence(self):
        payload, _status = cleanhouse._network_ui_contract(
            "CAPTURING",
            events=[{"event_id": "retained-finding"}],
            summary={"view": "findings", "source": "retained_event_spine"},
        )

        result = cleanhouse._network_apply_collector_truth(
            payload,
            {"state": "degraded", "reason_code": "capture_engine_unavailable"},
        )

        self.assertEqual(result["state"], "ERROR")
        self.assertEqual([item["event_id"] for item in result["events"]], ["retained-finding"])
        self.assertEqual(result["summary"]["capture_reason"], "engine_unavailable")
        self.assertEqual(result["summary"]["data_state"], "available")
        self.assertEqual(result["tags"]["status"], "OFFLINE")
        self.assertEqual(result["tags"]["state"], "DEGRADED")
        self.assertFalse(result["powered_by_wireshark"])

    def test_running_capture_with_delayed_source_evidence_is_truthfully_stale(self):
        payload, _status = cleanhouse._network_ui_contract("CAPTURING", events=[])

        result = cleanhouse._network_apply_collector_truth(
            payload,
            {
                "state": "running",
                "last_packet_sequence": 12,
                "ingestion_latency_ms": cleanhouse.NETWORK_CAPTURE_STALE_AFTER_MS + 1,
            },
        )

        self.assertEqual(result["state"], "CAPTURING")
        self.assertEqual(result["summary"]["capture_reason"], "capture_backlog")
        self.assertEqual(result["summary"]["data_state"], "stale")
        self.assertEqual(result["tags"]["state"], "DEGRADED")
        self.assertEqual(result["tags"]["reasons"], ["Capture engine limited"])

    def test_wireshark_branding_requires_running_capture_and_packet_evidence(self):
        payload, _status = cleanhouse._network_ui_contract("CAPTURING", events=[{"event_id": "packet-1"}])
        result = cleanhouse._network_apply_collector_truth(
            payload,
            {"state": "running", "last_packet_sequence": 1},
        )
        self.assertTrue(result["powered_by_wireshark"])

    def test_snapshot_reports_engine_unavailable_even_when_runtime_is_ready(self):
        collector = Mock()
        collector.snapshot.return_value = {
            "cursor": "boot:1",
            "high_water_cursor": "boot:1",
            "high_water_sequence": 1,
        }
        with patch.object(cleanhouse, "_get_network_collector", return_value=collector), patch.object(
            cleanhouse, "_network_events_in_range", return_value=[]
        ), patch.object(cleanhouse, "_network_active_connection_count", return_value=4), patch.object(
            cleanhouse,
            "network_collector_health",
            return_value={"state": "degraded", "reason_code": "capture_engine_unavailable"},
        ), patch.object(cleanhouse, "_runtime_readiness_payload", return_value={"runtime_state": "healthy"}):
            payload, status = cleanhouse._network_snapshot_payload()

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "ERROR")
        self.assertEqual(payload["summary"]["capture_reason"], "engine_unavailable")
        self.assertEqual(payload["summary"]["counts"]["os_active_connections"], 4)
        self.assertEqual(payload["events"], [])

    def test_absent_reviewed_bundle_raises_typed_engine_unavailable(self):
        engine_error = cleanhouse._network_error_contract("engine_unavailable", status_code=400)
        with patch.object(cleanhouse, "_bundled_wireshark_engine_interfaces", return_value=([], engine_error)):
            with self.assertRaises(CaptureEngineUnavailable):
                cleanhouse._network_collector_command_factory()

    def test_distribution_uses_packet_evidence_not_socket_inventory(self):
        packet = {"event_id": "packet-1", "process": "Example", "timestamp": "2026-10-15T12:00:00Z"}
        with patch.object(cleanhouse, "_network_events_in_range", return_value=[packet]) as packet_history, \
             patch.object(cleanhouse, "_network_running_app_summary", return_value=[]), \
             patch.object(cleanhouse, "_network_active_socket_events", side_effect=AssertionError("socket inventory is not distribution evidence")):
            payload, status = cleanhouse._network_projection_distribution("1m")

        self.assertEqual(status, 200)
        packet_history.assert_called_once()
        self.assertEqual(payload["summary"]["source"], "retained_packet_evidence")
        self.assertEqual(payload["summary"]["measurement_basis"], "packet_supported_communications")
        self.assertEqual([item["event_id"] for item in payload["events"]], ["packet-1"])

    def test_distribution_open_applications_are_sanitized_and_separate(self):
        running = [{
            "id": "app:safari",
            "name": "Safari",
            "category": "network",
            "path": "/Applications/Safari.app",
            "processes": [{"pid": 123, "command": "/Applications/Safari.app/Contents/MacOS/Safari"}],
        }]
        with patch.object(cleanhouse, "_network_app_identity_index", return_value=({}, running)):
            summary = cleanhouse._network_running_app_summary([])

        self.assertEqual(summary, [{
            "app_id": "app:safari",
            "name": "Safari",
            "category": "network",
            "observed_network_events": 0,
            "source": "applications_running_gui_inventory",
        }])

    def test_distribution_reuses_collector_application_inventory_cache(self):
        cached = [{"bundle_id": "app:safari", "name": "Safari", "category": "network"}]
        with cleanhouse._NETWORK_RUNNING_APPS_LOCK:
            previous_apps = cleanhouse._NETWORK_RUNNING_APPS
            previous_at = cleanhouse._NETWORK_RUNNING_APPS_AT
            cleanhouse._NETWORK_RUNNING_APPS = cached
            cleanhouse._NETWORK_RUNNING_APPS_AT = cleanhouse.time.monotonic()
        self.addCleanup(setattr, cleanhouse, "_NETWORK_RUNNING_APPS", previous_apps)
        self.addCleanup(setattr, cleanhouse, "_NETWORK_RUNNING_APPS_AT", previous_at)

        with patch.object(
            cleanhouse,
            "_network_app_identity_index",
            side_effect=AssertionError("fresh collector inventory cache must be reused"),
        ):
            summary = cleanhouse._network_running_app_summary([])

        self.assertEqual(summary[0]["app_id"], "app:safari")

    def test_recent_authentic_packets_feed_projections_without_waiting_for_history(self):
        packet = {
            "event_id": "packet-live-1",
            "process": "Safari",
            "timestamp": cleanhouse._now_iso(),
            "severity": "low",
            "dst_ip": "203.0.113.2",
            "dst_port": "443",
        }
        with cleanhouse._NETWORK_RECENT_OBSERVATIONS_LOCK:
            cleanhouse._NETWORK_RECENT_OBSERVATIONS.clear()
            cleanhouse._NETWORK_RECENT_OBSERVATIONS.append(packet)
        self.addCleanup(self._clear_recent_observations)

        with patch.object(cleanhouse, "_network_stored_observations", return_value=[]):
            visible = cleanhouse._network_events_in_range("1m", enrich_unknown=False)

        self.assertEqual([item["event_id"] for item in visible], ["packet-live-1"])

    def test_recent_short_window_does_not_block_on_large_stored_history(self):
        packet = {
            "event_id": "packet-live-fast",
            "process": "Safari",
            "timestamp": cleanhouse._now_iso(),
            "dst_ip": "203.0.113.2",
            "dst_port": "443",
        }
        with cleanhouse._NETWORK_RECENT_OBSERVATIONS_LOCK:
            cleanhouse._NETWORK_RECENT_OBSERVATIONS.clear()
            cleanhouse._NETWORK_RECENT_OBSERVATIONS.append(packet)
        self.addCleanup(self._clear_recent_observations)

        with patch.object(cleanhouse, "_network_stored_observations", side_effect=AssertionError("short live window must not hit retained history")):
            visible = cleanhouse._network_events_in_range("1m", enrich_unknown=False)

        self.assertEqual([item["event_id"] for item in visible], ["packet-live-fast"])

    def test_long_window_bounds_retained_history_query(self):
        observed = []

        def retained(limit, *, start=None, end=None):
            observed.append((limit, start, end))
            return []

        with patch.object(cleanhouse, "_network_stored_observations", side_effect=retained):
            visible = cleanhouse._network_events_in_range(
                "30m",
                limit=cleanhouse._network_projection_history_limit("30m"),
            )

        self.assertEqual(visible, [])
        self.assertEqual(observed[0][0], cleanhouse._network_projection_history_limit("30m"))
        self.assertIsNotNone(observed[0][1])
        self.assertIsNotNone(observed[0][2])
        self.assertLess(observed[0][1], observed[0][2])

    def test_stored_history_uses_bounded_index_read_before_window_filter(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"event_type": cleanhouse.NETWORK_OBSERVATION_EVENT_TYPE, "source_surface": "network", "timestamp": (now - timedelta(minutes=5)).isoformat()},
            {"event_type": cleanhouse.NETWORK_OBSERVATION_EVENT_TYPE, "source_surface": "network", "timestamp": now.isoformat()},
            {"event_type": cleanhouse.NETWORK_OBSERVATION_EVENT_TYPE, "source_surface": "network", "timestamp": (now + timedelta(seconds=1)).isoformat()},
        ]
        with patch.object(cleanhouse.events, "list_events", return_value=rows) as list_events:
            visible = cleanhouse._network_stored_event_rows(
                cleanhouse.NETWORK_OBSERVATION_EVENT_TYPE,
                limit=200,
                start=now - timedelta(minutes=1),
                end=now + timedelta(seconds=1),
            )

        self.assertEqual(visible, [rows[1]])
        self.assertEqual(list_events.call_args.kwargs["limit"], 200)
        self.assertEqual(list_events.call_args.kwargs["source_surface"], "network")
        self.assertNotIn("start_timestamp", list_events.call_args.kwargs)
        self.assertNotIn("end_timestamp", list_events.call_args.kwargs)

    def test_projection_history_limits_remain_bounded_for_every_window(self):
        limits = {
            key: cleanhouse._network_projection_history_limit(key)
            for key in cleanhouse.NETWORK_TIME_RANGES_MS
        }

        self.assertEqual(limits["5s"], 250)
        self.assertEqual(limits["1m"], 500)
        self.assertEqual(limits["30m"], 1000)
        self.assertTrue(all(limit <= 1500 for limit in limits.values()))

    def test_collector_enrichment_refresh_is_bounded(self):
        cleanhouse._NETWORK_COLLECTOR_ENRICHMENT = {}
        cleanhouse._NETWORK_COLLECTOR_ENRICHMENT_AT = 0.0
        event = {"event_id": "packet-cache", "dst_ip": "203.0.113.2", "dst_port": "443"}

        with patch.object(cleanhouse, "_network_enrichment_index", return_value={"remote:203.0.113.2:443": {"process": "Safari"}}) as build:
            first = cleanhouse._network_collector_enrich_event(event)
            second = cleanhouse._network_collector_enrich_event(event)

        self.assertEqual(build.call_count, 1)
        self.assertEqual(first["process"], "Safari")
        self.assertEqual(second["process"], "Safari")

    def test_recent_trend_samples_count_unique_connections_per_bucket(self):
        timestamp = cleanhouse._now_iso()
        samples = [
            {"event_id": "packet-a", "timestamp": timestamp, "process": "Safari", "src_ip": "10.0.0.2", "src_port": "5000", "dst_ip": "203.0.113.2", "dst_port": "443"},
            {"event_id": "packet-b", "timestamp": timestamp, "process": "Safari", "src_ip": "10.0.0.2", "src_port": "5000", "dst_ip": "203.0.113.2", "dst_port": "443"},
            {"event_id": "packet-c", "timestamp": timestamp, "process": "Mail", "src_ip": "10.0.0.2", "src_port": "5001", "dst_ip": "203.0.113.3", "dst_port": "443"},
        ]

        ticks = cleanhouse._network_trend_ticks_from_samples("1m", samples)

        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["connectionCount"], 2)
        self.assertEqual(len(ticks[0]["related_event_ids"]), 3)

    def test_collector_commits_durable_outbox_before_bounded_event_spine_queue(self):
        event = {
            "event_id": "packet-durable-order",
            "timestamp": cleanhouse._now_iso(),
            "process": "Safari",
            "dst_ip": "203.0.113.2",
            "dst_port": "443",
        }
        envelope = {"type": "network.event", "sequence": 1, "cursor": "boot:1", "event": event}
        calls = []
        cleanhouse._NETWORK_CANONICAL_EVENT_IDS_INITIALIZED = False
        cleanhouse._NETWORK_CANONICAL_EVENT_IDS.clear()
        self.addCleanup(setattr, cleanhouse, "_NETWORK_CANONICAL_EVENT_IDS_INITIALIZED", False)
        self.addCleanup(cleanhouse._NETWORK_CANONICAL_EVENT_IDS.clear)
        self.addCleanup(self._clear_recent_observations)

        with patch.object(cleanhouse, "_network_stored_observations", return_value=[]), patch.object(
            cleanhouse,
            "_enqueue_network_vvault_sync",
            side_effect=lambda _event: calls.append("durable_outbox") or True,
        ), patch.object(
            cleanhouse,
            "_enqueue_network_live_persistence",
            side_effect=lambda _event: calls.append("event_spine_queue") or True,
        ):
            result = cleanhouse._persist_network_collector_event(envelope)

        self.assertEqual(calls, ["durable_outbox", "event_spine_queue"])
        self.assertEqual(result["event"]["event_id"], event["event_id"])
        with cleanhouse._NETWORK_RECENT_OBSERVATIONS_LOCK:
            self.assertEqual(cleanhouse._NETWORK_RECENT_OBSERVATIONS[-1]["event_id"], event["event_id"])

    def test_timeline_does_not_promote_routine_info_packets(self):
        packet = {
            "event_id": "packet-routine-1",
            "process": "Python",
            "timestamp": cleanhouse._now_iso(),
            "severity": "info",
            "dst_ip": "127.0.0.1",
            "dst_port": "3333",
        }
        with patch.object(cleanhouse, "_network_projection_cache_get", return_value=None), \
             patch.object(cleanhouse, "_network_events_in_range", return_value=[packet]), \
             patch.object(cleanhouse, "_stored_network_timeline_notables", return_value=[]), \
             patch.object(cleanhouse, "_vvault_network_timeline_notables", return_value=[]), \
             patch.object(cleanhouse, "_stored_network_timeline_gaps", return_value=[]), \
             patch.object(cleanhouse, "_vvault_network_timeline_gaps", return_value=[]), \
             patch.object(cleanhouse, "_network_projection_cache_set"):
            payload, status = cleanhouse._network_projection_timeline("1m")

        self.assertEqual(status, 200)
        self.assertEqual(payload["events"], [])

    def _clear_recent_observations(self):
        with cleanhouse._NETWORK_RECENT_OBSERVATIONS_LOCK:
            cleanhouse._NETWORK_RECENT_OBSERVATIONS.clear()


if __name__ == "__main__":
    unittest.main()
