extends SceneTree
## Read-only camera/terrain fit candidates; no scene or assets are modified.

const TERRAIN = preload("res://scripts/meadow_scene.gd")
const VILLAGE = preload("res://scripts/meadow_village_builder.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.position = Vector3(0, 18, 39)
	camera.look_at(Vector3(0, 0, -27))
	camera.fov = 48.0
	var uvs: Array[Vector2] = []
	for p: Vector2 in VILLAGE.BODY_HUBS:
		uvs.append((p + Vector2(0.5, 0.5) - VILLAGE.BODY_CROP.position) / VILLAGE.BODY_CROP.size)
	for depth: float in [-127.0, -140.0, -150.0, -160.0, -170.0, -180.0, -195.0]:
		var targets: Array[Vector3] = []
		for target: Vector2 in VILLAGE.HUB_TARGETS:
			var pixel := target * root.get_visible_rect().size
			var origin := camera.project_ray_origin(pixel)
			var direction := camera.project_ray_normal(pixel)
			targets.append(origin + direction * ((depth - origin.z) / direction.z))
		var width := (targets[1].x - targets[0].x) / (uvs[1].x - uvs[0].x)
		var centre := targets[0].x - (uvs[0].x - 0.5) * width
		var base := TERRAIN.terrain_height(centre, depth)
		var height := (targets[0].y - base) / (VILLAGE.ANCHOR_V - uvs[0].y)
		var native := width * VILLAGE.BODY_CROP.size.y / VILLAGE.BODY_CROP.size.x
		var screen := camera.unproject_position(Vector3(centre, base, depth)) / root.get_visible_rect().size
		print("VILLAGE_FIT_CANDIDATE ", JSON.stringify({"depth": depth, "centre_x": centre,
			"width": width, "height": height, "native_height": native, "ratio": height / native,
			"base": base, "base_screen": str(screen)}))
	quit()
