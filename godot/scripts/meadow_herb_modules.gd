extends RefCounted
## Two unique source crops; shallow curved meshes with measured basal support.
## The native PNG is never rewritten. Existing meadow grass stays in place.
const TEXTURE = preload("res://assets/foliage/meadow-herbs-v73.png")
const CROPS := [Rect2i(24, 260, 905, 344), Rect2i(998, 208, 882, 414)]
const NAMES := ["RoadsideGrass", "Wildflowers"]
const FEET := [Vector2(-9.12985, 7.03097), Vector2(13.5, -4.5)]
const WIDTHS := [4.0, 5.4]
const OLD_SEAM_FEET := [Vector2(-9.12985, 7.03097), Vector2(10.0, -3.0)]
const COLUMNS := 48
const ROWS := 24
const ROOT_ROW := 20

static func build(scene: Node3D, index: int) -> MeshInstance3D:
	var crop: Rect2i = CROPS[index]
	var size := Vector2(TEXTURE.get_width(), TEXTURE.get_height())
	var region := Rect2(Vector2(crop.position) / size, Vector2(crop.size) / size)
	var anchor := Vector2(0.50, 0.975)
	var plant: MeshInstance3D = scene._art(NAMES[index], TEXTURE, FEET[index], WIDTHS[index],
		anchor, -0.025, Color(0.91, 0.96, 0.85), true, region)
	# Art relocation must not randomly reshuffle the established understory.
	# These short ground blades remain useful where the old broad flower base was.
	plant.set_meta("seam_sampling_foot", OLD_SEAM_FEET[index])
	plant.material_override.set_shader_parameter("remove_pale_matte", false)
	plant.material_override.set_shader_parameter("edge_inset", 0.35)
	plant.material_override.set_shader_parameter("relief_strength", 0.18)
	plant.material_override.set_shader_parameter("art_contrast", 1.06)
	plant.material_override.set_shader_parameter("art_exposure", 0.87)
	plant.material_override.set_shader_parameter("wind_strength", 0.065)
	plant.material_override.set_shader_parameter("rooted_herb", true)
	_conform(scene, plant, crop)
	return plant

static func _conform(scene: Node3D, plant: MeshInstance3D, crop: Rect2i,
		image_source: Image = null, basal_band: float = 0.0, surface: TriangleMesh = null) -> void:
	var source := image_source if image_source != null else TEXTURE.get_image()
	var quad: QuadMesh = plant.mesh
	var basis: Basis = scene.camera.global_basis
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var colours := PackedColorArray()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var roots := PackedVector3Array()
	var root_uvs := PackedVector2Array()
	var deltas := PackedFloat32Array()
	var bottoms := PackedFloat32Array()
	var depth := quad.size.x * 0.13
	for column in range(COLUMNS + 1):
		var u := float(column) / COLUMNS
		var pixel_x := clampi(crop.position.x + roundi(u * (crop.size.x - 1)), 0, source.get_width() - 1)
		var bottom := -1
		# A small horizontal neighbourhood avoids isolated antialias specks.
		for y in range(crop.position.y, crop.end.y):
			var solid := 0
			for dx in range(-2, 3):
				solid += int(source.get_pixel(clampi(pixel_x + dx, 0, source.get_width() - 1), y).a > 0.60)
			if solid >= 3:
				bottom = y
		var v := float(bottom - crop.position.y) / float(crop.size.y - 1) if bottom >= 0 else 0.975
		# Woody shrubs and arching fern tips are not carpets: only the low basal
		# stems are support points. Suspended leaf tips keep their native height.
		var visible_root := bottom >= 0 and v >= basal_band
		if not visible_root and basal_band > 0.0:
			v = 0.975
		bottoms.append(v)
		var x := quad.center_offset.x + (u - 0.5) * quad.size.x
		var z := -depth * pow(absf(u - 0.5) * 2.0, 2.0)
		var root_y := quad.center_offset.y + (0.5 - v) * quad.size.y
		var delta := 0.0
		for solve in range(6):
			var world := plant.position + basis * Vector3(x, root_y + delta, z)
			var soil_y: float = scene.terrain_height(world.x, world.z)
			if surface != null:
				var hit := surface.intersect_ray(Vector3(world.x, 60, world.z), Vector3.DOWN)
				assert(not hit.is_empty(), "Plant support needs actual triangulated soil")
				soil_y = hit.position.y
			delta += (soil_y - 0.025 - world.y) / basis.y.y
		deltas.append(delta)
		if visible_root and u > 0.04 and u < 0.96:
			roots.append(plant.position + basis * Vector3(x, root_y + delta, z))
			root_uvs.append(Vector2(u, v))
		for row in range(ROWS + 1):
			var t := float(row) / ROOT_ROW
			# The base follows the actual source feet. Preserve the upper foliage.
			var weight := smoothstep(0.25, 1.0, minf(t, 1.0))
			# Keep the full source through UV.y=1, including thin alpha tips.
			var uv_y := v * t if row <= ROOT_ROW else lerpf(v, 1.0, float(row - ROOT_ROW) / (ROWS - ROOT_ROW))
			var y := quad.center_offset.y + (0.5 - uv_y) * quad.size.y + delta * weight
			vertices.append(Vector3(x, y, z * weight))
			normals.append(Vector3.BACK)
			colours.append(Color(1, 1, 1, 1.0 - smoothstep(0.72, 1.0, minf(t, 1.0))))
			uvs.append(Vector2(u, uv_y))
	for column in range(COLUMNS):
		for row in range(ROWS):
			var i := column * (ROWS + 1) + row
			# Rows run from top to root; clockwise fronts face the camera.
			indices.append_array(PackedInt32Array([i, i + ROWS + 1, i + 1,
				i + 1, i + ROWS + 1, i + ROWS + 2]))
	# Geometric surface normals follow the shallow bow, including its shadow mesh.
	var sums := PackedVector3Array()
	sums.resize(vertices.size())
	for i in range(0, indices.size(), 3):
		var a := indices[i]
		var b := indices[i + 1]
		var c := indices[i + 2]
		var n := -(vertices[b] - vertices[a]).cross(vertices[c] - vertices[a])
		for j: int in [a, b, c]:
			sums[j] += n
	for i in range(normals.size()):
		normals[i] = sums[i].normalized()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_COLOR] = colours
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	plant.mesh = mesh
	plant.set_meta("herb_roots", roots)
	plant.set_meta("herb_root_uvs", root_uvs)
	plant.set_meta("herb_source_crop", crop)
	plant.set_meta("herb_depth", depth)
	plant.set_meta("herb_root_shifts", deltas)
	plant.set_meta("herb_source_bottoms", bottoms)
