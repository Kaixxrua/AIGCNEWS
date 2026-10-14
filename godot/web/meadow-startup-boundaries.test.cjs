/* Read-only startup-boundary sidecar: no browser, WASM, network or real waits.
 * Executes the shipped public Engine JS with mocked download/module/DOM APIs.
 * A manually pumped RAF queue preserves next-frame ordering; logical clock
 * jumps model blocking/delayed callbacks, never benchmark real Godot or a GPU.
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createHash } = require("node:crypto");

const shipped = path.resolve(__dirname, "../../artifacts/v117");
const engineText = fs.readFileSync(path.join(shipped, "index.js"), "utf8");
const publicOffset = engineText.indexOf("const InternalConfig = function");
assert.ok(publicOffset > 0, "Expected shipped public Engine/config definitions");
// Never evaluate the preceding generated runtime or instantiate WebAssembly.
const publicEngineText = engineText.slice(publicOffset);
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(directory, options = {}) {
  let clock = 0;
  const elements = new Map();
  const rafs = [];
  const events = [];
  const errors = [];
  const gates = { wasm: deferred(), pack: deferred(), fs: deferred() };
  const event = (name, value) => events.push({ name, value, at: clock });
  class Element {
    constructor(id) {
      Object.assign(this, { id, dataset: {}, attributes: {}, handlers: {},
        disabled: true, hidden: false, width: 1280, height: 800, tabIndex: 0,
        tagName: id === "canvas" ? "CANVAS" : "BUTTON" });
    }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    removeAttribute(key) { delete this.attributes[key]; }
    addEventListener(key, callback) { this.handlers[key] = callback; }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const document = { body: { dataset: {} }, visibilityState: "visible", handlers: {},
    getElementById: element, getElementsByTagName: () => [element("canvas")],
    addEventListener(key, callback) { this.handlers[key] = callback; },
    removeEventListener(key) { delete this.handlers[key]; } };
  const preference = { matches: false, addEventListener() {} };
  const schedule = (callback, kind) => { rafs.push({ callback, kind }); return rafs.length; };
  const window = { performance: { now: () => clock, getEntriesByType: () => [] },
    matchMedia: () => preference, location: { reload: () => event("reload") },
    requestAnimationFrame: callback => schedule(callback, "presentation") };
  const forbid = name => () => { throw new Error(`Unexpected ${name}`); };
  const h = { gates, events, errors, element, document, window, engines: [],
    time(value) { clock = value; }, event,
    count(name) { return events.filter(row => row.name === name).length; },
    presentationFrames() { return rafs.filter(row => row.kind === "presentation").length; },
    frame(at = clock) {
      clock = at;
      const batch = rafs.splice(0);
      for (const row of batch) { event("raf", row.kind); row.callback(clock); }
    },
    start(config = {}) {
      h.ui.start({ executable: "index", mainPack: "index-lite.pck", args: ["--", "--meadow-quality=lite"],
        fileSizes: { "index.wasm": 39514754, "index-lite.pck": 44327228 }, ...config });
    },
  };
  class MockPreloader {
    constructor() { this.preloadedFiles = []; h.preloader = this; }
    loadPromise(file, bytes, raw) {
      event("wasmFetch", { file, bytes, raw });
      return gates.wasm.promise.then(() => new MockResponse());
    }
    preload(file, destination, bytes) {
      event("packFetch", { file, destination, bytes });
      return gates.pack.promise.then(() => {
        this.preloadedFiles.push({ path: destination, buffer: new Uint8Array([1, 2, 3]) });
      });
    }
    setProgressFunc(callback) { this.progress = callback; }
    animateProgress() { event("progressRaf"); }
  }
  class MockResponse {
    constructor(body = null) { this.body = body; }
    clone() { return new MockResponse(this.body); }
  }
  const module = {
    initFS(paths) { event("initFS", paths); return gates.fs.promise; },
    initConfig(config) { event("initConfig"); h.godotConfig = config; },
    copyToFS(file, buffer) {
      event("copyBegin", file);
      options.onCopy?.(h, file, buffer);
      event("copyEnd", file);
    },
    callMain(args) {
      event("callMainBegin", Array.from(args));
      options.onMain?.(h);
      event("callMainEnd");
    },
  };
  const featureCheck = () => {
    clock += options.featureCost || 0;
    event("features");
    return options.missing || [];
  };
  const Features = { getMissingFeatures: featureCheck };
  const navigator = { languages: ["en-US"], serviceWorker: {
    register(name) { event("serviceWorkerRegister", name); return new Promise(() => {}); }
  } };
  const shared = { document, window, navigator, HTMLCanvasElement: Element,
    Promise, URL, Response: MockResponse,
    console: { error: error => errors.push(error), info: (...args) => event("report", args), log() {} },
    requestAnimationFrame: callback => schedule(callback, "progress"),
    setTimeout: forbid("timeout"), setInterval: forbid("interval"), fetch: forbid("network"),
    WebAssembly: { instantiate: forbid("WASM"), instantiateStreaming: forbid("WASM streaming") } };
  vm.runInNewContext(publicEngineText, { ...shared, Preloader: MockPreloader, Features,
    Godot() { event("moduleFactory"); return Promise.resolve(module); } }, { filename: "v117-public-engine.js" });
  h.PublicEngine = window.Engine;
  function Engine(config) {
    const engine = new h.PublicEngine(config);
    h.engines.push(engine);
    event("engineCreated");
    return engine;
  }
  Object.assign(Engine, h.PublicEngine);
  const code = ["meadow-loader.js", "meadow-controls.js"].map(name =>
    fs.readFileSync(path.join(directory, name), "utf8")).join("\n");
  vm.runInNewContext(code, { ...shared, Engine }, { filename: `${path.basename(directory)}-loader-controls.js` });
  h.ui = window.meadowTimeUI;
  for (const [name, gate] of Object.entries(gates)) {
    if (!options.defer?.includes(name)) gate.resolve();
  }
  return h;
}

// Actual controls, manually pumped frame batches. These are presentation-proxy
// boundaries, not confirmation that the GPU/compositor displayed a night frame.
function timeSwitchHarness() {
  const h = harness(__dirname);
  h.commands = [];
  h.bindTime = () => h.ui.bind((command, ...args) => {
    h.commands.push({ command, args, requested: h.element("canvas").dataset.timeSwitchRequestedAtMs,
      ack: h.element("canvas").dataset.timeSwitchAckMs,
      presentation: h.element("canvas").dataset.timeSwitchPresentationMs });
  });
  h.requestTime = at => { h.time(at); h.element("time-control").handlers.click(); };
  h.renderTime = (at, transitioning = false) => {
    h.time(at); h.ui.render(true, 1, true, transitioning, 10);
  };
  h.timing = h.element("canvas").dataset;
  return h;
}

test("time-switch presentation: only a dispatched time command stamps and clears its measurements", () => {
  const h = timeSwitchHarness();
  h.requestTime(500);
  assert.equal(h.timing.timeSwitchRequestedAtMs, undefined, "unbound click sends no actual time command");
  h.bindTime();
  assert.equal(h.commands[0].command, "reduced_motion");
  h.element("motion-control").handlers.click();
  h.renderTime(700);
  assert.equal(h.timing.timeSwitchRequestedAtMs, undefined);
  assert.equal(h.timing.timeSwitchAckMs, undefined);
  assert.equal(h.presentationFrames(), 0);
  h.timing.timeSwitchAckMs = "73";
  h.timing.timeSwitchPresentationMs = "41000";
  h.requestTime(1000);
  assert.equal(h.commands.at(-1).command, "time");
  assert.equal(h.commands.at(-1).requested, "1000", "stamp precedes synchronous native callback");
  assert.equal(h.commands.at(-1).ack, undefined);
  assert.equal(h.commands.at(-1).presentation, undefined);
  assert.equal(h.presentationFrames(), 0, "request alone is neither acknowledgement nor presentation");
});

test("time-switch presentation: acknowledgement precedes exactly two later frames and remains unchanged", () => {
  const h = timeSwitchHarness(); h.bindTime();
  h.requestTime(1000);
  h.renderTime(1020, true);
  assert.equal(h.timing.timeSwitchAckMs, undefined);
  assert.equal(h.presentationFrames(), 0, "transitioning is not an acknowledgement");
  h.renderTime(1073);
  assert.equal(h.timing.timeSwitchAckMs, "73", "UI acknowledgement is not a displayed night frame");
  assert.equal(h.timing.timeSwitchPresentationMs, undefined);
  assert.equal(h.presentationFrames(), 1);
  h.renderTime(1080);
  assert.equal(h.presentationFrames(), 1, "duplicate stable render must not enqueue a second chain");
  h.frame(1500);
  assert.equal(h.timing.timeSwitchPresentationMs, undefined);
  assert.equal(h.presentationFrames(), 1, "nested RAF belongs to another frame batch");
  h.renderTime(1600);
  h.frame(42000); // Logical delay only: no real GPU wait or timer.
  assert.equal(h.timing.timeSwitchAckMs, "73");
  assert.equal(h.timing.timeSwitchPresentationMs, "41000", "presentation uses the command's time origin");
  assert.ok(Number(h.timing.timeSwitchPresentationMs) > Number(h.timing.timeSwitchAckMs));
  assert.equal(h.presentationFrames(), 0);
  h.renderTime(43000);
  h.frame(44000);
  assert.equal(h.timing.timeSwitchPresentationMs, "41000", "later render/frame must not rewrite the result");
});

test("time-switch presentation: zero-time acknowledgement still deduplicates the two-RAF chain", () => {
  const h = timeSwitchHarness(); h.bindTime();
  h.requestTime(0);
  h.renderTime(0);
  h.renderTime(0);
  assert.equal(h.timing.timeSwitchAckMs, "0");
  assert.equal(h.presentationFrames(), 1);
  h.frame(16);
  assert.equal(h.timing.timeSwitchPresentationMs, undefined);
  h.frame(32);
  assert.equal(h.timing.timeSwitchPresentationMs, "32");
  assert.equal(h.timing.timeSwitchAckMs, "0");
});

test("time-switch presentation: failure before either RAF prevents a pending presentation record", async () => {
  for (const framesBeforeFailure of [0, 1]) {
    const h = timeSwitchHarness();
    h.start();
    await flush(); // Set up the actual controls' engine-exit failure callback.
    h.bindTime();
    h.requestTime(1000);
    h.renderTime(1073);
    if (framesBeforeFailure) h.frame(1080);
    h.time(1100);
    h.godotConfig.onExit(1);
    h.frame(1120);
    h.frame(1140);
    assert.equal(h.timing.timeSwitchPresentationMs, undefined);
    assert.equal(h.timing.timeSwitchAckMs, "73", "an earlier acknowledgement remains historical, not a presentation");
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.element("loading-message").attributes.role, "alert");
    assert.equal(h.element("time-control").disabled, true);
    assert.equal(h.errors.length, 1);
    h.requestTime(1200);
    assert.equal(h.timing.timeSwitchRequestedAtMs, "1000", "failure unbinds further commands");
    assert.equal(h.presentationFrames(), 0);
  }
});

test("time-switch presentation: a new request before either RAF invalidates old work until its own acknowledgement", () => {
  for (const framesBeforeSwitch of [0, 1]) {
    const h = timeSwitchHarness(); h.bindTime();
    h.requestTime(1000);
    h.renderTime(1073);
    if (framesBeforeSwitch) h.frame(1080);
    h.requestTime(1100);
    assert.equal(h.timing.timeSwitchAckMs, undefined);
    assert.equal(h.timing.timeSwitchPresentationMs, undefined);
    h.frame(1120);
    h.frame(1140);
    assert.equal(h.timing.timeSwitchPresentationMs, undefined, "old request must not publish into the new request");
    h.renderTime(1200);
    assert.equal(h.timing.timeSwitchAckMs, "100");
    h.frame(1216);
    assert.equal(h.timing.timeSwitchPresentationMs, undefined);
    h.frame(1232);
    assert.equal(h.timing.timeSwitchPresentationMs, "132");
  }
});

test("time-switch presentation: superseded second RAF cannot publish before the current request's second RAF", () => {
  const h = timeSwitchHarness(); h.bindTime();
  h.requestTime(1000);
  h.renderTime(1073);
  h.frame(1080);
  h.requestTime(1100);
  h.renderTime(1101);
  assert.equal(h.presentationFrames(), 2, "old second RAF and current first RAF are both pending");
  h.frame(1120);
  assert.equal(h.timing.timeSwitchAckMs, "1");
  assert.equal(h.timing.timeSwitchPresentationMs, undefined);
  assert.equal(h.presentationFrames(), 1);
  h.frame(1140);
  assert.equal(h.timing.timeSwitchPresentationMs, "40");
});

test("time-switch presentation: a new request with the same clock timestamp still invalidates old RAFs", () => {
  for (const framesBeforeSwitch of [0, 1]) {
    const h = timeSwitchHarness(); h.bindTime();
    h.requestTime(1000);
    h.renderTime(1000);
    if (framesBeforeSwitch) h.frame(1000); // A coarse clock can repeat across frame/event callbacks.
    h.requestTime(1000);
    assert.equal(h.commands.filter(row => row.command === "time").length, 2);
    h.frame(1016);
    h.frame(1032);
    assert.equal(h.timing.timeSwitchAckMs, undefined, "second command has not been acknowledged");
    assert.equal(h.timing.timeSwitchPresentationMs, undefined,
      "a timestamp is not a unique request identity; old RAFs must not publish a new command's result");
    h.renderTime(1050);
    h.frame(1066);
    assert.equal(h.timing.timeSwitchPresentationMs, undefined);
    h.frame(1082);
    assert.equal(h.timing.timeSwitchAckMs, "50");
    assert.equal(h.timing.timeSwitchPresentationMs, "82");
  }
});

test("review pins the exact shipped Engine implementation", () => {
  assert.equal(createHash("sha256").update(engineText).digest("hex"),
    "33c94cb3175f3333b82e2a3be5e8e86f77986f0aa2042b1631f6367a4e5bb6ba");
});

for (const [label, directory] of [["v117", shipped], ["working source", __dirname]]) {
  test(`${label}: merely loading helpers creates no engine or download`, () => {
    const h = harness(directory);
    assert.equal(h.count("engineCreated"), 0);
    assert.equal(h.count("packFetch"), 0);
    assert.equal(h.count("wasmFetch"), 0);
  });

  for (const [quality, pack] of [["original", "index.pck"], ["balanced", "index-balanced.pck"], ["lite", "index-lite.pck"]]) {
    test(`${label}: ${quality} initializes one engine and preloads only its chosen pack`, async () => {
      const h = harness(directory);
      const args = ["--", `--meadow-quality=${quality}`, "--startup-audit"];
      h.start({ mainPack: pack, args });
      await flush();
      assert.equal(h.count("engineCreated"), 1);
      assert.equal(h.count("wasmFetch"), 1);
      assert.equal(h.count("moduleFactory"), 1);
      assert.equal(h.count("initFS"), 1);
      assert.equal(h.count("packFetch"), 1);
      assert.equal(h.count("copyBegin"), 1);
      assert.equal(h.events.find(row => row.name === "packFetch").value.file, pack);
      assert.deepEqual(h.events.find(row => row.name === "callMainBegin").value,
        ["--main-pack", pack, ...args]);
      assert.deepEqual(args, ["--", `--meadow-quality=${quality}`, "--startup-audit"]);
    });
  }

  test(`${label}: WASM/init and preload are concurrent, both must finish before start`, async () => {
    for (const first of ["wasm", "pack"]) {
      const h = harness(directory, { defer: ["wasm", "pack", "fs"] });
      h.start();
      assert.equal(h.count("wasmFetch"), 1);
      assert.equal(h.count("packFetch"), 1);
      h.time(1500);
      h.gates[first].resolve();
      await flush();
      assert.equal(h.count("callMainBegin"), 0);
      h.gates[first === "wasm" ? "pack" : "wasm"].resolve();
      await flush();
      assert.equal(h.count("callMainBegin"), 0, "persistent FS initialization still pending");
      h.time(1800);
      h.gates.fs.resolve();
      await flush();
      assert.equal(h.count("callMainBegin"), 1);
      assert.equal(h.element("canvas").dataset.runtimeStartMs, "1800");
      assert.equal(h.element("canvas").dataset.engineStartedMs, "1800");
    }
  });

  test(`${label}: executable fallback supplies one legacy pack`, async () => {
    const h = harness(directory);
    h.start({ executable: "legacy", mainPack: undefined, args: [] });
    await flush();
    assert.equal(h.events.find(row => row.name === "packFetch").value.file, "legacy.pck");
    assert.deepEqual(h.events.find(row => row.name === "callMainBegin").value,
      ["--main-pack", "legacy.pck"]);
  });

  test(`${label}: sceneReady before start resolution does not schedule presentation early`, async () => {
    const h = harness(directory, { onMain(h) {
      h.ui.sceneReady(4415);
      assert.equal(h.element("loading").hidden, false);
      assert.equal(h.presentationFrames(), 0);
      assert.equal(h.element("canvas").dataset.engineStartedMs, undefined);
    } });
    h.start();
    await flush();
    assert.equal(h.presentationFrames(), 1);
    h.frame(16);
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.presentationFrames(), 1, "nested RAF belongs to the next frame");
    h.frame(32);
    assert.equal(h.element("loading").hidden, true);
    assert.equal(h.element("loading").attributes["aria-busy"], "false");
    assert.equal(h.element("canvas").dataset.loadMs, "32");
    assert.equal(h.count("report"), 1);
  });

  test(`${label}: resolved engine alone and completed progress never substitute for sceneReady`, async () => {
    const h = harness(directory);
    h.start();
    await flush();
    h.preloader.progress(100, 100);
    h.frame(1000);
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.presentationFrames(), 0);
    h.ui.sceneReady(20);
    assert.equal(h.presentationFrames(), 1);
    h.frame(1016);
    assert.equal(h.element("loading").hidden, false);
    h.frame(1032);
    assert.equal(h.element("loading").hidden, true);
  });

  test(`${label}: duplicate ready signals keep one two-RAF presentation chain`, async () => {
    const h = harness(directory);
    h.start();
    await flush();
    h.ui.sceneReady(1);
    h.ui.sceneReady(2);
    assert.equal(h.presentationFrames(), 1);
    h.frame(16);
    h.ui.sceneReady(3);
    assert.equal(h.presentationFrames(), 1);
    h.frame(32);
    h.ui.sceneReady(4);
    assert.equal(h.presentationFrames(), 0);
    assert.equal(h.count("report"), 1);
  });

  test(`${label}: logical minutes after sceneReady can be inside synchronous callMain`, async () => {
    const h = harness(directory, { onMain(h) {
      h.time(20705);
      h.ui.sceneReady(4415);
      Promise.resolve().then(() => h.event("microtaskFromScene"));
      // No real sleep: simulate more synchronous runtime/driver work on this stack.
      h.time(251107);
      assert.equal(h.count("microtaskFromScene"), 0);
      assert.equal(h.presentationFrames(), 0);
    } });
    h.start();
    await flush();
    assert.equal(h.events.find(row => row.name === "callMainEnd").at, 251107);
    assert.equal(h.events.find(row => row.name === "microtaskFromScene").at, 251107);
    assert.equal(h.element("canvas").dataset.sceneSignalMs, "20705");
    assert.equal(h.element("canvas").dataset.engineStartedMs, "251107");
    assert.equal(h.element("loading").hidden, false);
    // Delayed frame delivery is separate from the already-resolved startup promise.
    h.frame(256000);
    assert.equal(h.element("loading").hidden, false);
    h.frame(261896);
    assert.equal(h.element("canvas").dataset.loadMs, "261896");
  });

  test(`${label}: synchronous file-copy cost precedes callMain and sceneReady`, async () => {
    const h = harness(directory, {
      onCopy(h) { h.time(120000); },
      onMain(h) { h.ui.sceneReady(20); },
    });
    h.start();
    await flush();
    const names = h.events.map(row => row.name);
    assert.ok(names.indexOf("copyEnd") < names.indexOf("callMainBegin"));
    assert.equal(h.element("canvas").dataset.sceneSignalMs, "120000");
    assert.equal(h.element("canvas").dataset.engineStartedMs, "120000");
    assert.equal(h.count("copyBegin"), 1);
  });

  test(`${label}: engineStarted can be late even when callMain already returned`, async () => {
    const h = harness(directory, { onMain(h) {
      h.time(20705);
      h.ui.sceneReady(4415);
      Promise.resolve().then(() => {
        h.event("queuedWorkBegin");
        // A logical clock jump models synchronous work in an earlier microtask.
        h.time(251107);
        h.event("queuedWorkEnd");
      });
    } });
    h.start();
    await flush();
    assert.equal(h.events.find(row => row.name === "callMainEnd").at, 20705);
    assert.equal(h.events.find(row => row.name === "queuedWorkEnd").at, 251107);
    assert.equal(h.element("canvas").dataset.engineStartedMs, "251107");
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.presentationFrames(), 1);
  });

  test(`${label}: clock-origin offset is not misreported as a two-RAF delay`, async () => {
    const h = harness(directory, { featureCost: 400, onMain(h) { h.time(5400); h.ui.sceneReady(4415); } });
    h.start();
    await flush();
    assert.equal(h.element("canvas").dataset.engineStartedMs, "5000");
    assert.equal(h.element("canvas").dataset.sceneSignalMs, "5400");
    h.frame(5416);
    h.frame(5432);
    assert.equal(h.element("canvas").dataset.loadMs, "5432");
    assert.equal(5432 - 5000, 432, "32ms of frames plus 400ms of different time origins");
  });

  test(`${label}: rejected preload or synchronous start failure reaches accessible error state`, async () => {
    for (const phase of ["preload", "copy", "callMain"]) {
      const h = harness(directory, {
        defer: phase === "preload" ? ["pack"] : [],
        onCopy() { if (phase === "copy") throw new Error("copy failure"); },
        onMain() { if (phase === "callMain") throw new Error("main failure"); },
      });
      h.start();
      if (phase === "preload") h.gates.pack.reject(new Error("pack failure"));
      await flush();
      h.ui.sceneReady(10);
      h.frame(16);
      h.frame(32);
      assert.equal(h.element("loading").hidden, false);
      assert.equal(h.element("loading-message").attributes.role, "alert");
      assert.equal(h.element("retry").hidden, false);
      assert.equal(h.presentationFrames(), 0);
      assert.equal(h.errors.length, 1);
    }
  });

  test(`${label}: exit between the two RAFs cannot hide an error`, async () => {
    const h = harness(directory, { onMain(h) { h.ui.sceneReady(10); } });
    h.start();
    await flush();
    h.frame(16);
    h.godotConfig.onExit(1);
    h.frame(32);
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.element("loading-message").attributes.role, "alert");
    assert.equal(h.count("report"), 0);
  });

  test(`${label}: hidden=0 does not rule out delayed frame delivery while visible`, async () => {
    const h = harness(directory, { onMain(h) { h.ui.sceneReady(10); } });
    h.start();
    await flush();
    h.frame(200000);
    h.frame(210000);
    assert.equal(h.element("canvas").dataset.loadHiddenMs, "0");
    assert.equal(h.element("canvas").dataset.loadMs, "210000");
  });
}

test("public start resolves after callMain, without exit or service-worker settlement", async () => {
  const h = harness(shipped);
  h.start({ serviceWorker: "fixture-sw.js" });
  await flush();
  assert.equal(h.count("callMainEnd"), 1);
  assert.equal(h.count("serviceWorkerRegister"), 1);
  assert.equal(h.element("canvas").dataset.engineStartedMs, "0");
  assert.equal(h.errors.length, 0);
});

test("public startGame and the loader perform the same one-pack lifecycle", async () => {
  const manual = harness(shipped);
  manual.start();
  await flush();
  const automatic = harness(shipped);
  const engine = new automatic.PublicEngine({ executable: "index", mainPack: "index-lite.pck",
    args: ["--", "--meadow-quality=lite"], fileSizes: {} });
  await engine.startGame();
  const relevant = new Set(["wasmFetch", "packFetch", "moduleFactory", "initFS", "initConfig",
    "copyBegin", "copyEnd", "callMainBegin", "callMainEnd"]);
  const sequence = h => h.events.filter(row => relevant.has(row.name)).map(row => row.name);
  assert.deepEqual(sequence(manual), sequence(automatic));
  assert.deepEqual(manual.events.find(row => row.name === "callMainBegin").value,
    automatic.events.find(row => row.name === "callMainBegin").value);
});

test("SafeEngine instance methods are not on the exported constructor prototype", () => {
  const h = harness(shipped);
  assert.equal(h.PublicEngine.prototype.start, undefined);
  const first = new h.PublicEngine({});
  const second = new h.PublicEngine({});
  assert.equal(typeof first.start, "function");
  assert.notEqual(Object.getPrototypeOf(first), Object.getPrototypeOf(second));
});

test("automatic preloaded-file copy bypasses the public instance copyToFS method", async () => {
  const h = harness(shipped, { defer: ["pack"] });
  h.start();
  h.engines[0].copyToFS = () => { throw new Error("Not on automatic copy path"); };
  h.gates.pack.resolve();
  await flush();
  assert.equal(h.count("copyBegin"), 1);
  assert.equal(h.count("callMainEnd"), 1);
  assert.equal(h.errors.length, 0);
});

test("actual shipped preloader has four attempts and three 1s failure backoffs, not a ready timeout", async () => {
  const begin = engineText.indexOf("const Preloader =");
  const end = engineText.indexOf("const EngineConfig =", begin);
  assert.ok(begin >= 0 && end > begin);
  const timers = [];
  let attempts = 0;
  const context = { Promise,
    fetch() { attempts += 1; return Promise.reject(new Error("fixture network failure")); },
    setTimeout(callback, delay) { timers.push({ callback, delay }); },
  };
  vm.runInNewContext(engineText.slice(begin, end) + "\nglobalThis.fixture = new Preloader();", context);
  const outcome = context.fixture.loadPromise("fixture.pck", 1).catch(error => error.message);
  await flush();
  for (let retry = 0; retry < 3; retry += 1) {
    assert.equal(timers.length, 1);
    const timer = timers.shift();
    assert.equal(timer.delay, 1000);
    timer.callback();
    await flush();
  }
  assert.equal(await outcome, "fixture network failure");
  assert.equal(attempts, 4);
  assert.equal(timers.length, 0);
});

// Separate review of main-owned opt-in tracing. These are native-API mocks,
// not a GPU profile or authority to edit the helper here.
function traceHarness(options = {}) {
  let clock = 0;
  const h = { calls: [], observers: [], linkCost: 0, nativeError: null,
    rendererError: null, parameterError: null, contextError: null,
    shaderError: null, attachError: null, traceWrites: 0,
    result: { native: "unchanged" }, advance(ms) { clock += ms; } };
  class Canvas {
    constructor() { this.dataset = {}; this.width = 1280; this.height = 800; }
    getContext(...args) {
      h.calls.push({ name: "getContext", receiver: this, args });
      clock += options.contextCost || 0;
      if (h.contextError) throw h.contextError;
      return this.gl;
    }
  }
  class GL {
    constructor(canvas) { this.canvas = canvas; this.VENDOR = 7936; this.RENDERER = 7937; }
    shaderSource(...args) {
      h.calls.push({ name: "shaderSource", receiver: this, args });
      if (h.shaderError) throw h.shaderError;
      return h.result;
    }
    attachShader(...args) {
      h.calls.push({ name: "attachShader", receiver: this, args });
      if (h.attachError) throw h.attachError;
      return h.result;
    }
    linkProgram(...args) {
      h.calls.push({ name: "linkProgram", receiver: this, args });
      clock += h.linkCost;
      if (h.nativeError) throw h.nativeError;
      return h.result;
    }
    bufferData(...args) { h.calls.push({ name: "bufferData", receiver: this, args }); }
    getExtension(...args) {
      h.calls.push({ name: "getExtension", receiver: this, args });
      if (h.rendererError) throw h.rendererError;
      return options.noExtension ? null : { UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 };
    }
    getParameter(parameter) {
      h.calls.push({ name: "getParameter", receiver: this, args: [parameter] });
      if (h.parameterError) throw h.parameterError;
      return [7936, 37445].includes(parameter) ? "Fixture vendor" : "Fixture renderer";
    }
  }
  class Observer {
    constructor(callback) { this.callback = callback; h.observers.push(this); }
    observe(settings) { this.settings = settings; if (options.observerThrows) throw new Error("unsupported"); }
    disconnect() { this.disconnected = true; }
  }
  h.canvas = options.canvas || new Canvas();
  let traceValue;
  Object.defineProperty(h.canvas.dataset, "startupTrace", {
    configurable: true, enumerable: true,
    get() { return traceValue; },
    set(value) { h.traceWrites += 1; traceValue = value; }
  });
  h.otherCanvas = new Canvas();
  h.gl = h.canvas.gl = new GL(h.canvas);
  h.otherCanvas.gl = new GL(h.otherCanvas);
  h.GL = GL;
  h.Canvas = Canvas;
  h.originalLink = GL.prototype.linkProgram;
  h.originalBuffer = GL.prototype.bufferData;
  h.originalSource = GL.prototype.shaderSource;
  h.originalAttach = GL.prototype.attachShader;
  h.originalContext = Canvas.prototype.getContext;
  const window = { location: { search: options.search ?? "?startup_trace=1" },
    devicePixelRatio: 1.5, WebGL2RenderingContext: GL };
  const unexpected = () => { throw new Error("Trace must not log, fetch or schedule timers"); };
  const context = { window, URLSearchParams, HTMLCanvasElement: Canvas,
    performance: { now: () => clock },
    document: { visibilityState: "visible", hasFocus: () => true },
    PerformanceObserver: Observer, fetch: unexpected, setTimeout: unexpected, setInterval: unexpected,
    console: { log: unexpected, info: unexpected, warn: unexpected, error: unexpected,
      debug: unexpected, table: unexpected } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "meadow-startup-trace.js"), "utf8"), context,
    { filename: "main-owned-startup-trace.js" });
  h.trace = window.meadowStartupTrace;
  h.install = () => h.trace.install(h.canvas);
  h.report = () => JSON.parse(h.canvas.dataset.startupTrace);
  return h;
}

test("trace: missing/unknown/false opt-in leaves all prototypes and DOM untouched", () => {
  for (const search of ["", "?startup_trace=0", "?startup_trace=true", "?other=1"]) {
    const h = traceHarness({ search });
    assert.equal(h.trace, undefined);
    assert.equal(h.GL.prototype.linkProgram, h.originalLink);
    assert.equal(h.Canvas.prototype.getContext, h.originalContext);
    assert.equal(h.canvas.dataset.startupTrace, undefined);
    assert.equal(h.observers.length, 0);
  }
});

test("trace: install is idempotent; GL this, arguments, return and canvas inputs are preserved", () => {
  const h = traceHarness();
  h.install();
  const measured = h.GL.prototype.linkProgram;
  h.install();
  assert.equal(h.GL.prototype.linkProgram, measured);
  assert.equal(h.observers.length, 1);
  const program = {};
  const extra = { untouched: true };
  assert.equal(h.gl.linkProgram(program, extra), h.result);
  const call = h.calls.at(-1);
  assert.equal(call.receiver, h.gl);
  assert.equal(call.args[0], program);
  assert.equal(call.args[1], extra);
  assert.deepEqual([h.canvas.width, h.canvas.height], [1280, 800]);
  h.trace.mark("fixture");
  assert.equal(h.report().totals.linkProgram.calls, 1);
});

test("trace: unrelated contexts and canvases pass through without measurement", () => {
  const h = traceHarness();
  h.install();
  h.linkCost = 50;
  assert.equal(h.otherCanvas.getContext("webgl2"), h.otherCanvas.gl);
  assert.equal(h.otherCanvas.gl.linkProgram({}), h.result);
  h.trace.mark("fixture");
  assert.deepEqual(h.report().totals, {});
  assert.equal(h.calls.filter(row => row.name === "getParameter").length, 0);
});

test("trace: slow native exceptions keep their identity with successful diagnostic recording", () => {
  const h = traceHarness();
  h.install();
  h.linkCost = 30;
  h.nativeError = new Error("native failure");
  assert.throws(() => h.gl.linkProgram({}), error => error === h.nativeError);
  assert.equal(h.report().totals.linkProgram.calls, 1);
  assert.equal(h.report().slow[0].ms, 30);
});

test("trace: renderer capture preserves getContext result/options with extension and fallback", () => {
  for (const noExtension of [false, true]) {
    const h = traceHarness({ noExtension, contextCost: 7 });
    h.install();
    const attributes = { antialias: false, alpha: true };
    assert.equal(h.canvas.getContext("webgl2", attributes), h.gl);
    assert.equal(h.calls.find(row => row.name === "getContext").args[1], attributes);
    h.trace.mark("context-created");
    assert.deepEqual(h.report().renderer, { vendor: "Fixture vendor", device: "Fixture renderer" });
    assert.deepEqual(attributes, { antialias: false, alpha: true });
    assert.equal(h.report().totals.getParameter.calls, 2, "diagnostic queries are included in totals");
    assert.equal(h.report().totals.getContext, undefined, "current helper samples, but does not time getContext");
    assert.equal(h.report().elapsedMs, 7);
  }
});

test("trace: slow-call and observer details are bounded while aggregate counts continue", () => {
  const h = traceHarness();
  h.install();
  h.linkCost = 21;
  const program = {};
  for (let i = 0; i < 205; i += 1) h.gl.linkProgram(program);
  h.observers[0].callback({ getEntries: () => Array.from({ length: 100 }, (_, startTime) =>
    ({ startTime, duration: 51 })) });
  h.trace.mark("after-limit");
  assert.equal(h.report().slow.length, 200);
  assert.equal(h.report().totals.linkProgram.calls, 205);
  assert.equal(h.report().longTasks.length, 80);
  assert.equal(h.report().slow[0].program, h.report().slow[199].program);
});

test("trace: finish restores owned wrappers, disconnects observer and is idempotent", () => {
  const h = traceHarness();
  h.install();
  h.gl.linkProgram({});
  h.trace.finish();
  assert.equal(h.GL.prototype.linkProgram, h.originalLink);
  assert.equal(h.Canvas.prototype.getContext, h.originalContext);
  assert.equal(h.observers[0].disconnected, true);
  assert.equal(h.report().status, "completed");
  const result = h.canvas.dataset.startupTrace;
  h.gl.linkProgram({});
  h.trace.finish();
  assert.equal(h.canvas.dataset.startupTrace, result);
});

test("trace: finish does not overwrite another owner's later wrapper", () => {
  const h = traceHarness();
  h.install();
  const otherOwner = function () {};
  h.GL.prototype.bufferData = otherOwner;
  h.trace.finish();
  assert.equal(h.GL.prototype.bufferData, otherOwner);
  assert.equal(h.GL.prototype.linkProgram, h.originalLink);
});

test("trace: unsupported long-task observation does not prevent GL tracing or cleanup", () => {
  const h = traceHarness({ observerThrows: true });
  assert.doesNotThrow(h.install);
  assert.equal(h.gl.linkProgram({}), h.result);
  h.trace.finish();
  assert.equal(h.GL.prototype.linkProgram, h.originalLink);
});

test("trace: aggregate duration retains sub-0.1ms contributions", () => {
  const h = traceHarness();
  h.install();
  h.linkCost = 0.04;
  for (let i = 0; i < 10; i += 1) h.gl.linkProgram({});
  h.trace.mark("fractional-total");
  assert.ok(Math.abs(h.report().totals.linkProgram.ms - 0.4) < 1e-9,
    "10 calls of 0.04ms should total 0.4ms, not zero");
});

test("trace runtime: initConfig/copyToFS/callMain preserve receiver, argument identity and return", () => {
  const h = traceHarness();
  h.install();
  const runtime = {};
  const seen = [];
  const result = {};
  const names = ["initConfig", "copyToFS", "callMain"];
  for (const name of names) runtime[name] = function (...args) {
    seen.push({ name, receiver: this, args });
    h.advance(12.5);
    return result;
  };
  const original = { ...runtime };
  h.trace.instrumentEngine({ rtenv: runtime });
  const config = { canvas: h.canvas };
  const buffer = new Uint8Array([1, 2, 3]);
  const args = ["--main-pack", "fixture.pck"];
  assert.equal(runtime.initConfig(config), result);
  assert.equal(runtime.copyToFS("fixture.pck", buffer), result);
  assert.equal(runtime.callMain(args), result);
  assert.ok(seen.every(row => row.receiver === runtime));
  assert.equal(seen[0].args[0], config);
  assert.equal(seen[1].args[1], buffer);
  assert.equal(seen[2].args[0], args);
  assert.deepEqual(h.report().marks.map(row => row.name), ["trace-installed",
    "initConfig:enter", "initConfig:return", "copyToFS:enter", "copyToFS:return", "callMain:enter", "callMain:return"]);
  assert.equal(h.report().marks.at(-1).ms, 37.5);
  h.trace.finish();
  for (const name of names) assert.equal(runtime[name], original[name]);
});

test("trace runtime: thrown errors/values are not swallowed and finally markers still fire", () => {
  for (const name of ["initConfig", "copyToFS", "callMain"]) {
    for (const failure of [new Error("native runtime error"), "unwind", { exitStatus: 1 }]) {
      const h = traceHarness();
      h.install();
      const runtime = { [name]() { h.advance(5); throw failure; } };
      h.trace.instrumentEngine({ rtenv: runtime });
      let caught;
      try { runtime[name](); } catch (error) { caught = error; }
      assert.equal(caught, failure);
      assert.deepEqual(h.report().marks.map(row => row.name),
        ["trace-installed", `${name}:enter`, `${name}:return`]);
      assert.equal(h.report().marks.at(-1).ms, 5);
    }
  }
});

test("trace runtime: absent/private-version-mismatched methods are skipped without inventing hooks", () => {
  const h = traceHarness();
  h.install();
  for (const rtenv of [undefined, null, {}, { callMain: "not a function", copyToFS: 7 }]) {
    assert.doesNotThrow(() => h.trace.instrumentEngine({ rtenv }));
  }
  assert.deepEqual(h.report().marks.map(row => row.name), ["trace-installed"]);
  const runtime = { initConfig() {}, extra() {} };
  const extra = runtime.extra;
  h.trace.instrumentEngine({ rtenv: runtime });
  assert.equal(runtime.extra, extra);
  assert.equal(runtime.callMain, undefined);
});

test("trace runtime: restoration preserves a later owner's replacement", () => {
  const h = traceHarness();
  h.install();
  const runtime = { callMain() {} };
  h.trace.instrumentEngine({ rtenv: runtime });
  const replacement = function () {};
  runtime.callMain = replacement;
  h.trace.finish();
  assert.equal(runtime.callMain, replacement);
});

test("working loader instruments the initialized runtime once, before config/copy/callMain", async () => {
  const h = harness(__dirname, { defer: ["fs", "pack"] });
  let calls = 0;
  h.window.meadowStartupTrace = {
    install() {}, mark() {}, finish() {},
    instrumentEngine(engine) {
      calls += 1;
      assert.equal(engine, h.engines[0]);
      assert.equal(typeof engine.rtenv.callMain, "function");
      assert.equal(h.count("initConfig"), 0);
      assert.equal(h.count("copyBegin"), 0);
      h.event("instrumentEngine");
    }
  };
  h.start();
  h.gates.pack.resolve();
  await flush();
  assert.equal(calls, 0);
  h.gates.fs.resolve();
  await flush();
  assert.equal(calls, 1);
  const sequence = h.events.map(row => row.name);
  assert.ok(sequence.indexOf("instrumentEngine") < sequence.indexOf("initConfig"));
  assert.ok(sequence.indexOf("initConfig") < sequence.indexOf("copyBegin"));
  assert.ok(sequence.indexOf("copyBegin") < sequence.indexOf("callMainBegin"));
});

test("trace: optional renderer diagnostics fail open after successful getContext", () => {
  for (const failureSite of ["rendererError", "parameterError"]) {
    const h = traceHarness();
    h.install();
    h[failureSite] = new Error("optional renderer query failed");
    const attributes = { antialias: false };
    assert.equal(h.canvas.getContext("webgl2", attributes), h.gl);
    assert.equal(h.calls.find(row => row.name === "getContext").args[1], attributes);
    h.trace.mark("renderer-unavailable");
    assert.deepEqual(h.report().renderer, { unavailable: true });
    assert.equal(h.report().status, "running", "unavailable diagnostics are not a load failure");
    const queries = h.calls.filter(row => row.name === "getExtension").length;
    assert.equal(h.canvas.getContext("webgl2", attributes), h.gl);
    assert.equal(h.calls.filter(row => row.name === "getExtension").length, queries,
      "do not repeat a failed optional renderer probe");
  }
});

test("trace: native getContext errors and null contexts are not hidden by renderer fail-open", () => {
  const h = traceHarness();
  h.install();
  h.contextError = new Error("native context creation failed");
  assert.throws(() => h.canvas.getContext("webgl2"), error => error === h.contextError);
  h.contextError = null;
  h.canvas.gl = null;
  assert.equal(h.canvas.getContext("webgl2"), null);
  assert.equal(h.calls.filter(row => row.name === "getExtension").length, 0);
});

test("trace: loader errors finish real instrumentation with failed, never presentation", async () => {
  for (const phase of ["preload", "copy", "callMain", "between-frames"]) {
    const failure = new Error(`${phase} fixture failure`);
    const h = harness(__dirname, {
      defer: phase === "preload" ? ["pack"] : [],
      onCopy() { if (phase === "copy") throw failure; },
      onMain(h) {
        if (phase === "callMain") throw failure;
        if (phase === "between-frames") h.ui.sceneReady(20);
      },
    });
    const t = traceHarness({ canvas: h.element("canvas") });
    h.window.meadowStartupTrace = t.trace;
    h.start();
    if (phase === "preload") h.gates.pack.reject(failure);
    await flush();
    if (phase === "between-frames") {
      h.frame(16);
      h.godotConfig.onExit(1);
      h.frame(32);
    }
    assert.equal(t.report().status, "completed", "completed means tracing ended, not startup succeeded");
    assert.equal(t.report().marks.filter(row => row.name === "failed").length, 1);
    assert.equal(t.report().marks.some(row => row.name === "presentation"), false);
    assert.equal(t.GL.prototype.linkProgram, t.originalLink);
    assert.equal(t.GL.prototype.shaderSource, t.originalSource);
    assert.equal(t.GL.prototype.attachShader, t.originalAttach);
    assert.equal(t.Canvas.prototype.getContext, t.originalContext);
    assert.equal(t.observers[0].disconnected, true);
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.element("loading-message").attributes.role, "alert");
    assert.equal(h.count("report"), 0);
    assert.equal(h.errors.length, 1);
    if (phase !== "between-frames") assert.equal(h.errors[0], failure);
    const result = h.element("canvas").dataset.startupTrace;
    t.trace.finish();
    assert.equal(h.element("canvas").dataset.startupTrace, result,
      "a later finish must not relabel failure as presentation");
  }
});

test("trace: successful controls finish with presentation only at the second RAF", async () => {
  const h = harness(__dirname, { onMain(h) { h.ui.sceneReady(20); } });
  const t = traceHarness({ canvas: h.element("canvas") });
  h.window.meadowStartupTrace = t.trace;
  h.start();
  await flush();
  assert.equal(t.report().status, "running");
  h.frame(16);
  assert.equal(t.report().status, "running");
  h.frame(32);
  assert.equal(t.report().status, "completed");
  assert.equal(t.report().marks.at(-1).name, "presentation");
  assert.equal(t.report().marks.some(row => row.name === "failed"), false);
  assert.equal(h.element("loading").hidden, true);
  assert.equal(t.observers[0].disconnected, true);
});

test("trace metadata: only small labels reach slow-program records, without shader bodies or extra GL calls", () => {
  const h = traceHarness();
  h.install();
  const vertex = {}, fragment = {}, program = {};
  const vertexSource = "#define MODE_VERTEX\n#define MAX_FORWARD_LIGHTS 8\n// grove_root_v\nvoid UNIQUE_VERTEX_BODY() {}";
  const fragmentSource = "#define DISABLE_FOG\n#define MAX_LIGHT_DATA_STRUCTS 256\n// contact_shadows bed_depth\nvoid UNIQUE_FRAGMENT_BODY() {}";
  assert.equal(h.gl.shaderSource(vertex, vertexSource), h.result);
  assert.equal(h.gl.shaderSource(fragment, fragmentSource), h.result);
  assert.equal(h.gl.attachShader(program, vertex), h.result);
  assert.equal(h.gl.attachShader(program, fragment), h.result);
  assert.equal(h.traceWrites, 1, "metadata calls do not each stringify or publish a trace");
  h.linkCost = 25;
  assert.equal(h.gl.linkProgram(program), h.result);
  const row = h.report().slow[0];
  assert.equal(row.program, 1);
  assert.equal(row.sources.length, 2);
  assert.deepEqual(row.sources[0].tags, ["grove_root_v"]);
  assert.deepEqual(row.sources[1].tags, ["contact_shadows", "bed_depth"]);
  assert.deepEqual(row.sources[0].defines, ["#define MODE_VERTEX", "#define MAX_FORWARD_LIGHTS 8"]);
  assert.deepEqual(row.sources[1].defines, ["#define DISABLE_FOG", "#define MAX_LIGHT_DATA_STRUCTS 256"]);
  for (const [metadata, source] of [[row.sources[0], vertexSource], [row.sources[1], fragmentSource]]) {
    assert.deepEqual(Object.keys(metadata).sort(), ["bytes", "defines", "hash", "tags"]);
    assert.equal(metadata.bytes, source.length);
    assert.match(metadata.hash, /^[a-f0-9]{1,8}$/);
  }
  assert.equal(h.canvas.dataset.startupTrace.includes("UNIQUE_VERTEX_BODY"), false);
  assert.equal(h.canvas.dataset.startupTrace.includes("UNIQUE_FRAGMENT_BODY"), false);
  assert.deepEqual(h.calls.map(call => call.name),
    ["shaderSource", "shaderSource", "attachShader", "attachShader", "linkProgram"]);
  assert.ok(h.calls.every(call => call.receiver === h.gl));
  assert.equal(h.calls[0].args[0], vertex);
  assert.equal(h.calls[0].args[1], vertexSource);
  assert.equal(h.calls[2].args[0], program);
  assert.equal(h.calls[2].args[1], vertex);
  assert.equal(h.traceWrites, 2, "one additional snapshot for the slow call");
});

test("trace metadata: known tag whitelist and first twenty-four selected defines bound label counts", () => {
  const h = traceHarness();
  h.install();
  const tags = ["contact_shadows", "cloud_centres", "grove_root_v", "architecture_fog_density",
    "architecture_ab", "sunbreak_transmission", "bed_depth", "lit_windows", "canopy_lobes",
    "scene_exposure", "wing_phase", "meadow_mineral", "moon_direction"];
  const defines = Array.from({ length: 25 }, (_, index) => `#define MODE_FIXTURE_${index}`);
  const source = ["#define UNRELATED_DO_NOT_LOG 1", ...defines, `// ${tags.join(" ")} unknown_tag`].join("\n");
  const shader = {}, program = {};
  h.gl.shaderSource(shader, source);
  h.gl.attachShader(program, shader);
  h.linkCost = 21;
  h.gl.linkProgram(program);
  const metadata = h.report().slow[0].sources[0];
  assert.deepEqual(metadata.tags, tags);
  assert.deepEqual(metadata.defines, defines.slice(0, 24));
  assert.equal(h.canvas.dataset.startupTrace.includes("UNRELATED_DO_NOT_LOG"), false);
  assert.equal(h.canvas.dataset.startupTrace.includes("unknown_tag"), false);
});

test("trace metadata: identical sources correlate across programs without mixing their identities", () => {
  const h = traceHarness();
  h.install();
  const shaders = [{}, {}, {}], programs = [{}, {}, {}];
  for (let index = 0; index < shaders.length; index += 1) {
    const source = index < 2 ? "hello" : "different source";
    h.gl.shaderSource(shaders[index], source);
    h.gl.attachShader(programs[index], shaders[index]);
    h.linkCost = 21;
    h.gl.linkProgram(programs[index]);
  }
  const rows = h.report().slow;
  assert.deepEqual(rows.map(row => row.program), [1, 2, 3]);
  assert.equal(rows[0].sources[0].hash, "4f9f2cab", "known FNV-1a fixture");
  assert.equal(rows[1].sources[0].hash, rows[0].sources[0].hash);
  assert.notEqual(rows[2].sources[0].hash, rows[0].sources[0].hash);
});

test("trace metadata: opt-out, unrelated canvases and stopped wrappers do not inspect source inputs", () => {
  const source = { toString() { throw new Error("metadata should not inspect this input"); } };
  const off = traceHarness({ search: "?startup_trace=0" });
  assert.equal(off.gl.shaderSource({}, source), off.result);
  assert.equal(off.GL.prototype.shaderSource, off.originalSource);
  const h = traceHarness();
  h.install();
  assert.equal(h.otherCanvas.gl.shaderSource({}, source), h.result);
  const measured = h.GL.prototype.shaderSource;
  h.trace.finish("failed");
  const snapshot = h.canvas.dataset.startupTrace;
  assert.equal(measured.call(h.gl, {}, source), h.result);
  assert.equal(h.GL.prototype.shaderSource, h.originalSource);
  assert.equal(h.GL.prototype.attachShader, h.originalAttach);
  assert.equal(h.canvas.dataset.startupTrace, snapshot);
});

test("trace metadata: native source/attachment exceptions are propagated for valid engine-shaped arguments", () => {
  const h = traceHarness();
  h.install();
  const shader = {}, program = {};
  h.shaderError = new Error("native shaderSource failure");
  assert.throws(() => h.gl.shaderSource(shader, "void main() {}"), error => error === h.shaderError);
  h.shaderError = null;
  h.attachError = new Error("native attachShader failure");
  assert.throws(() => h.gl.attachShader(program, shader), error => error === h.attachError);
  assert.deepEqual(h.calls.map(call => call.name), ["shaderSource", "attachShader"]);
  h.trace.mark("metadata-exceptions");
  assert.equal(h.report().totals.shaderSource.calls, 1);
  assert.equal(h.report().totals.attachShader.calls, 1);
});

function compileIntegrationSource() {
  const reference = fs.readFileSync(path.resolve(__dirname,
    "../../artifacts/startup-v118/godot-analysis/engine-reference/drivers/gles3/shaders/scene.glsl"), "utf8");
  assert.equal(createHash("sha256").update(reference).digest("hex"),
    "2c77be0c85b7ab1a85ed8009c77cdb6216f1494d43083592213ad68f9e812977");
  // Actual pinned loop bodies, not a complete compilable/generated night shader.
  return "#version 300 es\n#define MAX_FORWARD_LIGHTS 8u\nprecision highp float;\nprecision highp int;\n" +
    reference.slice(reference.indexOf("#[fragment]") + "#[fragment]".length)
      .replace(/^#include[^\r\n]*/gm, "// offline fixture: expanded include omitted");
}

function compileLoaderIntegration(source, options = {}) {
  const h = traceHarness();
  h.disposeCalls = 0;
  const window = { location: { search: "?fast_compile=1&startup_trace=1" },
    HTMLCanvasElement: h.Canvas, WebGL2RenderingContext: h.GL,
    meadowStartupTrace: h.trace, performance: { now: () => 0 } };
  const context = { window, URLSearchParams };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "meadow-webgl-compile.js"), "utf8"), context);
  h.compile = window.meadowWebglCompile;
  // Exercise the real helper's install/dispose. The spy only counts disposal
  // and optionally throws AFTER real cleanup to test the loader's catch guard.
  window.meadowWebglCompile = { ...h.compile, install(canvas) {
    const dispose = h.compile.install(canvas);
    h.dispose = () => {
      h.disposeCalls++;
      dispose();
      if (options.cleanupThrows) throw new Error("fixture cleanup error must not replace startup error");
    };
    return h.dispose;
  } };
  class Engine {
    constructor() { if (options.phase === "constructor") throw options.failure; }
    init() {
      if (options.phase === "init-sync") throw options.failure;
      return options.phase === "init-reject" ? Promise.reject(options.failure) : Promise.resolve();
    }
    preloadFile() {
      if (options.phase === "preload-sync") throw options.failure;
      return options.phase === "preload-reject" ? Promise.reject(options.failure) : Promise.resolve();
    }
    start() {
      if (options.phase === "start-sync") throw options.failure;
      if (options.phase === "start-reject") return Promise.reject(options.failure);
      h.canvas.getContext("webgl2", { antialias: false });
      if (options.phase === "native-source") h.shaderError = options.failure;
      h.gl.shaderSource({}, source);
      h.canvas.dataset.sceneSignalMs = "10";
      h.trace.mark("sceneReady");
      return Promise.resolve();
    }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "meadow-loader.js"), "utf8"), { ...context, Engine });
  h.start = () => window.meadowLoader.start({ executable: "index", mainPack: "index-lite.pck" }, {}, h.canvas);
  h.compileReport = () => JSON.parse(h.canvas.dataset.fastCompile);
  return h;
}

test("compile integration: fatal startup disposes only its target and rethrows the original error", async () => {
  const source = compileIntegrationSource();
  for (const phase of ["constructor", "init-sync", "init-reject", "preload-sync", "preload-reject",
    "start-sync", "start-reject", "native-source"]) {
    for (const cleanupThrows of [false, true]) {
      const failure = new Error(`${phase} original startup failure`);
      const h = compileLoaderIntegration(source, { phase, failure, cleanupThrows });
      const disposeOther = h.compile.install(h.otherCanvas);
      h.otherCanvas.getContext("webgl2");
      const otherWrapper = h.otherCanvas.gl.shaderSource;
      const otherState = h.otherCanvas.dataset.fastCompile;
      await assert.rejects(h.start(), error => error === failure);
      assert.equal(h.disposeCalls, 1, `${phase}: exactly one loader-owned cleanup`);
      assert.equal(h.compileReport().status, "disposed");
      assert.equal(Object.hasOwn(h.canvas, "getContext"), false);
      assert.equal(Object.hasOwn(h.gl, "shaderSource"), false);
      assert.equal(h.otherCanvas.gl.shaderSource, otherWrapper);
      assert.equal(h.otherCanvas.dataset.fastCompile, otherState, "another canvas is not disposed or relabeled");
      assert.equal(h.report().status, "running", "loader catch does not own trace completion; controls handles that");
      disposeOther();
      h.trace.finish("failed");
      assert.equal(h.GL.prototype.shaderSource, h.originalSource);
      assert.equal(h.Canvas.prototype.getContext, h.originalContext);
    }
  }
});

test("compile integration: successful startup and trace completion retain later night-source rewriting", async () => {
  const source = compileIntegrationSource();
  const h = compileLoaderIntegration(source);
  await h.start();
  assert.equal(h.disposeCalls, 0, "success must not run fatal cleanup");
  assert.equal(h.compileReport().status, "bound");
  assert.equal(h.compileReport().rewrittenCalls, 1);
  assert.equal(Object.hasOwn(h.canvas, "getContext"), false, "context discovery is already restored");
  const wrapper = h.gl.shaderSource;
  // The real controls call this at presentation; it must not dispose the
  // separately owned compiler hook. RAF ordering is covered by existing cases.
  h.trace.finish();
  assert.equal(h.GL.prototype.shaderSource, h.originalSource);
  assert.equal(h.gl.shaderSource, wrapper);
  assert.equal(h.disposeCalls, 0);
  const stoppedTrace = h.canvas.dataset.startupTrace;
  const nightSource = source.replace("#CODE : LIGHT", "float m_night_fixture = 1.0;");
  assert.equal(h.gl.shaderSource({}, nightSource), h.result);
  const submitted = h.calls.at(-1).args[1];
  assert.notEqual(submitted, nightSource);
  assert.equal((submitted.match(/min\(uint\(MAX_FORWARD_LIGHTS\),/g) || []).length, 3);
  assert.equal(h.compileReport().rewrittenCalls, 2);
  assert.equal(h.compileReport().rewrittenLoops, 6);
  assert.equal(h.canvas.dataset.startupTrace, stoppedTrace, "night source does not restart finished timing");
  h.otherCanvas.gl.shaderSource({}, nightSource);
  assert.equal(h.calls.at(-1).args[1], nightSource, "unrelated context remains unchanged");
  h.dispose();
  assert.equal(h.disposeCalls, 1);
  assert.equal(Object.hasOwn(h.gl, "shaderSource"), false);
});
