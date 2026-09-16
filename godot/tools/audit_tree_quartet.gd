extends SceneTree
## Read-only alpha/gutter/anchor measurement for a 2x2 generated tree atlas.
## Never rewrites pixels and never assumes the AI made equal-sized cells.

func _init() -> void:
	var args := OS.get_cmdline_user_args()
	assert(args.size() == 1, "Pass exactly one tree quartet PNG path")
	var source := Image.load_from_file(args[0])
	assert(source != null and not source.is_empty(), "Cannot read atlas")
	var w := source.get_width()
	var h := source.get_height()
	var row_split := h / 2
	var minimum := w + 1
	for y in range(h * 2 / 5, h * 3 / 5):
		var count := 0
		for x in range(w):
			if source.get_pixel(x, y).a > 0.22:
				count += 1
		if count < minimum or (count == minimum and absi(y - h / 2) < absi(row_split - h / 2)):
			minimum = count
			row_split = y
	print("TREE_ROW_GUTTER y=", row_split, " visible=", minimum)
	assert(minimum == 0, "No clear horizontal alpha gutter: reject or regenerate")
	var rows := [0, row_split, h]
	for row in range(2):
		var column_split := w / 2
		minimum = h + 1
		for x in range(w / 3, w * 2 / 3):
			var count := 0
			for y in range(rows[row], rows[row + 1]):
				if source.get_pixel(x, y).a > 0.22:
					count += 1
			if count < minimum or (count == minimum and absi(x - w / 2) < absi(column_split - w / 2)):
				minimum = count
				column_split = x
		print("TREE_COLUMN_GUTTER row=", row, " x=", column_split, " visible=", minimum)
		assert(minimum == 0, "No clear vertical alpha gutter: reject or regenerate")
		var columns := [0, column_split, w]
		for column in range(2):
			var low := Vector2i(w, h)
			var high := Vector2i.ZERO
			for y in range(rows[row], rows[row + 1]):
				for x in range(columns[column], columns[column + 1]):
					if source.get_pixel(x, y).a > 0.22:
						low = low.min(Vector2i(x, y))
						high = high.max(Vector2i(x, y))
			var cell := Rect2i(Vector2i(columns[column], rows[row]), Vector2i(columns[column + 1] - columns[column], rows[row + 1] - rows[row]))
			var crop := Rect2i(low - Vector2i(3, 3), high - low + Vector2i(7, 7)).intersection(cell)
			var roots := PackedInt32Array()
			for y in range(maxi(low.y, high.y - 9), high.y + 1):
				for x in range(low.x, high.x + 1):
					if source.get_pixel(x, y).a > 0.22:
						roots.append(x)
			roots.sort()
			var root_x := roots[roots.size() / 2]
			var anchor := (Vector2(root_x, high.y) - Vector2(crop.position)) / Vector2(crop.size)
			print("TREE_CELL ", row * 2 + column, " crop=", crop, " anchor=", anchor)
	quit()
