import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const original = fs.readFileSync(new URL('../frontend/js/settings.js', import.meta.url), 'utf8');
const source = original.replace(/\}\)\(\);\s*$/, 'window.__photoTest = { showProviderPhotoReturn };})();');

function harness(url, avatarUrl = '') {
    const image = { hidden: true, listeners: {}, addEventListener(event, handler) { this.listeners[event] = handler; }, src: '' };
    const fallback = { hidden: false };
    const result = { innerHTML: '' };
    const link = { dataset: {}, setAttribute() {} };
    const nodes = {
        'settings-profile-image': image,
        'settings-profile-fallback': fallback,
        'settings-profile-link': link,
        'settings-action-result': result,
    };
    const calls = [];
    const window = { location: { href: url } };
    const history = {
        state: {},
        replaceState(_state, _title, path) { window.location.href = new URL(path, window.location.href).href; },
    };
    const context = vm.createContext({
        window, history, URL, URLSearchParams, console,
        document: { addEventListener() {}, getElementById(id) { return nodes[id] || null; }, querySelectorAll() { return []; } },
        fetch: async path => {
            calls.push(path);
            return { ok: true, json: async () => ({ user: { full_name: 'Owner', avatar_url: avatarUrl } }) };
        },
    });
    vm.runInContext(source, context);
    return { window, image, fallback, result, calls };
}

test('OAuth photo return loads the current session thumbnail and consumes its result', async () => {
    const avatar = 'https://lh3.googleusercontent.com/a/owner';
    const app = harness('http://localhost:3333/settings?settings=providers&photo_refreshed=google', avatar);
    await app.window.__photoTest.showProviderPhotoReturn();
    assert.deepEqual(app.calls, ['/api/auth/me']);
    assert.equal(app.image.src, avatar);
    app.image.listeners.load();
    assert.equal(app.image.hidden, false);
    assert.equal(app.fallback.hidden, true);
    assert.match(app.result.innerHTML, /Google profile photo refreshed/);
    assert.equal(new URL(app.window.location.href).searchParams.has('photo_refreshed'), false);
});

test('provider cancellation is visible without fetching a thumbnail or retaining the result query', async () => {
    const app = harness('http://localhost:3333/settings?settings=providers&error=photo_denied');
    await app.window.__photoTest.showProviderPhotoReturn();
    assert.deepEqual(app.calls, []);
    assert.match(app.result.innerHTML, /Photo refresh was cancelled at the provider/);
    assert.equal(new URL(app.window.location.href).searchParams.has('error'), false);
});
