extends SceneTree
## Read-only orientation diagnostic. Compare topology against supplied normals.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	_report("NativeQuadMesh", QuadMesh.new())
	for label: String in ["IndependentCastleHill", "DistantVillage", "ContinuousMeadow", "SolidLimestoneGeology", "LivingMeadowUnderstory", "CastleFoothillWoodland", "MiddleMeadowBrush"]:
		_report(label, scene.get_node(NodePath(label)).mesh)
	scene.queue_free()
	await process_frame
	quit()

func _report(label: String, mesh: Mesh) -> void:
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	var count := indices.size() if indices.size() > 0 else vertices.size()
	var positive := 0
	var negative := 0
	var flat := 0
	for i in range(0, count, 3):
		var a := indices[i] if indices.size() > 0 else i
		var b := indices[i + 1] if indices.size() > 0 else i + 1
		var c := indices[i + 2] if indices.size() > 0 else i + 2
		var orientation := (vertices[b] - vertices[a]).cross(vertices[c] - vertices[a]).normalized().dot((normals[a] + normals[b] + normals[c]).normalized())
		if orientation > 0.20:
			positive += 1
		elif orientation < -0.20:
			negative += 1
		else:
			flat += 1
	print("MEADOW_WINDING: %s; cross-dot-normal positive=%d / negative=%d / edge-on=%d" % [label, positive, negative, flat])
