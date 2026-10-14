extends RefCounted
## Six unique source crops, original RGBA kept intact; native-height tree crowns.
const ATLAS = preload("res://assets/foliage/mountain-groves-v100.png")
const HERBS = preload("res://scripts/meadow_herb_modules.gd")
const DAY_SHADER = preload("res://shaders/meadow_grove_day.gdshader")
const NATIVE_SHADER = preload("res://shaders/meadow_cutout.gdshader")
const CROPS: Array[Rect2] = [Rect2(38, 54, 565, 362), Rect2(676, 87, 550, 334),
	Rect2(32, 460, 572, 349), Rect2(668, 459, 558, 356),
	Rect2(31, 848, 575, 355), Rect2(681, 851, 544, 355)]
const ANCHORS: Array[Vector2] = [Vector2(0.390265487, 0.896408840), Vector2(0.580909091, 0.962574850),
	Vector2(0.320804196, 0.944126074), Vector2(0.389784946, 0.914325843),
	Vector2(0.392173913, 0.883098592), Vector2(0.664522059, 0.900000000)]
const FEET := [Vector2(-196, -280), Vector2(-153, -295), Vector2(-77, -278),
	Vector2(-50, -286), Vector2(187, -299), Vector2(199, -269)]
const WIDTHS := [34.0, 30.0, 28.0, 30.0, 32.0, 26.0]
const MAX_HEIGHTS := [22.0, 19.0, 18.0, 19.0, 21.0, 17.0]
const MARGIN := 0.30 # Covers the existing foliage wind (at most .24m).

class Atmosphere extends Node:
	var materials: Array[ShaderMaterial] = []
	var day_profiles: Array[Dictionary] = []
	var registered: Dictionary = {}
	var previous := Vector4(-1, -1, -1, -1)
	var previous_color := Color(-1, -1, -1)
	func register_grove(grove: MeshInstance3D) -> void:
		assert(grove != null, "Expected an already-built far woodland group")
		var id := grove.get_instance_id()
		if registered.has(id):
			return
		var original := grove.material_override as ShaderMaterial
		assert(original != null and (original.shader == NATIVE_SHADER or original.shader == DAY_SHADER))
		# Isolate shader/uniform changes, retaining texture resources and every
		# existing parameter. Never mutate a material shared with foreground art.
		var material := original.duplicate(false) as ShaderMaterial
		grove.material_override = material
		materials.append(material)
		# Candidate: recover shared incident-light response without contrast/mip
		# changes. Retain exact native values for night and unsupported fog modes.
		var native_tint: Color = original.get_shader_parameter("tint")
		var thick_crown := grove.has_meta("mountain_grove_index")
		var gain := Color(0.90, 0.98, 1.0) if thick_crown else Color(0.97, 1.0, 0.94)
		var anchor: Vector2 = grove.get_meta("art_anchor")
		var bottoms: PackedFloat32Array = grove.get_meta("herb_source_bottoms", PackedFloat32Array())
		var root_v := PackedFloat32Array()
		for column in range(25):
			var v := anchor.y
			if bottoms.size() > 1:
				var at := float(column) / 24.0 * (bottoms.size() - 1)
				var low := mini(int(at), bottoms.size() - 2)
				v = lerpf(bottoms[low], bottoms[low + 1], at - low)
			root_v.append(v)
		day_profiles.append({"tint": native_tint, "day_tint": native_tint * gain,
			"fill": float(original.get_shader_parameter("painted_fill")),
			"relief": float(original.get_shader_parameter("relief_strength")),
			"contact": float(original.get_shader_parameter("root_contact")),
			"root_v": root_v, "root_span": clampf(1.2 / float(grove.get_meta("art_height")), 0.035, 0.20)})
		registered[id] = true
		previous = Vector4(-1, -1, -1, -1)
	func _ready() -> void:
		process_priority = 2
	func _process(_delta: float) -> void:
		var scene := get_parent()
		var environment: Environment = scene.get_node("WorldEnvironment").environment
		var night: float = scene.get_node("LivingWeather").night_blend
		var supported: bool = environment != null and environment.fog_mode == Environment.FOG_MODE_EXPONENTIAL \
			and absf(environment.fog_height_density) < 0.0001 and environment.fog_sun_scatter == 0.0 \
			and environment.fog_aerial_perspective == 0.0
		var density: float = environment.fog_density if environment != null else 0.0
		var enabled: bool = environment != null and environment.fog_enabled
		var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy if environment != null else Color.BLACK
		var state := Vector4(night, density, float(enabled), float(supported))
		if state == previous and linear == previous_color:
			return
		previous = state
		previous_color = linear
		var target: Shader = DAY_SHADER if supported and night < 1.0 else NATIVE_SHADER
		var day := clampf(1.0 - night, 0.0, 1.0) if supported else 0.0
		for i in range(materials.size()):
			var material := materials[i]
			var profile: Dictionary = day_profiles[i]
			if material.shader != target:
				var retained := {}
				for entry: Dictionary in NATIVE_SHADER.get_shader_uniform_list():
					var value: Variant = material.get_shader_parameter(entry.name)
					if value != null:
						retained[entry.name] = value
				material.shader = target
				for key: String in retained:
					material.set_shader_parameter(key, retained[key])
			# Both source generations use the same diffuse/backlight shader. Reduce
			# the additive painted contribution and the whole-card rounded normal;
			# do not manufacture a painted sun direction or lift black leaf interiors.
			var tint: Color = profile.tint
			material.set_shader_parameter("tint", tint.lerp(profile.day_tint, day) if day > 0.0 else tint)
			material.set_shader_parameter("painted_fill", lerpf(profile.fill, 0.08, day) if day > 0.0 else profile.fill)
			material.set_shader_parameter("relief_strength", lerpf(profile.relief, 0.22, day) if day > 0.0 else profile.relief)
			material.set_shader_parameter("root_contact", lerpf(profile.contact, 0.38, day) if day > 0.0 else profile.contact)
			if target == DAY_SHADER:
				material.set_shader_parameter("grove_fog_enabled", enabled)
				material.set_shader_parameter("grove_fog_density", density)
				material.set_shader_parameter("grove_fog_linear_color", Vector3(linear.r, linear.g, linear.b))
				material.set_shader_parameter("grove_root_v", profile.root_v)
				material.set_shader_parameter("grove_root_span", profile.root_span)

static func build_selected(scene: Node3D) -> void:
	build(scene, ATLAS, CROPS, ANCHORS)

static func build(scene: Node3D, atlas: Texture2D, crops: Array[Rect2], anchors: Array[Vector2]) -> void:
	assert(atlas != null and atlas.get_width() > 0 and atlas.get_height() > 0)
	assert(crops.size() == 6 and anchors.size() == 6, "Six measured pixel crops and crop-local normalized root anchors required")
	if scene.has_meta("mountain_groves_built"):
		return
	var dimensions := Vector2(atlas.get_width(), atlas.get_height())
	var atlas_bounds := Rect2(Vector2.ZERO, dimensions)
	# Validate every source region before _art registers any pixels as occupied.
	for i in range(6):
		assert(crops[i].position.is_finite() and crops[i].size.is_finite())
		assert(crops[i].size.x > 0.0 and crops[i].size.y > 0.0 and atlas_bounds.encloses(crops[i]))
		assert(anchors[i].is_finite() and anchors[i].x >= 0.0 and anchors[i].x <= 1.0 and anchors[i].y > 0.0 and anchors[i].y <= 1.0)
		assert(not scene.has_node(NodePath("MountainGrove_%02d" % i)), "Do not append a partial/duplicate grove build")
		for j in range(i):
			assert(not crops[i].intersects(crops[j]), "Mountain groves must use disjoint source pixels")
	var camera := scene.get_node("Camera3D") as Camera3D
	var source := atlas.get_image()
	if source.is_compressed():
		var decompressed := source.decompress()
		assert(decompressed == OK, "Grove alpha must be readable")
	var soil: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	assert(not scene.has_node("GroveAtmosphere"), "Do not register a duplicate grove atmosphere")
	var atmosphere := Atmosphere.new()
	atmosphere.name = "GroveAtmosphere"
	scene.add_child(atmosphere)
	# Only the six old distant belts join the six new mountain groups.
	# UniqueWoodlandBelt_06/07 are foreground designs and remain native.
	for i in range(6):
		atmosphere.register_grove(scene.get_node("UniqueWoodlandBelt_%02d" % i) as MeshInstance3D)
	var building_guards: Array[Dictionary] = []
	for label: String in ["DistantVillage", "IndependentCastleHill"]:
		var card := scene.get_node(NodePath(label)) as MeshInstance3D
		var points := PackedVector3Array()
		for corner in range(8):
			points.append(card.to_global(card.mesh.get_aabb().get_endpoint(corner)))
		building_guards.append(_projection(camera, points))
	for i in range(6):
		var crop := crops[i]
		# A tall selected design shrinks uniformly; its native aspect never changes.
		var width: float = minf(WIDTHS[i], MAX_HEIGHTS[i] * crop.size.x / crop.size.y)
		var height := width * crop.size.y / crop.size.x
		var region := Rect2(crop.position / dimensions, crop.size / dimensions)
		var grove: MeshInstance3D = scene._art("MountainGrove_%02d" % i, atlas, FEET[i], width,
			anchors[i], -0.08, Color(0.88, 0.92, 0.82), true, region)
		var material := grove.material_override as ShaderMaterial
		# Same established distant-grove response, independent of atlas filename.
		material.set_shader_parameter("foliage_tone", true)
		material.set_shader_parameter("painted_fill", 0.16)
		material.set_shader_parameter("art_exposure", 0.85)
		material.set_shader_parameter("art_contrast", 1.26)
		material.set_shader_parameter("mip_bias", -0.45)
		material.set_shader_parameter("leaf_transmission", 0.10)
		material.set_shader_parameter("wind_strength", clampf(height * 0.026, 0.055, 0.24))
		grove.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		# Reuse the established bowed mesh and alpha-basal support. Roots are
		# pinned against the real triangle surface, crowns retain their native top.
		material.set_shader_parameter("rooted_herb", true)
		material.set_shader_parameter("edge_inset", 0.35)
		HERBS._conform(scene, grove, Rect2i(crop), source, 0.87, soil)
		var arrays := grove.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var points := PackedVector3Array()
		for vertex in vertices:
			# Reproduce the existing face_camera shader transform, not the node AABB.
			var p: Vector3 = grove.global_position + camera.global_basis * vertex
			var local := scene.to_local(p)
			assert(absf(local.x) + MARGIN <= 264.0 and local.z - MARGIN >= -312.0 and local.z + MARGIN <= -235.0, "Grove leaves the far terrain envelope")
			assert(local.x + MARGIN <= -24.0 or local.x - MARGIN >= 166.0, "Grove enters the central castle corridor")
			assert(scene.distance_to_road(Vector2(local.x, local.z)) > scene.road_half_width(local.z) + MARGIN, "Grove enters the road reserve")
			points.append(p)
		var projected := _projection(camera, points)
		var screen: Rect2 = projected.rect
		assert(screen.intersects(camera.get_viewport().get_visible_rect()), "Entire grove is off screen")
		for guard: Dictionary in building_guards:
			assert(not screen.intersects(guard.rect) or float(projected.near) > float(guard.far) + 2.0,
				"Grove would cover a village/castle surface instead of standing behind it")
		grove.set_meta("mountain_grove_index", i)
		grove.set_meta("atlas_crop_pixels", crop)
		grove.set_meta("grounding_mode", "bowed alpha-basal roots on triangle soil; upper crowns preserved")
		grove.set_meta("projected_rect", screen)
		atmosphere.register_grove(grove)
		print("MEADOW_MOUNTAIN_GROVE: %d foot=%s width=%.3f native_height=%.3f crop=%s viewport_rect=%s; visual acceptance pending" % [i, str(FEET[i]), width, height, str(crop), str(screen)])
	assert(atmosphere.materials.size() == 12 and atmosphere.registered.size() == 12)
	scene.set_meta("mountain_groves_built", true)
	print("MEADOW_MOUNTAIN_GROVES: six unique atlas regions / 13824 triangles; native aspect, alpha-basal ground following; visual acceptance pending")

static func _projection(camera: Camera3D, points: PackedVector3Array) -> Dictionary:
	var minimum := Vector2(INF, INF)
	var maximum := Vector2(-INF, -INF)
	var near_depth := INF
	var far_depth := -INF
	for p: Vector3 in points:
		var depth := -camera.to_local(p).z
		assert(depth > camera.near)
		var screen := camera.unproject_position(p)
		minimum = minimum.min(screen)
		maximum = maximum.max(screen)
		near_depth = minf(near_depth, depth)
		far_depth = maxf(far_depth, depth)
	return {"rect": Rect2(minimum, maximum - minimum), "near": near_depth, "far": far_depth}
