extends SceneTree
## Native GPU only. Frozen limestone source vs current; identical live includes.
## Solid texture inputs are sRGB samples, NOT a replacement mineral formula.
const SOURCE := "res://shaders/meadow_limestone.gdshader"
const BASELINE := "res://../artifacts/v107/meadow_limestone.v106-before.gdshader"
const BASELINE_SHA := "3265e7107901a405c17f3d99ba4f24f05a99ac3ce590e37b3b620f84c5a3219d"
const EPS := 2.0 / 255.0
const SIZE := Vector2i(128, 128)
var viewport: SubViewport
var card: MeshInstance3D
var done := false
var records: Array = []

func _initialize() -> void:
	root.disable_3d = true
	create_timer(60.0).timeout.connect(_timeout)
	_run.call_deferred()

func _timeout() -> void:
	if not done:
		push_error("ROCK_PIGMENT: FAIL timeout/runtime-aborted")
		quit(1)

func _check(ok: bool, label: String) -> bool:
	if not ok:
		push_error("ROCK_PIGMENT: FAIL " + label)
		quit(1)
	return ok

func _texture(value: float, alpha: float = 1.0) -> ImageTexture:
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(Color(value, value, value, alpha))
	return ImageTexture.create_from_image(image)

func _material(source: String) -> ShaderMaterial:
	for uniform: String in ["meadow_clock", "meadow_night"]:
		var declaration := "global uniform float " + uniform + ";"
		if not _check(source.count(declaration) == 1, "One isolated global " + uniform): return null
		source = source.replace(declaration, "uniform float " + uniform + ";")
	var material := ShaderMaterial.new()
	material.shader = Shader.new(); material.shader.code = source
	for uniform: String in ["limestone_texture", "meadow_texture"]:
		material.set_shader_parameter(uniform, _texture(0.2))
	material.set_shader_parameter("sunbreak_strength", 0.0)
	material.set_shader_parameter("meadow_clock", 0.0)
	return material

func _mesh(visibility: float, cap: float) -> ArrayMesh:
	var plane := PlaneMesh.new(); plane.size = Vector2(4, 4)
	var arrays := plane.get_mesh_arrays()
	var colours := PackedColorArray(); colours.resize(arrays[Mesh.ARRAY_VERTEX].size())
	colours.fill(Color(cap, 0.94, visibility, 1.0)); arrays[Mesh.ARRAY_COLOR] = colours
	var uv2 := PackedVector2Array(); uv2.resize(colours.size()); uv2.fill(Vector2.ONE)
	arrays[Mesh.ARRAY_TEX_UV2] = uv2
	var mesh := ArrayMesh.new(); mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

func _capture(material: ShaderMaterial) -> Image:
	card.material_override = material
	for frame in range(4): await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()

func _delta(a: Color, b: Color) -> float:
	return maxf(absf(a.r - b.r), maxf(absf(a.g - b.g), absf(a.b - b.b)))

func _run() -> void:
	if not _check(DisplayServer.get_name() != "headless" and not ProjectSettings.get_setting("rendering/shading/overrides/force_vertex_shading", false), "Real fragment GPU required"): return
	if not _check(FileAccess.get_sha256(BASELINE).to_lower() == BASELINE_SHA, "Exact frozen v106 baseline"): return
	var fingerprints := {}
	for path: String in [SOURCE, BASELINE, "res://shaders/meadow_palette.gdshaderinc", "res://shaders/meadow_surface.gdshaderinc", "res://shaders/meadow_mineral.gdshaderinc", "res://shaders/meadow_sunbreak.gdshaderinc"]:
		fingerprints[path] = FileAccess.get_sha256(path)
		if not _check(not str(fingerprints[path]).is_empty(), "Source/include exists " + path): return
	var before := _material(FileAccess.get_file_as_string(BASELINE))
	var current := _material(FileAccess.get_file_as_string(SOURCE))
	if not _check(before != null and current != null, "Both isolated materials ready"): return
	viewport = SubViewport.new(); viewport.size = SIZE; viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS; root.add_child(viewport)
	var env := Environment.new(); env.background_mode = Environment.BG_COLOR; env.background_color = Color.BLACK
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; env.ambient_light_color = Color.WHITE; env.ambient_light_energy = 0.2
	env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED; env.fog_enabled = false
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR; env.tonemap_exposure = 1.0
	var world := WorldEnvironment.new(); world.environment = env; viewport.add_child(world)
	card = MeshInstance3D.new(); card.position.y = 2; card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF; viewport.add_child(card)
	var camera := Camera3D.new(); camera.projection = Camera3D.PROJECTION_ORTHOGONAL; camera.size = 5
	camera.position = Vector3(0, 7, 0); camera.rotation_degrees.x = -90; viewport.add_child(camera); camera.make_current()
	var key := DirectionalLight3D.new(); key.shadow_enabled = false; key.light_color = Color.WHITE; viewport.add_child(key)
	# name, face RGB, face alpha, prefix enabled, night, turf cap, visibility, must reduce
	var cases := [["bright_open", .9, 1.0, true, 0.0, 0.0, 1.0, true],
		["bright_sheltered", .9, 1.0, true, 0.0, 0.0, .25, true],
		["dark_crack", .04, 1.0, true, 0.0, 0.0, 1.0, false],
		["face_alpha_zero", .9, 0.0, true, 0.0, 0.0, 1.0, false],
		["prefix_zero", .9, 1.0, false, 0.0, 0.0, .25, false],
		["night_open", .9, 1.0, true, 1.0, 0.0, 1.0, false],
		["night_sheltered", .9, 1.0, true, 1.0, 0.0, .25, false],
		["turf_cap_one", .9, 1.0, true, 0.0, 1.0, 1.0, false]]
	print("ROCK_PIGMENT_FIXTURE: 128x128 private viewport; dry y2 UP-normal plane; ROI(32,32,64,64); solid mineral/meadow texture .2; UV2=1,1; sunbreak0; native white direct + .2 ambient; linear tonemap; NO exact brightness formula")
	print("ROCK_PIGMENT_SOURCES: " + JSON.stringify(fingerprints))
	for test: Array in cases:
		var mesh := _mesh(float(test[6]), float(test[5])); card.mesh = mesh
		var face := _texture(float(test[1]), float(test[2]))
		for material: ShaderMaterial in [before, current]:
			material.set_shader_parameter("escarpment_texture", face)
			material.set_shader_parameter("rock_ao_vertex_count", mesh.surface_get_array_len(0) if test[3] else 0)
			material.set_shader_parameter("meadow_night", test[4])
		key.rotation_degrees = Vector3(-28, -145, 0) if test[4] == 1.0 else Vector3(-50, 0, 0)
		key.light_energy = 1.2 if test[4] == 1.0 else 1.4
		var a := await _capture(before); var b := await _capture(current); var restored := await _capture(before)
		for sample: Image in [a, b, restored]:
			if not _check(sample != null and not sample.is_empty() and sample.get_size() == SIZE, "Valid readback " + str(test[0])): return
		var mean_a := 0.0; var mean_b := 0.0; var change := 0.0; var stability := 0.0
		var increase := 0.0; var peak := 0.0; var reduced := 0
		for y in range(32, 96):
			for x in range(32, 96):
				var ca := a.get_pixel(x, y); var cb := b.get_pixel(x, y); var cr := restored.get_pixel(x, y)
				for colour: Color in [ca, cb, cr]:
					if not _check(Vector4(colour.r, colour.g, colour.b, colour.a).is_finite(), "Finite RGB readback"): return
				mean_a += ca.get_luminance(); mean_b += cb.get_luminance()
				change = maxf(change, _delta(ca, cb)); stability = maxf(stability, _delta(ca, cr))
				increase = maxf(increase, maxf(cb.r - ca.r, maxf(cb.g - ca.g, cb.b - ca.b)))
				peak = maxf(peak, maxf(_delta(ca, Color.BLACK), maxf(_delta(cb, Color.BLACK), _delta(cr, Color.BLACK))))
				if ca.get_luminance() - cb.get_luminance() > EPS: reduced += 1
		mean_a /= 4096.0; mean_b /= 4096.0
		var response: bool = mean_a - mean_b >= EPS and increase <= EPS if test[7] else change <= EPS
		# Intentionally dark fissures need not clear the bright baseline's .04.
		# Reuse the existing .02 readable-output floor on BOTH sides of this
		# equality control (5.1 display codes, still above the 2-code delta gate).
		# Texture inputs, lights, all response/delta/restoration gates stay fixed.
		var baseline_floor := .02 if test[0] == "dark_crack" else .04
		var readable := mean_a > baseline_floor and mean_b > .02 and peak < .98
		var passed := response and stability <= EPS and readable
		var record := {"case":test[0], "pixels":4096, "before":mean_a, "after":mean_b, "max_delta":change, "max_increase":increase, "restored_error":stability, "reduced_pixels":reduced, "baseline_floor":baseline_floor, "output_floor":.02, "peak":peak, "readable":readable, "response_pass":response, "restored_pass":stability <= EPS, "pass":passed}
		records.append(record); print("ROCK_PIGMENT_CASE: " + JSON.stringify(record))
		if not _check(passed, str(test[0])): return
	for path: String in fingerprints:
		if not _check(FileAccess.get_sha256(path) == fingerprints[path], "Source/include stable during run " + path): return
	if not _check(records.size() == 8, "All eight cases completed"): return
	done = true; viewport.free(); print("ROCK_PIGMENT: PASS; controlled source-isolation only, NOT actual cliff/visual acceptance or a repeat of BRDF/AO tests"); quit(0)
