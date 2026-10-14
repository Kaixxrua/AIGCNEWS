# Progressive first load: v153 bounded core target verified

## Acceptance boundary

The user prioritizes a usable real-time Godot core within 10 seconds. The
working test is 20 Mbps down / 5 Mbps up, CDP latency 80 ms, HTTP cache bypass,
foreground canvas 2560×1440 / DPR approximately 1. Controlled timing uses day,
clock zero and paused motion. GPU/driver shader caches are **not cleared**.
This is neither a production measurement nor an every-network/device SLA.

The ready gate remains actual main-scene ready + engine start + two animation
frame boundaries. The engine-only bootstrap never emits scene-ready. Dense
vegetation, full textures and visual mesh detail may arrive afterward; their
completion is independently reported after Godot applies and renders them.

## Frozen inputs and restoration

- v134 original PCK: `02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d`.
- v134 balanced PCK: `68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33`.
- v134 lite PCK: `61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3`.
- Shared WASM: `52d3ad52fd004291970d1ef02b0f818500f4f57500e20aadcb911373e4a78716`.

Derived optional lite artifacts change; the authored main scene, accepted art
and original/balanced packs remain frozen. v146 additionally tests a separately
reviewed shared-engine change, documented below. The private compiled main has
a progressive-controller hook and explicit proxy-AO guard.

Candidate07 retains full collision shapes and CPU support queries; the two
temporary meshes are replaced in-place with the full meshes. Nine deferred
vegetation roots preserve parent/order. Thirty texture objects are upgraded
in-place, preserving object identity, atlas registration and material links.
Water retains its accepted shader/flow and receives its exact full texture in
the final chunk. Reflection/focus resume after all twelve chunks are applied.

Eight small CPU-only alpha planes preserve the original `a > .60`, `a > .9`,
`a > .95` results at full source dimensions. Their continuous alpha values are
intentionally NOT identical; they are not used as visible texture assets.
Independent actual-native verification covered 37,745,940 predicate outcomes,
derived geometry, all five colliders, full texture restoration and day/night.
See `artifacts/startup-v135/support/candidate-01/HANDOFF.md` and its indexed
candidate07 validation proofs.

## Measured candidates, not passing samples

| Build | Change | Bounded cold core | Status |
| --- | --- | --- | --- |
| v134 | Previous full lite | 23.339 s | Historical baseline |
| v138 | Core + eight detail chunks | 15.369 s | Diagnostic log truncated |
| v140 | Smaller textures, CPU predicates, engine/bootstrap overlap | 12.550 / 12.192 s | Over budget |
| v141 | Temporarily deferred cast shadows / SSAO / glow | 17.850 s | Rejected; first shader compilation worsened |
| v142 | Proxy03 and 17 exact static meshes | 11.600 s | Over budget; diagnostic log truncated |
| v143 | Proxy04 precision, 50 optional root caches, AO bin deferred | 13.178 / 12.739 s | Over budget; second log complete |
| v145 | Current host, original shared engine, exact core10 | 12.920 s | Over budget; complete log |
| v146 | Same core/boot, deferred Web shader-stage diagnostics | 11.283 s | Over budget; complete log |
| v147 | Same engine/core, engine-first download schedule | 11.010 s | Over budget; complete log |
| v148 | Temporary quarter-resolution core, restored at first detail | 11.596 s | Rejected; no speed gain, controller reverted |
| v149 | Sky-only equivalent loop bound, original half-resolution | 11.430 s | No demonstrated gain; not integrated |

v140 core is 7,954,244 raw bytes and 7,765,752 transferred Brotli bytes.
Required WASM is 5,248,696 Brotli bytes; bootstrap is 4,070 Brotli bytes.
These figures exclude page JS/CSS/HTML/headers and deferred detail traffic.
v140 second run reached full detail at 29.235 s. No ≤10 s claim is made.

`v140-cold-diagnostic-02.json` has an untruncated request/response/finished log.
Its 4 KB bootstrap produced a legitimate sub-millisecond response-notification
timestamp inversion; the stricter analyzer needs actual headers-end evidence
before accepting that chain. This does not change its over-budget core time.

The v141 temporary lighting experiment was reverted from maintained sources.
Its immutable artifact is preserved for diagnosis, not user delivery.

Candidate10/v143 core is 6,990,628 raw / 6,669,938 Brotli bytes. Original AO
data (318,544 bytes) moves unchanged from core to chunk10, alongside the exact
full visual meshes. The optional root cache adds 50 memoized meshes and a
two-line private-main hook; its exact original fallback remains intact. The
static dependency manifest is repinned only to the actual compiled main GDC.
Actual native/twin candidate10 regression passes 17+50 hits, five unchanged
colliders, all twelve chunks, thirty in-place textures and unchanged thirteen
lights. The opt-in v144 Web probe subsequently confirmed 49/50 root hits. The
single exact-context miss was LivingMeadowGroup_05 position.y: a 3.5763e-7
difference, with all other input fields unchanged. Its original fallback is
retained; no tolerance was loosened to manufacture fifty hits. Probe/trace
URLs are diagnostic only and the final analyzer rejects them.

`v143-cold-diagnostic-02.json` continuously collects before navigation through
the DOM snapshot at 200 ms polling intervals; it is untruncated. Its 12.739 s
navigation-relative ready time remains an honest failure. Earlier candidate
files and failing measurements are preserved, not substituted with warm runs.

## Visual and regression checks so far

- `v140-full-day-2k.png`: saved native PNG and canvas both 2560×1440, full
  composition and bars inspected. Final terrain, trees, buildings and water
  visually agree with the v134 lite direction. Historical v134 dragon phase
  differs, so this is not a pixel-identical animation comparison.
- The full-scene day/night button still changes the actual scene and state.
- 109 compile/contract/bootstrap JS tests passed; 119 controls/quality/detail/
  startup-boundary JS tests passed after updating the diagnostic label cap.
- Independent native candidate07 full-scene restoration passed; headless
  checks are not a substitute for Web visual/presentation acceptance.

## Reviewed engine scheduling candidate

`engine/deferred-validation-01` contains the source proof, one capped build
(440.687 s / exit0), paired JS/WASM instantiation and unchanged memory/module
proofs. Only shader_gles3.cpp was recompiled. On Web, the successful path uses
the actual LINK_STATUS of both attached stages; a failed link still diagnoses
both stages and performs the original cleanup. Seven standalone source/mock-GL
tests passed, including byte-identical non-Web paths. This is not a fabricated
status or an early ready signal. Per-stage synchronous checks are deferred to
the failed-link path; shader source and rendering math do not change.

- WASM: `1bf0d192b97645d76e31fbb7582e3c112981a1e420d5d976ae71757866ee92e1`.
- JS: `96a4fbc94381a8e0c12362f7379f2febc775cf016175e2632820c5f6311195be`.
- Actual engine transfer: 5,249,199 Brotli bytes, not an important size saving.
- v146 instrumented run: zero stage-status checks on success; actual program
  checks remain (1,774.6 ms total). Its 11.435 s traced time is not a final sample.
- Actual complete v146 day/night QHD frames were personally and independently
  inspected against v140: no obvious missing assets, lighting regression or
  framing change. Night switching reached blend1; full detail was12/12.
- `stage_engine_web.py` now carries and validates every progressive chunk and
  bootstrap, including prepared size/hash records: 38 tests pass.

v147 gives WASM/init bandwidth before fetching the core, then overlaps the
engine's CPU bootstrap with that core transfer. It does not change readiness.
Its small measured improvement alone does not establish a general scheduling
win on other networks/devices. Both controlled samples remain over budget.

The temporary-resolution controller is restored byte-exact to source
`b02effb14cd07fe8df500319513f6aaf7dd25809cbd9367bc8da0450bb6ecd6f`.
Candidate12's native/twin audit passed but explicitly did not exercise its
Web-only scale branch. Its actual Web timing failed to justify the quality
change. Candidate11's sky overlay is likewise not selected for delivery.

The bootstrap's existing incomplete 90-second timeout was independently fixed:
one overall deadline now covers every await stage, stale callbacks/completions
cannot resume startup, and core fetch has a real AbortSignal. On timeout the
user reloads; no second engine is started in the same page. All247 host JS
tests passed, including22 bootstrap deadline/negative tests.

A proposed additional two-include loop composer was refused before writing any
candidate13 output: the ACTUAL core already contains those equivalent bounded
window/architecture loops and differs from the working source includes. This
is not a remaining optimization; input hash checks correctly prevented an old
shader from overwriting the reviewed packaged lighting code.

## Selected v153 result

Preview: <http://127.0.0.1:4231/v153/index.html?quality=lite&rev=1>.
This is the optional **lite** tier; original and balanced remain available.

Three samples were selected before execution, with the same URL, foreground
QHD canvas, fixed day/clock/paused motion and the network conditions above.
The existing analyzer and an independent reviewer both accept all three:

| Saved sample under `artifacts/startup-v135` | Navigation to real core ready |
| --- | ---: |
| `v153-target10-01.json` | 9,877 ms |
| `v153-target10-02.json` | 9,593 ms |
| `v153-target10-03.json` | 9,844 ms |

`v153-target10-main-report.json` reports `PASS`, `bounded3of3: true`,
`corePassCount: 3`, with no rejected conditions. The analyzer was not relaxed
to obtain this result. Each complete CDP log contains exactly one successful
200/full-body WASM, bootstrap and core transfer, no cached bodies, no other
quality pack and no duplicate WASM preload. The only pending request at the
core snapshot is detail traffic that starts after core readiness.

The narrowest margin is **123 ms**. HTTP cache bypass does not clear driver/GPU
shader caches. Controlled timing pauses motion to match phase; it does not
establish an all-motion, every-device benchmark. Two RAF boundaries and real
engine/scene-ready signals are not proof of the time of physical display
presentation. This is a shaped localhost measurement, **not a deployed
production measurement or a universal ten-second guarantee**.

The first scene is visibly lower-detail, not the accepted final-quality image.
Full lite textures, dense vegetation and detailed meshes load and apply in
the background. Sample 03 reached all **12/12 detail chunks at 27,380 ms**
from navigation (`v153-full-day-2k.json`). Do not describe this result as
"all assets downloaded/full quality within ten seconds" or as a poster load.

### Size and frozen inputs

- Initial prepared Brotli payload: **11,290,640 bytes** (11.29 decimal MB),
  comprising 4,532,767 bytes of shared engine/interface and 6,757,873 bytes
  of core/bootstrap. HTML and response headers are excluded.
- Actual WASM body: **4,448,037 bytes**; actual core body: **6,753,803 bytes**;
  actual bootstrap body: **4,070 bytes**. These are compressed transfer sizes,
  not raw texture/render-resolution estimates.
- Candidate15 mode5 core: `4c170ff401f2855fd7f14f1a0f6c53b20fb136b174421dedae4e8f148f16106c`,
  6,968,456 raw bytes. Native twin:
  `8d7a9e04209cd0154029634d7d8a8c92b90d5ec7f009b821bb1e4b4afe86df95`.
- Boot15: `fd5727057ca877d5d4efb6635495df5a80926a85195d4766d090a4f08c162885`;
  all twelve full-detail chunks remain byte-exact to candidate10.
- v153 original PCK remains
  `02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d`;
  balanced remains `68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33`.
  The reviewed shared engine changes above apply to all tiers; their PCKs do not change.

### Changes that crossed the remaining budget

1. Preassemble the fixed static world offline, then restore its real live
   controllers, resource aliases and typed arrays before the original dynamic
   tail executes. A thin three-node entry avoids first rebuilding the old
   world and then duplicating it. The restore contains 124 static nodes,
   preserves all five full colliders, rebinds windmill/weather/night groups,
   and keeps the original edge-growth initialization order. It does not
   replace the Godot scene with a flat image.
2. Start downloading the shared WASM from the document head only for an
   explicit recognized quality query. No pack is fetched by this hint; the
   chooser without an explicit query does not trigger it. The actual cohort
   proves the later engine fetch reuses this request without a second transfer.
3. Recompress the unchanged engine losslessly with Brotli quality11. Its
   4,448,037-byte sidecar saves 801,162 bytes versus the previous quality6
   sidecar. Raw WASM/JS and rendering math are unchanged by compression.

The quality11 sidecar SHA is
`d04c9aede11842cce88dca647a15812d2514037858e8a02727fc0d068e0d089e`.
`prepare_web_build.py` and `stage_lite_web.py` now validate the pinned raw
WASM, sidecar, proof and decoded equality before staging. Known inputs with
missing/corrupt proofs fail closed; an unrelated new engine without an
explicit verified sidecar follows the existing quality6 policy. Existing
approved bytes/mtime are preserved. No costly recompression is needed for
each new version.

The selected private restore guard permits only the exact core project hash
or the exact bootstrap project hash. Their records were independently checked:
only the initial `main_scene` value differs, and the effective scene is
restored to `res://scenes/main.tscn` before loading. Other dependencies and
effective settings remain guarded. This repairs the actual v150 bootstrap
guard failure; it does not turn a validation failure into a fake ready event.

Historical v150 guard failure, v151 10.082 s and v152 9.978 s diagnostics are
retained. v152 alone was not accepted as the three-run result. Rejected
quarter-resolution/shadow experiments are not part of v153.

### Independent native and visual acceptance

Actual candidate15/source10 native runs cover 18 day/night/detail phases,
145 nodes, all five colliders, four directional and nine omni lights, routes,
CPU support predicates, in-place texture aliases and all twelve full chunks.
No spot/area lights are present; the light-only specialization is hash-gated
to the actual reviewed core. Unknown/original/balanced packs retain their
normal behavior.

The strict bitwise native comparison remains **FAIL**, not silently relabeled:
small village/rotor transforms, derived village vertex/soil values and light
floating-point values differ. A separate actual-array probe quantified the
maximum world-space vertex difference as **0.018 mm**; all village indices,
normals, tangents and UVs are exact. Key-light/cloud differences are at most
one ULP. Colliders, routes and resource aliases agree. The main agent accepts
these visually negligible differences after measurement and full-frame review,
not as a claim of bit-identical geometry. Proofs and unchanged strict failures
remain under `independent/static-core/actual15-native-03` and
`independent/static-core/village-arrays-01`.

Main and independent reviewer inspected `v153-full-day-2k.png` and
`v153-full-night-2k.png` against v151: no obvious final scene, framing, lighting
or approved-water regression. Saved PNG and canvas are both 2560×1440 with
the established 16:10 scene letterboxed inside the frame. Lite's internal
3D scale remains 0.5; this is not a claim of native QHD 3D shading resolution.

`v153-core-day-2k.png` is a **core-stage/first-detail-applying** frame, not a
strict zero-chunk or physical-first-frame capture. Mountains/castle are blurry
and terrain detail coarse at this stage, but the main layout is recognizable;
no all-black textures, fake transparent backgrounds or fatal missing region
was found. This is accepted only as temporary core quality.

Actual controls also verified:

- Motion resumed: moving clouds, dragon, luminous wildlife and water were
  observed in `v153-motion-night-a.png`; the subsequent day transition
  completed with motion still running.
- Deliberate network loss after core readiness leaves day/night usable.
  `v153-offline-controls.json` records the real night transition with a detail
  error. Restoring the network and pressing retry completes 12/12 chunks
  without resetting the night state (`v153-retry-recovered.json`). This
  intentional failure is not counted as a target10 sample.
- Original and balanced were selected through the real quality dialog, each
  loaded successfully and completed a day-to-night transition with animation
  running. `v153-original-functional.json` and
  `v153-balanced-functional.json` record these unthrottled functional checks;
  their timings are explicitly excluded from the target10 benchmark. No v153
  runtime error was present in the reviewed error log (historical v150 guard
  errors remain visible and were not deleted).
- Network throttling, cache bypass, reduced-motion emulation, device metrics
  and the temporary viewport were restored; the final preview uses ordinary
  browser settings and running animation.

### Maintained build and regression record

v153 was staged through the maintained path, not an unrepeatable sidecar swap:

```powershell
E:/Anaconda3/python.exe -B godot/tools/stage_lite_web.py `
  artifacts/v147 `
  artifacts/startup-v135/build/candidate-15/mode5/index-lite.pck `
  artifacts/v153 `
  --bootstrap artifacts/startup-v135/build/boot-15
```

This command has already completed. Use a new, unused destination for a
subsequent build; do not overwrite the sealed measured artifacts.

- All **255** host JS tests pass. One test-only WebCrypto race was corrected
  by waiting for the real callback with a bounded timeout instead of assuming
  five event-loop ticks; production streaming code was not altered for it.
- Verified-Brotli tests: **14** pass (implementation review also ran seven
  related tests). Stage-engine regressions: **38** pass. Startup analyzer:
  **34** pass. Static-overlay integration: **9** pass.
- Independent network audit reads the original three complete logs and the
  unchanged analyzer. No samples, scoring thresholds or cache rules were
  edited to obtain the passing result.

Further scenery/Boss/backend work is outside this loading pass. No deployment
or private backend/reward operation was performed.
