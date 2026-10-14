extends Node3D
## One hamlet and two unique rotor regions. Rigid rotors share the weather clock.

const BODY_CROP := Rect2(16, 48, 1743, 365)
const ROTOR_CROPS := [Rect2(320, 450, 393, 392), Rect2(1050, 451, 378, 383)]
# Source pixel centres measured on the selected C atlas, not the crop centres.
const BODY_HUBS := [Vector2(399, 166), Vector2(1399, 212)]
const ROTOR_HUBS := [Vector2(516, 646), Vector2(1238, 643)]
const HUB_TARGETS := [Vector2(0.137, 0.213), Vector2(0.278, 0.223)]
const ROTOR_DIAMETERS := [8.8, 8.0]
const SPEEDS := [0.27, 0.21]
const PHASES := [-0.65, 0.22]
const DEPTH := -170.0
const ANCHOR_V := 0.987
const ROOT_BAND := 0.24
const ROOT_SINK := 0.025
const MESH_QUERY = preload("res://scripts/meadow_city_builder.gd")
const ARCHITECTURE = preload("res://scripts/meadow_architecture_profiles.gd")

var rotors: Array[MeshInstance3D] = []
var weather: Node
var last_clock := -INF

func build(meadow: Node3D, texture: Texture2D) -> void:
	var hubs: Array[Vector2] = []
	for pixel: Vector2 in BODY_HUBS:
		hubs.append((pixel + Vector2(0.5, 0.5) - BODY_CROP.position) / BODY_CROP.size)
	var targets: Array[Vector3] = []
	for target: Vector2 in HUB_TARGETS:
		var screen: Vector2 = target * meadow.get_viewport().get_visible_rect().size
		var origin: Vector3 = meadow.camera.project_ray_origin(screen)
		var direction: Vector3 = meadow.camera.project_ray_normal(screen)
		targets.append(origin + direction * ((DEPTH - origin.z) / direction.z))
	var width := (targets[1].x - targets[0].x) / (hubs[1].x - hubs[0].x)
	var centre_x := targets[0].x - (hubs[0].x - 0.5) * width
	var source_size := Vector2(texture.get_width(), texture.get_height())
	var village: MeshInstance3D = meadow._art("DistantVillage", texture, Vector2(centre_x, DEPTH),
		width, Vector2(0.5, ANCHOR_V), 0.0, Color(0.91, 0.95, 0.94), false,
		Rect2(BODY_CROP.position / source_size, BODY_CROP.size / source_size))
	var height := (targets[0].y - village.position.y) / (ANCHOR_V - hubs[0].y)
	var nominal_height := width * BODY_CROP.size.y / BODY_CROP.size.x
	print("MEADOW_VILLAGE_FIT: width %.3f; height %.3f; native %.3f; ratio %.3f; left target %s; base %s" % [
		width, height, nominal_height, height / nominal_height, targets[0], village.position])
	assert(height / nominal_height > 0.65 and height / nominal_height < 1.35,
		"Do not stretch the hamlet excessively to match a landmark")
	village.material_override.set_shader_parameter("art_contrast", 1.18)
	village.material_override.set_shader_parameter("art_exposure", 0.74)
	village.material_override.set_shader_parameter("bottom_fade", 0.008)
	village.material_override.set_shader_parameter("wind_strength", 0.0)
	village.material_override.set_shader_parameter("mip_bias", -0.45)
	ARCHITECTURE.apply_to(village.material_override, "DistantVillage", source_size)
	var source := texture.get_image()
	if source.is_compressed():
		var result := source.decompress()
		assert(result == OK, "Village alpha must be readable")
	_conform_foundation(meadow, village, source, width, height, hubs)
	for i in range(2):
		var crop: Rect2 = ROTOR_CROPS[i]
		var pivot: Vector2 = ROTOR_HUBS[i]
		var radius := 0.0
		for y in range(int(crop.position.y), int(crop.end.y)):
			for x in range(int(crop.position.x), int(crop.end.x)):
				if source.get_pixel(x, y).a > 0.60:
					radius = maxf(radius, Vector2(x, y).distance_to(pivot))
		assert(radius > 100.0, "Both distinct rotors must have visible radial blades")
		var rotor_width: float = ROTOR_DIAMETERS[i] * crop.size.x / (2.0 * radius)
		var anchor := (pivot + Vector2(0.5, 0.5) - crop.position) / crop.size
		var rotor: MeshInstance3D = meadow._art("VillageRotor_%d" % i, texture,
			Vector2(centre_x, DEPTH), rotor_width, anchor, 0.0, Color(0.91, 0.95, 0.94), false,
			Rect2(crop.position / source_size, crop.size / source_size))
		rotor.position = MESH_QUERY.mesh_point(village, hubs[i]) + Vector3(0.0, 0.0, 0.035)
		rotor.material_override.set_shader_parameter("art_contrast", 1.18)
		rotor.material_override.set_shader_parameter("art_exposure", 0.74)
		rotor.material_override.set_shader_parameter("wind_strength", 0.0)
		rotor.material_override.set_shader_parameter("mip_bias", -0.20)
		rotor.set_meta("body_hub_uv", hubs[i])
		rotor.set_meta("source_pivot_uv", anchor)
		rotor.set_meta("radius", ROTOR_DIAMETERS[i] * 0.5)
		rotor.extra_cull_margin = ROTOR_DIAMETERS[i]
		rotors.append(rotor)
	update_motion(0.0)
	print("MEADOW_VILLAGE_READY: one village and two unique rotors; width %.2f m; height %.2f m; source height ratio %.3f" % [width, height, height / nominal_height])

func _conform_foundation(meadow: Node3D, village: MeshInstance3D, source: Image,
		width: float, height: float, hubs: Array[Vector2]) -> void:
	var terrain: MeshInstance3D = meadow.get_node("ContinuousMeadow")
	var surface: TriangleMesh = terrain.mesh.generate_triangle_mesh()
	var columns: Array[float] = []
	for i in range(65):
		columns.append(float(i) / 64.0)
	for uv: Vector2 in hubs:
		columns.append(uv.x)
	columns.sort()
	var roots := PackedVector2Array()
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var min_step := INF
	for u: float in columns:
		var pixel_x := clampi(int(BODY_CROP.position.x + u * BODY_CROP.size.x), int(BODY_CROP.position.x), int(BODY_CROP.end.x) - 1)
		var bottom := -1
		for y in range(int(BODY_CROP.end.y) - 1, int(BODY_CROP.position.y) - 1, -1):
			if source.get_pixel(pixel_x, y).a > 0.60:
				bottom = y
				break
		var foot_v := (bottom + 0.5 - BODY_CROP.position.y) / BODY_CROP.size.y if bottom >= 0 else ANCHOR_V
		var x := (u - 0.5) * width
		var delta := 0.0
		if bottom >= 0:
			var hit: Dictionary = surface.intersect_ray(Vector3(village.position.x + x, 80.0, DEPTH), Vector3.DOWN)
			assert(not hit.is_empty(), "Village must stay on actual terrain")
			delta = hit.position.y - ROOT_SINK - (village.position.y + (ANCHOR_V - foot_v) * height)
			assert(delta < height * ROOT_BAND * 0.60, "Village root band would fold")
			roots.append(Vector2(u, foot_v))
		var previous := INF
		for row in range(26):
			var v := lerpf(0.0, foot_v - ROOT_BAND, float(row) / 16.0)
			if row > 16:
				v = lerpf(foot_v - ROOT_BAND, foot_v, float(row - 16) / 8.0)
			if row == 25:
				v = 1.0
			var y := (ANCHOR_V - v) * height + delta * smoothstep(foot_v - ROOT_BAND, foot_v, v)
			if row > 0:
				min_step = minf(min_step, previous - y)
			previous = y
			vertices.append(Vector3(x, y, 0.0))
			normals.append(Vector3.BACK)
			uvs.append(Vector2(u, v))
	for column in range(columns.size() - 1):
		for row in range(25):
			var i := column * 26 + row
			# Match the +Z facade normals with Godot's clockwise front faces.
			indices.append_array(PackedInt32Array([i, i + 26, i + 1, i + 1, i + 26, i + 27]))
	assert(min_step > 0.0, "Village foundation must not fold")
	village.mesh = meadow._array_mesh(vertices, normals, uvs, indices)
	village.set_meta("root_uvs", roots)

func _process(_delta: float) -> void:
	if weather == null:
		weather = get_parent().get_node_or_null("LivingWeather")
	if weather != null:
		update_motion(weather.animation_clock)

func update_motion(clock: float) -> void:
	if clock == last_clock:
		return
	last_clock = clock
	for i in range(rotors.size()):
		rotors[i].rotation.z = PHASES[i] + SPEEDS[i] * clock

static func audit(meadow: Node3D) -> void:
	var village: MeshInstance3D = meadow.get_node("DistantVillage")
	var roots: PackedVector2Array = village.get_meta("root_uvs")
	var hits := 0
	var maximum_error := 0.0
	for uv: Vector2 in roots:
		var p := MESH_QUERY.mesh_point(village, uv)
		assert(p.is_finite(), "Village root must exist on its rendered mesh")
		var ray := PhysicsRayQueryParameters3D.create(p + Vector3.UP * 10.0, p - Vector3.UP * 10.0)
		var hit: Dictionary = meadow.get_world_3d().direct_space_state.intersect_ray(ray)
		if not hit.is_empty():
			var error: float = absf(hit.position.y - p.y)
			maximum_error = maxf(maximum_error, error)
			if error < 0.035:
				hits += 1
	assert(roots.size() > 60 and hits == roots.size(), "Village foundation must meet its actual collision support")
	for i in range(2):
		var rotor: MeshInstance3D = meadow.get_node("VillageRotor_%d" % i)
		var hub := MESH_QUERY.mesh_point(village, rotor.get_meta("body_hub_uv"))
		var pivot: Vector2 = rotor.get_meta("source_pivot_uv")
		var quad: QuadMesh = rotor.mesh
		var actual := rotor.to_global(quad.center_offset + Vector3((pivot.x - 0.5) * quad.size.x, (0.5 - pivot.y) * quad.size.y, 0.0))
		assert(actual.distance_to(hub + Vector3(0, 0, 0.035)) < 0.0001, "Rotor pivot must stay on the painted axle")
		var screen: Vector2 = meadow.camera.unproject_position(hub) / meadow.get_viewport().get_visible_rect().size
		assert(screen.distance_to(HUB_TARGETS[i]) < 0.02, "Windmill scale/position drifted from reference")
		assert(float(rotor.material_override.get_shader_parameter("wind_strength")) == 0.0, "Wooden sails rotate rigidly, not as bending foliage")
		print("MEADOW_WINDMILL_HUB: %d at %s; reference %s; diameter %.2f m" % [i, screen, HUB_TARGETS[i], ROTOR_DIAMETERS[i]])
	print("MEADOW_VILLAGE_ROOT_AUDIT: %d/%d mesh feet supported; max error %.4f m; two fixed axles" % [hits, roots.size(), maximum_error])
