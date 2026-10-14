extends SceneTree
## v95 source/scene state audit only. Main runs the engine; no assets are written.
const BRIDGE = preload("res://scripts/meadow_architecture_fog.gd")
const NATIVE = preload("res://shaders/meadow_architecture.gdshader")
const DAY = preload("res://shaders/meadow_architecture_day.gdshader")
const LABELS := ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1", "ContinuousRiver"]
const WEATHER_COMPACT_SHA := "d66701e21eb6058f304e4153f1e6daa30cdbbbf1329e482746bb4e587138017c"
const PROTECTED := {
	"res://shaders/meadow_architecture.gdshader": "95fdba083314d0ee0dd36cccea9d7365c985060cbcc859ad17a8c91db61fdd7b",
	"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08",
	"res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d",
	"res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b",
	"res://shaders/meadow_leaves.gdshader": "dd218655817268a12de2be516df8d9280edb309502fb3228f0604450b5310335",
	"res://scripts/meadow_scene.gd": "b7ba803e9f56c3b11d0fd3c82906022152a1e074ef7e07c6a7471e78cb7b4046"}
var failed := false
var checks := 0

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	_source_checks()
	if failed:
		quit(1)
		return
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	root.add_child(scene) # One real world, synchronous ready; no renderer/readback claims.
	var weather = scene.get_node("LivingWeather")
	var world := scene.get_node("WorldEnvironment") as WorldEnvironment
	var original := world.environment
	var saved := {}
	for key: String in ["night_blend", "night_target", "motion_enabled", "reduced_motion", "animation_clock",
			"transition_elapsed", "transition_start", "transitioning", "reflection_revision", "ui_interval"]:
		saved[key] = weather.get(key)
	var processing: bool = weather.is_processing()
	var probe_transform: Transform3D = weather.probe.transform
	var snapshots := {}
	for label: String in LABELS:
		var card := scene.get_node(NodePath(label)) as MeshInstance3D
		snapshots[label] = {"material": card.material_override, "shader": card.material_override.shader,
			"parameters": _parameters(card.material_override), "mesh": card.mesh, "transform": card.transform}
	weather.set_process(false)
	weather.set_motion(false)
	_exercise(scene, original, snapshots)
	# Cleanup is outside the checks; failed expectations do not bypass restoration.
	world.environment = original
	weather._apply_lighting(float(saved["night_blend"]))
	for label: String in LABELS:
		var before: Dictionary = snapshots[label]
		var material: ShaderMaterial = before.material
		scene.get_node(NodePath(label)).material_override = material
		material.shader = before.shader
		for key: String in before.parameters:
			material.set_shader_parameter(key, before.parameters[key])
	for key: String in saved:
		weather.set(key, saved[key])
	weather.probe.transform = probe_transform
	RenderingServer.global_shader_parameter_set("meadow_clock", float(saved["animation_clock"]))
	weather.set_process(processing)
	_verify(scene, original, snapshots, DAY, 0.0, "restored")
	_expect(weather.environment == original and world.environment == original, "Original Environment references restored")
	scene.free()
	print("MEADOW_ARCHITECTURE_ATMOSPHERE_AUDIT: %s; %d source/state checks; one real scene, day/transition/native night/fallback/alternate environment; arrays/textures retained; no GPU/fog-pixel/visual/performance acceptance" % ["FAIL" if failed else "PASS", checks])
	quit(1 if failed else 0)

func _exercise(scene: Node3D, original: Environment, snapshots: Dictionary) -> void:
	var weather = scene.get_node("LivingWeather")
	var world := scene.get_node("WorldEnvironment") as WorldEnvironment
	_expect(weather.night_blend == 0.0 and not weather.transitioning, "Actual startup is the day endpoint")
	_verify(scene, original, snapshots, DAY, 0.0, "startup")
	for label: String in LABELS.slice(0, 2):
		var p: Dictionary = snapshots[label].parameters
		_expect(p.get("asset_texture") is Texture2D, label + " actual texture")
		for key: String in ["architecture_ab", "architecture_cd", "architecture_normals", "lit_windows"]:
			_expect(p.has(key) and p[key] != null and p[key].size() >= 32, label + " populated array " + key)
	_expect(is_equal_approx(original.fog_density, 0.00042), "Actual original day density")
	weather.toggle_time()
	weather.advance_weather(1.6)
	_expect(weather.transitioning and is_equal_approx(weather.night_blend, 0.5), "Real paused-clock half transition")
	_verify(scene, original, snapshots, DAY, 0.5, "half-night")
	weather.advance_weather(1.6)
	_expect(weather.night_blend == 1.0 and not weather.transitioning, "Real night endpoint")
	_verify(scene, original, snapshots, NATIVE, 1.0, "night")
	_expect(is_equal_approx(original.fog_density, 0.00048) and original.fog_light_color.is_equal_approx(Color(0.26, 0.34, 0.47)), "Native night fog parameters")
	_expect(is_equal_approx(weather.key_light.light_energy, 1.20) and is_equal_approx(original.tonemap_exposure, 2.2), "Original night lighting")
	weather.toggle_time()
	weather.advance_weather(1.6)
	_verify(scene, original, snapshots, DAY, 0.5, "half-day")
	weather.advance_weather(1.6)
	_verify(scene, original, snapshots, DAY, 0.0, "returned-day")
	_expect(weather.animation_clock == 0.0 and not weather.motion_enabled, "Transition did not advance paused clock")
	var original_state := _stored(original)
	var cases: Array[Dictionary] = [
		{"name": "alternate", "shader": DAY, "settings": {"fog_light_color": Color(0.25, 0.5, 0.75), "fog_light_energy": 1.7, "fog_density": 0.002}},
		{"name": "disabled", "shader": DAY, "settings": {"fog_enabled": false}},
		{"name": "depth-fallback", "shader": NATIVE, "settings": {"fog_mode": Environment.FOG_MODE_DEPTH}},
		{"name": "height-fallback", "shader": NATIVE, "settings": {"fog_height_density": 0.2}},
		{"name": "scatter-fallback", "shader": NATIVE, "settings": {"fog_sun_scatter": 0.3}}]
	for test: Dictionary in cases:
		var alternate := original.duplicate() as Environment
		for key: String in test.settings:
			alternate.set(key, test.settings[key])
		var untouched := _stored(alternate)
		world.environment = alternate # Weather deliberately still retains original.
		weather.advance_weather(0.0) # Exercise the real per-frame bridge, not its predicate.
		_verify(scene, alternate, snapshots, test.shader, 0.0, test.name)
		_expect(weather.environment == original and _stored(original) == original_state, "Alternate environment did not mutate original")
		_expect(_stored(alternate) == untouched, "Bridge did not write alternate Environment")
		world.environment = original
		weather.advance_weather(0.0)
		_verify(scene, original, snapshots, DAY, 0.0, test.name + "-restored")
	# Same private-material route used by the isolated fog-disabled GPU probe.
	var isolated := snapshots[LABELS[0]].material.duplicate() as ShaderMaterial
	var fog_off := original.duplicate() as Environment
	fog_off.fog_enabled = false
	var isolated_before := _parameters(isolated)
	BRIDGE.sync_material(isolated, fog_off, 0.0)
	_expect(isolated.shader == DAY and isolated.get_shader_parameter("architecture_fog_enabled") == false, "Isolated probe explicitly disables custom fog")
	_preserved(isolated, isolated_before, "isolated")
	_expect(isolated.get_shader_parameter("painted_fill") == isolated_before.get("painted_fill"), "Isolated fog bridge retains painted fill")
	_verify(scene, original, snapshots, DAY, 0.0, "isolated-left-main-unchanged")
	world.environment = null
	weather.advance_weather(0.0)
	_verify(scene, null, snapshots, NATIVE, 0.0, "missing-environment-fallback")
	world.environment = original
	weather.advance_weather(0.0)

func _verify(scene: Node3D, environment: Environment, snapshots: Dictionary, expected: Shader, blend: float, stage: String) -> void:
	for i in range(LABELS.size()):
		var label: String = LABELS[i]
		var card := scene.get_node(NodePath(label)) as MeshInstance3D
		var material := card.material_override as ShaderMaterial
		var before: Dictionary = snapshots[label]
		_expect(material == before.material and card.mesh == before.mesh and card.transform == before.transform, stage + ": references " + label)
		if material == null:
			continue
		_expect(material.shader == (expected if i < 2 else before.shader), stage + ": shader " + label)
		_preserved(material, before.parameters, stage + ": " + label)
		if i < 4:
			var fill: Variant = material.get_shader_parameter("painted_fill")
			_expect(_number(fill) and is_equal_approx(float(fill), lerpf(0.18, 0.26, blend)), stage + ": weather fill " + label)
		if i < 2 and expected == DAY and environment != null:
			var density: Variant = material.get_shader_parameter("architecture_fog_density")
			var color: Variant = material.get_shader_parameter("architecture_fog_linear_color")
			var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
			_expect(material.get_shader_parameter("architecture_fog_enabled") == environment.fog_enabled, stage + ": actual enabled flag")
			_expect(_number(density) and is_equal_approx(float(density), environment.fog_density), stage + ": actual density")
			_expect(color is Vector3 and color.is_finite() and color.is_equal_approx(Vector3(linear.r, linear.g, linear.b)), stage + ": linear color exactly one conversion")
	print("MEADOW_ARCHITECTURE_ATMOSPHERE_STATE: %s; expected=%s; night=%.3f" % [stage, expected.resource_path, blend])

func _preserved(material: ShaderMaterial, before: Dictionary, label: String) -> void:
	for key: String in before:
		if key == "painted_fill" or key.begins_with("architecture_fog_"):
			continue
		_expect(material.get_shader_parameter(key) == before[key], label + ": unchanged parameter " + key)

func _parameters(material: ShaderMaterial) -> Dictionary:
	var result := {}
	for entry: Dictionary in material.shader.get_shader_uniform_list():
		result[str(entry.name)] = material.get_shader_parameter(entry.name)
	return result.duplicate(true) # Arrays deep copied; texture Resource identities retained.

func _stored(resource: Resource) -> Dictionary:
	var result := {}
	for property: Dictionary in resource.get_property_list():
		if int(property.usage) & PROPERTY_USAGE_STORAGE:
			result[str(property.name)] = resource.get(property.name)
	return result.duplicate(true)

func _number(value: Variant) -> bool:
	return (typeof(value) == TYPE_FLOAT or typeof(value) == TYPE_INT) and is_finite(float(value))

func _expect(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failed = true
		push_error("MEADOW_ARCHITECTURE_ATMOSPHERE_AUDIT: FAIL; " + message)

func _source_checks() -> void:
	for path: String in PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == PROTECTED[path], "Protected source " + path)
	var weather := FileAccess.get_file_as_string("res://scripts/meadow_weather.gd")
	var bridge_line := 'const ARCHITECTURE_FOG = preload("res://scripts/meadow_architecture_fog.gd")'
	var sync_line := "ARCHITECTURE_FOG.sync_scene(get_parent(), night_blend)"
	_expect(weather.count(bridge_line) == 1 and weather.count(sync_line) == 2, "Only the approved weather bridge sites")
	var whitespace := RegEx.new()
	if whitespace.compile("\\s+") != OK:
		_expect(false, "Whitespace normalization")
		return
	weather = weather.replace(bridge_line, "").replace(sync_line, "")
	_expect(whitespace.sub(weather, "", true).sha256_text() == WEATHER_COMPACT_SHA, "All pre-v95 weather constants/endpoints/logic remain exact apart from bridge and whitespace")
	var native_text := FileAccess.get_file_as_string("res://shaders/meadow_architecture.gdshader").replace("\r\n", "\n")
	var day_text := FileAccess.get_file_as_string("res://shaders/meadow_architecture_day.gdshader").replace("\r\n", "\n")
	_expect(day_text.replace("#define MEADOW_ARCHITECTURE_DAY_FOG\n", "") == native_text, "Day wrapper differs only by fog macro")
	var baseline := ProjectSettings.globalize_path("res://").path_join("../artifacts/v95/meadow_cutout_surface.v94-before.gdshaderinc").simplify_path()
	_expect(FileAccess.get_sha256(baseline).to_lower() == "3052954debf06a3cca1c62ee1783fda3bf197d18159721d3c496499506e449fe", "Frozen v94 surface baseline")
	var surface := FileAccess.get_file_as_string("res://shaders/meadow_cutout_surface.gdshaderinc").replace("\r\n", "\n")
	for block: String in ['#ifdef MEADOW_ARCHITECTURE_DAY_FOG\n#include "res://shaders/meadow_architecture_fog.gdshaderinc"\n#endif\n',
			"#ifdef MEADOW_ARCHITECTURE_DAY_FOG\n    FOG = architecture_fog(VERTEX, sprite_uv, meadow_night);\n#endif\n"]:
		_expect(surface.count(block) == 1, "Exactly one opt-in fog insertion")
		surface = surface.replace(block, "")
	_expect(surface == FileAccess.get_file_as_string(baseline).replace("\r\n", "\n"), "Native night/nonarchitecture surface remains exact v94")
