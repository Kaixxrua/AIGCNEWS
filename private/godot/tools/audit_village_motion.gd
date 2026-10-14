extends SceneTree
## Exercise the actual rotor node transforms through the shared weather clock.

const MAIN = preload("res://scenes/main.tscn")
const VILLAGE = preload("res://scripts/meadow_village_builder.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var meadow := MAIN.instantiate()
	root.add_child(meadow)
	await physics_frame
	await physics_frame
	var weather: Node = meadow.get_node("LivingWeather")
	weather.set_process(false)
	await process_frame
	await process_frame
	var village: Node3D = meadow.get_node("DistantVillage")
	var body_transform := village.global_transform
	var rotors := [meadow.get_node("VillageRotor_0"), meadow.get_node("VillageRotor_1")]
	var first := [rotors[0].transform, rotors[1].transform]
	var start_clock: float = weather.animation_clock
	weather.advance_weather(0.125)
	weather.advance_weather(0.125)
	await process_frame
	await process_frame
	for i in range(2):
		var rotor: MeshInstance3D = rotors[i]
		assert(not rotor.transform.is_equal_approx(first[i]), "Each windmill rotor must visibly rotate")
		assert(rotor.position == first[i].origin, "Rotation must not orbit or drift from the axle")
		var expected := Basis(Vector3.BACK, VILLAGE.PHASES[i] + VILLAGE.SPEEDS[i] * weather.animation_clock)
		assert(rotor.basis.is_equal_approx(expected), "Rotor transform must consume the current shared clock")
	weather.set_motion(false)
	var frozen := [rotors[0].transform, rotors[1].transform]
	var frozen_clock: float = weather.animation_clock
	weather.advance_weather(0.25)
	await process_frame
	await process_frame
	for i in range(2):
		assert(rotors[i].transform == frozen[i], "Pause must freeze both real rotor transforms")
	weather.toggle_time()
	weather.advance_weather(3.2)
	await process_frame
	await process_frame
	assert(weather.night_blend == 1.0 and weather.animation_clock == frozen_clock,
		"Day/night must work while rotors are paused")
	for i in range(2):
		assert(rotors[i].transform == frozen[i], "Day/night must not restart a rotor phase")
	weather.set_motion(true)
	weather.advance_weather(0.25)
	await process_frame
	await process_frame
	for i in range(2):
		var rotor: MeshInstance3D = rotors[i]
		var expected := Basis(Vector3.BACK, VILLAGE.PHASES[i] + VILLAGE.SPEEDS[i] * weather.animation_clock)
		assert(rotor.basis.is_equal_approx(expected), "Resume must continue from the paused phase")
		assert(rotor.position == first[i].origin, "Rotor centre must remain attached after resume")
	assert(village.global_transform == body_transform, "Village masonry must stay static")
	assert(is_equal_approx(weather.animation_clock, start_clock + 0.5), "Only two active intervals should advance")
	VILLAGE.audit(meadow)
	print("MEADOW_VILLAGE_MOTION_AUDIT: PASS; two unique rigid rotors; shared clock; fixed pivots; pause/night/resume; static buildings")
	meadow.queue_free()
	await process_frame
	quit()
