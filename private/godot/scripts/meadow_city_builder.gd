extends RefCounted
## One source used once. Only its narrow foundation band follows actual terrain.

const WIDTH := 172.0
const DEPTH := -255.0
const ANCHOR_V := 0.955
const ROOT_BAND := 0.24
const ROOT_SINK := 0.025
const ARCHITECTURE = preload("res://scripts/meadow_architecture_profiles.gd")

func build(meadow: Node3D, texture: Texture2D, peak_uv: Vector2) -> void:
	var frame: Vector2 = meadow.get_viewport().get_visible_rect().size
	var screen := frame * Vector2(0.70, 0.06)
	var origin: Vector3 = meadow.camera.project_ray_origin(screen)
	var direction: Vector3 = meadow.camera.project_ray_normal(screen)
	var peak := origin + direction * ((DEPTH - origin.z) / direction.z)
	var centre_x := peak.x - (peak_uv.x - 0.5) * WIDTH
	var city: MeshInstance3D = meadow._art("IndependentCastleHill", texture,
		Vector2(centre_x, DEPTH), WIDTH, Vector2(0.5, ANCHOR_V), 0.0,
		Color(0.93, 0.95, 0.92), false)
	# Preserve the source's architectural proportions. The old city was
	# compressed to 79% vertically just to satisfy two framing anchors.
	var height := WIDTH * texture.get_height() / float(texture.get_width())
	city.position.y = peak.y - (ANCHOR_V - peak_uv.y) * height
	city.set_meta("art_height", height)
	city.set_meta("facade_height", height)
	city.material_override.set_shader_parameter("art_contrast", 1.16)
	city.material_override.set_shader_parameter("art_exposure", 0.86)
	city.material_override.set_shader_parameter("bottom_fade", 0.008)
	city.material_override.set_shader_parameter("wind_strength", 0.0)
	city.material_override.set_shader_parameter("mip_bias", -0.45)
	ARCHITECTURE.apply_to(city.material_override, "IndependentCastleHill", Vector2(texture.get_width(), texture.get_height()))
	# Read the imported alpha only; never rewrite the PNG or paint a fake ground.
	var source := texture.get_image()
	if source.is_compressed():
		var result := source.decompress()
		assert(result == OK, "City alpha must be readable")
	var terrain: MeshInstance3D = meadow.get_node("ContinuousMeadow")
	var surface: TriangleMesh = terrain.mesh.generate_triangle_mesh()
	var columns: Array[float] = []
	for i in range(129):
		columns.append(float(i) / 128.0)
	columns.append(peak_uv.x)
	columns.sort()
	var roots := PackedVector2Array()
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var max_shift := 0.0
	var min_step := INF
	for u: float in columns:
		var pixel_x := clampi(roundi(u * (source.get_width() - 1)), 0, source.get_width() - 1)
		var bottom := -1
		for y in range(source.get_height() - 1, -1, -1):
			if source.get_pixel(pixel_x, y).a > 0.60:
				bottom = y
				break
		var foot_v := float(bottom) / (source.get_height() - 1) if bottom >= 0 else ANCHOR_V
		var x := (u - 0.5) * WIDTH
		var delta := 0.0
		if bottom >= 0:
			var p := Vector3(city.position.x + x, 80.0, DEPTH)
			var hit: Dictionary = surface.intersect_ray(p, Vector3.DOWN)
			assert(not hit.is_empty(), "City foundations must remain over real terrain")
			delta = hit.position.y - ROOT_SINK - (city.position.y + (ANCHOR_V - foot_v) * height)
			# A negative shift lowers the foot; an upward shift must not fold masonry.
			assert(delta < height * ROOT_BAND * 0.60, "City root band would fold")
			roots.append(Vector2(u, foot_v))
			max_shift = maxf(max_shift, absf(delta))
		var previous := INF
		for row in range(26):
			# Include the measured foot as an exact mesh row, not an interpolated
			# point straddling the end of the smooth root-band deformation.
			var v := lerpf(0.0, foot_v - ROOT_BAND, float(row) / 16.0)
			if row > 16:
				v = lerpf(foot_v - ROOT_BAND, foot_v, float(row - 16) / 8.0)
			if row == 25:
				v = 1.0
			var weight := smoothstep(foot_v - ROOT_BAND, foot_v, v)
			var y := (ANCHOR_V - v) * height + delta * weight
			if row > 0:
				min_step = minf(min_step, previous - y)
			previous = y
			vertices.append(Vector3(x, y, 0.0))
			normals.append(Vector3.BACK)
			uvs.append(Vector2(u, v))
	for column in range(columns.size() - 1):
		for row in range(25):
			var i := column * 26 + row
			# Godot front faces are clockwise, like its native QuadMesh. The old
			# reverse winding made the renderer flip these +Z normals away from
			# sunlight and toward the moon, hidden by heavy painted emission.
			indices.append_array(PackedInt32Array([i, i + 26, i + 1, i + 1, i + 26, i + 27]))
	assert(min_step > 0.0, "City masonry mesh must stay monotonic")
	city.mesh = meadow._array_mesh(vertices, normals, uvs, indices)
	city.set_meta("root_uvs", roots)
	city.set_meta("root_band", ROOT_BAND)
	city.set_meta("max_foundation_shift", max_shift)
	print("MEADOW_CITY_READY: one unique source; %d alpha-column feet; %d vertices; max foundation shift %.3f m" % [roots.size(), vertices.size(), max_shift])

static func mesh_point(city: MeshInstance3D, uv: Vector2) -> Vector3:
	# Both audits and the peak landmark query the rendered mesh, not expected Y.
	var arrays := city.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	for i in range(uvs.size() - 1):
		if absf(uvs[i].x - uv.x) > 0.00001 or absf(uvs[i + 1].x - uv.x) > 0.00001:
			continue
		if uvs[i].y <= uv.y and uvs[i + 1].y >= uv.y:
			var t := inverse_lerp(uvs[i].y, uvs[i + 1].y, uv.y)
			return city.to_global(vertices[i].lerp(vertices[i + 1], t))
	return Vector3(INF, INF, INF)

static func audit(meadow: Node3D) -> void:
	var city: MeshInstance3D = meadow.get_node("IndependentCastleHill")
	var roots: PackedVector2Array = city.get_meta("root_uvs")
	var hits := 0
	var maximum_error := 0.0
	for uv: Vector2 in roots:
		var p := mesh_point(city, uv)
		assert(p.is_finite(), "Measured city foot must exist on its actual mesh")
		var query := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 10.0, p - Vector3.UP * 10.0)
		var hit: Dictionary = meadow.get_world_3d().direct_space_state.intersect_ray(query)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			maximum_error = maxf(maximum_error, error)
			if error < 0.035:
				hits += 1
	assert(roots.size() > 100 and hits == roots.size(), "City foundation must meet actual collision terrain across its width")
	assert(float(city.material_override.get_shader_parameter("wind_strength")) == 0.0, "Masonry must remain rigid")
	print("MEADOW_CITY_ROOT_AUDIT: %d/%d mesh feet supported; max error %.4f m; rigid masonry" % [hits, roots.size(), maximum_error])
