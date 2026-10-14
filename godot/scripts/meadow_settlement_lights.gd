extends RefCounted
## Warm interiors at measured source windows. No duplicated bitmap props.

const HALO_SHADER = preload("res://shaders/meadow_light_halo.gdshader")

const CITY_WINDOWS := [
	Vector4(1360, 124, 2, 3),
	Vector4(1206, 154, 2, 3),
	Vector4(1270, 179, 2, 3),
	Vector4(1473, 220, 2, 3),
	Vector4(951, 282, 2, 3),
	Vector4(951, 317, 2, 3),
	Vector4(91, 533, 2, 3),
	Vector4(157, 584, 2, 3),
	Vector4(399, 545, 2, 3),
	Vector4(536, 486, 2, 3),
	Vector4(554, 486, 2, 3),
	Vector4(653, 412, 2, 3),
	Vector4(669, 448, 2, 3),
	Vector4(705, 558, 2, 3),
	Vector4(739, 558, 2, 3),
	Vector4(818, 583, 2, 3),
	Vector4(835, 612, 2, 3),
	Vector4(1007, 550, 2, 3),
	Vector4(1039, 488, 2, 3),
	Vector4(1114, 583, 2, 3),
	Vector4(1153, 583, 2, 3),
	Vector4(1241, 595, 2, 3),
	Vector4(1292, 558, 2, 3),
	Vector4(1532, 501, 2, 3),
	Vector4(1559, 535, 2, 3),
	Vector4(1476, 394, 2, 3),
	Vector4(1502, 396, 2, 3),
	Vector4(1649, 569, 2, 3),
	Vector4(1677, 552, 2, 3),
	Vector4(1768, 427, 2, 3),
	Vector4(1944, 535, 2, 3),
	Vector4(1980, 530, 2, 3),
]
const VILLAGE_WINDOWS := [
	Vector4(191, 239, 5, 7), Vector4(150, 309, 5, 9), Vector4(318, 335, 6, 9),
	Vector4(344, 226, 4, 8), Vector4(426, 226, 4, 8), Vector4(494, 207, 4, 7),
	Vector4(511, 207, 4, 7), Vector4(542, 204, 4, 6), Vector4(586, 205, 4, 6),
	Vector4(670, 344, 6, 10), Vector4(770, 304, 5, 8), Vector4(814, 304, 5, 8),
	Vector4(932, 263, 5, 8), Vector4(990, 207, 4, 6), Vector4(1121, 299, 5, 8),
	Vector4(1314, 356, 5, 10), Vector4(1358, 267, 4, 8), Vector4(1434, 209, 3, 7),
	Vector4(1520, 268, 4, 5), Vector4(1542, 309, 4, 7),
]

static func apply(meadow: Node3D) -> void:
	_install(meadow.get_node("IndependentCastleHill"), CITY_WINDOWS, 2.6)
	_install(meadow.get_node("DistantVillage"), VILLAGE_WINDOWS, 1.85)
	_build_window_halos(meadow)
	_build_window_pools(meadow)
	print("MEADOW_SETTLEMENT_LIGHTS_READY: 32 castle/town + 20 village window/door lights; no rotating-window masks")

static func _build_window_pools(meadow: Node3D) -> void:
	# Four bounded real lights supplement the distant emissive panes. Keep the
	# total point-light count bounded; do not spawn one light per painted window.
	var selected := {"IndependentCastleHill": [8, 26], "DistantVillage": [2, 15]}
	for node_name: String in selected:
		var building: MeshInstance3D = meadow.get_node(node_name)
		var material: ShaderMaterial = building.material_override
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		var region: Vector4 = material.get_shader_parameter("uv_region")
		var openings: Array = building.get_meta("window_source_pixels")
		for index: int in selected[node_name]:
			var opening: Vector4 = openings[index]
			var source_uv := Vector2(opening.x / texture.get_width(), opening.y / texture.get_height())
			var local_uv := (source_uv - Vector2(region.x, region.y)) / Vector2(region.z, region.w)
			var source := _surface_point(building, local_uv)
			var light := add_source_pool(meadow, node_name + "_WindowPool_%d" % index,
				source + Vector3(0, 0, 1.2), 3.0, 10.0 if node_name == "IndependentCastleHill" else 7.5)
			light.set_meta("window_anchor", source)

static func add_source_pool(meadow: Node3D, label: String, centre: Vector3, energy: float, radius: float) -> OmniLight3D:
	var light := OmniLight3D.new()
	light.name = label
	light.position = centre
	light.light_color = Color(1.0, 0.70, 0.43)
	light.light_energy = 0.0
	light.omni_range = radius
	light.omni_attenuation = 1.45
	light.shadow_enabled = false
	light.set_meta("night_energy", energy)
	light.set_meta("flicker_phase", centre.x * 0.31 + centre.z * 0.23)
	meadow.add_child(light)
	light.add_to_group("meadow_night_sources")
	return light

static func _install(building: MeshInstance3D, openings: Array, energy: float) -> void:
	var material: ShaderMaterial = building.material_override
	var texture: Texture2D = material.get_shader_parameter("asset_texture")
	var size := Vector2(texture.get_width(), texture.get_height())
	var windows: Array[Vector4] = []
	for opening: Vector4 in openings:
		windows.append(Vector4(opening.x / size.x, opening.y / size.y, opening.z / size.x, opening.w / size.y))
	while windows.size() < 32:
		windows.append(Vector4.ZERO)
	material.set_shader_parameter("lit_windows", windows)
	material.set_shader_parameter("window_count", openings.size())
	material.set_shader_parameter("window_energy", energy)
	building.set_meta("window_source_pixels", openings)

static func _halo_material(strength: float) -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = HALO_SHADER
	material.render_priority = 127
	material.set_shader_parameter("glow_strength", strength)
	return material

static func _build_window_halos(meadow: Node3D) -> void:
	var quads := MultiMesh.new()
	quads.transform_format = MultiMesh.TRANSFORM_3D
	var quad := QuadMesh.new()
	quad.size = Vector2.ONE
	quads.mesh = quad
	quads.instance_count = 52
	var points := PackedVector3Array()
	var index := 0
	for node_name: String in ["IndependentCastleHill", "DistantVillage"]:
		var building: MeshInstance3D = meadow.get_node(node_name)
		var material: ShaderMaterial = building.material_override
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		var region: Vector4 = material.get_shader_parameter("uv_region")
		var openings: Array = building.get_meta("window_source_pixels")
		for opening: Vector4 in openings:
			var source_uv := Vector2(opening.x / texture.get_width(), opening.y / texture.get_height())
			var local_uv := (source_uv - Vector2(region.x, region.y)) / Vector2(region.z, region.w)
			var position := _surface_point(building, local_uv)
			assert(position.is_finite(), "Halo must originate on a rendered window")
			position += meadow.camera.global_basis.z * 0.25
			var pane_width := opening.z * 2.0 / (texture.get_width() * region.z) * building.mesh.get_aabb().size.x
			# The physical pane stays source-sized. Its soft optical halo needs
			# enough screen coverage to remain legible on the farther city.
			var diameter := clampf(pane_width * 5.4, 3.2 if node_name == "IndependentCastleHill" else 1.5, 5.8)
			quads.set_instance_transform(index, Transform3D(Basis.IDENTITY.scaled(Vector3.ONE * diameter), position))
			points.append(position)
			index += 1
	var glow := MultiMeshInstance3D.new()
	glow.name = "SettlementWindowHalos"
	glow.multimesh = quads
	glow.material_override = _halo_material(0.32)
	glow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	glow.extra_cull_margin = 6.0
	glow.set_meta("window_centres", points)
	meadow.add_child(glow)

static func _surface_point(building: MeshInstance3D, uv: Vector2) -> Vector3:
	var arrays := building.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	for i in range(0, indices.size(), 3):
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
			return building.to_global(vertices[a] * (1.0 - wb - wc) + vertices[b] * wb + vertices[c] * wc)
	return Vector3(INF, INF, INF)

static func add_lantern_halo(meadow: Node3D, centre: Vector3) -> void:
	var glow := MeshInstance3D.new()
	glow.name = "TrailLanternHalo"
	var quad := QuadMesh.new()
	quad.size = Vector2(0.95, 0.95)
	glow.mesh = quad
	glow.material_override = _halo_material(0.43)
	glow.position = centre + meadow.camera.global_basis.z * 0.10
	glow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	meadow.add_child(glow)

static func audit(meadow: Node3D) -> void:
	var count := 0
	for node_name: String in ["IndependentCastleHill", "DistantVillage"]:
		var building: MeshInstance3D = meadow.get_node(node_name)
		var material: ShaderMaterial = building.material_override
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		var source := texture.get_image()
		if source.is_compressed():
			assert(source.decompress() == OK)
		var openings: Array = building.get_meta("window_source_pixels")
		assert(int(material.get_shader_parameter("window_count")) == openings.size())
		var region: Vector4 = material.get_shader_parameter("uv_region")
		var region_rect := Rect2(region.x, region.y, region.z, region.w)
		for opening: Vector4 in openings:
			var uv := Vector2(opening.x / texture.get_width(), opening.y / texture.get_height())
			assert(region_rect.has_point(uv), "Lights cannot leak into another atlas region")
			assert(source.get_pixel(int(opening.x), int(opening.y)).a > 0.9, "Window centre must be on opaque artwork")
			count += 1
	for node_name: String in ["VillageRotor_0", "VillageRotor_1"]:
		assert(int(meadow.get_node(node_name).material_override.get_shader_parameter("window_count")) == 0,
			"Window lights must never turn with the rotors")
	assert(count == 52)
	var glow: MultiMeshInstance3D = meadow.get_node("SettlementWindowHalos")
	assert(glow.multimesh.instance_count == 52 and glow.get_meta("window_centres").size() == 52)
	assert(meadow.has_node("TrailLanternHalo"), "The near lantern also needs a soft halo")
	print("MEADOW_SETTLEMENT_LIGHTS_AUDIT: 52/52 opaque artwork anchors; two static buildings; rotor windows disabled")
	print("MEADOW_HALO_AUDIT: 52 batched window halos + 1 lantern halo; depth tested; shared paused clock")
