extends SceneTree
## v93 independent additive branchlet audit. One real world, two sequential builders.
## Existing v91/v92 audits remain untouched; main owns engine execution.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const CURRENT_PATH := "res://scripts/meadow_edge_growth.gd"
const CURRENT_SHA := "33f445246f5d23c338a22407207d0dc498469fd19ee8067f402adabf3090337e"
const BASELINE_RELATIVE := "../artifacts/v92/meadow_edge_growth.v91-before.gd"
const BASELINE_SHA := "df7dc8a18bee287a9aa87de299364849db7d7d4267cc90d2a345b6d96cd26e24"
const CACHE_SIGNATURE := "a697804e3160757ebf23f638fa2b7bfb7dd2b7c5d08145b0ec8d6d17089efc7e"
const SHADER_SHA := "dd218655817268a12de2be516df8d9280edb309502fb3228f0604450b5310335"
const GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
	"brush": ["MiddleMeadowBrush"]}
const MARKER := "MEADOW_BRANCHLET_TRANSITION_AUDIT"
const WIND_BUFFER := 0.06
const ROOT_RADIUS := 0.75
const EPS := 0.0001
# Explicit main-agent accepted protocol, not inferred from the test product.
const BLADES_PER_GROUP := 2
var failed := false

func _initialize() -> void:
	if not OS.is_debug_build() or OS.get_cmdline_user_args().has("--rebuild-static"):
		push_error(MARKER + ": FAIL; use a debug-capable local engine without --rebuild-static")
		quit(1)
		return
	_run.call_deferred()

func _run() -> void:
	var started := Time.get_ticks_msec()
	var baseline_path := ProjectSettings.globalize_path("res://").path_join(BASELINE_RELATIVE).simplify_path()
	assert(_require(FileAccess.file_exists(baseline_path) and FileAccess.get_sha256(baseline_path).to_lower() == BASELINE_SHA,
		"Require the exact external v91 source; never rewrite/copy it into res://"))
	var current_sha := FileAccess.get_sha256(CURRENT_PATH)
	assert(_require(current_sha.to_lower() == CURRENT_SHA and CACHE.signature() == CACHE_SIGNATURE))
	var baseline_script := GDScript.new()
	baseline_script.source_code = FileAccess.get_file_as_string(baseline_path)
	var compile_error := baseline_script.reload()
	assert(_require(compile_error == OK and baseline_script.can_instantiate()))
	var current_script := load(CURRENT_PATH) as GDScript
	assert(_require(current_script != null and current_script.can_instantiate()))
	var frozen := _freeze_world()
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	assert(_require(scene != null))
	var automatic := scene.get_node_or_null("MeadowEdgeGrowth")
	assert(_require(automatic != null and not automatic.is_inside_tree() and automatic.get_script() == current_script))
	scene.remove_child(automatic)
	automatic.free()
	root.add_child(scene)
	assert(_require(scene.is_node_ready() and scene.global_transform == Transform3D.IDENTITY))
	_verify_world(scene, frozen, "parent construction")
	var baseline := _spawn(scene, baseline_script, "V91Baseline", 1)
	var old_low := baseline.get_node("CrownToTurfFringe") as MeshInstance3D
	var old_data := _low_snapshot(old_low)
	var baseline_ms: Variant = old_low.get_meta("build_ms")
	scene.remove_child(baseline)
	baseline.free()
	_verify_world(scene, frozen, "baseline builder")
	var current := _spawn(scene, current_script, "V93Current", 2)
	var low := current.get_node_or_null("CrownToTurfFringe") as MeshInstance3D
	var branchlets := current.get_node_or_null("CrownTransitionBranchlets") as MeshInstance3D
	assert(_require(low != null and branchlets != null and low != branchlets))
	assert(_require(old_data == _low_snapshot(low),
		"All 605 v91 low roots/ranges/reaches/patches and ALL mesh channels must remain byte-exact"))
	var guides: PackedVector4Array = scene.get_node("MiddleMeadowBrush").get_meta("growth_guides")
	assert(_require(guides.size() == 14 and guides == PackedVector4Array(scene.MIDDLE_BRUSH.GUIDES)))
	_verify_low_geometry(scene, low, guides)
	var result := _verify_branchlets(scene, branchlets, guides[9])
	_verify_world(scene, frozen, "current builder and audit")
	assert(_require(CACHE.signature() == CACHE_SIGNATURE and FileAccess.get_sha256(CURRENT_PATH) == current_sha,
		"Source changed during audit; rerun on a stable snapshot"))
	assert(_require(FileAccess.get_sha256(baseline_path).to_lower() == BASELINE_SHA))
	if failed:
		return
	result.merge({"baseline_sha256": BASELINE_SHA, "current_sha256": current_sha,
		"same_world": true, "all_605_low_exact": true, "old_cache_groups": 5, "old_meshes": 9,
		"baseline_build_ms": baseline_ms, "current_low_build_ms": low.get_meta("build_ms"),
		"additional_branchlet_build_ms": branchlets.get_meta("build_ms"),
		"audit_elapsed_ms": Time.get_ticks_msec() - started})
	print("MEADOW_BRANCHLET_TRANSITION: " + JSON.stringify(result))
	scene.free()
	print(MARKER + ": PASS; v91 605 low roots and all channels exact; five caches/nine old world snapshots preserved; two actual twig segments, attached open fans, ray-supported roots and all-vertex wind reserves; geometry/source only, not visual/GPU/performance acceptance")
	quit(0)

func _spawn(scene: Node3D, script: GDScript, label: String, children: int) -> Node3D:
	var builder := script.new() as Node3D
	assert(_require(builder != null))
	builder.name = label
	scene.add_child(builder)
	assert(_require(builder.get("ready_complete") == true and builder.transform == Transform3D.IDENTITY,
		"Build must finish synchronously on the same ready real parent"))
	assert(_require(builder.get_child_count() == children, "Only the agreed low/fringe mesh children are allowed"))
	return builder

func _low_snapshot(low: MeshInstance3D) -> PackedByteArray:
	assert(_require(low != null and low.get_child_count() == 0 and low.transform == Transform3D.IDENTITY))
	var mesh := low.mesh as ArrayMesh
	assert(_require(mesh != null and mesh.get_surface_count() == 1))
	assert(_require(mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES))
	var arrays := mesh.surface_get_arrays(0)
	assert(_require(arrays[Mesh.ARRAY_VERTEX].size() == 16464 * 3))
	assert(_require(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty()))
	var roots: PackedVector3Array = low.get_meta("roots")
	assert(_require(roots.size() == 605))
	var snapshot := {"mesh": _snapshot(low), "metadata": {}}
	for key: String in ["roots", "patches", "ranges", "reaches", "patch_counts"]:
		assert(_require(low.has_meta(key)))
		snapshot["metadata"][key] = low.get_meta(key)
	_verify_material(low)
	return var_to_bytes(snapshot)

func _verify_branchlets(scene: Node3D, fringe: MeshInstance3D, guide: Vector4) -> Dictionary:
	assert(_require(fringe.transform == Transform3D.IDENTITY and fringe.get_child_count() == 0))
	assert(_require(fringe.layers == 8 and fringe.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED))
	assert(_require(fringe.get_meta("protocol_version", "") == "branchlets-93-1"))
	_verify_material(fringe)
	var mesh := fringe.mesh as ArrayMesh
	assert(_require(mesh != null and mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES))
	var arrays := mesh.surface_get_arrays(0)
	assert(_require(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty()))
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var colors: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var fields: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	assert(_require(vertices.size() > 0 and vertices.size() % 3 == 0 and vertices.size() + 16464 * 3 < 45000 * 3))
	for channel: int in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
		assert(_require(arrays[channel] != null and arrays[channel].size() == vertices.size()))
	var roots: PackedVector3Array = fringe.get_meta("roots")
	var joints: PackedVector3Array = fringe.get_meta("joints")
	var tips: PackedVector3Array = fringe.get_meta("tips")
	var ranges: PackedVector2Array = fringe.get_meta("ranges")
	var patches: PackedInt32Array = fringe.get_meta("patches")
	var reaches: PackedFloat32Array = fringe.get_meta("reaches")
	var groups: PackedInt32Array = fringe.get_meta("group_counts")
	var leaf_ranges: PackedVector2Array = fringe.get_meta("leaf_ranges")
	var leaf_bases: PackedVector3Array = fringe.get_meta("leaf_attachments")
	var leaf_owners: PackedInt32Array = fringe.get_meta("leaf_root_indices")
	assert(_require(roots.size() >= 1 and roots.size() <= 42, "Final agreed nonempty/cap42 guard; 30-50 was only a design estimate, not a user requirement"))
	for values: Variant in [joints, tips, ranges, patches, reaches, groups]:
		assert(_require(values.size() == roots.size()))
	assert(_require(leaf_ranges.size() == leaf_bases.size() and leaf_ranges.size() == leaf_owners.size()))
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var rocks: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var river_slope := 0.0
	for i in range(scene.RIVER_BENDS.size() - 1):
		var a: Vector2 = scene.RIVER_BENDS[i]
		var b: Vector2 = scene.RIVER_BENDS[i + 1]
		river_slope = maxf(river_slope, 1.5 * absf(b.y - a.y) / absf(b.x - a.x))
	river_slope += 0.65 * 0.31 + 1.25 * 0.054 + 0.50 * 0.23
	var next := 0
	var leaf_cursor := 0
	var group_cursor := 0
	var maximum_radius := 0.0
	var support_error := 0.0
	var attachment_error := 0.0
	var height_min := INF
	var height_max := -INF
	var inner_sum := 0.0
	var outer_sum := 0.0
	var inner_count := 0
	var outer_count := 0
	var margins := Vector4(INF, INF, INF, INF)
	var observed_heights := PackedFloat32Array()
	var reach_min := INF
	var reach_max := -INF
	var has_groups := fringe.has_meta("leaf_group_ranges") or fringe.has_meta("leaf_group_bases") or fringe.has_meta("leaf_group_plant_indices")
	assert(_require(has_groups and fringe.has_meta("heights"), "Final protocol requires group and height metadata"))
	var group_ranges := PackedVector2Array()
	var group_bases := PackedVector3Array()
	var group_owners := PackedInt32Array()
	if has_groups:
		assert(_require(fringe.has_meta("leaf_group_ranges") and fringe.has_meta("leaf_group_bases") and fringe.has_meta("leaf_group_plant_indices")))
		group_ranges = fringe.get_meta("leaf_group_ranges")
		group_bases = fringe.get_meta("leaf_group_bases")
		group_owners = fringe.get_meta("leaf_group_plant_indices")
		assert(_require(group_ranges.size() == group_bases.size() and group_ranges.size() == group_owners.size()))
	for r in range(roots.size()):
		var span := ranges[r]
		assert(_require(span.is_finite() and span.x == float(next) and span.y == float(int(span.y))))
		assert(_require(groups[r] == 3, "Final protocol: exactly three two-blade tiers per plant"))
		var leaves := groups[r] * BLADES_PER_GROUP
		assert(_require(int(span.y) == 24 + leaves * 18,
			"branchlets-93-1 requires two 12-corner twigs and the explicitly agreed fan count per group"))
		var end := next + int(span.y)
		assert(_require(end <= vertices.size()))
		var lower := _twig_endpoints(vertices, normals, colors, uv, next)
		var upper := _twig_endpoints(vertices, normals, colors, uv, next + 12)
		var actual_root := lower[0]
		var actual_joint := lower[1]
		var actual_tip := upper[1]
		assert(_require(actual_joint.distance_to(upper[0]) < EPS, "The two actual twig segments must meet"))
		assert(_require(roots[r].is_finite() and joints[r].is_finite() and tips[r].is_finite()))
		assert(_require(actual_root.distance_to(roots[r]) < EPS and actual_joint.distance_to(joints[r]) < EPS and actual_tip.distance_to(tips[r]) < EPS,
			"Metadata must agree with twig endpoints reconstructed from emitted corners"))
		assert(_require(actual_joint.y > actual_root.y and actual_tip.y > actual_joint.y))
		var height := actual_tip.y - actual_root.y
		assert(_require(height >= 0.25 - EPS and height <= 0.65 + EPS))
		observed_heights.append(height)
		height_min = minf(height_min, height)
		height_max = maxf(height_max, height)
		var hit := {}
		for surface: TriangleMesh in [land, rocks]:
			var candidate := surface.intersect_ray(Vector3(actual_root.x, 60, actual_root.z), Vector3.DOWN)
			if not candidate.is_empty() and (hit.is_empty() or candidate.position.y > hit.position.y):
				hit = candidate
		assert(_require(not hit.is_empty() and hit.normal.y >= 0.82))
		var error := actual_root.distance_to(hit.position + Vector3.UP * 0.006)
		support_error = maxf(support_error, error)
		assert(_require(error < EPS and not scene.below_river_surface(actual_root.x, actual_root.z, hit.position.y)))
		assert(_require(patches[r] == 9 and is_finite(reaches[r])))
		var local := (Vector2(actual_root.x, actual_root.z) - Vector2(guide.x, guide.y)) / Vector2(guide.z, guide.w)
		var angle := local.angle()
		var lobe := 0.76 + 0.16 * sin(angle * 3.0 + 9.0 * 1.47) + 0.08 * sin(angle * 7.0 - 9.0)
		var actual_reach := local.length() / lobe
		assert(_require(actual_reach >= 0.52 - EPS and actual_reach <= 1.48 + EPS and absf(actual_reach - reaches[r]) < EPS))
		reach_min = minf(reach_min, actual_reach)
		reach_max = maxf(reach_max, actual_reach)
		if actual_reach < 1.0:
			inner_count += 1
			inner_sum += height
		else:
			outer_count += 1
			outer_sum += height
		var tier_base := Vector3.ZERO
		var previous_tier_y := actual_root.y
		for leaf in range(leaves):
			var first := next + 24 + leaf * 18
			assert(_require(leaf_cursor < leaf_ranges.size() and leaf_ranges[leaf_cursor] == Vector2(first, 18) and leaf_owners[leaf_cursor] == r))
			var actual_base := _verify_leaf(vertices, colors, normals, first)
			assert(_require(leaf_bases[leaf_cursor].is_finite() and actual_base.distance_to(leaf_bases[leaf_cursor]) < EPS))
			var attachment := minf(_segment_distance(actual_base, actual_root, actual_joint),
				_segment_distance(actual_base, actual_joint, actual_tip))
			attachment_error = maxf(attachment_error, attachment)
			assert(_require(attachment < EPS, "Actual zero-wind leaf base must attach to a FINITE actual twig segment"))
			if leaf % BLADES_PER_GROUP == 0:
				tier_base = actual_base
				assert(_require(tier_base.y > previous_tier_y and tier_base.y < actual_tip.y,
					"Actual tiers must ascend along the finite stem below its tip"))
				previous_tier_y = tier_base.y
				if has_groups:
					assert(_require(group_cursor < group_ranges.size()))
					assert(_require(group_ranges[group_cursor] == Vector2(first, BLADES_PER_GROUP * 18) and group_owners[group_cursor] == r))
					assert(_require(group_bases[group_cursor].is_finite() and group_bases[group_cursor].distance_to(tier_base) < EPS))
				group_cursor += 1
			else:
				assert(_require(actual_base.distance_to(tier_base) < EPS, "All blades of one tier must share the same real attachment"))
			leaf_cursor += 1
		for i in range(next, end):
			var p := vertices[i]
			assert(_require(p.is_finite() and normals[i].is_finite() and absf(normals[i].length() - 1.0) < 0.001))
			assert(_require(is_finite(colors[i].r) and is_finite(colors[i].g) and is_finite(colors[i].b) and is_finite(colors[i].a)))
			assert(_require(fields[i].is_finite() and fields[i].x >= 0.0 and fields[i].x <= 1.0 and fields[i].y == 0.0))
			assert(_require(uv[i].is_finite()))
			if i >= next + 24:
				assert(_require(uv[i].x >= -900.0 and uv[i].is_equal_approx(Vector2(p.x, p.z))))
				# ArrayMesh may quantize the non-endpoint color channel to UNORM8.
				assert(_require(colors[i].a == 0.0 or absf(colors[i].a - 0.65) <= 1.0 / 255.0 or colors[i].a == 1.0))
			var radius := Vector2(p.x - actual_root.x, p.z - actual_root.z).length()
			assert(_require(radius <= ROOT_RADIUS + EPS and radius + WIND_BUFFER <= 0.81 + EPS))
			maximum_radius = maxf(maximum_radius, radius)
			var clearance := _clearance(scene, p, river_slope)
			for channel in range(4):
				margins[channel] = minf(margins[channel], clearance[channel])
		next = end
	assert(_require(next == vertices.size() and leaf_cursor == leaf_ranges.size(), "No extra opaque pads, unassigned triangles or hidden leaf ranges"))
	if has_groups:
		assert(_require(group_cursor == group_ranges.size()))
	if fringe.has_meta("heights"):
		var declared_heights: PackedFloat32Array = fringe.get_meta("heights")
		assert(_require(declared_heights.size() == observed_heights.size()))
		for i in range(declared_heights.size()):
			assert(_require(is_finite(declared_heights[i]) and absf(declared_heights[i] - observed_heights[i]) < EPS))
	var build_ms: float = fringe.get_meta("build_ms")
	assert(_require(is_finite(build_ms) and build_ms >= 0.0))
	return {"branchlet_roots": roots.size(), "branchlet_triangles": vertices.size() / 3,
		"low_triangles": 16464, "total_triangles": 16464 + vertices.size() / 3,
		"twig_segments": roots.size() * 2, "leaf_fans": leaf_cursor, "tiers": group_cursor,
		"blades_per_group": BLADES_PER_GROUP, "actual_radius_m": maximum_radius,
		"root_support_error_m": support_error, "leaf_attachment_error_m": attachment_error,
		"all_vertex_wind_margins": str(margins), "stem_height_min_m": height_min, "stem_height_max_m": height_max,
		"actual_reach_min": reach_min, "actual_reach_max": reach_max,
		"inner_reach_cutoff": 1.0, "inner_count": inner_count, "outer_count": outer_count,
		"inner_mean_stem_height_m": inner_sum / float(inner_count) if inner_count > 0 else null,
		"outer_mean_stem_height_m": outer_sum / float(outer_count) if outer_count > 0 else null}

func _twig_endpoints(vertices: PackedVector3Array, normals: PackedVector3Array,
		colors: PackedColorArray, uv: PackedVector2Array, first: int) -> PackedVector3Array:
	# Recover the centerline from actual cross-card bases, NOT from metadata.
	var a := (vertices[first] + vertices[first + 1]) * 0.5
	var b := vertices[first + 2]
	assert(_require(a.is_finite() and b.is_finite() and a.distance_to(b) > EPS))
	var width := 0.0
	for plane in range(2):
		var at := first + plane * 6
		var side := (vertices[at + 1] - vertices[at]) * 0.5
		var axis := Vector3.RIGHT if plane == 0 else Vector3.FORWARD
		var half_width := side.dot(axis)
		assert(_require(half_width > 0.0 and side.distance_to(axis * half_width) < EPS))
		if plane == 0:
			width = half_width
		else:
			assert(_require(absf(half_width - width) < EPS))
		var expected := PackedVector3Array([a - side, a + side, b, b, a + side, b + side * 0.35])
		var normal := -side.cross(b - a).normalized()
		for corner in range(6):
			assert(_require(vertices[at + corner].distance_to(expected[corner]) < EPS,
				"All twig corners must form the declared two open cross-cards, not a pad/cap"))
			assert(_require(normals[at + corner].distance_to(normal) < 0.001))
			assert(_require(uv[at + corner] == Vector2(-2000, 0) and colors[at + corner].a == 0.0))
		for triangle in range(at, at + 6, 3):
			var cross := (vertices[triangle + 1] - vertices[triangle]).cross(vertices[triangle + 2] - vertices[triangle])
			assert(_require(cross.length_squared() > 0.000000000001 and cross.dot(normal) < 0.0))
	return PackedVector3Array([a, b])

func _segment_distance(p: Vector3, a: Vector3, b: Vector3) -> float:
	var axis := b - a
	assert(_require(axis.length_squared() > 0.000000000001))
	var t := clampf((p - a).dot(axis) / axis.length_squared(), 0.0, 1.0)
	return p.distance_to(a + axis * t)

func _require(condition: bool, message: String = "Isolation invariant failed") -> bool:
	# Assertions in a helper abort that helper, not necessarily its caller.
	# Schedule a nonzero exit and retain failure state so no caller can print PASS.
	if not condition:
		failed = true
		push_error(MARKER + ": FAIL; " + message)
		quit(1)
	return condition

func _verify_low_geometry(scene: Node3D, fringe: MeshInstance3D, guides: PackedVector4Array) -> void:
	assert(_require(fringe != null and fringe.get_child_count() == 0 and fringe.transform == Transform3D.IDENTITY))
	assert(_require(fringe.layers == 8 and fringe.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED))
	_verify_material(fringe)
	var mesh := fringe.mesh as ArrayMesh
	assert(_require(mesh != null and mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES))
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var fields: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	assert(_require(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty(), "Ranges describe unindexed emitted vertices"))
	assert(_require(vertices.size() == colours.size() and vertices.size() == normals.size()))
	assert(_require(vertices.size() == uv.size() and vertices.size() == fields.size()))
	assert(_require(vertices.size() % 3 == 0 and vertices.size() < 45000 * 3))
	var roots: PackedVector3Array = fringe.get_meta("roots")
	var patches: PackedInt32Array = fringe.get_meta("patches")
	var ranges: PackedVector2Array = fringe.get_meta("ranges")
	var reaches: PackedFloat32Array = fringe.get_meta("reaches")
	assert(_require(roots.size() > 100 and roots.size() == patches.size() and roots.size() == ranges.size() and roots.size() == reaches.size()))
	var land: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var rocks: TriangleMesh = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var slope := 0.0
	for i in range(scene.RIVER_BENDS.size() - 1):
		var a: Vector2 = scene.RIVER_BENDS[i]
		var b: Vector2 = scene.RIVER_BENDS[i + 1]
		slope = maxf(slope, 1.5 * absf(b.y - a.y) / absf(b.x - a.x))
	slope += 0.65 * 0.31 + 1.25 * 0.054 + 0.50 * 0.23
	var counts := PackedInt32Array()
	counts.resize(14)
	var next := 0
	var max_radius := 0.0
	var max_support_error := 0.0
	var margins := Vector4(INF, INF, INF, INF)
	for r in range(roots.size()):
		var span: Vector2 = ranges[r]
		assert(_require(span.is_finite() and span.x == float(next) and (span.y == 72.0 or span.y == 90.0)))
		var end := next + int(span.y)
		assert(_require(end <= vertices.size()))
		var actual_root := _verify_leaf(vertices, colours, normals, next)
		assert(_require(roots[r].is_finite() and actual_root.distance_to(roots[r]) < EPS, "Metadata must match the actual leaf base"))
		for first in range(next + 18, end, 18):
			assert(_require(_verify_leaf(vertices, colours, normals, first).distance_to(actual_root) < EPS,
				"Every actual leaf base in this range must share the supported root"))
		var hit := {}
		for surface: TriangleMesh in [land, rocks]:
			var candidate := surface.intersect_ray(Vector3(actual_root.x, 60.0, actual_root.z), Vector3.DOWN)
			if not candidate.is_empty() and (hit.is_empty() or candidate.position.y > hit.position.y):
				hit = candidate
		assert(_require(not hit.is_empty() and hit.normal.y >= 0.82))
		var error := actual_root.distance_to(hit.position + Vector3.UP * 0.006)
		max_support_error = maxf(max_support_error, error)
		assert(_require(error < EPS and not scene.below_river_surface(actual_root.x, actual_root.z, hit.position.y), "Actual root must sit .006m above the highest land/rock support"))
		var patch: int = patches[r]
		assert(_require(patch >= 0 and patch < 14))
		counts[patch] += 1
		var guide: Vector4 = guides[patch]
		var local := (Vector2(actual_root.x, actual_root.z) - Vector2(guide.x, guide.y)) / Vector2(guide.z, guide.w)
		var angle := local.angle()
		var lobe := 0.76 + 0.16 * sin(angle * 3.0 + patch * 1.47) + 0.08 * sin(angle * 7.0 - patch)
		var reach := local.length() / lobe
		assert(_require(reach >= 0.52 - EPS and reach <= 1.48 + EPS and absf(reach - reaches[r]) < EPS,
			"Root positions must independently reproduce their frozen-guide reach"))
		for i in range(next, end):
			var p: Vector3 = vertices[i]
			assert(_require(p.is_finite() and normals[i].is_finite() and absf(normals[i].length() - 1.0) < 0.001))
			assert(_require(is_finite(colours[i].r) and is_finite(colours[i].g) and is_finite(colours[i].b) and is_finite(colours[i].a)))
			assert(_require(colours[i].a >= 0.0 and colours[i].a <= 1.0))
			assert(_require(uv[i].is_finite() and uv[i].x >= -900.0 and uv[i].is_equal_approx(Vector2(p.x, p.z)), "Real leaves only, with emitted world-XZ UVs"))
			assert(_require(fields[i].is_finite() and fields[i].x >= 0.0 and fields[i].x <= 1.0))
			var radius := Vector2(p.x - actual_root.x, p.z - actual_root.z).length()
			assert(_require(radius <= ROOT_RADIUS + EPS and radius + WIND_BUFFER <= 0.81 + EPS))
			max_radius = maxf(max_radius, radius)
			var clearance := _clearance(scene, p, slope)
			for channel in range(4):
				margins[channel] = minf(margins[channel], clearance[channel])
		next = end
	assert(_require(next == vertices.size(), "Root ranges must partition every actual vertex without gaps/overlap"))
	for count: int in counts:
		assert(_require(count > 0, "Every frozen crown guide must have a fringe"))
	assert(_require(counts == fringe.get_meta("patch_counts")))
	var build_ms: float = fringe.get_meta("build_ms")
	assert(_require(is_finite(build_ms) and build_ms >= 0.0))
	print("MEADOW_BRANCHLET_LOW_GEOMETRY: checked; five v77 bundles / nine mesh-array and collision snapshots exact; %d supported roots / %d triangles in 14 guides; open six-triangle leaves only; actual radius %.5f + .06m wind; support error %.6f; all-vertex road/Boss/river/habitat margins %s; reported build_ms=%.1f (diagnostic); geometry/source only, GPU/visual acceptance NOT TESTED" % [roots.size(), vertices.size() / 3, max_radius, max_support_error, margins, build_ms])

func _verify_material(mesh: MeshInstance3D) -> void:
	var material := mesh.material_override as ShaderMaterial
	assert(_require(material != null and material.shader.resource_path == "res://shaders/meadow_leaves.gdshader"))
	assert(_require(material.get_shader_parameter("middle_scrub") == true))
	assert(_require(material.get_shader_parameter("foothill_scrub") != true))
	assert(_require(mesh.material_overlay == null and material.next_pass == null))
	assert(_require(fringe_material_shader_matches(material), "Require unchanged approved leaves shader and turf texture"))
	assert(_require(mesh.get_surface_override_material(0) == null))
	var source := material.shader.code
	var comments := RegEx.new()
	assert(_require(comments.compile(r"//[^\r\n]*|/\*[\s\S]*?\*/") == OK))
	var compact := RegEx.new()
	assert(_require(compact.compile(r"\s+") == OK))
	source = compact.sub(comments.sub(source, "", true), "", true)
	var vertex := "voidvertex(){floatphase=VERTEX.x*0.31+VERTEX.z*0.21;floatbreeze=(sin(phase+meadow_clock*1.4)*0.70+sin(phase*2.7-meadow_clock*2.1)*0.30)*0.055;VERTEX.x+=breeze*COLOR.a*COLOR.a;VERTEX.z+=breeze*COLOR.a*0.4;world_position=(MODEL_MATRIX*vec4(VERTEX,1)).xyz;leaf_world_normal=normalize(mat3(MODEL_MATRIX)*NORMAL);}"
	assert(_require(source.contains(vertex + "voidfragment(){"), "Revisit the all-phase wind bound after any vertex-stage change"))
	for path: String in ["res://shaders/meadow_palette.gdshaderinc", "res://shaders/meadow_surface.gdshaderinc"]:
		source += compact.sub(comments.sub(FileAccess.get_file_as_string(path), "", true), "", true)
	assert(_require(not source.contains("EMISSION") and not source.contains("ALPHA"), "No emission or alpha material output"))
	assert(_require(Vector2(0.055, 0.055 * 0.4).length() < WIND_BUFFER))


func fringe_material_shader_matches(material: ShaderMaterial) -> bool:
	var path := "res://shaders/meadow_leaves.gdshader"
	var texture := material.get_shader_parameter("meadow_texture") as Texture2D
	return FileAccess.get_sha256(path).to_lower() == SHADER_SHA \
		and material.shader.code.replace("\r\n", "\n") == FileAccess.get_file_as_string(path).replace("\r\n", "\n") \
		and texture != null and texture.resource_path == "res://assets/materials/meadow-sward-v60.png"

func _clearance(scene: Node3D, p: Vector3, river_slope: float) -> Vector4:
	# Conservative whole .06m disk, not a sampled wind phase. Width is monotonic.
	var q := Vector2(p.x, p.z)
	var width := maxf(scene.road_half_width(q.y - WIND_BUFFER), scene.road_half_width(q.y + WIND_BUFFER))
	assert(_require(q.y - WIND_BUFFER > scene.RIVER_BENDS[-1].x))
	var margins := Vector4(scene.distance_to_road(q) - width - WIND_BUFFER,
		q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS - WIND_BUFFER,
		absf(q.x - scene.river_center(q.y)) - scene.river_half_width(q.y) - WIND_BUFFER * sqrt(1.0 + river_slope * river_slope), INF)
	for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
		var dx := maxf(habitat.position.x - q.x, q.x - habitat.end.x)
		var dz := maxf(habitat.position.y - q.y, q.y - habitat.end.y)
		margins.w = minf(margins.w, maxf(dx, dz) - WIND_BUFFER)
	assert(_require(margins.x >= 0.9 and margins.y >= 1.5 and margins.z >= 2.2 and margins.w >= 0.4,
		"Actual fringe vertex plus all-phase wind violates road/Boss/river/habitat reserves: " + str(margins)))
	return margins

func _verify_leaf(vertices: PackedVector3Array, colours: PackedColorArray, normals: PackedVector3Array, first: int) -> Vector3:
	# Independently reconstruct the emitted open fan: six boundary edges and one
	# common raised ridge. This rejects closed caps, extra faces and relabelled ranges.
	var base := Vector3.ZERO
	var ridge := Vector3.ZERO
	var bases := 0
	var ridges := 0
	var boundary := PackedVector3Array()
	for i in range(first, first + 18):
		if colours[i].a == 0.0:
			assert(_require(bases == 0 or vertices[i] == base))
			base = vertices[i]
			bases += 1
		if colours[i].a == 1.0:
			assert(_require(ridges == 0 or vertices[i] == ridge))
			ridge = vertices[i]
			ridges += 1
		elif not boundary.has(vertices[i]):
			boundary.append(vertices[i])
	assert(_require(bases == 2 and ridges == 6 and boundary.size() == 6 and not boundary.has(ridge)))
	var degree := PackedInt32Array([0, 0, 0, 0, 0, 0])
	var edges := {}
	for first_corner in range(first, first + 18, 3):
		var a: Vector3 = vertices[first_corner]
		var cross := (vertices[first_corner + 1] - a).cross(vertices[first_corner + 2] - a)
		var normal: Vector3 = normals[first_corner] + normals[first_corner + 1] + normals[first_corner + 2]
		assert(_require(cross.length_squared() > 0.000000000001 and cross.dot(normal) < 0.0))
		var sides := PackedInt32Array()
		var centers := 0
		for i in range(first_corner, first_corner + 3):
			if vertices[i] == ridge:
				centers += 1
			else:
				sides.append(boundary.find(vertices[i]))
		assert(_require(centers == 1 and sides.size() == 2 and sides[0] != sides[1]))
		var edge := Vector2i(mini(sides[0], sides[1]), maxi(sides[0], sides[1]))
		assert(_require(not edges.has(edge), "Duplicate/overlapping fan faces are not another leaf"))
		edges[edge] = true
		degree[sides[0]] += 1
		degree[sides[1]] += 1
	for count: int in degree:
		assert(_require(count == 2, "Six open boundary edges must form the leaf outline"))
	var connected := {0: true}
	for step in range(6):
		for edge: Vector2i in edges:
			if connected.has(edge.x) or connected.has(edge.y):
				connected[edge.x] = true
				connected[edge.y] = true
	assert(_require(connected.size() == 6, "The outline must be one connected open fan"))
	var tip := base
	for p: Vector3 in boundary:
		if Vector2(p.x - base.x, p.z - base.z).length_squared() > Vector2(tip.x - base.x, tip.z - base.z).length_squared():
			tip = p
	var length := tip - base
	var axis := Vector2(length.x, length.z)
	assert(_require(axis.length() > 0.01 and tip.y > base.y and ridge.y > base.y))
	for p: Vector3 in boundary:
		var delta := Vector2(p.x - base.x, p.z - base.z)
		assert(_require(delta.dot(axis) >= -EPS and delta.dot(axis) <= axis.length_squared() + EPS))
		assert(_require(absf(axis.cross(delta)) <= axis.length_squared() * 0.31 + EPS, "Pointed leaf silhouette, not a broad cover disk"))
	return base

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
