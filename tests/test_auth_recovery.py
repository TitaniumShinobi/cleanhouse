import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth_recovery


class AuthRecoveryTests(unittest.TestCase):
    def test_token_is_single_use_and_not_stored_raw(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "recovery.sqlite3"
            with patch.dict(os.environ, {"CLEANHOUSE_AUTH_RECOVERY_DB": str(db)}):
                token = auth_recovery.issue_recovery("user-1", "person@example.com")
                self.assertNotIn(token, db.read_bytes().decode("latin1"))
                self.assertEqual(auth_recovery.consume_recovery(token)["user_id"], "user-1")
                self.assertIsNone(auth_recovery.consume_recovery(token))

    def test_unknown_token_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"CLEANHOUSE_AUTH_RECOVERY_DB": str(Path(root) / "recovery.sqlite3")}):
                self.assertIsNone(auth_recovery.consume_recovery("not-a-token"))


if __name__ == "__main__":
    unittest.main()
