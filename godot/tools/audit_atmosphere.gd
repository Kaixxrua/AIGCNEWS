extends SceneTree
## Parameter/anchor regression only; Web screenshots remain the visual test.

const MAIN = preload("res://scenes/main.tscn")
const SETTLEMENT = preload("res://scripts/meadow_settlement_lights.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var focus: ShaderMaterial = scene.focus_material
	assert(float(focus.get_shader_parameter("near_radius")) <= 3.0, "Foreground must not dissolve into heavy blur")
	assert(float(focus.get_shader_parameter("near_end")) <= 32.0, "Keep the main framing tree outside strong defocus")
	assert(float(focus.get_shader_parameter("far_radius")) <= 0.15, "Do not wash out distant architecture")
	assert(float(focus.get_shader_parameter("far_start")) >= 300.0, "Keep both distant settlements readable")
	var stitches: MeshInstance3D = scene.get_node("PropGroundStitches")
	var roots: PackedVector3Array = stitches.get_meta("root_anchors")
	var max_error := 0.0
	for point: Vector3 in roots:
		var query := PhysicsRayQueryParameters3D.create(point + Vector3.UP * 0.25, point - Vector3.UP * 0.25)
		var hit: Dictionary = scene.get_world_3d().direct_space_state.intersect_ray(query)
		assert(not hit.is_empty(), "Every seam root needs real ground")
		if absf(point.y - hit.position.y) >= 0.016:
			print("SEAM_ROOT_MISMATCH: root %s; hit %s; surface %s" % [point, hit.position, hit.collider.name])
		max_error = maxf(max_error, absf(point.y - hit.position.y))
	assert(max_error < 0.016, "New grass must not float at art feet")
	var sky_material: ShaderMaterial = scene.get_node("WorldEnvironment").environment.sky.sky_material
	assert(sky_material.get_shader_parameter("cloud_centres").size() == 48)
	assert(sky_material.get_shader_parameter("cloud_radii").size() == 48)
	var min_cloud_shift := INF
	var cloud_groups: Dictionary = {}
	var cloud_centres = sky_material.get_shader_parameter("cloud_centres")
	var cloud_radii = sky_material.get_shader_parameter("cloud_radii")
	var min_lobe_width := INF
	var max_lobe_width := 0.0
	for i in range(cloud_centres.size()):
		var cloud: Vector4 = cloud_centres[i]
		# Four-second horizontal angular displacement at 800px render height.
		var shift := cloud.w * 4.0 / absf(cloud.z) * 800.0 / (2.0 * tan(deg_to_rad(48.0) * 0.5))
		min_cloud_shift = minf(min_cloud_shift, shift)
		cloud_groups[cloud.w] = int(cloud_groups.get(cloud.w, 0)) + 1
		var projected_width: float = cloud_radii[i].x * 2.0 / absf(cloud.z) * 800.0 / (2.0 * tan(deg_to_rad(48.0) * 0.5))
		min_lobe_width = minf(min_lobe_width, projected_width)
		max_lobe_width = maxf(max_lobe_width, projected_width)
	assert(min_cloud_shift >= 5.0, "Cloud drift must be legible within a few seconds, not only over minutes")
	assert(cloud_groups.size() == 16, "Keep separated near/far cloud groups, not eight broad uniform strips")
	for count in cloud_groups.values():
		assert(count == 3, "Three unequal billows belong to each drifting group")
	assert(min_lobe_width < 18.0 and max_lobe_width < 115.0, "Preserve both fine distant clouds and restrained near billows")
	print("MEADOW_CLOUD_SCALE_AUDIT: PASS; 16 groups / 48 volumes; individual lobe widths %.2f..%.2f px at 800px view" % [min_lobe_width, max_lobe_width])
	print("MEADOW_CLOUD_DRIFT_AUDIT: 48 volumes; slowest 4s displacement %.2f px at 800px view" % min_cloud_shift)
	print("MEADOW_SEAM_SUPPORT_AUDIT: %d/%d; max error %.4f m" % [roots.size(), roots.size(), max_error])
	for node_name: String in ["DistantVillage", "IndependentCastleHill"]:
		var building: MeshInstance3D = scene.get_node(node_name)
		var view_position: Vector3 = scene.camera.global_transform.affine_inverse() * building.position
		var blur := smoothstep(float(focus.get_shader_parameter("far_start")),
			float(focus.get_shader_parameter("far_end")), -view_position.z) * float(focus.get_shader_parameter("far_radius"))
		assert(blur < 0.15, "Architectural blur must stay subpixel at 1080px render height")
		assert(float(building.material_override.get_shader_parameter("mip_bias")) == -0.45,
			"Retain mipmaps with a modest architecture-only detail bias")
		print("MEADOW_ARCHITECTURE_FOCUS: %s; view depth %.2f m; far blur %.4f px at 1080 render height" % [node_name, -view_position.z, blur])
	SETTLEMENT.audit(scene)
	var water: MeshInstance3D = scene.get_node("ContinuousRiver")
	assert(water.material_override.render_priority > focus.render_priority,
		"Transparent water must survive the focus pass")
	assert(float(water.material_override.get_shader_parameter("shallow_opacity")) < 0.25)
	assert(float(water.material_override.get_shader_parameter("deep_opacity")) < 0.55)
	assert(water.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF)
	var stones: MultiMeshInstance3D = scene.get_node("SubmergedRiverStones")
	assert(stones.multimesh.instance_count == 72)
	var bends: PackedVector2Array = scene.ground_material.get_shader_parameter("river_bends")
	assert(bends == PackedVector2Array(scene.RIVER_BENDS), "Visible bed must follow the actual river")
	print("MEADOW_CLEAR_WATER_AUDIT: transparent after focus; shallow 0.18 / deep 0.46 base opacity; same curved bed")
	var weather = scene.get_node("LivingWeather")
	weather.set_process(false)
	weather.set_motion(false)
	var fixed_clock: float = weather.animation_clock
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 1.0 and weather.animation_clock == fixed_clock)
	assert(is_equal_approx(weather.key_light.light_energy, 1.20)
		and is_equal_approx(weather.environment.ambient_light_energy, 0.32), "Moonlight/fill endpoint must be restored")
	assert(is_equal_approx(weather.moon_bounce.light_energy, 0.32))
	# AgX and ACES have different exposure scales; retain only a 10% night lift,
	# with actual directional/local sources doing the illumination work.
	assert(weather.environment.tonemap_mode == Environment.TONE_MAPPER_AGX)
	assert(is_equal_approx(weather.environment.tonemap_exposure, 2.2))
	assert(weather.source_pools.size() == 7, "Three new lanterns and four window clusters need real light pools")
	for light: OmniLight3D in weather.source_pools:
		assert(light.light_energy > 2.0 and light.omni_range <= 12.0)
	assert(weather.environment.fog_density < 0.0008, "Night architecture should not disappear in dense blue fog")
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 0.0 and is_equal_approx(weather.key_light.light_energy, 1.90))
	assert(weather.moon_bounce.light_energy == 0.0)
	for light: OmniLight3D in weather.source_pools:
		assert(light.light_energy == 0.0)
	print("MEADOW_ATMOSPHERE_AUDIT: PASS; readable far focus; 52 fixed window anchors; brighter moonlight; reversible paused day/night")
	scene.queue_free()
	await process_frame
	quit()
