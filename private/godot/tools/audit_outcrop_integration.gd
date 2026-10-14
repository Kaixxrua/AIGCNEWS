extends SceneTree
## Verify real erosion openings and preserved play space, not art similarity.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var terrain: MeshInstance3D = scene.get_node("ContinuousMeadow")
	var geology: MeshInstance3D = scene.get_node("SolidLimestoneGeology")
	var land: TriangleMesh = terrain.mesh.generate_triangle_mesh()
	var exposed: PackedVector4Array = geology.get_meta("terrace_faces")
	var gaps := 0
	for shelf in range(3):
		var spec: Vector4 = scene.TERRACE_GULLIES[shelf]
		for angle: float in [spec.x, spec.z]:
			var p: Vector2 = scene.terrace_boundary(shelf, angle)
			var tangent: Vector2 = (scene.terrace_boundary(shelf, angle + 0.003) - scene.terrace_boundary(shelf, angle - 0.003)).normalized()
			var outside := Vector2(tangent.y, -tangent.x)
			var points := PackedVector3Array()
			for offset: float in [-1.5, 0.0, 1.5]:
				var q: Vector2 = p + outside * offset
				var hit: Dictionary = land.intersect_ray(Vector3(q.x, 40, q.y), Vector3.DOWN)
				assert(not hit.is_empty(), "A weathering opening must be actual supported land")
				points.append(hit.position)
			var covered := false
			for face: Vector4 in exposed:
				if int(face.x) == shelf and angle >= face.y and angle <= face.z:
					covered = true
			assert(not covered, "A continuous rock face still closes a planned grass gully")
			var rise := absf(points[0].y - points[2].y)
			print("MEADOW_GULLY_MEASURE: shelf %d angle %.2f; (%.2f, %.2f); 3m rise %.3f; real supported terrain, no cap across gap" % [shelf, angle, p.x, p.y, rise])
			gaps += 1
	assert(gaps == 6)
	# Shore morphology may change the banks; dense road/Boss probes remain
	# protected against the last delivered physical terrain, not just its formula.
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	var safe_points: int = protection.safe_probes
	var max_safe_change: float = protection.safe_error
	for material: ShaderMaterial in [terrain.material_override, geology.material_override]:
		var texture: Texture2D = material.get_shader_parameter("limestone_texture")
		assert(texture.resource_path.ends_with("limestone-fractured-v61.png"))
		assert(material.shader.code.contains("meadow_mineral.gdshaderinc"))
	var source := Image.load_from_file(ProjectSettings.globalize_path("res://assets/materials/limestone-fractured-v61.png"))
	assert(source != null and source.get_width() >= 1024)
	assert(source.detect_alpha() == Image.ALPHA_NONE)
	print("MEADOW_OUTCROP_INTEGRATION_AUDIT: PASS; six real gullies; %d preserved route/arena vertices, max change %.5fm; shared opaque limestone pigment" % [safe_points, max_safe_change])
	scene.queue_free()
	await process_frame
	quit()
