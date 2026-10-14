extends RefCounted
## v114 isolated candidate, NOT visually accepted. Call after terrain/detail exist.
## Five individually shaped masses, not another angular/layered cliff course.
## The open space reveals the EXISTING notch; this helper does not excavate it.
const LEAVES = preload("res://scripts/meadow_branch_geometry.gd")
const FORMS := [
	# angle, along/depth footprint, outward offset, crest rise, upper lean.
	[1.75, Vector2(3.8, 3.3), 0.65, 0.82, Vector2(0.25, -0.18)],
	[1.51, Vector2(4.2, 2.8), 0.55, 0.52, Vector2(-0.38, 0.10)],
	[1.79, Vector2(1.35, 1.45), 2.05, 0.80, Vector2(0.12, -0.08)],
	[1.32, Vector2(2.15, 1.9), 0.95, 0.28, Vector2(-0.18, -0.12)],
	[1.46, Vector2(1.65, 1.5), 2.65, 0.95, Vector2(-0.16, 0.06)],
]
const OUTLINES := [
	[Vector2(-0.48,-0.46), Vector2(0.25,-0.50), Vector2(0.49,-0.13), Vector2(0.36,0.44), Vector2(0.04,0.29), Vector2(-0.22,0.49), Vector2(-0.50,0.12)],
	[Vector2(-0.46,-0.38), Vector2(0.36,-0.47), Vector2(0.50,0.03), Vector2(0.18,0.48), Vector2(-0.10,0.32), Vector2(-0.43,0.46), Vector2(-0.51,-0.06)],
	[Vector2(-0.44,-0.30), Vector2(0.18,-0.48), Vector2(0.50,-0.04), Vector2(0.24,0.46), Vector2(-0.35,0.36)],
	[Vector2(-0.50,-0.24), Vector2(-0.02,-0.48), Vector2(0.47,-0.21), Vector2(0.34,0.45), Vector2(-0.14,0.29), Vector2(-0.46,0.40)],
	[Vector2(-0.46,-0.42), Vector2(0.33,-0.31), Vector2(0.49,0.24), Vector2(-0.06,0.47), Vector2(-0.38,0.13)],
]
const TOP_LEVELS := [0.02, -0.09, -0.24, -0.38, -0.27, -0.14, -0.04]
const GAP_ORIGIN := Vector2(-36.388867, -20.323368)
const GAP_TANGENT := Vector2(-0.885018018, 0.465556773)
const GAP_OUTWARD := Vector2(0.465556773, 0.885018018)
const XZ_LIMIT := Rect2(-43.0, -28.0, 20.0, 13.0)

static func build(scene: Node3D) -> void:
	assert(not scene.has_node("TerraceLandformsCandidate"), "Build terrace sidecar only once")
	var queries: Array[TriangleMesh] = []
	for label: String in ["ContinuousMeadow", "SolidLimestoneGeology"]:
		var old := scene.get_node(NodePath(label)) as MeshInstance3D
		assert(old.global_transform == scene.global_transform, "Expected scene-local support arrays")
		queries.append(old.mesh.generate_triangle_mesh())
	var builder := RockMesh.new()
	var ranges := PackedVector2Array()
	var roots := PackedVector3Array()
	var crest_hits := PackedVector3Array()
	var base_vertices := PackedVector3Array()
	var base_hits := PackedVector3Array()
	var base_sources := PackedInt32Array()
	var base_ranges := PackedVector2Array()
	var bounds: Array[AABB] = []
	var outwards := PackedVector2Array()
	var tangents := PackedVector2Array()
	var centres := PackedVector2Array()
	for piece in range(FORMS.size()):
		var spec: Array = FORMS[piece]
		var angle: float = spec[0]
		var span: Vector2 = spec[1]
		var edge: Vector2 = scene.terrace_boundary(0, angle)
		var tangent: Vector2 = (scene.terrace_boundary(0, angle + 0.003) - scene.terrace_boundary(0, angle - 0.003)).normalized()
		var outward := Vector2(tangent.y, -tangent.x)
		var centre: Vector2 = edge + outward * float(spec[2])
		var root := _support(queries, centre)
		var crest := _support(queries, edge - outward * 0.95)
		assert(not root.is_empty() and not crest.is_empty(), "No unsupported fallback rock")
		roots.append(root.position)
		crest_hits.append(crest.position)
		centres.append(centre)
		outwards.append(outward)
		tangents.append(tangent)
		# Two tall trans-course slabs, one smaller shoulder, two low toe fragments.
		var high: float = Vector3(crest.position).y if piece in [0, 1, 3] else Vector3(root.position).y
		high += float(spec[3])
		var outline: Array = OUTLINES[piece]
		var bottom := PackedVector3Array()
		var top := PackedVector3Array()
		var first_base := base_vertices.size()
		for side in range(outline.size()):
			var a: Vector2 = outline[side] * span
			var b: Vector2 = outline[(side + 1) % outline.size()] * span
			# Sample actual old triangles along the entire foot, not height formulas.
			var steps := maxi(1, int(ceil(a.distance_to(b) / 0.32)))
			for step in range(steps):
				var f := float(step) / steps
				var q := a.lerp(b, f)
				var p := centre + tangent * q.x + outward * q.y
				var hit := _support(queries, p)
				assert(not hit.is_empty(), "Every perimeter foot needs existing triangle support")
				var foot: Vector3 = hit.position - Vector3.UP * 0.14
				bottom.append(foot)
				base_vertices.append(foot)
				base_hits.append(hit.position)
				base_sources.append(hit.source)
				# Unequal crest and oblique shoulders; only one tall side face, no rings.
				var upper: Vector2 = q * Vector2(0.82, 0.76) + Vector2(spec[4])
				var upper_xz := centre + tangent * upper.x + outward * upper.y
				var level := lerpf(TOP_LEVELS[side], TOP_LEVELS[(side + 1) % outline.size()], f)
				top.append(Vector3(upper_xz.x, high + level, upper_xz.y))
		# Existing fractured shoulders can stand above the centre hit. Keep the
		# whole crest above its measured foot instead of allowing inverted sides.
		var lift := 0.0
		for foot: Vector3 in bottom:
			lift = maxf(lift, foot.y + 0.66 - high)
		high += lift
		for index in range(top.size()):
			top[index] += Vector3.UP * lift
		base_ranges.append(Vector2(first_base, bottom.size()))
		var crown_xz := centre + tangent * (0.07 * span.x) - outward * (0.08 * span.y)
		var crown := Vector3(crown_xz.x, high + 0.12, crown_xz.y)
		var low := bottom[0].y
		for p: Vector3 in bottom:
			low = minf(low, p.y)
		var sole := Vector3(centre.x, low - 0.10, centre.y)
		var first := builder.vertices.size()
		for side in range(bottom.size()):
			var next := (side + 1) % bottom.size()
			var delta := bottom[next] - bottom[side]
			var facing := Vector3(-delta.z, 0, delta.x).normalized()
			builder._triangle(bottom[side], bottom[next], top[next], facing)
			builder._triangle(bottom[side], top[next], top[side], facing)
			builder._triangle(crown, top[side], top[next], Vector3.UP)
			builder._triangle(sole, bottom[next], bottom[side], Vector3.DOWN)
		var count := builder.vertices.size() - first
		ranges.append(Vector2(first, count))
		bounds.append(_bounds(builder.vertices, first, count))
		# A continuous separating strip keeps ALL triangles away from the notch.
		# Bent centreline below lies inside it; no ray/metadata-only proof of a gap.
		var gap_side := signf((centre - GAP_ORIGIN).dot(GAP_TANGENT))
		for index in range(first, first + count):
			var p: Vector3 = builder.vertices[index]
			assert((Vector2(p.x, p.z) - GAP_ORIGIN).dot(GAP_TANGENT) * gap_side > 0.85)
			_validate(scene, p)
	var holder := Node3D.new()
	holder.name = "TerraceLandformsCandidate"
	var rocks := MeshInstance3D.new()
	rocks.name = "ErodedTerraceMasses"
	rocks.mesh = builder._mesh()
	var material: ShaderMaterial = scene.get_node("SolidLimestoneGeology").material_override.duplicate(false)
	material.set_shader_parameter("rock_ao_vertex_count", 0) # Own vertex IDs, never the old AO prefix.
	rocks.material_override = material
	rocks.layers = 8
	rocks.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	holder.add_child(rocks)
	# Sparse actual leaf roots on the new top triangles, not a turf pad or hedge.
	var rock_query := rocks.mesh.generate_triangle_mesh()
	var leaves := LEAVES.new()
	leaves.scene = scene
	var random := RandomNumberGenerator.new()
	random.seed = 1140827
	var leaf_roots := PackedVector3Array()
	var leaf_ranges := PackedVector2Array()
	var leaf_pieces := PackedInt32Array()
	for piece in range(FORMS.size()):
		var sprays: int = [3, 2, 0, 1, 0][piece]
		for spray in range(sprays):
			var p := centres[piece] + tangents[piece] * ((spray - (sprays - 1) * 0.5) * 0.42) + outwards[piece] * 0.48
			var hit := rock_query.intersect_ray(Vector3(p.x, 60, p.y), Vector3.DOWN)
			var old := _support(queries, p)
			if hit.is_empty() or Vector3(hit.normal).y < 0.55:
				continue
			if not old.is_empty() and Vector3(old.position).y > Vector3(hit.position).y:
				continue # Never plant a buried/invisible top face.
			var root: Vector3 = hit.position + Vector3.UP * 0.006
			var first: int = leaves.vertices.size()
			for leaf in range(4):
				var heading := outwards[piece].rotated(random.randf_range(-0.55, 0.55))
				var reach := random.randf_range(0.55, 0.90)
				var vertical := random.randf_range(-0.32, -0.15) if leaf < 3 else 0.26
				leaves.leaf(root, Vector3(heading.x * reach, vertical, heading.y * reach), random.randf_range(0.09, 0.14), random.randf_range(0.78, 0.88), 0.45)
			leaf_roots.append(root)
			leaf_ranges.append(Vector2(first, leaves.vertices.size() - first))
			leaf_pieces.append(piece)
	assert(not leaf_roots.is_empty(), "Inspect top support instead of accepting leafless candidate")
	for p: Vector3 in leaves.vertices:
		_validate(scene, p, 0.06)
		assert(absf((Vector2(p.x, p.z) - GAP_ORIGIN).dot(GAP_TANGENT)) > 0.91)
	var growth := MeshInstance3D.new()
	growth.name = "RootedCleftLeaves"
	growth.mesh = leaves.mesh()
	growth.material_override = scene.get_node("LivingMeadowUnderstory").material_override
	growth.layers = 8
	growth.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	growth.extra_cull_margin = 0.06
	holder.add_child(growth)
	var triangles: int = (builder.vertices.size() + leaves.vertices.size()) / 3
	assert(triangles <= 5000)
	rocks.set_meta("piece_ranges", ranges) # Unindexed [first corner, corner count].
	rocks.set_meta("piece_bounds", bounds)
	rocks.set_meta("old_surface_roots", roots)
	rocks.set_meta("old_crest_hits", crest_hits)
	rocks.set_meta("base_ranges", base_ranges)
	rocks.set_meta("base_vertices", base_vertices) # Actual corners in piece_ranges, including side/sole duplicates.
	rocks.set_meta("base_support_hits", base_hits) # Exact old triangle hits; base.y = hit.y - .14.
	rocks.set_meta("base_support_sources", base_sources) # 0 ContinuousMeadow, 1 SolidLimestoneGeology.
	growth.set_meta("roots", leaf_roots) # Actual new-rock hit + .006; leaf base has zero wind.
	growth.set_meta("root_ranges", leaf_ranges)
	growth.set_meta("root_pieces", leaf_pieces)
	var gap := PackedVector2Array()
	for q: Vector2 in [Vector2(-0.10,-1.5), Vector2(0.25,-0.3), Vector2(-0.20,1.1), Vector2(-0.35,2.8)]:
		gap.append(GAP_ORIGIN + GAP_TANGENT * q.x + GAP_OUTWARD * q.y)
	holder.set_meta("schema", "terrace-landforms-114-1")
	holder.set_meta("candidate_unaccepted", true)
	holder.set_meta("triangle_count", triangles)
	holder.set_meta("gap_xz_polyline", gap)
	holder.set_meta("gap_half_width", 0.40) # Free of NEW rocks/leaves only, not a new walkable excavation.
	holder.set_meta("bounds", rocks.mesh.get_aabb().merge(growth.mesh.get_aabb().grow(0.06)))
	scene.add_child(holder) # No owners/colliders, cache mutation, RNG sharing or existing material edits.
	print("MEADOW_TERRACE_LANDFORMS: candidate 5 masses/%d rooted sprays/%d triangles bounds=%s; not visual PASS" % [leaf_roots.size(), triangles, str(holder.get_meta("bounds"))])

static func _support(queries: Array[TriangleMesh], p: Vector2) -> Dictionary:
	var best := {}
	for index in range(queries.size()):
		var hit := queries[index].intersect_ray(Vector3(p.x, 60, p.y), Vector3.DOWN)
		if not hit.is_empty() and (best.is_empty() or Vector3(hit.position).y > Vector3(best.position).y):
			best = hit
			best["source"] = index
	return best

static func _validate(scene: Node3D, p: Vector3, wind: float = 0.0) -> void:
	var xz := Vector2(p.x, p.z)
	assert(XZ_LIMIT.grow(-wind).has_point(xz) and p.y >= -1.0 and p.y <= 6.0)
	assert(scene.distance_to_road(xz) > scene.road_half_width(p.z) + wind)
	assert(xz.distance_to(scene.BOSS_CENTER) > scene.BOSS_ARENA_RADIUS + wind)
	assert(absf(p.x - scene.river_center(p.z)) > scene.river_water_half_width(p.z) + 0.5 + wind)

class RockMesh:
	extends RefCounted
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()

	func _triangle(a: Vector3, b: Vector3, c: Vector3, facing: Vector3) -> void:
		var normal := (c - a).cross(b - a)
		assert(normal.length_squared() > 0.00000001)
		if normal.dot(facing) < 0.0: # Godot clockwise fronts, including concave shoulder cuts.
			var swap := b
			b = c
			c = swap
			normal = -normal
		normal = normal.normalized()
		for p: Vector3 in [a, b, c]:
			vertices.append(p)
			normals.append(normal)

	func _mesh() -> ArrayMesh:
		var colours := PackedColorArray()
		var uvs := PackedVector2Array()
		var fields := PackedVector2Array()
		for _p: Vector3 in vertices:
			colours.append(Color(0, 1, 1, 1)) # No turf cap/pale hero tag/per-block colour/AO.
			uvs.append(Vector2(-1, -1)) # No cliff PNG; existing world-metric mineral texture only.
			fields.append(Vector2.ZERO)
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = vertices
		arrays[Mesh.ARRAY_NORMAL] = normals
		arrays[Mesh.ARRAY_COLOR] = colours
		arrays[Mesh.ARRAY_TEX_UV] = uvs
		arrays[Mesh.ARRAY_TEX_UV2] = fields
		var result := ArrayMesh.new()
		result.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		return result

static func _bounds(points: PackedVector3Array, first: int, count: int) -> AABB:
	var result := AABB(points[first], Vector3.ZERO)
	for index in range(first + 1, first + count):
		result = result.expand(points[index])
	return result
