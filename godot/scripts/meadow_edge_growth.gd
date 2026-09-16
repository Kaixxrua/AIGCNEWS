extends Node3D
## Irregular low, rooted leaf sprays connect established crowns to short turf.
## Separate additive geometry: never rewrites the five frozen world bundles.
const BRUSH = preload("res://scripts/meadow_middle_brush.gd")
const GEOMETRY = preload("res://scripts/meadow_branch_geometry.gd")
const LEAVES = preload("res://shaders/meadow_leaves.gdshader")
const TURF = preload("res://assets/materials/meadow-sward-v60.png")
const RADIUS := 0.75
const WIND_RESERVE := 0.06
const CANDIDATES := 140
var ready_complete := false
var meadow: Node3D
var land: TriangleMesh
var rocks: TriangleMesh

func _ready() -> void:
	meadow = get_parent()
	# Child-ready happens before the parent constructs its cached world. Build
	# synchronously on parent-ready, before first draw, not on a later timer.
	if meadow.is_node_ready():
		_build()
	else:
		meadow.ready.connect(_build, CONNECT_ONE_SHOT)

func _build() -> void:
	var started := Time.get_ticks_msec()
	land = meadow.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	rocks = meadow.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var geometry := GEOMETRY.new()
	geometry.scene = meadow
	var random := RandomNumberGenerator.new()
	var roots := PackedVector3Array()
	var patches := PackedInt32Array()
	var ranges := PackedVector2Array()
	var reaches := PackedFloat32Array()
	var counts := PackedInt32Array()
	var occupied := {}
	for patch in range(BRUSH.GUIDES.size()):
		random.seed = 910733 + patch * 701
		var guide: Vector4 = BRUSH.GUIDES[patch]
		var count := 0
		for candidate in range(CANDIDATES):
			var angle := random.randf() * TAU
			var reach := sqrt(lerpf(0.52 * 0.52, 1.48 * 1.48, random.randf()))
			var edge := 1.0 - smoothstep(0.80, 1.48, reach)
			# Follow each original uneven crown footprint, but break its rim into
			# loose lobes and gaps. There is no continuous ring or opaque skirt.
			var lobe := 0.76 + 0.16 * sin(angle * 3.0 + patch * 1.47) + 0.08 * sin(angle * 7.0 - patch)
			var broken := 0.68 + 0.32 * sin(angle * 4.3 + patch * 2.1)
			if random.randf() > (0.24 + edge * 0.54) * broken:
				continue
			var p := Vector2(guide.x, guide.y) + Vector2(cos(angle) * guide.z, sin(angle) * guide.w) * reach * lobe
			if not _safe(p, RADIUS + WIND_RESERVE):
				continue
			var cell := Vector2i(floori(p.x / 0.38), floori(p.y / 0.38))
			if occupied.has(cell):
				continue
			var hit := _surface(p)
			if hit.is_empty() or hit.normal.y < 0.82 or meadow.below_river_surface(p.x, p.y, hit.position.y):
				continue
			# Reject steep unsupported overhangs instead of floating an entire
			# low spray across a ledge. Individual blades still stand above soil.
			var supported := true
			for offset: Vector2 in [Vector2(0.48, 0), Vector2(-0.48, 0), Vector2(0, 0.48), Vector2(0, -0.48)]:
				var neighbor := _surface(p + offset)
				if neighbor.is_empty() or absf(neighbor.position.y - hit.position.y) > 0.26:
					supported = false
					break
			if not supported:
				continue
			var root: Vector3 = hit.position + Vector3.UP * 0.006
			var first: int = geometry.vertices.size()
			var leaf_count := 4 + (candidate % 2)
			var tone := random.randf_range(0.92, 1.06) * lerpf(1.06, 0.96, edge)
			for leaf in range(leaf_count):
				var heading := angle + float(leaf) * 2.39996 + random.randf_range(-0.42, 0.42)
				var span := lerpf(0.24, 0.62, edge) * random.randf_range(0.72, 1.10)
				var rise := lerpf(0.09, 0.31, edge) * random.randf_range(0.70, 1.12)
				var length := Vector3(cos(heading) * span, rise, sin(heading) * span)
				var width := span * random.randf_range(0.19, 0.30)
				geometry.leaf(root, length, width, tone)
			roots.append(root)
			patches.append(patch)
			ranges.append(Vector2(first, geometry.vertices.size() - first))
			reaches.append(reach)
			occupied[cell] = true
			count += 1
		counts.append(count)
	var material := ShaderMaterial.new()
	material.shader = LEAVES
	material.set_shader_parameter("meadow_texture", TURF)
	material.set_shader_parameter("middle_scrub", true)
	var fringe := MeshInstance3D.new()
	fringe.name = "CrownToTurfFringe"
	fringe.mesh = geometry.mesh()
	fringe.material_override = material
	fringe.layers = 8
	fringe.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
	fringe.set_meta("roots", roots)
	fringe.set_meta("patches", patches)
	fringe.set_meta("ranges", ranges)
	fringe.set_meta("reaches", reaches)
	fringe.set_meta("patch_counts", counts)
	add_child(fringe)
	var elapsed := Time.get_ticks_msec() - started
	fringe.set_meta("build_ms", elapsed)
	_build_branchlets(roots, geometry.vertices.size())
	land = null
	rocks = null
	ready_complete = true
	print("MEADOW_EDGE_GROWTH: %d rooted sprays; patches %s; %d triangles; one extra batch; build_ms=%d; original crowns and terrain unchanged" % [roots.size(), counts, geometry.vertices.size() / 3, elapsed])

func _build_branchlets(low_roots: PackedVector3Array, low_vertices: int) -> void:
	# v93 additive protocol branchlets-93-1; the complete v91 fringe above is intact.
	# Each unindexed root range: twig(root,joint) 12 verts, twig(joint,tip) 12,
	# then 3 groups * 2 leaves, each GEOMETRY.leaf = 18 verts/6 triangles.
	# Per plant: 132 corners / 44 triangles. Twig UV=(-2000,0), wind=0;
	# leaves use world-XZ UV, two base corners wind=0, six ridge corners wind=1,
	# other outline corners wind=.65; authored upward normals, clockwise faces.
	# roots/joints/tips/ranges/patches/reaches/heights/group_counts are per-root.
	# leaf_group_ranges (36 corners), leaf_group_plant_indices, leaf_group_bases
	# describe the three ordered tiers; group_counts is always 3 in this candidate.
	# leaf_ranges/leaf_attachments/leaf_root_indices are parallel per-blade arrays;
	# each consecutive pair shares a point on a finite twig centerline, below tip.
	var started := Time.get_ticks_msec()
	var geometry := GEOMETRY.new()
	geometry.scene = meadow
	var random := RandomNumberGenerator.new()
	random.seed = 930733
	var guide: Vector4 = BRUSH.GUIDES[9]
	var roots := PackedVector3Array()
	var joints := PackedVector3Array()
	var tips := PackedVector3Array()
	var ranges := PackedVector2Array()
	var reaches := PackedFloat32Array()
	var heights := PackedFloat32Array()
	var patches := PackedInt32Array()
	var group_counts := PackedInt32Array()
	var leaf_group_ranges := PackedVector2Array()
	var leaf_group_plant_indices := PackedInt32Array()
	var leaf_group_bases := PackedVector3Array()
	var leaf_ranges := PackedVector2Array()
	var leaf_attachments := PackedVector3Array()
	var leaf_root_indices := PackedInt32Array()
	for candidate in range(900):
		if roots.size() >= 42:
			break
		var angle := random.randf() * TAU
		var reach := sqrt(lerpf(0.72 * 0.72, 1.34 * 1.34, random.randf()))
		var near_crown := 1.0 - smoothstep(0.76, 1.34, reach)
		var lobe := 0.76 + 0.16 * sin(angle * 3.0 + 9.0 * 1.47) + 0.08 * sin(angle * 7.0 - 9.0)
		var p := Vector2(guide.x, guide.y) + Vector2(cos(angle) * guide.z, sin(angle) * guide.w) * reach * lobe
		# Discontinuous groups beside the old crown; sparse outer stems stay short.
		var gaps := smoothstep(-0.15, 0.60, cos(angle * 3.0 - 4.2) + 0.40 * sin(angle * 5.0 + 0.8))
		if random.randf() > (0.16 + 0.55 * near_crown) * gaps or not _safe(p, RADIUS + WIND_RESERVE):
			continue
		var spaced := true
		for other: Vector3 in roots:
			if p.distance_to(Vector2(other.x, other.z)) < 0.58:
				spaced = false
				break
		for other: Vector3 in low_roots:
			if p.distance_to(Vector2(other.x, other.z)) < 0.20:
				spaced = false
				break
		if not spaced:
			continue
		var hit := _surface(p)
		if hit.is_empty() or hit.normal.y < 0.82 or meadow.below_river_surface(p.x, p.y, hit.position.y):
			continue
		var supported := true
		for offset: Vector2 in [Vector2(0.48, 0), Vector2(-0.48, 0), Vector2(0, 0.48), Vector2(0, -0.48)]:
			var neighbor := _surface(p + offset)
			if neighbor.is_empty() or absf(neighbor.position.y - hit.position.y) > 0.26:
				supported = false
				break
		if not supported:
			continue
		var root: Vector3 = hit.position + Vector3.UP * 0.006
		var height := clampf(lerpf(0.25, 0.65, near_crown) * random.randf_range(0.92, 1.04), 0.25, 0.65)
		var heading := random.randf() * TAU
		var lean := Vector3(cos(heading), 0, sin(heading)) * height * random.randf_range(0.06, 0.14)
		var joint := root + Vector3.UP * height * 0.52 + lean * 0.30
		var tip := root + Vector3.UP * height + lean
		var tone := random.randf_range(0.84, 0.94)
		var first: int = geometry.vertices.size()
		geometry.twig(root, joint, lerpf(0.006, 0.010, near_crown), tone)
		geometry.twig(joint, tip, lerpf(0.0035, 0.006, near_crown), tone)
		var groups := 3
		for group in range(groups):
			var tier := 0.22 + 0.65 * float(group) / float(groups - 1) + random.randf_range(-0.025, 0.025)
			var attachment := root.lerp(joint, tier / 0.52) if tier <= 0.52 else joint.lerp(tip, (tier - 0.52) / 0.48)
			var direction := heading + float(group) * 2.39996 + random.randf_range(-0.25, 0.25)
			var size := random.randf_range(0.22, 0.30) * lerpf(1.0, 0.88, tier)
			var group_first: int = geometry.vertices.size()
			for blade in range(2):
				var yaw: float = [-0.50, 0.50][blade]
				var blade_scale: float = [1.0, 0.86][blade]
				var length := Vector3(cos(direction + yaw), random.randf_range(0.20, 0.48), sin(direction + yaw)).normalized() * clampf(size * blade_scale, 0.16, 0.32)
				var width := length.length() * random.randf_range(0.22, 0.28)
				var leaf_first: int = geometry.vertices.size()
				geometry.leaf(attachment, length, width, tone)
				leaf_ranges.append(Vector2(leaf_first, 18))
				leaf_attachments.append(attachment)
				leaf_root_indices.append(roots.size())
			leaf_group_ranges.append(Vector2(group_first, 36))
			leaf_group_plant_indices.append(roots.size())
			leaf_group_bases.append(attachment)
		for i in range(first, geometry.vertices.size()):
			var offset: Vector3 = geometry.vertices[i] - root
			assert(Vector2(offset.x, offset.z).length() <= RADIUS, "Branchlets must retain the .75m radius plus .06m wind reserve")
		roots.append(root)
		joints.append(joint)
		tips.append(tip)
		ranges.append(Vector2(first, geometry.vertices.size() - first))
		reaches.append(reach)
		heights.append(tip.y - root.y)
		patches.append(9)
		group_counts.append(groups)
	assert(not roots.is_empty() and roots.size() <= 42, "Branchlets must remain a nonempty, bounded local experiment")
	assert(low_vertices + geometry.vertices.size() < 45000 * 3)
	var material := ShaderMaterial.new()
	material.shader = LEAVES
	material.set_shader_parameter("meadow_texture", TURF)
	material.set_shader_parameter("middle_scrub", true)
	var branchlets := MeshInstance3D.new()
	branchlets.name = "CrownTransitionBranchlets"
	branchlets.mesh = geometry.mesh()
	branchlets.material_override = material
	branchlets.layers = 8
	branchlets.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
	branchlets.set_meta("protocol_version", "branchlets-93-1")
	branchlets.set_meta("roots", roots)
	branchlets.set_meta("joints", joints)
	branchlets.set_meta("tips", tips)
	branchlets.set_meta("ranges", ranges)
	branchlets.set_meta("patches", patches)
	branchlets.set_meta("reaches", reaches)
	branchlets.set_meta("heights", heights)
	branchlets.set_meta("group_counts", group_counts)
	branchlets.set_meta("leaf_group_ranges", leaf_group_ranges)
	branchlets.set_meta("leaf_group_plant_indices", leaf_group_plant_indices)
	branchlets.set_meta("leaf_group_bases", leaf_group_bases)
	branchlets.set_meta("leaf_ranges", leaf_ranges)
	branchlets.set_meta("leaf_attachments", leaf_attachments)
	branchlets.set_meta("leaf_root_indices", leaf_root_indices)
	branchlets.set_meta("build_ms", Time.get_ticks_msec() - started)
	add_child(branchlets)
	print("MEADOW_BRANCHLETS: %d supported patch9 plants, %d triangles; two real twig segments and three two-leaf tiers; build_ms=%d; v91 low fringe retained exactly" % [roots.size(), geometry.vertices.size() / 3, branchlets.get_meta("build_ms")])

func _surface(p: Vector2) -> Dictionary:
	var hit := land.intersect_ray(Vector3(p.x, 60.0, p.y), Vector3.DOWN)
	var stone := rocks.intersect_ray(Vector3(p.x, 60.0, p.y), Vector3.DOWN)
	if not stone.is_empty() and (hit.is_empty() or stone.position.y > hit.position.y):
		return stone
	return hit

func _safe(p: Vector2, expansion: float) -> bool:
	if meadow.distance_to_road(p) < meadow.road_half_width(p.y) + expansion + 0.9:
		return false
	if p.distance_to(meadow.BOSS_CENTER) < meadow.BOSS_ARENA_RADIUS + expansion + 1.5:
		return false
	if absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + expansion + 2.2:
		return false
	for habitat: Rect2 in meadow.WILDLIFE_CONTROLLER.HABITATS:
		if habitat.grow(expansion + 0.4).has_point(p):
			return false
	return true
