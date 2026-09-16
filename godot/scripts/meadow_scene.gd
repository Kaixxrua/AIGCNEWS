extends Node3D
## One continuous world: terrain, collisions and the scale test use the same metres.
## Art cards are anchored by a root UV, never by the centre of a padded PNG.

const GROUND_SHADER = preload("res://shaders/meadow_ground.gdshader")
const GROUND_ATMOSPHERE = preload("res://scripts/meadow_ground_atmosphere.gd")
const CUTOUT_SHADER = preload("res://shaders/meadow_cutout.gdshader")
const DISTANT_CUTOUT_SHADER = preload("res://shaders/meadow_distant_cutout.gdshader")
const MOUNTAIN_RELIEF = preload("res://scripts/meadow_mountain_relief.gd")
const MOUNTAIN_ATMOSPHERE = preload("res://scripts/meadow_mountain_atmosphere.gd")
const MOUNTAIN_LANDFORM = preload("res://scripts/meadow_mountain_landform.gd")
const MOUNTAIN_GROVES = preload("res://scripts/meadow_mountain_groves.gd")
const LEDGE_BREAKUP = preload("res://scripts/meadow_ledge_breakup.gd")
const ROCK_OCCLUSION = preload("res://scripts/meadow_rock_occlusion.gd")
const FOCUS_SHADER = preload("res://shaders/meadow_focus.gdshader")
const WATER_SHADER = preload("res://shaders/meadow_water.gdshader")
const SKY_SHADER = preload("res://shaders/meadow_sky.gdshader")
const DETAIL_BUILDER = preload("res://scripts/meadow_detail_builder.gd")
const MIDDLE_BRUSH = preload("res://scripts/meadow_middle_brush.gd")
const CANOPY_PROFILES = preload("res://scripts/meadow_canopy_profiles.gd")
const HERB_MODULES = preload("res://scripts/meadow_herb_modules.gd")
const SCRUB_MODULES = preload("res://scripts/meadow_scrub_modules.gd")
const RIVERBANK_BUILDER = preload("res://scripts/meadow_riverbank_builder.gd")
const FOOTHILL_BUILDER = preload("res://scripts/meadow_foothill_builder.gd")
const BRIDGE_BUILDER = preload("res://scripts/meadow_bridge_builder.gd")
const FENCE_BUILDER = preload("res://scripts/meadow_fence_builder.gd")
const CITY_BUILDER = preload("res://scripts/meadow_city_builder.gd")
const VILLAGE_BUILDER = preload("res://scripts/meadow_village_builder.gd")
const SETTLEMENT_LIGHTS = preload("res://scripts/meadow_settlement_lights.gd")
const ROAD_LIGHTS = preload("res://scripts/meadow_road_lights.gd")
const WEATHER_CONTROLLER = preload("res://scripts/meadow_weather.gd")
const WILDLIFE_CONTROLLER = preload("res://scripts/meadow_wildlife.gd")
const STATIC_CACHE = preload("res://scripts/meadow_static_cache.gd")
const MEADOW = preload("res://assets/materials/meadow-sward-v60.png")
const ROCK = preload("res://assets/materials/ochre-trail-v39.png")
const WEATHERED_ROCK = preload("res://assets/materials/limestone-fractured-v61.png")
const BANK_LIMESTONE = preload("res://assets/materials/riverbank-limestone-v68.png")
const RIVER_RIPPLES = preload("res://assets/materials/river-ripples-v37.png")
const REFERENCE_TREES = preload("res://assets/foliage/reference-trees-v40.png")
const BROAD_TREE = preload("res://assets/foliage/foreground-oak-v39.png")
const VALLEY_COLONIES = preload("res://assets/foliage/valley-colonies-v41.png")
const FRAME_GROWTH = preload("res://assets/foliage/frame-growth-v43.png")
const MEADOW_COLONIES = preload("res://assets/foliage/meadow-colonies-v44.png")
const MEADOW_PATCHES = preload("res://assets/foliage/meadow-patches-v37.png")
const LIVING_MEADOW = preload("res://assets/foliage/living-meadow-v38.png")
const WOODLAND_GROUPS = preload("res://assets/foliage/woodland-groups-v37.png")
const WOODLAND_BELTS = preload("res://assets/foliage/woodland-belts-v39.png")
const DISTANT_GROVES = preload("res://assets/foliage/distant-groves-v57.png")
const LANTERN = preload("res://assets/props/foreground-lantern-v1.png")
const HORIZON = preload("res://assets/backgrounds/mountain-massif-v106.png")
const HORIZON_RIGHT = preload("res://assets/backgrounds/wooded-hills-v107.png")
const CASTLE_HILL = preload("res://assets/backgrounds/castle-town-v62.png")
const CASTLE_PEAK_UV := Vector2(0.653715, 0.074803)
const VILLAGE = preload("res://assets/backgrounds/windmill-village-v50.png")

const GRID_STEP := 0.75
const GRID_X := 232
const GRID_Z := 344
const MIN_X := -120.0
const MAX_X := 120.0
const MIN_Z := -231.0
const PLAYER_HEIGHT := 1.8
const BOSS_ARENA_RADIUS := 4.2
const BOSS_CENTER := Vector2(5.0, -12.0)
const SHADOW_CAPACITY := 72
const ROAD_WIDTH := Vector4(1.35, 3.10, -65.0, 10.0)
const WALK_POINTS := [Vector2(12.46, 2.52), Vector2(5.31, -4.41), Vector2(-5.99, -10.45), Vector2(0.83, -16.79), Vector2(8.34, -23.55), Vector2(11.43, -35.45), Vector2(25.39, -53.62), Vector2(32.64, -60.03)]
# Reference-space measurements are mapped onto the actual ground, not a decal
# of the reference image. The playable route follows these same world points.
const ROAD_POINTS := [Vector2(20.78, 6.85), Vector2(12.46, 2.52), Vector2(5.31, -4.41), Vector2(-5.99, -10.45), Vector2(0.83, -16.79), Vector2(8.34, -23.55), Vector2(11.43, -35.45), Vector2(25.39, -53.62), Vector2(32.64, -60.03), Vector2(31.33, -83.32), Vector2(25.73, -126.46), Vector2(-6.4, -189.41)]
const ROAD_FORK := [Vector2(-39, -4), Vector2(-5.99, -10.45)]
const BRIDGE_Z := -38.0
const BRIDGE_SPUR := [Vector2(13.4, -38), Vector2(24.7, -38)]
const TERRACES := [Vector4(-43, -43, 36, 25), Vector4(-45, -54, 27, 20), Vector4(-57, -74, 33, 22), Vector4(-5, -78, 10, 8)]
const TERRACE_HEIGHTS := [3.25, 2.55, 2.05, 1.35]
const TERRACE_TURNS := [-0.40, -0.18, -0.38, 0.0]
# Two differently placed weathering channels on each visible left outcrop.
# These reshape real land; they are not gaps punched only in a painted wall.
const TERRACE_GULLIES := [Vector4(1.00, 0.33, 2.22, 0.27),
	Vector4(0.62, 0.28, 1.83, 0.39), Vector4(1.13, 0.33, 2.43, 0.25)]
# v110 candidate: one upper-rim soil notch, centred on terrace 0 / step 51.
# World XZ frame; tangential support [-1.15, 1.85] m, radial [-2.10, 1.45] m.
const TERRACE_NOTCH_CENTER := Vector2(-36.388867, -20.323368)
const TERRACE_NOTCH_TANGENT := Vector2(-0.885018018, 0.465556773)
const TERRACE_NOTCH_DEPTH := 0.82
const RIVER_BENDS := [Vector2(30, 32), Vector2(10, 32), Vector2(-8, 24.5), Vector2(-34, 34), Vector2(-55, 47), Vector2(-79, 68), Vector2(-104, 65), Vector2(-135, 44), Vector2(-170, 33), Vector2(-231, 48)]
const FOREGROUND_RIM := [Vector2(-45, -7), Vector2(-28.8, 1.18), Vector2(-14.6, 9.32), Vector2(-3.27, 15.025), Vector2(5.4, 16.66), Vector2(18, 19), Vector2(45, 26)]

@onready var camera: Camera3D = $Camera3D
var ground_material: ShaderMaterial
var focus_material: ShaderMaterial
var focus_enabled := true
var shadow_ellipses: Array[Vector4] = []
var asset_paths: Dictionary = {}
var occupied_art_regions: Dictionary = {}
var scale_guide: Node3D
var walker: MeshInstance3D
var travel := 22.0
var route_length := 0.0
var audit_complete := false
var render_metrics_samples := 0

func _ready() -> void:
	var scene_start := Time.get_ticks_msec()
	_setup_view()
	_build_landscape()
	_build_water()
	_build_art_layers()
	SETTLEMENT_LIGHTS.apply(self)
	_build_unique_groundcover()
	_build_meadow_patches()
	# v39 cliff silhouettes come from solid geology. Keep the historical ledge
	# atlas on disk; painted slab cards over the same rock faces doubled the edges.
	_build_woodland_edges()
	_build_dense_edge_growth()
	_build_woodland_belts()
	_build_valley_colonies()
	_build_frame_growth()
	_build_meadow_colonies()
	BRIDGE_BUILDER.new().build(self)
	ROAD_LIGHTS.build(self)
	DETAIL_BUILDER.new().build(self)
	if not ROCK_OCCLUSION.apply(self):
		push_error("Left terrace occlusion data was not applied; inspect the offline bake")
	SCRUB_MODULES.build_stones(self)
	RIVERBANK_BUILDER.new().build(self)
	FOOTHILL_BUILDER.new().build(self)
	MOUNTAIN_GROVES.build_selected(self)
	LEDGE_BREAKUP.build(self)
	MIDDLE_BRUSH.new().build(self)
	_build_river_reflection()
	assert(shadow_ellipses.size() <= SHADOW_CAPACITY, "Increase the matching root-contact shader capacity before adding more props")
	while shadow_ellipses.size() < SHADOW_CAPACITY:
		shadow_ellipses.append(Vector4.ZERO)
	ground_material.set_shader_parameter("contact_shadows", shadow_ellipses)
	_build_scale_guide()
	_build_focus()
	var weather := WEATHER_CONTROLLER.new()
	weather.name = "LivingWeather"
	add_child(weather)
	var wildlife := WILDLIFE_CONTROLLER.new()
	wildlife.name = "LivingWildlife"
	add_child(wildlife)
	wildlife.setup(self)
	var mountain_atmosphere := MOUNTAIN_ATMOSPHERE.new()
	add_child(mountain_atmosphere)
	mountain_atmosphere.setup(self)
	var ground_atmosphere := GROUND_ATMOSPHERE.new()
	add_child(ground_atmosphere)
	ground_atmosphere.setup(self)
	get_tree().create_timer(8.0).timeout.connect(_report_render_metrics)
	print("MEADOW_READY: continuous terrain; %d unique art assets; N day/night, P motion, D focus, G depth, C scale guide" % asset_paths.size())
	var scene_build_ms := Time.get_ticks_msec() - scene_start
	print("MEADOW_STARTUP: scene_ready_ms=%d" % scene_build_ms)
	if OS.has_feature("web"):
		var loading_ui := JavaScriptBridge.get_interface("meadowTimeUI")
		if loading_ui != null:
			loading_ui.sceneReady(scene_build_ms)
		if JavaScriptBridge.eval("new URLSearchParams(location.search).get('render_audit') === '1'"):
			var render_audit = load("res://tools/audit_render_response.gd")
			render_audit.run.call_deferred(self)
		if JavaScriptBridge.eval("new URLSearchParams(location.search).get('canopy_audit') === '1'"):
			var canopy_audit = load("res://tools/audit_canopy_response.gd")
			canopy_audit.run.call_deferred(self)
		if JavaScriptBridge.eval("new URLSearchParams(location.search).get('architecture_audit') === '1'"):
			var architecture_audit = load("res://tools/audit_architecture_response.gd")
			architecture_audit.run.call_deferred(self)
		if JavaScriptBridge.eval("new URLSearchParams(location.search).get('mountain_audit') === '1'"):
			var mountain_audit = load("res://tools/audit_mountain_response.gd")
			mountain_audit.run.call_deferred(self)

func _setup_view() -> void:
	camera.position = Vector3(0, 18, 39)
	camera.look_at(Vector3(0, 0, -27))
	camera.fov = 48.0
	camera.near = 0.10
	# Include the full randomized dragon airspace, not only the distant town.
	camera.far = 560.0
	var environment: Environment = $WorldEnvironment.environment
	environment.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	var sky_material := ShaderMaterial.new()
	sky_material.shader = SKY_SHADER
	_setup_cloud_groups(sky_material)
	sky.sky_material = sky_material
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.43, 0.53, 0.73)
	environment.ambient_light_energy = 0.26
	environment.tonemap_mode = Environment.TONE_MAPPER_AGX
	environment.tonemap_agx_white = 8.0
	environment.tonemap_agx_contrast = 1.45
	environment.tonemap_exposure = 2.0
	environment.adjustment_enabled = true
	environment.adjustment_brightness = 1.0
	environment.adjustment_contrast = 1.0
	environment.adjustment_saturation = 1.0
	environment.ssao_enabled = true
	# Compatibility's simplified SSAO supports radius/intensity only.
	environment.ssao_radius = 0.52
	environment.ssao_intensity = 1.45
	environment.glow_enabled = true
	environment.glow_intensity = 0.12
	environment.glow_hdr_threshold = 1.10
	environment.glow_bloom = 0.0
	environment.fog_enabled = true
	environment.fog_light_color = Color(0.54, 0.69, 0.82)
	environment.fog_density = 0.00065
	environment.fog_sky_affect = 0.08
	# Upper-right side sun. A 110-degree backlight trial crushed the cliff faces;
	# retain enough frontal light for mineral detail, with mainly lateral shadows.
	$KeyLight.rotation_degrees = Vector3(-42, 70, 0)
	$KeyLight.light_color = Color(1.0, 0.95, 0.84)
	$KeyLight.light_energy = 1.60
	$KeyLight.shadow_enabled = true
	$KeyLight.directional_shadow_max_distance = 118.0
	# Two high-resolution cascades cover this fixed view without submitting the
	# entire meadow four times. Distant fogged silhouettes need no micro-shadows.
	$KeyLight.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	$KeyLight.directional_shadow_blend_splits = true
	$KeyLight.directional_shadow_split_1 = 0.27
	$KeyLight.shadow_bias = 0.025
	# Web A/B: 0.25 and 0.7 leave regular self-shadow stripes over both grass
	# and dirt; 1.3 clears them while retaining attached tree/rock/bridge shadows.
	$KeyLight.shadow_normal_bias = 1.3
	# More PCF samples, not a wider blur or a larger shadow-map allocation.
	$KeyLight.shadow_blur = 1.65

func _setup_cloud_groups(material: ShaderMaterial) -> void:
	var centres: Array[Vector4] = []
	var radii := PackedVector3Array()
	var cloud_random := RandomNumberGenerator.new()
	cloud_random.seed = 560909
	# More separated, unequal small cumulus groups. Keep the same 48 volume
	# budget; six broad overlapping lobes formerly merged into smooth sausages.
	var groups := [Vector3(-53, 10, -96), Vector3(-22, 13, -112),
		Vector3(16, 16, -128), Vector3(59, 13, -139),
		Vector3(-61, 16, -156), Vector3(-5, 18, -158),
		Vector3(48, 21, -184), Vector3(88, 20, -181),
		Vector3(-102, 14, -240), Vector3(-66, 10, -263),
		Vector3(-25, 11, -227), Vector3(20, 11, -274),
		Vector3(60, 18, -270), Vector3(109, 11, -251),
		Vector3(153, 24, -270), Vector3(-137, 24, -245)]
	for group: Vector3 in groups:
		var span := cloud_random.randf_range(4.0, 9.0)
		var scale := cloud_random.randf_range(0.72, 1.20)
		# Readable wind at the fixed camera scale: roughly 2–5 rendered px/s,
		# not the old imperceptible 0.1–0.3 px/s. Far layers drift more slowly.
		var speed := cloud_random.randf_range(0.55, 0.85) if group.z > -180.0 else cloud_random.randf_range(0.44, 0.66)
		for lobe in range(3):
			var x := (float(lobe) / 2.0 - 0.5) * span
			var uplift := (1.0 - absf(float(lobe) - 1.0)) * cloud_random.randf_range(0.4, 1.7)
			var centre := group + Vector3(x, uplift, cloud_random.randf_range(-2.8, 2.8))
			centres.append(Vector4(centre.x, centre.y, centre.z, speed))
			radii.append(Vector3(cloud_random.randf_range(2.4, 4.4),
				cloud_random.randf_range(1.0, 2.25), cloud_random.randf_range(2.0, 3.8)) * scale)
	material.set_shader_parameter("cloud_centres", centres)
	material.set_shader_parameter("cloud_radii", radii)

static func river_center(z: float) -> float:
	for i in range(RIVER_BENDS.size() - 1):
		var a: Vector2 = RIVER_BENDS[i]
		var b: Vector2 = RIVER_BENDS[i + 1]
		if z >= b.x:
			var t := clampf((a.x - z) / (a.x - b.x), 0.0, 1.0)
			return lerpf(a.y, b.y, t * t * (3.0 - 2.0 * t)) + 0.65 * sin(z * 0.31 + 0.4)
	return RIVER_BENDS[-1].y

static func river_half_width(z: float) -> float:
	return 6.2 + 1.25 * sin(z * 0.054 + 0.8) + 0.50 * sin(z * 0.23 + 1.8)

static func _hill(x: float, z: float, center: Vector2, radius: Vector2) -> float:
	var p := (Vector2(x, z) - center) / radius
	return exp(-p.length_squared() * 1.8)

static func meadow_height(x: float, z: float) -> float:
	# Broad connected hummocks; detail never comes from scaling a flat plane.
	var rolling := 0.55 * sin(x * 0.083 + z * 0.028) * cos(z * 0.076)
	rolling += 0.29 * sin(z * 0.16 + x * 0.055) + 0.12 * sin(x * 0.42) * cos(z * 0.28)
	rolling += 0.14 * sin(x * 0.91 + sin(z * 0.39)) * cos(z * 0.78 + x * 0.11)
	rolling += 2.3 * _hill(x, z, Vector2(-8, -63), Vector2(26, 21))
	rolling += 4.7 * _hill(x, z, Vector2(46, -66), Vector2(29, 33))
	rolling += 5.7 * _hill(x, z, Vector2(-50, -113), Vector2(52, 40))
	rolling += 5.2 * _hill(x, z, Vector2(72, -181), Vector2(60, 36))
	rolling += 4.5 * _hill(x, z, Vector2(-94, -176), Vector2(70, 32))
	# A broken foothill silhouette hides the former straight green skyline and
	# lets the independent mountain card meet actual undulating world geometry.
	rolling += 3.6 * _hill(x, z, Vector2(-92, -210), Vector2(43, 32))
	rolling += 2.4 * _hill(x, z, Vector2(-31, -198), Vector2(32, 34))
	rolling += 3.5 * _hill(x, z, Vector2(52, -211), Vector2(46, 35))
	rolling += 2.7 * _hill(x, z, Vector2(123, -199), Vector2(38, 32))
	rolling += MOUNTAIN_LANDFORM.height_offset(x, z)
	# The whole Boss clearing is flat; its perimeter blends into the meadow.
	var arena_blend := smoothstep(BOSS_ARENA_RADIUS + 1.0, 10.0, Vector2(x, z).distance_to(BOSS_CENTER))
	return lerpf(0.12, rolling, arena_blend)

static func terrain_height(x: float, z: float) -> float:
	return terrain_height_before_notch(x, z) + terrace_notch_offset(x, z)

static func terrain_height_before_notch(x: float, z: float) -> float:
	# Preserve the original geology inputs: fracture sampling and stone sizes
	# must be generated BEFORE the local displacement, not from a lowered crest.
	var rolling := meadow_height(x, z)
	# Finite overlapping outcrops, not three parallel rails running to the horizon.
	var highland := 0.0
	for i in range(TERRACES.size()):
		var shelf: Vector4 = TERRACES[i]
		# Different orientations and receding centres give each tier its own
		# footprint, instead of stacking near-concentric horizontal ledges.
		var local := (Vector2(x, z) - Vector2(shelf.x, shelf.y)).rotated(-TERRACE_TURNS[i]) / Vector2(shelf.z, shelf.w)
		var angle := local.angle()
		var radius := local.length() / terrace_radius(i, angle)
		# Eroded gullies expose a broad grassy descent between short rock faces.
		# Changing only the stone mesh left the same continuous artificial rails
		# in both the collision surface and its shadow.
		var edge_span := lerpf(0.030, 0.240 if i < 3 else 0.195, terrace_erosion(i, angle))
		var broken_crest := 1.0 + 0.13 * sin(angle * 7.0 + i * 1.9) + 0.055 * sin(angle * 13.0 - i * 0.8)
		# Depress the shoulder into each gully while retaining the plateau core.
		# Broad sloping fans interrupt a tier's otherwise continuous flat rim.
		broken_crest *= 1.0 - terrace_gully(i, angle) * smoothstep(0.65, 1.02, radius) * 0.52
		highland += TERRACE_HEIGHTS[i] * broken_crest * (1.0 - smoothstep(1.0 - edge_span, 1.0 + edge_span, radius))
	# Descend gently beyond the village. The mountains cover the actual far edge.
	highland *= smoothstep(-100.0, -59.0, z)
	var distance_to_river := absf(x - river_center(z))
	var channel_open := smoothstep(-195.0, -170.0, z)
	# The reference stream remains visible in a low valley. The former 4.7 m
	# riverside mound concealed the distant bends behind an implausible tall wall.
	var valley := (1.0 - smoothstep(-95.0, -50.0, z)) * (1.0 - smoothstep(6.0, 18.0, distance_to_river - river_half_width(z))) * channel_open
	rolling *= 1.0 - valley * 0.78
	var bank_offset := river_bank_offset(z, signf(x - river_center(z)))
	var bank_width := river_half_width(z) + bank_offset
	var bank_blend := smoothstep(5.0, 10.0, absf(z - BRIDGE_Z))
	var channel := 1.0 - smoothstep(bank_width - lerpf(0.25, 0.48, bank_blend),
		bank_width + lerpf(1.2, 1.65, bank_blend) + river_upper_slope(z), distance_to_river)
	# The visible bank is layered bedrock with supported grass benches. A broad
	# uniform smoothstep made a sandy chute regardless of how many rocks we added.
	var shore_strength := river_shore_strength(z)
	if shore_strength > 0.0:
		var side := signf(x - river_center(z))
		var profile := (distance_to_river - bank_width + 0.48) / (2.13 + river_upper_slope(z))
		var warp := sin(z * 0.28 + side * 1.6) * 0.035 + sin(z * 0.63 - side) * 0.014
		var shelf_profile := 0.40 * smoothstep(0.025 + warp, 0.20 + warp, profile)
		shelf_profile += 0.34 * smoothstep(0.37 - warp, 0.52 - warp, profile)
		shelf_profile += 0.26 * smoothstep(0.78 + warp, 0.97 + warp, profile)
		# Full-height erosion openings interrupt the beds, not decorative gaps
		# punched in a card while the physical land stays a continuous wall.
		var eroded_profile := smoothstep(0.02, 1.0, profile)
		var rise := lerpf(shelf_profile, eroded_profile, river_bank_gully(z, side))
		channel = lerpf(channel, 1.0 - rise, shore_strength)
	var bank_ridge := (1.0 - smoothstep(1.5, 4.8, absf(distance_to_river - river_half_width(z)))) * 0.45
	# Channel depth is measured from the local bank, keeping the water continuous
	# under hills. It closes naturally below the distant foothill at z=-172.
	var bank_height := rolling + highland + bank_ridge
	# The meadow is itself a foreground promontory, not an endless flat floor.
	# Its scalloped near escarpment is outside the playable path and Boss arena.
	var foreground_drop := smoothstep(foreground_edge(x) - 0.50, foreground_edge(x) + 0.65, z) * 4.2
	return lerpf(bank_height - foreground_drop, -3.0 + 0.18 * sin(z * 0.13), channel * channel_open)

static func terrace_notch_offset(x: float, z: float) -> float:
	# Shared physical displacement, not a removed wall face or dark decal.
	# C1 shoulders retain the plateau beyond 2.1 m inward and fade before the toe.
	var delta := Vector2(x, z) - TERRACE_NOTCH_CENTER
	var along := delta.dot(TERRACE_NOTCH_TANGENT)
	var outward := delta.dot(Vector2(TERRACE_NOTCH_TANGENT.y, -TERRACE_NOTCH_TANGENT.x))
	if along <= -1.15 or along >= 1.85 or outward <= -2.10 or outward >= 1.45:
		return 0.0
	var half_width := 1.15 if along < 0.0 else 1.85
	var mouth := 1.0 - smoothstep(0.18, half_width, absf(along))
	var shoulder := smoothstep(-2.10, -0.55, outward) * (1.0 - smoothstep(0.05, 1.45, outward))
	return -TERRACE_NOTCH_DEPTH * mouth * shoulder

static func river_bank_offset(z: float, side: float) -> float:
	# Small independent erosion coves, continuous with the actual height field.
	# The bridge approaches retain their previously verified shape.
	var blend := smoothstep(5.0, 10.0, absf(z - BRIDGE_Z))
	var small := (sin(z * 0.29 + side * 1.7) * 0.38 + sin(z * 0.81 - side) * 0.16) * blend
	var coves := sin(z * 0.20 + side * 2.0) * 0.92 + sin(z * 0.49 - side * 0.7) * 0.30
	coves += river_bank_gully(z, side) * 1.40
	return small + coves * river_shore_strength(z)

static func river_shore_strength(z: float) -> float:
	# Explicit local edit envelope; retain the bridge, its entries, foreground
	# rim and distant settlements. Walking and Boss terrain are tested densely.
	return smoothstep(-117.0, -104.0, z) * (1.0 - smoothstep(-12.0, -4.0, z)) * smoothstep(7.0, 11.0, absf(z - BRIDGE_Z))

static func river_water_half_width(z: float) -> float:
	return river_half_width(z) + 1.65 + river_upper_slope(z) + river_shore_strength(z) * 2.2

static func below_river_surface(x: float, z: float, height: float) -> bool:
	# Dry lower escarpments may also be below water elevation. Exclude plants
	# only inside the actual river footprint, not on every low part of the world.
	return height < -1.04 and absf(x - river_center(z)) < river_water_half_width(z)

static func river_bank_gully(z: float, side: float) -> float:
	# Keep the broad, camera-facing bedrock around z=-60 legible. Narrow erosion
	# mouths belong between the shelves, not across their most visible face.
	var openings := [Vector2(-23.5, 1.4), Vector2(-79.0, 2.8), Vector2(-105.0, 3.3)]
	var result := 0.0
	for opening: Vector2 in openings:
		var delta := (z - opening.x - (4.5 if side > 0.0 else 0.0)) / opening.y
		result = maxf(result, exp(-delta * delta * 1.7))
	return result

static func river_upper_slope(z: float) -> float:
	# Beyond the bridge, broaden the exposed shoulder into a weathered slope.
	# Keep all near-bank, bridge-entry and central playable geometry unchanged.
	var upper_valley := 1.0 - smoothstep(-78.0, -52.0, z)
	return upper_valley * (3.3 + sin(z * 0.17 + 0.4) * 0.55)

static func foreground_edge(x: float) -> float:
	# A diagonal promontory, measured from the original reference. Mild erosion
	# breaks the silhouette without moving the left/right endpoints into a rail.
	for i in range(FOREGROUND_RIM.size() - 1):
		var a: Vector2 = FOREGROUND_RIM[i]
		var b: Vector2 = FOREGROUND_RIM[i + 1]
		if x <= b.x:
			return lerpf(a.y, b.y, (x - a.x) / (b.x - a.x)) + 0.32 * sin(x * 0.63) + 0.13 * sin(x * 1.41)
	var last: Vector2 = FOREGROUND_RIM[-1]
	return last.y + (x - last.x) * 0.26

static func terrace_radius(index: int, angle: float) -> float:
	# Unequal lobes and erosion coves replace the concentric ellipse silhouette.
	var phase := float(index) * 1.73
	return 1.0 + 0.12 * sin(angle * 3.0 + phase) + 0.085 * sin(angle * 5.0 - phase * 0.7) + 0.032 * sin(angle * 11.0 + phase) - terrace_erosion(index, angle) * 0.055 - terrace_gully(index, angle) * 0.085

static func terrace_gully(index: int, angle: float) -> float:
	if index >= TERRACE_GULLIES.size():
		return 0.0
	var channels: Vector4 = TERRACE_GULLIES[index]
	var first := 1.0 - smoothstep(channels.y * 0.22, channels.y, absf(wrapf(angle - channels.x, -PI, PI)))
	var second := 1.0 - smoothstep(channels.w * 0.22, channels.w, absf(wrapf(angle - channels.z, -PI, PI)))
	return maxf(first, second)

static func terrace_erosion(index: int, angle: float) -> float:
	var phase := float(index) * 1.73
	var coves := sin(angle * 3.0 + phase * 0.8) * 0.62 + sin(angle * 5.0 - phase * 0.4) * 0.38
	return maxf(smoothstep(0.13, 0.71, coves), terrace_gully(index, angle))

static func terrain_normal(x: float, z: float) -> Vector3:
	var epsilon := 0.22
	return Vector3(terrain_height(x - epsilon, z) - terrain_height(x + epsilon, z), 2.0 * epsilon,
		terrain_height(x, z - epsilon) - terrain_height(x, z + epsilon)).normalized()

static func terrace_boundary(index: int, angle: float) -> Vector2:
	var shelf: Vector4 = TERRACES[index]
	var local := Vector2(cos(angle) * shelf.z, sin(angle) * shelf.w) * terrace_radius(index, angle)
	return Vector2(shelf.x, shelf.y) + local.rotated(TERRACE_TURNS[index])

static func distance_to_road(point: Vector2) -> float:
	var closest := 1000.0
	for i in range(ROAD_POINTS.size() - 1):
		closest = minf(closest, point.distance_to(Geometry2D.get_closest_point_to_segment(point, ROAD_POINTS[i], ROAD_POINTS[i + 1])))
	closest = minf(closest, point.distance_to(Geometry2D.get_closest_point_to_segment(point, BRIDGE_SPUR[0], BRIDGE_SPUR[1])))
	return minf(closest, point.distance_to(Geometry2D.get_closest_point_to_segment(point, ROAD_FORK[0], ROAD_FORK[1])))

static func road_half_width(z: float) -> float:
	return lerpf(ROAD_WIDTH.x, ROAD_WIDTH.y, smoothstep(ROAD_WIDTH.z, ROAD_WIDTH.w, z))

static func _growth_hash(p: Vector2) -> float:
	return fposmod(sin(p.dot(Vector2(127.1, 311.7))) * 43758.5453, 1.0)

static func _growth_noise(p: Vector2) -> float:
	var cell := p.floor()
	var f := p - cell
	f = f * f * (Vector2(3.0, 3.0) - f * 2.0)
	return lerpf(lerpf(_growth_hash(cell), _growth_hash(cell + Vector2.RIGHT), f.x),
		lerpf(_growth_hash(cell + Vector2.DOWN), _growth_hash(cell + Vector2.ONE), f.x), f.y)

static func growth_density(p: Vector2) -> float:
	# Deterministic, domain-warped patches replace periodic sin-product circles.
	# This is built once into UV2 and also sampled by real leaf placement. Nothing
	# moves the ground distribution every frame or tiles a vegetation prop.
	var warp := Vector2(_growth_noise(p * 0.051 + Vector2(12.7, 31.2)),
		_growth_noise(p * 0.051 + Vector2(68.1, 9.4))) * 11.0 - Vector2(5.5, 5.5)
	var q := p + warp
	var broad := _growth_noise(q * Vector2(0.115, 0.073))
	var middle := _growth_noise(q * 0.33 + Vector2(19.2, 43.8))
	var detail := _growth_noise(p * 0.74 + Vector2(51.9, 4.7)) * 2.0 - 1.0
	var density := clampf(0.50 + (broad - 0.5) * 1.35 + (middle - 0.5) * 0.45 + detail * 0.08, 0.0, 1.0)
	# The reference has a connected foreground mat and grassy rock shoulders,
	# not a uniformly sparse lawn. Regional envelopes shape that composition;
	# the irregular field still breaks their edges and supplies internal gaps.
	var foreground := smoothstep(-10.0, 3.0, p.y) * (1.0 - smoothstep(19.0, 29.0, p.y))
	foreground *= smoothstep(-43.0, -28.0, p.x) * (1.0 - smoothstep(21.0, 36.0, p.x))
	density = lerpf(density, maxf(density, 0.63 + middle * 0.21), foreground * 0.95)
	var shoulders := smoothstep(-88.0, -71.0, p.y) * (1.0 - smoothstep(-30.0, -17.0, p.y))
	shoulders *= 1.0 - smoothstep(-19.0, -5.0, p.x)
	density = lerpf(density, maxf(density, 0.61 + middle * 0.22), shoulders * 0.72)
	# The reference foreground has connected low growth below the fence/lamp,
	# not separate round tufts stranded in a lawn. Bias that measured verge only;
	# the same field still drives the ground shader and the physical leaf forms.
	var verge := _hill(p.x, p.y, Vector2(-23.8, 1.0), Vector2(3.1, 2.4))
	verge = maxf(verge, _hill(p.x, p.y, Vector2(-17.0, 2.0), Vector2(5.6, 3.0)))
	verge = maxf(verge, _hill(p.x, p.y, Vector2(-10.9, 6.2), Vector2(5.8, 4.0)))
	return lerpf(density, maxf(density, 0.81 + detail * 0.07), verge * 0.86)

func _build_landscape() -> void:
	if STATIC_CACHE.restore(self, "terrain"):
		var cached: MeshInstance3D = get_node("ContinuousMeadow")
		ground_material = cached.material_override
		print("MEADOW_TERRAIN: %d vertices / %d triangles (prebuilt)" % [cached.mesh.surface_get_array_len(0), cached.mesh.surface_get_array_index_len(0) / 3])
		return
	ground_material = ShaderMaterial.new()
	ground_material.shader = GROUND_SHADER
	ground_material.set_shader_parameter("meadow_texture", MEADOW)
	ground_material.set_shader_parameter("rock_texture", ROCK)
	ground_material.set_shader_parameter("limestone_texture", WEATHERED_ROCK)
	ground_material.set_shader_parameter("bank_limestone_texture", BANK_LIMESTONE)
	ground_material.set_shader_parameter("road_points", PackedVector2Array(ROAD_POINTS))
	ground_material.set_shader_parameter("road_fork", PackedVector2Array(ROAD_FORK))
	ground_material.set_shader_parameter("bridge_spur", PackedVector2Array(BRIDGE_SPUR))
	ground_material.set_shader_parameter("river_bends", PackedVector2Array(RIVER_BENDS))
	ground_material.set_shader_parameter("road_width", ROAD_WIDTH)
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var growth := PackedVector2Array()
	var indices := PackedInt32Array()
	# Keep extra samples attached to BOTH banks. A uniform grid alone aliases a
	# narrow cliff into a row of spikes, especially in the distance.
	const BANK_OFFSETS := [-0.4, 0.0, 0.22, 0.45, 0.70, 1.0, 1.5, 2.5, 4.0]
	var row_size := GRID_X + 1 + BANK_OFFSETS.size() * 2
	var row_z := PackedFloat32Array()
	# Sparse distant rows close the real ground below independently cut-out
	# mountain/forest silhouettes. The old -231 m edge exposed strips of sky
	# when the artificially wide forest belts were corrected.
	for i in range(24):
		row_z.append(MIN_Z - (24 - i) * 4.0)
	for iz in range(GRID_Z + 1):
		row_z.append(MIN_Z + iz * GRID_STEP)
	for z: float in row_z:
		var row_x := PackedFloat32Array()
		for ix in range(GRID_X + 1):
			var far_widening := 1.0 + (1.0 - smoothstep(-230.0, -70.0, z)) * 1.2
			row_x.append(lerpf(MIN_X, MAX_X, float(ix) / GRID_X) * far_widening)
		for offset in BANK_OFFSETS:
			var slot: int = BANK_OFFSETS.find(offset)
			const SHORE_FRACTIONS := [-0.06, 0.025, 0.20, 0.37, 0.52, 0.65, 0.78, 0.97, 1.04]
			var bank_sample := lerpf(offset, -0.48 + SHORE_FRACTIONS[slot] * (2.13 + river_upper_slope(z)), river_shore_strength(z))
			row_x.append(river_center(z) - river_half_width(z) - river_bank_offset(z, -1.0) - bank_sample)
			row_x.append(river_center(z) + river_half_width(z) + river_bank_offset(z, 1.0) + bank_sample)
		row_x.sort()
		for x in row_x:
			vertices.append(Vector3(x, terrain_height(x, z), z))
			normals.append(terrain_normal(x, z))
			uvs.append(Vector2(x, z))
			growth.append(Vector2(growth_density(Vector2(x, z)), 0.0))
	for iz in range(row_z.size() - 1):
		for ix in range(row_size - 1):
			var i := iz * row_size + ix
			indices.append_array(PackedInt32Array([i, i + 1, i + row_size, i + 1, i + row_size + 1, i + row_size]))
	var mesh := _array_mesh(vertices, normals, uvs, indices, growth)
	var land := MeshInstance3D.new()
	land.name = "ContinuousMeadow"
	land.mesh = mesh
	land.material_override = ground_material
	add_child(land)
	land.create_trimesh_collision()
	land.get_child(0).name = "GroundCollision"
	print("MEADOW_TERRAIN: %d vertices / %d triangles" % [vertices.size(), indices.size() / 3])

func _build_water() -> void:
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var flow_frames := PackedVector2Array()
	var indices := PackedInt32Array()
	var length_along := 0.0
	var previous_center := Vector2(river_center(MIN_Z), MIN_Z)
	var minimum_direction := INF
	var maximum_direction := -INF
	for iz in range(GRID_Z + 1):
		var z := MIN_Z + iz * GRID_STEP
		var center := Vector2(river_center(z), z)
		length_along += center.distance_to(previous_center)
		previous_center = center
		var half_width := river_water_half_width(z)
		var direction := (river_center(z + 0.1) - river_center(z - 0.1)) / 0.2
		minimum_direction = minf(minimum_direction, rad_to_deg(atan(direction)))
		maximum_direction = maxf(maximum_direction, rad_to_deg(atan(direction)))
		for side in range(2):
			var x := center.x + (2.0 * side - 1.0) * half_width
			vertices.append(Vector3(x, -1.05, z))
			normals.append(Vector3.UP)
			uvs.append(Vector2(side, length_along))
			flow_frames.append(Vector2(half_width, direction))
	for iz in range(GRID_Z):
		var i := iz * 2
		indices.append_array(PackedInt32Array([i, i + 1, i + 2, i + 1, i + 3, i + 2]))
	var water := MeshInstance3D.new()
	water.name = "ContinuousRiver"
	water.layers = 2
	water.mesh = _array_mesh(vertices, normals, uvs, indices, flow_frames)
	var material := ShaderMaterial.new()
	material.shader = WATER_SHADER
	material.set_shader_parameter("ripple_texture", RIVER_RIPPLES)
	material.set_shader_parameter("shallow_opacity", 0.18)
	material.set_shader_parameter("deep_opacity", 0.46)
	# Godot copies screen color before transparent geometry. Water must composite
	# AFTER the full-screen focus pass, or that pass would erase the transparent river.
	material.render_priority = 127
	water.material_override = material
	water.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(water)
	_build_submerged_stones()
	assert(length_along > GRID_Z * GRID_STEP and flow_frames.size() == vertices.size(), "Water flow coordinates must follow the curved river")
	print("MEADOW_RIVER_FLOW_AUDIT: %d paired bank rows; %.2f m arc length; local heading %.2f to %.2f deg" % [GRID_Z + 1, length_along, minimum_direction, maximum_direction])

func _build_submerged_stones() -> void:
	# Real opaque geometry below the transparent water, not drawn-on blue stones.
	var shape := SphereMesh.new()
	shape.radius = 1.0
	shape.height = 2.0
	shape.radial_segments = 8
	shape.rings = 4
	var stones := MultiMesh.new()
	stones.transform_format = MultiMesh.TRANSFORM_3D
	stones.use_colors = true
	stones.mesh = shape
	stones.instance_count = 72
	var random := RandomNumberGenerator.new()
	random.seed = 5109
	var maximum_top := -INF
	for i in range(72):
		var z := random.randf_range(-74.0, 3.0)
		var x := river_center(z) + random.randf_range(-0.74, 0.74) * river_half_width(z)
		var size := Vector3(random.randf_range(0.24, 0.73), random.randf_range(0.10, 0.27), random.randf_range(0.20, 0.66))
		var position := Vector3(x, terrain_height(x, z) + size.y * 0.4, z)
		var basis := Basis(Vector3.UP, random.randf_range(-PI, PI)).scaled(size)
		stones.set_instance_transform(i, Transform3D(basis, position))
		stones.set_instance_color(i, Color(0.43, 0.41, 0.33) * random.randf_range(0.67, 1.16))
		maximum_top = maxf(maximum_top, position.y + size.y)
	assert(maximum_top < -1.35, "Bed stones must remain safely below the river surface")
	var material := StandardMaterial3D.new()
	material.vertex_color_use_as_albedo = true
	material.roughness = 0.84
	material.metallic_specular = 0.14
	var bed := MultiMeshInstance3D.new()
	bed.name = "SubmergedRiverStones"
	bed.multimesh = stones
	bed.material_override = material
	bed.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(bed)
	print("MEADOW_RIVERBED_READY: 72 submerged stones in one batch; highest top %.3f m; water -1.05 m" % maximum_top)

func _build_river_reflection() -> void:
	# Compatibility supports probe reflections. Capture once, not every frame;
	# this is a local approximation, not SSR or a planar mirror of the whole river.
	var probe := ReflectionProbe.new()
	probe.name = "RiverSurroundingsReflection"
	probe.position = Vector3(river_center(-26.0), 1.8, -26.0)
	probe.size = Vector3(46, 20, 116)
	probe.origin_offset = Vector3(0, 0.8, 0)
	probe.box_projection = true
	probe.intensity = 0.68
	probe.blend_distance = 9.0
	probe.max_distance = 86.0
	probe.update_mode = ReflectionProbe.UPDATE_ONCE
	probe.ambient_mode = ReflectionProbe.AMBIENT_DISABLED
	probe.reflection_mask = 2
	probe.cull_mask = 1 # No water self-reflection, screen effect or tiny grass.
	add_child(probe)

func _build_art_layers() -> void:
	# Roots are measured in texture UVs, including transparent padding.
	_build_reference_trees()
	_art("BroadTreeAtRightFrame", BROAD_TREE, Vector2(18.7, 11.5), 7.2, Vector2(0.51, 0.95), -0.14)
	_shadow(Vector2(18.7, 11.5), Vector2(3.9, 2.5))
	HERB_MODULES.build(self, 0)
	_shadow(Vector2(-9.12985, 7.03097), Vector2(2.6, 1.1))
	HERB_MODULES.build(self, 1)
	_shadow(HERB_MODULES.FEET[1], Vector2(2.7, 1.2))
	# The two near rock clusters are now solid geology, not camera-facing PNGs.
	_shadow(Vector2(-5.6, 1.7), Vector2(1.8, 0.9))
	_shadow(Vector2(14.5, -7.0), Vector2(1.6, 0.9))
	FENCE_BUILDER.new().build(self)
	_art("TrailLantern", LANTERN, Vector2(-17.28809, -3.49135), 3.25, Vector2(0.51, 0.92), -0.08)
	_shadow(Vector2(-17.28809, -3.49135), Vector2(0.75, 0.6))
	# Shelf tops are the collision terrain itself. No detached broad-top art slabs.
	var village := VILLAGE_BUILDER.new()
	village.name = "VillageWindmills"
	add_child(village)
	village.build(self, VILLAGE)
	# C of four new true-alpha massifs. Native aspect, no compressed tall peaks.
	var mountains := _art("DistantMountainRidge", HORIZON, Vector2(-95, -310.0), 390.0, Vector2(0.5, 0.715), -0.05, Color(0.92, 0.96, 0.92), false)
	mountains.material_override.shader = preload("res://shaders/meadow_mountain.gdshader")
	mountains.material_override.set_shader_parameter("native_massif", true)
	mountains.material_override.set_shader_parameter("art_contrast", 1.16)
	mountains.material_override.set_shader_parameter("art_exposure", 0.95)
	mountains.material_override.set_shader_parameter("alpha_threshold", 0.60)
	mountains.position.y = 0.0
	MOUNTAIN_RELIEF.apply(self, mountains)
	mountains.material_override.set_shader_parameter("mountain_normal_strength", 0.0)
	# An independently generated low wooded ridge lets the castle keep its skyline.
	# Full source at native aspect, not a compressed crop of the main mountain.
	var right_ridge := _art("RightMountainRidge", HORIZON_RIGHT, Vector2(200, -320), 230.0,
		Vector2(0.5, 0.715), -0.05, Color(0.90, 0.94, 0.92), false)
	right_ridge.material_override.shader = preload("res://shaders/meadow_mountain.gdshader")
	right_ridge.material_override.set_shader_parameter("native_massif", true)
	right_ridge.material_override.set_shader_parameter("wooded_foothill", true)
	right_ridge.material_override.set_shader_parameter("alpha_threshold", 0.60)
	right_ridge.material_override.set_shader_parameter("art_contrast", 1.16)
	right_ridge.material_override.set_shader_parameter("art_exposure", 0.92)
	right_ridge.material_override.set_shader_parameter("mountain_normal_strength", 0.0)
	right_ridge.position.y = 0.0
	MOUNTAIN_RELIEF.apply(self, right_ridge)
	CITY_BUILDER.new().build(self, CASTLE_HILL, CASTLE_PEAK_UV)

func _build_reference_trees() -> void:
	# C of four fresh RGBA candidates. The previous reference-edit batch had an
	# opaque checkerboard and was rejected. Actual alpha gutters are not equal.
	var crops := [Rect2(32, 20, 728, 578), Rect2(801, 90, 428, 507),
		Rect2(40, 614, 587, 600), Rect2(651, 759, 578, 445)]
	var anchors := [Vector2(0.472527, 0.99308), Vector2(0.518692, 0.99211),
		Vector2(0.495741, 0.993333), Vector2(0.735294, 0.991011)]
	var names := ["OakOnLowerOutcrop", "YoungOakByVillage", "OldOakOnShelf", "YoungHawthornInValley"]
	# Screen-space rays found soil beside the protruding rock faces. Keep the
	# reference landmarks while rooting the trunks on the actual upper surface.
	var feet := [Vector2(-47.8063, -36.34222), Vector2(-60, -102.9), Vector2(-30.73954, -44.24666), Vector2(1.9, -94.06)]
	# Match crown coverage as well as root positions. The old undersized crowns
	# left the reference's shaded oak terraces looking like scattered saplings.
	var widths := [10.4, 6.9, 7.2, 8.6]
	for i in range(4):
		var crop: Rect2 = crops[i]
		var tree := _art(names[i], REFERENCE_TREES, feet[i], widths[i], anchors[i], -0.055,
			Color(0.88, 0.93, 0.82), true, Rect2(crop.position / 1254.0, crop.size / 1254.0))
		_conform_root_line(tree)
		_shadow(feet[i], Vector2(widths[i] * 0.48, widths[i] * 0.25))

func _build_unique_groundcover() -> void:
	SCRUB_MODULES.build_plants(self)

func _build_meadow_patches() -> void:
	# Crops follow measured transparent gutters. They never overlap another design.
	var crops := [Rect2(17, 53, 601, 272), Rect2(633, 50, 605, 274),
		Rect2(22, 357, 595, 298), Rect2(637, 338, 600, 310),
		Rect2(20, 662, 604, 300), Rect2(646, 709, 590, 246),
		Rect2(26, 975, 590, 245), Rect2(641, 987, 598, 237)]
	var names := ["LowBrambleEdge", "YarrowMeadow", "FernRiverGroup", "OakScrubBank",
		"SedgeInlet", "HeatherAndRoot", "ChamomileGap", "DryGrassyRubble"]
	var feet := [Vector2(-12.5, -4.0), Vector2(-2.0, 1.0), Vector2(16.8, -16.5),
		Vector2(-26.0, -34.0), Vector2(45.0, -24.0), Vector2(-14.4, 6.6),
		Vector2(-4.7, -33.0), Vector2(-7.0, -66.0)]
	var widths := [2.98, 3.84, 3.22, 3.12, 3.26, 3.22, 3.02, 3.84]
	for i in range(8):
		var crop: Rect2 = crops[i]
		var region := Rect2(crop.position / 1254.0, crop.size / 1254.0)
		var patch := _art(names[i], MEADOW_PATCHES, feet[i], widths[i], Vector2(0.5, 0.98), -0.14,
			Color(0.96, 0.98, 0.92), true, region)
		# Resize the whole colony, not only its vertical axis. Compressed leaf
		# artwork reads as a flat stripe even when the root mesh does not fold.
		_conform_root_line(patch)
		_shadow(feet[i], Vector2(widths[i] * 0.51, widths[i] * 0.22))


func _build_woodland_edges() -> void:
	var crops := [Rect2(92, 23, 487, 314), Rect2(725, 15, 437, 326),
		Rect2(70, 349, 542, 287), Rect2(691, 365, 501, 274),
		Rect2(75, 644, 507, 280), Rect2(663, 656, 545, 280),
		Rect2(69, 924, 494, 311), Rect2(671, 1015, 523, 218)]
	var names := ["OldOakOnShelf", "ThreeElmsByVillage", "WillowsAcrossWater", "HighMeadowOakAndSaplings",
		"FieldMapleAndHawthorn", "FarYoungOakCoppice", "TwoTreesOnLeftRidge", "UnevenRiversideHedge"]
	var feet := [Vector2(-31.14, -45.1), Vector2(-35, -140), Vector2(river_center(-29) + river_half_width(-29) + 8.0, -29), Vector2(84, -136),
		Vector2(-49, -21), Vector2(-24, -98), Vector2(-70, -125), Vector2(river_center(-48.0) + river_half_width(-48.0) + 3.5, -48)]
	var widths := [8.8, 8.8, 10.0, 12.6, 6.8, 16.0, 12.3, 12.0]
	for i in range(8):
		if i == 0 or i == 4:
			continue # Replaced by two unique v40 quartet designs, not doubled up.
		var crop: Rect2 = crops[i]
		var grove := _art(names[i], WOODLAND_GROUPS, feet[i], widths[i], Vector2(0.5, 0.985), -0.10,
			Color(0.90, 0.94, 0.85), true, Rect2(crop.position / 1254.0, crop.size / 1254.0))
		if i == 7:
			grove.mesh.size.y *= 0.68
			grove.mesh.center_offset.y *= 0.68
		_conform_root_line(grove)
		_shadow(feet[i], Vector2(widths[i] * 0.48, widths[i] * 0.22))

func _build_dense_edge_growth() -> void:
	# Selected C of four concurrent generations. Bounds follow measured alpha
	# gutters; each plant design appears exactly once, integrated at an edge.
	var crops := [Rect2(24, 57, 604, 277), Rect2(651, 44, 583, 291),
		Rect2(23, 366, 592, 252), Rect2(644, 354, 586, 275),
		Rect2(18, 625, 606, 294), Rect2(651, 659, 584, 244),
		Rect2(21, 925, 603, 275), Rect2(643, 934, 590, 282)]
	var feet := [Vector2(-8.0, 8.5), Vector2(-22.5, -15.0), Vector2(17.8, -4.0),
		Vector2(river_center(-26.0) - river_half_width(-26.0) - 2.8, -26),
		Vector2(-18.0, 4.0), Vector2(-7.5, -39.0), Vector2(-29.0, -32.0),
		Vector2(river_center(-49.0) + river_half_width(-49.0) + 3.8, -49)]
	var widths := [3.36, 4.13, 3.55, 3.22, 3.84, 4.03, 4.22, 4.42]
	for i in range(crops.size()):
		var crop: Rect2 = crops[i]
		var growth := _art("LivingMeadowGroup_%02d" % i, LIVING_MEADOW, feet[i], widths[i],
			Vector2(0.5, 0.985), -0.11, Color(0.93, 0.96, 0.86), true,
			Rect2(crop.position / 1254.0, crop.size / 1254.0))
		_conform_root_line(growth)
		_shadow(feet[i], Vector2(widths[i] * 0.42, widths[i] * 0.18))

func _build_woodland_belts() -> void:
	# Six naturally low, wide, small-tree groves replace vertically squeezed
	# tall-tree art. The two accepted foreground designs remain unchanged.
	var crops := [Rect2(17, 27, 591, 307), Rect2(641, 24, 596, 309),
		Rect2(20, 384, 592, 240), Rect2(640, 367, 596, 255),
		Rect2(19, 641, 598, 296), Rect2(644, 643, 591, 291),
		Rect2(24, 941, 572, 279), Rect2(635, 961, 590, 261)]
	var feet := [Vector2(-87, -147), Vector2(-44, -139), Vector2(-22, -173), Vector2(103, -126),
		Vector2(-129, -205), Vector2(101, -187), Vector2(-16.5, 14.8), Vector2(7.0, 16.5)]
	var widths := [45.0, 32.0, 40.0, 52.0, 86.0, 84.0, 13.8, 9.3]
	var grove_rows := [0, 187, 366, 535, 680, 857, 1024]
	for i in range(crops.size()):
		var crop: Rect2 = crops[i]
		var texture: Texture2D = WOODLAND_BELTS
		var dimensions := Vector2(1254, 1254)
		if i < 6:
			texture = DISTANT_GROVES
			dimensions = Vector2(1536, 1024)
			crop = Rect2(52, grove_rows[i], 1434, grove_rows[i + 1] - grove_rows[i])
		var root_y: float = [186.0/187.0, 174.0/179.0, 164.0/169.0, 144.0/145.0, 169.0/177.0, 148.0/167.0][i] if i < 6 else 0.985
		var grove := _art("UniqueWoodlandBelt_%02d" % i, texture, feet[i], widths[i],
			Vector2(0.5, root_y), -0.06 if i < 6 else -0.2, Color(0.88, 0.92, 0.82), true,
			Rect2(crop.position / dimensions, crop.size / dimensions))
		if i < 6:
			grove.material_override.set_shader_parameter("painted_fill", 0.16)
			grove.material_override.set_shader_parameter("mip_bias", -0.45)
			grove.material_override.set_shader_parameter("art_exposure", 0.85)
			grove.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		_conform_root_line(grove, i < 6)
		_shadow(feet[i], Vector2(widths[i] * 0.48, widths[i] * 0.24))
	print("MEADOW_DISTANT_GROVES_AUDIT: six unique natural-aspect groves; no vertical compression; real-alpha source; two foreground designs preserved")

func _build_valley_colonies() -> void:
	# D is the only four-way candidate with complete transparent gutters around
	# all eight designs. The former single copse is replaced, not stamped again.
	var crops := [Rect2(45, 74, 572, 247), Rect2(670, 38, 548, 297),
		Rect2(36, 367, 571, 247), Rect2(668, 366, 548, 256),
		Rect2(39, 682, 576, 248), Rect2(677, 625, 517, 339),
		Rect2(47, 957, 556, 262), Rect2(668, 1018, 536, 202)]
	var names := ["ValleyRoseColony", "LittleHawthornAndBramble", "HazelOnLeftMeadow",
		"LowWillowInValley", "DistantMugwortAndFlowers", "ThreeUnequalOaks",
		"FarBankReedColony", "CloverAtUpperTrail"]
	var feet := [Vector2(-20.57, -69.23), Vector2(-9.26, -106.30), Vector2(-31.33, -99.72),
		Vector2(18.77, -72.18), Vector2(22.51, -153.50), Vector2(42.10, -110.79),
		Vector2(river_center(-110.0) + river_half_width(-110.0) + 4.4, -110.0), Vector2(9.95, -47.85)]
	var widths := [7.1, 8.4, 6.8, 8.0, 10.8, 23.0, 7.4, 5.6]
	for i in range(crops.size()):
		var crop: Rect2 = crops[i]
		var colony := _art(names[i], VALLEY_COLONIES, feet[i], widths[i], Vector2(0.5, 0.986),
			-0.07, Color(0.80, 0.86, 0.71), true, Rect2(crop.position / 1254.0, crop.size / 1254.0))
		_conform_root_line(colony)
		_shadow(feet[i], Vector2(widths[i] * 0.48, widths[i] * 0.23))
		assert(terrain_height(feet[i].x, feet[i].y) > -0.75, "Valley vegetation must be on land above the river")
		assert(distance_to_road(feet[i]) > road_half_width(feet[i].y) + widths[i] * 0.28,
			"Valley colony intrudes into the shared playable trail")
	print("MEADOW_VALLEY_AUDIT: 8 unique colonies above water and clear of the trail")

func _build_frame_growth() -> void:
	# D of four simultaneous candidates. A/C failed the real-alpha gutter audit.
	# The old broad hawthorn/brambles leave the scene; every new region is used once.
	var crops := [Rect2(10, 25, 658, 722), Rect2(700, 162, 537, 568),
		Rect2(42, 810, 575, 408), Rect2(660, 890, 574, 326)]
	var anchors := [Vector2(0.641337, 0.998615), Vector2(0.318436, 0.992958),
		Vector2(0.626087, 0.990196), Vector2(0.534843, 0.987730)]
	var names := ["LeftFrameOak", "HazelAboveLimestone", "DeepValleyHawthorn", "FloweredTerraceToe"]
	# Root placement uses the solid terrain, including its widened distant rows.
	var feet := [Vector2(-128, -146), Vector2(-22.29, -31.52), Vector2(-5.72, -32.28), Vector2(-18.04696, -28.75131)]
	var widths := [21.0, 6.4, 8.4, 6.9]
	for i in range(crops.size()):
		var crop: Rect2 = crops[i]
		var growth := _art(names[i], FRAME_GROWTH, feet[i], widths[i], anchors[i], -0.07,
			Color(0.87, 0.93, 0.81), true, Rect2(crop.position / 1254.0, crop.size / 1254.0))
		_conform_root_line(growth)
		_shadow(feet[i], Vector2(widths[i] * 0.42, widths[i] * 0.23))
		var half_width := MAX_X * (1.0 + (1.0 - smoothstep(-230.0, -70.0, feet[i].y)) * 1.2)
		assert(absf(feet[i].x) <= half_width and feet[i].y >= MIN_Z,
			"Frame growth must be rooted inside the actual terrain mesh")
		assert(terrain_height(feet[i].x, feet[i].y) > -0.75, "Frame growth is below the water line")
		assert(distance_to_road(feet[i]) > road_half_width(feet[i].y) + widths[i] * 0.28,
			"Frame growth intrudes into the shared playable trail")
		assert(feet[i].distance_to(BOSS_CENTER) > BOSS_ARENA_RADIUS + widths[i] * 0.5,
			"Frame growth intrudes into the future Boss clearing")
	print("MEADOW_FRAME_GROWTH_AUDIT: 4 unique designs on terrain, clear of trail and Boss clearing")

func _build_meadow_colonies() -> void:
	# A of four concurrent real-alpha candidates. Four new designs, no stamping.
	var crops := [Rect2(13, 205, 587, 318), Rect2(658, 177, 588, 358),
		Rect2(13, 758, 603, 346), Rect2(648, 795, 593, 323)]
	var anchors := [Vector2(0.345826, 0.987421), Vector2(0.314626, 0.988827),
		Vector2(0.386401, 0.988439), Vector2(0.571669, 0.987616)]
	# The second existing colony follows the new gully shoulder: a 0.5m move
	# onto measured soil support, keeping its single unique image and full scale.
	var feet := [Vector2(-27.27, -19.75), Vector2(-14.20, -38.14),
		Vector2(-11.35, 2.11), Vector2(17.40, -33.40)]
	var widths := [4.2, 5.0, 3.5, 4.8]
	for i in range(4):
		var crop: Rect2 = crops[i]
		var growth := _art("MeadowColony_%02d" % i, MEADOW_COLONIES, feet[i], widths[i], anchors[i],
			-0.07, Color(0.88, 0.94, 0.79), true, Rect2(crop.position / 1254.0, crop.size / 1254.0))
		_conform_root_line(growth)
		_shadow(feet[i], Vector2(widths[i] * 0.42, widths[i] * 0.23))
		assert(terrain_height(feet[i].x, feet[i].y) > -0.75, "Meadow colonies must stand above water")
		assert(distance_to_road(feet[i]) > road_half_width(feet[i].y) + widths[i] * 0.28,
			"Meadow colony intrudes into the trail: %d" % i)
		assert(feet[i].distance_to(BOSS_CENTER) > BOSS_ARENA_RADIUS + widths[i] * 0.5,
			"Meadow colony intrudes into the Boss clearing")
	print("MEADOW_COLONY_AUDIT: 4 unique designs; trail and Boss clearing kept free")

func _conform_root_line(instance: MeshInstance3D, follow_whole_column: bool = false) -> void:
	# A wide copse must follow the ground under ALL its trunks, not just its centre.
	# Adjust only the lower root band. Tree crowns must keep their painted shape.
	var quad: QuadMesh = instance.mesh
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var base_height := terrain_height(instance.position.x, instance.position.z)
	var camera_up := camera.global_basis.y
	var root_band := 0.55 if quad.size.y < 2.5 else 0.30
	# smoothstep's maximum derivative is 1.5 / band. Bound the root shift by
	# height as well as width so short groundcover can never fold over itself.
	# A wide strip of SMALL distant trees follows the hill column by column;
	# translating their whole heights avoids both short-tree squashing and the
	# several-metre floating base caused by the old root-only displacement cap.
	var root_limit := 30.0 if follow_whole_column else minf(clampf(quad.size.x * 0.055, 0.70, 3.5), quad.size.y * root_band * 0.50)
	var minimum_column_step := INF
	for column in range(25):
		var u := float(column) / 24.0
		var x := quad.center_offset.x + (u - 0.5) * quad.size.x
		var delta := 0.0
		for solve in range(3):
			delta = (terrain_height(instance.position.x + x, instance.position.z + camera_up.z * delta) - base_height) / camera_up.y
			delta = clampf(delta, -root_limit, root_limit)
		var previous_y := -INF
		for row in range(9):
			var v := float(row) / 8.0
			var weight := 1.0 if follow_whole_column else 1.0 - smoothstep(0.0, root_band, v)
			var y := quad.center_offset.y + (v - 0.5) * quad.size.y + delta * weight
			if row > 0:
				minimum_column_step = minf(minimum_column_step, y - previous_y)
			previous_y = y
			vertices.append(Vector3(x, y, 0))
			normals.append(Vector3.BACK)
			uvs.append(Vector2(u, 1.0 - v))
	for column in range(24):
		for row in range(8):
			var i := column * 9 + row
			indices.append_array(PackedInt32Array([i, i + 1, i + 9, i + 1, i + 10, i + 9]))
	instance.mesh = _array_mesh(vertices, normals, uvs, indices)
	assert(minimum_column_step > 0.0, "Root deformation inverted a plant mesh: " + instance.name)

func _art(label: String, texture: Texture2D, foot: Vector2, width: float,
		anchor: Vector2, sink: float = 0.0, tint: Color = Color.WHITE, billboard: bool = true,
		region: Rect2 = Rect2(0, 0, 1, 1)) -> MeshInstance3D:
	# Atlas cells are DIFFERENT props. No duplicate or overlapping source regions.
	var existing_regions: Array = occupied_art_regions.get(texture.resource_path, [])
	for existing: Rect2 in existing_regions:
		assert(not existing.intersects(region), "Do not stamp the same art pixels twice: " + label)
	existing_regions.append(region)
	occupied_art_regions[texture.resource_path] = existing_regions
	asset_paths[texture.resource_path + "@" + str(region)] = label
	var mesh := QuadMesh.new()
	var height := width * texture.get_height() * region.size.y / (float(texture.get_width()) * region.size.x)
	mesh.size = Vector2(width, height)
	mesh.center_offset = Vector3((0.5 - anchor.x) * width, (anchor.y - 0.5) * height, 0)
	var material := ShaderMaterial.new()
	var mountain_art := texture == HORIZON or texture == HORIZON_RIGHT
	var distant := mountain_art or texture == VILLAGE or texture == CASTLE_HILL
	material.shader = DISTANT_CUTOUT_SHADER if distant else CUTOUT_SHADER
	material.set_shader_parameter("asset_texture", texture)
	material.set_shader_parameter("tint", tint)
	material.set_shader_parameter("face_camera", billboard)
	material.set_shader_parameter("uv_region", Vector4(region.position.x, region.position.y, region.size.x, region.size.y))
	material.set_shader_parameter("alpha_threshold", 0.22)
	material.set_shader_parameter("window_count", 0)
	material.set_shader_parameter("leaf_transmission", 0.0)
	material.set_shader_parameter("foliage_tone", texture.resource_path.contains("/foliage/"))
	material.set_shader_parameter("mip_bias", -0.25)
	material.set_shader_parameter("edge_inset", 0.35 if mountain_art else 0.65)
	material.set_shader_parameter("remove_pale_matte", false)
	if texture.resource_path.contains("/foliage/"):
		mesh.subdivide_width = 12
		mesh.subdivide_depth = 8
		material.set_shader_parameter("wind_strength", clampf(height * 0.026, 0.055, 0.24))
		material.set_shader_parameter("leaf_transmission", 0.10)
		# Keep the painted dark leaf masses after ACES and warm daylight. The
		# white/mint crown effect cannot be fixed by stronger depth-of-field blur.
		var far_foliage := 1.0 - smoothstep(-160.0, -65.0, foot.y)
		material.set_shader_parameter("art_contrast", lerpf(1.12, 1.26, far_foliage))
		material.set_shader_parameter("art_exposure", 0.72 if texture == BROAD_TREE else lerpf(0.80, 0.64, far_foliage))
	# Near props should respond to the real sun, sky fill and lamps. Reserve
	# substantial painted illumination for the independent distant matte art.
	material.set_shader_parameter("painted_fill", 0.88 if mountain_art else (0.60 if distant else 0.035))
	material.set_shader_parameter("relief_strength", 0.0 if distant else 0.38)
	CANOPY_PROFILES.apply_to(material, label)
	var instance := MeshInstance3D.new()
	instance.name = label
	instance.mesh = mesh
	instance.material_override = material
	instance.position = Vector3(foot.x, terrain_height(foot.x, foot.y) + sink, foot.y)
	instance.set_meta("art_foot", foot)
	instance.set_meta("art_width", width)
	instance.set_meta("art_height", height)
	instance.set_meta("art_anchor", anchor)
	var soil_bounds := Rect2(foot - Vector2(width * 0.5 + 2.0, width * 0.25 + 2.0), Vector2(width + 4.0, width * 0.5 + 4.0))
	var soil_heights := PackedFloat32Array()
	for row in range(5):
		for column in range(5):
			var p := soil_bounds.position + soil_bounds.size * Vector2(column / 4.0, row / 4.0)
			soil_heights.append(terrain_height(p.x, p.y))
	material.set_shader_parameter("soil_bounds", Vector4(soil_bounds.position.x, soil_bounds.position.y, soil_bounds.size.x, soil_bounds.size.y))
	material.set_shader_parameter("soil_heights", soil_heights)
	material.set_shader_parameter("root_contact", 0.0 if distant else 0.22)
	# Alpha-cutout silhouettes cast into the SAME sun shadow map as the terrain.
	# Only the distant painted skyline is excluded from local lighting/shadows.
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if distant else GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
	instance.extra_cull_margin = height
	add_child(instance)
	return instance

func _shadow(foot: Vector2, radius: Vector2) -> void:
	# A small root-contact term complements (not replaces) the projected silhouette.
	shadow_ellipses.append(Vector4(foot.x, foot.y, radius.x * 0.55, radius.y * 0.38))

func _report_render_metrics() -> void:
	render_metrics_samples += 1
	print("MEADOW_RENDER_METRICS: sample %d; %.0f fps; %d visible draw calls; %d visible primitives" % [
		render_metrics_samples, Engine.get_frames_per_second(), Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)])
	if render_metrics_samples < 3:
		get_tree().create_timer(5.0).timeout.connect(_report_render_metrics)

func _build_focus() -> void:
	var quad := QuadMesh.new()
	quad.size = Vector2(2, 2)
	var screen := MeshInstance3D.new()
	screen.name = "DepthAwareFocus"
	screen.layers = 4
	screen.mesh = quad
	screen.position.z = -0.5
	screen.extra_cull_margin = 1000.0
	screen.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	focus_material = ShaderMaterial.new()
	focus_material.shader = FOCUS_SHADER
	focus_material.set_shader_parameter("near_start", 16.0)
	focus_material.set_shader_parameter("near_end", 32.0)
	focus_material.set_shader_parameter("near_radius", 1.25)
	focus_material.set_shader_parameter("far_start", 300.0)
	focus_material.set_shader_parameter("far_end", 390.0)
	focus_material.set_shader_parameter("far_radius", 0.0)
	focus_material.render_priority = 126
	screen.material_override = focus_material
	camera.add_child(screen)

func _build_scale_guide() -> void:
	for i in range(WALK_POINTS.size() - 1):
		route_length += WALK_POINTS[i].distance_to(WALK_POINTS[i + 1])
	scale_guide = Node3D.new()
	scale_guide.name = "OptionalScaleGuide"
	scale_guide.visible = false
	add_child(scale_guide)
	var capsule := CapsuleMesh.new()
	capsule.height = PLAYER_HEIGHT
	capsule.radius = 0.30
	walker = MeshInstance3D.new()
	walker.name = "HumanScale_1_8m"
	walker.mesh = capsule
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.79, 0.19, 0.10)
	material.roughness = 0.8
	walker.material_override = material
	scale_guide.add_child(walker)
	# Ring vertices follow the same terrain as the future 8.4-metre combat clearing.
	var ring := ImmediateMesh.new()
	var ring_material := StandardMaterial3D.new()
	ring_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	ring_material.albedo_color = Color(1.0, 0.69, 0.25)
	ring.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, ring_material)
	for i in range(65):
		var angle := TAU * i / 64.0
		var x := 5.0 + cos(angle) * BOSS_ARENA_RADIUS
		var z := -12.0 + sin(angle) * BOSS_ARENA_RADIUS
		ring.surface_add_vertex(Vector3(x, terrain_height(x, z) + 0.07, z))
	ring.surface_end()
	var ring_instance := MeshInstance3D.new()
	ring_instance.mesh = ring
	scale_guide.add_child(ring_instance)

func _physics_process(delta: float) -> void:
	if not audit_complete:
		# Mark handled before calling diagnostics, including re-entry or failure.
		audit_complete = true
		if _startup_audit_enabled():
			_report_startup_audit("running")
			var audit_start_us := Time.get_ticks_usec()
			_audit_walk_surface()
			var audit_duration_ms := float(Time.get_ticks_usec() - audit_start_us) / 1000.0
			_report_startup_audit("completed", audit_duration_ms)
		else:
			_report_startup_audit("skipped", 0.0)
	if not scale_guide.visible:
		return
	travel = fmod(travel + delta * 1.5, 2.0 * route_length)
	var distance := travel if travel < route_length else 2.0 * route_length - travel
	var point := _point_on_route(distance)
	walker.position = Vector3(point.x, terrain_height(point.x, point.y) + PLAYER_HEIGHT * 0.5, point.y)

func _startup_audit_enabled() -> bool:
	# Custom CLI flags follow --; architecture_audit remains a separate audit.
	if OS.is_debug_build() or OS.get_cmdline_user_args().has("--startup-audit"):
		return true
	if OS.has_feature("web"):
		return bool(JavaScriptBridge.eval("new URLSearchParams(location.search).get('startup_audit') === '1'"))
	return false

func _report_startup_audit(status: String, duration_ms: float = -1.0) -> void:
	# Duration covers only _audit_walk_surface, not logging/bridge or scene build.
	print("MEADOW_STARTUP_AUDIT: status=%s duration_ms=%.3f" % [status, duration_ms])
	if not OS.has_feature("web"):
		return
	# Page-clock timestamps are separate from Godot ticks and loader elapsed time.
	# Write telemetry directly through the bridge; no shell callback/gate changes.
	JavaScriptBridge.eval("""(() => {
		const canvas = document.getElementById("canvas");
		if (!canvas) return;
		const data = canvas.dataset;
		const status = %s;
		const stamp = String(performance.now());
		data.startupAuditStatus = status;
		data.startupAuditEnabled = String(status === "running" || status === "completed");
		data.startupAuditDebugBuild = String(%s);
		// Observe backing-store pixels, never infer them from CSS or resize them.
		data.startupAuditCanvasWidth = String(canvas.width);
		data.startupAuditCanvasHeight = String(canvas.height);
		data.startupAuditDpr = Number.isFinite(window.devicePixelRatio) ? String(window.devicePixelRatio) : "unknown";
		if (status === "running") {
			data.startupAuditStartedAtMs = stamp;
			delete data.startupAuditFinishedAtMs;
			delete data.startupAuditMs;
			delete data.startupAuditElapsedMs;
		} else {
			data.startupAuditFinishedAtMs = stamp;
			data.startupAuditMs = String(%s);
			data.startupAuditElapsedMs = data.startupAuditMs;
			if (status === "skipped") delete data.startupAuditStartedAtMs;
		}
	})()""" % [JSON.stringify(status), JSON.stringify(OS.is_debug_build()), JSON.stringify(duration_ms)])

func _point_on_route(distance: float) -> Vector2:
	var point: Vector2 = WALK_POINTS[0]
	for i in range(WALK_POINTS.size() - 1):
		var start: Vector2 = WALK_POINTS[i]
		var finish: Vector2 = WALK_POINTS[i + 1]
		var length := start.distance_to(finish)
		point = start.lerp(finish, clampf(distance / length, 0.0, 1.0))
		if distance <= length:
			break
		distance -= length
	return point

func _audit_walk_surface() -> void:
	var hits := 0
	var max_error := 0.0
	for i in range(31):
		var point := _point_on_route(route_length * i / 30.0)
		var z := point.y
		var x := point.x
		var expected := terrain_height(x, z)
		var query := PhysicsRayQueryParameters3D.create(Vector3(x, expected + 5, z), Vector3(x, expected - 5, z))
		var result := get_world_3d().direct_space_state.intersect_ray(query)
		if not result.is_empty():
			hits += 1
			max_error = maxf(max_error, absf(result.position.y - expected))
			if absf(result.position.y - expected) > 0.05:
				print("MEADOW_ROUTE_OBSTRUCTION: probe %d at %s; expected %.3f / collision %.3f" % [i, point, expected, result.position.y])
	print("MEADOW_COLLISION_AUDIT: %d/31 grounded probes; max height error %.4f m" % [hits, max_error])
	assert(hits == 31 and max_error < 0.05, "Walking route must stay on the collision surface")
	var max_arena_error := 0.0
	var max_walk_slope := 0.0
	for i in range(65):
		var angle := TAU * i / 64.0
		var p := BOSS_CENTER + Vector2(cos(angle), sin(angle)) * BOSS_ARENA_RADIUS
		max_arena_error = maxf(max_arena_error, absf(terrain_height(p.x, p.y) - 0.12))
		var route_point := _point_on_route(route_length * i / 64.0)
		max_walk_slope = maxf(max_walk_slope, rad_to_deg(acos(terrain_normal(route_point.x, route_point.y).y)))
	print("MEADOW_PLAYSPACE_AUDIT: route max slope %.2f deg; Boss clearing height deviation %.4f m" % [max_walk_slope, max_arena_error])
	assert(max_walk_slope < 18.0 and max_arena_error < 0.02, "Keep the route gentle and the entire Boss clearing level")
	var near_foot := Vector3(0, terrain_height(0, 4), 4)
	var far_foot := Vector3(2, terrain_height(2, -39), -39)
	var near_pixels := camera.unproject_position(near_foot).distance_to(camera.unproject_position(near_foot + Vector3.UP * PLAYER_HEIGHT))
	var far_pixels := camera.unproject_position(far_foot).distance_to(camera.unproject_position(far_foot + Vector3.UP * PLAYER_HEIGHT))
	print("MEADOW_SCALE_AUDIT: 1.8m actor near=%.1fpx / far=%.1fpx; arena diameter=%.1fm" % [near_pixels, far_pixels, BOSS_ARENA_RADIUS * 2.0])
	_audit_composition()
	_audit_bridge_surface()
	_audit_horizon_ground()
	_audit_frame_roots()

func _audit_frame_roots() -> void:
	ROAD_LIGHTS.audit(self)
	FENCE_BUILDER.audit(self)
	_audit_supported_roots(["RoadsideGrass", "TrailLantern"], "MEADOW_FOREGROUND_ROOT_AUDIT")
	_audit_supported_roots(["LeftFrameOak", "HazelAboveLimestone", "DeepValleyHawthorn", "FloweredTerraceToe"], "MEADOW_FRAME_ROOT_AUDIT")
	_audit_supported_roots(["MeadowColony_00", "MeadowColony_01", "MeadowColony_02", "MeadowColony_03"], "MEADOW_COLONY_ROOT_AUDIT")
	_audit_supported_roots(["OakOnLowerOutcrop", "YoungOakByVillage", "OldOakOnShelf", "YoungHawthornInValley"], "MEADOW_CANOPY_ROOT_AUDIT")

func _audit_supported_roots(names: Array, tag: String) -> void:
	var hits := 0
	var max_error := 0.0
	for label: String in names:
		var plant: MeshInstance3D = get_node(NodePath(label))
		var p := plant.position
		var expected := terrain_height(p.x, p.z)
		# Start above the complete escarpment, never from inside a protruding rock.
		var ray := PhysicsRayQueryParameters3D.create(Vector3(p.x, expected + 8.0, p.z), Vector3(p.x, expected - 3.0, p.z))
		var result := get_world_3d().direct_space_state.intersect_ray(ray)
		if not result.is_empty():
			var error: float = absf(result.position.y - expected)
			max_error = maxf(max_error, error)
			if error < 0.075:
				hits += 1
			else:
				print("%s_MISMATCH: %s %.4f m" % [tag, label, error])
	print("%s: %d/%d supported root anchors; max error %.4f m" % [tag, hits, names.size(), max_error])
	assert(hits == names.size(), "New framing plants must stand on the actual collision surface")

func _audit_horizon_ground() -> void:
	CITY_BUILDER.audit(self)
	VILLAGE_BUILDER.audit(self)
	SETTLEMENT_LIGHTS.audit(self)
	var points := [Vector2(-132, -247), Vector2(0, -279), Vector2(132, -315), Vector2(0, MIN_Z)]
	var hits := 0
	for p: Vector2 in points:
		var expected := terrain_height(p.x, p.y)
		var ray := PhysicsRayQueryParameters3D.create(Vector3(p.x, expected + 2, p.y), Vector3(p.x, expected - 2, p.y))
		var result := get_world_3d().direct_space_state.intersect_ray(ray)
		if not result.is_empty() and absf(result.position.y - expected) < 0.05:
			hits += 1
	print("MEADOW_HORIZON_GROUND_AUDIT: %d/4 supported distant terrain probes; solid ground reaches -327 m" % hits)
	assert(hits == points.size(), "Distant cut-out silhouettes need continuous real terrain underneath")

func _audit_bridge_surface() -> void:
	var bridge: MeshInstance3D = $SmallMeadowFootbridge
	var left: float = bridge.get_meta("left_x")
	var right: float = bridge.get_meta("right_x")
	var base: float = bridge.get_meta("deck_y")
	var hits := 0
	var max_error := 0.0
	for i in range(9):
		var t := (i + 0.5) / 9.0
		var x := lerpf(left, right, t)
		var expected := base + 0.42 * sin(t * PI)
		var query := PhysicsRayQueryParameters3D.create(Vector3(x, expected + 2, BRIDGE_Z), Vector3(x, -2.0, BRIDGE_Z))
		var result := get_world_3d().direct_space_state.intersect_ray(query)
		if not result.is_empty() and absf(result.position.y - expected) < 0.055:
			hits += 1
			max_error = maxf(max_error, absf(result.position.y - expected))
	print("MEADOW_BRIDGE_AUDIT: %d/9 supported deck probes; max height error %.4f m" % [hits, max_error])
	assert(hits == 9, "The bridge must be solid under a future walking character")
	var entry_hits := 0
	var entry_probe_count := 0
	var max_entry_error := 0.0
	var max_entry_slope := 0.0
	for entry: Dictionary in bridge.get_meta("entries"):
		var end_x: float = entry.start_x
		var ground_x: float = entry.ground_x
		var ground_y: float = entry.ground_y
		var boards: int = entry.boards
		max_entry_slope = maxf(max_entry_slope, rad_to_deg(atan(absf(base - ground_y) / absf(ground_x - end_x))))
		for i in range(boards):
			entry_probe_count += 1
			var t := (i + 0.5) / float(boards)
			var x := lerpf(end_x, ground_x, t)
			var expected := maxf(lerpf(base, ground_y, t), terrain_height(x, BRIDGE_Z))
			var query := PhysicsRayQueryParameters3D.create(Vector3(x, expected + 1.0, BRIDGE_Z), Vector3(x, expected - 2.0, BRIDGE_Z))
			var result := get_world_3d().direct_space_state.intersect_ray(query)
			if not result.is_empty() and absf(result.position.y - expected) < 0.055:
				entry_hits += 1
				max_entry_error = maxf(max_entry_error, absf(result.position.y - expected))
	print("MEADOW_BRIDGE_ENTRY_AUDIT: %d/%d supported entry probes; max error %.4f m; grade %.2f deg" % [entry_hits, entry_probe_count, max_entry_error, max_entry_slope])
	assert(entry_hits == entry_probe_count and entry_probe_count > 0 and max_entry_slope < 18.0, "Both relocated bridge entries must meet walkable ground")

func _audit_composition() -> void:
	# Normalized landmarks measured from the user's 2560x1600 reference. These
	# constrain framing only; they are NOT an automatic test of artistic fidelity.
	var size := get_viewport().get_visible_rect().size
	var fork := Vector3(ROAD_FORK[1].x, terrain_height(ROAD_FORK[1].x, ROAD_FORK[1].y), ROAD_FORK[1].y)
	var mountain := _card_point($DistantMountainRidge, Vector2(0.244, 0.275))
	var castle := _card_point($IndependentCastleHill, CASTLE_PEAK_UV)
	var river := Vector3(river_center(-34.0), -1.05, -34.0)
	var landmarks := [fork, mountain, castle, river]
	var targets := [Vector2(0.42, 0.60), Vector2(0.08, 0.08), Vector2(0.70, 0.06), Vector2(0.80, 0.49)]
	var names := ["trail_fork", "left_mountain_peak", "castle_spire", "river_bend"]
	landmarks.append_array([$OakOnLowerOutcrop.global_position, $YoungOakByVillage.global_position,
		$OldOakOnShelf.global_position, $YoungHawthornInValley.global_position])
	targets.append_array([Vector2(0.06, 0.395), Vector2(0.20, 0.305), Vector2(0.242, 0.381), Vector2(0.51, 0.349)])
	names.append_array(["left_oak_root", "village_oak_root", "left_maple_root", "valley_hawthorn_root"])
	landmarks.append($TrailLantern.global_position)
	targets.append(Vector2(0.236, 0.672))
	names.append("foreground_lantern_root")
	var rim_targets := [Vector2(0.02, 0.705), Vector2(0.20, 0.815), Vector2(0.42, 0.910), Vector2(0.64, 0.965)]
	for index in range(4):
		var x: float = FOREGROUND_RIM[index + 1].x
		var z := foreground_edge(x) - 0.8
		landmarks.append(Vector3(x, terrain_height(x, z), z))
		targets.append(rim_targets[index])
		names.append("foreground_crest_%d" % index)
	for i in range(landmarks.size()):
		var screen := camera.unproject_position(landmarks[i]) / size
		print("MEADOW_COMPOSITION_AUDIT: %s normalized=(%.3f, %.3f); reference=(%.2f, %.2f)" % [names[i], screen.x, screen.y, targets[i].x, targets[i].y])
		var tolerance := 0.065 if i < 4 else 0.025
		assert(screen.distance_to(targets[i]) < tolerance, "Reference composition landmark drifted: " + names[i])

func _card_point(card: MeshInstance3D, uv: Vector2) -> Vector3:
	if card.name == "IndependentCastleHill":
		return CITY_BUILDER.mesh_point(card, uv)
	if card.name in ["DistantMountainRidge", "RightMountainRidge"] and card.mesh is ArrayMesh:
		return MOUNTAIN_RELIEF.mesh_point(card, uv)
	var quad: QuadMesh = card.mesh
	return card.to_global(quad.center_offset + Vector3((uv.x - 0.5) * quad.size.x, (0.5 - uv.y) * quad.size.y, 0))

func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_D:
				focus_enabled = not focus_enabled
				focus_material.set_shader_parameter("enabled", focus_enabled)
			KEY_G:
				focus_material.set_shader_parameter("show_depth", not bool(focus_material.get_shader_parameter("show_depth")))
			KEY_C:
				scale_guide.visible = not scale_guide.visible
				if scale_guide.visible:
					travel = 22.0

static func _array_mesh(vertices: PackedVector3Array, normals: PackedVector3Array,
		uvs: PackedVector2Array, indices: PackedInt32Array, uv2s: PackedVector2Array = PackedVector2Array()) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	if not uv2s.is_empty():
		arrays[Mesh.ARRAY_TEX_UV2] = uv2s
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
