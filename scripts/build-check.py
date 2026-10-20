#!/usr/bin/env python3
"""Shared source gate: isolated tests, no server or auth wizard dependency."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SYNTAX_FILES = ('backend/server.py', 'backend/api/auth.py', 'backend/api/cleanhouse.py')


def main():
    node = shutil.which('node')
    if not node:
        print('BUILD_CHECK_PREREQUISITE: Node.js 20+ required', file=sys.stderr)
        return 2
    try:
        version = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10, check=True,
                                 env={k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR') if k in os.environ})
        if int(version.stdout.strip().lstrip('v').split('.')[0]) < 20:
            raise ValueError('Node.js 20+ required')
        for name in SYNTAX_FILES:
            ast.parse((ROOT / name).read_text(), filename=name)
        with tempfile.TemporaryDirectory(prefix='cleanhouse-build-check-') as home:
            env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR') if k in os.environ}
            env.update(HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE='1')
            wrapper_env = dict(env, CLEANHOUSE_TEST_PYTHON=sys.executable)
            for key in ('PRODUCT_TEST_WITNESS_FILE', 'PRODUCT_TEST_WITNESS_NONCE'):
                if key in os.environ:
                    wrapper_env[key] = os.environ[key]
            commands = [
                ([node, 'test/auth-behavior.mjs'], wrapper_env, 240),
                ([sys.executable, '-B', 'scripts/verify-product-surfaces.py'], env, 60),
                ([sys.executable, '-B', '-m', 'unittest', '-v',
                  'tests.test_product_surface_baseline', 'tests.test_product_surface_dependencies',
                  'tests.test_build_check'], env, 120),
            ]
            for argv, child_env, timeout in commands:
                print('BUILD CHECK:', ' '.join(argv), flush=True)
                result = subprocess.run(argv, cwd=ROOT, env=child_env, timeout=timeout)
                if result.returncode:
                    return result.returncode if result.returncode > 0 else 1
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        print(f'BUILD_CHECK_FAILED: {type(error).__name__}', file=sys.stderr)
        return 2
    print('BUILD_CHECK_PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
