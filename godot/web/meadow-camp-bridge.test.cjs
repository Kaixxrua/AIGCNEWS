'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto, createHash} = require('node:crypto');
const bridge = require('./meadow-camp-bridge.js');
const origin = 'https://camp.example.test';
const ids = {hero:['hero-ranger'], pet:['pet-fox'], boss:['boss-guardian']};
const display = () => ({mode:'fighting', heroAssetId:ids.hero[0], petAssetId:ids.pet[0],
  bossAssetId:ids.boss[0], elapsed:12, duration:600, roundId:'round-public-1'});
const hpDisplay = (mode = 'fighting') => ({...display(), mode,
  bossHp:mode === 'defeated' ? 0 : 725, bossMaxHp:1000});
const modeDisplay = mode => mode === 'defeated' ? hpDisplay(mode) : {...display(), mode};
const demoDisplay = () => ({...display(), mode:'demo', elapsed:0, duration:0, roundId:''});
function fixture(config = {}) {
  const listeners = new Set(), sent = [], delivered = [], microtasks = [];
  let now = 0;
  const parent = {postMessage:(data, target) => sent.push({data, target})};
  const host = {parent, crypto:webcrypto, performance:{now:() => now},
    queueMicrotask:callback => microtasks.push(callback),
    addEventListener:(_type, callback) => listeners.add(callback),
    removeEventListener:(_type, callback) => listeners.delete(callback)};
  const api = bridge.create({allowedParentOrigin:origin, assetIds:ids, ...config}, host);
  const session = sent[0].data.session;
  const message = (snapshot = display(), sequence = 1) => ({protocol:bridge.PROTOCOL,
    version:1, type:'snapshot', session, sequence, snapshot});
  const send = (data, overrides = {}) => {
    for (const listener of listeners) listener({data, source:parent, origin, ...overrides});
  };
  const bind = value => delivered.push(JSON.parse(value));
  api.bind(bind);
  return {api, host, parent, sent, delivered, listeners, message, send, bind,
    flush:() => { while (microtasks.length) microtasks.shift()(); },
    time:value => { now = value; }};
}
test('explicit install: listener handshake is distinct from actual core gate', () => {
  const f = fixture();
  assert.equal(f.sent[0].data.type, 'bridge_ready');
  assert.match(f.sent[0].data.session, /^[a-f0-9]{32}$/);
  assert.ok(f.sent.every(row => row.target === origin));
  f.send(f.message()); f.flush();
  assert.equal(f.delivered.length, 0);
  f.api.corePresented(); f.flush();
  assert.deepEqual(f.delivered, [display()]);
});
test('requires exact configured HTTP(S) origin; never query-derived trust', () => {
  for (const value of ['*', 'null', '', origin + '/', origin + '/path', origin + '?parent=*',
    'https://name:secret@camp.example.test', 'https://*.example.test', 'file:///tmp']) {
    assert.throws(() => fixture({allowedParentOrigin:value}), undefined, value);
  }
  const f = fixture(); f.api.corePresented();
  f.send(f.message(), {origin:'https://camp.example.test.evil.test'});
  f.send(f.message(), {origin:'http://camp.example.test'});
  f.send(f.message(), {origin:'null'});
  f.send(f.message(), {source:{}}); f.flush();
  assert.equal(f.delivered.length, 0);
});
test('wrong protocol, version, type, nonce and malformed envelopes are inert', () => {
  const f = fixture(); f.api.corePresented();
  for (const change of [{protocol:'other'}, {version:2}, {type:'settle'}, {session:'old'},
    {sequence:-1}, {sequence:NaN}, {sequence:1.5}, {sequence:Number.MAX_SAFE_INTEGER + 1},
    {token:'secret'}, {snapshot:null}]) f.send({...f.message(), ...change});
  f.send(JSON.stringify(f.message())); f.send(null); f.send([]); f.flush();
  assert.equal(f.delivered.length, 0);
});
test('public snapshot rejects unknown private/authority fields at either boundary', () => {
  const f = fixture(); f.api.corePresented();
  for (const key of ['authToken', 'accountId', 'reward', 'hp', 'damage', 'url', '__proto__']) {
    f.send({...f.message(), [key]:'secret'});
    f.send(f.message({...display(), [key]:'secret'}));
  }
  f.flush(); assert.equal(f.delivered.length, 0);
  assert.ok(f.sent.every(row => !JSON.stringify(row).includes('secret')));
});
test('protocol v1 retains exact seven-key legacy snapshots and forwards only the paired HP extension', () => {
  const f = fixture(); f.api.corePresented();
  let sequence = 0;
  for (const mode of bridge.MODES) {
    if (mode !== 'defeated') {
      const legacy = modeDisplay(mode);
      f.send(f.message(legacy, ++sequence)); f.flush();
      assert.deepEqual(f.delivered.at(-1), legacy);
      assert.equal(Object.keys(f.delivered.at(-1)).length, 7);
      assert.equal(Object.hasOwn(f.delivered.at(-1), 'bossHp'), false);
    }
    const snapshot = hpDisplay(mode);
    f.send(f.message(snapshot, ++sequence)); f.flush();
    assert.deepEqual(f.delivered.at(-1), snapshot);
    assert.equal(Object.keys(f.delivered.at(-1)).length, 9);
  }
  assert.equal(bridge.VERSION, 1);
  assert.ok(f.sent.every(row => row.data.version === 1));
});
test('HP pair accepts integer boundaries without deriving mode, HP or settlement from time', () => {
  const f = fixture(); f.api.corePresented(); let sequence = 0;
  for (const [bossHp, bossMaxHp] of [[0,1], [1,1], [0,1e9], [1e9,1e9], [725,1000]]) {
    const snapshot = {...hpDisplay(), bossHp, bossMaxHp, elapsed:600};
    f.send(f.message(snapshot, ++sequence)); f.flush();
    assert.deepEqual(f.delivered.at(-1), snapshot);
    assert.equal(f.delivered.at(-1).mode, 'fighting');
  }
  f.time(600000); f.flush();
  assert.equal(f.delivered.length, 5);
  assert.equal(f.delivered.at(-1).bossHp, 725);
  assert.ok(f.sent.every(row => !['settle', 'reward', 'defeated', 'claim'].includes(row.data.type)));
});
test('single, invalid or over-bound HP fields are rejected without poisoning sequence', () => {
  const f = fixture(); f.api.corePresented();
  const invalid = [{...display(), bossHp:0}, {...display(), bossMaxHp:1000}];
  for (const key of ['bossHp', 'bossMaxHp']) {
    for (const value of [undefined, null, true, false, '0', 0.5, -1, 1e9 + 1, NaN, Infinity,
      -Infinity, Number.MAX_SAFE_INTEGER, 0n, [], {}, new Number(0)]) {
      invalid.push({...hpDisplay(), [key]:value});
    }
  }
  invalid.push({...hpDisplay(), bossHp:1001}, {...hpDisplay(), bossHp:0, bossMaxHp:0});
  for (const snapshot of invalid) f.send(f.message(snapshot, 999));
  f.flush(); assert.deepEqual(f.delivered, []);
  f.send(f.message(hpDisplay(), 1)); f.flush();
  assert.deepEqual(f.delivered, [hpDisplay()]);
});
test('defeated requires nine fields, zero HP, round reference and all three allowed actors', () => {
  const f = fixture(); f.api.corePresented();
  const invalid = [{...display(), mode:'defeated'}, {...hpDisplay('defeated'), bossHp:1},
    {...hpDisplay('defeated'), roundId:''}, {...hpDisplay('defeated'), roundId:'account@example.test'}];
  for (const role of ['hero', 'pet', 'boss']) {
    for (const id of ['', null, 'not-registered']) invalid.push({...hpDisplay('defeated'), [`${role}AssetId`]:id});
  }
  for (const snapshot of invalid) f.send(f.message(snapshot, 999));
  f.flush(); assert.deepEqual(f.delivered, []);
  const selected = []; f.api.bindAssetLoader(value => selected.push(value));
  const snapshot = hpDisplay('defeated'); f.send(f.message(snapshot)); f.flush();
  assert.deepEqual(f.delivered, [snapshot]);
  assert.deepEqual(selected, [[ids.hero[0], ids.pet[0], ids.boss[0]]]);
  // Defeat is not inferred from a timer threshold (including legacy 600s).
  f.send(f.message({...snapshot, elapsed:0, duration:0}, 2)); f.flush();
  assert.deepEqual(f.delivered.at(-1), {...snapshot, elapsed:0, duration:0});
});
test('HP extension cannot smuggle account, damage, reward or other health fields into either channel', () => {
  const f = fixture(); f.api.corePresented();
  for (const key of ['authToken', 'accountId', 'accountIdentifier', 'reward', 'rewards', 'claim', 'vip',
    'damage', 'skillDamage', 'heroHp', 'petHp', 'hp', 'maxHp', 'health', 'bossHP', 'url', '__proto__']) {
    for (const mode of ['fighting', 'defeated']) {
      f.send({...f.message(hpDisplay(mode), 999), [key]:'forbidden-secret'});
      f.send(f.message({...hpDisplay(mode), [key]:'forbidden-secret'}, 999));
    }
  }
  f.flush(); assert.deepEqual(f.delivered, []);
  assert.ok(f.sent.every(row => !JSON.stringify(row).includes('forbidden-secret')));
  f.send(f.message(hpDisplay('defeated'))); f.flush();
  assert.deepEqual(f.delivered, [hpDisplay('defeated')]);
});
test('HP extension retains exact parent, source, protocol, session and replay checks', () => {
  const f = fixture(); f.api.corePresented();
  for (const override of [{origin:'https://camp.example.test.evil.test'}, {origin:'null'}, {source:{}}])
    f.send(f.message(hpDisplay('defeated'), 999), override);
  for (const change of [{protocol:'other'}, {version:2}, {session:'old'}, {type:'defeat'}])
    f.send({...f.message(hpDisplay('defeated'), 999), ...change});
  f.flush(); assert.deepEqual(f.delivered, []);
  f.send(f.message(hpDisplay(), 1)); f.flush();
  f.send(f.message(hpDisplay('defeated'), 1)); f.flush();
  assert.deepEqual(f.delivered, [hpDisplay()]);
  f.send(f.message(hpDisplay('defeated'), 2)); f.flush();
  assert.deepEqual(f.delivered, [hpDisplay(), hpDisplay('defeated')]);
});
test('HP getters and symbol extras never execute; accepted numeric values are copied before delivery', () => {
  const f = fixture(); f.api.corePresented(); let accessed = false;
  for (const key of ['bossHp', 'bossMaxHp']) {
    const snapshot = hpDisplay();
    Object.defineProperty(snapshot, key, {get:() => { accessed = true; return 0; }});
    f.send(f.message(snapshot, 999));
  }
  f.send(f.message({...hpDisplay(), [Symbol('private')]:1}, 999)); f.flush();
  assert.equal(accessed, false); assert.deepEqual(f.delivered, []);
  const snapshot = hpDisplay(); f.send(f.message(snapshot));
  snapshot.bossHp = 0; snapshot.bossMaxHp = 1; snapshot.mode = 'defeated';
  f.flush(); assert.deepEqual(f.delivered, [hpDisplay()]);
});
test('asset allowlists are role-specific, bounded and copied at construction', () => {
  const mutable = {hero:[...ids.hero], pet:[...ids.pet], boss:[...ids.boss]};
  const f = fixture({assetIds:mutable}); f.api.corePresented();
  mutable.hero.push('hero-injected');
  for (const heroAssetId of ['hero-injected', ids.boss[0], '../hero', 'https://cdn.test/x', null, 123])
    f.send(f.message({...display(), heroAssetId}));
  f.flush(); assert.equal(f.delivered.length, 0);
  assert.throws(() => fixture({assetIds:{...ids, hero:[ids.boss[0]]}}));
  assert.throws(() => fixture({assetIds:{...ids, hero:Array(65).fill('hero-x')}}));
});
test('finite bounded numeric times and safe public round identifiers only', () => {
  const f = fixture(); f.api.corePresented();
  for (const change of [{elapsed:'12'}, {duration:true}, {elapsed:NaN}, {elapsed:Infinity},
    {duration:Infinity}, {elapsed:-1}, {elapsed:601}, {duration:86401}, {duration:0},
    {roundId:''}, {roundId:'<script>'}, {roundId:'x'.repeat(81)}, {mode:'completed'}])
    f.send(f.message({...display(), ...change}));
  f.flush(); assert.equal(f.delivered.length, 0);
});
test('known modes including no-actor waiting states; no automatic settlement', () => {
  const f = fixture(); f.api.corePresented();
  for (const [index, mode] of bridge.MODES.entries()) {
    const snapshot = modeDisplay(mode);
    f.send(f.message(snapshot, index)); f.flush();
    assert.equal(f.delivered.at(-1).mode, mode);
  }
  f.send(f.message({...display(), elapsed:600}, 20)); f.flush();
  assert.equal(f.delivered.at(-1).mode, 'fighting');
  f.send(f.message({mode:'waiting', heroAssetId:'', petAssetId:'', bossAssetId:'',
    elapsed:0, duration:0, roundId:''}, 21)); f.flush();
  assert.equal(f.delivered.at(-1).mode, 'waiting');
  assert.ok(f.sent.every(row => !['settle', 'reward', 'start'].includes(row.data.type)));
});
test('coalesces pre-core state, rejects replay, invalid sequence cannot poison stream', () => {
  const f = fixture();
  f.send(f.message({...display(), elapsed:1}, 1));
  f.send(f.message({...display(), elapsed:2}, 2));
  f.send({...f.message(display(), 10000), token:'bad'});
  f.api.corePresented(); f.flush();
  assert.deepEqual(f.delivered.map(s => s.elapsed), [2]);
  f.send(f.message(display(), 1)); f.send(f.message(display(), 2)); f.flush();
  assert.equal(f.delivered.length, 1);
  f.send(f.message({...display(), elapsed:3}, 3)); f.flush();
  assert.equal(f.delivered.at(-1).elapsed, 3);
});
test('delayed optional pack cannot replay a stale queued fighting state as fresh', () => {
  const f = fixture(); f.send(f.message()); f.time(15001);
  f.api.corePresented(); f.flush();
  assert.equal(f.delivered.length, 0);
  assert.equal(f.sent.at(-1).data.status, 'stale');
  f.send(f.message(display(), 2)); f.flush();
  assert.equal(f.delivered.length, 1);
});
test('slow-start demo waits for core and native binding, then delivers unchanged once', () => {
  for (const delay of [15001, 45000, 60000]) for (const lastGate of ['core', 'native']) {
    const f = fixture(), selected = [], snapshot = demoDisplay();
    f.api.bindAssetLoader(value => selected.push(value));
    if (lastGate === 'native') f.api.unbind(f.bind);
    f.send(f.message(snapshot)); f.flush();
    if (lastGate === 'native') { f.time(7552); f.api.corePresented(); f.flush(); }
    f.time(delay); f.flush();
    assert.deepEqual(f.delivered, [], `${lastGate} still closed at ${delay}ms`);
    assert.deepEqual(selected, []);
    if (lastGate === 'core') f.api.corePresented(); else f.api.bind(f.bind);
    f.flush();
    assert.deepEqual(f.delivered, [snapshot], `${lastGate} released at ${delay}ms`);
    assert.deepEqual(selected, [[ids.hero[0], ids.pet[0], ids.boss[0]]]);
    f.api.corePresented(); f.api.bind(f.bind); f.send(f.message(snapshot)); f.flush();
    assert.equal(f.delivered.length, 1); assert.equal(selected.length, 1);
    assert.ok(f.sent.every(row => !['ready', 'stale'].includes(row.data.status)));
    f.api.dispose();
  }
});
test('slow-start demo supports a late actor loader without replaying native state', () => {
  const f = fixture(), selected = [], snapshot = demoDisplay();
  f.api.corePresented(); f.send(f.message(snapshot)); f.flush();
  assert.deepEqual(f.delivered, [snapshot]);
  f.time(60000); f.api.bindAssetLoader(value => selected.push(value));
  assert.deepEqual(selected, [[ids.hero[0], ids.pet[0], ids.boss[0]]]);
  assert.deepEqual(f.delivered, [snapshot]);
  f.api.dispose();
});
test('slow-start latest server or hidden state supersedes old demo without fallback', () => {
  for (const mode of bridge.MODES.filter(mode => mode !== 'demo')) for (const age of [0, 15001]) {
    const f = fixture(), selected = [], latest = modeDisplay(mode);
    f.api.bindAssetLoader(value => selected.push(value));
    f.send(f.message(demoDisplay()));
    f.time(100); f.send(f.message(latest, 2));
    f.time(100 + age); f.api.corePresented(); f.send(f.message(demoDisplay())); f.flush();
    assert.deepEqual(f.delivered, age === 0 ? [latest] : [], `${mode} age ${age}`);
    const currentIds = ['waiting', 'unavailable'].includes(mode) ? [] : [ids.hero[0], ids.pet[0], ids.boss[0]];
    assert.deepEqual(selected, age === 0 ? [currentIds] : []);
    if (age > 15000) assert.equal(f.sent.at(-1).data.status, 'stale');
    f.api.dispose();
  }
});
test('every non-demo mode keeps the exact freshness boundary and fails closed on clock anomalies', () => {
  for (const mode of bridge.MODES.filter(mode => mode !== 'demo')) {
    for (const age of [15000, 15001, Infinity, NaN, -1]) {
      const f = fixture(), snapshot = modeDisplay(mode);
      f.send(f.message(snapshot)); f.time(age); f.api.corePresented(); f.flush();
      assert.deepEqual(f.delivered, age === 15000 ? [snapshot] : [], `${mode} age ${age}`);
      if (age !== 15000) assert.equal(f.sent.at(-1).data.status, 'stale');
      f.api.dispose();
    }
    const f = fixture(), selected = [];
    f.api.corePresented(); f.send(f.message(modeDisplay(mode))); f.flush();
    f.time(15001); f.api.bindAssetLoader(value => selected.push(value));
    assert.deepEqual(selected, [], `${mode} cannot refresh via late loader binding`);
    assert.equal(f.delivered.length, 1); f.api.dispose();
  }
});
test('slow-start demo exemption cannot bypass public schema, origin, source, session or sequence', () => {
  const f = fixture(), selected = [], hidden = {...demoDisplay(), mode:'unavailable'};
  f.api.bindAssetLoader(value => selected.push(value));
  f.send(f.message(hidden));
  for (const key of ['authToken', 'accountId', 'reward', 'url']) {
    f.send({...f.message(demoDisplay(), 999), [key]:'forbidden-secret'});
    f.send(f.message({...demoDisplay(), [key]:'forbidden-secret'}, 999));
  }
  for (const change of [{session:'old'}, {protocol:'other'}, {version:2}, {sequence:1}])
    f.send({...f.message(demoDisplay(), 999), ...change});
  f.send(f.message({...demoDisplay(), heroAssetId:'hero-unregistered'}, 999));
  f.send(f.message({...demoDisplay(), heroAssetId:'', petAssetId:'', bossAssetId:''}, 999));
  f.send(f.message(demoDisplay(), 999), {origin:'https://other.example.test'});
  f.send(f.message(demoDisplay(), 999), {source:{}});
  f.time(60000); f.api.corePresented(); f.flush();
  assert.deepEqual(f.delivered, []); assert.deepEqual(selected, []);
  f.send(f.message(hidden, 2)); f.flush();
  assert.deepEqual(f.delivered, [hidden]); assert.deepEqual(selected, [[]]);
  assert.ok(f.sent.every(row => row.target === origin && !JSON.stringify(row).includes('forbidden-secret')));
  f.api.dispose();
});
test('slow-start late loader uses the latest hidden state and never a previously delivered demo', () => {
  for (const mode of ['waiting', 'unavailable']) for (const age of [0, 15001]) {
    const f = fixture(), selected = [];
    f.api.corePresented(); f.send(f.message(demoDisplay())); f.flush();
    f.time(60000); f.send(f.message({...demoDisplay(), mode}, 2)); f.flush();
    f.time(60000 + age); f.api.bindAssetLoader(value => selected.push(value));
    assert.deepEqual(selected, age === 0 ? [[]] : [], `${mode} age ${age}`);
    assert.deepEqual(f.delivered.map(value => value.mode), ['demo', mode]);
    f.api.dispose();
  }
});
test('slow-start queued demo cannot outlive disposal or a newer hidden microtask', () => {
  for (const dispose of [false, true]) {
    const f = fixture(), selected = [], hidden = {...demoDisplay(), mode:'waiting'};
    f.api.bindAssetLoader(value => selected.push(value));
    f.send(f.message(demoDisplay())); f.time(60000); f.api.corePresented();
    if (dispose) f.api.dispose(); else f.send(f.message(hidden, 2));
    f.flush();
    assert.deepEqual(f.delivered, dispose ? [] : [hidden]);
    assert.deepEqual(selected, dispose ? [] : [[]]);
    f.api.dispose();
  }
});
test('clean disposal/unbind: pending callbacks and stale owners cannot leak', () => {
  const f = fixture(); f.api.corePresented();
  assert.equal(f.api.bind(() => {}), false);
  assert.equal(f.api.unbind(() => {}), false);
  f.send(f.message()); f.api.unbind(f.bind); f.flush();
  assert.equal(f.delivered.length, 0);
  f.api.bind(f.bind); f.flush(); assert.equal(f.delivered.length, 1);
  f.send(f.message(display(), 2)); f.api.dispose(); f.flush();
  assert.equal(f.delivered.length, 1); assert.equal(f.listeners.size, 0);
  assert.equal(f.api.bind(f.bind), false);
});
test('untrusted getter and symbol properties never enter renderer', () => {
  const f = fixture(); f.api.corePresented();
  let getterRead = false;
  const data = f.message(); Object.defineProperty(data, 'sequence', {get:() => { getterRead = true; return 1; }});
  f.send(data); f.send({...f.message(), [Symbol('secret')]:'private'}); f.flush();
  assert.equal(getterRead, false); assert.equal(f.delivered.length, 0);
});
test('status channel emits only fixed enums and suppresses duplicate updates', () => {
  const f = fixture(); const count = f.sent.length;
  assert.equal(f.api.report('token=secret'), false);
  f.api.report('missing_assets'); f.api.report('missing_assets');
  assert.equal(f.sent.length, count + 1);
  assert.deepEqual(Object.keys(f.sent.at(-1).data).sort(), ['protocol', 'session', 'status', 'type', 'version']);
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function downloadFixture(bytes = new Uint8Array([1, 2, 3, 4])) {
  const digest = createHash('sha256').update(bytes).digest('hex');
  const gate = deferred(), fetched = [], copied = [], mounted = [], status = [];
  let timeout;
  const host = {crypto:webcrypto, performance:{now:() => 0}, setTimeout:callback => { timeout = callback; return 1; }, clearTimeout:() => {},
    fetch:async (file, options) => { fetched.push({file, options}); return new Response(bytes); }};
  const options = {pack:{file:`camp-presentation-${digest.slice(0, 12)}.pck`, bytes:bytes.length, sha256:digest},
    coreReady:gate.promise, engine:{copyToFS:(...args) => copied.push(args)},
    mount:async (...args) => { mounted.push(args); return true; }, onStatus:value => status.push(value)};
  return {gate, fetched, copied, mounted, status, options, host, expire:() => timeout()};
}
test('additional pack transfer waits for actual core; uses existing engine and explicit apply ack', async () => {
  const f = downloadFixture(); const ack = deferred();
  f.options.mount = (...args) => { f.mounted.push(args); return ack.promise; };
  const result = bridge.loadPackAfterCore(f.options, f.host);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.fetched.length, 0); assert.equal(f.copied.length, 0);
  f.gate.resolve();
  while (!f.mounted.length) await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.status.at(-1), 'applying');
  assert.equal(f.fetched[0].options.credentials, 'omit');
  assert.equal(f.fetched[0].options.redirect, 'error');
  assert.equal(f.copied.length, 1);
  ack.resolve(true); assert.equal((await result).bytes, 4);
  assert.equal(f.status.at(-1), 'pack_ready');
});
test('pack descriptor paths, digest, size and unexpected fields fail before any fetch', async () => {
  for (const mutation of [{file:'../other.pck'}, {file:'https://host.test/x.pck'},
    {sha256:'f'.repeat(64)}, {bytes:0}, {bytes:17 * 1024 * 1024}, {bytes:1.5}, {token:'secret'}]) {
    const f = downloadFixture(); Object.assign(f.options.pack, mutation);
    await assert.rejects(bridge.loadPackAfterCore(f.options, f.host));
    assert.equal(f.fetched.length, 0);
  }
});
test('rejected or absent core gate never downloads', async () => {
  const f = downloadFixture(); const attempt = bridge.loadPackAfterCore(f.options, f.host);
  f.gate.reject(Error('engine failed')); await assert.rejects(attempt);
  assert.equal(f.fetched.length, 0);
  f.options.coreReady = undefined;
  await assert.rejects(bridge.loadPackAfterCore(f.options, f.host));
});
test('wrong response size, digest or HTTP failure never enters filesystem/Godot', async () => {
  for (const reply of [new Response(new Uint8Array([1, 2])), new Response(new Uint8Array(20)),
    new Response(new Uint8Array([9, 9, 9, 9])), new Response('', {status:503})]) {
    const f = downloadFixture(); f.host.fetch = async () => reply; f.gate.resolve();
    await assert.rejects(bridge.loadPackAfterCore(f.options, f.host), {reloadRequired:false});
    assert.equal(f.copied.length, 0); assert.equal(f.mounted.length, 0);
  }
});
test('abort while waiting for core or a stuck fetch prevents late application', async () => {
  for (const stage of ['core', 'fetch']) {
    const f = downloadFixture(); const controller = new AbortController(), response = deferred();
    f.options.signal = controller.signal;
    f.host.fetch = () => response.promise;
    if (stage === 'fetch') f.gate.resolve();
    const result = bridge.loadPackAfterCore(f.options, f.host);
    await new Promise(resolve => setImmediate(resolve)); controller.abort();
    await assert.rejects(result, {reloadRequired:false});
    f.gate.resolve(); response.resolve(new Response(new Uint8Array([1, 2, 3, 4])));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.copied.length, 0);
  }
});
test('overall timeout spans WebCrypto; stale completion cannot mount', async () => {
  const f = downloadFixture(), digest = deferred();
  f.host.crypto = {subtle:{digest:() => digest.promise}}; f.gate.resolve();
  const result = bridge.loadPackAfterCore(f.options, f.host);
  await new Promise(resolve => setImmediate(resolve)); f.expire();
  await assert.rejects(result, {reloadRequired:false});
  digest.resolve(new ArrayBuffer(32)); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.copied.length, 0);
});
test('uncertain or failed mount requires reload; no false ready or automatic retry', async () => {
  for (const mode of ['false', 'timeout', 'throw']) {
    const f = downloadFixture(), ack = deferred(); f.gate.resolve();
    f.options.mount = async (...args) => {
      f.mounted.push(args);
      if (mode === 'throw') throw Error('apply failed');
      return mode === 'false' ? false : ack.promise;
    };
    const result = bridge.loadPackAfterCore(f.options, f.host);
    const rejected = assert.rejects(result, {reloadRequired:true});
    if (mode === 'timeout') {
      while (!f.mounted.length) await new Promise(resolve => setImmediate(resolve));
      f.expire();
    }
    await rejected; ack.resolve(true);
    assert.equal(f.status.at(-1), 'reload_required');
    assert.equal(f.status.includes('ready'), false); assert.equal(f.mounted.length, 1);
    await assert.rejects(bridge.loadPackAfterCore(f.options, f.host), {reloadRequired:true});
    assert.equal(f.mounted.length, 1);
  }
});
test('duplicate same-engine requests share one download and mount, including after success', async () => {
  const f = downloadFixture();
  const first = bridge.loadPackAfterCore(f.options, f.host);
  const duplicate = bridge.loadPackAfterCore(f.options, f.host);
  f.gate.resolve(); await Promise.all([first, duplicate]);
  await bridge.loadPackAfterCore(f.options, f.host);
  assert.equal(f.fetched.length, 1); assert.equal(f.copied.length, 1); assert.equal(f.mounted.length, 1);
  const another = downloadFixture(new Uint8Array([4, 3, 2, 1]));
  await assert.rejects(bridge.loadPackAfterCore({...f.options, pack:another.options.pack}, f.host), /requires reload/);
});
test('explicit retry after a verified pre-mount failure can succeed', async () => {
  const f = downloadFixture(); f.gate.resolve();
  const original = f.host.fetch; f.host.fetch = async () => new Response('', {status:503});
  await assert.rejects(bridge.loadPackAfterCore(f.options, f.host), {reloadRequired:false});
  f.host.fetch = original;
  await bridge.loadPackAfterCore(f.options, f.host);
  assert.equal(f.mounted.length, 1);
});
test('overdue absolute deadline cannot be bypassed by queued microtasks', async () => {
  const f = downloadFixture(); let now = 0;
  f.host.performance.now = () => now;
  f.host.crypto = {subtle:{digest:async () => { now = 60001; return new ArrayBuffer(32); }}};
  f.gate.resolve();
  await assert.rejects(bridge.loadPackAfterCore(f.options, f.host), {reloadRequired:false});
  assert.equal(f.copied.length, 0);
});

function mountFixture(optional = undefined, actorShards = []) {
  const digest = 'a'.repeat(64), calls = [], timers = new Map();
  let now = 0, serial = 0;
  const pack = optional === undefined ? {file:`camp-presentation-${digest.slice(0, 12)}.pck`, bytes:123, sha256:digest} : optional;
  const host = {performance:{now:() => now}, setTimeout:(fn) => { const id = ++serial; timers.set(id, fn); return id; },
    clearTimeout:id => timers.delete(id)};
  const api = bridge.createMountClient({pack, actorShards}, host);
  const callback = (...args) => calls.push(args);
  return {api, host, pack, calls, callback, timers, time:value => { now = value; },
    expire:() => { for (const fn of [...timers.values()]) fn(); },
    path:pack ? `/${pack.file}` : null};
}
test('independent persistent mount facade waits for REAL core acknowledgement and survives boot cleanup', async () => {
  const f = mountFixture();
  assert.equal(f.calls.length, 0);
  await assert.rejects(f.api.mount(f.path, f.pack.sha256), /not_ready/);
  const gate = f.api.corePresented();
  assert.equal(gate, f.api.corePresented()); assert.equal(f.calls.length, 0);
  f.api.bind(f.callback); assert.deepEqual(f.calls, [['core_presented']]);
  assert.equal(f.api.coreAccepted(true, 'applied'), false);
  assert.equal(f.api.coreAccepted(true, 'core_presented'), true); assert.equal(await gate, true);
  const disposableBoot = {active:{}}; disposableBoot.active = null;
  const result = f.api.mount(f.path, f.pack.sha256);
  assert.equal(f.api.mount(f.path, f.pack.sha256), result);
  assert.deepEqual(f.calls.at(-1), ['mount', 1, f.path, f.pack.sha256]);
  assert.equal(f.api.applied(99, true, 'applied'), false);
  assert.equal(f.api.applied(1, 'true', 'applied'), false);
  assert.equal(f.api.applied(1, false, 'applied'), false);
  assert.equal(f.api.applied(1, true, 'unknown'), false);
  assert.equal(f.api.applied(1, true, 'applied'), true);
  assert.equal(await result, true); assert.equal(f.timers.size, 0);
  assert.equal(await f.api.mount(f.path, f.pack.sha256), true); assert.equal(f.calls.length, 2);
  assert.equal(f.api.applied(1, true, 'applied'), false);
});
test('mount facade accepts only trusted frozen pin, never parent-supplied URL/pack', async () => {
  const f = mountFixture(); f.api.bind(f.callback);
  const gate = f.api.corePresented(); f.api.coreAccepted(true, 'core_presented'); await gate;
  for (const path of ['https://evil.test/x.pck', '/other.pck', '../' + f.pack.file, f.pack.file])
    await assert.rejects(f.api.mount(path, f.pack.sha256), /pin_mismatch/);
  await assert.rejects(f.api.mount(f.path, 'b'.repeat(64)), /pin_mismatch/);
  assert.equal(f.calls.length, 1);
  assert.throws(() => bridge.createMountClient({pack:f.pack, query:'arbitrary'}, f.host));
  assert.throws(() => bridge.createMountClient({pack:{...f.pack, token:'private'}}, f.host));
  const unconfigured = mountFixture(null);
  await assert.rejects(unconfigured.api.mount('/anything.pck', 'a'.repeat(64)), /disabled/);
  assert.equal(unconfigured.calls.length, 0);
});
test('native facade rejects stale callbacks, false core, and lifecycle replacement', async () => {
  const f = mountFixture(); f.api.bind(f.callback);
  assert.equal(f.api.bind(() => {}), false);
  assert.equal(f.api.unbind(() => {}), false);
  const gate = f.api.corePresented();
  assert.equal(f.api.coreAccepted(false, 'not_ready'), true);
  await assert.rejects(gate, /not_ready/);
  await assert.rejects(f.api.mount(f.path, f.pack.sha256), /not_ready/);
  assert.equal(f.api.coreAccepted(true, 'core_presented'), false);
  const g = mountFixture(); const waiting = g.api.corePresented(); g.api.dispose();
  await assert.rejects(waiting, /disposed/); assert.equal(g.api.bind(g.callback), false);
  assert.equal(g.timers.size, 0);
});
test('native mount failure or lost callback is terminal, never an uncertain retry', async () => {
  for (const mode of ['reject', 'unbind', 'dispose', 'throw']) {
    const f = mountFixture();
    const callback = (...args) => { f.callback(...args); if (args[0] === 'mount' && mode === 'throw') throw Error('native gone'); };
    f.api.bind(callback); const gate = f.api.corePresented(); f.api.coreAccepted(true, 'core_presented'); await gate;
    const result = f.api.mount(f.path, f.pack.sha256);
    if (mode === 'reject') f.api.applied(1, false, 'reload_required');
    if (mode === 'unbind') assert.equal(f.api.unbind(callback), true);
    if (mode === 'dispose') f.api.dispose();
    await assert.rejects(result, {reloadRequired:true});
    assert.equal(f.api.applied(1, true, 'applied'), false);
    await assert.rejects(f.api.mount(f.path, f.pack.sha256), {reloadRequired:true});
    assert.equal(f.calls.length, 2); assert.equal(f.timers.size, 0);
  }
});
test('bounded native wait rejects late ack even when background timer has not fired', async () => {
  for (const mode of ['core', 'mount']) {
    const f = mountFixture(); f.api.bind(f.callback); let result = f.api.corePresented();
    if (mode === 'mount') { f.api.coreAccepted(true, 'core_presented'); await result; result = f.api.mount(f.path, f.pack.sha256); }
    f.time(30001);
    const accepted = mode === 'core' ? f.api.coreAccepted(true, 'core_presented') : f.api.applied(1, true, 'applied');
    assert.equal(accepted, false); await assert.rejects(result, {reloadRequired:mode === 'mount'});
    assert.equal(f.timers.size, 0);
  }
  const f = mountFixture(); const result = f.api.corePresented(); f.expire();
  await assert.rejects(result, /timeout/); assert.equal(f.api.bind(f.callback), false);
});
test('parent transport has no route to the independent native mount facade', () => {
  const mount = mountFixture(), f = fixture(); mount.api.bind(mount.callback); f.api.corePresented();
  for (const type of ['mount', 'core_presented', 'applied', 'settle']) f.send({...f.message(), type});
  f.send(f.message({...display(), pack:mount.pack})); f.flush();
  assert.equal(f.delivered.length, 0); assert.equal(mount.calls.length, 0);
  assert.equal(f.api.mount, undefined); assert.equal(f.api.coreAccepted, undefined);
});
test('catalogue namespace keys and honest single-actor demo work without guessing art IDs', () => {
  const f = fixture({assetIds:{hero:['hero/ranger'], pet:[], boss:[]}}); f.api.corePresented();
  const demo = {mode:'demo', heroAssetId:'hero/ranger', petAssetId:'', bossAssetId:'', elapsed:0, duration:0, roundId:''};
  f.send(f.message(demo)); f.flush(); assert.deepEqual(f.delivered, [demo]);
  for (const snapshot of [{...demo, mode:'fighting', duration:600, roundId:'public-1'},
    {...demo, mode:'paused', duration:600, roundId:'public-1'}, {...demo, heroAssetId:''}]) f.send(f.message(snapshot, 2));
  f.flush(); assert.equal(f.delivered.length, 1);
  for (const id of ['hero/ranger/x', 'hero//ranger', '../ranger', 'hero/../ranger', '/ranger', 'h'.repeat(65)])
    assert.throws(() => fixture({assetIds:{hero:[id], pet:[], boss:[]}}));
});
test('late pack completion cannot overwrite the real drawn actor status', () => {
  for (const status of ['ready', 'missing_assets', 'unsafe_placement', 'stale', 'unavailable']) {
    const f = fixture(); f.api.corePresented(); f.api.report('applying');
    f.api.report(status); const count = f.sent.length;
    assert.equal(f.api.report('pack_ready'), true);
    assert.equal(f.sent.length, count); assert.equal(f.sent.at(-1).data.status, status);
  }
});

function actorFixture() {
  const assetIds = {hero:[], pet:[], boss:[]}, actorShards = [], bodies = new Map(); let number = 1;
  for (const [role,count] of [['hero',6],['pet',6],['boss',1]]) for (let i = 0; i < count; i++) {
    const id = `${role}/actor-${i}`, bytes = new Uint8Array([number++, 2, 3, 4]);
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    const pack = {file:`camp-actor-${sha256.slice(0,12)}.pck`, bytes:bytes.length, sha256};
    assetIds[role].push(id); actorShards.push({pack, assetIds:[id]}); bodies.set(pack.file, bytes);
  }
  const core = deferred(), runtime = deferred(), fetched = [], copied = [], mounted = [], status = [], timers = new Map();
  let timerId = 0;
  const host = {crypto:webcrypto, performance:{now:() => 0}, setTimeout:fn => { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout:id => timers.delete(id), fetch:async (file, init) => { fetched.push({file,init}); return new Response(bodies.get(file)); }};
  const options = {actorShards, assetIds, coreReady:core.promise, runtimeReady:runtime.promise,
    engine:{copyToFS:(...args) => copied.push(args)}, mountActor:async (...args) => { mounted.push(args); return true; }, onStatus:s => status.push(s)};
  return {assetIds, actorShards, bodies, core, runtime, fetched, copied, mounted, status, timers, host, options,
    trio:[assetIds.hero[0], assetIds.pet[0], assetIds.boss[0]], packFor:id => actorShards.find(s => s.assetIds.includes(id)).pack,
    release:() => { core.resolve(true); runtime.resolve(true); }};
}
async function until(predicate) {
  for (let i = 0; i < 200; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 5)); }
  assert.fail('Bounded asynchronous test condition was not reached');
}
test('fresh defeated state loads only its pinned trio after both gates, without hiding or replaying it', async () => {
  const art = actorFixture(), f = fixture({assetIds:art.assetIds});
  const loader = bridge.createActorLoader(art.options, art.host);
  f.api.bindAssetLoader(loader.select);
  const snapshot = {...hpDisplay('defeated'), heroAssetId:art.trio[0], petAssetId:art.trio[1], bossAssetId:art.trio[2]};
  f.send(f.message(snapshot)); f.flush();
  assert.deepEqual(f.delivered, []);
  assert.deepEqual(loader.getStatus().selectedAssetIds, []);
  f.api.corePresented(); f.flush();
  assert.deepEqual(f.delivered, [snapshot]);
  assert.deepEqual(loader.getStatus().selectedAssetIds, art.trio);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(art.fetched.length, 0);
  art.core.resolve(true);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(art.fetched.length, 0);
  art.runtime.resolve(true); await until(() => art.mounted.length === 3);
  assert.equal(art.fetched.length, 3); assert.equal(art.copied.length, 3);
  assert.deepEqual(new Set(art.fetched.map(row => row.file)), new Set(art.trio.map(id => art.packFor(id).file)));
  assert.deepEqual(f.delivered, [snapshot], 'art completion never replays a fresh-looking snapshot');
  f.send(f.message({...snapshot, mode:'waiting'}, 2)); f.flush();
  assert.deepEqual(loader.getStatus().selectedAssetIds, []);
  f.send(f.message({...snapshot, mode:'fighting'}, 3)); f.flush();
  await until(() => loader.getStatus().mountedShards === 3);
  assert.equal(f.delivered.at(-1).mode, 'fighting');
  assert.equal(f.delivered.at(-1).bossHp, 0);
  assert.equal(art.fetched.length, 3, 'already cached actors need no world or actor reload');
  f.api.dispose(); loader.dispose();
});
test('slow-start demo uses the real actor loader while both native gates still prevent transfer', async () => {
  const art = actorFixture(), f = fixture({assetIds:art.assetIds});
  const loader = bridge.createActorLoader(art.options, art.host);
  f.api.bindAssetLoader(loader.select);
  const snapshot = {...demoDisplay(), heroAssetId:art.trio[0], petAssetId:art.trio[1], bossAssetId:art.trio[2]};
  f.send(f.message(snapshot)); f.time(60000); f.api.corePresented(); f.flush();
  assert.deepEqual(f.delivered, [snapshot]);
  assert.deepEqual(loader.getStatus().selectedAssetIds, art.trio);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(art.fetched.length, 0);
  art.core.resolve(true);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(art.fetched.length, 0);
  art.runtime.resolve(true); await until(() => art.mounted.length === 3);
  assert.equal(art.fetched.length, 3); assert.equal(art.copied.length, 3);
  assert.deepEqual(new Set(art.fetched.map(row => row.file)), new Set(art.trio.map(id => art.packFor(id).file)));
  assert.ok(art.fetched.every(({init}) => init.credentials === 'omit' && init.redirect === 'error'));
  f.send(f.message({...snapshot, mode:'unavailable'}, 2)); f.flush();
  assert.deepEqual(loader.getStatus().selectedAssetIds, []);
  assert.equal(art.fetched.length, 3); assert.equal(f.delivered.length, 2);
  f.api.dispose(); loader.dispose();
});
test('35MB catalogue is metadata only; no combined allocation or pre-core transfer', async () => {
  const f = actorFixture();
  const large = f.actorShards.map(row => ({...row, pack:{...row.pack, bytes:3 * 1024 * 1024}}));
  const loader = bridge.createActorLoader({...f.options, actorShards:large}, f.host);
  const pending = loader.select(f.trio); const rejected = assert.rejects(pending, /superseded/);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(f.fetched.length, 0);
  f.core.resolve(true); await new Promise(resolve => setImmediate(resolve)); assert.equal(f.fetched.length, 0);
  assert.equal(loader.getStatus().knownShards, 13); assert.equal(loader.getStatus().cachedPackBytes, 0);
  loader.dispose(); await rejected; assert.equal(f.copied.length, 0);
});
test('only selected trio downloads; outfit changes add one shard and cached return never refetches world', async () => {
  const f = actorFixture(), loader = bridge.createActorLoader(f.options, f.host); f.release();
  await Promise.all([loader.select(f.trio), loader.select(f.trio)]);
  assert.equal(f.fetched.length, 3); assert.equal(f.mounted.length, 3);
  assert.deepEqual(new Set(f.fetched.map(x => x.file)), new Set(f.trio.map(id => f.packFor(id).file)));
  await loader.select([f.assetIds.hero[1], ...f.trio.slice(1)]);
  assert.equal(f.fetched.length, 4); assert.equal(f.mounted.length, 4);
  await loader.select(f.trio); assert.equal(f.fetched.length, 4);
  assert.equal(loader.getStatus().mountedShards, 4);
  assert.ok(f.copied.every(([path]) => path.startsWith('/camp-actor-')));
  assert.ok(f.fetched.every(({init}) => init.credentials === 'omit' && init.redirect === 'error' && init.mode === 'same-origin'));
  assert.equal(bridge.createActorLoader(f.options, f.host), loader);
  assert.equal(f.timers.size, 0);
});
test('actor downloads are capped at two concurrent jobs', async () => {
  const f = actorFixture(), replies = new Map();
  f.host.fetch = (file,init) => { f.fetched.push({file,init}); const reply = deferred(); replies.set(file, reply); return reply.promise; };
  const loader = bridge.createActorLoader(f.options, f.host); f.release(); const selected = loader.select(f.trio);
  await until(() => f.fetched.length === 2); assert.equal(loader.getStatus().activeDownloads, 2);
  const first = f.fetched[0].file; replies.get(first).resolve(new Response(f.bodies.get(first)));
  await until(() => f.fetched.length === 3);
  assert.ok(loader.getStatus().activeDownloads <= 2);
  for (const {file} of f.fetched.slice(1)) replies.get(file).resolve(new Response(f.bodies.get(file)));
  await selected; assert.equal(f.mounted.length, 3);
});
test('superseded queued/in-flight artwork cannot make late filesystem writes', async () => {
  const f = actorFixture(), late = deferred(), previous = f.packFor(f.assetIds.hero[0]).file;
  const fetch = f.host.fetch;
  f.host.fetch = (file,init) => { if (file !== previous) return fetch(file,init); f.fetched.push({file,init}); return late.promise; };
  const loader = bridge.createActorLoader(f.options, f.host); f.release();
  const old = loader.select([f.assetIds.hero[0]]); const rejected = assert.rejects(old, {name:'AbortError'});
  await until(() => f.fetched.length === 1);
  await loader.select([f.assetIds.hero[1]]); await rejected;
  late.resolve(new Response(f.bodies.get(previous))); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.fetched[0].init.signal.aborted, true);
  assert.equal(f.copied.length, 1); assert.equal(f.mounted.length, 1);
  assert.equal(f.mounted[0][0], '/' + f.packFor(f.assetIds.hero[1]).file);
});
test('actor download failures need explicit retry; uncertain mounts never force world reload or re-mount', async () => {
  const f = actorFixture(); let failDownload = true;
  const fetch = f.host.fetch;
  f.host.fetch = (file,init) => failDownload ? (f.fetched.push({file,init}), Promise.resolve(new Response('', {status:503}))) : fetch(file,init);
  const loader = bridge.createActorLoader(f.options, f.host); f.release();
  await assert.rejects(loader.select([f.trio[0]]), {reloadRequired:false, retryable:true});
  await assert.rejects(loader.select([f.trio[0]])); assert.equal(f.fetched.length, 1);
  failDownload = false; await loader.retry(); assert.equal(f.fetched.length, 2);
  const g = actorFixture(); let rejectMount = true;
  g.options.mountActor = async (...args) => { g.mounted.push(args); if (rejectMount) throw Error('uncertain native mount'); return true; };
  const guarded = bridge.createActorLoader(g.options, g.host); g.release();
  await assert.rejects(guarded.select([g.trio[0]]), {reloadRequired:false, packUncertain:true, retryable:false});
  await assert.rejects(guarded.retry()); assert.equal(g.mounted.length, 1);
  rejectMount = false; await guarded.select([g.assetIds.hero[1]]);
  assert.equal(g.mounted.length, 2); assert.equal(g.status.includes('reload_required'), false);
});
test('actor identifiers, catalogues, resource URLs and library bounds are fail-closed', async () => {
  const f = actorFixture(), loader = bridge.createActorLoader(f.options, f.host);
  for (const ids of [['../../actor'], ['hero/unknown'], [f.trio[0],f.trio[0]], [f.assetIds.hero[0],f.assetIds.hero[1]], 'actor'])
    await assert.rejects(loader.select(ids));
  assert.equal(f.fetched.length, 0);
  for (const change of [{file:'https://other.test/a.pck'}, {bytes:10 * 1024 * 1024}, {token:'secret'}]) {
    const g = actorFixture(); g.actorShards[0].pack = {...g.actorShards[0].pack, ...change};
    assert.throws(() => bridge.createActorLoader(g.options, g.host));
  }
  const g = actorFixture(); g.actorShards[1].assetIds = g.actorShards[0].assetIds;
  assert.throws(() => bridge.createActorLoader(g.options, g.host), /Duplicate/);
  assert.throws(() => bridge.createActorLoader({...f.options, actorShards:f.actorShards.slice(1)}, f.host), /exactly cover/);
  loader.dispose(); await assert.rejects(loader.select(f.trio), /disposed/);
});
test('actor native callback is separately pinned, serialized and idempotently cached', async () => {
  const art = actorFixture(), f = mountFixture(undefined, art.actorShards);
  const actor = art.actorShards[0].pack, other = art.actorShards[1].pack;
  await assert.rejects(f.api.mountActor('/' + actor.file, actor.sha256), /not_ready/);
  f.api.bind(f.callback); const gate = f.api.corePresented(); f.api.coreAccepted(true, 'core_presented'); await gate;
  const runtime = f.api.mount(f.path, f.pack.sha256); f.api.applied(1, true, 'applied'); await runtime;
  await assert.rejects(f.api.mountActor('/outside.pck', actor.sha256), /pin_mismatch/);
  const first = f.api.mountActor('/' + actor.file, actor.sha256), second = f.api.mountActor('/' + other.file, other.sha256);
  assert.equal(f.api.mountActor('/' + actor.file, actor.sha256), first);
  assert.deepEqual(f.calls.at(-1), ['mount_actor',2,'/' + actor.file,actor.sha256]);
  f.api.applied(2, true, 'applied'); await first;
  assert.deepEqual(f.calls.at(-1), ['mount_actor',3,'/' + other.file,other.sha256]);
  f.api.applied(3, false, 'actor_unavailable'); await assert.rejects(second, {reloadRequired:false, packUncertain:true});
  assert.equal(await f.api.mountActor('/' + actor.file,actor.sha256), true);
  assert.equal(f.calls.length, 4); assert.equal(f.timers.size, 0);
});
test('asset loading never delays server pause/waiting or replays a previous display snapshot', async () => {
  const f = fixture(), needed = [], held = deferred();
  f.api.bindAssetLoader(ids => { needed.push(ids); return held.promise; }); f.api.corePresented();
  f.send(f.message()); f.flush(); assert.equal(f.delivered.length, 1); assert.deepEqual(needed[0], [ids.hero[0],ids.pet[0],ids.boss[0]]);
  f.send(f.message({...display(), mode:'paused'},2)); f.flush(); assert.equal(f.delivered.at(-1).mode,'paused');
  f.send(f.message({...display(), mode:'waiting'},3)); f.flush(); assert.deepEqual(needed.at(-1), []);
  held.resolve(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.delivered.length, 3); assert.equal(f.delivered.at(-1).mode,'waiting');
});

test('shared PNG shard is fetched once for multiple actors and later selections', async () => {
  const f = actorFixture();
  f.options.actorShards = [{pack:f.actorShards[0].pack, assetIds:Object.values(f.assetIds).flat()}];
  const loader = bridge.createActorLoader(f.options, f.host); f.release();
  await loader.select(f.trio);
  await loader.select([f.assetIds.hero[5], f.assetIds.pet[5], f.trio[2]]);
  assert.equal(f.fetched.length, 1); assert.equal(f.copied.length, 1); assert.equal(f.mounted.length, 1);
  assert.equal(loader.getStatus().knownShards, 1); assert.equal(loader.getStatus().mountedShards, 1);
});

test('all six heroes and six pets are swappable with one fixed boss and no duplicate transfers', async () => {
  const f = actorFixture(), loader = bridge.createActorLoader(f.options, f.host); f.release();
  for (let index = 0; index < 6; index++) {
    await loader.select([f.assetIds.hero[index], f.assetIds.pet[index], f.assetIds.boss[0]]);
    assert.equal(f.fetched.length, 3 + index * 2);
  }
  await loader.select(f.trio);
  assert.equal(f.fetched.length, 13); assert.equal(f.mounted.length, 13);
  assert.equal(new Set(f.fetched.map(item => item.file)).size, 13);
  assert.equal(loader.getStatus().mountedShards, 13); assert.equal(f.timers.size, 0);
});

test('queued actor jobs retain copied pins, engine and native callback bindings', async () => {
  const f = actorFixture(), loader = bridge.createActorLoader(f.options, f.host), expected = {...f.packFor(f.trio[0])};
  const selected = loader.select([f.trio[0]]);
  f.options.engine = {copyToFS:() => assert.fail('Cannot redirect a queued FS write')};
  f.options.mountActor = () => assert.fail('Cannot redirect a queued native mount');
  f.actorShards[0].pack.file = 'outside.pck';
  f.actorShards[0].assetIds[0] = 'hero/injected';
  f.release(); await selected;
  assert.equal(f.fetched[0].file, expected.file);
  assert.equal(f.copied.length, 1); assert.deepEqual(f.mounted[0], ['/' + expected.file, expected.sha256]);
});

test('rejected or false core/runtime gate prevents every actor fetch and mount', async () => {
  for (const mode of ['core-false', 'runtime-false', 'runtime-rejected', 'core-missing']) {
    const f = actorFixture(), loader = bridge.createActorLoader(f.options, f.host);
    const rejected = assert.rejects(loader.select(f.trio), /gate failed/);
    f.core.resolve(mode === 'core-false' ? false : mode === 'core-missing' ? undefined : true);
    if (mode === 'runtime-rejected') f.runtime.reject(Error('Runtime refused'));
    else f.runtime.resolve(mode !== 'runtime-false');
    await rejected;
    assert.equal(f.fetched.length, 0); assert.equal(f.copied.length, 0); assert.equal(f.mounted.length, 0);
    assert.equal(f.status.at(-1), 'error'); loader.dispose();
  }
});

test('actor size/hash failures cannot copy files and never request world reload', async () => {
  for (const bytes of [new Uint8Array([9,9,9,9]), new Uint8Array([1,2,3]), new Uint8Array([1,2,3,4,5])]) {
    const f = actorFixture(); f.host.fetch = async () => new Response(bytes);
    const loader = bridge.createActorLoader(f.options, f.host); f.release();
    await assert.rejects(loader.select([f.trio[0]]), {reloadRequired:false, retryable:true});
    assert.equal(f.copied.length, 0); assert.equal(f.mounted.length, 0);
    assert.equal(f.status.includes('reload_required'), false); assert.equal(f.timers.size, 0);
  }
});

test('actor channel timeout is terminal only for pending work, cached actors need no re-mount', async () => {
  const art = actorFixture(), f = mountFixture(undefined, art.actorShards);
  f.api.bind(f.callback); const core = f.api.corePresented(); f.api.coreAccepted(true, 'core_presented'); await core;
  const runtime = f.api.mount(f.path, f.pack.sha256); f.api.applied(1, true, 'applied'); await runtime;
  const [first,second,third] = art.actorShards.map(s => s.pack);
  const cached = f.api.mountActor('/' + first.file, first.sha256); f.api.applied(2, true, 'applied'); await cached;
  const waiting = f.api.mountActor('/' + second.file, second.sha256), queued = f.api.mountActor('/' + third.file, third.sha256);
  const failed = assert.rejects(waiting, {reloadRequired:false, packUncertain:true});
  const cancelled = assert.rejects(queued, {reloadRequired:false});
  f.time(30001);
  assert.equal(f.api.applied(3, true, 'applied'), false); await Promise.all([failed,cancelled]);
  assert.equal(await f.api.mountActor('/' + first.file, first.sha256), true);
  assert.equal(f.calls.length, 4); assert.equal(f.timers.size, 0);
  assert.equal(f.api.applied(3, true, 'applied'), false);
});
