/* Real helper + real loader, mocked Engine/DOM/GL only. No browser, network,
 * native light-count proof, GLSL compilation or performance claim.
 * Producer coverage: godot/tools/test_scene_render_contract.py.
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createHash } = require("node:crypto");
const { transformSource } = require("./meadow-webgl-compile.js");

const helperText = fs.readFileSync(path.join(__dirname, "meadow-webgl-compile.js"), "utf8");
const loaderText = fs.readFileSync(path.join(__dirname, "meadow-loader.js"), "utf8");
const reference = fs.readFileSync(path.resolve(__dirname,
  "../../artifacts/startup-v118/godot-analysis/engine-reference/drivers/gles3/shaders/scene.glsl"), "utf8");
assert.equal(createHash("sha256").update(reference).digest("hex"),
  "2c77be0c85b7ab1a85ed8009c77cdb6216f1494d43083592213ad68f9e812977");
// Stock stage and loop bodies; omitted includes mean this is NOT a complete
// compilable/generated shader. Native scene/driver acceptance belongs to main.
const source = "#version 300 es\n#define BASE_PASS\n#define MAX_FORWARD_LIGHTS 8u\n" +
  "precision highp float;\nprecision highp int;\n" +
  reference.slice(reference.indexOf("#[fragment]") + "#[fragment]".length)
    .replace(/^#include[^\r\n]*/gm, "// offline fixture: expanded include omitted");
const CONTRACT = Object.freeze({
  packSha256: "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c",
  spotLights: 0, areaLights: 0
});
const MAP = Object.freeze({ "index-lite.pck": CONTRACT });
const baseline = transformSource(source).source;
const specialized = transformSource(source, { contract: CONTRACT }).source;
const plain = value => JSON.parse(JSON.stringify(value));

test("render contract loader: directional base is explicit and limited to reviewed progressive core", async () => {
  const accepted = ["78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5",
                    "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c"];
  for (const progressive of [true, false]) {
    for (const search of ["", "?fast_compile=scene", "?fast_compile=1", "?fast_compile=0"]) {
      for (const packSha256 of [...accepted, CONTRACT.packSha256, "f".repeat(64)]) {
        const contract = {...CONTRACT, packSha256};
        const h = harness({search, contracts:{"index-lite.pck":contract},
          shader:source.replace("#define BASE_PASS", "#define BASE_PASS\n#define USE_ADDITIVE_LIGHTING")});
        h.window.meadowStream = {activate() {}};
        h.window.meadowDetailStatus = {};
        await h.start({executable:"index",mainPack:"index-lite.pck",progressive});
        const expected = progressive && accepted.includes(packSha256) && search !== "?fast_compile=1" && search !== "?fast_compile=0";
        assert.equal(h.report()?.sceneDirectionalBase ?? false, expected);
        assert.equal(h.report()?.specializedCalls ?? 0, expected ? 1 : 0);
        h.selection("index-lite.pck");
        for (const cleanup of h.cleanups) cleanup();
      }
    }
  }
});

function harness({ search = "?fast_compile=scene", contracts = MAP,
  helper = true, urlAPI = true, shader = source, phase, failure } = {}) {
  const h = { events: [], installs: [], engines: [], preloads: [], starts: [],
    nativeCalls: [], cleanups: [], cleanupCalls: 0, result: {} };
  class Canvas {
    constructor() {
      this.width = 1280; this.height = 800; this.dataset = {};
      this.gl = new GL(this);
    }
    getContext(...args) {
      h.events.push("getContext");
      assert.equal(args[0], "webgl2");
      return this.gl;
    }
  }
  class GL {
    constructor(canvas) { this.canvas = canvas; }
    shaderSource(...args) {
      h.nativeCalls.push({ receiver: this, args });
      if (phase === "native-source" && this.canvas === h.canvas) throw failure;
      return h.result;
    }
  }
  h.canvas = new Canvas();
  h.other = new Canvas();
  h.Canvas = Canvas; h.GL = GL;
  h.originalContext = Canvas.prototype.getContext;
  h.originalSource = GL.prototype.shaderSource;
  const forbidden = () => { throw new Error("No fetch, logs, timers or extra GL calls allowed"); };
  const window = { HTMLCanvasElement: Canvas, WebGL2RenderingContext: GL,
    location: { search }, performance: { now: () => 0 }, MEADOW_RENDER_CONTRACTS: contracts };
  const context = { window, fetch: forbidden, setTimeout: forbidden,
    console: { log: forbidden, info: forbidden, warn: forbidden, error: forbidden } };
  if (urlAPI) context.URLSearchParams = URLSearchParams;
  h.window = window;
  if (helper) {
    vm.runInNewContext(helperText, context);
    h.api = window.meadowWebglCompile;
    // Spy preserves the actual option object and invokes the ACTUAL helper.
    window.meadowWebglCompile = { ...h.api, install(canvas, options) {
      h.events.push("install");
      h.installs.push({ canvas, options });
      const dispose = h.api.install(canvas, options);
      const cleanup = () => { h.cleanupCalls++; dispose(); };
      h.cleanups.push(cleanup);
      return cleanup;
    } };
  }
  class Engine {
    constructor(config) {
      this.config = config; h.engines.push(this); h.events.push("constructor");
    }
    init(executable) {
      h.events.push("init"); this.executable = executable;
      if (phase === "init-reject") return Promise.reject(failure);
      return Promise.resolve();
    }
    preloadFile(...args) {
      h.events.push("preloadFile"); h.preloads.push(args);
      return Promise.resolve();
    }
    start(options) {
      h.events.push("start"); h.starts.push(options);
      const gl = this.config.canvas.getContext("webgl2", { antialias: false });
      gl.shaderSource({}, shader);
      return Promise.resolve();
    }
  }
  vm.runInNewContext(loaderText, { ...context, Engine });
  h.start = (config = { executable: "index", mainPack: "index-lite.pck" }, options = {}, canvas = h.canvas) =>
    window.meadowLoader.start(config, { ...options, canvas }, canvas);
  h.report = (canvas = h.canvas) => canvas.dataset.fastCompile ? JSON.parse(canvas.dataset.fastCompile) : undefined;
  h.submitted = () => h.nativeCalls.at(-1).args[1];
  h.selection = (pack, args = []) => {
    assert.equal(h.engines.length, 1, "one Engine for this navigation");
    assert.deepEqual(h.preloads, [[pack, pack]], "only selected PCK is preloaded, with its exact FS path");
    assert.deepEqual(plain(h.starts), [{ args: ["--main-pack", pack, ...args] }]);
    assert.equal(Canvas.prototype.getContext, h.originalContext);
    assert.equal(GL.prototype.shaderSource, h.originalSource);
    assert.deepEqual([h.canvas.width, h.canvas.height], [1280, 800]);
    assert.equal(Object.hasOwn(h.other.gl, "shaderSource"), false);
  };
  return h;
}

test("render contract loader: default enables only the selected known pack's verified contract", async () => {
  for (const packSha256 of [CONTRACT.packSha256, "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79"]) {
    for (const search of ["", "?quality=lite", "?quality=original&startup_trace=0"]) {
      const contract = { ...CONTRACT, packSha256 };
      const reads = [];
      const contracts = new Proxy({ "index-lite.pck": contract }, {
        get(target, name) { reads.push(name); return target[name]; }
      });
      const h = harness({ search, contracts });
      assert.equal(h.installs.length, 0, "loading the helper itself never enables anything");
      assert.equal(h.nativeCalls.length, 0);
      await h.start();
      assert.deepEqual(reads, ["index-lite.pck"], "lookup uses the actual selected pack, not a quality query label");
      assert.equal(h.installs.length, 1);
      assert.equal(h.installs[0].options.contract, contract);
      assert.deepEqual(h.events.slice(0, 2), ["install", "constructor"]);
      assert.equal(h.submitted(), specialized);
      assert.equal(h.report().specializationPackSha256, packSha256);
      assert.equal(h.report().specializedCalls, 1);
      assert.equal(h.report().specializationDefinesAdded, 2);
      h.selection("index-lite.pck");
      h.cleanups[0]();
    }
  }
});

test("render contract loader: default leaves original, balanced and unknown packs completely stock", async () => {
  for (const pack of ["index.pck", "index-balanced.pck", "future-boss.pck", "index-lite.future.pck"]) {
    const h = harness({ search: "?quality=lite" });
    await h.start({ executable: "index", mainPack: pack }, { mainPack: "index-lite.pck" });
    assert.equal(h.installs.length, 0, "another pack's contract cannot auto-enable this pack");
    assert.equal(h.submitted(), source);
    assert.equal(h.report(), undefined);
    assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
    assert.equal(Object.hasOwn(h.canvas.gl, "shaderSource"), false);
    h.selection(pack);
  }
});

test("render contract loader: default without a built contract stays stock even for a lite filename", async () => {
  for (const contracts of [null, {}, false, []]) {
    const h = harness({ search: "", contracts });
    await h.start();
    assert.equal(h.installs.length, 0);
    assert.equal(h.submitted(), source);
    assert.equal(h.report(), undefined);
    h.selection("index-lite.pck");
  }
  const h = harness({ search: "" });
  delete h.window.MEADOW_RENDER_CONTRACTS;
  await h.start();
  assert.equal(h.installs.length, 0);
  assert.equal(h.submitted(), source);
  h.selection("index-lite.pck");
});

test("render contract loader: explicit stock and unknown query modes do not install or read the contract", async () => {
  const unreadable = new Proxy({}, { get() { throw new Error("inactive contract access"); } });
  for (const search of ["?fast_compile=0", "?fast_compile=false", "?fast_compile=",
    "?fast_compile=SCENE", "?fast_compile=scene%20", "?fast_compile=2", "?fast_compile=0&fast_compile=scene"]) {
    const h = harness({ search, contracts: unreadable });
    await h.start();
    assert.equal(h.installs.length, 0, search);
    assert.equal(h.submitted(), source);
    assert.equal(h.report(), undefined);
    h.selection("index-lite.pck");
  }
});

test("render contract loader: fast_compile=1 is loop-only even with an available scene contract", async () => {
  for (const contracts of [MAP, new Proxy({}, { get() { throw new Error("loop-only contract access"); } })]) {
    const h = harness({ search: "?fast_compile=1", contracts });
    await h.start();
    assert.equal(h.installs[0].options.contract, undefined);
    assert.equal(h.submitted(), baseline);
    assert.equal(h.report().specializedCalls, 0);
    h.selection("index-lite.pck");
  }
});

test("render contract loader: scene mode forwards the exact selected pack contract before Engine creation", async () => {
  const h = harness();
  const args = ["--", "--meadow-quality=lite"];
  const config = { executable: "index", mainPack: "index-lite.pck", args };
  const options = { focusCanvas: false };
  await h.start(config, options);
  assert.equal(h.installs.length, 1);
  assert.equal(h.installs[0].canvas, h.canvas);
  assert.equal(h.installs[0].options.contract, CONTRACT);
  assert.deepEqual(h.events.slice(0, 2), ["install", "constructor"]);
  assert.equal(h.submitted(), specialized);
  assert.equal(h.report().specializationPackSha256, CONTRACT.packSha256);
  assert.equal(h.report().specializedCalls, 1);
  assert.equal(h.report().specializationDefinesAdded, 2);
  assert.equal(h.report().rewrittenLoops, 3);
  assert.equal(h.report().nativeFailures, 0);
  assert.equal(h.engines[0].config.focusCanvas, false);
  assert.deepEqual(config, { executable: "index", mainPack: "index-lite.pck", args });
  assert.deepEqual(options, { focusCanvas: false });
  h.selection("index-lite.pck", args);
});

test("render contract loader: v124 frozen v117 hash is preserved while a subsequent unknown hash stays loop-only", async () => {
  const v117LiteSha = "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79";
  for (const packSha256 of [v117LiteSha, "f".repeat(64)]) {
    const contract = { ...CONTRACT, packSha256 };
    const h = harness({ contracts: { "index-lite.pck": contract } });
    await h.start();
    assert.equal(h.installs[0].options.contract, contract);
    assert.equal(h.submitted(), packSha256 === v117LiteSha ? specialized : baseline);
    assert.equal(h.report().specializationPackSha256, packSha256 === v117LiteSha ? v117LiteSha : null);
    assert.equal(h.report().specializedCalls, packSha256 === v117LiteSha ? 1 : 0);
    h.selection("index-lite.pck");
    h.cleanups[0]();
  }
});

test("render contract loader: actual config.mainPack wins over query labels and engine option aliases", async () => {
  for (const pack of ["index.pck", "index-balanced.pck", "future-boss.pck", "index-lite.future.pck"] ) {
    const h = harness({ search: "?fast_compile=scene&quality=lite&mainPack=index-lite.pck" });
    await h.start({ executable: "index", mainPack: pack }, { mainPack: "index-lite.pck" });
    assert.equal(h.installs[0].options.contract, undefined, pack);
    assert.equal(h.submitted(), baseline);
    assert.equal(h.report().specializationPackSha256, null);
    assert.equal(h.report().specializedCalls, 0);
    h.selection(pack);
  }
});

test("render contract loader: absent/null/empty map has no quality fallback or implicit contract", async () => {
  for (const contracts of [null, {}, false, []]) {
    const h = harness({ contracts });
    await h.start();
    assert.equal(h.installs[0].options.contract, undefined);
    assert.equal(h.submitted(), baseline);
    assert.equal(h.report().specializedCalls, 0);
    h.selection("index-lite.pck");
  }
  const h = harness();
  delete h.window.MEADOW_RENDER_CONTRACTS;
  await h.start();
  assert.equal(h.installs[0].options.contract, undefined);
  assert.equal(h.submitted(), baseline);
});

test("render contract loader: same filename with future hash, invalid contract or nonzero counts stays loop-only", async () => {
  const invalid = [undefined, null, false, [], {}, { ...CONTRACT, packSha256: "f".repeat(64) },
    { ...CONTRACT, packSha256: CONTRACT.packSha256.toUpperCase() },
    { get packSha256() { throw new Error("malformed optional contract"); } }];
  for (const field of ["spotLights", "areaLights"])
    for (const value of [undefined, null, "0", false, -1, 1]) invalid.push({ ...CONTRACT, [field]: value });
  for (const contract of invalid) {
    const h = harness({ contracts: { "index-lite.pck": contract } });
    await h.start();
    assert.equal(h.installs[0].options.contract, contract, "test exercises helper validation, not a mocked substitute");
    assert.equal(h.submitted(), baseline);
    assert.equal(h.report().specializationPackSha256, null);
    assert.equal(h.report().specializedCalls, 0);
    h.selection("index-lite.pck");
  }
});

test("render contract loader: missing mainPack uses executable.pck for both lookup and preload", async () => {
  for (const mainPack of [undefined, null, ""]) {
    const h = harness();
    await h.start({ executable: "index", mainPack });
    assert.equal(h.installs[0].options.contract, undefined);
    assert.equal(h.submitted(), baseline);
    h.selection("index.pck");
  }
  const h = harness({ contracts: { "renamed.pck": CONTRACT } });
  await h.start({ executable: "renamed" });
  assert.equal(h.installs[0].options.contract, CONTRACT);
  assert.equal(h.submitted(), specialized);
  assert.equal(h.engines[0].executable, "renamed");
  h.selection("renamed.pck");
});

test("render contract loader: helper absence remains safe in legacy VMs without URLSearchParams", async () => {
  const h = harness({ helper: false, urlAPI: false });
  await h.start();
  assert.equal(h.installs.length, 0);
  assert.equal(h.submitted(), source);
  assert.equal(h.report(), undefined);
  h.selection("index-lite.pck");
});

test("render contract loader: accepted metadata cannot bypass fragment and variant source guards", async () => {
  for (const shader of ["void main() {}", source.replace("#define BASE_PASS", "#define BASE_PASS\n#define USE_VERTEX_LIGHTING")]) {
    const h = harness({ shader });
    await h.start();
    assert.equal(h.submitted(), transformSource(shader).source);
    assert.equal(h.report().specializedCalls, 0);
    h.selection("index-lite.pck");
  }
});

test("render contract loader: success retains night specialization; next pack/canvas does not inherit it", async () => {
  const h = harness();
  await h.start();
  const firstWrapper = h.canvas.gl.shaderSource;
  assert.equal(h.cleanupCalls, 0);
  assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
  const night = source.replace("#CODE : LIGHT", "float m_night_fixture = 1.0;");
  h.canvas.gl.shaderSource({}, night);
  assert.equal(h.submitted(), transformSource(night, { contract: CONTRACT }).source);
  assert.equal(h.report().specializedCalls, 2);
  assert.equal(h.report().specializationDefinesAdded, 4);
  h.other.gl.shaderSource({}, night);
  assert.equal(h.submitted(), night, "unrelated context must still be native");
  h.window.MEADOW_RENDER_CONTRACTS = { "index-lite.pck": { ...CONTRACT, packSha256: "f".repeat(64) } };
  await h.start({ executable: "index", mainPack: "index-lite.pck" }, {}, h.other);
  assert.equal(h.submitted(), baseline);
  assert.equal(h.report(h.other).specializedCalls, 0);
  assert.equal(h.report(h.other).specializationPackSha256, null);
  assert.equal(h.canvas.gl.shaderSource, firstWrapper);
  assert.equal(h.report().specializedCalls, 2, "new pack did not alter the prior frozen canvas contract");
  assert.equal(h.engines.length, 2);
  assert.deepEqual(h.preloads, [["index-lite.pck", "index-lite.pck"], ["index-lite.pck", "index-lite.pck"]]);
  for (const cleanup of h.cleanups) cleanup();
  assert.equal(Object.hasOwn(h.canvas.gl, "shaderSource"), false);
  assert.equal(Object.hasOwn(h.other.gl, "shaderSource"), false);
});

test("render contract loader: scene-mode failures dispose only the target and preserve original errors", async () => {
  for (const phase of ["init-reject", "native-source"]) {
    const failure = new Error(`original ${phase}`);
    const h = harness({ phase, failure });
    const otherCleanup = h.api.install(h.other, { contract: CONTRACT });
    h.other.getContext("webgl2");
    const otherWrapper = h.other.gl.shaderSource;
    const otherState = h.other.dataset.fastCompile;
    await assert.rejects(h.start(), error => error === failure);
    assert.equal(h.cleanupCalls, 1);
    assert.equal(h.report().status, "disposed");
    assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
    assert.equal(Object.hasOwn(h.canvas.gl, "shaderSource"), false);
    assert.equal(h.other.gl.shaderSource, otherWrapper);
    assert.equal(h.other.dataset.fastCompile, otherState);
    h.other.gl.shaderSource({}, source);
    assert.equal(h.submitted(), specialized);
    otherCleanup();
  }
});
