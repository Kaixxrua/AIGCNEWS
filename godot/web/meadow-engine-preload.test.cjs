const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shell = fs.readFileSync(path.join(__dirname,'meadow-shell.html'),'utf8');
const source = /<script data-meadow-engine-preload>([\s\S]*?)<\/script>/.exec(shell)[1];

function run(search, engine='index.js', overrides={}) {
  const hints=[];
  let forbiddenCalls=0;
  const forbidden=()=>{forbiddenCalls++;throw Error('No engine, pack fetch, storage, timers or ready side effect');};
  const context={URLSearchParams,location:{search},Engine:forbidden,fetch:forbidden,setTimeout:forbidden,
    localStorage:{getItem:forbidden,setItem:forbidden},
    document:{createElement(tag){assert.equal(tag,'link');return {};},head:{appendChild(hint){hints.push(hint);}}},
    ...overrides};
  vm.runInNewContext(source.replace('$GODOT_URL',engine),context);
  assert.equal(forbiddenCalls,0,'Optional catch must not conceal a forbidden side effect');
  return hints.map(h=>({...h}));
}

for(const quality of ['lite','balanced','original']) test(`early engine: explicit ${quality} downloads only shared WASM hint`,()=>{
  assert.deepEqual(run(`?quality=${quality}&rev=1`),[{rel:'preload',as:'fetch',type:'application/wasm',crossOrigin:'anonymous',href:'index.wasm'}]);
});
test('early engine: no selection, unknown query, saved preferences do not trigger a download',()=>{
  for(const query of ['', '?quality=', '?quality=unknown', '?quality=0', '?other=lite']) assert.deepEqual(run(query),[]);
});
test('early engine: safe local export basename only, no remote/query/unexpanded paths',()=>{
  for(const name of ['$GODOT_URL','../index.js','http://example.invalid/a.js','index.js?x=1']) assert.deepEqual(run('?quality=lite',name),[]);
  assert.equal(run('?quality=lite','meadow-v153.js')[0].href,'meadow-v153.wasm');
});
test('early engine: optional API/DOM failure does not block normal loading',()=>{
  assert.deepEqual(run('?quality=lite','index.js',{URLSearchParams:undefined}),[]);
  assert.deepEqual(run('?quality=lite','index.js',{document:{createElement(){throw Error('blocked');}}}),[]);
});
test('early engine: no eager PCK or engine start and hint precedes UI dependencies',()=>{
  assert.ok(shell.indexOf('data-meadow-engine-preload') < shell.indexOf('<link rel="stylesheet"'));
  assert.equal((shell.match(/data-meadow-engine-preload/g)||[]).length,1);
  assert.ok(!/\b(?:fetch|Engine|sceneReady|engineStarted)\s*\(/.test(source));
});
