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


if __name__ == "__main__":
    unittest.main()
