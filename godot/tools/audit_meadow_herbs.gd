extends SceneTree
## Actual new herb surfaces, source registration and full unchanged world arrays.
const MODULES = preload("res://scripts/meadow_herb_modules.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var preserved := 0
	# v75 explicitly replaces woody growth, covered by audit_porous_growth.gd.
	for group: String in ["terrain", "detail", "riverbank"]:
		var old: Node3D = load("res://assets/baked/v72/" + group + ".scn").instantiate()
		for previous: MeshInstance3D in old.get_children():
			var current: MeshInstance3D = scene.get_node(NodePath(previous.name))
			assert(previous.transform == current.transform)
			var a := previous.mesh.surface_get_arrays(0)
			var b := current.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Herb replacement must retain established world meshes: " + previous.name)
			preserved += 1
		old.free()
	assert(preserved == 7)
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var stone: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var root_error := 0.0
	var root_count := 0
	var min_road := INF
	var min_boss := INF
	var face_count := 0
	var atlas := MODULES.TEXTURE.get_image()
	var crop_uvs: Array[Rect2] = []
	for index in range(2):
		var plant: MeshInstance3D = scene.get_node(MODULES.NAMES[index])
		var material: ShaderMaterial = plant.material_override
		assert(material.get_shader_parameter("asset_texture") == MODULES.TEXTURE)
		assert(material.get_shader_parameter("remove_pale_matte") == false)
		assert(material.get_shader_parameter("painted_fill") <= 0.04)
		assert(material.get_shader_parameter("wind_strength") > 0.05)
		assert(material.get_shader_parameter("rooted_herb") == true)
		assert(plant.get_meta("art_foot") == MODULES.FEET[index])
		assert(plant.get_meta("seam_sampling_foot") == MODULES.OLD_SEAM_FEET[index])
		assert(plant.get_meta("art_width") == MODULES.WIDTHS[index])
		var crop: Rect2i = plant.get_meta("herb_source_crop")
		var uv: Vector4 = material.get_shader_parameter("uv_region")
		crop_uvs.append(Rect2(Vector2(uv.x, uv.y), Vector2(uv.z, uv.w)))
		var height: float = plant.get_meta("art_height")
		assert(is_equal_approx(height, MODULES.WIDTHS[index] * crop.size.y / float(crop.size.x)))
		var arrays := plant.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
		var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
		assert(vertices.size() == (MODULES.COLUMNS + 1) * (MODULES.ROWS + 1))
		var depth_low := INF
		var depth_high := -INF
		for column in range(MODULES.COLUMNS + 1):
			var start: int = column * (MODULES.ROWS + 1)
			assert(uvs[start].y == 0.0 and uvs[start + MODULES.ROWS].y == 1.0)
			for row in range(MODULES.ROWS + 1):
				var k := start + row
				depth_low = minf(depth_low, vertices[k].z)
				depth_high = maxf(depth_high, vertices[k].z)
				assert(normals[k].is_finite() and absf(normals[k].length() - 1.0) < 0.001)
				assert(colours[k].a == 0.0 if row >= MODULES.ROOT_ROW else colours[k].a >= 0.0)
				if row == 0:
					assert(colours[k].a == 1.0)
				if row > 0:
					assert(vertices[k].y < vertices[k - 1].y, "Herb ground deformation must not fold its image")
				var world: Vector3 = plant.position + scene.camera.global_basis * vertices[k]
				var p := Vector2(world.x, world.z)
				min_road = minf(min_road, scene.distance_to_road(p) - scene.road_half_width(p.y))
				min_boss = minf(min_boss, p.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
		assert(depth_high - depth_low > 0.40, "Use a genuinely curved surface, not a flat replacement sticker")
		for i in range(0, indices.size(), 3):
			var a := indices[i]
			var b := indices[i + 1]
			var c := indices[i + 2]
			var cross := (vertices[b] - vertices[a]).cross(vertices[c] - vertices[a])
			assert(cross.dot(normals[a] + normals[b] + normals[c]) < 0.0, "Clockwise front surfaces must face the light correctly")
			face_count += 1
		var roots: PackedVector3Array = plant.get_meta("herb_roots")
		var source_uvs: PackedVector2Array = plant.get_meta("herb_root_uvs")
		assert(roots.size() > 35 and roots.size() == source_uvs.size())
		var wildlife = scene.get_node("LivingWildlife")
		for i in range(roots.size()):
			var p := roots[i]
			var best_y := -INF
			for surface: TriangleMesh in [land, stone]:
				var hit := surface.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
				if not hit.is_empty():
					best_y = maxf(best_y, hit.position.y)
			assert(is_finite(best_y))
			root_error = maxf(root_error, absf(p.y - best_y))
			# Each support annotation must correspond to the actual root-row vertex.
			var column := roundi(source_uvs[i].x * MODULES.COLUMNS)
			var at: int = column * (MODULES.ROWS + 1) + MODULES.ROOT_ROW
			var actual: Vector3 = plant.position + scene.camera.global_basis * vertices[at]
			assert(actual.distance_to(p) < 0.00002)
			var source_xy := Vector2(crop.position) + source_uvs[i] * Vector2(crop.size - Vector2i.ONE)
			var alpha_sum := 0.0
			for dx in range(-2, 3):
				alpha_sum += atlas.get_pixel(roundi(source_xy.x) + dx, roundi(source_xy.y)).a
			assert(alpha_sum > 1.8, "Do not count transparent anchors as plant roots")
			assert(not wildlife.safe_point(Vector2(p.x, p.z)), "Animals must route around the new herb body")
			root_count += 1
		assert(plant.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED)
	assert(not crop_uvs[0].intersects(crop_uvs[1]))
	print("MEADOW_HERB_MEASURE: %d real source feet; ground error %.5fm; road/Boss margins %.3f/%.3fm; %d curved triangles" % [root_count, root_error, min_road, min_boss, face_count])
	assert(root_error < 0.075 and min_road > 0.25 and min_boss > 1.0)
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_HERB_AUDIT: PASS; two unique native-aspect RGBA modules; measured curved ground support; %d exact v72 meshes; %d protected playfield probes" % [preserved, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
