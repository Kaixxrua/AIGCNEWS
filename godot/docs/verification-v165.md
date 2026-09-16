# v165 combat proportions

Scope: after the accepted bottom-center long Boss HP bar, increase the
guardian's presence and distinguish companion body sizes. Preserve the
approved world, original artwork, all quality tiers, bottom HUD, account
state, damage, death timing and reward settlement.

The display-only scale multiplies sprite pixel size, visible-alpha heads,
contact shadows and terrain footprint together; root transforms stay at
unit scale with feet sampled from the same terrain. Catalogue/PNG bytes
are unchanged. Hero scale is 1.10 and Boss scale is 2.0 relative to v164.
The guardian moves 0.60m right and 0.25m back inside the existing clearing;
heroes move 0.20m left to preserve space beside its enlarged shoulders.
Its own layer-isolated night fill stays above the enlarged head; it does
not light the world or water.

The six source heroes' median idle visible heights become about 2.17-2.41m;
the guardian becomes about 7.64m, roughly 3.17-3.52 times as tall. These are
alpha>=32 foot-to-head artwork measurements, not a promise that crouching,
attacking or projected silhouettes have an identical ratio in every frame.

Pet display multipliers are species-specific: deer .90, fox .94, rabbit .60,
owl .62, finch .68 and juvenile dragon .93. Grounded roots, hover height,
flap/bob timing and the world's existing wildlife are retained. The change
does not shrink or reposition the independently approved wild animals.

## Candidate artifact

Single public build: `camp-presentation/scale-01`, `camp-bootstrap/scale-01`
and `artifacts/v165`; no world export or frontend rebuild. Runtime is
89,886 raw / 23,682 gzip / 22,412 Brotli bytes, only 975 extra gzip bytes
over v164. All 75 frozen world files and 13 original actor shards are reused.
This is a byte measurement, not a production network timing claim.

Runtime SHA256:
`23f3276261d58969e1900c64090d0101607ef3b86500c762e7c36d2c9e8f813e`.
Public manifest SHA256:
`fa4b75c3648ea105c0b81699455d2b902007afb6ba0b1697d6967275847f4376`.
Full wrapper `fc480e11393d`, lite wrapper `82fbd7d4c71b` retain their
unchanged selected-world pins. HUD is byte-identical to v164.

Skill source/target points now use the current alpha-visible body height,
including sprite-only hover/death offsets. Local flashes/ribbons use a mild
bounded size factor (0.85-1.30); arena-wide circles, choreography timing and
the three-mesh/6,000-vertex-per-role limit are unchanged. No new damage or
reward authority exists in these display calculations.

## Independent native and terrain verification

- Final combined presentation/effects/HUD regression: 38,359 checks, PASS.
- New original-art scale suite: 5,894 checks, PASS, all 13 actors x 32 frames.
  Actual idle Boss/hero ratio envelope is 3.137-3.545; Boss visible height is
  7.594-7.641m. Source PNG bytes, registration and unit root scales match.
- Real frozen native-twin terrain/core probe: 581 checks, PASS. All 13 scaled
  footprints and full lunge paths are safe against the actual terrain/river/
  rock predicates; all twelve detail chunks apply. Boss support radius is
  2.04m with 0.199m arena margin. The smallest margin is the existing flying
  dragon station at 0.0749m; do not expand it without rechecking.
- The actual-terrain artwork probe mounts the selected Ranger/Deer/Guardian;
  all thirteen descriptor footprints are tested there. The separate original-
  art suite mounts all thirteen original cutouts. Neither is a GPU/visual or
  production-load timing claim.

Evidence: `artifacts/camp-scale-v165/regression-progress.json`,
`scale-result.json` in that directory, and
`artifacts/camp-bootstrap/actual-scale-v165-01/actual-core-result.json`.
Main's final Web visual acceptance is recorded separately below.

## Actual contact-page acceptance

The existing local contact page now serves v165. Six scene-only static HTTP
checks pass, with runtime/decoded gzip and both wrappers matching the reviewed
pins. Only the scene directory was switched; v164 is recoverably archived in
the private preview workspace. The frontend, backend, account state, Nginx/CSP
and accepted source-world/actor PNGs were not changed by this scale follow-up.

Final original-quality pair: `artifacts/v165/boss-pressure-live-day-2k.png`
and `boss-pressure-live-night-2k.png` in the same directory, with accompanying
`.capture.json`. Both files and canvases are natively 2560x1440 at DPR ~1,
complete 16:10 composition with side letterboxing, the same paused world clock
142.065, night blend 0/1, and full wrapper `fc480e11393d`.

Main and independent visual review accept these live frames: clear large-Boss
presence, separate hero/deer silhouettes, no obvious detached-foot gap, readable
night stone/character detail and an unobstructed bottom 42% long HP bar. This is
a static-frame review of the current trio, not a claim to have visually sampled
every combination and every attack pose. The separate native checks cover all
thirteen actors' registration and bounded paths.

`boss-pressure-day-2k.png` is a post-death observation-phase diagnostic with no
visible Boss; it is NOT the scale acceptance image. World-clock values alone
cannot identify the optional choreography phase because mounting starts later.

The original user contact tab was retained and restored to normal viewport,
non-fullscreen, original quality, daytime and playing animation. Temporary QHD
device/viewport overrides were cleared. No extra QA tabs remain.
