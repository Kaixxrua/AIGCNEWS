extends "test_camp_bootstrap.gd"
## Actual small PCK mounts and real Sprite3D swaps in an isolated TEST world.
## Inherits only the existing tiny test world/check helpers, not a main-scene
## patch. Source fixture PNGs are synthetic test data, never delivered artwork.

var shard_request: Dictionary = {}

func pin_for(id: String) -> Dictionary:
	for shard: Dictionary in shard_request.actorShards:
		if shard.assetIds.has(id):
			return shard.pack
	return {}

func copy_fixture(pin: Dictionary) -> void:
	var user_path := OS.get_user_data_dir().simplify_path()
	var stage: String = str(shard_request.directory).simplify_path()
	check(user_path.begins_with(stage + "/"), "synthetic PCK copy remains inside isolated native directory")
	if not user_path.begins_with(stage + "/"):
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(user_path)
	var path: String = stage.path_join(pin.file)
	check(FileAccess.get_sha256(path) == pin.sha256, "native fixture input is exact pinned PCK")
	var file := FileAccess.open("user://" + str(pin.file), FileAccess.WRITE)
	file.store_buffer(FileAccess.get_file_as_bytes(path))
	file.close()

func state(hero: String = "hero/first", mode: String = "fighting") -> Dictionary:
	return {"mode": mode, "heroAssetId": hero, "petAssetId": "pet/first", "bossAssetId": "boss/first",
		"elapsed": 12.0, "duration": 600.0, "roundId": "public-shard-probe"}

func mount_one(host: Node, key: String, request_id: int) -> void:
	var pin := pin_for(key)
	copy_fixture(pin)
	host.mount_actor(request_id, "/" + str(pin.file), pin.sha256)
	await process_frame
	await process_frame
	check(replies.back() == [request_id, true, "applied"], "actor shard acknowledged after real mount/frame: " + key)

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	if arguments.size() != 1:
		quit(1)
		return
	shard_request = JSON.parse_string(FileAccess.get_file_as_string(arguments[0]))
	var settings_hash := FileAccess.get_sha256("res://project.binary")
	var code: Script = load("res://camp_bootstrap/camp_pack_host.gd")
	check(code != null and code.can_instantiate(), "production Host with actor pins parses")
	if code == null or not code.can_instantiate():
		quit(1)
		return
	var host: Node = code.new()
	var bad: Array = shard_request.actorShards.duplicate(true)
	bad[1].assetIds = bad[0].assetIds.duplicate()
	check(not host.configure({"version": 1, "optionalPack": shard_request.runtime, "actorShards": bad}), "native duplicate actor-to-shard mapping rejected")
	check(not host.configure({"version": 1, "optionalPack": null, "actorShards": shard_request.actorShards}), "shards cannot bypass a pinned runtime")
	check(host.configure({"version": 1, "optionalPack": shard_request.runtime, "actorShards": shard_request.actorShards}), "immutable native shard catalogue")
	root.add_child(host)
	host.mount_completed.connect(reply)
	var first := pin_for("hero/first")
	host.mount_actor(1, "/" + str(first.file), first.sha256)
	check(replies.back() == [1, false, "not_ready"], "no actor mount before real core")
	var world := TestWorld.new()
	world.name = "MeadowPlain"
	world.scene_file_path = "res://scenes/main.tscn"
	var wildlife := TestWildlife.new()
	wildlife.name = "LivingWildlife"
	world.add_child(wildlife)
	var weather := TestWeather.new()
	weather.name = "LivingWeather"
	world.add_child(weather)
	root.add_child(world)
	current_scene = world
	var world_id := world.get_instance_id()
	check(host.mark_core_presented(), "core accepted with real test samplers")
	check(world.get_child_count() == 2, "Host and core acceptance add zero meadow children")
	host.mount_actor(2, "/" + str(first.file), first.sha256)
	check(replies.back() == [2, false, "not_ready"], "actor mount still waits for runtime")
	copy_fixture(shard_request.runtime)
	host.mount_presentation(3, "/" + str(shard_request.runtime.file), shard_request.runtime.sha256)
	await process_frame
	await process_frame
	check(replies.back() == [3, true, "applied"], "tiny catalogue/renderer runtime mount")
	var renderer := world.get_node_or_null("CampPresentation")
	check(renderer != null, "single persistent renderer exists")
	if renderer == null:
		quit(1)
		return
	var renderer_id := renderer.get_instance_id()
	PresentationAssertions.assert_packed_sources(get_script().resource_path.get_base_dir().get_base_dir().path_join("scripts"), check)
	var effects: Node3D = renderer._effects
	var effect_nodes: Array = []
	for child: Node in effects.get_children():
		effect_nodes.append(child.get_instance_id())
	check(effect_nodes.size() == 3 and effects.get_parent() == renderer, "one renderer-owned three-node skill pool before actor downloads")
	renderer.set_process(false)
	for asset: Dictionary in renderer.read_catalogue().assets:
		check(not FileAccess.file_exists(asset.atlas), "runtime contains no actor PNG payload: " + str(asset.id))
	check(renderer.apply_snapshot(state()), "state accepted immediately before art download")
	await process_frame
	await process_frame
	check(PresentationAssertions.exact_presentation_children(renderer, []) and renderer._missing.size() == 3,
		"zero placeholder actors for missing initial trio; only post-core FX/HUD")
	check(renderer.apply_snapshot(state("hero/second")), "new selection does not wait for obsolete hero art")
	renderer._received_msec = Time.get_ticks_msec() - 3000
	var age_stamp: int = renderer._received_msec
	var phase: float = renderer._motion_clock
	await mount_one(host, "hero/first", 4)
	check(PresentationAssertions.exact_presentation_children(renderer, []), "late old hero shard never creates obsolete actor")
	check(renderer._received_msec == age_stamp and renderer._motion_clock == phase, "late shard does not refresh state age or phase")
	await mount_one(host, "hero/second", 5)
	check(PresentationAssertions.exact_presentation_children(renderer, ["hero"]) and renderer._actors.hero.id == "hero/second",
		"only CURRENT hero appears beside the existing FX/HUD")
	check(renderer._received_msec == age_stamp and renderer._motion_clock == phase, "current asset completion does not replay state")
	check(renderer.apply_snapshot(state("hero/second", "paused")), "server pause immediately applied while pet/Boss are missing")
	age_stamp = renderer._received_msec
	await mount_one(host, "pet/first", 6)
	await mount_one(host, "boss/first", 7)
	check(renderer._snapshot.mode == "paused" and renderer._received_msec == age_stamp, "late trio completion cannot resume paused mode")
	check(PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"]) and renderer._status == "ready",
		"all three real sprite actors ready after their shards; same single FX/HUD")
	check(world.get_instance_id() == world_id and renderer.get_instance_id() == renderer_id, "no world or renderer restart across shard mounts")
	var mount_count: int = host._actor_loaded.size()
	check(renderer.apply_snapshot(state()), "switch back to already cached first hero")
	check(renderer._actors.hero.id == "hero/first" and PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"]),
		"cached swap replaces only one modular actor, not the FX/HUD")
	check(host._actor_loaded.size() == mount_count, "cached swap makes no new native pack mount")
	host.mount_actor(8, "/" + str(first.file), first.sha256)
	check(replies.back() == [8, true, "applied"] and host._actor_loaded.size() == mount_count, "duplicate pinned shard mount is idempotent")
	host.mount_actor(9, "/outside.pck", first.sha256)
	check(replies.back() == [9, false, "pin_mismatch"], "arbitrary shard paths never mount")
	var confirmed := state()
	confirmed.mode = "defeated"
	confirmed.bossHp = 0
	confirmed.bossMaxHp = 1000
	check(renderer.apply_snapshot(confirmed), "nine-field confirmed defeated state accepted after real shard mounts")
	renderer._death_clock = 0.8
	renderer._update_actors()
	check(renderer._snapshot.mode == "defeated" and renderer._actors.boss.root.visible
		and renderer._actors.boss.sprite.modulate.a < 1.0, "fresh defeated actors are rendered in the actual death pose, not treated as waiting")
	var death_age: float = renderer._current_death_age()
	var death_phase: float = renderer._motion_clock
	var death_stamp: int = renderer._received_msec
	var death_state: Dictionary = renderer._snapshot.duplicate(true)
	renderer._actors.boss.root.free()
	renderer._actors.erase("boss")
	check(renderer.assets_available(["boss/first"]) and renderer._actors.has("boss"),
		"current mounted Boss artwork can materialize after a defeated snapshot")
	check(renderer._current_death_age() == death_age and renderer._motion_clock == death_phase
		and renderer._received_msec == death_stamp and renderer._snapshot == death_state,
		"late defeated artwork never restarts death, rewinds choreography or refreshes authority")
	check(PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"])
		and renderer._actors.boss.sprite.modulate.a < 1.0 and host._actor_loaded.size() == mount_count,
		"late Boss joins the current fade with the original pool and no duplicate PCK mount")
	renderer._actors.hero.root.free()
	renderer._actors.erase("hero")
	renderer._received_msec = Time.get_ticks_msec() - 16000
	age_stamp = renderer._received_msec
	check(not renderer.assets_available(["hero/first"]), "stale snapshot cannot be revived by asset completion")
	check(not renderer._actors.has("hero") and renderer._received_msec == age_stamp, "no stale actor or artificial fresh timestamp")
	check(FileAccess.get_sha256("res://project.binary") == settings_hash, "all PNG-only shard mounts preserve settings")
	check(world.get_instance_id() == world_id and world.get_child_count() == 3, "world/controllers remain intact")
	var final_effect_nodes: Array = []
	for child: Node in effects.get_children():
		final_effect_nodes.append(child.get_instance_id())
	check(renderer._effects == effects and final_effect_nodes == effect_nodes, "late/outfit/shard traffic cannot allocate another skill pool")
	world.free()
	host.free()
	await process_frame
	print("CAMP_ACTOR_SHARDS_TEST: %s (%d checks)" % ["PASS" if failures == 0 else "FAIL", checks])
	quit(0 if failures == 0 else 1)
