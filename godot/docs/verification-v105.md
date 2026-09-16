# v105 — explicit rock directional shelter

Scene-only;8.7 visual target not yet met. Water/weather/sky/focus unchanged.
The previous GLES AO_LIGHT_AFFECT path did not affect the direct-light sum.
Use an explicit local limestone-only directional multiplier with day.48/night.12
strength, controlled by actual-geometry visibility and the approved vertex prefix.
Omni lamps are not multiplied. Ambient AO remains active.

Native GPU test artifacts/v105/rock-light-gpu-fixed.log:10 cases PASS on the actual
GLES renderer,4096pixels/case, maximum error.0042505<2/255. Includes sun, moon,
day/night bounce, omni, ambient, and zero controls. Initial parse failure from a
reserved variable name is retained in rock-light-gpu.log; thresholds unchanged.
This proves mechanism only, not visual quality.

Export and packed-source checks passed; PCK121791280bytes,gzip117003775bytes,
SHA256150e4921d783e42d0ce4e7695c2ab002bdc31ce261a1869f52f9743ec1cebc92.
Actual Web canvas and saved PNGs2560x1440, DPR1, night0/1, animationclock0:
artifacts/v105/day-directional-2k.png and night-directional-2k.png.
PNG dimensions independently decoded; browser warning/error list empty.
Single startup sample download2507ms, scene5140ms, load45483ms; not a benchmark.

Main reviewed both original-resolution images. Night readable without a global
exposure reduction. Independent day review found no broad regression but only
a small visible cliff improvement: still a broad pale ledge. Do not count GPU
test success as a score increase. The next meaningful change is a native-aspect
mountain asset and its terrain join, not another tiny score-only adjustment.
