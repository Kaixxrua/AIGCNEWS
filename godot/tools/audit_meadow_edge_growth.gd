extends SceneTree
## v91: actual fringe geometry/support; frozen world snapshots precede scene startup.
const GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
	"brush": ["MiddleMeadowBrush"]}
const WIND_BUFFER := 0.06
const ROOT_RADIUS := 0.75
const EPS := 0.0001

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var frozen := {}
	var guides := PackedVector4Array()
	for group: String in GROUPS:
		var packed := load("res://assets/baked/v77/" + group + ".scn") as PackedScene
		assert(packed != null)
		var container := packed.instantiate() as Node3D
		assert(container.get_meta("cache_version", "") == "meadow-77-1")
		assert(container.get_child_count() == GROUPS[group].size())
		for label: String in GROUPS[group]:
			# Bytes freeze arrays/shapes now, even if a shared Resource mutates later.
			frozen[label] = var_to_bytes(_snapshot(container.get_node(NodePath(label))))
		if group == "brush":
			guides = container.get_node("MiddleMeadowBrush").get_meta("growth_guides")
		container.free()
	assert(frozen.size() == 9)
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	var growth := scene.get_node("MeadowEdgeGrowth") as Node3D
	for frame in range(120):
		if growth.get("ready_complete") == true:
			break
		await process_frame
	assert(growth.get("ready_complete") == true, "Edge growth did not finish its parent-ready build")
	assert(scene.global_transform == Transform3D.IDENTITY and growth.transform == Transform3D.IDENTITY)
	for label: String in frozen:
		assert(var_to_bytes(_snapshot(scene.get_node(NodePath(label)))) == frozen[label],
			"Changed frozen v77 mesh arrays/transform/collision subtree: " + label)
	assert(guides.size() == 14 and guides == PackedVector4Array(scene.MIDDLE_BRUSH.GUIDES))
	_verify_fringe(scene, growth, guides)
	scene.queue_free()
	await process_frame
	quit()

func _snapshot(node: Node) -> Dictionary:
	# Same collision contracts as audit_middle_meadow_mass, serialized before build.
	var data := {"class": node.get_class(), "name": str(node.name), "children": []}
	if node is Node3D:
		data.transform = node.transform
	if node is MeshInstance3D:
		var mesh := node.mesh as ArrayMesh
		assert(mesh != null)
		data.layers = node.layers
		data.shadow = node.cast_shadow
		data.surfaces = []
		for surface in range(mesh.get_surface_count()):
			data.surfaces.append([mesh.surface_get_primitive_type(surface), mesh.surface_get_arrays(surface)])
	if node is CollisionObject3D:
		data.collision = [node.collision_layer, node.collision_mask]
	if node is CollisionShape3D:
		var shape := node.shape as ConcavePolygonShape3D
		assert(shape != null, "Frozen world collision must remain a triangle mesh")
		data.shape = [node.disabled, shape.get_faces(), shape.backface_collision]
	for child: Node in node.get_children():
		data.children.append(_snapshot(child))
	return data

func _verify_material(mesh: MeshInstance3D) -> void:
	var material := mesh.material_override as ShaderMaterial
	assert(material != null and material.shader.resource_path == "res://shaders/meadow_leaves.gdshader")
	assert(material.get_shader_parameter("middle_scrub") == true)
	assert(material.get_shader_parameter("foothill_scrub") != true)
	assert(mesh.material_overlay == null and material.next_pass == null)
	var source := FileAccess.get_file_as_string(material.shader.resource_path)
	var comments := RegEx.new()
	assert(comments.compile(r"//[^\r\n]*|/\*[\s\S]*?\*/") == OK)
	var compact := RegEx.new()
	assert(compact.compile(r"\s+") == OK)
	source = compact.sub(comments.sub(source, "", true), "", true)
	var vertex := "voidvertex(){floatphase=VERTEX.x*0.31+VERTEX.z*0.21;floatbreeze=(sin(phase+meadow_clock*1.4)*0.70+sin(phase*2.7-meadow_clock*2.1)*0.30)*0.055;VERTEX.x+=breeze*COLOR.a*COLOR.a;VERTEX.z+=breeze*COLOR.a*0.4;world_position=(MODEL_MATRIX*vec4(VERTEX,1)).xyz;leaf_world_normal=normalize(mat3(MODEL_MATRIX)*NORMAL);}"
	assert(source.contains(vertex + "voidfragment(){"), "Revisit the all-phase wind bound after any vertex-stage change")
	for path: String in ["res://shaders/meadow_palette.gdshaderinc", "res://shaders/meadow_surface.gdshaderinc"]:
		source += compact.sub(comments.sub(FileAccess.get_file_as_string(path), "", true), "", true)
	assert(not source.contains("EMISSION") and not source.contains("ALPHA"), "No emission or alpha material output")
	assert(Vector2(0.055, 0.055 * 0.4).length() < WIND_BUFFER)

func _clearance(scene: Node3D, p: Vector3, river_slope: float) -> Vector4:
	# Conservative whole .06m disk, not a sampled wind phase. Width is monotonic.
	var q := Vector2(p.x, p.z)
	var width := maxf(scene.road_half_width(q.y - WIND_BUFFER), scene.road_half_width(q.y + WIND_BUFFER))
	assert(q.y - WIND_BUFFER > scene.RIVER_BENDS[-1].x)
	var margins := Vector4(scene.distance_to_road(q) - width - WIND_BUFFER,
		q.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS - WIND_BUFFER,
		absf(q.x - scene.river_center(q.y)) - scene.river_half_width(q.y) - WIND_BUFFER * sqrt(1.0 + river_slope * river_slope), INF)
	for habitat: Rect2 in scene.WILDLIFE_CONTROLLER.HABITATS:
		var dx := maxf(habitat.position.x - q.x, q.x - habitat.end.x)
		var dz := maxf(habitat.position.y - q.y, q.y - habitat.end.y)
		margins.w = minf(margins.w, maxf(dx, dz) - WIND_BUFFER)
	assert(margins.x >= 0.9 and margins.y >= 1.5 and margins.z >= 2.2 and margins.w >= 0.4,
		"Actual fringe vertex plus all-phase wind violates road/Boss/river/habitat reserves: " + str(margins))
	return margins

func _verify_fringe(scene: Node3D, growth: Node3D, guides: PackedVector4Array) -> void:
	assert(growth.get_child_count() == 1, "Only the additive leaf mesh may be added; no colliders/caps")
	var fringe := growth.get_node("CrownToTurfFringe") as MeshInstance3D
	assert(fringe != null and fringe.get_child_count() == 0 and fringe.transform == Transform3D.IDENTITY)
	assert(fringe.layers == 8 and fringe.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED)
	_verify_material(fringe)
	var mesh := fringe.mesh as ArrayMesh
	assert(mesh != null and mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES)
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var fields: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	assert(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty(), "Ranges describe unindexed emitted vertices")
	assert(vertices.size() == colours.size() and vertices.size() == normals.size())
	assert(vertices.size() == uv.size() and vertices.size() == fields.size())
	assert(vertices.size() % 3 == 0 and vertices.size() < 45000 * 3)
	var roots: PackedVector3Array = fringe.get_meta("roots")
	var patches: PackedInt32Array = fringe.get_meta("patches")
	var ranges: PackedVector2Array = fringe.get_meta("ranges")
	var reaches: PackedFloat32Array = fringe.get_meta("reaches")
	assert(roots.size() > 100 and roots.size() == patches.size() and roots.size() == ranges.size() and roots.size() == reaches.size())
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
		assert(span.is_finite() and span.x == float(next) and (span.y == 72.0 or span.y == 90.0))
		var end := next + int(span.y)
		assert(end <= vertices.size())
		var actual_root := _verify_leaf(vertices, colours, normals, next)
		assert(roots[r].is_finite() and actual_root.distance_to(roots[r]) < EPS, "Metadata must match the actual leaf base")
		for first in range(next + 18, end, 18):
			assert(_verify_leaf(vertices, colours, normals, first).distance_to(actual_root) < EPS,
				"Every actual leaf base in this range must share the supported root")
		var hit := {}
		for surface: TriangleMesh in [land, rocks]:
			var candidate := surface.intersect_ray(Vector3(actual_root.x, 60.0, actual_root.z), Vector3.DOWN)
			if not candidate.is_empty() and (hit.is_empty() or candidate.position.y > hit.position.y):
				hit = candidate
		assert(not hit.is_empty() and hit.normal.y >= 0.82)
		var error := actual_root.distance_to(hit.position + Vector3.UP * 0.006)
		max_support_error = maxf(max_support_error, error)
		assert(error < EPS and not scene.below_river_surface(actual_root.x, actual_root.z, hit.position.y), "Actual root must sit .006m above the highest land/rock support")
		var patch: int = patches[r]
		assert(patch >= 0 and patch < 14)
		counts[patch] += 1
		var guide: Vector4 = guides[patch]
		var local := (Vector2(actual_root.x, actual_root.z) - Vector2(guide.x, guide.y)) / Vector2(guide.z, guide.w)
		var angle := local.angle()
		var lobe := 0.76 + 0.16 * sin(angle * 3.0 + patch * 1.47) + 0.08 * sin(angle * 7.0 - patch)
		var reach := local.length() / lobe
		assert(reach >= 0.52 - EPS and reach <= 1.48 + EPS and absf(reach - reaches[r]) < EPS,
			"Root positions must independently reproduce their frozen-guide reach")
		for i in range(next, end):
			var p: Vector3 = vertices[i]
			assert(p.is_finite() and normals[i].is_finite() and absf(normals[i].length() - 1.0) < 0.001)
			assert(is_finite(colours[i].r) and is_finite(colours[i].g) and is_finite(colours[i].b) and is_finite(colours[i].a))
			assert(colours[i].a >= 0.0 and colours[i].a <= 1.0)
			assert(uv[i].is_finite() and uv[i].x >= -900.0 and uv[i].is_equal_approx(Vector2(p.x, p.z)), "Real leaves only, with emitted world-XZ UVs")
			assert(fields[i].is_finite() and fields[i].x >= 0.0 and fields[i].x <= 1.0)
			var radius := Vector2(p.x - actual_root.x, p.z - actual_root.z).length()
			assert(radius <= ROOT_RADIUS + EPS and radius + WIND_BUFFER <= 0.81 + EPS)
			max_radius = maxf(max_radius, radius)
			var clearance := _clearance(scene, p, slope)
			for channel in range(4):
				margins[channel] = minf(margins[channel], clearance[channel])
		next = end
	assert(next == vertices.size(), "Root ranges must partition every actual vertex without gaps/overlap")
	for count: int in counts:
		assert(count > 0, "Every frozen crown guide must have a fringe")
	assert(counts == fringe.get_meta("patch_counts"))
	var build_ms: float = fringe.get_meta("build_ms")
	assert(is_finite(build_ms) and build_ms >= 0.0)
	print("MEADOW_EDGE_GROWTH_AUDIT: PASS; five v77 bundles / nine mesh-array and collision snapshots exact; %d supported roots / %d triangles in 14 guides; open six-triangle leaves only; actual radius %.5f + .06m wind; support error %.6f; all-vertex road/Boss/river/habitat margins %s; reported build_ms=%.1f (diagnostic); geometry/source only, GPU/visual acceptance NOT TESTED" % [roots.size(), vertices.size() / 3, max_radius, max_support_error, margins, build_ms])

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
			assert(bases == 0 or vertices[i] == base)
			base = vertices[i]
			bases += 1
		if colours[i].a == 1.0:
			assert(ridges == 0 or vertices[i] == ridge)
			ridge = vertices[i]
			ridges += 1
		elif not boundary.has(vertices[i]):
			boundary.append(vertices[i])
	assert(bases == 2 and ridges == 6 and boundary.size() == 6 and not boundary.has(ridge))
	var degree := PackedInt32Array([0, 0, 0, 0, 0, 0])
	var edges := {}
	for first_corner in range(first, first + 18, 3):
		var a: Vector3 = vertices[first_corner]
		var cross := (vertices[first_corner + 1] - a).cross(vertices[first_corner + 2] - a)
		var normal: Vector3 = normals[first_corner] + normals[first_corner + 1] + normals[first_corner + 2]
		assert(cross.length_squared() > 0.000000000001 and cross.dot(normal) < 0.0)
		var sides := PackedInt32Array()
		var centers := 0
		for i in range(first_corner, first_corner + 3):
			if vertices[i] == ridge:
				centers += 1
			else:
				sides.append(boundary.find(vertices[i]))
		assert(centers == 1 and sides.size() == 2 and sides[0] != sides[1])
		var edge := Vector2i(mini(sides[0], sides[1]), maxi(sides[0], sides[1]))
		assert(not edges.has(edge), "Duplicate/overlapping fan faces are not another leaf")
		edges[edge] = true
		degree[sides[0]] += 1
		degree[sides[1]] += 1
	for count: int in degree:
		assert(count == 2, "Six open boundary edges must form the leaf outline")
	var connected := {0: true}
	for step in range(6):
		for edge: Vector2i in edges:
			if connected.has(edge.x) or connected.has(edge.y):
				connected[edge.x] = true
				connected[edge.y] = true
	assert(connected.size() == 6, "The outline must be one connected open fan")
	var tip := base
	for p: Vector3 in boundary:
		if Vector2(p.x - base.x, p.z - base.z).length_squared() > Vector2(tip.x - base.x, tip.z - base.z).length_squared():
			tip = p
	var length := tip - base
	var axis := Vector2(length.x, length.z)
	assert(axis.length() > 0.01 and tip.y > base.y and ridge.y > base.y)
	for p: Vector3 in boundary:
		var delta := Vector2(p.x - base.x, p.z - base.z)
		assert(delta.dot(axis) >= -EPS and delta.dot(axis) <= axis.length_squared() + EPS)
		assert(absf(axis.cross(delta)) <= axis.length_squared() * 0.31 + EPS, "Pointed leaf silhouette, not a broad cover disk")
	return base
