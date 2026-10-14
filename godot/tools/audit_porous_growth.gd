extends SceneTree
## v75: actual visible branch geometry, not metadata-only density assertions.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var unchanged := 0
	for group: String in ["terrain", "detail", "riverbank"]:
		var old: Node3D = load("res://assets/baked/v74/" + group + ".scn").instantiate()
		for previous: MeshInstance3D in old.get_children():
			var current: MeshInstance3D = scene.get_node(NodePath(previous.name))
			assert(previous.transform == current.transform)
			var a := previous.mesh.surface_get_arrays(0)
			var b := current.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Only the two woody layers may change: " + previous.name)
			unchanged += 1
		old.free()
	assert(unchanged == 7)
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var rocks: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var total_roots := 0
	for label: String in ["MiddleMeadowBrush", "CastleFoothillWoodland"]:
		var growth: MeshInstance3D = scene.get_node(NodePath(label))
		var roots: PackedVector3Array = growth.get_meta("roots" if label == "MiddleMeadowBrush" else "ground_roots")
		var root_faces: PackedInt32Array = growth.get_meta("root_faces")
		assert(roots.size() == root_faces.size() and roots.size() > 700)
		var arrays := growth.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
		var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
		var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
		var faces := growth.mesh.get_faces()
		var max_error := 0.0
		var query_roundoff := 0.0
		for i in range(roots.size()):
			var corner := root_faces[i] * 3
			var a := vertices[indices[corner] if not indices.is_empty() else corner]
			var b := vertices[indices[corner + 1] if not indices.is_empty() else corner + 1]
			var actual := (a + b) * 0.5
			query_roundoff = maxf(query_roundoff, actual.distance_to((faces[corner] + faces[corner + 1]) * 0.5))
			if actual.distance_to(roots[i]) >= 0.00005:
				print("POROUS_BASAL_MISMATCH: %s root %d; triangle %d; expected %s; actual %s; corners %s/%s" % [label, i, root_faces[i], roots[i], actual, faces[corner], faces[corner + 1]])
			assert(actual.distance_to(roots[i]) < 0.00005, "Root must be the actual basal twig edge")
			var highest := -INF
			for surface: TriangleMesh in [land, rocks]:
				var hit := surface.intersect_ray(Vector3(actual.x, 60, actual.z), Vector3.DOWN)
				if not hit.is_empty():
					highest = maxf(highest, hit.position.y)
			assert(is_finite(highest))
			max_error = maxf(max_error, absf(actual.y - highest))
		assert(max_error < 0.025)
		assert(query_roundoff < 0.00018, "Bound the triangle-query representation separately from render-root registration")
		var wind_tips := 0
		var wood := 0
		var road := INF
		var arena := INF
		for i in range(vertices.size()):
			var p := vertices[i]
			assert(p.is_finite() and absf(normals[i].length() - 1.0) < 0.001)
			var q := Vector2(p.x, p.z)
			road = minf(road, scene.distance_to_road(q) - scene.road_half_width(q.y))
			arena = minf(arena, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
			if uv[i].x < -1800:
				assert(colours[i].a == 0.0)
				wood += 1
			else:
				wind_tips += int(colours[i].a > 0.1)
			for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
				assert(not habitat.grow(0.35).has_point(q))
		for face in range(faces.size() / 3):
			var n := Vector3.ZERO
			for corner in range(3):
				var j := face * 3 + corner
				n += normals[indices[j] if not indices.is_empty() else j]
			var a := faces[face * 3]
			var b := faces[face * 3 + 1]
			var c := faces[face * 3 + 2]
			assert((b - a).cross(c - a).dot(n) < 0.0, "Clockwise twig/leaf fronts must match their light normals")
		assert(road > 0.25 and arena > 1.5 and wood > 1000 and wind_tips > 10000)
		assert(growth.get_child_count() == 0)
		assert(faces.size() / 3 < (125000 if label == "MiddleMeadowBrush" else 110000))
		print("POROUS_ROOTS: %s; %d actual twig bases; max soil error %.5fm; query roundoff %.7fm; road/Boss %.3f/%.3fm; %d triangles" % [label, roots.size(), max_error, query_roundoff, road, arena, faces.size() / 3])
		total_roots += roots.size()
	var brush: MeshInstance3D = scene.get_node("MiddleMeadowBrush")
	var heights: PackedFloat32Array = brush.get_meta("heights")
	var reaches: PackedFloat32Array = brush.get_meta("edge_distances")
	var inner := Vector2.ZERO
	var outer := Vector2.ZERO
	for i in range(heights.size()):
		if reaches[i] < 0.4:
			inner += Vector2(heights[i], 1)
		if reaches[i] > 0.8:
			outer += Vector2(heights[i], 1)
	assert(inner.y > 100 and outer.y > 100 and inner.x / inner.y > outer.x / outer.y * 1.8)
	var before_brush: Node3D = load("res://assets/baked/v74/brush.scn").instantiate()
	var old_query: TriangleMesh = before_brush.get_node("MiddleMeadowBrush").mesh.generate_triangle_mesh()
	var new_query: TriangleMesh = brush.mesh.generate_triangle_mesh()
	var old_coverage := 0
	var new_coverage := 0
	var size: Vector2 = scene.camera.get_viewport().get_visible_rect().size
	for x in range(160):
		for y in range(64):
			var screen: Vector2 = Vector2(0.02 + (x + 0.5) / 160.0 * 0.94, 0.23 + (y + 0.5) / 64.0 * 0.40) * size
			var origin: Vector3 = scene.camera.project_ray_origin(screen)
			var direction: Vector3 = scene.camera.project_ray_normal(screen)
			old_coverage += int(not old_query.intersect_ray(origin, direction).is_empty())
			new_coverage += int(not new_query.intersect_ray(origin, direction).is_empty())
	print("POROUS_MIDDLE_COVERAGE: %d -> %d camera-ray hits in 10240 fixed samples; inner/edge heights %.3f/%.3fm" % [old_coverage, new_coverage, inner.x / inner.y, outer.x / outer.y])
	assert(old_coverage > 10 and new_coverage > old_coverage * 1.5, "Wider zones must increase actual camera-visible leaf coverage")
	before_brush.free()
	var woodland: MeshInstance3D = scene.get_node("CastleFoothillWoodland")
	var previous: Node3D = load("res://assets/baked/v74/foothill.scn").instantiate()
	var old_wood: MeshInstance3D = previous.get_node("CastleFoothillWoodland")
	var old_faces := old_wood.mesh.get_faces()
	var new_faces := woodland.mesh.get_faces()
	var ranges: PackedVector2Array = woodland.get_meta("crown_ranges")
	assert(ranges.size() == old_wood.get_meta("crown_count") and ranges.size() == 283)
	assert(old_faces.size() == ranges.size() * 77 * 3)
	var shell_hits := 0
	var branch_hits := 0
	for crown in range(0, ranges.size(), 17):
		var old_group := old_faces.slice(crown * 77 * 3, (crown + 1) * 77 * 3)
		var new_group := new_faces.slice(int(ranges[crown].x) * 3, int(ranges[crown].x + ranges[crown].y) * 3)
		var a := TriangleMesh.new()
		var b := TriangleMesh.new()
		a.create_from_faces(old_group)
		b.create_from_faces(new_group)
		var bounds := Rect2(scene.camera.unproject_position(old_group[0]), Vector2.ZERO)
		for p in old_group:
			bounds = bounds.expand(scene.camera.unproject_position(p))
		for x in range(16):
			for y in range(12):
				var screen := bounds.position + bounds.size * Vector2((x + 0.5) / 16.0, (y + 0.5) / 12.0)
				var origin: Vector3 = scene.camera.project_ray_origin(screen)
				var direction: Vector3 = scene.camera.project_ray_normal(screen)
				if not a.intersect_ray(origin, direction).is_empty():
					shell_hits += 1
					branch_hits += int(not b.intersect_ray(origin, direction).is_empty())
	print("POROUS_CROWN_OPENINGS: %d/%d rays retained inside former solid silhouettes; 17 separate inspected crowns" % [branch_hits, shell_hits])
	assert(shell_hits > 500 and branch_hits > shell_hits * 0.20 and branch_hits < shell_hits * 0.88, "Retain wooded volume while opening real gaps, not alpha-cutting a solid shell")
	previous.free()
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_POROUS_GROWTH_AUDIT: PASS; seven v74 ground meshes exact; fourteen tapered middle zones; 283 open woody crowns; %d actual basal twig edges; %d protected playfield probes" % [total_roots, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
