extends Node3D

## Reusable first-pass hero environment asset:
## a grassy terrace with a rocky face, path interface, and river edge.

const GRASS_TEXTURE: Texture2D = preload("res://assets/materials/grass-meadow-v2.png")
const STONE_TEXTURE: Texture2D = preload("res://assets/materials/stone-cliff-v2.png")

var rng := RandomNumberGenerator.new()
var stone_palette: Array[Color] = [
	Color(0.28, 0.25, 0.20),
	Color(0.38, 0.34, 0.27),
	Color(0.47, 0.40, 0.30),
	Color(0.55, 0.48, 0.35),
]
var grass_palette: Array[Color] = [
	Color(0.22, 0.38, 0.12),
	Color(0.30, 0.49, 0.15),
	Color(0.39, 0.56, 0.18),
	Color(0.52, 0.63, 0.22),
]

func _ready() -> void:
	rng.seed = 240519
	_build_asset()

func _build_asset() -> void:
	var terrain := _group("Terrain")
	var dressing := _group("Dressing")

	# The module has a thick, readable silhouette instead of a flat ground plane.
	_add_box(terrain, "RockyBase", Vector3(7.8, 1.6, 5.8), Vector3(-1.2, -0.72, 0.0), Color(0.76, 0.66, 0.50), 0.96, Vector3.ZERO, STONE_TEXTURE)
	_add_box(terrain, "GrassTop", Vector3(7.55, 0.42, 5.55), Vector3(-1.2, 0.30, 0.0), Color(0.30, 0.48, 0.14), 0.92)
	_add_box(terrain, "GrassTopLight", Vector3(7.25, 0.045, 5.22), Vector3(-1.2, 0.535, -0.03), Color.WHITE, 0.95, Vector3.ZERO, GRASS_TEXTURE)

	# Two irregular stone courses establish the cliff face and its scale.
	_add_stone_course(terrain, 2.86, -0.72, 12, 0.42)
	_add_stone_course(terrain, 2.91, -1.28, 11, 0.38)
	_add_side_stones(terrain, 2.68, -0.72, 7)

	# The path is made from shallow, varied slabs so it remains a real surface.
	var path := _group("Path")
	for index in range(8):
		var z := 2.05 - float(index) * 0.72
		var width := 1.15 + float(index) * 0.12
		var x := -1.62 + sin(float(index) * 0.75) * 0.22
		var slab_color := Color(0.47, 0.31, 0.16).lerp(Color(0.68, 0.46, 0.23), float(index % 3) / 2.0)
		_add_box(path, "PathSlab_%02d" % index, Vector3(width, 0.075, 0.64), Vector3(x, 0.57, z), slab_color, 0.98, Vector3(0.0, rng.randf_range(-0.08, 0.08), rng.randf_range(-0.035, 0.035)))

	# A few exposed stones break up the otherwise broad grassy top.
	for index in range(16):
		var position := Vector3(
			rng.randf_range(-4.55, 2.05),
			0.62,
			rng.randf_range(-2.25, 2.25)
		)
		if abs(position.x + 1.6) < 1.0 and position.z > -2.0:
			continue
		_add_rock(dressing, "LooseRock_%02d" % index, position, rng.randf_range(0.10, 0.26), stone_palette[rng.randi_range(0, stone_palette.size() - 1)])

	# Grass tufts provide the hand-authored edge rhythm visible in the reference.
	for index in range(44):
		var tuft_position := Vector3(
			rng.randf_range(-4.6, 2.0),
			0.62,
			rng.randf_range(-2.35, 2.35)
		)
		if abs(tuft_position.x + 1.6) < 0.95 and tuft_position.z > -1.8:
			continue
		_add_grass_tuft(dressing, "GrassTuft_%02d" % index, tuft_position)

	# Water sits lower than the terrace, leaving a readable rocky bank between them.
	var water := _make_material(Color(0.08, 0.34, 0.54), 0.22, 0.08)
	_add_plane(terrain, "River", Vector2(3.35, 6.8), Vector3(3.65, 0.10, -0.18), water)
	for index in range(12):
		var ripple_z := -2.75 + float(index) * 0.50
		var ripple_x := 3.10 + sin(float(index) * 1.7) * 0.48
		_add_box(terrain, "WaterHighlight_%02d" % index, Vector3(rng.randf_range(0.22, 0.65), 0.012, 0.025), Vector3(ripple_x, 0.125, ripple_z), Color(0.56, 0.78, 0.78), 0.22, Vector3(0.0, rng.randf_range(-0.20, 0.20), 0.0))

	# A low bank on the river side makes the water read as a cut in the terrain.
	for index in range(9):
		var bank_z := -2.50 + float(index) * 0.58
		_add_rock(terrain, "RiverBankRock_%02d" % index, Vector3(2.58 + rng.randf_range(-0.08, 0.10), 0.22, bank_z), rng.randf_range(0.18, 0.34), stone_palette[rng.randi_range(1, stone_palette.size() - 1)])

func _group(group_name: String) -> Node3D:
	var node := Node3D.new()
	node.name = group_name
	add_child(node)
	return node

func _make_material(color: Color, roughness: float, metallic: float = 0.0, texture: Texture2D = null) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	material.metallic = metallic
	if texture != null:
		material.albedo_texture = texture
	return material

func _add_box(parent: Node3D, node_name: String, size: Vector3, position: Vector3, color: Color, roughness: float, rotation: Vector3 = Vector3.ZERO, texture: Texture2D = null) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = position
	instance.rotation = rotation
	instance.material_override = _make_material(color, roughness, 0.0, texture)
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	parent.add_child(instance)
	return instance

func _add_plane(parent: Node3D, node_name: String, size: Vector2, position: Vector3, material: Material) -> MeshInstance3D:
	var mesh := PlaneMesh.new()
	mesh.size = size
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = position
	instance.material_override = material
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	parent.add_child(instance)
	return instance

func _add_stone_course(parent: Node3D, front_z: float, y: float, count: int, depth: float) -> void:
	var start_x := -4.85
	for index in range(count):
		var width := rng.randf_range(0.48, 0.86)
		var height := rng.randf_range(0.34, 0.60)
		var x := start_x + float(index) * 0.82 + rng.randf_range(-0.09, 0.09)
		_add_box(parent, "FrontStone_%02d_%0.2f" % [index, y], Vector3(width, height, depth), Vector3(x, y, front_z + rng.randf_range(-0.04, 0.04)), Color(0.82, 0.72, 0.56), 0.96, Vector3(rng.randf_range(-0.06, 0.06), rng.randf_range(-0.09, 0.09), rng.randf_range(-0.06, 0.06)), STONE_TEXTURE)

func _add_side_stones(parent: Node3D, side_x: float, y: float, count: int) -> void:
	for index in range(count):
		var z := -2.35 + float(index) * 0.76
		_add_box(parent, "SideStone_%02d" % index, Vector3(0.45, rng.randf_range(0.36, 0.64), 0.62), Vector3(side_x, y + rng.randf_range(-0.12, 0.14), z), Color(0.82, 0.72, 0.56), 0.96, Vector3(rng.randf_range(-0.06, 0.06), rng.randf_range(-0.10, 0.10), rng.randf_range(-0.05, 0.05)), STONE_TEXTURE)

func _add_rock(parent: Node3D, node_name: String, position: Vector3, radius: float, color: Color) -> MeshInstance3D:
	var mesh := SphereMesh.new()
	mesh.radius = radius
	mesh.height = radius * 1.55
	mesh.radial_segments = 7
	mesh.rings = 4
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = position
	instance.scale = Vector3(1.0, rng.randf_range(0.55, 0.90), rng.randf_range(0.75, 1.15))
	instance.rotation_degrees = Vector3(rng.randf_range(-12.0, 12.0), rng.randf_range(0.0, 360.0), rng.randf_range(-12.0, 12.0))
	instance.material_override = _make_material(color, 0.98)
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	parent.add_child(instance)
	return instance

func _add_grass_tuft(parent: Node3D, node_name: String, position: Vector3) -> void:
	var tuft := Node3D.new()
	tuft.name = node_name
	tuft.position = position
	parent.add_child(tuft)
	for blade_index in range(3):
		var blade := _add_box(tuft, "Blade_%02d" % blade_index, Vector3(0.045, rng.randf_range(0.24, 0.42), 0.10), Vector3(rng.randf_range(-0.08, 0.08), rng.randf_range(0.10, 0.18), rng.randf_range(-0.04, 0.04)), grass_palette[rng.randi_range(0, grass_palette.size() - 1)], 0.96)
		blade.rotation_degrees = Vector3(rng.randf_range(-18.0, 18.0), rng.randf_range(0.0, 360.0), rng.randf_range(-18.0, 18.0))
