extends SceneTree
## v70 actual geometry/camera preservation. This cannot certify art fidelity.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var geology: MeshInstance3D = scene.get_node("SolidLimestoneGeology")
	var previous: Node3D = load("res://assets/baked/v69/detail.scn").instantiate()
	var old_geology: MeshInstance3D = previous.get_node("SolidLimestoneGeology")
	var a := old_geology.mesh.get_faces()
	var b := geology.mesh.get_faces()
	var left_end: int = geology.get_meta("left_terrace_face_vertices")
	assert(a.size() == b.size() and left_end > 10000 and left_end < b.size())
	var changed := 0
	var displacement := 0.0
	for i in range(b.size()):
		if i >= left_end:
			assert(a[i] == b[i], "Rim, river stones and hero rocks must retain exact face vertices")
		elif a[i] != b[i]:
			changed += 1
			displacement = maxf(displacement, a[i].distance_to(b[i]))
	assert(changed > 15000 and displacement > 0.25 and displacement < 2.0)
	# Indexed arrays change when local normal sharing changes. Expand the
	# attributes to original face order before checking the unaffected suffix.
	var aa := old_geology.mesh.surface_get_arrays(0)
	var bb := geology.mesh.surface_get_arrays(0)
	var ai: PackedInt32Array = aa[Mesh.ARRAY_INDEX]
	var bi: PackedInt32Array = bb[Mesh.ARRAY_INDEX]
	for i in range(left_end, b.size()):
		for attribute in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
			assert(aa[attribute][ai[i]] == bb[attribute][bi[i]], "Unrelated rock attributes changed")
	var rock_shape := geology.mesh.generate_triangle_mesh()
	var land_shape: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var camera: Camera3D = scene.get_node("Camera3D")
	var view_size := camera.get_viewport().get_visible_rect().size
	var visible_changes := 0
	var screen_delta := 0.0
	for i in range(0, left_end, 18):
		var before := (a[i] + a[i + 1] + a[i + 2]) / 3.0
		var after := (b[i] + b[i + 1] + b[i + 2]) / 3.0
		if before.distance_to(after) < 0.035 or camera.is_position_behind(after):
			continue
		var screen := camera.unproject_position(after) / view_size
		if screen.x < 0.015 or screen.x > 0.985 or screen.y < 0.05 or screen.y > 0.92:
			continue
		var ray := (after - camera.global_position).normalized()
		var stone_hit := rock_shape.intersect_ray(camera.global_position, ray)
		if stone_hit.is_empty() or stone_hit.position.distance_to(after) > 0.025:
			continue
		var land_hit := land_shape.intersect_ray(camera.global_position, ray)
		if not land_hit.is_empty() and camera.global_position.distance_to(land_hit.position) < camera.global_position.distance_to(after) - 0.04:
			continue
		var delta := screen.distance_to(camera.unproject_position(before) / view_size)
		if delta > 0.0008:
			visible_changes += 1
			screen_delta = maxf(screen_delta, delta)
	assert(visible_changes > 30, "Geometry changes must reach actual camera-visible cliff surfaces, not buried mesh")
	# Root geometry may replant on new cliff planes, but the three main
	# unaffected meshes must remain identical (also covered by massing audit).
	var old_metrics: Dictionary = old_geology.get_meta("builder_metrics")
	var metrics: Dictionary = geology.get_meta("builder_metrics")
	for key: String in ["stones", "walls", "bedded", "bank_stones", "face_domains"]:
		assert(old_metrics[key] == metrics[key])
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_CLIFF_PLANES_AUDIT: PASS; %d changed left-face vertices, max %.4fm; %d exact unaffected rock face vertices/attributes; %d terrain/rock-visible changes, max normalized screen shift %.5f; same rock triangles/counts; %d protected playfield probes" % [changed, displacement, b.size() - left_end, visible_changes, screen_delta, protection.safe_probes])
	previous.free()
	scene.queue_free()
	await process_frame
	quit()
