extends SceneTree

# Read-only audit: samples source alpha, never rewrites image pixels.
func _init() -> void:
	for path in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Could not load " + path)
			continue
		var empty := 0
		var partial := 0
		var total := 0
		var bounds := Rect2i(source.get_width(), source.get_height(), 0, 0)
		var minimum := Vector2i(source.get_width(), source.get_height())
		var maximum := Vector2i.ZERO
		for y in range(0, source.get_height(), 3):
			for x in range(0, source.get_width(), 3):
				var alpha := source.get_pixel(x, y).a
				total += 1
				if alpha < 0.01:
					empty += 1
				elif alpha < 0.99:
					partial += 1
				if alpha > 0.16:
					minimum = minimum.min(Vector2i(x, y))
					maximum = maximum.max(Vector2i(x, y))
		bounds = Rect2i(minimum, maximum - minimum + Vector2i.ONE)
		print(JSON.stringify({"path": path, "size": source.get_size(), "transparent_pct": 100.0 * empty / total, "partial_pct": 100.0 * partial / total, "alpha_bounds": bounds}))
	quit()
