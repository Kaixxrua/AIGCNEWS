extends RefCounted
## Native-aspect mountain region; local mesh UVs, no new material/collider/card.

const COLUMNS := 64
const ROWS := 20
const ROOT_BAND := 0.10
const PEAK_LIFT := 0.0
const DEPTH_SCALE := 8.0 # Bounded C-source shoulder, not the old narrow fins.

static func apply(scene: Node3D, mountain: MeshInstance3D) -> void:
	if mountain.has_meta("mountain_relief_v97"):
		return
	assert(scene.is_ancestor_of(mountain))
	var quad := mountain.mesh as QuadMesh
	var material := mountain.material_override as ShaderMaterial
	assert(quad != null and material != null, "Mountain relief requires the original mountain card")
	assert(not bool(material.get_shader_parameter("face_camera")), "Relief must remain in world space")
	var texture := material.get_shader_parameter("asset_texture") as Texture2D
	assert(texture != null)
	var region: Vector4 = material.get_shader_parameter("uv_region")
	assert(region.x >= 0.0 and region.y >= 0.0 and region.z > 0.0 and region.w > 0.0
		and region.x + region.z <= 1.000001 and region.y + region.w <= 1.000001)
	var native_height := quad.size.x * texture.get_height() * region.w / (texture.get_width() * region.z)
	assert(absf(quad.size.y - native_height) < 0.001, "Mountain region must retain native aspect")
	var flat_right := mountain.name == &"RightMountainRidge"
	var source := texture.get_image()
	assert(source != null and not source.is_empty())
	if source.is_compressed():
		var result := source.decompress()
		assert(result == OK, "Mountain alpha must be readable")
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var roots := PackedVector2Array()
	var root_shifts := PackedFloat32Array()
	var root_triangle_hits := PackedByteArray()
	var ground_node := scene.get_node("ContinuousMeadow") as MeshInstance3D
	assert(ground_node.global_transform == Transform3D.IDENTITY, "Terrain query requires world-space ground")
	var ground := ground_node.mesh.generate_triangle_mesh()
	var ground_bounds := ground_node.mesh.get_aabb()
	var scan_steps := maxi(1, ceili(region.w * (source.get_height() - 1)))
	var triangle_roots := 0
	var outside_roots := 0
	var depth_range := Vector2(INF, -INF)
	var x_range := Vector2(INF, -INF)
	var previous_x := -INF
	for column in range(COLUMNS + 1):
		var u := float(column) / COLUMNS
		var mapped_x := (_mapped_u(u) - 0.5) * quad.size.x
		assert(mapped_x > previous_x, "Mountain horizontal mapping must remain monotonic")
		previous_x = mapped_x
		var source_u := region.x + u * region.z
		var pixel_x := clampi(roundi(source_u * (source.get_width() - 1)), 0, source.get_width() - 1)
		var foot_v := clampf(0.5 + quad.center_offset.y / quad.size.y, 0.10, 0.99)
		var has_foot := false
		for sample_row in range(scan_steps, -1, -1):
			var local_v := float(sample_row) / scan_steps
			var y := clampi(roundi((region.y + local_v * region.w) * (source.get_height() - 1)), 0, source.get_height() - 1)
			if source.get_pixel(pixel_x, y).a > 0.60:
				foot_v = clampf((float(y) / (source.get_height() - 1) - region.y) / region.w, 0.0, 1.0)
				has_foot = true
				break
		var root_shift := 0.0
		if has_foot:
			var foot_local := quad.center_offset + Vector3(mapped_x, (0.5 - foot_v) * quad.size.y, 0.0)
			var foot_world := mountain.to_global(foot_local)
			# The height field and its rendered triangle interpolation differ on
			# the distant rolling slopes. Plant visible roots in the actual mesh.
			var ground_foot := ground_node.to_local(foot_world)
			var ray_top := Vector3(ground_foot.x, ground_bounds.end.y + 64.0, ground_foot.z)
			var hit := ground.intersect_ray(ray_top, Vector3.DOWN)
			if not hit.is_empty():
				foot_world.y = ground_node.to_global(Vector3(hit.position)).y - 0.05
				triangle_roots += 1
			else:
				# No height-function substitution inside the actual mesh's XZ bounds.
				# This conservative check covers the rectangular distant terrain.
				var inside := ground_foot.x >= ground_bounds.position.x and ground_foot.x <= ground_bounds.end.x \
					and ground_foot.z >= ground_bounds.position.z and ground_foot.z <= ground_bounds.end.z
				if inside:
					push_error("Mountain root missed actual terrain inside its bounds")
					assert(false, "In-bounds mountain grounding must use a real triangle hit")
					return # Fail closed in release too; original card remains untouched.
				foot_world.y = scene.terrain_height(foot_world.x, foot_world.z) - 0.05
				outside_roots += 1
			root_shift = mountain.to_local(foot_world).y - foot_local.y
			roots.append(Vector2(u, foot_v))
			root_shifts.append(root_shift)
			root_triangle_hits.append(0 if hit.is_empty() else 1)
		# Positive foundation shifts need enough blend height to avoid folding.
		var root_band := maxf(ROOT_BAND, maxf(root_shift, 0.0) * 2.0 / quad.size.y)
		assert(foot_v > root_band, "Mountain crop/root shift leaves no unfolded upper body")
		var previous_y := INF
		for row in range(ROWS + 1):
			# Include each actual alpha foot and its soft grounding band. The last
			# row only covers the existing transparent gutter, never a new skirt.
			var v := lerpf(0.0, foot_v - root_band, float(row) / 17.0)
			if row == 18:
				v = foot_v - root_band * 0.5
			elif row == 19:
				v = foot_v
			elif row == 20:
				v = 1.0
			# Opaque crop bottom: place its exact foot at v=1 without duplicate rows.
			if foot_v >= 1.0 and row >= 18:
				v = foot_v - root_band * float(20 - row) / 3.0
			var uv := Vector2(u, v)
			var rise := maxf(foot_v - v, 0.0)
			var rooted := smoothstep(0.06, 0.20, rise)
			var source_uv := Vector2(source_u, region.y + v * region.w)
			var depth := 0.0 if flat_right else _depth(source_uv) * rooted * DEPTH_SCALE
			var p := quad.center_offset + Vector3(mapped_x,
				(0.5 - v) * quad.size.y, depth)
			p.y += root_shift * smoothstep(foot_v - root_band, foot_v, v)
			assert(mountain.to_global(p).z < -255.0, "Mountain front must remain behind castle")
			assert(p.y < previous_y, "Mountain UV rows must not fold")
			previous_y = p.y
			vertices.append(p)
			normals.append(Vector3.ZERO)
			uvs.append(uv)
			depth_range.x = minf(depth_range.x, depth)
			depth_range.y = maxf(depth_range.y, depth)
			x_range.x = minf(x_range.x, p.x)
			x_range.y = maxf(x_range.y, p.x)
	for column in range(COLUMNS):
		for row in range(ROWS):
			var a := column * (ROWS + 1) + row
			var b := a + ROWS + 1
			# Clockwise from the meadow (+Z), matching native QuadMesh front faces.
			indices.append_array(PackedInt32Array([a, b, a + 1, a + 1, b, b + 1]))
	for i in range(0, indices.size(), 3):
		var a := indices[i]
		var b := indices[i + 1]
		var c := indices[i + 2]
		var area_normal := (vertices[c] - vertices[a]).cross(vertices[b] - vertices[a])
		assert(area_normal.z > 0.0, "Mountain front winding must remain +Z")
		for vertex_index: int in [a, b, c]:
			normals[vertex_index] += area_normal
	for i in range(normals.size()):
		normals[i] = normals[i].normalized()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.resource_name = "MountainReliefV97"
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	mountain.mesh = mesh
	mountain.set_meta("mountain_relief_v97", true)
	mountain.set_meta("relief_base_size", quad.size)
	mountain.set_meta("relief_base_offset", quad.center_offset)
	mountain.set_meta("relief_grid", Vector2i(COLUMNS, ROWS))
	mountain.set_meta("relief_root_uvs", roots)
	mountain.set_meta("relief_root_shifts", root_shifts)
	mountain.set_meta("relief_root_triangle_hits", root_triangle_hits) # Same order as local root UVs.
	mountain.set_meta("relief_source_region", region)
	mountain.set_meta("relief_depth_range", depth_range)
	mountain.set_meta("relief_max_lift", PEAK_LIFT)
	mountain.set_meta("relief_x_range", x_range) # Actual local vertex extrema, including base offset.
	mountain.set_meta("relief_left_x_ratio", 1.0)
	mountain.set_meta("relief_x_width_ratio", (x_range.y - x_range.x) / quad.size.x)
	mountain.set_meta("relief_x_mapping", Vector4(0.0, 1.0, 1.0, 1.0))
	print("MEADOW_MOUNTAIN_RELIEF: %s; %d vertices / %d triangles; depth %.3f..%.3fm; %d actual-triangle roots, %d OUTSIDE-only height-field roots; local UV / source region %s; candidate, NOT visual PASS" % [mountain.name, vertices.size(), indices.size() / 3, depth_range.x, depth_range.y, triangle_roots, outside_roots, str(region)])

static func _mapped_u(u: float) -> float:
	return u

static func _lobe(uv: Vector2, centre: Vector2, radius: Vector2, lean: float = 0.0) -> float:
	var q := (uv - centre) / radius
	q.x -= lean * q.y
	return 1.0 - smoothstep(0.0, 1.0, q.length_squared())

static func _depth(uv: Vector2) -> float:
	# Full-source C alignment. Smooth union stays in [0,1], including overlap.
	var primary := _lobe(uv, Vector2(0.24, 0.47), Vector2(0.17, 0.24))
	var secondary := 0.65 * _lobe(uv, Vector2(0.46, 0.53), Vector2(0.12, 0.16))
	return 1.0 - (1.0 - primary) * (1.0 - secondary)

static func mesh_point(mountain: MeshInstance3D, uv: Vector2) -> Vector3:
	# Either mountain; input is LOCAL UV, not full-source/cropped texture UV.
	# Query actual triangles, not a deformation formula.
	if uv.x < 0.0 or uv.x > 1.0 or uv.y < 0.0 or uv.y > 1.0:
		return Vector3(INF, INF, INF)
	var arrays := mountain.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	# Constant-U columns: inspect only the chosen column's 40 actual triangles.
	var grid: Vector2i = mountain.get_meta("relief_grid")
	var column := clampi(floori(uv.x * grid.x), 0, grid.x - 1)
	var first := column * grid.y * 6
	for i in range(first, first + grid.y * 6, 3):
		var a := indices[i]
		var b := indices[i + 1]
		var c := indices[i + 2]
		var ab := uvs[b] - uvs[a]
		var ac := uvs[c] - uvs[a]
		var determinant := ab.cross(ac)
		if absf(determinant) < 0.00000001:
			continue
		var relative := uv - uvs[a]
		var wb := relative.cross(ac) / determinant
		var wc := ab.cross(relative) / determinant
		if wb >= -0.00001 and wc >= -0.00001 and wb + wc <= 1.00001:
			return mountain.to_global(vertices[a] * (1.0 - wb - wc) + vertices[b] * wb + vertices[c] * wc)
	return Vector3(INF, INF, INF)
