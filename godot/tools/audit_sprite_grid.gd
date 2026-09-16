extends SceneTree
## Read-only pixel/alpha measurements; no image transformations or writes.

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 3:
		quit(1)
		return
	var columns := int(args[0])
	var rows := int(args[1])
	var failed := false
	for path in args.slice(2):
		var source := Image.load_from_file(path)
		if source == null:
			failed = true
			continue
		var w := source.get_width()
		var h := source.get_height()
		var clear := 0
		var red := 0
		var cells := []
		for row in range(rows):
			for col in range(columns):
				var lo := Vector2i(w, h)
				var hi := Vector2i(-1, -1)
				var visible := 0
				var edge_hits := 0
				var rect := Rect2i(col * w / columns, row * h / rows, w / columns, h / rows)
				for y in range(rect.position.y, rect.end.y):
					for x in range(rect.position.x, rect.end.x):
						var p := source.get_pixel(x, y)
						if p.a < 0.01:
							clear += 1
						if p.a > 0.22:
							lo = lo.min(Vector2i(x, y))
							hi = hi.max(Vector2i(x, y))
							visible += 1
							if x < rect.position.x + 2 or x >= rect.end.x - 2 or y < rect.position.y + 2 or y >= rect.end.y - 2:
								edge_hits += 1
							if p.r > 0.85 and p.g < 0.20:
								red += 1
				cells.append({"row": row, "col": col, "bounds": [lo.x, lo.y, hi.x, hi.y], "pixels": visible, "edge_hits": edge_hits})
				failed = failed or visible < 200 or edge_hits > 0
		var clear_percent := 100.0 * clear / (w * h)
		failed = failed or clear_percent < 25.0
		print("SPRITE_GRID ", JSON.stringify({"path": path, "size": [w, h], "transparent_pct": clear_percent, "red_pixels": red, "cells": cells}))
	quit(1 if failed else 0)
