extends RefCounted
## Optional scene-pinned CPU geometry cache. Missing/mismatched data runs original code.
const MANIFEST := "res://progressive/static-cache/manifest.json"
const STATE := &"_meadow_static_geometry_cache_v135"
const FIELDS := {
	"herb": ["herb_roots", "herb_root_uvs", "herb_source_crop", "herb_depth", "herb_root_shifts", "herb_source_bottoms"],
	"village": ["root_uvs"],
	"mountain": ["mountain_relief_v97", "relief_base_size", "relief_base_offset", "relief_grid", "relief_root_uvs",
		"relief_root_shifts", "relief_root_triangle_hits", "relief_source_region", "relief_depth_range", "relief_max_lift",
		"relief_x_range", "relief_left_x_ratio", "relief_x_width_ratio", "relief_x_mapping"]}

static func context(scene: Node3D, node: MeshInstance3D, inputs: Array) -> PackedByteArray:
	if not node.mesh is QuadMesh or not node.material_override is ShaderMaterial:
		return PackedByteArray()
	var camera: Camera3D = scene.camera
	var material: ShaderMaterial = node.material_override
	var texture := material.get_shader_parameter("asset_texture") as Texture2D
	if texture == null:
		return PackedByteArray()
	# Exact inputs, no epsilon/reprojection. A viewport/camera/content mismatch falls back.
	return var_to_bytes([str(node.name), node.transform, scene.global_transform, camera.global_transform,
		camera.projection, camera.size, camera.fov, camera.keep_aspect, camera.near, camera.far,
		camera.frustum_offset, camera.h_offset, camera.v_offset, scene.get_viewport().get_visible_rect(),
		node.mesh.size, node.mesh.center_offset, texture.resource_path, texture.get_width(), texture.get_height(),
		material.get_shader_parameter("uv_region"), inputs])

static func _state(scene: Node3D) -> Dictionary:
	if scene.has_meta(STATE):
		return scene.get_meta(STATE)
	var state := {"valid": false, "entries": {}, "hits": [], "misses": []}
	scene.set_meta(STATE, state)
	if not FileAccess.file_exists(MANIFEST):
		return state
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if not manifest is Dictionary or manifest.get("version") != 1 or not manifest.get("entries") is Dictionary:
		return state
	if not manifest.get("dependencies") is Dictionary:
		return state
	for path: String in manifest.dependencies:
		if not path.begins_with("res://") or FileAccess.get_sha256(path) != manifest.dependencies[path]:
			return state
	state.entries = manifest.entries
	state.valid = true
	return state

static func load_cached(scene: Node3D, node: MeshInstance3D, kind: String, inputs: Array) -> Dictionary:
	var state := _state(scene)
	var key := kind + "-" + str(node.name)
	if not state.valid or not FIELDS.has(kind) or not state.entries.has(key):
		state.misses.append(key)
		return {}
	var spec: Dictionary = state.entries[key]
	var path := str(spec.get("resource", ""))
	if not path.begins_with("res://progressive/static-cache/") or not path.ends_with(".res") or ".." in path:
		return {}
	if FileAccess.get_sha256(path) != str(spec.get("sha256", "")):
		return {}
	var cached := ResourceLoader.load(path, "Resource", ResourceLoader.CACHE_MODE_IGNORE)
	if cached == null:
		return {}
	var data: Variant = cached.get_meta("record", null)
	if not data is Dictionary or data.get("context") != context(scene, node, inputs) or data.get("kind") != kind:
		state.misses.append(key)
		print("MEADOW_STATIC_CACHE_MISS: " + key + " exact-context mismatch")
		return {}
	if not data.get("mesh") is ArrayMesh or not data.get("fields") is Dictionary or not data.get("extra") is Dictionary:
		return {}
	if data.fields.size() != FIELDS[kind].size() or data.mesh.get_surface_count() != 1:
		return {}
	for field: String in FIELDS[kind]:
		if not data.fields.has(field):
			return {}
	if kind == "village" and (not data.extra.get("radii") is PackedFloat64Array or data.extra.radii.size() != 2
			or data.extra.radii[0] <= 100.0 or data.extra.radii[1] <= 100.0):
		return {}
	# No node/material/collider replacement: only the exact originally generated mesh/fields.
	node.mesh = data.mesh
	for field: String in FIELDS[kind]:
		node.set_meta(field, data.fields[field])
	state.hits.append(key)
	print("MEADOW_STATIC_CACHE_HIT: " + key)
	var extra: Dictionary = data.extra.duplicate()
	extra["hit"] = true
	return extra
