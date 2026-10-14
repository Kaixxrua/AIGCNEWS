extends SceneTree
## Read-only: compare the whole animated silhouette with the rendered skyline.
## A high world Y / shoulder anchor alone can still put wings through a tower.

const MAIN = preload("res://scenes/main.tscn")
const SKY_COLUMNS := 2048
const SEEDS := [530909, 530910, 540001, 540029, 540113, 540977, 541237, 549991]
var deepest_vertex := 0.0

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var scene := MAIN.instantiate()
	root.add_child(scene)
	await physics_frame
	var wildlife = scene.get_node("LivingWildlife")
	var weather = scene.get_node("LivingWeather")
	wildlife.set_process(false)
	weather.set_process(false)
	var skyline := _skyline(scene)
	var silhouettes := _frame_bounds(wildlife)
	var top_margin := INF
	var landmark_gap := INF
	var minimum_height := INF
	var max_step := 0.0
	var worst := {}
	var samples := 0
	for seed_value: int in SEEDS:
		wildlife.reset_flight(seed_value)
		wildlife.dragon_bank = 0.0
		var previous: Vector3 = wildlife._flight_position(0.0)
		for step in range(1920):
			wildlife._update_dragon(float(step) * 0.125, 0.125)
			var position: Vector3 = wildlife.dragon.position
			minimum_height = minf(minimum_height, position.y)
			max_step = maxf(max_step, position.distance_to(previous))
			previous = position
			var rect := _projected_bounds(scene, wildlife, silhouettes[wildlife.dragon_frame], wildlife.dragon_frame)
			if wildlife.dragon_turn_mix < 1.0:
				rect = rect.merge(_projected_bounds(scene, wildlife, silhouettes[wildlife.previous_dragon_frame], wildlife.previous_dragon_frame))
			top_margin = minf(top_margin, rect.position.y)
			var gap := _clearance(skyline, rect)
			if gap < landmark_gap:
				landmark_gap = gap
				worst = {"seed": seed_value, "time": step * 0.125, "frame": wildlife.dragon_frame,
					"bounds": str(rect), "position": str(position), "gap": gap}
			assert(rect.position.x > 0.015 and rect.end.x < 0.985, "Dragon is clipped by the side of the view")
			samples += 1
	print("MEADOW_DRAGON_SKY_MEASURE: %d seeds / %d frames / 240s each; top %.2f px; skyline gap %.2f px; minimum Y %.2f m; max step %.3f m; worst %s" % [
		SEEDS.size(), samples, top_margin * 800.0, landmark_gap * 800.0, minimum_height, max_step, worst])
	assert(top_margin >= 0.006, "Raised flight clips the animated wings at the top of the frame")
	assert(landmark_gap >= 0.015, "Whole dragon needs at least 12px of clear sky above the actual mountain/castle outline")
	assert(minimum_height > 50.0 and max_step < 4.5, "Flight must be elevated and continuous")
	print("MEADOW_DRAGON_CLIP_AUDIT: deepest silhouette %.2f m; far clip %.2f m; %.2f m clearance" % [deepest_vertex, scene.camera.far, scene.camera.far - deepest_vertex])
	print("MEADOW_DRAGON_SKY_AUDIT: PASS; 32 source-alpha poses and blended turn silhouettes; no skyline overlap or viewport/far-plane clipping")
	scene.queue_free()
	await process_frame
	quit()

func _skyline(scene: Node3D) -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(SKY_COLUMNS)
	heights.fill(1.0)
	var view_size := root.get_visible_rect().size
	for label: String in ["DistantMountainRidge", "RightMountainRidge", "IndependentCastleHill"]:
		var card: MeshInstance3D = scene.get_node(label)
		var texture: Texture2D = card.material_override.get_shader_parameter("asset_texture")
		var source := texture.get_image()
		if source.is_compressed():
			assert(source.decompress() == OK)
		var columns := PackedFloat32Array()
		var mountain_lookup := {}
		var is_mountain := label in ["DistantMountainRidge", "RightMountainRidge"]
		var region: Vector4 = card.material_override.get_shader_parameter("uv_region")
		var threshold: float = card.material_override.get_shader_parameter("alpha_threshold")
		if is_mountain and not card.mesh is QuadMesh:
			mountain_lookup = mountain_uv_lookup(card.mesh)
		if card.mesh is QuadMesh or is_mountain:
			for x in range(source.get_width()):
				columns.append(float(x) / (source.get_width() - 1))
		else:
			# City mesh columns include its measured peak and rigid UV edges.
			var uv: PackedVector2Array = card.mesh.surface_get_arrays(0)[Mesh.ARRAY_TEX_UV]
			for i in range(0, uv.size(), 26):
				columns.append(uv[i].x)
		var previous := Vector2(-1, 1)
		for u: float in columns:
			var x := clampi(roundi((region.x + u * region.z) * (source.get_width() - 1)), 0, source.get_width() - 1)
			var top := -1
			for y in range(source.get_height()):
				var source_v := float(y) / (source.get_height() - 1)
				if source_v < region.y or source_v > region.y + region.w:
					continue
				if source.get_pixel(x, y).a > threshold:
					top = y
					break
			if top < 0:
				continue
			var sample_uv := Vector2(u, (float(top) / (source.get_height() - 1) - region.y) / region.w)
			var p: Vector3 = mountain_uv_point(card, sample_uv, mountain_lookup) if not mountain_lookup.is_empty() else scene._card_point(card, sample_uv)
			assert(p.is_finite(), "Skyline sample must lie on an actual mesh triangle")
			var screen: Vector2 = scene.camera.unproject_position(p) / view_size
			if previous.x >= 0.0:
				var first := clampi(floori(previous.x * SKY_COLUMNS), 0, SKY_COLUMNS - 1)
				var last := clampi(ceili(screen.x * SKY_COLUMNS), 0, SKY_COLUMNS - 1)
				if not mountain_lookup.is_empty():
					# Depth relief can reverse projected X locally; cover both endpoints.
					first = clampi(floori(minf(previous.x, screen.x) * SKY_COLUMNS), 0, SKY_COLUMNS - 1)
					last = clampi(ceili(maxf(previous.x, screen.x) * SKY_COLUMNS), 0, SKY_COLUMNS - 1)
				for column in range(first, last + 1):
					# Use the higher endpoint: conservative around narrow tower tips.
					heights[column] = minf(heights[column], minf(previous.y, screen.y))
			previous = screen
	return heights

static func mountain_uv_lookup(mesh: Mesh) -> Dictionary:
	# Independent triangle lookup, no production grid/26-row ordering assumption.
	assert(mesh.get_surface_count() == 1 and mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES)
	var arrays := mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var uv: PackedVector2Array = arrays[Mesh.ARRAY_TEX_UV]
	var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
	assert(uv.size() == vertices.size())
	if indices.is_empty():
		for i in range(vertices.size()):
			indices.append(i)
	assert(indices.size() % 3 == 0)
	var bins: Array[PackedInt32Array] = []
	for i in range(128):
		bins.append(PackedInt32Array())
	for i in range(0, indices.size(), 3):
		var a := indices[i]
		var b := indices[i + 1]
		var c := indices[i + 2]
		assert(a >= 0 and b >= 0 and c >= 0 and a < uv.size() and b < uv.size() and c < uv.size())
		var first := clampi(floori(minf(uv[a].x, minf(uv[b].x, uv[c].x)) * 128.0), 0, 127)
		var last := clampi(floori(maxf(uv[a].x, maxf(uv[b].x, uv[c].x)) * 128.0), 0, 127)
		for column in range(first, last + 1):
			var bucket: PackedInt32Array = bins[column]
			bucket.append(i)
			bins[column] = bucket
	return {"vertices": vertices, "uv": uv, "indices": indices, "bins": bins}

static func mountain_uv_point(card: MeshInstance3D, at_uv: Vector2, lookup: Dictionary) -> Vector3:
	var uv: PackedVector2Array = lookup.uv
	var vertices: PackedVector3Array = lookup.vertices
	var indices: PackedInt32Array = lookup.indices
	for triangle: int in lookup.bins[clampi(floori(at_uv.x * 128.0), 0, 127)]:
		var a := indices[triangle]
		var b := indices[triangle + 1]
		var c := indices[triangle + 2]
		var ab := uv[b] - uv[a]
		var ac := uv[c] - uv[a]
		var determinant := ab.cross(ac)
		if absf(determinant) <= 1e-12:
			continue
		var relative := at_uv - uv[a]
		var wb := relative.cross(ac) / determinant
		var wc := ab.cross(relative) / determinant
		if wb >= -1e-6 and wc >= -1e-6 and wb + wc <= 1.000001:
			return card.to_global(vertices[a] * (1.0 - wb - wc) + vertices[b] * wb + vertices[c] * wc)
	return Vector3(INF, INF, INF)

func _frame_bounds(wildlife: Node3D) -> Array[Rect2]:
	var source: Image = wildlife.dragon_texture.get_image()
	if source.is_compressed():
		assert(source.decompress() == OK)
	var bounds: Array[Rect2] = []
	for frame: Rect2 in wildlife.dragon_frames:
		var low := frame.end
		var high := frame.position
		for y in range(int(frame.position.y), int(frame.end.y)):
			for x in range(int(frame.position.x), int(frame.end.x)):
				if source.get_pixel(x, y).a > 0.22:
					low = low.min(Vector2(x, y))
					high = high.max(Vector2(x + 1, y + 1))
		bounds.append(Rect2((low - frame.position) / frame.size, (high - low) / frame.size))
		var body: Vector2 = wildlife.DRAGON_ART.BODIES[bounds.size() - 1]
		var canvas_low: Vector2 = low - body + wildlife.DRAGON_ART.PIVOT
		var canvas_high: Vector2 = high - body + wildlife.DRAGON_ART.PIVOT
		assert(canvas_low.x > 1 and canvas_low.y > 1 and canvas_high.x < wildlife.DRAGON_ART.CANVAS.x - 1 and canvas_high.y < wildlife.DRAGON_ART.CANVAS.y - 1,
			"Registered canvas must contain every wingtip in all 32 poses")
	assert(bounds.size() == 32)
	return bounds

func _projected_bounds(scene: Node3D, wildlife: Node3D, alpha_rect: Rect2, frame_index: int) -> Rect2:
	var card: MeshInstance3D = wildlife.dragon
	var bank: float = card.material_override.get_shader_parameter("sprite_bank")
	var frame: Rect2 = wildlife.dragon_frames[frame_index]
	var body: Vector2 = wildlife.DRAGON_ART.BODIES[frame_index]
	var low := Vector2(INF, INF)
	var high := Vector2(-INF, -INF)
	for uv: Vector2 in [alpha_rect.position, Vector2(alpha_rect.end.x, alpha_rect.position.y),
		alpha_rect.end, Vector2(alpha_rect.position.x, alpha_rect.end.y)]:
		var source_pixel := frame.position + uv * frame.size
		var offset: Vector2 = (source_pixel - body) * Vector2(1, -1) * wildlife.DRAGON_PIXEL_SCALE
		offset = offset.rotated(bank)
		var world: Vector3 = card.position + scene.camera.global_basis.x * offset.x + scene.camera.global_basis.y * offset.y
		var view_point: Vector3 = scene.camera.global_transform.affine_inverse() * world
		deepest_vertex = maxf(deepest_vertex, -view_point.z)
		assert(-view_point.z > scene.camera.near and -view_point.z < scene.camera.far - 2.0,
			"Projected sky coordinates are insufficient: the dragon must also be inside the camera's clipping planes")
		var screen: Vector2 = scene.camera.unproject_position(world) / root.get_visible_rect().size
		low = low.min(screen)
		high = high.max(screen)
	return Rect2(low, high - low)

func _clearance(skyline: PackedFloat32Array, bounds: Rect2) -> float:
	var top := 1.0
	var first := clampi(floori(bounds.position.x * SKY_COLUMNS) - 2, 0, SKY_COLUMNS - 1)
	var last := clampi(ceili(bounds.end.x * SKY_COLUMNS) + 2, 0, SKY_COLUMNS - 1)
	for x in range(first, last + 1):
		top = minf(top, skyline[x])
	return top - bounds.end.y
