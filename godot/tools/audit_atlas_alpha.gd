extends SceneTree

# Inspect only: UV cells and original RGBA remain untouched.
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 3:
		push_error("Usage: --script res://tools/audit_atlas_alpha.gd -- /absolute/atlas.png 4 2")
		quit(1)
		return
	var source := Image.load_from_file(args[0])
	var columns := int(args[1])
	var rows := int(args[2])
	if source == null or columns < 1 or rows < 1:
		quit(1)
		return
	var cell_size := Vector2i(source.get_width() / columns, source.get_height() / rows)
	for row in range(rows):
		for column in range(columns):
			var origin := Vector2i(column, row) * cell_size
			var minimum := cell_size
			var maximum := Vector2i.ZERO
			var transparent := 0
			var total := 0
			for y in range(0, cell_size.y, 2):
				for x in range(0, cell_size.x, 2):
					var alpha := source.get_pixel(origin.x + x, origin.y + y).a
					total += 1
					if alpha < 0.01:
						transparent += 1
					if alpha > 0.22:
						minimum = minimum.min(Vector2i(x, y))
						maximum = maximum.max(Vector2i(x, y))
			print(JSON.stringify({"cell": row * columns + column, "transparent_pct": 100.0 * transparent / total,
				"bounds": Rect2i(minimum, maximum - minimum + Vector2i.ONE), "cell_size": cell_size,
				"root_y": float(maximum.y) / cell_size.y}))
	quit()
