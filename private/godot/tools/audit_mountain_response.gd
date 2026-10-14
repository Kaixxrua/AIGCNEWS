extends RefCounted
## Opt-in GPU mechanism test. The fitted orthographic view is NOT scene acceptance.
const SAMPLE_UVS := [Vector2(0.151, 0.405), Vector2(0.209, 0.369), Vector2(0.291, 0.460), Vector2(0.330, 0.466)]

static func run(scene: Node3D) -> void:
	var original: MeshInstance3D = scene.get_node("DistantMountainRidge")
	if not original.mesh is QuadMesh:
		print("MEADOW_MOUNTAIN_RESPONSE: SKIP; v96 flat/profile diagnostic requires QuadMesh; use actual relief geometry audit and day/night visual checks")
		return
	var weather: Node = scene.get_node("LivingWeather")
	if float(weather.get("night_blend")) != 0.0 or weather.get("transitioning"):
		push_error("MEADOW_MOUNTAIN_RESPONSE: requires stable day0; no state modified")
		return
	var viewport := SubViewport.new()
	viewport.size = Vector2i(960, 384)
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.add_child(viewport)
	var world := WorldEnvironment.new()
	var environment: Environment = scene.get_node("WorldEnvironment").environment.duplicate()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.sky = null
	environment.fog_enabled = false
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	environment.ambient_light_energy = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.ssao_enabled = false
	world.environment = environment
	viewport.add_child(world)
	var card := MeshInstance3D.new()
	card.mesh = original.mesh
	card.position = -card.mesh.get_aabb().get_center()
	var material: ShaderMaterial = original.material_override.duplicate()
	material.set_shader_parameter("painted_fill", 0.0)
	card.material_override = material
	viewport.add_child(card)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = card.mesh.get_aabb().size.x / 2.5 * 1.08
	camera.position.z = 12.0
	viewport.add_child(camera)
	var key := DirectionalLight3D.new()
	key.shadow_enabled = false
	key.light_color = Color(1.0, 0.84, 0.62)
	key.light_energy = 1.90
	viewport.add_child(key)
	var positions: Array[Vector2i] = []
	var mesh := card.mesh as QuadMesh
	for uv: Vector2 in SAMPLE_UVS:
		var point := card.position + mesh.center_offset + Vector3((uv.x - 0.5) * mesh.size.x, (0.5 - uv.y) * mesh.size.y, 0)
		positions.append(Vector2i(camera.unproject_position(point)))
	var records: Array[Dictionary] = []
	var passed := true
	# Symmetric azimuths give the unprofiled +Z plane equal incident light.
	# Only normal strength changes inside each pair; colour and fill stay fixed.
	for azimuth: float in [72.0, -72.0]:
		key.rotation_degrees = Vector3(-34, azimuth, 0)
		var pair: Array[PackedFloat32Array] = []
		for strength: float in [0.0, 1.0]:
			material.set_shader_parameter("mountain_normal_strength", strength)
			for frame in range(5):
				await RenderingServer.frame_post_draw
			var rendered := viewport.get_texture().get_image()
			if rendered == null or rendered.is_empty():
				viewport.queue_free()
				push_error("MEADOW_MOUNTAIN_RESPONSE: empty GPU image; private viewport released")
				return
			pair.append(_samples(rendered, positions))
		var changes := PackedFloat32Array()
		for i in range(positions.size()):
			changes.append(pair[1][i] - pair[0][i])
		records.append({"azimuth": azimuth, "flat": str(pair[0]), "profiled": str(pair[1]), "delta": str(changes)})
		# Source-aligned left/right slopes reverse their incremental response.
		var separation := (changes[1] - changes[0]) + (changes[3] - changes[2])
		passed = passed and (separation > 0.015 if azimuth > 0 else separation < -0.015)
	# With fill0 and all incident light removed, neither profile adds light.
	key.light_energy = 0.0
	for frame in range(5):
		await RenderingServer.frame_post_draw
	var black := _samples(viewport.get_texture().get_image(), positions)
	for value: float in black:
		passed = passed and value <= 2.0 / 255.0
	print("MEADOW_MOUNTAIN_RESPONSE: " + JSON.stringify({"viewport": str(viewport.size), "projection": "fitted orthographic", "camera_size": camera.size, "source_uvs": str(SAMPLE_UVS), "sample_pixels": str(positions), "samples_per_roi": 9, "records": records, "zero_light": str(black), "scope": "normal-only; no production fog or appearance acceptance"}))
	viewport.queue_free()
	if passed:
		print("MEADOW_MOUNTAIN_RESPONSE_AUDIT: PASS; opposite slope increments reverse with symmetric lights; zero-fill zero-light stays black")
	else:
		push_error("MEADOW_MOUNTAIN_RESPONSE_AUDIT: FAIL; source-aligned slope response or zero-light protection")

static func _samples(rendered: Image, positions: Array[Vector2i]) -> PackedFloat32Array:
	var values := PackedFloat32Array()
	for pixel: Vector2i in positions:
		var sum := 0.0
		for y in range(-1, 2):
			for x in range(-1, 2):
				var c := rendered.get_pixel(pixel.x + x, pixel.y + y)
				sum += c.r * 0.2126 + c.g * 0.7152 + c.b * 0.0722
		values.append(sum / 9.0)
	return values
