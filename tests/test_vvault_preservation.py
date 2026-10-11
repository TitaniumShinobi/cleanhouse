import base64
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from backend import vvault_preservation, vvault_sync
from corefiles import config


class VVaultPreservationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_root = os.environ.get("CLEANHOUSE_VVAULT_ROOT")
        self._old_user = os.environ.get("CLEANHOUSE_VVAULT_USER_ID")
        self._old_shard = os.environ.get("CLEANHOUSE_VVAULT_SHARD")

    def tearDown(self):
        self._tmp.cleanup()
        self._restore_env("CLEANHOUSE_VVAULT_ROOT", self._old_root)
        self._restore_env("CLEANHOUSE_VVAULT_USER_ID", self._old_user)
        self._restore_env("CLEANHOUSE_VVAULT_SHARD", self._old_shard)

    @staticmethod
    def _restore_env(key, value):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def _enable_vvault(self):
        os.environ["CLEANHOUSE_VVAULT_ROOT"] = str(Path(self._tmp.name) / "vvault_files" / "users")
        os.environ["CLEANHOUSE_VVAULT_USER_ID"] = "test-user"
        os.environ["CLEANHOUSE_VVAULT_SHARD"] = "shard_0000"
        return config.cleanhouse_vvault_root()

    def test_path_resolution_and_disabled_state(self):
        os.environ.pop("CLEANHOUSE_VVAULT_USER_ID", None)
        os.environ["CLEANHOUSE_VVAULT_ROOT"] = str(Path(self._tmp.name) / "vvault_files" / "users")

        self.assertIsNone(config.cleanhouse_vvault_root())
        result = vvault_preservation.preserve_json(
            relative_dir="reports/security_reports",
            artifact_id="report:disabled",
            artifact_type="report",
            data={"id": "report:disabled"},
            source="test",
        )

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["reason"], "missing_user_id")

    def test_artifact_envelope_manifest_and_indexes(self):
        root = self._enable_vvault()
        self.assertIsNotNone(root)

        result = vvault_preservation.preserve_json(
            relative_dir="reports/security_reports",
            artifact_id="report:test",
            artifact_type="report",
            data={"id": "report:test", "timestamp": "2026-07-02T00:00:00Z"},
            source="unit-test",
            evidence_refs=["local://cleanhouse/test"],
            app="Safari",
            severity="high",
            report_type="security",
        )

        self.assertEqual(result["status"], "ok")
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "cleanhouse.vvault_artifact.v1")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["id"], "report:test")
        self.assertEqual(payload["type"], "report")
        self.assertEqual(payload["evidence_refs"], ["local://cleanhouse/test"])

        manifest = json.loads((root / "indexes" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "cleanhouse.vvault_manifest.v1")
        self.assertEqual(manifest["user_id"], "test-user")
        self.assertEqual(manifest["artifact_counts"]["report"], 1)
        vvault_preservation.preserve_json(
            relative_dir="reports/security_reports",
            artifact_id="report:test",
            artifact_type="report",
            data={"id": "report:test", "timestamp": "2026-07-02T00:00:00Z", "updated": True},
            source="unit-test",
            evidence_refs=["local://cleanhouse/test"],
            app="Safari",
            severity="high",
            report_type="security",
        )
        manifest = json.loads((root / "indexes" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["artifact_counts"]["report"], 1)
        self.assertTrue((root / "indexes" / "by_time" / "2026-07-02.json").is_file())
        self.assertTrue((root / "indexes" / "by_app" / "Safari.json").is_file())
        self.assertTrue((root / "indexes" / "by_severity" / "high.json").is_file())
        self.assertTrue((root / "indexes" / "by_report" / "security.json").is_file())

    def test_preservation_does_not_mutate_local_artifact(self):
        self._enable_vvault()
        local_path = Path(self._tmp.name) / "local-report.json"
        local_text = '{"local": true}'
        local_path.write_text(local_text, encoding="utf-8")

        result = vvault_preservation.preserve_local_artifact(
            "report",
            "report:network",
            {
                "schema_version": 1,
                "artifact_type": "report",
                "created_at": "2026-07-02T00:00:00Z",
                "data": {"id": "report:network", "report_type": "network", "timestamp": "2026-07-02T00:00:00Z"},
            },
            local_ref=str(local_path),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(local_path.read_text(encoding="utf-8"), local_text)
        self.assertIn("reports/network_reports", result["path"])

    def test_trend_bucket_and_receipt_paths(self):
        self._enable_vvault()

        trend = vvault_preservation.preserve_network_trend_bucket({
            "event_id": "network_bucket:test",
            "timestamp": "2026-07-02T00:00:00Z",
            "bucket_key": "1m:123",
            "connectionCount": 2,
            "source_event_id": "network:event",
        })
        receipt = vvault_preservation.preserve_local_artifact(
            "receipt",
            "receipt:test",
            {
                "schema_version": 1,
                "artifact_type": "receipt",
                "created_at": "2026-07-02T00:00:00Z",
                "data": {
                    "id": "receipt:test",
                    "timestamp": "2026-07-02T00:00:00Z",
                    "evidence_refs": ["local://cleanhouse/evidence"],
                },
            },
        )

        self.assertEqual(trend["status"], "ok")
        self.assertEqual(receipt["status"], "ok")
        self.assertIn("network/trend/buckets", trend["path"])
        self.assertIn("receipts/investigations", receipt["path"])

    def test_network_history_read_helpers_load_buckets_notables_and_gaps(self):
        self._enable_vvault()

        vvault_preservation.preserve_network_trend_bucket({
            "event_id": "network_bucket:read",
            "timestamp": "2026-07-02T00:00:05Z",
            "bucket_key": "1m:123",
            "bucket_range": "1m",
            "bucket_start": "2026-07-02T00:00:00Z",
            "bucket_end": "2026-07-02T00:01:00Z",
            "connectionCount": 4,
        })
        vvault_preservation.preserve_network_trend_sample({
            "sample_id": "network_sample:read",
            "event_id": "network:event:sample",
            "source_event_id": "network:event:sample",
            "timestamp": "2026-07-02T00:00:10Z",
            "app": "Codex",
            "destination": "example.com",
            "severity": "low",
            "evidence_refs": ["local://cleanhouse/network/network:event:sample"],
        })
        vvault_preservation.preserve_network_trend_tick({
            "tick_id": "network_tick:read",
            "event_id": "network_tick:read",
            "timestamp": "2026-07-02T00:00:15Z",
            "bucket_range": "1m",
            "bucket_key": "tick:1m:network_tick:read",
            "bucket_start": "2026-07-02T00:00:00Z",
            "bucket_end": "2026-07-02T00:01:00Z",
            "connectionCount": 1,
            "immutable": True,
        })
        vvault_preservation.preserve_network_timeline_notable({
            "event_id": "network:event:read",
            "timestamp": "2026-07-02T00:00:05Z",
            "summary": "Codex is communicating on the network.",
            "severity": "low",
        }, "history")
        vvault_preservation.preserve_network_timeline_gap("history", "history_interrupted", {
            "event_id": "network_gap:read",
            "event_type": "network_timeline_gap",
            "timestamp": "2026-07-02T00:02:00Z",
            "gap_start": "2026-07-02T00:01:00Z",
            "gap_end": "2026-07-02T00:02:00Z",
        })

        buckets = vvault_preservation.load_network_trend_buckets(range_key="1m")
        overlapping_buckets = vvault_preservation.load_network_trend_buckets(
            range_key="1m",
            start=datetime(2026, 7, 2, 0, 0, 30, tzinfo=timezone.utc),
            end=datetime(2026, 7, 2, 0, 1, 30, tzinfo=timezone.utc),
        )
        samples = vvault_preservation.load_network_trend_samples()
        ticks = vvault_preservation.load_network_trend_ticks(range_key="1m")
        notables = vvault_preservation.load_network_timeline_notables(range_key="1m")
        gaps = vvault_preservation.load_network_timeline_gaps(range_key="1m")

        self.assertEqual(buckets[0]["event_id"], "network_bucket:read")
        self.assertEqual(overlapping_buckets[0]["event_id"], "network_bucket:read")
        self.assertEqual(samples[0]["sample_id"], "network_sample:read")
        self.assertEqual(ticks[0]["tick_id"], "network_tick:read")
        self.assertEqual(notables[0]["event_id"], "network:event:read")
        self.assertEqual(gaps[0]["event_id"], "network_gap:read")

    def test_immutable_trend_tick_does_not_mutate_and_revision_is_separate(self):
        self._enable_vvault()
        tick = {
            "tick_id": "network_tick:immutable",
            "event_id": "network_tick:immutable",
            "timestamp": "2026-07-02T00:00:15Z",
            "bucket_range": "1m",
            "bucket_key": "tick:1m:network_tick:immutable",
            "bucket_start": "2026-07-02T00:00:00Z",
            "bucket_end": "2026-07-02T00:01:00Z",
            "connectionCount": 1,
            "immutable": True,
        }

        first = vvault_preservation.preserve_network_trend_tick(tick)
        second = vvault_preservation.preserve_network_trend_tick({**tick, "connectionCount": 99})
        stored = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
        revision = vvault_preservation.preserve_network_trend_tick_revision({
            "revision_of": "network_tick:immutable",
            "timestamp": "2026-07-02T00:00:20Z",
            "connectionCount": 99,
            "reason": "corrected count is written as a revision",
        })

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertTrue(second["existing"])
        self.assertEqual(stored["data"]["connectionCount"], 1)
        self.assertIn("network/trend/revisions", revision["path"])


class FilesVVaultSyncTests(unittest.TestCase):
    def setUp(self):
        vvault_sync.stop_service(timeout=2)
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = {
            key: os.environ.get(key)
            for key in (
                "CLEANHOUSE_FILES_OUTBOX_DB",
                "CLEANHOUSE_VVAULT_FILES_EVIDENCE_URL",
                "CLEANHOUSE_VVAULT_SERVICE_TOKEN",
                "CLEANHOUSE_VVAULT_USER_EMAIL",
                "CLEANHOUSE_VVAULT_USER_ID",
                "CLEANHOUSE_VVAULT_INSTANCE_ID",
            )
        }
        os.environ["CLEANHOUSE_FILES_OUTBOX_DB"] = str(Path(self._tmp.name) / "outbox.db")
        os.environ["CLEANHOUSE_VVAULT_FILES_EVIDENCE_URL"] = "https://vvault.example/files/evidence"
        os.environ["CLEANHOUSE_VVAULT_SERVICE_TOKEN"] = "test-token"
        os.environ["CLEANHOUSE_VVAULT_USER_EMAIL"] = "devon@example.com"
        os.environ["CLEANHOUSE_VVAULT_INSTANCE_ID"] = "zen-001"
        vvault_sync._KEYCHAIN_CACHE.update({"loaded_at": 0.0, "payload": {}})

    def tearDown(self):
        vvault_sync.stop_service(timeout=2)
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        vvault_sync._KEYCHAIN_CACHE.update({"loaded_at": 0.0, "payload": {}})
        self._tmp.cleanup()

    def test_keychain_credentials_are_used_without_exposing_values_in_status(self):
        for key in (
            "CLEANHOUSE_VVAULT_SERVICE_TOKEN",
            "VVAULT_SERVICE_TOKEN",
            "CLEANHOUSE_VVAULT_USER_EMAIL",
            "VVAULT_USER_EMAIL",
        ):
            os.environ.pop(key, None)
        vvault_sync._KEYCHAIN_CACHE.update({"loaded_at": 0.0, "payload": {}})
        completed = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({
                "token": "keychain-secret",
                "email": "devon@example.com",
                "user_id": "user-1",
                "instance_id": "zen-001",
            }),
            "stderr": "",
        })()

        with patch.object(vvault_sync.sys, "platform", "darwin"), patch.object(
            vvault_sync.Path, "is_file", return_value=True
        ), patch.object(vvault_sync.subprocess, "run", return_value=completed) as keychain_read:
            url, token = vvault_sync._config()
            identity = vvault_sync._owner_identity()
            state = vvault_sync.status()

        self.assertEqual(url, "https://vvault.example/files/evidence")
        self.assertEqual(token, "keychain-secret")
        self.assertEqual(identity["email"], "devon@example.com")
        self.assertEqual(state["credential_source"], "keychain")
        self.assertNotIn("keychain-secret", json.dumps(state))
        self.assertEqual(
            keychain_read.call_args.kwargs["timeout"],
            vvault_sync.KEYCHAIN_READ_TIMEOUT_SECONDS,
        )

    def test_authenticated_batch_is_idempotent_and_clears_backlog(self):
        with patch.object(vvault_sync, "start_service", return_value={"state": "test"}), patch.object(
            vvault_sync.vvault_preservation, "preserve_json", return_value={"status": "ok"}
        ):
            vvault_sync.enqueue("wazuh:event:1", {"timestamp": "2026-08-22T00:00:00Z", "value": 1})
            vvault_sync.enqueue("wazuh:event:1", {"timestamp": "2026-08-22T00:00:00Z", "value": 1})

        batches = []
        def transport(url, token, body):
            payload = json.loads(body)
            batches.append((url, token, payload))
            return {
                "receipt_id": "ovvaults-receipt-1",
                "batch_id": hashlib.sha256(body).hexdigest(),
                "accepted_evidence_ids": [item["evidence_id"] for item in payload["events"]],
                "owner_user_id": "user-1",
                "instance_id": "zen-001",
                "storage_owner": "ovvaults.vault_files",
                "committed_at": "2026-08-22T00:00:01Z",
            }

        result = vvault_sync.flush_once(transport=transport)

        self.assertEqual(result["synced"], 1)
        self.assertEqual(batches[0][1], "test-token")
        self.assertEqual(len(batches[0][2]["events"]), 1)
        self.assertEqual(vvault_sync.status()["pending"], 0)
        self.assertEqual(vvault_sync.status()["last_receipt"]["receipt_id"], "ovvaults-receipt-1")

    def test_evidence_id_collision_is_rejected(self):
        with patch.object(vvault_sync, "start_service", return_value={"state": "test"}), patch.object(
            vvault_sync.vvault_preservation, "preserve_json", return_value={"status": "ok"}
        ):
            vvault_sync.enqueue("network:event:collision", {"value": 1}, surface="network")
            with self.assertRaisesRegex(ValueError, "evidence ID collision"):
                vvault_sync.enqueue("network:event:collision", {"value": 2}, surface="network")

    def test_transport_failure_keeps_durable_backlog(self):
        with patch.object(vvault_sync, "start_service", return_value={"state": "test"}), patch.object(
            vvault_sync.vvault_preservation, "preserve_json", return_value={"status": "ok"}
        ):
            vvault_sync.enqueue("wazuh:event:2", {"timestamp": "2026-08-22T00:00:00Z"})

        result = vvault_sync.flush_once(
            transport=lambda *_args: (_ for _ in ()).throw(RuntimeError("offline"))
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(vvault_sync.status()["pending"], 1)

    def test_receipts_and_readiness_are_isolated_by_surface(self):
        timestamp = vvault_sync._now()
        with patch.object(vvault_sync, "start_service", return_value={"state": "test"}), patch.object(
            vvault_sync.vvault_preservation, "preserve_json", return_value={"status": "disabled"}
        ):
            vvault_sync.enqueue("files:event:scoped", {"timestamp": timestamp}, surface="files")
            vvault_sync.enqueue("network:event:scoped", {"timestamp": timestamp}, surface="network")

        def transport(_url, _token, body):
            payload = json.loads(body)
            batch_id = hashlib.sha256(body).hexdigest()
            return {
                "receipt_id": f"cleanhouse-files:{batch_id}",
                "batch_id": batch_id,
                "accepted_evidence_ids": [item["evidence_id"] for item in payload["events"]],
                "owner_user_id": "user-1",
                "instance_id": "zen-001",
                "storage_owner": "ovvaults.vault_files",
                "committed_at": timestamp,
            }

        vvault_sync.flush_once(surface="files", transport=transport)
        self.assertEqual(vvault_sync.status("files")["state"], "live")
        self.assertEqual(vvault_sync.status("network")["state"], "warming")
        self.assertEqual(vvault_sync.status("network")["backlog_depth"], 1)

        vvault_sync.flush_once(surface="network", transport=transport)
        self.assertEqual(vvault_sync.status("network")["state"], "live")
        with vvault_sync._managed_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evidence_receipts").fetchone()[0], 2)

    def test_noncanonical_receipt_does_not_clear_backlog(self):
        with patch.object(vvault_sync, "start_service", return_value={"state": "test"}), patch.object(
            vvault_sync.vvault_preservation, "preserve_json", return_value={"status": "disabled"}
        ):
            vvault_sync.enqueue("network:event:bad-receipt", {"timestamp": vvault_sync._now()}, surface="network")

        result = vvault_sync.flush_once(
            surface="network",
            transport=lambda _url, _token, body: {
                "receipt_id": "not-canonical",
                "batch_id": hashlib.sha256(body).hexdigest(),
                "accepted_evidence_ids": ["network:event:bad-receipt"],
                "owner_user_id": "user-1",
                "instance_id": "zen-001",
                "storage_owner": "filesystem",
                "committed_at": vvault_sync._now(),
            },
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(vvault_sync.status("network")["backlog_depth"], 1)
        self.assertFalse(vvault_sync.status("network")["evidence_authenticated"])

    def test_default_transport_sends_vvault_owner_scope_without_exposing_it_in_body(self):
        body = b'{"events":[],"schema":"cleanhouse.files_evidence.batch.v1"}'
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                batch_id = hashlib.sha256(body).hexdigest()
                return json.dumps({
                    "receipt_id": "receipt",
                    "batch_id": batch_id,
                    "accepted_evidence_ids": [],
                }).encode("utf-8")

        def open_request(request, **_kwargs):
            captured["headers"] = dict(request.header_items())
            return Response()

        with patch.object(vvault_sync.urllib.request, "urlopen", side_effect=open_request):
            vvault_sync._default_transport("https://vvault.example/api/cleanhouse/files/evidence", "test-token", body)

        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(captured["headers"]["X-chatty-key"], "test-token")
        self.assertEqual(captured["headers"]["X-chatty-user"], "devon@example.com")
        self.assertEqual(captured["headers"]["X-cleanhouse-instance"], "zen-001")
        self.assertNotIn("X-cleanhouse-key", captured["headers"])

    def test_dedicated_pairing_credential_uses_only_cleanhouse_auth_header(self):
        body = b'{"events":[],"schema":"cleanhouse.files_evidence.batch.v1"}'
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "receipt_id": "receipt",
                    "batch_id": hashlib.sha256(body).hexdigest(),
                    "accepted_evidence_ids": [],
                }).encode("utf-8")

        def open_request(request, **_kwargs):
            captured["headers"] = dict(request.header_items())
            return Response()

        with patch.object(vvault_sync, "_credential_type", return_value="cleanhouse_files_pairing"), patch.object(
            vvault_sync, "_owner_identity", return_value={
                "email": "devon@example.com",
                "user_id": "",
                "instance_id": "zen-001",
            }
        ), patch.object(vvault_sync.urllib.request, "urlopen", side_effect=open_request):
            vvault_sync._default_transport(
                "https://vvault.example/api/cleanhouse/files/evidence",
                "chf_v1_dedicated",
                body,
            )

        self.assertEqual(captured["headers"]["X-cleanhouse-key"], "chf_v1_dedicated")
        self.assertNotIn("Authorization", captured["headers"])
        self.assertNotIn("X-chatty-key", captured["headers"])

    def test_configured_but_unverified_endpoint_is_warming_not_live(self):
        state = vvault_sync.status()

        self.assertEqual(state["sync_state"], "warming")
        self.assertEqual(state["authentication_state"], "unverified")
        self.assertFalse(state["evidence_authenticated"])

    def test_pairing_decrypts_locally_and_stores_only_in_keychain(self):
        pairing_key = Path(self._tmp.name) / "pairing-private.pem"
        with patch.object(vvault_sync, "_pairing_private_key_path", return_value=pairing_key):
            started = vvault_sync.begin_pairing()
            public_key = serialization.load_pem_public_key(started["public_key_pem"].encode("ascii"))
            token = "chf_v1_" + "a" * 64
            ciphertext = public_key.encrypt(
                token.encode("utf-8"),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
            response = {
                "credential_type": "cleanhouse_files_pairing",
                "algorithm": "RSA-OAEP-3072-SHA256",
                "instance_id": "zen-001",
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            }
            with patch.object(vvault_sync, "_keychain_credentials", return_value={
                "email": "devon@example.com", "user_id": "user-1"
            }), patch.object(vvault_sync, "_store_keychain_payload") as store:
                completed = vvault_sync.complete_pairing(response)

        self.assertEqual(completed["status"], "paired")
        self.assertEqual(store.call_args.args[0]["token"], token)
        self.assertEqual(store.call_args.args[0]["auth_type"], "cleanhouse_files_pairing")
        self.assertFalse(pairing_key.exists())


if __name__ == "__main__":
    unittest.main()
