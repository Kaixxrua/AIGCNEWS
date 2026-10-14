extends SceneTree
const MAIN = preload("res://scenes/main.tscn")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	assert(ProjectSettings.get_setting("rendering/anti_aliasing/quality/msaa_3d") == 2)
	assert(scene.focus_material.get_shader_parameter("far_radius") == 0.0)
	assert(scene.focus_material.get_shader_parameter("near_radius") <= 1.25)
	var sun: DirectionalLight3D = scene.get_node("KeyLight")
	print("MEADOW_SHADOW_CONFIG_MEASURE: enabled=%s normal_bias=%.8f depth_bias=%.8f" % [sun.shadow_enabled, sun.shadow_normal_bias, sun.shadow_bias])
	assert(sun.shadow_enabled and is_equal_approx(sun.shadow_normal_bias, 1.3) and sun.shadow_bias <= 0.04)
	print("MEADOW_SHADOW_CONFIG_AUDIT: real shadows retained; verified 1.3 normal bias / low depth bias, no diagnostic disable")
	assert(scene.get_node_or_null("RocksAtBend") == null and scene.get_node_or_null("RiverBoulders") == null)
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var stone: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var roots: PackedVector3Array = scene.get_node("PropGroundStitches").get_meta("bank_roots")
	assert(roots.size() > 200)
	var max_bank_error := 0.0
	for p in roots:
		var height := -INF
		for surface in [land, stone]:
			var hit: Dictionary = surface.intersect_ray(p + Vector3.UP * 0.20, Vector3.DOWN)
			if not hit.is_empty():
				height = maxf(height, hit.position.y)
		assert(is_finite(height))
		max_bank_error = maxf(max_bank_error, absf(p.y - height))
	assert(max_bank_error < 0.012)
	var max_grove_error := 0.0
	for i in range(6):
		var grove: MeshInstance3D = scene.get_node("UniqueWoodlandBelt_%02d" % i)
		var texture: Texture2D = grove.material_override.get_shader_parameter("asset_texture")
		assert(texture.resource_path.ends_with("distant-groves-v57.png"))
		var uv: Vector4 = grove.material_override.get_shader_parameter("uv_region")
		var natural_height: float = float(grove.get_meta("art_width")) * texture.get_height() * uv.w / (texture.get_width() * uv.z)
		assert(absf(natural_height - float(grove.get_meta("art_height"))) < 0.001)
		var anchor: Vector2 = grove.get_meta("art_anchor")
		for column in [4, 8, 12, 16, 20]:
			var p := _plant_point(scene, grove, Vector2(column / 24.0, anchor.y))
			var hit := land.intersect_ray(p + Vector3.UP * 10, Vector3.DOWN)
			assert(not hit.is_empty())
			max_grove_error = maxf(max_grove_error, absf(p.y - hit.position.y))
	var willow: MeshInstance3D = scene.get_node("WillowsAcrossWater")
	var max_willow_error := 0.0
	for u: float in [0.42, 0.74]:
		var p := _plant_point(scene, willow, Vector2(u, 0.98))
		var hit := land.intersect_ray(p + Vector3.UP * 10, Vector3.DOWN)
		assert(not hit.is_empty() and hit.position.y > -0.4)
		assert(absf(p.x - scene.river_center(p.z)) > scene.river_half_width(p.z) + 1.6)
		max_willow_error = maxf(max_willow_error, absf(p.y - hit.position.y))
	print("MEADOW_REPORTED_FIXES_MEASURE: %d bank roots; bank %.4fm; distant grove %.4fm; willow %.4fm" % [roots.size(), max_bank_error, max_grove_error, max_willow_error])
	assert(max_grove_error < 0.25 and max_willow_error < 0.18, "Visible bases need continuous ground support")
	# The new upper-valley bevel cannot spill into the bridge or near bank.
	assert(scene.river_upper_slope(-38.0) == 0.0 and scene.river_upper_slope(-12.0) == 0.0)
	assert(scene.river_upper_slope(-80.0) > 2.7)
	var rock_arrays: Array = scene.get_node("SolidLimestoneGeology").mesh.surface_get_arrays(0)
	var rock_vertices: PackedVector3Array = rock_arrays[Mesh.ARRAY_VERTEX]
	var rock_colors: PackedColorArray = rock_arrays[Mesh.ARRAY_COLOR]
	var rock_growth: PackedVector2Array = rock_arrays[Mesh.ARRAY_TEX_UV2]
	assert(rock_growth.size() == rock_vertices.size())
	var cap_samples := 0
	for i in range(rock_vertices.size()):
		if rock_colors[i].r <= 0.5:
			continue
		var p := rock_vertices[i]
		assert(absf(rock_growth[i].x - scene.growth_density(Vector2(p.x, p.z))) < 0.00001)
		cap_samples += 1
	assert(cap_samples > 200)
	print("MEADOW_SHORE_POLISH_AUDIT: layered terrain banks; %d exact shared-pigment rock-cap samples" % cap_samples)
	var weather = scene.get_node("LivingWeather")
	assert(weather.day_bounce.light_energy > 0.2 and not weather.day_bounce.shadow_enabled)
	print("MEADOW_REPORTED_FIXES_AUDIT: PASS; sharp distance, MSAA cutouts, natural groves, solid near rocks, grounded banks and willow, sky fill")
	scene.queue_free()
	await process_frame
	quit()

func _plant_point(scene: Node3D, card: MeshInstance3D, uv: Vector2) -> Vector3:
	var vertices: PackedVector3Array = card.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	assert(vertices.size() == 225)
	var x := clampf(uv.x * 24.0, 0, 23.999)
	var y := clampf((1.0 - uv.y) * 8.0, 0, 7.999)
	var col := int(x)
	var row := int(y)
	var k := col * 9 + row
	var a := vertices[k].lerp(vertices[k + 1], y - row)
	var b := vertices[k + 9].lerp(vertices[k + 10], y - row)
	return card.position + scene.camera.global_basis * a.lerp(b, x - col)
