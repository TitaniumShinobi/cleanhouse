import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth_email


class AuthEmailTests(unittest.TestCase):
    def test_owner_only_resend_key_file_enables_magic_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "resend-key"
            key_file.write_text("re_fixture\n", encoding="utf-8")
            key_file.chmod(0o600)
            environment = {
                "EMAIL_SERVICE": "resend",
                "CLEANHOUSE_RESEND_API_KEY_FILE": str(key_file),
            }
            with patch.dict(os.environ, environment, clear=True):
                self.assertTrue(auth_email.email_delivery_available())
                key_file.chmod(0o640)
                self.assertFalse(auth_email.email_delivery_available())

    def test_resend_delivery_uses_secret_without_exposing_it_in_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "resend-key"
            key_file.write_text("re_fixture\n", encoding="utf-8")
            key_file.chmod(0o600)
            response = type("Response", (), {"raise_for_status": lambda self: None})()
            with patch.dict(os.environ, {
                "EMAIL_SERVICE": "resend",
                "CLEANHOUSE_RESEND_API_KEY_FILE": str(key_file),
            }, clear=True), patch.object(auth_email.requests, "post", return_value=response) as post:
                auth_email.deliver_auth_email("person@example.com", subject="Subject", text="Body")
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer re_fixture")
            self.assertNotIn("re_fixture", post.call_args.kwargs["data"])


if __name__ == "__main__":
    unittest.main()
