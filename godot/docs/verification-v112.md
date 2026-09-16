# v112 — far sward sampling and canonical cached ground

Candidate pending final Web comparison. Preserves v111 forest fog unification,
v110 corrected physical notch, and all approved water/weather/sky/focus sources.

## Material and cache changes

- Static native/day ground wrappers now share one implementation include.
  Initial expansion was byte-for-byte equal to the prior source/generated day
  shader. No runtime Shader.code construction remains.
- Only daytime dry far sward additionally samples the existing grass artwork
  at a clump-sized26.8m texture scale. Bounded source-ratio modulation(.64–1.36,
  weight.72) restores medium detail while retaining terrain/woodland pigments.
  Existing anisotropic mip filtering remains. No new image or landscape card.
- Far detail fades at pixel footprints1.1–3m; dry-height fade is-.1 to.05m.
  Low-lying grass at y0is still above water(-1.05m). Other road/shore/bank/cliff/
  submerged masks and full-night exclusion remain. Surface-gradient normal
  response reuses one clump-height sample rather than evaluating it three times.
-20actual cached-terrain ray samples in v111/far-sward-footprint.log show most
  selected positions around.3–1m per pixel, with two above2.2m. This is a geometric
  finite-difference diagnosis, not exact shader derivatives or visibility.
- normalize_ground_cache.gd first diagnosed, then explicitly repaired only
  the cached ground material to reference the canonical native shader. Exact
  raw mesh data, stored tree/placement/parameters and552000collider corners
  survived save/reload. Backup:artifacts/v112/terrain.pre-normalize.scn.
  Terrain file SHA256 now
  `b44e2c8c33fe4369d872fcb6ad3aa74180aac5463f18ae2eaadfb07ea4fc2771`;
  AO terrain geometry signature stayed
  `571794e952149047ce6296cf39d5021fcbcc420a7684496a023e884ffbb94e97`.
  The AO binary was not changed/rebaked; its cache-file provenance hashes record
  the historical bake, while runtime compatibility verifies actual mesh data.
- GroundAtmosphere skips runtime changes during --rebuild-static and disables
  processing there, preventing recurrence. Normal setup reports a noncanonical
  cache identity instead of silently ignoring it.

## Verification status

- Native private GPU/helper fixtures:2318checks,10crops PASS; all eight protected
  controls exact0pixel difference. This run predates only the setup/bake guard,
  not the revised material math. Actual cached-scene transitions follow.
- Export, actual pack smoke, native QHD Web day/night, startup and animation
  verification pending. No new score assigned from test counts.

### Runtime integration and package

`far-field-scene.log`:2553checks PASS on the real cached main scene. Actual
Weather callbacks and both atmosphere instances were exercised at day0,half.5,
night1,and return-day0. Ground shader object identity now changes between the
two canonical resources; current environment density/linear colour reach the
day variant, and night restores native fog. All12actual grove materials remain
registered independently; foreground06/07 bindings and parameters stay intact.
This is the integration case missing from the v111 private fixtures.

Export and actual PCK smoke passed, including current5cache bundles, AO apply,
31/31grounded probes, flat Boss clearing, bridge/city/vegetation root markers,
and no engine errors. PCK122259348bytes, gzip117475775bytes, SHA256
`953ed8c7f9341f4f10f1a4023681f391501f18ae3c1fd5c0f1bfcaba5a2e9a45`.
Actual Web visual/startup acceptance remains separate.
