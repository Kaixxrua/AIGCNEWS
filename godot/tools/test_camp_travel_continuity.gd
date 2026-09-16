extends "test_camp_hit_sync.gd"
## Independent actual-_process travel regression. Reuses the existing tiny
## TEST-only atlas/mounted renderer/HUD/effects fixture, never a movement stub.
## Run only after owner freeze, with the same explicit fixture.pck invocation
## as test_camp_hit_sync.gd. This script runs NO inherited combined test suite.
## Support plane/obstacles are synthetic: no actual-world or visual QA claim.

const TRAVEL_EXPECTED_SPEED := 2.2
const TRAVEL_EXPECTED_STRIDE := 1.6
const TRAVEL_DT := 0.05
const TRAVEL_LIMIT_STEPS := 1200
const POSITION_EPS := 0.0001
const ALLIES := ["hero", "pet"]

var _capture_support := false
var _support_samples: Array[Vector2] = []
var _support_count := 0
var _ring_blocked := false
var _ring_center := Vector2.ZERO

func expected_ground(point: Vector2) -> Vector3:
	return Vector3(point.x, point.x * 0.025 + point.y * 0.018, point.y)

func ground(point: Vector2) -> Vector3:
	if _capture_support:
		_support_count += 1
		# Observation must not amplify a stuck runtime loop into unbounded test
		# memory growth. Do not alter the ground value to escape such a loop.
		if _support_samples.size() < 16384:
			_support_samples.append(point)
		if _support_count == 16384:
			print("CAMP_TRAVEL_EXCESS_SUPPORT: same process call exceeded 16384 probes; last=" + str(_support_samples.slice(-12)))
	return expected_ground(point)

func permitted(point: Vector2) -> bool:
	# A closed annulus leaves the actor's current footprint and remote arena
	# valid but prevents any continuous route out. It is not a planner stub.
	var radius := point.distance_to(_ring_center)
	return not (_ring_blocked and radius >= 0.80 and radius <= 1.05)

func xz(point: Vector3) -> Vector2:
	return Vector2(point.x, point.z)

func travel_fixture(value: Dictionary, catalogue: Dictionary = {}) -> Dictionary:
	_ring_blocked = false
	_capture_support = false
	_support_samples.clear()
	var test := fixture(value, catalogue)
	if not test.is_empty():
		check(not test.scene._travel_active and not test.scene._travel_blocked,
			"initial actors may be placed once; first load is not an unseen journey")
		for role: String in ALLIES:
			check(test.scene._actors[role].get("placed", false), "initial ally has an explicitly established root: " + role)
	return test

func roots(scene: Node3D) -> Dictionary:
	var value: Dictionary = {}
	for role: String in ALLIES:
		value[role] = scene._actors[role].root.position
	return value

func walk_view(scene: Node3D) -> Dictionary:
	var value: Dictionary = {}
	for role: String in ALLIES:
		var actor: Dictionary = scene._actors[role]
		value[role] = {"position": actor.root.position, "frame": actor.frame,
			"distance": actor.get("walk_distance", -1.0), "direction": actor.get("walk_direction"),
			"sprite": actor.sprite.transform, "texture": actor.sprite.texture,
			"shadow": actor.shadow.global_transform, "visible": actor.root.visible}
	return value

func descendants(node: Node) -> PackedInt64Array:
	var result := PackedInt64Array([node.get_instance_id()])
	for child: Node in node.get_children():
		result.append_array(descendants(child))
	return result

func assert_roots_unchanged(scene: Node3D, before: Dictionary, label: String) -> void:
	for role: String in ALLIES:
		check(scene._actors[role].root.position.distance_to(before[role]) <= POSITION_EPS,
			"%s: %s before=%s after=%s" % [label, role, before[role], scene._actors[role].root.position])

func assert_paths_begin_at_roots(scene: Node3D, before: Dictionary) -> void:
	for role: String in ALLIES:
		var path: Variant = scene._travel_paths.get(role)
		check(path is PackedVector2Array and path.size() >= 2,
			"a genuine nonzero route is retained for each existing ally: " + role)
		if not path is PackedVector2Array or path.size() < 2:
			continue
		check(path[0].distance_to(xz(before[role])) <= POSITION_EPS,
			"route starts at the actual current/lunging root, not the old station: " + role)
		check(path[-1].distance_to(scene._actors[role].station) <= POSITION_EPS,
			"route ends at the new role/hover station: " + role)
		check(scene._travel_points.get(role, Vector2(INF, INF)).distance_to(xz(before[role])) <= POSITION_EPS,
			"cached travel point initially matches the preserved root: " + role)

func assert_no_remote_combat(scene: Node3D, expected_ratio: float, label: String) -> void:
	check(not scene._combat_cast_ready(), label + ": distant actors cannot satisfy cast readiness")
	check(scene._current_cast().is_empty(), label + ": no actor-local cast is manufactured while walking/blocked")
	check(scene._effects.debug_state().activeRoles.is_empty(), label + ": fixed effect pool has no distant attacks")
	for role: String in IDS:
		check(not scene._effects._pool[role].visible, label + ": real effect mesh is hidden: " + role)
	var hud: Dictionary = scene._boss_hud.debug_state()
	check(not hud.cast.visible and not hud.damage.visible and not hud.ultimate.visible,
		label + ": real HUD cannot leak a skill, damage number or old top banner")
	check(scene._damage_amount == 0 and scene._damage_age < 0.0,
		label + ": no hit feedback is created by confirmation, travel or route failure")
	assert_ratio(scene, expected_ratio, label + ": pending HP stays undisplayed until an actual post-arrival hit")

func assert_ground_contact(scene: Node3D, role: String, sampled: bool) -> void:
	var actor: Dictionary = scene._actors[role]
	var point := xz(actor.root.position)
	var foot := expected_ground(point)
	check(actor.root.position.distance_to(foot) <= POSITION_EPS,
		"walking root uses the current non-flat ground height: " + role)
	check(actor.shadow.global_position.distance_to(foot + Vector3.UP * 0.016) <= POSITION_EPS,
		"ground shadow follows the current foot, not the destination or hover sprite: " + role)
	var normal := Vector3(-0.025, 1.0, -0.018).normalized()
	check(actor.shadow.global_basis.y.normalized().dot(normal) > 0.9999,
		"contact plane follows the sampled local slope: " + role)
	if sampled:
		check(_support_samples.any(func(probe: Vector2) -> bool: return probe.distance_to(point) <= POSITION_EPS),
			"actual process calls the supplied sampler at this frame's foot: " + role)
	for offset: Vector2 in [Vector2.ZERO, Vector2.RIGHT, Vector2.LEFT, Vector2.UP, Vector2.DOWN,
		Vector2(1, 1).normalized(), Vector2(-1, 1).normalized(), Vector2(1, -1).normalized(), Vector2(-1, -1).normalized()]:
		check(permitted(point + offset * actor.radius), "actual moving footprint never enters the test obstacle: " + role)
	var opacity: float = actor.shadow.material_override.get_shader_parameter("contact_opacity")
	if actor.hovering:
		check(actor.sprite.position.y >= 1.19 - POSITION_EPS and actor.sprite.position.y <= 1.31 + POSITION_EPS,
			"flying pet keeps its modest shoulder-height hover over the sampled foot")
		check(close_enough(opacity, 0.10), "flying pet retains the lower-opacity ground shadow")
	else:
		check(absf(actor.sprite.position.y) <= POSITION_EPS and close_enough(opacity, 0.23),
			"ground actor does not acquire hover elevation or a raised shadow: " + role)

func travel_step(scene: Node3D, seconds: float = TRAVEL_DT) -> Dictionary:
	var before := walk_view(scene)
	var phase: float = scene._motion_clock
	var was_active: bool = scene._travel_active
	var was_blocked: bool = scene._travel_blocked
	_support_samples.clear()
	_support_count = 0
	_capture_support = true
	step(scene, seconds)
	_capture_support = false
	if scene._travel_blocked and not was_blocked:
		var boss: Dictionary = scene._actors.boss
		var near_boss: Array = []
		for point: Vector2 in _support_samples:
			var clearance: float = point.distance_to(boss.station) - boss.radius - 0.10
			if clearance <= 0.0001 and near_boss.size() < 8:
				near_boss.append({"point": point, "clearance": clearance})
		print("CAMP_TRAVEL_BLOCKED_TRACE: " + str({"motion": scene._motion_clock, "site": scene._spawn_index,
			"paths": scene._travel_paths, "points": scene._travel_points, "indices": scene._travel_indices,
			"roots": roots(scene), "boss_station": boss.station, "boss_radius": boss.radius,
			"near_boss_probes": near_boss, "ring_obstacle": _ring_blocked}))
	var after := walk_view(scene)
	var limit := TRAVEL_EXPECTED_SPEED * clampf(seconds, 0.0, 0.1)
	for role: String in ALLIES:
		var distance: float = before[role].position.distance_to(after[role].position)
		check(distance <= limit + POSITION_EPS,
			"actual per-frame Euclidean speed bound, including resumed/arrival steps: %s distance=%.9f limit=%.9f" % [role, distance, limit])
		if distance > POSITION_EPS:
			check(was_active and not was_blocked, "an ally only moves through an active safe route: " + role)
			check(after[role].distance > before[role].distance,
				"walk phase advances with actual covered distance: " + role)
			if scene._travel_active and not scene._travel_blocked:
				check(after[role].frame >= 8 and after[role].frame <= 15,
					"moving ally uses the separate eight-frame walk/flap row, never idle/attack: " + role)
				var expected_frame := 8 + int(floorf(after[role].distance / TRAVEL_EXPECTED_STRIDE * 8.0)) % 8
				check(after[role].frame == expected_frame and after[role].texture == scene._actors[role].frames[expected_frame],
					"actual Sprite3D texture follows the agreed distance/1.6m eight-frame walking cadence: " + role)
				var route: PackedVector2Array = scene._travel_paths.get(role, PackedVector2Array())
				if route.size() == 2 and xz(after[role].position).distance_to(route[-1]) > limit + POSITION_EPS:
					check(absf(distance - limit) < 0.001,
						"unobstructed interior travel is constant-speed, not eased interpolation: " + role)
			assert_ground_contact(scene, role, true)
			var direction: Variant = after[role].direction
			if scene._travel_active and not scene._travel_blocked:
				check(direction is Vector2 and direction.is_finite() and absf(direction.length() - 1.0) < 0.001,
					"in-transit moving actor retains a finite unit walk direction: " + role)
			elif scene._travel_blocked:
				# One ally may finish its safe step before the other detects the
				# obstruction. Its last direction is valid historical metadata;
				# the shared blocked state must nevertheless render both idle.
				check(after[role].frame >= 0 and after[role].frame < 8
					and after[role].texture == scene._actors[role].frames[after[role].frame],
					"new obstruction ends the safe-prefix step in idle, never attack or stale walking: " + role)
				check(direction is Vector2 and direction.is_finite()
					and (direction == Vector2.ZERO or absf(direction.length() - 1.0) < 0.001),
					"blocked actor keeps only a finite last movement direction, not an invalid interpolation vector: " + role)
			elif not scene._travel_active:
				check(direction == Vector2.ZERO and after[role].frame >= 0 and after[role].frame < 8,
					"arrival's final partial step ends idle at the endpoint, not in attack or stale walking: " + role)
		else:
			check(close_enough(before[role].distance, after[role].distance),
				"a stationary/finished ally cannot run walk frames from wall-clock time: " + role)
	if was_active or was_blocked:
		check(close_enough(scene._motion_clock, phase), "travel/failure freezes combat time, even on the arrival frame")
	return {"before": before, "after": after}

func walk_until_arrival(scene: Node3D, expected_ratio: float, repeated: Dictionary = {}) -> bool:
	var objects := identity(scene)
	var nodes := descendants(scene)
	var phase: float = scene._motion_clock
	var seen := {"hero": {}, "pet": {}}
	var travelled := {"hero": 0.0, "pet": 0.0}
	var ticks := 0
	while scene._travel_active and not scene._travel_blocked and ticks < TRAVEL_LIMIT_STEPS:
		if not repeated.is_empty() and ticks % 7 == 0:
			var old_roots := roots(scene)
			var old_view := walk_view(scene)
			var paths: Dictionary = scene._travel_paths.duplicate(true)
			var points: Dictionary = scene._travel_points.duplicate(true)
			check(apply_without_feedback(scene, repeated), "repeated route-time liveness snapshot is accepted")
			assert_roots_unchanged(scene, old_roots, "same-round snapshot cannot consume or restart a route")
			check(walk_view(scene) == old_view and scene._travel_paths == paths and scene._travel_points == points,
				"same snapshot preserves route progress, real walk frame/distance and hover pose")
		var sample := travel_step(scene)
		ticks += 1
		for role: String in ALLIES:
			var moved: float = sample.before[role].position.distance_to(sample.after[role].position)
			travelled[role] += moved
			if moved > POSITION_EPS and scene._travel_active:
				seen[role][sample.after[role].frame] = true
		check(identity(scene) == objects and descendants(scene) == nodes,
			"route frames/snapshots reuse all actors, atlas textures and fixed HUD/effect nodes")
		if scene._travel_active:
			assert_no_remote_combat(scene, expected_ratio, "in-transit frame %d" % ticks)
	var arrived: bool = not scene._travel_active and not scene._travel_blocked
	check(arrived and ticks < TRAVEL_LIMIT_STEPS, "safe test route reaches both targets within 60 actual shared-clock seconds")
	check(close_enough(scene._motion_clock, phase), "route completion does not charge travel time to the fight")
	if arrived:
		for role: String in ALLIES:
			check(xz(scene._actors[role].root.position).distance_to(scene._actors[role].station) <= POSITION_EPS,
				"both allies physically arrive before the fight can reopen: " + role)
			check(travelled[role] > 1.0 and seen[role].size() >= 2,
				"nontrivial real walking, not hidden teleport/one repeated still: %s metres=%.3f frames=%s" % [role, travelled[role], seen[role].keys()])
			assert_ground_contact(scene, role, false)
	print("CAMP_TRAVEL_ROUTE: ticks=%d metres=%s site=%s phase=%.6f arrived=%s" % [ticks, travelled, scene._spawn_index, phase, arrived])
	return arrived

func begin_formal_route(scene: Node3D, nonce: String, template: Dictionary = {}) -> Dictionary:
	var next := state(1000, "fighting", nonce) if template.is_empty() else template.duplicate(true)
	next.roundId = nonce
	next.elapsed = 0.0
	next.bossHp = 1000
	var before := roots(scene)
	var site: int = scene._spawn_index
	check(apply_without_feedback(scene, next), "new formal round snapshot selects the next Boss site")
	assert_roots_unchanged(scene, before, "formal apply_snapshot must never relocate existing hero/pet roots")
	check(scene._spawn_index != site, "continuity test genuinely selects a different approved Boss clearing")
	check(scene._travel_active and not scene._travel_blocked, "real existing allies enter a safe travel state")
	if scene._travel_active and not scene._travel_blocked:
		assert_paths_begin_at_roots(scene, before)
	assert_no_remote_combat(scene, 1.0, "new round before its first travel frame")
	return next

func test_formal_public_actor_travel() -> void:
	var catalogue := public_fixture_catalogue()
	for id: String in PUBLIC_ROLES:
		print("CAMP_TRAVEL_CASE_BEGIN: " + id)
		var initial := state(1000, "fighting", "travel-first-" + id)
		initial.heroAssetId = "hero_ranger"
		initial.petAssetId = "pet_deer"
		initial.bossAssetId = "boss_ancient_guardian"
		initial[PUBLIC_ROLES[id] + "AssetId"] = id
		var test := travel_fixture(initial, catalogue)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		var objects := identity(scene)
		# A real lunge has already displaced the hero from its idle station.
		# Preserving the station alone must not satisfy the continuity test.
		advance(scene, 0.20)
		check(xz(scene._actors.hero.root.position).distance_to(scene._actors.hero.station) > 0.10,
			"formal change starts from a genuine in-progress lunge, not a hand-set coordinate")
		var next := begin_formal_route(scene, "travel-next-" + id, initial)
		print("CAMP_TRAVEL_CASE_PLANNED: %s site=%s paths=%s" % [id, scene._spawn_index, scene._travel_paths])
		next.bossHp = 750
		var before := roots(scene)
		check(apply_without_feedback(scene, next), "confirmed decrease can queue during a journey")
		assert_roots_unchanged(scene, before, "HP confirmation is not movement")
		assert_no_remote_combat(scene, 1.0, "confirmed lower HP while distant")
		if walk_until_arrival(scene, 1.0, next):
			check(scene._combat_cast_ready(), "only physical arrival makes all roles combat-ready")
			step(scene, 0.05)
			assert_cast_actor_clearance(scene, "hero")
			advance_to(scene, 0.6 - EPSILON)
			assert_ratio(scene, 1.0, "arrival/charge alone cannot release pending HP")
			advance_to(scene, 0.6)
			assert_ratio(scene, 0.75, "first real post-arrival hero impact releases confirmed HP")
			assert_damage_hud(scene, true, 250)
			assert_cast_actor_clearance(scene, "hero")
			next.bossHp = 700
			check(apply_without_feedback(scene, next), "post-arrival pending pet hit")
			advance_to(scene, 2.1)
			assert_ratio(scene, 0.70, "real pet impact uses the new target after travelling")
			assert_damage_hud(scene, true, 50)
			assert_cast_actor_clearance(scene, "pet")
			check(identity(scene) == objects, "travel and resumed skills never reconstruct existing actors or textures")
		test.world.free()
	print("CAMP_TRAVEL_PUBLIC_IDS: 13 public style/hover IDs with synthetic TEST art; not real-art terrain certification")

func test_guest_boundary_continuity() -> void:
	var initial := guest()
	var test := travel_fixture(initial)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var objects := identity(scene)
	for cycle in range(1, 4):
		var boundary := float(cycle) * 31.2
		advance_to(scene, boundary - 0.01)
		var before := roots(scene)
		var site: int = scene._spawn_index
		var choices := spawn_count(scene)
		step(scene, 0.01)
		for role: String in ALLIES:
			check(scene._actors[role].root.position.distance_to(before[role]) <= TRAVEL_EXPECTED_SPEED * 0.01 + POSITION_EPS,
				"guest 31.2 boundary is a continuous process frame, never a teleport: cycle=%d role=%s before=%s after=%s" % [cycle, role, before[role], scene._actors[role].root.position])
		check(scene._spawn_index != site and spawn_count(scene) == choices + 1, "one new Boss site is selected at the real integer guest boundary")
		check(scene._travel_active and not scene._travel_blocked and scene._actors.boss.root.visible,
			"new full-health guest Boss waits for the existing walking allies")
		assert_no_remote_combat(scene, 1.0, "guest cycle reset is not a remote attack")
		if not walk_until_arrival(scene, 1.0, initial):
			break
		check(close_enough(scene._motion_clock, boundary), "full next guest battle phase starts only after both allies arrive")
		advance_to(scene, boundary + 0.6 - EPSILON)
		assert_ratio(scene, 1.0, "next guest round has its entire first windup after travelling")
		advance_to(scene, boundary + 0.6)
		assert_ratio(scene, 0.92, "guest first post-arrival impact remains the exact eight-step HP contract")
		assert_damage_hud(scene, true, 80)
	check(identity(scene) == objects, "more than two real guest cycles reuse actors/resources through walking and death")
	test.world.free()

func test_route_pause_hidden_stale() -> void:
	for name: String in ["local_pause", "server_pause", "stale", "renderer_hidden", "world_hidden"]:
		var test := travel_fixture(state(1000))
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		begin_formal_route(scene, "travel-gate-" + name)
		travel_step(scene)
		travel_step(scene)
		check(scene._travel_active, "freeze case genuinely pauses an unfinished journey: " + name)
		gate(test, name, true)
		travel_step(scene, 0.0)
		var held := walk_view(scene)
		var points: Dictionary = scene._travel_points.duplicate(true)
		var paths: Dictionary = scene._travel_paths.duplicate(true)
		var phase: float = scene._motion_clock
		# Large wall/shared-clock gaps are consumed at the same gate. On resume
		# only the next ordinary delta may be spent, never accumulated backlog.
		travel_step(scene, 2.0)
		travel_step(scene, 3.0)
		check(walk_view(scene) == held and scene._travel_points == points and scene._travel_paths == paths,
			"pause/hidden/stale preserves root, walk distance/frame, hover, shadow and path cursor: " + name)
		check(close_enough(scene._motion_clock, phase) and close_enough(scene._last_shared_clock, _clock),
			"frozen route consumes shared time without combat or future catch-up: " + name)
		gate(test, name, false)
		var resumed := travel_step(scene)
		check(resumed.before.hero.position.distance_to(resumed.after.hero.position) > POSITION_EPS,
			"resume genuinely continues walking rather than permanently freezing: " + name)
		assert_no_remote_combat(scene, 1.0, "resumed partial journey: " + name)
		test.world.free()

func test_retarget_and_zero_delta() -> void:
	var test := travel_fixture(state(1000))
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	# Pet is the lunging ally at this phase, independently of the hero case.
	advance(scene, 1.70)
	check(xz(scene._actors.pet.root.position).distance_to(scene._actors.pet.station) > 0.10,
		"retarget coverage starts with an actual pet lunge")
	begin_formal_route(scene, "travel-retarget-a")
	for tick in range(5):
		travel_step(scene)
	travel_step(scene, 3.0)
	var old_positions := roots(scene)
	var old_phase: float = scene._motion_clock
	var old_points: Dictionary = scene._travel_points.duplicate(true)
	var old_walk := walk_view(scene)
	for tick in range(5):
		# Directly exercise the no-step refresh path used by snapshots. It may
		# update visuals but cannot consume a cached route or reset walk frames.
		scene._update_actors(0.0)
		travel_step(scene, 0.0)
	assert_roots_unchanged(scene, old_positions, "zero-delta actor refresh cannot teleport or march allies")
	check(walk_view(scene) == old_walk and scene._travel_points == old_points and close_enough(scene._motion_clock, old_phase),
		"zero-delta refresh keeps distance-driven animation and route progress identical")
	var next := begin_formal_route(scene, "travel-retarget-b")
	assert_roots_unchanged(scene, old_positions, "new round mid-route replans from current roots, not either arena")
	walk_until_arrival(scene, 1.0, next)
	test.world.free()

func test_unreachable_route_waits() -> void:
	var test := travel_fixture(state(1000))
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var before := roots(scene)
	var objects := identity(scene)
	_ring_center = xz(before.hero)
	_ring_blocked = true
	var next := state(1000, "fighting", "travel-unreachable")
	check(apply_without_feedback(scene, next), "valid next-round snapshot can have a locally unreachable route")
	assert_roots_unchanged(scene, before, "failed real path planning must retain both existing roots")
	check(scene._travel_blocked, "unreachable test obstacle produces the explicit blocked state")
	next.bossHp = 650
	check(apply_without_feedback(scene, next), "real HP can queue while movement is locally blocked")
	var phase: float = scene._motion_clock
	for tick in range(330):
		travel_step(scene, 0.1)
		assert_roots_unchanged(scene, before, "blocked journey waits in place instead of sliding/teleporting")
		assert_no_remote_combat(scene, 1.0, "blocked beyond a full ordinary/ultimate cycle")
		if tick % 30 == 0:
			check(apply_without_feedback(scene, next), "blocked-route repeat cannot turn failure into a remote fight")
	check(close_enough(scene._motion_clock, phase), "33 seconds of blocked shared time cannot spend any fight phase")
	check(identity(scene) == objects, "failed/repeated routes do not create replacement actors or resources")
	_ring_blocked = false
	test.world.free()

func test_zero_confirmation_during_travel() -> void:
	var test := travel_fixture(state(1000))
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var next := begin_formal_route(scene, "travel-confirmed-final")
	travel_step(scene)
	next.mode = "defeated"
	next.bossHp = 0
	var before := roots(scene)
	check(apply_without_feedback(scene, next), "confirmed zero may arrive before the actors have reached the Boss")
	assert_roots_unchanged(scene, before, "zero confirmation cannot bypass travel by moving allies to their attack stations")
	check(scene._pending_death and not scene._death_active, "received zero queues the real final hit, not a remote death")
	assert_no_remote_combat(scene, 1.0, "confirmed zero still waits for visible actors")
	if walk_until_arrival(scene, 1.0, next):
		var windup: float = scene._motion_clock
		advance_to(scene, windup + 0.6 - EPSILON)
		assert_ratio(scene, 1.0, "post-travel confirmed finisher still has a complete 0.6-second windup")
		advance_to(scene, windup + 0.6)
		assert_ratio(scene, 0.0, "only the post-arrival final hit shows confirmed zero")
		assert_damage_hud(scene, true, 1000)
		check(scene._death_active and close_enough(scene._current_death_age(), 0.0), "travel never consumes any part of the final 3.2-second death")
		advance(scene, 3.2001)
		check(not scene._actors.boss.root.visible and scene._effects.debug_state().activeRoles.is_empty(),
			"post-travel death still closes the full body/ember tail")
	test.world.free()

func test_cached_hover_swap_during_cooldown() -> void:
	# Both outfits already live in the mounted TEST fixture; no missing-asset
	# stub or loader callback can hide the cached swap's synchronous behaviour.
	var initial := state(1000, "fighting", "travel-cached-hover")
	initial.heroAssetId = "hero_ranger"
	initial.petAssetId = "pet_dragon"
	initial.bossAssetId = "boss_ancient_guardian"
	var test := travel_fixture(initial, public_fixture_catalogue())
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var hero_id: int = scene._actors.hero.root.get_instance_id()
	var boss_id: int = scene._actors.boss.root.get_instance_id()
	var deer: Dictionary = initial.duplicate(true)
	deer.petAssetId = "pet_deer"
	check(apply_without_feedback(scene, deer), "preloaded hover pet can change to the already-mounted ground pet")
	if not drain_travel(scene):
		test.world.free()
		return
	advance(scene, 0.2)
	var zero: Dictionary = deer.duplicate(true)
	zero.bossHp = 0
	check(apply_without_feedback(scene, zero), "cached-swap case confirms an actual completed Boss defeat")
	advance(scene, 0.6)
	advance(scene, 3.2001)
	check(not scene._actors.boss.root.visible, "Boss body is genuinely gone before the cooldown outfit swap")
	var rest: Dictionary = zero.duplicate(true)
	rest.mode = "cooldown"
	rest.roundId = ""
	check(apply_without_feedback(scene, rest), "roundless cooldown retains the completed death")
	var before := roots(scene)
	var hover: Dictionary = rest.duplicate(true)
	hover.petAssetId = "pet_dragon"
	check(apply_without_feedback(scene, hover), "already-loaded dragon is selected again during cooldown")
	assert_roots_unchanged(scene, before, "cached ground-to-hover swap retains the party's actual feet")
	check(scene._travel_active and not scene._travel_blocked and scene._actors.pet.hovering,
		"cooldown hover station change starts a real journey without requiring a living Boss")
	var objects := identity(scene)
	var phase: float = scene._motion_clock
	var ticks := 0
	var moved := 0.0
	while scene._travel_active and not scene._travel_blocked and ticks < TRAVEL_LIMIT_STEPS:
		var sample := travel_step(scene)
		moved += sample.before.pet.position.distance_to(sample.after.pet.position)
		ticks += 1
		check(not scene._actors.boss.root.visible, "cached cooldown pet travel cannot resurrect/show the defeated Boss for even one process frame")
		check(scene._current_cast().is_empty() and scene._effects.debug_state().activeRoles.is_empty(),
			"cooldown movement never creates combat/cast/death replay effects")
		var hud: Dictionary = scene._boss_hud.debug_state()
		check(not hud.damage.visible and not hud.cast.visible, "cooldown travel cannot replay an old hit number or skill bubble")
		check(scene._snapshot == hover and close_enough(scene._motion_clock, phase), "cooldown movement preserves the supplied public state and freezes combat")
		check(identity(scene) == objects, "cached outfit is constructed once; walking cannot recreate its resources")
	check(not scene._travel_active and not scene._travel_blocked and moved > 3.0 and ticks < TRAVEL_LIMIT_STEPS,
		"ground-to-hover cooldown trip actually reaches its distinct station while the Boss stays hidden")
	assert_ground_contact(scene, "pet", false)
	step(scene, 0.05)
	check(not scene._actors.boss.root.visible and scene._current_cast().is_empty(), "first ordinary process after cooldown arrival cannot restart the Boss")
	check(scene._actors.hero.root.get_instance_id() == hero_id and scene._actors.boss.root.get_instance_id() == boss_id,
		"pet swap never rebuilds the retained hero or defeated Boss")
	test.world.free()

func test_same_round_hp_snapshot_unblocks_same_site() -> void:
	var test := travel_fixture(state(1000))
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var next := begin_formal_route(scene, "travel-obstacle-cleared")
	for tick in range(3):
		travel_step(scene)
	var targets: Dictionary = {}
	for role: String in ALLIES:
		targets[role] = scene._travel_paths[role][-1]
	var site := spawn_view(scene)
	var choices := spawn_count(scene)
	var objects := identity(scene)
	_ring_center = xz(scene._actors.hero.root.position)
	_ring_blocked = true
	var obstruction_steps := 0
	while scene._travel_active and not scene._travel_blocked and obstruction_steps < 20:
		travel_step(scene)
		obstruction_steps += 1
	check(scene._travel_blocked, "new test obstacle is encountered by real per-frame footprint validation, not a manually set flag")
	var held := roots(scene)
	var phase: float = scene._motion_clock
	assert_no_remote_combat(scene, 1.0, "mid-route obstacle holds the party")
	for tick in range(3):
		travel_step(scene)
		assert_roots_unchanged(scene, held, "newly blocked route remains at its last safe feet on subsequent process frames")
		for role: String in ALLIES:
			check(scene._actors[role].frame >= 0 and scene._actors[role].frame < 8,
				"blocked party visibly waits idle rather than walking or attacking: " + role)
		assert_no_remote_combat(scene, 1.0, "obstructed party stays idle until a fresh state permits recovery")
	_ring_blocked = false
	next.bossHp = 750
	check(apply_without_feedback(scene, next), "same assets/round with fresh confirmed HP can retry after the obstacle is cleared")
	assert_roots_unchanged(scene, held, "same-site retry starts from the actually held roots, not original or target stations")
	check(scene._travel_active and not scene._travel_blocked, "fresh valid state resumes the previously blocked journey")
	check(spawn_view(scene) == site and spawn_count(scene) == choices,
		"unblocking cannot reroll the Boss site, key or encounter selection count")
	check(close_enough(scene._motion_clock, phase), "HP refresh/replan cannot consume blocked fight time")
	assert_paths_begin_at_roots(scene, held)
	for role: String in ALLIES:
		check(scene._travel_paths[role][-1].distance_to(targets[role]) <= POSITION_EPS,
			"retry retains the original route's endpoint: " + role)
	if walk_until_arrival(scene, 1.0, next):
		advance_to(scene, 0.6 - EPSILON)
		assert_ratio(scene, 1.0, "route recovery cannot spend pending HP before the next visible impact")
		advance_to(scene, 0.6)
		assert_ratio(scene, 0.75, "first genuine post-recovery impact applies the received HP once")
		assert_damage_hud(scene, true, 250)
		assert_cast_actor_clearance(scene, "hero")
		check(identity(scene) == objects and scene._snapshot == next, "recovery preserves actor resources and the exact supplied public HP snapshot")
	_ring_blocked = false
	test.world.free()

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	check(arguments.size() == 1, "one explicit tiny fixture PCK is required")
	if arguments.size() != 1 or not prepare(arguments[0]):
		print("CAMP_TRAVEL_TEST: NOT_READY_OR_INVALID_INPUT (%d failed checks)" % _failures)
		quit(1)
		return
	root.size = Vector2i(1280, 800)
	root.content_scale_size = Vector2i(1280, 800)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	var constants: Dictionary = _code.get_script_constant_map()
	check(constants.get("TRAVEL_SPEED") == TRAVEL_EXPECTED_SPEED, "agreed public travel speed is 2.2 metres per second")
	check(constants.get("WALK_STRIDE") == TRAVEL_EXPECTED_STRIDE, "walking atlas cadence is tied to a 1.6-metre stride")
	test_formal_public_actor_travel()
	test_guest_boundary_continuity()
	test_route_pause_hidden_stale()
	test_retarget_and_zero_delta()
	test_unreachable_route_waits()
	test_zero_confirmation_during_travel()
	test_cached_hover_swap_during_cooldown()
	test_same_round_hp_snapshot_unblocks_same_site()
	await process_frame
	print("CAMP_TRAVEL_LIMITS: real mounted renderer/helper/HUD/effects and manual _process on synthetic ground; no real-world, GPU, Web/QHD, 60fps or reward proof")
	print("CAMP_TRAVEL_TEST: %s (%d checks, %d failures)" % ["PASS" if _failures == 0 else "FAIL", _checks, _failures])
	quit(0 if _failures == 0 else 1)
