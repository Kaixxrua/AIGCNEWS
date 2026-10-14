# v113 — rooted far meadow and woodland material integration

Candidate after v112 (main subjective score about 8.4/10). Web visual review is
required before assigning a new score; tests are not art acceptance.

## Changes

- Added a separate, deterministic distant-sward mesh: 2,165 rooted tufts in 167
  open colonies, 51,960 triangles, one material surface, no colliders or tiny
  shadow casters. It uses existing grass pigment, folded leaf geometry and the
  shared animated wind/light field. Every root was ray-planted on cached terrain.
- Prebaked only this additive mesh to `assets/baked/v113/far-sward.scn` (2,004,629
  bytes). Save/reload compared exact mesh arrays and roots. The five old cached
  bundles and AO bytes/source signature are unchanged. Cache SHA256:
  `308f3998727c0393a550f886cad691fdb761e4aad7d12cf9e2d47dcbd3091b92`.
- Dry far daytime terrain reduces the smooth procedural pigment amplitude and
  samples the established grass artwork at 35.26m clump scale, with anisotropic
  mip filtering intact. Scope exclusions and native night endpoint remain.
- Twelve distant groves use shared daytime painted-fill/relief/contact values
  and limited per-source chromatic corrections; their atmospheric foot transition
  follows measured alpha-column bases. Night and unsupported fog restore native
  values exactly. Foreground grove 06/07 and all source PNGs stay untouched.
- Tagged daytime terrace rock reduces per-block random tint, painted-strip
  contribution and triangle-normal emphasis. Real geometry, measured AO, other
  stone batches and the native night endpoint remain. This does not by itself
  solve the repeated rock arrangement; whole-frame review decides its value.

## Run results

- `far-sward-bake.log`: explicit sidecar bake, exact save/reload PASS.
- `rock-planes.log`: original 26 controlled GPU cases PASS, thresholds unchanged;
  source pin updated to reviewed `fb26bc08...`. Not a full-scene pixel proof.
- `far-field-gpu.log`: 7,022 checks PASS, all ten GPU cases complete. Eight scoped
  controls have zero pixel difference. Shared-native changes still need old/new
  full-frame comparison; pure-color fixtures cannot judge grass artwork.
- `far-field-scene.log`: 78,622 checks PASS, actual cached main transitions through
  day/half/night/day. Actual sward root error max .00500012m; height .2415–.7725m;
  reach max .69997m. After reach/wind allowance: minimum road clearance 6.255m,
  water-profile clearance 11.866m, Boss clearance 82.598m. No water reflection
  mask overlap. New geometry audit itself took 308ms, not scene startup time.
- Export/package and native-QHD Web visual review pending at time of this entry.

Protected: water, sky, weather, focus, camera, walking/Boss terrain, existing
cached geometry and AO. No new images generated and no AIGCNEWS integration.
