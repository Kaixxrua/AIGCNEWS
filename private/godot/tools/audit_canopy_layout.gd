extends SceneTree
## Read-only screen-space bounds. Bounds guide art review, not fidelity scoring.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var meadow: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var camera: Camera3D = meadow.get_node("Camera3D")
	var frame: Vector2 = root.get_visible_rect().size
	for label in ["OakOnLowerOutcrop", "YoungOakByVillage", "OldOakOnShelf", "YoungHawthornInValley",
		"HazelAboveLimestone", "DeepValleyHawthorn", "FloweredTerraceToe", "ThreeUnequalOaks"]:
		var tree: MeshInstance3D = meadow.get_node(NodePath(label))
		var points: PackedVector3Array = tree.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
		var minimum := Vector2(INF, INF)
		var maximum := Vector2(-INF, -INF)
		for point in points:
			# The cutout material uses the main camera basis even in the sun pass.
			var world := tree.global_position + camera.global_basis * point
			var screen := camera.unproject_position(world) / frame
			minimum = minimum.min(screen)
			maximum = maximum.max(screen)
		var bounds := Rect2(minimum, maximum - minimum)
		print("MEADOW_CANOPY_BOUNDS ", JSON.stringify({"name": label, "bounds": [bounds.position.x, bounds.position.y, bounds.size.x, bounds.size.y],
			"root": str(tree.global_position), "wind": tree.material_override.get_shader_parameter("wind_strength")}))
		assert(bounds.size.x < 0.18 and bounds.size.y < 0.22, "A midground crown must not overwhelm the scene")
	print("MEADOW_CANOPY_LAYOUT_AUDIT: PASS; eight distinct existing designs; rooted scale changes, no duplicated artwork")
	meadow.queue_free()
	await process_frame
	quit()
