import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "investigations.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "settings.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "settings.css").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend" / "investigations.html").read_text(encoding="utf-8")
SHELL_JS = (ROOT / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "frontend" / "js" / "auth.js").read_text(encoding="utf-8")


class AuthSettingsUiTests(unittest.TestCase):
    def test_modal_is_accessible_and_loaded_without_replacing_dashboard(self):
        self.assertIn('id="settings-modal"', HTML)
        self.assertIn('role="dialog"', HTML)
        self.assertIn('aria-modal="true"', HTML)
        self.assertIn('aria-labelledby="settings-title"', HTML)
        self.assertIn('role="tablist"', HTML)
        self.assertIn('role="tabpanel"', HTML)
        self.assertIn('/js/settings.js?v=2', HTML)
        self.assertIn('/css/settings.css?v=2', HTML)
        self.assertIn('id="settings-profile-link" href="/settings"', SHELL)
        self.assertIn('id="settings-profile-image"', SHELL)
        self.assertIn('id="settings-profile-fallback"', SHELL)
        self.assertNotIn("CleanHouse Advanced Monitor", HTML)

    def test_complete_settings_shell_is_declared_in_canonical_order(self):
        expected = [
            "general", "providers", "api", "notifications", "personalization",
            "schedules", "billing", "data", "security", "account", "advanced",
        ]
        declaration = re.search(r"const TABS = \[(.*?)\];", JS, re.S)
        self.assertIsNotNone(declaration)
        actual = re.findall(r"\['([^']+)',", declaration.group(1))
        self.assertEqual(expected, actual)
        for tab in ("notifications", "personalization", "schedules", "billing", "data"):
            self.assertRegex(JS, rf"UNAVAILABLE[^;]+['\"]{tab}['\"]")
        self.assertIn("does not claim that these controls are operational yet", JS)

    def test_functional_tabs_use_product_auth_contract(self):
        for endpoint in (
            "/api/auth/csrf",
            "/api/auth/providers",
            "/api/auth/tokens",
            "/api/auth/sessions",
            "/api/auth/sessions/revoke-others",
            "/api/auth/consent",
            "/api/auth/reauth",
            "/api/auth/me",
            "/api/auth/logout",
        ):
            self.assertIn(endpoint, JS)
        self.assertIn("CleanHouseAPI.getSettings()", JS)
        self.assertIn("CleanHouseAPI.updateSettings", JS)
        self.assertIn("input.dataset.key.split('.')", JS)
        self.assertIn("X-CSRF-Token", JS)
        self.assertIn("payload.csrfToken", JS)
        self.assertIn("X-CleanHouse-Reauth", JS)
        self.assertIn("credentials: 'include'", JS)

    def test_api_tokens_are_one_time_and_never_put_in_browser_storage(self):
        self.assertIn("It will not be shown again", JS)
        self.assertIn("navigator.clipboard.writeText", JS)
        self.assertNotIn("localStorage", JS)
        self.assertNotIn("sessionStorage", JS)
        self.assertNotIn("document.cookie", JS)
        self.assertIn("body().innerHTML = ''", JS)
        self.assertIn("let reauthToken = ''", JS)
        self.assertIn("reauthToken = result.reauthToken || result.reauth_token || ''", JS)
        self.assertIn("finally {\n            reauthToken = '';", JS)

    def test_provider_link_uses_authenticated_same_origin_prepare(self):
        self.assertIn("/start', { method: 'POST', body: { intent: 'link' } }", JS)
        self.assertIn('data-settings-action="provider-avatar-refresh"', JS)
        self.assertIn("'/api/auth/oauth/' + encodeURIComponent(provider) + '?intent=photo'", JS)
        self.assertIn("target.origin !== expectedOrigin", JS)
        self.assertIn("String(target).startsWith('/')", JS)
        self.assertIn("String(target).startsWith('//')", JS)
        self.assertNotIn("window.location.assign('/api/auth/oauth/", JS)

    def test_profile_is_hydrated_from_the_session(self):
        self.assertIn("hydrateAccountChrome", JS)
        self.assertIn("user.avatar_url || user.picture", JS)

    def test_keyboard_focus_and_deep_link_behavior_are_present(self):
        self.assertIn("event.key === 'Escape'", JS)
        self.assertIn("event.key !== 'Tab'", JS)
        self.assertIn("'ArrowLeft', 'ArrowRight', 'Home', 'End'", JS)
        self.assertIn("window.location.pathname === '/settings'", JS)
        self.assertIn("history.replaceState", JS)
        self.assertIn("returnFocus.focus()", JS)
        self.assertIn("safeLocalPath", JS)
        self.assertIn("query.get('return_to')", JS)
        self.assertIn("window.location.assign(returnUrl || '/overview')", JS)
        self.assertIn("window.location.pathname === route ? route + window.location.search + window.location.hash", SHELL_JS)

    def test_consent_surface_links_current_legal_documents(self):
        for path in ("/legal/terms", "/legal/privacy", "/legal/eeccd"):
            self.assertIn(path, JS)

    def test_password_signin_fetches_and_submits_csrf(self):
        self.assertIn("async function ensureAuthCsrf()", AUTH_JS)
        self.assertIn("fetch(`${AUTH_BASE_PATH}/csrf`", AUTH_JS)
        self.assertIn("'X-CSRF-Token': csrf", AUTH_JS)
        self.assertIn("postAuth('/login', { email, password })", AUTH_JS)

    def test_mobile_and_reduced_motion_styles_are_explicit(self):
        self.assertIn("@media (max-width: 760px)", CSS)
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)
        self.assertIn(":focus-visible", CSS)
        self.assertIn(".settings-overlay[hidden]", CSS)


if __name__ == "__main__":
    unittest.main()
