extends SceneTree
## One actual cached main, headless only. No file writes, GPU crops or geometry suite.
const MAIN = preload("res://scenes/main.tscn")
const GROUND = preload("res://scripts/meadow_ground_atmosphere.gd")
const GROVES = preload("res://scripts/meadow_mountain_groves.gd")
const WEATHER = preload("res://scripts/meadow_weather.gd")
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const AO = preload("res://scripts/meadow_rock_occlusion.gd")
const SWARD = preload("res://scripts/meadow_far_sward.gd")
const SWARD_CACHE_SHA := "308f3998727c0393a550f886cad691fdb761e4aad7d12cf9e2d47dcbd3091b92"
const CACHE_SIGNATURE := "d6edc82e3af84d52d155bb6f9d5e58dab057f3563984e438e8b11530ed634233"
const CACHE_PINS := {
	"res://assets/baked/v77/terrain.scn": "b44e2c8c33fe4369d872fcb6ad3aa74180aac5463f18ae2eaadfb07ea4fc2771",
	"res://assets/baked/v77/detail.scn": "46b397bf8a09a712ce94f520874952ab7c048e6e7a1dc78e1c3fa6198700fff8",
	"res://assets/baked/v77/foothill.scn": "089a44e1d190655001c796c68514460d60be87b8ffee05f7efb2f9ec11f47ff5",
	"res://assets/baked/v77/riverbank.scn": "979645039620c041e4f65a62b33eb7419811b8cfd959106ceb4da99a42994627",
	"res://assets/baked/v77/brush.scn": "b7e2627dc8bb1786530c5caf9fef99ba102d3cee4fea30e355fcb94f763befd9",
	"res://assets/baked/v110/rock-occlusion.bin": "f3f86ff17ed6da347d7fa155562b3ca4048bac04b52eebf560aa3d8113371577"}
const PROTECTED := {
	"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08",
	"res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b",
	"res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d",
	"res://scripts/meadow_weather.gd": "7afda1a94783bf28b48f860fa6a174220cc63a387d14ea094b16953c8ae4d5c9"}
var scene: Node3D
var weather: Node
var ground_bridge: Node
var grove_bridge: Node
var environment: Environment
var ground: ShaderMaterial
var ground_card: MeshInstance3D
var camera: Camera3D
var camera_state: Array = []
var cards: Array[MeshInstance3D] = []
var materials: Array[ShaderMaterial] = []
var originals: Array[Dictionary] = []
var grove_native: Array[Dictionary] = []
var sward_cached_hash := ""
var sward_measurements := {}
var foreground := {}
var ground_parameters := {}
var hashes := {}
var records: Array[Dictionary] = []
var checks := 0
var failures := 0
var finished := false

func _initialize() -> void:
	root.disable_3d = true
	root.size = Vector2i(2304, 1440)
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failures += 1
		push_error("FAR_FIELD_SCENE: " + label)
	return value

func _preflight() -> bool:
	if not _ok(DisplayServer.get_name() == "headless" and not OS.has_feature("web"), "Requires standalone --headless; no browser/user persistent UI"): return false
	if not _ok(OS.get_cmdline_user_args().is_empty(), "No bake/other opt-in arguments accepted"): return false
	for path: String in PROTECTED:
		_ok(FileAccess.get_sha256(path) == PROTECTED[path], "Protected source " + path)
	var signature: String = CACHE.signature()
	_ok(signature == CACHE_SIGNATURE, "Original five-cache geometry source signature; additive sidecar separate")
	for path: String in CACHE_PINS:
		_ok(FileAccess.get_sha256(path) == CACHE_PINS[path], "v112 normalized cache/AO exact " + path)
	if failures != 0: return false
	for group: String in CACHE.GROUPS:
		var path: String = CACHE.DIRECTORY + group + ".scn"
		hashes[path] = FileAccess.get_sha256(path)
		var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
		if not _ok(packed != null and not str(hashes[path]).is_empty(), "Cached group exists " + group): return false
		var state := packed.get_state()
		var metadata := {}
		for i in range(state.get_node_property_count(0)):
			metadata[str(state.get_node_property_name(0, i))] = state.get_node_property_value(0, i)
		_ok(metadata.get("metadata/cache_version") == CACHE.VERSION and metadata.get("metadata/source_signature") == signature, "Fresh cached group; refuse procedural fallback " + group)
	for path: String in [AO.DATA_PATH, "res://scenes/main.tscn", "res://scripts/meadow_scene.gd", "res://scripts/meadow_ground_atmosphere.gd", "res://scripts/meadow_mountain_groves.gd", "res://shaders/meadow_ground.gdshader", "res://shaders/meadow_ground_day.gdshader", "res://shaders/meadow_ground_surface.gdshaderinc", "res://shaders/meadow_grove_day.gdshader", "res://shaders/meadow_grove_fog.gdshaderinc"]:
		hashes[path] = FileAccess.get_sha256(path)
		_ok(not str(hashes[path]).is_empty(), "Required runtime source/data " + path)
	for path: String in [SWARD.CACHE_PATH, SWARD.SOURCE_PATH, "res://scripts/meadow_branch_geometry.gd", "res://shaders/meadow_far_ground.gdshaderinc", "res://shaders/meadow_leaves.gdshader", "res://shaders/meadow_surface.gdshaderinc", "res://shaders/meadow_palette.gdshaderinc", "res://shaders/meadow_sunbreak.gdshaderinc"]:
		hashes[path] = FileAccess.get_sha256(path)
		if not _ok(not str(hashes[path]).is_empty(), "Sward cache/dependency exists; no procedural fallback " + path): return false
	var sward_pack := load(SWARD.CACHE_PATH) as PackedScene
	if not _ok(hashes[SWARD.CACHE_PATH] == SWARD_CACHE_SHA, "Frozen v113 sidecar bake file"): return false
	if not _ok(sward_pack != null, "Prebuilt sward PackedScene"): return false
	var cached := sward_pack.instantiate() as MeshInstance3D
	if not _ok(cached != null, "Cached sward MeshInstance3D"): return false
	_ok(cached.get_meta("cache_revision", "") == SWARD.CACHE_REVISION and cached.get_meta("source_sha256", "") == hashes[SWARD.SOURCE_PATH] and cached.get_meta("terrain_sha256", "") == CACHE_PINS[SWARD.TERRAIN_PATH], "Current independent sidecar revision/source/terrain binding")
	if _ok(cached.mesh != null and cached.mesh.get_surface_count() == 1, "Sward cache actual single-surface mesh"):
		sward_cached_hash = _array_hash(cached.mesh.surface_get_arrays(0))
	cached.free()
	return failures == 0

func _array_hash(value: Variant) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(var_to_bytes(value))
	return hash.finish().hex_encode()

func _node(path: String) -> Node:
	var node := scene.get_node_or_null(NodePath(path))
	_ok(node != null, "Required actual node " + path)
	return node

func _parameters(material: ShaderMaterial, shader: Shader) -> Dictionary:
	var values := {}
	for uniform: Dictionary in shader.get_shader_uniform_list():
		var key := str(uniform.name)
		var value: Variant = material.get_shader_parameter(key)
		# Nil is an unset override, not false/zero. Resolve only through actual native defaults.
		if value == null: value = RenderingServer.shader_get_parameter_default(shader.get_rid(), key)
		values[key] = value
	_ok(not values.is_empty(), "Actual native uniform schema exposed")
	return values.duplicate(true)

func _equal_parameters(actual: Dictionary, expected: Dictionary, label: String) -> void:
	_ok(actual.size() == expected.size(), label + " uniform count")
	for key: String in expected:
		if not _ok(actual.get(key) == expected[key], label + "/" + key):
			print("FAR_FIELD_SCENE_PARAM_DIFF: ", label, "/", key, "; before(type=", typeof(expected[key]), ") ", var_to_str(expected[key]), "; after(type=", typeof(actual.get(key)), ") ", var_to_str(actual.get(key)))

func _capture() -> bool:
	weather = _node("LivingWeather")
	ground_bridge = _node("GroundAtmosphere")
	grove_bridge = _node("GroveAtmosphere")
	var world := _node("WorldEnvironment") as WorldEnvironment
	var mesh := _node("ContinuousMeadow") as MeshInstance3D
	var rock := _node("SolidLimestoneGeology")
	camera = _node("Camera3D") as Camera3D
	if weather == null or ground_bridge == null or grove_bridge == null or world == null or mesh == null or rock == null: return false
	if camera == null: return false
	ground_card = mesh
	camera_state = _camera_state()
	_ok(camera.position == Vector3(0, 18, 39) and camera.projection == Camera3D.PROJECTION_PERSPECTIVE and camera.fov == 48.0 and is_equal_approx(camera.near, .1) and camera.far == 560.0, "Established actual camera framing")
	environment = world.environment
	ground = scene.get("ground_material") as ShaderMaterial
	if not _ok(environment != null and ground != null and ground == mesh.material_override, "Actual ground material binding/environment"): return false
	_ok(ground_bridge.get_script() == GROUND and ground_bridge.get("meadow") == scene, "Ground runtime identity guard accepted actual cache")
	_ok(not ground_bridge.get("rebuilding_static") and ground_bridge.is_processing(), "Ground runtime enabled, not bake skip")
	_ok(weather.get_script() == WEATHER and grove_bridge is GROVES.Atmosphere, "Actual weather/grove implementations")
	_ok(rock.has_meta("rock_occlusion_applied"), "Main actually applied current cached AO")
	var registered: Dictionary = grove_bridge.get("registered")
	var actual_materials: Array = grove_bridge.get("materials")
	_ok(registered.size() == 12 and actual_materials.size() == 12, "Exactly 12 real registered far materials")
	var identities := {}
	for family: String in ["UniqueWoodlandBelt_", "MountainGrove_"]:
		for i in range(6):
			var card := _node(family + "%02d" % i) as MeshInstance3D
			if card == null: return false
			var material := card.material_override as ShaderMaterial
			if not _ok(material != null, "Actual grove ShaderMaterial"): return false
			_ok(registered.has(card.get_instance_id()) and actual_materials.has(material), "Registration matches actual card " + str(card.name))
			_ok(not identities.has(material.get_instance_id()), "Independent grove material " + str(card.name))
			identities[material.get_instance_id()] = true
			cards.append(card)
			materials.append(material)
			originals.append(_parameters(material, GROVES.NATIVE_SHADER))
			# The independent fixture verifies registration against untouched sources.
			# Here retain the actual saved native profile, not the already-applied day values.
			var at := actual_materials.find(material)
			var profiles: Array = grove_bridge.get("day_profiles")
			if not _ok(at >= 0 and at < profiles.size(), "Saved per-card native profile"): return false
			var profile: Dictionary = profiles[at]
			grove_native.append({"tint": profile.tint, "painted_fill": profile.fill, "relief_strength": profile.relief, "root_contact": profile.contact})
	for i in [6, 7]:
		var card := _node("UniqueWoodlandBelt_%02d" % i) as MeshInstance3D
		if card == null: return false
		var material := card.material_override as ShaderMaterial
		if not _ok(material != null and material.shader == GROVES.NATIVE_SHADER, "Foreground remains canonical native"): return false
		_ok(not registered.has(card.get_instance_id()) and not actual_materials.has(material), "Foreground excluded from registration")
		foreground[card] = {"material": material, "shader": material.shader, "mesh": card.mesh, "transform": card.transform, "layers": card.layers, "parameters": _parameters(material, GROVES.NATIVE_SHADER)}
	ground_parameters = _parameters(ground, GROUND.ORIGINAL_SHADER)
	return failures == 0

func _grove_expected(index: int, night: float) -> Dictionary:
	var result := originals[index].duplicate(true)
	var base: Dictionary = grove_native[index]
	var day := 1.0 - night
	var tint: Color = base.tint
	var gain := Color(.97, 1, .94) if index < 6 else Color(.90, .98, 1)
	result.tint = tint.lerp(tint * gain, day) if day > 0.0 else tint
	for pair: Array in [["painted_fill", .08], ["relief_strength", .22], ["root_contact", .38]]:
		result[pair[0]] = lerpf(base[pair[0]], pair[1], day) if day > 0.0 else base[pair[0]]
	return result

func _fog(material: ShaderMaterial, prefix: String, label: String) -> void:
	var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
	_ok(material.get_shader_parameter(prefix + "_fog_enabled") == environment.fog_enabled, label + " actual fog enabled")
	_ok(material.get_shader_parameter(prefix + "_fog_density") == environment.fog_density, label + " actual fog density")
	_ok(material.get_shader_parameter(prefix + "_fog_linear_color") == Vector3(linear.r, linear.g, linear.b), label + " actual fog colour converted once")

func _camera_state() -> Array:
	return [camera.transform, camera.projection, camera.fov, camera.size, camera.near, camera.far, camera.keep_aspect, camera.h_offset, camera.v_offset, camera.frustum_offset, camera.cull_mask]

func _single_pass(card: MeshInstance3D, material: ShaderMaterial, label: String) -> void:
	# Current production contract is one wrapper, not an additional render pass.
	_ok(card.material_override == material and material.next_pass == null and card.material_overlay == null, label + " single pass; no untested next_pass/overlay")

func _stage(label: String, night: float) -> bool:
	_ok(_camera_state() == camera_state, label + " camera placement/projection unchanged")
	_ok(weather.get("night_blend") == night, label + " actual weather endpoint")
	_ok(GROUND.supports_environment(environment), label + " supported actual environment")
	_ok(is_equal_approx(environment.fog_density, lerpf(.00042, .00048, night)), label + " original weather fog curve")
	_ok(environment.fog_light_color.is_equal_approx(Color(.54, .69, .82).lerp(Color(.26, .34, .47), night)), label + " original weather colour curve")
	var target: Shader = GROUND.ORIGINAL_SHADER if night == 1.0 else GROUND.day_shader
	_ok(scene.get("ground_material") == ground and ground.shader == target, label + " ground shader OBJECT identity (not just code/path)")
	_single_pass(ground_card, ground, label + "/ground")
	_equal_parameters(_parameters(ground, GROUND.ORIGINAL_SHADER), ground_parameters, label + "/ground")
	if night < 1.0: _fog(ground, "far_ground", label + "/ground")
	for i in range(materials.size()):
		var material := materials[i]
		_single_pass(cards[i], material, label + "/" + str(cards[i].name))
		_ok(cards[i].material_override == material, label + " stable grove material identity")
		_ok(material.shader == (GROVES.NATIVE_SHADER if night == 1.0 else GROVES.DAY_SHADER), label + " grove shader OBJECT identity")
		_equal_parameters(_parameters(material, GROVES.NATIVE_SHADER), _grove_expected(i, night), label + "/" + str(cards[i].name))
		if night < 1.0: _fog(material, "grove", label + "/" + str(cards[i].name))
	for card: MeshInstance3D in foreground:
		var before: Dictionary = foreground[card]
		var material: ShaderMaterial = before.material
		_single_pass(card, material, label + "/foreground")
		_ok(card.material_override == material and material.shader == before.shader and card.mesh == before.mesh and card.transform == before.transform and card.layers == before.layers, label + " foreground 06/07 binding/placement unchanged")
		_equal_parameters(_parameters(material, GROVES.NATIVE_SHADER), before.parameters, label + "/" + str(card.name))
	records.append({"stage": label, "night": night, "ground_shader": ground.shader.resource_path, "fog_density": environment.fog_density, "fog_colour": var_to_str(environment.fog_light_color), "registered": materials.size(), "protected_foreground": foreground.size()})
	print("FAR_FIELD_SCENE_STAGE: ", JSON.stringify(records.back()))
	return failures == 0

func _transition(delta: float) -> void:
	weather.call("advance_weather", delta)
	# Exercise actual instance callbacks including their state caches/identity guards.
	ground_bridge.call("_process", 0.0)
	grove_bridge.call("_process", 0.0)

func _run() -> void:
	create_timer(120.0).timeout.connect(func():
		if not finished:
			push_error("FAR_FIELD_SCENE: incomplete/timeout")
			quit(1))
	if not _preflight():
		_finish(false)
		return
	scene = MAIN.instantiate() as Node3D
	if not _ok(scene != null, "Instantiate main once"):
		_finish(false)
		return
	root.add_child(scene)
	var actual_weather := scene.get_node_or_null("LivingWeather")
	if not _ok(scene.is_node_ready() and actual_weather != null, "Actual main ready completed"):
		_finish(false)
		return
	actual_weather.call("set_motion", false)
	await process_frame
	await process_frame # Let priority-2 bridges perform natural startup synchronization.
	var captured: Variant = _capture()
	if captured != true:
		_finish(false)
		return
	scene.process_mode = Node.PROCESS_MODE_DISABLED
	var initial: Variant = _stage("startup_day", 0.0)
	var sward_complete: Variant = _sward_geometry()
	if initial != true or sward_complete != true:
		_finish(false)
		return
	weather.call("toggle_time")
	_transition(WEATHER.TRANSITION_SECONDS * .5)
	var half: Variant = _stage("half", .5)
	_transition(WEATHER.TRANSITION_SECONDS * .5)
	var night: Variant = _stage("night1_native", 1.0)
	weather.call("toggle_time")
	_transition(WEATHER.TRANSITION_SECONDS)
	var returned: Variant = _stage("return_day", 0.0)
	_finish(half == true and night == true and returned == true and records.size() == 4)

func _finish(complete: bool) -> void:
	for path: String in hashes: _ok(FileAccess.get_sha256(path) == hashes[path], "Read-only cache/AO/source " + path)
	for path: String in PROTECTED: _ok(FileAccess.get_sha256(path) == PROTECTED[path], "Protected source unchanged " + path)
	if is_instance_valid(scene): scene.free()
	finished = true
	print("FAR_FIELD_SCENE_AUDIT: ", "PASS" if complete and failures == 0 else "FAIL", "; ", JSON.stringify({"checks": checks, "failures": failures, "stages": records, "sward": sward_measurements, "source_hashes": hashes, "limits": "Actual ready/cache/helper plus bounded additive sward geometry only; no GPU pixels, full-world geometry/collision equivalence, pack verification or visual/performance acceptance. Any engine ERROR also vetoes acceptance."}))
	quit(0 if complete and failures == 0 else 1)

func _sward_geometry() -> bool:
	var started := Time.get_ticks_msec()
	var found := scene.find_children("DistantMeadowSward*", "MeshInstance3D", true, false)
	if not _ok(found.size() == 1, "One actual sward node"): return false
	var card := found[0] as MeshInstance3D
	var material := card.material_override as ShaderMaterial
	if not _ok(card.name == SWARD.LABEL and card.get_parent() == scene and card.transform == Transform3D.IDENTITY and card.get_child_count() == 0, "Sward identity placement, no child/collider"): return false
	if not _ok(card.mesh is ArrayMesh and card.mesh.get_surface_count() == 1 and card.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES and material != null, "One sward triangle surface/material"): return false
	_single_pass(card, material, "sward")
	_ok(material.shader == SWARD.LEAVES and material.get_shader_parameter("far_sward") == true and material.get_shader_parameter("meadow_texture") == SWARD.TURF, "Actual leaf shader/far gate/ground texture")
	_ok(card.layers == 8 and card.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF, "Sward layer8, no tiny shadow passes")
	var probe := _node("RiverSurroundingsReflection") as ReflectionProbe
	if probe == null: return false
	_ok((probe.cull_mask & card.layers) == 0, "Actual water reflection excludes sward layer")
	var arrays := card.mesh.surface_get_arrays(0)
	_ok(_array_hash(arrays) == sward_cached_hash, "Actual loaded geometry equals pre-main sidecar arrays")
	if not _ok(arrays[Mesh.ARRAY_INDEX] == null or arrays[Mesh.ARRAY_INDEX].is_empty(), "Declared unindexed corner-range protocol"): return false
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var uv2: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV2]
	if not _ok(vertices.size() > 0 and vertices.size() % 3 == 0 and vertices.size() / 3 <= 80000 and card.get_meta("triangle_budget", 0) == 80000, "Actual <=80000 triangles, not just metadata"): return false
	if not _ok(normals.size() == vertices.size() and colours.size() == vertices.size() and uv.size() == vertices.size() and uv2.size() == vertices.size(), "All leaf channels complete"): return false
	for pair: Array in [["ground_roots", TYPE_PACKED_VECTOR3_ARRAY], ["root_ranges", TYPE_PACKED_VECTOR2_ARRAY], ["colony_ranges", TYPE_PACKED_VECTOR2_ARRAY], ["root_heights", TYPE_PACKED_FLOAT32_ARRAY]]:
		if not _ok(typeof(card.get_meta(pair[0], null)) == pair[1], "Actual sward metadata type " + str(pair[0])): return false
	var roots: PackedVector3Array = card.get_meta("ground_roots")
	var ranges: PackedVector2Array = card.get_meta("root_ranges")
	var colonies: PackedVector2Array = card.get_meta("colony_ranges")
	var heights: PackedFloat32Array = card.get_meta("root_heights")
	if not _ok(not roots.is_empty() and roots.size() == ranges.size() and roots.size() == heights.size(), "Nonempty parallel root records"): return false
	var covered := 0
	for colony: Vector2 in colonies:
		if not _ok(colony.is_finite() and colony.x == covered and colony.y >= 1 and colony.y == int(colony.y), "Contiguous integral colony-to-root ranges"): return false
		covered += int(colony.y)
	if not _ok(covered == roots.size(), "Colonies cover each actual tuft once"): return false
	if not _ok(ground_card.transform == Transform3D.IDENTITY, "Ground ray coordinate space identity"): return false
	var soil := ground_card.mesh.generate_triangle_mesh() # One BVH, 2165 rays, no procedural terrain.
	if not _ok(soil != null, "Actual cached terrain TriangleMesh"): return false
	var max_root_error := 0.0
	var max_reach := 0.0
	var min_road := INF
	var min_water := INF
	var min_boss := INF
	var min_height := INF
	var max_height := 0.0
	var cursor := 0
	for i in range(roots.size()):
		var root_point := roots[i]
		var span := ranges[i]
		if not _ok(root_point.is_finite() and span == Vector2(cursor, 72) and cursor + 72 <= vertices.size(), "Four actual 18-corner leaf fans per root"): return false
		var hit := soil.intersect_ray(Vector3(root_point.x, 60, root_point.z), Vector3.DOWN)
		if not _ok(not hit.is_empty(), "Sward root hits actual triangle soil"): return false
		var error := root_point.distance_to(hit.position)
		max_root_error = maxf(max_root_error, error)
		_ok(error <= .02 and absf(root_point.y - Vector3(hit.position).y - .005) <= .00002, "Actual root +.005m, error <=.02m")
		_ok(root_point.z >= -216 and root_point.z <= -89 and Vector3(hit.position).y >= -.04 and Vector3(hit.normal).y >= .89, "Declared dry/root slope and Z envelope")
		var reach := 0.0
		var height := 0.0
		var channels_valid := true
		for j in range(cursor, cursor + 72):
			var p := vertices[j]
			channels_valid = channels_valid and p.is_finite() and normals[j].is_finite() and absf(normals[j].length() - 1) <= .002 and uv[j].is_finite() and uv2[j].is_finite() and Vector4(colours[j].r, colours[j].g, colours[j].b, colours[j].a).is_finite() and colours[j].a >= 0 and colours[j].a <= .651
			reach = maxf(reach, Vector2(p.x - root_point.x, p.z - root_point.z).length())
			height = maxf(height, p.y - root_point.y)
			channels_valid = channels_valid and p.y >= root_point.y - .00002 and uv[j].distance_to(Vector2(p.x, p.z)) <= .00002
		_ok(channels_valid, "Finite/unit leaf channels; actual world UV and no below-root blade")
		for leaf in range(4):
			var base := cursor + leaf * 18
			_ok(vertices[base].distance_to(root_point) <= .00002 and colours[base].a == 0, "Real fan base registered to root and pinned against wind")
			for triangle in range(6):
				var at := base + triangle * 3
				var cross := (vertices[at + 1] - vertices[at]).cross(vertices[at + 2] - vertices[at])
				_ok(cross.length_squared() > 1e-12 and cross.dot(normals[at] + normals[at + 1] + normals[at + 2]) < 0, "Nondegenerate clockwise actual leaf fan")
		var nominal := heights[i]
		_ok(is_finite(nominal) and nominal >= .28 - .00001 and nominal <= .82 + .00001 and height >= nominal * .65 - .00002 and height <= nominal + .00002, "Measured actual leaf height agrees with declared source range")
		# .06 conservatively covers actual leaf shader's .055 sinusoidal X/Z wind.
		var envelope := reach + .06
		var p := Vector2(root_point.x, root_point.z)
		var road: float = scene.distance_to_road(p) - scene.road_half_width(p.y) - envelope
		var water: float = absf(p.x - scene.river_center(p.y)) - scene.river_water_half_width(p.y) - envelope
		var boss: float = p.distance_to(scene.BOSS_CENTER) - scene.BOSS_ARENA_RADIUS - envelope
		_ok(road >= 3 and water >= 7 and boss > 0 and envelope <= 1.2, "Actual tuft reach+wind exclusion: road3/water7/Boss outside")
		min_road = minf(min_road, road)
		min_water = minf(min_water, water)
		min_boss = minf(min_boss, boss)
		max_reach = maxf(max_reach, reach)
		min_height = minf(min_height, height)
		max_height = maxf(max_height, height)
		cursor += 72
	_ok(cursor == vertices.size(), "Root ranges cover ALL actual mesh corners")
	sward_measurements = {"tufts": roots.size(), "colonies": colonies.size(), "triangles": vertices.size() / 3, "root_error_max_m": max_root_error, "actual_height_min_max_m": [min_height, max_height], "actual_reach_max_m": max_reach, "root_cross_section_clearance_after_reach_and_wind_m": {"road": min_road, "water": min_water, "boss": min_boss}, "audit_ms": Time.get_ticks_msec() - started, "limits": "Root/tuft envelope versus declared road/water profile; not exact Euclidean distance to every curved water-edge triangle or GPU visual/draw-count evidence"}
	print("FAR_SWARD_GEOMETRY: ", JSON.stringify(sward_measurements))
	return failures == 0
