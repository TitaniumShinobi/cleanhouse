import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { setTimeout as delay } from 'node:timers/promises';

const ROOT = new URL('../', import.meta.url);
const API_CLIENT_PATH = new URL('../frontend/js/api-client.js', import.meta.url);
const INVESTIGATIONS_PATH = new URL('../frontend/js/investigations.js', import.meta.url);
const API_CLIENT_SOURCE = fs.readFileSync(API_CLIENT_PATH, 'utf8');
const INVESTIGATIONS_SOURCE = fs.readFileSync(INVESTIGATIONS_PATH, 'utf8');

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

class MockClassList {
    constructor(owner) {
        this.owner = owner;
        this.values = new Set();
    }

    toggle(value, force) {
        if (force === undefined) {
            if (this.values.has(value)) this.values.delete(value);
            else this.values.add(value);
            return this.values.has(value);
        }
        if (force) this.values.add(value);
        else this.values.delete(value);
        return Boolean(force);
    }

    add(value) {
        this.values.add(value);
    }

    remove(value) {
        this.values.delete(value);
    }

    contains(value) {
        return this.values.has(value);
    }
}

class MockElement {
    constructor(id = '', dataset = {}) {
        this.id = id;
        this.dataset = { ...dataset };
        this.hidden = false;
        this.innerHTML = '';
        this.textContent = '';
        this.outerHTML = '';
        this.open = false;
        this.scrollLeft = 0;
        this.scrollTop = 0;
        this.value = '';
        this.listeners = new Map();
        this.attributes = new Map();
        this.classList = new MockClassList(this);
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }

    getAttribute(name) {
        return this.attributes.get(name) ?? null;
    }

    addEventListener(type, handler) {
        if (!this.listeners.has(type)) this.listeners.set(type, []);
        this.listeners.get(type).push(handler);
    }

    dispatch(type, event = {}) {
        (this.listeners.get(type) || []).forEach(handler => handler({
            currentTarget: this,
            target: this,
            preventDefault() {},
            ...event,
        }));
    }

    appendChild(child) {
        return child;
    }

    querySelector() {
        return null;
    }

    querySelectorAll() {
        return [];
    }

    closest() {
        return null;
    }

    getBoundingClientRect() {
        return { top: 0, right: 0, left: 0, bottom: 0, width: 0, height: 0 };
    }
}

function createHarness() {
    const ids = new Map();
    const panels = ['home', 'applications', 'files', 'custom', 'network', 'app-dashboard'].map(name => {
        const panel = new MockElement(name);
        panel.dataset.viewPanel = name;
        return panel;
    });
    const navLinks = ['home', 'applications', 'files', 'custom', 'network'].map(name => {
        const link = new MockElement(`nav-${name}`);
        link.dataset.view = name;
        return link;
    });
    const viewButtons = ['table', 'findings', 'timeline'].map(name => {
        const button = new MockElement(`view-${name}`, { networkView: name });
        return button;
    });
    const graphButtons = ['graph', 'chart'].map(name => {
        const button = new MockElement(`graph-${name}`, { networkTrendDisplay: name });
        return button;
    });
    const timelineButtons = ['1m', '30m', '1h', '24h', '7d', '1mo', '3mo', '12mo'].map(name => {
        const button = new MockElement(`timeline-${name}`, { networkTimelineRange: name });
        return button;
    });
    const trendButtons = ['vulnerabilities', 'threats', 'strengths'].map(value => {
        const button = new MockElement(`trend-series-${value}`, { networkTrendSeries: value });
        return button;
    });
    const trendSort = new MockElement('trend-sort');
    trendSort.value = 'canonical';
    const graphToggle = new MockElement('graph-toggle');
    const body = new MockElement('body');
    const documentListeners = new Map();
    const windowListeners = new Map();
    const storage = new Map();
    const liveSources = [];
    let timeoutId = 0;
    const timers = new Map();
    const location = {
        protocol: 'http:',
        origin: 'http://127.0.0.1:3333',
        href: 'http://127.0.0.1:3333/network',
        pathname: '/network',
        search: '',
    };

    class MockEventSource {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSED = 2;

        constructor(url) {
            this.url = String(url || '');
            this.readyState = MockEventSource.CONNECTING;
            this.listeners = new Map();
            this.onerror = null;
            liveSources.push(this);
        }

        close() {
            this.readyState = MockEventSource.CLOSED;
        }

        addEventListener(type, handler) {
            if (!this.listeners.has(type)) this.listeners.set(type, []);
            this.listeners.get(type).push(handler);
        }

        emit(type, payload = {}, options = {}) {
            if (type === 'open') this.readyState = MockEventSource.OPEN;
            const event = {
                data: typeof payload === 'string' ? payload : JSON.stringify(payload),
                lastEventId: String(options.lastEventId || ''),
            };
            (this.listeners.get(type) || []).forEach(handler => handler(event));
        }

        fail(options = {}) {
            if (options.closed) this.readyState = MockEventSource.CLOSED;
            if (typeof this.onerror === 'function') this.onerror(new Error('stream failed'));
        }
    }

    [
        'network-engine-panel',
        'scan-network-btn',
        'network-results',
        'network-toolbar-context',
        'network-area-status',
        'network-message',
        'action-sidebar-shell',
        'action-sidebar-toggle',
        'notification-center',
        'notification-center-menu',
        'notification-center-button',
        'notification-center-badge',
        'apps-area-status',
        'app-grid',
    ].forEach(id => ids.set(id, new MockElement(id)));

    const document = {
        body,
        hidden: false,
        readyState: 'loading',
        getElementById(id) {
            if (!ids.has(id)) ids.set(id, new MockElement(id));
            return ids.get(id);
        },
        createElement(tag) {
            return new MockElement(tag);
        },
        addEventListener(type, handler) {
            if (!documentListeners.has(type)) documentListeners.set(type, []);
            documentListeners.get(type).push(handler);
        },
        querySelector(selector) {
            if (selector === '.network-graph-toggle') return graphToggle;
            if (selector === '[data-network-trend-sort]') return trendSort;
            return null;
        },
        querySelectorAll(selector) {
            if (selector === '[data-view-panel]') return panels;
            if (selector === '.nav-link') return navLinks;
            if (selector === '[data-network-view]') return viewButtons;
            if (selector === '[data-network-trend-display]') return graphButtons;
            if (selector === '[data-network-timeline-range]') return timelineButtons;
            if (selector === '[data-network-trend-series]') return trendButtons;
            return [];
        },
    };

    const windowObject = {
        document,
        location,
        history: {
            replaceState(_state, _title, value) {
                if (typeof value === 'string' && value.startsWith('/')) {
                    location.pathname = value;
                    location.href = `${location.origin}${value}`;
                    return;
                }
                if (value && typeof value === 'object') {
                    location.pathname = value.pathname || location.pathname;
                    location.search = value.search || location.search;
                    location.href = `${location.origin}${location.pathname}${location.search}`;
                }
            },
        },
        localStorage: {
            getItem(key) {
                return storage.has(key) ? storage.get(key) : null;
            },
            setItem(key, value) {
                storage.set(key, String(value));
            },
            removeItem(key) {
                storage.delete(key);
            },
        },
        setTimeout(fn, ms = 0) {
            const id = ++timeoutId;
            const handle = setTimeout(() => {
                timers.delete(id);
                fn();
            }, ms);
            timers.set(id, handle);
            return id;
        },
        clearTimeout(id) {
            const handle = timers.get(id);
            if (handle) {
                clearTimeout(handle);
                timers.delete(id);
            }
        },
        setInterval(fn, ms = 0) {
            const id = ++timeoutId;
            const handle = setInterval(fn, ms);
            timers.set(id, handle);
            return id;
        },
        clearInterval(id) {
            const handle = timers.get(id);
            if (handle) {
                clearInterval(handle);
                timers.delete(id);
            }
        },
        requestAnimationFrame(fn) {
            return windowObject.setTimeout(() => fn(Date.now()), 0);
        },
        cancelAnimationFrame(id) {
            windowObject.clearTimeout(id);
        },
        addEventListener(type, handler) {
            if (!windowListeners.has(type)) windowListeners.set(type, []);
            windowListeners.get(type).push(handler);
        },
        removeEventListener(type, handler) {
            const list = windowListeners.get(type) || [];
            windowListeners.set(type, list.filter(item => item !== handler));
        },
        EventSource: MockEventSource,
        fetch: async () => ({ json: async () => ({}) }),
        console,
        URL,
        URLSearchParams,
        AbortController,
        performance: { now: () => Date.now() },
        innerWidth: 1440,
        innerHeight: 900,
        navigator: { userAgent: 'node-test' },
    };
    windowObject.window = windowObject;
    windowObject.self = windowObject;

    const context = vm.createContext({
        console,
        window: windowObject,
        document,
        history: windowObject.history,
        location,
        localStorage: windowObject.localStorage,
        URL,
        URLSearchParams,
        AbortController,
        setTimeout: windowObject.setTimeout,
        clearTimeout: windowObject.clearTimeout,
        setInterval: windowObject.setInterval,
        clearInterval: windowObject.clearInterval,
        fetch: windowObject.fetch,
        EventSource: windowObject.EventSource,
        performance: windowObject.performance,
    });
    context.window = windowObject;
    context.globalThis = context;
    vm.runInContext(API_CLIENT_SOURCE, context, { filename: API_CLIENT_PATH.pathname });
    vm.runInContext(INVESTIGATIONS_SOURCE, context, { filename: INVESTIGATIONS_PATH.pathname });
    vm.runInContext(`
        const __networkTestRealStartLiveUpdates = startNetworkLiveUpdates;
        const __networkTestRealStopLiveUpdates = stopNetworkLiveUpdates;
        startNetworkLiveUpdates = () => {};
        stopNetworkLiveUpdates = () => {};
        renderActionSidebar = () => {};
        bindNetworkEvidenceRows = () => {};
        bindNetworkFindingsWindow = () => {};
        bindNetworkPieInteractions = () => {};
        bindNetworkEvidenceElements = () => {};
        bindNetworkFloatingTooltips = () => {};
        enableNetworkColumnResize = () => {};
        restoreNetworkTableScroll = () => {};
        applyNetworkCtrlRouteTarget = () => {};
        renderActionSidebar = () => {};
        window.__CLEANHOUSE_NETWORK_TEST_HOOKS__ = {
            setView(mode) {
                networkViewMode = validNetworkViewMode(mode) || 'table';
                syncNetworkCoordinatorUiState();
            },
            setRange(rangeKey) {
                networkTimelineRangeMode = validNetworkTimelineRange(rangeKey) || '5s';
                syncNetworkCoordinatorUiState();
            },
            async hydrate(options = {}) {
                return await hydrateNetworkView(options);
            },
            async loadSnapshot(refresh = false, options = {}) {
                return await loadNetworkHeaderSnapshot(refresh, options);
            },
            cancelSnapshot() {
                cancelNetworkSnapshotLifecycle();
            },
            snapshotLifecycle() {
                return {
                    inFlight: networkHeaderSnapshotInFlight,
                    hasActivePromise: Boolean(networkSnapshotActivePromise),
                    hasPendingDemand: Boolean(networkSnapshotPendingDemand),
                    failureCount: networkSnapshotFailureCount,
                    backoffUntil: networkSnapshotBackoffUntil,
                };
            },
            async selectView(mode, options = {}) {
                return await selectNetworkView(mode, options);
            },
            async selectRange(rangeKey, options = {}) {
                return await selectNetworkRange(rangeKey, options);
            },
            render() {
                renderNetworkDisplay();
            },
            buildRenderModel(mode = networkViewMode) {
                return buildNetworkRenderModel(mode);
            },
            setTrendLiveTicks(ticks = []) {
                networkTrendLiveTape = Array.isArray(ticks) ? ticks.map(item => ({ ...item })) : [];
                syncNetworkCoordinatorUiState();
            },
            setTrendControls(options = {}) {
                networkTrendDisplayMode = validNetworkTrendDisplayMode(options.display) || networkTrendDisplayMode;
                networkTrendSortMode = validNetworkTrendSortMode(options.sort) || networkTrendSortMode;
                const selected = validNetworkTrendSeries(options.series || []);
                if (selected.length) networkTrendSeriesFilter = new Set(selected);
            },
            trendDataset(events = []) {
                const dataset = networkTrendDataset(events);
                return {
                    series: dataset.series.map(item => item.key),
                    totals: { ...dataset.totals },
                    gaps: dataset.slots.filter(slot => !slot.event).length,
                    observed: dataset.slots.filter(slot => slot.event).length,
                };
            },
            submitHeader(source, payload, options = {}) {
                submitNetworkHeaderEvidence(source, payload, options);
            },
            startLiveNow() {
                startNetworkLiveUpdatesNow();
            },
            enableLiveRuntime() {
                startNetworkLiveUpdates = __networkTestRealStartLiveUpdates;
                stopNetworkLiveUpdates = __networkTestRealStopLiveUpdates;
            },
            transportSnapshot() {
                return JSON.parse(JSON.stringify({
                    snapshotCursor: networkSnapshotCursor,
                    lastAppliedCursor: networkLastAppliedCursor,
                    cursorEpoch: networkCursorEpoch,
                    replayBufferLength: networkLiveReplayBuffer.length,
                    seenDeliveryCount: networkLiveSeenDeliveryKeys.size,
                    sourceUrl: networkLiveSource?.url || '',
                    rawEventIds: (Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events : [])
                        .flatMap(event => Array.isArray(event.raw_packet_events) ? event.raw_packet_events : [])
                        .map(event => event.event_id),
                }));
            },
            snapshot() {
                return JSON.parse(JSON.stringify({
                    coordinator: networkCoordinatorState,
                    viewMode: networkViewMode,
                    rangeMode: networkTimelineRangeMode,
                    currentNetworkData,
                    currentNetworkTableData,
                    currentNetworkProjectionData,
                    currentNetworkHeaderData,
                    currentNetworkTrendBaseData,
                    currentNetworkTags,
                    networkTimelineLastGoodMeta,
                    messageText: byId('network-message')?.textContent || '',
                    resultsHtml: byId('network-results')?.innerHTML || '',
                    toolbarHtml: byId('network-toolbar-context')?.innerHTML || '',
                    areaStatus: byId('network-area-status')?.textContent || '',
                }));
            },
        };
    `, context);

    function setApi(api) {
        context.window.CleanHouseAPI = api;
    }

    function cleanup() {
        for (const handle of timers.values()) {
            clearTimeout(handle);
            clearInterval(handle);
        }
        timers.clear();
    }

    return {
        context,
        hooks: context.window.__CLEANHOUSE_NETWORK_TEST_HOOKS__,
        liveSources,
        elements: { ids, viewButtons, graphButtons, timelineButtons, trendButtons, trendSort, graphToggle },
        setApi,
        cleanup,
    };
}

async function flush(ms = 0) {
    await delay(ms);
    await delay(0);
}

function networkEvent(id, extra = {}) {
    return {
        event_id: id,
        timestamp: extra.timestamp || '2026-07-07T12:00:00Z',
        protocol: extra.protocol || 'TCP',
        app_name: extra.app_name || 'Safari',
        dst_ip: extra.dst_ip || '203.0.113.10',
        dst_port: extra.dst_port || 443,
        summary: extra.summary || id,
        ...extra,
    };
}

function trendTick(id, extra = {}) {
    const now = Date.now();
    const start = new Date(now - 4000).toISOString();
    const end = new Date(now + 1000).toISOString();
    return {
        tick_id: id,
        bucket_key: id,
        bucket_range: extra.bucket_range || '5s',
        bucket_start: extra.bucket_start || start,
        bucket_end: extra.bucket_end || end,
        timestamp: extra.timestamp || end,
        evidence_state: 'observed',
        interpretation_schema: 'cleanhouse.network.trend.interpretation.v1',
        rule_version: 'network-trend-rationalization.v1',
        interpretation: extra.interpretation || {
            vulnerabilities: { value: 1, confidence: 0.8, rationale: ['Unknown external owner.'], signals: ['unknown_external_owner'], evidence_refs: [] },
            threats: { value: 0, confidence: null, rationale: [], signals: [], evidence_refs: [] },
            strengths: { value: 1, confidence: 0.8, rationale: ['Encrypted service.'], signals: ['encrypted_service'], evidence_refs: [] },
        },
        evidence_count: extra.evidence_count ?? 1,
        contradiction_count: extra.contradiction_count ?? 1,
        event_id: extra.event_id || id,
        evidence_refs: extra.evidence_refs || [],
        related_event_ids: extra.related_event_ids || [],
        ...extra,
    };
}

test('snapshot lifecycle serializes automatic demand and coalesces the newest refresh', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const first = deferred();
    const second = deferred();
    let active = 0;
    let maxActive = 0;
    const calls = [];
    harness.setApi({
        async getNetwork(options = {}) {
            active += 1;
            maxActive = Math.max(maxActive, active);
            calls.push(Boolean(options.refresh));
            const result = await (calls.length === 1 ? first.promise : second.promise);
            active -= 1;
            return result;
        },
    });

    const initial = harness.hooks.loadSnapshot(false, { reason: 'quiet-refresh' });
    const redundant = harness.hooks.loadSnapshot(false, { reason: 'quiet-refresh' });
    const manual = harness.hooks.loadSnapshot(true, { reason: 'manual-refresh' });
    await flush();
    assert.equal(calls.length, 1);
    assert.equal(harness.hooks.snapshotLifecycle().hasPendingDemand, true);

    first.resolve({ state: 'CAPTURING', events: [], summary: { reason: 'first' } });
    await initial;
    await flush();
    assert.equal(calls.length, 2);
    assert.equal(calls[1], true);
    assert.equal(maxActive, 1);

    second.resolve({ state: 'CAPTURING', events: [], summary: { reason: 'second' } });
    await Promise.all([redundant, manual]);
    assert.equal(maxActive, 1);
    assert.equal(harness.hooks.snapshotLifecycle().hasPendingDemand, false);
});

test('snapshot lifecycle teardown retires pending work without starting another request', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const active = deferred();
    let calls = 0;
    harness.setApi({
        async getNetwork() {
            calls += 1;
            return active.promise;
        },
    });

    const first = harness.hooks.loadSnapshot(false, { reason: 'quiet-refresh' });
    const pending = harness.hooks.loadSnapshot(true, { reason: 'manual-refresh' });
    harness.hooks.cancelSnapshot();
    await pending;
    active.resolve({ state: 'CAPTURING', events: [], summary: { reason: 'retired' } });
    await first;
    await flush();
    assert.equal(calls, 1);
    assert.equal(harness.hooks.snapshotLifecycle().hasPendingDemand, false);
});

test('snapshot lifecycle backs off automatic failures but manual refresh recovers immediately', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    let calls = 0;
    harness.setApi({
        async getNetwork() {
            calls += 1;
            if (calls === 1) throw new Error('slow backend');
            return { state: 'CAPTURING', events: [], summary: { reason: 'recovered' } };
        },
    });

    await harness.hooks.loadSnapshot(false, { reason: 'quiet-refresh' });
    const failed = harness.hooks.snapshotLifecycle();
    assert.equal(failed.failureCount, 1);
    assert.ok(failed.backoffUntil > Date.now());
    await harness.hooks.loadSnapshot(false, { reason: 'quiet-refresh' });
    assert.equal(calls, 1);
    await harness.hooks.loadSnapshot(true, { reason: 'manual-refresh' });
    assert.equal(calls, 2);
    assert.equal(harness.hooks.snapshotLifecycle().failureCount, 0);
});

test('snapshot cursor seeds live replay and refresh preserves in-flight cursor continuity', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const refreshSnapshot = deferred();
    const bootId = 'boot-cursor-a';
    let snapshotCalls = 0;
    const snapshotEvent = networkEvent('snapshot-10', {
        cursor: `${bootId}:10`,
        sequence: 10,
        collector_sequence: 10,
        server_boot_id: bootId,
        packet_index: 10,
    });

    harness.setApi({
        async getNetwork() {
            snapshotCalls += 1;
            if (snapshotCalls > 1) return refreshSnapshot.promise;
            return {
                state: 'CAPTURING',
                server_boot_id: bootId,
                cursor: `${bootId}:10`,
                high_water_cursor: `${bootId}:10`,
                events: [snapshotEvent],
                event_count: 1,
                summary: { reason: 'snapshot', cursor: `${bootId}:10` },
            };
        },
        async getNetworkProjection() {
            return { state: 'CAPTURING', events: [], summary: { reason: 'projection' } };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live?client=test';
        },
    });

    harness.hooks.setView('table');
    await harness.hooks.hydrate({ refresh: false, reason: 'cursor-handoff' });
    harness.hooks.startLiveNow();

    assert.equal(harness.liveSources.length, 1);
    const source = harness.liveSources[0];
    assert.equal(new URL(source.url).searchParams.get('after'), `${bootId}:10`);
    source.emit('open');

    const live11 = networkEvent('live-11', {
        cursor: `${bootId}:11`,
        sequence: 11,
        collector_sequence: 11,
        server_boot_id: bootId,
        packet_index: 11,
        timestamp: '2026-07-07T12:00:01Z',
    });
    source.emit('network-event', live11, { lastEventId: `${bootId}:11` });
    source.emit('network-event', live11, { lastEventId: `${bootId}:11` });

    let transport = harness.hooks.transportSnapshot();
    assert.equal(transport.lastAppliedCursor, `${bootId}:11`);
    assert.equal(transport.replayBufferLength, 1);
    assert.equal(transport.rawEventIds.filter(id => id === 'live-11').length, 1);

    const refreshPromise = harness.hooks.hydrate({ refresh: true, reason: 'manual-refresh' });
    await flush();
    const live12 = networkEvent('live-12', {
        cursor: `${bootId}:12`,
        sequence: 12,
        collector_sequence: 12,
        server_boot_id: bootId,
        packet_index: 12,
        timestamp: '2026-07-07T12:00:02Z',
    });
    source.emit('network-event', live12, { lastEventId: `${bootId}:12` });
    refreshSnapshot.resolve({
        state: 'CAPTURING',
        server_boot_id: bootId,
        cursor: `${bootId}:10`,
        high_water_cursor: `${bootId}:10`,
        events: [snapshotEvent],
        event_count: 1,
        summary: { reason: 'snapshot', cursor: `${bootId}:10` },
    });
    await refreshPromise;

    transport = harness.hooks.transportSnapshot();
    assert.equal(harness.liveSources.length, 1);
    assert.equal(transport.lastAppliedCursor, `${bootId}:12`);
    assert.equal(JSON.stringify(transport.rawEventIds.sort()), JSON.stringify(['live-11', 'live-12', 'snapshot-10']));

    source.emit('gap', {
        state: 'ERROR',
        server_boot_id: bootId,
        cursor: `${bootId}:13`,
        sequence: 13,
        collector_sequence: 13,
        summary: { reason: 'continuity_gap' },
    }, { lastEventId: `${bootId}:13` });
    assert.equal(harness.hooks.transportSnapshot().lastAppliedCursor, `${bootId}:13`);

    source.fail();
    assert.equal(harness.liveSources.length, 1);
    assert.equal(harness.hooks.transportSnapshot().lastAppliedCursor, `${bootId}:13`);

    harness.hooks.enableLiveRuntime();
    source.fail({ closed: true });
    harness.hooks.startLiveNow();
    assert.equal(harness.liveSources.length, 2);
    assert.equal(new URL(harness.liveSources[1].url).searchParams.get('after'), `${bootId}:13`);
});

test('stale snapshot response is ignored when a newer hydration wins', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const snapshotA = deferred();
    const snapshotB = deferred();
    const projectionB = deferred();
    const snapshotCalls = [];
    const projectionCalls = [];

    harness.setApi({
        async getNetwork(options = {}) {
            snapshotCalls.push({ snapshot: Boolean(options.snapshot), refresh: Boolean(options.refresh), abortedAtCall: Boolean(options.signal?.aborted) });
            return snapshotCalls.length === 1 ? snapshotA.promise : snapshotB.promise;
        },
        async getNetworkProjection(view, range, options = {}) {
            projectionCalls.push({ view, range, abortedAtCall: Boolean(options.signal?.aborted) });
            return projectionB.promise;
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('findings');
    const hydrationA = harness.hooks.hydrate({ refresh: false, reason: 'race-a' });
    await flush();
    const hydrationB = harness.hooks.hydrate({ refresh: true, reason: 'race-b' });
    await flush();
    snapshotA.resolve({ state: 'CAPTURING', events: [networkEvent('stale-raw')], event_count: 123, summary: { reason: 'snapshot-a' } });
    await flush();
    snapshotB.resolve({ state: 'CAPTURING', events: [networkEvent('fresh-raw')], event_count: 15, summary: { reason: 'snapshot-b' } });
    await flush();
    projectionB.resolve({
        state: 'CAPTURING',
        events: [networkEvent('finding-group-1')],
        summary: { counts: { connections: 15 }, reason: 'projection', grouped: true },
    });
    await hydrationB;
    await hydrationA;

    const state = harness.hooks.snapshot();
    assert.equal(snapshotCalls.length, 2);
    assert.deepEqual(projectionCalls.map(call => call.view), ['findings']);
    assert.equal(state.coordinator.requests.hydrationEpoch, 2);
    assert.equal(state.coordinator.snapshot.data.summary.reason, 'snapshot-b');
    assert.equal(state.coordinator.projections.findings['5s'].data.summary.grouped, true);
    assert.equal(state.currentNetworkData.summary.grouped, true);
    assert.equal(state.messageText, '1 findings.');
});

test('stale projection response is ignored after tab change', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const snapshot = deferred();
    const findingsProjection = deferred();
    const timelineProjection = deferred();
    const projectionCalls = [];

    harness.setApi({
        async getNetwork(options = {}) {
            return snapshot.promise;
        },
        async getNetworkProjection(view, range) {
            projectionCalls.push({ view, range });
            if (view === 'findings') return findingsProjection.promise;
            return timelineProjection.promise;
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('findings');
    const hydratePromise = harness.hooks.hydrate({ refresh: false, reason: 'findings-first' });
    snapshot.resolve({ state: 'CAPTURING', events: [networkEvent('base')], event_count: 42, summary: { reason: 'snapshot' } });
    await flush();
    harness.hooks.setView('timeline');
    const timelineLoad = vm.runInContext(`loadNetworkProjection('timeline', true, { epoch: networkHydrationEpoch });`, harness.context);
    await flush();
    findingsProjection.resolve({
        state: 'CAPTURING',
        events: [networkEvent('stale-finding')],
        summary: { counts: { connections: 42 }, grouped: true },
    });
    timelineProjection.resolve({
        state: 'CAPTURING',
        events: [networkEvent('timeline-fresh')],
        summary: { reason: 'projection', timeline_source: 'saved' },
    });
    await hydratePromise;
    await timelineLoad;
    harness.hooks.render();

    const state = harness.hooks.snapshot();
    assert.deepEqual(projectionCalls.map(call => call.view), ['findings', 'timeline']);
    assert.equal(state.viewMode, 'timeline');
    assert.equal(state.coordinator.render.model.mode, 'timeline');
    assert.equal(state.coordinator.render.model.data.events[0].event_id, 'timeline-fresh');
    assert.equal(state.messageText, '1 events in the last minute.');
});

test('findings hydration keeps grouped count authoritative', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const snapshot = deferred();
    const findingsProjection = deferred();

    harness.setApi({
        async getNetwork() {
            return snapshot.promise;
        },
        async getNetworkProjection() {
            return findingsProjection.promise;
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('findings');
    const hydratePromise = harness.hooks.hydrate({ refresh: false, reason: 'findings-grouped' });
    snapshot.resolve({
        state: 'CAPTURING',
        events: Array.from({ length: 3 }, (_, index) => networkEvent(`raw-${index}`)),
        event_count: 123,
        summary: { reason: 'snapshot', counts: { connections: 123 } },
    });
    await flush();
    let state = harness.hooks.snapshot();
    assert.match(state.messageText, /Loading grouped network findings|No grouped findings/);
    findingsProjection.resolve({
        state: 'CAPTURING',
        events: Array.from({ length: 15 }, (_, index) => networkEvent(`group-${index}`)),
        summary: { reason: 'projection', counts: { connections: 123 }, grouped: true },
    });
    await hydratePromise;
    state = harness.hooks.snapshot();
    assert.equal(state.messageText, '15 findings.');
    assert.equal(state.coordinator.render.model.mode, 'findings');
    assert.equal(state.coordinator.render.model.data.summary.grouped, true);
});

test('timeline range selection persists and redraws with selected range', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const projectionCalls = [];

    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [networkEvent('snapshot')], event_count: 1, summary: { reason: 'snapshot' } };
        },
        async getNetworkProjection(view, range) {
            projectionCalls.push({ view, range });
            return {
                state: 'CAPTURING',
                events: [networkEvent(`timeline-${range}`)],
                summary: { reason: 'projection', timeline_source: 'saved' },
            };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('timeline');
    await harness.hooks.hydrate({ refresh: false, reason: 'timeline-range' });
    await flush();
    await harness.hooks.selectRange('24h', { refresh: true });
    await flush(5);
    harness.hooks.render();

    const state = harness.hooks.snapshot();
    assert.equal(state.rangeMode, '24h');
    assert.equal(state.coordinator.ui.selectedRangeByView.timeline, '24h');
    assert.equal(state.coordinator.requests.projection.selectedRange, '24h');
    assert.equal(state.coordinator.requests.projection.effectiveFetchRange, '24h');
    assert.match(state.toolbarHtml, /data-network-timeline-range="24h" class="active"/);
    assert.equal(state.coordinator.render.model.selectedRange, '24h');
    assert.equal(state.messageText, '1 events in the last 24 hours.');
    assert.equal(projectionCalls.at(-1).range, '24h');
});

test('range change ignores stale timeline projection for previous range', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const firstProjection = deferred();
    const secondProjection = deferred();
    const projectionCalls = [];
    let projectionIndex = 0;

    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [networkEvent('snapshot')], event_count: 1, summary: { reason: 'snapshot' } };
        },
        async getNetworkProjection(view, range) {
            projectionCalls.push({ view, range });
            projectionIndex += 1;
            if (projectionIndex === 1) return firstProjection.promise;
            return secondProjection.promise;
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('timeline');
    harness.hooks.setRange('1m');
    const firstLoad = harness.hooks.hydrate({ refresh: false, reason: 'timeline-race' });
    await flush();
    const secondLoad = harness.hooks.selectRange('24h', { refresh: true });
    await flush();
    firstProjection.resolve({
        state: 'CAPTURING',
        events: [networkEvent('timeline-stale')],
        summary: { reason: 'projection', timeline_source: 'saved' },
    });
    secondProjection.resolve({
        state: 'CAPTURING',
        events: [networkEvent('timeline-current')],
        summary: { reason: 'projection', timeline_source: 'saved' },
    });
    await Promise.all([firstLoad, secondLoad]);
    await flush(5);
    harness.hooks.render();

    const state = harness.hooks.snapshot();
    assert.equal(state.coordinator.requests.projection.selectedRange, '24h');
    assert.equal(state.coordinator.render.model.selectedRange, '24h');
    assert.equal(state.coordinator.render.model.data.events[0].event_id, 'timeline-current');
    assert.equal(projectionCalls[0].range, '1m');
    assert.equal(projectionCalls[1].range, '24h');
});

test('trend 5s uses live ticks when saved projection is empty', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [networkEvent('snapshot')], event_count: 1, summary: { reason: 'snapshot' } };
        },
        async getNetworkProjection() {
            return {
                state: 'CAPTURING',
                events: [],
                summary: { reason: 'projection', view: 'trend', range: '5s' },
            };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('bar');
    harness.hooks.setRange('5s');
    harness.hooks.setTrendLiveTicks([
        trendTick('tick-1', {
            connectionCount: 4,
            evidence_refs: ['local://cleanhouse/network/tick-1'],
            related_event_ids: ['tick-1'],
        }),
    ]);
    await harness.hooks.hydrate({ refresh: false, reason: 'trend-live-fallback' });
    harness.hooks.render();

    const state = harness.hooks.snapshot();
    assert.equal(state.coordinator.render.model.mode, 'bar');
    assert.equal(state.coordinator.render.model.selectedRange, '5s');
    assert.equal(state.coordinator.render.model.data.events.length, 1);
    assert.equal(state.coordinator.render.model.data.summary.live_ticks, true);
    assert.equal(state.messageText, '1 interpreted bucket in the last 5 seconds.');
});

test('Trend Graph and Chart share filtered versioned buckets and preserve gaps', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const tick = trendTick('tick-parity', {
        interpretation: {
            vulnerabilities: { value: 2, confidence: 0.8, rationale: ['Owner unknown.'], signals: ['unknown_external_owner'], evidence_refs: ['evidence:v'] },
            threats: { value: 3, confidence: 0.9, rationale: ['Suspicious evidence.'], signals: ['suspicious'], evidence_refs: ['evidence:t'] },
            strengths: { value: 1, confidence: 0.7, rationale: ['Encrypted service.'], signals: ['encrypted_service'], evidence_refs: ['evidence:s'] },
        },
        evidence_count: 3,
    });
    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [networkEvent('snapshot')], event_count: 1, summary: { reason: 'snapshot' } };
        },
        async getNetworkProjection() {
            return { state: 'CAPTURING', events: [tick], summary: { reason: 'projection', view: 'trend', range: '5s', rule_version: 'network-trend-rationalization.v1' } };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('bar');
    harness.hooks.setRange('5s');
    await harness.hooks.hydrate({ refresh: false, reason: 'trend-parity' });
    harness.hooks.setTrendControls({ display: 'graph', sort: 'value_desc', series: ['threats', 'strengths'] });
    harness.hooks.render();
    const graph = harness.hooks.snapshot().resultsHtml;
    const dataset = harness.hooks.trendDataset([tick]);

    assert.equal(dataset.series.join('|'), 'threats|strengths');
    assert.equal(dataset.totals.threats, 3);
    assert.equal(dataset.totals.strengths, 1);
    assert.equal(dataset.observed, 1);
    assert.ok(dataset.gaps > 0);
    assert.match(graph, /data-trend-mode="graph"/);
    assert.match(graph, /network-trend-bucket is-gap/);
    assert.doesNotMatch(graph, /trend-vulnerabilities/);

    harness.hooks.setTrendControls({ display: 'chart' });
    harness.hooks.render();
    const chart = harness.hooks.snapshot().resultsHtml;
    assert.match(chart, /data-trend-mode="chart"/);
    assert.match(chart, /<th scope="col">Threats<\/th>/);
    assert.match(chart, /<th scope="col">Strengths<\/th>/);
    assert.doesNotMatch(chart, /<th scope="col">Vulnerabilities<\/th>/);
    assert.match(chart, />Gap<\/td>/);
    assert.match(chart, /network-trend-rationalization\.v1/);
});

test('restart warmup with empty snapshot does not render misleading no-data table copy', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setApi({
        async getNetwork() {
            return {
                state: 'WARMING',
                events: [],
                event_count: 0,
                summary: { reason: 'snapshot' },
                tags: { status: 'QUIET', state: 'DEGRADED', reasons: ['Restarting'], explanation: 'Waiting for network capture after restart.' },
            };
        },
        async getNetworkProjection() {
            return { state: 'CAPTURING', events: [], summary: { reason: 'projection' } };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('table');
    await harness.hooks.hydrate({ refresh: false, reason: 'restart-warmup' });
    harness.hooks.render();

    const state = harness.hooks.snapshot();
    assert.equal(state.areaStatus, 'Reconnecting to runtime');
    assert.match(state.resultsHtml, /network-table-wrap/);
    assert.match(state.resultsHtml, /<tbody><\/tbody>/);
    assert.doesNotMatch(state.resultsHtml, />NO_DATA</);
});

test('manual refresh says refreshing instead of no-data while snapshot is pending', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const snapshot = deferred();

    harness.setApi({
        async getNetwork() {
            return snapshot.promise;
        },
        async getNetworkProjection() {
            return { state: 'CAPTURING', events: [], summary: { reason: 'projection' } };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('table');
    const hydratePromise = harness.hooks.hydrate({ refresh: true, reason: 'manual-refresh' });
    await flush();

    let state = harness.hooks.snapshot();
    assert.equal(state.messageText, '0 active connections.');
    assert.doesNotMatch(state.resultsHtml, />NO_DATA</);

    snapshot.resolve({ state: 'NO_DATA', events: [], event_count: 0, summary: { reason: 'no_data' }, tags: { status: 'QUIET', state: 'HEALTHY', reasons: [] } });
    await hydratePromise;
    state = harness.hooks.snapshot();
    assert.equal(state.messageText, '0 active connections.');
    assert.match(state.resultsHtml, /network-table-wrap/);
    assert.doesNotMatch(state.resultsHtml, /No network packets observed yet/);
});

test('each network tab owns loading and empty copy', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const projections = {
        findings: deferred(),
        trend: deferred(),
        distribution: deferred(),
        timeline: deferred(),
    };

    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [], event_count: 0, summary: { reason: 'snapshot' }, tags: { status: 'QUIET', state: 'HEALTHY', reasons: [] } };
        },
        async getNetworkProjection(view) {
            return projections[view].promise;
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    const cases = [
        ['findings', 'Loading grouped network findings.', 'No grouped findings.'],
        ['bar', 'Loading saved and live network trend.', 'No trend points for the selected range.'],
        ['pie', 'Loading app distribution for the selected snapshot.', 'No packet-supported app activity in the selected snapshot.'],
        ['timeline', 'Loading network event history.', 'No notable events or continuity gaps in the selected window.'],
    ];

    for (const [mode, loadingCopy, emptyCopy] of cases) {
        const projectionView = mode === 'bar' ? 'trend' : (mode === 'pie' ? 'distribution' : mode);
        harness.hooks.setView(mode);
        const hydratePromise = harness.hooks.hydrate({ refresh: false, reason: `${mode}-truth` });
        await flush();
        let state = harness.hooks.snapshot();
        assert.equal(state.messageText, loadingCopy);
        assert.match(state.resultsHtml, new RegExp(loadingCopy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
        projections[projectionView].resolve({ state: 'NO_DATA', events: [], summary: { reason: 'no_data' }, tags: { status: 'QUIET', state: 'HEALTHY', reasons: [] } });
        await hydratePromise;
        state = harness.hooks.snapshot();
        assert.equal(state.messageText, emptyCopy);
        assert.match(state.resultsHtml, new RegExp(emptyCopy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
        assert.doesNotMatch(state.resultsHtml, />NO_DATA</);
    }
});

test('timeline settled empty does not borrow snapshot or last-good events', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());

    harness.setApi({
        async getNetwork() {
            return { state: 'CAPTURING', events: [networkEvent('snapshot-row')], event_count: 1, summary: { reason: 'snapshot' } };
        },
        async getNetworkProjection() {
            return { state: 'NO_DATA', events: [], summary: { reason: 'no_data', timeline_source: 'saved' }, tags: { status: 'QUIET', state: 'HEALTHY', reasons: [] } };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('timeline');
    await harness.hooks.hydrate({ refresh: false, reason: 'timeline-empty' });
    const state = harness.hooks.snapshot();
    assert.equal(state.coordinator.render.model.data.events.length, 0);
    assert.equal(state.messageText, 'No notable events or continuity gaps in the selected window.');
    assert.doesNotMatch(state.resultsHtml, /snapshot-row/);
});

test('degraded capture keeps retained findings visible and marks the header offline', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setApi({
        async getNetwork() {
            return {
                state: 'ERROR',
                events: [],
                summary: { reason: 'engine_unavailable', capture_reason: 'engine_unavailable' },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
            };
        },
        async getNetworkProjection() {
            return {
                state: 'ERROR',
                events: [networkEvent('retained-finding')],
                summary: { view: 'findings', reason: 'engine_unavailable', capture_reason: 'engine_unavailable' },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
                collector: { state: 'degraded', reason_code: 'capture_engine_unavailable' },
            };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('findings');
    await harness.hooks.hydrate({ refresh: false, reason: 'degraded-retained-findings' });
    const state = harness.hooks.snapshot();
    assert.equal(state.currentNetworkProjectionData.state, 'ERROR');
    assert.match(state.resultsHtml, /retained-finding/);
    assert.equal(state.currentNetworkTags.status, 'OFFLINE');
    assert.equal(state.currentNetworkTags.state, 'DEGRADED');
});

test('a healthy capture status clears stale capture degradation without erasing finding reasons', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());

    harness.hooks.submitHeader('live-status', {
        state: 'ERROR',
        events: [],
        summary: { reason: 'capture_backlog', capture_reason: 'capture_backlog' },
        tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
    }, { captureStatus: true });
    harness.hooks.submitHeader('snapshot', {
        state: 'CAPTURING',
        events: [networkEvent('unknown-app', { app_name: 'Unknown app', suspicious: true })],
        summary: { reason: 'events_observed', capture_reason: 'events_observed' },
        tags: { status: 'OBSERVING', state: 'DEGRADED', reasons: ['Unknown app active'] },
    }, { captureStatus: true });

    const reasons = harness.hooks.snapshot().currentNetworkHeaderData.latchedReasons.map(item => item.reason);
    assert.equal(reasons.join('|'), 'Unknown app active');
});

test('degraded capture empty projection renders the exact unavailable cause', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setApi({
        async getNetwork() {
            return {
                state: 'ERROR',
                events: [],
                summary: { reason: 'engine_unavailable', capture_reason: 'engine_unavailable' },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
            };
        },
        async getNetworkProjection() {
            return {
                state: 'ERROR',
                events: [],
                summary: { view: 'trend', reason: 'engine_unavailable', capture_reason: 'engine_unavailable' },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
            };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('bar');
    await harness.hooks.hydrate({ refresh: false, reason: 'degraded-empty-trend' });
    const state = harness.hooks.snapshot();
    assert.match(state.resultsHtml, /Capture engine unavailable\./);
    assert.equal(state.areaStatus, 'Capture engine unavailable.');
});

test('degraded Distribution keeps open applications separate from observed activity', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setApi({
        async getNetwork() {
            return {
                state: 'ERROR',
                events: [],
                summary: { reason: 'engine_unavailable', capture_reason: 'engine_unavailable' },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
            };
        },
        async getNetworkProjection() {
            return {
                state: 'ERROR',
                events: [],
                summary: {
                    view: 'distribution',
                    reason: 'engine_unavailable',
                    capture_reason: 'engine_unavailable',
                    open_applications_source: 'applications_running_gui_inventory',
                    open_applications: [{ name: 'Safari', observed_network_events: 0 }],
                },
                tags: { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'] },
            };
        },
        getNetworkLiveUrl() {
            return 'http://127.0.0.1:3333/cleanhouse/network/live';
        },
    });

    harness.hooks.setView('pie');
    await harness.hooks.hydrate({ refresh: false, reason: 'degraded-distribution' });
    const state = harness.hooks.snapshot();
    assert.equal(state.messageText, '0 active apps.');
    assert.match(state.resultsHtml, /No packet-supported network activity/);
    assert.match(state.resultsHtml, /Open applications/);
    assert.match(state.resultsHtml, /Safari/);
    assert.match(state.resultsHtml, /0 observed/);
    assert.equal(state.areaStatus, 'Capture engine unavailable.');
});
