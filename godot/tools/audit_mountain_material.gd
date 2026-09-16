extends SceneTree
## Source/state only. Main runs once after integration; no GPU/visual acceptance.
const MOUNTAIN := "res://shaders/meadow_mountain.gdshader"
const DISTANT := "res://shaders/meadow_distant_cutout.gdshader"
const INCLUDE := "res://shaders/meadow_mountain.gdshaderinc"
const NATIVE := "res://shaders/meadow_architecture.gdshader"
const DAY := "res://shaders/meadow_architecture_day.gdshader"
const SURFACE_COMPACT := "cefad77c96291e02b78800cb7fac489a75d8f71d4cfad5fff7d74b21f8c7a3b9"
const SCENE_COMPACT := "d74b110027cc2140d43a1bc21b842561cee93487784f7b4d3e4a6f72f0f46778"
const ARCHITECTURE := ["IndependentCastleHill", "DistantVillage"]
const WEATHER_FILL := ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]
const PROTECTED := {
	DISTANT: "5d12dffbb8757f07288065f7cad23134c026284d51d6fa4f1a1c3a183fcec07d",
	NATIVE: "95fdba083314d0ee0dd36cccea9d7365c985060cbcc859ad17a8c91db61fdd7b",
	DAY: "b7317370b1c3d6bffe288e578132b4fcb84f116bedbfee256ca754dc2990d028",
	"res://scripts/meadow_weather.gd": "7afda1a94783bf28b48f860fa6a174220cc63a387d14ea094b16953c8ae4d5c9",
	"res://scripts/meadow_architecture_fog.gd": "306840f13c2ed280d56bb524a341532feff8f049a5cea0f6c4e4da5eb95ea9fd",
	"res://shaders/meadow_architecture_fog.gdshaderinc": "b69a67edbc81b63d7fd4221679bae5aec2419aa77836ee917397c678c62f743e",
	"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08",
	"res://shaders/meadow_sky.gdshader": "374a45517bcbe5b8f27788938f4f9e25f7721e9e7368811fef1105ad7d90d37b",
	"res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d",
	"res://shaders/meadow_leaves.gdshader": "dd218655817268a12de2be516df8d9280edb309502fb3228f0604450b5310335",
	"res://assets/backgrounds/mountain-ridge-v39.png": "ec1f06815d2ca2d8cababd3c3a4b7fd44ef92b153514ac3dbc564d0c38cc7d49"}
var failed := false
var checks := 0

func _initialize() -> void:
	_run.call_deferred()

func _expect(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		failed = true
		push_error("MEADOW_MOUNTAIN_MATERIAL: FAIL; " + label)

func _compact(source: String) -> String:
	var regex := RegEx.new()
	regex.compile("\\s+")
	return regex.sub(source, "", true)

func _text(path: String) -> String:
	return FileAccess.get_file_as_string(path).replace("\r\n", "\n")

func _source_checks() -> void:
	for path: String in PROTECTED:
		_expect(FileAccess.get_sha256(path).to_lower() == PROTECTED[path], "Protected " + path)
	if not FileAccess.file_exists(MOUNTAIN):
		_expect(false, "Mountain wrapper not integrated yet")
		return
	var wrapper := _text(MOUNTAIN)
	# Comments may document the new wrapper; executable old render modes stay exact.
	var comments := RegEx.new()
	comments.compile("(?s)/\\*.*?\\*/|//[^\\n]*")
	var wrapper_code := comments.sub(wrapper, "", true)
	_expect(wrapper_code.count("#define MEADOW_MOUNTAIN") == 1, "One mountain opt-in macro")
	wrapper_code = wrapper_code.replace("#define MEADOW_MOUNTAIN", "")
	_expect(_compact(wrapper_code) == _compact(comments.sub(_text(DISTANT), "", true)), "Only macro differs from original distant wrapper")
	# Strip only balanced mountain-owned preprocessor blocks, never architecture code.
	var retained := ""
	var depth := 0
	var blocks := 0
	for line: String in _text("res://shaders/meadow_cutout_surface.gdshaderinc").split("\n"):
		var stripped := line.strip_edges()
		if depth == 0 and stripped == "#ifdef MEADOW_MOUNTAIN":
			depth = 1
			blocks += 1
		elif depth > 0:
			if stripped.begins_with("#if"):
				depth += 1
			elif stripped == "#endif":
				depth -= 1
			elif depth == 1 and (stripped == "#else" or stripped.begins_with("#elif")):
				_expect(false, "No mountain #else may alter nonmountain path")
		else:
			retained += line + "\n"
	_expect(depth == 0 and blocks > 0, "Balanced mountain-only insertions")
	_expect(_compact(retained).sha256_text() == SURFACE_COMPACT, "Nonmountain surface exact v95 apart from whitespace")
	_profile_checks(comments)
	# Remove exactly the approved assignment and contiguous Web opt-in block.
	# The original snapshot/signature stays fixed; real cache rebake is main's job.
	var scene_text := _text("res://scripts/meadow_scene.gd")
	var assignment := '\tmountains.material_override.shader = preload("res://shaders/meadow_mountain.gdshader")\n'
	var opt_in := '\t\tif JavaScriptBridge.eval("new URLSearchParams(location.search).get(\'mountain_audit\') === \'1\'"):\n' \
		+ '\t\t\tvar mountain_audit = load("res://tools/audit_mountain_response.gd")\n' \
		+ '\t\t\tmountain_audit.run.call_deferred(self)\n'
	_expect(scene_text.count(assignment) == 1 and scene_text.count(opt_in) == 1, "Exactly one approved assignment and three-line opt-in block")
	scene_text = scene_text.replace(assignment, "").replace(opt_in, "")
	_expect(_compact(scene_text).sha256_text() == SCENE_COMPACT, "No scene changes outside approved four lines")
	var export_config := ConfigFile.new()
	_expect(export_config.load("res://export_presets.cfg") == OK, "Read export configuration")
	var exports: Variant = export_config.get_value("preset.0", "export_files", PackedStringArray())
	for path: String in [MOUNTAIN, DAY, "res://scripts/meadow_architecture_fog.gd", "res://tools/audit_mountain_response.gd"]:
		_expect(path in exports, "Explicit export resource " + path)
	_expect(str(export_config.get_value("preset.0", "include_filter", "")).contains("*.gdshaderinc"), "Shader includes exported")
	print("MEADOW_MOUNTAIN_SOURCE: wrapper_sha=" + FileAccess.get_sha256(MOUNTAIN) + "; night branch semantics and profile ROI require independent source/GPU review")

func _profile_checks(comments: RegEx) -> void:
	if not FileAccess.file_exists(INCLUDE):
		_expect(false, "Mountain include not integrated yet")
		return
	var source := comments.sub(_text(INCLUDE), "", true)
	var compact := _compact(source)
	# Deliberately a small source contract, NOT a GLSL interpreter or pixel test.
	var guard := compact.find("if(day<=0.0){return;}")
	_expect(compact.contains("floatday=clamp(day_weight,0.0,1.0)*clamp(mountain_day_strength,0.0,1.0);"), "Bounded day input times bounded treatment strength; exact zero at night")
	for write: String in ["surface_normal=", "surface_albedo*=", "surface_emission*="]:
		_expect(guard >= 0 and compact.find(write) > guard, "Night guard precedes " + write)
	var surface := _compact(comments.sub(_text("res://shaders/meadow_cutout_surface.gdshaderinc"), "", true))
	_expect(surface.contains("meadow_mountain_surface(uv,clamp(1.0-meadow_night,0.0,1.0),mat3(VIEW_MATRIX),NORMAL,ALBEDO,EMISSION);"), "Actual full-source UV, day endpoint and view-space call contract")
	var regex := RegEx.new()
	regex.compile("meadow_mountain_plane\\(source_uv,\\s*vec2\\(([^)]+)\\),\\s*vec2\\(([^)]+)\\),\\s*([^,]+),\\s*vec3\\(([^)]+)\\)\\)")
	var matches := regex.search_all(source)
	_expect(matches.size() >= 6 and matches.size() <= 8, "Designed bounded 6-8 broad profiles, not a quality score")
	var records: Array[Dictionary] = []
	for match_value: RegExMatch in matches:
		var components: Array[float] = []
		for group in range(1, 5):
			for token: String in match_value.get_string(group).split(","):
				_expect(token.strip_edges().is_valid_float() and is_finite(token.to_float()), "Finite literal profile component")
				components.append(token.to_float())
		if components.size() != 8:
			_expect(false, "Profile vector dimensions")
			continue
		var centre := Vector2(components[0], components[1])
		var radius := Vector2(components[2], components[3])
		var facing := Vector3(components[5], components[6], components[7])
		_expect(centre.x >= 0.0 and centre.x <= 1.0 and centre.y >= 0.0 and centre.y <= 1.0, "Profile centre in source UV")
		_expect(radius.x > 0.0 and radius.y > 0.0 and radius.x <= 1.0 and radius.y <= 1.0, "Nondegenerate bounded profile radius")
		_expect(facing.length_squared() > 0.000001 and facing.z > 0.0, "Nonzero outward world-facing profile")
		records.append({"centre_uv": str(centre), "radius_uv": str(radius), "lean": components[4], "world_normal": str(facing.normalized())})
	print("MEADOW_MOUNTAIN_PROFILES: " + JSON.stringify(records) + "; source regions only, NOT measured alpha-mask coverage or GPU response")

func _parameters(material: ShaderMaterial) -> Dictionary:
	var values := {}
	for entry: Dictionary in material.shader.get_shader_uniform_list():
		values[str(entry.name)] = material.get_shader_parameter(entry.name)
	return values.duplicate(true)

func _run() -> void:
	_source_checks()
	if failed:
		quit(1)
		return
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate() as Node3D
	root.add_child(scene) # One real world; no awaits, second world, bake or writes.
	var weather = scene.get_node("LivingWeather")
	var saved := {}
	for key: String in ["night_blend", "night_target", "motion_enabled", "reduced_motion", "animation_clock", "transition_elapsed", "transition_start", "transitioning", "reflection_revision", "ui_interval"]:
		saved[key] = weather.get(key)
	var processing: bool = weather.is_processing()
	var probe_transform: Transform3D = weather.probe.transform
	var cards := {}
	for node: Node in scene.find_children("*", "MeshInstance3D", true, false):
		var card := node as MeshInstance3D
		if card.material_override is ShaderMaterial:
			var material := card.material_override as ShaderMaterial
			cards[card] = {"material": material, "shader": material.shader, "parameters": _parameters(material), "mesh": card.mesh, "transform": card.transform, "layers": card.layers, "shadow": card.cast_shadow}
	var mountain := scene.get_node("DistantMountainRidge") as MeshInstance3D
	_expect(mountain.mesh is QuadMesh, "Original Quad topology")
	_expect(mountain.position == Vector3(0, -5.5, -310), "Original mountain placement")
	if mountain.mesh is QuadMesh:
		_expect(mountain.mesh.size.is_equal_approx(Vector2(650, 650.0 / 3.0 * 0.4)), "Original compressed silhouette")
		_expect(mountain.mesh.center_offset.is_equal_approx(Vector3(0, 0.34 * 650.0 / 3.0 * 0.4, 0)), "Original anchor")
	_expect(mountain.material_override.get_shader_parameter("face_camera") == false, "Fixed mountain orientation")
	_expect(mountain.material_override.get_shader_parameter("asset_texture") == scene.HORIZON, "Original actual texture")
	_expect(weather.night_blend == 0.0 and not weather.transitioning, "Actual day startup")
	weather.set_process(false)
	weather.set_motion(false)
	_verify(cards, 0.0, "startup")
	weather.toggle_time()
	weather.advance_weather(1.6)
	_expect(is_equal_approx(weather.night_blend, 0.5), "Actual half-night")
	_verify(cards, 0.5, "half-night")
	weather.advance_weather(1.6)
	_expect(weather.night_blend == 1.0 and not weather.transitioning, "Actual night endpoint")
	_verify(cards, 1.0, "night")
	weather.toggle_time()
	weather.advance_weather(3.2)
	_expect(weather.night_blend == 0.0 and not weather.transitioning, "Returned day endpoint")
	_verify(cards, 0.0, "returned-day")
	# Failed expectations do not bypass cleanup. This audit owns the scene.
	weather._apply_lighting(float(saved.night_blend))
	for key: String in saved:
		weather.set(key, saved[key])
	weather.probe.transform = probe_transform
	RenderingServer.global_shader_parameter_set("meadow_clock", saved.animation_clock)
	weather.set_process(processing)
	for card: MeshInstance3D in cards:
		var before: Dictionary = cards[card]
		var material: ShaderMaterial = before.material
		card.material_override = material
		material.shader = before.shader
		for key: String in before.parameters:
			material.set_shader_parameter(key, before.parameters[key])
	scene.free()
	print("MEADOW_MOUNTAIN_MATERIAL_AUDIT: %s; %d source/state checks; one scene; NO GPU, night-pixel, normal-direction, ROI-quality or performance acceptance" % ["FAIL" if failed else "PASS", checks])
	quit(1 if failed else 0)

func _verify(cards: Dictionary, blend: float, stage: String) -> void:
	var mountain_count := 0
	for card: MeshInstance3D in cards:
		var before: Dictionary = cards[card]
		var material := card.material_override as ShaderMaterial
		_expect(material == before.material and card.mesh == before.mesh and card.transform == before.transform and card.layers == before.layers and card.cast_shadow == before.shadow, stage + ": identity/geometry/layers " + str(card.name))
		if material == null:
			continue
		var expected: String = before.shader.resource_path
		if ARCHITECTURE.has(str(card.name)):
			expected = NATIVE if blend == 1.0 else DAY
		if card.name == "DistantMountainRidge":
			expected = MOUNTAIN
		_expect(material.shader.resource_path == expected, stage + ": shader " + str(card.name))
		if material.shader.resource_path == MOUNTAIN:
			mountain_count += 1
		for key: String in before.parameters:
			if card.name == "DepthAwareFocus" and key == "scene_exposure":
				var exposure: Variant = material.get_shader_parameter(key)
				_expect((typeof(exposure) == TYPE_FLOAT or typeof(exposure) == TYPE_INT) and is_finite(float(exposure)) and is_equal_approx(float(exposure), lerpf(2.0, 2.2, blend)), stage + ": original focus exposure curve")
				continue
			if key == "painted_fill" and WEATHER_FILL.has(str(card.name)):
				continue # Existing weather source hash and original lighting audit own this curve.
			if key.begins_with("architecture_fog_") and ARCHITECTURE.has(str(card.name)) and blend != 0.0:
				continue # DAY parameters are not exposed by the native night shader.
			_expect(material.get_shader_parameter(key) == before.parameters[key], stage + ": preserved " + str(card.name) + "/" + key)
		if card.name == "DistantMountainRidge":
			for key: String in _parameters(material):
				var value: Variant = material.get_shader_parameter(key)
				if typeof(value) == TYPE_FLOAT:
					_expect(is_finite(float(value)), stage + ": finite mountain uniform " + key)
	_expect(mountain_count == 1, stage + ": exactly one mountain material consumer")
	print("MEADOW_MOUNTAIN_STATE: %s; night=%.2f; material state is NOT shader fragment output" % [stage, blend])
