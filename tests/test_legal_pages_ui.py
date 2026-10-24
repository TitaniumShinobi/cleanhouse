import unittest
from pathlib import Path

from backend import server


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "frontend" / "css" / "legal.css").read_text(encoding="utf-8")


class LegalPagesUiTests(unittest.TestCase):
    def test_each_legal_route_uses_isolated_html_shell_without_changing_content(self):
        documents = {
            "terms": (
                "CLEANHOUSE_TERMS_OF_SERVICE.md",
                "1. Agreement",
                "maintain suitable backups and recovery material;",
                "These Terms govern",
            ),
            "privacy": (
                "CLEANHOUSE_PRIVACY_NOTICE.md",
                "1. Scope",
                "OAuth identity providers for sign-in;",
                "This Notice explains",
            ),
            "eeccd": (
                "CLEANHOUSE_EUROPEAN_ELECTRONIC_COMMUNICATIONS_CODE_DISCLOSURE.md",
                "1. Ethics",
                "No surveillance.",
                "CleanHouse is engineered with",
            ),
        }
        for kind, (filename, heading, list_item, paragraph) in documents.items():
            source = (ROOT / "docs" / "legal" / filename).read_text(encoding="utf-8")
            response, status, headers = server._render_legal_document(ROOT / "docs" / "legal" / filename, kind)
            with self.subTest(kind=kind):
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
                self.assertIn(f'class="legal-page legal-page--{kind}"', response)
                self.assertIn(source.splitlines()[0], response)
                expected_date = "October 23, 2026" if kind in {"terms", "privacy"} else "November 9, 2025"
                self.assertIn(f"Last Updated: {expected_date}", response)
                self.assertIn('/css/legal.css?v=1', response)
                self.assertIn(f"<h2>{heading}</h2>", response)
                self.assertIn("<ul>", response)
                self.assertIn(list_item, response)
                self.assertIn(f"<p>{paragraph}", response)
                self.assertIn(
                    '<a href="mailto:info@thewreck.org">info@thewreck.org</a>',
                    response,
                )
                self.assertNotIn("[info@thewreck.org](mailto:info@thewreck.org)", response)

    def test_legal_css_is_page_scoped_and_soft_green(self):
        self.assertIn("body.legal-page", CSS)
        self.assertIn("rgba(44, 154, 87, .14)", CSS)
        self.assertIn("--legal-green: #55c885", CSS)
        self.assertIn(".legal-updated", CSS)
        self.assertIn("@media (max-width: 720px)", CSS)
        self.assertNotIn("body:not(.legal-page)", CSS)
        self.assertNotIn(".settings-", CSS)
        self.assertNotIn(".app-", CSS)


if __name__ == "__main__":
    unittest.main()
