/* Godot 4.7.2 / ANGLE scene-feature compiler workaround; NOT enabled on load.
 * This script only publishes its API. The loader must call install(canvas,
 * options) before Engine creates its context; the helper never installs itself.
 * Release policy belongs to the loader: absent fast_compile defaults to scene
 * specialization only for the actual selected pack's build-verified contract;
 * no contract, fast_compile=0, and unknown explicit values keep the stock path.
 * Explicit fast_compile=1 selects loop-only; =scene selects contract mode.
 * Cleanup is idempotent. No loader/query policy is implemented in this helper.
 *
 * Pin: ed1daf0bf001b61586d9930840f2f1394092c079, drivers/gles3/shaders/scene.glsl
 * SHA-256: 2c77be0c85b7ab1a85ed8009c77cdb6216f1494d43083592213ad68f9e812977
 * Only the three stock fragment loop blocks at lines 2644/2668/2693 match.
 * Structural fingerprints permit whitespace/comments and redundant highp on i;
 * they are not a claim to authenticate a complete generated material shader.
 * min(uint(MAX_FORWARD_LIGHTS), count) retains exactly the old iteration count
 * and order, including zero and count > cap. All light bodies stay byte-exact.
 *
 * Scene-feature contract API:
 *   transformSource(source, {contract: {packSha256, spotLights: 0, areaLights: 0}})
 *   install(canvas, {contract: {packSha256, spotLights: 0, areaLights: 0}})
 * Only the independently reviewed SCENE_PACK_SHA256S below are permitted
 * (neither original nor balanced). Main must supply the actual selected
 * immutable pack's hash and accept independent native/build-time proof of zero
 * spot/area lights throughout this scene (including night). This helper does NOT
 * hash/download a PCK or prove light counts. Never derive the contract from an
 * untrusted query or copy a stale accepted hash onto another pack.
 * By default only pinned BASE_PASS color fragments without vertex/depth/
 * unshaded/additive modes gain missing DISABLE_LIGHT_SPOT/AREA definitions.
 * Explicit sceneDirectionalBase: true additionally permits BASE_PASS plus
 * USE_ADDITIVE_LIGHTING, but never ADDITIVE_OMNI/SPOT or non-base variants.
 * The same zero-light contract is mandatory. This removes inactive spot/area
 * blocks, not directional/omni math or shared LightData members; active-uniform
 * reflection is NOT identical. This option is trusted loader policy, not a new
 * pack assertion. Unknown macro programs retain loop-only behavior.
 * This is NOT equivalent for future scenes with those light types. A future Boss
 * PCK's different hash automatically rejects specialization when supplied as the
 * actual contract. Missing/invalid contracts keep the existing loop-only mode.
 * Install snapshots its contract for the one-engine/one-pack canvas lifetime;
 * repeat install is idempotent, not an option switch. Reload/dispose for a new
 * pack. Keep the context hook after ready for later night shaders; fatal cleanup
 * remains caller-owned. Counters count submissions, not unique compiled programs.
 * Native light proof and measured release performance/visual acceptance remain
 * outside this helper; source guards and counters do not establish those facts.
 */
(function (root, factory) {
  "use strict";
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.meadowWebglCompile = api;
})(typeof window === "object" ? window : globalThis, function (root) {
  "use strict";
  const PIN = "godot-4.7.2-ed1daf0bf-scene-forward-loops-v1";
  const MAX_SOURCE_CHARS = 2 * 1024 * 1024;
  const MAX_EVIDENCE = 16;
  const SCENE_PACK_SHA256S = Object.freeze([
    "3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c",
    "018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79",
    "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf",
    "1182ea711300b62fc4cd097acb1321840e75b53d02e884fbcdf02a2e15796460",
    "dfae7b33bbf28a12a456610abb7dd80da36bd5158b5b5cfc8f1527c5150cadfc",
    "61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3",
    "699c08aac4201b9c507d964b6a857247af6f718ebab203da085e5937de0052db",
    "2850c2eebd3382b57866b77aba6dbfe5e4209190c478c502c637bce660fefff4",
    "78edf276bef239b94c97a549b1b853822d21f8ff2ffcdae372b045ae8da90dd5",
    "c88c9627f702ded260a44b781e516ebe89c9d1bade15b0b60b65d21c67e2e25b",
    "4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c"
  ]);
  const fingerprints = Object.freeze({
    omni_light_count: "db4015a4", spot_light_count: "2dffae45", area_light_count: "2a947276"
  });
  const installs = new WeakMap();

  function fnv(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
    return (hash >>> 0).toString(16).padStart(8, "0");
  }

  function canonical(block) {
    // Keep a preprocessor end-of-line token: joining directives changes GLSL.
    return (block.replace(/^[ \t]*(#[^\r\n]*)/gm, "$1\x00")
      .match(/[A-Za-z_]\w*|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[uUfF]?|>=|<=|==|!=|\+\+|--|&&|\|\||<<|>>|[^\s]/g) || []).join(" ");
  }

  function acceptedContract(options) {
    try {
      const contract = options?.contract;
      if (!contract || typeof contract !== "object" || Array.isArray(contract)) return null;
      const packSha256 = contract.packSha256;
      if (!SCENE_PACK_SHA256S.includes(packSha256) || contract.spotLights !== 0 || contract.areaLights !== 0) return null;
      return Object.freeze({ packSha256, spotLights: 0, areaLights: 0 });
    } catch (_) { return null; } // Optional/malformed contracts never block loop-only mode.
  }

  function directionalBaseOption(options) {
    try { return options?.sceneDirectionalBase === true; }
    catch (_) { return false; }
  }

  function missingSceneDefines(clean, contract, source, sceneDirectionalBase) {
    // This is a physical-line matcher, not a GLSL preprocessor. A continuation
    // can hide a mode name/directive, even by extending a preceding // comment.
    // Unknown splicing opts out; do not assume an excluded mode is inactive.
    if (!contract || clean.includes("\\") || /\\[\r\n]/.test(source)) return [];
    const targets = ["DISABLE_LIGHT_SPOT", "DISABLE_LIGHT_AREA"];
    const excluded = new Set(["USE_VERTEX_LIGHTING", "MODE_RENDER_DEPTH", "MODE_UNSHADED",
      "USE_ADDITIVE_LIGHTING", "ADDITIVE_OMNI", "ADDITIVE_SPOT", "RENDER_MATERIAL", "RENDER_MOTION_VECTORS"]);
    const directional = sceneDirectionalBase &&
      /^[ \t]*#[ \t]*define[ \t]+USE_ADDITIVE_LIGHTING\b/m.test(clean);
    let stockRevocationAt = -1;
    if (directional) {
      // The ONE pinned, inactive unshaded revocation is the only exception to
      // rejecting additive undefs. Excluded MODE_UNSHADED definitions below
      // still reject even in conditional branches. Mask for inspection only;
      // submitted shader text, predicates and shadow math remain untouched.
      const revocations = [...clean.matchAll(/^[ \t]*#[ \t]*ifdef[ \t]+MODE_UNSHADED[ \t]*\r?\n[ \t]*#[ \t]*ifdef[ \t]+USE_ADDITIVE_LIGHTING[ \t]*\r?\n[ \t]*#[ \t]*undef[ \t]+USE_ADDITIVE_LIGHTING[ \t]*\r?\n[ \t]*#[ \t]*endif[ \t]*\r?\n[ \t]*#[ \t]*endif[ \t]*\r?$/gm)];
      if (revocations.length !== 1) return [];
      const revocation = revocations[0];
      stockRevocationAt = revocation.index;
      clean = clean.slice(0, revocation.index) + revocation[0].replace(/[^\r\n]/g, " ") +
        clean.slice(revocation.index + revocation[0].length);
    }
    const flags = new Set();
    let depth = 0;
    for (const directive of clean.matchAll(/^[ \t]*#[ \t]*(\w+)\b([^\r\n]*)/gm)) {
      const [, command, tail] = directive;
      if (["if", "ifdef", "ifndef"].includes(command)) depth++;
      else if (command === "endif") { if (--depth < 0) return []; }
      else if ((command === "else" || command === "elif") && depth === 0) return [];
      else if (command === "define" || command === "undef") {
        const name = /^\s*([A-Za-z_]\w*)/.exec(tail)?.[1];
        // Even '#define USE_VERTEX_LIGHTING 0' activates stock #ifdef branches.
        // The pinned fragment conditionally UNDEFINES USE_ADDITIVE_LIGHTING;
        // it contains no conditional definition. C++ emits real enabled modes,
        // including BASE_PASS plus additive directional shadows, as defines.
        // Only the explicit directional-base option admits its unconditional
        // header define. Every other excluded definition still opts out.
        if (command === "define" && excluded.has(name) &&
            !(directional && name === "USE_ADDITIVE_LIGHTING")) return [];
        if (name !== "BASE_PASS" && !targets.includes(name) &&
            !(directional && name === "USE_ADDITIVE_LIGHTING")) continue;
        // Stock feature flags are unconditional object-like defines. Do not try
        // to evaluate arbitrary conditional/redefined/undefined macro programs.
        if (command === "undef" || depth !== 0 || flags.has(name) || tail.includes("\\") ||
            !/^\s*[A-Za-z_]\w*(?:\s+[^\r\n]*)?\s*$/.test(tail)) return [];
        if (directional && (name === "BASE_PASS" || name === "USE_ADDITIVE_LIGHTING") &&
            (directive.index >= stockRevocationAt || !/^\s*[A-Za-z_]\w*(?:\s+[01])?\s*$/.test(tail))) return [];
        flags.add(name);
      }
    }
    if (depth !== 0 || !flags.has("BASE_PASS")) return [];
    return targets.filter(name => !flags.has(name));
  }

  function transformSource(source, options) {
    const unchanged = { source, changed: false, loops: 0, specialized: false, addedDefines: [] };
    // No coercion, partial rewrite, shader-stage query or general GLSL optimizer.
    if (typeof source !== "string" || source.length > MAX_SOURCE_CHARS ||
        !source.includes("MAX_FORWARD_LIGHTS") || !source.includes("area_light_count")) return unchanged;
    const clean = source.replace(/\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g,
      comment => comment.replace(/[^\r\n]/g, " "));
    if (clean.includes("/*") || /["']/.test(clean) ||
        !/^\s*#version[ \t]+300[ \t]+es[ \t]*(?:\r?\n|$)/.test(clean) ||
        !/\blayout\s*\(\s*location\s*=\s*0\s*\)\s*out\s+vec4\s+frag_color\s*;/.test(clean)) return unchanged;
    const precision = [...clean.matchAll(/\bprecision\s+(\w+)\s+int\s*;/g)];
    const caps = [...clean.matchAll(/^[ \t]*#[ \t]*define[ \t]+MAX_FORWARD_LIGHTS\b([^\r\n]*)/gm)];
    if (precision.length !== 1 || precision[0][1] !== "highp" || caps.length !== 1 ||
        !/^\s*\d+u\s*$/.test(caps[0][1]) || Number(caps[0][1].trim().slice(0, -1)) > 0xffffffff ||
        /^[ \t]*#[ \t]*undef[ \t]+MAX_FORWARD_LIGHTS\b/m.test(clean) ||
        /^[ \t]*#[ \t]*(?:define|undef)[ \t]+(?:min|uint|i|omni_light_count|spot_light_count|area_light_count)\b/m.test(clean)) return unchanged;
    for (const kind of ["omni", "spot", "area"]) {
      const uniform = new RegExp(`\\buniform\\s+(?:highp\\s+)?uint\\s+${kind}_light_count\\s*;`, "g");
      const indices = new RegExp(`\\buniform\\s+(?:highp\\s+)?uint\\s+${kind}_light_indices\\s*\\[\\s*MAX_FORWARD_LIGHTS\\s*\\]\\s*;`, "g");
      if ([...clean.matchAll(uniform)].length !== 1 || [...clean.matchAll(indices)].length !== 1) return unchanged;
    }
    const prefix = /(\bfor\s*\(\s*(?:highp\s+)?uint\s+i\s*=\s*0u\s*;\s*i\s*<\s*)(MAX_FORWARD_LIGHTS)(\s*;\s*i\s*\+\+\s*\)\s*\{)(\s*)(if\s*\(\s*i\s*>=\s*(omni_light_count|spot_light_count|area_light_count)\s*\)\s*\{\s*break\s*;\s*\})/g;
    const candidates = [...clean.matchAll(prefix)];
    if (candidates.length !== 3) return unchanged;
    const edits = [];
    const counts = Object.keys(fingerprints);
    for (let index = 0; index < candidates.length; index++) {
      const match = candidates[index];
      const count = match[6];
      if (count !== counts[index]) return unchanged;
      const capStart = match.index + match[1].length;
      const open = capStart + match[2].length + match[3].length - 1;
      let end = open + 1, depth = 1;
      while (depth && end < clean.length) {
        if (clean[end] === "{") depth++;
        else if (clean[end] === "}") depth--;
        end++;
      }
      if (depth) return unchanged;
      const block = canonical(clean.slice(match.index, end).replace(/\bfor\s*\(\s*highp\s+uint\b/, "for (uint"));
      const kind = count.split("_")[0].toUpperCase();
      if (block.length !== 536 || fnv(block) !== fingerprints[count] ||
          !new RegExp(`#[ \\t]*ifndef[ \\t]+DISABLE_LIGHT_${kind}\\s*$`).test(clean.slice(0, match.index)) ||
          !/^\s*#[ \t]*endif\b/.test(clean.slice(end))) return unchanged;
      const guardStart = open + 1 + match[4].length;
      const guardEnd = match.index + match[0].length;
      edits.push({ start: capStart, end: capStart + match[2].length,
        text: `min(uint(MAX_FORWARD_LIGHTS), ${count})` });
      // Blank only the first equivalent if/break; retain diagnostic line numbers.
      edits.push({ start: guardStart, end: guardEnd,
        text: source.slice(guardStart, guardEnd).replace(/[^\r\n]/g, " ") });
    }
    // Specialization cannot bypass any of the existing stock-fragment guards.
    let addedDefines = missingSceneDefines(clean, acceptedContract(options), source, directionalBaseOption(options));
    if (addedDefines.length) {
      const version = /^\s*#version[^\r\n]*(?:\r?\n|$)/.exec(clean)[0];
      // Do not insert inside a block comment continuing past the version line.
      const versionPrefix = source.slice(0, version.length)
        .replace(/\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g, "");
      if (versionPrefix.includes("/*")) addedDefines = [];
      else {
        const newline = version.endsWith("\r\n") ? "\r\n" : "\n";
        edits.push({ start: version.length, end: version.length,
          text: addedDefines.map(name => `#define ${name}${newline}`).join("") });
      }
    }
    let result = source;
    for (const edit of edits.sort((a, b) => b.start - a.start))
      result = result.slice(0, edit.start) + edit.text + result.slice(edit.end);
    return { source: result, changed: true, loops: 3,
      specialized: addedDefines.length > 0, addedDefines };
  }

  function ownWrapper(target, name, wrapper) {
    const descriptor = Object.getOwnPropertyDescriptor(target, name);
    if (descriptor && !("value" in descriptor)) throw new TypeError("Accessor hook is unsupported");
    Object.defineProperty(target, name, {
      configurable: descriptor?.configurable ?? true,
      enumerable: descriptor?.enumerable ?? false,
      writable: descriptor?.writable ?? true, value: wrapper
    });
    return () => {
      if (Object.getOwnPropertyDescriptor(target, name)?.value !== wrapper) return;
      if (descriptor) Object.defineProperty(target, name, descriptor);
      else delete target[name];
    };
  }

  function install(canvas, options) {
    if (typeof root.HTMLCanvasElement !== "function" || !(canvas instanceof root.HTMLCanvasElement) ||
        typeof root.WebGL2RenderingContext !== "function") return () => {};
    const existing = installs.get(canvas);
    if (existing) return existing;
    const contract = acceptedContract(options);
    const sceneDirectionalBase = !!contract && directionalBaseOption(options);
    let active = true, bound = false;
    let restoreContext = () => {}, restoreSource = () => {};
    const stats = { pin: PIN, status: "waiting-context", shaderSourceCalls: 0,
      rewrittenCalls: 0, rewrittenLoops: 0, nativeFailures: 0,
      specializationPackSha256: contract?.packSha256 ?? null,
      sceneDirectionalBase,
      specializedCalls: 0, specializationDefinesAdded: 0, evidence: [] };
    const publish = () => {
      try { canvas.dataset.fastCompile = JSON.stringify(stats); }
      catch (_) { /* Optional diagnostics must never change a native result/error. */ }
    };
    const cleanup = () => {
      if (!active) return;
      active = false;
      try { restoreSource(); } catch (_) { /* A later owner may have frozen it. */ }
      try { restoreContext(); } catch (_) { /* Never overwrite another owner. */ }
      installs.delete(canvas);
      stats.status = "disposed";
      publish();
    };
    installs.set(canvas, cleanup);
    function bind(gl) {
      if (bound || !active || !(gl instanceof root.WebGL2RenderingContext) ||
          gl.canvas !== canvas || typeof gl.shaderSource !== "function") return;
      const original = gl.shaderSource;
      function shaderSource(...args) {
        if (!active || this !== gl || this.canvas !== canvas) return Reflect.apply(original, this, args);
        let result;
        try { result = transformSource(args[1], { contract, sceneDirectionalBase }); } catch (_) { /* Unknown input fails open. */ }
        const submitted = result?.changed ? [args[0], result.source, ...args.slice(2)] : args;
        stats.shaderSourceCalls++;
        try { return Reflect.apply(original, this, submitted); }
        catch (error) { stats.nativeFailures++; throw error; }
        finally {
          try {
            if (result?.changed) {
              stats.rewrittenCalls++;
              stats.rewrittenLoops += result.loops;
              if (result.specialized) {
                stats.specializedCalls++;
                stats.specializationDefinesAdded += result.addedDefines.length;
              }
              if (stats.evidence.length < MAX_EVIDENCE) stats.evidence.push({
                originalFnv: fnv(args[1]), transformedFnv: fnv(result.source),
                originalChars: args[1].length, transformedChars: result.source.length, loops: result.loops,
                ...(result.specialized ? { specializationDefines: result.addedDefines } : {})
              });
              publish();
            }
          } catch (_) { /* Do not mask shaderSource exceptions or return values. */ }
        }
      }
      restoreSource = ownWrapper(gl, "shaderSource", shaderSource);
      bound = true;
      stats.status = "bound";
      restoreContext();
      publish();
    }
    try {
      const original = canvas.getContext;
      if (typeof original !== "function") throw new TypeError("Canvas has no getContext");
      restoreContext = ownWrapper(canvas, "getContext", function (...args) {
        const result = Reflect.apply(original, this, args);
        if (active && this === canvas && args[0] === "webgl2" && result) {
          try { bind(result); }
          catch (_) {
            stats.status = "unavailable";
            try { restoreContext(); } catch (_) { /* Keep successful context result. */ }
            publish();
          }
        }
        return result;
      });
    } catch (_) { stats.status = "unavailable"; }
    publish();
    return cleanup;
  }

  return Object.freeze({ transformSource, install, pin: PIN });
});
