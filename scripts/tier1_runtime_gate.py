#!/usr/bin/env python3
"""Tier 1 runtime gate using CleanHouse HTTP APIs only."""

from __future__ import annotations

import argparse
import json
import tempfile
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:3333"
STATUS_READY_PATH = "/cleanhouse/status?ready=1"
STATUS_FULL_PATH = "/cleanhouse/status?refresh=1"
STATUS_FULL_TIMEOUT_SECONDS = 15.0


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> Any:
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    decoded = json.loads(body or "{}")
    return decoded


def elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000.0, 2)


def timed_request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    start = time.monotonic()
    try:
        decoded = request_json(base_url, method, path, payload, timeout=timeout)
    except Exception as exc:
        return {
            "status": "blocked",
            "source": path,
            "elapsed_ms": elapsed_ms(start),
            "error": str(exc),
            "payload": {},
        }
    return {
        "status": "ok",
        "source": path,
        "elapsed_ms": elapsed_ms(start),
        "payload": decoded if isinstance(decoded, dict) else {},
    }


def status_separation_probe(base_url: str) -> dict[str, Any]:
    readiness_probe = timed_request_json(base_url, "GET", STATUS_READY_PATH)
    full_probe = timed_request_json(
        base_url,
        "GET",
        STATUS_FULL_PATH,
        timeout=STATUS_FULL_TIMEOUT_SECONDS,
    )
    readiness = readiness_probe.get("payload", {})
    full_status = full_probe.get("payload", {})
    readiness_keys = sorted(readiness.keys()) if isinstance(readiness, dict) else []
    full_data = full_status.get("data", {}) if isinstance(full_status, dict) else {}
    manifest = full_data.get("collector_manifest", {}) if isinstance(full_data, dict) else {}
    runtime_status = full_data.get("runtime", {}) if isinstance(full_data, dict) else {}
    checks = {
        "readiness_request_ok": readiness_probe.get("status") == "ok",
        "full_status_request_ok": full_probe.get("status") == "ok",
        "readiness_status_ok": readiness.get("status") == "ok" and readiness.get("ready") is True,
        "readiness_payload_minimal": readiness_keys == ["ready", "status"],
        "readiness_omits_full_status": not any(key in readiness for key in ("data", "issues", "settings", "plugins")),
        "full_status_has_collector_manifest": isinstance(manifest, dict) and bool(manifest.get("surfaces")),
        "full_status_has_runtime": isinstance(runtime_status, dict) and bool(runtime_status),
    }
    return {
        "status": "ok" if all(checks.values()) else "failed",
        "checks": checks,
        "readiness": {
            "source": STATUS_READY_PATH,
            "status": readiness.get("status"),
            "ready": readiness.get("ready"),
            "keys": readiness_keys,
            "elapsed_ms": readiness_probe.get("elapsed_ms"),
            "error": readiness_probe.get("error"),
        },
        "full_status": {
            "source": STATUS_FULL_PATH,
            "status": full_status.get("status", "unknown") if isinstance(full_status, dict) else "unknown",
            "collector_surface_count": len(manifest.get("surfaces", {})) if isinstance(manifest, dict) else 0,
            "runtime_keys": sorted(runtime_status.keys()) if isinstance(runtime_status, dict) else [],
            "elapsed_ms": full_probe.get("elapsed_ms"),
            "error": full_probe.get("error"),
        },
        "payloads": {
            "readiness": readiness,
            "full_status": full_status,
        },
    }


def collector_manifest(status: dict[str, Any]) -> dict[str, Any]:
    canonical = status.get("data", {}).get("collector_manifest", {})
    if isinstance(canonical, dict) and canonical.get("surfaces"):
        collectors = []
        for name, surface in sorted(canonical.get("surfaces", {}).items()):
            if not isinstance(surface, dict):
                continue
            collectors.append({
                "name": name,
                "enabled": True,
                "status": surface.get("status", "unknown"),
                "collector_status": surface.get("collector_status", "unknown"),
                "observations": surface.get("issue_count", 0),
                "collector_failures": surface.get("collector_failures", 0),
            })
        return {
            "status": status.get("status", "unknown"),
            "collectors": collectors,
            "runtime": canonical.get("runtime", {}),
            "plugins": status.get("plugins", {}),
            "source": "/cleanhouse/status",
        }

    sections = status.get("data", {}).get("sections", {})
    enabled = status.get("settings", {})
    collectors = []
    for name in sorted(enabled):
        section = sections.get(name) or sections.get(collector_section_alias(name), {})
        counts = section.get("event_counts", {}) if isinstance(section, dict) else {}
        collectors.append({
            "name": name,
            "enabled": bool(enabled.get(name)),
            "status": section.get("status", "unknown") if isinstance(section, dict) else "unknown",
            "observations": counts.get("observations", 0),
            "collector_failures": counts.get("collector_failures", 0),
        })
    return {
        "status": status.get("status", "unknown"),
        "collectors": collectors,
        "plugins": status.get("plugins", {}),
        "source": "/cleanhouse/status",
    }


def collector_section_alias(name: str) -> str:
    return {
        "process_monitor": "processes",
        "data_flow_tracer": "network",
        "ai_activity": "ai_activity",
        "anomaly_detector": "anomalies",
        "integrity": "integrity",
        "command": "command",
        "cloud_usage": "cloud_usage",
        "tool_events": "tool_events",
    }.get(name, name)


def lineage_graph(workstation: dict[str, Any], approvals: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str) -> None:
        if not node_id or node_id in seen:
            return
        seen.add(node_id)
        nodes.append({"id": node_id, "type": node_type, "label": label or node_id})

    def add_edge(from_id: str, to_id: str, relation: str) -> None:
        if from_id and to_id:
            edges.append({"from": from_id, "to": to_id, "relation": relation})

    session = workstation.get("session", {})
    session_id = str(session.get("session_id") or workstation.get("session_id") or "")
    add_node(session_id, "session", session_id)
    for objective in workstation.get("objectives", []):
        node_id = str(objective.get("id") or objective.get("objective_id") or objective.get("prompt_id") or "")
        add_node(node_id, "objective", str(objective.get("text") or node_id))
        add_edge(session_id, node_id, "declares")
    for mutation in workstation.get("mutations", []):
        node_id = str(mutation.get("event_id") or mutation.get("id") or mutation.get("path") or mutation.get("summary") or "")
        add_node(node_id, "mutation", str(mutation.get("summary") or mutation.get("path") or node_id))
        add_edge(session_id, node_id, "observes")
    for alert in workstation.get("deviation_signals", {}).get("alerts", []):
        node_id = str(alert.get("id") or alert.get("alert_id") or f"{alert.get('alert_type', 'alert')}:{alert.get('description', '')}")
        add_node(node_id, "alert", str(alert.get("alert_type") or node_id))
        add_edge(session_id, node_id, "flags")
        for source_id in alert.get("source_ids", []):
            add_edge(str(source_id), node_id, "supports")
    for receipt in workstation.get("receipts", []):
        receipt_id = str(receipt.get("id") or "")
        add_node(receipt_id, "receipt", receipt_id)
        add_edge(session_id, receipt_id, "finalizes")
    for approval in approvals:
        approval_id = str(approval.get("id") or "")
        add_node(approval_id, "approval", str(approval.get("status") or approval_id))
        add_edge(session_id, approval_id, "requires_review")
        receipt_id = str(approval.get("metadata", {}).get("receipt_id") or "")
        add_edge(receipt_id, approval_id, "reviewed_by")
    for receipt_id, replay in workstation.get("receipt_replays", {}).items():
        replay_id = str(replay.get("id") or f"{receipt_id}:replay")
        add_node(replay_id, "replay", replay_id)
        add_edge(str(receipt_id), replay_id, "replays")

    return {"status": "ok", "session_id": session_id, "nodes": nodes, "edges": edges}


def run_active_spine(base_url: str) -> dict[str, Any]:
    objective_id = f"tier1-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix=".cleanhouse-tier1-", dir=Path.cwd()) as tmpdir:
        repo = Path(tmpdir)
        scope_dir = repo / "scope"
        outside_dir = repo / "outside"
        scope_dir.mkdir()
        outside_dir.mkdir()
        target = scope_dir / "owned.txt"
        target.write_text("before\n", encoding="utf-8")

        prompt = request_json(base_url, "POST", "/cleanhouse/prompt", {
            "text": "Tier 1 runtime gate objective",
            "context": "HTTP-only runtime verification gate; no browser automation.",
            "scope": "scope",
            "repo_path": str(repo),
            "tool_identity": "codex",
            "objective_id": objective_id,
        })
        session_id = str(prompt.get("session_id") or prompt.get("id") or "")

        request_json(base_url, "POST", "/cleanhouse/objective/start", {
            "session_id": session_id,
            "objective_id": objective_id,
            "text": "Tier 1 runtime gate objective",
        })
        before = request_json(base_url, "POST", "/cleanhouse/snapshot", {
            "repo_path": str(repo),
            "label": "before",
            "session_id": session_id,
        })

        target.write_text("after\n", encoding="utf-8")
        (outside_dir / "drift.txt").write_text("out of scope\n", encoding="utf-8")
        tool = request_json(base_url, "POST", "/cleanhouse/tool-event", {
            "tool_identity": "codex",
            "command": "tier1-runtime-gate",
            "args": ["tier1-runtime-gate", "--http-only"],
            "exit_code": 0,
            "cwd": str(repo),
            "session_id": session_id,
            "objective_id": objective_id,
            "duration": 0.01,
        })
        after = request_json(base_url, "POST", "/cleanhouse/snapshot", {
            "repo_path": str(repo),
            "label": "after",
            "session_id": session_id,
        })
        diff = request_json(base_url, "POST", "/cleanhouse/diff", {
            "before_id": before.get("id"),
            "after_id": after.get("id"),
            "session_id": session_id,
        })
        rollback_request = request_json(base_url, "POST", "/cleanhouse/rollback/request", {
            "session_id": session_id,
            "objective_id": objective_id,
            "snapshot_id": before.get("id"),
            "path": "scope/owned.txt",
            "repo_path": str(repo),
            "evidence_refs": [f"local://cleanhouse/diff/{diff.get('id', '')}"],
        })
        rollback_id = rollback_request.get("rollback", {}).get("id")
        rollback_execute = request_json(base_url, "POST", "/cleanhouse/rollback/execute", {
            "rollback_id": rollback_id,
            "repo_path": str(repo),
        }) if rollback_id else {"status": "blocked", "message": "rollback id missing"}

        timeline = request_json(base_url, "POST", "/cleanhouse/timeline", {"session_id": session_id})
        request_json(base_url, "POST", "/cleanhouse/correlate", {"session_id": session_id})
        request_json(base_url, "POST", "/cleanhouse/classify", {"session_id": session_id})
        alerts = request_json(base_url, "POST", "/cleanhouse/alerts", {"session_id": session_id})
        receipt = request_json(base_url, "POST", "/cleanhouse/receipt", {"session_id": session_id})
        receipt_id = str(receipt.get("id") or "")
        time.sleep(0.2)

        replay = request_json(base_url, "GET", f"/cleanhouse/receipt-replay?{urllib.parse.urlencode({'receipt_id': receipt_id})}") if receipt_id else {}
        bundle = request_json(base_url, "GET", f"/cleanhouse/receipt-bundle?{urllib.parse.urlencode({'receipt_id': receipt_id})}") if receipt_id else {}
        imported = request_json(base_url, "POST", "/cleanhouse/receipt-bundle/import", {
            "bundle": bundle.get("bundle", {})
        }) if bundle.get("bundle") else {}
        events: Any = []
        event_rows: list[dict[str, Any]] = []
        for _ in range(10):
            events = request_json(base_url, "GET", f"/events?{urllib.parse.urlencode({'session_id': session_id, 'limit': 200})}")
            event_rows = events if isinstance(events, list) else []
            if event_rows:
                break
            time.sleep(0.2)
        event_receipts = request_json(base_url, "GET", f"/receipts?{urllib.parse.urlencode({'session_id': session_id, 'limit': 50})}")
        cleanhouse_receipts = request_json(base_url, "GET", f"/cleanhouse/receipts?{urllib.parse.urlencode({'session_id': session_id})}")
        approvals = request_json(base_url, "GET", f"/cleanhouse/approval-queue?{urllib.parse.urlencode({'session_id': session_id})}")
        rollbacks = request_json(base_url, "GET", f"/cleanhouse/rollback?{urllib.parse.urlencode({'session_id': session_id})}")
        workstation = request_json(base_url, "GET", f"/cleanhouse/workstation?{urllib.parse.urlencode({'session_id': session_id})}")

        receipt_scope_paths = [
            str(path)
            for path in receipt.get("scope_analysis", {}).get("changed_paths", [])
            if path
        ]
        affected_paths = sorted({
            path
            for item in diff.get("changes", []) if isinstance(item, dict)
            for path in [str(item.get("path") or "")]
            if path
        } | set(receipt_scope_paths))
        receipt_manifest = receipt.get("collector_manifest", {}) if isinstance(receipt, dict) else {}
        collector_surfaces = receipt_manifest.get("surfaces", {}) if isinstance(receipt_manifest, dict) else {}
        receipt_bundle_verification = bundle.get("verification", {}) if isinstance(bundle, dict) else {}
        import_verification = imported.get("verification", {}) if isinstance(imported, dict) else {}
        checks = {
            "objective_id_visible": objective_id in json.dumps(receipt, sort_keys=True),
            "session_id_agrees": all(value == session_id for value in [
                timeline.get("session_id"),
                receipt.get("session_id"),
                replay.get("session_id"),
                workstation.get("session", {}).get("session_id"),
            ] if value),
            "event_count_visible": len(event_rows) > 0 and len(timeline.get("entries", [])) > 0,
            "affected_paths_visible": "scope/owned.txt" in affected_paths and "outside/drift.txt" in affected_paths,
            "approval_state_visible": bool(approvals.get("approval_queue")) or bool(receipt.get("approval_policy")),
            "rollback_executed_verified": rollback_execute.get("rollback", {}).get("status") == "executed_verified",
            "receipt_replay_hash_visible": bool(replay.get("integrity", {}).get("replay_hash")),
            "bundle_export_verified": all(receipt_bundle_verification.get(key) for key in ("bundle_hash_match", "manifest_hash_match", "timeline_hash_match", "replay_hash_match", "signature_verified")),
            "bundle_import_verified": all(import_verification.get(key) for key in ("bundle_hash_match", "manifest_hash_match", "timeline_hash_match", "replay_hash_match", "signature_verified")),
            "cleanhouse_receipt_visible": cleanhouse_receipts.get("count", 0) >= 1,
            "events_route_session_scoped": all(row.get("session_id") == session_id for row in event_rows),
            "no_browser_operator_verification": True,
            "browser_automation_used": False,
        }
        browser_flags = {
            key: value
            for key, value in checks.items()
            if key.endswith("browser_automation_used")
        }
        passed = (
            all(value for key, value in checks.items() if not key.endswith("browser_automation_used"))
            and not any(browser_flags.values())
        )
        return {
            "status": "ok" if passed else "failed",
            "session_id": session_id,
            "objective_id": objective_id,
            "checks": checks,
            "counts": {
                "events": len(event_rows),
                "timeline_entries": len(timeline.get("entries", [])),
                "alerts": len(alerts.get("alerts", [])),
                "approvals": len(approvals.get("approval_queue", [])),
                "rollbacks": rollbacks.get("count", 0),
                "cleanhouse_receipts": cleanhouse_receipts.get("count", 0),
                "event_receipts": len(event_receipts) if isinstance(event_receipts, list) else 0,
                "collector_surfaces": len(collector_surfaces) if isinstance(collector_surfaces, dict) else 0,
            },
            "affected_paths": affected_paths,
            "rollback_state": rollback_execute.get("rollback", {}),
            "receipt": {
                "id": receipt_id,
                "root_hash": receipt.get("integrity", {}).get("root_hash"),
                "replay_hash": replay.get("integrity", {}).get("replay_hash"),
                "bundle_hash": bundle.get("bundle", {}).get("integrity", {}).get("bundle_hash"),
                "import_status": imported.get("status"),
            },
            "tool_event": tool,
        }


def run_gate(base_url: str, session_id: str = "") -> dict[str, Any]:
    status_probe = status_separation_probe(base_url)
    readiness = status_probe.get("payloads", {}).get("readiness", {})
    full_status = status_probe.get("payloads", {}).get("full_status", {})
    active = run_active_spine(base_url) if not session_id else {}
    session_qs = f"?{urllib.parse.urlencode({'session_id': session_id})}" if session_id else ""
    workstation = request_json(base_url, "GET", f"/cleanhouse/workstation{session_qs}")
    resolved_session_id = session_id or active.get("session_id") or str(workstation.get("session", {}).get("session_id") or "")
    resolved_qs = f"?{urllib.parse.urlencode({'session_id': resolved_session_id})}" if resolved_session_id else ""
    receipts = request_json(base_url, "GET", f"/cleanhouse/receipts{resolved_qs}").get("receipts", [])
    approvals = request_json(base_url, "GET", f"/cleanhouse/approval-queue{resolved_qs}").get("approval_queue", [])

    replays: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    for receipt in receipts:
        receipt_id = str(receipt.get("id") or "")
        if not receipt_id:
            continue
        receipt_qs = urllib.parse.urlencode({"receipt_id": receipt_id})
        replay = request_json(base_url, "GET", f"/cleanhouse/receipt-replay?{receipt_qs}")
        if replay.get("status") == "ok":
            replays[receipt_id] = replay
        bundle = request_json(base_url, "GET", f"/cleanhouse/receipt-bundle?{receipt_qs}")
        if bundle.get("status") == "ok":
            bundle_payload = bundle.get("bundle", {})
            manifests[receipt_id] = {
                "manifest": bundle_payload.get("manifest", {}),
                "integrity": bundle_payload.get("integrity", {}),
                "verification": bundle.get("verification", {}),
            }

    manifest = collector_manifest(full_status)
    graph = lineage_graph(workstation, approvals)
    rollback_replay_state = {
        "status": "ok",
        "receipt_ids": [receipt.get("id") for receipt in receipts if receipt.get("id")],
        "approval_ids": [approval.get("id") for approval in approvals if approval.get("id")],
        "replay_hashes": {
            receipt_id: replay.get("integrity", {}).get("replay_hash")
            for receipt_id, replay in replays.items()
        },
        "bundle_verification": {
            receipt_id: manifest.get("verification", {})
            for receipt_id, manifest in manifests.items()
        },
    }
    checks = {
        "collector_manifest_visible": len(manifest["collectors"]) > 0 or active.get("counts", {}).get("collector_surfaces", 0) > 0,
        "lineage_graph_visible": len(graph["nodes"]) > 0 or bool(active.get("receipt", {}).get("id")),
        "rollback_replay_state_visible": len(receipts) == 0 or len(replays) > 0,
        "collector_manifest_source_http": True,
        "status_readiness_full_separated": status_probe.get("status") == "ok",
        "status_readiness_payload_minimal": status_probe.get("checks", {}).get("readiness_payload_minimal") is True,
        "status_full_has_runtime": status_probe.get("checks", {}).get("full_status_has_runtime") is True,
        "lineage_graph_source_http": True,
        "rollback_replay_source_http": True,
        "no_browser_operator_verification": True,
        "browser_automation_used": False,
        "workstation_api_available": workstation.get("status") == "ok",
    }
    checks.update({f"active_{key}": value for key, value in active.get("checks", {}).items()})
    browser_flags = {
        key: value
        for key, value in checks.items()
        if key.endswith("browser_automation_used")
    }
    passed = (
        all(value for key, value in checks.items() if not key.endswith("browser_automation_used"))
        and not any(browser_flags.values())
    )
    return {
        "status": "ok" if passed else "failed",
        "base_url": base_url,
        "session_id": resolved_session_id,
        "readiness": {
            "status": readiness.get("status", "unknown"),
            "ready": readiness.get("ready", False),
            "source": STATUS_READY_PATH,
            "elapsed_ms": status_probe.get("readiness", {}).get("elapsed_ms"),
        },
        "status_separation": {
            key: value for key, value in status_probe.items() if key != "payloads"
        },
        "performance": {
            "readiness_ms": status_probe.get("readiness", {}).get("elapsed_ms"),
            "full_status_ms": status_probe.get("full_status", {}).get("elapsed_ms"),
        },
        "collector_manifest": manifest,
        "lineage_graph": graph,
        "rollback_replay_state": rollback_replay_state,
        "active_spine": active,
        "operator_verification": {
            "method": "http-api",
            "checks": checks,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--session-id", default="")
    args = parser.parse_args()
    try:
        result = run_gate(args.base_url, args.session_id)
    except Exception as exc:
        result = {
            "status": "blocked",
            "base_url": args.base_url,
            "session_id": args.session_id,
            "blocker": str(exc),
            "operator_verification": {
                "method": "http-api",
                "checks": {
                    "no_browser_operator_verification": True,
                    "browser_automation_used": False,
                },
            },
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
