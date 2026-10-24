from __future__ import annotations

import json
import hashlib
import hmac
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts import start_isolated_runtime as isolated
from backend import runtime_supervisor


REPO_ROOT = Path(__file__).resolve().parent.parent


class StartIsolatedRuntimeTests(unittest.TestCase):
    def _inputs(self, root: Path, port: int | None = None) -> dict[str, str]:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        auth = root / "auth.json"
        credentials = root / "credentials.json"
        auth.write_text(json.dumps({"schema": "cleanhouse.auth.runtime.v1", "providers": {}}), encoding="utf-8")
        credentials.write_text(json.dumps({
            "invocation_nonce": "n" * 32,
            "flask_secret_key": "s" * 64,
        }), encoding="utf-8")
        auth.chmod(0o600)
        credentials.chmod(0o600)
        if port is None:
            with socket.socket() as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
        return {
            "START_TASK_ROOT": str(root),
            "HOME": str(root / "bootstrap-home"),
            "START_STATE_ROOT": str(root / "state"),
            "START_DATA_ROOT": str(root / "data"),
            "START_AUTH_CONFIG": str(auth),
            "START_EPHEMERAL_CREDENTIALS": str(credentials),
            "START_INVOCATION_NONCE": "n" * 32,
            "START_HOST": "127.0.0.1",
            "START_PORT": str(port),
        }

    def test_declaration_is_source_bound_and_has_all_seven_lanes(self):
        declaration = json.loads((REPO_ROOT / "start.isolated-launcher.json").read_text())
        self.assertEqual(declaration["contract"], "life-start-isolated-launcher/v1")
        self.assertEqual(declaration["version"], "1.0.0")
        self.assertEqual(declaration["source"]["content_digest"], isolated.source_content_digest())
        self.assertEqual([lane["id"] for lane in declaration["verification"]["lanes"]], [
            "build", "regression", "behavioral", "security_penetration",
            "recovery", "integration", "acceptance",
        ])
        isolated.validate_verification_declaration(declaration["verification"])
        self.assertTrue(all(lane["status"] == "DECLARED_NOT_VERIFIED" for lane in declaration["verification"]["lanes"]))

    def test_isolation_rejects_canonical_port_forged_nonce_and_canonical_root(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-test-") as temp:
            root = Path(temp)
            with self.assertRaisesRegex(isolated.IsolationError, "noncanonical"):
                isolated.validate_isolation(self._inputs(root / "port", 3333))
            forged = self._inputs(root / "nonce")
            forged["START_INVOCATION_NONCE"] = "short"
            with self.assertRaisesRegex(isolated.IsolationError, "INVOCATION_NONCE"):
                isolated.validate_isolation(forged)
            canonical = self._inputs(root / "canonical")
            canonical["START_TASK_ROOT"] = str(REPO_ROOT)
            with self.assertRaisesRegex(isolated.IsolationError, "canonical storage"):
                isolated.validate_isolation(canonical)

    def test_isolation_rejects_foreign_listener_and_stale_source_declaration(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-test-") as temp:
            root = Path(temp)
            class ValidLookingHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    payload = json.dumps({"status": "ok", "ready": True, "alive": True, "pid": os.getpid()}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

                def log_message(self, *_args):
                    return

            listener = HTTPServer(("127.0.0.1", 0), ValidLookingHandler)
            thread = threading.Thread(target=listener.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaisesRegex(isolated.IsolationError, "already occupied"):
                    isolated.validate_isolation(self._inputs(root / "foreign", listener.server_port))
            finally:
                listener.shutdown()
                listener.server_close()
                thread.join(timeout=2)
            declaration = root / "stale.json"
            stale_declaration = json.loads((REPO_ROOT / "start.isolated-launcher.json").read_text())
            stale_declaration["source"]["content_digest"] = "0" * 64
            declaration.write_text(json.dumps(stale_declaration), encoding="utf-8")
            with patch.object(isolated, "DECLARATION", declaration):
                with self.assertRaisesRegex(isolated.IsolationError, "source digest mismatch"):
                    isolated.validate_isolation(self._inputs(root / "stale"))

    def test_environment_preserves_auth_and_canonical_storage_boundary(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-test-") as temp:
            validated = isolated.validate_isolation(self._inputs(Path(temp)))
            env = isolated.isolated_environment(validated)
            self.assertEqual(env["CLEANHOUSE_ENABLE_AUTH"], "1")
            self.assertEqual(env["CLEANHOUSE_REQUIRE_LOGIN"], "1")
            self.assertEqual(env["CLEANHOUSE_ALLOWED_DOMAINS"], "start.invalid")
            self.assertEqual(env["CLEANHOUSE_PUBLIC_ORIGIN"], f"http://127.0.0.1:{validated['port']}")
            self.assertEqual(env["CLEANHOUSE_START_ISOLATED"], "1")
            self.assertNotIn("CLEANHOUSE_LAUNCHD_OWNED", env)
            self.assertNotIn("VVAULT_SERVICE_TOKEN", env)
            boundary = Path(temp).resolve()
            self.assertTrue(Path(env["HOME"]).resolve().is_relative_to(boundary))
            self.assertTrue(Path(env["CLEANHOUSE_DATA_ROOT"]).resolve().is_relative_to(boundary))

    def test_interpreter_provenance_preserves_virtualenv_and_dependencies(self):
        provenance = isolated.interpreter_provenance()
        self.assertTrue(provenance["exact_invocation_path"])
        self.assertTrue(provenance["dependencies_available"])
        self.assertEqual(provenance["observed"], str(REPO_ROOT / "cleanhouse_env/bin/python3"))
        resolved_base = str((REPO_ROOT / "cleanhouse_env/bin/python3").resolve())
        self.assertFalse(isolated.interpreter_provenance(resolved_base)["exact_invocation_path"])

    def test_bootstrap_home_must_be_task_owned_but_not_treated_as_canonical_home(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-home-") as temp:
            root = Path(temp) / "task"
            valid = self._inputs(root)
            validated = isolated.validate_isolation(valid)
            self.assertEqual(validated["bootstrap_home"], (root / "bootstrap-home").resolve())
            escaped = self._inputs(Path(temp) / "other")
            escaped["START_TASK_ROOT"] = str(root)
            with self.assertRaisesRegex(isolated.IsolationError, "HOME escapes"):
                isolated.validate_isolation(escaped)

    def test_bound_evidence_rejects_wrong_nonce_stale_generation_and_old_observation(self):
        secret = "s" * 64
        now = datetime.now(timezone.utc)
        core = {
            "schema": "cleanhouse.start_isolation_evidence.v1",
            "role": "backend",
            "invocation_nonce": "n" * 32,
            "generation": "g" * 64,
            "source_content_digest": "d" * 64,
            "pid": 100,
            "parent_pid": 99,
            "process_group_id": 99,
            "session_id": 99,
            "boot_id": "boot",
            "observed_at": now.isoformat(),
        }
        encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        evidence = {**core, "binding": {
            "algorithm": "hmac-sha256",
            "digest": hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest(),
        }}
        arguments = dict(secret=secret, nonce="n" * 32, generation="g" * 64, content_digest="d" * 64, now=now)
        self.assertTrue(isolated.verify_bound_evidence(evidence, **arguments))
        self.assertFalse(isolated.verify_bound_evidence(evidence, **{**arguments, "nonce": "x" * 32}))
        self.assertFalse(isolated.verify_bound_evidence(evidence, **{**arguments, "generation": "x" * 64}))
        stale = dict(evidence)
        stale["observed_at"] = (now - timedelta(seconds=60)).isoformat()
        stale_core = {key: item for key, item in stale.items() if key != "binding"}
        stale["binding"] = {"algorithm": "hmac-sha256", "digest": hmac.new(
            secret.encode(), json.dumps(stale_core, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256,
        ).hexdigest()}
        self.assertFalse(isolated.verify_bound_evidence(stale, **arguments))

    def test_live_evidence_uses_booting_during_initial_state_publication_gap(self):
        env = {
            "CLEANHOUSE_START_ISOLATED": "1",
            "START_INVOCATION_NONCE": "n" * 32,
            "START_RUNTIME_GENERATION": "r" * 64,
            "START_SOURCE_CONTENT_DIGEST": "d" * 64,
            "START_SOURCE_REVISION": "e" * 40,
            "FLASK_SECRET_KEY": "s" * 64,
            "CLEANHOUSE_HOST": "127.0.0.1",
            "CLEANHOUSE_PORT": "4444",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(runtime_supervisor, "read_state", return_value={}):
            evidence = runtime_supervisor.isolated_runtime_evidence(
                role="backend", boot_id="boot-id", challenge="c" * 32,
            )
            self.assertEqual(evidence["phase"], "booting")
            self.assertEqual(evidence["state_revision"], 0)
            self.assertTrue(runtime_supervisor._valid_isolated_evidence(
                evidence, role="backend", challenge="c" * 32,
            ))

    def test_ownership_checks_reject_escaped_child_and_stale_generation(self):
        supervisor = {"pid": 10, "process_group_id": 10, "session_id": 10, "run_id": "a", "invocation_nonce": "n", "source_content_digest": "d"}
        backend = {"parent_pid": 10, "process_group_id": 10, "session_id": 10, "run_id": "a", "generation": "backend-a", "invocation_nonce": "n", "source_content_digest": "d"}
        self.assertTrue(all(isolated.ownership_checks(supervisor, backend).values()))
        escaped = {**backend, "process_group_id": 11}
        self.assertFalse(isolated.ownership_checks(supervisor, escaped)["same_process_group"])
        stale = {**backend, "run_id": "old"}
        self.assertFalse(isolated.ownership_checks(supervisor, stale)["generation_matches"])

    def test_lane_contract_rejects_forged_partial_and_unbounded_evidence(self):
        declaration = json.loads((REPO_ROOT / "start.isolated-launcher.json").read_text())
        forged = json.loads(json.dumps(declaration["verification"]))
        forged["lanes"][0]["status"] = "PASS"
        with self.assertRaisesRegex(isolated.IsolationError, "self-assert"):
            isolated.validate_verification_declaration(forged)
        partial = json.loads(json.dumps(declaration["verification"]))
        partial["lanes"].pop()
        with self.assertRaisesRegex(isolated.IsolationError, "invalid verification lanes"):
            isolated.validate_verification_declaration(partial)
        unbounded = json.loads(json.dumps(declaration["verification"]))
        unbounded["lanes"][0]["timeout_seconds"] = 3600
        with self.assertRaisesRegex(isolated.IsolationError, "unbounded"):
            isolated.validate_verification_declaration(unbounded)

    def test_source_mutation_changes_content_digest(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-source-") as temp:
            root = Path(temp)
            for relative in isolated.SOURCE_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((REPO_ROOT / relative).read_bytes())
            before = isolated.source_content_digest(root)
            target = root / isolated.SOURCE_FILES[-1]
            target.write_bytes(target.read_bytes() + b"\n# mutation\n")
            self.assertNotEqual(before, isolated.source_content_digest(root))

    def test_extinction_is_never_claimed_by_live_product_evidence(self):
        declaration = json.loads((REPO_ROOT / "start.isolated-launcher.json").read_text())
        extinction = declaration["ownership"]["extinction_proof"]
        self.assertEqual(extinction["authority"], "start_adapter_only")
        self.assertEqual(extinction["product_claim"], "NOT_VERIFIED_WHILE_LIVE")

    def test_production_probe_rejects_replay_redirect_oversize_and_identity_mismatch(self):
        secret = "s" * 64
        nonce = "n" * 32
        run_id = "r" * 64
        source_digest = "d" * 64
        revision = "e" * 40
        mode = {"value": "ok"}
        expected = {
            "run_id": run_id, "invocation_nonce": nonce, "generation": "boot-new",
            "boot_id": "boot-new", "pid": 123, "parent_pid": 122,
            "process_group_id": 122, "session_id": 122,
            "source_content_digest": source_digest, "source_revision": revision,
            "phase": "bootstrap_ready", "state_revision": 3,
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if mode["value"] == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/health")
                    self.end_headers()
                    return
                if mode["value"] == "oversize":
                    body = b"x" * (runtime_supervisor.START_PROBE_MAX_BYTES + 1)
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                scalar_bodies = {
                    "array_body": [], "null_body": None, "string_body": "ok",
                    "number_body": 7, "bool_body": True,
                }
                if mode["value"] in scalar_bodies:
                    body = json.dumps(scalar_bodies[mode["value"]]).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                challenge = parse_qs(urlparse(self.path).query).get("challenge", [""])[0]
                revision_value = {
                    "negative_revision": -1,
                    "bool_revision": True,
                    "overflow_revision": runtime_supervisor.START_STATE_REVISION_MAX + 1,
                    "regressed_revision": 2,
                }.get(mode["value"], 4)
                phase_value = {
                    "wrong_phase": "invented",
                    "phase_object": {"value": "warm"},
                    "transition": "warming",
                }.get(mode["value"], "warm")
                core = {
                    "schema": runtime_supervisor.START_ISOLATION_SCHEMA,
                    "role": "backend", "invocation_nonce": nonce, "run_id": run_id,
                    "challenge": ("x" * 32 if mode["value"] == "wrong_challenge" else challenge),
                    "generation": ("boot-old" if mode["value"] == "prior_generation" else "boot-new"),
                    "source_content_digest": source_digest, "source_revision": revision,
                    "pid": 123, "parent_pid": 122, "process_group_id": 122, "session_id": 122,
                    "boot_id": ("boot-old" if mode["value"] == "prior_generation" else "boot-new"),
                    "host": "127.0.0.1", "port": self.server.server_port,
                    "phase": phase_value, "state_revision": revision_value,
                    "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                }
                encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
                evidence = {**core, "binding": {"algorithm": "hmac-sha256", "digest": hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()}}
                if mode["value"] == "isolation_array":
                    evidence = []
                elif mode["value"] == "binding_array":
                    evidence["binding"] = []
                payload = {"schema": runtime_supervisor.BACKEND_LIVENESS_SCHEMA, "status": "ok", "alive": True, "isolation": evidence, **core}
                payload["schema"] = runtime_supervisor.BACKEND_LIVENESS_SCHEMA
                payload["pid"] = 999 if mode["value"] == "outer_mismatch" else 123
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {
            "CLEANHOUSE_START_ISOLATED": "1", "START_INVOCATION_NONCE": nonce,
            "START_RUNTIME_GENERATION": run_id, "START_SOURCE_CONTENT_DIGEST": source_digest,
            "START_SOURCE_REVISION": revision, "FLASK_SECRET_KEY": secret,
        }
        try:
            def state_after():
                return {
                    "state_revision": 6 if mode["value"] == "transition" else 4,
                    "startup_phase": "warm",
                    "backend_pid": 123,
                    "backend_boot_id": "boot-new",
                }

            with patch.dict(os.environ, env, clear=False), patch.object(runtime_supervisor, "read_state", side_effect=state_after):
                self.assertEqual(runtime_supervisor._probe_ready("127.0.0.1", server.server_port, expected=expected)["status"], "ok")
                mode["value"] = "transition"
                self.assertEqual(runtime_supervisor._probe_ready("127.0.0.1", server.server_port, expected=expected)["status"], "ok")
                for value in (
                    "wrong_challenge", "prior_generation", "outer_mismatch", "redirect", "oversize",
                    "negative_revision", "bool_revision", "overflow_revision", "regressed_revision", "wrong_phase",
                    "array_body", "null_body", "string_body", "number_body", "bool_body",
                    "isolation_array", "binding_array", "phase_object",
                ):
                    mode["value"] = value
                    self.assertEqual(runtime_supervisor._probe_ready("127.0.0.1", server.server_port, expected=expected)["status"], "failed", value)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_production_classifier_does_not_claim_independent_listener_ownership(self):
        previous = {
            "backend_pid": 22, "supervisor_pid": 11, "backend_boot_id": "boot",
            "start_isolation": {"backend": {}, "supervisor": {}},
        }
        with patch.dict(os.environ, {"CLEANHOUSE_START_ISOLATED": "1"}, clear=False), \
             patch.object(runtime_supervisor, "_pid_alive", return_value=True), \
             patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "failed"}), \
             patch.object(runtime_supervisor, "isolated_runtime_evidence", return_value=None):
            state = runtime_supervisor.classify_state(previous, host="127.0.0.1", port=4444)
        self.assertFalse(state["backend_owned"])
        self.assertEqual(state["listener_ownership_observation"]["status"], "NOT_INDEPENDENTLY_ESTABLISHED")
        self.assertEqual(state["owned_listener_pids"], [])

    def test_classifier_rejects_revision_and_phase_drift_with_valid_hmac(self):
        secret = "s" * 64
        env = {
            "CLEANHOUSE_START_ISOLATED": "1", "START_INVOCATION_NONCE": "n" * 32,
            "START_RUNTIME_GENERATION": "r" * 64, "START_SOURCE_CONTENT_DIGEST": "d" * 64,
            "START_SOURCE_REVISION": "e" * 40, "FLASK_SECRET_KEY": secret,
            "CLEANHOUSE_HOST": "127.0.0.1", "CLEANHOUSE_PORT": "4444",
        }

        def signed(role, pid, parent, boot, phase, revision, challenge="c" * 32):
            core = {
                "schema": runtime_supervisor.START_ISOLATION_SCHEMA, "role": role,
                "invocation_nonce": "n" * 32, "run_id": "r" * 64, "challenge": challenge,
                "generation": boot, "source_content_digest": "d" * 64,
                "source_revision": "e" * 40, "pid": pid, "parent_pid": parent,
                "process_group_id": 11, "session_id": 11, "boot_id": boot,
                "host": "127.0.0.1", "port": 4444, "phase": phase,
                "state_revision": revision,
                "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
            encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
            return {**core, "binding": {"algorithm": "hmac-sha256", "digest": hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()}}

        supervisor = signed("supervisor", 11, 1, "supervisor-boot", "bootstrap_ready", 3, "")
        previous = {
            "backend_pid": 22, "supervisor_pid": 11, "backend_boot_id": "backend-boot",
            "startup_phase": "bootstrap_ready", "state_revision": 3,
            "start_isolation": {
                "backend": signed("backend", 22, 11, "backend-boot", "bootstrap_ready", 3, ""),
                "supervisor": supervisor,
            },
        }
        cases = [(-1, "warming"), (True, "warming"), (runtime_supervisor.START_STATE_REVISION_MAX + 1, "warming"), (2, "warming"), (4, "invented")]
        with patch.dict(os.environ, env, clear=False), patch.object(runtime_supervisor, "_pid_alive", return_value=True), patch.object(runtime_supervisor, "isolated_runtime_evidence", return_value=supervisor):
            valid_backend = signed("backend", 22, 11, "backend-boot", "warming", 4)
            with patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok", "pid": 22, "boot_id": "backend-boot", "challenge": "c" * 32, "isolation": valid_backend}):
                self.assertTrue(runtime_supervisor.classify_state(previous, host="127.0.0.1", port=4444)["backend_owned"])
            for revision, phase in cases:
                invalid = signed("backend", 22, 11, "backend-boot", phase, revision)
                with patch.object(runtime_supervisor, "_probe_ready", return_value={"status": "ok", "pid": 22, "boot_id": "backend-boot", "challenge": "c" * 32, "isolation": invalid}):
                    self.assertFalse(runtime_supervisor.classify_state(previous, host="127.0.0.1", port=4444)["backend_owned"])

    def test_isolated_readiness_requires_challenge_and_returns_503_when_unready(self):
        with patch.dict(os.environ, {"CLEANHOUSE_START_ISOLATED": "1"}, clear=False):
            from flask import Flask
            from backend.api.cleanhouse import bp

            app = Flask(__name__)
            app.register_blueprint(bp)
            with app.test_client() as client:
                missing = client.get("/cleanhouse/status?ready=1")
                self.assertEqual(missing.status_code, 400)
                self.assertEqual(missing.headers.get("Cache-Control"), "no-store")
                with patch("backend.api.cleanhouse._runtime_readiness_payload", return_value={
                    "status": "degraded", "ready": False, "backend": {}, "runtime": {},
                }), patch.object(runtime_supervisor, "isolated_runtime_evidence", return_value=None):
                    unready = client.get("/cleanhouse/status?ready=1&challenge=" + "c" * 32)
                self.assertEqual(unready.status_code, 503)
                self.assertFalse(unready.get_json()["ready"])
                self.assertEqual(unready.headers.get("Cache-Control"), "no-store")

    def test_isolated_transform_has_independent_oracle_denial_and_positive_control(self):
        # Exercise the real application guard, CSRF hook, and task-owned
        # device-session lifecycle without changing canonical auth or consent.
        from backend import auth_context, auth_runtime_config

        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-auth-") as temp:
            task_root = Path(temp)
            nonce = "a" * 32
            auth_config = task_root / "auth.json"
            auth_config.write_text(json.dumps({
                "schema": "cleanhouse.auth.runtime.v1",
                "appId": "cleanhouse-start-test",
                "publicOrigin": "http://localhost",
                "allowedOrigins": ["http://localhost"],
                "providers": {},
            }, sort_keys=True), encoding="utf-8")
            auth_before = auth_config.read_bytes()
            isolated_env = {
                "CLEANHOUSE_START_ISOLATED": "1",
                "START_INVOCATION_NONCE": nonce,
                "CLEANHOUSE_AUTH_DB": str(task_root / "auth.sqlite3"),
                "CLEANHOUSE_AUTH_CONFIG_PATH": str(auth_config),
                "CLEANHOUSE_DATA_ROOT": str(task_root / "data"),
                "CLEANHOUSE_ENABLE_AUTH": "1",
                "CLEANHOUSE_REQUIRE_LOGIN": "1",
                "CLEANHOUSE_PUBLIC_ORIGIN": "http://localhost",
            }
            auth_context.reset_store_cache()
            try:
                with patch.dict(os.environ, isolated_env, clear=False):
                    auth_runtime_config._runtime = None
                    from backend import server
                with server.app.test_client() as full_client:
                    with patch.dict(os.environ, {**isolated_env, "CLEANHOUSE_START_ISOLATED": ""}, clear=False):
                        self.assertEqual(full_client.get(
                            "/cleanhouse/start/transform?challenge=" + nonce
                        ).status_code, 401)
                        self.assertEqual(full_client.post(
                            "/cleanhouse/start/acceptance/session", json={"challenge": nonce}
                        ).status_code, 401)

                    with patch.dict(os.environ, isolated_env, clear=False):
                        self.assertEqual(full_client.get("/cleanhouse/start/transform").status_code, 401)
                        self.assertEqual(full_client.post(
                            "/cleanhouse/start/acceptance/session", json={"challenge": "f" * 32}
                        ).status_code, 401)
                        issued = full_client.post(
                            "/cleanhouse/start/acceptance/session", json={"challenge": nonce}
                        )
                        self.assertEqual(issued.status_code, 200)
                        issued_payload = issued.get_json()
                        csrf = issued_payload["csrf_token"]
                        device_cookie = next(
                            header.split(";", 1)[0].split("=", 1)[1]
                            for header in issued.headers.getlist("Set-Cookie")
                            if header.startswith("cleanhouse_device_session=")
                        )
                        self.assertTrue(device_cookie.startswith("chs_"))
                        identity = full_client.get(
                            "/cleanhouse/start/acceptance/me?challenge=" + nonce
                        )
                        self.assertEqual(identity.status_code, 200)
                        self.assertEqual(identity.get_json()["auth_kind"], "session")
                        denied = full_client.get("/cleanhouse/start/transform")
                        self.assertEqual(denied.status_code, 403)
                        control = full_client.get("/cleanhouse/start/transform?challenge=" + nonce)
                        self.assertEqual(control.status_code, 200)
                        self.assertEqual(
                            control.get_json()["challenge_transform"],
                            hashlib.sha256(nonce.encode()).hexdigest(),
                        )
                        headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
                        integration_nonce = "i" * 32
                        written = full_client.post(
                            "/cleanhouse/start/integration/write",
                            json={"nonce": integration_nonce},
                            headers=headers,
                        )
                        self.assertEqual(written.status_code, 200)
                        read = full_client.get(
                            "/cleanhouse/start/integration/read?nonce=" + integration_nonce
                        )
                        self.assertEqual(read.status_code, 200)
                        self.assertEqual(full_client.get(
                            "/cleanhouse/start/integration/read?nonce=" + integration_nonce
                        ).status_code, 404)
                        self.assertEqual(full_client.get("/overview").status_code, 200)
                        runtime = full_client.get("/cleanhouse/runtime")
                        self.assertEqual(runtime.status_code, 200)
                        self.assertIsInstance(runtime.get_json(), dict)
                        logged_out = full_client.post(
                            "/cleanhouse/start/acceptance/logout",
                            json={"challenge": nonce},
                            headers=headers,
                        )
                        self.assertEqual(logged_out.status_code, 200)
                        self.assertEqual(logged_out.get_json()["status"], "revoked")
                        self.assertIn("cleanhouse_device_session=;", logged_out.headers.get("Set-Cookie", ""))
                        full_client.set_cookie("cleanhouse_device_session", device_cookie, domain="localhost")
                        self.assertEqual(full_client.get(
                            "/cleanhouse/start/acceptance/me?challenge=" + nonce
                        ).status_code, 401)
                        with auth_context.get_store()._connection() as connection:
                            self.assertEqual(connection.execute(
                                "SELECT COUNT(*) FROM consent_receipts"
                            ).fetchone()[0], 0)
                        self.assertEqual(auth_config.read_bytes(), auth_before)
            finally:
                auth_context.reset_store_cache()
                auth_runtime_config._runtime = None

    def test_isolated_integration_crosses_writer_reader_and_consumes_nonce(self):
        from backend.api.cleanhouse import _start_integration_path

        with tempfile.TemporaryDirectory(prefix="cleanhouse-integration-") as temp, patch.dict(
            os.environ,
            {"CLEANHOUSE_START_ISOLATED": "1", "CLEANHOUSE_DATA_ROOT": temp},
            clear=False,
        ):
            self.assertEqual(
                _start_integration_path(),
                Path(temp) / "start-integration" / "single-use.json",
            )

    def test_real_supervisor_server_readiness_and_owned_group_extinction(self):
        with tempfile.TemporaryDirectory(prefix="cleanhouse-start-runtime-") as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            port = int(inputs["START_PORT"])
            env = {"PYTHONPATH": str(REPO_ROOT), **inputs}
            process = subprocess.Popen(
                [str(REPO_ROOT / "cleanhouse_env/bin/python3"), "scripts/start_isolated_runtime.py"],
                cwd=REPO_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                text=True,
            )
            try:
                deadline = time.monotonic() + 12
                ready = None
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        readiness_challenge = "r" * 32
                        with urlopen(f"http://127.0.0.1:{port}/cleanhouse/status?ready=1&challenge={readiness_challenge}", timeout=0.5) as response:
                            ready = json.loads(response.read())
                        if ready.get("ready") is True:
                            break
                    except (OSError, HTTPError, URLError, json.JSONDecodeError):
                        time.sleep(0.1)
                self.assertIsNone(process.poll())
                self.assertIsNotNone(ready)
                self.assertTrue(ready["ready"], json.dumps(ready, sort_keys=True))
                self.assertEqual(ready["listener"]["foreign_pids"], [])
                self.assertEqual(ready["listener"]["pids"], [ready["backend"]["pid"]])
                health_challenge = "h" * 32
                with urlopen(f"http://127.0.0.1:{port}/health?challenge={health_challenge}", timeout=1) as response:
                    health = json.loads(response.read())
                self.assertTrue(health["alive"])
                self.assertEqual(health["pid"], ready["backend"]["pid"])
                isolation_evidence = health["isolation"]
                source_digest = isolated.source_content_digest()
                run_id = hashlib.sha256(f"{'n' * 32}:{source_digest}".encode()).hexdigest()
                self.assertEqual(isolation_evidence["run_id"], run_id)
                self.assertTrue(isolated.verify_bound_evidence(
                    isolation_evidence,
                    secret="s" * 64,
                    nonce="n" * 32,
                    generation=isolation_evidence["generation"],
                    content_digest=source_digest,
                ))
                self.assertEqual(ready["start_isolation"]["backend"]["pid"], health["pid"])
                self.assertTrue(all(ready["start_isolation"]["checks"].values()))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
            with socket.socket() as probe:
                probe.settimeout(0.5)
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)
            state = json.loads((root / "state" / "state.json").read_text())
            self.assertEqual(state["port"], port)
            self.assertFalse((Path.home() / ".cleanhouse" / "runtime" / f"start-{inputs['START_INVOCATION_NONCE']}").exists())


if __name__ == "__main__":
    unittest.main()
