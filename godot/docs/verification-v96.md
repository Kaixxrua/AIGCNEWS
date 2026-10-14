# v96 — source-aligned mountain daylight response, limited WIP

Previous goal turn was progress: v95's local architecture fog treatment produced
a visible building-colour improvement, independently reviewed day and night.
The intervening user score question did not authorize broader mutation by
itself; this work resumed under the explicit continuing scene goal. Overall
near-reference fidelity is NOT achieved. Local Windows workspace and original
reference were re-read; Git still resolves to E:/, so no Git writes/worktrees.
Scoped v95 source/export/cache snapshots are under artifacts/v96.

## Evidence and candidate

Main and reviewer read the original reference and mountain-ridge-v39 PNG.
The PNG already has warm rock, shaded gullies and forest. Current rendered
ridge reads as a broad compressed blue/white strip. The actual Quad is650m
wide and86.667m high after the existing .40 height scale; metadata art_height
still describes the pre-compression card. This pass does NOT fix that geometry.

Only DistantMountainRidge opts into the new mountain wrapper, with the same
lambert_wrap and alpha modes as the old distant wrapper. Eight soft source-UV
regions supply broad world-space slope normals; no added texture noise or blur.
Day-only ALBEDO and EMISSION scales are independent, rather than reducing
painted_fill and automatically increasing its complement. Original fill=.88
remains stored. New day coefficients before renderer conversion are ALBEDO
.204–.276 and EMISSION .4576–.5984. These are NOT measured light percentages.
Separate normal/day strength controls allow diagnosis. Night1 returns before
any new normal/colour modification. Fog, global light, textures, alpha, mesh,
camera and geometry are unchanged. This is approximate normal relighting of
painted art, not newly modelled mountains or real mountain self-shadowing.

Implementation files: meadow_mountain.gdshader/.gdshaderinc, two opt-in shared
surface blocks, one scene material assignment and a three-line opt-in GPU
probe route, plus explicit export whitelist entries. Water/weather/sky/focus/
leaves and v95 architecture helper/wrappers were source-hash protected.

## Executed build and independent regression

Because scene.gd belongs to the existing cache signature, its authorized
four-line change invalidated all five bundles. Rebuilt actual procedural
source with bake_static_meadow.gd --rebuild-static; did not forge metadata.
Session35503 exited0, MEADOW_BAKE_AUDIT PASS,52022621 bytes,new signature
6ff256ffe77b6f483488c1e3f503d983cb33d0a71b2edc72ecde29f098e1d105.
Subsequent independent old/new cache comparison exited0:5 bundles,9 meshes,
117 full array channels,3 collision shapes,329 checks. Decoded arrays,
topology, transforms and collisions are exact. No material/GPU claim follows.

Build20260910-224031/session65948 exited0, ten material-only checked stages
after rebake, NOT the full35-stage regression suite. Mountain probe separately
parsed successfully. PCK118888444 bytes/gzip114100289; SHA256
209b568759906d0dbe0f5fa21921f9215d4311a84f578322b78951f52829b7bb.

Independent material/source audit initially failed because it incorrectly
expected DepthAwareFocus.scene_exposure to remain at its day value throughout
night. The production weather was unchanged. Corrected only that test to
explicitly check the existing lerp(2,2.2,blend); retained first FAIL log.
Rerun mountain-material-verified.log exited0,PASS11047. It checks actual
day/half/night/return state, one mountain consumer, unchanged other resources,
and source isolation. It does NOT execute shader branches or prove night pixels.
The older exact-v95 architecture source-snapshot audit was not rerun or relaxed;
v96's independent source checks account explicitly for the new mountain blocks.

## Real Web GPU diagnostic

Opt-in mountain_audit=1, private960×384 orthographic SubViewport, actual
mountain texture/Quad, camera size280.8, same colour handling, fill0, no fog,
ambient/reflection/shadow. Normal-only strengths0/1 under symmetric ±72deg
sun azimuths. Predefined UV centres .151/.405,.209/.369,.291/.460,.330/.466;
each measured3×3 pixels. Normal-induced display-luma deltas:

| Sun azimuth | Main left | Main right | Central left | Central right |
|---|---:|---:|---:|---:|
| +72 | -.0757534 | +.0481445 | -.0408986 | +.0454224 |
| -72 | +.0736413 | +.0026795 | +.0638037 | -.0039251 |

Recorded directional-separation predicate passed; zero-light samples all0.
This is useful mechanism evidence, not comprehensive GPU quality acceptance:
the probe does not yet independently validate alpha coverage, a non-profile
control, full OFF-v95 parity or every slope, and uses a close fitted orthographic
view rather than production fog. Those limitations remain explicit. No browser
warn/error was observed. The probe changes private resources, not main weather.

## Visual evidence and handoff scope

day-mountain-2k.png and night-mountain-2k.png both decoded as PNG2560×1440;
actual canvas2560×1440,DPR~1,clock0paused,day/night0/1. Complete16:10 scene
with side bars inspected by main, compared with v95's matched images. A night
button focus timeout actually switched time and reset DPR; main reobserved
night1, recalibrated and only then saved the night acceptance image.

Main judgment: the main ridge's broken white highlights are modestly calmer,
but the large low-wide blue-grey mountain strip remains. This is limited WIP,
not a convincing three-dimensional mountain replacement or overall goal pass.
No obvious night regression; approved water and readable night kept intact.
Independent review is recorded separately in artifacts/v96/visual-review.md.

Normal non-audit page was opened after closing the diagnostic tab and resetting
capture overrides. Its observed readiness was27.277s (download2.551s,
scene-build3.785s); warn/error list empty. Diagnostic first load was119.846s,
not a representative normal-load performance claim. Diagnostic startup logs
reported40–43fps/160draws at that earlier viewport, beforeQHD calibration;
not a QHD benchmark. An unrelated user v85 tab stayed open. No speedup claim.

Next useful art work is the low-wide mountain silhouette/forested foothill
connection, not repeated global exposure/saturation tweaks. Keep the full
harmonious near-reference goal active, including remaining asset-volume and
lighting/composition coherence; do not redefine success as these tests passing.
