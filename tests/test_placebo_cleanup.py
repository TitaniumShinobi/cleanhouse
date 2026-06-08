import tempfile
import unittest
from pathlib import Path

from corefiles.integrity import IntegrityMonitor
from corefiles.passion import restore_file as passion_restore_file
from corefiles.purge import restore_file as purge_restore_file


class PlaceboCleanupTests(unittest.TestCase):
    def test_passion_restore_file_does_not_report_success_without_restore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "sample.txt"
            target.write_text("original", encoding="utf-8")
            before = target.read_text(encoding="utf-8")

            result = passion_restore_file(target)
            after = target.read_text(encoding="utf-8")

            self.assertFalse(result)
            self.assertEqual(before, after)

    def test_purge_restore_file_does_not_report_success_without_restored_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "sample.txt"
            target.write_text("changed", encoding="utf-8")
            before = target.read_text(encoding="utf-8")

            result = purge_restore_file(target, dry_run=False)
            after = target.read_text(encoding="utf-8")

            self.assertFalse(result)
            self.assertEqual(before, after)

    def test_integrity_monitor_stats_expose_only_backed_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tracked.txt").write_text("v1", encoding="utf-8")
            monitor = IntegrityMonitor(root_dir=root, interval=1)
            keys = set(monitor.get_stats().keys())

            self.assertIn("files_scanned", keys)
            self.assertIn("timestamps", keys)
            self.assertNotIn("unauthorized_sessions", keys)
            self.assertNotIn("integrity_restorations", keys)
            self.assertNotIn("cloud_uploads", keys)


if __name__ == "__main__":
    unittest.main()
