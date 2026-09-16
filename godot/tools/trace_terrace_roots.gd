extends SceneTree
## Read-only diagnostic: locate ground at existing composition positions.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var meadow: Node3D = load("res://scenes/main.tscn").instantiate()
	meadow.audit_complete = true # Diagnostic only, never reports a scene pass.
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var camera: Camera3D = meadow.get_node("Camera3D")
	var frame: Vector2 = root.get_visible_rect().size
	var space: PhysicsDirectSpaceState3D = meadow.get_world_3d().direct_space_state
	var targets := {"OakOnLowerOutcrop": Vector2(0.06, 0.383),
		"OldOakOnShelf": Vector2(0.242, 0.375), "FloweredTerraceToe": Vector2(0.314, 0.447)}
	for label in targets:
		for dy in [-0.006, 0.0, 0.006]:
			var screen: Vector2 = (targets[label] + Vector2(0.0, dy)) * frame
			var start := camera.project_ray_origin(screen)
			var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(start,
				start + camera.project_ray_normal(screen) * 250.0))
			if hit.is_empty():
				continue
			var p: Vector3 = hit.position
			var top := space.intersect_ray(PhysicsRayQueryParameters3D.create(p + Vector3.UP * 10.0, p - Vector3.UP))
			print("TERRACE_ROOT_TRACE ", JSON.stringify({"name": label, "dy": dy,
				"point": str(p), "normal": str(hit.normal), "terrain": meadow.terrain_height(p.x, p.z),
				"top_y": null if top.is_empty() else top.position.y, "collider": hit.collider.name}))
	# Find a nearby flat toe after rotating the escarpments. Only report real
	# collision hits; these measurements never bypass the normal root audits.
	var flower: Node3D = meadow.get_node("FloweredTerraceToe")
	for dx in [-0.6, -0.3, 0.0, 0.3, 0.6]:
		for dz in [-0.6, -0.3, 0.0, 0.3, 0.6]:
			var foot := flower.position + Vector3(dx, 0.0, dz)
			var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(
				Vector3(foot.x, 15.0, foot.z), Vector3(foot.x, -3.0, foot.z)))
			if hit.is_empty():
				continue
			var error: float = absf(hit.position.y - meadow.terrain_height(foot.x, foot.z))
			if error < 0.03 and hit.normal.y > 0.90:
				print("TERRACE_TOE_CANDIDATE ", JSON.stringify({"offset": [dx, dz],
					"point": str(hit.position), "normal": str(hit.normal), "surface_error": error}))
	meadow.queue_free()
	await process_frame
	quit()
