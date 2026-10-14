/* Optional Emscripten frame-submit state cache. Default OFF.
 * Only the SDK patch's two blit queries use this API; getParameter is NEVER
 * replaced. No framebuffer/shader status, draw, blit, or readiness is changed.
 * See artifacts/startup-v128/frame-submit/README.md for the coverage lease.
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory;
  else if (!root.MeadowFramebufferState) root.MeadowFramebufferState = factory();
})(typeof globalThis === "object" ? globalThis : this, function createFramebufferState() {
  "use strict";
  const FRAMEBUFFER = 0x8d40, DRAW = 0x8ca9, READ = 0x8ca8;
  const DRAW_BINDING = 0x8ca6, READ_BINDING = 0x8caa, SCISSOR = 0x0c11;
  const MUTATORS = ["createFramebuffer", "bindFramebuffer", "deleteFramebuffer", "enable", "disable"];
  const contexts = new WeakMap(), receivers = new WeakMap();
  let enabled = false, coverage = false, configuration = 0;
  const totals = { registered: 0, rejected: 0, hits: 0, nativeReads: 0, invalidations: 0 };
  const own = (object, name) => Object.prototype.hasOwnProperty.call(object, name);
  const objectLike = value => value !== null && (typeof value === "object" || typeof value === "function");

  function forget(state, reason, permanent) {
    state.generation++;
    state.knownDraw = state.knownRead = state.knownScissor = false;
    state.reason = reason;
    if (permanent) state.active = false;
    totals.invalidations++;
  }

  function usable(state) {
    if (!state || !state.active || !enabled || !coverage || state.configuration !== configuration) return false;
    if (state.context.GLctx !== state.gl || state.context.version !== state.version) {
      forget(state, "context-replaced", true);
      return false;
    }
    for (const name of MUTATORS) {
      if (state.gl[name] !== state.wrappers[name]) {
        forget(state, "mutator-replaced:" + name, true);
        return false;
      }
    }
    if (state.gl.getParameter !== state.native.getParameter || state.gl.isContextLost !== state.native.isContextLost) {
      forget(state, "query-method-replaced", true);
      return false;
    }
    let lost;
    try { lost = Reflect.apply(state.native.isContextLost, state.gl, []); }
    catch (_) { forget(state, "context-health-query-failed", true); return false; }
    if (lost !== false) {
      if (!state.lost) {
        forget(state, "context-lost", false);
        state.objects = new WeakMap();
      }
      state.lost = true;
      return false;
    }
    if (state.lost) {
      forget(state, "context-restored", false);
      state.objects = new WeakMap();
      state.lost = false;
    }
    return true;
  }

  function nativeRead(context, pname) {
    totals.nativeReads++;
    // Invoke the CURRENT method and receiver on fallback, exactly as stock.
    return context.GLctx.getParameter(pname);
  }

  function read(context, pname, key, known) {
    const state = contexts.get(context);
    if (!usable(state)) return nativeRead(context, pname);
    if (state[known]) { state.hits++; totals.hits++; return state[key]; }
    const generation = state.generation;
    const value = nativeRead(context, pname);
    if (usable(state) && generation === state.generation) {
      if (pname === SCISSOR ? typeof value === "boolean" : value === null || objectLike(value)) {
        state[key] = value;
        state[known] = true;
        if (pname !== SCISSOR && objectLike(value)) state.objects.set(value, true);
        if (pname === DRAW_BINDING && state.version === 1) {
          state.read = value;
          state.knownRead = true;
        }
      } else forget(state, "unexpected-native-query-value", true);
    }
    return value;
  }

  function callMutator(state, name, receiver, args) {
    // Borrowing a tracked method with another context bypasses that context's
    // own wrapper. Preserve native `this`/arguments and revoke its cache lease.
    if (receiver !== state.gl) {
      const other = objectLike(receiver) ? receivers.get(receiver) : null;
      if (other) forget(other, "borrowed-native-mutator", true);
      return Reflect.apply(state.native[name], receiver, args);
    }
    const wasUsable = usable(state), generation = state.generation;
    let result;
    try { result = Reflect.apply(state.native[name], receiver, args); }
    catch (error) { forget(state, "native-mutator-threw:" + name, false); throw error; }
    if (!wasUsable || !usable(state) || generation !== state.generation) return result;
    if (name === "createFramebuffer") {
      if (objectLike(result)) state.objects.set(result, true);
    } else if (name === "bindFramebuffer") {
      const target = args[0], framebuffer = args[1] == null ? null : args[1];
      const validTarget = target === FRAMEBUFFER || (state.version === 2 && (target === READ || target === DRAW));
      const ownedLive = framebuffer === null || (objectLike(framebuffer) && state.objects.get(framebuffer) === true);
      // Do not infer success from a void WebGL return for unknown/deleted/
      // foreign objects or coerced enums. No getError polling/consumption.
      if (args.length < 2 || !validTarget || !ownedLive) {
        state.knownDraw = state.knownRead = false;
      } else {
        if (target === FRAMEBUFFER || target === DRAW) { state.draw = framebuffer; state.knownDraw = true; }
        if (target === FRAMEBUFFER || target === READ) { state.read = framebuffer; state.knownRead = true; }
      }
    } else if (name === "deleteFramebuffer") {
      if (objectLike(args[0])) state.objects.set(args[0], false);
      // Native deletion may unbind DRAW and/or READ. Reseed from the real
      // query rather than assuming any unbinding/error/context-loss outcome.
      state.knownDraw = state.knownRead = false;
    } else if (name === "enable" || name === "disable") {
      const capability = args[0];
      if (capability === SCISSOR) {
        state.scissor = name === "enable";
        state.knownScissor = true;
      } else if (!Number.isInteger(capability) || capability < 0 || capability > 0xffffffff) {
        // WebIDL coercion (including valueOf callbacks) may address SCISSOR.
        state.knownScissor = false;
      }
    }
    return result;
  }

  function release(context) {
    const state = contexts.get(context);
    if (!state) return;
    forget(state, "released", true);
    for (const name of MUTATORS) {
      // Never undo a later owner's method replacement.
      // A host may freeze the context after registration. Keep an inert
      // forwarding wrapper rather than making SDK teardown throw.
      try { if (state.gl[name] === state.wrappers[name]) delete state.gl[name]; }
      catch (_) { /* Already inactive; native calls still pass through. */ }
    }
    if (state.lostListenerInstalled) {
      try { state.canvas.removeEventListener("webglcontextlost", state.onLost); } catch (_) {}
      state.lostListenerInstalled = false;
    }
    if (state.restoredListenerInstalled) {
      try { state.canvas.removeEventListener("webglcontextrestored", state.onRestored); } catch (_) {}
      state.restoredListenerInstalled = false;
    }
    if (receivers.get(state.gl) === state) receivers.delete(state.gl);
  }

  function register(context) {
    if (!enabled || !coverage) return false;
    if (!objectLike(context) || !objectLike(context.GLctx) || ![1, 2].includes(context.version)) {
      totals.rejected++; return false;
    }
    const gl = context.GLctx, canvas = gl.canvas;
    if (receivers.has(gl) || contexts.has(context) || !Object.isExtensible(gl)
        || !canvas || typeof canvas.addEventListener !== "function" || typeof canvas.removeEventListener !== "function") {
      totals.rejected++; return false;
    }
    // Preexisting instance mutator wrappers/aliases are not a proved native
    // interception boundary. SDK trace wrappers added later also revoke it.
    if (MUTATORS.some(name => own(gl, name) || typeof gl[name] !== "function")
        || typeof gl.getParameter !== "function" || typeof gl.isContextLost !== "function") {
      totals.rejected++; return false;
    }
    const state = { context, gl, canvas, version: context.version, configuration,
      active: true, lost: false, generation: 1, objects: new WeakMap(), wrappers: {}, native: {},
      knownDraw: false, knownRead: false, knownScissor: false, hits: 0, reason: "registered",
      lostListenerInstalled: false, restoredListenerInstalled: false };
    for (const name of [...MUTATORS, "getParameter", "isContextLost"]) state.native[name] = gl[name];
    state.onLost = () => {
      forget(state, "context-lost-event", false);
      state.objects = new WeakMap(); state.lost = true;
      // No preventDefault: restoration policy remains the application's.
    };
    state.onRestored = () => {
      forget(state, "context-restored-event", false);
      state.objects = new WeakMap(); state.lost = false;
    };
    contexts.set(context, state); receivers.set(gl, state);
    try {
      for (const name of MUTATORS) {
        state.wrappers[name] = function (...args) { return callMutator(state, name, this, args); };
        Object.defineProperty(gl, name, { value: state.wrappers[name], configurable: true, writable: true });
      }
      canvas.addEventListener("webglcontextlost", state.onLost);
      state.lostListenerInstalled = true;
      canvas.addEventListener("webglcontextrestored", state.onRestored);
      state.restoredListenerInstalled = true;
      // Sample actual state BEFORE SDK offscreen FBO creation / any scene draw.
      // No guessed defaults, even for preinitialized/reused WebGL contexts.
      read(context, SCISSOR, "scissor", "knownScissor");
      read(context, DRAW_BINDING, "draw", "knownDraw");
      if (!usable(state)) { release(context); totals.rejected++; return false; }
    } catch (_) {
      release(context); totals.rejected++; return false;
    }
    totals.registered++;
    return true;
  }

  function configure(options) {
    configuration++;
    enabled = !!options && options.enabled === true;
    // This is a host integration precondition, NOT automatically inferred
    // proof. Saved raw/prototype calls are undetectable; absent audit => OFF.
    coverage = !!options && options.exclusiveContextMethods === true;
    return enabled && coverage;
  }

  function invalidate(context, reason) {
    const state = contexts.get(context);
    if (state) forget(state, reason || "external-native-bindings", true);
  }

  return Object.freeze({
    schemaVersion: 1, configure, register, release, invalidate,
    readScissor: context => read(context, SCISSOR, "scissor", "knownScissor"),
    readFramebufferBinding: context => read(context, DRAW_BINDING, "draw", "knownDraw"),
    readReadFramebufferBinding: context => context.version === 2
      ? read(context, READ_BINDING, "read", "knownRead") : nativeRead(context, READ_BINDING),
    withExternalBindings(context, callback) { invalidate(context); return callback(context.GLctx); },
    snapshot(context) {
      const state = context && contexts.get(context);
      return { enabled, exclusiveContextMethods: coverage, ...totals,
        context: state ? { active: usable(state), generation: state.generation, hits: state.hits,
          reason: state.reason, knownDraw: state.knownDraw, knownRead: state.knownRead,
          knownScissor: state.knownScissor, version: state.version } : null };
    }
  });
});
