import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductSurfaceBaselineTests(unittest.TestCase):
    def test_owner_approved_surfaces_remain_present_and_routed(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify-product-surfaces.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("11 protected surfaces", result.stdout)




class ProductSurfaceMutationTests(unittest.TestCase):
    def test_missing_files_markers_and_routes_fail_closed(self):
        import json
        import shutil
        import tempfile
        baseline = json.loads((ROOT / '.cleanhouse/product-surface-baseline.json').read_text())
        with tempfile.TemporaryDirectory(prefix='cleanhouse-surface-test-') as tmp:
            fixture = Path(tmp)
            paths = {'.cleanhouse/product-surface-baseline.json', 'scripts/verify-product-surfaces.py', 'backend/server.py'}
            paths.update(s['file'] for s in baseline['surfaces'])
            for relative in paths:
                dest = fixture / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, dest)
            def run():
                return subprocess.run([sys.executable, '-B', str(fixture / 'scripts/verify-product-surfaces.py')], capture_output=True, text=True)
            self.assertEqual(run().returncode, 0)
            for surface in baseline['surfaces']:
                for mutation in ('file', 'marker', 'route'):
                    with self.subTest(surface=surface['name'], mutation=mutation):
                        target = fixture / ('backend/server.py' if mutation == 'route' else surface['file'])
                        original = target.read_bytes()
                        try:
                            if mutation == 'file':
                                target.unlink()
                            elif mutation == 'marker':
                                target.write_text(original.decode().replace(surface['marker'], 'removed-marker'))
                            else:
                                source = original.decode()
                                for quote in ("'", '"'):
                                    source = source.replace('@app.route(' + quote + surface['route'] + quote + ')', '# removed route')
                                target.write_text(source)
                            result = run()
                            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                            self.assertIn(surface['name'], result.stderr)
                        finally:
                            target.write_bytes(original)
            self.assertEqual(run().returncode, 0)

if __name__ == "__main__":
    unittest.main()
