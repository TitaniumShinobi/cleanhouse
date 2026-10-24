from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from backend import launch_agent


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "investigations.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "settings.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "settings.css").read_text(encoding="utf-8")


class PolicyConsentModalTests(unittest.TestCase):
    def test_local_asset_references_are_tracked_runtime_payload(self):
        references = sorted(set(re.findall(r'(?:src|href)=["\'](/assets/[^"\']+)', HTML)))
        self.assertTrue(references)
        self.assertIn("assets", launch_agent.RUNTIME_INDEX_PREFIXES)
        for reference in references:
            relative = reference.removeprefix("/").split("?", 1)[0]
            self.assertTrue((ROOT / relative).is_file(), reference)
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", relative],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(tracked.returncode, 0, reference)

    def test_compact_dialog_has_accessible_blocking_controls(self):
        self.assertIn('id="policy-consent-modal"', HTML)
        self.assertIn('role="dialog" aria-modal="true"', HTML)
        self.assertIn('aria-labelledby="policy-consent-title"', HTML)
        self.assertIn('aria-describedby="policy-consent-description"', HTML)
        self.assertIn('id="policy-consent-checkbox" type="checkbox"', HTML)
        self.assertIn('id="policy-consent-accept"', HTML)
        self.assertIn('data-policy-action="accept" disabled', HTML)
        self.assertIn('role="status" aria-live="polite"', HTML)

    def test_standalone_policy_links_are_direct_and_safe(self):
        for path in ("/legal/terms", "/legal/privacy", "/legal/eeccd"):
            self.assertIn(f'href="{path}" target="_blank" rel="noopener"', HTML)

    def test_keyboard_focus_and_explicit_confirmation_are_enforced(self):
        self.assertIn("event.key === 'Escape'", JS)
        self.assertIn("event.key !== 'Tab'", JS)
        self.assertIn("document.activeElement === first", JS)
        self.assertIn("document.activeElement === last", JS)
        self.assertIn("accept.disabled = !checked || !checked.checked", JS)
        self.assertIn("if (!checked || !checked.checked) return", JS)

    def test_return_path_is_bounded_and_settings_remains_intentional(self):
        self.assertIn("safeLocalPath(query.get('return_to'))", JS)
        self.assertIn("window.location.assign(policyReturnPath())", JS)
        self.assertIn("window.location.pathname !== '/settings'", JS)
        self.assertIn("window.location.pathname === '/settings'", JS)

    def test_dismissal_only_hides_popup_and_reload_remains_server_gated(self):
        self.assertIn("node.hidden = true", JS)
        self.assertIn("url.searchParams.delete('consent')", JS)
        self.assertNotIn("acceptCurrentPolicies();\n            closePolicyConsent", JS)
        self.assertNotIn("data-policy-action=\"close\" data-policy-action=\"accept\"", HTML)
        self.assertIn("payload.consent_required === true", JS)

    def test_responsive_and_focus_styles_are_scoped(self):
        self.assertIn(".policy-consent-overlay", CSS)
        self.assertIn(".policy-consent-dialog", CSS)
        self.assertIn("@media (max-width: 560px)", CSS)
        self.assertIn(".policy-consent-dialog button:focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
