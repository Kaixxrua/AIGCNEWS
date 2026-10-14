extends SceneTree
## Read-only screenshot difference. No image or asset is rewritten.

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		push_error("Pass two absolute screenshot paths after --")
		quit(1)
		return
	var first := Image.load_from_file(args[0])
	var second := Image.load_from_file(args[1])
	if first == null or second == null or first.get_size() != second.get_size():
		push_error("Screenshots must load and have equal dimensions")
		quit(1)
		return
	var totals := [0.0, 0.0, 0.0]
	var pixels := [0, 0, 0]
	var changed := [0, 0, 0]
	var maximum := [0.0, 0.0, 0.0]
	var coordinates := [Vector2i.ZERO, Vector2i.ZERO, Vector2i.ZERO]
	for y in range(first.get_height()):
		for x in range(first.get_width()):
			var group := 0 if y < first.get_height() * 0.25 else 1
			if y < first.get_height() * 0.25 and x > first.get_width() * 0.81:
				group = 2
			var a := first.get_pixel(x, y)
			var b := second.get_pixel(x, y)
			var difference := (absf(a.r - b.r) + absf(a.g - b.g) + absf(a.b - b.b)) * 255.0
			totals[group] += difference
			pixels[group] += 1
			if difference > 6.1:
				changed[group] += 1
			if difference > maximum[group]:
				maximum[group] = difference
				coordinates[group] = Vector2i(x, y)
	for i in range(3):
		print("MEADOW_FRAME_DIFF: %s mean/channel=%.6f; pixels over 6 RGB sum=%d/%d; max=%.1f at %s" %
			[["sky", "ground", "controls"][i], totals[i] / (3.0 * pixels[i]), changed[i], pixels[i], maximum[i], coordinates[i]])
	quit()
