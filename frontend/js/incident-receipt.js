let _currentCard = null;
let _deepLinkNotificationId = '';
let _deepLinkNotificationAcked = false;

document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search || '');
    const sessionId = (params.get('session_id') || '').trim();
    const caseId = (params.get('case_id') || '').trim();
    const incidentId = (params.get('incident_id') || '').trim();
    const notificationId = (params.get('notification_id') || '').trim();
    _deepLinkNotificationId = notificationId;
    if (sessionId) {
        document.getElementById('session-id').value = sessionId;
    }
    if (incidentId) {
        document.getElementById('incident-id').value = incidentId;
    }
    if (caseId) {
        loadIncidentCard(caseId);
    } else if (sessionId) {
        loadIncidentCard();
    }
});

function setStatus(state, text) {
    const el = document.getElementById('status');
    el.className = `status ${state}`;
    el.textContent = text;
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function currentSessionId() {
    return String(document.getElementById('session-id').value || '').trim();
}

function currentRepoPath() {
    return String(document.getElementById('repo-path').value || '').trim();
}

function currentIncidentId() {
    return String(document.getElementById('incident-id').value || '').trim();
}

function statePill(status) {
    const normalized = String(status || 'unknown');
    if (normalized === 'blessed') return `<span class="pill good">${escapeHtml(normalized)}</span>`;
    if (normalized === 'purged' || normalized === 'quarantined' || normalized === 'purge_pending') return `<span class="pill warning">${escapeHtml(normalized)}</span>`;
    return `<span class="pill info">${escapeHtml(normalized)}</span>`;
}

function actionEnabled(card, action) {
    const status = String(card?.qpb_case?.status || '');
    if (action === 'quarantine') return status === 'detected' || status === 'quarantined';
    if (action === 'purge') return status === 'quarantined' || status === 'purge_pending';
    if (action === 'bless') return status === 'purged';
    return false;
}

function renderIncidentCard(card) {
    const container = document.getElementById('incident-card');
    if (!card) {
        container.innerHTML = '<div class="empty">No incident card loaded.</div>';
        return;
    }
    const suspicion = card.suspicion || {};
    const outcome = card.outcome || {};
    const incident = card.incident || {};
    const cardMeta = card?.qpb_case?.metadata || {};
    const refs = Array.isArray(card?.evidence?.refs) ? card.evidence.refs : [];
    const history = Array.isArray(card?.evidence?.history) ? card.evidence.history : [];
    const details = outcome.details || {};
    const removedPaths = Array.isArray(details.removed_paths) ? details.removed_paths : [];
    const processResults = Array.isArray(details.process_results) ? details.process_results : [];

    const refsHtml = refs.length
        ? `<ul class="list mono">${refs.slice(0, 20).map(ref => `<li>${escapeHtml(ref)}</li>`).join('')}</ul>`
        : '<div class="line">No evidence refs recorded.</div>';
    const historyHtml = history.length
        ? history.slice().reverse().map(entry => {
            const integrity = entry?.integrity?.root_hash || '';
            const meta = entry?.metadata || {};
            return (
                '<div class="history-row">' +
                `<div class="line"><strong>${escapeHtml(entry.action || 'unknown')}</strong> -> ${escapeHtml(entry.status || '')} at ${escapeHtml(entry.timestamp || '')}</div>` +
                `<div class="line">actor=${escapeHtml(entry.actor || '')} integrity_root_hash=<span class="mono">${escapeHtml(integrity)}</span></div>` +
                `<div class="line mono">${escapeHtml(JSON.stringify(meta || {}))}</div>` +
                '</div>'
            );
        }).join('')
        : '<div class="line">No decision history recorded.</div>';
    const removedHtml = removedPaths.length
        ? `<div class="line">removed_paths=${escapeHtml(removedPaths.join(', '))}</div>`
        : '';
    const processHtml = processResults.length
        ? `<div class="line mono">process_results=${escapeHtml(JSON.stringify(processResults))}</div>`
        : '';

    container.innerHTML =
        `<div class="line"><strong>${escapeHtml(suspicion.title || 'Incident')}</strong>${statePill(card?.qpb_case?.status)}</div>` +
        `<div class="line"><strong>What happened:</strong> process=${escapeHtml(suspicion.signal_process)} pid=${escapeHtml(suspicion.signal_pid)} touched ${escapeHtml(suspicion.target_path)}</div>` +
        `<div class="line"><strong>Why suspicious:</strong> ${escapeHtml(suspicion.reason || incident.summary || 'reason unavailable')}</div>` +
        `<div class="line"><strong>Requested action:</strong> ${escapeHtml(card?.decision_path?.next_action || 'review')}</div>` +
        `<div class="line"><strong>Expected effect:</strong> quarantine process scope, purge target file/process, bless trust reset</div>` +
        `<div class="line"><strong>Incident:</strong> ${escapeHtml(incident.id || 'unlinked')} · source_event=${escapeHtml(incident.source_event_id || '')}</div>` +
        `<div class="line"><strong>Evidence source:</strong> ${escapeHtml(cardMeta.synthetic ? 'synthetic' : 'runtime')}</div>` +
        `<div class="line"><strong>QPB case:</strong> ${escapeHtml(card?.qpb_case?.id || '')}</div>` +
        '<div class="actions">' +
            `<button class="quarantine" ${actionEnabled(card, 'quarantine') ? '' : 'disabled'} onclick="runDecision('quarantine')">Quarantine</button>` +
            `<button class="purge" ${actionEnabled(card, 'purge') ? '' : 'disabled'} onclick="runDecision('purge')">Purge</button>` +
            `<button class="bless" ${actionEnabled(card, 'bless') ? '' : 'disabled'} onclick="runDecision('bless')">Bless</button>` +
        '</div>' +
        '<div class="section-title">Outcome</div>' +
        `<div class="line">status=${escapeHtml(outcome.status || '')} action=${escapeHtml(outcome.action || '')} at ${escapeHtml(outcome.timestamp || '')}</div>` +
        `<div class="line">integrity_root_hash=<span class="mono">${escapeHtml(outcome.integrity_root_hash || '')}</span></div>` +
        removedHtml +
        processHtml +
        '<div class="section-title">Evidence</div>' +
        refsHtml +
        '<div class="section-title">Decision History</div>' +
        historyHtml;
}

async function ackDeepLinkNotificationIfNeeded() {
    if (!_deepLinkNotificationId || _deepLinkNotificationAcked || !window.CleanHouseAPI?.ackNotification) {
        return;
    }
    try {
        const result = await window.CleanHouseAPI.ackNotification(_deepLinkNotificationId);
        if (result && result.status === 'ok') {
            _deepLinkNotificationAcked = true;
        }
    } catch (e) {
        /* best effort only */
    }
}

async function loadIncidentCard(explicitCaseId = '') {
    const sessionId = currentSessionId();
    const caseId = String(explicitCaseId || '').trim();
    if (!sessionId && !caseId) {
        setStatus('degraded', 'Session ID or case_id is required to load.');
        return;
    }
    setStatus('clear', 'Loading incident card...');
    try {
        const result = await window.CleanHouseAPI.getStandaloneIncidentReceipt({
            sessionId: sessionId || null,
            caseId: caseId || null,
        });
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'load failed');
        }
        _currentCard = result.card || null;
        if (_currentCard?.session_id) {
            document.getElementById('session-id').value = _currentCard.session_id;
        }
        renderIncidentCard(_currentCard);
        await ackDeepLinkNotificationIfNeeded();
        setStatus('clear', 'Incident card loaded.');
    } catch (e) {
        _currentCard = null;
        renderIncidentCard(null);
        setStatus('degraded', `Load failed: ${e.message || 'unknown error'}`);
    }
}

async function createIncidentCard() {
    const sessionId = currentSessionId();
    const repoPath = currentRepoPath();
    const incidentId = currentIncidentId();
    if (!sessionId) {
        setStatus('degraded', 'Session ID is required to create a card.');
        return;
    }
    setStatus('clear', 'Binding runtime incident to standalone card...');
    try {
        const result = await window.CleanHouseAPI.createStandaloneIncidentReceipt({
            session_id: sessionId,
            incident_id: incidentId || undefined,
            repo_path: repoPath || undefined,
        });
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'create failed');
        }
        _currentCard = result.card || null;
        if (_currentCard?.incident?.id) {
            document.getElementById('incident-id').value = _currentCard.incident.id;
        }
        renderIncidentCard(_currentCard);
        setStatus('clear', result.reused ? 'Existing runtime incident card loaded.' : 'Runtime incident card bound.');
    } catch (e) {
        setStatus('degraded', `Create failed: ${e.message || 'unknown error'}`);
    }
}

async function runDecision(action) {
    const caseId = _currentCard?.qpb_case?.id || '';
    if (!caseId) {
        setStatus('degraded', 'No QPB case is loaded.');
        return;
    }
    const repoPath = currentRepoPath();
    const needsConfirm = action === 'purge';
    if (needsConfirm) {
        const ok = window.confirm('Confirm purge for this incident receipt?');
        if (!ok) return;
    }
    setStatus('clear', `Applying ${action}...`);
    try {
        const result = await window.CleanHouseAPI.transitionStandaloneIncidentReceipt(caseId, action, {
            actor: 'incident_receipt',
            confirm: needsConfirm,
            repo_path: repoPath || undefined,
        });
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || `${action} failed`);
        }
        _currentCard = result.card || null;
        renderIncidentCard(_currentCard);
        setStatus('clear', `${action} recorded.`);
    } catch (e) {
        setStatus('degraded', `${action} failed: ${e.message || 'unknown error'}`);
    }
}
