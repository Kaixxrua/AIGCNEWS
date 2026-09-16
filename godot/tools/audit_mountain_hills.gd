extends SceneTree
## v107 full-source wooded hills contract; v106 audit remains frozen history.
## Main runs after baking. No rendering/cache writes; inspect the scene's result,
## never use the production deformation/mesh_point formula as the oracle.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const PRIMARY := "res://assets/backgrounds/mountain-massif-v106.png"
const HILLS := "res://assets/backgrounds/wooded-hills-v107.png"
const OLD := "res://assets/backgrounds/mountain-ridge-v39.png"
const PROTECTED := {
	HILLS: "1c598a06d9c9ea8617c46dfdded24882f20d624fba2f70bc8601b86298b34d68",
	PRIMARY: "3f25bcca01d9f36ddac260b1e57c2a89b2a54a9a9004064ac83e77dbededd51d",
	OLD: "ec1f06815d2ca2d8cababd3c3a4b7fd44ef92b153514ac3dbc564d0c38cc7d49",
	"res://scripts/meadow_weather.gd": "7afda1a94783bf28b48f860fa6a174220cc63a387d14ea094b16953c8ae4d5c9",
	"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08",
	"res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b",
	"res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d"}
var failed := false
var checks := 0

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _expect(ok: bool, label: String) -> bool:
	checks += 1
	if not ok:
		failed = true
		push_error("MOUNTAIN_HILLS: FAIL; " + label)
	return ok

func _preflight() -> bool:
	for path: String in PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == PROTECTED[path], "Frozen source " + path)
	_expect(not OS.get_cmdline_user_args().has("--rebuild-static"), "Audit cannot request a rebake")
	var exports := ConfigFile.new()
	if not _expect(exports.load("res://export_presets.cfg") == OK, "Readable export selection"): return false
	var selected: PackedStringArray = exports.get_value("preset.0", "export_files", PackedStringArray())
	_expect(exports.get_value("preset.0", "export_filter", "") == "resources" and selected.has(HILLS) and not selected.has(OLD), "New hills selected; old PNG retained on disk but not selected for export")
	# This is export-selection evidence, not proof of final PCK contents.
	# Refuse stale caches BEFORE instantiating main, which otherwise rebuilds them.
	for group: String in CACHE.GROUPS:
		var packed := load(CACHE.DIRECTORY + group + ".scn") as PackedScene
		if not _expect(packed != null, "Existing cache " + group):
			return false
		var container := packed.instantiate()
		_expect(container.get_meta("source_signature", "") == CACHE.signature() and container.get_meta("cache_version", "") == CACHE.VERSION, "Current cache " + group)
		container.free()
	return not failed

func _run() -> void:
	if _preflight() != true or failed:
		quit(1)
		return
	var packed := load("res://scenes/main.tscn") as PackedScene
	if not _expect(packed != null, "Main scene exists"):
		quit(1)
		return
	var scene := packed.instantiate() as Node3D
	if not _expect(scene != null, "Main scene is Node3D"):
		quit(1)
		return
	root.add_child(scene)
	scene.process_mode = Node.PROCESS_MODE_DISABLED
	# Typed completion propagates runtime-aborted checks as failure, never PASS.
	var completed: bool = _verify(scene)
	scene.free()
	for path: String in PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == PROTECTED[path], "Still frozen " + path)
	_expect(completed, "All geometry checks completed")
	print("MOUNTAIN_HILLS: %s; checks=%d; CPU source/geometry/projection only, NOT GPU alpha filtering, lighting, visual occlusion or performance acceptance" % ["FAIL" if failed else "PASS", checks])
	quit(1 if failed else 0)

func _verify(scene: Node3D) -> bool:
	var camera := scene.get_node_or_null("Camera3D") as Camera3D
	var terrain := scene.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	var castle := scene.get_node_or_null("IndependentCastleHill") as MeshInstance3D
	if not _expect(camera != null and terrain != null and castle != null, "Camera, terrain and castle exist"):
		return false
	if not _expect(terrain.mesh != null and castle.mesh != null, "Actual terrain/castle meshes"):
		return false
	var ground := terrain.mesh.generate_triangle_mesh()
	if not _expect(ground != null, "Actual terrain triangle ray target"):
		return false
	var far_castle := -INF
	for p: Vector3 in castle.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]:
		far_castle = maxf(far_castle, -(camera.global_transform.affine_inverse() * castle.to_global(p)).z)
	var names := ["DistantMountainRidge", "RightMountainRidge"]
	for n in range(2):
		var card := scene.get_node_or_null(NodePath(names[n])) as MeshInstance3D
		if not _expect(card != null, "Actual card " + names[n]):
			return false
		if _card(card, camera, terrain, ground, far_castle, n == 0) != true:
			return false
	return not failed

func _card(card: MeshInstance3D, camera: Camera3D, terrain: MeshInstance3D, ground: TriangleMesh, castle_far: float, primary: bool) -> bool:
	var tag := str(card.name) + ": "
	var width := 390.0 if primary else 230.0
	var centre := Vector2(-95, -310) if primary else Vector2(200, -320)
	var region := Vector4(0, 0, 1, 1)
	var height := width * 724.0 / (2172.0 * region.z)
	var material := card.material_override as ShaderMaterial
	if not _expect(card.mesh is ArrayMesh and card.mesh.get_surface_count() == 1 and material != null, tag + "One ArrayMesh surface and shader material"):
		return false
	for key: String in ["relief_grid", "relief_base_size", "relief_base_offset", "relief_root_uvs", "relief_root_shifts", "relief_root_triangle_hits"]:
		if not _expect(card.has_meta(key), tag + "Metadata API " + key):
			return false
	_expect(card.get_meta("relief_grid") == Vector2i(64, 20), tag + "64x20 schema")
	_expect(typeof(card.get_meta("relief_base_offset")) == TYPE_VECTOR3, tag + "Offset type")
	_expect(typeof(card.get_meta("relief_root_uvs")) == TYPE_PACKED_VECTOR2_ARRAY and typeof(card.get_meta("relief_root_shifts")) == TYPE_PACKED_FLOAT32_ARRAY, tag + "Root metadata types")
	_expect(typeof(card.get_meta("relief_root_triangle_hits")) == TYPE_PACKED_BYTE_ARRAY, tag + "Root hit metadata type")
	_expect(card.get_meta("relief_base_size") is Vector2 and Vector2(card.get_meta("relief_base_size")).distance_to(Vector2(width, height)) < 0.0001, tag + "Native crop aspect, no height squash")
	_expect(card.global_basis.is_equal_approx(Basis.IDENTITY) and Vector2(card.global_position.x, card.global_position.z).distance_to(centre) < 0.0001, tag + "World centre and unscaled basis")
	_expect(material.get_shader_parameter("uv_region") == region, tag + "Full new source, no legacy crop")
	_expect(absf(card.global_position.y) < 0.0001, tag + "Approved world Y=0")
	_expect(material.get_shader_parameter("alpha_threshold") == 0.60 and material.get_shader_parameter("native_massif") == true, tag + "Native source profile and alpha .60")
	var wooded: Variant = material.get_shader_parameter("wooded_foothill")
	if wooded == null:
		_expect(FileAccess.get_file_as_string("res://shaders/meadow_mountain.gdshaderinc").count("uniform bool wooded_foothill = false;") == 1, tag + "Explicit wooded default")
		wooded = false
	_expect(wooded == (not primary), tag + "Wooded profile only on RightMountainRidge")
	_expect(material.get_shader_parameter("face_camera") == false, tag + "World-space orientation")
	_expect(material.shader != null and material.shader.resource_path in ["res://shaders/meadow_mountain.gdshader", "res://shaders/meadow_mountain_day.gdshader"], tag + "Mountain shader family")
	var surface := FileAccess.get_file_as_string("res://shaders/meadow_cutout_surface.gdshaderinc")
	# Dummy rendering servers need not expose shader defaults. Resolve only these
	# explicit source declarations; null never silently becomes false/zero.
	for entry: Array in [["wind_strength", 0.0, "uniform float wind_strength = 0.0;"], ["sprite_profile", 1.0, "uniform float sprite_profile = 1.0;"], ["sprite_bank", 0.0, "uniform float sprite_bank = 0.0;"], ["sprite_flip", false, "uniform bool sprite_flip = false;"]]:
		var value: Variant = material.get_shader_parameter(entry[0])
		if value == null:
			_expect(surface.count(entry[2]) == 1, tag + "Explicit default " + str(entry[0]))
			value = entry[1]
		_expect(value == entry[1], tag + "No shader coordinate deformation: " + str(entry[0]))
	var texture := material.get_shader_parameter("asset_texture") as Texture2D
	if not _expect(texture != null, tag + "Source texture") or failed:
		return false
	_expect(texture.resource_path == (PRIMARY if primary else HILLS) and texture.get_size() == Vector2(2172, 724), tag + "Exact source identity and dimensions")
	var source := texture.get_image()
	if not _expect(source != null and not source.is_empty(), tag + "Readable actual alpha"):
		return false
	if source.is_compressed() and not _expect(source.decompress() == OK, tag + "Alpha decode"):
		return false
	var arrays := card.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	if not _expect(vertices.size() == 65 * 21 and normals.size() == vertices.size() and uv.size() == vertices.size() and indices.size() == 64 * 20 * 6 and card.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES, tag + "Actual channel/topology counts"):
		return false
	var offset: Vector3 = card.get_meta("relief_base_offset")
	_expect(offset.is_finite() and absf(offset.x) < 0.0001 and absf(offset.z) < 0.0001, tag + "Base offset cannot move the approved XZ centre")
	var depth := Vector2(INF, -INF)
	var summed := PackedVector3Array()
	summed.resize(vertices.size())
	var uv_area := 0.0
	for col in range(65):
		for row in range(21):
			var i := col * 21 + row
			var p := vertices[i]
			_expect(p.is_finite() and normals[i].is_finite() and uv[i].is_finite(), tag + "Finite channels")
			_expect(absf(uv[i].x - float(col) / 64.0) < 1e-7 and uv[i].y >= 0 and uv[i].y <= 1, tag + "Registered column UV")
			_expect(absf(p.x - offset.x - (uv[i].x - 0.5) * width) < 0.0001, tag + "Actual identity horizontal mapping")
			if row <= 17:
				_expect(absf(p.y - offset.y - (0.5 - uv[i].y) * height) < 0.0001, tag + "Native upper slope height, no peak lift")
			if row == 0 or row == 20:
				_expect(uv[i].y == (0.0 if row == 0 else 1.0), tag + "Complete UV domain boundary")
			if row > 0:
				_expect(uv[i].y > uv[i - 1].y and p.y < vertices[i - 1].y, tag + "Monotone rows; no fold")
			var distance := -(camera.global_transform.affine_inverse() * card.to_global(p)).z
			_expect(distance > camera.near and distance < camera.far and distance > castle_far, tag + "Inside depth clip and behind entire castle")
			depth.x = minf(depth.x, p.z - offset.z)
			depth.y = maxf(depth.y, p.z - offset.z)
		for row in range(20 if col < 64 else 0):
			var a := col * 21 + row
			var start := (col * 20 + row) * 6
			var expected := PackedInt32Array([a, a + 21, a + 1, a + 1, a + 21, a + 22])
			for j in range(6):
				if not _expect(indices[start + j] == expected[j], tag + "Continuous canonical cell topology"):
					return false
	for t in range(0, indices.size(), 3):
		var a := indices[t]
		var b := indices[t + 1]
		var c := indices[t + 2]
		var front := (vertices[c] - vertices[a]).cross(vertices[b] - vertices[a])
		var area := (uv[b] - uv[a]).cross(uv[c] - uv[a]) * 0.5
		_expect(front.is_finite() and front.z > 0 and area > 0, tag + "Nondegenerate +Z winding and UV orientation")
		uv_area += area
		for i: int in [a, b, c]:
			summed[i] += front
	_expect(absf(uv_area - 1.0) < 0.00001, tag + "Full mesh UV area exactly one; no repeated PNG")
	var normal_error := 0.0
	for i in range(vertices.size()):
		normal_error = maxf(normal_error, normals[i].distance_to(summed[i].normalized()))
		_expect(normals[i].distance_to(summed[i].normalized()) < 0.0002 and absf(normals[i].length() - 1.0) < 0.0002, tag + "Actual area-weighted mesh normals")
	_expect(depth.y - depth.x > 0.1 if primary else maxf(absf(depth.x), absf(depth.y)) < 0.0001, tag + "Primary relief / right depth zero")
	if failed or _alpha(card, camera, terrain, ground, source, region, arrays, primary) != true:
		return false
	print("MOUNTAIN_HILLS_GEOMETRY: %s width=%.3f height=%.6f vertices=%d triangles=%d UVarea=%.9f depth=%s normal_error=%.9f" % [card.name, width, height, vertices.size(), indices.size() / 3, uv_area, str(depth), normal_error])
	return not failed

func _point(card: MeshInstance3D, arrays: Array, at: Vector2) -> Vector3:
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	var first := clampi(floori(at.x * 64), 0, 63) * 120
	for t in range(first, first + 120, 3):
		var a := indices[t]
		var b := indices[t + 1]
		var c := indices[t + 2]
		var ab := uv[b] - uv[a]
		var ac := uv[c] - uv[a]
		var wb := (at - uv[a]).cross(ac) / ab.cross(ac)
		var wc := ab.cross(at - uv[a]) / ab.cross(ac)
		if wb >= -1e-6 and wc >= -1e-6 and wb + wc <= 1.000001:
			return card.to_global(vertices[a] * (1 - wb - wc) + vertices[b] * wb + vertices[c] * wc)
	return Vector3(INF, INF, INF)

func _alpha(card: MeshInstance3D, camera: Camera3D, terrain: MeshInstance3D, ground: TriangleMesh, image: Image, region: Vector4, arrays: Array, primary: bool) -> bool:
	var roots: PackedVector2Array = card.get_meta("relief_root_uvs")
	var shifts: PackedFloat32Array = card.get_meta("relief_root_shifts")
	var production_hits: PackedByteArray = card.get_meta("relief_root_triangle_hits")
	if not _expect(roots.size() == shifts.size() and roots.size() == production_hits.size(), "Parallel root metadata"):
		return false
	var feet := 0
	var soil_roots := 0
	var unrendered_fallbacks := 0
	var terrain_bounds := terrain.mesh.get_aabb()
	var gap_range := Vector2(INF, -INF)
	var view_size := camera.get_viewport().get_visible_rect().size
	var threshold: Variant = card.material_override.get_shader_parameter("alpha_threshold")
	if not _expect(typeof(threshold) == TYPE_FLOAT and float(threshold) > 0 and float(threshold) < 1, "Actual finite alpha threshold"):
		return false
	var visible := 0
	var top_y := INF
	# Every source column in the crop, not a few manually selected peaks.
	for x in range(image.get_width()):
		var u := (float(x) / (image.get_width() - 1) - region.x) / region.z
		if u < 0 or u > 1:
			continue
		for y in range(image.get_height()):
			if image.get_pixel(x, y).a <= float(threshold):
				continue
			var p := _point(card, arrays, Vector2(u, float(y) / (image.get_height() - 1)))
			if not _expect(p.is_finite(), "Actual source silhouette registered to triangles"):
				return false
			var screen := camera.unproject_position(p) / view_size
			if screen.x >= 0 and screen.x <= 1:
				visible += 1
				top_y = minf(top_y, screen.y)
				_expect(screen.y >= (0.015 if primary else 0.0) and screen.y <= 1, "Visible-width skyline inside frame with primary top margin .015")
			break
	for col in range(65):
		var u := float(col) / 64
		var x := clampi(roundi((region.x + u * region.z) * (image.get_width() - 1)), 0, image.get_width() - 1)
		for y in range(image.get_height() - 1, -1, -1):
			if image.get_pixel(x, y).a <= 0.60:
				continue
			var at := Vector2(u, float(y) / (image.get_height() - 1))
			var p := _point(card, arrays, at)
			if not _expect(p.is_finite() and feet < roots.size(), "Actual opaque source root and metadata entry"):
				return false
			_expect(roots[feet].distance_to(at) < 1e-6 and is_finite(shifts[feet]), "Independently recovered source foot matches metadata")
			var base: Vector2 = card.get_meta("relief_base_size")
			var offset: Vector3 = card.get_meta("relief_base_offset")
			_expect(absf(card.to_local(p).y - offset.y - (0.5 - at.y) * base.y - shifts[feet]) < 0.0001, "Root shift metadata matches actual geometry")
			var hit := ground.intersect_ray(terrain.to_local(Vector3(p.x, 200, p.z)), (terrain.global_basis.inverse() * Vector3.DOWN).normalized())
			if hit.is_empty():
				# Explicit off-camera-margin scope correction, not a soil substitute.
				# A boundary point is IN bounds; either in-bounds or visible must hit.
				var local_root := terrain.to_local(p)
				var outside_terrain := local_root.x < terrain_bounds.position.x or local_root.x > terrain_bounds.end.x or local_root.z < terrain_bounds.position.z or local_root.z > terrain_bounds.end.z
				var screen := camera.unproject_position(p) / view_size
				var outside_view := screen.is_finite() and (screen.x < 0.0 or screen.x > 1.0)
				print("MOUNTAIN_HILLS_UNSUPPORTED_ROOT: %s column=%d world=%s screen_normalized=%s terrain_xz_outside=%s viewport_x_outside=%s production_hit=%d; NOT GROUNDED" % [card.name, col, str(p), str(screen), str(outside_terrain), str(outside_view), production_hits[feet]])
				if not _expect(outside_terrain and outside_view and production_hits[feet] == 0, "Unsupported root must be strictly OUTSIDE terrain XZ AND horizontal viewport, with production hit=0"):
					return false
				unrendered_fallbacks += 1
			else:
				_expect(production_hits[feet] == 1, "Actual terrain hit agrees with production metadata")
				var gap := p.y - terrain.to_global(Vector3(hit.position)).y
				gap_range.x = minf(gap_range.x, gap)
				gap_range.y = maxf(gap_range.y, gap)
				_expect(absf(gap + 0.05) <= 0.04, "Actual alpha root within .04m of terrain-.05")
				soil_roots += 1
			feet += 1
			break
	_expect(visible > 0 and feet > 0 and feet == roots.size(), "Nonempty silhouette/roots; no invented root metadata")
	# Independently scanned frozen PNG alpha>.60 at all 65 grid columns: both
	# have 63 roots; full hills columns 1..49 are in terrain XZ, 50..63 outside.
	# Those 14 candidates still require actual missing rays AND offscreen proof.
	_expect(soil_roots == (59 if primary else 49) and unrendered_fallbacks == (4 if primary else 14) and feet == 63 and soil_roots + unrendered_fallbacks == feet, "Frozen alpha contract: primary 59 soil/4 OUTSIDE; hills 49 soil/14 OUTSIDE; 63 each")
	print("MOUNTAIN_HILLS_ALPHA: %s visible_columns=%d top_y=%.6f roots=%d actual_soil_roots=%d unrendered_fallbacks=%d actual_terrain_gap=%s; OUTSIDE fallbacks NOT GROUNDED; sampled source-column feet, NOT every semantic tree root or GPU edge" % [card.name, visible, top_y, feet, soil_roots, unrendered_fallbacks, str(gap_range)])
	return not failed
