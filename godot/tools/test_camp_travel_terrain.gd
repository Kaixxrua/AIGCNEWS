extends "test_camp_spawn_layout.gd"
## C-owned real-terrain survey, separate from B's renderer/clock tests.
## NOT a world build. Run ONLY after Main/A freeze the helper; arguments are
## the independently supplied helper SHA256 and a NEW scoped result JSON.
## Uses the already pinned native core/Host setup and read-only query helpers.

const LAYOUT_SHA := "31eb128844eacc95c943fa0df3719add198b97e3c9f3f6ce2d433f3514b7fc18"
const BOSS_SOURCE_RADIUS := 1.02
const BOSS_DISPLAY_SCALE := 2.0
const BOSS_ROUTE_MARGIN := 0.10
const TRAVEL_STEP := 0.10

var _planner: Script
var _layout: Script
var _freeze_sha := ""
var _new_boss := Vector2.ZERO
var _boss_exclusion := 0.0
var _ground_calls := 0
var _permitted_calls := 0

func _planner_ground(point: Vector2) -> Vector3:
	_ground_calls += 1
	return query(point).surface

func _planner_permitted(point: Vector2) -> bool:
	_permitted_calls += 1
	return query(point).allowed and point.distance_to(_new_boss) > _boss_exclusion

func _inside_union(point: Vector2) -> bool:
	for centre: Vector2 in _layout.CENTRES:
		if point.distance_squared_to(centre) <= ARENA_RADIUS * ARENA_RADIUS:
			return true
	return false

static func _segment_distance(point: Vector2, start: Vector2, finish: Vector2) -> float:
	var delta := finish - start
	if delta.length_squared() == 0.0:
		return point.distance_to(start)
	return point.distance_to(start + delta * clampf((point - start).dot(delta) / delta.length_squared(), 0.0, 1.0))

static func _points_json(points: PackedVector2Array) -> Array:
	var rows: Array = []
	for point: Vector2 in points:
		rows.append([point.x, point.y])
	return rows

func _inspect_returned_path(path: PackedVector2Array, radius: float) -> Dictionary:
	var result := {"safe": true, "pathLengthM": 0.0, "minBossClearanceM": INF,
		"minRiverMarginM": INF, "minObstacleMarginM": INF, "minNormalY": 1.0,
		"maxHeightVariationM": 0.0, "footprintSamples": 0, "rootSamples": 0}
	var offsets := footprint_offsets(radius, true)
	for index in range(path.size() - 1):
		var start := path[index]
		var finish := path[index + 1]
		var length := start.distance_to(finish)
		result.pathLengthM += length
		var boss_clearance := _segment_distance(_new_boss, start, finish) - _boss_exclusion - radius
		result.minBossClearanceM = minf(result.minBossClearanceM, boss_clearance)
		# Exact segment-to-inflated-circle oracle, independent of sampled spokes.
		if boss_clearance < 0.0:
			result.safe = false
			result.failure = {"reason": "returned_segment_intersects_new_boss", "segment": index,
				"clearanceM": boss_clearance}
			return result
		var steps := maxi(1, ceili(length / TRAVEL_STEP))
		var previous: Variant = null
		for step in range(steps + 1):
			var point := start.lerp(finish, float(step) / steps)
			var middle: Dictionary = query(point)
			result.rootSamples += 1
			if not middle.surface.is_finite():
				result.safe = false
				result.failure = {"reason": "missing_root_support", "point": [point.x, point.y]}
				return result
			if previous != null and absf(middle.surface.y - previous.y) > maxf(0.08, length / steps * 0.32):
				result.safe = false
				result.failure = {"reason": "abrupt_root_height_step", "point": [point.x, point.y]}
				return result
			previous = middle.surface
			for offset: Vector2 in offsets:
				var probe := point + offset
				var sample: Dictionary = query(probe)
				var variation: float = absf(sample.surface.y - middle.surface.y)
				result.footprintSamples += 1
				result.minRiverMarginM = minf(result.minRiverMarginM, sample.riverMargin)
				result.minObstacleMarginM = minf(result.minObstacleMarginM, sample.obstacleMargin)
				result.minNormalY = minf(result.minNormalY, sample.normalY)
				result.maxHeightVariationM = maxf(result.maxHeightVariationM, variation)
				if not sample.allowed or not sample.surface.is_finite() or not _inside_union(probe) \
						or probe.distance_to(_new_boss) <= _boss_exclusion or variation > maxf(0.08, radius * 0.32):
					result.safe = false
					result.failure = {"reason": "returned_footprint_unsafe", "point": [probe.x, probe.y],
						"allowed": sample.allowed, "insideUnion": _inside_union(probe),
						"normalY": sample.normalY, "riverMarginM": sample.riverMargin,
						"obstacleMarginM": sample.obstacleMargin, "heightVariationM": variation}
					return result
	return result

func _route_case(spec: Dictionary, origin: int, destination: int, start: Vector2, start_kind: String) -> Dictionary:
	var centre: Vector2 = _layout.CENTRES[destination]
	var local: Vector2 = HOVER_STATION if HOVER.has(spec.id) else STATIONS[spec.role]
	var finish := centre + local
	var radius := radius_for(spec)
	_new_boss = centre + STATIONS.boss
	_ground_calls = 0
	_permitted_calls = 0
	var timer := Time.get_ticks_usec()
	var path: PackedVector2Array = _planner.find_path(start, finish, radius, _planner_ground, _planner_permitted)
	var row := {"actor": spec.id, "role": spec.role, "hover": HOVER.has(spec.id),
		"from": origin, "to": destination, "startKind": start_kind,
		"start": [start.x, start.y], "finish": [finish.x, finish.y], "radius": radius,
		"bossCentre": [_new_boss.x, _new_boss.y], "bossPhysicalRadius": BOSS_SOURCE_RADIUS * BOSS_DISPLAY_SCALE,
		"bossExclusionRadius": _boss_exclusion, "startBossClearanceM": start.distance_to(_new_boss) - _boss_exclusion - radius,
		"finishBossClearanceM": finish.distance_to(_new_boss) - _boss_exclusion - radius,
		"elapsedMs": (Time.get_ticks_usec() - timer) / 1000.0,
		"groundCalls": _ground_calls, "permittedCalls": _permitted_calls, "path": _points_json(path)}
	check(_ground_calls <= _planner.MAX_SUPPORT_PROBES and _permitted_calls <= _planner.MAX_SUPPORT_PROBES,
		"bounded actual planner callbacks: " + str(spec.id))
	if path.is_empty():
		row.outcome = "rejected_candidate"
		row.reason = "start_inside_new_boss" if row.startBossClearanceM < 0.0 else (
			"finish_inside_new_boss" if row.finishBossClearanceM < 0.0 else "empty_plan")
		row.supportBudgetReached = _permitted_calls >= _planner.MAX_SUPPORT_PROBES
		return row
	var shape_ok: bool = path.size() >= 2 and path.size() <= _planner.MAX_NODES + 2 \
		and path[0] == start and path[-1] == finish
	for point: Vector2 in path:
		shape_ok = shape_ok and point.is_finite()
	check(shape_ok, "returned exact finite endpoints: " + str(spec.id))
	if not shape_ok:
		row.outcome = "unsafe_returned_path"
		row.failure = {"reason": "invalid_path_shape_or_endpoints"}
		return row
	var inspected := _inspect_returned_path(path, radius)
	row.inspection = inspected
	row.outcome = "reachable" if inspected.safe else "unsafe_returned_path"
	check(inspected.safe, "%s %d->%d %s returned path terrain/Boss safety: %s" % [
		spec.id, origin, destination, start_kind, str(inspected.get("failure", {}))])
	if not inspected.safe:
		print("CAMP_TRAVEL_BLOCKER: " + JSON.stringify(row))
	return row

func _survey(assets: Array, phase: String) -> Dictionary:
	var rows: Array = []
	var lunge_edges: Array = []
	var reachable := 0
	var rejected := 0
	var unsafe := 0
	for origin in range(_layout.CENTRES.size()):
		for destination in range(_layout.CENTRES.size()):
			if origin == destination:
				continue
			for spec: Dictionary in assets:
				if spec.role == "boss":
					continue
				var local: Vector2 = HOVER_STATION if HOVER.has(spec.id) else STATIONS[spec.role]
				var start: Vector2 = _layout.CENTRES[origin] + local
				var row := _route_case(spec, origin, destination, start, "station_baseline")
				rows.append(row)
				reachable += int(row.outcome == "reachable")
				rejected += int(row.outcome == "rejected_candidate")
				unsafe += int(row.outcome == "unsafe_returned_path")
				# Extra analytic lunge-start envelope, not extra planner calls and
				# not a claim to have sampled a live user's current root.
				var old_boss: Vector2 = _layout.CENTRES[origin] + STATIONS.boss
				var full_lunge := start + start.direction_to(old_boss) * 0.58
				lunge_edges.append({"actor": spec.id, "from": origin, "to": destination,
					"fullLungeStart": [full_lunge.x, full_lunge.y],
					"stationClearanceM": row.startBossClearanceM,
					"fullLungeClearanceM": full_lunge.distance_to(_new_boss) - _boss_exclusion - row.radius,
					"minimumDuringLungeM": _segment_distance(_new_boss, start, full_lunge) - _boss_exclusion - row.radius,
					"scope": "analytic possible-start envelope only; Main must plan from actual current root"})
		print("CAMP_TRAVEL_PROGRESS: " + JSON.stringify({"phase": phase, "originsFinished": origin + 1,
			"routes": rows.size(), "reachable": reachable, "rejectedCandidates": rejected, "unsafeReturned": unsafe}))
	check(rows.size() == 240, phase + " all20 directed pairs times12 friendly actors classified")
	var actor_availability: Array = []
	for origin in range(5):
		for spec: Dictionary in assets:
			if spec.role == "boss":
				continue
			var choices: Array = []
			for row: Dictionary in rows:
				if row.from == origin and row.actor == spec.id and row.to != origin and row.outcome == "reachable":
					choices.append(row.to)
			actor_availability.append({"from": origin, "actor": spec.id, "reachableDestinations": choices})
			check(not choices.is_empty(), "%s site%d %s has a safe nonrepeating destination" % [phase, origin, spec.id])
			if choices.is_empty():
				print("CAMP_TRAVEL_BLOCKER: " + JSON.stringify({"phase": phase,
					"reason": "actor_has_no_safe_destination", "from": origin, "actor": spec.id}))
	check(actor_availability.size() == 60, phase + " all5 sites times12 companions have destination evidence")
	var party_availability: Array = []
	for origin in range(5):
		for hero: Dictionary in assets:
			if hero.role != "hero":
				continue
			for pet: Dictionary in assets:
				if pet.role != "pet":
					continue
				var choices: Array = []
				for destination in range(5):
					var matching := 0
					for row: Dictionary in rows:
						if row.from == origin and row.to == destination and row.actor in [hero.id, pet.id] and row.outcome == "reachable":
							matching += 1
					if matching == 2:
						choices.append(destination)
				party_availability.append({"from": origin, "hero": hero.id, "pet": pet.id, "reachableDestinations": choices})
				check(not choices.is_empty(), "%s site%d %s/%s share a safe nonrepeating destination" % [phase, origin, hero.id, pet.id])
				if choices.is_empty():
					print("CAMP_TRAVEL_BLOCKER: " + JSON.stringify({"phase": phase,
						"reason": "party_has_no_common_safe_destination", "from": origin, "hero": hero.id, "pet": pet.id}))
	return {"phase": phase, "rows": rows, "reachable": reachable, "rejectedCandidates": rejected,
		"unsafeReturned": unsafe, "lungeStartEnvelope": lunge_edges,
		"stationActorAvailability": actor_availability, "stationPartyAvailability": party_availability}

func _travel_probe() -> Dictionary:
	for resource: Array in [[_workspace.path_join(CORE), CORE_SHA], [_workspace.path_join(WRAPPER), WRAPPER_SHA],
		["res://project.binary", PROJECT_SHA], ["res://.godot/global_script_class_cache.cfg", CACHE_SHA],
		["res://camp_bootstrap/camp_pack_host.gd", HOST_SHA], [_workspace.path_join("godot/scripts/camp_pack_host.gd"), HOST_SHA],
		[_workspace.path_join("godot/scripts/camp_spawn_layout.gd"), LAYOUT_SHA],
		[_workspace.path_join("godot/assets/camp/v1/manifest.json"), CATALOGUE_SHA],
		[_workspace.path_join("godot/scripts/camp_travel_path.gd"), _freeze_sha]]:
		check(FileAccess.get_sha256(resource[0]) == resource[1], "exact frozen survey input: " + resource[0].get_file())
	if not failures.is_empty():
		return {}
	_planner = load(_workspace.path_join("godot/scripts/camp_travel_path.gd"))
	_layout = load(_workspace.path_join("godot/scripts/camp_spawn_layout.gd"))
	check(_planner != null and _layout != null, "frozen pure planner/layout parse")
	if not failures.is_empty():
		return {}
	var catalogue: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(_workspace.path_join("godot/assets/camp/v1/manifest.json")))
	var assets: Array = catalogue.assets
	check(assets.size() == 13 and _layout.CENTRES.size() == 5, "exact13 actors and5 clearings")
	var boss_count := 0
	for spec: Dictionary in assets:
		if spec.role == "boss":
			boss_count += 1
			check(is_equal_approx(spec.shadowRadius, BOSS_SOURCE_RADIUS), "actual original Boss source radius1.02")
	check(boss_count == 1, "one original Boss")
	_boss_exclusion = BOSS_SOURCE_RADIUS * BOSS_DISPLAY_SCALE + BOSS_ROUTE_MARGIN
	check(ProjectSettings.load_resource_pack(_workspace.path_join(CORE), false), "existing native core, no export or replacement")
	ProjectSettings.set_setting("application/run/main_scene", "res://scenes/main.tscn")
	var host_script: Script = load("res://camp_bootstrap/camp_pack_host.gd")
	_host = host_script.new()
	check(_host.configure({"version": 1, "optionalPack": null}), "Host only, no old presentation mounted")
	root.add_child(_host)
	var temporary := Node.new()
	root.add_child(temporary)
	current_scene = temporary
	check(change_scene_to_file("res://scenes/main.tscn") == OK, "load actual frozen scene")
	await process_frame
	await process_frame
	_world = current_scene as Node3D
	check(_world != null and _host.mark_core_presented(), "actual live terrain Host ready")
	if not failures.is_empty():
		return {}
	var wildlife := _world.get_node("LivingWildlife")
	var wildlife_id := wildlife.get_instance_id()
	var world_id := _world.get_instance_id()
	var children_before := _world.get_child_count()
	var core := _survey(assets, "core")
	var controller := _world.get_node("ProgressiveDetails")
	for chunk: Dictionary in controller.manifest.chunks:
		var path := _workspace.path_join(CORE).get_base_dir().path_join(str(chunk.file))
		check(FileAccess.get_sha256(path) == chunk.sha256, "exact existing native detail " + str(chunk.index))
		if FileAccess.get_sha256(path) != chunk.sha256:
			return {"core": core}
		await controller.apply_chunk(int(chunk.index), path)
		await process_frame
		check(controller.applied_count == int(chunk.index) + 1 and not controller.busy and controller.last_error == "",
			"normal detail apply " + str(chunk.index))
	check(controller.completed and controller.applied_count == 12 and _host._live(), "all12 details/current sampler ready")
	_cache.clear()
	var detail := _survey(assets, "all12details")
	check(_world.get_instance_id() == world_id and wildlife.get_instance_id() == wildlife_id
		and _world.get_child_count() == children_before, "world/wildlife identities and world child count retained")
	check(not _world.has_node("CampPresentation"), "no renderer/actors added to terrain survey")
	check(FileAccess.get_sha256(_workspace.path_join("godot/scripts/camp_travel_path.gd")) == _freeze_sha,
		"planner source unchanged throughout survey")
	check(FileAccess.get_sha256(_workspace.path_join("godot/scripts/camp_spawn_layout.gd")) == LAYOUT_SHA,
		"five-site layout unchanged throughout survey")
	var result := {"core": core, "all12details": detail, "baselineRouteCases": 480,
		"actualTerrainQueries": _queries, "bossPhysicalRadius": 2.04, "bossExclusionRadius": _boss_exclusion,
		"helperSha256": _freeze_sha, "hostSha256": HOST_SHA, "coreSha256": CORE_SHA,
		"wrapperSha256": WRAPPER_SHA, "catalogueSha256": CATALOGUE_SHA, "layoutSha256": LAYOUT_SHA,
		"sampling": {"arcStepM": TRAVEL_STEP, "footprintGridM": 0.20, "footprintRimSamples": 48},
		"limits": ["Safety of returned routes, not a requirement that all20 pairs are reachable",
			"Station starts explicitly labelled; lunge-start envelope is analytic, not additional planner runs or live-user data",
			"Actual frozen native terrain, not a moving-wildlife, Web/GPU, or continuous terrain collision proof"]}
	_world.free()
	_host.free()
	await process_frame
	return result

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	_workspace = get_script().resource_path.get_base_dir().path_join("../..").simplify_path()
	if arguments.size() != 2:
		print("CAMP_TRAVEL_HOLD: independently supplied frozen helper SHA256 and NEW scoped JSON required")
		quit(1)
		return
	_freeze_sha = arguments[0].to_lower()
	if _freeze_sha.length() != 64 or not _freeze_sha.is_valid_hex_number(false):
		quit(1)
		return
	_destination = arguments[1].replace("\\", "/").simplify_path()
	if not _destination.is_absolute_path() or not _destination.to_lower().begins_with(
			_workspace.path_join("artifacts/camp-travel-v168/").to_lower()) or FileAccess.file_exists(_destination):
		quit(1)
		return
	var timer := Time.get_ticks_usec()
	var result := await _travel_probe()
	result.status = "PASS" if failures.is_empty() else "FAIL"
	result.checks = checks
	result.failures = failures
	result.elapsedMs = (Time.get_ticks_usec() - timer) / 1000.0
	var output := FileAccess.open(_destination, FileAccess.WRITE)
	if output == null:
		quit(1)
		return
	output.store_string(JSON.stringify(result, "\t") + "\n")
	output.close()
	print("CAMP_TRAVEL_SURVEY: " + JSON.stringify({"status": result.status, "checks": checks,
		"failures": failures, "elapsedMs": result.elapsedMs, "actualTerrainQueries": _queries,
		"coreReachable": result.get("core", {}).get("reachable", 0),
		"detailReachable": result.get("all12details", {}).get("reachable", 0), "evidence": _destination}))
	quit(0 if failures.is_empty() else 1)
