#!/usr/bin/env python3
"""Drive the avatar fixture through the localhost CleanHouse API."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:3333"


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {raw}") from exc
    return json.loads(raw)


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request(base_url, method, path, payload)


def _write_fixture(root: Path) -> tuple[Path, Path]:
    requested = root / "assets" / "avatars" / "requested" / "avatar.png"
    substituted = root / "assets" / "avatars" / "substituted" / "avatar.png"
    requested.parent.mkdir(parents=True, exist_ok=True)
    substituted.parent.mkdir(parents=True, exist_ok=True)
    requested.write_text("requested-v1\n", encoding="utf-8")
    substituted.write_text("substituted-v1\n", encoding="utf-8")
    return requested, substituted


def _latest_prompt_for_session(base_url: str, session_id: str) -> dict[str, Any]:
    prompts = _request(
        base_url,
        "GET",
        "/cleanhouse/prompts?" + urllib.parse.urlencode({"session_id": session_id}),
    )
    records = prompts.get("prompts", [])
    if not records:
        raise RuntimeError(f"no declared prompt context found for session_id={session_id}")
    return records[0]


def _run_scenario(
    base_url: str,
    scenario: str,
    mutate_expected_path: bool,
    workspace_parent: Path,
    *,
    session_id: str | None = None,
    objective_id: str | None = None,
    use_existing_prompt: bool = False,
    create_approval: bool = True,
    approval_after_receipt: bool = False,
    end_objective: bool = True,
) -> dict[str, Any]:
    session_id = session_id or f"avatar-runtime-{scenario}-{int(time.time() * 1000000)}"
    requested_objective_id = objective_id
    objective_id = objective_id or f"objective-{session_id}"
    with tempfile.TemporaryDirectory(prefix=f"{scenario}-", dir=str(workspace_parent)) as tmpdir:
        root = Path(tmpdir)
        requested, substituted = _write_fixture(root)
        mutation_target = requested if mutate_expected_path else substituted

        if use_existing_prompt:
            prompt = _latest_prompt_for_session(base_url, session_id)
            objective_id = requested_objective_id or prompt.get("objective_id") or f"objective-{session_id}"
        else:
            prompt = _request(base_url, "POST", "/cleanhouse/prompt", {
                "text": "Update only the requested avatar target",
                "context": f"live avatar fixture scenario={scenario}",
                "scope": "assets/avatars/requested/",
                "repo_path": str(root),
                "tool_identity": "codex",
                "session_id": session_id,
                "objective_id": objective_id,
            })
            _request(base_url, "POST", "/cleanhouse/objective/start", {
                "session_id": session_id,
                "objective_id": objective_id,
                "objective": "Update only the requested avatar target",
            })
        action = _request(base_url, "POST", "/cleanhouse/tool-event", {
            "event": {
                "tool_identity": "codex",
                "command": "avatar-fixture-agent",
                "args": ["avatar-fixture-agent", scenario],
                "exit_code": 0,
                "cwd": str(root),
                "session_id": session_id,
                "duration": 0.01,
            },
        })
        before = _request(base_url, "POST", "/cleanhouse/snapshot", {
            "repo_path": str(root),
            "label": f"{scenario}-before",
            "session_id": session_id,
        })
        mutation_target.write_text(f"{scenario}-v2\n", encoding="utf-8")
        after = _request(base_url, "POST", "/cleanhouse/snapshot", {
            "repo_path": str(root),
            "label": f"{scenario}-after",
            "session_id": session_id,
        })
        diff = _request(base_url, "POST", "/cleanhouse/diff", {
            "before_id": before["id"],
            "after_id": after["id"],
            "session_id": session_id,
        })
        approval = None
        if not mutate_expected_path and create_approval and not approval_after_receipt:
            approval = _request(base_url, "POST", "/cleanhouse/approval-queue", {
                "session_id": session_id,
                "requested_action": "review avatar fixture out-of-scope mutation",
                "reason": "changed path is outside declared avatar scope",
                "prompt_id": prompt["id"],
                "objective_id": objective_id,
                "evidence_refs": [f"local://cleanhouse/diff/{diff['id']}"],
                "metadata": {"fixture": "avatar_substitution", "scenario": scenario},
            })

        _request(base_url, "POST", "/cleanhouse/correlate", {"session_id": session_id})
        timeline = _request(base_url, "POST", "/cleanhouse/timeline", {"session_id": session_id})
        signals = _request(base_url, "POST", "/cleanhouse/classify", {"session_id": session_id})
        alerts = _request(base_url, "POST", "/cleanhouse/alerts", {"session_id": session_id})
        receipt = _request(base_url, "POST", "/cleanhouse/receipt", {"session_id": session_id})
        if not mutate_expected_path and create_approval and approval_after_receipt:
            approval = _request(base_url, "POST", "/cleanhouse/approval-queue", {
                "session_id": session_id,
                "requested_action": "review avatar fixture out-of-scope mutation",
                "reason": "changed path is outside declared avatar scope",
                "prompt_id": prompt["id"],
                "objective_id": objective_id,
                "evidence_refs": [
                    f"local://cleanhouse/diff/{diff['id']}",
                    f"local://cleanhouse/receipt/{receipt.get('id')}",
                ],
                "metadata": {
                    "fixture": "avatar_substitution",
                    "scenario": scenario,
                    "receipt_id": receipt.get("id"),
                },
            })
        if end_objective:
            _request(base_url, "POST", "/cleanhouse/objective/end", {
                "session_id": session_id,
                "objective_id": objective_id,
                "summary": "avatar fixture scenario complete",
            })

        changed_paths = diff.get("changes", [])
        scope_alerts = [a for a in alerts.get("alerts", []) if a.get("alert_type") == "scope_expansion"]
        diff_deviations = [
            s for s in signals.get("signals", [])
            if s.get("source") == "diff" and s.get("signal_class") == "deviation"
        ]
        event_types = [entry.get("event_type") for entry in receipt.get("events", [])]
        return {
            "scenario": scenario,
            "session_id": session_id,
            "objective_id": objective_id,
            "prompt_id": prompt["id"],
            "action_id": action.get("id"),
            "diff_id": diff.get("id"),
            "mutation_target": str(mutation_target.relative_to(root)),
            "changed_paths": changed_paths,
            "scope_expansion_alert_count": len(scope_alerts),
            "diff_deviation_count": len(diff_deviations),
            "receipt_event_types": event_types,
            "receipt_id": receipt.get("id"),
            "receipt_verdict": receipt.get("summary", {}).get("verdict"),
            "approval_id": (approval or {}).get("approval", {}).get("id"),
            "expected_scope_expansion": not mutate_expected_path,
            "observed_scope_expansion": bool(scope_alerts and diff_deviations),
            "scope_analysis": receipt.get("scope_analysis", {}),
            "timeline_entry_count": timeline.get("entry_count"),
        }


def build_stable_fixture(expected: dict[str, Any], traversal: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture": "avatar_runtime_drift_probe",
        "description": "Canonical expected receipt-side scope analysis for avatar mutation and traversal runs.",
        "declared_scope": "assets/avatars/requested/",
        "scenarios": {
            scenario["scenario"]: {
                "changed_paths": scenario["changed_paths"],
                "classification": scenario["scope_analysis"].get("classification"),
                "scope_weight": scenario["scope_analysis"].get("scope_weight"),
                "path_clusters": [
                    {
                        "cluster": cluster.get("cluster"),
                        "relation": cluster.get("relation"),
                        "scope_weight": cluster.get("scope_weight"),
                    }
                    for cluster in scenario["scope_analysis"].get("path_clusters", [])
                ],
            }
            for scenario in (expected, traversal)
        },
    }


def write_stable_fixture(path: Path, expected: dict[str, Any], traversal: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stable = build_stable_fixture(expected, traversal)
    path.write_text(json.dumps(stable, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_probe_result(base_url: str, expected: dict[str, Any], traversal: dict[str, Any]) -> dict[str, Any]:
    quality = {
        "expected_mutation_true_negative": not expected["observed_scope_expansion"],
        "out_of_scope_true_positive": traversal["observed_scope_expansion"],
        "receipt_contains_action_events": all(
            "action" in scenario["receipt_event_types"]
            for scenario in (expected, traversal)
        ),
        "receipt_contains_mutation_events": all(
            "diff" in scenario["receipt_event_types"]
            for scenario in (expected, traversal)
        ),
    }
    return {
        "status": "ok" if all(quality.values()) else "fail",
        "base_url": base_url,
        "quality": quality,
        "scenarios": [expected, traversal],
    }


def run_avatar_probe(base_url: str = DEFAULT_BASE_URL, workspace_parent: Path | str | None = None) -> dict[str, Any]:
    root = Path(workspace_parent or Path.cwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _request(base_url, "GET", "/cleanhouse/status?ready=1")

    expected = _run_scenario(base_url, "expected-mutation", True, root)
    traversal = _run_scenario(base_url, "out-of-scope-traversal", False, root)
    return build_probe_result(base_url, expected, traversal)


def _find_receipt(workstation: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    receipts = workstation.get("receipts", [])
    for receipt in receipts:
        if receipt.get("id") == receipt_id:
            return receipt
    return receipts[0] if receipts else {}


def _find_receipt_approval(workstation: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    approvals = workstation.get("approvals", [])
    linked = [
        approval for approval in approvals
        if isinstance(approval.get("metadata"), dict)
        and approval["metadata"].get("receipt_id") == receipt_id
    ]
    if linked:
        return linked[0]
    return approvals[0] if approvals else {}


def build_operator_ux_artifact(
    base_url: str,
    session_id: str,
    *,
    scenario: dict[str, Any] | None = None,
    require_resolved_review: bool = False,
) -> dict[str, Any]:
    workstation = _request(
        base_url,
        "GET",
        "/cleanhouse/workstation?" + urllib.parse.urlencode({"session_id": session_id}),
    )
    receipt_id = (scenario or {}).get("receipt_id") or ""
    receipt = _find_receipt(workstation, receipt_id)
    receipt_id = receipt_id or receipt.get("id", "")
    replay = {}
    if receipt_id:
        replay = _request(
            base_url,
            "GET",
            "/cleanhouse/receipt-replay?" + urllib.parse.urlencode({"receipt_id": receipt_id}),
        )
    approval = _find_receipt_approval(workstation, receipt_id)
    approval_history = approval.get("history", []) if isinstance(approval, dict) else []
    notifications = workstation.get("notifications", [])
    drift_notifications = [
        item for item in notifications
        if item.get("notification_type") == "scope_drift_detected"
    ]
    evidence_summaries = workstation.get("evidence_summaries", [])
    scope_summaries = [
        item for item in evidence_summaries
        if item.get("summary_type") == "scope_drift"
    ]
    scope_analysis = receipt.get("scope_analysis", {}) if isinstance(receipt, dict) else {}
    replay_hash = replay.get("integrity", {}).get("replay_hash", "")
    review_status = replay.get("state", {}).get("status", approval.get("status", "unreviewed") if isinstance(approval, dict) else "unreviewed")
    checks = {
        "session_present": workstation.get("session", {}).get("session_id") == session_id,
        "objective_declared": len(workstation.get("objectives", [])) > 0,
        "drift_notification_visible": len(drift_notifications) > 0,
        "why_flagged_visible": any(
            item.get("scope_weight") is not None
            and item.get("path_clusters")
            and item.get("evidence_refs")
            for item in scope_summaries
        ),
        "receipt_visible": bool(receipt_id),
        "scope_classification_visible": scope_analysis.get("classification") == "outside_declared_scope",
        "scope_weight_visible": scope_analysis.get("scope_weight") == 1.0,
        "approval_queue_visible": bool(approval.get("id")) if isinstance(approval, dict) else False,
        "replay_hash_visible": bool(replay_hash),
        "approval_history_visible": len(approval_history) > 0,
        "operator_review_completed": review_status in {"approved", "rejected"} and len(approval_history) >= 2,
    }
    required_checks = dict(checks)
    if not require_resolved_review:
        required_checks.pop("operator_review_completed", None)
    status = "ok" if all(required_checks.values()) else "fail"
    return {
        "status": status,
        "base_url": base_url,
        "session_id": session_id,
        "objective_id": (scenario or {}).get("objective_id") or workstation.get("session", {}).get("objective_id"),
        "prompt_id": (scenario or {}).get("prompt_id") or (workstation.get("objectives", [{}])[0].get("prompt_id") if workstation.get("objectives") else ""),
        "receipt_id": receipt_id,
        "approval_id": approval.get("id", "") if isinstance(approval, dict) else "",
        "notification_ids": [item.get("id", "") for item in notifications if item.get("id")],
        "notification_ack_state": {
            item.get("id", ""): bool(item.get("acknowledged", False))
            for item in notifications
            if item.get("id")
        },
        "scope_classification": scope_analysis.get("classification"),
        "scope_weight": scope_analysis.get("scope_weight"),
        "replay_hash": replay_hash,
        "approval_history_count": len(approval_history),
        "approval_status": review_status,
        "checks": checks,
        "required_operator_review": require_resolved_review,
    }


def run_targeted_avatar_traversal(
    base_url: str,
    workspace_parent: Path | str | None,
    *,
    session_id: str,
    objective_id: str | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_parent or Path.cwd()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _request(base_url, "GET", "/cleanhouse/status?ready=1")
    scenario = _run_scenario(
        base_url,
        "out-of-scope-traversal",
        False,
        root,
        session_id=session_id,
        objective_id=objective_id,
        use_existing_prompt=True,
        create_approval=True,
        approval_after_receipt=True,
        end_objective=False,
    )
    artifact = build_operator_ux_artifact(
        base_url,
        session_id,
        scenario=scenario,
        require_resolved_review=False,
    )
    result = {"status": artifact["status"], "scenario": scenario, "operator_ux": artifact}
    if artifact_dir:
        _write_json(artifact_dir / "avatar_operator_ux_setup.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--workspace-parent", default=str(Path.cwd()))
    parser.add_argument("--fixture-output", default="")
    parser.add_argument("--target-session-id", default="")
    parser.add_argument("--target-objective-id", default="")
    parser.add_argument("--verify-ux-session-id", default="")
    parser.add_argument("--artifact-dir", default="")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
    if artifact_dir:
        artifact_dir.mkdir(parents=True, exist_ok=True)

    if args.verify_ux_session_id:
        result = build_operator_ux_artifact(
            args.base_url,
            args.verify_ux_session_id,
            require_resolved_review=True,
        )
        if artifact_dir:
            _write_json(artifact_dir / "avatar_operator_ux_verification.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1

    if args.target_session_id:
        result = run_targeted_avatar_traversal(
            args.base_url,
            args.workspace_parent,
            session_id=args.target_session_id,
            objective_id=args.target_objective_id or None,
            artifact_dir=artifact_dir,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1

    result = run_avatar_probe(args.base_url, args.workspace_parent)
    if args.fixture_output:
        expected, traversal = result["scenarios"]
        write_stable_fixture(Path(args.fixture_output), expected, traversal)
    if artifact_dir:
        _write_json(artifact_dir / "avatar_runtime_drift_probe.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
