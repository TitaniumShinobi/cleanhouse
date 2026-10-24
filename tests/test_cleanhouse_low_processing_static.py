from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dashboard_default_refresh_is_emergency_summary_only():
    source = read_text("frontend/js/dashboard.js")
    assert "async function refreshEmergencySummary()" in source
    assert "loadSessions().finally(() => refreshEmergencySummary())" in source
    assert "setInterval(() =>" in source
    assert "if (document.hidden) return;" in source
    assert "refreshEmergencySummary();" in source
    assert "const DASHBOARD_AUTO_REFRESH_INTERVAL_MS = 30000;" in source
    assert "fetchActiveContext(false)" in source


def test_dashboard_manual_refresh_keeps_evidence_caps():
    source = read_text("frontend/js/dashboard.js")
    assert "DASHBOARD_LOW_PROCESSING_EVENT_LIMIT = 20" in source
    assert "DASHBOARD_LOW_PROCESSING_RECEIPT_LIMIT = 5" in source
    assert "DASHBOARD_RENDER_ROW_LIMIT = 10" in source
    assert "DASHBOARD_INLINE_REF_LIMIT = 5" in source
    assert "getEvents(DASHBOARD_LOW_PROCESSING_EVENT_LIMIT)" in source
    assert "getReceipts(sessionId, DASHBOARD_LOW_PROCESSING_RECEIPT_LIMIT)" in source
    assert "fetchReceiptReplays(" in source
    assert "fetchReceiptBundles(" in source
    assert "renderReceiptScope(_lastReceipts, _lastApprovalQueue, _lastReceiptReplays, _lastReceiptBundles)" in source


def test_reports_history_is_summary_only_until_opened():
    source = read_text("frontend/js/reports.js")
    assert "const REPORT_HISTORY_LIMIT = 10;" in source
    assert "limit: REPORT_HISTORY_LIMIT" in source
    assert "summaryOnly: true" in source
    assert "async function loadReportDetail(reportId)" in source
    assert "window.CleanHouseAPI.getReport(reportId)" in source
    assert "data-report-detail" in source
    assert "report-open-button" in source


def test_backend_low_processing_route_caps_are_present():
    source = read_text("backend/api/cleanhouse.py")
    assert "LOW_PROCESSING_EVENT_LIMIT = 20" in source
    assert "LOW_PROCESSING_EVENT_MAX_LIMIT = 200" in source
    assert "LOW_PROCESSING_DOMAIN_EVENT_LIMIT = 50" in source
    assert "LOW_PROCESSING_REPORT_LIMIT = 10" in source
    assert "LOW_PROCESSING_REPORT_MAX_LIMIT = 50" in source
    assert "@bp.route(\"/cleanhouse/reports/<path:report_id>\"" in source
    assert "limit=limit or LOW_PROCESSING_REPORT_LIMIT" in source
    assert "limit=limit or LOW_PROCESSING_EVENT_LIMIT" in source


def test_investigations_render_caps_are_present():
    source = read_text("frontend/js/investigations.js")
    assert "const APPLICATION_RENDER_LIMIT = 80;" in source
    assert "const PROCESS_RENDER_LIMIT = 5;" in source
    assert "applications.slice(0, APPLICATION_RENDER_LIMIT)" in source
    assert "rows.slice(0, PROCESS_RENDER_LIMIT)" in source
