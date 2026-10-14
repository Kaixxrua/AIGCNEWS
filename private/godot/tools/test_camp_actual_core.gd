extends SceneTree
## Opt-in real frozen core15 runtime probe. No synthetic world, engine export,
## scene edits, visual substitute, or Web-ready fabrication. Native/headless
## observations do not replace main's browser/GPU/ten-second acceptance.

const PresentationAssertions := preload("test_camp_presentation.gd")
const Presentation := preload("../scripts/camp_presentation.gd")

var checks := 0
var failures: Array[String] = []
var mount_replies: Array = []

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures.append(label)
		print("CAMP_ACTUAL_CORE_FAIL: " + label)

func point_json(value: Vector3) -> Array:
	return [value.x, value.y, value.z]

func mount_reply(request_id: int, success: bool, code: String) -> void:
	mount_replies.append([request_id, success, code])

func stage_art_pack(pin: Dictionary, source_directory: String, probe_directory: String) -> bool:
	# Only small pinned presentation PCKs enter the isolated probe user folder.
	# Neither the scene PCK nor a staged export or PNG is copied/edited.
	var user_path := OS.get_user_data_dir().simplify_path()
	var source := source_directory.path_join(str(pin.file)).simplify_path()
	var scoped := user_path.begins_with(probe_directory.simplify_path() + "/") \
		and source.begins_with(source_directory.simplify_path() + "/") \
		and not FileAccess.file_exists("user://" + str(pin.file))
	check(scoped, "actual art PCK copy stays in new isolated user folder")
	if not scoped:
		return false
	var input := FileAccess.open(source, FileAccess.READ)
	var matches: bool = input != null and input.get_length() == int(pin.bytes) and FileAccess.get_sha256(source) == pin.sha256
	check(matches, "actual presentation artifact matches immutable pin: " + str(pin.file))
	if not matches:
		return false
	DirAccess.make_dir_recursive_absolute(user_path)
	var output := FileAccess.open("user://" + str(pin.file), FileAccess.WRITE)
	if output == null:
		check(false, "isolated presentation PCK output opens")
		return false
	output.store_buffer(input.get_buffer(input.get_length()))
	output.close()
	input.close()
	check(FileAccess.get_sha256("user://" + str(pin.file)) == pin.sha256, "isolated PCK copy remains byte-exact")
	return true

func mount_real_trio(host: Node, world: Node3D, art: Dictionary, probe_directory: String) -> Node3D:
	host.mount_completed.connect(mount_reply)
	if not stage_art_pack(art.runtime, art.directory, probe_directory):
		return null
	host.mount_presentation(1, "/" + str(art.runtime.file), art.runtime.sha256)
	await process_frame
	await process_frame
	check(not mount_replies.is_empty() and mount_replies.back() == [1, true, "applied"], "real Host mounts actual runtime after core")
	var renderer := world.get_node_or_null("CampPresentation") as Node3D
	check(renderer != null, "actual public renderer attached by Host, not manual fixture")
	if renderer == null:
		return null
	PresentationAssertions.assert_packed_sources(get_script().resource_path.get_base_dir().get_base_dir().path_join("scripts"), check)
	renderer.set_process(false)
	var snapshot := {"mode": "fighting", "heroAssetId": art.selectedAssetIds.hero, "petAssetId": art.selectedAssetIds.pet,
		"bossAssetId": art.selectedAssetIds.boss, "elapsed": 0.0, "duration": 600.0, "roundId": "native-public-trio-probe"}
	check(renderer.apply_snapshot(snapshot), "non-authoritative public display snapshot accepted")
	var request_id := 2
	for shard: Dictionary in art.selectedShards:
		if not stage_art_pack(shard.pack, art.directory, probe_directory):
			return renderer
		host.mount_actor(request_id, "/" + str(shard.pack.file), shard.pack.sha256)
		await process_frame
		await process_frame
		check(mount_replies.back() == [request_id, true, "applied"], "actual PNG-only actor shard applied through Host")
		request_id += 1
	await process_frame
	await process_frame
	check(PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"]),
		"actual selected trio plus exactly one presentation-owned FX/HUD; no placeholders")
	check(renderer.get_presentation_status().status == "ready", "actual trio ready after native frame boundary")
	return renderer

func inspect_real_trio(renderer: Node3D, host: Node, art: Dictionary) -> Dictionary:
	var result := {"assetIds": art.selectedAssetIds, "manifestSha256": art.manifestSha256,
		"runtime": art.runtime, "selectedShards": art.selectedShards, "actors": {},
		"note": "Actual pinned artwork, headless geometry/texture checks; no GPU or visual acceptance"}
	PresentationAssertions.assert_actor_heads(renderer, check)
	for expected: Dictionary in art.packedActors:
		var spec: Dictionary = expected.asset
		check(renderer._actors.has(spec.role), "actual actor exists: " + str(spec.id))
		if not renderer._actors.has(spec.role):
			continue
		var actor: Dictionary = renderer._actors[spec.role]
		check(actor.id == spec.id and actor.root.visible and actor.safe, "actual selected actor visible and safe: " + str(spec.id))
		check(actor.frames.size() == 32 and actor.sprite is Sprite3D, "actual actor has all 32 bitmap frames")
		check(FileAccess.get_sha256(spec.atlas) == expected.sourcePngSha256, "mounted original PNG bytes remain exact")
		check(actor.sprite.alpha_cut == SpriteBase3D.ALPHA_CUT_DISCARD \
			and is_equal_approx(actor.sprite.alpha_scissor_threshold, 32.0 / 255.0), "actual actor-only cutout threshold")
		var display_scale: float = Presentation._display_scale(spec)
		check(is_equal_approx(actor.height, float(spec.worldHeight) * display_scale)
			and is_equal_approx(actor.sprite.pixel_size, actor.height / float(spec.frameSize[1])), "source height times display scale sets actual frame size")
		check(is_equal_approx(actor.radius, float(spec.shadowRadius) * display_scale)
			and actor.root.scale.is_equal_approx(Vector3.ONE), "actual scaled contact radius with unit root transform")
		var heights: Array[float] = []
		var foot_gaps: Array[float] = []
		for index in range(32):
			var bounds: Array = expected.visibleFrameBounds[index]
			var anchor: Array = spec.frameAnchors[index] if spec.has("frameAnchors") else spec.anchor
			var image: Image = actor.frames[index].get_image()
			check(image.get_width() == int(spec.frameSize[0]) and image.get_height() == int(spec.frameSize[1]), "actual frame dimensions " + str(index))
			heights.append((float(bounds[3]) - float(bounds[1])) * actor.sprite.pixel_size)
			# Positive = visible bbox bottom above root anchor, not a claim that
			# a weapon/effect bbox is a foot. Preserve this diagnostic for review.
			foot_gaps.append((float(anchor[1]) - float(bounds[3])) * actor.sprite.pixel_size)
		result.actors[spec.role] = {"id": spec.id, "worldHeight": spec.worldHeight, "displayHeight": actor.height,
			"displayScale": display_scale, "shadowRadius": actor.radius,
			"stationGround": point_json(host.sample_ground(actor.station)), "sourcePngSha256": expected.sourcePngSha256,
			"visibleBoundsHeightM": [heights.min(), heights.max()], "bboxBottomVsGroundM": [foot_gaps.min(), foot_gaps.max()],
			"frameBoundsBottomVsGroundM": foot_gaps}
	# Actual frozen host terrain/river/rock predicates, for every scaled species.
	# In particular do not accidentally test the guardian's old 1.02m radius.
	var footprints := {}
	for spec: Dictionary in renderer._catalogue.values():
		var local_station: Vector2 = renderer.HOVER_PET_STATION if spec.id in renderer.HOVER_PET_IDS else renderer.STATIONS[spec.role]
		var station: Vector2 = renderer.ARENA_CENTER + local_station
		var target: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS["hero" if spec.role == "boss" else "boss"]
		var reach := 0.42 if spec.role == "boss" else 0.58
		var radius: float = float(spec.shadowRadius) * Presentation._display_scale(spec)
		var finish := station + station.direction_to(target) * reach
		var safe: bool = renderer._safe_segment(station, finish, radius)
		check(safe, "actual frozen terrain supports scaled full footprint/lunge: " + str(spec.id))
		if spec.id == "boss_ancient_guardian":
			check(is_equal_approx(radius, 2.04), "actual guardian footprint is the enlarged2.04m radius")
		footprints[spec.id] = {"radius": radius, "safe": safe, "foot": point_json(host.sample_ground(station)),
			"lungeFoot": point_json(host.sample_ground(finish)),
			"arenaBoundaryMarginM": renderer.ARENA_RADIUS - maxf(station.distance_to(renderer.ARENA_CENTER), finish.distance_to(renderer.ARENA_CENTER)) - radius}
	result["allActorScaledFootprints"] = footprints
	var rows := {"hero": {}, "pet": {}, "boss": {}}
	for index in range(53):
		# Explicit local presentation phase sweep, no authority or settlement.
		renderer._motion_clock = float(index) * 0.1
		check(renderer._update_actors(), "actual choreography safe at phase " + str(index))
		for role: String in renderer._actors:
			var actor: Dictionary = renderer._actors[role]
			rows[role][renderer._pose(role).row] = true
			var point := Vector2(actor.root.position.x, actor.root.position.z)
			check(actor.root.position.is_equal_approx(host.sample_ground(point)), "actual actor stays on sampler through action: " + role)
	result["phaseSamples"] = 53
	result["poseRowsObserved"] = {"hero": rows.hero.keys(), "pet": rows.pet.keys(), "boss": rows.boss.keys()}
	result["status"] = renderer.get_presentation_status().status
	return result

func inspect_actual_details(renderer: Node3D, host: Node, world: Node3D, directory: String) -> Dictionary:
	var weather := world.get_node("LivingWeather")
	var controller := world.get_node("ProgressiveDetails")
	var identity := weather.get_instance_id()
	var rows: Array = []
	var motion: bool = weather.motion_enabled
	weather.set_motion(false)
	for chunk: Dictionary in controller.manifest.chunks:
		var path := directory.path_join(str(chunk.file))
		check(FileAccess.get_sha256(path) == chunk.sha256, "actual native detail pin before apply: " + str(chunk.index))
		await controller.apply_chunk(int(chunk.index), path)
		await process_frame
		check(controller.applied_count == int(chunk.index) + 1 and not controller.busy and controller.last_error == "",
			"actual progressive controller applied pinned chunk: " + str(chunk.index))
		check(is_instance_valid(weather) and world.get_node("LivingWeather") == weather
			and renderer._lighting_weather == weather and host._weather == weather,
			"actual weather and both cached references survive detail chunk: " + str(chunk.index))
		renderer._process(0.0)
		rows.append({"applied": controller.applied_count, "weatherInstanceId": world.get_node("LivingWeather").get_instance_id(),
			"rendererWeatherValid": is_instance_valid(renderer._lighting_weather), "nightFactor": renderer._night_factor()})
	check(controller.completed and controller.applied_count == 12 and host._live(), "real all-twelve detail completion keeps Camp Host live")
	weather.set_motion(motion)
	return {"weatherInstanceBefore": identity, "weatherInstanceAfter": world.get_node("LivingWeather").get_instance_id(),
		"completed": controller.completed, "rows": rows, "note": "Actual pinned native detail PCKs; no substitute nodes or copied world pack"}

func capture_actual_lighting(world: Node3D, directory: String, label: String) -> Dictionary:
	for frame in range(12):
		await process_frame
		await RenderingServer.frame_post_draw
	var rendered: Image = root.get_texture().get_image()
	var destination := directory.path_join(label + ".png")
	check(not FileAccess.file_exists(destination), "new diagnostic GPU image only")
	check(rendered.save_png(destination) == OK, "actual native GPU image saved without scaling or pixel edits")
	var result := {"file": destination, "size": [rendered.get_width(), rendered.get_height()], "actors": {}}
	var camera := world.get_node("Camera3D") as Camera3D
	var renderer := world.get_node("CampPresentation")
	for role: String in renderer._actors:
		var actor: Dictionary = renderer._actors[role]
		var centre: Vector2 = camera.unproject_position(actor.sprite.global_position + Vector3(0, 1.0 if role != "boss" else 1.8, 0))
		# Camera coordinates are logical viewport units, not necessarily texture
		# pixels (e.g. native 1280x800 stretch -> 2304x1440 texture). No image resize.
		centre *= Vector2(rendered.get_size()) / root.get_visible_rect().size
		var sample := Rect2i(Vector2i(centre) - Vector2i(8, 14), Vector2i(16, 28)).intersection(Rect2i(Vector2i.ZERO, rendered.get_size()))
		var luminance := 0.0
		for y in range(sample.position.y, sample.end.y):
			for x in range(sample.position.x, sample.end.x):
				var pixel := rendered.get_pixel(x, y)
				luminance += 0.2126 * pixel.r + 0.7152 * pixel.g + 0.0722 * pixel.b
		result.actors[role] = {"sampleRect": [sample.position.x, sample.position.y, sample.size.x, sample.size.y],
			"meanSrgbLuma": luminance / maxi(1, sample.get_area())}
	return result

func inspect_real_night_lighting(renderer: Node3D, host: Node, world: Node3D, gpu_directory: String = "") -> Dictionary:
	# This is the mounted, hash-verified frozen meadow/weather, not a stub. Mirror
	# the actual QHD P -> N order while keeping the optional art phase stationary.
	var weather := world.get_node("LivingWeather")
	check(renderer._lighting_weather == weather and host._weather == weather,
		"actual renderer/Host share the real LivingWeather, not a guessed parent")
	var start_blend: float = weather.night_blend
	var start_clock: float = weather.animation_clock
	var motion: bool = weather.motion_enabled
	weather.set_motion(false)
	if not weather.night_target:
		weather.toggle_time()
	for index in range(34):
		weather.advance_weather(0.1)
		renderer._process(0.1)
	check(weather.night_blend == 1.0 and weather.animation_clock == start_clock,
		"actual P then N reaches night while shared animation clock stays frozen")
	check(renderer._night_factor() == 1.0, "actual renderer reads full-night blend while clock is paused")
	var result := {"weatherPath": str(weather.get_path()), "rendererPath": str(renderer.get_path()),
		"weatherScript": weather.get_script().resource_path, "blend": weather.night_blend,
		"sharedClockPaused": weather.animation_clock == start_clock,
		"physicalLightUnits": ProjectSettings.get_setting("rendering/lights_and_shadows/use_physical_light_units", false),
		"actors": {}, "note": "Actual frozen core + pinned art node values; not GPU illumination proof"}
	for role: String in renderer._actors:
		var actor: Dictionary = renderer._actors[role]
		var fill: OmniLight3D = actor.moon_fill
		check(is_equal_approx(fill.light_energy, renderer.MOON_FILL_NIGHT_ENERGY) and fill.is_visible_in_tree(),
			"actual paused-night actor fill is active: " + role)
		result.actors[role] = {"id": actor.id, "lightEnergy": fill.light_energy,
			"lightVisible": fill.is_visible_in_tree(), "actorLayers": actor.sprite.layers,
			"lightCullMask": fill.light_cull_mask, "position": point_json(fill.position),
			"range": fill.omni_range, "attenuation": fill.omni_attenuation,
			"spriteShaded": actor.sprite.shaded, "spriteModulate": str(actor.sprite.modulate),
			"spritePosition": point_json(actor.sprite.global_position)}
	if not gpu_directory.is_empty():
		# Temporarily freeze the actual local probe world while comparing ONLY
		# optional actor-light settings. No production/staged file is changed.
		var world_processing := world.is_processing()
		world.set_process(false)
		weather.set_process(false)
		renderer.set_process(false)
		var state: Dictionary = renderer._snapshot.duplicate(true)
		state.mode = "daily_complete"
		renderer.apply_snapshot(state)
		renderer._motion_clock = 0.0
		renderer._update_actors()
		# The actual night transition invalidates the accepted reflection probe;
		# its six-face GPU refresh and new shadow maps span rendered frames. Let
		# those settle BEFORE the first A/B case, retaining the strict return check.
		for frame in range(32):
			await process_frame
			await RenderingServer.frame_post_draw
		var captures: Array = []
		for variant: Dictionary in [{"name": "night-current", "energy": renderer.MOON_FILL_NIGHT_ENERGY, "decay": renderer.MOON_FILL_ATTENUATION},
			{"name": "night-v157-control", "energy": 1.1, "decay": 0.75},
			{"name": "night-off", "energy": 0.0, "decay": 0.75},
			{"name": "night-current-return", "energy": renderer.MOON_FILL_NIGHT_ENERGY, "decay": renderer.MOON_FILL_ATTENUATION}]:
			for actor: Dictionary in renderer._actors.values():
				actor.moon_fill.light_energy = variant.energy
				actor.moon_fill.omni_attenuation = variant.decay
				actor.moon_fill.visible = variant.energy > 0.0
			captures.append(await capture_actual_lighting(world, gpu_directory, variant.name))
		for actor: Dictionary in renderer._actors.values():
			actor.moon_fill.omni_attenuation = renderer.MOON_FILL_ATTENUATION
		renderer._sync_actor_lighting()
		result["gpuCaptures"] = captures
		for role: String in renderer._actors:
			var current_luma: float = captures[0].actors[role].meanSrgbLuma
			var old_luma: float = captures[1].actors[role].meanSrgbLuma
			check(current_luma > old_luma * 1.25, "real GPU body pixels visibly brighten relative to v157: " + role)
			check(absf(current_luma - float(captures[3].actors[role].meanSrgbLuma)) < 1.0 / 255.0,
				"real GPU fill returns identically after off/on: " + role)
		result.note = "Actual native OpenGL + source-byte-exact actors; actual saved texture dimensions, NOT Web QHD acceptance"
		world.set_process(world_processing)
		weather.set_process(true)
	weather.toggle_time()
	for index in range(34):
		weather.advance_weather(0.1)
		renderer._process(0.1)
	check(weather.night_blend == start_blend and weather.animation_clock == start_clock,
		"actual return-to-day does not advance the paused animation clock")
	weather.set_motion(motion)
	return result

func inspect_public_modes(renderer: Node3D, art: Dictionary) -> Array:
	# Exercise the renderer against the same public guest modes as the bridge,
	# without a parent app, account state or another resource-pack mount.
	var original_roots := {}
	var original_frames := {}
	for role: String in renderer._actors:
		original_roots[role] = renderer._actors[role].root.get_instance_id()
		original_frames[role] = renderer._actors[role].frames[0].get_instance_id()
	var snapshot := {"mode": "demo", "heroAssetId": art.selectedAssetIds.hero, "petAssetId": art.selectedAssetIds.pet,
		"bossAssetId": art.selectedAssetIds.boss, "elapsed": 0.0, "duration": 0.0, "roundId": ""}
	var rows: Array = []
	for mode: String in ["demo", "unavailable", "waiting", "demo"]:
		snapshot.mode = mode
		check(renderer.apply_snapshot(snapshot), "actual public mode accepted: " + mode)
		await process_frame
		await process_frame
		var status: Dictionary = renderer.get_presentation_status()
		var expected_status := "ready" if mode == "demo" else ("waiting_for_state" if mode == "waiting" else "unavailable")
		check(status.mode == mode and status.status == expected_status, "actual public mode reports after frame boundary: " + mode)
		var visible_count := 0
		for role: String in renderer._actors:
			var actor: Dictionary = renderer._actors[role]
			check(actor.root.get_instance_id() == original_roots[role] \
				and actor.frames[0].get_instance_id() == original_frames[role], "same-ID mode change retains actor and decoded art: " + role)
			check(actor.root.visible == (mode == "demo"), "actual public mode controls visibility: " + mode + "/" + role)
			visible_count += int(actor.root.visible)
		check(PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"]),
			"mode change keeps exactly the trio and existing FX/HUD, no substitute actors or world children")
		rows.append({"mode": mode, "status": status.status, "visibleActors": visible_count,
			"sameActorAndFrameInstances": true})
	# Native demo is explicitly non-authoritative and may outlive the state TTL.
	# This does NOT claim the separate JS pre-delivery TTL is exempt as well.
	renderer._received_msec -= 16000
	var received_before: int = renderer._received_msec
	check(renderer._age_seconds() > renderer.STALE_SECONDS, "actual demo has deliberately exceeded native state TTL")
	check(renderer.assets_available([art.selectedAssetIds.hero, art.selectedAssetIds.pet, art.selectedAssetIds.boss]),
		"already-mounted art remains usable for old non-authoritative native demo")
	renderer._process(1.0 / 60.0)
	check(renderer._received_msec == received_before and renderer.get_presentation_status().status == "ready",
		"native demo neither becomes stale nor refreshes received age on cached art notice")
	for role: String in renderer._actors:
		check(renderer._actors[role].root.visible, "native demo still visible beyond state TTL: " + role)
	for expected: Dictionary in art.packedActors:
		check(FileAccess.get_sha256(expected.asset.atlas) == expected.sourcePngSha256,
			"actual PNG remains byte-exact after public mode transitions: " + str(expected.asset.id))
	return rows

func audit_visible_rect(camera: Camera3D, world: Node3D, foot: Vector3, spec: Dictionary, bounds: Array, slot: int, lift: float) -> Rect2:
	# Conservative visible-alpha AABB in the actual frozen camera projection.
	# This is a numeric placement diagnostic, NEVER a screenshot/GPU substitute.
	var anchor: Array = spec.frameAnchors[slot] if spec.has("frameAnchors") else spec.anchor
	var pixel_size: float = float(spec.worldHeight) * Presentation._display_scale(spec) / float(spec.frameSize[1])
	var right := Vector3(camera.global_basis.x.x, 0, camera.global_basis.x.z).normalized()
	var base := world.to_global(foot + Vector3.UP * lift)
	var result := Rect2()
	var first := true
	for x: float in [float(bounds[0]), float(bounds[2])]:
		for y: float in [float(bounds[1]), float(bounds[3])]:
			var horizontal := (x - float(anchor[0])) * pixel_size * (-1.0 if spec.role == "boss" else 1.0)
			var point := camera.unproject_position(base + right * horizontal + Vector3.UP * (float(anchor[1]) - y) * pixel_size)
			result = Rect2(point, Vector2.ZERO) if first else result.expand(point)
			first = false
	return result

func audit_gap(left: Rect2, right: Rect2) -> float:
	return maxf(maxf(left.position.x - right.end.x, right.position.x - left.end.x),
		maxf(left.position.y - right.end.y, right.position.y - left.end.y))

func inspect_flying_stations(renderer: Node3D, host: Node, world: Node3D, audit: Dictionary) -> Dictionary:
	var camera := world.get_node("Camera3D") as Camera3D
	var viewport_size: Vector2 = camera.get_viewport().get_visible_rect().size
	var scale_to_1440 := 1440.0 / viewport_size.y
	var heroes: Array = []
	var pets: Array = []
	var boss: Dictionary = {}
	for row: Dictionary in audit.actors:
		if row.asset.role == "hero":
			heroes.append(row)
		elif row.asset.id in ["pet_owl", "pet_finch", "pet_dragon"]:
			pets.append(row)
		elif row.asset.role == "boss":
			boss = row
	check(heroes.size() == 6 and pets.size() == 3 and not boss.is_empty(), "actual public six heroes and three flying pets for silhouette audit")
	if heroes.is_empty() or pets.is_empty() or boss.is_empty():
		return {}
	check(renderer.apply_snapshot({"mode": "demo", "heroAssetId": heroes[0].asset.id, "petAssetId": pets[0].asset.id,
		"bossAssetId": boss.asset.id, "elapsed": 0.0, "duration": 0.0, "roundId": ""}), "geometry probe uses a valid public demo, never reward authority")
	var ground_pets := {}
	for row: Dictionary in audit.actors:
		var spec: Dictionary = row.asset
		if not spec.id in ["pet_deer", "pet_fox", "pet_rabbit"]:
			continue
		var station: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS.pet
		var finish := station + station.direction_to(renderer.ARENA_CENTER + renderer.STATIONS.boss) * 0.58
		var radius: float = float(spec.shadowRadius) * Presentation._display_scale(spec)
		var safe: bool = renderer._safe_segment(station, finish, radius)
		check(station.is_equal_approx(Vector2(3.65, -9.90)) and safe, "actual ground pet station and scaled footprint/lunge safe: " + spec.id)
		ground_pets[spec.id] = {"safe": safe, "shadowRadius": radius, "foot": point_json(host.sample_ground(station))}
	# The pose/bob joint cycle repeats after FOUR 5.2-second cycles (idle/walk
	# slots advance by two per cycle). Cache unchanged hero/Boss projections once
	# for all candidates rather than repeating expensive real-terrain ray tests.
	var references: Array = []
	var hero_station: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS.hero
	var boss_station: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS.boss
	for hero: Dictionary in heroes:
		check(renderer._safe_segment(hero_station, hero_station + hero_station.direction_to(boss_station) * 0.58,
			float(hero.asset.shadowRadius) * Presentation._display_scale(hero.asset)), "actual scaled hero footprint/lunge safe: " + hero.asset.id)
	check(renderer._safe_segment(boss_station, boss_station + boss_station.direction_to(hero_station) * 0.42,
		float(boss.asset.shadowRadius) * Presentation._display_scale(boss.asset)), "actual scaled Boss footprint/lunge safe")
	for index in range(417):
		renderer._motion_clock = float(index) * 0.05
		var hero_pose: Dictionary = renderer._pose("hero")
		var hero_slot: int = hero_pose.row * 8 + hero_pose.frame
		var hero_foot: Vector3 = host.sample_ground(hero_station + hero_station.direction_to(boss_station) * 0.58 * float(hero_pose.travel))
		var hero_rects := {}
		for hero: Dictionary in heroes:
			hero_rects[hero.asset.id] = audit_visible_rect(camera, world, hero_foot, hero.asset, hero.visibleFrameBounds[hero_slot], hero_slot, 0)
		var boss_pose: Dictionary = renderer._pose("boss")
		var boss_slot: int = boss_pose.row * 8 + boss_pose.frame
		var boss_foot: Vector3 = host.sample_ground(boss_station + boss_station.direction_to(hero_station) * 0.42 * float(boss_pose.travel))
		references.append({"phase": renderer._motion_clock, "petPose": renderer._pose("pet"), "heroSlot": hero_slot,
			"heroRects": hero_rects, "bossRect": audit_visible_rect(camera, world, boss_foot, boss.asset, boss.visibleFrameBounds[boss_slot], boss_slot, 0),
			"lift": renderer.HOVER_HEIGHT + sin(renderer._motion_clock * TAU / renderer.HOVER_PERIOD) * renderer.HOVER_BOB})
	var candidates := [Vector2(-1.35, 2.10), Vector2(-2.55, -1.75), Vector2(-2.70, -2.60), Vector2(-2.10, -3.05), Vector2(-1.70, -3.35)]
	if not renderer.HOVER_PET_STATION in candidates:
		candidates.append(renderer.HOVER_PET_STATION)
	var results: Array = []
	var chosen: Dictionary = {}
	for local: Vector2 in candidates:
		var station: Vector2 = renderer.ARENA_CENTER + local
		var direction := station.direction_to(boss_station)
		var finish := station + direction * 0.58
		var candidate := {"arenaLocalStation": [local.x, local.y], "foot": point_json(host.sample_ground(station)),
			"lungeFoot": point_json(host.sample_ground(finish)), "pets": {}, "safe": true, "minHeroGapAtHeight1440": INF,
			"minBossGapAtHeight1440": INF}
		for pet: Dictionary in pets:
			var spec: Dictionary = pet.asset
			var radius: float = float(spec.shadowRadius) * Presentation._display_scale(spec)
			var safe: bool = renderer._safe_segment(station, finish, radius)
			var min_hero := INF
			var min_boss := INF
			var closest := {}
			for reference: Dictionary in references:
				var pose: Dictionary = reference.petPose
				var pet_slot: int = pose.row * 8 + pose.frame
				var point := station + direction * 0.58 * float(pose.travel)
				var foot: Vector3 = host.sample_ground(point)
				safe = safe and renderer._safe_point(point, radius)
				var pet_rect := audit_visible_rect(camera, world, foot, spec, pet.visibleFrameBounds[pet_slot], pet_slot, float(reference.lift))
				for hero_id: String in reference.heroRects:
					var gap := audit_gap(pet_rect, reference.heroRects[hero_id]) * scale_to_1440
					if gap < min_hero:
						min_hero = gap
						closest = {"heroAssetId": hero_id, "phaseSeconds": reference.phase, "petSlot": pet_slot, "heroSlot": reference.heroSlot}
				min_boss = minf(min_boss, audit_gap(pet_rect, reference.bossRect) * scale_to_1440)
			candidate.pets[spec.id] = {"safe": safe, "shadowRadius": radius,
				"arenaBoundaryMarginM": renderer.ARENA_RADIUS - maxf(local.length(), finish.distance_to(renderer.ARENA_CENTER)) - radius,
				"minHeroGapAtHeight1440": min_hero, "minBossGapAtHeight1440": min_boss, "closestHero": closest}
			candidate.safe = candidate.safe and safe
			candidate.minHeroGapAtHeight1440 = minf(candidate.minHeroGapAtHeight1440, min_hero)
			candidate.minBossGapAtHeight1440 = minf(candidate.minBossGapAtHeight1440, min_boss)
		results.append(candidate)
		if local.is_equal_approx(renderer.HOVER_PET_STATION):
			chosen = candidate
	check(not chosen.is_empty() and chosen.safe, "chosen flying station has real terrain support, all three footprints and full lunge/return paths")
	check(not chosen.is_empty() and chosen.minHeroGapAtHeight1440 >= 4.0 and chosen.minBossGapAtHeight1440 >= 4.0,
		"chosen flying station separates visible AABBs from all six heroes and Boss throughout sampled action")
	return {"manifestSha256": audit.manifestSha256, "rendererSha256": FileAccess.get_sha256(get_script().resource_path.get_base_dir().path_join("../scripts/camp_presentation.gd")),
		"cameraTransform": str(camera.global_transform), "cameraFov": camera.fov, "viewportSize": [viewport_size.x, viewport_size.y],
		"phaseSamplesPerPet": references.size(), "groundPetsUnchanged": ground_pets, "candidates": results, "chosen": chosen,
		"note": "Signed conservative alpha>=32 AABB gap; <=0 is overlap. Numeric projection normalized to height1440, NOT a capture. Actual core only; main owns deferred-detail/Web/QHD acceptance."}

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() != 1:
		quit(1)
		return
	var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(arguments[0]))
	var cache_path := "res://.godot/global_script_class_cache.cfg"
	check(FileAccess.get_sha256(cache_path) == config.globalScriptCacheSha256, "exact frozen global class cache exists before real core mount")
	var cache := ConfigFile.new()
	check(cache.load(cache_path) == OK, "actual wrapper startup class ConfigFile reads without fallback")
	var script_classes: Variant = cache.get_value("", "list", null)
	check(script_classes is Array and script_classes.is_empty() and ProjectSettings.get_global_class_list().is_empty(),
		"actual startup class cache explicitly empty and engine-readable")
	check(FileAccess.get_sha256("res://project.binary") == config.projectBinarySha256, "frozen accepted bootstrap project.binary")
	check(FileAccess.get_sha256(config.selectedPack) == config.selectedPackSha256, "ACTUAL pinned core15 input: " + str(config.sourceVariant))
	check(ProjectSettings.load_resource_pack(config.selectedPack, false), "actual selected pack mounted replace_files=false")
	ProjectSettings.set_setting("application/run/main_scene", "res://scenes/main.tscn")
	var host_code: Script = load("res://camp_bootstrap/camp_pack_host.gd")
	var host: Node = host_code.new()
	var art: Dictionary = config.get("presentation", {})
	check(host.configure({"version": 1, "optionalPack": art.get("runtime"), "actorShards": art.get("actorShards", [])}), "ordinary root host configured from fixed pins")
	root.add_child(host)
	check(not host.mark_core_presented(), "no scene means no core acceptance")
	var old := Node.new()
	root.add_child(old)
	current_scene = old
	var previous: WeakRef = weakref(old)
	var start_usec := Time.get_ticks_usec()
	check(change_scene_to_file("res://scenes/main.tscn") == OK, "load real frozen main scene, not a test world")
	await process_frame
	await process_frame
	var setup_usec := Time.get_ticks_usec() - start_usec
	var world := current_scene as Node3D
	check(previous.get_ref() == null, "disposable startup scene actually freed")
	check(world != null and world.name == "MeadowPlain" and world.scene_file_path == "res://scenes/main.tscn", "actual main scene identity")
	if world == null:
		quit(1)
		return
	var wildlife := world.get_node_or_null("LivingWildlife")
	var weather := world.get_node_or_null("LivingWeather")
	check(wildlife != null and weather != null, "real live wildlife/weather nodes exist")
	if wildlife == null or weather == null:
		quit(1)
		return
	var ground: Variant = wildlife.get("ground_surface")
	var stone: Variant = wildlife.get("rock_surface")
	var obstacles: Variant = wildlife.get("obstacles")
	var clock_value: Variant = weather.get("animation_clock")
	check(ground is TriangleMesh and stone is TriangleMesh, "actual core15 ground/rock TriangleMesh instances")
	check(obstacles is Array and obstacles.is_typed() and obstacles.get_typed_builtin() == TYPE_VECTOR3,
		"actual typed Array[Vector3] satisfies Host Array condition")
	check((clock_value is int or clock_value is float) and is_finite(float(clock_value)), "actual finite shared animation clock")
	check(host.get_parent() == root and host.mark_core_presented(), "unmodified Host accepts real core15 conditions")
	check(not world.has_node("CampPackHost") and not world.has_node("CampPresentation"), "Host alone adds no MeadowPlain children")
	check(FileAccess.get_sha256("res://project.binary") == config.projectBinarySha256, "real restore retained accepted wrapper settings")
	check(FileAccess.get_sha256(config.renderer) == config.rendererSha256, "reviewed renderer source only")
	var renderer: Node3D
	var art_report: Dictionary = {}
	if art.is_empty():
		var renderer_code: Script = load(config.renderer)
		renderer = renderer_code.new()
		world.add_child(renderer)
		var descriptors: Array = []
		for row: Dictionary in config.get("placement", {}).get("actors", []):
			descriptors.append(row.asset)
		check(renderer.setup(world, {"version": 1, "assets": descriptors}, host.sample_ground, host.permitted_ground, host.animation_clock),
			"real-world renderer adapters configure after core; no preview blocks or fixture art")
	else:
		renderer = await mount_real_trio(host, world, art, str(arguments[0]).get_base_dir())
		if renderer == null:
			quit(1)
			return
		art_report = inspect_real_trio(renderer, host, art)
		art_report["publicModeTransitions"] = await inspect_public_modes(renderer, art)
		art_report["finalMode"] = renderer.get_presentation_status().mode
		if config.has("detailDirectory"):
			art_report["actualDetailContinuity"] = await inspect_actual_details(renderer, host, world, config.detailDirectory)
		art_report["actualNightLighting"] = await inspect_real_night_lighting(renderer, host, world,
			str(arguments[0]).get_base_dir() if config.get("gpuLightingProbe", false) else "")
	var stations := {}
	for role: String in ["hero", "pet", "boss"]:
		var station: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS[role]
		var opponent: Vector2 = renderer.ARENA_CENTER + renderer.STATIONS["hero" if role == "boss" else "boss"]
		var reach := 0.42 if role == "boss" else 0.58
		var radius: float = float(renderer._actors[role].radius) if renderer._actors.has(role) else (0.95 if role == "boss" else (0.32 if role == "hero" else 0.38))
		var finish := station + station.direction_to(opponent) * reach
		var foot: Vector3 = host.sample_ground(station)
		var finish_foot: Vector3 = host.sample_ground(finish)
		var safe: bool = renderer._safe_segment(station, finish, radius)
		check(foot.is_finite() and finish_foot.is_finite(), role + " actual ground ray hits")
		check(safe, role + " actual full footprint and entire lunge segment safe")
		stations[role] = {"foot": point_json(foot), "lungeFoot": point_json(finish_foot), "radius": radius,
			"safe": safe, "worldTerrainNormal": point_json(world.terrain_normal(station.x, station.y))}
	check(PresentationAssertions.exact_presentation_children(renderer, [] if art.is_empty() else ["hero", "pet", "boss"]),
		"only requested actual artwork plus owned FX/HUD; zero substituted actors when art was not requested")
	check(FileAccess.get_sha256(cache_path) == config.globalScriptCacheSha256, "real core and art mounts leave startup class cache exact")
	var report := {"status": "PASS" if failures.is_empty() else "FAIL", "checks": checks, "failures": failures,
		"globalScriptCacheSha256": config.globalScriptCacheSha256,
		"sourceVariant": config.sourceVariant, "targetWebPackSha256": config.targetWebPackSha256,
		"selectedPackSha256": config.selectedPackSha256, "projectBinarySha256": config.projectBinarySha256,
		"actualScene": world.scene_file_path, "sceneChildrenBeforeRenderer": world.get_child_count() - 1,
		"groundType": ground.get_class(), "rockType": stone.get_class(), "obstacleCount": obstacles.size(),
		"obstaclesTypedBuiltin": obstacles.get_typed_builtin(), "animationClock": clock_value,
		"nativeSceneTransitionAndTwoFramesMs": setup_usec / 1000.0, "stations": stations,
		"limits": ["Real core15 runtime, no synthetic meadow",
			"Native OpenGL diagnostic, NOT Web or ten-second proof" if config.get("gpuLightingProbe", false) else "Native/headless, NOT Web/GPU or ten-second proof",
			"All twelve pinned native detail chunks applied" if config.has("detailDirectory") else "Core only; no deferred detail chunks applied",
			"No actual art or visual acceptance in this probe" if art.is_empty() else
			("Actual pinned trio with matched GPU lighting A/B; main owns Web visual acceptance" if config.get("gpuLightingProbe", false) else "Actual pinned trio textures/geometry, no GPU or visual acceptance")]}
	if not art.is_empty():
		report["presentation"] = art_report
	if config.has("placement"):
		report["flyingStationAudit"] = inspect_flying_stations(renderer, host, world, config.placement)
		report.status = "PASS" if failures.is_empty() else "FAIL"
		report.checks = checks
	var destination: String = str(arguments[0]).get_base_dir().path_join("actual-core-result.json")
	check(not FileAccess.file_exists(destination), "new result path only")
	if not FileAccess.file_exists(destination):
		var output := FileAccess.open(destination, FileAccess.WRITE)
		output.store_string(JSON.stringify(report, "\t") + "\n")
		output.close()
	print("CAMP_ACTUAL_CORE_TEST: " + JSON.stringify(report))
	world.free()
	host.free()
	await process_frame
	quit(0 if failures.is_empty() else 1)
