extends "test_camp_travel_terrain.gd"
## C-owned focused follow-up. Preserve the old unbuffered test/results.
## Plan with Main's extra0.08m; independently inspect actual body radius.
## Real Host callbacks in planner timing, no diagnostic query-cache shortcut.

const PLANNING_CLEARANCE := 0.08
const OLD_RESULT := "artifacts/camp-travel-v168/native-01/terrain-result.json"
const OLD_RESULT_SHA := "7415efe66585fe28437683883c5fdabac841f34da3403d7dc9be457bafeab5c9"
const BASE_TEST_SHA := "3fd549248f0b5f0752ee6ee28cb7df5ada657025903abd339941b9666b7b6889"
# Previously measured common targets, now revalidated with the extra radius.
# Not a runtime hardcoded route table; rejected targets try remaining sites.
const FIRST_TARGET := {0: 2, 1: 0, 2: 4, 3: 0, 4: 2}
const FORMER_FAILURES := [
	{"actor": "pet_dragon", "from": 2, "to": 1},
	{"actor": "hero_mage", "from": 2, "to": 3},
	{"actor": "hero_alchemist", "from": 2, "to": 3},
	{"actor": "hero_astrologer", "from": 2, "to": 3}]

func _planner_ground(point: Vector2) -> Vector3:
	_ground_calls += 1
	return _host.sample_ground(point)

func _planner_permitted(point: Vector2) -> bool:
	_permitted_calls += 1
	return _host.permitted_ground(point) and point.distance_to(_new_boss) > _boss_exclusion

func _route_case(spec: Dictionary, origin: int, destination: int, start: Vector2, start_kind: String) -> Dictionary:
	var centre: Vector2 = _layout.CENTRES[destination]
	var local: Vector2 = HOVER_STATION if HOVER.has(spec.id) else STATIONS[spec.role]
	var finish := centre + local
	var radius := radius_for(spec)
	var planning_radius := radius + PLANNING_CLEARANCE
	_new_boss = centre + STATIONS.boss
	_ground_calls = 0
	_permitted_calls = 0
	var timer := Time.get_ticks_usec()
	var path: PackedVector2Array = _planner.find_path(start, finish, planning_radius, _planner_ground, _planner_permitted)
	var row := {"actor": spec.id, "role": spec.role, "hover": HOVER.has(spec.id),
		"from": origin, "to": destination, "startKind": start_kind,
		"start": [start.x, start.y], "finish": [finish.x, finish.y],
		"radius": radius, "planningRadius": planning_radius, "planningClearance": PLANNING_CLEARANCE,
		"bossCentre": [_new_boss.x, _new_boss.y], "bossPhysicalRadius": 2.04,
		"bossExclusionRadius": _boss_exclusion,
		"startBossClearanceM": start.distance_to(_new_boss) - _boss_exclusion - radius,
		"startPlanningBossClearanceM": start.distance_to(_new_boss) - _boss_exclusion - planning_radius,
		"finishPlanningBossClearanceM": finish.distance_to(_new_boss) - _boss_exclusion - planning_radius,
		"plannerElapsedMs": (Time.get_ticks_usec() - timer) / 1000.0,
		"timingScope": "actual Host callbacks; excludes independent oracle; no C query cache in planner",
		"groundCalls": _ground_calls, "permittedCalls": _permitted_calls, "path": _points_json(path)}
	check(_ground_calls <= _planner.MAX_SUPPORT_PROBES and _permitted_calls <= _planner.MAX_SUPPORT_PROBES,
		"bounded buffered planner callbacks: " + str(spec.id))
	if path.is_empty():
		row.outcome = "rejected_candidate"
		row.reason = "planning_start_inside_new_boss" if row.startPlanningBossClearanceM < 0.0 else (
			"planning_finish_inside_new_boss" if row.finishPlanningBossClearanceM < 0.0 else "empty_plan")
		row.supportBudgetReached = _permitted_calls >= _planner.MAX_SUPPORT_PROBES
		return row
	var shape_ok: bool = path.size() >= 2 and path.size() <= _planner.MAX_NODES + 2 \
		and path[0] == start and path[-1] == finish
	for point: Vector2 in path:
		shape_ok = shape_ok and point.is_finite()
	check(shape_ok, "buffered planner retains exact finite endpoints: " + str(spec.id))
	if not shape_ok:
		row.outcome = "unsafe_returned_path"
		row.failure = {"reason": "invalid_path_shape_or_endpoints"}
		return row
	timer = Time.get_ticks_usec()
	# Intentionally NOT planning_radius: execution/body radius is unchanged.
	var inspected := _inspect_returned_path(path, radius)
	row.oracleElapsedMs = (Time.get_ticks_usec() - timer) / 1000.0
	row.inspection = inspected
	row.outcome = "reachable" if inspected.safe else "unsafe_returned_path"
	check(inspected.safe, "%s %d->%d actual-radius oracle after buffered planning: %s" % [
		spec.id, origin, destination, str(inspected.get("failure", {}))])
	if not inspected.safe:
		print("CAMP_TRAVEL_BLOCKER: " + JSON.stringify(row))
	return row

static func _row_choices(rows: Array, origin: int, id: String) -> Array:
	var choices: Array = []
	for row: Dictionary in rows:
		if row.from == origin and row.to != origin and row.actor == id and row.outcome == "reachable" and not choices.has(row.to):
			choices.append(row.to)
	return choices

static func _common_choices(rows: Array, origin: int, hero_id: String, pet_id: String) -> Array:
	var choices: Array = []
	var hero_choices := _row_choices(rows, origin, hero_id)
	for choice: int in _row_choices(rows, origin, pet_id):
		if hero_choices.has(choice):
			choices.append(choice)
	return choices

static func _party_covered(rows: Array, origin: int, assets: Array) -> bool:
	for hero: Dictionary in assets:
		if hero.role != "hero":
			continue
		for pet: Dictionary in assets:
			if pet.role == "pet" and _common_choices(rows, origin, hero.id, pet.id).is_empty():
				return false
	return true

func _station_case(spec: Dictionary, origin: int, destination: int, purpose: String) -> Dictionary:
	var local: Vector2 = HOVER_STATION if HOVER.has(spec.id) else STATIONS[spec.role]
	var row := _route_case(spec, origin, destination, _layout.CENTRES[origin] + local, "station_baseline")
	row.purpose = purpose
	return row

func _survey(assets: Array, phase: String) -> Dictionary:
	var rows: Array = []
	for origin in range(5):
		var targets: Array = [FIRST_TARGET[origin]]
		for target in range(5):
			if target != origin and not targets.has(target):
				targets.append(target)
		for target: int in targets:
			for spec: Dictionary in assets:
				if spec.role != "boss":
					rows.append(_station_case(spec, origin, target, "party_reachability"))
			if _party_covered(rows, origin, assets):
				break
		print("CAMP_TRAVEL_BUFFER_PROGRESS: " + JSON.stringify({"phase": phase,
			"originsFinished": origin + 1, "routes": rows.size(), "partyCovered": _party_covered(rows, origin, assets)}))
	for former: Dictionary in FORMER_FAILURES:
		var existing: Array = rows.filter(func(row: Dictionary) -> bool:
			return row.actor == former.actor and row.from == former.from and row.to == former.to)
		if not existing.is_empty():
			existing[0].formerBoundaryFailure = true
			continue
		for spec: Dictionary in assets:
			if spec.id == former.actor:
				var row := _station_case(spec, former.from, former.to, "former_boundary_failure")
				row.formerBoundaryFailure = true
				rows.append(row)
				print("CAMP_TRAVEL_BUFFER_FORMER: " + JSON.stringify({"phase": phase, "actor": spec.id,
					"from": former.from, "to": former.to, "outcome": row.outcome, "plannerElapsedMs": row.plannerElapsedMs}))
	var actor_availability: Array = []
	var party_availability: Array = []
	for origin in range(5):
		for spec: Dictionary in assets:
			if spec.role == "boss":
				continue
			var choices := _row_choices(rows, origin, spec.id)
			actor_availability.append({"from": origin, "actor": spec.id, "reachableDestinations": choices})
			check(not choices.is_empty(), "%s buffered site%d %s has a safe nonrepeating target" % [phase, origin, spec.id])
		for hero: Dictionary in assets:
			if hero.role != "hero":
				continue
			for pet: Dictionary in assets:
				if pet.role != "pet":
					continue
				var choices := _common_choices(rows, origin, hero.id, pet.id)
				party_availability.append({"from": origin, "hero": hero.id, "pet": pet.id, "reachableDestinations": choices})
				check(not choices.is_empty(), "%s buffered site%d %s/%s have a common safe target" % [phase, origin, hero.id, pet.id])
	check(actor_availability.size() == 60 and party_availability.size() == 180, phase + " all origin/actor/loadout evidence")
	check(rows.filter(func(row: Dictionary) -> bool: return row.get("formerBoundaryFailure", false)).size() == 4,
		phase + " all4 former boundary failures reclassified")
	return {"phase": phase, "rows": rows,
		"reachable": rows.filter(func(row: Dictionary) -> bool: return row.outcome == "reachable").size(),
		"rejectedCandidates": rows.filter(func(row: Dictionary) -> bool: return row.outcome == "rejected_candidate").size(),
		"unsafeReturned": rows.filter(func(row: Dictionary) -> bool: return row.outcome == "unsafe_returned_path").size(),
		"stationActorAvailability": actor_availability, "stationPartyAvailability": party_availability}

func _check_main_contract() -> void:
	var source := FileAccess.get_file_as_string(_workspace.path_join("godot/scripts/camp_presentation.gd"))
	check(source.contains("const TRAVEL_CLEARANCE := 0.08"), "Main retains approved0.08 planning clearance")
	check(source.contains("var start := Vector2(actor.root.position.x, actor.root.position.z)"), "Main captures actual current actor root")
	check(source.contains("TravelPath.find_path(start, finish, actor.radius + TRAVEL_CLEARANCE, _ground, _route_permitted.bind(centre))"),
		"Main route call uses inflated radius and actual terrain/Boss closure")
	check(source.contains("return point.distance_to(centre + STATIONS.boss) > boss_radius + 0.10"), "Main Boss predicate retains0.10 margin")
	check(source.contains("not _travel_step_safe(point, next, actor.radius)"), "Main execution still checks actual radius")

func _travel_probe() -> Dictionary:
	check(FileAccess.get_sha256(_workspace.path_join(OLD_RESULT)) == OLD_RESULT_SHA, "old unbuffered evidence retained byte-identical")
	check(FileAccess.get_sha256(_workspace.path_join("godot/tools/test_camp_travel_terrain.gd")) == BASE_TEST_SHA,
		"old independent actual-radius oracle/test preserved")
	_check_main_contract()
	if not failures.is_empty():
		return {}
	var main_before := FileAccess.get_sha256(_workspace.path_join("godot/scripts/camp_presentation.gd"))
	var result: Dictionary = await super._travel_probe()
	_check_main_contract()
	result.erase("baselineRouteCases")
	result.focusedRouteCases = result.get("core", {}).get("rows", []).size() + result.get("all12details", {}).get("rows", []).size()
	result.planningClearanceM = PLANNING_CLEARANCE
	result.actualBodyRadiusUnchanged = true
	result.actualTerrainQueriesScope = "Independent oracle unique points only; real planner Host calls are counted separately per row"
	result.previousDiagnosticSha256 = OLD_RESULT_SHA
	result.oracleSourceSha256 = BASE_TEST_SHA
	result.mainSourceSha256Before = main_before
	result.mainSourceSha256After = FileAccess.get_sha256(_workspace.path_join("godot/scripts/camp_presentation.gd"))
	result.limits = ["Focused common-destination and previous-failure proof, NOT the full480 matrix",
		"Station starts; Main/B own actual moving-root and intermediate lunge renderer tests",
		"Planner timing uses actual Host callbacks without C's diagnostic cache; native, not Web latency",
		"Independent <=0.10m actual-radius footprint sampling and analytic Boss-disc line check",
		"Actual core and all12 details; no moving-wildlife, GPU, preview or service operation"]
	return result
