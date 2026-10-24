import os
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from backend import launch_agent, runtime_supervisor


class LaunchAgentTests(unittest.TestCase):
    def _index(self, repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    def _canonical_runtime_payload(self, state):
        checks = {
            "runtime_healthy": True, "startup_warm": True, "backend_alive": True,
            "supervisor_alive": True, "heartbeat_fresh": True, "readiness_probe_ok": True,
            "single_owned_listener": True, "listener_matches_backend": True,
            "no_foreign_listener": True, "no_self_deviation_block": True,
            "no_resource_guard_block": True,
        }
        return {
            "ready": True, "bootstrap_ready": True, "runtime_state": "healthy",
            "backend": {"pid": state["backend_pid"], "boot_id": state["backend_boot_id"]},
            "supervisor": {"pid": state["supervisor_pid"], "boot_id": state["boot_id"]},
            "listener": {
                "owned_pids": state["owned_listener_pids"],
                "foreign_pids": state["foreign_listener_pids"],
            },
            "readiness_contract": {
                "schema": "cleanhouse.runtime_operator_readiness.v1", "satisfied": True,
                "required_runtime_state": "healthy", "required_startup_phases": ["warm"],
                "checks": checks, "failed_checks": [],
            },
        }

    def _launch_plist_bytes(self, repo, *, host="127.0.0.1", port=3333, interpreter=None):
        interpreter = interpreter or sys.executable
        return plistlib.dumps({
            "ProgramArguments": [
                str(interpreter), "-m", "backend.runtime_supervisor", "supervise",
                "--host", host, "--port", str(port),
            ],
            "WorkingDirectory": str(Path(repo).resolve()),
        })

    def _run_launcher_readiness_probe(self, payload, status=200, raw_body=None):
        launcher = (launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        function = launcher.split("probe_readiness() {", 1)[1].split("\nPY\n}", 1)[0]
        source = function.split("<<'PY'\n", 1)[1]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return subprocess.run(
                [sys.executable, "-c", source, f"http://127.0.0.1:{server.server_port}/cleanhouse/status?ready=1", "1", "1"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_staged_runtime_contract_rejects_server_supervisor_version_skew(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            backend = app / "backend"
            backend.mkdir()
            (backend / "server.py").write_text(
                "from backend import runtime_supervisor\n"
                "runtime_supervisor._start_isolated_runtime()\n",
                encoding="utf-8",
            )
            (backend / "runtime_supervisor.py").write_text(
                "def supervise():\n    return None\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing _start_isolated_runtime"):
                launch_agent._validate_staged_runtime_contract(app)

            (backend / "runtime_supervisor.py").write_text(
                "def _start_isolated_runtime():\n    return False\n",
                encoding="utf-8",
            )
            launch_agent._validate_staged_runtime_contract(app)

    def test_launcher_readiness_probe_requires_complete_canonical_contract(self):
        checks = {
            "runtime_healthy": True,
            "startup_warm": True,
            "backend_alive": True,
            "supervisor_alive": True,
            "heartbeat_fresh": True,
            "readiness_probe_ok": True,
            "single_owned_listener": True,
            "listener_matches_backend": True,
            "no_foreign_listener": True,
            "no_self_deviation_block": True,
            "no_resource_guard_block": True,
        }
        valid = {
            "status": "ok",
            "ready": True,
            "bootstrap_ready": True,
            "runtime_state": "healthy",
            "reason_codes": ["historical_startup_observation"],
            "readiness_contract": {
                "schema": "cleanhouse.runtime_operator_readiness.v1",
                "satisfied": True,
                "required_runtime_state": "healthy",
                "required_startup_phases": ["warm"],
                "checks": checks,
                "failed_checks": [],
            },
        }
        self.assertEqual(self._run_launcher_readiness_probe(valid).returncode, 0)

        incomplete = {**valid, "readiness_contract": {**valid["readiness_contract"], "checks": {"runtime_healthy": True}}}
        rejected = self._run_launcher_readiness_probe(incomplete)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("Canonical readiness contract was not satisfied", rejected.stderr)

        contradictions = [
            {**valid, "bootstrap_ready": False},
            {**valid, "ready": 1},
            {**valid, "readiness_contract": {**valid["readiness_contract"], "required_runtime_state": "degraded"}},
            {**valid, "readiness_contract": {**valid["readiness_contract"], "required_startup_phases": ["warming", "warm"]}},
            {
                **valid,
                "readiness_contract": {
                    **valid["readiness_contract"],
                    "satisfied": False,
                    "checks": {**checks, "heartbeat_fresh": False},
                    "failed_checks": ["heartbeat_fresh"],
                },
            },
        ]
        for payload in contradictions:
            with self.subTest(payload=payload):
                self.assertNotEqual(self._run_launcher_readiness_probe(payload).returncode, 0)

        for malformed_reasons in (None, "historical", {"code": "historical"}, 7, ["historical", 7]):
            payload = dict(valid)
            if malformed_reasons is None:
                payload.pop("reason_codes")
            else:
                payload["reason_codes"] = malformed_reasons
            with self.subTest(reason_codes=malformed_reasons):
                self.assertNotEqual(self._run_launcher_readiness_probe(payload).returncode, 0)

        self.assertEqual(self._run_launcher_readiness_probe({**valid, "reason_codes": []}).returncode, 0)
        self.assertEqual(self._run_launcher_readiness_probe({**valid, "reason_codes": [""]}).returncode, 0)

    def test_launcher_readiness_probe_bounds_body_and_diagnostics(self):
        oversized = self._run_launcher_readiness_probe({}, raw_body=b"x" * (64 * 1024 + 1))
        self.assertNotEqual(oversized.returncode, 0)
        self.assertIn("response exceeded 65536 bytes", oversized.stderr)

        malformed = self._run_launcher_readiness_probe({}, raw_body=b"{not-json")
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("JSONDecodeError", malformed.stderr)

        secret = "do-not-print-in-full-" + ("s" * 400)
        rejected = self._run_launcher_readiness_probe({
            "status": "degraded",
            "reason_codes": [secret] * 20,
            "readiness_contract": {"failed_checks": [secret] * 20},
        })
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn(secret, rejected.stderr)
        self.assertLess(len(rejected.stderr), 3000)

    def test_launcher_readiness_probe_treats_http_401_as_probe_failure(self):
        rejected = self._run_launcher_readiness_probe({"error": "unauthorized"}, status=401)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("HTTPError", rejected.stderr)

    def test_launcher_prefers_launchd_readable_runtime_python(self):
        launcher = (launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        runtime_candidate = 'if [ -x "${RUNTIME_DIR}/python/bin/python3" ]; then'
        source_candidate = 'if [ -x "${REPO_ROOT}/cleanhouse_env/bin/python3" ]; then'

        self.assertIn(runtime_candidate, launcher)
        self.assertLess(launcher.index(runtime_candidate), launcher.index(source_candidate))

    def test_launcher_dispatches_to_launchagent_on_macos_and_supervisor_elsewhere(self):
        launcher = (launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        macos_branch = launcher.split('if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/launchctl ]; then', 1)[1].split(
            "else",
            1,
        )[0]

        self.assertIn("backend.launch_agent install", macos_branch)
        self.assertIn('--interpreter "${CLEANHOUSE_PYTHON}"', macos_branch)
        self.assertIn('--host "${HOST}"', macos_branch)
        self.assertIn('--port "${PORT}"', macos_branch)
        self.assertIn('--watch-root "${WATCH_DIR}"', macos_branch)
        self.assertIn("backend.runtime_supervisor start", launcher)
        self.assertIn('ACKNOWLEDGE_SELF_DEVIATION=0', launcher)
        self.assertIn('--acknowledge-self-deviation)', launcher)
        self.assertIn('ACKNOWLEDGE_SELF_DEVIATION=1', launcher)
        self.assertIn('export CLEANHOUSE_RUNTIME_DIR="${RUNTIME_DIR}"', launcher)
        self.assertIn('export CLEANHOUSE_DATA_ROOT="${CLEANHOUSE_DATA_ROOT:-${RUNTIME_DIR}/data}"', launcher)
        self.assertIn('STARTUP_TIMEOUT_SECONDS="${CLEANHOUSE_STARTUP_TIMEOUT_SECONDS:-180}"', launcher)
        self.assertIn("READY_DEADLINE=$((SECONDS + STARTUP_TIMEOUT_SECONDS))", launcher)
        self.assertIn('while ! probe_readiness "${READY_ENDPOINT}" 2; do', launcher)
        self.assertIn('contract.get("schema") == "cleanhouse.runtime_operator_readiness.v1"', launcher)
        self.assertIn("and set(checks) == required_checks", launcher)
        self.assertNotIn("INVOCATION_STARTED_RUNTIME", launcher)
        self.assertNotIn("start_response_created_runtime", launcher)
        self.assertNotIn("backend.launch_agent stop", launcher)
        self.assertNotIn("backend.runtime_supervisor stop", launcher)
        self.assertNotIn('RUNTIME_ENDPOINT=', launcher)
        self.assertNotIn('probe_runtime_safe', launcher)
        self.assertIn("except (HTTPError, OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:", launcher)

    def test_launcher_acknowledges_self_deviation_only_with_explicit_switch(self):
        launcher = launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_python = root / "fake-python"
            calls_path = root / "calls.log"
            fake_python.write_text("""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

calls = Path(__file__).with_name("calls.log")
with calls.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:4] == ["-m", "backend.runtime_env", "print-path"]:
    print(__file__)
    raise SystemExit(0)
if sys.argv[1:4] == ["-m", "backend.runtime_supervisor", "preflight"]:
    print(json.dumps({"status": "ready_to_start", "should_start": True}))
    raise SystemExit(0)
raise SystemExit(1)
""", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(root),
                "CLEANHOUSE_RUNTIME_DIR": str(root / "runtime"),
                "CLEANHOUSE_OPEN_BROWSER": "0",
                "CLEANHOUSE_PORT": "45559",
                "CLEANHOUSE_PYTHON": str(fake_python),
                "PYTHONPATH": str(launch_agent.REPO_ROOT),
            }

            subprocess.run(
                ["/bin/bash", str(launcher)],
                cwd=str(launch_agent.REPO_ROOT),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            default_calls = calls_path.read_text(encoding="utf-8").splitlines()
            calls_path.write_text("", encoding="utf-8")
            subprocess.run(
                ["/bin/bash", str(launcher), "--acknowledge-self-deviation"],
                cwd=str(launch_agent.REPO_ROOT),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            explicit_calls = calls_path.read_text(encoding="utf-8").splitlines()

        default_preflight = next(line for line in default_calls if "backend.runtime_supervisor preflight" in line)
        explicit_preflight = next(line for line in explicit_calls if "backend.runtime_supervisor preflight" in line)
        self.assertNotIn("--acknowledge-self-deviation", default_preflight)
        self.assertIn("--acknowledge-self-deviation", explicit_preflight)

    def test_rendered_plist_is_user_owned_keepalive_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            interpreter = Path(tmp) / "python3"
            interpreter.write_text("", encoding="utf-8")
            payload = plistlib.loads(
                launch_agent.render_plist(str(interpreter), host="127.0.0.1", port=3333)
            )

        self.assertEqual(payload["Label"], "org.cleanhouse.runtime")
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["ProcessType"], "Background")
        self.assertEqual(payload["ProgramArguments"][1:4], ["-m", "backend.runtime_supervisor", "supervise"])
        self.assertNotIn("sudo", " ".join(payload["ProgramArguments"]))

    def test_rendered_plist_preserves_virtualenv_interpreter_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "framework-python"
            target.write_text("", encoding="utf-8")
            interpreter = Path(tmp) / "venv" / "bin" / "python3"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(target)

            payload = plistlib.loads(launch_agent.render_plist(str(interpreter)))

        self.assertEqual(payload["ProgramArguments"][0], str(interpreter))
        self.assertNotEqual(payload["ProgramArguments"][0], str(target))

    def test_launch_contract_rejects_non_loopback_and_malformed_prior_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            for payload in (
                self._launch_plist_bytes(repo, host="0.0.0.0"),
                plistlib.dumps({"ProgramArguments": [sys.executable], "WorkingDirectory": str(repo)}),
                self._launch_plist_bytes(repo, port=0),
            ):
                with self.assertRaises(ValueError):
                    launch_agent._launch_contract_from_plist(payload)

    def test_rendered_plist_can_monitor_repository_separate_from_staged_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "python3"
            interpreter.write_text("", encoding="utf-8")
            staged = root / "staged"
            source = root / "accepted-source"
            monitored = root / "operator-repository"
            staged.mkdir()
            source.mkdir()
            monitored.mkdir()

            payload = launch_agent.build_payload(
                str(interpreter),
                repo_root=staged,
                source_repo_root=source,
                watch_root=monitored,
            )

        environment = payload["EnvironmentVariables"]
        self.assertEqual(environment["CLEANHOUSE_SOURCE_REPO_ROOT"], str(source.resolve()))
        self.assertEqual(environment["CLEANHOUSE_WATCH_DIR"], str(monitored.resolve()))
        self.assertNotEqual(environment["CLEANHOUSE_WATCH_DIR"], environment["PYTHONPATH"])

    def test_stage_runtime_moves_code_and_virtualenv_outside_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "source"
            for name in ("backend", "corefiles", "frontend", "models", "access_control"):
                directory = repo / name
                directory.mkdir(parents=True)
                (directory / "sentinel.py").write_text(name, encoding="utf-8")
            (repo / "config").mkdir()
            (repo / "config" / "auth-runtime.json").write_text(
                json.dumps({
                    "schema": "cleanhouse.auth-runtime.v1",
                    "providers": {"google": {"enabled": True}},
                }),
                encoding="utf-8",
            )
            (repo / ".env").write_text("SECRET=value\n", encoding="utf-8")
            (repo / "documents").mkdir()
            (repo / "documents" / "release-evidence.md").write_text("evidence only", encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_release.py").write_text("evidence only", encoding="utf-8")
            environment = repo / "cleanhouse_env"
            interpreter = environment / "bin" / "python3"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(Path(sys.executable))
            (environment / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
            wazuh_source = repo / "bundled" / "wazuh" / "darwin-arm64"
            wazuh_artifacts = {
                "wazuh-agent-4.14.7-1.arm64.pkg": b"package bytes",
                "wazuh-4.14.7-source.tar.gz": b"source archive bytes",
                "manifest.json": b'{"vendored": true}\n',
                "LICENSE": b"license bytes\n",
                "THIRD_PARTY_NOTICES.md": b"notices bytes\n",
                "SOURCE_COMPLIANCE.md": b"compliance bytes\n",
            }
            wazuh_source.mkdir(parents=True)
            for name, content in wazuh_artifacts.items():
                (wazuh_source / name).write_bytes(content)
            wireshark_source = repo / "bundled" / "wireshark" / "darwin-arm64"
            wireshark_artifacts = {
                "bin/tshark": b"tshark executable",
                "bin/dumpcap": b"dumpcap executable",
                "Resources/share/wireshark/COPYING": b"GPL license text\n",
            }
            for name, content in wireshark_artifacts.items():
                path = wireshark_source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for directory in ("Frameworks", "PlugIns/wireshark"):
                (wireshark_source / directory).mkdir(parents=True)
                (wireshark_source / directory / "sentinel").write_text(directory, encoding="utf-8")
            manifest = {
                "license_file": "Resources/share/wireshark/COPYING",
                "components": {
                    "bin/tshark": {"sha256": launch_agent._sha256(wireshark_source / "bin/tshark")},
                    "bin/dumpcap": {"sha256": launch_agent._sha256(wireshark_source / "bin/dumpcap")},
                },
                "runtime_closure": {
                    "bin/tshark": {"sha256": launch_agent._sha256(wireshark_source / "bin/tshark")},
                    "bin/dumpcap": {"sha256": launch_agent._sha256(wireshark_source / "bin/dumpcap")},
                    "Frameworks": {"sha256": launch_agent._bounded_tree_sha256(wireshark_source / "Frameworks")},
                    "Resources/share/wireshark": {"sha256": launch_agent._bounded_tree_sha256(wireshark_source / "Resources/share/wireshark")},
                    "PlugIns/wireshark": {"sha256": launch_agent._bounded_tree_sha256(wireshark_source / "PlugIns/wireshark")},
                },
            }
            manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
            (wireshark_source / "manifest.json").write_bytes(manifest_bytes)
            wireshark_artifacts["manifest.json"] = manifest_bytes
            self._index(repo)
            (repo / "frontend" / "sentinel.py").write_text("dirty-worktree", encoding="utf-8")
            (repo / "frontend" / "untracked.js").write_text("exclude", encoding="utf-8")
            helper = root / "installed-keychain-helper"
            helper.write_bytes(b"stable helper executable")
            helper.chmod(0o700)

            with patch.object(launch_agent, "_runtime_dir", return_value=root / "runtime"), patch.object(
                launch_agent, "_installed_keychain_helper", return_value=helper
            ):
                staged = launch_agent.stage_runtime(str(interpreter), repo_root=repo)

            staged_repo = Path(staged["repo_root"])
            staged_interpreter = Path(staged["interpreter"])
            self.assertTrue((staged_repo / "backend" / "sentinel.py").is_file())
            self.assertTrue((staged_repo / "corefiles" / "sentinel.py").is_file())
            self.assertTrue((staged_repo / "frontend" / "sentinel.py").is_file())
            self.assertEqual((staged_repo / "frontend" / "sentinel.py").read_text(), "frontend")
            self.assertFalse((staged_repo / "frontend" / "untracked.js").exists())
            self.assertTrue(staged_interpreter.exists())
            self.assertNotIn(str(repo), str(staged_interpreter))
            self.assertFalse((staged_repo / ".env").exists())
            self.assertFalse((staged_repo / "documents").exists())
            self.assertFalse((staged_repo / "tests").exists())
            self.assertTrue(all((staged_repo / path).exists() for path in staged["indexed_payload"]))
            auth_contract = json.loads(
                (staged_repo / "config" / "auth-runtime.json").read_text(encoding="utf-8")
            )
            self.assertEqual(auth_contract["schema"], "cleanhouse.auth-runtime.v1")
            self.assertNotIn("clientSecret", json.dumps(auth_contract))
            staged_helper = staged_repo / "backend" / "keychain-helper"
            self.assertEqual(staged_helper.read_bytes(), helper.read_bytes())
            self.assertEqual(staged_helper.stat().st_mode & 0o777, 0o700)
            self.assertEqual((staged_repo / "config" / "auth-runtime.json").stat().st_mode & 0o777, 0o600)
            release_manifest = json.loads(Path(staged["release_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(set(release_manifest["indexed_payload"]), set(staged["indexed_payload"]))
            self.assertEqual(
                release_manifest["indexed_payload"]["config/auth-runtime.json"],
                launch_agent._entry_record(staged_repo, "config/auth-runtime.json"),
            )
            self.assertNotEqual(
                release_manifest["index_records"]["config/auth-runtime.json"],
                release_manifest["indexed_payload"]["config/auth-runtime.json"],
            )
            self.assertEqual(set(release_manifest["derived_payload"]), {"backend/keychain-helper"})
            staged_wazuh = staged_repo / "bundled" / "wazuh" / "darwin-arm64"
            for name, content in wazuh_artifacts.items():
                self.assertEqual((staged_wazuh / name).read_bytes(), content)
            staged_wireshark = staged_repo / "bundled" / "wireshark" / "darwin-arm64"
            for name, content in wireshark_artifacts.items():
                self.assertEqual((staged_wireshark / name).read_bytes(), content)
    def test_stage_runtime_reuses_external_interpreter_without_copying_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "source"
            for name in ("backend", "corefiles", "frontend", "models", "access_control"):
                directory = repo / name
                directory.mkdir(parents=True)
                (directory / "sentinel.py").write_text(name, encoding="utf-8")
            (repo / "config").mkdir()
            (repo / "config/auth-runtime.json").write_text(
                json.dumps({"schema": "cleanhouse.auth-runtime.v1", "providers": {}}),
                encoding="utf-8",
            )
            environment = root / "external-venv"
            interpreter = environment / "bin" / "python3"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(Path(sys.executable))
            (environment / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
            helper = root / "installed-keychain-helper"
            helper.write_bytes(b"stable helper executable")
            helper.chmod(0o700)
            wireshark = repo / "bundled" / "wireshark" / "darwin-arm64"
            for relative in ("bin", "Frameworks", "Resources/share/wireshark", "PlugIns/wireshark"):
                directory = wireshark / relative
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "sentinel").write_text(relative, encoding="utf-8")
            closure = {
                relative: {"sha256": launch_agent._bounded_tree_sha256(wireshark / relative)}
                for relative in ("bin", "Frameworks", "Resources/share/wireshark", "PlugIns/wireshark")
            }
            (wireshark / "manifest.json").write_text(
                json.dumps({"runtime_closure": closure}), encoding="utf-8"
            )
            self._index(repo)

            with patch.object(launch_agent, "_runtime_dir", return_value=root / "runtime"), patch.object(
                launch_agent, "_installed_keychain_helper", return_value=helper
            ):
                staged = launch_agent.stage_runtime(str(interpreter), repo_root=repo)

            self.assertEqual(Path(staged["interpreter"]), interpreter)

    def test_status_does_not_treat_installed_plist_as_loaded(self):
        result = type("Result", (), {"returncode": 113, "stdout": "", "stderr": "not loaded"})()
        with patch.object(launch_agent, "plist_path", return_value=Path("/missing/agent.plist")), patch.object(
            launch_agent, "_run_launchctl", return_value=result
        ):
            status = launch_agent.status()

        self.assertFalse(status["loaded"])
        self.assertEqual(status["state"], "unavailable")

    def test_stop_unloads_agent_and_stops_verified_owned_runtime(self):
        completed = Mock(returncode=0, stdout="", stderr="")
        runtime = {
            "runtime_state": "unhealthy",
            "backend_alive": False,
            "supervisor_alive": False,
        }
        with patch.object(launch_agent, "_run_launchctl", return_value=completed) as launchctl, patch.object(
            launch_agent, "status", return_value={"loaded": False, "installed": True, "state": "installed"}
        ), patch.object(
            runtime_supervisor, "stop_runtime", return_value=runtime
        ) as stop_runtime:
            result = launch_agent.stop(host="127.0.0.1", port=3333)

        launchctl.assert_called_once_with(
            ["bootout", launch_agent.gui_domain(), str(launch_agent.plist_path())]
        )
        stop_runtime.assert_called_once_with("127.0.0.1", 3333)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["runtime"], runtime)

    def test_reinstall_loaded_unchanged_agent_kickstarts_without_bootout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "org.cleanhouse.runtime.plist"
            payload = b"stable launch agent definition"
            path.write_bytes(payload)
            staged = {
                "root": str(root / "runtime" / "current"),
                "repo_root": str(root / "runtime" / "current" / "app"),
                "interpreter": str(root / "runtime" / "current" / "python" / "bin" / "python3"),
                "source_repo_root": str(root / "source"),
                "previous": str(root / "runtime" / "previous"),
            }
            completed = Mock(returncode=0, stdout="", stderr="")
            calls = []

            def run_launchctl(args):
                calls.append(args)
                return completed

            with patch.object(launch_agent, "plist_path", return_value=path), patch.object(
                launch_agent, "_runtime_dir", return_value=root / "runtime"
            ), patch.object(
                launch_agent, "status", return_value={"loaded": True, "installed": True, "state": "loaded"}
            ), patch.object(
                launch_agent, "stage_runtime", return_value=staged
            ), patch.object(
                launch_agent, "render_plist", return_value=payload
            ), patch.object(
                launch_agent, "_bind_release_plists"
            ), patch.object(
                launch_agent, "_run_launchctl", side_effect=run_launchctl
            ), patch.object(
                launch_agent, "_verify_activation", return_value=True
            ), patch.object(
                launch_agent, "_finalize_staged_runtime"
            ) as finalize, patch.object(
                launch_agent, "_rollback_staged_runtime"
            ) as rollback:
                result = launch_agent.install("/runtime/python3")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, [["kickstart", "-k", f"{launch_agent.gui_domain()}/{launch_agent.LABEL}"]])
        finalize.assert_called_once_with(staged)
        rollback.assert_not_called()

    def test_failed_post_activation_verification_restores_previous_release(self):
        staged = {
            "root": "/runtime/current", "previous": "/runtime/previous",
            "interpreter": "/runtime/python", "repo_root": "/runtime/current/app",
            "source_repo_root": "/source",
        }
        completed = Mock(returncode=0, stdout="", stderr="")
        with patch.object(launch_agent, "plist_path", return_value=Path("/tmp/agent.plist")), patch.object(
            Path, "is_file", return_value=True
        ), patch.object(Path, "read_bytes", return_value=b"same"), patch.object(
            launch_agent, "status", return_value={"loaded": True}
        ), patch.object(launch_agent, "stage_runtime", return_value=staged), patch.object(
            launch_agent, "render_plist", return_value=b"same"
        ), patch.object(launch_agent, "_bind_release_plists"
        ), patch.object(launch_agent, "_run_launchctl", return_value=completed), patch.object(
            launch_agent, "_verify_activation", return_value=False
        ), patch.object(runtime_supervisor, "read_state", return_value={}
        ), patch.object(launch_agent, "_rollback_active_release") as rollback:
            result = launch_agent.install("/runtime/python", host="127.0.0.1", port=3333)
        self.assertEqual(result["status"], "error")
        rollback.assert_called_once_with(staged, launch_agent.gui_domain(), {}, host="127.0.0.1", port=3333)

    def test_failed_kickstart_uses_verified_rollback(self):
        staged = {
            "root": "/runtime/current", "previous": "/runtime/previous",
            "interpreter": "/runtime/python", "repo_root": "/runtime/current/app",
            "source_repo_root": "/source",
        }
        failed = Mock(returncode=5, stdout="", stderr="kickstart failed")
        with patch.object(launch_agent, "plist_path", return_value=Path("/tmp/agent.plist")), patch.object(
            Path, "is_file", return_value=True
        ), patch.object(Path, "read_bytes", return_value=b"same"), patch.object(
            launch_agent, "status", return_value={"loaded": True}
        ), patch.object(launch_agent, "stage_runtime", return_value=staged), patch.object(
            launch_agent, "render_plist", return_value=b"same"
        ), patch.object(launch_agent, "_bind_release_plists"
        ), patch.object(launch_agent, "_run_launchctl", return_value=failed), patch.object(
            runtime_supervisor, "read_state", return_value={}
        ), patch.object(launch_agent, "_rollback_active_release", return_value=False) as rollback:
            result = launch_agent.install("/runtime/python", host="127.0.0.1", port=3333)
        self.assertFalse(result["rollback_verified"])
        self.assertIn("rollback verification failed", result["message"])
        rollback.assert_called_once_with(staged, launch_agent.gui_domain(), {}, host="127.0.0.1", port=3333)

    def test_real_wireshark_manifest_closes_bounded_runtime_artifacts(self):
        root = launch_agent.REPO_ROOT / "bundled" / "wireshark" / "darwin-arm64"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["runtime_closure"]), {
            "bin/tshark", "bin/dumpcap", "Frameworks",
            "Resources/share/wireshark", "PlugIns/wireshark",
        })
        launch_agent._validate_wireshark_runtime(launch_agent.REPO_ROOT)
        closure = launch_agent._wireshark_git_closure(launch_agent.REPO_ROOT)
        self.assertEqual(len(closure), 636)
        self.assertEqual(len(set(closure)), 636)
        self.assertEqual(sum(os.lstat(launch_agent.REPO_ROOT / path).st_size for path in closure), 395998460)
        self.assertTrue((root / manifest["license_file"]).is_file())
        self.assertIn("bundled/wireshark/darwin-arm64", launch_agent.RUNTIME_INDEX_PREFIXES)

    def test_wireshark_manifest_rejects_escape_and_missing_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            root = app / launch_agent.WIRESHARK_RUNTIME_ROOT
            root.mkdir(parents=True)
            manifest = root / "manifest.json"
            for closure in ({"../escape": {"sha256": "0" * 64}}, {"manifest.json": {}}):
                manifest.write_text(json.dumps({"runtime_closure": closure}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    launch_agent._validate_wireshark_runtime(app)

    def test_directory_symlink_is_hashed_and_cannot_escape_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            target = app / "Frameworks/Real.framework"
            target.mkdir(parents=True)
            (target / "binary").write_text("framework", encoding="utf-8")
            link = app / "Frameworks/Current.framework"
            link.symlink_to(target.name)
            record = launch_agent._entry_record(app, "Frameworks/Current.framework")
            self.assertEqual(record["kind"], "symlink-directory")
            (target / "binary").write_text("changed", encoding="utf-8")
            self.assertNotEqual(record, launch_agent._entry_record(app, "Frameworks/Current.framework"))
            outside = Path(tmp) / "outside"
            outside.mkdir()
            escaping = app / "Frameworks/Escape.framework"
            escaping.symlink_to(outside)
            with self.assertRaises(ValueError):
                launch_agent._entry_record(app, "Frameworks/Escape.framework")

    def test_legacy_prior_snapshot_uses_its_own_bounded_path_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "current"
            app = current / "app"
            (app / "backend").mkdir(parents=True)
            (app / "backend/legacy.py").write_text("legacy", encoding="utf-8")
            (app / "frontend").mkdir()
            (app / "frontend/prior.js").write_text("prior", encoding="utf-8")
            (app / "backend/keychain-helper").write_text("derived", encoding="utf-8")
            manifest, paths = launch_agent._snapshot_prior_release(current)
        self.assertEqual(set(paths), {"backend/legacy.py", "frontend/prior.js"})
        self.assertEqual(set(manifest["indexed_payload"]), set(paths))
        self.assertEqual(manifest["origin"], "retained-prior-legacy-snapshot")
        self.assertIsNone(manifest["index_records"])

    def test_inactive_and_first_install_rollbacks_restore_definition_without_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.plist"
            path.write_bytes(b"replacement")
            staged = {"root": str(Path(tmp) / "current"), "previous": ""}
            with patch.object(launch_agent, "_rollback_staged_runtime") as rollback, patch.object(
                launch_agent, "status", return_value={"loaded": False}
            ), patch.object(launch_agent, "_run_launchctl") as launchctl, patch.object(
                runtime_supervisor, "read_state", return_value={}
            ):
                self.assertTrue(launch_agent._rollback_active_release(
                    staged, "gui/501", {}, path=path, prior_payload=b"installed-unloaded",
                    definition_changed=False, prior_loaded=False,
                ))
                self.assertEqual(path.read_bytes(), b"installed-unloaded")
                self.assertTrue(launch_agent._rollback_active_release(
                    staged, "gui/501", {}, path=path, prior_payload=None,
                    definition_changed=False, prior_loaded=False,
                ))
                self.assertFalse(path.exists())
            self.assertEqual(rollback.call_count, 2)
            launchctl.assert_not_called()

    def test_real_wireshark_exact_manifest_candidate_runs_tshark_version(self):
        source = launch_agent.REPO_ROOT / "bundled" / "wireshark" / "darwin-arm64"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp) / "app"
            candidate = app_root / launch_agent.WIRESHARK_RUNTIME_ROOT
            candidate.mkdir(parents=True)
            shutil.copy2(source / "manifest.json", candidate / "manifest.json")
            for relative in manifest["runtime_closure"]:
                origin = source / relative
                destination = candidate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if origin.is_dir():
                    subprocess.run(["/bin/cp", "-cR", str(origin), str(destination)], check=True)
                else:
                    shutil.copy2(origin, destination)
            launch_agent._validate_wireshark_runtime(app_root)
            environment = {
                **os.environ,
                "DYLD_LIBRARY_PATH": str(candidate / "Frameworks"),
                "WIRESHARK_DATA_DIR": str(candidate / "Resources/share/wireshark"),
                "WIRESHARK_PLUGIN_DIR": str(candidate / "PlugIns/wireshark"),
            }
            result = subprocess.run(
                [str(candidate / "bin/tshark"), "--version"], env=environment,
                text=True, capture_output=True, timeout=20, check=False,
            )
            dumpcap = subprocess.run(
                [str(candidate / "bin/dumpcap"), "--version"], env=environment,
                text=True, capture_output=True, timeout=20, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TShark (Wireshark) 4.6.6", result.stdout)
        self.assertEqual(dumpcap.returncode, 0, dumpcap.stderr)
        self.assertIn("Dumpcap (Wireshark) 4.6.6", dumpcap.stdout)

    def test_rollback_reports_verified_success_and_failure(self):
        completed = Mock(returncode=0)
        with patch.object(launch_agent, "_rollback_staged_runtime"), patch.object(
            launch_agent, "_run_launchctl", return_value=completed
        ), patch.object(launch_agent, "_verify_rollback", side_effect=[True, False]):
            self.assertTrue(launch_agent._rollback_active_release({}, "gui/501", {}))
            self.assertFalse(launch_agent._rollback_active_release({}, "gui/501", {}))

    def test_activation_verifier_consumes_flat_runtime_state_and_rejects_drift(self):
        class Response:
            status = 200

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(self.body).encode("utf-8")

        prior = {
            "supervisor_pid": 11,
            "boot_id": "old-supervisor",
            "backend_pid": 12,
            "backend_boot_id": "old-backend",
        }
        current = {
            "supervisor_pid": 21,
            "boot_id": "new-supervisor",
            "backend_pid": 22,
            "backend_boot_id": "new-backend",
            "owned_listener_pids": [22],
            "foreign_listener_pids": [],
            "supervisor_alive": True,
            "backend_alive": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "release"
            app = release / "app"
            payload = app / "backend" / "server.py"
            payload.parent.mkdir(parents=True)
            payload.write_text("accepted-index-bytes", encoding="utf-8")
            (app / "backend/keychain-helper").write_text("helper", encoding="utf-8")
            indexed_payload = ("backend/server.py",)
            launch_agent._write_release_manifest(
                release, indexed_payload,
                {"backend/server.py": launch_agent._entry_record(app, "backend/server.py")},
                origin="test",
            )
            plist = Path(tmp) / "agent.plist"
            plist_bytes = self._launch_plist_bytes(app)
            plist.write_bytes(plist_bytes)
            staged = {
                "root": str(release),
                "repo_root": str(app.resolve()),
                "indexed_payload": indexed_payload,
            }
            launch_agent._bind_release_plists(staged, plist_bytes, None)
            processes = {
                "launchd": {
                    "loaded": True, "pid": 21, "program": sys.executable,
                    "working_directory": str(app.resolve()),
                    "arguments": [sys.executable, "-m", "backend.runtime_supervisor", "supervise", "--host", "127.0.0.1", "--port", "3333"],
                },
                "supervisor": {"pid": 21, "ppid": 1, "command": "python -m backend.runtime_supervisor", "working_directory": str(app.resolve())},
                "backend": {"pid": 22, "ppid": 21, "command": f"python {app.resolve() / 'backend/server.py'}", "working_directory": str(app.resolve())},
            }
            staged["interpreter"] = sys.executable
            self.assertTrue(launch_agent._canonical_readiness_matches(self._canonical_runtime_payload(current), current))
            self.assertTrue(launch_agent._verify_release_manifest(
                release, indexed_payload, plist_bytes, staged["release_manifest_sha256"]
            ))
            with patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                launch_agent.urllib.request, "urlopen", return_value=Response(self._canonical_runtime_payload(current))
            ), patch.object(
                runtime_supervisor, "read_state", return_value=current
            ), patch.object(launch_agent, "_launchd_process_observation", return_value=processes["launchd"]), patch.object(
                launch_agent, "_process_observation", side_effect=lambda pid: processes["supervisor"] if pid == 21 else processes["backend"]
            ):
                self.assertTrue(launch_agent._processes_match_release(staged, current, staged["release_launch_contract"]))
                self.assertTrue(launch_agent._verify_activation(staged, prior, "127.0.0.1", 3333, 0.05))

            adversarial_processes = [
                {**processes["launchd"], "pid": 999},
                {**processes["launchd"], "working_directory": str(Path(tmp) / "wrong")},
                {**processes["launchd"], "program": "/usr/bin/false"},
            ]
            for launchd_state in adversarial_processes:
                with self.subTest(launchd=launchd_state), patch.object(
                    launch_agent, "plist_path", return_value=plist
                ), patch.object(
                    launch_agent.urllib.request, "urlopen", return_value=Response(self._canonical_runtime_payload(current))
                ), patch.object(runtime_supervisor, "read_state", return_value=current), patch.object(
                    launch_agent, "_launchd_process_observation", return_value=launchd_state
                ), patch.object(
                    launch_agent, "_process_observation", side_effect=lambda pid: processes["supervisor"] if pid == 21 else processes["backend"]
                ), patch.object(launch_agent.time, "sleep", return_value=None):
                    self.assertFalse(launch_agent._verify_activation(staged, prior, "127.0.0.1", 3333, 0.001))

            wrong_backend = {**processes["backend"], "ppid": 999}
            with patch.object(launch_agent, "_launchd_process_observation", return_value=processes["launchd"]), patch.object(
                launch_agent, "_process_observation", side_effect=lambda pid: processes["supervisor"] if pid == 21 else wrong_backend
            ):
                self.assertFalse(launch_agent._processes_match_release(staged, current, staged["release_launch_contract"]))

            (app / "backend/injected.py").write_text("injected", encoding="utf-8")
            self.assertFalse(launch_agent._verify_release_manifest(
                release, indexed_payload, plist_bytes, staged["release_manifest_sha256"]
            ))
            (app / "backend/injected.py").unlink()

            endpoint_mismatch = self._canonical_runtime_payload(current)
            endpoint_mismatch["backend"]["pid"] = 999
            self.assertFalse(launch_agent._canonical_readiness_matches(endpoint_mismatch, current))
            endpoint_mismatch = self._canonical_runtime_payload(current)
            endpoint_mismatch["supervisor"]["boot_id"] = "wrong-boot"
            self.assertFalse(launch_agent._canonical_readiness_matches(endpoint_mismatch, current))

            rejected = [
                {**current, "supervisor_pid": 11, "boot_id": "old-supervisor"},
                {**current, "owned_listener_pids": []},
                {**current, "foreign_listener_pids": [99]},
                {**current, "backend_boot_id": "old-backend"},
            ]
            for state in rejected:
                with self.subTest(state=state), patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                    launch_agent.urllib.request, "urlopen", return_value=Response(self._canonical_runtime_payload(state))
                ), patch.object(runtime_supervisor, "read_state", return_value=state), patch.object(
                    launch_agent.time, "sleep", return_value=None
                ), patch.object(launch_agent, "_launchd_process_observation", return_value=processes["launchd"]), patch.object(
                    launch_agent, "_process_observation", side_effect=lambda pid: processes["supervisor"] if pid == 21 else processes["backend"]
                ):
                    self.assertFalse(launch_agent._verify_activation(staged, prior, "127.0.0.1", 3333, 0.001))

    def test_rollback_verifier_consumes_flat_runtime_state_and_rejects_drift(self):
        failed = {
            "supervisor_pid": 21,
            "boot_id": "failed-supervisor",
            "backend_pid": 22,
            "backend_boot_id": "failed-backend",
        }
        restored = {
            "supervisor_pid": 31,
            "boot_id": "restored-supervisor",
            "backend_pid": 32,
            "backend_boot_id": "restored-backend",
            "owned_listener_pids": [32],
            "foreign_listener_pids": [],
            "supervisor_alive": True,
            "backend_alive": True,
            "heartbeat_fresh": True,
            "runtime_state": "healthy",
        }
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "current"
            app = current / "app"
            payload = app / "backend/server.py"
            payload.parent.mkdir(parents=True)
            payload.write_text("prior-release", encoding="utf-8")
            root_stat = current.stat()
            staged = {
                "root": str(current),
                "repo_root": str(app.resolve()),
                "interpreter": sys.executable,
                "prior_root_identity": [root_stat.st_dev, root_stat.st_ino],
                "prior_indexed_payload": ("backend/server.py",),
            }
            (app / "backend/keychain-helper").write_text("helper", encoding="utf-8")
            launch_agent._write_release_manifest(
                current, staged["prior_indexed_payload"], None, origin="retained-prior-test"
            )
            plist = Path(tmp) / "agent.plist"
            prior_interpreter = Path(tmp) / "prior-python"
            prior_interpreter.symlink_to(sys.executable)
            plist_bytes = self._launch_plist_bytes(
                app, host="127.0.0.1", port=4444, interpreter=prior_interpreter
            )
            plist.write_bytes(plist_bytes)
            manifest_path = current / "release-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["plist_sha256"] = hashlib.sha256(plist_bytes).hexdigest()
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            staged["prior_release_manifest_sha256"] = launch_agent._sha256(manifest_path)
            staged["prior_launch_contract"] = launch_agent._launch_contract_from_plist(plist_bytes)
            prior_processes = {
                "launchd": {
                    "loaded": True, "pid": 31, "program": str(prior_interpreter),
                    "working_directory": str(app.resolve()),
                    "arguments": staged["prior_launch_contract"]["arguments"],
                },
                "supervisor": {"pid": 31, "ppid": 1, "command": "python -m backend.runtime_supervisor", "working_directory": str(app.resolve())},
                "backend": {"pid": 32, "ppid": 31, "command": f"python {app.resolve() / 'backend/server.py'}", "working_directory": str(app.resolve())},
            }
            with patch.object(launch_agent, "_launchd_process_observation", return_value=prior_processes["launchd"]), patch.object(
                launch_agent, "_process_observation", side_effect=lambda pid: prior_processes["supervisor"] if pid == 31 else prior_processes["backend"]
            ):
                self.assertTrue(launch_agent._processes_match_release(staged, restored, staged["prior_launch_contract"]))
            wrong_launchd = {**prior_processes["launchd"], "arguments": [str(prior_interpreter), "wrong"]}
            with patch.object(launch_agent, "_launchd_process_observation", return_value=wrong_launchd), patch.object(
                launch_agent, "_process_observation", side_effect=lambda pid: prior_processes["supervisor"] if pid == 31 else prior_processes["backend"]
            ):
                self.assertFalse(launch_agent._processes_match_release(staged, restored, staged["prior_launch_contract"]))
            process_check = patch.object(launch_agent, "_processes_match_release", return_value=True)
            readiness = Mock(return_value=(200, self._canonical_runtime_payload(restored)))
            with patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                runtime_supervisor, "read_state", return_value=restored
            ), patch.object(
                launch_agent, "_readiness_payload", readiness
            ), process_check:
                self.assertTrue(launch_agent._verify_rollback(staged, failed, timeout_seconds=0.05))
            readiness.assert_called_with("127.0.0.1", 4444)

            not_ready = self._canonical_runtime_payload(restored)
            not_ready["readiness_contract"]["checks"]["startup_warm"] = False
            not_ready["readiness_contract"]["satisfied"] = False
            not_ready["readiness_contract"]["failed_checks"] = ["startup_warm"]
            with patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                runtime_supervisor, "read_state", return_value=restored
            ), patch.object(launch_agent, "_readiness_payload", return_value=(200, not_ready)), patch.object(
                launch_agent, "_processes_match_release", return_value=True
            ), patch.object(launch_agent.time, "sleep", return_value=None):
                self.assertFalse(launch_agent._verify_rollback(staged, failed, timeout_seconds=0.001))

            rejected = [
                {**restored, "backend_pid": 22, "backend_boot_id": "failed-backend", "owned_listener_pids": [22]},
                {**restored, "backend_boot_id": "failed-backend"},
                {**restored, "foreign_listener_pids": [99]},
                {**restored, "heartbeat_fresh": False},
                {**restored, "runtime_state": "unhealthy"},
            ]
            for state in rejected:
                with self.subTest(state=state), patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                    runtime_supervisor, "read_state", return_value=state
                ), patch.object(launch_agent.time, "sleep", return_value=None):
                    with patch.object(
                        launch_agent, "_readiness_payload", return_value=(200, self._canonical_runtime_payload(state))
                    ), patch.object(launch_agent, "_processes_match_release", return_value=True):
                        self.assertFalse(launch_agent._verify_rollback(staged, failed, timeout_seconds=0.001))

            payload.write_text("wrong-generation", encoding="utf-8")
            with patch.object(launch_agent, "plist_path", return_value=plist), patch.object(
                runtime_supervisor, "read_state", return_value=restored
            ), patch.object(
                launch_agent.time, "sleep", return_value=None
            ), patch.object(
                launch_agent, "_readiness_payload", return_value=(200, self._canonical_runtime_payload(restored))
            ), patch.object(launch_agent, "_processes_match_release", return_value=True):
                self.assertFalse(launch_agent._verify_rollback(staged, failed, timeout_seconds=0.001))

    def test_changed_definition_rollback_restores_plist_kickstarts_and_verifies(self):
        completed = Mock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "org.cleanhouse.runtime.plist"
            path.write_bytes(b"replacement")
            with patch.object(launch_agent, "_rollback_staged_runtime") as rollback, patch.object(
                launch_agent, "_run_launchctl", return_value=completed
            ) as launchctl, patch.object(launch_agent, "_verify_rollback", return_value=True) as verify:
                restored = launch_agent._rollback_active_release(
                    {}, "gui/501", {"boot_id": "prior"}, path=path,
                    prior_payload=b"prior-definition", definition_changed=True,
                )
            self.assertEqual(path.read_bytes(), b"prior-definition")
        self.assertTrue(restored)
        rollback.assert_called_once_with({})
        self.assertEqual(launchctl.call_args_list, [
            unittest.mock.call(["bootout", "gui/501", str(path)]),
            unittest.mock.call(["bootstrap", "gui/501", str(path)]),
            unittest.mock.call(["kickstart", "-k", f"gui/501/{launch_agent.LABEL}"]),
        ])
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[0], {})

    def test_reinstall_loaded_unchanged_agent_can_stage_without_restarting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "org.cleanhouse.runtime.plist"
            payload = b"stable launch agent definition"
            path.write_bytes(payload)
            staged = {
                "root": str(root / "runtime" / "current"),
                "repo_root": str(root / "runtime" / "current" / "app"),
                "interpreter": str(root / "runtime" / "current" / "python" / "bin" / "python3"),
                "source_repo_root": str(root / "source"),
                "previous": str(root / "runtime" / "previous"),
            }

            with patch.object(launch_agent, "plist_path", return_value=path), patch.object(
                launch_agent, "_runtime_dir", return_value=root / "runtime"
            ), patch.object(
                launch_agent, "status", return_value={"loaded": True, "installed": True, "state": "loaded"}
            ), patch.object(
                launch_agent, "stage_runtime", return_value=staged
            ), patch.object(
                launch_agent, "render_plist", return_value=payload
            ), patch.object(
                launch_agent, "_bind_release_plists"
            ), patch.object(
                launch_agent, "_run_launchctl"
            ) as launchctl, patch.object(
                launch_agent, "_finalize_staged_runtime"
            ) as finalize:
                result = launch_agent.install("/runtime/python3", start=False)

        self.assertEqual(result["status"], "ok")
        launchctl.assert_not_called()
        finalize.assert_called_once_with(staged)

    def test_runtime_observes_launchctl_instead_of_trusting_plist(self):
        result = type("Result", (), {"returncode": 113, "stdout": "", "stderr": "not loaded"})()
        with patch.object(runtime_supervisor.sys, "platform", "darwin"), patch.object(
            runtime_supervisor.subprocess, "run", return_value=result
        ):
            status = runtime_supervisor._launch_agent_observation()

        self.assertTrue(status["required"])
        self.assertFalse(status["loaded"])

    def test_plist_points_to_staged_helper_without_secret_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "python3"
            interpreter.write_text("", encoding="utf-8")
            repo = root / "app"
            repo.mkdir()
            payload = launch_agent.build_payload(str(interpreter), repo_root=repo)
        environment = payload["EnvironmentVariables"]
        self.assertEqual(
            environment["CLEANHOUSE_KEYCHAIN_HELPER_PATH"],
            str(repo.resolve() / "backend" / "keychain-helper"),
        )
        serialized = plistlib.dumps(payload).decode("utf-8")
        self.assertNotIn("CLIENT_SECRET", serialized)
        self.assertNotIn("client-secret-v2", serialized)


if __name__ == "__main__":
    unittest.main()
