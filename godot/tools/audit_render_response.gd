extends RefCounted
## Optional real-GPU Web probe (?render_audit=1); no scene or asset mutation.
## Compare a neutral screen-copy pass against its actual rendered input.

static func run(scene: Node3D) -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(96, 64)
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.add_child(viewport)
	var environment_node := WorldEnvironment.new()
	var environment: Environment = scene.get_node("WorldEnvironment").environment.duplicate()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.sky = null
	environment.fog_enabled = false
	environment_node.environment = environment
	viewport.add_child(environment_node)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 2.0
	camera.position.z = 3.0
	viewport.add_child(camera)
	var card := MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(3.0, 2.0)
	card.mesh = quad
	var ramp := ShaderMaterial.new()
	ramp.shader = Shader.new()
	ramp.shader.code = "shader_type spatial; render_mode unshaded, fog_disabled; void fragment() { float g = 0.08 + floor(UV.x * 8.0) * 0.11; ALBEDO = vec3(g); }"
	card.material_override = ramp
	viewport.add_child(card)
	var screen := MeshInstance3D.new()
	screen.mesh = quad
	screen.position.z = -0.5
	screen.extra_cull_margin = 1000.0
	var material := ShaderMaterial.new()
	material.shader = load("res://shaders/meadow_focus.gdshader")
	material.set_shader_parameter("enabled", false)
	screen.material_override = material
	camera.add_child(screen)
	var results: Array[Dictionary] = []
	var passed := true
	for exposure: float in [1.0, 2.0, 2.2]:
		environment.tonemap_exposure = exposure
		environment.tonemap_agx_contrast = 1.30 if exposure > 2.1 else 1.45
		environment.adjustment_saturation = 0.80 if exposure > 2.1 else 1.0
		screen.visible = false
		await _settle()
		var reference: Image = viewport.get_texture().get_image()
		for compensation: float in [0.1, 1.0, exposure]:
			material.set_shader_parameter("scene_exposure", compensation)
			screen.visible = true
			await _settle()
			var copied: Image = viewport.get_texture().get_image()
			var max_error := 0.0
			var values: Array[Vector2] = []
			for i in range(8):
				var x := 6 + i * 12
				var before := reference.get_pixel(x, 32).r
				var after := copied.get_pixel(x, 32).r
				max_error = maxf(max_error, absf(before - after))
				values.append(Vector2(before, after))
			results.append({"exposure": exposure, "compensation": compensation, "max_error": max_error, "samples": str(values)})
			if is_equal_approx(compensation, 0.1):
				passed = passed and max_error > 0.20 # Canary: screen pass must really render.
			elif is_equal_approx(compensation, exposure):
				passed = passed and max_error <= 2.0 / 255.0
	print("MEADOW_RENDER_RESPONSE: " + JSON.stringify(results))
	if passed:
		print("MEADOW_RENDER_RESPONSE_AUDIT: PASS; actual focus shader; 8 gray levels / 3 exposures; <=2 display code values; canary active")
	else:
		push_error("MEADOW_RENDER_RESPONSE_AUDIT: FAIL; screen pass changes exposure or gray ramp is not being drawn")
	viewport.queue_free()

static func _settle() -> void:
	for frame in range(5):
		await RenderingServer.frame_post_draw
