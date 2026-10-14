extends RefCounted
## Each source atlas is used once; UV frames are not repeated scene individuals.
## Registration measured by audit_gait_atlas.gd, including fractional atlas cells.

const PATHS := ["res://assets/creatures/leaf-hare-v54.png", "res://assets/creatures/bud-deer-v54.png",
	"res://assets/creatures/gold-fox-v54.png", "res://assets/creatures/moon-stag-v54.png"]
const HEIGHTS := [1.75, 2.85, 2.35, 3.20]
const ANCHORS := [
	# Frame 2 is intentionally airborne: use its row's ground baseline, not its paws.
	[Vector2(0.5338, 0.9301), Vector2(0.5422, 0.9301), Vector2(0.5453, 0.9301), Vector2(0.5376, 0.9301), Vector2(0.5607, 0.8591), Vector2(0.5397, 0.8591), Vector2(0.5381, 0.8591), Vector2(0.5409, 0.8658)],
	[Vector2(0.5028, 0.8896), Vector2(0.4953, 0.8916), Vector2(0.4980, 0.8877), Vector2(0.4872, 0.8916), Vector2(0.5035, 0.8721), Vector2(0.4954, 0.8721), Vector2(0.5059, 0.8701), Vector2(0.4901, 0.8721)],
	[Vector2(0.5225, 0.7881), Vector2(0.5285, 0.7881), Vector2(0.5218, 0.7881), Vector2(0.5295, 0.7881), Vector2(0.5275, 0.7354), Vector2(0.5361, 0.7354), Vector2(0.5231, 0.7354), Vector2(0.5318, 0.7354)],
	[Vector2(0.5329, 0.9729), Vector2(0.5341, 0.9729), Vector2(0.5353, 0.9662), Vector2(0.5288, 0.9729), Vector2(0.5364, 0.9673), Vector2(0.5344, 0.9673), Vector2(0.5378, 0.9605), Vector2(0.5313, 0.9673)]
]

static func get_animal(index: int) -> Dictionary:
	var texture: Texture2D = load(PATHS[index])
	assert(texture != null, "Selected eight-frame animal PNG is required")
	var cell := Vector2(texture.get_width() / 4.0, texture.get_height() / 2.0)
	var frames: Array[Rect2] = []
	for row in range(2):
		for column in range(4):
			frames.append(Rect2(Vector2(column, row) * cell, cell))
	return {"texture": texture, "frames": frames, "anchors": ANCHORS[index],
		"display": Vector2(cell.x / cell.y, 1.0) * HEIGHTS[index]}
