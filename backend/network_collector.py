"""Server-owned, replayable network packet collector.

The collector deliberately has no Flask dependency.  It owns one capture
process, persists each canonical event before fan-out, and gives each
subscriber a bounded queue with explicit continuity receipts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import copy
from datetime import datetime, timezone
import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Optional


Envelope = dict[str, Any]
CommandFactory = Callable[[], dict[str, Any]]
EventCallback = Callable[[Envelope], Optional[Envelope]]
EventIdentity = Callable[[dict[str, Any]], str]


_CLOSED = object()
_LOG = logging.getLogger(__name__)


class CaptureEngineUnavailable(RuntimeError):
    """Raised when the separately reviewed capture-engine bundle is absent."""


@dataclass
class _SubscriberState:
    subscriber_id: str
    queue: "queue.Queue[Envelope | object]"
    initial_cursor: str = ""
    dropped: int = 0
    closed: bool = False


class NetworkCollectorSubscription:
    """A closeable view over one collector subscriber queue."""

    def __init__(self, owner: "NetworkCollectorSupervisor", state: _SubscriberState) -> None:
        self._owner = owner
        self._state = state

    @property
    def subscriber_id(self) -> str:
        return self._state.subscriber_id

    @property
    def initial_cursor(self) -> str:
        return self._state.initial_cursor

    def get(self, timeout: float | None = None) -> Envelope | None:
        item = self._state.queue.get(timeout=timeout)
        if item is _CLOSED:
            return None
        return item if isinstance(item, dict) else None

    def close(self) -> None:
        self._owner._close_subscriber(self._state.subscriber_id)


class NetworkCollectorSupervisor:
    """Own a single capture process and an ordered canonical event stream."""

    def __init__(
        self,
        command_factory: CommandFactory,
        parse_line: Callable[[str, str], dict[str, Any] | None],
        enrich_event: Callable[[dict[str, Any]], dict[str, Any]],
        persist_event: EventCallback,
        persist_receipt: EventCallback,
        *,
        boot_id: str,
        replay_size: int = 2048,
        subscriber_queue_size: int = 256,
        watchdog_backoff_seconds: float = 1.0,
        process_factory: Callable[[list[str], str | None], Any] | None = None,
        event_identity: EventIdentity | None = None,
        coalesce_window_seconds: float = 0.0,
        coalesce_identity_limit: int = 8192,
    ) -> None:
        if replay_size < 1:
            raise ValueError("replay_size must be positive")
        if subscriber_queue_size < 2:
            raise ValueError("subscriber_queue_size must be at least 2")
        self._command_factory = command_factory
        self._parse_line = parse_line
        self._enrich_event = enrich_event
        self._persist_event = persist_event
        self._persist_receipt = persist_receipt
        self._boot_id = str(boot_id)
        self._replay_size = int(replay_size)
        self._subscriber_queue_size = int(subscriber_queue_size)
        self._watchdog_backoff_seconds = max(0.01, float(watchdog_backoff_seconds))
        self._process_factory = process_factory or self._default_process_factory
        self._event_identity = event_identity
        self._coalesce_window_seconds = max(0.0, float(coalesce_window_seconds))
        self._coalesce_identity_limit = max(64, int(coalesce_identity_limit))

        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._publish_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: Any = None
        self._subscribers: dict[str, _SubscriberState] = {}
        self._replay: deque[Envelope] = deque(maxlen=self._replay_size)

        self._state = "stopped"
        self._generation = 0
        self._restart_count = 0
        self._sequence = 0
        self._pid: int | None = None
        self._interface = ""
        self._started_at: float | None = None
        self._last_packet_at: float | None = None
        self._last_event_timestamp = ""
        self._last_ingestion_latency_ms: float | None = None
        self._last_packet_sequence = 0
        self._last_exit_at: float | None = None
        self._last_exit_code: int | None = None
        self._last_error = ""
        self._last_reason = ""
        self._last_recovery_at: float | None = None
        self._current_backoff_seconds = 0.0
        self._next_restart_at: float | None = None
        self._persistence_high_water_sequence = 0
        self._persistence_failures = 0
        self._receipt_persistence_failures = 0
        self._subscriber_drops = 0
        self._replay_evictions = 0
        self._packets_captured = 0
        self._packet_events_parsed = 0
        self._canonical_packet_events_emitted = 0
        self._coalesced_packet_events = 0
        self._coalesce_seen: dict[str, float] = {}

    def _should_coalesce(self, event: dict[str, Any]) -> bool:
        if self._event_identity is None or self._coalesce_window_seconds <= 0:
            return False
        identity = str(self._event_identity(event) or "").strip()
        if not identity:
            return False
        now = time.monotonic()
        with self._state_lock:
            previous = self._coalesce_seen.get(identity)
            if previous is not None and now - previous < self._coalesce_window_seconds:
                self._coalesced_packet_events += 1
                return True
            self._coalesce_seen.pop(identity, None)
            self._coalesce_seen[identity] = now
            while len(self._coalesce_seen) > self._coalesce_identity_limit:
                self._coalesce_seen.pop(next(iter(self._coalesce_seen)))
        return False

    @staticmethod
    def _default_process_factory(command: list[str], cwd: str | None) -> subprocess.Popen[str]:
        return subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )

    def _cursor(self, sequence: int) -> str:
        return f"{self._boot_id}:{max(0, int(sequence))}"

    def _parse_cursor(self, cursor: Any) -> tuple[int | None, bool]:
        text = str(cursor or "").strip()
        if not text:
            return None, True
        if text.isdigit():
            return int(text), True
        try:
            cursor_boot, raw_sequence = text.rsplit(":", 1)
            return int(raw_sequence), cursor_boot == self._boot_id
        except (TypeError, ValueError):
            return None, False

    def _base_envelope(self, item_type: str, event: dict[str, Any], sequence: int) -> Envelope:
        cursor = self._cursor(sequence)
        normalized_event = copy.deepcopy(event)
        normalized_event.setdefault("sequence", sequence)
        normalized_event.setdefault("collector_sequence", sequence)
        normalized_event.setdefault("cursor", cursor)
        normalized_event.setdefault("collector_cursor", cursor)
        normalized_event.setdefault("server_boot_id", self._boot_id)
        with self._state_lock:
            normalized_event.setdefault("collector_generation", self._generation)
        return {
            "type": item_type,
            "sequence": sequence,
            "cursor": cursor,
            "event": normalized_event,
        }

    @staticmethod
    def _callback_envelope_result(envelope: Envelope, result: Any) -> Envelope:
        if not isinstance(result, dict):
            return envelope
        if isinstance(result.get("event"), dict) and result.get("type"):
            merged = copy.deepcopy(result)
            merged.setdefault("type", envelope["type"])
            merged.setdefault("sequence", envelope["sequence"])
            merged.setdefault("cursor", envelope["cursor"])
            return merged
        updated = copy.deepcopy(envelope)
        updated["event"] = copy.deepcopy(result)
        updated["event"].setdefault("sequence", envelope["sequence"])
        updated["event"].setdefault("collector_sequence", envelope["sequence"])
        updated["event"].setdefault("cursor", envelope["cursor"])
        updated["event"].setdefault("collector_cursor", envelope["cursor"])
        return updated

    def _append_and_fan_out(self, envelope: Envelope) -> None:
        with self._state_lock:
            if len(self._replay) == self._replay.maxlen:
                self._replay_evictions += 1
            self._replay.append(copy.deepcopy(envelope))
            subscribers = list(self._subscribers.values())

            for subscriber in subscribers:
                if subscriber.closed:
                    continue
                try:
                    subscriber.queue.put_nowait(copy.deepcopy(envelope))
                    continue
                except queue.Full:
                    pass

                dropped_sequences: list[int] = []
                while True:
                    try:
                        dropped = subscriber.queue.get_nowait()
                    except queue.Empty:
                        break
                    if isinstance(dropped, dict):
                        dropped_sequences.append(int(dropped.get("sequence") or 0))
                dropped_sequences.append(int(envelope["sequence"]))
                subscriber.dropped += len(dropped_sequences)
                self._subscriber_drops += len(dropped_sequences)
                gap_sequence = int(envelope["sequence"])
                gap = self._base_envelope(
                    "collector.gap",
                    {
                        "reason": "subscriber_queue_overflow",
                        "state": "degraded",
                        "subscriber_id": subscriber.subscriber_id,
                        "gap_from_sequence": min(dropped_sequences),
                        "gap_to_sequence": max(dropped_sequences),
                        "dropped_count": len(dropped_sequences),
                    },
                    gap_sequence,
                )
                subscriber.queue.put_nowait(gap)
            self._state_changed.notify_all()

    def _publish_receipt(self, receipt_type: str, details: dict[str, Any]) -> Envelope:
        with self._publish_lock:
            sequence = self._sequence + 1
            envelope = self._base_envelope(receipt_type, details, sequence)
            try:
                envelope = self._callback_envelope_result(
                    envelope,
                    self._persist_receipt(copy.deepcopy(envelope)),
                )
                self._persistence_high_water_sequence = sequence
            except Exception as exc:
                with self._state_lock:
                    self._receipt_persistence_failures += 1
                    self._last_error = f"receipt persistence failed: {exc}"
            self._sequence = sequence
            self._append_and_fan_out(envelope)
            return copy.deepcopy(envelope)

    def publish_event(self, event: dict[str, Any]) -> Envelope:
        """Persist and publish one event; useful as a deterministic ingestion seam."""
        enriched = self._enrich_event(copy.deepcopy(event))
        with self._publish_lock:
            sequence = self._sequence + 1
            envelope = self._base_envelope("network.event", enriched, sequence)
            try:
                envelope = self._callback_envelope_result(
                    envelope,
                    self._persist_event(copy.deepcopy(envelope)),
                )
                self._persistence_high_water_sequence = sequence
            except Exception as exc:
                self._persistence_failures += 1
                self._last_error = f"event persistence failed: {exc}"
                failed_event = envelope.get("event") if isinstance(envelope.get("event"), dict) else {}
                envelope = self._base_envelope(
                    "collector.gap",
                    {
                        "reason": "persistence_failed",
                        "state": "degraded",
                        "lost_event_id": failed_event.get("event_id"),
                        "gap_from_sequence": sequence,
                        "gap_to_sequence": sequence,
                        "error": str(exc)[:512],
                    },
                    sequence,
                )
                try:
                    envelope = self._callback_envelope_result(
                        envelope,
                        self._persist_receipt(copy.deepcopy(envelope)),
                    )
                    self._persistence_high_water_sequence = sequence
                except Exception as receipt_exc:
                    self._receipt_persistence_failures += 1
                    self._last_error = f"gap receipt persistence failed: {receipt_exc}"
            self._sequence = sequence
            with self._state_lock:
                if envelope.get("type") == "network.event":
                    self._last_packet_at = time.time()
                    self._last_packet_sequence = sequence
                    persisted_event = envelope.get("event") if isinstance(envelope.get("event"), dict) else {}
                    self._last_event_timestamp = str(persisted_event.get("timestamp") or "")
                    self._last_ingestion_latency_ms = self._event_ingestion_latency_ms(
                        self._last_event_timestamp,
                        self._last_packet_at,
                    )
            self._append_and_fan_out(envelope)
            return copy.deepcopy(envelope)

    @staticmethod
    def _event_ingestion_latency_ms(timestamp: Any, ingested_at: float) -> float | None:
        text = str(timestamp or "").strip()
        if not text:
            return None
        try:
            event_epoch = float(text)
            if event_epoch > 100000000000:
                event_epoch /= 1000.0
        except (TypeError, ValueError):
            try:
                event_epoch = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
            except (TypeError, ValueError):
                return None
        return max(0.0, round((float(ingested_at) - event_epoch) * 1000.0, 3))

    def _stderr_drain(self, stream: Any, chunks: deque[str]) -> None:
        if stream is None:
            return
        while not self._stop_event.is_set():
            try:
                value = stream.read(4096)
            except TypeError:
                value = stream.read()
            except Exception:
                return
            if not value:
                return
            chunks.append(str(value)[-4096:])

    @staticmethod
    def _wait_process(process: Any, timeout: float | None = None) -> int | None:
        try:
            return process.wait(timeout=timeout)
        except TypeError:
            return process.wait()

    @staticmethod
    def _permission_denied(value: Any) -> bool:
        text = str(value or "").lower()
        return any(marker in text for marker in (
            "permission denied",
            "operation not permitted",
            "cannot open bpf",
            "/dev/bpf",
        ))

    @classmethod
    def _failure_reason(cls, value: BaseException | str) -> tuple[str, str]:
        if isinstance(value, CaptureEngineUnavailable):
            return "degraded", "capture_engine_unavailable"
        if cls._permission_denied(value):
            return "blocked", "capture_permission_blocked"
        return "degraded", "capture_failed"

    def _terminate_process(self, process: Any) -> None:
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            return
        try:
            self._wait_process(process, timeout=2.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                return

    def _supervise(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            process = None
            stderr_chunks: deque[str] = deque(maxlen=32)
            packet_sequence_before = self._last_packet_sequence
            try:
                spec = self._command_factory()
                command = list(spec.get("command") or [])
                if not command:
                    raise RuntimeError("capture command unavailable")
                cwd = str(spec.get("cwd")) if spec.get("cwd") else None
                interface = str(spec.get("interface") or "")
                process = self._process_factory(command, cwd)
                with self._state_lock:
                    previous_generation = self._generation
                    self._generation += 1
                    if previous_generation:
                        self._restart_count += 1
                    self._process = process
                    self._pid = getattr(process, "pid", None)
                    self._interface = interface
                    self._state = "running"
                    self._last_error = ""
                    self._last_reason = ""
                    self._state_changed.notify_all()

                stderr_thread = threading.Thread(
                    target=self._stderr_drain,
                    args=(getattr(process, "stderr", None), stderr_chunks),
                    daemon=True,
                    name="cleanhouse-network-collector-stderr",
                )
                stderr_thread.start()

                receipt_type = "collector.started" if self._generation == 1 else "collector.recovered"
                if receipt_type == "collector.recovered":
                    self._last_recovery_at = time.time()
                self._publish_receipt(receipt_type, {
                    "state": "running",
                    "pid": self._pid,
                    "generation": self._generation,
                    "restart_count": self._restart_count,
                })

                stdout = getattr(process, "stdout", None)
                if stdout is None:
                    raise RuntimeError("capture stdout unavailable")
                for line in stdout:
                    if self._stop_event.is_set():
                        break
                    with self._state_lock:
                        self._packets_captured += 1
                        packet_number = self._packets_captured
                    parsed = self._parse_line(str(line), interface)
                    if parsed:
                        with self._state_lock:
                            self._packet_events_parsed += 1
                        if self._should_coalesce(parsed):
                            continue
                        envelope = self.publish_event(parsed)
                        emitted = envelope.get("type") == "network.event"
                        if emitted:
                            with self._state_lock:
                                self._canonical_packet_events_emitted += 1
                        _LOG.debug("network_startup_reconciliation %s", json.dumps({
                            "stage": "packet_captured",
                            "packet_number": packet_number,
                            "canonical_event_emitted": emitted,
                            "sequence": envelope.get("sequence"),
                            "event_id": (envelope.get("event") or {}).get("event_id"),
                            "reason": "parsed_and_emitted" if emitted else str((envelope.get("event") or {}).get("reason") or "canonical_event_not_emitted"),
                        }, sort_keys=True, default=str))
                    else:
                        _LOG.info("network_startup_reconciliation %s", json.dumps({
                            "stage": "packet_captured",
                            "packet_number": packet_number,
                            "canonical_event_emitted": False,
                            "reason": "parser_returned_no_operator_visible_packet_event",
                        }, sort_keys=True))

                if self._stop_event.is_set():
                    self._terminate_process(process)
                    break
                exit_code = self._wait_process(process, timeout=1.0)
                stderr_thread.join(timeout=0.25)
                stderr_text = "".join(stderr_chunks)[-4096:]
                with self._state_lock:
                    self._last_exit_at = time.time()
                    self._last_exit_code = exit_code
                    self._last_error = stderr_text or f"capture exited with code {exit_code}"
                    self._state = "blocked" if self._permission_denied(stderr_text) else "degraded"
                    self._last_reason = (
                        "capture_permission_blocked" if self._state == "blocked" else "capture_exited"
                    )
                self._publish_receipt("collector.failure", {
                    "state": self._state,
                    "reason": self._last_reason,
                    "exit_code": exit_code,
                    "stderr": stderr_text,
                    "generation": self._generation,
                    "restart_count": self._restart_count,
                    "last_packet_sequence": self._last_packet_sequence,
                })
                self._publish_receipt("collector.gap", {
                    "state": "degraded",
                    "reason": "capture_interrupted",
                    "generation": self._generation,
                    "gap_from_sequence": self._last_packet_sequence + 1,
                    "gap_to_sequence": self._sequence + 1,
                })
                consecutive_failures = 0 if self._last_packet_sequence > packet_sequence_before else consecutive_failures + 1
            except Exception as exc:
                if not self._stop_event.is_set():
                    failure_state, failure_reason = self._failure_reason(exc)
                    with self._state_lock:
                        self._last_exit_at = time.time()
                        self._last_error = str(exc)
                        self._state = failure_state
                        self._last_reason = failure_reason
                    self._publish_receipt("collector.failure", {
                        "state": self._state,
                        "reason": self._last_reason,
                        "error": str(exc)[:1024],
                        "generation": self._generation,
                        "restart_count": self._restart_count,
                        "last_packet_sequence": self._last_packet_sequence,
                    })
                    self._publish_receipt("collector.gap", {
                        "state": "degraded",
                        "reason": "capture_interrupted",
                        "generation": self._generation,
                        "gap_from_sequence": self._last_packet_sequence + 1,
                        "gap_to_sequence": self._sequence + 1,
                    })
                    consecutive_failures = 0 if self._last_packet_sequence > packet_sequence_before else consecutive_failures + 1
            finally:
                if process is not None:
                    self._terminate_process(process)
                with self._state_lock:
                    if self._process is process:
                        self._process = None
                        self._pid = None
                    self._state_changed.notify_all()
            if not self._stop_event.is_set():
                backoff = min(
                    30.0,
                    self._watchdog_backoff_seconds * (2 ** min(10, max(0, consecutive_failures - 1))),
                )
                with self._state_lock:
                    self._current_backoff_seconds = backoff
                    self._next_restart_at = time.time() + backoff
                self._stop_event.wait(backoff)
                with self._state_lock:
                    self._next_restart_at = None

        with self._state_lock:
            self._process = None
            self._pid = None
            self._state = "stopped"
            self._current_backoff_seconds = 0.0
            self._next_restart_at = None
            self._state_changed.notify_all()

    def start(self) -> dict[str, Any]:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return self.health()
            self._stop_event.clear()
            self._state = "starting"
            self._started_at = time.time()
            self._thread = threading.Thread(
                target=self._supervise,
                daemon=True,
                name="cleanhouse-network-collector",
            )
            self._thread.start()
            self._state_changed.notify_all()
        return self.health()

    def wait_for_initial_state(self, timeout: float = 1.0) -> dict[str, Any]:
        """Wait for the first bounded state and its persisted lifecycle receipt."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._state_changed:
            while (
                (self._state == "starting" or self._sequence == 0)
                and time.monotonic() < deadline
            ):
                self._state_changed.wait(
                    timeout=min(0.05, max(0.0, deadline - time.monotonic()))
                )
        return self.health()

    def stop(self, timeout: float = 5.0) -> Envelope:
        self._stop_event.set()
        with self._state_lock:
            process = self._process
            thread = self._thread
        if process is not None:
            self._terminate_process(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        joined = thread is None or not thread.is_alive()
        with self._state_lock:
            self._state = "stopped" if joined else "stopping"
            self._process = None if joined else self._process
            self._pid = None if joined else self._pid
        receipt = self._publish_receipt("collector.stopped", {
            "state": self._state,
            "joined": joined,
            "generation": self._generation,
            "restart_count": self._restart_count,
        })
        with self._state_lock:
            subscriber_ids = list(self._subscribers)
        for subscriber_id in subscriber_ids:
            self._close_subscriber(subscriber_id)
        return receipt

    def refresh(self, timeout: float = 2.0) -> dict[str, Any]:
        """Synchronize to a health/persistence boundary without process restart."""
        self.start()
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._state_changed:
            initial_pid = self._pid
            initial_generation = self._generation
            while self._state == "starting" and time.monotonic() < deadline:
                self._state_changed.wait(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
        with self._publish_lock:
            pass
        synchronized_health = self.health()
        receipt = self._publish_receipt("collector.refreshed", {
            "state": synchronized_health["state"],
            "pid": synchronized_health["pid"],
            "generation": synchronized_health["generation"],
            "restart_count": synchronized_health["restart_count"],
        })
        health = self.health()
        health["refresh"] = {
            "status": "synchronized" if health["state"] == "running" else "degraded",
            "pid_stable": initial_pid in {None, health.get("pid")},
            "generation_stable": initial_generation in {0, health.get("generation")},
            "synchronized_at": time.time(),
            "receipt_cursor": receipt["cursor"],
        }
        return health

    def snapshot(self, *, include_events: bool = True) -> dict[str, Any]:
        with self._publish_lock:
            with self._state_lock:
                sequence = self._sequence
                replay = [copy.deepcopy(item) for item in self._replay] if include_events else []
        return {
            "cursor": self._cursor(sequence),
            "high_water_cursor": self._cursor(sequence),
            "high_water_sequence": sequence,
            "events": replay,
            "collector": self.health(),
        }

    def subscribe(self, after_cursor: Any = None) -> NetworkCollectorSubscription:
        state = _SubscriberState(
            subscriber_id=uuid.uuid4().hex,
            queue=queue.Queue(maxsize=self._subscriber_queue_size),
        )
        with self._publish_lock:
            with self._state_lock:
                requested, boot_matches = self._parse_cursor(after_cursor)
                if requested is None and boot_matches:
                    requested = self._sequence
                requested = max(0, int(requested or 0))
                state.initial_cursor = str(after_cursor or self._cursor(requested))
                original_requested = requested
                if not boot_matches:
                    requested = 0
                replay = list(self._replay)
                candidates = [item for item in replay if int(item.get("sequence") or 0) > requested]
                gap_reason = ""
                earliest = int(replay[0].get("sequence") or 0) if replay else self._sequence + 1
                if not boot_matches:
                    gap_reason = "cursor_boot_mismatch"
                elif requested < earliest - 1:
                    gap_reason = "replay_buffer_evicted"
                elif requested > self._sequence:
                    gap_reason = "cursor_ahead_of_collector"
                    candidates = []

                capacity = self._subscriber_queue_size
                reserve = 1 if gap_reason or len(candidates) > capacity else 0
                keep_count = max(0, capacity - reserve)
                kept = candidates[-keep_count:] if keep_count else []
                if len(kept) < len(candidates):
                    gap_reason = gap_reason or "subscriber_replay_overflow"
                    reserve = 1
                    keep_count = max(0, capacity - 1)
                    kept = candidates[-keep_count:] if keep_count else []

                if gap_reason:
                    first_kept = int(kept[0].get("sequence") or self._sequence + 1) if kept else self._sequence + 1
                    if gap_reason == "cursor_boot_mismatch":
                        gap_from = 0
                        gap_to = max(0, first_kept - 1)
                    elif gap_reason == "cursor_ahead_of_collector":
                        gap_from = self._sequence + 1
                        gap_to = original_requested
                    else:
                        gap_from = requested + 1
                        gap_to = max(requested, first_kept - 1)
                    gap_sequence = min(self._sequence, gap_to) if self._sequence else 0
                    gap = self._base_envelope("collector.gap", {
                        "reason": gap_reason,
                        "state": "degraded",
                        "requested_cursor": str(after_cursor or ""),
                        "gap_from_sequence": gap_from,
                        "gap_to_sequence": gap_to,
                    }, gap_sequence)
                    state.queue.put_nowait(gap)
                for item in kept:
                    state.queue.put_nowait(copy.deepcopy(item))
                self._subscribers[state.subscriber_id] = state
                self._state_changed.notify_all()
        return NetworkCollectorSubscription(self, state)

    def _close_subscriber(self, subscriber_id: str) -> None:
        with self._state_lock:
            state = self._subscribers.pop(subscriber_id, None)
            if state is None or state.closed:
                return
            state.closed = True
            while True:
                try:
                    state.queue.get_nowait()
                except queue.Empty:
                    break
            try:
                state.queue.put_nowait(_CLOSED)
            except queue.Full:
                pass
            self._state_changed.notify_all()

    def health(self) -> dict[str, Any]:
        with self._state_lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            return {
                "state": self._state,
                "server_boot_id": self._boot_id,
                "generation": self._generation,
                "restart_count": self._restart_count,
                "pid": self._pid,
                "interface": self._interface,
                "thread_alive": thread_alive,
                "started_at": self._started_at,
                "last_packet_at": self._last_packet_at,
                "last_event_timestamp": self._last_event_timestamp,
                "ingestion_latency_ms": self._last_ingestion_latency_ms,
                "last_packet_sequence": self._last_packet_sequence,
                "last_exit_at": self._last_exit_at,
                "last_exit_code": self._last_exit_code,
                "last_error": self._last_error,
                "reason_code": self._last_reason,
                "last_recovery_at": self._last_recovery_at,
                "watchdog_backoff_seconds": self._current_backoff_seconds,
                "next_restart_at": self._next_restart_at,
                "high_water_sequence": self._sequence,
                "high_water_cursor": self._cursor(self._sequence),
                "persistence_high_water_sequence": self._persistence_high_water_sequence,
                "persistence_high_water_cursor": self._cursor(self._persistence_high_water_sequence),
                "persistence_failures": self._persistence_failures,
                "receipt_persistence_failures": self._receipt_persistence_failures,
                "subscriber_count": len(self._subscribers),
                "subscriber_queue_capacity": self._subscriber_queue_size,
                "subscriber_drops": self._subscriber_drops,
                "replay_buffer_depth": len(self._replay),
                "replay_buffer_capacity": self._replay_size,
                "replay_evictions": self._replay_evictions,
                "startup_packets_captured": self._packets_captured,
                "startup_packet_events_parsed": self._packet_events_parsed,
                "startup_canonical_packet_events_emitted": self._canonical_packet_events_emitted,
                "coalesced_packet_events": self._coalesced_packet_events,
                "coalesce_window_seconds": self._coalesce_window_seconds,
                "coalesce_identity_count": len(self._coalesce_seen),
            }
