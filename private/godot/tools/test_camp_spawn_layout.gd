extends SceneTree
## Independent spawn geometry/selection regression. No renderer, world or assets
## are rewritten. --probe NEW_RESULT uses the existing pinned native core/wrapper;
## default NEW_RESULT runs only pure layout-helper checks in an isolated project.

const CORE := "artifacts/startup-v135/build/candidate-15/native/index-lite.pck"
const CORE_SHA := "8d7a9e04209cd0154029634d7d8a8c92b90d5ec7f009b821bb1e4b4afe86df95"
const WRAPPER := "artifacts/camp-bootstrap/actual-scale-v165-01/probe-wrapper.pck"
const WRAPPER_SHA := "82fbd7d4c71b5f2a802489d30e6932e9ace2078decabbad3e85cd86dfca0816a"
const HOST_SHA := "4ed0c2c4995f22f568d7662f9c372867e6127c7e88550390b764515ca7034124"
const CATALOGUE_SHA := "0170dc18fa2d6ab6dde97b5bb4a462330d649b99b87fe4fce267af75ed906953"
const PROJECT_SHA := "ab0dc16bf8ed9dcb14f2a5bc9003d9ce15693db063dfd6ca9c3f5623500d78e0"
const CACHE_SHA := "f61aa7ad3097022d6a9d110ca3f73fa7bb348ec2cf9a6e7c9523574dc75f5a16"
const TERRAIN_EVIDENCE := "artifacts/camp-spawn-v166/native/terrain-result-complete.json"
const TERRAIN_EVIDENCE_SHA := "f4751cd135fc14ae5436e76ea8a7d3a01e76ade616d76aff4d17aedd7f0b0fed"
const ARENA_RADIUS := 4.2
const STATIONS := {"hero": Vector2(-2.35, 1.10), "pet": Vector2(-1.35, 2.10), "boss": Vector2(1.85, -0.65)}
const HOVER_STATION := Vector2(-2.10, -3.20)
const HOVER := ["pet_owl", "pet_finch", "pet_dragon"]
const PET_SCALES := {"pet_deer": 0.90, "pet_fox": 0.94, "pet_rabbit": 0.60,
	"pet_owl": 0.62, "pet_finch": 0.68, "pet_dragon": 0.93}
## Search probes ONLY, not approved spawn sites. Exported sites are selected
## after the actual frozen-core result, never by this coarse search list alone.
const SEARCH_X := [-1.0, 2.0, 5.0, 8.0, 11.0]
const SEARCH_Z := [-18.0, -15.0, -12.0, -9.0, -6.0]

var checks := 0
var failures: Array[String] = []
var _workspace := ""
var _destination := ""
var _host: Node
var _world: Node3D
var _cache: Dictionary = {}
var _queries := 0

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures.append(label)
		print("CAMP_SPAWN_FAIL: " + label)

static func vector_json(value: Vector3) -> Array:
	return [value.x, value.y, value.z]

static func radius_for(spec: Dictionary) -> float:
	var scale: float = 2.0 if spec.role == "boss" else (1.10 if spec.role == "hero" else float(PET_SCALES[spec.id]))
	return float(spec.shadowRadius) * scale

func query(point: Vector2) -> Dictionary:
	if _cache.has(point):
		return _cache[point]
	_queries += 1
	var surface: Vector3 = _host.sample_ground(point)
	var allowed: bool = _host.permitted_ground(point)
	var normal: Vector3 = _world.terrain_normal(point.x, point.y)
	var river_margin: float = absf(point.x - float(_world.river_center(point.y))) - float(_world.river_half_width(point.y)) - 2.0
	var obstacle_margin := INF
	for obstacle: Vector3 in _world.get_node("LivingWildlife").obstacles:
		obstacle_margin = minf(obstacle_margin, point.distance_to(Vector2(obstacle.x, obstacle.y)) - obstacle.z - 0.10)
	var result := {"surface": surface, "allowed": allowed, "normalY": normal.y,
		"riverMargin": river_margin, "obstacleMargin": obstacle_margin}
	_cache[point] = result
	return result

func footprint_offsets(radius: float, dense: bool) -> Array[Vector2]:
	var result: Array[Vector2] = [Vector2.ZERO, Vector2(radius, 0), Vector2(-radius, 0), Vector2(0, radius), Vector2(0, -radius)]
	if dense:
		# Interior grid and circumference, not just the renderer's five probes.
		var count := ceili(radius / 0.20)
		for x in range(-count, count + 1):
			for z in range(-count, count + 1):
				var offset := Vector2(x * 0.20, z * 0.20)
				if offset.length() <= radius and not result.has(offset):
					result.append(offset)
		for index in range(48):
			var offset := Vector2.from_angle(TAU * index / 48.0) * radius
			if not result.has(offset):
				result.append(offset)
	return result

func inspect_actor(centre: Vector2, spec: Dictionary, dense: bool) -> Dictionary:
	var radius := radius_for(spec)
	var role: String = spec.role
	var local_station: Vector2 = HOVER_STATION if HOVER.has(spec.id) else STATIONS[role]
	var station := centre + local_station
	var opponent: Vector2 = centre + STATIONS["hero" if role == "boss" else "boss"]
	var reach := 0.42 if role == "boss" else 0.58
	var finish := station + station.direction_to(opponent) * reach
	var steps := ceili(reach / (0.10 if dense else 0.20))
	var offsets := footprint_offsets(radius, dense)
	var result := {"safe": true, "radius": radius, "station": [station.x, station.y],
		"finish": [finish.x, finish.y], "rootScale": [1, 1, 1], "maxHeightVariationM": 0.0,
		"minNormalY": 1.0, "minRiverMarginM": INF, "minObstacleMarginM": INF,
		"arenaBoundaryMarginM": ARENA_RADIUS - maxf(local_station.length(), finish.distance_to(centre)) - radius,
		"pathSamples": steps + 1, "footprintSamplesPerPath": offsets.size()}
	for index in range(steps + 1):
		var point := station.lerp(finish, float(index) / steps)
		var middle: Dictionary = query(point)
		if not middle.surface.is_finite():
			result.safe = false
			result.failure = "missing centre ray"
			return result
		for offset: Vector2 in offsets:
			var sample: Dictionary = query(point + offset)
			var variation: float = absf(sample.surface.y - middle.surface.y)
			result.minNormalY = minf(result.minNormalY, sample.normalY)
			result.minRiverMarginM = minf(result.minRiverMarginM, sample.riverMargin)
			result.minObstacleMarginM = minf(result.minObstacleMarginM, sample.obstacleMargin)
			result.maxHeightVariationM = maxf(result.maxHeightVariationM, variation)
			if not sample.allowed or not sample.surface.is_finite() or variation > maxf(0.08, radius * 0.32) or result.arenaBoundaryMarginM < 0.0:
				result.safe = false
				result.failure = {"point": [point.x + offset.x, point.y + offset.y], "allowed": sample.allowed,
					"normalY": sample.normalY, "riverMarginM": sample.riverMargin, "obstacleMarginM": sample.obstacleMargin,
					"heightVariationM": variation}
				return result
	result.foot = vector_json(_host.sample_ground(station))
	result.lungeFoot = vector_json(_host.sample_ground(finish))
	return result

func sweep(assets: Array, dense: bool, selected: Array = []) -> Array:
	var result: Array = []
	var camera := _world.get_node("Camera3D") as Camera3D
	var sites: Array = selected.duplicate(true)
	if not dense:
		for x: float in SEARCH_X:
			for z: float in SEARCH_Z:
				sites.append({"centre": [x, z]})
	for site: Dictionary in sites:
		var centre := Vector2(float(site.centre[0]), float(site.centre[1]))
		var row := {"centre": site.centre, "allActorsSafe": true, "actors": {}}
		for spec: Dictionary in assets:
			var actor := inspect_actor(centre, spec, dense)
			row.actors[spec.id] = actor
			row.allActorsSafe = row.allActorsSafe and actor.safe
		var foot: Vector3 = _host.sample_ground(centre)
		if foot.is_finite():
			var screen := camera.unproject_position(foot) / root.get_visible_rect().size
			row.footScreenFraction = [screen.x, screen.y]
		result.append(row)
	return result

func core_probe() -> Dictionary:
	check(FileAccess.get_sha256(_workspace.path_join(WRAPPER)) == WRAPPER_SHA, "exact existing v165 wrapper, no pack built")
	check(FileAccess.get_sha256("res://project.binary") == PROJECT_SHA, "accepted wrapper project settings")
	check(FileAccess.get_sha256("res://.godot/global_script_class_cache.cfg") == CACHE_SHA, "accepted empty script-class cache")
	check(FileAccess.get_sha256("res://camp_bootstrap/camp_pack_host.gd") == HOST_SHA, "exact existing terrain Host")
	check(FileAccess.get_sha256(_workspace.path_join(CORE)) == CORE_SHA, "frozen native twin core15")
	var catalogue_path := _workspace.path_join("godot/assets/camp/v1/manifest.json")
	check(FileAccess.get_sha256(catalogue_path) == CATALOGUE_SHA, "all13 original public descriptor pin")
	if not failures.is_empty():
		return {}
	var catalogue: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(catalogue_path))
	var assets: Array = catalogue.assets
	check(assets.size() == 13, "13 exact scaled actor descriptors")
	for spec: Dictionary in assets:
		if spec.role == "boss":
			check(is_equal_approx(radius_for(spec), 2.04), "actual enlarged Boss radius2.04")
	check(ProjectSettings.load_resource_pack(_workspace.path_join(CORE), false), "mount existing native twin without replacing resources")
	# Same in-memory main-scene context as the existing actual-core harness;
	# the frozen restoration code rejects the wrapper's boot-scene context.
	ProjectSettings.set_setting("application/run/main_scene", "res://scenes/main.tscn")
	var host_script: Script = load("res://camp_bootstrap/camp_pack_host.gd")
	_host = host_script.new()
	check(_host.configure({"version": 1, "optionalPack": null}), "no presentation or artwork mounted in terrain probe")
	root.add_child(_host)
	var temporary := Node.new()
	root.add_child(temporary)
	current_scene = temporary
	check(change_scene_to_file("res://scenes/main.tscn") == OK, "load actual frozen main scene")
	await process_frame
	await process_frame
	_world = current_scene as Node3D
	check(_world != null and _world.scene_file_path == "res://scenes/main.tscn" and _host.mark_core_presented(), "real meadow Host ready")
	if _world == null or not failures.is_empty():
		return {}
	var baseline_children := _world.get_child_count()
	var wildlife := _world.get_node("LivingWildlife")
	var wildlife_id := wildlife.get_instance_id()
	var core_rows := sweep(assets, false)
	var core_eligible: Array = []
	for row: Dictionary in core_rows:
		if row.allActorsSafe:
			core_eligible.append(row)
	print("CAMP_SPAWN_PROGRESS: core coarse eligible=" + JSON.stringify(core_eligible.map(func(row: Dictionary) -> Array: return row.centre)))
	var dense_core := sweep(assets, true, core_eligible)
	var dense_core_safe: Array = []
	for row: Dictionary in dense_core:
		if row.allActorsSafe:
			dense_core_safe.append(row.centre)
	print("CAMP_SPAWN_PROGRESS: core dense safe=" + JSON.stringify(dense_core_safe) + " queries=" + str(_queries))
	var controller := _world.get_node("ProgressiveDetails")
	for chunk: Dictionary in controller.manifest.chunks:
		var path := _workspace.path_join(CORE).get_base_dir().path_join(str(chunk.file))
		check(FileAccess.get_sha256(path) == chunk.sha256, "exact existing native detail " + str(chunk.index))
		if not failures.is_empty():
			return {}
		await controller.apply_chunk(int(chunk.index), path)
		await process_frame
		check(controller.applied_count == int(chunk.index) + 1 and not controller.busy and controller.last_error == "", "normal detail apply " + str(chunk.index))
	check(controller.completed and controller.applied_count == 12 and _host._live(), "all12 original details and actual current ground sampler")
	_cache.clear()
	var detailed_rows := sweep(assets, false)
	var eligible: Array = []
	for index in range(detailed_rows.size()):
		if detailed_rows[index].allActorsSafe and dense_core_safe.has(detailed_rows[index].centre):
			eligible.append(detailed_rows[index])
	print("CAMP_SPAWN_PROGRESS: detail coarse eligible=" + JSON.stringify(eligible.map(func(row: Dictionary) -> Array: return row.centre)))
	var dense_details := sweep(assets, true, eligible)
	# Require dense safety in BOTH independent sampler states. Never assume
	# detail safety implies the earlier lower-detail ground had identical heights.
	var safe: Array = []
	for row: Dictionary in dense_details:
		if row.allActorsSafe:
			safe.append(row.centre)
	check(safe.size() >= 3, "at least3 actual all13 full-detail dense-safe candidates")
	check(wildlife.get_instance_id() == wildlife_id and _world.get_node("LivingWildlife") == wildlife,
		"existing wildlife retained, no replacement animal system")
	check(not _world.has_node("CampPresentation") and not _world.has_node("CampSpawnLayout"), "probe added no meadow actor/layout nodes")
	var result := {"coreSha256": CORE_SHA, "wrapperSha256": WRAPPER_SHA, "hostSha256": HOST_SHA,
		"catalogueSha256": CATALOGUE_SHA, "coreCandidates": core_rows, "denseCoreCandidates": dense_core, "detailCandidates": detailed_rows,
		"denseDetailCandidates": dense_details, "safeCentres": safe, "actualPointQueries": _queries,
		"coreChildren": baseline_children, "detailChildren": _world.get_child_count(),
		"obstacles": wildlife.obstacles.size(), "groundType": wildlife.ground_surface.get_class(),
		"sampling": {"lungeStepM": 0.10, "interiorGridM": 0.20, "rimSamples": 48},
		"limits": ["Actual frozen native core and12details, no mock terrain", "No Web/GPU/collision-with-moving-wildlife claim", "Dense finite samples, not a continuous mathematical clearance proof"]}
	_world.free()
	_host.free()
	await process_frame
	return result

func selection_tests() -> Dictionary:
	var layout: Variant = load(_workspace.path_join("godot/scripts/camp_spawn_layout.gd"))
	check(layout != null, "pure helper parses")
	if layout == null:
		return {}
	var sites: Array = layout.CENTRES
	check(sites.size() >= 3 and sites.size() <= 5, "bounded3-5 approved sites")
	var indices := PackedInt32Array()
	for index in range(sites.size()):
		check(sites[index] is Vector2 and sites[index].is_finite(), "finite layout-only XZ centre")
		indices.append(index)
		for earlier in range(index):
			check(sites[index].distance_to(sites[earlier]) >= 4.0, "distinct sites at least4m apart")
	var coverage: Dictionary = {}
	for index in range(512):
		var seed_value := "public-round-" + str(index)
		var previous := index % indices.size()
		var first: int = layout.choose(indices, previous, seed_value)
		check(first != previous and indices.has(first), "never repeat previous site")
		check(first == layout.choose(indices, previous, seed_value), "same explicit inputs deterministic")
		var reverse := indices.duplicate()
		reverse.reverse()
		check(first == layout.choose(reverse, previous, seed_value), "eligible order does not alter choice")
		reverse.append(first)
		check(first == layout.choose(reverse, previous, seed_value), "duplicate eligibility does not alter choice")
		coverage[first] = true
	check(coverage.size() == sites.size(), "all approved sites reachable")
	check(layout.choose(PackedInt32Array(), -1, "a") == -1, "no safe site fails closed")
	check(layout.choose(PackedInt32Array([0]), 0, "a") == -1, "no forced same-site fallback")
	check(layout.choose(indices, -1, "") == -1, "empty seed rejected")
	check(layout.choose(indices, -1, "a".repeat(129)) == -1, "seed bounded")
	check(layout.choose(indices, -1, "a".repeat(128)) >= 0, "maximum seed accepted")
	check(layout.choose(indices, -1, "新一轮") >= 0, "UTF8 seed accepted")
	check(layout.choose(PackedInt32Array([0, -1]), -1, "a") == -1, "unknown negative index rejected")
	check(layout.choose(PackedInt32Array([0, sites.size()]), -1, "a") == -1, "unknown positive index rejected")
	check(layout.choose(indices, sites.size(), "a") == -1, "unknown previous index rejected")
	check(layout.choose(indices, -2, "a") == -1, "invalid previous sentinel rejected")
	check(layout.choose(PackedInt32Array([0]), -1, "a") == 0, "one eligible initial site allowed")
	# Observe the engine RNG only in this disposable native test process.
	seed(78163)
	var expected_random := randi()
	seed(78163)
	for index in range(128):
		layout.choose(indices, index % sites.size(), "rng-probe-" + str(index))
	check(randi() == expected_random, "layout leaves global/world RNG sequence unchanged")
	check(indices == PackedInt32Array([0, 1, 2, 3, 4]), "caller eligibility not mutated")
	var changed: Array = sites.duplicate()
	changed[0] = Vector2(999, 999)
	check(layout.CENTRES[0] == Vector2(5, -12), "copied centre list cannot mutate fixed sites")
	# Reuse the recorded real terrain survey, never launch another scene here.
	check(FileAccess.get_sha256(_workspace.path_join(TERRAIN_EVIDENCE)) == TERRAIN_EVIDENCE_SHA, "exact completed frozen-core survey evidence")
	if not failures.is_empty():
		return {}
	var terrain: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(_workspace.path_join(TERRAIN_EVIDENCE)))
	check(terrain.status == "PASS" and terrain.coreSha256 == CORE_SHA and terrain.catalogueSha256 == CATALOGUE_SHA, "survey passed for original terrain and13 actors")
	var json_sites: Array = []
	for centre: Vector2 in sites:
		var coordinates := [float(centre.x), float(centre.y)]
		json_sites.append(coordinates)
		for phase: String in ["denseCoreCandidates", "denseDetailCandidates"]:
			var matches: Array = terrain[phase].filter(func(row: Dictionary) -> bool: return row.centre == coordinates)
			check(matches.size() == 1 and matches[0].allActorsSafe, "site passed actual " + phase)
			if matches.is_empty():
				continue
			check(matches[0].actors.size() == 13, "every13 actor covered at chosen site")
			for actor: Dictionary in matches[0].actors.values():
				check(actor.safe and actor.pathSamples >= 6 and actor.footprintSamplesPerPath >= 48
					and actor.arenaBoundaryMarginM >= 0.0, "dense full-lunge footprint safe")
	return {"sites": json_sites, "selectionSeeds": 512, "terrainEvidenceSha256": TERRAIN_EVIDENCE_SHA,
		"helperSha256": FileAccess.get_sha256(_workspace.path_join("godot/scripts/camp_spawn_layout.gd"))}

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	_workspace = get_script().resource_path.get_base_dir().path_join("../..").simplify_path()
	var probe := arguments.size() == 2 and arguments[0] == "--probe"
	if not probe and arguments.size() != 1:
		quit(1)
		return
	_destination = arguments[-1].simplify_path()
	if not _destination.is_absolute_path() or not _destination.begins_with(_workspace.path_join("artifacts/camp-spawn-v166/")) or FileAccess.file_exists(_destination):
		quit(1)
		return
	var start := Time.get_ticks_usec()
	var result: Dictionary = await core_probe() if probe else selection_tests()
	result.status = "PASS" if failures.is_empty() else "FAIL"
	result.checks = checks
	result.failures = failures
	result.elapsedMs = (Time.get_ticks_usec() - start) / 1000.0
	var output := FileAccess.open(_destination, FileAccess.WRITE)
	if output == null:
		quit(1)
		return
	output.store_string(JSON.stringify(result, "\t") + "\n")
	output.close()
	print("CAMP_SPAWN_TEST: " + JSON.stringify({"status": result.status, "checks": checks, "failures": failures,
		"elapsedMs": result.elapsedMs, "safeCentres": result.get("safeCentres", []), "evidence": _destination}))
	quit(0 if failures.is_empty() else 1)
