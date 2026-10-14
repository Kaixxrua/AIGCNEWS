extends SceneTree
## Full-resolution read-only silhouette measurements for a distant PNG landmark.
## Alpha is data, not a checkerboard appearance. Never writes image pixels.

func _init() -> void:
	var failed := false
	for path in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		if source == null or source.is_empty():
			push_error("Cannot load landmark: " + path)
			failed = true
			continue
		var w := source.get_width()
		var h := source.get_height()
		var low := Vector2i(w, h)
		var high := Vector2i.ZERO
		var clear := 0
		var visible := 0
		var border := 0
		for y in range(h):
			for x in range(w):
				var alpha := source.get_pixel(x, y).a
				if alpha < 0.01:
					clear += 1
				if alpha <= 0.22:
					continue
				visible += 1
				low = low.min(Vector2i(x, y))
				high = high.max(Vector2i(x, y))
				if x == 0 or x == w - 1 or y == 0 or y == h - 1:
					border += 1
		var top_x := PackedInt32Array()
		for y in range(low.y, mini(low.y + 4, h)):
			for x in range(w):
				if source.get_pixel(x, y).a > 0.22:
					top_x.append(x)
		top_x.sort()
		var peak := Vector2.ZERO if top_x.is_empty() else Vector2(float(top_x[top_x.size() / 2]) / w, float(low.y) / h)
		print("LANDMARK_ALPHA ", JSON.stringify({"path": path, "size": [w, h],
			"transparent_pct_full": 100.0 * clear / (w * h), "visible_pixels": visible,
			"bounds": [low.x, low.y, high.x - low.x + 1, high.y - low.y + 1],
			"visible_border_pixels": border, "peak_uv": [peak.x, peak.y]}))
		if clear == 0 or visible == 0:
			failed = true
	quit(1 if failed else 0)
