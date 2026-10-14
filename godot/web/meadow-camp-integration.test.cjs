const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'meadow-camp-integration.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness({embedded=true, enabled=true}={}) {
  const calls = [], events = {};
  let acceptCore;
  const native = new Promise(resolve => {acceptCore=resolve;});
  const bridge = {corePresented:()=>calls.push('bridge-core'), report:value=>calls.push(['status',value]),dispose:()=>calls.push('dispose-bridge')};
  const mount = {corePresented:()=>{calls.push('native-core');return native;},mount:async()=>true,dispose:()=>calls.push('dispose-mount')};
  const window = {location:{origin:'https://site.test',search:enabled?'?camp=1':''},parent:{},
    addEventListener:(name,fn)=>{events[name]=fn;},MeadowCampBridge:{
      create:config=>{calls.push(['bridge',config]);return bridge;},
      createMountClient:config=>{calls.push(['mount-client',config]);return mount;},
      loadPackAfterCore:async options=>{calls.push('queued-pack');await options.coreReady;calls.push('download-pack');},
    }};
  if(!embedded)window.parent=window;
  vm.runInNewContext(source,{window,URLSearchParams,console});
  const config = {version:1,source:'frozen-v153',optionalPack:{file:'camp-presentation-aaaaaaaaaaaa.pck',bytes:1,sha256:'a'.repeat(64)},
    assetIds:{hero:['hero_ranger'],pet:['pet_deer'],boss:['boss_ancient_guardian']},bindings:{}};
  for(const [tier,file] of Object.entries({original:'index.pck',balanced:'index-balanced.pck',lite:'index-lite.pck'})) {
    const variant=tier==='lite'?'lite':'full',sha=variant==='lite'?'b'.repeat(64):'c'.repeat(64);
    config.bindings[tier]={mainPack:file,selectedPack:{file,bytes:100,sha256:'d'.repeat(64)},coreSha256:'d'.repeat(64),
      settingsVariant:variant,progressive:tier==='lite',bootstrap:{file:`camp-bootstrap-${variant}-${sha.slice(0,12)}.pck`,bytes:200,sha256:sha}};
  }
  return {api:window.meadowCampIntegration,config,calls,window,events,acceptCore};
}
test('standalone and unrequested pages install no bridge and load no add-on',()=>{
  for(const args of [{embedded:false},{enabled:false}]){const h=harness(args);assert.equal(h.api.initialize(h.config),false);assert.deepEqual(h.calls,[]);assert.equal(h.api.overrideChoice('lite',{}),null);}
});
test('same-origin authority is fixed and every tier binds its selected immutable pack',()=>{
  const h=harness();assert.equal(h.api.initialize(h.config),true);
  assert.equal(h.calls.find(x=>Array.isArray(x)&&x[0]==='bridge')[1].allowedParentOrigin,'https://site.test');
  for(const tier of Object.keys(h.config.bindings)) {
    const choice=h.api.overrideChoice(tier,{pack:h.config.bindings[tier].mainPack,bytes:100});
    assert.equal(choice.bootstrap.kind,'camp-wrapper');assert.equal(choice.bootstrap.selectedPack.file,choice.pack);
    assert.equal(choice.bootstrap.settingsVariant,tier==='lite'?'lite':'full');
  }
  assert.throws(()=>h.api.overrideChoice('lite',{pack:'index.pck',bytes:100}),/mismatch/);
  assert.throws(()=>h.api.overrideChoice('lite',{pack:'index-lite.pck',bytes:101}),/mismatch/);
  assert(!h.calls.includes('queued-pack'));
});
test('actual core gate and native acknowledgement both precede optional transfer',async()=>{
  const h=harness();h.api.initialize(h.config);
  const choice=h.api.overrideChoice('lite',{pack:'index-lite.pck',bytes:100});
  h.api.attachEngine({}, {mainPack:'index-lite.pck',campPresentation:true,bootstrap:choice.bootstrap},{dataset:{}});
  assert(!h.calls.includes('queued-pack'));
  h.api.corePresented();await tick();assert(h.calls.includes('queued-pack'));assert(!h.calls.includes('download-pack'));
  h.acceptCore(true);await tick();assert(h.calls.includes('download-pack'));
  h.api.corePresented();assert.equal(h.calls.filter(x=>x==='queued-pack').length,1);
});
test('invalid wrapper/settings/pack identities fail before bridge installation',()=>{
  for(const mutate of [c=>c.source='unknown',c=>c.bindings.original.settingsVariant='lite',c=>c.bindings.lite.bootstrap.file='../foreign.pck',c=>c.bindings.lite.coreSha256='0'.repeat(64)]) {
    const h=harness();mutate(h.config);assert.throws(()=>h.api.initialize(h.config));assert.deepEqual(h.calls,[]);
  }
});
test('old engine or a disposed page cannot restart the integration',()=>{
  const h=harness();h.api.initialize(h.config);const choice=h.api.overrideChoice('lite',{pack:'index-lite.pck',bytes:100});
  const config={mainPack:'index-lite.pck',campPresentation:true,bootstrap:choice.bootstrap};
  h.api.attachEngine({},config,{dataset:{}});assert.throws(()=>h.api.attachEngine({},config,{dataset:{}}));
  h.events.pagehide();h.api.corePresented();assert(!h.calls.includes('queued-pack'));
});
test('actor shards are bound only after core and reuse the same native/runtime gates',async()=>{
  const h=harness();let actorOptions,selection;const retry=()=>Promise.resolve(true);let disposed=false;
  h.config.actorShards=[{id:'hero_ranger',pack:{file:'camp-actor-eeeeeeeeeeee.pck',bytes:1,sha256:'e'.repeat(64)}}];
  h.window.MeadowCampBridge.createActorLoader=options=>{actorOptions=options;return{select:value=>{selection=value;},retry,dispose:()=>{disposed=true;}};};
  const original=h.window.MeadowCampBridge.create;
  h.window.MeadowCampBridge.create=config=>({...original(config),bindAssetLoader:select=>{select({mode:'demo'});h.calls.push('actor-loader-bound');}});
  h.api.initialize(h.config);const choice=h.api.overrideChoice('lite',{pack:'index-lite.pck',bytes:100});
  const engine={};h.api.attachEngine(engine,{mainPack:'index-lite.pck',campPresentation:true,bootstrap:choice.bootstrap},{dataset:{}});
  assert.equal(actorOptions,undefined);assert.equal(h.api.retryActors(),false);
  h.api.corePresented();await tick();assert(actorOptions);assert.equal(actorOptions.engine,engine);
  assert.deepEqual(selection,{mode:'demo'});assert(!h.calls.includes('download-pack'));assert.equal(h.api.retryActors(),false);
  h.acceptCore(true);await actorOptions.runtimeReady;await tick();assert.equal(h.api.retryActors(),true);
  h.events.pagehide();assert(disposed);assert.equal(h.api.retryActors(),false);
});
