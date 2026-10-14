extends SceneTree
## Geometry/space/material checks for v69. These are not reference-art scores.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var unchanged := 0
	var old_cover: Mesh
	# v75 deliberately remeshes the woody crowns, with separate shape/root tests.
	for group: String in ["terrain", "detail"]:
		var previous: Node3D = load("res://assets/baked/v68/" + group + ".scn").instantiate()
		for old: MeshInstance3D in previous.get_children():
			var current: MeshInstance3D = scene.get_node(NodePath(old.name))
			if old.name == "CreepingMeadowAndLedgeGrowth":
				old_cover = old.mesh
				continue
			# v70 remeshes the left outcrops and replants dependent seam roots.
			# Their unaffected geometry is checked against v69 by the cliff audit.
			if old.name in ["SolidLimestoneGeology", "PropGroundStitches"]:
				continue
			assert(current.transform == old.transform)
			var a := old.mesh.surface_get_arrays(0)
			var b := current.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Massing must not move terrain/rocks/fine grass/prop stitches/foothill: %s/%d" % [old.name, channel])
			unchanged += 1
		previous.free()
	assert(unchanged == 2 and old_cover != null)
	var cover: MeshInstance3D = scene.get_node("CreepingMeadowAndLedgeGrowth")
	var roots: PackedVector3Array = cover.get_meta("ecotone_anchors")
	var links: PackedVector4Array = cover.get_meta("ecotone_links")
	assert(links.size() >= 6)
	var populated := 0
	for link: Vector4 in links:
		var nearby := 0
		for root: Vector3 in roots:
			nearby += int(Vector2(root.x, root.z).distance_to(Vector2(link.x, link.y)) < 1.6)
		populated += int(nearby >= 12)
	assert(populated >= 6, "Connection guides must contain real supported plants, not just metadata")
	var rim_guides: PackedVector4Array = cover.get_meta("foreground_growth_guides")
	assert(rim_guides.size() == 8)
	var planted_rim := 0
	for guide: Vector4 in rim_guides:
		var near_rim := 0
		for p: Vector3 in roots:
			near_rim += int(Vector2(p.x, p.z).distance_to(Vector2(guide.x, guide.y)) < 1.7)
		planted_rim += int(near_rim >= 12)
	assert(planted_rim >= 6, "Foreground framing must contain actual planted leaf geometry")
	var before := _near_leaf_footprint(old_cover)
	var after := _near_leaf_footprint(cover.mesh)
	assert(before.y > 1000 and after.y > 1000)
	assert(after.x / after.y > before.x / before.y * 1.15, "Broad foreground leaves must have a measurably larger actual footprint")
	var before_triangles := old_cover.get_faces().size() / 3
	var after_triangles := cover.mesh.get_faces().size() / 3
	assert(after_triangles < before_triangles * 1.15, "Redistribute a bounded leaf budget rather than hiding the scene under unlimited geometry")
	var leaf_road_margin := INF
	var leaf_arena_margin := INF
	for p: Vector3 in cover.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]:
		var q := Vector2(p.x, p.z)
		leaf_road_margin = minf(leaf_road_margin, scene.distance_to_road(q) - scene.road_half_width(p.z))
		leaf_arena_margin = minf(leaf_arena_margin, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS)
	assert(leaf_road_margin > 0.08 and leaf_arena_margin > 1.0,
		"Whole leaf silhouettes, including tip and wind clearance, must stay outside the path/arena")
	assert(cover.cast_shadow != GeometryInstance3D.SHADOW_CASTING_SETTING_OFF)
	var source := FileAccess.get_file_as_string("res://shaders/meadow_surface.gdshaderinc")
	assert(source.contains("MEADOW_SURFACE_METRES = 13.4"))
	print("MEADOW_MASSING_AUDIT: PASS; %d exact unaffected meshes; %d/%d populated colony links; %d/%d planted foreground pockets; %d supported transition roots; mean near-leaf XZ triangle footprint %.5f -> %.5fm2; %d -> %d cushion triangles; complete-leaf road/arena clearance %.3f/%.3fm" % [
		unchanged, populated, links.size(), planted_rim, rim_guides.size(), roots.size(), before.x / before.y, after.x / after.y, before_triangles, after_triangles, leaf_road_margin, leaf_arena_margin])
	scene.queue_free()
	await process_frame
	quit()

func _near_leaf_footprint(mesh: Mesh) -> Vector2:
	var faces := mesh.get_faces()
	var area := 0.0
	var count := 0
	for i in range(0, faces.size(), 3):
		var middle: Vector3 = (faces[i] + faces[i + 1] + faces[i + 2]) / 3.0
		if middle.x < -33 or middle.x > 20 or middle.z < -9 or middle.z > 14:
			continue
		area += absf((faces[i + 1] - faces[i]).cross(faces[i + 2] - faces[i]).y) * 0.5
		count += 1
	return Vector2(area, count)
