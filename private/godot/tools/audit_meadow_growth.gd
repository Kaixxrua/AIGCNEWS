extends SceneTree
## Read-only checks for a shared material/geometry field and solid cap planting.

const MAIN = preload("res://scenes/main.tscn")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var arrays: Array = scene.get_node("ContinuousMeadow").mesh.surface_get_arrays(0)
	var positions: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var field: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	assert(field.size() == positions.size(), "Every terrain vertex must carry the shared growth field")
	var max_error := 0.0
	var sparse := 0
	var dense := 0
	for i in range(field.size()):
		var p := Vector2(positions[i].x, positions[i].z)
		max_error = maxf(max_error, absf(field[i].x - scene.growth_density(p)))
		if p.y > -100 and absf(p.x) < 60:
			sparse += int(field[i].x < 0.35)
			dense += int(field[i].x > 0.65)
	assert(max_error < 0.001, "Turf coloration must use the same density as generated grass")
	assert(sparse > 500 and dense > 500, "The playable meadow needs both sparse and dense regions")
	var image := preload("res://assets/materials/meadow-sward-v60.png").get_image()
	assert(image != null and image.get_width() == 1254 and image.get_height() == 1254)
	assert(image.detect_alpha() == Image.ALPHA_NONE, "Ground material must be opaque, not a fake cutout")
	var shared_path := "res://assets/materials/meadow-sward-v60.png"
	for label in ["ContinuousMeadow", "SolidLimestoneGeology", "LivingMeadowUnderstory",
		"CreepingMeadowAndLedgeGrowth", "PropGroundStitches", "CastleFoothillWoodland"]:
		var material: ShaderMaterial = scene.get_node(label).material_override
		var texture: Texture2D = material.get_shader_parameter("meadow_texture")
		assert(texture != null and texture.resource_path == shared_path)
		assert(material.shader.code.contains("meadow_surface.gdshaderinc"))
		assert(material.shader.code.contains("meadow_surface("))
	print("MEADOW_SHARED_SURFACE_AUDIT: 6 meshes; one opaque source, shared world coordinates and metric detail scale")
	var anchors: PackedVector3Array = scene.get_node("CreepingMeadowAndLedgeGrowth").get_meta("cap_anchors")
	assert(anchors.size() > 1000, "Cap support cannot pass vacuously with missing leaf geometry")
	var space: PhysicsDirectSpaceState3D = scene.get_world_3d().direct_space_state
	var supported := 0
	var max_root_error := 0.0
	var failed := 0
	for p in anchors:
		var query := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 0.12, p - Vector3.UP * 0.16)
		var hit := space.intersect_ray(query)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			max_root_error = maxf(max_root_error, error)
			if error <= 0.055:
				supported += 1
			else:
				if failed < 8:
					print("CAP_ROOT_MISMATCH: root %s; hit %s; surface %s" % [p, hit.position, hit.collider.name])
				failed += 1
		else:
			if failed < 8:
				print("CAP_ROOT_MISSING: %s" % p)
			failed += 1
	print("MEADOW_CAP_ROOT_AUDIT: %d/%d; max detected surface error %.5f m" % [supported, anchors.size(), max_root_error])
	assert(supported == anchors.size(), "Every new cap leaf root needs nearby real collision support")
	var creeping: PackedVector3Array = scene.get_node("CreepingMeadowAndLedgeGrowth").get_meta("creeping_anchors")
	assert(creeping.size() > 1000, "The meadow needs actual low ground-cover geometry")
	var creeping_supported := 0
	var creeping_error := 0.0
	for p in creeping:
		var query := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 0.12, p - Vector3.UP * 0.16)
		var hit := space.intersect_ray(query)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			creeping_error = maxf(creeping_error, error)
			if error <= 0.035:
				creeping_supported += 1
			else:
				print("CREEPING_ROOT_MISMATCH: root %s; hit %s; surface %s" % [p, hit.position, hit.collider.name])
		else:
			print("CREEPING_ROOT_MISSING: %s" % p)
	print("MEADOW_CREEPING_ROOT_AUDIT: %d/%d; max error %.5f m" % [creeping_supported, creeping.size(), creeping_error])
	assert(creeping_supported == creeping.size(), "Ground-cover roots must follow actual triangles, not a floating tangent mound")
	# Material/geometry integration: real leaves now receive the same density
	# colour field as soil, with no per-triangle uninitialised UV2 values.
	var leaf_samples := 0
	var field_deviation := 0.0
	for label in ["LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"]:
		var leaves: Array = scene.get_node(label).mesh.surface_get_arrays(0)
		var leaf_positions: PackedVector3Array = leaves[Mesh.ARRAY_VERTEX]
		var leaf_fields: PackedVector2Array = leaves[Mesh.ARRAY_TEX_UV2]
		var leaf_normals: PackedVector3Array = leaves[Mesh.ARRAY_NORMAL]
		assert(leaf_fields.size() == leaf_positions.size() and leaf_fields.size() > 1000)
		for i in range(0, leaf_fields.size(), 313):
			var p := leaf_positions[i]
			var value := leaf_fields[i].x
			assert(is_finite(value) and value >= 0.0 and value <= 1.0)
			assert(leaf_normals[i].is_finite() and absf(leaf_normals[i].length() - 1.0) < 0.002)
			# The field is taken at each leaf root, not at its moving tip.
			field_deviation = maxf(field_deviation, absf(value - scene.growth_density(Vector2(p.x, p.z))))
			leaf_samples += 1
	assert(field_deviation < 0.16, "Leaf-root colour must stay near the underlying terrain field")
	var woodland: MeshInstance3D = scene.get_node("CastleFoothillWoodland")
	var woodland_roots: PackedVector3Array = woodland.get_meta("ground_roots")
	assert(int(woodland.get_meta("crown_count")) > 80 and woodland_roots.size() > 1000)
	assert(woodland.material_override.get_shader_parameter("foothill_scrub") == true)
	assert(woodland.get_meta("field_origin") == scene.ground_material.get_shader_parameter("foothill_origin"))
	var woodland_error := 0.0
	var woodland_supported := 0
	var trail_clearance := INF
	for p in woodland_roots:
		assert(p.z < -170.0, "Foothill scrub must not intrude into local animal/Boss space")
		var query := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 0.2, p - Vector3.UP * 0.2)
		var hit := space.intersect_ray(query)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			woodland_error = maxf(woodland_error, error)
			woodland_supported += int(error < 0.025)
		var point := Vector2(p.x, p.z)
		trail_clearance = minf(trail_clearance, scene.distance_to_road(point) - scene.road_half_width(p.z))
	assert(woodland_supported == woodland_roots.size(), "Every distant crown rim must touch the collision terrain")
	assert(trail_clearance > 0.2, "Keep the distant extension of the trail open too")
	print("MEADOW_FOLIAGE_PALETTE_AUDIT: PASS; %d shared-field leaf samples; root/tip field deviation %.5f" % [leaf_samples, field_deviation])
	print("MEADOW_FOOTHILL_ROOT_AUDIT: PASS; %d/%d supported rim roots; max error %.5f m; path clearance %.2f m" % [woodland_supported, woodland_roots.size(), woodland_error, trail_clearance])
	print("MEADOW_GROWTH_FIELD_AUDIT: PASS; %d vertex samples; error %.7f; %d sparse / %d dense samples; opaque 1254px material" % [field.size(), max_error, sparse, dense])
	scene.queue_free()
	await process_frame
	quit()
