extends SceneTree
## Read-only placement diagnostic: all actual plant roots, exact stone shapes.
const MODULES = preload("res://scripts/meadow_scrub_modules.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	var roots := PackedVector3Array()
	for child in scene.get_children():
		for key: StringName in child.get_meta_list():
			var value = child.get_meta(key)
			if value is PackedVector3Array and (String(key).contains("root") or String(key).contains("anchors")):
				roots.append_array(value)
	var stones: MeshInstance3D = scene.get_node("ScrubStoneSupports")
	var centers: PackedVector3Array = stones.get_meta("scrub_stone_centers")
	var ranges: PackedVector2Array = stones.get_meta("scrub_stone_ranges")
	var groups: Array = stones.get_meta("scrub_stone_groups")
	var vertices: PackedVector3Array = stones.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	var chosen := PackedVector3Array()
	var radii := PackedFloat32Array()
	for i in range(8):
		var local := PackedVector3Array()
		var radius := 0.0
		for j in range(int(ranges[i].x), int(ranges[i].x + ranges[i].y)):
			var v := vertices[j] - centers[i]
			local.append(v)
			radius = maxf(radius, Vector2(v.x, v.z).length())
		var shape := TriangleMesh.new()
		shape.create_from_faces(local)
		var original := Vector2(centers[i].x, centers[i].z)
		var nearby := PackedVector3Array()
		for point in roots:
			if Vector2(point.x, point.z).distance_to(original) < 3.5:
				nearby.append(point)
		var choices: Array[Vector2] = []
		for ix in range(-15, 16):
			for iz in range(-15, 16):
				choices.append(original + Vector2(ix, iz) * 0.1)
		choices.sort_custom(func(a: Vector2, b: Vector2) -> bool: return a.distance_squared_to(original) < b.distance_squared_to(original))
		var found := false
		for p in choices:
			var blocked := false
			for j in range(chosen.size()):
				if p.distance_to(Vector2(chosen[j].x, chosen[j].z)) < radius + radii[j] + 0.04:
					blocked = true
			if blocked:
				continue
			var center := Vector3(p.x, scene.terrain_height(p.x, p.y) + 0.07, p.y)
			for foot in nearby:
				if Vector2(foot.x, foot.z).distance_to(p) > radius:
					continue
				var hit := shape.intersect_ray(Vector3(foot.x, 60, foot.z) - center, Vector3.DOWN)
				if not hit.is_empty() and hit.position.y + center.y - foot.y > 0.010:
					blocked = true
					break
			if blocked:
				continue
			for v in local:
				var q := Vector2(v.x + center.x, v.z + center.z)
				if scene.distance_to_road(q) - scene.road_half_width(q.y) < 0.3 or q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS < 1.0 or scene.terrain_height(q.x, q.y) <= -0.94:
					blocked = true
					break
			if blocked:
				continue
			chosen.append(center)
			radii.append(radius)
			print("SCRUB_ALL_ROOT_GAP: stone %d; offset %s; displacement %.4fm; nearby roots %d" % [i, p - MODULES.FEET[groups[i]], p.distance_to(original), nearby.size()])
			found = true
			break
		assert(found, "No safe measured gap for stone %d" % i)
	scene.queue_free()
	await process_frame
	quit()
