extends RefCounted
## Rooted branches with three-leaf clusters between existing art colonies.
## No bitmap copies, opaque mound shells, colliders or world-height changes.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const LEAF_SHADER = preload("res://shaders/meadow_leaves.gdshader")
const TURF = preload("res://assets/materials/meadow-sward-v60.png")
const GEOMETRY = preload("res://scripts/meadow_branch_geometry.gd")
# Leave room for the existing <0.060m horizontal breeze inside _safe(p, 1.9).
const LEAF_HORIZONTAL_RADIUS_LIMIT := 1.82
# Yaw around UP, length factor, half-width factor for each pointed leaflet.
const LEAFLET_PROFILES := [Vector3(0.0, 1.0, 0.56), Vector3(-0.75, 0.83, 0.50), Vector3(0.75, 0.68, 0.50)]
const GUIDES := [Vector4(-37, -34, 7.2, 3.9), Vector4(-28, -27, 6.7, 3.6),
	Vector4(-21, -41, 6.2, 4.6), Vector4(-8, -45, 7.0, 4.3),
	Vector4(-21, -63, 8.7, 5.4), Vector4(1, -62, 7.8, 4.5),
	Vector4(-42, -79, 9.4, 5.4), Vector4(-3, -88, 8.3, 5.0), Vector4(40, -104, 10.4, 5.6),
	Vector4(5, -39, 5.2, 3.8), Vector4(-32, -51, 6.8, 3.6),
	Vector4(-13, -73, 7.2, 4.5), Vector4(11, -98, 7.6, 4.8), Vector4(-19, -120, 11.0, 7.0)]
var geometry := GEOMETRY.new()
var roots := PackedVector3Array()
var root_faces := PackedInt32Array()
var heights := PackedFloat32Array()
var patches := PackedInt32Array()
var edge_distances := PackedFloat32Array()
# Actual emitted leaf-vertex radius in XZ, indexed exactly like roots.
var leaf_horizontal_radii := PackedFloat32Array()
var random := RandomNumberGenerator.new()
var scene: Node3D

func build(meadow: Node3D) -> void:
	scene = meadow
	geometry.scene = scene
	if CACHE.restore(scene, "brush"):
		var cached: MeshInstance3D = scene.get_node("MiddleMeadowBrush")
		print("MEADOW_MIDDLE_BRUSH_READY: %d rooted stems across fourteen distinct growth zones; one prebuilt branch/leaf batch" % cached.get_meta("roots").size())
		return
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var stone: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	for patch in range(GUIDES.size()):
		random.seed = 710921 + patch * 271
		var guide: Vector4 = GUIDES[patch]
		for candidate in range(140):
			var angle := random.randf() * TAU
			var reach := sqrt(random.randf())
			var lobe := 0.76 + 0.16 * sin(angle * 3.0 + patch * 1.47) + 0.08 * sin(angle * 7.0 - patch)
			var p := Vector2(guide.x, guide.y) + Vector2(cos(angle) * guide.z, sin(angle) * guide.w) * reach * lobe
			var envelope := 1.0 - smoothstep(0.25, 1.0, reach)
			if random.randf() > 0.44 + envelope * 0.44 or not _safe(p, 1.9):
				continue
			var hit := land.intersect_ray(Vector3(p.x, 60, p.y), Vector3.DOWN)
			var rock := stone.intersect_ray(Vector3(p.x, 60, p.y), Vector3.DOWN)
			if not rock.is_empty() and (hit.is_empty() or rock.position.y > hit.position.y):
				hit = rock
			if hit.is_empty() or hit.normal.y < 0.78 or scene.below_river_surface(p.x, p.y, hit.position.y):
				continue
			var root: Vector3 = hit.position + Vector3.UP * 0.006
			var height := lerpf(0.22, 1.13, envelope) * random.randf_range(0.83, 1.15)
			height *= lerpf(1.0, 1.43, smoothstep(45.0, 120.0, -p.y))
			# Several unequal crown peaks within each colony, not a level leaf mat.
			# Continuous world-space variation groups neighbouring stems naturally;
			# no extra RNG calls disturb the established root and colour sequence.
			var crown_rise := 0.90 + envelope * 0.64
			crown_rise += sin(p.x * 0.70 + p.y * 0.21 + patch * 1.4) * 0.30
			crown_rise += cos(p.x * 0.29 - p.y * 0.51) * 0.15
			height = minf(height * clampf(crown_rise, 0.76, 1.95), 2.35)
			var lean := Vector3(cos(angle + 0.7), 0, sin(angle + 0.7)) * height * random.randf_range(0.10, 0.21)
			roots.append(root)
			root_faces.append(geometry.vertices.size() / 3)
			heights.append(height)
			patches.append(patch)
			edge_distances.append(reach)
			var tone := random.randf_range(0.70, 0.90)
			var stem_joint := root + Vector3.UP * height * 0.52 + lean * 0.30
			var stem_tip := root + Vector3.UP * height + lean
			geometry.twig(root, stem_joint, height * 0.018, tone)
			geometry.twig(stem_joint, stem_tip, height * 0.009, tone)
			var first_leaf_vertex: int = geometry.vertices.size()
			# Twelve original slots; three two-triangle leaflets share each attachment.
			for leaf in range(12):
				# Break equal shelf spacing while retaining real stem attachments.
				var tier := 0.16 + (float(leaf) + sin(leaf * 1.71 + angle * 2.0) * 0.35) / 14.0
				# Attach to the two real twig segments, not an imagined quadratic stem.
				var origin := root.lerp(stem_joint, tier / 0.52) if tier <= 0.52 else stem_joint.lerp(stem_tip, (tier - 0.52) / 0.48)
				var heading := angle + leaf * 2.39996 + random.randf_range(-0.22, 0.22)
				var outward := Vector3(cos(heading), 0, sin(heading))
				var span := maxf(0.28, height * random.randf_range(0.55, 0.82) * (1.0 - tier * 0.22))
				# Broad middle branches, a compact rising crown and unequal outer tips.
				# Upper foliage turns inward instead of repeating the base's flat fan.
				var crown_taper := lerpf(1.14, 0.38, smoothstep(0.34, 0.94, tier))
				var side_variation := 0.86 + sin(heading * 1.73 + leaf * 0.83) * 0.17
				var radial_budget := LEAF_HORIZONTAL_RADIUS_LIMIT - Vector2(origin.x - root.x, origin.z - root.z).length()
				span = minf(maxf(lerpf(0.24, 0.35, envelope), span * crown_taper * side_variation), radial_budget)
				var rise_sample := random.randf_range(0.16, 0.45)
				var inclination := lerpf(0.12, 0.86, smoothstep(0.18, 0.94, tier)) + rise_sample * 0.72
				var length := outward * span + Vector3.UP * span * inclination
				var width := span * random.randf_range(0.32, 0.46) * lerpf(1.0, 1.12, envelope)
				# Cluster tips and folded side points stay within span in XZ;
				# retain the emitted-vertex measurement against the 1.82m root radius.
				_leaf_cluster(origin, length, width, tone)
			var leaf_radius := _emitted_leaf_horizontal_radius(root, first_leaf_vertex)
			assert(leaf_radius <= LEAF_HORIZONTAL_RADIUS_LIMIT + 0.0001, "Middle brush leaf exceeded its reserved footprint")
			leaf_horizontal_radii.append(leaf_radius)
	assert(roots.size() > 700)
	var material := ShaderMaterial.new()
	material.shader = LEAF_SHADER
	material.set_shader_parameter("meadow_texture", TURF)
	material.set_shader_parameter("middle_scrub", true)
	var brush := MeshInstance3D.new()
	brush.name = "MiddleMeadowBrush"
	brush.mesh = geometry.mesh()
	brush.material_override = material
	brush.layers = 8
	brush.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
	brush.set_meta("roots", roots)
	brush.set_meta("root_faces", root_faces)
	brush.set_meta("heights", heights)
	brush.set_meta("patches", patches)
	brush.set_meta("edge_distances", edge_distances)
	brush.set_meta("growth_guides", PackedVector4Array(GUIDES))
	brush.set_meta("leaf_horizontal_radii", leaf_horizontal_radii)
	brush.set_meta("leaf_horizontal_radius_limit", LEAF_HORIZONTAL_RADIUS_LIMIT)
	# Frozen 1,204-root layout: 14,448 three-leaf clusters / 43,344 leaflets.
	# Each root remains 2 four-triangle twigs + 12 six-triangle clusters = 80 triangles.
	var leaf_cluster_count := roots.size() * 12
	brush.set_meta("leaf_cluster_count", leaf_cluster_count)
	brush.set_meta("leaflet_count", leaf_cluster_count * 3)
	scene.add_child(brush)
	print("MEADOW_MIDDLE_BRUSH_READY: %d rooted stems across fourteen distinct growth zones; %d three-leaf clusters / %d pointed leaflets; %d branch/leaf triangles; one batch" % [roots.size(), leaf_cluster_count, leaf_cluster_count * 3, geometry.vertices.size() / 3])

func _leaf_cluster(origin: Vector3, length: Vector3, width: float, tone: float) -> void:
	# Replace one six-triangle leaf with three folded diamonds; no extra random draws.
	for profile: Vector3 in LEAFLET_PROFILES:
		var blade_length := length.rotated(Vector3.UP, profile.x) * profile.y
		var half_width := width * profile.z
		var side := Vector3(-blade_length.z, 0, blade_length.x).normalized() * half_width
		var shoulder := origin + blade_length * 0.42 - Vector3.UP * half_width * 0.30
		var left := shoulder - side
		var right := shoulder + side
		var tip := origin + blade_length
		# The origin-tip ridge joins two clockwise faces with their actual front normals.
		var left_normal := (tip - origin).cross(left - origin).normalized()
		var right_normal := (right - origin).cross(tip - origin).normalized()
		geometry._vertex(origin, left_normal, tone, 0.0, false)
		geometry._vertex(left, left_normal, tone, 0.65, false)
		geometry._vertex(tip, left_normal, tone * 1.02, 1.0, false)
		geometry._vertex(origin, right_normal, tone, 0.0, false)
		geometry._vertex(tip, right_normal, tone * 1.02, 1.0, false)
		geometry._vertex(right, right_normal, tone, 0.65, false)

func _emitted_leaf_horizontal_radius(root: Vector3, first_vertex: int) -> float:
	var radius_squared := 0.0
	for vertex in range(first_vertex, geometry.vertices.size()):
		var offset: Vector3 = geometry.vertices[vertex] - root
		radius_squared = maxf(radius_squared, offset.x * offset.x + offset.z * offset.z)
	return sqrt(radius_squared)

func _safe(p: Vector2, expansion: float) -> bool:
	if scene.distance_to_road(p) < scene.road_half_width(p.y) + expansion + 0.9:
		return false
	if p.distance_to(scene.BOSS_CENTER) < scene.BOSS_ARENA_RADIUS + expansion + 1.5:
		return false
	if absf(p.x - scene.river_center(p.y)) < scene.river_half_width(p.y) + expansion + 2.2:
		return false
	for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
		if habitat.grow(expansion + 0.4).has_point(p):
			return false
	return true
