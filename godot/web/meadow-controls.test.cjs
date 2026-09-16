const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "meadow-controls.js"), "utf8");
const loaderSource = fs.readFileSync(path.join(__dirname, "meadow-loader.js"), "utf8");

function harness({ reduced = false, missing = [], loadError = null, clock = () => 100, raf = (fn) => fn() } = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, dataset: {}, attributes: {}, handlers: {}, disabled: true, hidden: false,
      tagName: id === "canvas" ? "CANVAS" : "BUTTON",
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      addEventListener(name, callback) { this.handlers[name] = callback; }
    });
    return elements.get(id);
  }
  const document = { body: { dataset: {} }, getElementById: element, handlers: {},
    addEventListener(name, handler) { this.handlers[name] = handler; },
    removeEventListener(name) { delete this.handlers[name]; } };
  const preference = { matches: reduced, addEventListener(name, handler) { this[name] = handler; } };
  const calls = [];
  const errors = [];
  const window = { matchMedia: () => preference, location: { reload: () => calls.push(["reload"]) },
    performance: { now: clock }, requestAnimationFrame: raf };
  class Engine {
    constructor(config) { this.options = config; }
    static getMissingFeatures() { return missing; }
    init() { return Promise.resolve(); }
    preloadFile() { return Promise.resolve(); }
    start(options) {
      calls.push(["start", { ...this.options, ...options }]);
      return loadError ? Promise.reject(loadError) : Promise.resolve();
    }
  }
  vm.runInNewContext(loaderSource + source, { document, window, Engine, URL,
    console: { error: e => errors.push(e), info() {} } });
  const ui = window.meadowTimeUI;
  return { ui, element, document, preference, calls, errors,
    bind: () => ui.bind((...args) => calls.push(args)) };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test("buttons stay disabled until Godot binds; reduced motion is forwarded", () => {
  const h = harness({ reduced: true });
  assert.equal(h.element("time-control").disabled, true);
  h.bind();
  assert.equal(h.element("time-control").disabled, false);
  assert.deepEqual(h.calls, [["reduced_motion", true]]);
  h.element("time-control").handlers.click();
  h.element("motion-control").handlers.click();
  assert.deepEqual(h.calls.slice(-2), [["time"], ["motion"]]);
  h.ui.unbind();
  assert.equal(h.element("motion-control").disabled, true);
});

test("the acknowledged Godot state controls labels, animation state and announcements", () => {
  const h = harness();
  h.ui.render(true, 0.41, false, true, 12.5);
  assert.equal(h.element("time-label").textContent, "破晓");
  assert.equal(h.element("time-control").attributes["aria-label"], "破晓，切换到白天");
  assert.equal(h.element("canvas").dataset.nightBlend, "0.410");
  assert.equal(h.element("canvas").dataset.motion, "false");
  assert.equal(h.element("motion-control").attributes["aria-label"], "播放环境动画");
  assert.equal(h.element("time-state").textContent, undefined);
  h.ui.render(true, 1, false, false, 12.5);
  assert.equal(h.element("time-state").textContent, "已切换到夜晚，环境动画已暂停。");
  h.ui.render(false, 0, true, false, 13);
  assert.equal(h.element("time-state").textContent, "已切换到白天，环境动画正在播放。");
});

test("keyboard shortcuts do not double-dispatch canvas input, repeats or modified keys", () => {
  const h = harness();
  h.bind();
  const keydown = h.document.handlers.keydown;
  const event = { target: h.element("time-control"), code: "KeyN",
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; } };
  keydown(event);
  assert.equal(event.prevented, true);
  assert.deepEqual(h.calls.at(-1), ["time"]);
  const count = h.calls.length;
  keydown({ ...event, target: h.element("canvas") });
  keydown({ ...event, repeat: true });
  keydown({ ...event, ctrlKey: true });
  keydown({ ...event, target: { tagName: "INPUT" } });
  assert.equal(h.calls.length, count);
});

test("system motion preference changes are passed to Godot", () => {
  const h = harness();
  h.bind();
  h.preference.change({ matches: true });
  assert.deepEqual(h.calls.at(-1), ["reduced_motion", true]);
});

test("successful engine startup removes loading without stealing keyboard focus", async () => {
  const h = harness();
  h.ui.start({});
  await settle();
  assert.equal(h.element("loading").hidden, false);
  h.ui.sceneReady(123);
  assert.equal(h.element("loading").hidden, true);
  assert.equal(h.element("canvas").dataset.sceneBuildMs, "123");
  const options = h.calls.find(call => call[0] === "start")[1];
  assert.equal(options.focusCanvas, false);
  options.onProgress(50, 100);
  assert.equal(h.element("loading-progress").value, 50);
});

test("scene readiness may arrive before the start promise; completed downloads show build state", async () => {
  const h = harness();
  h.ui.start({});
  await settle();
  const options = h.calls.find(call => call[0] === "start")[1];
  options.onProgress(1024, 1024);
  assert.match(h.element("loading-message").textContent, /下载完成/);
  h.ui.sceneReady(42);
  await settle();
  assert.equal(h.element("loading").hidden, true);
  assert.equal(h.element("canvas").dataset.loadMs, "0");
});

test("feature and download failures expose an accessible retry state", async () => {
  for (const options of [{ missing: ["WebGL 2"] }, { loadError: new Error("download failed") }]) {
    const h = harness(options);
    h.ui.start({});
    await settle();
    assert.equal(h.element("loading").hidden, false);
    assert.equal(h.element("loading").attributes["aria-busy"], "false");
    assert.equal(h.element("loading-message").attributes.role, "alert");
    assert.equal(h.element("retry").hidden, false);
    assert.equal(h.element("time-control").disabled, true);
    h.element("retry").handlers.click();
    assert.deepEqual(h.calls.at(-1), ["reload"]);
  }
});

test("navigation clock includes HTML/helper time and keeps the real two-frame gate", async () => {
  let time = 650;
  const frames = [];
  const h = harness({ clock: () => time, raf: fn => frames.push(fn) });
  h.ui.start({});
  await settle();
  assert.equal(h.element("canvas").dataset.loadStartedPageMs, "650");
  assert.equal(h.element("canvas").dataset.navigationReadyMs, undefined);
  time = 8900;
  h.ui.sceneReady(1700);
  assert.equal(h.element("loading").hidden, false);
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.equal(h.element("canvas").dataset.navigationReadyMs, undefined);
  assert.equal(h.element("loading").hidden, false);
  time = 9100;
  frames.shift()();
  assert.equal(h.element("canvas").dataset.loadMs, "8450");
  assert.equal(h.element("canvas").dataset.navigationReadyMs, "9100");
  assert.equal(h.element("loading").hidden, true);
});
