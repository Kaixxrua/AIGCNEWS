# Optional bounded text/GUI follow-up (not the first v128 release)

Godot4.7.2 upstream `ed1daf0bf001b61586d9930840f2f1394092c079`, same isolated
Emscripten4.0.11/Python3.12.4/SCons4.9.1 and lazy shader + main-owned mode5
revision02 patches as [the first module profile](bounded-web-modules-v128.md).

The first release ZIP stays frozen at SHA256
`fd37fd4c6e5d47e4cd687ee7b9294645519beb848e1a17f39334557b7ac94896`.
This separate candidate changes only `module_text_server_adv_enabled=no`,
`module_text_server_fb_enabled=yes`, `disable_advanced_gui=yes`, and supplies
[a two-class feature profile](text-gui-web-v128.json). All other flags match the
first release. No additional C++ source changes. FreeType, MSDF and SVG stay.

## Source-bound boundary

- Stock `scene/register_scene_types.cpp:529` gates30 advanced GUI registrations;
  Label (`:474`) and Label3D (`:650`) remain outside that guard. Basic controls,
  Window/SubViewport, fonts, themes, HTML bridge and HTTP remain enabled.
- The class profile disables only ImporterMesh and ImporterMeshInstance3D, not
  ArrayMesh/MeshInstance3D. `core/object/class_db.h:43` inherits disabled status;
  `:568` elides registrations through `if constexpr`. Internal occluder-bake
  references may retain some importer methods; there is no guaranteed byte gain.
- `modules/text_server_fb/text_server_fb.cpp:71` retains simple Unicode layout,
  bitmap/dynamic/MSDF font capabilities. Its shaping loop (`:4950`) uses Unicode
  codepoints, covering-font selection, glyph advances and pair kerning.
  This does not preserve BiDi, complex/OpenType shaping or ligatures. Chinese
  glyphs still require a covering font: stock OpenSans is not a CJK-font promise.
- `scene/theme/default_theme.cpp:1399` still creates the same embedded font;
  font resources and Label3D's material/raster paths are unchanged. No MSDF cut.
- Current scale guide (`godot/scripts/meadow_scene.gd:1052`) is CapsuleMesh plus
  ImmediateMesh ring; no text or advanced GUI dependency. All actual 3D lights,
  shadows, physics, navigation, animation/skeletons and character core remain.
- Editor-only classes were already absent. No imaginary importer/editor savings
  are attributed to this candidate; bytes must come from the resulting binary.

[Assessment02](../../artifacts/startup-v128/engine/next-candidate-assessment-02.json)
checks every entry of the three hash-pinned184-entry packs, real GDC identifiers,
decoded binary resource class names, text-driver override absence and source
references. No removed class is referenced. The earlier assessment conservatively
matched the English word “Tree” in a tree-crown comment; revision02 excludes only
whole comment lines, never expressions/strings. Packed-byte proofs remain exact.

## Reproduction and gates

From the local project root, after the first release and audit are present:

```powershell
& E:/Anaconda3/python.exe -B artifacts/startup-v128/engine/text-gui-01/run_candidate.py
```

The finite runner first copies and verifies the old ZIP under the new artifact's
`baseline/`, refuses existing outputs, verifies source/pack pins and records the
complete expanded command in `build.log.json`. It reuses existing SDK/objects;
`-j4`, linker/ThinLTO/EMCC/Binaryen caps4, frozen SDK cache, child-only environment.
New scratch and outputs stay in that artifact. A changed global GUI define may
invalidate many objects despite cache reuse. Do not run duplicate/clean builds.

Use matching JS/WASM/worklets from the final candidate ZIP only. Main's real Web
acceptance must include original/balanced/lite, day/night/water, walking/scale
guide, animation and Chinese/basic Latin Label3D with an appropriate font.
Offline module loading is not rendering/first-ready proof. No 3–4MB or loading
time claim is made before measured results; preserve the advanced-text first ZIP.

A separate [bounded text fixture](../../artifacts/startup-v128/engine/text-gui-01/TEXT-TEST.md)
also executes real WASM headless initialization with the same local covering
font and checks Chinese/Latin glyph bounds, MSDF off/on, Label3D binding and
class availability. It stops before Web's frame callback, with no GL context,
network or shipped font. This supplements, but never replaces, Web visual tests.

## Completed candidate

The single build finished exit0 in948.641 seconds. Frozen ZIP SHA256:
`13f72c12a9fe98aa67156016a55ad7c81b89890e42e3f6af1d72ef9bada131c5`.
JS/WASM/worklets total5,310,531 Brotli6 bytes (first release6,288,032), so the
3–4MB engine goal was not reached. All11 policy gates and the real-WASM bounded
text fixture pass. Tested glyph bounds match, but non-MSDF sample line width
changes254→255px: do not claim general typography equivalence. First release
remains byteexact. See the [handoff](../../artifacts/startup-v128/engine/text-gui-01/HANDOFF.md)
for exact bytes, hashes, scope and remaining Web acceptance gates.
