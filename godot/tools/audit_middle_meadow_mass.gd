extends SceneTree
## v77: independent render-mesh measurements against the frozen v76 world.
## Root metadata registers samples; it is never accepted as proof of leaf mass.
const BASELINE := "res://assets/baked/v76/"
const WORLD_GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"]}
const ROOT_COUNT := 1204
const GUIDE_COUNT := 14
const LEAVES_PER_ROOT := 12 # Frozen six-triangle slots; current slots each hold three leaflets.
const WOOD_TRIANGLES_PER_ROOT := 8
const TRIANGLES_PER_LEAF := 6
const TRIANGLES_PER_ROOT := WOOD_TRIANGLES_PER_ROOT + LEAVES_PER_ROOT * TRIANGLES_PER_LEAF
const WIND_AMPLITUDE := 0.055
const WIND_Z_SCALE := 0.4
const RESERVED_ROOT_RADIUS := 1.9
const LEAF_RADIUS_LIMIT := 1.82
const ATTACHMENT_TOLERANCE := 0.001 # Actual leaf-to-wood surface distance, not a shape target.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var world := _verify_world(scene)
	var old_group := _baseline("brush")
	assert(old_group.get_child_count() == 1)
	var before := old_group.get_node("MiddleMeadowBrush") as MeshInstance3D
	var current := scene.get_node("MiddleMeadowBrush") as MeshInstance3D
	assert(before.transform == current.transform and current.transform == Transform3D.IDENTITY)
	assert(scene.global_transform == Transform3D.IDENTITY, "Measurements and shader wind bounds use world-space vertices")
	assert(before.cast_shadow == current.cast_shadow and current.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED)
	assert(before.layers == current.layers and current.layers == 8)
	assert(before.get_child_count() == 0 and current.get_child_count() == 0, "Decorative brush must not gain colliders")
	var material := current.material_override as ShaderMaterial
	assert(material != null and material.shader.resource_path == "res://shaders/meadow_leaves.gdshader")
	assert(material.get_shader_parameter("middle_scrub") == true)
	_verify_shader_wind(material.shader)
	var old_data := _render_data(before.mesh as ArrayMesh)
	var new_data := _render_data(current.mesh as ArrayMesh)
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var rocks: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var registration := _verify_roots(scene, before, current, old_data, new_data, land, rocks)
	var stems := _verify_stems(old_data, new_data, registration)
	var old_leaves := _measure_leaves(old_data, registration, false)
	var new_leaves := _measure_leaves(new_data, registration, true)
	_verify_crown(old_leaves, new_leaves, new_data, stems)
	var clearance := _verify_clearance(scene, new_data)
	var coverage := _verify_coverage(old_leaves.faces, new_leaves.faces, registration.guides, land, rocks)
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	assert(protection.safe_probes == 1373, "Retain all established playfield probes")
	print("MEADOW_MIDDLE_MEADOW_MASS_AUDIT: PASS; %d exact v76 world meshes / %d unchanged collision shapes; 1204 exact root registrations in 14 unchanged guides, patches %s; actual basal error %.6fm; 12 three-leaf clusters / 36 two-triangle leaflets per root, 14448 clusters / 43344 leaflets / 96320 triangles; connected current stems/leaf attachments and exact random colours; DIAGNOSTIC leaf XZ area %.3f -> %.3fm2, mean slot tip-rise/span %.4f -> %.4f, unoccluded top-down leaf coverage %d -> %d / %d; measured root radius %.4fm; whole-vertex wind-reserved road/Boss/river/habitat margins %.4f/%.4f/%.4f/%.4fm; 1373 protected playfield probes; geometry/safety only, visual crown acceptance remains separate" % [
		world.x, world.y, registration.counts, registration.root_error, old_leaves.area, new_leaves.area,
		old_leaves.mean_slope, new_leaves.mean_slope, coverage.x, coverage.y, GUIDE_COUNT * 40 * 24,
		new_leaves.maximum_radius, clearance.x, clearance.y, clearance.z, clearance.w])
	old_group.free()
	scene.queue_free()
	await process_frame
	quit()

func _baseline(group: String) -> Node3D:
	var packed := load(BASELINE + group + ".scn") as PackedScene
	assert(packed != null, "The frozen v76 cache is required: " + group)
	var container := packed.instantiate() as Node3D
	assert(container.get_meta("cache_version", "") == "meadow-76-1")
	return container

func _verify_world(scene: Node3D) -> Vector2i:
	var checked := Vector2i.ZERO
	for group: String in WORLD_GROUPS:
		var old := _baseline(group)
		assert(old.get_child_count() == WORLD_GROUPS[group].size())
		for label: String in WORLD_GROUPS[group]:
			var before := old.get_node(NodePath(label)) as MeshInstance3D
			var current := scene.get_node(NodePath(label)) as MeshInstance3D
			assert(before != null and current != null)
			assert(before.transform == current.transform and before.cast_shadow == current.cast_shadow,
				"Middle massing changed a protected transform/shadow mode: " + label)
			assert(before.layers == current.layers)
			var old_mesh := before.mesh as ArrayMesh
			var new_mesh := current.mesh as ArrayMesh
			assert(old_mesh != null and new_mesh != null and old_mesh.get_surface_count() == new_mesh.get_surface_count())
			for surface in range(old_mesh.get_surface_count()):
				assert(old_mesh.surface_get_primitive_type(surface) == new_mesh.surface_get_primitive_type(surface))
				var a := old_mesh.surface_get_arrays(surface)
				var b := new_mesh.surface_get_arrays(surface)
				for channel in range(Mesh.ARRAY_MAX):
					assert(a[channel] == b[channel], "Only MiddleMeadowBrush may change: %s/surface %d/channel %d" % [label, surface, channel])
			checked.x += 1
			checked.y += _verify_collision_tree(before, current)
		old.free()
	assert(checked == Vector2i(8, 3))
	return checked

func _verify_collision_tree(before: Node, current: Node) -> int:
	assert(before.get_class() == current.get_class() and before.get_child_count() == current.get_child_count())
	if before is Node3D:
		assert(before.transform == current.transform)
	if before is CollisionObject3D:
		assert(before.collision_layer == current.collision_layer and before.collision_mask == current.collision_mask)
	var shapes := 0
	if before is CollisionShape3D:
		assert(before.disabled == current.disabled)
		var old_shape := before.shape as ConcavePolygonShape3D
		var new_shape := current.shape as ConcavePolygonShape3D
		assert(old_shape != null and new_shape != null,
			"Frozen terrain/stone collision must remain a triangle mesh")
		assert(old_shape.get_faces() == new_shape.get_faces())
		assert(old_shape.backface_collision == new_shape.backface_collision)
		shapes += 1
	for child: Node in before.get_children():
		var counterpart := current.get_node_or_null(NodePath(str(child.name)))
		assert(counterpart != null, "A frozen collision child disappeared: " + str(child.name))
		shapes += _verify_collision_tree(child, counterpart)
	return shapes

func _render_data(mesh: ArrayMesh) -> Dictionary:
	assert(mesh != null and mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES)
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var fields: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	var indices := PackedInt32Array()
	if arrays[Mesh.ARRAY_INDEX] != null:
		indices = arrays[Mesh.ARRAY_INDEX]
	assert(vertices.size() == normals.size() and vertices.size() == colours.size())
	assert(vertices.size() == uv.size() and vertices.size() == fields.size())
	var corners := vertices.size() if indices.is_empty() else indices.size()
	assert(corners == ROOT_COUNT * TRIANGLES_PER_ROOT * 3,
		"Keep exactly 1204 stems, 14448 six-triangle leaf slots and 96320 total triangles")
	for index: int in indices:
		assert(index >= 0 and index < vertices.size())
	return {"vertices": vertices, "normals": normals, "colours": colours,
		"uv": uv, "fields": fields, "indices": indices, "corners": corners}

func _corner_index(data: Dictionary, corner: int) -> int:
	var indices: PackedInt32Array = data.indices
	return corner if indices.is_empty() else indices[corner]

func _corner(data: Dictionary, corner: int) -> Vector3:
	return data.vertices[_corner_index(data, corner)]

func _verify_roots(scene: Node3D, before: MeshInstance3D, current: MeshInstance3D,
		old_data: Dictionary, new_data: Dictionary, land: TriangleMesh, rocks: TriangleMesh) -> Dictionary:
	for key: String in ["roots", "root_faces", "patches", "edge_distances", "growth_guides"]:
		assert(before.has_meta(key) and current.has_meta(key))
		assert(before.get_meta(key) == current.get_meta(key), "Frozen root/guide/RNG registration changed: " + key)
	var roots: PackedVector3Array = before.get_meta("roots")
	var faces: PackedInt32Array = before.get_meta("root_faces")
	var patches: PackedInt32Array = before.get_meta("patches")
	var guides: PackedVector4Array = before.get_meta("growth_guides")
	assert(roots.size() == ROOT_COUNT and faces.size() == ROOT_COUNT and patches.size() == ROOT_COUNT)
	assert(guides.size() == GUIDE_COUNT and guides == PackedVector4Array(scene.MIDDLE_BRUSH.GUIDES))
	assert(before.get_meta("heights").size() == ROOT_COUNT and before.get_meta("edge_distances").size() == ROOT_COUNT)
	assert(current.get_meta("heights").size() == ROOT_COUNT)
	var counts := PackedInt32Array()
	counts.resize(GUIDE_COUNT)
	var maximum_error := 0.0
	for root_index in range(ROOT_COUNT):
		# Fixed triangle order plus actual wood UV classification below makes a
		# changed root_faces array unable to relabel leaves as proof of support.
		assert(faces[root_index] == root_index * TRIANGLES_PER_ROOT)
		var corner := faces[root_index] * 3
		var old_root := (_corner(old_data, corner) + _corner(old_data, corner + 1)) * 0.5
		var new_root := (_corner(new_data, corner) + _corner(new_data, corner + 1)) * 0.5
		assert(old_root.distance_to(roots[root_index]) < 0.00005 and new_root.distance_to(roots[root_index]) < 0.00005)
		assert(new_root.distance_to(old_root) < 0.00005, "Actual basal twig edge moved")
		assert(patches[root_index] >= 0 and patches[root_index] < GUIDE_COUNT)
		counts[patches[root_index]] += 1
		var highest := -INF
		for surface: TriangleMesh in [land, rocks]:
			var hit := surface.intersect_ray(Vector3(new_root.x, 60.0, new_root.z), Vector3.DOWN)
			if not hit.is_empty():
				highest = maxf(highest, hit.position.y)
		assert(is_finite(highest))
		maximum_error = maxf(maximum_error, absf(new_root.y - highest))
	for count: int in counts:
		assert(count >= 10)
	assert(maximum_error < 0.012, "Retain the existing canopy-brush root support gate")
	return {"roots": roots, "patches": patches, "guides": guides, "counts": counts, "root_error": maximum_error,
		"old_heights": before.get_meta("heights"), "heights": current.get_meta("heights")}

func _verify_stems(before: Dictionary, current: Dictionary, registration: Dictionary) -> PackedVector3Array:
	var joints := PackedVector3Array()
	var scales := Vector2(INF, -INF)
	for root_index in range(ROOT_COUNT):
		var start := root_index * TRIANGLES_PER_ROOT * 3
		var root_position: Vector3 = registration.roots[root_index]
		for corner in range(start, start + WOOD_TRIANGLES_PER_ROOT * 3):
			var old_index := _corner_index(before, corner)
			var new_index := _corner_index(current, corner)
			assert(before.uv[old_index].x < -1800.0 and current.uv[new_index].x < -1800.0)
			for channel: String in ["colours", "uv"]:
				assert(before[channel][old_index] == current[channel][new_index],
					"Changed stem shape must retain original random pigment and wood UVs: " + channel)
			assert(current.colours[new_index].a == 0.0)
			var offset: Vector3 = current.vertices[new_index] - root_position
			assert(Vector2(offset.x, offset.z).length() < RESERVED_ROOT_RADIUS)
		for corner in range(start, start + WOOD_TRIANGLES_PER_ROOT * 3, 3):
			var a := _corner(current, corner)
			var cross := (_corner(current, corner + 1) - a).cross(_corner(current, corner + 2) - a)
			var normal: Vector3 = current.normals[_corner_index(current, corner)]
			assert(cross.length_squared() > 0.000000000001 and cross.dot(normal) < 0.0)
		# Read the two current twig segments from their rendered crossing ribbons.
		var previous := root_position
		joints.append(root_position)
		for segment in range(2):
			var first := start + segment * 12
			var a := (_corner(current, first) + _corner(current, first + 1)) * 0.5
			var b := _corner(current, first + 2)
			assert(a.distance_to(previous) < 0.00005 and b.y > a.y, "Actual stem segments must join and rise from the supported base")
			for ribbon in range(0, 12, 6):
				var edge := first + ribbon
				assert(((_corner(current, edge) + _corner(current, edge + 1)) * 0.5).distance_to(a) < 0.00005)
				assert(_corner(current, edge + 2) == b and _corner(current, edge + 3) == b)
				assert(_corner(current, edge + 4) == _corner(current, edge + 1))
			joints.append(b)
			previous = b
		var old_height: float = _corner(before, start + 14).y - root_position.y
		var height := previous.y - root_position.y
		assert(old_height > 0.0 and absf(old_height - registration.old_heights[root_index]) < 0.0001)
		assert(absf(height - registration.heights[root_index]) < 0.0001, "Height metadata must describe the actual stem")
		assert(height >= old_height * 0.76 - 0.0001 and height <= minf(old_height * 1.95, 2.35) + 0.0001,
			"Measured stem growth must stay within the authorized modulation and 2.35m cap")
		scales.x = minf(scales.x, height / old_height)
		scales.y = maxf(scales.y, height / old_height)
	print("MIDDLE_MEADOW_STEM_SUPPORT: 1204 rooted two-segment stems; measured height ratios %.4f..%.4f; wood colours/UV/wind preserved" % [scales.x, scales.y])
	return joints

func _measure_leaves(data: Dictionary, registration: Dictionary, clustered: bool) -> Dictionary:
	var faces := PackedVector3Array()
	var origins := PackedVector3Array()
	var origin_colours := PackedColorArray()
	var ridge_colours := PackedColorArray()
	var spans := PackedFloat32Array()
	var slopes := PackedFloat32Array()
	var patch_areas := PackedFloat64Array()
	patch_areas.resize(GUIDE_COUNT)
	var total_area := 0.0
	var slope_sum := 0.0
	var maximum_radius := 0.0
	var crown_depths := PackedFloat32Array()
	for root_index in range(ROOT_COUNT):
		var root_position: Vector3 = registration.roots[root_index]
		var first := (root_index * TRIANGLES_PER_ROOT + WOOD_TRIANGLES_PER_ROOT) * 3
		var vertical := Vector2(INF, -INF)
		for leaf in range(LEAVES_PER_ROOT):
			var start := first + leaf * TRIANGLES_PER_LEAF * 3
			var origin := Vector3.ZERO
			var base_colour := Color.BLACK
			var ridge_colour := Color.BLACK
			var attachments := 0
			var ridges := 0
			for corner in range(start, start + TRIANGLES_PER_LEAF * 3):
				var index := _corner_index(data, corner)
				var p: Vector3 = data.vertices[index]
				var colour: Color = data.colours[index]
				assert(data.uv[index].x >= -1800.0, "Every one of the twelve leaf slots must contain real leaf triangles")
				faces.append(p)
				vertical.x = minf(vertical.x, p.y)
				vertical.y = maxf(vertical.y, p.y)
				maximum_radius = maxf(maximum_radius, Vector2(p.x - root_position.x, p.z - root_position.z).length())
				# Wind-zero attachments and wind-one folds (v76) / tips (current)
				# come from actual attributes, never generated proof metadata.
				if colour.a == 0.0:
					if attachments > 0:
						assert(p == origin and colour == base_colour)
					origin = p
					base_colour = colour
					attachments += 1
				if colour.a == 1.0:
					if ridges > 0:
						assert(colour == ridge_colour)
					ridge_colour = colour
					ridges += 1
			assert(attachments == (6 if clustered else 2) and ridges == 6,
				"A frozen leaf has two attachment corners; a current three-leaf cluster has six")
			if clustered:
				_verify_leaflet_pairs(data, start, origin)
			# Keep one independently measured maximum span/slope per frozen slot.
			# All six triangles still contribute to area, coverage and wind clearance.
			var span := 0.0
			var tip := origin
			var area := 0.0
			for corner in range(start, start + TRIANGLES_PER_LEAF * 3, 3):
				var a := _corner(data, corner)
				var b := _corner(data, corner + 1)
				var c := _corner(data, corner + 2)
				var cross := (b - a).cross(c - a)
				var normal: Vector3 = data.normals[_corner_index(data, corner)] + data.normals[_corner_index(data, corner + 1)] + data.normals[_corner_index(data, corner + 2)]
				assert(cross.length_squared() > 0.000000000001 and cross.dot(normal) < 0.0,
					"Visible, nondegenerate clockwise leaf faces must retain matching light normals")
				area += absf(cross.y) * 0.5
				for p: Vector3 in [a, b, c]:
					var reach := Vector2(p.x - origin.x, p.z - origin.z).length()
					if reach > span:
						span = reach
						tip = p
			assert(span > 0.01 and tip.y > origin.y and area > 0.0)
			var slope := (tip.y - origin.y) / span
			origins.append(origin)
			origin_colours.append(base_colour)
			ridge_colours.append(ridge_colour)
			spans.append(span)
			slopes.append(slope)
			total_area += area
			slope_sum += slope
			patch_areas[registration.patches[root_index]] += area
		crown_depths.append(vertical.y - vertical.x)
	assert(origins.size() == ROOT_COUNT * LEAVES_PER_ROOT)
	return {"faces": faces, "origins": origins, "origin_colours": origin_colours,
		"ridge_colours": ridge_colours, "spans": spans, "slopes": slopes, "area": total_area,
		"mean_slope": slope_sum / origins.size(), "patch_areas": patch_areas, "maximum_radius": maximum_radius,
		"crown_depths": crown_depths}

func _verify_leaflet_pairs(data: Dictionary, start: int, origin: Vector3) -> void:
	var tips := PackedVector3Array()
	for leaflet in range(3):
		var pair_tips := PackedVector3Array()
		var shoulders := PackedVector3Array()
		for triangle in range(2):
			var attachments := 0
			var tip_corners := 0
			var first := start + leaflet * 6 + triangle * 3
			for corner in range(first, first + 3):
				var index := _corner_index(data, corner)
				var p: Vector3 = data.vertices[index]
				var wind: float = data.colours[index].a
				if wind == 0.0:
					assert(p == origin, "Every leaflet triangle must share its cluster's current static attachment")
					attachments += 1
				elif wind == 1.0:
					pair_tips.append(p)
					tip_corners += 1
				else:
					assert(wind > 0.0 and wind < 1.0)
					shoulders.append(p)
			assert(attachments == 1 and tip_corners == 1,
				"Each of the two leaflet triangles needs one attachment, one tip and one shoulder")
		assert(pair_tips.size() == 2 and pair_tips[0] == pair_tips[1] and shoulders.size() == 2,
			"A two-triangle leaflet must share its actual origin-tip ridge, not two unrelated tips")
		var tip: Vector3 = pair_tips[0]
		var axis := Vector2(tip.x - origin.x, tip.z - origin.z)
		var span := axis.length()
		assert(span > 0.01 and tip.y > origin.y)
		var left := Vector2(shoulders[0].x - origin.x, shoulders[0].z - origin.z)
		var right := Vector2(shoulders[1].x - origin.x, shoulders[1].z - origin.z)
		assert(axis.cross(left) * axis.cross(right) < 0.0,
			"Leaflet shoulders must lie on opposite sides; duplicate/overlapping half-faces are not a diamond")
		for side: Vector2 in [left, right]:
			assert(side.dot(axis) > 0.0 and side.dot(axis) < span * span
				and absf(axis.cross(side)) / span < span * 0.5,
				"Both narrow shoulders must lie between the common attachment and pointed tip")
		var midpoint: Vector3 = (shoulders[0] + shoulders[1]) * 0.5
		var along := ((left + right) * 0.5).dot(axis) / (span * span)
		assert(midpoint.y < lerpf(origin.y, tip.y, along), "The diamond must fold below its origin-tip ridge")
		tips.append(tip)
		if leaflet > 0:
			var primary := Vector2(tips[0].x - origin.x, tips[0].z - origin.z)
			assert(absf(absf(primary.angle_to(axis)) - 0.75) < 0.001
				and absf(span / primary.length() - (0.83 if leaflet == 1 else 0.68)) < 0.001,
				"Three distinct pointed blades must retain the agreed fan directions and unequal reaches")
			if leaflet == 2:
				var previous := Vector2(tips[1].x - origin.x, tips[1].z - origin.z)
				assert(primary.cross(previous) * primary.cross(axis) < 0.0,
					"The two shorter leaflets must fan to opposite sides, not duplicate one blade")

func _verify_crown(before: Dictionary, current: Dictionary, data: Dictionary,
		stems: PackedVector3Array) -> void:
	assert(before.origin_colours == current.origin_colours and before.ridge_colours == current.ridge_colours,
		"Original random pigment samples must survive the geometry-only leaf change")
	var depth_sum := Vector2.ZERO
	var angle_spread_sum := Vector2.ZERO
	var upper_turn_sum := 0.0
	var maximum_gap := 0.0
	for root_index in range(ROOT_COUNT):
		var start := root_index * LEAVES_PER_ROOT
		var wood_start := root_index * TRIANGLES_PER_ROOT * 3
		var base: Vector3 = stems[root_index * 3]
		var top: Vector3 = stems[root_index * 3 + 2]
		var previous_y := base.y
		var old_angles := Vector2(INF, -INF)
		var angles := Vector2(INF, -INF)
		var lower_angle := 0.0
		var upper_angle := 0.0
		for leaf in range(LEAVES_PER_ROOT):
			var index := start + leaf
			var origin: Vector3 = current.origins[index]
			assert(origin.y > previous_y and origin.y < top.y, "Twelve ordered tiers must attach along the current stem")
			previous_y = origin.y
			var gap := INF
			for corner in range(wood_start, wood_start + WOOD_TRIANGLES_PER_ROOT * 3, 3):
				gap = minf(gap, _distance_to_triangle(origin, _corner(data, corner), _corner(data, corner + 1), _corner(data, corner + 2)))
			maximum_gap = maxf(maximum_gap, gap)
			assert(gap <= ATTACHMENT_TOLERANCE,
				"Leaf attachment leaves the actual current stem: root %d slot %d gap %.6fm" % [root_index, leaf, gap])
			var old_angle: float = atan(before.slopes[index])
			var angle: float = atan(current.slopes[index])
			old_angles = Vector2(minf(old_angles.x, old_angle), maxf(old_angles.y, old_angle))
			angles = Vector2(minf(angles.x, angle), maxf(angles.y, angle))
			if leaf < 4:
				lower_angle += angle * 0.25
			if leaf >= 8:
				upper_angle += angle * 0.25
		assert(current.origins[start + 11].y - current.origins[start].y > (top.y - base.y) * 0.5,
			"The actual crown needs vertically distributed attachments, not one flattened tier")
		assert(upper_angle > lower_angle, "Upper crown leaflets must turn upward relative to the lower tiers")
		depth_sum += Vector2(before.crown_depths[root_index], current.crown_depths[root_index])
		angle_spread_sum += Vector2(old_angles.y - old_angles.x, angles.y - angles.x)
		upper_turn_sum += upper_angle - lower_angle
	for patch in range(GUIDE_COUNT):
		assert(before.patch_areas[patch] > 0.0 and current.patch_areas[patch] > 0.0)
		print("MIDDLE_MEADOW_PATCH_AREA: DIAGNOSTIC; patch %d, %.3f -> %.3fm2" % [patch, before.patch_areas[patch], current.patch_areas[patch]])
	# Shape metrics describe the actual crown, not a target to maximize XZ area.
	print("MIDDLE_MEADOW_CROWN: actual leaf-to-wood gap max %.6fm; mean vertical leaf extent %.3f -> %.3fm; mean per-root angle spread %.2f -> %.2f degrees; upper-minus-lower inclination %.2f degrees; DIAGNOSTIC geometry, not visual acceptance" % [
		maximum_gap, depth_sum.x / ROOT_COUNT, depth_sum.y / ROOT_COUNT,
		rad_to_deg(angle_spread_sum.x / ROOT_COUNT), rad_to_deg(angle_spread_sum.y / ROOT_COUNT), rad_to_deg(upper_turn_sum / ROOT_COUNT)])
	var maximum_wind := Vector2(WIND_AMPLITUDE, WIND_AMPLITUDE * WIND_Z_SCALE).length()
	assert(current.maximum_radius <= LEAF_RADIUS_LIMIT + 0.0001)
	assert(current.maximum_radius + maximum_wind < RESERVED_ROOT_RADIUS,
		"Whole leaves plus maximum shader breeze must stay inside the reserved root field")

func _distance_to_triangle(point: Vector3, a: Vector3, b: Vector3, c: Vector3) -> float:
	var normal := (b - a).cross(c - a)
	var projection := point - normal * ((point - a).dot(normal) / normal.length_squared())
	var inside := true
	var distance := INF
	for edge: Array in [[a, b], [b, c], [c, a]]:
		var first: Vector3 = edge[0]
		var direction: Vector3 = edge[1] - first
		inside = inside and normal.dot(direction.cross(projection - first)) >= 0.0
		var t := clampf((point - first).dot(direction) / direction.length_squared(), 0.0, 1.0)
		distance = minf(distance, point.distance_to(first + direction * t))
	return minf(distance, point.distance_to(projection)) if inside else distance

func _verify_shader_wind(shader: Shader) -> void:
	# Bind the analytic displacement bound to the actual complete vertex stage.
	# Only whitespace is ignored; a later wind change requires a reviewed bound.
	var expected := """void vertex() {
    float phase = VERTEX.x * 0.31 + VERTEX.z * 0.21;
    float breeze = (sin(phase + meadow_clock * 1.4) * 0.70
        + sin(phase * 2.7 - meadow_clock * 2.1) * 0.30) * 0.055;
    VERTEX.x += breeze * COLOR.a * COLOR.a;
    VERTEX.z += breeze * COLOR.a * 0.4;
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz;
    leaf_world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);
}"""
	# Read the bound resource's source; the headless renderer need not retain
	# Shader.code or expose default uniforms through its dummy shader storage.
	var source := FileAccess.get_file_as_string(shader.resource_path)
	var start := source.find("void vertex()")
	var end := source.find("void fragment()", start)
	assert(start >= 0 and end > start)
	var whitespace := RegEx.new()
	assert(whitespace.compile("\\s+") == OK)
	assert(whitespace.sub(source.substr(start, end - start), "", true) == whitespace.sub(expected, "", true),
		"Shader vertex behavior changed; revisit the all-phase wind clearance bound")

func _verify_clearance(scene: Node3D, data: Dictionary) -> Vector4:
	var margins := Vector4(INF, INF, INF, INF)
	var bend_slope := 0.0
	for i in range(scene.RIVER_BENDS.size() - 1):
		var a: Vector2 = scene.RIVER_BENDS[i]
		var b: Vector2 = scene.RIVER_BENDS[i + 1]
		bend_slope = maxf(bend_slope, 1.5 * absf(b.y - a.y) / absf(b.x - a.x))
	# Smoothstep's maximum derivative plus the centre/width sinusoid bounds.
	var river_slope := bend_slope + 0.65 * 0.31 + 1.25 * 0.054 + 0.50 * 0.23
	for index in range(data.vertices.size()):
		var p: Vector3 = data.vertices[index]
		var normal: Vector3 = data.normals[index]
		var field: Vector2 = data.fields[index]
		var alpha: float = data.colours[index].a
		assert(p.is_finite() and normal.is_finite() and absf(normal.length() - 1.0) < 0.001)
		assert(field.is_finite() and field.x >= 0.0 and field.x <= 1.0 and alpha >= 0.0 and alpha <= 1.0)
		if data.uv[index].x < -1800.0:
			assert(alpha == 0.0, "Woody bases must not move with the leaf breeze")
		var q := Vector2(p.x, p.z)
		# |0.7 sin + 0.3 sin| <= 1, for every time and phase, not sampled gusts.
		var wind := Vector2(WIND_AMPLITUDE * alpha * alpha, WIND_AMPLITUDE * alpha * WIND_Z_SCALE)
		var maximum_road_width := maxf(scene.road_half_width(q.y - wind.y), scene.road_half_width(q.y + wind.y))
		margins.x = minf(margins.x, scene.distance_to_road(q) - maximum_road_width - wind.length())
		margins.y = minf(margins.y, q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS - wind.length())
		assert(q.y - wind.y > scene.RIVER_BENDS[-1].x, "Use the continuous authored river-bend domain")
		margins.z = minf(margins.z, absf(q.x - scene.river_center(q.y)) - scene.river_half_width(q.y) - wind.x - river_slope * wind.y)
		for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
			# Signed distance to the axis-aligned expanded habitat, preserving
			# the existing grow(0.35) exclusion even at rectangular corners.
			var dx := maxf(habitat.position.x - q.x, q.x - habitat.end.x) - wind.x
			var dz := maxf(habitat.position.y - q.y, q.y - habitat.end.y) - wind.y
			margins.w = minf(margins.w, maxf(dx, dz))
	assert(margins.x > 0.65 and margins.y > 1.5 and margins.z > 2.2 and margins.w > 0.35,
		"Every actual wood/leaf vertex must retain road, Boss, river and habitat clearance through the full shader breeze: " + str(margins))
	return margins

func _verify_coverage(old_faces: PackedVector3Array, new_faces: PackedVector3Array,
		guides: PackedVector4Array, land: TriangleMesh, rocks: TriangleMesh) -> Vector2i:
	var old_query := TriangleMesh.new()
	var new_query := TriangleMesh.new()
	old_query.create_from_faces(old_faces)
	new_query.create_from_faces(new_faces)
	var counts := Vector2i.ZERO
	var patch := 0
	for guide: Vector4 in guides:
		var patch_counts := Vector2i.ZERO
		# Fixed v76 guide boxes plus the pre-existing 1.9m root reserve. The
		# sampling window cannot grow or shift in response to new proof metadata.
		var bounds := Vector2(guide.z + 2.0, guide.w + 2.0)
		for x in range(40):
			for z in range(24):
				var q := Vector2(guide.x, guide.y) + bounds * (Vector2((x + 0.5) / 40.0, (z + 0.5) / 24.0) * 2.0 - Vector2.ONE)
				var origin := Vector3(q.x, 60.0, q.y)
				var old_hit := old_query.intersect_ray(origin, Vector3.DOWN)
				var new_hit := new_query.intersect_ray(origin, Vector3.DOWN)
				if old_hit.is_empty() and new_hit.is_empty():
					continue
				var soil := -INF
				for surface: TriangleMesh in [land, rocks]:
					var hit := surface.intersect_ray(origin, Vector3.DOWN)
					if not hit.is_empty():
						soil = maxf(soil, hit.position.y)
				assert(is_finite(soil))
				patch_counts.x += int(not old_hit.is_empty() and old_hit.position.y >= soil)
				patch_counts.y += int(not new_hit.is_empty() and new_hit.position.y >= soil)
		assert(patch_counts.x > 0 and patch_counts.y > 0, "Every original guide must retain actual unoccluded leaf coverage")
		print("MIDDLE_MEADOW_PATCH_COVERAGE: DIAGNOSTIC; patch %d, %d -> %d / 960" % [patch, patch_counts.x, patch_counts.y])
		counts += patch_counts
		patch += 1
	assert(counts.x > 0 and counts.y > 0)
	return counts
