extends RefCounted
## Candidate, NOT visually accepted. Three separated grass/stone interruptions
## on terrace 0's front lip, not a new continuous hedge or a replacement cliff.
const GEOLOGY = preload("res://scripts/meadow_detail_builder.gd")
const BRANCHES = preload("res://scripts/meadow_branch_geometry.gd")
const ANGLES := [1.76, 1.54, 1.30]
const SPANS := [Vector2(1.25, 0.48), Vector2(1.95, 0.66), Vector2(0.95, 0.42)]
const COUNTS := [22, 38, 16]
const ROCK_COUNTS := [2, 3, 1]

static func build(scene: Node3D) -> void:
	assert(not scene.has_node("LedgeBreakupStones") and not scene.has_node("LedgeBreakupGrowth"), "Build ledge candidate only once")
	var queries: Array[TriangleMesh] = []
	for label: String in ["ContinuousMeadow", "SolidLimestoneGeology"]:
		var surface := scene.get_node(NodePath(label)) as MeshInstance3D
		assert(surface.global_transform == scene.global_transform, "Support meshes must share scene-local coordinates")
		queries.append(surface.mesh.generate_triangle_mesh())
	var geology := GEOLOGY.new()
	geology.meadow = scene
	var leaves := BRANCHES.new()
	leaves.scene = scene
	var centres := PackedVector3Array()
	var tangents := PackedVector2Array()
	var outwards := PackedVector2Array()
	var stone_ranges := PackedVector2Array()
	var leaf_ranges := PackedVector2Array()
	var stone_centres := PackedVector3Array()
	var stone_sizes := PackedVector3Array()
	var group_bounds: Array[AABB] = []
	for group in range(3):
		var angle: float = ANGLES[group]
		var edge: Vector2 = scene.terrace_boundary(0, angle)
		var tangent: Vector2 = (scene.terrace_boundary(0, angle + 0.003) - scene.terrace_boundary(0, angle - 0.003)).normalized()
		var outward := Vector2(tangent.y, -tangent.x)
		var p := edge - outward * 0.72
		var hit := _support(queries, p)
		assert(not hit.is_empty(), "Ledge lip needs actual triangle support")
		centres.append(hit.position)
		tangents.append(tangent)
		outwards.append(outward)
		geology.random.seed = 1000917 + group * 997
		var first: int = geology.vertices.size()
		for rock in range(ROCK_COUNTS[group]):
			# Different along/inland offsets: no row of evenly bedded blocks.
			var along: float = [-0.48, 0.44, 1.08][rock] * SPANS[group].x
			var foot := p + tangent * along - outward * (0.25 + float(rock % 2) * 0.45)
			var support := _support(queries, foot)
			assert(not support.is_empty() and _safe(scene, foot, 1.5))
			var scale: float = [1.0, 1.22, 0.83][group] * [1.0, 0.72, 0.51][rock]
			var size := Vector3(1.32, 0.78, 0.94) * scale
			var centre: Vector3 = support.position + Vector3.UP * size.y * 0.10
			var rock_first: int = geology.vertices.size()
			geology._rock(centre, size, -atan2(tangent.y, tangent.x) + 0.43 + rock * 1.17, false)
			# _rock's first 11 side pairs expose its actual bottom-ring corners.
			# Bury the whole sampled base, not only the centre ray, into old soil/rock.
			var lower := 0.0
			for side in range(11):
				var corner: Vector3 = geology.vertices[rock_first + side * 6]
				var base := _support(queries, Vector2(corner.x, corner.z))
				assert(not base.is_empty())
				lower = maxf(lower, corner.y - Vector3(base.position).y + 0.02)
			for vertex in range(rock_first, geology.vertices.size()):
				geology.vertices[vertex] -= Vector3.UP * lower
			centre.y -= lower
			stone_centres.append(centre)
			stone_sizes.append(size)
		stone_ranges.append(Vector2(first, geology.vertices.size() - first))
		group_bounds.append(_bounds(geology.vertices, first, geology.vertices.size() - first))
	# This new mesh has its own vertex IDs and no baked terrace-occlusion prefix.
	var stone_material: ShaderMaterial = scene.get_node("SolidLimestoneGeology").material_override.duplicate()
	stone_material.set_shader_parameter("rock_ao_vertex_count", 0)
	var stones: MeshInstance3D = geology._publish("LedgeBreakupStones", stone_material, true)
	stones.layers = 8 # Exclude this local addition from the river reflection.
	queries.append(stones.mesh.generate_triangle_mesh())
	var roots := PackedVector3Array()
	var root_groups := PackedInt32Array()
	var root_ranges := PackedVector2Array()
	var accepted_counts := PackedInt32Array()
	for group in range(3):
		var random := RandomNumberGenerator.new()
		random.seed = 1000931 + group * 193
		var first: int = leaves.vertices.size()
		var root_first := roots.size()
		var centre: Vector3 = centres[group]
		var tangent: Vector2 = tangents[group]
		var outward: Vector2 = outwards[group]
		var accepted := 0
		for attempt in range(COUNTS[group] * 5):
			if accepted >= COUNTS[group]:
				break
			var angle := random.randf() * TAU
			var radial := sqrt(random.randf())
			var along: float = cos(angle) * radial * SPANS[group].x
			var inset: float = sin(angle) * radial * SPANS[group].y + 0.13 * sin(along * 2.7 + group)
			var p := Vector2(centre.x, centre.z) + tangent * along + outward * inset
			var hit := _support(queries, p)
			if hit.is_empty() or not _safe(scene, p, 1.3):
				continue
			if Vector3(hit.normal).y < 0.56 or absf(Vector3(hit.position).y - centre.y) > 1.05:
				continue # Do not plant on the vertical wall or its lower toe.
			var root: Vector3 = hit.position + Vector3.UP * 0.006
			var root_start: int = leaves.vertices.size()
			var height := random.randf_range(0.43, 0.95) * (1.15 if group == 1 else 0.90)
			var phase := random.randf() * TAU
			var tone := random.randf_range(0.76, 0.96)
			for leaf in range(6):
				var heading := phase + leaf * 2.399963
				var reach := random.randf_range(0.28, 0.65)
				var length := Vector3(cos(heading) * reach, height * random.randf_range(0.55, 1.0), sin(heading) * reach)
				# A minority of actual rooted leaves cross the lip; no hanging turf pad.
				if accepted % 5 == 0 and leaf < 2:
					var direction := outward.rotated(random.randf_range(-0.45, 0.45))
					length = Vector3(direction.x, -0.20, direction.y) * random.randf_range(0.65, 1.0)
				elif group == 1 and (leaf + accepted) % 3 == 0:
					# Bend about one third of the middle group's upright leaves only.
					# Reuse existing samples so all later roots/widths keep their RNG sequence.
					var direction := outward.rotated(sin(heading) * 0.35)
					var extension := lerpf(0.60, 0.90, inverse_lerp(0.28, 0.65, reach))
					var drop := lerpf(0.15, 0.30, inverse_lerp(0.55, 1.0, length.y / height))
					length = Vector3(direction.x * extension, -drop, direction.y * extension)
				leaves.leaf(root, length, random.randf_range(0.085, 0.16), tone, 0.55)
			roots.append(root)
			root_groups.append(group)
			root_ranges.append(Vector2(root_start, leaves.vertices.size() - root_start))
			accepted += 1
		assert(accepted >= COUNTS[group] / 2, "Inspect candidate lip support instead of accepting an empty patch")
		accepted_counts.append(accepted)
		leaf_ranges.append(Vector2(first, leaves.vertices.size() - first))
		group_bounds[group] = group_bounds[group].merge(_bounds(leaves.vertices, first, leaves.vertices.size() - first))
		print("MEADOW_LEDGE_BREAKUP: group=%d centre=%s bounds=%s sprays=%d roots=%d..%d; candidate, not visual PASS" % [group, str(centre), str(group_bounds[group]), accepted, root_first, roots.size()])
	assert((geology.vertices.size() + leaves.vertices.size()) / 3 <= 4000)
	var growth := MeshInstance3D.new()
	growth.name = "LedgeBreakupGrowth"
	growth.mesh = leaves.mesh()
	growth.material_override = scene.get_node("LivingMeadowUnderstory").material_override
	growth.layers = 8
	growth.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	growth.extra_cull_margin = 0.06
	scene.add_child(growth)
	stones.set_meta("group_ranges", stone_ranges)
	stones.set_meta("stone_centres", stone_centres)
	stones.set_meta("stone_sizes", stone_sizes)
	growth.set_meta("group_ranges", leaf_ranges)
	growth.set_meta("ground_roots", roots)
	growth.set_meta("root_groups", root_groups)
	growth.set_meta("root_ranges", root_ranges)
	growth.set_meta("spray_counts", accepted_counts)
	for mesh: MeshInstance3D in [stones, growth]:
		mesh.set_meta("group_centres", centres)
		mesh.set_meta("group_bounds", group_bounds) # Actual scene-local stone + leaf vertex bounds; add .06 wind.
		mesh.set_meta("candidate_unaccepted", true)
	# No colliders, terrain edits, new material/PNG or mutation of existing batches.

static func _support(queries: Array[TriangleMesh], p: Vector2) -> Dictionary:
	var best := {}
	for surface: TriangleMesh in queries:
		var hit := surface.intersect_ray(Vector3(p.x, 60.0, p.y), Vector3.DOWN)
		if not hit.is_empty() and (best.is_empty() or Vector3(hit.position).y > Vector3(best.position).y):
			best = hit
	return best

static func _safe(scene: Node3D, p: Vector2, reach: float) -> bool:
	return scene.distance_to_road(p) > scene.road_half_width(p.y) + reach \
		and p.distance_to(scene.BOSS_CENTER) > scene.BOSS_ARENA_RADIUS + reach \
		and absf(p.x - scene.river_center(p.y)) > scene.river_water_half_width(p.y) + reach

static func _bounds(vertices: PackedVector3Array, first: int, count: int) -> AABB:
	var bounds := AABB(vertices[first], Vector3.ZERO)
	for i in range(first + 1, first + count):
		bounds = bounds.expand(vertices[i])
	return bounds
