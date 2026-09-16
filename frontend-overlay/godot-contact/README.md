# Godot contact integration

`GodotContactScene.vue` at the repository root is the canonical Vue bridge for
the private Godot contact page. `contact-godot-interaction.css` is the scoped
production override that keeps the iframe clickable while allowing the contact
copy and entry card to remain interactive.

The public AIGCNEWS repository must not contain this Godot project, its exported
PCK/WASM artifacts, or its private build and publication scripts. Production
updates start from the active Godot release and must retain the black-border fix;
never replace the scene with the legacy `ContactFieldScene` implementation.
