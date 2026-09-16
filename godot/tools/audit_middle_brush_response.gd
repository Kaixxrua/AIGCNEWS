extends RefCounted
## v90 vs v85 combined tint/BACKLIGHT GPU A/B; no individual attribution.
## No scene/cache/global-clock mutation.
## Root 600 is registered before readback; controls never select pixels by gain.
const ROOT_INDEX := 600
const REPAIR := "    if (middle_scrub && UV.x >= -900.0) {\n        BACKLIGHT = vec3(0.18);\n    }\n"
const NEW_PIGMENT := "pigment *= mix(vec3(0.86, 0.94, 0.78), vec3(0.93, 0.97, 0.85), outer_leaf);"
const OLD_PIGMENT := "pigment *= mix(vec3(0.70, 0.82, 0.63), vec3(0.89, 0.94, 0.78), outer_leaf);"
const SIZE := Vector2i(256, 256)
const MARKER := "MEADOW_MIDDLE_BRUSH_RESPONSE_AUDIT"

static func run(scene: Node3D) -> void:
	var started := Time.get_ticks_msec()
	var original := scene.get_node_or_null("MiddleMeadowBrush") as MeshInstance3D
	if original == null or not original.mesh is ArrayMesh:
		push_error(MARKER + ": FAIL; actual cached ArrayMesh is missing")
		return
	var original_mesh := original.mesh as ArrayMesh
	var actual := original.material_override as ShaderMaterial
	if actual == null or actual.shader == null or original_mesh.get_surface_count() != 1:
		push_error(MARKER + ": FAIL; expected one surface and the actual ShaderMaterial")
		return
	var code := actual.shader.code.replace("\r\n", "\n")
	var flags := _effective_flags(actual)
	if flags.is_empty():
		return
	print("MEADOW_MIDDLE_BRUSH_RESPONSE_FLAGS: " + JSON.stringify(flags))
	if flags["middle_scrub"] != true or flags["foothill_scrub"] != false \
			or code.count(REPAIR) != 1 or code.count("render_mode cull_disabled, diffuse_burley;") != 1 \
			or code.count("BACKLIGHT = pigment * 0.06;") != 1 or code.count("void fragment()") != 1 \
			or code.count(NEW_PIGMENT) != 1:
		var middle_value: Variant = actual.get_shader_parameter("middle_scrub")
		var foothill_value: Variant = actual.get_shader_parameter("foothill_scrub")
		print("MEADOW_MIDDLE_BRUSH_RESPONSE_EARLY: " + JSON.stringify({
			"middle_scrub": middle_value, "middle_variant_type": type_string(typeof(middle_value)),
			"middle_effective": flags["middle_scrub"],
			"foothill_scrub": foothill_value, "foothill_variant_type": type_string(typeof(foothill_value)),
			"foothill_effective": flags["foothill_scrub"],
			"shader_resource_path": actual.shader.resource_path,
			"code_length_lf": code.length(), "code_sha256_lf": code.sha256_text(),
			"repair_count": code.count(REPAIR),
			"new_pigment_count": code.count(NEW_PIGMENT),
			"render_mode_count": code.count("render_mode cull_disabled, diffuse_burley;"),
			"original_backlight_count": code.count("BACKLIGHT = pigment * 0.06;"),
			"fragment_count": code.count("void fragment()")}))
		push_error(MARKER + ": FAIL; expected actual middle material and exactly one of each combined repair")
		return
	var roots: PackedVector3Array = original.get_meta("roots", PackedVector3Array())
	var faces: PackedInt32Array = original.get_meta("root_faces", PackedInt32Array())
	var arrays := original_mesh.surface_get_arrays(0)
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX] if arrays[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var corners := indices.size() if not indices.is_empty() else vertices.size()
	if roots.size() != 1204 or faces.size() != roots.size() \
			or original_mesh.surface_get_primitive_type(0) != Mesh.PRIMITIVE_TRIANGLES \
			or corners != 96320 * 3 or faces[ROOT_INDEX + 1] - faces[ROOT_INDEX] != 80:
		push_error(MARKER + ": FAIL; expected frozen 1204-root / 96320-triangle geometry")
		return
	for channel in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
		if arrays[channel] == null or arrays[channel].size() != vertices.size():
			push_error(MARKER + ": FAIL; required actual per-vertex channel missing")
			return
	var first := faces[ROOT_INDEX] * 3
	if first < 0 or first + 240 > 96320 * 3:
		push_error(MARKER + ": FAIL; registered root range is outside the actual mesh")
		return
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	# Cached vertices are deduplicated; root_faces addresses INDEX corner order.
	# Real emitted twigs precede the 36 leaflets. Verify before slicing controls.
	for i in range(240):
		var at := indices[first + i] if not indices.is_empty() else first + i
		if at < 0 or at >= vertices.size():
			push_error(MARKER + ": FAIL; selected cached index is outside vertex arrays")
			return
		if (uv[at].x < -1800.0 if i < 24 else uv[at].x >= -900.0):
			continue
		push_error(MARKER + ": FAIL; actual twig/leaf UV markers disagree with registered root")
		return
	var old_shader := Shader.new()
	old_shader.code = code.replace(REPAIR, "").replace(NEW_PIGMENT, OLD_PIGMENT)
	# Source audit owns equivalence to frozen v85. OFF removes the exact
	# BACKLIGHT repair and restores the original tint mix,
	# keeping middle_scrub true. Combined v90 vs v85, not individual attribution.
	var mask_shader := Shader.new()
	mask_shader.code = code.get_slice("void fragment()", 0).replace(
		"render_mode cull_disabled, diffuse_burley;", "render_mode cull_disabled, unshaded;") \
		+ "void fragment() { ALBEDO = UV.x < -1800.0 ? vec3(1,0,0) : (UV.x >= -900.0 ? vec3(0,1,0) : vec3(0)); }\n"
	# Runtime load avoids a preload cycle when canopy's optional dispatch calls us.
	var metrics = load("res://tools/audit_canopy_response.gd")
	var weather: Node = scene.get_node("LivingWeather")
	var initial_night := float(weather.get("night_blend"))
	var records: Array[Dictionary] = []
	var passed := true
	for label: String in ["middle_leaf", "wood_only", "other_leaf", "foothill_leaf"]:
		var material_source := actual
		if label == "other_leaf":
			var understory := scene.get_node("LivingMeadowUnderstory") as MeshInstance3D
			material_source = understory.material_override as ShaderMaterial
		elif label == "foothill_leaf":
			var foothill := scene.get_node("CastleFoothillWoodland") as MeshInstance3D
			material_source = foothill.material_override as ShaderMaterial
		if material_source == null or material_source.shader == null \
				or material_source.shader.resource_path != actual.shader.resource_path:
			push_error(MARKER + ": FAIL; unexpected actual control material")
			return
		var control_flags := _effective_flags(material_source)
		if control_flags.is_empty():
			return
		if control_flags["middle_scrub"] != (label in ["middle_leaf", "wood_only"]) \
				or control_flags["foothill_scrub"] != (label == "foothill_leaf"):
			push_error(MARKER + ": FAIL; unexpected actual control material")
			return
		# Nonmiddle cases use their real materials on the SAME root fixture, not
		# a claim that the entire understory/foothill mesh has been GPU inspected.
		var mesh := _slice(arrays, first, 24 if label == "wood_only" else 240)
		var rigs: Array[Dictionary] = []
		for variant in range(3):
			var material := material_source.duplicate() as ShaderMaterial
			if variant != 1:
				material.shader = old_shader if variant == 0 else mask_shader
			rigs.append(_rig(scene, original, mesh, material, variant == 2))
		for direction in range(3): # Sun, moon direction, then no incident light.
			for rig: Dictionary in rigs:
				var key: DirectionalLight3D = rig["key"]
				key.rotation_degrees = Vector3(-28, -145, 0) if direction == 1 else Vector3(-34, 72, 0)
				key.light_energy = 0.0 if direction == 2 else (1.20 if direction == 1 else 1.90)
				key.light_color = Color(0.65, 0.79, 1.0) if direction == 1 else Color(1.0, 0.84, 0.62)
			for _frame in range(5):
				await RenderingServer.frame_post_draw
			# All three images belong to one frame: actual wind/cloud clock stays
			# shared and untouched; sequential five-frame A/B would be invalid.
			var before: Image = rigs[0]["viewport"].get_texture().get_image()
			var after: Image = rigs[1]["viewport"].get_texture().get_image()
			var mask: Image = rigs[2]["viewport"].get_texture().get_image()
			if not metrics._valid_readback(before, SIZE) or not metrics._valid_readback(after, SIZE) \
					or not metrics._valid_readback(mask, SIZE):
				for rig: Dictionary in rigs:
					rig["viewport"].queue_free()
				push_error(MARKER + ": FAIL; missing or incorrectly sized GPU readback")
				return
			var stable := absf(float(weather.get("night_blend")) - initial_night) < 0.000001
			var record := {"case": label, "direction": direction, "night_blend_stable": stable,
				"middle_scrub": control_flags["middle_scrub"],
				"foothill_scrub": control_flags["foothill_scrub"]}
			var ok := stable
			if direction == 2:
				var old_max: float = metrics._image_max_rgb(before)
				var new_max: float = metrics._image_max_rgb(after)
				ok = ok and old_max < 1.0 / 255.0 and new_max < 1.0 / 255.0
				record.merge({"zero_light_before_max": old_max, "zero_light_after_max": new_max})
			else:
				var pixels := _pixels(mask, label == "wood_only")
				var minimum := 24 if label == "wood_only" else 200
				if pixels.size() < minimum:
					record.merge({"pixels": pixels.size(), "minimum": minimum,
						"roi_error": "insufficient eroded actual UV-marker coverage", "pass": false})
					records.append(record)
					passed = false
					continue
				var delta: Dictionary = metrics._region_delta(before, after, pixels)
				record["all_visible"] = delta
				if label == "middle_leaf":
					# Existing display-code/highlight standards, fixed before any
					# readback. Dark half is selected only from OFF, never gain.
					var values: Array[float] = []
					for pixel: Vector2i in pixels:
						values.append(metrics._luma(before.get_pixelv(pixel)))
					values.sort()
					var shade: Array[Vector2i] = []
					for pixel: Vector2i in pixels:
						if metrics._luma(before.get_pixelv(pixel)) <= values[values.size() >> 1]:
							shade.append(pixel)
					var lower: Dictionary = metrics._region_delta(before, after, shade)
					var bright: Dictionary = metrics._region_delta(before, after, metrics._brightest_quartile(before, pixels))
					ok = ok and int(lower["pixels"]) >= 200 and float(lower["mean_gain"]) >= 2.0 / 255.0 \
						and float(lower["fraction_above_two_codes"]) >= 0.25
					ok = ok and int(bright["pixels"]) >= 50 and float(bright["mean_rgb_delta"]) <= 12.0 / 255.0 \
						and float(bright["p95_rgb_delta"]) <= 24.0 / 255.0 \
						and float(bright["clipped_after"]) <= float(bright["clipped_before"]) + 0.01
					record.merge({"off_frame_dark_half": lower, "off_frame_bright_quartile": bright})
				else:
					ok = ok and pixels.size() >= (24 if label == "wood_only" else 200) \
						and float(delta["max_rgb_delta"]) <= 2.0 / 255.0
			passed = passed and ok
			record["pass"] = ok
			records.append(record)
		for rig: Dictionary in rigs:
			rig["viewport"].queue_free()
	var environment: Environment = scene.get_node("WorldEnvironment").environment
	print("MEADOW_MIDDLE_BRUSH_RESPONSE: " + JSON.stringify({"root_index": ROOT_INDEX,
		"root": str(roots[ROOT_INDEX]), "fixture_triangles": 80, "leaflets": 36, "wood_triangles": 8,
		"source_indexed": not indices.is_empty(), "source_vertices": vertices.size(), "source_corners": corners,
		"material": actual.shader.resource_path, "viewport": str(SIZE), "same_frame_ab": true,
		"shared_meadow_night": initial_night, "exposure": environment.tonemap_exposure,
		"contrast": environment.tonemap_agx_contrast, "saturation": environment.adjustment_saturation,
		"ambient": 0.0, "shadows": false, "probe_elapsed_ms": Time.get_ticks_msec() - started,
		"records": records, "pass": passed}))
	if passed:
		print(MARKER + ": PASS; actual cached root/material combined v90 vs v85 tint/BACKLIGHT OFF/ON, not individual attribution; leaf efficacy, highlights, wood, nonmiddle material controls and zero light; directional stress only, not actual night endpoint or full-scene visual/performance acceptance")
	else:
		push_error(MARKER + ": FAIL; inspect fixed ROI coverage, efficacy, highlight/control/zero-light records; no existing gate relaxed")

static func _effective_flags(material: ShaderMaterial) -> Dictionary:
	var result := {}
	for flag: String in ["middle_scrub", "foothill_scrub"]:
		if material.shader.code.count("uniform bool %s = false;" % flag) != 1:
			push_error(MARKER + ": FAIL; expected exact false shader declaration for " + flag)
			return {}
		var value: Variant = material.get_shader_parameter(flag)
		var kind := typeof(value)
		if kind != TYPE_NIL and kind != TYPE_BOOL:
			push_error(MARKER + ": FAIL; " + flag + " must be Nil/default or bool, got " + type_string(kind))
			return {}
		# Web bool(null) is not a safe way to resolve a shader's unset override.
		result[flag] = false if kind == TYPE_NIL else value
	return result

static func _slice(arrays: Array, first: int, count: int) -> ArrayMesh:
	var result := []
	result.resize(Mesh.ARRAY_MAX)
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX] if arrays[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
	for channel in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
		# Expand ONLY this selected face range, retaining every real attribute.
		var values: Variant = arrays[channel].slice(0, 0)
		values.resize(count)
		for i in range(count):
			var at := indices[first + i] if not indices.is_empty() else first + i
			values[i] = arrays[channel][at]
		result[channel] = values
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, result)
	return mesh

static func _rig(scene: Node3D, original: MeshInstance3D, mesh: ArrayMesh,
		material: ShaderMaterial, mask: bool) -> Dictionary:
	var viewport := SubViewport.new()
	viewport.size = SIZE
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	scene.add_child(viewport)
	var world := WorldEnvironment.new()
	var environment: Environment = scene.get_node("WorldEnvironment").environment.duplicate()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.sky = null
	environment.fog_enabled = false
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
	environment.ambient_light_energy = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.ssao_enabled = false
	environment.glow_enabled = false
	if mask: # IDs only; geometry/depth/vertex clock remain exact, not shaded RGB.
		environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
		environment.tonemap_exposure = 1.0
		environment.adjustment_enabled = false
	world.environment = environment
	viewport.add_child(world)
	var card := MeshInstance3D.new()
	card.mesh = mesh
	card.material_override = material
	card.layers = original.layers
	card.cast_shadow = original.cast_shadow
	viewport.add_child(card)
	card.global_transform = original.global_transform # Keep procedural pigment world coordinates.
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	var source_camera := scene.get_node("Camera3D") as Camera3D
	camera.basis = source_camera.global_basis
	var bounds := mesh.get_aabb()
	var centre := original.global_transform * bounds.get_center()
	var extent := 0.0
	for i in range(8):
		var p := camera.basis.inverse() * (original.global_transform * bounds.get_endpoint(i) - centre)
		extent = maxf(extent, maxf(absf(p.x), absf(p.y)))
	camera.size = extent * 2.2 + 0.14 # Fit actual geometry plus unchanged wind reserve.
	camera.position = centre + camera.basis.z * (bounds.size.length() + 12.0)
	viewport.add_child(camera)
	var key := DirectionalLight3D.new()
	key.shadow_enabled = false
	viewport.add_child(key)
	return {"viewport": viewport, "key": key}

static func _pixels(mask: Image, wood: bool) -> Array[Vector2i]:
	var result: Array[Vector2i] = []
	for y in range(1, SIZE.y - 1):
		for x in range(1, SIZE.x - 1):
			var centre := mask.get_pixel(x, y)
			if not (centre.r > 0.9 and centre.g < 0.1 if wood else centre.g > 0.9 and centre.r < 0.1):
				continue
			var inside := true
			for dy in range(-1, 2):
				for dx in range(-1, 2):
					var c := mask.get_pixel(x + dx, y + dy)
					inside = inside and (c.r > 0.9 and c.g < 0.1 if wood else c.g > 0.9 and c.r < 0.1)
					if not inside:
						break
				if not inside:
					break
			if inside:
				result.append(Vector2i(x, y))
	return result
