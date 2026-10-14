extends SceneTree
## Physical relief and preserved terrain/embedded-rock regression, not a
## visual similarity score. The Web day/night comparison is still required.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var geology: MeshInstance3D = scene.get_node("SolidLimestoneGeology")
	var old_group: Node3D = load("res://assets/baked/v63/detail.scn").instantiate()
	var old_geology: MeshInstance3D = old_group.get_node("SolidLimestoneGeology")
	var current_shape := geology.mesh.generate_triangle_mesh()
	var old_shape := old_geology.mesh.generate_triangle_mesh()
	var probes: PackedVector3Array = geology.get_meta("relief_probes")
	var directions: PackedVector3Array = geology.get_meta("relief_normals")
	assert(probes.size() > 2500 and probes.size() == directions.size())
	var exterior_samples := 0
	var changed_samples := 0
	var sum_relief := 0.0
	var max_relief := 0.0
	for i in range(0, probes.size(), 3):
		var point := probes[i]
		var direction := directions[i]
		var origin := point + direction * 1.5
		var now := current_shape.intersect_ray(origin, -direction)
		if now.is_empty() or now.position.distance_to(point) > 0.018:
			continue # Existing embedded stones may hide part of the backing wall.
		var before := old_shape.intersect_ray(origin, -direction)
		if before.is_empty():
			continue
		exterior_samples += 1
		var amount: float = (now.position - before.position).dot(direction)
		if amount > 0.012 and amount < 0.5:
			changed_samples += 1
			sum_relief += amount
			max_relief = maxf(max_relief, amount)
	assert(exterior_samples > 250 and changed_samples > 200, "Relief must exist on actual outward-facing collision triangles")
	var old_count := old_geology.mesh.get_faces().size() / 3
	var new_count := geology.mesh.get_faces().size() / 3
	assert(new_count > old_count and new_count < old_count * 1.35, "Keep fractured surfaces inside a bounded geometry budget")
	var arrays := geology.mesh.surface_get_arrays(0)
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var field: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	var fronts := 0
	var backs := 0
	for i in range(colours.size()):
		if colours[i].r < 0.5:
			continue
		assert(field[i].y >= 0.0 and field[i].y <= 1.0)
		fronts += int(field[i].y < 0.22)
		backs += int(field[i].y > 0.90)
	assert(fronts > 1000 and backs > 1000)
	assert(geology.material_override.shader.code.contains("UV2.y") and geology.material_override.shader.code.contains("edge_tufts"))
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	var before_metrics: Dictionary = old_geology.get_meta("builder_metrics")
	var metrics: Dictionary = geology.get_meta("builder_metrics")
	# The 75 v63 river stones are resampled on the new bank; all other
	# stone counts/bed domains and continuous escarpments remain unchanged.
	assert(before_metrics.stones - 75 == metrics.stones - metrics.bank_stones and before_metrics.bedded == metrics.bedded and before_metrics.walls == metrics.walls)
	print("MEADOW_ROCK_RELIEF_AUDIT: PASS; %d/%d outward surface samples changed, mean %.4fm max %.4fm; %d -> %d rock triangles; %d exposed-edge / %d soil-backed turf vertices; non-river stone counts retained; %d protected playfield probes" % [changed_samples, exterior_samples, sum_relief / changed_samples, max_relief, old_count, new_count, fronts, backs, protection.safe_probes])
	old_group.free()
	scene.queue_free()
	await process_frame
	quit()
