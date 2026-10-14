# Private lossless scene codec, v128

This is a project-specific **RSCC mode 5**, not a standard Godot resource codec.
Use `filtered-scene-codec-v128.patch` on the pinned Godot4.7.2 source commit
`ed1daf0bf001b61586d9930840f2f1394092c079`. It includes the exact inverse header
and the final partial-block fixes. Modes0–4 remain unchanged, so the original
and balanced packs keep their existing representation.

## Representation and reproduction

`godot/tools/build_filtered_scene_pack_v128.py` selects a reversible transform
per1MiB block before Zstd19. A one-byte filter selector precedes each Zstd frame.
Filters use byte planes and unsigned modular deltas; tails stay literal. The
builder independently reverses every transform and compares every decoded
resource byte. It also emits an equivalent stock-codec native-audit twin.

The exact C++ inverse was compiled and exercised as WebAssembly:2248 positive
roundtrips and288 negative/boundary cases passed. Those tests are recorded in
`artifacts/startup-v128/engine/filter-wasm-tests.json`. Matching-engine real Web
loading was separately checked; native twin tests alone do not validate this
private Web decoder.

Build and script inputs are pinned by the release manifests under
`artifacts/startup-v128/engine/`. Use only matching JS/WASM/worklets from one
reviewed template. An ordinary stock Godot template cannot read mode5. This is
for our trusted, build-verified packs, not a format for accepting third-party
resource uploads. Keep that boundary if implementing future integrations.

## Scope

Lossless means the **decoded resource bytes** are unchanged from the input to
this codec. The optional lite input has its own separately documented texture
and leaf-geometry LOD; this codec does not make lite identical to original.
The new edge-controller cache avoids rebuilding the same632 rooted sprays and
branchlets at startup. Its actual payload adds~0.61MB; it is a CPU/payload trade,
not additional compression saving.

Original/balanced assets and accepted water textures, materials and animation
remain unchanged. The position-quantization candidate is explicitly rejected:
small position errors changed some AO samples, so its~1.24MB gain is not shipped.

## Measurement boundary

Count the selected pack plus shared engine and host, using actual negotiated
compressed transfer. Navigation-relative `navigationReadyMs` includes HTML/helper
time. `loadMs` retains the earlier quality-start clock for comparisons. Both keep
the existing real-scene-ready, engine-start, two-RAF gate; neither is by itself
a physical GPU presentation timestamp. Do not report localhost, warm HTTP cache,
or headless-native preparation times as production cold-load performance.
