# v127 — smaller complete-scene lite pack and lazy Web shader variants

2026-09-12. Local Windows preview:
<http://127.0.0.1:4231/v127/index.html?quality=lite&rev=1>.

The approved world is retained. This is an optional, visibly softer lite tier,
not a new art-direction pass, flattened image or an absolute size/speed limit.
No Boss/backend integration, SSH, Git writes, deployment or rewards work.

## Implemented and separated

1. **Engine-only v126:** custom Godot 4.7.2 at upstream commit
   `ed1daf0bf001b61586d9930840f2f1394092c079`. Web allocates variant maps but
   compiles only the exact shader variant requested by an actual draw. Bind,
   link-status checks, uniforms and failures remain real and synchronous.
   Native policy and all Web features/modules are retained. No fake readiness.
   [Durable patch and build recipe](../engine-patches/README.md).
2. **Lossless scene containers:** five RSCC resources repacked with stronger
   Zstd blocks. All 87,008,067 decoded bytes are exact; terrain and geometry,
   triangles, materials, metadata and collisions are not simplified or removed.
3. **Selected Q60 texture tier:** 12 textures drop one further original mip;
   10 registration-sensitive atlases retain physical dimensions. 22 CTEX
   entries change RGB encoding; alpha of every retained source mip is exact.
   Water, four animal atlases and five material textures are byte-exact to v125.
4. **v127 combines (1)–(3):** all 184 entries retained, 157 byte-exact to v125,
   5 decoded-scene-exact and 22 equal the reviewed Q60 candidate. No rejected
   vertex-dedup candidate is included. Its package grew despite fewer vertices.

The engine uses matching newly built JS/WASM. Original and balanced PCKs remain
byte-identical to v114; the shared engine is intentionally new. Staging is into
new directories; older exports and recovery sources are not overwritten.

## Size: bytes on the wire, not lower render resolution

Decimal MB. Total covers selected pack + shared engine/host assets, excluding
HTML and response headers. Only the selected pack is requested.

| Prepared/live representation | v125 lite | v127 lite |
| --- | ---: | ---: |
| Raw PCK bytes | 44,327,612 | 34,261,596 |
| Gzip PCK bytes, same level 6 | 39,340,280 | 30,928,686 |
| Gzip total bytes | 49,540,435 | 41,134,274 |
| Brotli total bytes | 46,655,182 | 39,102,090 |

Like-for-like reduction: **17.0% gzip total / 16.2% Brotli total**. Do not compare
v125 gzip against v127 Brotli and attribute all savings to pack changes.

The previously stopped loopback server was restored with the existing
`serve_meadow.py`, bound only to 127.0.0.1:4231 and the artifacts directory.
This current server negotiates verified Brotli sidecars. Actual HEAD responses
for v127 returned `Content-Encoding: br`: PCK 30,833,342 bytes and WASM
8,188,237 bytes. Browser resource timings independently report those exact
encoded body sizes. Gzip remains the fallback; the quality menu conservatively
labels its figures explicitly as gzip, not as guaranteed wire consumption.

## Matched engine-only A/B/B/A

Same browser, actual canvas/PNG 2560×1440, DPR approximately 1, same 16:10 scene
with side bars, clock 0, paused via reduced-motion preference. HTTP cache bypass
enabled, unthrottled loopback, visible document, hidden-load time 0. Shader trace
off and startup diagnostic off. The v125 pack and host helper are unchanged in
v126. Build/link/native tests had completed before these runs.

| Sequence | Engine/pack | Ready ms |
| --- | --- | ---: |
| A1 | stock / v125 | 12,266 |
| B1 | lazy / v125 | 9,655 |
| B2 | lazy / v125 | 8,600 |
| A2 | stock / v125 | 13,537 |

Two-sample means: 12,901.5 → 9,127.5 ms, approximately **29.3% shorter** in this
bounded local comparison. First-screen shader-source submissions: **286 → 120**.
This is not unique-program count or compiler CPU time. Required first-use
variants still compile synchronously; this patch does not eliminate all stalls.

First paused night switch, one sample each: stock 2,369 ms, lazy 1,610 ms,
final composed v127 1,672 ms. These presentation milestones are distinct from
immediate command acknowledgements and from animated transition duration.

**Driver/browser compiled-code caches already existed and were not cleared.**
Do not call these GPU-cold runs or compare them to the historical 50–79-second
v125 captures. An uncontrolled existing warm v125 observation was separately
saved but excluded. Emscripten is pinned from upstream CI; the unknown exact
stock compiler flags were not recovered, so this is a custom-engine comparison,
not a byte-reproducible build isolating every compiler option.

## Final v127 network tests

- Unthrottled loopback + HTTP cache bypass: **9,397 ms** (not production speed).
- Browser-emulated **20 Mbps download / 5 Mbps upload / 80 ms latency**, HTTP
  cache bypass: **26,553 ms**. Pack transfer lasted 17,722 ms; the real ready
  gate still waits for scene-ready, engine start and two RAF boundaries.
- Same emulated network, cache revalidation/primed: **8,428 ms**; subsequent
  measured revisit **8,219 ms**. Each large resource transferred only a 300-byte
  revalidation response, not its body. Do not label this a zero-request load.

These are this Windows machine's bounded browser simulations, **not deployed
CDN measurements or a production SLA**. GPU-cold devices, slower CPUs and packet
loss remain unmeasured. At this payload, complete-world first loads in 2–3 seconds
on a 20 Mbps connection are not supported by the results.

Raw DOM measurements: [A1](../../artifacts/startup-v126/v125-a-http-bypass.json),
[B1](../../artifacts/startup-v126/v126-a-http-bypass.json),
[B2](../../artifacts/startup-v126/v126-b-http-bypass.json),
[A2](../../artifacts/startup-v126/v125-b-http-bypass.json),
[final local](../../artifacts/startup-v126/v127-http-bypass.json),
[limited cold](../../artifacts/startup-v126/v127-cold-20mbps-80ms.json),
[limited warm](../../artifacts/startup-v126/v127-warm-20mbps-80ms.json).

## Visual and functional acceptance

Main inspected actual original-detail 2560×1440 PNGs, including full framing,
castle, cliff, right tree and both side bars. These are real QHD canvas captures,
not upscaled images. Lite's internal 3D scale remains 0.5; do not describe its
3D detail as full native QHD. The camera, lighting, shaders, water and scale are
unchanged from v125 lite.

- Engine-only day: castle, meadow, water and right-tree regions are pixel-exact.
  Night: those regions differ by at most one 8-bit level. Actor/dragon poses can
  differ at clock zero; no false whole-frame pixel-identity claim.
- Composed Q60: visibly softer lower-edge tree crowns/shrubs; right tree mildly
  softer, fine roof/wall detail smoother. Whole-frame day RGB mean absolute
  difference 1.114/255, night 0.711/255. Metrics are supporting evidence only.
- Main and independent reviewer accept this tradeoff **for optional extreme-lite**:
  full world and readable silhouettes retained; no newly continuous white halos,
  missing major assets, broken shadows or obvious water/light discontinuity.
  It is not equivalent to original quality; users retain the original choice.
- Web night motion was observed through clock 87, with moving clouds, dragon,
  luminous stag and water; return-day reached blend 0 and motion continued.
- The in-scene quality menu exposes all three choices and explicit reload/size
  explanations. Original was selected and applied through the actual UI; its
  unchanged PCK loaded with the matching custom engine, day/night reached both
  endpoints and motion continued through clock 223.596. No captured browser
  errors/warnings. [Original day smoke](../../artifacts/v127/day-original-smoke-2k.png)
  and [original night smoke](../../artifacts/v127/night-original-smoke-2k.png)
  were personally inspected; these are functional smoke checks, not matched
  old/new original-quality performance or pixel comparisons. Balanced is
  hash/contract verified, not separately Web-smoked this turn.

Temporary network throttling, cache bypass, reduced-motion emulation and the
QHD viewport/device override were cleared on the deliverable tab. Final preview
returns to lite with ordinary animation. The old disconnected error tab was
not used as performance evidence; measurements use the restored service/tab.

[Day](../../artifacts/v127/day-lite-2k.png),
[night](../../artifacts/v127/night-lite-2k.png),
[night motion](../../artifacts/v127/night-motion-2k.png).
Pixel comparisons are in `artifacts/startup-v126/{day,night}-{engine,pack}-metrics.json`.

Independent final pack audit: one native run, **11/11 strict comparisons**, 144
nodes, 17 required paths, 5 exact colliders. Seven day/night/animated light
censuses: 4 Directional + 9 Omni + 0 Spot/Area. Four animals retain/visit 8 frames,
dragon retains 32 (22 observed per finite seed), routes and walking/Boss constants
unchanged. Headless/native success is not represented as GPU visual proof.
[Hash-bound report](../../artifacts/startup-v126/independent/final-composed-scene-contract.md).

## Regressions and reproducibility

- Full Web tests after integration: **174/174 pass**.
- Engine-staging focused tests: **23/23 pass**.
- Updated exact scene-contract publication tests: **12/12 pass**.
- Texture focused suite: **19/19 pass**, including real candidate mip/alpha checks.
- New engine: one successful build, offline module/source/scheduling verification;
  [full build provenance](../../artifacts/startup-v126/engine/engine-manifest.json).
- Original SHA256:
  `02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d`.
- Balanced SHA256:
  `68198062fb7918abaef956d588ec5e929104dffe348d520602c862749af67a33`.
- Final lite SHA256:
  `771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf`.
- New WASM SHA256:
  `fb3c2f151e8351492c23913522bc537c22d2de973501f239c5eb96946b8178f9`.
- Matching JS SHA256:
  `ec9d30e70e4150d7594afad38d0ab5b22c6d535aaa524156656ab413b7cedcc8`.

Recipes: `optimize_scene_containers.py`, `build_lite_pack.py --texture-profile
mip2-q60`, `compose_lite_v126.py`, `stage_engine_web.py`, `stage_lite_web.py`.
All require new output paths. The recipe is pinned to reviewed inputs. New scene
hashes do not inherit the no-Spot/Area optimization; new Boss lighting must be
audited. Do not replace the tested engine with a future stock export silently.
