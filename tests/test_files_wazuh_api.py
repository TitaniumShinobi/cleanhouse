from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from flask import Flask

from backend.api import cleanhouse


class FilesWazuhReadApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            key: os.environ.get(key)
            for key in ("CLEANHOUSE_ENABLE_AUTH", "CLEANHOUSE_REQUIRE_LOGIN")
        }
        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "0"
        os.environ["CLEANHOUSE_REQUIRE_LOGIN"] = "0"
        app = Flask(__name__)
        app.secret_key = "focused-test"
        app.register_blueprint(cleanhouse.bp)
        app.testing = True
        self.client = app.test_client()

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @staticmethod
    def _dependencies(*, watcher_status="unavailable", wazuh=None, rows=None):
        return (
            patch.object(
                cleanhouse.events,
                "list_events_by_sources",
                return_value={
                    cleanhouse.FILES_WATCHER_SOURCE: list(rows or []),
                    cleanhouse.FILES_WAZUH_SOURCE: [],
                },
            ),
            patch.object(
                cleanhouse.events,
                "get_watcher_status",
                return_value={"status": watcher_status, "watch_dir": "/scope"},
            ),
            patch.object(
                cleanhouse.wazuh_files,
                "status",
                return_value=wazuh or {
                    "configured": False,
                    "operational": False,
                    "authenticated": False,
                    "powered_by_wazuh": False,
                    "historical_wazuh_proof": False,
                    "health": "unavailable",
                    "lifecycle": "unavailable",
                    "monitored_scope": "/scope",
                },
            ),
            patch.object(
                cleanhouse.vvault_sync,
                "status",
                return_value={"sync_state": "unavailable", "evidence_authenticated": False},
            ),
            patch.object(
                cleanhouse.file_integrity,
                "snapshot",
                return_value={"state": "no_data", "generation": 0},
            ),
        )

    def test_unavailable_provider_does_not_fabricate_files_availability(self):
        patches = self._dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            response = self.client.get("/cleanhouse/files/snapshot")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["collector"]["provider"], "none")
        self.assertFalse(payload["collector"]["operational"])
        self.assertFalse(payload["powered_by_wazuh"])
        self.assertFalse(payload["monitoring"]["always_on"])
        self.assertEqual(payload["events"], [])

    def test_local_watcher_is_truthfully_labeled_fallback(self):
        patches = self._dependencies(watcher_status="running")
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            payload = self.client.get("/cleanhouse/files/snapshot").get_json()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["collector"]["health"], "fallback")
        self.assertEqual(payload["collector"]["provider"], "watchdog")
        self.assertTrue(payload["collector"]["fallback"]["active"])
        self.assertFalse(payload["collector"]["evidence_authenticated"])
        self.assertTrue(payload["monitoring"]["always_on"])

    def test_configured_provider_is_warming_not_operational(self):
        patches = self._dependencies(wazuh={
            "configured": True,
            "operational": False,
            "authenticated": False,
            "powered_by_wazuh": False,
            "historical_wazuh_proof": False,
            "health": "warming",
            "lifecycle": "packaged",
            "monitored_scope": "/scope",
        })
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            payload = self.client.get("/cleanhouse/files/snapshot").get_json()

        self.assertEqual(payload["collector"]["health"], "warming")
        self.assertFalse(payload["collector"]["operational"])

    def test_operational_provider_is_selected_only_from_explicit_evidence(self):
        patches = self._dependencies(watcher_status="running", wazuh={
            "configured": True,
            "operational": True,
            "authenticated": True,
            "powered_by_wazuh": True,
            "historical_wazuh_proof": True,
            "health": "live",
            "lifecycle": "scanning",
            "agent_id": "001",
            "monitored_scope": "/scope",
        })
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            payload = self.client.get("/cleanhouse/files/snapshot").get_json()

        self.assertEqual(payload["collector"]["health"], "live")
        self.assertEqual(payload["collector"]["provider"], "wazuh")
        self.assertTrue(payload["collector"]["operational"])
        self.assertTrue(payload["powered_by_wazuh"])
        self.assertFalse(payload["collector"]["fallback"]["active"])
        self.assertTrue(payload["monitoring"]["always_on"])

    def test_read_routes_require_the_existing_session_when_auth_is_enabled(self):
        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "1"
        os.environ["CLEANHOUSE_REQUIRE_LOGIN"] = "1"

        response = self.client.get("/cleanhouse/files/snapshot")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "Authentication required")

    def test_cross_provider_projection_prefers_wazuh_without_rewriting_raw_rows(self):
        watchdog = {
            "id": 1,
            "path": "/scope/file.txt",
            "event_type": "modified",
            "provider": "watchdog",
            "timestamp": "2026-10-13T12:00:00+00:00",
        }
        wazuh = {
            "id": 2,
            "path": "/scope/file.txt",
            "event_type": "modified",
            "provider": "wazuh",
            "timestamp": "2026-10-13T12:00:02+00:00",
        }
        projected = cleanhouse._files_correlated([watchdog, wazuh], limit=10)

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["provider"], "wazuh")
        self.assertEqual(projected[0]["correlated_providers"], ["watchdog", "wazuh"])
        self.assertNotIn("correlated_providers", watchdog)
        self.assertNotIn("correlated_providers", wazuh)

    def test_sse_formatter_preserves_durable_event_id(self):
        payload = cleanhouse._files_sse_event(
            "files-snapshot", {"schema": "cleanhouse.files.v2"}, event_id="41"
        )

        self.assertTrue(payload.startswith("id: 41\nevent: files-snapshot\n"))
        self.assertIn('"schema":"cleanhouse.files.v2"', payload)


if __name__ == "__main__":
    unittest.main()
