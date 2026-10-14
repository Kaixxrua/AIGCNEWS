extends SceneTree
## v71 surface, safe-space and preservation tests. Not a reference-art score.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var preserved := 0
	# The v75 woodland crown replacement is verified by its dedicated audit.
	for group: String in ["terrain", "detail", "riverbank"]:
		var previous: Node3D = load("res://assets/baked/v70/" + group + ".scn").instantiate()
		for before: MeshInstance3D in previous.get_children():
			var now: MeshInstance3D = scene.get_node(NodePath(before.name))
			assert(before.transform == now.transform)
			var a := before.mesh.surface_get_arrays(0)
			var b := now.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "New brush must not reshuffle existing geometry: %s/%d" % [before.name, channel])
			preserved += 1
		previous.free()
	assert(preserved == 7)
	var brush: MeshInstance3D = scene.get_node("MiddleMeadowBrush")
	var roots: PackedVector3Array = brush.get_meta("roots")
	var heights: PackedFloat32Array = brush.get_meta("heights")
	var patches: PackedInt32Array = brush.get_meta("patches")
	assert(roots.size() > 180 and roots.size() == heights.size() and roots.size() == patches.size())
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var stones: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var root_error := 0.0
	var counts := PackedInt32Array()
	counts.resize(scene.MIDDLE_BRUSH.GUIDES.size())
	var max_height := 0.0
	for i in range(roots.size()):
		var p: Vector3 = roots[i]
		var highest := -INF
		for surface: TriangleMesh in [land, stones]:
			var hit := surface.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
			if not hit.is_empty():
				highest = maxf(highest, hit.position.y)
		assert(is_finite(highest))
		root_error = maxf(root_error, absf(p.y - highest))
		counts[patches[i]] += 1
		max_height = maxf(max_height, heights[i])
	assert(root_error < 0.012 and max_height > 1.3 and max_height < 2.5)
	for count: int in counts:
		assert(count >= 10, "Each named middle-ground patch must contain actual rooted branches")
	var road_margin := INF
	var boss_margin := INF
	var array: Array = brush.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = array[Mesh.ARRAY_VERTEX]
	var colours: PackedColorArray = array[Mesh.ARRAY_COLOR]
	var uvs: PackedVector2Array = array[Mesh.ARRAY_TEX_UV]
	var wood_vertices := 0
	var moving_vertices := 0
	for i in range(vertices.size()):
		var p: Vector3 = vertices[i]
		var q := Vector2(p.x, p.z)
		road_margin = minf(road_margin, scene.distance_to_road(q) - scene.road_half_width(p.z))
		boss_margin = minf(boss_margin, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
		for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
			assert(not habitat.grow(0.35).has_point(q), "Entire brush must stay out of current animal random-path habitats")
		if uvs[i].x < -1800.0:
			wood_vertices += 1
			assert(colours[i].a == 0.0)
		else:
			moving_vertices += int(colours[i].a > 0.5)
	assert(road_margin > 0.65 and boss_margin > 1.5 and wood_vertices > 1000 and moving_vertices > 5000)
	var triangles := brush.mesh.get_faces().size() / 3
	assert(triangles < 125000, "Fourteen wider v75 zones have a bounded 125k triangle budget")
	assert(brush.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED)
	assert(brush.material_override.get_shader_parameter("middle_scrub") == true)
	assert(brush.get_child_count() == 0, "Decorative branch growth must not add new colliders")
	var targeted := 0
	for node in scene.get_children():
		if not node is MeshInstance3D or not node.has_meta("art_foot"):
			continue
		var material: ShaderMaterial = node.material_override
		if material.shader.resource_path != "res://shaders/meadow_cutout.gdshader":
			continue
		var declared_count = material.get_shader_parameter("canopy_count")
		# Godot returns null for an unoverridden include uniform in headless
		# mode; the actual shader default is zero. Do not cast null to int.
		var count := 0 if declared_count == null else int(declared_count)
		if scene.CANOPY_PROFILES.PROFILES.has(str(node.name)):
			assert(count == scene.CANOPY_PROFILES.PROFILES[str(node.name)].size())
			assert(is_equal_approx(float(material.get_shader_parameter("canopy_strength")), 0.92))
			targeted += 1
		else:
			assert(count == 0, "Do not round uninspected props or combined forest art into one sphere")
	assert(targeted == 5)
	print("MEADOW_CANOPY_BRUSH_AUDIT: PASS; %d exact v70 meshes; %d explicitly profiled trees; %d stems across %s patches, max height %.3fm, root error %.5fm; %d new triangles in one batch; entire-leaf road/Boss margins %.3f/%.3fm; current animal habitats unchanged" % [preserved, targeted, roots.size(), str(counts), max_height, root_error, triangles, road_margin, boss_margin])
	scene.queue_free()
	await process_frame
	quit()
