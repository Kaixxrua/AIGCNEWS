extends SceneTree
## Physical/registration regressions. These do not certify artistic fidelity.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var city: MeshInstance3D = scene.get_node("IndependentCastleHill")
	var texture: Texture2D = city.material_override.get_shader_parameter("asset_texture")
	assert(texture.resource_path.ends_with("castle-town-v62.png"))
	var source := texture.get_image()
	if source.is_compressed():
		assert(source.decompress() == OK)
	var arrays: Array = city.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var native_height: float = city.get_meta("art_width") * source.get_height() / float(source.get_width())
	var max_distortion := 0.0
	var facade_samples := 0
	for i in range(uv.size() - 1):
		if not is_equal_approx(uv[i].x, uv[i + 1].x) or uv[i + 1].y > 0.35:
			continue
		var dy := uv[i + 1].y - uv[i].y
		if dy <= 0:
			continue
		var actual_height := (vertices[i].y - vertices[i + 1].y) / dy
		max_distortion = maxf(max_distortion, absf(actual_height / native_height - 1.0))
		facade_samples += 1
	assert(facade_samples > 100 and max_distortion < 0.0001, "City facades must retain the uncompressed source aspect")
	# Light rectangles, not only their centres, must lie on actual opaque art.
	var windows: Array = city.get_meta("window_source_pixels")
	var window_samples := 0
	for opening: Vector4 in windows:
		for dy in range(-int(opening.w), int(opening.w) + 1):
			for dx in range(-int(opening.z), int(opening.z) + 1):
				assert(source.get_pixel(int(opening.x) + dx, int(opening.y) + dy).a > 0.90, "A window mask leaked into transparent space")
				window_samples += 1
	assert(windows.size() == 32 and window_samples == 1120)
	var woodland: MeshInstance3D = scene.get_node("CastleFoothillWoodland")
	assert(int(woodland.get_meta("city_seam_crowns", 0)) > 20)
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_CITY_INTEGRATION_AUDIT: PASS; %d uncompressed facade samples, max ratio error %.7f; 1120 opaque window pixels; %d seam crowns; %d unrelated terrain vertices exact" % [facade_samples, max_distortion, woodland.get_meta("city_seam_crowns"), protection.unchanged])
	scene.queue_free()
	await process_frame
	quit()
