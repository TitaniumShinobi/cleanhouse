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

function valueOrUnavailable(value) {
    return value === undefined || value === null || value === '' ? 'Unavailable' : String(value);
}

function allowedThreatRow(item) {
    const id = valueOrUnavailable(item.id);
    const target = item.target_name || item.target_path || item.target_type || 'Unavailable';
    return (
        '<article class="allowed-threat-row">' +
        '  <div class="allowed-threat-main">' +
        '    <h2>' + escapeHtml(valueOrUnavailable(item.threat_name)) + '</h2>' +
        '    <p>' + escapeHtml(valueOrUnavailable(target)) + '</p>' +
        '  </div>' +
        '  <dl class="allowed-threat-meta">' +
        '    <div><dt>Severity</dt><dd>' + escapeHtml(valueOrUnavailable(item.severity)) + '</dd></div>' +
        '    <div><dt>Allowed</dt><dd>' + escapeHtml(valueOrUnavailable(item.created_at)) + '</dd></div>' +
        '    <div><dt>Reason</dt><dd>' + escapeHtml(valueOrUnavailable(item.reason)) + '</dd></div>' +
        '  </dl>' +
        '  <button class="secondary-action allowed-threat-remove" type="button" data-allowed-id="' + escapeHtml(id) + '">Remove</button>' +
        '</article>'
    );
}

function renderAllowedThreats(items) {
    const list = byId('allowed-threats-list');
    if (!list) return;
    if (!Array.isArray(items) || items.length === 0) {
        list.innerHTML = '<div class="empty-state">No allowed threats are recorded on this device.</div>';
        return;
    }
    list.innerHTML = items.map(allowedThreatRow).join('');
    list.querySelectorAll('.allowed-threat-remove').forEach(button => {
        button.addEventListener('click', async () => {
            button.disabled = true;
            const result = await window.CleanHouseAPI.deleteAllowedThreat(button.dataset.allowedId);
            renderAllowedThreats(Array.isArray(result.allowed_threats) ? result.allowed_threats : []);
        });
    });
}

async function loadAllowedThreats() {
    const list = byId('allowed-threats-list');
    if (list) list.innerHTML = '<div class="empty-state">Loading allowed threats...</div>';
    try {
        const result = await window.CleanHouseAPI.getAllowedThreats();
        renderAllowedThreats(Array.isArray(result.allowed_threats) ? result.allowed_threats : []);
    } catch (error) {
        if (list) list.innerHTML = '<div class="empty-state">Allowed threats are unavailable.</div>';
    }
}

document.addEventListener('DOMContentLoaded', loadAllowedThreats);
