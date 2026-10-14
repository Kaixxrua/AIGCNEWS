extends SceneTree
## Read-only trace of the user's foreground landmarks onto real scene collision.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var meadow: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var camera: Camera3D = meadow.get_node("Camera3D")
	var frame: Vector2 = root.get_visible_rect().size
	var targets := {
		"fence_near": Vector2(0.064, 0.730),
		"fence_second": Vector2(0.116, 0.704),
		"fence_third": Vector2(0.164, 0.678),
		"fence_far": Vector2(0.210, 0.660),
		"lantern_root": Vector2(0.236, 0.672),
		"verge_below_lamp": Vector2(0.225, 0.729),
		"verge_crest": Vector2(0.32, 0.785),
	}
	for label in targets:
		var uv: Vector2 = targets[label]
		var start := camera.project_ray_origin(uv * frame)
		var ray := PhysicsRayQueryParameters3D.create(start, start + camera.project_ray_normal(uv * frame) * 420.0)
		var hit := meadow.get_world_3d().direct_space_state.intersect_ray(ray)
		if hit.is_empty():
			print("FOREGROUND_TRACE_MISS ", label)
			continue
		var p: Vector3 = hit.position
		print("FOREGROUND_TRACE ", JSON.stringify({"name": label, "screen": [uv.x, uv.y],
			"world": [p.x, p.y, p.z], "normal": str(hit.normal),
			"heightfield": meadow.terrain_height(p.x, p.z),
			"road_clearance": meadow.distance_to_road(Vector2(p.x, p.z)) - meadow.road_half_width(p.z),
			"rim_distance": meadow.foreground_edge(p.x) - p.z}))
	meadow.queue_free()
	await process_frame
	quit()
