"""Gate control-flow tests; real regressions run separately through the same gate."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('product_build_check', Path(__file__).resolve().parents[1] / 'scripts/build-check.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class BuildCheckTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        self.root = Path(self.home.name)
        for relative in gate.SYNTAX_FILES:
            p = self.root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('pass\n')
        p = patch.object(gate, 'ROOT', self.root); p.start(); self.addCleanup(p.stop)
        p = patch.object(gate.shutil, 'which', return_value='/fixture/node'); p.start(); self.addCleanup(p.stop)

    def results(self, codes=(0, 0, 0)):
        return [subprocess.CompletedProcess([], 0, stdout='v22.0.0')] + [subprocess.CompletedProcess([], c) for c in codes]

    def test_success_and_isolated_witness_routing(self):
        environment = {'PATH': '/fixture', 'PROVIDER_SECRET': 'not-for-child', 'PYTHONPATH': '/untrusted',
                       'PRODUCT_TEST_WITNESS_FILE': '/fixture/witness', 'PRODUCT_TEST_WITNESS_NONCE': 'nonce'}
        with patch.dict(gate.os.environ, environment, clear=True), patch.object(gate.subprocess, 'run', side_effect=self.results()) as run:
            self.assertEqual(gate.main(), 0)
        calls = run.call_args_list[1:]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0].kwargs['env']['CLEANHOUSE_TEST_PYTHON'], gate.sys.executable)
        self.assertEqual(calls[0].kwargs['env']['PRODUCT_TEST_WITNESS_NONCE'], 'nonce')
        for call in calls:
            env = call.kwargs['env']
            self.assertNotIn('PROVIDER_SECRET', env); self.assertNotIn('PYTHONPATH', env)
            self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
        for call in calls[1:]: self.assertNotIn('PRODUCT_TEST_WITNESS_NONCE', call.kwargs['env'])

    def test_each_gate_failure_stops_following_commands(self):
        for index in range(3):
            with self.subTest(index=index):
                results = self.results(); results[index + 1].returncode = 7
                with patch.object(gate.subprocess, 'run', side_effect=results) as run:
                    self.assertEqual(gate.main(), 7); self.assertEqual(run.call_count, index + 2)

    def test_missing_node(self):
        with patch.object(gate.shutil, 'which', return_value=None), patch.object(gate.subprocess, 'run') as run:
            self.assertEqual(gate.main(), 2); run.assert_not_called()

    def test_old_node(self):
        with patch.object(gate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='v18.0.0')):
            self.assertEqual(gate.main(), 2)

    def test_timeout_and_missing_executable(self):
        for error in (subprocess.TimeoutExpired('fixture', 1), FileNotFoundError()):
            with patch.object(gate.subprocess, 'run', side_effect=[self.results()[0], error]):
                self.assertEqual(gate.main(), 2)

    def test_syntax_failure_prevents_execution(self):
        (self.root / gate.SYNTAX_FILES[0]).write_text('def invalid(:')
        with patch.object(gate.subprocess, 'run', side_effect=self.results()) as run:
            self.assertEqual(gate.main(), 2); self.assertEqual(run.call_count, 1)


if __name__ == '__main__': unittest.main()
