import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../frontend/js/investigations.js',import.meta.url),'utf8');
function run(expression){
 const context=vm.createContext({console,URL,URLSearchParams,AbortController,
 document:{addEventListener(){},querySelectorAll(){return[];},querySelector(){return null;},getElementById(){return null;}},
 window:{addEventListener(){},localStorage:{getItem(){return null;},setItem(){}},location:{pathname:'/network'}}});
 vm.runInContext(source,context);return vm.runInContext(expression,context);
}
test('authoritative empty owners never fall back to events or open application inventory',()=>{
 const html=run(`renderNetworkPie([{process:'Safari'}],{summary:{owners:[],open_applications:[{name:'Installed app',observed_network_events:8}]}})`);
 assert.match(html,/No packet-supported network activity/);assert.doesNotMatch(html,/network-pie-slice|Installed app|Safari/);
});
test('wheel and list use the same valid observed counts, stable names and evidence',()=>{
 const html=run(`renderNetworkPie([],{summary:{owners:[
 {owner_id:'code',name:'  Code  ',observed_network_events:2,evidence_refs:['packet:code'],assessment_refs:['assessment:code']},
 {owner_id:'codex',name:'Codex',observed_network_events:2,evidence_refs:['packet:codex']},
 ...[0,-1,NaN,Infinity,1.5].map((count,i)=>({name:'invalid'+i,observed_network_events:count}))
 ]}})`);
 assert.equal((html.match(/class="network-pie-slice"/g)||[]).length,2);
 assert.equal((html.match(/class="network-pie-legend-row"/g)||[]).length,2);
 for(const name of ['Code','Codex'])assert.equal((html.match(new RegExp('aria-label="'+name+': 2 observed network events"','g'))||[]).length,2);
 assert.equal((html.match(/data-evidence-entity-id="code"/g)||[]).length,2);
 assert.equal((html.match(/data-assessment-ids="assessment:code"/g)||[]).length,2);
 assert.doesNotMatch(html,/invalid|NaN|Infinity|connections|Open applications/i);
 assert.match(html,/role="group" aria-label="Network activity distribution by app"/);
 assert.match(html,/text-anchor="middle">4</);
});
test('legacy packet owners retain evidence and assessments without inventory guesses',()=>{
 const html=run(`renderNetworkPie([
 {process:'  Code ',event_id:'p1',assessment_refs:['a1']},
 {process:'Code',event_id:'p2',evidence_refs:['raw:p2'],assessment_refs:['a2']},
 {process:'Codex',event_id:'p3'}, {event_id:'unattributed'}
 ],{summary:{open_applications:[{name:'Inventory-only'}]}})`);
 assert.match(html,/data-evidence-entity-id="distribution:Code"/);
 assert.match(html,/local:\/\/cleanhouse\/network\/p1\|raw:p2\|local:\/\/cleanhouse\/network\/p2/);
 assert.match(html,/data-assessment-ids="a1\|a2"/);
 assert.match(html,/Unknown app: 1 observed network event/);
 assert.doesNotMatch(html,/Inventory-only/);
});
test('one owner has finite donut geometry and a matching singular label',()=>{
 const html=run(`renderNetworkPie([],{summary:{owners:[{owner_id:'only',name:'Safari',observed_network_events:1}]}})`);
 assert.equal((html.match(/aria-label="Safari: 1 observed network event"/g)||[]).length,2);
 assert.doesNotMatch(html,/NaN|Infinity|undefined/);
 assert.equal((html.match(/class="network-pie"/g)||[]).length,1);
});
