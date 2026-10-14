extends SceneTree
## Actual entry only: no frames, chunks, RNG reset, rebuild or resource save.
const SCOPE := "E:/Projects/Godot-Octopath2/artifacts/startup-v135/independent/static-core/"
var errors: Array[String] = []
var ready_count := 0

func _initialize() -> void:
	_run.call_deferred()

func _check(ok: bool, message: String) -> bool:
	if not ok:
		errors.append(message)
		push_error("VILLAGE_ARRAYS: " + message)
	return ok

func _hash(value: Variant) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes(value))
	return context.finish().hex_encode()

func _plain(value: Variant) -> Variant:
	if value == null:
		return null
	if value is Vector2:
		return [value.x, value.y]
	if value is Vector3:
		return [value.x, value.y, value.z]
	if value is Vector4:
		return [value.x, value.y, value.z, value.w]
	if value is Color:
		return [value.r, value.g, value.b, value.a]
	if value is Array or typeof(value) >= TYPE_PACKED_BYTE_ARRAY:
		var rows: Array = []
		for item: Variant in value:
			rows.append(_plain(item))
		return rows
	return value

func _array(value: Variant) -> Dictionary:
	return {"type": type_string(typeof(value)), "sha256": _hash(value), "values": _plain(value)}

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		quit(2)
		return
	var request: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var output := str(request.out).replace("\\", "/").simplify_path()
	if not output.begins_with(SCOPE) or FileAccess.file_exists(output):
		quit(2)
		return
	root.size = Vector2i(1280, 800)
	root.content_scale_size = Vector2i(1280, 800)
	var started := Time.get_ticks_usec()
	var packed: PackedScene = load(str(ProjectSettings.get_setting("application/run/main_scene")))
	if not _check(packed != null, "Actual main scene loads"):
		quit(1)
		return
	var scene: Node3D = packed.instantiate()
	var initial_nodes := 1 + scene.find_children("*", "", true, false).size()
	scene.ready.connect(func() -> void: ready_count += 1)
	root.add_child(scene)
	current_scene = scene
	var ready_us := Time.get_ticks_usec()
	for node: Node in [scene] + scene.find_children("*", "", true, false):
		node.set_process(false)
		node.set_physics_process(false)
	_check(scene.is_node_ready() and ready_count == 1, "One complete actual ready")
	_check(FileAccess.get_sha256(request.corePack.file) == request.corePack.sha256, "Actual PCK SHA")
	for path: String in request.mountedPins:
		_check(FileAccess.get_sha256("res://" + path) == request.mountedPins[path], "Mounted entry pin: " + path)
	var village: MeshInstance3D = scene.get_node("DistantVillage")
	var surfaces: Array = []
	if _check(village.mesh is ArrayMesh, "Actual village ArrayMesh"):
		var mesh: ArrayMesh = village.mesh
		for i in range(mesh.get_surface_count()):
			var arrays: Array = mesh.surface_get_arrays(i)
			var slots: Array = []
			for value: Variant in arrays:
				slots.append(_array(value))
			surfaces.append({"primitive": mesh.surface_get_primitive_type(i), "format": mesh.surface_get_format(i),
				"arraysSha256": _hash(arrays), "slots": slots})
	var box: AABB = village.mesh.get_aabb()
	var materials := {}
	for name: String in ["DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		var node: MeshInstance3D = scene.get_node(NodePath(name))
		var material: ShaderMaterial = node.material_override
		var heights: Variant = material.get_shader_parameter("soil_heights")
		var bounds: Variant = material.get_shader_parameter("soil_bounds")
		_check(heights is PackedFloat32Array and heights.size() == 25 and bounds is Vector4, "Actual 25 soil samples and bounds: " + name)
		materials[name] = {"soil_heights": _array(heights), "soil_bounds": _array(bounds),
			"shader": material.shader.resource_path}
	var transform: Transform3D = village.global_transform
	var report := {"schema": "village-arrays-v1", "status": "OBSERVED" if errors.is_empty() else "FAIL",
		"errors": errors, "requestSha256": FileAccess.get_sha256(args[0]), "corePack": request.corePack,
		"entryNodesBeforeReady": initial_nodes, "nodeCount": 1 + scene.find_children("*", "", true, false).size(),
		"readyCount": ready_count, "cpuLoadThroughReadyMsNotBenchmark": (ready_us - started) / 1000.0,
		"surfaceArrays": surfaces, "aabb": {"sha256": _hash(box), "position": _plain(box.position), "size": _plain(box.size)},
		"transform": {"sha256": _hash(transform), "columns": [_plain(transform.basis.x), _plain(transform.basis.y), _plain(transform.basis.z)],
			"origin": _plain(transform.origin)}, "materials": materials,
		"limits": ["Real ready then immediate freeze; zero frame/chunk advances; no original conform rerun.",
			"Native array observation, not Web/performance/visual acceptance; strict full-scene FAIL remains."]}
	var file := FileAccess.open(output, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	file.close()
	scene.free()
	quit(0 if errors.is_empty() else 1)
