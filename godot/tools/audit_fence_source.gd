extends SceneTree
## Full-resolution read-only alpha gate; reports root rows without altering PNGs.

func _initialize() -> void:
	if OS.get_cmdline_user_args().is_empty():
		push_error("Supply at least one fence PNG to audit")
		quit(1)
		return
	var failed := false
	for path in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Cannot load fence image: " + path)
			failed = true
			continue
		var clear := 0
		var red := 0
		var visible := 0
		for y in range(source.get_height()):
			for x in range(source.get_width()):
				var p := source.get_pixel(x, y)
				if p.a < 0.01:
					clear += 1
				if p.a > 0.22:
					visible += 1
					if p.r > 0.85 and p.g < 0.20:
						red += 1
		var percent := 100.0 * clear / (source.get_width() * source.get_height())
		var accepted := percent > 35.0 and visible > 20000 and red == 0
		failed = failed or not accepted
		var roots := []
		for u in [0.085, 0.386, 0.642, 0.923]:
			var x := roundi(u * (source.get_width() - 1))
			var top := source.get_height()
			var bottom := -1
			for y in range(source.get_height()):
				if source.get_pixel(x, y).a > 0.50:
					top = mini(top, y)
					bottom = maxi(bottom, y)
			roots.append({"u": u, "top": top, "bottom": bottom,
				"root_v": float(bottom) / (source.get_height() - 1)})
		print("FENCE_SOURCE_ALPHA ", JSON.stringify({"path": path, "size": str(source.get_size()),
			"transparent_pct": percent, "red_matte_pixels": red, "accepted_alpha": accepted, "column_bounds": roots}))
	quit(1 if failed else 0)
