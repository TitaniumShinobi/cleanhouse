#!/usr/bin/env python3
"""Offline verification for CleanHouse signed receipt bundles."""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.api.cleanhouse_monitoring import (  # noqa: E402
    CleanHouseMonitoringAdapter,
    _canonical_json_bytes,
    _evidence_key_management_profile,
)


EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INVALID_USAGE = 2


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return None, f"malformed canonical JSON: {path.name} is not an object"
        _canonical_json_bytes(payload)
        return payload, None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, f"malformed canonical JSON: {path.name}: {exc}"


def _artifact_paths(bundle_path: Path) -> dict[str, Path]:
    if bundle_path.name == "bundle.json":
        return {
            "manifest": bundle_path.with_name("manifest.json"),
            "signature": bundle_path.with_name("manifest.sig"),
            "public_key": bundle_path.with_name("public-key.json"),
        }
    if bundle_path.name.endswith("-bundle.json"):
        prefix = bundle_path.name[: -len("-bundle.json")]
        return {
            "manifest": bundle_path.with_name(f"{prefix}-manifest.json"),
            "signature": bundle_path.with_name(f"{prefix}-manifest.sig"),
            "public_key": bundle_path.with_name(f"{prefix}-public-key.json"),
        }
    return {
        "manifest": bundle_path.with_name(f"{bundle_path.stem}-manifest.json"),
        "signature": bundle_path.with_name(f"{bundle_path.stem}-manifest.sig"),
        "public_key": bundle_path.with_name(f"{bundle_path.stem}-public-key.json"),
    }


def _has_signed_indicators(bundle: dict[str, Any], paths: dict[str, Path]) -> bool:
    integrity = bundle.get("integrity", {}) if isinstance(bundle.get("integrity"), dict) else {}
    return any((
        isinstance(bundle.get("manifest"), dict),
        isinstance(bundle.get("manifest_signature"), dict),
        bool(integrity.get("manifest_hash")),
        any(path.exists() for path in paths.values()),
    ))


def _read_signature(path: Path) -> tuple[str | None, str | None]:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return None, f"missing artifact files: {path.name}: {exc}"
    try:
        raw_signature = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        return None, f"malformed signature artifact: {path.name}: invalid base64: {exc}"
    if len(raw_signature) != 64:
        return None, f"malformed signature artifact: {path.name}: ed25519 signature length mismatch"
    if base64.b64encode(raw_signature).decode("ascii") != value:
        return None, f"malformed signature artifact: {path.name}: non-canonical base64"
    return value, None


def _hydrate_bundle(
    bundle: dict[str, Any],
    manifest: dict[str, Any] | None,
    signature_b64: str | None,
) -> dict[str, Any]:
    hydrated = copy.deepcopy(bundle)
    if manifest is not None:
        hydrated["manifest"] = manifest
    if signature_b64 is not None:
        manifest_payload = hydrated.get("manifest", {})
        signer = manifest_payload.get("signer", {}) if isinstance(manifest_payload, dict) else {}
        embedded = hydrated.get("manifest_signature", {})
        signature = copy.deepcopy(embedded) if isinstance(embedded, dict) else {}
        signature["algorithm"] = "ed25519"
        signature["signature_encoding"] = "base64"
        signature["signature_b64"] = signature_b64
        if isinstance(manifest_payload, dict):
            signature.setdefault("manifest_hash", hashlib.sha256(_canonical_json_bytes(manifest_payload)).hexdigest())
        if isinstance(signer, dict):
            signature.setdefault("key_id", signer.get("key_id", ""))
            signature.setdefault("public_key_fingerprint", signer.get("public_key_fingerprint", ""))
        hydrated["manifest_signature"] = signature
    return hydrated


def _fingerprint_from_public_key(public_key: dict[str, Any]) -> tuple[str, str]:
    raw_public = base64.b64decode(str(public_key.get("public_key_b64", "")), validate=True)
    if len(raw_public) != 32:
        raise ValueError("public-key length mismatch")
    fingerprint = hashlib.sha256(raw_public).hexdigest()
    return fingerprint, f"ed25519:{fingerprint[:16]}"


def _public_key_failures(manifest: dict[str, Any] | None, public_key: dict[str, Any] | None) -> list[str]:
    if not manifest or not public_key:
        return []
    signer = manifest.get("signer", {}) if isinstance(manifest.get("signer"), dict) else {}
    failures: list[str] = []
    for key_payload in (signer, public_key):
        if str(key_payload.get("algorithm", "")) != "ed25519":
            failures.append("public-key algorithm mismatch")
        if str(key_payload.get("public_key_encoding", "")) != "raw-base64":
            failures.append("public-key encoding mismatch")
    try:
        signer_fingerprint, signer_key_id = _fingerprint_from_public_key(signer)
        public_fingerprint, public_key_id = _fingerprint_from_public_key(public_key)
    except ValueError as exc:
        return sorted(set([*failures, str(exc)]))
    except Exception:
        return sorted(set([*failures, "public-key fingerprint mismatch"]))
    if signer.get("public_key_fingerprint") != signer_fingerprint:
        failures.append("public-key fingerprint mismatch")
    if public_key.get("public_key_fingerprint") != public_fingerprint:
        failures.append("public-key fingerprint mismatch")
    if signer.get("public_key_b64") != public_key.get("public_key_b64"):
        failures.append("public-key fingerprint mismatch")
    if signer.get("public_key_fingerprint") != public_key.get("public_key_fingerprint"):
        failures.append("public-key fingerprint mismatch")
    if signer.get("key_id") != signer_key_id:
        failures.append("signer key id mismatch")
    if public_key.get("key_id") != public_key_id:
        failures.append("signer key id mismatch")
    if signer.get("key_id") != public_key.get("key_id"):
        failures.append("signer key id mismatch")
    return sorted(set(failures))


def _deterministic_evidence_failures(
    adapter: CleanHouseMonitoringAdapter,
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    integrity = bundle.get("integrity", {}) if isinstance(bundle.get("integrity"), dict) else {}
    timeline = bundle.get("timeline", {}) if isinstance(bundle.get("timeline"), dict) else {}
    approval = bundle.get("approval", {}) if isinstance(bundle.get("approval"), dict) else {}
    replay = bundle.get("replay", {}) if isinstance(bundle.get("replay"), dict) else {}
    manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest"), dict) else {}
    evidence_chain = bundle.get("evidence_chain", []) if isinstance(bundle.get("evidence_chain"), list) else []
    approval_history = approval.get("history", []) if isinstance(approval.get("history"), list) else []
    replay_approval_history = (
        replay.get("approval_history", []) if isinstance(replay.get("approval_history"), list) else approval_history
    )
    expected_signed_refs = adapter._receipt_bundle_evidence_refs(bundle)

    if "evidence_ref_count" in integrity and integrity.get("evidence_ref_count") != len(evidence_chain):
        failures.append("evidence ref count mismatch")
    if "timeline_event_count" in integrity and integrity.get("timeline_event_count") != timeline.get("entry_count", 0):
        failures.append("timeline event count mismatch")
    if "approval_history_count" in integrity and (
        integrity.get("approval_history_count") != len(approval_history)
        or integrity.get("approval_history_count") != len(replay_approval_history)
    ):
        failures.append("approval history count mismatch")

    if verification.get("signature_status") != "unavailable" and isinstance(manifest, dict):
        key_management = manifest.get("key_management")
        if not isinstance(key_management, dict):
            failures.append("key management label missing")
        elif key_management != _evidence_key_management_profile():
            failures.append("key management label mismatch")
        if manifest.get("evidence_ref_count", 0) != len(expected_signed_refs):
            failures.append("manifest evidence ref count mismatch")
        if manifest.get("approval_history_count", 0) != len(replay_approval_history):
            failures.append("manifest approval history count mismatch")
    return failures


def _key_management_warnings(verification: dict[str, Any]) -> list[str]:
    status = verification.get("signature_status")
    if status == "verified":
        return [
            "key management limitation: local unmanaged Ed25519 key; verify public-key fingerprint through a separate trusted channel",
            "key management limitation: no rotation, revocation, certificate authority, or hardware-backed key storage in Gate A",
        ]
    if status == "unavailable":
        return [
            "key management limitation: unsigned legacy bundle has no signature trust anchor",
        ]
    return []


def _verification_failures(
    adapter: CleanHouseMonitoringAdapter,
    bundle: dict[str, Any],
    verification: dict[str, Any],
    public_key_failures: list[str],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if verification.get("bundle_hash_match") is False:
        failures.append("bundle hash mismatch")
    if verification.get("timeline_hash_match") is False:
        failures.append("timeline hash mismatch")
    if verification.get("receipt_root_hash_match") is False:
        failures.append("receipt root hash mismatch")
    if verification.get("replay_hash_match") is False:
        failures.append("replay hash mismatch")
    if verification.get("bundle_id_match") is False:
        failures.append("bundle id mismatch")
    if verification.get("manifest_hash_match") is False and verification.get("signature_status") != "unavailable":
        failures.append("manifest hash mismatch")
    if verification.get("manifest_contents_match") is False and verification.get("signature_status") != "unavailable":
        failures.append("manifest contents mismatch")
        manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest"), dict) else {}
        if manifest.get("evidence_refs") != adapter._receipt_bundle_evidence_refs(bundle):
            failures.append("evidence refs reordered/changed")
        signature = bundle.get("manifest_signature", {}) if isinstance(bundle.get("manifest_signature"), dict) else {}
        signer = manifest.get("signer", {}) if isinstance(manifest.get("signer"), dict) else {}
        if signature.get("key_id") != signer.get("key_id"):
            failures.append("signer key id mismatch")
        if signature.get("public_key_fingerprint") != signer.get("public_key_fingerprint"):
            failures.append("public-key fingerprint mismatch")
    if verification.get("signature_status") == "unavailable":
        warnings.append("signature unavailable")
    elif verification.get("signature_verified") is not True:
        failures.append("signature failure")
    if (
        verification.get("key_management_label_present") is True
        and verification.get("key_management_label_match") is False
        and verification.get("signature_status") != "unavailable"
    ):
        failures.append("key management label mismatch")
    warnings.extend(_key_management_warnings(verification))
    failures.extend(_deterministic_evidence_failures(adapter, bundle, verification))
    failures.extend(public_key_failures)
    return sorted(set(failures)), sorted(set(warnings))


def verify_bundle_path(bundle_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "fail",
        "exit_code": EXIT_FAIL,
        "bundle_path": str(bundle_path),
        "receipt_id": "",
        "bundle_id": "",
        "verification": {},
        "warnings": [],
        "failures": [],
    }
    if not bundle_path.is_file():
        result["status"] = "invalid_usage"
        result["exit_code"] = EXIT_INVALID_USAGE
        result["failures"] = [f"missing bundle file: {bundle_path}"]
        return result

    bundle, error = _load_json(bundle_path)
    if error:
        result["status"] = "invalid_usage"
        result["exit_code"] = EXIT_INVALID_USAGE
        result["failures"] = [error]
        return result
    assert bundle is not None

    paths = _artifact_paths(bundle_path)
    signed = _has_signed_indicators(bundle, paths)
    manifest = None
    public_key = None
    signature_b64 = None
    public_key_failures: list[str] = []

    if signed:
        missing = [path.name for path in paths.values() if not path.is_file()]
        if missing:
            result.update({
                "receipt_id": str(bundle.get("receipt_id", "")),
                "bundle_id": str(bundle.get("bundle_id", "")),
                "failures": ["missing artifact files: " + ", ".join(sorted(missing))],
            })
            return result
        manifest, error = _load_json(paths["manifest"])
        if error:
            result["status"] = "invalid_usage"
            result["exit_code"] = EXIT_INVALID_USAGE
            result["failures"] = [error]
            return result
        public_key, error = _load_json(paths["public_key"])
        if error:
            result["status"] = "invalid_usage"
            result["exit_code"] = EXIT_INVALID_USAGE
            result["failures"] = [error]
            return result
        signature_b64, error = _read_signature(paths["signature"])
        if error:
            result["failures"] = [error]
            return result
        public_key_failures = _public_key_failures(manifest, public_key)

    hydrated = _hydrate_bundle(bundle, manifest, signature_b64)
    adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
    adapter.persistence_enabled = False
    verification_result = adapter.verify_receipt_timeline_bundle(hydrated)
    verification = verification_result.get("verification", {})
    failures, warnings = _verification_failures(adapter, hydrated, verification, public_key_failures)
    if verification_result.get("status") != "ok" and not failures:
        failures.append(str(verification_result.get("message") or "verification failed"))
    result.update({
        "status": "pass" if not failures else "fail",
        "exit_code": EXIT_PASS if not failures else EXIT_FAIL,
        "receipt_id": str(hydrated.get("receipt_id", "")),
        "bundle_id": str(hydrated.get("bundle_id", "")),
        "verification": verification,
        "warnings": warnings,
        "failures": failures,
    })
    return result


def _print_human(result: dict[str, Any]) -> None:
    passed = result.get("exit_code") == EXIT_PASS
    print(("PASS" if passed else "FAIL") + " cleanhouse bundle verification")
    if result.get("receipt_id"):
        print(f"receipt_id: {result['receipt_id']}")
    if result.get("bundle_id"):
        print(f"bundle_id: {result['bundle_id']}")
    verification = result.get("verification", {}) if isinstance(result.get("verification"), dict) else {}
    if verification.get("computed_replay_hash") or verification.get("expected_replay_hash"):
        print(f"replay_hash: {verification.get('expected_replay_hash') or verification.get('computed_replay_hash')}")
    if verification.get("manifest_hash"):
        print(f"manifest_hash: {verification['manifest_hash']}")
    if verification.get("signature_status"):
        print(f"signature_status: {verification['signature_status']}")
    for warning in result.get("warnings", []):
        print(f"warning: {warning}")
    for failure in result.get("failures", []):
        print(f"failure: {failure}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a CleanHouse receipt bundle offline.")
    parser.add_argument("bundle", nargs="?", help="Path to *-bundle.json or bundle.json")
    parser.add_argument("--json", action="store_true", help="Print deterministic JSON instead of human-readable output")
    args = parser.parse_args(argv)
    if not args.bundle:
        result = {
            "status": "invalid_usage",
            "exit_code": EXIT_INVALID_USAGE,
            "bundle_path": "",
            "receipt_id": "",
            "bundle_id": "",
            "verification": {},
            "warnings": [],
            "failures": ["missing bundle argument"],
        }
    else:
        result = verify_bundle_path(Path(args.bundle).expanduser().resolve())
    if args.json:
        print(_json_dump(result))
    else:
        _print_human(result)
    return int(result.get("exit_code", EXIT_FAIL))


if __name__ == "__main__":
    raise SystemExit(main())
