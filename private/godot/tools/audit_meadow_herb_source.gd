extends SceneTree
## Read-only alpha/crop registration for the two independent herb modules.

func _initialize() -> void:
	var paths := OS.get_cmdline_user_args()
	if paths.is_empty():
		push_error("Provide source atlas PNG paths after --")
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
		for cell in range(2):
			var low := Vector2i(source.get_width(), source.get_height())
			var high := Vector2i(-1, -1)
			var visible := 0
			for y in range(source.get_height()):
				for x in range(cell * source.get_width() / 2, (cell + 1) * source.get_width() / 2):
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
						if abs(x - source.get_width() / 2) < 12:
							gutter += 1
			var bounds := Rect2i(low, high - low + Vector2i.ONE)
			var aspect := float(bounds.size.x) / maxf(bounds.size.y, 1)
			var feet := PackedInt32Array()
			for i in range(25):
				var x := roundi(lerpf(low.x, high.x, i / 24.0))
				var bottom := -1
				for y in range(source.get_height()):
					if source.get_pixel(x, y).a > 0.60:
						bottom = y
				feet.append(bottom)
			cells.append({"bounds": str(bounds), "aspect": aspect, "visible_pixels": visible, "feet": str(feet)})
			failed = failed or visible < 10000 or aspect < 1.60 or aspect > 4.0
		var transparent := float(clear) / (source.get_width() * source.get_height())
		var valid := transparent > 0.50 and transparent < 0.95 and red == 0 and border == 0 and gutter == 0
		failed = failed or not valid
		print("HERB_SOURCE_AUDIT ", JSON.stringify({"path": path, "size": str(source.get_size()),
			"transparent_fraction": transparent, "red_matte": red, "edge_clipping": border,
			"gutter_pixels": gutter, "alpha_gate": valid, "cells": cells}))
	if not failed:
		print("MEADOW_HERB_SOURCE_AUDIT: PASS; true-alpha, clean gutter, full padding and two native-aspect modules")
	quit(1 if failed else 0)
