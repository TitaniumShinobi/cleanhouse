import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const api = fs.readFileSync(new URL('../frontend/js/api-client.js', import.meta.url), 'utf8');
const shell = fs.readFileSync(new URL('../frontend/js/investigations.js', import.meta.url), 'utf8');
function setup(status=428, code='consent_required') {
    const elements = new Map();
    const get = id => { if (!elements.has(id)) elements.set(id, {textContent:'', innerHTML:'', dataset:{}, hidden:false}); return elements.get(id); };
    const listeners = {};
    const window = { location:{protocol:'http:',origin:'http://localhost:3333',href:'http://localhost:3333/network',pathname:'/network'},
        fetch: async () => new Response(JSON.stringify({code}), {status}),
        addEventListener:(name, fn) => { listeners[name]=fn; }, dispatchEvent:event => listeners[event.type]?.(event),
        setTimeout,clearTimeout,setInterval,clearInterval, localStorage:{getItem:()=>null,setItem(){}}, history:{replaceState(){}} };
    const context = vm.createContext({window,document:{addEventListener(){},getElementById:get,querySelectorAll:()=>[],querySelector:()=>null},
        console,URL,URLSearchParams,Response,AbortController,CustomEvent:class {constructor(type){this.type=type;}},setTimeout,clearTimeout,setInterval,clearInterval});
    vm.runInContext(api,context); vm.runInContext(shell,context);
    return {context,window,get};
}
test('only same-origin consent rejection blocks access; body remains readable',async()=>{
    for(const [status,code,origin,blocked] of [[428,'consent_required','http://localhost:3333',true],[500,'server_error','http://localhost:3333',false],[428,'other_precondition','http://localhost:3333',false],[428,'consent_required','https://example.test',false]]) {
        const {window}=setup(status,code);
        const response=await window.fetch(origin+'/cleanhouse/network');
        assert.equal((await response.json()).code,code);
        assert.equal(window.CleanHouseAccess.consentRequired,blocked);
    }
});
test('blocked rendering survives tab changes and late error callbacks without collector claims',async()=>{
    const {window,context,get}=setup();
    await window.fetch('/cleanhouse/network');
    for(const call of ['renderApplications()','renderFilesDisplay()','renderNetworkDisplay()','renderNetworkUnavailable({state:"ERROR",summary:{reason:"capture_failed"}})','renderNetworkHeader()','networkEnginePanel("Capture failed")']) vm.runInContext(call,context);
    for(const id of ['app-grid','files-results','network-results']) {
        assert.match(get(id).innerHTML,/Policy consent required/);
        assert.match(get(id).innerHTML,/Review policies/);
        assert.doesNotMatch(get(id).innerHTML,/capture failed|No applications|No file events/i);
    }
    assert.equal(get('network-state-tag').textContent,'CONSENT REQUIRED');
    assert.match(get('overview-threats').textContent,/Data access is blocked/);
    assert.equal(get('overview-threat-count').textContent,'—');
    // No new requests or streams can be started while blocked.
    window.CleanHouseAPI.getApplications=()=>{throw Error('must not fetch');};
    await vm.runInContext('loadApplications(true)',context);
    vm.runInContext('startNetworkLiveUpdates(); startFilesLiveMonitoring()',context);
});
