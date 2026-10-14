# v111 — far woodland consistency and distant meadow response

Superseded candidate: do not use as a final visual acceptance. v109 was
subjectively about8.4/10, not8.7. No combat or
AIGCNEWS integration in this pass. User's two current issues take priority:
inconsistent distant trees, and distant ground that looks unrendered/flat.

## Scoped changes

- Both existing woodland belts00–05 and new mountain groves00–05 now use
  the same true view-distance fog protocol: daytime canopy optical scale.50,
  root band.75, night1native. Exactly12 distinct registered materials; no
  foreground06/07 change, shared-material mutation, new crop or tree duplication.
  The old ordering was reversed: closer pale belts used full fog while farther
  saturated groves used canopy.30.
- Dry far ground gains mid-scale sward pigment and a bounded real-light normal
  response. Procedural detail fades with actual pixel footprint; existing texture
  filtering and near surface remain unchanged. World-z transition-88 to-132m,
  road/shore/bank/cliff/submerged exclusions. No new collision or grass card.
- Ground-only daytime fog scale.65 within that scope. No Environment, exposure
  or water material edits. A single runtime shader variant adds one define to
  the canonical ground source. All original parameters are retained on switches;
  night1and unsupported fog settings restore the original native shader.
- Includes the separately validated v110 physical notch correction and softer
  limestone normal blend. See verification-v110.md for failed and corrected runs.

## Build evidence

- `artifacts/v111/bake.log`: five geometry bundles,52,020,866bytes;
  source signature`d6edc82e3af84d52d155bb6f9d5e58dab057f3563984e438e8b11530ed634233`.
- Protected water, weather, sky and focus SHA256 values remain identical to v109.
- Fresh AO, native GPU response, pack smoke and original2560×1440day/night
  comparison are pending. None of the source observations is a visual score.

## Completed checks and discovered integration defect

Fresh AO completed:318544bytes,317556prefix vertices,6350880rays,170148ms;
cache files were unchanged during that bake. Pack smoke passed and the actual
helper was included in the pack. PCK122262836bytes, SHA256
`2349805f09139a80d9a6a903c142b17ee61677f0e75e5fc76482c8e4bd9aaf06`.

The first two native fixture runs failed because six uninitialized canopy
uniforms changed fromNil to typed defaults even in untouched controls. Explicit
nonzero fixture inputs fixed this without weakening exact comparisons. Final
`far-field-initialized-gpu.log`:2314checks,10private GPU crops PASS, all eight
protected controls exactly identical. This was NOT proof of scene integration.

Original Web day/night2560×1440PNG captures are day-far-field-2k.png and
night-far-field-2k.png in artifacts/v111, canvas matching,DPR1,clock0,endpoints0/1.
Main and independent review found limited forest improvement, still-flat far
grass, and a slight night foreground/forest-floor separation regression. Not8.7.
The first Web tab crashed; the second eventually loaded in209491ms, download
4415ms,sceneBuild6067ms. Those clock boundaries do not identify the crash cause.

Further cache inspection found a real integration defect introduced in v111:
the offline full-scene bake ran GroundAtmosphere.setup and serialized its
runtime-generated day Shader into terrain.scn. On cache restore that embedded
Shader was not either canonical shader object; the helper's identity guard
silently skipped it. Day fog uniforms therefore did not track night changes.
The private fixtures did not exercise that path. v112 replaces the embedded
material reference and adds a real cached-scene transition check. This defect
must not be projected back onto v109 or claimed as the proven crash cause.
