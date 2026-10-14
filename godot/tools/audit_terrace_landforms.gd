extends SceneTree
## v114: one real main; only additive terrace geometry. No GPU/bake/cache writes.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const C := Vector2(-36.388867, -20.323368)
const T := Vector2(-0.885018018, 0.465556773)
const N := Vector2(0.465556773, 0.885018018)
const LIMIT := Rect2(-43, -28, 20, 13)
const EPS := .0002 # Stored float32 positions / packed normals, not a clearance waiver.
const ROCK_SHA := "fb26bc08f6d39ce63d80346bef6d1e14b11740954127daeb1e294b6fdba4120e"
var scene: Node3D
var holder: Node3D
var rocks: MeshInstance3D
var leaves: MeshInstance3D
var old_queries: Array[TriangleMesh] = []
var piece_queries: Array[TriangleMesh] = []
var protected := {}
var hashes := {}
var checks := 0
var failures := 0
var results := {}

func _initialize() -> void:
	root.disable_3d = true
	root.size = Vector2i(2304, 1440)
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failures += 1
		push_error("TERRACE_LANDFORMS: " + label)
	return value

func _preflight() -> bool:
	if not _ok(DisplayServer.get_name() == "headless" and OS.get_cmdline_user_args().is_empty(), "Standalone headless only, no bake flags"): return false
	# Inherit only byte-identical v113 inputs, never replay its grass/GPU suite.
	for pair: Array in [["far-field-scene.log", "FAR_FIELD_SCENE_AUDIT: PASS; "], ["far-field-gpu.log", "FAR_FIELD_FIXTURE_AUDIT: PASS; "]]:
		var record := {}
		for line: String in FileAccess.get_file_as_string("res://../artifacts/v113/" + pair[0]).split("\n"):
			if line.begins_with(pair[1]):
				var value: Variant = JSON.parse_string(line.substr(str(pair[1]).length()))
				if value is Dictionary: record = value
		if not _ok(record.get("failures", -1) == 0 and record.get("source_hashes") is Dictionary, "Historical v113 input manifest " + pair[0]): return false
		for path: String in record.source_hashes:
			if path != "res://scripts/meadow_ground_atmosphere.gd": protected[path] = record.source_hashes[path]
	protected["res://shaders/meadow_limestone.gdshader"] = ROCK_SHA
	for path: String in protected:
		_ok(FileAccess.get_sha256(path) == protected[path], "Frozen v113 cache/AO/material/world input " + path)
	for path: String in ["res://scripts/meadow_terrace_landforms.gd", "res://scripts/meadow_ground_atmosphere.gd"]:
		hashes[path] = FileAccess.get_sha256(path)
		_ok(not str(hashes[path]).is_empty(), "New source/interface present " + path)
	if failures != 0: return false
	var signature: String = CACHE.signature()
	for group: String in CACHE.GROUPS:
		var packed := load(CACHE.DIRECTORY + group + ".scn") as PackedScene
		if not _ok(packed != null, "Existing old cache " + group): return false
		var state := packed.get_state()
		var values := {}
		for i in range(state.get_node_property_count(0)):
			values[str(state.get_node_property_name(0, i))] = state.get_node_property_value(0, i)
		_ok(values.get("metadata/source_signature") == signature and values.get("metadata/cache_version") == CACHE.VERSION, "Reject stale cache before main can rebuild " + group)
	return failures == 0

func _old_hit(p: Vector3) -> Dictionary:
	var best := {}
	for i in range(old_queries.size()):
		var hit := old_queries[i].intersect_ray(Vector3(p.x, 60, p.z), Vector3.DOWN)
		if not hit.is_empty() and (best.is_empty() or Vector3(hit.position).y > Vector3(best.position).y):
			best = hit
			best["source"] = i
	return best

func _bounds(points: PackedVector3Array, first: int, count: int) -> AABB:
	var box := AABB(points[first], Vector3.ZERO)
	for i in range(first + 1, first + count): box = box.expand(points[i])
	return box

func _bounds_match(value: Variant, actual: AABB) -> bool:
	return value is AABB and value.position.distance_to(actual.position) <= EPS and value.size.distance_to(actual.size) <= EPS

func _arrays(card: MeshInstance3D) -> Array:
	if not _ok(card.mesh is ArrayMesh and card.mesh.get_surface_count() == 1 and card.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES, "Single actual triangle mesh " + str(card.name)): return []
	var arrays := card.mesh.surface_get_arrays(0)
	if not _ok(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty(), "Declared unindexed corner protocol"): return []
	if not _ok(arrays[Mesh.ARRAY_VERTEX].size() > 0 and arrays[Mesh.ARRAY_VERTEX].size() % 3 == 0 and arrays[Mesh.ARRAY_NORMAL].size() == arrays[Mesh.ARRAY_VERTEX].size(), "Complete nonempty mesh channels"): return []
	return arrays

func _triangles(arrays: Array, is_rock: bool) -> void:
	var v: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var wind := 0.0 if is_rock else .06
	for first in range(0, v.size(), 3):
		var low := INF
		var high := -INF
		for i in range(first, first + 3):
			var p := v[i]
			var xz := Vector2(p.x, p.z)
			_ok(p.is_finite() and normals[i].is_finite() and absf(normals[i].length() - 1) <= .002, "Finite positions/unit normals")
			_ok(LIMIT.grow(-wind).has_point(xz) and p.y >= -1 and p.y <= 6, "Actual full geometry within declared bounds")
			_ok(scene.distance_to_road(xz) > scene.road_half_width(p.z) + wind and xz.distance_to(scene.BOSS_CENTER) > scene.BOSS_ARENA_RADIUS + wind and absf(p.x - scene.river_center(p.z)) > scene.river_water_half_width(p.z) + .5 + wind, "Actual corners exclude road/water/Boss")
			var along := (xz - C).dot(T)
			low = minf(low, along)
			high = maxf(high, along)
		# A linear half-space bounds EVERY point of a triangle, not just its centre.
		_ok(low > .85 + wind or high < -.85 - wind, "Entire projected triangle stays on one side of open notch strip")
		var cross := (v[first + 2] - v[first]).cross(v[first + 1] - v[first])
		if not _ok(cross.length_squared() > 1e-10, "Nondegenerate triangle"): continue
		for i in range(first, first + 3):
			_ok(cross.normalized().distance_to(normals[i]) <= .002 if is_rock else cross.dot(normals[i]) > 0, "Clockwise winding / rock geometric normals; leaf artistic normals permitted")

func _geometry() -> bool:
	var candidates := scene.find_children("TerraceLandformsCandidate*", "Node3D", true, false)
	if not _ok(candidates.size() == 1, "One integrated holder; no audit-side fallback build"): return false
	holder = candidates[0] as Node3D
	rocks = holder.get_node_or_null("ErodedTerraceMasses") as MeshInstance3D
	leaves = holder.get_node_or_null("RootedCleftLeaves") as MeshInstance3D
	if not _ok(rocks != null and leaves != null and holder.get_child_count() == 2 and holder.get_parent() == scene and holder.get_meta("schema", "") == "terrace-landforms-114-1", "One rock mesh plus one leaf mesh, declared schema"): return false
	var old_rock := scene.get_node_or_null("SolidLimestoneGeology") as MeshInstance3D
	var ground := scene.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	var understory := scene.get_node_or_null("LivingMeadowUnderstory") as MeshInstance3D
	var probe := scene.get_node_or_null("RiverSurroundingsReflection") as ReflectionProbe
	if not _ok(old_rock != null and ground != null and understory != null and probe != null, "Actual existing support/material/reflection nodes"): return false
	for card: MeshInstance3D in [ground, old_rock, rocks, leaves]:
		_ok(card.global_transform == scene.global_transform, "Actual support/candidate coordinate identity")
	for card: MeshInstance3D in [rocks, leaves]:
		_ok(card.get_child_count() == 0 and card.layers == 8 and (probe.cull_mask & card.layers) == 0 and card.material_overlay == null, "No child collider/overlay; layer8 excluded by actual reflection mask")
	var material := rocks.material_override as ShaderMaterial
	var original := old_rock.material_override as ShaderMaterial
	if not _ok(material != null and original != null and material != original and material.shader == original.shader and material.next_pass == null, "Independent rock material, unchanged limestone shader/single pass"): return false
	_ok(material.get_shader_parameter("rock_ao_vertex_count") == 0 and original.get_shader_parameter("rock_ao_vertex_count") == 317556, "New AO prefix zero, original AO prefix retained")
	_ok(leaves.material_override == understory.material_override and leaves.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF, "Existing leaf material reused, no leaf shadow pass")
	for card: MeshInstance3D in [ground, old_rock]: old_queries.append(card.mesh.generate_triangle_mesh())
	if not _ok(old_queries[0] != null and old_queries[1] != null, "Old actual triangle surfaces available"): return false
	var a := _arrays(rocks)
	var b := _arrays(leaves)
	if a.is_empty() or b.is_empty(): return false
	var v: PackedVector3Array = a[Mesh.ARRAY_VERTEX]
	var lv: PackedVector3Array = b[Mesh.ARRAY_VERTEX]
	_ok((v.size() + lv.size()) / 3 <= 5000 and holder.get_meta("triangle_count", 0) == (v.size() + lv.size()) / 3, "Measured nonempty combined <=5000 triangles")
	_triangles(a, true)
	_triangles(b, false)
	for spec: Array in [[rocks, "piece_ranges", TYPE_PACKED_VECTOR2_ARRAY], [rocks, "piece_bounds", TYPE_ARRAY], [rocks, "base_ranges", TYPE_PACKED_VECTOR2_ARRAY], [rocks, "base_vertices", TYPE_PACKED_VECTOR3_ARRAY], [rocks, "base_support_hits", TYPE_PACKED_VECTOR3_ARRAY], [rocks, "base_support_sources", TYPE_PACKED_INT32_ARRAY], [leaves, "roots", TYPE_PACKED_VECTOR3_ARRAY], [leaves, "root_ranges", TYPE_PACKED_VECTOR2_ARRAY], [leaves, "root_pieces", TYPE_PACKED_INT32_ARRAY], [holder, "gap_xz_polyline", TYPE_PACKED_VECTOR2_ARRAY]]:
		if not _ok(typeof(spec[0].get_meta(spec[1], null)) == spec[2], "Metadata protocol " + str(spec[1])): return false
	var ranges: PackedVector2Array = rocks.get_meta("piece_ranges")
	var bases: PackedVector2Array = rocks.get_meta("base_ranges")
	var feet: PackedVector3Array = rocks.get_meta("base_vertices")
	var hits: PackedVector3Array = rocks.get_meta("base_support_hits")
	var sources: PackedInt32Array = rocks.get_meta("base_support_sources")
	var boxes: Array = rocks.get_meta("piece_bounds")
	if not _ok(ranges.size() == 5 and bases.size() == 5 and boxes.size() == 5 and feet.size() == hits.size() and feet.size() == sources.size(), "Five pieces and complete support metadata"): return false
	var cursor := 0
	var foot_cursor := 0
	var max_base_error := 0.0
	for piece in range(5):
		var r := ranges[piece]
		var base := bases[piece]
		if not _ok(r.is_finite() and base.is_finite() and r.x == cursor and base.x == foot_cursor and base.y >= 3 and base.y == int(base.y) and r.y == base.y * 12 and cursor + int(r.y) <= v.size() and foot_cursor + int(base.y) <= feet.size(), "Ranges map actual four triangles per perimeter segment"): return false
		_ok(_bounds_match(boxes[piece], _bounds(v, cursor, int(r.y))), "Actual per-piece bounds agree, not metadata-only")
		var query := TriangleMesh.new()
		query.create_from_faces(v.slice(cursor, cursor + int(r.y)))
		piece_queries.append(query)
		for j in range(int(base.y)):
			var at := foot_cursor + j
			var foot := v[cursor + j * 12] # First corner is invariant under b/c winding swaps.
			var next := v[cursor + ((j + 1) % int(base.y)) * 12]
			_ok(foot.distance_to(feet[at]) <= EPS and Vector2(foot.x - next.x, foot.z - next.z).length() <= .3201, "Actual perimeter feet bound to metadata, <=.32m sampling")
			var hit := _old_hit(foot)
			if not _ok(not hit.is_empty(), "Every actual base sample hits old terrain/rock"): return false
			var measured: Vector3 = hit.position
			max_base_error = maxf(max_base_error, absf(measured.y - foot.y - .14))
			_ok(measured.distance_to(hits[at]) <= EPS and sources[at] == hit.source and absf(measured.y - foot.y - .14) <= EPS, "Base embedded .14m in highest actual old support, correct source")
		cursor += int(r.y)
		foot_cursor += int(base.y)
	_ok(cursor == v.size() and foot_cursor == feet.size(), "No omitted rock corners or base records")
	var roots: PackedVector3Array = leaves.get_meta("roots")
	var lr: PackedVector2Array = leaves.get_meta("root_ranges")
	var pieces: PackedInt32Array = leaves.get_meta("root_pieces")
	var colors: PackedColorArray = b[Mesh.ARRAY_COLOR]
	if not _ok(not roots.is_empty() and roots.size() == lr.size() and roots.size() == pieces.size() and colors.size() == lv.size(), "Actual leaf root/channel protocol"): return false
	var rock_query := rocks.mesh.generate_triangle_mesh()
	var max_leaf_error := 0.0
	cursor = 0
	for i in range(roots.size()):
		if not _ok(roots[i].is_finite() and lr[i] == Vector2(cursor, 72) and cursor + 72 <= lv.size() and pieces[i] >= 0 and pieces[i] < 5, "Four leaf fans bound to valid piece/range"): return false
		var origin := Vector3(roots[i].x, 60, roots[i].z)
		var hit := rock_query.intersect_ray(origin, Vector3.DOWN)
		var piece_hit := piece_queries[pieces[i]].intersect_ray(origin, Vector3.DOWN)
		if not _ok(not hit.is_empty() and not piece_hit.is_empty(), "Leaf roots ray-hit NEW rock and declared piece"): return false
		var error := roots[i].distance_to(Vector3(hit.position) + Vector3.UP * .006)
		max_leaf_error = maxf(max_leaf_error, error)
		_ok(error <= EPS and Vector3(hit.position).distance_to(piece_hit.position) <= EPS and Vector3(hit.normal).y >= .55, "Real top attachment +.006m, not another/buried piece")
		var old := _old_hit(roots[i])
		_ok(old.is_empty() or Vector3(old.position).y <= Vector3(hit.position).y + EPS, "Leaf support top not hidden under old surface")
		for leaf in range(4):
			_ok(lv[cursor + leaf * 18].distance_to(roots[i]) <= EPS and colors[cursor + leaf * 18].a == 0, "Actual leaf fan base equals root; zero base wind")
		cursor += 72
	_ok(cursor == lv.size(), "All leaf corners covered")
	var gap: PackedVector2Array = holder.get_meta("gap_xz_polyline")
	var expected := [Vector2(-.10, -1.5), Vector2(.25, -.3), Vector2(-.20, 1.1), Vector2(-.35, 2.8)]
	if not _ok(gap.size() == 4 and holder.get_meta("gap_half_width", 0) == .4, "Declared bent notch corridor"): return false
	for i in range(4):
		_ok(gap[i].distance_to(C + T * expected[i].x + N * expected[i].y) <= EPS and absf((gap[i] - C).dot(T)) + .4 < .85, "Whole .4m-halfwidth corridor lies inside triangle-free strip")
	var actual_bounds := _bounds(v, 0, v.size()).merge(_bounds(lv, 0, lv.size()).grow(.06))
	_ok(_bounds_match(holder.get_meta("bounds"), actual_bounds), "Holder actual combined bounds including leaf wind")
	results = {"pieces": 5, "rock_triangles": v.size() / 3, "leaf_triangles": lv.size() / 3, "base_samples": feet.size(), "leaf_roots": roots.size(), "base_embed_error_max_m": max_base_error, "leaf_attachment_error_max_m": max_leaf_error, "actual_bounds": var_to_str(actual_bounds), "notch": "ALL projected triangles outside +/-0.85m strip, leaves include .06m wind; full bent .4m halfwidth corridor covered; NEW geometry exclusion only, not a walkable excavation", "rock_cast_shadow": rocks.cast_shadow}
	return failures == 0

func _run() -> void:
	quit(1) # Synchronous runtime exception cannot become a false PASS.
	var started := Time.get_ticks_msec()
	var prepared: Variant = _preflight()
	var complete: Variant = false
	if prepared == true:
		scene = (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
		root.add_child(scene)
		scene.process_mode = Node.PROCESS_MODE_DISABLED
		if _ok(scene.is_node_ready(), "Actual main ready completed"):
			var audit_start := Time.get_ticks_msec()
			complete = _geometry()
			results["geometry_audit_ms"] = Time.get_ticks_msec() - audit_start
	for path: String in protected: _ok(FileAccess.get_sha256(path) == protected[path], "Frozen input unchanged during audit " + path)
	for path: String in hashes: _ok(FileAccess.get_sha256(path) == hashes[path], "Candidate source stable during audit " + path)
	if is_instance_valid(scene): scene.free()
	var passed: bool = prepared == true and complete == true and failures == 0
	print("TERRACE_LANDFORMS_AUDIT: ", "PASS" if passed else "FAIL", "; ", JSON.stringify({"checks": checks, "failures": failures, "measurements": results, "elapsed_ms": Time.get_ticks_msec() - started, "candidate_hashes": hashes, "limits": "No v113 grass-suite/GPU/material rerun; sampled base burial, not solid Boolean union; no collision additions or visual/score/performance acceptance. Any engine ERROR vetoes acceptance."}))
	quit(0 if passed else 1)
