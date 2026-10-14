extends RefCounted
## One unique cutout follows a real depth-varying fence line, not a floating card.

const FENCE = preload("res://assets/props/country-fence-v47.png")
const ROOT_UVS := [Vector2(0.085, 0.964039), Vector2(0.386, 0.762102),
	Vector2(0.642, 0.582296), Vector2(0.923, 0.399723)]
const ROOT_XZ := [Vector2(-25.136728, 2.140587), Vector2(-23.309698, -0.068462),
	Vector2(-21.636118, -2.719261), Vector2(-19.397381, -4.533272)]
const ROOT_TARGETS := [Vector2(0.064, 0.730), Vector2(0.116, 0.704),
	Vector2(0.164, 0.678), Vector2(0.210, 0.660)]
const UV_HEIGHT_METRES := 3.4
const ROOT_SINK := 0.016

func build(meadow: Node3D) -> void:
	# Register this source exactly once using the same duplicate-art guard.
	var fence: MeshInstance3D = meadow._art("CountryFence", FENCE, ROOT_XZ[0], 10.2,
		ROOT_UVS[0], -ROOT_SINK, Color(0.83, 0.88, 0.85), false)
	fence.position = Vector3.ZERO
	fence.material_override.set_shader_parameter("art_contrast", 1.08)
	fence.material_override.set_shader_parameter("art_exposure", 0.86)
	fence.material_override.set_shader_parameter("relief_strength", 0.20)
	fence.material_override.set_shader_parameter("wind_strength", 0.0)
	var columns: Array[float] = []
	for i in range(41):
		columns.append(float(i) / 40.0)
	for root_uv: Vector2 in ROOT_UVS:
		columns.append(root_uv.x)
	columns.sort()
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for u: float in columns:
		var segment := 0
		while segment < ROOT_UVS.size() - 2 and u > ROOT_UVS[segment + 1].x:
			segment += 1
		# Extrapolate only the transparent padding beyond the end posts.
		var t := inverse_lerp(ROOT_UVS[segment].x, ROOT_UVS[segment + 1].x, u)
		var p: Vector2 = ROOT_XZ[segment].lerp(ROOT_XZ[segment + 1], t)
		var root_v: float = lerpf(ROOT_UVS[segment].y, ROOT_UVS[segment + 1].y, t)
		var base_y: float = meadow.terrain_height(p.x, p.y) - ROOT_SINK
		var tangent: Vector2 = (ROOT_XZ[segment + 1] - ROOT_XZ[segment]).normalized()
		var normal := Vector3(-tangent.y, 0, tangent.x)
		if normal.dot(meadow.camera.position - Vector3(p.x, base_y, p.y)) < 0.0:
			normal = -normal
		for row in range(17):
			var v := float(row) / 16.0
			vertices.append(Vector3(p.x, base_y + (root_v - v) * UV_HEIGHT_METRES, p.y))
			normals.append(normal)
			uvs.append(Vector2(u, v))
	for column in range(columns.size() - 1):
		for row in range(16):
			var i := column * 17 + row
			indices.append_array(PackedInt32Array([i, i + 1, i + 17, i + 1, i + 18, i + 17]))
	fence.mesh = meadow._array_mesh(vertices, normals, uvs, indices)
	fence.set_meta("root_uvs", PackedVector2Array(ROOT_UVS))
	fence.set_meta("reference_targets", PackedVector2Array(ROOT_TARGETS))
	var length := 0.0
	for i in range(ROOT_XZ.size() - 1):
		length += ROOT_XZ[i].distance_to(ROOT_XZ[i + 1])
	print("MEADOW_FENCE_READY: one unique three-rail source; four separate ground roots; %.2f m bent line; no wind on timber" % length)

static func mesh_root(fence: MeshInstance3D, root_uv: Vector2) -> Vector3:
	# Recover the point from the actual mesh UVs, not a saved expected root height.
	var arrays := fence.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	for i in range(uvs.size() - 1):
		if absf(uvs[i].x - root_uv.x) > 0.00001 or absf(uvs[i + 1].x - root_uv.x) > 0.00001:
			continue
		if uvs[i].y <= root_uv.y and uvs[i + 1].y >= root_uv.y:
			var t := inverse_lerp(uvs[i].y, uvs[i + 1].y, root_uv.y)
			return fence.to_global(vertices[i].lerp(vertices[i + 1], t))
	return Vector3(INF, INF, INF)

static func audit(meadow: Node3D) -> void:
	var fence: MeshInstance3D = meadow.get_node("CountryFence")
	var root_uvs: PackedVector2Array = fence.get_meta("root_uvs")
	var targets: PackedVector2Array = fence.get_meta("reference_targets")
	var hits := 0
	var maximum_error := 0.0
	var maximum_screen_error := 0.0
	var minimum_clearance := INF
	for i in range(root_uvs.size()):
		var p := mesh_root(fence, root_uvs[i])
		assert(p.is_finite(), "Every painted post foot must exist on the mesh")
		var ray := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 8.0, p - Vector3.UP * 3.0)
		var hit: Dictionary = meadow.get_world_3d().direct_space_state.intersect_ray(ray)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			maximum_error = maxf(maximum_error, error)
			if error < 0.035:
				hits += 1
		var screen: Vector2 = meadow.camera.unproject_position(p) / meadow.get_viewport().get_visible_rect().size
		maximum_screen_error = maxf(maximum_screen_error, screen.distance_to(targets[i]))
		var clearance: float = meadow.distance_to_road(Vector2(p.x, p.z)) - meadow.road_half_width(p.z)
		minimum_clearance = minf(minimum_clearance, clearance)
	assert(hits == 4, "Each actual fence post must sit on supported soil")
	assert(maximum_screen_error < 0.006, "Fence roots must preserve the reference foreground line")
	assert(minimum_clearance > 0.28, "Fence posts must not invade the trail")
	assert(float(fence.material_override.get_shader_parameter("wind_strength")) == 0.0, "Timber must remain rigid")
	print("MEADOW_FENCE_AUDIT: %d/4 mesh feet supported; max height error %.4f m; screen error %.5f; trail clearance %.3f m" % [
		hits, maximum_error, maximum_screen_error, minimum_clearance])
