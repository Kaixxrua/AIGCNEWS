# v92 — rejected central tall-leaf transition

**Not accepted as a visual improvement.** The central patch9 experiment made
its ground-origin leaf fans taller, but they read as an added tuft of bright
pointed grass rather than a natural crown-to-turf transition. Independent
day/night original-image review rejected the net integration benefit, and the
main agent agrees. Preserve candidate source, exports and images as failed
evidence; do not promote preview defaults or claim the plant goal completed.

## Executed evidence

- Candidate source SHA256
  `0525fb17beb40c73af71aa97f14f5492110e0c4bd105a1d468e54427b44ae804`.
  Frozen as `artifacts/v92/meadow_edge_growth.rejected.gd`.
- Original v91 fringe geometry audit exited0/PASS: 611 supported roots,
  16,608 triangles, nine old mesh/collision snapshots exact; radius .68169m
  plus .06m wind; road/Boss/river/habitat margins
  1.657508/19.01693/7.903976/4.484672m. These are technical checks, not art approval.
- New independent same-world isolation audit exited0/PASS: every root and
  actual vertex/normal/color/UV/UV2 in the other thirteen patches exactly
  matches frozen v91. Patch9 changed actual triangle geometry: 49→55 roots,
  1,338→1,482 triangles, mean root crown height .244785→.629495m,
  maximum .345810→.700000m. Old five cache files and nine world snapshots
  remain exact. Baseline/current build464/524ms are diagnostic headless
  sequential observations, not a controlled Web performance comparison.
- Single export session91002 exited0, `20260910-183858-*`: ten-stage existing
  cache/material workflow. NOT full35 stages; new geometry/isolation checks
  were separately run. PCK118,866,028 bytes/gzip114,085,672; actual SHA matches
  manifest `77b6c9641233a88be327985832c0658a32dce7cb42664390ad1bb77ca715f922`.
- Real day/night original PNGs under artifacts/v92:
  `day-transition-2k.png`, `night-transition-2k.png`. Native2560x1440 decoded
  PNG, canvas same, DPR~1, clock0 paused, endpoints0/1, full16:10 scene with
  sidebars. Main and independent reviewer inspected originals against v91.
  Dragon random initial pose differs; excluded from comparison. Overrides
  restored after capture. Old/world/water/sky shaders unchanged.

## Performance observations, not an optimization claim

First ordinary tab6, coexisting with playing v91: download34946ms,
load38939ms, parent6651ms plus fringe517ms; startup samples6/6/5FPS,
158calls and2,780,250 visible primitives. No warn/error. This was a genuine
slow observation; competition is a possible confound, not a proven cause.

Both old tabs then closed. Fresh sole ordinary tab7, canvas1920x1080/DPR1.5,
day0 pausedclock0, no concurrent engine: download1378ms, load15725ms,
parent2147ms plus fringe529ms. Samples at10:48:33/38/43UTC were43/42/42FPS,
158calls and2,780,250 visible primitives. The first severe slowdown did not
reproduce, but this neither proves its root cause nor establishes unchanged
performance versus v91, stable animated FPS, or a2K frame-rate claim.

## Next implementation

Keep v91's fine outer low foliage; replace the rejected ground-origin long
fans with actual short branching plants carrying smaller leaves at several
heights. The old fringe and all protected geometry should remain intact.
New attachment topology requires an independent geometry test, not lowering
the old common-ground-root leaf-fan test until the rejected design passes.
This local experiment does not redefine the overall reference-fidelity goal.
