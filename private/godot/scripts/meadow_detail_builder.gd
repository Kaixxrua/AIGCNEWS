extends RefCounted
## Unique solid geology and a continuous, non-colliding meadow understory.
## Every rock has its own vertices. No tree/prop artwork is duplicated here.

const ROCK_SHADER = preload("res://shaders/meadow_limestone.gdshader")
const LEAF_SHADER = preload("res://shaders/meadow_leaves.gdshader")
const STONE = preload("res://assets/materials/limestone-fractured-v61.png")
const ESCARPMENTS = preload("res://assets/materials/limestone-escarpments-v46.png")
const GRASS = preload("res://assets/materials/meadow-sward-v60.png")
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const FACE_CROPS := [Rect2(33, 24, 2106, 158), Rect2(33, 207, 2097, 154),
	Rect2(33, 361, 2105, 184), Rect2(39, 562, 2087, 139)]
const FACE_SPANS := [Vector2(-54, -6), Vector2(-66, -17), Vector2(-77, -19)]

var meadow
var random := RandomNumberGenerator.new()
var vertices := PackedVector3Array()
var normals := PackedVector3Array()
var colors := PackedColorArray()
var uv := PackedVector2Array()
var growth_fields := PackedVector2Array()
var leaf_density := 0.0
var stone_count := 0
var wall_count := 0
var bedded_rock_count := 0
var bank_stone_count := 0
var leaf_count := 0
var face_domain := -1
var notch_source_geometry := false
var face_start := Vector2.ZERO
var face_end := Vector2.RIGHT
var face_low := Vector2.ZERO
var face_high := Vector2.ONE
var used_face_domains: Dictionary = {}
var ledge_caps: Array = []
var sparse_blades := 0
var dense_blades := 0
var ledge_sprays := 0
var cap_anchors := PackedVector3Array()
var creeping_anchors := PackedVector3Array()
var ecotone_anchors := PackedVector3Array()
var ecotone_guides := PackedVector4Array()
var ecotone_heights := PackedVector2Array()
var ecotone_links := PackedVector4Array()
var foreground_growth_guides := PackedVector4Array()
var terrace_faces := PackedVector4Array()
var relief_probes := PackedVector3Array()
var relief_normals := PackedVector3Array()

func build(scene: Node3D) -> void:
	meadow = scene
	if CACHE.restore(scene, "detail"):
		var metrics: Dictionary = scene.get_node("SolidLimestoneGeology").get_meta("builder_metrics")
		assert(metrics.stones > 1000 and metrics.leaves > 100000 and metrics.face_domains == 4)
		print("MEADOW_CLIFF_SURFACE_AUDIT: 4 unique atlas regions on 4 solid escarpments; prebuilt meshes")
		print("MEADOW_DETAIL_AUDIT: %d unique solid rocks; %d individual grass/leaf forms; prebuilt" % [metrics.stones, metrics.leaves])
		print("MEADOW_GROWTH_AUDIT: shared terrain UV2 field; %d sparse / %d dense blades; %d supported cap sprays (prebuilt)" % [metrics.sparse, metrics.dense, metrics.caps])
		print("MEADOW_PROP_SEAM_AUDIT: %d actual-surface grass roots (prebuilt)" % scene.get_node("PropGroundStitches").get_meta("root_anchors").size())
		return
	random.seed = 380091
	var start := Time.get_ticks_msec()
	notch_source_geometry = true
	_build_escarpments()
	# A spatial revision of the left terraces must not silently reshape the
	# foreground rim, river stones or hero boulders later in this same batch.
	var left_terrace_vertex_count := vertices.size()
	# Independent streams keep later revisions of the cliffs from reshuffling
	# unrelated river stones, the foreground rim and the meadow understory.
	random.seed = 610902
	_build_foreground_escarpment()
	random.seed = 610903
	_build_riverbanks()
	random.seed = 610904
	_build_loose_stones()
	random.seed = 610905
	_build_hero_boulders()
	notch_source_geometry = false
	var rock_material := ShaderMaterial.new()
	rock_material.shader = ROCK_SHADER
	rock_material.set_shader_parameter("limestone_texture", STONE)
	rock_material.set_shader_parameter("escarpment_texture", ESCARPMENTS)
	rock_material.set_shader_parameter("meadow_texture", GRASS)
	var rocks := _publish("SolidLimestoneGeology", rock_material, true)
	rocks.create_trimesh_collision()
	rocks.set_meta("terrace_faces", terrace_faces)
	rocks.set_meta("relief_probes", relief_probes)
	rocks.set_meta("relief_normals", relief_normals)
	rocks.set_meta("left_terrace_face_vertices", left_terrace_vertex_count)
	_clear_arrays()
	random.seed = 610906
	_build_living_meadow()
	random.seed = 610907
	_build_fern_colonies()
	var leaf_material := ShaderMaterial.new()
	leaf_material.shader = LEAF_SHADER
	leaf_material.set_shader_parameter("meadow_texture", GRASS)
	# Sub-pixel grass shadows alias at this wide camera distance and resubmit
	# hundreds of thousands of triangles. Leaves still receive tree/rock shadows;
	# their own root occlusion comes from vertex shading and SSAO.
	var understory := _publish("LivingMeadowUnderstory", leaf_material, false)
	understory.layers = 8 # Tiny leaves need not be captured by the river probe.
	_clear_arrays()
	# Reuse Mesh's cached triangle queries during construction only. Height-field
	# sampling alone diverges from the triangulated cliff bevel near an edge.
	var land_mesh: Mesh = meadow.get_node("ContinuousMeadow").mesh
	var surface_queries: Array[TriangleMesh] = [land_mesh.generate_triangle_mesh(), rocks.mesh.generate_triangle_mesh()]
	var query_ceiling := maxf(land_mesh.get_aabb().end.y, rocks.mesh.get_aabb().end.y) + 2.0
	_build_creeping_colonies(surface_queries, query_ceiling)
	random.seed = 630907
	_build_ledge_growth(surface_queries, query_ceiling)
	# The broader, low leaf cushions have meaningful silhouettes and cast shadows.
	# Keep the fine grass in its cheaper non-casting mesh above.
	var cushions := _publish("CreepingMeadowAndLedgeGrowth", leaf_material, true)
	cushions.layers = 8
	cushions.set_meta("cap_anchors", cap_anchors)
	cushions.set_meta("creeping_anchors", creeping_anchors)
	cushions.set_meta("ecotone_anchors", ecotone_anchors)
	cushions.set_meta("ecotone_guides", ecotone_guides)
	cushions.set_meta("ecotone_heights", ecotone_heights)
	cushions.set_meta("ecotone_links", ecotone_links)
	cushions.set_meta("foreground_growth_guides", foreground_growth_guides)
	_clear_arrays()
	var seams := _build_prop_seams(surface_queries, query_ceiling)
	var bank_roots := _build_bank_growth(surface_queries, query_ceiling)
	var stitches := _publish("PropGroundStitches", leaf_material, false)
	stitches.layers = 8
	stitches.set_meta("root_anchors", seams)
	stitches.set_meta("bank_roots", bank_roots)
	rocks.set_meta("builder_metrics", {"stones": stone_count, "leaves": leaf_count, "walls": wall_count,
		"bedded": bedded_rock_count, "bank_stones": bank_stone_count, "sparse": sparse_blades, "dense": dense_blades,
		"caps": ledge_sprays, "face_domains": used_face_domains.size()})
	print("MEADOW_PROP_SEAM_AUDIT: %d actual-surface grass roots; one mesh; no image props copied" % seams.size())
	print("MEADOW_BANK_GROWTH_AUDIT: %d actual-surface roots; irregular grass/reed colonies, no floating caps" % bank_roots.size())
	print("MEADOW_DETAIL_AUDIT: %d unique solid rocks; %d individual grass/leaf forms; build %d ms" % [
		stone_count, leaf_count, Time.get_ticks_msec() - start])
	print("MEADOW_GEOLOGY_AUDIT: %d continuous stratified rock-face segments" % wall_count)
	print("MEADOW_BEDDED_ROCK_AUDIT: %d angular blocks on the four escarpments; river stones retain their worn profile" % bedded_rock_count)
	assert(used_face_domains.size() == 4, "Each selected cliff strip belongs to one unique rock surface")
	print("MEADOW_CLIFF_SURFACE_AUDIT: 4 unique atlas regions on 4 solid escarpments; no repeated strip instances")
	assert(sparse_blades > 0 and dense_blades > sparse_blades * 3, "Meadow must retain both sparse turf and connected dense growth")
	assert(ledge_sprays > 24, "Ledge growth must be grounded on actual rock caps")
	print("MEADOW_GROWTH_AUDIT: shared terrain UV2 field; %d sparse / %d dense blades; %d supported cap sprays" % [sparse_blades, dense_blades, ledge_sprays])

func _build_prop_seams(surface_queries: Array[TriangleMesh], query_ceiling: float) -> PackedVector3Array:
	# Short, irregular grass overlaps the feet of art props. It uses the same
	# terrain material and exact surface queries as the existing meadow growth.
	var seam_random := RandomNumberGenerator.new()
	seam_random.seed = 520922
	var anchors := PackedVector3Array()
	for child in meadow.get_children():
		if not child is MeshInstance3D or not child.has_meta("art_foot"):
			continue
		var material: ShaderMaterial = child.material_override
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		if not texture.resource_path.contains("/foliage/") and not texture.resource_path.contains("/props/"):
			continue
		var foot: Vector2 = child.get_meta("seam_sampling_foot", child.get_meta("art_foot"))
		if foot.y < -145.0:
			continue
		var width: float = child.get_meta("art_width")
		for sample in range(42):
			var x := seam_random.randf_range(-0.46, 0.46) * width
			var z := seam_random.randf_range(0.15, minf(1.1, width * 0.22))
			var p := foot + Vector2(x, z)
			if not _outside_play_space(p, 3.2):
				continue
			if absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + 1.6:
				continue
			var surface_y := -INF
			var surface_normal := Vector3.UP
			for query: TriangleMesh in surface_queries:
				var hit := query.intersect_ray(Vector3(p.x, query_ceiling, p.y), Vector3.DOWN)
				if not hit.is_empty() and hit.position.y > surface_y:
					surface_y = hit.position.y
					surface_normal = hit.normal
			if not is_finite(surface_y) or surface_normal.y < 0.80:
				continue
			var root := Vector3(p.x, surface_y + 0.006, p.y)
			anchors.append(root)
			for leaf in range(3):
				var angle := seam_random.randf() * TAU
				var outward := Vector3(cos(angle), 0.0, sin(angle))
				var height := seam_random.randf_range(0.16, 0.36)
				_blade(root, Vector3(-outward.z, 0, outward.x), outward * height * 0.60,
					height, seam_random.randf_range(0.045, 0.095), seam_random.randf_range(0.76, 1.03), surface_normal)
	assert(anchors.size() > 100, "Prop seams must contain real grounded vegetation")
	return anchors

func _build_bank_growth(surface_queries: Array[TriangleMesh], query_ceiling: float) -> PackedVector3Array:
	var bank_random := RandomNumberGenerator.new()
	bank_random.seed = 570919
	var roots := PackedVector3Array()
	for side: float in [-1.0, 1.0]:
		for sample in range(1900):
			var z := bank_random.randf_range(-136.0, 18.0)
			if absf(z - meadow.BRIDGE_Z) < 3.0:
				continue
			var colony := sin(z * 0.42 + side * 1.7) * 0.5 + 0.5
			if bank_random.randf() > lerpf(0.15, 0.84, colony):
				continue
			var clearance: float = bank_random.randf_range(0.2, 2.25) + meadow.river_upper_slope(z) * 0.65
			var x: float = meadow.river_center(z) + side * (meadow.river_half_width(z) + meadow.river_bank_offset(z, side) + clearance)
			var point := Vector2(x, z)
			if not _outside_play_space(point, 3.1):
				continue
			var best := {}
			for query: TriangleMesh in surface_queries:
				var hit := query.intersect_ray(Vector3(x, query_ceiling, z), Vector3.DOWN)
				if not hit.is_empty() and (best.is_empty() or hit.position.y > best.position.y):
					best = hit
			if best.is_empty() or best.position.y < -1.28 or best.normal.y < 0.34:
				continue
			var root: Vector3 = best.position + Vector3.UP * 0.005
			roots.append(root)
			for leaf in range(bank_random.randi_range(3, 6)):
				var angle := bank_random.randf() * TAU
				var outward := Vector3(cos(angle), 0, sin(angle))
				var height := bank_random.randf_range(0.14, 0.36) * (1.6 if clearance < 1.0 else 1.0)
				_blade(root, Vector3(-outward.z, 0, outward.x), outward * height * 0.45,
					height, bank_random.randf_range(0.035, 0.085), bank_random.randf_range(0.76, 1.02), best.normal)
	assert(roots.size() > 200)
	return roots

func _build_escarpments() -> void:
	for shelf in range(meadow.TERRACES.size()):
		face_domain = shelf if shelf < 3 else -1
		for step in range(194):
			var angle := TAU * float(step) / 194.0
			var point: Vector2 = meadow.terrace_boundary(shelf, angle)
			if point.x < -83.0 or point.y < -93.0:
				continue
			var next_angle := TAU * float(step + 1) / 194.0
			var next: Vector2 = meadow.terrace_boundary(shelf, next_angle)
			var outside := _shelf_outside(shelf, angle)
			var next_outside := _shelf_outside(shelf, next_angle)
			var tangent := (next - point).normalized()
			var bottom := float(meadow.terrain_height_before_notch(point.x + outside.x * 1.65, point.y + outside.y * 1.65)) - 0.16
			var top := float(meadow.terrain_height_before_notch(point.x - outside.x * 1.55, point.y - outside.y * 1.55)) + 0.04
			var next_bottom := float(meadow.terrain_height_before_notch(next.x + next_outside.x * 1.65, next.y + next_outside.y * 1.65)) - 0.16
			var next_top := float(meadow.terrain_height_before_notch(next.x - next_outside.x * 1.55, next.y - next_outside.y * 1.55)) + 0.04
			# Broad erosion saddles belong to the grassy height field, not a
			# low continuous retaining wall joining the remaining exposed faces.
			if minf(top - bottom, next_top - next_bottom) < 0.65 or meadow.terrace_erosion(shelf, angle) > 0.64:
				continue
			terrace_faces.append(Vector4(shelf, angle, next_angle, point.distance_to(next)))
			_wall_segment(point, next, bottom, next_bottom, top, next_top, outside, next_outside)
			# Sparse broken shelves project from a continuous face. The former wall
			# consisted entirely of separate upright rocks and read as a palisade.
			if random.randf() < 0.32:
				var ledge := Vector3(point.x + outside.x * 0.52, lerpf(bottom, top, random.randf_range(0.15, 0.78)), point.y + outside.y * 0.52)
				_rock(ledge, Vector3(random.randf_range(1.3, 2.7), random.randf_range(0.28, 0.68), 1.1), -atan2(tangent.y, tangent.x), false)
			if random.randf() < 0.52:
				var toe := point + outside * random.randf_range(0.8, 2.2)
				var radius := random.randf_range(0.26, 0.66)
				_rock(Vector3(toe.x, meadow.terrain_height_before_notch(toe.x, toe.y) + radius * 0.1, toe.y),
					Vector3(radius * 1.8, radius, radius * 1.5), random.randf() * TAU, false)

func _build_foreground_escarpment() -> void:
	face_domain = 3
	for i in range(84):
		var x := -34.0 + i * 0.78
		var z: float = meadow.foreground_edge(x)
		if absf(x - meadow.river_center(z)) < meadow.river_half_width(z) + 0.8:
			continue
		var next_x := x + 0.78
		var next_z: float = meadow.foreground_edge(next_x)
		var a := Vector2(x, z)
		var b := Vector2(next_x, next_z)
		var outside := _rim_outside(x)
		var next_outside := _rim_outside(next_x)
		var upper: float = meadow.terrain_height(x, z - 1.1)
		var next_upper: float = meadow.terrain_height(next_x, next_z - 1.1)
		_wall_segment(a, b, upper - 4.35, next_upper - 4.35, upper, next_upper, outside, next_outside)
		if random.randf() < 0.48:
			var center := Vector3(x + outside.x * 0.56, upper - random.randf_range(0.9, 3.5), z + outside.y * 0.56)
			_rock(center, Vector3(random.randf_range(1.3, 2.9), random.randf_range(0.32, 0.85), 1.4), random.randf_range(-0.5, 0.5), false)

func _build_riverbanks() -> void:
	face_domain = -1
	var stones := 0
	for side in [-1.0, 1.0]:
		for i in range(246):
			var z := 24.0 - i * 0.72
			if absf(z - meadow.BRIDGE_Z) < 3.0:
				continue
			# Bedrock is the sloping terrain itself. Discontinuous embedded stones
			# expose soil/reeds between them, instead of a capped green cardboard wall.
			var colony := 0.5 + 0.5 * sin(z * 0.21 + side * 1.7)
			if random.randf() > lerpf(0.28, 0.78, colony):
				continue
			var offset := random.randf_range(-0.18, 1.22)
			var x: float = meadow.river_center(z) + side * (meadow.river_half_width(z)
				+ meadow.river_bank_offset(z, side) + offset)
			var y: float = meadow.terrain_height(x, z)
			if y < -1.60 or y > 3.5:
				continue
			var size := Vector3(random.randf_range(0.42, 1.10), random.randf_range(0.32, 0.78), random.randf_range(0.48, 1.30))
			_rock(Vector3(x, y + size.y * 0.19, z), size, random.randf() * TAU, false)
			stones += 1
	print("MEADOW_NATURAL_BANK_AUDIT: %d embedded irregular stones; continuous terrain banks; no horizontal river caps" % stones)
	bank_stone_count = stones

func _build_hero_boulders() -> void:
	# Replace the two near cutout clusters with distinct volumetric rocks, sunk
	# into the same physical terrain and included in its collision/shadow batch.
	face_domain = -1
	var rocks := [Vector4(-5.8, 1.52, 2.12, 1.24), Vector4(-4.58, 1.9, 1.32, 0.83),
		Vector4(-6.78, 2.12, 1.02, 0.64), Vector4(14.20, -7.12, 2.20, 1.33),
		Vector4(15.58, -6.77, 1.62, 0.91)]
	for i in range(rocks.size()):
		var spec: Vector4 = rocks[i]
		var p := Vector2(spec.x, spec.y)
		var size := Vector3(spec.z, spec.w, spec.z * 0.76)
		_rock(Vector3(p.x, meadow.terrain_height(p.x, p.y) + size.y * 0.22, p.y),
			size, float(i) * 1.73, false, false, true)
	print("MEADOW_SOLID_PROPS_AUDIT: 5 distinct near boulders; real volume, collision and directional shadows; no rock cards")

func _shelf_outside(shelf: int, angle: float) -> Vector2:
	var tangent: Vector2 = (meadow.terrace_boundary(shelf, angle + 0.003) - meadow.terrace_boundary(shelf, angle - 0.003)).normalized()
	return Vector2(tangent.y, -tangent.x)

func _rim_outside(x: float) -> Vector2:
	var slope: float = (meadow.foreground_edge(x + 0.03) - meadow.foreground_edge(x - 0.03)) / 0.06
	return Vector2(-slope, 1.0).normalized()

func _bank_outside(z: float, side: float) -> Vector2:
	var x0: float = meadow.river_center(z + 0.03) + side * meadow.river_half_width(z + 0.03)
	var x1: float = meadow.river_center(z - 0.03) + side * meadow.river_half_width(z - 0.03)
	var tangent := Vector2(x1 - x0, -0.06).normalized()
	return Vector2(-tangent.y, tangent.x) * -side

func _wall_vertex(point: Vector2, outside: Vector2, bottom: float, top: float, layer: int) -> Vector3:
	const LEVELS := [0.0, 0.16, 0.33, 0.50, 0.69, 0.85, 1.0]
	# Every endpoint is a deterministic function of the world position. Adjacent
	# pieces therefore share edges; random per-piece offsets would reopen cracks.
	var phase := point.x * 1.13 + point.y * 0.91
	var fraction: float = LEVELS[layer]
	var fracture := sin(phase * 0.57) * 0.12 + sin(point.y * 0.91 - point.x * 0.39) * 0.065
	# A shared monotonic warp undulates the beds without splitting adjacent
	# segments or crossing two rows. There is no fixed full-length notch band.
	fraction += fracture * sin(fraction * PI)
	var irregular := sin(phase + layer * 1.67) * 0.19 + sin(point.y * 1.83 - point.x * 0.79 + layer * 2.31) * 0.11
	# The height-field cliff is bevelled across roughly 1.2 metres. Lower rows
	# must extend beyond that bevel or the terrain buries the detailed wall.
	var exposed_toe: float = (1.0 - fraction) * 1.45
	var shoulder_inset := smoothstep(0.70, 1.0, fraction) * 0.42 if face_domain >= 0 and face_domain < 3 else 0.0
	var p: Vector2 = point + outside * (0.20 + irregular + exposed_toe - shoulder_inset)
	# Interior joints lean across the beds. The shared endpoint function keeps
	# neighbouring sections welded; upper/lower boundaries stay exactly fixed.
	var tangent := Vector2(-outside.y, outside.x)
	p += tangent * sin(phase * 0.79 + layer * 2.13) * 0.14 * sin(float(layer) * PI / 6.0)
	return Vector3(p.x, lerpf(bottom, top, fraction), p.y)

func _wall_notch_drop(point: Vector2, outside: Vector2, bottom: float, top: float) -> float:
	if face_domain != 0:
		return 0.0
	var crest := _wall_vertex(point, outside, bottom, top, 6)
	return meadow.terrace_notch_offset(crest.x, crest.z)

func _wall_segment(a: Vector2, b: Vector2, bottom_a: float, bottom_b: float,
		top_a: float, top_b: float, outside_a: Vector2, outside_b: Vector2) -> void:
	# Generate the ORIGINAL fracture field, stone sizes and winding first.
	# Only the final wall corners receive a continuous downward displacement.
	var drop_a := _wall_notch_drop(a, outside_a, bottom_a, top_a)
	var drop_b := _wall_notch_drop(b, outside_b, bottom_b, top_b)
	wall_count += 1
	face_start = a
	face_end = b
	face_low = Vector2(bottom_a, bottom_b)
	face_high = Vector2(top_a, top_b)
	if face_domain >= 0:
		used_face_domains[face_domain] = true
	var outward := Vector3(outside_a.x + outside_b.x, 0, outside_a.y + outside_b.y).normalized()
	for layer in range(6):
		var a0 := _wall_vertex(a, outside_a, bottom_a, top_a, layer)
		var a1 := _wall_vertex(a, outside_a, bottom_a, top_a, layer + 1)
		var b0 := _wall_vertex(b, outside_b, bottom_b, top_b, layer)
		var b1 := _wall_vertex(b, outside_b, bottom_b, top_b, layer + 1)
		assert(a1.y > a0.y and b1.y > b0.y, "Weathered cliff beds must remain monotonic")
		var inside := (a0 + a1 + b0 + b1) * 0.25 - outward * 3.0
		var tone := 0.88 + 0.08 * sin(layer * 2.3 + a.x * 0.13 + a.y * 0.10)
		var meta := Color(0.0, tone, 0.5, 1.0)
		var drops := Vector4(drop_a * (a0.y - bottom_a) / (top_a - bottom_a),
			drop_a * (a1.y - bottom_a) / (top_a - bottom_a),
			drop_b * (b1.y - bottom_b) / (top_b - bottom_b),
			drop_b * (b0.y - bottom_b) / (top_b - bottom_b))
		_weathered_wall_cell(a0, a1, b1, b0, inside, outside_a, outside_b, meta, layer, drops)
	# A thin turf-bearing upper lip meets the solid collision terrain behind it.
	# This hides neither a floating card nor a duplicated painted ledge.
	var front_a := _wall_vertex(a, outside_a, bottom_a, top_a, 6)
	var front_b := _wall_vertex(b, outside_b, bottom_b, top_b, 6)
	var rear_a := Vector3(a.x - outside_a.x * 1.55, top_a - 0.04, a.y - outside_a.y * 1.55)
	var rear_b := Vector3(b.x - outside_b.x * 1.55, top_b - 0.04, b.y - outside_b.y * 1.55)
	# The inner edge follows actual terrain instead of extending an arbitrary
	# level green strip around every irregular escarpment.
	if face_domain >= 0 and face_domain < 3:
		rear_a.y = meadow.terrain_height_before_notch(rear_a.x, rear_a.z) + 0.012
		rear_b.y = meadow.terrain_height_before_notch(rear_b.x, rear_b.z) + 0.012
	var rear_drop_a: float = meadow.terrace_notch_offset(rear_a.x, rear_a.z) if face_domain == 0 else 0.0
	var rear_drop_b: float = meadow.terrace_notch_offset(rear_b.x, rear_b.z) if face_domain == 0 else 0.0
	var cap_center := (front_a + front_b + rear_a + rear_b) * 0.25 - Vector3.UP
	_face(front_a, rear_a, front_b, cap_center, Color(1.0, 0.94, 0.5, 1.0), Vector3.ONE, 0.18, Vector3(drop_a, rear_drop_a, drop_b))
	_face(front_b, rear_a, rear_b, cap_center, Color(1.0, 0.94, 0.5, 1.0), Vector3.ONE, 0.18, Vector3(drop_b, rear_drop_a, rear_drop_b))
	front_a.y += drop_a
	front_b.y += drop_b
	rear_a.y += rear_drop_a
	rear_b.y += rear_drop_b
	if face_domain >= 0:
		ledge_caps.append([front_a, front_b, rear_a, rear_b])
	# Broken oblong mineral faces emerge from the continuous bedrock. They are
	# shallow, staggered and differently sized, never full-height stone posts.
	# Real silhouette relief is essential here; grain on a smooth strip still
	# looks like a cut sheet of sand, regardless of the source texture quality.
	var tangent := (b - a).normalized()
	var face_height := (top_a + top_b - bottom_a - bottom_b) * 0.5
	var left_outcrop := face_domain >= 0 and face_domain < 3
	var bands := 2 if left_outcrop else 3
	for band in range(bands):
		if random.randf() > (0.48 if left_outcrop else (0.43 if face_domain == 3 else 0.58)):
			continue
		var along := random.randf_range(0.05, 0.95)
		var fraction := clampf((band + random.randf_range(0.08, 0.84)) / float(bands), 0.08, 0.94)
		# Natural joints do not follow two/three masonry courses. Sample the
		# entire face and lean the exposed plates across the sedimentary beds.
		if left_outcrop:
			fraction = random.randf_range(0.10, 0.91)
		var point := a.lerp(b, along)
		var out := outside_a.lerp(outside_b, along).normalized()
		var low := lerpf(bottom_a, bottom_b, along)
		var high := lerpf(top_a, top_b, along)
		var projection := (1.0 - fraction) * 1.45 + random.randf_range(0.12 if left_outcrop else 0.26, 0.36 if left_outcrop else 0.49)
		var p := point + out * projection
		var center := Vector3(p.x, lerpf(low, high, fraction), p.y)
		var width := a.distance_to(b) * random.randf_range(0.65, 2.25 if left_outcrop else 1.95)
		var height := clampf(face_height / float(bands) * random.randf_range(0.40 if left_outcrop else 0.48, 1.10), 0.26, 2.0 if left_outcrop else 1.3)
		# The old wide protrusions hid most of the fractured backing and read
		# like two long retaining-wall courses. Reveal unequal upright plates,
		# keeping the same random stream, supports and total geometry budget.
		if left_outcrop:
			width *= 0.61
			height *= 1.08
		var tilt := random.randf_range(-0.48, 0.48) if left_outcrop else 0.0
		_rock(center, Vector3(width, height, random.randf_range(0.56, 1.03)),
			-atan2(tangent.y, tangent.x) + random.randf_range(-0.35, 0.35), false, false, false, tilt)

func _weathered_wall_cell(a: Vector3, b: Vector3, c: Vector3, d: Vector3,
		inside: Vector3, outside_a: Vector2, outside_b: Vector2, meta: Color, layer: int, drops: Vector4 = Vector4.ZERO) -> void:
	# Sample one continuous, irregular fracture field across ALL mesh cells.
	# The rejected inset-quad version outlined the modelling grid like masonry.
	# Shared edge positions and outward vectors now sample exactly the same field.
	var points := PackedVector3Array()
	var shifts := PackedFloat32Array()
	for row in range(3):
		var v := float(row) / 2.0
		for column in range(4):
			var u := float(column) / 3.0
			var base := a.lerp(d, u).lerp(b.lerp(c, u), v)
			var outside := outside_a.lerp(outside_b, u).normalized()
			var outward := Vector3(outside.x, 0, outside.y)
			var vertical := (float(layer) + v) / 6.0
			points.append(base + outward * _fracture_height(base) * sin(vertical * PI))
			shifts.append(lerpf(lerpf(drops.x, drops.w, u), lerpf(drops.y, drops.z, u), v))
	for row in range(2):
		for column in range(3):
			var i := row * 4 + column
			var rounding := 0.08 if face_domain >= 0 and face_domain < 3 else 0.19
			_face(points[i], points[i + 4], points[i + 1], inside, meta, Vector3.ONE, rounding, Vector3(shifts[i], shifts[i + 4], shifts[i + 1]))
			_face(points[i + 1], points[i + 4], points[i + 5], inside, meta, Vector3.ONE, rounding, Vector3(shifts[i + 1], shifts[i + 4], shifts[i + 5]))
	var out := outside_a.lerp(outside_b, 0.5).normalized()
	relief_probes.append((points[1] + points[5] + points[2]) / 3.0 + Vector3.UP * ((shifts[1] + shifts[5] + shifts[2]) / 3.0))
	relief_normals.append(Vector3(out.x, 0, out.y))

func _fracture_height(p: Vector3) -> float:
	# Unequal cellular fracture planes in physical space, warped off horizontal
	# courses. This shapes mesh vertices; it is not a painted crack/normal overlay.
	var plane := Vector2(p.x * 0.66 + p.z * 0.41, p.y * 0.92)
	var left_outcrop := face_domain >= 0 and face_domain < 3
	if left_outcrop:
		# Smaller, deeper natural fracture volumes at the preview's metre scale.
		# Only the left terrace faces change; this field displaces actual vertices
		# and hence collision, occlusion and shadows, not just image colour.
		plane = Vector2(p.x * 1.02 + p.z * 0.64, p.y * 1.30)
	plane.y += meadow._growth_noise(Vector2(plane.x * 0.41, 4.7)) * 0.63
	var cell := plane.floor()
	var nearest := INF
	var next_nearest := INF
	var mineral_id := 0.0
	for y in range(-1, 2):
		for x in range(-1, 2):
			var id := cell + Vector2(x, y)
			var jitter := Vector2(meadow._growth_hash(id + Vector2(37.1, 9.4)), meadow._growth_hash(id + Vector2(5.6, 61.8)))
			var seed_point := id + Vector2(0.12, 0.12) + jitter * 0.76
			var distance := plane.distance_to(seed_point)
			if distance < nearest:
				next_nearest = nearest
				nearest = distance
				mineral_id = jitter.x
			elif distance < next_nearest:
				next_nearest = distance
	var plate := smoothstep(0.012, 0.20, next_nearest - nearest)
	if left_outcrop:
		return 0.045 + plate * lerpf(0.28, 0.59, mineral_id)
	return 0.035 + plate * lerpf(0.12, 0.31, mineral_id)

func _build_loose_stones() -> void:
	for i in range(210):
		var p := Vector2(random.randf_range(-49.0, 50.0), random.randf_range(-87.0, 19.0))
		if not _outside_play_space(p, 3.0) or absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + 2.4:
			continue
		var radius := random.randf_range(0.13, 0.43)
		var size := Vector3(radius * 1.9, radius * 0.73, radius * random.randf_range(1.0, 1.7))
		_rock(Vector3(p.x, meadow.terrain_height_before_notch(p.x, p.y) + size.y * 0.20, p.y), size, random.randf() * TAU, false)

func _outside_play_space(p: Vector2, road_clearance: float) -> bool:
	var clearance := maxf(road_clearance, meadow.road_half_width(p.y) + 0.60)
	return meadow.distance_to_road(p) > clearance and p.distance_to(Vector2(5, -12)) > 6.2

func _rock(center: Vector3, size: Vector3, heading: float, turf: bool, column: bool = false, hero: bool = false, tilt: float = 0.0) -> void:
	# Keep each original rock rigid: lowering a face must not resize/tilt it.
	# External users of this builder already supply their own supported centres.
	var rigid_drop: float = meadow.terrace_notch_offset(center.x, center.z) if notch_source_geometry else 0.0
	var rigid_shifts := Vector3.ONE * rigid_drop
	stone_count += 1
	var sides := 19 if hero else 11
	var bedded := face_domain >= 0 and not column
	if bedded:
		bedded_rock_count += 1
	var rings: Array[PackedVector3Array] = []
	var levels := [-0.5, -0.26, 0.25, 0.5]
	var radii := [0.93, 1.0, 0.96, 0.85] if column else [0.74, 1.0, 0.94, 0.66]
	if bedded:
		radii = [0.87, 1.0, 0.97, 0.81]
	var transform := Basis(Vector3.UP, heading) * Basis(Vector3.FORWARD, tilt)
	var angles := PackedFloat32Array()
	var profile := PackedFloat32Array()
	for side in range(sides):
		angles.append(TAU * side / sides + random.randf_range(-0.16, 0.16) * (0.4 if hero else 1.0))
		profile.append(lerpf(1.0, random.randf_range(0.68, 1.22), 0.42 if hero else 1.0))
	for ring in range(4):
		var points := PackedVector3Array()
		for side in range(sides):
			var a := angles[side]
			var r: float = radii[ring] * profile[side] * random.randf_range(0.85, 1.12)
			if hero:
				r = lerpf(radii[ring] * profile[side], r, 0.35)
			var jitter := 0.045 if hero else (0.065 if column else 0.12)
			var local := Vector3(cos(a) * size.x * 0.5 * r, (levels[ring] + random.randf_range(-jitter, jitter)) * size.y, sin(a) * size.z * 0.5 * r)
			if bedded:
				# Broader chipped planes, not ellipsoidal pebbles stretched sideways.
				# Reuse the same random samples so this art change cannot reshuffle
				# the meadow, river stones or later vegetation distributions.
				var radius_variation: float = r / (radii[ring] * profile[side])
				var plane_radius: float = radii[ring] * lerpf(1.0, profile[side], 0.46) * lerpf(1.0, radius_variation, 0.24)
				local.x = signf(cos(a)) * pow(absf(cos(a)), 0.55) * size.x * 0.5 * plane_radius
				local.z = signf(sin(a)) * pow(absf(sin(a)), 0.55) * size.z * 0.5 * plane_radius
				var sampled_jitter := local.y / size.y - float(levels[ring])
				var chipped_bed := (profile[side] - 0.95) * 0.14
				local.y = (float(levels[ring]) + chipped_bed + sampled_jitter * 0.30) * size.y
			points.append(center + transform * local)
		rings.append(points)
	var tone := random.randf_range(0.66, 1.08)
	var meta := Color(1.0 if turf else 0.0, lerpf(1.0, tone, 0.28) if hero else tone, random.randf(), 0.4 if hero else 1.0)
	var normal_scale := Vector3(1.0 / maxf(size.x * size.x, 0.01),
		1.0 / maxf(size.y * size.y, 0.01), 1.0 / maxf(size.z * size.z, 0.01))
	var worn_edge := 0.68 if hero else (0.16 if bedded else 0.48)
	for ring in range(3):
		for side in range(sides):
			var next := (side + 1) % sides
			_face(rings[ring][side], rings[ring + 1][side], rings[ring][next], center, meta, normal_scale, worn_edge, rigid_shifts)
			_face(rings[ring][next], rings[ring + 1][side], rings[ring + 1][next], center, meta, normal_scale, worn_edge, rigid_shifts)
	for side in range(sides):
		_face(rings[3][side], center + Vector3.UP * size.y * 0.53, rings[3][(side + 1) % sides], center, meta, normal_scale, worn_edge, rigid_shifts)

func _face(a: Vector3, b: Vector3, c: Vector3, center: Vector3, color: Color,
		normal_scale: Vector3 = Vector3.ONE, rounded_weight: float = 0.18, shifts: Vector3 = Vector3.ZERO) -> void:
	var normal := (b - a).cross(c - a).normalized()
	var middle := (a + b + c) / 3.0
	if normal.dot(middle - center) < 0.0:
		normal = -normal
		var swap := b
		b = c
		c = swap
		shifts = Vector3(shifts.x, shifts.z, shifts.y)
	if shifts != Vector3.ZERO:
		# Original winding is fixed BEFORE deformation; never hide a folded face
		# by asking the displaced inside point to choose a new vertex order.
		a.y += shifts.x
		b.y += shifts.y
		c.y += shifts.z
		var deformed_normal := (b - a).cross(c - a).normalized()
		assert(deformed_normal.dot(normal) > 0.0, "Notch must preserve original face orientation")
		normal = deformed_normal
		center.y += (shifts.x + shifts.y + shifts.z) / 3.0
	var mapped_face := face_domain >= 0
	if face_domain >= 0 and face_domain < 3:
		var shelf: Vector4 = meadow.TERRACES[face_domain]
		var span: Vector2 = FACE_SPANS[face_domain]
		mapped_face = middle.z >= shelf.y and middle.x >= span.x and middle.x <= span.y
	# Godot's front faces use clockwise winding.
	for p in [a, c, b]:
		vertices.append(p)
		# Ellipsoid-aware weathering normals retain the silhouette and collision,
		# without lighting every triangle like a separate low-poly shard. A simple
		# spherical normal would be wrong for our long, shallow limestone blocks.
		var rounded: Vector3 = ((p - center) * normal_scale).normalized()
		normals.append((normal * (1.0 - rounded_weight) + rounded * rounded_weight).normalized())
		colors.append(color)
		uv.append(_rock_surface_uv(p) if mapped_face else Vector2(-1, -1))
		# Turf-bearing rock lips share the ground's pigment field. This is baked
		# once, not an extra runtime noise calculation for every visible pixel.
		var density: float = meadow.growth_density(Vector2(p.x, p.z)) if color.r > 0.5 else 0.0
		var soil_backing := 0.0
		if color.r > 0.5:
			var ground_point := Vector2(p.x, p.z)
			var boundary := Geometry2D.get_closest_point_to_segment(ground_point, face_start, face_end)
			soil_backing = clampf((ground_point.distance_to(boundary) - 0.35) / 1.20, 0.0, 1.0)
		growth_fields.append(Vector2(density, soil_backing))

func _rock_surface_uv(p: Vector3) -> Vector2:
	if face_domain < 0:
		return Vector2(-1, -1)
	var along: float
	if face_domain < 3:
		var span: Vector2 = FACE_SPANS[face_domain]
		# Fit the visible mineral face, not the full half-ellipse circumference;
		# the latter stretched each painted block into a long horizontal plank.
		along = inverse_lerp(span.x, span.y, p.x)
	else:
		along = inverse_lerp(-34.0, 31.52, p.x)
	var tangent := face_end - face_start
	var t := clampf((Vector2(p.x, p.z) - face_start).dot(tangent) / maxf(tangent.length_squared(), 0.001), 0.0, 1.0)
	var bottom := lerpf(face_low.x, face_low.y, t)
	var top := lerpf(face_high.x, face_high.y, t)
	var down := 1.0 - clampf((p.y - bottom) / maxf(top - bottom, 0.1), 0.0, 1.0)
	var region: Rect2 = FACE_CROPS[face_domain]
	# A strip progresses once around one front-facing escarpment. No modulo,
	# tiling, copied cards or separate floating painted slab is involved.
	return (region.position + Vector2(clampf(along, 0.002, 0.998), down) * region.size) / Vector2(2172, 724)

func _build_living_meadow() -> void:
	for i in range(118000):
		var z := 22.0 - pow(random.randf(), 1.75) * 115.0
		var half_width := 20.0 + (22.0 - z) * 0.52
		var x := random.randf_range(-half_width, half_width)
		var p := Vector2(x, z)
		var river_clearance := absf(x - meadow.river_center(z)) - float(meadow.river_half_width(z))
		var arena := p.distance_to(Vector2(5, -12)) < 6.2
		if river_clearance < 1.45 or meadow.distance_to_road(p) < meadow.road_half_width(z) + 0.25:
			continue
		var density: float = meadow.growth_density(p)
		var cover := smoothstep(0.30, 0.74, density)
		if random.randf() > 0.035 + pow(cover, 1.4) * 0.72:
			continue
		var normal: Vector3 = meadow.terrain_normal(x, z)
		if normal.y < 0.89 or meadow.below_river_surface(x, z, meadow.terrain_height(x, z)):
			continue
		var root := Vector3(x, meadow.terrain_height(x, z) - 0.025, z)
		var height := random.randf_range(0.04, 0.16) * (0.55 + cover * 0.75)
		var width := random.randf_range(0.020, 0.060)
		if arena:
			# Tiny ankle-clear groundcover, not a bare circular golf green. This
			# geometry has no collision and never changes the flat combat surface.
			height *= 0.24
			width *= 0.65
		var angle := random.randf() * TAU
		var spread := Vector3(cos(angle), 0, sin(angle))
		var bend := Vector3(sin(angle) * 0.24, 0, cos(angle) * 0.24) * height
		var tint := random.randf_range(0.78, 1.05)
		if random.randf() < 0.14:
			# Broad leaves are local accents, not a uniform half-metre-leaf carpet.
			width *= 1.35
			height *= 0.80
		_blade(root, spread, bend, height, width, tint, normal)
		if cover < 0.25:
			sparse_blades += 1
		elif cover > 0.75:
			dense_blades += 1
		if density > 0.66 and random.randf() < 0.023:
			_flower(root + Vector3.UP * height * 0.90, random.randf_range(0.055, 0.09))

func _blade(root: Vector3, spread: Vector3, bend: Vector3, height: float, width: float, tint: float, surface_normal: Vector3, broad_frond: bool = false) -> void:
	leaf_count += 1
	leaf_density = meadow.growth_density(Vector2(root.x, root.z))
	var normal := (surface_normal * 0.80 + Vector3(spread.z, 0.2, -spread.x) * 0.25).normalized()
	for row in range(3):
		var low := row / 3.0
		var high := (row + 1.0) / 3.0
		var a := root + Vector3.UP * height * low + bend * low * low
		var b := root + Vector3.UP * height * high + bend * high * high
		var wa := width * (1.0 - low * 0.88)
		var wb := width * (1.0 - high)
		var lower_normal := normal
		var upper_normal := normal
		if broad_frond:
			# One smoothly bending normal field per broad frond. The old nearly
			# vertical normal lit every leaf in a cushion as the same flat lawn.
			var lower_plane := spread.cross(Vector3.UP * height + bend * 2.0 * low).normalized()
			var upper_plane := spread.cross(Vector3.UP * height + bend * 2.0 * high).normalized()
			if lower_plane.y < 0.0:
				lower_plane = -lower_plane
			if upper_plane.y < 0.0:
				upper_plane = -upper_plane
			lower_normal = (surface_normal * 0.55 + lower_plane * 0.45).normalized()
			upper_normal = (surface_normal * 0.55 + upper_plane * 0.45).normalized()
		_leaf_vertex(a - spread * wa, lower_normal, tint * (0.62 + low * 0.38), low)
		_leaf_vertex(b - spread * wb, upper_normal, tint * (0.62 + high * 0.38), high)
		_leaf_vertex(a + spread * wa, lower_normal, tint * (0.62 + low * 0.38), low)
		if row < 2:
			# The final blade tip has zero width; its second triangle had no area.
			# Omit that redundant submission without changing the silhouette.
			_leaf_vertex(a + spread * wa, lower_normal, tint * (0.62 + low * 0.38), low)
			_leaf_vertex(b - spread * wb, upper_normal, tint * (0.62 + high * 0.38), high)
			_leaf_vertex(b + spread * wb, upper_normal, tint * (0.62 + high * 0.38), high)

func _build_fern_colonies() -> void:
	# Larger low-growing leaf sprays connect isolated painted props to the carpet.
	# Every spray has unique geometry; paths and the whole Boss clearing stay open.
	var centers := [Vector2(-18, -19), Vector2(-33, -28), Vector2(-9, -52),
		Vector2(19, -20), Vector2(40, -42), Vector2(-14, 5), Vector2(11, 14),
		Vector2(-27, -49), Vector2(-2, -88), Vector2(36, -69), Vector2(-48, -65)]
	for i in range(1900):
		var center: Vector2 = centers[i % centers.size()]
		var angle := random.randf() * TAU
		var radius := sqrt(random.randf()) * random.randf_range(3.0, 7.8)
		var p := center + Vector2(cos(angle), sin(angle)) * radius
		if random.randf() > smoothstep(0.28, 0.70, meadow.growth_density(p)):
			continue
		if not _outside_play_space(p, 3.1):
			continue
		if absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + 1.8:
			continue
		var n: Vector3 = meadow.terrain_normal(p.x, p.y)
		if n.y < 0.89 or meadow.below_river_surface(p.x, p.y, meadow.terrain_height(p.x, p.y)):
			continue
		var root := Vector3(p.x, meadow.terrain_height(p.x, p.y) - 0.04, p.y)
		var height := random.randf_range(0.20, 0.43)
		var tone := random.randf_range(0.65, 1.06)
		var count := random.randi_range(5, 9)
		for leaf in range(count):
			var heading := angle + TAU * leaf / count + random.randf_range(-0.3, 0.3)
			var outward := Vector3(cos(heading), 0, sin(heading))
			var spread := Vector3(-outward.z, 0, outward.x)
			_blade(root, spread, outward * height * random.randf_range(0.4, 1.1),
				height * random.randf_range(0.6, 1.15), random.randf_range(0.075, 0.14), tone, n)

func _build_creeping_colonies(surface_queries: Array[TriangleMesh], query_ceiling: float) -> void:
	# Redistribute the existing leaf budget into the transition from taller art
	# plants / rock toes to low meadow. Roots are still individually ray planted;
	# these guides never raise or flatten the ground and are not image instances.
	random.seed = 630906
	for label: String in ["OakOnLowerOutcrop", "OldOakOnShelf", "HazelAboveLimestone",
		"DeepValleyHawthorn", "FloweredTerraceToe", "MeadowColony_00", "MeadowColony_01",
		"MeadowColony_02", "MeadowColony_03", "FernAndStone", "RiverRoseThicket",
		"LowBrambleEdge", "HeatherAndRoot", "TerraceHeather", "FernRiverGroup"]:
		var plant: MeshInstance3D = meadow.get_node(NodePath(label))
		var foot: Vector2 = plant.get_meta("groundcover_sampling_foot", plant.get_meta("art_foot"))
		var width: float = plant.get_meta("art_width")
		ecotone_guides.append(Vector4(foot.x, foot.y + 0.8, clampf(width * 0.62, 2.3, 5.8), clampf(width * 0.33, 1.7, 3.6)))
	# Short, broken links between already adjacent unique art colonies, not a
	# repeated shrub strip. Individual roots still pass road/river/surface checks.
	var link_pairs := [["HeatherAndRoot", "MeadowColony_02"], ["TerraceHeather", "MeadowColony_02"],
		["LowBrambleEdge", "MeadowColony_02"], ["HazelAboveLimestone", "FloweredTerraceToe"],
		["FloweredTerraceToe", "MeadowColony_01"], ["DeepValleyHawthorn", "MeadowColony_01"]]
	for pair: Array in link_pairs:
		var a: Vector2 = meadow.get_node(NodePath(pair[0])).get_meta("art_foot")
		var b: Vector2 = meadow.get_node(NodePath(pair[1])).get_meta("art_foot")
		var across := Vector2(-(b - a).y, (b - a).x).normalized()
		for t: float in [0.33, 0.67]:
			var point := a.lerp(b, t) + across * sin(t * PI) * 0.65
			if not _outside_play_space(point, 3.2):
				continue
			var link := Vector4(point.x, point.y, 3.4, 2.6)
			ecotone_guides.append(link)
			ecotone_links.append(link)
	for shelf in range(3):
		for sample in range(22):
			var angle := TAU * (float(sample) + random.randf_range(-0.3, 0.3)) / 22.0
			var p: Vector2 = meadow.terrace_boundary(shelf, angle)
			if p.x < -70.0 or p.y < -86.0 or random.randf() < 0.30:
				continue
			# Unequal pockets, not a continuous green ribbon over the stone face.
			p += _shelf_outside(shelf, angle) * random.randf_range(1.3, 3.1)
			ecotone_guides.append(Vector4(p.x, p.y, random.randf_range(2.4, 4.8), random.randf_range(1.5, 3.2)))
	# Concentrate part of the former isolated background sprays into a broken
	# foreground apron. The physical cliff stays visible between unequal pockets.
	var rim_x := [-30.0, -25.0, -19.0, -13.0, -7.0, 0.0, 7.0, 14.0]
	for i in range(rim_x.size()):
		var x: float = rim_x[i]
		var z: float = meadow.foreground_edge(x) - 2.1 - 0.55 * sin(float(i) * 1.7)
		var guide := Vector4(x, z, 3.0 + 0.65 * sin(float(i) * 2.3), 1.8 + 0.25 * cos(float(i)))
		ecotone_guides.append(guide)
		foreground_growth_guides.append(guide)
	for i in range(2100):
		var z := 18.0 - pow(random.randf(), 1.45) * 129.0
		var half_width := 22.0 + (18.0 - z) * 0.48
		var p := Vector2(random.randf_range(-half_width, half_width), z)
		var transition := i < 1840
		var envelope := 0.0
		if transition:
			var guide: Vector4 = ecotone_guides[i % ecotone_guides.size()]
			var theta := random.randf() * TAU
			var reach := sqrt(random.randf())
			var broken_edge := 0.86 + 0.18 * sin(theta * 3.0 + float(i % ecotone_guides.size()))
			p = Vector2(guide.x, guide.y) + Vector2(cos(theta) * guide.z, sin(theta) * guide.w) * reach * broken_edge
			envelope = 1.0 - smoothstep(0.15, 1.05, reach)
		if not _outside_play_space(p, 3.2):
			continue
		if absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + 2.2:
			continue
		var density: float = meadow.growth_density(p)
		var acceptance := lerpf(0.38, 0.94, envelope) if transition else smoothstep(0.42, 0.77, density)
		if random.randf() > acceptance:
			continue
		var n: Vector3 = meadow.terrain_normal(p.x, p.y)
		if n.y < (0.73 if transition else 0.93):
			continue
		var root := Vector3(p.x, meadow.terrain_height(p.x, p.y), p.y)
		var radius := random.randf_range(0.82, 1.65) if transition else random.randf_range(1.00, 2.40)
		var heading := random.randf() * TAU
		var stretch := random.randf_range(1.20, 2.10)
		var count := random.randi_range(15, 22) if transition else random.randi_range(30, 48)
		var tone := random.randf_range(0.71, 1.04)
		for leaf in range(count):
			var angle := random.randf() * TAU
			var distance := sqrt(random.randf()) * radius
			# Unequal fingers overlap adjacent patches, not identical round mounds.
			var lobe := 0.78 + 0.18 * sin(angle * 3.0 + heading) + 0.13 * sin(angle * 5.0 - heading)
			var footprint := Vector2(cos(angle) * stretch, sin(angle) / sqrt(stretch)) * distance * lobe
			footprint = footprint.rotated(heading)
			var offset := Vector3(footprint.x, 0, footprint.y)
			var ground_point := Vector2(root.x + offset.x, root.z + offset.z)
			if not _outside_play_space(ground_point, 3.2):
				continue
			if meadow.distance_to_road(ground_point) < meadow.road_half_width(ground_point.y) + 0.90:
				continue
			if absf(ground_point.x - meadow.river_center(ground_point.y)) < meadow.river_half_width(ground_point.y) + 1.8:
				continue
			if not transition and meadow.growth_density(ground_point) < 0.44:
				continue
			# Query the exact visible surface at EACH root. The old tangent plane
			# plus a raised spherical mound floated above undulating ground.
			var surface_y := -INF
			var surface_normal := Vector3.UP
			for query: TriangleMesh in surface_queries:
				var hit := query.intersect_ray(Vector3(ground_point.x, query_ceiling, ground_point.y), Vector3.DOWN)
				if not hit.is_empty() and hit.position.y > surface_y:
					surface_y = hit.position.y
					surface_normal = hit.normal
			if not is_finite(surface_y) or meadow.below_river_surface(ground_point.x, ground_point.y, surface_y) or surface_normal.y < 0.78:
				continue
			var leaf_root := Vector3(ground_point.x, surface_y + 0.006, ground_point.y)
			creeping_anchors.append(leaf_root)
			var direction := Vector3(cos(angle + 0.6), 0.0, sin(angle + 0.6))
			# Taller leaves at the centre make a real low cushion. Every root
			# remains on its queried triangle; never lift a whole planted patch.
			var centre_growth := 1.0 - smoothstep(0.20, 1.0, distance / radius)
			var stature := pow(envelope, 0.60) * lerpf(0.45, 1.0, centre_growth) if transition else centre_growth * 0.22
			var height := lerpf(0.08, 0.90, stature) * random.randf_range(0.85, 1.08)
			if transition:
				ecotone_anchors.append(leaf_root)
				ecotone_heights.append(Vector2(envelope, height))
				# A common rooted crown with unequal curved fronds, not one upright
				# giant leaf or a floating opaque dome. More connected roots support
				# 2–3 broader fronds within the existing low-cover triangle budget.
				var fronds := random.randi_range(2, 3)
				for frond in range(fronds):
					var heading_leaf := angle + TAU * float(frond) / fronds + random.randf_range(-0.24, 0.24)
					var outward := Vector3(cos(heading_leaf), 0, sin(heading_leaf))
					var frond_height := height * random.randf_range(0.68, 1.0)
					if frond % 3 == 0:
						_blade(leaf_root, Vector3(-outward.z, 0, outward.x), outward * frond_height * random.randf_range(0.55, 0.95),
							frond_height, random.randf_range(0.065, 0.13), tone * 0.92, surface_normal, true)
					else:
						outward.y = -(surface_normal.x * outward.x + surface_normal.z * outward.z) / surface_normal.y
						_oval_leaf(leaf_root, outward * frond_height * 0.90 + Vector3.UP * frond_height * 0.85,
							random.randf_range(0.095, 0.19), tone * 0.94, true)
			else:
				var length_m := random.randf_range(0.20, 0.39) * lerpf(1.0, 1.40, stature)
				direction.y = -(surface_normal.x * direction.x + surface_normal.z * direction.z) / surface_normal.y
				_oval_leaf(leaf_root, direction * length_m + Vector3.UP * height,
					random.randf_range(0.060, 0.125) * lerpf(1.0, 1.18, stature), tone * random.randf_range(0.94, 1.06))
			if leaf % 29 == 0 and density > 0.67:
				_flower(leaf_root + Vector3.UP * 0.09, random.randf_range(0.05, 0.075))
	print("MEADOW_ECOTONE_READY: %d irregular prop/rock guides; %d supported transition roots; %d total low-cover roots" % [ecotone_guides.size(), ecotone_anchors.size(), creeping_anchors.size()])

func _build_ledge_growth(surface_queries: Array[TriangleMesh], query_ceiling: float) -> void:
	# Barycentric anchors on the exact solid cap triangles, including the near rim.
	# No floating leaf fringe guessed from a separate ellipse or height offset.
	for cap: Array in ledge_caps:
		var middle: Vector3 = (cap[0] + cap[1]) * 0.5
		var p := Vector2(middle.x, middle.z)
		if not _outside_play_space(p, 3.2):
			continue
		var density: float = meadow.growth_density(p)
		if random.randf() > smoothstep(0.32, 0.76, density) * 0.84:
			continue
		ledge_sprays += 1
		var outward: Vector3 = ((cap[0] + cap[1]) - (cap[2] + cap[3])).normalized()
		var tone := random.randf_range(0.73, 1.03)
		for leaf in range(random.randi_range(14, 28)):
			var t := random.randf()
			var depth := random.randf_range(0.04, 0.42)
			var q: Vector3
			if t + depth <= 1.0:
				q = cap[0] * (1.0 - t - depth) + cap[1] * t + cap[2] * depth
			else:
				q = cap[1] * (1.0 - depth) + cap[2] * (1.0 - t) + cap[3] * (t + depth - 1.0)
			if not _outside_play_space(Vector2(q.x, q.z), 3.2):
				continue
			# Start above both complete meshes, never inside a decorative rock.
			var surface_y := -INF
			var surface_normal := Vector3.UP
			for query: TriangleMesh in surface_queries:
				var hit := query.intersect_ray(Vector3(q.x, query_ceiling, q.z), Vector3.DOWN)
				if not hit.is_empty() and hit.position.y > surface_y:
					surface_y = hit.position.y
					surface_normal = hit.normal
			assert(is_finite(surface_y), "A planted cap must intersect its own solid geometry")
			if surface_normal.y < 0.55:
				continue
			q.y = surface_y + 0.006
			cap_anchors.append(q)
			var direction := outward.rotated(Vector3.UP, random.randf_range(-1.2, 1.2))
			direction.y = random.randf_range(-0.24, 0.12)
			_oval_leaf(q, direction * random.randf_range(0.22, 0.51), random.randf_range(0.055, 0.11), tone)

func _oval_leaf(root: Vector3, length: Vector3, width: float, tone: float, broad_frond: bool = false) -> void:
	leaf_count += 1
	leaf_density = meadow.growth_density(Vector2(root.x, root.z))
	var side := Vector3(-length.z, 0, length.x).normalized() * width
	var ridge := root + length * 0.46 + Vector3.UP * width * 0.34
	var outline := [root, root + length * 0.30 - side, root + length * 0.72 - side * 0.83,
		root + length, root + length * 0.72 + side * 0.83, root + length * 0.30 + side]
	for i in range(outline.size()):
		var a: Vector3 = outline[i]
		var b: Vector3 = outline[(i + 1) % outline.size()]
		# Shared curved normals remove the six independently lit triangular
		# facets. Keep the actual silhouette/ridge, roots and low wind movement.
		var axis := (Vector3.UP - length.normalized() * 0.16).normalized()
		if broad_frond:
			var leaf_plane := side.cross(length).normalized()
			if leaf_plane.y < 0.0:
				leaf_plane = -leaf_plane
			axis = axis.lerp(leaf_plane, 0.72).normalized()
		var normal_a := (axis + (a - ridge).normalized() * 0.16).normalized()
		var normal_b := (axis + (b - ridge).normalized() * 0.16).normalized()
		var coherent_tone := lerpf(0.88, tone, 0.42)
		_leaf_vertex(a, normal_a, coherent_tone * 0.94, 0.0 if i == 0 else 0.65)
		_leaf_vertex(ridge, axis, coherent_tone * 1.01, 1.0)
		_leaf_vertex(b, normal_b, coherent_tone * 0.94, 0.0 if i == outline.size() - 1 else 0.65)

func _leaf_vertex(p: Vector3, normal: Vector3, tone: float, tip: float) -> void:
	vertices.append(p)
	normals.append(normal)
	colors.append(Color(tone, tone, tone, tip))
	uv.append(Vector2(p.x, p.z))
	growth_fields.append(Vector2(leaf_density, 0.0))

func _flower(center: Vector3, radius: float) -> void:
	var density: float = meadow.growth_density(Vector2(center.x, center.z))
	for i in range(5):
		var a := TAU * i / 5.0
		var b := TAU * (i + 0.74) / 5.0
		for p in [center, center + Vector3(cos(a), 0, sin(a)) * radius, center + Vector3(cos(b), 0, sin(b)) * radius]:
			vertices.append(p)
			normals.append(Vector3.UP)
			colors.append(Color(1.0, 0.95, 0.72, 0.6))
			uv.append(Vector2(-999, -999))
			growth_fields.append(Vector2(density, 0.0))

func _publish(label: String, material: Material, shadows: bool) -> MeshInstance3D:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_COLOR] = colors
	arrays[Mesh.ARRAY_TEX_UV] = uv
	if not growth_fields.is_empty():
		assert(growth_fields.size() == vertices.size(), "Every leaf must carry the shared ground-colour field")
		arrays[Mesh.ARRAY_TEX_UV2] = growth_fields
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var instance := MeshInstance3D.new()
	instance.name = label
	instance.mesh = mesh
	instance.material_override = material
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED if shadows else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	meadow.add_child(instance)
	return instance

func _clear_arrays() -> void:
	vertices = PackedVector3Array()
	normals = PackedVector3Array()
	colors = PackedColorArray()
	uv = PackedVector2Array()
	growth_fields = PackedVector2Array()
