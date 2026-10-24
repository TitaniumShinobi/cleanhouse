#!/usr/bin/env python3
"""One-command regression gate for the avatar receipt incident."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from avatar_runtime_drift_probe import DEFAULT_BASE_URL, request_json, run_avatar_probe


VERIFY_KEYS = (
    "bundle_hash_match",
    "timeline_hash_match",
    "receipt_root_hash_match",
    "replay_hash_match",
    "bundle_id_match",
    "manifest_hash_match",
    "signature_verified",
)


def _scenario_map(probe_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        scenario.get("scenario", ""): scenario
        for scenario in probe_result.get("scenarios", [])
        if isinstance(scenario, dict)
    }


def _float_equals(value: Any, expected: float) -> bool:
    try:
        return abs(float(value) - expected) < 1e-9
    except (TypeError, ValueError):
        return False


def validate_probe_result(probe_result: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    scenarios = _scenario_map(probe_result)
    expected = scenarios.get("expected-mutation")
    traversal = scenarios.get("out-of-scope-traversal")

    if probe_result.get("status") != "ok":
        reasons.append(f"probe status is {probe_result.get('status')!r}, expected 'ok'")
    if not expected:
        reasons.append("missing expected-mutation scenario")
    if not traversal:
        reasons.append("missing out-of-scope-traversal scenario")
    if not expected or not traversal:
        return reasons

    expected_analysis = expected.get("scope_analysis", {})
    traversal_analysis = traversal.get("scope_analysis", {})
    if expected.get("observed_scope_expansion"):
        reasons.append("expected-mutation became a false positive")
    if expected_analysis.get("classification") != "within_declared_scope":
        reasons.append(
            f"expected-mutation classification changed to {expected_analysis.get('classification')!r}"
        )
    if not _float_equals(expected_analysis.get("scope_weight"), 0.0):
        reasons.append(f"expected-mutation scope_weight changed to {expected_analysis.get('scope_weight')!r}")

    if not traversal.get("observed_scope_expansion"):
        reasons.append("out-of-scope-traversal became a false negative")
    if traversal_analysis.get("classification") != "outside_declared_scope":
        reasons.append(
            f"out-of-scope-traversal classification changed to {traversal_analysis.get('classification')!r}"
        )
    if not _float_equals(traversal_analysis.get("scope_weight"), 1.0):
        reasons.append(f"out-of-scope-traversal scope_weight changed to {traversal_analysis.get('scope_weight')!r}")

    for scenario in (expected, traversal):
        name = scenario.get("scenario", "unknown")
        event_types = scenario.get("receipt_event_types", [])
        if "action" not in event_types:
            reasons.append(f"{name} receipt is missing action evidence")
        if "diff" not in event_types:
            reasons.append(f"{name} receipt is missing mutation evidence")
        if not scenario.get("receipt_id"):
            reasons.append(f"{name} did not produce a receipt_id")
    return reasons


def validate_bundle_checks(bundle_checks: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    by_name = {
        check.get("scenario", ""): check
        for check in bundle_checks
        if isinstance(check, dict)
    }
    for name in ("expected-mutation", "out-of-scope-traversal"):
        check = by_name.get(name)
        if not check:
            reasons.append(f"missing bundle check for {name}")
            continue
        if check.get("export_status") != "ok":
            reasons.append(f"{name} bundle export status is {check.get('export_status')!r}")
        if check.get("import_status") != "ok":
            reasons.append(f"{name} offline import status is {check.get('import_status')!r}")
        if check.get("repeat_import_status") != "ok":
            reasons.append(f"{name} repeated offline import status is {check.get('repeat_import_status')!r}")
        for key in VERIFY_KEYS:
            if check.get("export_verification", {}).get(key) is not True:
                reasons.append(f"{name} export verification failed: {key}")
            if check.get("import_verification", {}).get(key) is not True:
                reasons.append(f"{name} offline import verification failed: {key}")
            if check.get("repeat_import_verification", {}).get(key) is not True:
                reasons.append(f"{name} repeated offline import verification failed: {key}")
        for key in ("bundle_hash", "timeline_hash", "receipt_root_hash", "replay_hash"):
            values = [
                check.get(key),
                check.get(f"import_{key}"),
                check.get(f"repeat_import_{key}"),
            ]
            if not values[0] or len(set(values)) != 1:
                reasons.append(f"{name} {key} is not deterministic across export/import")
        for key in ("manifest_hash",):
            values = [
                check.get(key),
                check.get(f"import_{key}"),
                check.get(f"repeat_import_{key}"),
            ]
            if not values[0] or len(set(values)) != 1:
                reasons.append(f"{name} {key} is not deterministic across export/import")
        if check.get("signature_status") != "verified":
            reasons.append(f"{name} signature status is {check.get('signature_status')!r}")
        if check.get("evidence_ref_count", 0) < 1:
            reasons.append(f"{name} bundle has no evidence refs")
    traversal = by_name.get("out-of-scope-traversal")
    if traversal and traversal.get("approval_history_count", 0) < 2:
        reasons.append("out-of-scope-traversal bundle is missing approval history")
    return reasons


def validate_regression_gate(probe_result: dict[str, Any], bundle_checks: list[dict[str, Any]]) -> list[str]:
    return validate_probe_result(probe_result) + validate_bundle_checks(bundle_checks)


def _ready(base_url: str) -> bool:
    try:
        request_json(base_url, "GET", "/cleanhouse/status?ready=1")
        return True
    except Exception:
        return False


def _host_port(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if host in {"localhost", "::1"}:
        host = "127.0.0.1"
    return host, parsed.port or 3333


def _default_server_python() -> str:
    local_python = REPO_ROOT / "cleanhouse_env" / "bin" / "python3"
    if local_python.is_file():
        return str(local_python)
    return sys.executable


def _tail(path: Path, max_lines: int = 40) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _start_runtime(base_url: str, python_exe: str, temp_home: Path, log_path: Path) -> subprocess.Popen:
    host, port = _host_port(base_url)
    env = os.environ.copy()
    env["HOME"] = str(temp_home)
    env["CLEANHOUSE_HOST"] = host
    env["CLEANHOUSE_PORT"] = str(port)
    env.setdefault("CLEANHOUSE_ENABLE_AUTH", "0")
    env.setdefault("PYTHONUNBUFFERED", "1")
    log = log_path.open("ab")
    process = subprocess.Popen(
        [python_exe, "backend/server.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    log.close()
    return process


def _wait_for_ready(base_url: str, process: subprocess.Popen | None, log_path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ready(base_url):
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"owned CleanHouse runtime exited before readiness with status {process.returncode}\n{_tail(log_path)}"
            )
        time.sleep(0.25)
    raise RuntimeError(f"CleanHouse runtime did not become ready at {base_url}\n{_tail(log_path)}")


def _stop_runtime(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _offline_import(bundle: dict[str, Any]) -> dict[str, Any]:
    from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter

    adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
    adapter.persistence_enabled = False
    return adapter.import_receipt_timeline_bundle(bundle)


def _ensure_receipt_review(base_url: str, scenario: dict[str, Any]) -> dict[str, Any] | None:
    if scenario.get("scenario") != "out-of-scope-traversal":
        return None
    receipt_id = scenario.get("receipt_id", "")
    diff_id = scenario.get("diff_id", "")
    approval = request_json(base_url, "POST", "/cleanhouse/approval-queue", {
        "session_id": scenario.get("session_id", ""),
        "requested_action": "reject avatar receipt traversal",
        "reason": "receipt flagged substituted avatar path outside declared scope",
        "prompt_id": scenario.get("prompt_id"),
        "objective_id": scenario.get("objective_id"),
        "evidence_refs": [
            f"local://cleanhouse/receipt/{receipt_id}",
            f"local://cleanhouse/diff/{diff_id}",
        ],
        "reviewer_note": "regression gate rejected out-of-scope avatar traversal",
        "reviewer": "avatar_receipt_regression_gate",
        "metadata": {
            "fixture": "avatar_substitution",
            "scenario": scenario.get("scenario"),
            "receipt_id": receipt_id,
        },
    })
    approval_id = approval.get("approval", {}).get("id", "")
    if not approval_id:
        raise RuntimeError("failed to create receipt-linked approval for out-of-scope traversal")
    return request_json(
        base_url,
        "POST",
        f"/cleanhouse/approval-queue/{urllib.parse.quote(approval_id, safe='')}",
        {
            "status": "rejected",
            "note": "regression gate rejected out-of-scope avatar traversal",
            "reviewer": "avatar_receipt_regression_gate",
        },
    )


def _bundle_check(base_url: str, scenario: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_id = scenario.get("receipt_id", "")
    if not receipt_id:
        raise RuntimeError(f"{scenario.get('scenario')} did not produce a receipt_id")
    export = request_json(
        base_url,
        "GET",
        "/cleanhouse/receipt-bundle?" + urllib.parse.urlencode({"receipt_id": receipt_id}),
    )
    bundle = export.get("bundle", {})
    if not isinstance(bundle, dict):
        raise RuntimeError(f"{scenario.get('scenario')} receipt bundle export did not return a bundle")
    imported = _offline_import(bundle)
    imported_again = _offline_import(bundle)
    integrity = bundle.get("integrity", {})
    import_integrity = imported.get("integrity", {})
    repeat_integrity = imported_again.get("integrity", {})
    return {
        "scenario": scenario.get("scenario"),
        "receipt_id": receipt_id,
        "export_status": export.get("status"),
        "import_status": imported.get("status"),
        "repeat_import_status": imported_again.get("status"),
        "export_verification": export.get("verification", {}),
        "import_verification": imported.get("verification", {}),
        "repeat_import_verification": imported_again.get("verification", {}),
        "bundle_hash": integrity.get("bundle_hash"),
        "timeline_hash": integrity.get("timeline_hash"),
        "receipt_root_hash": integrity.get("receipt_root_hash"),
        "replay_hash": integrity.get("replay_hash"),
        "manifest_hash": integrity.get("manifest_hash"),
        "signature_status": export.get("verification", {}).get("signature_status"),
        "signature_verified": export.get("verification", {}).get("signature_verified"),
        "signer_key_id": export.get("verification", {}).get("signer_key_id"),
        "public_key_fingerprint": export.get("verification", {}).get("public_key_fingerprint"),
        "import_bundle_hash": import_integrity.get("bundle_hash"),
        "import_timeline_hash": import_integrity.get("timeline_hash"),
        "import_receipt_root_hash": import_integrity.get("receipt_root_hash"),
        "import_replay_hash": import_integrity.get("replay_hash"),
        "import_manifest_hash": import_integrity.get("manifest_hash"),
        "repeat_import_bundle_hash": repeat_integrity.get("bundle_hash"),
        "repeat_import_timeline_hash": repeat_integrity.get("timeline_hash"),
        "repeat_import_receipt_root_hash": repeat_integrity.get("receipt_root_hash"),
        "repeat_import_replay_hash": repeat_integrity.get("replay_hash"),
        "repeat_import_manifest_hash": repeat_integrity.get("manifest_hash"),
        "evidence_ref_count": integrity.get("evidence_ref_count", 0),
        "approval_history_count": integrity.get("approval_history_count", 0),
    }, bundle


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_gate(
    *,
    base_url: str,
    workspace_parent: Path,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    probe_result = run_avatar_probe(base_url, workspace_parent)
    scenarios = _scenario_map(probe_result)
    for scenario in scenarios.values():
        _ensure_receipt_review(base_url, scenario)

    bundle_checks: list[dict[str, Any]] = []
    if artifact_dir:
        _write_json(artifact_dir / "avatar_probe.json", probe_result)
    for scenario_name in ("expected-mutation", "out-of-scope-traversal"):
        scenario = scenarios.get(scenario_name)
        if scenario is None:
            continue
        check, bundle = _bundle_check(base_url, scenario)
        bundle_checks.append(check)
        if artifact_dir:
            _write_json(artifact_dir / f"{scenario_name}-bundle.json", bundle)
            _write_json(artifact_dir / f"{scenario_name}-bundle-check.json", check)
            if isinstance(bundle.get("manifest"), dict):
                _write_json(artifact_dir / f"{scenario_name}-manifest.json", bundle["manifest"])
                signer = bundle["manifest"].get("signer", {})
                if isinstance(signer, dict):
                    _write_json(artifact_dir / f"{scenario_name}-public-key.json", signer)
            if isinstance(bundle.get("manifest_signature"), dict):
                signature = str(bundle["manifest_signature"].get("signature_b64", ""))
                (artifact_dir / f"{scenario_name}-manifest.sig").write_text(signature + "\n", encoding="utf-8")
            _write_json(artifact_dir / f"{scenario_name}-verification.json", check.get("export_verification", {}))

    reasons = validate_regression_gate(probe_result, bundle_checks)
    result = {
        "status": "ok" if not reasons else "fail",
        "base_url": base_url,
        "quality": probe_result.get("quality", {}),
        "bundle_checks": bundle_checks,
        "failures": reasons,
    }
    if artifact_dir:
        _write_json(artifact_dir / "avatar_receipt_regression_gate.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--workspace-parent", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--python", default="")
    args = parser.parse_args()

    process: subprocess.Popen | None = None
    with contextlib.ExitStack() as stack:
        workspace_parent = Path(args.workspace_parent).resolve() if args.workspace_parent else Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="avatar-gate-workspace-", dir=str(REPO_ROOT)))).resolve()
        workspace_parent.mkdir(parents=True, exist_ok=True)
        artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)

        log_path = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="avatar-gate-runtime-"))) / "server.log"
        if not _ready(args.base_url):
            if args.no_start:
                print(f"CleanHouse runtime is not ready at {args.base_url}", file=sys.stderr)
                return 1
            temp_home = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="avatar-gate-home-")))
            process = _start_runtime(args.base_url, args.python or _default_server_python(), temp_home, log_path)
            try:
                _wait_for_ready(args.base_url, process, log_path)
            except Exception as exc:
                _stop_runtime(process)
                print(str(exc), file=sys.stderr)
                return 1

        try:
            result = run_gate(
                base_url=args.base_url,
                workspace_parent=workspace_parent,
                artifact_dir=artifact_dir,
            )
        except Exception as exc:
            _stop_runtime(process)
            print(f"avatar receipt regression gate failed: {exc}", file=sys.stderr)
            if log_path.exists():
                tail = _tail(log_path)
                if tail:
                    print(tail, file=sys.stderr)
            return 1
        finally:
            _stop_runtime(process)

    if result["status"] != "ok":
        for reason in result.get("failures", []):
            print(f"FAIL: {reason}", file=sys.stderr)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
