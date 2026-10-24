import unittest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from backend import runtime_env


class RuntimeEnvTests(unittest.TestCase):
    def test_candidates_prefer_managed_runtime_before_active_and_repo_environments(self):
        with patch.dict(
            os.environ,
            {
                "CLEANHOUSE_PYTHON": "",
                "CLEANHOUSE_RUNTIME_DIR": "/managed/runtime",
            },
            clear=False,
        ), patch.object(runtime_env.sys, "executable", "/active/python3"), patch.object(
            runtime_env.shutil, "which", return_value="/system/python3"
        ):
            candidates = runtime_env._candidate_entries(Path("/repo"))

        self.assertEqual(
            [candidate["source"] for candidate in candidates],
            [
                "managed_runtime",
                "active_sys_executable",
                "repo_cleanhouse_env",
                "repo_dot_venv",
                "system_python3",
            ],
        )
        self.assertEqual(candidates[0]["path"], "/managed/runtime/python/bin/python3")

    def test_resolve_prefers_env_override_when_valid(self):
        candidates = [
            {"source": "env_override", "path": "/override/python3"},
            {"source": "active_sys_executable", "path": "/active/python3"},
        ]

        def probe(path, repo_root=None):
            if path == "/override/python3":
                return {
                    "path": path,
                    "status": "runnable",
                    "runnable": True,
                    "supervisor_compatible": True,
                    "backend_compatible": True,
                    "failure_reason": "",
                    "errors": [],
                }
            raise AssertionError("unexpected fallback probe")

        with patch.object(runtime_env, "_candidate_entries", return_value=candidates), patch.object(
            runtime_env, "probe_interpreter", side_effect=probe
        ):
            resolved = runtime_env.resolve_interpreter(Path("/repo"))
        self.assertEqual(resolved["selected_path"], "/override/python3")
        self.assertEqual(resolved["selected_source"], "env_override")
        self.assertEqual(resolved["status"], "runnable")

    def test_resolve_falls_back_deterministically(self):
        candidates = [
            {"source": "env_override", "path": "/missing/python3"},
            {"source": "active_sys_executable", "path": "/active/python3"},
            {"source": "repo_dot_venv", "path": "/repo/.venv/bin/python3"},
        ]

        def probe(path, repo_root=None):
            if path == "/missing/python3":
                return {
                    "path": path,
                    "status": "unusable",
                    "runnable": False,
                    "supervisor_compatible": False,
                    "backend_compatible": False,
                    "failure_reason": "missing_executable",
                    "errors": [],
                }
            if path == "/active/python3":
                return {
                    "path": path,
                    "status": "supervisor_only",
                    "runnable": False,
                    "supervisor_compatible": True,
                    "backend_compatible": False,
                    "failure_reason": "backend_dependencies_unavailable",
                    "errors": [{"component": "flask", "error": "ModuleNotFoundError: flask"}],
                }
            return {
                "path": path,
                "status": "runnable",
                "runnable": True,
                "supervisor_compatible": True,
                "backend_compatible": True,
                "failure_reason": "",
                "errors": [],
            }

        with patch.object(runtime_env, "_candidate_entries", return_value=candidates), patch.object(
            runtime_env, "probe_interpreter", side_effect=probe
        ):
            resolved = runtime_env.resolve_interpreter(Path("/repo"))
        self.assertEqual(resolved["selected_path"], "/repo/.venv/bin/python3")
        self.assertEqual(resolved["selected_source"], "repo_dot_venv")
        self.assertEqual(resolved["status"], "runnable")
        self.assertEqual(resolved["failures"][0]["reason"], "missing_executable")

    def test_resolve_records_failures_when_dependencies_missing(self):
        candidates = [{"source": "active_sys_executable", "path": "/active/python3"}]
        result = {
            "path": "/active/python3",
            "status": "supervisor_only",
            "runnable": False,
            "supervisor_compatible": True,
            "backend_compatible": False,
            "failure_reason": "backend_dependencies_unavailable",
            "errors": [{"component": "backend.server", "error": "ModuleNotFoundError: flask"}],
        }
        with patch.object(runtime_env, "_candidate_entries", return_value=candidates), patch.object(
            runtime_env, "probe_interpreter", return_value=result
        ):
            resolved = runtime_env.resolve_interpreter(Path("/repo"))
        self.assertEqual(resolved["status"], "unavailable")
        self.assertIsNone(resolved["selected_path"])
        self.assertFalse(resolved["supervisor_compatible"])
        self.assertFalse(resolved["backend_compatible"])
        self.assertEqual(resolved["failures"][0]["reason"], "backend_dependencies_unavailable")
        self.assertEqual(resolved["attempts"][0]["failure_reason"], "backend_dependencies_unavailable")

    def test_probe_interpreter_uses_long_default_timeout(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"errors": [], "runtime_supervisor_importable": true, "flask_importable": true, "backend_server_importable": true}',
            stderr="",
        )
        with patch.dict(os.environ, {"CLEANHOUSE_INTERPRETER_PROBE_TIMEOUT_SECONDS": ""}, clear=False), patch.object(
            runtime_env.Path, "exists", return_value=True
        ), patch.object(runtime_env.os, "access", return_value=True), patch.object(
            runtime_env.subprocess, "run", return_value=result
        ) as run_mock:
            runtime_env.probe_interpreter("/repo/.venv/bin/python3", Path("/repo"))

        self.assertEqual(run_mock.call_args.kwargs["timeout"], runtime_env.DEFAULT_INTERPRETER_PROBE_TIMEOUT_SECONDS)

    def test_probe_interpreter_honors_timeout_override(self):
        result = SimpleNamespace(
            returncode=0,
            stdout='{"errors": [], "runtime_supervisor_importable": true, "flask_importable": true, "backend_server_importable": true}',
            stderr="",
        )
        with patch.dict(os.environ, {"CLEANHOUSE_INTERPRETER_PROBE_TIMEOUT_SECONDS": "7"}, clear=False), patch.object(
            runtime_env.Path, "exists", return_value=True
        ), patch.object(runtime_env.os, "access", return_value=True), patch.object(
            runtime_env.subprocess, "run", return_value=result
        ) as run_mock:
            runtime_env.probe_interpreter("/repo/.venv/bin/python3", Path("/repo"))

        self.assertEqual(run_mock.call_args.kwargs["timeout"], 7.0)

    def test_probe_interpreter_rejects_transitive_backend_import_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            backend.mkdir()
            (backend / "__init__.py").write_text("", encoding="utf-8")
            (backend / "runtime_supervisor.py").write_text("", encoding="utf-8")
            (backend / "server.py").write_text(
                "import cleanhouse_missing_transitive_dependency\n",
                encoding="utf-8",
            )

            result = runtime_env.probe_interpreter(sys.executable, root)

        self.assertFalse(result["backend_compatible"])
        self.assertFalse(result["runnable"])
        self.assertEqual(result["failure_reason"], "backend_dependencies_unavailable")
        self.assertTrue(any(
            error.get("component") == "backend.server"
            and "cleanhouse_missing_transitive_dependency" in error.get("error", "")
            for error in result["errors"]
        ))


if __name__ == "__main__":
    unittest.main()
