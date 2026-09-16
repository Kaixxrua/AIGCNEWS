extends SceneTree
## Diagnostic only: intersect reference image coordinates with actual colliders.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var meadow: Node3D = load("res://scenes/main.tscn").instantiate()
	# This diagnostic does not advertise a pass; normal tests remain enabled elsewhere.
	meadow.audit_complete = true
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var camera: Camera3D = meadow.get_node("Camera3D")
	var frame: Vector2 = root.get_visible_rect().size
	var space: PhysicsDirectSpaceState3D = meadow.get_world_3d().direct_space_state
	var targets := {"OakOnLowerOutcrop": Vector2(0.06, 0.395), "OldOakOnShelf": Vector2(0.242, 0.381)}
	for label in targets:
		for dx in [-0.006, 0.0, 0.006]:
			for dy in [-0.006, 0.0, 0.006]:
				var screen: Vector2 = (targets[label] + Vector2(dx, dy)) * frame
				var start := camera.project_ray_origin(screen)
				var ray := PhysicsRayQueryParameters3D.create(start, start + camera.project_ray_normal(screen) * 250.0)
				var hit := space.intersect_ray(ray)
				if hit.is_empty():
					continue
				var p: Vector3 = hit.position
				var top_ray := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 8.0, p - Vector3.UP)
				var top := space.intersect_ray(top_ray)
				print("CANOPY_SUPPORT_TRACE ", JSON.stringify({"name": label, "offset": [dx, dy], "point": str(p), "normal": str(hit.normal),
					"top_y": null if top.is_empty() else top.position.y, "terrain": meadow.terrain_height(p.x, p.z), "collider": hit.collider.name}))
	meadow.queue_free()
	await process_frame
	quit()
