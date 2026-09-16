extends Node
## Root sibling, NOT an autoload and NEVER a pre-core MeadowPlain child.
## The derived wrapper configures this node from its build-time pinned manifest.
## meadowCampMount is a separate, retained callback; meadowBoot.active is unused.
## No eval, parent messages, URLs, accounts, rewards or dynamic resource names.

signal mount_completed(request_id: int, success: bool, code: String)

const TARGET := "res://scenes/main.tscn"
const ENTRY := "res://camp_presentation/camp_presentation.gd"
const CATALOGUE := "res://camp_presentation/manifest.json"
const MAX_PACK := 16 * 1024 * 1024
const MAX_ACTOR_PACK := 9 * 1024 * 1024
const MAX_LIBRARY := 128 * 1024 * 1024

var _configured := false
var _pack: Dictionary = {}
var _actor_shards: Dictionary = {}
var _actor_attempted: Dictionary = {}
var _actor_loaded: Dictionary = {}
var _actor_busy := false
var _runtime_ready := false
var _core := false
var _attempted := false
var _world: Node3D
var _wildlife: Node
var _weather: Node
var _presentation: Node3D
var _web: JavaScriptObject
var _callback: JavaScriptObject

static func _exact(value: Variant, keys: Array) -> bool:
	if not value is Dictionary or value.size() != keys.size():
		return false
	for key: Variant in value:
		if not keys.has(key):
			return false
	return true

static func valid_pack(value: Variant, actor: bool = false) -> bool:
	if not _exact(value, ["file", "bytes", "sha256"]):
		return false
	if not value.sha256 is String or value.sha256.length() != 64 or not value.file is String:
		return false
	for character: String in value.sha256:
		if not character in "0123456789abcdef":
			return false
	if value.file != ("camp-actor-" if actor else "camp-presentation-") + value.sha256.left(12) + ".pck":
		return false
	return (value.bytes is int or value.bytes is float) and is_finite(float(value.bytes)) \
		and value.bytes == floorf(float(value.bytes)) and value.bytes > 0 and value.bytes <= (MAX_ACTOR_PACK if actor else MAX_PACK)

static func _asset_id(value: Variant) -> bool:
	if not value is String or value.is_empty() or value.length() > 64:
		return false
	var parts: PackedStringArray = value.split("/", true)
	if parts.size() > 2:
		return false
	for part: String in parts:
		if part.is_empty() or not part[0] in "abcdefghijklmnopqrstuvwxyz":
			return false
		for character: String in part:
			if not character in "abcdefghijklmnopqrstuvwxyz0123456789_-":
				return false
	return true

func configure(value: Dictionary) -> bool:
	if _configured or is_inside_tree() or not (_exact(value, ["version", "optionalPack"]) or _exact(value, ["version", "optionalPack", "actorShards"])):
		return false
	if not (value.version is int or value.version is float) or value.version != 1:
		return false
	if value.optionalPack != null and not valid_pack(value.optionalPack):
		return false
	var shards: Variant = value.get("actorShards", [])
	if not shards is Array or shards.size() > 64 or (not shards.is_empty() and value.optionalPack == null):
		return false
	var staged := {}
	var identifiers := {}
	var total := 0
	for shard: Variant in shards:
		if not _exact(shard, ["pack", "assetIds"]) or not valid_pack(shard.pack, true):
			return false
		if not shard.assetIds is Array or shard.assetIds.is_empty() or shard.assetIds.size() > 64 or staged.has(shard.pack.file):
			return false
		for id: Variant in shard.assetIds:
			if not _asset_id(id) or identifiers.has(id):
				return false
			identifiers[id] = true
		total += int(shard.pack.bytes)
		staged[shard.pack.file] = shard.duplicate(true)
	if total > MAX_LIBRARY or identifiers.size() > 64:
		return false
	_actor_shards = staged
	_pack = {} if value.optionalPack == null else value.optionalPack.duplicate(true)
	_configured = true
	name = "CampPackHost"
	return true

func _ready() -> void:
	set_process(false)
	if not _configured or get_parent() != get_tree().root:
		_configured = false
		return
	if OS.has_feature("web"):
		_web = JavaScriptBridge.get_interface("meadowCampMount")
		if _web != null:
			_callback = JavaScriptBridge.create_callback(_request)
			if not _web.bind(_callback):
				_callback = null
				_web = null

func _request(arguments: Array) -> void:
	# Only the trusted same-document facade can call this function. The iframe
	# display transport has no path to it. Exit the JS stack before any work.
	if arguments.size() == 1 and arguments[0] is String and arguments[0] == "core_presented":
		_ack_core.call_deferred()
	elif arguments.size() == 4 and arguments[0] is String and arguments[0] in ["mount", "mount_actor"]:
		if not (arguments[1] is int or arguments[1] is float) or not is_finite(float(arguments[1])):
			return
		if arguments[1] != floorf(float(arguments[1])) or arguments[1] < 1 or arguments[1] > 2147483647:
			return
		if arguments[2] is String and arguments[2].length() <= 64 and arguments[3] is String and arguments[3].length() == 64:
			if arguments[0] == "mount_actor":
				mount_actor.call_deferred(int(arguments[1]), arguments[2], arguments[3])
			else:
				mount_presentation.call_deferred(int(arguments[1]), arguments[2], arguments[3])

func _ack_core() -> void:
	var accepted := mark_core_presented()
	if _web != null:
		_web.coreAccepted(accepted, "core_presented" if accepted else "not_ready")

func mark_core_presented() -> bool:
	# This checks the real scene; it does NOT manufacture or replace the owner's
	# scene-ready + engine-start + two-RAF gate, which must call this afterwards.
	if not _configured or not is_inside_tree() or get_parent() != get_tree().root:
		return false
	var scene := get_tree().current_scene
	if not scene is Node3D or scene.name != "MeadowPlain" or scene.scene_file_path != TARGET or not scene.is_node_ready():
		return false
	if _core:
		return is_instance_valid(_world) and _world == scene
	for method: String in ["river_center", "river_half_width", "terrain_normal"]:
		if not scene.has_method(method):
			return false
	var wildlife := scene.get_node_or_null("LivingWildlife")
	var weather := scene.get_node_or_null("LivingWeather")
	if wildlife == null or weather == null or not wildlife.get("ground_surface") is TriangleMesh \
		or not wildlife.get("rock_surface") is TriangleMesh or not wildlife.get("obstacles") is Array:
		return false
	var clock_value: Variant = weather.get("animation_clock")
	if not (clock_value is int or clock_value is float) or not is_finite(float(clock_value)) or clock_value < 0:
		return false
	_world = scene
	_wildlife = wildlife
	_weather = weather
	_core = true
	return true

func _live() -> bool:
	return _configured and _core and is_inside_tree() and is_instance_valid(_world) \
		and is_instance_valid(_wildlife) and is_instance_valid(_weather) and get_tree().current_scene == _world

func mount_presentation(request_id: int, path: String, digest: String) -> void:
	if request_id < 1 or request_id > 2147483647:
		return
	if not _live():
		_finish(request_id, false, "not_ready")
		return
	if _pack.is_empty():
		_finish(request_id, false, "disabled")
		return
	if path != "/" + str(_pack.file) or digest != _pack.sha256:
		_finish(request_id, false, "pin_mismatch")
		return
	if _attempted:
		_finish(request_id, false, "reload_required")
		return
	# Web copyToFS uses the exact virtual root filename. Native tests/tools use
	# Godot's application-specific user directory, never a machine drive root.
	var storage_path := path if OS.has_feature("web") else "user://" + str(_pack.file)
	var file := FileAccess.open(storage_path, FileAccess.READ)
	if file == null or file.get_length() != int(_pack.bytes):
		_finish(request_id, false, "pin_mismatch")
		return
	file.close()
	if FileAccess.get_sha256(storage_path) != _pack.sha256:
		_finish(request_id, false, "pin_mismatch")
		return
	# Builder audits the pinned pack's entire namespace. Runtime also refuses an
	# already occupied namespace, and never enables replacement on mount.
	if FileAccess.file_exists(ENTRY) or FileAccess.file_exists(CATALOGUE) or _world.has_node("CampPresentation"):
		_finish(request_id, false, "namespace_conflict")
		return
	_attempted = true
	if not ProjectSettings.load_resource_pack(storage_path, false):
		_finish(request_id, false, "reload_required")
		return
	var code: Script = load(ENTRY)
	if code == null or not code.can_instantiate():
		_finish(request_id, false, "reload_required")
		return
	var instance: Variant = code.new()
	if not instance is Node3D:
		if instance is Node:
			instance.free()
		_finish(request_id, false, "reload_required")
		return
	_presentation = instance
	_world.add_child(_presentation)
	if not _presentation.setup(_world, _presentation.read_catalogue(), sample_ground, permitted_ground, animation_clock):
		_presentation.queue_free()
		_finish(request_id, false, "reload_required")
		return
	if OS.has_feature("web") and not _presentation.bind_web():
		_presentation.queue_free()
		_finish(request_id, false, "reload_required")
		return
	# Mounted component != visible-art-ready. The renderer reports its own
	# missing_assets/ready status for each snapshot after drawing those actors.
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
	await get_tree().process_frame
	_runtime_ready = _live() and is_instance_valid(_presentation) and not _presentation.is_queued_for_deletion()
	_finish(request_id, _runtime_ready, "applied")

func mount_actor(request_id: int, path: String, digest: String) -> void:
	if request_id < 1 or request_id > 2147483647:
		return
	if not _live() or not _runtime_ready or not is_instance_valid(_presentation):
		_finish(request_id, false, "not_ready")
		return
	var name_only := path.trim_prefix("/")
	if path != "/" + name_only or not _actor_shards.has(name_only) or digest != _actor_shards[name_only].pack.sha256:
		_finish(request_id, false, "pin_mismatch")
		return
	if _actor_loaded.has(name_only):
		_finish(request_id, true, "applied")
		return
	if _actor_attempted.has(name_only):
		_finish(request_id, false, "actor_unavailable")
		return
	if _actor_busy:
		_finish(request_id, false, "busy")
		return
	var shard: Dictionary = _actor_shards[name_only]
	var storage_path := path if OS.has_feature("web") else "user://" + name_only
	var file := FileAccess.open(storage_path, FileAccess.READ)
	if file == null or file.get_length() != int(shard.pack.bytes):
		_finish(request_id, false, "pin_mismatch")
		return
	file.close()
	if FileAccess.get_sha256(storage_path) != digest:
		_finish(request_id, false, "pin_mismatch")
		return
	var resources: PackedStringArray = _presentation.asset_paths(shard.assetIds)
	if resources.size() != 1 or FileAccess.file_exists(resources[0]):
		_finish(request_id, false, "namespace_conflict")
		return
	_actor_attempted[name_only] = true
	_actor_busy = true
	# Builder permits exactly ONE byte-pinned PNG entry here, no scripts,
	# manifests, project settings, removal entries or resource replacement.
	if not ProjectSettings.load_resource_pack(storage_path, false) or not FileAccess.file_exists(resources[0]):
		_actor_busy = false
		_finish(request_id, false, "actor_unavailable")
		return
	_actor_loaded[name_only] = true
	_presentation.assets_available(shard.assetIds)
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
	await get_tree().process_frame
	_actor_busy = false
	_finish(request_id, _live() and is_instance_valid(_presentation), "applied")

func sample_ground(point: Vector2) -> Vector3:
	if not _live():
		return Vector3(INF, INF, INF)
	# Re-read existing samplers: progressive detail upgrades may replace them.
	# Never regenerate the landscape triangle meshes for this small add-on.
	var ground: TriangleMesh = _wildlife.get("ground_surface")
	var rock: TriangleMesh = _wildlife.get("rock_surface")
	if ground == null or rock == null:
		return Vector3(INF, INF, INF)
	var hit := ground.intersect_ray(Vector3(point.x, 75, point.y), Vector3.DOWN)
	if hit.is_empty():
		return Vector3(INF, INF, INF)
	var height: float = hit.position.y
	var stone := rock.intersect_ray(Vector3(point.x, 75, point.y), Vector3.DOWN)
	if not stone.is_empty():
		height = maxf(height, float(stone.position.y))
	return Vector3(point.x, height + 0.018, point.y)

func permitted_ground(point: Vector2) -> bool:
	if not _live() or not point.is_finite():
		return false
	# Wildlife's safe_point excludes the Boss clearing and central route, so it
	# cannot be reused. Preserve its river, slope, stone and prop protections.
	if absf(point.x - float(_world.river_center(point.y))) < float(_world.river_half_width(point.y)) + 2.0:
		return false
	var normal: Vector3 = _world.terrain_normal(point.x, point.y)
	if not normal.is_finite() or normal.y < 0.94:
		return false
	var obstacles: Array = _wildlife.get("obstacles")
	for obstacle: Variant in obstacles:
		if not obstacle is Vector3 or not obstacle.is_finite() or point.distance_to(Vector2(obstacle.x, obstacle.y)) < obstacle.z + 0.10:
			return false
	var ground: TriangleMesh = _wildlife.get("ground_surface")
	var rock: TriangleMesh = _wildlife.get("rock_surface")
	if ground == null or rock == null:
		return false
	var hit := ground.intersect_ray(Vector3(point.x, 75, point.y), Vector3.DOWN)
	var stone := rock.intersect_ray(Vector3(point.x, 75, point.y), Vector3.DOWN)
	return not hit.is_empty() and (stone.is_empty() or float(stone.position.y) - float(hit.position.y) <= 0.065)

func animation_clock() -> float:
	return float(_weather.get("animation_clock")) if _live() else NAN

func _finish(request_id: int, success: bool, code: String) -> void:
	if not success and code == "applied":
		code = "reload_required"
	mount_completed.emit(request_id, success, code)
	if _web != null:
		_web.applied(request_id, success, code)

func _exit_tree() -> void:
	_core = false
	_runtime_ready = false
	if _web != null and _callback != null:
		_web.unbind(_callback)
	_callback = null
	_web = null
