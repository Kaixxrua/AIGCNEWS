extends SceneTree
## Inert, isolated raw-ArrayMesh reader/assembler. Never rebuild mesh arrays.

var request: Dictionary
var output: String
var failures := 0
var serial := 0
const CHANNELS := [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT,
    Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(condition: bool, message: String) -> bool:
	if not condition:
		failures += 1
		push_error("MESH_COMPACT: " + message)
	return condition

func _sha(data: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	if not data.is_empty():
		context.update(data)
	return context.finish().hex_encode()

func _hash(value: Variant) -> String:
	return _sha(var_to_bytes(value))

func _write(name: String, data: PackedByteArray) -> String:
	var path := output.path_join(name)
	if not _ok(name == name.get_file() and not FileAccess.file_exists(path), "New flat output: " + path):
		return ""
	var file := FileAccess.open(path, FileAccess.WRITE)
	if not _ok(file != null, "Open artifact output"):
		return ""
	file.store_buffer(data)
	file.close()
	_ok(FileAccess.get_sha256(path) == _sha(data), "Artifact readback")
	return path

func _stable(value: Variant, depth: int = 0) -> Variant:
	if not _ok(depth < 40, "Acyclic stored graph"):
		return null
	if value is Mesh:
		return [value.get_class(), value.resource_name] # Full mesh record checked separately.
	if value is Resource:
		_ok(value.get_script() == null, "No resource scripts")
		if value is Shader:
			_ok(value.resource_path.begins_with("res://") and not value.resource_path.contains("::"), "External packed shader")
			return [value.get_class(), value.resource_path, _sha(value.code.to_utf8_buffer())]
		if value is Texture2D:
			return [value.get_class(), value.resource_path] # PCK textures are never replaced.
		return [value.get_class(), _properties(value, ["resource_path", "resource_scene_unique_id"], depth + 1)]
	if value is Dictionary:
		var result := {}
		for key: Variant in value:
			result[str(key)] = _stable(value[key], depth + 1)
		return result
	if value is Array:
		var result: Array = []
		for item: Variant in value:
			result.append(_stable(item, depth + 1))
		return result
	if value is Object:
		_ok(false, "Unexpected stored Object")
		return null
	return [typeof(value), _hash(value)]

func _properties(object: Object, excluded: Array, depth: int = 0) -> Dictionary:
	var result := {}
	for property: Dictionary in object.get_property_list():
		var key := str(property.name)
		if int(property.usage) & PROPERTY_USAGE_STORAGE and key not in excluded:
			result[key] = _stable(object.get(key), depth + 1)
	return result

func _mesh(mesh: ArrayMesh, label: String, dump: bool) -> Dictionary:
	_ok(mesh.get_script() == null and mesh.get_blend_shape_count() == 0 and mesh.shadow_mesh == null, "Static unskinned mesh: " + label)
	var rows: Array = []
	var surfaces: Array = mesh.get("_surfaces")
	for surface_index in range(surfaces.size()):
		var raw: Dictionary = surfaces[surface_index]
		var count: int = raw.vertex_count
		var format: int = raw.format
		var arrays := mesh.surface_get_arrays(surface_index)
		_ok(raw.primitive == Mesh.PRIMITIVE_TRIANGLES, "Triangles only")
		var fixed := {}
		for key: Variant in raw:
			if key not in ["vertex_count", "vertex_data", "attribute_data", "index_data"]:
				fixed[str(key)] = _stable(raw[key])
		var row := {"surface": surface_index, "vertex_count": count, "format": format,
			"index_count": mesh.surface_get_array_index_len(surface_index),
			"vertex_stride": RenderingServer.mesh_surface_get_format_vertex_stride(format, count),
			"normal_tangent_stride": RenderingServer.mesh_surface_get_format_normal_tangent_stride(format, count),
			"attribute_stride": RenderingServer.mesh_surface_get_format_attribute_stride(format, count),
			"index_stride": RenderingServer.mesh_surface_get_format_index_stride(format, count),
			"fixed": fixed, "raw_buffers": {}, "decoded": {}, "channel_hashes": {}}
		for channel in range(Mesh.ARRAY_MAX):
			row.channel_hashes[str(channel)] = _hash(arrays[channel])
			if dump and channel >= 6 and channel < Mesh.ARRAY_INDEX:
				_ok(arrays[channel] == null or arrays[channel].is_empty(), "No custom/skin attributes")
		if dump:
			_ok(raw.get("lods", []).is_empty() and raw.get("skin_data", PackedByteArray()).is_empty()
				and raw.get("blend_shapes", PackedByteArray()).is_empty(), "No LOD/skin/blend data")
		for key: String in ["vertex_data", "attribute_data", "index_data"]:
			var data: PackedByteArray = raw.get(key, PackedByteArray())
			var info := {"bytes": data.size(), "sha256": _sha(data)}
			if dump:
				info.path = _write("m%d-s%d-%s.bin" % [serial, surface_index, key], data)
			row.raw_buffers[key] = info
		if dump:
			for channel: int in CHANNELS:
				if arrays[channel] == null and str(request.allowed_root).replace("\\", "/").ends_with("/artifacts/startup-v128/precision"):
					continue # Solid terrain legitimately has no authored tangent channel.
				_ok(arrays[channel] != null, "All six decoded channels present")
				var data: PackedByteArray = arrays[channel].to_byte_array()
				row.decoded[str(channel)] = {"path": _write("m%d-s%d-c%d.bin" % [serial, surface_index, channel], data),
					"bytes": data.size(), "sha256": _sha(data)}
		rows.append(row)
	serial += 1
	return {"label": label, "properties": _properties(mesh, ["_surfaces", "resource_path", "resource_scene_unique_id"]), "surfaces": rows}

func _inert(packed: PackedScene) -> bool:
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		_ok(state.get_node_instance(i) == null, "No nested scene execution")
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				_ok(state.get_node_property_value(i, j) == null, "Inert nodes only")
	return failures == 0

func _snapshot(path: String, targets: Array) -> Dictionary:
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "Load PackedScene") or not _inert(packed):
		return {}
	var node := packed.instantiate() # Off-tree, no _ready or gameplay.
	var tree := {}
	var meshes := {}
	var pending: Array[Node] = [node]
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		var label := str(node.get_path_to(current))
		var groups := current.get_groups()
		groups.sort()
		tree[label] = {"class": current.get_class(), "index": current.get_index(), "groups": groups,
			"owner": str(node.get_path_to(current.owner)) if current.owner != null else "",
			"properties": _properties(current, ["scene_file_path"])}
		if current is MeshInstance3D:
			if _ok(current.mesh is ArrayMesh, "Stored ArrayMesh"):
				meshes[label] = _mesh(current.mesh, label, label in targets)
		for child: Node in current.get_children():
			pending.append(child)
	var result := {"tree": tree, "meshes": meshes, "bundle": _stable(packed.get("_bundled")),
		"packed_properties": _properties(packed, ["_bundled", "resource_path", "resource_scene_unique_id"])}
	node.free()
	return result

func _assemble(item: Dictionary) -> String:
	var packed := ResourceLoader.load(item.path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "Load assembly source") or not _inert(packed):
		return ""
	var node := packed.instantiate()
	var replacements := {}
	for label: String in item.targets:
		var current := node.get_node(NodePath(label)) as MeshInstance3D
		if not _ok(current != null and current.mesh is ArrayMesh, "Allowlisted mesh exists"):
			return ""
		var original: ArrayMesh = current.mesh
		var change: Dictionary = item.replacements[label]
		var raw: Array = original.get("_surfaces")
		if not _ok(raw.size() == 1, "One pinned surface per target"):
			return ""
		var derived: ArrayMesh = original.duplicate(false)
		var surfaces := raw.duplicate(true)
		surfaces[0].vertex_count = int(change.vertex_count)
		if change.has("index_count"):
			_ok(str(request.allowed_root).replace("\\", "/").ends_with("/artifacts/startup-v128/leaf-lod"), "LOD index-count scope")
			surfaces[0].index_count = int(change.index_count)
		for key: String in ["vertex_data", "attribute_data", "index_data"]:
			var info: Dictionary = change.buffers[key]
			var file_path := str(info.path).replace("\\", "/").simplify_path()
			_ok(file_path.begins_with(str(request.allowed_root).replace("\\", "/") + "/"), "Scoped replacement buffer")
			_ok(FileAccess.get_sha256(file_path) == info.sha256, "Replacement SHA")
			surfaces[0][key] = FileAccess.get_file_as_bytes(file_path)
		derived.clear_surfaces()
		derived.set("_surfaces", surfaces) # No add_surface_from_arrays, normalization or repacking.
		_ok(derived.get_surface_count() == 1, "Raw surface accepted")
		_ok(not replacements.has(original.get_instance_id()), "No ambiguous shared target mesh")
		replacements[original.get_instance_id()] = derived
	# Preserve the packed node/connection/variant order, not a fresh node-tree pack.
	var bundle: Dictionary = packed.get("_bundled").duplicate(false)
	var variants: Array = bundle.variants.duplicate()
	var replaced := 0
	for i in range(variants.size()):
		if variants[i] is ArrayMesh and replacements.has(variants[i].get_instance_id()):
			variants[i] = replacements[variants[i].get_instance_id()]
			replaced += 1
	_ok(replaced == item.targets.size(), "Exact allowlisted variant substitutions")
	bundle.variants = variants
	var copy: PackedScene = packed.duplicate(false)
	copy.set("_bundled", bundle)
	var target := output.path_join(str(item.resource).get_file())
	if failures == 0 and _ok(not FileAccess.file_exists(target), "New scene output"):
		_ok(ResourceSaver.save(copy, target, ResourceSaver.FLAG_COMPRESS) == OK, "Save isolated scene")
	node.free()
	return target

func _run() -> void:
	quit(1) # A script error must not accidentally return success.
	var args := OS.get_cmdline_user_args()
	if not _ok(args.size() == 2 and args[0] == "--request", "Python-created request required"):
		return
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(args[1]))
	if not _ok(value is Dictionary, "Request JSON"):
		return
	request = value
	output = str(request.output).replace("\\", "/").simplify_path()
	var allowed := str(request.allowed_root).replace("\\", "/").simplify_path()
	var owned_scope := allowed.ends_with("/artifacts/startup-v126/mesh-compact") or allowed.ends_with("/artifacts/startup-v128/leaf-lod") or allowed.ends_with("/artifacts/startup-v128/precision")
	if not _ok(owned_scope and output.begins_with(allowed + "/")
		and ProjectSettings.globalize_path("res://").replace("\\", "/").begins_with(allowed + "/"), "Isolated artifact project/output"):
		return
	var version := Engine.get_version_info()
	if not _ok(version.major == 4 and version.minor == 7 and version.patch == 2, "Pinned Godot4.7.2"):
		return
	if not _ok(ProjectSettings.load_resource_pack(request.reference_pack), "Read-only frozen dependency pack"):
		return
	var rows := {}
	for item: Dictionary in request.files:
		if not _ok(FileAccess.get_sha256(item.path) == item.sha256, "Pinned scene input"):
			return
		var path: String = item.path
		if request.get("assemble", false):
			path = _assemble(item)
		if failures == 0:
			rows[item.resource] = {"path": path, "sha256": FileAccess.get_sha256(path), "snapshot": _snapshot(path, item.targets)}
		print("MESH_COMPACT_SCENE: ", item.resource, " failures=", failures)
	if failures == 0:
		_write("inspection.json", (JSON.stringify({"engine": version.string, "files": rows, "failures": failures}, "\t") + "\n").to_utf8_buffer())
	print("MESH_COMPACT_OFFLINE: ", "PASS" if failures == 0 else "FAIL")
	quit(0 if failures == 0 else 1)
