# v163 combat presentation — 2026-09-13

Scope: add a Boss HP bar, role-specific skills, hero/Boss ultimates and a
confirmed-zero-HP death presentation to the accepted world. Account rules,
damage computation and reward settlement remain outside this public project.

## Runtime boundary

- Protocol v1 accepts exactly the original seven display fields, or those seven
  plus the paired `bossHp` / `bossMaxHp` integer fields. A `defeated` snapshot
  requires zero HP, a display nonce and all selected roles. The renderer sends
  no damage, cast, death, random draw or reward instruction upstream.
- The signed-in site supplies confirmed HP. Its completion transition holds a
  short death presentation; neither elapsed animation time nor reaching a
  local visual endpoint can settle an account reward.
- Guest observation has no DEMO label. The site clearly says observation and
  explains that participating in drops requires signing in and starting.
- Old seven-field callers are retained for compatibility, not silently
  reinterpreted as the new health contract.

## Presentation

- Three reusable mesh slots implement hero, pet and Boss effects. No new PNG,
  particle-spawn queue, autonomous timer, world light or scene rebuild.
- Six hero skill/ultimate identities and six pet skill identities; Boss runic
  attack, anticipation ring, area strike and breakup/fade on confirmed death.
- The common pauseable clock controls pose, trails and death. Hidden parents,
  local pause and stale state do not advance combat animation.
- HP uses received values, with a cosmetic trailing bar. The bar follows each
  frame's visible alpha-art head rather than transparent atlas headroom. Its
  one-time scan matches the existing alpha cutoff (32/255); alpha1–31 cleanup
  noise must not count as the head. No PNG or its alpha is changed.
- The world's priority-126 focus composite initially erased transparent
  effects. Combat surfaces and the blended dying Boss now render at 127 with
  depth testing retained. Living actors revert to priority 0. The approved
  focus shader and water remain unchanged.

## Immutable assets and cost

Candidate: `artifacts/v163`, built from `camp-presentation/combat-05` and
`camp-bootstrap/combat-05`.

- Staged production payload: 152 files; all 75 frozen-world pins preserved.
- All 13 actor shards and their original PNGs are reused byte for byte.
- Optional runtime: 86,686 bytes raw / 22,703 gzip / 21,458 Brotli.
- Runtime SHA-256:
  `057684c616a1894223f3fad2f35d34bbb5671fd827f31e13704f49f73c150421`.
- Runtime gzip grows 13,072 bytes over v158's 9,631-byte runtime; this is a
  post-core script cost, not another multi-megabyte texture download.
- Wrappers: 20,400 bytes raw; lite gzip 6,558, full gzip 6,598.
- These are measured artifact sizes, not cold-load or production timing claims.

## Verification status

The isolated HTML tool in `artifacts/v160/qa.html` selects v162 and sends
explicitly synthetic display snapshots. It is only a visual harness and is not
included in the v163 production manifest. It does not connect to accounts or
perform settlement. Native/bridge regression is complete; final contact-page
integration/visual acceptance follows separately below.

Independent final regression (combat-05 source and exact mounted bytes):

- Native presentation: 37,866 checks, zero failures, including threshold heads,
  hidden clocks, HP, death, pose and actual generated effect vertices.
- Actual frozen core + three actors + all twelve detail chunks: 564 checks.
- Wrapper checks: 64 / 64 / 68; selected-actor shard checks: 58.
- Bridge/boot/integration JavaScript: 91 tests.
- Builder self-tests: 14 + 10. Main separately reran both successfully.
- Exact full/lite wrapper pins, three quality cores and all 39 actor transport
  artifacts are preserved. The logs and reproduction commands are in
  `artifacts/camp-regression-v163/summary.json`.
- These CPU/native assertions are not a GPU performance measurement and do not
  replace visual acceptance. v162 hero-impact day/night PNGs have verified
  2560×1440 canvases and files, but predate the final alpha-threshold head fix.

Discard v159 as an early diagnostic compile-failure build. v160 screenshots
show the overwritten-effects bug. v161's first incorrectly sized captures
are diagnostics, not QHD acceptance evidence. Every accepted image must have
actual 2560×1440 canvas and PNG dimensions, complete framing and recorded phase.

## Contact-page integration, followed by v164 bottom-bar request

The privately assembled v163 contact page was exercised through the actual
browser: sign in with a fresh isolated test account, explicitly start a new
round, receive real server HP updates, complete the round, inspect the reward
and round-history panels, then explicitly pause and sign out. The completed
Boss was absent while companions remained. The original-quality capture
`artifacts/v163/contact-real-defeated-day.png` has verified 2560×1440 canvas,
PNG, DPR approximately 1 and complete framing. This is a local synthetic
account verification, not a deployment or a grant of real production benefits.
Detailed business evidence remains only in the private backend workspace.

The user's subsequent request replaces the head-following bar with one fixed
long bar at bottom center. v164 changes only HUD and its tests, retaining the
verified renderer/effects and confirmed-health/death behavior:

- Width is 67% of the letterboxed 16:10 world; it cannot stretch across the
  black side bars. Bottom reservation reaches 90 pixels at QHD to clear the
  website's fullscreen caption/buttons. Narrow viewports are bounded.
- The existing `present` API is retained; moving the anchor cannot move the
  bar. No duplicate head bar. The upper ultimate strip is preserved.
- HUD's independent tests: 432 checks. Combined native regression: 38,359
  checks, zero failures. All prior HP, zero-death, alpha-threshold, pause,
  hidden-parent and role-effect coverage remains.
- Exact runtime and wrapper pins were independently checked in v164.
  Renderer/effects and all 13 actor shard pins are unchanged from v163.
  Actual-core verification above is not falsely represented as rerun for this
  HUD-only follow-up.
- v164 / combat-06 runtime: 86,654 raw / 22,707 gzip / 21,461 Brotli bytes;
  SHA-256 `1395cbe95e20af0c796b31673b37d990ab764794352afb48298a0eb3fca6bf3d`.
- Native log and exact-byte proof:
  `artifacts/camp-regression-v164/native-bottom-hud.log` and
  `staged-pin-proof.json` in the same directory.

v164 has been privately staged at the existing local contact preview. Six
read-only HTTP checks confirm the new scene, exact compressed/decoded runtime
pins and unchanged headers. v163's stage is recoverably archived, not deleted.
No account logic, backend/Nginx restart, CSP change or frontend rebuild was
part of this final HUD change. Web visual verification follows below.

Final v164 HUD acceptance passed in the actual local contact page. The live
64% bar is fixed at bottom center in the original-quality day/night pair:
`artifacts/v164/contact-bottom-hp-live-day-2k.png` and
`artifacts/v164/contact-bottom-hp-live-night-2k.png`. Their `.capture.json`
records confirm 2560x1440 canvas and PNG, DPR approximately 1, full letterboxed
framing and the identical paused world clock 228.753 (night blend 0 / 1).
Main and independent visual review both confirm clear red fill/percentage,
no head-bar duplicate and no overlap with the website caption or controls.
The ordinary-sized contact-page preview was also checked and restored to
daytime animation, with temporary viewport/fullscreen overrides removed.
The earlier `contact-bottom-hp-day-2k.png` captured 0% during death and is only
a layout/death-phase diagnostic, not evidence of live red-fill readability.

`artifacts/v162/qa-defeated-night-2k.png` is a diagnostic 2583×1551 capture despite
its historical filename; do not use it as QHD evidence. The actual-contact v163
defeated-day image described above is the valid complete QHD death endpoint.
