/* Optional public presentation transport. Loading this file does not fetch a pack,
 * install listeners, change core readiness or start an engine.
 *
 * Trusted integration (never derive allowedParentOrigin/assetIds from a query):
 *   window.meadowCamp = MeadowCampBridge.create({allowedParentOrigin, assetIds});
 *   // At the EXISTING scene-ready + engine-start + two-RAF gate:
 *   meadowCamp.corePresented();
 *   // Schedule loadPackAfterCore after that gate; a trusted Godot hook mounts
 *   // with load_resource_pack(path, false), creates the node and acknowledges
 *   // only after setup and a render boundary. Existing tier packs stay intact.
 *
 * Sharded owner integration (selected-pack-bindings version stays 1):
 *   const mount = createMountClient({pack:config.optionalPack,
 *     actorShards:config.actorShards ?? []}); // install as meadowCampMount first
 *   // Inside the actual corePresented gate, using the already-running engine:
 *   const nativeCore = mount.corePresented();
 *   const runtimeReady = loadPackAfterCore({pack:config.optionalPack,
 *     coreReady:nativeCore, engine, mount:(p,h) => mount.mount(p,h), onStatus});
 *   const actors = createActorLoader({actorShards:config.actorShards,
 *     assetIds:config.assetIds, coreReady:nativeCore, runtimeReady, engine,
 *     mountActor:(p,h) => mount.mountActor(p,h), onStatus});
 *   meadowCamp.bindAssetLoader(actors.select);
 * Owner catches runtimeReady failures, disposes actors on pagehide, and wires
 * explicit actor-download retry to actors.retry(). Omit this actor loader for
 * legacy monolithic packs. Pin the full catalogue before engine startup; only
 * current IDs are fetched. Cache is per running engine, not a promise of
 * persistence across reloads. Staging copies files but MUST NOT preload shards.
 *
 * Parent -> child (exact keys; sequence strictly increases within session):
 * {protocol:'meadow-camp-presentation', version:1, type:'snapshot', session,
 *  sequence:1, snapshot:{mode:'fighting', heroAssetId:'hero-ranger',
 *  petAssetId:'pet-fox', bossAssetId:'boss-guardian', elapsed:12, duration:600,
 *  roundId:'public-round-reference'}}
 * session comes from bridge_ready; it is a replay guard, NOT an auth token.
 * roundId must already be a public opaque display reference. This bridge cannot
 * identify sensitive values hidden inside an otherwise valid public field.
 * Version 1 accepts the original seven keys or exactly those seven plus the
 * paired bossHp/bossMaxHp integer display values. A defeated snapshot requires
 * that pair with bossHp=0, a public round reference and all three actors.
 * No credentials, account data, damage/reward authority, commands or arbitrary
 * URLs belong here. Neither zero HP nor time causes a mode change/settlement.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MeadowCampBridge = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const PROTOCOL = 'meadow-camp-presentation';
  const VERSION = 1;
  const MODES = Object.freeze(['demo', 'fighting', 'paused', 'cooldown',
    'daily_complete', 'waiting', 'unavailable', 'defeated']);
  const ROLES = ['hero', 'pet', 'boss'];
  const SNAPSHOT_KEYS = ['mode', 'heroAssetId', 'petAssetId', 'bossAssetId',
    'elapsed', 'duration', 'roundId'];
  const SNAPSHOT_HP_KEYS = [...SNAPSHOT_KEYS, 'bossHp', 'bossMaxHp'];
  const ENVELOPE_KEYS = ['protocol', 'version', 'type', 'session', 'sequence', 'snapshot'];
  // Public catalogue keys, not resource paths. Allow e.g. hero/ranger while
  // keeping transport IDs separate from the fixed namespaced PCK paths.
  const ID = /^(?=.{1,64}$)[a-z][a-z0-9_-]*(?:\/[a-z][a-z0-9_-]*)?$/;
  const ROUND = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
  const STATUSES = new Set(['waiting_for_core', 'waiting_for_state', 'loading',
    'applying', 'pack_ready', 'ready', 'missing_assets', 'unsafe_placement', 'stale',
    'unavailable', 'error', 'reload_required']);

  function exact(value, keys) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const own = Reflect.ownKeys(value);
    return own.length === keys.length && own.every(key => keys.includes(key)
      && Object.getOwnPropertyDescriptor(value, key)?.get === undefined
      && Object.getOwnPropertyDescriptor(value, key)?.set === undefined);
  }
  function originOf(value) {
    if (typeof value !== 'string' || value === 'null') throw Error('Exact parent origin required');
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.origin !== value || value.includes('*')
        || url.username || url.password) throw Error('Exact parent origin required');
    return value;
  }
  function assetsOf(value) {
    if (!exact(value, ROLES)) throw Error('Three public asset allowlists required');
    const result = {};
    const all = new Set();
    for (const role of ROLES) {
      if (!Array.isArray(value[role]) || value[role].length > 64) throw Error('Invalid asset allowlist');
      result[role] = new Set();
      for (const id of value[role]) {
        if (typeof id !== 'string' || !ID.test(id) || all.has(id)) throw Error('Invalid asset identifier');
        result[role].add(id); all.add(id);
      }
    }
    return result;
  }
  function snapshotOf(value, assets) {
    const keys = exact(value, SNAPSHOT_KEYS) ? SNAPSHOT_KEYS
      : exact(value, SNAPSHOT_HP_KEYS) ? SNAPSHOT_HP_KEYS : null;
    if (!keys || !MODES.includes(value.mode)
        || typeof value.elapsed !== 'number' || !Number.isFinite(value.elapsed)
        || typeof value.duration !== 'number' || !Number.isFinite(value.duration)
        || value.elapsed < 0 || value.duration < 0 || value.duration > 86400
        || value.elapsed > value.duration || typeof value.roundId !== 'string'
        || (value.roundId !== '' && !ROUND.test(value.roundId))) return null;
    if (['fighting', 'paused'].includes(value.mode)
        && (!value.roundId || value.duration <= 0)) return null;
    const hasHp = keys === SNAPSHOT_HP_KEYS;
    if (hasHp && (!Number.isInteger(value.bossHp) || !Number.isInteger(value.bossMaxHp)
        || value.bossHp < 0 || value.bossHp > 1e9 || value.bossMaxHp <= 0
        || value.bossMaxHp > 1e9 || value.bossHp > value.bossMaxHp)) return null;
    if (value.mode === 'defeated' && (!hasHp || value.bossHp !== 0 || !value.roundId)) return null;
    for (const role of ROLES) {
      const id = value[`${role}AssetId`];
      if (typeof id !== 'string' || (id !== '' && !assets[role].has(id))) return null;
      if (['fighting', 'paused', 'defeated'].includes(value.mode) && !id) return null;
    }
    if (value.mode === 'demo' && ROLES.every(role => !value[`${role}AssetId`])) return null;
    // Never forward the original object: this boundary reconstructs public data.
    return Object.freeze(Object.fromEntries(keys.map(key => [key, value[key]])));
  }

  function create(config, host = globalThis.window) {
    const parentOrigin = originOf(config?.allowedParentOrigin);
    const assets = assetsOf(config.assetIds);
    if (!host?.parent || host.parent === host) throw Error('A configured parent iframe is required');
    const parent = host.parent;
    const nonce = new Uint8Array(16);
    host.crypto.getRandomValues(nonce);
    const session = Array.from(nonce, n => n.toString(16).padStart(2, '0')).join('');
    let sequence = -1, delivered = -1, closed = false, core = false;
    let callback = null, latest = null, scheduled = false, lastStatus = '', receivedAt = 0, assetLoader = null;
    const post = (type, fields) => {
      if (!closed) parent.postMessage({protocol: PROTOCOL, version: VERSION, type,
        session, ...fields}, parentOrigin);
    };
    const report = status => {
      if (closed || !STATUSES.has(status)) return false;
      // Mount completion and the renderer's first drawn-frame callback may
      // arrive in either order. A late component ack must not erase actor
      // readiness, missing art or a stale/unsafe presentation diagnosis.
      if (status === 'pack_ready' && ['ready', 'missing_assets', 'unsafe_placement', 'stale', 'unavailable'].includes(lastStatus)) return true;
      if (status !== lastStatus) { lastStatus = status; post('presentation_status', {status}); }
      return true;
    };
    function selectAssets(snapshot, current) {
      if (!assetLoader) return;
      const ids = ['waiting', 'unavailable'].includes(snapshot.mode) ? []
        : ROLES.map(role => snapshot[`${role}AssetId`]).filter(Boolean);
      try {
        Promise.resolve(assetLoader(Object.freeze(ids))).catch(() => {
          if (!closed && sequence === current) report('error');
        });
      } catch (_) { if (!closed && sequence === current) report('error'); }
    }
    function canDeliverLatest() {
      if (!latest) return false;
      // Only the CURRENT validated, non-authoritative demo can survive a slow
      // core/runtime start. Never refresh server timestamps or fall back to an
      // older demo after a newer server/hidden snapshot replaces it.
      if (latest.mode === 'demo') return true;
      const age = host.performance.now() - receivedAt;
      return Number.isFinite(age) && age >= 0 && age <= 15000;
    }
    function flush() {
      if (closed || !core || !callback || !latest || delivered === sequence || scheduled) return;
      scheduled = true;
      host.queueMicrotask(() => {
        scheduled = false;
        if (closed || !core || !callback || !latest || delivered === sequence) return;
        if (!canDeliverLatest()) { report('stale'); return; }
        const current = sequence;
        try {
          // Server pause/mode changes are immediate, even while art downloads.
          // Native assets_available fills missing CURRENT actors without any
          // JS snapshot replay or resetting the renderer's stale-state clock.
          callback(JSON.stringify(latest)); delivered = current; selectAssets(latest, current);
        }
        catch (_) { report('error'); }
      });
    }
    function receive(event) {
      if (closed || event.source !== parent || event.origin !== parentOrigin) return;
      try {
        const data = event.data;
        if (!exact(data, ENVELOPE_KEYS) || data.protocol !== PROTOCOL || data.version !== VERSION
            || data.type !== 'snapshot' || data.session !== session
            || !Number.isSafeInteger(data.sequence) || data.sequence < 0 || data.sequence <= sequence) return;
        const snapshot = snapshotOf(data.snapshot, assets);
        if (!snapshot) return;
        latest = snapshot; sequence = data.sequence; receivedAt = host.performance.now(); flush();
      } catch (_) { /* Malformed data never enters Godot or produces an echo. */ }
    }
    host.addEventListener('message', receive);
    const api = Object.freeze({
      corePresented() {
        if (closed || core) return;
        core = true; report('waiting_for_state'); flush();
      },
      bind(next) {
        if (closed || typeof next !== 'function' || (callback && callback !== next)) return false;
        if (callback !== next) delivered = -1;
        callback = next; flush(); return true;
      },
      unbind(previous) {
        if (callback !== previous) return false;
        callback = null; delivered = -1; return true;
      },
      bindAssetLoader(loader) {
        if (closed || typeof loader !== 'function' || (assetLoader && assetLoader !== loader)) return false;
        assetLoader = loader;
        if (core && latest && delivered === sequence && canDeliverLatest()) selectAssets(latest, sequence);
        return true;
      },
      unbindAssetLoader(loader) {
        if (assetLoader !== loader) return false;
        assetLoader = null; return true;
      },
      report,
      dispose() {
        if (closed) return;
        closed = true; host.removeEventListener('message', receive);
        callback = latest = assetLoader = null;
      }
    });
    // bridge_ready means only the listener is installed, NEVER scene/core ready.
    post('bridge_ready', {}); report('waiting_for_core');
    return api;
  }

  function packOf(value) {
    if (!exact(value, ['file', 'bytes', 'sha256']) || typeof value.file !== 'string'
        || !/^camp-presentation-[a-f0-9]{12}\.pck$/.test(value.file)
        || typeof value.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.sha256)
        || value.file !== `camp-presentation-${value.sha256.slice(0, 12)}.pck`
        || !Number.isSafeInteger(value.bytes) || value.bytes <= 0 || value.bytes > 16 * 1024 * 1024)
      throw Error('Invalid presentation pack');
    return Object.freeze({...value});
  }

  function actorPackOf(value) {
    if (!exact(value, ['file', 'bytes', 'sha256']) || typeof value.sha256 !== 'string'
        || !/^[a-f0-9]{64}$/.test(value.sha256) || value.file !== `camp-actor-${value.sha256.slice(0, 12)}.pck`
        || !Number.isSafeInteger(value.bytes) || value.bytes <= 0 || value.bytes > 9 * 1024 * 1024)
      throw Error('Invalid actor shard pin');
    return Object.freeze({...value});
  }
  function shardsOf(value) {
    if (!Array.isArray(value) || value.length > 64) throw Error('Bounded actor shard manifest required');
    const byFile = new Map(), byId = new Map(); let total = 0;
    for (const row of value) {
      if (!exact(row, ['pack', 'assetIds']) || !Array.isArray(row.assetIds)
          || row.assetIds.length < 1 || row.assetIds.length > 64) throw Error('Invalid actor shard');
      const pack = actorPackOf(row.pack);
      if (byFile.has(pack.file)) throw Error('Duplicate actor shard');
      const assetIds = row.assetIds.map(id => {
        if (typeof id !== 'string' || !ID.test(id) || byId.has(id)) throw Error('Duplicate or invalid shard asset key');
        byId.set(id, pack); return id;
      });
      byFile.set(pack.file, Object.freeze({pack, assetIds:Object.freeze(assetIds)})); total += pack.bytes;
    }
    if (total > 128 * 1024 * 1024 || byId.size > 64) throw Error('Actor library exceeds bounded cache budget');
    return {byFile, byId, total};
  }

  /** Independent native mount callback facade. Install as meadowCampMount
   * BEFORE starting the wrapper. Never merge with meadowBoot.active or expose
   * these functions through the parent postMessage transport.
   * config.pack is the wrapper's build-time optionalPack pin (null disables it).
   * corePresented must be called at the owner's EXISTING actual core gate.
   * No file fetch/copy/mount occurs here; loadPackAfterCore owns bounded I/O.
   */
  function createMountClient(config, host = globalThis.window) {
    if (!exact(config, ['pack']) && !exact(config, ['pack', 'actorShards'])) throw Error('Explicit optional pack pin required');
    const pack = config.pack === null ? null : packOf(config.pack);
    const shards = shardsOf(config.actorShards === undefined ? [] : config.actorShards);
    if (!pack && shards.byFile.size) throw Error('Actor shards require a pinned runtime');
    let callback = null, closed = false, core = false, coreSent = false;
    let coreRequest = null, pending = null, attempt = null, serial = 0, runtimeApplied = false;
    const actorAttempts = new Map(), actorQueue = [];
    const codes = new Set(['applied', 'not_ready', 'disabled', 'pin_mismatch',
      'namespace_conflict', 'reload_required', 'actor_unavailable', 'busy']);
    const failure = (code, uncertain = false, actor = false) => {
      const error = Error(`Camp native mount: ${code}`);
      error.reloadRequired = uncertain && !actor; error.packUncertain = uncertain; error.retryable = !uncertain;
      return error;
    };
    function settle(request, success, value) {
      if (!request || request.done) return false;
      request.done = true; host.clearTimeout(request.timer);
      if (success) request.resolve(value); else request.reject(value);
      return true;
    }
    function stopAll(code) {
      closed = true; callback = null;
      settle(coreRequest, false, failure(code));
      settle(pending, false, failure(code, true, pending?.actor));
      for (const queued of actorQueue.splice(0)) settle(queued, false, failure(code, false, true));
    }
    function request(uncertain, actor = false) {
      const record = {done:false, actor, expiresAt:host.performance.now() + 30000};
      record.promise = new Promise((resolve, reject) => { record.resolve = resolve; record.reject = reject; });
      // Retain rejected state for duplicate calls without an unhandled rejection.
      record.promise.catch(() => {});
      record.timer = host.setTimeout(() => { settle(record, false, failure('timeout', uncertain, actor)); stopAll('timeout'); }, 30000);
      return record;
    }
    function live(record, uncertain) {
      if (closed || !record || record.done) return false;
      if (host.performance.now() >= record.expiresAt) {
        settle(record, false, failure('timeout', uncertain, record.actor)); stopAll('timeout'); return false;
      }
      return true;
    }
    function sendCore() {
      if (!callback || coreSent || !live(coreRequest, false)) return;
      coreSent = true;
      try { callback('core_presented'); }
      catch (_) { stopAll('callback'); }
    }
    function pumpActors() {
      if (closed || !runtimeApplied || (pending && !pending.done) || !actorQueue.length) return;
      pending = actorQueue.shift();
      if (!live(pending, true)) return;
      try { callback('mount_actor', pending.id, pending.path, pending.digest); }
      catch (_) { stopAll('callback'); }
    }
    return Object.freeze({
      bind(next) {
        if (closed || typeof next !== 'function' || (callback && callback !== next)) return false;
        callback = next; sendCore(); return true;
      },
      unbind(previous) {
        if (!callback || callback !== previous) return false;
        stopAll('unbound');
        return true;
      },
      corePresented() {
        if (coreRequest) return coreRequest.promise;
        if (closed) return Promise.reject(failure('closed'));
        coreRequest = request(false); sendCore(); return coreRequest.promise;
      },
      coreAccepted(success, code) {
        if (!coreSent || typeof success !== 'boolean'
            || code !== (success ? 'core_presented' : 'not_ready') || !live(coreRequest, false)) return false;
        core = success;
        if (!success) closed = true;
        return settle(coreRequest, success, success ? true : failure('not_ready'));
      },
      mount(path, digest) {
        if (!pack) return Promise.reject(failure('disabled'));
        if (path !== `/${pack.file}` || digest !== pack.sha256) return Promise.reject(failure('pin_mismatch'));
        if (attempt) return attempt;
        if (closed || !callback || !core) return Promise.reject(failure('not_ready'));
        pending = request(true); pending.id = ++serial; attempt = pending.promise;
        try { callback('mount', pending.id, path, digest); }
        catch (_) { stopAll('callback'); }
        return attempt;
      },
      mountActor(path, digest) {
        const shard = typeof path === 'string' && path.startsWith('/') ? shards.byFile.get(path.slice(1)) : null;
        if (!shard || path !== `/${shard.pack.file}` || digest !== shard.pack.sha256) return Promise.reject(failure('pin_mismatch', false, true));
        if (actorAttempts.has(path)) return actorAttempts.get(path);
        if (closed || !callback || !core || !runtimeApplied) return Promise.reject(failure('not_ready', false, true));
        const next = request(true, true); next.id = ++serial; next.path = path; next.digest = digest;
        actorAttempts.set(path, next.promise); actorQueue.push(next); pumpActors();
        return next.promise;
      },
      applied(id, success, code) {
        if (!Number.isSafeInteger(id) || id < 1 || id !== pending?.id || typeof success !== 'boolean'
            || !codes.has(code) || success !== (code === 'applied') || !live(pending, true)) return false;
        const actor = pending.actor;
        const accepted = settle(pending, success, success ? true : failure(code, true, actor));
        if (!actor) { runtimeApplied = success; if (!success) stopAll(code); }
        pumpActors();
        return accepted;
      },
      dispose() {
        stopAll('disposed');
      }
    });
  }

  /** One attempt. On download failure the owner may retry explicitly. Once mount
   * has been invoked, a failure has reloadRequired=true: do not retry an uncertain
   * mount in the same engine. Owner serializes attempts and preserves core/detail
   * scheduling. mount(path, sha256) must resolve true after a REAL applied frame.
   * pack_ready acknowledges the mounted component; only the renderer reports
   * ready for selected visible actors. Same-engine duplicate calls share one
   * attempt. An uncertain mount or a different pack requires a fresh engine.
   * No pack can be downloaded before an explicit, successfully resolved coreReady.
   */
  const engineLoads = new WeakMap();
  async function loadPackAfterCore(options, host = globalThis.window) {
    const spec = packOf(options?.pack);
    if (!options.coreReady || typeof options.coreReady.then !== 'function'
        || typeof options.engine?.copyToFS !== 'function' || typeof options.mount !== 'function')
      throw Error('Explicit core gate, running engine and mount acknowledgement required');
    const key = `${spec.sha256}:${spec.bytes}`;
    const existing = engineLoads.get(options.engine);
    if (existing) {
      if (existing.key !== key) throw Error('A different presentation pack requires reload');
      return existing.promise;
    }
    const promise = runPackLoad(options, host, spec);
    engineLoads.set(options.engine, {key, promise});
    try { return await promise; }
    catch (error) {
      if (!error.reloadRequired) engineLoads.delete(options.engine);
      throw error;
    }
  }
  async function runPackLoad(options, host, spec) {
    const report = status => { try { options.onStatus?.(status); } catch (_) { /* UI is optional. */ } };
    const abort = new AbortController();
    let stop, timer, mounting = false, stopped = false, expiresAt = Infinity;
    const deadline = new Promise((_, reject) => { stop = () => {
      stopped = true; abort.abort(); reject(Error('Presentation load cancelled or timed out'));
    }; });
    deadline.catch(() => {});
    const check = () => {
      if (!stopped && host.performance.now() >= expiresAt) stop();
      if (stopped) throw Error('Presentation load cancelled or timed out');
    };
    const wait = async promise => { const result = await Promise.race([promise, deadline]); check(); return result; };
    options.signal?.addEventListener('abort', stop, {once:true});
    if (options.signal?.aborted) stop();
    try {
      report('waiting_for_core');
      await wait(options.coreReady);
      expiresAt = host.performance.now() + 60000;
      timer = host.setTimeout(stop, 60000);
      report('loading');
      // Relative, content-addressed local pack only; omit credentials even on the
      // same origin and reject redirects. This path has no backend dependency.
      const response = await wait(host.fetch(spec.file, {signal:abort.signal,
        credentials:'omit', redirect:'error', mode:'same-origin'}));
      if (!response.ok) throw Error('Presentation download failed');
      // Streaming bounds protect memory even if the server sends the wrong size.
      const reader = response.body?.getReader();
      if (!reader) throw Error('A bounded streaming response is required');
      const bytes = new Uint8Array(spec.bytes);
      let offset = 0;
      try {
        while (true) {
          const part = await wait(reader.read());
          if (part.done) break;
          if (!(part.value instanceof Uint8Array) || offset + part.value.byteLength > bytes.length)
            throw Error('Presentation size mismatch');
          bytes.set(part.value, offset); offset += part.value.byteLength;
        }
      } catch (error) { Promise.resolve(reader.cancel()).catch(() => {}); throw error; }
      finally { reader.releaseLock(); }
      if (offset !== bytes.length) throw Error('Presentation size mismatch');
      const digest = await wait(host.crypto.subtle.digest('SHA-256', bytes));
      const sha = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
      if (sha !== spec.sha256) throw Error('Presentation checksum mismatch');
      const path = `/${spec.file}`;
      check(); options.engine.copyToFS(path, bytes.buffer); check();
      report('applying');
      const result = await wait(Promise.resolve().then(() => {
        check(); mounting = true; return options.mount(path, spec.sha256);
      }));
      if (result !== true) throw Error('Presentation was not applied');
      report('pack_ready');
      return Object.freeze({path, sha256:sha, bytes:bytes.length});
    } catch (error) {
      // Error messages are local diagnostics; never send arbitrary exception text
      // back across the iframe. The status protocol exposes fixed enums only.
      const failure = new Error('Camp presentation could not be loaded', {cause:error});
      failure.reloadRequired = mounting;
      report(mounting ? 'reload_required' : 'error');
      throw failure;
    } finally {
      host.clearTimeout(timer); options.signal?.removeEventListener('abort', stop); abort.abort();
    }
  }
  /** On-demand immutable actor library. No fetch at construction, no preload of
   * unused outfits, at most TWO bounded downloads, native mounts serialized by
   * createMountClient. select takes only validated public IDs (<=1 per role).
   * Previously mounted PCKs stay in this engine's FS; only the current three
   * actors' decoded frame textures are retained by the renderer.
   * Failed downloads need explicit retry(). Failed/uncertain actor mounts are
   * terminal for that shard, but never reload the world or the renderer pack.
   */
  const actorLibraries = new WeakMap();
  function createActorLoader(options, host = globalThis.window) {
    const shards = shardsOf(options?.actorShards);
    const assets = assetsOf(options.assetIds), roleOf = new Map();
    for (const role of ROLES) for (const id of assets[role]) roleOf.set(id, role);
    if (roleOf.size !== shards.byId.size || [...roleOf.keys()].some(id => !shards.byId.has(id)))
      throw Error('Shard catalogue must exactly cover the public asset allowlists');
    if (typeof options.engine?.copyToFS !== 'function' || typeof options.mountActor !== 'function'
        || typeof options.coreReady?.then !== 'function' || typeof options.runtimeReady?.then !== 'function')
      throw Error('Explicit core/runtime gates and native actor mount required');
    // Copy authority-bearing owner bindings once, just as the pins/IDs above.
    // Later edits to a caller's options object cannot redirect a queued job.
    const engine = options.engine, mountActor = options.mountActor, onStatus = options.onStatus;
    const coreReady = options.coreReady, runtimeReady = options.runtimeReady;
    const identity = JSON.stringify([...shards.byFile.values()].sort((a,b) => a.pack.file.localeCompare(b.pack.file)))
      + JSON.stringify([...roleOf].sort());
    const existing = actorLibraries.get(engine);
    if (existing) {
      if (existing.identity !== identity) throw Error('An engine cannot replace its immutable actor catalogue');
      return existing.api;
    }
    const jobs = new Map(); let selected = [], wanted = new Set(), running = 0, ready = false, closed = false, gateError = null;
    const report = status => { if (!closed) try { onStatus?.(status); } catch (_) { /* Owner UI is optional. */ } };
    const cancelled = () => { const error = Error('Actor selection superseded'); error.name = 'AbortError'; return error; };
    function fail(job, error) {
      if (job.done) return;
      job.done = true; job.state = 'failed'; job.error = error; job.reject(error);
    }
    function cancel(job) {
      if (job.done || job.state === 'applying') return;
      job.cancelled = true; job.abort.abort();
      if (job.state === 'queued') fail(job, cancelled());
      if (jobs.get(job.spec.file) === job) jobs.delete(job.spec.file);
    }
    function makeJob(spec) {
      const job = {spec, state:'queued', abort:new AbortController(), done:false, cancelled:false, error:null};
      job.promise = new Promise((resolve,reject) => { job.resolve = resolve; job.reject = reject; });
      job.promise.catch(() => {}); jobs.set(spec.file, job); return job;
    }
    function finishStatus() {
      if ([...wanted].every(file => jobs.get(file)?.state === 'mounted')) report(wanted.size ? 'pack_ready' : 'waiting_for_state');
    }
    function pump() {
      if (closed || !ready || gateError) return;
      for (const job of jobs.values()) {
        if (running >= 2) break;
        if (job.state !== 'queued' || !wanted.has(job.spec.file)) continue;
        running++; job.state = 'loading';
        void runPackLoad({coreReady:Promise.resolve(true), engine, pack:job.spec,
          signal:job.abort.signal, mount:mountActor,
          onStatus:status => {
            if (status === 'applying') job.state = 'applying';
            if (wanted.has(job.spec.file) && jobs.get(job.spec.file) === job && ['loading','applying'].includes(status)) report(status);
          }}, host, job.spec).then(result => {
            job.state = 'mounted'; job.done = true; job.resolve(result);
            // A stale selection may finish a native mount already in progress.
            // Cache it; the renderer does not replay that obsolete selection.
            finishStatus();
          }, error => {
            if (job.cancelled) { fail(job, cancelled()); return; }
            const failure = Error('Actor artwork could not be loaded', {cause:error});
            failure.reloadRequired = false; failure.packUncertain = !!error.reloadRequired;
            failure.retryable = !failure.packUncertain;
            fail(job, failure);
            if (wanted.has(job.spec.file) && jobs.get(job.spec.file) === job) report('error');
          }).finally(() => { running--; pump(); });
      }
    }
    function select(ids) {
      if (closed) return Promise.reject(Error('Actor loader disposed'));
      if (!Array.isArray(ids) || ids.length > 3 || new Set(ids).size !== ids.length
          || ids.some(id => typeof id !== 'string' || !roleOf.has(id))
          || new Set(ids.map(id => roleOf.get(id))).size !== ids.length)
        return Promise.reject(Error('Only current public hero/pet/boss identifiers are accepted'));
      selected = [...ids]; wanted = new Set(ids.map(id => shards.byId.get(id).file));
      for (const job of [...jobs.values()]) if (!wanted.has(job.spec.file)) cancel(job);
      if (gateError) return Promise.reject(gateError);
      const tasks = [...wanted].map(file => (jobs.get(file) || makeJob(shards.byFile.get(file).pack)).promise);
      if (!ready && wanted.size) report('waiting_for_core');
      pump(); finishStatus();
      return Promise.all(tasks);
    }
    const api = Object.freeze({
      select,
      retry() {
        if (closed) return Promise.reject(Error('Actor loader disposed'));
        for (const file of wanted) {
          const job = jobs.get(file);
          if (job?.state === 'failed' && job.error?.retryable) jobs.delete(file);
        }
        return select(selected);
      },
      getStatus() {
        return Object.freeze({selectedAssetIds:Object.freeze([...selected]), knownShards:shards.byFile.size,
          activeDownloads:running, queuedShards:[...jobs.values()].filter(j => j.state === 'queued').length,
          mountedShards:[...jobs.values()].filter(j => j.state === 'mounted').length,
          cachedPackBytes:[...jobs.values()].filter(j => j.state === 'mounted').reduce((sum,j) => sum + j.spec.bytes, 0)});
      },
      dispose() {
        if (closed) return;
        closed = true;
        for (const job of jobs.values()) if (!job.done) { job.abort.abort(); fail(job, cancelled()); }
      }
    });
    actorLibraries.set(engine, {identity, api});
    void Promise.all([coreReady, runtimeReady]).then(([coreResult, runtimeResult]) => {
      if (coreResult !== true || !runtimeResult) throw Error('Native core/runtime readiness was refused');
      if (!closed) { ready = true; pump(); }
    }).catch(error => {
      gateError = Error('Actor runtime gate failed', {cause:error});
      for (const job of jobs.values()) if (!job.done) fail(job, gateError);
      if (wanted.size) report('error');
    });
    return api;
  }
  return Object.freeze({PROTOCOL, VERSION, MODES, create, createMountClient, loadPackAfterCore, createActorLoader});
});
