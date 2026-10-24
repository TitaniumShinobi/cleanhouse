import os
import tempfile
import unittest
import queue
import sqlite3
import threading
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from backend import events
from backend.api import cleanhouse as cleanhouse_module

class CleanHouseEventStorageTests(unittest.TestCase):
    def setUp(self):
        self._api_patches = [
            patch.object(
                cleanhouse_module,
                "jsonify",
                side_effect=lambda obj=None, **kwargs: obj if obj is not None else kwargs,
            ),
            patch.object(
                cleanhouse_module,
                "Response",
                side_effect=lambda *args, **kwargs: SimpleNamespace(
                    args=args,
                    kwargs=kwargs,
                    headers={},
                ),
            ),
            patch.object(cleanhouse_module, "stream_with_context", side_effect=lambda func: func),
            patch.object(
                cleanhouse_module,
                "send_file",
                side_effect=lambda *args, **kwargs: {"send_file": args, "kwargs": kwargs},
            ),
        ]
        for api_patch in self._api_patches:
            api_patch.start()
        self._old_request = cleanhouse_module.request
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "events.db"
        self._old_db_env = os.environ.get("CLEANHOUSE_EVENTS_DB")
        os.environ["CLEANHOUSE_EVENTS_DB"] = str(self._db_path)
        events.init_db()
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )

    def tearDown(self):
        events._stop_db_writer()
        cleanhouse_module.request = self._old_request
        for api_patch in reversed(self._api_patches):
            api_patch.stop()
        self._tmp.cleanup()
        if self._old_db_env is None:
            os.environ.pop("CLEANHOUSE_EVENTS_DB", None)
        else:
            os.environ["CLEANHOUSE_EVENTS_DB"] = self._old_db_env

    def test_insert_and_list_events(self):
        events.insert_event(
            event_type="modified",
            path="/tmp/test.txt",
            summary="modified: /tmp/test.txt",
            session_id="session-1",
        )
        rows = events.list_events(limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for key in ("id", "timestamp", "session_id", "event_type", "path", "summary"):
            self.assertIn(key, row)
        self.assertEqual(row["session_id"], "session-1")
        self.assertEqual(row["event_type"], "modified")
        self.assertEqual(row["path"], "/tmp/test.txt")
        self.assertEqual(row["summary"], "modified: /tmp/test.txt")
        self.assertIn("objective_id", row)
        self.assertIn("collector_status", row)
        self.assertEqual(row["evidence_refs"], [])
        self.assertEqual(row["data"], {})

    def test_list_events_applies_bounded_timestamp_window(self):
        for timestamp, path in (
            ("2026-10-15T10:00:00Z", "/network/before"),
            ("2026-10-15T10:05:00Z", "/network/in-window"),
            ("2026-10-15T10:10:00Z", "/network/after"),
        ):
            events.insert_event(
                event_type="network_observation",
                path=path,
                summary=path,
                session_id="network-window",
                timestamp=timestamp,
                source_surface="network",
            )

        rows = events.list_events(
            limit=10,
            event_type="network_observation",
            source_surface="network",
            start_timestamp="2026-10-15T10:01:00Z",
            end_timestamp="2026-10-15T10:09:00Z",
        )

        self.assertEqual([row["path"] for row in rows], ["/network/in-window"])

    def test_invalid_configured_events_db_falls_back_to_default_path(self):
        blocked_parent = Path(self._tmp.name) / "not-a-directory"
        blocked_parent.write_text("file blocks directory creation", encoding="utf-8")
        fallback_path = Path(self._tmp.name) / "fallback" / "events.db"
        os.environ["CLEANHOUSE_EVENTS_DB"] = str(blocked_parent / "events.db")
        events._DB_INIT_STATE.clear()

        with patch.object(events, "DEFAULT_DB_PATH", fallback_path):
            events.init_db()

        self.assertTrue(fallback_path.is_file())

    def test_insert_event_persists_optional_metadata_fields(self):
        events.insert_event(
            event_type="tool_event",
            path="/tools/test",
            summary="tool_event: test",
            session_id="session-metadata",
            objective_id="objective-1",
            source_surface="api",
            actor_type="worker",
            evidence_level="observed",
            observed_vs_expected={"observed": "ran", "expected": "run"},
            collector_status="ok",
            scope_relation="in_scope",
            evidence_refs=[{"type": "path", "value": "/tools/test"}],
            raw_evidence_ref="raw://event/1",
            data={"exit_code": 0},
        )

        row = events.list_events(limit=10, session_id="session-metadata")[0]
        self.assertEqual(row["objective_id"], "objective-1")
        self.assertEqual(row["source_surface"], "api")
        self.assertEqual(row["actor_type"], "worker")
        self.assertEqual(row["evidence_level"], "observed")
        self.assertEqual(row["observed_vs_expected"]["expected"], "run")
        self.assertEqual(row["collector_status"], "ok")
        self.assertEqual(row["scope_relation"], "in_scope")
        self.assertEqual(row["evidence_refs"][0]["value"], "/tools/test")
        self.assertEqual(row["raw_evidence_ref"], "raw://event/1")
        self.assertEqual(row["data"]["exit_code"], 0)

    def test_provider_event_and_cursor_commit_atomically_and_deduplicate(self):
        first = events.insert_event_with_cursor(
            collector="wazuh-test",
            cursor='["2026-08-22T00:00:00Z","alert-1"]',
            source_event_key="wazuh:index:alert-1",
            event_type="modified",
            path="/tmp/wazuh.txt",
            summary="Wazuh observed modified",
            source_surface="wazuh_fim",
            provider="wazuh",
            evidence_level="authenticated",
        )
        duplicate = events.insert_event_with_cursor(
            collector="wazuh-test",
            cursor='["2026-08-22T00:00:00Z","alert-1"]',
            source_event_key="wazuh:index:alert-1",
            event_type="modified",
            path="/tmp/wazuh.txt",
            summary="duplicate",
            source_surface="wazuh_fim",
            provider="wazuh",
            evidence_level="authenticated",
        )

        self.assertTrue(first["inserted"])
        self.assertFalse(duplicate["inserted"])
        self.assertEqual(len(events.list_events(limit=10, source_surface="wazuh_fim")), 1)
        self.assertEqual(events.get_collector_cursor("wazuh-test")["cursor"], first["cursor"])

    def test_async_insert_event_persists_metadata_fields(self):
        events.insert_event_async(
            event_type="process_event",
            path="/bin/test",
            summary="process_event: test",
            session_id="session-async-metadata",
            objective_id="objective-async",
            source_surface="runtime",
            actor_type="collector",
            collector_status="ok",
            evidence_refs=["/bin/test"],
            data={"pid": 123},
        )
        events._EVENT_QUEUE.join()

        row = events.list_events(limit=10, session_id="session-async-metadata")[0]
        self.assertEqual(row["objective_id"], "objective-async")
        self.assertEqual(row["source_surface"], "runtime")
        self.assertEqual(row["actor_type"], "collector")
        self.assertEqual(row["collector_status"], "ok")
        self.assertEqual(row["evidence_refs"], ["/bin/test"])
        self.assertEqual(row["data"]["pid"], 123)

    def test_watchdog_handler_emits_stable_source_key_without_crashing(self):
        if events.FileSystemEventHandler is None:
            self.skipTest("watchdog is unavailable")
        observed_path = Path(self._tmp.name) / "observed.txt"
        observed_path.write_text("evidence", encoding="utf-8")
        handler = events._CleanHouseFileHandler(self._db_path, Path(self._tmp.name))
        event = SimpleNamespace(is_directory=False, src_path=str(observed_path))

        with patch.object(events, "insert_event_async") as insert_async:
            handler.on_modified(event)

        source_event_key = insert_async.call_args.kwargs["source_event_key"]
        self.assertTrue(source_event_key.startswith("watchdog:"))
        self.assertEqual(len(source_event_key), len("watchdog:") + 64)
        self.assertEqual(insert_async.call_args.kwargs["provider"], "watchdog")
        self.assertTrue(insert_async.call_args.kwargs["data"]["fallback"])

    def test_list_events_migrates_old_rows_with_defaults(self):
        self._db_path.unlink(missing_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO events (timestamp, session_id, event_type, path, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("2026-01-01T00:00:00+00:00", "old-session", "modified", "/tmp/old.txt", "old"),
            )
            conn.commit()
        finally:
            conn.close()

        row = events.list_events(limit=10, session_id="old-session")[0]
        self.assertEqual(row["path"], "/tmp/old.txt")
        self.assertIsNone(row["objective_id"])
        self.assertIsNone(row["collector_status"])
        self.assertEqual(row["observed_vs_expected"], {})
        self.assertEqual(row["evidence_refs"], [])
        self.assertEqual(row["data"], {})

    def test_events_endpoint_returns_rows(self):
        events.insert_event(
            event_type="created",
            path="/tmp/created.txt",
            summary="created: /tmp/created.txt",
            session_id="session-2",
        )
        response = cleanhouse_module.get_events()
        self.assertIsInstance(response, list)
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["event_type"], "created")
        self.assertIn("path", response[0])
        self.assertIn("timestamp", response[0])

    def test_events_endpoint_rejects_non_integer_limit(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "abc"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit must be an integer")

    def test_events_endpoint_rejects_zero_limit(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "0"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit must be at least 1")

    def test_events_endpoint_rejects_limit_above_maximum(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "1001"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit exceeds maximum")

    def test_events_endpoint_rejects_malformed_session_id(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": "bad session"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "session_id format is invalid")

    def test_events_endpoint_row_schema_contract(self):
        events.insert_event(
            event_type="created",
            path="/tmp/schema-events.txt",
            summary="created: /tmp/schema-events.txt",
            session_id="session-events-schema",
            observed_vs_expected={"observed": "created"},
            evidence_refs=["local://cleanhouse/test/events-schema"],
            data={"ok": True},
        )
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "10", "session_id": "session-events-schema"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_events()
        self.assertIsInstance(response, list)
        self.assertGreaterEqual(len(response), 1)
        row = response[0]
        for key in ("id", "timestamp", "session_id", "event_type", "path", "summary"):
            self.assertIn(key, row)
        self.assertIsInstance(row.get("observed_vs_expected"), dict)
        self.assertIsInstance(row.get("evidence_refs"), list)
        self.assertIsInstance(row.get("data"), dict)

    def test_events_endpoint_rejects_invalid_row_field_types(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        bad_rows = [
            {
                "id": "evt-1",
                "timestamp": "2026-05-30T00:00:00Z",
                "session_id": "session-typed",
                "event_type": "created",
                "path": "/tmp/file.txt",
                "summary": "",
                "observed_vs_expected": {},
                "evidence_refs": [],
                "data": {},
            }
        ]
        with patch.object(events, "list_events", return_value=bad_rows):
            response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "events payload schema invalid")

    def test_events_endpoint_rejects_invalid_evidence_ref_shape(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        bad_rows = [
            {
                "id": "evt-2",
                "timestamp": "2026-05-30T00:00:00Z",
                "session_id": "session-typed",
                "event_type": "created",
                "path": "/tmp/file.txt",
                "summary": "created",
                "observed_vs_expected": {},
                "evidence_refs": [123],
                "data": {},
            }
        ]
        with patch.object(events, "list_events", return_value=bad_rows):
            response = cleanhouse_module.get_events()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "events payload schema invalid")

    def test_receipts_endpoint_creates_and_returns_rows(self):
        events.insert_event(
            event_type="prompt_event",
            path="/tmp/prompt.txt",
            summary="prompt: /tmp/prompt.txt",
            session_id="session-3",
        )
        events.insert_event(
            event_type="shell_event",
            path="/bin/bash",
            summary="shell: run",
            session_id="session-3",
        )
        events.insert_event(
            event_type="created",
            path="/tmp/file.txt",
            summary="created: /tmp/file.txt",
            session_id="session-3",
        )
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": "session-3", "limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertIsInstance(response, list)
        self.assertGreaterEqual(len(response), 1)
        row = response[0]
        self.assertIn("id", row)
        self.assertIn("event_ids", row)
        self.assertIn("timestamp", row)
        self.assertIn("summary", row)

    def test_receipts_endpoint_rejects_non_integer_limit(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "abc"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit must be an integer")

    def test_receipts_endpoint_rejects_zero_limit(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "0"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit must be at least 1")

    def test_receipts_endpoint_rejects_limit_above_maximum(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"limit": "1001"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "limit exceeds maximum")

    def test_receipts_endpoint_rejects_malformed_session_id(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": "bad session"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "session_id format is invalid")

    def test_receipts_endpoint_row_schema_contract(self):
        session_id = "session-receipts-schema"
        events.insert_event(
            event_type="prompt_event",
            path="/tmp/schema-receipt-prompt.txt",
            summary="prompt: /tmp/schema-receipt-prompt.txt",
            session_id=session_id,
        )
        events.insert_event(
            event_type="created",
            path="/tmp/schema-receipt-file.txt",
            summary="created: /tmp/schema-receipt-file.txt",
            session_id=session_id,
        )
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": session_id, "limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        response = cleanhouse_module.get_receipts_list()
        self.assertIsInstance(response, list)
        self.assertGreaterEqual(len(response), 1)
        row = response[0]
        for key in ("id", "timestamp", "session_id", "summary", "event_ids"):
            self.assertIn(key, row)
        self.assertIsInstance(row.get("event_ids"), list)
        self.assertIsInstance(row.get("affected_paths"), list)

    def test_receipts_endpoint_rejects_invalid_row_field_types(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": "session-receipts-schema", "limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        bad_rows = [
            {
                "id": "receipt-1",
                "timestamp": "2026-05-30T00:00:00Z",
                "session_id": "session-receipts-schema",
                "summary": "ok",
                "event_ids": ["evt-1", ""],
                "affected_paths": ["/tmp/file.txt"],
            }
        ]
        with patch.object(events, "ensure_latest_receipt", return_value=None), patch.object(events, "list_receipts", return_value=bad_rows):
            response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "receipts payload schema invalid")

    def test_receipts_endpoint_rejects_invalid_affected_paths_shape(self):
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": "session-receipts-schema", "limit": "10"},
            headers={},
            get_json=lambda silent=True: None,
        )
        bad_rows = [
            {
                "id": "receipt-2",
                "timestamp": "2026-05-30T00:00:00Z",
                "session_id": "session-receipts-schema",
                "summary": "ok",
                "event_ids": ["evt-1"],
                "affected_paths": [42],
            }
        ]
        with patch.object(events, "ensure_latest_receipt", return_value=None), patch.object(events, "list_receipts", return_value=bad_rows):
            response = cleanhouse_module.get_receipts_list()
        self.assertEqual(response[1], 400)
        self.assertEqual(response[0]["message"], "receipts payload schema invalid")

    def test_objective_markers_and_receipt_enrichment(self):
        objective_id = "o-cleanhouse-test"
        session_id = "session-objective"

        events.insert_event(
            event_type="objective_start",
            path=f"/objectives/{objective_id}",
            summary="Fix test objective",
            session_id=session_id,
        )
        events.insert_event(
            event_type="shell_event",
            path="/bin/bash",
            summary="shell_event: run test",
            session_id=session_id,
        )
        events.insert_event(
            event_type="modified",
            path="/tmp/objective.txt",
            summary="modified /tmp/objective.txt",
            session_id=session_id,
        )
        events.insert_event(
            event_type="objective_end",
            path=f"/objectives/{objective_id}",
            summary="",
            session_id=session_id,
        )

        receipt_id = events.ensure_latest_receipt(session_id=session_id)
        self.assertIsNotNone(receipt_id)
        receipts = events.list_receipts(limit=20, session_id=session_id)
        self.assertGreaterEqual(len(receipts), 1)
        latest = receipts[0]
        self.assertEqual(latest.get("objective_id"), objective_id)
        self.assertEqual(latest.get("objective_count"), 1)
        self.assertEqual(latest.get("session_count"), 1)
        self.assertEqual(latest.get("event_count"), 4)
        self.assertIn("event_ids", latest)
        self.assertIn("shell_event_count", latest)
        self.assertIn("process_event_count", latest)
        self.assertIn("/tmp/objective.txt", latest.get("affected_paths", []))

    def test_prompt_and_approval_events_are_receipted(self):
        session_id = "session-approval-receipt"
        events.insert_event(
            event_type="prompt_event",
            path="/prompts/prompt-avatar",
            summary="prompt_event: update avatar",
            session_id=session_id,
        )
        events.insert_event(
            event_type="approval_requested",
            path="/approval-queue/approval-avatar",
            summary="approval_requested: review avatar mutation",
            session_id=session_id,
        )
        events.insert_event(
            event_type="approval_resolved",
            path="/approval-queue/approval-avatar",
            summary="approval_resolved: rejected",
            session_id=session_id,
        )

        receipt_id = events.ensure_latest_receipt(session_id=session_id)
        self.assertIsNotNone(receipt_id)
        receipts = events.list_receipts(limit=10, session_id=session_id)
        latest = receipts[0]
        self.assertEqual(latest.get("event_count"), 3)
        self.assertIn("/prompts/prompt-avatar", latest.get("affected_paths", []))
        self.assertIn("/approval-queue/approval-avatar", latest.get("affected_paths", []))

    def test_objective_endpoints_create_objective_events(self):
        session_id = "session-objective-api"
        cleanhouse_module.request = SimpleNamespace(
            args={"session_id": session_id},
            headers={},
            get_json=lambda silent=True: {
                "objective": "Fix avatar",
                "session_id": session_id,
            },
        )
        start_response = cleanhouse_module.start_objective()
        self.assertEqual(start_response.get("status"), "ok")
        self.assertEqual(start_response.get("session_id"), session_id)
        objective_id = start_response.get("objective_id")
        self.assertIsInstance(objective_id, str)
        self.assertNotEqual(objective_id, "")

        events_rows = events.list_events(limit=10, session_id=session_id)
        self.assertTrue(any(
            row["event_type"] == "objective_start" and row["path"].endswith(f"/objectives/{objective_id}")
            for row in events_rows
        ))

        cleanhouse_module.request = SimpleNamespace(
            args={},
            headers={},
            get_json=lambda silent=True: {
                "objective_id": objective_id,
                "session_id": session_id,
            },
        )
        end_response = cleanhouse_module.end_objective()
        self.assertEqual(end_response.get("status"), "ok")
        self.assertEqual(end_response.get("session_id"), session_id)
        self.assertEqual(end_response.get("objective_id"), objective_id)

    def test_writer_queue_saturation_records_drop_metrics(self):
        original_queue = events._EVENT_QUEUE
        original_start_writer = events._start_db_writer
        original_metrics = events.get_writer_metrics()

        small_queue = queue.Queue(maxsize=1)
        events._EVENT_QUEUE = small_queue
        events._start_db_writer = lambda: None

        try:
            small_queue.put({
                "record_type": "event",
                "event_type": "created",
                "path": "/tmp/seed.txt",
                "summary": "created",
                "session_id": "session-metrics",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }, timeout=0.1)

            events.insert_event_async(
                event_type="modified",
                path="/tmp/full.txt",
                summary="modified",
                session_id="session-metrics",
            )

            after = events.get_writer_metrics()
            self.assertGreater(after.get("dropped", 0), original_metrics.get("dropped", 0))
        finally:
            events._EVENT_QUEUE = original_queue
            events._start_db_writer = original_start_writer
            events._stop_db_writer()

    def test_runtime_status_includes_watcher_and_writer_health(self):
        status = events.get_runtime_status()
        self.assertIn("watcher", status)
        self.assertIn("writer", status)
        self.assertIn("queue", status)
        self.assertIn("degradation", status)
        self.assertIn(status["watcher"]["status"], {"running", "stopped", "unavailable"})
        self.assertIn("collector_status", status["watcher"])
        self.assertIn("state", status["watcher"])
        self.assertIn("support_status", status["watcher"])
        self.assertIn("queue_depth", status["writer"])
        self.assertIn("collector_status", status["writer"])
        self.assertIn("queue", status["writer"])
        self.assertIn("metrics", status["writer"])
        self.assertIn("timestamps", status["writer"])
        self.assertIn("degradation", status["writer"])
        self.assertIn("last_event_at", status)
        self.assertIn("last_event_type", status)

    def test_event_writer_starts_without_waiting_for_first_event(self):
        events._stop_db_writer()

        first = events.start_event_writer()
        second = events.start_event_writer()

        self.assertEqual(first["status"], "running")
        self.assertEqual(first["collector_status"], "ok")
        self.assertEqual(second["status"], "running")
        self.assertEqual(second["collector_status"], "ok")

    def test_event_writer_start_failure_remains_visible(self):
        events._stop_db_writer()

        with patch.object(threading.Thread, "start", side_effect=RuntimeError("start failed")):
            health = events.start_event_writer()

        self.assertEqual(health["status"], "stopped")
        self.assertEqual(health["collector_status"], "failure")
        self.assertEqual(health["last_error"]["source"], "writer_start")
        self.assertTrue(health["degradation"]["degraded"])

    def test_dead_watcher_observer_is_reported_as_an_error(self):
        class DeadObserver:
            @staticmethod
            def is_alive():
                return False

        original_state = dict(events._WATCHER_STATE)
        try:
            events._WATCHER_STATE.update({
                "observer": DeadObserver(),
                "watch_dir": Path(self._tmp.name),
                "last_error": None,
                "started_at": "2026-08-22T00:00:00+00:00",
                "stop_requested": False,
            })

            with patch.object(events, "FileSystemEventHandler", object()), patch.object(events, "Observer", object()):
                status = events.get_watcher_status()

            self.assertEqual(status["collector_status"], "error")
            self.assertEqual(status["last_error"]["source"], "watcher_observer_exit")
            self.assertEqual(status["started_at"], "2026-08-22T00:00:00+00:00")
        finally:
            events._WATCHER_STATE.clear()
            events._WATCHER_STATE.update(original_state)

    def test_filesystem_watcher_filters_event_db_sidecars_without_drops(self):
        original_metrics = events.get_writer_metrics()
        sidecars = [
            self._db_path,
            self._db_path.with_name(self._db_path.name + "-wal"),
            self._db_path.with_name(self._db_path.name + "-shm"),
            self._db_path.with_name(self._db_path.name + "-journal"),
        ]

        for path in sidecars:
            events.insert_event_async(
                event_type="modified",
                path=str(path),
                summary=f"modified: {path}",
                session_id="sidecar-filter",
                source_surface="filesystem_watcher",
            )

        rows = events.list_events(limit=10, session_id="sidecar-filter")
        health = events.get_writer_health()
        metrics = health["metrics"]
        self.assertEqual(rows, [])
        self.assertEqual(metrics.get("filtered", 0), original_metrics.get("filtered", 0) + len(sidecars))
        self.assertEqual(metrics.get("dropped", 0), original_metrics.get("dropped", 0))
        self.assertIsNotNone(health["timestamps"].get("last_filtered_at"))

    def test_writer_queue_failure_surfaces_in_health(self):
        original_queue = events._EVENT_QUEUE
        original_start_writer = events._start_db_writer
        original_metrics = events.get_writer_metrics()

        small_queue = queue.Queue(maxsize=1)
        events._EVENT_QUEUE = small_queue
        events._start_db_writer = lambda: None

        try:
            small_queue.put({
                "record_type": "event",
                "event_type": "created",
                "path": "/tmp/seed.txt",
                "summary": "created",
                "session_id": "session-metrics",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }, timeout=0.1)

            events.insert_event_async(
                event_type="modified",
                path="/tmp/full.txt",
                summary="modified",
                session_id="session-metrics",
            )

            health = events.get_writer_health()
            metrics = health["metrics"]
            self.assertGreater(metrics.get("write_failures", 0), original_metrics.get("write_failures", 0))
            self.assertEqual(health["collector_status"], "failure")
            self.assertEqual(health["last_error"]["source"], "queue_full")
            self.assertTrue(health["degradation"]["degraded"])
            self.assertIn("queue_full", health["degradation"]["reasons"])
        finally:
            events._EVENT_QUEUE = original_queue
            events._start_db_writer = original_start_writer
            events._stop_db_writer()


if __name__ == "__main__":
    unittest.main()
