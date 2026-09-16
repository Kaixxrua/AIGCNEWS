extends SceneTree
## Offline artifact generation only. No source PNG transformations.
const MAIN = preload("res://scenes/main.tscn")
const CACHE = preload("res://scripts/meadow_static_cache.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	assert(OS.get_cmdline_user_args().has("--rebuild-static"), "Bake must use the procedural source, never its previous cache")
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	assert(DirAccess.make_dir_recursive_absolute(CACHE.DIRECTORY) == OK)
	var total_bytes := 0
	for group: String in CACHE.GROUPS:
		var container := Node3D.new()
		container.name = "BakedMeadow"
		container.set_meta("cache_version", CACHE.VERSION)
		container.set_meta("source_signature", CACHE.signature())
		for label: String in CACHE.GROUPS[group]:
			var copy := scene.get_node(label).duplicate()
			if not _index_meshes(copy):
				copy.free()
				container.free()
				scene.queue_free()
				quit(1)
				return
			container.add_child(copy)
			_own(copy, container)
		var packed := PackedScene.new()
		assert(packed.pack(container) == OK)
		var path: String = CACHE.DIRECTORY + group + ".scn"
		assert(ResourceSaver.save(packed, path, ResourceSaver.FLAG_COMPRESS) == OK)
		var file := FileAccess.open(path, FileAccess.READ)
		total_bytes += file.get_length()
		print("MEADOW_BAKE_FILE: %s; %d bytes; %d root nodes" % [path, file.get_length(), container.get_child_count()])
		file.close()
		container.free()
	print("MEADOW_BAKE_AUDIT: PASS; %d geometry bundles; %d bytes; signature %s" % [CACHE.GROUPS.size(), total_bytes, CACHE.signature()])
	scene.queue_free()
	await process_frame
	quit()

func _own(node: Node, owner_root: Node) -> void:
	node.owner = owner_root
	for child in node.get_children():
		_own(child, owner_root)

func _index_meshes(node: Node) -> bool:
	if node is MeshInstance3D and node.mesh is ArrayMesh and node.mesh.surface_get_array_index_len(0) == 0:
		var before: Mesh = node.mesh
		var source: Array = before.surface_get_arrays(0)
		var surface := SurfaceTool.new()
		surface.create_from(before, 0)
		surface.index()
		var indexed := surface.commit()
		if before.get_faces() != indexed.get_faces():
			push_error("Indexing moved/reordered a triangle")
			return false
		var after := indexed.surface_get_arrays(0)
		var indices: PackedInt32Array = after[Mesh.ARRAY_INDEX]
		for attribute in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
			if source[attribute] == null:
				continue
			for sample in range(0, indices.size(), 139):
				var a = source[attribute][sample]
				var b = after[attribute][indices[sample]]
				# Godot decodes/re-encodes packed octahedral normals here. Retain a
				# tight measured quantization bound; colour/UV/wind remain exact.
				var valid: bool = a.distance_to(b) < 0.0002 if attribute == Mesh.ARRAY_NORMAL else a == b
				if not valid:
					push_error("Indexing changed material/normal/wind data")
					return false
		node.mesh = indexed
		print("MEADOW_INDEX_AUDIT: %s; %d -> %d vertices; exact triangles, exact sampled colour/UV/wind, normal roundoff <0.0002" % [node.name, before.surface_get_array_len(0), indexed.surface_get_array_len(0)])
	for child in node.get_children():
		if not _index_meshes(child):
			return false
	return true
