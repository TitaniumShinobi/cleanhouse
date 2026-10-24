import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../frontend/js/investigations.js', import.meta.url), 'utf8');

test('repeated Findings render uses one resize callback and touches only the mounted feed', () => {
    const listeners = new Set();
    let mounted;
    function fixture() {
        let writes = 0;
        const classes = new Map();
        const feed = new EventTarget();
        Object.assign(feed, { scrollTop: 0, clientHeight: 100, scrollHeight: 300, querySelectorAll: () => [] });
        return { feed, classes, get writes() { return writes; },
            querySelector: () => feed,
            classList: { toggle(name, value) { writes++; classes.set(name, value); } } };
    }
    const context = vm.createContext({ console, URL, URLSearchParams,
        document: { addEventListener() {}, querySelector: () => mounted },
        window: { addEventListener(type, callback) { if (type === 'resize') listeners.add(callback); },
            location: {pathname:'/network'}, localStorage:{getItem:()=>null} } });
    vm.runInContext(source, context);
    const first = mounted = fixture();
    for (let i = 0; i < 25; i++) vm.runInContext('bindNetworkFindingsWindow()', context);
    assert.equal(listeners.size, 1);
    assert.equal(first.classes.get('has-top-fade'), false);
    assert.equal(first.classes.get('has-bottom-fade'), true);
    const firstWrites = first.writes;
    const second = mounted = fixture();
    second.feed.scrollTop = 200;
    vm.runInContext('bindNetworkFindingsWindow()', context);
    const before = second.writes;
    for (const callback of listeners) callback();
    assert.equal(listeners.size, 1);
    assert.equal(first.writes, firstWrites);
    assert.equal(second.writes, before + 2);
    assert.equal(second.classes.get('has-top-fade'), true);
    assert.equal(second.classes.get('has-bottom-fade'), false);
    second.feed.scrollTop = 50;
    second.feed.dispatchEvent(new Event('scroll'));
    assert.equal(second.classes.get('has-top-fade'), true);
    assert.equal(second.classes.get('has-bottom-fade'), true);
    mounted = null;
    assert.doesNotThrow(() => { for (const callback of listeners) callback(); });
    assert.equal(first.writes, firstWrites);
});
