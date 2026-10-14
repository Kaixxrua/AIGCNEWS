/* Opt-in, local-only startup timing. No rendering inputs or GL results change. */
(() => {
  "use strict";
  if (new URLSearchParams(window.location.search).get("startup_trace") !== "1") return;
  const clock = () => performance.now();
  const origin = clock();
  const totals = {};
  const slow = [];
  const marks = [];
  const restore = [];
  const programs = new WeakMap();
  const sources = new WeakMap();
  const attached = new WeakMap();
  let nextProgram = 0;
  let canvas;
  let stopped = false;
  let renderer = null;
  let observer;
  const longTasks = [];
  const elapsed = () => Math.round((clock() - origin) * 10) / 10;
  function publish() {
    if (!canvas) return;
    canvas.dataset.startupTrace = JSON.stringify({
      status: stopped ? "completed" : "running", elapsedMs: elapsed(), renderer,
      canvas: [canvas.width, canvas.height], dpr: window.devicePixelRatio,
      visibility: document.visibilityState, focused: document.hasFocus(),
      marks, totals: Object.fromEntries(Object.entries(totals).map(([name, row]) =>
        [name, {...row, ms: Math.round(row.ms*10)/10}])), slow, longTasks
    });
  }
  function wrap(proto, name) {
    const original = proto[name];
    if (typeof original !== "function") return;
    function measured(...args) {
      if (this.canvas !== canvas || stopped) return Reflect.apply(original, this, args);
      if (name === "shaderSource") {
        const source = String(args[1]);
        const tags = ["contact_shadows", "cloud_centres", "grove_root_v", "architecture_fog_density",
          "architecture_ab", "sunbreak_transmission", "bed_depth", "lit_windows", "canopy_lobes",
          "scene_exposure", "wing_phase", "meadow_mineral", "moon_direction"]
          .filter(tag => source.includes(tag));
        let hash = 2166136261;
        for (let i=0; i<source.length; i++) hash = Math.imul(hash ^ source.charCodeAt(i), 16777619);
        sources.set(args[0], {bytes: source.length, tags, hash: (hash>>>0).toString(16),
          defines: (source.match(/^#define (?:BASE_PASS[^\n]*|USE_ADDITIVE_LIGHTING[^\n]*|ADDITIVE_OMNI[^\n]*|ADDITIVE_SPOT[^\n]*|USE_VERTEX_LIGHTING[^\n]*|MODE_[^\n]+|DISABLE_[^\n]+|MAX_FORWARD_LIGHTS[^\n]+|MAX_LIGHT_DATA_STRUCTS[^\n]+)/gm) || []).slice(0, 24)});
      } else if (name === "attachShader") {
        const entries = attached.get(args[0]) || [];
        entries.push(sources.get(args[1]));
        attached.set(args[0], entries);
      }
      const start = clock();
      try {
        return Reflect.apply(original, this, args);
      } finally {
        const duration = clock() - start;
        const row = totals[name] || (totals[name] = {calls: 0, ms: 0, maxMs: 0});
        row.calls++;
        row.ms += duration;
        row.maxMs = Math.max(row.maxMs, Math.round(duration * 10) / 10);
        if (duration >= 20 && slow.length < 200) {
          let program;
          if (["linkProgram", "getProgramParameter", "useProgram", "getUniformLocation"].includes(name)) {
            if (args[0] && !programs.has(args[0])) programs.set(args[0], ++nextProgram);
            program = programs.get(args[0]);
          }
          slow.push({name, startMs: Math.round((start-origin)*10)/10,
            ms: Math.round(duration*10)/10, program,
            parameter: name === "getProgramParameter" ? args[1] : undefined,
            sources: program ? attached.get(args[0]) : undefined,
            sceneReady: !!canvas.dataset.sceneSignalMs});
          publish();
        }
      }
    }
    proto[name] = measured;
    restore.push(() => { if (proto[name] === measured) proto[name] = original; });
  }
  window.meadowStartupTrace = {
    install(target) {
      if (canvas) return;
      canvas = target;
      const prototype = window.WebGL2RenderingContext?.prototype;
      if (prototype) {
        for (const name of ["shaderSource", "attachShader", "compileShader", "linkProgram", "getProgramParameter",
          "getShaderParameter", "getUniformLocation", "getActiveUniform", "getUniformBlockIndex",
          "bufferData", "bufferSubData", "texImage2D", "texImage3D", "texSubImage2D",
          "texStorage2D", "compressedTexImage2D", "generateMipmap", "getParameter",
          "drawElements", "drawArrays", "drawElementsInstanced", "drawArraysInstanced",
          "useProgram", "finish", "readPixels", "blitFramebuffer", "checkFramebufferStatus"])
          wrap(prototype, name);
      }
      const original = HTMLCanvasElement.prototype.getContext;
      function context(...args) {
        const result = Reflect.apply(original, this, args);
        if (this === canvas && args[0] === "webgl2" && result && renderer === null) {
          try {
            const extension = result.getExtension("WEBGL_debug_renderer_info");
            renderer = { vendor: result.getParameter(extension?.UNMASKED_VENDOR_WEBGL || result.VENDOR),
              device: result.getParameter(extension?.UNMASKED_RENDERER_WEBGL || result.RENDERER) };
          } catch (_) { renderer = {unavailable: true}; }
        }
        return result;
      }
      HTMLCanvasElement.prototype.getContext = context;
      restore.push(() => { if (HTMLCanvasElement.prototype.getContext === context)
        HTMLCanvasElement.prototype.getContext = original; });
      if (typeof PerformanceObserver === "function") {
        try {
          observer = new PerformanceObserver(list => {
            for (const item of list.getEntries()) if (longTasks.length < 80)
              longTasks.push({startMs: Math.round(item.startTime-origin), ms: Math.round(item.duration)});
            publish();
          });
          observer.observe({type: "longtask", buffered: true});
        } catch (_) { /* Unsupported observer is not an engine failure. */ }
      }
      this.mark("trace-installed");
    },
    mark(name) { marks.push({name, ms: elapsed()}); publish(); },
    instrumentEngine(engine) {
      // Diagnostic-only, pinned to the shipped Godot 4.7.2 wrapper. These are
      // not stable public Engine API; normal startup never depends on them.
      const runtime = engine.rtenv;
      for (const name of ["initConfig", "copyToFS", "callMain"]) {
        if (typeof runtime?.[name] !== "function") continue;
        const original = runtime[name];
        const trace = this;
        function measured(...args) {
          trace.mark(`${name}:enter`);
          try { return Reflect.apply(original, this, args); }
          finally { trace.mark(`${name}:return`); }
        }
        runtime[name] = measured;
        restore.push(() => { if (runtime[name] === measured) runtime[name] = original; });
      }
    },
    finish(outcome = "presentation") {
      if (stopped) return;
      marks.push({name: outcome, ms: elapsed()});
      stopped = true;
      for (const undo of restore.reverse()) undo();
      observer?.disconnect();
      publish();
    }
  };
})();
