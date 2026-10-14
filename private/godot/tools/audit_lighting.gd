extends SceneTree
## Lighting intent/budget regression; final appearance must be checked in WebGL.
const MAIN = preload("res://scenes/main.tscn")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var weather = scene.get_node("LivingWeather")
	weather.set_process(false)
	weather.set_motion(false)
	var fixed_clock: float = weather.animation_clock
	assert(ProjectSettings.get_setting("rendering/renderer/rendering_method") == "gl_compatibility")
	assert(ProjectSettings.get_setting("rendering/lights_and_shadows/directional_shadow/size") == 4096)
	assert(ProjectSettings.get_setting("rendering/lights_and_shadows/directional_shadow/soft_shadow_filter_quality") == 3)
	assert(weather.key_light.directional_shadow_mode == DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS)
	assert(weather.key_light.directional_shadow_max_distance == 118.0)
	assert(is_equal_approx(weather.key_light.shadow_normal_bias, 1.3))
	assert(weather.key_light.shadow_blur < 1.7 and weather.key_light.shadow_enabled)
	assert(weather.environment.ssao_enabled and is_equal_approx(weather.environment.ssao_radius, 0.52))
	assert(is_equal_approx(weather.environment.ssao_intensity, 1.45))
	assert(is_equal_approx(weather.environment.ambient_light_energy, 0.22))
	assert(is_equal_approx(weather.day_bounce.light_energy, 0.18))
	assert(is_equal_approx(weather.key_light.light_energy, 1.90))
	# Retire the neutral-day B>=0.80 assumption for reference warm sunlight.
	# This is an input contract; 2K review must still reject yellow cast/water shifts.
	assert(weather.key_light.light_color.is_equal_approx(Color(1.0, 0.84, 0.62)))
	assert(weather.key_light.rotation_degrees.is_equal_approx(Vector3(-34, 72, 0)))
	assert(weather.environment.tonemap_mode == Environment.TONE_MAPPER_AGX)
	assert(is_equal_approx(weather.environment.tonemap_agx_white, 8.0))
	assert(is_equal_approx(weather.environment.tonemap_agx_contrast, 1.45))
	assert(is_equal_approx(weather.environment.adjustment_saturation, 1.0))
	assert(weather.environment.adjustment_enabled)
	assert(weather.environment.glow_enabled, "The screen-response contract requires final engine post-tonemapping")
	assert(is_equal_approx(weather.environment.adjustment_brightness, 1.0))
	assert(is_equal_approx(weather.environment.adjustment_contrast, 1.0))
	var day_exposure: float = weather.environment.tonemap_exposure
	assert(is_equal_approx(day_exposure, 2.0))
	assert(is_equal_approx(float(scene.focus_material.get_shader_parameter("scene_exposure")), day_exposure))
	var sky_material: ShaderMaterial = weather.environment.sky.sky_material
	var sun_direction: Vector3 = sky_material.get_shader_parameter("sun_direction")
	var cloud_direction: Vector3 = sky_material.get_shader_parameter("cloud_light_direction")
	assert(sun_direction.dot(weather.key_light.basis.z.normalized()) > 0.999)
	assert(cloud_direction.dot(sun_direction) > 0.999, "Cloud illumination must agree with scene shadows")
	assert(not weather.day_bounce.shadow_enabled and not weather.moon_bounce.shadow_enabled)
	var near_foliage := 0
	var near_opaque_props := 0
	for node in scene.get_children():
		if not node is MeshInstance3D or not node.has_meta("art_foot"):
			continue
		var foot: Vector2 = node.get_meta("art_foot")
		if foot.y < -65.0:
			continue
		var material: ShaderMaterial = node.material_override
		if material.shader.resource_path != "res://shaders/meadow_cutout.gdshader":
			continue
		var fill := float(material.get_shader_parameter("painted_fill"))
		assert(fill <= 0.04, "Near art should receive the scene's actual lighting")
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		if texture.resource_path.contains("/foliage/"):
			assert(is_equal_approx(float(material.get_shader_parameter("leaf_transmission")), 0.10))
			near_foliage += 1
		else:
			assert(float(material.get_shader_parameter("leaf_transmission")) == 0.0)
			near_opaque_props += 1
	assert(near_foliage >= 15 and near_opaque_props >= 3)
	var material_source := FileAccess.get_file_as_string("res://shaders/meadow_cutout.gdshader")
	assert(material_source.contains("diffuse_burley") and not material_source.contains("diffuse_lambert_wrap"))
	for label: String in ["DistantVillage", "IndependentCastleHill"]:
		var distant: MeshInstance3D = scene.get_node(NodePath(label))
		assert(distant.material_override.shader.resource_path == "res://shaders/meadow_architecture_day.gdshader")
		assert(is_equal_approx(float(distant.material_override.get_shader_parameter("painted_fill")), 0.18))
		assert(distant.material_override.get_shader_parameter("architecture_count") == 32)
	assert(not weather.lantern_light.shadow_enabled, "Do not allocate local shadow work in daylight")
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 1.0 and weather.animation_clock == fixed_clock)
	for label: String in ["DistantVillage", "IndependentCastleHill"]:
		assert(scene.get_node(NodePath(label)).material_override.shader.resource_path == "res://shaders/meadow_architecture.gdshader", "Night must restore the original native-fog shader")
	assert(is_equal_approx(weather.key_light.light_energy, 1.20))
	assert(weather.key_light.light_color.is_equal_approx(Color(0.65, 0.79, 1.0)))
	assert(weather.key_light.rotation_degrees.is_equal_approx(Vector3(-28, -145, 0)))
	assert(is_equal_approx(weather.environment.ambient_light_energy, 0.32))
	assert(is_equal_approx(weather.moon_bounce.light_energy, 0.32))
	assert(is_equal_approx(weather.environment.tonemap_exposure, 2.2))
	assert(is_equal_approx(weather.environment.tonemap_agx_contrast, 1.30))
	assert(is_equal_approx(weather.environment.adjustment_saturation, 0.80))
	assert(is_equal_approx(float(scene.focus_material.get_shader_parameter("scene_exposure")), 2.2))
	assert(weather.environment.tonemap_exposure / day_exposure <= 1.11,
		"Keep night readable with light sources, not an arbitrary global exposure jump")
	var moon_direction: Vector3 = sky_material.get_shader_parameter("moon_direction")
	cloud_direction = sky_material.get_shader_parameter("cloud_light_direction")
	assert(moon_direction.dot(weather.key_light.basis.z.normalized()) > 0.999)
	assert(cloud_direction.dot(moon_direction) > 0.999)
	assert(weather.lantern_light.shadow_enabled and weather.lantern_light.shadow_opacity >= 0.8)
	var local_shadows := 0
	for light: OmniLight3D in scene.find_children("*", "OmniLight3D", true, false):
		if light.shadow_enabled:
			local_shadows += 1
	assert(local_shadows == 1, "Only the nearby trail lantern needs local real-time shadows")
	for light: OmniLight3D in weather.source_pools:
		assert(light.light_energy > 2.0 and not light.shadow_enabled)
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 0.0 and not weather.lantern_light.shadow_enabled)
	assert(weather.animation_clock == fixed_clock)
	assert(is_equal_approx(weather.key_light.light_energy, 1.90))
	assert(weather.key_light.light_color.is_equal_approx(Color(1.0, 0.84, 0.62)))
	assert(weather.key_light.rotation_degrees.is_equal_approx(Vector3(-34, 72, 0)))
	assert(is_equal_approx(weather.environment.ambient_light_energy, 0.22))
	assert(is_equal_approx(weather.day_bounce.light_energy, 0.18))
	assert(is_equal_approx(float(scene.focus_material.get_shader_parameter("scene_exposure")), day_exposure))
	# v81 restores day AgX contrast to 1.45 while retaining the warm key colour.
	# Night lighting, exposure compensation and the spatial contract stay fixed.
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	assert(scene.focus_material.get_shader_parameter("far_radius") == 0.0)
	assert(scene.focus_material.get_shader_parameter("near_radius") <= 1.25)
	print("MEADOW_LIGHTING_AUDIT: PASS; v81 day RGB 1.0/0.84/0.62, AgX contrast 1.45; day/night key 1.90/1.20, restored day; AgX highlights with 10%% night exposure lift; matched sun/moon/cloud directions; %d near foliage / %d solid-art props; 1 night-only shadowed lamp; 2 unchanged 4096 shadow cascades; %d protected playfield probes" % [near_foliage, near_opaque_props, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()
