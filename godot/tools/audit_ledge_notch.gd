extends SceneTree
## v110 fixed-contract cache comparison. No main scene, bake, AO apply or rendering.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const C := Vector2(-36.388867, -20.323368)
const T := Vector2(-0.885018018, 0.465556773)
const N := Vector2(0.465556773, 0.885018018)
const BASE := {"terrain": "65da9650732e4891b245f688c7b05f5af2d305a8ff973605845cee3a5e9f60ac", "detail": "f8f5508ed3c6194718ffef14e577e99a06b11863e3fed789d7fe4d9804d23e65"}
const PROTECTED := {"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08", "res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b", "res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d", "res://scripts/meadow_weather.gd": "7afda1a94783bf28b48f860fa6a174220cc63a387d14ea094b16953c8ae4d5c9"}
var failures := 0
var failure_categories := {}
var failure_examples := {}
var checks := 0
var files := {}
var loaded: Array[Node] = []
var stats := {}
var support_faces := PackedVector3Array()
var support_query: TriangleMesh
var terrain_before: Mesh
var terrain_after: Mesh
var meshes := 0
var collisions := 0
var leaf_source_before: GDScript
var leaf_source_after: GDScript

func _initialize() -> void:
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failures += 1
		var category := label.get_slice(" corner=", 0).get_slice(" tri=", 0).get_slice(" old=", 0)
		failure_categories[category] = int(failure_categories.get(category, 0)) + 1
		if not failure_examples.has(category): failure_examples[category] = []
		var examples: Array = failure_examples[category]
		if examples.size() < 3:
			examples.append(label)
			push_error("LEDGE_NOTCH: " + label)
	return value

func _run() -> void:
	quit(1)
	var complete: Variant = _verify()
	for node in loaded: node.free()
	for path: String in files: _ok(FileAccess.get_sha256(path) == files[path], "File changed during audit: " + path)
	var passed: bool = complete == true and failures == 0
	if OS.get_cmdline_user_args().has("--geometry-only"):
		print("LEDGE_NOTCH_DIAGNOSTIC: ", "COMPLETE" if passed else "ERROR", "; ", JSON.stringify({"full_audit": false, "checks": checks, "failures": failures, "measurements": stats, "files": files, "limits": "diagnostic output only, NOT geometry acceptance/full PASS; skips full scope/collision/AO checks"}))
		quit(0 if passed else 1)
		return
	print("LEDGE_NOTCH_AUDIT: ", "PASS" if passed else "FAIL", "; ", JSON.stringify({"checks": checks, "failures": failures, "failure_categories": failure_categories, "failure_examples": failure_examples, "meshes": meshes, "collisions": collisions, "measurements": stats, "files": files, "AO": "NOT_TESTED: fresh v110 sidecar/signatures require separate audit after bake", "limits": "inert cached geometry only; projected displacement is not visibility/visual/GPU acceptance; no main runtime attachments"}))
	quit(0 if passed else 1)

func _bundle(path: String) -> Node:
	if not _ok(FileAccess.file_exists(path), "Missing cache " + path): return null
	files[path] = FileAccess.get_sha256(path)
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
	if not _ok(packed != null, "Load cache " + path): return null
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				if not _ok(state.get_node_property_value(i, j) == null, "Reject scripted cache before instantiation"): return null
	var node := packed.instantiate()
	loaded.append(node) # Deliberately never added to the tree.
	return node

func _inside(p: Vector3) -> bool:
	var d := Vector2(p.x, p.z) - C
	return d.dot(T) > -1.15 and d.dot(T) < 1.85 and d.dot(N) > -2.10 and d.dot(N) < 1.45

func _normal_domain(p: Vector3) -> bool:
	# Exact union of four world-axis samples, not a relaxed rectangular margin.
	return _inside(p + Vector3(0.22, 0, 0)) or _inside(p - Vector3(0.22, 0, 0)) or _inside(p + Vector3(0, 0, 0.22)) or _inside(p - Vector3(0, 0, 0.22))

func _expanded(mesh: Mesh, label: String) -> Array:
	if not _ok(mesh is ArrayMesh and mesh.get_surface_count() == 1, "One actual ArrayMesh surface"): return []
	if not _ok(mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES and mesh.get_blend_shape_count() == 0, "Static triangles"): return []
	var a := mesh.surface_get_arrays(0)
	for channel in range(Mesh.ARRAY_MAX):
		print("LEDGE_NOTCH_CHANNEL: ", label, " channel=", channel, " type=", type_string(typeof(a[channel])), " size=", 0 if a[channel] == null else a[channel].size())
	var ids: PackedInt32Array = a[Mesh.ARRAY_INDEX] if a[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
	var count: int = a[Mesh.ARRAY_VERTEX].size() if ids.is_empty() else ids.size()
	if not _ok(count > 0 and count % 3 == 0, "Nonempty triangle corners"): return []
	var out: Array = []
	out.resize(Mesh.ARRAY_MAX)
	for channel in range(Mesh.ARRAY_INDEX):
		if a[channel] == null: continue
		if not _ok(typeof(a[channel]) in [TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_FLOAT32_ARRAY, TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_VECTOR2_ARRAY, TYPE_PACKED_VECTOR3_ARRAY, TYPE_PACKED_COLOR_ARRAY, TYPE_PACKED_VECTOR4_ARRAY], "Packed mesh channel " + str(channel)): return []
		if a[channel].is_empty():
			if not _ok(channel not in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL], "Required geometry channel nonempty"): return []
			out[channel] = a[channel].duplicate() # Preserve typed empty, never convert to null.
			continue
		if not _ok(channel in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2], "Unsupported NONEMPTY packed/custom channel=" + str(channel)): return []
		var stride := 4 if channel == Mesh.ARRAY_TANGENT else 1
		if channel == Mesh.ARRAY_TANGENT:
			if not _ok(typeof(a[channel]) in [TYPE_PACKED_FLOAT32_ARRAY, TYPE_PACKED_FLOAT64_ARRAY], "Tangent packed scalar type"): return []
		if not _ok(a[channel].size() == a[Mesh.ARRAY_VERTEX].size() * stride, "Per-vertex channel length/stride channel=" + str(channel)): return []
		var values: Variant = a[channel].duplicate()
		values.resize(count * stride)
		for i in range(count):
			var id: int = i if ids.is_empty() else ids[i]
			if not _ok(id >= 0 and id < a[Mesh.ARRAY_VERTEX].size(), "Valid vertex index"): return []
			for component in range(stride): values[i * stride + component] = a[channel][id * stride + component]
		out[channel] = values
	return out

func _same_corner(a: Array, b: Array, channel: int, corner: int) -> bool:
	var stride := 4 if channel == Mesh.ARRAY_TANGENT else 1
	for component in range(stride):
		if a[channel][corner * stride + component] != b[channel][corner * stride + component]: return false
	return true

func _ground_tangent(a: Array, b: Array, corner: int) -> void:
	# Current _array_mesh omits tangents; _index_meshes skips indexed terrain.
	# Godot 4.7.2 synthesizes each missing tangent from that vertex's normal,
	# NOT a MikkTSpace/SurfaceTool triangle average. Thus _normal_domain is
	# sufficient; no rectangular expansion or even a topological one-ring.
	# Primary: https://raw.githubusercontent.com/godotengine/godot/4.7.2-stable/servers/rendering/rendering_server.cpp (ARRAY_TANGENT, lines 623-644).
	# Independently test the frame, not a copied generator. 1e-3 accommodates
	# separate uint16 octahedral normal/tangent quantization (tangent sign bit).
	for data: Array in [a, b]:
		var tangent: Variant = data[Mesh.ARRAY_TANGENT]
		var k := corner * 4
		var t := Vector3(tangent[k], tangent[k + 1], tangent[k + 2])
		var n: Vector3 = data[Mesh.ARRAY_NORMAL][corner]
		_ok(t.is_finite() and n.is_finite() and is_finite(tangent[k + 3]), "Ground derived tangent finite")
		_ok(absf(t.length() - 1.0) <= 0.001 and absf(n.length() - 1.0) <= 0.001, "Ground derived tangent/normal unit length")
		_ok(absf(t.dot(n)) <= 0.001, "Ground derived tangent orthogonal to actual normal")
		_ok(tangent[k + 3] == 1.0, "Ground synthesized tangent handedness +1")
	_ok(a[Mesh.ARRAY_TANGENT][corner * 4 + 3] == b[Mesh.ARRAY_TANGENT][corner * 4 + 3], "Ground exact preserved handedness")

func _caps(a: Array) -> PackedInt32Array:
	var result := PackedInt32Array()
	var colors: PackedColorArray = a[Mesh.ARRAY_COLOR]
	var i := 0
	while i < colors.size():
		var color := colors[i]
		# COLOR is UNORM8: tolerate one code for the known .94/.5 tag only.
		if color.r == 1.0 and absf(color.g - 0.94) <= 1.0 / 255.0 and absf(color.b - 0.5) <= 1.0 / 255.0 and color.a == 1.0:
			if not _ok(i >= 216 and i + 6 <= colors.size(), "Cap follows six 12-triangle wall beds"): return result
			for j in range(6): _ok(colors[i + j] == color, "Two complete turf cap triangles")
			result.append(i)
			i += 6
		else: i += 3
	return result

func _rock_domain(node: MeshInstance3D, a: Array, b: Array) -> PackedByteArray:
	var mask := PackedByteArray()
	mask.resize(a[Mesh.ARRAY_VERTEX].size())
	var ca := _caps(a)
	var cb := _caps(b)
	if not _ok(ca == cb, "Cap corner positions/order retained"): return mask
	var faces: PackedVector4Array = node.get_meta("terrace_faces", PackedVector4Array())
	if not _ok(faces.size() > 0 and ca.size() >= faces.size(), "Real caps cover recorded terrace segments"): return mask
	var selected := 0
	var ground_query := terrain_after.generate_triangle_mesh()
	for f in range(faces.size()):
		var step := roundi(faces[f].y * 194.0 / TAU)
		if int(faces[f].x) != 0 or step < 49 or step > 52: continue
		selected += 1
		var start := ca[f] - 216
		var end := ca[f + 1] - 216 if f + 1 < ca.size() else mask.size()
		for i in range(start, end): mask[i] = 1
		# Read the real cap corners, not a helper-provided crease position.
		var unique: Array[Vector3] = []
		for i in range(ca[f], ca[f] + 6):
			var p: Vector3 = b[Mesh.ARRAY_VERTEX][i]
			if not unique.has(p): unique.append(p)
		_ok(unique.size() == 4, "Cap has four shared vertices step=" + str(step))
		var shared := 0
		var rear_max_gap := 0.0
		for p in unique:
			var is_front := false
			for i in range(start + 180, ca[f]):
				if b[Mesh.ARRAY_VERTEX][i] == p:
					shared += 1
					is_front = true
					break
			if not is_front:
				var hit := ground_query.intersect_ray(Vector3(p.x, 100, p.z), Vector3.DOWN)
				_ok(not hit.is_empty(), "Cap rear has actual terrain triangles beneath")
				if not hit.is_empty(): rear_max_gap = maxf(rear_max_gap, absf(p.y - Vector3(hit.position).y - 0.012))
		_ok(shared == 2, "Actual cap/front shares both last-bed endpoints step=" + str(step))
		# Source rear=height_function+.012 is not necessarily mesh-ray+.012:
		# print tessellation error, do not invent a new contact tolerance here.
		print("LEDGE_NOTCH_SEGMENT: step=", step, " corners=[", start, ",", end, ") cap=", ca[f], " rear_mesh_error_from_012=", rear_max_gap)
	_ok(selected == 4, "Exactly frozen terrace0 steps49..52 exist")
	return mask

func _project(p: Vector3) -> Vector2:
	# Same fixed 48-degree vertical FOV, 16:10 composition; no rendering needed.
	var view := Transform3D(Basis.IDENTITY, Vector3(0, 18, 39)).looking_at(Vector3(0, 0, -27))
	var q := view.affine_inverse() * p
	var scale := -q.z * tan(deg_to_rad(24.0))
	return Vector2(0.5 + q.x / (scale * 3.2), 0.5 - q.y / (scale * 2.0))

func _mesh(a_node: MeshInstance3D, b_node: MeshInstance3D) -> bool:
	meshes += 1
	var label := str(a_node.name)
	var a := _expanded(a_node.mesh, label + "/before")
	var b := _expanded(b_node.mesh, label + "/after")
	if a.is_empty() or b.is_empty(): return false
	var av: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
	var bv: PackedVector3Array = b[Mesh.ARRAY_VERTEX]
	if not _ok(av.size() == bv.size(), label + " corner count changed: possible rejection/random-stream reorder old=%d new=%d" % [av.size(), bv.size()]): return false
	for channel in range(Mesh.ARRAY_INDEX):
		if not _ok(typeof(a[channel]) == typeof(b[channel]), label + " channel presence/type"): return false
		if a[channel] != null:
			if not _ok(a[channel].size() == b[channel].size(), label + " exact expanded channel size/empty state channel=" + str(channel)): return false
			if a[channel].is_empty():
				if not _ok(a[channel] == b[channel], label + " exact typed empty channel=" + str(channel)): return false
	var ground := label == "ContinuousMeadow"
	var rock := label == "SolidLimestoneGeology"
	var mask := PackedByteArray()
	if ground:
		terrain_before = a_node.mesh
		terrain_after = b_node.mesh
		_ok(a_node.mesh.surface_get_arrays(0)[Mesh.ARRAY_INDEX] == b_node.mesh.surface_get_arrays(0)[Mesh.ARRAY_INDEX], "Terrain fixed original indices")
	elif rock:
		_ok(a_node.get_meta("terrace_faces") == b_node.get_meta("terrace_faces"), "Wall segment identity retained")
		mask = _rock_domain(a_node, a, b)
	else:
		return _leaves(label, a, b)
	var changed := 0
	var protected_corners := 0
	var max_drop := 0.0
	var projected_pixels := 0.0
	var tangent_deltas_inside := 0
	var tangent_deltas_outside := 0
	var tangent_checks := 0
	for i in range(0, av.size(), 3):
		var affected := (_inside(av[i]) or _inside(av[i + 1]) or _inside(av[i + 2])) if ground else mask[i] == 1
		if affected:
			for j in range(3): support_faces.append(av[i + j])
		var triangle_changed := false
		for j in range(i, i + 3):
			var position_allowed := _inside(av[j]) if ground else affected
			var normal_allowed := _normal_domain(av[j]) if ground else affected
			var delta := bv[j] - av[j]
			_ok(bv[j].is_finite() and b[Mesh.ARRAY_NORMAL][j].is_finite(), label + " finite geometry")
			if ground: _ok(av[j].x == bv[j].x and av[j].z == bv[j].z, "Terrain exact XZ")
			if not position_allowed: _ok(av[j] == bv[j], label + " OUTSIDE exact position corner=" + str(j) + " old=" + str(av[j]) + " new=" + str(bv[j]))
			if position_allowed: _ok(delta.y <= 0.00001 and delta.y >= (-0.82001 if ground else -0.90001), label + " bounded downward deformation")
			if delta != Vector3.ZERO:
				changed += 1
				triangle_changed = true
				max_drop = maxf(max_drop, -delta.y)
				var screen := _project(av[j])
				if Rect2(0, 0, 1, 1).has_point(screen): projected_pixels = maxf(projected_pixels, (_project(bv[j]) - screen).length() * 1440.0)
			if not position_allowed and not normal_allowed: protected_corners += 1
			for channel in range(1, Mesh.ARRAY_INDEX):
				if a[channel] == null or a[channel].is_empty(): continue
				var allowed := normal_allowed if channel == Mesh.ARRAY_NORMAL else (not ground and affected)
				if ground and channel == Mesh.ARRAY_TANGENT:
					allowed = normal_allowed
					if not _same_corner(a, b, channel, j):
						if allowed: tangent_deltas_inside += 1
						else: tangent_deltas_outside += 1
					if allowed:
						_ground_tangent(a, b, j)
						tangent_checks += 1
				if not allowed: _ok(_same_corner(a, b, channel, j), label + " exact protected channel=%d corner=%d" % [channel, j])
		if triangle_changed:
			var old_normal := (av[i + 2] - av[i]).cross(av[i + 1] - av[i])
			var new_normal := (bv[i + 2] - bv[i]).cross(bv[i + 1] - bv[i])
			_ok(new_normal.length_squared() > 1e-14 and old_normal.dot(new_normal) > 0.0, label + " nondegenerate/no reversed winding tri=" + str(i / 3))
	_ok(changed > 0 and max_drop > 0.01 and projected_pixels > 0.1, label + " nonzero in-frame geometric notch")
	stats[label] = {"changed_corners": changed, "protected_corners": protected_corners, "max_drop": max_drop, "max_projected_displacement_px": projected_pixels, "ground_tangent_delta_inside_normal_domain": tangent_deltas_inside, "ground_tangent_delta_OUTSIDE": tangent_deltas_outside, "ground_tangent_frame_checks_corners": tangent_checks}
	return true

func _leaves(label: String, a: Array, b: Array) -> bool:
	if support_query == null:
		support_query = TriangleMesh.new()
		support_query.create_from_faces(support_faces)
	var av: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
	var bv: PackedVector3Array = b[Mesh.ARRAY_VERTEX]
	var i := 0
	var moved := 0
	var reframed := 0
	while i < av.size():
		if not _ok(i + 15 <= av.size(), label + " complete leaf group"): return false
		var flower: bool = a[Mesh.ARRAY_TEX_UV][i] == Vector2(-999, -999)
		var oval: bool = not flower and a[Mesh.ARRAY_COLOR][i + 1].a == 1.0
		var count := 18 if oval else 15
		if not _ok(i + count <= av.size(), label + " complete actual leaf topology"): return false
		var root_point: Vector3 = av[i] if oval or flower else (av[i] + av[i + 2]) * 0.5
		var delta := bv[i] - av[i]
		var local_change := false
		var frame_change := false
		for j in range(i, i + count):
			frame_change = frame_change or not _same_corner(a, b, Mesh.ARRAY_NORMAL, j) or not _same_corner(a, b, Mesh.ARRAY_TANGENT, j)
		var allow_frame := false
		if frame_change and label == "LivingMeadowUnderstory" and not oval and not flower and _normal_domain(root_point):
			# This only verifies the established shading-input dependency. Scope,
			# displacement, collision and actual leaf edges remain cache-derived.
			allow_frame = _leaf_frame(a, b, i, count, root_point)
			if allow_frame: reframed += 1
		for j in range(i, i + count):
			_ok(bv[j].is_finite(), label + " finite actual leaf vertex")
			local_change = local_change or av[j] != bv[j]
			for channel in range(1, Mesh.ARRAY_INDEX):
				if allow_frame and channel in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT]: continue
				if a[channel] != null and not a[channel].is_empty(): _ok(_same_corner(a, b, channel, j), label + " exact leaf attributes corner=%d channel=%d" % [j, channel])
		if local_change:
			moved += 1
			var hit := support_query.intersect_ray(Vector3(root_point.x, 100, root_point.z), Vector3.DOWN)
			var supported: bool = _inside(root_point) or (not hit.is_empty() and absf(root_point.y - Vector3(hit.position).y) <= 0.08)
			_ok(supported, label + " OUTSIDE unsupported leaf group corner=" + str(i) + " root=" + str(root_point))
			_ok(delta.x == 0.0 and delta.z == 0.0 and delta.y <= 0.0 and delta.y >= -0.90001, label + " leaf only moves down")
			for j in range(i, i + count): _ok((bv[j] - av[j] - delta).length() <= 0.00001, label + " rigid leaf translation (float32 storage tolerance)")
		i += count
	stats[label] = {"corners": av.size(), "moved_groups": moved, "source_verified_local_frame_groups": reframed}
	return true

func _leaf_shading_sources() -> bool:
	if leaf_source_before != null and leaf_source_after != null: return true
	var old_path := ProjectSettings.globalize_path("res://../artifacts/v110/meadow_scene.v109-before.gd").simplify_path()
	if not _ok(FileAccess.get_sha256(old_path) == "6b8438126308383b3ca9335b2754d020e1540f4d1fedd0eac679bc56d39abe05", "Frozen original leaf shading input source"): return false
	files[old_path] = FileAccess.get_sha256(old_path)
	# Compile static functions only: never instantiate either scene script,
	# load main.tscn, call ready/build, or modify the frozen source.
	leaf_source_before = GDScript.new()
	leaf_source_before.source_code = FileAccess.get_file_as_string(old_path)
	if not _ok(leaf_source_before.reload() == OK, "Compile original static shading source"): return false
	leaf_source_after = load("res://scripts/meadow_scene.gd") as GDScript
	return _ok(leaf_source_after != null, "Current static shading source")

func _leaf_frame(a: Array, b: Array, first: int, count: int, root_point: Vector3) -> bool:
	if not _leaf_shading_sources(): return false
	var previous: Variant = leaf_source_before.call("terrain_normal", root_point.x, root_point.z)
	var current: Variant = leaf_source_after.call("terrain_normal", root_point.x, root_point.z)
	if not _ok(typeof(previous) == TYPE_VECTOR3 and typeof(current) == TYPE_VECTOR3, "Actual static soil-normal inputs"): return false
	var old_soil: Vector3 = previous
	var new_soil: Vector3 = current
	if not _ok(old_soil.is_finite() and new_soil.is_finite() and old_soil.distance_to(new_soil) > 0.0000001, "Local leaf source normal really changed"): return false
	_ok(old_soil.y >= 0.88999 and new_soil.y >= 0.88999, "Both soil inputs satisfy original Living slope acceptance")
	var old_span: Vector3 = a[Mesh.ARRAY_VERTEX][first + 2] - a[Mesh.ARRAY_VERTEX][first]
	var new_span: Vector3 = b[Mesh.ARRAY_VERTEX][first + 2] - b[Mesh.ARRAY_VERTEX][first]
	if not _ok(old_span.length() > 0.0001 and old_span == new_span and old_span.y == 0.0, "Actual unchanged blade root-width direction"): return false
	var spread := old_span.normalized()
	var art_bias := Vector3(spread.z, 0.2, -spread.x) * 0.25
	var expected_old := (old_soil * 0.80 + art_bias).normalized()
	var expected_new := (new_soil * 0.80 + art_bias).normalized()
	var max_error := 0.0
	var max_nd := 0.0
	var max_td := 0.0
	var initial_failures := failures
	for j in range(first, first + count):
		var old_n: Vector3 = a[Mesh.ARRAY_NORMAL][j]
		var new_n: Vector3 = b[Mesh.ARRAY_NORMAL][j]
		var old_t := _tan(a, j)
		var new_t := _tan(b, j)
		max_error = maxf(max_error, maxf(old_n.distance_to(expected_old), new_n.distance_to(expected_new)))
		max_nd = maxf(max_nd, old_n.distance_to(new_n))
		max_td = maxf(max_td, (new_t - old_t).length())
		# 1e-3 is a storage/reconstruction bound: octahedral normal/tangent
		# packing plus float32 root and small blade-width reconstruction; not
		# fitted to the .11 source-driven change and not a visual tolerance.
		_ok(old_n.distance_to(expected_old) <= 0.001 and new_n.distance_to(expected_new) <= 0.001, "Local leaf follows soil/art-normal direction")
		for pair: Array in [[old_n, old_t], [new_n, new_t]]:
			var n: Vector3 = pair[0]
			var t4: Vector4 = pair[1]
			var t := Vector3(t4.x, t4.y, t4.z)
			_ok(n.is_finite() and t4.is_finite(), "Local leaf shading frame finite")
			_ok(absf(n.length() - 1.0) <= 0.001 and absf(t.length() - 1.0) <= 0.001, "Local leaf shading frame unit length")
			_ok(absf(n.dot(t)) <= 0.001, "Local leaf shading frame orthogonal")
		_ok(old_t.w == new_t.w and new_t.w == 1.0, "Local leaf exact original handedness")
	# Position rigidity applies even to normal-only groups; no hidden leaf reshape.
	var shift: Vector3 = b[Mesh.ARRAY_VERTEX][first] - a[Mesh.ARRAY_VERTEX][first]
	for j in range(first, first + count):
		_ok((b[Mesh.ARRAY_VERTEX][j] - a[Mesh.ARRAY_VERTEX][j] - shift).length() <= 0.00001, "Local reframed leaf retains actual rigid geometry")
	print("LEDGE_NOTCH_LEAF_FRAME: ", JSON.stringify({"first_corner": first, "root": _xyz(root_point), "source_normal_old": _xyz(old_soil), "source_normal_new": _xyz(new_soil), "max_expected_normal_error": max_error, "max_normal_delta": max_nd, "max_tangent4_delta": max_td, "scope": "Living ordinary blade/root in fixed normal-sampling domain; static shading-input verification only"}))
	return failures == initial_failures

func _tree(a: Node, b: Node, mesh: Mesh = null) -> bool:
	if not _ok(a.name == b.name and a.get_class() == b.get_class() and a.get_child_count() == b.get_child_count(), "Exact cache tree " + str(a.name)): return false
	if a is Node3D: _ok(a.transform == b.transform and a.transform == Transform3D.IDENTITY and a.visible == b.visible, "Identity/exact cache placement " + str(a.name))
	if a is MeshInstance3D:
		_ok(a.layers == b.layers and a.cast_shadow == b.cast_shadow and a.extra_cull_margin == b.extra_cull_margin, "Render flags retained")
		if not _mesh(a, b): return false
		mesh = b.mesh
	if a is CollisionObject3D: _ok(a.collision_layer == b.collision_layer and a.collision_mask == b.collision_mask, "Collision filters retained")
	if a is CollisionShape3D:
		collisions += 1
		if not _ok(a.shape is ConcavePolygonShape3D and b.shape is ConcavePolygonShape3D and mesh != null, "Known actual collision mesh"): return false
		_ok(a.disabled == b.disabled and a.shape.margin == b.shape.margin and a.shape.backface_collision == b.shape.backface_collision, "Collision configuration retained")
		_ok(b.shape.get_faces() == mesh.get_faces(), "Actual collision exactly follows new rendered triangles")
		var old_parent := a.get_parent().get_parent() as MeshInstance3D
		_ok(old_parent != null and a.shape.get_faces() == old_parent.mesh.get_faces(), "Baseline collision also matches original mesh")
	for i in range(a.get_child_count()):
		if not _tree(a.get_child(i), b.get_child(i), mesh): return false
	return true

func _verify() -> bool:
	for arg: String in OS.get_cmdline_user_args():
		if not _ok(not arg.contains("bake") and not arg.contains("rebuild"), "No generation flags"): return false
	if OS.get_cmdline_user_args().has("--geometry-only"): return _diagnose()
	for path: String in PROTECTED:
		_ok(FileAccess.get_sha256(path) == PROTECTED[path], "Protected source " + path)
		files[path] = FileAccess.get_sha256(path)
	var signature: String = CACHE.signature()
	for path: String in CACHE.SOURCES: files[path] = FileAccess.get_sha256(path)
	for group: String in ["terrain", "detail"]:
		var old_path := ProjectSettings.globalize_path("res://../artifacts/v110/" + group + ".v109-before.scn").simplify_path()
		if not _ok(FileAccess.get_sha256(old_path) == BASE[group], "Pinned v109 baseline " + group): return false
		var before := _bundle(old_path)
		var after := _bundle(CACHE.DIRECTORY + group + ".scn")
		if before == null or after == null: return false
		_ok(after.get_meta("source_signature", "") == signature and before.get_meta("source_signature", "") != signature, "Actual fresh v110 cache signature " + group)
		_ok(before.get_meta("cache_version", "") == CACHE.VERSION and after.get_meta("cache_version", "") == CACHE.VERSION, "Cache schema retained")
		if not _tree(before, after): return false
	_ok(meshes == 5 and collisions == 2, "Both bundles/all five meshes/two actual colliders covered")
	_ok(CACHE.signature() == signature, "Source stable throughout comparison")
	# Exact outside-domain triangles above + exact mesh/collider correspondence
	# protect every central/Boss triangle, not just a few height-function samples.
	stats["current_cache_signature"] = signature
	return true

# Diagnostic path reads raw indexed channels, avoiding expanded arrays and the
# full 54-million-check traversal. It may inspect a cache while A edits source;
# cached file hashes are frozen, but no claim of current source readiness is made.
func _xyz(p: Vector3) -> Array:
	return [p.x, p.y, p.z]

func _raw(mesh: Mesh) -> Array:
	if not _ok(mesh is ArrayMesh and mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES, "Diagnostic actual triangle surface"): return []
	var a := mesh.surface_get_arrays(0)
	var vertices: int = a[Mesh.ARRAY_VERTEX].size()
	if not _ok(vertices > 0 and a[Mesh.ARRAY_NORMAL] != null and a[Mesh.ARRAY_NORMAL].size() == vertices, "Diagnostic actual normals"): return []
	if not _ok(a[Mesh.ARRAY_TANGENT] != null and a[Mesh.ARRAY_TANGENT].size() == vertices * 4, "Diagnostic actual four-component tangents"): return []
	var count := _corner_count(a)
	if not _ok(count > 0 and count % 3 == 0, "Diagnostic full triangles"): return []
	if a[Mesh.ARRAY_INDEX] != null:
		for id: int in a[Mesh.ARRAY_INDEX]:
			if not _ok(id >= 0 and id < vertices, "Diagnostic index in range"): return []
	return a

func _corner_count(a: Array) -> int:
	return a[Mesh.ARRAY_VERTEX].size() if a[Mesh.ARRAY_INDEX] == null or a[Mesh.ARRAY_INDEX].is_empty() else a[Mesh.ARRAY_INDEX].size()

func _id(a: Array, corner: int) -> int:
	return corner if a[Mesh.ARRAY_INDEX] == null or a[Mesh.ARRAY_INDEX].is_empty() else a[Mesh.ARRAY_INDEX][corner]

func _tan(a: Array, id: int) -> Vector4:
	var t: Variant = a[Mesh.ARRAY_TANGENT]
	return Vector4(t[id * 4], t[id * 4 + 1], t[id * 4 + 2], t[id * 4 + 3])

func _triangle_data(a: Array, b: Array, triangle: int) -> Dictionary:
	var old: Array[Vector3] = []
	var new: Array[Vector3] = []
	var corners: Array = []
	for j in range(triangle * 3, triangle * 3 + 3):
		var ai := _id(a, j)
		var bi := _id(b, j)
		var p: Vector3 = a[Mesh.ARRAY_VERTEX][ai]
		var q: Vector3 = b[Mesh.ARRAY_VERTEX][bi]
		var an: Vector3 = a[Mesh.ARRAY_NORMAL][ai]
		var bn: Vector3 = b[Mesh.ARRAY_NORMAL][bi]
		old.append(p)
		new.append(q)
		corners.append({"corner": j, "old_vertex_id": ai, "new_vertex_id": bi, "old_xyz": _xyz(p), "new_xyz": _xyz(q), "delta_xyz": _xyz(q - p), "delta_magnitude": q.distance_to(p), "old_normal": _xyz(an), "new_normal": _xyz(bn), "normal_delta": an.distance_to(bn), "normal_dot": an.dot(bn), "normal_lengths": [an.length(), bn.length()]})
	var x := (old[2] - old[0]).cross(old[1] - old[0])
	var y := (new[2] - new[0]).cross(new[1] - new[0])
	return {"triangle": triangle, "corners": corners, "old_clockwise_cross": _xyz(x), "new_clockwise_cross": _xyz(y), "cross_dot": x.dot(y), "unit_geometric_normal_dot": x.normalized().dot(y.normalized()), "old_twice_area": x.length(), "new_twice_area": y.length(), "new_area_squared": y.length_squared()}

func _diagnose() -> bool:
	var baseline := ProjectSettings.globalize_path("res://../artifacts/v110/detail.v109-before.scn").simplify_path()
	if not _ok(FileAccess.get_sha256(baseline) == BASE.detail, "Diagnostic pinned original detail"): return false
	var before := _bundle(baseline)
	var after := _bundle(CACHE.DIRECTORY + "detail.scn")
	if before == null or after == null: return false
	stats["actual_cached_signature"] = after.get_meta("source_signature", "")
	for name: String in ["SolidLimestoneGeology", "LivingMeadowUnderstory"]:
		var old_node := before.get_node_or_null(NodePath(name)) as MeshInstance3D
		var new_node := after.get_node_or_null(NodePath(name)) as MeshInstance3D
		if not _ok(old_node != null and new_node != null, "Diagnostic nodes " + name): return false
		var a := _raw(old_node.mesh)
		var b := _raw(new_node.mesh)
		if a.is_empty() or b.is_empty(): return false
		if not _ok(_corner_count(a) == _corner_count(b), "Diagnostic corner correspondence " + name): return false
		if name == "LivingMeadowUnderstory":
			if not _diagnose_leaves(a, b): return false
			continue
		var selected := {}
		for triangle: int in [4888, 5121, 5204]: selected[triangle] = true
		var violations := 0
		for j in range(_corner_count(a)):
			var p: Vector3 = a[Mesh.ARRAY_VERTEX][_id(a, j)]
			var q: Vector3 = b[Mesh.ARRAY_VERTEX][_id(b, j)]
			var delta := q - p
			if delta.y <= 0.00001 and delta.y >= -0.90001: continue
			violations += 1
			if violations <= 100:
				selected[j / 3] = true
				var d := Vector2(p.x, p.z) - C
				print("LEDGE_NOTCH_DIAG_CORNER: ", JSON.stringify({"corner": j, "triangle": j / 3, "old_xyz": _xyz(p), "new_xyz": _xyz(q), "delta_xyz": _xyz(delta), "magnitude": delta.length(), "old_s_r": [d.dot(T), d.dot(N)], "old_inside_height_domain": _inside(p)}))
		for triangle: int in selected:
			if not _ok(triangle * 3 + 2 < _corner_count(a), "Diagnostic requested triangle exists"): return false
			print("LEDGE_NOTCH_DIAG_TRIANGLE: ", JSON.stringify(_triangle_data(a, b, triangle)))
		stats["rock_y_limit_violations_all_corners"] = violations
		stats["rock_corner_output_truncated"] = violations > 100
		stats["rock_reported_triangles"] = selected.size()
	return true

func _diagnose_leaves(a: Array, b: Array) -> bool:
	var i := 0
	var groups := 0
	var moved_groups := 0
	var attribute_groups := 0
	var worst_normal := 0.0
	var worst_tangent := 0.0
	while i < _corner_count(a):
		var first := _id(a, i)
		if not _ok(i + 15 <= _corner_count(a), "Diagnostic complete leaf group"): return false
		var flower: bool = a[Mesh.ARRAY_TEX_UV][first] == Vector2(-999, -999)
		var oval: bool = not flower and a[Mesh.ARRAY_COLOR][_id(a, i + 1)].a == 1.0
		var count := 18 if oval else 15
		if not _ok(i + count <= _corner_count(a), "Diagnostic leaf topology"): return false
		var translation: Vector3 = b[Mesh.ARRAY_VERTEX][_id(b, i)] - a[Mesh.ARRAY_VERTEX][first]
		var residual := 0.0
		var movement := 0.0
		var normal_delta := 0.0
		var tangent_delta := 0.0
		var normal_changes := 0
		var tangent_changes := 0
		var hand_changes := 0
		var minimum_geo_dot := 1.0
		var edge_delta := 0.0
		var witness := {}
		for j in range(i, i + count):
			var ai := _id(a, j)
			var bi := _id(b, j)
			var p: Vector3 = a[Mesh.ARRAY_VERTEX][ai]
			var q: Vector3 = b[Mesh.ARRAY_VERTEX][bi]
			var an: Vector3 = a[Mesh.ARRAY_NORMAL][ai]
			var bn: Vector3 = b[Mesh.ARRAY_NORMAL][bi]
			var at := _tan(a, ai)
			var bt := _tan(b, bi)
			movement = maxf(movement, p.distance_to(q))
			residual = maxf(residual, (q - p - translation).length())
			if an != bn: normal_changes += 1
			if at != bt: tangent_changes += 1
			if at.w != bt.w: hand_changes += 1
			var nd := an.distance_to(bn)
			if nd > normal_delta: witness = {"corner": j, "old_normal": _xyz(an), "new_normal": _xyz(bn), "old_tangent": [at.x, at.y, at.z, at.w], "new_tangent": [bt.x, bt.y, bt.z, bt.w]}
			normal_delta = maxf(normal_delta, nd)
			tangent_delta = maxf(tangent_delta, (bt - at).length())
			if (j - i) % 3 == 0:
				var p1: Vector3 = a[Mesh.ARRAY_VERTEX][_id(a, j + 1)]
				var p2: Vector3 = a[Mesh.ARRAY_VERTEX][_id(a, j + 2)]
				var q1: Vector3 = b[Mesh.ARRAY_VERTEX][_id(b, j + 1)]
				var q2: Vector3 = b[Mesh.ARRAY_VERTEX][_id(b, j + 2)]
				var gn := (p2 - p).cross(p1 - p)
				var hn := (q2 - q).cross(q1 - q)
				minimum_geo_dot = minf(minimum_geo_dot, gn.normalized().dot(hn.normalized()))
				edge_delta = maxf(edge_delta, maxf(((q1 - q) - (p1 - p)).length(), ((q2 - q) - (p2 - p)).length()))
		if movement > 0.0: moved_groups += 1
		if normal_changes + tangent_changes > 0: attribute_groups += 1
		if movement > 0.0 or normal_changes + tangent_changes > 0:
			print("LEDGE_NOTCH_DIAG_LEAF: ", JSON.stringify({"first_corner": i, "corners": count, "kind": "flower" if flower else ("oval" if oval else "blade"), "translation": _xyz(translation), "max_position_delta": movement, "max_rigid_translation_residual": residual, "max_actual_edge_delta": edge_delta, "min_old_new_geometric_normal_dot": minimum_geo_dot, "max_normal_delta": normal_delta, "max_tangent4_delta": tangent_delta, "normal_changed_corners": normal_changes, "tangent_changed_corners": tangent_changes, "handedness_changes": hand_changes, "max_normal_witness": witness, "note": "Shading normal need not equal face normal; unchanged edges plus changed shading frame require explanation, not automatic acceptance."}))
		worst_normal = maxf(worst_normal, normal_delta)
		worst_tangent = maxf(worst_tangent, tangent_delta)
		groups += 1
		i += count
	stats["leaf_diagnostic"] = {"groups": groups, "moved_groups": moved_groups, "attribute_changed_groups": attribute_groups, "max_normal_delta": worst_normal, "max_tangent4_delta": worst_tangent}
	return true
