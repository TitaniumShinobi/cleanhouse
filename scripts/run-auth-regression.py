#!/usr/bin/env python3
"""Run the isolated product-owned auth regression gate; no live service required."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    missing = [name for name in ("flask", "requests") if importlib.util.find_spec(name) is None]
    node = shutil.which("node")
    if missing or node is None:
        print("AUTH_REGRESSION_PREREQUISITE: install Flask==3.1.3 and requests==2.32.5 "
              "in this Python environment and Node.js 22 on PATH. Missing: "
              + ", ".join(missing + ([] if node else ["node"])), file=sys.stderr)
        return 2
    try:
        version = subprocess.run([node, "--version"], check=True, capture_output=True,
                                 text=True, timeout=10).stdout.strip()
        if int(version.lstrip("v").split(".")[0]) < 20:
            raise ValueError("Node.js 20 or newer is required")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"AUTH_REGRESSION_PREREQUISITE: {error}", file=sys.stderr)
        return 2
    # Do not inherit provider credentials, real HOME, or Python import overrides.
    with tempfile.TemporaryDirectory(prefix="cleanhouse-auth-regression-") as home:
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
        env.update(HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE="1",
                   JWT_SECRET_KEY="synthetic-auth-regression-only")
        print("AUTH regression: isolated backend, logout UI, and API admission tests", flush=True)
        for suite in ("tests.test_auth_api_validation", "tests.test_api_admission"):
            command = [sys.executable, "-B", "-m", "unittest", "-v", suite]
            try:
                result = subprocess.run(command, cwd=root, env=env, timeout=90)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f"AUTH_REGRESSION_EXECUTION_FAILED: {error}", file=sys.stderr)
                return 2
            if result.returncode:
                return result.returncode if result.returncode >= 0 else 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
