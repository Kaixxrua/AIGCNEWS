extends SceneTree
## Read-only alpha bounds for a one-column, four-strip surface atlas.

func _init() -> void:
	var failed := false
	for path in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		if source == null:
			push_error("Cannot load " + path)
			failed = true
			continue
		var width := source.get_width()
		var height := source.get_height()
		var row_counts := PackedInt32Array()
		row_counts.resize(height)
		var transparent := 0
		var red := 0
		for y in range(height):
			for x in range(width):
				var p := source.get_pixel(x, y)
				if p.a < 0.01:
					transparent += 1
				if p.a > 0.22:
					row_counts[y] += 1
					if p.r > 0.85 and p.g < 0.20:
						red += 1
		var edges: Array[int] = [0]
		for row in range(1, 4):
			var center := roundi(row * height / 4.0)
			var best := center
			for y in range(maxi(0, center - 48), mini(height, center + 49)):
				if row_counts[y] < row_counts[best] or (row_counts[y] == row_counts[best] and absi(y - center) < absi(best - center)):
					best = y
			edges.append(best)
			if row_counts[best] != 0:
				failed = true
			print("STRIP_GUTTER ", JSON.stringify({"file": path, "row": row, "y": best, "visible_pixels": row_counts[best]}))
		edges.append(height)
		for row in range(4):
			var low := Vector2i(width, edges[row + 1])
			var high := Vector2i(0, edges[row])
			for y in range(edges[row], edges[row + 1]):
				for x in range(width):
					if source.get_pixel(x, y).a > 0.22:
						low = low.min(Vector2i(x, y))
						high = high.max(Vector2i(x, y))
			var origin := (low - Vector2i(3, 3)).max(Vector2i(0, edges[row]))
			var end := (high + Vector2i(4, 4)).min(Vector2i(width, edges[row + 1]))
			print("STRIP_CROP ", JSON.stringify({"row": row, "crop": [origin.x, origin.y, end.x - origin.x, end.y - origin.y]}))
		print("STRIP_ALPHA ", JSON.stringify({"file": path, "size": [width, height],
			"transparent_pct": 100.0 * transparent / (width * height), "red_matte_pixels": red}))
	quit(1 if failed else 0)
