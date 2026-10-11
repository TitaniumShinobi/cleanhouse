import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import events, wazuh_files


class WazuhFilesTests(unittest.TestCase):
    def setUp(self):
        wazuh_files.stop_service(timeout=2)
        wazuh_files.vvault_sync.stop_service(timeout=2)
        self.tmp = tempfile.TemporaryDirectory()
        self.keychain_patch = patch.object(wazuh_files.vvault_sync, "_keychain_credentials", return_value={})
        self.keychain_patch.start()
        self.previous = {key: os.environ.get(key) for key in (
            "CLEANHOUSE_EVENTS_DB",
            "CLEANHOUSE_FILES_INTEGRITY_DB",
            "CLEANHOUSE_FILES_OUTBOX_DB",
            "CLEANHOUSE_WAZUH_EVENTS_URL",
            "CLEANHOUSE_WAZUH_INVENTORY_URL",
            "CLEANHOUSE_WAZUH_ENROLL_URL",
            "CLEANHOUSE_VVAULT_SERVICE_TOKEN",
            "CLEANHOUSE_VVAULT_USER_EMAIL",
            "CLEANHOUSE_VVAULT_USER_ID",
            "CLEANHOUSE_VVAULT_INSTANCE_ID",
            "CLEANHOUSE_WATCH_DIR",
        )}
        os.environ["CLEANHOUSE_EVENTS_DB"] = str(Path(self.tmp.name) / "events.db")
        os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"] = str(Path(self.tmp.name) / "integrity.db")
        os.environ["CLEANHOUSE_FILES_OUTBOX_DB"] = str(Path(self.tmp.name) / "outbox.db")
        os.environ["CLEANHOUSE_WATCH_DIR"] = "/scope"
        events._DB_INIT_STATE.clear()
        wazuh_files._STATE.update(
            {"authenticated": False, "authenticated_event_count": 0, "last_error": "", "last_event_at": ""}
        )

    def tearDown(self):
        wazuh_files.stop_service(timeout=2)
        wazuh_files.vvault_sync.stop_service(timeout=2)
        self.keychain_patch.stop()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        events._DB_INIT_STATE.clear()
        self.tmp.cleanup()

    @staticmethod
    def _hit():
        return {
            "_index": "wazuh-alerts-4.x-2026.08.22",
            "_id": "alert-1",
            "sort": ["2026-08-22T00:00:00Z", "alert-1"],
            "_source": {
                "timestamp": "2026-08-22T00:00:00Z",
                "agent": {"id": "001", "name": "mac-mini"},
                "manager": {"name": "cleanhouse-wazuh"},
                "rule": {"id": "550", "description": "Integrity checksum changed"},
                "data": {
                    "syscheck": {
                        "event": "modified",
                        "path": "/scope/file.txt",
                        "sha256_after": "a" * 64,
                        "size_after": 12,
                        "perm_after": "rw-r--r--",
                    }
                },
            },
        }

    def test_authenticated_hit_is_normalized_committed_and_deduplicated(self):
        with patch.object(wazuh_files.vvault_sync, "enqueue", return_value={"status": "queued"}):
            first = wazuh_files.ingest_hits([self._hit()])
            replay = wazuh_files.ingest_hits([self._hit()])

        rows = events.list_events(limit=10, source_surface="wazuh_fim")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(replay["duplicates"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "wazuh")
        self.assertEqual(rows[0]["data"]["wazuh"]["agent_id"], "001")
        self.assertTrue(events.get_collector_cursor(wazuh_files.COLLECTOR)["cursor"])
        self.assertEqual(wazuh_files.file_integrity.snapshot()["generation"], 1)

    def test_wazuh_preservation_payload_omits_live_ingestion_latency(self):
        preserved = []

        def capture(_evidence_id, payload):
            preserved.append(payload)
            return {"status": "queued"}

        with patch.object(wazuh_files.vvault_sync, "enqueue", side_effect=capture):
            result = wazuh_files.ingest_hits([self._hit()])

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(preserved), 1)
        self.assertNotIn("ingestion_latency_ms", preserved[0])

    def test_outbox_replay_ignores_only_live_ingestion_latency(self):
        payload = {
            "source_event_key": "wazuh:test:alert-1",
            "path": "/scope/file.txt",
            "ingestion_latency_ms": 10,
        }
        with (
            patch.object(wazuh_files.vvault_sync.vvault_preservation, "preserve_json", return_value={"state": "cached"}),
            patch.object(wazuh_files.vvault_sync, "start_service", return_value={}),
        ):
            first = wazuh_files.vvault_sync.enqueue("wazuh:test:alert-1", payload)
            replay = wazuh_files.vvault_sync.enqueue(
                "wazuh:test:alert-1",
                {**payload, "ingestion_latency_ms": 999},
            )
            with self.assertRaisesRegex(ValueError, "evidence ID collision"):
                wazuh_files.vvault_sync.enqueue(
                    "wazuh:test:alert-1",
                    {**payload, "path": "/scope/other.txt"},
                )

        self.assertEqual(first["status"], "queued")
        self.assertEqual(replay["status"], "existing")

    def test_poll_authentication_failure_clears_live_claim(self):
        os.environ["CLEANHOUSE_WAZUH_EVENTS_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/events"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        wazuh_files._STATE["authenticated"] = True

        result = wazuh_files.poll_once(transport=lambda _request: (_ for _ in ()).throw(RuntimeError("denied")))

        self.assertFalse(result["authenticated"])
        self.assertFalse(wazuh_files._STATE["authenticated"])

    def test_permission_only_alert_keeps_permission_evidence(self):
        hit = self._hit()
        hit["_id"] = "alert-permission"
        syscheck = hit["_source"]["data"]["syscheck"]
        syscheck.pop("sha256_after")
        syscheck["changed_attributes"] = ["perm"]

        normalized = wazuh_files.normalize_hit(hit)

        self.assertEqual(normalized["operation"], "permission")
        self.assertIn("permission", normalized["change_kinds"])
        self.assertEqual(normalized["metadata"]["mode"], "rw-r--r--")

    def test_native_manager_alert_with_top_level_syscheck_is_normalized(self):
        hit = self._hit()
        source = hit["_source"]
        source["syscheck"] = source.pop("data")["syscheck"]

        normalized = wazuh_files.normalize_hit(hit)

        self.assertEqual(normalized["path"], "/scope/file.txt")
        self.assertEqual(normalized["operation"], "modified")
        self.assertEqual(normalized["hashes"]["sha256"], "a" * 64)

    def test_projection_failure_does_not_advance_provider_cursor(self):
        with patch.object(wazuh_files.vvault_sync, "enqueue", side_effect=RuntimeError("outbox unavailable")):
            result = wazuh_files.ingest_hits([self._hit()])

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(events.get_collector_cursor(wazuh_files.COLLECTOR)["cursor"], "")
        self.assertEqual(events.list_events(limit=10, source_surface="wazuh_fim"), [])

    def test_inventory_paginates_manager_results(self):
        os.environ["CLEANHOUSE_WAZUH_INVENTORY_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/inventory"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        items = [{"id": str(index), "path": f"/scope/{index}", "sha256": "a" * 64} for index in range(501)]

        def transport(request):
            offset = int(request.full_url.split("offset=")[1].split("&")[0])
            return {
                "schema": "vvault.cleanhouse.wazuh_inventory.v1",
                "provider": "wazuh_manager",
                "evidence_authenticated": True,
                "agent_id": "001",
                "monitored_scope": "/scope",
                "data": {
                    "affected_items": items[offset:offset + 500],
                    "total_affected_items": len(items),
                }
            }

        inventory = wazuh_files.inventory(transport=transport)

        self.assertEqual(len(inventory), 501)
        self.assertEqual(inventory[-1]["path"], "/scope/500")

    def test_inventory_continues_when_scope_filter_makes_page_short(self):
        os.environ["CLEANHOUSE_WAZUH_INVENTORY_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/inventory"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"

        def transport(request):
            offset = int(request.full_url.split("offset=")[1].split("&")[0])
            pages = {
                0: [{"id": "1", "path": "/scope/one", "sha256": "a" * 64}],
                500: [{"id": "2", "path": "/scope/two", "sha256": "b" * 64}],
            }
            return {
                "schema": "vvault.cleanhouse.wazuh_inventory.v1",
                "provider": "wazuh_manager",
                "evidence_authenticated": True,
                "agent_id": "001",
                "monitored_scope": "/scope",
                "data": {
                    "affected_items": pages.get(offset, []),
                    "total_affected_items": 1000,
                    "source_total_affected_items": 1000,
                    "source_page_count": 500,
                    "next_offset": offset + 500,
                    "complete": offset >= 500,
                },
            }

        inventory = wazuh_files.inventory(transport=transport)

        self.assertEqual([item["path"] for item in inventory], ["/scope/one", "/scope/two"])

    def test_inventory_and_feed_exclude_nested_runtime_artifacts(self):
        os.environ["CLEANHOUSE_WAZUH_INVENTORY_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/inventory"
        os.environ["CLEANHOUSE_WAZUH_EVENTS_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/events"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        excluded = self._hit()
        excluded["_id"] = "excluded-cache"
        excluded["_source"]["data"]["syscheck"]["path"] = "/scope/backend/__pycache__/module.pyc"
        included = self._hit()
        included["_id"] = "included-source"
        included["_source"]["data"]["syscheck"]["path"] = "/scope/backend/module.py"

        inventory = wazuh_files.inventory(transport=lambda _request: {
            "schema": "vvault.cleanhouse.wazuh_inventory.v1",
            "provider": "wazuh_manager",
            "evidence_authenticated": True,
            "agent_id": "001",
            "monitored_scope": "/scope",
            "data": {
                "affected_items": [
                    {"id": "1", "path": "/scope/backend/__pycache__/module.pyc"},
                    {"id": "2", "path": "/scope/backend/module.py"},
                ],
                "total_affected_items": 2,
            },
        })
        with patch.object(wazuh_files.vvault_sync, "enqueue", return_value={"status": "queued"}):
            poll = wazuh_files.poll_once(transport=lambda _request: {
                "schema": "vvault.cleanhouse.wazuh_feed.v1",
                "provider": "wazuh_manager",
                "evidence_authenticated": True,
                "agent_id": "001",
                "monitored_scope": "/scope",
                "cursor": "wazuh-jsonl.v1:1:2:3",
                "items": [excluded, included],
            })

        self.assertEqual([item["path"] for item in inventory], ["/scope/backend/module.py"])
        self.assertEqual(poll["received"], 1)
        self.assertEqual(poll["filtered"], 1)

    def test_poll_accepts_only_authenticated_vvault_manager_feed(self):
        os.environ["CLEANHOUSE_WAZUH_EVENTS_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/events"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        hit = self._hit()
        hit["_index"] = "wazuh-manager-alerts"
        hit["_vvault_cursor"] = "wazuh-jsonl.v1:1:2:300"

        with patch.object(wazuh_files.vvault_sync, "enqueue", return_value={"status": "queued"}):
            result = wazuh_files.poll_once(
                transport=lambda _request: {
                    "schema": "vvault.cleanhouse.wazuh_feed.v1",
                    "provider": "wazuh_manager",
                    "evidence_authenticated": True,
                    "agent_id": "001",
                    "monitored_scope": "/scope",
                    "manager": "cleanhouse-wazuh",
                    "manager_version": "4.14.7",
                    "stream_identity": "alerts-json:1048577",
                    "stream_generation": "1048577:1",
                    "gap_state": "none_observed",
                    "items": [hit],
                }
            )

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(events.get_collector_cursor(wazuh_files.COLLECTOR)["cursor"], hit["_vvault_cursor"])

    def test_poll_advances_authenticated_empty_page_cursor(self):
        os.environ["CLEANHOUSE_WAZUH_EVENTS_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/events"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        page_cursor = "wazuh-jsonl.v1:1:2:4194304"

        result = wazuh_files.poll_once(
            transport=lambda _request: {
                "schema": "vvault.cleanhouse.wazuh_feed.v1",
                "provider": "wazuh_manager",
                "evidence_authenticated": True,
                "agent_id": "001",
                "monitored_scope": "/scope",
                "manager": "cleanhouse-wazuh",
                "manager_version": "4.14.7",
                "stream_identity": "1:2",
                "stream_generation": "2:3",
                "gap_state": "none_observed",
                "cursor": page_cursor,
                "items": [],
            }
        )

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["received"], 0)
        self.assertEqual(events.get_collector_cursor(wazuh_files.COLLECTOR)["cursor"], page_cursor)

    def test_poll_rejects_unattested_feed_payload(self):
        os.environ["CLEANHOUSE_WAZUH_EVENTS_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/events"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"

        result = wazuh_files.poll_once(
            transport=lambda _request: {
                "schema": "vvault.cleanhouse.wazuh_feed.v1",
                "provider": "wazuh_manager",
                "evidence_authenticated": False,
                "items": [],
            }
        )

        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["authenticated"])

    def test_pairing_headers_are_reused_for_enrollment(self):
        os.environ["CLEANHOUSE_WAZUH_ENROLL_URL"] = "https://vvault.example/api/cleanhouse/files/wazuh/enroll"
        client_key = "opaque-client-key"
        fingerprint = __import__("hashlib").sha256(client_key.encode()).hexdigest()

        with patch.object(
            wazuh_files.vvault_sync,
            "authenticated_headers",
            return_value={"X-CleanHouse-Key": "paired", "X-Chatty-User": "devon@example.com"},
        ):
            result = wazuh_files.enroll_agent(
                manager="vvault.thewreck.org",
                agent_name="zen-001",
                monitored_scope="/scope",
                transport=lambda request: {
                    "schema": "vvault.cleanhouse.wazuh_enrollment.v1",
                    "provider": "wazuh_manager",
                    "evidence_authenticated": True,
                    "agent_id": "001",
                    "agent_name": "zen-001",
                    "manager": "vvault.thewreck.org",
                    "monitored_scope": "/scope",
                    "key_fingerprint": fingerprint,
                    "receipt_id": "wazuh-enrollment:receipt",
                    "client_key": client_key,
                    "request_headers": dict(request.header_items()),
                },
            )

        self.assertEqual(result["agent_id"], "001")
        self.assertEqual(result["client_key"], client_key)

    def test_historical_powered_state_survives_current_feed_failure(self):
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "service-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        with patch.object(wazuh_files.vvault_sync, "enqueue", return_value={"status": "queued"}):
            wazuh_files.ingest_hits([self._hit()])
        wazuh_files._STATE["authenticated"] = False
        wazuh_files._STATE["last_error"] = "manager unavailable"

        state = wazuh_files.status()

        self.assertTrue(state["powered_by_wazuh"])
        self.assertTrue(state["historical_wazuh_proof"])
        self.assertEqual(state["health"], "degraded")


if __name__ == "__main__":
    unittest.main()
