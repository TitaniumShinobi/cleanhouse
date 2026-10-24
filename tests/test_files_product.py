import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import events
from backend.api import cleanhouse


class FilesProductTests(unittest.TestCase):
    def setUp(self):
        self._api_patches = [
            patch.object(
                cleanhouse,
                "jsonify",
                side_effect=lambda obj=None, **kwargs: obj if obj is not None else kwargs,
            ),
            patch.object(
                cleanhouse,
                "Response",
                side_effect=lambda *args, **kwargs: SimpleNamespace(
                    args=args,
                    kwargs=kwargs,
                    headers={},
                ),
            ),
            patch.object(cleanhouse, "stream_with_context", side_effect=lambda func: func),
        ]
        for api_patch in self._api_patches:
            api_patch.start()
        self._old_request = cleanhouse.request
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "events.db"
        self.old_db = os.environ.get("CLEANHOUSE_EVENTS_DB")
        self.old_integrity_db = os.environ.get("CLEANHOUSE_FILES_INTEGRITY_DB")
        self.old_outbox_db = os.environ.get("CLEANHOUSE_FILES_OUTBOX_DB")
        os.environ["CLEANHOUSE_EVENTS_DB"] = str(self.db_path)
        os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"] = str(Path(self.temp_dir.name) / "integrity.db")
        os.environ["CLEANHOUSE_FILES_OUTBOX_DB"] = str(Path(self.temp_dir.name) / "outbox.db")
        events._DB_INIT_STATE.clear()
        events.init_db()

    def tearDown(self):
        events._stop_db_writer()
        cleanhouse.request = self._old_request
        for api_patch in reversed(self._api_patches):
            api_patch.stop()
        self.temp_dir.cleanup()
        events._DB_INIT_STATE.clear()
        if self.old_db is None:
            os.environ.pop("CLEANHOUSE_EVENTS_DB", None)
        else:
            os.environ["CLEANHOUSE_EVENTS_DB"] = self.old_db
        if self.old_integrity_db is None:
            os.environ.pop("CLEANHOUSE_FILES_INTEGRITY_DB", None)
        else:
            os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"] = self.old_integrity_db
        if self.old_outbox_db is None:
            os.environ.pop("CLEANHOUSE_FILES_OUTBOX_DB", None)
        else:
            os.environ["CLEANHOUSE_FILES_OUTBOX_DB"] = self.old_outbox_db

    def test_snapshot_uses_watcher_events_and_aggregates_findings(self):
        protected = Path(self.temp_dir.name) / ".env"
        protected.write_text("TEST=1", encoding="utf-8")
        for index in range(5):
            events.insert_event(
                event_type="modified",
                path=str(protected),
                summary=f"modified pass {index}",
                timestamp=f"2026-08-20T00:00:0{index}+00:00",
                source_surface="filesystem_watcher",
                actor_type="collector",
                evidence_refs=[str(protected)],
                data={"watch_dir": self.temp_dir.name},
            )

        with patch.object(
            events, "get_watcher_status", return_value={"status": "running", "watch_dir": self.temp_dir.name}
        ), patch.object(
            cleanhouse.wazuh_files,
            "status",
            return_value={"configured": False, "powered_by_wazuh": False, "health": "unavailable"},
        ), patch.object(
            cleanhouse.vvault_sync, "status", return_value={"state": "unavailable", "pending": 0}
        ) as preservation_status:
            snapshot = cleanhouse._files_snapshot(200)

        self.assertTrue(snapshot["monitoring"]["always_on"])
        self.assertEqual(snapshot["schema"], "cleanhouse.files.v2")
        self.assertEqual(snapshot["collector"]["provider"], "watchdog")
        self.assertEqual(snapshot["monitoring"]["status"], "fallback")
        self.assertFalse(snapshot["powered_by_wazuh"])
        self.assertFalse(snapshot["collector"]["package_verified"])
        self.assertFalse(snapshot["collector"]["package_signature_verified"])
        self.assertEqual(len(snapshot["events"]), 5)
        categories = {finding["category"] for finding in snapshot["findings"]}
        self.assertIn("protected-change", categories)
        self.assertIn("rapid-churn", categories)
        self.assertGreater(snapshot["attention_count"], 0)
        preservation_status.assert_called_once_with(surface="files")

    def test_snapshot_explains_unavailable_fallback_observer(self):
        watcher_error = {
            "source": "watcher_observer_exit",
            "message": "watchdog observer terminated unexpectedly",
        }
        with patch.object(
            events,
            "get_watcher_status",
            return_value={
                "status": "stopped",
                "collector_status": "error",
                "watch_dir": self.temp_dir.name,
                "last_error": watcher_error,
            },
        ), patch.object(
            cleanhouse.wazuh_files,
            "status",
            return_value={"configured": False, "powered_by_wazuh": False, "health": "unavailable"},
        ), patch.object(
            cleanhouse.vvault_sync, "status", return_value={"state": "unavailable", "pending": 0}
        ):
            snapshot = cleanhouse._files_snapshot(200)

        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["collector"]["provider"], "none")
        self.assertFalse(snapshot["collector"]["fallback"]["active"])
        self.assertEqual(snapshot["collector"]["fallback_reason"], "watcher_observer_exit")
        self.assertEqual(snapshot["collector"]["fallback"]["last_error"], watcher_error)

    def test_mediation_state_is_folded_from_append_only_events(self):
        mediation_id = "a" * 32
        common = {
            "mediation_id": mediation_id,
            "request": "Verify the changed file",
            "scope": "all",
            "evidence_names": [],
            "created_at": "2026-08-20T00:00:00+00:00",
        }
        events.insert_event(
            event_type="file_mediation_queued",
            path=f"/files/mediations/{mediation_id}",
            summary=common["request"],
            source_surface="files_mediation",
            data={**common, "status": "queue"},
        )
        events.insert_event(
            event_type="file_mediation_in_progress",
            path=f"/files/mediations/{mediation_id}",
            summary=common["request"],
            source_surface="files_mediation",
            data={**common, "status": "in_progress"},
        )

        folded = cleanhouse._fold_file_mediations(
            events.list_events(limit=20, source_surface="files_mediation")
        )
        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["status"], "in_progress")
        self.assertEqual(folded[0]["execution_state"], "unavailable_until_zaelith")

    def test_mediation_transition_returns_immutable_nonexecuting_receipt(self):
        cleanhouse.request = SimpleNamespace(
            args={},
            headers={},
            get_json=lambda silent=True: {
                "request": "Review the changed file",
                "scope": "all",
                "evidence_names": ["wazuh-index://alerts/1"],
            },
        )
        patches = (
            patch.object(events, "get_watcher_status", return_value={"status": "stopped", "watch_dir": self.temp_dir.name}),
            patch.object(cleanhouse.wazuh_files, "status", return_value={"configured": False, "powered_by_wazuh": False}),
            patch.object(cleanhouse.vvault_sync, "status", return_value={"state": "unavailable", "pending": 0}),
            patch.object(cleanhouse.vvault_sync, "enqueue", return_value={"status": "queued"}),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            queued, status_code = cleanhouse.queue_file_mediation()
            mediation_id = queued["mediation"]["id"]
            cleanhouse.request = SimpleNamespace(
                args={}, headers={}, get_json=lambda silent=True: {"status": "in_progress"}
            )
            transitioned = cleanhouse.transition_file_mediation(mediation_id)

        receipt = transitioned["transition_receipt"]
        self.assertEqual(status_code, 201)
        self.assertEqual(receipt["from"], "queue")
        self.assertEqual(receipt["to"], "in_progress")
        self.assertEqual(receipt["execution_state"], "unavailable_until_zaelith")
        self.assertTrue(receipt["id"].startswith("files-mediation:"))

    def test_attention_acknowledgement_is_append_only_and_removes_badge_count(self):
        protected = Path(self.temp_dir.name) / ".env"
        events.insert_event(
            event_type="modified",
            path=str(protected),
            summary="modified protected file",
            source_surface="filesystem_watcher",
            provider="watchdog",
            evidence_refs=[str(protected)],
        )
        cleanhouse.request = SimpleNamespace(
            args={},
            headers={
                "Origin": "http://localhost:3333",
                "Sec-Fetch-Site": "same-origin",
                "X-CleanHouse-Intent": "files-attention-acknowledge",
            },
            get_json=lambda silent=True: {"all": True},
        )
        with patch.dict(os.environ, {"CLEANHOUSE_ENABLE_AUTH": "0"}), patch.object(
            events, "get_watcher_status", return_value={"status": "running", "watch_dir": self.temp_dir.name}
        ), patch.object(
            cleanhouse.wazuh_files, "status", return_value={"configured": False, "powered_by_wazuh": False}
        ), patch.object(
            cleanhouse.vvault_sync, "status", return_value={"state": "unavailable", "pending": 0}
        ), patch.object(cleanhouse.vvault_sync, "enqueue", return_value={"status": "queued"}):
            before = cleanhouse._files_snapshot(200)
            response = cleanhouse.acknowledge_files_attention()

        self.assertGreater(before["attention_count"], 0)
        self.assertEqual(response["snapshot"]["attention_count"], 0)
        self.assertTrue(response["receipt"]["id"].startswith("files-attention:"))

    def test_sse_reconnect_emits_fresh_state_and_collector_only_changes(self):
        cleanhouse.request = SimpleNamespace(args={}, headers={"Last-Event-ID": "42"})
        base = {
            "cursor": 42,
            "attention_count": 0,
            "collector": {"health": "warming"},
            "integrity": {"generation": 1},
            "preservation": {"state": "live"},
        }
        changed = {**base, "collector": {"health": "live"}}
        with patch.object(cleanhouse, "_files_snapshot", side_effect=[base, changed]), patch.object(
            cleanhouse.time, "sleep", return_value=None
        ):
            response = cleanhouse.stream_files_live()
            stream = response.args[0]
            first = next(stream)
            second = next(stream)

        self.assertIn("id: 42", first)
        self.assertIn('"health":"warming"', first)
        self.assertIn('"health":"live"', second)

    def test_privileged_wazuh_status_rejects_cross_site_request(self):
        cleanhouse.request = SimpleNamespace(
            args={},
            host="localhost:3333",
            headers={
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
                "X-CleanHouse-Intent": "wazuh-status",
            },
        )

        response = cleanhouse.get_files_wazuh_status()

        self.assertEqual(response[1], 403)

    def test_wazuh_setup_enrolls_through_vvault_without_browser_secret(self):
        cleanhouse.request = SimpleNamespace(
            args={},
            headers={},
            get_json=lambda silent=True: {
                "manager": "vvault.thewreck.org",
                "agent_name": "zen-001",
                "monitored_scope": self.temp_dir.name,
            },
        )
        enrollment = {
            "status": "ok",
            "agent_id": "001",
            "agent_name": "zen-001",
            "manager": "vvault.thewreck.org",
            "monitored_scope": self.temp_dir.name,
            "key_fingerprint": "a" * 64,
            "receipt_id": "enrollment:1",
            "client_key": "transient-secret",
        }
        with patch.object(
            cleanhouse, "_require_privileged_files_request", return_value=None
        ), patch.object(
            cleanhouse.wazuh_runtime, "verify_bundle", return_value={"packaged": True}
        ), patch.object(
            cleanhouse.wazuh_files, "enroll_agent", return_value=enrollment
        ) as enroll, patch.object(
            cleanhouse.wazuh_runtime,
            "store_enrollment_key",
            return_value={"status": "ok", "stored": True},
        ) as store, patch.object(
            cleanhouse.wazuh_runtime,
            "install_with_authorization",
            return_value={"status": "ok", "installed": True},
        ) as install:
            response, status_code = cleanhouse.setup_files_wazuh()

        self.assertEqual(status_code, 200)
        self.assertNotIn("client_key", response["enrollment"])
        enroll.assert_called_once()
        store.assert_called_once_with("transient-secret")
        install.assert_called_once_with(
            manager="vvault.thewreck.org",
            agent_name="zen-001",
            agent_id="001",
            monitored_scope=self.temp_dir.name,
        )

    def test_wazuh_projection_supersedes_correlated_watchdog_row(self):
        base = {
            "path": str(Path(self.temp_dir.name) / "file.txt"),
            "event_type": "modified",
            "timestamp": "2026-08-22T00:00:00+00:00",
        }
        watchdog = {**base, "id": 2, "provider": "watchdog", "source_surface": "filesystem_watcher"}
        wazuh = {**base, "id": 1, "provider": "wazuh", "source_surface": "wazuh_fim"}

        projected = cleanhouse._files_correlated([watchdog, wazuh], limit=10)

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["provider"], "wazuh")
        self.assertEqual(projected[0]["correlated_providers"], ["watchdog", "wazuh"])

    def test_files_frontend_contract_is_live_and_reconciliation_first(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend" / "investigations.html").read_text(encoding="utf-8")
        js = (root / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
        css = (root / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")

        self.assertIn('id="reconcile-files-btn"', html)
        self.assertNotIn('id="scan-files-btn"', html)
        self.assertIn('id="files-mediation-badge"', html)
        self.assertIn('id="files-provider"', html)
        self.assertIn("Powered by Wazuh", html)
        self.assertIn("new EventSource", js)
        self.assertIn("getFilesLiveUrl", js)
        self.assertIn("transitionFileMediation", js)
        self.assertIn(".files-mediation-badge", css)


if __name__ == "__main__":
    unittest.main()
