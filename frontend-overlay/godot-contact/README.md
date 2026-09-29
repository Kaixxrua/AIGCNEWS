# Godot contact integration

`GodotContactScene.vue` at the repository root is the canonical Vue bridge for
the private Godot contact page; `ContactPageView.vue` and both `*.test.ts` files
next to it complete the four protected sources pinned by
`aigcnews-private-release.json`. Since 20260929-contact-poster the page shows a
static screenshot first and only embeds the Godot iframe after the visitor picks
a quality and presses 开启 (see `scripts/contact-poster/README.md`).
`contact-godot-interaction.css` is the scoped
production override that keeps the iframe clickable while allowing the contact
copy and entry card to remain interactive.

The public AIGCNEWS repository must not contain this Godot project, its exported
PCK/WASM artifacts, or its private build and publication scripts. Production
updates start from the active Godot release and must retain the black-border fix;
never replace the scene with the legacy `ContactFieldScene` implementation.
