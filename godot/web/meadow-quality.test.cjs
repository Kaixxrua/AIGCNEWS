const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "meadow-quality.js"), "utf8");
const loaderSource = fs.readFileSync(path.join(__dirname, "meadow-loader.js"), "utf8");
const shell = fs.readFileSync(path.join(__dirname, "meadow-shell.html"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));
const modes = ["lite", "balanced", "original"];
const catalog = {
  original: { pack: "index.pck", bytes: 200_000_000, gzipBytes: 160_000_000 },
  balanced: { pack: "index-balanced.pck", bytes: 140_000_000, gzipBytes: 117_000_000 },
  lite: { pack: "index-lite.pck", bytes: 30_000_000, gzipBytes: 20_000_000 }
};
const shared = {
  "index.wasm": { bytes: 40_000_000, gzipBytes: 15_000_000 },
  "index.js": { bytes: 2_000_000, gzipBytes: 1_000_000 },
  "meadow-controls.js": { bytes: 200_000, gzipBytes: 100_000 },
  "meadow-controls.css": { bytes: 100_000, gzipBytes: 50_000 }
};

function harness({ query = "", saved = null, storageBlocked = false, storageReadBlocked = false,
  storageWriteBlocked = false, choices = catalog, sharedFiles = shared, radioModes = modes,
  omittedIds = [], args = ["--test"], onStart = null } = {}) {
  const elements = new Map();
  let focused;
  function element(id) {
    if (!elements.has(id)) elements.set(id, { dataset: {}, handlers: {}, hidden: false, open: false,
      attributes: {}, disabled: false, textContent: "",
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); },
      fire(name, event = {}) { for (const fn of this.handlers[name] || []) fn(event); },
      showModal() { this.open = true; },
      close() { if (this.open) { this.open = false; this.fire("close"); } },
      focus() { focused = id; } });
    return elements.get(id);
  }
  const radios = radioModes.map(value => Object.assign(element(`radio-${value}`), { value, checked: value === "lite" }));
  const calls = [], navigations = [];
  const window = {
    location: { href: `http://127.0.0.1:4231/v114/index.html${query}`, assign: url => navigations.push(url) },
    localStorage: {
      getItem() { if (storageBlocked || storageReadBlocked) throw Error("blocked"); return saved; },
      setItem(_, value) { if (storageBlocked || storageWriteBlocked) throw Error("blocked"); saved = value; }
    },
    MEADOW_QUALITY: choices, MEADOW_QUALITY_SHARED: sharedFiles,
    meadowTimeUI: { start: config => { calls.push(config); if (onStart) onStart(config); } }
  };
  const document = { getElementById: id => omittedIds.includes(id) ? null : element(id), querySelectorAll: () => radios };
  vm.runInNewContext(source, { window, document, URL });
  const config = { executable: "index", mainPack: "index.pck", args,
    fileSizes: { "index.wasm": 40_000_000, "index.js": 2_000_000,
      ...Object.fromEntries(Object.values(catalog).map(choice => [choice.pack, choice.bytes])) } };
  window.meadowQuality.mount(config);
  return { calls, navigations, element, config, window, radios,
    focused: () => focused, saved: () => saved,
    selected: () => radios.find(r => r.checked)?.value,
    choose(value) {
      radios.forEach(r => { r.checked = r.value === value; });
      radios.find(r => r.checked)?.fire("change");
    } };
}

test("first visit recommends lite, but requires confirmation before any pack or engine starts", () => {
  const h = harness();
  assert.equal(h.calls.length, 0);
  assert.equal(h.selected(), "lite");
  assert.equal(h.focused(), "radio-lite");
  assert.equal(h.saved(), null);
  assert.equal(h.element("quality-dialog").open, true);
  assert.equal(h.element("loading-progress").hidden, true);
  assert.equal(h.element("loading").attributes["aria-busy"], "false");
  let prevented = false;
  h.element("quality-dialog").fire("cancel", { preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  h.element("quality-enter").fire("click");
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].mainPack, "index-lite.pck");
  assert.equal(h.saved(), "lite");
  assert.equal(h.element("loading-progress").hidden, false);
  assert.equal(h.element("loading").attributes["aria-busy"], "true");
});

for (const value of modes) {
  test(`${value}: explicit query wins over stored preference and starts only its own pack`, () => {
    const h = harness({ query: `?quality=${value}`, saved: modes.find(mode => mode !== value) });
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].mainPack, catalog[value].pack);
    assert.deepEqual(Object.keys(h.calls[0].fileSizes).filter(name => name.endsWith(".pck")), [catalog[value].pack]);
    assert.equal(h.calls[0].fileSizes[catalog[value].pack], catalog[value].bytes);
    assert.equal(h.calls[0].fileSizes["index.wasm"], shared["index.wasm"].bytes);
    assert.equal(h.element("canvas").dataset.textureQuality, value);
    h.element("quality-control").fire("click");
    h.element("quality-enter").fire("click");
    h.window.meadowQuality.mount(h.config);
    assert.equal(h.calls.length, 1);
    assert.equal(h.navigations.length, 0);
  });

  test(`${value}: valid stored preference still wins when query is unknown`, () => {
    const h = harness({ query: "?quality=unknown", saved: value });
    assert.equal(h.calls[0].mainPack, catalog[value].pack);
    assert.equal(h.element("quality-dialog").open, false);
  });
}

test("all quality switches navigate once, preserve URL state, and never start a second engine", () => {
  for (const from of modes) for (const to of modes.filter(mode => mode !== from)) {
    const h = harness({ query: "?rev=1&weather=night#scene", saved: from });
    h.element("quality-control").fire("click");
    assert.match(h.element("quality-notice").textContent, /重新载入/);
    h.choose(to);
    h.element("quality-enter").fire("click");
    h.element("quality-enter").fire("click");
    h.element("quality-control").fire("click");
    assert.equal(h.calls.length, 1);
    assert.equal(h.navigations.length, 1);
    const destination = new URL(h.navigations[0]);
    assert.equal(destination.searchParams.get("quality"), to);
    assert.equal(destination.searchParams.get("rev"), "1");
    assert.equal(destination.searchParams.get("weather"), "night");
    assert.equal(destination.hash, "#scene");
    assert.equal(h.saved(), to);
    assert.equal(h.element("quality-enter").disabled, true);
  }
});

test("cancel restores focus and reopening restores the active choice", () => {
  const h = harness({ saved: "original" });
  h.element("quality-control").fire("click");
  h.choose("lite");
  h.element("quality-cancel").fire("click");
  assert.equal(h.focused(), "quality-control");
  assert.equal(h.element("quality-dialog").open, false);
  assert.equal(h.saved(), "original");
  h.element("quality-control").fire("click");
  assert.equal(h.selected(), "original");
  let prevented = false;
  h.element("quality-dialog").fire("cancel", { preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.equal(h.calls.length, 1);
  assert.equal(h.navigations.length, 0);
});

test("invalid preference and unavailable storage do not block entry", () => {
  for (const options of [{ saved: "ultra", query: "?quality=invalid" }, { storageBlocked: true },
    { saved: "original", storageReadBlocked: true }, { storageWriteBlocked: true }]) {
    const h = harness(options);
    assert.equal(h.calls.length, 0);
    h.element("quality-enter").fire("click");
    assert.equal(h.calls[0].mainPack, "index-lite.pck");
  }
  const h = harness({ saved: "balanced", storageWriteBlocked: true });
  assert.equal(h.calls[0].mainPack, "index-balanced.pck");
  h.element("quality-control").fire("click");
  h.choose("lite"); h.element("quality-enter").fire("click");
  assert.equal(new URL(h.navigations[0]).searchParams.get("quality"), "lite");
  assert.equal(h.calls.length, 1);
});

test("missing lite is disabled and never fetched, including stale queries and preferences", () => {
  const choices = { original: catalog.original, balanced: catalog.balanced };
  for (const options of [{}, { query: "?quality=lite" }, { saved: "lite" }]) {
    const h = harness({ ...options, choices });
    assert.equal(h.calls.length, 0);
    assert.equal(h.selected(), "balanced");
    assert.equal(h.element("radio-lite").disabled, true);
    assert.equal(h.element("quality-recommended").hidden, true);
    assert.match(h.element("quality-lite-size").textContent, /暂未提供/);
    h.choose("lite"); h.element("quality-enter").fire("click");
    assert.equal(h.calls.length, 0);
    h.choose("balanced"); h.element("quality-enter").fire("click");
    assert.equal(h.calls[0].mainPack, "index-balanced.pck");
  }
  const h = harness({ choices, query: "?quality=lite", saved: "original" });
  assert.equal(h.calls[0].mainPack, "index.pck");
  h.element("quality-control").fire("click");
  h.choose("lite"); h.element("quality-enter").fire("click");
  assert.equal(h.navigations.length, 0);
});

test("missing catalog only permits the exported original pack; empty catalog permits none", () => {
  const h = harness({ choices: null });
  assert.equal(h.selected(), "original");
  assert.equal(h.element("radio-balanced").disabled, true);
  assert.equal(h.element("radio-lite").disabled, true);
  h.element("quality-enter").fire("click");
  assert.equal(h.calls[0].mainPack, "index.pck");
  for (const choices of [{}, { lite: { bytes: 10 }, original: { pack: "" }, ultra: catalog.lite }]) {
    const empty = harness({ choices, query: "?quality=lite" });
    assert.equal(empty.element("quality-enter").disabled, true);
    assert.equal(empty.focused(), "quality-dialog");
    assert.match(empty.element("quality-total-size").textContent, /暂无可用画质/);
    empty.element("quality-enter").fire("click");
    assert.equal(empty.calls.length, 0);
  }
});

test("download totals include exactly one shared engine, all shared UI files and the selected pack", () => {
  const h = harness();
  assert.match(h.element("quality-shared-size").textContent, /gzip 16\.1 MB · 未压缩 42\.3 MB/);
  for (const value of modes) {
    h.choose(value);
    const total = h.element("quality-total-size").textContent;
    const raw = ((catalog[value].bytes + 42_300_000) / 1_000_000).toFixed(1);
    const gzip = ((catalog[value].gzipBytes + 16_150_000) / 1_000_000).toFixed(1);
    assert.ok(total.includes(`gzip ${gzip} MB`), total);
    assert.ok(total.includes(`未压缩 ${raw} MB`), total);
    assert.match(h.element(`quality-${value}-size`).textContent, /素材包/);
  }
  assert.equal(h.calls.length, 0);
  assert.match(h.element("quality-balanced-size").textContent, /117\.0 MB/);
});

test("incomplete sizes never substitute raw bytes for gzip or claim a complete total", () => {
  const partial = { ...shared, "index.wasm": { bytes: 40_000_000, brBytes: 10_000_000 } };
  const h = harness({ sharedFiles: partial });
  assert.doesNotMatch(h.element("quality-total-size").textContent, /gzip|Brotli/);
  assert.match(h.element("quality-total-size").textContent, /未压缩 72\.3 MB/);
  for (const sharedFiles of [{ "index.js": shared["index.js"] }, { "index.wasm": shared["index.wasm"] },
    { ...shared, "index.wasm": { bytes: -1, gzipBytes: NaN } }]) {
    const incomplete = harness({ sharedFiles });
    assert.match(incomplete.element("quality-total-size").textContent, /大小待生成/);
    assert.doesNotMatch(incomplete.element("quality-total-size").textContent, /\d+\.\d+ MB/);
  }
});

test("quality argument is documented, replaces stale values, preserves other args and does not resize canvas", () => {
  for (const args of [["--test"], ["--test", "--", "--seed=3", "--meadow-quality=original"]]) {
    const before = [...args];
    const h = harness({ args, saved: "lite" });
    const actual = Array.from(h.calls[0].args);
    assert.deepEqual(args, before);
    assert.equal(actual.filter(arg => arg === "--").length, 1);
    assert.deepEqual(actual.filter(arg => arg.startsWith("--meadow-quality=")), ["--meadow-quality=lite"]);
    assert.ok(actual.indexOf("--meadow-quality=lite") > actual.indexOf("--"));
    assert.ok(actual.includes("--test"));
    if (args.includes("--seed=3")) assert.ok(actual.includes("--seed=3"));
    assert.equal(h.element("canvas").width, undefined);
    assert.equal(h.element("canvas").height, undefined);
    assert.equal(Object.keys(h.config.fileSizes).filter(name => name.endsWith(".pck")).length, 3);
  }
  assert.match(source, /OS\.get_cmdline_user_args\(\)/);
});

test("legacy two-option quality shells remain usable without the new summary nodes", () => {
  const h = harness({ radioModes: ["original", "balanced"],
    omittedIds: ["quality-recommended", "quality-total-size", "quality-shared-size"] });
  assert.equal(h.calls.length, 0);
  assert.equal(h.selected(), "balanced");
  h.choose("original"); h.element("quality-enter").fire("click");
  assert.equal(h.calls[0].mainPack, "index.pck");
});

test("progressive lite discloses later detail downloads and still starts only the chosen core", () => {
  const choices = structuredClone(catalog);
  choices.lite.details = {bytes: 18_000_000, gzipBytes: 17_000_000};
  const h = harness({choices});
  assert.equal(h.calls.length, 0);
  assert.match(h.element('quality-lite-size').textContent, /后续细节/);
  assert.match(h.element('quality-total-size').textContent, /首屏/);
  h.element('quality-enter').fire('click');
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].progressive, true);
  assert.deepEqual(Object.keys(h.calls[0].fileSizes).filter(name => name.endsWith('.pck')), ['index-lite.pck']);
  const original = harness({choices, query:'?quality=original'});
  assert.equal(original.calls[0].progressive, undefined);
});

test("shell names all three tiers accurately with accessible labels and no pack or WASM preloads", () => {
  assert.match(shell, /<strong>极速 /);
  assert.match(shell, /<strong>均衡<\/strong>/);
  assert.match(shell, /<strong>原画<\/strong>/);
  assert.doesNotMatch(shell, /快速加载|两档|秒内|即刻/);
  assert.match(shell, /完整场景，降低渲染分辨率与素材细节/);
  assert.match(shell, /value="lite" checked/);
  for (const value of modes) {
    assert.match(shell, new RegExp(`value="${value}"[^>]+aria-describedby="quality-${value}-description quality-${value}-size"`));
  }
  assert.match(shell, /id="quality-total-size" role="status" aria-live="polite" aria-atomic="true"/);
  assert.doesNotMatch(shell, /(?:src|href)="[^"$]*\.(?:pck|wasm)|rel="(?:preload|prefetch)"/);
});

test("engine initialization and chosen pack fetch remain parallel; both must finish before start", async () => {
  const events = [];
  let finishInit, finishPack;
  class Engine {
    constructor(config) { this.config = config; }
    init(executable) { events.push(["init", executable]); return new Promise(resolve => { finishInit = resolve; }); }
    preloadFile(url, destination) { events.push(["pack", url, destination]); return new Promise(resolve => { finishPack = resolve; }); }
    start(config) { events.push(["start", ...config.args]); return Promise.resolve(); }
  }
  const window = { performance: { now: () => 100 } };
  vm.runInNewContext(loaderSource, { window, Engine });
  const canvas = { dataset: {} };
  const pending = window.meadowLoader.start({ executable: "index", mainPack: "index-balanced.pck", args: ["--foo"] }, {}, canvas);
  assert.deepEqual(events, [["init", "index"], ["pack", "index-balanced.pck", "index-balanced.pck"]]);
  finishPack(); await settle();
  assert.equal(events.length, 2);
  finishInit(); await pending;
  assert.deepEqual(events[2], ["start", "--main-pack", "index-balanced.pck", "--foo"]);
  assert.equal(canvas.dataset.engineStartedMs, "0");
});

test("all three choices reach the real loader with one engine and one chosen pack after confirmation", async () => {
  for (const value of modes) {
    const events = [];
    let pending;
    class Engine {
      constructor(config) { events.push(["engine", config.mainPack]); }
      init(executable) { events.push(["init", executable]); return Promise.resolve(); }
      preloadFile(url, destination) { events.push(["pack", url, destination]); return Promise.resolve(); }
      start(config) { events.push(["start", ...config.args]); return Promise.resolve(); }
    }
    const window = { performance: { now: () => 100 } };
    vm.runInNewContext(loaderSource, { window, Engine });
    const h = harness({ onStart: config => { pending = window.meadowLoader.start(config, {}, { dataset: {} }); } });
    assert.deepEqual(events, []);
    h.choose(value);
    assert.deepEqual(events, []);
    h.element("quality-enter").fire("click");
    h.element("quality-enter").fire("click");
    await pending;
    assert.deepEqual(events, [["engine", catalog[value].pack], ["init", "index"],
      ["pack", catalog[value].pack, catalog[value].pack],
      ["start", "--main-pack", catalog[value].pack, "--test", "--", `--meadow-quality=${value}`]]);
    h.element("quality-control").fire("click");
    h.choose(modes.find(mode => mode !== value)); h.element("quality-enter").fire("click");
    assert.equal(events.length, 4);
    assert.equal(h.navigations.length, 1);
  }
});
