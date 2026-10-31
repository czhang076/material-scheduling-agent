// Execute the shipped state controller in a small DOM shell; no copied controller logic.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {randomUUID} = require('node:crypto');
const vm = require('node:vm');

function harness() {
  const nodes = new Map();
  function node() {return {disabled:false,value:'',textContent:'',classList:{toggle(){}},replaceChildren(){},append(){},scrollIntoView(){}};}
  const context = vm.createContext({crypto:{randomUUID},structuredClone,setTimeout,clearTimeout,AbortController,
    document:{getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:node,createTextNode:value=>value},
    localStorage:{setItem(){},removeItem(){}},matchMedia:()=>({matches:true})});
  const source = readFileSync(process.env.SCHEDULER_WEB_SOURCE || resolve(__dirname,'../../src/material_scheduler/interfaces/web/app.js'),'utf8');
  const end = source.indexOf('document.querySelectorAll("[data-view]")');
  assert.ok(end > 0);
  vm.runInContext(source.slice(0,end),context);
  vm.runInContext('render=()=>{};renderPending=()=>{};toast=()=>{};network=()=>{};',context);
  return {context,run:code=>vm.runInContext(code,context)};
}
const payload = hour => ({schema_version:'1.0',request_id:'REQ-'+hour,items:[{item_id:'I01',material_id:'M01',channel:'douyin',time_requirement:{requested_start:'2030-06-01T'+hour+':00:00+08:00'}}]});
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}

test('network-unknown old input never replaces newly edited requirements',async()=>{
  const h=harness();let calls=0;
  h.context.api=async()=>{calls++;throw Object.assign(new Error('network'),{network:true});};
  h.context.old=payload('18');h.context.newer=payload('20');
  await h.run('submitRequest(old,"mock")');
  const operation=h.run('state.pending.submission_id');
  await h.run('submitRequest(newer,"mock")');
  assert.equal(calls,1);
  assert.equal(h.run('state.pending.submission_id'),operation);
  assert.match(h.run('$("form-error").textContent'),/原提交|待查询/);
});

test('changing real mode to Mock cannot retry the old real operation',async()=>{
  const h=harness();let calls=0;
  h.context.api=async()=>{calls++;throw Object.assign(new Error('network'),{network:true});};
  h.context.old=payload('18');
  await h.run('submitRequest(old,"real")');
  await h.run('submitRequest(old,"mock")');
  assert.equal(calls,1);
  assert.equal(h.run('state.pending.mode'),'real');
});

test('an identical retry reuses the operation and clears it only after loading',async()=>{
  const h=harness(),sent=[];
  h.context.api=async(path,options)=>{sent.push(JSON.parse(JSON.stringify(options.body)));if(sent.length===1)throw Object.assign(new Error('network'),{network:true});return {run:{run_id:'RUN-1'},reused:true};};
  h.run('loadRun=async()=>{}');h.context.old=payload('18');
  await h.run('submitRequest(old,"mock")');await h.run('submitRequest(old,"mock")');
  assert.equal(sent.length,2);assert.deepEqual(sent[0],sent[1]);assert.equal(h.run('state.pending'),null);
});

test('explicit old-operation retry is independent of a changed form',async()=>{
  const h=harness(),sent=[];
  h.context.old=payload('18');h.run('state.pending={request:old,mode:"mock",submission_id:"SUB-OLD"};loadRun=async()=>{};');
  h.context.api=async(path,options)=>{sent.push(options.body);return {run:{run_id:'RUN-OLD'},reused:true};};
  await h.run('retryPendingSubmission()');
  assert.equal(sent[0].submission_id,'SUB-OLD');assert.equal(sent[0].request.request_id,'REQ-18');
});

function job(id){return {run_id:id,status:'FINISHED'};}
function page(id){return {events:[{run_id:id,sequence:1,event:{type:'run_started'}}],next_after:1,has_more:false};}
function bootstrap(){return {csrf_token:'token',runs:[],drafts:[],catalog:{materials:[]}};}

test('late events of A cannot enter selected B',async()=>{
  const h=harness(),hold=deferred(),entered=deferred();
  h.context.api=async path=>{if(path==='/api/runs/A')return job('A');if(path==='/api/runs/B')return job('B');if(path.includes('/A/events')){entered.resolve();await hold.promise;return page('A');}if(path.includes('/B/events'))return page('B');return bootstrap();};
  const a=h.run('loadRun("A",false)');await entered.promise;await h.run('loadRun("B",false)');hold.resolve();await a;
  assert.equal(h.run('state.job.run_id'),'B');assert.deepEqual(Array.from(h.run('state.events'),e=>e.run_id),['B']);
});

test('late metadata of A cannot replace selected B',async()=>{
  const h=harness(),hold=deferred(),entered=deferred();
  h.context.api=async path=>{if(path==='/api/runs/A'){entered.resolve();await hold.promise;return job('A');}if(path==='/api/runs/B')return job('B');if(path.includes('/A/events'))return page('A');if(path.includes('/B/events'))return page('B');return bootstrap();};
  const a=h.run('loadRun("A",false)');await entered.promise;await h.run('loadRun("B",false)');hold.resolve();await a;
  assert.equal(h.run('state.job.run_id'),'B');assert.deepEqual(Array.from(h.run('state.events'),e=>e.run_id),['B']);
});

test('overlapping refreshes cannot duplicate sequences',async()=>{
  const h=harness(),hold=deferred(),entered=deferred();let reads=0;
  h.context.api=async path=>{if(path==='/api/runs/A')return job('A');if(path.includes('/A/events')){if(reads++===0){entered.resolve();await hold.promise;}return page('A');}return bootstrap();};
  const first=h.run('loadRun("A",false)');await entered.promise;await h.run('loadRun("A",false)');hold.resolve();await first;
  assert.equal(h.run('state.events.length'),1);assert.equal(h.run('state.cursor'),1);
});
