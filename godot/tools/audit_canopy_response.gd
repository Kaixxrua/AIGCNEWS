extends RefCounted
## Optional actual-WebGL test of the same cutout material, not a rewritten model.
## Isolate direct-light response in a private viewport. Main scene is untouched.

const WEATHER = preload("res://scripts/meadow_weather.gd")
const CODE_VALUE: float = 1.0 / 255.0
# Fixed before the BACKLIGHT readback; these are display-code differences,
# not CPU estimates of linear reflectance or proof of full-scene acceptance.
const LOWER_MIN_PIXELS: int = 200
const LOWER_MIN_MEAN_GAIN: float = 2.0 / 255.0
const LOWER_MIN_IMPROVED_FRACTION: float = 0.25
const HIGHLIGHT_MIN_PIXELS: int = 50
const HIGHLIGHT_MAX_MEAN_RGB_DELTA: float = 12.0 / 255.0
const HIGHLIGHT_MAX_P95_RGB_DELTA: float = 24.0 / 255.0
const HIGHLIGHT_MAX_EXTRA_CLIPPED_FRACTION: float = 0.01
const WOOD_MIN_PIXELS: int = 24
const WOOD_MAX_RGB_DELTA: float = 2.0 / 255.0
# Independently selected on the real oak PNG, not generated from the shader's
# leaf mask. Crown wood is INSIDE the lobe, so a lobe-only fix cannot pass it.
const LOWER_CROWN_UV: Rect2 = Rect2(0.14, 0.45, 0.72, 0.27)
const UPPER_CROWN_UV: Rect2 = Rect2(0.14, 0.08, 0.76, 0.32)
const CROWN_WOOD_UV: Rect2 = Rect2(0.39, 0.48, 0.18, 0.28)
const BARE_TRUNK_UV: Rect2 = Rect2(0.46, 0.81, 0.10, 0.11)

static func run(scene: Node3D) -> void:
	# Dedicated opt-in for procedural middle-brush readback. The normal canopy
	# query retains its complete historical gates; this is a separate workload.
	if OS.has_feature("web") and JavaScriptBridge.eval("new URLSearchParams(location.search).get('middle_brush_audit') === '1'"):
		var brush_probe = load("res://tools/audit_middle_brush_response.gd")
		await brush_probe.run(scene)
		return
	var viewport: SubViewport = SubViewport.new()
	viewport.size = Vector2i(160, 160)
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.add_child(viewport)
	var scene_camera: Camera3D = scene.get_node("Camera3D") as Camera3D
	# Rotate the complete private rig, not just its key: world-up leaf normals
	# must see the same camera pitch as the actual scene. Relative framing and
	# the historical camera-space key directions remain unchanged.
	var probe_space: Node3D = Node3D.new()
	probe_space.basis = scene_camera.global_basis
	viewport.add_child(probe_space)
	var world: WorldEnvironment = WorldEnvironment.new()
	var scene_world: WorldEnvironment = scene.get_node("WorldEnvironment") as WorldEnvironment
	var environment: Environment = scene_world.environment.duplicate() as Environment
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.sky = null
	environment.fog_enabled = false
	environment.ambient_light_energy = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.ssao_enabled = false
	world.environment = environment
	viewport.add_child(world)
	var tree: MeshInstance3D = scene.get_node("BroadTreeAtRightFrame") as MeshInstance3D
	var card: MeshInstance3D = MeshInstance3D.new()
	card.mesh = tree.mesh
	card.position = -tree.mesh.get_aabb().get_center()
	var source_material: ShaderMaterial = tree.material_override as ShaderMaterial
	var material: ShaderMaterial = source_material.duplicate() as ShaderMaterial
	# Disable only nondirectional fill in this diagnostic, not in the artwork.
	material.set_shader_parameter("painted_fill", 0.0)
	material.set_shader_parameter("leaf_transmission", 0.0)
	# Preserve the legacy upper-crown normal regression despite new profile flags.
	material.set_shader_parameter("canopy_backlight", false)
	material.set_shader_parameter("canopy_leaf_orientation", false)
	material.set_shader_parameter("canopy_pigment_recovery", false)
	material.set_shader_parameter("wind_strength", 0.0)
	material.set_shader_parameter("root_contact", 0.0)
	card.material_override = material
	probe_space.add_child(card)
	var camera: Camera3D = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = tree.mesh.get_aabb().size.y * 1.10
	camera.position.z = 12.0
	probe_space.add_child(camera)
	var key: DirectionalLight3D = DirectionalLight3D.new()
	key.shadow_enabled = false
	probe_space.add_child(key)
	var results: Array[Dictionary] = []
	var passed: bool = true
	for night: bool in [false, true]:
		_set_key_direction(scene_camera, key, night)
		var values: Array[float] = []
		for strength: float in [0.0, 0.92]:
			material.set_shader_parameter("canopy_strength", strength)
			var rendered: Image = await _capture(viewport)
			var sum: float = 0.0
			for y: int in range(20, 60):
				for x: int in range(48, 116):
					var pixel: Color = rendered.get_pixel(x, y)
					sum += pixel.r * 0.2126 + pixel.g * 0.7152 + pixel.b * 0.0722
			values.append(sum / (40.0 * 68.0))
		results.append({"night_direction": night, "canopy_leaf_orientation": false,
			"canopy_pigment_recovery": false,
			"flat_upper_mean": values[0], "volume_upper_mean": values[1]})
		if night:
			passed = passed and values[1] > values[0] + 0.008
		else:
			passed = passed and values[1] > 0.06 and absf(values[1] - values[0]) > 0.008
	print("MEADOW_CANOPY_RESPONSE: " + JSON.stringify(results))
	if passed:
		print("MEADOW_CANOPY_RESPONSE_AUDIT: PASS; actual broad-oak cutout shader/PNG; zero-fill private viewport; sun/moon directions; new upper-crown direct-light response")
	else:
		push_error("MEADOW_CANOPY_RESPONSE_AUDIT: FAIL; rounded crown did not produce the required actual direct-light response")
	await _tone_probe(viewport, environment, material, key)
	await _leaf_transfer_probe(scene, viewport, environment, card, camera, key, source_material)
	viewport.queue_free()

static func _tone_probe(viewport: SubViewport, environment: Environment,
		material: ShaderMaterial, key: DirectionalLight3D) -> void:
	# The same original oak, UVs, alpha, shader and camera; no synthetic texture.
	# Uniform white incident fill isolates reflectance from crown orientation.
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color.WHITE
	environment.ambient_light_energy = 0.60
	key.light_energy = 0.0
	material.set_shader_parameter("canopy_strength", 0.92)
	material.set_shader_parameter("foliage_tone", false)
	var before: Image = await _capture(viewport)
	material.set_shader_parameter("foliage_tone", true)
	var after: Image = await _capture(viewport)
	var shadow_count: int = 0
	var shadow_before: float = 0.0
	var shadow_after: float = 0.0
	var retained_detail: int = 0
	var light_count: int = 0
	var light_delta: float = 0.0
	# Keep the legacy window and selection for comparison with previous logs.
	# This is descriptive data, not the acceptance cohort for the new repair.
	for y: int in range(15, 125):
		for x: int in range(15, 145):
			var old: float = _luma(before.get_pixel(x, y))
			var now: float = _luma(after.get_pixel(x, y))
			if old < 0.12 and now > 0.016:
				shadow_count += 1
				shadow_before += old
				shadow_after += now
				retained_detail += int(now > old + 2.0 / 255.0)
			if old > 0.38:
				light_count += 1
				light_delta += absf(now - old)
	shadow_before /= float(maxi(shadow_count, 1))
	shadow_after /= float(maxi(shadow_count, 1))
	light_delta /= float(maxi(light_count, 1))
	# Turning off incident light must extinguish the repaired leaves: no neon
	# emission or all-screen exposure lift can pass this part of the probe.
	environment.ambient_light_energy = 0.0
	var dark: Image = await _capture(viewport)
	var unlit_max: float = 0.0
	for y: int in range(15, 125):
		for x: int in range(15, 145):
			unlit_max = maxf(unlit_max, _luma(dark.get_pixel(x, y)))
	var former_effect_gate_met: bool = shadow_count > 200 and retained_detail > 150 \
		and shadow_after > shadow_before + 0.014 and light_count > 100 and light_delta < 0.045
	var result: Dictionary = {"diagnostic_only": true,
		"shadow_pixels": shadow_count, "shadow_before": shadow_before,
		"shadow_after": shadow_after, "detail_pixels_above_two_codes": retained_detail,
		"highlight_pixels": light_count, "highlight_mean_delta": light_delta,
		"no_incident_light_max": unlit_max, "former_effect_gate_met": former_effect_gate_met,
		"previous_reported_webgl_observation": {"shadow_pixels": 3468,
			"shadow_before": 0.058854, "shadow_after": 0.059437,
			"detail_pixels_above_two_codes": 0}}
	print("MEADOW_FOLIAGE_TONE_RESPONSE: " + JSON.stringify(result))
	print("MEADOW_FOLIAGE_TONE_RESPONSE_AUDIT: DIAGNOSTIC_ONLY; the previous large toe-improvement hypothesis was contradicted by WebGL; no relaxed efficacy PASS")
	if unlit_max < CODE_VALUE:
		print("MEADOW_FOLIAGE_NO_INCIDENT_LIGHT_AUDIT: PASS; existing zero-light check retained")
	else:
		push_error("MEADOW_FOLIAGE_NO_INCIDENT_LIGHT_AUDIT: FAIL; oak emits without incident light")

static func _leaf_transfer_probe(scene: Node3D, viewport: SubViewport,
		environment: Environment, card: MeshInstance3D, camera: Camera3D,
		key: DirectionalLight3D, source_material: ShaderMaterial) -> void:
	for flag: String in ["canopy_backlight", "canopy_leaf_orientation", "canopy_pigment_recovery"]:
		if not _has_uniform(source_material, flag):
			push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; real oak shader lacks " + flag + "; cannot compare the agreed combined repair")
			return
	var source_enabled: bool = bool(source_material.get_shader_parameter("canopy_backlight"))
	var source_orientation: bool = bool(source_material.get_shader_parameter("canopy_leaf_orientation"))
	var source_pigment: bool = bool(source_material.get_shader_parameter("canopy_pigment_recovery"))
	var transmission: float = float(source_material.get_shader_parameter("leaf_transmission"))
	var strength: float = float(source_material.get_shader_parameter("canopy_strength"))
	var lobe_count: int = int(source_material.get_shader_parameter("canopy_count"))
	if not source_enabled or not source_orientation or not source_pigment \
			or not is_equal_approx(transmission, 0.10) or lobe_count < 1:
		print("MEADOW_LEAF_TRANSFER_RESPONSE: " + JSON.stringify({"scene_canopy_backlight": source_enabled,
			"scene_canopy_leaf_orientation": source_orientation,
			"scene_canopy_pigment_recovery": source_pigment,
			"leaf_transmission": transmission, "canopy_count": lobe_count}))
		push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; actual oak profile must enable all three repair flags with lobes and leaf_transmission=0.10")
		return
	# Fresh copy: neither the upper-normal sweep nor the toe sweep can leak into
	# this comparison. Texture, UVs, tint, exposure, toe and base crown profile
	# stay original; this bounded shade/albedo investigation measures all three
	# repair flags together, not full-scene visual acceptance.
	var material: ShaderMaterial = source_material.duplicate() as ShaderMaterial
	material.set_shader_parameter("painted_fill", 0.0)
	material.set_shader_parameter("wind_strength", 0.0)
	material.set_shader_parameter("root_contact", 0.0)
	card.material_override = material
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	environment.ambient_light_energy = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.glow_enabled = false
	var regions: Dictionary = _oak_regions(viewport, card, camera, material)
	if regions.has("error"):
		print("MEADOW_LEAF_TRANSFER_RESPONSE: " + JSON.stringify(regions))
		push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; cannot register independent source-art sample regions")
		return
	var lower_pixels: Array[Vector2i] = regions["lower"]
	var upper_pixels: Array[Vector2i] = regions["upper"]
	var crown_wood_pixels: Array[Vector2i] = regions["crown_wood"]
	var trunk_pixels: Array[Vector2i] = regions["trunk"]
	var scene_camera: Camera3D = scene.get_node("Camera3D") as Camera3D
	var weather: Node = scene.get_node("LivingWeather")
	# Global meadow_night belongs to the main world. Do not change it to fake
	# isolated night tint. Test BOTH real light directions at this logged, fixed
	# shader tint and reject a run if a scene transition contaminates the pair.
	var initial_night_blend: float = float(weather.get("night_blend"))
	var records: Array[Dictionary] = []
	var passed: bool = true
	for night: bool in [false, true]:
		_set_key_direction(scene_camera, key, night)
		material.set_shader_parameter("canopy_backlight", false)
		material.set_shader_parameter("canopy_leaf_orientation", false)
		material.set_shader_parameter("canopy_pigment_recovery", false)
		var before: Image = await _capture(viewport)
		material.set_shader_parameter("canopy_backlight", true)
		# Both orientation and pigment recovery remain false in this intermediate.
		var backlight_only: Image = await _capture(viewport)
		material.set_shader_parameter("canopy_leaf_orientation", true)
		material.set_shader_parameter("canopy_pigment_recovery", true)
		var after: Image = await _capture(viewport)
		if not _valid_readback(before, viewport.size) or not _valid_readback(backlight_only, viewport.size) \
				or not _valid_readback(after, viewport.size):
			push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; missing or incorrectly sized GPU readback")
			return
		# Bright pixels are selected from the OLD frame only, never from the gain.
		var bright_pixels: Array[Vector2i] = _brightest_quartile(before, upper_pixels)
		var lower: Dictionary = _region_delta(before, after, lower_pixels)
		# Descriptive intermediate result only: the combined PASS must not be
		# attributed solely to BACKLIGHT, whose previous moon gain missed the gate.
		var transfer_lower: Dictionary = _region_delta(before, backlight_only, lower_pixels)
		var highlights: Dictionary = _region_delta(before, after, bright_pixels)
		var crown_wood: Dictionary = _region_delta(before, after, crown_wood_pixels)
		var trunk: Dictionary = _region_delta(before, after, trunk_pixels)
		var lower_ok: bool = int(lower["pixels"]) >= LOWER_MIN_PIXELS \
			and float(lower["mean_gain"]) >= LOWER_MIN_MEAN_GAIN \
			and float(lower["fraction_above_two_codes"]) >= LOWER_MIN_IMPROVED_FRACTION
		var highlights_ok: bool = int(highlights["pixels"]) >= HIGHLIGHT_MIN_PIXELS \
			and float(highlights["mean_rgb_delta"]) <= HIGHLIGHT_MAX_MEAN_RGB_DELTA \
			and float(highlights["p95_rgb_delta"]) <= HIGHLIGHT_MAX_P95_RGB_DELTA \
			and float(highlights["clipped_after"]) <= float(highlights["clipped_before"]) + HIGHLIGHT_MAX_EXTRA_CLIPPED_FRACTION
		var wood_ok: bool = int(crown_wood["pixels"]) >= WOOD_MIN_PIXELS \
			and int(trunk["pixels"]) >= WOOD_MIN_PIXELS \
			and float(crown_wood["max_rgb_delta"]) <= WOOD_MAX_RGB_DELTA \
			and float(trunk["max_rgb_delta"]) <= WOOD_MAX_RGB_DELTA
		var tint_stable: bool = absf(float(weather.get("night_blend")) - initial_night_blend) < 0.000001
		var direction_ok: bool = lower_ok and highlights_ok and wood_ok and tint_stable
		passed = passed and direction_ok
		records.append({"night_light_direction": night, "key_energy": key.light_energy,
			"light_direction_in_camera_space": str(key.basis.z), "key_color": str(key.light_color),
			"backlight_only_diagnostic": {"diagnostic_only": true, "canopy_backlight": true,
				"canopy_leaf_orientation": false, "canopy_pigment_recovery": false,
				"lower_crown": transfer_lower},
			"lower_crown": lower, "upper_bright_quartile": highlights,
			"wood_inside_crown": crown_wood, "bare_trunk": trunk,
			"lower_pass": lower_ok, "highlight_pass": highlights_ok,
			"wood_pass": wood_ok, "shared_night_tint_stable": tint_stable,
			"direction_pass": direction_ok})
	key.light_energy = 0.0
	var dark_records: Array[Dictionary] = []
	for enabled: bool in [false, true]:
		material.set_shader_parameter("canopy_backlight", enabled)
		material.set_shader_parameter("canopy_leaf_orientation", enabled)
		material.set_shader_parameter("canopy_pigment_recovery", enabled)
		var dark: Image = await _capture(viewport)
		if not _valid_readback(dark, viewport.size):
			push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; zero-light GPU readback missing or incorrectly sized")
			return
		var dark_max: float = _image_max_rgb(dark)
		var dark_ok: bool = dark_max < CODE_VALUE
		passed = passed and dark_ok
		dark_records.append({"canopy_backlight": enabled, "canopy_leaf_orientation": enabled,
			"canopy_pigment_recovery": enabled, "max_rgb": dark_max, "pass": dark_ok})
	var final_tint_stable: bool = absf(float(weather.get("night_blend")) - initial_night_blend) < 0.000001
	passed = passed and final_tint_stable
	var texture: Texture2D = material.get_shader_parameter("asset_texture") as Texture2D
	var report: Dictionary = {"texture": texture.resource_path, "viewport": str(viewport.size),
		"source_canopy_backlight": source_enabled, "leaf_transmission": transmission,
		"source_canopy_leaf_orientation": source_orientation,
		"source_canopy_pigment_recovery": source_pigment,
		"acceptance_flags": {"before": {"canopy_backlight": false, "canopy_leaf_orientation": false,
				"canopy_pigment_recovery": false},
			"after": {"canopy_backlight": true, "canopy_leaf_orientation": true,
				"canopy_pigment_recovery": true}},
		"uv_region": str(material.get_shader_parameter("uv_region")),
		"art_exposure": float(material.get_shader_parameter("art_exposure")),
		"foliage_tone": bool(material.get_shader_parameter("foliage_tone")),
		"canopy_strength": strength, "canopy_count": lobe_count,
		"ambient_energy": 0.0, "painted_fill": 0.0, "shadow_enabled": key.shadow_enabled,
		"shared_meadow_night": initial_night_blend, "shared_night_tint_stable": final_tint_stable,
		"tonemap_exposure": environment.tonemap_exposure, "agx_contrast": environment.tonemap_agx_contrast,
		"highlight_selection": "brightest old-frame quartile of source-green upper crown",
		"thresholds": {"lower_min_pixels": LOWER_MIN_PIXELS,
			"lower_min_mean_gain": LOWER_MIN_MEAN_GAIN,
			"lower_min_fraction_above_two_codes": LOWER_MIN_IMPROVED_FRACTION,
			"highlight_min_pixels": HIGHLIGHT_MIN_PIXELS,
			"highlight_max_mean_rgb_delta": HIGHLIGHT_MAX_MEAN_RGB_DELTA,
			"highlight_max_p95_rgb_delta": HIGHLIGHT_MAX_P95_RGB_DELTA,
			"highlight_max_extra_clipped_fraction": HIGHLIGHT_MAX_EXTRA_CLIPPED_FRACTION,
			"wood_min_pixels_each": WOOD_MIN_PIXELS, "wood_max_rgb_delta": WOOD_MAX_RGB_DELTA,
			"no_incident_light_max_exclusive": CODE_VALUE},
		"directions": records, "no_incident_light": dark_records, "pass": passed}
	print("MEADOW_LEAF_TRANSFER_RESPONSE: " + JSON.stringify(report))
	if passed:
		print("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: PASS; actual oak BACKLIGHT + leaf-orientation + pigment-recovery probe; unchanged lower-leaf, highlight, wood and zero-light gates passed; BACKLIGHT-only data is diagnostic; not full-scene visual acceptance")
	else:
		push_error("MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: FAIL; combined BACKLIGHT + leaf-orientation + pigment-recovery probe missed unchanged gates; inspect per-direction and BACKLIGHT-only data; no full-scene acceptance implied")

static func _oak_regions(viewport: SubViewport, card: MeshInstance3D,
		camera: Camera3D, material: ShaderMaterial) -> Dictionary:
	var quad: QuadMesh = card.mesh as QuadMesh
	var texture: Texture2D = material.get_shader_parameter("asset_texture") as Texture2D
	if quad == null or texture == null:
		return {"error": "expected the original oak QuadMesh and texture"}
	var source: Image = texture.get_image()
	if source == null or source.is_empty():
		return {"error": "cannot read the real imported oak texture for ROI registration"}
	if source.is_compressed():
		var error: Error = source.decompress()
		if error != OK:
			return {"error": "cannot decompress the oak image for source-only ROI selection"}
	var top_left: Vector2 = camera.unproject_position(card.to_global(quad.center_offset + Vector3(-quad.size.x, quad.size.y, 0.0) * 0.5))
	var bottom_right: Vector2 = camera.unproject_position(card.to_global(quad.center_offset + Vector3(quad.size.x, -quad.size.y, 0.0) * 0.5))
	var frame: Rect2 = Rect2(top_left, bottom_right - top_left)
	if frame.size.x <= 0.0 or frame.size.y <= 0.0:
		return {"error": "invalid source UV to viewport registration"}
	var uv_region: Vector4 = material.get_shader_parameter("uv_region")
	var region_size: Vector2 = Vector2(uv_region.z, uv_region.w)
	var source_step: Vector2 = region_size / frame.size
	var flip: bool = bool(material.get_shader_parameter("sprite_flip"))
	var lower: Array[Vector2i] = []
	var upper: Array[Vector2i] = []
	var crown_wood: Array[Vector2i] = []
	var trunk: Array[Vector2i] = []
	for y: int in range(viewport.size.y):
		for x: int in range(viewport.size.x):
			var uv: Vector2 = (Vector2(float(x) + 0.5, float(y) + 0.5) - frame.position) / frame.size
			if flip:
				uv.x = 1.0 - uv.x
			if not (LOWER_CROWN_UV.has_point(uv) or UPPER_CROWN_UV.has_point(uv) \
					or CROWN_WOOD_UV.has_point(uv) or BARE_TRUNK_UV.has_point(uv)):
				continue
			var source_uv: Vector2 = Vector2(uv_region.x, uv_region.y) + uv * region_size
			var kind: int = _source_patch_kind(source, source_uv, source_step)
			var pixel: Vector2i = Vector2i(x, y)
			if kind == 1:
				if LOWER_CROWN_UV.has_point(uv):
					lower.append(pixel)
				if UPPER_CROWN_UV.has_point(uv):
					upper.append(pixel)
			elif kind == 2:
				if CROWN_WOOD_UV.has_point(uv):
					crown_wood.append(pixel)
				if BARE_TRUNK_UV.has_point(uv):
					trunk.append(pixel)
	return {"lower": lower, "upper": upper, "crown_wood": crown_wood, "trunk": trunk}

static func _source_patch_kind(source: Image, uv: Vector2, step_uv: Vector2) -> int:
	# A 3x3 footprint one rendered pixel apart excludes alpha/leaf-wood borders.
	# These source colours only classify samples; NEVER linearize them to predict
	# the shader's contrast clipping or to manufacture a lighting result.
	var leaf: bool = true
	var wood: bool = true
	for y: int in range(-1, 2):
		for x: int in range(-1, 2):
			var at: Vector2 = uv + Vector2(x, y) * step_uv
			var pixel: Vector2i = Vector2i(clampi(int(floor(at.x * source.get_width())), 0, source.get_width() - 1),
				clampi(int(floor(at.y * source.get_height())), 0, source.get_height() - 1))
			var color: Color = source.get_pixelv(pixel)
			if color.a < 250.0 / 255.0:
				return 0
			leaf = leaf and color.g > color.r * 1.03 and color.g > color.b * 1.05
			wood = wood and color.r > color.g * 1.06 and color.g > color.b * 1.04
	return 1 if leaf else (2 if wood else 0)

static func _brightest_quartile(before: Image, candidates: Array[Vector2i]) -> Array[Vector2i]:
	var selected: Array[Vector2i] = []
	if candidates.is_empty():
		return selected
	var values: Array[float] = []
	for pixel: Vector2i in candidates:
		values.append(_luma(before.get_pixelv(pixel)))
	values.sort()
	var cutoff: float = values[mini(int(floor(values.size() * 0.75)), values.size() - 1)]
	for pixel: Vector2i in candidates:
		if _luma(before.get_pixelv(pixel)) >= cutoff:
			selected.append(pixel)
	return selected

static func _region_delta(before: Image, after: Image, pixels: Array[Vector2i]) -> Dictionary:
	var old_sum: float = 0.0
	var new_sum: float = 0.0
	var rgb_sum: float = 0.0
	var rgb_max: float = 0.0
	var improved: int = 0
	var clipped_before: int = 0
	var clipped_after: int = 0
	var rgb_deltas: Array[float] = []
	for pixel: Vector2i in pixels:
		var old: Color = before.get_pixelv(pixel)
		var now: Color = after.get_pixelv(pixel)
		var delta: float = maxf(absf(now.r - old.r), maxf(absf(now.g - old.g), absf(now.b - old.b)))
		old_sum += _luma(old)
		new_sum += _luma(now)
		rgb_sum += delta
		rgb_max = maxf(rgb_max, delta)
		rgb_deltas.append(delta)
		improved += int(_luma(now) - _luma(old) > 2.0 * CODE_VALUE)
		clipped_before += int(maxf(old.r, maxf(old.g, old.b)) >= 254.0 * CODE_VALUE)
		clipped_after += int(maxf(now.r, maxf(now.g, now.b)) >= 254.0 * CODE_VALUE)
	rgb_deltas.sort()
	var p95: float = 0.0
	if not rgb_deltas.is_empty():
		p95 = rgb_deltas[clampi(int(ceil(rgb_deltas.size() * 0.95)) - 1, 0, rgb_deltas.size() - 1)]
	var divisor: float = float(maxi(pixels.size(), 1))
	return {"pixels": pixels.size(), "before_mean": old_sum / divisor, "after_mean": new_sum / divisor,
		"mean_gain": (new_sum - old_sum) / divisor, "pixels_above_two_codes": improved,
		"fraction_above_two_codes": float(improved) / divisor, "mean_rgb_delta": rgb_sum / divisor,
		"p95_rgb_delta": p95, "max_rgb_delta": rgb_max,
		"clipped_before": float(clipped_before) / divisor, "clipped_after": float(clipped_after) / divisor}

static func _image_max_rgb(rendered: Image) -> float:
	var maximum: float = 0.0
	for y: int in range(rendered.get_height()):
		for x: int in range(rendered.get_width()):
			var color: Color = rendered.get_pixel(x, y)
			maximum = maxf(maximum, maxf(color.r, maxf(color.g, color.b)))
	return maximum

static func _has_uniform(material: ShaderMaterial, uniform_name: String) -> bool:
	for uniform: Dictionary in material.shader.get_shader_uniform_list():
		if String(uniform.get("name", "")) == uniform_name:
			return true
	return false

static func _set_key_direction(scene_camera: Camera3D, key: DirectionalLight3D, night: bool) -> void:
	var rotation: Vector3 = WEATHER.NIGHT_KEY_ROTATION if night else WEATHER.DAY_KEY_ROTATION
	key.basis = scene_camera.global_basis.inverse() * Basis.from_euler(rotation * PI / 180.0)
	key.light_energy = WEATHER.NIGHT_MOON_ENERGY if night else WEATHER.DAY_SUN_ENERGY
	key.light_color = Color(0.65, 0.79, 1.0) if night else Color(1.0, 0.84, 0.62)

static func _capture(viewport: SubViewport) -> Image:
	for _frame: int in range(5):
		await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()

static func _valid_readback(rendered: Image, expected_size: Vector2i) -> bool:
	return rendered != null and not rendered.is_empty() and rendered.get_size() == expected_size

static func _luma(color: Color) -> float:
	return color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722
