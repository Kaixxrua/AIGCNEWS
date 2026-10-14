extends SceneTree
## Twenty read-only terrain ray samples. No main, GPU render, bake or writes.
const CACHE_PATH := "res://assets/baked/v77/terrain.scn"
const XS := [1250, 1500, 1800, 2000, 2250]
const YS := [380, 410, 440, 470]
var bundle: Node
var viewport: SubViewport
var camera: Camera3D
var terrain: TriangleMesh

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _run() -> void:
	quit(1) # Synchronous runtime errors cannot default to a successful exit.
	var before := FileAccess.get_sha256(CACHE_PATH)
	var complete: Variant = _sample()
	if is_instance_valid(viewport): viewport.free()
	if is_instance_valid(bundle): bundle.free()
	var valid: bool = complete == true and not before.is_empty() and FileAccess.get_sha256(CACHE_PATH) == before
	print("FAR_SWARD_FOOTPRINT_DIAGNOSTIC: ", "COMPLETE" if valid else "ERROR", "; cache_sha256=", before, "; terrain-only adjacent-pixel finite differences, NOT GPU derivatives/occluder visibility/visual PASS; misses are not zero footprint")
	quit(0 if valid else 1)

func _ray(pixel: Vector2) -> Dictionary:
	var hit := terrain.intersect_ray(camera.project_ray_origin(pixel), camera.project_ray_normal(pixel))
	if hit.is_empty(): return {}
	var p: Vector3 = hit.position
	var depth := -camera.to_local(p).z
	if not p.is_finite() or depth < camera.near or depth > camera.far: return {}
	return hit

func _sample() -> bool:
	var packed := ResourceLoader.load(CACHE_PATH, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
	if packed == null: return false
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script" and state.get_node_property_value(i, j) != null:
				push_error("FAR_SWARD_FOOTPRINT: cache must be inert")
				return false
	bundle = packed.instantiate() # Off-tree: never trigger scene construction.
	var mesh_node := bundle.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	if mesh_node == null or mesh_node.mesh == null or mesh_node.transform != Transform3D.IDENTITY: return false
	if bundle is Node3D and bundle.transform != Transform3D.IDENTITY: return false
	terrain = mesh_node.mesh.generate_triangle_mesh()
	if terrain == null: return false
	viewport = SubViewport.new()
	viewport.size = Vector2i(2304, 1440)
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
	root.add_child(viewport)
	camera = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_PERSPECTIVE
	camera.keep_aspect = Camera3D.KEEP_HEIGHT
	camera.fov = 48.0
	camera.near = .1
	camera.far = 560.0
	viewport.add_child(camera)
	camera.position = Vector3(0, 18, 39)
	camera.look_at(Vector3(0, 0, -27))
	camera.make_current()
	print("FAR_SWARD_FOOTPRINT_FIXTURE: QHD2560x1440 -> viewport2304x1440 x-128; pixel centres +0.5; +1px X/Y; cached_signature=", bundle.get_meta("source_signature", ""))
	for y: int in YS:
		for x: int in XS:
			var pixel := Vector2(x - 128 + .5, y + .5)
			var base := _ray(pixel)
			var dx := _ray(pixel + Vector2.RIGHT)
			var dy := _ray(pixel + Vector2.DOWN)
			var record := {"qhd_pixel": [x, y], "viewport_pixel_centre": [pixel.x, pixel.y], "base_hit": not base.is_empty(), "x1_hit": not dx.is_empty(), "y1_hit": not dy.is_empty()}
			if not base.is_empty():
				var p: Vector3 = base.position
				record["world_xyz"] = [p.x, p.y, p.z]
				if not dx.is_empty() and not dy.is_empty():
					var px: Vector3 = dx.position
					var py: Vector3 = dy.position
					var fx := Vector2(px.x - p.x, px.z - p.z).length()
					var fy := Vector2(py.x - p.x, py.z - p.z).length()
					var footprint := maxf(fx, fy)
					record.merge({"xz_m_per_pixel_x": fx, "xz_m_per_pixel_y": fy, "footprint": footprint, "old_far_resolved": 1.0 - smoothstep(.8, 2.2, footprint)})
			print("FAR_SWARD_FOOTPRINT_POINT: ", JSON.stringify(record))
	return true
