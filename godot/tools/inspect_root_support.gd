extends SceneTree
## Read-only local placement probe against the actual two baked solid meshes.
const MEADOW = preload("res://scripts/meadow_scene.gd")

func _initialize() -> void:
	var land_group: Node3D = load("res://assets/baked/v61/terrain.scn").instantiate()
	var rock_group: Node3D = load("res://assets/baked/v61/detail.scn").instantiate()
	var land: TriangleMesh = land_group.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var rock: TriangleMesh = rock_group.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var target := Vector2(-14.20, -37.64)
	var choices: Array[Dictionary] = []
	for x in range(-8, 9):
		for z in range(-8, 9):
			var p := target + Vector2(x, z) * 0.25
			var expected := MEADOW.terrain_height(p.x, p.y)
			var actual := -INF
			for surface in [land, rock]:
				var hit: Dictionary = surface.intersect_ray(Vector3(p.x, 40, p.y), Vector3.DOWN)
				if not hit.is_empty():
					actual = maxf(actual, hit.position.y)
			var error := absf(actual - expected)
			var slope := rad_to_deg(acos(clampf(MEADOW.terrain_normal(p.x, p.y).y, -1, 1)))
			if error < 0.018 and slope < 28:
				choices.append({"point": p, "error": error, "slope": slope, "score": p.distance_to(target) + slope * 0.014})
	choices.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.score < b.score)
	for i in range(mini(6, choices.size())):
		print("MEADOW_ROOT_SUPPORT_OPTION: ", choices[i])
	land_group.free()
	rock_group.free()
	quit()
