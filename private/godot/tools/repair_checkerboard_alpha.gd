extends SceneTree

const BACKGROUND_MIN_VALUE := 0.78
const BACKGROUND_MAX_SATURATION := 0.10


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() == 0 or args.size() % 2 != 0:
		push_error("Usage: godot --headless --script repair_checkerboard_alpha.gd -- <input.png> <output.png> [...]")
		quit(2)
		return

	for index in range(0, args.size(), 2):
		_repair(args[index], args[index + 1])

	quit()


func _repair(input_path: String, output_path: String) -> void:
	var image := Image.load_from_file(input_path)
	if image == null:
		push_error("Unable to load image: %s" % input_path)
		return
	image.convert(Image.FORMAT_RGBA8)

	var width := image.get_width()
	var height := image.get_height()
	var visited := PackedByteArray()
	visited.resize(width * height)
	var queue_x := PackedInt32Array()
	var queue_y := PackedInt32Array()

	for x in range(width):
		_enqueue_if_background(image, x, 0, visited, queue_x, queue_y)
		_enqueue_if_background(image, x, height - 1, visited, queue_x, queue_y)
	for y in range(1, height - 1):
		_enqueue_if_background(image, 0, y, visited, queue_x, queue_y)
		_enqueue_if_background(image, width - 1, y, visited, queue_x, queue_y)

	var head := 0
	var transparent_pixels := 0
	while head < queue_x.size():
		var x := queue_x[head]
		var y := queue_y[head]
		head += 1

		var color := image.get_pixel(x, y)
		image.set_pixel(x, y, Color(color.r, color.g, color.b, 0.0))
		transparent_pixels += 1

		for offset in [Vector2i(-1, -1), Vector2i(0, -1), Vector2i(1, -1), Vector2i(-1, 0), Vector2i(1, 0), Vector2i(-1, 1), Vector2i(0, 1), Vector2i(1, 1)]:
			_enqueue_if_background(image, x + offset.x, y + offset.y, visited, queue_x, queue_y)

	# The generated checkerboard is often blended into the silhouette by one or
	# two pale pixels. Remove that matte fringe now that the true background is
	# known to be transparent. This is deliberately limited to neutral, bright
	# pixels so warm stone, grass, and wood color stays intact.
	for pass_index in range(2):
		var fringe_pixels: Array[Vector2i] = []
		for y in range(1, height - 1):
			for x in range(1, width - 1):
				var pixel := image.get_pixel(x, y)
				if pixel.a <= 0.0 or not _is_fringe_pixel(pixel):
					continue
				if _has_transparent_neighbor(image, x, y):
					fringe_pixels.append(Vector2i(x, y))
		for pixel_position in fringe_pixels:
			var fringe_color := image.get_pixel(pixel_position.x, pixel_position.y)
			image.set_pixel(pixel_position.x, pixel_position.y, Color(fringe_color.r, fringe_color.g, fringe_color.b, 0.0))
		transparent_pixels += fringe_pixels.size()

	var error := image.save_png(output_path)
	if error != OK:
		push_error("Unable to save repaired image: %s" % output_path)
	else:
		print("Repaired %s -> %s (%d transparent pixels)" % [input_path, output_path, transparent_pixels])


func _enqueue_if_background(image: Image, x: int, y: int, visited: PackedByteArray, queue_x: PackedInt32Array, queue_y: PackedInt32Array) -> void:
	if x < 0 or y < 0 or x >= image.get_width() or y >= image.get_height():
		return
	var index := y * image.get_width() + x
	if visited[index] == 1:
		return
	visited[index] = 1
	if not _is_checkerboard_pixel(image.get_pixel(x, y)):
		return
	queue_x.append(x)
	queue_y.append(y)


func _is_checkerboard_pixel(color: Color) -> bool:
	var maximum: float = maxf(color.r, maxf(color.g, color.b))
	var minimum: float = minf(color.r, minf(color.g, color.b))
	return maximum >= BACKGROUND_MIN_VALUE and maximum - minimum <= BACKGROUND_MAX_SATURATION


func _is_fringe_pixel(color: Color) -> bool:
	var maximum: float = maxf(color.r, maxf(color.g, color.b))
	var minimum: float = minf(color.r, minf(color.g, color.b))
	return maximum >= 0.72 and maximum - minimum <= 0.14


func _has_transparent_neighbor(image: Image, x: int, y: int) -> bool:
	for offset in [Vector2i(-1, -1), Vector2i(0, -1), Vector2i(1, -1), Vector2i(-1, 0), Vector2i(1, 0), Vector2i(-1, 1), Vector2i(0, 1), Vector2i(1, 1)]:
		if image.get_pixel(x + offset.x, y + offset.y).a <= 0.0:
			return true
	return false
