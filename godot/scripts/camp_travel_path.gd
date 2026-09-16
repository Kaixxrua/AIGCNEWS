extends RefCounted
## Pure, bounded scene-local XZ planner. Call on a target/obstacle change, NOT
## every frame. Callbacks must describe one stable terrain/obstacle snapshot:
## sample_ground(Vector2) -> finite Vector3 with matching X/Z, and
## permitted(Vector2) -> bool using camp_pack_host's river/prop/stone checks
## and terrain normal.y >= 0.94 (NOT wildlife's arena-excluding predicate).
## No movement, clock, I/O, RNG, HP or world state is owned here.
##
## Footprints are FILLED discs: radial and perimeter spacing <= 0.20m, at
## every <= 0.20m along each segment. Like the renderer, this is a sampled
## safety contract, not continuous collision detection for arbitrary sub-grid
## predicates. The host's existing obstacle clearance is retained unchanged.
## All probes stay in the UNION of the five approved 4.2m clearings, never in
## a single old arena and never in the rectangle's unapproved outer corners.
## An empty result means unsafe, unreachable at this resolution, or budget
## exhausted; the owner must wait/replan, never teleport. Equal endpoints
## return one validated point. Otherwise the exact input endpoints are kept.

const Layout := preload("camp_spawn_layout.gd")
const ARENA_RADIUS := 4.2
const SAMPLE_STEP := 0.20
const GRID_STEP := 0.60
const GRID_ORIGIN := Vector2(-2.2, -19.2)
const GRID_SIDE := 25 # [-2.2, 12.2] x [-19.2, -4.8]; probes still test union.
const MAX_NODES := GRID_SIDE * GRID_SIDE
const MAX_SUPPORT_PROBES := 65536 # Each calls permitted/sample at most once.
const MAX_RADIUS := 2.4 # Largest allowed source shadowRadius * display scale.
const SMOOTH_LOOKAHEAD := 8
const NEIGHBOURS: Array[Vector2i] = [Vector2i(-1, 0), Vector2i(0, -1),
	Vector2i(1, 0), Vector2i(0, 1), Vector2i(-1, -1), Vector2i(1, -1),
	Vector2i(1, 1), Vector2i(-1, 1)]

static func find_path(start: Vector2, finish: Vector2, radius: float,
		sample_ground: Callable, permitted: Callable) -> PackedVector2Array:
	if not start.is_finite() or not finish.is_finite() or not is_finite(radius) \
			or radius < 0.0 or radius > MAX_RADIUS \
			or not sample_ground.is_valid() or not permitted.is_valid():
		return PackedVector2Array()
	return Search.new(radius, sample_ground, permitted).solve(start, finish)

class Search extends RefCounted:
	var _ground: Callable
	var _permitted: Callable
	var _radius: float
	var _offsets := PackedVector2Array([Vector2.ZERO])
	var _supports: Dictionary = {}
	var _points: Dictionary = {}
	var _probes := 0
	var _exhausted := false

	func _init(radius: float, ground: Callable, permitted: Callable) -> void:
		_radius = radius
		_ground = ground
		_permitted = permitted
		var rings := ceili(radius / SAMPLE_STEP)
		for ring in range(1, rings + 1):
			var distance := radius * float(ring) / rings
			# Multiples of eight include the renderer's cardinal probes as well
			# as diagonal/interior support; no centre-plus-four-points shortcut.
			var count := maxi(8, ceili(TAU * distance / SAMPLE_STEP / 8.0) * 8)
			for index in range(count):
				_offsets.append(Vector2.from_angle(TAU * index / count) * distance)

	func _inside(point: Vector2) -> bool:
		for centre: Vector2 in Layout.CENTRES:
			if point.distance_squared_to(centre) <= ARENA_RADIUS * ARENA_RADIUS:
				return true
		return false

	func _support(point: Vector2) -> Variant:
		if _supports.has(point):
			return _supports[point]
		if _exhausted or not _inside(point):
			return null
		if _probes >= MAX_SUPPORT_PROBES:
			_exhausted = true
			return null
		_probes += 1
		var allowed: Variant = _permitted.call(point)
		var result: Variant = null
		if allowed is bool and allowed:
			var sampled: Variant = _ground.call(point)
			if sampled is Vector3 and sampled.is_finite() \
					and absf(sampled.x - point.x) <= 0.001 and absf(sampled.z - point.y) <= 0.001:
				result = sampled
		_supports[point] = result
		return result

	func _safe_point(point: Vector2) -> bool:
		if _points.has(point):
			return _points[point]
		var centre: Variant = _support(point)
		var safe: bool = centre != null
		if safe:
			for offset: Vector2 in _offsets:
				var surface: Variant = _support(point + offset)
				if surface == null or absf(surface.y - centre.y) > maxf(0.08, _radius * 0.32):
					safe = false
					break
		_points[point] = safe
		return safe

	func _segment(start: Vector2, finish: Vector2) -> bool:
		var steps := maxi(1, ceili(start.distance_to(finish) / SAMPLE_STEP))
		var previous: Variant = null
		for index in range(steps + 1):
			var point := start.lerp(finish, float(index) / steps)
			if not _safe_point(point):
				return false
			var surface: Vector3 = _supports[point]
			# Also reject abrupt steps between footprint samples, including a
			# zero-radius caller. Smooth slopes still use the host normal guard.
			if previous != null and absf(surface.y - previous.y) > maxf(0.08,
					start.distance_to(finish) / steps * 0.32):
				return false
			previous = surface
		return true

	func _world(cell: Vector2i) -> Vector2:
		return GRID_ORIGIN + Vector2(cell) * GRID_STEP

	func _cell_valid(cell: Vector2i) -> bool:
		return cell.x >= 0 and cell.y >= 0 and cell.x < GRID_SIDE and cell.y < GRID_SIDE

	func solve(start: Vector2, finish: Vector2) -> PackedVector2Array:
		if not _safe_point(start) or not _safe_point(finish):
			return PackedVector2Array()
		if start == finish:
			return PackedVector2Array([start])
		if _segment(start, finish):
			return PackedVector2Array([start, finish])
		var open: Array[Vector2i] = []
		var costs: Dictionary = {}
		var parents: Dictionary = {}
		var closed: Dictionary = {}
		var nearest := Vector2i(((start - GRID_ORIGIN) / GRID_STEP).round())
		# Exact endpoints connect through independently checked local segments,
		# never snap the actor to a grid cell or silently alter its destination.
		for y in range(-1, 2):
			for x in range(-1, 2):
				var cell := nearest + Vector2i(x, y)
				if _cell_valid(cell) and _segment(start, _world(cell)):
					open.append(cell)
					costs[cell] = start.distance_to(_world(cell))
					parents[cell] = cell
		while not open.is_empty() and closed.size() < MAX_NODES and not _exhausted:
			# At most 625 nodes: a stable linear min scan is bounded and avoids
			# a heap/decrease-key subsystem for this tiny one-off local route.
			var best := 0
			var best_score := INF
			for index in range(open.size()):
				var score: float = costs[open[index]] + _world(open[index]).distance_to(finish)
				if score < best_score:
					best = index
					best_score = score
			var cell: Vector2i = open[best]
			open.remove_at(best)
			closed[cell] = true
			var point := _world(cell)
			if point.distance_to(finish) <= GRID_STEP * 1.75 and _segment(point, finish):
				return _simplify(_reconstruct(cell, parents, start, finish))
			for direction: Vector2i in NEIGHBOURS:
				var next := cell + direction
				if not _cell_valid(next) or closed.has(next):
					continue
				var cost: float = costs[cell] + point.distance_to(_world(next))
				if costs.has(next) and costs[next] <= cost:
					continue
				if not _segment(point, _world(next)):
					continue
				if not costs.has(next):
					open.append(next)
				costs[next] = cost
				parents[next] = cell
		return PackedVector2Array()

	func _reconstruct(cell: Vector2i, parents: Dictionary, start: Vector2,
			finish: Vector2) -> PackedVector2Array:
		var reverse := PackedVector2Array([finish])
		for _index in range(MAX_NODES):
			var point := _world(cell)
			if reverse[-1] != point:
				reverse.append(point)
			if parents[cell] == cell:
				if reverse[-1] != start:
					reverse.append(start)
				reverse.reverse()
				return reverse
			cell = parents[cell]
		return PackedVector2Array()

	func _simplify(path: PackedVector2Array) -> PackedVector2Array:
		if path.is_empty():
			return path
		var result := PackedVector2Array([path[0]])
		var cursor := 0
		while cursor < path.size() - 1 and not _exhausted:
			var next := mini(cursor + SMOOTH_LOOKAHEAD, path.size() - 1)
			while next > cursor + 1 and not _segment(path[cursor], path[next]):
				next -= 1
			result.append(path[next]) # Adjacent fallback was already validated.
			cursor = next
		return PackedVector2Array() if _exhausted else result
