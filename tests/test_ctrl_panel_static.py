import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_investigations_js() -> str:
    return (ROOT / "frontend" / "js" / "investigations.js").read_text(encoding="utf-8")


class CtrlPanelStaticTests(unittest.TestCase):
    def test_ctrl_outside_click_is_close_only_and_capture_phase(self):
        source = read_investigations_js()
        handler = re.search(
            r"function handleActionSidebarOutsideClick\(event\) \{(?P<body>.*?)\n\}",
            source,
            re.S,
        )
        self.assertIsNotNone(handler, "ctrl outside-click handler must exist")
        body = handler.group("body")

        self.assertIn("Product lock: outside-click dismissal is close-only", body)
        self.assertIn("if (!actionSidebarOpen) return;", body)
        self.assertIn("sidebar.contains(target)", body)
        self.assertIn("toggle.contains(target)", body)
        self.assertIn("event.preventDefault();", body)
        self.assertIn("event.stopPropagation();", body)
        self.assertIn("event.stopImmediatePropagation();", body)
        self.assertIn("setActionSidebarOpen(false);", body)
        self.assertNotIn("data-evidence-surface", body)
        self.assertIsNotNone(
            re.search(
                r"document\.addEventListener\('click', event => \{.*?handleActionSidebarOutsideClick\(event\);.*?\}, true\);",
                source,
                re.S,
            ),
            "outside-click dismissal must stay capture-phase",
        )

    def test_ctrl_close_invalidates_async_work_without_body_rerender(self):
        source = read_investigations_js()
        setter = re.search(
            r"function setActionSidebarOpen\(open\) \{(?P<body>.*?)\n\}",
            source,
            re.S,
        )
        self.assertIsNotNone(setter, "ctrl open/close setter must exist")
        body = setter.group("body")

        self.assertIn("if (actionSidebarOpen) {", body)
        self.assertIn("syncActionSidebarShell();", body)
        self.assertIn("scheduleActionSidebarRender();", body)
        self.assertIn("actionSidebarRequestEpoch += 1;", body)
        self.assertIn("evidenceCommandLoading = false;", body)
        self.assertIn("evidenceInsightLoading = false;", body)
        self.assertIn("evidenceInsightRequestKey = '';", body)
        self.assertIn("syncActionSidebarShell();", body)

        close_branch = body.split("if (actionSidebarOpen) {", 1)[1].split("syncActionSidebarShell();", 1)[1]
        self.assertNotIn("renderActionSidebar();", close_branch)
        self.assertIn("const requestEpoch = ++actionSidebarRequestEpoch;", source)
        self.assertIn("requestEpoch !== actionSidebarRequestEpoch", source)

    def test_network_raw_metadata_moves_to_ctrl_sidebar(self):
        source = read_investigations_js()
        self.assertNotIn("Event metadata", source)
        self.assertIn("Technical Details", source)
        self.assertIn("networkTechnicalDetailsHtml(", source)
        self.assertIn('id="network-raw-metadata"', source)

        render_body = source.split("function renderNetworkDisplay() {", 1)[1].split("function renderNetworkFindings(", 1)[0]
        self.assertIn("results.innerHTML = (renderers[networkViewMode] || renderNetworkTable)(filteredEvents, data);", render_body)
        self.assertNotIn("network-raw-metadata", render_body)
        self.assertNotIn("networkTechnicalDetailsHtml(", render_body)

        technical_body = source.split("function networkTechnicalDetailsHtml(data, events, open = false) {", 1)[1].split("function refreshNetworkMetadataFooter()", 1)[0]
        self.assertIn("Technical Details", technical_body)
        self.assertIn("network-raw-metadata", technical_body)

        sidebar_body = source.split("function evidenceSidebarSections(context = {}, networkData = {}, snapshot = null) {", 1)[1].split("function renderEvidenceActionSidebar()", 1)[0]
        self.assertIn("const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context, { networkData });", sidebar_body)
        self.assertNotIn("resolveNetworkEvidenceEvent(context)", sidebar_body)
        self.assertIn("networkTechnicalDetailsHtml(snapshotState.technicalData || {}, snapshotState.technicalEvents || [])", sidebar_body)

    def test_table_ctrl_open_does_not_auto_run_insight(self):
        source = read_investigations_js()
        body = source.split("function maybeRequestCtrlInsightForSelection(context = {}) {", 1)[1].split("function executeEvidenceAction(", 1)[0]

        self.assertIn("if (normalizedCtrlText(sourceView) === 'table') return;", body)

    def test_bare_control_key_toggles_ctrl_without_chords_or_typing(self):
        source = read_investigations_js()
        self.assertIn(
            "Product lock: bare Ctrl toggles ctrl; chords, repeats, and editable targets never toggle it.",
            source,
        )
        self.assertIn("if (event.key === 'Control') {", source)
        self.assertIn("if (event.repeat) {", source)
        self.assertIn("controlKeyChordActive = true;", source)
        self.assertIn("if (event.ctrlKey) controlKeyChordActive = true;", source)
        self.assertIn("if (event.key !== 'Control') return;", source)
        self.assertIn("target.closest('input, textarea, select, [contenteditable=\"true\"]')", source)
        self.assertIn(
            "editableTarget || controlKeyChordActive || event.altKey || event.metaKey || event.shiftKey",
            source,
        )
        self.assertIn("setActionSidebarOpen(!actionSidebarOpen);", source)
        self.assertIn("setActionSidebarOpen(false);", source)

    def test_table_row_click_opens_ctrl_without_forcing_network_rerender(self):
        source = read_investigations_js()
        open_body = source.split("function openEvidenceActions(", 1)[1].split("function requestEvidenceInsight(", 1)[0]
        bind_body = source.split("function bindNetworkEvidenceRows(context = null) {", 1)[1].split("function bindNetworkEvidenceElements(", 1)[0]

        self.assertIn("setActionSidebarOpen(true);", open_body)
        self.assertNotIn("renderNetworkDisplay();", open_body)
        self.assertIn("setPinnedNetworkTableSelection(normalizedEntityId, findNetworkTableEventByEntityId(normalizedEntityId));", open_body)
        self.assertIn("flushNetworkTableRender({ force: true });", open_body)
        self.assertIn("openEvidenceActions(descriptor);", bind_body)
        self.assertNotIn("renderNetworkDisplay();", bind_body)
        self.assertIn("scheduleActionSidebarRender();", open_body)

    def test_table_selection_stays_pinned_until_blank_outside_click(self):
        source = read_investigations_js()
        clear_body = source.split("function clearPinnedNetworkTableSelection() {", 1)[1].split("function handleNetworkTablePinnedOutsideClick(event) {", 1)[0]
        outside_body = source.split("function handleNetworkTablePinnedOutsideClick(event) {", 1)[1].split("function currentEvidenceCommandNetworkData()", 1)[0]

        self.assertIn("setPinnedNetworkTableSelection('');", clear_body)
        self.assertIn("flushNetworkTableRender({ force: true });", clear_body)
        self.assertIn("if (networkViewMode !== 'table' || !networkTablePinnedEntityId) return;", outside_body)
        self.assertIn("if (!network || network.hidden) return;", outside_body)
        self.assertIn("if (table && target.closest('tr.network-row-evidence')) return;", outside_body)
        self.assertIn("if (table && target.closest('.network-column-resizer')) return;", outside_body)
        self.assertIn("if (target.closest('#action-sidebar') || target.closest('#action-sidebar-toggle')) return;", outside_body)
        self.assertIn("clearPinnedNetworkTableSelection();", outside_body)
        self.assertIn("handleNetworkTablePinnedOutsideClick(event);", source)

    def test_ctrl_uses_cached_snapshot_for_resolved_table_selection(self):
        source = read_investigations_js()
        open_body = source.split("function openEvidenceActions(", 1)[1].split("function currentEvidenceCommandNetworkData()", 1)[0]
        render_body = source.split("function renderEvidenceActionSidebar() {", 1)[1].split("function syncActionSidebarShell()", 1)[0]
        insight_body = source.split("function evidenceInsightHtml(context, snapshot = null) {", 1)[1].split("function buildNetworkCtrlRouteTarget(", 1)[0]

        self.assertIn("const nextSnapshot = buildEvidenceCommandSnapshot(context, {", open_body)
        self.assertIn("descriptor: { ...params, relatedIds: boundedRelatedIds, assessmentRefs: boundedAssessmentRefs },", open_body)
        self.assertIn("setCurrentEvidenceCommandSnapshot(nextSnapshot);", open_body)
        self.assertIn("const snapshot = evidenceCommandContext", render_body)
        self.assertIn("networkCtrlHeaderHtml(evidenceCommandContext, snapshot)", render_body)
        self.assertIn("evidenceSidebarSections(evidenceCommandContext, networkData, snapshot)", render_body)
        self.assertIn("const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context);", insight_body)

    def test_ctrl_renders_canonical_security_assessment_rationale(self):
        source = read_investigations_js()
        insight_body = source.split("function evidenceInsightHtml(context, snapshot = null) {", 1)[1].split("function buildNetworkCtrlRouteTarget(", 1)[0]

        self.assertIn("context?.__selectedAssessment", insight_body)
        self.assertIn("resolveNetworkAssessment(context || {})", insight_body)
        self.assertIn("Security assessment", insight_body)
        self.assertIn("assessment?.rationale", insight_body)
        self.assertIn("assessment.category", insight_body)
        self.assertIn("assessment.severity", insight_body)
        self.assertIn("assessment.confidence.label", insight_body)
        self.assertIn("assessment.confidence.score", insight_body)
        self.assertIn("assessment.lifecycle", insight_body)
        self.assertIn("assessmentRule", insight_body)

    def test_network_evidence_selection_preserves_owner_and_destination_identity(self):
        source = read_investigations_js()
        attributes_body = source.split("function networkEvidenceAttributes(event, sourceView = networkViewMode || 'table') {", 1)[1].split("function networkConnectionIdentityFields", 1)[0]
        descriptor_body = source.split("function evidenceActionDescriptorFromRow(row) {", 1)[1].split("function evidenceAttributes(", 1)[0]
        open_body = source.split("function openEvidenceActions(", 1)[1].split("function clearPinnedNetworkTableSelection", 1)[0]

        self.assertIn("data-evidence-owner", attributes_body)
        self.assertIn("data-evidence-destination", attributes_body)
        self.assertIn("row.dataset.evidenceOwner", descriptor_body)
        self.assertIn("row.dataset.evidenceDestination", descriptor_body)
        self.assertIn("app_name: params.owner", open_body)
        self.assertIn("destination: params.destination", open_body)
        header_body = source.split("function resolveCtrlHeaderAppName(context = {}, selectedEvent = null) {", 1)[1].split("function networkCtrlHeaderHtml", 1)[0]
        self.assertIn("resolveCtrlEvidenceAppName(context)", header_body)

    def test_ctrl_resolved_render_defers_nonessential_body_sections(self):
        source = read_investigations_js()
        render_body = source.split("function renderEvidenceActionSidebar() {", 1)[1].split("function syncActionSidebarShell()", 1)[0]
        essential_body = source.split("function evidenceSidebarEssentialHtml(context = {}, snapshot = null) {", 1)[1].split("function evidenceSidebarSections(", 1)[0]
        schedule_body = source.split("function scheduleActionSidebarRender() {", 1)[1].split("function scheduleActionSidebarDeferredDetails(", 1)[0]
        deferred_body = source.split("function scheduleActionSidebarDeferredDetails(requestId = actionSidebarDeferredRenderRequestId) {", 1)[1].split("function buildEvidenceCommandSnapshot(", 1)[0]
        render_sidebar_body = source.split("function renderActionSidebar() {", 1)[1].split("function setActionSidebarOpen(open) {", 1)[0]

        self.assertIn("let actionSidebarDeferredDetailsReady = false;", source)
        self.assertIn("let actionSidebarDeferredRenderRequestId = 0;", source)
        self.assertIn("function scheduleActionSidebarDeferredDetails(requestId = actionSidebarDeferredRenderRequestId) {", source)
        self.assertIn("window.requestAnimationFrame(() => {", source)
        self.assertIn("actionSidebarDeferredTimer = window.setTimeout(() => {", source)
        self.assertIn("actionSidebarDeferredDetailsReady = true;", source)
        self.assertIn("actionSidebarDeferredDetailsReady", render_body)
        self.assertIn("evidenceSidebarEssentialHtml(evidenceCommandContext, snapshot)", render_body)
        self.assertIn("scheduleActionSidebarDeferredDetails(actionSidebarDeferredRenderRequestId);", render_body)
        self.assertIn("Loading control details…", essential_body)
        self.assertIn("function scheduleActionSidebarRender() {", source)
        self.assertIn("if (networkShouldSuspendDomWork()) {", schedule_body)
        self.assertIn("markNetworkDeferredRender('sidebar');", schedule_body)
        self.assertIn("if (networkShouldSuspendDomWork()) {", deferred_body)
        self.assertIn("markNetworkDeferredRender('sidebar');", deferred_body)
        self.assertIn("if (networkShouldSuspendDomWork()) {", render_sidebar_body)
        self.assertIn("markNetworkDeferredRender('sidebar');", render_sidebar_body)

    def test_ctrl_action_menu_uses_mee_groups_and_marks_inapplicable_actions(self):
        source = read_investigations_js()
        css = (ROOT / "frontend" / "css" / "investigations.css").read_text(encoding="utf-8")
        catalog_body = source.split("function networkCtrlActionCatalog(subject, context = {}) {", 1)[1].split("function networkCtrlGroupedActions(actions = [])", 1)[0]
        sections_body = source.split("function evidenceSidebarSections(context = {}, networkData = {}, snapshot = null) {", 1)[1].split("function renderEvidenceActionSidebar()", 1)[0]

        self.assertIn("const CTRL_ACTION_GROUPS = [", source)
        self.assertIsNotNone(re.search(r"label: 'Monitoring'.*?label: 'Evidence'.*?label: 'Enforcement'", source, re.S))
        self.assertIn("function networkCtrlActionApplicability(actionId, subject = {}, context = {}) {", source)
        self.assertIn("function networkCtrlSubjectHasBlockTarget(subject = {}, context = {}) {", source)
        self.assertIn("function networkCtrlSubjectHasQuarantineTarget(subject = {}, context = {}) {", source)
        self.assertIn("function networkCtrlSubjectCanAllow(subject = {}, context = {}) {", source)
        self.assertIn("if (!action) return { ...item, enabled: false, disabled_reason: 'Backend capability unavailable.' };", catalog_body)
        self.assertIn("enabled: item.enabled && action.enabled !== false,", catalog_body)
        self.assertIn("(action.enabled ? '' : ' disabled')", sections_body)
        self.assertIn("networkCtrlGroupedActions(actions).map(group", sections_body)
        self.assertIn("action-sidebar-action-group-title", sections_body)
        self.assertIn(".action-sidebar-action-group", css)
        self.assertIn(".action-sidebar-action-group-title", css)
        self.assertIn(".action-sidebar-action-btn:disabled", css)


if __name__ == "__main__":
    unittest.main()
