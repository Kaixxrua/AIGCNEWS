extends RefCounted
## Mountain-foot woodland: new rooted branch/leaf geometry, never image cards.
const GEOMETRY = preload("res://scripts/meadow_branch_geometry.gd")
const LEAVES = preload("res://shaders/meadow_mountain_woodland.gdshader")
const MAX_CROWNS := 100
const TRIANGLES_PER_CROWN := 172 # Seven twigs * 4 + six closed leaf masses * 24.
const WIND_MARGIN := 0.06
# Unequal overlapping shoulders (x,z,half-width,half-depth), not a horizontal row.
const GUIDES := [Vector4(-201, -294, 30, 15), Vector4(-137, -289, 29, 18),
	Vector4(-66, -296, 22, 12), Vector4(208, -291, 20, 17),
	Vector4(-180, -256, 19, 14), Vector4(-112, -256, 18, 14),
	Vector4(-62, -256, 16, 13), Vector4(196, -260, 15, 13),
	Vector4(-177, -277, 20, 14), Vector4(-97, -276, 18, 12)]
# Four hill groves, four sparse lower fringes, two connecting shoulders.
const COUNTS := [20, 14, 22, 12, 5, 3, 8, 4, 6, 6]
const HEIGHTS := [5.8, 6.2, 5.8, 4.8, 4.0, 3.8, 4.0, 3.5, 4.5, 4.2]

static func build(scene: Node3D) -> void:
	if scene.has_node("MountainFootWoodland"):
		return
	var started := Time.get_ticks_msec()
	var land := scene.get_node("ContinuousMeadow") as MeshInstance3D
	var surface := land.mesh.generate_triangle_mesh()
	var terrain_to_scene := scene.global_transform.affine_inverse() * land.global_transform
	var camera := scene.get_node("Camera3D") as Camera3D
	var building_guards: Array[Dictionary] = []
	for label: String in ["DistantVillage", "IndependentCastleHill"]:
		var card := scene.get_node(NodePath(label)) as MeshInstance3D
		var screen_x := Vector2(INF, -INF)
		var far_depth := -INF
		for corner in range(8):
			var p := card.to_global(card.mesh.get_aabb().get_endpoint(corner))
			var sx := camera.unproject_position(p).x
			screen_x.x = minf(screen_x.x, sx)
			screen_x.y = maxf(screen_x.y, sx)
			far_depth = maxf(far_depth, -camera.to_local(p).z)
		building_guards.append({"screen_x": screen_x, "far_depth": far_depth})
	var geometry := GEOMETRY.new()
	geometry.scene = scene
	geometry.density_override = 0.72
	var roots := PackedVector3Array()
	var ranges := PackedVector2Array()
	var radii := PackedFloat32Array()
	var heights := PackedFloat32Array()
	var guide_ids := PackedInt32Array()
	var counts := PackedInt32Array()
	var lobe_centres := PackedVector3Array()
	var lobe_ranges := PackedVector2Array()
	for group in range(GUIDES.size()):
		var random := RandomNumberGenerator.new()
		random.seed = 980911 + group * 7919
		var guide: Vector4 = GUIDES[group]
		var accepted := 0
		for attempt in range(COUNTS[group] * 14):
			if accepted >= COUNTS[group] or roots.size() >= MAX_CROWNS:
				break
			var angle := random.randf() * TAU
			var radial := sqrt(random.randf())
			var p := Vector2(guide.x + cos(angle) * guide.z * radial,
				guide.y + sin(angle) * guide.w * radial)
			var height: float = HEIGHTS[group] * lerpf(1.0, 0.58, radial) * random.randf_range(0.86, 1.12)
			height *= lerpf(1.0, 0.76, smoothstep(-292.0, -245.0, p.y))
			var radius := random.randf_range(2.2, 3.8) * lerpf(1.0, 0.78, radial)
			radius = minf(radius, height * 0.70 + 0.8)
			var reach := radius * 1.75 + height * 0.08 + WIND_MARGIN
			if absf(p.x) + reach > 264.0 or p.y - reach < -312.0 or p.y + reach > -235.0:
				continue
			if not (p.x + reach <= -24.0 or p.x - reach >= 166.0):
				continue # Match landform sides; leave castle foundations/central valley open.
			# A diagonal open saddle survives even where neighbouring groves overlap.
			var saddle_x := -31.0 + (p.y + 275.0) * 0.22
			if absf(p.x - saddle_x) < reach + 5.5:
				continue
			if scene.distance_to_road(p) < scene.road_half_width(p.y) + reach + 3.0:
				continue
			var crowded := false
			for i in range(roots.size()):
				if p.distance_to(Vector2(roots[i].x, roots[i].z)) < (radius + radii[i]) * 0.72:
					crowded = true
					break
			if crowded:
				continue
			var ray_origin := Vector3(p.x, 160.0, p.y)
			var scene_to_terrain := terrain_to_scene.affine_inverse()
			var hit := surface.intersect_ray(scene_to_terrain * ray_origin,
				(scene_to_terrain.basis * Vector3.DOWN).normalized())
			if hit.is_empty():
				continue
			var normal := (terrain_to_scene.basis.inverse().transposed() * Vector3(hit.normal)).normalized()
			if normal.y < 0.72:
				continue
			var root: Vector3 = terrain_to_scene * Vector3(hit.position) - Vector3.UP * 0.015
			var bounds := AABB(root + Vector3(-reach, -0.1, -reach), Vector3(reach * 2.0, height + 1.5, reach * 2.0))
			if _in_front_of_building(scene, camera, bounds, building_guards):
				continue
			var first: int = geometry.vertices.size()
			# Placement and crown details have separate, stable random streams.
			var detail := RandomNumberGenerator.new()
			detail.seed = 981013 + group * 10007 + attempt * 97
			var parts := _crown(geometry, root, height, radius, detail)
			lobe_centres.append_array(parts.centres)
			lobe_ranges.append_array(parts.ranges)
			assert(geometry.vertices.size() - first == TRIANGLES_PER_CROWN * 3)
			roots.append(root)
			radii.append(radius)
			heights.append(height)
			guide_ids.append(group)
			ranges.append(Vector2(first, geometry.vertices.size() - first))
			accepted += 1
		counts.append(accepted)
	if roots.is_empty():
		push_error("MEADOW_MOUNTAIN_WOODLAND: no supported crowns; inspect placement/terrain")
		return
	assert(geometry.vertices.size() / 3 <= 18000)
	for p: Vector3 in geometry.vertices:
		assert(absf(p.x) + WIND_MARGIN <= 264.0 and p.z - WIND_MARGIN >= -312.0 and p.z + WIND_MARGIN <= -235.0)
		assert(p.x + WIND_MARGIN <= -24.0 or p.x - WIND_MARGIN >= 166.0)
	var material := ShaderMaterial.new()
	material.shader = LEAVES
	# Private, texture-free canopy response: preserve downward/outward normals.
	var instance := MeshInstance3D.new()
	instance.name = "MountainFootWoodland"
	instance.mesh = geometry.mesh()
	instance.material_override = material
	instance.layers = 8
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	instance.extra_cull_margin = WIND_MARGIN
	instance.set_meta("ground_roots", roots)
	instance.set_meta("crown_ranges", ranges) # Unindexed [first vertex, vertex count].
	instance.set_meta("crown_radii", radii)
	instance.set_meta("crown_heights", heights)
	instance.set_meta("guide_ids", guide_ids)
	instance.set_meta("guide_counts", counts)
	instance.set_meta("triangle_budget", 18000)
	instance.set_meta("geometry_revision", "volume-crowns-98-2")
	instance.set_meta("triangles_per_crown", TRIANGLES_PER_CROWN)
	instance.set_meta("lobe_centres", lobe_centres)
	instance.set_meta("lobe_ranges", lobe_ranges) # Six consecutive closed 72-corner masses per crown.
	scene.add_child(instance)
	print("MEADOW_MOUNTAIN_WOODLAND: %d triangle-ray rooted crowns / %d triangles; groups=%s; one branch/leaf batch; build_ms=%d; visual acceptance pending" % [roots.size(), geometry.vertices.size() / 3, str(counts), Time.get_ticks_msec() - started])

static func _in_front_of_building(scene: Node3D, camera: Camera3D, bounds: AABB, building_guards: Array[Dictionary]) -> bool:
	var screen_x := Vector2(INF, -INF)
	var near_depth := INF
	for corner in range(8):
		var p := scene.to_global(bounds.get_endpoint(corner))
		var sx := camera.unproject_position(p).x
		screen_x.x = minf(screen_x.x, sx)
		screen_x.y = maxf(screen_x.y, sx)
		near_depth = minf(near_depth, -camera.to_local(p).z)
	for building: Dictionary in building_guards:
		var span: Vector2 = building.screen_x
		if screen_x.y >= span.x and screen_x.x <= span.y and near_depth <= float(building.far_depth) + 3.0:
			return true
	return false

static func _crown(geometry: RefCounted, root: Vector3, height: float, radius: float, random: RandomNumberGenerator) -> Dictionary:
	var tone := random.randf_range(0.88, 1.04)
	var lean := Vector3(random.randf_range(-0.055, 0.055), 0.0, random.randf_range(-0.055, 0.055)) * height
	var joint := root + Vector3.UP * height * 0.40 + lean * 0.5
	var top := root + Vector3.UP * height * 0.80 + lean
	geometry.twig(root, joint, radius * 0.038, tone * 0.90)
	geometry.twig(joint, top, radius * 0.025, tone * 0.90)
	var phase := random.randf() * TAU
	var centres := PackedVector3Array()
	var sizes := PackedVector3Array()
	var turns := PackedFloat32Array()
	for arm in range(5):
		var tier := 0.32 + arm * 0.085
		var attach := root.lerp(joint, tier / 0.40) if tier <= 0.40 else joint.lerp(top, (tier - 0.40) / 0.40)
		var heading := phase + arm * 2.399963 + random.randf_range(-0.25, 0.25)
		var branch := Vector3(cos(heading), 0.0, sin(heading)) * radius * random.randf_range(0.40, 0.62)
		branch.y = height * random.randf_range(0.07, 0.11)
		var tip := attach + branch
		geometry.twig(attach, tip, radius * 0.018, tone * 0.92)
		centres.append(tip) # The actual branch ends inside its closed leaf mass.
		sizes.append(Vector3(radius * random.randf_range(0.47, 0.65), height * random.randf_range(0.20, 0.25), radius * random.randf_range(0.40, 0.61)))
		turns.append(heading)
	centres.append(top)
	sizes.append(Vector3(radius * 0.46, height * 0.20, radius * 0.48))
	turns.append(phase)
	var ranges := PackedVector2Array()
	for i in range(centres.size()):
		var first: int = geometry.vertices.size()
		_leaf_mass(geometry, centres[i], sizes[i], turns[i], tone * random.randf_range(0.93, 1.04), random)
		ranges.append(Vector2(first, geometry.vertices.size() - first))
	return {"centres": centres, "ranges": ranges}

static func _leaf_mass(geometry: RefCounted, centre: Vector3, radii: Vector3, heading: float, tone: float, random: RandomNumberGenerator) -> void:
	# Two unequal six-point rings plus poles: a solid 24-triangle leafy lobe,
	# not a camera-facing fan. Independently shaped lobes overlap at real branches.
	var turn := Basis(Vector3.UP, heading) * Basis(Vector3.FORWARD, random.randf_range(-0.12, 0.12))
	var points := PackedVector3Array([Vector3(0, -radii.y, 0)])
	var angles := PackedFloat32Array()
	for i in range(6):
		angles.append(float(i) * TAU / 6.0 + random.randf_range(-0.12, 0.12))
	for ring in range(2):
		for i in range(6):
			var angle := angles[i]
			var spread := random.randf_range(0.84, 1.04) if ring == 0 else random.randf_range(0.72, 0.94)
			var y := random.randf_range(-0.48, -0.34) if ring == 0 else random.randf_range(0.36, 0.52)
			points.append(Vector3(cos(angle) * radii.x * spread, y * radii.y, sin(angle) * radii.z * spread))
	points.append(Vector3(radii.x * 0.10, radii.y, -radii.z * 0.08))
	var faces := PackedInt32Array()
	for i in range(6):
		var a := 1 + i
		var b := 1 + (i + 1) % 6
		faces.append_array(PackedInt32Array([0, a, b, a, a + 6, b, b, a + 6, b + 6, 13, b + 6, a + 6]))
	var normals := PackedVector3Array()
	normals.resize(points.size())
	for i in range(0, faces.size(), 3):
		var a := faces[i]
		var b := faces[i + 1]
		var c := faces[i + 2]
		var normal := (points[c] - points[a]).cross(points[b] - points[a])
		if normal.dot((points[a] + points[b] + points[c]) / 3.0) < 0.0:
			faces[i + 1] = c
			faces[i + 2] = b
			normal = -normal
		for corner: int in [a, b, c]:
			normals[corner] += normal
	for index: int in faces:
		var normal := (turn * normals[index]).normalized()
		var p := centre + turn * points[index]
		geometry._vertex(p, normal, tone, 0.0, false)
		# Continuous per-vertex interior/underside occlusion; never a bright top mask.
		geometry.fields[geometry.fields.size() - 1] = Vector2(lerpf(0.66, 1.0, smoothstep(-0.65, 0.75, normal.y)), 0.0)
