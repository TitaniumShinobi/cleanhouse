/* CleanHouse Monitor Dashboard */

let autoRefreshTimer = null;
let currentSessionId = null;
let _lastTimelineEntries = [];
let _lastAlerts = [];
let _lastFileEvents = [];
let _lastReceipt = null;
let _lastReceipts = [];
let _lastReports = [];
let _lastApprovalQueue = [];
let _lastReceiptReplays = {};
let _lastReceiptBundles = {};
let _lastWorkstation = null;
let _lastPrimaryIntervention = null;
let _lastContinuityProvenance = null;
let _lastCollectorManifest = null;
let _lastLineageGraph = null;
let _lastRollbackReplayState = null;
let _lastOperatorVerification = null;
let _notifiedNotificationIds = new Set();
let _dashboardNotificationsEnabled = false;
let _browserNotificationWindowStart = 0;
let _browserNotificationCount = 0;
let _backendDisconnectCount = 0;
let _lastWorkstationOkAt = null;
let _pendingDashboardFocus = null;
let _activeLoginReportId = '';
const OPERATOR_STATE_KEY = 'cleanhouse.operatorState.v1';
const BROWSER_NOTIFICATION_WINDOW_MS = 30000;
const BROWSER_NOTIFICATION_MAX_PER_WINDOW = 3;

document.addEventListener('DOMContentLoaded', () => {
    _pendingDashboardFocus = readDashboardDeepLink();
    restoreOperatorState();
    applyDashboardDeepLinkToInputs();
    initOperatorSessionInput();
    renderRuntimeIndicator('unknown', 'waiting for first runtime poll');
    loadSessions();
    if (document.getElementById('auto-refresh').checked) {
        toggleAutoRefresh();
    }
});

function restoreOperatorState() {
    const state = readOperatorState();
    if (!state) return;
    const sessionInput = document.getElementById('operator-session-input');
    if (sessionInput && state.session_id) {
        sessionInput.value = state.session_id;
        currentSessionId = state.session_id;
    }
    setInputValue('objective-text', state.objective_text);
    setInputValue('objective-scope', state.objective_scope);
    setInputValue('objective-context', state.objective_context);
    setInputValue('objective-tool', state.objective_tool);
}

function initOperatorSessionInput() {
    const input = document.getElementById('operator-session-input');
    if (input && !input.value) {
        input.value = generateSessionId();
    }
}

function readDashboardDeepLink() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const sessionId = (params.get('session_id') || '').trim();
        const notificationId = (params.get('notification_id') || '').trim();
        const loginReportId = (params.get('login_report_id') || params.get('report_id') || '').trim();
        if (loginReportId) {
            _activeLoginReportId = loginReportId;
        }
        if (!sessionId && !notificationId && !loginReportId) return null;
        return { session_id: sessionId, notification_id: notificationId, login_report_id: loginReportId };
    } catch (e) {
        return null;
    }
}

function applyDashboardDeepLinkToInputs() {
    if (!_pendingDashboardFocus || !_pendingDashboardFocus.session_id) return;
    currentSessionId = _pendingDashboardFocus.session_id;
    const sessionInput = document.getElementById('operator-session-input');
    if (sessionInput) {
        sessionInput.value = currentSessionId;
    }
    persistOperatorState({ session_id: currentSessionId });
}

async function loadSessions() {
    const sel = document.getElementById('session-select');
    try {
        const data = await window.CleanHouseAPI.getIntents();
        const intents = data.intents || [];
        sel.innerHTML = '<option value="">— Select session —</option>';
        for (const intent of intents) {
            const opt = document.createElement('option');
            opt.value = intent.id;
            const label = intent.text
                ? intent.text.substring(0, 60) + (intent.text.length > 60 ? '...' : '')
                : '(no text)';
            opt.textContent = `${label} [${intent.scope || 'no scope'}]`;
            sel.appendChild(opt);
        }
        const stored = readOperatorState();
        const restoredSession = stored?.session_id || currentSessionId || '';
        if (restoredSession) {
            ensureSessionOption(restoredSession, restoredSession + ' [operator]');
            sel.value = restoredSession;
            onSessionChange();
        } else if (intents.length > 0) {
            sel.value = intents[0].id;
            onSessionChange();
        } else {
            currentSessionId = document.getElementById('operator-session-input')?.value || generateSessionId();
            renderSessionBar({ session_id: currentSessionId, status: 'stopped' });
        }
    } catch (e) {
        sel.innerHTML = '<option value="">— Failed to load sessions —</option>';
        setStatus('degraded', 'Collector unavailable: could not fetch intents');
    }
}

function onSessionChange() {
    const sel = document.getElementById('session-select');
    currentSessionId = sel.value;
    const sessionInput = document.getElementById('operator-session-input');
    if (sessionInput && currentSessionId) {
        sessionInput.value = currentSessionId;
        persistOperatorState({ session_id: currentSessionId });
    }
    const btn = document.getElementById('report-btn');
    if (currentSessionId) {
        btn.disabled = false;
        refreshAll();
    } else {
        btn.disabled = true;
        clearPanels();
        setStatus('clear', 'Select a session to begin monitoring.');
    }
}

async function refreshAll() {
    const tasks = [fetchEvents(), fetchNativeReports()];
    if (currentSessionId) {
        tasks.push(fetchTimeline(currentSessionId), fetchAlerts(currentSessionId), fetchReceiptScope(currentSessionId), fetchWorkstation(currentSessionId), fetchTier1Surfaces(currentSessionId));
    } else {
        tasks.push(fetchTier1Surfaces(null));
    }
    await Promise.all(tasks);
}

async function fetchTimeline(sessionId) {
    const body = document.getElementById('tl-body');
    try {
        const data = await window.CleanHouseAPI.buildTimeline(sessionId);
        const timelines = data.timelines || [];
        const entries = Array.isArray(data.entries)
            ? data.entries
            : (timelines.length > 0 ? timelines[0].entries || [] : []);
        _lastTimelineEntries = entries;
        renderTimeline(entries);
        updateStatus(entries, []);
    } catch (e) {
        body.innerHTML = '<div class="error-state">Failed to load timeline: ' + e.message + '</div>';
        setStatus('degraded', 'Timeline unavailable: ' + (e.message || 'unknown error'));
    }
}

async function fetchEvents() {
    const body = document.getElementById('fs-events-body');
    try {
        const events = await window.CleanHouseAPI.getEvents(50);
        _lastFileEvents = Array.isArray(events) ? events : [];
        renderFileEvents(_lastFileEvents);
    } catch (e) {
        body.innerHTML = '<div class="error-state">Failed to load filesystem events: ' + e.message + '</div>';
        setStatus('degraded', 'Filesystem events unavailable: ' + (e.message || 'unknown error'));
    }
}

async function fetchAlerts(sessionId) {
    const body = document.getElementById('alert-body');
    try {
        const data = await window.CleanHouseAPI.getAlerts(sessionId);
        const alerts = data.alerts || [];
        _lastAlerts = alerts;
        renderAlerts(alerts);
    } catch (e) {
        body.innerHTML = '<div class="error-state">Failed to load alerts: ' + e.message + '</div>';
        setStatus('degraded', 'Alerts unavailable: ' + (e.message || 'unknown error'));
    }
}

async function fetchReceiptScope(sessionId) {
    const body = document.getElementById('receipt-scope-body');
    try {
        const [receiptData, approvalData] = await Promise.all([
            window.CleanHouseAPI.getReceipts(sessionId),
            window.CleanHouseAPI.getApprovalQueue(sessionId),
        ]);
        _lastReceipts = receiptData.receipts || [];
        _lastReceipt = _lastReceipts.length > 0 ? _lastReceipts[0] : null;
        _lastApprovalQueue = approvalData.approval_queue || [];
        const [replays, bundles] = await Promise.all([
            fetchReceiptReplays(_lastReceipts),
            fetchReceiptBundles(_lastReceipts),
        ]);
        _lastReceiptReplays = replays;
        _lastReceiptBundles = bundles;
        renderReceiptScope(_lastReceipts, _lastApprovalQueue, _lastReceiptReplays, _lastReceiptBundles);
    } catch (e) {
        _lastReceipt = null;
        _lastReceipts = [];
        _lastApprovalQueue = [];
        _lastReceiptReplays = {};
        _lastReceiptBundles = {};
        document.getElementById('scope-cluster-count').textContent = '0';
        body.innerHTML = '<div class="error-state">Failed to load receipt scope: ' + escapeHtml(e.message) + '</div>';
    }
}

async function fetchNativeReports() {
    const body = document.getElementById('native-report-body');
    try {
        const data = await window.CleanHouseAPI.getReports();
        _lastReports = data.reports || [];
        renderNativeReports(_lastReports);
    } catch (e) {
        _lastReports = [];
        const count = document.getElementById('native-report-count');
        if (count) count.textContent = '0';
        if (body) {
            body.innerHTML = '<div class="error-state">Failed to load native reports: ' + escapeHtml(e.message || 'unknown error') + '</div>';
        }
    }
}

async function fetchWorkstation(sessionId) {
    try {
        const data = await window.CleanHouseAPI.getWorkstation(sessionId);
        _lastWorkstation = data && data.status === 'ok' ? data : null;
        _backendDisconnectCount = 0;
        _lastWorkstationOkAt = new Date();
        renderWorkstation(_lastWorkstation);
    } catch (e) {
        _backendDisconnectCount += 1;
        renderWorkstationDisconnect(e.message || 'workstation unavailable');
    }
}

async function fetchTier1Surfaces(sessionId) {
    try {
        const [collectorManifest, lineageGraph, rollbackReplayState, operatorVerification] = await Promise.all([
            window.CleanHouseAPI.getCollectorManifest(false),
            window.CleanHouseAPI.getLineageGraph(sessionId),
            window.CleanHouseAPI.getRollbackReplayState(sessionId),
            window.CleanHouseAPI.getOperatorVerification(sessionId),
        ]);
        _lastCollectorManifest = collectorManifest;
        _lastLineageGraph = lineageGraph;
        _lastRollbackReplayState = rollbackReplayState;
        _lastOperatorVerification = operatorVerification;
        renderCollectorManifest(collectorManifest);
        renderLineageGraph(lineageGraph);
        renderRollbackReplayState(rollbackReplayState);
        renderOperatorVerification(operatorVerification);
    } catch (e) {
        renderTier1Unavailable(e.message || 'tier1 surfaces unavailable');
    }
}

async function fetchReceiptReplays(receipts) {
    const replays = {};
    await Promise.all((receipts || []).map(async receipt => {
        if (!receipt.id) return;
        try {
            const replay = await window.CleanHouseAPI.getReceiptReplay(receipt.id);
            replays[receipt.id] = replay || { status: 'unknown', message: 'replay response unavailable' };
        } catch (e) {
            replays[receipt.id] = { status: 'unavailable', message: e.message || 'replay unavailable' };
        }
    }));
    return replays;
}

async function fetchReceiptBundles(receipts) {
    const bundles = {};
    await Promise.all((receipts || []).map(async receipt => {
        if (!receipt.id) return;
        try {
            const bundle = await window.CleanHouseAPI.getReceiptBundle(receipt.id);
            bundles[receipt.id] = normalizeReceiptBundleState(bundle);
        } catch (e) {
            bundles[receipt.id] = { status: 'unavailable', message: e.message || 'bundle unavailable' };
        }
    }));
    return bundles;
}

function renderWorkstation(data) {
    if (!data) {
        renderWorkstationDisconnect('workstation unavailable');
        return;
    }
    renderSessionBar(data.session || {});
    updateRuntimeIndicatorFromWorkstation(data, true);
    renderOperationalPresence(data.operational_presence || null);
    renderContinuityProvenance(data.continuity_provenance || null);
    renderObjectiveFeed(data.objectives || []);
    renderMutationStream(data.mutations || []);
    renderDeviationPanel(data.deviation_signals || {}, data.evidence_summaries || []);
    renderApprovalRequired(data.approvals || []);
    renderWorkstationReplay(data.receipts || [], data.receipt_replays || {});
    renderNotificationTray(data.notifications || []);
    maybeSendBrowserNotifications(data.notifications || []);
    applyPendingDashboardFocus();
}

function renderWorkstationDisconnect(message) {
    const detail = _backendDisconnectCount > 1
        ? 'retrying workstation connection (' + _backendDisconnectCount + ')'
        : 'retrying workstation connection';
    if (_lastWorkstation) {
        updateRuntimeIndicatorFromWorkstation(_lastWorkstation, false, detail);
        setStatus('degraded', detail + ': ' + message);
        return;
    }
    renderSessionBar({ session_id: currentSessionId || '', status: 'unknown' });
    renderRuntimeIndicator('unavailable', 'workstation unavailable: ' + message);
    const html = '<div class="empty-state"><div class="icon">!</div><div>unavailable: ' + escapeHtml(message) + '</div></div>';
    for (const id of [
        'operational-presence-body',
        'continuity-provenance-body',
        'objective-feed-body',
        'mutation-stream-body',
        'deviation-alert-body',
        'approval-required-body',
        'receipt-replay-body',
        'notification-tray'
    ]) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    }
    const continuityState = document.getElementById('continuity-provenance-state');
    if (continuityState) continuityState.textContent = 'unknown';
}

function renderSessionBar(session) {
    const sessionInput = document.getElementById('operator-session-input');
    const typedSessionId = sessionInput ? sessionInput.value.trim() : '';
    const sessionId = session.session_id || currentSessionId || typedSessionId || 'none';
    const status = session.status || 'stopped';
    document.getElementById('operator-session-id').textContent = sessionId;
    const statusEl = document.getElementById('operator-session-status');
    statusEl.textContent = status;
    statusEl.className = 'session-status status-' + cssToken(status);
    const hasSessionInput = Boolean(sessionId && sessionId !== 'none');
    document.getElementById('session-start-btn').disabled = !hasSessionInput || status === 'active';
    document.getElementById('session-stop-btn').disabled = !hasSessionInput || status !== 'active';
    document.getElementById('session-finalize-btn').disabled = !hasSessionInput || status === 'finalized';
    const declareBtn = document.getElementById('declare-objective-btn');
    if (declareBtn) {
        declareBtn.disabled = !hasSessionInput || status !== 'active';
    }
    updateNotificationButton();
}

function updateRuntimeIndicatorFromWorkstation(data, backendReachable, overrideDetail = '') {
    const session = data?.session || {};
    const status = session.status || 'stopped';
    if (!backendReachable) {
        const staleState = status === 'active' ? deriveRuntimeState(data) : 'idle';
        renderRuntimeIndicator(
            'degraded',
            (overrideDetail || 'retrying workstation connection') + '; last known state=' + staleState
        );
        return;
    }
    if (status !== 'active') {
        renderRuntimeIndicator('idle', status || 'unavailable');
        return;
    }
    const state = deriveRuntimeState(data);
    const detail = state === 'drift detected'
        ? 'evidence refs present'
        : (_lastWorkstationOkAt ? 'last poll ' + formatTime(_lastWorkstationOkAt.toISOString()) : 'backend reachable');
    renderRuntimeIndicator(state, detail);
}

function deriveRuntimeState(data) {
    if (!data || (data.session || {}).status !== 'active') {
        return 'idle';
    }
    if (hasCurrentDriftEvidence(data)) {
        return 'drift detected';
    }
    return 'monitoring';
}

function hasCurrentDriftEvidence(data) {
    const notifications = Array.isArray(data.notifications) ? data.notifications : [];
    if (notifications.some(item => !item.acknowledged && item.notification_type === 'scope_drift_detected' && hasEvidenceRefs(item))) {
        return true;
    }
    const summaries = Array.isArray(data.evidence_summaries) ? data.evidence_summaries : [];
    if (summaries.some(item => item.summary_type === 'scope_drift' && hasEvidenceRefs(item))) {
        return true;
    }
    const alerts = (data.deviation_signals && Array.isArray(data.deviation_signals.alerts))
        ? data.deviation_signals.alerts
        : [];
    if (alerts.some(item => item.alert_type === 'scope_expansion' && hasEvidenceRefs(item))) {
        return true;
    }
    return hasPendingDriftApproval(data);
}

function hasPendingDriftApproval(data) {
    const approvals = Array.isArray(data.approvals) ? data.approvals : [];
    const receipts = Array.isArray(data.receipts) ? data.receipts : [];
    const receiptClassifications = new Map(receipts.map(receipt => [
        receipt.id,
        (receipt.scope_analysis || {}).classification
    ]));
    return approvals.some(item => {
        if (!item || !['pending', 'needs_review'].includes(item.status) || !hasEvidenceRefs(item)) {
            return false;
        }
        const metadata = item.metadata || {};
        if (metadata.classification === 'outside_declared_scope') {
            return true;
        }
        const receiptId = metadata.receipt_id || '';
        return receiptId && receiptClassifications.get(receiptId) === 'outside_declared_scope';
    });
}

function hasEvidenceRefs(item) {
    return Array.isArray(item?.evidence_refs) && item.evidence_refs.length > 0;
}

function renderRuntimeIndicator(state, detail) {
    const normalized = ['idle', 'monitoring', 'drift detected', 'degraded', 'unknown', 'unavailable'].includes(state) ? state : 'unknown';
    const el = document.getElementById('runtime-indicator');
    const text = document.getElementById('runtime-indicator-text');
    const detailEl = document.getElementById('runtime-indicator-detail');
    if (!el || !text || !detailEl) return;
    el.className = 'runtime-indicator runtime-' + cssToken(normalized);
    text.textContent = normalized;
    detailEl.textContent = detail || 'unavailable';
}

function renderOperationalPresence(presence) {
    const body = document.getElementById('operational-presence-body');
    const stateEl = document.getElementById('operational-presence-state');
    if (!body || !stateEl) return;
    if (!presence) {
        stateEl.textContent = 'unknown';
        body.innerHTML = '<div class="empty-state"><div class="icon">•</div><div>Operational presence unavailable.</div></div>';
        return;
    }
    const state = presence.state || 'unknown';
    const counts = presence.open_counts || {};
    const objective = presence.objective || {};
    const focus = presence.focus || {};
    const intervention = presence.primary_intervention || null;
    _lastPrimaryIntervention = intervention;
    const clipboardAvailable = Boolean(navigator.clipboard && navigator.clipboard.writeText);
    const countPairs = [
        ['approvals', counts.pending_approvals],
        ['notifications', counts.unacknowledged_notifications],
        ['drift', counts.scope_drift_summaries],
        ['mutations', counts.recent_mutations],
        ['events', counts.live_events],
    ];
    stateEl.textContent = state;
    body.innerHTML =
        '<div class="presence-row state-' + cssToken(state) + ' priority-' + cssToken(presence.priority || 'info') + '">' +
        '  <div class="presence-head">' +
        '    <strong>' + escapeHtml(presence.interrupt ? 'attention required' : 'quiet watch') + '</strong>' +
        '    <span>' + escapeHtml(formatTime(presence.last_activity_at)) + '</span>' +
        '  </div>' +
        '  <div class="presence-summary">' + escapeHtml(presence.summary || '') + '</div>' +
        '  <div class="presence-next">' + escapeHtml(presence.next_action || '') + '</div>' +
        '  <div class="presence-metrics">' + countPairs.map(([label, value]) =>
        '    <span><strong>' + escapeHtml(String(value ?? 0)) + '</strong>' + escapeHtml(label) + '</span>'
        ).join('') + '</div>' +
        (intervention ? renderPresenceIntervention(intervention, clipboardAvailable) : '') +
        (objective.id ? '<div class="workstation-meta">objective=' + escapeHtml(objective.id) + ' · scope=' + escapeHtml(valueOrUnavailable(objective.scope)) + ' · tool=' + escapeHtml(valueOrUnavailable(objective.tool_identity)) + '</div>' : '') +
        (focus.type ? '<div class="workstation-meta">focus=' + escapeHtml(focus.type) + ' · id=' + escapeHtml(valueOrUnavailable(focus.id || focus.receipt_id)) + '</div>' : '') +
        renderInlineRefs(presence.evidence_refs || []) +
        '</div>';
}

function renderNativeReports(reports) {
    const body = document.getElementById('native-report-body');
    const count = document.getElementById('native-report-count');
    if (!body || !count) return;
    const nativeReports = (reports || []).filter(report => report.report_type === 'login_summary');
    count.textContent = String(nativeReports.length);
    if (nativeReports.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">▤</div><div>No since-login native reports recorded yet.</div></div>';
        return;
    }
    body.innerHTML = nativeReports.slice(0, 6).map(renderNativeReportRow).join('');
}

function renderNativeReportRow(report) {
    const receipt = report.receipt || {};
    const summary = receipt.summary || {};
    const metadata = report.metadata || receipt.metadata || {};
    const evidenceCount = Array.isArray(report.evidence_links) ? report.evidence_links.length : 0;
    const eventCount = summary.event_count ?? metadata.event_count ?? 0;
    const receiptCount = summary.receipt_count ?? metadata.receipt_count ?? 0;
    const reportCount = summary.report_count ?? metadata.report_count ?? 0;
    const activeClass = report.id && report.id === _activeLoginReportId ? ' active-login-report' : '';
    return '<div class="workstation-row native-report-row' + activeClass + '" data-report-id="' + escapeHtml(report.id || '') + '">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(report.report_type || 'report') + '</strong>' +
        '    <span>' + escapeHtml(formatTime(report.timestamp)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-summary">' + escapeHtml(summary.text || report.context || 'Report summary unavailable.') + '</div>' +
        '  <div class="workstation-meta">window_start=' + escapeHtml(valueOrUnavailable(metadata.previous_login_at || metadata.window_start)) +
            ' · window_end=' + escapeHtml(valueOrUnavailable(metadata.current_login_at || metadata.window_end)) + '</div>' +
        '  <div class="workstation-meta">events=' + escapeHtml(String(eventCount)) +
            ' · receipts=' + escapeHtml(String(receiptCount)) +
            ' · reports=' + escapeHtml(String(reportCount)) +
            ' · evidence_refs=' + escapeHtml(String(evidenceCount)) + '</div>' +
        '  <div class="receipt-review-actions">' +
        '    <button class="receipt-action review" onclick="openStoredReport(\'' + escapeJsString(report.id || '') + '\')">Open Report</button>' +
        '  </div>' +
        renderInlineRefs((report.evidence_links || []).slice(0, 5)) +
        '</div>';
}

function openStoredReport(reportId) {
    const report = (_lastReports || []).find(item => item.id === reportId);
    if (!report) return;
    document.getElementById('report-modal').style.display = 'flex';
    showReportResult({ status: 'ok', ...report });
}

function renderPresenceIntervention(intervention, clipboardAvailable) {
    const hasDraft = Boolean(intervention.draft_correction_prompt);
    return '<div class="presence-intervention">' +
        '  <div class="presence-intervention-head">' +
        '    <strong>' + escapeHtml(intervention.type || 'intervention') + '</strong>' +
        '    <span>' + escapeHtml(valueOrUnavailable(intervention.receipt_id || intervention.approval_id || intervention.notification_id)) + '</span>' +
        '  </div>' +
        '  <div class="presence-intervention-summary">' + escapeHtml(intervention.summary || '') + '</div>' +
        '  <div class="presence-actions">' +
        '    <button onclick="reviewPresenceEvidence()">Review Evidence</button>' +
        '    <button onclick="stabilizePrimaryIntervention()">Stabilize</button>' +
        '    <button onclick="copyPrimaryCorrection()" ' + (clipboardAvailable && hasDraft ? '' : 'disabled') + '>Copy Correction</button>' +
        '  </div>' +
        '</div>';
}

function renderContinuityProvenance(provenance) {
    const body = document.getElementById('continuity-provenance-body');
    const stateEl = document.getElementById('continuity-provenance-state');
    if (!body || !stateEl) return;
    _lastContinuityProvenance = provenance;
    if (!provenance) {
        stateEl.textContent = 'unknown';
        body.innerHTML = '<div class="empty-state"><div class="icon">•</div><div>Continuity provenance unavailable.</div></div>';
        return;
    }
    const claims = Array.isArray(provenance.claims) ? provenance.claims : [];
    const active = provenance.active_source || activeContinuityClaim();
    const failures = Array.isArray(provenance.failed_pickups) ? provenance.failed_pickups : [];
    const searches = Array.isArray(provenance.search_results) ? provenance.search_results : [];
    stateEl.textContent = provenance.status || 'unknown';

    const activeHtml = active && active.id
        ? renderContinuityClaim(active, true)
        : '<div class="continuity-claim classification-unknown"><div class="workstation-summary">No active continuity source selected.</div></div>';
    const failureHtml = failures.length
        ? '<div class="continuity-section"><div class="continuity-section-title">Failed Pickups</div>' +
            failures.map(renderContinuityFailure).join('') +
            '</div>'
        : '';
    const searchHtml = searches.length
        ? '<div class="continuity-section"><div class="continuity-section-title">Search Results</div>' +
            searches.slice(0, 4).map(renderContinuitySearch).join('') +
            '</div>'
        : '';
    const claimHtml = claims.length
        ? '<div class="continuity-section"><div class="continuity-section-title">Claims</div>' +
            claims.slice(0, 8).map(claim => renderContinuityClaim(claim, false)).join('') +
            '</div>'
        : '';
    const freshness = provenance.freshness || {};
    body.innerHTML =
        '<div class="continuity-row status-' + cssToken(provenance.status || 'unknown') + '">' +
        '  <div class="continuity-head">' +
        '    <strong>active_source=' + escapeHtml(valueOrUnavailable(active?.source_type)) + '</strong>' +
        '    <span>' + escapeHtml(valueOrUnavailable(active?.classification)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-meta">freshness=' + escapeHtml(valueOrUnavailable(freshness.state)) +
            ' · timestamp=' + escapeHtml(valueOrUnavailable(freshness.timestamp)) + '</div>' +
        '  <div class="workstation-summary">' + escapeHtml(provenance.confidence_basis || 'confidence basis unavailable') + '</div>' +
        '  <div class="continuity-actions">' +
        '    <button onclick="acceptContinuity()">Accept Continuity</button>' +
        '    <button onclick="ignoreContinuity()">Ignore</button>' +
        '    <button onclick="searchContinuityDeeper()">Search Deeper</button>' +
        '    <button onclick="pinCanonicalContext()">Pin Canonical Context</button>' +
        '  </div>' +
        activeHtml +
        failureHtml +
        searchHtml +
        claimHtml +
        '</div>';
}

function renderContinuityClaim(claim, isActive) {
    const freshness = claim.freshness || {};
    const staleMarker = ['stale', 'old', 'unknown'].includes(freshness.state) || claim.classification === 'degraded'
        ? ' · marker=' + valueOrUnavailable(freshness.state || claim.classification)
        : '';
    return '<div class="continuity-claim classification-' + cssToken(claim.classification || 'unknown') + (isActive ? ' active' : '') + '" data-continuity-claim-id="' + escapeHtml(claim.id || '') + '">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml((isActive ? 'active ' : '') + (claim.source_type || 'source')) + '</strong>' +
        '    <span>' + escapeHtml(claim.classification || 'unknown') + '</span>' +
        '  </div>' +
        '  <div class="workstation-summary">' + escapeHtml(claim.summary || '') + '</div>' +
        (claim.snippet ? '<div class="continuity-snippet">' + escapeHtml(claim.snippet) + '</div>' : '') +
        '  <div class="workstation-meta">source_ref=' + escapeHtml(valueOrUnavailable(claim.source_ref)) +
            ' · freshness=' + escapeHtml(valueOrUnavailable(freshness.state)) + staleMarker + '</div>' +
        (claim.confidence_basis ? '<div class="workstation-meta">basis=' + escapeHtml(claim.confidence_basis) + '</div>' : '') +
        renderInlineRefs(claim.evidence_refs || []) +
        '</div>';
}

function renderContinuityFailure(failure) {
    return '<div class="continuity-failure">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(failure.source_type || 'pickup') + '</strong>' +
        '    <span>' + escapeHtml(failure.reason || 'failed') + '</span>' +
        '  </div>' +
        '  <div class="workstation-summary">' + escapeHtml(failure.detail || failure.reason || 'pickup unavailable') + '</div>' +
        '  <div class="workstation-meta">freshness_at=' + escapeHtml(valueOrUnavailable(failure.freshness_at)) + '</div>' +
        renderInlineRefs(failure.evidence_refs || []) +
        '</div>';
}

function renderContinuitySearch(search) {
    const results = Array.isArray(search.results) ? search.results : [];
    const sources = Array.isArray(search.searched_sources) ? search.searched_sources : [];
    const resultRows = results.length
        ? results.slice(0, 5).map(result =>
            '<div class="continuity-search-result">' +
            '  <div class="continuity-snippet">' + escapeHtml(result.snippet || '') + '</div>' +
            '  <div class="workstation-meta">ref=' + escapeHtml(valueOrUnavailable(result.source_ref)) + '</div>' +
            renderInlineRefs(result.evidence_refs || []) +
            '</div>'
        ).join('')
        : '<div class="workstation-meta">visible outcome=no_results</div>';
    return '<div class="continuity-search">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(search.status || 'search') + '</strong>' +
        '    <span>' + escapeHtml(formatTime(search.created_at)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-meta">searched_sources=' + escapeHtml(String(sources.length)) +
            ' · result_count=' + escapeHtml(String(search.result_count ?? results.length)) + '</div>' +
        (sources.length ? '<div class="continuity-source-list">' + sources.slice(0, 5).map(source => '<code>' + escapeHtml(source) + '</code>').join('') + '</div>' : '') +
        resultRows +
        '</div>';
}

function renderObjectiveFeed(objectives) {
    const body = document.getElementById('objective-feed-body');
    document.getElementById('objective-feed-count').textContent = objectives.length;
    if (objectives.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">◎</div><div>No objective evidence recorded for this session.</div></div>';
        return;
    }
    body.innerHTML = objectives.map(objective =>
        '<div class="workstation-row">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(objective.id || 'objective') + '</strong>' +
        '    <span>' + escapeHtml(formatTime(objective.timestamp)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-summary">' + escapeHtml(objective.text || '') + '</div>' +
        '  <div class="workstation-meta">scope=' + escapeHtml(objective.scope || '(none)') + ' · tool=' + escapeHtml(objective.tool_identity || '') + '</div>' +
        '</div>'
    ).join('');
}

function renderMutationStream(mutations) {
    const body = document.getElementById('mutation-stream-body');
    document.getElementById('mutation-stream-count').textContent = mutations.length;
    if (mutations.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">≡</div><div>No local controlled mutations recorded for this session.</div></div>';
        return;
    }
    body.innerHTML = mutations.map(mutation => {
        const changes = Array.isArray(mutation.changes)
            ? mutation.changes.map(change => typeof change === 'string' ? change : (change.path || '')).filter(Boolean)
            : [];
        const refs = mutation.evidence_refs || [];
        return '<div class="workstation-row mutation-row">' +
            '  <div class="workstation-row-head">' +
            '    <strong>' + escapeHtml(mutation.source || 'mutation') + '</strong>' +
            '    <span>' + escapeHtml(formatTime(mutation.timestamp)) + '</span>' +
            '  </div>' +
            '  <div class="workstation-summary">' + escapeHtml(mutation.summary || mutation.path || '') + '</div>' +
            (changes.length ? '<div class="workstation-paths">' + changes.slice(0, 6).map(path => '<code>' + escapeHtml(path) + '</code>').join('') + '</div>' : '') +
            renderInlineRefs(refs) +
            '</div>';
    }).join('');
}

function renderDeviationPanel(deviationSignals, evidenceSummaries) {
    const body = document.getElementById('deviation-alert-body');
    const alerts = deviationSignals.alerts || [];
    const summaries = (evidenceSummaries || []).filter(item =>
        item.summary_type === 'scope_drift' || item.summary_type === 'alert'
    );
    document.getElementById('deviation-alert-count').textContent = summaries.length || alerts.length;
    if (summaries.length === 0 && alerts.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">⚑</div><div>No deviation summaries recorded for this session.</div></div>';
        return;
    }
    const summaryHtml = summaries.map(summary =>
        '<div class="why-flagged-row severity-' + cssToken(summary.severity || 'info') + '">' +
        '  <div class="why-title">Why flagged</div>' +
        '  <div class="workstation-summary">' + escapeHtml(summary.summary || '') + '</div>' +
        (summary.rationale ? '<div class="workstation-meta">' + escapeHtml(summary.rationale) + '</div>' : '') +
        (summary.scope_weight !== undefined ? '<div class="workstation-meta">scope_weight=' + escapeHtml(formatScopeWeight(summary.scope_weight)) + '</div>' : '') +
        renderPathClustersInline(summary.path_clusters || []) +
        renderInlineRefs(summary.evidence_refs || []) +
        '</div>'
    ).join('');
    body.innerHTML = summaryHtml || alerts.map(alert =>
        '<div class="why-flagged-row severity-' + cssToken(alert.severity || 'low') + '">' +
        '  <div class="why-title">' + escapeHtml(alert.alert_type || 'alert') + '</div>' +
        '  <div class="workstation-summary">' + escapeHtml(alert.description || '') + '</div>' +
        '  <div class="workstation-meta">' + escapeHtml(alert.rationale || '') + '</div>' +
        renderInlineRefs(alert.evidence_refs || []) +
        '</div>'
    ).join('');
}

function renderApprovalRequired(approvals) {
    const body = document.getElementById('approval-required-body');
    const pending = (approvals || []).filter(item => item.status === 'pending' || item.status === 'needs_review');
    document.getElementById('approval-required-count').textContent = pending.length;
    if (pending.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">✓</div><div>No approval-required records are pending.</div></div>';
        return;
    }
    body.innerHTML = pending.map(item => {
        const approvalId = item.id || '';
        const disabled = approvalId ? '' : ' disabled';
        const metadata = item.metadata || {};
        const receiptId = metadata.receipt_id ? ' · receipt_id=' + escapeHtml(metadata.receipt_id) : '';
        const promptId = item.prompt_id ? ' · prompt_id=' + escapeHtml(item.prompt_id) : '';
        const objectiveId = item.objective_id ? ' · objective_id=' + escapeHtml(item.objective_id) : '';
        return '<div class="workstation-row approval-required-row" data-approval-id="' + escapeHtml(approvalId) + '">' +
            '  <div class="workstation-row-head">' +
            '    <strong>' + escapeHtml(item.status || 'pending') + '</strong>' +
            '    <span>' + escapeHtml(formatTime(item.created_at)) + '</span>' +
            '  </div>' +
            '  <div class="workstation-summary">' + escapeHtml(item.requested_action || '') + '</div>' +
            '  <div class="workstation-meta">' + escapeHtml(item.reason || 'review reason unavailable') + '</div>' +
            '  <div class="workstation-meta">decision_effect=operator review record only' + receiptId + promptId + objectiveId + '</div>' +
            '  <textarea class="receipt-review-note workstation-approval-note" data-approval-id="' + escapeHtml(approvalId) + '" placeholder="Reviewer note recorded with decision">' + escapeHtml(item.reviewer_note || item.resolution_note || '') + '</textarea>' +
            '  <div class="receipt-review-actions">' +
            '    <button class="receipt-action approve" onclick="handleWorkstationApprovalAction(\'' + escapeJsString(approvalId) + '\', \'approved\')"' + disabled + '>Approve</button>' +
            '    <button class="receipt-action reject" onclick="handleWorkstationApprovalAction(\'' + escapeJsString(approvalId) + '\', \'rejected\')"' + disabled + '>Reject</button>' +
            '    <button class="receipt-action review" onclick="handleWorkstationApprovalAction(\'' + escapeJsString(approvalId) + '\', \'needs_review\')"' + disabled + '>Needs review</button>' +
            '  </div>' +
            renderInlineRefs(item.evidence_refs || []) +
            '</div>';
    }).join('');
}

function renderWorkstationReplay(receipts, replays) {
    const body = document.getElementById('receipt-replay-body');
    const replayCount = Object.values(replays || {}).filter(replay => replayStatusLabel(replay) === 'ok').length;
    document.getElementById('receipt-replay-count').textContent = replayCount;
    if (!receipts.length) {
        body.innerHTML = '<div class="empty-state"><div class="icon">⌁</div><div>No replayable receipts recorded for this session.</div></div>';
        return;
    }
    body.innerHTML = receipts.map(receipt => {
        const replay = replays[receipt.id] || null;
        const replayStatus = replayStatusLabel(replay);
        const state = replay && replayStatus === 'ok' ? replay.state || {} : {};
        const integrity = replay && replay.integrity ? replay.integrity : {};
        const receiptRoot = receiptRootHash(receipt);
        const message = replay && replay.status && replay.status !== 'ok'
            ? '<div class="workstation-summary">replay_message=' + escapeHtml(replay.message || 'unavailable') + '</div>'
            : '';
        return '<div class="workstation-row replay-row">' +
            '  <div class="workstation-row-head">' +
                '    <strong>' + escapeHtml(receipt.id || 'unavailable') + '</strong>' +
                '    <span>' + escapeHtml(formatReceiptTimestamp(receipt.timestamp)) + '</span>' +
            '  </div>' +
            '  <div class="workstation-meta">replay_status=' + escapeHtml(replayStatus) + ' · approval_state=' + escapeHtml(valueOrUnavailable(state.status)) + ' · evidence_refs=' + escapeHtml(String(integrity.evidence_ref_count ?? (receipt.evidence_index || []).length)) + '</div>' +
            '  <div class="workstation-meta">receipt_root_hash=' + escapeHtml(valueOrUnavailable(receiptRoot)) + '</div>' +
            (message || (!replay ? '<div class="workstation-summary">replay_message=unavailable</div>' : '')) +
            '  <div class="receipt-replay-hash">replay_hash=' + escapeHtml(replayHashValue(replay)) + '</div>' +
            '</div>';
    }).join('');
}

function renderNotificationTray(notifications) {
    const body = document.getElementById('notification-tray');
    const pending = (notifications || []).filter(item => !item.acknowledged);
    document.getElementById('notification-tray-count').textContent = pending.length;
    if (!notifications.length) {
        body.innerHTML = '<div class="empty-state"><div class="icon">•</div><div>No dashboard/browser notifications recorded.</div></div>';
        return;
    }
    body.innerHTML = notifications.map(item =>
        '<div class="notification-row severity-' + cssToken(item.severity || 'info') + (item.acknowledged ? ' acknowledged' : '') + '" data-notification-id="' + escapeHtml(item.id || '') + '">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(item.notification_type || 'notification') + '</strong>' +
        '    <span>' + escapeHtml(formatTime(item.created_at)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-summary">' + escapeHtml(item.summary || 'notification summary unavailable') + '</div>' +
        '  <div class="workstation-meta">delivery=dashboard tray · browser_notification=' + escapeHtml(browserNotificationStateLabel()) + '</div>' +
        renderInlineRefs(item.evidence_refs || []) +
        '  <button class="notification-ack" onclick="ackNotification(\'' + escapeJsString(item.id || '') + '\')" ' + (item.acknowledged ? 'disabled' : '') + '>Ack</button>' +
        '</div>'
    ).join('');
}

function renderCollectorManifest(manifest) {
    const body = document.getElementById('collector-manifest-body');
    const collectors = manifest?.collectors || [];
    document.getElementById('collector-manifest-count').textContent = collectors.length;
    if (collectors.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">▦</div><div>No collector health snapshot available.</div></div>';
        updateStatus(_lastTimelineEntries);
        return;
    }
    body.innerHTML = collectors.map(collector => {
        const enabledLabel = collector.enabled === null ? 'configured unknown' : (collector.enabled ? 'enabled' : 'disabled');
        const collectorStatus = collector.collector_status || 'unknown';
        const dependency = collector.dependency_available === undefined ? '' : ' · dependency_available=' + String(Boolean(collector.dependency_available));
        const watchDir = collector.watch_dir ? ' · watch_dir=' + escapeHtml(collector.watch_dir) : '';
        return '<div class="tier1-row collector-row status-' + cssToken(collector.status || 'unknown') + ' collector-status-' + cssToken(collectorStatus) + '">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(collector.name || 'collector') + '</strong>' +
        '    <span>' + escapeHtml(enabledLabel) + '</span>' +
        '  </div>' +
        '  <div class="workstation-meta">status=' + escapeHtml(collector.status || 'unknown') +
        ' · collector_status=' + escapeHtml(collectorStatus) +
        ' · observations=' + escapeHtml(String(collector.observations || 0)) +
        ' · failures=' + escapeHtml(String(collector.collector_failures || 0)) +
        dependency + watchDir + '</div>' +
        (collector.failure ? '<div class="workstation-summary">' + escapeHtml(collector.failure.message || collector.failure.error || 'collector failure') + '</div>' : '') +
        '</div>'
    }).join('');
    updateStatus(_lastTimelineEntries);
}

function renderLineageGraph(graph) {
    const body = document.getElementById('lineage-graph-body');
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    document.getElementById('lineage-graph-count').textContent = nodes.length;
    if (nodes.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">⌬</div><div>No session evidence links available.</div></div>';
        return;
    }
    const edgeRows = edges.slice(0, 12).map(edge =>
        '<div class="lineage-edge">' +
        '  <code>' + escapeHtml(edge.from || '') + '</code>' +
        '  <span>' + escapeHtml(edge.relation || 'links') + '</span>' +
        '  <code>' + escapeHtml(edge.to || '') + '</code>' +
        '</div>'
    ).join('');
    body.innerHTML =
        '<div class="tier1-summary">nodes=' + escapeHtml(String(nodes.length)) + ' · edges=' + escapeHtml(String(edges.length)) + '</div>' +
        nodes.slice(0, 10).map(node =>
            '<div class="tier1-node node-' + cssToken(node.type || 'unknown') + '">' +
            '  <strong>' + escapeHtml(node.type || 'node') + '</strong>' +
            '  <span>' + escapeHtml(node.label || node.id || '') + '</span>' +
            '</div>'
        ).join('') +
        '<div class="lineage-edge-list">' + edgeRows + '</div>';
}

function renderRollbackReplayState(state) {
    const body = document.getElementById('rollback-replay-body');
    const receipts = state?.receipts || [];
    const replays = state?.replays || {};
    const manifests = state?.manifests || {};
    const rollbacks = state?.rollbacks || [];
    document.getElementById('rollback-replay-count').textContent = receipts.length + rollbacks.length;
    if (receipts.length === 0 && rollbacks.length === 0) {
        const message = state?.rollback_status && state.rollback_status !== 'ok'
            ? 'Rollback endpoint ' + valueOrUnavailable(state.rollback_status) + ': ' + valueOrUnavailable(state.rollback_message)
            : 'No rollback/replay/signature state recorded for this session.';
        body.innerHTML = '<div class="empty-state"><div class="icon">↺</div><div>' + escapeHtml(message) + '</div></div>';
        return;
    }
    const receiptRows = receipts.map(receipt => {
        const replay = replays[receipt.id] || null;
        const manifestInfo = manifests[receipt.id] || {};
        const manifest = manifestInfo.manifest || manifestInfo;
        const manifestIntegrity = manifestInfo.integrity || {};
        const approval = (state.approvals || []).find(item => item?.metadata?.receipt_id === receipt.id) || {};
        const rollback = findRollbackForReceipt(receipt, state);
        const replayStatus = replayStatusLabel(replay);
        const bundleStatus = bundleStatusLabel(manifestInfo);
        const signatureStatus = bundleSignatureStatus(manifestInfo);
        const trustState = receiptTrustState(receipt, replay, manifestInfo);
        return '<div class="tier1-row rollback-row">' +
            '  <div class="workstation-row-head">' +
            '    <strong>' + escapeHtml(receipt.id || 'receipt') + '</strong>' +
            '    <span>' + escapeHtml(trustState) + '</span>' +
            '  </div>' +
            '  <div class="workstation-meta">replay_status=' + escapeHtml(replayStatus) + ' · approval_state=' + escapeHtml(approval.status || replay?.state?.status || 'unreviewed') + '</div>' +
            '  <div class="workstation-meta">bundle_status=' + escapeHtml(bundleStatus) + ' · signature_status=' + escapeHtml(signatureStatus) + ' · signature_verified=' + escapeHtml(bundleSignatureVerifiedLabel(manifestInfo)) + '</div>' +
            '  <div class="workstation-meta">replay_hash=' + escapeHtml(replayHashValue(replay)) + '</div>' +
            '  <div class="workstation-meta">manifest_hash=' + escapeHtml(valueOrUnavailable(manifestIntegrity.manifest_hash || manifest.manifest_hash)) + '</div>' +
            '  <div class="workstation-meta">operator_decision=' + escapeHtml(approval.status || replay?.state?.status || 'unreviewed') + ' · rollback_status=' + escapeHtml(rollbackStatusLabel(rollback)) + '</div>' +
            '  <div class="workstation-meta">rollback_verification=' + escapeHtml(rollbackVerificationLabel(rollback)) + '</div>' +
            '</div>';
    }).join('');
    const rollbackOnlyRows = rollbacks
        .filter(rollback => !receipts.some(receipt => findRollbackForReceipt(receipt, state)?.id === rollback.id))
        .map(renderRollbackRecordRow)
        .join('');
    body.innerHTML = receiptRows + rollbackOnlyRows;
}

function findRollbackForReceipt(receipt, state) {
    const receiptId = receipt?.id || '';
    if (!receiptId) return null;
    const receiptRef = 'local://cleanhouse/receipt/' + receiptId;
    return (state?.rollbacks || []).find(rollback => {
        const metadata = rollback.metadata || {};
        if (metadata.receipt_id === receiptId) return true;
        const refs = Array.isArray(rollback.evidence_refs) ? rollback.evidence_refs : [];
        return refs.includes(receiptRef);
    }) || null;
}

function renderRollbackRecordRow(rollback) {
    const verification = rollback?.verification || {};
    return '<div class="tier1-row rollback-row">' +
        '  <div class="workstation-row-head">' +
        '    <strong>' + escapeHtml(rollback?.id || 'rollback') + '</strong>' +
        '    <span>' + escapeHtml(rollbackStatusLabel(rollback)) + '</span>' +
        '  </div>' +
        '  <div class="workstation-meta">requested_path=' + escapeHtml(valueOrUnavailable(rollback?.requested_path)) + ' · status=' + escapeHtml(rollbackStatusLabel(rollback)) + '</div>' +
        '  <div class="workstation-meta">verification=' + escapeHtml(valueOrUnavailable(verification.reason)) + '</div>' +
        renderInlineRefs(rollback?.evidence_refs || []) +
        '</div>';
}

function renderOperatorVerification(verification) {
    const body = document.getElementById('operator-verification-body');
    const checks = verification?.checks || {};
    const entries = Object.entries(checks);
    document.getElementById('operator-verification-count').textContent = entries.filter(([name, value]) => !verificationCheckPassed(name, value)).length;
    if (entries.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">□</div><div>No local HTTP evidence gap output available.</div></div>';
        return;
    }
    body.innerHTML =
        '<div class="tier1-summary">source=' + escapeHtml(verification.method || 'http-api') +
        ' · status=' + escapeHtml(verification.status || 'unknown') + '</div>' +
        entries.map(([name, value]) => {
            const passed = verificationCheckPassed(name, value);
            return '<div class="verification-check ' + (passed ? 'pass' : 'fail') + '">' +
            '  <span>' + escapeHtml(name) + '</span>' +
            '  <em>' + escapeHtml(verificationCheckValue(value)) + '</em>' +
            '  <strong>' + escapeHtml(passed ? 'pass' : 'fail') + '</strong>' +
            '</div>';
        }).join('');
}

function renderTier1Unavailable(message) {
    for (const pair of [
        ['collector-manifest-body', 'collector-manifest-count'],
        ['lineage-graph-body', 'lineage-graph-count'],
        ['rollback-replay-body', 'rollback-replay-count'],
        ['operator-verification-body', 'operator-verification-count'],
    ]) {
        const body = document.getElementById(pair[0]);
        const count = document.getElementById(pair[1]);
        if (count) count.textContent = pair[1] === 'operator-verification-count' ? '1' : '0';
        if (body) body.innerHTML = '<div class="error-state">Failed to load tier1 surface: ' + escapeHtml(message) + '</div>';
    }
}

function renderInlineRefs(refs) {
    if (!refs || refs.length === 0) {
        return '';
    }
    return '<div class="workstation-refs">' + refs.map(ref =>
        '<a href="' + escapeHtml(ref) + '">' + escapeHtml(ref) + '</a>'
    ).join('') + '</div>';
}

function renderPathClustersInline(clusters) {
    if (!Array.isArray(clusters) || clusters.length === 0) {
        return '';
    }
    return '<div class="workstation-clusters">' + clusters.slice(0, 4).map(cluster =>
        '<span>' + escapeHtml(cluster.cluster || '(unclustered)') + ': ' + escapeHtml(cluster.relation || 'unknown') + '</span>'
    ).join('') + '</div>';
}

async function startSelectedSession() {
    const sessionId = resolveOperatorSessionId(true);
    if (!sessionId) return;
    setObjectiveResult('Starting session...');
    try {
        const result = await window.CleanHouseAPI.startOperatorSession(sessionId, null, 'operator session started from dashboard', { source: 'dashboard' });
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'session start failed');
        }
        currentSessionId = sessionId;
        persistOperatorState({ session_id: sessionId, objective_id: result.session?.objective_id || readOperatorState()?.objective_id || '' });
        ensureSessionOption(sessionId, sessionId + ' [operator]');
        document.getElementById('session-select').value = sessionId;
        setObjectiveResult('Session active: ' + sessionId);
        await fetchWorkstation(currentSessionId);
    } catch (e) {
        setObjectiveResult('Session start failed: ' + (e.message || 'unknown error'), true);
    }
}

async function stopSelectedSession(finalize) {
    const sessionId = resolveOperatorSessionId(false);
    if (!sessionId) return;
    try {
        const result = await window.CleanHouseAPI.stopOperatorSession(sessionId, finalize, finalize ? 'operator session finalized from dashboard' : 'operator session stopped from dashboard', { source: 'dashboard' });
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'session stop failed');
        }
        persistOperatorState({ session_id: sessionId, objective_id: result.session?.objective_id || readOperatorState()?.objective_id || '' });
        setObjectiveResult(finalize ? 'Session finalized.' : 'Session stopped.');
        await fetchWorkstation(sessionId);
    } catch (e) {
        setObjectiveResult('Session state update failed: ' + (e.message || 'unknown error'), true);
    }
}

async function declareObjective(event) {
    if (event && event.preventDefault) event.preventDefault();
    const sessionId = resolveOperatorSessionId(false);
    if (!sessionId) {
        setObjectiveResult('Start a session before declaring an objective.', true);
        return;
    }
    const sessionStatus = document.getElementById('operator-session-status')?.textContent || '';
    if (sessionStatus !== 'active') {
        setObjectiveResult('Session must be active before objective declaration.', true);
        return;
    }
    const text = document.getElementById('objective-text').value.trim();
    const scope = document.getElementById('objective-scope').value.trim();
    const context = document.getElementById('objective-context').value.trim();
    const tool = document.getElementById('objective-tool').value.trim() || 'codex';
    if (!text || !scope) {
        setObjectiveResult('Objective and declared scope are required.', true);
        return;
    }
    const objectiveId = 'objective-' + sessionId + '-' + Date.now();
    setObjectiveResult('Declaring objective...');
    try {
        const prompt = await window.CleanHouseAPI.submitPrompt(text, context, scope, '', tool, sessionId, objectiveId);
        if (!prompt || prompt.status !== 'ok') {
            throw new Error(prompt?.message || 'prompt ingestion failed');
        }
        const sessionResult = await window.CleanHouseAPI.startOperatorSession(
            sessionId,
            objectiveId,
            'operator objective declared: ' + text,
            {
                source: 'dashboard',
                prompt_id: prompt.id || '',
                declared_scope: scope,
                context
            }
        );
        if (!sessionResult || sessionResult.status !== 'ok') {
            throw new Error(sessionResult?.message || 'session objective update failed');
        }
        currentSessionId = sessionId;
        persistOperatorState({
            session_id: sessionId,
            objective_id: objectiveId,
            objective_text: text,
            objective_scope: scope,
            objective_context: context,
            objective_tool: tool,
        });
        ensureSessionOption(sessionId, text.substring(0, 60) + (text.length > 60 ? '...' : '') + ' [' + scope + ']');
        document.getElementById('session-select').value = sessionId;
        setObjectiveResult('Objective declared: ' + (prompt.id || objectiveId));
        await loadSessions();
        document.getElementById('session-select').value = sessionId;
        currentSessionId = sessionId;
        await refreshAll();
    } catch (e) {
        setObjectiveResult('Objective declaration failed: ' + (e.message || 'unknown error'), true);
    }
}

async function handleWorkstationApprovalAction(approvalId, action) {
    if (!approvalId) {
        setStatus('unknown', 'Approval action unavailable: approval id missing');
        return;
    }
    const noteEl = document.querySelector('.workstation-approval-note[data-approval-id="' + cssAttr(approvalId) + '"]');
    const note = noteEl ? noteEl.value.trim() : '';
    try {
        const result = await window.CleanHouseAPI.resolveApprovalQueueItem(approvalId, action, note, 'dashboard');
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'approval update failed');
        }
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Approval update failed: ' + (e.message || 'unknown error'));
    }
}

function reviewPresenceEvidence() {
    const intervention = _lastPrimaryIntervention;
    if (!intervention) {
        setStatus('unknown', 'No intervention evidence is selected.');
        return;
    }
    const target = findInterventionTarget(intervention);
    if (!target) {
        setStatus('unknown', 'Intervention evidence is not visible in the current viewport.');
        return;
    }
    target.classList.add('presence-highlight');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => target.classList.remove('presence-highlight'), 2400);
}

async function stabilizePrimaryIntervention() {
    const intervention = _lastPrimaryIntervention;
    if (!intervention) {
        setStatus('unknown', 'No intervention is available to stabilize.');
        return;
    }
    const sessionId = currentSessionId || intervention.session_id || _lastWorkstation?.session?.session_id || '';
    if (!sessionId) {
        setStatus('unknown', 'Stabilize unavailable: session id missing');
        return;
    }
    const objective = _lastWorkstation?.operational_presence?.objective || {};
    const parentInterventionId = intervention.approval_id || intervention.notification_id || intervention.receipt_id || intervention.type || '';
    try {
        if (intervention.approval_id) {
            const approvalResult = await window.CleanHouseAPI.resolveApprovalQueueItem(
                intervention.approval_id,
                'needs_review',
                'Stabilize intervention: ' + (intervention.reason || intervention.summary || 'operator requested re-evaluation'),
                'dashboard'
            );
            if (!approvalResult || approvalResult.status !== 'ok') {
                throw new Error(approvalResult?.message || 'approval stabilization failed');
            }
        }
        if (intervention.notification_id) {
            const notificationResult = await window.CleanHouseAPI.ackNotification(intervention.notification_id);
            if (!notificationResult || notificationResult.status !== 'ok') {
                throw new Error(notificationResult?.message || 'notification acknowledgement failed');
            }
        }
        if (intervention.draft_correction_prompt) {
            const prompt = await window.CleanHouseAPI.submitPrompt(
                intervention.draft_correction_prompt,
                'Operational Presence stabilization',
                objective.scope || '',
                '',
                objective.tool_identity || 'CleanHouse',
                sessionId,
                objective.id || null,
                {
                    prompt_type: 'stabilization',
                    parent_intervention_id: parentInterventionId,
                    evidence_refs: intervention.evidence_refs || [],
                    metadata: {
                        source: 'operational_presence',
                        intervention_type: intervention.type || '',
                        approval_id: intervention.approval_id || '',
                        notification_id: intervention.notification_id || '',
                        receipt_id: intervention.receipt_id || '',
                    },
                }
            );
            if (!prompt || prompt.status !== 'ok') {
                throw new Error(prompt?.message || 'stabilization prompt failed');
            }
        }
        setStatus('unknown', 'Stabilize recorded: session requires re-evaluation before continuing.');
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Stabilize failed: ' + (e.message || 'unknown error'));
    }
}

async function copyPrimaryCorrection() {
    const intervention = _lastPrimaryIntervention;
    if (!intervention || !intervention.draft_correction_prompt) {
        setStatus('unknown', 'No correction prompt is available to copy.');
        return;
    }
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
        setStatus('unknown', 'Clipboard API unavailable for correction copy.');
        return;
    }
    try {
        await navigator.clipboard.writeText(intervention.draft_correction_prompt);
        setStatus('clear', 'Correction prompt copied.');
    } catch (e) {
        setStatus('degraded', 'Correction copy failed: ' + (e.message || 'unknown error'));
    }
}

function activeContinuityClaim() {
    const provenance = _lastContinuityProvenance || {};
    if (provenance.active_source && provenance.active_source.id) {
        return provenance.active_source;
    }
    const claims = Array.isArray(provenance.claims) ? provenance.claims : [];
    return claims.find(claim => claim && claim.id) || null;
}

async function acceptContinuity() {
    const claim = activeContinuityClaim();
    const sessionId = continuitySessionId();
    if (!claim || !claim.id || !sessionId) {
        setStatus('unknown', 'Accept continuity unavailable: claim or session missing.');
        return;
    }
    try {
        const result = await window.CleanHouseAPI.recordContinuityDecision(
            sessionId,
            claim.id,
            'accept',
            'Operator accepted this continuity source.',
            claim.evidence_refs || [],
            { source_type: claim.source_type || '', classification: claim.classification || '' },
            'dashboard'
        );
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'continuity decision failed');
        }
        setStatus('clear', 'Continuity decision recorded: accepted.');
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Accept continuity failed: ' + (e.message || 'unknown error'));
    }
}

async function ignoreContinuity() {
    const claim = activeContinuityClaim();
    const sessionId = continuitySessionId();
    if (!claim || !claim.id || !sessionId) {
        setStatus('unknown', 'Ignore unavailable: claim or session missing.');
        return;
    }
    try {
        const result = await window.CleanHouseAPI.recordContinuityDecision(
            sessionId,
            claim.id,
            'ignore',
            'Operator ignored this continuity source for the active session.',
            claim.evidence_refs || [],
            { source_type: claim.source_type || '', classification: claim.classification || '' },
            'dashboard'
        );
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'continuity decision failed');
        }
        setStatus('unknown', 'Continuity decision recorded: ignored.');
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Ignore continuity failed: ' + (e.message || 'unknown error'));
    }
}

async function searchContinuityDeeper() {
    const sessionId = continuitySessionId();
    if (!sessionId) {
        setStatus('unknown', 'Search deeper unavailable: session missing.');
        return;
    }
    const claim = activeContinuityClaim();
    const query = continuitySearchQuery(claim);
    if (!query) {
        setStatus('unknown', 'Search deeper unavailable: no bounded query source.');
        return;
    }
    try {
        const result = await window.CleanHouseAPI.searchContinuity(sessionId, query, {
            max_results: 8,
            max_files: 12,
            operator: 'dashboard'
        });
        if (!result || !['ok', 'no_results'].includes(result.status)) {
            throw new Error(result?.message || 'continuity search failed');
        }
        const count = result.search?.result_count ?? 0;
        setStatus(result.status === 'ok' ? 'clear' : 'unknown', 'Continuity search recorded: ' + count + ' result(s).');
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Search deeper failed: ' + (e.message || 'unknown error'));
    }
}

async function pinCanonicalContext() {
    const claim = activeContinuityClaim();
    const sessionId = continuitySessionId();
    const objective = _lastWorkstation?.operational_presence?.objective || {};
    if (!claim || !sessionId) {
        setStatus('unknown', 'Pin unavailable: continuity claim or session missing.');
        return;
    }
    const text = (claim.snippet || claim.summary || '').trim();
    if (!text) {
        setStatus('unknown', 'Pin unavailable: active claim has no recoverable text.');
        return;
    }
    try {
        const result = await window.CleanHouseAPI.pinContinuityContext(
            sessionId,
            text,
            claim.source_ref || '',
            claim.evidence_refs || [],
            objective.id || null,
            {
                source_claim_id: claim.id || '',
                source_type: claim.source_type || '',
                classification: claim.classification || '',
            },
            'dashboard'
        );
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'continuity pin failed');
        }
        setStatus('clear', 'Canonical context pinned.');
        await refreshAll();
    } catch (e) {
        setStatus('degraded', 'Pin canonical context failed: ' + (e.message || 'unknown error'));
    }
}

function continuitySessionId() {
    return currentSessionId || _lastContinuityProvenance?.session_id || _lastWorkstation?.session?.session_id || '';
}

function continuitySearchQuery(claim) {
    const candidates = [
        claim?.snippet,
        claim?.summary,
        _lastWorkstation?.operational_presence?.objective?.text,
        _lastWorkstation?.session?.summary,
        continuitySessionId(),
    ];
    return (candidates.find(value => typeof value === 'string' && value.trim()) || '').trim().slice(0, 200);
}

function findInterventionTarget(intervention) {
    if (intervention.approval_id) {
        const approval = document.querySelector('.approval-required-row[data-approval-id="' + cssAttr(intervention.approval_id) + '"]');
        if (approval) return approval;
    }
    if (intervention.receipt_id) {
        const receipt = document.querySelector('.receipt-card[data-receipt-id="' + cssAttr(intervention.receipt_id) + '"]');
        if (receipt) return receipt;
    }
    if (intervention.notification_id) {
        const notification = document.querySelector('.notification-row[data-notification-id="' + cssAttr(intervention.notification_id) + '"]');
        if (notification) return notification;
    }
    if (intervention.type === 'scope_drift') {
        return document.getElementById('deviation-alert-panel');
    }
    if (intervention.type === 'notification') {
        return document.getElementById('notification-tray-panel');
    }
    return document.getElementById('operational-presence-panel');
}

function focusDashboardNotification(notification) {
    if (!notification) return;
    const notificationId = typeof notification === 'string' ? notification : (notification.id || notification.notification_id || '');
    const sessionId = typeof notification === 'object' ? (notification.session_id || '') : '';
    if (sessionId && sessionId !== currentSessionId) {
        currentSessionId = sessionId;
        ensureSessionOption(sessionId, sessionId + ' [operator]');
        const select = document.getElementById('session-select');
        if (select) select.value = sessionId;
        const sessionInput = document.getElementById('operator-session-input');
        if (sessionInput) sessionInput.value = sessionId;
        persistOperatorState({ session_id: sessionId });
        fetchWorkstation(sessionId).then(() => focusDashboardNotification(notificationId));
        return;
    }
    focusNotificationRow(notificationId);
}

function focusNotificationRow(notificationId) {
    if (!notificationId) return false;
    const target = document.querySelector('.notification-row[data-notification-id="' + cssAttr(notificationId) + '"]');
    if (!target) return false;
    target.classList.add('presence-highlight');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => target.classList.remove('presence-highlight'), 3000);
    return true;
}

function applyPendingDashboardFocus() {
    if (!_pendingDashboardFocus) return;
    const pending = _pendingDashboardFocus;
    if (pending.session_id && pending.session_id !== currentSessionId) return;
    if (pending.notification_id && focusNotificationRow(pending.notification_id)) {
        _pendingDashboardFocus = null;
        clearDashboardDeepLinkParams();
    }
}

function clearDashboardDeepLinkParams() {
    if (!window.history || !window.history.replaceState) return;
    try {
        const url = new URL(window.location.href);
        url.searchParams.delete('notification_id');
        url.searchParams.delete('session_id');
        window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
    } catch (e) {
        /* best effort only */
    }
}

async function ackNotification(notificationId) {
    try {
        const result = await window.CleanHouseAPI.ackNotification(notificationId);
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'notification ack failed');
        }
        await fetchWorkstation(currentSessionId);
    } catch (e) {
        setStatus('degraded', 'Notification acknowledgement failed: ' + (e.message || 'unknown error'));
    }
}

function updateNotificationButton() {
    const btn = document.getElementById('notification-enable-btn');
    if (!btn) return;
    if (!('Notification' in window)) {
        _dashboardNotificationsEnabled = false;
        btn.disabled = true;
        btn.textContent = 'Browser Notifications Unavailable';
        return;
    }
    if (Notification.permission === 'granted') {
        _dashboardNotificationsEnabled = true;
        btn.disabled = true;
        btn.textContent = 'Browser Notifications Allowed (Dashboard Open)';
    } else if (Notification.permission === 'denied') {
        _dashboardNotificationsEnabled = false;
        btn.disabled = true;
        btn.textContent = 'Browser Notifications Denied';
    } else {
        _dashboardNotificationsEnabled = false;
        btn.disabled = false;
        btn.textContent = 'Enable Browser Notifications (Dashboard)';
    }
}

async function requestDashboardNotificationPermission() {
    if (!('Notification' in window)) return;
    try {
        const permission = await Notification.requestPermission();
        _dashboardNotificationsEnabled = permission === 'granted';
        updateNotificationButton();
        if (_lastWorkstation) {
            maybeSendBrowserNotifications(_lastWorkstation.notifications || []);
        }
    } catch (e) {
        _dashboardNotificationsEnabled = false;
        updateNotificationButton();
        setStatus('unknown', 'Browser notification permission unavailable: ' + (e.message || 'unknown error'));
    }
}

function maybeSendBrowserNotifications(notifications) {
    if (!('Notification' in window) || Notification.permission !== 'granted') {
        return;
    }
    _dashboardNotificationsEnabled = true;
    const now = Date.now();
    if (!_browserNotificationWindowStart || now - _browserNotificationWindowStart > BROWSER_NOTIFICATION_WINDOW_MS) {
        _browserNotificationWindowStart = now;
        _browserNotificationCount = 0;
    }
    for (const item of notifications || []) {
        if (item.acknowledged || _notifiedNotificationIds.has(item.id)) {
            continue;
        }
        if (_browserNotificationCount >= BROWSER_NOTIFICATION_MAX_PER_WINDOW) {
            break;
        }
        try {
            const notification = new Notification('CleanHouse dashboard ' + (item.notification_type || 'notification'), {
                body: item.summary || 'notification summary unavailable',
                tag: item.id || undefined
            });
            notification.onclick = () => {
                window.focus();
                focusDashboardNotification(item);
            };
            _notifiedNotificationIds.add(item.id);
            _browserNotificationCount += 1;
        } catch (e) {
            _notifiedNotificationIds.add(item.id);
            setStatus('unknown', 'Browser notification dispatch unavailable: ' + (e.message || 'unknown error'));
        }
    }
}

function browserNotificationStateLabel() {
    if (!('Notification' in window)) {
        return 'unavailable';
    }
    if (Notification.permission === 'granted') {
        return 'allowed_dashboard_open';
    }
    if (Notification.permission === 'denied') {
        return 'denied';
    }
    return 'not_requested';
}

function resolveOperatorSessionId(generateIfMissing) {
    const input = document.getElementById('operator-session-input');
    let sessionId = input ? input.value.trim() : '';
    if (!sessionId && currentSessionId) {
        sessionId = currentSessionId;
    }
    if (!sessionId && generateIfMissing) {
        sessionId = generateSessionId();
    }
    if (sessionId && input) {
        input.value = sessionId;
    }
    return sessionId;
}

function generateSessionId() {
    return 'operator-' + new Date().toISOString().replace(/[^0-9TZ]/g, '').toLowerCase();
}

function readOperatorState() {
    try {
        const raw = window.localStorage ? window.localStorage.getItem(OPERATOR_STATE_KEY) : null;
        return raw ? JSON.parse(raw) : null;
    } catch (e) {
        return null;
    }
}

function persistOperatorState(patch) {
    try {
        if (!window.localStorage) return;
        const current = readOperatorState() || {};
        const next = Object.assign({}, current, patch, { updated_at: new Date().toISOString() });
        window.localStorage.setItem(OPERATOR_STATE_KEY, JSON.stringify(next));
    } catch (e) {
        // Local storage is an operator convenience; the persisted runtime state remains authoritative.
    }
}

function setInputValue(id, value) {
    if (value === undefined || value === null || value === '') return;
    const el = document.getElementById(id);
    if (el) {
        el.value = value;
    }
}

function ensureSessionOption(sessionId, label) {
    const sel = document.getElementById('session-select');
    if (!sel || !sessionId) return;
    const existing = Array.from(sel.options).find(opt => opt.value === sessionId);
    if (existing) {
        existing.textContent = label || existing.textContent;
        return;
    }
    const opt = document.createElement('option');
    opt.value = sessionId;
    opt.textContent = label || sessionId;
    sel.appendChild(opt);
}

function setObjectiveResult(message, isError = false) {
    const el = document.getElementById('objective-declare-result');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('error', isError);
}

function renderTimeline(entries) {
    const body = document.getElementById('tl-body');
    document.getElementById('tl-count').textContent = entries.length;
    if (entries.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">⏱</div><div>No timeline events recorded for this session.</div></div>';
        return;
    }
    const sorted = [...entries].sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
    let html = '';
    for (const entry of sorted) {
        const ts = formatTime(entry.timestamp);
        const etype = entry.event_type || 'unknown';
        const status = entry.status || 'observed';
        const label = entry.label || '';
        const eventId = entry.event_id || '';
        const dataStr = entry.data ? describeData(entry.data) : '';
        const severity = entry.severity || '';
        const severityBadge = severity ? `<span class="severity-badge ${severity}">${severity}</span>` : '';
        html += `<div class="tl-entry">
            <div class="tl-header">
                <span class="tl-time">${ts}</span>
                <span class="tl-type">${escapeHtml(etype)}</span>
                ${severityBadge}
                <span class="tl-status ${status}">${status}</span>
            </div>
            <div class="tl-detail">${escapeHtml(label)}${dataStr ? ' — ' + escapeHtml(dataStr) : ''}</div>
            <div class="tl-evidence">${eventId ? '🔗 <a href="' + escapeHtml(eventId) + '">' + escapeHtml(eventId) + '</a>' : ''}</div>
        </div>`;
    }
    body.innerHTML = html;
}

function renderFileEvents(entries) {
    const body = document.getElementById('fs-events-body');
    document.getElementById('fs-event-count').textContent = entries.length;
    if (entries.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">🖿</div><div>No observed filesystem events yet.</div></div>';
        return;
    }
    const sorted = [...entries].sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''));
    let html = '';
    for (const entry of sorted) {
        const ts = formatTime(entry.timestamp);
        const path = entry.path || '';
        const etype = entry.event_type || 'unknown';
        const summary = entry.summary || '';
        html += `<div class="tl-entry">
            <div class="tl-header">
                <span class="tl-time">${ts}</span>
                <span class="tl-type">${escapeHtml(etype)}</span>
            </div>
            <div class="tl-detail">${escapeHtml(path)}</div>
            <div class="tl-evidence">${escapeHtml(summary)}</div>
        </div>`;
    }
    body.innerHTML = html;
}

function renderAlerts(alerts) {
    const body = document.getElementById('alert-body');
    document.getElementById('alert-count').textContent = alerts.length;
    if (alerts.length === 0) {
        body.innerHTML = '<div class="empty-state"><div class="icon">⚑</div><div>No alerts generated for this session.</div></div>';
        return;
    }
    let html = '';
    for (const alert of alerts) {
        const atype = alert.alert_type || 'unknown';
        const severity = alert.severity || 'low';
        const hasConfidence = typeof alert.confidence === 'number' && Number.isFinite(alert.confidence);
        const confidence = hasConfidence ? Math.max(0, Math.min(1, alert.confidence)) : null;
        const confPct = hasConfidence ? Math.round(confidence * 100) : null;
        const sourceIds = alert.source_ids || [];
        const desc = alert.description || '';
        const rationale = alert.rationale || '';
        const eventLinks = sourceIds.map(id =>
            `<a class="event-link" href="local://cleanhouse/timeline/${encodeURIComponent(id)}">${escapeHtml(id)}</a>`
        ).join(', ');
        html += `<div class="alert-card severity-${severity}">
            <div class="alert-header">
                <span class="alert-type">${escapeHtml(atype)}</span>
                <span class="severity-badge ${severity}">${severity}</span>
            </div>
            <div class="alert-desc">${escapeHtml(desc)}</div>
            <div class="alert-meta">
                <span class="conf-label">Confidence:</span>
                ${hasConfidence ? '<span class="conf-bar"><span class="conf-fill" style="width:' + confPct + '%"></span></span><span>' + confPct + '%</span>' : '<span>unknown</span>'}
                ${eventLinks ? '<span>| ' + eventLinks + '</span>' : ''}
            </div>
            ${rationale ? '<div class="alert-rationale">' + escapeHtml(rationale) + '</div>' : ''}
        </div>`;
    }
    body.innerHTML = html;
}

function renderReceiptScope(receipts, approvals = _lastApprovalQueue, replays = _lastReceiptReplays, bundles = _lastReceiptBundles) {
    const body = document.getElementById('receipt-scope-body');
    const receiptList = Array.isArray(receipts) ? receipts : (receipts ? [receipts] : []);
    if (receiptList.length === 0) {
        document.getElementById('scope-cluster-count').textContent = '0';
        body.innerHTML = '<div class="empty-state"><div class="icon">⌁</div><div>No receipt scope evidence recorded for this session.</div></div>';
        return;
    }

    const clusterCount = receiptList.reduce((total, receipt) => {
        const clusters = receipt.scope_analysis && Array.isArray(receipt.scope_analysis.path_clusters)
            ? receipt.scope_analysis.path_clusters
            : [];
        return total + clusters.length;
    }, 0);
    document.getElementById('scope-cluster-count').textContent = clusterCount;
    body.innerHTML = receiptList.map(receipt =>
        renderReceiptCard(receipt, findReceiptApproval(receipt, approvals), replays[receipt.id] || null, bundles[receipt.id] || null)
    ).join('');
}

function renderReceiptCard(receipt, approval, replay, bundle) {
    const analysis = receipt.scope_analysis || {};
    const metadata = receipt.metadata || {};
    const clusters = Array.isArray(analysis.path_clusters) ? analysis.path_clusters : [];
    const changedPaths = Array.isArray(analysis.changed_paths) ? analysis.changed_paths : [];
    const declaredScope = analysis.declared_scope || metadata.scope || '';
    const classification = analysis.classification || '';
    const verdict = receipt?.summary?.verdict || 'unknown';
    const outOfScopeCount = analysis.out_of_scope_count ?? 0;
    const changeCount = analysis.change_count ?? changedPaths.length;
    const scopeWeight = analysis.scope_weight;
    const scopePct = scopeWeightPercent(scopeWeight);
    const evidenceRows = replay && Array.isArray(replay.evidence_chain)
        ? replay.evidence_chain
        : collectReceiptEvidenceRows(receipt);
    const receiptId = receipt.id || '';
    const timestamp = receipt.timestamp || metadata.origin || '';
    const approvalState = receiptApprovalStatus(approval, replay);
    const replayHash = receiptReplayHash(receipt, replay);
    const replayStatus = replayStatusLabel(replay);
    const rootHash = receiptRootHash(receipt);
    const bundleStatus = bundleStatusLabel(bundle);
    const signatureStatus = bundleSignatureStatus(bundle);
    const signatureVerified = bundleSignatureVerifiedLabel(bundle);
    const clipboardAvailable = Boolean(navigator.clipboard && navigator.clipboard.writeText);

    const clustersHtml = clusters.length > 0
        ? clusters.map(renderScopeCluster).join('')
        : '<div class="scope-empty-line">unavailable</div>';
    const changedPathsHtml = changedPaths.length > 0
        ? renderPathList(changedPaths)
        : '<div class="scope-empty-line">unavailable</div>';
    const affectedPathsHtml = renderAffectedPathLinks(metadata.repo_path || '', changedPaths);
    const refsHtml = evidenceRows.length > 0
        ? evidenceRows.map(row =>
            '<div class="receipt-evidence-row">' +
            '<a href="' + escapeHtml(row.ref) + '">' + escapeHtml(row.ref) + '</a>' +
            '<span>' + escapeHtml(row.source || 'evidence') + (row.label ? ' · ' + escapeHtml(row.label) : '') + '</span>' +
            '</div>'
        ).join('')
        : '<div class="scope-empty-line">unavailable</div>';

    return '<div class="receipt-card" data-receipt-id="' + escapeHtml(receiptId) + '">' +
        '<div class="receipt-card-header">' +
        '  <div>' +
        '    <div class="receipt-card-title">' + escapeHtml(receiptId || 'unavailable') + '</div>' +
        '    <div class="receipt-card-meta">timestamp=' + escapeHtml(formatReceiptTimestamp(timestamp)) + '</div>' +
        '    <div class="receipt-utilities">' +
        '      <button class="receipt-copy-button" onclick="copyReceiptSummary(\'' + escapeJsString(receiptId) + '\')" title="' + (clipboardAvailable ? 'Copy receipt evidence summary' : 'Clipboard API unavailable') + '" ' + (clipboardAvailable ? '' : 'disabled') + '>Copy receipt summary</button>' +
        '    </div>' +
        '  </div>' +
        renderReceiptApprovalActions(receipt, approval) +
        '</div>' +
        '<div class="scope-summary">' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">timestamp</span>' +
        '    <span class="scope-code">' + escapeHtml(formatReceiptTimestamp(timestamp)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">receipt_verdict</span>' +
        '    <span class="scope-value relation-' + cssToken(verdict || 'unknown') + '">' + escapeHtml(valueOrUnavailable(verdict)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">scope_classification</span>' +
        '    <span class="scope-value relation-' + cssToken(classification || 'unavailable') + '">' + escapeHtml(valueOrUnavailable(classification)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">scope_weight</span>' +
        '    <span class="scope-weight-value">' + escapeHtml(formatScopeWeight(scopeWeight)) + '</span>' +
        '    <span class="scope-weight-bar"><span style="width:' + scopePct + '%"></span></span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">receipt_root_hash</span>' +
        '    <span class="scope-code">' + escapeHtml(valueOrUnavailable(rootHash)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">replay_status</span>' +
        '    <span class="scope-value relation-' + cssToken(replayStatus || 'unknown') + '">' + escapeHtml(valueOrUnavailable(replayStatus)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">replay_hash</span>' +
        '    <span class="scope-code">' + escapeHtml(replayHash) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">bundle_status</span>' +
        '    <span class="scope-value relation-' + cssToken(bundleStatus || 'unknown') + '">' + escapeHtml(valueOrUnavailable(bundleStatus)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">signature_status</span>' +
        '    <span class="scope-code">' + escapeHtml(valueOrUnavailable(signatureStatus)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">signature_verified</span>' +
        '    <span class="scope-code">' + escapeHtml(valueOrUnavailable(signatureVerified)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">approval_state</span>' +
        '    <span class="scope-code">' + escapeHtml(approvalState) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">declared_scope</span>' +
        '    <span class="scope-code">' + escapeHtml(valueOrUnavailable(declaredScope)) + '</span>' +
        '  </div>' +
        '  <div class="scope-summary-row">' +
        '    <span class="scope-label">changed_paths</span>' +
        '    <span class="scope-count-text">' + escapeHtml(formatChangedPathCount(outOfScopeCount, changeCount, changedPaths)) + '</span>' +
        '  </div>' +
        '</div>' +
        '<div class="scope-section">' +
        '  <div class="scope-section-title">Clustered Paths</div>' +
        '  <div class="scope-clusters">' + clustersHtml + '</div>' +
        '</div>' +
        '<div class="scope-section">' +
        '  <div class="scope-section-title">Changed Paths</div>' +
        changedPathsHtml +
        '</div>' +
        '<div class="scope-section">' +
        '  <div class="scope-section-title">Open Affected Paths</div>' +
        affectedPathsHtml +
        '</div>' +
        '<div class="scope-section">' +
        '  <div class="scope-section-title">Evidence Refs</div>' +
        '  <div class="receipt-evidence-list">' + refsHtml + '</div>' +
        '</div>' +
        renderReceiptBundleVerification(bundle) +
        renderReceiptReplay(replay) +
        '</div>';
}

function renderReceiptApprovalActions(receipt, approval) {
    const status = approval ? approval.status : 'unreviewed';
    const displayStatus = status === 'pending' || status === 'needs_review' ? 'needs review' : status;
    const receiptId = receipt.id || '';
    const approvedActive = status === 'approved' ? ' active' : '';
    const rejectedActive = status === 'rejected' ? ' active' : '';
    const reviewActive = status === 'pending' || status === 'needs_review' ? ' active' : '';
    const note = approval && (approval.reviewer_note || approval.resolution_note) ? (approval.reviewer_note || approval.resolution_note) : '';
    return '<div class="receipt-review">' +
        '<div class="receipt-review-status status-' + cssToken(status) + '">' + escapeHtml(displayStatus) + '</div>' +
        '<textarea class="receipt-review-note" data-receipt-id="' + escapeHtml(receiptId) + '" placeholder="Reviewer note">' + escapeHtml(note) + '</textarea>' +
        '<div class="receipt-review-actions">' +
        '  <button class="receipt-action approve' + approvedActive + '" onclick="handleReceiptApprovalAction(\'' + escapeJsString(receiptId) + '\', \'approved\')">Approve</button>' +
        '  <button class="receipt-action reject' + rejectedActive + '" onclick="handleReceiptApprovalAction(\'' + escapeJsString(receiptId) + '\', \'rejected\')">Reject</button>' +
        '  <button class="receipt-action review' + reviewActive + '" onclick="handleReceiptApprovalAction(\'' + escapeJsString(receiptId) + '\', \'needs_review\')">Needs review</button>' +
        '</div>' +
        '<div class="receipt-review-message" data-receipt-id="' + escapeHtml(receiptId) + '">' + escapeHtml(note) + '</div>' +
        renderApprovalHistory(approval) +
        '</div>';
}

function renderApprovalHistory(approval) {
    const history = approval && Array.isArray(approval.history) ? approval.history : [];
    if (history.length === 0) {
        return '<div class="approval-history empty">No approval history recorded.</div>';
    }
    const rows = history.map(entry =>
        '<div class="approval-history-row">' +
        '  <span>' + escapeHtml(formatTime(entry.timestamp)) + '</span>' +
        '  <strong>' + escapeHtml(entry.status || entry.action || '') + '</strong>' +
        '  <em>' + escapeHtml(entry.reviewer || '') + '</em>' +
        '  <small>' + escapeHtml(entry.note || '') + '</small>' +
        '</div>'
    ).join('');
    return '<div class="approval-history">' + rows + '</div>';
}

function renderReceiptReplay(replay) {
    if (!replay) {
        return '<div class="scope-section"><div class="scope-section-title">State Replay</div><div class="scope-empty-line">replay_status=unavailable</div></div>';
    }
    if (replay.status && replay.status !== 'ok') {
        return '<div class="scope-section"><div class="scope-section-title">State Replay</div><div class="scope-empty-line">replay_status=' + escapeHtml(replay.status) + ' · message=' + escapeHtml(replay.message || 'unavailable') + '</div></div>';
    }
    if (!replay.integrity) {
        return '<div class="scope-section"><div class="scope-section-title">State Replay</div><div class="scope-empty-line">replay_status=unknown · integrity=unavailable</div></div>';
    }
    const state = replay.state || {};
    const integrity = replay.integrity || {};
    return '<div class="scope-section">' +
        '  <div class="scope-section-title">State Replay</div>' +
        '  <div class="receipt-replay-summary">' +
        '    <span>replay_status=' + escapeHtml(replayStatusLabel(replay)) + '</span>' +
        '    <span>approval_state=' + escapeHtml(valueOrUnavailable(state.status)) + '</span>' +
        '    <span>history=' + escapeHtml(String(integrity.approval_history_count ?? 0)) + '</span>' +
        '    <span>evidence_refs=' + escapeHtml(String(integrity.evidence_ref_count ?? 0)) + '</span>' +
        '  </div>' +
        '  <div class="receipt-replay-hash">replay_hash=' + escapeHtml(replayHashValue(replay)) + '</div>' +
        '</div>';
}

function renderReceiptBundleVerification(bundle) {
    if (!bundle) {
        return '<div class="scope-section"><div class="scope-section-title">Bundle Signature</div><div class="scope-empty-line">bundle_status=unavailable · signature_status=unavailable</div></div>';
    }
    const verification = bundle.verification || {};
    const failedChecks = bundleVerificationChecks(verification, false);
    const unknownChecks = bundleVerificationChecks(verification, null);
    const checkText = failedChecks.length
        ? 'failed_checks=' + failedChecks.join(',')
        : 'failed_checks=0';
    const unknownText = unknownChecks.length
        ? ' · unknown_checks=' + unknownChecks.join(',')
        : ' · unknown_checks=0';
    const keyManagement = verification.key_management_status || bundle.manifest?.key_management?.mode || 'unavailable';
    return '<div class="scope-section">' +
        '  <div class="scope-section-title">Bundle Signature</div>' +
        '  <div class="receipt-replay-summary">' +
        '    <span>bundle_status=' + escapeHtml(bundleStatusLabel(bundle)) + '</span>' +
        '    <span>signature_status=' + escapeHtml(bundleSignatureStatus(bundle)) + '</span>' +
        '    <span>signature_verified=' + escapeHtml(bundleSignatureVerifiedLabel(bundle)) + '</span>' +
        '    <span>key_management=' + escapeHtml(valueOrUnavailable(keyManagement)) + '</span>' +
        '  </div>' +
        '  <div class="scope-empty-line">' + escapeHtml(checkText + unknownText) + '</div>' +
        '  <div class="receipt-replay-hash">manifest_hash=' + escapeHtml(valueOrUnavailable(bundle.integrity?.manifest_hash || bundle.manifest?.manifest_hash)) + '</div>' +
        '</div>';
}

function receiptApprovalStatus(approval, replay) {
    if (approval && approval.status) {
        return approval.status;
    }
    if (replay && replayStatusLabel(replay) === 'ok' && replay.state && replay.state.status) {
        return replay.state.status;
    }
    return 'unreviewed';
}

function receiptReplayHash(receipt, replay) {
    return replayHashValue(replay);
}

function formatReceiptTimestamp(value) {
    return value ? formatTime(value) : 'unavailable';
}

function formatChangedPathCount(outOfScopeCount, changeCount, changedPaths) {
    if (!Array.isArray(changedPaths) || changedPaths.length === 0) {
        return 'unavailable';
    }
    return String(outOfScopeCount) + ' outside declared scope / ' + String(changeCount) + ' total';
}

function renderAffectedPathLinks(repoPath, changedPaths) {
    if (!repoPath || !Array.isArray(changedPaths) || changedPaths.length === 0) {
        return '<div class="scope-empty-line">unavailable</div>';
    }
    return '<div class="affected-path-links">' + changedPaths.map(path => {
        const href = affectedPathHref(repoPath, path);
        return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noreferrer">' + escapeHtml(path) + '</a>';
    }).join('') + '</div>';
}

function affectedPathHref(repoPath, changedPath) {
    const base = String(repoPath || '').replace(/\/+$/, '');
    const rel = String(changedPath || '').replace(/^\/+/, '');
    const fullPath = base + '/' + rel;
    return 'file://' + fullPath.split('/').map(part => encodeURIComponent(part)).join('/');
}

function buildReceiptSummaryText(receipt, approval, replay, bundle) {
    const analysis = receipt.scope_analysis || {};
    const metadata = receipt.metadata || {};
    const changedPaths = Array.isArray(analysis.changed_paths) ? analysis.changed_paths : [];
    const lines = [
        'receipt_id=' + valueOrUnavailable(receipt.id),
        'timestamp=' + formatReceiptTimestamp(receipt.timestamp || metadata.origin || ''),
        'receipt_verdict=' + valueOrUnavailable(receipt?.summary?.verdict || 'unknown'),
        'receipt_root_hash=' + valueOrUnavailable(receiptRootHash(receipt)),
        'scope_classification=' + valueOrUnavailable(analysis.classification),
        'scope_weight=' + formatScopeWeight(analysis.scope_weight),
        'replay_status=' + replayStatusLabel(replay),
        'replay_hash=' + receiptReplayHash(receipt, replay),
        'bundle_status=' + bundleStatusLabel(bundle),
        'signature_status=' + bundleSignatureStatus(bundle),
        'signature_verified=' + bundleSignatureVerifiedLabel(bundle),
        'key_management=' + valueOrUnavailable(bundle?.verification?.key_management_status || bundle?.manifest?.key_management?.mode),
        'approval_state=' + receiptApprovalStatus(approval, replay),
        'declared_scope=' + valueOrUnavailable(analysis.declared_scope || metadata.scope),
        'changed_paths=' + (changedPaths.length ? changedPaths.join(', ') : 'unavailable'),
        'evidence_refs=' + receiptApprovalEvidenceRefs(receipt).join(', '),
    ];
    return lines.join('\n');
}

function renderScopeCluster(cluster) {
    const relation = cluster.relation || 'unknown';
    const paths = Array.isArray(cluster.changed_paths) ? cluster.changed_paths : [];
    const explanation = cluster.explanation || relationExplanation(relation);
    return '<div class="scope-cluster relation-' + cssToken(relation) + '">' +
        '<div class="scope-cluster-header">' +
        '  <span class="scope-cluster-name">' + escapeHtml(cluster.cluster || '(unclustered)') + '</span>' +
        '  <span class="scope-value relation-' + cssToken(relation) + '">' + escapeHtml(relation) + '</span>' +
        '</div>' +
        '<div class="scope-cluster-meta">' +
        '  <span>scope_weight=' + escapeHtml(formatScopeWeight(cluster.scope_weight)) + '</span>' +
        '  <span>' + escapeHtml(String(cluster.out_of_scope_count ?? 0)) + ' outside / ' + escapeHtml(String(cluster.change_count ?? paths.length)) + ' total</span>' +
        '</div>' +
        '<div class="scope-cluster-explain">' + escapeHtml(explanation) + '</div>' +
        renderPathList(paths) +
        '</div>';
}

function renderPathList(paths) {
    return '<ul class="scope-path-list">' + paths.map(path =>
        '<li>' + escapeHtml(path) + '</li>'
    ).join('') + '</ul>';
}

function collectReceiptEvidenceRows(receipt) {
    const rows = [];
    const seen = new Set();
    const add = (ref, source = '', label = '') => {
        if (!ref || seen.has(ref)) return;
        seen.add(ref);
        rows.push({ ref, source, label });
    };

    for (const entry of receipt.evidence_index || []) {
        add(entry.ref || entry.uri, entry.source, entry.label);
    }
    for (const alert of receipt.alerts || []) {
        for (const ref of alert.evidence_refs || []) {
            add(ref, alert.alert_type || 'alert', alert.severity || '');
        }
    }
    return rows;
}

function findReceiptApproval(receipt, approvals = _lastApprovalQueue) {
    if (!receipt || !receipt.id) return null;
    return (approvals || []).find(item =>
        item && item.metadata && item.metadata.receipt_id === receipt.id
    ) || null;
}

function findReceiptById(receiptId) {
    return (_lastReceipts || []).find(receipt => receipt.id === receiptId) || null;
}

function receiptEvidenceRef(receipt) {
    return 'local://cleanhouse/receipt/' + (receipt.id || '');
}

function receiptApprovalEvidenceRefs(receipt) {
    const refs = [receiptEvidenceRef(receipt)];
    for (const row of collectReceiptEvidenceRows(receipt)) {
        refs.push(row.ref);
    }
    return [...new Set(refs.filter(Boolean))];
}

function receiptApprovalReason(receipt) {
    const analysis = receipt.scope_analysis || {};
    return 'receipt review: classification=' + valueOrUnavailable(analysis.classification) +
        '; scope_weight=' + formatScopeWeight(analysis.scope_weight);
}

async function createReceiptApproval(receipt, action, reviewerNote) {
    const metadata = receipt.metadata || {};
    const analysis = receipt.scope_analysis || {};
    const actionLabel = action === 'needs_review' ? 'needs review' : action;
    return await window.CleanHouseAPI.createApprovalQueueItem(
        receipt.session_id || currentSessionId,
        actionLabel + ' receipt ' + (receipt.id || ''),
        receiptApprovalReason(receipt),
        receiptApprovalEvidenceRefs(receipt),
        metadata.prompt_id || null,
        metadata.objective_id || null,
        {
            source: 'dashboard_receipt_card',
            receipt_id: receipt.id || '',
            classification: valueOrUnavailable(analysis.classification),
            scope_weight: analysis.scope_weight ?? null,
        },
        reviewerNote,
        'dashboard'
    );
}

async function handleReceiptApprovalAction(receiptId, action) {
    const receipt = findReceiptById(receiptId);
    if (!receipt) return;
    const reviewerNote = getReceiptReviewNote(receiptId) || receiptApprovalReason(receipt);
    setReceiptReviewMessage(receiptId, 'Saving review state...');
    try {
        let approval = findReceiptApproval(receipt);
        if (!approval) {
            const created = await createReceiptApproval(receipt, action, reviewerNote);
            if (!created || created.status !== 'ok') {
                throw new Error(created?.message || 'approval queue create failed');
            }
            approval = created.approval;
        }
        const resolved = await window.CleanHouseAPI.resolveApprovalQueueItem(
            approval.id,
            action,
            reviewerNote,
            'dashboard'
        );
        if (!resolved || resolved.status !== 'ok') {
            throw new Error(resolved?.message || 'approval queue resolve failed');
        }
        await fetchReceiptScope(currentSessionId);
    } catch (e) {
        setReceiptReviewMessage(receiptId, 'Review action failed: ' + (e.message || 'unknown error'), true);
    }
}

async function copyReceiptSummary(receiptId) {
    const receipt = findReceiptById(receiptId);
    if (!receipt) return;
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
        setReceiptReviewMessage(receiptId, 'Copy unavailable: clipboard API unavailable.', true);
        return;
    }
    const approval = findReceiptApproval(receipt);
    const replay = _lastReceiptReplays[receiptId] || null;
    const bundle = _lastReceiptBundles[receiptId] || null;
    try {
        await navigator.clipboard.writeText(buildReceiptSummaryText(receipt, approval, replay, bundle));
        setReceiptReviewMessage(receiptId, 'Receipt summary copied.');
    } catch (e) {
        setReceiptReviewMessage(receiptId, 'Copy failed: ' + (e.message || 'unavailable'), true);
    }
}

function getReceiptReviewNote(receiptId) {
    const el = document.querySelector('.receipt-review-note[data-receipt-id="' + cssAttr(receiptId) + '"]');
    return el ? el.value.trim() : '';
}

function setReceiptReviewMessage(receiptId, message, isError = false) {
    const el = document.querySelector('.receipt-review-message[data-receipt-id="' + cssAttr(receiptId) + '"]');
    if (!el) return;
    el.textContent = message;
    el.classList.toggle('error', isError);
}

function formatScopeWeight(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value.toFixed(3);
    }
    if (value !== undefined && value !== null && value !== '') {
        return String(value);
    }
    return 'unavailable';
}

function valueOrUnavailable(value) {
    if (value === undefined || value === null || value === '') {
        return 'unavailable';
    }
    return String(value);
}

function normalizeReceiptBundleState(bundle) {
    if (!bundle || typeof bundle !== 'object') {
        return { status: 'unknown', message: 'bundle response unavailable' };
    }
    if (bundle.status !== 'ok') {
        return {
            status: bundle.status || 'unknown',
            message: bundle.message || 'bundle unavailable',
            verification: bundle.verification || {},
        };
    }
    return {
        status: 'ok',
        bundle_id: bundle.bundle?.bundle_id || '',
        manifest: bundle.bundle?.manifest || {},
        integrity: bundle.bundle?.integrity || {},
        signature: bundle.bundle?.manifest_signature || {},
        verification: bundle.verification || {},
    };
}

function replayStatusLabel(replay) {
    if (!replay) {
        return 'unavailable';
    }
    if (replay.status && replay.status !== 'ok') {
        return replay.status;
    }
    if (replay.integrity && replay.integrity.replay_hash) {
        return 'ok';
    }
    return replay.status || 'unknown';
}

function replayHashValue(replay) {
    return valueOrUnavailable(replay?.integrity?.replay_hash);
}

function receiptRootHash(receipt) {
    return receipt?.integrity?.root_hash || '';
}

function bundleStatusLabel(bundle) {
    if (!bundle) {
        return 'unavailable';
    }
    if (bundle.status && bundle.status !== 'ok') {
        return bundle.status;
    }
    if (bundle.integrity?.bundle_hash || bundle.integrity?.manifest_hash || bundle.verification?.bundle_hash_match !== undefined) {
        return 'ok';
    }
    return bundle.status || 'unknown';
}

function bundleSignatureStatus(bundle) {
    const verification = bundle?.verification || {};
    if (verification.signature_status) {
        return verification.signature_status;
    }
    if (verification.signature_verified === true) {
        return 'verified';
    }
    if (verification.signature_verified === false) {
        return 'failed';
    }
    return 'unavailable';
}

function bundleSignatureVerifiedLabel(bundle) {
    const status = bundleSignatureStatus(bundle);
    if (status === 'unavailable') return 'unavailable';
    const value = bundle?.verification?.signature_verified;
    if (value === true) return 'true';
    if (value === false) return 'false';
    return 'unknown';
}

function bundleVerificationChecks(verification, expected) {
    const keys = [
        'bundle_hash_match',
        'timeline_hash_match',
        'receipt_root_hash_match',
        'replay_hash_match',
        'manifest_hash_match',
        'manifest_contents_match',
        'bundle_id_match',
    ];
    return keys.filter(key => {
        if (expected === null) {
            return verification[key] !== true && verification[key] !== false;
        }
        return verification[key] === expected;
    });
}

function receiptTrustState(receipt, replay, bundle) {
    const verdict = receipt?.summary?.verdict || 'unknown';
    const replayStatus = replayStatusLabel(replay);
    const signatureStatus = bundleSignatureStatus(bundle);
    const failedChecks = bundleVerificationChecks(bundle?.verification || {}, false);
    const unknownChecks = bundleVerificationChecks(bundle?.verification || {}, null);
    if (replayStatus !== 'ok') {
        return replayStatus === 'unavailable' ? 'replay unavailable' : 'replay ' + replayStatus;
    }
    if (!bundle) {
        return 'signature unavailable';
    }
    if (failedChecks.length > 0) {
        return 'verification degraded';
    }
    if (unknownChecks.length > 0) {
        return 'verification unknown';
    }
    if (signatureStatus === 'verified') {
        return verdict;
    }
    if (signatureStatus === 'unavailable') {
        return 'signature unavailable';
    }
    return signatureStatus || verdict;
}

function rollbackStatusLabel(rollback) {
    if (!rollback) {
        return 'not recorded';
    }
    return valueOrUnavailable(rollback.status || rollback.rollback_status);
}

function rollbackVerificationLabel(rollback) {
    if (!rollback) {
        return 'unavailable';
    }
    const verification = rollback.verification || {};
    return valueOrUnavailable(verification.reason || verification.status || rollback.message);
}

function verificationCheckPassed(name, value) {
    return value === true;
}

function verificationCheckValue(value) {
    if (value === true) return 'true';
    if (value === false) return 'false';
    return valueOrUnavailable(value);
}

function scopeWeightPercent(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return 0;
    }
    return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

function relationExplanation(relation) {
    if (relation === 'outside_declared_scope') {
        return 'Changed path cluster does not match the declared scope prefix.';
    }
    if (relation === 'within_declared_scope') {
        return 'Changed path cluster matches the declared scope prefix.';
    }
    return 'Receipt did not include a path relation explanation.';
}

function cssToken(value) {
    return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
}

function cssAttr(value) {
    return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function escapeJsString(value) {
    return String(value || '')
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');
}

function updateStatus(entries) {
    const collectorState = collectorManifestStatus(_lastCollectorManifest);
    if (collectorState.state === 'degraded') {
        setStatus('degraded', 'Collector status degraded: ' + collectorState.detail);
        return;
    }
    if (collectorState.state === 'unknown') {
        setStatus('unknown', 'Collector status unknown: ' + collectorState.detail);
        return;
    }
    const timelineEntries = Array.isArray(entries) ? entries : [];
    if (timelineEntries.length === 0) {
        setStatus('unknown', 'No timeline evidence observed for selected session');
        return;
    }
    let hasCollectorFailure = false;
    let hasUnknown = false;
    let collectorDetail = '';
    for (const entry of timelineEntries) {
        if (entry.event_type === 'collector_failure') {
            hasCollectorFailure = true;
            collectorDetail = entry.label || 'collector error';
        }
        if (entry.status === 'unknown' || entry.status === 'inferred') {
            hasUnknown = true;
        }
    }
    if (hasCollectorFailure) {
        setStatus('degraded', 'Observed behavior pattern: collector failure detected — ' + collectorDetail);
    } else if (hasUnknown) {
        setStatus('unknown', 'Observed behavior pattern: some events have unknown or inferred status');
    } else {
        setStatus('clear', 'Current poll: no degraded or unknown timeline entries observed');
    }
}

function collectorManifestStatus(manifest) {
    if (!manifest || !Array.isArray(manifest.collectors)) {
        return { state: 'unknown', detail: 'collector manifest unavailable' };
    }
    const collectors = Array.isArray(manifest?.collectors) ? manifest.collectors : [];
    if (collectors.length === 0) {
        return { state: 'unknown', detail: 'collector manifest empty' };
    }
    const degradedStates = new Set(['failure', 'failed', 'error', 'critical']);
    const unknownStates = new Set(['unknown', 'dependency_missing', 'no_baseline', 'inactive', 'unavailable']);
    for (const collector of collectors) {
        const collectorStatus = collector.collector_status || '';
        const status = collector.status || '';
        if (degradedStates.has(collectorStatus) || degradedStates.has(status)) {
            return {
                state: 'degraded',
                detail: (collector.name || 'collector') + ' collector_status=' + valueOrUnavailable(collectorStatus || status),
            };
        }
    }
    for (const collector of collectors) {
        const collectorStatus = collector.collector_status || '';
        const status = collector.status || '';
        if (unknownStates.has(collectorStatus) || unknownStates.has(status)) {
            return {
                state: 'unknown',
                detail: (collector.name || 'collector') + ' collector_status=' + valueOrUnavailable(collectorStatus || status),
            };
        }
    }
    return { state: 'clear', detail: '' };
}

function setStatus(state, text) {
    const banner = document.getElementById('status-banner');
    banner.className = state;
    document.getElementById('status-text').textContent = text;
}

function clearPanels() {
    document.getElementById('tl-body').innerHTML = '<div class="empty-state"><div class="icon">⏱</div><div>No timeline events recorded for this session.</div></div>';
    document.getElementById('alert-body').innerHTML = '<div class="empty-state"><div class="icon">⚑</div><div>No alerts generated for this session.</div></div>';
    document.getElementById('receipt-scope-body').innerHTML = '<div class="empty-state"><div class="icon">⌁</div><div>No receipt scope evidence recorded for this session.</div></div>';
    document.getElementById('tl-count').textContent = '0';
    document.getElementById('alert-count').textContent = '0';
    document.getElementById('scope-cluster-count').textContent = '0';
    document.getElementById('fs-events-body').innerHTML = '<div class="empty-state"><div class="icon">🖿</div><div>No observed filesystem events yet.</div></div>';
    document.getElementById('fs-event-count').textContent = '0';
    renderSessionBar({ session_id: '', status: 'stopped' });
    document.getElementById('operational-presence-state').textContent = 'unknown';
    document.getElementById('continuity-provenance-state').textContent = 'unknown';
    document.getElementById('objective-feed-count').textContent = '0';
    document.getElementById('mutation-stream-count').textContent = '0';
    document.getElementById('deviation-alert-count').textContent = '0';
    document.getElementById('approval-required-count').textContent = '0';
    document.getElementById('receipt-replay-count').textContent = '0';
    document.getElementById('notification-tray-count').textContent = '0';
    document.getElementById('collector-manifest-count').textContent = '0';
    document.getElementById('lineage-graph-count').textContent = '0';
    document.getElementById('rollback-replay-count').textContent = '0';
    document.getElementById('operator-verification-count').textContent = '0';
    document.getElementById('operational-presence-body').innerHTML = '<div class="empty-state"><div class="icon">•</div><div>Operational presence unavailable.</div></div>';
    document.getElementById('continuity-provenance-body').innerHTML = '<div class="empty-state"><div class="icon">•</div><div>Continuity provenance unavailable.</div></div>';
    document.getElementById('objective-feed-body').innerHTML = '<div class="empty-state"><div class="icon">◎</div><div>No objective evidence recorded for this session.</div></div>';
    document.getElementById('mutation-stream-body').innerHTML = '<div class="empty-state"><div class="icon">≡</div><div>No local controlled mutations recorded for this session.</div></div>';
    document.getElementById('deviation-alert-body').innerHTML = '<div class="empty-state"><div class="icon">⚑</div><div>No deviation summaries recorded for this session.</div></div>';
    document.getElementById('approval-required-body').innerHTML = '<div class="empty-state"><div class="icon">✓</div><div>No approval-required records are pending.</div></div>';
    document.getElementById('receipt-replay-body').innerHTML = '<div class="empty-state"><div class="icon">⌁</div><div>No replayable receipts recorded for this session.</div></div>';
    document.getElementById('notification-tray').innerHTML = '<div class="empty-state"><div class="icon">•</div><div>No dashboard/browser notifications recorded.</div></div>';
    document.getElementById('collector-manifest-body').innerHTML = '<div class="empty-state"><div class="icon">▦</div><div>No collector health snapshot available.</div></div>';
    document.getElementById('lineage-graph-body').innerHTML = '<div class="empty-state"><div class="icon">⌬</div><div>No session evidence links available.</div></div>';
    document.getElementById('rollback-replay-body').innerHTML = '<div class="empty-state"><div class="icon">↺</div><div>No rollback/replay/signature state recorded for this session.</div></div>';
    document.getElementById('operator-verification-body').innerHTML = '<div class="empty-state"><div class="icon">□</div><div>No local HTTP evidence gap output available.</div></div>';
    renderRuntimeIndicator('unknown', 'no session selected');
    _lastReceipt = null;
    _lastReceipts = [];
    _lastApprovalQueue = [];
    _lastReceiptReplays = {};
    _lastReceiptBundles = {};
    _lastWorkstation = null;
    _lastPrimaryIntervention = null;
    _lastContinuityProvenance = null;
    _lastCollectorManifest = null;
    _lastLineageGraph = null;
    _lastRollbackReplayState = null;
    _lastOperatorVerification = null;
}

function formatTime(iso) {
    if (!iso) return 'unavailable';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
        return iso;
    }
}

function describeData(data) {
    if (!data) return '';
    if (typeof data === 'string') return data;
    const parts = [];
    if (data.command) parts.push(data.command);
    if (data.returncode !== undefined) parts.push('exit ' + data.returncode);
    if (data.duration !== undefined) parts.push(data.duration.toFixed(2) + 's');
    if (data.created_count !== undefined) parts.push('+' + data.created_count);
    if (data.modified_count !== undefined) parts.push('~' + data.modified_count);
    if (data.deleted_count !== undefined) parts.push('-' + data.deleted_count);
    return parts.join(' | ');
}

function escapeHtml(str) {
    if (typeof str !== 'string') return String(str || '');
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toggleAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
    if (document.getElementById('auto-refresh').checked) {
        autoRefreshTimer = setInterval(refreshAll, 2000);
        refreshAll();
    }
}

/* ── Report Observed Behavior ─────────────────────────── */

function gatherEvidenceRefs() {
    const refs = [];
    for (const entry of _lastTimelineEntries) {
        if (entry.event_id) refs.push('local://cleanhouse/timeline/' + entry.event_id);
    }
    for (const alert of _lastAlerts) {
        if (alert.evidence_refs) {
            for (const r of alert.evidence_refs) {
                if (r) refs.push(r);
            }
        }
    }
    if (_lastReceipt) {
        for (const row of collectReceiptEvidenceRows(_lastReceipt)) {
            refs.push(row.ref);
        }
    }
    return [...new Set(refs)];
}

function openReportPanel() {
    document.getElementById('report-modal').style.display = 'flex';
    if (!currentSessionId) {
        showReportEmpty();
        return;
    }
    showReportReview();
}

function closeReportPanel() {
    document.getElementById('report-modal').style.display = 'none';
}

function showReportEmpty() {
    const body = document.getElementById('report-body');
    const footer = document.getElementById('report-footer');
    body.innerHTML = '<div class="report-empty"><div class="icon">⚑</div><div>No session data available for reporting. Select a session first.</div></div>';
    footer.innerHTML = '<button class="btn-secondary" onclick="closeReportPanel()">Close</button>';
}

function showReportReview() {
    const refs = gatherEvidenceRefs();
    const sel = document.getElementById('session-select');
    const intentLabel = sel.options[sel.selectedIndex]?.text || currentSessionId;
    const refsHtml = refs.length > 0
        ? refs.map(r => '<a href="' + escapeHtml(r) + '">' + escapeHtml(r) + '</a>').join('')
        : '<div style="color:#5a7a9a;font-style:italic;">No evidence refs recorded for this session.</div>';

    const body = document.getElementById('report-body');
    body.innerHTML =
        '<div class="session-info">Session: <strong>' + escapeHtml(intentLabel) + '</strong></div>' +
        '<div class="form-row">' +
        '  <div class="form-group"><label for="r-type">Report Type</label><select id="r-type"><option value="incident">incident</option><option value="audit">audit</option><option value="info">info</option></select></div>' +
        '  <div class="form-group"><label for="r-contact">Contact</label><input id="r-contact" type="text" placeholder="analyst@example.com"></div>' +
        '</div>' +
        '<div class="form-row">' +
        '  <div class="form-group"><label for="r-target">Target</label><input id="r-target" type="text" placeholder="staging-1"></div>' +
        '  <div class="form-group"><label for="r-context">Context</label><input id="r-context" type="text" placeholder="weekly audit"></div>' +
        '</div>' +
        '<div class="evidence-section">' +
        '  <div class="evidence-count">Evidence Refs (' + refs.length + ' total — raw, unredacted)</div>' +
        '  <div class="evidence-list">' + refsHtml + '</div>' +
        '</div>';

    const footer = document.getElementById('report-footer');
    footer.innerHTML =
        '<button class="btn-secondary" onclick="closeReportPanel()">Cancel</button>' +
        '<button class="btn-primary" onclick="submitReport()">Generate Report</button>';
}

async function submitReport() {
    const reportType = document.getElementById('r-type').value;
    const contact = document.getElementById('r-contact').value;
    const target = document.getElementById('r-target').value;
    const context = document.getElementById('r-context').value;

    showReportSubmitting();

    try {
        const result = await window.CleanHouseAPI.exportReport(currentSessionId, reportType, contact, target, context);
        if (result && result.status === 'ok') {
            showReportResult(result);
        } else {
            showReportError(result?.message || 'Report generation returned unexpected status');
        }
    } catch (e) {
        showReportError(e.message || 'Network error during report generation');
    }
}

function showReportSubmitting() {
    const body = document.getElementById('report-body');
    const footer = document.getElementById('report-footer');
    body.innerHTML = '<div class="report-submitting"><div class="spinner"></div><div>Generating report...</div></div>';
    footer.innerHTML = '';
}

function showReportResult(result) {
    const refs = result.evidence_links || [];
    const refsHtml = refs.length > 0
        ? refs.map(r => '<a href="' + escapeHtml(r) + '">' + escapeHtml(r) + '</a>').join('')
        : '<div style="color:#5a7a9a;font-style:italic;">No evidence refs in report.</div>';

    const body = document.getElementById('report-body');
    body.innerHTML =
        '<div class="report-success">' +
        '  <div class="icon">✓</div>' +
        '  <div>Report generated successfully.</div>' +
        '  <div class="report-id">ID: ' + escapeHtml(result.id || '') + '</div>' +
        '</div>' +
        '<div class="evidence-section" style="margin-top:12px;">' +
        '  <div class="evidence-count">Evidence Refs (' + refs.length + ' total — preserved)</div>' +
        '  <div class="evidence-list">' + refsHtml + '</div>' +
        '</div>';

    const footer = document.getElementById('report-footer');
    footer.innerHTML = '<button class="btn-secondary" onclick="closeReportPanel()">Close</button>';
}

function showReportError(message) {
    const body = document.getElementById('report-body');
    const footer = document.getElementById('report-footer');
    body.innerHTML =
        '<div class="report-error">' +
        '  <div class="icon">✕</div>' +
        '  <div>' + escapeHtml(message) + '</div>' +
        '</div>';
    footer.innerHTML =
        '<button class="btn-secondary" onclick="closeReportPanel()">Close</button>' +
        '<button class="btn-primary" onclick="showReportReview()">Retry</button>';
}

/* ── Settings Panel ─────────────────────────── */

let _currentSettings = null;

function openSettingsPanel() {
    document.getElementById('settings-modal').style.display = 'flex';
    const body = document.getElementById('settings-body');
    body.innerHTML = '<p class="loading">Loading settings...</p>';
    const footer = document.getElementById('settings-footer');
    footer.innerHTML = '';
    loadSettings();
}

function closeSettingsPanel() {
    document.getElementById('settings-modal').style.display = 'none';
}

async function loadSettings() {
    const body = document.getElementById('settings-body');
    try {
        const data = await window.CleanHouseAPI.getSettings();
        if (data && data.status === 'ok' && data.settings) {
            _currentSettings = data.settings;
            renderSettings(data.settings);
        } else {
            body.innerHTML = '<div class="error-state">Failed to load settings: ' + (data?.message || 'unknown error') + '</div>';
        }
    } catch (e) {
        body.innerHTML = '<div class="error-state">Failed to load settings: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderSettings(settings) {
    const body = document.getElementById('settings-body');
    let html = '';

    /* Collectors */
    html += '<div class="settings-group"><h3>Collectors</h3>';
    if (settings.collectors) {
        for (const [name, enabled] of Object.entries(settings.collectors)) {
            const label = name.replace(/_/g, ' ');
            html += '<div class="setting-row">' +
                '<div><div class="setting-label">' + escapeHtml(label) + '</div></div>' +
                '<div class="setting-control"><button class="setting-toggle ' + (enabled ? 'on' : '') + '" data-group="collectors" data-key="' + escapeHtml(name) + '" onclick="toggleSetting(this)"></button></div>' +
                '</div>';
        }
    }
    html += '</div>';

    /* Risk Thresholds */
    html += '<div class="settings-group"><h3>Risk Thresholds</h3>';
    if (settings.risk_thresholds) {
        const rt = settings.risk_thresholds;
        if (rt.alert_signal_count) {
            for (const [sev, count] of Object.entries(rt.alert_signal_count)) {
                html += '<div class="setting-row">' +
                    '<div><div class="setting-label">alert_signal_count (' + escapeHtml(sev) + ')</div></div>' +
                    '<div class="setting-control"><input class="setting-input" type="number" min="0" value="' + count + '" data-group="risk_thresholds" data-key="alert_signal_count.' + escapeHtml(sev) + '"></div>' +
                    '</div>';
            }
        }
        if (rt.alert_confidence_min !== undefined) {
            html += '<div class="setting-row">' +
                '<div><div class="setting-label">alert_confidence_min</div></div>' +
                '<div class="setting-control"><input class="setting-input" type="number" min="0" max="1" step="0.05" value="' + rt.alert_confidence_min + '" data-group="risk_thresholds" data-key="alert_confidence_min"></div>' +
                '</div>';
        }
    }
    html += '</div>';

    /* Retention */
    html += '<div class="settings-group"><h3>Retention Limits</h3>';
    if (settings.retention) {
        for (const [key, val] of Object.entries(settings.retention)) {
            const label = key.replace(/_/g, ' ');
            html += '<div class="setting-row">' +
                '<div><div class="setting-label">' + escapeHtml(label) + '</div></div>' +
                '<div class="setting-control"><input class="setting-input" type="number" min="1" value="' + val + '" data-group="retention" data-key="' + escapeHtml(key) + '"></div>' +
                '</div>';
        }
    }
    html += '</div>';

    /* Evidence Depth */
    html += '<div class="settings-group"><h3>Evidence Depth</h3>';
    if (settings.evidence_depth) {
        for (const [key, val] of Object.entries(settings.evidence_depth)) {
            const label = key.replace(/_/g, ' ');
            html += '<div class="setting-row">' +
                '<div><div class="setting-label">' + escapeHtml(label) + '</div></div>' +
                '<div class="setting-control"><input class="setting-input" type="number" min="0.1" step="any" value="' + val + '" data-group="evidence_depth" data-key="' + escapeHtml(key) + '"></div>' +
                '</div>';
        }
    }
    html += '</div>';

    html += '<div id="settings-result"></div>';

    body.innerHTML = html;

    const footer = document.getElementById('settings-footer');
    footer.innerHTML =
        '<button class="btn-secondary" onclick="closeSettingsPanel()">Close</button>' +
        '<button class="btn-primary" onclick="saveSettings()">Save Settings</button>';
}

function toggleSetting(btn) {
    const isOn = btn.classList.contains('on');
    if (isOn) {
        btn.classList.remove('on');
    } else {
        btn.classList.add('on');
    }
}

function buildSettingsPayload() {
    const payload = {};
    const toggles = document.querySelectorAll('.setting-toggle');
    for (const btn of toggles) {
        const group = btn.dataset.group;
        const key = btn.dataset.key;
        const val = btn.classList.contains('on');
        if (!payload[group]) payload[group] = {};
        payload[group][key] = val;
    }
    const inputs = document.querySelectorAll('.setting-input');
    for (const input of inputs) {
        const group = input.dataset.group;
        const key = input.dataset.key;
        let val = parseFloat(input.value);
        if (Number.isInteger(val)) val = parseInt(input.value, 10);
        if (!payload[group]) payload[group] = {};
        if (key.includes('.')) {
            const [parent, child] = key.split('.');
            if (!payload[group][parent]) payload[group][parent] = {};
            payload[group][parent][child] = val;
        } else {
            payload[group][key] = val;
        }
    }
    return payload;
}

async function saveSettings() {
    const payload = buildSettingsPayload();
    const resultDiv = document.getElementById('settings-result');
    resultDiv.innerHTML = '<div class="report-submitting" style="padding:12px;"><div class="spinner" style="width:18px;height:18px;border-width:2px;display:inline-block;vertical-align:middle;margin:0 8px 0 0;"></div>Saving...</div>';
    try {
        const result = await window.CleanHouseAPI.updateSettings(payload);
        if (result && result.status === 'ok') {
            resultDiv.innerHTML = '<div class="settings-result success">Settings saved.<div class="saved-at">Updated: ' + escapeHtml(result.updated || '') + '</div></div>';
            _currentSettings = result.settings;
        } else {
            resultDiv.innerHTML = '<div class="settings-result error">' + escapeHtml(result?.message || 'Save failed') + '</div>';
        }
    } catch (e) {
        resultDiv.innerHTML = '<div class="settings-result error">Network error: ' + escapeHtml(e.message) + '</div>';
    }
}
