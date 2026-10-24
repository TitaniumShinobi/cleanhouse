import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / 'backend/api/auth.py').read_text()
SERVER = (ROOT / 'backend/server.py').read_text()
DOC = (ROOT / 'documents/00_start-here/cleanhouse-mfa.md').read_text()
DELETE_UI = (ROOT / 'frontend/js/account-delete.js').read_text()


class CleanHouseMfaContractTests(unittest.TestCase):
    def test_server_enforces_mfa_before_consent_without_merging_states(self):
        mfa = SERVER.index("if not mfa_authorized:")
        consent = SERVER.index("if not identity.consent_current:")
        self.assertLess(mfa, consent)
        self.assertIn("code': 'mfa_required'", SERVER)
        self.assertIn("code': 'consent_required'", SERVER)

    def test_consent_handler_does_not_request_authentication_or_mfa(self):
        start = AUTH.index("def accept_consent():")
        end = AUTH.index("@bp.route('/auth/magic/request'", start)
        handler = AUTH[start:end]
        for forbidden in ('reauthenticate(', 'mfa_challenge(', 'mfa_verify(', 'authenticate_user('):
            self.assertNotIn(forbidden, handler)
        self.assertIn('_record_current_consent', handler)

    def test_source_contract_records_external_limits_and_rollback(self):
        self.assertIn('No live migration was run.', DOC)
        self.assertIn('Ordinary policy acceptance remains a separate, idempotent authenticated action.', DOC)
        self.assertIn('canonical runtime activation', DOC)
        self.assertIn('must not be silently deleted', DOC)

    def test_documented_operation_targets_match_server_and_ui_contract(self):
        for phrase in (
            '`authenticate`, `factor.add`, and `recovery.rotate` require an empty target',
            '`factor.remove` requires the exact factor ID', '`account.delete` requires `delete`',
            '`provider.manage` requires the exact provider ID', '`token.manage` requires the exact token ID',
            '`session.manage` requires the exact session ID',
        ):
            self.assertIn(phrase, DOC)
        for literal in ("'provider.manage'", "'token.manage'", "'session.manage'", "'account.delete'"):
            self.assertIn(literal, AUTH)

    def test_account_deletion_uses_exact_mfa_operation_and_target(self):
        self.assertIn("operation: 'account.delete', target: 'delete'", DELETE_UI)
        self.assertIn("'X-CleanHouse-MFA-Target': 'delete'", DELETE_UI)
        self.assertIn("'/api/auth/mfa/verify'", DELETE_UI)


if __name__ == '__main__':
    unittest.main()
