# Web shader variant scheduling patch

[lazy-web-variants.patch](lazy-web-variants.patch) is the byte-exact v126 patch
for upstream Godot **4.7.2**, commit
[`ed1daf0bf001b61586d9930840f2f1394092c079`](https://github.com/godotengine/godot/tree/ed1daf0bf001b61586d9930840f2f1394092c079).
Apply it to an isolated upstream engine source root, not this game's `godot/`
directory. Patch SHA256:
`8e07b9ed39dab725dc209ced6bc9d73cb0b2167b3379f8a5437aefd75e25af09`.

## Invariant

Only `ShaderGLES3::_initialize_version` changes. On Web it constructs every
variant-map slot without eagerly compiling default specializations. The
unchanged `_version_bind_shader` synchronously compiles the exact requested
variant and full specialization mask on first use, including defaults when
requested. Real compile/link checks, failures and uniform setup remain intact;
the native eager-compilation/cache branch is unchanged. No shader, light/shadow
mask, GUI or module is removed. Later first-use work can still stall; this
document makes no performance claim.

## Exact tested build

Toolchain: Python **3.12.4** (`E:/Anaconda3/python.exe`), task-local SCons
**4.9.1**, Emscripten **4.0.11** (compiler commit
`d3432e7a2a6585331c94b041973fb16c9f332ce4`). The emsdk launcher is pinned to
`5eb0bde7585670252e8ba05e9d361627bffd08b5`; SDK binary release:
`7033fec38817ec01909b044ea0193ddd5057255c`.

From `E:/Projects/Godot-Octopath2`, after the isolated setup and patch application
described in [reproduction steps](../../artifacts/startup-v126/engine/REPRODUCE.md):

```powershell
& E:/Anaconda3/python.exe -B artifacts/startup-v126/engine/run_owned.py --cwd E:/Projects/Godot-Octopath2/.tools/godot-web-v126/src --log build-release-01.log -- E:/Anaconda3/python.exe -B -m SCons platform=web target=template_release threads=no arch=wasm32 production=yes lto=thin optimize=size debug_symbols=no use_closure_compiler=no javascript_eval=yes dlink_enabled=no wasm_simd=yes progress=no "linkflags=-Wl,--threads=4 -Wl,--thinlto-jobs=4" -j4
```

The [runner](../../artifacts/startup-v126/engine/run_owned.py) sets child-only
`BUILD_NAME=v126_lazy`, `GODOT_VERSION_STATUS=stable` and
`EMCC_CORES=BINARYEN_CORES=EMSDK_NUM_CORES=CMAKE_BUILD_PARALLEL_LEVEL=4`.
Compilation, linker and ThinLTO caps are all four. SDK, Python search path,
cache and temporary paths remain local; no global activation is required.
Default Web features/modules remain enabled. The recorded build exited **0**;
the runner refuses existing logs, so a replay needs a fresh log name.

## Integration and provenance

Always stage matching **JS and WASM from this same build**, with its audio
worklets. Never combine custom WASM with stock JS. Refresh file-size/compressed
sidecars; retain the identical v125 PCK and helper for engine-only comparison.
Scene, day/night, shadow and water acceptance still requires the main Web test.

The tested template ZIP is recorded in the
[release manifest](../../artifacts/startup-v126/engine/engine-manifest.json), SHA256
`c0a30de5fa926d03de79fcc1fbada68f5144011f9821ede35c7eb91a55f4c797`.
See [acquisition provenance](../../artifacts/startup-v126/engine/acquisition.json),
[build command/exit record](../../artifacts/startup-v126/engine/build-release-01.log.json),
[invariant review](../../artifacts/startup-v126/engine/INVARIANTS.md),
[source proof](../../artifacts/startup-v126/engine/post-build-source-tree-proof.json),
[scheduling tests](../../artifacts/startup-v126/engine/scheduling-tests.json) and
[JS/WASM validation](../../artifacts/startup-v126/engine/module-validation.json).
Emscripten was pinned from upstream CI, not recovered from stripped stock WASM;
this is not a claim of byte-reproducible stock compilation or a perfectly
toolchain-controlled A/B. Offline tests do not establish browser performance.
