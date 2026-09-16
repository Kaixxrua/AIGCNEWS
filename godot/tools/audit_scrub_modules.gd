extends SceneTree
## Actual source/mesh/soil registration, independent rocks and preserved world.
const MODULES = preload("res://scripts/meadow_scrub_modules.gd")
const HERBS = preload("res://scripts/meadow_herb_modules.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var preserved := 0
	# The v75 woody meshes intentionally change; all unrelated geometry is exact.
	for group: String in ["terrain", "detail", "riverbank"]:
		var old: Node3D = load("res://assets/baked/v73/" + group + ".scn").instantiate()
		for previous: MeshInstance3D in old.get_children():
			var current: MeshInstance3D = scene.get_node(NodePath(previous.name))
			assert(previous.transform == current.transform)
			var a := previous.mesh.surface_get_arrays(0)
			var b := current.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Scrub changes must not reshuffle established world geometry: " + previous.name)
			preserved += 1
		old.free()
	assert(preserved == 7)
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var atlas := MODULES.TEXTURE.get_image()
	var regions: Array[Rect2] = []
	var feet_count := 0
	var max_root_error := 0.0
	var min_road := INF
	var min_boss := INF
	var faces := 0
	var wildlife = scene.get_node("LivingWildlife")
	for i in range(6):
		var plant: MeshInstance3D = scene.get_node(MODULES.NAMES[i])
		var material: ShaderMaterial = plant.material_override
		assert(plant.get_meta("art_foot") == MODULES.FEET[i])
		assert(plant.get_meta("art_width") == MODULES.WIDTHS[i])
		assert(material.get_shader_parameter("asset_texture") == MODULES.TEXTURE)
		assert(material.get_shader_parameter("painted_fill") <= 0.04)
		assert(material.get_shader_parameter("rooted_herb") == true)
		assert(material.get_shader_parameter("remove_pale_matte") == false)
		var crop: Rect2i = MODULES.CROPS[i]
		var height: float = plant.get_meta("art_height")
		assert(is_equal_approx(height, MODULES.WIDTHS[i] * crop.size.y / float(crop.size.x)))
		var uv: Vector4 = material.get_shader_parameter("uv_region")
		var region := Rect2(Vector2(uv.x, uv.y), Vector2(uv.z, uv.w))
		for other: Rect2 in regions:
			assert(not region.intersects(other), "Every source design is used once")
		regions.append(region)
		var arrays := plant.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
		var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
		var plant_road := INF
		var worst_road := Vector2.ZERO
		assert(vertices.size() == (HERBS.COLUMNS + 1) * (HERBS.ROWS + 1))
		for column in range(HERBS.COLUMNS + 1):
			var start: int = column * (HERBS.ROWS + 1)
			assert(uvs[start].y == 0.0 and uvs[start + HERBS.ROWS].y == 1.0)
			assert(is_equal_approx(vertices[start].y, height * 0.975), "Keep native upper silhouettes")
			for row in range(HERBS.ROWS + 1):
				var k := start + row
				assert(absf(normals[k].length() - 1.0) < 0.001)
				if row >= HERBS.ROOT_ROW:
					assert(colours[k].a == 0.0, "Measured roots must not drift with wind")
				if row > 0:
					assert(vertices[k].y < vertices[k - 1].y, "Do not fold the image at its base")
				var world: Vector3 = plant.position + scene.camera.global_basis * vertices[k]
				var p := Vector2(world.x, world.z)
				var road_margin: float = scene.distance_to_road(p) - scene.road_half_width(p.y)
				if road_margin < plant_road:
					plant_road = road_margin
					worst_road = p
				min_road = minf(min_road, scene.distance_to_road(p) - scene.road_half_width(p.y))
				min_boss = minf(min_boss, p.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
		for j in range(0, indices.size(), 3):
			var a := indices[j]
			var b := indices[j + 1]
			var c := indices[j + 2]
			assert((vertices[b] - vertices[a]).cross(vertices[c] - vertices[a]).dot(normals[a] + normals[b] + normals[c]) < 0.0)
			faces += 1
		var roots: PackedVector3Array = plant.get_meta("herb_roots")
		var source_uvs: PackedVector2Array = plant.get_meta("herb_root_uvs")
		assert(roots.size() >= 4 and roots.size() == source_uvs.size(), "Need visible basal stems, not transparent annotations")
		var plant_error := 0.0
		for j in range(roots.size()):
			var p := roots[j]
			assert(source_uvs[j].y >= MODULES.BASAL_BAND)
			var source_xy := Vector2(crop.position) + source_uvs[j] * Vector2(crop.size - Vector2i.ONE)
			var alpha_sum := 0.0
			for dx in range(-2, 3):
				alpha_sum += atlas.get_pixel(roundi(source_xy.x) + dx, roundi(source_xy.y)).a
			assert(alpha_sum > 1.8)
			var column := roundi(source_uvs[j].x * HERBS.COLUMNS)
			var actual: Vector3 = plant.position + scene.camera.global_basis * vertices[column * (HERBS.ROWS + 1) + HERBS.ROOT_ROW]
			assert(actual.distance_to(p) < 0.00002)
			var hit := land.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
			assert(not hit.is_empty() and hit.position.y > -0.95)
			plant_error = maxf(plant_error, absf(p.y - hit.position.y))
			assert(not wildlife.safe_point(Vector2(p.x, p.z)))
			feet_count += 1
		max_root_error = maxf(max_root_error, plant_error)
		print("SCRUB_ROOT_MEASURE: %s; %d basal source points; ground error %.5fm; road %.4fm at %s" % [MODULES.NAMES[i], roots.size(), plant_error, plant_road, worst_road])
		assert(plant_error < 0.026, "Actual mesh sampling should retain only the deliberate 2.5cm soil sink")
	print("SCRUB_CLEARANCE: road/Boss %.4f/%.4fm" % [min_road, min_boss])
	assert(min_road > 0.25 and min_boss > 1.0)
	var stones: MeshInstance3D = scene.get_node("ScrubStoneSupports")
	assert(stones.material_override == scene.get_node("SolidLimestoneGeology").material_override)
	assert(stones.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED)
	assert(stones.find_children("*", "CollisionShape3D", true, false).size() == 1)
	var arrays := stones.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var centers: PackedVector3Array = stones.get_meta("scrub_stone_centers")
	var ranges: PackedVector2Array = stones.get_meta("scrub_stone_ranges")
	assert(centers.size() == 8 and ranges.size() == 8)
	var query := stones.mesh.generate_triangle_mesh()
	var all_stone_road := INF
	var all_stone_boss := INF
	for i in range(8):
		var center := centers[i]
		var low := INF
		var high := -INF
		var stone_road := INF
		var start := int(ranges[i].x)
		var count := int(ranges[i].y)
		for j in range(start, start + count):
			var p := vertices[j]
			var soil := land.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
			assert(not soil.is_empty() and soil.position.y > -0.95)
			low = minf(low, p.y - soil.position.y)
			high = maxf(high, p.y - soil.position.y)
			var q := Vector2(p.x, p.z)
			stone_road = minf(stone_road, scene.distance_to_road(q) - scene.road_half_width(q.y))
			all_stone_boss = minf(all_stone_boss, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
			if (j - start) % 3 == 0:
				assert((vertices[j + 1] - p).cross(vertices[j + 2] - p).dot(normals[j] + normals[j + 1] + normals[j + 2]) < 0.0)
		var hit := query.intersect_ray(Vector3(center.x, 60, center.z), Vector3.DOWN)
		assert(not hit.is_empty() and low < -0.05 and high > 0.10)
		assert(not wildlife.safe_point(Vector2(center.x, center.z)))
		all_stone_road = minf(all_stone_road, stone_road)
		print("SCRUB_STONE_MEASURE: %d; soil-relative bottom/top %.4f/%.4fm; road %.4fm" % [i, low, high, stone_road])
	assert(all_stone_road > 0.25 and all_stone_boss > 1.0)
	# New geology must not bury existing seams or the visible bases of the new
	# plants. Check every measured root family, not just the low-cover batch.
	var checked_roots := 0
	for child in scene.get_children():
		for key: StringName in child.get_meta_list():
			var value = child.get_meta(key)
			if value is PackedVector3Array and (String(key).contains("root") or String(key).contains("anchors")):
				for p: Vector3 in value:
					var hit := query.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
					if not hit.is_empty():
						assert(hit.position.y - p.y < 0.011, "A new stone must not bury a measured plant root: %s %s" % [child.name, p])
					checked_roots += 1
	assert(checked_roots > 50000)
	print("SCRUB_ROOT_PRESERVATION: %d measured root samples; no new stone intersects visible plant bases" % checked_roots)
	var before := stones.mesh.surface_get_arrays(0)
	var weather = scene.get_node("LivingWeather")
	weather.set_process(false)
	weather.set_motion(true)
	weather.advance_weather(2.0)
	weather.toggle_time()
	weather.advance_weather(3.2)
	for channel in range(Mesh.ARRAY_MAX):
		assert(before[channel] == stones.mesh.surface_get_arrays(0)[channel], "Rocks must not deform with leaf wind")
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_SCRUB_AUDIT: PASS; six unique plant-only modules; %d grounded basal points; %.5fm maximum root error; %d curved plant triangles; eight independent colliding stones; %d exact v73 world meshes; %d protected probes" % [feet_count, max_root_error, faces, preserved, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
