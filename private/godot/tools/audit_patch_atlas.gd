extends SceneTree
## Read-only: find real gutters rather than cutting across AI-drawn leaves.
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var source := Image.load_from_file(args[0])
	var width := source.get_width()
	var height := source.get_height()
	print("ATLAS_SIZE ", width, "x", height)
	for column in range(2):
		var left := column * width / 2
		var right := (column + 1) * width / 2
		var edges: Array[int] = [0]
		for seam in range(1, 4):
			var best_y := seam * height / 4
			var best_count := width
			var best_distance := height
			for y in range(best_y - 50, best_y + 61):
				var count := 0
				for x in range(left, right):
					if source.get_pixel(x, y).a > 0.22:
						count += 1
				var distance := absi(y - (seam * height / 4 + 16))
				if count < best_count or (count == best_count and distance < best_distance):
					best_y = y
					best_count = count
					best_distance = distance
			edges.append(best_y)
			print("GUTTER col=", column, " y=", best_y, " opaque samples=", best_count)
		edges.append(height)
		for row in range(4):
			var low := Vector2i(right, edges[row + 1])
			var high := Vector2i(left, edges[row])
			var red_pixels := 0
			var opaque_pixels := 0
			for y in range(edges[row], edges[row + 1]):
				for x in range(left, right):
					var pixel := source.get_pixel(x, y)
					if pixel.a > 0.22:
						low = low.min(Vector2i(x, y))
						high = high.max(Vector2i(x, y))
						opaque_pixels += 1
						if pixel.r > 0.85 and pixel.g < 0.20:
							red_pixels += 1
			var rectangle := Rect2i(low - Vector2i.ONE * 3, high - low + Vector2i.ONE * 7)
			print("CELL ", row * 2 + column, " crop=", rectangle, " red=", red_pixels, "/", opaque_pixels)
	quit()
