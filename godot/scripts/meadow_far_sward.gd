extends RefCounted
## Low, open grass colonies on actual distant terrain, not billboard ground pads.
## Separate deterministic detail stream: no existing cache/terrain/trees move.
const GEOMETRY = preload("res://scripts/meadow_branch_geometry.gd")
const LEAVES = preload("res://shaders/meadow_leaves.gdshader")
const TURF = preload("res://assets/materials/meadow-sward-v60.png")
const LABEL := "DistantMeadowSward"
const MAX_TRIANGLES := 80000
const CACHE_PATH := "res://assets/baked/v113/far-sward.scn"
const SOURCE_PATH := "res://scripts/meadow_far_sward.gd"
const TERRAIN_PATH := "res://assets/baked/v77/terrain.scn"
const CACHE_REVISION := "rooted-sward-113-1"

static func build(scene: Node3D) -> void:
	if scene.has_node(LABEL):
		return
	var land := scene.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	if land == null:
		return
	var started := Time.get_ticks_msec()
	if not OS.get_cmdline_user_args().has("--bake-far-sward") and ResourceLoader.exists(CACHE_PATH):
		var packed := load(CACHE_PATH) as PackedScene
		var cached := packed.instantiate() as MeshInstance3D
		var valid: bool = cached.get_meta("cache_revision", "") == CACHE_REVISION
		if FileAccess.file_exists(SOURCE_PATH):
			valid = valid and cached.get_meta("source_sha256", "") == FileAccess.get_sha256(SOURCE_PATH) \
				and cached.get_meta("terrain_sha256", "") == FileAccess.get_sha256(TERRAIN_PATH)
		if valid:
			scene.add_child(cached)
			print("MEADOW_FAR_SWARD: %d exact-surface tufts; prebuilt sidecar in %d ms; no existing cache modified" % [cached.get_meta("ground_roots").size(), Time.get_ticks_msec() - started])
			return
		cached.free()
	var surface := land.mesh.generate_triangle_mesh()
	var random := RandomNumberGenerator.new()
	random.seed = 1130911
	var geometry := GEOMETRY.new()
	geometry.scene = scene
	var roots := PackedVector3Array()
	var colony_ranges := PackedVector2Array()
	var root_ranges := PackedVector2Array()
	var heights := PackedFloat32Array()
	# Broken drifts follow the same density field as soil, with open breathing
	# room between them. No equally spaced rows, closed green shells or repeats.
	for sample in range(660):
		var z := random.randf_range(-213.0, -92.0)
		var x := random.randf_range(-110.0, 115.0)
		var centre := Vector2(x, z)
		var density: float = scene.growth_density(centre)
		var coverage := smoothstep(0.26, 0.76, density)
		var blend := smoothstep(-213.0, -191.0, z) * (1.0 - smoothstep(-106.0, -92.0, z))
		if random.randf() > coverage * blend * 0.86 or not _safe(scene, centre, 6.0):
			continue
		var axis := random.randf() * TAU
		var span := Vector2(random.randf_range(2.3, 5.8), random.randf_range(1.3, 3.0))
		var tone := random.randf_range(0.83, 0.99)
		var start := roots.size()
		for tuft in range(random.randi_range(8, 19)):
			var angle := random.randf() * TAU
			var radius := sqrt(random.randf())
			var local := Vector2(cos(angle) * span.x, sin(angle) * span.y) * radius
			var p := centre + local.rotated(axis)
			if not _safe(scene, p, 1.2):
				continue
			var hit := surface.intersect_ray(Vector3(p.x, 60.0, p.y), Vector3.DOWN)
			if hit.is_empty() or Vector3(hit.normal).y < 0.89 or Vector3(hit.position).y < -0.04:
				continue
			var root: Vector3 = hit.position + Vector3.UP * 0.005
			var height := random.randf_range(0.40, 0.82) * (1.0 - radius * 0.30)
			var first: int = geometry.vertices.size()
			for leaf in range(4):
				var heading := angle + float(leaf) * 2.399963 + random.randf_range(-0.30, 0.30)
				var reach := random.randf_range(0.30, 0.70)
				var direction := Vector3(cos(heading) * reach, height * random.randf_range(0.65, 1.0), sin(heading) * reach)
				geometry.leaf(root, direction, random.randf_range(0.070, 0.145), tone, 0.65)
			roots.append(root)
			root_ranges.append(Vector2(first, geometry.vertices.size() - first))
			heights.append(height)
		if roots.size() > start:
			colony_ranges.append(Vector2(start, roots.size() - start))
	assert(roots.size() > 400 and geometry.vertices.size() / 3 <= MAX_TRIANGLES)
	var material := ShaderMaterial.new()
	material.shader = LEAVES
	material.set_shader_parameter("meadow_texture", TURF)
	material.set_shader_parameter("far_sward", true)
	var mesh := MeshInstance3D.new()
	mesh.name = LABEL
	mesh.mesh = geometry.mesh()
	mesh.material_override = material
	mesh.layers = 8 # Does not enter the approved water reflection.
	mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mesh.extra_cull_margin = 0.06
	mesh.set_meta("ground_roots", roots)
	mesh.set_meta("root_ranges", root_ranges)
	mesh.set_meta("colony_ranges", colony_ranges)
	mesh.set_meta("root_heights", heights)
	mesh.set_meta("triangle_budget", MAX_TRIANGLES)
	mesh.set_meta("cache_revision", CACHE_REVISION)
	mesh.set_meta("source_sha256", FileAccess.get_sha256(SOURCE_PATH))
	mesh.set_meta("terrain_sha256", FileAccess.get_sha256(TERRAIN_PATH))
	scene.add_child(mesh)
	print("MEADOW_FAR_SWARD: %d rooted tufts in %d distinct open colonies; %d triangles, one mesh, no colliders; %d ms" % [roots.size(), colony_ranges.size(), geometry.vertices.size() / 3, Time.get_ticks_msec() - started])

static func _safe(scene: Node3D, p: Vector2, reach: float) -> bool:
	return p.y >= -216.0 and p.y <= -89.0 \
		and scene.distance_to_road(p) > scene.road_half_width(p.y) + reach + 3.0 \
		and p.distance_to(scene.BOSS_CENTER) > scene.BOSS_ARENA_RADIUS + reach \
		and absf(p.x - scene.river_center(p.y)) > scene.river_water_half_width(p.y) + reach + 7.0
