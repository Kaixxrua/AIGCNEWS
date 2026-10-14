extends SceneTree
## Read-only registration aid. Search locally around visually chosen openings;
## these samples are not a substitute for checking the final night render.
const AREAS := [Vector2i(1355, 123), Vector2i(1199, 156), Vector2i(1272, 185),
	Vector2i(1470, 213), Vector2i(952, 285), Vector2i(952, 321),
	Vector2i(82, 535), Vector2i(158, 586), Vector2i(397, 548),
	Vector2i(536, 489), Vector2i(558, 489), Vector2i(655, 414),
	Vector2i(667, 449), Vector2i(704, 560), Vector2i(738, 562),
	Vector2i(821, 587), Vector2i(832, 615), Vector2i(1011, 547),
	Vector2i(1045, 485), Vector2i(1115, 586), Vector2i(1154, 586),
	Vector2i(1244, 585), Vector2i(1285, 551), Vector2i(1530, 507),
	Vector2i(1556, 539), Vector2i(1475, 393), Vector2i(1500, 398),
	Vector2i(1639, 574), Vector2i(1674, 552), Vector2i(1776, 429),
	Vector2i(1940, 540), Vector2i(1980, 531)]

func _initialize() -> void:
	var source := Image.load_from_file(ProjectSettings.globalize_path("res://assets/backgrounds/castle-town-v62.png"))
	for i in range(AREAS.size()):
		var centre: Vector2i = AREAS[i]
		var best := -INF
		var selected := centre
		for dy in range(-10, 11):
			for dx in range(-10, 11):
				var p := centre + Vector2i(dx, dy)
				var c := source.get_pixelv(p)
				if c.a < 0.98:
					continue
				var interior := 0.0
				var surround := 0.0
				var covered := true
				for y in range(-3, 4):
					for x in range(-2, 3):
						var pixel := source.get_pixelv(p + Vector2i(x, y))
						covered = covered and pixel.a > 0.98
						interior += pixel.get_luminance() / 35.0
					for x: int in [-5, 5]:
						surround += source.get_pixelv(p + Vector2i(x, y)).get_luminance() / 14.0
				if not covered:
					continue
				var score := (surround - interior) * 2.0 - interior * 0.30 - Vector2(dx, dy).length() * 0.004
				if score > best:
					best = score
					selected = p
		print("CITY_WINDOW_SAMPLE: %02d Vector4(%d, %d, 2, 3), local_score=%.3f" % [i, selected.x, selected.y, best])
	quit()
