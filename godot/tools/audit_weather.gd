extends SceneTree
## Deterministic transition/clock regression test. Does not write project assets.

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
	assert(weather.night_blend == 0.0 and not weather.transitioning)
	_verify_settlement_fill(scene, 0.0)
	var terrain_position: Vector3 = scene.get_node("MeadowColony_00").position
	var initial_clock: float = weather.animation_clock
	weather.advance_weather(0.125)
	weather.advance_weather(0.125)
	assert(is_equal_approx(weather.animation_clock, initial_clock + 0.25), "Environment clock must advance")
	weather.set_motion(false)
	var frozen_clock: float = weather.animation_clock
	weather.advance_weather(1.0)
	assert(weather.animation_clock == frozen_clock, "Pause must freeze all environment shader clocks")
	weather.toggle_time()
	weather.advance_weather(0.8)
	var partial: float = weather.night_blend
	assert(partial > 0.0 and partial < 1.0, "Day/night must interpolate")
	_verify_settlement_fill(scene, partial)
	weather.toggle_time()
	assert(weather.night_blend == partial, "Rapid reversal must not jump to an endpoint")
	_verify_settlement_fill(scene, partial)
	weather.advance_weather(0.8)
	var reversing: float = weather.night_blend
	assert(reversing > 0.0 and reversing < partial, "Reversal must fade from the current value")
	_verify_settlement_fill(scene, reversing)
	weather.advance_weather(2.4) # Keep the original 3.2-second reversal deadline.
	assert(weather.night_blend == 0.0 and not weather.transitioning, "Reversal must finish at day")
	_verify_settlement_fill(scene, 0.0)
	assert(is_equal_approx(weather.key_light.light_energy, 1.90), "Day lighting must be exactly restored")
	assert(weather.lantern_light.light_energy == 0.0, "Day lamp must be off")
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 1.0 and not weather.transitioning, "Night endpoint must finish")
	_verify_settlement_fill(scene, 1.0)
	assert(is_equal_approx(weather.key_light.light_energy, 1.20), "Night must use directional moonlight")
	assert(weather.environment.ambient_light_energy <= 0.50 and weather.moon_bounce.light_energy > 0.25,
		"Use directional moon fill and visible sources, not excessive uniform ambient light")
	assert(weather.lantern_light.light_energy > 2.4, "Night lamp must illuminate its surroundings")
	assert(weather.animation_clock == frozen_clock, "Day/night must still work with animation paused")
	assert(weather.probe.update_mode == ReflectionProbe.UPDATE_ONCE, "Never recapture all reflection faces every frame")
	assert(weather.probe.position.distance_to(weather.probe_origin) <= 0.0011, "Reflection refresh must not accumulate drift")
	assert(scene.get_node("MeadowColony_00").position == terrain_position, "Animation must not move root anchors")
	weather.reduced_motion = true
	weather.toggle_time()
	assert(weather.night_blend == 0.0 and not weather.transitioning, "Reduced motion must skip transition animation")
	_verify_settlement_fill(scene, 0.0)
	weather.set_motion(true)
	weather.advance_weather(0.1)
	assert(is_equal_approx(weather.animation_clock, frozen_clock + 0.1), "Resume must continue from frozen phase")
	weather.set_reduced_motion(false)
	weather.toggle_time()
	weather.advance_weather(0.5)
	weather.set_reduced_motion(true)
	assert(weather.night_blend == 1.0 and not weather.transitioning and not weather.motion_enabled,
		"Enabling reduced motion mid-transition must settle at the requested endpoint")
	_verify_settlement_fill(scene, 1.0)
	weather.set_motion(true)
	assert(not weather.reduced_motion, "Explicit Play must restore transitions as well as the environment clock")
	weather.toggle_time()
	weather.advance_weather(0.7)
	assert(weather.transitioning and weather.night_blend > 0.0 and weather.night_blend < 1.0,
		"Day/night must genuinely fade after manually overriding reduced motion")
	_verify_settlement_fill(scene, weather.night_blend)
	weather.set_motion(false)
	weather.advance_weather(3.2)
	assert(weather.night_blend == 0.0 and not weather.transitioning,
		"A manual pause freezes creatures but must not disable their time-of-day fade")
	_verify_settlement_fill(scene, 0.0)
	print("MEADOW_WEATHER_AUDIT: PASS; 4 settlement materials fill 0.18/0.26 at startup, partial/reversed blend and restored endpoints; moving clock, pause/resume, smooth transition, rapid reversal, day/night endpoints, reduced motion, fixed roots, once-only reflection")
	scene.queue_free()
	await process_frame
	quit()

func _verify_settlement_fill(scene: Node3D, blend: float) -> void:
	# Independent acceptance endpoints; inspect actual materials, not the controller's list/constants.
	var expected := lerpf(0.18, 0.26, blend)
	for label: String in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		var art: MeshInstance3D = scene.get_node(NodePath(label))
		var material: ShaderMaterial = art.material_override
		assert(material != null)
		assert(is_equal_approx(float(material.get_shader_parameter("painted_fill")), expected),
			"Settlement painted fill must follow the shared reversible blend: %s at %.6f" % [label, blend])
