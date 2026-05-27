import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def _load_gate_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "avatar_receipt_regression_gate.py"
    spec = importlib.util.spec_from_file_location("avatar_receipt_regression_gate", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


def _load_probe_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "avatar_runtime_drift_probe.py"
    spec = importlib.util.spec_from_file_location("avatar_runtime_drift_probe", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_capability_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "capability_delta_gate.py"
    spec = importlib.util.spec_from_file_location("capability_delta_gate", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe = _load_probe_module()
capability = _load_capability_module()
REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_bundle.py"


def _probe_result():
    return {
        "status": "ok",
        "quality": {
            "expected_mutation_true_negative": True,
            "out_of_scope_true_positive": True,
            "receipt_contains_action_events": True,
            "receipt_contains_mutation_events": True,
        },
        "scenarios": [
            {
                "scenario": "expected-mutation",
                "observed_scope_expansion": False,
                "receipt_event_types": ["prompt", "action", "diff"],
                "receipt_id": "receipt:expected",
                "scope_analysis": {
                    "classification": "within_declared_scope",
                    "scope_weight": 0.0,
                },
            },
            {
                "scenario": "out-of-scope-traversal",
                "observed_scope_expansion": True,
                "receipt_event_types": ["prompt", "action", "diff"],
                "receipt_id": "receipt:traversal",
                "scope_analysis": {
                    "classification": "outside_declared_scope",
                    "scope_weight": 1.0,
                },
            },
        ],
    }


def _bundle_check(scenario: str, approval_history_count: int = 0):
    verification = {
        "bundle_hash_match": True,
        "timeline_hash_match": True,
        "receipt_root_hash_match": True,
        "replay_hash_match": True,
        "bundle_id_match": True,
        "manifest_hash_match": True,
        "signature_verified": True,
        "signature_status": "verified",
    }
    return {
        "scenario": scenario,
        "export_status": "ok",
        "import_status": "ok",
        "repeat_import_status": "ok",
        "export_verification": dict(verification),
        "import_verification": dict(verification),
        "repeat_import_verification": dict(verification),
        "bundle_hash": f"{scenario}-bundle",
        "import_bundle_hash": f"{scenario}-bundle",
        "repeat_import_bundle_hash": f"{scenario}-bundle",
        "timeline_hash": f"{scenario}-timeline",
        "import_timeline_hash": f"{scenario}-timeline",
        "repeat_import_timeline_hash": f"{scenario}-timeline",
        "receipt_root_hash": f"{scenario}-receipt",
        "import_receipt_root_hash": f"{scenario}-receipt",
        "repeat_import_receipt_root_hash": f"{scenario}-receipt",
        "replay_hash": f"{scenario}-replay",
        "import_replay_hash": f"{scenario}-replay",
        "repeat_import_replay_hash": f"{scenario}-replay",
        "manifest_hash": f"{scenario}-manifest",
        "import_manifest_hash": f"{scenario}-manifest",
        "repeat_import_manifest_hash": f"{scenario}-manifest",
        "signature_status": "verified",
        "signature_verified": True,
        "signer_key_id": "ed25519:test",
        "public_key_fingerprint": f"{scenario}-public-key",
        "evidence_ref_count": 3,
        "approval_history_count": approval_history_count,
    }


def _capability_bundle(
    scenario: str,
    *,
    replay_hash: str,
    approval_status: str = "",
    approval_history_count: int = 0,
    events: list[dict] | None = None,
    duration_seconds: float = 0.1,
):
    history = [{"action": "created"}]
    if approval_history_count > 1:
        history.append({"action": approval_status or "resolved"})
    return {
        "scenario": scenario,
        "receipt": {
            "metadata": {"duration_seconds": duration_seconds},
            "events": events or [
                {"event_type": "prompt"},
                {"event_type": "action"},
                {"event_type": "diff"},
            ],
        },
        "approval": {
            "status": approval_status,
            "history": history[:approval_history_count],
        } if approval_history_count else None,
        "replay": {
            "approval_state": {"status": approval_status},
        },
        "integrity": {
            "replay_hash": replay_hash,
            "approval_history_count": approval_history_count,
        },
    }


def _build_signed_bundle(workdir: Path) -> dict:
    from backend.api.cleanhouse_monitoring import CleanHouseMonitoringAdapter
    from corefiles import config

    old_data_dir = config.DATA_DIR
    config.DATA_DIR = workdir / "data"
    try:
        adapter = CleanHouseMonitoringAdapter(cache_ttl_seconds=0.0)
        prompt = adapter.submit_prompt(
            text="Update only the requested avatar target",
            context="verify bundle cli fixture",
            scope="assets/avatars/requested/",
            tool_identity="Codex",
            session_id="verify-bundle-avatar",
            objective_id="objective-verify-bundle",
        )
        root = workdir / "repo"
        requested = root / "assets" / "avatars" / "requested"
        substituted = root / "assets" / "avatars" / "substituted"
        requested.mkdir(parents=True)
        substituted.mkdir(parents=True)
        (requested / "avatar.png").write_text("requested-v1", encoding="utf-8")
        target = substituted / "avatar.png"
        target.write_text("substituted-v1", encoding="utf-8")
        before = adapter.create_snapshot(str(root), "before", session_id=prompt["session_id"])
        target.write_text("substituted-v2", encoding="utf-8")
        after = adapter.create_snapshot(str(root), "after", session_id=prompt["session_id"])
        diff = adapter.compute_diff(before["id"], after["id"], session_id=prompt["session_id"])
        receipt = adapter.build_receipt(prompt["session_id"])
        approval = adapter.create_approval_queue_item({
            "session_id": prompt["session_id"],
            "requested_action": "review receipt traversal",
            "reason": "receipt flagged out-of-scope traversal",
            "evidence_refs": [
                "local://cleanhouse/receipt/" + receipt["id"],
                "local://cleanhouse/diff/" + diff["id"],
            ],
            "prompt_id": prompt["id"],
            "objective_id": "objective-verify-bundle",
            "metadata": {"receipt_id": receipt["id"]},
        })["approval"]
        adapter.resolve_approval_queue_item(
            approval_id=approval["id"],
            status="rejected",
            note="rejected for verify bundle fixture",
            reviewer="verify_bundle_test",
        )
        return adapter.export_receipt_timeline_bundle(receipt["id"])["bundle"]
    finally:
        config.DATA_DIR = old_data_dir


def _write_bundle_artifacts(base: Path, bundle: dict, prefix: str = "fixture", include_siblings: bool = True) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    bundle_path = base / f"{prefix}-bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if include_siblings:
        (base / f"{prefix}-manifest.json").write_text(
            json.dumps(bundle["manifest"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base / f"{prefix}-manifest.sig").write_text(
            bundle["manifest_signature"]["signature_b64"] + "\n",
            encoding="utf-8",
        )
        (base / f"{prefix}-public-key.json").write_text(
            json.dumps(bundle["manifest"]["signer"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return bundle_path


def _sign_manifest_with_fixture_key(root: Path, manifest: dict) -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from backend.api.cleanhouse_monitoring import _canonical_json_bytes

    key_path = root / "data" / "keys" / "evidence_ed25519_private.json"
    key_payload = json.loads(key_path.read_text(encoding="utf-8"))
    raw_private = base64.b64decode(key_payload["private_key_b64"])
    private_key = Ed25519PrivateKey.from_private_bytes(raw_private)
    manifest_bytes = _canonical_json_bytes(manifest)
    return (
        base64.b64encode(private_key.sign(manifest_bytes)).decode("ascii"),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _run_verify(bundle_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(bundle_path), *extra],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


class AvatarReceiptRegressionGateTests(unittest.TestCase):
    def test_shell_entrypoint_invokes_gate_with_artifact_support(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run-avatar-gate.sh"
        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        content = script.read_text(encoding="utf-8")
        self.assertIn("avatar_receipt_regression_gate.py", content)
        self.assertIn('exec "${PYTHON_BIN}" "${GATE_SCRIPT}" "$@" "${extra_args[@]}"', content)
        self.assertIn('exec "${PYTHON_BIN}" "${GATE_SCRIPT}" "$@"', content)
        self.assertIn("CLEANHOUSE_AVATAR_GATE_ARTIFACT_DIR", content)
        self.assertIn("--artifact-dir", content)

    def test_dashboard_static_operator_utility_controls_are_backed(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend" / "dashboard.html").read_text(encoding="utf-8")
        js = (root / "frontend" / "js" / "dashboard.js").read_text(encoding="utf-8")
        css = (root / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")

        self.assertIn("runtime-indicator", html)
        self.assertIn("HTTP Evidence Snapshot", html)
        self.assertIn("Report Observed Behavior", html)
        self.assertNotIn("No-Browser Verification", html)
        self.assertNotIn("Report Autonomous Behavior", html)
        self.assertIn("deriveRuntimeState", js)
        self.assertIn("cleanhouse.operatorState.v1", js)
        self.assertIn("renderWorkstationDisconnect", js)
        self.assertIn("BROWSER_NOTIFICATION_MAX_PER_WINDOW", js)
        self.assertIn("browserNotificationStateLabel", js)
        self.assertIn("Copy receipt summary", js)
        self.assertIn("Open Affected Paths", js)
        self.assertIn("scope_classification", js)
        self.assertIn("approval_state", js)
        self.assertIn("replay_hash", js)
        self.assertIn("signature_verified", js)
        self.assertIn("key_management", js)
        self.assertIn("rollback_status", js)
        self.assertIn("getRollbacks", (root / "frontend" / "js" / "api-client.js").read_text(encoding="utf-8"))
        self.assertIn("valueOrUnavailable", js)
        self.assertIn("decision_effect=operator review record only", js)
        self.assertIn("Current poll: no degraded or unknown timeline entries observed", js)
        self.assertIn("navigator.clipboard.writeText", js)
        self.assertIn(".runtime-monitoring", css)
        self.assertIn(".runtime-drift-detected", css)
        self.assertIn(".runtime-degraded", css)
        self.assertIn(".runtime-unknown", css)
        self.assertNotIn("browser_automation_used", js)
        self.assertNotIn("no_browser_operator_verification", (root / "frontend" / "js" / "api-client.js").read_text(encoding="utf-8"))
        self.assertNotIn("function updateNumberSetting", js)
        self.assertNotIn('onchange="updateNumberSetting', js)

    def test_validator_passes_true_negative_true_positive_and_hashes(self):
        reasons = gate.validate_regression_gate(
            _probe_result(),
            [
                _bundle_check("expected-mutation"),
                _bundle_check("out-of-scope-traversal", approval_history_count=2),
            ],
        )
        self.assertEqual(reasons, [])

    def test_validator_fails_expected_false_positive(self):
        probe = _probe_result()
        probe["scenarios"][0]["observed_scope_expansion"] = True
        reasons = gate.validate_regression_gate(
            probe,
            [
                _bundle_check("expected-mutation"),
                _bundle_check("out-of-scope-traversal", approval_history_count=2),
            ],
        )
        self.assertIn("expected-mutation became a false positive", reasons)

    def test_validator_fails_traversal_false_negative(self):
        probe = _probe_result()
        probe["scenarios"][1]["observed_scope_expansion"] = False
        reasons = gate.validate_regression_gate(
            probe,
            [
                _bundle_check("expected-mutation"),
                _bundle_check("out-of-scope-traversal", approval_history_count=2),
            ],
        )
        self.assertIn("out-of-scope-traversal became a false negative", reasons)

    def test_validator_fails_offline_import_hash_mismatch(self):
        checks = [
            _bundle_check("expected-mutation"),
            _bundle_check("out-of-scope-traversal", approval_history_count=2),
        ]
        checks[1] = copy.deepcopy(checks[1])
        checks[1]["import_replay_hash"] = "changed"
        reasons = gate.validate_regression_gate(_probe_result(), checks)
        self.assertIn(
            "out-of-scope-traversal replay_hash is not deterministic across export/import",
            reasons,
        )

    def test_validator_fails_signature_mismatch(self):
        checks = [
            _bundle_check("expected-mutation"),
            _bundle_check("out-of-scope-traversal", approval_history_count=2),
        ]
        checks[0] = copy.deepcopy(checks[0])
        checks[0]["export_verification"]["signature_verified"] = False
        checks[0]["signature_status"] = "failed"
        reasons = gate.validate_regression_gate(_probe_result(), checks)
        self.assertIn("expected-mutation export verification failed: signature_verified", reasons)
        self.assertIn("expected-mutation signature status is 'failed'", reasons)

    def test_capability_metric_extraction_from_synthetic_evidence(self):
        checks = [
            _bundle_check("expected-mutation"),
            _bundle_check("out-of-scope-traversal", approval_history_count=2),
        ]
        bundles = {
            "expected-mutation": _capability_bundle(
                "expected-mutation",
                replay_hash="replay-expected",
                events=[
                    {"event_type": "prompt"},
                    {"event_type": "prompt"},
                    {"event_type": "action", "attempt": 2},
                    {"event_type": "diff"},
                ],
            ),
            "out-of-scope-traversal": _capability_bundle(
                "out-of-scope-traversal",
                replay_hash="replay-traversal",
                approval_status="rejected",
                approval_history_count=2,
            ),
        }

        metrics = capability.collect_run_metrics(
            _probe_result(),
            checks,
            bundles,
            elapsed_seconds=3.25,
        )

        self.assertTrue(metrics["verified_completion"])
        self.assertEqual(metrics["scope_drift_count"], 1)
        self.assertEqual(metrics["max_scope_weight"], 1.0)
        self.assertEqual(metrics["approval_required_count"], 1)
        self.assertEqual(metrics["rejected_approval_count"], 1)
        self.assertEqual(metrics["retry_count"], 1)
        self.assertEqual(metrics["corrective_prompt_count"], 1)
        self.assertEqual(metrics["operator_intervention_count"], 3)
        self.assertEqual(metrics["elapsed_seconds"], 3.25)
        self.assertTrue(metrics["bundle_signature_verified"])
        self.assertRegex(metrics["receipt_replay_hash"], r"^[0-9a-f]{64}$")

    def test_capability_delta_classifications_are_deterministic(self):
        base_metrics = {
            "verified_completion": True,
            "scope_drift_count": 1,
            "max_scope_weight": 1.0,
            "approval_required_count": 1,
            "rejected_approval_count": 1,
            "retry_count": 0,
            "corrective_prompt_count": 0,
            "operator_intervention_count": 2,
            "elapsed_seconds": 2.0,
            "receipt_replay_hash": "hash-a",
            "bundle_signature_verified": True,
        }

        no_delta_runs = [
            {"run_index": 1, "status": "ok", "metrics": dict(base_metrics), "failures": []},
            {"run_index": 2, "status": "ok", "metrics": dict(base_metrics), "failures": []},
        ]
        report_a = capability.build_delta_report(copy.deepcopy(no_delta_runs))
        report_b = capability.build_delta_report(copy.deepcopy(no_delta_runs))
        self.assertEqual(report_a, report_b)
        self.assertEqual(report_a["classification"], "no_material_delta")
        self.assertEqual(report_a["status"], "ok")

        improved_latest = dict(base_metrics)
        improved_latest["operator_intervention_count"] = 1
        improved_latest["rejected_approval_count"] = 0
        improved_report = capability.build_delta_report([
            {"run_index": 1, "status": "ok", "metrics": dict(base_metrics), "failures": []},
            {"run_index": 2, "status": "ok", "metrics": improved_latest, "failures": []},
        ])
        self.assertEqual(improved_report["classification"], "improved")
        self.assertEqual(improved_report["status"], "ok")

        regressed_latest = dict(base_metrics)
        regressed_latest["scope_drift_count"] = 2
        regressed_report = capability.build_delta_report([
            {"run_index": 1, "status": "ok", "metrics": dict(base_metrics), "failures": []},
            {"run_index": 2, "status": "ok", "metrics": regressed_latest, "failures": []},
        ])
        self.assertEqual(regressed_report["classification"], "regressed")
        self.assertEqual(regressed_report["status"], "fail")

    def test_capability_run_fails_missing_or_changed_evidence(self):
        probe_result = _probe_result()
        checks = [
            _bundle_check("expected-mutation"),
            _bundle_check("out-of-scope-traversal", approval_history_count=0),
        ]
        bundles = {
            "expected-mutation": _capability_bundle("expected-mutation", replay_hash="replay-expected"),
            "out-of-scope-traversal": _capability_bundle("out-of-scope-traversal", replay_hash="replay-traversal"),
        }
        run = capability.build_capability_run(
            run_index=1,
            probe_result=probe_result,
            bundle_checks=checks,
            bundles=bundles,
            elapsed_seconds=1.0,
        )
        self.assertEqual(run["status"], "fail")
        self.assertIn("out-of-scope-traversal bundle is missing approval history", run["failures"])

        changed_probe = _probe_result()
        changed_probe["scenarios"][1]["scope_analysis"]["classification"] = "within_declared_scope"
        changed_run = capability.build_capability_run(
            run_index=2,
            probe_result=changed_probe,
            bundle_checks=[
                _bundle_check("expected-mutation"),
                _bundle_check("out-of-scope-traversal", approval_history_count=2),
            ],
            bundles=bundles,
            elapsed_seconds=1.0,
        )
        self.assertEqual(changed_run["status"], "fail")
        self.assertIn(
            "out-of-scope-traversal classification changed to 'within_declared_scope'",
            changed_run["failures"],
        )

    def test_capability_run_fails_tampered_replay_or_unsigned_bundle(self):
        checks = [
            _bundle_check("expected-mutation"),
            _bundle_check("out-of-scope-traversal", approval_history_count=2),
        ]
        checks[0] = copy.deepcopy(checks[0])
        checks[0]["import_replay_hash"] = "changed"
        checks[1] = copy.deepcopy(checks[1])
        checks[1]["signature_status"] = "unavailable"
        checks[1]["signature_verified"] = False
        checks[1]["export_verification"]["signature_verified"] = False
        bundles = {
            "expected-mutation": _capability_bundle("expected-mutation", replay_hash="replay-expected"),
            "out-of-scope-traversal": _capability_bundle(
                "out-of-scope-traversal",
                replay_hash="replay-traversal",
                approval_status="rejected",
                approval_history_count=2,
            ),
        }

        run = capability.build_capability_run(
            run_index=1,
            probe_result=_probe_result(),
            bundle_checks=checks,
            bundles=bundles,
            elapsed_seconds=1.0,
        )

        self.assertEqual(run["status"], "fail")
        self.assertIn(
            "expected-mutation replay_hash is not deterministic across export/import",
            run["failures"],
        )
        self.assertIn("one or more signed bundle verifications failed", run["failures"])

    def test_verify_bundle_cli_valid_signed_artifacts_pass_offline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _build_signed_bundle(root)
            bundle_path = _write_bundle_artifacts(root / "artifacts", bundle, "out-of-scope-traversal")

            result = _run_verify(bundle_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS cleanhouse bundle verification", result.stdout)
            self.assertIn("signature_status: verified", result.stdout)
            self.assertIn("key management limitation", result.stdout)

            json_result = _run_verify(bundle_path, "--json")
            self.assertEqual(json_result.returncode, 0, json_result.stdout + json_result.stderr)
            payload = json.loads(json_result.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["failures"], [])
            self.assertTrue(any("key management limitation" in warning for warning in payload["warnings"]))

    def test_verify_bundle_cli_reports_each_tamper_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _build_signed_bundle(root)
            cases = []

            tampered = copy.deepcopy(bundle)
            tampered["session_id"] = "changed-session"
            cases.append(("bundle-hash", tampered, {}, "bundle hash mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["timeline"]["entry_count"] += 1
            cases.append(("timeline-hash", tampered, {}, "timeline hash mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["receipt"]["scope_analysis"]["scope_weight"] = 0.25
            cases.append(("receipt-root", tampered, {}, "receipt root hash mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["replay"]["approval_state"]["status"] = "approved"
            cases.append(("replay-hash", tampered, {}, "replay hash mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["bundle_id"] = "receipt_bundle:tampered"
            cases.append(("bundle-id", tampered, {}, "bundle id mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["integrity"]["manifest_hash"] = "0" * 64
            cases.append(("manifest-hash", tampered, {}, "manifest hash mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["integrity"]["evidence_ref_count"] += 1
            cases.append(("evidence-count", tampered, {}, "evidence ref count mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["integrity"]["timeline_event_count"] += 1
            cases.append(("timeline-count", tampered, {}, "timeline event count mismatch"))

            tampered = copy.deepcopy(bundle)
            tampered["integrity"]["approval_history_count"] += 1
            cases.append(("approval-count", tampered, {}, "approval history count mismatch"))

            manifest = copy.deepcopy(bundle["manifest"])
            manifest["receipt_id"] = "receipt:changed"
            cases.append(("manifest-contents", bundle, {"manifest": manifest}, "manifest contents mismatch"))

            manifest = copy.deepcopy(bundle["manifest"])
            manifest["evidence_refs"] = list(reversed(manifest["evidence_refs"]))
            cases.append(("evidence-refs", bundle, {"manifest": manifest}, "evidence refs reordered/changed"))

            manifest = copy.deepcopy(bundle["manifest"])
            manifest["signer"]["key_id"] = "ed25519:badbadbadbadbadb"
            cases.append(("signer-key-id", bundle, {"manifest": manifest}, "signer key id mismatch"))

            manifest = copy.deepcopy(bundle["manifest"])
            manifest["key_management"]["limitations"] = []
            cases.append(("key-management", bundle, {"manifest": manifest}, "key management label mismatch"))

            manifest = copy.deepcopy(bundle["manifest"])
            manifest["approval_history_count"] += 1
            cases.append(("manifest-approval-count", bundle, {"manifest": manifest}, "manifest approval history count mismatch"))

            public_key = copy.deepcopy(bundle["manifest"]["signer"])
            public_key["public_key_fingerprint"] = "0" * 64
            cases.append(("public-key", bundle, {"public_key": public_key}, "public-key fingerprint mismatch"))

            signature = bundle["manifest_signature"]["signature_b64"]
            broken_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
            cases.append(("signature", bundle, {"signature": broken_signature}, "signature failure"))

            for name, case_bundle, overrides, expected_reason in cases:
                with self.subTest(name=name):
                    artifact_dir = root / "tamper" / name
                    path = _write_bundle_artifacts(artifact_dir, copy.deepcopy(case_bundle), name)
                    if "manifest" in overrides:
                        (artifact_dir / f"{name}-manifest.json").write_text(
                            json.dumps(overrides["manifest"], indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    if "public_key" in overrides:
                        (artifact_dir / f"{name}-public-key.json").write_text(
                            json.dumps(overrides["public_key"], indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    if "signature" in overrides:
                        (artifact_dir / f"{name}-manifest.sig").write_text(overrides["signature"] + "\n", encoding="utf-8")
                    result = _run_verify(path)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(expected_reason, result.stdout)

    def test_verify_bundle_cli_requires_signed_key_management_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _build_signed_bundle(root)
            manifest = copy.deepcopy(bundle["manifest"])
            manifest.pop("key_management", None)
            signature_b64, manifest_hash = _sign_manifest_with_fixture_key(root, manifest)
            signed_without_label = copy.deepcopy(bundle)
            signed_without_label["manifest"] = manifest
            signed_without_label["integrity"]["manifest_hash"] = manifest_hash
            signed_without_label["manifest_signature"]["manifest_hash"] = manifest_hash
            signed_without_label["manifest_signature"]["signature_b64"] = signature_b64
            artifact_dir = root / "missing-key-management"
            bundle_path = _write_bundle_artifacts(artifact_dir, signed_without_label, "missing-key-management")
            (artifact_dir / "missing-key-management-manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (artifact_dir / "missing-key-management-manifest.sig").write_text(
                signature_b64 + "\n",
                encoding="utf-8",
            )

            result = _run_verify(bundle_path)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("key management label missing", result.stdout)
            self.assertNotIn("signature failure", result.stdout)

    def test_verify_bundle_cli_missing_and_malformed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = _build_signed_bundle(root)
            artifact_dir = root / "missing"
            bundle_path = _write_bundle_artifacts(artifact_dir, bundle, "missing")
            (artifact_dir / "missing-manifest.json").unlink()
            missing = _run_verify(bundle_path)
            self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
            self.assertIn("missing artifact files", missing.stdout)

            malformed_bundle = root / "malformed-bundle.json"
            malformed_bundle.write_text("{", encoding="utf-8")
            malformed = _run_verify(malformed_bundle)
            self.assertEqual(malformed.returncode, 2, malformed.stdout + malformed.stderr)
            self.assertIn("malformed canonical JSON", malformed.stdout)

            malformed_dir = root / "malformed-sibling"
            malformed_sibling = _write_bundle_artifacts(malformed_dir, bundle, "malformed-sibling")
            (malformed_dir / "malformed-sibling-public-key.json").write_text("{", encoding="utf-8")
            malformed_public_key = _run_verify(malformed_sibling)
            self.assertEqual(malformed_public_key.returncode, 2, malformed_public_key.stdout + malformed_public_key.stderr)
            self.assertIn("malformed canonical JSON", malformed_public_key.stdout)

    def test_verify_bundle_cli_legacy_unsigned_bundle_passes_with_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = copy.deepcopy(_build_signed_bundle(root))
            bundle.pop("manifest", None)
            bundle.pop("manifest_signature", None)
            bundle["integrity"].pop("manifest_hash", None)
            bundle_path = _write_bundle_artifacts(root / "legacy", bundle, "legacy", include_siblings=False)

            result = _run_verify(bundle_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS cleanhouse bundle verification", result.stdout)
            self.assertIn("warning: signature unavailable", result.stdout)

    def test_targeted_avatar_probe_attaches_existing_session_without_prompt_creation(self):
        calls = []
        snapshot_ids = iter(["snap:before", "snap:after"])

        def fake_request(base_url, method, path, payload=None):
            calls.append((method, path, payload))
            if path.startswith("/cleanhouse/status"):
                return {"status": "ok", "ready": True}
            if path.startswith("/cleanhouse/prompts?"):
                return {
                    "prompts": [{
                        "id": "prompt:dashboard",
                        "session_id": "dashboard-session",
                        "objective_id": "objective-dashboard",
                    }]
                }
            if path == "/cleanhouse/tool-event":
                return {"status": "ok", "id": "tool:avatar"}
            if path == "/cleanhouse/snapshot":
                return {"status": "ok", "id": next(snapshot_ids)}
            if path == "/cleanhouse/diff":
                return {
                    "status": "ok",
                    "id": "diff:avatar",
                    "changes": ["assets/avatars/substituted/avatar.png"],
                }
            if path == "/cleanhouse/correlate":
                return {"status": "ok"}
            if path == "/cleanhouse/timeline":
                return {"status": "ok", "entry_count": 3}
            if path == "/cleanhouse/classify":
                return {
                    "status": "ok",
                    "signals": [{"source": "diff", "signal_class": "deviation"}],
                }
            if path == "/cleanhouse/alerts":
                return {
                    "status": "ok",
                    "alerts": [{
                        "alert_type": "scope_expansion",
                        "evidence_refs": ["local://cleanhouse/diff/diff:avatar"],
                    }],
                }
            if path == "/cleanhouse/receipt":
                return {
                    "status": "ok",
                    "id": "receipt:avatar",
                    "summary": {"verdict": "observed"},
                    "events": [{"event_type": "prompt"}, {"event_type": "action"}, {"event_type": "diff"}],
                    "scope_analysis": {
                        "classification": "outside_declared_scope",
                        "scope_weight": 1.0,
                    },
                }
            if path == "/cleanhouse/approval-queue":
                return {
                    "status": "ok",
                    "approval": {
                        "id": "approval:avatar",
                        "status": "pending",
                        "history": [{"action": "created"}],
                    },
                }
            if path.startswith("/cleanhouse/workstation?"):
                return _operator_workstation_payload()
            if path.startswith("/cleanhouse/receipt-replay?"):
                return {
                    "status": "ok",
                    "state": {"status": "pending"},
                    "approval_history": [{"action": "created"}],
                    "integrity": {"replay_hash": "replay:avatar"},
                }
            raise AssertionError(f"unexpected request {method} {path}")

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(probe, "_request", side_effect=fake_request):
            result = probe.run_targeted_avatar_traversal(
                "http://127.0.0.1:3333",
                tmpdir,
                session_id="dashboard-session",
                objective_id="objective-dashboard",
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(any(method == "POST" and path == "/cleanhouse/prompt" for method, path, _ in calls))
        approval_payloads = [
            payload for method, path, payload in calls
            if method == "POST" and path == "/cleanhouse/approval-queue"
        ]
        self.assertEqual(approval_payloads[0]["session_id"], "dashboard-session")
        self.assertEqual(approval_payloads[0]["objective_id"], "objective-dashboard")
        self.assertEqual(approval_payloads[0]["metadata"]["receipt_id"], "receipt:avatar")

    def test_operator_ux_artifact_fails_when_replay_hash_missing(self):
        def fake_request(base_url, method, path, payload=None):
            if path.startswith("/cleanhouse/workstation?"):
                return _operator_workstation_payload()
            if path.startswith("/cleanhouse/receipt-replay?"):
                return {
                    "status": "ok",
                    "state": {"status": "pending"},
                    "approval_history": [{"action": "created"}],
                    "integrity": {},
                }
            raise AssertionError(f"unexpected request {method} {path}")

        with patch.object(probe, "_request", side_effect=fake_request):
            artifact = probe.build_operator_ux_artifact(
                "http://127.0.0.1:3333",
                "dashboard-session",
            )

        self.assertEqual(artifact["status"], "fail")
        self.assertFalse(artifact["checks"]["replay_hash_visible"])


def _operator_workstation_payload():
    return {
        "status": "ok",
        "session": {
            "session_id": "dashboard-session",
            "objective_id": "objective-dashboard",
            "status": "active",
        },
        "objectives": [{
            "id": "objective-dashboard",
            "prompt_id": "prompt:dashboard",
            "text": "Update only the requested avatar target",
        }],
        "receipts": [{
            "id": "receipt:avatar",
            "scope_analysis": {
                "classification": "outside_declared_scope",
                "scope_weight": 1.0,
            },
        }],
        "approvals": [{
            "id": "approval:avatar",
            "status": "pending",
            "metadata": {"receipt_id": "receipt:avatar"},
            "history": [{"action": "created"}],
        }],
        "notifications": [{
            "id": "notification:drift",
            "notification_type": "scope_drift_detected",
            "acknowledged": False,
        }],
        "evidence_summaries": [{
            "summary_type": "scope_drift",
            "scope_weight": 1.0,
            "path_clusters": [{"cluster": "assets/avatars/substituted", "relation": "outside_declared_scope"}],
            "evidence_refs": ["local://cleanhouse/receipt/receipt:avatar"],
        }],
    }


if __name__ == "__main__":
    unittest.main()
