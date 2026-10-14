# v97 — continuous distant mountain relief, candidate verification

Previous development turn made progress by implementing an unexported relief
helper and independent geometry/skyline checks. The intervening rating request
was read-only. Work resumed under the explicit continuing scene goal; near-
reference harmony is not achieved. Current local files and agent terminal status
were rechecked. Git still resolves to E:/, so no Git writes; scoped v96 scene,
export and wildlife snapshots are retained in artifacts/v97.

## Actual implementation

The original 2172x724 mountain PNG is used once on one continuous ArrayMesh:
1365 vertices, 2560 triangles, full UV domain, broad source-aligned forward/rear
relief, partly released left/central height compression. Area-weighted actual
triangle normals replace the v96 analytic normal profile (strength now 0).
No new texture, card, collider, light or camera change. The existing v96 mountain
colour treatment and v95 architecture fog remain. Night may change with real
geometry; identical pixels are not required, but readability is.

63 measured alpha-column feet are softly moved to terrain_height-.05. This is
NOT proof of complete attachment to the actual terrain mesh: terrain triangles
interpolate the function, and alpha notches between mountain columns differ.
The terrain at z=-310 covers approximately x+-264 whereas the original wide
mountain spans x+-325; outer feet are expected offscreen. Visual review must
inspect the visible foot region, not equate metadata with support.

Production landmark queries now interpolate actual mountain mesh triangles.
Independent sky audit uses its own triangle-UV lookup instead of treating all
non-Quad geometry as the city mesh's 26-row layout. Its original bounds, seeds,
minimum gap, pose count and clipping thresholds remain unchanged.

## Executed checks, before Web export

Real cache bake session84182 exited0, MEADOW_BAKE_AUDIT PASS: 5 bundles,
52022618 bytes, source signature
be8c9b3afe5b7b84bc7bfe0519609ce46043adca7bcc2c93e112d2e9d11b9ae8.
Independent geometry audit PASS18621: UV area1, closed interior/shared edges,
no folds, actual depth -5.371908..24.07413m, normal quantization error .000107710.
Nearest mountain view depth309.1773 exceeds castle farthest292.18350; visible
alpha skyline stays inside frame (minimum normalized y=.034609). All sampled
feet report function gap-.05; unmeasured alpha edges are not certified.

Initial dragon_sky.log failed: conservative whole-pose skyline gap -9.80px,
required >=12px at the audit's 800px-high composition. Do not call this precise
pixel collision or ignore it because other scene assertions passed.
Moving the target airspace into the open valley, x=.28..62, first made the
400-second wildlife route-coverage check fail: the old absolute .22 target
separation forced alternating endpoints in the narrower space.
Final separation is .46 times usable width. B-spline continuity, world size25m,
depth -460..-355, speed11, 32 poses, ground fauna and fades remain unchanged.
The only audit_wildlife edit is a measurement print before the unchanged gate.

Final serialized session55246 exited0:

- wildlife-flightfix2.log: PASS400s, 8 dragon views/4 wing states/32 poses,
  x=.334203..561400 (span .227197), 83 random legs, projected open-wing48.6..59.4px,
  all animal grounding/animation/fade/pause/day-night/resume gates unchanged.
- dragon_sky-flightfix2.log: PASS8 seeds/15360 frames/240s each; top5.37px,
  skyline gap30.79px, minimumY57.32m, maxstep2.569m, far-plane clearance97.70m.
- mountain_cache_equivalence-flightfix2.log: PASS329; all9 nonmountain cached
  meshes,117 complete channels,3 collision shapes exactly match frozen v95
  decoded geometry. This excludes material/GPU/performance acceptance.

Both failed attempts remain in artifacts/v97. The old v96 flat normal-response
probe explicitly SKIPs ArrayMesh; SKIP is not a GPU response PASS. Historical
Quad/exact-v96-source audits were not loosened or reported as v97 passes.

Web export, actual QHD day/night images and independent visual verdict are
pending at this documentation checkpoint. Technical passes above do not prove
the requested final visual quality or that this candidate should be kept.

## Candidate1 actual Web and visual rejection

Ten-stage export session43125 exited0 (20260911-001417 logs), pack
6097b37314bfff265cd1100b0ba43594b74f97930bdf32a6d894d48bc2c78001,
118895304 bytes. Full35-stage suite was not run. Browser first readiness138.006s,
download2.723s, scene6.186s; CDP/layout/focus timeouts occurred. This is not a
normal-load benchmark or evidence of unchanged performance. Original v96
agent tab was closed; unrelated user v85 tab left alone.

day-relief-2k.png and night-relief-2k.png: actual canvas2560x1440, DPR~1,
paused clock0, day/night0/1, native PNGs with complete16:10 composition.
Day decoded2560x1440; night captured through the same native PNG workflow after
rechecking night1 and recalibrating the focus timeout's DPR reset. Original
images personally inspected by main and B. Shape is taller, but the large
blue-grey wall and weak foothill/grass join remain. Night is readable but the
dark mountain area and straight grass boundary are more intrusive. Candidate1
is not accepted as the finished mountain pass; preserve its images/snapshots.

## Candidate2 adjustment and executed checks

Only PEAK_LIFT .18->.08 in relief geometry. Depth, normals and sampled feet
retain the same construction. A separate MountainAtmosphere Node runs at
priority1 after weather and reads the actual WorldEnvironment. In supported
exponential fog it selects a mountain-only day shader, with source-UV optical
depth .46..1 for forested near slopes, rear ridge and soft foot return. This is
an artistic local atmosphere treatment, not physically simulated heterogeneous
fog. There is no new colour texture, blur or global Environment mutation.
At night1 or unsupported/null environments it uses the original native mountain
wrapper. Linear fog colour is converted once; original material parameters
including zero synthetic-normal strength survive shader changes.

Actual second bake session25486 exited0 PASS,52022630 bytes, signature
30f1c625a3f12c9164f477d69fd14abfb92011a6a822c974c67f110a39b36556.
Session86473 exited0: relief PASS18623 (skyline y=.055663, actual normal error
.000096160), dragon PASS15360 frames/gap35.39px/top5.37px, wildlife PASS400s,
and nonmountain cache equivalence PASS329 (9meshes/117channels/3collisions).

The first atmosphere test wrongly looked for DepthAwareFocus at scene root
instead of Camera3D/DepthAwareFocus. Runtime errors invalidated its printed
PASS1033; the enclosing log gate correctly rejected it, stopping the export.
The failed log remains. Only the test path and explicit required-node/snapshot/
stage-completion checks were corrected; no production behaviour or threshold
was weakened. Corrected audit C4D04C8B... ran actual priority1 callbacks through
all20 stages and PASS2039 without errors (mountain_atmosphere-verified.log).
This includes real weather day/half/night/return, alternate/disabled/unsupported
fog, original Environment preservation, parameter/array and foreign-resource
preservation. It is still state evidence, not a GPU fog-pixel equivalence test.

The subsequent ten-stage export in session87256 exited0. Candidate2 pack
640eb9d1a91769b3434cef171b95b87577b09ca4968d12c87ea970aac204ec92,
118899272 bytes, gzip114110917. No full35-stage suite or performance pass claimed.
Browser candidate2 uses v97/index.html?rev=2; server revalidates existing assets
by ETag/mtime, rather than immutable caching the overwritten candidate pack.
Candidate2 actual images and visual decision remain pending at this checkpoint.
