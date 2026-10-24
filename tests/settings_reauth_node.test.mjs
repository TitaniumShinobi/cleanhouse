import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const original = fs.readFileSync(new URL('../frontend/js/settings.js', import.meta.url), 'utf8');
const source = original.replace(/\}\)\(\);\s*$/, 'window.__reauthTest = { reauthControl };})();');
const context = vm.createContext({
    window: {},
    document: { addEventListener() {}, getElementById() { return null; }, querySelectorAll() { return []; } },
    console, URL, URLSearchParams, fetch: async () => { throw new Error('not used'); },
});
vm.runInContext(source, context);
const render = payload => context.window.__reauthTest.reauthControl({ reauthentication: payload });

const email = { id: 'magic_email', label: 'Confirm by verified email', available: true };
const noEmail = { ...email, available: false };
const password = available => ({ id: 'password', label: 'Confirm password', available });
const google = configured => ({ id: 'google', label: 'Confirm with Google', connected: true, configured, available: false });

test('Google-only identity offers verified email without a password prompt', () => {
    const html = render({ password: password(false), verified_email: email, providers: [google(true)] });
    assert.match(html, /Signed in with Google/);
    assert.match(html, /Confirm by verified email/);
    assert.doesNotMatch(html, /Current password|Confirm password/);
});

test('password-only identity preserves password confirmation', () => {
    const html = render({ password: password(true), verified_email: noEmail, providers: [] });
    assert.match(html, /Current password/);
    assert.match(html, /Confirm password/);
    assert.doesNotMatch(html, /Signed in with Google/);
});

test('mixed identity exposes supported password and verified-email methods', () => {
    const html = render({ password: password(true), verified_email: email, providers: [google(true)] });
    assert.match(html, /Current password/);
    assert.match(html, /Confirm by verified email/);
    assert.match(html, /Signed in with Google/);
});

test('unavailable OAuth provider is context, not a fake confirmation action', () => {
    const html = render({ password: password(false), verified_email: email, providers: [google(false)] });
    assert.match(html, /Signed in with Google/);
    assert.doesNotMatch(html, />Confirm with Google</);
});

test('capability failure and no-method state are explicit and password-free', () => {
    const discoveryFailure = context.window.__reauthTest.reauthControl(null);
    const unavailable = render({ password: password(false), verified_email: noEmail, providers: [google(false)] });
    assert.match(discoveryFailure, /Confirmation methods are currently unavailable/);
    assert.match(unavailable, /No fresh confirmation method is currently available/);
    assert.doesNotMatch(discoveryFailure + unavailable, /Current password|Confirm password/);
});
