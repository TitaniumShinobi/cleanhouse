import os
import tempfile
import unittest
from pathlib import Path

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
from corefiles import config


class QpbMediatorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmp_data = tempfile.TemporaryDirectory()
        self._tmp_repo = tempfile.TemporaryDirectory()
        self._old_data_dir = config.DATA_DIR
        config.DATA_DIR = Path(self._tmp_data.name) / "data"
        os.environ["CLEANHOUSE_NATIVE_NOTIFICATIONS"] = "0"
        self.repo_root = Path(self._tmp_repo.name)

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        self._tmp_data.cleanup()
        self._tmp_repo.cleanup()

    def test_qpb_requires_purge_confirmation_and_bless_after_purge(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        target = self.repo_root / "wipe.txt"
        target.write_text("danger", encoding="utf-8")

        created = adapter.create_qpb_case({
            "session_id": "session-qpb",
            "target_scope": {"paths": ["wipe.txt"]},
            "metadata": {"repo_path": str(self.repo_root)},
        })
        self.assertEqual(created["status"], "ok")
        case_id = created["case"]["id"]

        quarantined = adapter.advance_qpb_case(case_id, "quarantine", {"actor": "test"})
        self.assertEqual(quarantined["status"], "ok")
        self.assertEqual(quarantined["case"]["status"], "quarantined")

        pending = adapter.advance_qpb_case(case_id, "purge", {"actor": "test", "repo_path": str(self.repo_root)})
        self.assertEqual(pending["status"], "ok")
        self.assertEqual(pending["case"]["status"], "purge_pending")
        self.assertTrue(target.exists())

        purged = adapter.advance_qpb_case(
            case_id,
            "purge",
            {"actor": "test", "confirm": True, "repo_path": str(self.repo_root)},
        )
        self.assertEqual(purged["status"], "ok")
        self.assertEqual(purged["case"]["status"], "purged")
        self.assertFalse(target.exists())

        blessed = adapter.advance_qpb_case(case_id, "bless", {"actor": "test"})
        self.assertEqual(blessed["status"], "ok")
        self.assertEqual(blessed["case"]["status"], "blessed")

    def test_mediator_apply_and_undo_roundtrip(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        target = self.repo_root / "notes.txt"
        target.write_text("before", encoding="utf-8")

        created = adapter.create_operation_proposal({
            "session_id": "session-med",
            "proposal_type": "mediator",
            "reason": "update notes",
            "operations": [{"op": "write_file", "path": "notes.txt", "content": "after"}],
            "metadata": {"repo_path": str(self.repo_root)},
        })
        self.assertEqual(created["status"], "ok")
        proposal_id = created["proposal"]["id"]

        approved = adapter.resolve_operation_proposal(
            proposal_id,
            "approve",
            {"confirm": True, "repo_path": str(self.repo_root)},
        )
        self.assertEqual(approved["status"], "ok")
        self.assertEqual(approved["proposal"]["status"], "applied")
        self.assertEqual(target.read_text(encoding="utf-8"), "after")

        undone = adapter.undo_operation_proposal(proposal_id, {"repo_path": str(self.repo_root)})
        self.assertEqual(undone["status"], "ok")
        self.assertEqual(undone["proposal"]["status"], "undone")
        self.assertEqual(target.read_text(encoding="utf-8"), "before")

    def test_settings_accept_new_groups(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        result = adapter.update_settings({
            "automation": {"qpb_enabled": True, "auto_adjust_enabled": False},
            "qpb_policy": {"purge_requires_confirmation": True, "purge_confidence_min": 0.9},
            "mediator": {"default_mode": "suggest_confirm", "undo_enabled": True, "approval_timeout_seconds": 600},
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["settings"]["qpb_policy"]["purge_confidence_min"], 0.9)

    def test_standalone_incident_receipt_decision_path(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        target = self.repo_root / "incident.txt"
        target.write_text("suspicious", encoding="utf-8")
        process_ref = "local://cleanhouse/process/agentd-999999"
        mutation_ref = "local://cleanhouse/mutation/incident-txt"
        deviation_ref = "local://cleanhouse/deviation/runtime-policy-match"

        runtime_incident = adapter.emit_domain_event({
            "domain": "agent_firewall",
            "surface": "port_monitor",
            "event_type": "process_file_integrity_suspicion",
            "session_id": "session-incident",
            "severity": "warning",
            "actor": {"type": "process", "pid": 999999, "process": "agentd"},
            "resource": {"path": "incident.txt", "process_pid": 999999},
            "observed_vs_expected": {"status": "observed", "details": "unexpected outbound connection with file mutation"},
            "evidence_refs": [process_ref, mutation_ref, deviation_ref],
        })
        self.assertEqual(runtime_incident["status"], "ok")
        incident_id = runtime_incident["incident"]["id"]

        created = adapter.create_standalone_incident_receipt({
            "session_id": "session-incident",
            "repo_path": str(self.repo_root),
            "incident_id": incident_id,
            "force_new": True,
        })
        self.assertEqual(created["status"], "ok")
        card = created["card"]
        case_id = card["qpb_case"]["id"]
        self.assertEqual(card["qpb_case"]["status"], "detected")
        self.assertTrue(card["incident"])
        self.assertEqual(card["incident"]["id"], incident_id)
        self.assertFalse(card["qpb_case"]["metadata"].get("synthetic", True))
        self.assertIn(process_ref, card["evidence"]["refs"])
        self.assertIn(mutation_ref, card["evidence"]["refs"])
        self.assertIn(deviation_ref, card["evidence"]["refs"])
        self.assertTrue(target.exists())

        quarantined = adapter.advance_standalone_incident_receipt(case_id, "quarantine", {"actor": "test"})
        self.assertEqual(quarantined["status"], "ok")
        self.assertEqual(quarantined["card"]["qpb_case"]["status"], "quarantined")

        pending = adapter.advance_standalone_incident_receipt(
            case_id,
            "purge",
            {"actor": "test", "repo_path": str(self.repo_root)},
        )
        self.assertEqual(pending["status"], "ok")
        self.assertEqual(pending["card"]["qpb_case"]["status"], "purge_pending")
        self.assertTrue(target.exists())

        purged = adapter.advance_standalone_incident_receipt(
            case_id,
            "purge",
            {"actor": "test", "confirm": True, "repo_path": str(self.repo_root)},
        )
        self.assertEqual(purged["status"], "ok")
        self.assertEqual(purged["card"]["qpb_case"]["status"], "purged")
        self.assertFalse(target.exists())

        blessed = adapter.advance_standalone_incident_receipt(case_id, "bless", {"actor": "test"})
        self.assertEqual(blessed["status"], "ok")
        self.assertEqual(blessed["card"]["qpb_case"]["status"], "blessed")
        outcome = blessed["card"]["outcome"]
        self.assertEqual(outcome["status"], "blessed")
        self.assertTrue(outcome["integrity_root_hash"])
        resolved = adapter.get_incident_cases(session_id="session-incident")
        incident_rows = [row for row in resolved["incidents"] if row.get("id") == incident_id]
        self.assertEqual(len(incident_rows), 1)
        self.assertEqual(incident_rows[0]["status"], "resolved")
        outcomes = adapter.action_outcome_audit(limit=50)
        actions = [row for row in outcomes["outcomes"] if row.get("incident_id") == incident_id]
        self.assertTrue(any(row.get("action") == "review" for row in actions))
        self.assertTrue(any(row.get("action") == "resolve" for row in actions))

    def test_standalone_incident_receipt_requires_runtime_incident(self):
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        created = adapter.create_standalone_incident_receipt({
            "session_id": "session-no-runtime-incident",
            "repo_path": str(self.repo_root),
            "force_new": True,
        })
        self.assertEqual(created["status"], "error")
        self.assertIn("no runtime incident available", created["message"])


if __name__ == "__main__":
    unittest.main()
