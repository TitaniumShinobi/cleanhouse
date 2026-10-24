import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../frontend/js/investigations.js', import.meta.url), 'utf8');
function harness() {
    const context = vm.createContext({console, URL, URLSearchParams, AbortController,
        document: {addEventListener() {}, querySelector() {return null;}, querySelectorAll() {return [];}, getElementById() {return null;}},
        window: {addEventListener() {}, localStorage: {getItem() {return null;}, setItem() {}}, location: {pathname: '/network'}}});
    vm.runInContext(source, context);
    vm.runInContext(`networkSelectedRangeWindow = () => ({start:new Date('2026-10-22T12:00:00Z'),end:new Date('2026-10-22T12:00:05Z'),range:{buckets:5,durationMs:5000}});`, context);
    return expression => vm.runInContext(expression, context);
}

for (const metric of ['connections', 'strengths', 'vulnerabilities', 'threats']) {
    test(`${metric}: explicit missing coverage is not zero-valued evidence`, () => {
        const run = harness();
        const html = run(`networkTrendMetric='${metric}'; renderNetworkBarGraph([
            {event_id:'gap',bucket_start:'2026-10-22T12:00:00Z',bucket_end:'2026-10-22T12:00:01Z',gap:true,value:null},
            {event_id:'zero',bucket_start:'2026-10-22T12:00:01Z',bucket_end:'2026-10-22T12:00:02Z',connectionCount:0,value:0},
            {event_id:'observed',bucket_start:'2026-10-22T12:00:02Z',bucket_end:'2026-10-22T12:00:03Z',connectionCount:3,value:3},
            {event_id:'outside',bucket_start:'2026-10-22T12:00:05Z',bucket_end:'2026-10-22T12:00:06Z',connectionCount:99,value:99}
        ])`);
        assert.doesNotMatch(html, /data-evidence-entity-id="gap"|data-evidence-entity-id="outside"/);
        assert.equal((html.match(/No retained evidence for this interval/g)||[]).length, 3);
        assert.match(html, /network-trend-bar is-zero/);
        assert.match(html, /aria-label="0 /);
        assert.match(html, /aria-label="3 /);
        assert.equal((html.match(/role="button"/g)||[]).length, 2);
    });
}

test('metric selection preserves range, requests only changed valid selections, and exposes pressed state', () => {
    const run = harness();
    const result = run(`(() => {
        const requests=[];
        const buttons=['connections','strengths','vulnerabilities','threats','invalid'].map(metric=>({dataset:{networkTrendMetric:metric},addEventListener(type,callback){this.click=callback}}));
        document.querySelectorAll=()=>buttons;
        renderNetworkProjectionLoading=()=>{};
        deferNetworkProjectionLoad=(mode,refresh)=>requests.push([mode,refresh,networkTrendMetric]);
        networkTimelineRangeMode='24h';
        bindNetworkTrendMetricControls();
        buttons[0].click(); buttons[1].click(); buttons[1].click();buttons[2].click();buttons[3].click();buttons[4].click();
        return {requests,range:networkTimelineRangeMode,html:networkTrendMetricControlsHtml()};
    })()`);
    assert.equal(result.range, '24h');
    assert.equal(result.requests.length, 3);
    assert.deepEqual(Array.from(result.requests, row => row[2]), ['strengths','vulnerabilities','threats']);
    assert.match(result.html, /role="group" aria-label="Trend metric"/);
    assert.equal((result.html.match(/aria-pressed="true"/g)||[]).length, 1);
    assert.match(result.html, /data-network-trend-metric="threats" class="active" aria-pressed="true"/);
});

test('range change immediately excludes old evidence and late completion cannot populate cache or base', async () => {
    const run = harness();
    const result = await run(`(async () => {
        networkViewMode='bar';networkTrendMetric='threats';persistNetworkTimelineRange('1m');
        const old={state:'CAPTURING',events:[{event_id:'old-range'}],summary:{range:'1m',metric:'threats'}};
        rememberNetworkSettledProjection('trend','1m',old);
        currentNetworkTrendBaseData=old;
        let finish;
        window.CleanHouseAPI={getNetworkProjection:()=>new Promise(resolve=>finish=resolve)};
        renderConsentRequired=()=>false;logNetworkStartup=()=>{};
        renderNetworkDisplay=()=>{};deferNetworkProjectionLoad=()=>{};
        const pending=loadNetworkProjection('bar');
        const oldSignal=networkProjectionAbortController.signal;
        selectNetworkRange('24h');
        const immediate=buildNetworkRenderModel('bar');
        const phase=ensureNetworkCoordinatorState().viewStates.tabs.bar.phase;
        finish(old);await pending;
        return {aborted:oldSignal.aborted,immediateIds:immediate.events.map(x=>x.event_id),phase,
            range:immediate.selectedRange,cacheKeys:Object.keys(networkProjectionCache),base:currentNetworkTrendBaseData,
            target:networkCoordinatorProjectionRecord('trend','24h')};
    })()`);
    assert.equal(result.aborted,true);
    assert.equal(result.range,'24h');
    assert.equal(result.phase,'loading');
    assert.deepEqual(Array.from(result.immediateIds),[]);
    assert.deepEqual(Array.from(result.cacheKeys),[]);
    assert.equal(result.base,null);
    assert.equal(result.target,null);
});

test('only an exact range and metric record is reusable; unkeyed fallback cannot supply old range', () => {
    const run=harness();
    const result=run(`(() => {
        networkViewMode='bar';networkTrendMetric='strengths';persistNetworkTimelineRange('24h');
        const old={events:[{event_id:'wrong-range'}],summary:{range:'1m',metric:'strengths'}};
        networkSettledProjectionState.trend={range:'1m',effectiveFetchRange:'1m',data:old};
        currentNetworkTrendBaseData=old;
        const fallback=networkSettledProjectionData('trend','24h');
        const base=buildNetworkRenderModel('bar').events;
        const wrongMetric=networkTrendProjectionWithLive({events:[{event_id:'wrong-metric'}],summary:{range:'24h',metric:'threats'}},'24h').events;
        rememberNetworkSettledProjection('trend','24h',{events:[{event_id:'target'}],summary:{range:'24h',metric:'strengths'}});
        return {fallback,base,wrongMetric,target:networkSettledProjectionData('trend','24h').events};
    })()`);
    assert.equal(result.fallback,null);
    assert.equal(result.base.length,0);
    assert.equal(result.wrongMetric.length,0);
    assert.equal(result.target[0].event_id,'target');
});

test('Trend context occupies its own toolbar row and returns to original parent for other views', () => {
    const run = harness();
    const result = run(`(() => {
        const context={innerHTML:'',hidden:true}, moves=[], bindings=[];
        bindNetworkTrendMetricControls=()=>bindings.push('metric');
        bindNetworkTimelineRangeControls=()=>bindings.push('range');
        document.getElementById=id=>id==='network-toolbar-context'?context:null;
        document.querySelector=selector=>selector.endsWith('.network-toolbar')?{append(node){moves.push('toolbar')}}:{prepend(node){moves.push('actions')}};
        networkViewMode='bar';renderNetworkToolbarContext();const trend=context.innerHTML;
        networkViewMode='pie';renderNetworkToolbarContext();
        return {moves,bindings,trend,hidden:context.hidden,remaining:context.innerHTML};
    })()`);
    assert.deepEqual(Array.from(result.moves), ['toolbar','actions']);
    assert.deepEqual(Array.from(result.bindings), ['metric','range']);
    assert.match(result.trend, /Trend metric/);
    assert.equal(result.hidden,true);
    assert.equal(result.remaining,'');
});

test('settled Trend records cannot relabel another metric and switching invalidates in-flight evidence', () => {
    const run = harness();
    const result = run(`(() => {
        networkTrendMetric='connections';
        networkCoordinatorRememberProjection('trend','1m','1m',{events:[{event_id:'connection-only'}]},0,1);
        networkTrendMetric='threats';
        const absent=networkCoordinatorProjectionRecord('trend','1m');
        networkCoordinatorRememberProjection('trend','1m','1m',{events:[{event_id:'threat-only'}]},0,2);
        networkTrendMetric='connections';
        const original=networkCoordinatorProjectionRecord('trend','1m').data.events[0].event_id;
        let aborted=0;
        networkProjectionAbortController={abort(){aborted++}};
        networkProjectionRequestId=7;
        networkSettledProjectionState.trend={data:{events:[{event_id:'old'}]}};
        currentNetworkTrendBaseData={events:[{event_id:'old'}]};
        const button={dataset:{networkTrendMetric:'threats'},addEventListener(type,callback){this.click=callback}};
        document.querySelectorAll=()=>[button];
        renderNetworkProjectionLoading=()=>{};deferNetworkProjectionLoad=()=>{};
        bindNetworkTrendMetricControls();button.click();
        return {absent,original,aborted,requestId:networkProjectionRequestId,base:currentNetworkTrendBaseData,settled:networkSettledProjectionState.trend};
    })()`);
    assert.equal(result.absent,null);
    assert.equal(result.original,'connection-only');
    assert.equal(result.aborted,1);
    assert.equal(result.requestId,8);
    assert.equal(result.base,null);
    assert.equal(result.settled,null);
});

test('bar names use correct singular and plural for every metric', () => {
    const run = harness();
    for (const [metric, singular, plural] of [
        ['connections', 'observed connection', 'observed connections'],
        ['strengths', 'strength', 'strengths'],
        ['vulnerabilities', 'vulnerability', 'vulnerabilities'],
        ['threats', 'threat', 'threats'],
    ]) {
        for (const count of [0, 1, 9]) {
            const html = run(`networkTrendMetric='${metric}';renderNetworkBarGraph([{event_id:'bar',bucket_start:'2026-10-22T12:00:01Z',bucket_end:'2026-10-22T12:00:02Z',connectionCount:${count},value:${count}}])`);
            assert.ok(html.includes(`aria-label="${count} ${count === 1 ? singular : plural}. `));
        }
    }
});

test('Enter and Space select the same bar evidence exactly once after rebinding', () => {
    const run = harness();
    const result = run(`(() => {
        const handlers={}, selections=[], prevented=[];
        const element={tagName:'DIV',dataset:{evidenceEntityId:'covered-zero',evidenceSurface:'network',evidenceSourceView:'bar',evidenceRef:'interval-1'},
            addEventListener(type,callback){(handlers[type] ||= []).push(callback)}};
        document.querySelectorAll=()=>[element];
        openEvidenceActions=descriptor=>selections.push(descriptor);
        bindNetworkEvidenceElements('.network-trend-bar');
        bindNetworkEvidenceElements('.network-trend-bar');
        for (const key of ['Enter',' ','Escape']) {
            handlers.keydown.forEach(handler=>handler({key,preventDefault(){prevented.push(key)}}));
        }
        handlers.click.forEach(handler=>handler({stopPropagation(){}}));
        return {selections,prevented,keydownHandlers:handlers.keydown.length,clickHandlers:handlers.click.length};
    })()`);
    assert.equal(result.keydownHandlers, 1);
    assert.equal(result.clickHandlers, 1);
    assert.deepEqual(Array.from(result.prevented), ['Enter', ' ']);
    assert.equal(result.selections.length, 3);
    for (const descriptor of result.selections) {
        assert.equal(descriptor.entityId, 'covered-zero');
        assert.equal(descriptor.sourceView, 'bar');
        assert.equal(descriptor.ref, 'interval-1');
    }
});
