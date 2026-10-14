extends "E:/Projects/Godot-Octopath2/godot/tools/build_progressive_scenes_v135.gd"
## One offline LOD hierarchy per isolated geometric piece. Never runs the scene.
## Constant normals are simplifier inputs ONLY; final buffers select untouched
## original vertex/normal/tangent/colour/UV records in the Python assembler.

func _piece_lods(item: Dictionary) -> Dictionary:
	var packed := _load("res://" + item.entry)
	var source := packed.instantiate()
	var target := source.get_node(NodePath(item.mesh)) as MeshInstance3D
	_ok(_hash(target.mesh.get("_surfaces")) == item.source_raw_sha256, "Exact previously decoded source surface")
	var vertices: PackedVector3Array = target.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	_ok(FileAccess.get_sha256(item.piece_indices.path) == item.piece_indices.sha256, "Pinned piece corner partition")
	var corners := FileAccess.get_file_as_bytes(item.piece_indices.path).to_int32_array()
	var output := PackedInt32Array()
	var results: Array = []
	var started := Time.get_ticks_msec()
	for piece: Dictionary in item.pieces:
		var original := corners.slice(int(piece.offset), int(piece.offset + piece.count))
		var maps := {}
		var inverse := PackedInt32Array()
		var positions := PackedVector3Array()
		var indices := PackedInt32Array()
		for index: int in original:
			if not maps.has(index):
				maps[index] = positions.size()
				positions.append(vertices[index])
				inverse.append(index)
			indices.append(maps[index])
		var normals := PackedVector3Array()
		normals.resize(positions.size())
		normals.fill(Vector3.UP)
		var arrays: Array = []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = positions
		arrays[Mesh.ARRAY_NORMAL] = normals
		arrays[Mesh.ARRAY_INDEX] = indices
		var importer := ImporterMesh.new()
		importer.add_surface(Mesh.PRIMITIVE_TRIANGLES, arrays)
		if not piece.get("protected", false) and indices.size() > 24:
			importer.generate_lods(30.0, 0.0, [])
		var levels: Array = []
		for level in range(importer.get_surface_lod_count(0)):
			var lod := importer.get_surface_lod_indices(0, level)
			var start := output.size()
			for index: int in lod:
				output.append(inverse[index])
			levels.append({"level": level, "offset": start, "count": lod.size(),
				"engineErrorMetric": importer.get_surface_lod_size(0, level)})
		results.append({"id": piece.id, "levels": levels})
		if results.size() % 250 == 0:
			print("PROXY_PIECES: ", item.group, " ", results.size(), "/", item.pieces.size())
	source.free()
	return {"group": item.group, "pieces": results, "indices": _binary(item.group + "-piece-lods.bin", output.to_byte_array()),
		"lodGenerationMs": Time.get_ticks_msec() - started, "renderBuffersModified": false}

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		super._run()
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	if request.get("mode") != "piece_lods":
		super._run()
		return
	if not _ok(FileAccess.get_sha256(request.pack) == PACK_SHA, "Exact native baseline"):
		quit(1)
		return
	var rows: Array = []
	for item: Dictionary in request.groups:
		_ok(FileAccess.get_sha256("res://" + item.entry) == item.sha256, "Exact full source entry")
		rows.append(_piece_lods(item))
	var report := {"status": "PASS" if failures.is_empty() else "FAIL", "groups": rows, "failures": failures,
		"offTreeOnly": true, "mainSceneInstantiated": false, "packSha256": PACK_SHA, "engine": Engine.get_version_info()}
	_ok(str(request.output).begins_with(SCOPE + "proxy-03/") and not FileAccess.file_exists(request.output), "Fresh proxy-03 output")
	var file := FileAccess.open(request.output, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	file.close()
	quit(0 if failures.is_empty() else 1)
