extends "audit_progressive_v135.gd"
## Read-only actual core plus isolated reference resources; no chunk application.

func _ray_compare(original: TriangleMesh, from_shape: TriangleMesh, faces: PackedVector3Array) -> Dictionary:
	var origins := PackedVector3Array([
		Vector3(-7.333333, 80, 3.75), Vector3(-12.833333, 80, -16.625), Vector3(12.75, 80, -8),
		Vector3(-40.06073, 80, -19.3212), Vector3(-33.20683, 80, -22.57353), Vector3(-26.01611, 80, -25.69632),
		Vector3(-67.666252, 80, -168.8), Vector3(-108.04164, 80, -168.8), Vector3(-0.673382, 80, -253.8)])
	var step: int = maxi(1, faces.size() / 3 / 256)
	for triangle in range(0, faces.size() / 3, step):
		var i: int = triangle * 3
		var centre: Vector3 = (faces[i] + faces[i + 1] + faces[i + 2]) / 3.0
		origins.append(Vector3(centre.x, maxf(80.0, centre.y + 10.0), centre.z))
	var result := {"rays": origins.size(), "hits": 0, "hitMissDifferences": 0,
		"positionDifferences": 0, "normalDifferences": 0, "faceIndexDifferences": 0,
		"maxPositionDistance": 0.0, "maxNormalDistance": 0.0}
	for origin: Vector3 in origins:
		var a: Dictionary = original.intersect_ray(origin, Vector3.DOWN)
		var b: Dictionary = from_shape.intersect_ray(origin, Vector3.DOWN)
		if a.is_empty() != b.is_empty():
			result.hitMissDifferences += 1
			continue
		if a.is_empty():
			continue
		result.hits += 1
		result.positionDifferences += int(a.position != b.position)
		result.normalDifferences += int(a.normal != b.normal)
		result.faceIndexDifferences += int(a.face_index != b.face_index)
		result.maxPositionDistance = maxf(result.maxPositionDistance, Vector3(a.position).distance_to(b.position))
		result.maxNormalDistance = maxf(result.maxNormalDistance, Vector3(a.normal).distance_to(b.normal))
	return result

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		quit(2)
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	output_path = str(request.out).replace("\\", "/")
	if not output_path.begins_with(AUDIT_SCOPE) or FileAccess.file_exists(output_path):
		quit(2)
		return
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	scene = packed.instantiate() as Node3D
	_check(scene.get_script() != null, "Actual main script parsed")
	scene.set("audit_complete", true)
	root.add_child(scene)
	current_scene = scene
	weather = scene.get_node("LivingWeather")
	wildlife = scene.get_node("LivingWildlife")
	weather.set_process(false)
	wildlife.set_process(false)
	var originals := {}
	var holders: Array[Node] = []
	for ref: Dictionary in request.expected.referenceScenes:
		if ref.resource not in ["assets/baked/v77/terrain.scn", "assets/baked/v77/detail.scn"]:
			continue
		_check(FileAccess.get_sha256(ref.file) == ref.sha256, "Pinned complete original scene")
		var full := ResourceLoader.load(ref.file, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		var holder := full.instantiate()
		holders.append(holder)
		var name: String = "ContinuousMeadow" if ref.resource.ends_with("terrain.scn") else "SolidLimestoneGeology"
		originals[name] = holder.get_node(NodePath(name))
	var full_rows := {}
	for name: String in originals:
		var full: MeshInstance3D = originals[name]
		var faces: PackedVector3Array = full.mesh.get_faces()
		full_rows[name] = {"faceVertices": faces.size(), "facesSha256": _sha(faces.to_byte_array()),
			"surfaceCount": full.mesh.get_surface_count(), "localTransform": _json(full.transform)}
	var collider_rows: Array = []
	for collider: CollisionShape3D in scene.find_children("*", "CollisionShape3D", true, false):
		_check(collider.shape is ConcavePolygonShape3D, "Expected pinned concave shape")
		var faces: PackedVector3Array = collider.shape.get_faces()
		var data := faces.to_byte_array()
		var row := {"path": _stable_path(collider), "shapeId": str(collider.shape.get_instance_id()),
			"faceVertices": faces.size(), "facesSha256": _sha(data), "disabled": collider.disabled,
			"globalTransform": _json(collider.global_transform), "matchesCompleteMeshes": []}
		for name: String in originals:
			var full: MeshInstance3D = originals[name]
			var full_faces: PackedVector3Array = full.mesh.get_faces()
			if data != full_faces.to_byte_array():
				continue
			var current: MeshInstance3D = scene.get_node(NodePath(name))
			var same_space := collider.global_transform == current.global_transform and current.global_transform == scene.global_transform
			var rebuilt := TriangleMesh.new()
			_check(rebuilt.create_from_faces(faces), "Stock TriangleMesh.create_from_faces accepts full collider faces")
			var rays := _ray_compare(full.mesh.generate_triangle_mesh(), rebuilt, full_faces)
			row.matchesCompleteMeshes.append({"mesh": name, "rawFaceBytesExactlyEqual": true,
				"sameSceneLocalCoordinates": same_space,
				"rebuiltFacesExactlyEqual": rebuilt.get_faces().to_byte_array() == full_faces.to_byte_array(),
				"rebuiltFacesSha256": _sha(rebuilt.get_faces().to_byte_array()), "rayComparison": rays})
			_check(same_space, "No transform adapter required for existing support-query coordinates")
		collider_rows.append(row)
	_check(collider_rows.size() == 5, "Exactly five actual core colliders observed")
	var report := {"schema": "progressive-core-full-collider-correspondence-v1",
		"status": "PASS_CPU_STRUCTURAL_ONLY" if errors.is_empty() else "FAIL", "errors": errors,
		"corePack": request.corePack, "fullReferenceMeshes": full_rows, "colliders": collider_rows,
		"sceneInstantiatedFromActualCorePack": true, "chunksApplied": 0,
		"limitations": ["Exact face-byte equality is separate from TriangleMesh cached face-normal equality.",
			"Bounded ray sample is not proof for every possible query. No runtime substitution or rendered visual test."]}
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	file.close()
	for holder: Node in holders:
		holder.free()
	scene.free()
	quit(0 if errors.is_empty() else 1)
