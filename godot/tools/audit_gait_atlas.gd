extends SceneTree
## Read-only source-alpha, complete cell bounds and frame registration measurements.

func _initialize() -> void:
	var failed := false
	for path: String in OS.get_cmdline_user_args():
		var image := Image.load_from_file(path)
		if image == null:
			failed = true
			continue
		var size := image.get_size()
		var frame_size := Vector2(size.x / 4.0, size.y / 2.0)
		var clear := 0
		var edge_hits := 0
		var frames := []
		var all_poses_valid := true
		for row in range(2):
			for column in range(4):
				var frame_origin := Vector2(column, row) * frame_size
				var origin := Vector2i(frame_origin.floor())
				var end := Vector2i((frame_origin + frame_size).floor())
				var cell := end - origin
				var low := cell
				var high := Vector2i.ZERO
				var visible := 0
				for y in range(cell.y):
					for x in range(cell.x):
						var p := image.get_pixelv(origin + Vector2i(x, y))
						if p.a < 0.01:
							clear += 1
						if p.a > 0.22:
							low = low.min(Vector2i(x, y))
							high = high.max(Vector2i(x, y))
							visible += 1
							if x < 2 or y < 2 or x >= cell.x - 2 or y >= cell.y - 2:
								edge_hits += 1
				var centroid_x := 0.0
				var weight := 0.0
				# Dense middle torso band, excluding hooves and antler/ear motion.
				for y in range(int(lerpf(low.y, high.y, 0.45)), int(lerpf(low.y, high.y, 0.67)) + 1):
					for x in range(cell.x):
						var alpha := image.get_pixelv(origin + Vector2i(x, y)).a
						if alpha > 0.60:
							centroid_x += x * alpha
							weight += alpha
				var anchor := (Vector2(centroid_x / maxf(weight, 1.0), high.y + 0.5) + Vector2(origin) - frame_origin) / frame_size
				all_poses_valid = all_poses_valid and visible > 200
				frames.append({"frame": frames.size(), "bounds": [low.x, low.y, high.x, high.y],
					"anchor": [snappedf(anchor.x, 0.0001), snappedf(anchor.y, 0.0001)], "opaque_pixels": visible})
		var transparency := float(clear) / (size.x * size.y)
		var valid := transparency > 0.30 and edge_hits == 0 and all_poses_valid
		failed = failed or not valid
		print("MEADOW_GAIT_ATLAS: ", JSON.stringify({"path": path, "size": [size.x, size.y], "cell": [frame_size.x, frame_size.y],
			"transparent_pct": transparency * 100.0, "edge_hits": edge_hits, "valid": valid, "frames": frames}))
	quit(1 if failed else 0)
