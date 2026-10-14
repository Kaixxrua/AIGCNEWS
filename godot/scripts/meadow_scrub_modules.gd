extends RefCounted
## Six distinct plant-only cutouts; painted prop stones become solid geology.
const TEXTURE = preload("res://assets/foliage/meadow-scrub-v74.png")
const HERBS = preload("res://scripts/meadow_herb_modules.gd")
const GEOLOGY = preload("res://scripts/meadow_detail_builder.gd")
const CROPS := [Rect2i(19, 41, 484, 389), Rect2i(536, 90, 613, 337),
	Rect2i(1161, 126, 599, 299), Rect2i(29, 485, 508, 363),
	Rect2i(595, 459, 510, 394), Rect2i(1165, 564, 591, 285)]
const NAMES := ["GoldenGrasses", "RiverRoseThicket", "FernAndStone", "DistantOakScrub", "BankReeds", "TerraceHeather"]
const FEET := [Vector2(-4, 13), Vector2(44, -21), Vector2(15, -1),
	Vector2(68, -59), Vector2(23, -30), Vector2(-17, 3)]
const WIDTHS := [1.8, 3.0, 3.4, 4.1, 1.6, 3.1]
const BASAL_BAND := 0.87

static func build_plants(scene: Node3D) -> void:
	var source := TEXTURE.get_image()
	var size := Vector2(source.get_size())
	var soil: TriangleMesh = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	for i in range(NAMES.size()):
		var crop: Rect2i = CROPS[i]
		var region := Rect2(Vector2(crop.position) / size, Vector2(crop.size) / size)
		# Keep native width and ordering. The fern's former foot intruded into the
		# road, so only this plant and its separate stones move toward the bank.
		var plant: MeshInstance3D = scene._art(NAMES[i], TEXTURE, FEET[i], WIDTHS[i],
			Vector2(0.5, 0.975), -0.025, Color(0.94, 0.97, 0.88), true, region)
		var material: ShaderMaterial = plant.material_override
		if i == 2:
			# Previously generated low grass remains useful along the road edge;
			# relocation must not reseed all later undergrowth in the large batch.
			plant.set_meta("seam_sampling_foot", Vector2(12, -1))
			plant.set_meta("groundcover_sampling_foot", Vector2(12, -1))
		material.set_shader_parameter("edge_inset", 0.35)
		material.set_shader_parameter("relief_strength", 0.20)
		material.set_shader_parameter("art_contrast", 1.07)
		material.set_shader_parameter("art_exposure", 0.94)
		material.set_shader_parameter("wind_strength", 0.075 if i == 0 or i == 4 else 0.06)
		material.set_shader_parameter("rooted_herb", true)
		HERBS._conform(scene, plant, crop, source, BASAL_BAND, soil)
		plant.set_meta("scrub_module", i)
		scene._shadow(FEET[i], Vector2(WIDTHS[i] * 0.48, WIDTHS[i] * 0.27))

static func build_stones(scene: Node3D) -> void:
	# New small support rocks use the same solid stone generator/material as the
	# landscape, with an independent seed. None is a painted stone on a leaf card.
	var geology := GEOLOGY.new()
	geology.meadow = scene
	geology.random.seed = 740911
	var groups := [2, 2, 2, 3, 3, 4, 5, 5]
	# Measured gaps preserve existing low cover, prop-seam roots and new basal
	# shoots. These offsets are not random retries performed during startup.
	var offsets := [Vector2(-0.7, -0.45), Vector2(0.25, 0.55), Vector2(0.96, 0.05),
		Vector2(-1.2, -0.15), Vector2(0.25, 0.9), Vector2(-0.52, -0.2),
		Vector2(-0.75, -1.15), Vector2(-1.6, -0.7)]
	var sizes := [Vector3(1.1, 0.52, 0.7), Vector3(0.72, 0.38, 0.5), Vector3(0.65, 0.4, 0.45),
		Vector3(1.0, 0.6, 0.7), Vector3(0.7, 0.38, 0.6), Vector3(0.75, 0.4, 0.55),
		Vector3(1.0, 0.5, 0.7), Vector3(0.65, 0.35, 0.6)]
	var centers := PackedVector3Array()
	var obstacles := PackedVector3Array()
	var ranges := PackedVector2Array()
	for i in range(groups.size()):
		var p: Vector2 = FEET[groups[i]] + offsets[i]
		var center := Vector3(p.x, scene.terrain_height(p.x, p.y) + 0.07, p.y)
		var start: int = geology.vertices.size()
		geology._rock(center, sizes[i], 0.73 + i * 1.91, false)
		ranges.append(Vector2(start, geology.vertices.size() - start))
		centers.append(center)
		obstacles.append(Vector3(p.x, p.y, maxf(sizes[i].x, sizes[i].z) * 0.56))
	# Vertex IDs restart in this independent mesh. Do not inherit the terrain's
	# prefix-specific baked AO/plane tags or mutate its shared material instance.
	var material: ShaderMaterial = scene.get_node("SolidLimestoneGeology").material_override.duplicate()
	material.set_shader_parameter("rock_ao_vertex_count", 0)
	var stones: MeshInstance3D = geology._publish("ScrubStoneSupports", material, true)
	stones.create_trimesh_collision()
	stones.set_meta("scrub_stone_centers", centers)
	stones.set_meta("scrub_stone_ranges", ranges)
	stones.set_meta("scrub_stone_obstacles", obstacles)
	stones.set_meta("scrub_stone_groups", groups)
	print("MEADOW_SCRUB_READY: six unique plant-only cutouts; eight independent solid support rocks; native proportions and shared lighting")
