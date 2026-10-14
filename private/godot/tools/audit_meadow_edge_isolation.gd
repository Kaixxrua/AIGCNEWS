extends SceneTree
## v92: exact patch isolation on one real world; no source edits or second world.
## Run in a debug-capable local engine; require the final PASS marker as well as exit 0.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const CURRENT_PATH := "res://scripts/meadow_edge_growth.gd"
const BASELINE_RELATIVE := "../artifacts/v92/meadow_edge_growth.v91-before.gd"
const BASELINE_SHA := "df7dc8a18bee287a9aa87de299364849db7d7d4267cc90d2a345b6d96cd26e24"
const CACHE_SIGNATURE := "a697804e3160757ebf23f638fa2b7bfb7dd2b7c5d08145b0ec8d6d17089efc7e"
const TARGET_PATCH := 9
const PATCH_COUNT := 14
const BASELINE_COUNTS := [42, 36, 52, 47, 20, 41, 44, 49, 46, 49, 55, 35, 46, 43]
const CHANNELS := [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR,
	Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]
const GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
	"brush": ["MiddleMeadowBrush"]}
const MARKER := "MEADOW_EDGE_ISOLATION_AUDIT"
var failed := false

func _require(condition: bool, message: String = "Isolation invariant failed") -> bool:
	# Assertions in a helper abort that helper, not necessarily its caller.
	# Schedule a nonzero exit and retain failure state so no caller can print PASS.
	if not condition:
		failed = true
		push_error(MARKER + ": FAIL; " + message)
		quit(1)
	return condition

func _initialize() -> void:
	if not OS.is_debug_build():
		push_error(MARKER + ": FAIL; assertions must be enabled; use the local debug-capable engine")
		quit(1)
		return
	if OS.get_cmdline_user_args().has("--rebuild-static"):
		push_error(MARKER + ": FAIL; this read-only audit must not rebuild caches")
		quit(1)
		return
	_run.call_deferred()

func _run() -> void:
	var started := Time.get_ticks_msec()
	var baseline_path := ProjectSettings.globalize_path("res://").path_join(BASELINE_RELATIVE).simplify_path()
	assert(_require(FileAccess.file_exists(baseline_path), "Frozen external v91 builder is missing: " + baseline_path))
	assert(_require(FileAccess.get_sha256(baseline_path).to_lower() == BASELINE_SHA, "Frozen v91 builder changed"))
	var current_sha := FileAccess.get_sha256(CURRENT_PATH)
	assert(_require(current_sha.length() == 64 and CACHE.signature() == CACHE_SIGNATURE,
		"Current builder must exist and all eleven old cache sources must remain frozen"))
	# Compile the exact external text in memory. Its preloads already use res://.
	# No source rewriting, helper substitution, copied world or on-disk script copy.
	var baseline_script := GDScript.new()
	baseline_script.source_code = FileAccess.get_file_as_string(baseline_path)
	var compile_error := baseline_script.reload()
	assert(_require(compile_error == OK and baseline_script.can_instantiate(), "External v91 GDScript compilation failed"))
	var current_script := load(CURRENT_PATH) as GDScript
	assert(_require(current_script != null and current_script.can_instantiate()))
	var frozen: Dictionary = _freeze_world()
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	assert(_require(scene != null))
	# Remove only the unready automatic fringe node, before entering the tree.
	# Then each builder gets exactly one normal _ready on the same ready parent.
	var automatic := scene.get_node_or_null("MeadowEdgeGrowth")
	assert(_require(automatic != null and not automatic.is_inside_tree()))
	assert(_require(automatic.get_script() == current_script, "Scene must reference the current fringe builder"))
	scene.remove_child(automatic)
	automatic.free()
	root.add_child(scene)
	assert(_require(scene.is_node_ready() and scene.global_transform == Transform3D.IDENTITY))
	_verify_world(scene, frozen, "parent construction")
	var before := _build_and_capture(scene, baseline_script, "V91Baseline")
	_verify_world(scene, frozen, "v91 builder")
	var after := _build_and_capture(scene, current_script, "V92Current")
	_verify_world(scene, frozen, "v92 builder")
	assert(_require(int(before["root_count"]) == 605 and int(before["triangles"]) == 16464,
		"Frozen v91 must reproduce its independently observed geometry in this real world"))
	var records: Array[Dictionary] = []
	var unchanged_patches := 0
	for patch in range(PATCH_COUNT):
		var old_roots: Array = before["patches"][patch]
		var new_roots: Array = after["patches"][patch]
		assert(_require(old_roots.size() == BASELINE_COUNTS[patch], "Frozen v91 per-patch root count changed"))
		var attributes_equal := var_to_bytes(old_roots) == var_to_bytes(new_roots)
		var positions_equal := _positions_equal(old_roots, new_roots)
		var geometry_equal := _triangle_keys(old_roots) == _triangle_keys(new_roots) if patch == TARGET_PATCH else positions_equal
		var record := {"patch": patch, "before_roots": old_roots.size(), "after_roots": new_roots.size(),
			"exact_root_range_attributes": attributes_equal, "actual_positions_equal": positions_equal,
			"triangle_geometry_equal": geometry_equal,
			"before_height": _height_stats(old_roots), "after_height": _height_stats(new_roots)}
		records.append(record)
		print("MEADOW_EDGE_ISOLATION_PATCH: " + JSON.stringify(record))
		if patch != TARGET_PATCH:
			assert(_require(attributes_equal,
				"Unexpected change outside patch9: patch %d; root/reach/local range or actual vertex/normal/color/UV/UV2 differs" % patch))
			unchanged_patches += 1
		else:
			assert(_require(not geometry_equal, "Patch9 must change actual triangle geometry, not just ordering, metadata, colors or normals"))
	assert(_require(unchanged_patches == 13))
	assert(_require(CACHE.signature() == CACHE_SIGNATURE and FileAccess.get_sha256(CURRENT_PATH) == current_sha,
		"Sources changed while audit was running; retry on a stable source snapshot"))
	assert(_require(FileAccess.get_sha256(baseline_path).to_lower() == BASELINE_SHA))
	if failed:
		return
	print("MEADOW_EDGE_ISOLATION: " + JSON.stringify({"baseline_sha256": BASELINE_SHA,
		"current_sha256": current_sha, "same_world": true, "old_cache_groups": 5, "old_meshes": 9,
		"unchanged_patches": unchanged_patches, "changed_patch": TARGET_PATCH,
		"before_roots": before["root_count"], "after_roots": after["root_count"],
		"before_triangles": before["triangles"], "after_triangles": after["triangles"],
		"baseline_build_ms": before["build_ms"], "current_build_ms": after["build_ms"],
		"audit_elapsed_ms": Time.get_ticks_msec() - started, "patches": records}))
	scene.free()
	print(MARKER + ": PASS; exact 13-patch root/local-range and five-channel isolation; patch9 actual geometry changed; five cache files and nine old mesh/collision snapshots preserved; run original v91 geometry audit separately; no GPU/visual/performance PASS")
	quit(0)

func _build_and_capture(scene: Node3D, script: GDScript, label: String) -> Dictionary:
	var builder := script.new() as Node3D
	assert(_require(builder != null))
	builder.name = label
	scene.add_child(builder)
	assert(_require(builder.get("ready_complete") == true, label + " must finish synchronously on the ready real parent"))
	assert(_require(builder.transform == Transform3D.IDENTITY and builder.get_child_count() == 1))
	var fringe := builder.get_node_or_null("CrownToTurfFringe") as MeshInstance3D
	assert(_require(fringe != null and fringe.transform == Transform3D.IDENTITY and fringe.get_child_count() == 0))
	var result := _capture(fringe)
	result["build_ms"] = fringe.get_meta("build_ms")
	# Packed-array slices below survive node deletion; baseline cannot collide with
	# the current builder, inflate render counters, or leave a duplicate live fringe.
	scene.remove_child(builder)
	builder.free()
	return result

func _capture(fringe: MeshInstance3D) -> Dictionary:
	var mesh := fringe.mesh as ArrayMesh
	assert(_require(mesh != null and mesh.get_surface_count() == 1))
	assert(_require(mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES))
	var arrays := mesh.surface_get_arrays(0)
	assert(_require(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty(), "Ranges require unindexed emitted corners"))
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var colors: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	assert(_require(vertices.size() > 0 and vertices.size() % 3 == 0 and vertices.size() < 45000 * 3))
	for channel: int in CHANNELS:
		assert(_require(arrays[channel] != null and arrays[channel].size() == vertices.size()))
	var roots: PackedVector3Array = fringe.get_meta("roots")
	var patches: PackedInt32Array = fringe.get_meta("patches")
	var ranges: PackedVector2Array = fringe.get_meta("ranges")
	var reaches: PackedFloat32Array = fringe.get_meta("reaches")
	var declared_counts: PackedInt32Array = fringe.get_meta("patch_counts")
	assert(_require(roots.size() > 100 and patches.size() == roots.size() and ranges.size() == roots.size()))
	assert(_require(reaches.size() == roots.size() and declared_counts.size() == PATCH_COUNT))
	var grouped: Array = []
	var local_corners := PackedInt32Array()
	local_corners.resize(PATCH_COUNT)
	for patch in range(PATCH_COUNT):
		grouped.append([])
	var next := 0
	for r in range(roots.size()):
		var patch := patches[r]
		assert(_require(patch >= 0 and patch < PATCH_COUNT))
		var span := ranges[r]
		assert(_require(span.is_finite() and span.x == float(next) and (span.y == 72.0 or span.y == 90.0),
			"Keep the original v91 four/five open-leaf range contract"))
		var end := next + int(span.y)
		assert(_require(end <= vertices.size() and roots[r].is_finite() and is_finite(reaches[r])))
		# Bind range metadata to actual zero-wind bases of every emitted leaf.
		for first in range(next, end, 18):
			var bases := 0
			for i in range(first, first + 18):
				assert(_require(vertices[i].is_finite()))
				if colors[i].a == 0.0:
					assert(_require(vertices[i] == roots[r], "Root metadata disagrees with actual leaf attachment"))
					bases += 1
			assert(_require(bases == 2, "Every existing six-triangle leaf must expose both actual root corners"))
		var channels: Array = []
		for channel: int in CHANNELS:
			channels.append(arrays[channel].slice(next, end))
		# Absolute offsets may shift when patch9 changes count. Preserve each
		# patch's own ordered root, local range and ALL actual channel data exactly.
		grouped[patch].append({"root": roots[r], "reach": reaches[r],
			"local_range": Vector2i(local_corners[patch], int(span.y)), "channels": channels})
		local_corners[patch] += int(span.y)
		next = end
	assert(_require(next == vertices.size(), "Ranges must partition every emitted corner without overlap or omissions"))
	for patch in range(PATCH_COUNT):
		assert(_require(grouped[patch].size() > 0 and grouped[patch].size() == declared_counts[patch]))
	return {"patches": grouped, "root_count": roots.size(), "triangles": vertices.size() / 3}

func _positions_equal(before: Array, after: Array) -> bool:
	if before.size() != after.size():
		return false
	for r in range(before.size()):
		if var_to_bytes(before[r]["channels"][0]) != var_to_bytes(after[r]["channels"][0]):
			return false
	return true

func _triangle_keys(roots: Array) -> PackedStringArray:
	# Patch9 cannot pass by merely reordering identical roots/triangles/corners.
	# Exact serialized positions retain precision; sorting retains multiplicity.
	var triangles := PackedStringArray()
	for record: Dictionary in roots:
		var vertices: PackedVector3Array = record["channels"][0]
		for first in range(0, vertices.size(), 3):
			var corners := PackedStringArray()
			for offset in range(3):
				corners.append(var_to_bytes(vertices[first + offset]).hex_encode())
			corners.sort()
			triangles.append("/".join(corners))
	triangles.sort()
	return triangles

func _height_stats(roots: Array) -> Dictionary:
	var low := INF
	var high := -INF
	var root_min := INF
	var root_max := -INF
	var crown_sum := 0.0
	var corners := 0
	for record: Dictionary in roots:
		var root_position: Vector3 = record["root"]
		root_min = minf(root_min, root_position.y)
		root_max = maxf(root_max, root_position.y)
		var crown := -INF
		var vertices: PackedVector3Array = record["channels"][0]
		for p: Vector3 in vertices:
			var height := p.y - root_position.y
			low = minf(low, height)
			high = maxf(high, height)
			crown = maxf(crown, height)
		crown_sum += crown
		corners += vertices.size()
	return {"roots": roots.size(), "triangles": corners / 3,
		"vertex_height_above_root_min_m": low, "vertex_height_above_root_max_m": high,
		"mean_root_crown_height_m": crown_sum / float(roots.size()),
		"root_world_y_min_m": root_min, "root_world_y_max_m": root_max}

func _freeze_world() -> Dictionary:
	var nodes := {}
	var files := {}
	for group: String in GROUPS:
		var path := CACHE.DIRECTORY + group + ".scn"
		assert(_require(FileAccess.file_exists(path)))
		files[path] = FileAccess.get_sha256(path)
		var packed := load(path) as PackedScene
		assert(_require(packed != null))
		var container := packed.instantiate() as Node3D
		assert(_require(container != null and container.get_child_count() == GROUPS[group].size()))
		assert(_require(container.get_meta("cache_version", "") == CACHE.VERSION))
		assert(_require(container.get_meta("source_signature", "") == CACHE_SIGNATURE))
		for label: String in GROUPS[group]:
			nodes[label] = _snapshot_digest(container.get_node(NodePath(label)))
		container.free()
	assert(_require(nodes.size() == 9 and files.size() == 5))
	return {"nodes": nodes, "files": files}

func _verify_world(scene: Node3D, frozen: Dictionary, stage: String) -> void:
	for label: String in frozen["nodes"]:
		assert(_require(_snapshot_digest(scene.get_node(NodePath(label))) == frozen["nodes"][label],
			stage + " changed an old mesh/transform/collision subtree: " + label))
	for path: String in frozen["files"]:
		assert(_require(FileAccess.get_sha256(path) == frozen["files"][path], stage + " changed a cache file: " + path))

func _snapshot_digest(node: Node) -> String:
	var context := HashingContext.new()
	assert(_require(context.start(HashingContext.HASH_SHA256) == OK))
	assert(_require(context.update(var_to_bytes(_snapshot(node))) == OK))
	return context.finish().hex_encode()

func _snapshot(node: Node) -> Dictionary:
	var result := {"class": node.get_class(), "name": str(node.name), "children": []}
	if node is Node3D:
		result["transform"] = node.transform
	if node is MeshInstance3D:
		var mesh := node.mesh as ArrayMesh
		assert(_require(mesh != null))
		result["layers"] = node.layers
		result["shadow"] = node.cast_shadow
		var surfaces: Array = []
		for surface in range(mesh.get_surface_count()):
			surfaces.append([mesh.surface_get_primitive_type(surface), mesh.surface_get_arrays(surface)])
		result["surfaces"] = surfaces
	if node is CollisionObject3D:
		result["collision"] = [node.collision_layer, node.collision_mask]
	if node is CollisionShape3D:
		var shape := node.shape as ConcavePolygonShape3D
		assert(_require(shape != null, "Frozen collision contract requires concave triangle shapes"))
		result["shape"] = [node.disabled, shape.get_faces(), shape.backface_collision]
	for child: Node in node.get_children():
		result["children"].append(_snapshot(child))
	return result
