extends "res://scripts/meadow_detail_builder.gd"
## Discontinuous, embedded bedrock, not a second flat bank or an image strip.
## The v68 stepped terrain replaces these small skins inside its edit region.

var block_centres := PackedVector3Array()
var block_sizes := PackedVector3Array()
var block_ranges := PackedVector2Array()
var patch_guides := PackedVector4Array()
var existing_prop_roots := PackedVector3Array()
var bank_surface: TriangleMesh
var bank_relief_probes := PackedVector3Array()
var bank_relief_directions := PackedVector3Array()

func build(scene: Node3D) -> void:
	meadow = scene
	if CACHE.restore(scene, "riverbank"):
		_report()
		return
	random.seed = 670910
	existing_prop_roots = scene.get_node("PropGroundStitches").get_meta("root_anchors")
	var old_cover: MeshInstance3D = scene.get_node("CreepingMeadowAndLedgeGrowth")
	for label: String in ["cap_anchors", "creeping_anchors"]:
		for root: Vector3 in old_cover.get_meta(label):
			var clearance: float = absf(root.x - scene.river_center(root.z)) - scene.river_half_width(root.z)
			if clearance < scene.river_upper_slope(root.z) + 4.0:
				existing_prop_roots.append(root)
	var land_mesh: Mesh = scene.get_node("ContinuousMeadow").mesh
	var land_query := land_mesh.generate_triangle_mesh()
	bank_surface = land_query
	for side: float in [-1.0, 1.0]:
		var z := 19.0 + random.randf_range(-2.0, 2.0)
		while z > -150.0:
			var span := random.randf_range(3.8, 8.6)
			var centre_z := z - span * 0.5
			z -= span + random.randf_range(1.0, 3.9)
			if absf(centre_z - scene.BRIDGE_Z) < span * 0.5 + 4.2:
				continue
			patch_guides.append(Vector4(side, centre_z, span, random.randf_range(0.70, 1.0)))
			var beds := random.randi_range(3, 4)
			for bed in range(beds):
				var along := -span * 0.5 + random.randf_range(0.0, 0.8)
				while along < span * 0.5:
					var length_m := random.randf_range(1.65, 3.35)
					var sample_z := centre_z + along + length_m * 0.5
					along += length_m * random.randf_range(0.72, 1.12)
					if random.randf() < 0.13:
						continue # Broken exposures; keep rooted soil and small coves.
					var fraction := (float(bed) + random.randf_range(0.32, 0.70)) / float(beds)
					var offset := _contour_offset(sample_z, side, fraction)
					var point := _bank_point(sample_z, side, offset)
					var hit := land_query.intersect_ray(Vector3(point.x, 60, point.y), Vector3.DOWN)
					if hit.is_empty() or hit.position.y < -1.42 or hit.normal.y > 0.91:
						continue
					var top: Vector2 = _bank_point(sample_z, side, 1.65 + scene.river_upper_slope(sample_z))
					var rise: float = scene.terrain_height(top.x, top.y) + 1.30
					var size := Vector3(length_m, clampf(rise / beds * random.randf_range(0.85, 1.30), 0.46, 1.0),
						random.randf_range(1.25, 2.35))
					var tangent := (_bank_point(sample_z + 0.08, side, offset) - _bank_point(sample_z - 0.08, side, offset)).normalized()
					var across := Vector2(tangent.y, -tangent.x) * side
					# The middle and back of each block enter real soil. Only its
					# weathered front and irregular ledge project into the water.
					var centre: Vector3 = hit.position - Vector3.UP * size.y * 0.16
					if not _block_is_safe(centre, size, tangent, across):
						continue
					var start := vertices.size()
					_bank_block(centre, size, tangent, across)
					block_centres.append(centre)
					block_sizes.append(size)
					block_ranges.append(Vector2(start, vertices.size()))
	assert(block_centres.size() > 30 and block_centres.size() < 650)
	var rock_material := ShaderMaterial.new()
	rock_material.shader = ROCK_SHADER
	rock_material.set_shader_parameter("limestone_texture", STONE)
	rock_material.set_shader_parameter("escarpment_texture", ESCARPMENTS)
	rock_material.set_shader_parameter("meadow_texture", GRASS)
	var rocks := _publish("EmbeddedRiverbankStrata", rock_material, true)
	rocks.create_trimesh_collision()
	rocks.set_meta("block_centres", block_centres)
	rocks.set_meta("block_sizes", block_sizes)
	rocks.set_meta("block_ranges", block_ranges)
	rocks.set_meta("patch_guides", patch_guides)
	rocks.set_meta("bank_relief_probes", bank_relief_probes)
	rocks.set_meta("bank_relief_directions", bank_relief_directions)
	_clear_arrays()
	random.seed = 670911
	var queries: Array[TriangleMesh] = [land_query, rocks.mesh.generate_triangle_mesh(),
		scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()]
	var roots := _riparian_cover(queries)
	var leaf_material := ShaderMaterial.new()
	leaf_material.shader = LEAF_SHADER
	leaf_material.set_shader_parameter("meadow_texture", GRASS)
	var cover := _publish("RootedRiparianCover", leaf_material, false)
	cover.layers = 8
	cover.set_meta("ground_roots", roots)
	_report()

func _report() -> void:
	var rocks: MeshInstance3D = meadow.get_node("EmbeddedRiverbankStrata")
	var cover: MeshInstance3D = meadow.get_node("RootedRiparianCover")
	print("MEADOW_RIVERBANK_READY: %d embedded layered blocks; %d irregular exposures; %d exact-surface riparian roots; 2 batches" % [
		rocks.get_meta("block_centres").size(), rocks.get_meta("patch_guides").size(), cover.get_meta("ground_roots").size()])

func _bank_point(z: float, side: float, offset: float) -> Vector2:
	return Vector2(meadow.river_center(z) + side * (meadow.river_half_width(z) + meadow.river_bank_offset(z, side) + offset), z)

func _contour_offset(z: float, side: float, fraction: float) -> float:
	var low := -0.48
	var high: float = 1.65 + meadow.river_upper_slope(z)
	var upper := _bank_point(z, side, high)
	var target: float = lerpf(-1.32, meadow.terrain_height(upper.x, z) - 0.22, fraction)
	# Follow height contours, including the much wider upstream shoulder. The
	# old fixed nominal-edge offset missed almost all that exposed bank.
	for step in range(12):
		var middle := (low + high) * 0.5
		var p := _bank_point(z, side, middle)
		if meadow.terrain_height(p.x, z) < target:
			low = middle
		else:
			high = middle
	return (low + high) * 0.5

func _block_is_safe(centre: Vector3, size: Vector3, tangent: Vector2, across: Vector2) -> bool:
	for u: float in [-0.60, 0.0, 0.60]:
		for v: float in [-0.60, 0.0, 0.60]:
			var p := Vector2(centre.x, centre.z) + tangent * size.x * u + across * size.z * v
			# The v67 low-resolution skins bridge across the new concave steps.
			# Use the actual v68 bedrock there, not a floating chord over a gully.
			if meadow.river_shore_strength(p.y) > 0.01:
				return false
			if not _outside_play_space(p, 1.0) or absf(p.y - meadow.BRIDGE_Z) < 4.0:
				return false
	# Retain soil pockets around established art roots (notably the willow).
	# A new bed must not grow through an existing supported trunk/grass seam.
	for root: Vector3 in existing_prop_roots:
		var offset := Vector2(root.x - centre.x, root.z - centre.z)
		if absf(offset.dot(tangent)) < size.x * 0.60 + 0.25 and absf(offset.dot(across)) < size.z * 0.60 + 0.25:
			return false
	return true

func _bank_block(centre: Vector3, size: Vector3, tangent: Vector2, across: Vector2) -> void:
	# The rejected trial used horizontal cuboids and looked like masonry.
	# This volume follows the actual triangulated bank across its whole width;
	# only shallow, world-continuous mineral fractures emerge from the soil.
	var front := PackedVector3Array()
	var backing := PackedVector3Array()
	var outward := PackedVector3Array()
	for row in range(4):
		var v := float(row) / 3.0
		for column in range(6):
			var u := float(column) / 5.0
			var taper := 0.72 + sin(u * PI) * 0.28
			var q := Vector2(centre.x, centre.z) + tangent * (u - 0.5) * size.x + across * (v - 0.5) * size.z * taper
			var hit := bank_surface.intersect_ray(Vector3(q.x, 60, q.y), Vector3.DOWN)
			assert(not hit.is_empty())
			var base: Vector3 = hit.position
			var direction: Vector3 = hit.normal
			var feather := sin(u * PI) * sin(v * PI)
			var relief := (0.40 + _fracture_height(base) * 1.60) * feather - 0.028
			front.append(base + direction * relief)
			backing.append(base - direction * 0.24)
			outward.append(direction)
	var colour := Color(1, random.randf_range(0.94, 1.02), 0.5, 1.0)
	face_domain = -1
	for row in range(3):
		for column in range(5):
			var i := row * 6 + column
			var normal := (outward[i] + outward[i + 6] + outward[i + 1]).normalized()
			var middle := (front[i] + front[i + 6] + front[i + 1]) / 3.0
			_face(front[i], front[i + 6], front[i + 1], middle - normal, colour, Vector3.ONE, 0.10)
			_face(front[i + 1], front[i + 6], front[i + 7], middle - normal, colour, Vector3.ONE, 0.10)
			if row == 1 and column == 2:
				bank_relief_probes.append(middle)
				bank_relief_directions.append(normal)
	# Turf is broken over the exposed rock, never a completely green flat cap.
	for i in range(growth_fields.size() - 90, growth_fields.size()):
		growth_fields[i].y = 0.0
	colour.r = 0.0
	for row in range(3):
		for column in range(5):
			var i := row * 6 + column
			var middle := (backing[i] + backing[i + 6] + backing[i + 1]) / 3.0
			_face(backing[i], backing[i + 6], backing[i + 1], middle + outward[i], colour)
			_face(backing[i + 1], backing[i + 6], backing[i + 7], middle + outward[i], colour)
	var rim := [0, 1, 2, 3, 4, 5, 11, 17, 23, 22, 21, 20, 19, 18, 12, 6]
	for edge in range(rim.size()):
		var a: int = rim[edge]
		var b: int = rim[(edge + 1) % rim.size()]
		var middle := (front[a] + front[b] + backing[a] + backing[b]) * 0.25
		var inward := (Vector3(centre.x, middle.y, centre.z) - middle).normalized()
		_face(front[a], front[b], backing[a], middle + inward, colour)
		_face(front[b], backing[b], backing[a], middle + inward, colour)

func _riparian_cover(queries: Array[TriangleMesh]) -> PackedVector3Array:
	var roots := PackedVector3Array()
	for guide: Vector4 in patch_guides:
		for sample in range(80):
			var z := guide.y + random.randf_range(-0.62, 0.62) * guide.z
			var fraction := random.randf_range(0.28, 1.0)
			var offset := _contour_offset(z, guide.x, fraction) + random.randf_range(-0.32, 0.62)
			var p := _bank_point(z, guide.x, offset)
			if not _outside_play_space(p, 1.1) or absf(z - meadow.BRIDGE_Z) < 4.2:
				continue
			var best := {}
			for query: TriangleMesh in queries:
				var hit := query.intersect_ray(Vector3(p.x, 60, p.y), Vector3.DOWN)
				if not hit.is_empty() and (best.is_empty() or hit.position.y > best.position.y):
					best = hit
			if best.is_empty() or best.position.y < -1.04 or best.normal.y < 0.52:
				continue
			var root: Vector3 = best.position + Vector3.UP * 0.005
			roots.append(root)
			var stature := random.randf_range(0.20, 0.45) * guide.w
			for leaf in range(random.randi_range(3, 5)):
				var angle := random.randf() * TAU
				var direction := Vector3(cos(angle), 0, sin(angle))
				direction.y = -(best.normal.x * direction.x + best.normal.z * direction.z) / best.normal.y
				_oval_leaf(root, direction * stature + Vector3.UP * stature * random.randf_range(0.45, 0.95),
					stature * random.randf_range(0.17, 0.28), random.randf_range(0.78, 0.97))
	assert(roots.size() > 500 and roots.size() < 6000)
	return roots
