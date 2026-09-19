/* Runs only inside the Godot iframe, before Engine captures fetch. */
(() => {
  'use strict';
  const config = window.MEADOW_DELIVERY;
  if (!config) return;
  const originalFetch = window.fetch.bind(window);
  const cacheName = 'meadow-verified-assets-v1';
  const pending = new Map();
  const hex = bytes => Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, '0')).join('');
  const notify = (file, loaded, total, source) => window.dispatchEvent(new CustomEvent('meadow-download', {
    detail: {file, loaded, total, source}
  }));
  const validate = async (bytes, spec) => {
    if (bytes.byteLength !== spec.bytes || hex(await crypto.subtle.digest('SHA-256', bytes)) !== spec.sha256)
      throw Error('场景资源校验失败');
  };
  const responseFor = (bytes, file) => new Response(bytes, {headers: {
    'Content-Type': file.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream',
    'Content-Length': String(bytes.byteLength)
  }});

  async function download(file, spec, signal) {
    const key = new URL(file, location.href);
    key.search = '?v=' + spec.sha256;
    let cache;
    try { cache = await caches.open(cacheName); } catch { /* Storage is optional. */ }
    signal?.throwIfAborted();
    let cached;
    try { cached = await cache?.match(key.href); } catch { cache = undefined; }
    if (cached) {
      const bytes = await cached.arrayBuffer();
      try {
        await validate(bytes, spec);
        signal?.throwIfAborted();
        notify(file, spec.bytes, spec.bytes, 'cache');
        return bytes;
      } catch (error) {
        signal?.throwIfAborted();
        try { await cache.delete(key.href); } catch { cache = undefined; }
      }
    }
    const cdn = new URL(file, config.cdn);
    cdn.search = key.search;
    let lastError;
    for (const url of [cdn.href, key.href]) {
      const abort = new AbortController();
      const cancel = () => abort.abort(signal.reason);
      signal?.addEventListener('abort', cancel, {once: true});
      let timer;
      const touch = () => {
        clearTimeout(timer);
        timer = setTimeout(() => abort.abort(new Error('资源下载停滞')), 30000);
      };
      try {
        signal?.throwIfAborted();
        touch();
        const response = await originalFetch(url, {signal: abort.signal, mode: 'cors', credentials: 'omit'});
        if (!response.ok || !response.body) throw Error(`资源下载失败（${response.status}）`);
        const reader = response.body.getReader();
        const bytes = new Uint8Array(spec.bytes);
        let loaded = 0;
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          if (loaded + value.length > spec.bytes) throw Error('资源长度超出发布清单');
          bytes.set(value, loaded);
          loaded += value.length;
          touch();
          notify(file, loaded, spec.bytes, url === cdn.href ? 'cdn' : 'origin');
        }
        clearTimeout(timer);
        if (loaded !== spec.bytes) throw Error('资源下载不完整');
        await validate(bytes, spec);
        signal?.throwIfAborted();
        try { await cache?.put(key.href, responseFor(bytes, file)); } catch { /* Quota/private mode: continue without persistence. */ }
        return bytes;
      } catch (error) {
        signal?.throwIfAborted();
        lastError = error;
      } finally {
        clearTimeout(timer);
        abort.abort();
        signal?.removeEventListener('abort', cancel);
      }
    }
    throw lastError;
  }

  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    const file = url.pathname.split('/').pop();
    const spec = config.assets[file];
    // No API, third-party, Range, POST, or unknown file interception.
    const request = new Request(input instanceof Request ? input : url, init);
    if (url.origin !== location.origin || url.pathname !== '/camp-scene/' + file || !Object.hasOwn(config.assets, file)
        || request.method !== 'GET' || request.headers.has('range')) return originalFetch(input, init);
    const signal = init?.signal || (input instanceof Request ? input.signal : undefined);
    signal?.throwIfAborted();
    // Shared engine warmup has no consumer abort signal; pack transfers retain
    // their original cancellation semantics and never join an abandoned fetch.
    let work = !signal && pending.get(file);
    if (!work) {
      work = download(file, spec, signal);
      if (!signal) {
        pending.set(file, work);
        work.finally(() => pending.delete(file)).catch(() => {});
      }
    }
    return responseFor(await work, file);
  };

  // Entering /contact is the intent signal. Warm only the shared engine while
  // the chooser is visible, never all three packs or optional actor assets.
  if (!navigator.connection?.saveData && config.assets['index.wasm'])
    window.fetch('index.wasm').catch(() => {});
})();
