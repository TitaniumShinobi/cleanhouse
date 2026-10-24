import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.api.cleanhouse_monitoring as monitoring_module
from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
from corefiles import config


class NotificationTruthHardeningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name) / "data"
        self._env = patch.dict(
            os.environ,
            {
                "CLEANHOUSE_DATA_ROOT": self._tmp.name,
                "CLEANHOUSE_NATIVE_NOTIFICATIONS": "0",
                "CLEANHOUSE_NOTIFICATION_DEBUG_MODE": "0",
                "CLEANHOUSE_NOTIFICATION_VALIDATION_MODE": "0",
                "CLEANHOUSE_NOTIFICATION_PROVING_MODE": "0",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        config.DATA_DIR = self._old_data_dir
        self._tmp.cleanup()

    def test_active_context_refresh_does_not_attach_without_attach_flag(self):
        class FakeCollector:
            def collect(self, *, follow_enabled, ignored_keys=(), explicit_pickup=None):
                return {
                    "id": "active_context:passive",
                    "dedupe_key": "k-passive",
                    "source_type": "clipboard",
                    "session_id": "passive-session",
                    "objective_id": "objective-passive",
                    "tool_identity": "codex",
                    "active_prompt": "Do something",
                    "attachable": True,
                    "evidence_refs": ["local://cleanhouse/active-context/active_context:passive"],
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._active_context_collector = FakeCollector()
        result = adapter.get_active_context(refresh=True)
        context = result["active_context"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(context["id"], "active_context:passive")
        self.assertFalse(bool(context.get("attached")))
        prompts = adapter.get_prompts(session_id="passive-session")["prompts"]
        self.assertEqual(prompts, [])

    def test_active_context_refresh_attach_true_allows_attach(self):
        class FakeCollector:
            def collect(self, *, follow_enabled, ignored_keys=(), explicit_pickup=None):
                return {
                    "id": "active_context:attach",
                    "dedupe_key": "k-attach",
                    "source_type": "clipboard",
                    "session_id": "attach-session",
                    "objective_id": "objective-attach",
                    "tool_identity": "codex",
                    "active_prompt": "Implement attach",
                    "context": "explicit attach",
                    "attachable": True,
                    "evidence_refs": ["local://cleanhouse/active-context/active_context:attach"],
                }

        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        adapter._active_context_collector = FakeCollector()
        result = adapter.get_active_context(refresh=True, attach=True)
        context = result["active_context"]
        self.assertTrue(bool(context.get("attached")))
        self.assertTrue(str(context.get("prompt_id", "")).startswith("prompt:"))

    def test_non_target_notifications_are_persist_only(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        created = adapter._ensure_operator_notification(
            notification_type="scope_drift_detected",
            session_id="scope-session",
            objective_id="objective-scope",
            severity="warning",
            summary="scope drift",
            evidence_refs=["local://cleanhouse/test/scope"],
            source="alert",
            metadata={"alert_id": "alert:scope"},
        )
        self.assertIsNotNone(created)
        metadata = created.metadata
        self.assertEqual(metadata.get("dispatch_class"), "persist_only")
        self.assertEqual(metadata.get("dispatch_suppressed_reason"), "non_target_notification_persist_only")
        self.assertEqual((metadata.get("native_delivery_result") or {}).get("status"), "skipped")

    def test_production_notification_requires_runtime_backing(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        created = adapter._ensure_operator_notification(
            notification_type="codex_prompt_sent",
            session_id="prompt-session",
            objective_id="objective-prompt",
            severity="info",
            summary="prompt sent",
            evidence_refs=["local://cleanhouse/test/prompt"],
            source="prompt",
            metadata={"tool_identity": "codex"},
        )
        self.assertIsNotNone(created)
        metadata = created.metadata
        self.assertEqual(metadata.get("dispatch_class"), "persist_only")
        self.assertEqual(metadata.get("dispatch_suppressed_reason"), "non_target_notification_persist_only")
        self.assertEqual((metadata.get("native_delivery_result") or {}).get("status"), "skipped")

    def test_incident_action_required_targets_incident_receipt(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        created = adapter._ensure_operator_notification(
            notification_type="incident_action_required",
            session_id="incident-session",
            objective_id="objective-incident",
            severity="critical",
            summary="incident action required",
            evidence_refs=["local://cleanhouse/test/incident"],
            source="policy_engine",
            metadata={
                "incident_id": "incident:abc123",
                "domain_event_id": "domain_event:abc123",
                "event_id": "domain_event:abc123",
            },
        )
        self.assertIsNotNone(created)
        metadata = created.metadata
        self.assertEqual(metadata.get("dispatch_class"), "persist_only")
        self.assertEqual(metadata.get("dispatch_suppressed_reason"), "non_target_notification_persist_only")
        click_url = str(metadata.get("click_url") or "")
        self.assertIn("/incident-receipt", click_url)
        self.assertIn("incident_id=incident%3Aabc123", click_url)
        self.assertIn("notification_id=", click_url)

    def test_probe_notifications_are_validation_only_by_default(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.send_test_operator_notification(
            session_id="probe-session",
            objective_id="objective-probe",
            notification_type="codex_prompt_sent",
            severity="info",
            summary="probe",
        )
        self.assertEqual(result.get("status"), "ok")
        notification = result["notification"]
        metadata = notification.get("metadata", {})
        self.assertEqual(metadata.get("dispatch_class"), "validation_only")
        self.assertEqual(metadata.get("dispatch_suppressed_reason"), "validation_notification_dispatch_disabled")


if __name__ == "__main__":
    unittest.main()
