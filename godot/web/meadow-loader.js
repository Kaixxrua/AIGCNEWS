/* Public Godot loading API, with separate transfer/runtime/presentation clocks.
 * No render settings, game state, asset quality, or readiness gates are changed.
 */
(() => {
  "use strict";
  const now = () => window.performance?.now?.() ?? 0;
  window.meadowLoader = {
    async start(config, options, canvas) {
      let disposeCompile = () => {};
      try {
        if (config.progressive && (!window.meadowStream || !window.meadowDetailStatus))
          throw new Error("分批加载组件下载失败，请刷新重试。");
        window.meadowStartupTrace?.install(canvas);
        const executable = config.executable;
        const pack = config.mainPack || `${executable}.pck`;
        if (window.meadowWebglCompile) {
          const requestedMode = new URLSearchParams(window.location.search).get("fast_compile");
          const selectedContract = requestedMode === null || requestedMode === "scene"
            ? window.MEADOW_RENDER_CONTRACTS?.[pack] : undefined;
          // Only native-verified, byte-pinned lite builds opt in automatically.
          // fast_compile=0 keeps a stock-driver diagnostic path available.
          const mode = requestedMode === null ? (selectedContract ? "scene" : "0") : requestedMode;
          if (mode === "1" || mode === "scene") {
            const contract = mode === "scene" ? selectedContract : undefined;
            // Candidates07/15 were independently checked through core, all
            // twelve detail chunks, day/night and transitions: no Spot/Area.
            // This narrow light contract does not assert bit-identical scene
            // serialization; candidate15's numeric differences remain recorded.
            // Do not extend the directional-base compiler path to future packs
            // merely because they reuse the lite filename or this loader.
            const sceneDirectionalBase = config.progressive === true &&
              ["78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5",
               "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c"].includes(contract?.packSha256);
            disposeCompile = window.meadowWebglCompile.install(canvas, {contract, sceneDirectionalBase});
          }
        }
        const started = now();
        const engine = new Engine({ ...config, ...options,
          ...(config.bootstrap ? {onProgress: () => {}} : {}) });
        if (config.campPresentation) window.meadowCampIntegration?.attachEngine(engine, config, canvas);
        const mark = name => {
          canvas.dataset[name] = String(Math.round(now() - started));
          window.meadowStartupTrace?.mark(name);
        };
        if (config.bootstrap) {
          if ((!config.progressive && !config.campPresentation) || !window.meadowBoot) throw Error("分批启动组件缺失，请刷新重试。");
          options.onProgress?.(0, 0);
          await window.meadowBoot.start(engine, config, options, canvas, mark);
          return;
        }
        // These are the same two concurrent operations used by Engine.startGame.
        // Do not serialize WASM initialization behind the much larger pack fetch.
        await Promise.all([
          engine.init(executable).then(() => mark("engineInitMs")),
          engine.preloadFile(pack, pack).then(() => mark("packFetchedMs"))
        ]);
        window.meadowStartupTrace?.instrumentEngine(engine);
        window.meadowStream?.activate(engine, pack, canvas);
        mark("runtimeStartMs");
        await engine.start({ args: ["--main-pack", pack, ...(config.args || [])] });
        mark("engineStartedMs");
      } catch (error) {
        try { disposeCompile(); } catch (_) { /* Keep the original startup error. */ }
        throw error;
      }
    },
    observeVisibility(canvas) {
      let hiddenAt = document.visibilityState === "hidden" ? now() : null;
      let hiddenMs = 0;
      const changed = () => {
        if (document.visibilityState === "hidden") {
          if (hiddenAt === null) hiddenAt = now();
        } else if (hiddenAt !== null) {
          hiddenMs += now() - hiddenAt;
          hiddenAt = null;
        }
      };
      document.addEventListener("visibilitychange", changed);
      return () => {
        if (hiddenAt !== null) hiddenMs += now() - hiddenAt;
        canvas.dataset.loadHiddenMs = String(Math.round(hiddenMs));
        document.removeEventListener("visibilitychange", changed);
      };
    },
    report(canvas) {
      const resources = window.performance?.getEntriesByType?.("resource") || [];
      const payload = resources.filter(r => /\.(?:wasm|pck)(?:\?|$)/.test(r.name)).map(r => ({
        // Relative filenames only: no user/account data or third-party telemetry.
        file: new URL(r.name).pathname.split("/").pop(),
        startMs: Math.round(r.startTime),
        responseStartMs: Math.round(r.responseStart),
        responseEndMs: Math.round(r.responseEnd),
        durationMs: Math.round(r.duration),
        transferBytes: r.transferSize,
        encodedBodyBytes: r.encodedBodySize,
        decodedBodyBytes: r.decodedBodySize
      }));
      canvas.dataset.resourceTiming = JSON.stringify(payload);
      const fields = ["loadMs", "navigationReadyMs", "loadStartedPageMs", "downloadMs", "sceneBuildMs", "sceneSignalMs", "engineInitMs",
        "packFetchedMs", "runtimeStartMs", "engineStartedMs", "loadHiddenMs"];
      const result = Object.fromEntries(fields.map(key => [key, Number(canvas.dataset[key] || 0)]));
      result.resources = payload;
      result.note = "Elapsed milestones overlap; downloadMs is a progress callback, not network-only time. First presentation waits for scene-ready and two RAF boundaries. Hidden-tab runs are not foreground benchmarks.";
      console.info("MEADOW_WEB_READY", JSON.stringify(result));
      return result;
    }
  };
})();
