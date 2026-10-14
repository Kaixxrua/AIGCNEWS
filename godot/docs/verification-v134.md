# v134 — first-load reduction, 10-second target NOT met

2026-09-12, local Windows recovery workspace. Preview:
<http://127.0.0.1:4231/v134/index.html?quality=lite&rev=1>.

The accepted art direction remains frozen. This is still the complete live
Godot world, with the original and balanced packs preserved. No poster swap,
early loader dismissal, SSH, production deployment, Boss or backend work.
The user has been asked whether non-critical scene details may load after
the initial live world appears; that change is **not implemented in v134**.

## Measured result and limits

Same browser/machine, visible document, actual 2560×1440 canvas, DPR about 1,
16:10 scene letterboxed, paused clock 0. Browser-emulated **20 Mbps download,
5 Mbps upload, 80 ms latency setting**, HTTP cache bypass. Driver/shader caches
already existed and were **not cleared**. Builds/profiling were stopped for
these samples. This is bounded local network simulation, not a deployed-CDN
measurement, GPU-cold test, median, P95 or production guarantee.

| Comparable measurement | v127, this session | v134 |
| --- | ---: | ---: |
| Prepared Brotli engine/host + selected pack, bytes | 39,102,090 | 30,885,685 |
| Prepared gzip engine/host + selected pack, bytes | 41,134,274 | 32,140,986 |
| Raw lite PCK bytes | 34,261,596 | 25,782,196 |
| Quality-start to actual ready gate, ms (`loadMs`) | 28,165 | 22,894 |
| Navigation-start to actual ready gate, ms | not instrumented | 23,339 |
| Pack fetched milestone, ms after quality-start | 17,704 | 13,824 |
| Engine started milestone, ms after quality-start | 26,538 | 21,323 |
| Scene build duration, ms | 3,441 | 2,713 |

Like-for-like prepared Brotli reduction: **21.0%**. Comparable ready sample:
**28.2 → 22.9 seconds**. For the user's "open the page" criterion, use v134's
**23.3 seconds**, not its later-starting 22.9-second counter. The updated host
records both clocks; it still requires the real scene-ready signal, engine
start and two RAF boundaries. It does not merely wait for downloaded bytes.
Full-frame PNGs were inspected after ready, not at an instrumented physical
display-presentation timestamp.

The v134 network record contains response/finished pairs for all **10 expected
HTTP requests** (plus one zero-transfer blob), totaling **30,896,911 encoded
transfer bytes including HTML/headers**. Every compressible response negotiated
Brotli. Only `index-lite.pck` was fetched, not original/balanced. The event
buffer reports truncation at navigation; this is not claimed to be a complete
browser trace, but the expected requests are each accounted for explicitly.

At 20 Mbps, 30.9 MB alone has an ideal wire floor of about **12.4 seconds**,
before initialization. **The 10-second first-load target remains unmet.**
Changing first-screen detail loading needs a user decision; neither a warm
cache result nor an unthrottled localhost result can satisfy that target.

One separately primed-cache revisit under the same bandwidth/latency settings
reached ready at **9,722 ms from navigation** (9,309 ms from quality-start).
Both large resources reported 300-byte revalidation transfers, with no body
download. This is a **repeat visit**, explicitly not the requested first load.
Its bounded event read was untruncated with no captured exception/Log warning.

Evidence: [v127 same-session cold sample](../../artifacts/startup-v128/bench-v127-cold20-current-01.json),
[v134 cold sample](../../artifacts/startup-v128/bench-v134-cold20-01.json),
[v134 cache revisit](../../artifacts/startup-v128/bench-v134-warm20-01.json),
[prepared payload](../../artifacts/v134/web-payload.json).

## What is actually shipped

1. **Bounded leaf subdivision LOD in lite only.** Keeps plant/root placement,
   transforms, materials and retained vertex channels; reduces small leaf
   strips/fans by about 443k triangles. This is limited geometric loss, not
   lossless geometry. No trees or scene objects are removed. Unmatched
   primitives stay unchanged. Candidate-02 is the verified candidate.
2. **Exact preapplied rock ambient occlusion.** Runs the actual existing AO
   calculation before packaging and preserves the resulting surfaces and
   legitimate idempotence metadata. No material/shader or runtime guard bypass.
3. **Lossless filtered scene containers.** Private RSCC mode 5 stores reversible
   byte-plane/delta filters followed by Zstd. Decoded scene bytes are identical
   to the reviewed input. This requires the paired custom engine; it is not a
   general stock-Godot pack or an untrusted-resource upload feature.
4. **Exact cached crown-edge construction.** Restores 632 roots (605 fringe +
   27 branchlets), 52,956 vertices / 17,652 triangles, with exact transforms,
   colors and materials. Runtime restores synchronously before ready and
   duplicates mutable resources. The measured Web restore was 26 ms, compared
   with roughly 578 ms construction in the earlier intermediate build; do not
   claim four seconds of savings. The added cache has a real transfer cost.
5. **Smaller paired Web engine.** Trims unused modules and uses the reviewed
   basic text/GUI build, while preserving the required 3D renderer, physics,
   navigation and animation. Retains the previously reviewed lazy shader patch.
6. **Reflection depth-copy correction.** Only SSAO-forced depth copying now
   requires `!is_reflection_probe`. Probes already skip SSAO post-processing;
   actual material depth consumers remain untouched. This fixes the six
   depth/stencil blit warnings also present in v127. Main-view SSAO, water
   materials, reflection capture settings and animation remain unchanged.

The final combination is 185 PCK entries: relative to the reviewed filtered
pack, 183 are exact, one compiled crown controller is replaced and one scene
cache is added. The main `meadow_scene.gdc` remains unchanged. The native audit
twin contains identical decoded scenes in a stock-readable codec; never serve
that audit twin as the smaller shipping pack.

Build/review sources: [composition](../../artifacts/startup-v128/combined-01/README.md),
[complete native proof](../../artifacts/startup-v128/combined-01/final-proof.json),
[engine handoff](../../artifacts/startup-v128/engine/reflection-depth-01/HANDOFF.md),
[codec contract](../engine-patches/filtered-scene-codec-v128.md),
[reflection contract](../engine-patches/reflection-depth-web-v128.md).

## Verification and visual acceptance

- Full native combined audit: 144 nodes, five colliders, 17 required objects,
  13 lights (four directional/nine omni), seven day/night phases, 11 original
  plus eight v127 contracts. Actual AO values, idempotence, walking/Boss space,
  weather/water/routes and all 632 cached roots pass. No Spot/Area lights.
- Mode-5 inverse: 2,248 round trips and 288 negative cases; actual paired
  JS/WASM instantiation, memory/FS checks and six reflection-scope tests pass.
- Main web suite: **175 tests pass**. Stager suite: **24**, reviewed scene
  contract: **12**, mode-5 pairing guard: **3**, exact composition: **4** pass.
- Stagers inspect real RSCC entries and reject a mode-5 pack with a stock,
  unknown or mixed engine before creating the destination. Only reviewed
  pack hashes permit the zero-Spot/Area shader specialization.
- Final lite cold run: no captured JavaScript exception or WebGL warning;
  full day and night render successfully. Previous six reflection warnings
  are absent. This is not a guarantee against every possible runtime error.
- Main personally inspected original-detail QHD lite day/night, original
  night and balanced day: complete framing, both side bars, castle, terrain,
  river, foreground and readable wildlife retained. Lite's internal 3D scale
  is still **0.5**, so these are QHD canvas captures, not native-QHD 3D detail.
  No claim of whole-frame pixel identity (animal poses can differ at clock 0).
- Final shared-engine functional Web checks: original and balanced both load
  their selected pack only and reach the real ready gate; each switches to
  night (`nightBlend=1`). These were **unthrottled functional smoke tests**,
  not first-load performance acceptance. Original-night and balanced
  day/night observation windows contain no captured exception/Log warning.

Screenshots: [lite day](../../artifacts/startup-v128/day-v134-2k.png),
[lite night](../../artifacts/startup-v128/night-v134-2k.png),
[original night](../../artifacts/startup-v128/night-v134-original-2k.png),
[balanced day](../../artifacts/startup-v128/day-v134-balanced-2k.png).

## Frozen identities and rejected work

Rechecked final on-disk SHA256:

| File | SHA256 |
| --- | --- |
| Original PCK (unchanged) | `02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d` |
| Balanced PCK (unchanged) | `68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33` |
| Final lite PCK | `61f4ca64a129328a0329623013a9f5cfa0968406c8e8913f73f2403f99ffe9b3` |
| Final WASM | `52d3ad52fd004291970d1ef02b0f818500f4f57500e20aadcb911373e4a78716` |
| Paired engine ZIP | `1344c8aecdc55404e560240a7dd22b3a4734e85a2a04efef7617416acf3b6858` |

**Not shipped:** position/UV quantization (changed actual AO in 11/320 checked
samples), aggressive terrain/rock simplification (shape errors), ineffective
collision/long-window compression experiments, and v132's optional framebuffer
state cache (no reliable performance win under its build-interfered sample).
Failed/rejected artifacts remain separate for audit; no old release is deleted.

The final v134 engine has no v132 framebuffer JavaScript transformation. Its
build name still says `v128_text_gui_lazy`; identify the release by SHA, not
that retained label. Original/balanced resource preservation is byte-exact;
the shared engine is intentionally changed, so engine/render bit-identity is
not asserted. Local recovery isolation was retained because Git resolves to
the drive root, making automated worktree/Git writes unsafe here.

Browser handoff: temporary throttling, cache bypass, reduced-motion emulation,
device-metrics and QHD viewport overrides were cleared. The preview returns
to normal-size lite daylight with environment animation playing. Existing
user tabs are retained; all three completed subagents were closed.
