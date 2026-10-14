extends SceneTree
## Verify actual embedded volume/support/clearance and retained old geometry.
## Passing this check is not a visual-quality or reference-similarity score.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var strata: MeshInstance3D = scene.get_node("EmbeddedRiverbankStrata")
	var cover: MeshInstance3D = scene.get_node("RootedRiparianCover")
	var land: Mesh = scene.get_node("ContinuousMeadow").mesh
	var old_rocks: Mesh = scene.get_node("SolidLimestoneGeology").mesh
	var terrain_query := land.generate_triangle_mesh()
	var queries: Array[TriangleMesh] = [terrain_query, old_rocks.generate_triangle_mesh(), strata.mesh.generate_triangle_mesh()]
	var centres: PackedVector3Array = strata.get_meta("block_centres")
	var sizes: PackedVector3Array = strata.get_meta("block_sizes")
	var ranges: PackedVector2Array = strata.get_meta("block_ranges")
	var faces := strata.mesh.get_faces()
	assert(centres.size() > 30 and centres.size() == sizes.size() and ranges.size() == centres.size())
	assert(strata.get_child_count() == 1 and strata.get_child(0) is StaticBody3D)
	var minimum_embed := INF
	var visible_blocks := 0
	var upstream_blocks := 0
	var road_margin := INF
	var arena_margin := INF
	for i in range(centres.size()):
		var p := centres[i]
		var hit := terrain_query.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
		assert(not hit.is_empty())
		var embedded: float = hit.position.y - p.y
		assert(absf(embedded - sizes[i].y * 0.16) < 0.002, "Block centre must be inside the actual triangulated bank")
		minimum_embed = minf(minimum_embed, embedded)
		upstream_blocks += int(p.z < -65.0)
		var top := -INF
		for j in range(int(ranges[i].x), int(ranges[i].y)):
			top = maxf(top, faces[j].y)
		visible_blocks += int(top > hit.position.y + 0.10)
	assert(visible_blocks == centres.size() and minimum_embed > 0.065 and upstream_blocks > 15)
	var probes: PackedVector3Array = strata.get_meta("bank_relief_probes")
	var directions: PackedVector3Array = strata.get_meta("bank_relief_directions")
	assert(probes.size() == centres.size() and directions.size() == probes.size())
	var exposed_probes := 0
	var mean_relief := 0.0
	for i in range(probes.size()):
		var origin := probes[i] + directions[i] * 1.0
		var before := terrain_query.intersect_ray(origin, -directions[i])
		var after := queries[2].intersect_ray(origin, -directions[i])
		assert(not before.is_empty() and not after.is_empty())
		var relief: float = (after.position - before.position).dot(directions[i])
		assert(relief > 0.015 and relief < 1.10, "Bank-scale fractures must remain within the authored 1.1m projection envelope")
		mean_relief += relief
		exposed_probes += 1
	print("MEADOW_BANK_RELIEF_MEASURE: %d actual outward collision probes; mean %.4fm" % [exposed_probes, mean_relief / exposed_probes])
	for p: Vector3 in faces:
		assert(scene.river_shore_strength(p.z) < 0.02, "Legacy micro-surface skins must not bridge the newly sculpted bank steps")
		var q := Vector2(p.x, p.z)
		road_margin = minf(road_margin, scene.distance_to_road(q) - scene.road_half_width(p.z))
		arena_margin = minf(arena_margin, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
		assert(absf(p.z - scene.BRIDGE_Z) > 4.0)
		assert(absf(p.x - scene.river_center(p.z)) < scene.river_half_width(p.z) + scene.river_upper_slope(p.z) + 4.0)
	assert(road_margin > 0.60 and arena_margin > 2.0)
	var roots: PackedVector3Array = cover.get_meta("ground_roots")
	assert(roots.size() > 500)
	var root_error := 0.0
	for p: Vector3 in roots:
		var highest := -INF
		for query: TriangleMesh in queries:
			var hit := query.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
			if not hit.is_empty():
				highest = maxf(highest, hit.position.y)
		assert(is_finite(highest) and p.y > -1.04)
		root_error = maxf(root_error, absf(p.y - highest))
	assert(root_error < 0.012)
	var triangles := faces.size() / 3 + cover.mesh.get_faces().size() / 3
	assert(triangles < 85000, "Improve bank shape within a bounded two-batch geometry budget")
	assert(strata.cast_shadow != GeometryInstance3D.SHADOW_CASTING_SETTING_OFF)
	assert(cover.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF)
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_RIVERBANK_AUDIT: PASS; %d/%d exposed embedded blocks, %d upstream; minimum embed %.4fm; %d roots, support error %.5fm; road/arena margins %.3f/%.3fm; %d extra triangles in two batches; %d protected playfield probes" % [
		visible_blocks, centres.size(), upstream_blocks, minimum_embed, roots.size(), root_error, road_margin, arena_margin, triangles, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
