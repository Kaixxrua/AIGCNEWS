extends RefCounted
## Independent spatial contract for the deliberate v68 terrain reshape.
## Do not expand these bounds merely to make a failing regression pass.

static func in_edit_neighborhood(scene: Node3D, p: Vector3) -> bool:
	if p.z < -118.0 or p.z > -3.0 or (p.z > -44.5 and p.z < -31.5):
		return false
	var distance: float = absf(p.x - scene.river_center(p.z))
	return absf(distance - scene.river_half_width(p.z)) < scene.river_upper_slope(p.z) + 6.0

static func verify(scene: Node3D, require_change: bool = true) -> Dictionary:
	var before: Node3D = load("res://assets/baked/v67/terrain.scn").instantiate()
	var old: MeshInstance3D = before.get_node("ContinuousMeadow")
	var current: MeshInstance3D = scene.get_node("ContinuousMeadow")
	assert(old.transform == current.transform)
	var old_arrays := old.mesh.surface_get_arrays(0)
	var new_arrays := current.mesh.surface_get_arrays(0)
	var a: PackedVector3Array = old_arrays[Mesh.ARRAY_VERTEX]
	var b: PackedVector3Array = new_arrays[Mesh.ARRAY_VERTEX]
	assert(a.size() == b.size() and a.size() == 92619)
	assert(old_arrays[Mesh.ARRAY_INDEX] == new_arrays[Mesh.ARRAY_INDEX])
	var surface := current.mesh.generate_triangle_mesh()
	var unchanged := 0
	var changed := 0
	var maximum_change := 0.0
	var safe_probes := 0
	var safe_error := 0.0
	var visible_changes := 0
	var screen_delta := 0.0
	var viewport_size: Vector2 = scene.get_viewport().get_visible_rect().size
	for i in range(a.size()):
		var p := a[i]
		if not in_edit_neighborhood(scene, p) and not in_edit_neighborhood(scene, b[i]):
			for channel: int in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
				assert(old_arrays[channel][i] == new_arrays[channel][i], "Shore reshape escaped into unrelated terrain at %s, channel %d" % [p, channel])
			unchanged += 1
		else:
			# Bank samples were redistributed horizontally. Comparing matching
			# array indices measures resampling as well as terrain deformation.
			# Raycast at the SAME old world X/Z to measure actual ground change.
			var shore_hit := surface.intersect_ray(Vector3(p.x, p.y + 40, p.z), Vector3.DOWN)
			assert(not shore_hit.is_empty())
			var current_p: Vector3 = shore_hit.position
			var amount := absf(p.y - current_p.y)
			if amount > 0.05:
				changed += 1
				maximum_change = maxf(maximum_change, amount)
				var uv: Vector2 = scene.camera.unproject_position(current_p) / viewport_size
				if current_p.y > -0.94 and uv.x > 0.64 and uv.x < 1.0 and uv.y > 0.25 and uv.y < 0.78:
					# An in-frustum underwater or terrain-occluded change does not
					# establish visible bank shape. Check dry terrain line of sight.
					var sightline: Vector3 = (current_p - scene.camera.global_position).normalized()
					var seen := surface.intersect_ray(scene.camera.global_position, sightline)
					if not seen.is_empty() and seen.position.distance_to(current_p) < 0.10:
						visible_changes += 1
						var old_uv: Vector2 = scene.camera.unproject_position(p) / viewport_size
						screen_delta = maxf(screen_delta, old_uv.distance_to(uv))
		var q := Vector2(p.x, p.z)
		var route: bool = p.z > -65.0 and scene.distance_to_road(q) < scene.road_half_width(p.z) + 0.8
		if route or q.distance_to(Vector2(5, -12)) < 5.0:
			var hit := surface.intersect_ray(Vector3(p.x, p.y + 40, p.z), Vector3.DOWN)
			assert(not hit.is_empty())
			safe_error = maxf(safe_error, absf(hit.position.y - p.y))
			safe_probes += 1
	assert(unchanged > 80000 and safe_probes > 1000 and safe_error < 0.025)
	if require_change:
		assert(changed > 300 and maximum_change > 1.0, "The bank needs a macro shape change, not only micro-surface decoration")
		assert(visible_changes > 80 and screen_delta > 0.008, "New geometry must affect the camera-visible bank")
	before.free()
	return {"unchanged": unchanged, "changed": changed, "maximum_change": maximum_change,
		"safe_probes": safe_probes, "safe_error": safe_error, "visible_changes": visible_changes, "screen_delta": screen_delta}
