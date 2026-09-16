extends SceneTree
## Read-only alpha, separation and bounds. Does not prove art quality or edit PNGs.

func _initialize() -> void:
	var paths := OS.get_cmdline_user_args()
	if paths.is_empty():
		push_error("Pass village atlas PNG paths after --")
		quit(1)
		return
	var failed := false
	for path in paths:
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Cannot read: " + path)
			failed = true
			continue
		var clear := 0
		var red := 0
		var row_hits := PackedInt32Array()
		row_hits.resize(source.get_height())
		for y in range(source.get_height()):
			for x in range(source.get_width()):
				var p := source.get_pixel(x, y)
				if p.a < 0.01:
					clear += 1
				if p.a > 0.22:
					row_hits[y] += 1
					if p.r > 0.85 and p.g < 0.20:
						red += 1
		var longest_start := -1
		var longest_length := 0
		var start := -1
		for y in range(int(source.get_height() * 0.32), int(source.get_height() * 0.67)):
			if row_hits[y] == 0:
				if start < 0:
					start = y
				if y - start + 1 > longest_length:
					longest_start = start
					longest_length = y - start + 1
			else:
				start = -1
		var split := longest_start + longest_length / 2
		var regions := []
		if longest_length >= 3:
			regions.append(_bounds(source, Rect2i(0, 0, source.get_width(), split)))
			regions.append(_bounds(source, Rect2i(0, split, source.get_width() / 2, source.get_height() - split)))
			regions.append(_bounds(source, Rect2i(source.get_width() / 2, split, source.get_width() - source.get_width() / 2, source.get_height() - split)))
		var percent := 100.0 * clear / (source.get_width() * source.get_height())
		var accepted := percent > 25.0 and percent < 98.0 and red == 0 and regions.size() == 3
		for region: Dictionary in regions:
			accepted = accepted and region.visible_pixels > 1000
		failed = failed or not accepted
		print("VILLAGE_ATLAS_AUDIT ", JSON.stringify({"path": path, "size": str(source.get_size()),
			"transparent_pct": percent, "red_matte_pixels": red, "gutter_start": longest_start,
			"gutter_rows": longest_length, "split_y": split, "regions": regions, "accepted_alpha": accepted}))
	quit(1 if failed else 0)

func _bounds(source: Image, region: Rect2i) -> Dictionary:
	var low := Vector2i(source.get_width(), source.get_height())
	var high := Vector2i(-1, -1)
	var count := 0
	for y in range(region.position.y, region.end.y):
		for x in range(region.position.x, region.end.x):
			if source.get_pixel(x, y).a > 0.22:
				low.x = mini(low.x, x)
				low.y = mini(low.y, y)
				high.x = maxi(high.x, x)
				high.y = maxi(high.y, y)
				count += 1
	return {"bounds_min": str(low), "bounds_max": str(high), "visible_pixels": count}
