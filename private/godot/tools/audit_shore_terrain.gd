extends SceneTree

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var result: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	var stone: Texture2D = scene.ground_material.get_shader_parameter("bank_limestone_texture")
	assert(stone.resource_path == "res://assets/materials/riverbank-limestone-v68.png")
	var stone_image := stone.get_image()
	assert(stone_image.get_width() >= 1024 and stone_image.get_height() >= 1024)
	assert(stone_image.detect_alpha() == Image.ALPHA_NONE, "This is a full-bleed opaque material, not a cutout")
	assert(stone_image.has_mipmaps(), "Bank material needs mipmaps at the actual distant viewing scale")
	print("MEADOW_SHORE_TERRAIN_AUDIT: PASS; %d changed same-XZ shore probes, max height %.3fm; %d dry terrain-visible bank changes, max normalized displacement %.4f; %d unrelated vertices exact; %d protected road/arena probes, error %.5fm" % [
		result.changed, result.maximum_change, result.visible_changes, result.screen_delta, result.unchanged, result.safe_probes, result.safe_error])
	scene.queue_free()
	await process_frame
	quit()
