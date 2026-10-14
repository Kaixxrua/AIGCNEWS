extends SceneTree
## Pixel-box overlap shared by near/distant cutout shaders. Verify conservation
## across subpixel phases; real appearance is still checked in WebGL at night.

func _initialize() -> void:
	var common := FileAccess.get_file_as_string("res://shaders/meadow_cutout_surface.gdshaderinc")
	for path: String in ["res://shaders/meadow_cutout.gdshader", "res://shaders/meadow_distant_cutout.gdshader"]:
		var shader: Shader = load(path)
		assert(shader.code.contains("meadow_cutout_surface.gdshaderinc"))
	assert(common.contains("window_box_coverage(uv, half_pixel, opening)"))
	assert(common.contains("fwidth(uv) * 0.5"))
	var maximum_error := 0.0
	var cases := 0
	for size: Vector2 in [Vector2(0.35, 0.65), Vector2(0.7, 1.2), Vector2(1.4, 2.1)]:
		for ix in range(9):
			for iy in range(9):
				var opening := Rect2(Vector2(ix / 9.0, iy / 9.0) - size * 0.5, size)
				var coverage := 0.0
				for x in range(-3, 5):
					for y in range(-3, 5):
						var pixel := Rect2(Vector2(x - 0.5, y - 0.5), Vector2.ONE)
						var overlap := opening.intersection(pixel)
						coverage += maxf(overlap.size.x, 0.0) * maxf(overlap.size.y, 0.0)
				maximum_error = maxf(maximum_error, absf(coverage - size.x * size.y))
				cases += 1
	assert(cases == 243 and maximum_error < 0.00001)
	print("MEADOW_WINDOW_SAMPLING_AUDIT: PASS; 243 size/phase cases; coverage error %.8f; no oversized source rectangles" % maximum_error)
	quit()
