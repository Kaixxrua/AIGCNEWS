# v85 — cloud-star integration and architecture painted fill

Progress candidate, not completion of scene/reference fidelity. Water, global lighting/weather, camera/focus, assets and geometry are unchanged. Vegetation was investigated but not edited; its dark-island transition remains work to do.

## Implementation and rejected alternative

v84 direct pigment attenuation failed actual moon-direction roof response (.002597 < .006) and was removed, not worked around by lowering the gate. v85 leaves graded_art, ALBEDO, relief/normal, alpha and subsequent window formulas byte-exact to the v83 backup. Only the architecture wrapper attenuates its existing painted-fill EMISSION: source luminance smoothstep .08–.80 drives day .30–.75 and night .65–.85 multipliers. This affects the entire castle/village material including embedded vegetation; it is not a complete semantic stone mask. Real diffuse illumination is not reduced. Window emission is added after the attenuation and is not multiplied by it.

Sky retains v83 clear-star position, radius, intensity and twinkle. Existing cloud opacity .01–.12 smoothly removes only the star contribution before the unchanged cloud mix; opacity ≥.12 extinguishes point stars. This is an artistic point-star extinction curve, not a physical cloud simulation. No extra textures, loops, draw passes or new assets.

## Verification actually performed

- Build session 58132 exited 0: `20260910-162834-*` material-only ten-stage flow, five current v77 caches, import, three GPU parse checks, source, foliage tone, lighting, export and pack smoke. This was NOT the full 35-stage suite.
- Additional current-source architecture-fill audit exited 0: 5,125 bounded/monotonic CPU cases, exact non-fill source and unchanged zero-fill path/window expression. Filename remains `audit_architecture_pigment.gd`, marker explicitly describes the v85 fill design. It is not a pixel-render test.
- Additional current-source sky, architecture and window audits (session 11002 exit 0): prior non-star sky/weather/water/focus guards, exact v83 clear stars, cloud-extinction algebra, shared clock/reversal, source-aligned architecture, 1,373 protected playfield probes and 243 window sample phases passed. Logs are in `artifacts/v85/extra-*.log`.
- Actual WebGL, diagnostic tab 23, 08:33:28–08:34:23 UTC: architecture PASS (day flat/profile means .058130/.074183; moon-direction .000000/.010319 > .006; control error zero); canopy, leaf transfer and render response PASS with original gates. Old large-toe foliage test remains DIAGNOSTIC_ONLY. No warn/error. These isolated probes swap key directions in the initial day environment, not actual night-endpoint scenes.
- Separate real day/night scene captures: `day-fill-2k.png` and `night-fill-2k.png`, decoded PNG 2560×1440, canvas same, DPR approximately 1, clock 0 paused, night blend 0/1, complete 16:10 scene with sidebars. Main personally inspected original images. The first same-call capture was cropped by delayed compositing despite correct dimensions; renamed `day-fill-invalid-crop.png`, explicitly excluded.
- Independent visual review: cloud-edge bright specks suppressed in the sampled night frame; clear-sky stars still readable. Night building silhouettes/roofs/windows and water/trees show no obvious regression. Castle day response is only modestly improved, still pale and lacking clear large-volume separation/terrain integration: pre-registered castle goal NOT passed. Vegetation benefit NOT claimed.
- Ordinary fresh tab 24, no diagnostic query: 1920×1080 canvas at DPR1.5, ready18,820ms/download2,593ms/scene2,452ms, no warn/error, day/night controls work. Diagnostic tab took95,753ms and v84 diagnostic156,446ms; these are different workloads, not comparative optimization benchmarks or proof of the old browser-crash cause. Temporary overrides were restored and diagnostic/old tabs closed.

## Frozen evidence and remaining work

Current cutout SHA `2f4c660dbeb147725254f5a5c5a50d87971f73ca64c10981404bb6fdc0e6c094`; sky SHA `374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b`. Exact final shader copies are in `artifacts/v85/`. The v83 source and rejected v84 source remain preserved. Recovery source and invalid inherited Git root were not modified; isolation skill fallback used local versioned exports and scoped backups.

PCK118,845,188 bytes, gzip114,065,156, SHA `f9e40f579b9fe3858d50cdc0dc8b1715217598ee7f98c47e20562922bd63573a`, independently matched to payload manifest. Compared with v83 gzip increases331 bytes. Existing WASM and web controls unchanged.

Next high-value work is broad architectural plane/base integration and dark plant crowns against light turf, not another blanket exposure/contrast change. Global grey cast and full asset harmony remain unproven. Preserve approved water and readable night lighting. Preview: http://127.0.0.1:4231/v85/index.html
