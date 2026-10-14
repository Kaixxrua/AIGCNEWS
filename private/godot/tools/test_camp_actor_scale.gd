extends SceneTree
## Focused public v165 scale contracts using all 13 ORIGINAL pinned PNG shards.
## Run in a disposable headless project, never the editor or a live service.
## Args: absolute main-built presentation-pack.json, NEW scoped result.json.
## Actual frozen terrain is checked separately by test_camp_actual_core.gd.

const ACTORS := {
	"hero_ranger": "hero", "hero_knight": "hero", "hero_mage": "hero",
	"hero_bard": "hero", "hero_alchemist": "hero", "hero_astrologer": "hero",
	"pet_deer": "pet", "pet_fox": "pet", "pet_rabbit": "pet",
	"pet_owl": "pet", "pet_finch": "pet", "pet_dragon": "pet",
	"boss_ancient_guardian": "boss",
}
const PET_SCALES := {"pet_deer": 0.90, "pet_fox": 0.94, "pet_rabbit": 0.60,
	"pet_owl": 0.62, "pet_finch": 0.68, "pet_dragon": 0.93}
const HOVER := ["pet_owl", "pet_finch", "pet_dragon"]
const STATIONS := {"hero": Vector2(2.65, -10.90), "pet": Vector2(3.65, -9.90),
	"boss": Vector2(6.85, -12.65)}
const PHASES := [0.0, 0.29, 0.30, 0.60, 0.949, 0.95, 1.349, 1.35, 1.5, 1.8,
	2.1, 2.449, 2.45, 2.85, 5.19, 5.2, 5.8, 10.399, 10.4, 11.349, 11.35,
	11.7, 11.83, 12.03, 12.75, 13.8, 15.6, 16.55, 17.23, 17.95, 19.0,
	20.8, 21.4, 22.9, 26.0, 26.6, 28.1, 31.199, 31.2]

class TestWeather:
	extends Node
	var night_blend := 0.0

var checks := 0
var failures: Array[String] = []
var _workspace := ""
var _result_path := ""
var _clock := 0.0
var _deny_enabled := false
var _denied_probe := Vector2.ZERO
var _scene: Node3D
var _camera: Camera3D
var _pool_ids: Array[int] = []
var _hud_id := 0
var _source_assets: Dictionary = {}
var _source_hashes: Dictionary = {}
var _actor_evidence: Dictionary = {}
var _ratios: Dictionary = {}

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures.append(label)
		print("CAMP_ACTOR_SCALE_FAIL: " + label)

static func expected_scale(spec: Dictionary) -> float:
	# Independent approved oracle, not the renderer's own constants.
	if spec.role == "pet":
		return float(PET_SCALES.get(spec.id, 0.80))
	return 2.0 if spec.role == "boss" else 1.10

func ground(point: Vector2) -> Vector3:
	return Vector3(point.x, point.x * 0.025 + point.y * 0.018, point.y)

func permitted(point: Vector2) -> bool:
	return not _deny_enabled or point.distance_to(_denied_probe) > 0.002

func clock_value() -> float:
	return _clock

func snapshot() -> Dictionary:
	return {"mode": "paused", "heroAssetId": "hero_ranger", "petAssetId": "pet_deer",
		"bossAssetId": "boss_ancient_guardian", "elapsed": 210.0, "duration": 600.0,
		"roundId": "public-scale-v165", "bossHp": 1155, "bossMaxHp": 6000}

func _scoped(path: String, directory: String) -> bool:
	return path.is_absolute_path() and path.simplify_path().replace("\\", "/").to_lower().begins_with(
		directory.simplify_path().replace("\\", "/").to_lower() + "/")

func _json(path: String) -> Dictionary:
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	check(value is Dictionary, "JSON object: " + path.get_file())
	return value if value is Dictionary else {}

func _mount(pin: Dictionary, directory: String) -> bool:
	var name := str(pin.get("file", ""))
	var path := directory.path_join(name).simplify_path()
	var valid: bool = name == name.get_file() and name.ends_with(".pck") and _scoped(path, directory)
	check(valid, "pinned pack is a local basename")
	if not valid:
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	valid = file != null and file.get_length() == int(pin.get("bytes", -1)) \
		and FileAccess.get_sha256(path) == pin.get("sha256", "")
	check(valid, "exact existing PCK bytes/hash: " + name)
	if not valid:
		return false
	var mounted := ProjectSettings.load_resource_pack(path, false)
	check(mounted, "mount without replacing resources: " + name)
	return mounted

func _load_art(manifest_path: String) -> Dictionary:
	var manifest := _json(manifest_path)
	if manifest.get("version") != 2 or not manifest.get("actorShards") is Array:
		check(false, "main-built sharded version2 runtime required")
		return {}
	var directory := manifest_path.get_base_dir()
	if not _mount(manifest.pack, directory):
		return {}
	for name: String in ["camp_presentation.gd", "camp_combat_effects.gd", "camp_boss_hud.gd"]:
		var source := _workspace.path_join("godot/scripts/" + name)
		var packed := "res://camp_presentation/" + name
		check(FileAccess.file_exists(packed) and FileAccess.get_file_as_bytes(source) == FileAccess.get_file_as_bytes(packed),
			"runtime contains exact frozen current source: " + name)
		_source_hashes[source] = FileAccess.get_sha256(source)
	if not failures.is_empty():
		return {}
	var ids: Dictionary = {}
	for shard: Dictionary in manifest.actorShards:
		for id: String in shard.assetIds:
			check(ACTORS.has(id) and not ids.has(id), "unique approved actor shard ID: " + id)
			ids[id] = true
		if not _mount(shard.pack, directory):
			return {}
	check(ids.size() == 13, "all 13 actor shards, no synthetic actor replacement")
	var source_manifest := _workspace.path_join("godot/assets/camp/v1/manifest.json")
	_source_hashes[source_manifest] = FileAccess.get_sha256(source_manifest)
	for spec: Dictionary in _json(source_manifest).get("assets", []):
		_source_assets[spec.id] = spec
	var catalogue := _json("res://camp_presentation/manifest.json")
	check(catalogue.get("assets", []).size() == 13 and _source_assets.size() == 13, "13 original catalogue entries")
	var seen: Dictionary = {}
	for spec: Dictionary in catalogue.get("assets", []):
		if not ACTORS.has(spec.id) or not _source_assets.has(spec.id):
			check(false, "only the frozen original actor IDs")
			return {}
		check(not seen.has(spec.id) and spec.role == ACTORS[spec.id], "unique original role: " + str(spec.id))
		seen[spec.id] = true
		var original: Dictionary = _source_assets[spec.id]
		for key: String in original:
			if key != "atlas":
				check(spec.get(key) == original[key], "source descriptor remains unchanged: " + str(spec.id) + "/" + key)
		var png := source_manifest.get_base_dir().path_join(str(original.atlas)).simplify_path()
		check(_scoped(png, source_manifest.get_base_dir()), "original PNG remains within the public art directory")
		check(FileAccess.get_file_as_bytes(png) == FileAccess.get_file_as_bytes(spec.atlas), "byte-exact original PNG: " + str(spec.id))
		_source_hashes[png] = FileAccess.get_sha256(png)
	return catalogue

func _frame_info(image: Image, original: Image) -> Dictionary:
	# Scan BASE pixels only; source alpha 1..31 is preserved but not visible.
	var width := image.get_width()
	var height := image.get_height()
	var pixels := image.get_data()
	var source := original.get_data()
	var left := width
	var top := height
	var right := -1
	var bottom := -1
	var exact_alpha := true
	for y in range(height):
		for x in range(width):
			var index := (y * width + x) * 4 + 3
			exact_alpha = exact_alpha and pixels[index] == source[index]
			if pixels[index] >= 32:
				left = mini(left, x)
				top = mini(top, y)
				right = maxi(right, x)
				bottom = maxi(bottom, y)
	return {"bounds": Rect2i(left, top, right - left + 1, bottom - top + 1) if right >= 0 else Rect2i(),
		"exactAlpha": exact_alpha}

func _nodes() -> void:
	check(_scene._actors.size() == 3 and _scene.get_child_count() == 5, "exact trio plus one FX and HUD")
	check(_scene._boss_hud.get_instance_id() == _hud_id, "no HUD replacement during scale/swap")
	var ids: Array[int] = []
	for child: Node in _scene._effects.get_children():
		ids.append(child.get_instance_id())
	check(ids == _pool_ids and ids.size() == 3, "same fixed three-mesh pool")
	var debug: Dictionary = _scene._effects.debug_state()
	for count: int in debug.vertices.values():
		check(count >= 0 and count <= int(debug.vertexLimit), "scaled geometry stays within the existing role vertex cap")
	for actor: Dictionary in _scene._actors.values():
		check(actor.root.get_parent() == _scene and actor.root.get_child_count() == 3, "actor owns only sprite, light and shadow")
		check(actor.root.scale.is_equal_approx(Vector3.ONE) and actor.sprite.scale.is_equal_approx(Vector3.ONE)
			and actor.shadow.scale.is_equal_approx(Vector3.ONE), "no root or secondary transform scale")

func _audit_actor(spec: Dictionary) -> void:
	var actor: Dictionary = _scene._actors[spec.role]
	var multiplier := expected_scale(spec)
	var pixel_size := float(spec.worldHeight) * multiplier / float(spec.frameSize[1])
	var radius := float(spec.shadowRadius) * multiplier
	check(is_equal_approx(_scene._display_scale(spec), multiplier), "approved physical multiplier: " + str(spec.id))
	check(is_equal_approx(actor.sprite.pixel_size, pixel_size) and is_equal_approx(actor.height, float(spec.worldHeight) * multiplier),
		"scaled frame-height denominator and physical actor.height: " + str(spec.id))
	check(is_equal_approx(actor.radius, radius) and actor.shadow.mesh.size.is_equal_approx(Vector2(radius * 2.0, radius * 1.4)),
		"physical footprint and shadow size scale once: " + str(spec.id))
	var station: Vector2 = Vector2(2.90, -15.20) if spec.id in HOVER else STATIONS[spec.role]
	check(actor.station.is_equal_approx(station), "approved unchanged/new station: " + str(spec.id))
	var opponent: Vector2 = STATIONS.hero if spec.role == "boss" else STATIONS.boss
	check(actor.direction.is_equal_approx(station.direction_to(opponent)), "facing/lunge uses approved Boss position")
	check(actor.frames.size() == 32 and actor.heads.size() == 32 and actor.offsets.size() == 32, "all frame caches have 32 entries")
	var fill: OmniLight3D = actor.moon_fill
	check(fill.position.is_equal_approx(Vector3(-3, maxf(4.0, float(actor.heads.max()) + 0.8), 6)), "own moon bounce remains above scaled visible head")
	check(is_equal_approx(fill.omni_range, 16.0) and fill.light_cull_mask == {"hero": 1 << 17, "pet": 1 << 18, "boss": 1 << 19}[spec.role]
		and not fill.shadow_enabled, "moon range/role isolation/shadow policy unchanged")
	var source := Image.new()
	if source.load_png_from_buffer(FileAccess.get_file_as_bytes(spec.atlas)) != OK:
		check(false, "original PNG decodes")
		return
	var idle: Array[float] = []
	var frame_rows: Array = []
	for index in range(32):
		var frame: Image = actor.frames[index].get_image()
		var rect: Array = spec.frameRects[index]
		var original := source.get_region(Rect2i(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])))
		var valid := frame.get_size() == original.get_size() and frame.get_format() == Image.FORMAT_RGBA8
		check(valid, "%s frame%d original dimensions/RGBA" % [spec.id, index])
		if not valid:
			continue
		var info := _frame_info(frame, original)
		var bounds: Rect2i = info.bounds
		check(info.exactAlpha and bounds.has_area(), "%s frame%d exact alpha and nonempty visible art" % [spec.id, index])
		var anchor: Array = spec.frameAnchors[index] if spec.has("frameAnchors") else spec.anchor
		var half := Vector2(float(spec.frameSize[0]), float(spec.frameSize[1])) * 0.5
		var flip := -1.0 if spec.role == "boss" else 1.0
		var offset: Vector2 = actor.offsets[index]
		var pivot := Vector2((float(anchor[0]) - half.x) * flip + offset.x, half.y - float(anchor[1]) + offset.y) * pixel_size
		check(pivot.is_zero_approx() and actor.sprite.flip_h == (spec.role == "boss"), "%s frame%d pixel foot pivot survives scale/mirror" % [spec.id, index])
		var head := maxf(0.0, float(anchor[1]) - bounds.position.y) * pixel_size
		check(is_equal_approx(actor.heads[index], head), "%s frame%d cached head uses actual alpha>=32" % [spec.id, index])
		var height := bounds.size.y * pixel_size
		if index < 8:
			idle.append(height)
		frame_rows.append({"frame": index, "alphaBounds": [bounds.position.x, bounds.position.y, bounds.end.x, bounds.end.y],
			"visibleHeightM": height, "visibleWidthM": bounds.size.x * pixel_size, "headAboveAnchorM": head,
			"bboxBottomAboveAnchorM": (float(anchor[1]) - bounds.end.y) * pixel_size})
	check(idle.size() == 8 and frame_rows.size() == 32, "complete actual-frame measurement: " + str(spec.id))
	_actor_evidence[spec.id] = {"role": spec.role, "scale": multiplier, "pixelSize": actor.sprite.pixel_size,
		"sourceWorldHeight": spec.worldHeight, "displayHeight": actor.height, "contactRadius": actor.radius,
		"idleVisibleHeightsM": idle, "frames": frame_rows}
	# Negative footprint oracles exercise the REAL predicate, not only expected values.
	var centre: Vector2 = _scene.ARENA_CENTER
	var edge: float = _scene.ARENA_RADIUS - radius
	check(_scene._safe_point(centre + Vector2(edge - 0.001, 0), radius), "scaled footprint just inside arena")
	check(not _scene._safe_point(centre + Vector2(edge + 0.001, 0), radius), "scaled footprint just outside fails closed")
	_denied_probe = station + Vector2(radius, 0)
	_deny_enabled = true
	check(not _scene._safe_segment(station, station + actor.direction * actor.reach, radius), "denied physical footprint probe rejects whole segment")
	_deny_enabled = false
	var confirmed: Dictionary = _scene._snapshot.duplicate(true)
	for phase: float in PHASES:
		_scene._motion_clock = phase
		check(_scene._update_actors(), "bounded action/ultimate phase: " + str(phase))
		var pose: Dictionary = _scene._pose(spec.role)
		var point: Vector2 = station + actor.direction * actor.reach * float(pose.travel)
		check(actor.root.position.is_equal_approx(ground(point)), "lunge retained; root remains exactly ground-sampled")
		check(actor.shadow.global_position.is_equal_approx(ground(point) + Vector3(0, 0.016, 0)), "shadow never inherits sprite bob or height scale")
		check(_scene._safe_point(point, radius) and point.distance_to(centre) + radius <= _scene.ARENA_RADIUS, "actual physical radius fits each sampled pose")
		var lift := 1.25 + sin(phase * TAU / 2.6) * 0.06 if spec.id in HOVER else 0.0
		check(is_equal_approx(actor.sprite.position.y, lift), "species scale does not scale the hover lift/bob")
		check(actor.sprite.offset == actor.offsets[actor.frame], "pose selects its matching pixel anchor")
		check(_scene._snapshot == confirmed and is_equal_approx(_scene._confirmed_boss_ratio(), 1155.0 / 6000.0), "scale/choreography cannot change confirmed HP/time/round")
	_nodes()

func _audit_ratios() -> void:
	var boss: Array = _actor_evidence.boss_ancient_guardian.idleVisibleHeightsM
	for id: String in ACTORS:
		if ACTORS[id] != "hero":
			continue
		var hero: Array = _actor_evidence[id].idleVisibleHeightsM
		if boss.size() != 8 or hero.size() != 8 or float(hero.min()) <= 0.0:
			check(false, "ratio requires eight real positive idle frames")
			continue
		var low := float(boss.min()) / float(hero.max())
		var high := float(boss.max()) / float(hero.min())
		check(low >= 3.0 and high <= 3.7, "all idle-frame visible Boss/hero ratios in 3.0..3.7: " + id)
		_ratios[id] = {"minimum": low, "maximum": high}

func _audit_freeze_and_hud() -> void:
	for mode: String in ["paused", "stale", "hidden"]:
		var state := snapshot()
		state.mode = "paused" if mode == "paused" else "fighting"
		check(_scene.apply_snapshot(state), "freeze setup " + mode)
		if mode == "stale":
			_scene._received_msec = Time.get_ticks_msec() - 16000
		_scene.visible = mode != "hidden"
		var phase: float = _scene._motion_clock
		var fx_clock: float = _scene._effects.debug_state().clock
		var transforms: Array = []
		for actor: Dictionary in _scene._actors.values():
			transforms.append([actor.root.transform, actor.sprite.transform, actor.shadow.transform])
		_clock += 0.1
		_scene._process(0.1)
		var after: Array = []
		for actor: Dictionary in _scene._actors.values():
			after.append([actor.root.transform, actor.sprite.transform, actor.shadow.transform])
		check(transforms == after and is_equal_approx(phase, _scene._motion_clock)
			and is_equal_approx(fx_clock, _scene._effects.debug_state().clock), "all scaled transforms and skill clock frozen: " + mode)
		_scene.visible = true
	var state := snapshot()
	check(_scene.apply_snapshot(state), "restore valid positive confirmed HP")
	var boss: Dictionary = _scene._actors.boss
	var head: Vector3 = boss.root.global_position + Vector3.UP * (boss.heads[maxi(0, boss.frame)] + boss.sprite.position.y + 0.18)
	var hud: Dictionary = _scene._boss_hud.debug_state()
	check(hud.anchor.is_equal_approx(_camera.unproject_position(head)), "HUD receives the scaled alpha-visible head anchor")
	check(hud.visible and hud.layout == "bottom_center" and is_equal_approx(hud.ratio, 1155.0 / 6000.0), "fixed-bottom HUD and authoritative ratio unaffected")
	check(not _scene._death_active and boss.root.visible, "scaling positive HP never triggers death")
	state.mode = "defeated"
	state.bossHp = 0
	state.elapsed = 261.43
	check(_scene.apply_snapshot(state), "only confirmed zero enters death")
	for age: float in [0.0, 0.6, 1.5, 2.59, 2.6]:
		_scene._death_clock = age
		_scene._update_actors()
		check(_scene._snapshot == state and _scene._confirmed_boss_ratio() == 0.0, "death cannot alter HP/time snapshot")
		check(boss.root.visible == (age < 2.6) and is_equal_approx(boss.height, 12.0), "same death lifetime with scaled physical Boss")
		_nodes()
	state = snapshot()
	state.mode = "fighting"
	state.roundId = "public-scale-v165-next"
	check(_scene.apply_snapshot(state), "new display round resets prior death")
	check(not _scene._death_active and is_zero_approx(_scene._death_clock) and boss.root.visible
		and boss.sprite.modulate == Color.WHITE and boss.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD, "new round restores scaled living sprite without state invention")

func _finish(started: int, manifest_path: String = "") -> void:
	for path: String in _source_hashes:
		check(FileAccess.get_sha256(path) == _source_hashes[path], "source/art immutable throughout focused test: " + path.get_file())
	var report := {"status": "PASS" if failures.is_empty() else "FAIL", "checks": checks, "failures": failures,
		"elapsedMs": (Time.get_ticks_usec() - started) / 1000.0, "presentationManifest": manifest_path,
		"sourceHashes": _source_hashes, "actors": _actor_evidence, "idleBossHeroRatios": _ratios,
		"limitations": ["Actual pinned original PNGs in a tiny sloped TEST world; actual frozen terrain is a separate probe.",
			"Headless CPU geometry/alpha evidence, not GPU, screenshots, perceived perspective or FPS.",
			"Only idle silhouettes require ratio3.0..3.7; attack/crouch frames retain their original anatomy.",
			"No backend, account, rewards, provider, network or autonomous combat authority."]}
	if not _result_path.is_empty() and not FileAccess.file_exists(_result_path):
		var output := FileAccess.open(_result_path, FileAccess.WRITE)
		if output != null:
			output.store_string(JSON.stringify(report, "\t") + "\n")
			output.close()
		else:
			check(false, "new evidence file opens inside assigned artifact directory")
	print("CAMP_ACTOR_SCALE_TEST: %s (%d checks)" % ["PASS" if failures.is_empty() else "FAIL", checks])
	quit(0 if failures.is_empty() else 1)

func run() -> void:
	var started := Time.get_ticks_usec()
	_workspace = get_script().resource_path.get_base_dir().get_base_dir().get_base_dir().simplify_path()
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() != 2:
		check(false, "requires main-built pack manifest and new scoped evidence path")
		_finish(started)
		return
	var manifest_path := str(arguments[0]).simplify_path()
	var output_path := str(arguments[1]).simplify_path()
	var valid := _scoped(manifest_path, _workspace.path_join("artifacts")) and manifest_path.get_file() == "presentation-pack.json"
	valid = valid and _scoped(output_path, _workspace.path_join("artifacts/camp-scale-v165")) \
		and output_path.ends_with(".json") and not FileAccess.file_exists(output_path) and DirAccess.dir_exists_absolute(output_path.get_base_dir())
	check(valid and DisplayServer.get_name() == "headless", "isolated headless input and new output are confined to public artifacts")
	if not valid or DisplayServer.get_name() != "headless":
		_finish(started)
		return
	_result_path = output_path
	var catalogue := _load_art(manifest_path)
	if catalogue.is_empty() or not failures.is_empty():
		_finish(started, manifest_path)
		return
	var code: Script = load("res://camp_presentation/camp_presentation.gd")
	check(code != null and code.can_instantiate(), "actual packed renderer parses")
	if code == null or not code.can_instantiate():
		_finish(started, manifest_path)
		return
	root.size = Vector2i(1280, 800)
	var world := Node3D.new()
	root.add_child(world)
	var weather := TestWeather.new()
	weather.name = "LivingWeather"
	world.add_child(weather)
	var light := DirectionalLight3D.new()
	light.light_energy = 1.2
	world.add_child(light)
	_camera = Camera3D.new()
	world.add_child(_camera)
	_camera.position = Vector3(17, 20, 18)
	_camera.look_at(Vector3(5, 3, -12))
	_camera.current = true
	var children_before := world.get_child_count()
	var world_transform := world.transform
	var light_transform := light.transform
	_scene = code.new()
	world.add_child(_scene)
	check(_scene.setup(world, catalogue, ground, permitted, clock_value), "real renderer uses isolated sloped samplers")
	_scene.set_process(false)
	check(_scene.apply_snapshot(snapshot()), "public confirmed-state fixture accepted")
	if _scene._actors.size() != 3:
		check(false, "all three initial original actors load")
		world.free()
		_finish(started, manifest_path)
		return
	_hud_id = _scene._boss_hud.get_instance_id()
	for child: Node in _scene._effects.get_children():
		_pool_ids.append(child.get_instance_id())
	check(is_equal_approx(code._display_scale({"role": "pet", "id": "unregistered_pet"}), 0.80), "unknown pet ID has bounded0.80 scale fallback")
	check(is_equal_approx(code._display_scale({"role": "hero", "id": "pet_dragon"}), 1.10), "species override cannot leak into a non-pet role")
	for spec: Dictionary in catalogue.assets:
		var state := snapshot()
		state[spec.role + "AssetId"] = spec.id
		var previous_root: Node3D = _scene._actors[spec.role].root
		var replacing: bool = _scene._actors[spec.role].id != spec.id
		check(_scene.apply_snapshot(state), "actual original actor selection: " + str(spec.id))
		check(not replacing or not is_instance_valid(previous_root), "obsolete actor root released on swap")
		_audit_actor(spec)
	check(_actor_evidence.size() == 13, "measured every original actor")
	_audit_ratios()
	_audit_freeze_and_hud()
	for night: float in [0.0, 0.5, 1.0]:
		weather.night_blend = night
		_scene.set_animation_paused(true)
		_scene._process(0.0)
		for actor: Dictionary in _scene._actors.values():
			check(is_equal_approx(actor.height, _actor_evidence[actor.id].displayHeight), "day/night never changes physical actor height")
		check(world.transform == world_transform and world.get_child_count() == children_before + 1
			and light.transform == light_transform and is_equal_approx(light.light_energy, 1.2), "world layout/light/ownership unchanged")
	_nodes()
	world.free()
	await process_frame
	_finish(started, manifest_path)
