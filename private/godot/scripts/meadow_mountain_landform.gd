extends RefCounted
## Finite mountain-foot slopes in the existing continuous terrain, not a new card.
## The village (-170), castle foundation and all playable/river land stay unchanged.

static func _mound(p: Vector2, centre: Vector2, radius: Vector2) -> float:
	var q := (p - centre) / radius
	return 1.0 - smoothstep(0.0, 1.0, q.length_squared())

static func height_offset(x: float, z: float) -> float:
	if z >= -225.0 or z <= -327.0:
		return 0.0
	var p := Vector2(x, z)
	var slopes := 8.0 * _mound(p, Vector2(-213.0, -291.0), Vector2(69.0, 47.0))
	slopes += 11.0 * _mound(p, Vector2(-137.0, -286.0), Vector2(56.0, 45.0))
	slopes += 7.0 * _mound(p, Vector2(-66.0, -293.0), Vector2(43.0, 48.0))
	slopes += 5.5 * _mound(p, Vector2(221.0, -289.0), Vector2(40.0, 43.0))
	# Leave the castle's entire x footprint and the open central valley alone.
	var left := 1.0 - smoothstep(-44.0, -24.0, x)
	var right := smoothstep(166.0, 187.0, x)
	var ends := smoothstep(-327.0, -312.0, z) * (1.0 - smoothstep(-250.0, -225.0, z))
	# Low rolling shoulders, not tall smooth plinths beneath the mountain art.
	return slopes * 0.55 * maxf(left, right) * ends
