extends SceneTree
## One real scene; external baseline compiled in memory, never instantiated.
const OLD = preload("res://tools/audit_mountain_material.gd")
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const BASE_SHA := "a931617d7b660dc01e9e04be29bcdc667ea775c42e3c7937a32d1cb0c4993262"
const ASSET_SHA := "15d53d1a69420cbfe470477dd3f584b0267f34969056473bafb2ac5bdada5ba1"
const EXTRA := {"res://scenes/main.tscn": "6edd01b8939e02defad401ce855f1eb1ca73130354b2ac166a42012327da03ac", "res://shaders/meadow_palette.gdshaderinc": "91b7013c8ec118e3f6578978d9718b3b334edd23b0a20a5bc4cb78a94a950d4a", "res://shaders/meadow_surface.gdshaderinc": "0005905cd6dfaee47c4bba8548e598cc3d1e1aec057440cb10288d461a0928d4"}
var failed := false
var checks := 0

func _initialize() -> void:
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failed = true
		push_error("MEADOW_MOUNTAIN_WOODLAND_AUDIT: FAIL; " + label)
		quit(1)
	return value

func _assets(directory: String, paths: Array[String]) -> void:
	for file in DirAccess.get_files_at(directory):
		if file.get_extension() in ["png", "jpg", "webp"]: paths.append(directory.path_join(file))
	for folder in DirAccess.get_directories_at(directory): _assets(directory.path_join(folder), paths)

func _allowed(p: Vector3) -> bool:
	return p.z > -327.0 and p.z < -225.0 and (p.x < -24.0 or p.x > 166.0)

func _run() -> void:
	# A runtime error aborting this method must retain exit 1, not default success.
	quit(1)
	if not _ok(not OS.get_cmdline_user_args().has("--rebuild-static"), "No bake from this audit"): return
	var baseline_path := ProjectSettings.globalize_path("res://../artifacts/v98/meadow_scene.v97-before.gd")
	if not _ok(FileAccess.get_sha256(baseline_path) == BASE_SHA, "Frozen v97 scene"): return
	for path: String in OLD.PROTECTED:
		if path == "res://shaders/meadow_leaves.gdshader":
			# v98 candidate2 deliberately opts near vegetation into the shared
			# sunlight pass; GPU equivalence is a separate, executed probe.
			if not _ok(FileAccess.get_sha256(path) == "f5a422104b8bce905593cb21a91bc12fe2664bdac2844d0dd88f242375b34c52", "Reviewed sunlight leaf source"): return
			continue
		if not _ok(FileAccess.get_sha256(path) == OLD.PROTECTED[path], "Protected " + path): return
	for path: String in EXTRA:
		if not _ok(FileAccess.get_sha256(path) == EXTRA[path], "Protected " + path): return
	var source_hashes := {}
	for path: String in ["res://scripts/meadow_scene.gd", "res://scripts/meadow_mountain_landform.gd", "res://scripts/meadow_mountain_woodland.gd"]: source_hashes[path] = FileAccess.get_sha256(path)
	if not _ok(FileAccess.get_sha256("res://scripts/meadow_branch_geometry.gd") == "d2207d2b78d7697fe83870880ec484e29a4af730c2b265ce894b9b87c9c2b99f", "Branch primitive source"): return
	var paths: Array[String] = []
	_assets("res://assets", paths)
	paths.sort()
	var asset_text := ""
	for path in paths: asset_text += path + ":" + FileAccess.get_sha256(path) + "\n"
	if not _ok(asset_text.sha256_text() == ASSET_SHA, "All 80 existing raster assets exact, no new PNG"): return
	var previous := FileAccess.get_file_as_string(baseline_path).replace("\r\n", "\n")
	var current := FileAccess.get_file_as_string("res://scripts/meadow_scene.gd").replace("\r\n", "\n")
	for addition: String in ['const MOUNTAIN_LANDFORM = preload("res://scripts/meadow_mountain_landform.gd")\n', '\trolling += MOUNTAIN_LANDFORM.height_offset(x, z)\n', 'const MOUNTAIN_WOODLAND = preload("res://scripts/meadow_mountain_woodland.gd")\n', '\tMOUNTAIN_WOODLAND.build(self)\n']:
		if not _ok(current.count(addition) == 1, "Exactly one approved scene addition: " + addition.strip_edges()): return
		current = current.replace(addition, "")
	if not _ok(current == previous, "All other scene code exact: camera/water/road/Boss/static functions"): return
	var baseline := GDScript.new()
	baseline.source_code = previous
	if not _ok(baseline.reload() == OK and baseline.can_instantiate(), "External baseline reload"): return
	# Reject stale caches before scene construction; never trigger an implicit full rebuild.
	for group: String in CACHE.GROUPS:
		var packed := load(CACHE.DIRECTORY + group + ".scn") as PackedScene
		if not _ok(packed != null, "Current cache " + group): return
		var container := packed.instantiate()
		var valid: bool = container.get_meta("source_signature", "") == CACHE.signature() and container.get_meta("cache_version", "") == CACHE.VERSION
		container.free()
		if not _ok(valid, "Main must rebake current signature: " + group): return
	var packed_scene := load("res://scenes/main.tscn") as PackedScene
	if not _ok(packed_scene != null, "Main scene resource"): return
	var scene := packed_scene.instantiate() as Node3D
	if not _ok(scene != null, "Main scene instance"): return
	root.add_child(scene)
	var land := scene.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	var wood := scene.get_node_or_null("MountainFootWoodland") as MeshInstance3D
	if not _ok(land != null and wood != null, "Actual terrain and woodland required"): return
	if not _ok(land.mesh is ArrayMesh and wood.mesh is ArrayMesh and wood.mesh.get_surface_count() == 1, "Actual triangle meshes"): return
	if not _ok(land.global_transform == Transform3D.IDENTITY and wood.global_transform == Transform3D.IDENTITY, "World-space geometry"): return
	if not _ok(_terrain(scene, baseline, land) == true, "Terrain audit completed"): return
	if not _ok(_crowns(scene, land, wood) == true, "Crown audit completed"): return
	scene.free()
	for path: String in source_hashes:
		if not _ok(FileAccess.get_sha256(path) == source_hashes[path], "Source stable during audit " + path): return
	if failed: return
	print("MEADOW_MOUNTAIN_WOODLAND_AUDIT: PASS; checks=%d; actual terrain/roots/ranges/unique geometry; NOT GPU, whole-edge grounding, visual or performance acceptance" % checks)
	quit(0)

func _terrain(scene: Node3D, baseline: GDScript, land: MeshInstance3D) -> bool:
	var collisions := land.find_children("*", "CollisionShape3D", true, false)
	if not _ok(collisions.size() == 1 and collisions[0].shape is ConcavePolygonShape3D, "Actual terrain collision required"): return false
	if not _ok(collisions[0].global_transform == land.global_transform and not collisions[0].disabled and collisions[0].shape.get_faces() == land.mesh.get_faces(), "Actual collision faces exact current mesh"): return false
	var vertices: PackedVector3Array = land.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	var protected_count := 0
	var changed := 0
	for p: Vector3 in vertices:
		if not _ok(p.is_finite(), "Finite terrain vertex"): return false
		var expected := Vector3(p.x, scene.terrain_height(p.x, p.z), p.z)
		if not _ok(p == expected, "Actual mesh matches current terrain function"): return false
		var old := Vector3(p.x, baseline.terrain_height(p.x, p.z), p.z)
		if not _allowed(p):
			if not _ok(p == old, "Actual protected terrain vertex EXACT v97"): return false
			protected_count += 1
		elif p != old: changed += 1
	# Independent rectangular lattice includes protected near land and central far corridor.
	for z in range(-340, 81, 4):
		for x in range(-300, 301, 4):
			if not _allowed(Vector3(x, 0, z)):
				if not _ok(scene.terrain_height(x, z) == baseline.terrain_height(x, z) and scene.meadow_height(x, z) == baseline.meadow_height(x, z), "Protected static height EXACT"): return false
	if not _ok(protected_count > 0 and changed > 0, "Nonempty protected terrain and actual far relief change"): return false
	print("MEADOW_MOUNTAIN_WOODLAND_TERRAIN: protected_vertices=%d changed_far_vertices=%d; not whole-cache equality" % [protected_count, changed])
	return true

func _crowns(scene: Node3D, land: MeshInstance3D, wood: MeshInstance3D) -> bool:
	var a := wood.mesh.surface_get_arrays(0)
	var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
	var uv: PackedVector2Array = a[Mesh.ARRAY_TEX_UV]
	var normals: PackedVector3Array = a[Mesh.ARRAY_NORMAL]
	var colors: PackedColorArray = a[Mesh.ARRAY_COLOR]
	var uv2: PackedVector2Array = a[Mesh.ARRAY_TEX_UV2]
	if not _ok(wood.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES and (a[Mesh.ARRAY_INDEX] == null or a[Mesh.ARRAY_INDEX].is_empty()), "Unindexed actual triangles"): return false
	if not _ok(v.size() > 0 and v.size() % 3 == 0 and v.size() <= 18000 * 3 and uv.size() == v.size() and normals.size() == v.size() and colors.size() == v.size() and uv2.size() == v.size(), "Actual budget and complete channels"): return false
	var material := wood.material_override as ShaderMaterial
	var ground := land.material_override as ShaderMaterial
	if not _ok(material != null and material.shader != null and ground != null, "Material dependencies"): return false
	if not _ok(material.shader.resource_path == "res://shaders/meadow_mountain_woodland.gdshader" and wood.get_meta("geometry_revision", "") == "volume-crowns-98-2", "Private volumetric canopy response"): return false
	if not _ok(typeof(wood.get_meta("ground_roots", null)) == TYPE_PACKED_VECTOR3_ARRAY and typeof(wood.get_meta("crown_ranges", null)) == TYPE_PACKED_VECTOR2_ARRAY, "Required grouping metadata types"): return false
	var roots: PackedVector3Array = wood.get_meta("ground_roots")
	var ranges: PackedVector2Array = wood.get_meta("crown_ranges")
	if not _ok(roots.size() > 0 and roots.size() == ranges.size(), "Nonempty root/range mapping"): return false
	if not _ok(roots.size() <= 100 and wood.get_meta("triangles_per_crown", 0) == 172, "Volume-crown count/budget"): return false
	if not _closed_lobes(wood, v, normals, roots.size()): return false
	var terrain := land.mesh.generate_triangle_mesh()
	if not _ok(terrain != null, "Actual terrain triangle surface"): return false
	var end := 0
	var shapes := {}
	var triangles := {}
	var max_gap := 0.0
	var max_radius := 0.0
	var height_range := Vector2(INF, -INF)
	for crown in range(roots.size()):
		var first := int(ranges[crown].x)
		var count := int(ranges[crown].y)
		if not _ok(ranges[crown] == Vector2(first, count) and first == end and count >= 12 and count % 3 == 0 and first + count <= v.size(), "Contiguous complete crown ranges"): return false
		end = first + count
		if not _ok(uv[first].x == -2000.0 and uv[first + 1].x == -2000.0, "Actual first twig root corners"): return false
		var root_point := (v[first] + v[first + 1]) * 0.5
		if not _ok(root_point.distance_to(roots[crown]) < 0.0001, "Metadata root agrees with actual twig"): return false
		var hit := terrain.intersect_ray(Vector3(root_point.x, 160, root_point.z), Vector3.DOWN)
		if not _ok(not hit.is_empty(), "Actual root ray hits terrain"): return false
		var gap: float = Vector3(hit.position).y - root_point.y
		max_gap = maxf(max_gap, absf(gap - 0.015))
		if not _ok(absf(gap - 0.015) <= 0.003, "Actual twig rooted 0.015 below triangle surface"): return false
		var local_shape := PackedVector3Array()
		var top := root_point.y
		var leaves := 0
		for i in range(first, end):
			var p := v[i]
			if not _ok(p.is_finite() and normals[i].is_finite() and uv[i].is_finite() and uv2[i].is_finite() and is_finite(colors[i].r) and is_finite(colors[i].g) and is_finite(colors[i].b) and is_finite(colors[i].a) and colors[i].a >= 0 and colors[i].a <= 1, "Finite channels and bounded wind"): return false
			if not _ok(absf(p.x) + 0.06 <= 264 and p.z - 0.06 >= -312 and p.z + 0.06 <= -235, "All vertex wind-space bounds"): return false
			if not _ok(scene.distance_to_road(Vector2(p.x, p.z)) > scene.road_half_width(p.z) + 0.06, "Actual crown clears road"): return false
			local_shape.append(p - root_point)
			top = maxf(top, p.y)
			max_radius = maxf(max_radius, Vector2(p.x - root_point.x, p.z - root_point.z).length())
			if uv[i].x > -900: leaves += 1
		if not _ok(leaves > 0 and top > root_point.y, "Actual leaf crown above stem root"): return false
		var identity := var_to_bytes(local_shape).hex_encode().sha256_text()
		if not _ok(not shapes.has(identity), "No identical translated crown geometry"): return false
		shapes[identity] = true
		height_range.x = minf(height_range.x, top - root_point.y)
		height_range.y = maxf(height_range.y, top - root_point.y)
	for i in range(0, v.size(), 3):
		var points := [str(v[i]), str(v[i + 1]), str(v[i + 2])]
		points.sort()
		var key := "|".join(points)
		if not _ok((v[i + 1] - v[i]).cross(v[i + 2] - v[i]).length_squared() > 1e-12 and not triangles.has(key), "Nondegenerate unique actual triangle"): return false
		triangles[key] = true
	if not _ok(end == v.size(), "No unassigned vertices"): return false
	print("MEADOW_MOUNTAIN_WOODLAND_GEOMETRY: crowns=%d triangles=%d root_error=%f max_radius=%f height=%s" % [roots.size(), v.size() / 3, max_gap, max_radius, str(height_range)])
	return true

func _closed_lobes(wood: MeshInstance3D, vertices: PackedVector3Array, normals: PackedVector3Array, crowns: int) -> bool:
	var centres: PackedVector3Array = wood.get_meta("lobe_centres")
	var ranges: PackedVector2Array = wood.get_meta("lobe_ranges")
	if not _ok(centres.size() == crowns * 6 and ranges.size() == centres.size(), "Six closed lobes per crown"): return false
	for lobe in range(centres.size()):
		var first := int(ranges[lobe].x)
		var count := int(ranges[lobe].y)
		if not _ok(count == 72 and first >= 0 and first + count <= vertices.size(), "Lobe triangle extent"): return false
		var edge_uses := {}
		var volume := 0.0
		for at in range(first, first + count, 3):
			var a := vertices[at] - centres[lobe]
			var b := vertices[at + 1] - centres[lobe]
			var c := vertices[at + 2] - centres[lobe]
			volume += a.dot(c.cross(b)) / 6.0
			for corner in range(3):
				var i := at + corner
				if not _ok(normals[i].dot(vertices[i] - centres[lobe]) > 0.0, "Outward volumetric canopy normal"): return false
				var edge := [str(vertices[i]), str(vertices[at + (corner + 1) % 3])]
				edge.sort()
				var key := "|".join(edge)
				edge_uses[key] = int(edge_uses.get(key, 0)) + 1
		for uses: int in edge_uses.values():
			if not _ok(uses == 2, "Closed canopy edge paired exactly twice"): return false
		if not _ok(volume > 0.005, "Positive actual leaf-mass volume"): return false
	print("MEADOW_MOUNTAIN_VOLUME: %d closed lobes, outward normals and actual positive volumes" % centres.size())
	return true
