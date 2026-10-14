# v167 actor-local combat feedback

This completes the combat feedback work recorded in `verification-v166.md`.
The v166 Web review found a real hero-bubble/Boss overlap. The bubble now
prefers the caster's outer side, and both its body and pointer avoid other
actors' current camera-projected body rectangles. The caster's own head,
page controls, caption, bottom bar and damage-number separation remain
protected. It does not hide every bubble to pass the overlap checks.

## Preserved behavior

- Large outlined white hit numbers; gold emphasis for the hero's ultimate.
  Number, displayed health decrease and visible friendly impact share one
  animation clock. Server-confirmed health/rewards remain authoritative.
- Caster-local Chinese skill names ending in `！`, no screen-centred banner.
- Long bottom HP line with no displayed percentage or enclosing heavy frame.
- Final blow, weighted defeat and fade; five verified safe encounter centres
  with no consecutive same-location respawn. Repeated snapshots do not reroll.
- Approved world/water/animation, original/balanced/lite tiers, all 13 actor
  artwork shards and the subset font are unchanged from v166.

## Exact candidate and native checks

- Public artifact: `artifacts/v167`; 152 files, 75 frozen world files preserved.
- Runtime: `camp-presentation-dab2d25c7a12.pck`, 165310 bytes raw,
  60367 gzip / 57503 Brotli bytes. No full-world export or production timing claim.
- Manifest SHA256: `3951235f1ed45f15dae1d51b1ab73748ba30587e13849cf6a2a37bbdd4201be5`.
- Runtime SHA256: `dab2d25c7a12674181b09555f7c0a2fdc5d99f467d758d2ae6adee4ef15263b4`.
- Full wrapper: `6593a3dc97511836d40bbe37f1b96cc0f54d13f8bb847e125a64274678654bd8`.
- Lite wrapper: `a3fa1115fb816dc01185443996789a31461f7d5d8fd0cb2a14569598c18469b1`.
- Renderer: `9d548a6eb31f7daf8039abcdd4e1be3c0308f8ad0e6988b226ecb4ddeda451a0`.
- HUD: `ef8a0a17f8a8b17678f661ac151e3e823c310b49518cb719357bedfd1075997d`.
- Main combined suite: 38408 checks PASS. Independent HUD: 1233 PASS.
- Independent actual-process suite: 67909 checks, zero failures, exit 0;
  `artifacts/camp-hit-sync-native-li9rkksp` contains output, reproducer and
  complete before/after source pins. It covers impact/HP/damage, defeat,
  pause/hidden/stale/missing actors, respawn and visible bubble clearance
  for 13 asset IDs, five skill phases and two different encounter sites.

An earlier new test wrongly expected punctuation in normalized title metadata.
Its failure evidence is retained in `camp-hit-sync-native-3w5t7vxv`. Only that
test was corrected to require BOTH normalized metadata and the complete drawn
Chinese text including `！`. Runtime pins are identical in the failed and
passing test runs; no production behavior was changed to satisfy the assertion.

## Local Web visual verification

Local contact preview loaded the exact full wrapper `6593a3dc9751`. The scene
alone was staged after recoverably archiving v166; the existing frontend,
listener and all other services were retained. Six bounded static HTTP checks
passed. The actual scene receipt SHA256 is
`d5e225aa883717784ac5eecafcbfb2957e1aabf6dc9e323ece398ce6f3d68959`.

Main and independent reviewer inspected original-resolution screenshots from
`artifacts/camp-web-v167`. All 33 day and 29 night sequence captures have a
2560x1440 canvas and PNG, DPR approximately 1, original quality and complete
16:10 letterboxed composition. Sequence JSON records the exact wrapper,
night endpoint, animation state, dimensions and clock with each image.

- Day 000/008: hero's bubble is left of the hero/Boss group, not on the torso.
- Day 016: pet's skill and white 50; day 024: readable white 70.
- Day 029 / night 026: clearly visible gold 290, hero ultimate name and local
  impact effect; bubble does not hide the guardian's body.
- Night 000: readable white 150 and hero skill; night 016: Boss bubble above
  its own head. Text is readable against the unchanged moonlit scene.
- Day 009/010/011 and night 006/007/008 show the final blow, weighted sideward
  kneel/collapse and disappearance; day 013/014 shows the next encounter at
  another site. No obvious foot gap or ground penetration in reviewed poses.
- Bottom HP line remains distinct without a percentage, enclosing card or
  overlap with the caption/buttons. No old screen-centred skill banner.

This is a bounded visual PASS, not proof of 60fps animation, all 13 actors at
all five sites, or exact death timing from roughly one-second image samples.
The independent reviewer notes a nonblocking limitation: the pet bubble in
night 014 is farther from the small deer and its short tail is subtle; its
single-frame ownership is less immediate than the hero's, though it remains
readable and avoids the actors. No claim of perfect bubble ownership is made.

Normal browsing was restored (day, original, playing, no fullscreen or device
override), then the page was scrolled to the complete embedded scene. Ordinary
view screenshots are separately labelled: canvas 1390x868, page PNG 1539x1347,
DPR 1.5, NOT claimed as QHD. The main also checked this smaller whole-scene
presentation; `ordinary-sequence.json` records its native metrics.

No account, reward, timer rule, backend, production service or production
deployment was changed, and no real account battle/reward was exercised.
