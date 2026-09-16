extends SceneTree
## v103 geometry contract. Old v97 linear-X registration audit remains unchanged.
const SKY = preload("res://tools/audit_dragon_sky.gd")
var failed := false

func _initialize() -> void:
	_run.call_deferred()

func _expect(ok: bool, message: String) -> void:
	if not ok:
		failed = true
		push_error("MOUNTAIN_MASS: " + message)

func _expected_x(u: float) -> float:
	var mapped := 0.196 + 0.68 * (u - 0.196)
	if u > 0.45:
		var t := (u - 0.45) / 0.55
		mapped = (2*t*t*t - 3*t*t + 1)*0.36872 + (t*t*t - 2*t*t + t)*0.374 \
			+ (-2*t*t*t + 3*t*t) + (t*t*t - t*t)*0.649
	return (mapped - 0.5) * 650.0

func _run() -> void:
	var scene := (load("res://scenes/main.tscn") as PackedScene).instantiate()
	root.add_child(scene)
	await physics_frame
	var mountain: MeshInstance3D = scene.get_node("DistantMountainRidge")
	var camera: Camera3D = scene.camera
	var arrays := mountain.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	_expect(vertices.size() == 1365 and indices.size() == 7680, "Expected unchanged single-surface UV topology")
	var sums := PackedVector3Array()
	sums.resize(vertices.size())
	var depth := Vector2(INF, -INF)
	var extent := Vector2(INF, -INF)
	var area := 0.0
	for i in range(vertices.size()):
		_expect(vertices[i].is_finite() and uv[i].is_finite(), "Finite geometry")
		_expect(absf(vertices[i].x - _expected_x(uv[i].x)) < 0.0002, "Declared C1 source-to-world registration")
		var d := -camera.to_local(mountain.to_global(vertices[i])).z
		depth = Vector2(minf(depth.x, d), maxf(depth.y, d))
		extent = Vector2(minf(extent.x, vertices[i].x), maxf(extent.y, vertices[i].x))
	for i in range(0, indices.size(), 3):
		var a := indices[i]
		var b := indices[i+1]
		var c := indices[i+2]
		var winding := (uv[b]-uv[a]).cross(uv[c]-uv[a])
		var front := (vertices[c]-vertices[a]).cross(vertices[b]-vertices[a])
		_expect(winding > 0.0 and front.z > 0.0, "No UV/geometry folds")
		area += winding * 0.5
		for j: int in [a,b,c]:
			sums[j] += front
	_expect(absf(area-1.0) < 0.00001, "Whole source UV domain used once")
	for i in range(vertices.size()):
		_expect(normals[i].distance_to(sums[i].normalized()) < 0.0002, "Actual triangle-derived normals")
	var castle: MeshInstance3D = scene.get_node("IndependentCastleHill")
	var castle_far := -INF
	for p: Vector3 in castle.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]:
		castle_far = maxf(castle_far, -camera.to_local(castle.to_global(p)).z)
	_expect(depth.x > castle_far + 2.0 and depth.y < camera.far, "Mountain wholly behind castle and before far clip")
	var lookup := SKY.mountain_uv_lookup(mountain.mesh)
	var source: Image = scene.HORIZON.get_image()
	if source.is_compressed():
		_expect(source.decompress() == OK, "Readable original source alpha")
	var size := root.get_visible_rect().size
	var min_top := INF
	var visible := 0
	for x in range(source.get_width()):
		for y in range(source.get_height()):
			if source.get_pixel(x,y).a > 0.22:
				var p := SKY.mountain_uv_point(mountain, Vector2(float(x)/(source.get_width()-1),float(y)/(source.get_height()-1)),lookup)
				var screen := camera.unproject_position(p) / size
				if screen.x >= 0 and screen.x <= 1:
					visible += 1
					min_top = minf(min_top, screen.y)
					_expect(screen.y >= 0.0 and screen.y <= 1.0, "Visible alpha silhouette not clipped")
				break
	var terrain: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	var feet := 0
	var max_gap := -INF
	for column in range(65):
		var u := column / 64.0
		var x := roundi(u*(source.get_width()-1))
		for y in range(source.get_height()-1,-1,-1):
			if source.get_pixel(x,y).a > 0.60:
				var p := SKY.mountain_uv_point(mountain,Vector2(u,float(y)/(source.get_height()-1)),lookup)
				if absf(p.x) < 264.0:
					var hit := terrain.intersect_ray(Vector3(p.x,60.0,p.z),Vector3.DOWN)
					_expect(not hit.is_empty(), "Actual soil under in-bounds alpha root")
					if not hit.is_empty():
						feet += 1
						max_gap = maxf(max_gap,p.y-Vector3(hit.position).y)
				break
	_expect(visible > 0 and feet > 40 and max_gap < 0.04, "Nonempty supported sampled roots")
	print("MEADOW_MOUNTAIN_MASS: %s; extent=%s depth=%s castle_far=%.4f visible_top=%.5f sampled_feet=%d max_soil_gap=%.5f UVarea=%.8f; NOT visual or GPU lighting acceptance" % ["FAIL" if failed else "PASS",extent,depth,castle_far,min_top,feet,max_gap,area])
	scene.queue_free()
	await process_frame
	quit(1 if failed else 0)
