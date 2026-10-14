extends SceneTree
## Default: inert cache diagnosis only. Main runs this tool serially, never a bake.
## Write opt-in: -- --normalize-ground-cache; no AO/provenance/source edits.
const CACHE := "res://assets/baked/v77/terrain.scn"
const NATIVE := "res://shaders/meadow_ground.gdshader"
const BACKUP := "res://../artifacts/v112/terrain.pre-normalize.scn"
const AO = preload("res://scripts/meadow_rock_occlusion.gd")
var bundles: Array[Node] = []
var failures := 0
var original_sha := ""
var ao_sha := ""
var save_started := false
var native: Shader

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	if not value:
		failures += 1
		push_error("GROUND_CACHE: " + label)
	return value

func _run() -> void:
	quit(1) # Synchronous exceptions must never fall through to PASS.
	var result: Variant = _execute()
	var passed: bool = result == true and failures == 0
	if not passed and save_started:
		var restored := DirAccess.copy_absolute(ProjectSettings.globalize_path(BACKUP), ProjectSettings.globalize_path(CACHE))
		print("GROUND_CACHE_ROLLBACK: ", restored == OK and FileAccess.get_sha256(CACHE) == original_sha, "; preserved backup=", ProjectSettings.globalize_path(BACKUP))
	for bundle: Node in bundles:
		bundle.free()
	print("GROUND_CACHE: ", "COMPLETE" if passed else "FAIL", "; normalize_requested=", OS.get_cmdline_user_args().has("--normalize-ground-cache"), "; failures=", failures, "; no geometry/AO bake; NOT visual/GPU acceptance")
	quit(0 if passed else 1)

func _load_bundle() -> Node:
	# IGNORE_DEEP prevents reusing the just-saved mesh/material from memory.
	var packed := ResourceLoader.load(CACHE, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "PackedScene load"): return null
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		if not _ok(state.get_node_instance(i) == null, "No nested instantiated scenes"): return null
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				if not _ok(state.get_node_property_value(i, j) == null, "Inert nodes only"): return null
	var bundle := packed.instantiate() # Never add to tree: no _ready/main/world reconstruction.
	bundles.append(bundle)
	return bundle

func _hash(value: Variant) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes(value))
	return context.finish().hex_encode()

func _stable(value: Variant, depth: int = 0) -> Variant:
	# Preserve packed channels as exact typed byte hashes, not decoded/repacked geometry.
	if not _ok(depth < 24, "No recursive/unsupported resource graph"): return null
	if value is Resource:
		var resource: Resource = value
		if not _ok(resource.get_script() == null, "No scripted cache resources"): return null
		if resource is Texture2D and not resource.resource_path.is_empty() and not resource.resource_path.contains("::"):
			return [resource.get_class(), resource.resource_path, FileAccess.get_sha256(resource.resource_path)]
		var properties := {}
		for property: Dictionary in resource.get_property_list():
			var key := str(property.name)
			if int(property.usage) & PROPERTY_USAGE_STORAGE and key not in ["resource_path", "resource_scene_unique_id"]:
				properties[key] = _stable(resource.get(key), depth + 1)
		return [resource.get_class(), properties]
	if value is Dictionary:
		var result := {}
		for key: Variant in value: result[key] = _stable(value[key], depth + 1)
		return result
	if value is Array:
		var result: Array = []
		for item: Variant in value: result.append(_stable(item, depth + 1))
		return result
	if typeof(value) >= TYPE_PACKED_BYTE_ARRAY:
		return [typeof(value), value.size(), _hash(value)]
	if value is Object:
		_ok(false, "Unexpected non-resource object in stored data")
		return null
	return value

func _native_parameters(material: ShaderMaterial) -> Dictionary:
	var values := {}
	for uniform: Dictionary in native.get_shader_uniform_list():
		var key := str(uniform.name)
		values[key] = material.get_shader_parameter(key)
	_ok(not values.is_empty(), "Native uniform schema available")
	return values

func _material_state(material: ShaderMaterial) -> Dictionary:
	var properties := {}
	for property: Dictionary in material.get_property_list():
		var key := str(property.name)
		if int(property.usage) & PROPERTY_USAGE_STORAGE and key not in ["shader", "resource_path", "resource_scene_unique_id"] and not key.begins_with("shader_parameter/"):
			properties[key] = _stable(material.get(key))
	return {"properties": properties, "native_parameters": _stable(_native_parameters(material))}

func _snapshot(bundle: Node, ground: MeshInstance3D) -> Dictionary:
	var tree := {}
	var collisions := {}
	var pending: Array[Node] = [bundle]
	while not pending.is_empty():
		var node: Node = pending.pop_back()
		var path := str(bundle.get_path_to(node))
		var properties := {}
		for property: Dictionary in node.get_property_list():
			var key := str(property.name)
			if int(property.usage) & PROPERTY_USAGE_STORAGE and key != "scene_file_path":
				if node == ground and key == "material_override":
					properties[key] = _material_state(ground.material_override as ShaderMaterial)
				else:
					properties[key] = _stable(node.get(key))
		var groups := node.get_groups()
		groups.sort()
		tree[path] = {"class": node.get_class(), "owner": str(bundle.get_path_to(node.owner)) if node.owner != null else "", "index": node.get_index(), "groups": groups, "stored": properties}
		if node is CollisionShape3D:
			if _ok(node.shape is ConcavePolygonShape3D, "Actual triangle collider " + path):
				var faces: PackedVector3Array = node.shape.get_faces()
				_ok(not faces.is_empty(), "Nonempty collider faces " + path)
				collisions[path] = {"corners": faces.size(), "faces_sha256": _hash(faces)}
		for child: Node in node.get_children(): pending.append(child)
	_ok(not collisions.is_empty(), "Actual cached collision(s) present")
	var raw: Variant = ground.mesh.get("_surfaces")
	_ok(raw is Array and not raw.is_empty(), "Stored raw _surfaces present")
	return {"tree": tree, "raw_surfaces": _stable(raw), "colliders": collisions, "ao_terrain_signature": AO._signature(ground.mesh), "cache_version": bundle.get_meta("cache_version", null), "source_signature": bundle.get_meta("source_signature", null)}

func _same(before: Dictionary, after: Dictionary) -> bool:
	for key: String in before:
		_ok(before[key] == after.get(key), "Exact post-save " + key)
	return failures == 0

func _ground(bundle: Node) -> MeshInstance3D:
	var ground := bundle.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	if not _ok(ground != null, "ContinuousMeadow exists"): return null
	if not _ok(ground.mesh is ArrayMesh and ground.mesh.get_surface_count() == 1, "Single-surface ArrayMesh"): return null
	var material := ground.material_override as ShaderMaterial
	if not _ok(material != null and material.shader != null, "Ground ShaderMaterial override"): return null
	return ground

func _execute() -> bool:
	original_sha = FileAccess.get_sha256(CACHE)
	ao_sha = FileAccess.get_sha256(AO.DATA_PATH)
	if not _ok(not original_sha.is_empty() and not ao_sha.is_empty(), "Cache and existing AO files available"): return false
	native = ResourceLoader.load(NATIVE, "Shader", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as Shader
	if not _ok(native != null and native.resource_path == NATIVE, "Canonical native shader"): return false
	var bundle := _load_bundle()
	if bundle == null: return false
	var ground := _ground(bundle)
	if ground == null: return false
	var material := ground.material_override as ShaderMaterial
	var before := _snapshot(bundle, ground)
	var file := FileAccess.open(AO.DATA_PATH, FileAccess.READ)
	if not _ok(file != null, "Read existing AO"): return false
	var data: Variant = file.get_var(false)
	file.close()
	if not _ok(data is Dictionary, "AO dictionary"): return false
	var aligned: bool = data.get("terrain_signature", "") == before.ao_terrain_signature
	var day_define := RegEx.new()
	day_define.compile("(?m)^\\s*#define\\s+MEADOW_FAR_GROUND_DAY(?:\\s|$)")
	var has_day: bool = day_define.search(material.shader.code) != null
	var embedded: bool = material.shader.resource_path.is_empty() or material.shader.resource_path.contains("::")
	print("GROUND_CACHE_DIAGNOSTIC: ", JSON.stringify({"file_sha256": original_sha, "shader_path": material.shader.resource_path, "code_length": material.shader.code.length(), "day_define": has_day, "embedded": embedded, "raw_surfaces_sha256": _hash(before.raw_surfaces), "ao_actual_terrain_signature": before.ao_terrain_signature, "ao_recorded_terrain_signature": data.get("terrain_signature", ""), "ao_aligned": aligned, "ao_mesh_signature": data.get("mesh_signature", ""), "colliders": before.colliders, "cache_version": before.cache_version, "source_signature": before.source_signature, "native_parameters": _stable(_native_parameters(material)), "ao_file_provenance": "Historical bake hashes are NOT current cache-file requirements; untouched"}))
	if not _ok(aligned, "AO actual terrain geometry signature aligned"): return false
	if not _ok(failures == 0, "Snapshot supported"): return false
	if not OS.get_cmdline_user_args().has("--normalize-ground-cache"):
		return _ok(FileAccess.get_sha256(CACHE) == original_sha and FileAccess.get_sha256(AO.DATA_PATH) == ao_sha, "Default diagnosis read-only")
	if not embedded or not has_day:
		print("GROUND_CACHE_NO_CHANGE: no embedded day shader proven; replacement refused")
		return true
	if not _ok(not FileAccess.file_exists(BACKUP), "Never overwrite an existing recovery backup"): return false
	var parameters := _native_parameters(material)
	var replacement := material.duplicate(false) as ShaderMaterial
	replacement.shader = native
	for key: String in parameters:
		replacement.set_shader_parameter(key, parameters[key])
	ground.material_override = replacement
	if not _same(before, _snapshot(bundle, ground)): return false
	var packed := PackedScene.new()
	if not _ok(packed.pack(bundle) == OK, "Pack existing inert tree without geometry construction"): return false
	var backup_absolute := ProjectSettings.globalize_path(BACKUP)
	if not _ok(DirAccess.make_dir_recursive_absolute(backup_absolute.get_base_dir()) == OK, "Create backup directory"): return false
	if not _ok(FileAccess.get_sha256(CACHE) == original_sha and FileAccess.get_sha256(AO.DATA_PATH) == ao_sha, "No concurrent cache/AO change before write"): return false
	if not _ok(DirAccess.copy_absolute(ProjectSettings.globalize_path(CACHE), backup_absolute) == OK and FileAccess.get_sha256(BACKUP) == original_sha, "Exact recoverable backup"): return false
	save_started = true
	if not _ok(ResourceSaver.save(packed, CACHE, ResourceSaver.FLAG_COMPRESS) == OK, "Save normalized cache"): return false
	var reloaded := _load_bundle()
	if reloaded == null: return false
	var loaded_ground := _ground(reloaded)
	if loaded_ground == null: return false
	var after := _snapshot(reloaded, loaded_ground)
	_same(before, after)
	var loaded_material := loaded_ground.material_override as ShaderMaterial
	_ok(loaded_material.shader.resource_path == NATIVE, "Reloaded canonical shader path")
	_ok(after.ao_terrain_signature == data.terrain_signature, "Reloaded AO geometry signature unchanged")
	_ok(FileAccess.get_sha256(AO.DATA_PATH) == ao_sha, "Entire AO binary, signatures and historical provenance untouched")
	print("GROUND_CACHE_NORMALIZED: ", JSON.stringify({"before_file_sha256": original_sha, "after_file_sha256": FileAccess.get_sha256(CACHE), "backup": backup_absolute, "colliders": after.colliders, "ao_terrain_signature": after.ao_terrain_signature, "failures": failures}))
	return failures == 0
