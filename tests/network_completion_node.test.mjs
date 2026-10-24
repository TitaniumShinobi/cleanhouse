import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const jsSource = fs.readFileSync(new URL('../frontend/js/investigations.js', import.meta.url), 'utf8');
const htmlSource = fs.readFileSync(new URL('../frontend/investigations.html', import.meta.url), 'utf8');
const cssSource = fs.readFileSync(new URL('../frontend/css/investigations.css', import.meta.url), 'utf8');
const apiSource = fs.readFileSync(new URL('../frontend/js/api-client.js', import.meta.url), 'utf8');

function evaluate(expression) {
    const context = vm.createContext({
        console, URL, URLSearchParams, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
        document: {
            hidden: false, addEventListener() {}, getElementById() { return null; },
            querySelector() { return null; }, querySelectorAll() { return []; },
        },
        window: {
            setTimeout, clearTimeout, setInterval, clearInterval,
            addEventListener() {},
            requestAnimationFrame(callback) { return setTimeout(callback, 0); },
            cancelAnimationFrame(id) { clearTimeout(id); },
            location: { pathname: '/network', href: 'http://127.0.0.1:3333/network', origin: 'http://127.0.0.1:3333' },
            history: { replaceState() {} },
            localStorage: { getItem() { return null; }, setItem() {} },
        },
    });
    context.window.window = context.window;
    context.window.document = context.document;
    vm.runInContext(jsSource, context, { filename: 'investigations.js' });
    return vm.runInContext(expression, context);
}

test('Graph and Chart preserve bar/pie duplicate navigation', () => {
    assert.match(htmlSource, /data-network-graph-view="bar"[^>]*>Graph</);
    assert.match(htmlSource, /data-network-graph-view="pie"[^>]*>Chart</);
    assert.match(jsSource, /graphToggle\.hidden = !\['bar', 'pie'\]\.includes\(networkViewMode\)/);
    assert.doesNotMatch(htmlSource, /data-network-trend-display/);
});

test('Trend remains a graph with a separate four-metric selector and gaps', () => {
    const rendered = evaluate(`networkTrendMetric='vulnerabilities';
    networkSelectedRangeWindow = () => ({
        start: new Date('2026-10-22T12:00:00Z'), end: new Date('2026-10-22T12:00:05Z'),
        range: { buckets: 5, durationMs: 5000 }
    });
    renderNetworkBarGraph([{
        event_id:'network-bucket:1',
        bucket_key:'bucket:1', bucket_start:'2026-10-22T12:00:01Z', bucket_end:'2026-10-22T12:00:02Z',
        metric:'vulnerabilities', value:3, assessment_refs:['assessment:1']
    }])`);
    assert.match(rendered, /network-trend-chart/);
    assert.match(rendered, /data-trend-metric="vulnerabilities"/);
    assert.match(rendered, /data-evidence-entity-id="network-bucket:1"/);
    assert.doesNotMatch(rendered, /<table/);
    for (const [metric, label] of Object.entries({ connections: 'Connections', strengths: 'Strengths', vulnerabilities: 'Vulnerabilities', threats: 'Threats' })) {
        assert.match(jsSource, new RegExp(`${metric}: '${label}'`));
    }
    assert.match(jsSource, /network-trend-bar is-empty/);
});

test('Findings preserve native details and canonical assessment prose', () => {
    const rendered = evaluate(`renderNetworkFindings([], {assessments:[{
        assessment_id:'assessment:unknown-app', category:'vulnerability', severity:'medium',
        confidence:{score:0.85,label:'high'}, lifecycle:'observed',
        subject:{label:'Unknown externally active application'}, rule:{id:'network.unknown_external_app',version:'1'},
        rationale:'The owner could not be attributed.', evidence_refs:['event:1']
    }]})`);
    assert.match(rendered, /<details class="case-item network-finding-item"/);
    assert.match(rendered, /data-category="vulnerability"/);
    assert.match(rendered, /The owner could not be attributed/);
    assert.match(rendered, /assessment:unknown-app/);
});

test('Distribution renders one packet-backed donut and one matching owner list', () => {
    const rendered = evaluate(`renderNetworkPie([], {summary:{owners:Array.from({length:10}, (_, index) => ({
        owner_id:'network-owner:'+index, name:'App '+index, observed_network_events:index+1,
        evidence_refs:['event:'+index], assessment_refs:['assessment:'+index]
    }))}})`);
    assert.equal((rendered.match(/class="network-pie"/g) || []).length, 1);
    assert.equal((rendered.match(/class="network-pie-legend"/g) || []).length, 1);
    assert.equal((rendered.match(/class="network-pie-legend-row"/g) || []).length, 10);
    assert.doesNotMatch(rendered, /Open applications/i);
    assert.match(rendered, /data-assessment-ids="assessment:0"/);
    assert.match(rendered, /data-evidence-related-ids="event:0"/);
    assert.match(rendered, /data-evidence-entity-id="network-owner:0"/);
    assert.match(rendered, /data-evidence-owner="App 0"/);
    assert.doesNotMatch(rendered, /data-evidence-ref="event:0"/);
});

test('deduped Connections retain every canonical assessment reference for ctrl', () => {
    const merged = evaluate(`networkMergeConnectionEvent(
        networkMergeConnectionEvent(null, {
            event_id:'packet:1', timestamp:'2026-07-04T12:00:00Z', process:'Safari',
            source_display:'127.0.0.1:50000', destination_display:'example.test:443',
            protocol:'TCP', dst_port:'443', assessment_refs:['assessment:strength']
        }),
        {
            event_id:'packet:2', timestamp:'2026-07-04T12:00:01Z', process:'Safari',
            source_display:'127.0.0.1:50000', destination_display:'example.test:443',
            protocol:'TCP', dst_port:'443', assessment_refs:['assessment:vulnerability']
        }
    )`);
    assert.deepEqual(Array.from(merged.assessment_refs), ['assessment:strength', 'assessment:vulnerability']);
    const attrs = evaluate(`networkEvidenceAttributes(${JSON.stringify(merged)}, 'table')`);
    assert.match(attrs, /data-assessment-ids="assessment:strength\|assessment:vulnerability"/);
});

test('Timeline interval exposes every contained event as an exact selection', () => {
    const rendered = evaluate(`renderNetworkTimeline([1,2,3].map(index => ({
        event_id:'event:'+index, timestamp:new Date().toISOString(), known_malicious:index===1,
        summary:'Event '+index, reason:index===1?'Known malicious endpoint':'Routine retained evidence',
        process:'Test app', dst_ip:index===1?'203.0.113.1':'127.0.0.'+index, scope:index===1?'external':'local'
    })), {})`);
    assert.match(rendered, /network-timeline-interval/);
    assert.equal((rendered.match(/class="network-timeline-event"/g) || []).length, 3);
    for (const id of ['event:1', 'event:2', 'event:3']) assert.match(rendered, new RegExp(id));
});

test('Network tabs and visual navigation expose accessible state', () => {
    const networkTabsMarkup = htmlSource.match(/<div class="network-display-controls"[\s\S]*?<\/div>/)?.[0] || '';
    assert.match(htmlSource, /role="tablist" aria-label="Network evidence views"/);
    assert.equal((networkTabsMarkup.match(/role="tab"/g) || []).length, 5);
    assert.match(htmlSource, /role="tabpanel" aria-labelledby="network-tab-connections"/);
    assert.match(htmlSource, /aria-label="Network visual navigation"/);
    assert.match(jsSource, /button\.setAttribute\('aria-selected', active \? 'true' : 'false'\)/);
    assert.match(jsSource, /button\.setAttribute\('aria-pressed', active \? 'true' : 'false'\)/);
    assert.match(jsSource, /event\.key === 'ArrowRight'/);
});

test('Shared Network frame preserves centered and responsive visual layouts', () => {
    assert.match(cssSource, /\.network-trend,[\s\S]*margin: 0 auto;[\s\S]*width: 100%;/);
    assert.match(cssSource, /\.network-pie-layout \{[^}]*flex-wrap: wrap;[^}]*justify-content: flex-start;/);
    assert.match(cssSource, /\.network-pie-legend \{[^}]*flex: 1 1 240px;[^}]*min-width: 0;/);
});

test('ctrl resolution preserves canonical assessment and evidence identity', () => {
    const merged = evaluate(`currentNetworkProjectionData={assessments:[{
        assessment_id:'assessment:exact', assessment_key:'unknown-app', category:'vulnerability',
        lifecycle:'observed', severity:'medium', rationale:'Owner attribution is missing.',
        rule:{id:'network.unknown_external_app',version:'1'}, subject:{label:'Unknown app'}, evidence_refs:['event:exact']
    }],events:[{event_id:'event:exact',summary:'Raw connection',process:'Unknown app',evidence_refs:['event:exact']} ]};
    mergeNetworkEvidenceContext({source_surface:'network',source_view:'findings',source_entity_id:'assessment:exact',evidence_refs:['event:exact']})`);
    assert.equal(merged.assessment_id, 'assessment:exact');
    assert.equal(merged.assessment_category, 'vulnerability');
    assert.equal(merged.source_entity_id, 'assessment:exact');
    assert.equal(merged.__selectedEvent.event_id, 'event:exact');
    assert.equal(merged.network_reasons[0], 'Owner attribution is missing.');
    assert.deepEqual(Array.from(merged.evidence_refs), ['event:exact']);
});

test('API sends metric additively and Findings does not inherit Trend range', () => {
    assert.match(apiSource, /if \(\(view \|\| 'findings'\) !== 'findings'\) query\.set\('range'/);
    assert.match(apiSource, /if \(normalized\.metric\) query\.set\('metric', normalized\.metric\)/);
    for (const type of ['network-event', 'gap', 'failure', 'status']) {
        assert.match(jsSource, new RegExp(`source\\.addEventListener\\('${type}'`));
    }
});

test('Header operational reasons are separate from authoritative posture', () => {
    assert.match(htmlSource, /id="network-posture-summary"/);
    assert.match(htmlSource, /— Threats/);
    assert.match(jsSource, /return mergeNetworkHeaderReasonEntries\(networkHeaderReasonsFromTagsPayload\(tags\)\)/);
    assert.match(jsSource, /currentNetworkHeaderData\.assessmentSummary/);
    for (const category of ['strengths', 'vulnerabilities', 'threats']) {
        assert.match(cssSource, new RegExp(`data-network-posture="${category}"`));
    }
});

test('Established Network behaviors remain present', () => {
    for (const symbol of [
        'networkTablePinnedEntityId', 'enableNetworkColumnResize', 'enableNetworkColumnSort',
        'network-findings-window', 'NETWORK_TREND_Y_AXIS_OPTIONS', 'networkCoordinatorState',
        'networkLastAppliedCursor', 'buildNetworkCtrlSubject', 'networkTimelineNotableBuckets'
    ]) assert.match(jsSource, new RegExp(symbol));
    assert.match(cssSource, /@media \(max-width: 980px\)/);
});
