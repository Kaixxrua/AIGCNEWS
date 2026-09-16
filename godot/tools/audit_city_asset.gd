extends SceneTree
## Read-only source/alpha measurements. Passing alpha is not an art-fidelity score.

func _initialize() -> void:
	var paths := OS.get_cmdline_user_args()
	if paths.is_empty():
		push_error("Pass one or more city PNG paths after --")
		quit(1)
		return
	var failed := false
	for path in paths:
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Cannot read city source: " + path)
			failed = true
			continue
		var clear := 0
		var visible := 0
		var red := 0
		var low := Vector2i(source.get_width(), source.get_height())
		var high := Vector2i(-1, -1)
		var peak_x := []
		for y in range(source.get_height()):
			for x in range(source.get_width()):
				var p := source.get_pixel(x, y)
				if p.a < 0.01:
					clear += 1
				if p.a > 0.22:
					visible += 1
					if p.r > 0.85 and p.g < 0.20:
						red += 1
				if p.a > 0.60:
					low.x = mini(low.x, x)
					low.y = mini(low.y, y)
					high.x = maxi(high.x, x)
					high.y = maxi(high.y, y)
					if y == low.y:
						peak_x.append(x)
		var percent := 100.0 * clear / (source.get_width() * source.get_height())
		var accepted := percent > 25.0 and percent < 98.0 and visible > 20000 and red == 0
		failed = failed or not accepted
		var peak := Vector2.ZERO
		if not peak_x.is_empty():
			for x in peak_x:
				peak.x += x
			peak.x /= peak_x.size() * float(source.get_width() - 1)
			peak.y = float(low.y) / (source.get_height() - 1)
		var feet := []
		if high.x > low.x:
			for t in [0.06, 0.18, 0.35, 0.50, 0.65, 0.82, 0.94]:
				var x := roundi(lerpf(low.x, high.x, t))
				var foot := -1
				for y in range(source.get_height()):
					if source.get_pixel(x, y).a > 0.60:
						foot = y
				feet.append({"u": float(x) / (source.get_width() - 1), "v": float(foot) / (source.get_height() - 1)})
		print("CITY_SOURCE_AUDIT ", JSON.stringify({"path": path, "size": str(source.get_size()),
			"transparent_pct": percent, "visible_pixels": visible, "red_matte_pixels": red,
			"bounds_min": str(low), "bounds_max": str(high), "peak_uv": str(peak),
			"column_feet": feet, "accepted_alpha": accepted}))
	quit(1 if failed else 0)
