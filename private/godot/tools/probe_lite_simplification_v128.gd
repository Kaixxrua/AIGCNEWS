extends SceneTree
## Read-only source probe: no LOD candidate is integrated by this script.
func _initialize() -> void:
	root.disable_3d = true
	run.call_deferred()
func run() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if args.size() != 2: return
	if not ProjectSettings.load_resource_pack(args[0]): return
	var rows := []
	for item in [["res://assets/baked/v77/terrain.scn", "ContinuousMeadow"], ["res://assets/baked/v77/detail.scn", "SolidLimestoneGeology"]]:
		var packed: PackedScene = load(item[0])
		var node := packed.instantiate()
		var current: MeshInstance3D = node.get_node(NodePath(item[1]))
		var original: ArrayMesh = current.mesh
		var importer := ImporterMesh.new()
		importer.add_surface(Mesh.PRIMITIVE_TRIANGLES, original.surface_get_arrays(0))
		var started := Time.get_ticks_msec()
		importer.generate_lods(30.0, 0.0, [])
		var lods := []
		for i in range(importer.get_surface_lod_count(0)):
			var indices := importer.get_surface_lod_indices(0, i)
			lods.append({"triangles": indices.size() / 3, "error": importer.get_surface_lod_size(0, i)})
		rows.append({"mesh": item[1], "sourceTriangles": original.surface_get_array_index_len(0)/3,
			"probeMs": Time.get_ticks_msec() - started, "lods": lods, "notApproved": true})
		node.free()
	var path: String = args[1].replace("\\", "/")
	if not path.contains("/artifacts/startup-v128/") or FileAccess.file_exists(path): return
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(JSON.stringify(rows, "\t"));file.close()
	print("SIMPLIFICATION_PROBE: ", JSON.stringify(rows))
	quit(0)
