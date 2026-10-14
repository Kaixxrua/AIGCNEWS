"use strict";
// Functional callbacks use Node's real EventTarget dispatch, with a minimal DOM.
// Browser/native keyboard defaults, screen readers and responsive pixels are NOT
// asserted by this offline suite; main owns browser integration/visual acceptance.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "meadow-progressive.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "meadow-progressive.css"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

class Element extends EventTarget {
  constructor(name, document) {
    super(); this.tagName = name.toUpperCase(); this.nodeType = 1; this.ownerDocument = document;
    this.dataset = {}; this.attributes = new Map(); this.children = []; this.parentNode = null;
    this.hidden = false; this.disabled = false; this.textWrites = 0; this._text = ""; this.handlers = new Map();
  }
  set textContent(value) { this.textWrites++; this._text = String(value); }
  get textContent() { return this._text; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...children) { for (const child of children) { this.children.push(child); child.parentNode = this; } }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); this.parentNode = null; }
  addEventListener(name, callback, options) {
    super.addEventListener(name, callback, options);
    if (!this.handlers.has(name)) this.handlers.set(name, new Set());
    this.handlers.get(name).add(callback);
  }
  removeEventListener(name, callback, options) { super.removeEventListener(name, callback, options); this.handlers.get(name)?.delete(callback); }
  click() { if (!this.disabled && !this.hidden) this.dispatchEvent(new Event("click")); }
  focus() { throw Error("Status UI must not steal focus"); }
}

function harness() {
  const document = { createElement: name => new Element(name, document) };
  document.body = document.createElement("body");
  const canvas = document.createElement("canvas"), loader = document.createElement("section");
  canvas.dataset.loadMs = "14000"; loader.hidden = false;
  document.body.append(canvas, loader);
  const noRequest = () => { throw Error("No transport, engine, timer or readiness work belongs here"); };
  const window = { document, fetch: noRequest, setTimeout: noRequest, requestAnimationFrame: noRequest };
  vm.runInNewContext(source, { window, fetch: noRequest, XMLHttpRequest: noRequest, WebSocket: noRequest,
    setTimeout: noRequest, requestAnimationFrame: noRequest, Engine: noRequest });
  const ui = window.meadowDetailStatus.create();
  const [message, count, progress, button] = ui.element.children;
  return { document, window, canvas, loader, ui, message, count, progress, button,
    phase: () => ui.element.dataset.detailPhase,
    bypassDisabledClick: () => button.dispatchEvent(new Event("click")) };
}

test("starts hidden/idle, owns only its element and exposes no ready/transport API", () => {
  const h = harness();
  assert.equal(h.phase(), "idle"); assert.equal(h.ui.element.hidden, true);
  assert.equal(h.canvas.dataset.loadMs, "14000"); assert.equal(h.loader.hidden, false);
  assert.equal(h.document.body.children.length, 3);
  assert.deepEqual(Object.keys(h.ui).sort(), ["applying", "complete", "destroy", "element", "fail", "loading"]);
  assert.doesNotMatch(source, /(?:\bfetch\s*\(|new\s+(?:XMLHttpRequest|WebSocket|Engine)\b|requestAnimationFrame\s*\(|setTimeout\s*\(|\.focus\s*\(|\.loadMs\s*=)/);
});

test("polite status and native retry button; no custom keyboard/double-dispatch handlers", () => {
  const h = harness(); h.ui.fail(() => {});
  assert.equal(h.message.getAttribute("role"), "status");
  assert.equal(h.message.getAttribute("aria-live"), "polite");
  assert.equal(h.message.getAttribute("aria-atomic"), "true");
  assert.equal(h.button.tagName, "BUTTON"); assert.equal(h.button.type, "button");
  assert.equal(h.button.getAttribute("aria-label"), "重试加载场景细节");
  assert.equal(h.button.getAttribute("tabindex"), null);
  assert.deepEqual([...h.button.handlers.keys()], ["click"]);
  assert.equal(h.ui.element.getAttribute("aria-modal"), null);
  assert.equal(h.ui.element.getAttribute("tabindex"), null);
});

test("loading progress is truthful, unknown is text-only and live text does not repeat per byte", () => {
  const h = harness(); h.ui.loading();
  assert.equal(h.message.textContent, "场景细节加载中…"); assert.equal(h.progress.hidden, true);
  const writes = h.message.textWrites;
  for (const loaded of [0, 1, 27, 100]) h.ui.loading({ loaded, total: 100 });
  assert.equal(h.message.textWrites, writes); assert.equal(h.count.textContent, "100%");
  assert.equal(h.progress.value, 1); assert.equal(h.phase(), "loading");
  assert.equal(h.ui.element.dataset.detailLoaded, "100");
  h.ui.loading(0.37);
  assert.equal(h.count.textContent, "37%"); assert.equal(h.ui.element.dataset.detailTotal, undefined);
  h.ui.loading();
  assert.equal(h.progress.hidden, true); assert.equal(h.ui.element.dataset.detailProgress, undefined);
});

test("malformed/overrun totals are not clamped into invented completion", () => {
  const h = harness();
  for (const value of [NaN, Infinity, -1, 1.01, "1", null, true, { loaded: 2, total: 1 },
    { loaded: 0, total: 0 }, { loaded: -1, total: 100 }, { loaded: 1, total: Infinity },
    { loaded: 1.5, total: 2 }, { loaded: Number.MAX_SAFE_INTEGER + 1, total: Number.MAX_SAFE_INTEGER + 1 }]) {
    h.ui.loading(value); assert.equal(h.phase(), "loading"); assert.equal(h.progress.hidden, true);
    assert.equal(h.ui.element.dataset.detailProgress, undefined); assert.equal(h.count.textContent, "");
  }
});

test("applying counts remain separate from download and never auto-complete, including zero work", () => {
  const h = harness(); h.ui.loading({ loaded: 20, total: 40 }); h.ui.applying(1, 3);
  assert.equal(h.message.textContent, "正在应用场景细节…"); assert.equal(h.count.textContent, "1 / 3");
  assert.equal(h.ui.element.dataset.detailLoaded, undefined); assert.equal(h.ui.element.dataset.detailDone, "1");
  assert.equal(h.progress.getAttribute("aria-label"), "场景细节应用进度");
  h.ui.applying(3, 3); assert.equal(h.phase(), "applying"); assert.equal(h.progress.value, 1);
  h.ui.applying(0, 0); assert.equal(h.phase(), "applying"); assert.equal(h.progress.hidden, true); assert.equal(h.count.textContent, "0 / 0");
  for (const pair of [[4, 3], [-1, 2], [1.5, 2], [1, NaN], ["1", 3]]) {
    h.ui.applying(...pair); assert.equal(h.progress.hidden, true); assert.equal(h.ui.element.dataset.detailDone, undefined);
  }
});

test("complete is explicit, terminal, retained for truthful announcement and ignores all stale updates", () => {
  const h = harness(); h.ui.applying(4, 4); assert.equal(h.ui.complete(), true);
  assert.equal(h.phase(), "complete"); assert.equal(h.message.textContent, "场景细节已加载");
  assert.equal(h.progress.hidden, true); assert.equal(h.button.hidden, true); assert.equal(h.ui.element.hidden, false);
  const previous = JSON.stringify(h.ui.element.dataset);
  assert.equal(h.ui.loading({ get loaded() { throw Error("Stale input inspected"); } }), false);
  assert.equal(h.ui.applying(0, 10), false); assert.equal(h.ui.fail(() => { throw Error("Stale retry"); }), false);
  assert.equal(h.ui.complete(), false); h.bypassDisabledClick(); assert.equal(JSON.stringify(h.ui.element.dataset), previous);
});

test("failure without a callable retry does not expose a fake recovery action", () => {
  const h = harness();
  for (const callback of [undefined, null, "reload", {}]) {
    h.ui.fail(callback); assert.equal(h.phase(), "error"); assert.equal(h.button.hidden, true);
    assert.equal(h.message.textContent, "场景细节加载失败"); h.bypassDisabledClick();
    assert.equal(h.ui.element.dataset.detailRetryCount, "0");
  }
  h.ui.loading(0.1); assert.equal(h.phase(), "loading");
});

test("actual click dispatch retries once with zero arguments and no internal receiver", async () => {
  const h = harness(), pending = deferred(); let calls = 0;
  h.ui.fail(function (...args) { calls++; assert.equal(this, undefined); assert.equal(args.length, 0); return pending.promise; });
  h.button.click(); h.button.click(); h.bypassDisabledClick();
  assert.equal(h.phase(), "retrying"); assert.equal(h.button.disabled, true);
  await settle(); assert.equal(calls, 1); assert.equal(h.ui.element.dataset.detailRetryCount, "1");
  pending.resolve(); await settle();
  assert.equal(h.phase(), "retrying"); assert.equal(h.ui.element.dataset.detailRetryPending, "false");
  assert.equal(h.button.disabled, true); // Result is NOT a detail-complete signal.
  h.ui.loading(0.4); h.ui.applying(2, 2); assert.equal(h.phase(), "applying"); h.ui.complete();
  assert.equal(h.phase(), "complete");
});

test("reentrant fail/click inside an outstanding retry cannot overlap another attempt", async () => {
  const h = harness(), pending = deferred(); let calls = 0;
  const callback = () => { calls++; h.ui.fail(callback); h.bypassDisabledClick(); return pending.promise; };
  h.ui.fail(callback); h.button.click(); await settle();
  assert.equal(calls, 1); assert.equal(h.phase(), "error"); assert.equal(h.button.disabled, true);
  pending.resolve(); await settle(); assert.equal(h.button.disabled, false);
  h.button.click(); await settle(); assert.equal(calls, 2);
});

test("sync throws, rejected promises and throwing thenables restore retry without unhandled errors", async () => {
  for (const failure of [() => { throw Error("sync"); }, () => Promise.reject(Error("async")),
    () => ({ get then() { throw Error("then getter"); } })]) {
    const h = harness(); let calls = 0;
    h.ui.fail(() => { calls++; h.ui.loading(0.2); return failure(); });
    h.button.click(); h.bypassDisabledClick(); await settle();
    assert.equal(calls, 1); assert.equal(h.phase(), "error"); assert.equal(h.button.disabled, false);
    assert.equal(h.ui.element.dataset.detailRetryPending, "false");
  }
});

test("a newer explicit failure keeps its replacement callback after an old promise rejects", async () => {
  const h = harness(), pending = deferred(); let oldCalls = 0, newCalls = 0;
  h.ui.fail(() => { oldCalls++; return pending.promise; }); h.button.click(); await settle();
  h.ui.fail(() => { newCalls++; }); h.bypassDisabledClick(); assert.equal(newCalls, 0);
  pending.reject(Error("stale")); await settle(); assert.equal(h.phase(), "error");
  h.button.click(); await settle(); assert.equal(oldCalls, 1); assert.equal(newCalls, 1);
});

test("late rejection after explicit complete cannot restore errors or retry controls", async () => {
  const h = harness(), pending = deferred();
  h.ui.fail(() => pending.promise); h.button.click(); await settle(); h.ui.complete();
  const previous = JSON.stringify(h.ui.element.dataset); pending.reject(Error("late")); await settle();
  assert.equal(h.phase(), "complete"); assert.equal(JSON.stringify(h.ui.element.dataset), previous);
  assert.equal(h.button.hidden, true);
});

test("destroy is idempotent, removes its event listener and suppresses pending callback/updates", async () => {
  const h = harness(); let calls = 0;
  h.ui.fail(() => { calls++; }); h.button.click(); assert.equal(h.ui.destroy(), true); await settle();
  assert.equal(calls, 0); assert.equal(h.ui.element.parentNode, null); assert.equal(h.phase(), "destroyed");
  assert.equal(h.button.handlers.get("click").size, 0); h.bypassDisabledClick();
  assert.equal(h.ui.destroy(), false); assert.equal(h.ui.loading(), false); assert.equal(h.ui.complete(), false);
  assert.equal(h.document.body.children.length, 2); assert.equal(h.loader.hidden, false);
});

test("destroy after callback entry ignores its later rejection", async () => {
  const h = harness(), pending = deferred();
  h.ui.fail(() => pending.promise); h.button.click(); await settle(); h.ui.destroy();
  pending.reject(Error("removed")); await settle(); assert.equal(h.phase(), "destroyed"); assert.equal(h.ui.element.parentNode, null);
});

test("multiple instances and custom containers are independent; invalid containers are rejected", () => {
  const h = harness(), container = h.document.createElement("aside"); h.document.body.append(container);
  const second = h.window.meadowDetailStatus.create(container); second.loading(0.2); h.ui.complete();
  assert.equal(second.element.dataset.detailPhase, "loading"); assert.equal(second.element.parentNode, container);
  second.destroy(); assert.equal(container.children.length, 0); assert.equal(h.phase(), "complete");
  for (const invalid of [null, {}, { nodeType: 3 }, "body"]) assert.throws(() => h.window.meadowDetailStatus.create(invalid), { name: "TypeError" });
});

test("isolated static styling leaves scene input available and provides native-button focus/contrast tokens", () => {
  assert.match(css, /max-inline-size:\s*calc\(100vw - 2rem\)/); assert.match(css, /flex-wrap:\s*wrap/);
  assert.match(css, /pointer-events:\s*none/); assert.match(css, /__retry\s*\{[^}]*pointer-events:\s*auto/s);
  assert.match(css, /min-block-size:\s*2\.75rem/); assert.match(css, /__retry:focus-visible/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/); assert.match(css, /forced-colors:\s*active/);
  assert.doesNotMatch(css, /(?:#canvas|#loading|#quality|backdrop-filter|@keyframes)/);
  for (const match of css.matchAll(/(?:animation|transition):([^;]+);/g)) {
    assert.match(match[1].trim(), /^none(?:\s*!important)?$/);
  }
});
