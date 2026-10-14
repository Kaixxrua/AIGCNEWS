extends RefCounted
## Open woody crowns bridge the castle cutout to the actual valley.
## Each crown has real rooted twigs and distinct folded leaf sprays, not a shell.

const LEAVES = preload("res://shaders/meadow_leaves.gdshader")
const TURF = preload("res://assets/materials/meadow-sward-v60.png")
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const GEOMETRY = preload("res://scripts/meadow_branch_geometry.gd")
const SIDES := 11
var geometry := GEOMETRY.new()
var roots := PackedVector3Array()
var root_faces := PackedInt32Array()
var crown_ranges := PackedVector2Array()
var crown_centers := PackedVector3Array()
var crowns := 0
var random := RandomNumberGenerator.new()

static func cover_at(p: Vector2, origin: Vector2) -> float:
	# Match meadow_palette.gdshaderinc. The front is not a straight dark belt.
	var spread := 1.0 - smoothstep(70.0, 104.0, absf(p.x - origin.x))
	var front := origin.y + 57.0 + 10.0 * sin(p.x * 0.069) + 7.0 * sin(p.x * 0.173 + 1.4)
	return spread * (1.0 - smoothstep(origin.y + 7.0, front, p.y))

func build(scene: Node3D) -> void:
	geometry.scene = scene
	geometry.density_override = 0.86
	var city: MeshInstance3D = scene.get_node("IndependentCastleHill")
	var origin := Vector2(city.position.x, city.position.z)
	scene.ground_material.set_shader_parameter("foothill_origin", origin)
	if CACHE.restore(scene, "foothill"):
		var cached := scene.get_node("CastleFoothillWoodland")
		print("MEADOW_FOOTHILL_READY: %d unique open woody crowns; %d actual-terrain roots; no image duplication (prebuilt)" % [cached.get_meta("crown_count"), cached.get_meta("ground_roots").size()])
		return
	var land: Mesh = scene.get_node("ContinuousMeadow").mesh
	var surface: TriangleMesh = land.generate_triangle_mesh()
	random.seed = 550909
	for sample in range(230):
		var p := origin + Vector2(random.randf_range(-100.0, 100.0), random.randf_range(4.0, 72.0))
		var density := cover_at(p, origin)
		var grove: float = scene._growth_noise(p * 0.064 + Vector2(7.1, 2.7))
		if random.randf() > density * smoothstep(0.22, 0.70, grove) * 0.87:
			continue
		# The distant path remains open too, even though it is outside the current AI habitat.
		if scene.distance_to_road(p) < scene.road_half_width(p.y) + 5.0:
			continue
		for lobe in range(random.randi_range(3, 6)):
			var q := p + Vector2(random.randf_range(-3.2, 3.2), random.randf_range(-2.0, 2.0))
			var radius := Vector2(random.randf_range(1.3, 3.3), random.randf_range(1.4, 3.1))
			if scene.distance_to_road(q) < scene.road_half_width(q.y) + maxf(radius.x, radius.y) * 1.26 + 0.5:
				continue
			var hit := surface.intersect_ray(Vector3(q.x, 60.0, q.y), Vector3.DOWN)
			if hit.is_empty() or hit.normal.y < 0.90:
				continue
			_crown(surface, hit.position, radius, random.randf_range(0.95, 2.75), random.randf_range(0.79, 1.00))
	# Tie the near edge of this actual city source into the woodland rather
	# than relying only on a broad, unrelated random scatter in front of it.
	var seam_crowns := _build_city_foot_growth(scene, city, surface)
	assert(crowns > 80 and roots.size() > 1000, "Foothill integration requires real, rooted crown geometry")
	var material := ShaderMaterial.new()
	material.shader = LEAVES
	material.set_shader_parameter("meadow_texture", TURF)
	material.set_shader_parameter("foothill_scrub", true)
	var instance := MeshInstance3D.new()
	instance.name = "CastleFoothillWoodland"
	instance.mesh = geometry.mesh()
	instance.material_override = material
	instance.layers = 8
	# Beyond the sun's near shadow cascades; folded leaf normals supply shape.
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	instance.set_meta("ground_roots", roots)
	instance.set_meta("root_faces", root_faces)
	instance.set_meta("crown_ranges", crown_ranges)
	instance.set_meta("crown_centers", crown_centers)
	instance.set_meta("crown_count", crowns)
	instance.set_meta("field_origin", origin)
	instance.set_meta("city_seam_crowns", seam_crowns)
	scene.add_child(instance)
	print("MEADOW_FOOTHILL_READY: %d unique open woody crowns; %d actual-terrain roots; no image duplication" % [crowns, roots.size()])
	print("MEADOW_CITY_SEAM_READY: %d unequal solid crowns follow actual city feet, not a straight hedge" % seam_crowns)

func _build_city_foot_growth(scene: Node3D, city: MeshInstance3D, surface: TriangleMesh) -> int:
	random.seed = 620909
	var count_before := crowns
	var city_feet: PackedVector2Array = city.get_meta("root_uvs")
	for i in range(1, city_feet.size() - 1, 4):
		var foot: Vector3 = scene._card_point(city, city_feet[i])
		if random.randf() < 0.23:
			continue
		for lobe in range(random.randi_range(1, 3)):
			var q := Vector2(foot.x, foot.z) + Vector2(random.randf_range(-3.5, 3.5), random.randf_range(1.6, 12.0))
			var radius := Vector2(random.randf_range(1.3, 3.1), random.randf_range(1.1, 2.8))
			if scene.distance_to_road(q) < scene.road_half_width(q.y) + maxf(radius.x, radius.y) * 1.26 + 0.5:
				continue
			var hit := surface.intersect_ray(Vector3(q.x, 60, q.y), Vector3.DOWN)
			if hit.is_empty() or hit.normal.y < 0.88:
				continue
			_crown(surface, hit.position, radius, random.randf_range(1.15, 3.9), random.randf_range(0.78, 0.94))
	assert(crowns - count_before > 20)
	return crowns - count_before

func _crown(surface: TriangleMesh, root: Vector3, radius: Vector2, height: float, tone: float) -> void:
	var first_face := geometry.vertices.size() / 3
	var phase := random.randf() * TAU
	var lean := Vector2(random.randf_range(-0.35, 0.35), random.randf_range(-0.30, 0.30))
	# Keep the placement RNG's three original draws; changing one crown must not
	# reshuffle the entire city-foot woodland. Detail has its own independent seed.
	var detail := RandomNumberGenerator.new()
	detail.seed = 750910 + crowns * 307
	for stem in range(SIDES + 1):
		var angle := float(stem) / SIDES * TAU
		var lobing := 1.0 + sin(angle * 3.0 + phase) * 0.17 + sin(angle * 7.0 - phase) * 0.075
		var p := root + Vector3(cos(angle) * radius.x * lobing, 0, sin(angle) * radius.y * lobing)
		if stem == SIDES:
			p = root
		var hit := surface.intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
		assert(not hit.is_empty(), "Every woody stem needs real soil")
		p.y = hit.position.y - 0.012
		roots.append(p)
		root_faces.append(geometry.vertices.size() / 3)
		var rise := height * (1.0 if stem == SIDES else detail.randf_range(0.67, 0.98))
		var top := root + Vector3(lean.x + cos(angle + phase) * radius.x * 0.18,
			rise, lean.y + sin(angle + phase) * radius.y * 0.18)
		geometry.twig(p, top, minf(radius.x, radius.y) * 0.022, tone * 0.86)
		for leaf in range(4):
			var tier := 0.30 + leaf * 0.19
			var origin := p.lerp(top, tier)
			var heading := angle + phase + leaf * 2.39996 + detail.randf_range(-0.4, 0.4)
			var span := minf(radius.x, radius.y) * detail.randf_range(0.44, 0.72)
			var length := Vector3(cos(heading), detail.randf_range(0.10, 0.34), sin(heading)) * span
			geometry.leaf(origin, length, span * detail.randf_range(0.35, 0.55), tone * detail.randf_range(0.84, 1.05), 0.24)
	crown_ranges.append(Vector2(first_face, geometry.vertices.size() / 3 - first_face))
	crown_centers.append(root)
	crowns += 1
