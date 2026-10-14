# v95 — diagnose and reduce daytime architecture fog veil

Previous goal turn was progress: v94 made a small building-pigment improvement,
but main and independent review still judged the whole castle too pale. Goal
is active; neither buildings nor the complete near-reference scene are done.

## Actual runtime decomposition, before production changes

Diagnostic export session80137 exited0, ten-stage material/cache workflow
(not35-stage full suite). Production shader was exactly v94 candidate4.
Web URL used both architecture_audit=1 and architecture_layers=1. The opt-in
test reads the actual scene viewport/camera, changes one setting, reads pixels,
then restores original Environment and material references before analysis.
The old isolated roof probe and its thresholds are retained.

All five records: day0, clock0, paused, not transitioning. Actual GPU readback
1728×1080, logical viewport1280×800. The browser QHD override landed after the
diagnostic; these measurements are NOT 2K acceptance screenshots. Castle ROI
x774,y79,w640,h215; village x173,y213,w365,h80. Rectangles include some
background/occlusion and are not semantic building-only masks.

| Single-variable experiment | Castle mean/stddev | Village mean/stddev |
|---|---|---|
| Baseline | .620966 / .110520 | .473248 / .125333 |
| Fog disabled | .456112 / .252067 | .206929 / .196119 |
| Environment ambient disabled | .616641 / .111469 | .467876 / .122213 |
| painted_fill=0 | .638591 / .105274 | .502571 / .133646 |
| Restored | .620966 / .110520 | .473248 / .125333 |

Values are weighted display-code RGB, not physical luminance or a quality
score. All baseline/restored region statistics match as printed. No warn/error.
painted_fill=0 also raises ALBEDO's factor from .82 to1, so that experiment is
explicitly NOT pure emission removal. Environment ambient=0 does not turn off
the .18 directional DaySkyBounce. No actual image acceptance is inferred.

Actual fog: enabled, mode0 exponential, density.00042, height_density0,
colour(.54,.69,.82), energy1, aerial0, sun_scatter0, sky_affect.08.
AgX exposure2/contrast1.45; ambient .22. Castle art_exposure is .94 and village
.84: architecture profile setup overrides earlier builder values. Source PNGs
have warm walls, dark roofs/wood and baked shade; they are not neutral grey.

This ranks fog as the largest measured washout contribution among these tested
settings, not proof that it is the sole cause or a reason to globally remove fog.

## Pinned engine evidence and implementation contract

[GLES scene.glsl](https://github.com/godotengine/godot/blob/4.7.2-stable/drivers/gles3/shaders/scene.glsl#L1817)
uses exponential distance fog in the active mode. Fog blends in linear light
before exposure/display conversion. Writing FOG on any branch suppresses the
default fog operation across the compiled shader, so simply omitting a night
assignment cannot preserve native night fog.
[GLES Environment upload](https://github.com/godotengine/godot/blob/4.7.2-stable/drivers/gles3/rasterizer_scene_gles3.cpp#L1489)
converts Environment fog colour from sRGB to linear and multiplies energy once.

Planned candidate: architecture-only daytime fog variant, actual Environment
uniforms, thinner daylight optical depth with a soft foundation return to normal
fog. The night1 endpoint uses the original shader. Unsupported fog mode/height/
scatter falls back to original shader. Other scene fog/water/lighting unchanged.
Runtime probes must sync their own Environment to material fog uniforms; a
copied production material must not retain fog in an isolated no-fog test.

No Git writes: revalidated root is E:/ with E:/.git. Scoped snapshots retained.

## Implemented candidate and executed acceptance

The day architecture wrapper now uses a local exponential-fog density scale
of .55, softly returning to full density over the bottom .72–1 sprite UV band.
It receives the actual WorldEnvironment's enabled flag, density and linear
fog colour. The two building materials switch back to the original native
wrapper at night1; unsupported fog conditions also use the original wrapper.
No global fog, light, water, image texture or architecture profile was changed.
The helper preserves texture and profile/window parameters when switching.

First production build stopped on the old lighting audit's hard-coded native
day wrapper. The test now expects the new day wrapper and explicitly checks
the original wrapper at night1; no lighting thresholds were relaxed. Second
build exposed a real export-whitelist omission, which prevented weather from
compiling in the pack. Added the helper and day shader to export_files; includes
were already covered. Both failed logs remain, rather than being called passes.

Final build 20260910-215435 (session96909) exited0: ten checked material-only
stages and Web payload preparation, NOT the full35-stage suite. All five static
cache bundles current. PCK118879116 bytes, gzip114095231, SHA256
895a0de123bb7ae1ea9a22ef1f24b4e4c7d00f664496e5464a333b86af07f6eb.
Independent atmosphere state audit exited0, PASS3112: actual startup, half
transitions, native night, reverse transition, alternate/disabled/unsupported
environments, resource/array preservation and protected source paths. This
is state validation, not a substitute for GPU or visual evidence.

Actual Web roof probe passed unchanged thresholds: day flat .0451951498786608
to profiled .0593696447710196; moon-direction flat0 to .00659552682191133;
control errors0. Moon-direction is still the isolated direction test, not
the actual night scene. Browser warn/error list was empty.

Main and independent reviewer inspected original day-atmosphere-2k.png and
night-atmosphere-2k.png against v94/day-final-2k.png and night-final-2k.png.
Both candidate canvases2560×1440, DPR~1, paused clock0, day/night endpoints0/1,
and complete16:10 composition with side bars. Random dragon pose and UI
focus/sharpness differences are excluded. The night file was recaptured after
verifying night1 because the initial calibrated mouse click missed the button.

Accepted as a local improvement: ordinary whole-frame visible roof/stone/wood
separation, reduced grey veil and retained soft building/ground transition.
Neither reviewer saw a new dark cutout rim, rotor mismatch, or night regression.
This does NOT establish overall near-reference completion or identical pixels.
The main rated current overall style fidelity subjectively about7/10 and named
remaining volume consistency and lighting/composition hierarchy as next work.
