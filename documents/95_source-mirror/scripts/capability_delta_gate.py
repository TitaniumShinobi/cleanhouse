#!/usr/bin/env python3
"""Evidence-only capability delta gate for fixed CleanHouse objectives."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import avatar_receipt_regression_gate as avatar_gate
from avatar_runtime_drift_probe import DEFAULT_BASE_URL
from verify_bundle import verify_bundle_path


SCENARIO_NAMES = ("expected-mutation", "out-of-scope-traversal")
LOWER_IS_BETTER = (
    "scope_drift_count",
    "max_scope_weight",
    "approval_required_count",
    "rejected_approval_count",
    "retry_count",
    "corrective_prompt_count",
    "operator_intervention_count",
)
ELAPSED_TOLERANCE_SECONDS = 1.0


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _stable_hash(payload: Any) -> str:
    import hashlib

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scenario_map(probe_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(scenario.get("scenario", "")): scenario
        for scenario in probe_result.get("scenarios", [])
        if isinstance(scenario, dict)
    }


def _bundle_check_map(bundle_checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(check.get("scenario", "")): check
        for check in bundle_checks
        if isinstance(check, dict)
    }


def _receipt_events(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    receipt = bundle.get("receipt", {}) if isinstance(bundle.get("receipt"), dict) else {}
    events = receipt.get("events", [])
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _retry_marker(event: dict[str, Any]) -> bool:
    metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
    explicit_values = (
        event.get("retry"),
        metadata.get("retry"),
        event.get("retried"),
        metadata.get("retried"),
    )
    if any(value is True for value in explicit_values):
        return True
    for value in (event.get("attempt"), metadata.get("attempt")):
        try:
            if int(value) > 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _approval_status(bundle: dict[str, Any]) -> str:
    approval = bundle.get("approval", {}) if isinstance(bundle.get("approval"), dict) else {}
    replay = bundle.get("replay", {}) if isinstance(bundle.get("replay"), dict) else {}
    replay_state = replay.get("approval_state", {}) if isinstance(replay.get("approval_state"), dict) else {}
    return str(approval.get("status") or replay_state.get("status") or "")


def _approval_history_count(bundle: dict[str, Any], check: dict[str, Any] | None = None) -> int:
    approval = bundle.get("approval", {}) if isinstance(bundle.get("approval"), dict) else {}
    history = approval.get("history", []) if isinstance(approval.get("history"), list) else []
    if history:
        return len(history)
    integrity = bundle.get("integrity", {}) if isinstance(bundle.get("integrity"), dict) else {}
    return int(_float_value(integrity.get("approval_history_count", (check or {}).get("approval_history_count", 0)), 0))


def _receipt_duration(bundle: dict[str, Any]) -> float | None:
    receipt = bundle.get("receipt", {}) if isinstance(bundle.get("receipt"), dict) else {}
    metadata = receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}
    value = metadata.get("duration_seconds")
    if value is None:
        return None
    return _float_value(value, 0.0)


def collect_run_metrics(
    probe_result: dict[str, Any],
    bundle_checks: list[dict[str, Any]],
    bundles: dict[str, dict[str, Any]],
    *,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    scenarios = _scenario_map(probe_result)
    checks = _bundle_check_map(bundle_checks)
    validation_failures = avatar_gate.validate_regression_gate(probe_result, bundle_checks)
    scope_weights = [
        _float_value(scenario.get("scope_analysis", {}).get("scope_weight"), 0.0)
        for scenario in scenarios.values()
    ]
    scope_drift_count = sum(
        1
        for scenario in scenarios.values()
        if scenario.get("observed_scope_expansion")
        or scenario.get("scope_analysis", {}).get("classification") == "outside_declared_scope"
    )
    approval_required_count = 0
    rejected_approval_count = 0
    retry_count = 0
    prompt_event_count = 0
    receipt_durations: list[float] = []
    replay_hashes: dict[str, str] = {}

    for scenario_name in SCENARIO_NAMES:
        bundle = bundles.get(scenario_name, {})
        check = checks.get(scenario_name, {})
        if scenario_name in scenarios and scenarios[scenario_name].get("approval_id"):
            approval_required_count += 1
        elif bundle and _approval_history_count(bundle, check) > 0:
            approval_required_count += 1
        if _approval_status(bundle) == "rejected":
            rejected_approval_count += 1
        for event in _receipt_events(bundle):
            if event.get("event_type") == "prompt":
                prompt_event_count += 1
            if event.get("event_type") == "action" and _retry_marker(event):
                retry_count += 1
        duration = _receipt_duration(bundle)
        if duration is not None:
            receipt_durations.append(duration)
        replay_hash = check.get("replay_hash") or bundle.get("integrity", {}).get("replay_hash", "")
        if replay_hash:
            replay_hashes[scenario_name] = str(replay_hash)

    corrective_prompt_count = max(0, prompt_event_count - len([s for s in SCENARIO_NAMES if s in scenarios]))
    operator_intervention_count = approval_required_count + rejected_approval_count + corrective_prompt_count
    if elapsed_seconds is None:
        elapsed_seconds = round(sum(receipt_durations), 3) if receipt_durations else 0.0

    return {
        "verified_completion": not validation_failures,
        "scope_drift_count": scope_drift_count,
        "max_scope_weight": max(scope_weights) if scope_weights else 0.0,
        "approval_required_count": approval_required_count,
        "rejected_approval_count": rejected_approval_count,
        "retry_count": retry_count,
        "corrective_prompt_count": corrective_prompt_count,
        "operator_intervention_count": operator_intervention_count,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "receipt_replay_hash": _stable_hash(replay_hashes) if replay_hashes else "",
        "bundle_signature_verified": all(
            check.get("signature_verified") is True
            and check.get("signature_status") == "verified"
            and check.get("export_verification", {}).get("signature_verified") is True
            for check in bundle_checks
        ),
    }


def build_capability_run(
    *,
    run_index: int,
    probe_result: dict[str, Any],
    bundle_checks: list[dict[str, Any]],
    bundles: dict[str, dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    failures = avatar_gate.validate_regression_gate(probe_result, bundle_checks)
    metrics = collect_run_metrics(
        probe_result,
        bundle_checks,
        bundles,
        elapsed_seconds=elapsed_seconds,
    )
    if not metrics["bundle_signature_verified"]:
        failures.append("one or more signed bundle verifications failed")
    run_core = {
        "run_index": run_index,
        "suite": "avatar_runtime_drift_probe",
        "scenario_count": len(_scenario_map(probe_result)),
        "metrics": metrics,
        "failures": failures,
    }
    return {
        "schema": "cleanhouse.capability_run.v1",
        "artifact_type": "capability_run",
        "run_id": f"capability_run:{_stable_hash(run_core)[:24]}",
        "status": "ok" if not failures else "fail",
        **run_core,
    }


def _metric_delta(first: Any, last: Any) -> Any:
    if isinstance(first, bool) or isinstance(last, bool):
        return {"first": bool(first), "last": bool(last), "changed": bool(first) != bool(last)}
    if isinstance(first, (int, float)) and isinstance(last, (int, float)):
        return {"first": first, "last": last, "delta": round(float(last) - float(first), 3)}
    return {"first": first, "last": last, "changed": first != last}


def classify_delta(runs: list[dict[str, Any]]) -> tuple[str, list[str], dict[str, Any]]:
    if not runs:
        return "regressed", ["no capability runs were collected"], {}
    first = runs[0].get("metrics", {})
    last = runs[-1].get("metrics", {})
    deltas = {
        key: _metric_delta(first.get(key), last.get(key))
        for key in sorted(set(first) | set(last))
        if key != "receipt_replay_hash"
    }
    failures: list[str] = []
    improved = False
    worsened = False

    for run in runs:
        for reason in run.get("failures", []):
            failures.append(f"run {run.get('run_index')}: {reason}")
        metrics = run.get("metrics", {})
        if metrics.get("verified_completion") is not True:
            failures.append(f"run {run.get('run_index')}: verified_completion is false")
        if metrics.get("bundle_signature_verified") is not True:
            failures.append(f"run {run.get('run_index')}: bundle_signature_verified is false")

    if first.get("verified_completion") is False and last.get("verified_completion") is True:
        improved = True
    if first.get("verified_completion") is True and last.get("verified_completion") is False:
        worsened = True
    if first.get("bundle_signature_verified") is False and last.get("bundle_signature_verified") is True:
        improved = True
    if first.get("bundle_signature_verified") is True and last.get("bundle_signature_verified") is False:
        worsened = True

    for key in LOWER_IS_BETTER:
        first_value = _float_value(first.get(key), 0.0)
        last_value = _float_value(last.get(key), 0.0)
        if last_value < first_value:
            improved = True
        elif last_value > first_value:
            worsened = True

    first_elapsed = _float_value(first.get("elapsed_seconds"), 0.0)
    last_elapsed = _float_value(last.get("elapsed_seconds"), 0.0)
    elapsed_delta = last_elapsed - first_elapsed
    if elapsed_delta > ELAPSED_TOLERANCE_SECONDS:
        worsened = True
    elif elapsed_delta < -ELAPSED_TOLERANCE_SECONDS:
        improved = True

    if failures or worsened:
        return "regressed", failures, deltas
    if improved:
        return "improved", failures, deltas
    return "no_material_delta", failures, deltas


def build_delta_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    classification, failures, deltas = classify_delta(runs)
    return {
        "schema": "cleanhouse.capability_delta_report.v1",
        "artifact_type": "capability_delta_report",
        "suite": "avatar_runtime_drift_probe",
        "status": "fail" if failures or classification == "regressed" else "ok",
        "classification": classification,
        "run_count": len(runs),
        "metric_deltas": deltas,
        "runs": runs,
        "failures": failures,
        "meaning": (
            "no material capability delta under fixed objective evidence"
            if classification == "no_material_delta"
            else "capability delta measured from fixed objective evidence"
        ),
    }


def _prepare_artifact_root(artifact_dir: Path | None) -> Path | None:
    if artifact_dir is None:
        return None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_root = artifact_dir / f"capability-delta-{_now_stamp()}-{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def _write_offline_verifications(run_dir: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for scenario_name in SCENARIO_NAMES:
        bundle_path = run_dir / "avatar" / f"{scenario_name}-bundle.json"
        if not bundle_path.exists():
            continue
        verification = verify_bundle_path(bundle_path)
        results[scenario_name] = verification
        _write_json(run_dir / "avatar" / f"{scenario_name}-offline-verification.json", verification)
    return results


def _collect_iteration(
    *,
    base_url: str,
    workspace_parent: Path,
    run_index: int,
    run_dir: Path | None,
) -> dict[str, Any]:
    with contextlib.ExitStack() as stack:
        avatar_artifact_dir = (run_dir / "avatar") if run_dir else Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix=f"capability-delta-run-{run_index:03d}-"))
        )
        started = time.monotonic()
        gate_result = avatar_gate.run_gate(
            base_url=base_url,
            workspace_parent=workspace_parent,
            artifact_dir=avatar_artifact_dir,
        )
        elapsed = time.monotonic() - started
        probe_result = _load_json(avatar_artifact_dir / "avatar_probe.json")
        bundles = {
            scenario_name: _load_json(avatar_artifact_dir / f"{scenario_name}-bundle.json")
            for scenario_name in SCENARIO_NAMES
            if (avatar_artifact_dir / f"{scenario_name}-bundle.json").exists()
        }
        capability_run = build_capability_run(
            run_index=run_index,
            probe_result=probe_result,
            bundle_checks=gate_result.get("bundle_checks", []),
            bundles=bundles,
            elapsed_seconds=elapsed,
        )
        capability_run["gate_status"] = gate_result.get("status")
        if run_dir:
            capability_run["offline_verifications"] = _write_offline_verifications(run_dir)
            _write_json(run_dir / "run.json", capability_run)
        return capability_run


def run_capability_delta_gate(
    *,
    base_url: str,
    runs: int,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_root = _prepare_artifact_root(artifact_dir)
    with tempfile.TemporaryDirectory(prefix="capability-delta-workspace-", dir=str(REPO_ROOT)) as workspace_tmp:
        workspace_parent = Path(workspace_tmp).resolve()
        collected_runs: list[dict[str, Any]] = []
        for index in range(1, runs + 1):
            run_dir = artifact_root / f"run-{index:03d}" if artifact_root else None
            if run_dir:
                run_dir.mkdir(parents=True, exist_ok=False)
            collected_runs.append(
                _collect_iteration(
                    base_url=base_url,
                    workspace_parent=workspace_parent,
                    run_index=index,
                    run_dir=run_dir,
                )
            )
    report = build_delta_report(collected_runs)
    report["base_url"] = base_url
    if artifact_root:
        report["artifact_dir"] = str(artifact_root)
        _write_json(artifact_root / "delta-report.json", report)
    return report


def _print_human(report: dict[str, Any]) -> None:
    passed = report.get("status") == "ok"
    print(("PASS" if passed else "FAIL") + " cleanhouse capability delta gate")
    print(f"classification: {report.get('classification', '')}")
    print(f"runs: {report.get('run_count', 0)}")
    if report.get("artifact_dir"):
        print(f"artifact_dir: {report['artifact_dir']}")
    runs = report.get("runs", [])
    if runs:
        latest_metrics = runs[-1].get("metrics", {})
        for key in (
            "verified_completion",
            "scope_drift_count",
            "max_scope_weight",
            "approval_required_count",
            "rejected_approval_count",
            "retry_count",
            "corrective_prompt_count",
            "operator_intervention_count",
            "elapsed_seconds",
            "receipt_replay_hash",
            "bundle_signature_verified",
        ):
            print(f"{key}: {latest_metrics.get(key)}")
    for key, delta in report.get("metric_deltas", {}).items():
        if key in {"verified_completion", "bundle_signature_verified"}:
            continue
        if isinstance(delta, dict) and "delta" in delta:
            print(f"delta.{key}: {delta.get('first')} -> {delta.get('last')} ({delta.get('delta')})")
    for reason in report.get("failures", []):
        print(f"failure: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.runs < 2:
        print("INVALID_USAGE cleanhouse capability delta gate", file=sys.stderr)
        print("--runs must be at least 2", file=sys.stderr)
        return 2

    process: subprocess.Popen | None = None
    with contextlib.ExitStack() as stack:
        artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
        log_path = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="capability-delta-runtime-"))) / "server.log"
        if not avatar_gate._ready(args.base_url):
            if args.no_start:
                print(f"CleanHouse runtime is not ready at {args.base_url}", file=sys.stderr)
                return 1
            temp_home = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="capability-delta-home-")))
            process = avatar_gate._start_runtime(
                args.base_url,
                avatar_gate._default_server_python(),
                temp_home,
                log_path,
            )
            try:
                avatar_gate._wait_for_ready(args.base_url, process, log_path)
            except Exception as exc:
                avatar_gate._stop_runtime(process)
                print(str(exc), file=sys.stderr)
                return 1

        try:
            report = run_capability_delta_gate(
                base_url=args.base_url,
                runs=args.runs,
                artifact_dir=artifact_dir,
            )
        except Exception as exc:
            avatar_gate._stop_runtime(process)
            print(f"capability delta gate failed: {exc}", file=sys.stderr)
            if log_path.exists():
                tail = avatar_gate._tail(log_path)
                if tail:
                    print(tail, file=sys.stderr)
            return 1
        finally:
            avatar_gate._stop_runtime(process)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
