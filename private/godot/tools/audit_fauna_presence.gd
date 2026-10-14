extends SceneTree
## Exercise the real presence controller without waiting for new bitmap assets.

const WILDLIFE = preload("res://scripts/meadow_wildlife.gd")
const WEATHER = preload("res://scripts/meadow_weather.gd")

class PresenceScene extends Node3D:
	var camera: Camera3D

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := PresenceScene.new()
	root.add_child(scene)
	scene.camera = Camera3D.new()
	scene.add_child(scene.camera)
	var wildlife := WILDLIFE.new()
	scene.add_child(wildlife)
	wildlife.set_process(false)
	wildlife.meadow = scene
	# Kept outside the tree: only its public clock/blend state is needed here.
	var weather := WEATHER.new()
	wildlife.weather = weather
	for i in range(4):
		var card := MeshInstance3D.new()
		card.mesh = QuadMesh.new()
		var material := ShaderMaterial.new()
		material.shader = wildlife.ANIMAL_SHADER
		card.material_override = material
		wildlife.add_child(card)
		wildlife.animals.append({"node": card, "night_only": i == 3, "presence": 0.0})
	wildlife.night_light = OmniLight3D.new()
	wildlife.add_child(wildlife.night_light)
	wildlife.night_halo = MeshInstance3D.new()
	wildlife.night_halo.material_override = ShaderMaterial.new()
	wildlife.night_halo.material_override.shader = wildlife.HALO
	wildlife.add_child(wildlife.night_halo)
	wildlife.night_aura = MeshInstance3D.new()
	wildlife.night_aura.material_override = ShaderMaterial.new()
	wildlife.night_aura.material_override.shader = wildlife.SPIRIT_AURA
	wildlife.add_child(wildlife.night_aura)
	var partial := 0
	for step in range(201):
		weather.night_blend = float(step) / 200.0
		wildlife.advance(0.0)
		var day: float = wildlife.animals[0].presence
		var night: float = wildlife.animals[3].presence
		for i in range(3):
			assert(is_equal_approx(wildlife.animals[i].presence, day))
		assert(absf(float(wildlife.night_aura.material_override.get_shader_parameter("visibility")) - night) < 0.000001)
		assert(absf(wildlife.night_light.light_energy - night * 1.15) < 0.000001)
		if day > 0.01 and day < 0.99:
			partial += 1
		if step == 0:
			assert(day == 1.0 and night == 0.0 and not wildlife.night_aura.visible)
		elif step == 200:
			assert(day == 0.0 and night == 1.0 and wildlife.night_aura.visible)
	assert(partial > 50)
	# Halo and real light follow a moving spirit, including a reversed heading.
	var spirit: MeshInstance3D = wildlife.animals[3].node
	spirit.position = Vector3(-3, 2, -8)
	spirit.material_override.set_shader_parameter("sprite_flip", true)
	wildlife.advance(0.0)
	assert(wildlife.night_light.position.is_equal_approx(spirit.position + Vector3.UP * 1.55))
	assert(wildlife.night_aura.position.is_equal_approx(spirit.position + scene.camera.global_basis.y * 1.55 - scene.camera.global_basis.z * 0.06))
	print("MEADOW_FAUNA_PRESENCE_UNIT: PASS; %d partial-alpha samples; paused clock still changes presence; aura and physical light follow the spirit" % partial)
	weather.free()
	scene.queue_free()
	await process_frame
	quit()
