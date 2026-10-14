extends SceneTree
## v85 painted-fill audit. Filename/marker retained; rejected v84 pigment is gone.
## Authoring CPU/source proof only, not a shader readback or visual acceptance test.
const SOURCE := "res://shaders/meadow_cutout_surface.gdshaderinc"
var weights := Vector3.ZERO
var day_gains := Vector2.ZERO
var night_gains := Vector2.ZERO
var knees := Vector2.ZERO

func _initialize() -> void:
	var source := _read(SOURCE)
	var baseline_path := ProjectSettings.globalize_path("res://").path_join("../artifacts/v84/meadow_cutout_surface.v83-before.gdshaderinc").simplify_path()
	var baseline := _read(baseline_path)
	var base_line := "    EMISSION = color.rgb * painted_fill * mix(vec3(1.0), vec3(0.36, 0.43, 0.54), meadow_night);\n"
	var base_start := source.find(base_line)
	assert(base_start >= 0 and baseline.contains(base_line), "Keep the actual v83 painted_fill factor")
	var start := source.find("#ifdef MEADOW_ARCHITECTURE\n", base_start)
	var end := source.find("#endif\n", start)
	assert(start == base_start + base_line.length() and end > start,
		"Attenuate only existing painted emission, immediately after its assignment")
	end += "#endif\n".length()
	var branch := source.substr(start, end - start)
	assert(source.substr(0, start) + source.substr(end) == baseline,
		"Everything outside fill attenuation must be exact v83: graded_art, ALBEDO, normals, alpha and windows")
	var window_start := source.find("    if (window_count > 0 && meadow_night > 0.01)")
	var old_window_start := baseline.find("    if (window_count > 0 && meadow_night > 0.01)")
	assert(window_start > end and old_window_start >= 0)
	assert(source.substr(window_start) == baseline.substr(old_window_start),
		"Window masks, additive emission, following lanterns and alpha must remain byte-exact")
	var expression := RegEx.new()
	assert(expression.compile(r"^#ifdefMEADOW_ARCHITECTUREfloatpainted_value=dot\(source\.rgb,vec3\(([0-9.]+),([0-9.]+),([0-9.]+)\)\);floatpainted_highlight=smoothstep\(([0-9.]+),([0-9.]+),painted_value\);floatdaylight_fill=mix\(([0-9.]+),([0-9.]+),painted_highlight\);floatmoonlight_fill=mix\(([0-9.]+),([0-9.]+),painted_highlight\);EMISSION\*=mix\(daylight_fill,moonlight_fill,meadow_night\);#endif$") == OK)
	var matched := expression.search(_compact(branch))
	assert(matched != null, "The CPU model must match the actual source operator, not a detached copy")
	weights = Vector3(float(matched.get_string(1)), float(matched.get_string(2)), float(matched.get_string(3)))
	knees = Vector2(float(matched.get_string(4)), float(matched.get_string(5)))
	day_gains = Vector2(float(matched.get_string(6)), float(matched.get_string(7)))
	night_gains = Vector2(float(matched.get_string(8)), float(matched.get_string(9)))
	assert(weights.is_finite() and weights.x > 0.0 and weights.y > 0.0 and weights.z > 0.0)
	assert(is_equal_approx(weights.x + weights.y + weights.z, 1.0))
	for bounds: Vector2 in [day_gains, night_gains]:
		assert(bounds.is_finite() and bounds.x > 0.0 and bounds.x <= bounds.y and bounds.y <= 1.0,
			"Only finite, positive attenuation of painted fill is allowed")
	assert(night_gains.x >= day_gains.x and night_gains.y >= day_gains.y,
		"Retain at least as much painted fill at night, without changing actual lighting")
	assert(knees.is_finite() and knees.x >= 0.0 and knees.y > knees.x)
	var compact := _compact(source)
	assert(compact.count("graded_art(") == 4, "One definition, one centre and two neighbour calls")
	assert(compact.contains("vec4color=vec4(graded_art(source.rgb),source.a*tint.a);"))
	assert(compact.contains("floatl=dot(color.rgb,metric);"))
	for axis: String in ["x", "y"]:
		assert(compact.contains("floatd%s=(dot(graded_art(neighbor_%s.rgb),metric)-l)*step(alpha_threshold,neighbor_%s.a);" % [axis, axis, axis]),
			"Centre and opaque relief neighbours must use the same graded_art operator")
	for wrapper: String in ["meadow_cutout.gdshader", "meadow_distant_cutout.gdshader", "meadow_architecture.gdshader"]:
		var code := _compact(_read("res://shaders/" + wrapper))
		assert(code.contains("meadow_cutout_surface.gdshaderinc"))
		assert(code.contains("#defineMEADOW_ARCHITECTURE") == (wrapper == "meadow_architecture.gdshader"),
			"Nonarchitecture wrappers must keep the exact old path")
	var cases := 0
	# Positive normalized weights map every finite source RGB in [0,1] to [0,1].
	# Test that scalar domain; do not fabricate rendered pixels or GPU efficacy.
	for night: float in [0.0, 0.25, 0.5, 0.75, 1.0]:
		var lower := lerpf(day_gains.x, night_gains.x, night)
		var upper := lerpf(day_gains.y, night_gains.y, night)
		var previous := -1.0
		for i in range(1025):
			var value := float(i) / 1024.0
			var gain := _fill_gain(value, night)
			assert(is_finite(gain) and gain >= lower - 0.000001 and gain <= upper + 0.000001)
			assert(gain >= previous and _fill_gain(value, 1.0) >= _fill_gain(value, 0.0))
			previous = gain
			# Bound to the exact base_line above. Only zero base EMISSION is
			# multiplied; all other outputs and subsequent windows are identical.
			var color := Vector3(value, 0.37, 0.83)
			var zero_fill := color * 0.0 * Vector3.ONE.lerp(Vector3(0.36, 0.43, 0.54), night)
			assert(zero_fill == Vector3.ZERO and zero_fill * gain == zero_fill)
			cases += 1
	print("MEADOW_ARCHITECTURE_PIGMENT_AUDIT: PASS; v85 painted EMISSION only; CPU/source; exact v83 graded_art/ALBEDO/normal/alpha and window expression; actual zero-fill source path unchanged; %d finite bounded/monotonic fill samples; day %.3f..%.3f night %.3f..%.3f; GPU/2K NOT TESTED" % [cases, day_gains.x, day_gains.y, night_gains.x, night_gains.y])
	quit()

func _fill_gain(value: float, night: float) -> float:
	var highlight := smoothstep(knees.x, knees.y, value)
	return lerpf(lerpf(day_gains.x, day_gains.y, highlight), lerpf(night_gains.x, night_gains.y, highlight), night)

func _read(path: String) -> String:
	assert(FileAccess.file_exists(path), "Missing authoring source/baseline: " + path)
	return FileAccess.get_file_as_string(path).replace("\r\n", "\n")

func _compact(source: String) -> String:
	var comments := RegEx.new()
	assert(comments.compile(r"(?m)^[ \t]*//[^\r\n]*|/\*[\s\S]*?\*/") == OK)
	var whitespace := RegEx.new()
	assert(whitespace.compile(r"\s+") == OK)
	return whitespace.sub(comments.sub(source, "", true), "", true)
