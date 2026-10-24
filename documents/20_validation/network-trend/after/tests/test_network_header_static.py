import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class NetworkHeaderStaticTests(unittest.TestCase):
    def test_network_mobile_shell_keeps_the_main_canvas_in_the_visible_grid_column(self):
        css = read_text("frontend/css/investigations.css")

        self.assertIn("body:has(#network:not([hidden])) .main-canvas {", css)
        mobile_rule = css.split("@media (max-width: 980px) {", 1)[1]
        network_canvas = mobile_rule.split("body:has(#network:not([hidden])) .main-canvas {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-column: 1;", network_canvas)
        self.assertIn("overflow: hidden;", network_canvas)
        self.assertIn("height: 100%;", network_canvas)
        network_view = mobile_rule.split("#network.view-section {", 1)[1].split("}", 1)[0]
        self.assertIn("min-width: 0;", network_view)
        self.assertIn("width: 100%;", network_view)

    def test_network_table_uses_one_native_sticky_header_in_shared_scroll_container(self):
        css = read_text("frontend/css/investigations.css")
        source = read_text("frontend/js/investigations.js")
        wrap_rule = css.split(".network-table-wrap {", 1)[1].split("}", 1)[0]
        header_rule = css.split(".network-table th {", 1)[1].split("}", 1)[0]

        self.assertIn("overflow-x: auto;", wrap_rule)
        self.assertIn("align-self: start;", wrap_rule)
        self.assertNotIn("align-self: center;", wrap_rule)
        scoped_wrap_rule = css.split("#network .network-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("height: calc(100% - 10px);", scoped_wrap_rule)
        self.assertIn("min-height: 240px;", wrap_rule)
        self.assertNotIn("max-height:", wrap_rule)
        self.assertIn("overflow-y: hidden;", wrap_rule)
        self.assertIn("scrollbar-gutter: stable;", wrap_rule)
        table_rule = css.split(".network-table {", 1)[1].split("}", 1)[0]
        body_rule = css.split(".network-table tbody {", 1)[1].split("}", 1)[0]
        self.assertIn("table-layout: fixed;", table_rule)
        self.assertNotIn("display: grid;", table_rule)
        self.assertIn("display: block;", body_rule)
        self.assertIn("height: calc(100% - 34px);", body_rule)
        self.assertIn("overflow-y: scroll;", body_rule)
        self.assertNotIn("overflow-y: scroll;", wrap_rule)
        network_table_body = source.split("function renderNetworkTable(events, data = {}) {", 1)[1].split("function networkTableRowHtml(", 1)[0]
        self.assertEqual(network_table_body.count("<thead><tr>"), 1)
        self.assertIn("if (networkViewMode !== 'table' && !events.length", source)
        self.assertIn("const bodyHtml = orderedRows.length", source)
        self.assertIn("network-table-empty-row", source)

    def test_network_connections_label_and_responsive_viewport_contract(self):
        html = read_text("frontend/investigations.html")
        css = read_text("frontend/css/investigations.css")
        source = read_text("frontend/js/investigations.js")

        self.assertIn('data-network-view="table">Connections</button>', html)
        self.assertNotIn('data-network-view="table">Table</button>', html)

        network_shell = css.split("#network.view-section {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-rows: auto auto auto minmax(0, 1fr) 44px;", network_shell)
        self.assertIn("gap: 8px;", network_shell)
        self.assertIn("height: 100%;", network_shell)
        self.assertIn("overflow: hidden;", network_shell)

        toolbar_rule = css.split(".network-toolbar {", 1)[1].split("}", 1)[0]
        self.assertIn("margin: 0;", toolbar_rule)

        results_rule = css.split("#network #network-results {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: auto;", results_rule)
        self.assertIn("max-width: 1280px;", results_rule)
        self.assertIn("margin: 0 auto;", results_rule)
        table_results_rule = css.split("#network #network-results:has(.network-table) {", 1)[1].split("}", 1)[0]
        self.assertIn("align-content: stretch;", table_results_rule)
        self.assertIn("grid-template-rows: minmax(250px, 1fr);", table_results_rule)
        self.assertIn("overflow: hidden;", table_results_rule)

        table_wrap_rule = css.split(".network-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("align-self: start;", table_wrap_rule)
        self.assertNotIn("align-self: center;", table_wrap_rule)
        scoped_table_wrap_rule = css.split("#network .network-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("height: calc(100% - 10px);", scoped_table_wrap_rule)
        self.assertNotIn("620px", scoped_table_wrap_rule)

        provider_rule = css.split(".network-powered-fixed {", 1)[1].split("}", 1)[0]
        self.assertIn("position: relative;", provider_rule)
        self.assertIn("min-height: 44px;", provider_rule)
        self.assertNotIn("position: fixed;", provider_rule)

        network_canvas = css.split("body:has(#network:not([hidden])) .main-canvas {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: hidden;", network_canvas)
        self.assertIn("height: 100%;", network_canvas)

        self.assertIn("window.addEventListener('resize', updateFade, { passive: true });", source)
        self.assertNotIn("window.addEventListener('resize', hydrateNetworkView", source)
        self.assertNotIn("window.addEventListener('resize', loadNetwork", source)

    def test_network_findings_uses_the_bounded_responsive_results_window(self):
        css = read_text("frontend/css/investigations.css")
        source = read_text("frontend/js/investigations.js")
        backend = read_text("backend/api/cleanhouse.py")
        contract = read_text("documents/00_start-here/network-findings-implementation.md")

        results_rule = css.split("#network #network-results:has(.network-findings-window) {", 1)[1].split("}", 1)[0]
        self.assertIn("align-content: stretch;", results_rule)
        self.assertIn("grid-template-rows: minmax(250px, 1fr);", results_rule)
        self.assertIn("overflow: hidden;", results_rule)

        window_rule = css.split(".network-findings-window {", 1)[1].split("}", 1)[0]
        self.assertIn("align-self: start;", window_rule)
        self.assertIn("height: calc(100% - 10px);", window_rule)
        self.assertIn("margin: 0 auto;", window_rule)
        self.assertIn("max-width: 1280px;", window_rule)
        self.assertIn("min-height: 240px;", window_rule)
        self.assertIn("overflow: hidden;", window_rule)
        self.assertIn("text-align: left;", window_rule)
        self.assertIn("width: 100%;", window_rule)

        feed_rule = css.split(".network-findings-feed {", 1)[1].split("}", 1)[0]
        self.assertIn("height: 100%;", feed_rule)
        self.assertIn("max-height: none;", feed_rule)
        self.assertIn("overflow: auto;", feed_rule)
        self.assertIn("overscroll-behavior: contain;", feed_rule)

        findings_body = source.split("function renderNetworkFindings(events) {", 1)[1].split(
            "function bindNetworkFindingsWindow()", 1
        )[0]
        self.assertIn("networkFindingPriority(event)", findings_body)
        self.assertIn("networkEvidenceAttributes(event, 'findings')", findings_body)
        self.assertIn("<details class=\"case-item network-finding-item\"", findings_body)
        self.assertIn("network-findings-body-action-link", findings_body)
        self.assertIn("CONNECTIONS-FINDINGS-LAYOUT-001", contract)
        self.assertIn("#network #network-results:has(.network-findings-window)", contract)
        self.assertIn("## Architecture and data provenance", contract)
        self.assertIn("## Rendered components and controls", contract)
        self.assertIn("## State and transition contract", contract)
        self.assertIn("## Failure states and operator interpretation", contract)
        self.assertIn("`50,000` retained events", contract)
        self.assertIn("`100` findings", contract)
        self.assertIn("`768x1024`", contract)
        self.assertIn("`1728x1117`", contract)
        self.assertIn("Source/runtime stylesheet SHA-256", contract)
        self.assertIn("`CLEANHOUSE.md` remains unchanged", contract)

        self.assertIn('NETWORK_EVIDENCE_LOOKBACK = int(os.environ.get("CLEANHOUSE_NETWORK_EVIDENCE_LOOKBACK", "50000"))', backend)
        self.assertIn('NETWORK_FINDINGS_LOOKBACK = int(os.environ.get("CLEANHOUSE_NETWORK_FINDINGS_LOOKBACK", "10000"))', backend)
        self.assertIn("NETWORK_FINDINGS_CACHE_SECONDS = 15.0", backend)
        self.assertIn("NETWORK_FINDINGS_RELATED_ID_LIMIT = 8", backend)
        self.assertIn("NETWORK_FINDINGS_DESTINATION_LIMIT = 8", backend)
        self.assertIn('"projection_window": "12mo"', backend)
        self.assertIn("[:min(NETWORK_PROJECTION_LIMIT, 100)]", backend)
        self.assertIn("findings: `${verb} grouped network findings.`", source)
        self.assertIn("No grouped findings.", source)

    def test_network_contract_exposes_boot_identity_and_vvault_readiness(self):
        backend = read_text("backend/api/cleanhouse.py")
        frontend = read_text("frontend/js/investigations.js")
        api_source = read_text("frontend/js/api-client.js")
        self.assertIn('"server_boot_id": NETWORK_SERVER_BOOT_ID', backend)
        self.assertIn('"vvault": _network_vvault_readiness()', backend)
        self.assertIn('return _network_error_contract("vvault_persistence_unavailable", status_code=503)', backend)
        self.assertIn("const NETWORK_SERVER_BOOT_STORAGE_KEY = 'cleanhouse.network.serverBootId';", frontend)
        self.assertIn("function observeNetworkServerBoot(response = {}, requestReason = '') {", frontend)
        self.assertIn("previousBootId === bootId ? 'page-reload' : 'server-restarted'", frontend)
        self.assertIn("query.set('require_vvault', '1')", api_source)

    def test_capture_failed_is_a_reason_label(self):
        source = read_text("frontend/js/investigations.js")
        self.assertRegex(source, r"capture_failed:\s*'Capture failed'")
        self.assertIn("capture_failed: { title: 'Capture failed'", source)
        self.assertIn("'Capture failed': { meaning: 'CleanHouse could not fully capture network history.', summary: 'Capture failed' }", source)
        self.assertIn("NETWORK_REASON_TAGS.has(normalized)", source)
        self.assertNotIn("capture_failed: 'capture_failed'", source)

    def test_runtime_reconnect_copy_uses_separate_health_line(self):
        js = read_text("frontend/js/investigations.js")
        html = read_text("frontend/investigations.html")
        css = read_text("frontend/css/investigations.css")

        self.assertNotIn("network-runtime-health", js)
        self.assertNotIn("network-runtime-health", html)
        self.assertNotIn(".network-runtime-health", css)
        self.assertNotIn("Runtime degraded. Reconnecting without reloading the page.", js)
        self.assertNotIn("runtimeHealth.hidden = false;", js)
        self.assertNotIn("runtimeHealth.textContent = 'Runtime degraded. Reconnecting without reloading the page.';", js)
        self.assertNotIn("networkRoute.textContent = 'Runtime degraded. Reconnecting without reloading the page. ' + message;", js)

    def test_timeline_uses_tab_local_projection_truth(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("if (networkDataHasEvents(projectionData))", source)
        self.assertIn("return networkTimelineDataWithSource(projectionData, projectionData?.summary?.timeline_source || 'saved');", source)
        self.assertIn("return cloneNetworkProjectionData(projectionData);", source)
        self.assertIn("return networkProjectionPlaceholderData('timeline', selectedRange);", source)
        self.assertNotIn("const live = networkTimelineLiveFallbackData();", source)
        self.assertNotIn("return projectionData || networkHeaderTableData() || {};", source)
        self.assertIn("view === 'timeline'", source)
        self.assertIn("data = networkTimelineBestData(settledProjection, { selectedRange });", source)

    def test_timeline_refreshes_when_header_live_table_evidence_arrives(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("function refreshNetworkTimelineDisplayIfVisible()", source)
        self.assertIn("if (!evidenceSource.startsWith('projection:')) {", source)
        self.assertIn("refreshNetworkTimelineDisplayIfVisible();", source)
        self.assertIn("submitNetworkHeaderEvidence('snapshot', errorData", source)
        self.assertIn("submitNetworkHeaderEvidence('live-packet', currentNetworkTableData", source)

    def test_network_shell_paints_before_projection_fetches(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("renderNetworkDisplay();", source)
        self.assertIn("function deferNetworkProjectionLoad(mode = networkViewMode, refresh = false)", source)
        self.assertIn("window.requestAnimationFrame(() => window.setTimeout(run, 0));", source)
        self.assertIn("function selectNetworkView(mode, options = {}) {", source)
        self.assertIn("renderNetworkDisplay();", source.split("function selectNetworkView(mode, options = {}) {", 1)[1])
        self.assertIn("if (projectionView) deferNetworkProjectionLoad(networkViewMode, Boolean(options.refresh));", source)

    def test_projection_loading_keeps_authoritative_state_in_render_model(self):
        source = read_text("frontend/js/investigations.js")
        body = source.split("function renderNetworkProjectionLoading(mode = networkViewMode) {", 1)[1].split("function deferNetworkProjectionLoad(", 1)[0]
        self.assertIn("networkCoordinatorSetProjectionLoading(view, selectedRange, effectiveFetchRange, networkHydrationEpoch, networkProjectionRequestId);", body)
        self.assertIn("renderNetworkDisplay();", body)
        self.assertNotIn("currentNetworkData =", body)
        self.assertNotIn("currentNetworkProjectionData =", body)

    def test_empty_projection_cannot_overwrite_last_good_timeline_cache(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("function rememberNetworkTimelineData(data, options = {}) {", source)
        self.assertIn("if (!networkDataHasEvents(data)) return;", source)
        self.assertIn("networkTimelineLastGoodMeta = {", source)
        self.assertIn("if (projectionView !== 'timeline' || networkDataHasEvents(nextProjectionData)) {", source)
        self.assertIn("networkProjectionCache[cacheKey] = cloneNetworkProjectionData(nextProjectionData);", source)

    def test_timeline_trend_projection_lookups_are_bounded_and_cached(self):
        source = read_text("backend/api/cleanhouse.py")
        self.assertIn("NETWORK_PROJECTION_CACHE_SECONDS = 8.0", source)
        self.assertIn("def _network_projection_cache_get(view: str, range_key: str) -> dict[str, Any] | None:", source)
        self.assertIn("def _network_projection_cache_set(view: str, range_key: str, payload: dict[str, Any]) -> None:", source)
        self.assertIn("cached = _network_projection_cache_get(\"timeline\", range_key)", source)
        self.assertIn("history_limit = _network_projection_history_limit(range_key)", source)
        self.assertIn("visible = _network_events_in_range(range_key, limit=history_limit)", source)
        self.assertIn("_stored_network_timeline_notables(limit=history_limit, start=start, end=end)", source)
        self.assertIn("_vvault_network_timeline_notables(range_key, start, end, limit=history_limit)", source)
        self.assertIn("_stored_network_timeline_gaps(limit=history_limit, start=start, end=end)", source)
        self.assertIn("_vvault_network_timeline_gaps(range_key, start, end, limit=history_limit)", source)
        self.assertIn("cached = _network_projection_cache_get(\"trend\", range_key)", source)
        self.assertIn("_vvault_network_trend_ticks(range_key, start, end, limit=history_limit)", source)
        self.assertIn("_vvault_network_trend_samples(start, end, limit=history_limit)", source)
        self.assertIn("_network_projection_cache_set(\"timeline\", range_key, payload)", source)
        self.assertIn("_network_projection_cache_set(\"trend\", range_key, payload)", source)

    def test_authoritative_snapshot_clears_recovered_capture_state_without_downgrading_provider(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("submitNetworkHeaderEvidence('snapshot', tableSnapshotData, { captureStatus: true });", source)
        provider_body = source.split("function updateNetworkWiresharkBranding(data = {}) {", 1)[1].split(
            "function setNetworkHeaderData(data = {}, options = {}) {", 1
        )[0]
        self.assertIn("if (!hasEvidence) return;", provider_body)

    def test_network_hydration_aborts_stale_requests_and_uses_canonical_snapshot(self):
        source = read_text("frontend/js/investigations.js")
        api_source = read_text("frontend/js/api-client.js")
        self.assertIn("let networkHydrationEpoch = 0;", source)
        self.assertIn("let networkSnapshotAbortController = null;", source)
        self.assertIn("let networkProjectionAbortController = null;", source)
        self.assertIn("let networkCoordinatorState = null;", source)
        self.assertIn("let networkSettledProjectionState = {", source)
        self.assertIn("function createNetworkCoordinatorState() {", source)
        self.assertIn("function networkCoordinatorRememberSnapshot(data, epoch = networkHydrationEpoch, requestId = networkSnapshotRequestId) {", source)
        self.assertIn("function networkCoordinatorSetProjectionLoading(view, selectedRange, effectiveFetchRange, epoch, requestId) {", source)
        self.assertIn("function abortNetworkHydrationRequests()", source)
        self.assertIn("networkSnapshotAbortController.abort();", source)
        self.assertIn("networkProjectionAbortController.abort();", source)
        self.assertIn("async function hydrateNetworkView(options = {}) {", source)
        self.assertIn("const epoch = ++networkHydrationEpoch;", source)
        self.assertIn("stopNetworkLiveUpdates();", source)
        self.assertIn("abortNetworkHydrationRequests();", source)
        self.assertIn("await loadNetworkHeaderSnapshot(refresh, { epoch, reason });", source)
        self.assertIn("await loadNetworkProjection(networkViewMode, refresh, { epoch });", source)
        self.assertIn("function resumeNetworkForegroundRendering(reason = 'resume') {", source)
        self.assertIn("if (wasSuspended || hadDeferredWork || networkVisibilityPendingHydration) {", source)
        self.assertIn("window.addEventListener('pageshow', event => {", source)
        self.assertIn("scheduleNetworkForegroundRendering('resume');", source)
        self.assertIn("scheduleNetworkForegroundRendering('pageshow');", source)
        self.assertIn("snapshot: true", api_source)
        self.assertIn("async getNetwork(options = false)", api_source)
        self.assertIn("async getNetworkProjection(view, range = '5s', options = false)", api_source)
        self.assertIn("window.CleanHouseAPI.getNetwork({ refresh, snapshot: true, signal });", source)
        self.assertIn("window.CleanHouseAPI.getNetworkProjection(projectionView, projectionRange, { refresh, signal });", source)
        self.assertIn("rememberNetworkSettledProjection(projectionView, selectedRange, nextProjectionData, epoch);", source)
        self.assertIn("networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId)", source)

    def test_timeline_range_controls_use_persisted_selected_range(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("function networkTimelineSelectedRangeMode(rangeKey = networkTimelineRangeMode) {", source)
        self.assertIn("activeRange: networkTimelineDisplayRangeMode(),", source)
        self.assertIn("const selectedTimelineRangeMode = networkTimelineSelectedRangeMode();", source)
        self.assertIn("const projectionTimelineRangeMode = networkTimelineDisplayRangeMode(selectedTimelineRangeMode);", source)
        self.assertIn("function selectNetworkRange(mode, options = {}) {", source)
        self.assertIn("persistNetworkTimelineRange(mode);", source)
        self.assertIn("renderNetworkToolbarContext();", source.split("function selectNetworkRange(mode, options = {}) {", 1)[1])
        self.assertIn("renderNetworkDisplay();", source.split("function selectNetworkRange(mode, options = {}) {", 1)[1])
        self.assertIn("deferNetworkProjectionLoad(networkViewMode, Boolean(options.refresh ?? true));", source)
        self.assertIn("selectNetworkRange(button.dataset.networkTimelineRange || '5s', { refresh: true });", source)

    def test_trend_5s_prefers_live_tick_composition(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("if (view === 'trend') {", source.split("function networkSettledProjectionData(view, range = networkTimelineRangeMode) {", 1)[1])
        self.assertIn("return networkTrendProjectionWithLive(settled.data, selectedRange);", source)
        self.assertIn("networkTrendProjectionWithLive(", source)
        self.assertIn("networkTimelineSelectedRangeMode()", source)
        self.assertIn("networkCoordinatorSelectedRange(projectionView);", source)
        self.assertIn("currentNetworkProjectionData = networkTrendProjectionWithLive(currentNetworkTrendBaseData, selectedRange);", source)

    def test_network_count_uses_real_total_and_tab_specific_body_labels(self):
        source = read_text("frontend/js/investigations.js")
        html = read_text("frontend/investigations.html")
        headline_section = source.split("function networkCountHeadlineText(mode = networkViewMode, data = null) {", 1)[1].split("function networkConnectionCountText(", 1)[0]
        self.assertIn("function networkCountHeadlineText(mode = networkViewMode, data = null)", source)
        self.assertIn("function networkHeadlineDataForMode(mode = networkViewMode)", source)
        self.assertIn("function renderNetworkToolbarContext()", source)
        self.assertIn("renderNetworkToolbarContext();", source)
        self.assertIn("id=\"network-toolbar-context\"", html)
        self.assertIn("const totalConnectionCount = Number(", source)
        self.assertIn("summaryCounts.connections ?? data.totalConnectionCount ?? currentNetworkHeaderData.totalConnectionCount", source)
        self.assertIn("if (resolvedMode === 'findings')", source)
        self.assertIn("return `${shownCount} findings.`;", source)
        self.assertIn("if (resolvedMode === 'table')", source)
        self.assertIn("const connectionCount = total > 0 ? total : shownCount;", source)
        self.assertIn("return `${connectionCount} active ${connectionCount === 1 ? 'connection' : 'connections'}.`;", source)
        self.assertIn("if (resolvedMode === 'trend')", source)
        self.assertIn("return `${shownCount} interpreted ${shownCount === 1 ? 'bucket' : 'buckets'} in the last ${timeviewLabel || 'selected window'}.`;", source)
        self.assertIn("if (resolvedMode === 'distribution')", source)
        self.assertIn("return `${appCount} active apps.`;", source)
        self.assertIn("if (resolvedMode === 'timeline')", source)
        self.assertIn("return `${shownCount} events in the last ${timeviewLabel || 'selected window'}.`;", source)
        self.assertIn("setText('network-message', networkCountHeadlineText(networkViewMode, model.headlineData));", source)
        self.assertIn("const totalConnectionCount = Number(currentNetworkHeaderData.totalConnectionCount || 0);", source)
        self.assertIn("const activeSocketCount = Number(currentNetworkHeaderData.activeSocketCount || 0);", source)
        self.assertIn("const activeConnectionCount = Number(currentNetworkHeaderData.activeConnectionCount || 0);", source)
        self.assertNotIn("displayedConnectionCount", source.split("function networkHeaderCurrentCount(now = Date.now())", 1)[1].split("function setNetworkHeaderData(", 1)[0])
        self.assertIn("const activeConnectionCount = totalCount > 0", source)
        self.assertIn(": Math.max(previousActiveCount, activeSocketCount);", source)
        self.assertNotIn("networkConnectionCountText(networkHeaderCurrentCount())", source)
        self.assertNotIn("network-trend-title", source)
        self.assertIn("if (resolvedMode === 'findings')", source)
        self.assertIn("const summaryCounts = data.summary && typeof data.summary.counts === 'object' ? data.summary.counts : {};", source)
        self.assertIn("const displayedEventCount = Number(data.event_count ?? data.activeConnectionCount ?? (hasEvents ? events.length : currentNetworkHeaderData.displayedConnectionCount));", source)
        self.assertIn("const capped = displayedCount >= NETWORK_LIVE_EVENT_LIMIT && (totalCount === 0 || totalCount > displayedCount);", source)
        self.assertNotIn("networkCountHeadlineText('table', { events, total_connection_count: currentNetworkHeaderData.totalConnectionCount, displayed_connection_count: currentNetworkHeaderData.displayedConnectionCount, displayed_connection_count_capped: currentNetworkHeaderData.displayedConnectionCountCapped })", source)
        self.assertNotIn("networkCountHeadlineText('findings', { events })", source)
        self.assertNotIn("networkCountHeadlineText('trend', { events })", source)
        self.assertNotIn("networkCountHeadlineText('distribution', { events })", source)
        self.assertNotIn("networkCountHeadlineText('timeline', { events: timelineEvents })", source)
        self.assertIn("data = settledProjection || networkProjectionPlaceholderData('findings', selectedRange);", source)
        self.assertIn("return buildNetworkRenderModel(mode).headlineData;", source)
        self.assertNotIn("total_connection_count: currentNetworkHeaderData.totalConnectionCount || 0,", headline_section)
        self.assertNotIn("displayed_connection_count_capped: Boolean(currentNetworkHeaderData.displayedConnectionCountCapped),", headline_section)
        self.assertNotIn("networkRangeControlsHtml('Trend range') +", source)
        self.assertNotIn("networkTimelineRangeControlsHtml() +", source)

    def test_trend_uses_versioned_interpretation_controls_and_preserves_missing_buckets(self):
        backend = read_text("backend/api/cleanhouse.py")
        source = read_text("frontend/js/investigations.js")
        html = read_text("frontend/investigations.html")
        css = read_text("frontend/css/investigations.css")

        self.assertIn('NETWORK_TREND_INTERPRETATION_SCHEMA = "cleanhouse.network.trend.interpretation.v1"', backend)
        self.assertIn('NETWORK_TREND_RULE_VERSION = "network-trend-rationalization.v1"', backend)
        self.assertIn("def _network_trend_interpretation_from_event", backend)
        self.assertIn("def _network_trend_interpretation_buckets", backend)
        self.assertIn('"zero_means": "observed_bucket_without_matching_signal"', backend)
        self.assertIn('"missing_means": "no_retained_evidence_for_bucket"', backend)
        self.assertIn("const NETWORK_TREND_SERIES = Object.freeze([", source)
        self.assertIn("function networkTrendDataset(events)", source)
        self.assertIn("function networkTrendGraphHtml(dataset)", source)
        self.assertIn("function networkTrendChartHtml(dataset)", source)
        self.assertIn('class="network-trend-bucket is-gap"', source)
        self.assertNotIn('class="network-trend-bar is-empty" style="height:2%"', source)
        self.assertIn('data-network-trend-display="graph"', html)
        self.assertIn('data-network-trend-display="chart"', html)
        self.assertIn("#network #network-results:has(.network-trend-window)", css)
        self.assertIn("height: calc(100% - 10px);", css.split(".network-trend-window {", 1)[1].split("}", 1)[0])

    def test_render_model_reads_selected_range_and_coordinator_snapshot(self):
        source = read_text("frontend/js/investigations.js")
        body = source.split("function buildNetworkRenderModel(mode = networkViewMode) {", 1)[1].split("function networkHeadlineDataForMode(", 1)[0]
        self.assertIn("const coordinator = syncNetworkCoordinatorUiState();", body)
        self.assertIn("const selectedRange = projectionView ? networkCoordinatorSelectedRange(projectionView) : '';", body)
        self.assertIn("const effectiveFetchRange = projectionView ? networkCoordinatorEffectiveFetchRange(projectionView, selectedRange) : '';", body)
        self.assertIn("const snapshotTableData = networkCoordinatorSnapshotTableData();", body)
        self.assertIn("data = settledProjection || networkProjectionPlaceholderData('findings', selectedRange);", body)
        self.assertIn("data = networkTimelineBestData(settledProjection, { selectedRange });", body)
        self.assertIn("data = settledProjection || networkTrendProjectionWithLive(currentNetworkTrendBaseData || networkProjectionPlaceholderData('trend', selectedRange), selectedRange);", body)
        self.assertIn("String(coordinator.snapshot?.version || 0),", body)

    def test_network_table_api_uses_bounded_unenriched_history_read(self):
        source = read_text("backend/api/cleanhouse.py")
        body = source.split("def _network_current_packet_payload() -> tuple[dict[str, Any], int]:", 1)[1].split("@bp.route(\"/cleanhouse/network/projection\"", 1)[0]
        self.assertIn("limit=min(NETWORK_EVIDENCE_LOOKBACK, 200)", body)
        self.assertIn("enrich_unknown=False", body)

    def test_network_empty_buffer_uses_collector_truth_not_runtime_readiness(self):
        backend = read_text("backend/api/cleanhouse.py")
        frontend = read_text("frontend/js/investigations.js")
        self.assertIn("NETWORK_UI_STATES = {\"READY\", \"CAPTURING\", \"NO_DATA\", \"WARMING\", \"ERROR\", \"CAPTURE_BLOCKED\"}", backend)
        self.assertIn("def _network_runtime_probe_state(events_payload: list[dict[str, Any]]) -> str:", backend)
        self.assertIn("return \"CAPTURING\" if events_payload else \"NO_DATA\"", backend)
        self.assertIn("def _network_collector_contract(health: dict[str, Any] | None) -> tuple[str, str]:", backend)
        self.assertIn("def _network_apply_collector_truth(payload: dict[str, Any], health: dict[str, Any] | None) -> dict[str, Any]:", backend)
        self.assertNotIn("readiness = _runtime_readiness_payload()", backend.split("def _network_runtime_probe_state", 1)[1].split("def _app_icon_cache_dir", 1)[0])
        self.assertIn("NETWORK_CONTRACT_STATES = new Set(['READY', 'CAPTURING', 'NO_DATA', 'WARMING', 'ERROR', 'CAPTURE_BLOCKED']);", frontend)
        self.assertIn("function networkTableEmptyStateText(data = {}) {", frontend)
        self.assertIn("return 'Loading live network packets';", frontend)
        self.assertIn("submitNetworkHeaderEvidence('live-status', startupPayload, { captureStatus: true, source: 'status' });", frontend)
        self.assertIn("function networkTabViewState(renderModel = null) {", frontend)
        self.assertIn("function networkTabLoadingCopy(mode = networkViewMode, phase = networkPagePhase) {", frontend)
        self.assertIn("function networkTabEmptyCopy(mode = networkViewMode) {", frontend)

    def test_wireshark_attribution_is_permanent_and_live_state_is_truthful(self):
        backend = read_text("backend/api/cleanhouse.py")
        frontend = read_text("frontend/js/investigations.js")
        html = read_text("frontend/investigations.html")
        self.assertIn('id="network-provider"', html)
        self.assertIn('aria-label="Powered by Wireshark — verifying"', html)
        self.assertIn('data-provider-state="verifying"', html)
        self.assertIn('payload["powered_by_wireshark"] = bool(', backend)
        self.assertIn("function updateNetworkWiresharkBranding(data = {}) {", frontend)
        self.assertIn("provider.dataset.providerState = state;", frontend)
        self.assertIn("provider.setAttribute('aria-label', `Powered by Wireshark — ${state}`);", frontend)
        self.assertNotIn("provider.hidden = !powered;", frontend)

    def test_network_table_live_updates_are_buffered_and_cadenced(self):
        source = read_text("frontend/js/investigations.js")
        css = read_text("frontend/css/investigations.css")
        self.assertIn("let networkTableFlushTimer = null;", source)
        self.assertIn("let networkTableUiBuffer = [];", source)
        self.assertIn("let networkRenderSuspended = false;", source)
        self.assertIn("let networkVisibilityPendingHydration = false;", source)
        self.assertIn("let networkDeferredRenderFlags = {", source)
        self.assertIn("let networkTablePinnedRowSnapshot = null;", source)
        self.assertIn("let networkHeaderRenderTimer = null;", source)
        self.assertIn("let networkHeaderRenderPending = false;", source)
        self.assertIn("const NETWORK_TABLE_DOM_ROW_LIMIT = 120;", source)
        self.assertIn("const NETWORK_TABLE_FLUSH_MS = 180;", source)
        self.assertIn("const NETWORK_HEADER_FLUSH_MS = 500;", source)
        self.assertIn("function networkShouldSuspendDomWork() {", source)
        self.assertIn("function suspendNetworkRenderWork() {", source)
        self.assertIn("function scheduleNetworkForegroundRendering(reason = 'resume') {", source)
        self.assertIn("function scheduleNetworkTableFlush() {", source)
        self.assertIn("function flushNetworkTableRender(options = {}) {", source)
        self.assertIn("function scheduleNetworkHeaderRender() {", source)
        self.assertIn("function flushNetworkHeaderRender(options = {}) {", source)
        self.assertIn("return networkShouldSuspendDomWork() || networkHidden || networkViewMode !== 'table';", source)
        self.assertIn("if (networkHeaderRenderPending) {", source.split("function setActionSidebarOpen(open) {", 1)[1])
        self.assertIn("flushNetworkHeaderRender({ force: true });", source.split("function setActionSidebarOpen(open) {", 1)[1])
        self.assertIn("if (networkViewMode === 'table' && networkTableUiBuffer.length) {", source.split("function setActionSidebarOpen(open) {", 1)[1])
        self.assertIn("flushNetworkTableRender({ force: true });", source.split("function setActionSidebarOpen(open) {", 1)[1])
        header_body = source.split("function submitNetworkHeaderEvidence(source, payload = {}, options = {}) {", 1)[1].split("function networkHeaderTableData()", 1)[0]
        self.assertIn("if (evidenceSource === 'live-packet') {", header_body)
        self.assertIn("scheduleNetworkHeaderRender();", header_body)
        self.assertIn("return;", header_body)
        append_body = source.split("function appendNetworkLiveEvent(event, eventMeta = {}) {", 1)[1].split("function renderNetworkUnavailable(", 1)[0]
        self.assertIn("mergeNetworkLiveEventIntoTableData(data, canonicalEvent, observedAt);", append_body)
        merge_body = source.split("function mergeNetworkLiveEventIntoTableData(data = {}, event = {}, observedAt = Date.now()) {", 1)[1].split("function appendNetworkLiveEvent(", 1)[0]
        self.assertIn("const connectionKey = networkConnectionIdentityKey(event);", merge_body)
        self.assertIn("events.findIndex(item => networkConnectionIdentityKey(item) === connectionKey)", merge_body)
        self.assertIn("networkTableUiBuffer.push(networkEvidenceEntityId(mergedEvent));", append_body)
        self.assertIn("if (networkTableUiBuffer.length > NETWORK_TABLE_DOM_ROW_LIMIT) {", append_body)
        self.assertIn("networkTableHiddenPacketCount = Math.min(networkTableHiddenPacketCount + 1, NETWORK_LIVE_EVENT_LIMIT);", append_body)
        self.assertIn("if (networkShouldSuspendDomWork()) {", append_body)
        self.assertIn("networkVisibilityPendingHydration = true;", append_body)
        self.assertIn("scheduleNetworkTableFlush();", append_body)
        self.assertNotIn("appendNetworkLiveTableRow(event)", append_body)
        table_body = source.split("function renderNetworkTable(events, data = {}) {", 1)[1].split("function networkTableRowHtml(", 1)[0]
        self.assertIn("networkTableVisibleRows(events, {", table_body)
        self.assertIn("limit: NETWORK_TABLE_DOM_ROW_LIMIT,", table_body)
        self.assertIn("pinnedEntityId: networkTablePinnedEntityId,", table_body)
        self.assertIn("const pinnedSnapshot = pinnedEntityId ? syncNetworkTablePinnedSnapshot(rows) : null;", source)
        self.assertIn("if (pinnedIndex < 0 && pinnedSnapshot) {", source)
        self.assertIn("syncNetworkTablePinnedSnapshot(currentNetworkTableData.events);", source)
        self.assertIn("const isPinnedStale = Boolean(isPinned && event?.__networkPinnedStale);", source)
        self.assertIn("network-row-pinned-stale", source)
        self.assertIn(".network-table tbody tr.network-row-pinned-stale {", css)
        self.assertIn("if (networkShouldSuspendDomWork()) {", source.split("function renderNetworkDisplay() {", 1)[1])
        self.assertIn("markNetworkDeferredRender(networkViewMode === 'table' ? 'table' : 'display');", source)
        self.assertIn("window.addEventListener('focus', () => {", source)
        self.assertIn("window.addEventListener('blur', () => {", source)
        self.assertIn("window.addEventListener('pageshow', event => {", source)
        self.assertIn("window.addEventListener('pagehide', () => {", source)

    def test_ctrl_render_snapshot_reuses_resolved_event_and_technical_payload(self):
        source = read_text("frontend/js/investigations.js")
        self.assertIn("let evidenceCommandSnapshot = null;", source)
        self.assertIn("function currentEvidenceCommandSnapshot(context = evidenceCommandContext) {", source)
        self.assertIn("function buildEvidenceCommandSnapshot(context = {}, options = {}) {", source)
        self.assertIn("const selectedEvent = mergedContext.__selectedEvent || resolveNetworkEvidenceEvent(mergedContext);", source)
        self.assertIn("const subject = buildNetworkCtrlSubject(mergedContext, descriptor, selectedEvent);", source)
        self.assertIn("const routeTarget = buildNetworkCtrlRouteTarget(mergedContext, subject);", source)
        self.assertIn("technicalEvents,", source)
        self.assertIn("technicalData,", source)
        self.assertIn("const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context);", source)
        self.assertIn("const event = snapshotState.selectedEvent || resolveNetworkEvidenceEvent(context);", source)
        self.assertIn("const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context, { networkData });", source)
        self.assertIn("networkTechnicalDetailsHtml(snapshotState.technicalData || {}, snapshotState.technicalEvents || [])", source)
        self.assertIn("function evidenceSidebarEssentialHtml(context = {}, snapshot = null) {", source)
        self.assertIn("function clearActionSidebarDeferredDetails() {", source)
        self.assertIn("function resetActionSidebarDeferredDetails() {", source)


if __name__ == "__main__":
    unittest.main()
