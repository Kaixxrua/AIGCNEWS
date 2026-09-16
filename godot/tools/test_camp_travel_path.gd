extends SceneTree
## Isolated synthetic sampler tests only; no renderer, world, images or PCK.
const Planner := preload("res://camp_presentation/camp_travel_path.gd")
var checks := 0
var failures := 0
var maximum_probes := 0

class Terrain extends RefCounted:
	var obstacles: Array[Rect2] = []
	var clearance := 0.10 # Existing camp_pack_host obstacle predicate margin.
	var grade := 0.0
	var step := false
	var allowed_override: Variant = null
	var malformed := ""
	var allowed_calls := 0
	var ground_calls := 0
	var capture := false
	var probes := PackedVector2Array()

	func permitted(point: Vector2) -> Variant:
		allowed_calls += 1
		if capture:
			probes.append(point)
		if allowed_override != null:
			return allowed_override
		# Same threshold as the actual bootstrap predicate; the planner must
		# query it for the entire footprint, not only the path centre.
		if Vector3(-grade, 1, 0).normalized().y < 0.94:
			return false
		for obstacle: Rect2 in obstacles:
			if obstacle.grow(clearance).has_point(point):
				return false
		return true

	func ground(point: Vector2) -> Variant:
		ground_calls += 1
		match malformed:
			"number": return 0.0
			"boolean": return true
			"string": return "ground"
			"nan": return Vector3(point.x, NAN, point.y)
			"inf": return Vector3(point.x, INF, point.y)
			"x": return Vector3(point.x + 0.002, 0, point.y)
			"z": return Vector3(point.x, 0, point.y + 0.002)
		return Vector3(point.x, point.x * grade + (0.4 if step and point.x > 5.0 else 0.0), point.y)

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func route(world: Terrain, start: Vector2, finish: Vector2, radius: float) -> PackedVector2Array:
	var allowed_before := world.allowed_calls
	var ground_before := world.ground_calls
	var result := Planner.find_path(start, finish, radius, world.ground, world.permitted)
	var probes := world.allowed_calls - allowed_before
	maximum_probes = maxi(maximum_probes, probes)
	check(probes <= Planner.MAX_SUPPORT_PROBES, "per-call predicate work is hard bounded")
	check(world.ground_calls - ground_before <= Planner.MAX_SUPPORT_PROBES, "per-call ground work is hard bounded")
	check(result.size() <= Planner.MAX_NODES + 2, "bounded polyline output")
	if not result.is_empty():
		check(result[0] == start and result[-1] == finish, "exact safe endpoints; no grid snapping")
		for point: Vector2 in result:
			check(point.is_finite(), "returned waypoints are finite")
	return result

func verify_swept_disc(path: PackedVector2Array, radius: float, world: Terrain) -> void:
	# A separate denser CARTESIAN footprint oracle, not the implementation's
	# concentric rings. All successful obstacle fixtures have physical margin.
	var safe := not path.is_empty()
	for segment in range(1, path.size()):
		var a := path[segment - 1]
		var b := path[segment]
		var steps := maxi(1, ceili(a.distance_to(b) / 0.05))
		for index in range(steps + 1):
			var centre := a.lerp(b, float(index) / steps)
			var divisions := maxi(1, ceili(radius / 0.05))
			for row in range(-divisions, divisions + 1):
				for column in range(-divisions, divisions + 1):
					var offset := Vector2(column, row) * radius / divisions
					if offset.length_squared() > radius * radius:
						continue
					var point := centre + offset
					var in_union := false
					for site: Vector2 in Planner.Layout.CENTRES:
						in_union = in_union or point.distance_to(site) <= 4.20001
					safe = safe and in_union
					for obstacle: Rect2 in world.obstacles:
						safe = safe and not obstacle.has_point(point)
	check(safe, "independent 0.05m swept filled-disc oracle clears actual obstacles and five-site union")

func test_inputs_and_standing() -> void:
	var world := Terrain.new()
	var point := Vector2(5, -12)
	for radius in [0.0, 0.12, 0.6, 2.04, 2.4]:
		check(route(world, point, point, radius) == PackedVector2Array([point]), "coincident endpoints return one fully checked standing point")
	for radius in [-0.1, NAN, INF, 2.4001]:
		check(route(world, point, point, radius).is_empty(), "invalid scale fails closed")
	for bad in [Vector2(NAN, 0), Vector2(0, INF), Vector2(1.0e20, -12), Vector2(-2.2, -19.2)]:
		check(route(world, bad, point, 0.2).is_empty(), "invalid start or rectangle corner outside union")
		check(route(world, point, bad, 0.2).is_empty(), "invalid finish is never shortened to reachable prefix")
	check(Planner.find_path(point, point, 0.2, Callable(), world.permitted).is_empty(), "missing ground callback")
	check(Planner.find_path(point, point, 0.2, world.ground, Callable()).is_empty(), "missing predicate callback")
	world.obstacles = [Rect2(4.98, -12.02, 0.04, 0.04)]
	check(route(world, point, point, 0.2).is_empty(), "coincident unsafe endpoints do not bypass validation")

func test_direct_cross_site_and_endpoint_spacing() -> void:
	var world := Terrain.new()
	for start: Vector2 in Planner.Layout.CENTRES:
		for finish: Vector2 in Planner.Layout.CENTRES:
			var path := route(world, start, finish, 0.45)
			check(path.size() == (1 if start == finish else 2), "all five sites connect directly on clear ground; no old single-arena cap")
	var start := Vector2(0.731, -14.239)
	var finish := Vector2(7.219, -8.817)
	var path := route(world, start, finish, 0.51)
	check(path == PackedVector2Array([start, finish]), "off-grid endpoints remain byte-identical")
	check(route(world, start, start + Vector2(0.0001, 0.0), 0.51).size() == 2, "near endpoints are not silently snapped together")
	world.capture = true
	world.probes.clear()
	start = Vector2(2, -12)
	finish = Vector2(8.07, -12)
	path = route(world, start, finish, 0.0)
	check(path.size() == 2, "zero-radius path still samples the entire segment")
	var last := start.x
	var positions: Array[float] = []
	for probe: Vector2 in world.probes:
		positions.append(probe.x)
	positions.sort()
	for x: float in positions:
		check(x - last <= 0.20001, "segment probes no farther than 0.20m apart, including fractional last step")
		last = x
	check(last == finish.x, "exact final point is checked")

func test_detours_and_no_corner_cutting() -> void:
	var world := Terrain.new()
	world.obstacles = [Rect2(4.4, -13.0, 1.2, 2.0)]
	var start := Vector2(2, -12)
	var finish := Vector2(8, -12)
	var path := route(world, start, finish, 0.45)
	check(path.size() > 2, "bounded A* goes around obstruction instead of hiding/teleporting")
	verify_swept_disc(path, 0.45, world)
	check(route(world, start, finish, 0.45) == path, "repeat planning is deterministic without RNG")
	# Two corners leave a tempting diagonal line between nodes. Checking only
	# grid vertices or only cardinal spokes would intersect the real footprint.
	world.obstacles = [Rect2(4.3, -12.9, 0.45, 0.6), Rect2(5.05, -11.75, 0.45, 0.6)]
	path = route(world, start, finish, 0.35)
	check(not path.is_empty(), "safe route remains available around staggered corners")
	verify_swept_disc(path, 0.35, world)
	# A 2cm physical wall is NOT skipped between far-apart path vertices.
	# The same existing +0.10m host predicate clearance protects sub-grid props.
	world.obstacles = [Rect2(5.09, -19.3, 0.02, 14.6)]
	check(route(world, start, finish, 0.24).is_empty(), "complete thin barrier cannot be crossed anywhere in approved union")
	world.obstacles = [Rect2(5.09, -13.2, 0.02, 2.4)]
	path = route(world, start, finish, 0.24)
	check(path.size() > 2, "finite thin obstacle can be safely walked around")
	verify_swept_disc(path, 0.24, world)

func test_filled_footprint_and_terrain_guards() -> void:
	var world := Terrain.new()
	world.clearance = 0.0
	# The centre and FOUR cardinal tips are clear, but an interior diagonal
	# foot-support point is not. This is intentionally not a rim-only test.
	world.obstacles = [Rect2(5.08, -11.92, 0.09, 0.09)]
	check(route(world, Vector2(5, -12), Vector2(5, -12), 0.45).is_empty(), "filled footprint catches an interior off-axis prop")
	world.obstacles = []
	# Centre lies inside the union; part of its large footprint does not.
	check(route(world, Vector2(-2.0, -15), Vector2(-2.0, -15), 0.4).is_empty(), "every footprint probe, not just centre, stays inside approved area")
	world.grade = 0.28
	check(route(world, Vector2(2, -12), Vector2(8, -12), 0.6).size() == 2, "normal-approved gentle slope and renderer's height-difference tolerance")
	world.grade = 0.5
	check(route(world, Vector2(2, -12), Vector2(8, -12), 0.6).is_empty(), "normal.y below 0.94 never bypasses host predicate")
	world.grade = 0.0
	world.step = true
	check(route(world, Vector2(2, -12), Vector2(8, -12), 0.0).is_empty(), "abrupt ground drop between segment samples refused even for zero radius")
	world.step = false
	for bad in ["number", "boolean", "string", "nan", "inf", "x", "z"]:
		world.malformed = bad
		check(route(world, Vector2(2, -12), Vector2(8, -12), 0.3).is_empty(), "malformed/misregistered ground rejected: " + bad)
	world.malformed = ""
	for bad: Variant in [false, 1, 1.0, "true", {}, Vector3.ZERO]:
		world.allowed_override = bad
		check(route(world, Vector2(2, -12), Vector2(8, -12), 0.3).is_empty(), "predicate must return literal true boolean")

func test_per_call_cache_and_budgets() -> void:
	var world := Terrain.new()
	var start := Vector2(2, -12)
	var finish := Vector2(8, -12)
	check(route(world, start, finish, 0.4).size() == 2, "initial clear callback snapshot")
	world.obstacles = [Rect2(4.4, -13, 1.2, 2)]
	check(route(world, start, finish, 0.4).size() > 2, "changed obstacles invalidate all previous-call cache")
	world.obstacles = []
	check(route(world, start, finish, 0.4).size() == 2, "removed obstruction allows straight route again")
	check(Planner.MAX_NODES == 625 and Planner.SMOOTH_LOOKAHEAD == 8, "finite grid/min-scan and bounded shortcut lookahead")
	# Exercise the real hard-stop branch without spending 65k fake callbacks.
	var search := Planner.Search.new(0.4, world.ground, world.permitted)
	search._probes = Planner.MAX_SUPPORT_PROBES - 1
	var before := world.allowed_calls
	check(search.solve(start, finish).is_empty() and search._exhausted, "exhaustion is fail-closed, not an unchecked path")
	check(world.allowed_calls - before == 1, "no extra callback after support budget")
	world.obstacles = [Rect2(5.09, -19.3, 0.02, 14.6)]
	check(route(world, Vector2(1, -15), Vector2(9, -9), 0.6).is_empty(), "unreachable search remains bounded and ends")

func run() -> void:
	var source: Script = Planner
	if not source.can_instantiate():
		check(false, "raw helper compiles before route tests")
		quit(1)
		return
	test_inputs_and_standing()
	test_direct_cross_site_and_endpoint_spacing()
	test_detours_and_no_corner_cutting()
	test_filled_footprint_and_terrain_guards()
	test_per_call_cache_and_budgets()
	print("CAMP_TRAVEL_PATH_TEST: %s checks=%d failures=%d maxProbes=%d" % [
		"PASS" if failures == 0 else "FAIL", checks, failures, maximum_probes])
	quit(0 if failures == 0 else 1)
