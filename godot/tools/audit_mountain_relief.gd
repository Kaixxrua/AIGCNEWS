extends SceneTree
## One actual scene. Geometry/state only; main owns serialized engine execution.
const SKY = preload("res://tools/audit_dragon_sky.gd")
const V96 = preload("res://tools/audit_mountain_material.gd")
var failed := false
var checks := 0

func _initialize() -> void:
	_run.call_deferred()

func _expect(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failed = true
		push_error("MEADOW_MOUNTAIN_RELIEF_AUDIT: FAIL; " + message)

func _run() -> void:
	# Reuse frozen hashes, not the obsolete v96 Quad/source-insertion assertions.
	for path: String in V96.PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == V96.PROTECTED[path], "Protected source " + path)
	var helper := "res://scripts/meadow_mountain_relief.gd"
	var helper_hash := FileAccess.get_sha256(helper)
	_expect(not helper_hash.is_empty(), "Relief helper exists")
	var exports := ConfigFile.new()
	_expect(exports.load("res://export_presets.cfg") == OK, "Export configuration")
	_expect(helper in exports.get_value("preset.0", "export_files", PackedStringArray()), "New helper explicitly exported")
	if failed:
		quit(1)
		return
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	root.add_child(scene)
	var mountain := scene.get_node("DistantMountainRidge") as MeshInstance3D
	var weather = scene.get_node("LivingWeather")
	weather.set_process(false)
	scene.get_node("LivingWildlife").set_process(false)
	var material := mountain.material_override as ShaderMaterial
	_expect(mountain.mesh is ArrayMesh and mountain.mesh.get_surface_count() == 1, "One actual ArrayMesh surface")
	_expect(material != null and material.shader.resource_path == "res://shaders/meadow_mountain_day.gdshader", "Actual supported-day mountain atmosphere material")
	if not failed:
		_expect(material.get_shader_parameter("mountain_normal_strength") == 0.0 and material.get_shader_parameter("relief_strength") == 0.0, "No profile or texture-rounded normal replacement")
		var wind: Variant = material.get_shader_parameter("wind_strength")
		if wind == null:
			_expect(FileAccess.get_file_as_string("res://shaders/meadow_cutout_surface.gdshaderinc").count("uniform float wind_strength = 0.0;") == 1, "Explicit zero shader default for unset wind")
			wind = 0.0
		_expect(material.get_shader_parameter("face_camera") == false and (typeof(wind) == TYPE_FLOAT or typeof(wind) == TYPE_INT) and float(wind) == 0.0, "Rigid world-space mountain")
		_expect(material.get_shader_parameter("asset_texture") == scene.HORIZON and material.get_shader_parameter("uv_region") == Vector4(0, 0, 1, 1), "Original full PNG, no crop/stamp")
		var consumers := 0
		for node: Node in scene.find_children("*", "MeshInstance3D", true, false):
			if node.material_override is ShaderMaterial and node.material_override.get_shader_parameter("asset_texture") == scene.HORIZON:
				consumers += 1
		_expect(consumers == 1, "Single PNG consumer in actual scene")
		_expect(mountain.find_children("*", "CollisionShape3D", true, false).is_empty(), "No new mountain collider")
		_geometry(scene, mountain)
	# No awaits or user-scene state: reset global values before freeing this scene.
	RenderingServer.global_shader_parameter_set("meadow_night", weather.night_blend)
	RenderingServer.global_shader_parameter_set("meadow_clock", weather.animation_clock)
	scene.free()
	_expect(FileAccess.get_sha256(helper) == helper_hash, "Helper stable during audit")
	print("MEADOW_MOUNTAIN_RELIEF_AUDIT: %s; checks=%d; actual topology/normals/UV/depth/alpha-foot/projection checks; NOT GPU lighting, whole-scene visual, night readability or performance acceptance" % ["FAIL" if failed else "PASS", checks])
	quit(1 if failed else 0)

func _geometry(scene: Node3D, card: MeshInstance3D) -> void:
	var arrays := card.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	_expect(vertices.size() > 4 and vertices.size() == normals.size() and vertices.size() == uv.size(), "Actual complete relief channels")
	_expect(indices.size() > 6 and indices.size() % 3 == 0 and card.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES, "Indexed triangles")
	if failed:
		return
	var unique_uv := {}
	var columns := {}
	var edge_counts := {}
	var area_normals := PackedVector3Array()
	area_normals.resize(vertices.size())
	var used := {}
	var depth := Vector2(INF, -INF)
	var view_depth := Vector2(INF, -INF)
	var camera: Camera3D = scene.camera
	var view_inverse := camera.global_transform.affine_inverse()
	for i in range(vertices.size()):
		_expect(vertices[i].is_finite() and normals[i].is_finite() and uv[i].is_finite(), "Finite vertex channels " + str(i))
		_expect(uv[i].x >= 0.0 and uv[i].x <= 1.0 and uv[i].y >= 0.0 and uv[i].y <= 1.0 and not unique_uv.has(uv[i]), "Unique bounded source UV " + str(i))
		unique_uv[uv[i]] = i
		if not columns.has(uv[i].x):
			columns[uv[i].x] = []
		columns[uv[i].x].append(i)
		_expect(absf(vertices[i].x - (uv[i].x - 0.5) * 650.0) <= 0.0001, "Original horizontal registration " + str(i))
		depth.x = minf(depth.x, vertices[i].z)
		depth.y = maxf(depth.y, vertices[i].z)
		var distance: float = -(view_inverse * card.to_global(vertices[i])).z
		view_depth.x = minf(view_depth.x, distance)
		view_depth.y = maxf(view_depth.y, distance)
		_expect(distance > camera.near and distance < camera.far, "Finite geometry inside depth clip planes " + str(i))
	var area := 0.0
	for triangle in range(0, indices.size(), 3):
		var a := indices[triangle]
		var b := indices[triangle + 1]
		var c := indices[triangle + 2]
		if a < 0 or b < 0 or c < 0 or a >= vertices.size() or b >= vertices.size() or c >= vertices.size():
			_expect(false, "Valid triangle indices")
			return
		var signed_uv := (uv[b] - uv[a]).cross(uv[c] - uv[a])
		var front := (vertices[c] - vertices[a]).cross(vertices[b] - vertices[a])
		_expect(signed_uv > 1e-12 and front.is_finite() and front.z > 0.0, "Nonfolded UV and clockwise +Z triangle " + str(triangle / 3))
		area += signed_uv * 0.5
		for index: int in [a, b, c]:
			used[index] = true
			area_normals[index] += front
		for edge: Vector2i in [Vector2i(a, b), Vector2i(b, c), Vector2i(c, a)]:
			var key := Vector2i(mini(edge.x, edge.y), maxi(edge.x, edge.y))
			var value: Vector2i = edge_counts.get(key, Vector2i.ZERO)
			value.x += 1
			value.y += 1 if edge.x < edge.y else -1
			edge_counts[key] = value
	_expect(absf(area - 1.0) <= 0.00001 and used.size() == vertices.size(), "Whole UV domain covered once; no unused vertices")
	var perimeter := 0.0
	for edge: Vector2i in edge_counts:
		var value: Vector2i = edge_counts[edge]
		_expect(value.x == 1 or (value.x == 2 and value.y == 0), "Manifold shared edge with opposite orientation")
		if value.x == 1:
			var a := uv[edge.x]
			var b := uv[edge.y]
			_expect((a.x == b.x and (a.x == 0.0 or a.x == 1.0)) or (a.y == b.y and (a.y == 0.0 or a.y == 1.0)), "Only domain border is open; no cracks")
			perimeter += a.distance_to(b)
	_expect(absf(perimeter - 4.0) <= 0.00001 and vertices.size() - edge_counts.size() + indices.size() / 3 == 1, "Single continuous disk topology")
	var max_normal_error := 0.0
	for i in range(vertices.size()):
		var error := normals[i].distance_to(area_normals[i].normalized())
		max_normal_error = maxf(max_normal_error, error)
		_expect(error < 0.0002 and absf(normals[i].length() - 1.0) < 0.0002, "Normal derived from actual triangles, allowing packed-normal quantization")
	_expect(depth.x < -0.1 and depth.y > 0.1, "Actual forward and rear relief, not metadata-only volume")
	for u: float in columns:
		var previous_y := INF
		var previous_v := -INF
		# Sort actual UVs; do not trust metadata grid dimensions or vertex ordering.
		var rows: Array = columns[u]
		rows.sort_custom(func(a: int, b: int) -> bool: return uv[a].y < uv[b].y)
		for index: int in rows:
			_expect(uv[index].y > previous_v and vertices[index].y < previous_y, "Monotone actual column; no geometric fold")
			previous_v = uv[index].y
			previous_y = vertices[index].y
	var castle := scene.get_node("IndependentCastleHill") as MeshInstance3D
	var castle_far := -INF
	for point: Vector3 in castle.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]:
		castle_far = maxf(castle_far, -(view_inverse * castle.to_global(point)).z)
	_expect(view_depth.x > castle_far, "Entire relief remains behind castle in camera depth; sufficient nonocclusion bound")
	var lookup: Dictionary = SKY.mountain_uv_lookup(card.mesh)
	var texture := card.material_override.get_shader_parameter("asset_texture") as Texture2D
	var source := texture.get_image()
	if source.is_compressed():
		_expect(source.decompress() == OK, "Decode original alpha")
	_projection_and_feet(scene, card, lookup, source, columns.keys())
	print("MEADOW_MOUNTAIN_RELIEF_GEOMETRY: vertices=%d triangles=%d columns=%d UVarea=%.9f depth=%s view_depth=%s castle_far=%.5f normal_error=%.9f; metadata not used as proof" % [vertices.size(), indices.size() / 3, columns.size(), area, str(depth), str(view_depth), castle_far, max_normal_error])

func _projection_and_feet(scene: Node3D, card: MeshInstance3D, lookup: Dictionary, source: Image, columns: Array) -> void:
	var size := scene.get_viewport().get_visible_rect().size
	var visible_tops := 0
	var cropped_tops := 0
	var lowest_top := INF
	for x in range(source.get_width()):
		var top := -1
		for y in range(source.get_height()):
			if source.get_pixel(x, y).a > 0.22:
				top = y
				break
		if top < 0:
			continue
		var at_uv := Vector2(float(x) / (source.get_width() - 1), float(top) / (source.get_height() - 1))
		var point: Vector3 = SKY.mountain_uv_point(card, at_uv, lookup)
		_expect(point.is_finite(), "Source silhouette lies on actual triangles")
		if not point.is_finite():
			continue
		var screen: Vector2 = scene.camera.unproject_position(point) / size
		if screen.x >= 0.0 and screen.x <= 1.0:
			visible_tops += 1
			lowest_top = minf(lowest_top, screen.y)
			_expect(screen.y >= 0.0 and screen.y <= 1.0, "Visible-width alpha skyline inside frame")
		else:
			cropped_tops += 1 # Original wide backdrop wings may extend outside frame.
	_expect(visible_tops > 0, "Nonempty actual visible skyline")
	var feet := 0
	var clearance := Vector2(INF, -INF)
	var root_depth := 0.0
	var positive_gaps := 0
	for u: float in columns:
		var x := clampi(roundi(u * (source.get_width() - 1)), 0, source.get_width() - 1)
		var bottom := -1
		for y in range(source.get_height() - 1, -1, -1):
			if source.get_pixel(x, y).a > 0.60:
				bottom = y
				break
		if bottom < 0:
			continue
		var point: Vector3 = SKY.mountain_uv_point(card, Vector2(u, float(bottom) / (source.get_height() - 1)), lookup)
		_expect(point.is_finite(), "Actual opaque alpha foot on mesh")
		if not point.is_finite():
			continue
		feet += 1
		root_depth = maxf(root_depth, absf(card.to_local(point).z))
		var gap: float = point.y - scene.terrain_height(point.x, point.z)
		clearance.x = minf(clearance.x, gap)
		clearance.y = maxf(clearance.y, gap)
		if gap > 0.0:
			positive_gaps += 1
	_expect(feet > 0 and root_depth <= 0.001, "Nonempty alpha feet remain on original depth plane")
	print("MEADOW_MOUNTAIN_RELIEF_PLACEMENT: visible_alpha_columns=%d cropped_wings=%d top_y=%.6f feet=%d terrain_function_gap=%s positive_gaps=%d root_depth=%.6f; gap is diagnostic, NOT terrain attachment PASS; source-foot columns, not every alpha-edge texel or collision support" % [visible_tops, cropped_tops, lowest_top, feet, str(clearance), positive_gaps, root_depth])
