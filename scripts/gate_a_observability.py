#!/usr/bin/env python3
"""Headless Gate A observability verification for current CleanHouse collectors."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import events as cleanhouse_events
from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
from corefiles.collectors.data_flow_tracer import DataFlowTracer
from corefiles.collectors.process_monitor import ProcessMonitor


Component = dict[str, Any]
PROCESS_PROBE_MARKER = "cleanhouse-gate-a-process-probe"


def _component(name: str, status: str, **data: Any) -> Component:
    return {
        "name": name,
        "status": status,
        "evidence_ref": f"local://cleanhouse/gate-a/{name}",
        **data,
    }


@contextlib.contextmanager
def _temporary_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _local_process_probe():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", PROCESS_PROBE_MARKER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        yield {
            "pid": str(process.pid),
            "marker": PROCESS_PROBE_MARKER,
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


@contextlib.contextmanager
def _local_tcp_probe():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    stop = threading.Event()
    accepted: list[socket.socket] = []

    def accept_once() -> None:
        try:
            conn, _addr = server.accept()
        except OSError:
            return
        accepted.append(conn)
        stop.wait(10)

    thread = threading.Thread(target=accept_once, daemon=True)
    thread.start()
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        time.sleep(0.2)
        yield {
            "host": "127.0.0.1",
            "port": port,
            "pid": str(os.getpid()),
        }
    finally:
        stop.set()
        with contextlib.suppress(OSError):
            client.close()
        for conn in accepted:
            with contextlib.suppress(OSError):
                conn.close()
        with contextlib.suppress(OSError):
            server.close()
        thread.join(timeout=1)


def _runtime_gap_truth_label(collector_status: Any) -> str:
    status = str(collector_status or "unknown")
    if status == "dependency_missing":
        return "unsupported"
    if status in {"inactive", "no_baseline", "partial_capture", "no_ports_observed"}:
        return "partial"
    if status in {"unknown", "no_event"}:
        return "unknown"
    return "collector_gap"


def _annotate_runtime_gap(gap: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(gap)
    annotated["truth_label"] = _runtime_gap_truth_label(gap.get("collector_status"))
    return annotated


def verify_filesystem_watcher(timeout_seconds: float = 5.0) -> Component:
    session_id = "gate-a-filesystem"
    with tempfile.TemporaryDirectory(prefix=".cleanhouse-gate-a-fs-") as tmp:
        root = Path(tmp)
        watch_dir = root / "watch"
        watch_dir.mkdir()
        db_path = root / "events.db"
        with _temporary_env({
            "CLEANHOUSE_EVENTS_DB": str(db_path),
            "CLEANHOUSE_WATCH_DIR": str(watch_dir),
            "CLEANHOUSE_SESSION_ID": session_id,
        }):
            cleanhouse_events.stop_events_services()
            cleanhouse_events.start_watcher()
            watcher_status = cleanhouse_events.get_watcher_status()
            if watcher_status.get("collector_status") != "ok":
                cleanhouse_events.stop_events_services()
                return _component(
                    "filesystem_watcher",
                    "gap",
                    coverage_proven=False,
                    collector_status=watcher_status.get("collector_status"),
                    support_status=watcher_status.get("support_status"),
                    unsupported_reason=watcher_status.get("unsupported_reason"),
                    watcher_status=watcher_status,
                    visible_gap=True,
                )

            target = watch_dir / "observed.txt"
            target_event_path = str((watch_dir.resolve() / target.name).resolve(strict=False))
            time.sleep(0.2)
            target.write_text("created\n", encoding="utf-8")
            time.sleep(0.1)
            target.write_text("modified\n", encoding="utf-8")
            time.sleep(0.1)
            target.unlink()

            deadline = time.monotonic() + timeout_seconds
            rows: list[dict[str, Any]] = []
            expected_event_types = {"created", "modified", "deleted"}
            while time.monotonic() < deadline:
                try:
                    cleanhouse_events._EVENT_QUEUE.join()
                except Exception:
                    pass
                rows = cleanhouse_events.list_events(limit=20, session_id=session_id)
                observed_types = {
                    str(row.get("event_type"))
                    for row in rows
                    if row.get("path") == target_event_path
                }
                if expected_event_types.issubset(observed_types):
                    break
                time.sleep(0.05)

            cleanhouse_events.stop_events_services()
            event_rows = [row for row in rows if row.get("path") == target_event_path]
            event_types = sorted({str(row.get("event_type")) for row in event_rows})
            if not event_rows:
                return _component(
                    "filesystem_watcher",
                    "fail",
                    coverage_proven=False,
                    collector_status="no_event",
                    watcher_status=watcher_status,
                    event_count=0,
                )
            missing_event_types = sorted(expected_event_types - set(event_types))
            if missing_event_types:
                return _component(
                    "filesystem_watcher",
                    "gap",
                    coverage_proven=False,
                    collector_status="partial_capture",
                    watcher_status=watcher_status,
                    event_count=len(event_rows),
                    event_types=event_types,
                    missing_event_types=missing_event_types,
                    visible_gap=True,
                )
            return _component(
                "filesystem_watcher",
                "pass",
                coverage_proven=True,
                collector_status="ok",
                watcher_status=watcher_status,
                event_count=len(event_rows),
                event_types=event_types,
            )


def verify_process_snapshot(
    monitor_factory: Callable[..., Any] = ProcessMonitor,
    probe_process: bool | None = None,
) -> Component:
    should_probe = (monitor_factory is ProcessMonitor) if probe_process is None else probe_process
    probe_context = _local_process_probe() if should_probe else contextlib.nullcontext(None)
    with probe_context as probe:
        monitor = monitor_factory(show_all=True)
        processes = monitor.get_processes()
    if not processes:
        return _component(
            "process_snapshot",
            "fail",
            coverage_proven=False,
            collector_status="empty_snapshot",
            process_count=0,
        )
    required = {"pid", "user", "cpu", "mem", "command"}
    lineage = {"ppid", "start_time", "args", "source_command"}
    complete_rows = [
        proc for proc in processes
        if required.issubset(proc.keys())
    ]
    lineage_rows = [
        proc for proc in processes
        if lineage.issubset(proc.keys())
    ]
    if not complete_rows:
        return _component(
            "process_snapshot",
            "fail",
            coverage_proven=False,
            collector_status="missing_fields",
            process_count=len(processes),
            required_fields=sorted(required),
        )
    probe_rows: list[dict[str, Any]] = []
    if probe:
        probe_rows = [
            proc for proc in processes
            if str(proc.get("pid")) == probe["pid"]
            or probe["marker"] in str(proc.get("command", ""))
        ]
        if not probe_rows:
            return _component(
                "process_snapshot",
                "gap",
                coverage_proven=False,
                collector_status="probe_not_observed",
                process_count=len(processes),
                visible_gap=True,
                probe_pid=probe["pid"],
                probe_marker=probe["marker"],
            )
    return _component(
        "process_snapshot",
        "pass",
        coverage_proven=True,
        collector_status="ok",
        process_count=len(processes),
        lineage_fields_present=bool(lineage_rows),
        local_probe_observed=bool(probe_rows) if probe else None,
        probe_pid=probe["pid"] if probe else None,
        sample_pid=str(complete_rows[0].get("pid")),
    )


def verify_network_port_snapshot(
    tracer_factory: Callable[..., Any] = DataFlowTracer,
    local_probe: bool | None = None,
) -> Component:
    should_probe = (tracer_factory is DataFlowTracer) if local_probe is None else local_probe
    probe_context = _local_tcp_probe() if should_probe else contextlib.nullcontext(None)
    try:
        with probe_context as probe:
            tracer = tracer_factory(monitor_duration=1)
            tracer.scan_network_connections()
    except OSError as exc:
        return _component(
            "network_port_snapshot",
            "fail",
            coverage_proven=False,
            collector_status="probe_setup_failed",
            error_type=exc.__class__.__name__,
            error_detail=str(exc),
        )
    snapshots = tracer.trace_data.get("network_snapshots", [])
    connections = tracer.trace_data.get("network_connections", [])
    port_connections = [
        conn for conn in connections
        if isinstance(conn.get("port"), int)
    ]
    if not snapshots:
        return _component(
            "network_port_snapshot",
            "gap",
            coverage_proven=False,
            collector_status="no_snapshot",
            visible_gap=True,
            connection_count=len(connections),
        )
    if not port_connections:
        return _component(
            "network_port_snapshot",
            "gap",
            coverage_proven=False,
            collector_status="no_ports_observed",
            visible_gap=True,
            snapshot_count=len(snapshots),
            connection_count=len(connections),
        )
    probe_matches: list[dict[str, Any]] = []
    probe_pid_matches: list[dict[str, Any]] = []
    if probe:
        probe_port = int(probe["port"])
        probe_pid = str(probe["pid"])
        probe_matches = [
            conn for conn in connections
            if conn.get("port") == probe_port
            or f":{probe_port}" in str(conn.get("address", ""))
        ]
        probe_pid_matches = [
            conn for conn in probe_matches
            if str(conn.get("pid")) == probe_pid
        ]
        if not probe_matches:
            return _component(
                "network_port_snapshot",
                "gap",
                coverage_proven=False,
                collector_status="probe_port_not_observed",
                visible_gap=True,
                snapshot_count=len(snapshots),
                connection_count=len(connections),
                port_count=len(port_connections),
                probe_port=probe_port,
                probe_pid=probe_pid,
            )
        if not probe_pid_matches:
            return _component(
                "network_port_snapshot",
                "gap",
                coverage_proven=False,
                collector_status="probe_process_not_attributed",
                visible_gap=True,
                snapshot_count=len(snapshots),
                connection_count=len(connections),
                port_count=len(port_connections),
                probe_port=probe_port,
                probe_pid=probe_pid,
                probe_match_count=len(probe_matches),
            )
    return _component(
        "network_port_snapshot",
        "pass",
        coverage_proven=True,
        collector_status="ok",
        snapshot_count=len(snapshots),
        connection_count=len(connections),
        port_count=len(port_connections),
        local_probe_observed=bool(probe_matches) if probe else None,
        local_probe_attributed=bool(probe_pid_matches) if probe else None,
        probe_port=probe["port"] if probe else None,
        probe_pid=probe["pid"] if probe else None,
        delta_count=len(tracer.trace_data.get("network_deltas", [])),
    )


def verify_unsupported_gap_visibility(
    adapter_factory: Callable[..., Any] = CleanHouseMonitoringAdapter,
) -> Component:
    adapter = adapter_factory(cache_ttl_seconds=0.0)
    manifest = adapter._build_collector_manifest()
    runtime_gaps = [
        _annotate_runtime_gap(gap)
        for gap in adapter._runtime_gaps_from_manifest(manifest)
    ]
    cloud_usage = adapter.get_cloud_usage(refresh=True)
    adapters = cloud_usage.get("data", {}).get("cloud_usage_adapters", [])
    unsupported = [
        entry for entry in adapters
        if entry.get("status") == "unsupported"
        and isinstance(entry.get("limitation"), str)
        and entry.get("limitation")
    ]
    watcher_surface = manifest.get("surfaces", {}).get("filesystem_watcher", {})
    visible_runtime_gap = any(
        gap.get("evidence_refs")
        and str(gap.get("collector_status") or "")
        for gap in runtime_gaps
    )
    if not unsupported and not visible_runtime_gap:
        return _component(
            "unsupported_gap_visibility",
            "fail",
            coverage_proven=False,
            collector_status="missing_visible_gap",
            unsupported_count=len(unsupported),
            runtime_gap_count=len(runtime_gaps),
        )
    if visible_runtime_gap:
        return _component(
            "unsupported_gap_visibility",
            "gap",
            coverage_proven=False,
            collector_status="native_runtime_gaps_visible",
            unsupported_count=len(unsupported),
            runtime_gap_count=len(runtime_gaps),
            filesystem_watcher_status=watcher_surface.get("collector_status"),
            runtime_gap_truth_labels=sorted({
                str(gap.get("truth_label"))
                for gap in runtime_gaps
                if gap.get("truth_label")
            }),
            runtime_gaps=runtime_gaps,
            runtime_gap_visibility_proven=True,
            visible_gap=True,
        )
    return _component(
        "unsupported_gap_visibility",
        "pass",
        coverage_proven=True,
        collector_status="ok",
        unsupported_count=len(unsupported),
        runtime_gap_count=len(runtime_gaps),
        filesystem_watcher_status=watcher_surface.get("collector_status"),
        runtime_gap_truth_labels=sorted({
            str(gap.get("truth_label"))
            for gap in runtime_gaps
            if gap.get("truth_label")
        }),
        runtime_gaps=runtime_gaps,
    )


def run_gate() -> dict[str, Any]:
    components = [
        verify_filesystem_watcher(),
        verify_process_snapshot(),
        verify_network_port_snapshot(),
        verify_unsupported_gap_visibility(),
    ]
    failures = [item for item in components if item.get("status") == "fail"]
    gaps = [item for item in components if item.get("status") == "gap"]
    status = "fail" if failures else "partial" if gaps else "pass"
    return {
        "schema": "cleanhouse.gate_a_observability.v1",
        "status": status,
        "coverage_status": status,
        "browser_automation_used": False,
        "os_wide_monitoring_expanded": False,
        "failures": failures,
        "visible_gaps": gaps,
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON")
    args = parser.parse_args()
    result = run_gate()
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True, default=str))
    return 1 if result.get("status") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
