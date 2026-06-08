#!/usr/bin/env python3
"""Generate a beta proof bundle from verified local evidence.

Outputs include:
- targeted test results
- deterministic evidence-chain artifacts
- bundle verification result
- claim matrix
- known limitations
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
from corefiles import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_pytest(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "status": "pass" if proc.returncode == 0 else "fail",
    }


def _build_evidence_chain() -> dict[str, Any]:
    original_data_dir = config.DATA_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp_data, tempfile.TemporaryDirectory() as tmp_repo:
            config.DATA_DIR = Path(tmp_data) / "data"
            os.environ["CLEANHOUSE_NATIVE_NOTIFICATIONS"] = "0"
            adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
            root = Path(tmp_repo)

            prompt = adapter.submit_prompt(
                text="Generate deterministic evidence chain",
                context="beta proof bundle run",
                scope="src/",
                repo_path=str(root),
                tool_identity="codex",
                session_id="beta-proof-session",
                objective_id="objective-beta-proof",
            )
            session_id = str(prompt.get("session_id", "beta-proof-session"))

            events = []
            events.append(adapter.start_operator_session({
                "session_id": session_id,
                "objective_id": "objective-beta-proof",
                "summary": "beta proof objective started",
                "metadata": {"source": "beta-proof"},
            }))

            source_file = root / "src" / "demo.txt"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("before\n", encoding="utf-8")

            before = adapter.create_snapshot(str(root), "before", session_id=session_id)
            source_file.write_text("after\n", encoding="utf-8")
            after = adapter.create_snapshot(str(root), "after", session_id=session_id)
            diff = adapter.compute_diff(before["id"], after["id"], session_id=session_id)

            timeline = adapter.build_timeline(session_id=session_id)
            receipt = adapter.build_receipt(session_id=session_id)
            replay = adapter.replay_receipt_state(receipt["id"])
            bundle_result = adapter.export_receipt_timeline_bundle(receipt["id"])
            verification = adapter.verify_receipt_timeline_bundle(bundle_result["bundle"])

            events.append(adapter.stop_operator_session({
                "session_id": session_id,
                "summary": "beta proof objective completed",
                "metadata": {"source": "beta-proof"},
                "finalize": True,
            }))

            return {
                "session_id": session_id,
                "prompt": prompt,
                "objective_lifecycle": events,
                "before_snapshot": before,
                "after_snapshot": after,
                "diff": diff,
                "timeline": timeline,
                "receipt": receipt,
                "replay": replay,
                "bundle_export": bundle_result,
                "bundle_verification": verification,
            }
    finally:
        config.DATA_DIR = original_data_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate beta proof bundle artifacts.")
    parser.add_argument(
        "--artifact-dir",
        default=str(REPO_ROOT / "docs" / "evidence" / "beta_proof_bundle"),
        help="Directory for output artifacts.",
    )
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    tests = [
        [sys.executable, "-m", "pytest", "-q", "tests/test_events_api.py"],
        [sys.executable, "-m", "pytest", "-q", "tests/test_qpb_mediator_workflows.py"],
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_cleanhouse_monitoring_api.py",
            "-k",
            "integrity_changed_file_detection or integrity_duplicate_scan_stable or integrity_baseline_determinism or prune_deterministic_auditable or objective_start or objective_end",
        ],
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_avatar_receipt_regression_gate.py",
            "-k",
            "verify_bundle_cli_valid_signed_artifacts_pass_offline or verify_bundle_cli_reports_each_tamper_reason",
        ],
    ]

    test_results = [_run_pytest(cmd) for cmd in tests]
    evidence_chain = _build_evidence_chain()

    known_limitations = [
        "Scope is local-first runtime evidence; no external provider trust authority is asserted.",
        "Chain-of-custody is partial; this bundle proves local evidence continuity only.",
        "Desktop notification lane is noise-controlled and not treated as visibility guarantee.",
    ]

    claim_matrix = [
        {
            "claim": "Events API creation/persistence/retrieval paths are executable in current runtime",
            "implemented": True,
            "verified": test_results[0]["status"] == "pass",
            "evidence_ref": "tests/test_events_api.py",
        },
        {
            "claim": "Deterministic prompt->mutation->timeline->receipt->replay->bundle chain exists",
            "implemented": True,
            "verified": evidence_chain["bundle_verification"].get("status") == "ok",
            "evidence_ref": "beta_proof_chain.json",
        },
        {
            "claim": "Retention cleanup is auditable with actor/time/reason",
            "implemented": True,
            "verified": test_results[2]["status"] == "pass",
            "evidence_ref": "tests/test_cleanhouse_monitoring_api.py::test_prune_deterministic_auditable",
        },
    ]

    summary = {
        "generated_at": _now_iso(),
        "artifact_dir": str(artifact_dir),
        "test_pass_count": sum(1 for item in test_results if item["status"] == "pass"),
        "test_total": len(test_results),
        "chain_status": evidence_chain["bundle_verification"].get("status"),
        "known_limitations": known_limitations,
    }

    _write_json(artifact_dir / "test_results.json", test_results)
    _write_json(artifact_dir / "beta_proof_chain.json", evidence_chain)
    _write_json(artifact_dir / "claim_matrix.json", claim_matrix)
    _write_json(artifact_dir / "known_limitations.json", known_limitations)
    _write_json(artifact_dir / "beta_proof_bundle.json", summary)

    print(f"artifact_dir: {artifact_dir}")
    print(f"tests_passed: {summary['test_pass_count']}/{summary['test_total']}")
    print(f"chain_status: {summary['chain_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
