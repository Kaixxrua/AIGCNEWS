# Reflection-probe SSAO depth-copy guard

Apply [reflection-depth-web-v128.patch](reflection-depth-web-v128.patch) to pinned
Godot 4.7.2, upstream commit
[`ed1daf0bf001b61586d9930840f2f1394092c079`](https://github.com/godotengine/godot/tree/ed1daf0bf001b61586d9930840f2f1394092c079).
It is a one-condition change in `drivers/gles3/rasterizer_scene_gles3.cpp:2705`.
Keep the existing lazy-variant and additive mode5 patches unchanged.

## Contract

SSAO's forced `used_depth_texture` request applies only to non-probe views,
because the Compatibility renderer skips SSAO post-processing for reflection
probes. Material-requested depth reads remain set independently; the patch does
not clear them or suppress any GL validation. Main-view SSAO, water/focus depth,
probe captures, all shader loops, render formats and quality settings are unchanged.
This is not a general solution for depth-reading materials inside a probe.

Original C++ SHA256:
`6d0719c9cd2caf685a9825028183bdf058081d7bc92d4b27ed2587f39b081221`.
Patched C++ SHA256:
`5df472583b1e9f3ba74ea2a584fb1e85ae0550432017a66342ba83811dc64239`.
Patch SHA256:
`9363796de7d4481d008de546c1694396c981d2456b07afdaf505c26b6ce7d7b5`.

## Reproduction and verification

Use the same isolated Python 3.12.4 / SCons 4.9.1 / Emscripten 4.0.11 toolchain
and exact command array in
[text-GUI build](../../artifacts/startup-v128/engine/text-gui-01/build.log.json).
No feature-flag changes. `BUILD_NAME=v128_text_gui_lazy` is intentionally retained
to avoid unrelated generated-version rebuilds; identify this candidate by hashes.
SCons, linker, ThinLTO, EMCC and Binaryen worker caps are all four. No global SDK
activation, cache clean or duplicate full build.

[Candidate runner](../../artifacts/startup-v128/engine/reflection-depth-01/run_reflection_build.py)
has separate `prepare` and `build` operations. Run `prepare` before applying this
patch, apply via the normal patch tool, then run `build` once. The source root is
`.tools/godot-web-v126/src`; the runner uses the exact prior command rather than
reconstructing module flags. Existing releases are copied/pinned, never replaced.

Run the durable scope tests from the project root:

```powershell
& E:/Anaconda3/python.exe -B godot/engine-patches/test_reflection_depth_web_v128.py
```

Tests pin the exact inverse source diff, unchanged actual-depth-consumer branch,
main/probe/material truth table, excluded probe post-pass, module flags/classes,
mode5 and lazy shader/loop source. The collector also checks every original
upstream file, frozen game scripts/shaders/scenes/config/textures and old releases,
actual build exit, paired JS/WASM syntax/module/instantiation and compressed sizes.
It does not fake a GL context or claim a rendered-frame pass.

Stage only the matching JS/WASM/worklets from the candidate ZIP described in
`artifacts/startup-v128/engine/reflection-depth-01/engine-manifest.json` after it
exists and records successful checks. Main owns whole-frame/day/night/water and
warning-absence testing. No performance claim; v127 already showed the same six
warnings. See [diagnosis](../../artifacts/startup-v128/depth-blit-diagnostic.md).
