extends "E:/Projects/Godot-Octopath2/artifacts/startup-v135/support/candidate-01/audit-integrated06.gd"
## One real candidate08 native process; reuse every existing structural check.
## The observer runs AFTER production weather and progressive processing.

class LightingObserver extends Node:
	var audit: SceneTree
	func _process(_delta: float) -> void:
		audit.call("_lighting_tick")

var lighting_rows: Array = []
var lighting_ticks := 0
var real_weather_ticks := 0
var real_nightward_ticks := 0
var real_dayward_ticks := 0
var lighting_observer: Node
var lighting_probe_phase := "normal"
var previous_lights: Dictionary

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	previous_lights = JSON.parse_string(FileAccess.get_file_as_string(spec.lightingBaseline)).lightPhases
	lighting_observer = LightingObserver.new()
	lighting_observer.name = "IndependentLightingObserver"
	lighting_observer.audit = self
	lighting_observer.process_priority = 101
	root.add_child(lighting_observer)
	await super._run()

func _lighting_state() -> Dictionary:
	var environment: Environment = scene.get_node("WorldEnvironment").environment
	return {"phase": lighting_probe_phase, "applied": controller.applied_count,
		"completed": controller.completed, "nightBlend": weather.night_blend,
		"nightTarget": weather.night_target, "transitioning": weather.transitioning,
		"keyShadow": scene.get_node("KeyLight").shadow_enabled,
		"lampShadow": weather.lantern_light.shadow_enabled,
		"lampEnergy": weather.lantern_light.light_energy,
		"ssao": environment.ssao_enabled, "glow": environment.glow_enabled,
		"weatherProcessing": weather.is_processing(), "controllerProcessing": controller.is_processing(),
		"weatherPriority": weather.process_priority, "controllerPriority": controller.process_priority}

func _assert_lighting(row: Dictionary) -> void:
	if row.completed:
		_check(row.keyShadow and row.ssao and row.glow, "Original key shadow / SSAO / glow restored")
		_check(row.lampShadow == (float(row.nightBlend) > 0.40), "Final lamp shadow follows current night blend")
		_check(not row.controllerProcessing, "Temporary lighting enforcer stops after completion")
	else:
		_check(not row.keyShadow and not row.lampShadow and not row.ssao and not row.glow,
			"Real pending frame has no temporary key/lamp shadow or SSAO/glow")
		_check(row.controllerProcessing and int(row.controllerPriority) > int(row.weatherPriority),
			"Production enforcer is scheduled after weather")

func _lighting_tick() -> void:
	if not is_instance_valid(controller) or not is_instance_valid(weather):
		return
	var row := _lighting_state()
	_assert_lighting(row)
	lighting_ticks += 1
	if row.weatherProcessing and row.transitioning and not row.completed:
		real_weather_ticks += 1
		if lighting_probe_phase == "real-weather-nightward":
			real_nightward_ticks += 1
		elif lighting_probe_phase == "real-weather-dayward":
			real_dayward_ticks += 1
		# A live bright lamp is retained even though its shadow is deferred.
		_check(float(row.nightBlend) > 0.40 and float(row.lampEnergy) > 0.0,
			"Actual transition has a lit lamp, not a missing-light shortcut")
		lighting_rows.append(row)

func _capture_lighting(label: String) -> void:
	var row := _lighting_state()
	row["label"] = label
	_assert_lighting(row)
	lighting_rows.append(row)
	_record_lights(label)

func _negative_before_first_group() -> void:
	await super._negative_before_first_group()
	_check(controller.manifest.get("deferLighting", false), "Actual mounted manifest enables the candidate08 gate")
	_check(_same_json(controller.deferred_lighting, {"ssao": true, "glow": true, "key_shadow": true}),
		"Actual initial flags captured for exact final restoration")
	# All details remain unmounted while both real weather directions execute.
	# Deliberately seed the transition halfway so the >.40 lamp threshold is exercised.
	weather.call("toggle_time")
	weather.set("transition_elapsed", 1.5)
	lighting_probe_phase = "real-weather-nightward"
	weather.set_process(true)
	await process_frame
	await process_frame
	await process_frame
	weather.set_process(false)
	weather.call("advance_weather", 3.2)
	await process_frame
	await process_frame
	_capture_lighting("pending-full-night")
	_check(is_equal_approx(float(weather.night_blend), 1.0), "Pending night reached endpoint")
	weather.call("toggle_time")
	weather.set("transition_elapsed", 1.5)
	lighting_probe_phase = "real-weather-dayward"
	weather.set_process(true)
	await process_frame
	await process_frame
	await process_frame
	weather.set_process(false)
	weather.call("advance_weather", 3.2)
	await process_frame
	await process_frame
	_capture_lighting("pending-return-day")
	_check(is_equal_approx(float(weather.night_blend), 0.0), "Pending return-day reached endpoint")
	_check(controller.applied_count == 0, "Real transition probe did not pre-apply any detail")
	lighting_probe_phase = "normal"

func _exercise_phase(index: int) -> void:
	await super._exercise_phase(index)
	# SceneTree.process_frame is emitted BEFORE node _process. Crossing another
	# frame observes the controller's previous real tick rather than invoking it.
	await process_frame
	_capture_lighting("before-chunk-%d" % index)

func _record_snapshot(label: String) -> Dictionary:
	var snapshot: Dictionary = super._record_snapshot(label)
	_capture_lighting(label)
	if label in ["core", "final-day", "final-night"]:
		var actual: Array = light_phases[label].lights.duplicate(true)
		var expected: Array = previous_lights[label].lights.duplicate(true)
		if label == "core":
			for rows: Array in [actual, expected]:
				for row: Dictionary in rows:
					row.erase("shadowEnabled")
		_check(_same_json(actual, expected), "All actual light contributions match accepted07 " + label)
	return snapshot

func _finish() -> void:
	_check(lighting_ticks > 0 and real_nightward_ticks > 0 and real_dayward_ticks > 0,
		"Observer saw real scheduled weather/enforcer ticks in both transition directions")
	if is_instance_valid(controller):
		_capture_lighting("final-restoration")
	var file := FileAccess.open(output_path.get_base_dir().path_join("lighting-observations.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"status": "PASS_NATIVE_LIGHTING_RESTORATION" if errors.is_empty() else "FAIL",
		"errors": errors, "rows": lighting_rows, "observedScheduledTicks": lighting_ticks,
		"realWeatherTransitionTicks": real_weather_ticks, "nightwardTicks": real_nightward_ticks,
		"daywardTicks": real_dayward_ticks,
		"limits": ["Headless native, not GL shader compile or visible frame evidence.",
			"Controlled transition checkpoint and paused animation clock are test-only.",
			"Production shadow-enforcer function was never called directly by the probe."]}, "\t", true, true) + "\n")
	file.close()
	if is_instance_valid(lighting_observer):
		lighting_observer.free()
	super._finish()
