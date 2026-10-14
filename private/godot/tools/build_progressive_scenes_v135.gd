extends SceneTree
## Off-tree partition only. No main scene, imports, gameplay, or source rewrites.

const SCOPE := "E:/Projects/Godot-Octopath2/artifacts/startup-v135/scenes/"
const PACK_SHA := "83caf8ac1126ccacea3a2146109d234193a3de60a887cff2d383e4cfb21c6ce6"
var request: Dictionary
var failures: Array[String] = []
var proxy_carrier: Node3D
var proxy_visuals: Node3D

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	if not value:
		failures.append(label)
		push_error("PROGRESSIVE_SCENES: " + label)
	return value

func _sha(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	if not bytes.is_empty():
		context.update(bytes)
	return context.finish().hex_encode()

func _hash(value: Variant) -> String:
	return _sha(var_to_bytes(value))

func _stable(value: Variant, depth: int = 0) -> Variant:
	if not _ok(depth < 40, "Bounded stored-resource graph"):
		return null
	if value is Shader or value is Texture2D:
		_ok(value.resource_path.begins_with("res://") and not value.resource_path.contains("::"), "Pinned external shader/texture")
		return [value.get_class(), value.resource_path]
	if value is Resource:
		_ok(value.get_script() == null, "No scripted stored resource")
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
	_ok(not value is Object, "Only stored Variant values")
	return [typeof(value), _hash(value)]

func _properties(object: Object, excluded: Array = [], depth: int = 0) -> Dictionary:
	var result := {}
	for property: Dictionary in object.get_property_list():
		var name := str(property.name)
		if int(property.usage) & PROPERTY_USAGE_STORAGE and name not in excluded:
			result[name] = _stable(object.get(name), depth + 1)
	return result

func _load(path: String) -> PackedScene:
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "Load actual pinned PackedScene " + path):
		return null
	var state := packed.get_state()
	_ok(state.get_connection_count() == 0, "No hidden signal wiring in cache")
	for i in range(state.get_node_count()):
		_ok(state.get_node_instance(i) == null, "No nested scene instantiation")
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				_ok(state.get_node_property_value(i, j) == null, "Inert node only")
	return packed

func _inventory(node: Node) -> Dictionary:
	var rows: Array = []
	var pending: Array[Node] = [node]
	var buffer_bytes := 0
	var collision_bytes := 0
	var collision_count := 0
	while not pending.is_empty():
		var child: Node = pending.pop_front()
		var row := {"path": str(node.get_path_to(child)), "class": child.get_class(), "index": child.get_index()}
		if child is MeshInstance3D and child.mesh != null:
			_ok(child.mesh is ArrayMesh, "Stored ArrayMesh only")
			var surfaces: Array = []
			for surface: Dictionary in child.mesh.get("_surfaces"):
				var sizes := {}
				for key: String in ["vertex_data", "attribute_data", "index_data", "skin_data"]:
					sizes[key] = surface.get(key, PackedByteArray()).size()
					buffer_bytes += sizes[key]
				surfaces.append({"vertices": surface.vertex_count, "indices": surface.get("index_count", 0), "bufferBytes": sizes})
			row["surfaces"] = surfaces
		if child is CollisionShape3D:
			collision_count += 1
			_ok(child.shape is ConcavePolygonShape3D, "Known exact collision representation")
			var faces: PackedVector3Array = child.shape.get_faces()
			row["collisionCorners"] = faces.size()
			row["collisionBytes"] = faces.to_byte_array().size()
			row["collisionSha256"] = _sha(faces.to_byte_array())
			collision_bytes += row.collisionBytes
		rows.append(row)
		for grandchild: Node in child.get_children():
			pending.append(grandchild)
	return {"nodes": rows, "meshBufferBytes": buffer_bytes, "collisionBytes": collision_bytes, "collisionCount": collision_count}

func _snapshot(node: Node) -> Dictionary:
	var result := {}
	var pending: Array[Node] = [node]
	while not pending.is_empty():
		var child: Node = pending.pop_front()
		var label := str(node.get_path_to(child))
		var groups := child.get_groups()
		groups.sort()
		var row := {"class": child.get_class(), "index": child.get_index(), "groups": groups,
			"owner": str(node.get_path_to(child.owner)) if child.owner != null else "",
			"properties": _properties(child, ["scene_file_path"] if child == node else [])}
		if child is MeshInstance3D and child.mesh != null:
			var decoded: Array = []
			for i in range(child.mesh.get_surface_count()):
				decoded.append(_stable(child.mesh.surface_get_arrays(i)))
			row["allDecodedMeshChannels"] = decoded
		result[label] = row
		for grandchild: Node in child.get_children():
			pending.append(grandchild)
	return result

func _placeholder(original: Node) -> Node:
	_ok(original is MeshInstance3D and original.get_child_count() == 0, "Only collision-free leaf mesh nodes may be deferred")
	var replacement := MeshInstance3D.new()
	replacement.name = original.name
	for property: Dictionary in original.get_property_list():
		var name := str(property.name)
		if not (int(property.usage) & PROPERTY_USAGE_STORAGE):
			continue
		var value: Variant = original.get(name)
		if value is Resource or name in ["mesh", "material_override", "material_overlay", "skin", "script"] or name.begins_with("surface_material_override/"):
			continue
		replacement.set(name, value)
	for group: StringName in original.get_groups():
		replacement.add_to_group(group, original.is_in_group(group))
	_ok(not original.has_meta("progressive_placeholder"), "Original full node is not a placeholder")
	replacement.mesh = ArrayMesh.new()
	replacement.material_override = original.material_override
	replacement.set_meta("progressive_placeholder", true)
	_ok(replacement.name == original.name and replacement.mesh.get_surface_count() == 0 and replacement.material_override != null,
		"Same-name marked placeholder with duplicable empty mesh and original material")
	_ok(replacement.mesh.duplicate(false) != null and replacement.material_override.duplicate(false) != null, "Unmodified cached edge duplicate operations supported")
	return replacement

func _owners(node: Node, owner_root: Node) -> void:
	node.owner = owner_root
	for child: Node in node.get_children():
		_owners(child, owner_root)

func _save(node: Node, original: PackedScene, path: String) -> PackedScene:
	_ok(path.simplify_path().begins_with(SCOPE) and not FileAccess.file_exists(path), "New scoped scene only")
	var packed := PackedScene.new()
	_ok(packed.pack(node) == OK, "Pack off-tree split resource")
	for key: StringName in original.get_meta_list():
		packed.set_meta(key, original.get_meta(key))
	_ok(ResourceSaver.save(packed, path, ResourceSaver.FLAG_COMPRESS) == OK, "Save independent split scene")
	return _load(path)

func _partition(item: Dictionary, packed: PackedScene) -> Dictionary:
	var node := packed.instantiate()
	var expected := _snapshot(node)
	var before_inventory := _inventory(node)
	var deferred := Node3D.new()
	deferred.name = node.name
	var mapped: Array = []
	for label: String in item.deferred:
		var original := node.get_node_or_null(NodePath(label))
		if not _ok(original != null and original.get_parent() == node, "Exact direct child " + label):
			continue
		var index := original.get_index()
		var placeholder := _placeholder(original)
		_owners(original, null)
		node.remove_child(original)
		node.add_child(placeholder)
		node.move_child(placeholder, index)
		placeholder.owner = node
		deferred.add_child(original)
		_owners(original, deferred)
		mapped.append({"name": label, "class": original.get_class(), "originalIndex": index,
			"deferredIndex": original.get_index(), "placeholderMesh": "ArrayMesh:0-surfaces", "swapRequiresOriginalSiblingIndex": true})
	var core_inventory := _inventory(node)
	var deferred_inventory := _inventory(deferred)
	_ok(core_inventory.collisionCount == before_inventory.collisionCount and deferred_inventory.collisionCount == 0,
		"Every original collider remains in first-load core")
	var core_packed := _save(node, packed, item.core_output)
	var deferred_packed := _save(deferred, packed, item.deferred_output)
	node.free()
	deferred.free()
	var restored := core_packed.instantiate()
	var core_snapshot := _snapshot(restored)
	var details := deferred_packed.instantiate()
	for row: Dictionary in mapped:
		var placeholder := restored.get_node(NodePath(row.name)) as MeshInstance3D
		_ok(placeholder != null and placeholder.mesh != null and placeholder.mesh.get_surface_count() == 0 and placeholder.get_index() == row.originalIndex
			and placeholder.get_meta("progressive_placeholder", false) and placeholder.material_override != null,
			"Reloaded placeholder class/name/index")
		var full := details.get_node(NodePath(row.name))
		_ok(not full.has_meta("progressive_placeholder"), "Full replacement carries no placeholder marker")
		restored.remove_child(placeholder)
		placeholder.free()
		_owners(full, null)
		details.remove_child(full)
		restored.add_child(full)
		restored.move_child(full, row.originalIndex)
		_owners(full, restored)
	details.free()
	var actual := _snapshot(restored)
	var exact := actual == expected
	_ok(exact, "Reassembled node/property/material/raw-buffer/decoded-channel/collision parity: " + item.group)
	var result := {"group": item.group, "sourceEntry": item.entry, "mapping": mapped, "original": before_inventory,
		"core": core_inventory, "deferred": deferred_inventory, "reassembledExact": exact,
		"originalSnapshot": expected, "reassembledSnapshot": actual, "coreSnapshot": core_snapshot,
		"packedResourceMetadataExact": _properties(packed, ["_bundled", "resource_path", "resource_scene_unique_id"]) == _properties(core_packed, ["_bundled", "resource_path", "resource_scene_unique_id"])}
	restored.free()
	return result

func _partition_root(item: Dictionary, packed: PackedScene) -> Dictionary:
	var original := packed.instantiate() as MeshInstance3D
	var expected := _snapshot(original)
	var before := _inventory(original)
	_ok(original.name == &"DistantMeadowSward" and original.get_child_count() == 0, "Exact FarSward root identity")
	var placeholder := _placeholder(original) as MeshInstance3D
	_ok(placeholder.get_meta("cache_revision") == "rooted-sward-113-1" and placeholder.get_meta("ground_roots").size() == 2165,
		"FarSward stub retains revision and all ground_roots; valid cache avoids procedural fallback")
	var core := _save(placeholder, packed, item.core_output)
	var core_node := core.instantiate() as MeshInstance3D
	_ok(core_node.mesh != null and core_node.mesh.get_surface_count() == 0 and core_node.get_meta("progressive_placeholder", false)
		and core_node.get_meta_list().size() == original.get_meta_list().size() + 1, "Reloaded empty FarSward and original metadata plus marker")
	for key: StringName in original.get_meta_list():
		_ok(_stable(core_node.get_meta(key)) == _stable(original.get_meta(key)), "Exact FarSward metadata " + str(key))
	var core_inventory := _inventory(core_node)
	var container := Node3D.new()
	container.name = "ProgressiveDetails"
	var full := _load("res://" + item.entry).instantiate()
	full.scene_file_path = "" # Transport container, not an instance of the core stub.
	container.add_child(full)
	_owners(full, container)
	var deferred_inventory := _inventory(container)
	var deferred_packed := _save(container, packed, item.deferred_output)
	container.free()
	var loaded_container := deferred_packed.instantiate()
	_ok(loaded_container.get_child_count() == 1 and loaded_container.has_node("DistantMeadowSward"), "FarSward chunk uses exact named container child")
	var restored := loaded_container.get_node("DistantMeadowSward")
	_owners(restored, null)
	loaded_container.remove_child(restored)
	loaded_container.free()
	_ok(not restored.has_meta("progressive_placeholder"), "Full FarSward has no progressive metadata")
	var actual := _snapshot(restored)
	_ok(expected == actual, "Deferred FarSward exact original root")
	var result := {"group": item.group, "sourceEntry": item.entry, "original": before,
		"core": core_inventory, "deferred": deferred_inventory,
		"mapping": [{"name": str(original.name), "class": "MeshInstance3D", "replaceSceneRoot": true,
			"preserveRuntimeSiblingIndex": true, "placeholderMesh": "ArrayMesh:0-surfaces"}],
		"reassembledExact": expected == actual, "originalSnapshot": expected, "reassembledSnapshot": actual, "coreSnapshot": _snapshot(core_node),
		"packedResourceMetadataExact": _properties(packed, ["_bundled", "resource_path", "resource_scene_unique_id"]) == _properties(core, ["_bundled", "resource_path", "resource_scene_unique_id"])}
	core_node.free()
	placeholder.free()
	original.free()
	restored.free()
	return result

func _binary(name: String, bytes: PackedByteArray) -> Dictionary:
	var path := str(request.output).get_base_dir().path_join(name)
	_ok(name == name.get_file() and path.begins_with(SCOPE) and not FileAccess.file_exists(path), "New scoped proxy buffer")
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_buffer(bytes)
	file.close()
	return {"path": path, "bytes": bytes.size(), "sha256": _sha(bytes)}

func _proxy_dump(item: Dictionary, packed: PackedScene) -> Dictionary:
	var node := packed.instantiate()
	var target := node.get_node(NodePath(item.mesh)) as MeshInstance3D
	var mesh: ArrayMesh = target.mesh
	_ok(mesh.get_surface_count() == 1 and mesh.get_blend_shape_count() == 0 and mesh.shadow_mesh == null, "One static proxy source surface")
	var arrays := mesh.surface_get_arrays(0)
	var importer := ImporterMesh.new()
	importer.add_surface(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var begun := Time.get_ticks_msec()
	importer.generate_lods(30.0, 0.0, [])
	_ok(_stable(importer.get_surface_arrays(0)) == _stable(arrays), "LOD generation did not modify original vertex channels")
	var levels: Array = []
	for level in range(importer.get_surface_lod_count(0)):
		levels.append({"index": level, "triangles": importer.get_surface_lod_indices(0, level).size() / 3,
			"engineErrorMetric": importer.get_surface_lod_size(0, level)})
	_ok(int(item.lod_index) < levels.size(), "Requested bounded LOD exists")
	var indices := importer.get_surface_lod_indices(0, int(item.lod_index))
	var surfaces: Array = mesh.get("_surfaces")
	var raw: Dictionary = surfaces[0]
	var count := int(raw.vertex_count)
	var format := int(raw.format)
	var result := {"group": item.group, "mesh": item.mesh, "levels": levels, "selectedLevel": item.lod_index,
		"lodGenerationMs": Time.get_ticks_msec() - begun, "sourceVertices": count,
		"sourceIndices": mesh.surface_get_array_index_len(0), "sourceRawSurfacesSha256": _hash(surfaces),
		"vertexStride": RenderingServer.mesh_surface_get_format_vertex_stride(format, count),
		"normalStride": RenderingServer.mesh_surface_get_format_normal_tangent_stride(format, count),
		"attributeStride": RenderingServer.mesh_surface_get_format_attribute_stride(format, count),
		"indexStride": RenderingServer.mesh_surface_get_format_index_stride(format, count),
		"format": format, "buffers": {}, "channels": {},
		"lodIndices": _binary(item.group + "-lod-indices.bin", indices.to_byte_array()),
		"originalAoPrefix": int(target.material_override.get_shader_parameter("rock_ao_vertex_count")) if item.group == "detail" else 0}
	for key: String in ["vertex_data", "attribute_data", "index_data"]:
		result.buffers[key] = _binary(item.group + "-" + key + ".bin", raw[key])
	for channel in range(Mesh.ARRAY_MAX):
		if channel >= 6 and channel < Mesh.ARRAY_INDEX:
			_ok(arrays[channel] == null or arrays[channel].is_empty(), "No proxy custom/skin channels")
		if channel < 6 and arrays[channel] != null:
			result.channels[str(channel)] = _binary(item.group + "-channel-" + str(channel) + ".bin", arrays[channel].to_byte_array())
	node.free()
	return result

func _proxy_assemble(item: Dictionary, packed: PackedScene) -> Dictionary:
	var source := packed.instantiate()
	var exact := source.get_node(NodePath(item.mesh)) as MeshInstance3D
	_ok(FileAccess.get_sha256(item.core_source) == item.core_source_sha256, "Frozen partition core input")
	var core_packed := _load(item.core_source)
	var core := core_packed.instantiate()
	var current := core.get_node(NodePath(item.mesh)) as MeshInstance3D
	var expected := _snapshot(core)
	var exact_mesh: ArrayMesh = exact.mesh
	_ok(_stable(current.mesh) == _stable(exact_mesh), "Core full mesh equals actual v134 source")
	var before_raw: Array = exact_mesh.get("_surfaces")
	var surfaces: Array = before_raw.duplicate(true)
	surfaces[0].vertex_count = int(item.vertex_count)
	surfaces[0].index_count = int(item.index_count)
	for key: String in ["vertex_data", "attribute_data", "index_data"]:
		var info: Dictionary = item.buffers[key]
		_ok(str(info.path).begins_with(SCOPE) and FileAccess.get_sha256(info.path) == info.sha256, "Selected original raw buffer pin")
		surfaces[0][key] = FileAccess.get_file_as_bytes(info.path)
	var derived: ArrayMesh = exact_mesh.duplicate(false)
	derived.clear_surfaces()
	derived.set("_surfaces", surfaces)
	_ok(derived.get_surface_count() == 1, "Proxy raw surface accepted without re-encoding vertices")
	var decoded := derived.surface_get_arrays(0)
	for key: String in item.expected_channels:
		_ok(_sha(decoded[int(key)].to_byte_array()) == item.expected_channels[key], "Selected original decoded channel exact: " + item.mesh + "/" + key)
	current.mesh = derived
	current.set_meta("progressive_visual_proxy", true)
	if item.group == "detail":
		current.material_override = current.material_override.duplicate(false)
		current.material_override.set_shader_parameter("rock_ao_vertex_count", int(item.proxy_ao_prefix))
	var bootstrap := MeshInstance3D.new()
	bootstrap.name = exact.name
	bootstrap.mesh = current.mesh
	bootstrap.material_override = current.material_override
	proxy_visuals.add_child(bootstrap)
	bootstrap.owner = proxy_visuals
	var full := MeshInstance3D.new()
	full.name = exact.name
	full.mesh = exact.mesh
	full.material_override = exact.material_override
	proxy_carrier.add_child(full)
	full.owner = proxy_carrier
	_save(core, core_packed, item.core_output)
	var core_snapshot := _snapshot(core)
	var collider_paths: Array = []
	for path: String in expected:
		if expected[path]["class"] in ["StaticBody3D", "CollisionShape3D"]:
			_ok(expected[path] == core_snapshot[path], "Proxy retains exact collider node/data: " + path)
			collider_paths.append(path)
	var result := {"group": item.group, "mesh": item.mesh, "corePath": item.core_output,
		"expectedCoreSnapshot": expected, "proxyCoreSnapshot": core_snapshot, "colliderPaths": collider_paths,
		"sourceRawSurfacesSha256": _hash(before_raw), "proxyRawSurfacesSha256": _hash(surfaces),
		"proxyAoPrefix": item.proxy_ao_prefix, "fullAoPrefix": item.full_ao_prefix,
		"allSelectedDecodedChannelsExact": true}
	core.free()
	source.free()
	return result

func _proxy_verify_upgrade(rows: Array) -> void:
	_save(proxy_carrier, PackedScene.new(), request.visual_output)
	proxy_carrier.free()
	_save(proxy_visuals, PackedScene.new(), request.bootstrap_visual_output)
	proxy_visuals.free()
	var visual := _load(request.visual_output).instantiate()
	_ok(visual.get_child_count() == 2, "Two inert mesh-only carriers")
	for row: Dictionary in rows:
		var core := _load(row.corePath).instantiate()
		var target := core.get_node(NodePath(row.mesh)) as MeshInstance3D
		var full := visual.get_node(NodePath(row.mesh)) as MeshInstance3D
		_ok(full.get_child_count() == 0 and full.get_script() == null, "Carrier has no scripts/colliders")
		_ok(_hash(full.mesh.get("_surfaces")) == row.sourceRawSurfacesSha256, "Late full raw mesh EXACT actual v134")
		var collider_ids := {}
		for path: String in row.colliderPaths:
			collider_ids[path] = core.get_node(NodePath(path)).get_instance_id()
		# Match the proposed meshOnly contract: live nodes/material state retained.
		target.mesh = full.mesh
		if row.group == "detail":
			target.material_override.set_shader_parameter("rock_ao_vertex_count", int(row.fullAoPrefix))
		target.remove_meta("progressive_visual_proxy")
		var after := _snapshot(core)
		row["meshOnlyRestoredExact"] = after == row.expectedCoreSnapshot
		_ok(row.meshOnlyRestoredExact, "Mesh-only late restore returns exact full core fields")
		row["restoredSnapshot"] = after
		for path: String in collider_ids:
			_ok(core.get_node(NodePath(path)).get_instance_id() == collider_ids[path], "Mesh-only upgrade leaves collider instance intact")
		row["collisionInstancesUnchangedDuringUpgrade"] = true
		core.free()
	visual.free()

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if not _ok(args.size() == 1, "One bounded request JSON"):
		quit(1)
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	if not _ok(FileAccess.get_sha256(request.pack) == PACK_SHA, "Exact native input pin"):
		quit(1)
		return
	var rows: Array = []
	if request.mode == "proxy_assemble":
		proxy_carrier = Node3D.new()
		proxy_carrier.name = "ProgressiveWorldVisuals"
		proxy_visuals = Node3D.new()
		proxy_visuals.name = "BootstrapVisuals"
	for item: Dictionary in request.groups:
		_ok(FileAccess.get_sha256("res://" + item.entry) == item.sha256, "Mounted source entry " + item.entry)
		var packed := _load("res://" + item.entry)
		if not failures.is_empty():
			break
		if request.mode == "inventory":
			var instance := packed.instantiate()
			var row := _inventory(instance)
			row["group"] = item.group
			row["entry"] = item.entry
			rows.append(row)
			instance.free()
		elif request.mode == "partition":
			rows.append(_partition_root(item, packed) if item.get("replace_root", false) else _partition(item, packed))
		elif request.mode == "proxy_dump":
			rows.append(_proxy_dump(item, packed))
		elif request.mode == "proxy_assemble":
			rows.append(_proxy_assemble(item, packed))
		else:
			_ok(false, "Unknown mode")
		print("PROGRESSIVE_GROUP: ", item.group, "; failures=", failures.size())
	if request.mode == "proxy_assemble" and failures.is_empty():
		_proxy_verify_upgrade(rows)
	var result := {"status": "PASS" if failures.is_empty() else "FAIL", "groups": rows,
		"mode": request.mode, "packSha256": PACK_SHA, "engine": Engine.get_version_info(), "failures": failures,
		"mainSceneInstantiated": false, "offTreeOnly": true}
	_ok(str(request.output).simplify_path().begins_with(SCOPE) and not FileAccess.file_exists(request.output), "New scoped JSON output")
	var output := FileAccess.open(request.output, FileAccess.WRITE)
	output.store_string(JSON.stringify(result, "\t", true, true) + "\n")
	output.close()
	print("PROGRESSIVE_SCENES: ", result.status)
	quit(0 if failures.is_empty() else 1)
