extends SceneTree

func _initialize() -> void:
	var scene: Node3D = load("res://assets/baked/v58/detail.scn").instantiate()
	for node: MeshInstance3D in scene.get_children():
		var before: Mesh = node.mesh
		var source: Array = before.surface_get_arrays(0)
		var surface := SurfaceTool.new()
		surface.create_from(before, 0)
		surface.index()
		var indexed := surface.commit()
		var after := indexed.surface_get_arrays(0)
		var indices: PackedInt32Array = after[Mesh.ARRAY_INDEX]
		var errors := {}
		for attribute in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
			if source[attribute] == null:
				continue
			var maximum := 0.0
			for sample in range(0, indices.size(), 139):
				var a = source[attribute][sample]
				var b = after[attribute][indices[sample]]
				if a is Color:
					maximum = maxf(maximum, maxf(maxf(absf(a.r-b.r), absf(a.g-b.g)), maxf(absf(a.b-b.b), absf(a.a-b.a))))
				else:
					maximum = maxf(maximum, a.distance_to(b))
			errors[attribute] = maximum
		print("MEADOW_INDEX_PRECISION: ", node.name, " ", errors, " vertices ", before.surface_get_array_len(0), " -> ", indexed.surface_get_array_len(0), " triangles_identical=", before.get_faces() == indexed.get_faces())
	scene.free()
	quit()
