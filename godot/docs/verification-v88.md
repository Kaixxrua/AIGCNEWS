# v88 — middle foliage material trial (not accepted)

The source combines v86's neutral leaf BACKLIGHT with a milder inner/outer
middle-leaf tint. No geometry, global lighting, sky, camera or water edits.
Frozen shader and both material probes are in `artifacts/v88/*.final.*`.

## Executed evidence

- Main build session 68149 exited 0. CPU source/actual indexed-mesh material
  audit passed, probe parse passed, then the material-only ten-stage workflow
  completed (`20260910-174005-*`). Not the full 35-stage suite.
- Five v77 bundles matched current source signature
  `a697804e3160757ebf23f638fa2b7bfb7dd2b7c5d08145b0ec8d6d17089efc7e`.
  CPU material audit checked 86,688 leaf and 9,632 wood triangles; wood final
  pigment and nonmiddle shader paths remain the baseline.
- Actual WebGL tab 1 at 09:41:26–09:41:41 UTC, v88 middle-brush diagnostic:
  effective flags resolved correctly; all twelve records completed. Root 600,
  indexed 288,960 corners, 80-triangle fixture, 256-square diagnostic views.
  Overall **FAIL**, not an incomplete/early-exit run. The only failed gate was
  moon-direction dark-half mean gain: .003496 < 2/255. Day dark-half .016841
  passed. Dark-half fractions over two codes .789874/.263932; highlight
  mean maximum-channel deltas .028139/.017574 and p95 .043137/.027451 passed;
  clipping stayed zero. Wood/other/foothill controls had zero delta; all
  zero-incident-light maxima were zero. Directional fixtures used the initial
  day environment, no ambient/shadows, not the actual night endpoint.
- Main inspected native PNG `day-middle-2k.png` and `night-middle-2k.png`,
  decoded 2560x1440, actual canvas same, DPR ~1, clock0 paused, blend0/1,
  complete 16:10 scene with sidebars. Temporary viewport overrides restored.
  Main sees dark crown/grass discontinuities still present, especially at
  night. No claim of full visual acceptance; independent review is in
  `artifacts/v88/visual-review.md`.
- Diagnostic page ready19,701ms/download1,011ms/scene2,133ms. These are not
  ordinary-preview comparative performance measurements.

PCK 118,858,456 bytes; gzip114,078,146; SHA256
`ae93e82ba9cda2807cf1768a50e24456d37933d35bf951eb2e9d2092c584384b`.
Leaf shader SHA256 `d50d98983e31e9191d5e33da66ad629053f127590b1165810e6b42c392b01ffb`.
Water SHA256 `ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08`;
weather `273b5c384aa3250f480ddf1f984c03d169a5f93c839ff22a6b1bb2feafe7f4ab`;
sky `374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b`;
cutout `2f4c660dbeb147725254f5a5c5a50d87971f73ca64c10981404bb6fdc0e6c094`;
ground `33d277d22866ac753550bba094add58ccfe9668f28d506512ba4775d66f0b5ce`.

## Next action

v89 tests a local leaf-body reflectance blend, removing some inherited dark
soil coloration from raised foliage. It does not brighten global lighting or
introduce emission. Existing GPU thresholds are not weakened to accept v88.
The goal remains incomplete; v85 stays the default preview pending acceptance.
