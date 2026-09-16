extends SceneTree
## v90: source contracts and cached mesh attributes only; no GPU lighting claims.
const SHADER_PATH := "res://shaders/meadow_leaves.gdshader"
const CACHE_PATH := "res://assets/baked/v77/brush.scn"
# Frozen artifacts/v86/meadow_leaves.v85-before.gdshader:
# file SHA256 8DCCFD135603027FD9BFB5974EAC59420E78BBF6BC451766EA4E54FC1FD3BA6B.
# Remove REVIEWED_OVERRIDE and revert ONLY REVIEWED_MIDDLE_TINT after normalization.
const V85_SHADER_NORMALIZED_SHA := "0397e5a3b58c59d7b55103102c66ed465ffd5b728202d1c5d6f053db696002ae"
const REVIEWED_OVERRIDE := "if(middle_scrub&&UV.x>=-900.0){BACKLIGHT=vec3(0.18);}"
const BASELINE_MIDDLE_TINT := "pigment*=mix(vec3(0.70,0.82,0.63),vec3(0.89,0.94,0.78),outer_leaf);"
const REVIEWED_MIDDLE_TINT := "pigment*=mix(vec3(0.86,0.94,0.78),vec3(0.93,0.97,0.85),outer_leaf);"
const MIDDLE_TINT_PREFIX := "if(middle_scrub){floatouter_leaf=smoothstep(0.10,0.90,COLOR.a);"
const WOOD_OVERRIDE := "if(UV.x<-1800.0){pigment=vec3(0.105,0.073,0.034)*COLOR.rgb;}"
const OLD_INNER_TINT := Vector3(0.70, 0.82, 0.63)
const OLD_OUTER_TINT := Vector3(0.89, 0.94, 0.78)
const NEW_INNER_TINT := Vector3(0.86, 0.94, 0.78)
const NEW_OUTER_TINT := Vector3(0.93, 0.97, 0.85)
const MAX_TINT_GAIN := 26.0 / 21.0 # .78/.63, the largest endpoint channel ratio.
const LEAF_UV_CUTOFF := -900.0
const TRANSMISSION := 0.18
const OLD_TRANSMISSION := 0.06
const ROOT_COUNT := 1204
const TRIANGLES_PER_ROOT := 80
const WOOD_TRIANGLES_PER_ROOT := 8
const PROTECTED_SOURCES := {
	"res://scripts/meadow_middle_brush.gd": "b2484c143ce30902a5f4b3ba2b9df117826c5b5e0915af49149e95130636a5f5",
	"res://scripts/meadow_branch_geometry.gd": "d2207d2b78d7697fe83870880ec484e29a4af730c2b265ce894b9b87c9c2b99f",
	"res://scripts/meadow_static_cache.gd": "346e9eda9ad56f0ca659e5843d5d22e6446da2b085f2c697cecfc17a185b82a7",
	"res://shaders/meadow_palette.gdshaderinc": "91b7013c8ec118e3f6578978d9718b3b334edd23b0a20a5bc4cb78a94a950d4a",
	"res://shaders/meadow_surface.gdshaderinc": "0005905cd6dfaee47c4bba8548e598cc3d1e1aec057440cb10288d461a0928d4",
}

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	_verify_source()
	_verify_response_coefficients()
	_verify_middle_tint()
	_verify_cached_triangle_tags()
	print("MEADOW_MIDDLE_BRUSH_MATERIAL_AUDIT: PASS; CPU/source only; exact v85 remainder after ONLY branch removal and reviewed tint reversion; bounded positive middle tint; protected palette/geometry sources; cached middle_scrub material; all 96320 indexed triangles keep wood/leaf tags without crossing -900; zero-wind leaf roots included; neutral 0.18 only for middle leaves; final twig pigment and other-plant path exact; no EMISSION; GPU efficacy/zero-light/visual acceptance NOT TESTED")
	quit()

func _normalize(source: String) -> String:
	var comments := RegEx.new()
	assert(comments.compile(r"//[^\r\n]*|/\*[\s\S]*?\*/") == OK)
	var whitespace := RegEx.new()
	assert(whitespace.compile(r"\s+") == OK)
	return whitespace.sub(comments.sub(source, "", true), "", true)

func _verify_source() -> void:
	for path: String in PROTECTED_SOURCES:
		assert(FileAccess.get_sha256(path).to_lower() == PROTECTED_SOURCES[path].to_lower(),
			"Material-only work changed protected geometry/cache selection/world pigment: " + path)
	var source := _normalize(FileAccess.get_file_as_string(SHADER_PATH))
	assert(source.count(REVIEWED_OVERRIDE) == 1, "Require the single, exact reviewed UV/flag override")
	assert(source.contains("BACKLIGHT=pigment*0.06;" + REVIEWED_OVERRIDE + "ROUGHNESS=mix(0.95,0.80,COLOR.a);"),
		"Override must follow the old BACKLIGHT assignment, without touching pigment or other outputs")
	assert(source.count(REVIEWED_MIDDLE_TINT) == 1 and source.count(BASELINE_MIDDLE_TINT) == 0,
		"Require exactly the reviewed v88 tint, not an additional or unchanged old mix")
	assert(source.count("if(middle_scrub){") == 1 and source.contains(
		MIDDLE_TINT_PREFIX + REVIEWED_MIDDLE_TINT + "}" + WOOD_OVERRIDE
		+ "ALBEDO=pigment*meadow_cloud_light(p,meadow_clock,meadow_night);"),
		"Tint must stay inside the original middle block; unchanged wood override must follow it before ALBEDO")
	assert(_tint_statement(OLD_INNER_TINT, OLD_OUTER_TINT) == BASELINE_MIDDLE_TINT)
	assert(_tint_statement(NEW_INNER_TINT, NEW_OUTER_TINT) == REVIEWED_MIDDLE_TINT,
		"CPU tint endpoints must match the exact shader change")
	var restored := source.replace(REVIEWED_OVERRIDE, "").replace(REVIEWED_MIDDLE_TINT, BASELINE_MIDDLE_TINT)
	assert(restored.sha256_text() == V85_SHADER_NORMALIZED_SHA,
		"Outside the exact BACKLIGHT branch and middle tint endpoints, preserve the entire v85 shader including vertex/wind, NORMAL, ALBEDO, other pigment paths, roughness, specular and AO")
	assert(not source.contains("EMISSION"), "This change supplies no emissive term")
	assert(source.count("BACKLIGHT=") == 2)
	var cpu_contract := "if(middle_scrub&&UV.x>=%.1f){BACKLIGHT=vec3(%.2f);}" % [LEAF_UV_CUTOFF, TRANSMISSION]
	assert(REVIEWED_OVERRIDE == cpu_contract,
		"CPU selector/coefficient must remain bound to the exact shader branch")
	print("MIDDLE_BRUSH_MATERIAL_SOURCE: exact v85 normalized baseline restored after removing ONLY reviewed BACKLIGHT branch and reverting ONLY reviewed middle tint; no new texture reads, time dependence, alpha or emission")

func _tint_statement(inner: Vector3, outer: Vector3) -> String:
	return "pigment*=mix(vec3(%.2f,%.2f,%.2f),vec3(%.2f,%.2f,%.2f),outer_leaf);" % [
		inner.x, inner.y, inner.z, outer.x, outer.y, outer.z]

func _post_middle_tint(pigment: Vector3, colour: Color, uv_x: float, middle_scrub: bool, revised: bool) -> Vector3:
	var result := pigment
	if middle_scrub:
		var outer_leaf := smoothstep(0.10, 0.90, colour.a)
		var inner := NEW_INNER_TINT if revised else OLD_INNER_TINT
		var outer := NEW_OUTER_TINT if revised else OLD_OUTER_TINT
		result *= inner.lerp(outer, outer_leaf)
	# Source guard binds this final overwrite and its ordering before ALBEDO.
	if uv_x < -1800.0:
		result = Vector3(0.105, 0.073, 0.034) * Vector3(colour.r, colour.g, colour.b)
	return result

func _verify_middle_tint() -> void:
	var pigments := [Vector3.ZERO, Vector3(0.0001, 0.01, 0.2), Vector3(0.30, 0.60, 0.05), Vector3.ONE, Vector3(1.2, 0.2, 2.0)]
	# Endpoint inequalities bound the full convex mix; sample smoothstep and all
	# wind weights too, including zero-wind attachments, .65 folds and 1.0 tips.
	for step in range(101):
		var wind := float(step) / 100.0
		var weight := smoothstep(0.10, 0.90, wind)
		var old_tint := OLD_INNER_TINT.lerp(OLD_OUTER_TINT, weight)
		var new_tint := NEW_INNER_TINT.lerp(NEW_OUTER_TINT, weight)
		for channel in range(3):
			assert(new_tint[channel] > old_tint[channel] and new_tint[channel] <= 1.0)
			assert(new_tint[channel] <= old_tint[channel] * MAX_TINT_GAIN + 0.000001,
				"Tint remains multiplicative reflectance: at most 26/21 of old per channel, not extra energy")
		var colour := Color(0.61, 0.72, 0.53, wind)
		for pigment: Vector3 in pigments:
			var old := _post_middle_tint(pigment, colour, 0.0, true, false)
			var current := _post_middle_tint(pigment, colour, 0.0, true, true)
			assert(_post_middle_tint(pigment, colour, 0.0, false, false) == pigment)
			assert(_post_middle_tint(pigment, colour, 0.0, false, true) == pigment,
				"Nonmiddle pigment path is identical")
			for channel in range(3):
				assert(current[channel] >= old[channel] and current[channel] <= pigment[channel] + 0.000001)
				assert(current[channel] <= old[channel] * MAX_TINT_GAIN + 0.000001)
			if pigment == Vector3.ZERO:
				assert(current == Vector3.ZERO, "Tint cannot lift black or create an additive term")
	print("MIDDLE_BRUSH_MATERIAL_TINT: positive channel change bounded by 26/21 of old; all tint factors <=1; black stays black; nonmiddle unchanged; CPU reflectance only, not GPU efficacy")

func _selected(middle_scrub: bool, uv_x: float) -> bool:
	return middle_scrub and uv_x >= LEAF_UV_CUTOFF

func _backlight(pigment: Vector3, middle_scrub: bool, uv_x: float) -> Vector3:
	return Vector3.ONE * TRANSMISSION if _selected(middle_scrub, uv_x) else pigment * OLD_TRANSMISSION

func _verify_response_coefficients() -> void:
	var pigments := [Vector3.ZERO, Vector3(0.0001, 0.01, 0.2), Vector3(0.30, 0.60, 0.05), Vector3.ONE, Vector3(1.2, 0.2, 2.0)]
	for uv_x: float in [-2000.0, -1800.0, -1000.0, -900.001, -900.0, -899.999, 0.0, 50.0]:
		for pigment: Vector3 in pigments:
			var old := pigment * OLD_TRANSMISSION
			assert(_backlight(pigment, false, uv_x) == old, "Other plants must keep old BACKLIGHT at every UV")
			var current := _backlight(pigment, true, uv_x)
			if uv_x < LEAF_UV_CUTOFF:
				assert(current == old, "Wood and reserved negative-UV paths must remain exact")
			else:
				assert(current == Vector3.ONE * TRANSMISSION, "Middle leaf coefficient must be neutral and bounded at 0.18")
	# These are coefficient identities, not proof that an unlit pixel stays black.
	assert(_selected(true, -900.0) and not _selected(true, -900.001))
	print("MIDDLE_BRUSH_MATERIAL_COEFFICIENTS: flag/UV boundaries; zero/dark/bright pigment inputs; old RGB wood/other-plant path; no GPU light-response claim")

func _verify_cached_triangle_tags() -> void:
	# Load only the existing packed brush; do not instantiate/build the full meadow.
	var packed := load(CACHE_PATH) as PackedScene
	assert(packed != null, "Current v77 brush cache is required")
	var container := packed.instantiate() as Node3D
	assert(container != null and container.get_meta("cache_version", "") == "meadow-77-1")
	assert(container.get_child_count() == 1)
	var brush := container.get_node("MiddleMeadowBrush") as MeshInstance3D
	assert(brush != null and brush.transform == Transform3D.IDENTITY)
	var material := brush.material_override as ShaderMaterial
	assert(material != null and material.shader != null and material.shader.resource_path == SHADER_PATH)
	assert(material.get_shader_parameter("middle_scrub") == true,
		"Cached mixed wood/leaf batch must actually opt into the reviewed material path")
	# Unset default uniforms may read null with a headless dummy renderer.
	assert(material.get_shader_parameter("foothill_scrub") != true)
	var roots: PackedVector3Array = brush.get_meta("roots")
	var root_faces: PackedInt32Array = brush.get_meta("root_faces")
	assert(roots.size() == ROOT_COUNT and root_faces.size() == ROOT_COUNT)
	for root_index in range(ROOT_COUNT):
		assert(root_faces[root_index] == root_index * TRIANGLES_PER_ROOT)

	var mesh := brush.mesh as ArrayMesh
	assert(mesh != null and mesh.get_surface_count() == 1)
	assert(mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES)
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices := PackedInt32Array()
	if arrays[Mesh.ARRAY_INDEX] != null:
		indices = arrays[Mesh.ARRAY_INDEX]
	assert(not indices.is_empty(), "Audit the actual indexed brush cache, not reconstructed sample leaves")
	assert(vertices.size() == colours.size() and vertices.size() == uv.size())
	assert(indices.size() == ROOT_COUNT * TRIANGLES_PER_ROOT * 3)
	var leaf_triangles := 0
	var wood_triangles := 0
	var leaf_zero_wind_corners := 0
	var leaf_uv_range := Vector2(INF, -INF)
	for triangle in range(ROOT_COUNT * TRIANGLES_PER_ROOT):
		# Independent frozen slot order: 8 wood + 72 leaflet triangles per root.
		# Never use UV classification itself as the expected wood/leaf label.
		var expected_leaf := triangle % TRIANGLES_PER_ROOT >= WOOD_TRIANGLES_PER_ROOT
		var uv_range := Vector2(INF, -INF)
		var zero_wind := 0
		var tip_wind := 0
		var folded_side := 0
		for corner in range(3):
			var index: int = indices[triangle * 3 + corner]
			assert(index >= 0 and index < vertices.size())
			var tag: Vector2 = uv[index]
			var colour: Color = colours[index]
			assert(tag.is_finite() and is_finite(colour.a))
			uv_range.x = minf(uv_range.x, tag.x)
			uv_range.y = maxf(uv_range.y, tag.x)
			assert(_selected(true, tag.x) == expected_leaf, "Leaf/twig selection disagrees with the frozen actual triangle slot")
			assert(not _selected(false, tag.x))
			if expected_leaf:
				var position: Vector3 = vertices[index]
				assert(tag.is_equal_approx(Vector2(position.x, position.z)), "Leaf UVs must retain emitted world-XZ tags")
				leaf_uv_range.x = minf(leaf_uv_range.x, tag.x)
				leaf_uv_range.y = maxf(leaf_uv_range.y, tag.x)
				if colour.a == 0.0:
					zero_wind += 1
					leaf_zero_wind_corners += 1
				elif colour.a == 1.0:
					tip_wind += 1
				else:
					assert(colour.a > 0.0 and colour.a < 1.0)
					folded_side += 1
			else:
				assert(tag == Vector2(-2000.0, 0.0) and colour.a == 0.0,
					"Twig UV sentinel and zero wind must remain distinct from leaf attachments")
				var twig_pigment := Vector3(0.105, 0.073, 0.034) * Vector3(colour.r, colour.g, colour.b)
				assert(_post_middle_tint(Vector3.ONE, colour, tag.x, true, false) == twig_pigment)
				assert(_post_middle_tint(Vector3.ONE, colour, tag.x, true, true) == twig_pigment,
					"Every actual rooted twig keeps its final pigment overwrite after the changed middle tint")
				assert(_backlight(twig_pigment, true, tag.x) == twig_pigment * OLD_TRANSMISSION,
					"Actual twig RGB-weighted BACKLIGHT remains old, not neutral or forced to zero")
		assert(uv_range.x >= LEAF_UV_CUTOFF or uv_range.y < LEAF_UV_CUTOFF,
			"No triangle may interpolate across the leaf/twig selector threshold")
		if expected_leaf:
			assert(zero_wind == 1 and tip_wind == 1 and folded_side == 1,
				"Each actual leaflet triangle includes its zero-wind attachment, folded side and tip")
			leaf_triangles += 1
		else:
			wood_triangles += 1
	assert(leaf_triangles == ROOT_COUNT * 72 and wood_triangles == ROOT_COUNT * 8)
	assert(leaf_zero_wind_corners == leaf_triangles,
		"COLOR.a=0 must NOT exclude leaf roots; only UV/flag separates them from twigs")
	print("MIDDLE_BRUSH_MATERIAL_TAGS: cached material true; %d leaf / %d wood triangles; %d selected zero-wind leaf corners; actual leaf UV.x %.3f..%.3f; no threshold-crossing triangles (convex interpolation); GPU shading NOT TESTED" %
		[leaf_triangles, wood_triangles, leaf_zero_wind_corners, leaf_uv_range.x, leaf_uv_range.y])
	container.free()
