const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const crypto = require('node:crypto');
const code = fs.readFileSync(__dirname+'/meadow-stream.js','utf8');
const tick = () => new Promise(r=>setImmediate(r));
// WebCrypto resolves on a worker; an arbitrary five event-loop ticks is not
// evidence that hashing finished when the whole suite runs concurrently.
async function until(predicate, label) {
  const deadline=Date.now()+3000;
  while(!predicate()) {
    assert.ok(Date.now()<deadline,`Timed out waiting for real test state: ${label}`);
    await new Promise(resolve=>setTimeout(resolve,1));
  }
}
function setup() {
  const frames=[], timers=new Map(), calls=[]; let timer=0, failure=false;
  const body = new Uint8Array([1,2,3]);
  const hash=crypto.createHash('sha256').update(body).digest('hex');
  const manifest={version:1,chunks:[{index:0,file:`detail-0-${hash.slice(0,12)}.pck`,bytes:3,sha256:hash}]};
  const canvas={dataset:{navigationReadyMs:'8000'}};
  const ui={loading:v=>calls.push(['loading',v]),applying:()=>calls.push(['applying']),complete:()=>calls.push(['complete']),fail:cb=>{ui.retry=cb;calls.push(['error']);}};
  const engine={copyToFS:(...v)=>calls.push(['copy',...v])};
  const window={performance:{now:()=>8100},requestAnimationFrame:fn=>frames.push(fn),
    setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id),
    crypto:crypto.webcrypto, meadowDetailStatus:{create:()=>ui}, meadowLoader:{report:()=>{}},
    fetch:async file=>{calls.push(['fetch',file]);if(failure)throw Error('network');return {ok:true,arrayBuffer:async()=>body.buffer};}};
  vm.runInNewContext(code,{window,document:{body:{}},console:{warn:()=>{}},AbortController,Uint8Array,ArrayBuffer,Error,JSON,Set,Number,Promise});
  const api=window.meadowStream;
  return {api,window,canvas,manifest,frames,timers,calls,ui,engine,setFailure:v=>failure=v,
    bind:()=>api.bind(JSON.stringify(manifest),(index,path)=>calls.push(['apply',index,path]))};
}
test('no detail fetch before actual core presentation, and original stays idle',async()=>{
  const s=setup();s.api.activate(s.engine,'index.pck',s.canvas);s.bind();s.api.corePresented();await tick();assert.equal(s.calls.length,0);
  s.api.activate(s.engine,'index-lite.pck',s.canvas);s.bind();await tick();assert.equal(s.calls.length,0);
  s.api.corePresented();assert.equal(s.calls.length,0);assert.equal(s.frames.length,1);
  s.frames.shift()();await tick();await tick();assert.equal(s.calls.filter(x=>x[0]==='fetch').length,1);
});
test('network/hash/copy do not mark complete; only real matching Godot ack does',async()=>{
  const s=setup();s.api.activate(s.engine,'index-lite.pck',s.canvas);s.bind();s.api.corePresented();s.frames.shift()();
  await until(()=>s.calls.some(x=>x[0]==='apply'),'matching Godot apply callback');
  assert(s.calls.some(x=>x[0]==='copy'));assert(s.calls.some(x=>x[0]==='apply'));assert(!s.calls.some(x=>x[0]==='complete'));
  s.api.applied(1,true,'');await tick();assert(!s.calls.some(x=>x[0]==='complete'));
  s.api.applied(0,true,'');await tick();s.frames.shift()();await tick();
  assert.equal(s.canvas.dataset.detailStatus,'complete');assert.equal(s.canvas.dataset.coreReadyMs,'8000');assert.equal(s.canvas.dataset.detailChunksApplied,'1');
});
test('network failure keeps core active and retry resumes single flight',async()=>{
  const s=setup();s.setFailure(true);s.api.activate(s.engine,'index-lite.pck',s.canvas);s.bind();s.api.corePresented();s.frames.shift()();await tick();
  assert.equal(s.canvas.dataset.detailStatus,'error');assert.equal(s.canvas.dataset.navigationReadyMs,'8000');
  s.setFailure(false);const attempt=s.ui.retry();s.ui.retry();
  await until(()=>s.calls.some(x=>x[0]==='apply'),'retry finishes real WebCrypto hash');
  assert.equal(s.calls.filter(x=>x[0]==='fetch').length,2);s.api.applied(0,true,'');
  await until(()=>s.frames.length===1,'actual ack schedules next frame');s.frames.shift()();await attempt;
  assert.equal(s.canvas.dataset.detailStatus,'complete');
});
test('malformed/remote manifest and corrupt bytes are rejected',async()=>{
  const s=setup();s.api.activate(s.engine,'index-lite.pck',s.canvas);
  for(const file of ['https://example.com/a.pck','../detail-0-abcdefabcdef.pck','detail-0-notahash.pck']){
    const m=structuredClone(s.manifest);m.chunks[0].file=file;assert.throws(()=>s.api.bind(JSON.stringify(m),()=>{}));
  }
  s.manifest.chunks[0].sha256='0'.repeat(64);
  assert.throws(()=>s.bind(),/标识/);
  s.manifest.chunks[0].file='detail-0-000000000000.pck';
  s.bind();s.api.corePresented();s.frames.shift()();
  await until(()=>s.canvas.dataset.detailStatus==='error','real corrupt-byte hash rejection');
  assert.equal(s.canvas.dataset.detailStatus,'error');assert(!s.calls.some(x=>x[0]==='copy'));
});
