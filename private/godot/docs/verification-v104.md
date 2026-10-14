# v104 — local rock shelter and broad foreground sunlight

Scene-only; subjective8.7 target remains pending, no combat/integration work.

The new broad foreground cloud is on the shared world-space solar projection,
not a screen vignette. Crown/grass/rock receive the same moving footprint. Only
existing warm day-key transmission changes, not albedo, exposure, moon/lamps,
sky or the approved water shader. Native GLES controlled probe passed427checks,
40records including night, bounce, ambient, omni and zero-light controls. This
probe ran before the limestone AO integration, so it validates the cloud-field
change, NOT all final limestone behavior or full-scene visual acceptance.

New rock-occlusion sidecar uses actual terrain and geology triangles,8 sky rays
and12 local-hemisphere rays per unique vertex. Offline run6350880rays took107499ms;
317556 approved left-prefix vertices,303968 occluded, minimumvisibility.00025045,
mean sky/local(.331687,.527378). Binary318544bytes. Original source cache files
did not change during this bake. Runtime must only validate/read these results
and upload a derived mesh; never trace rays or silently bake missing data.

Only left-prefix COLOR.b may change. Other mesh channels, geometry/collisions,
material ownership and all nonprefix vertices are regression gates. Shader
uses VERTEX_ID against explicit default-zero `rock_ao_vertex_count`, so unrelated
rocks keep their original AO. Local shelter affects ambient most strongly,
and direct light by a restrained day .38/night .12 fraction; it is not a painted
black edge. AO affects indirect and, through AO_LIGHT_AFFECT, direct light per
[Godot's shader reference](https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/spatial_shader.html).

Before snapshots: artifacts/v104/detail.v103-before.scn and terrain.v103-before.scn,
plus main/limestone/sunbreak source snapshots. Main-scene integration requires
a fresh five-cache source signature; runtime AO is explicitly skipped during
static rebuilding to keep the original geometry data clean.

Static rebuild completed5bundles/52021277bytes, signature
b794af243d6e443dd68055e9d90241e3b314049dc26528bba1a1996804cda271.
The first apply test caught normal re-quantization when building a fresh mesh
from decoded arrays. The next attempted byte-buffer update did not operate in
Godot's headless dummy backend (its update method is empty in the
[engine source](https://github.com/godotengine/godot/blob/master/servers/rendering/dummy/storage/mesh_storage.h)).
Both failed logs are retained. Final implementation copies pinned ArrayMesh
serialized raw surfaces and patches only prefix RGBA8 blue bytes before upload.
No test tolerance was relaxed. Off-tree real apply audit now passes exact
normal/position/index/UV/RGA/suffix/collision preservation, unchanged original
resources and idempotence.2021283checks; decoded visibility mean.400321,min0,max1,
316674blue values changed; this count is not a quality score.

Export/pack passed and sidecar is included/applied. PCK121790736bytes,
gzip117003533; SHA2567afe5703b307e88ec9357fe80a7ac2b8ce316fae75e41a40b5f6ac95db9fed97.
Actual Web captures day-shelter-2k.png/night-shelter-2k.png: canvas2560x1440,
DPR1, clock0 paused, night0/1, complete framing; browser warnings/errors empty.
Startup single sample download1839ms, scene4944ms, load119085ms. Initial ordinary
viewport render samples26fps/169drawcalls/2802380primitives; not a controlled
benchmark and not an acceptable basis to claim faster loading.

Main/independent day review: foreground light mass has visible but modest benefit;
left cliff still lacks enough directional separation. Matched read-only RGB
analysis v103->v104 (not screenshot editing) cliff ROI130,650,610,140 has mean
luma136.057->135.121; foreground130,1000,1000,300 changes101.399->87.976;
middle950,510,400,290 changes101.692->101.608. Water sample1950,710,190,170
RGB meanabsolutechange.000165/255; this is one ROI, not whole-river equivalence.

Important correction: despite the generic AO_LIGHT_AFFECT shader contract, the
locked [GLES source](https://github.com/godotengine/godot/blob/4.7.2-stable/drivers/gles3/shaders/scene.glsl)
only applies AO to ambient fill, computes direct AO, but does not multiply the
final direct-light sum by it. v104 therefore does NOT establish the intended
direct-cavity response. v105 adds an explicit local directional-light branch.
Do not describe v104 as having completed the target rock volume pass.

Protected water/weather/sky/focus source hashes remain unchanged; this alone
does not prove identical reflected pixels. No8.7 declaration; still WIP.
