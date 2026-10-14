extends SceneTree
## Standalone native-GPU fixture: no main scene, globals, baseline strings or files changed.
const SOURCE := "res://shaders/meadow_limestone.gdshader"
const EPS := 2.0 / 255.0
const SIZE := Vector2i(128, 128)
var viewport: SubViewport
var card: MeshInstance3D
var material: ShaderMaterial
var records: Array = []
var done := false

func _initialize() -> void:
	root.disable_3d = true
	create_timer(60.0).timeout.connect(_timeout)
	_run.call_deferred()

func _timeout() -> void:
	if not done: push_error("ROCK_LIGHT_RESPONSE: FAIL timeout/runtime-aborted"); quit(1)

func _check(ok: bool, label: String) -> bool:
	if not ok: push_error("ROCK_LIGHT_RESPONSE: FAIL " + label); quit(1)
	return ok

func _mesh(visibility: float) -> ArrayMesh:
	var plane := PlaneMesh.new()
	plane.size = Vector2(4, 4)
	var arrays := plane.get_mesh_arrays()
	var colours := PackedColorArray()
	colours.resize(arrays[Mesh.ARRAY_VERTEX].size()); colours.fill(Color(0, 0.94, visibility, 1))
	arrays[Mesh.ARRAY_COLOR] = colours
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

func _capture(mesh: ArrayMesh, enabled: bool) -> Image:
	card.mesh = mesh
	material.set_shader_parameter("rock_ao_vertex_count", mesh.surface_get_array_len(0) if enabled else 0)
	for frame in range(4): await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()

func _delta(a: Color, b: Color) -> float:
	return maxf(absf(a.r - b.r), maxf(absf(a.g - b.g), absf(a.b - b.b)))

func _run() -> void:
	if not _check(DisplayServer.get_name() != "headless" and not ProjectSettings.get_setting("rendering/shading/overrides/force_vertex_shading", false), "real fragment GPU required"): return
	var original := load(SOURCE) as Shader
	if not _check(original != null, "actual shader exists"): return
	var code := original.code
	for name: String in ["meadow_clock", "meadow_night"]:
		if not _check(code.count("global uniform float " + name + ";") == 1, "one isolated global " + name): return
		code = code.replace("global uniform float " + name + ";", "uniform float " + name + ";")
	material = ShaderMaterial.new(); material.shader = Shader.new(); material.shader.code = code
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8); image.fill(Color(0.7, 0.7, 0.7, 1))
	var texture := ImageTexture.create_from_image(image)
	for uniform: String in ["limestone_texture", "escarpment_texture", "meadow_texture"]: material.set_shader_parameter(uniform, texture)
	material.set_shader_parameter("sunbreak_strength", 0.0); material.set_shader_parameter("meadow_clock", 0.0)
	viewport = SubViewport.new(); viewport.size = SIZE; viewport.own_world_3d = true; viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS; root.add_child(viewport)
	var env := Environment.new(); env.background_mode = Environment.BG_COLOR; env.background_color = Color.BLACK
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; env.ambient_light_color = Color.WHITE; env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	env.fog_enabled = false; env.tonemap_mode = Environment.TONE_MAPPER_LINEAR; env.tonemap_exposure = 1.0
	var world := WorldEnvironment.new(); world.environment = env; viewport.add_child(world)
	card = MeshInstance3D.new(); card.position.y = 2; card.material_override = material; card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF; viewport.add_child(card)
	var camera := Camera3D.new(); camera.projection = Camera3D.PROJECTION_ORTHOGONAL; camera.size = 5; camera.position = Vector3(0, 7, 0); camera.rotation_degrees.x = -90; viewport.add_child(camera); camera.make_current()
	var key := DirectionalLight3D.new(); key.shadow_enabled = false; viewport.add_child(key)
	var lamp := OmniLight3D.new(); lamp.position = Vector3(0, 6, 0); lamp.omni_range = 20; lamp.shadow_enabled = false; viewport.add_child(lamp)
	var clear := _mesh(1.0); var sheltered := _mesh(0.25)
	var cases := [["day", 0.0, "dir", Vector3(-34,72,0), Color(1,.84,.62), 1.90, .64],
		["moon", 1.0, "dir", Vector3(-28,-145,0), Color(.65,.79,1), 1.20, .91],
		["bounce_day", 0.0, "dir", Vector3(-58,-112,0), Color(.62,.72,.88), .18, .64],
		["bounce_night", 1.0, "dir", Vector3(-38,32,0), Color(.52,.61,.75), .32, .91]]
	for night: float in [0.0, 1.0]:
		for kind: String in ["omni", "ambient", "zero"]: cases.append([kind + str(int(night)), night, kind, Vector3.ZERO, Color.WHITE, 0.0, .385 if kind == "ambient" else 1.0])
	print("ROCK_LIGHT_FIXTURE: 128x128; fixed UP normal, solid textures, dry y2; ROI=Rect2i(32,32,64,64); linear tonemap; sunbreak0; source_sha=" + original.code.sha256_text())
	print("ROCK_LIGHT_INCLUDE_SHA: " + str(load("res://shaders/meadow_sunbreak.gdshaderinc").get("code")).sha256_text())
	for test: Array in cases:
		material.set_shader_parameter("meadow_night", test[1])
		key.rotation_degrees = test[3]; key.light_color = test[4]; key.light_energy = test[5] if test[2] == "dir" else 0.0
		lamp.light_energy = 3.2 if test[2] == "omni" else 0.0; env.ambient_light_energy = .32 if test[2] == "ambient" else 0.0
		var a := await _capture(clear, true); var b := await _capture(sheltered, true); var off := await _capture(sheltered, false)
		for sample: Image in [a, b, off]:
			if not _check(sample != null and not sample.is_empty() and sample.get_size() == SIZE, "valid readback " + str(test[0])): return
		var before := 0.0; var after := 0.0; var error := 0.0; var control := 0.0; var peak := 0.0
		for y in range(32, 96):
			for x in range(32, 96):
				var ca := a.get_pixel(x,y); var cb := b.get_pixel(x,y); var co := off.get_pixel(x,y)
				var predicted := (ca.srgb_to_linear() * float(test[6])).linear_to_srgb()
				before += ca.get_luminance(); after += cb.get_luminance()
				error = maxf(error, _delta(predicted, cb)); control = maxf(control, _delta(ca, co))
				peak = maxf(peak, maxf(_delta(ca, Color.BLACK), maxf(_delta(cb, Color.BLACK), _delta(co, Color.BLACK))))
		before /= 4096.0; after /= 4096.0
		var has_signal: bool = peak <= EPS if test[2] == "zero" else before > .04 and peak < .98
		var response: bool = before - after >= 1.0 / 255.0 if float(test[6]) < 1.0 else true
		var passed := has_signal and response and error <= EPS and control <= EPS
		var record := {"case":test[0], "pixels":4096, "before":before, "after":after, "linear_factor":test[6], "max_error":error, "gate_off_error":control, "pass":passed}
		records.append(record); print("ROCK_LIGHT_CASE: " + JSON.stringify(record))
		if not _check(passed, str(test[0])): return
	if not _check(records.size() == 10, "all ten cases completed"): return
	done = true; viewport.free(); print("ROCK_LIGHT_RESPONSE: PASS; controlled lighting only, not actual cliff/visual acceptance"); quit(0)
