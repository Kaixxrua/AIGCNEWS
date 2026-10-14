extends SceneTree
## Read-only horizontal cloud tracking in an observed sky-only screenshot ROI.
## Arguments: first.jpg second.jpg x y width height. Never edits an image.

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 6:
		quit(1)
		return
	var first := Image.load_from_file(args[0])
	var second := Image.load_from_file(args[1])
	var roi := Rect2i(int(args[2]), int(args[3]), int(args[4]), int(args[5]))
	if first == null or second == null or first.get_size() != second.get_size():
		quit(1)
		return
	assert(roi.position.x >= 0 and roi.position.y >= 0)
	assert(roi.end.x + 40 < first.get_width() and roi.end.y < first.get_height())
	var best_error := INF
	var best_shift := 0
	var fixed_error := 0.0
	for shift in range(41):
		var error := 0.0
		for y in range(roi.position.y, roi.end.y):
			for x in range(roi.position.x, roi.end.x):
				var a := first.get_pixel(x, y)
				var b := second.get_pixel(x + shift, y)
				error += absf(a.r - b.r) + absf(a.g - b.g) + absf(a.b - b.b)
		error *= 255.0 / (roi.size.x * roi.size.y * 3.0)
		if shift == 0:
			fixed_error = error
		if error < best_error:
			best_error = error
			best_shift = shift
	var passed := best_shift >= 3 and best_shift < 40 and best_error < fixed_error * 0.65
	print("MEADOW_CLOUD_FRAME_AUDIT: %s; ROI %s; best rightward shift %d px; fixed error %.4f; tracked error %.4f RGB255/channel" %
		["PASS" if passed else "FAIL", roi, best_shift, fixed_error, best_error])
	quit(0 if passed else 1)
