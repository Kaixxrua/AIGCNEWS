extends SceneTree
## Read-only projection analysis. The reference stays outside the game package.
## Screen traces guide edits; they are NOT an artistic-fidelity pass/fail test.

var meadow: Node3D
var camera: Camera3D
var frame_size := Vector2(1280, 800)

func _init() -> void:
	root.size = Vector2i(frame_size)
	call_deferred("_run")

func _run() -> void:
	meadow = load("res://scenes/main.tscn").instantiate()
	root.add_child(meadow)
	camera = meadow.get_node("Camera3D")
	await process_frame
	await physics_frame
	frame_size = root.get_visible_rect().size
	var traces := {
		"near_cliff": [Vector2(0.02, 0.705), Vector2(0.20, 0.815), Vector2(0.42, 0.910), Vector2(0.64, 0.965)],
		"main_trail": [Vector2(0.91, 0.760), Vector2(0.72, 0.700), Vector2(0.58, 0.640), Vector2(0.42, 0.605),
			Vector2(0.51, 0.550), Vector2(0.59, 0.515), Vector2(0.605, 0.460), Vector2(0.69, 0.402),
			Vector2(0.73, 0.374), Vector2(0.68, 0.344), Vector2(0.61, 0.316), Vector2(0.48, 0.280)],
		"left_tree_roots": [Vector2(0.06, 0.395), Vector2(0.20, 0.305), Vector2(0.242, 0.381)],
		"central_shrubs": [Vector2(0.445, 0.452), Vector2(0.51, 0.349), Vector2(0.698, 0.334)],
		"v43_frame_growth": [Vector2(0.005, 0.290), Vector2(0.283, 0.443), Vector2(0.445, 0.452), Vector2(0.315, 0.492)],
		"v44_meadow_colonies": [Vector2(0.188, 0.530), Vector2(0.372, 0.417), Vector2(0.303, 0.723), Vector2(0.651, 0.460)],
		"v41_low_colonies": [Vector2(0.367, 0.362), Vector2(0.455, 0.322), Vector2(0.340, 0.310),
			Vector2(0.618, 0.367), Vector2(0.583, 0.302), Vector2(0.698, 0.334),
			Vector2(0.813, 0.346), Vector2(0.579, 0.424)],
	}
	for label in traces:
		var points := []
		for screen: Vector2 in traces[label]:
			# For a crest target, intersect the undropped meadow surface. Intersecting
			# the existing cliff slope would fit a point below the intended top edge.
			var world := _ground_at(screen, label == "near_cliff")
			points.append({"screen": [screen.x, screen.y], "world": [snappedf(world.x, 0.01), snappedf(world.y, 0.01), snappedf(world.z, 0.01)]})
		print("REFERENCE_TRACE ", JSON.stringify({"name": label, "points": points}))
	for asset_label in meadow.asset_paths.values():
		var card: MeshInstance3D = meadow.get_node(NodePath(asset_label))
		var anchor := camera.unproject_position(card.global_position) / frame_size
		print("CURRENT_ART_ANCHOR ", JSON.stringify({"name": asset_label, "uv": [snappedf(anchor.x, 0.001), snappedf(anchor.y, 0.001)], "world": str(card.global_position)}))
	var castle: MeshInstance3D = meadow.get_node("IndependentCastleHill")
	print("CASTLE_PLACEMENT ", JSON.stringify({"foot_y": castle.position.y,
		"terrain_y": meadow.terrain_height(castle.position.x, castle.position.z),
		"world_size": str(castle.mesh.size)}))
	for x in [-35.0, -25.0, -15.0, -5.0, 5.0, 15.0, 25.0]:
		var z: float = meadow.foreground_edge(x) - 0.8
		var p := Vector3(x, meadow.terrain_height(x, z), z)
		print("CURRENT_CLIFF_EDGE ", JSON.stringify({"world": str(p), "uv": str(camera.unproject_position(p) / frame_size)}))
	for z in [-60.0, -38.0, -23.0, -8.0, 8.0]:
		var samples := []
		for side in [-1.0, 0.0, 1.0]:
			var p := Vector3(meadow.river_center(z) + side * meadow.river_half_width(z), -1.05, z)
			samples.append(str(camera.unproject_position(p) / frame_size))
		print("RIVER_CHANNEL_PROJECTION ", JSON.stringify({"z": z, "left_center_right": samples}))
	quit()

func _ground_at(uv: Vector2, undropped_crest: bool = false) -> Vector3:
	var start := camera.project_ray_origin(uv * frame_size)
	var direction := camera.project_ray_normal(uv * frame_size)
	var previous_t := 0.1
	for i in range(1, 841):
		var t := i * 0.5
		var p := start + direction * t
		var height: float = meadow.meadow_height(p.x, p.z) if undropped_crest else meadow.terrain_height(p.x, p.z)
		if p.y <= height:
			var high := t
			var low := previous_t
			for iteration in range(16):
				var middle := (low + high) * 0.5
				var q := start + direction * middle
				var q_height: float = meadow.meadow_height(q.x, q.z) if undropped_crest else meadow.terrain_height(q.x, q.z)
				if q.y <= q_height:
					high = middle
				else:
					low = middle
			return start + direction * ((low + high) * 0.5)
		previous_t = t
	return Vector3.INF
