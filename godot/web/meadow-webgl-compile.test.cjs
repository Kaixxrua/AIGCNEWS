/* Offline structural/semantic tests, not GLSL compilation or a Web performance claim. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createHash } = require("node:crypto");
const { transformSource, pin } = require("./meadow-webgl-compile.js");
const helper = fs.readFileSync(path.join(__dirname, "meadow-webgl-compile.js"), "utf8");
const reference = fs.readFileSync(path.resolve(__dirname,
  "../../artifacts/startup-v118/godot-analysis/engine-reference/drivers/gles3/shaders/scene.glsl"), "utf8");
const fragment = reference.slice(reference.indexOf("#[fragment]") + "#[fragment]".length);
// Godot's build expands includes before shaderSource. We omit those unrelated
// definitions here, retaining the real stock loop bodies and all stage text.
// This fixture must not be mistaken for a complete compilable generated shader.
const source = "#version 300 es\n#define MAX_FORWARD_LIGHTS 8u\nprecision highp float;\nprecision highp int;\n" +
  fragment.replace(/^#include[^\r\n]*/gm, "// offline fixture: expanded include omitted");

function expectedRewrite(input) {
  let result = input;
  for (const kind of ["omni", "spot", "area"]) {
    const original = `for (uint i = 0u; i < MAX_FORWARD_LIGHTS; i++) {\n\t\tif (i >= ${kind}_light_count) {\n\t\t\tbreak;\n\t\t}`;
    const replacement = `for (uint i = 0u; i < min(uint(MAX_FORWARD_LIGHTS), ${kind}_light_count); i++) {\n\t\t` +
      `if (i >= ${kind}_light_count) {\n\t\t\tbreak;\n\t\t}`.replace(/[^\r\n]/g, " ");
    assert.equal(result.split(original).length, 2, `one stock ${kind} loop`);
    result = result.replace(original, replacement);
  }
  return result;
}

test("pins the inspected Godot 4.7.2 stock template, not a moving upstream file", () => {
  assert.equal(createHash("sha256").update(reference).digest("hex"),
    "2c77be0c85b7ab1a85ed8009c77cdb6216f1494d43083592213ad68f9e812977");
  assert.equal(pin, "godot-4.7.2-ed1daf0bf-scene-forward-loops-v1");
});

test("stock fragment changes exactly three bounds and only their first equivalent guards", () => {
  const result = transformSource(source);
  assert.equal(result.changed, true);
  assert.equal(result.loops, 3);
  assert.equal(result.source, expectedRewrite(source), "all other math, samples, blocks and defines remain byte-exact");
  assert.equal(result.source.split("\n").length, source.split("\n").length);
  assert.equal((result.source.match(/min\(uint\(MAX_FORWARD_LIGHTS\), (omni|spot|area)_light_count\)/g) || []).length, 3);
});

test("rewriting is idempotent and does not change already uniform-bounded shaders", () => {
  const first = transformSource(source);
  const second = transformSource(first.source);
  assert.equal(second.changed, false);
  assert.equal(second.source, first.source);
});

test("stock whitespace, CRLF, comments/braces and redundant highp preserve the same rewrite", () => {
  const variants = [
    source.replace(/\n/g, "\r\n"),
    source.replace(/for \(uint i = 0u; i < MAX_FORWARD_LIGHTS; i\+\+\) \{/g,
      "for(highp uint i=0u;i<MAX_FORWARD_LIGHTS;i++){ /* } fake brace { */"),
    source.replace(/if \(i >= (\w+_light_count)\) \{\n\t\t\tbreak;/g,
      "if(i >= $1){ /* do not parse this } */\n break ;"),
    source.replace(/uniform uint (\w+_light_(?:count|indices))/g, "uniform highp uint $1"),
  ];
  for (const input of variants) {
    const result = transformSource(input);
    assert.equal(result.changed, true);
    assert.equal(result.loops, 3);
    assert.equal(result.source.split("\n").length, input.split("\n").length);
    assert.equal((result.source.match(/min\(uint\(MAX_FORWARD_LIGHTS\),/g) || []).length, 3);
  }
});

test("custom material math outside the three pinned loop bodies is preserved verbatim", () => {
  const custom = "float m_custom_light(vec3 v) { for (int j=0;j<72;j++){ if(j>32){break;} } return sin(v.x); }";
  const input = source.replace("#CODE : LIGHT", custom);
  assert.equal(transformSource(input).source, expectedRewrite(input));
  assert.equal(transformSource(input).source.includes(custom), true);
});

for (const [name, change] of [
  ["unknown loop body", s => s.replace("light_process_area(area_light_indices[i], vertex,", "light_process_area(area_light_indices[i], changed_vertex,")],
  ["different first comparison", s => s.replace("if (i >= omni_light_count)", "if (i > omni_light_count)")],
  ["different count", s => s.replace("if (i >= omni_light_count)", "if (i >= spot_light_count)")],
  ["work before break", s => s.replace("if (i >= omni_light_count)", "alpha += 1.0; if (i >= omni_light_count)")],
  ["extra statement in guard", s => s.replace("if (i >= omni_light_count) {", "if (i >= omni_light_count) { alpha += 1.0;")],
  ["unbraced guard", s => s.replace(/if \(i >= omni_light_count\) \{\s*break;\s*\}/, "if (i >= omni_light_count) break;")],
  ["signed iterator", s => s.replace("for (uint i = 0u; i < MAX_FORWARD_LIGHTS; i++)", "for (int i = 0; i < MAX_FORWARD_LIGHTS; i++)")],
  ["missing uniform contract", s => s.replace("uniform uint omni_light_count;", "uniform int omni_light_count;")],
  ["missing stage contract", s => s.replace("out vec4 frag_color;", "out vec4 unknown_color;")],
  ["other GLSL version", s => s.replace("#version 300 es", "#version 330")],
  ["low precision default", s => s.replace("precision highp int;", "precision mediump int;")],
  ["redefined precision default", s => s.replace("precision highp int;", "precision highp int;\nprecision lowp int;")],
  ["nonliteral cap", s => s.replace("#define MAX_FORWARD_LIGHTS 8u", "#define MAX_FORWARD_LIGHTS get_cap()")],
  ["negative cap", s => s.replace("#define MAX_FORWARD_LIGHTS 8u", "#define MAX_FORWARD_LIGHTS -1u")],
  ["overflow cap", s => s.replace("#define MAX_FORWARD_LIGHTS 8u", "#define MAX_FORWARD_LIGHTS 4294967296u")],
  ["cap redefinition", s => s + "\n#define MAX_FORWARD_LIGHTS 4u\n"],
  ["cap undefinition", s => s + "\n#undef MAX_FORWARD_LIGHTS\n"],
  ["min macro replacement", s => s + "\n#define min(a,b) a\n"],
  ["unclosed comment", s => s + "\n/* unterminated"],
  ["mismatched body brace", s => s.replace("light_process_area(area_light_indices[i],", "{ light_process_area(area_light_indices[i],")],
]) {
  test(`${name} fails closed as a transformation and passes the original string unchanged`, () => {
    const input = change(source);
    const result = transformSource(input);
    assert.equal(result.changed, false);
    assert.equal(result.source, input);
    assert.equal(result.loops, 0);
  });
}

test("vertex, unrelated, comment-only, oversized and non-string inputs are untouched", () => {
  const value = { toString() { throw new Error("must not coerce"); } };
  const vertex = source.slice(0, source.indexOf("precision highp int;") + 20) +
    reference.slice(reference.indexOf("#[vertex]"), reference.indexOf("#[fragment]"));
  for (const input of [vertex, "void main() {}", `/* ${source} */`, source + " ".repeat(2 * 1024 * 1024),
    undefined, null, 7, value]) {
    const result = transformSource(input);
    assert.equal(result.source, input);
    assert.equal(result.changed, false);
  }
});

test("light iteration count/order remain exact for zero, below cap, equal cap and above cap", () => {
  for (const cap of [0, 1, 8, 32, 256]) {
    assert.equal(transformSource(source.replace("MAX_FORWARD_LIGHTS 8u", `MAX_FORWARD_LIGHTS ${cap}u`)).changed, true);
    for (const count of [0, 1, Math.max(0, cap - 1), cap, cap + 1, 0xffffffff]) {
      const before = [], after = [];
      for (let i = 0; i < cap; i++) { if (i >= count) break; before.push(i); }
      for (let i = 0; i < Math.min(cap, count); i++) after.push(i);
      assert.deepEqual(after, before);
      assert.equal(after.length, Math.min(cap, count));
    }
  }
  assert.equal(transformSource(source.replace("MAX_FORWARD_LIGHTS 8u", "MAX_FORWARD_LIGHTS 4294967295u")).changed, true);
});

function browser(options = {}) {
  const h = { calls: [], writes: 0, sourceError: null, contextError: null, result: {} };
  class Canvas {
    constructor() {
      this.width = 1280; this.height = 800;
      this.dataset = new Proxy({}, { set(target, key, value) {
        if (options.telemetryThrows) throw new Error("dataset unavailable");
        h.writes++; target[key] = value; return true;
      } });
    }
    getContext(...args) {
      h.calls.push({ name: "getContext", receiver: this, args });
      if (h.contextError) throw h.contextError;
      return this.nextContext;
    }
  }
  class GL {
    constructor(canvas) { this.canvas = canvas; }
    shaderSource(...args) {
      h.calls.push({ name: "shaderSource", receiver: this, args });
      if (h.sourceError) throw h.sourceError;
      return h.result;
    }
  }
  const unexpected = () => { throw new Error("No logs, timers, downloads or additional GL operations allowed"); };
  const root = { HTMLCanvasElement: Canvas, WebGL2RenderingContext: GL,
    location: { search: "?fast_compile=1" }, fetch: unexpected, setTimeout: unexpected,
    console: { log: unexpected, info: unexpected, warn: unexpected, error: unexpected } };
  vm.runInNewContext(helper, { window: root, console: root.console, fetch: unexpected, setTimeout: unexpected });
  h.api = root.meadowWebglCompile;
  h.Canvas = Canvas; h.GL = GL;
  h.canvas = new Canvas(); h.other = new Canvas();
  h.gl = h.canvas.nextContext = new GL(h.canvas);
  h.otherGL = h.other.nextContext = new GL(h.other);
  h.originalContext = Canvas.prototype.getContext;
  h.originalSource = GL.prototype.shaderSource;
  h.read = () => JSON.parse(h.canvas.dataset.fastCompile);
  h.bind = installOptions => { h.cleanup = h.api.install(h.canvas, installOptions); h.canvas.getContext("webgl2"); };
  return h;
}

test("merely loading the helper never installs or fetches, even with fast_compile=1", () => {
  const h = browser();
  assert.equal(h.calls.length, 0);
  assert.equal(h.writes, 0);
  assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
  assert.equal(Object.hasOwn(h.gl, "shaderSource"), false);
  assert.equal(h.Canvas.prototype.getContext, h.originalContext);
  assert.equal(h.GL.prototype.shaderSource, h.originalSource);
});

test("explicit install is per-canvas/idempotent, preserves context args/result, and restores getContext after binding", () => {
  const h = browser();
  const cleanup = h.api.install(h.canvas);
  assert.equal(h.api.install(h.canvas), cleanup);
  assert.equal(h.calls.length, 0, "never create a context with invented attributes");
  const attributes = { alpha: false, antialias: false };
  assert.equal(h.canvas.getContext("webgl2", attributes), h.gl);
  assert.equal(h.calls[0].args[1], attributes);
  assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
  assert.equal(Object.hasOwn(h.gl, "shaderSource"), true);
  assert.equal(h.read().status, "bound");
  assert.deepEqual([h.canvas.width, h.canvas.height], [1280, 800]);
  assert.equal(h.Canvas.prototype.getContext, h.originalContext);
  assert.equal(h.GL.prototype.shaderSource, h.originalSource);
});

test("target shaderSource preserves receiver/shader/extra args/return and transforms only its source", () => {
  const h = browser(); h.bind();
  const shader = {}, extra = {};
  assert.equal(h.gl.shaderSource(shader, source, extra), h.result);
  const call = h.calls.at(-1);
  assert.equal(call.receiver, h.gl);
  assert.equal(call.args[0], shader);
  assert.equal(call.args[1], expectedRewrite(source));
  assert.equal(call.args[2], extra);
  assert.equal(h.calls.length, 2, "one native getContext and one native shaderSource; no status queries");
  assert.equal(h.read().rewrittenCalls, 1);
  assert.equal(h.read().rewrittenLoops, 3);
  assert.match(h.read().evidence[0].originalFnv, /^[a-f0-9]{8}$/);
  assert.notEqual(h.read().evidence[0].originalFnv, h.read().evidence[0].transformedFnv);
});

test("unmatched sources and non-string arguments retain identity; unrelated/borrowed contexts are not rewritten", () => {
  const h = browser(); h.bind();
  const input = { toString() { throw new Error("not an engine string"); } };
  assert.equal(h.gl.shaderSource({}, input), h.result);
  assert.equal(h.calls.at(-1).args[1], input);
  h.gl.shaderSource({}, "unknown shader");
  assert.equal(h.calls.at(-1).args[1], "unknown shader");
  h.otherGL.shaderSource({}, source);
  assert.equal(h.calls.at(-1).args[1], source);
  h.gl.shaderSource.call(h.otherGL, {}, source);
  assert.equal(h.calls.at(-1).args[1], source);
  assert.equal(Object.hasOwn(h.otherGL, "shaderSource"), false);
});

test("only a real target-owned WebGL2 context binds, not 2D, null, lookalikes or another canvas", () => {
  const h = browser(); h.api.install(h.canvas);
  const real = h.gl;
  for (const [kind, result] of [["2d", real], ["webgl", real], ["webgl2", null],
    ["webgl2", { canvas: h.canvas, shaderSource() {} }], ["webgl2", h.otherGL]]) {
    h.canvas.nextContext = result;
    assert.equal(h.canvas.getContext(kind), result);
    assert.equal(h.read().status, "waiting-context");
    assert.equal(Object.hasOwn(real, "shaderSource"), false);
  }
  h.canvas.nextContext = real;
  h.canvas.getContext("webgl2");
  assert.equal(h.read().status, "bound");
});

test("native context errors propagate without binding and can be retried", () => {
  const h = browser(); h.api.install(h.canvas);
  h.contextError = new Error("native getContext");
  assert.throws(() => h.canvas.getContext("webgl2"), error => error === h.contextError);
  assert.equal(h.read().status, "waiting-context");
  h.contextError = null;
  assert.equal(h.canvas.getContext("webgl2"), h.gl);
  assert.equal(h.read().status, "bound");
});

test("native shader exceptions/throws retain identity even when optional DOM diagnostics fail", () => {
  for (const telemetryThrows of [false, true]) {
    for (const failure of [new Error("native shaderSource"), "native-value", { native: true }]) {
      const h = browser({ telemetryThrows }); h.bind();
      h.sourceError = failure;
      let caught;
      try { h.gl.shaderSource({}, source); } catch (error) { caught = error; }
      assert.equal(caught, failure);
      assert.equal(h.calls.filter(call => call.name === "shaderSource").length, 1);
      assert.doesNotThrow(h.cleanup);
    }
  }
});

test("successful native calls survive telemetry failures and unwrappable contexts fail open", () => {
  const h = browser({ telemetryThrows: true }); h.bind();
  assert.equal(h.gl.shaderSource({}, source), h.result);
  const locked = browser(); Object.preventExtensions(locked.gl);
  locked.api.install(locked.canvas);
  assert.equal(locked.canvas.getContext("webgl2"), locked.gl);
  assert.equal(locked.read().status, "unavailable");
  assert.equal(locked.gl.shaderSource, locked.originalSource);
  assert.equal(Object.hasOwn(locked.canvas, "getContext"), false);
});

test("cleanup works before/after binding, restores exact own descriptors and is idempotent", () => {
  for (const bind of [false, true]) {
    const h = browser();
    Object.defineProperty(h.canvas, "getContext", { value: h.originalContext, configurable: true, writable: false });
    Object.defineProperty(h.gl, "shaderSource", { value: h.originalSource, configurable: true, enumerable: true });
    const beforeContext = Object.getOwnPropertyDescriptor(h.canvas, "getContext");
    const beforeSource = Object.getOwnPropertyDescriptor(h.gl, "shaderSource");
    const cleanup = h.api.install(h.canvas);
    if (bind) h.canvas.getContext("webgl2");
    const wrapper = h.gl.shaderSource;
    cleanup();
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.canvas, "getContext"), beforeContext);
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.gl, "shaderSource"), beforeSource);
    const snapshot = h.canvas.dataset.fastCompile;
    cleanup();
    wrapper.call(h.gl, {}, source);
    assert.equal(h.calls.at(-1).args[1], source, "captured disposed wrapper must also bypass transformation");
    assert.equal(h.canvas.dataset.fastCompile, snapshot);
    assert.equal(h.read().status, "disposed");
  }
});

test("cleanup preserves another owner's replacement; separate canvases can be disposed independently", () => {
  const h = browser(); h.bind();
  const otherCleanup = h.api.install(h.other); h.other.getContext("webgl2");
  const replacement = function () {};
  h.gl.shaderSource = replacement;
  h.cleanup();
  assert.equal(h.gl.shaderSource, replacement);
  h.otherGL.shaderSource({}, source);
  assert.equal(h.calls.at(-1).args[1], expectedRewrite(source));
  otherCleanup();
  assert.equal(Object.hasOwn(h.otherGL, "shaderSource"), false);
  const pending = browser(); const cleanup = pending.api.install(pending.canvas);
  pending.canvas.getContext = replacement; cleanup();
  assert.equal(pending.canvas.getContext, replacement);
});

test("short diagnostic evidence has a hard entry bound and never includes full shader text", () => {
  const h = browser(); h.bind();
  for (let i = 0; i < 20; i++) h.gl.shaderSource({}, source);
  const report = h.read();
  assert.equal(report.rewrittenCalls, 20);
  assert.equal(report.rewrittenLoops, 60);
  assert.equal(report.evidence.length, 16);
  assert.equal(h.canvas.dataset.fastCompile.includes("light_process_omni"), false);
  assert.ok(h.canvas.dataset.fastCompile.length < 4096);
  assert.ok(report.evidence.every(row => Object.keys(row).length === 5));
});

// This is the explicit scene contract supplied by main, not a native inventory
// proof. Independent native/build-time acceptance remains an integration gate.
const sceneContract = Object.freeze({
  packSha256: "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c",
  spotLights: 0, areaLights: 0
});
const sceneOptions = Object.freeze({ contract: sceneContract });
const v117LiteSha = "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79";
const denseQ60Sha = "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf";
const reviewedPacks = [sceneContract.packSha256, v117LiteSha, denseQ60Sha,
  "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460",
  "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc",
  "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3",
  "699c08aac4201b9c507d964b6a857247af6f718ebab203da085e5937de0052db",
  "2850c2eebd3382b57866b77aba6dbfe5e4209190c478c502c637bce660fefff4",
  "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5",
  "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b",
  "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c"];
const colorSource = source.replace("#version 300 es\n", "#version 300 es\n#define BASE_PASS\n");
const featureFlags = ["DISABLE_LIGHT_SPOT", "DISABLE_LIGHT_AREA"];
const addFlags = (input, names) => input.replace(/(#version[^\r\n]*)(\r?\n)/,
  (_, version, newline) => version + newline + names.map(name => `#define ${name}${newline}`).join(""));

test("scene contract allowlist: only independently reviewed lite hashes receive identical source edits", () => {
  const declaration = /const SCENE_PACK_SHA256S = Object\.freeze\((\[[\s\S]*?\])\)/.exec(helper);
  assert.ok(declaration, "keep the full private allowlist explicit and reviewable");
  assert.deepEqual(JSON.parse(declaration[1]), reviewedPacks);
  for (const packSha256 of reviewedPacks) {
    const result = transformSource(colorSource, { contract: { ...sceneContract, packSha256 } });
    assert.equal(result.source, addFlags(expectedRewrite(colorSource), featureFlags));
    assert.equal(result.specialized, true);
    assert.equal(result.loops, 3);
    assert.deepEqual(result.addedDefines, featureFlags);
  }
});

test("scene contract allowlist: snapshot and telemetry retain the actual validated hash, read exactly once", () => {
  for (const packSha256 of reviewedPacks) {
    let reads = 0;
    const contract = { spotLights: 0, areaLights: 0,
      get packSha256() { return ++reads === 1 ? packSha256 : "f".repeat(64); } };
    const h = browser(); h.bind({ contract });
    assert.equal(reads, 1);
    h.gl.shaderSource({}, colorSource);
    assert.equal(h.read().specializationPackSha256, packSha256, "never substitute the first allowlisted hash");
    assert.equal(h.read().specializedCalls, 1);
    assert.equal(h.read().specializationDefinesAdded, 2);
    assert.equal(h.calls.at(-1).args[1], addFlags(expectedRewrite(colorSource), featureFlags));
    assert.equal(reads, 1, "shader submissions use the immutable validated snapshot");
    h.cleanup();
  }
});

test("scene contract allowlist: future, original, balanced and nonzero contracts retain loop-only output", () => {
  const baseline = transformSource(colorSource);
  const rejectedHashes = ["f".repeat(64), v117LiteSha.slice(0, -1) + "0",
    "02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d",
    "68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33",
    v117LiteSha.toUpperCase(), v117LiteSha + " ", null, undefined];
  for (const packSha256 of rejectedHashes)
    assert.deepEqual(transformSource(colorSource, { contract: { ...sceneContract, packSha256 } }), baseline);
  for (const packSha256 of [sceneContract.packSha256, v117LiteSha]) {
    for (const field of ["spotLights", "areaLights"]) {
      for (const value of [1, 9, -1, "0", false, null, undefined])
        assert.deepEqual(transformSource(colorSource,
          { contract: { ...sceneContract, packSha256, [field]: value } }), baseline);
    }
  }
  const h = browser(); h.bind({ contract: { ...sceneContract, packSha256: "f".repeat(64) } });
  h.gl.shaderSource({}, colorSource);
  assert.equal(h.calls.at(-1).args[1], baseline.source);
  assert.equal(h.read().specializationPackSha256, null);
  assert.equal(h.read().specializedCalls, 0);
  h.cleanup();
});

test("scene specialization: exact contract adds only the two missing zero-light flags after version", () => {
  const input = addFlags(colorSource, ["RENDER_SHADOWS", "SHADOW_MODE_PCF_5", "USE_INSTANCING"]);
  assert.ok(input.includes("#undef USE_ADDITIVE_LIGHTING"),
    "stock conditional undefinition must not be mistaken for an enabled additive mode");
  const result = transformSource(input, sceneOptions);
  assert.equal(result.source, addFlags(expectedRewrite(input), featureFlags),
    "directional/omni, shadows and all bodies stay byte-exact beyond the existing loop edits");
  assert.equal(result.specialized, true);
  assert.deepEqual(result.addedDefines, featureFlags);
  assert.equal(result.loops, 3);
  assert.equal(result.source.split("\n").length, input.split("\n").length + 2);
  assert.equal(result.source.includes("#define DISABLE_LIGHT_OMNI"), false);
  assert.equal(result.source.includes("#define DISABLE_LIGHT_DIRECTIONAL"), false);
  assert.equal(result.source.includes("#define SHADOWS_DISABLED"), false);
});

test("scene specialization: missing, unknown, future, malformed or nonzero contracts retain loop-only output", () => {
  const options = [undefined, null, {}, sceneContract, { contract: null }, { contract: {} },
    { contract: { ...sceneContract, packSha256: "f".repeat(64) } },
    { contract: { ...sceneContract, packSha256: sceneContract.packSha256.toUpperCase() } },
    { contract: { ...sceneContract, packSha256: sceneContract.packSha256 + " " } },
    { get contract() { throw new Error("bad optional getter"); } },
    { contract: { get packSha256() { throw new Error("bad contract getter"); } } }];
  for (const field of ["spotLights", "areaLights"]) {
    for (const value of [undefined, null, false, "0", NaN, -1, 1, 0.5])
      options.push({ contract: { ...sceneContract, [field]: value } });
  }
  const baseline = transformSource(colorSource);
  for (const value of options) assert.deepEqual(transformSource(colorSource, value), baseline);
  assert.equal(baseline.specialized, false);
  assert.deepEqual(baseline.addedDefines, []);
});

test("scene specialization: an accepted contract never bypasses the stock fragment/source guard", () => {
  for (const input of ["void main() {}", reference.slice(0, reference.indexOf("#[fragment]")),
    colorSource.replace("#version 300 es", "#version 330"),
    colorSource.replace("precision highp int;", "precision mediump int;"),
    colorSource.replace("uniform uint area_light_count;", "uniform int area_light_count;"),
    colorSource.replace("light_process_spot(spot_light_indices[i], vertex,", "light_process_spot(spot_light_indices[i], unknown_vertex,"),
    colorSource + " ".repeat(2 * 1024 * 1024)]) {
    const result = transformSource(input, sceneOptions);
    assert.equal(result.source, input);
    assert.equal(result.changed, false);
    assert.equal(result.specialized, false);
  }
});

for (const flag of ["USE_VERTEX_LIGHTING", "MODE_RENDER_DEPTH", "MODE_UNSHADED", "USE_ADDITIVE_LIGHTING",
  "ADDITIVE_OMNI", "ADDITIVE_SPOT", "RENDER_MATERIAL", "RENDER_MOTION_VECTORS"]) {
  test(`scene specialization: defined ${flag} excludes the variant without changing loop-only behavior`, () => {
    for (const value of ["", " 0"]) {
      const input = colorSource.replace("#version 300 es\n", `#version 300 es\n#define ${flag}${value}\n`);
      assert.deepEqual(transformSource(input, sceneOptions), transformSource(input));
      assert.equal(transformSource(input).loops, 3);
    }
  });
}

test("scene specialization: only missing flags are inserted; both preexisting flags remain untouched", () => {
  for (const existing of [[], [featureFlags[0]], [featureFlags[1]], featureFlags]) {
    const input = addFlags(colorSource, existing);
    const missing = featureFlags.filter(name => !existing.includes(name));
    const result = transformSource(input, sceneOptions);
    assert.equal(result.source, addFlags(expectedRewrite(input), missing));
    assert.deepEqual(result.addedDefines, missing);
    assert.equal(result.specialized, missing.length > 0);
    for (const flag of featureFlags)
      assert.equal((result.source.match(new RegExp(`^#define ${flag}$`, "gm")) || []).length, 1);
  }
  const input = colorSource.replace("#version 300 es\n", "#version 300 es\n# define DISABLE_LIGHT_SPOT 0\n");
  assert.deepEqual(transformSource(input, sceneOptions).addedDefines, ["DISABLE_LIGHT_AREA"],
    "a macro with value zero is still defined for stock #ifdef conditions");
});

test("scene specialization: missing BASE_PASS and conditional, revoked, duplicated or multiline flags opt out", () => {
  const additions = [
    "#if 0\n#define DISABLE_LIGHT_SPOT\n#endif\n",
    "#ifdef UNKNOWN\n#define DISABLE_LIGHT_AREA\n#endif\n",
    "#if 0\n#define USE_VERTEX_LIGHTING\n#endif\n",
    "#undef DISABLE_LIGHT_SPOT\n", "#undef DISABLE_LIGHT_AREA\n", "#undef BASE_PASS\n",
    "#define DISABLE_LIGHT_SPOT\n#define DISABLE_LIGHT_SPOT\n",
    "#define BASE_PASS\n", "#define DISABLE_LIGHT_AREA(x) x\n",
    "#define DISABLE_LIGHT_AREA \\\n  1\n", "#else\n"
  ];
  assert.deepEqual(transformSource(source, sceneOptions), transformSource(source));
  for (const addition of additions) {
    const input = colorSource.replace("#version 300 es\n", "#version 300 es\n" + addition);
    assert.deepEqual(transformSource(input, sceneOptions), transformSource(input));
  }
  const conditionalBase = colorSource.replace("#define BASE_PASS", "#if 1\n#define BASE_PASS\n#endif");
  assert.deepEqual(transformSource(conditionalBase, sceneOptions), transformSource(conditionalBase));
});

test("scene specialization: comments do not masquerade as flags and CRLF/version placement is preserved", () => {
  const input = ("/* #define USE_VERTEX_LIGHTING */\n" + colorSource)
    .replace("#version 300 es\n", "#version 300 es // native version comment\n// #define DISABLE_LIGHT_SPOT\n")
    .replace(/\n/g, "\r\n");
  const result = transformSource(input, sceneOptions);
  assert.equal(result.specialized, true);
  assert.ok(result.source.startsWith("/* #define USE_VERTEX_LIGHTING */\r\n#version 300 es // native version comment\r\n" +
    "#define DISABLE_LIGHT_SPOT\r\n#define DISABLE_LIGHT_AREA\r\n// #define DISABLE_LIGHT_SPOT\r\n"));
  assert.equal(result.source.replace(/\r\n/g, "").includes("\n"), false);
});

test("scene specialization: an open block comment at the version boundary opts out without false telemetry", () => {
  const input = colorSource.replace("#version 300 es\n", "#version 300 es /* version comment\ncontinued */\n");
  assert.deepEqual(transformSource(input, sceneOptions), transformSource(input));
  assert.equal(transformSource(input).loops, 3);
  const singleLine = colorSource.replace("#version 300 es\n", "#version 300 es /* closed */\n");
  assert.equal(transformSource(singleLine, sceneOptions).specialized, true);
});

test("scene specialization: combined transformation is idempotent and never strips existing definitions", () => {
  const first = transformSource(colorSource, sceneOptions);
  assert.equal(first.specialized, true);
  const second = transformSource(first.source, sceneOptions);
  assert.equal(second.source, first.source);
  assert.equal(second.changed, false);
  assert.equal(second.specialized, false);
  assert.deepEqual(second.addedDefines, []);
});

test("scene specialization install: no contract stays loop-only; the opt-in result and counters match pure transform", () => {
  for (const options of [undefined, sceneOptions]) {
    const h = browser(); h.bind(options);
    const shader = {}, extra = {};
    assert.equal(h.gl.shaderSource(shader, colorSource, extra), h.result);
    const call = h.calls.at(-1);
    assert.equal(call.receiver, h.gl);
    assert.equal(call.args[0], shader);
    assert.equal(call.args[1], transformSource(colorSource, options).source);
    assert.equal(call.args[2], extra);
    const report = h.read();
    assert.equal(report.specializationPackSha256, options ? sceneContract.packSha256 : null);
    assert.equal(report.rewrittenCalls, 1);
    assert.equal(report.rewrittenLoops, 3);
    assert.equal(report.specializedCalls, options ? 1 : 0);
    assert.equal(report.specializationDefinesAdded, options ? 2 : 0);
    assert.equal(report.nativeFailures, 0);
    if (options) assert.deepEqual(report.evidence[0].specializationDefines, featureFlags);
    else assert.equal(report.evidence[0].specializationDefines, undefined);
    assert.notEqual(report.evidence[0].originalFnv, report.evidence[0].transformedFnv);
    assert.equal(h.calls.length, 2, "no extra GL calls, downloads or shader queries");
    assert.equal(h.GL.prototype.shaderSource, h.originalSource);
    h.cleanup();
  }
});

test("scene specialization install: absent/one/two existing flags count only newly inserted definitions", () => {
  const h = browser(); h.bind(sceneOptions);
  h.gl.shaderSource({}, colorSource);
  h.gl.shaderSource({}, addFlags(colorSource, ["DISABLE_LIGHT_SPOT"]));
  h.gl.shaderSource({}, addFlags(colorSource, featureFlags));
  assert.equal(h.read().rewrittenCalls, 3);
  assert.equal(h.read().rewrittenLoops, 9);
  assert.equal(h.read().specializedCalls, 2);
  assert.equal(h.read().specializationDefinesAdded, 3);
  assert.equal(h.read().evidence[2].specializationDefines, undefined);
});

test("scene specialization install: contracts are per-canvas snapshots and never enabled by a repeated install", () => {
  const mutable = { contract: { ...sceneContract } };
  const h = browser(); h.bind(mutable);
  mutable.contract.packSha256 = "f".repeat(64); // Does not change the already loaded immutable pack.
  mutable.contract.spotLights = 1;
  h.gl.shaderSource({}, colorSource);
  assert.equal(h.read().specializedCalls, 1);
  const disposeOther = h.api.install(h.other); h.other.getContext("webgl2");
  assert.equal(h.api.install(h.other, sceneOptions), disposeOther);
  h.otherGL.shaderSource({}, colorSource);
  assert.equal(h.calls.at(-1).args[1], transformSource(colorSource).source);
  assert.equal(JSON.parse(h.other.dataset.fastCompile).specializedCalls, 0);
  disposeOther();
  h.cleanup();
  // A new pack/engine lifetime must install with its actual new hash: reject it.
  h.bind({ contract: { ...sceneContract, packSha256: "f".repeat(64) } });
  h.gl.shaderSource({}, colorSource);
  assert.equal(h.calls.at(-1).args[1], transformSource(colorSource).source);
  assert.equal(h.read().specializationPackSha256, null);
  assert.equal(h.read().specializedCalls, 0);
});

test("scene specialization install: native exceptions/returns and failed diagnostic writes remain transparent", () => {
  for (const telemetryThrows of [false, true]) {
    const h = browser({ telemetryThrows }); h.bind(sceneOptions);
    assert.equal(h.gl.shaderSource({}, colorSource), h.result);
    const failure = new Error("native specialized source submission failed");
    h.sourceError = failure;
    assert.throws(() => h.gl.shaderSource({}, colorSource), error => error === failure);
    if (!telemetryThrows) {
      assert.equal(h.read().nativeFailures, 1);
      assert.equal(h.read().specializedCalls, 2, "counts submissions, not successful linked programs");
    }
    assert.doesNotThrow(h.cleanup);
    assert.equal(Object.hasOwn(h.gl, "shaderSource"), false);
  }
});

test("scene specialization install: diagnostics remain hard-bounded short hashes/counts, with no shader bodies", () => {
  const h = browser(); h.bind(sceneOptions);
  for (let i = 0; i < 20; i++) h.gl.shaderSource({}, colorSource);
  assert.equal(h.read().specializedCalls, 20);
  assert.equal(h.read().specializationDefinesAdded, 40);
  assert.equal(h.read().evidence.length, 16);
  assert.equal(h.canvas.dataset.fastCompile.includes("light_process_omni"), false);
  assert.ok(h.canvas.dataset.fastCompile.length < 8192);
  assert.ok(h.read().evidence.every(row => row.specializationDefines.length === 2));
});

test("v138 stock premise: pinned fragment revokes additive for unshaded, never conditionally defines it", () => {
  assert.equal((fragment.match(/^[ \t]*#[ \t]*define[ \t]+USE_ADDITIVE_LIGHTING\b/gm) || []).length, 0);
  assert.equal((fragment.match(/^[ \t]*#[ \t]*undef[ \t]+USE_ADDITIVE_LIGHTING\b/gm) || []).length, 1);
  assert.match(fragment, /#ifdef MODE_UNSHADED\s+#ifdef USE_ADDITIVE_LIGHTING\s+#undef USE_ADDITIVE_LIGHTING\s+#endif\s+#endif/);
  const ordinary = transformSource(colorSource, sceneOptions);
  assert.equal(ordinary.source, addFlags(expectedRewrite(colorSource), featureFlags),
    "the real stock conditional undef already permits the ordinary lit BASE_PASS");
  const invented = colorSource.replace("#undef USE_ADDITIVE_LIGHTING", "#define USE_ADDITIVE_LIGHTING");
  assert.deepEqual(transformSource(invented, sceneOptions), transformSource(invented),
    "changing the stock undef into a define is an unknown shader, not a pinned stock path");
});

for (const [name, definition] of [
  ["inactive literal branch", "#if 0\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["active literal branch", "#if 1\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["active base branch", "#ifdef BASE_PASS\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["lit fragment branch", "#ifndef MODE_UNSHADED\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["unknown nested branch", "#ifdef UNKNOWN\n#if 0\n#define USE_ADDITIVE_LIGHTING\n#endif\n#endif\n"],
  ["else branch", "#if 0\n#else\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["elif branch", "#if 0\n#elif defined(BASE_PASS)\n#define USE_ADDITIVE_LIGHTING\n#endif\n"],
  ["zero object-like value", "#if 1\n#define USE_ADDITIVE_LIGHTING 0\n#endif\n"],
  ["function-like mode", "#define USE_ADDITIVE_LIGHTING(x) x\n"],
  ["comment and directive whitespace", "# if 1\n# define /* mode */ USE_ADDITIVE_LIGHTING\n# endif\n"],
  ["continued macro name", "#define USE_ADDITIVE_\\\nLIGHTING\n"],
  ["continued directive name", "#def\\\nine USE_ADDITIVE_LIGHTING\n"],
  ["continued excluded vertex mode", "#define USE_VERTEX_\\\nLIGHTING\n"],
  ["continued excluded depth mode", "#define MODE_RENDER_\\\nDEPTH\n"],
]) {
  test("v138 scene mode mutation rejects " + name + " without relaxing loop-only behavior", () => {
    const input = colorSource.replace("#define BASE_PASS\n", "#define BASE_PASS\n" + definition);
    const withoutContract = transformSource(input);
    assert.equal(withoutContract.loops, 3);
    const result = transformSource(input, sceneOptions);
    assert.equal(result.specialized, false);
    assert.deepEqual(result, withoutContract);
    assert.equal(withoutContract.specialized, false);
  });
}

test("v138 unknown splicing is refused; non-continuation backslashes inside comments remain harmless", () => {
  const unknown = colorSource.replace("#define BASE_PASS\n", "#define BASE_PASS\n#define ALIAS \\\n value\n");
  const rejected = transformSource(unknown, sceneOptions);
  assert.equal(rejected.specialized, false);
  assert.deepEqual(rejected, transformSource(unknown));
  const commented = colorSource.replace("#define BASE_PASS\n",
    "#define BASE_PASS\n/* #define USE_ADDITIVE_\\LIGHTING */\n");
  assert.equal(transformSource(commented, sceneOptions).source, addFlags(expectedRewrite(commented), featureFlags));
});

test("v138 line-comment continuation cannot counterfeit an active BASE_PASS before comment removal", () => {
  for (const newline of ["\n", "\r\n", "\r"]) {
    const input = colorSource.replace("#define BASE_PASS", "// continued comment \\" + newline + "#define BASE_PASS");
    const result = transformSource(input, sceneOptions);
    assert.equal(result.specialized, false);
    assert.deepEqual(result, transformSource(input));
  }
});

test("v138 native disabled flags need no helper additions: submission counts are not unpruned-program counts", () => {
  const h = browser(); h.bind(sceneOptions);
  const ordinary = colorSource;
  const nativePruned = addFlags(colorSource, featureFlags);
  const nativeShadowBase = addFlags(nativePruned, ["USE_ADDITIVE_LIGHTING", "LIGHT_USE_PSSM4", "SHADOW_MODE_PCF_5"]);
  for (const input of [ordinary, nativePruned, nativeShadowBase]) h.gl.shaderSource({}, input);
  assert.equal(h.read().rewrittenCalls, 3);
  assert.equal(h.read().specializedCalls, 1);
  assert.equal(h.read().specializationDefinesAdded, 2);
  for (const call of h.calls.filter(call => call.name === "shaderSource")) {
    for (const flag of featureFlags) assert.ok(call.args[1].includes("#define " + flag + "\n"));
  }
  assert.equal(h.calls.at(-1).args[1], expectedRewrite(nativeShadowBase),
    "already-pruned real additive-shadow math is not removed or rewritten by scene specialization");
  h.cleanup();
});

test("v138 actual bounded trace: most observed scene sources already carry both zero-light flags", () => {
  const bytes = fs.readFileSync(path.resolve(__dirname, "../../artifacts/startup-v135/v138-startup-trace.json"));
  assert.equal(createHash("sha256").update(bytes).digest("hex"),
    "5bcb94d7b4080e15d8b34e203048d0a2b2d82b7cef3a1f96b5181970431b23ec");
  const record = JSON.parse(bytes), trace = JSON.parse(record.data.startupTrace);
  const stats = JSON.parse(record.data.fastCompile);
  assert.equal(trace.totals.getShaderParameter.ms, 873.2);
  assert.equal(trace.totals.getProgramParameter.ms, 1718.9);
  assert.equal(trace.totals.shaderSource.calls, 96);
  assert.equal(stats.shaderSourceCalls, 120, "later helper snapshot and core-only trace are not the same capture interval");
  assert.equal(stats.rewrittenCalls, 46);
  assert.equal(stats.specializedCalls, 1, "counts newly inserted defines only");
  const programs = new Map(), sources = new Map();
  for (const row of trace.slow) {
    const scene = (row.sources || []).filter(s => s.defines.includes("#define MAX_FORWARD_LIGHTS 8u"));
    if (!scene.length) continue;
    programs.set(row.program, scene);
    for (const source of scene) sources.set(source.hash, source);
  }
  const both = s => featureFlags.every(flag => s.defines.includes("#define " + flag));
  assert.equal(programs.size, 17);
  assert.equal(sources.size, 34);
  assert.equal([...sources.values()].filter(both).length, 33);
  assert.equal([...programs.values()].filter(pair => pair.every(both)).length, 16);
  assert.ok([...programs.values()].every(pair => pair.some(both)));
  assert.equal([...sources.values()].find(s => !both(s)).hash, "7b523cd1");
  // No shader stage, BASE_PASS or USE_ADDITIVE_LIGHTING is recorded in this
  // bounded metadata. Do not extrapolate these 17 programs to all submissions,
  // invent the stage of 7b523cd1, or label the 2.5921s synchronous wait recoverable.
});

test("v138 scene path never overrides compile/link/status/log/validation methods or native failure results", () => {
  const h = browser(), calls = [], nativeError = new Error("native validation failure");
  const methods = ["compileShader", "linkProgram", "validateProgram", "getShaderParameter",
    "getProgramParameter", "getShaderInfoLog", "getProgramInfoLog", "getError"];
  let throwing = null;
  const returns = Object.fromEntries(methods.map(name => [name,
    name.includes("Parameter") ? false : name.includes("InfoLog") ? "native diagnostic" : { native: name }]));
  for (const name of methods) {
    Object.defineProperty(h.GL.prototype, name, { configurable: true, writable: true, value: function (...args) {
      calls.push({ name, receiver: this, args });
      if (throwing === name) throw nativeError;
      return returns[name];
    } });
  }
  const descriptors = methods.map(name => Object.getOwnPropertyDescriptor(h.GL.prototype, name));
  h.bind(sceneOptions);
  for (const input of [colorSource, addFlags(colorSource, ["USE_ADDITIVE_LIGHTING"])]) h.gl.shaderSource({}, input);
  assert.equal(calls.length, 0, "the helper submits sources, never calls validation on the engine's behalf");
  for (let index = 0; index < methods.length; index++) {
    const name = methods[index], object = {}, parameter = name === "getShaderParameter" ? 0x8b81 : 0x8b82;
    assert.equal(Object.hasOwn(h.gl, name), false);
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.GL.prototype, name), descriptors[index]);
    assert.equal(h.gl[name](object, parameter), returns[name], "false compile/link results must remain false");
    assert.equal(calls.at(-1).receiver, h.gl);
    assert.deepEqual(calls.at(-1).args, [object, parameter]);
    throwing = name;
    assert.throws(() => h.gl[name](object, parameter), error => error === nativeError);
    throwing = null;
  }
  h.cleanup();
  for (let index = 0; index < methods.length; index++)
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.GL.prototype, methods[index]), descriptors[index]);
});

const directionalOptions = { ...sceneOptions, sceneDirectionalBase: true };
const directionalSource = addFlags(colorSource, ["USE_ADDITIVE_LIGHTING", "LIGHT_USE_PSSM4", "SHADOW_MODE_PCF_5"]);

test("directional base: explicit true and an accepted zero-light contract are both mandatory", () => {
  for (const sceneDirectionalBase of [undefined, false, 0, 1, "true", "sceneDirectionalBase", {}])
    assert.deepEqual(transformSource(directionalSource, { ...sceneOptions, sceneDirectionalBase }), transformSource(directionalSource));
  for (const contract of [undefined, { ...sceneContract, packSha256: "f".repeat(64) },
    { ...sceneContract, spotLights: 1 }, { ...sceneContract, areaLights: 1 }])
    assert.deepEqual(transformSource(directionalSource, { contract, sceneDirectionalBase: true }), transformSource(directionalSource));
  const hostile = { ...sceneOptions, get sceneDirectionalBase() { throw Error("untrusted option"); } };
  assert.deepEqual(transformSource(directionalSource, hostile), transformSource(directionalSource));
  assert.equal(transformSource(colorSource, directionalOptions).source, transformSource(colorSource, sceneOptions).source);
});

test("directional base: only two missing flags and the three existing loop edits; all shadows/math/blocks stay exact", () => {
  for (const existing of [[], [featureFlags[0]], [featureFlags[1]], featureFlags]) {
    const input = addFlags(directionalSource, existing);
    const missing = featureFlags.filter(name => !existing.includes(name));
    const result = transformSource(input, directionalOptions);
    assert.equal(result.source, addFlags(expectedRewrite(input), missing));
    assert.deepEqual(result.addedDefines, missing);
    assert.equal(result.specialized, missing.length > 0);
    assert.equal(transformSource(result.source, directionalOptions).source, result.source);
  }
  for (const value of [" 0", " 1"]) {
    const input = directionalSource.replace("#define USE_ADDITIVE_LIGHTING\n", "#define USE_ADDITIVE_LIGHTING" + value + "\n");
    assert.equal(transformSource(input, directionalOptions).source, addFlags(expectedRewrite(input), featureFlags));
  }
  const crlf = directionalSource.replace(/\n/g, "\r\n");
  assert.equal(transformSource(crlf, directionalOptions).source,
    addFlags(expectedRewrite(directionalSource), featureFlags).replace(/\n/g, "\r\n"));
});

test("directional base: vertex/depth/unshaded/positional-additive and non-base modes remain excluded", () => {
  for (const name of ["USE_VERTEX_LIGHTING", "MODE_RENDER_DEPTH", "MODE_UNSHADED", "ADDITIVE_OMNI",
    "ADDITIVE_SPOT", "RENDER_MATERIAL", "RENDER_MOTION_VECTORS"]) {
    for (const addition of ["#define " + name + " 0\n", "#if 0\n#define " + name + "\n#endif\n"] ) {
      const input = directionalSource.replace("#define BASE_PASS\n", "#define BASE_PASS\n" + addition);
      assert.deepEqual(transformSource(input, directionalOptions), transformSource(input), name);
    }
  }
  const noBase = directionalSource.replace("#define BASE_PASS\n", "");
  assert.deepEqual(transformSource(noBase, directionalOptions), transformSource(noBase));
});

test("directional base: unknown additive macro programs never use the stock inactive-undef exception", () => {
  const mutations = [
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "#if 1\n#define USE_ADDITIVE_LIGHTING\n#endif\n"),
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "#define USE_ADDITIVE_LIGHTING(x) x\n"),
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "#define USE_ADDITIVE_LIGHTING UNKNOWN\n"),
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "#define USE_ADDITIVE_LIGHTING\n#define USE_ADDITIVE_LIGHTING\n"),
    s => s + "\n#undef USE_ADDITIVE_LIGHTING\n",
    s => s.replace("#undef USE_ADDITIVE_LIGHTING", "#define USE_ADDITIVE_LIGHTING"),
    s => s.replace("#ifdef MODE_UNSHADED\n#ifdef USE_ADDITIVE_LIGHTING", "#ifndef MODE_UNSHADED\n#ifdef USE_ADDITIVE_LIGHTING"),
    s => s.replace("#undef USE_ADDITIVE_LIGHTING", "#undef USE_ADDITIVE_LIGHTING\n#else\n#undef USE_ADDITIVE_LIGHTING"),
    s => s.replace("#undef USE_ADDITIVE_LIGHTING", ""),
    s => s + "\n#ifdef MODE_UNSHADED\n#ifdef USE_ADDITIVE_LIGHTING\n#undef USE_ADDITIVE_LIGHTING\n#endif\n#endif\n",
    s => s.replace("#define BASE_PASS\n", "#if 1\n#define BASE_PASS\n#endif\n"),
    s => s.replace("#define BASE_PASS\n", "") + "\n#define BASE_PASS\n",
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "") + "\n#define USE_ADDITIVE_LIGHTING\n",
    s => s.replace("#define USE_ADDITIVE_LIGHTING\n", "#define USE_ADDITIVE_\\\nLIGHTING\n"),
  ];
  for (const mutate of mutations) {
    const input = mutate(directionalSource);
    assert.deepEqual(transformSource(input, directionalOptions), transformSource(input));
  }
  const unknownBody = directionalSource.replace("light_process_spot(spot_light_indices[i], vertex,",
    "light_process_spot(spot_light_indices[i], unknown_vertex,");
  assert.equal(transformSource(unknownBody, directionalOptions).source, unknownBody);
});

test("directional base install: snapshot is immutable, no extra GL calls, native errors and cleanup stay transparent", () => {
  let reads = 0;
  const options = { ...sceneOptions, get sceneDirectionalBase() { return ++reads === 1; } };
  const h = browser(); h.bind(options);
  assert.equal(reads, 1);
  assert.equal(h.gl.shaderSource({}, directionalSource), h.result);
  assert.equal(h.calls.at(-1).args[1], transformSource(directionalSource, directionalOptions).source);
  assert.equal(h.calls.length, 2, "only getContext and real shaderSource");
  assert.equal(h.read().sceneDirectionalBase, true);
  assert.equal(h.read().specializedCalls, 1);
  const failure = new Error("actual native shaderSource failure"); h.sourceError = failure;
  assert.throws(() => h.gl.shaderSource({}, directionalSource), error => error === failure);
  assert.equal(h.read().nativeFailures, 1);
  assert.equal(reads, 1, "no mutable option reads at later/night submissions");
  h.cleanup();
  assert.equal(Object.hasOwn(h.gl, "shaderSource"), false);
  const other = browser(); other.bind(sceneOptions);
  other.api.install(other.canvas, directionalOptions);
  other.gl.shaderSource({}, directionalSource);
  assert.equal(other.calls.at(-1).args[1], expectedRewrite(directionalSource), "repeat install cannot enable the scope");
  assert.equal(other.read().sceneDirectionalBase, false);
  other.cleanup();
});

for (const [candidate, packSha256] of [
  ["06", "2850c2eebd3382b57866b77aba6dbfe5e4209190c478c502c637bce660fefff4"],
  ["07", "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5"],
  ["10", "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b"]
]) {
test(`native${candidate} allowlist evidence: actual mode5 pin binds the reviewed 12-chunk zero-light day/night contract`, () => {
  const directory = path.resolve(__dirname, `../../artifacts/startup-v135/support/candidate-01/integrated${candidate}-native-01`);
  const read = name => JSON.parse(fs.readFileSync(path.join(directory, name), "utf8"));
  const twin = read("web-twin-proof.json"), native = read("native.json");
  assert.equal(twin.status, "PASS_EXACT_LOGICAL_NATIVE_WEB_TWIN");
  assert.equal(native.status, "PASS_CPU_STRUCTURAL_ONLY");
  assert.deepEqual(native.errors, []);
  assert.equal(read("support-observations.json").status, "PASS_NATIVE_SUPPORT_AND_FULL_STRUCTURAL_AUDIT");
  assert.ok(reviewedPacks.includes(packSha256));
  const coreMode5 = candidate === "10" ? twin.pairs.find(pair => pair.chunk === "core").mode5 : twin.coreMode5;
  assert.equal(coreMode5.sha256, packSha256);
  const pack = fs.readFileSync(path.resolve(__dirname, `../../artifacts/startup-v135/build/candidate-${candidate}/mode5/index-lite.pck`));
  assert.equal(pack.length, coreMode5.bytes);
  assert.equal(createHash("sha256").update(pack).digest("hex"), packSha256);
  assert.equal(twin.pairs.length, 13, "core plus twelve detail chunks");
  assert.equal(native.lightPhases["final-day"].nightBlend, 0);
  assert.equal(native.lightPhases["final-night"].nightBlend, 1);
  for (const key of ["core", ...Array.from({ length: 12 }, (_, i) => "chunk-" + i), "final-day", "final-night"]) {
    const phase = native.lightPhases[key];
    assert.equal(phase.includesHidden, true);
    assert.deepEqual(phase.counts, { AreaLight3D: 0, DirectionalLight3D: 4, OmniLight3D: 9, RectLight3D: 0, SpotLight3D: 0 });
    assert.equal(phase.lightSetSha256, candidate === "10"
      ? "27d320c70c2ae5ccd9677a458d7bb886fd09557352eaae9e1a7f445feea9bc8a"
      : twin.nativeLightSetSha256);
  }
  if (candidate === "07") {
    assert.equal(native.snapshots.length, 16);
    // Inventory maps contain present classes only; explicit zero-type phase
    // counts (including hidden lights) were checked separately above.
    for (const snapshot of native.snapshots)
      assert.deepEqual(snapshot.inventory.lightCounts,
        { DirectionalLight3D: 4, OmniLight3D: 9 }, snapshot.label);
  }
  const options = { contract: { ...sceneContract, packSha256 }, sceneDirectionalBase: true };
  assert.equal(transformSource(directionalSource, options).source, addFlags(expectedRewrite(directionalSource), featureFlags));
});
}

test("native15 contract is light-only: actual 18 phases, no hidden Spot/Area; strict scene diff remains recorded", () => {
  const root = path.resolve(__dirname, "../../artifacts/startup-v135");
  const reportPath = path.join(root, "independent/static-core/actual15-native-03/candidate/native.json");
  const bytes = fs.readFileSync(reportPath);
  assert.equal(createHash("sha256").update(bytes).digest("hex"),
    "85dcdbba93fe6d7e69bc76a89aef559133e14c52d752767ad69ca49ffafb5104");
  const native = JSON.parse(bytes);
  const packSha256 = "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c";
  assert.equal(native.status, "OBSERVED_CPU_ONLY");
  assert.deepEqual(native.errors, []);
  assert.equal(native.packBinding.allLoadedEntryMd5Match, true);
  assert.equal(native.corePack.sha256, "8d7a9e04209cd0154029634d7d8a8c92b90d5ec7f009b821bb1e4b4afe86df95");
  const labels = ["core", "transition-half", "reduced-night", "reduced-day",
    ...Array.from({length:12}, (_, i) => `chunk-${i}`), "final-night", "final-day"];
  assert.deepEqual(native.snapshots.map(s => s.contract.label), labels);
  for (const snapshot of native.snapshots) {
    assert.deepEqual(snapshot.contract.lights,
      {AreaLight3D:0, DirectionalLight3D:4, OmniLight3D:9, SpotLight3D:0});
    const observed = snapshot.contract.nodes.filter(n => /Light3D$/.test(n.class));
    assert.equal(observed.length, 13, "All graph nodes, including non-visible lights, are enumerated");
    assert.ok(observed.every(n => ["OmniLight3D", "DirectionalLight3D"].includes(n.class)));
  }
  assert.deepEqual(native.chunks.map(c => c.index), Array.from({length:12},(_,i)=>i));
  const comparison = JSON.parse(fs.readFileSync(path.join(root,
    "independent/static-core/actual15-native-03/comparison.json")));
  assert.equal(comparison.status, "FAIL", "Do not relabel separate floating-point geometry differences");
  for (const [kind, sha256] of [["native",native.corePack.sha256],["mode5",packSha256]]) {
    const data = fs.readFileSync(path.join(root, `build/candidate-15/${kind}/index-lite.pck`));
    assert.equal(createHash("sha256").update(data).digest("hex"), sha256);
  }
  assert.equal(transformSource(directionalSource,
    {contract:{...sceneContract,packSha256},sceneDirectionalBase:true}).source,
    addFlags(expectedRewrite(directionalSource),featureFlags));
});
