# Bounded Web module profile (v128)

Use [the profile](bounded-web-modules-v128.py) only with Godot 4.7.2 commit
`ed1daf0bf001b61586d9930840f2f1394092c079` and the existing
[lazy Web patch](lazy-web-variants.patch). The module profile itself requires no
additional C++ patch. The initial v128 build also incorporates main's
additive mode5 codec, pinned in the
[source extension](../../artifacts/startup-v128/engine/source-extension-02.json)
and [complete codec diff](../../artifacts/startup-v128/engine/main-mode5-source-02.patch).
Main's mode5-only short-tail reader correction and preallocation bounds are in
revision02. The successful incremental stabilization and frozen first release
are recorded in [HANDOFF.md](../../artifacts/startup-v128/engine/HANDOFF.md).
Offline checks are not a substitute for main's actual Web decoder/scene tests.
This profile is scoped to the audited original/balanced/lite world,
not arbitrary future projects or editor/import tools.

## Contract

The [keep/remove manifest](../../artifacts/startup-v128/engine/module-policy.json)
lists all 36 removed and 10 retained modules, with reasons. All three v127 packs
have 184 entries; their 32 CTEX textures use RGB/RGBA WebP. Shipped GDC identifier
tables and decoded resource bytes contain no removed-module class references.
The [audit](../../artifacts/startup-v128/engine/dependency-audit-02.json) records
actual pack and entry hashes, texture formats and script identifiers.

Retain full GLES3 rendering, every light/shadow path, meshes/materials,
animation/skeletons, 3D GodotPhysics3D, 3D navigation, complete GUI and advanced
text shaping/FreeType/MSDF/SVG. Retain PNG/WebP, core audio/WAV/generators and
audio effects, browser HTTP/HTTPS, JavaScriptBridge, JSON, cryptography and
WebSocket. Physics engine selection stays at the original GodotPhysics3D
default; no Jolt-to-Godot behavior switch is introduced.

Remove unused alternate image/media codecs, runtime model importers and mesh
processing, CSG/GridMap/visual-shader/noise modules, 2D physics/navigation, XR,
ENet/UPnP/WebRTC/high-level multiplayer, JSON-RPC, RegEx and ZIP support. New
content using these features requires another template. No global class
whitelist or project feature profile is used. Editor-only code was already
absent and is not claimed as a measured saving. Compression modes 0-4 and real
shader link checks remain unchanged; mode5 adds bounded lossless unfiltering.

## Reproduction

Reuse the isolated SDK from [v126 setup](../../artifacts/startup-v126/engine/REPRODUCE.md):
Python 3.12.4, SCons 4.9.1, Emscripten 4.0.11, compiler commit
`d3432e7a2a6585331c94b041973fb16c9f332ce4`. SDK download/provenance pins remain
in [acquisition.json](../../artifacts/startup-v126/engine/acquisition.json).
The [runner](../../artifacts/startup-v128/engine/run_build.py) records the exact
expanded command and child environment; its source directory is
`E:/Projects/Godot-Octopath2/.tools/godot-web-v126/src`.

```powershell
# From E:/Projects/Godot-Octopath2; requires the successful hash-bound audit.
& E:/Anaconda3/python.exe -B artifacts/startup-v128/engine/run_build.py
# Completed after main's reader correction and independent source pin update:
& E:/Anaconda3/python.exe -B artifacts/startup-v128/engine/run_build.py --log build-mode5-stabilize-02.log
```

This invokes the profile-equivalent explicit options, `-j4`, and linker
`--threads=4 --thinlto-jobs=4`, without a clean build. Child-only
`EMCC_CORES=BINARYEN_CORES=EMSDK_NUM_CORES=CMAKE_BUILD_PARALLEL_LEVEL=4`,
`BUILD_NAME=v128_trimmed_lazy`, `GODOT_VERSION_STATUS=stable` and
`EM_FROZEN_CACHE=1` prevent global setup and SDK cache changes. New scratch/logs
stay under the v128 artifact directory. Generated source-tree build outputs are
reused; the old v126 release/template and old artifacts remain frozen. For a
rerun choose a fresh log name with `--log`; never overwrite recorded evidence.

For a manually prepared identical child environment, the durable profile can
replace the expanded options: from the isolated engine source root run
`E:/Anaconda3/python.exe -B -m SCons profile=E:/Projects/Godot-Octopath2/godot/engine-patches/bounded-web-modules-v128.py -j4`.

The stabilization finished with exit0 in498.062 seconds. Frozen ZIP SHA256:
`fd37fd4c6e5d47e4cd687ee7b9294645519beb848e1a17f39334557b7ac94896`.
The first release preserves advanced text/MSDF and complete GUI; any later
text/GUI candidate uses a separate profile and artifact and must not replace it.

## Integration gate

Stage **matching JS and WASM from the same template ZIP**, with its worklets,
into a new version. Refresh transport/file-size metadata. Preserve PCK bytes
for an engine-only comparison. Audit any subsequently changed texture format
against the retained decoder set. Keep original/balanced/lite visual, motion,
day/night, water, walking, UI and full-ready tests in the main integration gate.

Neither module removal nor offline checks establish a 4 MB engine or a
10-second first load. Compare actual raw/gzip/Brotli bytes using identical
compression parameters and measure the complete ready milestone under the
same 20 Mbps / 80 ms HTTP-cache-bypass conditions. No GPU-cold assumption.
