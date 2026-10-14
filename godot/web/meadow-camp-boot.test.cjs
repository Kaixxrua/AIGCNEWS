/* Focused read-only camp-wrapper startup regression.
 * Executes frozen v153's PUBLIC Engine JS and the current shared boot/loader/
 * controls (plus integration in gate tests). No WASM instantiation, network,
 * scene export, image edits, or actual filesystem writes from Engine.copyToFS.
 * Small deterministic TEST buffers use real WebCrypto SHA-256, distinct for
 * every selected tier. These are NOT scene PCKs or a Web performance result.
 * Actual frozen scene/settings hashes are separately verified by the explicit
 * build_camp_bootstrap.py --actual-core-test --native-twin report.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, webcrypto} = require('node:crypto');
const bridge = require('./meadow-camp-bridge.js');
const sources = Object.fromEntries(['boot', 'loader', 'controls', 'camp-integration'].map(name =>
  [name, fs.readFileSync(path.join(__dirname, `meadow-${name}.js`), 'utf8')]));
const shipped = fs.readFileSync(path.resolve(__dirname, '../../artifacts/v153/index.js'), 'utf8');
const offset = shipped.indexOf('const InternalConfig = function');
assert.ok(offset > 0, 'Expected frozen public Engine/config definitions, after generated WASM runtime');
const publicEngine = shipped.slice(offset);
assert.ok(!publicEngine.includes('var Godot='), 'Never evaluate the generated WASM runtime');
const tiers = {original:'index.pck', balanced:'index-balanced.pck', lite:'index-lite.pck'};
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const tick = () => new Promise(resolve => setImmediate(resolve));

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
async function until(predicate) {
  for (let index = 0; index < 150; index++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 2));
  }
  assert.fail('Bounded asynchronous startup checkpoint was not reached');
}
function clock() {
  let now = 0, serial = 0;
  const timers = new Map(), delays = [];
  return {now:() => now, timers, delays,
    setTimeout(fn, ms) { const id = ++serial; timers.set(id, {fn, at:now + ms}); delays.push(ms); return id; },
    clearTimeout(id) { timers.delete(id); },
    elapse(ms) { now += ms; },
    advance(ms) {
      now += ms;
      for (const [id, row] of [...timers]) if (row.at <= now) { timers.delete(id); row.fn(); }
    }};
}
function abortable(promise, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    if (signal.aborted) { abort(); return; }
    signal.addEventListener('abort', abort, {once:true});
    Promise.resolve(promise).then(value => {
      signal.removeEventListener('abort', abort); resolve(value);
    }, error => { signal.removeEventListener('abort', abort); reject(error); });
  });
}
function fixtureBindings() {
  const bodies = new Map(), variants = {};
  for (const variant of ['full', 'lite']) {
    const bytes = Buffer.from(`TEST wrapper ${variant}`);
    const sha256 = hash(bytes), file = `camp-bootstrap-${variant}-${sha256.slice(0,12)}.pck`;
    bodies.set(file, bytes); variants[variant] = {file, bytes:bytes.length, sha256};
  }
  const config = {version:1, source:'frozen-v153', bindings:{}, actorShards:[],
    assetIds:{hero:['hero/ranger'], pet:['pet/deer'], boss:['boss/guardian']}};
  for (const [tier, file] of Object.entries(tiers)) {
    // Equal length exposes wrong-tier responses to SHA validation, not size.
    const bytes = Buffer.from(`TEST core ${tier.padEnd(8, '_')}`), sha256 = hash(bytes);
    bodies.set(file, bytes);
    const variant = tier === 'lite' ? 'lite' : 'full';
    config.bindings[tier] = {mainPack:file, selectedPack:{file, bytes:bytes.length, sha256},
      bootstrap:{...variants[variant]}, settingsVariant:variant, progressive:tier === 'lite', coreSha256:sha256};
  }
  const bytes = Buffer.from('TEST optional renderer'), sha256 = hash(bytes);
  config.optionalPack = {file:`camp-presentation-${sha256.slice(0,12)}.pck`, bytes:bytes.length, sha256};
  bodies.set(config.optionalPack.file, bytes);
  return {config, bodies};
}

function harness(tier = 'lite', settings = {}) {
  const fixture = fixtureBindings(), calls = [], files = new Map(), elements = new Map(), rafs = [], errors = [];
  const time = clock(), requests = new Map(), wasm = deferred(), filesystem = deferred();
  const binding = fixture.config.bindings[tier];
  const config = {executable:'index', mainPack:binding.mainPack, progressive:binding.progressive,
    campPresentation:true, args:['--', `--meadow-quality=${tier}`],
    fileSizes:{'index.wasm':1, ...Object.fromEntries(Object.values(fixture.config.bindings).map(b => [b.mainPack,b.selectedPack.bytes]))},
    bootstrap:{...binding.bootstrap, kind:'camp-wrapper', selectedPack:{...binding.selectedPack},
      coreSha256:binding.coreSha256, settingsVariant:binding.settingsVariant}};
  const record = (type, ...args) => calls.push({type, args, at:time.now()});
  class Element {
    constructor(id) { Object.assign(this, {id, dataset:{}, attributes:{}, handlers:{}, disabled:true,
      hidden:false, tabIndex:0, tagName:id === 'canvas' ? 'CANVAS' : 'BUTTON'}); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, fn) { this.handlers[name] = fn; }
  }
  const element = id => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  const document = {body:{dataset:{}}, visibilityState:'visible', getElementById:element,
    getElementsByTagName:() => [element('canvas')], addEventListener() {}, removeEventListener() {}};
  const events = {}, parentMessages = [];
  const window = {document, performance:{now:time.now, getEntriesByType:() => []}, crypto:webcrypto,
    location:{origin:'https://camp.test', search:'?camp=1', reload:() => record('reload')},
    parent:{postMessage:(data, origin) => parentMessages.push({data,origin})},
    matchMedia:() => ({matches:false, addEventListener() {}}),
    addEventListener:(name, fn) => { events[name] = fn; }, removeEventListener:name => { delete events[name]; },
    queueMicrotask, setTimeout:time.setTimeout, clearTimeout:time.clearTimeout,
    requestAnimationFrame:fn => { rafs.push({fn, kind:'presentation'}); },
    meadowStream:{activate:(_engine, pack) => record('stream', pack), corePresented:() => record('detail-gate')},
    meadowDetailStatus:{}, meadowStartupTrace:{install() {}, mark:name => record('mark',name), finish:() => record('trace-finish')}};
  const h = {calls, files, config, fixture, window, time, rafs, errors, requests, events, wasm, filesystem, parentMessages, element,
    engine:null, engines:[], autoBind:true, engineMutator:null, onCopy:null,
    count:type => calls.filter(row => row.type === type).length,
    rows:type => calls.filter(row => row.type === type),
    reply(file, {body=fixture.bodies.get(file), status=200} = {}) {
      assert.ok(requests.has(file), `Requested ${file} before test supplies its response`);
      requests.get(file).reply.resolve({status, body});
    },
    replyBoot(value) { h.reply(h.config.bootstrap.file, value); },
    replyCore(value) { h.reply(h.config.mainPack, value); },
    bind() { window.meadowBoot.bind(file => { record('mount',file); }); },
    frame() { for (const row of rafs.splice(0)) { record('raf',row.kind); row.fn(time.now()); } },
    presentationFrames:() => rafs.filter(row => row.kind === 'presentation').length,
    run() { return window.meadowLoader.start(config, {onProgress:(...args) => record('progress',...args)}, element('canvas')); },
    startUI() { window.meadowTimeUI.start(config); },
    noReady() {
      assert.equal(element('canvas').dataset.navigationReadyMs, undefined);
      assert.equal(h.count('camp-gate'), 0);
      assert.equal(h.count('detail-gate'), 0);
    }};
  const fetch = (file, init) => {
    record('fetch', file, init);
    assert.ok(init.signal instanceof AbortSignal);
    assert.ok(fixture.bodies.has(file), `Only pinned test pack requests: ${file}`);
    assert.ok(!requests.has(file), `No duplicate download: ${file}`);
    const reply = deferred(); requests.set(file, {reply, signal:init.signal});
    return abortable(reply.promise, init.signal).then(({status, body}) => {
      if (body && typeof body.then === 'function') return {
        ok:status >= 200 && status < 300, status,
        arrayBuffer:() => { record('body',file); return abortable(body, init.signal); }};
      const response = new Response(body, {status});
      const read = response.arrayBuffer.bind(response);
      response.arrayBuffer = () => { record('body',file); return read(); };
      return response;
    });
  };
  window.fetch = fetch;
  const crypto = {subtle:{digest:(algorithm, bytes) => { record('digest',hash(Buffer.from(bytes))); return webcrypto.subtle.digest(algorithm,bytes); }}};
  h.crypto = crypto;
  class Preloader {
    constructor() { this.preloadedFiles = []; }
    loadPromise(file) { record('wasm-fetch',file); return wasm.promise.then(() => new Response(new Uint8Array([0]))); }
    preload(file, destination) { record('preload',file,destination); return Promise.resolve(); }
    setProgressFunc() {}
    animateProgress() {}
  }
  const module = {
    initFS() { record('initFS'); return filesystem.promise; },
    initConfig(value) { record('initConfig'); h.nativeConfig = value; },
    copyToFS(file, bytes) { record('copy',file,hash(Buffer.from(bytes))); h.onCopy?.(file,bytes); files.set(file,Buffer.from(bytes)); },
    callMain(args) { record('main',...Array.from(args)); if (h.autoBind) h.bind(); }
  };
  const shared = {window, document, crypto, AbortController, performance:window.performance,
    setTimeout:time.setTimeout, clearTimeout:time.clearTimeout, fetch, Response, URL, URLSearchParams,
    HTMLCanvasElement:Element, navigator:{languages:['en-US']},
    requestAnimationFrame:fn => rafs.push({fn,kind:'progress'}),
    console:{info() {}, log() {}, warn:(...args) => record('warn',...args), error:error => errors.push(error)}};
  vm.runInNewContext(publicEngine, {...shared, Preloader, Features:{getMissingFeatures:() => []},
    Godot:() => { record('module'); return Promise.resolve(module); },
    WebAssembly:{instantiate:() => assert.fail('No actual WASM'), instantiateStreaming:() => assert.fail('No actual WASM')}},
    {filename:'frozen-v153-public-engine.js'});
  const PublicEngine = window.Engine;
  function Engine(options) {
    const engine = new PublicEngine(options); h.engine = engine; h.engines.push(engine); record('engine');
    for (const name of ['init', 'start', 'preloadFile', 'copyToFS']) {
      const original = engine[name].bind(engine);
      engine[name] = (...args) => { record(`engine-${name}`,...(name === 'copyToFS' ? [args[0]] : args)); return original(...args); };
    }
    h.engineMutator?.(engine); return engine;
  }
  Engine.getMissingFeatures = () => [];
  vm.runInNewContext(sources.boot + sources.loader + sources.controls, {...shared, Engine}, {filename:'shared-camp-startup.js'});
  if (settings.integration) {
    window.MeadowCampBridge = {
      create:cfg => bridge.create(cfg,window), createMountClient:cfg => bridge.createMountClient(cfg,window),
      createActorLoader:cfg => bridge.createActorLoader(cfg,window), loadPackAfterCore:cfg => bridge.loadPackAfterCore(cfg,window)};
    vm.runInNewContext(sources['camp-integration'], shared, {filename:'shared-camp-integration.js'});
    assert.equal(window.meadowCampIntegration.initialize(fixture.config), true);
    const actualGate = window.meadowCampIntegration.corePresented;
    h.nativeCalls = [];
    window.meadowCampMount.bind((...args) => { h.nativeCalls.push(args); record('native-camp',...args); });
    // Observe rather than replace the frozen owner method.
    const api = window.meadowCampIntegration;
    window.meadowCampIntegration = {...api, corePresented:() => { record('camp-gate'); actualGate(); }};
  } else {
    window.meadowCampIntegration = {attachEngine:(...args) => record('attach',...args), corePresented:() => record('camp-gate')};
  }
  if (!settings.deferInit) wasm.resolve();
  if (!settings.deferFS) filesystem.resolve();
  return h;
}

async function startBootstrap(h) {
  await until(() => h.requests.has(h.config.bootstrap.file));
  h.replyBoot();
  await until(() => h.count('main') === 1);
}
async function mountCore(h) {
  h.replyCore();
  await until(() => h.count('mount') === 1);
}
async function finish(h, run) {
  await mountCore(h); h.window.meadowBoot.mounted(true,'scene_entered'); await run;
  assert.equal(h.time.timers.size, 0);
}

for (const tier of Object.keys(tiers)) {
  test(`${tier}: actual public Engine init/fetch/copy/start preserves selected SHA and only its settings wrapper`, async () => {
    const h = harness(tier), run = h.run(); await startBootstrap(h);
    const spec = h.config.bootstrap;
    assert.equal(h.count('engine'), 1); assert.equal(h.count('attach'), 1);
    assert.equal(h.count('wasm-fetch'), 1); assert.equal(h.count('preload'), 0);
    assert.deepEqual(h.rows('fetch').map(row => row.args[0]), [spec.file,tiers[tier]]);
    assert.equal(h.rows('fetch').every(row => row.args[1].credentials === 'same-origin'), true);
    assert.deepEqual(h.rows('copy').map(row => row.args), [[spec.file,spec.sha256]]);
    assert.deepEqual(h.rows('main')[0].args, ['--main-pack',spec.file,'--',`--meadow-quality=${tier}`]);
    assert.equal(h.count('stream'), tier === 'lite' ? 1 : 0);
    assert.equal(h.config.progressive, tier === 'lite');
    assert.ok(h.calls.findIndex(row => row.type === 'initFS') < h.calls.findIndex(row => row.type === 'copy'));
    assert.ok(h.calls.findIndex(row => row.type === 'copy') < h.calls.findIndex(row => row.type === 'main'));
    h.noReady();
    await mountCore(h);
    assert.equal(hash(h.files.get('/meadow-core.pck')), spec.selectedPack.sha256);
    assert.deepEqual(h.rows('copy').map(row => row.args[0]), [spec.file,'/meadow-core.pck']);
    assert.equal(h.element('canvas').dataset.engineStartedMs, undefined);
    h.window.meadowBoot.mounted(true,'scene_entered'); await run;
    assert.ok(h.element('canvas').dataset.engineStartedMs !== undefined);
    h.noReady(); assert.equal(h.count('engine-start'), 1); assert.equal(h.time.timers.size, 0);
  });
  test(`${tier}: another quality tier's same-length bytes cannot pass selected core SHA`, async () => {
    const h = harness(tier), run = h.run(), rejected = assert.rejects(run,/校验/);
    await startBootstrap(h);
    const another = Object.keys(tiers).find(value => value !== tier);
    h.replyCore({body:h.fixture.bodies.get(tiers[another])}); await rejected;
    assert.equal(h.files.has('/meadow-core.pck'), false); assert.equal(h.count('mount'), 0);
    assert.equal(h.element('canvas').dataset.packFetchedMs, undefined); h.noReady();
    assert.equal(h.time.timers.size, 0);
  });
}

test('full tiers share their settings wrapper but all three selected scene hashes differ', () => {
  const {config} = fixtureBindings();
  assert.deepEqual(config.bindings.original.bootstrap, config.bindings.balanced.bootstrap);
  assert.notEqual(config.bindings.original.bootstrap.sha256, config.bindings.lite.bootstrap.sha256);
  assert.equal(new Set(Object.values(config.bindings).map(row => row.coreSha256)).size, 3);
});

test('wrapper may download alongside init, but neither wrapper copy nor core transfer can precede real FS init', async () => {
  const h = harness('lite',{deferFS:true}), run = h.run();
  await until(() => h.requests.has(h.config.bootstrap.file) && h.count('initFS') === 1);
  h.replyBoot(); await until(() => h.count('digest') === 1); await tick();
  assert.equal(h.count('copy'), 0); assert.equal(h.count('main'), 0); assert.equal(h.requests.size, 1);
  h.filesystem.resolve(); await until(() => h.count('main') === 1);
  await finish(h,run); h.noReady();
});

test('engine initialization alone cannot start an unverified or still-downloading wrapper', async () => {
  const h = harness('balanced'), run = h.run();
  await until(() => h.count('initFS') === 1); await tick();
  assert.equal(h.count('copy'), 0); assert.equal(h.count('main'), 0); assert.equal(h.requests.size, 1);
  h.replyBoot(); await until(() => h.count('main') === 1); await finish(h,run);
});

test('invalid wrapper/selected-pack identity is rejected before boot init/fetch/copy/start', async () => {
  const mutations = [
    c => { c.campPresentation = false; }, c => { c.mainPack = 'foreign.pck'; },
    c => { c.bootstrap.settingsVariant = 'full'; }, c => { c.bootstrap.file = '../outside.pck'; },
    c => { c.bootstrap.bytes = 128 * 1024; }, c => { c.bootstrap.bytes = 0; },
    c => { c.bootstrap.sha256 = 'f'.repeat(64); }, c => { c.bootstrap.coreSha256 = 'x'.repeat(64); },
    c => { c.bootstrap.selectedPack.file = 'index.pck'; },
    c => { c.bootstrap.selectedPack.bytes++; }, c => { c.bootstrap.selectedPack.sha256 = '0'.repeat(64); },
    c => { c.bootstrap.selectedPack = null; }
  ];
  for (const mutate of mutations) {
    const h = harness(); mutate(h.config);
    await assert.rejects(h.run(),/无效/);
    for (const type of ['engine-init','fetch','copy','main','mount']) assert.equal(h.count(type),0,type);
    assert.equal(h.time.timers.size,0); h.noReady();
  }
});

for (const mode of ['http','length','hash']) {
  test(`bad wrapper ${mode} cannot enter FS, start engine main or fetch selected core`, async () => {
    const h = harness(), run = h.run(), rejected = assert.rejects(run,/启动文件/);
    await until(() => h.requests.has(h.config.bootstrap.file));
    const bytes = Buffer.from(h.fixture.bodies.get(h.config.bootstrap.file)); bytes[0] ^= 1;
    h.replyBoot(mode === 'http' ? {status:503} : {body:mode === 'length' ? bytes.subarray(1) : bytes});
    await rejected;
    assert.equal(h.count('copy'),0); assert.equal(h.count('main'),0); assert.equal(h.requests.size,1);
    assert.equal(h.time.timers.size,0); h.noReady();
  });
}

test('selected core HTTP/length rejection releases startup without a scene mount', async () => {
  for (const mode of ['http','length']) {
    const h = harness(), run = h.run(), rejected = assert.rejects(run,/场景/);
    await startBootstrap(h); h.replyCore(mode === 'http' ? {status:404} : {body:new Uint8Array([1])}); await rejected;
    assert.equal(h.files.has('/meadow-core.pck'),false); assert.equal(h.count('mount'),0); h.noReady();
    assert.equal(h.time.timers.size,0);
  }
});

test('Godot rejection and duplicate startup cannot become ready or reuse disposed boot callbacks', async () => {
  const h = harness(), run = h.run(), rejected = assert.rejects(run,/selected_pack_pin/);
  await startBootstrap(h); await mountCore(h);
  h.window.meadowBoot.mounted(false,'selected_pack_pin'); await rejected;
  h.window.meadowBoot.mounted(true,'scene_entered'); h.window.meadowBoot.bind(() => assert.fail('Closed callback'));
  assert.equal(h.element('canvas').dataset.engineStartedMs,undefined); h.noReady();
  const counts = ['engine-init','fetch','copy','main'].map(type => h.count(type));
  await assert.rejects(h.run(),/刷新/);
  assert.deepEqual(['engine-init','fetch','copy','main'].map(type => h.count(type)),counts);
});

for (const phase of ['wrapper-fetch','wrapper-body','init','bind','core','mount']) {
  test(`single 90s deadline covers ${phase}; late work cannot resume camp-wrapper startup`, async () => {
    const h = harness('lite',{deferInit:phase === 'init'}), body = deferred();
    if (phase === 'bind') h.autoBind = false;
    const run = h.run(), rejected = assert.rejects(run,/超时/);
    await until(() => h.requests.has(h.config.bootstrap.file));
    if (phase === 'wrapper-body') h.replyBoot({body:body.promise});
    else if (phase !== 'wrapper-fetch') h.replyBoot();
    if (['bind','core','mount'].includes(phase)) await until(() => h.count('main') === 1);
    if (['bind','mount'].includes(phase)) {
      h.replyCore(); await until(() => h.element('canvas').dataset.packFetchedMs !== undefined);
      if (phase === 'mount') await until(() => h.count('mount') === 1);
    }
    h.time.advance(90000); await rejected;
    assert.deepEqual(h.time.delays,[90000]); assert.equal(h.time.timers.size,0);
    assert.ok([...h.requests.values()].every(row => row.signal.aborted));
    const before = h.calls.length;
    h.wasm.resolve(); body.resolve(new ArrayBuffer(1));
    for (const [file, request] of h.requests) request.reply.resolve({body:h.fixture.bodies.get(file),status:200});
    h.window.meadowBoot.bind(() => recordLate()); h.window.meadowBoot.mounted(true,'scene_entered');
    function recordLate() { assert.fail('Late mount must not run'); }
    await tick(); await tick();
    // The underlying uncancellable engine init may finish, but the boot must
    // not perform any new download/copy/main/mount/progress milestone.
    assert.equal(h.calls.slice(before).some(row => ['fetch','copy','main','mount','progress','mark'].includes(row.type)),false);
    assert.equal(h.element('canvas').dataset.engineStartedMs,undefined); h.noReady();
  });
}

test('wrapper digest or copy cannot beat an overdue timer whose callback has not run', async () => {
  for (const phase of ['digest','copy']) {
    const h = harness(), pending = deferred();
    if (phase === 'digest') h.crypto.subtle.digest = () => pending.promise;
    else h.onCopy = () => h.time.elapse(90000);
    const run = h.run(), rejected = assert.rejects(run,/超时/);
    await until(() => h.requests.has(h.config.bootstrap.file)); h.replyBoot();
    if (phase === 'digest') {
      await until(() => h.count('body') === 1); h.time.elapse(90000);
      pending.resolve(Uint8Array.from(Buffer.from(h.config.bootstrap.sha256,'hex')).buffer);
    }
    await rejected;
    assert.equal(h.requests.size,1); assert.equal(h.count('main'),0); h.noReady();
    assert.equal(h.time.timers.size,0);
  }
});

for (const order of ['scene-first','engine-first']) {
  test(`real controls ${order}: engine/scene + two RAFs + independent native ack gate optional download`, async () => {
    const h = harness('lite',{integration:true}); h.startUI(); await startBootstrap(h);
    if (order === 'scene-first') h.window.meadowTimeUI.sceneReady(25);
    assert.equal(h.presentationFrames(),0); h.noReady();
    await mountCore(h); h.window.meadowBoot.mounted(true,'scene_entered');
    await until(() => h.element('canvas').dataset.engineStartedMs !== undefined); await tick();
    if (order === 'engine-first') { assert.equal(h.presentationFrames(),0); h.window.meadowTimeUI.sceneReady(25); }
    assert.equal(h.presentationFrames(),1); h.noReady();
    const optional = h.fixture.config.optionalPack;
    assert.equal(h.requests.has(optional.file),false);
    h.time.elapse(100); h.frame(); h.noReady(); assert.equal(h.presentationFrames(),1);
    h.time.elapse(16); h.frame();
    assert.equal(h.element('loading').hidden,true); assert.equal(h.count('camp-gate'),1);
    assert.equal(h.element('canvas').dataset.navigationReadyMs,'116');
    assert.deepEqual(h.nativeCalls,[['core_presented']]); assert.equal(h.requests.has(optional.file),false);
    assert.equal(h.window.meadowCampMount.coreAccepted(true,'core_presented'),true);
    await until(() => h.requests.has(optional.file)); h.reply(optional.file);
    await until(() => h.nativeCalls.some(row => row[0] === 'mount'));
    const request = h.nativeCalls.find(row => row[0] === 'mount');
    assert.deepEqual(request.slice(2),['/' + optional.file,optional.sha256]);
    assert.equal(h.window.meadowCampMount.applied(request[1],true,'applied'),true); await tick();
    assert.equal(h.engines.length,1); assert.equal(h.count('main'),1); assert.equal(h.time.timers.size,0);
    h.events.pagehide();
  });
}

test('native core refusal leaves the usable world visible and never downloads the optional runtime', async () => {
  const h = harness('lite',{integration:true}); h.startUI(); await startBootstrap(h);
  await mountCore(h); h.window.meadowBoot.mounted(true,'scene_entered');
  await until(() => h.element('canvas').dataset.engineStartedMs !== undefined); await tick();
  h.window.meadowTimeUI.sceneReady(30); h.frame(); h.frame();
  h.window.meadowCampMount.coreAccepted(false,'not_ready'); await tick();
  assert.equal(h.requests.size,2); assert.equal(h.element('loading').hidden,true);
  assert.equal(h.engines.length,1); assert.equal(h.count('reload'),0);
  assert.equal(h.element('canvas').dataset.campStatus,'error'); assert.equal(h.time.timers.size,0);
  h.events.pagehide();
});
