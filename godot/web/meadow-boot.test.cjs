const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto, createHash} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname,'meadow-boot.js'),'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve=yes;reject=no;});
  return {promise,resolve,reject};
}

function fakeClock() {
  let now=0, id=0;
  const timers=new Map(), delays=[];
  return {
    now:()=>now, delays, pending:()=>timers.size,
    setTimeout(fn,ms){delays.push(ms);timers.set(++id,{fn,at:now+ms});return id;},
    clearTimeout(key){timers.delete(key);},
    elapse(ms){now+=ms;}, // Event loop busy: clock advances, timers not delivered.
    advance(ms){
      const end=now+ms;
      for (;;) {
        const next=[...timers].filter(([,row])=>row.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
        if (!next) break;
        now=Math.max(now,next[1].at);timers.delete(next[0]);next[1].fn();
      }
      now=end;
    }
  };
}

function abortable(promise, signal) {
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(signal.reason);
    if (signal.aborted) {abort();return;}
    signal.addEventListener('abort',abort,{once:true});
    Promise.resolve(promise).then(value=>{
      signal.removeEventListener('abort',abort);resolve(value);
    },error=>{
      signal.removeEventListener('abort',abort);reject(error);
    });
  });
}

function observe(promise) {
  const state={status:'pending'};
  promise.then(()=>{state.status='resolved';},error=>{state.status='rejected';state.error=error;});
  return state;
}

function noReady(h) {
  assert.equal(h.canvas.dataset.navigationReadyMs,undefined);
  assert.equal(h.canvas.dataset.coreReadyMs,undefined);
  assert(!h.calls.some(row=>row[0]==='mark'&&row[1]==='engineStartedMs'));
}

function harness() {
  const calls=[];
  const clock=fakeClock(), crypto={subtle:{digest:(...args)=>webcrypto.subtle.digest(...args)}};
  const payload = Uint8Array.from([1,2,3,4]);
  const sha = createHash('sha256').update(payload).digest('hex');
  const config={mainPack:'index-lite.pck',executable:'index',args:['--','--meadow-quality=lite'],
    fileSizes:{'index-lite.pck':4},bootstrap:{file:'bootstrap.pck',coreSha256:sha}};
  const downloaded=deferred(), marks=new Map();
  let signal;
  const window={meadowStream:{activate:(_,pack)=>calls.push(['stream',pack])}};
  vm.runInNewContext(source,{window,crypto,AbortController,performance:{now:clock.now},
    setTimeout:clock.setTimeout,clearTimeout:clock.clearTimeout,
    fetch:(url,options)=>{
      signal=options.signal;
      assert(signal instanceof AbortSignal,'Use a real AbortController/AbortSignal');
      assert.equal(options.credentials,'same-origin');
      calls.push(['fetch',url]);
      signal.addEventListener('abort',()=>calls.push(['abort']),{once:true});
      return abortable(downloaded.promise,signal);
    }});
  const api=window.meadowBoot;
  let markMounted;
  const waitMounted = new Promise(resolve => {markMounted=resolve;});
  const engine={init:async()=>{calls.push(['init']);},
    preloadFile:async(...args)=>{calls.push(['preload',...args]);},
    start:async ({args})=>{calls.push(['start',...args]);api.bind(file=>{calls.push(['mount',file]);markMounted();});},
    copyToFS:(file,bytes)=>calls.push(['copy',file,bytes.byteLength])};
  const canvas={dataset:{}};
  const options={onProgress:(...args)=>calls.push(['progress',...args])};
  const reply=({status=200,body=payload.buffer}={})=>downloaded.resolve({
    ok:status>=200&&status<300,status,arrayBuffer:()=>{
      calls.push(['body']);return abortable(body,signal);
    }});
  return {api,engine,config,canvas,calls,options,waitMounted,clock,crypto,reply,
    get signal(){return signal;},
    rejectFetch:downloaded.reject,
    finishCore(bytes=payload){reply({body:bytes.buffer});},
    waitMark(name){
      if (calls.some(row=>row[0]==='mark'&&row[1]===name)) return Promise.resolve();
      if (!marks.has(name)) marks.set(name,deferred());
      return marks.get(name).promise;
    },
    run(){return api.start(engine,config,options,canvas,name=>{
      calls.push(['mark',name]);marks.get(name)?.resolve();
    });}};
}

test('engine starts during the selected core download; boot never reports actual scene ready',async()=>{
  const h=harness();const run=h.run();await tick();
  assert(h.calls.some(row=>row[0]==='start'));
  assert(!h.calls.some(row=>row[0]==='copy'));
  assert.deepEqual(h.calls.find(row=>row[0]==='start'),['start','--main-pack','bootstrap.pck','--','--meadow-quality=lite']);
  assert.equal(h.canvas.dataset.navigationReadyMs,undefined);
  assert.equal(h.canvas.dataset.coreReadyMs,undefined);
  h.finishCore();await h.waitMounted;
  assert(h.calls.some(row=>row[0]==='copy'));
  assert(!h.calls.some(row=>row[0]==='mark'&&row[1]==='engineStartedMs'));
  h.api.mounted(true,'');await run;
  assert(h.calls.some(row=>row[0]==='mark'&&row[1]==='engineStartedMs'));
  assert.equal(h.canvas.dataset.coreReadyMs,undefined,'Real controls own scene/presentation readiness');
  assert.doesNotMatch(source,/\.sceneReady\s*\(/);
  assert.deepEqual(h.calls.filter(row=>row[0]==='fetch').map(row=>row[1]),['index-lite.pck']);
});

test('bad downloaded bytes never mount a core and surface failure instead of ready',async()=>{
  const h=harness();const run=h.run();await tick();h.finishCore(Uint8Array.from([4,3,2,1]));
  await assert.rejects(run,/校验/);
  assert(!h.calls.some(row=>row[0]==='copy'||row[0]==='mount'));
  assert.equal(h.canvas.dataset.coreReadyMs,undefined);
});

test('engine download has a head start, then CPU bootstrap overlaps core transfer',async()=>{
  const h=harness();let finishInit;
  h.engine.init=()=>{h.calls.push(['init']);return new Promise(resolve=>{finishInit=resolve;});};
  const run=h.run();await tick();
  assert.equal(h.canvas.dataset.downloadSchedule,'engine-first');
  assert(h.calls.some(row=>row[0]==='preload'&&row[1]==='bootstrap.pck'));
  assert(!h.calls.some(row=>row[0]==='fetch'||row[0]==='start'));
  finishInit();await tick();
  assert(h.calls.some(row=>row[0]==='fetch'&&row[1]==='index-lite.pck'));
  assert(h.calls.some(row=>row[0]==='start'));
  assert(!h.calls.some(row=>row[0]==='copy'));
  h.finishCore();await h.waitMounted;h.api.mounted(true,'');await run;
  assert.equal(h.canvas.dataset.coreReadyMs,undefined);
});

test('failed engine initialization never downloads a pack or reports success',async()=>{
  const h=harness();h.engine.init=async()=>{throw Error('synthetic init failed');};
  await assert.rejects(h.run(),/synthetic init failed/);
  assert(!h.calls.some(row=>row[0]==='fetch'||row[0]==='start'||row[0]==='copy'));
  assert.equal(h.canvas.dataset.coreReadyMs,undefined);
});

test('a rejected Godot scene mount does not resolve successful startup',async()=>{
  const h=harness();const run=h.run();await tick();h.finishCore();await h.waitMounted;
  h.api.mounted(false,'cannot mount');await assert.rejects(run,/cannot mount/);
  assert(!h.calls.some(row=>row[0]==='mark'&&row[1]==='engineStartedMs'));
});

test('original/balanced and malformed bootstrap identity are rejected before requests',async()=>{
  for (const mode of ['index.pck','index-balanced.pck']) {
    const h=harness();h.config.mainPack=mode;await assert.rejects(h.run(),/无效/);assert.equal(h.calls.length,0);
  }
  const h=harness();h.config.bootstrap.file='../bootstrap.pck';await assert.rejects(h.run(),/无效/);assert.equal(h.calls.length,0);
});

for (const phase of ['init','preload','start','bound','core','mount']) {
  test(`one overall deadline ends pending ${phase}; late completions cannot resume startup`,async()=>{
    const h=harness(), gate=deferred();
    if (phase==='init') h.engine.init=()=>gate.promise;
    if (phase==='preload') h.engine.preloadFile=()=>gate.promise;
    if (phase==='start') {
      const original=h.engine.start;
      h.engine.start=args=>original(args).then(()=>gate.promise);
    }
    if (phase==='bound') h.engine.start=async()=>{h.calls.push(['start']);};
    const outcome=observe(h.run());await tick();
    if (phase==='bound'||phase==='mount') {
      h.finishCore();await h.waitMark('packFetchedMs');
      if (phase==='mount') await h.waitMounted;
    }
    assert.equal(outcome.status,'pending');
    h.clock.advance(90000);await tick();
    assert.equal(outcome.status,'rejected');assert.match(outcome.error.message,/超时/);
    assert.deepEqual(h.clock.delays,[90000],'No separate bind/mount timer or renewed allowance');
    assert.equal(h.clock.pending(),0);
    if (phase==='init'||phase==='preload') assert.equal(h.signal,undefined);
    else assert.equal(h.signal.aborted,true,'Real core AbortSignal must be cancelled');
    const before=h.calls.slice();
    gate.resolve();h.finishCore();
    h.api.bind(file=>h.calls.push(['late-mount',file]));h.api.mounted(true,'');
    await tick();await tick();
    assert.deepEqual(h.calls,before,'No late download, copy, mount, progress or milestone');
    noReady(h);
  });
}

test('response body pending at deadline receives the real fetch abort signal',async()=>{
  const h=harness(), body=deferred();
  const outcome=observe(h.run());await tick();h.reply({body:body.promise});await tick();
  assert(h.calls.some(row=>row[0]==='body'));
  h.clock.advance(90000);await tick();
  assert.equal(outcome.status,'rejected');assert.match(outcome.error.message,/超时/);
  assert(h.signal instanceof AbortSignal);assert.equal(h.signal.aborted,true);
  assert.equal(h.signal.reason.name,'AbortError');
  body.resolve(Uint8Array.from([1,2,3,4]).buffer);await tick();
  assert(!h.calls.some(row=>row[0]==='copy'||row[0]==='mount'));
  noReady(h);assert.equal(h.clock.pending(),0);
});

test('non-cancellable late digest cannot report pack fetched or mount',async()=>{
  const h=harness(), digest=deferred();
  h.crypto.subtle.digest=()=>{h.calls.push(['digest']);return digest.promise;};
  const outcome=observe(h.run());await tick();h.finishCore();await tick();
  assert(h.calls.some(row=>row[0]==='digest'));
  h.clock.advance(90000);await tick();
  assert.equal(outcome.status,'rejected');
  const before=h.calls.slice();
  digest.resolve(Uint8Array.from(Buffer.from(h.config.bootstrap.coreSha256,'hex')).buffer);
  await tick();await tick();
  assert.deepEqual(h.calls,before);noReady(h);
});

test('time spent initializing consumes the same mount deadline, not another 90 seconds',async()=>{
  const h=harness(), init=deferred();h.engine.init=()=>init.promise;
  const outcome=observe(h.run());await tick();h.clock.advance(80000);init.resolve();await tick();
  h.finishCore();await h.waitMounted;
  h.clock.advance(9999);await tick();assert.equal(outcome.status,'pending');
  h.clock.advance(1);await tick();
  assert.equal(outcome.status,'rejected');assert.match(outcome.error.message,/超时/);
  assert.deepEqual(h.clock.delays,[90000]);assert.equal(h.clock.pending(),0);noReady(h);
});

test('an overdue promise cannot beat a timer whose event-loop delivery was delayed',async()=>{
  const h=harness(), init=deferred();h.engine.init=()=>init.promise;
  const outcome=observe(h.run());await tick();
  h.clock.elapse(90000); // Deliberately do not execute the timeout callback.
  init.resolve();await tick();
  assert.equal(outcome.status,'rejected');assert.match(outcome.error.message,/超时/);
  assert(!h.calls.some(row=>row[0]==='fetch'||row[0]==='start'));
  assert.equal(h.clock.pending(),0);noReady(h);
});

test('overdue bind and mounted callbacks cannot beat an undelivered deadline timer',async()=>{
  for (const phase of ['bind','mounted']) {
    const h=harness();
    if (phase==='bind') h.engine.start=async()=>{};
    const outcome=observe(h.run());await tick();h.finishCore();
    await h.waitMark('packFetchedMs');
    if (phase==='mounted') await h.waitMounted;
    h.clock.elapse(90000);
    if (phase==='bind') h.api.bind(file=>h.calls.push(['late-mount',file]));
    else h.api.mounted(true,'');
    await tick();
    assert.equal(outcome.status,'rejected');assert.match(outcome.error.message,/超时/);
    assert(!h.calls.some(row=>row[0]==='late-mount'));
    if (phase==='bind') assert(!h.calls.some(row=>row[0]==='copy'));
    assert.equal(h.signal.aborted,true);assert.equal(h.clock.pending(),0);noReady(h);
  }
});

test('deadline is rechecked after synchronous progress and filesystem callbacks',async()=>{
  for (const phase of ['progress','copy']) {
    const h=harness();
    if (phase==='progress') h.options.onProgress=()=>h.clock.elapse(90000);
    else h.engine.copyToFS=()=>{h.calls.push(['copy']);h.clock.elapse(90000);};
    const run=h.run();await tick();h.finishCore();
    await assert.rejects(run,/超时/);
    assert(!h.calls.some(row=>row[0]==='mount'));
    if (phase==='progress') assert(!h.calls.some(row=>row[0]==='copy'));
    assert.equal(h.clock.pending(),0);noReady(h);
  }
});

test('core failure immediately releases pending engine.start rather than waiting for its deadline',async()=>{
  const h=harness(), start=deferred();h.engine.start=()=>start.promise;
  const run=h.run();await tick();h.rejectFetch(Error('synthetic connection lost'));
  await assert.rejects(run,/synthetic connection lost/);
  assert.equal(h.clock.now(),0);assert.equal(h.clock.pending(),0);assert.equal(h.signal.aborted,true);
  const before=h.calls.slice();start.resolve();await tick();
  assert.deepEqual(h.calls,before);noReady(h);
});

test('exceptional init, preload, start, HTTP, length, copy and bridge paths clean up without success',async()=>{
  for (const phase of ['init-sync','preload','start-sync','start-reject','http','length','copy','bridge']) {
    const h=harness();
    if (phase==='init-sync') h.engine.init=()=>{throw Error('synthetic init');};
    if (phase==='preload') h.engine.preloadFile=async()=>{throw Error('synthetic preload');};
    if (phase==='start-sync') h.engine.start=()=>{throw Error('synthetic start');};
    if (phase==='start-reject') h.engine.start=async()=>{throw Error('synthetic start');};
    if (phase==='copy') h.engine.copyToFS=()=>{throw Error('synthetic copy');};
    if (phase==='bridge') h.engine.start=async()=>h.api.bind(()=>{throw Error('synthetic bridge');});
    const run=h.run();
    const rejected=assert.rejects(run,phase==='http'?/404/:phase==='length'?/校验/:/synthetic/);
    await tick();
    if (phase==='http') h.reply({status:404});
    else h.finishCore(phase==='length'?Uint8Array.from([1,2,3]):undefined);
    await rejected;
    assert.equal(h.clock.pending(),0,phase);
    if (h.signal) assert.equal(h.signal.aborted,true,phase);
    noReady(h);
  }
});

test('late engine rejections and a missing bind produce no unhandled rejection',async()=>{
  const unhandled=[];const listener=error=>unhandled.push(error);
  process.on('unhandledRejection',listener);
  try {
    for (const phase of ['init','preload','start']) {
      const h=harness(), gate=deferred();
      const name=phase==='preload'?'preloadFile':phase;
      h.engine[name]=()=>gate.promise;
      const outcome=observe(h.run());await tick();h.clock.advance(90000);await tick();
      assert.equal(outcome.status,'rejected');
      gate.reject(Error(`late ${phase} rejection`));await tick();await tick();
      assert.equal(h.clock.pending(),0);noReady(h);
    }
    assert.deepEqual(unhandled,[]);
  } finally {process.removeListener('unhandledRejection',listener);}
});

test('untagged bridge callbacks cannot cross into a second startup in the same page',async()=>{
  const h=harness(), init=deferred();h.engine.init=()=>init.promise;
  const first=observe(h.run());await tick();
  const before=h.calls.slice();
  await assert.rejects(h.run(),/刷新/);assert.deepEqual(h.calls,before);
  h.clock.advance(90000);await tick();assert.equal(first.status,'rejected');
  await assert.rejects(h.run(),/刷新/);
  const closed=h.calls.slice();
  init.resolve();h.api.bind(file=>h.calls.push(['late-mount',file]));h.api.mounted(true,'');
  await tick();await tick();assert.deepEqual(h.calls,closed);noReady(h);
});
