"""Static guardrails for the owner-approved Network meanings.

These tests intentionally protect product meaning rather than pixel styling or
backend algorithms. They fail when a repair removes or repurposes an
established surface.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NetworkOwnerCanonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canon = (ROOT / "CLEANHOUSE.md").read_text(encoding="utf-8")
        cls.product_contract = (
            ROOT / "documents/00_start-here/network-product-contract.md"
        ).read_text(encoding="utf-8")
        cls.taxonomy_contract = (
            ROOT / "documents/00_start-here/security-assessment-taxonomy.md"
        ).read_text(encoding="utf-8")
        cls.trend_contract = (
            ROOT / "documents/00_start-here/network-trend-implementation.md"
        ).read_text(encoding="utf-8")
        cls.projection_contract = (
            ROOT / "documents/00_start-here/network-projection-views.md"
        ).read_text(encoding="utf-8")
        cls.html = (ROOT / "frontend/investigations.html").read_text(encoding="utf-8")
        cls.javascript = (
            ROOT / "frontend/js/investigations.js"
        ).read_text(encoding="utf-8")

    def test_connections_is_visible_name_and_table_is_compatibility_name(self) -> None:
        self.assertIn("| Connections | Exact network observations", self.canon)
        self.assertIn("internal view identifier `table`", self.canon)
        self.assertIn(">Connections</button>", self.html)
        self.assertIn("data-network-view=\"table\"", self.html)

    def test_graph_chart_is_duplicate_navigation_on_both_visual_tabs(self) -> None:
        for contract in (self.canon, self.product_contract, self.trend_contract):
            self.assertRegex(contract, r"(?:`|\*\*)Graph(?:`|\*\*) selects (?:`|\*\*)?Trend")
            self.assertRegex(contract, r"(?:`|\*\*)Chart(?:`|\*\*) selects (?:`|\*\*)?Distribution")
        self.assertRegex(self.html, r'data-network-graph-view="bar"[^>]*>Graph</button>')
        self.assertRegex(self.html, r'data-network-graph-view="pie"[^>]*>Chart</button>')
        self.assertIn("['bar', 'pie'].includes(networkViewMode)", self.javascript)

    def test_trend_remains_graph_with_four_metrics(self) -> None:
        self.assertIn("Trend remains a graph", self.canon)
        self.assertIn("Connections remains the default graph metric", self.canon)
        for metric in ("connections", "strengths", "vulnerabilities", "threats"):
            self.assertIn(f"{metric}: '", self.javascript)
        self.assertNotIn("Interpreted Trend", self.html)

    def test_assessment_category_is_not_operational_health(self) -> None:
        self.assertIn("cleanhouse.security_assessment.v1", self.taxonomy_contract)
        self.assertIn("Operational and lifecycle states", self.taxonomy_contract)
        self.assertIn("never become security categories", self.taxonomy_contract)
        self.assertIn("data.assessments", self.javascript)
        self.assertIn("assessment.category", self.javascript)

    def test_distribution_is_one_packet_backed_donut_and_matching_list(self) -> None:
        self.assertIn("one donut and one matching owner list", self.canon)
        self.assertIn("Only software with observed Network activity appears", self.canon)
        self.assertNotIn("Open Applications", self.html)
        self.assertIn("network-pie-layout", self.javascript)
        self.assertIn("network-pie-legend-row", self.javascript)

    def test_timeline_and_ctrl_preserve_exact_selection_identity(self) -> None:
        self.assertIn("exposes every\n  contained event individually", self.projection_contract)
        self.assertIn("same evidence and assessment IDs", self.canon)
        self.assertIn("network-timeline-interval", self.javascript)
        self.assertIn("data-assessment-id", self.javascript)
        self.assertIn("More actions", self.html)


if __name__ == "__main__":
    unittest.main()
