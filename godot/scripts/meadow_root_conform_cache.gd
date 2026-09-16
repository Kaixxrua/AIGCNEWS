extends RefCounted
## Exact optional memoization of the fixed scene's 50 root-conform meshes.
## No node/material/collider/animation mutation. Original function remains fallback.
const CONTRACT = preload("res://scripts/meadow_static_geometry_cache.gd")
const MANIFEST := "res://progressive/root-conform/manifest.json"
const STATE := &"_meadow_root_conform_cache_v135"

static func _state(scene: Node3D) -> Dictionary:
	if scene.has_meta(STATE):
		return scene.get_meta(STATE)
	var state := {"valid": false, "records": {}, "hits": [], "misses": []}
	scene.set_meta(STATE, state)
	# Share the already required exact main GDC/support/alpha dependency contract.
	# The integrator must repin that main dependency after adding the two-line hook.
	if not CONTRACT._state(scene).get("valid", false) or not FileAccess.file_exists(MANIFEST):
		return state
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if not manifest is Dictionary or manifest.get("version") != 1 or manifest.get("count") != 50:
		return state
	var path := str(manifest.get("resource", ""))
	if path != "res://progressive/root-conform/meshes.res" or FileAccess.get_sha256(path) != str(manifest.get("sha256", "")):
		return state
	var resource := ResourceLoader.load(path, "Resource", ResourceLoader.CACHE_MODE_IGNORE)
	if resource == null:
		return state
	var records: Variant = resource.get_meta("records", null)
	if not records is Dictionary or records.size() != 50:
		return state
	for name: String in records:
		var record: Variant = records[name]
		if not record is Dictionary or not record.get("context") is PackedByteArray or record.context.is_empty():
			return state
		if not record.get("wholeColumn") is bool or not record.get("mesh") is ArrayMesh:
			return state
		var mesh: ArrayMesh = record.mesh
		if mesh.get_surface_count() != 1 or mesh.surface_get_array_len(0) != 225 or mesh.surface_get_array_index_len(0) != 1152:
			return state
		if mesh.surface_get_material(0) != null:
			return state
	state.records = records
	state.valid = true
	return state

static func restore(scene: Node3D, node: MeshInstance3D, whole_column: bool) -> bool:
	var state := _state(scene)
	var key := str(node.name)
	if not state.valid or not state.records.has(key):
		state.misses.append(key)
		return false
	var record: Dictionary = state.records[key]
	if record.wholeColumn != whole_column or record.context != CONTRACT.context(scene, node, [whole_column]):
		state.misses.append(key)
		return false
	node.mesh = record.mesh
	state.hits.append(key)
	if state.hits.size() == 50:
		print("MEADOW_ROOT_CONFORM_CACHE: 50 HIT; exact original meshes; live materials retained")
	return true
