# v107/v108 — quiet right hills, real rock pigment, retained mountain highlights

Scene-only work. No Boss/player/combat/backend changes. Water/weather/sky/focus
sources unchanged. Independent visual acceptance still pending; no8.7 claim.

v107 replaces v106's rejected tall old crop with a new full-source wooded ridge,
230x76.6667m at(200,0,-320). Native aspect, true alpha.60, mipmaps; original old
PNG preserved on disk but removed from the export selection. C chosen by main,
independent visual reviewer and alpha audit from four concurrent built-in
imagegen candidates. Prompts/provenance:artifacts/v107/hills-generation.md.
Selected PNG SHA2561c598a06d9c9ea8617c46dfdded24882f20d624fba2f70bc8601b86298b34d68.

v107 limestone: only daylight tagged bare-cliff prefix removes positive painted
luminance relative to its mineral pigment. Keeps hue, dark cracks,38% blend,
normals and actual AO. Explicit independent prefix gate, not AO-threshold guessing.
Native GPU eight-case test PASS: bright open/sheltered reduction; dark cracks,
alpha0, prefix0, night open/sheltered, turf cap remain exact in these fixtures.
Initial dark-crack test wrongly demanded baseline>.04 although deliberately dark
input measured.036; corrected only this input's nonblack floor to.02. Delta,
restoration and brightness-reduction tolerances unchanged; failed log retained.
Controlled fixture is not actual-cliff visual acceptance.

v108 only widens the new main massif's day shoulder.24->.48, still continuous,
bounded and hue-preserving. Old shoulder compressed entire broad bright planes,
not just glitter. Night and wooded foothill keep original path. No new blur,
global exposure change or water intervention. v107 build retained as intermediate,
not visually accepted; v108 carries these combined changes for Web acceptance.

Static bake5bundles52021279bytes, signature
084871603472c059f9c2916df69ba33df7c552b6e97a6e2680d9469ace66ab5f.
New native hill audit47632checks PASS; source/crop/flags/aspect/geometry/alpha
registration/real support contracts.59primary and49right roots hit actual soil;
4+14 unsupported roots lie strictly outside both terrain and horizontal viewport
and are explicitly logged NOT GROUNDED. Every visible sampled foot hits soil.
UVarea1 permesh,1365vertices/2560triangles each, actual mesh-derived normals.
Right visible skyline top.15446 vs rejectedv106.08525 (lower is now quieter).
Full dragon test8seeds15360frames32poses/blendedturns PASS,25.72px minimum skyline
gap at800px internal height. Current cache preflight5/5 PASS.

v108 PCK122253220bytes,gzip117463273; SHA256
01f746bdedbaa2bc011b006e776ee1328e6145c98ebb28418a48b5dbb1e3ec73.
Web captures now exist at artifacts/v108/day-final-2k.png and
artifacts/v108/night-final-2k.png. Both were captured from a verified
2560x1440 canvas, DPR1, clock0, paused, at day0/night1; no upscale. The
16:10 scene is letterboxed inside QHD. Dragon startup route/pose is random,
so matching weather clock does not imply identical wildlife animation.

Independent daytime review: 8.2–8.5/10, not the requested8.7. The right ridge
is now subordinate to the castle and the main massif is broader, but the
left-middle limestone ledge remains an overly continuous pale-yellow band.
The pigment fixture improvement cannot be substituted for visible production
scene improvement. Night independent review is pending. v108 is an intermediate
candidate, not final acceptance; next work targets that actual ledge response.
