/* CleanHouse unified local Settings modal.
 *
 * Authentication and antivirus state remain server-authoritative. This module
 * renders only returned state and never persists credentials or tokens in
 * browser storage.
 */
(function () {
    'use strict';

    const TABS = [
        ['general', 'General'],
        ['providers', 'Providers'],
        ['api', 'API'],
        ['notifications', 'Notifications'],
        ['personalization', 'Personalization'],
        ['schedules', 'Schedules'],
        ['billing', 'Billing'],
        ['data', 'Data'],
        ['security', 'Security'],
        ['account', 'Account'],
        ['advanced', 'Advanced'],
    ];
    const UNAVAILABLE = new Set(['notifications', 'personalization', 'schedules', 'billing', 'data']);
    let activeTab = 'general';
    let returnFocus = null;
    let csrfToken = '';
    let reauthToken = '';
    let runtimeSettings = null;
    let returnUrl = '';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function modal() { return document.getElementById('settings-modal'); }
    function body() { return document.getElementById('settings-body'); }
    function footer() { return document.getElementById('settings-footer'); }
    function policyModal() { return document.getElementById('policy-consent-modal'); }

    async function readJson(response) {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(payload.message || payload.error || 'Request failed');
            error.code = payload.code || payload.error_code || '';
            error.status = response.status;
            throw error;
        }
        return payload;
    }

    async function request(path, options) {
        const requestOptions = Object.assign({}, options || {});
        const sensitive = Boolean(requestOptions.sensitive);
        delete requestOptions.sensitive;
        const init = Object.assign({ credentials: 'include', headers: { Accept: 'application/json' } }, requestOptions);
        init.headers = Object.assign({ Accept: 'application/json' }, init.headers || {});
        if (init.body && typeof init.body !== 'string') {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(init.body);
        }
        if (init.method && init.method !== 'GET' && init.method !== 'HEAD') {
            if (!csrfToken) await loadCsrf();
            if (csrfToken) init.headers['X-CSRF-Token'] = csrfToken;
        }
        if (sensitive && reauthToken) init.headers['X-CleanHouse-Reauth'] = reauthToken;
        return readJson(await fetch(path, init));
    }

    async function sensitiveRequest(path, options) {
        try {
            return await request(path, Object.assign({}, options || {}, { sensitive: true }));
        } finally {
            reauthToken = '';
        }
    }

    async function mfaStepUp(operation, target) {
        const challenge = await request('/api/auth/mfa/challenge', { method: 'POST', body: { operation, target: target || '' } });
        const factors = await request('/api/auth/mfa/factors');
        const factor = (factors.factors || [])[0];
        const entered = window.prompt('Enter your six-digit authenticator code, or prefix a recovery code with recovery:');
        if (!entered) throw new Error('MFA verification was cancelled.');
        const body = { challengeId: challenge.challengeId };
        if (entered.startsWith('recovery:')) body.recoveryCode = entered.slice(9).trim();
        else { body.factorId = factor && factor.factor_id; body.code = entered.trim(); }
        const verified = await request('/api/auth/mfa/verify', { method: 'POST', body });
        if (!verified.proof) throw new Error('MFA verification did not return an operation proof.');
        return verified.proof;
    }

    async function sensitiveMfaRequest(path, options, operation, target) {
        try {
            return await sensitiveRequest(path, options);
        } catch (error) {
            if (error.code !== 'MFA_STEP_UP_REQUIRED') throw error;
            const proof = await mfaStepUp(operation, target || '');
            const retry = Object.assign({}, options || {});
            retry.headers = Object.assign({}, retry.headers || {}, {
                'X-CleanHouse-MFA': proof,
                'X-CleanHouse-MFA-Target': target || '',
            });
            return request(path, retry);
        }
    }

    async function loadCsrf() {
        const response = await fetch('/api/auth/csrf', { credentials: 'include', headers: { Accept: 'application/json' } });
        const payload = await readJson(response);
        csrfToken = payload.csrfToken || payload.csrf_token || payload.token || '';
    }

    function renderTabs() {
        const tabs = document.getElementById('settings-tabs');
        tabs.innerHTML = TABS.map(([id, label]) =>
            '<button type="button" role="tab" id="settings-tab-' + id + '" data-settings-tab="' + id + '"' +
            ' aria-controls="settings-body" aria-selected="' + (id === activeTab ? 'true' : 'false') + '"' +
            ' tabindex="' + (id === activeTab ? '0' : '-1') + '">' + esc(label) +
            (UNAVAILABLE.has(id) ? '<span class="settings-tab-state">Unavailable</span>' : '') + '</button>'
        ).join('');
    }

    function setFooter(html) {
        footer().innerHTML = html || '<button type="button" class="btn-secondary" data-settings-action="close">Close</button>';
    }

    function setLoading(message) {
        body().setAttribute('aria-busy', 'true');
        body().innerHTML = '<div class="settings-state"><span class="settings-spinner" aria-hidden="true"></span><p>' + esc(message || 'Loading settings…') + '</p></div>';
        setFooter();
    }

    function setError(message) {
        body().setAttribute('aria-busy', 'false');
        body().innerHTML = '<div class="settings-state settings-error" role="alert"><h2>Settings unavailable</h2><p>' + esc(message) + '</p><button type="button" class="btn-secondary" data-settings-action="retry">Retry</button></div>';
        setFooter();
    }

    function unavailablePanel(label) {
        body().innerHTML = '<section class="settings-section settings-unavailable"><span class="settings-eyebrow">Not available in this release</span><h2>' + esc(label) + '</h2><p>This section is reserved in the unified Settings system. CleanHouse does not claim that these controls are operational yet.</p></section>';
        setFooter();
    }

    function reauthControl(payload) {
        const capabilities = payload && payload.reauthentication ? payload.reauthentication : null;
        if (!capabilities) {
            return '<section class="settings-reauth" aria-labelledby="settings-reauth-title"><h3 id="settings-reauth-title">Recent reauthentication</h3><p role="status">Confirmation methods are currently unavailable. Retry this Settings section before making a sensitive change.</p></section>';
        }
        const password = capabilities.password || {};
        const email = capabilities.verified_email || {};
        const connectedProviders = Array.isArray(capabilities.providers)
            ? capabilities.providers.filter(provider => provider && provider.connected)
            : [];
        const providerNote = connectedProviders.length
            ? '<p class="settings-reauth-note">Signed in with ' + connectedProviders.map(provider => esc(provider.id === 'google' ? 'Google' : (provider.label || provider.id))).join(' and ') + '. Use an available verified confirmation method below.</p>'
            : '';
        const passwordControl = password.available
            ? '<label for="settings-reauth-password">Current password</label><div><input id="settings-reauth-password" name="password" type="password" autocomplete="current-password"><button type="submit" class="btn-secondary">' + esc(password.label || 'Confirm password') + '</button></div>'
            : '';
        const emailControl = email.available
            ? '<button type="button" class="btn-secondary" data-settings-action="reauth-email">' + esc(email.label || 'Confirm by verified email') + '</button>'
            : '';
        const unavailable = !password.available && !email.available
            ? '<p class="settings-result error" role="status">No fresh confirmation method is currently available. Verified-email delivery is not configured.</p>'
            : '';
        return '<form id="settings-reauth-form" class="settings-reauth"><h3 id="settings-reauth-title">Recent reauthentication</h3><p>Sensitive changes require a fresh human confirmation for this section.</p>' + providerNote + passwordControl + emailControl + unavailable + '</form>';
    }

    async function loadReauthCapabilities() {
        return request('/api/auth/reauth');
    }

    async function renderGeneral() {
        body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">This Mac</span><h2>General</h2><p>CleanHouse runs as device-local macOS antivirus software. Its browser dashboard is the local control interface.</p><dl class="settings-facts"><div><dt>Control surface</dt><dd>Local dashboard</dd></div><div><dt>Session authority</dt><dd>Revocable device session</dd></div><div><dt>Processing</dt><dd>Local-first and bounded</dd></div></dl></section>';
        setFooter();
    }

    function providerRows(payload) {
        const source = payload.providers || payload;
        const providers = Array.isArray(source) ? source : Object.entries(source || {}).map(([id, value]) => Object.assign({ id }, value || {}));
        const byId = new Map(providers.map(item => [String(item.id || item.provider || '').toLowerCase(), item]));
        return ['google', 'github'].map(id => Object.assign({ id, name: id === 'github' ? 'GitHub' : 'Google', available: false, connected: false }, byId.get(id) || {}));
    }

    async function renderProviders() {
        setLoading('Loading provider status…');
        try {
            const [payload, reauth] = await Promise.all([request('/api/auth/providers'), loadReauthCapabilities()]);
            const rows = providerRows(payload);
            body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">Identity connections</span><h2>Providers</h2><p>Provider credentials stay in macOS Keychain. Unavailable providers remain visibly unavailable.</p><div class="settings-list">' + rows.map(provider => {
                const id = String(provider.id).toLowerCase();
                const connected = Boolean(provider.connected || provider.linked);
                const available = Boolean(provider.available || provider.configured);
                const detail = connected ? 'Connected to this CleanHouse identity.' : (available ? 'Available to connect.' : 'Unavailable until owner configuration is complete.');
                const action = connected
                    ? '<button type="button" class="btn-secondary" data-settings-action="provider-avatar-refresh" data-provider="' + esc(id) + '"' + (available ? '' : ' disabled') + '>Refresh photo</button><button type="button" class="btn-secondary" data-settings-action="provider-unlink" data-provider="' + esc(id) + '">Unlink</button>'
                    : '<button type="button" class="btn-primary" data-settings-action="provider-link" data-provider="' + esc(id) + '"' + (available ? '' : ' disabled') + '>Connect</button>';
                return '<article class="settings-row"><div><h3>' + esc(provider.name || id) + '</h3><p>' + esc(detail) + '</p></div><div class="settings-row-action"><span class="settings-badge ' + (connected ? 'ok' : (available ? 'ready' : 'unavailable')) + '">' + (connected ? 'Connected' : (available ? 'Available' : 'Unavailable')) + '</span>' + action + '</div></article>';
            }).join('') + '</div>' + reauthControl(reauth) + '<div id="settings-action-result" aria-live="polite"></div></section>';
            setFooter();
            await showProviderPhotoReturn();
        } catch (error) { setError(error.message); }
    }

    async function showProviderPhotoReturn() {
        const url = new URL(window.location.href);
        const provider = url.searchParams.get('photo_refreshed');
        const failure = url.searchParams.get('error');
        const errors = {
            photo_identity_mismatch: 'Photo refresh was rejected because the provider or device session changed.',
            photo_unavailable: 'The provider did not return a usable profile photo.',
            photo_denied: 'Photo refresh was cancelled at the provider.',
            photo_provider_error: 'The provider could not complete photo refresh.',
            photo_token_exchange_failed: 'CleanHouse could not complete photo refresh with the provider.',
            photo_user_info_failed: 'CleanHouse could not read the provider profile photo.',
        };
        if (provider !== 'google' && provider !== 'github' && !Object.hasOwn(errors, failure)) return;
        if (provider === 'google' || provider === 'github') {
            try {
                const profile = await request('/api/auth/me');
                renderSidebarProfile(profile.user || null);
                actionResult(profile.user && profile.user.avatar_url
                    ? (provider === 'google' ? 'Google' : 'GitHub') + ' profile photo refreshed.'
                    : 'Photo refresh returned without an available image.', !profile.user || !profile.user.avatar_url);
            } catch (_) {
                actionResult('CleanHouse could not confirm the refreshed profile photo. Retry this section.', true);
            }
        } else {
            actionResult(errors[failure], true);
        }
        url.searchParams.delete('photo_refreshed');
        url.searchParams.delete('error');
        history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    }

    function normalizeTokens(payload) {
        return Array.isArray(payload.tokens) ? payload.tokens : [];
    }

    async function renderApi() {
        setLoading('Loading personal API tokens…');
        try {
            const [payload, reauth] = await Promise.all([request('/api/auth/tokens'), loadReauthCapabilities()]);
            const tokens = normalizeTokens(payload);
            body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">Local automation</span><h2>Personal API tokens</h2><p>Tokens can operate antivirus features as you, but cannot change authentication, sessions, providers, consent, tokens, or account ownership.</p>' +
                '<form id="settings-token-form" class="settings-inline-form"><label for="settings-token-days">Expires in</label><select id="settings-token-days" name="expires_in_days"><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option></select><button type="submit" class="btn-primary">Create token</button></form>' +
                '<div id="settings-token-reveal" aria-live="assertive"></div><div class="settings-list">' + (tokens.length ? tokens.map(token =>
                    '<article class="settings-row"><div><h3>' + esc(token.name || token.prefix || 'CleanHouse token') + '</h3><p>Created ' + esc(token.created_at || 'unknown') + ' · expires ' + esc(token.expires_at || 'unknown') + '</p></div><div class="settings-row-action"><span class="settings-badge ' + (token.revoked_at ? 'unavailable' : 'ok') + '">' + (token.revoked_at ? 'Revoked' : 'Active') + '</span>' +
                    (token.revoked_at ? '' : '<button type="button" class="btn-secondary" data-settings-action="token-rotate" data-token-id="' + esc(token.id) + '">Rotate</button><button type="button" class="btn-danger" data-settings-action="token-revoke" data-token-id="' + esc(token.id) + '">Revoke</button>') + '</div></article>'
                ).join('') : '<div class="settings-empty">No personal API tokens.</div>') + '</div>' + reauthControl(reauth) + '<div id="settings-action-result" aria-live="polite"></div></section>';
            setFooter();
        } catch (error) { setError(error.message); }
    }

    async function renderSecurity() {
        setLoading('Loading device sessions…');
        try {
            const [payload, reauth, mfa] = await Promise.all([request('/api/auth/sessions'), loadReauthCapabilities(), request('/api/auth/mfa/factors')]);
            const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
            const factors = Array.isArray(mfa.factors) ? mfa.factors : [];
            const factorRows = factors.length ? factors.map(factor => '<article class="settings-row"><div><h3>' + esc(factor.label || 'Authenticator') + '</h3><p>Added ' + esc(factor.created_at || 'unknown') + '</p></div><button type="button" class="btn-danger" data-settings-action="mfa-remove" data-factor-id="' + esc(factor.factor_id) + '">Remove</button></article>').join('') : '<div class="settings-empty">No authenticator factors enrolled.</div>';
            body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">Access to this antivirus</span><h2>Security</h2><p>Review device and browser sessions. Revocation survives CleanHouse and Mac restarts.</p><h3>Multi-factor authentication</h3><p>TOTP factors protect admission and sensitive operations. Recovery codes are displayed once.</p>' + (factors.length && !mfa.admissionAuthorized ? '<div class="settings-notice"><strong>MFA verification required.</strong><button type="button" class="btn-primary" data-settings-action="mfa-admit">Verify this session</button></div>' : '') + '<div class="settings-list">' + factorRows + '</div><form id="settings-mfa-enroll-form" class="settings-inline-form"><label for="settings-mfa-label">Factor label</label><input id="settings-mfa-label" value="Authenticator" maxlength="80"><button type="submit" class="btn-primary">Add authenticator</button></form><button type="button" class="btn-secondary" data-settings-action="mfa-recovery-rotate"' + (factors.length ? '' : ' disabled') + '>Rotate recovery codes</button><div id="settings-mfa-result" aria-live="assertive"></div><h3>Sessions</h3><div class="settings-list">' + (sessions.length ? sessions.map(session => {
                const current = Boolean(session.current);
                return '<article class="settings-row"><div><h3>' + esc(session.label || session.device_name || 'Local session') + (current ? ' <span class="sr-only">current</span>' : '') + '</h3><p>Last used ' + esc(session.last_used_at || 'unknown') + ' · expires ' + esc(session.expires_at || 'unknown') + '</p></div><div class="settings-row-action"><span class="settings-badge ' + (current ? 'ok' : 'ready') + '">' + (current ? 'Current' : 'Other') + '</span>' + (current ? '' : '<button type="button" class="btn-danger" data-settings-action="session-revoke" data-session-id="' + esc(session.id) + '">Revoke</button>') + '</div></article>';
            }).join('') : '<div class="settings-empty">No session records were returned.</div>') + '</div>' + reauthControl(reauth) + '<div id="settings-action-result" aria-live="polite"></div></section>';
            setFooter('<button type="button" class="btn-danger" data-settings-action="sessions-revoke-others">Revoke other sessions</button><button type="button" class="btn-secondary" data-settings-action="close">Close</button>');
        } catch (error) { setError(error.message); }
    }

    async function renderAccount() {
        setLoading('Loading account and consent…');
        try {
            const [me, consent, reauth] = await Promise.all([request('/api/auth/me'), request('/api/auth/consent'), loadReauthCapabilities()]);
            const user = me.user || me;
            const required = Array.isArray(consent.required) ? consent.required : [];
            const missing = Array.isArray(consent.missing) ? consent.missing : [];
            body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">CleanHouse identity</span><h2>Account</h2><dl class="settings-facts"><div><dt>Name</dt><dd>' + esc(user.full_name || user.name || 'Not provided') + '</dd></div><div><dt>Email</dt><dd>' + esc(user.email || 'Not provided') + '</dd></div><div><dt>Consent</dt><dd>' + (missing.length ? 'Action required' : 'Current') + '</dd></div></dl>' +
                (missing.length ? '<div class="settings-notice" role="status"><h3>Review required</h3><p>Review the current <a href="/legal/terms" target="_blank" rel="noopener">Terms of Service</a>, <a href="/legal/privacy" target="_blank" rel="noopener">Privacy Notice</a>, and <a href="/legal/eeccd" target="_blank" rel="noopener">EECCD disclosure</a>. Acceptance is required before protected antivirus controls are available.</p><label class="settings-consent"><input id="settings-consent-check" type="checkbox"> I accept the current required policies (' + esc(required.join(', ') || missing.join(', ')) + ').</label><button type="button" class="btn-primary" data-settings-action="consent-accept">Accept current policies</button></div>' : '<div class="settings-notice ok" role="status">Current required policy versions are accepted.</div>') +
                reauthControl(reauth) +
                '<div id="settings-action-result" aria-live="polite"></div></section>';
            setFooter('<a class="btn-secondary settings-link-button" href="/account/delete">Account deletion</a><button type="button" class="btn-danger" data-settings-action="logout">Log out</button><button type="button" class="btn-secondary" data-settings-action="close">Close</button>');
        } catch (error) { setError(error.message); }
    }

    function runtimeSettingRows(settings) {
        const groups = ['collectors', 'risk_thresholds', 'retention', 'evidence_depth', 'automation', 'qpb_policy', 'mediator'];
        function fields(group, values, prefix) {
            return Object.entries(values || {}).map(([key, value]) => {
                const path = prefix ? prefix + '.' + key : key;
                if (value && typeof value === 'object' && !Array.isArray(value)) return fields(group, value, path);
                const label = path.replace(/[._]/g, ' ');
                if (typeof value === 'boolean') {
                    return '<label class="settings-row"><span><strong>' + esc(label) + '</strong><small>Stored by the existing local runtime settings service.</small></span><input class="advanced-setting" type="checkbox" data-group="' + esc(group) + '" data-key="' + esc(path) + '"' + (value ? ' checked' : '') + '></label>';
                }
                const type = typeof value === 'number' ? 'number' : 'text';
                return '<label class="settings-row"><span><strong>' + esc(label) + '</strong><small>Stored by the existing local runtime settings service.</small></span><input class="advanced-setting setting-input" type="' + type + '" data-group="' + esc(group) + '" data-key="' + esc(path) + '" value="' + esc(value) + '"></label>';
            }).join('');
        }
        return groups.filter(group => settings && settings[group]).map(group => {
            const rows = fields(group, settings[group], '');
            return rows ? '<div class="settings-group"><h3>' + esc(group.replace(/_/g, ' ')) + '</h3>' + rows + '</div>' : '';
        }).join('');
    }

    async function renderAdvanced() {
        setLoading('Loading runtime controls…');
        try {
            const payload = await window.CleanHouseAPI.getSettings();
            if (!payload || payload.status !== 'ok' || !payload.settings) throw new Error(payload && payload.message ? payload.message : 'Runtime settings unavailable');
            runtimeSettings = payload.settings;
            body().innerHTML = '<section class="settings-section"><span class="settings-eyebrow">Existing local controls</span><h2>Advanced</h2><p>These controls preserve the existing runtime settings behavior. Their values are local runtime configuration, not authentication policy.</p>' + runtimeSettingRows(runtimeSettings) + '<div id="settings-action-result" aria-live="polite"></div></section>';
            setFooter('<button type="button" class="btn-secondary" data-settings-action="close">Close</button><button type="button" class="btn-primary" data-settings-action="advanced-save">Save Advanced settings</button>');
        } catch (error) { setError(error.message); }
    }

    async function renderActiveTab() {
        body().setAttribute('aria-labelledby', 'settings-tab-' + activeTab);
        body().setAttribute('aria-busy', 'false');
        const label = (TABS.find(item => item[0] === activeTab) || ['', activeTab])[1];
        if (UNAVAILABLE.has(activeTab)) return unavailablePanel(label);
        const renderers = { general: renderGeneral, providers: renderProviders, api: renderApi, security: renderSecurity, account: renderAccount, advanced: renderAdvanced };
        return (renderers[activeTab] || renderGeneral)();
    }

    async function selectTab(id, focus) {
        if (!TABS.some(tab => tab[0] === id)) return;
        activeTab = id;
        renderTabs();
        if (focus) document.getElementById('settings-tab-' + id).focus();
        await renderActiveTab();
        const url = new URL(window.location.href);
        url.searchParams.set('settings', id);
        history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    }

    function firstFocusable() {
        return modal().querySelector('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]');
    }

    function onModalKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeSettingsPanel();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = Array.from(modal().querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]')).filter(node => node.offsetParent !== null);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    async function openSettingsPanel(requestedTab) {
        returnFocus = document.activeElement;
        const query = new URLSearchParams(window.location.search);
        if (!returnUrl) {
            const requestedReturn = query.get('return_to');
            returnUrl = safeLocalPath(requestedReturn) || (window.location.pathname === '/settings' ? '/overview' : window.location.pathname + window.location.search + window.location.hash);
        }
        const selected = requestedTab || query.get('settings') || query.get('tab') || 'general';
        activeTab = TABS.some(tab => tab[0] === selected) ? selected : 'general';
        modal().hidden = false;
        document.body.classList.add('settings-modal-open');
        renderTabs();
        await renderActiveTab();
        await consumeEmailReauthFragment();
        const active = document.getElementById('settings-tab-' + activeTab) || firstFocusable();
        if (active) active.focus();
    }

    function closeSettingsPanel() {
        modal().hidden = true;
        document.body.classList.remove('settings-modal-open');
        body().innerHTML = '';
        footer().innerHTML = '';
        reauthToken = '';
        const destination = returnUrl || '/overview';
        returnUrl = '';
        history.replaceState(history.state, '', destination);
        if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
    }

    function safeLocalPath(value) {
        if (!value || typeof value !== 'string' || new TextEncoder().encode(value).length > 2048) return '';
        let decoded = value;
        for (let attempt = 0; attempt < 4; attempt += 1) {
            if (!decoded.startsWith('/') || decoded.startsWith('//') || decoded.includes('\\') || /[\x00-\x1f\x7f]/.test(decoded)) return '';
            let next;
            try { next = decodeURIComponent(decoded); } catch (_) { return ''; }
            if (next === decoded) break;
            decoded = next;
            if (attempt === 3) return '';
        }
        let parsed;
        try { parsed = new URL(decoded, window.location.origin); } catch (_) { return ''; }
        if (parsed.origin !== window.location.origin) return '';
        const segments = [];
        for (const segment of parsed.pathname.split('/')) {
            if (!segment || segment === '.') continue;
            if (segment === '..') segments.pop(); else segments.push(segment);
        }
        const normalized = '/' + segments.join('/');
        const loopTarget = normalized.replace(/\/+$/, '') || '/';
        if (loopTarget === '/login' || loopTarget === '/signup' || normalized.startsWith('/settings')) return '';
        return parsed.pathname + parsed.search + parsed.hash;
    }

    function policyReturnPath() {
        const query = new URLSearchParams(window.location.search);
        return safeLocalPath(query.get('return_to')) || safeLocalPath(window.location.pathname) || '/overview';
    }

    function policyFocusable() {
        const node = policyModal();
        return node ? Array.from(node.querySelectorAll('button:not([disabled]), a[href], input:not([disabled])')).filter(item => item.offsetParent !== null) : [];
    }

    function openPolicyConsent() {
        const node = policyModal();
        if (!node) return;
        node.hidden = false;
        document.body.classList.add('policy-consent-open');
        const first = policyFocusable()[0];
        if (first) first.focus();
    }

    function closePolicyConsent() {
        const node = policyModal();
        if (!node) return;
        node.hidden = true;
        document.body.classList.remove('policy-consent-open');
        const url = new URL(window.location.href);
        url.searchParams.delete('consent');
        url.searchParams.delete('return_to');
        history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    }

    function onPolicyKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            closePolicyConsent();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = policyFocusable();
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    function syncPolicyAccept() {
        const checked = document.getElementById('policy-consent-checkbox');
        const accept = document.getElementById('policy-consent-accept');
        if (accept) accept.disabled = !checked || !checked.checked;
    }

    async function acceptCurrentPolicies() {
        const checked = document.getElementById('policy-consent-checkbox');
        const result = document.getElementById('policy-consent-result');
        if (!checked || !checked.checked) return;
        try {
            await request('/api/auth/consent', { method: 'POST', body: { accept_current: true } });
            window.location.assign(policyReturnPath());
        } catch (error) {
            if (result) result.textContent = error.message;
        }
    }

    function renderSidebarProfile(user) {
        const link = document.getElementById('settings-profile-link');
        const image = document.getElementById('settings-profile-image');
        const fallback = document.getElementById('settings-profile-fallback');
        if (!link || !image || !fallback || !user) return;
        const label = String(user.full_name || user.name || user.email || 'Account');
        link.setAttribute('aria-label', 'Open settings for ' + label);
        link.dataset.label = label;
        const avatarUrl = String(user.avatar_url || user.picture || '').trim();
        if (!avatarUrl) return;
        image.addEventListener('load', () => { image.hidden = false; fallback.hidden = true; }, { once: true });
        image.addEventListener('error', () => { image.hidden = true; fallback.hidden = false; }, { once: true });
        image.src = avatarUrl;
    }

    async function hydrateAccountChromeAndPolicyGate(forceOpen) {
        try {
            const payload = await request('/api/auth/me');
            renderSidebarProfile(payload.user || null);
            if (forceOpen || payload.consent_required === true) openPolicyConsent();
        } catch (_) {
            if (forceOpen) openPolicyConsent();
        }
    }

    function actionResult(message, error) {
        const target = document.getElementById('settings-action-result');
        if (target) target.innerHTML = '<div class="settings-result ' + (error ? 'error' : 'success') + '" role="status">' + esc(message) + '</div>';
    }

    async function mutate(action, successMessage, rerender) {
        try {
            await action();
            actionResult(successMessage, false);
            if (rerender) await renderActiveTab();
        } catch (error) { actionResult(error.message, true); }
    }

    function buildAdvancedPayload() {
        const result = {};
        document.querySelectorAll('#settings-body .advanced-setting').forEach(input => {
            if (!result[input.dataset.group]) result[input.dataset.group] = {};
            let value = input.type === 'checkbox' ? input.checked : input.value;
            if (input.type === 'number') value = Number(input.value);
            const parts = input.dataset.key.split('.');
            let target = result[input.dataset.group];
            parts.forEach((part, index) => {
                if (index === parts.length - 1) target[part] = value;
                else {
                    if (!target[part]) target[part] = {};
                    target = target[part];
                }
            });
        });
        return result;
    }

    async function handleAction(button) {
        const action = button.dataset.settingsAction;
        if (action === 'close') return closeSettingsPanel();
        if (action === 'retry') return renderActiveTab();
        if (action === 'reauth-email') {
            const scopeByTab = { providers: 'provider_link', api: 'token_manage', security: 'session_manage', account: 'account' };
            const scope = scopeByTab[activeTab] || 'account';
            return mutate(
                () => request('/api/auth/reauth', { method: 'POST', body: { method: 'magic_email_request', scope } }),
                'A single-use confirmation link was sent to your verified email.',
                false
            );
        }
        if (action === 'provider-avatar-refresh') {
            const provider = button.dataset.provider;
            if (!['google', 'github'].includes(provider)) return;
            return mutate(async () => {
                const result = await request('/api/auth/oauth/' + encodeURIComponent(provider) + '?intent=photo', { method: 'POST', body: {} });
                const target = new URL(result.authorization_url || '');
                const expectedOrigin = provider === 'google' ? 'https://accounts.google.com' : 'https://github.com';
                if (target.origin !== expectedOrigin) throw new Error('Provider start did not return the expected authorization URL.');
                window.location.assign(target.href);
            }, 'Opening provider authorization…', false);
        }
        if (action === 'provider-link') {
            const provider = button.dataset.provider;
            if (!['google', 'github'].includes(provider)) return;
            return mutate(async () => {
                const result = await sensitiveMfaRequest('/api/auth/providers/' + encodeURIComponent(provider) + '/start', { method: 'POST', body: { intent: 'link' } }, 'provider.manage', provider);
                const target = result.authorization_url || result.redirect_url;
                if (!target || !String(target).startsWith('/') || String(target).startsWith('//')) throw new Error('Provider start did not return a safe local redirect.');
                window.location.assign(target);
            }, 'Opening provider authorization…', false);
        }
        if (action === 'provider-unlink') return mutate(() => sensitiveMfaRequest('/api/auth/providers/' + encodeURIComponent(button.dataset.provider), { method: 'DELETE' }, 'provider.manage', button.dataset.provider), 'Provider unlinked.', true);
        if (action === 'token-rotate') return mutate(async () => {
            const result = await sensitiveMfaRequest('/api/auth/tokens/' + encodeURIComponent(button.dataset.tokenId) + '/rotate', { method: 'POST', body: {} }, 'token.manage', button.dataset.tokenId);
            revealToken(result);
        }, 'Token rotated. Copy the replacement now.', false);
        if (action === 'token-revoke') return mutate(() => sensitiveMfaRequest('/api/auth/tokens/' + encodeURIComponent(button.dataset.tokenId), { method: 'DELETE' }, 'token.manage', button.dataset.tokenId), 'Token revoked.', true);
        if (action === 'session-revoke') return mutate(() => sensitiveMfaRequest('/api/auth/sessions/' + encodeURIComponent(button.dataset.sessionId), { method: 'DELETE' }, 'session.manage', button.dataset.sessionId), 'Session revoked.', true);
        if (action === 'sessions-revoke-others') return mutate(() => sensitiveMfaRequest('/api/auth/sessions/revoke-others', { method: 'POST', body: {} }, 'session.manage', 'others'), 'Other sessions revoked.', true);
        if (action === 'mfa-remove') return mutate(async () => {
            const target = button.dataset.factorId;
            const proof = await mfaStepUp('factor.remove', target);
            await request('/api/auth/mfa/remove', { method: 'POST', body: { factorId: target, proof } });
        }, 'Authenticator removed.', true);
        if (action === 'mfa-admit') return mutate(async () => {
            await mfaStepUp('authenticate', '');
            const url = new URL(window.location.href);
            const destination = safeLocalPath(url.searchParams.get('return_to')) || '/overview';
            window.location.assign(destination);
        }, 'MFA verification complete.', false);
        if (action === 'mfa-recovery-rotate') return mutate(async () => {
            const proof = await mfaStepUp('recovery.rotate', '');
            const result = await request('/api/auth/mfa/recovery/rotate', { method: 'POST', body: { proof } });
            const target = document.getElementById('settings-mfa-result');
            if (target) target.innerHTML = '<div class="settings-token-reveal" role="alert"><strong>Save these one-time recovery codes now.</strong><code>' + esc((result.recoveryCodes || []).join('\n')) + '</code></div>';
        }, 'Recovery codes rotated.', false);
        if (action === 'consent-accept') {
            const checked = document.getElementById('settings-consent-check');
            if (!checked || !checked.checked) return actionResult('Confirm acceptance before continuing.', true);
            try {
                await request('/api/auth/consent', { method: 'POST', body: { accept_current: true } });
                window.location.assign(returnUrl || '/overview');
            } catch (error) {
                actionResult(error.message, true);
            }
            return;
        }
        if (action === 'logout') return mutate(async () => {
            await request('/api/auth/logout', { method: 'POST', body: {} });
            window.location.assign('/login');
        }, 'Logged out.', false);
        if (action === 'advanced-save') return mutate(async () => {
            const result = await window.CleanHouseAPI.updateSettings(buildAdvancedPayload());
            if (!result || result.status !== 'ok') throw new Error(result && result.message ? result.message : 'Save failed');
            runtimeSettings = result.settings;
        }, 'Advanced runtime settings saved.', false);
    }

    function revealToken(result) {
        const secret = result.token || result.secret || result.api_token;
        const target = document.getElementById('settings-token-reveal');
        if (!target || !secret) return;
        target.innerHTML = '<div class="settings-token-reveal" role="alert"><strong>Copy this token now. It will not be shown again.</strong><code>' + esc(secret) + '</code><button type="button" class="btn-secondary" data-settings-action="token-copy" data-token-value="' + esc(secret) + '">Copy token</button></div>';
    }

    async function consumeEmailReauthFragment() {
        const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
        const token = fragment.get('reauth');
        const scope = fragment.get('scope');
        if (!token || !scope) return;
        history.replaceState(history.state, '', window.location.pathname + window.location.search);
        try {
            const result = await request('/api/auth/reauth', {
                method: 'POST',
                body: { method: 'magic_email_verify', token, scope },
            });
            reauthToken = result.reauthToken || result.reauth_token || '';
            if (!reauthToken) throw new Error('Email confirmation did not return a bounded grant.');
            actionResult('Recent email reauthentication confirmed.', false);
        } catch (error) {
            actionResult(error.message, true);
        }
    }

    async function onClick(event) {
        const tab = event.target.closest('[data-settings-tab]');
        if (tab) { event.preventDefault(); await selectTab(tab.dataset.settingsTab, true); return; }
        const action = event.target.closest('[data-settings-action]');
        if (!action) return;
        event.preventDefault();
        if (action.dataset.settingsAction === 'token-copy') {
            try { await navigator.clipboard.writeText(action.dataset.tokenValue || ''); actionResult('Token copied.', false); }
            catch (_) { actionResult('Copy failed. Select the token manually.', true); }
            return;
        }
        await handleAction(action);
    }

    async function onSubmit(event) {
        if (event.target.id === 'settings-mfa-enroll-form') {
            event.preventDefault();
            try {
                const current = await request('/api/auth/mfa/factors');
                let proof = '';
                if ((current.factors || []).length) proof = await mfaStepUp('factor.add', '');
                const enrolled = await request('/api/auth/mfa/enroll', { method: 'POST', body: { label: document.getElementById('settings-mfa-label').value, proof } });
                const code = window.prompt('Add this provisioning URI to your authenticator, then enter its six-digit code:\n\n' + enrolled.provisioningUri);
                if (!code) throw new Error('Enrollment confirmation was cancelled.');
                const confirmed = await request('/api/auth/mfa/confirm', { method: 'POST', body: { factorId: enrolled.factorId, code: code.trim() } });
                const target = document.getElementById('settings-mfa-result');
                if (target && (confirmed.recoveryCodes || []).length) target.innerHTML = '<div class="settings-token-reveal" role="alert"><strong>Save these one-time recovery codes now.</strong><code>' + esc(confirmed.recoveryCodes.join('\n')) + '</code></div>';
                actionResult('Authenticator activated.', false);
            } catch (error) { actionResult(error.message, true); }
            return;
        }
        if (event.target.id === 'settings-token-form') {
            event.preventDefault();
            const days = Number(document.getElementById('settings-token-days').value || 30);
            try {
                const result = await sensitiveMfaRequest('/api/auth/tokens', { method: 'POST', body: { expires_in_days: days } }, 'token.manage', 'create');
                revealToken(result);
            } catch (error) { actionResult(error.message, true); }
            return;
        }
        if (event.target.id === 'settings-reauth-form') {
            event.preventDefault();
            const field = document.getElementById('settings-reauth-password');
            const password = field ? field.value : '';
            const scopeByTab = { providers: 'provider_link', api: 'token_manage', security: 'session_manage', account: 'account' };
            const scope = scopeByTab[activeTab] || 'account';
            try {
                const result = await request('/api/auth/reauth', { method: 'POST', body: { password, scope } });
                reauthToken = result.reauthToken || result.reauth_token || '';
                if (!reauthToken) throw new Error('Reauthentication did not return a bounded grant.');
                if (field) field.value = '';
                actionResult('Recent reauthentication confirmed.', false);
            } catch (error) {
                if (field) field.value = '';
                actionResult(error.message, true);
            }
        }
    }

    function onTabKeydown(event) {
        const tab = event.target.closest('[data-settings-tab]');
        if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const ids = TABS.map(item => item[0]);
        let index = ids.indexOf(tab.dataset.settingsTab);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = ids.length - 1;
        else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length;
        selectTab(ids[index], true);
    }

    document.addEventListener('DOMContentLoaded', () => {
        const node = modal();
        if (!node) return;
        node.addEventListener('keydown', onModalKeydown);
        node.addEventListener('click', onClick);
        node.addEventListener('submit', onSubmit);
        document.getElementById('settings-tabs').addEventListener('keydown', onTabKeydown);
        node.addEventListener('click', event => { if (event.target === node) closeSettingsPanel(); });
        document.querySelectorAll('a[href="/settings"]').forEach(link => link.addEventListener('click', event => {
            event.preventDefault();
            returnUrl = window.location.pathname + window.location.search + window.location.hash;
            const url = new URL(window.location.href);
            url.searchParams.set('settings', 'general');
            history.pushState(history.state, '', url.pathname + url.search + url.hash);
            openSettingsPanel('general');
        }));
        if (window.location.pathname === '/settings' || new URLSearchParams(window.location.search).has('settings')) openSettingsPanel();
        const consent = new URLSearchParams(window.location.search).get('consent');
        const policy = policyModal();
        if (policy) {
            policy.addEventListener('keydown', onPolicyKeydown);
            policy.addEventListener('change', event => {
                if (event.target && event.target.id === 'policy-consent-checkbox') syncPolicyAccept();
            });
            policy.addEventListener('click', event => {
                const action = event.target.closest('[data-policy-action]');
                if (!action) return;
                event.preventDefault();
                if (action.dataset.policyAction === 'close') closePolicyConsent();
                if (action.dataset.policyAction === 'accept') acceptCurrentPolicies();
            });
        }
        if (window.location.pathname !== '/settings') hydrateAccountChromeAndPolicyGate(consent === 'required');
        else if (window.authState && window.authState.ready) window.authState.ready.then(() => renderSidebarProfile(window.authState.getUser()));
    });

    window.openSettingsPanel = openSettingsPanel;
    window.closeSettingsPanel = closeSettingsPanel;
})();
