/**
 * CleanHouse API Client
 * Supports both pywebview (desktop) and HTTP fetch (browser) modes
 */

// Detect environment
const IS_PYWEBVIEW = typeof window !== 'undefined' &&
                     window.pywebview &&
                     window.pywebview.api;

function cleanHouseHttpOrigin() {
    if (
        typeof window !== 'undefined' &&
        window.location &&
        (window.location.protocol === 'http:' || window.location.protocol === 'https:')
    ) {
        return window.location.origin;
    }
    return 'http://127.0.0.1:3333';
}

const CLEANHOUSE_HTTP_ORIGIN = cleanHouseHttpOrigin();
const API_BASE_URL = IS_PYWEBVIEW ? null : `${CLEANHOUSE_HTTP_ORIGIN}/api`;

console.log('[API] Environment detected:', IS_PYWEBVIEW ? 'pywebview (desktop)' : 'browser (web)');

/**
 * API Client - routes calls to pywebview or HTTP fetch
 */
const CLEANHOUSE_BOOT_FETCH_TIMEOUT_MS = 1800;
const CLEANHOUSE_VIEW_FETCH_TIMEOUT_MS = 3500;
async function fetchJson(url, options = {}, timeoutMs = CLEANHOUSE_VIEW_FETCH_TIMEOUT_MS) {
    const decode = async response => {
        const payload = await response.json();
        if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
            payload.__http_status = response.status;
        }
        return payload;
    };
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || typeof AbortController === 'undefined') {
        const response = await fetch(url, options);
        return await decode(response);
    }
    if (options.signal) {
        const response = await fetch(url, options);
        return await decode(response);
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        return await decode(response);
    } finally {
        window.clearTimeout(timeout);
    }
}

const API = {
    async deleteAllowedThreat(allowedId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/allowed-threats/${encodeURIComponent(allowedId)}`, {
            method: 'DELETE'
        });
        return await response.json();
    },
    async getAllowedThreats() {
        return await fetchJson(
            `${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/allowed-threats`,
            {},
            CLEANHOUSE_BOOT_FETCH_TIMEOUT_MS
        );
    },
    async startAccountConnect(provider, connectionMethod, consentVersion = 'v1') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/accounts/connect/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider,
                connection_method: connectionMethod,
                consent_version: consentVersion,
            })
        });
        return await response.json();
    },
    async listConnectedAccounts() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/accounts`);
        return await response.json();
    },
    async analyzeZaelithText(text, prompt = '', source = 'zaelith-page') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/zaelith/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, prompt, source })
        });
        return await response.json();
    },
    async getReport(reportId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/reports/${encodeURIComponent(reportId)}`);
        return await response.json();
    },
    /**
     * Create account
     */
    async createAccount(fullName, email, password, role, turnstileToken = '') {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.createAccount(fullName, email, password, role, turnstileToken);
        } else {
            const response = await fetch(`${API_BASE_URL}/auth/createAccount`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fullName, email, password, role, turnstileToken })
            });
            return await response.json();
        }
    },

    /**
     * Login
     */
    async login(email, password) {
        if (IS_PYWEBVIEW) {
            // For desktop, we'd need to add a login method to the API wrapper
            // For now, return error
            return { success: false, message: 'Login via pywebview not yet implemented' };
        } else {
            const response = await fetch(`${API_BASE_URL}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            return await response.json();
        }
    },

    /**
     * Open OAuth URL
     */
    openOAuthUrl(url, provider) {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.openOAuthUrl(url, provider);
        } else {
            // For web, we need to implement OAuth differently
            // For now, open in same window
            const oauthUrl = `/api/auth/oauth/${provider}`;
            window.location.href = oauthUrl;
            return { success: true, message: `Opening ${provider} authentication...` };
        }
    },

    /**
     * Show login page
     */
    showLogin() {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.showLogin();
        } else {
            window.location.href = '/login';
            return { success: true };
        }
    },

    /**
     * Show signup page
     */
    showSignup() {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.showSignup();
        } else {
            window.location.href = '/signup';
            return { success: true };
        }
    },

    /**
     * Logging functions (optional, for debugging)
     */
    log(message, level = 'INFO') {
        if (IS_PYWEBVIEW && window.pywebview.api.log) {
            return window.pywebview.api.log(message, level);
        } else {
            console.log(`[${level}] ${message}`);
            return { success: true };
        }
    },

    logClick(elementType, details) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_click) {
            return window.pywebview.api.log_click(elementType, details);
        } else {
            console.log(`[CLICK] ${elementType}: ${details}`);
            return { success: true };
        }
    },

    logInput(fieldName, fieldType, charCount) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_input) {
            return window.pywebview.api.log_input(fieldName, fieldType, charCount);
        } else {
            console.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
            return { success: true };
        }
    },

    logFocus(fieldName) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_focus) {
            return window.pywebview.api.log_focus(fieldName);
        } else {
            console.log(`[FOCUS] Field "${fieldName}" focused`);
            return { success: true };
        }
    },

    logBlur(fieldName) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_blur) {
            return window.pywebview.api.log_blur(fieldName);
        } else {
            console.log(`[BLUR] Field "${fieldName}" blurred`);
            return { success: true };
        }
    },

    /**
     * Export session report with contact/target filing metadata
     */
    async exportReport(sessionId, reportType = 'incident', contact = '', target = '', context = '') {
        if (IS_PYWEBVIEW) {
            if (window.pywebview.api.exportReport) {
                return window.pywebview.api.exportReport(sessionId, reportType, contact, target, context);
            }
            return { status: 'unknown', message: 'pywebview exportReport not available' };
        } else {
            const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/report`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    report_type: reportType,
                    contact,
                    target,
                    context,
                })
            });
            return await response.json();
        }
    },

    /**
     * Retrieve stored reports, optionally filtered by session_id
     */
    async getReports(sessionId = null, options = {}) {
        if (IS_PYWEBVIEW) {
            if (window.pywebview.api.getReports) {
                return window.pywebview.api.getReports(sessionId);
            }
            return { reports: [], count: 0, message: 'pywebview getReports not available' };
        } else {
            const params = new URLSearchParams();
            if (sessionId) params.set('session_id', sessionId);
            if (options.reportType) params.set('report_type', options.reportType);
            if (options.limit) params.set('limit', String(options.limit));
            if (options.summaryOnly) params.set('summary_only', '1');
            const suffix = params.toString() ? `?${params.toString()}` : '';
            const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/reports${suffix}`);
            return await response.json();
        }
    },

    async buildLoginReport(userId = '', email = '', previousLoginAt = null, currentLoginAt = null, trigger = 'dashboard') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/login-report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                email,
                previous_login_at: previousLoginAt,
                current_login_at: currentLoginAt,
                trigger,
            })
        });
        return await response.json();
    },

    async pollLoginReport(jobId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/login-report/${encodeURIComponent(jobId)}`);
        return await response.json();
    },

    /**
     * Get all submitted intents
     */
    async getIntents() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/intents`);
        return await response.json();
    },

    /**
     * Build timeline for a session
     */
    async buildTimeline(sessionId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/timeline`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        });
        return await response.json();
    },

    /**
     * Get latest filesystem events
     */
    async getEvents(limit = 100) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/events?limit=${encodeURIComponent(limit)}`);
        return await response.json();
    },

    /**
     * Get the full collector status envelope for dashboard views.
     */
    async getStatus(refresh = false) {
        const suffix = refresh ? '?refresh=1' : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/status${suffix}`);
        return await response.json();
    },

    async getRuntime() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/runtime`);
        return await response.json();
    },

    async getTaskManager(refresh = false) {
        const suffix = refresh ? '?refresh=1' : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/task-manager${suffix}`);
        return await response.json();
    },

    async getPortMonitor(refresh = false) {
        const suffix = refresh ? '?refresh=1' : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/port-monitor${suffix}`);
        return await response.json();
    },

    async getDomainObserverCatalog() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/domains`);
        return await response.json();
    },

    async getDomainEvents({ domain = null, surface = null, severity = null, status = null, limit = null } = {}) {
        const params = new URLSearchParams();
        if (domain) params.set('domain', domain);
        if (surface) params.set('surface', surface);
        if (severity) params.set('severity', severity);
        if (status) params.set('status', status);
        if (limit) params.set('limit', String(limit));
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/domain-events${suffix}`);
        return await response.json();
    },

    async emitDomainEvent(payload) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/domain-events`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        return await response.json();
    },

    async getIncidents({ sessionId = null, status = null, severity = null, limit = null } = {}) {
        const params = new URLSearchParams();
        if (sessionId) params.set('session_id', sessionId);
        if (status) params.set('status', status);
        if (severity) params.set('severity', severity);
        if (limit) params.set('limit', String(limit));
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/incidents${suffix}`);
        return await response.json();
    },

    async updateIncident(incidentId, action, { note = '', actor = 'operator' } = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/incidents/${encodeURIComponent(incidentId)}/${encodeURIComponent(action)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note, actor }),
        });
        return await response.json();
    },

    async getNotificationDelivery(limit = 200) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notification-delivery?limit=${encodeURIComponent(limit)}`);
        return await response.json();
    },

    async getNotificationPolicy(limit = 200) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notification-policy?limit=${encodeURIComponent(limit)}`);
        return await response.json();
    },

    async getActionOutcomes(limit = 200) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/action-outcomes?limit=${encodeURIComponent(limit)}`);
        return await response.json();
    },

    async getCollectorManifest(refresh = false) {
        const status = await this.getStatus(refresh);
        const data = status?.data || {};
        const sections = data.sections || {};
        const manifest = data.collector_manifest || {};
        const surfaces = manifest.surfaces || {};
        const enabled = status?.settings || {};
        const surfaceNames = new Set(Object.keys(surfaces));
        for (const name of Object.keys(enabled)) {
            surfaceNames.add(collectorSectionAlias(name));
        }
        const collectors = Array.from(surfaceNames).sort().map(surfaceName => {
            const configuredName = collectorNameForSurface(surfaceName);
            const section = sections[surfaceName] || {};
            const surface = surfaces[surfaceName] || {};
            const eventCounts = section.event_counts || {};
            const hasEnabledSetting = Object.prototype.hasOwnProperty.call(enabled, configuredName);
            const enabledState = hasEnabledSetting ? Boolean(enabled[configuredName]) : null;
            const collectorStatus = surface.collector_status || (enabledState === false ? 'disabled' : 'unknown');
            return {
                name: surfaceName,
                configured_name: configuredName,
                enabled: enabledState,
                status: surface.status || section.status || (enabledState === false ? 'disabled' : 'unknown'),
                collector_status: collectorStatus,
                observations: eventCounts.observations || 0,
                collector_failures: surface.collector_failures ?? eventCounts.collector_failures ?? 0,
                returned_issue_count: section.returned_issue_count ?? 0,
                issue_count: surface.issue_count ?? section.issue_count ?? 0,
                dependency_available: surface.dependency_available,
                watch_dir: surface.watch_dir,
                failure: section.collector_failure || null,
            };
        });
        return {
            status: status?.status || 'unknown',
            generated_at: manifest.generated_at || status?.generated_at || new Date().toISOString(),
            collectors,
            runtime: manifest.runtime || {},
            plugins: status?.plugins || { count: 0, enabled_count: 0, entries: [] },
            source: refresh ? '/cleanhouse/status?refresh=1' : '/cleanhouse/status',
        };
    },

    /**
     * Get alerts for a session
     */
    async getAlerts(sessionId) {
        const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/alerts${params}`);
        return await response.json();
    },

    /**
     * Get receipts, optionally filtered by session_id
     */
    async getReceipts(sessionId = null) {
        const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/receipts${params}`);
        return await response.json();
    },

    async getReceiptReplay(receiptId) {
        const params = `?receipt_id=${encodeURIComponent(receiptId)}`;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/receipt-replay${params}`);
        return await response.json();
    },

    async getReceiptBundle(receiptId) {
        const params = `?receipt_id=${encodeURIComponent(receiptId)}`;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/receipt-bundle${params}`);
        return await response.json();
    },

    async importReceiptBundle(bundle) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/receipt-bundle/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle })
        });
        return await response.json();
    },

    /**
     * Get current runtime settings
     */
    async getSettings() {
        if (IS_PYWEBVIEW) {
            if (window.pywebview.api.getSettings) {
                return window.pywebview.api.getSettings();
            }
            return { status: 'unknown', settings: {}, message: 'pywebview getSettings not available' };
        } else {
            const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/settings`);
            return await response.json();
        }
    },

    /**
     * Update runtime settings (partial merge per group)
     */
    async updateSettings(data) {
        if (IS_PYWEBVIEW) {
            if (window.pywebview.api.updateSettings) {
                return window.pywebview.api.updateSettings(data);
            }
            return { status: 'unknown', message: 'pywebview updateSettings not available' };
        } else {
            const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            return await response.json();
        }
    },

    /**
     * Submit declared user intent text and scope
     */
    async submitIntent(text, scope = '', repoPath = '', toolIdentity = 'CleanHouse') {
        if (IS_PYWEBVIEW) {
            if (window.pywebview.api.submitIntent) {
                return window.pywebview.api.submitIntent(text, scope, repoPath, toolIdentity);
            }
            return { status: 'unknown', id: null, message: 'pywebview submitIntent not available' };
        } else {
            const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/intent`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text,
                    scope,
                    repo_path: repoPath,
                    tool_identity: toolIdentity
                })
            });
            return await response.json();
        }
    },

    async submitPrompt(text, context = '', scope = '', repoPath = '', toolIdentity = 'CleanHouse', sessionId = null, objectiveId = null, options = {}) {
        const payload = {
            text,
            context,
            scope,
            repo_path: repoPath,
            tool_identity: toolIdentity
        };
        if (sessionId) payload.session_id = sessionId;
        if (objectiveId) payload.objective_id = objectiveId;
        const promptType = options.prompt_type || options.promptType;
        const parentInterventionId = options.parent_intervention_id || options.parentInterventionId;
        if (promptType) payload.prompt_type = promptType;
        if (parentInterventionId) payload.parent_intervention_id = parentInterventionId;
        if (Array.isArray(options.evidence_refs)) payload.evidence_refs = options.evidence_refs;
        if (Array.isArray(options.evidenceRefs)) payload.evidence_refs = options.evidenceRefs;
        if (options.metadata && typeof options.metadata === 'object') payload.metadata = options.metadata;
        if (options.source) payload.source = options.source;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/prompt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async startObjective(sessionId, objectiveText = '', objectiveId = null) {
        const payload = {
            session_id: sessionId,
            objective: objectiveText || '',
        };
        if (objectiveId) payload.objective_id = objectiveId;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/objective/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async getPrompts(sessionId = null) {
        const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/prompts${params}`);
        return await response.json();
    },

    async startOperatorSession(sessionId, objectiveId = null, summary = '', metadata = {}) {
        const payload = {
            session_id: sessionId,
            summary,
            metadata
        };
        if (objectiveId) payload.objective_id = objectiveId;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/session/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async stopOperatorSession(sessionId, finalize = false, summary = '', metadata = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/session/stop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                finalize,
                summary,
                metadata
            })
        });
        return await response.json();
    },

    async getWorkstation(sessionId = null, options = {}) {
        const query = new URLSearchParams();
        if (sessionId) query.set('session_id', sessionId);
        if (options.scopeEvidence) query.set('scope_evidence', '1');
        const params = query.toString() ? `?${query.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/workstation${params}`);
        return await response.json();
    },

    async runApplicationInvestigation(payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/investigations/application`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async getProcesses(refresh = false) {
        const query = new URLSearchParams();
        if (refresh) query.set('refresh', '1');
        const params = query.toString() ? `?${query.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/processes${params}`);
        return await response.json();
    },

    async getApplications(refresh = false) {
        const query = new URLSearchParams();
        if (refresh) query.set('refresh', '1');
        const params = query.toString() ? `?${query.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/applications${params}`);
        return await response.json();
    },

    async runSystemScan() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/scan/system`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        return await response.json();
    },

    async getWiresharkStatus() {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/network/wireshark`);
        return await response.json();
    },

    async getNetwork(refresh = false) {
        const query = new URLSearchParams();
        if (refresh) query.set('refresh', '1');
        const params = query.toString() ? `?${query.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/network${params}`);
        return await response.json();
    },

    async getActiveContext(refresh = false, attach = false) {
        const query = new URLSearchParams();
        if (refresh) query.set('refresh', '1');
        if (attach) query.set('attach', '1');
        const params = query.toString() ? `?${query.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/active-context${params}`);
        return await response.json();
    },

    async setActiveContextFollow(enabled) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/active-context/follow`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: Boolean(enabled) })
        });
        return await response.json();
    },

    async pickupActiveContext(payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/active-context/pickup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async ignoreActiveContext(dedupeKey = '') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/active-context/ignore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dedupe_key: dedupeKey || '' })
        });
        return await response.json();
    },

    async getContinuity(sessionId = null) {
        const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/continuity${params}`);
        return await response.json();
    },

    async pinContinuityContext(sessionId, text, sourceRef = '', evidenceRefs = [], objectiveId = null, metadata = {}, operator = 'dashboard') {
        const payload = {
            session_id: sessionId,
            text,
            source_ref: sourceRef,
            evidence_refs: evidenceRefs,
            metadata,
            operator
        };
        if (objectiveId) payload.objective_id = objectiveId;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/continuity/pins`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async recordContinuityDecision(sessionId, claimId, decision, note = '', evidenceRefs = [], metadata = {}, operator = 'dashboard') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/continuity/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                claim_id: claimId,
                decision,
                note,
                evidence_refs: evidenceRefs,
                metadata,
                operator
            })
        });
        return await response.json();
    },

    async searchContinuity(sessionId, query = '', options = {}) {
        const payload = {
            session_id: sessionId,
            query,
            operator: options.operator || 'dashboard'
        };
        for (const key of ['max_results', 'max_files', 'max_bytes']) {
            if (options[key] !== undefined) payload[key] = options[key];
        }
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/continuity/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async getLineageGraph(sessionId = null) {
        const [workstation, approvalData] = await Promise.all([
            this.getWorkstation(sessionId),
            this.getApprovalQueue(sessionId),
        ]);
        return buildLineageGraph(workstation, approvalData?.approval_queue || []);
    },

    async getRollbacks(sessionId = null) {
        const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/rollback${params}`);
        return await response.json();
    },

    async getRollbackReplayState(sessionId = null) {
        const [receiptData, approvalData] = await Promise.all([
            this.getReceipts(sessionId),
            this.getApprovalQueue(sessionId),
        ]);
        let rollbackData = { status: 'unavailable', rollbacks: [], count: 0, message: 'rollback endpoint not queried' };
        try {
            rollbackData = await this.getRollbacks(sessionId);
        } catch (e) {
            rollbackData = {
                status: 'unavailable',
                rollbacks: [],
                count: 0,
                message: e.message || 'rollback endpoint unavailable',
            };
        }
        const receipts = receiptData?.receipts || [];
        const approvals = approvalData?.approval_queue || [];
        const rollbacks = rollbackData?.rollbacks || [];
        const replays = {};
        const manifests = {};
        await Promise.all(receipts.map(async receipt => {
            if (!receipt?.id) return;
            try {
                const replay = await this.getReceiptReplay(receipt.id);
                replays[receipt.id] = replay || { status: 'unknown', message: 'replay response unavailable' };
            } catch (e) {
                replays[receipt.id] = { status: 'error', message: e.message || 'replay unavailable' };
            }
            try {
                const bundle = await this.getReceiptBundle(receipt.id);
                if (bundle?.status === 'ok') {
                    manifests[receipt.id] = {
                        status: 'ok',
                        manifest: bundle.bundle?.manifest || {},
                        integrity: bundle.bundle?.integrity || {},
                        signature: bundle.bundle?.manifest_signature || {},
                        verification: bundle.verification || {},
                    };
                } else {
                    manifests[receipt.id] = {
                        status: bundle?.status || 'unknown',
                        message: bundle?.message || 'bundle unavailable',
                        verification: bundle?.verification || {},
                    };
                }
            } catch (e) {
                manifests[receipt.id] = { status: 'unavailable', message: e.message || 'manifest unavailable' };
            }
        }));
        return {
            status: 'ok',
            session_id: sessionId || '',
            receipts,
            approvals,
            rollbacks,
            replays,
            manifests,
            replay_count: Object.values(replays).filter(replay => replay?.status === 'ok').length,
            manifest_count: Object.values(manifests).filter(manifest => manifest?.status === 'ok').length,
            rollback_status: rollbackData?.status || 'unknown',
            rollback_count: rollbacks.length,
            rollback_message: rollbackData?.message || '',
        };
    },

    async getOperatorVerification(sessionId = null) {
        const [collectorManifest, lineageGraph, rollbackReplayState, workstation] = await Promise.all([
            this.getCollectorManifest(false),
            this.getLineageGraph(sessionId),
            this.getRollbackReplayState(sessionId),
            this.getWorkstation(sessionId),
        ]);
        const checks = {
            collector_health_visible: collectorManifest.collectors.length > 0,
            session_evidence_links_visible: lineageGraph.nodes.length > 0,
            receipt_replay_available_or_no_receipts: rollbackReplayState.receipts.length === 0 || rollbackReplayState.replay_count > 0,
            rollback_endpoint_available: rollbackReplayState.rollback_status === 'ok',
            source_local_http_api_snapshot: true,
            workstation_api_available: workstation?.status === 'ok',
        };
        const passed = Object.entries(checks).every(([name, value]) =>
            value === true
        );
        return {
            status: passed ? 'ok' : 'failed',
            session_id: sessionId || workstation?.session?.session_id || '',
            generated_at: new Date().toISOString(),
            method: 'http-api',
            checks,
        };
    },

    async ackNotification(notificationId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notifications/${encodeURIComponent(notificationId)}/ack`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        return await response.json();
    },

    async unackNotification(notificationId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notifications/${encodeURIComponent(notificationId)}/unack`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        return await response.json();
    },

    async snoozeNotification(notificationId, minutes = 10) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notifications/${encodeURIComponent(notificationId)}/snooze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ minutes }),
        });
        return await response.json();
    },

    async getNotificationTimeline(notificationId) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notifications/${encodeURIComponent(notificationId)}/timeline`);
        return await response.json();
    },

    async sendNotificationProbe(payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/notifications/probe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        return await response.json();
    },

    async createApprovalQueueItem(sessionId, requestedAction, reason = '', evidenceRefs = [], promptId = null, objectiveId = null, metadata = {}, reviewerNote = '', reviewer = 'dashboard') {
        const payload = {
            session_id: sessionId,
            requested_action: requestedAction,
            reason,
            evidence_refs: evidenceRefs,
            metadata,
            reviewer_note: reviewerNote,
            reviewer
        };
        if (promptId) payload.prompt_id = promptId;
        if (objectiveId) payload.objective_id = objectiveId;
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/approval-queue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    },

    async getApprovalQueue(sessionId = null, status = null) {
        const params = new URLSearchParams();
        if (sessionId) params.set('session_id', sessionId);
        if (status) params.set('status', status);
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/approval-queue${suffix}`);
        return await response.json();
    },

    async resolveApprovalQueueItem(approvalId, status, note = '', reviewer = 'dashboard') {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/approval-queue/${encodeURIComponent(approvalId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, note, reviewer })
        });
        return await response.json();
    },

    async getQpbCases(sessionId = null, status = null) {
        const params = new URLSearchParams();
        if (sessionId) params.set('session_id', sessionId);
        if (status) params.set('status', status);
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/qpb/cases${suffix}`);
        return await response.json();
    },

    async createQpbCase(payload) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/qpb/cases`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async transitionQpbCase(caseId, action, payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/qpb/cases/${encodeURIComponent(caseId)}/${encodeURIComponent(action)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async getStandaloneIncidentReceipt({ sessionId = null, caseId = null } = {}) {
        const params = new URLSearchParams();
        if (sessionId) params.set('session_id', sessionId);
        if (caseId) params.set('case_id', caseId);
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/incident-receipt${suffix}`);
        return await response.json();
    },

    async createStandaloneIncidentReceipt(payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/incident-receipt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        return await response.json();
    },

    async transitionStandaloneIncidentReceipt(caseId, action, payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/incident-receipt/${encodeURIComponent(caseId)}/${encodeURIComponent(action)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        return await response.json();
    },

    async getMediatorProposals(sessionId = null, proposalType = null, status = null) {
        const params = new URLSearchParams();
        if (sessionId) params.set('session_id', sessionId);
        if (proposalType) params.set('proposal_type', proposalType);
        if (status) params.set('status', status);
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/mediator/proposals${suffix}`);
        return await response.json();
    },

    async createMediatorProposal(payload) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/mediator/proposals`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async resolveMediatorProposal(proposalId, decision, payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/mediator/proposals/${encodeURIComponent(proposalId)}/${encodeURIComponent(decision)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async undoMediatorProposal(proposalId, payload = {}) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/mediator/proposals/${encodeURIComponent(proposalId)}/undo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async createAutoSortProposal(payload) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/auto-sort/proposal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    },

    async createCleanerProposal(payload) {
        const response = await fetch(`${CLEANHOUSE_HTTP_ORIGIN}/cleanhouse/cleaner/proposal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
        return await response.json();
    }
};

// Export for use in other scripts
if (typeof window !== 'undefined') {
    window.CleanHouseAPI = API;
}

function collectorSectionAlias(name) {
    const aliases = {
        process_monitor: 'processes',
        data_flow_tracer: 'network',
        ai_activity: 'ai_activity',
        anomaly_detector: 'anomalies',
        integrity: 'integrity',
        command: 'command',
        cloud_usage: 'cloud_usage',
        tool_events: 'tool_events',
    };
    return aliases[name] || name;
}

function collectorNameForSurface(surfaceName) {
    const aliases = {
        processes: 'process_monitor',
        network: 'data_flow_tracer',
        ai_activity: 'ai_activity',
        anomalies: 'anomaly_detector',
        integrity: 'integrity',
        command: 'command',
        cloud_usage: 'cloud_usage',
        tool_events: 'tool_events',
    };
    return aliases[surfaceName] || surfaceName;
}

function buildLineageGraph(workstation, approvals = []) {
    const nodes = [];
    const edges = [];
    const seen = new Set();
    const addNode = (id, type, label, meta = {}) => {
        if (!id || seen.has(id)) return;
        seen.add(id);
        nodes.push({ id, type, label: label || id, meta });
    };
    const addEdge = (from, to, relation) => {
        if (!from || !to) return;
        edges.push({ from, to, relation });
    };

    const session = workstation?.session || {};
    const sessionId = session.session_id || workstation?.session_id || '';
    addNode(sessionId, 'session', sessionId || 'session', { status: session.status || 'unknown' });

    for (const objective of workstation?.objectives || []) {
        const id = objective.id || objective.objective_id || objective.prompt_id;
        addNode(id, 'objective', objective.text || id, objective);
        addEdge(sessionId, id, 'declares');
    }
    for (const mutation of workstation?.mutations || []) {
        const id = mutation.event_id || mutation.id || mutation.path || mutation.summary;
        addNode(id, 'mutation', mutation.summary || mutation.path || id, mutation);
        addEdge(sessionId, id, 'observes');
    }
    for (const alert of workstation?.deviation_signals?.alerts || []) {
        const id = alert.id || alert.alert_id || alert.alert_type + ':' + (alert.description || '');
        addNode(id, 'alert', alert.alert_type || id, alert);
        addEdge(sessionId, id, 'flags');
        for (const sourceId of alert.source_ids || []) addEdge(sourceId, id, 'supports');
    }
    for (const receipt of workstation?.receipts || []) {
        addNode(receipt.id, 'receipt', receipt.id, receipt);
        addEdge(sessionId, receipt.id, 'finalizes');
    }
    for (const approval of approvals || workstation?.approvals || []) {
        addNode(approval.id, 'approval', approval.status || approval.id, approval);
        addEdge(sessionId, approval.id, 'requires_review');
        const receiptId = approval?.metadata?.receipt_id;
        if (receiptId) addEdge(receiptId, approval.id, 'reviewed_by');
    }
    for (const [receiptId, replay] of Object.entries(workstation?.receipt_replays || {})) {
        addNode(replay.id || receiptId + ':replay', 'replay', replay.id || 'replay', replay);
        addEdge(receiptId, replay.id || receiptId + ':replay', 'replays');
    }

    return {
        status: 'ok',
        session_id: sessionId,
        nodes,
        edges,
        node_count: nodes.length,
        edge_count: edges.length,
    };
}
