# v98 — mountain-foot integration, in progress

The previous user-requested status checks did not advance production and repeated
the same quality assessment. The present development pass must produce a visible
change at ordinary whole-scene scale, not a higher self-assigned score.

## Baseline and direction

Current source and exported v97 pack were rechecked. Baseline pack SHA256:
640eb9d1a91769b3434cef171b95b87577b09ca4968d12c87ea970aac204ec92.
Day/night baseline PNGs are artifacts/v97/day-atmosphere-2k.png and
night-atmosphere-2k.png: decoded PNG2560x1440, actual canvas2560x1440,
DPR1, day/night0/1, paused clock0, complete16:10 framing with side letterbox.
Main and independent review see a hard dark mountain-foot/bright meadow join,
a detached village, excessive broken rock contrast, and uneven asset integration.
v97 candidate2 is limited net progress, not the approximately8.7 visual threshold.

This pass gives the mountain base actual rolling land and rooted woody crowns.
The shape and its forest soil must work together, not as a straight row or dark
stripe. Preserve the approved river, near gameplay, building foundations, readable
night and existing animation. No new raster or duplicated tree image is involved.

## Isolation and verification plan

Read-only Git checks still resolve to E:/ and E:/.git, not an isolated project.
No Git mutation. Scoped v97 source snapshots are stored beside v98 artifacts.
Implementation, independent visual review and regression/integration discovery
are split across the three existing agents; main owns integration and builds.

New terrain is limited to z(-327,-225) and x<-24 or x>166. Height field, normals
and collision are generated together; the castle footprint, village, river and
playable terrain must be independently compared against the frozen v97 source.
One added crown batch is limited to18000triangles and actual terrain-ray roots.
The source-signature list includes the new landform; caches must be really rebaked.
Existing narrow source-hash audits are not re-labelled universal v98 tests.

Actual build, measured bounds, QHD images, startup performance and visual verdict
are pending. No tests or quality pass is claimed at this checkpoint.

## First candidate executed checks

Real procedural bake session92295 exited0: five geometry bundles,52021204bytes,
signature6403c778b9265ab795e93967548d3943c08d11ced37ed330562305899981ca90.
All128crown placements accepted:16896triangles, one extra leaf/branch batch;
headless build87-107ms is not a browser GPU or end-to-end performance measurement.
The actual current terrain feeds collision, normals and ray-grounded crown roots.

Independent new audit in session48443 PASS456550:87970 protected vertices exact
v97,2591 far vertices changed, actual128crowns/16896triangles, root-error0 within
its0.003m tolerance, crown heights1.478221..6.512055m. This tests actual mesh data,
roots, unique crowns, range and unchanged near heights, not artistic quality.

Two old-scope failures are retained, not waived as passes:

- MaterialOnly stopped at foliage-tone-check: that reflectance-only audit demands
  every terrain channel remain exactly v76, contradicting this intended far-land
  edit. It did not export or complete its ten-stage path.
- Original lighting audit reached its legacy shore_regression call after the
  day/night/return checks, then failed on a far terrain normal at z=-327. The
  terrain_normal finite difference samples0.22m into the new slope. This remains
  an overall FAIL; it is not a clean lighting PASS and no old gate was loosened.

For this geometry candidate, actual independent terrain/collision protection and
existing scene source smoke evidence replace the inapplicable whole-old-terrain
invariant. Session43800 then ran original dragon audit, export, exported-pack smoke,
payload preparation and loopback preview check, exiting0. No full35-stage suite or
MATERIAL_ONLY COMPLETE is claimed. Runtime day/night rendering still needs review.
Exported PCK118908476bytes/gzip114116860, SHA256
1b5bab380d84dffc2ba57d357175f6434545adcc1c3828c19dad890d9d4f0f80.
Browser candidate is v98/index.html?rev=1, currently awaiting actual first frame.

## First actual browser review: rejected

Both day-foothill-2k.png and night-foothill-2k.png are decoded PNG2560x1440,
canvas2560x1440/DPR1, paused clock0, day/night0/1 and complete side-letterboxed
framing. Main and independent reviewer reject the first candidate as a net visual
improvement: shallow bright crowns form a pale decorative seam and the new hills
look like smooth plinths. The unchanged readable night/water is not a quality pass.

Observed first browser load: download2634ms, scene-build6002ms, total127994ms;
initial viewport1042x898 at DPR1.5 before the QHD calibration. No comparable
performance improvement is claimed. GPU startup/compilation remains expensive.

## Second candidate in progress

Slope amplitude reduced to55%; woodland replaced by100 independently shaped
crowns with600 closed leaf lobes, no additional PNG or repeated cutout. One batch,
17200triangles. A new shared sunlight-only field targets near dry terrain, opaque
plants and stone; the original weather/sky/water/focus files remain unchanged.
Real-light shader equivalence and whole-frame WebGL review must precede acceptance.

The first bake invocation omitted its required --rebuild-static flag and failed
before writing caches; its stopped process/log remain recorded as a failure.
Corrected source bake session7916 exited0:5bundles,52017852bytes,
signature3424d1630a47b6f1b2b0531ab2b3cedb3dd622e42ab69787202a8fad14a104f3.
Actual-volume audit session29568 exited0:600closed positive-volume lobes, outward
normals,100crowns/17200triangles, exact87970protected terrain vertices,2591far
vertices changed. This is geometry evidence, not a visual score.

First native GPU sunlight probe failed ground direct-light parity while ambient
and zero-light controls matched. Investigating terrain's implicit GLES Lambert
versus explicitly Burley plant/stone wrappers; no tolerance was relaxed and no
GPU pass or second-candidate export is claimed at this checkpoint.

## Next product stage

User asks to move to Boss/character/combat assets at approximately8.7/10 overall
HD-2D quality. Do not reduce the final scope or inflate a score to pass this gate.
The AIGCNEWS integration source was located and read: private PRD v0.2 and its
existing backend contract, not the superseded v0.1 draft. Reuse its account/time/
reward boundaries; do not copy private backend implementation into this workspace
or deploy/enable real rewards as a side effect of visual work.
