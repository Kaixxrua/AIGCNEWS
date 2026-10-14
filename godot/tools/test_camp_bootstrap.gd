extends SceneTree
## Isolated native tests: real sealed settings/PCKs, shallow test scenes only.
## Synthetic fixture sprites never become public artwork. No large export.

const PresentationAssertions := preload("test_camp_presentation.gd")

class TestWorld extends Node3D:
	func river_center(_z: float) -> float:
		return 40.0
	func river_half_width(_z: float) -> float:
		return 2.0
	func terrain_normal(_x: float, _z: float) -> Vector3:
		return Vector3.UP

class TestWildlife extends Node:
	var ground_surface := TriangleMesh.new()
	var rock_surface := TriangleMesh.new()
	var obstacles: Array[Vector3] = []
	func _init() -> void:
		var plane := PlaneMesh.new()
		plane.size = Vector2(200, 200)
		ground_surface = plane.generate_triangle_mesh()

class TestWeather extends Node:
	var animation_clock := 0.0

var checks := 0
var failures := 0
var replies: Array = []

func _initialize() -> void:
	if OS.get_cmdline_user_args() == PackedStringArray(["cache-missing-control"]):
		var cache := ConfigFile.new()
		var path := "res://.godot/global_script_class_cache.cfg"
		var error := cache.load(path)
		var absent := not FileAccess.file_exists(path) and error != OK
		print("CAMP_GLOBAL_CACHE_NEGATIVE_CONTROL: %s " % ("PASS" if absent else "FAIL") \
			+ JSON.stringify({"fileAbsent": not FileAccess.file_exists(path), "configLoadError": error,
			"note": "Editor native hides export-only startup log; ConfigFile still detects missing required metadata"}))
		quit(0 if absent else 1)
		return
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("CAMP_BOOTSTRAP_FAIL: " + label)

func reply(request_id: int, success: bool, code: String) -> void:
	replies.append([request_id, success, code])

func run() -> void:
	var arguments := OS.get_cmdline_user_args()
	check(arguments.size() == 1, "small native test config")
	if arguments.size() != 1:
		quit(1)
		return
	var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(arguments[0]))
	var cache_path := "res://.godot/global_script_class_cache.cfg"
	check(FileAccess.file_exists(cache_path), "global class cache exists before selected pack mount")
	check(FileAccess.get_sha256(cache_path) == config.globalScriptCacheSha256, "startup class cache uses exact frozen bytes")
	var cache := ConfigFile.new()
	check(cache.load(cache_path) == OK, "startup ConfigFile load succeeds, not just an empty API fallback")
	var script_classes: Variant = cache.get_value("", "list", null)
	check(script_classes is Array and script_classes.is_empty(), "cache contains an explicit empty class list")
	check(ProjectSettings.get_global_class_list().is_empty(), "engine consumes the explicit empty startup class list")
	var initial_hash := FileAccess.get_sha256("res://project.binary")
	check(initial_hash == config.bootProjectSha256, "initial wrapper settings bytes")
	check(ProjectSettings.get_setting("application/run/main_scene") == "res://progressive/boot.tscn", "initial entry only")
	check(FileAccess.get_sha256(config.selectedPack) == config.selectedPackSha256, "sealed selected pack actual hash")
	check(ProjectSettings.load_resource_pack(config.selectedPack, false), "mount ACTUAL frozen selected pack")
	check(FileAccess.get_sha256("res://project.binary") == initial_hash, "replace_files false retains wrapper settings file")
	ProjectSettings.set_setting("application/run/main_scene", "res://scenes/main.tscn")
	for key: String in config.settings:
		var expected: Variant = bytes_to_var(str(config.settings[key]).hex_decode())
		check(var_to_bytes(ProjectSettings.get_setting(key, null)) == var_to_bytes(expected), "exact effective setting " + key)
	var code: Script = load("res://camp_bootstrap/camp_pack_host.gd")
	check(code != null and code.can_instantiate(), "actual uncompiled Host source parses")
	if code == null or not code.can_instantiate():
		quit(1)
		return
	var host: Node = code.new()
	check(not host.configure({"version": true, "optionalPack": config.optionalPack}), "bool version rejected")
	check(not host.configure({"version": 1, "optionalPack": config.optionalPack, "token": "forbidden"}), "unknown config rejected")
	var bad: Dictionary = config.optionalPack.duplicate()
	bad.file = "../../other.pck"
	check(not host.configure({"version": 1, "optionalPack": bad}), "arbitrary PCK path rejected")
	check(host.configure({"version": 1, "optionalPack": config.optionalPack}), "one-time pinned configure")
	check(not host.configure({"version": 1, "optionalPack": null}), "cannot replace pin")
	root.add_child(host)
	host.mount_completed.connect(reply)
	var callable_handle := Callable(host, "mark_core_presented")
	check(not host.mark_core_presented(), "no readiness before actual scene")
	var path: String = "/" + str(config.optionalPack.file)
	host.mount_presentation(1, path, config.optionalPack.sha256)
	check(replies.back() == [1, false, "not_ready"], "mount before core refused")
	var boot := Node.new()
	root.add_child(boot)
	current_scene = boot
	var old_reference: WeakRef = weakref(boot)
	check(change_scene_to_file("res://camp_bootstrap/probe-scene.tscn") == OK, "real shallow scene transition")
	await process_frame
	await process_frame
	check(old_reference.get_ref() == null and callable_handle.is_valid(), "boot really freed; retained Host callable lives")
	check(root.get_node_or_null("CampPackHost") == host and host.get_parent() == root, "ordinary persistent root sibling")
	var camera := Camera3D.new()
	camera.name = "Camera3D"
	current_scene.add_child(camera)
	var edge := Node3D.new()
	edge.name = "MeadowEdgeGrowth"
	current_scene.add_child(edge)
	check(current_scene.get_child_count() == 2 and edge.get_child_count() == 0, "no extra MeadowPlain children before core15")
	var context_matches: Variant = null
	if config.tier == "lite":
		var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://progressive/static-core/manifest.json"))
		check(initial_hash in manifest.dependencies["res://project.binary"], "ACTUAL frozen core15 dependency accepts wrapper")
		var settings := {}
		for key: String in ["application/run/main_scene", "display/window/size/viewport_width",
				"display/window/size/viewport_height", "display/window/stretch/mode", "display/window/stretch/aspect",
				"rendering/renderer/rendering_method", "rendering/scaling_3d/scale", "rendering/scaling_3d/mode",
				"shader_globals/meadow_clock", "shader_globals/meadow_night"]:
			settings[key] = ProjectSettings.get_setting(key, null)
		var context_bytes := var_to_bytes([str(current_scene.name), current_scene.transform,
			current_scene.get_viewport().get_visible_rect(), settings])
		context_matches = context_bytes.hex_encode() == manifest.contextHex
		check(context_matches, "ACTUAL core15 context matches with real Host sibling")
	check(not host.mark_core_presented(), "matching name alone is NOT a ready scene")
	current_scene.free()
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
	check(host.mark_core_presented(), "ready tiny scene with real samplers accepted")
	check(host.mark_core_presented(), "core gate is idempotent on same scene")
	check(world.get_child_count() == 2, "core acceptance itself adds no scene children")
	check(host.sample_ground(Vector2(5, -12)).is_equal_approx(Vector3(5, 0.018, -12)), "reuses real TriangleMesh ground")
	check(host.permitted_ground(Vector2(5, -12)), "arena allowed, wildlife no-combat exclusion NOT reused")
	check(not host.permitted_ground(Vector2(40, -12)), "river remains forbidden")
	wildlife.obstacles.append(Vector3(5, -12, 0.5))
	check(not host.permitted_ground(Vector2(5, -12)), "existing prop obstacles honored")
	wildlife.obstacles.clear()
	host.mount_presentation(2, "/arbitrary.pck", config.optionalPack.sha256)
	check(replies.back() == [2, false, "pin_mismatch"], "native exact optional path pin")
	host.mount_presentation(3, path, "0".repeat(64))
	check(replies.back() == [3, false, "pin_mismatch"], "native exact hash pin")
	check(not host._attempted and world.get_child_count() == 2, "rejected paths do not mount or mutate scene")
	# Only a temporary application data folder can receive this synthetic file.
	var stage: String = str(config.testArtPath).get_base_dir().simplify_path()
	var user_path := OS.get_user_data_dir().simplify_path()
	check(user_path.begins_with(stage + "/"), "native user data stays inside isolated fixture directory")
	if not user_path.begins_with(stage + "/"):
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(user_path)
	var blob := FileAccess.get_file_as_bytes(config.testArtPath)
	var destination := FileAccess.open("user://" + str(config.optionalPack.file), FileAccess.WRITE)
	destination.store_buffer(PackedByteArray([0]))
	destination.close()
	host.mount_presentation(6, path, config.optionalPack.sha256)
	check(replies.back() == [6, false, "pin_mismatch"] and not host._attempted, "actual wrong-size file rejected before mount")
	destination = FileAccess.open("user://" + str(config.optionalPack.file), FileAccess.WRITE)
	var corrupt := blob.duplicate()
	corrupt[0] = 0
	destination.store_buffer(corrupt)
	destination.close()
	host.mount_presentation(7, path, config.optionalPack.sha256)
	check(replies.back() == [7, false, "pin_mismatch"] and not host._attempted, "actual wrong digest rejected before mount")
	destination = FileAccess.open("user://" + str(config.optionalPack.file), FileAccess.WRITE)
	destination.store_buffer(blob)
	destination.close()
	host.mount_presentation(4, path, config.optionalPack.sha256)
	await process_frame
	await process_frame
	check(replies.back() == [4, true, "applied"], "actual pinned optional pack mount acknowledged after frame")
	check(world.get_child_count() == 3 and world.has_node("CampPresentation"), "ONE new post-core presentation child")
	var renderer := world.get_node_or_null("CampPresentation")
	if renderer != null:
		PresentationAssertions.assert_packed_sources(get_script().resource_path.get_base_dir().get_base_dir().path_join("scripts"), check)
		check(renderer.apply_snapshot({"mode": "fighting", "heroAssetId": "hero-test", "petAssetId": "pet-test",
			"bossAssetId": "boss-test", "elapsed": 3.0, "duration": 600.0, "roundId": "public-test-nonce"}), "real renderer accepts display snapshot")
		await process_frame
		await process_frame
		check(renderer.get_presentation_status().status == "ready"
			and PresentationAssertions.exact_presentation_children(renderer, ["hero", "pet", "boss"]),
			"three functional grounded actors plus exactly one owned FX/HUD; no substitute blocks")
		var hp_state := {"mode": "fighting", "heroAssetId": "hero-test", "petAssetId": "pet-test",
			"bossAssetId": "boss-test", "elapsed": 600.0, "duration": 600.0, "roundId": "public-test-nonce",
			"bossHp": 375, "bossMaxHp": 1000}
		check(renderer.apply_snapshot(hp_state) and is_equal_approx(renderer._confirmed_boss_ratio(), 0.375)
			and not renderer._death_active, "selected tier renders confirmed HP rather than legacy elapsed on the same engine")
		hp_state.mode = "defeated"
		hp_state.bossHp = 0
		check(renderer.apply_snapshot(hp_state) and renderer._death_active and renderer._snapshot == hp_state,
			"selected tier accepts explicit defeat without constructing a new scene or settlement state")
	host.mount_presentation(5, path, config.optionalPack.sha256)
	check(replies.back() == [5, false, "reload_required"] and world.get_child_count() == 3, "duplicate native mount cannot create duplicate actor tree")
	check(FileAccess.get_sha256("res://project.binary") == initial_hash, "optional pack never overrides settings")
	check(FileAccess.get_sha256(cache_path) == config.globalScriptCacheSha256, "scene and optional mounts retain matching global class cache")
	check(FileAccess.get_sha256(config.selectedPack) == config.selectedPackSha256, "sealed selected pack unchanged at end")
	world.free()
	check(not host.mark_core_presented() and not host._live(), "scene replacement invalidates old optional renderer")
	host.free()
	await process_frame
	print("CAMP_BOOTSTRAP_TEST: %s (%d checks) " % ["PASS" if failures == 0 else "FAIL", checks] + JSON.stringify({
		"tier": config.tier, "failures": failures, "core15Context": context_matches, "projectBinarySha256": initial_hash}))
	quit(0 if failures == 0 else 1)
