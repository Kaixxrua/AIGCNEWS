extends SceneTree
## Read-only alpha components/gutters. Source images are never changed.

func _initialize() -> void:
	for path: String in OS.get_cmdline_user_args():
		var source := Image.load_from_file(path)
		assert(source != null)
		var w := source.get_width()
		var h := source.get_height()
		var mask := PackedByteArray()
		mask.resize(w * h)
		var clear := 0
		var red := 0
		var rows := PackedInt32Array()
		rows.resize(h)
		for y in range(h):
			for x in range(w):
				var pixel := source.get_pixel(x, y)
				if pixel.a < 0.01:
					clear += 1
				if pixel.a > 0.22:
					mask[y * w + x] = 1
					rows[y] += 1
					if pixel.r > 0.85 and pixel.g < 0.20:
						red += 1
		var empty_bands := []
		var first := -1
		for y in range(h + 1):
			if y < h and rows[y] == 0:
				if first < 0:
					first = y
			elif first >= 0:
				empty_bands.append([first, y - 1])
				first = -1
		var components := []
		for initial in range(w * h):
			if mask[initial] != 1:
				continue
			var queue := PackedInt32Array([initial])
			mask[initial] = 0
			var head := 0
			var low := Vector2i(w, h)
			var high := Vector2i.ZERO
			while head < queue.size():
				var index := queue[head]
				head += 1
				var point := Vector2i(index % w, index / w)
				low = low.min(point)
				high = high.max(point)
				for offset: Vector2i in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
					var next := point + offset
					if next.x < 0 or next.y < 0 or next.x >= w or next.y >= h:
						continue
					var next_index := next.y * w + next.x
					if mask[next_index] == 1:
						mask[next_index] = 0
						queue.append(next_index)
			if queue.size() >= 350:
				components.append({"bounds": [low.x, low.y, high.x + 1, high.y + 1], "pixels": queue.size()})
		print("IMAGE_REGIONS ", JSON.stringify({"path": path, "size": [w, h], "clear_pct": 100.0 * clear / (w * h),
			"red_pixels": red, "empty_rows": empty_bands, "components": components}))
	quit()
