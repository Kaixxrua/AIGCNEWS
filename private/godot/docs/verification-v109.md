# v109 — limestone planes and material ownership

Scene-only candidate after the independent v108 rating of8.2–8.5. No8.7
acceptance claim before actual Web day/night review. Boss, combat and backend
work remain deferred. The approved water/weather/sky/focus sources are unchanged.

## Changes

- `meadow_limestone.gdshader` reads the real triangle plane from world-position
  derivatives, aligns it with the mesh normal, and blends65% into daytime bare
  terrace normals. A continuous slope-dependent pigment separates warmer
  shoulders from cooler steep mineral faces. Degenerate derivatives fail closed;
  `rock_plane_strength=0` disables this new block. No outline or random shading.
  Exact night, non-prefix and turf-tagged paths skip this block.
- The targeted prefix includes four real terraces, their backs and toe rocks;
  it is not a screen-space mask of only the most visible left ledge.
- Independent scope review found an inherited material-ownership bug: the scrub
  and ledge-support meshes reused the tagged terrain material despite their own
  vertex IDs starting from zero. Both now duplicate that material and reset
  only their own prefix count to0. This also removes the old accidental AO on
  these14 small support rocks; full night pixel identity is therefore NOT claimed.

## Verification so far

- Native OpenGL GPU test `rock-planes-gpu.log`:26cases PASS, including aligned
  and biased vertex normals on uphill/front/side planes, intermediate and near
  endpoint day values, night, prefix0, turf and tiny-area fallback. Controlled
  strength0/1/0 comparison; restoration exact, near endpoint error <=1/255.
  This tests response and gates, not production cliff aesthetics or normal-vector
  correctness in every mesh.
- Actual scene `rock-material-scope.log`:158checks PASS, four limestone material
  references/four unique instances. Only SolidLimestoneGeology has count317556;
  ScrubStoneSupports, EmbeddedRiverbankStrata and LedgeBreakupStones each have0.
  The two duplicated materials preserve all other queried shader parameters.
- Cache rebuilt once after the scrub helper source change:5bundles52015849bytes,
  signature `b5a4867248b49168461f0fc561833e812dd647ae41ff01be8938c32a0592af9b`.
  This is not a new independent collision-array equivalence claim.
- Shader candidate SHA256
  `cbf37c7b625666a3257f29fdf3a57f713c24d814daebfe8453e88324ee531865`.

Final export uses `export-final.log`; the earlier export predates the helper
ownership correction and is not the Web acceptance build. Web QHD captures,
independent visual judgment and final pack smoke results follow.

## Actual Web result

`day-planes-2k.png` / `night-planes-2k.png` in artifacts/v109 were captured from
verified2560x1440 canvas/DPR1, clock0, paused, at their day/night endpoints.
Both complete frames were personally inspected at original resolution. The
independent reviewer found visible but limited day-plane improvement, with no
obvious night readability regression. Some facet boundaries are too hard and
the long straight grass lip remains. Overall judgment stays8.2–8.5; main's
current subjective estimate is about8.4, not8.7. Do not treat this as final.

Actual exported-pack smoke passed with the fresh five caches, AO apply,31/31
grounded probes, flat Boss clearing and128/128 castle feet. Final PCK122249172
bytes, SHA256`62d030c50ca5cf005d9d2cf8a53e7211f95eb311fa5e0fde723e48b4a9ae0b45`.
The v110 candidate targets a real local top-edge incision and less aggressive
triangle-normal mixing; no visual credit is assigned before its own review.
