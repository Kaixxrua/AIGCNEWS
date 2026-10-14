extends SceneTree
## Independent source-level native regression for the public hit/HP contract.
## Run ONLY after the renderer/VFX owners announce source readiness:
## Godot --headless --path <existing isolated test project> --script <this file>
##   -- <tiny fixture.pck made by build_camp_presentation.test_fixture/prepare>
## Uses the existing synthetic TEST-only atlas builder, never real actor PNGs.
## All five packed module sources must exactly match the owners' current files.
## No production build/export, world mount, browser, private state or networking.
## A synthetic support plane tests control flow, NOT real terrain or visual QA.

const IDS := {"hero": "hero-test", "pet": "pet-test", "boss": "boss-test"}
const PERIOD_US := 31200000
const HIT_US := [600000, 2100000, 5800000, 7300000, 11830000, 21400000, 22900000, 26600000, 28100000]
const HIT_ROLES := ["hero", "pet", "hero", "pet", "hero", "hero", "pet", "hero", "pet"]
const GUEST_RATIOS := [0.92, 0.87, 0.76, 0.69, 0.40, 0.25, 0.18, 0.0]
const GUEST_DAMAGE := [80, 50, 110, 70, 290, 150, 70, 180]
const EXPECTED_STATIONS := {"hero": Vector2(-2.35, 1.10), "pet": Vector2(-1.35, 2.10), "boss": Vector2(1.85, -0.65)}
const EXPECTED_HOVER_STATION := Vector2(-2.10, -3.20)
const EXPECTED_CENTRES := [Vector2(5.0, -12.0), Vector2(2.0, -15.0), Vector2(8.0, -15.0), Vector2(2.0, -9.0), Vector2(8.0, -9.0)]
const PUBLIC_ROLES := {"hero_ranger": "hero", "hero_knight": "hero", "hero_mage": "hero",
	"hero_bard": "hero", "hero_alchemist": "hero", "hero_astrologer": "hero",
	"pet_deer": "pet", "pet_fox": "pet", "pet_rabbit": "pet", "pet_owl": "pet",
	"pet_finch": "pet", "pet_dragon": "pet", "boss_ancient_guardian": "boss"}
const EPSILON := 0.0001
const STEP := 0.05

var _checks := 0
var _failures := 0
var _clock := 0.0
var _code: Script
var _catalogue: Dictionary
var _source_directory := ""
var _spawn_commits: Dictionary = {}

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	_checks += 1
	if not value:
		_failures += 1
		print("CAMP_HIT_SYNC_FAIL: " + label)

func close_enough(a: float, b: float) -> bool:
	return is_finite(a) and is_finite(b) and absf(a - b) < 0.000001

func ground(point: Vector2) -> Vector3:
	return Vector3(point.x, point.x * 0.025 + point.y * 0.018, point.y)

func permitted(_point: Vector2) -> bool:
	return true

func clock_value() -> float:
	return _clock

func state(hp: int = 900, mode: String = "fighting", nonce: String = "public-hit-sync-01") -> Dictionary:
	return {"mode": mode, "heroAssetId": IDS.hero, "petAssetId": IDS.pet,
		"bossAssetId": IDS.boss, "elapsed": 0.0, "duration": 600.0,
		"roundId": nonce, "bossHp": hp, "bossMaxHp": 1000}

func guest(nonce: String = "") -> Dictionary:
	var value := state(1000, "demo", nonce)
	value.erase("bossHp")
	value.erase("bossMaxHp")
	value.elapsed = 0.0
	value.duration = 0.0
	return value

func prepare(fixture_path: String) -> bool:
	var file := FileAccess.open(fixture_path, FileAccess.READ)
	var valid: bool = file != null and file.get_length() < 1024 * 1024 and fixture_path.get_file() == "fixture.pck"
	check(valid, "explicit sub-1MB test fixture only; never a production or world PCK")
	if not valid:
		return false
	check(ProjectSettings.load_resource_pack(fixture_path, false), "non-replacing tiny test fixture mount")
	print("CAMP_HIT_SYNC_FIXTURE: " + FileAccess.get_sha256(fixture_path))
	var raw: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://camp_presentation/manifest.json"))
	if not raw is Dictionary:
		check(false, "mounted public catalogue is readable")
		return false
	_catalogue = raw
	_source_directory = get_script().resource_path.get_base_dir().get_base_dir().path_join("scripts")
	_code = load("res://camp_presentation/camp_presentation.gd")
	check(_code != null and _code.can_instantiate(), "current renderer compiles in the tiny isolated fixture")
	if _code == null or not _code.can_instantiate():
		return false
	var modules: Dictionary = _code.get_script_constant_map()
	for pair: Array in [["", "camp_presentation.gd"], ["CombatEffects", "camp_combat_effects.gd"], ["BossHud", "camp_boss_hud.gd"], ["SpawnLayout", "camp_spawn_layout.gd"]]:
		var module: Script = _code if pair[0] == "" else modules.get(pair[0])
		var path := _source_directory.path_join(pair[1])
		check(module != null and module.source_code == FileAccess.get_file_as_string(path)
			and FileAccess.get_sha256("res://camp_presentation/" + pair[1]) == FileAccess.get_sha256(path), "executed current source identity: " + pair[1])
		print("CAMP_HIT_SYNC_SOURCE: %s %s" % [pair[1], FileAccess.get_sha256(path)])
	var travel_module: Script
	for value: Variant in modules.values():
		if value is Script and value.resource_path.get_file() == "camp_travel_path.gd":
			travel_module = value
	var travel_path := _source_directory.path_join("camp_travel_path.gd")
	check(travel_module != null and travel_module.source_code == FileAccess.get_file_as_string(travel_path)
		and FileAccess.get_sha256("res://camp_presentation/camp_travel_path.gd") == FileAccess.get_sha256(travel_path),
		"executed current source identity: camp_travel_path.gd (actual renderer preload)")
	print("CAMP_HIT_SYNC_SOURCE: camp_travel_path.gd " + FileAccess.get_sha256(travel_path))
	var methods: Array = _code.get_script_method_list()
	for method: String in ["_boss_hit_between", "_displayed_boss_ratio", "_confirmed_boss_ratio", "_current_death_age", "_actor_screen_rect", "_current_cast"]:
		var found: bool = methods.any(func(entry: Dictionary) -> bool: return entry.name == method)
		check(found, "owner's agreed method is present: " + method)
		if not found:
			return false
	var properties: Array = _code.get_script_property_list()
	for field: String in ["_damage_amount", "_damage_age", "_damage_heavy", "_spawn_index", "_spawn_key", "_spawn_ready", "_arena_center",
		"_travel_active", "_travel_blocked", "_travel_paths", "_travel_points", "_travel_indices", "_locomotion_clock"]:
		var found: bool = properties.any(func(entry: Dictionary) -> bool: return entry.name == field)
		check(found, "owner's agreed damage-feedback field is ready: " + field)
		if not found:
			return false
	var hud_module: Script = modules.get("BossHud")
	for api: String in ["present_damage", "present_cast"]:
		var available: bool = hud_module != null and hud_module.get_script_method_list().any(func(entry: Dictionary) -> bool: return entry.name == api)
		check(available, "HUD owner's API is ready; no stub replaces it: " + api)
		if not available:
			return false
	var cast_api: bool = hud_module.get_script_method_list().any(func(entry: Dictionary) -> bool:
		return entry.name == "present_cast" and entry.args.size() == 6)
	check(cast_api, "HUD owner's six-argument cast API includes side preference and actor exclusions")
	if not cast_api:
		return false
	return _failures == 0

func fixture(initial: Dictionary, catalogue: Dictionary = {}, expect_ready: bool = true) -> Dictionary:
	_clock = 0.0
	var world := Node3D.new()
	root.add_child(world)
	var light := DirectionalLight3D.new()
	light.light_energy = 1.2
	light.rotation_degrees = Vector3(-28, -145, 0)
	world.add_child(light)
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.position = Vector3(18, 20, 25)
	camera.look_at(Vector3(5, 0, -12))
	camera.current = true
	var scene: Node3D = _code.new()
	world.add_child(scene)
	var configured: bool = scene.setup(world, _catalogue if catalogue.is_empty() else catalogue, ground, permitted, clock_value)
	check(configured, "real renderer setup on an isolated test support plane")
	if not configured:
		world.free()
		return {}
	scene.set_process(false)
	# Reproducible presentation-local entropy, not a replaced selection method
	# or access to the world's/global random stream.
	scene._spawn_seed = "public-hit-sync-layout-seed"
	check(apply_without_feedback(scene, initial), "initial valid public snapshot accepted")
	check(scene._damage_amount == 0, "first snapshot, including initial zero HP, never invents a damage number")
	if expect_ready:
		check(scene._actors.size() == 3 and scene._actors.values().all(func(actor: Dictionary) -> bool: return actor.safe), "real renderer-created test frame textures and support-plane roots are ready")
	return {"world": world, "scene": scene, "light": light, "camera": camera,
		"light_state": [light.transform, light.light_energy, light.light_color, light.light_cull_mask]}

func damage_view(scene: Node3D) -> Dictionary:
	return {"amount": scene._damage_amount, "age": scene._damage_age, "heavy": scene._damage_heavy}

func assert_no_new_damage(scene: Node3D, before: Dictionary, label: String) -> void:
	var after := damage_view(scene)
	# Amount may be cleared when a bubble expires or its domain changes. A
	# positive amount must not change/restart/reclassify without an actual hit.
	var created: bool = (after.amount > 0 and float(after.age) >= 0.0 and float(after.age) < 1.20
		and (before.amount <= 0 or float(before.age) < 0.0 or after.amount != before.amount
			or float(after.age) + 0.000001 < float(before.age) or after.heavy != before.heavy))
	check(not created, label)

func apply_without_feedback(scene: Node3D, value: Dictionary) -> bool:
	var before := damage_view(scene)
	var before_spawn := spawn_view(scene)
	var identical: bool = scene._snapshot == value
	var accepted: bool = scene.apply_snapshot(value)
	record_spawn_commit(scene, before_spawn)
	assert_no_new_damage(scene, before, "snapshot arrival/baseline correction cannot create a damage popup")
	if identical and accepted:
		check(damage_view(scene) == before, "identical snapshots neither replay nor prematurely age the existing damage number")
	return accepted

func step(scene: Node3D, seconds: float = STEP) -> void:
	var before_ratio: float = scene._displayed_boss_ratio()
	var before_feedback := damage_view(scene)
	var public_before: Dictionary = scene._snapshot.duplicate(true)
	var before_spawn := spawn_view(scene)
	_clock += seconds
	scene._process(seconds)
	record_spawn_commit(scene, before_spawn)
	var after_ratio: float = scene._displayed_boss_ratio()
	var units := 1000.0 if scene._snapshot.get("mode") == "demo" else float(scene._snapshot.get("bossMaxHp", 0))
	if units > 0.0 and after_ratio < before_ratio:
		var expected_amount := roundi((before_ratio - after_ratio) * units)
		check(expected_amount > 0 and scene._damage_amount == expected_amount,
			"same process frame: damage amount equals the visible confirmed HP decrement (%d), got %s" % [expected_amount, scene._damage_amount])
		check(close_enough(scene._damage_age, 0.0), "same process frame: damage age starts at zero with the HP drop")
		check(scene._damage_heavy is bool, "heavy/light feedback is a boolean presentation tag, not a damage multiplier")
	else:
		assert_no_new_damage(scene, before_feedback, "idle/charge/Boss attack/no pending HP cannot create or replay damage feedback")
	check(scene._snapshot == public_before, "damage feedback never modifies public HP, mode or authority fields")

func spawn_view(scene: Node3D) -> Dictionary:
	return {"index": scene._spawn_index, "key": scene._spawn_key, "center": scene._arena_center,
		"ready": scene._spawn_ready}

func record_spawn_commit(scene: Node3D, before: Dictionary) -> void:
	var after := spawn_view(scene)
	# Count EFFECTIVE choices, not calls that return immediately for the same
	# key. Observe before/after the actual owner method; no algorithm is stubbed.
	if after.ready and after.index >= 0 and (after.key != before.key or after.index != before.index):
		var id := scene.get_instance_id()
		_spawn_commits[id] = int(_spawn_commits.get(id, 0)) + 1
		check(after.index < EXPECTED_CENTRES.size() and after.center == EXPECTED_CENTRES[after.index], "committed site is an explicit approved candidate, never an arbitrary coordinate")
		if before.index >= 0:
			check(after.index != before.index, "each committed respawn chooses a non-repeating site")

func spawn_count(scene: Node3D) -> int:
	return int(_spawn_commits.get(scene.get_instance_id(), 0))

func station_view(scene: Node3D) -> Dictionary:
	var actors: Dictionary = {}
	for role: String in scene._actors:
		var actor: Dictionary = scene._actors[role]
		actors[role] = [actor.station, actor.direction, actor.reach]
	return {"spawn": spawn_view(scene), "actors": actors}

func assert_relative_layout(scene: Node3D) -> void:
	for role: String in scene._actors:
		var actor: Dictionary = scene._actors[role]
		var offset: Vector2 = EXPECTED_HOVER_STATION if actor.hovering else EXPECTED_STATIONS[role]
		var expected: Vector2 = scene._arena_center + offset
		var opponent: Vector2 = scene._arena_center + EXPECTED_STATIONS["hero" if role == "boss" else "boss"]
		check(actor.station.is_equal_approx(expected), "current arena translates the accepted role/hover station: " + role)
		check(actor.direction.is_equal_approx(expected.direction_to(opponent)), "lunge direction targets the current opponent, not the old clearing: " + role)
		var pose: Dictionary = scene._pose(role)
		var foot := ground(expected + expected.direction_to(opponent) * actor.reach * float(pose.travel))
		check(actor.root.position.is_equal_approx(foot), "actual process samples the translated current foot/lunge point: " + role)

func assert_damage_hud(scene: Node3D, expected_visible: bool, amount: int = 0) -> void:
	var hud: Dictionary = scene._boss_hud.debug_state()
	var number: Dictionary = hud.damage
	check(number.visible == expected_visible, "real HUD damage visibility matches the animation lifetime: " + str(number))
	if expected_visible:
		check(number.amount == amount and number.text == str(amount), "real HUD prints the exact hit amount, not percent points")
		check(close_enough(number.age, scene._damage_age) and number.heavy == scene._damage_heavy,
			"real HUD receives the same hit age/classification without a second clock")
		check(number.rect.has_area() and not number.rect.intersects(number.caption_rect)
			and not number.rect.intersects(number.controls_rect) and not number.rect.intersects(number.boss_rect)
			and not number.rect.grow(4.0).intersects(number.cast_rect), "actual damage rectangle avoids controls, caption, long bar and cast bubble")
	check(not hud.ultimate.visible and hud.ultimate.text == "", "the removed top ultimate banner cannot reappear with hit feedback")

func assert_cast_actor_clearance(scene: Node3D, expected_role: String) -> void:
	# Observe the real renderer -> six-argument HUD path after _process. Do not
	# call present_cast here: doing so could conceal missing integration inputs.
	var selected: Dictionary = scene._current_cast()
	var hud: Dictionary = scene._boss_hud.debug_state()
	var cast: Dictionary = hud.cast
	var camera := scene.get_viewport().get_camera_3d()
	check(selected.get("role") == expected_role, "cast-clearance sample exercises the intended hero/pet/Boss skill")
	check(cast.visible and scene._boss_hud._cast.is_visible_in_tree() and cast.rect.has_area(),
		"cast clearance cannot pass by hiding every bubble: role=%s site=%s clock=%.6f cast=%s" % [expected_role, scene._arena_center, scene._motion_clock, cast])
	# HUD stores an unpunctuated title, then appends one full-width ! when
	# drawing. Compare that metadata AND the complete displayed skill text;
	# do not mistake intentional normalization for a stale/incorrect caster.
	var expected_text: String = selected.get("title", "")
	check(expected_text.ends_with("！") and cast.title == expected_text.trim_suffix("！")
		and cast.text.replace("\n", "") == expected_text,
		"the actual bubble shows the current skill and its exclamation mark: expected=%s title=%s text=%s" % [expected_text, cast.title, cast.text])
	check(is_instance_valid(camera), "cast exclusion geometry uses the current actual fixture camera")
	if not is_instance_valid(camera):
		return
	for role: String in IDS:
		if role == expected_role:
			continue
		var occupied: Rect2 = scene._actor_screen_rect(scene._actors[role], camera)
		check(occupied.has_area() and occupied.position.is_finite() and occupied.size.is_finite(),
			"other living actor has a nonempty current projected body exclusion: " + role)
		check(not cast.rect.intersects(occupied),
			"actual cast rectangle avoids the other actor's complete current body: caster=%s target=%s site=%s clock=%.6f cast=%s actor=%s" % [expected_role, role, scene._arena_center, scene._motion_clock, cast.rect, occupied])
	check(not hud.ultimate.visible, "actor-local cast clearance never falls back to the removed top banner")

func advance(scene: Node3D, seconds: float) -> void:
	var remaining := seconds
	var budget := 16000
	while remaining > 0.000000001 and budget > 0:
		var part := minf(STEP, remaining)
		step(scene, part)
		remaining -= part
		budget -= 1
	check(budget > 0, "bounded manual clock driver terminates")

func advance_to(scene: Node3D, target: float) -> void:
	check(not scene._travel_active and not scene._travel_blocked,
		"combat-clock driver requires real travel arrival first, never skips frozen travel time")
	if scene._travel_active or scene._travel_blocked:
		return
	var gap: float = target - scene._motion_clock
	check(gap >= -0.000001, "test timeline only advances")
	if gap > 0.0:
		advance(scene, gap)

func drain_travel(scene: Node3D) -> bool:
	# Deliberately separate travel time from combat time. Advance the owner's
	# actual _process and shared-clock samples; never assign roots or clocks.
	# Existing hit/HP assertions resume only after a bounded real arrival.
	var combat_clock: float = scene._motion_clock
	var steps := 0
	while scene._travel_active and not scene._travel_blocked and steps < 1200:
		step(scene, STEP)
		steps += 1
		check(close_enough(scene._motion_clock, combat_clock), "travel cannot spend a combat/impact frame, including its arrival frame")
	var arrived: bool = not scene._travel_active and not scene._travel_blocked
	check(arrived, "safe fixture route arrives within 60 shared-clock seconds, without teleport or an advance_to deadlock")
	return arrived

func assert_ratio(scene: Node3D, expected: float, label: String) -> void:
	check(close_enough(scene._displayed_boss_ratio(), expected), label + " / display")
	var hud: Dictionary = scene._boss_hud.debug_state()
	if hud.visible:
		check(close_enough(hud.ratio, expected), label + " / actual HUD fill")

func identity(scene: Node3D) -> Array:
	var result: Array = [scene._effects.get_instance_id(), scene._boss_hud.get_instance_id()]
	for child: Node in scene._effects.get_children():
		if child is MeshInstance3D:
			result.append([child.get_instance_id(), child.mesh.get_instance_id(), child.material_override.get_instance_id()])
	for role: String in IDS:
		if scene._actors.has(role):
			result.append([scene._actors[role].root.get_instance_id(), scene._actors[role].frames.duplicate()])
	return result

func appearance(scene: Node3D) -> Array:
	var result: Array = [damage_view(scene), station_view(scene)]
	for role: String in IDS:
		if scene._actors.has(role):
			var actor: Dictionary = scene._actors[role]
			result.append([actor.root.transform, actor.root.visible, actor.sprite.transform,
				actor.sprite.modulate, actor.sprite.texture, actor.sprite.offset, actor.shadow.transform])
	for child: Node in scene._effects.get_children():
		if child is MeshInstance3D:
			result.append([child.visible, child.mesh.get_surface_count(), child.mesh.get_aabb()])
	return result

func expected_hit(before_us: int, after_us: int) -> String:
	for cycle in range(3):
		for index in range(HIT_US.size()):
			var at: int = cycle * PERIOD_US + HIT_US[index]
			if before_us < at and at <= after_us:
				return HIT_ROLES[index]
	return ""

func test_hit_boundaries() -> void:
	# An independent integer timeline, not a copy of the renderer's helper.
	for tick in range(1, 6241):
		var before_us := (tick - 1) * 10000
		var after_us := tick * 10000
		var actual: String = _code._boss_hit_between(before_us / 1000000.0, after_us / 1000000.0)
		check(actual == expected_hit(before_us, after_us), "all idle/charge/Boss/ultimate-reservation intervals: " + str(after_us))
	for cycle in range(3):
		for index in range(HIT_US.size()):
			var at: float = (cycle * PERIOD_US + HIT_US[index]) / 1000000.0
			check(_code._boss_hit_between(at - EPSILON, at) == HIT_ROLES[index], "impact included exactly once at " + str(at))
			check(_code._boss_hit_between(at, at + EPSILON) == "" and _code._boss_hit_between(at, at) == "", "impact never replays at the left boundary: " + str(at))
	for pair: Array in [[0.7, 0.6], [-1.0, 0.6], [NAN, 0.6], [0.5, NAN], [0.5, INF]]:
		check(_code._boss_hit_between(pair[0], pair[1]) == "", "invalid/reversed clock interval fails closed: " + str(pair))

func test_guest_steps() -> void:
	var initial := guest()
	var test := fixture(initial)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var objects := identity(scene)
	check(scene._spawn_index == 0 and spawn_count(scene) == 1, "first guest encounter uses accepted site zero exactly once")
	assert_ratio(scene, 1.0, "guest starts full")
	for tick in range(1, 9361):
		step(scene, 0.01)
		# Expected progress comes from the independent driver, never from an
		# accidentally frozen renderer clock (which would conceal a deadlock).
		var micros: int = (tick * 10000) % PERIOD_US
		var expected := 1.0
		for index in range(GUEST_RATIOS.size()):
			if micros >= HIT_US[index]:
				expected = GUEST_RATIOS[index]
			if micros == HIT_US[index]:
				check(scene._damage_amount == GUEST_DAMAGE[index] and close_enough(scene._damage_age, 0.0), "explicit guest hit/damage contract: %d at %d microseconds" % [GUEST_DAMAGE[index], micros])
		assert_ratio(scene, expected, "eight discrete guest steps, no elapsed drain: " + str(micros))
		check(scene._snapshot == initial and not scene._snapshot.has("bossHp"), "guest animation never creates authority fields")
		if micros >= 26600000:
			check(close_enough(scene._current_death_age(), (micros - 26600000) / 1000000.0), "guest death age starts with the zero-HP impact and keeps advancing: " + str(tick))
			# One microsecond tolerance for the 0.35s follow-through endpoint;
			# 0.3501s is independently asserted idle in the real death process.
			check(scene._pose("pet").row == 0 and (micros <= 26950001 or scene._pose("hero").row == 0), "only the last hero follow-through may finish: tick=%d phase_us=%d age=%.17f hero=%s pet=%s" % [tick, micros, scene._current_death_age(), scene._pose("hero"), scene._pose("pet")])
		var cycle_tick: int = (tick - 1) % 3120 + 1
		if cycle_tick in [2940, 2979, 2981, 3120]:
			check(close_enough(scene._motion_clock, tick / 100.0), "hidden dying Boss must not freeze the ember/reset clock: expected=%.2f actual=%.9f" % [tick / 100.0, scene._motion_clock])
		if cycle_tick == 3120:
			check(scene._current_death_age() < 0.0 and scene._actors.boss.root.visible, "guest really respawns after every complete 31.2s cycle: " + str(tick / 3120))
			check(spawn_count(scene) == 1 + tick / 3120, "one effective respawn per completed guest cycle, never per frame: tick=%d clock=%.17f choices=%d spawn=%s" % [tick, scene._motion_clock, spawn_count(scene), spawn_view(scene)])
			check(scene._damage_amount == 0 or scene._damage_age < 0.0, "guest respawn clears the previous hit feedback before the next fight: tick=%d feedback=%s" % [tick, damage_view(scene)])
			# Regression: HP/death use integer microseconds. Snapshot arrival on
			# exactly that frame must use the same cycle key, including clocks
			# represented as 62.399999999996 rather than mathematical 62.4.
			var boundary_layout := station_view(scene)
			var boundary_choices := spawn_count(scene)
			for refresh in range(5):
				check(apply_without_feedback(scene, initial), "same-boundary guest refresh is accepted without resetting the encounter")
			step(scene, 0.0)
			check(station_view(scene) == boundary_layout and spawn_count(scene) == boundary_choices,
				"same-frame snapshot and zero-delta process cannot choose the old cycle key or reroll a fresh respawn")
			if not drain_travel(scene):
				break
			assert_relative_layout(scene)
		if cycle_tick == 80:
			var stable := station_view(scene)
			var choices := spawn_count(scene)
			for repeated in range(25):
				check(apply_without_feedback(scene, initial), "guest liveness snapshot burst is accepted")
			check(station_view(scene) == stable and spawn_count(scene) == choices, "guest snapshot burst never reselects a site or reallocates actors")
	check(close_enough(scene._motion_clock, 93.6), "three full guest cycles execute through the real process path")
	check(identity(scene) == objects, "guest steps/death/reset keep textures, actors and the three-mesh pool")
	test.world.free()

func test_confirmed_and_displayed() -> void:
	var initial := state(1000)
	var test := fixture(initial)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var previous := 1.0
	for index in range(HIT_US.size()):
		var at: float = HIT_US[index] / 1000000.0
		advance_to(scene, at - 0.10)
		assert_ratio(scene, previous, "unchanged confirmed HP cannot be damaged by earlier choreography")
		var supplied := state(900 - index * 100)
		check(apply_without_feedback(scene, supplied), "new confirmed reduction queues before impact")
		check(close_enough(scene._confirmed_boss_ratio(), float(supplied.bossHp) / 1000.0), "confirmed truth updates immediately")
		assert_ratio(scene, previous, "snapshot arrival is not a visible hit")
		advance_to(scene, at - EPSILON)
		assert_ratio(scene, previous, "charge/travel cannot drain HP")
		advance_to(scene, at)
		previous = float(supplied.bossHp) / 1000.0
		assert_ratio(scene, previous, "qualified actual impact applies pending confirmed HP: " + str(at))
		check(scene._damage_amount == 100 and close_enough(scene._damage_age, 0.0), "each confirmed 100-HP decrease emits exactly 100 on its impact frame")
		check(scene._pose("boss").row == 3, "Boss reacts on a real allied impact: %s actual_clock=%.17f phase=%.17f pose=%s" % [at, scene._motion_clock, fposmod(scene._motion_clock, 5.2), scene._pose("boss")])
		check(scene._snapshot == supplied and not scene._snapshot.has("damage") and not scene._snapshot.has("reward"), "impact does not mutate or extend the supplied snapshot")
		check(apply_without_feedback(scene, supplied), "identical confirmed snapshot remains accepted")
		assert_ratio(scene, previous, "duplicate snapshot cannot double-deduct")
	advance_to(scene, 30.2)
	assert_ratio(scene, previous, "late Boss attack/idle cannot reduce positive confirmed HP")
	check(not scene._death_active, "nonzero confirmed HP never dies from choreography")
	test.world.free()

func test_excluded_attacks_and_legacy() -> void:
	for bounds: Array in [[2.3, 3.6, 5.8], [14.0, 17.03, 21.4]]:
		var initial := state()
		initial.elapsed = bounds[0]
		var test := fixture(initial)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		check(apply_without_feedback(scene, state(800)), "first pending HP sample")
		check(apply_without_feedback(scene, state(600)), "latest confirmed sample replaces pending target")
		advance_to(scene, bounds[1])
		assert_ratio(scene, 0.9, "Boss's own normal/ultimate impact cannot spend pending damage")
		advance_to(scene, bounds[2] - EPSILON)
		assert_ratio(scene, 0.9, "idle/reserved gap cannot spend pending damage")
		advance_to(scene, bounds[2])
		assert_ratio(scene, 0.6, "next actual hero hit shows latest confirmed target, not a guessed damage amount")
		test.world.free()
	var legacy := state()
	legacy.erase("bossHp")
	legacy.erase("bossMaxHp")
	legacy.elapsed = 300.0
	var test := fixture(legacy)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	assert_ratio(scene, 0.5, "legacy seven-field first sample remains supported")
	advance(scene, 0.2)
	assert_ratio(scene, 0.5, "legacy sender's elapsed is not locally extrapolated into damage")
	check(scene._snapshot == legacy and scene._snapshot.size() == 7, "legacy compatibility never appends HP or authority fields")
	var upgrade := state(400)
	var prior_clock: float = scene._motion_clock
	check(apply_without_feedback(scene, upgrade), "same-round seven-to-nine-field upgrade accepted")
	assert_ratio(scene, 0.4, "first authoritative HP replaces the legacy estimate immediately as a fresh health baseline")
	check(close_enough(scene._confirmed_boss_ratio(), 0.4) and close_enough(scene._motion_clock, prior_clock), "health-contract upgrade does not invent a hit or reset the encounter clock")
	var next_hp := state(350)
	check(apply_without_feedback(scene, next_hp), "subsequent nine-field sample is a normal pending decrease")
	assert_ratio(scene, 0.4, "only the first nine-field sample is a baseline exception")
	advance_to(scene, 302.2 - EPSILON)
	assert_ratio(scene, 0.4, "subsequent real HP decrease waits through the reserved/idle gap")
	advance_to(scene, 302.2)
	assert_ratio(scene, 0.35, "subsequent real HP decrease releases at the actual hero impact")
	check(scene._snapshot == next_hp, "health-contract upgrade and hit leave the nine fields unchanged")
	test.world.free()
	var zero_test := fixture(legacy)
	if not zero_test.is_empty():
		var zero_scene: Node3D = zero_test.scene
		check(apply_without_feedback(zero_scene, state(0)), "first real HP sample may already be zero after legacy observation")
		assert_ratio(zero_scene, 0.0, "legacy estimate never fabricates a positive real-HP baseline")
		check(zero_scene._death_active and not zero_scene._pending_death, "first real zero starts death directly instead of an invented historical final strike")
		zero_test.world.free()

func test_last_hit_and_death() -> void:
	for mode: String in ["fighting", "defeated"]:
		var initial := state(850)
		initial.elapsed = 8.2 if mode == "fighting" else 39.4
		var test := fixture(initial)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		var objects := identity(scene)
		var zero := state(0, mode)
		var start := 26.0 if mode == "fighting" else 57.2
		check(apply_without_feedback(scene, zero), "confirmed zero follows an observed positive HP baseline: " + mode)
		check(close_enough(scene._motion_clock, start) and scene._pending_death and not scene._death_active, "zero queues the current cycle's last hero windup without starting death")
		check(close_enough(scene._confirmed_boss_ratio(), 0.0), "pending finisher never conceals the authoritative zero value")
		assert_ratio(scene, 0.85, "visible zero waits for the final hit")
		advance(scene, 0.31)
		check(scene._pose("hero").row == 2 and "hero" in scene._effects.debug_state().activeRoles, "final windup/trajectory is a visible hero attack even for supplied defeated mode")
		var held: float = scene._motion_clock
		check(apply_without_feedback(scene, zero) and close_enough(scene._motion_clock, held), "repeated pending zero cannot rewind the finisher")
		advance_to(scene, start + 0.6 - EPSILON)
		assert_ratio(scene, 0.85, "last hit cannot show zero early")
		advance_to(scene, start + 0.6)
		assert_ratio(scene, 0.0, "the final hero impact is the exact visible-zero boundary")
		check(scene._damage_amount == 850 and close_enough(scene._damage_age, 0.0), "zero-HP final blow retains its exact 850 damage number")
		check(scene._death_active and not scene._pending_death and close_enough(scene._death_clock, 0.0), "death starts at age zero, not one frame into its 3.2 seconds")
		check(scene._snapshot == zero, "last hit/death never changes the authoritative mode or HP")
		var age := 0.0
		for next_age: float in [0.15, 0.3501, 0.8, 1.6, 2.8, 3.1999]:
			advance(scene, next_age - age)
			age = next_age
			check(close_enough(scene._current_death_age(), age), "full shared-clock death age: " + str(age))
			check(scene._pose("pet").row == 0 and (age < 0.35 or scene._pose("hero").row == 0), "death cancels new allied attacks after the bounded final follow-through")
			check(scene._effects.debug_state().activeRoles == ["boss"], "death fragments/embers persist through the 3.2s tail: " + str(age))
			check(apply_without_feedback(scene, zero) and close_enough(scene._current_death_age(), age), "duplicate zero never restarts death: " + str(age))
		advance(scene, 3.2 - age)
		check(close_enough(scene._current_death_age(), 3.2), "death lasts 3.2 animation seconds")
		# Permit <0.1ms floating accumulation at the terminal boundary, not a
		# missing rendered frame or any shortened death/ember phase.
		step(scene, EPSILON)
		check(not scene._actors.boss.root.visible and scene._effects.debug_state().activeRoles.is_empty(), "3.2s closes both the Boss body and final embers")
		advance(scene, 0.4)
		check(apply_without_feedback(scene, zero) and not scene._actors.boss.root.visible, "same defeated encounter cannot respawn after completion")
		check(identity(scene) == objects, "last hit and full death reuse actors, textures and the fixed mesh pool")
		check([test.light.transform, test.light.light_energy, test.light.light_color, test.light.light_cull_mask] == test.light_state, "death does not relight the isolated world")
		test.world.free()

func test_initial_zero_and_empty_round_hold() -> void:
	for mode: String in ["cooldown", "daily_complete"]:
		var zero := state(0)
		var test := fixture(zero)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		check(scene._death_active and not scene._pending_death and close_enough(scene._current_death_age(), 0.0), "initial zero begins death directly; no invented historical last hit")
		assert_ratio(scene, 0.0, "initial zero baseline is never fabricated as positive HP")
		advance(scene, 0.4)
		var inactive := state(0, mode, "")
		check(apply_without_feedback(scene, inactive), "public empty-round post-completion mode accepted")
		check(close_enough(scene._current_death_age(), 0.4), "empty round cannot reset or cut off an already begun death: " + mode)
		advance(scene, 2.7)
		check(close_enough(scene._current_death_age(), 3.1) and scene._effects.debug_state().activeRoles == ["boss"], "post-completion mode preserves the complete ember tail: " + mode)
		advance(scene, 0.1)
		step(scene, EPSILON)
		check(not scene._actors.boss.root.visible and scene._effects.debug_state().activeRoles.is_empty(), "held death ends cleanly at 3.2s: " + mode)
		check(scene._snapshot == inactive, "animation hold cannot restore or rewrite an old public round")
		test.world.free()

func gate(test: Dictionary, name: String, enabled: bool) -> void:
	var scene: Node3D = test.scene
	match name:
		"local_pause":
			scene._animation_paused = enabled
		"server_pause":
			var value: Dictionary = scene._snapshot.duplicate(true)
			value.mode = "paused" if enabled else "fighting"
			check(apply_without_feedback(scene, value), "valid mode change for pause gate")
		"stale":
			scene._received_msec = Time.get_ticks_msec() - (16000 if enabled else 0)
		"renderer_hidden":
			scene.visible = not enabled
		"world_hidden":
			test.world.visible = not enabled
		"unsafe_actor":
			scene._actors.pet.safe = not enabled

func test_freeze_gates() -> void:
	for stage: String in ["ordinary", "finisher", "feedback", "death"]:
		var dying: bool = stage == "death"
		var test := fixture(state(0 if dying else 900))
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		var case_number := 0
		var gates := ["local_pause", "server_pause", "stale", "renderer_hidden", "world_hidden"]
		if not dying:
			gates.append("unsafe_actor")
		for name: String in gates:
			case_number += 1
			var initial := state(0 if dying else 900, "fighting", "public-gate-" + str(case_number))
			check(apply_without_feedback(scene, initial), "fresh isolated gate case")
			if not drain_travel(scene):
				break
			if stage == "finisher":
				check(apply_without_feedback(scene, state(0, "fighting", initial.roundId)) and scene._pending_death, "confirmed final strike is genuinely queued before freeze")
			advance(scene, 0.5)
			if stage in ["ordinary", "feedback"]:
				check(apply_without_feedback(scene, state(700, "fighting", initial.roundId)), "pending HP exists before freeze")
			if stage == "feedback":
				advance(scene, 0.3)
				check(scene._damage_amount == 200 and close_enough(scene._damage_age, 0.2), "a real post-hit damage popup is aging before its pause/stale/hidden gate")
			gate(test, name, true)
			# Consume one zero-step refresh before taking the pose baseline. This
			# permits fail-closed hiding, but never allows a clock or HP advance.
			step(scene, 0.0)
			var phase: float = scene._motion_clock
			var age: float = scene._current_death_age()
			var view := appearance(scene)
			var ratio: float = scene._displayed_boss_ratio()
			var feedback := damage_view(scene)
			var snapshot: Dictionary = scene._snapshot.duplicate(true)
			advance(scene, 2.0)
			check(close_enough(scene._motion_clock, phase) and close_enough(scene._current_death_age(), age), "shared combat/death clock freezes: %s stage=%s" % [name, stage])
			assert_ratio(scene, ratio, "display HP freezes: " + name)
			check(appearance(scene) == view and scene._snapshot == snapshot, "frozen pose/geometry/public data stays unchanged: " + name)
			check(close_enough(scene._last_shared_clock, _clock), "frozen gate consumes shared samples without catch-up: " + name)
			gate(test, name, false)
			step(scene, 0.05)
			if dying:
				check(close_enough(scene._current_death_age(), age + 0.05), "resumed death advances only the next live step: " + name)
			elif stage == "feedback":
				check(scene._damage_amount == feedback.amount and close_enough(scene._damage_age, float(feedback.age) + 0.05), "resumed damage number ages only by the next live animation step: " + name)
			else:
				assert_ratio(scene, 0.9, "resume does not immediately spend missed wall-clock hits: " + name)
				step(scene, 0.05)
				assert_ratio(scene, 0.0 if stage == "finisher" else 0.7, "pending HP changes at the next genuinely visible impact: " + name)
				if stage == "finisher":
					check(scene._death_active and not scene._pending_death and close_enough(scene._death_clock, 0.0), "resumed last hit starts a complete death at age zero: " + name)
		test.world.free()

func test_missing_actor_gate() -> void:
	var incomplete: Dictionary = _catalogue.duplicate(true)
	var original_pet: Dictionary = {}
	for actor: Dictionary in incomplete.assets:
		if actor.id == IDS.pet:
			original_pet = actor.duplicate(true)
			actor.atlas = "res://camp_presentation/atlases/test-intentionally-absent.png"
	var test := fixture(guest(), incomplete, false)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	check(not scene._actors.has("pet") and IDS.pet in scene._missing, "real absent resource exercises the optional-actor loading gate")
	advance(scene, 1.0)
	check(close_enough(scene._motion_clock, 0.0), "guest cannot advance combat while one selected actor is not ready")
	assert_ratio(scene, 1.0, "missing actor cannot produce empty-space damage")
	scene._catalogue[IDS.pet] = original_pet
	check(scene.assets_available([IDS.pet]), "existing fixture pet resource becomes available without world reload")
	check(scene._actors.size() == 3, "late actor joins the same presentation node")
	step(scene, 0.05)
	assert_ratio(scene, 1.0, "late actor arrival does not replay missed attacks")
	advance(scene, 0.55)
	assert_ratio(scene, 0.92, "guest first damage requires its first live hero impact")
	test.world.free()

func test_round_and_domain_reset() -> void:
	var test := fixture(state())
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var objects := identity(scene)
	advance(scene, 0.2)
	check(apply_without_feedback(scene, state(0)), "pending final blow before round change")
	check(scene._pending_death, "round reset case really contains a pending final hit")
	var next := state(800, "fighting", "public-next-round")
	check(apply_without_feedback(scene, next), "new nonempty nonce establishes a new baseline")
	assert_ratio(scene, 0.8, "new round cannot inherit pending damage")
	check(scene._damage_amount == 0, "new nonempty round clears any pending or previous damage popup")
	check(not scene._pending_death and not scene._death_active and close_enough(scene._motion_clock, 0.0), "new round cancels previous final blow and phase")
	var zero := state(0, "fighting", "public-initial-zero-round")
	check(apply_without_feedback(scene, zero), "new zero baseline starts actual death")
	advance(scene, 1.0)
	check(apply_without_feedback(scene, next), "new live round replaces an in-progress previous death")
	check(scene._actors.boss.root.visible and not scene._death_active and scene._actors.boss.sprite.modulate == Color.WHITE,
		"new live round restores a living Boss, not a partly faded death pose")
	check(scene._actors.boss.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD and scene._actors.boss.sprite.render_priority == 0,
		"new live round restores ordinary actor cutout/material ordering")
	# Keep the nonce identical so this proves DOMAIN reset, not only nonce reset.
	check(apply_without_feedback(scene, guest(next.roundId)), "enter guest domain with unchanged opaque nonce")
	assert_ratio(scene, 1.0, "entering guest domain clears authoritative display history")
	check(scene._damage_amount == 0, "guest-domain reset clears the old damage number")
	drain_travel(scene)
	advance(scene, 2.2)
	assert_ratio(scene, 0.87, "guest domain has its own explicit hit staircase")
	check(apply_without_feedback(scene, next), "return to formal domain with the same opaque nonce")
	assert_ratio(scene, 0.8, "formal first sample is an immediate baseline, not a guest-derived pending change")
	check(scene._damage_amount == 0, "formal-domain first snapshot cannot replay guest damage feedback")
	check(not scene._pending_death and not scene._death_active and scene._snapshot == next, "domain changes leave no ghost death or manufactured state")
	check(identity(scene) == objects, "round/domain reset reuses the original actor and effect objects")
	test.world.free()

func test_long_running_clock() -> void:
	var initial := state()
	initial.elapsed = 519.9
	var test := fixture(initial)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	advance(scene, 0.2)
	check(close_enough(scene._motion_clock, 520.1), "presentation clock does not wrap at the old non-cycle-aligned 520-second boundary")
	check(apply_without_feedback(scene, state(700)), "confirmed pending damage across the old wrap boundary")
	advance_to(scene, 520.6 - EPSILON)
	assert_ratio(scene, 0.9, "long-running timeline waits for the correct next allied hit")
	advance_to(scene, 520.6)
	assert_ratio(scene, 0.7, "long-running hit helper and actual process use the same cycle")
	test.world.free()

func test_damage_units_and_lifetime() -> void:
	# Independent integer expectations, including a non-1000 real maximum and
	# a one-HP change at the maximum public HP limit. Never use percent points.
	for values: Array in [[975, 701, 1234, 274], [999999999, 999999998, 1000000000, 1]]:
		var initial := state(values[0])
		initial.bossMaxHp = values[2]
		var test := fixture(initial)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		var lower: Dictionary = initial.duplicate(true)
		lower.bossHp = values[1]
		advance(scene, 0.4)
		check(apply_without_feedback(scene, lower), "pending real HP decrease with its own maximum")
		advance_to(scene, 0.6 - EPSILON)
		check(scene._damage_amount == 0, "confirmation/charge alone cannot create the first popup")
		advance_to(scene, 0.6)
		check(scene._damage_amount == values[3] and close_enough(scene._damage_age, 0.0), "real damage uses confirmed integer HP units: " + str(values[3]))
		assert_damage_hud(scene, true, values[3])
		advance(scene, 0.2)
		var feedback := damage_view(scene)
		check(close_enough(scene._damage_age, 0.2), "damage age advances on the same animation clock")
		check(apply_without_feedback(scene, lower) and damage_view(scene) == feedback, "repeated HP while the number is visible neither replays nor shortens it")
		advance(scene, 0.9)
		check(close_enough(scene._damage_age, 1.1), "last-hit feedback has not expired at 1.1 animation seconds")
		assert_damage_hud(scene, true, values[3])
		advance(scene, 0.0999)
		check(close_enough(scene._damage_age, 1.1999), "damage lifetime remains bounded just before 1.2 seconds")
		advance(scene, 0.0002)
		check(close_enough(scene._damage_age, 1.2), "damage lifetime reaches the owner's 1.2-second terminal age")
		assert_damage_hud(scene, false)
		var expired := damage_view(scene)
		advance_to(scene, 3.6)
		check(damage_view(scene) == expired, "no-pending pet/Boss attacks cannot restart an expired damage number")
		# Baseline correction may keep or clear old expired feedback, but cannot
		# create a fresh number. Do not prescribe its inactive-field sentinel.
		check(apply_without_feedback(scene, initial), "upward health correction establishes a baseline without a popup")
		check(scene._snapshot == initial, "feedback and expiry never modify the confirmed correction snapshot")
		test.world.free()
	var round_test := fixture(state(950))
	if not round_test.is_empty():
		var scene: Node3D = round_test.scene
		check(apply_without_feedback(scene, state(800)), "prepare an actual visible popup before round reset")
		advance(scene, 0.8)
		check(scene._damage_amount == 150 and close_enough(scene._damage_age, 0.2), "old round genuinely has an active 150 damage number")
		check(apply_without_feedback(scene, state(1000, "fighting", "public-popup-new-round")), "new nonempty round begins while old feedback is visible")
		check(scene._damage_amount == 0, "new round clears a genuinely active old number, not just an already-empty field")
		round_test.world.free()

func test_spawn_round_lifecycle() -> void:
	var initial := state(1000, "fighting", "public-spawn-first")
	var test := fixture(initial)
	if test.is_empty():
		return
	var scene: Node3D = test.scene
	var objects := identity(scene)
	check(scene._spawn_index == 0 and spawn_count(scene) == 1, "first formal encounter commits accepted site zero once")
	var stations := station_view(scene)
	for repeat in range(60):
		var refresh: Dictionary = initial.duplicate(true)
		refresh.elapsed = repeat * 0.1
		check(apply_without_feedback(scene, refresh), "same-round elapsed refresh remains a display-only snapshot")
		step(scene, 0.001)
	check(spawn_count(scene) == 1 and station_view(scene) == stations, "same-round snapshot flood cannot reroll placement or use server elapsed as a new local phase")
	check(apply_without_feedback(scene, state(850, "fighting", initial.roundId)), "formal pending HP before first visible hit")
	advance_to(scene, 0.6)
	assert_damage_hud(scene, true, 150)
	check(station_view(scene) == stations and spawn_count(scene) == 1, "damage and its popup never move the encounter")
	check(apply_without_feedback(scene, state(0, "defeated", initial.roundId)), "formal zero queues a final hit at its old site")
	check(scene._pending_death and scene._displayed_boss_ratio() == 0.85, "zero arrival preserves visible positive health until the final impact")
	advance(scene, 0.59)
	check(station_view(scene) == stations and spawn_count(scene) == 1, "zero/last-hit windup cannot choose a new site")
	advance(scene, 0.01)
	assert_ratio(scene, 0.0, "formal final impact still belongs to the old encounter")
	assert_damage_hud(scene, true, 850)
	var ended := state(0, "cooldown", "")
	check(apply_without_feedback(scene, ended), "empty-round cooldown can hold the confirmed death")
	advance(scene, 3.2001)
	check(station_view(scene) == stations and spawn_count(scene) == 1, "the entire death/ember tail stays at the old site even after a roundless cooldown")
	check(not scene._actors.boss.root.visible, "death lifecycle really completes before testing the next respawn")
	var seen := {0: true}
	for index in range(1, 25):
		var next := state(1000, "fighting", "public-spawn-next-%02d" % index)
		var previous_site: int = scene._spawn_index
		check(apply_without_feedback(scene, next), "new explicit nonempty round starts a single new encounter")
		if not drain_travel(scene):
			break
		step(scene, 0.05)
		check(spawn_count(scene) == index + 1 and scene._spawn_index != previous_site, "one effective non-repeating selection for each new formal round")
		check(scene._damage_amount == 0 and scene._damage_age < 0.0 and not scene._pending_death and not scene._death_active,
			"new round clears old hit feedback and death, not only the Boss health")
		assert_ratio(scene, 1.0, "new formal encounter uses its own confirmed full-health baseline")
		assert_relative_layout(scene)
		seen[scene._spawn_index] = true
		stations = station_view(scene)
		for repeat in range(10):
			check(apply_without_feedback(scene, next), "identical new-round liveness snapshot")
		check(spawn_count(scene) == index + 1 and station_view(scene) == stations, "liveness refreshes cannot draw additional random sites")
		check(identity(scene) == objects, "every formal respawn preserves actor/frame resources and the fixed effect pool")
	print("CAMP_HIT_SYNC_SPAWN: formal observed candidate indices=" + str(seen.keys()) + "; no random-distribution or actual-terrain claim")
	test.world.free()

func public_fixture_catalogue() -> Dictionary:
	# Reuse only the existing synthetic TEST atlas to exercise every public
	# style/hover dispatch. This is NOT a real-art footprint or scale survey.
	var templates: Dictionary = {}
	for actor: Dictionary in _catalogue.assets:
		templates[actor.role] = actor
	var result: Dictionary = _catalogue.duplicate(true)
	result.assets = []
	for id: String in PUBLIC_ROLES:
		var actor: Dictionary = templates[PUBLIC_ROLES[id]].duplicate(true)
		actor.id = id
		result.assets.append(actor)
	return result

func mesh_view(scene: Node3D) -> Dictionary:
	var result: Dictionary = {}
	for role: String in IDS:
		var mesh: MeshInstance3D = scene._effects._pool[role]
		result[role] = {"visible": mesh.visible, "surfaces": mesh.mesh.get_surface_count(), "bounds": mesh.mesh.get_aabb(),
			"vertices": scene._effects._counts[role], "style": scene._effects._styles.get(role, "")}
	return result

func sample_style_phase(scene: Node3D, phase: float) -> void:
	# Geometry calibration, NOT a locomotion-continuity assertion. First finish
	# the real trip and play the real fight clock to just before this sample.
	# Different-length trips legitimately leave hover on different phases;
	# align only that independent visual clock for an exact rigid-translation
	# comparison, then let actual _process create all poses/HUD/mesh vertices.
	# test_camp_travel_continuity never assigns either animation clock.
	advance_to(scene, phase - EPSILON)
	if scene._travel_active or scene._travel_blocked:
		return
	scene._locomotion_clock = phase - EPSILON
	step(scene, EPSILON)
	check(close_enough(scene._motion_clock, phase) and close_enough(scene._locomotion_clock, phase),
		"post-arrival geometry comparison samples matching combat and independent hover phases")

func test_public_style_target_translation() -> void:
	var catalogue := public_fixture_catalogue()
	var stages := [{"time": 0.65, "role": "hero"}, {"time": 2.15, "role": "pet"}, {"time": 3.65, "role": "boss"},
		{"time": 11.95, "role": "hero"}, {"time": 17.15, "role": "boss"}]
	for id: String in PUBLIC_ROLES:
		var initial := state(1000, "fighting", "public-style-first")
		initial.heroAssetId = "hero_ranger"
		initial.petAssetId = "pet_deer"
		initial.bossAssetId = "boss_ancient_guardian"
		initial[PUBLIC_ROLES[id] + "AssetId"] = id
		var test := fixture(initial, catalogue)
		if test.is_empty():
			continue
		var scene: Node3D = test.scene
		var objects := identity(scene)
		for index in range(stages.size()):
			var stage: Dictionary = stages[index]
			var before_round: Dictionary = initial.duplicate(true)
			before_round.roundId = "public-style-%d-before" % index
			before_round.elapsed = stage.time - 0.05
			check(apply_without_feedback(scene, before_round), "style calibration starts from a real round baseline: " + id)
			if not drain_travel(scene):
				break
			# A real relocation may align the display clock to its cycle start.
			# Walk first, then actually play to the requested calibration phase;
			# never restore the supplied elapsed by assigning a renderer clock.
			sample_style_phase(scene, stage.time)
			assert_relative_layout(scene)
			assert_cast_actor_clearance(scene, stage.role)
			var before := mesh_view(scene)
			var center: Vector2 = scene._arena_center
			var frame_ids: Array = []
			for role: String in IDS:
				frame_ids.append(scene._actors[role].frame)
			check(before[stage.role].visible and before[stage.role].vertices > 0 and before[stage.role].surfaces == 1,
				"actual _process produced the active role's real geometry before moving: %s / %s" % [id, stage])
			var after_round: Dictionary = before_round.duplicate(true)
			after_round.roundId = "public-style-%d-after" % index
			check(apply_without_feedback(scene, after_round), "new round translates the same cast to a different safe test-plane site")
			if not drain_travel(scene):
				break
			sample_style_phase(scene, stage.time)
			assert_relative_layout(scene)
			assert_cast_actor_clearance(scene, stage.role)
			var after := mesh_view(scene)
			var translation := ground(scene._arena_center) - ground(center)
			check(translation.length() > 1.0, "projectile comparison genuinely uses two distinct encounter sites")
			for role: String in IDS:
				check(scene._actors[role].frame == frame_ids[IDS.keys().find(role)], "equal phase at different sites keeps the same atlas frame: " + role)
				check(before[role].visible == after[role].visible and before[role].vertices == after[role].vertices
					and before[role].style == after[role].style, "respawn retains the active role/style/geometry budget: " + role)
				if before[role].visible:
					var old_bounds: AABB = before[role].bounds
					var new_bounds: AABB = after[role].bounds
					check(new_bounds.position.distance_to(old_bounds.position + translation) < 0.002
						and new_bounds.size.distance_to(old_bounds.size) < 0.002,
						"actual skill vertices track the translated actor AND target, not stale world endpoints: %s / %s" % [id, stage])
			check(identity(scene) == objects, "all public style dispatches reuse existing actor roots, frames and meshes across placement changes: " + id)
			check(scene._damage_amount == 0, "unconfirmed style/ultimate geometry alone cannot invent hit numbers")
		test.world.free()
	print("CAMP_HIT_SYNC_STYLE_TARGETS: 13 public IDs x 5 ordinary/ultimate phases x 2 different sites; synthetic art/control-flow only")

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	check(arguments.size() == 1, "one explicit tiny fixture PCK is required")
	if arguments.size() != 1 or not prepare(arguments[0]):
		print("CAMP_HIT_SYNC_TEST: NOT_READY_OR_INVALID_INPUT (%d failed checks)" % _failures)
		quit(1)
		return
	# A headless Window defaults to 64x64, where the real HUD must hide. Give
	# the control-flow fixture an explicit logical viewport; this is not a
	# screenshot, GPU render or claimed QHD acceptance resolution.
	root.size = Vector2i(1280, 800)
	root.content_scale_size = Vector2i(1280, 800)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	check(root.get_visible_rect().size.is_equal_approx(Vector2(1280, 800)), "native UI contract uses an explicit real logical viewport, not a 64x64 hidden HUD")
	test_hit_boundaries()
	test_guest_steps()
	test_confirmed_and_displayed()
	test_excluded_attacks_and_legacy()
	test_last_hit_and_death()
	test_initial_zero_and_empty_round_hold()
	test_freeze_gates()
	test_missing_actor_gate()
	test_round_and_domain_reset()
	test_long_running_clock()
	test_damage_units_and_lifetime()
	test_spawn_round_lifecycle()
	test_public_style_target_translation()
	await process_frame
	print("CAMP_HIT_SYNC_LIMITS: source-native control flow only; no actual-world, GPU/QHD, pack-source-pin, private gameplay or reward proof")
	print("CAMP_HIT_SYNC_TEST: %s (%d checks, %d failures)" % ["PASS" if _failures == 0 else "FAIL", _checks, _failures])
	quit(0 if _failures == 0 else 1)
