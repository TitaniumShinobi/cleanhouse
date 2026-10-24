"""Focused acceptance tests for the server-owned Network collector.

The suite uses only in-memory callbacks and fake capture processes.  It must
never invoke tshark or depend on a browser/SSE client being present.
"""

from __future__ import annotations

import io
import queue
import subprocess
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.network_collector import NetworkCollectorSupervisor


class _BlockingStdout:
    """Small file-like iterator that unblocks when its process is terminated."""

    _CLOSED = object()

    def __init__(self, lines=()):
        self._lines = queue.Queue()
        self._closed = False
        for line in lines:
            self._lines.put(line)

    def __iter__(self):
        return self

    def __next__(self):
        value = self._lines.get(timeout=2)
        if value is self._CLOSED:
            raise StopIteration
        return value

    def close(self):
        if not self._closed:
            self._closed = True
            self._lines.put(self._CLOSED)


class _FakeProcess:
    def __init__(self, pid: int, *, lines=(), exit_code=None, stderr=""):
        self.pid = pid
        self.stdout = _BlockingStdout(lines)
        self.stderr = io.StringIO(stderr)
        self.returncode = exit_code
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exited = threading.Event()
        if exit_code is not None:
            self.stdout.close()
            self._exited.set()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake-tshark", timeout)
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15
        self.stdout.close()
        self._exited.set()

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self.stdout.close()
        self._exited.set()


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class NetworkCollectorArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.persisted = []
        self.receipts = []
        self.collectors = []

    def tearDown(self):
        for collector in self.collectors:
            collector.stop(timeout=1)

    def _collector(self, **overrides):
        options = {
            "command_factory": lambda: {
                "command": ["fake-tshark"],
                "cwd": None,
                "interface": "test0",
            },
            "process_factory": lambda command, cwd: _FakeProcess(4000),
            "parse_line": lambda line, interface: {
                "event_id": line.strip(),
                "payload": line.strip(),
                "interface": interface,
            },
            "enrich_event": lambda event: dict(event),
            "persist_event": self.persisted.append,
            "persist_receipt": self.receipts.append,
            "boot_id": "test-boot",
            "replay_size": 8,
            "subscriber_queue_size": 8,
            "watchdog_backoff_seconds": 0.001,
        }
        options.update(overrides)
        collector = NetworkCollectorSupervisor(**options)
        self.collectors.append(collector)
        return collector

    def _publish(self, collector, event_id):
        return collector.publish_event({"event_id": event_id, "payload": event_id})

    def test_one_capture_fans_out_same_ordered_envelopes_to_multiple_subscribers(self):
        process = _FakeProcess(4101)
        process_factory = Mock(return_value=process)
        collector = self._collector(process_factory=process_factory)

        collector.start()
        self.assertTrue(_wait_until(lambda: collector.health()["state"] == "running"))
        first = collector.subscribe()
        second = collector.subscribe()
        collector.start()
        sent = [self._publish(collector, event_id) for event_id in ("packet-a", "packet-b")]
        first_seen = [first.get(timeout=0.2), first.get(timeout=0.2)]
        second_seen = [second.get(timeout=0.2), second.get(timeout=0.2)]

        self.assertEqual(process_factory.call_count, 1)
        self.assertEqual([item["cursor"] for item in first_seen], [item["cursor"] for item in sent])
        self.assertEqual([item["cursor"] for item in second_seen], [item["cursor"] for item in sent])
        self.assertEqual([item["event"]["event_id"] for item in first_seen], ["packet-a", "packet-b"])
        self.assertEqual([item["cursor"] for item in self.persisted], [item["cursor"] for item in sent])
        self.assertEqual(collector.health()["generation"], 1)
        self.assertEqual(collector.health()["subscriber_count"], 2)
        first.close()
        second.close()

    def test_collection_and_canonical_persistence_continue_with_zero_subscribers(self):
        process = _FakeProcess(4151, lines=("background-a\n", "background-b\n"))
        process_factory = Mock(return_value=process)
        collector = self._collector(process_factory=process_factory)

        collector.start()
        self.assertTrue(_wait_until(lambda: len(self.persisted) == 2))
        snapshot = collector.snapshot()

        self.assertEqual(process_factory.call_count, 1)
        self.assertEqual(collector.health()["subscriber_count"], 0)
        self.assertEqual([item["event"]["event_id"] for item in self.persisted], ["background-a", "background-b"])
        self.assertEqual(snapshot["cursor"], self.persisted[-1]["cursor"])
        self.assertEqual(snapshot["high_water_cursor"], self.persisted[-1]["cursor"])
        self.assertNotEqual(self.persisted[0]["cursor"], self.persisted[-1]["cursor"])

    def test_snapshot_cursor_handoff_replays_then_tails_each_event_exactly_once(self):
        collector = self._collector()
        self._publish(collector, "before-snapshot")
        cursor = collector.snapshot()["cursor"]
        expected = [self._publish(collector, event_id) for event_id in ("during-handoff", "after-handoff")]

        subscriber = collector.subscribe(after_cursor=cursor)
        replayed = [subscriber.get(timeout=0.2), subscriber.get(timeout=0.2)]
        expected.append(self._publish(collector, "live-tail"))
        replayed.append(subscriber.get(timeout=0.2))

        self.assertEqual([item["cursor"] for item in replayed], [item["cursor"] for item in expected])
        self.assertEqual(len({item["cursor"] for item in replayed}), 3)
        self.assertEqual(
            [item["event"]["event_id"] for item in replayed],
            ["during-handoff", "after-handoff", "live-tail"],
        )
        subscriber.close()

    def test_refresh_reports_new_high_water_without_restarting_capture(self):
        process = _FakeProcess(4201)
        process_factory = Mock(return_value=process)
        collector = self._collector(process_factory=process_factory)

        collector.start()
        self.assertTrue(_wait_until(lambda: collector.health()["state"] == "running"))
        generation = collector.health()["generation"]
        before_cursor = collector.snapshot()["cursor"]
        self._publish(collector, "refresh-visible")
        refreshed = collector.refresh(timeout=0.2)

        self.assertEqual(process_factory.call_count, 1)
        self.assertEqual(refreshed["generation"], generation)
        self.assertEqual(refreshed["pid"], 4201)
        self.assertEqual(refreshed["high_water_cursor"], collector.snapshot()["cursor"])
        self.assertNotEqual(refreshed["high_water_cursor"], before_cursor)

    def test_health_exposes_source_event_time_and_ingestion_latency(self):
        collector = self._collector()
        source_time = datetime.now(timezone.utc) - timedelta(seconds=2)

        collector.publish_event({
            "event_id": "latency-visible",
            "timestamp": source_time.isoformat().replace("+00:00", "Z"),
        })
        health = collector.health()

        self.assertEqual(health["last_event_timestamp"], source_time.isoformat().replace("+00:00", "Z"))
        self.assertGreaterEqual(health["ingestion_latency_ms"], 1500)
        self.assertLess(health["ingestion_latency_ms"], 5000)

    def test_supervised_capture_coalesces_repeated_flow_samples_with_explicit_metrics(self):
        process = _FakeProcess(4201, lines=("flow-a\n", "flow-a\n", "flow-b\n"))
        collector = self._collector(
            process_factory=Mock(return_value=process),
            event_identity=lambda event: str(event.get("payload") or ""),
            coalesce_window_seconds=1.0,
        )

        collector.start()
        self.assertTrue(_wait_until(lambda: collector.health()["startup_packets_captured"] >= 3))
        health = collector.health()

        self.assertEqual(health["startup_packet_events_parsed"], 3)
        self.assertEqual(health["startup_canonical_packet_events_emitted"], 2)
        self.assertEqual(health["coalesced_packet_events"], 1)
        self.assertEqual(health["coalesce_window_seconds"], 1.0)
        self.assertEqual([item["event"]["event_id"] for item in self.persisted], ["flow-a", "flow-b"])

    def test_coalescing_window_is_measured_from_last_emitted_sample(self):
        collector = self._collector(
            event_identity=lambda event: str(event.get("payload") or ""),
            coalesce_window_seconds=1.0,
        )
        event = {"payload": "continuous-flow"}

        with patch("backend.network_collector.time.monotonic", side_effect=(10.0, 10.4, 10.8, 11.1)):
            self.assertFalse(collector._should_coalesce(event))
            self.assertTrue(collector._should_coalesce(event))
            self.assertTrue(collector._should_coalesce(event))
            self.assertFalse(collector._should_coalesce(event))

        self.assertEqual(collector.health()["coalesced_packet_events"], 2)

    def test_watchdog_restarts_failed_capture_and_emits_typed_continuity_receipts(self):
        failed = _FakeProcess(4301, exit_code=17, stderr="capture failed")
        recovered = _FakeProcess(4302)
        process_factory = Mock(side_effect=[failed, recovered])
        collector = self._collector(process_factory=process_factory)

        collector.start()
        self.assertTrue(_wait_until(lambda: collector.health()["generation"] >= 2))
        self.assertTrue(_wait_until(lambda: any(item["type"] == "collector.recovered" for item in self.receipts)))
        health = collector.health()

        self.assertEqual(process_factory.call_count, 2)
        self.assertEqual(health["pid"], 4302)
        self.assertEqual(health["restart_count"], 1)
        receipt_types = [receipt["type"] for receipt in self.receipts]
        self.assertIn("collector.failure", receipt_types)
        self.assertIn("collector.gap", receipt_types)
        self.assertIn("collector.recovered", receipt_types)

    def test_bounded_subscriber_queue_emits_explicit_gap_receipt(self):
        collector = self._collector(subscriber_queue_size=2)
        subscriber = collector.subscribe()

        self._publish(collector, "queued-a")
        self._publish(collector, "queued-b")
        self._publish(collector, "queued-c")

        gap_receipt = subscriber.get(timeout=0.2)
        self.assertEqual(gap_receipt["type"], "collector.gap")
        gap = gap_receipt["event"]
        self.assertEqual(gap["reason"], "subscriber_queue_overflow")
        self.assertTrue(gap["subscriber_id"])
        self.assertLessEqual(gap["gap_from_sequence"], gap["gap_to_sequence"])
        self.assertEqual(gap["dropped_count"], 3)
        self.assertEqual(collector.health()["subscriber_drops"], 3)
        subscriber.close()

    def test_stop_terminates_capture_and_joins_watchdog_thread(self):
        process = _FakeProcess(4401)
        process_factory = Mock(return_value=process)
        collector = self._collector(process_factory=process_factory)

        collector.start()
        self.assertTrue(_wait_until(lambda: collector.health()["state"] == "running"))
        receipt = collector.stop(timeout=1)

        self.assertEqual(receipt["type"], "collector.stopped")
        self.assertTrue(receipt["event"]["joined"])
        self.assertEqual(receipt["event"]["state"], "stopped")
        self.assertEqual(process.terminate_calls, 1)
        self.assertFalse(collector.health()["thread_alive"])


if __name__ == "__main__":
    unittest.main()
