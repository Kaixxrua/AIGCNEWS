extends SceneTree
## Narrow real-helper fixture; no main/cache/AO/build. Default: headless state
## checks. Pass --GPU after -- with a native renderer for ten private GPU crops.
const GROVES = preload("res://scripts/meadow_mountain_groves.gd")
const GROUND = preload("res://scripts/meadow_ground_atmosphere.gd")
const PIXEL_EPS := 1.0 / 255.0 + 0.0000001 # One code plus float32 readback rounding only.
const PROTECTED := {"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08", "res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b", "res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d", "res://scripts/meadow_weather.gd": "7afda1a94783bf28b48f860fa6a174220cc63a387d14ea094b16953c8ae4d5c9"}
class WeatherFixture extends Node:
	var night_blend := 0.0
var fixture: Node3D
var world: WorldEnvironment
var weather: WeatherFixture
var bridge: GROVES.Atmosphere
var cards: Array[MeshInstance3D] = []
var originals: Array[ShaderMaterial] = []
var expected: Array[Dictionary] = []
var identities: Array[int] = []
var source_hashes := {}
var checks := 0
var failures := 0
var stages := 0
var ground_stages := 0
var gpu_records: Array = []
var gpu_view: SubViewport
var finished := false
var uniform_schemas := {}
var parameter_diff_counts := {}
var parameter_diff_seen := {}

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(condition: bool, label: String) -> bool:
	checks += 1
	if not condition:
		failures += 1
		push_error("FAR_FOREST_HELPER: " + label)
	return condition

func _run() -> void:
	var gpu := OS.get_cmdline_user_args().has("--GPU")
	if gpu:
		create_timer(90.0).timeout.connect(func():
			if not finished:
				push_error("FAR_FIELD: timeout/incomplete GPU run")
				quit(1))
	else: quit(1)
	var completed: Variant = _verify()
	if completed == true and failures == 0:
		completed = _ground_helpers()
	if gpu and completed == true and failures == 0:
		completed = await _ground_gpu()
	if is_instance_valid(fixture): fixture.free()
	if is_instance_valid(gpu_view): gpu_view.free()
	for path: String in source_hashes: _ok(FileAccess.get_sha256(path) == source_hashes[path], "File unchanged during fixture " + path)
	var passed: bool = completed == true and failures == 0
	finished = true
	print("FAR_FIELD_FIXTURE_AUDIT: ", "PASS" if passed else "FAIL", "; ", JSON.stringify({"checks": checks, "failures": failures, "parameter_diff_counts": parameter_diff_counts, "forest_stages": stages, "ground_helper_stages": ground_stages, "registered_fixture_cards": cards.size(), "source_hashes": source_hashes, "ground_gpu": gpu_records if gpu else "NOT_RUN: requires --GPU/native renderer", "limits": "synthetic registered cards and private ground crops only; NOT actual scene build/geometry/alpha roots, grove fog pixels .50/.75, complete masks, full-scene night parity, final pack or performance"}))
	quit(0 if passed else 1)

func _parameters(material: ShaderMaterial) -> Dictionary:
	var result := {}
	var uniforms := GROVES.NATIVE_SHADER.get_shader_uniform_list()
	_log_schema(GROVES.NATIVE_SHADER, uniforms)
	for item: Dictionary in uniforms:
		var key := str(item.name)
		result[key] = material.get_shader_parameter(key)
	return result

func _log_schema(shader: Shader, uniforms: Array) -> void:
	var encoded := JSON.stringify(uniforms)
	var id := str(shader.get_instance_id())
	if uniform_schemas.get(id, "") == encoded: return
	print("FAR_UNIFORM_SCHEMA: ", JSON.stringify({"shader": shader.resource_path, "shader_instance": id, "process_frame": Engine.get_process_frames(), "changed_since_previous_query": uniform_schemas.has(id), "uniforms": uniforms}))
	uniform_schemas[id] = encoded

func _value_info(value: Variant) -> Dictionary:
	var result := {"type": type_string(typeof(value)), "type_id": typeof(value)}
	if value is Resource:
		result["resource_class"] = value.get_class()
		result["resource_path"] = value.resource_path
		result["instance_id"] = value.get_instance_id()
	elif value is Array or (typeof(value) >= TYPE_PACKED_BYTE_ARRAY and typeof(value) <= TYPE_PACKED_VECTOR4_ARRAY):
		result["size"] = value.size()
		if value is Array:
			result["typed_builtin"] = value.get_typed_builtin()
			result["typed_class"] = str(value.get_typed_class_name())
		var elements: Array = []
		for i in range(mini(value.size(), 128)): elements.append(_value_info(value[i]))
		result["elements"] = elements
		result["truncated"] = value.size() > 128
	elif value is Vector2: result["value"] = [value.x, value.y]
	elif value is Vector3: result["value"] = [value.x, value.y, value.z]
	elif value is Vector4: result["value"] = [value.x, value.y, value.z, value.w]
	elif value is Color: result["value"] = [value.r, value.g, value.b, value.a]
	elif typeof(value) in [TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING]: result["value"] = value
	else: result["value"] = var_to_str(value)
	return result

func _parameter_diffs(actual: Dictionary, baseline: Dictionary, label: String) -> void:
	var keys := baseline.keys()
	for key: Variant in actual:
		if not keys.has(key): keys.append(key)
	var differences := 0
	for key: Variant in keys:
		var present_a := actual.has(key)
		var present_b := baseline.has(key)
		var a: Variant = actual.get(key)
		var b: Variant = baseline.get(key)
		if present_a == present_b and typeof(a) == typeof(b) and a == b: continue
		differences += 1
		var category := str(key) + " | " + type_string(typeof(b)) + " -> " + type_string(typeof(a))
		parameter_diff_counts[category] = int(parameter_diff_counts.get(category, 0)) + 1
		var detail := {"key": str(key), "expected_present": present_b, "actual_present": present_a, "expected": _value_info(b), "actual": _value_info(a)}
		var signature := JSON.stringify(detail).sha256_text()
		if not parameter_diff_seen.has(signature):
			parameter_diff_seen[signature] = true
			detail["context"] = label
			detail["process_frame"] = Engine.get_process_frames()
			print("FAR_PARAMETER_DIFF: ", JSON.stringify(detail))
	if differences == 0 and actual != baseline:
		var category := "dictionary_unequal_but_each_key_value_equal"
		parameter_diff_counts[category] = int(parameter_diff_counts.get(category, 0)) + 1
		print("FAR_PARAMETER_DICTIONARY_DIFF: ", JSON.stringify({"context": label, "actual_keys": actual.keys(), "expected_keys": baseline.keys(), "actual_hash": actual.hash(), "expected_hash": baseline.hash()}))

func _parameters_equal(actual: Dictionary, baseline: Dictionary, label: String) -> bool:
	if actual != baseline: _parameter_diffs(actual, baseline, label)
	return _ok(actual == baseline, label) # Original exact gate, deliberately unchanged.

func _environment_state(environment: Environment) -> Dictionary:
	var result := {}
	if environment == null: return result
	for item: Dictionary in environment.get_property_list():
		if int(item.usage) & PROPERTY_USAGE_STORAGE: result[str(item.name)] = environment.get(item.name)
	return result

func _material(index: int, texture: Texture2D) -> ShaderMaterial:
	var result := ShaderMaterial.new()
	result.shader = GROVES.NATIVE_SHADER
	var values := {"asset_texture": texture, "tint": Color(.7 + index * .02, .8, .6, 1), "alpha_threshold": .22 + index * .01, "bottom_fade": .03, "face_camera": true, "edge_inset": .35, "remove_pale_matte": false, "uv_region": Vector4(.05 * index, .1, .1, .3), "painted_fill": .16, "relief_strength": .62, "leaf_transmission": .1, "art_contrast": 1.26, "art_exposure": .85, "foliage_tone": true, "wind_strength": .055 + index * .02, "rooted_herb": true, "lantern_flame": false, "mip_bias": -.45, "sprite_flip": false, "sprite_bank": .03, "sprite_profile": .9, "creature_visibility": 1.0, "creature_glow": 0.0, "window_count": 2, "window_energy": 1.2, "root_contact": .7, "soil_bounds": Vector4(-2, -3, 4, 5), "sunbreak_strength": .72}
	var soil := PackedFloat32Array()
	soil.resize(25)
	for i in range(25): soil[i] = float(index) + float(i) * .0125
	values["soil_heights"] = soil
	var windows: Array[Vector4] = []
	for i in range(32): windows.append(Vector4(.01 * i, .3, .01, .02))
	values["lit_windows"] = windows
	# Explicit non-default canopy inputs: a cold getter can otherwise return
	# Nil before native defaults resolve, even on untouched source materials.
	values["canopy_count"] = 2
	values["canopy_lobes"] = PackedVector4Array([Vector4(.25, .35, .18, .22), Vector4(.68, .42, .21, .19), Vector4(.37, .73, .16, .17), Vector4(.76, .71, .14, .20)])
	values["canopy_strength"] = .45 + index * .025
	values["canopy_backlight"] = true
	values["canopy_leaf_orientation"] = true
	values["canopy_pigment_recovery"] = true
	for key: String in values: result.set_shader_parameter(key, values[key])
	return result

func _register(index: int) -> bool:
	# Observe lazy getter/default changes BEFORE production registration as well.
	_parameter_diffs(_parameters(originals[index % 6]), expected[index % 6], "before_register/original/" + str(index))
	bridge.register_grove(cards[index])
	var material := cards[index].material_override as ShaderMaterial
	if not _ok(material != null and material != originals[index % 6], "Registration duplicates source material"): return false
	var identity := material.get_instance_id()
	_ok(not identities.has(identity), "Independent material for each generation/card")
	identities.append(identity)
	bridge.register_grove(cards[index])
	_ok(cards[index].material_override == material and bridge.materials.size() == index + 1 and bridge.registered.size() == index + 1, "Duplicate registration is inert")
	_parameters_equal(_parameters(material), expected[index % 6], "Registration preserves all exposed native parameters/" + str(index))
	return true

func _tick(label: String, environment: Environment, night: float, day_shader: bool) -> bool:
	world.environment = environment
	weather.night_blend = night
	var before := _environment_state(environment)
	bridge._process(0.0) # Actual production callback, deterministic; automatic processing disabled.
	var target: Shader = GROVES.DAY_SHADER if day_shader else GROVES.NATIVE_SHADER
	for i in range(identities.size()):
		var material := cards[i].material_override as ShaderMaterial
		if not _ok(material != null, "Material exists " + label): return false
		_ok(material.get_instance_id() == identities[i] and bridge.materials[i] == material, "Registered material identity remains stable " + label)
		_ok(material.shader == target, "Exact shader endpoint/fallback " + label)
		var prescribed := expected[i % 6].duplicate(true)
		var day := 1.0 - night if day_shader else 0.0
		var tint: Color = prescribed.tint
		var gain := Color(.97, 1.0, .94) if i < 6 else Color(.90, .98, 1.0)
		prescribed.tint = tint.lerp(tint * gain, day) if day > 0.0 else tint
		for pair: Array in [["painted_fill", .08], ["relief_strength", .22], ["root_contact", .38]]:
			prescribed[pair[0]] = lerpf(expected[i % 6][pair[0]], pair[1], day) if day > 0.0 else expected[i % 6][pair[0]]
		_parameters_equal(_parameters(material), prescribed, "Four prescribed day fields; all other native fields exact; native endpoints exact " + label + "/" + str(i))
		if day_shader:
			_ok(material.get_shader_parameter("grove_fog_enabled") == environment.fog_enabled, "Actual enabled " + label)
			_ok(absf(float(material.get_shader_parameter("grove_fog_density")) - environment.fog_density) <= 1e-8, "Actual density " + label)
			var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
			var color: Variant = material.get_shader_parameter("grove_fog_linear_color")
			if not _ok(typeof(color) == TYPE_VECTOR3, "Linear fog color type " + label): return false
			_ok(Vector3(color).distance_to(Vector3(linear.r, linear.g, linear.b)) <= 1e-6, "sRGB to linear exactly once then energy " + label)
			var roots: Variant = material.get_shader_parameter("grove_root_v")
			if not _ok(typeof(roots) == TYPE_PACKED_FLOAT32_ARRAY and roots.size() == 25, "25 actual source-root UV columns " + label): return false
			for column in range(25):
				var expected_root := .88 if i < 6 else .75 + .20 * float(column) / 24.0
				_ok(absf(float(roots[column]) - expected_root) <= 1e-6, "Root UV input interpolation, not arbitrary skirt " + label)
			_ok(material.get_shader_parameter("grove_root_span") == clampf(1.2 / float(12 + i % 6), .035, .20), "Root span from actual fixture height " + label)
	for i in range(originals.size()):
		_ok(originals[i].shader == GROVES.NATIVE_SHADER, "Shared original shader untouched " + label)
		_parameters_equal(_parameters(originals[i]), expected[i], "Shared foreground/source material untouched " + label + "/" + str(i))
	_ok(_environment_state(environment) == before and weather.night_blend == night, "Environment/weather input unmodified " + label)
	_ok(bridge.materials.size() == identities.size() and bridge.registered.size() == identities.size(), "Exact registration count " + label)
	stages += 1
	print("FAR_FOREST_STAGE: ", label, " registered=", identities.size(), " target=", target.resource_path, " cumulative_failures=", failures)
	return true

func _verify() -> bool:
	for path: String in PROTECTED:
		_ok(FileAccess.get_sha256(path) == PROTECTED[path], "Protected water/sky/focus/weather " + path)
		source_hashes[path] = FileAccess.get_sha256(path)
	for path: String in ["res://scripts/meadow_mountain_groves.gd", "res://shaders/meadow_grove_day.gdshader", "res://shaders/meadow_grove_fog.gdshaderinc", "res://shaders/meadow_cutout.gdshader", "res://shaders/meadow_cutout_surface.gdshaderinc", "res://shaders/meadow_sunbreak.gdshaderinc"]:
		if not _ok(FileAccess.file_exists(path), "Required helper/shader " + path): return false
		source_hashes[path] = FileAccess.get_sha256(path)
	fixture = Node3D.new()
	world = WorldEnvironment.new()
	world.name = "WorldEnvironment"
	fixture.add_child(world)
	weather = WeatherFixture.new()
	weather.name = "LivingWeather"
	fixture.add_child(weather)
	bridge = GROVES.Atmosphere.new()
	bridge.name = "GroveAtmosphere"
	bridge.set_process(false)
	fixture.add_child(bridge)
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(Color(.2, .5, .1, 1))
	var texture := ImageTexture.create_from_image(image)
	for i in range(6):
		var material := _material(i, texture)
		originals.append(material)
		expected.append(_parameters(material))
		_ok(expected[i].size() >= 30 and expected[i].get("asset_texture") == texture, "Nonempty complete uniform fixture including real texture")
		_ok(expected[i].get("soil_heights") != null and expected[i].get("lit_windows") != null, "Array uniforms represented")
	for i in range(12):
		var card := MeshInstance3D.new()
		card.name = ("UniqueWoodlandBelt_%02d" % i) if i < 6 else ("MountainGrove_%02d" % (i - 6))
		card.mesh = QuadMesh.new()
		card.material_override = originals[i % 6] # Deliberately shared across generations.
		# Real new registration inputs; two source families remain deliberately distinct.
		card.set_meta("art_anchor", Vector2(.5, .88))
		card.set_meta("art_height", float(12 + i % 6))
		if i >= 6:
			card.set_meta("mountain_grove_index", i - 6)
			card.set_meta("herb_source_bottoms", PackedFloat32Array([.75, .80, .85, .90, .95]))
		fixture.add_child(card)
		cards.append(card)
	var environment := Environment.new()
	environment.fog_enabled = true
	environment.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	environment.fog_height_density = 0.0
	environment.fog_sun_scatter = 0.0
	environment.fog_aerial_perspective = 0.0
	environment.fog_density = .00042
	environment.fog_light_color = Color(.35, .55, .75, 1)
	environment.fog_light_energy = 1.3
	world.environment = environment
	root.add_child(fixture) # Only fixture nodes; actual helper _ready sets priority.
	bridge.set_process(false)
	_ok(bridge.process_priority == 2, "Actual helper ready priority")
	for i in range(6):
		if not _register(i): return false
	if not _tick("first_generation_day", environment, 0.0, true): return false
	for i in range(6, 12):
		if not _register(i): return false
	if not _tick("late_registration_same_environment", environment, 0.0, true): return false
	if not _tick("unchanged_repeat", environment, 0.0, true): return false
	for pair: Array in [["half", .5, true], ["near_night", .999, true], ["night_native", 1.0, false], ["return_day", 0.0, true]]:
		if not _tick(pair[0], environment, pair[1], pair[2]): return false
	var original_state := _environment_state(environment)
	var alternate := environment.duplicate() as Environment
	alternate.fog_light_color = Color(.61, .22, .13, 1)
	alternate.fog_light_energy = .8
	alternate.fog_density = .0012
	if not _tick("environment_duplicate", alternate, 0.0, true): return false
	alternate.fog_enabled = false
	if not _tick("fog_disabled", alternate, 0.0, true): return false
	if not _tick("original_environment_restored", environment, 0.0, true): return false
	for pair: Array in [["fog_mode", Environment.FOG_MODE_DEPTH], ["fog_height_density", .02], ["fog_height_density", -.02], ["fog_sun_scatter", .2], ["fog_aerial_perspective", .3]]:
		var unsupported := environment.duplicate() as Environment
		unsupported.set(pair[0], pair[1])
		if not _tick("unsupported_" + str(pair[0]) + "_" + str(pair[1]), unsupported, 0.0, false): return false
		if not _tick("supported_return", environment, 0.0, true): return false
	if not _tick("missing_environment_native", null, 0.0, false): return false
	if not _tick("final_day_restore", environment, 0.0, true): return false
	_ok(_environment_state(environment) == original_state, "Original environment fully retained through alternate tests")
	_ok(identities.size() == 12 and stages == 22, "All twelve materials and bounded stage sequence completed")
	return true

func _ground_parameters(material: ShaderMaterial) -> Dictionary:
	var result := {}
	var uniforms := GROUND.ORIGINAL_SHADER.get_shader_uniform_list()
	_log_schema(GROUND.ORIGINAL_SHADER, uniforms)
	for entry: Dictionary in uniforms: result[str(entry.name)] = material.get_shader_parameter(entry.name)
	return result

func _ground_material() -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = GROUND.ORIGINAL_SHADER
	var img := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	img.fill(Color(.5, .58, .36, 1))
	var texture := ImageTexture.create_from_image(img)
	for name: String in ["meadow_texture", "rock_texture", "bank_limestone_texture", "limestone_texture"]: material.set_shader_parameter(name, texture)
	var contacts: Array[Vector4] = []
	for i in range(72): contacts.append(Vector4(10 + i, -20, 0, 0))
	material.set_shader_parameter("contact_shadows", contacts)
	material.set_shader_parameter("road_width", Vector4(1.35, 3.1, -65, 10))
	material.set_shader_parameter("foothill_origin", Vector2(0, -255))
	material.set_shader_parameter("sunbreak_strength", 0.0)
	_ground_paths(material, false, false)
	return material

func _ground_paths(material: ShaderMaterial, road: bool, river: bool) -> void:
	var roads := PackedVector2Array()
	var bends := PackedVector2Array()
	for i in range(12): roads.append(Vector2(-40 if road else 1000, 30 - i * 35))
	for i in range(10): bends.append(Vector2(30 - i * 40, 0 if river else 1000))
	material.set_shader_parameter("road_points", roads)
	material.set_shader_parameter("road_fork", PackedVector2Array([Vector2(900, 30), Vector2(910, -300)]))
	material.set_shader_parameter("bridge_spur", PackedVector2Array([Vector2(950, 30), Vector2(960, -300)]))
	material.set_shader_parameter("river_bends", bends)
	material.set_shader_parameter("road_width", Vector4(6, 6, -65, 10) if road else Vector4(1.35, 3.1, -65, 10))

func _ground_tick(material: ShaderMaterial, original: Dictionary, environment: Environment, night: float, day: bool, label: String) -> bool:
	var snapshot := _environment_state(environment)
	GROUND.sync_material(material, environment, night)
	_ok(material.shader == (GROUND.make_day_shader() if day else GROUND.ORIGINAL_SHADER), "Ground exact shader " + label)
	_parameters_equal(_ground_parameters(material), original, "Ground preserves ALL native parameters " + label)
	_ok(_environment_state(environment) == snapshot, "Ground environment untouched " + label)
	if day:
		_ok(material.get_shader_parameter("far_ground_fog_enabled") == environment.fog_enabled, "Ground actual fog enable " + label)
		_ok(absf(float(material.get_shader_parameter("far_ground_fog_density")) - environment.fog_density) <= 1e-8, "Ground actual density " + label)
		var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
		var color: Variant = material.get_shader_parameter("far_ground_fog_linear_color")
		if not _ok(typeof(color) == TYPE_VECTOR3, "Ground fog vec3 " + label): return false
		_ok(Vector3(color).distance_to(Vector3(linear.r, linear.g, linear.b)) <= 1e-6, "Ground single linear conversion " + label)
	ground_stages += 1
	print("FAR_GROUND_HELPER_STAGE: ", label, " cumulative_failures=", failures)
	return true

func _ground_helpers() -> bool:
	for path: String in ["res://scripts/meadow_ground_atmosphere.gd", "res://scripts/meadow_far_sward.gd", "res://scripts/meadow_branch_geometry.gd", "res://shaders/meadow_leaves.gdshader", "res://shaders/meadow_ground.gdshader", "res://shaders/meadow_ground_day.gdshader", "res://shaders/meadow_ground_surface.gdshaderinc", "res://shaders/meadow_far_ground.gdshaderinc", "res://shaders/meadow_palette.gdshaderinc", "res://shaders/meadow_surface.gdshaderinc", "res://shaders/meadow_mineral.gdshaderinc", "res://shaders/meadow_mountain_floor.gdshaderinc"]:
		if not _ok(FileAccess.file_exists(path), "Ground dependency " + path): return false
		source_hashes[path] = FileAccess.get_sha256(path)
	var variant: Shader = GROUND.make_day_shader()
	if not _ok(variant != null and variant != GROUND.ORIGINAL_SHADER and variant == GROUND.make_day_shader() and variant == GROUND.day_shader, "One cached actual day variant"): return false
	var material := _ground_material()
	var original := _ground_parameters(material)
	_ok(original.size() >= 12, "Ground populated texture/array/native uniform fixture")
	var environment := world.environment.duplicate() as Environment
	_ok(GROUND.supports_environment(environment), "Ground exponential environment supported")
	for pair: Array in [["day", 0.0, true], ["half", .5, true], ["near_night", .999, true], ["night_native", 1.0, false], ["return", 0.0, true]]:
		if not _ground_tick(material, original, environment, pair[1], pair[2], pair[0]): return false
	var alternate := environment.duplicate() as Environment
	alternate.fog_density = .0011
	alternate.fog_light_color = Color(.63, .2, .39, 1)
	alternate.fog_light_energy = .7
	if not _ground_tick(material, original, alternate, 0.0, true, "alternate_environment"): return false
	alternate.fog_enabled = false
	if not _ground_tick(material, original, alternate, 0.0, true, "fog_disabled"): return false
	for pair: Array in [["fog_mode", Environment.FOG_MODE_DEPTH], ["fog_height_density", .02], ["fog_sun_scatter", .2], ["fog_aerial_perspective", .2]]:
		var unsupported := environment.duplicate() as Environment
		unsupported.set(pair[0], pair[1])
		_ok(not GROUND.supports_environment(unsupported), "Ground unsupported predicate " + str(pair[0]))
		if not _ground_tick(material, original, unsupported, 0.0, false, str(pair[0])): return false
		if not _ground_tick(material, original, environment, 0.0, true, "supported_return"): return false
	_ok(not GROUND.supports_environment(null), "Ground null environment unsupported")
	if not _ground_tick(material, original, null, 0.0, false, "null_environment"): return false
	if not _ground_tick(material, original, environment, 0.0, true, "final_return"): return false
	var foreign := originals[0].duplicate() as ShaderMaterial
	var foreign_params := _parameters(foreign)
	GROUND.sync_material(foreign, environment, 0.0)
	_ok(foreign.shader == GROVES.NATIVE_SHADER and _parameters(foreign) == foreign_params, "Ground helper ignores unrelated material")
	_ok(ground_stages == 17, "Complete bounded ground helper transitions")
	return true

func _isolated_shader(source: Shader) -> Shader:
	var code := source.code
	for name: String in ["meadow_clock", "meadow_night"]:
		var declaration := "global uniform float " + name + ";"
		if not _ok(code.count(declaration) == 1, "Single isolated ground global " + name): return null
		code = code.replace(declaration, "uniform float " + name + ";")
	var shader := Shader.new()
	shader.code = code # Includes, far scope, BRDF and FOG remain unmodified.
	return shader

func _gpu_capture(card: MeshInstance3D, material: ShaderMaterial) -> Image:
	card.material_override = material
	for i in range(4): await RenderingServer.frame_post_draw
	return gpu_view.get_texture().get_image()

func _pixel_delta(a: Color, b: Color) -> float:
	return maxf(absf(a.r - b.r), maxf(absf(a.g - b.g), absf(a.b - b.b)))

func _ground_gpu() -> bool:
	if not _ok(DisplayServer.get_name() != "headless" and not ProjectSettings.get_setting("rendering/shading/overrides/force_vertex_shading", false), "--GPU requires actual fragment renderer, not headless"): return false
	var native := _isolated_shader(GROUND.ORIGINAL_SHADER)
	var variant := _isolated_shader(GROUND.make_day_shader())
	if native == null or variant == null: return false
	gpu_view = SubViewport.new()
	gpu_view.size = Vector2i(128, 128)
	gpu_view.own_world_3d = true
	gpu_view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(gpu_view)
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color.WHITE
	environment.ambient_light_energy = .2
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	environment.tonemap_exposure = 1.0
	environment.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	environment.fog_height_density = 0.0
	environment.fog_sun_scatter = 0.0
	environment.fog_aerial_perspective = 0.0
	environment.fog_density = .00042
	environment.fog_light_color = Color(.45, .6, .75, 1)
	environment.fog_light_energy = 1.0
	var env_node := WorldEnvironment.new()
	env_node.environment = environment
	gpu_view.add_child(env_node)
	var card := MeshInstance3D.new()
	card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	gpu_view.add_child(card)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 5.0
	camera.near = .1
	camera.far = 250.0
	camera.rotation_degrees.x = -90
	gpu_view.add_child(camera)
	camera.make_current()
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-34, 72, 0)
	key.light_color = Color.WHITE
	key.light_energy = 1.9
	key.shadow_enabled = false
	gpu_view.add_child(key)
	# Actual full shader on bounded world-space crops, not injected mask outputs.
	# Bank/inner-shore exclusions overlap; this does not isolate their attribution.
	var cases := [["far_day", Vector3(-40, 2, -145), 0.0, false, false, Vector3.UP, true, true],
		["far_day_no_fog", Vector3(-40, 2, -145), 0.0, false, false, Vector3.UP, false, true],
		["forced_variant_night1", Vector3(-40, 2, -145), 1.0, false, false, Vector3.UP, true, false],
		["near_day", Vector3(-40, 2, -60), 0.0, false, false, Vector3.UP, true, false],
		["road_day", Vector3(-40, 2, -145), 0.0, true, false, Vector3.UP, true, false],
		["bank_day", Vector3(8, 2, -145), 0.0, false, true, Vector3.UP, true, false],
		["inner_shore_day", Vector3(10, 2, -145), 0.0, false, true, Vector3.UP, true, false],
		["submerged_day", Vector3(0, -2, -145), 0.0, false, true, Vector3.UP, true, false],
		["cliff_day", Vector3(-40, 2, -145), 0.0, false, false, Vector3(0, .4, .9165151), true, false],
		["low_height_day", Vector3(-40, -.1, -145), 0.0, false, false, Vector3.UP, true, false]]
	print("FAR_GROUND_GPU_FIXTURE: actual native/generated variant; globals localized only; private128x128 ROI32,32,64,64; ortho5m camera120m above crop; solid textures; white key1.9 ambient.2; no shadows; clock0; fixed 1LSB controls; not a real night-light/full-scene capture")
	for test: Array in cases:
		card.position = test[1]
		camera.position = card.position + Vector3.UP * 120.0
		environment.fog_enabled = test[6]
		var plane := PlaneMesh.new()
		plane.size = Vector2(4, 4)
		var arrays := plane.get_mesh_arrays()
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		normals.fill(test[5])
		arrays[Mesh.ARRAY_NORMAL] = normals
		var uv2 := PackedVector2Array()
		uv2.resize(arrays[Mesh.ARRAY_VERTEX].size())
		uv2.fill(Vector2(.62, 0))
		arrays[Mesh.ARRAY_TEX_UV2] = uv2
		var mesh := ArrayMesh.new()
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
		card.mesh = mesh
		var before := _ground_material()
		_ground_paths(before, test[3], test[4])
		var parameters := _ground_parameters(before)
		var after := before.duplicate() as ShaderMaterial
		GROUND.sync_material(after, environment, 0.0) # Populate actual environment bridge parameters.
		var fog_parameters := {}
		for name: String in ["far_ground_fog_enabled", "far_ground_fog_density", "far_ground_fog_linear_color"]:
			fog_parameters[name] = after.get_shader_parameter(name)
			if not _ok(fog_parameters[name] != null, "Actual helper populated GPU fog parameter " + name): return false
		before.shader = native
		after.shader = variant # Deliberately also test variant math at night=1.
		for name: String in fog_parameters: after.set_shader_parameter(name, fog_parameters[name])
		for name: String in parameters:
			if parameters[name] != null:
				before.set_shader_parameter(name, parameters[name])
				after.set_shader_parameter(name, parameters[name])
		for material: ShaderMaterial in [before, after]:
			material.set_shader_parameter("meadow_clock", 0.0)
			material.set_shader_parameter("meadow_night", test[2])
		var a := await _gpu_capture(card, before)
		var b := await _gpu_capture(card, after)
		var restored := await _gpu_capture(card, before)
		for img: Image in [a, b, restored]:
			if not _ok(img != null and not img.is_empty() and img.get_size() == Vector2i(128, 128), "Complete GPU readback " + str(test[0])): return false
		var maximum := 0.0
		var repeat_error := 0.0
		var changed_pixels := 0
		var mean_before := 0.0
		var mean_after := 0.0
		var mean_delta := 0.0
		var peak := 0.0
		var finite := true
		for y in range(32, 96):
			for x in range(32, 96):
				var ca := a.get_pixel(x, y)
				var cb := b.get_pixel(x, y)
				var cr := restored.get_pixel(x, y)
				finite = finite and Vector4(ca.r, ca.g, ca.b, ca.a).is_finite() and Vector4(cb.r, cb.g, cb.b, cb.a).is_finite() and Vector4(cr.r, cr.g, cr.b, cr.a).is_finite()
				var delta := _pixel_delta(ca, cb)
				maximum = maxf(maximum, delta)
				repeat_error = maxf(repeat_error, _pixel_delta(ca, cr))
				if delta > PIXEL_EPS: changed_pixels += 1
				mean_before += ca.get_luminance()
				mean_after += cb.get_luminance()
				mean_delta += delta
				peak = maxf(peak, maxf(_pixel_delta(ca, Color.BLACK), _pixel_delta(cb, Color.BLACK)))
		var response: bool = maximum > PIXEL_EPS and changed_pixels >= 16 if test[7] else maximum <= PIXEL_EPS
		var passed: bool = finite and response and repeat_error <= PIXEL_EPS and mean_before / 4096.0 > .01 and mean_after / 4096.0 > .01 and peak < .98
		var record := {"case": test[0], "pixels": 4096, "native_mean": mean_before / 4096.0, "variant_mean": mean_after / 4096.0, "mean_abs_maxRGB_delta": mean_delta / 4096.0, "max_delta": maximum, "changed_pixels_over_1LSB": changed_pixels, "restored_error": repeat_error, "peak": peak, "finite": finite, "response_expected": test[7], "pass": passed}
		gpu_records.append(record)
		print("FAR_GROUND_GPU_CASE: ", JSON.stringify(record))
		if not _ok(passed, "Ground GPU " + str(test[0])): return false
	return _ok(gpu_records.size() == 10, "All ten GPU cases completed")
