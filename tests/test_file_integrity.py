import os
import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from backend import file_integrity


def entry(path: str, digest: str, *, size: int = 1):
    return {
        "path": path,
        "provider": "wazuh",
        "observed_at": "2026-08-22T00:00:00+00:00",
        "hashes": {"sha256": digest},
        "metadata": {"size": size, "mode": "0644"},
        "evidence_refs": [f"wazuh://{digest}"],
    }


class FileIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("CLEANHOUSE_FILES_INTEGRITY_DB")
        os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"] = str(Path(self.tmp.name) / "integrity.db")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("CLEANHOUSE_FILES_INTEGRITY_DB", None)
        else:
            os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"] = self.previous
        self.tmp.cleanup()

    def test_rolling_generations_preserve_chain_and_rename_delete(self):
        one = file_integrity.observe({**entry("/scope/a", "a" * 64), "operation": "created"})
        two = file_integrity.observe(
            {**entry("/scope/b", "a" * 64), "operation": "moved", "old_path": "/scope/a"}
        )
        three = file_integrity.observe({"path": "/scope/b", "operation": "deleted", "provider": "wazuh"})

        self.assertEqual(two["previous_chain_hash"], one["chain_hash"])
        self.assertEqual(three["previous_chain_hash"], two["chain_hash"])
        self.assertEqual(file_integrity.snapshot()["entry_count"], 0)
        self.assertEqual(file_integrity.snapshot()["authorization_state"], "not_evaluated_until_zaelith")

    def test_reconcile_receipt_detects_drift_and_advances_generation(self):
        baseline = file_integrity.rebuild([entry("/scope/a", "a" * 64)], provider="wazuh")
        receipt = file_integrity.reconcile(
            [entry("/scope/a", "b" * 64), entry("/scope/new", "c" * 64)], provider="wazuh"
        )

        self.assertEqual(receipt["changed"], 1)
        self.assertEqual(receipt["added"], 1)
        self.assertGreater(receipt["advanced_generation"], baseline["generation"])
        self.assertEqual(file_integrity.snapshot()["last_reconciliation"]["state"], "drift")
        self.assertTrue(file_integrity.verify_reconciliation_receipts()["valid"])

    def test_chain_verification_detects_tampered_generation(self):
        file_integrity.observe({**entry("/scope/a", "a" * 64), "operation": "created"})
        self.assertTrue(file_integrity.verify_chain(force=True)["valid"])
        with closing(sqlite3.connect(os.environ["CLEANHOUSE_FILES_INTEGRITY_DB"])) as conn:
            conn.execute("UPDATE baseline_generations SET delta_json = ? WHERE generation = 1", ('{"tampered":true}',))
            conn.commit()

        result = file_integrity.verify_chain(force=True)

        self.assertFalse(result["valid"])
        self.assertIn("chain hash mismatch", result["first_error"])


if __name__ == "__main__":
    unittest.main()
