# v94 — local daytime architecture colour response

Scope: the user's grey daytime castle/village report. Only the
`MEADOW_ARCHITECTURE` path in `meadow_cutout_surface.gdshaderinc` changes.
Water, weather/exposure/fog, sky, geometry, vegetation and window expressions
are protected. Night=1 skips the new pigment operations and retains the old
night fill. Day/night transition values intentionally change.

## Candidate history — do not conflate technical and visual acceptance

1. Surface `422a63cc53fedcab9954b53664166ef1bf270e9e520f873266db1b16531a8de6`:
   rejected. Real Web architecture probe FAILED; day roof flat .058130459,
   profile .057788093 (absolute difference below .01). Moon-direction
   flat0/profile .006242934, control error0. Roof darkening counteracted
   the measured profile response. Original probe/thresholds were not changed.
2. `f604246f6b64d5e552ecaf407fde2851dfdfd1f829a53aa5cf9c5eda152d490b`:
   technical PASS, visible benefit insufficient. Roof ALBEDO restored;
   small wall-only chroma adjustment. Actual Web probe day .058130459 to
   .074182805; moon-direction0 to .010319100; controls0.
3. `0666379548c3d9664bddef3de212959fa680164373bf13309a1c87434b416937`:
   same GPU PASS, visual improvement still too small (main and independent
   review). Reduced daytime painted fill .30–.75 to .10–.50, stronger wall
   chroma. Saved as day/night-candidate3-2k.png. Existing read-only regional
   statistics: castle mean158.612 to158.341, village123.806 to123.635;
   meadow132.134 unchanged. These encoded RGB metrics are not art scores.
4. `3052954debf06a3cca1c62ee1783fda3bf197d18159721d3c496499506e449fe`:
   current candidate. Whole-building daytime ALBEDO chroma×1.25 around its
   own weighted value, bounded per-channel gain, reflectance×.90. This
   applies equally with or without normal profiles; no probe-specific path.
   Retains candidate3's local wall separation and daytime fill attenuation.

Each candidate completed the existing ten-stage material/cache export path,
not the full35-stage suite. Final export session89182 exited0. Three probe
parse checks during build are NOT real GPU execution. Existing geometry
cache signature a697804e3160757ebf23f638fa2b7bfb7dd2b7c5d08145b0ec8d6d17089efc7e
remains current. Old v85 pigment audit's exact-operation contract is no longer
applicable; it was not weakened or reported as passing for this new scope.

Current PCK118870492 bytes, gzip114088754; SHA256
`f3f09bbee7c0cb14332edb254ec60d40d71ae171011ad2d30ad55d5a86d5678a`.
Final candidate real Web GPU and visual acceptance are recorded below after
execution. No performance improvement claim; no assets or rendering passes
were added, but shader arithmetic changed.

## Screenshot discipline

Original native PNG captures use actual canvas2560×1440, DPR approximately1,
clock0 paused, day/night endpoints0/1. The complete16:10 scene is letterboxed
inside QHD. Never upscale or crop. A fresh v93 night baseline was captured at
`artifacts/v94/night-v93-baseline-2k.png`; candidate3's night castle/village
regional means and edge measures match that baseline. This is not a claim
that every image pixel matches: random dragon poses differ, and UI compositor
softness is separately visible. Final candidate needs its own captures.

All candidate shader snapshots and rejected screenshots are preserved in
artifacts/v94. Git still points outside the project to the drive root, so no
Git writes, worktree creation, SSH, hooks or recovery-source edits occurred.
Preview defaults remain v91 pending visual acceptance; v93 vegetation remains
an unfinished visual pass, not retroactively accepted by this building fix.

## Candidate4 executed results / bounded handoff

- Real Web `?rev=4&architecture_audit=1` PASS, unchanged thresholds. Day roof
  flat/profile .0451951498786608/.0593696447710196; moon-direction
  0/.00659552682191133. Control error0 in both, day control .37060549855232.
  Moon-direction margin is small (.0005955); this probe keeps shader night=0
  and is not proof of the actual night endpoint.
- `day-final-2k.png` and `night-final-2k.png`: decoded PNG2560×1440, actual
  canvas2560×1440/DPR1.00000003, pausedclock0/day0 or night1 verified before
  capture. Main inspected original full framing, both bars, castle, tree and
  foreground cliff. Night appearance retains visible windows and readable
  terrain; no claim of every-pixel identity. Small HTML control softness is a
  separate observed compositor issue, not a building-material change.
- Main visual assessment: village roof/stone/shadow colour separation is
  more readable; castle stone is less neutral but still pale overall. Treat
  this as a limited WIP improvement, NOT fully resolved architecture grey
  cast and NOT the complete near-reference goal. Independent final review
  recorded separately in artifacts/v94/visual-review.md when available.
- Normal non-diagnostic preview `http://127.0.0.1:4231/v94/index.html?rev=4`
  loaded with no warn/error. Download1205ms, load15988ms, scene2203ms;
  canvas990×1074/DPR1.5 is the user's current narrow normal panel, not QHD.
  Temporary screenshot overrides cleared; daytime animation resumed.
  Diagnostic page download1359/load22020/scene2071ms is not a stable FPS
  measurement. No performance win claimed.
