extends RefCounted
## Opt-in actual GPU readback on the real castle mesh, PNG and architecture shader.

const ARCHITECTURE_FOG = preload("res://scripts/meadow_architecture_fog.gd")

static func run(scene: Node3D) -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(480, 192)
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
	world.environment = environment
	viewport.add_child(world)
	var original: MeshInstance3D = scene.get_node("IndependentCastleHill")
	var card := MeshInstance3D.new()
	card.mesh = original.mesh
	card.position = -card.mesh.get_aabb().get_center()
	var material: ShaderMaterial = original.material_override.duplicate()
	material.set_shader_parameter("painted_fill", 0.0)
	material.set_shader_parameter("root_contact", 0.0)
	material.set_shader_parameter("window_count", 0)
	# This viewport owns its disabled fog; never inherit the main viewport's enable flag.
	ARCHITECTURE_FOG.sync_material(material, environment, float(scene.get_node("LivingWeather").get("night_blend")))
	card.material_override = material
	viewport.add_child(card)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = maxf(card.mesh.get_aabb().size.y, card.mesh.get_aabb().size.x / 2.5) * 1.08
	camera.position.z = 12.0
	viewport.add_child(camera)
	var key := DirectionalLight3D.new()
	key.shadow_enabled = false
	viewport.add_child(key)
	var texture: Texture2D = material.get_shader_parameter("asset_texture")
	var size := Vector2(texture.get_width(), texture.get_height())
	# Three left-facing roof interiors plus an unprofiled control surface.
	var pixels := [Vector2(1335, 82), Vector2(1184, 133), Vector2(1290, 126), Vector2(1543, 334)]
	var sample_positions: Array[Vector2i] = []
	for pixel: Vector2 in pixels:
		var point := _mesh_point(card.mesh, pixel / size)
		assert(point.is_finite())
		sample_positions.append(Vector2i(camera.unproject_position(card.position + point)))
	var passed := true
	var records: Array[Dictionary] = []
	for night: bool in [false, true]:
		key.rotation_degrees = scene.WEATHER_CONTROLLER.NIGHT_KEY_ROTATION if night else scene.WEATHER_CONTROLLER.DAY_KEY_ROTATION
		key.light_energy = 1.20 if night else 1.90
		key.light_color = Color(0.65, 0.79, 1.0) if night else Color(1.0, 0.84, 0.62)
		var comparisons: Array[PackedFloat32Array] = []
		for strength: float in [0.0, 1.0]:
			material.set_shader_parameter("architecture_strength", strength)
			for frame in range(5):
				await RenderingServer.frame_post_draw
			var rendered := viewport.get_texture().get_image()
			var values := PackedFloat32Array()
			for pixel: Vector2i in sample_positions:
				var sum := 0.0
				for y in range(-1, 2):
					for x in range(-1, 2):
						var c := rendered.get_pixel(pixel.x + x, pixel.y + y)
						sum += c.r * 0.2126 + c.g * 0.7152 + c.b * 0.0722
				values.append(sum / 9.0)
			comparisons.append(values)
		var old_mean := (comparisons[0][0] + comparisons[0][1] + comparisons[0][2]) / 3.0
		var new_mean := (comparisons[1][0] + comparisons[1][1] + comparisons[1][2]) / 3.0
		var control_error := absf(comparisons[0][3] - comparisons[1][3])
		passed = passed and control_error <= 2.0 / 255.0
		# A front wall must face the sun, not receive the moon through its back.
		passed = passed and (comparisons[0][3] < 0.003 if night else comparisons[0][3] > 0.04)
		passed = passed and (new_mean > old_mean + 0.006 if night else absf(new_mean - old_mean) > 0.01)
		records.append({"night_direction": night, "flat_roof_mean": old_mean, "profiled_roof_mean": new_mean, "control_error": control_error, "before": str(comparisons[0]), "after": str(comparisons[1])})
	print("MEADOW_ARCHITECTURE_RESPONSE: " + JSON.stringify(records))
	if passed:
		print("MEADOW_ARCHITECTURE_RESPONSE_AUDIT: PASS; actual castle shader/PNG/mesh; zero-fill sun/moon roof response; unprofiled control unchanged")
	else:
		push_error("MEADOW_ARCHITECTURE_RESPONSE_AUDIT: FAIL; directional roof response or unprofiled control failed")
	viewport.queue_free()
	if OS.has_feature("web") and JavaScriptBridge.eval("new URLSearchParams(location.search).get('architecture_layers') === '1'"):
		await diagnose_layers(scene)

static func diagnose_layers(scene: Node3D) -> void:
	# Temporary single-variable substitutions; restore original references BEFORE statistics/errors.
	for frame in range(3):
		await scene.get_tree().process_frame
	var viewport := scene.get_viewport()
	var camera := viewport.get_camera_3d()
	var world: WorldEnvironment = scene.get_node("WorldEnvironment")
	var original_environment := world.environment
	var weather: Node = scene.get_node("LivingWeather")
	var cards: Array[MeshInstance3D] = []
	var materials: Array[ShaderMaterial] = []
	for label: String in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		cards.append(scene.get_node(NodePath(label)) as MeshInstance3D)
		materials.append(cards[-1].material_override as ShaderMaterial)
	if camera == null or weather.get("transitioning") == true:
		print("MEADOW_ARCHITECTURE_LAYERS: SKIP; missing active camera or weather transition")
		return
	for experiment: String in ["baseline", "fog_disabled", "ambient_disabled", "painted_fill_zero", "restored"]:
		var environment := original_environment.duplicate() as Environment
		if experiment == "fog_disabled":
			environment.fog_enabled = false
		if experiment == "ambient_disabled":
			environment.ambient_light_source = Environment.AMBIENT_SOURCE_DISABLED
			environment.ambient_light_energy = 0.0
		world.environment = environment
		var sampled_materials: Array[ShaderMaterial] = []
		for i in range(cards.size()):
			var temporary := materials[i].duplicate() as ShaderMaterial
			if experiment == "painted_fill_zero":
				temporary.set_shader_parameter("painted_fill", 0.0)
			if i < 2:
				ARCHITECTURE_FOG.sync_material(temporary, environment, float(weather.get("night_blend")))
			cards[i].material_override = temporary
			sampled_materials.append(temporary)
		for frame in range(5):
			await RenderingServer.frame_post_draw
		var rendered := viewport.get_texture().get_image()
		world.environment = original_environment
		for i in range(cards.size()):
			cards[i].material_override = materials[i]
			if i < 2:
				ARCHITECTURE_FOG.sync_material(materials[i], original_environment, float(weather.get("night_blend")))
		if rendered == null or rendered.is_empty():
			push_error("MEADOW_ARCHITECTURE_LAYERS: empty image; original resources restored")
			return
		var parameters := {"experiment": experiment, "diagnostic_only": true, "restored_before_analysis": true, "viewport": str(viewport.get_visible_rect()), "image_size": str(rendered.get_size()), "image_format": rendered.get_format(), "camera_transform": str(camera.global_transform), "projection": str(camera.get_camera_projection()), "night": weather.get("night_blend"), "clock": weather.get("animation_clock"), "motion": weather.get("motion_enabled"), "transitioning": weather.get("transitioning"), "lights": {}, "materials": {}}
		for property: Dictionary in environment.get_property_list():
			var key := str(property.name)
			if key.begins_with("fog_") or key.begins_with("ambient_") or key.begins_with("reflected_") or key.begins_with("tonemap_") or key.begins_with("adjustment_"):
				parameters[key] = str(environment.get(key))
		for light: Node in scene.find_children("*", "DirectionalLight3D", false, false):
			parameters.lights[str(light.name)] = [str(light.rotation_degrees), str(light.light_color), light.light_energy, light.visible, light.light_cull_mask, light.shadow_enabled]
		for i in range(cards.size()):
			var values := {}
			for key: String in ["painted_fill", "architecture_strength", "architecture_count", "art_exposure", "art_contrast", "tint", "window_count", "window_energy", "root_contact", "mip_bias"]:
				values[key] = str(sampled_materials[i].get_shader_parameter(key))
			values["shader"] = sampled_materials[i].shader.resource_path
			if sampled_materials[i].shader == ARCHITECTURE_FOG.DAY_SHADER:
				for key: String in ["architecture_fog_enabled", "architecture_fog_density", "architecture_fog_linear_color"]:
					values[key] = str(sampled_materials[i].get_shader_parameter(key))
			if experiment == "painted_fill_zero":
				values["painted_fill"] = "0.0"
				values["coupling"] = {"warning": "NOT emission-only: removes painted EMISSION AND increases ALBEDO factor", "albedo_factor_before": 1.0 - float(materials[i].get_shader_parameter("painted_fill")), "albedo_factor_after": 1.0}
			parameters.materials[str(cards[i].name)] = values
		var regions := {}
		for i in range(2):
			var roi := _layer_roi(camera, cards[i], viewport.get_visible_rect(), rendered.get_size())
			regions[str(cards[i].name)] = _layer_statistics(rendered, roi)
		print("MEADOW_ARCHITECTURE_LAYERS: " + JSON.stringify({"parameters": parameters, "regions": regions}))
	for frame in range(5):
		await RenderingServer.frame_post_draw
	print("MEADOW_ARCHITECTURE_LAYERS: DONE; environment/material references restored; sun unchanged; no images saved; not acceptance")

static func _layer_roi(camera: Camera3D, card: MeshInstance3D, visible: Rect2, image_size: Vector2i) -> Rect2i:
	# Actual camera projection already owns the 16:10 framing; map its logical rect to readback pixels.
	var bounds := Rect2(camera.unproject_position(card.to_global(card.mesh.get_aabb().position)), Vector2.ZERO)
	for corner in range(8):
		bounds = bounds.expand(camera.unproject_position(card.to_global(card.mesh.get_aabb().get_endpoint(corner))))
	# Interior rectangle reduces transparent gutters; includes background/occlusion, not an alpha mask.
	bounds = Rect2(bounds.position + bounds.size * Vector2(0.08, 0.12), bounds.size * Vector2(0.84, 0.70))
	var scale_to_image := minf(float(image_size.x) / visible.size.x, float(image_size.y) / visible.size.y)
	var letterbox := (Vector2(image_size) - visible.size * scale_to_image) * 0.5
	var first := ((bounds.position - visible.position) * scale_to_image + letterbox).floor()
	var last := ((bounds.end - visible.position) * scale_to_image + letterbox).ceil()
	return Rect2i(Vector2i(first), Vector2i(last - first)).intersection(Rect2i(Vector2i.ZERO, image_size))

static func _layer_statistics(rendered: Image, roi: Rect2i) -> Dictionary:
	if not roi.has_area():
		return {"roi": str(roi), "error": "offscreen/empty"}
	var sum := Vector4.ZERO
	var squares := Vector4.ZERO
	var low := Vector4(INF, INF, INF, INF)
	var high := Vector4(-INF, -INF, -INF, -INF)
	for y in range(roi.position.y, roi.end.y):
		for x in range(roi.position.x, roi.end.x):
			var c := rendered.get_pixel(x, y)
			var v := Vector4(c.r, c.g, c.b, c.r * 0.2126 + c.g * 0.7152 + c.b * 0.0722)
			sum += v
			squares += v * v
			for channel in range(4):
				low[channel] = minf(low[channel], v[channel])
				high[channel] = maxf(high[channel], v[channel])
	var mean := sum / float(roi.get_area())
	var variance := squares / float(roi.get_area()) - mean * mean
	for channel in range(4):
		variance[channel] = sqrt(maxf(variance[channel], 0.0))
	return {"roi": str(roi), "pixels": roi.get_area(), "channels": "R,G,B,luma; readback code values", "mean": str(mean), "stddev": str(variance), "min": str(low), "max": str(high)}

static func _mesh_point(mesh: Mesh, uv: Vector2) -> Vector3:
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	for i in range(0, indices.size(), 3):
		var ia := indices[i]
		var ib := indices[i + 1]
		var ic := indices[i + 2]
		var a := uvs[ia]
		var ab := uvs[ib] - a
		var ac := uvs[ic] - a
		var determinant := ab.cross(ac)
		if absf(determinant) < 0.0000001:
			continue
		var p := uv - a
		var u := p.cross(ac) / determinant
		var v := ab.cross(p) / determinant
		if u >= -0.00001 and v >= -0.00001 and u + v <= 1.00001:
			return vertices[ia] + (vertices[ib] - vertices[ia]) * u + (vertices[ic] - vertices[ia]) * v
	return Vector3(INF, INF, INF)
