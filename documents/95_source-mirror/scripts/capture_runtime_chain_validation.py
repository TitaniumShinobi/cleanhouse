#!/usr/bin/env python3
"""Capture one runtime-chain validation artifact set (not canonical).

Writes a run folder:
  docs/evidence/runtime_chain_validation/<utc-timestamp>_<event-id>/

Required artifacts:
  - chain_ids.json
  - outcome.json
  - evidence_refs.json
  - incident_receipt.json
  - test_output.txt
  - operator_screenshot.png
  - manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "docs" / "evidence" / "runtime_chain_validation"
RUN_NOTES_DEFAULT = "validation_only"


def _now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
    except Exception as exc:  # pragma: no cover - cli path validation
        raise SystemExit(f"invalid {label} json: {path} ({exc})")
    if not isinstance(loaded, dict):
        raise SystemExit(f"{label} json must be an object: {path}")
    return loaded


def _extract_outcome_fields(receipt_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    card = receipt_payload.get("card", {}) if isinstance(receipt_payload.get("card"), dict) else {}
    outcome = card.get("outcome", {}) if isinstance(card.get("outcome"), dict) else {}
    qpb_case = card.get("qpb_case", {}) if isinstance(card.get("qpb_case"), dict) else {}
    decision_path = card.get("decision_path", {}) if isinstance(card.get("decision_path"), dict) else {}
    outcome_hash = str(outcome.get("integrity_root_hash", "") or "").strip()
    if not outcome_hash:
        raise SystemExit("receipt payload missing card.outcome.integrity_root_hash")
    state = {
        "qpb_case_status": str(qpb_case.get("status", "") or ""),
        "incident_status": str((card.get("incident", {}) or {}).get("status", "") or ""),
        "decision_current_status": str(decision_path.get("current_status", "") or ""),
        "decision_next_action": str(decision_path.get("next_action", "") or ""),
        "outcome_action": str(outcome.get("action", "") or ""),
        "outcome_actor": str(outcome.get("actor", "") or ""),
        "outcome_timestamp": str(outcome.get("timestamp", "") or ""),
    }
    return state, outcome_hash


def _extract_evidence_refs(
    receipt_payload: dict[str, Any],
    event_payload: dict[str, Any] | None,
    incident_payload: dict[str, Any] | None,
) -> list[str]:
    refs: list[str] = []

    def _add(items: Any) -> None:
        if not isinstance(items, list):
            return
        for raw in items:
            if isinstance(raw, dict):
                value = raw.get("uri")
            else:
                value = raw
            ref = str(value or "").strip()
            if ref and ref not in refs:
                refs.append(ref)

    card = receipt_payload.get("card", {}) if isinstance(receipt_payload.get("card"), dict) else {}
    evidence = card.get("evidence", {}) if isinstance(card.get("evidence"), dict) else {}
    _add(evidence.get("refs", []))
    if event_payload is not None:
        _add(event_payload.get("evidence_refs", []))
    if incident_payload is not None:
        _add(incident_payload.get("evidence_refs", []))
    return refs


def _build_manifest(run_dir: Path, files: list[str], *, captured_at_utc: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for name in files:
        path = run_dir / name
        entries.append({
            "file": name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return {
        "captured_at_utc": captured_at_utc,
        "validation_only": True,
        "notes": RUN_NOTES_DEFAULT,
        "artifact_count": len(entries),
        "artifacts": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture one runtime chain validation artifact set.")
    parser.add_argument("--artifact-root", default=str(DEFAULT_ARTIFACT_ROOT), help="Base runtime validation directory.")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--incident-receipt-json-source",
        required=True,
        help="Path to receipt payload json (raw API response after final decision).",
    )
    parser.add_argument(
        "--test-output-source",
        required=True,
        help="Path to text file with exact commands + pass/fail output.",
    )
    parser.add_argument(
        "--operator-screenshot-source",
        required=True,
        help="Path to operator-captured PNG screenshot.",
    )
    parser.add_argument(
        "--event-json-source",
        default="",
        help="Optional path to event json payload for evidence ref merge.",
    )
    parser.add_argument(
        "--incident-json-source",
        default="",
        help="Optional path to incident json payload for evidence ref merge.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    event_id = str(args.event_id).strip()
    incident_id = str(args.incident_id).strip()
    receipt_id = str(args.receipt_id).strip()
    session_id = str(args.session_id).strip()

    if not event_id or not incident_id or not receipt_id or not session_id:
        raise SystemExit("event-id, incident-id, receipt-id, and session-id are required")

    artifact_root = Path(args.artifact_root).expanduser().resolve()
    receipt_src = Path(args.incident_receipt_json_source).expanduser().resolve()
    test_output_src = Path(args.test_output_source).expanduser().resolve()
    screenshot_src = Path(args.operator_screenshot_source).expanduser().resolve()
    event_src = Path(args.event_json_source).expanduser().resolve() if args.event_json_source else None
    incident_src = Path(args.incident_json_source).expanduser().resolve() if args.incident_json_source else None

    if not receipt_src.exists():
        raise SystemExit(f"missing receipt json source: {receipt_src}")
    if not test_output_src.exists():
        raise SystemExit(f"missing test output source: {test_output_src}")
    if not screenshot_src.exists():
        raise SystemExit(f"missing screenshot source: {screenshot_src}")
    if screenshot_src.suffix.lower() != ".png":
        raise SystemExit(f"operator screenshot must be .png: {screenshot_src}")
    if event_src is not None and not event_src.exists():
        raise SystemExit(f"event json source not found: {event_src}")
    if incident_src is not None and not incident_src.exists():
        raise SystemExit(f"incident json source not found: {incident_src}")

    captured_at_utc = _now_utc_iso()
    run_name = f"{_now_utc_compact()}_{_safe_slug(event_id, fallback='event')}"
    run_dir = artifact_root / run_name
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)

    receipt_payload = _load_json_file(receipt_src, "incident receipt")
    event_payload = _load_json_file(event_src, "event") if event_src is not None else None
    incident_payload = _load_json_file(incident_src, "incident") if incident_src is not None else None

    decision_state, outcome_hash = _extract_outcome_fields(receipt_payload)
    evidence_refs = _extract_evidence_refs(receipt_payload, event_payload, incident_payload)

    chain_ids = {
        "event_id": event_id,
        "incident_id": incident_id,
        "receipt_id": receipt_id,
        "session_id": session_id,
        "timestamps": {
            "captured_at_utc": captured_at_utc,
            "run_folder_timestamp_utc": run_name.split("_", 1)[0],
        },
    }
    outcome = {
        "final_decision_state": decision_state,
        "outcome_hash": outcome_hash,
    }
    evidence = {
        "evidence_refs": evidence_refs,
        "count": len(evidence_refs),
    }

    _write_json(run_dir / "chain_ids.json", chain_ids)
    _write_json(run_dir / "outcome.json", outcome)
    _write_json(run_dir / "evidence_refs.json", evidence)
    _write_json(run_dir / "incident_receipt.json", receipt_payload)
    shutil.copyfile(test_output_src, run_dir / "test_output.txt")
    shutil.copyfile(screenshot_src, run_dir / "operator_screenshot.png")

    file_order = [
        "chain_ids.json",
        "outcome.json",
        "evidence_refs.json",
        "incident_receipt.json",
        "test_output.txt",
        "operator_screenshot.png",
    ]
    manifest = _build_manifest(run_dir, file_order, captured_at_utc=captured_at_utc)
    _write_json(run_dir / "manifest.json", manifest)

    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
