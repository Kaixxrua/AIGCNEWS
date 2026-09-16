extends RefCounted
## One small, solid crossing. Timbers are unique pieces of this single asset.

const WOOD = preload("res://assets/materials/bridge-oak-v39.png")
const SHADER = preload("res://shaders/meadow_wood.gdshader")
var vertices := PackedVector3Array()
var normals := PackedVector3Array()
var uvs := PackedVector2Array()
var colors := PackedColorArray()
var rng := RandomNumberGenerator.new()
var left_x: float
var right_x: float
var deck_y: float
var river_z: float

func build(scene: Node3D) -> MeshInstance3D:
	rng.seed = 390081
	river_z = scene.BRIDGE_Z
	var center: float = scene.river_center(river_z)
	var half: float = scene.river_half_width(river_z)
	left_x = center - half - 1.8
	right_x = center + half + 1.8
	deck_y = maxf(scene.terrain_height(left_x, river_z), scene.terrain_height(right_x, river_z)) + 0.28
	var span := right_x - left_x
	var boards := ceili(span / 0.43)
	for i in range(boards):
		var x := lerpf(left_x, right_x, (i + 0.5) / boards)
		_box(Vector3(x, height_at(x) - 0.09, river_z), Vector3(span / boards - 0.022, 0.18, rng.randf_range(2.96, 3.08)), Basis.IDENTITY, rng.randf_range(0.82, 1.12))
	for side in [-1.0, 1.0]:
		var z: float = river_z + side * 1.34
		for i in range(10):
			var x := lerpf(left_x, right_x, i / 9.0)
			_box(Vector3(x, height_at(x) + 0.52, z), Vector3(0.18, 1.24, 0.18), Basis.IDENTITY, rng.randf_range(0.74, 1.05))
			if i == 9:
				continue
			var next_x := lerpf(left_x, right_x, (i + 1.0) / 9.0)
			for elevation in [0.43, 1.03, -0.32]:
				_beam(Vector3(x, height_at(x) + elevation, z), Vector3(next_x, height_at(next_x) + elevation, z), 0.12 if elevation > 0.0 else 0.24)
		for t in [0.23, 0.76]:
			var x := lerpf(left_x, right_x, t)
			var top := height_at(x) - 0.16
			_box(Vector3(x, (top - 1.8) * 0.5, z), Vector3(0.28, top + 1.8, 0.30), Basis.IDENTITY, 0.74)
	# Short graded entries meet the real bank instead of floating above it.
	var entries: Array[Dictionary] = []
	for side in [-1.0, 1.0]:
		var end_x := left_x if side < 0.0 else right_x
		var entry_length := 4.0
		while entry_length < 8.0:
			var bank_y: float = scene.terrain_height(end_x + side * entry_length, river_z) + 0.055
			if absf(deck_y - bank_y) / entry_length <= tan(deg_to_rad(15.0)):
				break
			entry_length += 0.5
		var ground_x: float = end_x + side * entry_length
		var ground_y: float = scene.terrain_height(ground_x, river_z) + 0.055
		var entry_boards := ceili(entry_length / 0.40)
		var slope := (ground_y - deck_y) / (ground_x - end_x)
		var angle := atan(slope)
		var basis := Basis(Vector3.BACK, angle)
		for i in range(entry_boards):
			var t := (i + 0.5) / float(entry_boards)
			var top := Vector3(lerpf(end_x, ground_x, t), lerpf(deck_y, ground_y, t), river_z)
			_box(top - basis.y * 0.08, Vector3(entry_length / entry_boards / cos(angle) - 0.018, 0.16, 2.98),
				basis, rng.randf_range(0.82, 1.05))
		entries.append({"start_x": end_x, "ground_x": ground_x, "ground_y": ground_y, "boards": entry_boards})
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_COLOR] = colors
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var bridge := MeshInstance3D.new()
	bridge.name = "SmallMeadowFootbridge"
	bridge.mesh = mesh
	var material := ShaderMaterial.new()
	material.shader = SHADER
	material.set_shader_parameter("wood_texture", WOOD)
	bridge.material_override = material
	scene.add_child(bridge)
	bridge.create_trimesh_collision()
	bridge.set_meta("left_x", left_x)
	bridge.set_meta("right_x", right_x)
	bridge.set_meta("deck_y", deck_y)
	bridge.set_meta("entries", entries)
	print("MEADOW_BRIDGE_READY: one %.2f m crossing, 3 m wide; real deck collision and sun shadows" % span)
	return bridge

func height_at(x: float) -> float:
	var t := inverse_lerp(left_x, right_x, x)
	return deck_y + 0.42 * sin(t * PI)

func _beam(a: Vector3, b: Vector3, thickness: float) -> void:
	var direction := b - a
	_box((a + b) * 0.5, Vector3(direction.length() + 0.08, thickness, thickness),
		Basis(Vector3.BACK, atan2(direction.y, direction.x)), rng.randf_range(0.76, 1.02))

func _box(center: Vector3, size: Vector3, basis: Basis, tone: float) -> void:
	var corners: Array[Vector3] = []
	for i in range(8):
		corners.append(Vector3(0.5 if i & 1 else -0.5, 0.5 if i & 2 else -0.5, 0.5 if i & 4 else -0.5) * size)
	for indices in [[0, 4, 6, 2], [1, 3, 7, 5], [0, 1, 5, 4], [2, 6, 7, 3], [0, 2, 3, 1], [4, 5, 7, 6]]:
		var a := corners[indices[0]]
		var b := corners[indices[1]]
		var c := corners[indices[2]]
		var d := corners[indices[3]]
		var n := (b - a).cross(c - a).normalized()
		if n.dot(a) < 0.0:
			n = -n
			var temp := b
			b = d
			d = temp
		for p: Vector3 in [a, c, b, a, d, c]:
			vertices.append(center + basis * p)
			normals.append(basis * n)
			var along := p.x if size.x > size.z else p.z
			var across := p.z if size.x > size.z else p.x
			if absf(n.y) < 0.5:
				across = p.y
			uvs.append(Vector2(across / 0.7 + center.x * 0.19, along / 2.4 + center.z * 0.31))
			colors.append(Color(tone, tone, tone, 1.0))
