import os
import tempfile
import unittest
import queue
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import sys
import types

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")

    class _Blueprint:
        def __init__(self, name, import_name):
            self.name = name
            self.import_name = import_name

        def route(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def after_request(self, func):
            return func

    flask_stub.Blueprint = _Blueprint
    flask_stub.jsonify = lambda obj=None, **kwargs: obj if obj is not None else kwargs
    flask_stub.request = SimpleNamespace(args={}, headers={})
    sys.modules["flask"] = flask_stub

from backend import events
from backend.api import cleanhouse as cleanhouse_module

class CleanHouseEventStorageTests(unittest.TestCase):
    def setUp(self):
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
        self.assertIn("degradation", status["writer"])

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
