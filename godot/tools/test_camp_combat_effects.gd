extends RefCounted
## Independent, headless-only public presentation regression suite.
## Invoked by test_camp_presentation.gd with its disposable synthetic PCK.
## No real PNG edits, whole-world loads, GPU preview, server or private state.

const EFFECTS_PATH := "res://camp_presentation/camp_combat_effects.gd"
const ROLES := ["hero", "pet", "boss"]
const PUBLIC_ACTORS := {
	"hero_ranger": "hero", "hero_knight": "hero", "hero_mage": "hero",
	"hero_bard": "hero", "hero_alchemist": "hero", "hero_astrologer": "hero",
	"pet_deer": "pet", "pet_fox": "pet", "pet_rabbit": "pet",
	"pet_owl": "pet", "pet_finch": "pet", "pet_dragon": "pet",
	"boss_ancient_guardian": "boss",
}
const EXPECTED_STYLES := ["wind_arrow", "sun_cleave", "ember_orb", "resonance", "aether_flask", "starfall",
	"antler_light", "foxfire", "moon_dash", "feather_fan", "golden_gale", "azure_breath", "runic_quake"]
const DEBUG_KEYS := ["poolSize", "vertices", "activeRoles", "styles", "clock", "vertexLimit", "ultimate"]

class VertexProbe:
	extends "res://camp_presentation/camp_combat_effects.gd"
	# Observe the REAL CPU emission path, then delegate unchanged to ImmediateMesh.
	# This avoids treating empty dummy-renderer GPU readback as geometry evidence.
	var emitted: Array = []
	func _vertex(point: Vector3, color: Color, alpha: float) -> void:
		emitted.append([point, color, alpha])
		super._vertex(point, color, alpha)

class TestWeather:
	extends Node
	var night_blend := 0.0

var _tree: SceneTree
var _assertion: Callable
var _presentation: Script
var _effects: Script
var _catalogue: Dictionary
var _clock := 0.0
var _mesh_changes := 0
var _peak_vertices := 0

func check(value: bool, label: String) -> void:
	_assertion.call(value, "combat: " + label)

func ground(point: Vector2) -> Vector3:
	return Vector3(point.x, point.x * 0.025 + point.y * 0.018, point.y)

func permitted(_point: Vector2) -> bool:
	return true

func clock_value() -> float:
	return _clock

func snapshot(mode: String = "fighting") -> Dictionary:
	return {"mode": mode, "heroAssetId": "hero-test", "petAssetId": "pet-test", "bossAssetId": "boss-test",
		"elapsed": 12.0, "duration": 600.0, "roundId": "public-combat-test"}

func hp_snapshot(mode: String = "fighting", hp: int = 725, maximum: int = 1000) -> Dictionary:
	var state := snapshot(mode)
	state.bossHp = hp
	state.bossMaxHp = maximum
	return state

func fixture(catalogue: Dictionary = {}) -> Dictionary:
	var world := Node3D.new()
	_tree.root.add_child(world)
	var weather := TestWeather.new()
	weather.name = "LivingWeather"
	world.add_child(weather)
	var light := DirectionalLight3D.new()
	light.light_energy = 1.2
	light.light_color = Color(0.65, 0.79, 1.0)
	light.rotation_degrees = Vector3(-28, -145, 0)
	world.add_child(light)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_color = Color(0.1, 0.2, 0.3)
	world.add_child(environment)
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.position = Vector3(18, 20, 25)
	camera.look_at(Vector3(5, 0, -12))
	camera.current = true
	var scene: Node3D = _presentation.new()
	world.add_child(scene)
	check(scene.setup(world, _catalogue if catalogue.is_empty() else catalogue, ground, permitted, clock_value),
		"isolated real presentation setup")
	scene.set_process(false)
	check(scene.apply_snapshot(snapshot()), "synthetic complete snapshot accepted")
	return {"world": world, "weather": weather, "light": light, "environment": environment,
		"camera": camera, "scene": scene}

func effects_fixture() -> Dictionary:
	# Standalone VFX tests can run before the renderer/HUD merge lands. These
	# nodes are tiny TEST fixtures, never actor artwork or a substitute world.
	var world := Node3D.new()
	_tree.root.add_child(world)
	var light := DirectionalLight3D.new()
	world.add_child(light)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	world.add_child(environment)
	var camera := Camera3D.new()
	world.add_child(camera)
	camera.position = Vector3(18, 20, 25)
	camera.look_at(Vector3(5, 0, -12))
	var actors: Dictionary = {}
	var positions := {"hero": Vector2(2.85, -10.90), "pet": Vector2(3.65, -9.90), "boss": Vector2(6.25, -12.4)}
	var ids := {"hero": "hero_ranger", "pet": "pet_deer", "boss": "boss_ancient_guardian"}
	for role: String in ROLES:
		var actor_root := Node3D.new()
		world.add_child(actor_root)
		actor_root.position = ground(positions[role])
		var sprite := Sprite3D.new()
		actor_root.add_child(sprite)
		var shadow := MeshInstance3D.new()
		actor_root.add_child(shadow)
		var fill := OmniLight3D.new()
		actor_root.add_child(fill)
		actors[role] = {"id": ids[role], "role": role, "root": actor_root, "sprite": sprite,
			"shadow": shadow, "moon_fill": fill, "height": 3.8 if role == "boss" else 1.8, "safe": true}
	return {"world": world, "light": light, "environment": environment, "camera": camera, "actors": actors}

func effects_of(scene: Node3D) -> Node3D:
	for child: Node in scene.get_children():
		var script: Script = child.get_script()
		if child is Node3D and script != null and script.resource_path == EFFECTS_PATH:
			return child
	return null

func hud_of(scene: Node3D) -> CanvasLayer:
	for child: Node in scene.get_children():
		if child is CanvasLayer and child.has_method("debug_state"):
			return child
	return null

func pool_of(effects: Node3D) -> Array:
	var pool: Array = []
	for child: Node in effects.get_children():
		if child is MeshInstance3D:
			pool.append(child)
	return pool

func pool_identity(effects: Node3D) -> Array:
	var result: Array = []
	for mesh: MeshInstance3D in pool_of(effects):
		result.append([mesh.get_instance_id(), mesh.mesh.get_instance_id() if mesh.mesh != null else 0,
			mesh.material_override.get_instance_id() if mesh.material_override != null else 0])
	return result

func pool_view(effects: Node3D) -> Array:
	# ImmediateMesh keeps its surface count and AABB on CPU. The headless dummy
	# renderer does NOT expose GPU vertex arrays: an empty readback is no proof.
	var result: Array = []
	for mesh: MeshInstance3D in pool_of(effects):
		result.append([mesh.visible, mesh.transform, mesh.mesh.get_surface_count(), mesh.mesh.get_aabb()])
	return result

func pool_hidden(effects: Node3D) -> bool:
	for mesh: MeshInstance3D in pool_of(effects):
		if mesh.is_visible_in_tree():
			return false
	return true

func check_diagnostics(effects: Node3D) -> int:
	var state: Dictionary = effects.debug_state()
	check(state.size() == DEBUG_KEYS.size() and DEBUG_KEYS.all(func(key: String) -> bool: return state.has(key)),
		"diagnostics expose the agreed seven fields, not gameplay state")
	if not DEBUG_KEYS.all(func(key: String) -> bool: return state.has(key)):
		return -1
	check(state.poolSize == 3 and state.vertexLimit == 6000 and state.vertices.size() == 3,
		"pool and per-role vertex ceiling match the current explicit API")
	var total := 0
	for role: String in ROLES:
		var count: Variant = state.vertices.get(role)
		check(count is int and count >= 0 and count <= state.vertexLimit and count % 3 == 0,
			"reported geometry is whole triangles within the role budget: " + role)
		if count is int:
			total += count
		var mesh: MeshInstance3D = effects.get_node(role.capitalize() + "Skill")
		check(mesh.visible == (count > 0) and state.activeRoles.has(role) == mesh.visible,
			"diagnostic activity matches actual pooled visibility: " + role)
		check(mesh.mesh.get_surface_count() == (1 if count > 0 else 0),
			"active geometry has one nonempty surface; inactive slots have none: " + role)
	check(total <= 9000, "actual simultaneous emitted total stays inside the discussed 9000-vertex envelope")
	_peak_vertices = maxi(_peak_vertices, total)
	return total

func mesh_changed() -> void:
	_mesh_changes += 1

func actor_state(actors: Dictionary) -> Dictionary:
	var nodes: Dictionary = {}
	for role: String in actors:
		var actor: Dictionary = actors[role]
		nodes[role] = [actor.root.transform, actor.root.visible, actor.sprite.transform,
			actor.sprite.texture, actor.sprite.offset, actor.sprite.layers, actor.sprite.shaded,
			actor.shadow.transform, actor.shadow.material_override, actor.moon_fill.light_energy,
			actor.moon_fill.light_cull_mask]
	return {"data": actors.duplicate(true), "nodes": nodes}

func world_state(test: Dictionary) -> Array:
	var children: Array = []
	for child: Node in test.world.get_children():
		children.append(child.get_instance_id())
	return [children, test.world.transform, test.light.transform, test.light.light_energy,
		test.light.light_color, test.light.light_cull_mask, test.environment.environment,
		test.environment.environment.background_color, test.camera.transform, test.camera.cull_mask]

func step(scene: Node3D, delta: float = 0.1) -> void:
	_clock += delta
	scene._process(delta)

func test_confirmed_hp() -> void:
	var test := fixture()
	var scene: Node3D = test.scene
	check(scene.has_method("_confirmed_boss_ratio"), "confirmed-only Boss ratio API exists")
	if not scene.has_method("_confirmed_boss_ratio"):
		test.world.free()
		return
	var hud := hud_of(scene)
	check(hud != null, "HUD is a presentation-owned CanvasLayer with debug_state")
	for elapsed: float in [0.0, 150.0, 300.0, 599.5, 600.0]:
		var state := snapshot()
		state.elapsed = elapsed
		var supplied: Dictionary = state.duplicate(true)
		check(scene.apply_snapshot(state), "confirmed HP input accepted at " + str(elapsed))
		var expected := 1.0 - elapsed / 600.0
		check(is_equal_approx(scene._confirmed_boss_ratio(), expected), "ratio is exactly 1 - confirmed elapsed / duration")
		var authoritative: Dictionary = scene._snapshot.duplicate(true)
		# Age affects legacy visualElapsed; it must NEVER reduce confirmed HP.
		scene._received_msec = Time.get_ticks_msec() - 2000
		for index in range(60):
			step(scene)
		check(is_equal_approx(scene._confirmed_boss_ratio(), expected), "a full local action cycle cannot reduce HP")
		check(scene._snapshot == authoritative and state == supplied,
			"skills neither mutate the input nor add damage/reward/settlement fields")
		check(scene.get_presentation_status().mode == "fighting", "zero displayed HP never decides victory or cooldown")
		if hud != null:
			var displayed: Dictionary = hud.debug_state()
			check(displayed.visible and displayed.presentation_only and is_equal_approx(displayed.ratio, expected)
				and displayed.percent == ceili(expected * 100.0), "visible HUD fill and percent use only the confirmed sample")
			check(displayed.trail_ratio >= displayed.ratio and displayed.trail_ratio <= 1.0,
				"optional damage trail never changes the real fill or escapes its bound")
	var good := snapshot()
	good.elapsed = 300.0
	check(scene.apply_snapshot(good), "restore confirmed mid-round state")
	for change: Dictionary in [{"elapsed": NAN}, {"elapsed": true}, {"elapsed": 601.0},
		{"duration": 0.0}, {"damage": 20}, {"reward": "synthetic-only"},
		{"heroAssetId": "hero-unknown"}, {"heroAssetId": "boss-test"}]:
		var bad: Dictionary = good.duplicate(true)
		bad.merge(change, true)
		var before: Dictionary = scene._snapshot.duplicate(true)
		check(not scene.apply_snapshot(bad), "invalid or authority-bearing data stays rejected: " + str(change.keys()))
		check(scene._snapshot == before and is_equal_approx(scene._confirmed_boss_ratio(), 0.5),
			"rejected input leaves the last confirmed HP and public state unchanged")
	test.world.free()

func test_real_hp_and_confirmed_death() -> void:
	var test := fixture()
	var scene: Node3D = test.scene
	var effects := effects_of(scene)
	var hud := hud_of(scene)
	var identity := pool_identity(effects)
	var unchanged_world := world_state(test)
	var original_frames: Array = scene._actors.boss.frames.duplicate()
	var original_pixels: Array = []
	for frame: Texture2D in original_frames:
		original_pixels.append(frame.get_image().get_data())
	for elapsed: float in [0.0, 300.0, 600.0]:
		var supplied := hp_snapshot()
		supplied.elapsed = elapsed
		check(scene.apply_snapshot(supplied), "real integer HP snapshot accepted independently of elapsed")
		for phase: float in [0.65, 10.9, 11.5, 16.1, 17.2, 20.0]:
			scene._motion_clock = phase
			scene._update_actors()
			step(scene)
			check(is_equal_approx(scene._confirmed_boss_ratio(), 0.725) and scene._snapshot == supplied,
				"normal skills and both ultimates cannot predict damage or reduce confirmed HP")
			check(hud.debug_state().visible and is_equal_approx(hud.debug_state().ratio, 0.725)
				and hud.debug_state().percent == 73, "actual Boss bar displays HP/max, never the old elapsed ratio")
			check(not scene._death_active and scene._current_death_age() < 0.0,
				"elapsed reaching duration cannot kill a Boss with confirmed positive HP")
			check(scene._actors.boss.sprite.render_priority == 0, "living cutout Boss keeps its original priority before defeat")
	var zero := hp_snapshot("fighting", 0)
	check(scene.apply_snapshot(zero), "confirmed zero HP may arrive before the explicit defeated mode")
	check(scene._pending_death and not scene._death_active and is_equal_approx(hud.debug_state().ratio, 0.725),
		"confirmed zero first releases a visible finishing attack, not an idle HP drop")
	for tick in range(6):
		step(scene)
	check(scene._death_active and scene._current_death_age() == 0.0 and scene._snapshot.mode == "fighting",
		"the final visible impact starts only local defeat, never changes supplied authority mode")
	check(scene._pose("boss").row == 3 and scene._pose("hero").row == 2 and scene._pose("pet").row == 0,
		"registered Boss hit pose and hero follow-through show the final impact")
	check(not hud.debug_state().ultimate.visible and effects.debug_state().activeRoles == ["boss"]
		and effects.debug_state().styles.get("boss") == "guardian_defeat", "death cancels the ultimate strip and every ordinary skill")
	for tick in range(8):
		step(scene)
	var age: float = scene._current_death_age()
	check(age > 0.5 and age < 1.0 and scene._actors.boss.sprite.modulate.a == 1.0
		and scene._actors.boss.sprite.basis != Basis.IDENTITY,
		"shared steps advance a legible weighted collapse before the body fades")
	check(scene._actors.boss.sprite.render_priority == 127, "blended death sprite draws after frozen priority-126 screen copy")
	for role: String in ["hero", "pet"]:
		check(scene._actors[role].sprite.render_priority == 0, "Boss death never changes another actor's render priority: " + role)
	check(scene.apply_snapshot(zero) and is_equal_approx(scene._current_death_age(), age), "duplicate zero-HP snapshot never replays death")
	var dead := hp_snapshot("defeated", 0)
	check(scene.apply_snapshot(dead) and is_equal_approx(scene._current_death_age(), age), "later defeated mode keeps the same in-progress death")
	check(scene._snapshot == dead and not scene._snapshot.has("reward") and not scene._snapshot.has("damage"),
		"death retains exactly the supplied public fields, without any local settlement output")
	for tick in range(40):
		step(scene)
	check(not scene._actors.boss.root.visible and not scene._actors.boss.shadow.is_visible_in_tree(),
		"completed death hides the real Boss and its grounded contact shadow")
	check(scene._actors.hero.root.visible and scene._actors.pet.root.visible and pool_hidden(effects)
		and not hud.debug_state().ultimate.visible, "death leaves allies present without orphan skill effects")
	var ended: float = scene._current_death_age()
	check(scene.apply_snapshot(dead) and is_equal_approx(scene._current_death_age(), ended)
		and not scene._actors.boss.root.visible, "repeated defeated state cannot resurrect an already hidden Boss")
	for tick in range(320):
		step(scene)
	check(scene._snapshot == dead and scene._snapshot.mode == "defeated" and not scene._actors.boss.root.visible,
		"a full local choreography cycle never respawns or settles a confirmed defeated round")
	for mode: String in ["cooldown", "daily_complete", "waiting", "unavailable"]:
		check(scene.apply_snapshot(hp_snapshot(mode, 0)), "post-defeat/hidden public mode accepted: " + mode)
		step(scene)
		check(not scene._actors.boss.root.visible and pool_hidden(effects) and not hud.debug_state().ultimate.visible,
			"post-defeat or hidden mode has no Boss, death particles or ultimate strip: " + mode)
	var next := hp_snapshot("fighting", 1000)
	next.roundId = "public-confirmed-next-round"
	next.elapsed = 0.0
	check(scene.apply_snapshot(next) and scene._actors.boss.root.visible and not scene._death_active,
		"only a new confirmed live state restores the Boss")
	check(scene._actors.boss.sprite.modulate == Color.WHITE
		and scene._actors.boss.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD
		and scene._actors.boss.sprite.render_priority == 0
		and is_equal_approx(scene._actors.boss.sprite.alpha_scissor_threshold, 32.0 / 255.0),
		"new live round restores the exact normal shaded cutout appearance")
	check(scene._actors.boss.frames == original_frames and pool_identity(effects) == identity,
		"HP, death and a new round reuse original textures and the same three effect meshes")
	for index in range(original_frames.size()):
		check(original_frames[index].get_image().get_data() == original_pixels[index], "death never changes source frame pixels: " + str(index))
	check(world_state(test) == unchanged_world, "death and HP updates never mutate world lights, camera or environment")
	test.world.free()

func test_death_gates_and_spectator_cycle() -> void:
	var test := fixture()
	var scene: Node3D = test.scene
	var effects := effects_of(scene)
	var identity := pool_identity(effects)
	for gate: String in ["paused", "local_pause", "stale", "hidden", "parent_hidden"]:
		scene.visible = true
		test.world.visible = true
		scene.set_animation_paused(false)
		var alive := hp_snapshot("fighting", 1000)
		alive.roundId = "public-death-gate-" + gate
		check(scene.apply_snapshot(alive), "fresh live state for death gate: " + gate)
		var dead: Dictionary = alive.duplicate(true)
		dead.mode = "defeated"
		dead.bossHp = 0
		check(scene.apply_snapshot(dead), "confirmed death starts before gate: " + gate)
		for tick in range(7):
			step(scene)
		match gate:
			"paused":
				dead.mode = "paused"
				scene.apply_snapshot(dead)
			"local_pause":
				scene.set_animation_paused(true)
			"stale":
				scene._received_msec = Time.get_ticks_msec() - 16000
			"hidden":
				scene.visible = false
			"parent_hidden":
				test.world.visible = false
		step(scene, 0.0)
		var age: float = scene._current_death_age()
		var phase: float = scene._motion_clock
		var appearance := pool_view(effects)
		var sprite: Sprite3D = scene._actors.boss.sprite
		var pose := [sprite.transform, sprite.texture, sprite.modulate, sprite.offset]
		var state: Dictionary = scene._snapshot.duplicate(true)
		for tick in range(12):
			step(scene)
		check(is_equal_approx(scene._current_death_age(), age) and is_equal_approx(scene._motion_clock, phase)
			and [sprite.transform, sprite.texture, sprite.modulate, sprite.offset] == pose
			and pool_view(effects) == appearance, "death pose, fade and particles obey the same freeze gate: " + gate)
		check(scene._snapshot == state and pool_identity(effects) == identity, "death gates cannot alter public HP or rebuild the pool: " + gate)
	scene.visible = true
	test.world.visible = true
	scene.set_animation_paused(false)
	var spectator := snapshot("demo")
	spectator.elapsed = 0.0
	spectator.duration = 0.0
	spectator.roundId = ""
	check(scene.apply_snapshot(spectator), "legacy unauthenticated spectator snapshot stays supported")
	# The preceding real round has a different site. Walk there through the
	# owner-driven process before auditing fixed spectator pose-table phases.
	for _index in range(400):
		if not scene._travel_active:
			break
		step(scene, 0.05)
	check(not scene._travel_active and not scene._travel_blocked, "spectator relocation completes before isolated death-pose sampling")
	scene._process(0.0)
	for phase: float in [25.9, 26.0, 26.599, 26.6, 26.8, 28.7, 29.3, 31.199, 31.2, 31.3]:
		scene._motion_clock = phase
		scene._update_actors()
		var dead: bool = phase >= 26.6 and phase < 31.2
		check((scene._current_death_age() >= 0.0) == dead, "spectator death starts on the 26.6s hero impact and resets at 31.2s: " + str(phase))
		check(scene._actors.boss.root.visible == (phase < 29.2 or phase >= 31.2), "spectator Boss actually fades away before the next cycle: " + str(phase))
		check(scene._actors.boss.sprite.render_priority == (127 if dead else 0),
			"spectator death/new cycle switches only Boss transparent/live priority: " + str(phase))
		check(scene._snapshot == spectator and scene._snapshot.size() == 7 and not scene._death_active,
			"spectator choreography never invents confirmed HP, nonce, victory or rewards")
		check(pool_identity(effects) == identity, "spectator cycle never allocates a new effect pool")
	test.world.free()

func test_defeat_cpu_geometry() -> void:
	var test := effects_fixture()
	var effects := VertexProbe.new()
	test.world.add_child(effects)
	effects.configure()
	var identity := pool_identity(effects)
	var unchanged_actors := actor_state(test.actors)
	var unchanged_world := world_state(test)
	for age: float in [0.0, 0.35, 0.8, 1.5, 2.6, 3.199]:
		for night: float in [0.0, 1.0]:
			effects.emitted.clear()
			effects.present_defeat(test.actors, age, test.camera, night)
			var actual: Array = effects.emitted.duplicate(true)
			check(not actual.is_empty() and check_diagnostics(effects) == actual.size(), "defeat has real counted CPU triangle submissions")
			check(effects.debug_state().activeRoles == ["boss"] and effects.debug_state().styles.boss == "guardian_defeat"
				and not effects.debug_state().ultimate.get("active", false), "only the single Boss pool slot emits defeat, never an ultimate")
			var finite := true
			for vertex: Array in actual:
				finite = finite and vertex[0].is_finite() and is_finite(vertex[2]) and vertex[2] >= 0.0 and vertex[2] <= 1.0
			check(finite and pool_identity(effects) == identity, "death vertices/colors remain finite and bounded in the existing pool")
			effects.emitted.clear()
			effects.present_defeat(test.actors, age, test.camera, night)
			check(effects.emitted == actual, "same death age reproduces every actual submitted vertex and alpha")
	for age: float in [-1.0, NAN, INF, 3.2, 1000000000.0]:
		effects.present_defeat(test.actors, age, test.camera, 1.0)
		check(pool_hidden(effects) and check_diagnostics(effects) == 0 and pool_identity(effects) == identity,
			"invalid or completed death clears all geometry without new nodes")
	check(actor_state(test.actors) == unchanged_actors and world_state(test) == unchanged_world,
		"death module never modifies actors, ground roots, shadows or original world lighting")
	test.world.free()

func test_fixed_pool() -> void:
	var test := effects_fixture()
	var actors: Dictionary = test.actors
	var effects: Node3D = _effects.new()
	test.world.add_child(effects)
	effects.configure()
	var pool := pool_of(effects)
	check(pool.size() == 3 and effects.get_child_count() == 3, "configure creates exactly three pooled mesh nodes")
	if pool.size() != 3:
		test.world.free()
		return
	for mesh: MeshInstance3D in pool:
		check(mesh.mesh is ImmediateMesh and mesh.get_child_count() == 0, "pool slots have ImmediateMesh and no child emitters/timers/lights")
	var identity := pool_identity(effects)
	effects.configure()
	check(pool_identity(effects) == identity and effects.get_child_count() == 3, "duplicate configure cannot allocate another pool")
	check(not effects.is_processing(), "module owns no autonomous process clock")
	var material: ShaderMaterial = pool[0].material_override
	check(material.render_priority == 127, "transparent skills composite after the frozen priority-126 focus pass")
	for mesh: MeshInstance3D in pool:
		check(mesh.material_override == material and mesh.material_override.render_priority == 127
			and mesh.cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_OFF,
			"all three pooled roles share the exact after-focus material without world shadows")
	var uniform_names: Array = []
	for uniform: Dictionary in material.shader.get_shader_uniform_list():
		uniform_names.append(uniform.name)
	check(uniform_names == ["night_restraint"], "headless shader parser exposes only the local restraint uniform")
	check(material.shader.code.contains("unshaded") and material.shader.code.contains("depth_draw_never")
		and not material.shader.code.contains("TIME") and not material.shader.code.contains("depth_test_disabled"),
		"shader has no independent clock, world-light contribution or through-world depth bypass")
	var unchanged_actors := actor_state(actors)
	var unchanged_world := world_state(test)
	var seen_active := false
	for cycle in range(6):
		for tick in range(313):
			var phase := cycle * 31.2 + tick * 0.1
			effects.present(actors, phase, "fighting", true, test.camera, float(cycle % 2))
			seen_active = seen_active or not pool_hidden(effects)
			check(effects.get_child_count() == 3 and pool_identity(effects) == identity,
				"full cycles reuse every mesh node, ImmediateMesh and material")
			for mesh: MeshInstance3D in pool:
				check(mesh.mesh.get_surface_count() <= 1, "old geometry surfaces never accumulate")
			check_diagnostics(effects)
	check(seen_active, "real skill geometry is exercised, not an always-hidden passing fixture")
	check(material.render_priority == 127, "normal/ultimate/day/night regeneration never resets the material to default priority")
	# Exact phase from the formerly invisible Web capture. CPU submission and
	# ordering are regression evidence, not a substitute for main's GPU image.
	effects.present(actors, 12.13, "paused", true, test.camera, 0.0)
	var afterglow: Dictionary = effects.debug_state()
	var target: Vector3 = actors.boss.root.position + Vector3.UP * float(actors.boss.height) * 0.44
	check(afterglow.ultimate.stage == "AFTERGLOW" and afterglow.activeRoles == ["hero"]
		and afterglow.vertices.hero == 336 and pool[0].mesh.get_surface_count() == 1,
		"paused 12.13s Ranger afterglow still contains its ring, twelve trails, disc and star")
	check(pool[0].material_override.render_priority == 127 and pool[0].mesh.get_aabb().get_center().distance_to(target) < 0.15,
		"the real 12.13s mesh is centered at the Boss target and ordered after the focus pass")
	check(actor_state(actors) == unchanged_actors, "direct VFX never edits actor data, frames, light, transform or selection")
	check(world_state(test) == unchanged_world, "day/night VFX leaves world nodes, camera, environment and light untouched")
	for phase: float in [0.0, 0.3, 0.58, 0.94, 1.5, 2.08, 3.58, 5.19, 5.2]:
		effects.present(actors, phase, "fighting", true, test.camera, 0.5)
		var first := pool_view(effects)
		var diagnostic: Dictionary = effects.debug_state()
		effects.present(actors, phase, "fighting", true, test.camera, 0.5)
		check(pool_view(effects) == first and effects.debug_state() == diagnostic, "same clock reproduces geometry bounds and all diagnostic state")
		effects.present(actors, phase + 10.4, "fighting", true, test.camera, 1.0)
		effects.present(actors, phase, "fighting", true, test.camera, 0.5)
		check(pool_view(effects) == first, "returning to a clock does not retain a previous emission")
	effects.hide_effects()
	check(pool_hidden(effects) and pool_identity(effects) == identity, "hide uses the same pool without destroying or adding nodes")
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete"]:
		effects.present(actors, 0.65, mode, true, test.camera, 1.0)
		check(pool_hidden(effects), "noncombat mode hides skill pool: " + mode)
	effects.present(actors, 0.65, "fighting", false, test.camera, 1.0)
	check(pool_hidden(effects), "disabled presentation hides skill pool")
	for bad_clock: float in [NAN, INF, -0.1]:
		effects.present(actors, bad_clock, "fighting", true, test.camera, 0.0)
		check(pool_hidden(effects) and pool_identity(effects) == identity, "invalid clock fails closed without allocating nodes")
	for night: float in [0.0, 0.5, 1.0, NAN, INF, -10.0, 10.0]:
		effects.present(actors, 0.65, "fighting", true, test.camera, night)
		var restraint: float = material.get_shader_parameter("night_restraint")
		check(is_finite(restraint) and restraint >= 0.78 - 0.00001 and restraint <= 1.0,
			"night restraint remains bounded even with malformed optional weather")
	var debug_before: Dictionary = effects.debug_state()
	var returned: Dictionary = effects.debug_state()
	returned.vertices.hero = 999999
	returned.styles.clear()
	returned.activeRoles.clear()
	check(effects.debug_state() == debug_before, "mutating returned diagnostics cannot alter runtime state")
	test.world.free()

func expected_ultimate(clock: float) -> Dictionary:
	# Independent decimal-time oracle: avoid copying production's floating
	# modulo and reproducing its boundary mistakes in expected values.
	var result := {"reserved": false, "active": false, "role": "", "phase": 0.0, "stage": ""}
	if not is_finite(clock) or clock < 0.0:
		return result
	var micros: int = roundi(clock * 1000000.0) % 31200000
	result.reserved = micros >= 10400000 and micros < 20800000
	var phase := -1
	if micros >= 10400000 and micros < 13800000:
		result.role = "hero"
		phase = micros - 10400000
	elif micros >= 15600000 and micros < 19000000:
		result.role = "boss"
		phase = micros - 15600000
	if phase >= 0:
		result.active = true
		result.phase = phase / 1000000.0
		result.stage = "CHARGE" if phase < 950000 else ("UNLEASH" if phase < 1500000 else "AFTERGLOW")
	return result

func test_ultimate_timeline_and_geometry() -> void:
	for cycle: float in [0.0, 31.2, 62.4]:
		for local: float in [0.0, 10.3999, 10.4, 10.4001, 11.3499, 11.35, 11.3501,
			11.8999, 11.9, 11.9001, 13.7999, 13.8, 13.8001, 15.5999, 15.6, 15.6001,
			16.5499, 16.55, 16.5501, 17.0999, 17.1, 17.1001, 18.9999, 19.0, 19.0001,
			20.7999, 20.8, 20.8001, 31.1999, 31.2]:
			var clock := cycle + local
			var expected := expected_ultimate(clock)
			var actual: Dictionary = _effects.ultimate_state(clock)
			check(actual.size() == 5 and actual.get("reserved") == expected.reserved and actual.get("active") == expected.active
				and actual.get("role") == expected.role and actual.get("stage") == expected.stage
				and is_equal_approx(float(actual.get("phase", -1.0)), expected.phase),
				"ultimate half-open boundary at %.4fs expected %s, got %s" % [clock, str(expected), str(actual)])
			check(actual == _effects.ultimate_state(clock), "ultimate timeline is a pure deterministic clock query")
	for clock: float in [-1.0, NAN, INF]:
		check(_effects.ultimate_state(clock) == expected_ultimate(clock), "invalid ultimate clock is inactive, never an action trigger")
	var test := effects_fixture()
	var effects := VertexProbe.new()
	test.world.add_child(effects)
	effects.configure()
	var identity := pool_identity(effects)
	var actors: Dictionary = test.actors
	var titles: Array = []
	for id: String in PUBLIC_ACTORS:
		var role: String = PUBLIC_ACTORS[id]
		if role == "pet":
			continue
		var title: String = _effects.ultimate_name(id, role)
		check(not title.is_empty() and title.length() <= 64 and not titles.has(title), "each hero and Boss has a bounded distinct ultimate title: " + id)
		titles.append(title)
		actors[role].id = id
		var start := 10.4 if role == "hero" else 15.6
		var unchanged := actor_state(actors)
		for phase: float in [0.001, 0.5, 0.949, 0.951, 1.0, 1.119, 1.121, 1.429, 1.431,
			1.499, 1.501, 1.529, 1.531, 1.629, 1.631, 2.0, 2.349, 2.351, 3.399]:
			effects.emitted.clear()
			effects.present(actors, start + phase, "fighting", true, test.camera, 0.5)
			var actual: Array = effects.emitted.duplicate(true)
			var debug: Dictionary = effects.debug_state()
			check(check_diagnostics(effects) == actual.size() and not actual.is_empty(), "ultimate emits counted real CPU triangles: " + id)
			check(debug.activeRoles == [role] and debug.styles.get(role) == "ultimate_" + _effects.skill_for(id, role).style,
				"only the selected ultimate caster draws; all regular skills are suppressed: " + id)
			var finite := true
			for vertex: Array in actual:
				finite = finite and vertex[0].is_finite() and is_finite(vertex[2]) and vertex[2] >= 0 and vertex[2] <= 1
			check(finite and pool_identity(effects) == identity, "ultimate geometry stays finite and reuses the existing pool")
			effects.emitted.clear()
			effects.present(actors, start + phase, "fighting", true, test.camera, 0.5)
			check(effects.emitted == actual and effects.debug_state() == debug, "same ultimate clock repeats exact emitted vertices and diagnostic state")
		check(actor_state(actors) == unchanged, "ultimate cannot mutate actor state, transforms, selection or artwork")
	for gap: float in [13.8001, 14.0, 15.5999, 19.0001, 19.5, 20.7999]:
		effects.emitted.clear()
		effects.present(actors, gap, "fighting", true, test.camera, 0.0)
		check(effects.emitted.is_empty() and pool_hidden(effects) and effects.debug_state().ultimate.reserved
			and not effects.debug_state().ultimate.active, "reserved ultimate gap suppresses every ordinary skill")
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete"]:
		effects.present(actors, 11.0, mode, true, test.camera, 0.0)
		check(pool_hidden(effects) and not effects.debug_state().ultimate.active, "mode transition clears active ultimate: " + mode)
	effects.present(actors, 16.2, "fighting", true, test.camera, 0.0)
	effects.hide_effects()
	check(pool_hidden(effects) and not effects.debug_state().ultimate.active and pool_identity(effects) == identity,
		"explicit hide clears ultimate bookkeeping as well as real geometry")
	test.world.free()

func test_ultimate_round_and_pose() -> void:
	var test := fixture()
	var scene: Node3D = test.scene
	var effects := effects_of(scene)
	var supplied := snapshot()
	supplied.elapsed = 300.0
	check(scene.apply_snapshot(supplied), "confirmed mid-round sample before cosmetic ultimate")
	var authoritative: Dictionary = scene._snapshot.duplicate(true)
	for role: String in ["hero", "boss"]:
		var start := 10.4 if role == "hero" else 15.6
		var target := "boss" if role == "hero" else "hero"
		for phase: float in [0.5, 1.0, 1.5, 2.0, 2.4]:
			scene._motion_clock = start + phase
			check(scene._update_actors(), "ultimate actor travel still passes the real ground sampler")
			var pose: Dictionary = scene._pose(role)
			check(pose.row == (2 if phase < 1.63 else (1 if phase < 2.35 else 0))
				and pose.frame >= 0 and pose.frame <= 7 and pose.travel >= 0.0 and pose.travel <= 1.0,
				"ultimate caster uses bounded registered charge/attack/return poses: " + role)
			check(scene._pose("pet").row == 0 and scene._pose(target).row == (3 if phase == 1.5 else 0),
				"only the timed target reacts; pets never start a normal skill inside ultimate reservation")
			check(scene._snapshot == authoritative and is_equal_approx(scene._confirmed_boss_ratio(), 0.5),
				"ultimate hits cannot reduce confirmed HP, elapsed, round state or create rewards")
	var identity := pool_identity(effects)
	scene._motion_clock = 16.2
	scene._update_actors()
	check(effects.debug_state().ultimate.active, "round-change test starts with a real active Boss ultimate")
	var next := snapshot()
	next.roundId = "public-combat-next-round"
	next.elapsed = 0.0
	var expected_next: Dictionary = next.duplicate(true)
	check(scene.apply_snapshot(next), "new confirmed public round accepted")
	check(scene._snapshot == expected_next and next == expected_next and scene._motion_clock == 0.0
		and is_equal_approx(scene._confirmed_boss_ratio(), 1.0), "only the supplied new round resets phase and HP")
	check(not effects.debug_state().ultimate.active and pool_identity(effects) == identity,
		"new round removes old ultimate without creating a new pool or settlement")
	test.world.free()

func test_styles_and_cpu_vertices() -> void:
	var test := effects_fixture()
	var actors: Dictionary = test.actors
	var effects := VertexProbe.new()
	test.world.add_child(effects)
	effects.configure()
	var observed_styles: Array = []
	var palettes: Array = []
	var index := 0
	for id: String in PUBLIC_ACTORS:
		var role: String = PUBLIC_ACTORS[id]
		var skill: Dictionary = _effects.skill_for(id, role)
		check(skill.size() == 3 and skill.has("style") and skill.has("color") and skill.has("accent"),
			"explicit style/color/accent contract for " + id)
		check(skill.get("style") == EXPECTED_STYLES[index] and skill == _effects.skill_for(id, role),
			"public actor has its own deterministic named skill: " + id)
		index += 1
		observed_styles.append(skill.style)
		check(skill.color is Color and skill.accent is Color, "both palette entries are Godot colors: " + id)
		for color: Color in [skill.color, skill.accent]:
			check(Vector4(color.r, color.g, color.b, color.a).is_finite() and color.r >= 0 and color.r <= 1
				and color.g >= 0 and color.g <= 1 and color.b >= 0 and color.b <= 1 and color.a == 1,
				"bounded finite opaque source palette: " + id)
		check(not palettes.has([skill.color, skill.accent]), "actor palette is not an accidental generic duplicate: " + id)
		palettes.append([skill.color, skill.accent])
		actors[role].id = id
		actors[role].sprite.position.y = 1.25 if id in ["pet_owl", "pet_finch", "pet_dragon"] else 0.0
		var offset: float = {"hero": 0.0, "pet": 1.5, "boss": 3.0}[role]
		var saw_primary := false
		var saw_accent := false
		for phase: float in [0.0, 0.29, 0.30, 0.59, 0.60, 0.62, 0.63, 0.65, 0.66, 0.94, 1.29, 1.30, 1.31]:
			var clock := offset + phase
			effects.emitted.clear()
			effects.present(actors, clock, "fighting", true, test.camera, 0.0)
			check(check_diagnostics(effects) == effects.emitted.size(), "reported vertex count equals actual CPU submissions: " + id)
			var actual: Array = effects.emitted.duplicate(true)
			var finite := true
			for vertex: Array in actual:
				finite = finite and vertex[0].is_finite() and is_finite(vertex[2]) and vertex[2] >= 0 and vertex[2] <= 1
				saw_primary = saw_primary or vertex[1] == skill.color
				saw_accent = saw_accent or vertex[1] == skill.accent
			check(finite, "actual submitted positions and alpha remain finite and bounded: " + id)
			if phase < 1.30:
				check(not actual.is_empty() and effects.debug_state().styles.get(role) == skill.style,
					"every active-phase branch emits real triangles using its selected style: " + id)
			effects.emitted.clear()
			effects.present(actors, clock, "fighting", true, test.camera, 0.0)
			check(effects.emitted == actual, "same clock reproduces every actual CPU vertex and color: " + id)
			effects.emitted.clear()
			effects.present(actors, clock + 10.4, "fighting", true, test.camera, 1.0)
			effects.emitted.clear()
			effects.present(actors, clock, "fighting", true, test.camera, 0.0)
			check(effects.emitted == actual, "CPU geometry does not depend on the previous presentation call: " + id)
		check(saw_primary and saw_accent, "both declared actor colors occur in real emitted vertices: " + id)
	check(observed_styles == EXPECTED_STYLES and observed_styles.size() == 13, "all six heroes, six pets and guardian styles exercised")
	for role: String in ROLES:
		var default_id: String = {"hero": "hero_ranger", "pet": "pet_deer", "boss": "boss_ancient_guardian"}[role]
		for unknown: String in ["", "unknown-id", "hero/alias", "../not-a-path", "pet_dragon" if role != "pet" else "hero_mage"]:
			check(_effects.skill_for(unknown, role) == _effects.skill_for(default_id, role),
				"unknown/cross-role style uses bounded role-native fallback: " + role)
	var authority: Dictionary = actors.duplicate(true)
	for absent: String in ROLES:
		var partial: Dictionary = actors.duplicate()
		partial.erase(absent)
		effects.present(partial, 0.65, "fighting", true, test.camera, 0.0)
		check(not effects.debug_state().activeRoles.has(absent), "missing actor cannot retain its old skill: " + absent)
	check(actors == authority, "style selection and partial asset availability do not mutate the actor dictionary")
	test.world.free()

func test_caller_gates() -> void:
	var test := fixture()
	var scene: Node3D = test.scene
	var effects := effects_of(scene)
	check(effects != null, "renderer owns the confirmed VFX module")
	if effects == null:
		test.world.free()
		return
	for mesh: MeshInstance3D in pool_of(effects):
		mesh.mesh.changed.connect(mesh_changed)
	for gate_case: Array in [["paused", 0.65], ["local_pause", 0.65], ["stale", 0.65], ["hidden", 0.65], ["parent_hidden", 0.65],
		["paused", 10.9], ["local_pause", 10.9], ["stale", 10.9], ["hidden", 10.9], ["parent_hidden", 10.9],
		["paused", 16.1], ["local_pause", 16.1], ["stale", 16.1], ["hidden", 16.1], ["parent_hidden", 16.1]]:
		var gate: String = gate_case[0]
		check(scene.apply_snapshot(snapshot()), "fresh state before " + gate)
		scene.set_animation_paused(false)
		scene.visible = true
		test.world.visible = true
		scene._motion_clock = gate_case[1]
		step(scene, 0.0)
		match gate:
			"paused":
				scene.apply_snapshot(snapshot("paused"))
			"local_pause":
				scene.set_animation_paused(true)
			"stale":
				scene._received_msec = Time.get_ticks_msec() - 16000
			"hidden":
				scene.visible = false
			"parent_hidden":
				test.world.visible = false
		# Let a hide/freeze transition settle, then ensure it stays frozen.
		step(scene, 0.0)
		var phase: float = scene._motion_clock
		var appearance := pool_view(effects)
		var diagnostic: Dictionary = effects.debug_state()
		var identity := pool_identity(effects)
		var state: Dictionary = scene._snapshot.duplicate(true)
		_mesh_changes = 0
		for index in range(12):
			step(scene)
		check(is_equal_approx(scene._motion_clock, phase) and pool_view(effects) == appearance and effects.debug_state() == diagnostic,
			"caller gate cannot advance skill/ultimate phase or geometry: %s at %.2f" % [gate, gate_case[1]])
		check(pool_identity(effects) == identity and scene._snapshot == state, "gate retains pool and confirmed state: " + gate)
		check(_mesh_changes == 0, "frozen caller does not silently rebuild identical mesh geometry: " + gate)
		check(is_equal_approx(scene._last_shared_clock, _clock), "frozen caller still consumes shared-clock samples: " + gate)
		if gate in ["hidden", "parent_hidden"]:
			check(not hud_of(scene).visible, "Node3D visibility gate explicitly hides its independent CanvasLayer: " + gate)
		scene.visible = true
		test.world.visible = true
		scene.set_animation_paused(false)
		if gate in ["hidden", "parent_hidden"]:
			step(scene, 0.0)
			check(is_equal_approx(scene._motion_clock, phase) and hud_of(scene).visible,
				"show resumes HUD at the same phase without catching up hidden time: " + gate)
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete"]:
		check(scene.apply_snapshot(snapshot(mode)), "noncombat renderer state accepted: " + mode)
		for index in range(4):
			step(scene)
		check(pool_hidden(effects), "renderer hides skills outside fighting/demo: " + mode)
	var demo := snapshot("demo")
	demo.elapsed = 0.0
	demo.duration = 0.0
	demo.roundId = ""
	check(scene.apply_snapshot(demo), "explicit demo has no authoritative round or duration")
	scene._motion_clock = 10.6
	scene._received_msec = Time.get_ticks_msec() - 16000
	var demo_state: Dictionary = scene._snapshot.duplicate(true)
	var demo_clock: float = scene._motion_clock
	var seen_active := false
	for index in range(60):
		step(scene)
		seen_active = seen_active or not pool_hidden(effects)
	check(scene._motion_clock != demo_clock and seen_active, "explicit demo can animate skills even without fresh authority")
	check(scene._snapshot == demo_state and scene.get_presentation_status().mode == "demo", "demo never creates or completes a credited round")
	var hud := hud_of(scene)
	check(hud != null and hud.debug_state().visible and not hud.debug_state().labels.has("DEMO")
		and not hud.debug_state().text.contains("DEMO"), "legacy transport mode does not add a user-visible demo label")
	test.world.free()

func check_bottom_hud_layout(state: Dictionary, viewport: Vector2, caption_clearance: float) -> void:
	# Independent user-facing layout contract, not a copy of the HUD's layout
	# implementation. Coordinates stay in the caller's viewport domain; there
	# is no extra DPR multiplier and these headless checks are not QHD captures.
	var plate: Rect2 = state.rect
	check(state.visible and Rect2(Vector2.ZERO, viewport).encloses(plate)
		and not plate.intersects(state.controls_rect),
		"fixed bottom Boss bar stays inside the viewport and clear of existing controls: " + str(viewport))
	check(absf(plate.get_center().x - viewport.x * 0.5) <= 1.0,
		"fixed bottom Boss bar is horizontally centered, not head-anchored: " + str(viewport))
	# Cases explicitly include the real 1280x800 -> 2304x1440 world stretch:
	# 50 logical pixels become 90px. Small screens keep 48px, not a tiny
	# proportional gap. The whole plate must end at this fixed caption boundary.
	var caption := Rect2(0.0, viewport.y - caption_clearance, viewport.x, caption_clearance)
	check(absf(plate.end.y - caption.position.y) <= 1.0 and not plate.intersects(caption),
		"entire Boss plate sits at the exact fixed bottom inset without covering caption: " + str(viewport))
	# Width means the accepted 16:10 WORLD, excluding letterboxes. The user's
	# approximate QHD pixel target is not a 1400px hard cap, and compact mobile
	# layouts must not be incorrectly required to occupy 80 percent of canvas.
	var world_width := minf(viewport.x, viewport.y * 1.6)
	check(plate.size.x >= world_width * 0.65 - 1.0 and plate.size.x <= world_width * 0.70 + 1.0,
		"long bar spans 65-70 percent of the visible world across canvas aspect ratios: " + str(viewport))
	check(plate.position.x >= 4.0 and plate.end.x <= viewport.x - 4.0,
		"narrow and wide viewports retain side clearance")
	check(plate.encloses(state.bar_rect) and state.bar_rect.size.x > 0.0 and state.bar_rect.size.y > 0.0,
		"visible HP track remains nonempty and completely inside its fixed plate")

func test_hud_contract() -> void:
	var code: Script = load("res://camp_presentation/camp_boss_hud.gd")
	check(code != null and code.can_instantiate(), "actual HUD script loads without renderer or private data")
	if code == null or not code.can_instantiate():
		return
	var hud: CanvasLayer = code.new()
	_tree.root.add_child(hud)
	check(hud.get_child_count() == 3 and not hud.is_processing() and not hud.is_physics_processing(),
		"HUD owns exactly the Boss bar, caster bubble and damage number, with no autonomous timer/process")
	var panel: Control = hud.get_child(0)
	var panel_id := panel.get_instance_id()
	var ultimate: Control = hud.get_child(1)
	var ultimate_id := ultimate.get_instance_id()
	var damage: Control = hud.get_child(2)
	var damage_id := damage.get_instance_id()
	check(panel.name == "BossBar" and ultimate.has_method("present") and not ultimate.visible
		and ultimate.mouse_filter == Control.MOUSE_FILTER_IGNORE and ultimate.focus_mode == Control.FOCUS_NONE,
		"second HUD child is the initially hidden noninteractive caster bubble")
	check(damage.mouse_filter == Control.MOUSE_FILTER_IGNORE and damage.focus_mode == Control.FOCUS_NONE,
		"damage numbers never intercept world controls")
	check(panel.mouse_filter == Control.MOUSE_FILTER_IGNORE and panel.focus_mode == Control.FOCUS_NONE,
		"Boss bar cannot intercept input or steal focus from the world")
	for sample: Array in [[Vector2(1280, 800), 50.0], [Vector2(2560, 1440), 90.0],
		[Vector2(2304, 1440), 90.0], [Vector2(3440, 1440), 90.0], [Vector2(390, 844), 53.0],
		[Vector2(320, 200), 48.0], [Vector2(320, 568), 48.0], [Vector2(768, 480), 48.0]]:
		var viewport: Vector2 = sample[0]
		var caption_clearance: float = sample[1]
		var anchor := viewport * Vector2(0.5, 0.55)
		for remaining: float in [1.0, 0.5, 0.0001, 0.0]:
			hud.present("fighting", remaining, anchor, viewport, true, false, false, 0.0)
			var state: Dictionary = hud.debug_state()
			check(state.visible and is_equal_approx(state.ratio, remaining) and state.percent == ceili(remaining * 100.0),
				"confirmed ratio stays exact; percentage is diagnostic only")
			check(not state.text.contains("%"), "the visible Boss bar no longer prints a percentage")
			check_bottom_hud_layout(state, viewport, caption_clearance)
		hud.present("fighting", 0.5, anchor, viewport, true, false, false, 0.0)
		var fixed_plate: Rect2 = hud.debug_state().rect
		for moved_anchor: Vector2 in [Vector2.ZERO, viewport, viewport * Vector2(0.1, 0.95), Vector2(-100, -100)]:
			hud.present("fighting", 0.5, moved_anchor, viewport, true, false, false, 0.0)
			check(hud.debug_state().visible and hud.debug_state().rect == fixed_plate,
				"finite head-anchor motion cannot move or hide the bottom-fixed Boss bar: " + str(viewport))
		for flags: Array in [[false, false], [false, true], [true, false], [true, true]]:
			hud.present("fighting", 0.5, anchor, viewport, true, flags[0], flags[1], 0.0)
			var state: Dictionary = hud.debug_state()
			check_bottom_hud_layout(state, viewport, caption_clearance)
			check(absf(state.rect.end.y - fixed_plate.end.y) <= 1.0,
				"SYNC/PAUSED wrapping retains the same bottom edge and caption clearance")
			hud.present_ultimate("WIND REQUIEM", "CHARGE", true, viewport)
			var ultimate_state: Dictionary = hud.debug_state().ultimate
			check(not ultimate_state.visible or (Rect2(Vector2.ZERO, viewport).encloses(ultimate_state.rect)
				and not ultimate_state.rect.intersects(hud.debug_state().rect)),
				"legacy ultimate call never resurrects a screen-centred banner")
			hud.present_ultimate("", "", false, viewport)
	for tiny: Vector2 in [Vector2.ZERO, Vector2(100, 100), Vector2(320, 40), Vector2(-320, 200), Vector2(NAN, 800)]:
		hud.present("fighting", 0.5, Vector2.ZERO, tiny, true, false, false, 0.0)
		check(not hud.debug_state().visible and not panel.visible,
			"invalid or unreadably narrow viewport hides the bar instead of overflowing: " + str(tiny))
	var anchor := Vector2(640, 440)
	var viewport := Vector2(1280, 800)
	hud.present("demo", 0.8, anchor, viewport, true, false, false, 0.0)
	check(hud.debug_state().visible and not hud.debug_state().labels.has("DEMO") and not hud.debug_state().text.contains("DEMO"),
		"legacy mode retains its HUD without the superseded visible demo label")
	hud.present("fighting", 0.8, anchor, viewport, true, false, false, 0.0)
	hud.present("fighting", 0.5, anchor, viewport, true, false, false, 0.0)
	var trail_before: Dictionary = hud.debug_state()
	for index in range(12):
		hud.present("fighting", 0.5, anchor, viewport, true, false, false, 0.0)
	check(hud.debug_state() == trail_before, "zero-delta refresh never advances the cosmetic trail")
	for gate: String in ["paused", "stale"]:
		hud.present("paused" if gate == "paused" else "fighting", 0.5, anchor, viewport, true, gate == "stale", gate == "paused", 0.0)
		var held: Dictionary = hud.debug_state()
		for index in range(12):
			hud.present("paused" if gate == "paused" else "fighting", 0.5, anchor, viewport, true, gate == "stale", gate == "paused", 0.1)
		check(hud.debug_state().trail_ratio == held.trail_ratio and hud.debug_state().trail_delay == held.trail_delay,
			"cosmetic trail cannot advance through " + gate)
		check(hud.debug_state().labels.has("PAUSED" if gate == "paused" else "SYNC"), "HUD truthfully labels " + gate)
	for index in range(12):
		hud.present("fighting", 0.5, anchor, viewport, true, false, false, 0.1)
	check(hud.debug_state().ratio == 0.5 and hud.debug_state().trail_ratio == 0.5,
		"explicit positive presentation steps settle only the trail, never the supplied HP")
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete"]:
		hud.present(mode, 0.5, anchor, viewport, true, false, false, 0.1)
		check(not hud.debug_state().visible, "noncombat HUD stays hidden: " + mode)
	hud.present("fighting", 0.5, anchor, viewport, false, false, false, 0.1)
	check(not hud.debug_state().visible, "absent or occluded Boss has no floating health bar")
	check(hud.get_child_count() == 3 and panel.get_instance_id() == panel_id and panel.get_child_count() == 0
		and ultimate.get_instance_id() == ultimate_id and ultimate.get_child_count() == 0
		and damage.get_instance_id() == damage_id and damage.get_child_count() == 0,
		"all ratios, modes and layouts reuse the three draw-only controls")
	hud.free()
	check(not is_instance_valid(panel), "HUD teardown frees its draw control")
	check(not is_instance_valid(ultimate) and not is_instance_valid(damage), "HUD teardown frees both popups without orphan controls")

func test_swap_and_late_assets() -> void:
	var descriptors: Dictionary = _catalogue.duplicate(true)
	var alternative: Dictionary = descriptors.assets[0].duplicate(true)
	# Different confirmed skill profile makes a stale old effect observable.
	# Reuses only fixture pixels, never the original Mage PNG or actor shard.
	alternative.id = "hero_mage"
	descriptors.assets.append(alternative)
	var test := fixture(descriptors)
	var scene: Node3D = test.scene
	var effects := effects_of(scene)
	if effects == null:
		check(false, "swap test requires the real VFX module")
		test.world.free()
		return
	var identity := pool_identity(effects)
	scene._motion_clock = 0.65
	step(scene, 0.0)
	var previous_root: Node3D = scene._actors.hero.root
	var selected := snapshot("paused")
	selected.heroAssetId = alternative.id
	check(scene.apply_snapshot(selected), "outfit swap accepted during pause")
	check(not is_instance_valid(previous_root) and scene._actors.hero.id == alternative.id,
		"old actor is actually freed; new selected actor replaces it")
	var changed_effect: Dictionary = effects.debug_state()
	check(pool_identity(effects) == identity and (not changed_effect.activeRoles.has("hero")
		or changed_effect.styles.get("hero") == "ember_orb"),
		"outfit change removes old wind skill; only hidden or current frozen Mage effect is permitted")
	var changed_view := pool_view(effects)
	var generation: int = scene._generation
	var received: int = scene._received_msec
	var phase: float = scene._motion_clock
	var state: Dictionary = scene._snapshot.duplicate(true)
	check(scene.assets_available(["hero-test"]), "obsolete already-mounted asset notification is safely accepted")
	check(scene._generation == generation and scene._received_msec == received and scene._motion_clock == phase
		and scene._snapshot == state and scene._actors.hero.id == alternative.id,
		"late old asset cannot revive old actor, replay state, refresh age or advance skills")
	check(effects.debug_state() == changed_effect and pool_view(effects) == changed_view and pool_identity(effects) == identity,
		"late old asset cannot revive old effects or redraw the current frozen skill")
	# Simulate CURRENT asset arriving after its actor was absent, using only the
	# already mounted synthetic fixture. No real source art or pack is written.
	scene._actors.hero.root.free()
	scene._actors.erase("hero")
	check(scene.assets_available([alternative.id]), "current missing actor can appear on asset availability")
	check(scene._actors.has("hero") and scene._actors.hero.id == alternative.id,
		"only the current selection materializes")
	check(scene._received_msec == received and scene._motion_clock == phase and scene._snapshot == state,
		"current late asset cannot resume a paused round or refresh authority")
	var arrived_effect: Dictionary = effects.debug_state()
	check(pool_identity(effects) == identity and (not arrived_effect.activeRoles.has("hero")
		or arrived_effect.styles.get("hero") == "ember_orb"), "current late asset cannot inherit the removed actor's skill")
	var slots := pool_of(effects)
	test.world.free()
	check(not is_instance_valid(effects), "world teardown frees the presentation-owned effect module")
	for mesh: Variant in slots:
		check(not is_instance_valid(mesh), "world teardown frees each pooled node, without orphan emitters")

func run(tree: SceneTree, presentation_script: Script, catalogue: Dictionary, assertion: Callable) -> void:
	_tree = tree
	_assertion = assertion
	_presentation = presentation_script
	_catalogue = catalogue
	check(FileAccess.file_exists(EFFECTS_PATH), "test PCK includes the production VFX script")
	if not FileAccess.file_exists(EFFECTS_PATH):
		return
	_effects = load(EFFECTS_PATH)
	check(_effects != null and _effects.can_instantiate(), "VFX script parses in isolated headless Godot")
	if _effects == null or not _effects.can_instantiate():
		return
	var prior_size: Vector2i = tree.root.size
	tree.root.size = Vector2i(1280, 800)
	test_fixed_pool()
	test_styles_and_cpu_vertices()
	test_ultimate_timeline_and_geometry()
	test_confirmed_hp()
	test_real_hp_and_confirmed_death()
	test_death_gates_and_spectator_cycle()
	test_defeat_cpu_geometry()
	test_hud_contract()
	test_caller_gates()
	test_ultimate_round_and_pose()
	test_swap_and_late_assets()
	await tree.process_frame
	tree.root.size = prior_size
	print("CAMP_COMBAT_GEOMETRY: peak simultaneous vertices=%d; pool=3; headless CPU emission, not GPU timing" % _peak_vertices)

func run_effects_only(tree: SceneTree, assertion: Callable) -> void:
	_tree = tree
	_assertion = assertion
	_effects = load(EFFECTS_PATH)
	check(_effects != null and _effects.can_instantiate(), "standalone VFX script parses")
	if _effects == null or not _effects.can_instantiate():
		return
	test_fixed_pool()
	test_styles_and_cpu_vertices()
	test_ultimate_timeline_and_geometry()
	await tree.process_frame
	print("CAMP_COMBAT_GEOMETRY: peak simultaneous vertices=%d; pool=3; headless CPU emission, not GPU timing" % _peak_vertices)

func run_hud_only(tree: SceneTree, assertion: Callable) -> void:
	_tree = tree
	_assertion = assertion
	test_hud_contract()
	await tree.process_frame
