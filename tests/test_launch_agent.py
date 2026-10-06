import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import launch_agent, runtime_supervisor


class LaunchAgentTests(unittest.TestCase):
    def test_launcher_prefers_launchd_readable_runtime_python(self):
        launcher = (launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        runtime_candidate = 'if [ -x "${RUNTIME_DIR}/python/bin/python3" ]; then'
        source_candidate = 'if [ -x "${REPO_ROOT}/cleanhouse_env/bin/python3" ]; then'

        self.assertIn(runtime_candidate, launcher)
        self.assertLess(launcher.index(runtime_candidate), launcher.index(source_candidate))

    def test_blocked_preflight_does_not_stop_an_existing_runtime(self):
        launcher = (launch_agent.REPO_ROOT / "scripts" / "cleanhouse-up.sh").read_text(encoding="utf-8")
        blocked_branch = launcher.split('if [ "${PREFLIGHT_STATUS}" -ne 0 ]; then', 1)[1].split(
            "render_startup_warning",
            1,
        )[0]

        self.assertIn("render_blocked_preflight", blocked_branch)
        self.assertNotIn("backend.launch_agent stop", blocked_branch)
        self.assertNotIn("backend.runtime_supervisor stop", blocked_branch)

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

            with patch.object(launch_agent, "_runtime_dir", return_value=root / "runtime"):
                staged = launch_agent.stage_runtime(str(interpreter), repo_root=repo)

            staged_repo = Path(staged["repo_root"])
            staged_interpreter = Path(staged["interpreter"])
            self.assertTrue((staged_repo / "backend" / "sentinel.py").is_file())
            self.assertTrue((staged_repo / "corefiles" / "sentinel.py").is_file())
            self.assertTrue((staged_repo / "frontend" / "sentinel.py").is_file())
            self.assertTrue(staged_interpreter.exists())
            self.assertNotIn(str(repo), str(staged_interpreter))
            self.assertFalse((staged_repo / ".env").exists())
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

            with patch.object(launch_agent, "_runtime_dir", return_value=root / "runtime"):
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

    def test_runtime_observes_launchctl_instead_of_trusting_plist(self):
        result = type("Result", (), {"returncode": 113, "stdout": "", "stderr": "not loaded"})()
        with patch.object(runtime_supervisor.sys, "platform", "darwin"), patch.object(
            runtime_supervisor.subprocess, "run", return_value=result
        ):
            status = runtime_supervisor._launch_agent_observation()

        self.assertTrue(status["required"])
        self.assertFalse(status["loaded"])


if __name__ == "__main__":
    unittest.main()
