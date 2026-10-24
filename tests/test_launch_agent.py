import os
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import launch_agent, runtime_supervisor


class LaunchAgentTests(unittest.TestCase):
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
        self.assertIn("backend.runtime_supervisor start", launcher)
        self.assertIn("READY_DEADLINE=$((SECONDS + STARTUP_TIMEOUT_SECONDS))", launcher)
        self.assertIn('while ! probe_json "${READY_ENDPOINT}" 2; do', launcher)
        self.assertIn("except (OSError, URLError, json.JSONDecodeError):", launcher)

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

    def test_stage_runtime_moves_code_and_virtualenv_outside_source_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "source"
            for name in ("backend", "corefiles", "frontend", "models"):
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
            self.assertTrue(staged_interpreter.exists())
            self.assertNotIn(str(repo), str(staged_interpreter))
            self.assertFalse((staged_repo / ".env").exists())
            auth_contract = json.loads(
                (staged_repo / "config" / "auth-runtime.json").read_text(encoding="utf-8")
            )
            self.assertEqual(auth_contract["schema"], "cleanhouse.auth-runtime.v1")
            self.assertNotIn("clientSecret", json.dumps(auth_contract))
            staged_helper = staged_repo / "backend" / "keychain-helper"
            self.assertEqual(staged_helper.read_bytes(), helper.read_bytes())
            self.assertEqual(staged_helper.stat().st_mode & 0o777, 0o700)
            self.assertEqual((staged_repo / "config" / "auth-runtime.json").stat().st_mode & 0o777, 0o600)
            staged_wazuh = staged_repo / "bundled" / "wazuh" / "darwin-arm64"
            for name, content in wazuh_artifacts.items():
                self.assertEqual((staged_wazuh / name).read_bytes(), content)

    def test_stage_runtime_reuses_external_interpreter_without_copying_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "source"
            for name in ("backend", "corefiles", "frontend", "models"):
                directory = repo / name
                directory.mkdir(parents=True)
                (directory / "sentinel.py").write_text(name, encoding="utf-8")
            environment = root / "external-venv"
            interpreter = environment / "bin" / "python3"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(Path(sys.executable))
            (environment / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
            helper = root / "installed-keychain-helper"
            helper.write_bytes(b"stable helper executable")
            helper.chmod(0o700)

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
                launch_agent, "_run_launchctl", side_effect=run_launchctl
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
