(function () {
    'use strict';

    const ALLOWED_STATES = new Set([
        'loading', 'live', 'no_data', 'fallback', 'warming', 'degraded', 'unavailable', 'error'
    ]);
    let activeRequest = null;
    let loadStarted = false;

    function element(id) {
        return document.getElementById(id);
    }

    function normalizedState(value) {
        const state = String(value || 'unavailable').toLowerCase();
        return ALLOWED_STATES.has(state) ? state : 'unavailable';
    }

    function stateLabel(state) {
        return {
            loading: 'Loading',
            live: 'Live',
            no_data: 'No data',
            fallback: 'Fallback',
            warming: 'Warming',
            degraded: 'Degraded',
            unavailable: 'Unavailable',
            error: 'Error',
        }[state] || 'Unavailable';
    }

    function setCard(name, state, copy) {
        const safeState = normalizedState(state);
        const card = document.querySelector(`[data-overview-card="${name}"]`);
        const pill = element(`overview-${name}-state`);
        const description = element(`overview-${name}-copy`);
        if (card) card.dataset.state = safeState;
        if (pill) pill.textContent = stateLabel(safeState);
        if (description) description.textContent = copy;
    }

    function runtimeCopy(runtime) {
        if (runtime.ready && runtime.state === 'live') {
            return 'Canonical operator readiness passed.';
        }
        if (runtime.state === 'warming') {
            return 'CleanHouse is recovering or still warming. Operator readiness has not passed.';
        }
        if (runtime.state === 'degraded') {
            return 'Canonical readiness failed. CleanHouse remains fail-closed.';
        }
        return 'Canonical runtime readiness is unavailable.';
    }

    function networkCopy(network) {
        if (network.state === 'live' && network.operational) {
            return 'The bounded Network collector is operational.';
        }
        if (network.state === 'warming') {
            return 'The Network collector is starting with bounded retry.';
        }
        if (network.reason_code === 'capture_engine_unavailable') {
            return 'Packet capture is unavailable. No packet data is being fabricated.';
        }
        if (network.state === 'degraded') {
            return 'Network collection is degraded. Review the Network page for its bounded reason.';
        }
        return 'Network collection is unavailable.';
    }

    function filesCopy(files) {
        if (files.state === 'live' && files.operational && files.evidence_authenticated) {
            return 'Authenticated Wazuh file evidence is live.';
        }
        if (files.state === 'no_data' && files.operational) {
            return 'Wazuh is connected; no authenticated file events are available yet.';
        }
        if (files.state === 'fallback' && files.fallback_active) {
            return 'Local watchdog fallback is active. This is not Wazuh evidence.';
        }
        if (files.state === 'warming') {
            return 'Wazuh is configured but authenticated evidence is not operational yet.';
        }
        if (files.state === 'degraded') {
            return 'File monitoring is degraded. Retained evidence may still be available.';
        }
        return 'File monitoring is unavailable.';
    }

    function renderPayload(payload) {
        if (!payload || payload.schema !== 'cleanhouse.overview.v1') {
            throw new Error('Overview status contract unavailable');
        }
        const runtime = payload.runtime || {};
        const network = payload.network || {};
        const files = payload.files || {};
        setCard('runtime', runtime.state, runtimeCopy(runtime));
        setCard('network', network.state, networkCopy(network));
        setCard('files', files.state, filesCopy(files));
        const announcement = element('overview-announcement');
        if (announcement) {
            announcement.textContent = payload.state === 'live'
                ? 'CleanHouse status is live.'
                : `CleanHouse status is ${stateLabel(normalizedState(payload.state)).toLowerCase()}.`;
        }
    }

    function renderFailure() {
        setCard('runtime', 'error', 'Runtime status could not be loaded.');
        setCard('network', 'unavailable', 'Network status could not be loaded.');
        setCard('files', 'unavailable', 'Files status could not be loaded.');
        const announcement = element('overview-announcement');
        if (announcement) announcement.textContent = 'CleanHouse status is unavailable. Use Refresh status to retry.';
    }

    async function loadOverview() {
        loadStarted = true;
        const retry = element('overview-retry');
        if (retry) retry.disabled = true;
        if (activeRequest) activeRequest.abort();
        activeRequest = new AbortController();
        const timer = window.setTimeout(() => activeRequest.abort(), 5000);
        try {
            const response = await fetch('/cleanhouse/overview', {
                credentials: 'include',
                cache: 'no-store',
                headers: { Accept: 'application/json' },
                signal: activeRequest.signal,
            });
            if (response.status === 401) {
                window.location.assign('/login?redirect=%2Foverview');
                return;
            }
            if (!response.ok) throw new Error(`Overview status failed with ${response.status}`);
            renderPayload(await response.json());
        } catch (error) {
            if (error && error.name === 'AbortError' && activeRequest?.signal.aborted) {
                renderFailure();
            } else {
                renderFailure();
            }
        } finally {
            window.clearTimeout(timer);
            if (retry) retry.disabled = false;
        }
    }

    async function logout() {
        const announcement = element('overview-announcement');
        if (announcement) announcement.textContent = 'Signing out…';
        try {
            const response = await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) throw new Error('Logout failed');
            window.location.assign('/login');
        } catch (error) {
            if (announcement) announcement.textContent = 'Sign out failed. Try again.';
        }
    }

    function initOverview() {
        element('overview-retry')?.addEventListener('click', loadOverview);
        element('cleanhouse-logout')?.addEventListener('click', logout);
        if (!loadStarted && document.querySelector('[data-view-panel="home"]:not([hidden])')) {
            loadOverview();
        }
    }

    document.addEventListener('DOMContentLoaded', initOverview);
    window.addEventListener('cleanhouse:viewchange', event => {
        if (event.detail?.view === 'home') loadOverview();
    });
})();
