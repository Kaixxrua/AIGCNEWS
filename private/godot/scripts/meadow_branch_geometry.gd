extends RefCounted
## Individually authored folded leaves/twigs, shared by two depth bands.
## No repeated image cards or closed green mound shells.
var vertices := PackedVector3Array()
var normals := PackedVector3Array()
var colours := PackedColorArray()
var uvs := PackedVector2Array()
var fields := PackedVector2Array()
var scene: Node3D
var density_override := -1.0

func leaf(origin: Vector3, length: Vector3, width: float, tone: float, wind_scale: float = 1.0) -> void:
	var side := Vector3(-length.z, 0, length.x).normalized() * width
	var ridge := origin + length * 0.46 + Vector3.UP * width * 0.38
	var outline := [origin, origin + length * 0.31 - side, origin + length * 0.72 - side * 0.75,
		origin + length, origin + length * 0.72 + side * 0.75, origin + length * 0.31 + side]
	var axis := side.cross(length).normalized()
	if axis.y < 0.0:
		axis = -axis
	axis = axis.lerp(Vector3.UP, 0.28).normalized()
	for i in range(6):
		var a: Vector3 = outline[i]
		var b: Vector3 = outline[(i + 1) % 6]
		var na: Vector3 = (axis + (a - ridge).normalized() * 0.12).normalized()
		var nb: Vector3 = (axis + (b - ridge).normalized() * 0.12).normalized()
		var wa := (0.0 if i == 0 else 0.65) * wind_scale
		var wb := (0.0 if i == 5 else 0.65) * wind_scale
		# Clockwise fronts on both depth tiers, including their shadow geometry.
		if (ridge - a).cross(b - a).dot(axis) < 0.0:
			_vertex(a, na, tone, wa, false)
			_vertex(ridge, axis, tone * 1.02, wind_scale, false)
			_vertex(b, nb, tone, wb, false)
		else:
			_vertex(a, na, tone, wa, false)
			_vertex(b, nb, tone, wb, false)
			_vertex(ridge, axis, tone * 1.02, wind_scale, false)

func twig(a: Vector3, b: Vector3, width: float, tone: float) -> void:
	for axis: Vector3 in [Vector3.RIGHT, Vector3.FORWARD]:
		var side := axis * width
		var normal := -side.cross(b - a).normalized()
		# The midpoint of the first two corners is the exact measured soil root.
		for p: Vector3 in [a - side, a + side, b, b, a + side, b + side * 0.35]:
			_vertex(p, normal, tone, 0.0, true)

func _vertex(p: Vector3, normal: Vector3, tone: float, wind: float, wood: bool) -> void:
	vertices.append(p)
	normals.append(normal)
	colours.append(Color(tone, tone, tone, wind))
	uvs.append(Vector2(-2000, 0) if wood else Vector2(p.x, p.z))
	var density: float = density_override if density_override >= 0.0 else scene.growth_density(Vector2(p.x, p.z))
	fields.append(Vector2(density, 0))

func mesh() -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_COLOR] = colours
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_TEX_UV2] = fields
	var result := ArrayMesh.new()
	result.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return result
