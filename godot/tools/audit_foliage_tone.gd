extends SceneTree
## Reflectance scope and old-world regression; appearance is checked in WebGL.
const SOURCE_STRIDE := 8
const CUTOUT_SHADERS := ["res://shaders/meadow_cutout.gdshader",
	"res://shaders/meadow_distant_cutout.gdshader", "res://shaders/meadow_architecture.gdshader"]

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var preserved := 0
	# v77 intentionally changes MiddleMeadowBrush proportions. Its roots, real
	# leaf mass, budget and wind clearance belong to audit_middle_meadow_mass.gd.
	for group: String in ["terrain", "detail", "foothill", "riverbank"]:
		var previous: Node3D = load("res://assets/baked/v76/" + group + ".scn").instantiate()
		for before: MeshInstance3D in previous.get_children():
			var now: MeshInstance3D = scene.get_node(NodePath(before.name))
			assert(before.transform == now.transform)
			var a := before.mesh.surface_get_arrays(0)
			var b := now.mesh.surface_get_arrays(0)
			for channel in range(Mesh.ARRAY_MAX):
				assert(a[channel] == b[channel], "Reflectance repair must not move/rebuild differently: %s/%d" % [before.name, channel])
			assert(before.cast_shadow == now.cast_shadow)
			preserved += 1
		previous.free()
	assert(preserved == 8)
	assert(ProjectSettings.get_setting("rendering/renderer/rendering_method") == "gl_compatibility")
	var backlit_trees := _verify_backlight_scope(scene)
	var plants := 0
	var nonplants := 0
	var zeroed_channels := 0
	var measured_channels := 0
	var source_images := {}
	for node in scene.get_children():
		if not node is MeshInstance3D or not node.has_meta("art_foot"):
			continue
		var material: ShaderMaterial = node.material_override
		var texture: Texture2D = material.get_shader_parameter("asset_texture")
		var is_plant := texture.resource_path.contains("/foliage/")
		assert(material.get_shader_parameter("foliage_tone") == is_plant)
		if is_plant:
			plants += 1
			assert(is_equal_approx(float(material.get_shader_parameter("leaf_transmission")), 0.10))
			# Six established far groves are outside the near shadow cascade;
			# preserve their explicit v75 OFF state, not an invented new shadow.
			var expected_shadow := GeometryInstance3D.SHADOW_CASTING_SETTING_OFF if texture == scene.DISTANT_GROVES else GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
			assert(node.cast_shadow == expected_shadow)
			if not source_images.has(texture.resource_path):
				var pixels := Image.new()
				assert(pixels.load_png_from_buffer(FileAccess.get_file_as_bytes(texture.resource_path)) == OK)
				source_images[texture.resource_path] = pixels
			# Decode each PNG once, but measure every actual material's own crop,
			# tint and contrast. Different atlas cells are not interchangeable.
			var counts := _sample_source(source_images[texture.resource_path], material)
			zeroed_channels += counts.x
			measured_channels += counts.y
			print("MEADOW_FOLIAGE_SOURCE: %s; %s; uv_region %s; tint %s; contrast %.6f; %d/%d sampled channels clipped by old contrast" % [
				node.name, texture.resource_path, material.get_shader_parameter("uv_region"),
				material.get_shader_parameter("tint"), float(material.get_shader_parameter("art_contrast")), counts.x, counts.y])
		else:
			nonplants += 1
			assert(is_zero_approx(float(material.get_shader_parameter("leaf_transmission"))))
	assert(plants >= 25 and nonplants >= 6)
	# Counts describe the source sample population, not a required amount of
	# damage. In particular, the old linearized 84126/254007 estimate is invalid.
	# Curve properties, independently covered by the actual material GPU probe.
	for contrast: float in [1.06, 1.07, 1.12, 1.26]:
		var last := 0.0
		for i in range(1, 10001):
			var value := i / 10000.0
			var graded := value / (contrast + (1.0 - contrast) * value / 0.18) if value < 0.18 else (value - 0.18) * contrast + 0.18
			assert(graded > last and graded > 0.0)
			if value >= 0.18:
				assert(is_equal_approx(graded, (value - 0.18) * contrast + 0.18))
			last = graded
	var protection: Dictionary = preload("res://tools/shore_regression.gd").verify(scene)
	print("MEADOW_FOLIAGE_TONE_AUDIT: PASS; %d plant / %d nonplant materials; %d/%d alpha-visible base-source sampled channels clipped by old contrast (GLES3 sRGB-encoded RGB, per-material UV/tint/contrast, stride %d; descriptive, not screen clipping); %d profiled trees with all three canopy flags enabled, all other shared cutouts off; unchanged leaf transmission; 8 exact v76 meshes/shadow modes; MiddleMeadowBrush geometry is checked separately by MEADOW_MIDDLE_MEADOW_MASS_AUDIT; 40,000 positive monotonic tone samples, exact high shoulder; %d protected playfield probes" % [plants, nonplants, zeroed_channels, measured_channels, SOURCE_STRIDE, backlit_trees, protection.safe_probes])
	scene.queue_free()
	await process_frame
	quit()

func _verify_backlight_scope(scene: Node3D) -> int:
	var profiles: Dictionary = scene.CANOPY_PROFILES.PROFILES
	assert(profiles.size() == 5)
	var enabled := {}
	for node: MeshInstance3D in scene.find_children("*", "MeshInstance3D", true, false):
		if node.mesh == null:
			continue
		for surface in range(node.mesh.get_surface_count()):
			var material := node.get_active_material(surface) as ShaderMaterial
			if material == null or material.shader == null or not CUTOUT_SHADERS.has(material.shader.resource_path):
				continue
			var expected: bool = node.get_parent() == scene and profiles.has(str(node.name))
			var backlight: Variant = material.get_shader_parameter("canopy_backlight")
			assert((backlight != null and bool(backlight)) == expected,
				"Only the five profiled trees may enable canopy_backlight: " + str(node.get_path()))
			var orientation: Variant = material.get_shader_parameter("canopy_leaf_orientation")
			assert((orientation != null and bool(orientation)) == expected,
				"Only the five profiled trees may enable canopy_leaf_orientation: " + str(node.get_path()))
			var pigment_recovery: Variant = material.get_shader_parameter("canopy_pigment_recovery")
			assert((pigment_recovery != null and bool(pigment_recovery)) == expected,
				"Only the five profiled trees may enable canopy_pigment_recovery: " + str(node.get_path()))
			if expected:
				enabled[str(node.name)] = true
	for label: String in profiles:
		assert(enabled.has(label), "Missing profiled canopy material: " + label)
	assert(enabled.size() == 5)
	return enabled.size()

func _sample_source(pixels: Image, material: ShaderMaterial) -> Vector2i:
	var region: Vector4 = material.get_shader_parameter("uv_region")
	var tint: Color = material.get_shader_parameter("tint")
	var contrast := _float_parameter(material, "art_contrast", 1.0)
	var exposure := _float_parameter(material, "art_exposure", 1.0)
	var threshold := _float_parameter(material, "alpha_threshold", 0.16)
	var visibility := _float_parameter(material, "creature_visibility", 1.0)
	var inset := _float_parameter(material, "edge_inset", 0.0)
	var bottom_fade := _float_parameter(material, "bottom_fade", 0.0)
	var remove_matte: bool = material.get_shader_parameter("remove_pale_matte") == true
	var size := Vector2(pixels.get_size())
	assert(region.z > 0.0 and region.w > 0.0)
	assert(region.x >= 0.0 and region.y >= 0.0 and region.x + region.z <= 1.000001 and region.y + region.w <= 1.000001)
	# Integer texel centres strictly inside this material's source UV region.
	var start := Vector2i(ceili(region.x * size.x - 0.5), ceili(region.y * size.y - 0.5))
	var end := Vector2i(ceili((region.x + region.z) * size.x - 0.5), ceili((region.y + region.w) * size.y - 0.5))
	var counts := Vector2i.ZERO
	for y in range(maxi(start.y, 0), mini(end.y, pixels.get_height()), SOURCE_STRIDE):
		for x in range(maxi(start.x, 0), mini(end.x, pixels.get_width()), SOURCE_STRIDE):
			# Compatibility custom shaders consume encoded RGB for these inputs.
			# Neither PNG samples nor the source_color tint should be linearized.
			var pixel := pixels.get_pixel(x, y)
			var pigment := Vector3(maxf(pixel.r * tint.r, 0.0), maxf(pixel.g * tint.g, 0.0), maxf(pixel.b * tint.b, 0.0))
			var opacity := pixel.a * tint.a * visibility
			if opacity < threshold:
				continue
			if inset > 0.0:
				opacity = minf(opacity, minf(minf(_source_alpha(pixels, Vector2(x + inset, y)), _source_alpha(pixels, Vector2(x - inset, y))),
					minf(_source_alpha(pixels, Vector2(x, y + inset)), _source_alpha(pixels, Vector2(x, y - inset)))))
			if remove_matte:
				var graded := Vector3.ZERO
				for channel in range(3):
					var value: float = pigment[channel]
					graded[channel] = (value / (contrast + (1.0 - contrast) * value / 0.18) if value < 0.18 else (value - 0.18) * contrast + 0.18) * exposure
				var darkest := minf(graded.x, minf(graded.y, graded.z))
				var saturation := maxf(graded.x, maxf(graded.y, graded.z)) - darkest
				opacity *= 1.0 - smoothstep(0.38, 0.75, darkest) * (1.0 - smoothstep(0.06, 0.23, saturation))
			if bottom_fade > 0.0:
				var local_v := ((y + 0.5) / size.y - region.y) / region.w
				opacity *= smoothstep(0.0, bottom_fade, 1.0 - local_v)
			if opacity < threshold:
				continue
			for value: float in [pigment.x, pigment.y, pigment.z]:
				counts.y += 1
				counts.x += int(value > 0.0 and (value - 0.18) * contrast + 0.18 <= 0.0)
	return counts

func _float_parameter(material: ShaderMaterial, parameter: StringName, fallback: float) -> float:
	# Supply the shader default explicitly when an unset headless query is null.
	var value: Variant = material.get_shader_parameter(parameter)
	return fallback if value == null else float(value)

func _source_alpha(pixels: Image, at: Vector2) -> float:
	# Base-level bilinear alpha, clamped like the shader's repeat_disable sampler.
	# This is source visibility only: no camera occlusion, mip or GPU light claim.
	var origin := Vector2i(floori(at.x), floori(at.y))
	var weight := at - Vector2(origin)
	var x0 := clampi(origin.x, 0, pixels.get_width() - 1)
	var x1 := clampi(origin.x + 1, 0, pixels.get_width() - 1)
	var y0 := clampi(origin.y, 0, pixels.get_height() - 1)
	var y1 := clampi(origin.y + 1, 0, pixels.get_height() - 1)
	return lerpf(lerpf(pixels.get_pixel(x0, y0).a, pixels.get_pixel(x1, y0).a, weight.x),
		lerpf(pixels.get_pixel(x0, y1).a, pixels.get_pixel(x1, y1).a, weight.x), weight.y)
