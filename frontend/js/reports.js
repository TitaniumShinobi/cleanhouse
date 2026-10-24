(function () {
    const REPORT_HISTORY_LIMIT = 10;

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
        })[char]);
    }

    function formatTime(value) {
        if (!value) return 'time unavailable';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleString();
    }

    function reportSummary(report) {
        const receipt = report.receipt || {};
        const summary = receipt.summary || {};
        return summary.text || report.context || report.message || 'Report summary unavailable.';
    }

    function renderConcernLetter(letter) {
        if (!letter || typeof letter !== 'object') return '';
        const facts = Array.isArray(letter.facts) ? letter.facts : [];
        const actions = Array.isArray(letter.requested_actions) ? letter.requested_actions : [];
        return `<section class="concern-letter" aria-label="Generated letter of concern">
            <div class="concern-head">
                <span class="section-kicker">Letter of concern</span>
                <strong>${escapeHtml(letter.subject || 'Letter of Concern')}</strong>
            </div>
            <p>${escapeHtml(letter.impact || '')}</p>
            <div class="concern-columns">
                <div>
                    <span class="concern-label">Facts</span>
                    <ul>${facts.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
                </div>
                <div>
                    <span class="concern-label">Requested action</span>
                    <ol>${actions.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ol>
                </div>
            </div>
        </section>`;
    }

    function renderReportDetail(report) {
        const refs = Array.isArray(report.evidence_links) ? report.evidence_links : [];
        const receipt = report.receipt || {};
        const summary = receipt.summary || {};
        const metadata = report.metadata || {};
        const summaryHtml = summary.text
            ? `<section class="report-summary-block">
                <span class="section-kicker">Summary</span>
                <p>${escapeHtml(summary.text)}</p>
                <div class="report-meta">
                    ${summary.risk_level ? `<span class="tag">${escapeHtml(summary.risk_level)} risk</span>` : ''}
                    ${summary.confidence ? `<span class="tag">${escapeHtml(summary.confidence)} confidence</span>` : ''}
                    ${summary.triggered_indicators !== undefined ? `<span class="tag">${escapeHtml(summary.triggered_indicators)} indicators</span>` : ''}
                </div>
            </section>`
            : '';
        const metadataHtml = metadata.evidence_boundary || metadata.triggered_indicators
            ? `<section class="report-summary-block">
                <span class="section-kicker">Boundary</span>
                <p>${escapeHtml(metadata.evidence_boundary || 'Report metadata unavailable.')}</p>
                ${Array.isArray(metadata.triggered_indicators) && metadata.triggered_indicators.length
                    ? `<div class="report-meta">${metadata.triggered_indicators.slice(0, 12).map(item => `<span class="tag">${escapeHtml(item)}</span>`).join('')}</div>`
                    : ''}
            </section>`
            : '';
        const refsHtml = refs.length
            ? `<div class="report-meta">${refs.slice(0, 10).map(ref => `<a class="tag" href="${escapeHtml(ref)}">${escapeHtml(ref)}</a>`).join('')}</div>`
            : '<div class="empty-state">No evidence refs in this report.</div>';
        return `<div class="report-detail">
            ${summaryHtml}
            ${metadataHtml}
            ${renderConcernLetter(report.concern_letter)}
            ${refsHtml}
        </div>`;
    }

    function reportDetailNode(reportId) {
        return Array.from(document.querySelectorAll('[data-report-detail]')).find(node => node.dataset.reportDetail === reportId) || null;
    }

    async function loadReportDetail(reportId) {
        const detail = reportDetailNode(reportId);
        if (!detail) return;
        detail.innerHTML = '<div class="empty-state">Loading report detail...</div>';
        try {
            const payload = await window.CleanHouseAPI.getReport(reportId);
            if (payload.status && payload.status !== 'ok') {
                throw new Error(payload.message || 'Report detail unavailable.');
            }
            detail.innerHTML = renderReportDetail(payload);
        } catch (error) {
            detail.innerHTML = `<div class="empty-state">${escapeHtml(error.message || 'Report detail unavailable.')}</div>`;
        }
    }

    function renderReports(reports) {
        const list = document.getElementById('reports-list');
        if (!list) return;
        if (!reports || reports.length === 0) {
            list.innerHTML = '<div class="empty-state">No reports match this filter.</div>';
            return;
        }
        list.innerHTML = reports.map(report => {
            const evidenceCount = Array.isArray(report.evidence_links) ? report.evidence_links.length : 0;
            return `<article class="report-row">
                <header>
                    <div>
                        <div class="report-title">${escapeHtml(report.report_type || 'report')}</div>
                        <p class="helper-copy">${escapeHtml(reportSummary(report))}</p>
                    </div>
                    <span class="tag blue">${escapeHtml(formatTime(report.timestamp))}</span>
                </header>
                <div class="report-meta">
                    <span class="tag">${evidenceCount} evidence refs</span>
                    <button class="secondary-action report-open-button" type="button" data-report-id="${escapeHtml(report.id || '')}">Open report</button>
                </div>
                <div data-report-detail="${escapeHtml(report.id || '')}"></div>
            </article>`;
        }).join('');
        list.querySelectorAll('.report-open-button').forEach(button => {
            button.addEventListener('click', () => loadReportDetail(button.dataset.reportId || ''));
        });
    }

    async function loadReports() {
        const filter = document.getElementById('report-filter')?.value || '';
        const params = new URLSearchParams(window.location.search);
        const openReportId = params.get('open') || '';
        const list = document.getElementById('reports-list');
        if (list) list.innerHTML = '<div class="empty-state">Loading reports...</div>';
        try {
            const payload = await window.CleanHouseAPI.getReports(null, {
                reportType: filter || undefined,
                limit: REPORT_HISTORY_LIMIT,
                summaryOnly: true,
            });
            renderReports(payload.reports || []);
            if (openReportId) {
                loadReportDetail(openReportId);
            }
        } catch (error) {
            if (list) list.innerHTML = `<div class="empty-state">${escapeHtml(error.message || 'Reports unavailable.')}</div>`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const params = new URLSearchParams(window.location.search);
        if (params.get('source') === 'zaelith') {
            const filter = document.getElementById('report-filter');
            if (filter) filter.value = 'zaelith_audit';
        }
        document.getElementById('refresh-reports-btn')?.addEventListener('click', loadReports);
        document.getElementById('report-filter')?.addEventListener('change', loadReports);
        loadReports();
    });
})();
