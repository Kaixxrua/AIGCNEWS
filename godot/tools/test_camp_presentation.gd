extends SceneTree
## Tiny isolated native test. Synthetic frame data is TEST-only, never final art.
var failures := 0
var checks := 0
var test_clock := 0.0

class TestWeather:
	extends Node
	var night_blend: Variant = 0.0

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("CAMP_TEST_FAIL: " + label)

func ground(point: Vector2) -> Vector3:
	return Vector3(point.x, point.x * 0.025 + point.y * 0.018, point.y)

func permitted(_point: Vector2) -> bool:
	return true

func denied(_point: Vector2) -> bool:
	return false

func clock_value() -> float:
	return test_clock

func arrive_before_pose_sampling(scene: Node3D) -> void:
	# Pose-table tests may set clocks explicitly only after actual relocation.
	# Never clear routes or move roots directly to manufacture an arrival.
	for _index in range(400):
		if not scene._travel_active:
			break
		test_clock += 0.05
		scene._process(0.05)
	check(not scene._travel_active and not scene._travel_blocked, "actual safe relocation completes before isolated pose sampling")
	scene._process(0.0)

func snapshot(mode: String = "fighting") -> Dictionary:
	return {"mode": mode, "heroAssetId": "hero-test", "petAssetId": "pet-test", "bossAssetId": "boss-test",
		"elapsed": 12.0, "duration": 600.0, "roundId": "public-round-01"}

static func assert_packed_sources(source_directory: String, assertion: Callable) -> void:
	# Every runtime module is a regeneration input. Comparing only the renderer
	# would miss an old VFX priority or HUD inside an otherwise newly pinned PCK.
	for name: String in ["camp_presentation.gd", "camp_combat_effects.gd", "camp_boss_hud.gd", "camp_spawn_layout.gd", "camp_travel_path.gd"]:
		var source_path := source_directory.path_join(name)
		var packed_path := "res://camp_presentation/" + name
		var available := FileAccess.file_exists(source_path) and FileAccess.file_exists(packed_path)
		var matches := false
		if available:
			var source: PackedByteArray = FileAccess.get_file_as_bytes(source_path)
			matches = not source.is_empty() and source == FileAccess.get_file_as_bytes(packed_path)
		assertion.call(available and matches, "mounted regeneration input matches exact current source bytes: " + name)

static func cutout_top(image: Image) -> int:
	# Independent byte-level oracle: alpha 1..31 remains in the source texture
	# but is not part of the visible Sprite3D silhouette. Do not use get_used_rect.
	var pixels: PackedByteArray = image.get_data()
	var width := image.get_width()
	for y in range(image.get_height()):
		for x in range(width):
			if pixels[(y * width + x) * 4 + 3] >= 32:
				return y
	return image.get_height()

static func assert_actor_heads(scene: Node3D, assertion: Callable) -> void:
	for role: String in scene._actors:
		var actor: Dictionary = scene._actors[role]
		var complete: bool = actor.has("heads") and actor.heads.size() == 32
		assertion.call(complete, role + " caches exactly 32 visible-art head heights")
		if not complete:
			continue
		var spec: Dictionary = scene._catalogue[actor.id]
		for index in range(32):
			var image: Image = actor.frames[index].get_image()
			var anchor: Array = spec.frameAnchors[index] if spec.has("frameAnchors") else spec.anchor
			var expected: float = maxf(0.0, float(anchor[1]) - cutout_top(image)) * actor.sprite.pixel_size
			assertion.call(is_equal_approx(actor.heads[index], expected),
				"%s head frame %d matches alpha>=32 before mips: expected %.6fm, got %.6fm" % [role, index, expected, actor.heads[index]])

func test_public_hp_schema(code: Script, world: Node3D, catalogue: Dictionary) -> void:
	var scene: Node3D = code.new()
	world.add_child(scene)
	check(scene.setup(world, catalogue, ground, permitted), "paired public HP schema setup")
	scene.set_process(false)
	var extended := snapshot()
	extended.bossHp = 725
	extended.bossMaxHp = 1000
	for mode: String in ["demo", "fighting", "paused", "cooldown", "daily_complete", "waiting", "unavailable", "defeated"]:
		var legacy := snapshot(mode)
		check(scene.validate_snapshot(legacy) == (mode != "defeated"), "exact seven-key legacy compatibility: " + mode)
		var state: Dictionary = extended.duplicate(true)
		state.mode = mode
		state.bossHp = 0 if mode == "defeated" else 725
		check(scene.validate_snapshot(state), "exact nine-key public HP accepted: " + mode)
	for pair: Array in [[0, 1], [1, 1], [0, 1000000000], [1000000000, 1000000000], [725.0, 1000.0]]:
		var state: Dictionary = extended.duplicate(true)
		state.bossHp = pair[0]
		state.bossMaxHp = pair[1]
		check(scene.validate_snapshot(state), "integer HP range includes zero and 1e9, including JSON number representation")
		var decoded: Variant = JSON.parse_string(JSON.stringify(state))
		check(scene.validate_snapshot(decoded), "real JSON roundtrip preserves the public integer HP pair")
	check(scene.apply_snapshot(extended), "valid HP state becomes the last confirmed snapshot")
	var prior: Dictionary = scene._snapshot.duplicate(true)
	var stamp: int = scene._received_msec
	var generation: int = scene._generation
	var invalid: Array[Dictionary] = []
	for key: String in ["bossHp", "bossMaxHp"]:
		var unpaired: Dictionary = extended.duplicate(true)
		unpaired.erase(key)
		invalid.append(unpaired)
		for value: Variant in [null, true, false, "0", 0.5, -1, 1000000001, NAN, INF, -INF, [], {}]:
			var state: Dictionary = extended.duplicate(true)
			state[key] = value
			invalid.append(state)
	for change: Dictionary in [{"bossHp": 1001}, {"bossHp": 0, "bossMaxHp": 0},
		{"mode": "defeated"}, {"mode": "defeated", "bossHp": 0, "roundId": ""}]:
		var state: Dictionary = extended.duplicate(true)
		state.merge(change, true)
		invalid.append(state)
	for key: String in ["authToken", "accountId", "reward", "rewards", "claim", "vip", "damage", "skillDamage",
		"heroHp", "petHp", "hp", "maxHp", "health", "bossHP", "url"]:
		var state: Dictionary = extended.duplicate(true)
		state[key] = "forbidden-test-only"
		invalid.append(state)
	for role: String in ["hero", "pet", "boss"]:
		for id: String in ["", "not-registered"]:
			var state: Dictionary = extended.duplicate(true)
			state.mode = "defeated"
			state.bossHp = 0
			state[role + "AssetId"] = id
			invalid.append(state)
	for state: Dictionary in invalid:
		check(not scene.validate_snapshot(state) and not scene.apply_snapshot(state), "malformed HP/defeat/private input rejected: " + str(state.keys()))
		check(scene._snapshot == prior and scene._received_msec == stamp and scene._generation == generation,
			"rejection cannot mutate display, refresh age or replace pending generation")
	var defeated: Dictionary = extended.duplicate(true)
	defeated.mode = "defeated"
	defeated.bossHp = 0
	defeated.elapsed = 0.0
	defeated.duration = 0.0
	check(scene.validate_snapshot(defeated), "explicit defeat has no inferred minimum timer or legacy 600-second threshold")
	check(scene.apply_snapshot(snapshot()), "exact legacy state still works after a nine-key state")
	check(scene._snapshot.size() == 7 and not scene._snapshot.has("bossHp") and not scene._snapshot.has("bossMaxHp"),
		"legacy update never inherits stale HP extension fields")
	scene.free()

static func exact_presentation_children(scene: Node3D, roles: Array) -> bool:
	# HUD/VFX are presentation-owned, not extra actors or new world children.
	# Keep an exact allowlist: neither a relaxed count nor hidden stand-in art.
	if scene._actors.size() != roles.size() or scene.get_child_count() != roles.size() + 2:
		return false
	var actor_roots: Array = []
	for role: String in roles:
		if not scene._actors.has(role):
			return false
		var actor: Dictionary = scene._actors[role]
		if not is_instance_valid(actor.root) or actor.root.get_parent() != scene \
			or not actor.sprite is Sprite3D or actor.sprite.get_parent() != actor.root:
			return false
		actor_roots.append(actor.root)
	var effects := 0
	var hud := 0
	for child: Node in scene.get_children():
		if child in actor_roots:
			continue
		var script: Script = child.get_script()
		if child is Node3D and script != null and script.resource_path.get_file() == "camp_combat_effects.gd" \
			and child.has_method("present") and child.has_method("debug_state"):
			effects += 1
		elif child is CanvasLayer and child.has_method("debug_state"):
			hud += 1
		else:
			return false
	return effects == 1 and hud == 1

func test_actor_moon_fill(code: Script, catalogue: Dictionary) -> void:
	var world := Node3D.new()
	root.add_child(world)
	var weather := TestWeather.new()
	weather.name = "LivingWeather"
	world.add_child(weather)
	var world_light := DirectionalLight3D.new()
	world_light.light_energy = 1.2
	world_light.light_color = Color(0.65, 0.79, 1.0)
	world_light.rotation_degrees = Vector3(-28, -145, 0)
	world.add_child(world_light)
	var world_light_state := [world_light.transform, world_light.light_color, world_light.light_energy, world_light.light_cull_mask]
	var descriptors: Dictionary = catalogue.duplicate(true)
	var alternative: Dictionary = descriptors.assets[0].duplicate(true)
	alternative.id = "hero-moon-second"
	descriptors.assets.append(alternative)
	var scene: Node3D = code.new()
	world.add_child(scene)
	check(scene.setup(world, descriptors, ground, permitted), "moon fill reads the current scene's existing LivingWeather")
	scene.set_process(false)
	scene.set_animation_paused(true)
	check(scene.apply_snapshot(snapshot("daily_complete")), "night compensation supports daily-complete idle")
	var saved: Dictionary = {}
	for role: String in scene._actors:
		var actor: Dictionary = scene._actors[role]
		var fill: OmniLight3D = actor.moon_fill
		saved[role] = {"root": actor.root.transform, "sprite": actor.sprite.transform, "offset": actor.sprite.offset,
			"texture": actor.sprite.texture, "shadow": actor.shadow.transform, "material": actor.shadow.material_override,
			"alpha": actor.sprite.texture.get_image().get_data()}
		var layer: int = {"hero": 1 << 17, "pet": 1 << 18, "boss": 1 << 19}[role]
		check(actor.sprite.layers == (1 | layer) and fill.light_cull_mask == layer,
			"actor retains original layer1 and receives only its role fill: " + role)
		for accepted_layers in [1, 2, 4, 8, 32, 1 | 32, 1 | 8]:
			check((fill.light_cull_mask & accepted_layers) == 0,
				"fill excludes accepted world/water/fauna/focus/grass/building layers: " + role)
		for other_role: String in scene._actors:
			check(bool(fill.light_cull_mask & scene._actors[other_role].sprite.layers) == (other_role == role),
				"moon fill cannot double-light a neighbouring actor: " + role + "/" + other_role)
		check(actor.shadow.layers == 1 and (fill.light_cull_mask & actor.shadow.layers) == 0,
			"ground contact shadow never receives actor compensation: " + role)
		check(fill.get_parent() == actor.root and fill.position.is_equal_approx(Vector3(-3, maxf(4.0, actor.heads.max() + 0.8), 6))
			and is_equal_approx(fill.omni_range, 16.0) and is_equal_approx(fill.omni_attenuation, 0.75),
			"soft upper/front-left real light follows actor, not world: " + role)
		check(fill.light_color.is_equal_approx(Color(0.63, 0.75, 0.95)) and fill.light_specular == 0.0
			and fill.light_indirect_energy == 0.0 and fill.light_volumetric_fog_energy == 0.0
			and fill.light_bake_mode == Light3D.BAKE_DISABLED and not fill.shadow_enabled,
			"restrained cool diffuse only; no GI/fog/specular/shadow side effects: " + role)
	var phase: float = scene._motion_clock
	for blend in [0.0, 0.25, 0.5, 1.0, 0.5, 0.0]:
		weather.night_blend = blend
		scene._process(0.1)
		for role: String in scene._actors:
			var actor: Dictionary = scene._actors[role]
			check(is_equal_approx(actor.moon_fill.light_energy, 8.0 * blend)
				and actor.moon_fill.visible == (blend > 0), "GPU-calibrated 0/4/8 blend ramp and zero day: " + role)
			check(actor.sprite.shaded and actor.sprite.material_override == null
				and actor.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD
				and is_equal_approx(actor.sprite.alpha_scissor_threshold, 32.0 / 255.0),
				"normal shaded cutout material retained; no emission or outline: " + role)
			check(actor.sprite.texture == saved[role].texture
				and actor.sprite.texture.get_image().get_data() == saved[role].alpha,
				"day/night never mutates frame pixels or source art: " + role)
			check(actor.root.transform == saved[role].root and actor.sprite.transform == saved[role].sprite
				and actor.sprite.offset == saved[role].offset and actor.shadow.transform == saved[role].shadow
				and actor.shadow.material_override == saved[role].material,
				"lighting cannot alter station, scale, anchors or ground contact: " + role)
		check(is_equal_approx(scene._motion_clock, phase) and weather.night_blend == blend,
			"paused idle still follows weather without advancing display clock or writing blend")
		check([world_light.transform, world_light.light_color, world_light.light_energy, world_light.light_cull_mask] == world_light_state
			and world.get_child_count() == 3 and exact_presentation_children(scene, ["hero", "pet", "boss"]),
			"no world light mutations or extra world children; only three actors plus one FX and HUD")
	scene.set_animation_paused(false)
	for mode: String in ["paused", "fighting", "waiting", "unavailable"]:
		scene.apply_snapshot(snapshot(mode))
		if mode == "fighting":
			scene._received_msec = Time.get_ticks_msec() - 16000
		phase = scene._motion_clock
		for blend in [1.0, 0.0]:
			weather.night_blend = blend
			scene._process(0.1)
			check(is_equal_approx(scene._motion_clock, phase), "night sync cannot bypass pause/stale/hidden pose gate: " + mode)
			for actor: Dictionary in scene._actors.values():
				check(is_equal_approx(actor.moon_fill.light_energy, 8.0 * blend), "weather updates before paused/stale/hidden gate: " + mode)
				if mode in ["waiting", "unavailable"]:
					check(not actor.moon_fill.is_visible_in_tree() and not actor.sprite.is_visible_in_tree(),
						"hidden authority state hides the fill with its actor: " + mode)
	# Late assets/outfit changes must start at current night, not wait for motion.
	weather.night_blend = 1.0
	var state := snapshot("daily_complete")
	state.heroAssetId = alternative.id
	var removed_fill: OmniLight3D = scene._actors.hero.moon_fill
	check(scene.apply_snapshot(state) and not is_instance_valid(removed_fill), "actor swap frees its old isolated fill")
	check(is_equal_approx(scene._actors.hero.moon_fill.light_energy, 8.0)
		and scene._actors.hero.moon_fill.is_visible_in_tree(), "late selected actor begins with current night compensation")
	for bad: Variant in [null, true, "1", NAN, INF, -0.01, 1.01]:
		weather.night_blend = bad
		scene._process(0.0)
		check(scene._night_factor() == 0.0 and scene._actors.hero.moon_fill.light_energy == 0.0
			and not scene._actors.hero.moon_fill.visible, "malformed weather fails to unchanged daytime, never unbounded energy")
	weather.free()
	scene._process(0.0)
	check(scene._actors.hero.moon_fill.light_energy == 0.0, "freed optional weather safely removes compensation")
	world.free()

func test_portrait_frames(code: Script, world: Node3D, catalogue: Dictionary) -> void:
	# 1024x1536 / 4x8 is a PHYSICAL layout. Each logical action still owns eight
	# explicit slots, spanning two physical rows. Test both normal and permuted
	# rectangles using newly generated TEST-only pixels, not edited public art.
	for permuted in [false, true]:
		var descriptors: Dictionary = catalogue.duplicate(true)
		var spec: Dictionary = {}
		for candidate: Dictionary in descriptors.assets:
			if candidate.id == "pet_dragon":
				spec = candidate
		check(not spec.is_empty(), "dedicated portrait test descriptor exists")
		if spec.is_empty():
			return
		check(spec.frameSize.size() == 2 and spec.frameSize[0] == 256 and spec.frameSize[1] == 192 \
			and spec.frameRects.size() == 32, "explicit 256x192 non-square frame contract")
		check(Vector2(spec.frameRects[4][0], spec.frameRects[4][1]) == Vector2(0, 192) \
			and Vector2(spec.frameRects[31][0], spec.frameRects[31][1]) == Vector2(768, 1344),
			"four physical columns, eight physical rows; not guessed eight columns")
		var original: Array = spec.frameRects.duplicate(true)
		if permuted:
			for index in range(32):
				spec.frameRects[index] = original[(index * 7 + 3) % 32]
		var source := Image.new()
		check(source.load_png_from_buffer(FileAccess.get_file_as_bytes(spec.atlas)) == OK \
			and source.get_size() == Vector2i(1024, 1536), "native PNG dimensions are portrait, unchanged")
		var scene: Node3D = code.new()
		world.add_child(scene)
		check(scene.setup(world, descriptors, ground, permitted), "mixed square and portrait actor setup")
		scene.set_process(false)
		var state := snapshot("cooldown")
		state.petAssetId = "pet_dragon"
		check(scene.apply_snapshot(state) and scene._actors.has("pet"), "portrait dragon materializes via normal snapshot path")
		if not scene._actors.has("pet"):
			scene.free()
			continue
		var actor: Dictionary = scene._actors.pet
		check(actor.frames.size() == 32 and actor.offsets.size() == 32, "all portrait frames and anchors decoded")
		check(is_equal_approx(actor.sprite.pixel_size, 2.2 * code._display_scale(spec) / 192.0), "display height divides frame HEIGHT 192, never width 256")
		check(actor.hovering and not actor.sprite.flip_h, "exact pet_dragon keeps its own hover and facing")
		check(scene._actors.hero.frames[0].get_size() == Vector2(32, 32) \
			and scene._actors.boss.frames[0].get_size() == Vector2(32, 32), "per-actor dimensions do not leak into other actors")
		for index in range(32):
			var physical: int = (index * 7 + 3) % 32 if permuted else index
			var frame: Image = actor.frames[index].get_image()
			check(frame.get_size() == Vector2i(256, 192) and frame.has_mipmaps(), "portrait frame dimensions and independent mips %d" % index)
			var expected := Color((40.0 + physical * 6.0) / 255.0, 80.0 / 255.0, 120.0 / 255.0, 254.0 / 255.0)
			check(frame.get_pixel(12, 12).is_equal_approx(expected), "explicit rectangle selects exact physical-cell pixels %d" % index)
			check(is_equal_approx(frame.get_pixel(0, 0).a, 31.0 / 255.0) \
				and frame.get_pixel(0, 0).a < actor.sprite.alpha_scissor_threshold, "portrait edge noise retained below cutout %d" % index)
			check(actor.offsets[index].is_equal_approx(Vector2(4 - index % 3, 84 - index % 4)),
				"per-frame anchor uses half-width128 / half-height96 %d" % index)
		for index in range(8):
			scene._motion_clock = (index + 0.25) / 5.0
			check(scene._update_actors() and actor.frame == index and actor.sprite.texture == actor.frames[index],
				"eight idle slots cross physical row boundary %d" % index)
			check(actor.sprite.offset == actor.offsets[index], "idle swaps matching portrait anchor %d" % index)
		state.mode = "fighting"
		check(scene.apply_snapshot(state), "portrait dragon enters display-only fighting mode")
		arrive_before_pose_sampling(scene)
		# Four complete ordinary cycles remain covered. Cycles 2/3 now belong to
		# the explicit ultimate reservation; the combat suite tests those poses.
		for cycle: int in [0, 1, 4, 5]:
			for half in range(2):
				var index: int = 8 + (7 + cycle * 2 + half) % 8
				scene._motion_clock = 1.5 + cycle * 5.2 + (0.05 if half == 0 else 0.20)
				check(scene._update_actors() and actor.frame == index and actor.sprite.texture == actor.frames[index],
					"eight walk/flap slots use explicit portrait rectangles %d" % index)
		for index in range(8):
			scene._motion_clock = 1.5 + 0.30 + (index + 0.5) * 0.65 / 8.0
			check(scene._update_actors() and actor.frame == 16 + index and actor.sprite.texture == actor.frames[16 + index],
				"explicit attack action remains separate from walk/flap %d" % index)
			check(actor.sprite.offset == actor.offsets[16 + index], "attack swaps matching portrait anchor %d" % index)
			var foot := ground(Vector2(actor.root.position.x, actor.root.position.z))
			check(actor.root.position.is_equal_approx(foot) and actor.shadow.global_position.is_equal_approx(foot + Vector3(0, 0.016, 0)) \
				and actor.sprite.position.y >= 1.19, "portrait frame/anchor changes preserve hover above grounded shadow %d" % index)
		scene.free()

func test_pet_hover(code: Script, world: Node3D, catalogue: Dictionary) -> void:
	# Reuse tiny TEST-only art via descriptors. No generated/public PNG is edited
	# or packed again, and no fixture can become delivered creature artwork.
	var flying_ids := ["pet_owl", "pet_finch", "pet_dragon"]
	var pet_ids := ["pet_deer", "pet_owl", "pet_fox", "pet_finch", "pet_rabbit", "pet_dragon",
		"pet/owl", "pet_dragon_variant", "pet-test"]
	var assets: Array = [catalogue.assets[0].duplicate(true), catalogue.assets[2].duplicate(true)]
	for id: String in pet_ids:
		var spec: Dictionary = catalogue.assets[1].duplicate(true)
		spec.id = id
		assets.append(spec)
	var scene: Node3D = code.new()
	world.add_child(scene)
	check(scene.setup(world, {"version": 1, "assets": assets}, ground, permitted, clock_value), "hover test public catalogue and real sloped sampler")
	scene.set_process(false)
	var world_transform := world.transform
	for id: String in pet_ids:
		var state := snapshot()
		state.petAssetId = id
		check(scene.apply_snapshot(state), "public pet selection " + id)
		arrive_before_pose_sampling(scene)
		var actor: Dictionary = scene._actors.pet
		var hovering: bool = id in flying_ids
		check(actor.hovering == hovering, "only exact three pet IDs hover: " + id)
		var station: Vector2 = scene._arena_center + (Vector2(-2.10, -3.20) if hovering else Vector2(-1.35, 2.10))
		check(actor.station.is_equal_approx(station), "exact flying IDs retain the rear local station at every respawn site: " + id)
		check(actor.direction.is_equal_approx(station.direction_to(scene._arena_center + Vector2(1.85, -0.65))) and is_equal_approx(actor.reach, 0.58),
			"flying station recalculates Boss-facing lunge without changing reach: " + id)
		check(scene._safe_segment(actor.station, actor.station + actor.direction * actor.reach, actor.radius),
			"entire selected station footprint and lunge/return stay safe: " + id)
		var opacity := float(actor.shadow.material_override.get_shader_parameter("contact_opacity"))
		check(is_equal_approx(opacity, 0.10 if hovering else 0.23), "only hovering pet shadow becomes lighter: " + id)
		var minimum := INF
		var maximum := -INF
		for index in range(27 if hovering else 3):
			scene._motion_clock = index * 0.2
			scene._locomotion_clock = scene._motion_clock
			check(scene._update_actors(), "pet choreography remains safe " + id)
			var point := Vector2(actor.root.position.x, actor.root.position.z)
			var sampled := ground(point)
			check(actor.root.position.is_equal_approx(sampled), "pet ROOT remains ground-sampled: " + id)
			check(actor.shadow.global_position.is_equal_approx(sampled + Vector3(0, 0.016, 0)) \
				and actor.shadow.quaternion != Quaternion.IDENTITY, "pet shadow remains on actual sloped ground: " + id)
			var lift: float = actor.sprite.position.y
			var expected := 1.25 + sin(scene._motion_clock * TAU / 2.6) * 0.06 if hovering else 0.0
			check(is_equal_approx(lift, expected) and lift >= (1.19 - 0.0001 if hovering else 0.0) \
				and lift <= (1.31 + 0.0001 if hovering else 0.0), "only sprite has bounded shoulder-height lift: " + id)
			minimum = minf(minimum, lift)
			maximum = maxf(maximum, lift)
		check(maximum - minimum > 0.10 if hovering else is_zero_approx(maximum), "hover bobs; ground pets never bob: " + id)
		for role: String in ["hero", "boss"]:
			var fixed: Vector2 = scene._arena_center + (Vector2(-2.35, 1.10) if role == "hero" else Vector2(1.85, -0.65))
			check(scene._actors[role].station.is_equal_approx(fixed), "flying pet keeps the same hero/Boss offsets within each respawn site: " + role)
			check(scene._actors[role].sprite.position.y == 0.0 \
				and is_equal_approx(float(scene._actors[role].shadow.material_override.get_shader_parameter("contact_opacity")), 0.23),
				"hover does not alter other actors or their shadows: " + role)
		check(world.transform == world_transform, "hover never moves the world")
		if not hovering:
			continue
		var before: Vector3 = actor.sprite.position
		var phase: float = scene._motion_clock
		state.mode = "paused"
		scene.apply_snapshot(state)
		test_clock += 0.1
		scene._process(0.1)
		check(actor.sprite.position == before and is_equal_approx(scene._motion_clock, phase), "server pause freezes hover and flap phase: " + id)
		state.mode = "fighting"
		scene.apply_snapshot(state)
		scene.set_animation_paused(true)
		test_clock += 0.1
		scene._process(0.1)
		check(actor.sprite.position == before and is_equal_approx(scene._motion_clock, phase), "local pause freezes hover and flap phase: " + id)
		scene.set_animation_paused(false)
		scene._received_msec = Time.get_ticks_msec() - 16000
		test_clock += 0.1
		scene._process(0.1)
		check(actor.sprite.position == before and scene._status == "stale", "stale server state freezes hover: " + id)
		for hidden_mode: String in ["unavailable", "waiting"]:
			state.mode = hidden_mode
			scene.apply_snapshot(state)
			check(not actor.sprite.is_visible_in_tree() and not actor.shadow.is_visible_in_tree(), "hidden mode hides hovering art AND ground shadow: " + id)
		state.mode = "demo"
		state.elapsed = 0.0
		state.duration = 0.0
		state.roundId = ""
		scene.apply_snapshot(state)
		check(actor.sprite.is_visible_in_tree() and actor.sprite.position.y >= 1.19, "public demo restores hover without authority fields: " + id)
	scene.free()
	# The ID check alone must not lift a non-pet descriptor.
	var wrong_role: Dictionary = catalogue.duplicate(true)
	wrong_role.assets[0].id = "pet_owl"
	scene = code.new()
	world.add_child(scene)
	check(scene.setup(world, wrong_role, ground, permitted), "exact ID role-guard test setup")
	var state := snapshot()
	state.heroAssetId = "pet_owl"
	check(scene.apply_snapshot(state) and not scene._actors.hero.hovering and scene._actors.hero.sprite.position.y == 0.0 \
		and scene._actors.hero.station.is_equal_approx(Vector2(2.65, -10.90)),
		"a matching name in a non-pet role remains grounded")
	scene.free()

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	var effects_only: bool = arguments.size() == 2 and arguments[1] == "--effects-only"
	var hud_only: bool = arguments.size() == 2 and arguments[1] == "--hud-only"
	check(arguments.size() == 1 or effects_only or hud_only, "fixture pack path and optional explicit component-only mode")
	if arguments.size() != 1 and not effects_only and not hud_only:
		quit(1)
		return
	check(ProjectSettings.load_resource_pack(arguments[0], false), "real optional PCK mount")
	if effects_only or hud_only:
		var effects_tests: Script = load(get_script().resource_path.get_base_dir().path_join("test_camp_combat_effects.gd"))
		check(effects_tests != null and effects_tests.can_instantiate(), "standalone VFX regression suite loads")
		if effects_tests != null and effects_tests.can_instantiate():
			var suite: RefCounted = effects_tests.new()
			if effects_only:
				await suite.run_effects_only(self, check)
			else:
				await suite.run_hud_only(self, check)
		print("%s: %s (%d checks)" % ["CAMP_COMBAT_EFFECTS_TEST" if effects_only else "CAMP_BOSS_HUD_TEST",
			"PASS" if failures == 0 else "FAIL", checks])
		quit(0 if failures == 0 else 1)
		return
	var code: Script = load("res://camp_presentation/camp_presentation.gd")
	assert_packed_sources(get_script().resource_path.get_base_dir().get_base_dir().path_join("scripts"), check)
	check(code != null and code.can_instantiate(), "raw namespaced script loads in Godot")
	if code == null or not code.can_instantiate():
		quit(1)
		return
	var world := Node3D.new()
	root.add_child(world)
	var scene: Node3D = code.new()
	world.add_child(scene)
	var catalogue: Dictionary = scene.read_catalogue()
	check(scene.setup(world, catalogue, ground, permitted, clock_value), "generic scene and sampler setup")
	check(not scene.setup(world, catalogue, ground, permitted), "duplicate setup rejected")
	check(scene.apply_snapshot(snapshot()), "valid display snapshot")
	await process_frame
	await process_frame
	check(exact_presentation_children(scene, ["hero", "pet", "boss"]), "exactly three real modular actors plus one FX and one HUD")
	check(scene.get_presentation_status().status == "ready", "after-frame presentation acknowledgement")
	assert_actor_heads(scene, check)
	for role: String in scene._actors:
		var actor: Dictionary = scene._actors[role]
		check(actor.frames.size() == 32 and actor.sprite is Sprite3D, role + " full frame set")
		check(actor.sprite.shaded and actor.root.visible and actor.safe, role + " grounded lit actor")
		check(actor.moon_fill.light_energy == 0.0 and not actor.moon_fill.visible,
			role + " missing optional weather leaves original daytime lighting")
		check(actor.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD, role + " only actor sprite uses real cutout, not opaque prepass")
		check(is_equal_approx(actor.sprite.alpha_scissor_threshold, 32.0 / 255.0), role + " alpha scissor matches builder >=32 threshold")
		check(actor.sprite.texture.get_image().has_mipmaps(), role + " per-frame mips")
		check(actor.sprite.texture.get_image().get_pixel(0, 0).a == 0.0, role + " exact transparent base alpha")
		var pixels: Image = actor.sprite.texture.get_image()
		check(is_equal_approx(pixels.get_pixel(12, 12).a, 254.0 / 255.0), role + " alpha254 body bytes retained and visible")
		check(is_equal_approx(pixels.get_pixel(1, 0).a, 31.0 / 255.0) and pixels.get_pixel(1, 0).a < actor.sprite.alpha_scissor_threshold,
			role + " alpha31 boundary noise is retained in texture but discarded by scissor")
		check(is_equal_approx(pixels.get_pixel(4, 4).a, 32.0 / 255.0) and pixels.get_pixel(4, 4).a >= actor.sprite.alpha_scissor_threshold,
			role + " alpha32 survives exactly at threshold inside four-pixel guard")
		check(actor.root.position.is_equal_approx(ground(Vector2(actor.root.position.x, actor.root.position.z))), role + " real ground height")
		check(actor.shadow.quaternion != Quaternion.IDENTITY, role + " sloping contact shadow")
	var invalid := snapshot()
	invalid["authToken"] = "secret"
	check(not scene.apply_snapshot(invalid), "private field rejected in native boundary too")
	invalid = snapshot()
	invalid.heroAssetId = "boss-test"
	check(not scene.apply_snapshot(invalid), "cross-role asset rejected")
	invalid = snapshot()
	invalid.elapsed = NAN
	check(not scene.apply_snapshot(invalid), "NaN rejected")
	invalid = snapshot()
	invalid.elapsed = true
	check(not scene.apply_snapshot(invalid), "bool is not a numeric time")
	invalid = snapshot()
	invalid.roundId = ""
	check(not scene.apply_snapshot(invalid), "fight requires public round reference")
	invalid = snapshot()
	invalid.elapsed = 600.0
	check(scene.apply_snapshot(invalid), "display at duration end")
	scene._process(0.1)
	check(scene.get_presentation_status().mode == "fighting", "time never changes authoritative mode")
	for index in range(60):
		test_clock += 0.1
		scene._process(0.1)
		for role: String in scene._actors:
			var actor: Dictionary = scene._actors[role]
			var point := Vector2(actor.root.position.x, actor.root.position.z)
			check(point.distance_to(scene.ARENA_CENTER) + actor.radius <= scene.ARENA_RADIUS, "bounded action " + role)
			check(actor.root.position.is_equal_approx(ground(point)), "action remains grounded " + role)
	var before: float = scene._motion_clock
	scene.apply_snapshot(snapshot("paused"))
	test_clock += 0.1
	scene._process(0.1)
	check(is_equal_approx(scene._motion_clock, before), "server pause freezes pose")
	scene.apply_snapshot(snapshot())
	scene.set_animation_paused(true)
	test_clock += 0.1
	scene._process(0.1)
	check(is_equal_approx(scene._motion_clock, before), "local animation pause obeyed")
	scene.set_animation_paused(false)
	scene._received_msec = Time.get_ticks_msec() - 16000
	test_clock += 0.1
	scene._process(0.1)
	check(is_equal_approx(scene._motion_clock, before) and scene._status == "stale", "stale authority freezes visual action")
	scene.apply_snapshot(snapshot("cooldown"))
	check(scene._pose("hero").row == 0, "cooldown uses idle, not combat")
	scene.apply_snapshot(snapshot("waiting"))
	check(not scene._actors.hero.root.visible, "waiting hides combat without scene replacement")
	var unsafe_scene: Node3D = code.new()
	world.add_child(unsafe_scene)
	check(unsafe_scene.setup(world, catalogue, ground, denied), "independent predicate setup")
	unsafe_scene.apply_snapshot(snapshot())
	await process_frame
	await process_frame
	check(unsafe_scene._status == "unsafe_placement" and not unsafe_scene._actors.hero.root.visible, "unsafe ground is refused")
	var missing_scene: Node3D = code.new()
	world.add_child(missing_scene)
	var missing: Dictionary = catalogue.duplicate(true)
	missing.assets[0].atlas = "res://camp_presentation/atlases/absent.png"
	check(missing_scene.setup(world, missing, ground, permitted), "missing optional art descriptor")
	missing_scene.apply_snapshot(snapshot())
	await process_frame
	await process_frame
	check(missing_scene._status == "missing_assets" and not missing_scene._actors.has("hero"), "missing art never becomes a primitive actor")
	check(exact_presentation_children(missing_scene, ["pet", "boss"]), "only pet/Boss plus FX/HUD; no hidden substitute for missing hero")
	var malformed_scene: Node3D = code.new()
	world.add_child(malformed_scene)
	var malformed: Dictionary = catalogue.duplicate(true)
	malformed.version = true
	check(not malformed_scene.setup(world, malformed, ground, permitted), "boolean manifest version rejected")
	malformed = catalogue.duplicate(true)
	malformed.assets[0].atlas = "res://scripts/meadow_scene.gd"
	check(not malformed_scene.setup(world, malformed, ground, permitted), "foreign resource path rejected")
	malformed = catalogue.duplicate(true)
	malformed.assets[0].frameRects = []
	check(not malformed_scene.setup(world, malformed, ground, permitted), "complete explicit frame contract required")
	malformed = catalogue.duplicate(true)
	malformed.assets[0].frameAnchors = [[16, 28]]
	check(not malformed_scene.setup(world, malformed, ground, permitted), "per-frame anchors must cover 32 slots")
	var flexible: Dictionary = catalogue.duplicate(true)
	flexible.assets[0].id = "hero/ranger"
	for asset: Dictionary in flexible.assets:
		asset.frameAnchors = []
		for index in range(32):
			asset.frameAnchors.append([14 + index % 2, 26 + index % 2])
	flexible.assets[2].worldHeight = 6.0
	var registered: Node3D = code.new()
	world.add_child(registered)
	check(registered.setup(world, flexible, ground, permitted), "generic frame sizes, public slash key and per-frame anchors")
	var named := snapshot("cooldown")
	named.heroAssetId = "hero/ranger"
	check(registered.apply_snapshot(named), "catalogue asset_key used verbatim")
	check(not registered._actors.boss.root.visible, "cooldown correctly hides the finished Boss")
	# The newly required inactive Boss must not animate. Test frame registration
	# under a complete paused encounter instead, deliberately selecting poses.
	named.mode = "paused"
	check(registered.apply_snapshot(named) and registered._actors.boss.root.visible, "explicit pose audit uses a visible Boss")
	for phase in [0.0, 0.25]:
		registered._motion_clock = phase
		registered._update_actors()
		var expected := Vector2(2, 10) if phase == 0.0 else Vector2(1, 11)
		check(registered._actors.hero.sprite.offset == expected, "per-frame feet compensation changes only offset")
		check(registered._actors.boss.sprite.offset == Vector2(-expected.x, expected.y), "mirrored Boss anchor correctly reflected")
	check(is_equal_approx(registered._actors.boss.sprite.pixel_size, 6.0 * code._display_scale(flexible.assets[2]) / 32.0), "same atlas cell scales Boss independently")
	var demo := {"mode": "demo", "heroAssetId": "hero/ranger", "petAssetId": "", "bossAssetId": "",
		"elapsed": 0.0, "duration": 0.0, "roundId": ""}
	check(registered.apply_snapshot(demo) and exact_presentation_children(registered, ["hero"]),
		"single-actor demo plus FX/HUD requires no stand-in art")
	demo.mode = "fighting"
	demo.roundId = "public-test"
	demo.duration = 600.0
	check(not registered.apply_snapshot(demo), "incomplete demo cannot masquerade as complete fighting presentation")
	test_pet_hover(code, world, catalogue)
	test_portrait_frames(code, world, catalogue)
	test_actor_moon_fill(code, catalogue)
	test_public_hp_schema(code, world, catalogue)
	world.free()
	await process_frame
	# Load the sibling TEST script from this entry's absolute path, not into the
	# delivered PCK. The builder still mounts only synthetic test artwork.
	var combat_code: Script = load(get_script().resource_path.get_base_dir().path_join("test_camp_combat_effects.gd"))
	check(combat_code != null and combat_code.can_instantiate(), "independent combat regression suite loads")
	if combat_code != null and combat_code.can_instantiate():
		var combat_tests: RefCounted = combat_code.new()
		await combat_tests.run(self, code, catalogue, check)
	print("CAMP_PRESENTATION_TEST: %s (%d checks)" % ["PASS" if failures == 0 else "FAIL", checks])
	quit(0 if failures == 0 else 1)
