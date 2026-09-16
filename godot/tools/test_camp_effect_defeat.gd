extends SceneTree
## Focused native CPU geometry checks in an EMPTY project with the current
## source at res://camp_presentation/camp_combat_effects.gd. No world, art,
## renderer/HUD, pack build, browser, HP simulation or network is involved.

class Probe:
	extends "res://camp_presentation/camp_combat_effects.gd"
	var emitted: Array = []
	var rings: Array = []
	var discs: Array = []
	var strikes: Array = []
	var stars: Array = []
	var rocks: Array = []
	var beams: Array = []
	func clear_probe() -> void:
		for entries: Array in [emitted, rings, discs, strikes, stars, rocks, beams]:
			entries.clear()
	func _vertex(point: Vector3, color: Color, alpha: float) -> void:
		emitted.append([point, color, alpha])
		super._vertex(point, color, alpha)
	func _ring(center: Vector3, radius: float, width: float, color: Color, alpha: float, ground: bool, rotation: float = 0.0) -> void:
		rings.append({"center": center, "radius": radius, "width": width, "alpha": alpha, "ground": ground})
		super._ring(center, radius, width, color, alpha, ground, rotation)
	func _disc(center: Vector3, radius: float, color: Color, alpha: float) -> void:
		var first := emitted.size()
		super._disc(center, radius, color, alpha)
		discs.append({"center": center, "radius": radius, "alpha": alpha, "vertices": emitted.slice(first)})
	func _crescent(center: Vector3, radius: float, width: float, color: Color, alpha: float, rotation: float) -> void:
		strikes.append({"center": center, "radius": radius, "alpha": alpha})
		super._crescent(center, radius, width, color, alpha, rotation)
	func _star(center: Vector3, radius: float, color: Color, alpha: float, rotation: float = 0.0) -> void:
		stars.append({"center": center, "radius": radius, "alpha": alpha})
		super._star(center, radius, color, alpha, rotation)
	func _arrow(point: Vector3, direction: Vector3, radius: float, color: Color, alpha: float) -> void:
		rocks.append({"center": point, "radius": radius, "alpha": alpha})
		super._arrow(point, direction, radius, color, alpha)
	func _beam(start: Vector3, finish: Vector3, width: float, color: Color, alpha: float) -> void:
		beams.append({"start": start, "finish": finish, "width": width, "color": color, "alpha": alpha})
		super._beam(start, finish, width, color, alpha)

var checks := 0
var failures := 0
var peak_vertices := 0
var effects: Probe
var world: Node3D
var camera: Camera3D
var actors: Dictionary = {}
var pool_ids: Array = []

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("CAMP_EFFECT_DEFEAT_FAIL: " + label)

func sample(age: float, night: float = 0.0) -> Dictionary:
	effects.clear_probe()
	effects.present_defeat(actors, age, camera, night)
	var state := effects.debug_state()
	var total := 0
	for count: int in state.vertices.values():
		check(count >= 0 and count <= 6000 and count % 3 == 0, "bounded triangle pool")
		total += count
	peak_vertices = maxi(peak_vertices, total)
	check(total == effects.emitted.size() and total <= 1200, "actual death emission stays well below existing 6000-role limit")
	check(effects.emitted.all(func(v: Array) -> bool:
		return v[0].is_finite() and is_finite(v[2]) and v[2] >= 0.0 and v[2] <= 1.0), "finite positions and bounded alpha")
	check(state.vertices.hero == 0 and state.vertices.pet == 0 and not state.ultimate.active, "only Boss pool, no skills/ultimate restarted")
	check(effects.get_children().map(func(n: Node) -> int: return n.get_instance_id()) == pool_ids
		and effects.get_child_count() == 3 and not effects.is_processing(), "no extra nodes or autonomous clock")
	return {"state": state, "emitted": effects.emitted.duplicate(true), "rings": effects.rings.duplicate(true),
		"discs": effects.discs.duplicate(true), "strikes": effects.strikes.duplicate(true),
		"stars": effects.stars.duplicate(true), "rocks": effects.rocks.duplicate(true), "beams": effects.beams.duplicate(true)}

func centroid(items: Array) -> Vector3:
	var total := Vector3.ZERO
	for item: Dictionary in items:
		total += item.center
	return total / maxi(1, items.size())

func test_stages() -> void:
	for night: float in [0.0, 1.0]:
		for age: float in [0.0, 0.11, 0.219, 0.22, 0.75, 1.349, 1.35, 1.60, 2.299, 2.30, 2.50, 2.75, 3.199]:
			var view := sample(age, night)
			check(view.state.activeRoles == ["boss"] and view.state.styles.boss == "guardian_defeat", "active death keeps existing public debug contract")
			check(not view.emitted.is_empty(), "every active age emits geometry")
			check(sample(age, night) == view, "held age reproduces exact geometry, including night")
			if age < 0.22:
				check(view.strikes.size() == 2 and view.stars.size() == 1 and view.discs.size() == 1, "finishing flash is a small local hit, not a screen overlay")
				check(view.beams.size() == 6 and view.rocks.is_empty(), "final hero contact tails precede stone fragments")
			elif age < 1.35:
				check(view.rocks.size() == 14 and view.beams.size() == 20, "fourteen chips plus three small paired cracks during owner's kneel")
				check(view.discs.is_empty() and view.strikes.is_empty() and view.stars.is_empty(), "no dust cloud hides the stagger pose")
			elif age < 2.30:
				check(view.rocks.size() == 14 and view.discs.size() == 6 and view.stars.is_empty(), "bounded falling stones and six ground dust fans")
			else:
				check(view.rocks.is_empty() and view.stars.size() == 10, "ember stage does not keep flying rocks or start another kill")
				check(view.discs.size() == (6 if age < 2.75 else 0), "dust overlaps then clears before embers end")
	var middle := sample(0.75)
	sample(3.0)
	check(sample(0.75) == middle, "rewinding supplied age retains no particle history")
	var early_rocks := sample(1.40)
	var low_rocks := sample(2.20)
	check(centroid(low_rocks.rocks).y < centroid(early_rocks.rocks).y - 0.70, "stone cohort visibly descends toward terrain")
	var before_split := sample(1.34999)
	var after_split := sample(1.35)
	check(centroid(before_split.rocks).distance_to(centroid(after_split.rocks)) < 0.001, "stagger-to-fall centres have no jump")
	var tail := sample(2.30)
	var end := sample(3.10)
	check(end.stars[0].alpha < tail.stars[0].alpha * 0.10 and end.stars[0].radius < tail.stars[0].radius * 0.10, "embers shrink and fade during final 0.9s")

func test_contact_continuity() -> void:
	for id: String in ["hero_ranger", "hero_knight", "hero_mage", "hero_bard", "hero_alchemist", "hero_astrologer"]:
		actors.hero.id = id
		var view := sample(0.0)
		var skill := effects.skill_for(id, "hero")
		var source: Vector3 = actors.hero.root.position + Vector3.UP * (1.98 * 0.47)
		for index in range(view.beams.size()):
			var beam: Dictionary = view.beams[index]
			check(beam.color == (skill.color if index % 2 == 0 else skill.accent), "contact retains current hero skill colours: " + id)
			check((beam.finish - beam.start).normalized().dot(source.direction_to(beam.finish)) > 0.999,
				"tail points from hero into actual contact, never away from target")
			check(beam.start.distance_to(beam.finish) <= 0.951, "short residual trail cannot cross the arena")
		var fading := sample(0.20)
		check(fading.beams[0].alpha < view.beams[0].alpha * 0.03, "contact trail clears by 220ms rather than popping at death start")
	actors.hero.id = "hero_ranger"
	actors.hero.root.visible = false
	check(sample(0.10).beams.is_empty(), "hidden hero never invents a final attack")
	actors.hero.root.visible = true
	actors.hero.safe = false
	check(sample(0.10).beams.is_empty(), "unsafe hero never invents a final attack")
	actors.hero.safe = true
	var saved: Dictionary = actors.hero
	actors.erase("hero")
	check(sample(0.10).beams.is_empty(), "missing hero still permits local Boss burst without fabricated direction")
	actors.hero = saved

func test_pose_and_ground() -> void:
	var boss: Dictionary = actors.boss
	for scale_y: float in [1.0, 0.72, 0.40]:
		boss.sprite.basis = Basis(Vector3.UP, 0.35) * Basis(Vector3.BACK, -0.42) * Basis.from_scale(Vector3(1.04, scale_y, 1.0))
		boss.sprite.position = Vector3(0.20, -0.18, 0.10)
		var view := sample(0.75)
		var expected: Vector3 = boss.root.position + boss.sprite.position + boss.sprite.basis.y.normalized() * (5.94 * scale_y * 0.39)
		expected += Vector3.UP * (0.07 + 0.75 * 0.40 - 0.75 * 0.75 * 0.32)
		check(is_equal_approx(effects._body_height(boss), 5.94 * scale_y), "heads use positive Sprite Y scale once, never atlas padding")
		check(centroid(view.rocks).is_equal_approx(expected), "death chips follow owner lean, translation and single squat factor")
		check(view.rings[0].center.is_equal_approx(boss.root.position + Vector3.UP * 0.07), "squat/lean cannot move terrain ring")
		boss.frame = 1
		check(is_equal_approx(effects._body_height(boss), 4.95 * scale_y), "current-frame head remains authoritative for visible geometry")
		boss.frame = 0
	for scale_y: float in [0.0, -0.50]:
		boss.sprite.scale = Vector3(1.0, scale_y, 1.0)
		check(is_equal_approx(effects._body_height(boss), 5.94), "non-positive optional squash falls back to unscaled visible height")
	boss.sprite.transform = Transform3D.IDENTITY
	check(is_equal_approx(effects._body_height({"height": 8.5, "heads": [5.94], "frame": 0}), 5.94), "missing optional Sprite scale keeps legacy metadata usable")
	for rotation: Vector3 in [Vector3.ZERO, Vector3(-0.55, 0.30, 0.0), Vector3(-0.55, 0.30, 0.40)]:
		camera.rotation = rotation
		for age: float in [1.35, 1.70, 2.29, 2.30, 2.70, 3.10]:
			var view := sample(age)
			var foot: Vector3 = boss.root.position + Vector3.UP * 0.07
			for ring: Dictionary in view.rings:
				check(ring.ground and ring.radius + ring.width <= 1.85, "terrain ring remains local, including large Boss")
				check(Vector2(ring.center.x - foot.x, ring.center.z - foot.z).length() < 0.0001,
					"ground effects stay at registered feet")
			for dust: Dictionary in view.discs:
				check(dust.vertices.all(func(v: Array) -> bool: return v[0].y >= foot.y + 0.019), "dust fans stay above ground even with camera roll")
				check(dust.vertices.all(func(v: Array) -> bool:
					return Vector2(v[0].x - foot.x, v[0].z - foot.z).length() <= 1.85), "dust does not expand into a full-arena cloud")
				check(dust.alpha <= 0.24, "ground dust cannot become an opaque body mask")
	camera.rotation = Vector3.ZERO

func test_cleanup_and_purity() -> void:
	var metadata := actors.duplicate(true)
	var transforms: Array = []
	for role: String in actors:
		transforms.append([actors[role].root.transform, actors[role].sprite.transform, actors[role].root.visible])
	for age: float in [0.0, 0.60, 1.70, 2.50, 3.19]:
		sample(age)
	check(actors == metadata, "no supplied metadata, authority fields or actor objects changed")
	var index := 0
	for role: String in actors:
		check(transforms[index] == [actors[role].root.transform, actors[role].sprite.transform, actors[role].root.visible],
			"effect never animates owner position/scale/visibility")
		index += 1
	actors.boss.root.visible = false
	check(not sample(2.80).emitted.is_empty(), "hidden Boss body can leave bounded embers without resurrection")
	actors.boss.root.visible = true
	for age: float in [-1.0, NAN, INF, 3.20, 3.80, 4.0, 1.0e9]:
		var view := sample(age)
		check(view.emitted.is_empty() and view.state.activeRoles.is_empty(), "complete/invalid age clears every surface")
	actors.boss.safe = false
	check(sample(1.70).emitted.is_empty(), "unsafe terrain suppresses defeat geometry")
	actors.boss.safe = true
	var boss: Dictionary = actors.boss
	actors.erase("boss")
	check(sample(1.70).emitted.is_empty(), "missing Boss leaves no ghost death")
	actors.boss = boss
	effects.clear_probe()
	effects.present(actors, 0.80, "fighting", true, camera, 0.5)
	var regular: Array = effects.emitted.duplicate(true)
	sample(1.70)
	effects.clear_probe()
	effects.present(actors, 0.80, "fighting", true, camera, 0.5)
	check(effects.emitted == regular, "defeat has no lasting effect on normal skill geometry")
	check(effects.get_node("BossSkill").material_override.render_priority == 127, "approved focus-copy ordering preserved")

func run() -> void:
	world = Node3D.new()
	root.add_child(world)
	camera = Camera3D.new()
	world.add_child(camera)
	for role: String in ["hero", "pet", "boss"]:
		var actor_root := Node3D.new()
		world.add_child(actor_root)
		actor_root.position = {"hero": Vector3(-2, 0.15, 0.8), "pet": Vector3(-2.7, 0.17, -1.5), "boss": Vector3(2.2, 0.35, -0.8)}[role]
		var sprite := Sprite3D.new()
		actor_root.add_child(sprite)
		actors[role] = {"id": {"hero": "hero_ranger", "pet": "pet_owl", "boss": "boss_ancient_guardian"}[role],
			"root": actor_root, "sprite": sprite, "safe": true, "frame": 0,
			"height": 8.5 if role == "boss" else 2.8, "heads": [5.94, 4.95] if role == "boss" else [1.98],
			"sentinel_authority": {"hp": 0, "never_write": true}}
	effects = Probe.new()
	world.add_child(effects)
	effects.configure()
	pool_ids = effects.get_children().map(func(n: Node) -> int: return n.get_instance_id())
	test_stages()
	test_contact_continuity()
	test_pose_and_ground()
	test_cleanup_and_purity()
	world.free()
	print("CAMP_EFFECT_DEFEAT_TEST: %s (%d/%d checks); peak CPU vertices=%d, no GPU/performance claim" % ["PASS" if failures == 0 else "FAIL", checks - failures, checks, peak_vertices])
	quit(0 if failures == 0 else 1)
