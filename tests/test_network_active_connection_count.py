import unittest
from unittest.mock import Mock, patch

from backend.api import cleanhouse


class NetworkActiveConnectionCountTests(unittest.TestCase):
    def test_snapshot_reports_macos_lsof_connection_count_separately_from_rows(self):
        collector = Mock()
        collector.snapshot.return_value = {
            "cursor": "boot:9",
            "high_water_cursor": "boot:9",
            "high_water_sequence": 9,
        }
        stored_rows = [
            {"event_id": "packet-a", "timestamp": "2026-07-12T18:00:00Z"},
            {"event_id": "packet-b", "timestamp": "2026-07-12T18:00:01Z"},
        ]
        socket_rows = [
            {"socket_role": "connection"},
            {"socket_role": "listener"},
            {"socket_role": "connection"},
            {"socket_role": "socket"},
            {"socket_role": "connection"},
        ]

        with patch.object(cleanhouse, "_get_network_collector", return_value=collector), patch.object(
            cleanhouse, "_network_events_in_range", return_value=stored_rows
        ), patch.object(cleanhouse, "_network_active_socket_events", return_value=socket_rows), patch.object(
            cleanhouse, "network_collector_health", return_value={"state": "running"}
        ), patch.object(
            cleanhouse, "_network_vvault_readiness", return_value={"state": "unavailable", "authenticated": False}
        ):
            payload, status = cleanhouse._network_snapshot_payload()

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["summary"]["counts"]["connections"], 2)
        self.assertEqual(payload["summary"]["counts"]["os_active_connections"], 3)
        self.assertEqual(payload["summary"]["active_connection_source"], "macos_lsof")


if __name__ == "__main__":
    unittest.main()
