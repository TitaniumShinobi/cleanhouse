import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/js/auth.js', import.meta.url), 'utf8');
const start = source.indexOf('function safeLocalReturn(value)');
const end = source.indexOf('async function completeOAuthRedirectIfPresent()', start);
assert.ok(start >= 0 && end > start, 'auth navigation functions must remain executable');

const window = {
    location: { origin: 'http://localhost:3333', href: '' },
    authState: null,
};
const context = vm.createContext({
    window,
    URL,
    TextEncoder,
    decodeURIComponent,
    setTimeout: callback => callback(),
    showSuccess() {},
    dashboardRedirectWithLoginReport: () => '/overview?login_report=1',
});
vm.runInContext(
    source.slice(start, end) + '\nglobalThis.__authNavigation = { safeLocalReturn, completeAuth };',
    context,
);
const { safeLocalReturn, completeAuth } = context.__authNavigation;

test('safe local auth return accepts one bounded same-origin route', () => {
    assert.equal(safeLocalReturn('/network?range=30m#active'), '/network?range=30m#active');
});

test('unsafe and loop auth returns fall back to the normal dashboard route', () => {
    const unsafe = [
        '//attacker.example/path',
        '/\\attacker.example/path',
        '/%2fattacker.example/path',
        '/%5cattacker.example/path',
        '/safe%0apath',
        '/login',
        '/login/',
        '/login/?next=/network',
        '/login%2f?next=/network',
        '/signup?next=/network',
        '/signup/',
        '/signup%2f',
        '/safe/../login',
        '/' + 'a'.repeat(2048),
    ];
    for (const value of unsafe) {
        window.location.href = '';
        assert.equal(safeLocalReturn(value), '', value);
        completeAuth({ return_to: value });
        assert.equal(window.location.href, '/overview?login_report=1', value);
    }
});

test('a safe auth return is consumed as the navigation target', () => {
    completeAuth({ return_to: '/network?range=30m' });
    assert.equal(window.location.href, '/network?range=30m');
});
