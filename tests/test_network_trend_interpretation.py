from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.api import cleanhouse


ROOT = Path(__file__).resolve().parents[1]


class NetworkTrendGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        with cleanhouse._NETWORK_PROJECTION_CACHE_LOCK:
            cleanhouse._NETWORK_PROJECTION_CACHE.clear()

    def test_samples_aggregate_unique_connections_per_bucket(self):
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        samples = [
            {
                "event_id": "network:one",
                "timestamp": timestamp,
                "src_ip": "127.0.0.1",
                "src_port": "50001",
                "dst_ip": "203.0.113.10",
                "dst_port": "443",
                "protocol": "tcp",
            },
            {
                "event_id": "network:one-duplicate",
                "timestamp": timestamp,
                "src_ip": "127.0.0.1",
                "src_port": "50001",
                "dst_ip": "203.0.113.10",
                "dst_port": "443",
                "protocol": "tcp",
            },
            {
                "event_id": "network:two",
                "timestamp": timestamp,
                "src_ip": "127.0.0.1",
                "src_port": "50002",
                "dst_ip": "203.0.113.11",
                "dst_port": "443",
                "protocol": "tcp",
            },
        ]

        ticks = cleanhouse._network_trend_ticks_from_samples("1m", samples)

        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["connectionCount"], 2)
        self.assertEqual(len(ticks[0]["related_event_ids"]), 3)

    def test_five_second_range_retains_subsecond_bucket_resolution(self):
        _, start, end = cleanhouse._network_trend_bucket_key(
            "2026-10-16T12:00:00.900Z",
            "5s",
        )

        self.assertLess((end - start).total_seconds(), 1.0)
        self.assertAlmostEqual(
            (end - start).total_seconds(),
            int(cleanhouse.NETWORK_TIME_RANGES_MS["5s"] / cleanhouse.NETWORK_TREND_BUCKETS["5s"]) / 1000,
            places=3,
        )

    def test_projection_returns_count_ticks_and_explicit_gap_metadata(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        tick = {
            "event_id": "network_tick:accepted",
            "tick_id": "network_tick:accepted",
            "timestamp": now,
            "bucket_key": "tick:1m:accepted",
            "bucket_range": "1m",
            "bucket_start": now,
            "connectionCount": 7,
        }
        with patch.object(cleanhouse, "_stored_network_trend_ticks", return_value=[tick]), patch.object(
            cleanhouse, "_vvault_network_trend_ticks", return_value=[]
        ), patch.object(cleanhouse, "_network_stored_observations", return_value=[]), patch.object(
            cleanhouse, "_vvault_network_trend_samples", return_value=[]
        ), patch.object(cleanhouse, "_stored_network_buckets", return_value=[]), patch.object(
            cleanhouse, "_vvault_network_buckets", return_value=[]
        ), patch.object(
            cleanhouse, "_network_vvault_readiness", return_value={"state": "unavailable", "authenticated": False}
        ):
            payload, status = cleanhouse._network_projection_trend("1m")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["events"]), cleanhouse.NETWORK_TREND_BUCKETS["1m"])
        observed = [item for item in payload["events"] if not item.get("gap")]
        gaps = [item for item in payload["events"] if item.get("gap")]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["connectionCount"], 7)
        self.assertTrue(all(item["value"] is None for item in gaps))
        self.assertEqual(payload["summary"]["measurement"], "observed_connection_count")
        self.assertEqual(payload["summary"]["zero_means"], "observed_bucket_with_zero_connections")
        self.assertEqual(payload["summary"]["missing_means"], "no_retained_evidence_for_bucket")
        self.assertGreaterEqual(payload["summary"]["gap_count"], 0)

    def test_public_event_does_not_embed_trend_interpretation(self):
        event = {
            "event_id": "network:factual",
            "process": "Safari",
            "dst_ip": "203.0.113.12",
            "dst_port": "443",
            "protocol": "TLS",
        }

        public = cleanhouse._network_public_event(event)

        self.assertEqual(public["event_id"], event["event_id"])
        self.assertNotIn("trend_interpretation", public)

    def test_frontend_restores_graph_and_chart_duplicate_navigation(self):
        source = (ROOT / "frontend/js/investigations.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend/investigations.html").read_text(encoding="utf-8")

        self.assertIn('data-network-graph-view="bar"', html)
        self.assertIn('data-network-graph-view="pie"', html)
        self.assertIn("selectNetworkView(button.dataset.networkGraphView || 'bar');", source)
        self.assertIn("function renderNetworkBarGraph(events)", source)
        self.assertIn("aria-label=\"Network ' + escapeHtml(trendMetricLabel) + ' trend\"", source)
        self.assertNotIn("Interpreted Trend", source)
        self.assertNotIn("networkTrendDataset", source)


if __name__ == "__main__":
    unittest.main()
