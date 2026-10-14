# Complete-scene lite tier — v115–v117

## Scope

The user approved a genuinely smaller complete Godot scene, accepting lower
render resolution and texture/detail fidelity. This is not a static screenshot,
video, alternate 2D engine, or a reduced composition. The accepted original and
the existing balanced pack are preserved byte-for-byte. Boss/combat assets and
AIGCNEWS integration are not part of this pass.

## Build isolation and reproducibility

Work stays in the recovered local Windows workspace. Git resolves to the drive
root rather than a safe project repository, so no Git/worktree operation was
performed. Each candidate is an independent artifact directory. No original
artwork, imported source texture, original/balanced PCK, shared Web engine or
existing geometry cache was overwritten. Three concurrent agents handled
geometry/compiler work, independent checks, and UI/settings/startup checks;
the main agent integrated builds and performed Web visual acceptance.

The frozen baseline is `artifacts/v114/index.pck`, SHA-256
`02adc956b196fc701092b5186343da9146a5f30b64f349d5d3dcbe12b8f81a6d`.
The shared Godot 4.7.2 release WASM remains SHA-256
`fc74679e3b97f76878947fcd4fbe1268cbfa6188182a2e33bbc3f5dc9bfa57d0`.

Tools:

- `build_lite_pack.py`: independently builds/pins all variant entries; can reuse
  the checked texture trial and accept only explicit geometry/runtime manifests.
- `build_lite_geometry.py`: stock ArrayMesh packing, bounded attributes, all
  original node/vertex/index/triangle order and collision surfaces retained.
- `build_lite_settings.gd`: isolated exported settings; 0.5 3D resolution scale,
  bilinear reconstruction, 2x MSAA and a 2048 directional shadow atlas.
- `compile_lite_startup.py`: stock compiler for exactly one optional-diagnostic
  gate; original source reproduces the original packed bytecode exactly.
- `stage_lite_web.py`: new version output, frozen original/balanced/engine copies,
  current three-tier UI, gzip/Brotli siblings and measured payload catalog.

Keep `candidate-native-04` as the chosen geometry candidate. `candidate-gzip-02`
and the texture-only trial remain diagnostic fallbacks. Do not mix new rock UV
data with the old AO signature, or recompress terrain without rebinding the
far-sward terrain file hash. AO sample geometry and all 317,556 original
visibility-to-vertex mappings remain exact; only the mesh signature is rebound.

## Size accounting

The v116 stronger candidate was measured, not estimated:

| Tier | PCK bytes | PCK gzip bytes | Shared engine + UI + one PCK, gzip bytes |
| --- | ---: | ---: | ---: |
| Original | 123,983,036 | 119,336,771 | 129,528,016 |
| Balanced | 111,244,748 | 106,593,765 | 116,785,010 |
| Lite | 44,326,092 | 39,338,999 | 49,530,244 |

Totals exclude HTML and HTTP headers. MB means decimal MB. The lite total is
61.76% smaller than original; it is not a 20–40 MB completed target or a
single-digit-MB contact page. Texture payload alone shrank from 69,504,448 to
9,963,968 bytes. The remaining dominant cost is real 3D geometry plus the
standard engine, not a missing image compression option. Brotli siblings are
prepared but the running port-4231 preview serves gzip; do not claim live
Brotli savings without deployment verification.

All 184 original resource paths remain. Texture logical sizes are unchanged;
lower stored mips use Godot's size-limit contract. All retained alpha samples
are exact to their selected original mip. Pixel-coordinate consumers (dragon,
settlements, measured vegetation/lantern crops) retain their physical dimensions.
Water texture and shader/flow code are unchanged. UI downloads only the chosen
pack; changing quality reloads into a single new engine instance.

## Verified Web evidence

Main inspected original-resolution 2560x1440 PNGs:

- `artifacts/v115/day-lite-2k.png`, `night-lite-2k.png`: fallback geometry.
- `artifacts/v116/day-lite-2k.png`, `night-lite-2k.png`: stronger geometry.

For those captures the actual canvas and PNG were both 2560x1440, DPR 1,
weather clock 0, motion paused, night blend exactly 0 or 1. The entire 16:10
composition remains letterboxed, not stretched/cropped. This is a QHD capture
of the intentionally half-resolution 3D tier, **not native-QHD 3D detail**.
Random dragon route/pose can differ despite equal weather clock; do not use it
as a pixel-identical static comparison region.

Main visual judgment: scene inventory, framing, connected grass/rock edges,
water transparency, warm lamps and readable night lighting remain coherent.
Fine texture and foliage detail are visibly softer than the accepted original,
which is the authorized lite tradeoff. No obvious newly missing cutout region,
white fringe, geometry collapse or gross lighting/silhouette change was found.
This is not a claim of mathematically identical appearance.

Real v116 Web diagnostics additionally passed walking 31/31, bridge 9/9 and
entries 24/24, city foundations 128/128, village 65/65, all tested root anchors,
52 settlement lights and the 317,556-sample AO apply. Normal Web console had no
error/warning entries. Actual ResourceTiming confirmed only `index-lite.pck`
(39,338,999 encoded bytes), not original/balanced, loaded with the shared engine.
The menu showed all three measured sizes and updated the sum when original was
selected. Applying original did reach the original scene and requested only
`index.pck` (119,336,771 encoded bytes). Transient CUA target/focus errors were
followed by fresh target lookup; the observed v116 page remained alive.

## Startup investigation and limits

The old main scene unconditionally performed the entire first-physics developer
audit. The new source gates only that optional audit to debug builds or explicit
`--startup-audit` / Web `startup_audit=1`. Existing targeted audit query paths,
gameplay processing, walking/collisions and rendering remain intact. It reports
audit duration and actual canvas/DPR separately from engine/download milestones.
See `artifacts/loading-v115/startup-diagnosis.md` for source and compiler proof.

Earlier local load milestones (v115 278.7 s, v116 lite 225.6 s, original 265.1 s)
are **not valid matched performance comparisons**: browser input/navigation
reset DPR and one run rendered a 3840x2160 backing canvas instead of the intended
size; CUA focus/target scheduling was also unstable. `loadHiddenMs=0` does not
rule out these confounds. Network transfer finished much earlier, but that is
not equivalent to a rendered, interactive scene. No public-network open-time
promise follows from localhost measurements.

The final release Web opt-in was actually exercised. It reported
`startupAuditDebugBuild=false`, enabled/completed, and **452.8 ms** inside the
full audit. Therefore the audit is **not the main explanation** for the long
observed engine-start delay. The gate avoids unnecessary work but must not be
marketed as solving that delay. Its startup marker recorded a 1280x800 canvas,
DPR approximately 1; subsequent browser interaction had changed the backing
store to 1920x1200. Full raw telemetry is
`artifacts/v117/startup-audit-enabled-web.json`.

Final integrated v117: PCK 44,327,228 bytes, SHA-256
`018ae7b592213c3dedb7f538cde84c08f17935487d9da8349873106abfe5ed79`;
gzip 39,340,225 bytes; all shared engine/UI plus the selected PCK gzip
**49,531,470 bytes**. It differs from the visually reviewed v116 lite pack in
exactly one of 184 entries, the 47,900-byte startup-gate compiled script. The
other 183 entries, including all visual resources/settings, are byte-identical.

Independent final native/structural verification is complete:
`artifacts/loading-v115/runtime/final-trial-independent-review.json`. All 11
native baseline comparisons pass, no engine warnings/errors, 144 scene nodes,
five exact collider hashes, original water and day/night behavior, all four
eight-frame species and seeded routes retained. The separate structural check
passes all 184 entries with 40 declared changes and 144 unchanged entries.
Its semantic follow-ups are addressed by separate geometry/compiler/native/Web
evidence, not silently removed from the checker.

## Final Web handoff / unresolved performance

Default release v117 actually reports `startupAuditStatus=skipped`,
`startupAuditEnabled=false`, `startupAuditDebugBuild=false`, zero audit work;
the explicit opt-in reports completed. Both reach the real scene and enabled
controls. The default run is saved in `artifacts/v117/startup-default-web.json`.
It still reported 261.896 seconds to presentation in this test environment,
with a 1.527-second lite PCK request. This is not a successful end-to-end latency
optimization or a production benchmark. The enabled/default runs have different
startup backing sizes (1280x800 versus 1920x1200), and the latter included an
attempted 10-ms-interval CPU sample. Do not subtract their total times to claim
the audit saved 45 seconds; its direct measured cost was only 452.8 ms.

The profiler stop request timed out and its result could not be recovered;
the subsequent stop confirmed no recording remained, then Profiler was disabled.
No usable CPU profile was produced. The long engine/presentation interval needs
a separate reliable browser/driver/first-frame profile. Its cause is unresolved;
it is not attributed to shaders, the GPU, network, or the optional audit without
evidence. Public deployment/CDN bandwidth and cold-device performance were not
measured. The delivered result is the independently verified complete-scene size
reduction and quality choice, not an assertion that extreme lightweight/instant
loading has been achieved.

Final capture `artifacts/v117/night-lite-2k-final.png` is a visually inspected,
complete 2560x1440 PNG at actual QHD canvas, DPR 1, clock 0, night 1, paused.
Both sidebars, complete castle, foreground cliff and right tree are present.
It retains the accepted lite night appearance and complete scene. The earlier
`artifacts/v117/day-lite-2k.png` is **INVALID tiled diagnostic evidence**: merely
changing the device override while the browser viewport remained 1280x800 did
not produce correct full framing. It is retained for diagnosis, not acceptance
or presentation. Setting the browser viewport to QHD before applying the known
1.5-display-mapping correction produced the verified final capture above.

## Regression evidence

Main ran 11 strong-geometry artifact tests, 19 quality/loader JavaScript tests,
20 transport tests (one optional skip), and five runtime-replacement scoping
tests. Earlier in this pass the four texture tests and ten settings tests also
passed. Independent verification includes exact pack directory/MD5/remap checks,
all retained-mip alpha and atlas contracts, seeded native day/night wildlife
routes, collision hashes, camera/light/object contract and isolated compiler
checks. Source-level gate tests are separate from true release-Web execution.

Do not relabel structural/native tests as visual or production-performance
acceptance. Original and balanced assets have not been regenerated.

Final additions: 18 startup source/Node-VM tests and all 61 independent checker
tests pass. The final native report passes all 11 comparisons. All three
subagents completed their concrete assignments and were closed; no separate
user-visible Codex task was created.

Final live Web animation check: after pressing the observed play control,
`motion=true`, night blend 1, and weather clock advanced from 0 through 212.485,
277.180 and 467.482. The full QHD motion capture
`artifacts/v117/night-lite-motion-2k.png` was inspected: clouds, dragon pose/sky
position, luminous stag position/pose and water pattern differ from the paused
frame while the scene stays complete. This is sampled visual motion evidence,
not an exhaustive route test. Temporary CDP metrics/viewport overrides were
cleared/reset, profiling disabled, and the live night preview marked deliverable.

Final HTTP HEAD (curl without automatic decompression) returned 200 for the
selected PCK with `Content-Encoding: gzip`, `Content-Length: 39340225`,
`Vary: Accept-Encoding`, ETag and revalidation caching. The HTML also returned
200. The earlier PowerShell response wrapper stripped encoding/length on its
auto-decompressed view; that blank wrapper output is not evidence of absent
compression. Brotli remains prepared-only (46,646,622 total bytes if all prepared
encodings are correctly served), not a live deployment claim.
