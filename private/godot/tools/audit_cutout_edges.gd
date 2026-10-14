extends SceneTree
## Full-resolution, read-only alpha/edge audit. Never edits the PNG.

func _init() -> void:
	var failed := false
	for path in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Could not read " + path)
			failed = true
			continue
		var visible := 0
		var red := 0
		var clear := 0
		for y in range(source.get_height()):
			for x in range(source.get_width()):
				var p := source.get_pixel(x, y)
				if p.a < 0.01:
					clear += 1
				if p.a > 0.22:
					visible += 1
					if p.r > 0.85 and p.g < 0.20:
						red += 1
		print(JSON.stringify({"file": path, "visible_pixels": visible, "red_matte_pixels": red,
			"transparent_pct_full": 100.0 * clear / (source.get_width() * source.get_height())}))
	quit(1 if failed else 0)
