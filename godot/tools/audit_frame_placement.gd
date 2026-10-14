extends SceneTree
## Read-only neighbourhood probes for new frame-growth roots. No scene writes.

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	var meadow: Node3D = load("res://scenes/main.tscn").instantiate()
	meadow.audit_complete = true
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var camera: Camera3D = meadow.get_node("Camera3D")
	for label in ["LeftFrameOak", "HazelAboveLimestone", "DeepValleyHawthorn", "FloweredTerraceToe"]:
		var origin: Vector3 = meadow.get_node(NodePath(label)).position
		for dz in [-0.8, 0.0, 0.8]:
			for dx in [-0.8, 0.0, 0.8]:
				var p := Vector2(origin.x + dx, origin.z + dz)
				var expected: float = meadow.terrain_height(p.x, p.y)
				var ray := PhysicsRayQueryParameters3D.create(Vector3(p.x, expected + 8.0, p.y), Vector3(p.x, expected - 3.0, p.y))
				var result: Dictionary = meadow.get_world_3d().direct_space_state.intersect_ray(ray)
				var uv := camera.unproject_position(Vector3(p.x, expected, p.y)) / root.get_visible_rect().size
				print("FRAME_PLACEMENT ", JSON.stringify({"name": label, "x": p.x, "z": p.y,
					"ground": expected, "hit": null if result.is_empty() else result.position.y,
					"collider": "none" if result.is_empty() else str(result.collider.get_parent().name),
					"screen": [uv.x, uv.y]}))
	quit()
