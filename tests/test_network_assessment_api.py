from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.api import cleanhouse
from backend.evidence_context import network_distribution_owner_id
from backend.security_assessments import assess_network_event


def _packet(event_id: str, *, timestamp: str | None = None, process: str = "Example") -> dict:
    return {
        "event_id": event_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "process": process,
        "direction": "outbound_external",
        "dst_ip": "203.0.113.8",
        "dns_query": "example.test",
        "destination_display": "example.test",
        "dst_port": 443,
        "protocol": "tcp",
        "severity": "warning",
    }


class NetworkAssessmentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        with cleanhouse._NETWORK_PROJECTION_CACHE_LOCK:
            cleanhouse._NETWORK_PROJECTION_CACHE.clear()
        readiness = patch.object(
            cleanhouse,
            "_network_vvault_readiness",
            return_value={"state": "unavailable", "authenticated": False},
        )
        readiness.start()
        self.addCleanup(readiness.stop)

    def test_posture_does_not_reclassify_operational_header(self):
        packet = _packet("packet-unknown", process="Unknown app")
        payload, _status = cleanhouse._network_ui_contract("CAPTURING", events=[packet])
        payload = cleanhouse.add_assessment_contract(payload, [packet])

        self.assertEqual(payload["tags"]["state"], "HEALTHY")
        self.assertEqual(payload["tags"]["reasons"], [])
        self.assertEqual(payload["assessment_summary"]["counts"]["vulnerabilities"], 1)
        self.assertEqual(payload["assessment_summary"]["counts"]["threats"], 0)

    def test_header_reuses_retained_findings_posture_without_changing_health(self):
        retained = cleanhouse.add_assessment_contract(
            {},
            [_packet("packet-retained") | {"encryption_verified": True}],
        )
        target = {
            "state": "ERROR",
            "tags": {"status": "OFFLINE", "state": "DEGRADED"},
            "summary": {"capture_reason": "engine_unavailable"},
        }
        with patch.object(
            cleanhouse,
            "_network_projection_findings",
            return_value=(retained, 200),
        ):
            result = cleanhouse._network_apply_retained_posture(target)

        self.assertEqual(result["state"], "ERROR")
        self.assertEqual(result["tags"], target["tags"])
        self.assertEqual(result["summary"], target["summary"])
        self.assertEqual(result["assessment_refs"], retained["assessment_refs"])
        self.assertEqual(result["assessment_summary"], retained["assessment_summary"])

    def test_gap_only_projection_is_no_data_not_available(self):
        payload, _status = cleanhouse._network_ui_contract(
            "NO_DATA",
            events=[{
                "event_id": "gap:one",
                "timestamp": "2026-10-17T00:00:01Z",
                "coverage_state": "gap",
                "gap": True,
            }],
            summary={"view": "trend", "reason": "projection"},
        )

        result = cleanhouse._network_apply_collector_truth(
            payload,
            {"state": "running", "last_packet_sequence": 0},
        )

        self.assertEqual(result["summary"]["data_state"], "no_data")
        self.assertEqual(result["summary"]["reason"], "no_data")

    def test_distribution_donut_and_owner_list_use_one_packet_dataset(self):
        packets = [
            _packet("packet-a", process="Safari"),
            _packet("packet-b", process="Safari"),
            _packet("packet-c", process="Mail"),
        ]
        with patch.object(cleanhouse, "_network_events_in_range", return_value=packets), patch.object(
            cleanhouse,
            "_network_running_app_summary",
            side_effect=AssertionError("GUI inventory is not Distribution evidence"),
        ):
            payload, status = cleanhouse._network_projection_distribution("1m")

        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["owners"], payload["summary"]["open_applications"])
        self.assertEqual(payload["summary"]["classified_apps"], {"Safari": 2, "Mail": 1})
        self.assertTrue(all(item["source"] == "retained_packet_evidence" for item in payload["summary"]["owners"]))
        safari = next(item for item in payload["summary"]["owners"] if item["name"] == "Safari")
        self.assertEqual(safari["owner_id"], network_distribution_owner_id("Safari"))
        self.assertEqual(len(safari["evidence_refs"]), 2)
        self.assertEqual(safari["assessment_refs"], [])

    def test_findings_assessments_use_full_retained_window(self):
        strength = _packet("packet-strength") | {"encryption_verified": True, "severity": "info"}
        assessment_id = assess_network_event(strength)[0][0]["assessment_id"]
        with patch.object(cleanhouse, "_network_retained_events", return_value=[strength]), patch.object(
            cleanhouse, "_network_findings_cache_get", return_value=None
        ), patch.object(cleanhouse, "_network_findings_cache_set"):
            payload, status = cleanhouse._network_projection_findings("12mo")

        self.assertEqual(status, 200)
        self.assertEqual(payload["events"], [])
        self.assertIn(assessment_id, payload["assessment_refs"])
        self.assertEqual(payload["assessment_summary"]["counts"]["strengths"], 1)

    def test_snapshot_persistence_attaches_canonical_assessment_identity(self):
        packet = _packet("packet-snapshot") | {"encryption_verified": True}
        expected_id = assess_network_event(packet)[0][0]["assessment_id"]
        with patch.object(cleanhouse.events, "insert_event"), patch.object(
            cleanhouse, "persist_network_assessment_transitions"
        ) as transitions:
            result = cleanhouse._persist_network_observation(
                packet,
                {},
                persist_trend=False,
                check_existing=False,
                enqueue_vvault=False,
            )

        self.assertIn(expected_id, result["assessment_refs"])
        self.assertEqual(result["assessments"][0]["category"], "strength")
        transitions.assert_called_once()
        self.assertIn(expected_id, transitions.call_args.args[0]["assessment_refs"])

    def test_assessment_contract_exposes_rule_and_coverage_truth(self):
        packet = _packet("packet-covered") | {"encryption_verified": True}
        gap = {
            "event_id": "gap:one",
            "event_type": "network_timeline_gap",
            "timestamp": packet["timestamp"],
            "coverage_state": "gap",
            "gap": True,
        }
        payload = cleanhouse.add_assessment_contract({}, [packet, gap], metric="strengths")

        self.assertEqual(payload["assessment_rule_version"], "network-assessment-rules.v1")
        self.assertEqual(payload["assessment_coverage"], {
            "state": "partial",
            "retained_event_count": 2,
            "assessed_event_count": 1,
            "gap_count": 1,
        })
        self.assertEqual(payload["assessment_gap"]["present"], True)
        self.assertEqual(payload["assessment_gap"]["evidence_refs"], ["gap:one"])

    def test_same_assessment_identity_crosses_network_projections(self):
        now = datetime.now(timezone.utc)
        packet = _packet(
            "packet-parity",
            timestamp=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        ) | {"encryption_verified": True}
        assessment_id = assess_network_event(packet)[0][0]["assessment_id"]
        header = cleanhouse.add_assessment_contract({}, [packet])
        trend = cleanhouse.add_assessment_contract({}, [packet], metric="strengths")
        with patch.object(cleanhouse, "_network_retained_events", return_value=[packet]), patch.object(
            cleanhouse, "_network_findings_cache_get", return_value=None
        ), patch.object(cleanhouse, "_network_findings_cache_set"):
            findings, _ = cleanhouse._network_projection_findings("12mo")
        with patch.object(cleanhouse, "_network_events_in_range", return_value=[packet]):
            distribution, _ = cleanhouse._network_projection_distribution("1m")
        with patch.object(cleanhouse, "_network_projection_cache_get", return_value=None), patch.object(
            cleanhouse, "_network_projection_window", return_value=(now - timedelta(minutes=1), now)
        ), patch.object(cleanhouse, "_network_events_in_range", return_value=[packet]), patch.object(
            cleanhouse, "_stored_network_timeline_notables", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_timeline_notables", return_value=[]), patch.object(
            cleanhouse, "_stored_network_timeline_gaps", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_timeline_gaps", return_value=[]), patch.object(
            cleanhouse, "_network_stored_assessment_transitions", return_value=[]
        ), patch.object(cleanhouse, "_network_projection_cache_set"):
            timeline, _ = cleanhouse._network_projection_timeline("1m")
        with patch.object(cleanhouse.events, "insert_event"), patch.object(
            cleanhouse, "persist_network_assessment_transitions"
        ):
            connection = cleanhouse._persist_network_observation(
                packet,
                {},
                persist_trend=False,
                check_existing=False,
                enqueue_vvault=False,
            )

        for projection in (header, trend, findings, distribution, timeline):
            self.assertIn(assessment_id, projection["assessment_refs"])
        self.assertIn(assessment_id, connection["assessment_refs"])
        owner = distribution["summary"]["owners"][0]
        self.assertIn(assessment_id, owner["assessment_refs"])
        self.assertIn("local://cleanhouse/network/packet-parity", owner["evidence_refs"])

    def test_timeline_retains_each_event_and_canonical_transition(self):
        now = datetime.now(timezone.utc)
        first = _packet("packet-a", timestamp=(now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"))
        second = _packet("packet-b", timestamp=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))
        transition = assess_network_event({**first, "malicious_endpoint_verified": True})[0][-1]
        with patch.object(cleanhouse, "_network_projection_cache_get", return_value=None), patch.object(
            cleanhouse, "_network_projection_window", return_value=(now - timedelta(minutes=1), now)
        ), patch.object(cleanhouse, "_network_events_in_range", return_value=[first, second]), patch.object(
            cleanhouse, "_stored_network_timeline_notables", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_timeline_notables", return_value=[]), patch.object(
            cleanhouse, "_stored_network_timeline_gaps", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_timeline_gaps", return_value=[]), patch.object(
            cleanhouse, "_network_stored_assessment_transitions", return_value=[transition]
        ), patch.object(cleanhouse, "_network_projection_cache_set"):
            payload, status = cleanhouse._network_projection_timeline("1m")

        self.assertEqual(status, 200)
        event_ids = {item["event_id"] for item in payload["events"]}
        self.assertIn("packet-a", event_ids)
        self.assertIn("packet-b", event_ids)
        self.assertTrue(any(item.startswith("assessment-transition:") for item in event_ids))
        self.assertIn(transition["assessment_id"], payload["assessment_refs"])

    def test_category_trend_preserves_covered_zero_and_gap(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start = now - timedelta(seconds=2)
        covered = {
            "event_id": "tick:covered",
            "bucket_start": start.isoformat().replace("+00:00", "Z"),
            "bucket_end": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "timestamp": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "coverage_state": "observed",
            "gap": False,
            "connectionCount": 0,
        }
        gap = {
            "event_id": "tick:gap",
            "bucket_start": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "bucket_end": now.isoformat().replace("+00:00", "Z"),
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "coverage_state": "gap",
            "gap": True,
            "connectionCount": None,
        }
        transition = assess_network_event(_packet(
            "packet-strength",
            timestamp=(start - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        ) | {"encryption_verified": True})[0][-1]
        with patch.object(cleanhouse, "_network_projection_cache_get", return_value=None), patch.object(
            cleanhouse, "_network_projection_window", return_value=(start, now)
        ), patch.object(cleanhouse, "_network_retention_start", return_value=start - timedelta(days=1)), patch.object(
            cleanhouse, "_stored_network_buckets", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_buckets", return_value=[]), patch.object(
            cleanhouse, "_stored_network_trend_ticks", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_trend_ticks", return_value=[]), patch.object(
            cleanhouse, "_network_stored_observations", return_value=[]
        ), patch.object(cleanhouse, "_vvault_network_trend_samples", return_value=[]), patch.object(
            cleanhouse, "_network_complete_trend_geometry", return_value=[covered, gap]
        ), patch.object(cleanhouse, "_network_stored_assessment_transitions", return_value=[transition]), patch.object(
            cleanhouse.vvault_preservation, "preserve_network_timeline_gap"
        ), patch.object(cleanhouse, "_network_projection_cache_set"):
            payload, status = cleanhouse._network_projection_trend("1m", metric="strengths")

        self.assertEqual(status, 200)
        self.assertEqual([item["value"] for item in payload["events"]], [1, None])
        self.assertEqual(payload["summary"]["coverage_state"], "partial")
        self.assertEqual(payload["summary"]["observed_bucket_count"], 1)
        self.assertEqual(payload["summary"]["zero_means"], "observed_bucket_with_no_active_assessments")
        self.assertIn(transition["assessment_id"], payload["assessment_refs"])


if __name__ == "__main__":
    unittest.main()
