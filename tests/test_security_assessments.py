from __future__ import annotations

import unittest

from backend.security_assessments import (
    ASSESSMENT_SCHEMA,
    RULE_REGISTRY_VERSION,
    active_assessment_series,
    assess_network_event,
    assess_network_events,
    persist_network_assessment_transitions,
)


def _event(**overrides):
    value = {
        "event_id": "event-1",
        "timestamp": "2026-10-16T22:00:00Z",
        "process": "Example",
        "direction": "outbound_external",
        "dst_ip": "203.0.113.8",
        "destination_display": "example.test",
        "dns_query": "example.test",
        "dst_port": 443,
        "protocol": "tcp",
        "collector_cursor": "cursor-1",
        "generation": 4,
    }
    value.update(overrides)
    return value


class SecurityAssessmentClassificationTests(unittest.TestCase):
    def test_unknown_app_missing_destination_and_unusual_port(self):
        assessments, indicators = assess_network_event(_event(
            process="Unknown app",
            destination_display="",
            dns_query="",
            http_host="",
            tls_sni="",
            dst_port=31337,
            unusual_port=True,
        ))
        self.assertEqual(
            {item["rule_id"] for item in assessments},
            {
                "network.unknown_external_application",
                "network.destination_identity_missing",
            },
        )
        self.assertEqual([item["category"] for item in assessments], ["vulnerability", "vulnerability"])
        self.assertEqual(len(indicators), 1)
        self.assertEqual(indicators[0]["kind"], "unusual_port")
        self.assertEqual(indicators[0]["classification"], "neutral")

    def test_port_443_alone_is_not_encryption_strength(self):
        assessments, _ = assess_network_event(_event(dst_port=443))
        self.assertNotIn("strength", {item["category"] for item in assessments})

    def test_verified_encryption_is_strength(self):
        assessments, _ = assess_network_event(_event(encryption_verified=True))
        strength = next(item for item in assessments if item["rule_id"] == "network.encryption_verified")
        self.assertEqual(strength["category"], "strength")
        self.assertEqual(strength["severity"], "informational")

    def test_verified_malicious_endpoint_is_threat_and_strength_can_coexist(self):
        assessments, _ = assess_network_event(_event(
            encryption_verified=True,
            malicious_endpoint_verified=True,
        ))
        self.assertEqual({item["category"] for item in assessments}, {"strength", "threat"})

    def test_scary_free_text_is_not_verified_threat(self):
        assessments, indicators = assess_network_event(_event(
            reason="verified malicious endpoint exfiltration quarantine bypass",
            summary="malware detected",
        ))
        self.assertNotIn("threat", {item["category"] for item in assessments})
        self.assertEqual(indicators, [])

    def test_unverified_detector_flags_are_not_threats(self):
        assessments, _ = assess_network_event(_event(
            known_malicious=True,
            malware_detected=True,
            exfiltration_detected=True,
            unauthorized_inbound=True,
            exploit_detected=True,
            quarantine_bypass=True,
        ))
        self.assertNotIn("threat", {item["category"] for item in assessments})

    def test_capture_failure_is_operational_only(self):
        assessments, indicators = assess_network_event(_event(
            reason="capture_engine_unavailable",
            event_type="collector.failure",
            known_malicious=True,
        ))
        self.assertEqual(assessments, [])
        self.assertEqual(indicators, [])

    def test_malformed_or_missing_event_time_never_mints_current_assessment(self):
        for timestamp in (None, "not-a-timestamp", ""):
            with self.subTest(timestamp=timestamp):
                assessments, indicators = assess_network_event(_event(
                    timestamp=timestamp,
                    malicious_endpoint_verified=True,
                ))
                self.assertEqual(assessments, [])
                self.assertEqual(indicators, [])

    def test_wire_contract_has_flat_canonical_fields_and_nested_aliases(self):
        assessments, _ = assess_network_event(_event(encryption_verified=True))
        item = next(value for value in assessments if value["category"] == "strength")
        self.assertEqual(item["schema"], ASSESSMENT_SCHEMA)
        self.assertEqual(item["rule_version"], RULE_REGISTRY_VERSION)
        self.assertEqual(item["rule_id"], item["rule"]["id"])
        self.assertEqual(item["assessment_state"], item["lifecycle"])
        self.assertEqual(item["owner_disposition"], item["disposition"])
        self.assertEqual(item["subject_type"], item["subject"]["type"])
        self.assertEqual(item["subject_id"], item["subject"]["id"])
        self.assertEqual(item["source_cursor"], item["cursor"])

    def test_identity_dedup_and_evidence_refs_are_bounded(self):
        first = _event(
            process="Unknown app",
            evidence_refs=[f"local://ref/{index}" for index in range(80)],
        )
        second = _event(
            event_id="event-2",
            timestamp="2026-10-16T22:00:02Z",
            collector_cursor="cursor-2",
            process="Unknown app",
            evidence_refs=["local://ref/extra"],
        )
        assessments, _ = assess_network_events([first, second])
        item = next(value for value in assessments if value["category"] == "vulnerability")
        self.assertEqual(item["first_seen"], "2026-10-16T22:00:00Z")
        self.assertEqual(item["last_seen"], "2026-10-16T22:00:02Z")
        self.assertLessEqual(len(item["evidence_refs"]), 32)

    def test_aggregation_is_replay_order_independent(self):
        first = _event(
            process="Unknown app",
            timestamp="2026-10-16T22:00:00Z",
            collector_cursor="cursor-1",
        )
        second = _event(
            event_id="event-2",
            process="Unknown app",
            timestamp="2026-10-16T22:00:02Z",
            collector_cursor="cursor-2",
        )
        forward = assess_network_events([first, second, dict(first)])
        reverse = assess_network_events([second, first, dict(second)])
        self.assertEqual(forward, reverse)

    def test_transition_persistence_is_append_only_and_bound_to_raw_evidence(self):
        writes = []
        assessments = persist_network_assessment_transitions(
            _event(encryption_verified=True),
            insert_event=lambda **kwargs: writes.append(kwargs),
        )
        self.assertEqual(len(writes), len(assessments))
        self.assertTrue(all(item["event_type"] == "security_assessment_transition" for item in writes))
        self.assertTrue(all(item["evidence_level"] == "derived" for item in writes))
        self.assertTrue(all(item["source_event_key"].startswith("network-assessment-transition:") for item in writes))

    def test_transition_persistence_prefers_attached_canonical_assessments(self):
        canonical = assess_network_event(_event(
            malicious_endpoint_verified=True,
        ))[0][-1]
        # This is the bounded public/writer envelope: it retains the canonical
        # assessment but no longer carries the private classifier input.
        bounded = _event()
        bounded["assessments"] = [canonical]
        writes = []

        persisted = persist_network_assessment_transitions(
            bounded,
            insert_event=lambda **kwargs: writes.append(kwargs),
        )

        self.assertEqual([item["assessment_id"] for item in persisted], [canonical["assessment_id"]])
        self.assertEqual(
            writes[0]["data"]["security_assessment"]["assessment_id"],
            canonical["assessment_id"],
        )
        self.assertEqual(writes[0]["data"]["security_assessment"]["category"], "threat")


class SecurityAssessmentTrendTests(unittest.TestCase):
    def test_pre_window_active_state_seeds_each_covered_bucket_and_resolves(self):
        base = assess_network_event(_event(
            timestamp="2026-10-16T21:59:00Z",
            malicious_endpoint_verified=True,
        ))[0][-1]
        resolved = dict(base)
        resolved.update({
            "last_seen": "2026-10-16T22:00:02Z",
            "lifecycle": "resolved",
            "assessment_state": "resolved",
            "source_cursor": "cursor-resolved",
        })
        buckets = [
            {
                "bucket_start": "2026-10-16T22:00:00Z",
                "bucket_end": "2026-10-16T22:00:02Z",
                "coverage_state": "observed",
                "connectionCount": 2,
            },
            {
                "bucket_start": "2026-10-16T22:00:02Z",
                "bucket_end": "2026-10-16T22:00:04Z",
                "coverage_state": "observed",
                "connectionCount": 0,
            },
        ]
        points = active_assessment_series(buckets, [base, resolved], metric="threats")
        self.assertEqual([point["value"] for point in points], [1, 0])
        self.assertEqual(points[0]["assessment_refs"], [base["assessment_id"]])
        self.assertEqual(points[1]["assessment_refs"], [])

    def test_replayed_transition_is_deduplicated(self):
        transition = assess_network_event(_event(malicious_endpoint_verified=True))[0][-1]
        points = active_assessment_series([
            {
                "bucket_start": "2026-10-16T22:00:00Z",
                "bucket_end": "2026-10-16T22:00:05Z",
                "coverage_state": "observed",
            },
        ], [transition, dict(transition)], metric="threats")
        self.assertEqual(points[0]["value"], 1)

    def test_quiet_covered_bucket_is_zero_and_gap_is_not_zero(self):
        buckets = [
            {
                "bucket_start": "2026-10-16T22:00:00Z",
                "bucket_end": "2026-10-16T22:00:02Z",
                "coverage_state": "observed",
                "connectionCount": 0,
            },
            {
                "bucket_start": "2026-10-16T22:00:02Z",
                "bucket_end": "2026-10-16T22:00:04Z",
                "coverage_state": "gap",
                "gap": True,
            },
        ]
        points = active_assessment_series(buckets, [], metric="vulnerabilities")
        self.assertEqual(points[0]["value"], 0)
        self.assertFalse(points[0]["gap"])
        self.assertIsNone(points[1]["value"])
        self.assertTrue(points[1]["gap"])

    def test_connections_metric_retains_existing_observed_count(self):
        points = active_assessment_series([
            {
                "bucket_start": "2026-10-16T22:00:00Z",
                "bucket_end": "2026-10-16T22:00:05Z",
                "coverage_state": "observed",
                "connectionCount": 7,
            },
        ], [], metric="connections")
        self.assertEqual(points[0]["value"], 7)

    def test_unsupported_metric_fails_closed(self):
        with self.assertRaises(ValueError):
            active_assessment_series([], [], metric="severity")


if __name__ == "__main__":
    unittest.main()
