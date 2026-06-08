import unittest
from pathlib import Path
from unittest.mock import patch

from backend import runtime_env


class RuntimeEnvTests(unittest.TestCase):
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
        self.assertEqual(resolved["status"], "supervisor_only")
        self.assertTrue(resolved["supervisor_compatible"])
        self.assertFalse(resolved["backend_compatible"])
        self.assertEqual(resolved["attempts"][0]["failure_reason"], "backend_dependencies_unavailable")


if __name__ == "__main__":
    unittest.main()
