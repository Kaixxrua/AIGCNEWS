# v90 — middle foliage light response

Work in progress, not overall reference-fidelity completion. Removes the
ineffective v89 dark-body ALBEDO blend. Retains v88's middle tint and uses
neutral BACKLIGHT .18 only for actual middle leaf triangles; wood retains
pigment*.06, other foliage is unchanged. No new textures, passes, geometry,
blur or emission. Global lighting, approved water and v85 sky are unchanged.

## Executed verification

- Main session46463 exited0. Current source/indexed-mesh CPU material audit,
  probe parse, then material-only ten stages (`20260910-175746-*`) passed.
  Not the full35-stage suite. Five current v77 cache bundles verified before
  export; original walking/Boss/world geometry reused, not regenerated.
- Real WebGL diagnostic tab3, 09:59:12–09:59:29UTC: fixed root600 all12
  records PASS with unchanged thresholds. Day/moon-direction dark-half gain
  .040898635/.01987113 (4207/4217 pixels); improved fractions .981459/.734883.
  Highlight mean maximum-channel delta .032407/.024103; p95 .054902/.035294;
  zero clipping. Wood81pixels and other/foothill8410pixels had zero control
  delta. All zero-light maxima0. Moon wood was measurably lit. No warn/error.
  Probe uses initial day environment with swapped key, no ambient/shadows;
  it is not actual night-endpoint/fullscene acceptance or a frame benchmark.
- Separate true day/night captures `artifacts/v90/day-middle-2k.png` and
  `night-middle-2k.png`: decoded native PNG2560x1440, actual canvas same,
  DPR~1, clock0 paused, blend0/1, complete16:10 composition with sidebars.
  Main personally viewed both originals; overrides restored after capture.
  Bright stars remain visible and moonlit ground remains readable. Main sees
  some additional leaf-layer response, but isolated dark crowns, broad
  vegetation-ground transitions and pale architecture still need work.
- Diagnostic ready22,241ms/download1,699ms/scene2,589ms. Not an ordinary-page
  performance comparison. Separate ordinary tab4, no diagnostic query:
  ready15,453ms/download1,148ms/scene2,160ms, default1920x1080 canvas/DPR1.5,
  no warn/error, night switch and animation play work. Preview handed over
  at night with motion playing; no temporary viewport overrides remain.

Independent original-image review agrees that the daytime leaf-layer gain is
small (R1 clearer than P), nighttime visual gain is unconfirmed, and neither
P nor R1 meets full integration acceptance. No evident protected-scene
regression. Retain as a work-in-progress material baseline, not a declaration
that the dark islands are solved. Next work should soften crown-edge-to-short-
grass transitions through irregular low foliage while preserving crown mass,
real roots/shadows and all movement space, rather than further increasing
one global backlight coefficient. Overall grey cast/architecture remain open.

## Identity and preserved scope

PCK118,858,344 bytes; gzip114,078,042; SHA256
`4cf531c56b181e10a0c8f6077744ecad2ee796fde7706abf7b2423566f83a277`,
independently matched to payload manifest. Leaf shader
`dd218655817268a12de2be516df8d9280edb309502fb3228f0604450b5310335`.
Exact shader/audits frozen in artifacts/v90 final copies. Independent reviews
are in `artifacts/v90/gpu-review.md` and `visual-review.md`.

Water `ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08`,
weather `273b5c384aa3250f480ddf1f984c03d169a5f93c839ff22a6b1bb2feafe7f4ab`,
sky `374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b`,
shared cutout `2f4c660dbeb147725254f5a5c5a50d87971f73ca64c10981404bb6fdc0e6c094`,
ground `33d277d22866ac753550bba094add58ccfe9668f28d506512ba4775d66f0b5ce`
remain the protected v85 sources. No Git writes or recovery-source changes;
bad inherited E:/ Git root required versioned-export/snapshot fallback.

v88/v89 failed efficacy evidence remains preserved, not relabeled successful.
The broader goal stays active; shader probe success must not stand in for
whole-scene art acceptance.
