extends SceneTree
## Real surface/space/budget checks for the reworked leaf transition, not an
## automated claim that the artwork looks like the reference.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var growth: MeshInstance3D = scene.get_node("CreepingMeadowAndLedgeGrowth")
	var roots: PackedVector3Array = growth.get_meta("ecotone_anchors")
	var heights: PackedVector2Array = growth.get_meta("ecotone_heights")
	var guides: PackedVector4Array = growth.get_meta("ecotone_guides")
	# Each shared root supports multiple real fronds; v69 broadens them and
	# redistributes density into connected colonies under the same world checks.
	assert(roots.size() > 6000 and roots.size() == heights.size() and guides.size() > 25)
	var terrain: Mesh = scene.get_node("ContinuousMeadow").mesh
	var rocks: Mesh = scene.get_node("SolidLimestoneGeology").mesh
	var queries: Array[TriangleMesh] = [terrain.generate_triangle_mesh(), rocks.generate_triangle_mesh()]
	var root_error := 0.0
	var road_margin := INF
	var arena_margin := INF
	var inner_height := 0.0
	var outer_height := 0.0
	var inner_count := 0
	var outer_count := 0
	for i in range(roots.size()):
		var p := roots[i]
		var highest := -INF
		for surface: TriangleMesh in queries:
			var hit := surface.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
			if not hit.is_empty():
				highest = maxf(highest, hit.position.y)
		assert(is_finite(highest))
		root_error = maxf(root_error, absf(p.y - highest))
		var point := Vector2(p.x, p.z)
		road_margin = minf(road_margin, scene.distance_to_road(point) - scene.road_half_width(p.z))
		arena_margin = minf(arena_margin, point.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
		assert(absf(p.x - scene.river_center(p.z)) > scene.river_half_width(p.z) + 1.79)
		# The new intermediate leaf tier stays below one metre, outside the
		# protected path/arena. Entire leaf geometry is also checked in v69.
		assert(heights[i].y > 0.04 and heights[i].y < 1.0)
		if heights[i].x > 0.72:
			inner_height += heights[i].y
			inner_count += 1
		elif heights[i].x < 0.25:
			outer_height += heights[i].y
			outer_count += 1
	assert(root_error < 0.012 and road_margin > 0.89 and arena_margin > 1.99)
	assert(inner_count > 500 and outer_count > 500)
	inner_height /= inner_count
	outer_height /= outer_count
	assert(inner_height > outer_height * 1.35, "Patch edges must taper instead of forming equal-height green walls")
	# Compare every array/transform for unaffected meshes, not merely a couple
	# of central height samples. The low cushion mesh is intentionally different.
	var original: Node3D = load("res://assets/baked/v62/detail.scn").instantiate()
	var old_cover: Mesh = original.get_node("CreepingMeadowAndLedgeGrowth").mesh
	var old_leaf_triangles := old_cover.get_faces().size() / 3
	var changed: bool = old_cover.surface_get_arrays(0)[Mesh.ARRAY_VERTEX] != growth.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	original.free()
	# v75 replaces the woody crown layer. Strengthen the unrelated-world check
	# to all seven current terrain/detail/riverbank meshes against the v74 release.
	var unchanged := 0
	for group_name: String in ["terrain", "detail", "riverbank"]:
		var old_group: Node3D = load("res://assets/baked/v74/" + group_name + ".scn").instantiate()
		for old_mesh: MeshInstance3D in old_group.get_children():
			var current: MeshInstance3D = scene.get_node(NodePath(old_mesh.name))
			assert(current.transform == old_mesh.transform)
			var a := old_mesh.mesh.surface_get_arrays(0)
			var b := current.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Woody growth changed protected ground geometry: " + old_mesh.name)
			unchanged += 1
		old_group.free()
	var triangles := growth.mesh.get_faces().size() / 3
	assert(unchanged == 7 and changed and old_leaf_triangles > 100000)
	assert(triangles < old_leaf_triangles * 1.10, "Improve massing by redistribution, not unlimited geometry growth")
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_ECOTONE_AUDIT: PASS; %d guides, %d roots, support error %.5fm; road margin %.3fm, arena margin %.3fm; inner/outer height %.3f/%.3fm; %d -> %d cushion triangles; seven v74 ground meshes exact; %d protected playfield probes" % [guides.size(), roots.size(), root_error, road_margin, arena_margin, inner_height, outer_height, old_leaf_triangles, triangles, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
