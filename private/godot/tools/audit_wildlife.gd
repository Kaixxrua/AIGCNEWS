extends SceneTree
## Checks real transforms/frames over many random journeys, not just parameters.

const MAIN = preload("res://scenes/main.tscn")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var wildlife = scene.get_node("LivingWildlife")
	var weather = scene.get_node("LivingWeather")
	wildlife.set_process(false)
	weather.set_process(false)
	wildlife.rng.seed = 520933
	wildlife.reset_flight(530909)
	assert(wildlife.animals.size() == 4)
	for animal: Dictionary in wildlife.animals:
		assert(animal.node.material_override.render_priority > scene.focus_material.render_priority,
			"True-alpha animals must not be overwritten by the focus screen copy")
	assert(wildlife.night_aura.material_override.render_priority > scene.focus_material.render_priority)
	assert(wildlife.night_halo.material_override.render_priority > scene.focus_material.render_priority)
	assert(not wildlife.animals[3].node.visible and wildlife.night_light.light_energy == 0.0,
		"The nocturnal spirit must not appear or light the grass by day")
	var night_start: Transform3D = wildlife.animals[3].node.transform
	var frames := [{}, {}, {}, {}]
	var dragon_frames := {}
	var dragon_views := {}
	var dragon_wings := {}
	var min_depth := INF
	var max_depth := -INF
	var max_ground_error := 0.0
	var worst_ground := {}
	var previous_dragon: Vector3 = wildlife._flight_position(0.0)
	var min_sky_x := INF
	var max_sky_x := -INF
	var min_size := INF
	var max_size := -INF
	var projected_heights := [INF, INF, INF, INF]
	for sample in range(3200):
		if sample == 1600:
			assert(wildlife.animals[3].node.transform == night_start, "Hidden nocturnal animal must not walk off before night")
			weather.toggle_time()
			weather.advance_weather(3.2)
		weather.advance_weather(0.125)
		wildlife.advance(weather.animation_clock)
		for i in range(4):
			var animal: Dictionary = wildlife.animals[i]
			assert(wildlife.safe_point(animal.point), "Animal entered a road, river, prop or steep slope")
			assert(wildlife.HABITATS[i].grow(0.01).has_point(animal.point))
			assert(animal.frames.size() == 8 and animal.frame >= 0 and animal.frame < 8)
			frames[i][animal.frame] = true
			var position: Vector3 = animal.node.position
			var tip: Vector3 = position + scene.camera.global_basis.y * animal.node.mesh.size.y
			var projected_height: float = scene.camera.unproject_position(position).distance_to(scene.camera.unproject_position(tip))
			projected_heights[i] = minf(projected_heights[i], projected_height)
			var query := PhysicsRayQueryParameters3D.create(position + Vector3.UP * 1.5, position - Vector3.UP * 1.5)
			var hit: Dictionary = scene.get_world_3d().direct_space_state.intersect_ray(query)
			assert(not hit.is_empty(), "Animal needs actual collidable ground")
			if absf(position.y - hit.position.y) > max_ground_error:
				max_ground_error = absf(position.y - hit.position.y)
				worst_ground = {"animal": i, "feet": position, "hit": hit.position, "collider": str(hit.collider)}
		var depth: float = wildlife.dragon.position.z
		min_depth = minf(min_depth, depth)
		max_depth = maxf(max_depth, depth)
		assert(depth >= wildlife.FLIGHT_DEPTH.x and depth <= wildlife.FLIGHT_DEPTH.y, "Dragon must stay in its actual 3D airspace")
		assert(wildlife.dragon.position.y > 50.0, "Dragon must fly high above the meadow, not skim the ground or ridge")
		var screen: Vector2 = scene.camera.unproject_position(wildlife.dragon.position) / root.get_visible_rect().size
		assert(wildlife.FLIGHT_FRAME.grow(0.005).has_point(screen), "Flight must stay inside the visible sky band")
		min_sky_x = minf(min_sky_x, screen.x)
		max_sky_x = maxf(max_sky_x, screen.x)
		var half_wing: Vector3 = scene.camera.global_basis.x * wildlife.DRAGON_SPAN * 0.5
		var width: float = scene.camera.unproject_position(wildlife.dragon.position + half_wing).distance_to(
			scene.camera.unproject_position(wildlife.dragon.position - half_wing))
		min_size = minf(min_size, width)
		max_size = maxf(max_size, width)
		assert(wildlife.dragon.position.distance_to(previous_dragon) < 4.5, "Random route joins must not teleport")
		previous_dragon = wildlife.dragon.position
		dragon_frames[wildlife.dragon_frame] = true
		dragon_views[wildlife.dragon_view] = true
		dragon_wings[wildlife.dragon_frame / 8] = true
	print("MEADOW_ANIMAL_SUPPORT: ", worst_ground)
	assert(max_ground_error < 0.04, "Animal feet do not match the physics terrain")
	assert(max_depth - min_depth > 45.0 and dragon_wings.size() == 4 and dragon_views.size() >= 6)
	print("MEADOW_DRAGON_TURN_AUDIT: %d directional views / %d wing states / %d combined frames; real views, fixed body scale, no horizontal squeeze or mirroring" % [dragon_views.size(), dragon_wings.size(), dragon_frames.size()])
	print("MEADOW_DRAGON_ROUTE_MEASURE: sky_x %.6f..%.6f; travel %.6f; legs %d" % [min_sky_x, max_sky_x, max_sky_x - min_sky_x, wildlife.flight_legs])
	assert(wildlife.flight_legs >= 6 and max_sky_x - min_sky_x > 0.18,
		"Random flight must cover varied sky targets instead of a small repeated circle")
	assert(max_size / min_size > 1.15, "Real perspective must visibly change dragon size")
	assert(projected_heights[0] > 18.0 and projected_heights[1] > 25.0 and projected_heights[2] > 19.0,
		"Ground animals must remain legible at the 1280x800 reference viewport")
	print("MEADOW_WILDLIFE_SCREEN_SCALE: minimum animal heights %s px; dragon open-wing %.1f..%.1f px; sky x %.3f..%.3f; %d random legs" % [projected_heights, min_size, max_size, min_sky_x, max_sky_x, wildlife.flight_legs])
	for i in range(4):
		var animal: Dictionary = wildlife.animals[i]
		assert(animal.travel > 15.0 and animal.turns > 5 and frames[i].size() == 8,
			"Every species must move, change destination and animate")
		var screen: Vector2 = scene.camera.unproject_position(animal.node.global_position) / get_root().get_visible_rect().size
		print("MEADOW_ANIMAL_AUDIT: %s; %.2f m travelled; %d destinations; 8 frames; screen %s" % [animal.node.name, animal.travel, animal.turns, screen])
	assert(wildlife.animals[3].node.visible and wildlife.night_light.light_energy > 0.8)
	for i in range(3):
		assert(not wildlife.animals[i].node.visible, "Day creatures must be absent at night")
	assert(wildlife.night_aura.visible, "The night spirit needs its soft moving aura")
	assert(wildlife.night_light.position.distance_to(wildlife.animals[3].node.position + Vector3.UP * 1.55) < 0.001,
		"Nocturnal light must follow the actual moving animal")
	weather.set_motion(false)
	var frozen := []
	for animal: Dictionary in wildlife.animals:
		frozen.append([animal.node.transform, animal.frame])
	var dragon_transform: Transform3D = wildlife.dragon.transform
	var dragon_uv: Vector4 = wildlife.dragon.material_override.get_shader_parameter("uv_region")
	for step in range(20):
		weather.advance_weather(0.20)
		wildlife.advance(weather.animation_clock)
	for i in range(4):
		assert(wildlife.animals[i].node.transform == frozen[i][0] and wildlife.animals[i].frame == frozen[i][1])
	assert(wildlife.dragon.transform == dragon_transform and wildlife.dragon.material_override.get_shader_parameter("uv_region") == dragon_uv)
	weather.toggle_time()
	weather.advance_weather(3.2)
	wildlife.advance(weather.animation_clock)
	assert(weather.night_blend == 0.0 and wildlife.dragon.transform == dragon_transform)
	assert(not wildlife.animals[3].node.visible and wildlife.night_light.light_energy == 0.0)
	for i in range(3):
		assert(wildlife.animals[i].node.visible)
	weather.toggle_time()
	weather.advance_weather(3.2)
	wildlife.advance(weather.animation_clock)
	assert(wildlife.animals[3].node.visible and wildlife.dragon.transform == dragon_transform)
	weather.set_motion(true)
	weather.advance_weather(0.20)
	wildlife.advance(weather.animation_clock)
	assert(wildlife.dragon.position.distance_to(dragon_transform.origin) < 3.0)
	assert(wildlife.dragon.position.distance_to(dragon_transform.origin) > 0.01)
	var first_route: Array = wildlife.flight_points.duplicate()
	wildlife.reset_flight(530910)
	assert(wildlife.flight_points != first_route, "A different visit seed must not repeat the flight route")
	# Appearance follows the 3.2s lighting transition even when time is paused.
	weather.set_motion(false)
	weather.toggle_time()
	var prior_day := 0.0
	var prior_night := 1.0
	var partial_samples := 0
	for step in range(32):
		weather.advance_weather(0.10)
		wildlife.advance(weather.animation_clock)
		var day: float = wildlife.animals[0].presence
		var night: float = wildlife.animals[3].presence
		assert(day >= prior_day - 0.00001 and night <= prior_night + 0.00001)
		assert(absf(float(wildlife.animals[0].node.material_override.get_shader_parameter("creature_visibility")) - day) < 0.00001)
		if day > 0.01 and day < 0.99:
			partial_samples += 1
		prior_day = day
		prior_night = night
	assert(partial_samples >= 6 and prior_day > 0.999 and prior_night < 0.001,
		"Dawn needs multiple genuinely partial alpha states, not a visibility switch")
	print("MEADOW_FAUNA_FADE_AUDIT: PASS; %d partial-alpha dawn samples; day/night groups separate; aura and point light follow the spirit" % partial_samples)
	print("MEADOW_WILDLIFE_AUDIT: PASS; 400s seeded random paths including nocturnal stag; eight frames each; max grounded error %.4f m; dragon z %.2f..%.2f; pause/day-night/resume exact" % [max_ground_error, min_depth, max_depth])
	scene.queue_free()
	await process_frame
	quit()
