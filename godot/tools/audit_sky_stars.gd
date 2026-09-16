extends SceneTree
## Narrow CPU/source contracts only. No shader execution or visible-star count.

const MAIN = preload("res://scenes/main.tscn")
const SKY_PATH := "res://shaders/meadow_sky.gdshader"
# Normalized v81 source: comments/whitespace and the old star insertion removed.
# v84 strips only the exact extra star attenuation matched below; this SHA is unchanged.
const PROTECTED_SKY_SHA := "629591fe485334965ed271f30fcc8f3aa0e5ce12c2fa6ae32ff3d663dbdec8ce"
# Frozen v83 clear-sky code, normalized in the same way. Provenance:
# artifacts/v84/sky-v83-before-cloud-occlusion.gdshader (file SHA CEB850CB...).
const V83_STAR_HELPER_SHA := "85bffe144c5d96a92242e9af4858d4b307dea33f976601d66023d44ac65cb45c"
const V83_STAR_INSERTION_SHA := "ae505f59c8f7efbba07a6c253b435d97b141f705c6e2b908ed1634996338ba8f"
const PROTECTED_SOURCES := {
	"res://scripts/meadow_weather.gd": "273b5c384aa3250f480ddf1f984c03d169a5f93c839ff22a6b1bb2feafe7f4ab",
	"res://shaders/meadow_water.gdshader": "ce72c8d1d1faef447f92c076ac86486243a1032d1ad505becc3dbe7237cd2a08",
	"res://shaders/meadow_focus.gdshader": "4b1ce9d576d645e14f90df6ed85d11a371929c2b0302b3092be9825a56bb241d",
}

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var fade := _verify_source()
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	var weather = scene.get_node("LivingWeather")
	weather.set_process(false)
	weather.set_motion(false)
	var frozen_clock: float = weather.animation_clock
	var camera_pose: Transform3D = scene.camera.global_transform
	var sky_material: ShaderMaterial = weather.environment.sky.sky_material
	assert(sky_material.shader.resource_path == SKY_PATH)
	assert(weather.environment.ambient_light_source == Environment.AMBIENT_SOURCE_COLOR,
		"Extra stars must not become a new diffuse sky-light source")
	_verify_view(scene.camera, fade)
	assert(weather.night_blend == 0.0 and _night_gain(weather.night_blend, fade) == 0.0)
	weather.toggle_time()
	weather.advance_weather(1.6)
	var partial: float = weather.night_blend
	var partial_gain := _night_gain(partial, fade)
	assert(partial_gain > 0.0 and partial_gain < 1.0)
	weather.toggle_time()
	assert(weather.night_blend == partial and _night_gain(weather.night_blend, fade) == partial_gain,
		"Reversal must not jump the star fade while motion is paused")
	weather.advance_weather(0.8)
	assert(weather.night_blend < partial and _night_gain(weather.night_blend, fade) < partial_gain)
	weather.advance_weather(2.4)
	assert(weather.night_blend == 0.0 and _night_gain(weather.night_blend, fade) == 0.0)
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 1.0 and _night_gain(weather.night_blend, fade) == 1.0)
	assert(weather.animation_clock == frozen_clock, "Paused shared clock must also freeze star twinkle")
	weather.set_motion(true)
	weather.advance_weather(0.1)
	assert(is_equal_approx(weather.animation_clock, frozen_clock + 0.1))
	weather.set_motion(false)
	var resumed_clock: float = weather.animation_clock
	weather.advance_weather(0.5)
	assert(weather.animation_clock == resumed_clock)
	weather.toggle_time()
	weather.advance_weather(3.2)
	assert(weather.night_blend == 0.0 and _night_gain(weather.night_blend, fade) == 0.0)
	assert(scene.camera.global_transform == camera_pose)
	print("MEADOW_SKY_STARS_AUDIT: PASS; CPU/source only; v81 non-star sky/weather/water/focus preserved; v83 clear-star source exact; cloud-opacity star-only extinction; stationary star coordinates; bounded cell support; horizon/night fade; paused/reversed/restored time; GPU/2K visibility NOT TESTED")
	scene.queue_free()
	await process_frame
	quit()

func _verify_source() -> Vector4:
	for path: String in PROTECTED_SOURCES:
		var text := FileAccess.get_file_as_string(path).replace("\r\n", "\n")
		assert(text.sha256_text() == PROTECTED_SOURCES[path], "Out-of-scope source changed: " + path)
	var source := FileAccess.get_file_as_string(SKY_PATH)
	var comments := RegEx.new()
	assert(comments.compile(r"//[^\r\n]*|/\*[\s\S]*?\*/") == OK)
	var whitespace := RegEx.new()
	assert(whitespace.compile(r"\s+") == OK)
	source = whitespace.sub(comments.sub(source, "", true), "", true)
	var helper := _match(source, r"floatnight_stars\(vec3ray\)\{([^{}]+)\}")
	var stars := _match(source, r"floatstars=night_stars\(EYEDIR\)\*smoothstep\(([0-9.]+),([0-9.]+),height\);stars\*=smoothstep\(([0-9.]+),([0-9.]+),meadow_night\);night\+=vec3\(0\.53,0\.65,0\.88\)\*\(stars\+moon\*0\.9\+halo\);")
	# Match the complete adjacent cloud query and mix, removing only capture 1.
	# This does NOT exempt the cloud function, opacity, guard or composition from the old SHA.
	var occlusion := _match(source, r"vec4cloud=cumulus\(EYEDIR,normalize\(cloud_light_direction\)\);(floatstar_occlusion=smoothstep\(([0-9.]+),([0-9.]+),cloud\.a\);background-=vec3\(0\.53,0\.65,0\.88\)\*stars\*meadow_night\*star_occlusion;)background=mix\(background,cloud\.rgb,cloud\.a\);")
	var protected := source.replace(helper.get_string(0), "").replace(stars.get_string(0), "<STARS>")
	protected = protected.replace(occlusion.get_string(1), "")
	assert(protected.sha256_text() == PROTECTED_SKY_SHA,
		"Keep v81 day/night background, moon/halo, cloud math/query/mix and final output exact")
	assert(helper.get_string(0).sha256_text() == V83_STAR_HELPER_SHA,
		"Preserve v83 clear-star coordinates, occupancy, size, strength, AA and twinkle exactly")
	assert(stars.get_string(0).sha256_text() == V83_STAR_INSERTION_SHA,
		"Preserve v83 clear-star colour and horizon/night fades exactly")
	_verify_cloud_occlusion(Vector2(float(occlusion.get_string(2)), float(occlusion.get_string(3))))
	var body := helper.get_string(1)
	var twinkle := _match(body, r"floattwinkle=1\.0\+main_star\*([0-9.]+)\*sin\(meadow_clock\*mix\(([0-9.]+),([0-9.]+),size_seed\)\+size_seed\*[0-9.]+\);returnoccupied\*point\*strength\*twinkle;")
	var stationary := body.replace(twinkle.get_string(0), "")
	for token: String in ["meadow_clock", "meadow_night", "TIME", "SCREEN_UV", "cumulus(", "cloud_", "sun_direction", "moon_direction"]:
		assert(not stationary.contains(token), "Star positions/occupancy must not depend on time, fade or moving clouds: " + token)
	assert(not source.contains("TIME") and body.count("meadow_clock") == 1)
	for token: String in ["for(", "while(", "texture("]:
		assert(not body.contains(token), "Keep the star helper a bounded, texture-free single-cell lookup")
	var amplitude := float(twinkle.get_string(1))
	assert(amplitude >= 0.0 and amplitude < 1.0, "Twinkle must never invert or extinguish a star")
	assert(float(twinkle.get_string(2)) > 0.0 and float(twinkle.get_string(3)) > 0.0)
	var angular := _match(body, r"vec2horizontal=dot\(ray\.xz,ray\.xz\)<([0-9.]+)\?vec2\(0\.0,-([0-9.]+)\):ray\.xz;vec2star_uv=vec2\(atan\(horizontal\.x,-horizontal\.y\),asin\(clamp\(ray\.y,-1\.0,1\.0\)\)\)\*([0-9.]+);vec2cell=floor\(star_uv\);")
	assert(float(angular.get_string(1)) > 0.0 and float(angular.get_string(2)) > 0.0 and float(angular.get_string(3)) > 0.0)
	var inset := _match(body, r"vec2centre=vec2\(hash3\(vec3\(cell,[0-9.]+\)\),hash3\(vec3\(cell,[0-9.]+\)\)\)\*([0-9.]+)\+([0-9.]+);")
	var clearance := minf(float(inset.get_string(2)), 1.0 - float(inset.get_string(1)) - float(inset.get_string(2)))
	var radius := _match(body, r"floatradius=mix\(([0-9.]+),([0-9.]+),size_seed\)\+main_star\*([0-9.]+);")
	assert(float(radius.get_string(1)) > 0.0 and float(radius.get_string(2)) >= float(radius.get_string(1)))
	assert(float(radius.get_string(3)) >= 0.0)
	var max_radius := float(radius.get_string(2)) + float(radius.get_string(3))
	var filter := _match(body, r"floathalf_pixel=max\(length\(fwidth\(star_uv\)\)\*0\.5,([0-9.]+)\);floatfiltered_area=radius\*radius\+half_pixel\*half_pixel;floatfiltered_radius=min\(sqrt\(filtered_area\),([0-9.]+)\);floatpoint=1\.0-smoothstep\(0\.0,filtered_radius,length\(fract\(star_uv\)-centre\)\);point\*=radius\*radius/filtered_area;")
	var support_cap := float(filter.get_string(2))
	assert(float(filter.get_string(1)) > 0.0 and body.count("fwidth(") == 1)
	assert(max_radius <= support_cap and support_cap < clearance,
		"Even filtered stars must end inside their own cell; no edge clipping or neighbour scan")
	var fade := Vector4(float(stars.get_string(1)), float(stars.get_string(2)), float(stars.get_string(3)), float(stars.get_string(4)))
	assert(fade.x >= 0.0 and fade.y > fade.x)
	assert(fade.z > 0.0 and fade.w > fade.z and fade.w <= 1.0)
	assert(smoothstep(fade.x, fade.y, 0.0) == 0.0)
	print("SKY_STARS_SOURCE: radius <= %.3f; filtered support %.3f < inset %.3f; twinkle 1 +/- %.3f; no visible-count claim" % [max_radius, support_cap, clearance, amplitude])
	return fade

func _verify_cloud_occlusion(fade: Vector2) -> void:
	assert(fade == Vector2(0.01, 0.12), "Reviewed star-only cloud fringe thresholds changed")
	var previous_visibility := 1.0
	var sky_and_moon := Vector3(0.12, 0.22, 0.35)
	var cloud_colour := Vector3(0.23, 0.29, 0.41)
	var star_colour := Vector3(0.53, 0.65, 0.88)
	for i in range(101):
		var opacity := float(i) / 100.0
		var removed := smoothstep(fade.x, fade.y, opacity)
		var visibility := (1.0 - opacity) * (1.0 - removed)
		assert(visibility >= 0.0 and visibility <= 1.0 - opacity + 0.000001)
		assert(visibility <= previous_visibility + 0.000001, "Cloud extinction must be monotonic")
		if opacity <= fade.x:
			assert(is_equal_approx(visibility, 1.0 - opacity), "Clear sky keeps v83 star visibility")
		if opacity >= fade.y:
			assert(visibility == 0.0, "Visible cloud fringes must extinguish point stars")
		previous_visibility = visibility
		# Source-matched compositing algebra, not GPU pixels or an artistic brightness gate.
		for night_weight: float in [0.0, 0.5, 1.0]:
			for strength: float in [0.0, 0.75, 2.538]:
				var star := star_colour * strength * night_weight
				var old_composite := (sky_and_moon + star).lerp(cloud_colour, opacity)
				var new_composite := (sky_and_moon + star - star * removed).lerp(cloud_colour, opacity)
				var expected := sky_and_moon.lerp(cloud_colour, opacity) + star * visibility
				assert(new_composite.is_equal_approx(expected), "Only star contribution may change")
				if opacity <= fade.x or strength == 0.0 or night_weight == 0.0:
					assert(new_composite.is_equal_approx(old_composite), "Clear/day/non-star controls changed")
	print("SKY_STARS_CLOUD: CPU algebra only; original cloud query/mix; clear/day/non-star controls; bounded monotonic extinction; opacity >= 0.12 removes stars; GPU fringes NOT TESTED")

func _verify_view(camera: Camera3D, fade: Vector4) -> void:
	var size: Vector2 = camera.get_viewport().get_visible_rect().size
	assert(size.x > 0.0 and size.y > 0.0)
	var faded := 0
	var full := 0
	var below := 0
	var max_height := 0.0
	# Actual camera rays in the upper quarter; not a sky/geometry/cloud pixel mask.
	for y in range(32):
		for x in range(80):
			var screen := Vector2((x + 0.5) / 80.0, (y + 0.5) / 32.0 * 0.25) * size
			var height := camera.project_ray_normal(screen).y
			var gain := smoothstep(fade.x, fade.y, maxf(height, 0.0))
			max_height = maxf(max_height, height)
			faded += int(gain > 0.0 and gain < 1.0)
			full += int(gain == 1.0)
			below += int(height <= 0.0)
			if height <= 0.0:
				assert(gain == 0.0)
	assert(faded > 0 and full > 0 and below > 0,
		"The fade must reach the actual low sky, include a soft boundary and exclude below-horizon rays")
	print("SKY_STARS_DOMAIN: 2560 camera rays; horizon mask partial/full/below %d/%d/%d; top elevation %.3f degrees; no cloud/geometry/AA visibility claim" % [faded, full, below, rad_to_deg(asin(max_height))])

func _night_gain(blend: float, fade: Vector4) -> float:
	return blend * smoothstep(fade.z, fade.w, blend)

func _match(source: String, pattern: String) -> RegExMatch:
	var expression := RegEx.new()
	assert(expression.compile(pattern) == OK)
	var matches := expression.search_all(source)
	assert(matches.size() == 1, "Reviewed star-source contract changed: " + pattern)
	return matches[0]
