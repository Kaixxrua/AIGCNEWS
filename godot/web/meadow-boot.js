/* Public Engine API only. Download/init the engine first, then overlap its
 * CPU bootstrap with the selected core transfer. No ready gate is changed. */
(() => {
  'use strict';
  let active;
  let started = false;
  const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
    n => n.toString(16).padStart(2, '0')).join('');
  window.meadowBoot = {
    async start(engine, config, options, canvas, mark) {
      const spec = config.bootstrap;
      const campWrapper = spec?.kind === 'camp-wrapper';
      const pinnedCamp = campWrapper && config.campPresentation === true
        && ['index.pck', 'index-balanced.pck', 'index-lite.pck'].includes(config.mainPack)
        && spec.selectedPack?.file === config.mainPack && spec.selectedPack?.bytes === config.fileSizes?.[config.mainPack]
        && Number.isSafeInteger(spec.selectedPack.bytes) && spec.selectedPack.bytes > 0
        && spec.selectedPack.sha256 === spec.coreSha256 && /^[a-f0-9]{64}$/.test(spec.sha256)
        && Number.isSafeInteger(spec.bytes) && spec.bytes > 0 && spec.bytes < 128 * 1024
        && spec.settingsVariant === (config.mainPack === 'index-lite.pck' ? 'lite' : 'full')
        && spec.file === `camp-bootstrap-${spec.settingsVariant}-${spec.sha256.slice(0, 12)}.pck`;
      if (!(pinnedCamp || (!campWrapper && config.mainPack === 'index-lite.pck' && spec?.file === 'bootstrap.pck'))
          || !/^[a-f0-9]{64}$/.test(spec?.coreSha256)) throw Error('无效的引擎启动配置');
      // The Godot bridge has no per-run token. A second engine needs a page
      // reload so callbacks from a timed-out engine cannot bind to a new run.
      if (started) throw Error('引擎已接入此页面，请刷新后重试');
      started = true;
      const state = {callback:null, closed:false, error:null}; active = state;
      canvas.dataset.engineBootstrap = spec.file;
      const bound = new Promise(resolve => {state.bound = resolve;});
      const abort = new AbortController();
      const deadline = performance.now() + 90000;
      const timeout = () => Error('场景启动超时（90秒），请刷新后重试');
      let rejectStopped;
      const stopped = new Promise((_resolve, reject) => {rejectStopped = reject;});
      // Cancellation can precede the next await, including inside a bridge
      // callback. Observe it immediately; every phase still races this promise.
      stopped.catch(() => {});
      const cancel = error => {
        if (state.closed) return;
        state.closed = true; state.error = error;
        rejectStopped(error);
        abort.abort();
      };
      state.isOpen = () => {
        // A busy event loop can deliver a promise before an overdue timer.
        if (!state.closed && performance.now() >= deadline) cancel(timeout());
        return !state.closed;
      };
      const check = () => {
        if (!state.isOpen()) throw state.error || Error('场景启动已结束');
      };
      const wait = async promise => {
        const value = await Promise.race([promise, stopped]);
        check();
        return value;
      };
      const timer = setTimeout(() => cancel(timeout()), 90000);
      try {
        // Give the smaller engine the bandwidth first. Its synchronous main()
        // setup can then run while the core travels, instead of blocking the
        // core's completed-download callback near the end of parallel fetches.
        canvas.dataset.downloadSchedule = 'engine-first';
        const bootDownload = campWrapper ? Promise.resolve().then(async () => {
          check();
          const response = await fetch(spec.file, {signal:abort.signal, credentials:'same-origin'});
          check();
          if (!response.ok) throw Error('启动文件下载失败');
          const bytes = await response.arrayBuffer(); check();
          if (bytes.byteLength !== spec.bytes || await digest(bytes) !== spec.sha256) throw Error('启动文件校验失败');
          check(); return bytes;
        }) : Promise.resolve().then(() => {check(); return engine.preloadFile(spec.file, spec.file);});
        const [, bootBytes] = await wait(Promise.all([
          Promise.resolve().then(() => {check(); return engine.init(config.executable);})
            .then(() => {check(); mark('engineInitMs');}),
          bootDownload
        ]));
        if (campWrapper) { check(); engine.copyToFS(spec.file, bootBytes); }
        // Do not use Engine.preloadFile(core) after starting that engine: use its
        // documented copyToFS method after the download has actually completed.
        check();
        const core = fetch(config.mainPack, {signal:abort.signal, credentials:'same-origin'}).then(async response => {
          check();
          if (!response.ok) throw Error(`场景下载失败（${response.status}）`);
          const bytes = await response.arrayBuffer();
          check();
          if (bytes.byteLength !== config.fileSizes[config.mainPack]) throw Error('场景文件校验失败');
          const actualSha = await digest(bytes);
          check();
          if (actualSha !== spec.coreSha256) throw Error('场景文件校验失败');
          mark('packFetchedMs');
          return bytes;
        });
        // A failed transfer must also release a still-pending engine.start().
        core.catch(cancel);
        check();
        if (config.progressive || !campWrapper) window.meadowStream.activate(engine, config.mainPack, canvas);
        check();
        mark('runtimeStartMs');
        check();
        await wait(engine.start({args:['--main-pack', spec.file, ...(config.args || [])]}));
        check();
        mark('bootstrapStartedMs');
        const [bytes] = await wait(Promise.all([core, bound]));
        check();
        options.onProgress?.(bytes.byteLength, bytes.byteLength);
        check();
        engine.copyToFS('/meadow-core.pck', bytes);
        check();
        await wait(new Promise((resolve, reject) => {
          state.resolve = resolve; state.reject = reject;
          state.callback('/meadow-core.pck');
        }));
        check();
        mark('engineStartedMs');
      } finally {
        state.closed = true;
        state.callback = state.bound = state.resolve = state.reject = null;
        if (active === state) active = null;
        clearTimeout(timer);
        abort.abort();
      }
    },
    bind(callback) {
      if (active?.isOpen() && active.bound && typeof callback === 'function') {
        active.callback = callback; active.bound(); active.bound = null;
      }
    },
    mounted(success, message) {
      if (!active?.isOpen() || !active.resolve) return;
      const {resolve, reject} = active;
      active.resolve = active.reject = null;
      if (success) resolve(); else reject(Error(message || '场景接入失败'));
    }
  };
})();
