extends Node3D

## Asset-only foreground composition lookdev.
## The sunny valley reference is used for art direction, not as a runtime plate.

const TREE_TEXTURE: Texture2D = preload("res://assets/foliage/ai-tree-v1.png")
const LEAN_TREE_TEXTURE: Texture2D = preload("res://assets/foliage/ai-tree-lean-v1.png")
const BROAD_TREE_TEXTURE: Texture2D = preload("res://assets/foliage/ai-tree-broad-v1.png")
const TERRAIN_TEXTURE: Texture2D = preload("res://assets/terrain/grass-cliff-terrace-v1.png")
const ROOT_MOUND_TEXTURE: Texture2D = preload("res://assets/terrain/tree-root-mound-v1.png")
const FOREGROUND_TERRACE_TEXTURE: Texture2D = preload("res://assets/terrain/foreground-grass-terrace-v2.png")
const FOREGROUND_PATH_TEXTURE: Texture2D = preload("res://assets/terrain/foreground-dirt-path-v3.png")
const FOREGROUND_RIVERBANK_TEXTURE: Texture2D = preload("res://assets/terrain/foreground-riverbank-v1.png")
const FAR_HORIZON_TEXTURE: Texture2D = preload("res://assets/backgrounds/far-horizon-mountain-v1.png")
const FAR_VILLAGE_TEXTURE: Texture2D = preload("res://assets/backgrounds/far-village-windmills-v1.png")
const FOREGROUND_FIELD_TEXTURE: Texture2D = preload("res://assets/terrain/foreground-golden-field-v1.png")
const FOREGROUND_ROCK_TEXTURE: Texture2D = preload("res://assets/props/foreground-rock-cluster-v2.png")
const FOREGROUND_SHRUB_TEXTURE: Texture2D = preload("res://assets/foliage/foreground-grass-shrub-v3.png")
const FOREGROUND_WILDFLOWER_TEXTURE: Texture2D = preload("res://assets/foliage/foreground-wildflower-patch-v1.png")
const FOREGROUND_BOULDER_TEXTURE: Texture2D = preload("res://assets/props/foreground-boulder-pair-v1.png")
const FOREGROUND_FENCE_TEXTURE: Texture2D = preload("res://assets/props/foreground-fence-v2.png")
const FOREGROUND_LANTERN_TEXTURE: Texture2D = preload("res://assets/props/foreground-lantern-v1.png")
const MEADOW_FIELD_TEXTURE: Texture2D = preload("res://assets/materials/meadow-field-v3.png")
const DOF_SHADER: Shader = preload("res://shaders/foreground_dof.gdshader")
const ASSET_LAYER_BLUR_SHADER: Shader = preload("res://shaders/asset_layer_blur.gdshader")

# Keep all future character, enemy and boss placement in the same world scale.
# One player-height is deliberately close to the height of the lantern prop;
# bosses can then grow by scale rather than by a separate screen-space rule.
const PLAYER_HEIGHT_WORLD := 1.8
const PLAYER_RADIUS_WORLD := 0.32
const BOSS_HEIGHT_WORLD := 3.6
const BOSS_ARENA_RADIUS_WORLD := 4.2
const ENABLE_COMPATIBILITY_DOF := false

var rng := RandomNumberGenerator.new()
var grass_top: StandardMaterial3D
var meadow: StandardMaterial3D
var stone: StandardMaterial3D
var path_material: StandardMaterial3D
var river_material: StandardMaterial3D
var wood_material: StandardMaterial3D
var roof_material: StandardMaterial3D
var tree_materials: Array[StandardMaterial3D] = []

func _ready() -> void:
	rng.seed = 240519
	_setup_materials()
	_setup_camera()
	_setup_lighting()
	_setup_atmosphere()
	_build_foreground_asset_composition(self)
	if ENABLE_COMPATIBILITY_DOF:
		_setup_compatibility_dof()

func _setup_materials() -> void:
	grass_top = _make_material(Color(0.30, 0.50, 0.15), 0.99)
	meadow = _make_material(Color(0.24, 0.40, 0.13), 0.99)
	stone = _make_material(Color(0.40, 0.34, 0.24), 0.98)
	path_material = _make_material(Color(0.50, 0.33, 0.17), 0.98)
	river_material = _make_material(Color(0.045, 0.27, 0.54), 0.18)
	wood_material = _make_material(Color(0.28, 0.14, 0.065), 0.92)
	roof_material = _make_material(Color(0.18, 0.24, 0.18), 0.96)
	tree_materials = [
		_make_material(Color(0.08, 0.22, 0.07), 0.98),
		_make_material(Color(0.12, 0.31, 0.09), 0.98),
		_make_material(Color(0.20, 0.39, 0.11), 0.98),
		_make_material(Color(0.30, 0.46, 0.14), 0.98),
	]

func _setup_camera() -> void:
	var camera := $Camera3D
	# A higher 3/4 perspective exposes the top surfaces of the terraces while
	# keeping perspective scale for near/far characters and bosses.
	camera.position = Vector3(11.5, 19.0, 24.5)
	camera.look_at(Vector3(0.0, 0.5, -5.0), Vector3.UP)
	camera.fov = 52.0
	camera.far = 120.0

func fifty_two() -> float:
	return 52.0

func _setup_lighting() -> void:
	var key_light := $KeyLight
	key_light.rotation_degrees = Vector3(-54.0, -28.0, 0.0)
	key_light.light_color = Color(1.0, 0.78, 0.50)
	key_light.light_energy = 1.70
	key_light.shadow_enabled = true
	key_light.directional_shadow_max_distance = 24.0

	var fill_light := DirectionalLight3D.new()
	fill_light.name = "CoolSkyFill"
	fill_light.rotation_degrees = Vector3(-24.0, 142.0, 0.0)
	fill_light.light_color = Color(0.42, 0.64, 0.90)
	fill_light.light_energy = 0.52
	fill_light.shadow_enabled = false
	add_child(fill_light)

func _setup_atmosphere() -> void:
	var environment: Environment = $WorldEnvironment.environment
	var sky := Sky.new()
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color(0.24, 0.50, 0.78)
	sky_material.sky_horizon_color = Color(0.78, 0.88, 0.94)
	sky_material.ground_bottom_color = Color(0.44, 0.56, 0.45)
	sky_material.ground_horizon_color = Color(0.73, 0.82, 0.78)
	sky_material.sun_angle_max = 18.0
	sky_material.sun_curve = 0.08
	sky_material.sun_energy_multiplier = 0.65
	sky.sky_material = sky_material
	environment.background_mode = Environment.BG_SKY
	environment.sky = sky
	environment.fog_enabled = true
	environment.fog_light_color = Color(0.58, 0.72, 0.80)
	environment.fog_light_energy = 0.34
	environment.fog_density = 0.0045
	environment.fog_sky_affect = 0.20

func _setup_compatibility_dof() -> void:
	# CanvasItem shaders cannot access the depth buffer in the Compatibility
	# renderer. Use a spatial full-screen quad instead, so the Web build can
	# read both screen color and 3D depth without switching renderers.
	var dof_quad := MeshInstance3D.new()
	dof_quad.name = "ForegroundDepthOfField"
	var quad_mesh := QuadMesh.new()
	quad_mesh.size = Vector2(2.0, 2.0)
	dof_quad.mesh = quad_mesh
	dof_quad.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	dof_quad.render_priority = 127

	var dof_material := ShaderMaterial.new()
	dof_material.shader = DOF_SHADER
	var camera := $Camera3D
	dof_material.set_shader_parameter("focus_depth", 32.0)
	dof_material.set_shader_parameter("focus_range", 7.0)
	dof_material.set_shader_parameter("max_blur", 2.0)
	dof_material.set_shader_parameter("camera_near", camera.near)
	dof_material.set_shader_parameter("camera_far", camera.far)
	dof_material.set_shader_parameter("viewport_size", get_viewport().get_visible_rect().size)
	dof_quad.material_override = dof_material
	add_child(dof_quad)

func _build_landscape() -> void:
	var world := _group("ValleyFloor")
	var ground_material := _make_material(Color(0.31, 0.48, 0.16), 1.0)
	_add_plane(world, "ValleyGround", Vector2(46.0, 62.0), Vector3(0.0, -0.48, -8.0), ground_material)

	var patch_colors := [
		Color(0.36, 0.54, 0.18),
		Color(0.43, 0.59, 0.19),
		Color(0.28, 0.44, 0.14),
		Color(0.52, 0.60, 0.20),
	]
	for index in range(28):
		var patch_position := Vector3(
			rng.randf_range(-15.0, 13.0),
			-0.38,
			rng.randf_range(-22.0, 13.0)
		)
		if patch_position.x > 5.0 and patch_position.z < 5.0:
			continue
		_add_ground_patch(world, "MeadowPatch_%02d" % index, patch_position, Vector2(rng.randf_range(1.2, 3.8), rng.randf_range(0.5, 1.8)), patch_colors[rng.randi_range(0, patch_colors.size() - 1)])

func _build_terraces() -> void:
	var terrain := _group("TerracedLandscape")
	var wall_material := _make_material(Color(0.49, 0.38, 0.25), 0.98)

	_add_terrace(
		terrain,
		"ForegroundTerrace",
		[Vector2(-17.0, 15.0), Vector2(3.8, 15.0), Vector2(7.2, 9.6), Vector2(5.0, 3.6), Vector2(-6.2, 3.0), Vector2(-15.6, 7.2)],
		0.46,
		-0.70,
		grass_top,
		wall_material
	)
	_add_terrace(
		terrain,
		"LeftMiddleTerrace",
		[Vector2(-17.0, 1.2), Vector2(-10.2, -0.2), Vector2(-9.0, -5.5), Vector2(-16.0, -5.2)],
		0.92,
		-0.20,
		grass_top,
		wall_material
	)
	_add_terrace(
		terrain,
		"LeftFarTerrace",
		[Vector2(-15.0, -7.0), Vector2(-8.2, -7.6), Vector2(-6.0, -12.4), Vector2(-13.5, -13.2)],
		0.60,
		-0.05,
		grass_top,
		wall_material
	)
	_add_terrace(
		terrain,
		"RightBankTerrace",
		[Vector2(10.9, 6.8), Vector2(16.0, 8.5), Vector2(16.2, 2.0), Vector2(13.5, -3.7), Vector2(10.8, -1.8)],
		0.34,
		-0.34,
		grass_top,
		wall_material
	)

	_add_stone_line(terrain, "ForegroundStoneEdge", -15.2, 4.0, 7.8, -0.12, 14)
	_add_stone_line(terrain, "LeftStoneEdge", -15.6, -9.3, -5.0, 0.34, 6)
	_add_stone_line(terrain, "FarStoneEdge", -13.2, -6.6, -12.2, 0.12, 6)

func _build_path() -> void:
	var path := _group("ValleyPath")
	var path_points := [
		Vector3(-1.3, 0.54, 14.2),
		Vector3(-0.8, 0.53, 9.0),
		Vector3(0.25, 0.16, 4.1),
		Vector3(-0.15, -0.22, -0.8),
		Vector3(0.30, -0.20, -6.4),
		Vector3(0.80, -0.16, -12.0),
		Vector3(1.85, -0.10, -18.2),
		Vector3(2.20, -0.02, -23.8),
	]
	var path_widths := [5.0, 4.1, 3.25, 2.55, 2.15, 1.65, 1.20, 0.72]
	_add_ribbon(path, "MainDirtPath", path_points, path_widths, path_material)

	var path_stones := _group("PathStones")
	for index in range(28):
		var t := rng.randf_range(0.05, 0.92)
		var path_index := int(t * float(path_points.size() - 1))
		var start_point: Vector3 = path_points[path_index]
		var next_point: Vector3 = path_points[min(path_index + 1, path_points.size() - 1)]
		var blend := fmod(t * float(path_points.size() - 1), 1.0)
		var position := start_point.lerp(next_point, blend)
		position.x += rng.randf_range(-1.7, 1.7) * (1.0 - t * 0.45)
		position.y += 0.10
		position.z += rng.randf_range(-0.25, 0.25)
		_add_rock(path_stones, "PathRock_%02d" % index, position, rng.randf_range(0.08, 0.24), Color(0.42, 0.34, 0.23))

func _build_river_and_bridge() -> void:
	var water := _group("RiverSystem")
	var river_points := [
		Vector3(10.8, -0.10, 14.0),
		Vector3(10.4, -0.08, 9.0),
		Vector3(9.2, -0.02, 4.0),
		Vector3(9.55, 0.02, -1.8),
		Vector3(10.8, -0.04, -7.0),
		Vector3(9.1, -0.04, -13.0),
		Vector3(10.0, 0.02, -19.5),
		Vector3(8.3, 0.04, -26.5),
	]
	var river_widths := [6.0, 5.6, 5.2, 4.8, 4.3, 3.8, 3.2, 2.6]
	_add_ribbon(water, "River", river_points, river_widths, river_material)

	for index in range(24):
		var point_index := index % (river_points.size() - 1)
		var position: Vector3 = river_points[point_index].lerp(river_points[point_index + 1], rng.randf_range(0.1, 0.9))
		position.y += 0.045
		position.x += rng.randf_range(-1.25, 1.25)
		var ripple := _add_box(water, "WaterRipple_%02d" % index, Vector3(rng.randf_range(0.25, 0.90), 0.018, 0.045), position, _make_material(Color(0.70, 0.88, 0.88), 0.18))
		ripple.rotation_degrees.y = rng.randf_range(-18.0, 18.0)

	_build_bridge(water)
	_build_river_bank_rocks(water, river_points)

func _build_bridge(parent: Node3D) -> void:
	var bridge := _group("WoodenBridge")
	var bridge_z := -1.8
	for index in range(9):
		var x := 6.7 + float(index) * 0.78
		_add_box(bridge, "BridgePlank_%02d" % index, Vector3(0.70, 0.20, 1.35), Vector3(x, 0.52, bridge_z), wood_material, Vector3(0.0, rng.randf_range(-0.035, 0.035), rng.randf_range(-0.04, 0.04)))

	for side in [-1.0, 1.0]:
		for index in range(4):
			var x := 7.0 + float(index) * 2.05
			_add_box(bridge, "BridgePost_%s_%02d" % [str(side), index], Vector3(0.16, 1.18, 0.16), Vector3(x, 1.08, bridge_z + side * 0.56), wood_material)
		_add_box(bridge, "BridgeRail_%s" % str(side), Vector3(6.5, 0.14, 0.14), Vector3(9.8, 1.45, bridge_z + side * 0.56), wood_material)

func _build_river_bank_rocks(parent: Node3D, river_points: Array) -> void:
	for point_index in range(river_points.size() - 1):
		var start_point: Vector3 = river_points[point_index]
		var end_point: Vector3 = river_points[point_index + 1]
		for side in [-1.0, 1.0]:
			var position := start_point.lerp(end_point, 0.50)
			position.x += side * rng.randf_range(1.8, 2.8)
			position.y = 0.12
			position.z += rng.randf_range(-0.65, 0.65)
			_add_rock(parent, "BankRock_%02d_%s" % [point_index, str(side)], position, rng.randf_range(0.18, 0.42), Color(0.43, 0.38, 0.27))

func _build_mountains() -> void:
	var mountains := _group("DistantMountains")
	var mountain_colors := [
		_make_material(Color(0.35, 0.49, 0.51), 1.0),
		_make_material(Color(0.43, 0.56, 0.56), 1.0),
		_make_material(Color(0.55, 0.64, 0.60), 1.0),
	]
	var mountain_specs := [
		[-15.0, 8.0, 10.0, -39.0, 0],
		[-8.0, 7.0, 8.5, -37.0, 1],
		[-1.0, 9.0, 12.0, -41.0, 0],
		[7.0, 6.8, 8.0, -38.0, 2],
		[14.0, 8.5, 11.0, -42.0, 1],
	]
	for spec in mountain_specs:
		_add_cone(mountains, "Mountain_%s" % str(spec[0]), Vector3(spec[0], spec[2] * 0.48 - 0.45, spec[3]), spec[1], spec[2], mountain_colors[spec[4]], false)

	var foothills := _make_material(Color(0.32, 0.48, 0.38), 1.0)
	for index in range(9):
		var hill := _add_cone(mountains, "FarFoothill_%02d" % index, Vector3(-18.0 + float(index) * 4.5, 1.7, -31.0 - float(index % 2) * 2.0), 5.5, 3.4 + float(index % 3) * 0.8, foothills, false)
		hill.scale.x = 1.35

func _build_settlement() -> void:
	var settlement := _group("DistantSettlement")
	var castle_body := _make_material(Color(0.70, 0.61, 0.45), 0.99)
	var castle_shadow := _make_material(Color(0.42, 0.38, 0.31), 1.0)
	var castle_position := Vector3(4.4, 0.0, -24.0)

	_add_box(settlement, "CastleKeep", Vector3(4.8, 3.2, 2.8), castle_position + Vector3(0.0, 1.6, 0.0), castle_body)
	for side in [-1.0, 1.0]:
		for depth in [-1.0, 1.0]:
			var tower_position := castle_position + Vector3(side * 2.45, 2.1, depth * 0.95)
			_add_cylinder(settlement, "CastleTower_%s_%s" % [str(side), str(depth)], tower_position, 0.58, 4.2, castle_body, 8)
			_add_cone(settlement, "CastleRoof_%s_%s" % [str(side), str(depth)], tower_position + Vector3(0.0, 2.35, 0.0), 0.78, 1.25, castle_shadow, false)
	_add_cone(settlement, "CastleSpire", castle_position + Vector3(0.0, 4.1, 0.0), 0.85, 2.0, castle_shadow, false)
	_add_box(settlement, "CastleWall", Vector3(11.0, 1.0, 1.0), castle_position + Vector3(0.0, 0.5, 1.7), castle_body)

	var village := _group("FarVillage")
	for index in range(7):
		var position := Vector3(-10.8 + float(index % 4) * 2.0, 0.0, -18.4 - float(index / 4) * 2.2)
		_add_house(village, "House_%02d" % index, position, 0.85 + float(index % 3) * 0.15)
	_add_windmill(village, Vector3(-13.0, 0.0, -16.6))

func _add_house(parent: Node3D, house_name: String, position: Vector3, size: float) -> void:
	var house_material := _make_material(Color(0.60, 0.47, 0.28), 0.99)
	_add_box(parent, house_name + "_Body", Vector3(1.65, 1.25, 1.45) * size, position + Vector3(0.0, 0.62 * size, 0.0), house_material)
	_add_cone(parent, house_name + "_Roof", position + Vector3(0.0, 1.45 * size, 0.0), 1.25 * size, 0.95 * size, roof_material, false, 4)

func _add_windmill(parent: Node3D, position: Vector3) -> void:
	var mill_material := _make_material(Color(0.52, 0.42, 0.27), 0.99)
	_add_cylinder(parent, "WindmillTower", position + Vector3(0.0, 1.7, 0.0), 0.56, 3.4, mill_material, 8)
	var hub := Node3D.new()
	hub.name = "WindmillBlades"
	hub.position = position + Vector3(0.0, 2.25, -0.52)
	parent.add_child(hub)
	for index in range(4):
		var blade := _add_box(hub, "Blade_%02d" % index, Vector3(0.12, 1.65, 0.08), Vector3(0.0, 0.72, 0.0), mill_material)
		blade.rotation_degrees.z = float(index) * 90.0

func _build_foliage() -> void:
	var foliage := _group("ValleyFoliage")

	var tree_specs := [
		[12.2, 0.0, 10.0, 2.0, 1],
		[-11.5, 0.0, -1.4, 2.2, 1],
		[-5.8, 0.0, -3.0, 1.4, 2],
		[3.1, 0.0, -5.0, 1.6, 2],
		[5.6, 0.0, -11.0, 1.2, 3],
		[-4.0, 0.0, -14.0, 1.4, 2],
		[8.0, 0.0, -15.5, 1.25, 2],
		[-7.8, 0.0, -20.0, 1.0, 3],
		[8.8, 0.0, -21.5, 1.1, 3],
	]
	for index in range(tree_specs.size()):
		var spec = tree_specs[index]
		_add_tree(foliage, "HeroTree_%02d" % index, Vector3(spec[0], spec[1], spec[2]), spec[3], spec[4])

	for index in range(34):
		var z := rng.randf_range(-25.0, 7.0)
		var x := rng.randf_range(-14.0, 12.0)
		if abs(x - 0.5) < 2.3 and z > -15.0:
			continue
		if x > 6.8 and z > -4.0:
			continue
		var depth_factor: float = clampf((z + 25.0) / 32.0, 0.0, 1.0)
		_add_tree(foliage, "Tree_%02d" % index, Vector3(x, -0.10, z), rng.randf_range(0.45, 1.10) * (0.70 + depth_factor * 0.45), 1 + index % 3)

func _build_foreground_asset_composition(parent: Node3D) -> void:
	var horizon := _group("DistantHorizonAssets")
	_build_asset_sprite(horizon, "FarMountainCastleHorizon", FAR_HORIZON_TEXTURE, Vector3(-6.0, 6.6, -19.0), 0.0330, Color.WHITE, 0.16, 1.4)
	_build_asset_sprite(horizon, "FarVillageWindmills", FAR_VILLAGE_TEXTURE, Vector3(-10.0, 3.8, -13.5), 0.0140, Color.WHITE, 0.16, 1.0)

	var base := _group("AssetCompositionPlain")
	var plain_material := _make_material(Color(0.40, 0.52, 0.28), 1.0, MEADOW_FIELD_TEXTURE)
	# Extend beyond the camera frustum so the ground never exposes its rectangular
	# silhouette against the sky at the far left/right corners.
	_add_plane(base, "PlainGround", Vector2(500.0, 500.0), Vector3(0.0, -0.62, -150.0), plain_material)

	var terrain := _group("ForegroundTerrainAssets")
	_build_asset_sprite(terrain, "BackGrassTerrace", FOREGROUND_TERRACE_TEXTURE, Vector3(-4.8, 1.90, -7.3), 0.0090, Color.WHITE, 0.16, 0.65)
	_build_asset_sprite(terrain, "RightMiddleTerrace", TERRAIN_TEXTURE, Vector3(7.4, 0.90, -5.4), 0.0074, Color.WHITE, 0.16, 0.40)
	_build_ground_asset_sprite(terrain, "MidgroundGoldenField", FOREGROUND_FIELD_TEXTURE, Vector3(-5.0, -0.50, -1.2), 0.0092, Color(0.96, 0.94, 0.82, 1.0), 0.34)
	_build_ground_asset_sprite(terrain, "RightRiverBankAsset", FOREGROUND_RIVERBANK_TEXTURE, Vector3(10.5, -0.50, 2.5), 0.0145)
	_build_ground_asset_sprite(terrain, "MainDirtPathAsset", FOREGROUND_PATH_TEXTURE, Vector3(0.0, -0.53, 3.5), 0.0140)

	var foliage := _group("ForegroundFoliageAssets")
	_build_asset_sprite(foliage, "HeroTreeAsset", TREE_TEXTURE, Vector3(-11.8, 5.00, 10.5), 0.0100, Color.WHITE, 0.16, 1.05)
	_build_asset_sprite(foliage, "LeanTreeAsset", LEAN_TREE_TEXTURE, Vector3(-1.8, 3.45, -2.0), 0.0062)
	_build_asset_sprite(foliage, "BroadTreeAsset", BROAD_TREE_TEXTURE, Vector3(10.4, 3.80, 6.8), 0.0080, Color.WHITE, 0.16, 0.85)
	_build_asset_sprite(foliage, "HeroTreeRootMound", ROOT_MOUND_TEXTURE, Vector3(-11.8, -0.05, 10.85), 0.0058, Color.WHITE, 0.16, 0.80)
	_build_asset_sprite(foliage, "LeftGrassShrub", FOREGROUND_SHRUB_TEXTURE, Vector3(-5.8, 0.50, 7.6), 0.0055, Color.WHITE, 0.16, 0.65)
	_build_asset_sprite(foliage, "RightWildflowerPatch", FOREGROUND_WILDFLOWER_TEXTURE, Vector3(5.8, 0.40, 7.0), 0.0052, Color.WHITE, 0.16, 0.60)

	var props := _group("ForegroundPropAssets")
	_build_asset_sprite(props, "LeftRockCluster", FOREGROUND_ROCK_TEXTURE, Vector3(-2.4, 0.35, 6.6), 0.0044, Color.WHITE, 0.16, 0.45)
	_build_asset_sprite(props, "RightBoulderPair", FOREGROUND_BOULDER_TEXTURE, Vector3(7.8, 0.22, 6.0), 0.0038, Color.WHITE, 0.16, 0.40)
	_build_asset_sprite(props, "RusticFence", FOREGROUND_FENCE_TEXTURE, Vector3(-8.7, 0.72, 7.0), 0.0053)
	_build_asset_sprite(props, "PathLantern", FOREGROUND_LANTERN_TEXTURE, Vector3(3.6, 1.45, 6.2), 0.0040)

	_build_gameplay_layout(parent)

func _build_gameplay_layout(parent: Node3D) -> void:
	# Invisible anchors keep the central path and meadow available for future
	# auto-battle movement. The right river bank remains a hard visual boundary,
	# while the open center-right meadow is reserved for a boss encounter.
	var gameplay := Node3D.new()
	gameplay.name = "GameplayLayout"
	gameplay.set_meta("player_height_world", PLAYER_HEIGHT_WORLD)
	gameplay.set_meta("player_radius_world", PLAYER_RADIUS_WORLD)
	gameplay.set_meta("boss_height_world", BOSS_HEIGHT_WORLD)
	gameplay.set_meta("boss_arena_radius_world", BOSS_ARENA_RADIUS_WORLD)
	parent.add_child(gameplay)

	_add_gameplay_marker(gameplay, "PlayerSpawn", Vector3(0.0, -0.48, 4.4))
	_add_gameplay_marker(gameplay, "PatrolWaypointA", Vector3(-2.4, -0.48, 2.1))
	_add_gameplay_marker(gameplay, "PatrolWaypointB", Vector3(-0.8, -0.48, -0.4))
	_add_gameplay_marker(gameplay, "PatrolWaypointC", Vector3(2.5, -0.48, 0.7))
	_add_gameplay_marker(gameplay, "PatrolWaypointD", Vector3(3.6, -0.48, 3.2))
	_add_gameplay_marker(gameplay, "BossArenaCenter", Vector3(2.6, -0.46, -2.0))
	_add_gameplay_marker(gameplay, "BossArenaNorth", Vector3(2.6, -0.46, -6.2))
	_add_gameplay_marker(gameplay, "BossArenaSouth", Vector3(2.6, -0.46, 2.2))
	_add_gameplay_marker(gameplay, "BossArenaWest", Vector3(-1.6, -0.46, -2.0))
	_add_gameplay_marker(gameplay, "BossArenaEast", Vector3(6.8, -0.46, -2.0))
	_add_gameplay_marker(gameplay, "RiverBlockedBoundary", Vector3(8.4, -0.46, 0.0))

func _add_gameplay_marker(parent: Node3D, marker_name: String, position: Vector3) -> void:
	var marker := Marker3D.new()
	marker.name = marker_name
	marker.position = position
	parent.add_child(marker)

func _build_asset_sprite(parent: Node3D, sprite_name: String, texture: Texture2D, position: Vector3, pixel_size: float, modulate: Color = Color.WHITE, alpha_scissor_threshold: float = 0.16, layer_blur_radius: float = 0.0) -> void:
	var sprite := Sprite3D.new()
	sprite.name = sprite_name
	sprite.texture = texture
	sprite.position = position
	sprite.pixel_size = pixel_size
	sprite.modulate = modulate
	sprite.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	# Keep cutout assets in the opaque pass so the compatibility post-process
	# can see them in the screen texture instead of painting over them.
	sprite.alpha_cut = SpriteBase3D.ALPHA_CUT_DISCARD
	sprite.alpha_scissor_threshold = alpha_scissor_threshold
	sprite.shaded = false
	sprite.double_sided = true
	sprite.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	if layer_blur_radius > 0.001:
		var blur_material := ShaderMaterial.new()
		blur_material.shader = ASSET_LAYER_BLUR_SHADER
		blur_material.set_shader_parameter("sprite_texture", texture)
		blur_material.set_shader_parameter("texture_size", Vector2(texture.get_size()))
		blur_material.set_shader_parameter("blur_radius", layer_blur_radius)
		sprite.material_override = blur_material
	parent.add_child(sprite)

func _build_ground_asset_sprite(parent: Node3D, sprite_name: String, texture: Texture2D, position: Vector3, pixel_size: float, modulate: Color = Color.WHITE, alpha_scissor_threshold: float = 0.16, layer_blur_radius: float = 0.0) -> void:
	_build_asset_sprite(parent, sprite_name, texture, position, pixel_size, modulate, alpha_scissor_threshold, layer_blur_radius)
	var sprite := parent.get_node(sprite_name) as Sprite3D
	sprite.billboard = BaseMaterial3D.BILLBOARD_DISABLED
	# The source image is authored in camera-facing coordinates. Rotate it onto
	# the meadow and keep its near end toward the camera.
	sprite.rotation_degrees.x = -90.0

func _add_tree(parent: Node3D, tree_name: String, position: Vector3, size: float, palette_index: int) -> void:
	var tree := Node3D.new()
	tree.name = tree_name
	tree.position = position
	parent.add_child(tree)

	var trunk_material := _make_material(Color(0.25, 0.15, 0.075), 1.0)
	_add_cylinder(tree, "Trunk", Vector3(0.0, 0.72 * size, 0.0), 0.16 * size, 1.45 * size, trunk_material, 7)
	for index in range(4):
		var foliage_mesh := SphereMesh.new()
		foliage_mesh.radius = (0.70 - float(index) * 0.075) * size
		foliage_mesh.height = (0.85 - float(index) * 0.07) * size
		foliage_mesh.radial_segments = 8
		foliage_mesh.rings = 4
		var foliage_piece := MeshInstance3D.new()
		foliage_piece.name = "Canopy_%02d" % index
		foliage_piece.mesh = foliage_mesh
		foliage_piece.position = Vector3((float(index % 2) - 0.5) * 0.28 * size, (1.28 + float(index) * 0.42) * size, float(index % 2) * 0.18 * size)
		foliage_piece.scale = Vector3(1.0, 0.76, 0.82)
		foliage_piece.material_override = tree_materials[(palette_index + index) % tree_materials.size()]
		foliage_piece.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		tree.add_child(foliage_piece)

func _build_clouds() -> void:
	var clouds := _group("SkyClouds")
	var cloud_material := _make_material(Color(0.96, 0.94, 0.86, 0.52), 1.0)
	cloud_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	cloud_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	cloud_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	var cloud_specs := [
		[-16.0, 13.0, -34.0, 4.3, 0.75],
		[-7.0, 15.0, -39.0, 5.8, 0.95],
		[3.5, 13.8, -36.0, 4.8, 0.70],
		[14.5, 16.0, -40.0, 5.5, 0.85],
		[20.0, 11.5, -30.0, 3.6, 0.60],
	]
	for index in range(cloud_specs.size()):
		var spec = cloud_specs[index]
		var cloud := _add_sphere(clouds, "Cloud_%02d" % index, Vector3(spec[0], spec[1], spec[2]), spec[3], cloud_material, false)
		cloud.scale = Vector3(1.8, 0.30, 0.55 + spec[4] * 0.20)

func _group(group_name: String) -> Node3D:
	var node := Node3D.new()
	node.name = group_name
	add_child(node)
	return node

func _make_material(color: Color, roughness: float, texture: Texture2D = null) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	material.metallic = 0.0
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	if texture != null:
		material.albedo_texture = texture
	return material

func _add_plane(parent: Node3D, node_name: String, size: Vector2, position: Vector3, material: Material) -> MeshInstance3D:
	var mesh := PlaneMesh.new()
	mesh.size = size
	return _add_mesh_instance(parent, node_name, mesh, material, position, false)

func _add_box(parent: Node3D, node_name: String, size: Vector3, position: Vector3, material: Material, rotation: Vector3 = Vector3.ZERO, cast_shadow: bool = true) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	var instance := _add_mesh_instance(parent, node_name, mesh, material, position, cast_shadow)
	instance.rotation = rotation
	return instance

func _add_cylinder(parent: Node3D, node_name: String, position: Vector3, radius: float, height: float, material: Material, segments: int = 8, cast_shadow: bool = true) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius * 0.86
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = segments
	mesh.rings = 2
	return _add_mesh_instance(parent, node_name, mesh, material, position, cast_shadow)

func _add_cone(parent: Node3D, node_name: String, position: Vector3, radius: float, height: float, material: Material, cast_shadow: bool = true, segments: int = 7) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.0
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = segments
	mesh.rings = 1
	return _add_mesh_instance(parent, node_name, mesh, material, position, cast_shadow)

func _add_sphere(parent: Node3D, node_name: String, position: Vector3, radius: float, material: Material, cast_shadow: bool = true) -> MeshInstance3D:
	var mesh := SphereMesh.new()
	mesh.radius = radius
	mesh.height = radius * 1.45
	mesh.radial_segments = 10
	mesh.rings = 5
	return _add_mesh_instance(parent, node_name, mesh, material, position, cast_shadow)

func _add_rock(parent: Node3D, node_name: String, position: Vector3, radius: float, color: Color) -> MeshInstance3D:
	var material := _make_material(color, 0.99)
	var rock := _add_sphere(parent, node_name, position, radius, material)
	rock.scale = Vector3(1.0, rng.randf_range(0.55, 0.90), rng.randf_range(0.75, 1.20))
	rock.rotation_degrees = Vector3(rng.randf_range(-15.0, 15.0), rng.randf_range(0.0, 360.0), rng.randf_range(-15.0, 15.0))
	return rock

func _add_ground_patch(parent: Node3D, node_name: String, position: Vector3, size: Vector2, color: Color) -> void:
	var patch := _add_sphere(parent, node_name, position, 1.0, _make_material(color, 1.0), false)
	patch.scale = Vector3(size.x, 0.09, size.y)

func _add_mesh_instance(parent: Node3D, node_name: String, mesh: Mesh, material: Material, position: Vector3, cast_shadow: bool) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = position
	instance.material_override = material
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if cast_shadow else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	parent.add_child(instance)
	return instance

func _add_terrace(parent: Node3D, node_name: String, points: Array, top_y: float, bottom_y: float, top_material: Material, side_material: Material) -> void:
	_add_polygon_surface(parent, node_name + "_Top", points, top_y + 0.01, top_material)
	_add_side_walls(parent, node_name + "_Walls", points, top_y, bottom_y, side_material)

func _add_polygon_surface(parent: Node3D, node_name: String, points: Array, height: float, material: Material) -> void:
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	for index in range(1, points.size() - 1):
		var a := Vector3(points[0].x, height, points[0].y)
		var b := Vector3(points[index].x, height, points[index].y)
		var c := Vector3(points[index + 1].x, height, points[index + 1].y)
		_append_triangle(vertices, normals, uvs, a, b, c, Vector3.UP, Vector2(a.x * 0.045, a.z * 0.045), Vector2(b.x * 0.045, b.z * 0.045), Vector2(c.x * 0.045, c.z * 0.045))
	var mesh := _mesh_from_arrays(vertices, normals, uvs)
	_add_mesh_instance(parent, node_name, mesh, material, Vector3.ZERO, false)

func _add_side_walls(parent: Node3D, node_name: String, points: Array, top_y: float, bottom_y: float, material: Material) -> void:
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	for index in range(points.size()):
		var current: Vector2 = points[index]
		var next: Vector2 = points[(index + 1) % points.size()]
		var edge := next - current
		var normal := Vector3(edge.y, 0.0, -edge.x).normalized()
		var a := Vector3(current.x, top_y, current.y)
		var b := Vector3(next.x, top_y, next.y)
		var c := Vector3(next.x, bottom_y, next.y)
		var d := Vector3(current.x, bottom_y, current.y)
		var u_start := float(index) * 0.35
		_append_triangle(vertices, normals, uvs, a, b, c, normal, Vector2(u_start, 0.0), Vector2(u_start + 0.35, 0.0), Vector2(u_start + 0.35, 1.0))
		_append_triangle(vertices, normals, uvs, a, c, d, normal, Vector2(u_start, 0.0), Vector2(u_start + 0.35, 1.0), Vector2(u_start, 1.0))
	var mesh := _mesh_from_arrays(vertices, normals, uvs)
	_add_mesh_instance(parent, node_name, mesh, material, Vector3.ZERO, true)

func _add_stone_line(parent: Node3D, node_name: String, start_x: float, end_x: float, z: float, y: float, count: int) -> void:
	for index in range(count):
		var amount: float = float(index) / maxf(float(count - 1), 1.0)
		var x: float = lerpf(start_x, end_x, amount) + rng.randf_range(-0.16, 0.16)
		var block_size := Vector3(rng.randf_range(0.85, 1.55), rng.randf_range(0.35, 0.72), rng.randf_range(0.30, 0.52))
		_add_box(parent, "%s_%02d" % [node_name, index], block_size, Vector3(x, y, z + rng.randf_range(-0.10, 0.10)), stone, Vector3(rng.randf_range(-0.06, 0.06), rng.randf_range(-0.08, 0.08), rng.randf_range(-0.07, 0.07)))

func _add_ribbon(parent: Node3D, node_name: String, points: Array, widths: Array, material: Material) -> void:
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	for index in range(points.size() - 1):
		var current: Vector3 = points[index]
		var next: Vector3 = points[index + 1]
		var tangent := Vector2(next.x - current.x, next.z - current.z).normalized()
		var side := Vector2(-tangent.y, tangent.x)
		var left_a := Vector3(current.x + side.x * widths[index] * 0.5, current.y + 0.025, current.z + side.y * widths[index] * 0.5)
		var right_a := Vector3(current.x - side.x * widths[index] * 0.5, current.y + 0.025, current.z - side.y * widths[index] * 0.5)
		var left_b := Vector3(next.x + side.x * widths[index + 1] * 0.5, next.y + 0.025, next.z + side.y * widths[index + 1] * 0.5)
		var right_b := Vector3(next.x - side.x * widths[index + 1] * 0.5, next.y + 0.025, next.z - side.y * widths[index + 1] * 0.5)
		_append_triangle(vertices, normals, uvs, left_a, right_a, left_b, Vector3.UP, Vector2(0.0, float(index)), Vector2(1.0, float(index)), Vector2(0.0, float(index + 1)))
		_append_triangle(vertices, normals, uvs, right_a, right_b, left_b, Vector3.UP, Vector2(1.0, float(index)), Vector2(1.0, float(index + 1)), Vector2(0.0, float(index + 1)))
	var mesh := _mesh_from_arrays(vertices, normals, uvs)
	_add_mesh_instance(parent, node_name, mesh, material, Vector3.ZERO, false)

func _append_triangle(vertices: PackedVector3Array, normals: PackedVector3Array, uvs: PackedVector2Array, a: Vector3, b: Vector3, c: Vector3, normal: Vector3, uv_a: Vector2, uv_b: Vector2, uv_c: Vector2) -> void:
	vertices.append(a)
	vertices.append(b)
	vertices.append(c)
	normals.append(normal)
	normals.append(normal)
	normals.append(normal)
	uvs.append(uv_a)
	uvs.append(uv_b)
	uvs.append(uv_c)

func _mesh_from_arrays(vertices: PackedVector3Array, normals: PackedVector3Array, uvs: PackedVector2Array) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
