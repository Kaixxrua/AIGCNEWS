extends SceneTree
## Read-only six-cell RGBA inspection. It never edits source image pixels.

func _initialize() -> void:
	var paths := OS.get_cmdline_user_args()
	if paths.is_empty():
		push_error("Provide atlas PNG paths after --")
		quit(1)
		return
	var failed := false
	for path: String in paths:
		var source := Image.load_from_file(ProjectSettings.globalize_path(path))
		if source == null:
			push_error("Cannot read source: " + path)
			failed = true
			continue
		var clear := 0
		var red := 0
		var border := 0
		var gutter := 0
		var cells: Array[Dictionary] = []
		# Image generators do not promise mathematical thirds. Find actual empty
		# vertical gutters per row; an equal-grid crop can slice intact branches.
		var row_edges := [_split_edges(source, 0), _split_edges(source, 1)]
		if row_edges[0].is_empty() or row_edges[1].is_empty():
			push_error("No separated three-column silhouettes: " + path)
			failed = true
			continue
		for cell in range(6):
			var low := source.get_size()
			var high := Vector2i(-1, -1)
			var visible := 0
			var row: int = cell / 3
			var col: int = cell % 3
			var edges: PackedInt32Array = row_edges[row]
			for y in range(row * source.get_height() / 2, (row + 1) * source.get_height() / 2):
				for x in range(edges[col], edges[col + 1]):
					var p := source.get_pixel(x, y)
					if p.a < 0.01:
						clear += 1
					if p.a > 0.22:
						visible += 1
						low = low.min(Vector2i(x, y))
						high = high.max(Vector2i(x, y))
						if p.r > 0.85 and p.g < 0.20:
							red += 1
						if x < 5 or y < 5 or x >= source.get_width() - 5 or y >= source.get_height() - 5:
							border += 1
						if abs(x - edges[1]) < 4 or abs(x - edges[2]) < 4 or abs(y - source.get_height() / 2) < 4:
							gutter += 1
			var bounds := Rect2i(low, high - low + Vector2i.ONE)
			var aspect := float(bounds.size.x) / maxf(bounds.size.y, 1)
			cells.append({"bounds": [low.x, low.y, high.x + 1, high.y + 1], "aspect": aspect, "visible_pixels": visible})
			failed = failed or visible < 4000 or aspect < 0.60 or aspect > 4.0
		var transparent := float(clear) / (source.get_width() * source.get_height())
		var valid := transparent > 0.35 and transparent < 0.95 and red == 0 and border == 0 and gutter == 0
		failed = failed or not valid
		print("SCRUB_SOURCE_AUDIT ", JSON.stringify({"path": path, "size": str(source.get_size()),
			"transparent_fraction": transparent, "red_matte": red, "edge_clipping": border,
			"gutter_pixels": gutter, "alpha_gate": valid, "row_edges": row_edges, "cells": cells}))
	if not failed:
		print("MEADOW_SCRUB_SOURCE_AUDIT: PASS; six distinct true-alpha modules; open gutters and full padding")
	quit(1 if failed else 0)

func _split_edges(source: Image, row: int) -> PackedInt32Array:
	var counts := PackedInt32Array()
	counts.resize(source.get_width())
	for y in range(row * source.get_height() / 2, (row + 1) * source.get_height() / 2):
		for x in range(source.get_width()):
			counts[x] += int(source.get_pixel(x, y).a > 0.22)
	var edges := PackedInt32Array([0])
	for split in range(1, 3):
		var low := floori(source.get_width() * (split / 3.0 - 0.105))
		var high := ceili(source.get_width() * (split / 3.0 + 0.105))
		var start := -1
		var best := -1
		var longest := 0
		for x in range(low, high + 1):
			if x < high and counts[x] == 0:
				if start < 0:
					start = x
			elif start >= 0:
				if x - start > longest:
					longest = x - start
					best = (x + start) / 2
				start = -1
		if longest < 8:
			return PackedInt32Array()
		edges.append(best)
	edges.append(source.get_width())
	return edges
