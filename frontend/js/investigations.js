let applications = [];
let selectedApp = null;
let selectedFilter = '';
let runtimeNotifications = [];

function byId(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function setText(id, value) {
    const el = byId(id);
    if (el) el.textContent = value || 'Unknown';
}

function showView(view) {
    const target = view === 'app-dashboard' ? 'app-dashboard' : view;
    document.querySelectorAll('[data-view-panel]').forEach(panel => {
        panel.hidden = panel.dataset.viewPanel !== target;
    });
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.view === view);
    });
    if (view === 'applications') history.replaceState(null, '', '/applications');
    if (view === 'network') history.replaceState(null, '', '/network');
    if (view === 'files') history.replaceState(null, '', '/files');
    if (view === 'custom') history.replaceState(null, '', '/custom-scan');
    if (view === 'home') history.replaceState(null, '', '/investigations');
}

function normalizedText(value) {
    return String(value ?? '').trim().toLowerCase();
}

function notificationText(notification) {
    try {
        return JSON.stringify(notification || {}).toLowerCase();
    } catch (error) {
        return String(notification || '').toLowerCase();
    }
}

function routeContext(id, message) {
    const el = byId(id);
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
}

function highlightElement(id) {
    const el = byId(id);
    if (!el) return;
    el.classList.remove('route-highlight');
    void el.offsetWidth;
    el.classList.add('route-highlight');
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function appBadge(app) {
    if (!app.badge) return '';
    return '<span class="app-badge" aria-label="New app">' + escapeHtml(app.badge_count || app.badge) + '</span>';
}

function appCard(app, selectable = false) {
    const checked = selectedFilter && customFilterMatch(app, selectedFilter) ? ' checked' : '';
    return (
        '<button class="app-card" type="button" data-app-id="' + escapeHtml(app.id) + '">' +
        '  <span class="app-icon-wrap">' + appBadge(app) + '<img class="app-icon" src="' + escapeHtml(app.icon_url) + '" alt="" loading="lazy" decoding="async"></span>' +
        '  <strong>' + escapeHtml(app.name) + '</strong>' +
        '  <small>' + escapeHtml(app.running ? 'Running' : app.category || 'Installed') + '</small>' +
        (selectable ? '<label class="scan-check"><input type="checkbox" value="' + escapeHtml(app.id) + '"' + checked + '> Include</label>' : '') +
        '</button>'
    );
}

function renderApplications() {
    const grid = byId('app-grid');
    if (!applications.length) {
        grid.innerHTML = '<div class="empty-state">No applications were discovered yet.</div>';
        return;
    }
    grid.innerHTML = applications.map(app => appCard(app)).join('');
    grid.querySelectorAll('.app-card').forEach(card => {
        card.addEventListener('click', () => openAppDashboard(card.dataset.appId));
    });
    setText('apps-area-status', `${applications.length} apps, ${applications.filter(app => app.badge).length} new`);
    renderCustomApps();
}

function renderCustomApps() {
    const list = byId('custom-app-list');
    if (!list) return;
    list.innerHTML = applications.map(app => appCard(app, true)).join('');
    list.querySelectorAll('.app-card').forEach(card => {
        card.addEventListener('click', event => {
            if (event.target && event.target.tagName === 'INPUT') return;
            const input = card.querySelector('input');
            if (input) input.checked = !input.checked;
        });
    });
}

async function loadApplications(refresh = false) {
    byId('app-grid').innerHTML = '<div class="empty-state">Loading applications from this Mac...</div>';
    const payload = await window.CleanHouseAPI.getApplications(refresh);
    applications = Array.isArray(payload.apps) ? payload.apps : [];
    renderApplications();
}

function processRows(app, selectable = false) {
    const rows = Array.isArray(app.processes) ? app.processes : [];
    if (!rows.length) return '<div class="empty-state">No running processes are currently matched to this app.</div>';
    return rows.map(row =>
        '<label class="process-row">' +
        (selectable ? '  <input type="checkbox" value="' + escapeHtml(row.pid || '') + '">' : '') +
        '  <span><strong>' + escapeHtml(row.command || row.process || row.name || 'Process') + '</strong><small>PID ' + escapeHtml(row.pid || 'unknown') + '</small></span>' +
        '  <span>CPU ' + escapeHtml(row.cpu ?? row.cpu_percent ?? 'unknown') + '</span>' +
        '  <span>Memory ' + escapeHtml(row.rss_bytes ? `${Math.round(Number(row.rss_bytes) / 1024 / 1024)} MB` : row.mem ?? 'unknown') + '</span>' +
        '</label>'
    ).join('');
}

function openAppDashboard(appId) {
    selectedApp = applications.find(app => app.id === appId) || applications[0] || null;
    if (!selectedApp) return;
    setText('selected-app-name', selectedApp.name);
    setText('selected-app-subtitle', selectedApp.bundle_id);
    byId('selected-app-icon').src = selectedApp.icon_url;
    byId('selected-app-icon').alt = selectedApp.name;
    setText('app-identity-name', selectedApp.name);
    setText('app-identity-bundle', selectedApp.bundle_id);
    setText('app-identity-version', selectedApp.version);
    setText('app-identity-path', selectedApp.path);
    setText('app-running-state', selectedApp.running ? 'Running' : 'Not running');
    setText('app-audit-state', selectedApp.audit_status || 'adopted');
    setText('app-badge-state', selectedApp.badge || 'None');
    byId('app-process-list').innerHTML = processRows(selectedApp, false);
    byId('app-custom-process-list').innerHTML = processRows(selectedApp, true);
    byId('app-custom-scan-panel').hidden = true;
    byId('app-scan-result').hidden = true;
    byId('evidence').hidden = true;
    showView('app-dashboard');
    history.replaceState(null, '', `/applications/${encodeURIComponent(selectedApp.id)}`);
}

function findAppForNotification(notification) {
    const metadata = notification?.metadata && typeof notification.metadata === 'object' ? notification.metadata : {};
    const candidates = [
        notification?.app_id,
        notification?.application_id,
        notification?.application,
        notification?.app,
        notification?.app_name,
        notification?.subject,
        notification?.subject_name,
        metadata.app_id,
        metadata.application_id,
        metadata.application,
        metadata.app,
        metadata.app_name,
        metadata.bundle_id,
        metadata.bundle_identifier,
        metadata.process_name,
        metadata.path,
        metadata.file_path,
    ].filter(Boolean).map(normalizedText);
    const text = notificationText(notification);
    return applications.find(app => {
        const fields = [
            app.id,
            app.name,
            app.bundle_id,
            app.path,
        ].filter(Boolean).map(normalizedText);
        if (fields.some(field => candidates.includes(field))) return true;
        const name = normalizedText(app.name);
        const bundle = normalizedText(app.bundle_id);
        const path = normalizedText(app.path);
        return Boolean(
            (name && text.includes(name)) ||
            (bundle && text.includes(bundle)) ||
            (path && text.includes(path))
        );
    }) || null;
}

function routeForNotification(notification) {
    const text = notificationText(notification);
    const metadata = notification?.metadata && typeof notification.metadata === 'object' ? notification.metadata : {};
    const app = findAppForNotification(notification);
    if (app) {
        return {
            view: 'app-dashboard',
            appId: app.id,
            targetId: text.includes('process') || text.includes('pid') ? 'app-process-list' : 'app-dashboard',
            contextId: 'app-route-context',
            message: `Opened from notification: ${notification.summary || app.name}`,
        };
    }
    const surface = normalizedText(metadata.surface || metadata.domain || notification?.source || '');
    const type = normalizedText(notification?.notification_type || '');
    if (
        surface.includes('network') ||
        type.includes('port') ||
        type.includes('network') ||
        text.includes('opened port') ||
        text.includes('port ') ||
        text.includes('domain') ||
        text.includes('dns') ||
        text.includes('connection') ||
        text.includes('interface') ||
        text.includes('wireshark')
    ) {
        return {
            view: 'network',
            targetId: 'network-results',
            contextId: 'network-route-context',
            message: `Opened from notification: ${notification.summary || 'Network activity'}`,
        };
    }
    if (
        surface.includes('file') ||
        surface.includes('integrity') ||
        type.includes('file') ||
        type.includes('integrity') ||
        text.includes('file ') ||
        text.includes('folder') ||
        text.includes('created') ||
        text.includes('deleted') ||
        text.includes('modified') ||
        text.includes('integrity')
    ) {
        return {
            view: 'files',
            targetId: 'files-status',
            contextId: 'files-route-context',
            message: `Opened from notification: ${notification.summary || 'File activity'}`,
        };
    }
    if (type.includes('process') || text.includes('process') || text.includes('pid')) {
        return {
            view: 'applications',
            targetId: 'app-grid',
            contextId: '',
            message: '',
        };
    }
    return {
        view: 'home',
        targetId: 'home',
        contextId: '',
        message: '',
    };
}

function renderEvidence(report) {
    const evidence = report.evidence || {};
    byId('evidence').hidden = false;
    byId('evidence-timeline').innerHTML = '<p><strong>Question</strong></p><p>' + escapeHtml(report.question || 'Application scan') + '</p><p><strong>Status</strong></p><p>' + escapeHtml(report.status || 'unknown') + '</p>';
    byId('evidence-process').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.runtime_activity || {}, null, 2)) + '</pre>';
    byId('evidence-file').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.file_activity || {}, null, 2)) + '</pre>';
    byId('evidence-network').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.network_activity || {}, null, 2)) + '</pre>';
    byId('evidence-receipt').innerHTML =
        '<p><strong>Evidence artifact</strong></p><code>' + escapeHtml(evidence.evidence_artifact_path || 'Unavailable') + '</code>' +
        '<p><strong>Receipt artifact</strong></p><code>' + escapeHtml(evidence.receipt_artifact_path || 'Unavailable') + '</code>';
}

function renderAppScan(report) {
    const findings = Array.isArray(report.finding_objects) ? report.finding_objects : [];
    byId('app-scan-result').hidden = false;
    setText('app-result-title', findings[0]?.title || `${selectedApp?.name || 'App'} scan complete`);
    setText('app-result-summary', findings[0]?.summary || report.next_action || 'Scan complete.');
    byId('app-finding-list').innerHTML = findings.map(finding =>
        '<article class="operator-finding-card">' +
        '  <h4>' + escapeHtml(finding.title || 'Finding') + '</h4>' +
        '  <dl class="finding-meta">' +
        '    <div><dt>Severity</dt><dd>' + escapeHtml(finding.severity || 'Unknown') + '</dd></div>' +
        '    <div><dt>Confidence</dt><dd>' + escapeHtml(finding.confidence ?? 'Unknown') + '</dd></div>' +
        '    <div><dt>Evidence Strength</dt><dd>' + escapeHtml(finding.evidence_strength || 'Unknown') + '</dd></div>' +
        '  </dl>' +
        '  <p>' + escapeHtml(finding.next_action || report.next_action || 'No next action returned.') + '</p>' +
        '</article>'
    ).join('');
    renderEvidence(report);
}

async function scanSelectedApp() {
    if (!selectedApp) return;
    byId('scan-app-btn').disabled = true;
    setText('app-result-title', 'Scanning app...');
    try {
        const report = await window.CleanHouseAPI.runApplicationInvestigation({
            session_id: `app-scan-${selectedApp.id}`,
            question: `Scan ${selectedApp.name}.`,
            target: selectedApp.path,
            application: selectedApp.id,
        });
        renderAppScan(report);
    } catch (error) {
        byId('app-scan-result').hidden = false;
        setText('app-result-title', 'Scan failed');
        setText('app-result-summary', error.message || String(error));
    } finally {
        byId('scan-app-btn').disabled = false;
    }
}

function scanSelectedProcesses() {
    const selected = Array.from(byId('app-custom-process-list').querySelectorAll('input:checked')).map(input => input.value);
    if (!selected.length) {
        setText('app-custom-scan-status', 'Select at least one app process or component first.');
        return;
    }
    setText('app-custom-scan-status', `Custom app scan prepared for ${selected.length} process/component item(s). Evidence attaches to this app dashboard.`);
}

function toggleAppCustomScan() {
    const panel = byId('app-custom-scan-panel');
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) panel.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function runSystemScan() {
    byId('system-scan-btn').disabled = true;
    byId('scan-results').hidden = false;
    setText('scan-status', 'Scanning');
    try {
        const result = await window.CleanHouseAPI.runSystemScan();
        setText('scan-status', result.status || 'unknown');
        setText('scan-findings', String(result.finding_count ?? 0));
        setText('scan-evidence', result.evidence_ref || 'Unavailable');
        setText('scan-receipt', result.receipt_ref || 'Unavailable');
        setText('scan-next-action', result.next_action || 'Review app dashboards.');
    } catch (error) {
        setText('scan-status', 'failed');
        setText('scan-next-action', error.message || String(error));
    } finally {
        byId('system-scan-btn').disabled = false;
    }
}

async function loadWireshark() {
    const status = await window.CleanHouseAPI.getWiresharkStatus();
    setText('network-area-status', status.status === 'available' ? 'Wireshark ready' : 'Setup required');
    setText('wireshark-message', status.message);
    setText('wireshark-permission', status.permission_state);
    setText('wireshark-fallback', status.fallback);
}

async function loadNotificationBadge() {
    const badge = byId('notification-center-badge');
    if (!badge || !window.CleanHouseAPI?.getRuntime) return;
    try {
        const runtime = await window.CleanHouseAPI.getRuntime();
        runtimeNotifications = Array.isArray(runtime?.runtime_notifications) ? runtime.runtime_notifications : [];
        const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
        badge.hidden = unread === 0;
        badge.textContent = unread > 99 ? '99+' : String(unread);
        renderNotificationCenter();
    } catch (error) {
        runtimeNotifications = [];
        badge.hidden = true;
        renderNotificationCenter('Notifications unavailable.');
    }
}

function notificationIcon(notification, app) {
    if (app?.icon_url) {
        return '<span class="notification-icon"><img src="' + escapeHtml(app.icon_url) + '" alt=""></span>';
    }
    const type = normalizedText(notification?.notification_type || notification?.source || '');
    if (type.includes('network') || type.includes('port')) return '<span class="notification-icon">NW</span>';
    if (type.includes('file') || type.includes('integrity')) return '<span class="notification-icon">FI</span>';
    if (type.includes('process')) return '<span class="notification-icon">PR</span>';
    return '<span class="notification-icon">CH</span>';
}

function renderNotificationCenter(errorMessage = '') {
    const list = byId('notification-list');
    const count = byId('notification-center-count');
    if (!list) return;
    const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
    if (count) count.textContent = unread ? `${unread} unread` : 'No unread';
    if (errorMessage) {
        list.innerHTML = '<p class="notification-empty">' + escapeHtml(errorMessage) + '</p>';
        return;
    }
    if (!runtimeNotifications.length) {
        list.innerHTML = '<p class="notification-empty">No live CleanHouse notifications.</p>';
        return;
    }
    list.innerHTML = runtimeNotifications.map((notification, index) => {
        const app = findAppForNotification(notification);
        const route = routeForNotification(notification);
        const summary = notification.summary || notification.notification_type || 'CleanHouse notification';
        const detail = route.view === 'app-dashboard'
            ? `Opens ${app?.name || 'app'} dashboard`
            : route.view === 'network'
                ? 'Opens Network evidence'
                : route.view === 'files'
                    ? 'Opens File evidence'
                    : 'Opens CleanHouse overview';
        return (
            '<button class="notification-item" type="button" role="menuitem" data-notification-index="' + index + '">' +
            notificationIcon(notification, app) +
            '<span class="notification-copy">' +
            '  <strong>' + escapeHtml(summary) + '</strong>' +
            '  <span>' + escapeHtml(detail) + '</span>' +
            '  <small>' + escapeHtml(notification.severity || notification.notification_type || 'notification') + '</small>' +
            '</span>' +
            '</button>'
        );
    }).join('');
    list.querySelectorAll('.notification-item').forEach(button => {
        button.addEventListener('click', () => openNotification(runtimeNotifications[Number(button.dataset.notificationIndex)]));
    });
}

function setNotificationDropdown(open) {
    const menu = byId('notification-center-menu');
    const button = byId('notification-center-button');
    if (!menu || !button) return;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
}

async function openNotification(notification) {
    if (!notification) return;
    const route = routeForNotification(notification);
    setNotificationDropdown(false);
    if (notification.id && window.CleanHouseAPI?.ackNotification) {
        window.CleanHouseAPI.ackNotification(notification.id).catch(() => {});
        notification.acknowledged = true;
        renderNotificationCenter();
        const badge = byId('notification-center-badge');
        const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
        if (badge) {
            badge.hidden = unread === 0;
            badge.textContent = unread > 99 ? '99+' : String(unread);
        }
    }
    if (route.view === 'app-dashboard') {
        openAppDashboard(route.appId);
    } else {
        showView(route.view);
    }
    if (route.contextId) routeContext(route.contextId, route.message);
    if (route.view === 'network' && route.message && !byId('network-results').textContent.trim()) {
        byId('network-results').innerHTML = '<details class="case-item" open><summary>Selected notification</summary><p>' + escapeHtml(route.message) + '</p></details>';
    }
    window.setTimeout(() => highlightElement(route.targetId), 50);
}

async function scanNetwork() {
    const wireshark = await window.CleanHouseAPI.getWiresharkStatus();
    const fallback = await window.CleanHouseAPI.getNetwork(true);
    byId('network-results').innerHTML =
        '<details class="case-item" open><summary>Wireshark</summary><pre>' + escapeHtml(JSON.stringify(wireshark, null, 2)) + '</pre></details>' +
        '<details class="case-item"><summary>Fallback Network Metadata</summary><pre>' + escapeHtml(JSON.stringify(fallback.data || fallback, null, 2)) + '</pre></details>';
}

function customFilterMatch(app, filter) {
    if (filter === 'running') return Boolean(app.running);
    if (filter === 'new') return Boolean(app.badge);
    if (filter === 'attention') return Boolean(app.badge) || Boolean(app.running);
    return app.category === filter;
}

function applyCustomFilter(filter) {
    selectedFilter = filter;
    renderCustomApps();
    setText('custom-scan-status', `Selected filter: ${filter}.`);
}

function runCustomScan() {
    const selected = Array.from(byId('custom-app-list').querySelectorAll('input:checked')).map(input => input.value);
    setText('custom-scan-status', selected.length ? `Custom scan prepared for ${selected.length} app(s).` : 'Choose at least one app or filter.');
}

function init() {
    document.querySelectorAll('[data-view]').forEach(link => {
        link.addEventListener('click', event => {
            event.preventDefault();
            showView(link.dataset.view);
        });
    });
    byId('system-scan-btn').addEventListener('click', runSystemScan);
    byId('refresh-apps-btn').addEventListener('click', () => loadApplications(true));
    byId('scan-app-btn').addEventListener('click', scanSelectedApp);
    byId('app-custom-scan-toggle').addEventListener('click', toggleAppCustomScan);
    byId('scan-processes-btn').addEventListener('click', scanSelectedProcesses);
    byId('scan-network-btn').addEventListener('click', scanNetwork);
    byId('scan-files-btn').addEventListener('click', () => setText('files-status', 'Files scan template ready. File evidence will attach through CleanHouse event and integrity collectors.'));
    byId('run-custom-scan-btn').addEventListener('click', runCustomScan);
    document.querySelectorAll('[data-filter]').forEach(button => {
        button.addEventListener('click', () => applyCustomFilter(button.dataset.filter));
    });
    const notificationButton = byId('notification-center-button');
    if (notificationButton) {
        notificationButton.addEventListener('click', event => {
            event.preventDefault();
            const menu = byId('notification-center-menu');
            setNotificationDropdown(Boolean(menu?.hidden));
        });
    }
    document.addEventListener('click', event => {
        const center = byId('notification-center');
        if (center && !center.contains(event.target)) setNotificationDropdown(false);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') setNotificationDropdown(false);
    });
    const path = window.location.pathname;
    if (path.startsWith('/network')) showView('network');
    else if (path.startsWith('/files')) showView('files');
    else if (path.startsWith('/custom-scan')) showView('custom');
    else if (path.startsWith('/applications')) showView('applications');
    else showView('home');
    loadApplications(false).then(() => {
        const match = decodeURIComponent(window.location.pathname.replace(/^\/applications\/?/, ''));
        if (match && match !== window.location.pathname) openAppDashboard(match);
        return loadNotificationBadge();
    }).catch(error => {
        byId('app-grid').innerHTML = '<div class="empty-state">Failed to load apps: ' + escapeHtml(error.message || error) + '</div>';
        loadNotificationBadge();
    });
    loadWireshark().catch(() => setText('network-area-status', 'Wireshark unknown'));
}

document.addEventListener('DOMContentLoaded', init);
