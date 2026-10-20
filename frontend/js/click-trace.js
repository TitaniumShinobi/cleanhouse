(function () {
    'use strict';

    var NOTICE_TTL_MS = 5000;
    var NOTICE_LIMIT = 5;
    var OBSERVER_VERSION = '2.0.0';
    var ROOT_TEST_ID = 'cleanhouse-click-trace-log';
    var NOTICE_TEST_ID = 'cleanhouse-click-trace-notice';
    var PENDING_NAVIGATION_NOTICE_KEY = 'cleanhouse.clickTrace.pendingNavigation';
    var notices = [];
    var timers = Object.create(null);
    var sequence = 0;

    function compactText(value, maxLength) {
        var raw = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
        if (!raw) return '';
        var limit = maxLength || 96;
        return raw.length > limit ? raw.slice(0, limit - 1).trimEnd() + '…' : raw;
    }

    function traceText(value) {
        return compactText(value, 4000);
    }

    function closestTraceTarget(target) {
        if (!target || typeof target.closest !== 'function') return null;
        return target.closest('button, a, input, textarea, select, summary, [role="button"], [data-testid], [aria-label], [title]');
    }

    function isSuppressedInputClick(target) {
        if (!target || typeof target.closest !== 'function') return false;
        var input = target.closest('input, textarea, select');
        if (!input) return false;
        var testId = input.getAttribute && input.getAttribute('data-testid');
        return testId === 'zaelith-message-input';
    }

    function normalizeTarget(target) {
        var fallback = target && target.nodeType === 1 ? target : null;
        var element = closestTraceTarget(target) || fallback;
        if (!element || !element.tagName) return null;

        var tag = element.tagName.toLowerCase();
        var type = String(element.getAttribute && element.getAttribute('type') || element.type || '').toLowerCase();
        var isPassword = tag === 'input' && type === 'password';
        var textSource = '';

        if (tag === 'input' || tag === 'textarea') {
            textSource = isPassword
                ? (element.getAttribute('placeholder') || element.getAttribute('aria-label') || '')
                : (element.value || element.getAttribute('value') || element.getAttribute('placeholder') || element.textContent || '');
        } else {
            textSource = element.textContent || '';
        }

        return {
            tag: tag,
            testId: traceText(element.getAttribute('data-testid')),
            label: traceText(textSource),
            ariaLabel: traceText(element.getAttribute('aria-label')),
            title: traceText(element.getAttribute('title')),
            placeholder: traceText(element.getAttribute('placeholder'))
        };
    }

    function targetLabel(target) {
        return compactText(target && target.testId, 56)
            || compactText(target && target.ariaLabel, 56)
            || compactText(target && target.title, 56)
            || compactText(target && target.placeholder, 56)
            || compactText(target && target.label, 56)
            || compactText(target && target.tag, 32)
            || 'app';
    }

    function ensureRoot() {
        var existing = document.querySelector('[data-testid="' + ROOT_TEST_ID + '"]');
        if (existing) {
            existing.setAttribute('data-observer-version', OBSERVER_VERSION);
            return existing;
        }
        var root = document.createElement('section');
        root.className = 'cleanhouse-click-trace';
        root.setAttribute('data-testid', ROOT_TEST_ID);
        root.setAttribute('data-observer-version', OBSERVER_VERSION);
        root.setAttribute('aria-label', 'Screen activity notifications');
        root.setAttribute('aria-live', 'polite');
        document.body.appendChild(root);
        return root;
    }

    function render() {
        var root = ensureRoot();
        root.textContent = '';
        root.hidden = notices.length === 0;
        notices.forEach(function (entry) {
            var card = document.createElement('div');
            card.className = 'cleanhouse-click-trace__notice';
            card.setAttribute('data-testid', NOTICE_TEST_ID);

            var kind = document.createElement('span');
            kind.className = 'cleanhouse-click-trace__kind';
            kind.textContent = entry.kind;

            var message = document.createElement('span');
            message.className = 'cleanhouse-click-trace__message';
            message.textContent = entry.message;

            card.appendChild(kind);
            card.appendChild(message);
            root.appendChild(card);
        });
    }

    function removeNotice(id) {
        notices = notices.filter(function (entry) {
            return entry.id !== id;
        });
        if (timers[id]) {
            clearTimeout(timers[id]);
            delete timers[id];
        }
        render();
    }

    function presentNotice(notice, now) {
        if (!notice || notice.expiresAt <= now) return null;
        notices = notices.filter(function (entry) {
            return entry.expiresAt > now;
        });
        notices.push(notice);
        notices = notices.slice(-NOTICE_LIMIT);

        var activeIds = Object.create(null);
        notices.forEach(function (entry) {
            activeIds[entry.id] = true;
        });
        Object.keys(timers).forEach(function (id) {
            if (activeIds[id]) return;
            clearTimeout(timers[id]);
            delete timers[id];
        });

        timers[notice.id] = setTimeout(function () {
            removeNotice(notice.id);
        }, Math.max(0, notice.expiresAt - now));

        render();
        return notice;
    }

    function pushNotice(kind, message, payload, idPrefix) {
        var now = Date.now();
        return presentNotice({
            id: (idPrefix || 'cleanhouse-trace') + '-' + now + '-' + (++sequence),
            kind: kind,
            message: message,
            timestamp: now,
            expiresAt: now + NOTICE_TTL_MS,
            payload: payload || {}
        }, now);
    }

    function pushClickNotice(target) {
        return pushNotice('ui.click', 'Click ' + targetLabel(target), { target: target }, 'cleanhouse-click');
    }

    function pushKeyNotice(key) {
        return pushNotice('ui.key', 'Press ' + compactText(key, 32), { key: key }, 'cleanhouse-key');
    }

    function navigationSessionStorage() {
        try {
            return window.sessionStorage || null;
        } catch (_error) {
            return null;
        }
    }

    function persistNavigationNotice(eventTarget, notice) {
        var storage = navigationSessionStorage();
        if (!notice || !storage || !window.location) return;
        var anchor = eventTarget && typeof eventTarget.closest === 'function' ? eventTarget.closest('a') : null;
        if (!anchor || anchor.getAttribute('download')) return;
        var target = anchor.getAttribute('target');
        if (target && target !== '_self') return;
        var href = anchor.getAttribute('href');
        if (!href || href.charAt(0) === '#') return;

        try {
            var current = new URL(window.location.href);
            var destination = new URL(href, current.href);
            if (destination.origin !== current.origin) return;
            if (destination.pathname === current.pathname && destination.search === current.search) return;
            storage.setItem(PENDING_NAVIGATION_NOTICE_KEY, JSON.stringify({
                version: 1,
                kind: notice.kind,
                message: notice.message,
                timestamp: notice.timestamp,
                expiresAt: notice.expiresAt
            }));
        } catch (_error) {
            // Observation must never interfere with navigation.
        }
    }

    function restoreNavigationNotice() {
        var storage = navigationSessionStorage();
        if (!storage) return null;
        var raw = '';
        try {
            raw = storage.getItem(PENDING_NAVIGATION_NOTICE_KEY) || '';
            storage.removeItem(PENDING_NAVIGATION_NOTICE_KEY);
        } catch (_error) {
            return null;
        }
        if (!raw) return null;

        try {
            var stored = JSON.parse(raw);
            var now = Date.now();
            if (stored.version !== 1 || stored.kind !== 'ui.click' || !stored.message) return null;
            return presentNotice({
                id: 'cleanhouse-navigation-' + now + '-' + (++sequence),
                kind: stored.kind,
                message: stored.message,
                timestamp: Number(stored.timestamp) || now,
                expiresAt: Number(stored.expiresAt) || 0,
                payload: { restoredAfterNavigation: true }
            }, now);
        } catch (_error) {
            return null;
        }
    }

    function onDocumentClick(event) {
        if (isSuppressedInputClick(event.target)) return;
        var target = normalizeTarget(event.target);
        if (!target) return;
        var notice = pushClickNotice(target);
        persistNavigationNotice(event.target, notice);
    }

    function install() {
        if (!document || !document.addEventListener || !document.body) return;
        if (window.CleanHouseClickTrace && window.CleanHouseClickTrace.installed) return;
        document.addEventListener('click', onDocumentClick, true);
        restoreNavigationNotice();
        window.CleanHouseClickTrace = {
            installed: true,
            version: OBSERVER_VERSION,
            normalizeTarget: normalizeTarget,
            pushClickNotice: pushClickNotice,
            pushKeyNotice: pushKeyNotice,
            getNotices: function () {
                return notices.slice();
            },
            clear: function () {
                Object.keys(timers).forEach(function (id) {
                    clearTimeout(timers[id]);
                    delete timers[id];
                });
                notices = [];
                render();
            }
        };
    }

    if (document.body) {
        install();
    } else {
        document.addEventListener('DOMContentLoaded', install, { once: true });
    }
}());
