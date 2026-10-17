"""Account creation must work from the staged release, without checkout imports."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import launch_agent


class StagedAccountDependencyTests(unittest.TestCase):
    def test_staged_release_creates_account_without_source_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for name in ('backend', 'corefiles', 'frontend'):
                (source / name).mkdir(parents=True)
            for name in ('models', 'access_control'):
                shutil.copytree(launch_agent.REPO_ROOT / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            helper = root / 'helper'
            helper.write_text('#!/bin/sh\nexit 1\n')
            helper.chmod(0o700)
            with patch.object(launch_agent, '_runtime_dir', return_value=root / 'runtime'), \
                 patch.object(launch_agent, '_installed_keychain_helper', return_value=helper), \
                 patch.object(launch_agent.auth_runtime_config, 'staged_public_contract', return_value={}):
                staged = launch_agent.stage_runtime(sys.executable, repo_root=source)
            # Removing the fixture source also rules out fallback into that source tree.
            shutil.rmtree(source)
            app = Path(staged['repo_root'])
            script = '''
import sys
from pathlib import Path
app = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(app))
from models.user_model import UserService
import models.user_model
import access_control.access_control as policy
assert Path(models.user_model.__file__).resolve().is_relative_to(app)
assert Path(policy.__file__).resolve().is_relative_to(app)
service = UserService(Path(sys.argv[2]))
user = service.create_user('Synthetic User', 'staging@example.invalid', 'Synthetic-password-123!')
assert user.user_id
assert service.get_user_by_email('staging@example.invalid').user_id == user.user_id
print('STAGED_ACCOUNT_CREATION_PASS')
'''
            result = subprocess.run(
                [sys.executable, '-I', '-B', '-c', script, str(app), str(root / 'accounts')],
                cwd=root, env={'PATH': os.defpath, 'HOME': str(root)},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('STAGED_ACCOUNT_CREATION_PASS', result.stdout)

    def test_missing_dependency_preserves_current_release_and_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for name in ('backend', 'corefiles', 'frontend', 'models'):
                (source / name).mkdir(parents=True)
            runtime = root / 'runtime'
            current = runtime / launch_agent.STAGED_RUNTIME_NAME / 'current'
            current.mkdir(parents=True)
            marker = current / 'previous-release'
            marker.write_bytes(b'unchanged')
            with patch.object(launch_agent, '_runtime_dir', return_value=runtime):
                with self.assertRaises(FileNotFoundError) as failure:
                    launch_agent.stage_runtime(sys.executable, repo_root=source)
            self.assertEqual(Path(failure.exception.args[0]), source.resolve() / 'access_control')
            self.assertEqual(marker.read_bytes(), b'unchanged')
            self.assertEqual(list(current.parent.iterdir()), [current])


if __name__ == '__main__':
    unittest.main()
