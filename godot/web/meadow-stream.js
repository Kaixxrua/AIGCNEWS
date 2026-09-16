/* Real post-presentation Godot pack loading. No alternative renderer or ready gate. */
(() => {
  "use strict";
  let active = null;
  const time = () => window.performance.now();
  const hex = bytes => Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, "0")).join("");
  function manifestOf(text) {
    const value = JSON.parse(text);
    if (value.version !== 1 || !Array.isArray(value.chunks) || !value.chunks.length || value.chunks.length > 32)
      throw new Error("无效的细节清单");
    const files = new Set();
    value.chunks.forEach((chunk, index) => {
      if (chunk.index !== index || !/^detail-\d+-[a-f0-9]{12}\.pck$/.test(chunk.file)
          || !/^[a-f0-9]{64}$/.test(chunk.sha256) || !Number.isSafeInteger(chunk.bytes)
          || chunk.bytes <= 0 || chunk.bytes > 32 * 1024 * 1024 || files.has(chunk.file))
        throw new Error("无效的细节文件");
      if (chunk.file !== `detail-${index}-${chunk.sha256.slice(0, 12)}.pck`)
        throw new Error("细节文件标识不一致");
      files.add(chunk.file);
    });
    return value;
  }
  async function download(state, chunk) {
    const abort = new AbortController();
    const timeout = window.setTimeout(() => abort.abort(), 90000);
    try {
      const response = await window.fetch(chunk.file, {signal: abort.signal, credentials: "same-origin"});
      if (!response.ok) throw new Error(`细节下载失败（${response.status}）`);
      const reader = response.body?.getReader();
      let bytes;
      if (reader) {
        const parts = []; let received = 0;
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          received += part.value.byteLength;
          if (received > chunk.bytes) { await reader.cancel(); throw new Error("细节文件大小不匹配"); }
          parts.push(part.value);
          state.ui?.loading((state.doneBytes + received) / state.totalBytes);
        }
        bytes = new Uint8Array(received); let offset = 0;
        for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
      } else {
        bytes = new Uint8Array(await response.arrayBuffer());
      }
      if (bytes.byteLength !== chunk.bytes || hex(await window.crypto.subtle.digest("SHA-256", bytes)) !== chunk.sha256)
        throw new Error("细节文件校验失败");
      return bytes;
    } finally { window.clearTimeout(timeout); }
  }
  async function run(state) {
    if (state !== active || state.running || !state.presented || !state.manifest || !state.callback) return;
    state.running = true;
    delete state.canvas.dataset.detailError;
    state.ui ??= window.meadowDetailStatus?.create(document.body);
    state.canvas.dataset.detailStatus = "loading";
    state.canvas.dataset.detailsStartedPageMs ??= String(Math.round(time()));
    try {
      while (state.index < state.manifest.chunks.length) {
        const chunk = state.manifest.chunks[state.index];
        state.ui?.loading(state.doneBytes / state.totalBytes);
        const bytes = await download(state, chunk);
        if (state !== active) return;
        const path = `/meadow-detail-${chunk.index}.pck`;
        state.engine.copyToFS(path, bytes.buffer);
        state.canvas.dataset.detailStatus = "applying";
        state.ui?.applying(state.index, state.manifest.chunks.length);
        await new Promise((resolve, reject) => {
          const timer = window.setTimeout(() => {
            state.pending = null;
            reject(new Error("场景细节接入超时"));
          }, 90000);
          state.pending = {index: state.index, resolve, reject, timer};
          try { state.callback(chunk.index, path); }
          catch (error) { window.clearTimeout(timer); state.pending = null; reject(error); }
        });
        state.doneBytes += chunk.bytes;
        state.index++;
        state.canvas.dataset.detailChunksApplied = String(state.index);
        // Yield to the actual game between chunks; no busy polling loop.
        await new Promise(resolve => window.requestAnimationFrame(resolve));
      }
      state.canvas.dataset.detailStatus = "complete";
      state.canvas.dataset.detailsCompletePageMs = String(Math.round(time()));
      state.ui?.complete();
      window.meadowLoader?.report(state.canvas);
    } catch (error) {
      state.canvas.dataset.detailStatus = "error";
      state.canvas.dataset.detailError = error?.message || String(error);
      state.ui?.fail(() => run(state));
      console.warn("MEADOW_DETAILS_INCOMPLETE", error?.message || String(error));
    } finally { state.running = false; }
  }
  window.meadowStream = {
    activate(engine, pack, canvas) {
      if (pack !== "index-lite.pck") return;
      active = {engine, canvas, index: 0, doneBytes: 0, totalBytes: 0,
        running: false, presented: false, manifest: null, callback: null, pending: null};
    },
    bind(text, callback) {
      if (!active || typeof callback !== "function") return;
      active.manifest = manifestOf(text);
      active.callback = callback;
      active.totalBytes = active.manifest.chunks.reduce((sum, chunk) => sum + chunk.bytes, 0);
      active.canvas.dataset.detailChunksTotal = String(active.manifest.chunks.length);
      active.canvas.dataset.detailStatus = "waiting-for-core";
    },
    corePresented() {
      if (!active || !active.manifest || active.presented) return;
      active.presented = true;
      active.canvas.dataset.coreReadyMs = active.canvas.dataset.navigationReadyMs;
      window.requestAnimationFrame(() => run(active));
    },
    applied(index, success, message) {
      const pending = active?.pending;
      if (!pending || pending.index !== index) return;
      window.clearTimeout(pending.timer);
      active.pending = null;
      if (success) pending.resolve();
      else pending.reject(new Error(message || "场景细节未能接入"));
    }
  };
})();
