from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.api import cleanhouse


class NetworkTrendInterpretationTests(unittest.TestCase):
    def setUp(self) -> None:
        with cleanhouse._NETWORK_PROJECTION_CACHE_LOCK:
            cleanhouse._NETWORK_PROJECTION_CACHE.clear()

    def test_rules_preserve_contradictory_threat_and_strength_signals(self):
        result = cleanhouse._network_trend_interpretation_from_event({
            "event_id": "network:contradiction",
            "process": "Safari",
            "dst_ip": "203.0.113.9",
            "dst_port": "443",
            "tls_sni": "example.test",
            "protocol": "TLS",
            "confidence": "high",
            "suspicious": True,
            "severity": "warning",
            "collector_generation": 7,
        })

        self.assertEqual(result["schema"], "cleanhouse.network.trend.interpretation.v1")
        self.assertEqual(result["rule_version"], "network-trend-rationalization.v1")
        self.assertTrue(result["series"]["threats"]["matched"])
        self.assertTrue(result["series"]["strengths"]["matched"])
        self.assertTrue(result["contradictory"])
        self.assertEqual(result["capture_generation"], 7)
        self.assertEqual(result["source_event_id"], "network:contradiction")

    def test_unknown_cleartext_external_evidence_maps_to_vulnerability_without_inventing_strength(self):
        result = cleanhouse._network_trend_interpretation_from_event({
            "event_id": "network:vulnerability",
            "process": "Unknown app",
            "dst_ip": "203.0.113.10",
            "dst_port": "80",
            "protocol": "HTTP",
            "confidence": "low",
        })

        vulnerability = result["series"]["vulnerabilities"]
        self.assertTrue(vulnerability["matched"])
        self.assertIn("unknown_external_owner", vulnerability["signals"])
        self.assertIn("unresolved_external_destination", vulnerability["signals"])
        self.assertIn("cleartext_http", vulnerability["signals"])
        self.assertFalse(result["series"]["strengths"]["matched"])
        self.assertFalse(result["series"]["threats"]["matched"])

    def test_bucket_deduplicates_evidence_and_preserves_rule_provenance(self):
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        sample = {
            "source_event_id": "network:deduplicated",
            "event_id": "network:deduplicated",
            "timestamp": timestamp,
            "app": "Safari",
            "dst_ip": "203.0.113.11",
            "dst_port": "443",
            "tls_sni": "example.test",
            "protocol": "TLS",
            "confidence": "high",
            "suspicious": True,
            "collector_generation": 4,
            "evidence_refs": ["local://cleanhouse/network/network:deduplicated"],
        }

        buckets = cleanhouse._network_trend_interpretation_buckets("1m", [sample, dict(sample)])

        self.assertEqual(len(buckets), 1)
        bucket = buckets[0]
        self.assertEqual(bucket["evidence_count"], 1)
        self.assertEqual(bucket["contradiction_count"], 1)
        self.assertEqual(bucket["capture_generations"], [4])
        self.assertEqual(bucket["related_event_ids"], ["network:deduplicated"])
        self.assertEqual(bucket["rule_version"], "network-trend-rationalization.v1")
        self.assertEqual(bucket["interpretation"]["threats"]["value"], 1)
        self.assertEqual(bucket["interpretation"]["strengths"]["value"], 1)
        self.assertEqual(bucket["interpretation"]["vulnerabilities"]["value"], 0)

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

    def test_projection_ignores_legacy_count_ticks_and_reports_missing_buckets_as_gaps(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        legacy_tick = {
            "event_id": "network_tick:legacy",
            "tick_id": "network_tick:legacy",
            "timestamp": now,
            "bucket_key": "tick:1m:legacy",
            "bucket_range": "1m",
            "connectionCount": 99,
        }
        with patch.object(cleanhouse, "_stored_network_trend_ticks", return_value=[legacy_tick]), patch.object(
            cleanhouse, "_vvault_network_trend_ticks", return_value=[]
        ), patch.object(cleanhouse, "_network_stored_observations", return_value=[]), patch.object(
            cleanhouse, "_vvault_network_trend_samples", return_value=[]
        ), patch.object(cleanhouse, "_network_vvault_readiness", return_value={"state": "unavailable", "authenticated": False}
        ), patch.object(cleanhouse.vvault_preservation, "preserve_network_timeline_gap") as preserve_gap:
            payload, status = cleanhouse._network_projection_trend("1m")

        self.assertEqual(status, 200)
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["summary"]["gap_count"], cleanhouse.NETWORK_TREND_BUCKETS["1m"])
        self.assertEqual(payload["summary"]["zero_means"], "observed_bucket_without_matching_signal")
        self.assertEqual(payload["summary"]["missing_means"], "no_retained_evidence_for_bucket")
        preserve_gap.assert_called_once()

    def test_factual_event_is_not_rewritten_by_interpretation(self):
        event = {
            "event_id": "network:immutable-fact",
            "process": "Safari",
            "dst_ip": "203.0.113.12",
            "dst_port": "443",
            "tls_sni": "example.test",
            "protocol": "TLS",
            "confidence": "high",
        }
        original = dict(event)

        cleanhouse._network_trend_interpretation_from_event(event)

        self.assertEqual(event, original)

    def test_enrichment_publishes_the_versioned_interpretation_without_replacing_facts(self):
        event = {
            "event_id": "network:enriched-fact",
            "process": "Safari",
            "dst_ip": "203.0.113.13",
            "dst_port": "443",
            "tls_sni": "example.test",
            "protocol": "TLS",
            "confidence": "high",
        }

        enriched = cleanhouse._network_apply_enrichment(event, {})
        public = cleanhouse._network_public_event(enriched)

        self.assertEqual(public["event_id"], event["event_id"])
        self.assertEqual(public["dst_ip"], event["dst_ip"])
        self.assertEqual(
            public["trend_interpretation"]["schema"],
            "cleanhouse.network.trend.interpretation.v1",
        )
        self.assertEqual(
            public["trend_interpretation"]["rule_version"],
            "network-trend-rationalization.v1",
        )


if __name__ == "__main__":
    unittest.main()
