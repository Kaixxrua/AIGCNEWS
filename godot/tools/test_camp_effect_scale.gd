extends SceneTree
## Focused CPU-emission checks. Run in an empty native project containing ONLY
## the current source at res://camp_presentation/camp_combat_effects.gd.
## No world, PNG/PCK build, renderer/HUD suite, network or server state.

class Probe:
	extends "res://camp_presentation/camp_combat_effects.gd"
	var rings: Array = []
	var strikes: Array = []
	var stars: Array = []
	var fragments: Array = []
	var emitted: Array = []
	func clear_probe() -> void:
		rings.clear()
		strikes.clear()
		stars.clear()
		fragments.clear()
		emitted.clear()
	func _vertex(point: Vector3, color: Color, alpha: float) -> void:
		emitted.append([point, alpha])
		super._vertex(point, color, alpha)
	func _ring(center: Vector3, radius: float, width: float, color: Color, alpha: float, ground: bool, rotation: float = 0.0) -> void:
		rings.append({"center": center, "radius": radius, "width": width, "ground": ground})
		super._ring(center, radius, width, color, alpha, ground, rotation)
	func _crescent(center: Vector3, radius: float, width: float, color: Color, alpha: float, rotation: float) -> void:
		strikes.append({"center": center, "radius": radius})
		super._crescent(center, radius, width, color, alpha, rotation)
	func _star(center: Vector3, radius: float, color: Color, alpha: float, rotation: float = 0.0) -> void:
		stars.append(center)
		super._star(center, radius, color, alpha, rotation)
	func _arrow(point: Vector3, direction: Vector3, radius: float, color: Color, alpha: float) -> void:
		fragments.append(point)
		super._arrow(point, direction, radius, color, alpha)

var checks := 0
var failures := 0
var peak_vertices := 0
var effects: Node3D
var world: Node3D
var actors: Dictionary = {}

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("CAMP_EFFECT_SCALE_FAIL: " + label)

func body(role: String, height: float, fraction: float) -> Vector3:
	return actors[role].root.position + Vector3.UP * (height * fraction + actors[role].sprite.position.y)

func sample(clock: float, mode: String = "fighting") -> Dictionary:
	effects.clear_probe()
	effects.present(actors, clock, mode, true, null, 0.5)
	return capture()

func capture() -> Dictionary:
	var state: Dictionary = effects.debug_state()
	var total := 0
	for count: int in state.vertices.values():
		check(count >= 0 and count <= 6000 and count % 3 == 0, "per-role vertex budget/triangles")
		total += count
	peak_vertices = maxi(peak_vertices, total)
	check(total == effects.emitted.size() and total <= 9000, "real emitted count equals bounded diagnostics")
	check(effects.emitted.all(func(v: Array) -> bool: return v[0].is_finite() and is_finite(v[1])), "finite emitted geometry")
	return {"rings": effects.rings.duplicate(true), "strikes": effects.strikes.duplicate(true),
		"stars": effects.stars.duplicate(), "fragments": effects.fragments.duplicate(),
		"emitted": effects.emitted.duplicate(true), "state": state}

func ground_rings(view: Dictionary) -> Array:
	return view.rings.filter(func(r: Dictionary) -> bool: return r.ground)

func test_legacy_and_heads() -> void:
	var legacy_charge := sample(0.20)
	check(legacy_charge.rings[0].center.is_equal_approx(body("hero", 1.8, 0.47)), "missing heads keeps legacy source height")
	var legacy_hit := sample(0.80)
	check(legacy_hit.rings[0].center.is_equal_approx(body("boss", 3.8, 0.44)), "missing heads keeps legacy target height")
	check(is_equal_approx(legacy_hit.rings[0].radius, 0.26 + (0.20 / 0.70) * 0.96), "legacy effect radius is unchanged")
	for role: String in actors:
		actors[role].height = {"hero": 2.8, "pet": 2.0, "boss": 8.5}[role]
		actors[role].heads = {"hero": [1.98, 1.60], "pet": [1.188, 0.99], "boss": [5.94, 4.95]}[role]
		actors[role].frame = 0
	actors.pet.sprite.position.y = 1.25
	for role: String in actors:
		var clock: float = {"hero": 0.20, "pet": 1.70, "boss": 3.20}[role]
		var view := sample(clock)
		check(view.rings[0].center.is_equal_approx(body(role, actors[role].heads[0], 0.47)),
			"current visible torso plus separate hover source: " + role)
	var hit := sample(0.80)
	check(hit.rings[0].center.is_equal_approx(body("boss", 5.94, 0.44)), "large Boss hit excludes transparent cell padding")
	actors.boss.frame = 1
	hit = sample(0.80)
	check(hit.rings[0].center.is_equal_approx(body("boss", 4.95, 0.44)), "same-clock frame change uses the new real head height")
	actors.boss.frame = 0
	var counter := sample(3.80)
	check(counter.stars[-1].is_equal_approx(body("hero", 1.98, 0.44)), "Boss strike still aims at the small hero torso")
	for invalid: Variant in [[], [NAN], [INF], [-1.0], [99.0], [true], ["5.94"], null]:
		actors.boss.heads = invalid
		check(sample(0.80).rings[0].center.is_equal_approx(body("boss", 8.5, 0.44)), "invalid optional head metadata uses finite legacy height")
	actors.boss.heads = [5.94, 4.95]
	for frame: int in [-1, 2, 500]:
		actors.boss.frame = frame
		check(sample(0.80).rings[0].center.is_equal_approx(body("boss", 8.5, 0.44)), "out-of-range frame cannot reuse another pose's head")
	actors.boss.frame = 0

func test_local_sizes_and_ground() -> void:
	actors.boss.heads = [3.0]
	var small := sample(0.80)
	actors.boss.heads = [5.94]
	var large := sample(0.80)
	check(large.rings[0].radius > small.rings[0].radius and large.rings[0].radius <= small.rings[0].radius * 1.30001,
		"torso ring grows mildly and never scales with full Boss growth")
	check(large.state.vertices == small.state.vertices, "scale adds no geometry")
	actors.boss.height = 30.0
	actors.boss.heads = [25.0]
	check(is_equal_approx(sample(0.80).rings[0].radius, large.rings[0].radius), "size remains capped for an oversized optional actor")
	actors.boss.height = 8.5
	actors.boss.heads = [5.94]
	actors.hero.id = "hero_knight"
	var strike := sample(0.80)
	check(is_equal_approx(strike.strikes[0].radius, 1.1 * 1.30), "normal cleave fits the large target with bounded size")
	var ultimate := sample(12.13)
	actors.boss.heads = [3.0]
	var prior_ultimate := sample(12.13)
	check(ultimate.rings[0].radius > prior_ultimate.rings[0].radius
		and ultimate.rings[0].radius <= prior_ultimate.rings[0].radius * 1.15001, "already-large ultimate ring grows at most fifteen percent")
	for setup: Array in [["hero_alchemist", 0.80], ["hero_alchemist", 12.13], ["hero_ranger", 3.80], ["hero_ranger", 16.10], ["hero_ranger", 17.60]]:
		actors.hero.id = setup[0]
		actors.boss.heads = [3.0]
		var before := sample(setup[1])
		actors.boss.heads = [5.94]
		var after := sample(setup[1])
		check(not ground_rings(after).is_empty() and ground_rings(before) == ground_rings(after), "ground rune/quake centre, radius and width remain unchanged")
	actors.hero.id = "hero_ranger"

func test_death_and_purity() -> void:
	var before: Dictionary = actors.duplicate(true)
	var transforms: Array = []
	for role: String in actors:
		transforms.append([actors[role].root.transform, actors[role].sprite.transform])
	var identity: Array = effects.get_children().map(func(n: Node) -> int: return n.get_instance_id())
	var frozen := sample(0.80, "paused")
	check(sample(0.80, "paused") == frozen, "same paused frame reproduces exact CPU geometry without advancement")
	sample(16.10)
	check(sample(0.80, "paused") == frozen, "returning to a sample keeps no effect-size history")
	check(actors == before, "effects never mutate supplied actor metadata")
	var index := 0
	for role: String in actors:
		check(transforms[index] == [actors[role].root.transform, actors[role].sprite.transform], "effects never move/scale actor nodes")
		index += 1
	actors.boss.sprite.position.y = -0.18
	actors.boss.root.visible = false
	effects.clear_probe()
	effects.present_defeat(actors, 0.75, null, 1.0)
	var death := capture()
	var center := Vector3.ZERO
	for point: Vector3 in death.fragments:
		center += point
	center /= maxi(1, death.fragments.size())
	var expected := body("boss", 5.94, 0.39) + Vector3.UP * (0.07 + 0.75 * 0.40 - 0.75 * 0.75 * 0.32)
	check(death.fragments.size() == 14 and center.is_equal_approx(expected), "death centre follows current visible Boss torso and sink, even after sprite hiding")
	check(is_equal_approx(death.rings[0].center.y, actors.boss.root.position.y + 0.07)
		and is_equal_approx(death.rings[0].radius, 0.65 + 0.75 * 0.34), "death ring stays on terrain at its original radius")
	effects.clear_probe()
	effects.present_defeat(actors, 0.75, null, 1.0)
	check(capture() == death, "held death age does not advance fragments")
	actors.boss.root.visible = true
	actors.boss.sprite.position.y = 0.0
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete", "defeated"]:
		check(sample(0.80, mode).emitted.is_empty(), "ordinary effects retain mode gates: " + mode)
	effects.clear_probe()
	effects.present_defeat(actors, 3.20, null, 0.0)
	check(capture().emitted.is_empty(), "original death end boundary is unchanged")
	check(effects.get_children().map(func(n: Node) -> int: return n.get_instance_id()) == identity
		and effects.get_child_count() == 3 and not effects.is_processing(), "original three pooled nodes, no autonomous clock")
	check(effects.get_node("HeroSkill").material_override.render_priority == 127, "frozen focus-copy compositing priority retained")

func run() -> void:
	world = Node3D.new()
	root.add_child(world)
	for role: String in ["hero", "pet", "boss"]:
		var actor_root := Node3D.new()
		world.add_child(actor_root)
		actor_root.position = {"hero": Vector3(-2, 0.15, 0.8), "pet": Vector3(-2.7, 0.17, -1.5), "boss": Vector3(2.2, 0.35, -0.8)}[role]
		var sprite := Sprite3D.new()
		actor_root.add_child(sprite)
		actors[role] = {"id": {"hero": "hero_ranger", "pet": "pet_owl", "boss": "boss_ancient_guardian"}[role],
			"root": actor_root, "sprite": sprite, "safe": true, "height": 3.8 if role == "boss" else 1.8}
	effects = Probe.new()
	world.add_child(effects)
	test_legacy_and_heads()
	test_local_sizes_and_ground()
	test_death_and_purity()
	world.free()
	print("CAMP_EFFECT_SCALE_TEST: %s (%d/%d checks); peak CPU vertices=%d, no GPU/performance claim" % ["PASS" if failures == 0 else "FAIL", checks - failures, checks, peak_vertices])
	quit(0 if failures == 0 else 1)
