# Godot contact integration

`GodotContactScene.vue` at the repository root is the canonical Vue bridge for
the private Godot contact page; `ContactPageView.vue` and both `*.test.ts` files
next to it complete the four protected sources pinned by
`aigcnews-private-release.json`. Since 20260929-contact-poster the page shows a
static screenshot first and only embeds the Godot iframe after the visitor picks
a quality and presses 开启 (see `scripts/contact-poster/README.md`).
Since 20260929-contact-comic the view also carries the desktop comic layout
(title above an ink-framed scene, paper contact card); those rules only apply
under the public site's `.app-shell--comic-page` shell at ≥64rem. Releases that
only change these sources are assembled with
`scripts/contact-release/build_source_release.py`.
The hand-drawn pieces of that layout (scene frame, halftone dots, title brush,
contact card, note, badge, buttons, QR frame, quality chooser) are generated
9-slice images in `comic/`, each with a `-night` twin; the release script copies
them into `camp-scene/comic/` (served as `/camp-scene/comic/ct-*.webp`) and adds
them to the manifest. They are rendered by `scripts/contact-comic/ct_specs.py`
(`python ct_specs.py <out dir> <meta json> [names...]`, next to `inkframe.py`);
the printed pad/slice numbers are what the view's `border-image` rules use. An
asset that changes must get a new file name, since releases never rewrite a file
an earlier release shipped.
`contact-godot-interaction.css` is the scoped
production override that keeps the iframe clickable while allowing the contact
copy and entry card to remain interactive.

The public AIGCNEWS repository must not contain this Godot project, its exported
PCK/WASM artifacts, or its private build and publication scripts. Production
updates start from the active Godot release and must retain the black-border fix;
never replace the scene with the legacy `ContactFieldScene` implementation.
