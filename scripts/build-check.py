#!/usr/bin/env python3
"""Shared source build gate; no server, credentials, or AUTH wizard required."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix='cleanhouse-build-check-') as home:
        env={k:os.environ[k] for k in ('PATH','SYSTEMROOT','WINDIR') if k in os.environ}
        env.update(HOME=home,USERPROFILE=home,PYTHONDONTWRITEBYTECODE='1')
        commands=[['scripts/run-auth-regression.py'],['scripts/verify-product-surfaces.py'],
            ['-m','unittest','-v','tests.test_product_surface_baseline','tests.test_product_surface_dependencies']]
        for args in commands:
            print('BUILD CHECK:', ' '.join(args),flush=True)
            try:r=subprocess.run([sys.executable,'-B',*args],cwd=ROOT,env=env,timeout=300)
            except (OSError,subprocess.TimeoutExpired) as e:
                print('BUILD_CHECK_FAILED:',e,file=sys.stderr);return 1
            if r.returncode:return 1
        for name in ('backend/server.py','backend/api/auth.py','backend/api_admission.py'):
            ast.parse((ROOT/name).read_text(),filename=name)
    print('BUILD_CHECK_PASS')
    return 0

if __name__=='__main__':sys.exit(main())
