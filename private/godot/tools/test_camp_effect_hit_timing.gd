extends SceneTree
## Isolated native geometry tests; use an empty project with the current
## effect module at res://camp_presentation/camp_combat_effects.gd.
## Verify actual submitted projectile centres and bursts, not HP simulation.

class Probe:
	extends "res://camp_presentation/camp_combat_effects.gd"
	var events: Array = []
	var phases: Array = []
	var submitted := 0
	var finite := true
	func reset_probe() -> void:
		events.clear()
		phases.clear()
		submitted = 0
		finite = true
	func _vertex(point: Vector3, color: Color, alpha: float) -> void:
		submitted += 1
		finite = finite and point.is_finite() and is_finite(alpha) and alpha >= 0.0 and alpha <= 1.0
		super._vertex(point, color, alpha)
	func _draw_skill(skill: Dictionary, phase: float, source: Vector3, target: Vector3, floor_point: Vector3, cycle_index: int,
		source_scale: float = 1.0, target_scale: float = 1.0) -> void:
		phases.append(phase)
		super._draw_skill(skill, phase, source, target, floor_point, cycle_index, source_scale, target_scale)
	func _draw_ultimate(skill: Dictionary, phase: float, source: Vector3, target: Vector3,
		caster_floor: Vector3, target_floor: Vector3, role: String, source_scale: float = 1.0, target_scale: float = 1.0) -> void:
		phases.append(phase)
		super._draw_ultimate(skill, phase, source, target, caster_floor, target_floor, role, source_scale, target_scale)
	func _beam(start: Vector3, finish: Vector3, width: float, color: Color, alpha: float) -> void:
		events.append({"kind": "beam", "center": finish, "radius": width})
		super._beam(start, finish, width, color, alpha)
	func _arrow(point: Vector3, direction: Vector3, radius: float, color: Color, alpha: float) -> void:
		events.append({"kind": "arrow", "center": point, "radius": radius})
		super._arrow(point, direction, radius, color, alpha)
	func _star(center: Vector3, radius: float, color: Color, alpha: float, rotation: float = 0.0) -> void:
		events.append({"kind": "star", "center": center, "radius": radius})
		super._star(center, radius, color, alpha, rotation)
	func _disc(center: Vector3, radius: float, color: Color, alpha: float) -> void:
		events.append({"kind": "disc", "center": center, "radius": radius})
		super._disc(center, radius, color, alpha)
	func _ring(center: Vector3, radius: float, width: float, color: Color, alpha: float, ground: bool, rotation: float = 0.0) -> void:
		events.append({"kind": "ground_ring" if ground else "ring", "center": center, "radius": radius})
		super._ring(center, radius, width, color, alpha, ground, rotation)
	func _crescent(center: Vector3, radius: float, width: float, color: Color, alpha: float, rotation: float) -> void:
		events.append({"kind": "strike", "center": center, "radius": radius})
		super._crescent(center, radius, width, color, alpha, rotation)

var checks := 0
var failures := 0
var peak_vertices := 0
var effects: Probe
var world: Node3D
var actors: Dictionary = {}

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		if failures <= 25:
			print("CAMP_EFFECT_HIT_TIMING_FAIL: " + label)

func sample(clock: float, role: String) -> Dictionary:
	effects.reset_probe()
	effects.present(actors, clock, "paused", true, null, 0.5)
	var state := effects.debug_state()
	var total := 0
	for count: int in state.vertices.values():
		total += count
		check(count <= 6000 and count >= 0 and count % 3 == 0, "existing per-role geometry budget")
	peak_vertices = maxi(peak_vertices, total)
	check(effects.finite and total == effects.submitted and total > 0 and total <= 9000, "actual finite CPU geometry matches diagnostics")
	check(state.activeRoles == [role] and effects.phases.size() == 1, "only requested actor's event is active")
	return {"events": effects.events.duplicate(true), "phases": effects.phases.duplicate(), "state": state}

func select(view: Dictionary, kind: String) -> Array:
	return view.events.filter(func(e: Dictionary) -> bool: return e.kind == kind)

func head_center(view: Dictionary, kind: String, count: int) -> Vector3:
	var parts := select(view, kind)
	check(parts.size() >= count, "expected existing projectile geometry present")
	var point := Vector3.ZERO
	for index in range(mini(count, parts.size())):
		point += parts[index].center
	return point / count

func target_point(role: String) -> Vector3:
	var actor: Dictionary = actors["hero" if role == "boss" else "boss"]
	return actor.root.position + Vector3.UP * (float(actor.heads[0]) * 0.44)

func burst_at(view: Dictionary, role: String, ultimate: bool) -> bool:
	var target_role := "hero" if role == "boss" else "boss"
	var size: float = effects._effect_scale(actors[target_role], target_role)
	var radius := 0.65 * lerpf(1.0, size, 0.5) if ultimate else (0.54 if role == "boss" else 0.46) * size
	var point := target_point(role)
	return select(view, "disc" if ultimate else "star").any(func(e: Dictionary) -> bool:
		return e.center.distance_to(point) < 0.00001 and is_equal_approx(e.radius, radius))

func projectile(view: Dictionary, id: String, ultimate: bool) -> Vector3:
	var style: String = effects.skill_for(id, id.get_slice("_", 0)).style
	if style == "runic_quake":
		return head_center(view, "star", 5 if ultimate else 3)
	if style in ["wind_arrow", "feather_fan", "golden_gale"]:
		return head_center(view, "arrow", 5 if ultimate else 3)
	if style in ["sun_cleave", "moon_dash", "foxfire"]:
		return head_center(view, "strike", 3 if style == "foxfire" else 1)
	if style in ["resonance", "antler_light"]:
		return head_center(view, "ring", 1)
	if style == "starfall":
		return head_center(view, "star", 6 if ultimate else 3)
	if style == "azure_breath":
		return head_center(view, "beam", 1)
	if style == "aether_flask" and ultimate:
		return head_center(view, "star", 3)
	return head_center(view, "disc", 1)

func test_ordinary_markers() -> void:
	for id: String in effects.SKILLS:
		var role := id.get_slice("_", 0)
		actors[role].id = id
		for cycle: int in [0, 1, 4, 5, 6, 600]:
			var base: float = cycle * 5.2 + effects.OFFSETS[role]
			var before := sample(base + 0.599999, role)
			var hit := sample(base + 0.60, role)
			var after := sample(base + 0.600001, role)
			var label := "%s cycle %d" % [id, cycle]
			check(not burst_at(before, role, false), "no target burst before ordinary receipt marker: " + label)
			check(burst_at(hit, role, false) and burst_at(after, role, false), "burst begins ON 0.60 marker: " + label)
			check(hit.phases == [0.60], "exact marker survives role offsets/cycle modulo: " + label)
			check(projectile(before, id, false).distance_to(target_point(role)) > 0.000005, "projectile still approaches immediately before marker: " + label)
			check(projectile(hit, id, false).distance_to(target_point(role)) < 0.00001, "projectile reaches target ON 0.60 marker: " + label)
			check(projectile(after, id, false).distance_to(target_point(role)) < 0.00001, "contact holds through the existing follow-through: " + label)
			if cycle == 5:
				check(sample(base + 0.60, role) == hit, "paused/final-hit marker has no self advancement")

func test_ultimate_markers() -> void:
	for id: String in effects.ULTIMATE_NAMES:
		var role := id.get_slice("_", 0)
		actors[role].id = id
		for cycle: int in [0, 1, 37]:
			var base := cycle * 31.2 + (15.6 if role == "boss" else 10.4)
			var before := sample(base + 1.429999, role)
			var hit := sample(base + 1.43, role)
			var after := sample(base + 1.430001, role)
			var label := "%s cycle %d" % [id, cycle]
			check(not burst_at(before, role, true), "no ultimate target burst before 1.43: " + label)
			check(burst_at(hit, role, true) and burst_at(after, role, true), "ultimate burst begins ON 1.43 marker: " + label)
			check(hit.phases == [1.43], "ultimate integer-microsecond phase remains exact: " + label)
			check(projectile(before, id, true).distance_to(target_point(role)) > 0.000005, "ultimate still approaches immediately before marker: " + label)
			check(projectile(hit, id, true).distance_to(target_point(role)) < 0.00001, "ultimate reaches target ON 1.43 marker: " + label)
			check(projectile(after, id, true).distance_to(target_point(role)) < 0.00001, "ultimate keeps its existing contact afterglow: " + label)

func run() -> void:
	world = Node3D.new()
	root.add_child(world)
	for role: String in ["hero", "pet", "boss"]:
		var actor_root := Node3D.new()
		world.add_child(actor_root)
		actor_root.position = {"hero": Vector3(-2, 0.15, 0.8), "pet": Vector3(-2.7, 0.17, -1.5), "boss": Vector3(2.2, 0.35, -0.8)}[role]
		var sprite := Sprite3D.new()
		actor_root.add_child(sprite)
		actors[role] = {"id": {"hero": "hero_ranger", "pet": "pet_deer", "boss": "boss_ancient_guardian"}[role],
			"root": actor_root, "sprite": sprite, "safe": true, "frame": 0,
			"height": 8.5 if role == "boss" else 2.8, "heads": [5.94] if role == "boss" else [1.98]}
	effects = Probe.new()
	world.add_child(effects)
	test_ordinary_markers()
	test_ultimate_markers()
	world.free()
	print("CAMP_EFFECT_HIT_TIMING_TEST: %s (%d/%d checks); peak CPU vertices=%d, no GPU/performance claim" % ["PASS" if failures == 0 else "FAIL", checks - failures, checks, peak_vertices])
	quit(0 if failures == 0 else 1)
