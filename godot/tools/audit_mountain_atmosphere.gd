extends SceneTree
## One real scene, actual process callbacks. No GPU/fog-pixel or visual claims.
const BRIDGE = preload("res://scripts/meadow_mountain_atmosphere.gd")
const V96 = preload("res://tools/audit_mountain_material.gd")
const NATIVE := "res://shaders/meadow_mountain.gdshader"
const DAY := "res://shaders/meadow_mountain_day.gdshader"
const OTHERS := ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1", "ContinuousRiver", "Camera3D/DepthAwareFocus", "OldOakOnShelf"]
const BASES := {
	"meadow_cutout_surface.candidate1.gdshaderinc": "555b2bc7f1dcc8a60cbf68f849046c1eb90a31141020a98098934671062a3fff",
	"meadow_scene.candidate1.gd": "966c64f4d155c0c17d63992a24aaacde1d6fe95474bd5d29fbcfeb64ec1bb801",
	"meadow_mountain_relief.candidate1.gd": "119ae17fec07a6dfcba239cfef0401d7c23359b52cb1f83bcfb60747d64204fc"}
var failed := false
var checks := 0
var scene: Node3D
var mountain: MeshInstance3D
var original_material: ShaderMaterial
var original_mesh: Mesh
var original_transform: Transform3D
var mountain_parameters: Dictionary
var completed_stages := 0
var snapshot_complete := false
var source_checks_complete := false

func _initialize() -> void:
	_run.call_deferred()

func _expect(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		failed = true
		push_error("MEADOW_MOUNTAIN_ATMOSPHERE: FAIL; " + label)

func _text(path: String) -> String:
	return FileAccess.get_file_as_string(path).replace("\r\n", "\n")

func _source_checks() -> void:
	for path: String in V96.PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == V96.PROTECTED[path], "Protected v95 path " + path)
	for pair: Array in [[NATIVE, "1cb506a54618a13cefd85d9039fd04b061fdf5f5fe3060432aff02c48f75a85f"],
		["res://shaders/meadow_mountain.gdshaderinc", "e9e775bf581e4238189a9ea03904dc55cfbe1593dea874a8597ac847f2a9751a"],
		["res://scripts/meadow_wildlife.gd", "ec40e60b835be5d9192649fbae128be4f1bd03a981bd5ddfb7c20271ae7a02ec"]]:
		_expect(FileAccess.get_sha256(pair[0]).to_lower() == pair[1], "Accepted mountain/native/flight source " + str(pair[0]))
	var directory := ProjectSettings.globalize_path("res://").path_join("../artifacts/v97").simplify_path()
	for name: String in BASES:
		_expect(FileAccess.get_sha256(directory.path_join(name)).to_lower() == BASES[name], "Frozen candidate1 baseline " + name)
	var surface := _text("res://shaders/meadow_cutout_surface.gdshaderinc")
	for block: String in ['#ifdef MEADOW_MOUNTAIN_DAY_FOG\n#include "res://shaders/meadow_mountain_fog.gdshaderinc"\n#endif\n',
		"#ifdef MEADOW_MOUNTAIN_DAY_FOG\n    FOG = mountain_fog(VERTEX, sprite_uv, meadow_night);\n#endif\n"]:
		_expect(surface.count(block) == 1, "Exactly one approved mountain fog insertion")
		surface = surface.replace(block, "")
	_expect(surface == _text(directory.path_join("meadow_cutout_surface.candidate1.gdshaderinc")), "All previous surface paths exact, including architecture")
	var main := _text("res://scripts/meadow_scene.gd")
	var preload_line := 'const MOUNTAIN_ATMOSPHERE = preload("res://scripts/meadow_mountain_atmosphere.gd")\n'
	var setup_lines := "\tvar mountain_atmosphere := MOUNTAIN_ATMOSPHERE.new()\n\tadd_child(mountain_atmosphere)\n\tmountain_atmosphere.setup(self)\n"
	_expect(main.count(preload_line) == 1 and main.count("\twildlife.setup(self)\n" + setup_lines) == 1, "One setup immediately after wildlife setup")
	_expect(main.replace(preload_line, "").replace(setup_lines, "") == _text(directory.path_join("meadow_scene.candidate1.gd")), "Scene changed only by approved atmosphere setup")
	var relief := _text("res://scripts/meadow_mountain_relief.gd")
	_expect(relief.count("const PEAK_LIFT := 0.08") == 1 and relief.replace("const PEAK_LIFT := 0.08", "const PEAK_LIFT := 0.18") == _text(directory.path_join("meadow_mountain_relief.candidate1.gd")), "Only authorized lift adjustment, not a geometry quality gate")
	var comments := RegEx.new()
	comments.compile("(?m)^\\s*//[^\\n]*\\n")
	var whitespace := RegEx.new()
	whitespace.compile("\\s+")
	var day_code := _text(DAY)
	_expect(day_code.count("#define MEADOW_MOUNTAIN_DAY_FOG\n") == 1, "Single day-only fog macro")
	_expect(whitespace.sub(comments.sub(day_code.replace("#define MEADOW_MOUNTAIN_DAY_FOG\n", ""), "", true), "", true) == whitespace.sub(comments.sub(_text(NATIVE), "", true), "", true), "Day wrapper retains original diffuse/alpha/mountain paths")
	var config := ConfigFile.new()
	_expect(config.load("res://export_presets.cfg") == OK, "Export configuration")
	for path: String in [DAY, "res://scripts/meadow_mountain_atmosphere.gd", "res://scripts/meadow_mountain_relief.gd", V96.DAY, "res://scripts/meadow_architecture_fog.gd"]:
		_expect(path in config.get_value("preset.0", "export_files", PackedStringArray()), "Export includes " + path)
	_expect(str(config.get_value("preset.0", "include_filter", "")).contains("*.gdshaderinc"), "Shader includes exported")
	source_checks_complete = true

func _parameters(material: ShaderMaterial) -> Dictionary:
	var values := {}
	_expect(material != null and material.shader != null, "Snapshot requires an actual ShaderMaterial and shader")
	if material == null or material.shader == null:
		return values
	for entry: Dictionary in material.shader.get_shader_uniform_list():
		values[str(entry.name)] = material.get_shader_parameter(entry.name)
	return values.duplicate(true)

func _stored(resource: Resource) -> Dictionary:
	var values := {}
	for entry: Dictionary in resource.get_property_list():
		if int(entry.usage) & PROPERTY_USAGE_STORAGE:
			values[str(entry.name)] = resource.get(entry.name)
	return values.duplicate(true)

func _other_state() -> Dictionary:
	snapshot_complete = false
	var values := {}
	for label: String in OTHERS:
		var card := scene.get_node_or_null(NodePath(label)) as MeshInstance3D
		_expect(card != null, "Required protected mesh exists: " + label)
		if card == null:
			return {}
		var material := card.material_override as ShaderMaterial
		_expect(material != null and material.shader != null and card.mesh != null, "Complete protected mesh/material: " + label)
		if material == null or material.shader == null or card.mesh == null:
			return {}
		values[label] = [card.material_override, card.material_override.shader, _parameters(card.material_override), card.mesh, card.transform, card.layers]
	snapshot_complete = true
	return values

func _preserved(material: ShaderMaterial, before: Dictionary, stage: String) -> bool:
	for key: String in before:
		if not key.begins_with("mountain_fog_"):
			_expect(material.get_shader_parameter(key) == before[key], stage + ": retained " + key)
	return true

func _material(material: ShaderMaterial, environment: Environment, expected: String, before: Dictionary, stage: String) -> bool:
	_expect(material != null and material.shader != null, stage + ": material and shader exist")
	if material == null or material.shader == null:
		return false
	_expect(material.shader.resource_path == expected, stage + ": shader")
	_expect(_preserved(material, before, stage) == true, stage + ": parameter comparison completed")
	if expected == DAY and environment != null:
		var density: Variant = material.get_shader_parameter("mountain_fog_density")
		var color: Variant = material.get_shader_parameter("mountain_fog_linear_color")
		var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
		_expect(material.get_shader_parameter("mountain_fog_enabled") == environment.fog_enabled, stage + ": actual enabled flag")
		_expect((typeof(density) == TYPE_FLOAT or typeof(density) == TYPE_INT) and is_finite(float(density)) and is_equal_approx(float(density), environment.fog_density), stage + ": actual density")
		_expect(color is Vector3 and color.is_finite() and color.is_equal_approx(Vector3(linear.r, linear.g, linear.b)), stage + ": exactly one linear conversion, no exposure multiplication")
	return true

func _stage(expected: String, stage: String) -> void:
	var world := scene.get_node_or_null("WorldEnvironment") as WorldEnvironment
	_expect(world != null, stage + ": required WorldEnvironment exists")
	if world == null:
		return
	var environment := world.environment
	var before := _stored(environment) if environment != null else {}
	var others := _other_state()
	_expect(snapshot_complete and others.size() == OTHERS.size(), stage + ": complete before snapshot, never empty-equals-empty")
	if failed:
		return
	# Two frames allow the production priority-1 Node callback to run, not a direct sync call.
	await process_frame
	await process_frame
	_expect(world.environment == environment and (environment == null or _stored(environment) == before), stage + ": actual Environment untouched")
	var after := _other_state()
	_expect(snapshot_complete and after.size() == OTHERS.size(), stage + ": complete after snapshot")
	if failed:
		return
	_expect(after == others, stage + ": all protected material/mesh/transform states untouched by bridge")
	_expect(mountain.material_override == original_material and mountain.mesh == original_mesh and mountain.transform == original_transform, stage + ": mountain identities unchanged")
	_expect(_material(original_material, environment, expected, mountain_parameters, stage) == true, stage + ": material checks completed")
	print("MEADOW_MOUNTAIN_ATMOSPHERE_STATE: " + stage + "; shader=" + original_material.shader.resource_path)
	completed_stages += 1

func _run() -> void:
	_source_checks()
	_expect(source_checks_complete, "Source checks completed without interrupted helper")
	if failed:
		quit(1)
		return
	var frozen := {}
	for path: String in ["res://scripts/meadow_mountain_atmosphere.gd", "res://shaders/meadow_mountain_fog.gdshaderinc", "res://scripts/meadow_mountain_relief.gd"]:
		frozen[path] = FileAccess.get_sha256(path)
	scene = (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	_expect(scene != null, "Main scene instantiated")
	if scene == null:
		quit(1)
		return
	root.add_child(scene)
	mountain = scene.get_node_or_null("DistantMountainRidge") as MeshInstance3D
	var weather = scene.get_node_or_null("LivingWeather")
	var bridge := scene.get_node_or_null("MountainAtmosphere")
	var world := scene.get_node_or_null("WorldEnvironment") as WorldEnvironment
	var wildlife := scene.get_node_or_null("LivingWildlife")
	_expect(mountain != null and weather != null and bridge != null and world != null and wildlife != null, "All required scene nodes exist")
	if failed:
		scene.free()
		quit(1)
		return
	original_material = mountain.material_override
	original_mesh = mountain.mesh
	_expect(original_material != null and original_material.shader != null and original_mesh != null and world.environment != null, "Required startup material/mesh/Environment resources exist")
	var initial_others := _other_state()
	_expect(snapshot_complete and initial_others.size() == OTHERS.size(), "Complete required-node preflight")
	if failed:
		scene.free()
		quit(1)
		return
	original_transform = mountain.transform
	mountain_parameters = _parameters(original_material)
	var original := world.environment
	_expect(weather.night_blend == 0.0 and original_material.shader.resource_path == DAY, "Setup synchronously selected DAY before first frame")
	_expect(bridge.get_script() == BRIDGE and bridge.process_priority == 1 and bridge.process_priority > weather.process_priority and bridge.is_processing(), "Actual active priority-1 bridge")
	weather.set_motion(false)
	weather.set_process(false)
	wildlife.set_process(false)
	await _stage(DAY, "startup")
	weather.toggle_time()
	for test: Array in [[0.5, DAY, "half-night"], [1.0, NATIVE, "night"]]:
		weather.advance_weather(1.6)
		_expect(is_equal_approx(weather.night_blend, test[0]), "Real weather endpoint " + str(test[2]))
		await _stage(test[1], test[2])
		var expected_architecture: String = V96.NATIVE if test[0] == 1.0 else V96.DAY
		for label: String in V96.ARCHITECTURE:
			var architecture := scene.get_node_or_null(NodePath(label)) as MeshInstance3D
			_expect(architecture != null, "Required architecture mesh exists: " + label)
			if architecture == null:
				continue
			var architecture_material := architecture.material_override as ShaderMaterial
			_expect(architecture_material != null and architecture_material.shader != null and architecture_material.shader.resource_path == expected_architecture, "Existing architecture day/native-night retained")
	weather.toggle_time()
	weather.advance_weather(1.6)
	await _stage(DAY, "half-day")
	weather.advance_weather(1.6)
	await _stage(DAY, "returned-day")
	_expect(weather.night_blend == 0.0 and weather.animation_clock == 0.0 and not weather.transitioning, "Returned stable day with paused clock")
	var original_state := _stored(original)
	for test: Dictionary in [
		{"name": "alternate", "shader": DAY, "values": {"fog_light_color": Color(0.25, 0.5, 0.75), "fog_light_energy": 1.7, "fog_density": 0.002}},
		{"name": "disabled", "shader": DAY, "values": {"fog_enabled": false}},
		{"name": "depth", "shader": NATIVE, "values": {"fog_mode": Environment.FOG_MODE_DEPTH}},
		{"name": "height", "shader": NATIVE, "values": {"fog_height_density": 0.2}},
		{"name": "scatter", "shader": NATIVE, "values": {"fog_sun_scatter": 0.3}},
		{"name": "aerial", "shader": NATIVE, "values": {"fog_aerial_perspective": 0.4}}]:
		var alternate := original.duplicate() as Environment
		for key: String in test.values:
			alternate.set(key, test.values[key])
		world.environment = alternate # Weather intentionally still retains original.
		await _stage(test.shader, test.name)
		_expect(weather.environment == original and _stored(original) == original_state, "Original cached Environment untouched")
		world.environment = original
		await _stage(DAY, test.name + "-restore")
	world.environment = null
	await _stage(NATIVE, "null-environment")
	world.environment = original
	await _stage(DAY, "null-restore")
	# Explicit nondefault arrays on a PRIVATE material exercise real shader swaps.
	var private_material := original_material.duplicate() as ShaderMaterial
	var windows := PackedVector4Array()
	var heights := PackedFloat32Array()
	for i in range(32):
		windows.append(Vector4(i / 32.0, 0.3, 0.01, 0.02))
	for i in range(25):
		heights.append(i * 0.03125)
	private_material.set_shader_parameter("lit_windows", windows)
	private_material.set_shader_parameter("soil_heights", heights)
	var private_before := _parameters(private_material)
	for night: float in [1.0, 0.5, 0.0]:
		BRIDGE.sync_material(private_material, original, night)
		_expect(_material(private_material, original, NATIVE if night == 1.0 else DAY, private_before, "private-arrays") == true, "Private array checks completed")
	var river := scene.get_node_or_null("ContinuousRiver") as MeshInstance3D
	_expect(river != null, "Required river mesh still exists")
	if river != null:
		var foreign := river.material_override as ShaderMaterial
		_expect(foreign != null and foreign.shader != null, "Required river material still exists")
		if foreign != null and foreign.shader != null:
			var foreign_before := _parameters(foreign)
			var foreign_shader := foreign.shader
			BRIDGE.sync_material(foreign, original, 0.0)
			_expect(foreign.shader == foreign_shader and _parameters(foreign) == foreign_before and _stored(original) == original_state, "Foreign material and Environment unchanged by direct helper")
	await _stage(DAY, "final-restored")
	_expect(completed_stages == 20, "All twenty asynchronous stages completed; interrupted stage cannot report PASS")
	# All environments restored before freeing the sole audit-owned scene.
	bridge.set_process(false)
	world.environment = original
	RenderingServer.global_shader_parameter_set("meadow_night", 0.0)
	RenderingServer.global_shader_parameter_set("meadow_clock", 0.0)
	scene.free()
	for path: String in frozen:
		_expect(FileAccess.get_sha256(path) == frozen[path], "Stable source during audit " + path)
	print("MEADOW_MOUNTAIN_ATMOSPHERE_AUDIT: %s; %d source/state checks; actual startup/process sync/day-half-night-return/alternate-disabled-fallback/arrays; NO GPU pixels, visual or performance acceptance" % ["FAIL" if failed else "PASS", checks])
	quit(1 if failed else 0)
