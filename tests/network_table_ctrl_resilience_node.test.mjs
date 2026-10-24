import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { setTimeout as delay } from 'node:timers/promises';

const API_CLIENT_PATH = new URL('../frontend/js/api-client.js', import.meta.url);
const INVESTIGATIONS_PATH = new URL('../frontend/js/investigations.js', import.meta.url);
const API_CLIENT_SOURCE = fs.readFileSync(API_CLIENT_PATH, 'utf8');
const INVESTIGATIONS_SOURCE = fs.readFileSync(INVESTIGATIONS_PATH, 'utf8');

function camelizeDataKey(name = '') {
    return String(name || '').replace(/^data-/, '').replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

class MockClassList {
    constructor(owner) {
        this.owner = owner;
        this.values = new Set();
    }

    add(...values) {
        values.forEach(value => {
            if (value) this.values.add(String(value));
        });
        this.owner.className = Array.from(this.values).join(' ');
    }

    remove(...values) {
        values.forEach(value => this.values.delete(String(value)));
        this.owner.className = Array.from(this.values).join(' ');
    }

    toggle(value, force) {
        const normalized = String(value);
        if (force === undefined) {
            if (this.values.has(normalized)) this.values.delete(normalized);
            else this.values.add(normalized);
        } else if (force) {
            this.values.add(normalized);
        } else {
            this.values.delete(normalized);
        }
        this.owner.className = Array.from(this.values).join(' ');
        return this.values.has(normalized);
    }

    contains(value) {
        return this.values.has(String(value));
    }
}

class MockNode {
    constructor(tagName = 'div') {
        this.tagName = String(tagName || 'div').toUpperCase();
        this.children = [];
        this.parentElement = null;
        this.listeners = new Map();
        this.dataset = {};
        this.attributes = new Map();
        this.classList = new MockClassList(this);
        this.className = '';
        this.hidden = false;
        this.innerHTML = '';
        this.textContent = '';
        this.scrollLeft = 0;
        this.scrollTop = 0;
        this.open = false;
        this.id = '';
        this.value = '';
        this.style = {
            values: new Map(),
            setProperty: (name, value) => this.style.values.set(String(name), String(value)),
        };
        this.isFragment = false;
        this.replaceChildrenCount = 0;
        this.lastReplaceChildrenSize = 0;
    }

    get firstElementChild() {
        return this.children[0] || null;
    }

    get lastElementChild() {
        return this.children[this.children.length - 1] || null;
    }

    appendChild(child) {
        const nodes = child?.isFragment ? child.children : [child];
        nodes.forEach(node => {
            if (!node) return;
            node.parentElement = this;
            this.children.push(node);
        });
        return child;
    }

    replaceChildren(...items) {
        this.children = [];
        this.replaceChildrenCount += 1;
        items.forEach(item => {
            const nodes = item?.isFragment ? item.children : [item];
            nodes.forEach(node => {
                if (!node) return;
                node.parentElement = this;
                this.children.push(node);
            });
        });
        this.lastReplaceChildrenSize = this.children.length;
    }

    removeChild(child) {
        this.children = this.children.filter(node => node !== child);
        if (child) child.parentElement = null;
        return child;
    }

    insertBefore(child, before) {
        if (!before) {
            return this.appendChild(child);
        }
        const index = this.children.indexOf(before);
        if (index === -1) return this.appendChild(child);
        child.parentElement = this;
        this.children.splice(index, 0, child);
        return child;
    }

    insertAdjacentElement(position, element) {
        if (position === 'afterbegin') {
            return this.insertBefore(element, this.children[0] || null);
        }
        if (position === 'afterend' && this.parentElement) {
            const siblings = this.parentElement.children;
            const index = siblings.indexOf(this);
            element.parentElement = this.parentElement;
            siblings.splice(index + 1, 0, element);
            return element;
        }
        return this.appendChild(element);
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
            stopPropagation() {},
            stopImmediatePropagation() {},
            ...event,
        }));
    }

    setAttribute(name, value) {
        const normalized = String(name);
        const text = String(value);
        this.attributes.set(normalized, text);
        if (normalized === 'id') this.id = text;
        if (normalized === 'class') {
            this.className = text;
            this.classList = new MockClassList(this);
            text.split(/\s+/).filter(Boolean).forEach(token => this.classList.add(token));
        }
        if (normalized.startsWith('data-')) {
            this.dataset[camelizeDataKey(normalized)] = text;
        }
    }

    getAttribute(name) {
        return this.attributes.get(String(name)) || '';
    }

    closest(selector) {
        let current = this;
        while (current) {
            if (matchesSelector(current, selector)) return current;
            current = current.parentElement;
        }
        return null;
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
        const found = [];
        const walk = node => {
            node.children.forEach(child => {
                if (matchesSelector(child, selector)) found.push(child);
                walk(child);
            });
        };
        walk(this);
        return found;
    }

    contains(node) {
        let current = node;
        while (current) {
            if (current === this) return true;
            current = current.parentElement;
        }
        return false;
    }

    scrollIntoView() {}

    focus() {}
}

class MockFragment extends MockNode {
    constructor() {
        super('#fragment');
        this.isFragment = true;
    }
}

function matchesSelector(node, selector) {
    const normalized = String(selector || '').trim();
    if (!normalized) return false;
    if (normalized.startsWith('#')) return node.id === normalized.slice(1);
    if (normalized === 'tbody') return node.tagName === 'TBODY';
    if (normalized === '.network-table') return node.classList.contains('network-table');
    if (normalized === '.network-table-wrap') return node.classList.contains('network-table-wrap');
    if (normalized === '.network-table tbody') return node.tagName === 'TBODY' && node.closest('.network-table');
    if (normalized === 'tr.network-row-evidence') {
        return node.tagName === 'TR' && node.classList.contains('network-row-evidence');
    }
    const rowMatch = normalized.match(/^tr\.network-row-evidence\[data-evidence-entity-id="(.+)"\]$/);
    if (rowMatch) {
        return node.tagName === 'TR' &&
            node.classList.contains('network-row-evidence') &&
            String(node.dataset.evidenceEntityId || '') === rowMatch[1];
    }
    return false;
}

function networkEvent(id, extra = {}) {
    const digitMatch = String(id || '').match(/(\d+)$/);
    const numericId = digitMatch
        ? Number(digitMatch[1])
        : Array.from(String(id || '')).reduce((sum, char) => sum + char.charCodeAt(0), 0);
    const sourcePort = 50000 + (numericId % 10000);
    const destinationHost = `203.0.113.${(numericId % 240) + 1}`;
    return {
        event_id: id,
        timestamp: extra.timestamp || '2026-07-09T12:00:00Z',
        process: extra.process || 'Safari',
        source_display: extra.source_display || `127.0.0.1:${sourcePort}`,
        destination_display: extra.destination_display || `${destinationHost}:443`,
        protocol: extra.protocol || 'TCP',
        dst_ip: extra.dst_ip || destinationHost,
        dst_port: extra.dst_port || '443',
        summary: extra.summary || `Event ${id}`,
        reason: extra.reason || '',
        meaning: extra.meaning || '',
        ...extra,
    };
}

function createHarness() {
    const ids = new Map();
    const documentListeners = new Map();
    const windowListeners = new Map();
    const storage = new Map();
    let timerId = 0;
    const timers = new Map();
    const liveTimeouts = new Set();

    const body = new MockNode('body');
    const location = {
        protocol: 'http:',
        origin: 'http://127.0.0.1:3333',
        href: 'http://127.0.0.1:3333/network',
        pathname: '/network',
        search: '',
    };

    [
        'network-results',
        'network-message',
        'network-area-status',
        'network-toolbar-context',
        'network',
        'action-sidebar',
        'action-sidebar-body',
        'action-sidebar-toggle',
        'action-sidebar-shell',
        'network-status-tag',
        'network-state-tag',
        'network-reason-tags',
        'network-action-summary',
        'network-engine-panel',
        'scan-network-btn',
        'notification-center',
        'notification-center-menu',
        'notification-center-button',
        'notification-center-badge',
    ].forEach(id => {
        const element = new MockNode('div');
        element.id = id;
        ids.set(id, element);
    });

    ids.get('network').hidden = false;
    ids.get('action-sidebar').focus = () => {};

    const tableDom = {
        wrap: null,
        table: null,
        thead: null,
        tbody: null,
        resizers: [],
        mount(events = []) {
            const wrap = new MockNode('div');
            wrap.classList.add('network-table-wrap');
            const table = new MockNode('table');
            table.classList.add('network-table');
            const thead = new MockNode('thead');
            const headerRow = new MockNode('tr');
            const resizers = [];
            for (let index = 0; index < 7; index += 1) {
                const header = new MockNode('th');
                const resizer = new MockNode('button');
                resizer.classList.add('network-column-resizer');
                header.appendChild(resizer);
                headerRow.appendChild(header);
                resizers.push(resizer);
            }
            thead.appendChild(headerRow);
            const tbody = new MockNode('tbody');
            events.forEach(event => tbody.appendChild(this.createRow(event)));
            table.appendChild(thead);
            table.appendChild(tbody);
            wrap.appendChild(table);
            this.wrap = wrap;
            this.table = table;
            this.thead = thead;
            this.tbody = tbody;
            this.resizers = resizers;
            ids.get('network-results').querySelector = selector => {
                if (selector === '.network-table-wrap') return this.wrap;
                if (selector === '.network-table') return this.table;
                if (selector === '.network-table thead' || selector === 'thead') return this.thead;
                if (selector === '.network-table tbody') return this.tbody;
                return null;
            };
        },
        unmount() {
            this.wrap = null;
            this.table = null;
            this.thead = null;
            this.tbody = null;
            this.resizers = [];
        },
        createRow(event, reason = '') {
            const row = new MockNode('tr');
            row.classList.add('network-row-evidence');
            if (reason) row.classList.add('network-row-affected');
            if (event?.__networkPinnedStale) {
                row.classList.add('network-row-pinned');
                row.classList.add('network-row-pinned-stale');
            }
            row.setAttribute('data-evidence-surface', 'network');
            row.setAttribute('data-evidence-entity-id', String(event.event_id || event.id || ''));
            row.setAttribute('data-evidence-ref', String(event.raw_evidence_ref || ''));
            row.setAttribute('data-evidence-source-view', 'table');
            row.setAttribute('tabindex', '0');
            row.setAttribute('role', 'button');
            row.innerHTML = String(event.summary || event.event_id || '');
            return row;
        },
        rowIds() {
            return this.tbody ? this.tbody.children.map(row => row.dataset.evidenceEntityId || '') : [];
        },
        rows() {
            return this.tbody ? this.tbody.children.slice() : [];
        },
        resetCounts() {
            if (this.tbody) {
                this.tbody.replaceChildrenCount = 0;
                this.tbody.lastReplaceChildrenSize = this.tbody.children.length;
            }
        },
        mutationCount() {
            return this.tbody ? this.tbody.replaceChildrenCount : 0;
        },
    };

    const document = {
        body,
        hidden: false,
        readyState: 'loading',
        getElementById(id) {
            if (!ids.has(id)) {
                const element = new MockNode('div');
                element.id = id;
                ids.set(id, element);
            }
            return ids.get(id);
        },
        createElement(tag) {
            return new MockNode(tag);
        },
        createDocumentFragment() {
            return new MockFragment();
        },
        addEventListener(type, handler) {
            if (!documentListeners.has(type)) documentListeners.set(type, []);
            documentListeners.get(type).push(handler);
        },
        querySelector(selector) {
            if (selector === '.network-table') return tableDom.table;
            if (selector === '.network-table-wrap') return tableDom.wrap;
            if (selector === '.network-table tbody') return tableDom.tbody;
            return null;
        },
        querySelectorAll() {
            return [];
        },
    };

    const windowObject = {
        document,
        location,
        history: {
            replaceState(_state, _title, value) {
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
            const id = ++timerId;
            const handle = setTimeout(() => {
                timers.delete(id);
                liveTimeouts.delete(id);
                fn();
            }, ms);
            timers.set(id, handle);
            liveTimeouts.add(id);
            return id;
        },
        clearTimeout(id) {
            const handle = timers.get(id);
            if (handle) {
                clearTimeout(handle);
                timers.delete(id);
                liveTimeouts.delete(id);
            }
        },
        setInterval(fn, ms = 0) {
            const id = ++timerId;
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
            const handlers = windowListeners.get(type) || [];
            windowListeners.set(type, handlers.filter(item => item !== handler));
        },
        fetch: async () => ({ json: async () => ({ status: 'ok', context: {}, actions: [] }) }),
        EventSource: class {
            close() {}
            addEventListener() {}
        },
        console,
        URL,
        URLSearchParams,
        AbortController,
        performance: { now: () => Date.now() },
        innerWidth: 1440,
        innerHeight: 900,
        navigator: { userAgent: 'node-test' },
        CSS: { escape: value => String(value) },
        __TABLE_TEST_DOM: tableDom,
        __TABLE_TEST_STATE: {
            renderDisplayCalls: 0,
            renderHeaderCalls: 0,
            timelineRefreshCalls: 0,
            tableFlushCalls: 0,
            sidebarRenderCalls: 0,
            resumeHydrationCalls: 0,
            insightRequestCalls: 0,
            getNetworkCalls: 0,
            getNetworkProjectionCalls: 0,
            technicalDetailsEventCounts: [],
            resolveEvidenceEventCalls: 0,
            buildSubjectCalls: 0,
            buildRouteTargetCalls: 0,
            ctrlResolvedRenderMs: 0,
            ctrlResolvedRenderSamples: [],
            actionBodyWriteCount: 0,
            actionBodyHtmlSizes: [],
            preDeferredResolvedWrites: 0,
            deferredDetailCommits: 0,
            firstResolvedBodyHtmlSize: 0,
        },
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
        Element: MockNode,
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
    context.Element = MockNode;
    vm.runInContext(API_CLIENT_SOURCE, context, { filename: API_CLIENT_PATH.pathname });
    vm.runInContext(INVESTIGATIONS_SOURCE, context, { filename: INVESTIGATIONS_PATH.pathname });
    vm.runInContext(`
        startNetworkLiveUpdates = () => {};
        stopNetworkLiveUpdates = () => {};
        bindNetworkFindingsWindow = () => {};
        bindNetworkPieInteractions = () => {};
        bindNetworkEvidenceElements = () => {};
        bindNetworkFloatingTooltips = () => {};
        enableNetworkColumnResize = () => {};
        applyNetworkCtrlRouteTarget = () => {};
        const __actionSidebarBody = byId('action-sidebar-body');
        const __networkResults = byId('network-results');
        Object.defineProperty(__networkResults, 'innerHTML', {
            configurable: true,
            get() {
                return this.__innerHTML || '';
            },
            set(value) {
                const text = String(value || '');
                this.__innerHTML = text;
                if (text.includes('network-table-wrap')) {
                    const visible = networkTableVisibleRows(Array.isArray(currentNetworkData?.events) ? currentNetworkData.events : [], {
                        filterReason: '',
                        pinnedEntityId: networkTablePinnedEntityId,
                        limit: NETWORK_TABLE_DOM_ROW_LIMIT,
                    });
                    window.__TABLE_TEST_DOM.mount(visible);
                    const pinnedRow = window.__TABLE_TEST_DOM.rows().find(row => row.dataset.evidenceEntityId === String(networkTablePinnedEntityId || ''));
                    if (pinnedRow) {
                        pinnedRow.classList.add('network-row-pinned');
                        if (networkTablePinnedRowSnapshot?.__networkPinnedStale) {
                            pinnedRow.classList.add('network-row-pinned-stale');
                        }
                    }
                    return;
                }
                window.__TABLE_TEST_DOM.unmount();
            },
        });
        Object.defineProperty(__actionSidebarBody, 'innerHTML', {
            configurable: true,
            get() {
                return this.__innerHTML || '';
            },
            set(value) {
                const text = String(value || '');
                this.__innerHTML = text;
                window.__TABLE_TEST_STATE.actionBodyWriteCount += 1;
                window.__TABLE_TEST_STATE.actionBodyHtmlSizes.push(text.length);
                if (evidenceCommandContext && !evidenceCommandLoading && !actionSidebarDeferredDetailsReady) {
                    window.__TABLE_TEST_STATE.preDeferredResolvedWrites += 1;
                    if (!window.__TABLE_TEST_STATE.firstResolvedBodyHtmlSize) {
                        window.__TABLE_TEST_STATE.firstResolvedBodyHtmlSize = text.length;
                    }
                }
                if (evidenceCommandContext && !evidenceCommandLoading && actionSidebarDeferredDetailsReady) {
                    window.__TABLE_TEST_STATE.deferredDetailCommits += 1;
                }
            },
        });
        const __originalNetworkTechnicalDetailsHtml = networkTechnicalDetailsHtml;
        networkTechnicalDetailsHtml = (data, events, open = false) => {
            window.__TABLE_TEST_STATE.technicalDetailsEventCounts.push(Array.isArray(events) ? events.length : -1);
            return __originalNetworkTechnicalDetailsHtml(data, events, open);
        };
        const __originalResolveNetworkEvidenceEvent = resolveNetworkEvidenceEvent;
        resolveNetworkEvidenceEvent = (context = {}) => {
            window.__TABLE_TEST_STATE.resolveEvidenceEventCalls += 1;
            const eventCount = Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events.length : 0;
            let burn = 0;
            const iterations = Math.min(eventCount, 600) * 12000;
            for (let index = 0; index < iterations; index += 1) {
                burn += index % 7;
            }
            if (burn < 0) window.__TABLE_TEST_STATE.syntheticBurn = burn;
            return __originalResolveNetworkEvidenceEvent(context);
        };
        const __originalBuildNetworkCtrlSubject = buildNetworkCtrlSubject;
        buildNetworkCtrlSubject = (...args) => {
            window.__TABLE_TEST_STATE.buildSubjectCalls += 1;
            return __originalBuildNetworkCtrlSubject(...args);
        };
        const __originalBuildNetworkCtrlRouteTarget = buildNetworkCtrlRouteTarget;
        buildNetworkCtrlRouteTarget = (...args) => {
            window.__TABLE_TEST_STATE.buildRouteTargetCalls += 1;
            return __originalBuildNetworkCtrlRouteTarget(...args);
        };
        const __originalRenderNetworkDisplay = renderNetworkDisplay;
        renderNetworkDisplay = (...args) => {
            window.__TABLE_TEST_STATE.renderDisplayCalls += 1;
            return __originalRenderNetworkDisplay(...args);
        };
        const __originalRenderNetworkHeader = renderNetworkHeader;
        renderNetworkHeader = (...args) => {
            window.__TABLE_TEST_STATE.renderHeaderCalls += 1;
            return __originalRenderNetworkHeader(...args);
        };
        const __originalRefreshTimeline = refreshNetworkTimelineDisplayIfVisible;
        refreshNetworkTimelineDisplayIfVisible = (...args) => {
            window.__TABLE_TEST_STATE.timelineRefreshCalls += 1;
            return __originalRefreshTimeline(...args);
        };
        const __originalFlushTable = flushNetworkTableRender;
        flushNetworkTableRender = (options = {}) => {
            window.__TABLE_TEST_STATE.tableFlushCalls += 1;
            return __originalFlushTable(options);
        };
        const __originalRenderEvidenceActionSidebar = renderEvidenceActionSidebar;
        renderEvidenceActionSidebar = (...args) => {
            window.__TABLE_TEST_STATE.sidebarRenderCalls += 1;
            const start = performance.now();
            const result = __originalRenderEvidenceActionSidebar(...args);
            const elapsed = performance.now() - start;
            if (evidenceCommandContext && !evidenceCommandLoading) {
                window.__TABLE_TEST_STATE.ctrlResolvedRenderMs = Math.max(window.__TABLE_TEST_STATE.ctrlResolvedRenderMs, elapsed);
                window.__TABLE_TEST_STATE.ctrlResolvedRenderSamples.push(elapsed);
            }
            return result;
        };
        const __originalResumeNetworkViewHydration = resumeNetworkViewHydration;
        resumeNetworkViewHydration = (...args) => {
            window.__TABLE_TEST_STATE.resumeHydrationCalls += 1;
            return __originalResumeNetworkViewHydration(...args);
        };
        createNetworkTableRowElement = (event, reason = '') => {
            const row = window.__TABLE_TEST_DOM.createRow(event, reason);
            if (networkTablePinnedEntityId && networkEvidenceEntityId(event) === networkTablePinnedEntityId) {
                row.classList.add('network-row-pinned');
                if (event?.__networkPinnedStale) {
                    row.classList.add('network-row-pinned-stale');
                }
            }
            return row;
        };
        window.__TABLE_CTRL_TEST_HOOKS__ = {
            setView(mode) {
                networkViewMode = validNetworkViewMode(mode) || 'table';
            },
            renderDisplay() {
                return renderNetworkDisplay();
            },
            domRefs() {
                return {
                    wrap: window.__TABLE_TEST_DOM.wrap,
                    table: window.__TABLE_TEST_DOM.table,
                    thead: window.__TABLE_TEST_DOM.thead,
                    tbody: window.__TABLE_TEST_DOM.tbody,
                    resizers: window.__TABLE_TEST_DOM.resizers.slice(),
                };
            },
            setApplications(items = []) {
                applications = Array.isArray(items) ? items.map(item => ({ ...item })) : [];
                applicationsLoaded = true;
            },
            setPinned(entityId = '') {
                setPinnedNetworkTableSelection(entityId);
            },
            primeTable(events = []) {
                const rawEvents = Array.isArray(events) ? events.map(event => ({ ...event })) : [];
                currentNetworkTableData = networkTableDataFromEvents({
                    state: 'CAPTURING',
                    summary: { reason: 'events_observed', counts: { connections: rawEvents.length, os_active_connections: rawEvents.length } },
                }, rawEvents);
                currentNetworkData = currentNetworkTableData;
                currentNetworkProjectionData = null;
                networkTableUiBuffer = [];
                const visible = networkTableVisibleRows(currentNetworkTableData.events, {
                    pinnedEntityId: networkTablePinnedEntityId,
                    limit: NETWORK_TABLE_DOM_ROW_LIMIT,
                });
                window.__TABLE_TEST_DOM.mount(visible);
                networkTableRenderState = {
                    rowKeys: visible.map(event => networkEvidenceEntityId(event)),
                    lastReason: '',
                    lastFilterReason: '',
                };
                window.__TABLE_TEST_DOM.resetCounts();
            },
            setTableData(events = [], state = 'CAPTURING', reason = 'events_observed', osActiveCount = null) {
                const rawEvents = Array.isArray(events) ? events.map(event => ({ ...event })) : [];
                const authoritativeCount = osActiveCount === null ? rawEvents.length : Number(osActiveCount);
                currentNetworkTableData = networkTableDataFromEvents({
                    state,
                    summary: { reason, counts: { connections: rawEvents.length, os_active_connections: authoritativeCount } },
                }, rawEvents);
                currentNetworkHeaderData.osActiveConnectionCount = authoritativeCount;
                currentNetworkData = currentNetworkTableData;
                currentNetworkProjectionData = null;
            },
            reconcileSnapshot(events = [], osActiveCount = null) {
                const rawEvents = Array.isArray(events) ? events.map(event => ({ ...event })) : [];
                const authoritativeCount = osActiveCount === null ? rawEvents.length : Number(osActiveCount);
                currentNetworkTableData = reconcileNetworkInventoryFromSnapshot(currentNetworkTableData, {
                    state: 'CAPTURING',
                    summary: { reason: 'snapshot', counts: { os_active_connections: authoritativeCount } },
                }, rawEvents);
                currentNetworkData = currentNetworkTableData;
                return currentNetworkTableData;
            },
            setPagePhase(phase = 'ready', reason = '') {
                setNetworkPagePhase(phase, reason);
            },
            setTableFilter(reason = '') {
                networkActionFilterReason = String(reason || '');
            },
            cycleSort(key = '') {
                cycleNetworkTableSort(key);
            },
            visibleSortValues(key = '') {
                return networkTableVisibleRows(currentNetworkTableData?.events || [], {
                    limit: NETWORK_TABLE_DOM_ROW_LIMIT,
                }).map(event => networkTableSortValue(event, key));
            },
            bindRows() {
                bindNetworkEvidenceRows();
            },
            clickRow(index = 0) {
                const row = window.__TABLE_TEST_DOM.rows()[index];
                if (row) row.dispatch('click');
            },
            clickBlankNetwork() {
                const target = byId('network');
                const event = {
                    target,
                    preventDefault() {},
                    stopPropagation() {},
                    stopImmediatePropagation() {},
                };
                handleNetworkTablePinnedOutsideClick(event);
                handleActionSidebarOutsideClick(event);
            },
            clickTableChrome() {
                const target = window.__TABLE_TEST_DOM.table;
                if (!target) return;
                handleNetworkTablePinnedOutsideClick({ target });
                handleActionSidebarOutsideClick({ target });
            },
            appendLive(event) {
                appendNetworkLiveEvent({ ...event });
            },
            dispatchVisibility(hidden = true) {
                document.hidden = Boolean(hidden);
                if (document.hidden) {
                    networkDocumentHiddenAt = Date.now();
                    suspendNetworkRenderWork();
                    return;
                }
                scheduleNetworkForegroundRendering('resume');
            },
            dispatchWindowBlur() {
                networkWindowBackgrounded = true;
            },
            dispatchWindowFocus() {
                networkWindowBackgrounded = false;
                scheduleNetworkForegroundRendering('focus');
            },
            dispatchPageHide(persisted = true) {
                networkWindowBackgrounded = true;
                networkDocumentHiddenAt = Date.now();
                suspendNetworkRenderWork();
            },
            dispatchPageShow(persisted = true) {
                networkWindowBackgrounded = false;
                if (persisted) scheduleNetworkForegroundRendering('pageshow');
            },
            setActionOpen(open) {
                setActionSidebarOpen(open);
            },
            openEvidence(descriptor = {}) {
                openEvidenceActions(descriptor);
            },
            requestInsight(action = { required_role: 'Insight' }) {
                requestEvidenceInsight(action);
            },
            executeAction(action = {}, origin = '') {
                executeEvidenceAction(action, origin);
            },
            actionMenuHtml(context = {}, actions = []) {
                evidenceCommandContext = { ...context };
                evidenceCommandActions = Array.isArray(actions) ? actions.map(action => ({ ...action })) : [];
                evidenceCommandSnapshot = buildEvidenceCommandSnapshot(evidenceCommandContext);
                return evidenceSidebarSections(evidenceCommandContext, {}, evidenceCommandSnapshot);
            },
            flushTable(force = true) {
                return flushNetworkTableRender({ force });
            },
            flushHeader(force = true) {
                return flushNetworkHeaderRender({ force });
            },
            resetSpies() {
                window.__TABLE_TEST_STATE.renderDisplayCalls = 0;
                window.__TABLE_TEST_STATE.renderHeaderCalls = 0;
                window.__TABLE_TEST_STATE.timelineRefreshCalls = 0;
                window.__TABLE_TEST_STATE.tableFlushCalls = 0;
                window.__TABLE_TEST_STATE.sidebarRenderCalls = 0;
                window.__TABLE_TEST_STATE.resumeHydrationCalls = 0;
                window.__TABLE_TEST_STATE.insightRequestCalls = 0;
                window.__TABLE_TEST_STATE.getNetworkCalls = 0;
                window.__TABLE_TEST_STATE.getNetworkProjectionCalls = 0;
                window.__TABLE_TEST_STATE.technicalDetailsEventCounts = [];
                window.__TABLE_TEST_STATE.resolveEvidenceEventCalls = 0;
                window.__TABLE_TEST_STATE.buildSubjectCalls = 0;
                window.__TABLE_TEST_STATE.buildRouteTargetCalls = 0;
                window.__TABLE_TEST_STATE.ctrlResolvedRenderMs = 0;
                window.__TABLE_TEST_STATE.ctrlResolvedRenderSamples = [];
                window.__TABLE_TEST_STATE.actionBodyWriteCount = 0;
                window.__TABLE_TEST_STATE.actionBodyHtmlSizes = [];
                window.__TABLE_TEST_STATE.preDeferredResolvedWrites = 0;
                window.__TABLE_TEST_STATE.deferredDetailCommits = 0;
                window.__TABLE_TEST_STATE.firstResolvedBodyHtmlSize = 0;
                window.__TABLE_TEST_DOM.resetCounts();
            },
            snapshot() {
                return JSON.parse(JSON.stringify({
                    actionSidebarOpen,
                    actionSidebarDeferredDetailsReady,
                    networkHeaderRenderPending,
                    networkTableUiBufferLength: networkTableUiBuffer.length,
                    networkTableRenderState,
                    networkTablePinnedEntityId,
                    networkTablePinnedRowSnapshot,
                    networkTableSort,
                    networkRenderSuspended,
                    networkVisibilityPendingHydration,
                    networkDeferredRenderFlags,
                    tableFlushTimerActive: Boolean(networkTableFlushTimer),
                    headerFlushTimerActive: Boolean(networkHeaderRenderTimer),
                    currentNetworkTableData,
                    currentNetworkHeaderData,
                    networkMessage: byId('network-message')?.textContent || '',
                    evidenceCommandSelectionKey,
                    evidenceCommandStatus,
                    evidenceInsightLoading,
                    evidenceInsightError,
                    evidenceCommandSnapshot,
                    evidenceSnapshotFrozen: Boolean(
                        evidenceCommandSnapshot &&
                        Object.isFrozen(evidenceCommandSnapshot) &&
                        Object.isFrozen(evidenceCommandSnapshot.context) &&
                        Object.isFrozen(evidenceCommandSnapshot.actions)
                    ),
                    spyState: window.__TABLE_TEST_STATE,
                    dom: {
                        rowIds: window.__TABLE_TEST_DOM.rowIds(),
                        rowClasses: window.__TABLE_TEST_DOM.rows().map(row => row.className || ''),
                        mutationCount: window.__TABLE_TEST_DOM.mutationCount(),
                    },
                    visibleRowIds: networkTableVisibleRows(
                        Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events : [],
                        {
                            filterReason: '',
                            pinnedEntityId: networkTablePinnedEntityId,
                            limit: NETWORK_TABLE_DOM_ROW_LIMIT,
                        },
                    ).map(event => networkEvidenceEntityId(event)),
                }));
            },
        };
    `, context);
    context.window.__TABLE_TEST_DOCUMENT_LISTENERS__ = documentListeners;
    context.window.__TABLE_TEST_WINDOW_LISTENERS__ = windowListeners;
    function cleanup() {
        for (const handle of timers.values()) {
            clearTimeout(handle);
            clearInterval(handle);
        }
        timers.clear();
    }

    return {
        hooks: context.window.__TABLE_CTRL_TEST_HOOKS__,
        context,
        cleanup,
        setNetworkApi({ getNetwork = null, getNetworkProjection = null } = {}) {
            const existing = context.window.CleanHouseAPI || {};
            context.window.CleanHouseAPI = {
                ...existing,
                getNetwork: async options => {
                    context.window.__TABLE_TEST_STATE.getNetworkCalls += 1;
                    if (typeof getNetwork === 'function') return getNetwork(options);
                    return {
                        state: 'CAPTURING',
                        events: [networkEvent('snapshot-1')],
                        event_count: 1,
                        summary: { reason: 'snapshot', counts: { connections: 1 } },
                    };
                },
                getNetworkProjection: async (view, range, options) => {
                    context.window.__TABLE_TEST_STATE.getNetworkProjectionCalls += 1;
                    if (typeof getNetworkProjection === 'function') return getNetworkProjection(view, range, options);
                    return {
                        state: 'CAPTURING',
                        events: [],
                        summary: { reason: 'projection', view, range },
                    };
                },
                getNetworkLiveUrl: existing.getNetworkLiveUrl || (() => 'http://127.0.0.1:3333/live'),
            };
        },
        setEvidenceApi(handler, insightHandler = null, actionHandler = null) {
            const existing = context.window.CleanHouseAPI || {};
            context.window.CleanHouseAPI = {
                ...existing,
                getEvidenceActions: handler,
                requestEvidenceInsight: async payload => {
                    context.window.__TABLE_TEST_STATE.insightRequestCalls += 1;
                    if (typeof insightHandler === 'function') return insightHandler(payload);
                    return { status: 'ok', audit: { id: 'insight:test' }, insight: { plain_language_summary: 'test' } };
                },
                recordEvidenceAction: async payload => {
                    if (typeof actionHandler === 'function') return actionHandler(payload);
                    return { status: 'ok', audit: { id: 'action:test' } };
                },
            };
        },
    };
}

async function flush(ms = 0) {
    await delay(ms);
    await delay(0);
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

function actionLabels(html = '') {
    return Array.from(String(html || '').matchAll(/data-ctrl-more-action="([^"]+)"/g)).map(match => match[1]);
}

function disabledActionLabels(html = '') {
    return Array.from(String(html || '').matchAll(/<button[^>]*data-ctrl-more-action="([^"]+)"[^>]*\sdisabled\b[^>]*>/g)).map(match => match[1]);
}

function actionGroups(html = '') {
    return Array.from(String(html || '').matchAll(/class="action-sidebar-action-group-title">([^<]+)</g)).map(match => match[1]);
}

function allCapabilities() {
    return ['observe', 'allow', 'mark_read', 'mark_unread', 'copy', 'export', 'restrict', 'block', 'quarantine', 'terminate']
        .map(id => ({ id, label: id, enabled: true, required_role: 'operator' }));
}

test('ctrl action menu renders Monitoring Evidence Enforcement groups in order', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'network',
        source_view: 'table',
        source_entity_id: '203.0.113.10:443',
        subject_type: 'destination',
        destination: '203.0.113.10:443',
        evidence_key: 'network:203.0.113.10:443',
        summary: 'Known malicious endpoint finding',
        validation_state: 'threat',
        network_reasons: ['Known malicious endpoint'],
    }, allCapabilities());

    assert.deepEqual(actionGroups(html), ['Monitoring', 'Evidence', 'Enforcement']);
    assert.deepEqual(actionLabels(html).slice(0, 6), ['observe', 'allow', 'mark_read', 'mark_unread', 'copy', 'export']);
    assert.deepEqual(disabledActionLabels(html), ['quarantine', 'terminate']);
});

test('historical network event keeps terminate and non-policy allow disabled', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'network',
        source_view: 'timeline',
        source_entity_id: '',
        summary: 'Historical event marker',
        validation_state: 'low',
    }, allCapabilities());
    const labels = actionLabels(html);
    const disabled = disabledActionLabels(html);

    assert.ok(labels.includes('terminate'));
    assert.ok(labels.includes('allow'));
    assert.ok(disabled.includes('terminate'));
    assert.ok(disabled.includes('allow'));
    assert.ok(labels.includes('observe'));
    assert.ok(labels.includes('copy'));
    assert.ok(labels.includes('export'));
});

test('destination evidence enables block and disables allow quarantine terminate', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'network',
        source_view: 'table',
        source_entity_id: '203.0.113.10:443',
        subject_type: 'destination',
        destination: '203.0.113.10:443',
        summary: 'Destination name missing',
        network_reasons: ['Destination name missing'],
    }, allCapabilities());
    const labels = actionLabels(html);
    const disabled = disabledActionLabels(html);

    assert.ok(labels.includes('block'));
    assert.ok(labels.includes('restrict'));
    assert.ok(labels.includes('allow'));
    assert.ok(labels.includes('quarantine'));
    assert.ok(labels.includes('terminate'));
    assert.ok(!disabled.includes('block'));
    assert.ok(!disabled.includes('restrict'));
    assert.ok(disabled.includes('allow'));
    assert.ok(disabled.includes('quarantine'));
    assert.ok(disabled.includes('terminate'));
});

test('healthy or already allowed evidence keeps allow unavailable', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'network',
        source_view: 'table',
        source_entity_id: 'ChatGPT',
        subject_type: 'app_process',
        process: 'ChatGPT',
        process_state: 'active',
        validation_state: 'healthy',
        summary: 'ChatGPT network activity is healthy',
    }, allCapabilities());
    const labels = actionLabels(html);
    const disabled = disabledActionLabels(html);

    assert.ok(labels.includes('allow'));
    assert.ok(disabled.includes('allow'));
    assert.ok(labels.includes('observe'));
    assert.ok(!disabled.includes('observe'));
});

test('active app process evidence shows terminate and quarantine', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'network',
        source_view: 'table',
        source_entity_id: '4321',
        subject_type: 'app_process',
        process: 'ChatGPT',
        process_state: 'active',
        summary: 'ChatGPT PID 4321 active process',
    }, allCapabilities());
    const labels = actionLabels(html);
    const disabled = disabledActionLabels(html);

    assert.ok(labels.includes('terminate'));
    assert.ok(labels.includes('quarantine'));
    assert.ok(labels.includes('restrict'));
    assert.ok(!disabled.includes('terminate'));
    assert.ok(!disabled.includes('quarantine'));
    assert.ok(!disabled.includes('restrict'));
});

test('file or executable tied evidence shows quarantine', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const html = harness.hooks.actionMenuHtml({
        source_surface: 'files',
        source_view: 'table',
        source_entity_id: '/Applications/Sample.app',
        path: '/Applications/Sample.app',
        summary: 'Executable evidence',
    }, allCapabilities());
    const labels = actionLabels(html);
    const disabled = disabledActionLabels(html);

    assert.ok(labels.includes('quarantine'));
    assert.ok(labels.includes('terminate'));
    assert.ok(!disabled.includes('quarantine'));
    assert.ok(disabled.includes('terminate'));
});

test('row click opens ctrl without calling renderNetworkDisplay', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: 'row click',
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('row-1')]);
    harness.hooks.bindRows();
    harness.hooks.resetSpies();

    harness.hooks.clickRow(0);
    await flush();

    const state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.equal(state.spyState.renderDisplayCalls, 0);
    assert.equal(state.networkTablePinnedEntityId, state.dom.rowIds[0]);
    assert.match(state.dom.rowIds[0], /^connection:/);
});

test('Distribution ctrl keeps stable aggregate identity and refreshes changed evidence sets', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const calls = [];
    const insightPayloads = [];
    harness.setEvidenceApi(async params => {
        calls.push({ ...params });
        return {
            status: 'ok',
            context: {
                evidence_key: `network:${params.entityId}`,
                source_surface: 'network',
                source_view: 'distribution',
                source_entity_id: params.entityId,
                evidence_refs: [],
                assessment_refs: [],
                summary: 'Aggregate owner evidence.',
            },
            actions: [],
        };
    }, async payload => {
        insightPayloads.push(payload);
        return { status: 'ok', audit: { id: 'insight:distribution' }, insight: {} };
    });
    const base = {
        surface: 'network', entityId: 'network-owner:stable', sourceView: 'distribution',
        ref: '', owner: 'Safari', destination: '',
    };

    harness.hooks.openEvidence({ ...base, relatedIds: ['event:1'], assessmentRefs: ['assessment:1'] });
    await flush();
    harness.hooks.openEvidence({ ...base, relatedIds: ['event:2'], assessmentRefs: ['assessment:2'] });
    await flush();

    const state = harness.hooks.snapshot();
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[1], {
        surface: 'network', entityId: 'network-owner:stable', sourceView: 'distribution',
        ref: '', owner: 'Safari', destination: '',
    });
    assert.deepEqual(Array.from(state.evidenceCommandSnapshot.context.evidence_refs), ['event:2']);
    assert.deepEqual(Array.from(state.evidenceCommandSnapshot.context.assessment_refs), ['assessment:2']);
    assert.equal(state.evidenceCommandSnapshot.context.destination || '', '');
    assert.equal(insightPayloads.at(-1).evidenceContext.source_entity_id, 'network-owner:stable');
    assert.deepEqual(Array.from(insightPayloads.at(-1).evidenceContext.assessment_refs), ['assessment:2']);
});

test('table renderer preserves shell header resizers scroll and patches only tbody across routine states', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('row-1'), networkEvent('row-2'), networkEvent('row-3')]);
    const initial = harness.hooks.domRefs();
    initial.wrap.scrollTop = 240;
    initial.wrap.scrollLeft = 75;

    harness.hooks.renderDisplay();
    const repeated = harness.hooks.domRefs();
    assert.equal(repeated.wrap, initial.wrap);
    assert.equal(repeated.table, initial.table);
    assert.equal(repeated.thead, initial.thead);
    assert.equal(repeated.tbody, initial.tbody);
    assert.deepEqual(repeated.resizers, initial.resizers);
    assert.equal(repeated.wrap.scrollTop, 240);
    assert.equal(repeated.wrap.scrollLeft, 75);

    for (const state of [
        { events: [], phase: 'ready', contract: 'NO_DATA', reason: 'no_data' },
        { events: [], phase: 'loading', contract: 'CAPTURING', reason: 'waiting_for_capture' },
        { events: [], phase: 'ready', contract: 'ERROR', reason: 'capture_failed' },
        { events: [networkEvent('filtered-1')], phase: 'ready', contract: 'CAPTURING', reason: 'events_observed', filter: 'Known malicious endpoint' },
        { events: Array.from({ length: 140 }, (_value, index) => networkEvent(`many-${index}`)), phase: 'ready', contract: 'CAPTURING', reason: 'events_observed' },
    ]) {
        harness.hooks.setPagePhase(state.phase, state.reason);
        harness.hooks.setTableFilter(state.filter || '');
        harness.hooks.setTableData(state.events, state.contract, state.reason);
        harness.hooks.renderDisplay();
        const current = harness.hooks.domRefs();
        assert.equal(current.wrap, initial.wrap);
        assert.equal(current.thead, initial.thead);
        assert.equal(current.tbody, initial.tbody);
        assert.deepEqual(current.resizers, initial.resizers);
        assert.equal(current.wrap.scrollTop, 240);
    }

    harness.hooks.setView('findings');
    harness.hooks.renderDisplay();
    assert.equal(harness.hooks.domRefs().wrap, null);
    harness.hooks.setView('table');
    harness.hooks.setTableFilter('');
    harness.hooks.renderDisplay();
    const returned = harness.hooks.domRefs();
    assert.notEqual(returned.wrap, initial.wrap);
    assert.notEqual(returned.thead, initial.thead);
    assert.equal(returned.resizers.length, 7);
});

test('table fills unused viewport capacity with structurally empty grid rows', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([]);
    harness.hooks.setPagePhase('ready', 'settled');
    harness.hooks.renderDisplay();

    let rows = harness.hooks.domRefs().tbody.children;
    assert.equal(rows.length, 10);
    rows.forEach(row => {
        assert.equal(row.className, 'network-table-empty-row');
        assert.equal(row.children.length, 7);
        row.children.forEach(cell => assert.equal(cell.textContent, ''));
    });

    harness.hooks.setTableData([networkEvent('live-1'), networkEvent('live-2'), networkEvent('live-3')]);
    harness.hooks.renderDisplay();
    rows = harness.hooks.domRefs().tbody.children;
    assert.equal(rows.filter(row => row.classList.contains('network-row-evidence')).length, 3);
    assert.equal(rows.filter(row => row.className === 'network-table-empty-row').length, 7);
});

test('live table rows and no-packets summary are mutually exclusive', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([]);
    harness.hooks.setPagePhase('ready', 'settled');
    harness.hooks.renderDisplay();
    assert.equal(harness.hooks.snapshot().networkMessage, '0 active connections.');

    harness.hooks.setTableData([networkEvent('live-authoritative')], 'CAPTURING', 'events_observed', 37);
    harness.hooks.renderDisplay();
    const state = harness.hooks.snapshot();
    assert.equal(state.dom.rowIds.filter(Boolean).length, 1);
    assert.equal(state.networkMessage, '1 active connection.');
    assert.doesNotMatch(state.networkMessage, /No network packets observed yet/);
});

test('a visible live row makes the table loading state impossible', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([]);
    harness.hooks.setPagePhase('starting', 'live-start');
    harness.hooks.setTableData([networkEvent('first-live-row')], 'CAPTURING', 'events_observed', 37);
    harness.hooks.renderDisplay();

    const state = harness.hooks.snapshot();
    assert.equal(state.dom.rowIds.filter(Boolean).length, 1);
    assert.equal(state.networkMessage, '1 active connection.');
    assert.doesNotMatch(state.networkMessage, /Loading live network packets/);
});

test('snapshot reconciliation never removes an inventory row solely because it is absent', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    const quiet = networkEvent('quiet-connection', {
        source_display: '127.0.0.1:51001',
        destination_display: '198.51.100.10:443',
    });
    const active = networkEvent('active-connection', {
        source_display: '127.0.0.1:51002',
        destination_display: '198.51.100.20:443',
    });
    harness.hooks.setTableData([quiet, active], 'CAPTURING', 'events_observed', 40);

    harness.hooks.reconcileSnapshot([{
        ...active,
        timestamp: '2026-07-12T18:00:10Z',
        packet_index: 2,
    }], 39);
    harness.hooks.renderDisplay();

    const state = harness.hooks.snapshot();
    assert.equal(state.currentNetworkTableData.events.length, 2);
    assert.equal(state.currentNetworkTableData.events.some(event => event.source_display === '127.0.0.1:51001'), true);
    const refreshed = state.currentNetworkTableData.events.find(event => event.source_display === '127.0.0.1:51002');
    assert.equal(refreshed.packet_count, 2);
});

test('Network Table always returns operator sorting to Time descending', t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.setTableData([
        networkEvent('sort-a', { timestamp: '2026-07-12T18:00:03Z', process: 'Zulu', source_display: '10.0.0.3:503', destination_display: 'z.example:443', protocol: 'TLS', dst_port: '443', meaning: 'Zulu translation' }),
        networkEvent('sort-b', { timestamp: '2026-07-12T18:00:02Z', process: 'Alpha', source_display: '10.0.0.1:501', destination_display: 'a.example:53', protocol: 'DNS', dst_port: '53', meaning: 'Alpha translation' }),
        networkEvent('sort-c', { timestamp: '2026-07-12T18:00:01Z', process: 'Mike', source_display: '10.0.0.2:502', destination_display: 'm.example:80', protocol: 'HTTP', dst_port: '80', meaning: 'Mike translation' }),
    ], 'CAPTURING', 'events_observed', 3);

    let sortState = harness.hooks.snapshot().networkTableSort;
    assert.equal(sortState.key, 'time');
    assert.equal(sortState.direction, 'desc');
    harness.hooks.cycleSort('time');
    assert.equal(harness.hooks.snapshot().networkTableSort.direction, 'asc');
    harness.hooks.cycleSort('time');
    assert.equal(harness.hooks.snapshot().networkTableSort.direction, 'desc');

    for (const key of ['app', 'source', 'destination', 'protocol', 'port', 'translation']) {
        const defaultValues = harness.hooks.visibleSortValues(key);
        harness.hooks.cycleSort(key);
        const ascending = harness.hooks.visibleSortValues(key);
        assert.equal(ascending.every((value, index) => index === 0 || String(ascending[index - 1]).localeCompare(String(value), undefined, { numeric: true, sensitivity: 'base' }) <= 0), true);
        harness.hooks.cycleSort(key);
        const descending = harness.hooks.visibleSortValues(key);
        assert.deepEqual(descending, ascending.slice().reverse());
        harness.hooks.cycleSort(key);
        assert.deepEqual(harness.hooks.visibleSortValues(key), defaultValues);
        sortState = harness.hooks.snapshot().networkTableSort;
        assert.equal(sortState.key, 'time');
        assert.equal(sortState.direction, 'desc');
    }
});

test('live packet updates buffer rows and schedule one table flush without per-packet DOM mutation', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('base-1')]);
    harness.hooks.resetSpies();

    harness.hooks.appendLive(networkEvent('live-1'));
    harness.hooks.appendLive(networkEvent('live-2'));

    const state = harness.hooks.snapshot();
    assert.equal(state.networkTableUiBufferLength, 2);
    assert.equal(state.tableFlushTimerActive, true);
    assert.equal(state.dom.mutationCount, 0);
    assert.equal(state.spyState.tableFlushCalls, 0);
});

test('repeated packets update one deduped active connection row and header count together', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('base-1')]);
    harness.hooks.resetSpies();

    const firstPacket = networkEvent('packet-1', {
        source_display: '127.0.0.1:55111',
        destination_display: '198.51.100.20:443',
        dst_ip: '198.51.100.20',
        packet_index: 1,
        timestamp: '2026-07-09T12:00:01Z',
    });
    const secondPacket = networkEvent('packet-2', {
        source_display: '127.0.0.1:55111',
        destination_display: '198.51.100.20:443',
        dst_ip: '198.51.100.20',
        packet_index: 2,
        timestamp: '2026-07-09T12:00:02Z',
    });

    harness.hooks.appendLive(firstPacket);
    harness.hooks.appendLive(secondPacket);
    harness.hooks.flushTable(true);
    harness.hooks.flushHeader(true);
    await flush();

    const state = harness.hooks.snapshot();
    const liveRows = state.currentNetworkTableData.events.filter(event => event.source_display === '127.0.0.1:55111');
    assert.equal(liveRows.length, 1);
    assert.equal(liveRows[0].packet_count, 2);
    assert.equal(liveRows[0].raw_packet_events.length, 2);
    assert.equal(state.currentNetworkTableData.event_count, state.currentNetworkHeaderData.displayedConnectionCount);
    assert.equal(state.currentNetworkTableData.summary.counts.connections, state.currentNetworkTableData.events.length);
    assert.equal(state.networkMessage, '2 active connections.');
});

test('first live packet ends loading and updates the captured-packet header', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('base-1')]);
    harness.hooks.setActionOpen(true);
    harness.hooks.resetSpies();

    harness.hooks.appendLive(networkEvent('live-1'));
    await flush(220);

    let state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.equal(state.dom.mutationCount >= 1, true);
    assert.equal(state.spyState.renderDisplayCalls, 0);
    assert.equal(state.networkHeaderRenderPending, false);
    assert.equal(state.spyState.renderHeaderCalls, 1);
    assert.equal(state.spyState.tableFlushCalls, 1);
    assert.equal(state.networkTableUiBufferLength, 0);
    assert.match(state.dom.rowIds[0], /^connection:/);

    harness.hooks.setActionOpen(false);
    await flush();

    state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, false);
    assert.equal(state.spyState.tableFlushCalls, 1);
    assert.equal(state.spyState.renderHeaderCalls, 1);
});

test('window blur keeps visible live table and header work running', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('base-1')]);
    harness.hooks.resetSpies();

    harness.hooks.dispatchWindowBlur();
    harness.hooks.appendLive(networkEvent('blur-live-1'));
    await flush(220);

    const state = harness.hooks.snapshot();
    assert.equal(state.networkRenderSuspended, false);
    assert.equal(state.spyState.tableFlushCalls, 1);
    assert.equal(state.networkTableUiBufferLength, 0);
    assert.equal(state.dom.mutationCount >= 1, true);
});

test('pinned row stays retained and ordered above live rows under the DOM cap', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const seed = Array.from({ length: 120 }, (_item, index) => networkEvent(`seed-${index}`));
    const pinned = networkEvent('seed-90');
    seed[90] = pinned;
    harness.hooks.setView('table');
    harness.hooks.primeTable(seed);
    const pinnedId = harness.hooks.snapshot().visibleRowIds[90];
    harness.hooks.setPinned(pinnedId);
    harness.hooks.resetSpies();

    for (let index = 0; index < 25; index += 1) {
        harness.hooks.appendLive(networkEvent(`live-${index}`));
    }
    harness.hooks.flushTable(true);
    await flush();

    const state = harness.hooks.snapshot();
    assert.equal(state.networkTablePinnedEntityId, pinnedId);
    assert.equal(state.visibleRowIds[0], pinnedId);
    assert.equal(state.currentNetworkTableData.events[0].event_id, pinnedId);
    assert.equal(state.visibleRowIds.length, 120);
    assert.equal(state.dom.rowIds.length, 120);
    assert.ok(state.visibleRowIds.includes(pinnedId));
});

test('pinned row stays at the top until another row is selected or blank network space is clicked', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: `selected ${params.entityId}`,
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([
        networkEvent('row-1'),
        networkEvent('row-2'),
        networkEvent('row-3'),
    ]);
    harness.hooks.bindRows();

    harness.hooks.clickRow(1);
    await flush();

    let state = harness.hooks.snapshot();
    const row2Id = state.networkTablePinnedEntityId;
    assert.equal(state.dom.rowIds[0], row2Id);
    assert.match(row2Id, /^connection:/);

    harness.hooks.clickRow(2);
    await flush();

    state = harness.hooks.snapshot();
    const row3Id = state.networkTablePinnedEntityId;
    assert.equal(state.dom.rowIds[0], row3Id);
    assert.match(row3Id, /^connection:/);

    harness.hooks.clickBlankNetwork();
    await flush();

    state = harness.hooks.snapshot();
    assert.equal(state.networkTablePinnedEntityId, '');
    assert.notEqual(state.dom.rowIds[0], row3Id);
});

test('blank table chrome clears the pinned row while row clicks keep the control panel open', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            evidence_key: `network:${params.entityId}`,
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: 'table chrome selection',
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('row-1'), networkEvent('row-2')]);
    harness.hooks.bindRows();

    harness.hooks.clickRow(0);
    await flush();
    let state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.ok(state.networkTablePinnedEntityId);

    harness.hooks.clickTableChrome();
    await flush();
    state = harness.hooks.snapshot();
    assert.equal(state.networkTablePinnedEntityId, '');
    assert.equal(state.actionSidebarOpen, true);
});

test('hidden live updates catch up through one foreground snapshot without tearing down buffered rows', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setNetworkApi({
        getNetwork: async () => ({
            state: 'CAPTURING',
            events: [networkEvent('snapshot-1'), networkEvent('snapshot-2')],
            event_count: 2,
            summary: { reason: 'snapshot', counts: { connections: 2 } },
        }),
    });
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('base-1')]);
    harness.hooks.resetSpies();

    harness.hooks.dispatchVisibility(true);
    harness.hooks.appendLive(networkEvent('hidden-1'));
    harness.hooks.appendLive(networkEvent('hidden-2'));
    await flush(220);

    let state = harness.hooks.snapshot();
    assert.equal(state.networkRenderSuspended, true);
    assert.equal(state.networkVisibilityPendingHydration, true);
    assert.equal(state.spyState.tableFlushCalls, 0);
    assert.equal(state.spyState.renderHeaderCalls, 0);
    assert.equal(state.spyState.renderDisplayCalls, 0);
    assert.equal(state.dom.mutationCount, 0);

    harness.hooks.dispatchVisibility(false);
    await flush(80);

    state = harness.hooks.snapshot();
    assert.equal(state.networkRenderSuspended, false);
    assert.equal(state.spyState.resumeHydrationCalls, 1);
    assert.equal(state.spyState.getNetworkCalls, 1);
    assert.equal(state.spyState.getNetworkProjectionCalls, 0);
    assert.equal(state.networkTableUiBufferLength, 0);
    assert.match(state.dom.rowIds[0], /^connection:/);
    const rawEventIds = state.currentNetworkTableData.events
        .flatMap(event => Array.isArray(event.raw_packet_events) ? event.raw_packet_events : [])
        .map(event => event.event_id);
    assert.ok(rawEventIds.includes('hidden-1'));
    assert.ok(rawEventIds.includes('hidden-2'));
});

test('hidden ctrl work stays deferred until foreground recovery resumes one coalesced sidebar render', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setNetworkApi({
        getNetwork: async () => ({
            state: 'CAPTURING',
            events: [networkEvent('row-1')],
            event_count: 1,
            summary: { reason: 'snapshot', counts: { connections: 1 } },
        }),
    });
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: `selected ${params.entityId}`,
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([networkEvent('row-1')]);
    harness.hooks.bindRows();
    harness.hooks.dispatchVisibility(true);
    harness.hooks.resetSpies();

    harness.hooks.clickRow(0);
    await flush(20);

    let state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.equal(state.spyState.sidebarRenderCalls, 0);
    assert.equal(state.spyState.actionBodyWriteCount, 0);
    assert.equal(state.actionSidebarDeferredDetailsReady, false);
    assert.equal(state.networkDeferredRenderFlags.sidebar, true);

    harness.hooks.dispatchVisibility(false);
    await flush(80);

    state = harness.hooks.snapshot();
    assert.equal(state.spyState.resumeHydrationCalls, 1);
    assert.equal(state.spyState.sidebarRenderCalls >= 1, true);
    assert.equal(state.spyState.actionBodyWriteCount >= 1, true);
    assert.equal(state.actionSidebarDeferredDetailsReady, true);
});

test('foreground recovery preserves a pinned live row at the top without stale styling', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setNetworkApi({
        getNetwork: async () => ({
            state: 'CAPTURING',
            events: [networkEvent('row-2'), networkEvent('row-9')],
            event_count: 2,
            summary: { reason: 'snapshot', counts: { connections: 2 } },
        }),
    });
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: `selected ${params.entityId}`,
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([
        networkEvent('row-1'),
        networkEvent('row-2'),
        networkEvent('row-3'),
    ]);
    harness.hooks.bindRows();
    harness.hooks.clickRow(1);
    await flush();
    const selectedActiveId = harness.hooks.snapshot().networkTablePinnedEntityId;

    harness.hooks.dispatchVisibility(true);
    harness.hooks.appendLive(networkEvent('hidden-1'));
    await flush(20);
    harness.hooks.dispatchVisibility(false);
    await flush(80);

    const state = harness.hooks.snapshot();
    assert.equal(state.networkTablePinnedEntityId, selectedActiveId);
    assert.equal(state.visibleRowIds[0], selectedActiveId);
    assert.equal(state.dom.rowIds[0], selectedActiveId);
    assert.match(state.dom.rowClasses[0], /network-row-pinned/);
    assert.doesNotMatch(state.dom.rowClasses[0], /network-row-pinned-stale/);
});

test('selected inventory row remains unchanged when a foreground snapshot omits it', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    harness.setNetworkApi({
        getNetwork: async () => ({
            state: 'CAPTURING',
            events: Array.from({ length: 140 }, (_item, index) => networkEvent(`live-${index + 1000}`)),
            event_count: 140,
            summary: { reason: 'snapshot', counts: { connections: 140 } },
        }),
    });
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: `selected ${params.entityId}`,
        },
        actions: [],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable([
        networkEvent('row-1'),
        networkEvent('row-2'),
        networkEvent('row-3'),
    ]);
    harness.hooks.bindRows();
    harness.hooks.clickRow(1);
    await flush();
    const selectedStaleId = harness.hooks.snapshot().networkTablePinnedEntityId;

    harness.hooks.dispatchVisibility(true);
    harness.hooks.appendLive(networkEvent('hidden-1'));
    await flush(20);
    harness.hooks.dispatchVisibility(false);
    await flush(20);

    const state = harness.hooks.snapshot();
    assert.equal(state.networkTablePinnedEntityId, selectedStaleId);
    assert.equal(Boolean(state.networkTablePinnedRowSnapshot.__networkPinnedStale), false);
    assert.equal(state.visibleRowIds[0], selectedStaleId);
    assert.equal(state.dom.rowIds[0], selectedStaleId);
    assert.doesNotMatch(state.dom.rowClasses[0], /network-row-pinned-stale/);
    assert.equal(state.visibleRowIds.length, 120);
});

test('table ctrl open is selection-scoped and does not auto-run insight', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const seed = Array.from({ length: 160 }, (_item, index) => networkEvent(`seed-${index}`, {
        summary: `Seed event ${index}`,
        evidence_refs: [`local://cleanhouse/network/seed-${index}`],
    }));
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            evidence_key: `network:${params.entityId}`,
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: 'table row selected',
            evidence_refs: [`local://cleanhouse/network/${params.entityId}`],
        },
        actions: [{ id: 'ask_insight', label: 'Ask Insight', enabled: true, required_role: 'Insight' }],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable(seed);
    harness.hooks.bindRows();
    harness.hooks.resetSpies();

    harness.hooks.clickRow(80);
    await flush(10);

    const state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.equal(state.spyState.insightRequestCalls, 0);
    assert.equal(state.actionSidebarDeferredDetailsReady, true);
    assert.ok(state.spyState.technicalDetailsEventCounts.length >= 1);
    assert.equal(
        state.spyState.technicalDetailsEventCounts.at(-1),
        1,
        `ctrl technical details should resolve one event, saw ${state.spyState.technicalDetailsEventCounts.join(',')}`,
    );
});

test('A to B selection scopes Insight Copy Export and delayed action completion to one immutable version', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const insightA = deferred();
    const actionA = deferred();
    const actionPayloads = [];
    const actions = [
        { id: 'copy', label: 'Copy', enabled: true, required_role: 'viewer' },
        { id: 'export', label: 'Export', enabled: true, required_role: 'viewer' },
    ];
    harness.setEvidenceApi(
        async params => ({
            status: 'ok',
            context: {
                evidence_key: `network:${params.entityId}`,
                source_surface: params.surface,
                source_entity_id: params.entityId,
                source_view: params.sourceView,
                summary: `selection ${params.entityId}`,
            },
            actions,
        }),
        async payload => {
            if (payload.evidenceKey === 'network:A') return insightA.promise;
            return {
                status: 'ok',
                audit: { id: 'insight:B' },
                insight: { finding: 'B only', plain_language_summary: 'B selection insight' },
            };
        },
        async payload => {
            actionPayloads.push(payload);
            if (payload.entityId === 'A') return actionA.promise;
            return { status: 'ok', message: 'B export completed', audit: { id: 'action:B' } };
        },
    );
    harness.hooks.setView('table');

    harness.hooks.openEvidence({ surface: 'network', entityId: 'A', sourceView: 'table' });
    await flush(10);
    let state = harness.hooks.snapshot();
    assert.equal(state.evidenceCommandSnapshot.evidenceKey, 'network:A');
    assert.equal(state.evidenceSnapshotFrozen, true);

    harness.hooks.requestInsight();
    await flush();
    harness.hooks.executeAction(actions[0]);
    await flush();
    assert.equal(Object.keys(actionPayloads[0].insightPayload.insight).length, 0);

    harness.hooks.openEvidence({ surface: 'network', entityId: 'B', sourceView: 'table' });
    await flush(10);
    insightA.resolve({
        status: 'ok',
        audit: { id: 'insight:A' },
        insight: { finding: 'stale A', plain_language_summary: 'must not reach B' },
    });
    await flush();

    state = harness.hooks.snapshot();
    assert.equal(state.evidenceCommandSnapshot.evidenceKey, 'network:B');
    assert.equal(state.evidenceCommandSnapshot.insightResult, null);

    harness.hooks.requestInsight();
    await flush();
    harness.hooks.executeAction(actions[1]);
    await flush();
    actionA.resolve({ status: 'ok', message: 'stale A copy completed', audit: { id: 'action:A' } });
    await flush();

    state = harness.hooks.snapshot();
    assert.equal(actionPayloads.length, 2);
    assert.equal(actionPayloads[1].insightPayload.evidence_context.evidence_key, 'network:B');
    assert.equal(actionPayloads[1].insightPayload.insight.finding, 'B only');
    assert.equal(state.evidenceCommandSnapshot.evidenceKey, 'network:B');
    assert.equal(state.evidenceCommandSnapshot.insightResult.insight.finding, 'B only');
    assert.equal(state.evidenceCommandSnapshot.actionReceipt.audit.id, 'action:B');
    assert.equal(state.evidenceCommandStatus, 'B export completed');
    assert.equal(state.evidenceSnapshotFrozen, true);
});

test('resolved table ctrl open stays within the synchronous workload budget for large live datasets', async t => {
    const harness = createHarness();
    t.after(() => harness.cleanup());
    const seed = Array.from({ length: 520 }, (_item, index) => networkEvent(`seed-${index}`, {
        timestamp: `2026-07-09T12:${String(index % 60).padStart(2, '0')}:00Z`,
        process: index % 2 === 0 ? 'Safari' : `Worker ${index % 9}`,
        summary: `Outbound connection ${index}`,
        reason: index % 3 === 0 ? 'High connection volume' : 'Destination name missing',
        meaning: index % 3 === 0 ? 'burst' : 'lookup pending',
        raw_evidence_ref: `local://cleanhouse/network/seed-${index}`,
        evidence_refs: [`local://cleanhouse/network/seed-${index}`, `local://cleanhouse/network/flow-${index}`],
        related_event_ids: [`seed-${Math.max(0, index - 1)}`],
        dst_ip: `203.0.113.${index % 255}`,
        dst_port: String(4000 + (index % 40)),
        pid: String(5000 + index),
    }));
    const selectedIndex = 80;
    const selectedEvent = seed[selectedIndex];
    harness.hooks.setApplications(Array.from({ length: 180 }, (_item, index) => ({
        name: `Application ${index}`,
        bundle_id: `com.cleanhouse.app${index}`,
        processes: Array.from({ length: 4 }, (__item, processIndex) => ({
            process: processIndex === 0 && index === 12 ? selectedEvent.process : `proc-${index}-${processIndex}`,
            command: `/Applications/App${index}.app/${processIndex}`,
            name: processIndex === 0 && index === 12 ? selectedEvent.process : `proc-${index}-${processIndex}`,
            path: `/Applications/App${index}.app/Contents/MacOS/${processIndex}`,
        })),
    })));
    harness.setEvidenceApi(async params => ({
        status: 'ok',
        context: {
            evidence_key: `network:${params.entityId}`,
            source_surface: params.surface,
            source_entity_id: params.entityId,
            source_view: params.sourceView,
            summary: selectedEvent.summary,
            destination: selectedEvent.destination_display,
            dst_host: selectedEvent.destination_display,
            dst_ip: selectedEvent.dst_ip,
            dst_port: selectedEvent.dst_port,
            protocol: selectedEvent.protocol,
            process: selectedEvent.process,
            process_name: selectedEvent.process,
            evidence_refs: [...selectedEvent.evidence_refs, `local://cleanhouse/network/detail-${params.entityId}`],
            network_reasons: [selectedEvent.reason, selectedEvent.meaning, 'Operator review'],
            validation_state: 'unvalidated',
        },
        actions: [{ id: 'ask_insight', label: 'Ask Insight', enabled: true, required_role: 'Insight' }],
    }));
    harness.hooks.setView('table');
    harness.hooks.primeTable(seed);
    harness.hooks.bindRows();
    harness.hooks.resetSpies();

    harness.hooks.clickRow(selectedIndex);
    await flush(30);

    const state = harness.hooks.snapshot();
    assert.equal(state.actionSidebarOpen, true);
    assert.equal(state.spyState.renderDisplayCalls, 0);
    assert.equal(state.spyState.insightRequestCalls, 0);
    assert.equal(state.actionSidebarDeferredDetailsReady, true);
    assert.equal(state.spyState.resolveEvidenceEventCalls <= 2, true, `resolve scans regressed to ${state.spyState.resolveEvidenceEventCalls}`);
    assert.equal(state.spyState.buildSubjectCalls <= 3, true, `subject builds regressed to ${state.spyState.buildSubjectCalls}`);
    assert.equal(state.spyState.buildRouteTargetCalls <= 4, true, `route target builds regressed to ${state.spyState.buildRouteTargetCalls}`);
    assert.equal(state.spyState.ctrlResolvedRenderMs < 16, true, `resolved ctrl render exceeded budget: ${state.spyState.ctrlResolvedRenderMs.toFixed(2)}ms`);
    assert.equal(state.spyState.preDeferredResolvedWrites, 1, `expected one resolved shell write before defer, saw ${state.spyState.preDeferredResolvedWrites}`);
    assert.equal(state.spyState.deferredDetailCommits >= 1, true, 'expected deferred detail commit');
    assert.equal(state.spyState.firstResolvedBodyHtmlSize < 1600, true, `resolved shell HTML too large: ${state.spyState.firstResolvedBodyHtmlSize}`);
    assert.ok(state.spyState.technicalDetailsEventCounts.length >= 1);
    assert.equal(
        state.spyState.technicalDetailsEventCounts.at(-1),
        1,
        `ctrl technical details should resolve one event, saw ${state.spyState.technicalDetailsEventCounts.join(',')}`,
    );
});
