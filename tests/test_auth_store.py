import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.auth_store import AuthStore


NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "auth" / "auth.sqlite3"
        self.store = AuthStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def _raw_database(self) -> bytes:
        return self.db_path.read_bytes()

    def test_initializes_private_versioned_database(self):
        self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.db_path.parent.stat().st_mode & 0o777, 0o700)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_session_secret_is_hash_only_and_persists_across_store_restart(self):
        issued = self.store.issue_session("user-1", auth_method="password", now=NOW)
        self.assertNotIn(issued.secret.encode(), self._raw_database())
        restarted = AuthStore(self.db_path)
        result = restarted.validate_session(issued.secret, now=NOW + timedelta(minutes=1))
        self.assertEqual(result.status, "valid")
        self.assertEqual(result.record["user_id"], "user-1")

    def test_provider_avatar_updates_matching_sessions_only(self):
        now = datetime.now(timezone.utc)
        google = self.store.issue_session("user-1", auth_method="oauth:google", now=now)
        current = self.store.issue_session("user-1", auth_method="password", now=now)
        other = self.store.issue_session("user-1", auth_method="password", now=now)
        foreign = self.store.issue_session("user-2", auth_method="oauth:google", now=now)
        avatar = "https://lh3.googleusercontent.com/a/owner"
        self.assertEqual(self.store.refresh_provider_session_avatar(
            "user-1", "google", avatar, current_session_id=current.id
        ), 2)
        self.assertEqual(self.store.validate_session(google.secret, now=now).record["metadata"]["avatar_url"], avatar)
        self.assertEqual(self.store.validate_session(current.secret, now=now).record["metadata"]["avatar_url"], avatar)
        self.assertNotIn("avatar_url", self.store.validate_session(other.secret, now=now).record["metadata"])
        self.assertNotIn("avatar_url", self.store.validate_session(foreign.secret, now=now).record["metadata"])

    def test_session_lifetimes_and_coalesced_last_use(self):
        issued = self.store.issue_session("user-1", auth_method="password", now=NOW)
        first = self.store.validate_session(issued.secret, now=NOW + timedelta(minutes=1))
        self.assertEqual(first.record["last_used_at"], NOW.isoformat())
        updated = self.store.validate_session(issued.secret, now=NOW + timedelta(minutes=6))
        self.assertEqual(updated.record["last_used_at"], (NOW + timedelta(minutes=6)).isoformat())
        self.assertEqual(updated.record["absolute_expires_at"], (NOW + timedelta(days=30)).isoformat())
        self.assertEqual(updated.record["idle_expires_at"], (NOW + timedelta(days=7, minutes=6)).isoformat())

    def test_daily_session_rotation_is_atomic_and_old_secret_replays_fail(self):
        issued = self.store.issue_session("user-1", auth_method="password", now=NOW)
        rotated = self.store.validate_session(issued.secret, now=NOW + timedelta(days=1, seconds=1))
        self.assertEqual(rotated.status, "rotated")
        self.assertIsNotNone(rotated.replacement)
        self.assertEqual(
            self.store.validate_session(issued.secret, now=NOW + timedelta(days=1, seconds=2)).status,
            "replayed",
        )
        self.assertEqual(
            self.store.validate_session(rotated.replacement.secret, now=NOW + timedelta(days=1, seconds=2)).status,
            "valid",
        )
        self.assertNotIn(rotated.replacement.secret.encode(), self._raw_database())

    def test_concurrent_refresh_has_one_winner(self):
        issued = self.store.issue_session("user-1", auth_method="password", now=NOW)
        barrier = threading.Barrier(3)
        statuses = []

        def refresh():
            local = AuthStore(self.db_path)
            barrier.wait()
            statuses.append(local.refresh_session(issued.secret, now=NOW + timedelta(hours=1)).status)

        threads = [threading.Thread(target=refresh), threading.Thread(target=refresh)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(statuses), ["replayed", "rotated"])

    def test_idle_and_absolute_expiry_fail_closed(self):
        idle = self.store.issue_session("idle-user", auth_method="password", now=NOW)
        absolute = self.store.issue_session("absolute-user", auth_method="password", now=NOW)
        self.assertEqual(
            self.store.validate_session(idle.secret, now=NOW + timedelta(days=7, seconds=1)).status,
            "expired",
        )
        self.assertEqual(
            self.store.validate_session(absolute.secret, now=NOW + timedelta(days=30, seconds=1)).status,
            "expired",
        )

    def test_logout_and_revoke_others_append_events(self):
        current = self.store.issue_session("user-1", auth_method="password", now=NOW)
        other = self.store.issue_session("user-1", auth_method="magic", now=NOW)
        self.assertEqual(self.store.revoke_other_sessions("user-1", current.id, now=NOW + timedelta(minutes=1)), 1)
        self.assertEqual(self.store.validate_session(other.secret, now=NOW + timedelta(minutes=2)).status, "revoked")
        self.assertTrue(self.store.revoke_session(current.id, "user-1", now=NOW + timedelta(minutes=2)))
        with sqlite3.connect(self.db_path) as connection:
            event_types = [row[0] for row in connection.execute("SELECT event_type FROM session_events")]
        self.assertEqual(event_types.count("session_issued"), 2)
        self.assertEqual(event_types.count("session_revoked"), 2)

    def test_session_events_and_consent_receipts_are_database_append_only(self):
        self.store.issue_session("user-1", auth_method="password", now=NOW)
        digest = hashlib.sha256(b"terms").hexdigest()
        self.store.record_consent("user-1", "terms", digest, "checkbox", transaction_id="tx-1", now=NOW)
        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM session_events")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE consent_receipts SET acceptance_method = 'other'")

    def test_versioned_consent_requires_exact_current_digests(self):
        terms_v1 = hashlib.sha256(b"terms-v1").hexdigest()
        terms_v2 = hashlib.sha256(b"terms-v2").hexdigest()
        privacy = hashlib.sha256(b"privacy").hexdigest()
        self.store.record_consent("user-1", "terms", terms_v1, "signup", transaction_id="tx-1", now=NOW)
        old = self.store.consent_status("user-1", {"terms": terms_v1, "privacy": privacy})
        self.assertFalse(old["current"])
        self.assertEqual(old["missing"], ["privacy"])
        changed = self.store.consent_status("user-1", {"terms": terms_v2})
        self.assertFalse(changed["current"])
        self.assertEqual(changed["missing"], ["terms"])

    def test_magic_challenge_is_bound_single_use_and_expires(self):
        challenge = self.store.issue_magic_challenge(
            "Person@Example.com", intent="signin", purpose="magic_auth", origin="http://localhost:3333", now=NOW
        )
        self.assertNotIn(challenge.secret.encode(), self._raw_database())
        mismatch = self.store.consume_magic_challenge(
            challenge.secret, purpose="password_recovery", origin="http://localhost:3333", now=NOW
        )
        self.assertEqual(mismatch.status, "binding_mismatch")
        accepted = self.store.consume_magic_challenge(
            challenge.secret, purpose="magic_auth", origin="http://localhost:3333", now=NOW
        )
        self.assertEqual(accepted.status, "consumed")
        self.assertEqual(accepted.record["normalized_email"], "person@example.com")
        self.assertEqual(
            self.store.consume_magic_challenge(
                challenge.secret, purpose="magic_auth", origin="http://localhost:3333", now=NOW
            ).status,
            "replayed",
        )
        expired = self.store.issue_magic_challenge(
            "other@example.com", intent="signup", purpose="magic_auth", origin="http://localhost:3333", now=NOW
        )
        self.assertEqual(
            self.store.consume_magic_challenge(
                expired.secret, purpose="magic_auth", origin="http://localhost:3333",
                now=NOW + timedelta(minutes=15, seconds=1),
            ).status,
            "expired",
        )

    def test_delivery_failure_can_revoke_magic_challenge(self):
        challenge = self.store.issue_magic_challenge(
            "person@example.com", intent="signin", purpose="magic_auth", origin="http://localhost:3333", now=NOW
        )
        self.assertTrue(self.store.revoke_magic_challenge(challenge.id, now=NOW + timedelta(seconds=1)))
        self.assertEqual(
            self.store.consume_magic_challenge(
                challenge.secret, purpose="magic_auth", origin="http://localhost:3333", now=NOW + timedelta(seconds=2)
            ).status,
            "revoked",
        )

    def test_external_identity_uses_provider_subject_and_refuses_cross_user_link(self):
        binding_id = self.store.bind_external_identity(
            "user-1", "github", "stable-subject-7", verified_email="Person@Example.com", now=NOW
        )
        self.assertEqual(
            self.store.external_identity("github", "stable-subject-7")["binding_id"], binding_id
        )
        with self.assertRaisesRegex(ValueError, "another user"):
            self.store.bind_external_identity(
                "user-2", "github", "stable-subject-7", verified_email="person@example.com", now=NOW
            )

    def test_api_token_one_time_secret_hash_expiry_rotation_and_replay(self):
        issued = self.store.issue_api_token("user-1", label="automation", now=NOW)
        self.assertTrue(issued.secret.startswith("chpat_"))
        self.assertNotIn(issued.secret.encode(), self._raw_database())
        self.assertEqual(self.store.validate_api_token(issued.secret, now=NOW).status, "valid")
        rotated = self.store.rotate_api_token(issued.id, "user-1", now=NOW + timedelta(days=1))
        self.assertIsNotNone(rotated)
        self.assertEqual(self.store.validate_api_token(issued.secret, now=NOW + timedelta(days=1)).status, "replayed")
        self.assertEqual(self.store.validate_api_token(rotated.secret, now=NOW + timedelta(days=1)).status, "valid")
        self.assertNotIn("token_hash", self.store.list_api_tokens("user-1")[0])

    def test_api_token_lifetime_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 90"):
            self.store.issue_api_token("user-1", label="too-long", lifetime_days=91, now=NOW)

    def test_reauth_grant_is_scope_and_session_bound_single_use(self):
        grant = self.store.issue_reauth_grant("user-1", "session-1", "tokens:create", now=NOW)
        self.assertFalse(self.store.consume_reauth_grant(
            grant.secret, user_id="user-1", session_id="session-1", scope="sessions:revoke", now=NOW
        ))
        self.assertTrue(self.store.consume_reauth_grant(
            grant.secret, user_id="user-1", session_id="session-1", scope="tokens:create", now=NOW
        ))
        self.assertFalse(self.store.consume_reauth_grant(
            grant.secret, user_id="user-1", session_id="session-1", scope="tokens:create", now=NOW
        ))

    def test_pending_enrollment_is_purpose_bound_and_atomic(self):
        pending = self.store.issue_pending_enrollment(
            "magic_signup", email="New@Example.com", payload={"full_name": "New Person"}, now=NOW
        )
        self.assertEqual(
            self.store.consume_pending_enrollment(pending.secret, kind="oauth_signup", now=NOW).status,
            "binding_mismatch",
        )
        consumed = self.store.consume_pending_enrollment(pending.secret, kind="magic_signup", now=NOW)
        self.assertEqual(consumed.status, "consumed")
        self.assertEqual(consumed.record["email"], "new@example.com")
        self.assertEqual(consumed.record["payload"]["full_name"], "New Person")
        self.assertEqual(
            self.store.consume_pending_enrollment(pending.secret, kind="magic_signup", now=NOW).status,
            "replayed",
        )

    def test_metadata_size_and_query_results_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "bounded storage"):
            self.store.issue_session("user-1", auth_method="password", metadata={"large": "x" * 20000}, now=NOW)
        for index in range(3):
            self.store.issue_session("user-1", auth_method=f"method-{index}", now=NOW + timedelta(seconds=index))
        self.assertEqual(len(self.store.list_sessions("user-1", limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
