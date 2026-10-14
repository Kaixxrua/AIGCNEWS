extends SceneTree
## Bounded offline reader/validator for build_lite_geometry.py. Never run main,
## import assets, resave resources or enter the original project's editor.
## The Python entry point creates an isolated project under the artifact root.

var request: Dictionary
var output: String
var failures := 0
var mesh_index := 0

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(condition: bool, message: String) -> bool:
	if not condition:
		failures += 1
		push_error("LITE_GEOMETRY: " + message)
	return condition

func _sha(bytes: PackedByteArray) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	if not bytes.is_empty():
		hash.update(bytes)
	return hash.finish().hex_encode()

func _hash(value: Variant) -> String:
	return _sha(var_to_bytes(value))

func _write(name: String, bytes: PackedByteArray) -> String:
	if not _ok(name == name.get_file(), "Flat artifact filename required"):
		return ""
	var path := output.path_join(name)
	if not _ok(not FileAccess.file_exists(path), "Refuse existing output " + path):
		return ""
	var file := FileAccess.open(path, FileAccess.WRITE)
	if not _ok(file != null, "Create output " + path):
		return ""
	file.store_buffer(bytes)
	file.flush()
	_ok(file.get_error() == OK, "Write completed " + path)
	file.close()
	_ok(FileAccess.get_sha256(path) == _sha(bytes), "Write readback " + path)
	return path

func _stable(value: Variant, depth: int = 0) -> Variant:
	if not _ok(depth < 32, "Acyclic stored resource graph"):
		return null
	if value is Mesh:
		# Full mesh properties are independently checked below, without reducing
		# node/material/metadata comparison to object instance IDs.
		return ["mesh", value.get_class(), value.resource_name]
	if value is Resource:
		var resource: Resource = value
		_ok(resource.get_script() == null, "No resource scripts")
		if resource is Shader or resource is Texture2D:
			var path := resource.resource_path
			_ok(path.begins_with("res://") and not path.contains("::"), "Canonical external shader/texture")
			return [resource.get_class(), path, FileAccess.get_sha256(path)]
		var properties := {}
		for property: Dictionary in resource.get_property_list():
			var key := str(property.name)
			if int(property.usage) & PROPERTY_USAGE_STORAGE and key not in ["resource_path", "resource_scene_unique_id"]:
				properties[key] = _stable(resource.get(key), depth + 1)
		return [resource.get_class(), properties]
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
		_ok(false, "Unexpected Object in serialized properties")
		return null
	return [typeof(value), _hash(value)]

func _signature(mesh: Mesh) -> String:
	# Byte-for-byte the runtime meadow_rock_occlusion.gd signature algorithm.
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(var_to_bytes(mesh.surface_get_primitive_type(0)))
	for channel: Variant in mesh.surface_get_arrays(0):
		hash.update(var_to_bytes(channel))
	return hash.finish().hex_encode()

func _mesh(mesh: ArrayMesh, label: String, dump: bool) -> Dictionary:
	_ok(mesh.get_script() == null and mesh.get_blend_shape_count() == 0, "Static ArrayMesh " + label)
	_ok(mesh.shadow_mesh == null, "No unprocessed shadow mesh " + label)
	var properties := {}
	for property: Dictionary in mesh.get_property_list():
		var key := str(property.name)
		if int(property.usage) & PROPERTY_USAGE_STORAGE and key not in ["_surfaces", "resource_path", "resource_scene_unique_id"]:
			properties[key] = _stable(mesh.get(key))
	var surfaces: Array = mesh.get("_surfaces")
	var rows: Array = []
	for surface_index in range(surfaces.size()):
		var raw: Dictionary = surfaces[surface_index]
		var count: int = raw.vertex_count
		var format: int = raw.format
		var arrays := mesh.surface_get_arrays(surface_index)
		_ok(mesh.surface_get_primitive_type(surface_index) == Mesh.PRIMITIVE_TRIANGLES, "Triangle surface " + label)
		_ok(not (format & Mesh.ARRAY_FLAG_COMPRESS_ATTRIBUTES) or request.get("allow_compressed", false) or request.get("native_pack", false), "Expected authorized vertex format " + label)
		var vertex_stride := RenderingServer.mesh_surface_get_format_vertex_stride(format, count)
		var attribute_stride := RenderingServer.mesh_surface_get_format_attribute_stride(format, count)
		var offsets := {}
		for channel in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
			offsets[str(channel)] = RenderingServer.mesh_surface_get_format_offset(format, count, channel)
		var fixed_properties := {}
		for key: Variant in raw:
			if key not in ["vertex_data", "attribute_data"]:
				fixed_properties[str(key)] = _stable(raw[key])
		var channel_hashes := {}
		for channel in range(Mesh.ARRAY_MAX):
			channel_hashes[str(channel)] = _hash(arrays[channel])
		var row := {"surface": surface_index, "format": format, "vertex_count": count,
			"index_count": mesh.surface_get_array_index_len(surface_index), "vertex_stride": vertex_stride,
			"attribute_stride": attribute_stride, "offsets": offsets, "fixed_properties": fixed_properties,
			"channel_hashes": channel_hashes, "raw_buffers": {}, "aabb": _stable(raw.aabb)}
		var bounds: AABB = raw.aabb
		row["aabb_values"] = [bounds.position.x, bounds.position.y, bounds.position.z, bounds.size.x, bounds.size.y, bounds.size.z]
		var uv_scale: Vector4 = raw.get("uv_scale", Vector4())
		row["uv_scale_values"] = [uv_scale.x, uv_scale.y, uv_scale.z, uv_scale.w]
		for key: String in ["vertex_data", "attribute_data", "index_data"]:
			var data: PackedByteArray = raw.get(key, PackedByteArray())
			var info := {"bytes": data.size(), "sha256": _sha(data)}
			if dump and not data.is_empty():
				info["path"] = _write("mesh-%02d-s%d-%s.bin" % [mesh_index, surface_index, key], data)
			row.raw_buffers[key] = info
		# Independent decoded float data lets Python reject any mismatch between
		# its strided storage view and what the pinned engine actually renders.
		if dump:
			row["decoded"] = {}
			row["decoded_sha256"] = {}
			for channel in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
				if arrays[channel] != null:
					row.decoded[str(channel)] = _write("mesh-%02d-s%d-channel-%d.bin" % [mesh_index, surface_index, channel], arrays[channel].to_byte_array())
					row.decoded_sha256[str(channel)] = _sha(arrays[channel].to_byte_array())
		rows.append(row)
	mesh_index += 1
	return {"label": label, "properties": properties, "signature": _signature(mesh), "surfaces": rows}

func _snapshot(path: String, dump: bool) -> Dictionary:
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "Load PackedScene " + path):
		return {}
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		_ok(state.get_node_instance(i) == null, "No nested scene instantiation")
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				_ok(state.get_node_property_value(i, j) == null, "Inert nodes only")
	if failures > 0:
		return {}
	var node := packed.instantiate() # Off-tree: no _ready, gameplay or physics world.
	var tree := {}
	var meshes := []
	var collisions := {}
	var pending: Array[Node] = [node]
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		var label := str(node.get_path_to(current))
		var properties := {}
		for property: Dictionary in current.get_property_list():
			var key := str(property.name)
			if int(property.usage) & PROPERTY_USAGE_STORAGE and key != "scene_file_path":
				if key == "metadata/terrain_sha256":
					properties[key] = str(current.get(key))
				else:
					properties[key] = _stable(current.get(key))
		var groups := current.get_groups()
		groups.sort()
		tree[label] = {"class": current.get_class(), "properties": properties, "groups": groups,
			"index": current.get_index(), "owner": str(node.get_path_to(current.owner)) if current.owner != null else ""}
		if current is MeshInstance3D:
			if _ok(current.mesh is ArrayMesh, "Stored ArrayMesh " + label):
				meshes.append(_mesh(current.mesh, label, dump))
		if current is CollisionShape3D:
			_ok(current.shape is ConcavePolygonShape3D, "Exact triangle collision")
			collisions[label] = {"corners": current.shape.get_faces().size(), "sha256": _hash(current.shape.get_faces())}
		for child: Node in current.get_children():
			pending.append(child)
	node.free()
	return {"tree": tree, "node_count": state.get_node_count(), "meshes": meshes, "collisions": collisions}

func _native_pack(path: String) -> Dictionary:
	# _snapshot has already rejected scripts/nested scenes in the same input.
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	var node := packed.instantiate()
	var pending: Array[Node] = [node]
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		if current is MeshInstance3D and current.name not in ["ContinuousMeadow", "SolidLimestoneGeology", "MiddleMeadowBrush", "EmbeddedRiverbankStrata"]:
			var original: ArrayMesh = current.mesh
			var source_raw: Array = original.get("_surfaces")
			var derived := ArrayMesh.new()
			for s in range(original.get_surface_count()):
				var arrays := original.surface_get_arrays(s)
				if request.get("native_basis_safe", false):
					# Compressed TBN stores a rotation, requiring an orthonormal basis.
					# These scene shaders do not consume authored TANGENT/BINORMAL;
					# preserve the original NORMAL and make only its encoding basis valid.
					var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
					var tangents: PackedFloat32Array = arrays[Mesh.ARRAY_TANGENT].duplicate()
					for i in range(normals.size()):
						var normal := normals[i].normalized()
						var tangent := Vector3(tangents[i * 4], tangents[i * 4 + 1], tangents[i * 4 + 2])
						tangent -= normal * normal.dot(tangent)
						if tangent.length_squared() < 0.000001:
							tangent = normal.cross(Vector3.RIGHT if absf(normal.y) > 0.95 else Vector3.UP)
						tangent = tangent.normalized()
						tangents[i * 4] = tangent.x
						tangents[i * 4 + 1] = tangent.y
						tangents[i * 4 + 2] = tangent.z
					arrays[Mesh.ARRAY_TANGENT] = tangents
				if request.get("canonical_leaf_uv", false):
					var material := current.material_override as ShaderMaterial
					if material != null and material.shader.resource_path == "res://shaders/meadow_leaves.gdshader":
						var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV].duplicate()
						for i in range(uv.size()):
							uv[i] = Vector2(-2048.0 if uv[i].x < -1800.0 else (-1024.0 if uv[i].x < -900.0 else 0.0), 0.0)
						arrays[Mesh.ARRAY_TEX_UV] = uv
				derived.add_surface_from_arrays(original.surface_get_primitive_type(s), arrays, [], {}, Mesh.ARRAY_FLAG_COMPRESS_ATTRIBUTES)
			var candidate_raw: Array = derived.get("_surfaces")
			for s in range(candidate_raw.size()):
				var a: Dictionary = source_raw[s]
				var b: Dictionary = candidate_raw[s]
				# RGBA8 is data (wind/pigment), not an expendable visual approximation.
				if int(a.format) & Mesh.ARRAY_FORMAT_COLOR:
					var count: int = a.vertex_count
					var source_stride := RenderingServer.mesh_surface_get_format_attribute_stride(a.format, count)
					var target_stride := RenderingServer.mesh_surface_get_format_attribute_stride(b.format, count)
					var source_offset := RenderingServer.mesh_surface_get_format_offset(a.format, count, Mesh.ARRAY_COLOR)
					var target_offset := RenderingServer.mesh_surface_get_format_offset(b.format, count, Mesh.ARRAY_COLOR)
					var attributes: PackedByteArray = b.attribute_data
					var source_attributes: PackedByteArray = a.attribute_data
					for i in range(count):
						for component in range(4):
							attributes[i * target_stride + target_offset + component] = source_attributes[i * source_stride + source_offset + component]
					b.attribute_data = attributes
				# Keep every non-format surface field, including material and LODs.
				for key: Variant in a:
					if key not in ["format", "vertex_data", "attribute_data", "aabb", "uv_scale"]:
						b[key] = a[key]
			var replacement: ArrayMesh = original.duplicate(false)
			replacement.clear_surfaces()
			replacement.set("_surfaces", candidate_raw)
			current.mesh = replacement
		for child: Node in current.get_children():
			pending.append(child)
	var copy := PackedScene.new()
	_ok(copy.pack(node) == OK, "Pack inert native-compression COPY")
	var target := output.path_join("native-" + path.get_file())
	if _ok(not FileAccess.file_exists(target), "Native trial is a NEW artifact"):
		_ok(ResourceSaver.save(copy, target, ResourceSaver.FLAG_COMPRESS) == OK, "Save native draft only")
	node.free()
	return {"path": target, "sha256": FileAccess.get_sha256(target), "snapshot": _snapshot(target, true)}

func _runtime_probe(ao: Dictionary) -> Dictionary:
	var paths: Dictionary = request.runtime_probe
	var terrain_pack := ResourceLoader.load(paths.terrain, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	var detail_pack := ResourceLoader.load(paths.detail, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(terrain_pack != null and detail_pack != null, "AO probe caches load"):
		return {}
	# Already proven inert by the independent full candidate inspection.
	var terrain_bundle := terrain_pack.instantiate()
	var detail_bundle := detail_pack.instantiate()
	var terrain := terrain_bundle.get_node("ContinuousMeadow") as MeshInstance3D
	var rock := detail_bundle.get_node("SolidLimestoneGeology") as MeshInstance3D
	var original_mesh: Mesh = rock.mesh
	var original_arrays := original_mesh.surface_get_arrays(0)
	var before_signature := _signature(original_mesh)
	var before_material: Material = rock.material_override
	var collision_before := {}
	for child: Node in rock.find_children("*", "CollisionShape3D", true, false):
		collision_before[str(rock.get_path_to(child))] = _stable(child.shape)
	_clear_temporary_owners(terrain)
	_clear_temporary_owners(rock)
	terrain_bundle.remove_child(terrain)
	detail_bundle.remove_child(rock)
	var scene := Node3D.new()
	scene.add_child(terrain)
	scene.add_child(rock)
	var logic: GDScript = load("res://scripts/meadow_rock_occlusion.gd")
	if not _ok(logic != null, "Existing runtime AO helper loaded from read-only pack"):
		scene.free()
		terrain_bundle.free()
		detail_bundle.free()
		return {}
	_ok(logic._signature(original_mesh) == ao.mesh_signature, "Actual runtime rock signature matches")
	_ok(logic._signature(terrain.mesh) == ao.terrain_signature, "Actual runtime terrain signature matches")
	var applied: bool = logic.apply(scene, request.ao_path)
	_ok(applied, "Existing AO.apply accepts complete candidate without bypass")
	if applied:
		var after_arrays := rock.mesh.surface_get_arrays(0)
		for channel in range(Mesh.ARRAY_MAX):
			if channel != Mesh.ARRAY_COLOR:
				_ok(_hash(original_arrays[channel]) == _hash(after_arrays[channel]), "AO retains mesh channel " + str(channel))
		var before_colours: PackedColorArray = original_arrays[Mesh.ARRAY_COLOR]
		var after_colours: PackedColorArray = after_arrays[Mesh.ARRAY_COLOR]
		var visibility: PackedByteArray = ao.visibility
		var exact_mapping := before_colours.size() == after_colours.size()
		for i in range(before_colours.size()):
			var a := before_colours[i]
			var b := after_colours[i]
			exact_mapping = exact_mapping and a.r == b.r and a.g == b.g and a.a == b.a
			if i < visibility.size():
				exact_mapping = exact_mapping and absf(b.b - float(visibility[i]) / 255.0) < 0.0000001
			else:
				exact_mapping = exact_mapping and a.b == b.b
		_ok(exact_mapping, "Every original AO visibility sample maps to the exact original vertex index")
		_ok(rock.material_override != before_material, "AO material uses a runtime duplicate")
		_ok(_signature(original_mesh) == before_signature, "AO leaves cached source mesh unchanged")
		for child: Node in rock.find_children("*", "CollisionShape3D", true, false):
			_ok(collision_before[str(rock.get_path_to(child))] == _stable(child.shape), "AO leaves original collision unchanged")
	var result := {"applied": applied, "original_runtime_helper": true, "off_tree": not scene.is_inside_tree(),
		"visibility_samples_checked": ao.visibility.size(), "mesh_signature": before_signature,
		"terrain_signature": _signature(terrain.mesh), "collision_shapes_checked": collision_before.size(),
		"all_sample_indices_and_nonblue_attributes_exact": failures == 0}
	scene.free()
	terrain_bundle.free()
	detail_bundle.free()
	return result

func _clear_temporary_owners(node: Node) -> void:
	node.owner = null
	for child: Node in node.get_children():
		_clear_temporary_owners(child)

func _run() -> void:
	quit(1) # A parse/runtime failure must never fall through to success.
	var args := OS.get_cmdline_user_args()
	if not _ok(args.size() == 2 and args[0] == "--request", "Use the Python builder to create a request"):
		return
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(args[1]))
	if not _ok(value is Dictionary, "Request JSON"):
		return
	request = value
	output = str(request.output).replace("\\", "/").simplify_path()
	var allowed := str(request.allowed_root).replace("\\", "/").simplify_path()
	if not _ok(output.begins_with(allowed + "/") and allowed.ends_with("/artifacts/loading-v115/geometry"), "Artifact-only write scope"):
		return
	if not _ok(ProjectSettings.globalize_path("res://").replace("\\", "/").begins_with(allowed + "/"), "Isolated project, never original cache directory"):
		return
	var version := Engine.get_version_info()
	if not _ok(version.major == 4 and version.minor == 7 and version.patch == 2, "Pinned Godot 4.7.2"):
		return
	if not _ok(ProjectSettings.load_resource_pack(request.reference_pack), "Mount existing pack read-only for external dependencies"):
		return
	var rows := {}
	var native_rows := {}
	for item: Dictionary in request.files:
		var path := str(item.path)
		var before := FileAccess.get_sha256(path)
		if not _ok(before == item.sha256, "Expected input SHA " + path):
			return
		rows[item.resource] = _snapshot(path, request.get("dump", false))
		if request.get("native_pack", false) and failures == 0:
			native_rows[item.resource] = _native_pack(path)
		_ok(FileAccess.get_sha256(path) == before, "Original unchanged " + path)
		print("LITE_GEOMETRY_INSPECT: ", item.resource, " nodes=", rows[item.resource].get("node_count", 0), " meshes=", rows[item.resource].get("meshes", []).size())
	var ao_file := FileAccess.open(request.ao_path, FileAccess.READ)
	if not _ok(ao_file != null, "Read AO data"):
		return
	var ao: Variant = ao_file.get_var(false)
	ao_file.close()
	if not _ok(ao is Dictionary, "AO dictionary"):
		return
	var ao_fields := {}
	for key: Variant in ao:
		if key in ["mesh_signature", "terrain_signature", "visibility_sha256", "prefix_corners", "prefix_vertices", "version"]:
			ao_fields[str(key)] = ao[key]
		else:
			ao_fields[str(key)] = _stable(ao[key])
	var report := {"engine": version.string, "files": rows, "ao": ao_fields, "failures": failures,
		"scope": "Off-tree resource load; no main, no asset import/export, no GPU/visual/network acceptance"}
	if not native_rows.is_empty():
		report["native_drafts"] = native_rows
	if request.has("runtime_probe"):
		report["runtime_probe"] = _runtime_probe(ao)
	report["failures"] = failures
	if failures == 0:
		_write("inspection.json", (JSON.stringify(report, "\t") + "\n").to_utf8_buffer())
	print("LITE_GEOMETRY_OFFLINE: ", "PASS" if failures == 0 else "FAIL")
	quit(0 if failures == 0 else 1)
