extends RefCounted
## Opt-in run(existing_scene): one private viewport; no world/cache rebuild or globals changed.
## Controlled meshes + actual material parameters; not semantic/full-scene GPU acceptance.
const SIZE := Vector2i(320, 192)
const EPS := 2.0 / 255.0 # Registered maximum RGB error, not mean-error masking.
const MIN_PIXELS := 200
const MARKER := "MEADOW_SUNBREAK_LIGHTING_AUDIT"
const MATERIALS := {"ground": "ContinuousMeadow", "leaves": "LivingMeadowUnderstory",
	"middle_leaves": "MiddleMeadowBrush", "limestone": "SolidLimestoneGeology", "cutout": "OldOakOnShelf"}
var viewport: SubViewport
var environment: Environment
var card: MeshInstance3D
var camera: Camera3D
var key: DirectionalLight3D
var bounce: DirectionalLight3D
var lamp: OmniLight3D
var failed := false
var records: Array[Dictionary] = []
var source_hashes := {}
var checks := 0

func _text(path: String) -> String:
	# Export may remap Shader/ShaderInclude resources; do not require loose source files.
	if FileAccess.file_exists(path): return FileAccess.get_file_as_string(path)
	var resource := load(path)
	if resource is Shader or resource is ShaderInclude: return str(resource.get("code"))
	return ""

static func run(scene: Node3D) -> bool:
	var probe = (load("res://tools/audit_sunbreak_lighting.gd") as GDScript).new()
	var completed: Variant = await probe._run(scene)
	if is_instance_valid(probe.viewport): probe.viewport.free()
	var passed: bool = completed == true and not probe.failed and probe.records.size() == MATERIALS.size() * 8
	var baseline_hashes := {}
	for name: String in BASELINE: baseline_hashes[name] = str(BASELINE[name]).sha256_text()
	print("MEADOW_SUNBREAK_LIGHTING: " + JSON.stringify({"records": probe.records,
		"checks": probe.checks, "source_hashes": probe.source_hashes, "baseline_sha256": baseline_hashes, "size": str(SIZE),
		"max_rgb_error_gate": EPS, "min_mask_pixels": MIN_PIXELS,
		"day_reference": "native BRDF; only old pigment-cloud neutralized on dry land; night original",
		"scope": "controlled geometry/material lighting; no main scene construction, no global mutation; no visual/performance acceptance",
		"pass": passed}))
	if passed: print(MARKER + ": PASS; native night/day-clear parity; sun-only attenuation; ambient/zero/bounce/omni controls")
	else: push_error(MARKER + ": FAIL; inspect per-case native parity/control/coverage and runtime errors")
	return passed

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failed = true
		push_error(MARKER + ": FAIL; " + label)
	return value

func _expand(path: String, before: bool, depth: int = 0) -> String:
	if not _ok(depth < 12, "Finite shader include tree"): return ""
	var name := path.get_file()
	var source: String = BASELINE[name] if before and BASELINE.has(name) else _text(path)
	if not _ok(not source.is_empty(), "Shader source " + path): return ""
	if not (before and BASELINE.has(name)): source_hashes[path] = source.sha256_text()
	var include := RegEx.new()
	include.compile('#include\\s+"([^"]+)"')
	for match_result in include.search_all(source):
		var replacement := _expand(match_result.get_string(1), before, depth + 1)
		if replacement.is_empty(): return ""
		source = source.replace(match_result.get_string(), replacement)
	return source

func _shader(path: String, before: bool, mask: bool = false) -> Shader:
	var code := _expand(path, before)
	if failed: return null
	# Shader-local copies make true night1/clock0 possible without touching the running world.
	for name: String in ["meadow_night", "meadow_clock"]:
		if not _ok(code.count("global uniform float " + name + ";") == 1, "Exactly one isolated global " + name): return null
		code = code.replace("global uniform float " + name + ";", "uniform float " + name + ";")
	if before:
		var declaration := "uniform bool audit_clear_day_cloud = false;\n"
		code = code.replace("shader_type spatial;", "shader_type spatial;\n" + declaration)
		var call := "meadow_cloud_light(p.xz, meadow_clock, meadow_night)" if path.ends_with("meadow_limestone.gdshader") else "meadow_cloud_light(p, meadow_clock, meadow_night)"
		if not path.ends_with("meadow_cutout.gdshader"):
			if not _ok(code.count(call) == 1, "Exactly one legacy pigment-cloud call"): return null
			var clear := "mix(1.0, " + call + ", submerged)" if path.ends_with("meadow_ground.gdshader") else "1.0"
			code = code.replace(call, "((audit_clear_day_cloud && meadow_night == 0.0) ? " + clear + " : " + call + ")")
	if mask:
		# Retain original vertex and alpha/discard code; only final shaded output becomes an ID.
		var render := RegEx.new()
		render.compile("render_mode[^;]+;")
		code = render.sub(code, "render_mode cull_disabled, unshaded;", true)
		var start := code.find("void fragment()")
		if not _ok(start >= 0, "Mask fragment exists"): return null
		var bracket := code.find("{", start)
		var nesting := 1
		var end := bracket + 1
		while nesting > 0 and end < code.length():
			if code[end] == "{": nesting += 1
			elif code[end] == "}": nesting -= 1
			end += 1
		if not _ok(nesting == 0, "Mask fragment closes"): return null
		code = code.insert(end - 1, "\nALBEDO = vec3(1.0); EMISSION = vec3(0.0);\n")
	var shader := Shader.new()
	shader.code = code
	return shader

func _mesh() -> ArrayMesh:
	# Three spatially separated curved patches exercise front/back diffuse, GGX and BACKLIGHT.
	var sphere := SphereMesh.new()
	sphere.radius = 2.5
	sphere.height = 5.0
	sphere.radial_segments = 16
	sphere.rings = 8
	var input := sphere.get_mesh_arrays()
	var output := []
	output.resize(Mesh.ARRAY_MAX)
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var colors := PackedColorArray()
	var uv := PackedVector2Array()
	var uv2 := PackedVector2Array()
	var indices: PackedInt32Array = input[Mesh.ARRAY_INDEX]
	for x: float in [-32.0, -12.0, 8.0]:
		for i: int in indices:
			var p: Vector3 = input[Mesh.ARRAY_VERTEX][i] + Vector3(x, 3.5, -40)
			vertices.append(p)
			normals.append(input[Mesh.ARRAY_NORMAL][i])
			colors.append(Color(0.9, 0.85, 0.8, 0.65))
			uv.append(input[Mesh.ARRAY_TEX_UV][i])
			uv2.append(Vector2(0.6, 0))
	output[Mesh.ARRAY_VERTEX] = vertices
	output[Mesh.ARRAY_NORMAL] = normals
	output[Mesh.ARRAY_COLOR] = colors
	output[Mesh.ARRAY_TEX_UV] = uv
	output[Mesh.ARRAY_TEX_UV2] = uv2
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, output)
	return mesh

func _rig(scene: Node3D) -> void:
	viewport = SubViewport.new()
	viewport.size = SIZE
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.add_child(viewport)
	var world := WorldEnvironment.new()
	environment = Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.5, 0.6, 0.7)
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.fog_enabled = false
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	world.environment = environment
	viewport.add_child(world)
	card = MeshInstance3D.new()
	card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	viewport.add_child(card)
	camera = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.far = 1000.0
	viewport.add_child(camera)
	key = DirectionalLight3D.new()
	bounce = DirectionalLight3D.new()
	lamp = OmniLight3D.new()
	for light: Light3D in [key, bounce, lamp]:
		light.shadow_enabled = false
		viewport.add_child(light)

func _lights(kind: String) -> void:
	environment.ambient_light_energy = 0.0
	key.rotation_degrees = Vector3(-34, 72, 0)
	key.light_color = Color(1, 0.84, 0.62)
	key.light_energy = 1.90 if kind == "sun" else 0.0
	bounce.rotation_degrees = Vector3(-58, -112, 0)
	bounce.light_color = Color(0.62, 0.72, 0.88)
	bounce.light_energy = 0.18 if kind == "bounce" else 0.0
	lamp.light_energy = 0.0
	if kind == "night":
		key.rotation_degrees = Vector3(-28, -145, 0)
		key.light_color = Color(0.65, 0.79, 1)
		key.light_energy = 1.20
		bounce.rotation_degrees = Vector3(-38, 32, 0)
		bounce.light_energy = 0.32
		bounce.light_color = Color(0.52, 0.61, 0.75)
	if kind == "ambient": environment.ambient_light_energy = 0.32
	if kind == "omni":
		lamp.position = card.global_transform * card.mesh.get_aabb().get_center() + Vector3(0, 8, 6)
		lamp.omni_range = 80.0
		lamp.light_color = Color(1, 0.7, 0.4)
		lamp.light_energy = 3.2

func _capture(material: ShaderMaterial, kind: String, night: float, strength: float, clear: bool) -> Image:
	_lights(kind)
	material.set_shader_parameter("meadow_night", night)
	material.set_shader_parameter("meadow_clock", 0.0)
	var has_strength := false
	for property: Dictionary in material.shader.get_shader_uniform_list():
		if property.name == "sunbreak_strength": has_strength = true
	if has_strength: material.set_shader_parameter("sunbreak_strength", strength)
	else: material.set_shader_parameter("audit_clear_day_cloud", clear)
	card.material_override = material
	for frame in range(4): await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	if not _ok(image != null and not image.is_empty() and image.get_size() == SIZE, "Valid GPU readback"): return null
	return image

func _pixels(mask: Image) -> Array[Vector2i]:
	var pixels: Array[Vector2i] = []
	for y in range(2, SIZE.y - 2):
		for x in range(2, SIZE.x - 2):
			var inside := true
			for dy in range(-1, 2):
				for dx in range(-1, 2):
					var c := mask.get_pixel(x + dx, y + dy)
					inside = inside and minf(c.r, minf(c.g, c.b)) > 0.95
			if inside: pixels.append(Vector2i(x, y))
	return pixels

func _delta(a: Image, b: Image, pixels: Array[Vector2i]) -> Dictionary:
	var peak := 0.0
	var rise := 0.0
	var drop := 0.0
	var before := 0.0
	for p: Vector2i in pixels:
		var ca := a.get_pixelv(p)
		var cb := b.get_pixelv(p)
		peak = maxf(peak, maxf(absf(ca.r - cb.r), maxf(absf(ca.g - cb.g), absf(ca.b - cb.b))))
		rise = maxf(rise, maxf(cb.r - ca.r, maxf(cb.g - ca.g, cb.b - ca.b)))
		before += ca.get_luminance()
		drop += ca.get_luminance() - cb.get_luminance()
	return {"max_rgb_delta": peak, "max_rgb_rise": rise, "mean_drop": drop / pixels.size(), "before_mean": before / pixels.size()}

func _run(scene: Node3D) -> bool:
	if not _ok(scene != null and scene.is_inside_tree(), "Pass the existing live scene; never instantiate main"): return false
	if not _ok(DisplayServer.get_name() != "headless", "Actual GPU window/Web required, not dummy readback"): return false
	if not _ok(not ProjectSettings.get_setting("rendering/shading/overrides/force_vertex_shading", false), "Pixel lighting required"): return false
	for light: Light3D in scene.find_children("*", "Light3D", true, false):
		for property: Dictionary in light.get_property_list():
			if property.name in ["light_size", "light_angular_distance"]:
				if not _ok(float(light.get(property.name)) == 0.0, "Native parity requires zero light size: " + str(light.name)): return false
	# Resource stability only; old file-hash audits remain independent and unchanged.
	var protected := {}
	for path: String in ["res://shaders/meadow_water.gdshader", "res://shaders/meadow_sky.gdshader", "res://shaders/meadow_focus.gdshader", "res://shaders/meadow_mountain_woodland.gdshader"]:
		var source := _text(path)
		if not _ok(not source.is_empty(), "Protected resource exists " + path): return false
		protected[path] = source.sha256_text()
	var weather := scene.get_node_or_null("LivingWeather")
	if not _ok(weather != null, "Existing weather required"): return false
	var weather_script: Script = weather.get_script()
	_rig(scene)
	var fixture := _mesh()
	for label: String in MATERIALS:
		var original := scene.get_node_or_null(NodePath(MATERIALS[label])) as MeshInstance3D
		if not _ok(original != null and original.material_override is ShaderMaterial, "Actual material " + label): return false
		var actual := original.material_override as ShaderMaterial
		var path: String = actual.shader.resource_path if actual.shader != null else ""
		var expected := "meadow_leaves.gdshader" if label == "middle_leaves" else "meadow_" + label + ".gdshader"
		if not _ok(path.get_file() == expected, "Expected targeted wrapper " + label): return false
		var native := actual.duplicate() as ShaderMaterial
		var current := actual.duplicate() as ShaderMaterial
		var mask := actual.duplicate() as ShaderMaterial
		native.shader = _shader(path, true)
		current.shader = _shader(path, false)
		mask.shader = _shader(path, true, true)
		if not _ok(native.shader != null and current.shader != null and mask.shader != null, "All shader variants built"): return false
		var uniforms: Array[String] = []
		for property: Dictionary in current.shader.get_shader_uniform_list(): uniforms.append(property.name)
		if not _ok("sunbreak_strength" in uniforms, "Actual sunbreak uniform required"): return false
		card.mesh = original.mesh if label == "cutout" else fixture
		card.global_transform = original.global_transform if label == "cutout" else Transform3D.IDENTITY
		var source_camera := scene.get_node_or_null("Camera3D") as Camera3D
		if not _ok(source_camera != null, "Actual camera orientation"): return false
		camera.global_basis = source_camera.global_basis
		var bounds := card.mesh.get_aabb()
		var center := card.global_transform * bounds.get_center()
		var extent := 0.0
		for corner in range(8):
			var p := camera.global_basis.inverse() * (card.global_transform * bounds.get_endpoint(corner) - center)
			extent = maxf(extent, maxf(absf(p.y), absf(p.x) * SIZE.y / SIZE.x))
		camera.size = extent * 2.2 + 0.2
		camera.position = center + camera.global_basis.z * (bounds.size.length() + 15.0)
		var mask_image: Image = await _capture(mask, "zero", 0.0, 0.0, false)
		if mask_image == null: return false
		var pixels := _pixels(mask_image)
		if not _ok(pixels.size() >= MIN_PIXELS, "Registered opaque interior coverage " + label): return false
		for kind: String in ["sun", "night", "ambient", "zero", "bounce", "omni"]:
			var night := 1.0 if kind == "night" else 0.0
			var before: Image = await _capture(native, kind, night, 0.0, true)
			var off: Image = await _capture(current, kind, night, 0.0, false)
			var on: Image = await _capture(current, kind, night, 0.72, false)
			if before == null or off == null or on == null: return false
			var parity := _delta(before, off, pixels)
			var change := _delta(off, on, pixels)
			var valid: bool = parity.max_rgb_delta <= EPS
			if kind == "sun":
				valid = valid and parity.before_mean > 0.02 and change.max_rgb_rise <= EPS and change.max_rgb_delta > EPS and change.mean_drop >= 1.0 / 255.0
			else:
				valid = valid and change.max_rgb_delta <= EPS
				if kind in ["ambient", "omni", "bounce"]: valid = valid and parity.before_mean > 1.0 / 255.0
			records.append({"material": label, "case": kind, "night": night, "clock": 0, "strengths": [0.0, 0.72], "pixels": pixels.size(), "native_off": parity, "off_on": change, "pass": valid})
			_ok(valid, label + "/" + kind)
		# Raw legacy ambient is intentionally reported separately: removing pigment cloud is
		# NOT equivalent to preserving all historic day ambient pixels. Never hide this delta.
		var legacy: Image = await _capture(native, "ambient", 0.0, 0.0, false)
		var revised: Image = await _capture(current, "ambient", 0.0, 0.72, false)
		if legacy == null or revised == null: return false
		records.append({"material": label, "case": "legacy_day_ambient", "diagnostic_only": true, "delta": _delta(legacy, revised, pixels)})
		# Zero direct/ambient can still contain the cutout's unchanged painted EMISSION.
		var emission_before: Image = await _capture(native, "zero", 1.0, 0.0, false)
		var emission_after: Image = await _capture(current, "zero", 1.0, 0.72, false)
		if emission_before == null or emission_after == null: return false
		var emission := _delta(emission_before, emission_after, pixels)
		var emission_ok: bool = emission.max_rgb_delta <= EPS
		records.append({"material": label, "case": "night_zero", "delta": emission, "pass": emission_ok})
		_ok(emission_ok, label + "/night_zero")
	for path: String in protected:
		if not _ok(_text(path).sha256_text() == protected[path], "Protected resource stable " + path): return false
	if not _ok(is_instance_valid(weather) and weather.get_script() == weather_script, "Existing weather script retained"): return false
	for path: String in source_hashes:
		if not _ok(_text(path).sha256_text() == source_hashes[path], "Shader stable during readback " + path): return false
	return not failed

# Exact raw snapshots from artifacts/v98/lighting-before; embedded for exported Web access.
const BASELINE := {
	"meadow_cutout_surface.gdshaderinc": "global uniform float meadow_clock;\nglobal uniform float meadow_night;\nuniform sampler2D asset_texture : source_color, repeat_disable, filter_linear_mipmap_anisotropic;\nuniform vec4 tint : source_color = vec4(1.0);\nuniform float alpha_threshold = 0.16;\nuniform float bottom_fade = 0.0;\nuniform bool face_camera = true;\nuniform float edge_inset = 0.0;\nuniform bool remove_pale_matte = false;\nuniform vec4 uv_region = vec4(0.0, 0.0, 1.0, 1.0);\nuniform float painted_fill = 0.15;\nuniform float relief_strength = 0.75;\nuniform float leaf_transmission = 0.0;\nuniform float art_contrast = 1.0;\nuniform float art_exposure = 1.0;\n// Only plant art opts into a black-preserving reflectance toe. This is not\n// emissive fill: without incident light these colours still render black.\nuniform bool foliage_tone = false;\nuniform float wind_strength = 0.0;\nuniform bool rooted_herb = false;\nuniform bool lantern_flame = false;\nuniform float mip_bias = 0.0;\nuniform bool sprite_flip = false;\nuniform float sprite_bank = 0.0;\nuniform float sprite_profile = 1.0;\nuniform float creature_visibility = 1.0;\nuniform float creature_glow = 0.0;\nuniform int window_count = 0;\n// Source-image UV centres and half extents, measured on real painted openings.\nuniform vec4 lit_windows[32];\nuniform float window_energy = 2.0;\nuniform float root_contact = 0.0;\nuniform vec4 soil_bounds = vec4(0.0, 0.0, 1.0, 1.0);\nuniform float soil_heights[25];\nvarying vec3 art_world_position;\n#ifdef MEADOW_MOUNTAIN\n#include \"res://shaders/meadow_mountain.gdshaderinc\"\n#endif\n#ifdef MEADOW_MOUNTAIN_DAY_FOG\n#include \"res://shaders/meadow_mountain_fog.gdshaderinc\"\n#endif\n#include \"res://shaders/meadow_canopy.gdshaderinc\"\n#ifdef MEADOW_ARCHITECTURE\n#include \"res://shaders/meadow_architecture.gdshaderinc\"\n#endif\n#ifdef MEADOW_ARCHITECTURE_DAY_FOG\n#include \"res://shaders/meadow_architecture_fog.gdshaderinc\"\n#endif\n\nfloat window_box_coverage(vec2 at_uv, vec2 half_pixel, vec4 opening) {\n    // Analytic pixel/window overlap keeps distant subpixel panes from popping\n    // off between fragment centres, without inflating the painted opening.\n    vec2 overlap = max(vec2(0.0), min(at_uv + half_pixel, opening.xy + opening.zw)\n        - max(at_uv - half_pixel, opening.xy - opening.zw));\n    return clamp(overlap.x * overlap.y / max(4.0 * half_pixel.x * half_pixel.y, 0.000000000001), 0.0, 1.0);\n}\n\nvec3 graded_art(vec3 raw) {\n    vec3 pigment = max(raw * tint.rgb, vec3(0.0));\n    vec3 shoulder = (pigment - vec3(0.18)) * art_contrast + vec3(0.18);\n    if (foliage_tone) {\n        // GLES3 supplies sRGB-encoded source channels here; the engine converts\n        // to linear after the custom fragment. The old affine contrast clips\n        // below ~0.019 (1.12) or ~0.037 (1.26), before shadows contribute.\n        // This rational toe is positive for every positive source channel,\n        // matches value AND derivative at 0.18, and leaves the shoulder exact.\n        vec3 low = pigment / max(vec3(art_contrast) + (1.0 - art_contrast)\n            * clamp(pigment / 0.18, vec3(0.0), vec3(1.0)), vec3(0.001));\n        return mix(low, shoulder, step(vec3(0.18), pigment)) * art_exposure;\n    }\n    return max(shoulder, vec3(0.0)) * art_exposure;\n}\n\nvoid vertex() {\n    VERTEX.x *= sprite_profile;\n    // Animated creatures bank about their registered body centre, not the PNG.\n    VERTEX.xy = mat2(vec2(cos(sprite_bank), sin(sprite_bank)), vec2(-sin(sprite_bank), cos(sprite_bank))) * VERTEX.xy;\n    // The root band never moves. Subdivided crowns bend softly, not rigid cards.\n    float tip = 1.0 - UV.y;\n    float weight = smoothstep(0.12, 0.46, tip) * tip * tip;\n    // New herb surfaces have per-column source feet, not one horizontal UV base.\n    // Their explicit vertex weight pins those measured roots during every gust.\n    if (rooted_herb) { weight *= COLOR.a; }\n    float phase = MODEL_MATRIX[3].x * 0.17 + MODEL_MATRIX[3].z * 0.11;\n    float gust = sin(meadow_clock * 1.35 + phase) * 0.70\n        + sin(meadow_clock * 2.17 + phase * 1.7 + VERTEX.x * 0.8) * 0.30;\n    VERTEX.x += gust * wind_strength * weight;\n    VERTEX.y += sin(meadow_clock * 1.71 + phase + UV.x * 4.0) * wind_strength * weight * 0.18;\n    if (face_camera) {\n        // Billboarding belongs to the material. A custom fragment shader alone\n        // must not replace the built-in billboard transform.\n        // Keep the artwork oriented to the MAIN camera even in the sun's shadow\n        // pass. Facing the light here would produce unrelated moving shadows.\n        MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0], MAIN_CAM_INV_VIEW_MATRIX[1], MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);\n        MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);\n    }\n    art_world_position = (INV_VIEW_MATRIX * MODELVIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;\n}\nvoid fragment() {\n    vec2 sprite_uv = vec2(sprite_flip ? 1.0 - UV.x : UV.x, UV.y);\n#ifdef MEADOW_MOUNTAIN_DAY_FOG\n    FOG = mountain_fog(VERTEX, sprite_uv, meadow_night);\n#endif\n#ifdef MEADOW_ARCHITECTURE_DAY_FOG\n    FOG = architecture_fog(VERTEX, sprite_uv, meadow_night);\n#endif\n    vec2 uv = uv_region.xy + sprite_uv * uv_region.zw;\n    vec4 source = texture(asset_texture, uv, mip_bias);\n    vec4 color = vec4(graded_art(source.rgb), source.a * tint.a);\n    // Far landmark art already contains broad painted light. Restore its deep\n    // forest tones before shared tone mapping/fog rather than removing atmosphere.\n    float opacity = color.a * creature_visibility;\n    if (edge_inset > 0.0) {\n        vec2 texel = vec2(edge_inset) / vec2(textureSize(asset_texture, 0));\n        float inner_alpha = min(min(texture(asset_texture, uv + vec2(texel.x, 0), mip_bias).a,\n            texture(asset_texture, uv - vec2(texel.x, 0), mip_bias).a),\n            min(texture(asset_texture, uv + vec2(0, texel.y), mip_bias).a,\n            texture(asset_texture, uv - vec2(0, texel.y), mip_bias).a));\n        opacity = min(opacity, inner_alpha);\n    }\n    if (remove_pale_matte) {\n        float darkest = min(color.r, min(color.g, color.b));\n        float saturation = max(color.r, max(color.g, color.b)) - darkest;\n        float matte = smoothstep(0.38, 0.75, darkest) * (1.0 - smoothstep(0.06, 0.23, saturation));\n        opacity *= 1.0 - matte;\n    }\n    if (bottom_fade > 0.0) {\n        opacity *= smoothstep(0.0, bottom_fade, 1.0 - UV.y);\n    }\n    vec2 pixel = 1.0 / vec2(textureSize(asset_texture, 0));\n    vec3 metric = vec3(0.30, 0.58, 0.12);\n    float l = dot(color.rgb, metric);\n    vec4 neighbor_x = texture(asset_texture, uv + vec2(pixel.x * 2.0, 0), mip_bias);\n    vec4 neighbor_y = texture(asset_texture, uv + vec2(0, pixel.y * 2.0), mip_bias);\n    // Different grading on the centre and neighbours introduced a false\n    // constant slope whenever exposure/contrast changed. Alpha gutters must\n    // not introduce a dark bevel around otherwise intact foliage either.\n    float dx = (dot(graded_art(neighbor_x.rgb), metric) - l) * step(alpha_threshold, neighbor_x.a);\n    float dy = (dot(graded_art(neighbor_y.rgb), metric) - l) * step(alpha_threshold, neighbor_y.a);\n    vec3 rounded = normalize(vec3((UV.x - 0.5) * 0.95 - dx * 1.5,\n        (0.60 - UV.y) * 0.8 + dy * 1.5, 1.0));\n    NORMAL = normalize(mix(NORMAL, rounded, relief_strength));\n    if (canopy_count > 0) {\n        float leaf_orientation_mask = 0.0;\n        vec3 leaf_up = vec3(0.0, 1.0, 0.0);\n        if (canopy_leaf_orientation) {\n            leaf_orientation_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);\n            // NORMAL is in view space; use gravity's up, independent of light/time.\n            leaf_up = normalize(mat3(VIEW_MATRIX) * vec3(0.0, 1.0, 0.0));\n        }\n        NORMAL = meadow_canopy_normal(NORMAL, sprite_uv, vec2(-dx, dy),\n            leaf_orientation_mask, leaf_up);\n    }\n#ifdef MEADOW_ARCHITECTURE\n    vec4 architecture = architecture_surface(uv);\n    NORMAL = normalize(mix(NORMAL, mat3(VIEW_MATRIX) * architecture.xyz, architecture.w));\n    // A bounded correction of broad painted sunlight, retaining brick/window\n    // detail and occlusion. New directional lighting supplies the plane contrast.\n    vec3 painted_key = normalize(vec3(0.66, 0.71, 0.25));\n    float painted_irradiance = 0.64 + 0.36 * max(dot(architecture.xyz, painted_key), 0.0);\n    color.rgb *= mix(1.0, clamp(0.80 / painted_irradiance, 0.84, 1.25), architecture.w * 0.55);\n#endif\n    float leaf_pigment_gain = 1.0;\n    if (canopy_pigment_recovery && canopy_count > 0) {\n        float leaf_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);\n        // The source includes painted lighting, not unlit albedo. Partially\n        // recover only its dark leaf pigment before real light acts on it.\n        // Bounded RGB scaling retains hue/texture and exact black; high source\n        // colours and wood are unchanged. This adds no incident light.\n        float source_luma = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));\n        float painted_shadow = 1.0 - smoothstep(0.18, 0.42, source_luma);\n        leaf_pigment_gain += 0.25 * leaf_mask * painted_shadow;\n    }\n    if (root_contact > 0.0) {\n        vec2 grid = clamp((art_world_position.xz - soil_bounds.xy) / soil_bounds.zw * 4.0, vec2(0.0), vec2(3.999));\n        ivec2 cell = ivec2(floor(grid));\n        vec2 f = fract(grid);\n        int k = cell.y * 5 + cell.x;\n        float soil_y = mix(mix(soil_heights[k], soil_heights[k + 1], f.x),\n            mix(soil_heights[k + 5], soil_heights[k + 6], f.x), f.y);\n        float root = 1.0 - smoothstep(0.04, 0.80, art_world_position.y - soil_y);\n        color.rgb *= mix(vec3(1.0), vec3(0.69, 0.78, 0.63), root * root_contact);\n    }\n    ALBEDO = color.rgb * leaf_pigment_gain * (1.0 - painted_fill) * mix(vec3(1.0), vec3(0.78, 0.90, 1.0), meadow_night);\n    // Painted distant light must become moonlight too, not stay daylight-white.\n    EMISSION = color.rgb * painted_fill * mix(vec3(1.0), vec3(0.36, 0.43, 0.54), meadow_night);\n#ifdef MEADOW_MOUNTAIN\n    meadow_mountain_surface(uv, clamp(1.0 - meadow_night, 0.0, 1.0), mat3(VIEW_MATRIX), NORMAL, ALBEDO, EMISSION);\n#endif\n#ifdef MEADOW_ARCHITECTURE\n    // Remove the uniformly glowing painted fill, not the stone's reflectance.\n    // Keep actual sun/moon response, relief and windows exactly independent.\n    // Sheltered masonry receives less baked fill than bright painted stone;\n    // retain more at night so settlement silhouettes remain readable.\n    float painted_value = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));\n    float painted_highlight = smoothstep(0.08, 0.80, painted_value);\n    float daylight_fill = mix(0.10, 0.50, painted_highlight);\n    float moonlight_fill = mix(0.65, 0.85, painted_highlight);\n    EMISSION *= mix(daylight_fill, moonlight_fill, meadow_night);\n    // Day-only material separation on existing source-aligned planes. Skip the\n    // operation entirely at the night endpoint; painted fill/windows stay exact.\n    float architecture_day = clamp(1.0 - meadow_night, 0.0, 1.0);\n    // Whole-asset pigment is independent of profile coverage/strength. Retain\n    // source hue and detail, with bounded channel scaling and exact black.\n    if (architecture_day > 0.0) {\n        float architecture_value = dot(ALBEDO, vec3(0.2126, 0.7152, 0.0722));\n        vec3 architecture_color = vec3(architecture_value)\n            + (ALBEDO - vec3(architecture_value)) * 1.25;\n        architecture_color = clamp(architecture_color, ALBEDO * 0.75, ALBEDO * 1.25) * 0.90;\n        ALBEDO = mix(ALBEDO, architecture_color, architecture_day);\n    }\n    if (architecture_day > 0.0 && architecture.w > 0.0) {\n        // Green/olive source pixels can sit inside the broad masonry profiles.\n        float green_excess = (source.g - 0.5 * (source.r + source.b)) / max(painted_value, 0.04);\n        float source_green = smoothstep(0.015, 0.09, green_excess)\n            * (1.0 - smoothstep(0.02, 0.10, source.r - source.g));\n        float roof = smoothstep(0.30, 0.70, architecture.y);\n        float facing = smoothstep(0.08, 0.55, dot(architecture.xyz, painted_key));\n        float stone = (1.0 - roof) * smoothstep(0.10, 0.50, painted_value);\n        float source_warmth = mix(0.45, 1.0, smoothstep(-0.03, 0.10, source.r - source.b));\n        // Local wall tint excludes roof planes. Walls exchange bounded\n        // chroma while preserving ALBEDO luminance in this shader's colour space.\n        float wall_weight = architecture_day * clamp(architecture.w, 0.0, 1.0)\n            * stone * (1.0 - source_green);\n        float wall_value = dot(ALBEDO, vec3(0.2126, 0.7152, 0.0722));\n        if (wall_weight > 0.0 && wall_value > 0.000001) {\n            vec3 wall_gain = mix(vec3(0.94, 1.0, 1.14), vec3(1.16, 1.0, 0.95), facing * source_warmth);\n            vec3 wall_color = ALBEDO * wall_gain;\n            wall_color *= wall_value / dot(wall_color, vec3(0.2126, 0.7152, 0.0722));\n            ALBEDO = mix(ALBEDO, wall_color, wall_weight);\n        }\n    }\n#endif\n    // No all-body neon outline. Only pale antler cores and cool bright fur\n    // markings emit; all other fur still receives the shared scene lighting.\n    float pale_core = smoothstep(0.38, 0.82, max(source.r, max(source.g, source.b)));\n    float antler_band = 1.0 - smoothstep(0.36, 0.48, UV.y);\n    float cool_spot = smoothstep(0.025, 0.13, source.b - source.r)\n        * smoothstep(0.68, 0.88, max(source.r, max(source.g, source.b)));\n    EMISSION += vec3(0.50, 0.83, 1.0) * max(pale_core * antler_band, cool_spot * 0.48) * creature_glow;\n    if (window_count > 0 && meadow_night > 0.01) {\n        float window_glow = 0.0;\n        vec2 half_pixel = max(fwidth(uv) * 0.5, pixel * 0.5);\n        for (int i = 0; i < 32; i++) {\n            if (i >= window_count) { break; }\n            vec4 opening = lit_windows[i];\n            vec2 distance_uv = abs(uv - opening.xy) / max(opening.zw, pixel * 0.5);\n            float pane = window_box_coverage(uv, half_pixel, opening);\n            float spill = exp(-dot(distance_uv, distance_uv) * 0.60) * 0.12;\n            // Mostly steady interior lamps, with different very small changes.\n            float candle = 0.96 + sin(meadow_clock * 1.1 + float(i) * 2.37) * 0.04;\n            window_glow += (pane + spill) * candle;\n        }\n        EMISSION += vec3(1.0, 0.57, 0.24) * min(window_glow, 1.35)\n            * window_energy * smoothstep(0.30, 0.90, meadow_night);\n    }\n    if (lantern_flame) {\n        float glass = smoothstep(0.54, 0.57, UV.x) * (1.0 - smoothstep(0.72, 0.75, UV.x))\n            * smoothstep(0.39, 0.41, UV.y) * (1.0 - smoothstep(0.49, 0.50, UV.y));\n        float warm = smoothstep(0.10, 0.35, source.r - source.b) * smoothstep(0.35, 0.80, source.r);\n        float flicker = 1.0 + sin(meadow_clock * 6.3) * 0.035 + sin(meadow_clock * 10.7) * 0.015;\n        EMISSION += vec3(1.0, 0.60, 0.28) * glass * warm * meadow_night * flicker * 2.4;\n    }\n    ROUGHNESS = 0.91;\n    SPECULAR = 0.04;\n    // Thin leaves transmit a little light; stone, buildings and lamp posts do\n    // not. Broad Lambert wrapping previously lit every cutout like foliage.\n    BACKLIGHT = color.rgb * leaf_transmission;\n    if (canopy_backlight && canopy_count > 0) {\n        float leaf_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);\n        if (leaf_mask > 0.0) {\n            // Avoid multiplying leaf reflectance again; retain the existing\n            // transmission amount (0.10 on these trees), with a soft mask edge.\n            // A zero mask keeps the original assignment above exactly.\n            BACKLIGHT = mix(BACKLIGHT, vec3(leaf_transmission), leaf_mask);\n        }\n    }\n    ALPHA = opacity;\n    // Alpha-scissor puts cutouts in the depth-writing opaque pass. Plain\n    // discard + ALPHA would instead create transparency sorting regressions.\n    ALPHA_SCISSOR_THRESHOLD = alpha_threshold;\n    ALPHA_ANTIALIASING_EDGE = alpha_threshold * 0.65;\n    ALPHA_TEXTURE_COORDINATE = uv * vec2(textureSize(asset_texture, 0));\n}\n",
	"meadow_cutout.gdshader": "shader_type spatial;\nrender_mode cull_disabled, diffuse_burley, alpha_to_coverage;\n#include \"res://shaders/meadow_cutout_surface.gdshaderinc\"\n",
	"meadow_ground.gdshader": "shader_type spatial;\nglobal uniform float meadow_clock;\nglobal uniform float meadow_night;\nrender_mode cull_disabled;\n\nuniform sampler2D rock_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;\nuniform sampler2D bank_limestone_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;\nuniform vec4 contact_shadows[72];\nuniform vec2 road_points[12];\nuniform vec2 road_fork[2];\nuniform vec2 bridge_spur[2];\nuniform vec2 river_bends[10];\nuniform vec4 road_width = vec4(1.35, 3.10, -65.0, 10.0);\nuniform vec2 foothill_origin = vec2(0.0, -255.0);\nvarying vec3 world_position;\nvarying vec3 world_normal;\n\n#include \"res://shaders/meadow_palette.gdshaderinc\"\n#include \"res://shaders/meadow_mountain_floor.gdshaderinc\"\n#include \"res://shaders/meadow_surface.gdshaderinc\"\n#include \"res://shaders/meadow_mineral.gdshaderinc\"\n\nfloat hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\nfloat noise(vec2 p) {\n    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);\n    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);\n}\nfloat segment_distance(vec2 p, vec2 a, vec2 b) {\n    vec2 v = b - a;\n    return length(p - a - v * clamp(dot(p - a, v) / dot(v, v), 0.0, 1.0));\n}\nvec2 river_shape(vec2 p) {\n    float centre = river_bends[9].y;\n    for (int i = 0; i < 9; i++) {\n        vec2 a = river_bends[i];\n        vec2 b = river_bends[i + 1];\n        if (p.y >= b.x) {\n            float t = clamp((a.x - p.y) / (a.x - b.x), 0.0, 1.0);\n            centre = mix(a.y, b.y, t * t * (3.0 - 2.0 * t)) + 0.65 * sin(p.y * 0.31 + 0.4);\n            break;\n        }\n    }\n    float half_width = 6.2 + 1.25 * sin(p.y * 0.054 + 0.8) + 0.50 * sin(p.y * 0.23 + 1.8);\n    float side = sign(p.x - centre);\n    float perturb = (sin(p.y * 0.29 + side * 1.7) * 0.38 + sin(p.y * 0.81 - side) * 0.16)\n        * smoothstep(5.0, 10.0, abs(p.y + 38.0));\n    float shore_strength = smoothstep(-117.0, -104.0, p.y) * (1.0 - smoothstep(-12.0, -4.0, p.y))\n        * smoothstep(7.0, 11.0, abs(p.y + 38.0));\n    float bank_z = p.y - (side > 0.0 ? 4.5 : 0.0);\n    vec3 gully_delta = vec3((bank_z + 23.5) / 1.4, (bank_z + 79.0) / 2.8, (bank_z + 105.0) / 3.3);\n    vec3 gully_field = exp(-gully_delta * gully_delta * 1.7);\n    float gully = max(gully_field.x, max(gully_field.y, gully_field.z));\n    perturb += (sin(p.y * 0.20 + side * 2.0) * 0.92 + sin(p.y * 0.49 - side * 0.7) * 0.30 + gully * 1.40) * shore_strength;\n    return vec2(centre, half_width + perturb);\n}\nvoid vertex() {\n    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;\n    world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);\n}\nvoid fragment() {\n    vec2 p = world_position.xz;\n    // UV2 was sampled from the same world field that places the living grass.\n    float thicket = smoothstep(0.30, 0.74, UV2.x);\n    vec2 warp = vec2(noise(p * 0.23), noise(p * 0.23 + 20.0)) * 1.1;\n    vec3 fine_grass = meadow_surface(p);\n    vec3 ground = fine_grass;\n    // The source already contains deep leaf crevices. A second strong dark\n    // multiplier and unrelated high-frequency normals turned turf into gravel.\n    ground = meadow_pigment(pow(max(ground, vec3(0.0)), vec3(0.98)), p, UV2.x);\n    // Distant foothills share the cool, wooded palette of the mountain base;\n    // they must not become a fluorescent smooth band behind the village.\n    float foothill = 1.0 - smoothstep(-195.0, -107.0, p.y);\n    float distant_scrub = smoothstep(0.31, 0.66, noise(p * 0.36 + noise(p * 0.09) * 3.0));\n    ground *= mix(vec3(1.0), mix(vec3(0.53, 0.64, 0.70), vec3(0.79, 0.84, 0.79), distant_scrub), foothill * 0.84);\n    // A broken woodland floor continues under the real foothill scrub volumes.\n    // Its irregular leading edge follows the same field as the new geometry.\n    float wooded_foot = meadow_foothill_cover(p, foothill_origin);\n    ground *= mix(vec3(1.0), vec3(0.61, 0.73, 0.67), wooded_foot * 0.75);\n    ground = mountain_forest_floor(ground, p);\n\n    float road = segment_distance(p, road_fork[0], road_fork[1]);\n    road = min(road, segment_distance(p, bridge_spur[0], bridge_spur[1]));\n    for (int i = 0; i < 11; i++) {\n        road = min(road, segment_distance(p, road_points[i], road_points[i + 1]));\n    }\n    float width = mix(road_width.x, road_width.y, smoothstep(road_width.z, road_width.w, p.y));\n    width *= 0.88 + noise(p * 0.19 + vec2(13.1, 2.7)) * 0.24;\n    float edge = noise(p * 2.7) * 0.30 + noise(p * 0.85) * 0.52;\n    float road_mask = 1.0 - smoothstep(width - 0.45, width + 0.82, road + edge);\n    vec3 grit = texture(rock_texture, p / 6.2).rgb;\n    float grit_value = dot(grit, vec3(0.299, 0.587, 0.114));\n    vec3 dirt = grit * vec3(0.98, 0.96, 0.80);\n    dirt *= 0.88 + noise(p * 2.7) * 0.24;\n    dirt *= mix(0.77, 1.08, noise(p * 0.55 + warp * 0.3));\n    // The pale daytime dust should not become a self-luminous grey ribbon at\n    // night. Retain texture, lower its reflectance and shift it toward moonlight.\n    dirt *= mix(vec3(1.0), vec3(0.64, 0.73, 0.88), meadow_night);\n    // Meadow fingers interrupt the worn edges; the middle remains legible for\n    // walking. This is material weathering, not new obstacles in the route.\n    float encroaching_grass = thicket * smoothstep(0.22, 0.90, road / width) * 0.62;\n    ground = mix(ground, dirt, road_mask * (0.96 - encroaching_grass));\n\n    vec2 channel = river_shape(p);\n    float shore_distance = abs(p.x - channel.x) - channel.y;\n    float upper_shoulder = (1.0 - smoothstep(-78.0, -52.0, p.y)) * (3.3 + sin(p.y * 0.17 + 0.4) * 0.55);\n    float bank_zone = (1.0 - smoothstep(1.25 + upper_shoulder * 0.45, 3.4 + upper_shoulder, abs(shore_distance)))\n        * smoothstep(-190.0, -162.0, p.y);\n    vec3 n = normalize(world_normal);\n    // Height-function normals are flat at both ends of each smoothstep shelf.\n    // Interpolating those endpoint normals erased the actually steep rock face.\n    // Restore the real triangle orientation ONLY on the sculpted river shore.\n    vec3 geometric_normal = normalize(cross(dFdx(world_position), dFdy(world_position)));\n    geometric_normal *= sign(dot(geometric_normal, n));\n    float sculpted_shore = smoothstep(-117.0, -104.0, p.y) * (1.0 - smoothstep(-12.0, -4.0, p.y))\n        * smoothstep(7.0, 11.0, abs(p.y + 38.0));\n    n = normalize(mix(n, geometric_normal, bank_zone * sculpted_shore * 0.94));\n    vec3 mineral_weights = pow(abs(n), vec3(4.0));\n    mineral_weights /= max(dot(mineral_weights, vec3(1.0)), 0.001);\n    vec3 rock = meadow_mineral_pigment(meadow_mineral_sample(world_position, mineral_weights), world_position);\n    float cliff = 1.0 - smoothstep(0.64, 0.88, n.y);\n    float moss = smoothstep(0.50, 0.80, noise(p * 1.3 + world_position.y * 0.27)) * smoothstep(0.58, 0.82, n.y);\n    rock = mix(rock, ground, moss * 0.55);\n    ground = mix(ground, rock, cliff);\n    float erosion = smoothstep(0.28, 0.72, noise(p * 2.4 + world_position.y));\n    // The backing bank and embedded beds share limestone pigment. Road grit\n    // belongs only in broken soil pockets, not over the entire vertical face.\n    vec3 bank_weights = pow(abs(n), vec3(3.0));\n    bank_weights /= max(dot(bank_weights, vec3(1.0)), 0.001);\n    vec3 bank_grain = texture(rock_texture, world_position.zy / 4.6).rgb * bank_weights.x\n        + texture(rock_texture, world_position.xz / 4.6).rgb * bank_weights.y\n        + texture(rock_texture, world_position.xy / 4.6).rgb * bank_weights.z;\n    // Metre-scaled fractured limestone belongs to the real bank mesh. Its\n    // pigment contains no scene lighting; relief and daylight remain dynamic.\n    vec3 bank_pigment = rock;\n    if (bank_zone * cliff > 0.001) {\n        vec3 bed_sample = texture(bank_limestone_texture, world_position.zy / vec2(7.2, -6.0)).rgb * bank_weights.x\n            + texture(bank_limestone_texture, world_position.xz / 7.2).rgb * bank_weights.y\n            + texture(bank_limestone_texture, world_position.xy / vec2(7.2, -6.0)).rgb * bank_weights.z;\n        bank_pigment = mix(rock, bed_sample * vec3(0.64, 0.65, 0.59), 0.92);\n    }\n    vec3 bank_soil = mix(bank_pigment, bank_grain * vec3(0.60, 0.60, 0.51), erosion * 0.14);\n    float grass_roots = smoothstep(0.50, 0.88, n.y) * smoothstep(0.36, 0.75, noise(p * 3.7));\n    bank_soil = mix(bank_soil, ground, grass_roots * 0.74);\n    ground = mix(ground, bank_soil, bank_zone * cliff * 0.88);\n    float wet = 1.0 - smoothstep(-1.2, -0.1, world_position.y);\n    vec3 wet_ground = mix(ground, rock * vec3(0.38, 0.47, 0.46), wet * 0.65);\n    vec3 wet_bank = mix(ground, ground * vec3(0.52, 0.64, 0.71), wet * 0.75);\n    ground = mix(wet_ground, wet_bank, bank_zone);\n    // Actual opaque channel floor, now visible through the transparent river.\n    float bed_mask = (1.0 - smoothstep(-0.25, 0.6, shore_distance)) * smoothstep(-195.0, -170.0, p.y);\n    float submerged = (1.0 - smoothstep(-1.65, -1.12, world_position.y)) * bed_mask;\n    float grains = noise(p * 5.0) * 0.65 + noise(p * 13.0) * 0.35;\n    vec3 sediment = mix(vec3(0.16, 0.15, 0.11), vec3(0.32, 0.29, 0.21), grains);\n    sediment *= 0.80 + noise(p * 0.55) * 0.28;\n    float light_net = pow(1.0 - abs(sin(p.x * 2.9 + noise(p * 0.7 + meadow_clock * 0.015) * 5.0)), 12.0);\n    sediment += vec3(0.11, 0.13, 0.095) * light_net * (1.0 - meadow_night * 0.80);\n    ground = mix(ground, sediment, submerged);\n\n    float shadow = 1.0;\n    for (int i = 0; i < 72; i++) {\n        vec4 s = contact_shadows[i];\n        if (s.z > 0.0) {\n            float d = length((p - s.xy) / vec2(s.z, s.w));\n            shadow *= mix(0.72, 1.0, smoothstep(0.0, 1.0, d));\n        }\n    }\n    // Low frequency moving cloud shade gives one shared lighting field.\n    ALBEDO = ground * shadow * meadow_cloud_light(p, meadow_clock, meadow_night) * 0.98;\n    // The generated grass supplies both leaf color and fine relief. World-space\n    // normal perturbation needs no fake grass cards and remains outside geometry.\n    vec2 detail_uv = meadow_surface_uv(p);\n    float center_height = dot(texture(meadow_texture, detail_uv).rgb, vec3(0.30, 0.58, 0.12));\n    float hx = dot(texture(meadow_texture, detail_uv + vec2(0.003, 0)).rgb, vec3(0.30, 0.58, 0.12));\n    float hz = dot(texture(meadow_texture, detail_uv + vec2(0, 0.003)).rgb, vec3(0.30, 0.58, 0.12));\n    float trail_x = dot(texture(rock_texture, p / 6.2 + vec2(0.006, 0)).rgb, vec3(0.299, 0.587, 0.114));\n    float trail_z = dot(texture(rock_texture, p / 6.2 + vec2(0, 0.006)).rgb, vec3(0.299, 0.587, 0.114));\n    float pixel_footprint = max(length(dFdx(p)), length(dFdy(p)));\n    float resolved_relief = 1.0 - smoothstep(0.06, 0.28, pixel_footprint);\n    vec2 relief = mix(vec2(center_height - hx, center_height - hz) * thicket * thicket * 0.24,\n        vec2(grit_value - trail_x, grit_value - trail_z) * 1.65, road_mask) * resolved_relief;\n    vec3 detailed_normal = normalize(n + vec3(relief.x, 0, relief.y) * (1.0 - cliff));\n    // Bounded surface-gradient micro-relief. It cannot alter silhouette or\n    // substitute for the three physically sculpted rock shelves above.\n    float bank_height = dot(bank_pigment, vec3(0.30, 0.58, 0.12));\n    vec3 sigma_x = dFdx(world_position);\n    vec3 sigma_y = dFdy(world_position);\n    vec3 rx = cross(sigma_y, n);\n    vec3 ry = cross(n, sigma_x);\n    float determinant = dot(sigma_x, rx);\n    vec3 bank_gradient = (rx * dFdx(bank_height) + ry * dFdy(bank_height))\n        * sign(determinant) / max(abs(determinant), 0.00001);\n    bank_gradient *= min(0.10, 0.24 / max(length(bank_gradient), 0.001));\n    detailed_normal = normalize(detailed_normal - bank_gradient * bank_zone * cliff * resolved_relief);\n    NORMAL = normalize((VIEW_MATRIX * vec4(detailed_normal, 0)).xyz);\n    // Dry dirt scatters broadly; grass and damp soil have a modest real\n    // specular response. Do not paint white highlights into every surface.\n    ROUGHNESS = mix(mix(mix(0.86, 0.97, road_mask), 0.63, wet), mix(0.94, 0.67, wet), bank_zone * cliff);\n    SPECULAR = mix(mix(mix(0.16, 0.07, road_mask), 0.24, wet), 0.10, bank_zone * cliff);\n}\n",
	"meadow_leaves.gdshader": "shader_type spatial;\nrender_mode cull_disabled, diffuse_burley;\nglobal uniform float meadow_clock;\nglobal uniform float meadow_night;\nuniform bool foothill_scrub = false;\nuniform bool middle_scrub = false;\nvarying vec3 world_position;\nvarying vec3 leaf_world_normal;\n#include \"res://shaders/meadow_palette.gdshaderinc\"\n#include \"res://shaders/meadow_surface.gdshaderinc\"\nvoid vertex() {\n    float phase = VERTEX.x * 0.31 + VERTEX.z * 0.21;\n    float breeze = (sin(phase + meadow_clock * 1.4) * 0.70\n        + sin(phase * 2.7 - meadow_clock * 2.1) * 0.30) * 0.055;\n    VERTEX.x += breeze * COLOR.a * COLOR.a;\n    VERTEX.z += breeze * COLOR.a * 0.4;\n    world_position = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz;\n    leaf_world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);\n}\nvoid fragment() {\n    // Grass fans are intentionally two-sided. The renderer's back-face normal\n    // flip otherwise lights half the fans from below, producing black speckles.\n    // Use the authored continuous upper-surface normal on either winding.\n    vec3 upper_normal = normalize(leaf_world_normal);\n    upper_normal.y = abs(upper_normal.y);\n    NORMAL = normalize((VIEW_MATRIX * vec4(upper_normal, 0.0)).xyz);\n    vec2 p = world_position.xz;\n    vec3 meadow = meadow_surface(p);\n    vec3 pigment = meadow_pigment(meadow, p, UV2.x) * COLOR.rgb;\n    // Modest top-leaf light separates the foliage silhouette from the soil;\n    // a whole random bright triangle is no longer the unit of contrast.\n    pigment *= mix(1.02, 1.19, COLOR.a);\n    if (foothill_scrub) {\n        // Resolve a leafy wooded mass, not bright single grass blades, this far away.\n        pigment = mix(pigment, vec3(0.052, 0.082, 0.041) * COLOR.rgb, 0.48);\n        pigment *= vec3(0.72, 0.85, 0.78);\n    }\n    if (UV.x < -900.0) { pigment = vec3(0.59, 0.58, 0.37); }\n    // The new woody/herb tier has denser olive foliage than the meadow under\n    // it; this is material reflectance, not a dark overlay on the terrain.\n    if (middle_scrub) {\n        // Broad mid-height leaves connect the turf and painted shrub islands.\n        // The turf/density and vertex tone already supply the broad dark mass.\n        // Avoid multiplying another deeply green filter into sheltered leaves;\n        // retain an olive body that can receive the same light as nearby turf.\n        // Root occlusion, real branch shadows and leaf gaps remain independent.\n        float outer_leaf = smoothstep(0.10, 0.90, COLOR.a);\n        pigment *= mix(vec3(0.86, 0.94, 0.78), vec3(0.93, 0.97, 0.85), outer_leaf);\n    }\n    if (UV.x < -1800.0) { pigment = vec3(0.105, 0.073, 0.034) * COLOR.rgb; }\n    ALBEDO = pigment * meadow_cloud_light(p, meadow_clock, meadow_night);\n    BACKLIGHT = pigment * 0.06;\n    // Thin middle-crown leaflets receive restrained back-side illumination.\n    // Wood and other vegetation keep their established response. This adds\n    // no emission; the no-incident-light case is checked in the GPU probe.\n    if (middle_scrub && UV.x >= -900.0) {\n        BACKLIGHT = vec3(0.18);\n    }\n    ROUGHNESS = mix(0.95, 0.80, COLOR.a);\n    SPECULAR = 0.14;\n    AO = 0.78 + COLOR.a * 0.22;\n}\n",
	"meadow_limestone.gdshader": "shader_type spatial;\nrender_mode cull_disabled, diffuse_burley;\nglobal uniform float meadow_clock;\nglobal uniform float meadow_night;\nuniform sampler2D escarpment_texture : source_color, repeat_disable, filter_linear_mipmap_anisotropic;\nvarying vec3 world_position;\nvarying vec3 world_normal;\n#include \"res://shaders/meadow_palette.gdshaderinc\"\n#include \"res://shaders/meadow_surface.gdshaderinc\"\n#include \"res://shaders/meadow_mineral.gdshaderinc\"\nfloat hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\nfloat noise(vec2 p) {\n    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);\n    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);\n}\nvoid vertex() {\n    world_position = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz;\n    world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);\n}\nvoid fragment() {\n    vec3 p = world_position;\n    vec3 n = normalize(world_normal);\n    vec3 weight = pow(abs(n), vec3(4.0));\n    weight /= max(dot(weight, vec3(1.0)), 0.001);\n    vec3 mineral = meadow_mineral_pigment(meadow_mineral_sample(p, weight), p);\n    // Broad planes are provided by solid geometry; this map is just mineral grain.\n    vec4 painted_face = texture(escarpment_texture, clamp(UV, vec2(0.0), vec2(1.0)));\n    // Disregard low-alpha matte RGB while retaining the untouched source PNG.\n    float face_mask = step(0.0, UV.x) * smoothstep(0.22, 0.42, painted_face.a);\n    // Let scene light describe the actual planes. The old 64% pre-lit strip\n    // washed out the new geometry and repeated its painted bright shoulders.\n    // Keep a restrained amount of unique fissure colour; no fake black outline.\n    mineral = mix(mineral, painted_face.rgb * vec3(0.76, 0.75, 0.68), face_mask * 0.38);\n    mineral *= mix(1.0, COLOR.g, 0.48);\n    float cap = smoothstep(0.68, 0.92, n.y) * COLOR.r;\n    // Soil continues at the rear; its exposed stone edge has broken pockets\n    // of turf, not one fully green horizontal strip around the whole outcrop.\n    float edge_tufts = smoothstep(0.30, 0.70, noise(p.xz * 1.65 + p.y * 0.19));\n    edge_tufts *= mix(0.48, 1.0, smoothstep(0.28, 0.73, UV2.x));\n    cap *= mix(edge_tufts, 1.0, smoothstep(0.06, 0.72, UV2.y));\n    vec3 turf = meadow_pigment(meadow_surface(p.xz), p.xz, UV2.x);\n    // The near boulders are pale worn limestone, not the ochre cliff band.\n    // Vertex alpha tags that geology; it is metadata, not surface opacity.\n    float pale_stone = 1.0 - smoothstep(0.45, 0.90, COLOR.a);\n    float stone_value = dot(mineral, vec3(0.30, 0.58, 0.12));\n    vec3 pale = mix(mineral, vec3(stone_value) * vec3(1.04, 1.02, 0.96), 0.52) * 1.03;\n    mineral = mix(mineral, pale, pale_stone);\n    vec3 rock = mix(mineral, turf, cap * 0.94);\n    float wet = 1.0 - smoothstep(-1.08, -0.40, p.y);\n    ALBEDO = mix(rock, rock * vec3(0.52, 0.64, 0.71), wet * 0.75)\n        * meadow_cloud_light(p.xz, meadow_clock, meadow_night);\n    // Actual sun responds to fine mineral relief as well as the solid silhouette.\n    vec3 metric = vec3(0.30, 0.58, 0.12);\n    float h = dot(meadow_mineral_sample(p, weight), metric);\n    vec3 gradient = vec3(h - dot(meadow_mineral_sample(p + vec3(0.028, 0, 0), weight), metric),\n        h - dot(meadow_mineral_sample(p + vec3(0, 0.028, 0), weight), metric),\n        h - dot(meadow_mineral_sample(p + vec3(0, 0, 0.028), weight), metric));\n    gradient -= n * dot(gradient, n);\n    float resolved_grain = 1.0 - smoothstep(0.10, 0.40, max(length(dFdx(p)), length(dFdy(p))));\n    NORMAL = normalize((VIEW_MATRIX * vec4(normalize(n + gradient * mix(1.35, 0.85, face_mask) * (1.0 - cap) * resolved_grain), 0)).xyz);\n    ROUGHNESS = mix(0.94, 0.67, wet);\n    SPECULAR = 0.10;\n    AO = 0.93;\n}\n",
	"meadow_palette.gdshaderinc": "// World-space vegetation colour and cloud shade, shared by soil and real leaves.\n// Do not give each triangle an unrelated bright material: foliage reads in masses.\nfloat meadow_hash(vec2 p) {\n    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);\n}\nfloat meadow_noise(vec2 p) {\n    vec2 i = floor(p);\n    vec2 f = fract(p);\n    f = f * f * (3.0 - 2.0 * f);\n    return mix(mix(meadow_hash(i), meadow_hash(i + vec2(1, 0)), f.x),\n        mix(meadow_hash(i + vec2(0, 1)), meadow_hash(i + vec2(1, 1)), f.x), f.y);\n}\nvec3 meadow_pigment(vec3 source, vec2 p, float density) {\n    float mass = smoothstep(0.27, 0.76, meadow_noise(p * vec2(0.095, 0.065) + vec2(4.3, 8.1)));\n    float thicket = smoothstep(0.30, 0.74, density);\n    // Compress the source's brightest yellow leaf specks, keeping its edges,\n    // dark crevices and hue. This is reflectance, not extra camera blur.\n    float value = dot(source, vec3(0.30, 0.58, 0.12));\n    vec3 pigment = source / (1.0 + max(value - 0.30, 0.0) * 0.72);\n    pigment *= mix(vec3(0.80, 0.91, 0.80), vec3(1.04, 1.03, 0.90), mass);\n    pigment *= mix(vec3(1.05, 1.02, 0.94), vec3(0.68, 0.82, 0.63), thicket);\n    return pigment;\n}\nfloat meadow_cloud_light(vec2 p, float clock, float night) {\n    float cloud = smoothstep(0.25, 0.71,\n        meadow_noise(p * 0.036 + vec2(2.7 + clock * 0.0015, 1.3)));\n    // Weak at night: moonlit grass must not become a globally black blanket.\n    return mix(mix(0.79, 1.0, cloud), mix(0.95, 1.0, cloud), night);\n}\nfloat meadow_foothill_cover(vec2 p, vec2 origin) {\n    float spread = 1.0 - smoothstep(70.0, 104.0, abs(p.x - origin.x));\n    float front = origin.y + 57.0 + 10.0 * sin(p.x * 0.069) + 7.0 * sin(p.x * 0.173 + 1.4);\n    float depth = 1.0 - smoothstep(origin.y + 7.0, front, p.y);\n    return spread * depth;\n}\n"
}
