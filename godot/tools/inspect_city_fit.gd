extends SceneTree
## Read-only dimensions and source-space registration for settlement art.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	var city: MeshInstance3D = scene.get_node("IndependentCastleHill")
	var texture: Texture2D = city.material_override.get_shader_parameter("asset_texture")
	var arrays: Array = city.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var column := Vector2(-1, -1)
	for i in range(uvs.size() - 1):
		if is_equal_approx(uvs[i].x, uvs[i + 1].x) and uvs[i + 1].y > uvs[i].y and uvs[i + 1].y < 0.35:
			column = Vector2(vertices[i].y - vertices[i + 1].y, uvs[i + 1].y - uvs[i].y)
			break
	assert(column.y > 0)
	var height := column.x / column.y
	var width: float = city.get_meta("art_width")
	var natural := width * texture.get_height() / float(texture.get_width())
	print("CITY_FIT_MEASURE ", JSON.stringify({"texture": texture.resource_path,
		"position": str(city.position), "width_m": width, "drawn_height_m": height,
		"natural_height_m": natural, "vertical_ratio": height / natural,
		"root_columns": city.get_meta("root_uvs").size()}))
	scene.queue_free()
	await process_frame
	quit()
