# v168 continuous travel after Boss respawn

The user reported that companions reset/teleport when the Boss respawns.
The presentation now retains each placed companion's actual feet and walks
to the next encounter station. A new Boss may appear at its new location;
the party does not instantly move with it.

## Behavior and scope

- Choose a nonrepeating, reachable encounter site using the existing five
  centres and real terrain/body-clearance predicates. Unreachable routes
  hold existing companions in place; a fresh same-round snapshot can retry
  the original destination rather than teleport or reroll it.
- Travel is bounded to 2.2 m/s in ground-following 3D distance. Walk frames
  follow actual distance; facing follows movement. Hover companions retain
  grounded roots and shadows with their separate hover animation.
- Freeze combat choreography while travelling: no cast bubble, impact,
  damage number or displayed HP drain until the party arrives. Confirmed
  server HP remains queued for visible impact, not replaced by local rules.
- Pause, stale/hidden state and missing assets cannot catch up by teleport.
  Late actor-pack swaps retain feet. Completed-Boss cooldown swaps do not
  resurrect the Boss, and in-round swaps return to the retained pose target.
- Preserve world art, water, actor artwork, original/balanced/lite quality,
  death animation, bottom health line and actor-local combat feedback.
  No backend, account, timer, reward or production changes.

## Exact final candidate

- Artifact: `artifacts/v168`; 152 files, 75 frozen world files, 13 actor shards.
- Renderer SHA256: `c1795e8e3b47936bb9e8349b53840276b2c445c4d97c2b28fa6bdbb9a45dd588`.
- Path helper SHA256: `e9a4cbebf1978b1595ae9344643476d4c22deba65ab7886ba21de2a390e4b2a5`.
- Manifest SHA256: `4df3ef25151784e328b058491573b1b015f042d5716b9a666c8b09243b33d6dd`.
- Runtime: `camp-presentation-5a85eb2a20de.pck`, 185150 raw,
  66079 gzip / 62325 Brotli bytes.
- Runtime SHA256: `5a85eb2a20de9dc8141c516a3d7f0dbe4fa55931f765c6acb9b9b1e6817cf401`.
- Full wrapper SHA256: `9e46b2f8932fcaecaaad47bef09abc8475e65f62df2ee425b2fb73d480717aad`.
- Lite wrapper SHA256: `fd844800a8d0e6be705b6a9e6bc6feaeaf7cc4cf7c190f70980b1fa714745a61`.
- Build inputs: `artifacts/camp-presentation/travel-02` and
  `artifacts/camp-bootstrap/travel-02`. The earlier unserved candidate is
  recoverably retained as `artifacts/v168-candidate-01`.

## Native and packaging checks

- Main combined presentation/effect suite: 38422 checks PASS.
- Independent helper: 454 checks PASS. Presentation builder: 18 tests PASS;
  bootstrap builder: 11 tests PASS, including five-script exact-byte checks.
- Independent final renderer suites: 60714 continuity checks and 135392
  hit-sync checks; zero failures, exit 0, no SCRIPT ERROR/ERROR. Source pins
  were unchanged before/after. Evidence and exact reproducer are under
  `artifacts/camp-travel-final-3drr1efv`.
- These cover actual process-driven travel, three guest round boundaries,
  formal round changes from lunging poses, all 13 styles, pause/hidden/stale,
  blocked/recovered routes, cooldown ground-to-hover swaps and queued final
  hits/death. Continuous tests do not assign feet or animation clocks.
- Independent real terrain: 926 checks PASS over 128 routes across core
  and all 12 original-detail chunks, using unchanged actual body radii and
  a dense independent terrain/Boss-clearance oracle. Each origin/loadout
  retains a verified nonrepeating common destination at station baselines.
  Evidence: `artifacts/camp-travel-v168/terrain-clearance-handoff.md`.

The terrain test measured ordinary native planning at roughly 60–235 ms per
actor and several Boss-body detours near four seconds. The final renderer
analytically rejects those direct-line/Boss conflicts before attempting
respawn planning and tries another candidate. This is a bounded mitigation,
not a claim of hitch-free Web performance or production latency. The terrain
survey is not exhaustive proof for every intermediate moving-root position;
runtime still checks actual current roots and real terrain on every move.

Main independently checked the retained real-terrain result: all 60
common-target routes in each terrain phase are safe two-vertex direct paths.
Their minimum analytic Boss margin after the extra planning buffer is
0.620000286 m. Thus the final respawn filter retains the surveyed common
destinations; it does not require accepting the slow body-detour candidates.

## Local Web acceptance

The scene-only v168 stage passed, with v167 archived recoverably. Six bounded
static HTTP checks passed. The existing frontend's 4970 files / 654 folders,
configuration and listener identity were unchanged; no service was restarted.
Receipt SHA256:
`f87986ad19b869fb4bab2a0b24fa3a3dbd1b23b5dab426aab79dd97889300800`.
Static HTTP proof SHA256:
`da3bdaf16bc59306b1b981e3b2e69c48ac49ee6e895ec29f4340703805ed4f3a`.

The actual local contact-page browser loaded full wrapper `9e46b2f8932f`.
Evidence is under `artifacts/camp-web-v168`: 49 day frames over 45.8 seconds
and 37 night frames over 40.5 seconds. Both sequence JSON files record actual
2560x1440 canvas and native PNG, DPR approximately 1, original quality,
playing motion and endpoint night blend 0/1. No screenshot was upscaled.
The full 16:10 composition, castle, foreground cliff and side bars were
personally inspected, not inferred from file dimensions.

- Day 018: both companions wait at the former site after Boss disappearance.
  Day 019: the new Boss appears up/left while companions start from their
  old vicinity. Day 020: both are visibly midway, with walking poses.
  Day 021: they reach the new station and the hero begins its skill.
  Day 022: the first white 80 and impact ring appear after arrival.
  During day 019/020 the bottom line stays full and there is no skill bubble,
  damage number or attack effect. Main and the independent reviewer agree.
- Night 012/013: companions retain the previous site. Night 014/015 show
  successive rightward walking positions towards the new Boss, with full
  HP and no combat feedback. Night 016 reaches the new station and resumes
  the hero's skill. Feet and party remain readable under the retained
  moonlight; no obvious floating gap appeared in these reviewed frames.
  The independent night review agrees after inspecting 14 full original
  frames, including 013–018: white 80 / pet 50 follow arrival in 017/018.
  Night 028 retains the readable gold 290. One nonblocking observation is
  that the pet bubble in 018 crosses part of background nocturnal wildlife;
  it does not obscure the three combat actors and is outside this fix.
- The independent day review also checked final hit/death/disappearance in
  014/015/016, a gold ultimate number in 034 and post-arrival pet feedback in
  023/024. Existing bottom HP line, local bubbles and page controls remain
  separated. The main inspected the unchanged complete world and water in
  both lighting endpoints and the normal embedded presentation.

This is bounded visual acceptance of Ranger + Deer in sampled actual Web
travel, not proof of 60fps, no single-frame foot sliding, all 13 characters
at all sites, or a real-account battle/reward. A roughly one-second capture
interval cannot support those stronger claims. Day 019 briefly puts the new
Boss's foot silhouette near the hero's head/shoulder in projection; day 020
separates them and neither remains persistently obscured.

Browser handoff restored day/original/playing, no fullscreen and no temporary
viewport/device override. `ordinary-restored.json` records the separate normal
view: canvas 1390x868, PNG 1539x1347, DPR 1.5, viewport 1026x898. This ordinary
capture is explicitly not QHD. The page is left at the complete embedded scene.
