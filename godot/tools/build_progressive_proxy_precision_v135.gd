extends "E:/Projects/Godot-Octopath2/godot/tools/build_progressive_scenes_v135.gd"
## Read-only off-tree validation of the two already encoded proxy-04 resources.

func _verify_precision(item: Dictionary) -> Dictionary:
	for key: String in ["before", "after", "full_carrier"]:
		_ok(FileAccess.get_sha256(item[key].path) == item[key].sha256, "Pinned resource " + key)
	var before := _load(item.before.path).instantiate() as Node3D
	var after := _load(item.after.path).instantiate() as Node3D
	var a := before.get_node(NodePath(item.mesh)) as MeshInstance3D
	var b := after.get_node(NodePath(item.mesh)) as MeshInstance3D
	_ok(before.transform == Transform3D.IDENTITY and after.transform == Transform3D.IDENTITY
		and a.transform == Transform3D.IDENTITY and b.transform == Transform3D.IDENTITY, "Verified identity world-space transforms")
	var old_snapshot := _snapshot(before)
	var new_snapshot := _snapshot(after)
	var comparable: Dictionary = old_snapshot.duplicate(true)
	comparable[item.mesh].properties.mesh = new_snapshot[item.mesh].properties.mesh
	comparable[item.mesh].allDecodedMeshChannels = new_snapshot[item.mesh].allDecodedMeshChannels
	_ok(comparable == new_snapshot, "Every non-mesh node/material/metadata/collision property exact")
	_ok(_properties(a.mesh, ["_surfaces", "resource_path", "resource_scene_unique_id"])
		== _properties(b.mesh, ["_surfaces", "resource_path", "resource_scene_unique_id"]), "Mesh metadata and AABB exact")
	var old_raw: Dictionary = a.mesh.get("_surfaces")[0]
	var new_raw: Dictionary = b.mesh.get("_surfaces")[0]
	_ok(old_raw.keys() == new_raw.keys(), "Surface field layout unchanged")
	for key: Variant in old_raw:
		if key not in ["vertex_data", "attribute_data"]:
			_ok(_stable(old_raw[key]) == _stable(new_raw[key]), "Exact fixed surface field " + str(key))
	for key: String in item.buffers:
		_ok(_sha(new_raw[key]) == item.buffers[key].sha256, "Actual reloaded raw buffer " + key)
	var aa := a.mesh.surface_get_arrays(0)
	var bb := b.mesh.surface_get_arrays(0)
	for channel in range(Mesh.ARRAY_MAX):
		if channel not in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
			_ok(_stable(aa[channel]) == _stable(bb[channel]), "Exact decoded tangent/RGBA/index/other channel " + str(channel))
	var max_position := 0.0
	var max_normal := 0.0
	var max_uv := 0.0
	var max_uv2 := 0.0
	for i in range(aa[Mesh.ARRAY_VERTEX].size()):
		var pa: Vector3 = aa[Mesh.ARRAY_VERTEX][i]
		var pb: Vector3 = bb[Mesh.ARRAY_VERTEX][i]
		var na: Vector3 = aa[Mesh.ARRAY_NORMAL][i]
		var nb: Vector3 = bb[Mesh.ARRAY_NORMAL][i]
		max_position = maxf(max_position, pa.distance_to(pb))
		max_normal = maxf(max_normal, rad_to_deg(na.angle_to(nb)))
		var uv_a: Vector2 = aa[Mesh.ARRAY_TEX_UV][i]
		var uv_b: Vector2 = bb[Mesh.ARRAY_TEX_UV][i]
		var uv2_a: Vector2 = aa[Mesh.ARRAY_TEX_UV2][i]
		var uv2_b: Vector2 = bb[Mesh.ARRAY_TEX_UV2][i]
		max_uv = maxf(max_uv, uv_a.distance_to(uv_b))
		max_uv2 = maxf(max_uv2, uv2_a.distance_to(uv2_b))
	_ok(max_position <= 0.02 and max_normal <= 5.0 and max_uv <= 0.002 and max_uv2 <= 0.002, "Actual Godot decoded error limits")
	_ok(FileAccess.get_sha256(item.protected.path) == item.protected.sha256, "Protected vertex index pin")
	var protected := FileAccess.get_file_as_bytes(item.protected.path).to_int32_array()
	for index: int in protected:
		for channel: int in [0, 1, 4, 5]:
			_ok(aa[channel][index] == bb[channel][index], "Protected road/bridge/Boss decoded values exact")
	var ids := {}
	for path: String in item.collider_paths:
		_ok(old_snapshot[path] == new_snapshot[path], "Exact full collider node/face buffer")
		ids[path] = after.get_node(NodePath(path)).get_instance_id()
	var full := _load(item.full_carrier.path).instantiate()
	b.mesh = full.get_node(NodePath(item.mesh)).mesh
	if item.group == "detail":
		b.material_override.set_shader_parameter("rock_ao_vertex_count", int(item.full_ao_prefix))
	b.remove_meta("progressive_visual_proxy")
	var restored := _snapshot(after)
	# Compare native typed snapshots directly, then the external JSON transport.
	# JSON.parse_string represents numeric type tags/indices as floats; that alone
	# must not reject identical Godot var_to_bytes hashes for every stored value.
	a.mesh = full.get_node(NodePath(item.mesh)).mesh
	if item.group == "detail":
		a.material_override.set_shader_parameter("rock_ao_vertex_count", int(item.full_ao_prefix))
	a.remove_meta("progressive_visual_proxy")
	var expected_native := _snapshot(before)
	var exact: bool = restored == expected_native and JSON.parse_string(JSON.stringify(restored)) == item.expected_full
	_ok(exact, "Exact candidate07 final root state with frozen proxy02 carrier")
	for path: String in ids:
		_ok(after.get_node(NodePath(path)).get_instance_id() == ids[path], "Collider instance retained after final mesh swap")
	var row := {"group": item.group, "mesh": item.mesh, "maxWorldPositionError": max_position,
		"maxNormalDegrees": max_normal, "maxUvVectorError": max_uv, "maxUv2VectorError": max_uv2,
		"protectedVertices": protected.size(), "allNonMeshPropertiesExact": comparable == new_snapshot,
		"finalRestoredExact": exact, "nativeTypedRestorationExact": restored == expected_native, "colliderInstancesPreserved": true,
		"initialSnapshot": new_snapshot, "restoredSnapshot": restored, "fullColliderNodes": item.collider_paths}
	full.free()
	before.free()
	after.free()
	return row

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if not _ok(args.size() == 1, "One request"):
		quit(1)
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	if not _ok(request.mode == "precision_verify" and FileAccess.get_sha256(request.pack) == PACK_SHA, "Pinned read-only verification"):
		quit(1)
		return
	var rows: Array = []
	for item: Dictionary in request.groups:
		rows.append(_verify_precision(item))
	var report := {"status": "PASS" if failures.is_empty() else "FAIL", "groups": rows, "failures": failures,
		"offTreeOnly": true, "mainSceneInstantiated": false, "resourcesResaved": false,
		"packSha256": PACK_SHA, "engine": Engine.get_version_info()}
	_ok(str(request.output).begins_with(SCOPE + "proxy-04/") and not FileAccess.file_exists(request.output), "Fresh owned proof")
	var output := FileAccess.open(request.output, FileAccess.WRITE)
	output.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	output.close()
	quit(0 if failures.is_empty() else 1)
