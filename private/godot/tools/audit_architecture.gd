extends SceneTree
## Registration and preservation checks; WebGL/image review is still required.
const PROFILES = preload("res://scripts/meadow_architecture_profiles.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var preserved := 0
	# v75 intentionally replaces the two woody growth meshes; its dedicated
	# porous-growth audit owns them. Every unrelated world mesh remains exact.
	for group: String in ["terrain", "detail", "riverbank"]:
		var previous: Node3D = load("res://assets/baked/v71/" + group + ".scn").instantiate()
		for before: MeshInstance3D in previous.get_children():
			var now: MeshInstance3D = scene.get_node(NodePath(before.name))
			assert(before.transform == now.transform)
			var old_arrays := before.mesh.surface_get_arrays(0)
			var new_arrays := now.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(old_arrays[channel] == new_arrays[channel], "Architecture must not reshuffle world geometry: " + before.name)
			preserved += 1
		previous.free()
	assert(preserved == 7)
	var weather = scene.get_node("LivingWeather")
	assert(weather.settlement_bounce.light_cull_mask == 32 and not weather.settlement_bounce.shadow_enabled)
	assert(weather.settlement_bounce.light_energy == 0.0)
	var receiving := 0
	for node in scene.get_children():
		if not node is MeshInstance3D:
			continue
		var should_receive: bool = str(node.name) in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]
		assert(bool(node.layers & 32) == should_receive, "Settlement sky fill must not brighten meadow, water or other art")
		receiving += int(should_receive)
	assert(receiving == 4)
	var samples := 0
	var minimum_opaque := 1.0
	var invalid_regions: Array[String] = []
	var front_faces := 0
	for label: String in ["IndependentCastleHill", "DistantVillage"]:
		var art: MeshInstance3D = scene.get_node(NodePath(label))
		var material: ShaderMaterial = art.material_override
		assert(material.shader == PROFILES.SHADER)
		assert(material.get_shader_parameter("architecture_count") == 32)
		assert(is_equal_approx(float(material.get_shader_parameter("painted_fill")), 0.18))
		assert(material.get_shader_parameter("wind_strength") == 0.0)
		assert(material.get_shader_parameter("window_count") == (32 if label == "IndependentCastleHill" else 20))
		assert(art.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF)
		assert(material.get_shader_parameter("face_camera") == false)
		var mesh_data := art.mesh.surface_get_arrays(0)
		var mesh_vertices: PackedVector3Array = mesh_data[Mesh.ARRAY_VERTEX]
		var mesh_normals: PackedVector3Array = mesh_data[Mesh.ARRAY_NORMAL]
		var mesh_indices: PackedInt32Array = mesh_data[Mesh.ARRAY_INDEX]
		for triangle in range(0, mesh_indices.size(), 3):
			var a := mesh_indices[triangle]
			var b := mesh_indices[triangle + 1]
			var c := mesh_indices[triangle + 2]
			var geometric := (mesh_vertices[b] - mesh_vertices[a]).cross(mesh_vertices[c] - mesh_vertices[a]).normalized()
			assert(geometric.dot(mesh_normals[a]) < -0.99, "Clockwise facade topology must agree with the authored +Z normal")
			front_faces += 1
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		var source := texture.get_image()
		if source.is_compressed():
			assert(source.decompress() == OK)
		var faces: Array[Dictionary] = PROFILES.city_faces() if label == "IndependentCastleHill" else PROFILES.village_faces()
		for index in range(faces.size()):
			var face: Dictionary = faces[index]
			var polygon: PackedVector2Array = face.polygon
			var bounds := Rect2(polygon[0], Vector2.ZERO)
			for p: Vector2 in polygon:
				bounds = bounds.expand(p)
			var count := 0
			var opaque := 0
			for row in range(9):
				for column in range(9):
					var p := bounds.position + bounds.size * Vector2((column + 0.5) / 9.0, (row + 0.5) / 9.0)
					if not Geometry2D.is_point_in_polygon(p, polygon):
						continue
					assert(p.x >= 0 and p.y >= 0 and p.x < source.get_width() and p.y < source.get_height())
					opaque += int(source.get_pixel(int(p.x), int(p.y)).a > 0.90)
					count += 1
			assert(count >= 20)
			var ratio := float(opaque) / count
			minimum_opaque = minf(minimum_opaque, ratio)
			if ratio <= 0.90:
				invalid_regions.append("%s/%d %.3f" % [label, index, ratio])
			samples += count
			assert(is_equal_approx(face.normal.length(), 1.0))
	assert(invalid_regions.is_empty(), "Measured architecture regions leave the opaque artwork: " + str(invalid_regions))
	scene.CITY_BUILDER.audit(scene)
	scene.VILLAGE_BUILDER.audit(scene)
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	assert(front_faces == 9750)
	weather.set_process(false)
	weather.set_motion(false)
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(is_equal_approx(weather.settlement_bounce.light_energy, 0.70))
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.settlement_bounce.light_energy == 0.0)
	print("MEADOW_ARCHITECTURE_AUDIT: PASS; 9750 correct clockwise facade triangles; 64 inspected source planes; %d opaque-registration samples, minimum %.3f; %d exact v71 meshes; 52 window masks and 2 rotor pivots; %d protected playfield probes" % [samples, minimum_opaque, preserved, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
