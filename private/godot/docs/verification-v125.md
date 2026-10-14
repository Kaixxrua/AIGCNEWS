# v125 — measured startup bottleneck and bounded shader mitigation

Date: 2026-09-11. Local Windows workspace only. Preview:
[v125 lite](http://127.0.0.1:4231/v125/index.html?quality=lite&rev=1).

## Outcome and limits

The dominant download-complete stall is synchronous WebGL program-link/status
waiting during Godot's first render. It is not primarily PCK download, texture
upload, filesystem copying, or the optional scene audit. The selected lite build
reduces shader complexity without reducing actual lights, shadows, objects or
texture quality relative to v117 lite. QHD day/night checks pass visually.

This is a **partial startup mitigation, not a solved fast-loading contact page**.
Final normal, trace-off runs took **78.827s and 50.588s** to the existing ready /
two-RAF presentation milestone. First night still took **22.274s** to that
transition's presentation-opportunity marker. Do not hide these residual waits
or advertise a stable 42-second result, instant opening, or a production SLA.

## Root-cause evidence

- [Baseline trace 02](../../artifacts/v118/startup-trace-02.json): 302.350s ready,
  281.445s inside `getProgramParameter` across 284 calls. These are measured
  synchronous driver-call wall times, not exclusively compiler CPU time.
- `callMain` entered at 3674.2ms and returned at 291906ms on the trace clock;
  scene-ready was signalled at 22469.5ms, well before engine start returned.
  `copyToFS` took about 30ms. Texture/buffer uploads were about 0.1s each.
- Actual renderer: ANGLE / NVIDIA GeForce RTX 3060 Laptop / D3D11, not a
  software-renderer assumption. 143 programs and 286 shader submissions.
- Pinned Godot source commit `ed1daf0bf001b61586d9930840f2f1394092c079`:
  `platform/web/web_main.cpp` runs the initial callback synchronously;
  `drivers/gles3/shader_gles3.cpp` initializes default variants and waits for
  link status; `shader_gles3.h` has its async queue branch disabled. The native
  shader-cache path does not provide a Web cache workaround.
- Source files and exact URL/hash pins are retained in
  [engine-reference](../../artifacts/startup-v118/godot-analysis/engine-reference/pins.json).
  RenderingDevice pipeline flags are not a verified solution for this GLES path.
- The optional full audit cost roughly 0.453s in the earlier probe, and normal
  v125 reports it skipped. Removing that audit alone cannot fix this stall.

## Implemented changes

1. `meadow-loader.js` keeps WASM init and pack transfer concurrent and preserves
   genuine engine-start, scene-ready and two-RAF gates. It automatically installs
   the bounded compiler helper only for the selected pack's verified contract.
2. `meadow-webgl-compile.js` rewrites only three fingerprinted stock Godot 4.7.2
   forward-light loops to equivalent runtime bounds. For eligible BASE_PASS
   fragments, it also disables the two light types absent throughout this scene:
   Spot and Area. Actual directional/Omni lighting and shadows remain.
3. The selected derived lite PCK hoists light-independent cloud transmission into
   a fragment-to-light varying and changes three material loops to equivalent
   runtime bounds. The contact-shadow count remains 72; no contacts are removed.
   The combined transformation explicitly composes both passes on shared files.
4. `meadow-startup-trace.js` is opt-in (`startup_trace=1`) and absent from the
   final normal run's runtime hooks. It records actual boundaries and WebGL
   waits, not fabricated progress. Time-switch instrumentation distinguishes
   logical acknowledgement from the later two-RAF opportunity.
5. Builders stage immutable version directories, retain variant provenance and
   compute contracts from actual PCK bytes. No source art or main scene edits,
   full exports, original-tier re-encoding, extra services or SSH were used.

The WebGL hook is context-local, validates source fingerprints, preserves real
native return values/errors, and fails open for unrecognized sources. It stays
installed after ready for first-use night variants, and is cleaned up on fatal
startup errors. This is not a replacement for a general shader compiler.

### Eligibility and fallback

The normal main scene has 144 nodes, four directional lights, nine Omni lights,
zero Spot lights and zero Area lights. Construction and day/night lifetime were
independently audited, including direct rendering-server/dynamic creation paths.
Night changes existing lights rather than creating a new light type. The lantern
retains its night shadow toggle. The proof does not cover future Boss content.

- Selected combined pack SHA256:
  `3255a33ff20e6a778d5191c584aa254b35a999c8e5fd9c853a8a0053582e447c`.
- The other eligible hash is unchanged v117 lite:
  `018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79`.
- Original, balanced and unknown/new packs default to stock: no automatic hook.
  New scene/light content changes the pack hash and requires a fresh audit.
- `fast_compile=0` explicitly restores the stock-host path. `=1` is loop-only;
  `=scene` requests contract mode. Unknown explicit values are off. Queries
  cannot provide trusted hashes or light counts. Opt-out/loop-only paths do not
  depend on reading the optional scene-contract registry.
- The helper does not rehash network bytes itself. This assumes the complete,
  immutable version directory prepared from the verified files. Do not overwrite
  a PCK in place under an old HTML contract.

[Combined resource/native proof](../../artifacts/startup-v118/independent/combined-01-review.md),
[zero-type lifetime proof](../../artifacts/startup-v118/independent/zero-unused-light-contract-review.md),
[later contract/trace validation](../../artifacts/startup-v118/independent/v117-zero-unused-light-contract.md).
The later validation supersedes the earlier stale-v123-helper observation.

## Measured experiments, not controlled cold-device benchmarks

| Build / treatment | Ready seconds | GL program-query wall seconds |
| --- | ---: | ---: |
| v118 baseline, trace 01 | 296.237 | 278.727 |
| v118 baseline, trace 02 | 302.350 | 281.445 |
| v119 hoist only | 101.214 | 88.258 |
| v120 stock pack + loop helper | 212.649 | 198.007 |
| v121 hoist + loop helper | 98.730 | 84.895 |
| v122 combined pack + loop helper | 214.503 | 197.306 |
| v123 combined + zero-type specialization | 42.579 | 28.895 |
| v124 unchanged v117 pack + specialization | 75.743 | 60.249 |
| v125 normal, trace OFF, run 1 | 78.827 | not instrumented |
| v125 same URL, trace OFF, run 2 | 50.588 | not instrumented |

The isolated loop/hoist experiments are not separately accepted speed solutions.
Combined + specialization was retained for final normal and visual checks; its
normal-run variability prevents claiming that the earlier 42.579s is stable.
These different runs have uncontrolled driver/shader/code-cache state, with some
earlier canvases 1280x800/DPR~1 and others 1920x1200/DPR1.5. Unchanged source groups
also had widely varying waits. Do not infer causal percentages by subtraction.
Neither HTTP-cache testing nor localhost transfer speed establishes cold-device
or real-network production performance.

Final normal evidence:

| Milestone (ms) | Run 1 | Run 2 |
| --- | ---: | ---: |
| Pack fetched | 1590 | 1646 |
| WASM init | 1175 | 1668 |
| Runtime start | 1590 | 1671 |
| Scene signal (controls clock) | 11966 | 10110 |
| Engine start returned | 70543 | 48946 |
| Ready / presentation opportunity | 78827 | 50588 |
| Hidden time | 0 | 0 |

Both normal starts used canvas 1920x1200, DPR1.5, visible page, lite scale0.5,
day0/clock0/paused. Trace data was absent, default specialization was active:
286 submissions,117 rewritten calls,351 loops,32 specialized calls/64 defines,
zero native-submission exceptions. One lite pack and one WASM fetch only; no
original/balanced background downloads. Milestones have documented different
origins and overlap: do not add them or equate progress callbacks with network.

[Run 1](../../artifacts/v125/startup-normal-01.json),
[run 2](../../artifacts/v125/startup-normal-02.json).

First night: logical acknowledgement48ms, two-RAF opportunity22274ms. This is
not a 48ms visible transition. Input changed display scaling to3840x2160/DPR1.5,
so this is an observed first-use wait, not a matched performance benchmark.
The hook correctly remained active:348 submissions,148 rewrites,36 specialized
calls/72 defines. QHD capture afterward confirmed the actual night image.
[First-night evidence](../../artifacts/v125/first-night-transition.json).
Return to day with animation also succeeded (7.702s opportunity marker in that
run), with additional first-use shaders. Neither transition is declared fast.

## Visual and functional acceptance

Main inspected original-size PNGs personally, not just test pass counts:

- [Day QHD](../../artifacts/v125/day-lite-2k.png) and
  [night QHD](../../artifacts/v125/night-lite-2k.png), both actual2560x1440 PNGs
  and actual2560x1440 canvas, DPR~1. Full16:10 scene has side letterboxing,
  complete castle, near cliff and right tree. Not a tiled/cropped capture.
- These are QHD captures of the **lite tier**, whose internal3D scale is0.5;
  they are not a claim of native-QHD3D texture/detail quality.
- Clock0, paused, day0/night1 matched the frozen lite captures. Composition,
  textures, water appearance, moonlight, lamp/window halos and stars are intact.
- Day regional RGB comparison: meadow, water and right tree pixel-exact;
  full-frame99.8174% of pixels within one channel level. Night castle exact;
  meadow/water/right-tree all within one level, full-frame99.8142%. Small full
  differences include non-deterministic creature/dragon pose and control focus.
  Metrics supplement inspection; they are not a universal perceptual guarantee.
- [Day metrics](../../artifacts/v125/day-pixel-metrics.json),
  [night metrics](../../artifacts/v125/night-pixel-metrics.json).
- Animation was enabled through the real button. Clock advanced58.338→121.488;
  [motion QHD](../../artifacts/v125/night-motion-2k.png) shows changed dragon
  pose/location, moving luminous stag, displaced clouds and changed water flow.
  [Motion state](../../artifacts/v125/night-motion-state.json). No browser
  warnings/errors in the final inspected log. Returned to day with motion on.
- Native independent comparison11/11 passes: camera/FOV,5 colliders and open
  walk/Boss space,4 fauna species with8 frames, varied dragon poses, water and
  render settings. This headless proof does not substitute for Web visuals.

Browser viewport/CDP overrides were cleared after capture. Ordinary preview
size restored; original user tabs were not closed.

## Regression and payload

Final delegated regression results: Web174/174; build contracts11/11;
transport19 passed,1 Windows-symlink-privilege skip. Independent contract65/65;
shader builder49/49 with20 old/new shader-language validations. No new service
was started for transport tests (in-memory handler adapter).

All184 pack entries are bound:178 byte-exact to v117, six intentionally modified
shader resources. Scripts, scenes, textures, water/sky code and render settings
are exact. New contact-shadow iteration default72 and absence of overrides were
checked; do not mistake this for direct GPU uniform readback.

v125 lite pack44,327,612 bytes; gzip39,340,280 bytes. Shared+lite prepared gzip
payload49,540,435 bytes (decimal49.54MB, not all HTML/protocol overhead). This pass
targets post-download startup, **not another meaningful download-size reduction**.
Actual existing server HEAD returned200, Content-Encoding:gzip and
Content-Length:39340280. Brotli files are prepared, but this server serves gzip.
PowerShell's automatically decoded HEAD view suppressed those fields; raw curl
HEAD and browser encoded-body timings provide the actual encoding evidence.

All seven frozen original files passed post-staging hash checks, including:

| File | SHA256 |
| --- | --- |
| original PCK | `02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d` |
| balanced PCK | `68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33` |
| WASM | `fc74679e3b97f76878947fcd4fbe1268cbfa6188182a2e33bbc3f5dc9bfa57d0` |
| engine JS | `33c94cb3175f3333b82e2a3be5e8e86f77986f0aa2042b1631f6367a4e5bb6ba` |

Current/staged host hashes match: loader`f61eec43…`, helper`0360263e…`.
Pack provenance, manifest and frozen hashes remain alongside the preview.

## Remaining work

1. Remaining synchronous first-render and first-night variant compilation must
   be reduced or scheduled without lying about readiness. This likely requires
   a bounded GLES engine/variant-scheduling change and another physical/visual
   acceptance cycle, not more texture recompression or a progress-label change.
2. Validate performance on a genuinely cold browser/device and controlled
   production-like network. Do not clear the user's browser/profile/driver
   caches to manufacture that test without a separate isolated test setup.
3. Keep the future scene contract hash gate when Boss/person assets are added;
   do not blindly reuse the zero-type proof for new lighting content.

No AIGCNEWS deployment, Boss implementation, Git reset/commit, recovery-source
mutation or artwork regeneration was part of this pass.
