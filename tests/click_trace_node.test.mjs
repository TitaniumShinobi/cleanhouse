import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { performance } from 'node:perf_hooks';

const CLICK_TRACE_PATH = new URL('../frontend/js/click-trace.js', import.meta.url);
const CLICK_TRACE_SOURCE = fs.readFileSync(CLICK_TRACE_PATH, 'utf8');

function camelizeDataKey(name = '') {
    return String(name).replace(/^data-/, '').replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

function splitSelectors(selector = '') {
    return String(selector).split(',').map(item => item.trim()).filter(Boolean);
}

function matchesSelector(node, selector) {
    if (!node || !selector) return false;
    if (selector === 'button' || selector === 'a' || selector === 'input' || selector === 'textarea' || selector === 'select' || selector === 'summary') {
        return node.tagName.toLowerCase() === selector;
    }
    if (selector === '[role="button"]') return node.getAttribute('role') === 'button';
    if (selector === '[data-testid]') return Boolean(node.getAttribute('data-testid'));
    if (selector === '[aria-label]') return Boolean(node.getAttribute('aria-label'));
    if (selector === '[title]') return Boolean(node.getAttribute('title'));
    if (selector === '[data-testid="cleanhouse-click-trace-log"]') {
        return node.getAttribute('data-testid') === 'cleanhouse-click-trace-log';
    }
    return false;
}

function createSessionStorage() {
    const values = new Map();
    return {
        getItem(key) {
            return values.has(String(key)) ? values.get(String(key)) : null;
        },
        setItem(key, value) {
            values.set(String(key), String(value));
        },
        removeItem(key) {
            values.delete(String(key));
        }
    };
}

class MockElement {
    constructor(tagName = 'div') {
        this.nodeType = 1;
        this.tagName = String(tagName).toUpperCase();
        this.children = [];
        this.parentElement = null;
        this.attributes = new Map();
        this.dataset = {};
        this.hidden = false;
        this.className = '';
        this.value = '';
        this._textContent = '';
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    set textContent(value) {
        this._textContent = String(value || '');
        if (this._textContent === '') this.children = [];
    }

    appendChild(child) {
        child.parentElement = this;
        this.children.push(child);
        return child;
    }

    setAttribute(name, value) {
        const key = String(name);
        const text = String(value);
        this.attributes.set(key, text);
        if (key === 'class') this.className = text;
        if (key.startsWith('data-')) this.dataset[camelizeDataKey(key)] = text;
    }

    getAttribute(name) {
        return this.attributes.get(String(name)) || '';
    }

    closest(selector) {
        let current = this;
        const selectors = splitSelectors(selector);
        while (current) {
            if (selectors.some(item => matchesSelector(current, item))) return current;
            current = current.parentElement;
        }
        return null;
    }
}

function createHarness(options = {}) {
    const documentListeners = new Map();
    const timerCalls = [];
    const pageUrl = new URL(options.href || 'http://localhost:3333/investigations');
    const sessionStorage = options.sessionStorage || createSessionStorage();
    const document = {
        readyState: options.readyState || 'complete',
        body: new MockElement('body'),
        createElement(tag) {
            return new MockElement(tag);
        },
        addEventListener(type, handler) {
            if (!documentListeners.has(type)) documentListeners.set(type, []);
            documentListeners.get(type).push(handler);
        },
        querySelector(selector) {
            const stack = [document.body];
            while (stack.length) {
                const node = stack.shift();
                if (matchesSelector(node, selector)) return node;
                stack.push(...node.children);
            }
            return null;
        }
    };
    const window = {
        document,
        location: {
            href: pageUrl.href,
            origin: pageUrl.origin,
            pathname: pageUrl.pathname,
            search: pageUrl.search
        },
        sessionStorage,
        setTimeout(handler, ms) {
            const id = timerCalls.length + 1;
            timerCalls.push({ id, handler, ms, cleared: false });
            return id;
        },
        clearTimeout(id) {
            const timer = timerCalls.find(item => item.id === id);
            if (timer) timer.cleared = true;
        }
    };
    const context = {
        window,
        document,
        setTimeout: window.setTimeout.bind(window),
        clearTimeout: window.clearTimeout.bind(window),
        Date,
        URL,
        console
    };
    vm.createContext(context);
    vm.runInContext(CLICK_TRACE_SOURCE, context, { filename: 'click-trace.js' });

    function append(tag, attrs = {}, text = '') {
        const node = new MockElement(tag);
        Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
        node.textContent = text;
        document.body.appendChild(node);
        return node;
    }

    function click(target) {
        const event = { target };
        (documentListeners.get('click') || []).forEach(handler => handler(event));
    }

    return {
        append,
        click,
        document,
        sessionStorage,
        timerCalls,
        window
    };
}

function noticeText(document) {
    return document.querySelector('[data-testid="cleanhouse-click-trace-log"]')?.textContent || '';
}

function noticeCards(document) {
    const root = document.querySelector('[data-testid="cleanhouse-click-trace-log"]');
    return root ? root.children : [];
}

test('shared nav and placeholder clicks create visible ui.click cards', () => {
    const harness = createHarness();
    const nav = harness.append('a', { 'data-testid': 'cleanhouse-nav-applications', 'aria-label': 'Applications' }, '');
    const placeholder = harness.append('button', { 'aria-label': 'Placeholder action' }, 'Coming soon');

    harness.click(nav);
    harness.click(placeholder);

    assert.match(noticeText(harness.document), /ui\.click/);
    assert.match(noticeText(harness.document), /Click cleanhouse-nav-applications/);
    assert.match(noticeText(harness.document), /Click Placeholder action/);
});

test('observer installs immediately when a parser-time body already exists', () => {
    const harness = createHarness({ readyState: 'loading' });

    assert.equal(harness.window.CleanHouseClickTrace.installed, true);
    assert.equal(harness.window.CleanHouseClickTrace.version, '2.0.0');
});

test('representative in-page clicks use Code target-label precedence', () => {
    const harness = createHarness();
    const networkToggle = harness.append('button', {
        'data-testid': 'network-view-table',
        'aria-label': 'Network table',
        title: 'Table view'
    }, 'Table');

    harness.click(networkToggle);

    assert.equal(noticeCards(harness.document).length, 1);
    assert.match(noticeText(harness.document), /Click network-view-table/);
    assert.equal(
        harness.document.querySelector('[data-testid="cleanhouse-click-trace-log"]').getAttribute('data-observer-version'),
        '2.0.0'
    );
    assert.equal(harness.window.CleanHouseClickTrace.getNotices()[0].kind, 'ui.click');
    assert.equal(harness.timerCalls[0].ms, 5000);
});

test('repeated clicks retain five active cards and stay lightweight', () => {
    const harness = createHarness();
    const scanButton = harness.append('button', { 'aria-label': 'Scan Network' }, 'Refresh Network');
    const start = performance.now();

    for (let index = 0; index < 250; index += 1) {
        harness.click(scanButton);
    }

    const elapsed = performance.now() - start;
    assert.equal(noticeCards(harness.document).length, 5);
    assert.equal(harness.window.CleanHouseClickTrace.getNotices().length, 5);
    assert.ok(elapsed < 100, `click trace took ${elapsed.toFixed(2)}ms`);
});

test('same-origin navigation restores the click notice on the destination page', () => {
    const sessionStorage = createSessionStorage();
    const source = createHarness({ href: 'http://localhost:3333/network', sessionStorage });
    const overview = source.append('a', { href: '/overview', 'aria-label': 'Overview' });

    source.click(overview);

    const destination = createHarness({ href: 'http://localhost:3333/overview', sessionStorage });
    assert.match(noticeText(destination.document), /ui\.click/);
    assert.match(noticeText(destination.document), /Click Overview/);
    assert.equal(destination.window.CleanHouseClickTrace.getNotices()[0].payload.restoredAfterNavigation, true);
});

test('the source action can publish the standalone Control observation', () => {
    const harness = createHarness();

    harness.window.CleanHouseClickTrace.pushKeyNotice('Control');

    assert.equal(harness.window.CleanHouseClickTrace.version, '2.0.0');
    assert.match(noticeText(harness.document), /ui\.key/);
    assert.match(noticeText(harness.document), /Press Control/);
    assert.equal(harness.window.CleanHouseClickTrace.getNotices()[0].payload.key, 'Control');
});
