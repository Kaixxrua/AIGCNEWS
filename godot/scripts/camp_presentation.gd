extends Node3D
## Optional, post-core public presentation only. No network, account, gameplay
## timer, HP, damage, reward or settlement authority lives here. The visible
## Boss bar receives confirmed HP; legacy seven-field senders retain their
## old progress projection. A death animation never decides a reward outcome.
##
## Pack resource path: res://camp_presentation/camp_presentation.gd
## Integration owns the mount: validate hash, load_resource_pack(path, false),
## add ONE child to the current meadow, then setup(). Never replace its scene.
## setup callbacks use scene-local metres: sample(Vector2 XZ) -> Vector3 XYZ,
## permitted(Vector2 XZ) -> bool; clock() -> the shared animation-clock seconds.
## The existing wildlife.safe_point EXCLUDES the Boss arena: do not use it here.
## Provide a camp-specific river/slope/obstacle predicate. Footprint and segment
## checks below keep every action within the approved central clearing.
##
## Art: eight columns, rows idle/walk/attack/hit. Assets may share a PNG;
## frameRects supplies 32 exact pixel rectangles per actor (UVs derive from the
## actual PNG dimensions). Fixed foot anchors; no procedural actor substitutes.
## Typical cell 192x256, pivot (96,232); frameSize is generic, not role-fixed.
## Optional frameAnchors: 32 per-cell pixel anchors, falling back to anchor.
## Boss may use the same 1536x1024 atlas and worldHeight up to 6 metres.
## Keep >=4 cutout-transparent border pixels (alpha <32/255) in EVERY cell,
## consistent perspective,
## lighting and scale, right-facing three-quarter art, no painted floor/shadow.
## Raw PNGs are decoded ONLY after this optional pack has been mounted. Separate
## frame textures/mips prevent atlas neighbours bleeding at the lite 3D scale.
## Only pet_owl/pet_finch/pet_dragon use hover/flap artwork: lift the sprite,
## never its ground-sampled root or contact shadow. No existing wildlife moves.
## Read LivingWeather.night_blend only. A soft, upper/front moon bounce lights
## each actor on its own reserved render layer; it never illuminates the world,
## water, existing wildlife or contact shadows. Day uses the original material
## and world lighting unchanged. No emission, unshaded art or outline is added.

signal presentation_status(status: String, missing_assets: PackedStringArray)

const CombatEffects := preload("camp_combat_effects.gd")
const BossHud := preload("camp_boss_hud.gd")
const SpawnLayout := preload("camp_spawn_layout.gd")
const TravelPath := preload("camp_travel_path.gd")
const MANIFEST_PATH := "res://camp_presentation/manifest.json"
const MODES := ["demo", "fighting", "paused", "defeated", "cooldown", "daily_complete", "waiting", "unavailable"]
const ROLES := ["hero", "pet", "boss"]
const SNAPSHOT_KEYS := ["mode", "heroAssetId", "petAssetId", "bossAssetId", "elapsed", "duration", "roundId"]
const HP_KEYS := ["bossHp", "bossMaxHp"]
const ASSET_KEYS := ["id", "role", "atlas", "frameSize", "frameRects", "anchor", "worldHeight", "shadowRadius"]
const ARENA_CENTER := Vector2(5.0, -12.0)
const ARENA_RADIUS := 4.2
const STATIONS := {"hero": Vector2(-2.35, 1.10), "pet": Vector2(-1.35, 2.10), "boss": Vector2(1.85, -0.65)}
## Presentation scale, not a change to the immutable source-art catalogue.
## The guardian's visible idle height is about 3.2-3.5 heroes, not merely a
## larger atlas cell. Keep roots at unit scale: feet, shadows and safe paths
## remain in the same scene-local metres as the accepted clearing.
const ROLE_DISPLAY_SCALE := {"hero": 1.10, "pet": 0.80, "boss": 2.0}
const PET_DISPLAY_SCALE := {"pet_deer": 0.90, "pet_fox": 0.94, "pet_rabbit": 0.60,
	"pet_owl": 0.62, "pet_finch": 0.68, "pet_dragon": 0.93}
const HOVER_PET_STATION := Vector2(-2.10, -3.20)
const OFFSETS := {"hero": 0.0, "pet": 1.5, "boss": 3.0}
const STALE_SECONDS := 15.0
const CYCLE_SECONDS := 5.2
const HOVER_PET_IDS := ["pet_owl", "pet_finch", "pet_dragon"]
const HOVER_HEIGHT := 1.25
const HOVER_BOB := 0.06
const HOVER_PERIOD := 2.6
const GROUND_SHADOW_OPACITY := 0.23
const HOVER_SHADOW_OPACITY := 0.10
## Keep layer 1 for existing world lights; layers 18/19/20 isolate role fills.
const MOON_FILL_LAYERS := {"hero": 1 << 17, "pet": 1 << 18, "boss": 1 << 19}
const MOON_FILL_COLOR := Color(0.63, 0.75, 0.95)
const MOON_FILL_POSITION := Vector3(-3.0, 4.0, 6.0)
const MOON_FILL_RANGE := 16.0
const MOON_FILL_ATTENUATION := 0.75
## Godot Omni decay uses distance in METRES, not distance/range. At this soft
## 6-8m offset, the old 1.10 energy was underpowered after distance falloff.
## Actual frozen core + all 12 details / source-art GPU A/B calibrated 8.0:
## day 0, halfway 4, full night 8. Real diffuse/range falloff, NOT emission.
const MOON_FILL_NIGHT_ENERGY := 8.0
## Optional actor sprites ONLY. Source PNG alpha is never rewritten; the normal
## Sprite3D scissor discards alpha below this threshold in the render pipeline.
const ALPHA_CUTOFF := 32.0 / 255.0
const SHADOW_CODE := """shader_type spatial;
render_mode unshaded, cull_disabled, depth_draw_never;
uniform float contact_opacity : hint_range(0.0, 1.0) = 0.23;
void fragment() {
    float radius = length((UV - vec2(0.5)) * 2.0);
    ALBEDO = vec3(0.035, 0.044, 0.027);
    ALPHA = (1.0 - smoothstep(0.22, 1.0, radius)) * contact_opacity;
}
"""

var _configured := false
var _catalogue: Dictionary = {}
var _actors: Dictionary = {}
var _snapshot: Dictionary = {}
var _missing := PackedStringArray()
var _status := "waiting_for_state"
var _reported_missing := PackedStringArray()
var _has_reported := false
var _ground: Callable
var _permitted: Callable
var _shared_clock: Callable
var _last_shared_clock := 0.0
var _motion_clock := 0.0
var _received_msec := 0
var _generation := 0
var _animation_paused := false
var _shadow_shader: Shader
var _lighting_weather: Node
var _web: JavaScriptObject
var _callback: JavaScriptObject
var _effects: Node3D
var _boss_hud: CanvasLayer
var _death_clock := 0.0
var _death_active := false
var _pending_death := false
var _has_health_sample := false
var _visible_boss_ratio := 1.0
var _pending_boss_ratio := 1.0
var _damage_amount := 0
var _damage_age := -1.0
var _damage_heavy := false
var _damage_point := Vector3.ZERO
var _damage_anchor_pending := false
var _arena_center := ARENA_CENTER
var _spawn_index := -1
var _spawn_key := ""
var _spawn_ready := true
var _spawn_seed := ""
## Relocation is a separate presentation state. Existing companions keep their
## actual feet; only the newly spawned guardian may appear at the next site.
const TRAVEL_SPEED := 2.2
const WALK_STRIDE := 1.6
const TRAVEL_CLEARANCE := 0.08
var _travel_active := false
var _travel_blocked := false
var _travel_paths: Dictionary = {}
var _travel_points: Dictionary = {}
var _travel_indices: Dictionary = {}
var _retained_party: Dictionary = {}
var _locomotion_clock := 0.0
const SPECTATOR_BATTLE_SECONDS := 26.6
const SPECTATOR_CYCLE_SECONDS := 31.2
## Choreography markers, NOT the private server's damage/reward rules. Both
## the spectator bar and confirmed-HP presentation release on these impacts.
## No normal hits occur while the two ultimates reserve 10.4..20.8 seconds.
const BOSS_HIT_MS := [600, 2100, 5800, 7300, 11830, 21400, 22900, 26600, 28100]
const BOSS_HIT_ROLES := ["hero", "pet", "hero", "pet", "hero", "hero", "pet", "hero", "pet"]
const SPECTATOR_REMAINING := [0.92, 0.87, 0.76, 0.69, 0.40, 0.25, 0.18, 0.0]
const SKILL_NAMES := {"hero_ranger": "穿林风矢", "hero_knight": "曜日斩", "hero_mage": "炽焰弹",
	"hero_bard": "弦音共鸣", "hero_alchemist": "以太药瓶", "hero_astrologer": "流星坠",
	"pet_deer": "灵角辉光", "pet_fox": "狐火", "pet_rabbit": "月影突袭", "pet_owl": "风羽齐射",
	"pet_finch": "金羽疾风", "pet_dragon": "苍蓝吐息", "boss_ancient_guardian": "古印震地"}
const ULTIMATE_CAST_NAMES := {"hero_ranger": "风之镇魂曲", "hero_knight": "旭日十字", "hero_mage": "凤凰星火",
	"hero_bard": "群星序曲", "hero_alchemist": "翠灵新生", "hero_astrologer": "天星裁决",
	"boss_ancient_guardian": "符文天崩"}

static func read_catalogue() -> Dictionary:
	if not FileAccess.file_exists(MANIFEST_PATH):
		return {}
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
	return value if value is Dictionary else {}

static func _exact(value: Variant, keys: Array) -> bool:
	if not value is Dictionary or value.size() != keys.size():
		return false
	for key: Variant in value:
		if not keys.has(key):
			return false
	return true

static func _number(value: Variant, minimum: float, maximum: float) -> bool:
	return (value is float or value is int) and is_finite(float(value)) and float(value) >= minimum and float(value) <= maximum

static func _identifier(value: Variant, maximum: int = 64, uppercase: bool = false) -> bool:
	if not value is String or value.is_empty() or value.length() > maximum:
		return false
	var allowed := "abcdefghijklmnopqrstuvwxyz0123456789_-"
	if uppercase:
		allowed += "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	for index in range(value.length()):
		if not value[index] in allowed:
			return false
	return value[0] in ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if uppercase else "abcdefghijklmnopqrstuvwxyz")

static func _asset_identifier(value: Variant) -> bool:
	if not value is String or value.length() > 64:
		return false
	var parts: PackedStringArray = value.split("/", true)
	if parts.size() < 1 or parts.size() > 2:
		return false
	for part: String in parts:
		if not _identifier(part):
			return false
	return true

static func _anchor(value: Variant, cell: Array) -> bool:
	return value is Array and value.size() == 2 and _number(value[0], 4, cell[0] - 4) and _number(value[1], 4, cell[1] - 4)

static func _valid_asset(value: Variant) -> bool:
	if not (_exact(value, ASSET_KEYS) or _exact(value, ASSET_KEYS + ["frameAnchors"])) or not _asset_identifier(value.id) or not value.role in ROLES:
		return false
	if not value.atlas is String or not value.atlas.begins_with("res://camp_presentation/atlases/") or not value.atlas.ends_with(".png"):
		return false
	if not _identifier(value.atlas.trim_prefix("res://camp_presentation/atlases/").trim_suffix(".png")):
		return false
	for key: String in ["frameSize", "anchor"]:
		if not value[key] is Array or value[key].size() != 2:
			return false
	for dimension: Variant in value.frameSize:
		if not _number(dimension, 32, 512) or float(dimension) != floorf(float(dimension)):
			return false
	if value.has("frameAnchors"):
		if not value.frameAnchors is Array or value.frameAnchors.size() != 32:
			return false
		for anchor: Variant in value.frameAnchors:
			if not _anchor(anchor, value.frameSize):
				return false
	if not value.frameRects is Array or value.frameRects.size() != 32:
		return false
	for rect: Variant in value.frameRects:
		if not rect is Array or rect.size() != 4:
			return false
		for coordinate: Variant in rect:
			if not _number(coordinate, 0, 8192) or float(coordinate) != floorf(float(coordinate)):
				return false
		if rect[2] != value.frameSize[0] or rect[3] != value.frameSize[1]:
			return false
	return _anchor(value.anchor, value.frameSize) \
		and _number(value.worldHeight, 0.4, 6.0) and _number(value.shadowRadius, 0.12, 1.2)

func setup(scene: Node3D, catalogue: Dictionary, sample_ground: Callable, permitted_ground: Callable, shared_clock: Callable = Callable()) -> bool:
	if _configured or scene == null or get_parent() != scene or not is_inside_tree():
		return false
	if not sample_ground.is_valid() or not permitted_ground.is_valid():
		return false
	if not _exact(catalogue, ["version", "assets"]) or not _number(catalogue.version, 1, 1) or not catalogue.assets is Array or catalogue.assets.size() > 64:
		return false
	var staged: Dictionary = {}
	for asset: Variant in catalogue.assets:
		if not _valid_asset(asset) or staged.has(asset.id):
			return false
		staged[asset.id] = asset.duplicate(true)
	_catalogue = staged
	_ground = sample_ground
	_permitted = permitted_ground
	_shared_clock = shared_clock
	if _shared_clock.is_valid():
		var current: Variant = _shared_clock.call()
		if not _number(current, 0.0, 1.0e12):
			return false
		_last_shared_clock = float(current)
	# The frozen core validates its original 16:10 settings before this optional
	# presentation mounts. Expand only after that gate so wide contact embeds
	# reveal more world space instead of adding pillarboxes or stretching actors.
	get_tree().root.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_EXPAND
	transform = Transform3D.IDENTITY
	name = "CampPresentation"
	_shadow_shader = Shader.new()
	_shadow_shader.code = SHADOW_CODE
	_lighting_weather = scene.get_node_or_null("LivingWeather")
	_configured = true
	_effects = CombatEffects.new()
	add_child(_effects)
	_effects.configure()
	_boss_hud = BossHud.new()
	add_child(_boss_hud)
	return true

func _night_factor() -> float:
	if not is_instance_valid(_lighting_weather):
		return 0.0
	var value: Variant = _lighting_weather.get("night_blend")
	return float(value) if _number(value, 0.0, 1.0) else 0.0

func _sync_actor_lighting() -> void:
	var energy := MOON_FILL_NIGHT_ENERGY * _night_factor()
	for actor: Dictionary in _actors.values():
		actor.moon_fill.light_energy = energy
		actor.moon_fill.visible = energy > 0.0

func bind_web() -> bool:
	if not _configured or not OS.has_feature("web") or _callback != null:
		return false
	_web = JavaScriptBridge.get_interface("meadowCamp")
	if _web == null:
		return false
	_callback = JavaScriptBridge.create_callback(_receive_web)
	if not _web.bind(_callback):
		_callback = null
		_web = null
		return false
	_report(_status)
	return true

func _receive_web(arguments: Array) -> void:
	if arguments.size() != 1 or not arguments[0] is String or arguments[0].length() > 1024:
		return
	# Exit JS -> Godot before loading textures or changing nodes.
	var value: Variant = JSON.parse_string(arguments[0])
	if value is Dictionary:
		apply_snapshot.call_deferred(value)

func validate_snapshot(value: Variant) -> bool:
	if not (_exact(value, SNAPSHOT_KEYS) or _exact(value, SNAPSHOT_KEYS + HP_KEYS)) or not value.mode in MODES:
		return false
	if value.has("bossHp"):
		if not _number(value.bossMaxHp, 1.0, 1.0e9) or not _number(value.bossHp, 0.0, float(value.bossMaxHp)):
			return false
		if float(value.bossHp) != floorf(float(value.bossHp)) or float(value.bossMaxHp) != floorf(float(value.bossMaxHp)):
			return false
	if value.mode == "defeated" and (not value.has("bossHp") or value.bossHp != 0 or value.roundId == ""):
		return false
	if not _number(value.duration, 0.0, 86400.0) or not _number(value.elapsed, 0.0, float(value.duration)):
		return false
	if not value.roundId is String or (value.roundId != "" and not _identifier(value.roundId, 80, true)):
		return false
	if value.mode in ["fighting", "paused"] and (value.roundId == "" or value.duration <= 0):
		return false
	for role: String in ROLES:
		var id: Variant = value[role + "AssetId"]
		if not id is String:
			return false
		if id != "" and (not _catalogue.has(id) or _catalogue[id].role != role):
			return false
		if id == "" and value.mode in ["fighting", "paused", "defeated"]:
			return false
	if value.mode == "demo" and value.heroAssetId == "" and value.petAssetId == "" and value.bossAssetId == "":
		return false
	return true

func apply_snapshot(value: Dictionary) -> bool:
	if not _configured or not validate_snapshot(value):
		return false
	var previous_round: String = _snapshot.get("roundId", "")
	var previous_mode: String = _snapshot.get("mode", "waiting")
	var changed_health_contract := _snapshot.has("bossHp") != value.has("bossHp")
	var was_dead := _confirmed_defeat()
	# The host's four-second hold can expire while the user pauses animation.
	# Keep an already observed defeat through cooldown; a new round, logout or
	# unavailable scene still clears it. This never delays server settlement.
	var keep_defeat: bool = (_death_active or _pending_death) and value.mode in ["cooldown", "daily_complete"] and value.roundId == ""
	var reset: bool = (previous_round != value.roundId and not keep_defeat) or ((previous_mode == "demo") != (value.mode == "demo"))
	if reset:
		_motion_clock = float(value.elapsed)
		_death_clock = 0.0
		_death_active = false
		_pending_death = false
		_has_health_sample = false
		_damage_age = -1.0
		_damage_amount = 0
		_damage_anchor_pending = false
	_snapshot = value.duplicate(true)
	_received_msec = Time.get_ticks_msec()
	_generation += 1
	if value.mode in ["demo", "fighting", "paused"] and not keep_defeat:
		_select_spawn("spectator:%d" % _combat_cycle(_motion_clock) if value.mode == "demo" else "round:" + str(value.roundId))
	if value.mode in ["waiting", "unavailable", "demo"]:
		_death_active = false
		_pending_death = false
		_has_health_sample = false
		if value.mode != "demo":
			_damage_age = -1.0
	elif not keep_defeat:
		if changed_health_contract:
			_has_health_sample = false
		var ratio := _confirmed_boss_ratio()
		var had_live_sample := _has_health_sample and _visible_boss_ratio > 0.0
		if not _has_health_sample or ratio > _visible_boss_ratio:
			# First observation/reconnect and upward corrections are baselines,
			# not newly invented hits. Never replay damage from an unseen round.
			_visible_boss_ratio = ratio
		_pending_boss_ratio = ratio
		_has_health_sample = true
		if _confirmed_defeat() and (reset or not was_dead) and not _death_active and not _pending_death:
			_death_clock = 0.0
			if had_live_sample:
				# Confirmed final blow: 0.6s visible hero release, then 3.2s defeat.
				# Fits the existing 4s host hold without adding any reward callback.
				_pending_death = true
				_motion_clock = _combat_cycle(_motion_clock) * SPECTATOR_CYCLE_SECONDS + 26.0
			else:
				_death_active = true
	_refresh_selected()
	return true

func asset_paths(ids: Array) -> PackedStringArray:
	# Host uses this only with build-pinned IDs, never a requested resource path.
	var paths := PackedStringArray()
	if not _configured or ids.is_empty() or ids.size() > 64:
		return paths
	for id: Variant in ids:
		if not id is String or not _catalogue.has(id):
			return PackedStringArray()
		var path: String = _catalogue[id].atlas
		if not paths.has(path):
			paths.append(path)
	return paths

func assets_available(ids: Array) -> bool:
	# Mount completion never replays an old snapshot, changes authoritative mode,
	# resets its age, or resets the shared animation phase. Late shards for an
	# obsolete outfit stay cached but do not create that obsolete actor.
	if not _configured or _snapshot.is_empty() or asset_paths(ids).is_empty():
		return false
	if _age_seconds() > STALE_SECONDS and _snapshot.mode != "demo":
		_report("stale")
		return false
	var needed := false
	for role: String in ROLES:
		needed = needed or (ids.has(_snapshot[role + "AssetId"]) and not _actors.has(role))
	if needed:
		_generation += 1
		_refresh_selected()
	return true

func _refresh_selected() -> void:
	_missing.clear()
	var safe := true
	var rebuilt_companion := false
	var was_travelling := _travel_active
	for role: String in ROLES:
		var id: String = _snapshot[role + "AssetId"]
		if _actors.has(role) and _actors[role].id != id:
			if role != "boss" and _actors[role].placed:
				_retained_party[role] = {"position": _actors[role].root.position, "distance": _actors[role].walk_distance}
			_actors[role].root.free()
			_actors.erase(role)
		if id == "":
			_retained_party.erase(role)
			_travel_paths.erase(role)
			_travel_points.erase(role)
			_travel_indices.erase(role)
			continue
		if _snapshot.mode in ["waiting", "unavailable"]:
			if _actors.has(role):
				_actors[role].root.visible = false
			continue
		if not _actors.has(role):
			var actor := _make_actor(_catalogue[id])
			if actor.is_empty():
				_missing.append(id)
				continue
			_actors[role] = actor
			if _retained_party.has(role):
				actor.root.position = _retained_party[role].position
				actor.placed = true
				actor.walk_distance = _retained_party[role].distance
				_retained_party.erase(role)
				rebuilt_companion = true
		var actor: Dictionary = _actors[role]
		_set_actor_station(actor)
		var target_safe := _spawn_ready and _safe_segment(actor.station, actor.station + actor.direction * actor.reach, actor.radius)
		if not target_safe and role != "boss" and actor.placed:
			# A failed new destination must not erase an already visible companion.
			_travel_active = true
			_travel_blocked = true
			if not _travel_points.has(role):
				_travel_points[role] = Vector2(actor.root.position.x, actor.root.position.z)
			actor.walk_direction = Vector2.ZERO
		else:
			actor.safe = target_safe
		actor.root.visible = (actor.safe or (role != "boss" and actor.placed)) and not _snapshot.mode in ["waiting", "unavailable"]
		safe = safe and actor.safe
	if rebuilt_companion:
		# Re-plan the entire visible party from their current feet, including
		# late shards. A cached outfit change must not reset another ally either.
		var routes := _routes_to(_arena_center, not was_travelling)
		if routes.has("blocked"):
			_hold_party()
			_travel_active = true
			_travel_blocked = true
		else:
			_install_travel_routes(routes)
	safe = _update_actors() and safe
	var next_status := "missing_assets" if not _missing.is_empty() else ("ready" if safe and not _travel_blocked else "unsafe_placement")
	if _snapshot.mode == "unavailable":
		next_status = "unavailable"
	elif _snapshot.mode == "waiting":
		next_status = "waiting_for_state"
	_ack_rendered.call_deferred(_generation, next_status)

func _visible_art_top(frame: Image) -> int:
	# PNG cutouts can contain almost-transparent RGB/alpha cleanup specks.
	# Match Sprite3D's discard threshold, rather than get_used_rect's alpha>0.
	# Scan only until the first visible pixel, once during in-memory extraction.
	var rgba := frame.get_data()
	var stride := frame.get_width() * 4
	var cutoff := roundi(ALPHA_CUTOFF * 255.0)
	for offset in range(3, rgba.size(), 4):
		if rgba[offset] >= cutoff:
			return floori(float(offset) / float(stride))
	return frame.get_height()

static func _display_scale(spec: Dictionary) -> float:
	if spec.role == "pet":
		return float(PET_DISPLAY_SCALE.get(spec.id, ROLE_DISPLAY_SCALE.pet))
	return float(ROLE_DISPLAY_SCALE.get(spec.role, 1.0))

func _make_actor(spec: Dictionary) -> Dictionary:
	if not FileAccess.file_exists(spec.atlas):
		return {}
	var file := FileAccess.open(spec.atlas, FileAccess.READ)
	if file == null or file.get_length() > 8 * 1024 * 1024:
		return {}
	var source := Image.new()
	if source.load_png_from_buffer(file.get_buffer(file.get_length())) != OK:
		return {}
	var cell := Vector2i(int(spec.frameSize[0]), int(spec.frameSize[1]))
	if source.get_width() * source.get_height() > 16777216 or source.get_format() != Image.FORMAT_RGBA8:
		return {}
	var frames: Array[Texture2D] = []
	var art_tops: Array[int] = []
	for rectangle: Array in spec.frameRects:
		var region := Rect2i(int(rectangle[0]), int(rectangle[1]), int(rectangle[2]), int(rectangle[3]))
		if not Rect2i(Vector2i.ZERO, source.get_size()).encloses(region):
			return {}
		# Runtime frame extraction is in memory, never an edit of the supplied PNG.
		var frame := source.get_region(region)
		art_tops.append(_visible_art_top(frame))
		# Extend hidden RGB before mip filtering; this preserves base alpha and
		# avoids a dark fringe from transparent padding in distant/lite rendering.
		frame.fix_alpha_edges()
		if frame.generate_mipmaps() != OK:
			return {}
		frames.append(ImageTexture.create_from_image(frame))
	var root := Node3D.new()
	root.name = "Camp" + str(spec.role).capitalize()
	var hovering: bool = spec.role == "pet" and spec.id in HOVER_PET_IDS
	var sprite := Sprite3D.new()
	sprite.name = "Art"
	sprite.texture = frames[0]
	var display_scale := _display_scale(spec)
	var display_height := float(spec.worldHeight) * display_scale
	var contact_radius := float(spec.shadowRadius) * display_scale
	sprite.pixel_size = display_height / cell.y
	var offsets: Array[Vector2] = []
	var heads: Array[float] = []
	for index in range(32):
		var anchor: Array = spec.frameAnchors[index] if spec.has("frameAnchors") else spec.anchor
		var offset := Vector2(cell.x * 0.5 - float(anchor[0]), float(anchor[1]) - cell.y * 0.5)
		if spec.role == "boss":
			offset.x = -offset.x
		offsets.append(offset)
		heads.append(maxf(0.0, float(anchor[1]) - art_tops[index]) * sprite.pixel_size)
	sprite.offset = offsets[0]
	sprite.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
	sprite.shaded = true
	sprite.double_sided = true
	sprite.alpha_cut = SpriteBase3D.ALPHA_CUT_DISCARD
	sprite.alpha_scissor_threshold = ALPHA_CUTOFF
	sprite.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	sprite.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	sprite.flip_h = spec.role == "boss"
	sprite.layers |= int(MOON_FILL_LAYERS[spec.role])
	root.add_child(sprite)
	var moon_fill := OmniLight3D.new()
	moon_fill.name = "ActorMoonBounce"
	moon_fill.position = MOON_FILL_POSITION
	# A taller guardian must still receive its reserved moon bounce from above,
	# not from a chest-level lamp. This light remains isolated from the world.
	moon_fill.position.y = maxf(MOON_FILL_POSITION.y, heads.max() + 0.8)
	moon_fill.light_color = MOON_FILL_COLOR
	moon_fill.light_energy = MOON_FILL_NIGHT_ENERGY * _night_factor()
	moon_fill.light_cull_mask = int(MOON_FILL_LAYERS[spec.role])
	moon_fill.omni_range = MOON_FILL_RANGE
	moon_fill.omni_attenuation = MOON_FILL_ATTENUATION
	moon_fill.light_specular = 0.0
	moon_fill.light_indirect_energy = 0.0
	moon_fill.light_volumetric_fog_energy = 0.0
	moon_fill.light_bake_mode = Light3D.BAKE_DISABLED
	moon_fill.shadow_enabled = false
	moon_fill.visible = moon_fill.light_energy > 0.0
	# Actor ownership makes visibility, swaps and teardown remove the light too.
	root.add_child(moon_fill)
	var shadow := MeshInstance3D.new()
	shadow.name = "FootContact"
	var plane := PlaneMesh.new()
	plane.size = Vector2(contact_radius * 2.0, contact_radius * 1.4)
	shadow.mesh = plane
	shadow.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := ShaderMaterial.new()
	material.shader = _shadow_shader
	# Per-actor material, not a global shader parameter or shared world shadow.
	material.set_shader_parameter("contact_opacity", HOVER_SHADOW_OPACITY if hovering else GROUND_SHADOW_OPACITY)
	shadow.material_override = material
	shadow.position.y = 0.016
	root.add_child(shadow)
	root.visible = false
	add_child(root)
	# Separate airborne silhouettes from the hero's head. Ground pets retain
	# their accepted station; the same terrain/footprint/lunge checks still apply.
	var station: Vector2 = _arena_center + (HOVER_PET_STATION if hovering else STATIONS[spec.role])
	var opponent: Vector2 = _arena_center + STATIONS["hero" if spec.role == "boss" else "boss"]
	return {"id": spec.id, "role": spec.role, "root": root, "sprite": sprite, "shadow": shadow,
		"hovering": hovering, "moon_fill": moon_fill, "height": display_height,
		"frames": frames, "offsets": offsets, "heads": heads, "frame": -1, "station": station, "direction": station.direction_to(opponent),
		"reach": 0.42 if spec.role == "boss" else 0.58, "radius": contact_radius, "safe": false,
		"placed": false, "walk_distance": 0.0, "walk_direction": Vector2.ZERO}

func _sample(point: Vector2) -> Variant:
	var result: Variant = _ground.call(point)
	if not result is Vector3 or not result.is_finite() or absf(result.x - point.x) > 0.001 or absf(result.z - point.y) > 0.001:
		return null
	return result

func _safe_point(point: Vector2, radius: float, centre: Vector2 = Vector2(INF, INF)) -> bool:
	var reference := _arena_center if not centre.is_finite() else centre
	if point.distance_to(reference) + radius > ARENA_RADIUS:
		return false
	var surface_centre: Variant = _sample(point)
	if surface_centre == null:
		return false
	for offset: Vector2 in [Vector2.ZERO, Vector2(radius, 0), Vector2(-radius, 0), Vector2(0, radius), Vector2(0, -radius)]:
		var probe := point + offset
		var allowed: Variant = _permitted.call(probe)
		var surface: Variant = _sample(probe)
		if not allowed is bool or not allowed or surface == null or absf(surface.y - surface_centre.y) > maxf(0.08, radius * 0.32):
			return false
	return true

func _safe_segment(start: Vector2, finish: Vector2, radius: float, centre: Vector2 = Vector2(INF, INF)) -> bool:
	var steps := maxi(1, ceili(start.distance_to(finish) / 0.20))
	for index in range(steps + 1):
		if not _safe_point(start.lerp(finish, float(index) / steps), radius, centre):
			return false
	return true

func _layout_is_safe(centre: Vector2) -> bool:
	# Check the complete catalogue, not only this currently equipped trio.
	# Source dimensions, alpha registration and the world's samplers stay intact.
	for spec: Dictionary in _catalogue.values():
		var hovering: bool = spec.role == "pet" and spec.id in HOVER_PET_IDS
		var station: Vector2 = centre + (HOVER_PET_STATION if hovering else STATIONS[spec.role])
		var target: Vector2 = centre + STATIONS["hero" if spec.role == "boss" else "boss"]
		var radius := float(spec.shadowRadius) * _display_scale(spec)
		var finish := station + station.direction_to(target) * (0.42 if spec.role == "boss" else 0.58)
		if not _safe_segment(station, finish, radius, centre):
			return false
	return true

func _set_actor_station(actor: Dictionary) -> void:
	actor.station = _arena_center + (HOVER_PET_STATION if actor.hovering else STATIONS[actor.role])
	var target: Vector2 = _arena_center + STATIONS["hero" if actor.role == "boss" else "boss"]
	actor.direction = actor.station.direction_to(target)

func _select_spawn(key: String) -> void:
	if key == _spawn_key:
		if not _travel_blocked:
			return
		if _spawn_ready:
			# Explicit fresh state can retry a blocked route to the SAME site.
			# Do not reroll a living guardian or erase the already travelled path.
			var targets: Dictionary = {}
			for role: String in _travel_paths:
				var path: PackedVector2Array = _travel_paths[role]
				if not path.is_empty():
					targets[role] = path[-1]
			var routes := _routes_to(_arena_center, false, targets)
			if not routes.has("blocked"):
				_install_travel_routes(routes)
			return
	if _spawn_seed.is_empty():
		# Presentation-local entropy; never advances the world's random stream.
		_spawn_seed = "%d:%d" % [get_instance_id(), Time.get_ticks_usec()]
	var eligible := PackedInt32Array()
	for index in range(SpawnLayout.CENTRES.size()):
		if _layout_is_safe(SpawnLayout.CENTRES[index]):
			eligible.append(index)
	# Keep the accepted first encounter as the initial reference. Every respawn
	# chooses a different verified clearing, stable across repeated snapshots.
	var selected: int = 0 if _spawn_index < 0 and eligible.has(0) else SpawnLayout.choose(eligible, _spawn_index, _spawn_seed + ":" + key)
	var routes: Dictionary = {}
	# A valid destination is not proof of a connected route. Reject sites that
	# a currently visible companion cannot reach without crossing an obstacle.
	while selected >= 0:
		routes = _routes_to(SpawnLayout.CENTRES[selected], false, {}, true)
		if not routes.has("blocked"):
			break
		eligible.remove_at(eligible.find(selected))
		selected = SpawnLayout.choose(eligible, _spawn_index, _spawn_seed + ":" + key)
	_spawn_key = key
	_spawn_ready = selected >= 0
	if not _spawn_ready:
		# Do not hide/teleport an already visible party to conceal a route failure.
		_hold_party()
		_travel_active = true
		_travel_blocked = true
		_report("unsafe_placement")
		return
	_spawn_index = selected
	_arena_center = SpawnLayout.CENTRES[selected]
	_damage_age = -1.0
	_damage_amount = 0
	_damage_heavy = false
	_damage_anchor_pending = false
	_install_travel_routes(routes)
	for actor: Dictionary in _actors.values():
		_set_actor_station(actor)
		actor.safe = _safe_segment(actor.station, actor.station + actor.direction * actor.reach, actor.radius)
	if _travel_active:
		# Start the next visual exchange from idle after arrival, not halfway
		# through an unseen lunge. Authoritative elapsed/HP are untouched.
		_motion_clock = _combat_cycle(_motion_clock) * SPECTATOR_CYCLE_SECONDS

func _install_travel_routes(routes: Dictionary) -> void:
	_travel_paths = routes
	_travel_points.clear()
	_travel_indices.clear()
	_travel_active = false
	_travel_blocked = false
	for role: String in routes:
		var path: PackedVector2Array = routes[role]
		_travel_points[role] = path[0]
		_travel_indices[role] = 1
		_travel_active = _travel_active or path[0].distance_to(path[path.size() - 1]) > 0.00001
	if not _travel_active:
		_travel_paths.clear()
		_travel_points.clear()
		_travel_indices.clear()

func _route_permitted(point: Vector2, centre: Vector2) -> bool:
	var allowed: Variant = _permitted.call(point)
	if not allowed is bool or not allowed:
		return false
	var boss_id: String = _snapshot.get("bossAssetId", "")
	var boss_radius := 0.0
	if _catalogue.has(boss_id):
		boss_radius = float(_catalogue[boss_id].shadowRadius) * _display_scale(_catalogue[boss_id])
	return point.distance_to(centre + STATIONS.boss) > boss_radius + 0.10

func _routes_to(centre: Vector2, resume_pose: bool = false, targets: Dictionary = {}, respawn_candidate: bool = false) -> Dictionary:
	var routes: Dictionary = {}
	for role: String in ["hero", "pet"]:
		if not _actors.has(role) or not _actors[role].placed:
			continue
		var actor: Dictionary = _actors[role]
		var start := Vector2(actor.root.position.x, actor.root.position.z)
		var finish: Vector2 = centre + (HOVER_PET_STATION if actor.hovering else STATIONS[role])
		if targets.has(role):
			finish = targets[role]
		elif resume_pose:
			# An in-round outfit can finish at the currently held lunge point.
			# Resuming that same attack phase then cannot teleport to its reach.
			finish += finish.direction_to(centre + STATIONS.boss) * actor.reach * float(_pose(role).travel)
		if respawn_candidate:
			# A new guardian need not pick a site that forces an expensive detour
			# around its own body. Analytically reject that candidate BEFORE terrain
			# search, then try another verified site; never loosen collision safety.
			var boss_id: String = _snapshot.get("bossAssetId", "")
			var boss_radius := float(_catalogue[boss_id].shadowRadius) * _display_scale(_catalogue[boss_id]) if _catalogue.has(boss_id) else 0.0
			var boss_point: Vector2 = centre + STATIONS.boss
			var segment := finish - start
			var amount := clampf((boss_point - start).dot(segment) / segment.length_squared(), 0.0, 1.0) if segment.length_squared() > 0.000001 else 0.0
			if boss_point.distance_to(start + segment * amount) <= boss_radius + 0.10 + actor.radius + TRAVEL_CLEARANCE:
				return {"blocked": true}
		var path := TravelPath.find_path(start, finish, actor.radius + TRAVEL_CLEARANCE, _ground, _route_permitted.bind(centre))
		if path.is_empty():
			return {"blocked": true}
		routes[role] = path
	return routes

func _hold_party() -> void:
	_travel_paths.clear()
	_travel_indices.clear()
	_travel_points.clear()
	for role: String in ["hero", "pet"]:
		if _actors.has(role) and _actors[role].placed:
			var actor: Dictionary = _actors[role]
			_travel_points[role] = Vector2(actor.root.position.x, actor.root.position.z)
			actor.walk_direction = Vector2.ZERO

func _advance_travel(step: float) -> void:
	if _travel_blocked or step <= 0.0:
		return
	var any_pending := false
	for role: String in _travel_paths:
		if not _actors.has(role) or not _actors[role].safe:
			any_pending = true
			continue
		var actor: Dictionary = _actors[role]
		var path: PackedVector2Array = _travel_paths[role]
		var index: int = _travel_indices[role]
		var point: Vector2 = _travel_points[role]
		var budget := TRAVEL_SPEED * step
		actor.walk_direction = Vector2.ZERO
		var segments := 0
		while index < path.size() and budget > 0.00001 and segments < 8:
			segments += 1
			var target := path[index]
			var distance := point.distance_to(target)
			if distance <= 0.000001:
				index += 1
				continue
			var taken := minf(budget, distance)
			var next := point.move_toward(target, taken)
			var foot: Variant = _sample(point)
			var next_foot: Variant = _sample(next)
			if foot == null or next_foot == null:
				_travel_blocked = true
				actor.walk_direction = Vector2.ZERO
				_report("unsafe_placement")
				break
			var surface_distance: float = foot.distance_to(next_foot)
			# Speed is metres over the actual sloped ground, not only XZ metres.
			# A bounded refinement prevents a long host delta from overshooting.
			for _adjustment in range(4):
				if surface_distance <= budget:
					break
				taken *= maxf(0.0, budget - 0.000001) / surface_distance
				next = point.move_toward(target, taken)
				next_foot = _sample(next)
				if next_foot == null:
					break
				surface_distance = foot.distance_to(next_foot)
			# Vector2 coordinates are finite-precision: a sub-pixel residual budget
			# may round to the same point. Never spin without consuming distance.
			if next == point or surface_distance < 0.000001:
				break
			# Recheck the short actual step; the route was planned only once.
			# If terrain changes, hold the current feet rather than snap/fade.
			if next_foot == null or surface_distance > budget + 0.000001 or not _travel_step_safe(point, next, actor.radius):
				_travel_blocked = true
				actor.walk_direction = Vector2.ZERO
				_report("unsafe_placement")
				break
			actor.walk_direction = point.direction_to(next)
			actor.walk_distance += surface_distance
			point = next
			budget -= surface_distance
			if taken >= distance:
				index += 1
		_travel_points[role] = point
		_travel_indices[role] = index
		any_pending = any_pending or index < path.size()
		if _travel_blocked:
			break
	# Retain endpoint overrides until the next real combat step, preventing an
	# arrival-time pose from moving feet twice within the same animation tick.
	if not any_pending and not _travel_blocked:
		_travel_active = false
		for actor: Dictionary in _actors.values():
			actor.walk_direction = Vector2.ZERO

func _travel_step_safe(start: Vector2, finish: Vector2, radius: float) -> bool:
	var steps := maxi(1, ceili(start.distance_to(finish) / 0.10))
	for index in range(steps + 1):
		var point := start.lerp(finish, float(index) / steps)
		var foot: Variant = _sample(point)
		if foot == null:
			return false
		for direction: Vector2 in [Vector2.ZERO, Vector2.RIGHT, Vector2.LEFT, Vector2.UP, Vector2.DOWN,
				Vector2(0.707107, 0.707107), Vector2(-0.707107, 0.707107), Vector2(0.707107, -0.707107), Vector2(-0.707107, -0.707107)]:
			var probe := point + direction * radius
			var surface: Variant = _sample(probe)
			if not _route_permitted(probe, _arena_center) or surface == null or absf(surface.y - foot.y) > maxf(0.08, radius * 0.32):
				return false
	return true

func set_animation_paused(paused: bool) -> void:
	_animation_paused = paused
	_sync_boss_hud()

func _process(delta: float) -> void:
	if not _configured:
		return
	# Weather keeps transitioning while choreography is paused or server state
	# is stale. Sync lighting before those gates without advancing any pose/time.
	_sync_actor_lighting()
	var step := clampf(delta, 0.0, 0.1)
	if _shared_clock.is_valid():
		var current: Variant = _shared_clock.call()
		if not _number(current, 0.0, 1.0e12):
			return
		step = clampf(float(current) - _last_shared_clock, 0.0, 0.1)
		_last_shared_clock = float(current)
	if _snapshot.is_empty():
		return
	if not is_visible_in_tree():
		# CanvasLayer is not covered by its Node3D parent's visibility. Hide it
		# explicitly and consume the shared-clock sample without advancing combat.
		_boss_hud.visible = false
		return
	if _age_seconds() > STALE_SECONDS and _snapshot.mode != "demo":
		_report("stale")
		_sync_boss_hud()
		return
	if _animation_paused or _snapshot.mode in ["paused", "waiting", "unavailable"]:
		_sync_boss_hud()
		return
	if _travel_active:
		for role: String in ROLES:
			if role == "boss" and (_snapshot.mode in ["cooldown", "daily_complete"] or _death_active):
				continue
			if not _actors.has(role) or not _actors[role].safe or not _actors[role].root.visible:
				_sync_boss_hud()
				return
		_locomotion_clock += step
		_advance_travel(step)
		_update_actors(step)
		return
	# Do not advance unseen attacks while optional actor shards are missing.
	if _current_death_age() < 0.0 and _combat_mode() in ["demo", "fighting"] and not _combat_cast_ready():
		_sync_boss_hud()
		return
	var before := _motion_clock
	_locomotion_clock += step
	_travel_points.clear()
	_travel_paths.clear()
	_travel_indices.clear()
	var previous_ratio := _displayed_boss_ratio()
	if _damage_age >= 0.0:
		_damage_age = minf(_damage_age + step, 1.20)
	# Do not wrap at 520s: that is not a multiple of the ultimate/guest cycle.
	_motion_clock += step
	if _snapshot.get("mode") == "demo" and _combat_cycle(before) != _combat_cycle(_motion_clock):
		_select_spawn("spectator:%d" % _combat_cycle(_motion_clock))
	if _death_active:
		_death_clock = minf(_death_clock + step, 4.0)
	else:
		_release_confirmed_hit(before, _motion_clock)
	var shown := _displayed_boss_ratio()
	if shown < previous_ratio and _boss_hit_between(before, _motion_clock) != "":
		# One-way hit feedback. Real rounds show the exact confirmed HP decrease;
		# only unauthenticated observation uses a local 1000-point display scale.
		var maximum := 1000.0 if _snapshot.get("mode") == "demo" else float(_snapshot.get("bossMaxHp", 1000.0))
		_damage_amount = roundi((previous_ratio - shown) * maximum)
		_damage_age = 0.0 if _damage_amount > 0 else -1.0
		var ultimate := CombatEffects.ultimate_state(_motion_clock)
		_damage_heavy = ultimate.active and ultimate.role == "hero"
		_damage_anchor_pending = _damage_amount > 0
	_update_actors(step)

func _combat_mode() -> String:
	if _pending_death:
		return "fighting"
	if _death_active:
		return "defeated"
	return str(_snapshot.get("mode", "waiting"))

func _combat_cast_ready() -> bool:
	if _travel_active:
		return false
	for role: String in ROLES:
		if not _actors.has(role) or not _actors[role].safe or not _actors[role].root.visible:
			return false
	return true

static func _boss_hit_between(before: float, after: float) -> String:
	if not is_finite(before) or not is_finite(after) or before < 0.0 or after <= before:
		return ""
	var start_us := roundi(before * 1000000.0)
	var end_us := roundi(after * 1000000.0)
	var base_us := (start_us / 31200000) * 31200000
	for index in range(BOSS_HIT_MS.size()):
		var event_us: int = base_us + BOSS_HIT_MS[index] * 1000
		if event_us > start_us and event_us <= end_us:
			return BOSS_HIT_ROLES[index]
	if end_us >= base_us + 31200000 + BOSS_HIT_MS[0] * 1000:
		return "hero"
	return ""

static func _combat_cycle(clock: float) -> int:
	# Same microsecond boundary as HP, hit poses and ultimate VFX. Otherwise a
	# rounded respawn can appear one frame before its new layout is selected.
	return roundi(clock * 1000000.0) / 31200000

func _release_confirmed_hit(before: float, after: float) -> void:
	if _snapshot.get("mode") == "demo" or not _has_health_sample or _pending_boss_ratio >= _visible_boss_ratio:
		return
	var role := _boss_hit_between(before, after)
	if role == "" or not _combat_cast_ready():
		return
	# Release only damage already confirmed by the server. Repeated liveness
	# snapshots and subsequent attacks cannot create another decrement.
	_visible_boss_ratio = _pending_boss_ratio
	if _pending_death and _visible_boss_ratio == 0.0:
		_pending_death = false
		_death_active = true
		_death_clock = 0.0

func _update_actors(delta: float = 0.0) -> bool:
	if _snapshot.is_empty():
		return true
	var safe := true
	for role: String in _actors:
		var actor: Dictionary = _actors[role]
		if not actor.safe:
			continue
		actor.root.visible = not _snapshot.mode in ["waiting", "unavailable"]
		if role == "boss" and not _spawn_ready:
			actor.root.visible = false
		if role == "boss" and _snapshot.mode in ["cooldown", "daily_complete"] and not (_death_active or _pending_death):
			actor.root.visible = false
		if not actor.root.visible:
			continue
		var pose := _pose(role)
		var point: Vector2 = actor.station + actor.direction * actor.reach * pose.travel
		if _travel_points.has(role):
			point = _travel_points[role]
		var foot: Variant = _sample(point)
		if foot == null:
			actor.safe = false
			actor.root.visible = false
			safe = false
			_report("unsafe_placement")
			continue
		actor.root.position = foot
		actor.placed = true
		# The same bounded presentation clock drives flap frames and a small bob.
		# Keeping root at foot preserves terrain checks and the ground shadow;
		# server/local pause and stale state freeze this offset with the pose.
		actor.sprite.position = Vector3(0.0, HOVER_HEIGHT + sin(_locomotion_clock * TAU / HOVER_PERIOD) * HOVER_BOB if actor.hovering else 0.0, 0.0)
		if role != "boss":
			var direction: Vector2 = actor.walk_direction if _travel_active and actor.walk_direction.length_squared() > 0.0 else actor.direction
			var camera := get_viewport().get_camera_3d()
			var right := camera.global_basis.x if is_instance_valid(camera) else Vector3.RIGHT
			var side := Vector3(direction.x, 0, direction.y).dot(right)
			if absf(side) > 0.05:
				actor.sprite.flip_h = side < 0.0
		var death_age := _current_death_age()
		if role == "boss" and death_age >= 0.0:
			_apply_defeat_pose(actor, death_age)
		else:
			actor.sprite.basis = Basis.IDENTITY
			actor.sprite.billboard = BaseMaterial3D.BILLBOARD_FIXED_Y
			actor.sprite.alpha_cut = SpriteBase3D.ALPHA_CUT_DISCARD
			actor.sprite.render_priority = 0
			actor.sprite.modulate = Color.WHITE
			actor.shadow.material_override.set_shader_parameter("contact_opacity", HOVER_SHADOW_OPACITY if actor.hovering else GROUND_SHADOW_OPACITY)
		# Fit the contact plane to actual local support without tilting the actor.
		var across: Variant = _sample(point + Vector2(0.15, 0))
		var along: Variant = _sample(point + Vector2(0, 0.15))
		if across != null and along != null:
			var normal: Vector3 = (along - foot).cross(across - foot).normalized()
			if normal.y > 0.8:
				actor.shadow.quaternion = Quaternion(Vector3.UP, normal)
		var frame: int = pose.row * 8 + pose.frame
		if actor.frame != frame:
			actor.sprite.texture = actor.frames[frame]
			actor.frame = frame
		var registered: Vector2 = actor.offsets[frame]
		actor.sprite.offset = Vector2(-registered.x, registered.y) if role != "boss" and actor.sprite.flip_h else registered
	var death_age := _current_death_age()
	if _damage_anchor_pending and _actors.has("boss"):
		var boss: Dictionary = _actors.boss
		_damage_point = boss.root.global_position + boss.sprite.position + Vector3.UP * boss.heads[maxi(0, boss.frame)] * 0.72
		_damage_anchor_pending = false
	if _travel_active or not _travel_points.is_empty():
		_effects.present(_actors, _motion_clock, "waiting", false, get_viewport().get_camera_3d(), _night_factor())
	elif death_age >= 0.0:
		_effects.present_defeat(_actors, death_age, get_viewport().get_camera_3d(), _night_factor())
	else:
		_effects.present(_actors, _motion_clock, _combat_mode(), safe,
			get_viewport().get_camera_3d(), _night_factor())
	_sync_boss_hud(delta)
	return safe

func _apply_defeat_pose(actor: Dictionary, age: float) -> void:
	# Pivot around the registered feet, not the centre of the padded atlas.
	# A short recoil, a weighted kneel and sideways collapse remain legible
	# before the body fades. Root/ground placement and world lighting are intact.
	var camera := get_viewport().get_camera_3d()
	var facing := Vector3.BACK
	if is_instance_valid(camera):
		# Match the existing fixed-Y billboard's camera axes before adding roll;
		# aiming anew at the camera position would yaw/snap the flat art on death.
		facing = camera.global_basis.z
		facing.y = 0.0
		facing = facing.normalized() if facing.length_squared() > 0.0001 else Vector3.BACK
	var right := Vector3.UP.cross(facing).normalized()
	var kneel := smoothstep(0.22, 1.35, age)
	var collapse := smoothstep(1.18, 2.30, age)
	var recoil := sin(minf(age / 0.22, 1.0) * PI) * 0.10
	var lean := recoil + kneel * 0.12 + collapse * 0.95
	actor.sprite.billboard = BaseMaterial3D.BILLBOARD_DISABLED
	actor.sprite.basis = Basis(right, Vector3.UP, facing) * Basis(Vector3.BACK, -lean) * Basis.from_scale(Vector3(1.0 + kneel * 0.04, 1.0 - kneel * 0.28, 1.0))
	actor.sprite.position = right * (recoil * 0.45 + collapse * 0.28) + Vector3.DOWN * (kneel * 0.035 + collapse * 0.08)
	actor.sprite.alpha_cut = SpriteBase3D.ALPHA_CUT_DISABLED
	actor.sprite.render_priority = 127
	var flash := (1.0 - smoothstep(0.0, 0.16, age)) * 0.18
	actor.sprite.modulate = Color(1.0 + flash, 1.0 + flash * 0.7, 1.0, 1.0 - smoothstep(1.70, 2.60, age))
	actor.shadow.material_override.set_shader_parameter("contact_opacity", GROUND_SHADOW_OPACITY * (1.0 - smoothstep(1.35, 2.60, age)))
	actor.root.visible = age < 2.60

func _confirmed_boss_ratio() -> float:
	# This layer cannot send damage, death, random draws or rewards upstream.
	# New snapshots display HP computed by the private authoritative backend.
	if _snapshot.get("mode") == "demo":
		var phase_ms := roundi(_motion_clock * 1000000.0) % 31200000 / 1000.0
		var remaining := 1.0
		for index in range(SPECTATOR_REMAINING.size()):
			if phase_ms >= BOSS_HIT_MS[index]:
				remaining = SPECTATOR_REMAINING[index]
		return remaining
	if _snapshot.has("bossHp"):
		return float(_snapshot.bossHp) / float(_snapshot.bossMaxHp)
	var duration := float(_snapshot.get("duration", 0.0))
	return clampf(1.0 - float(_snapshot.get("elapsed", 0.0)) / duration, 0.0, 1.0) if duration > 0.0 else 1.0

func _displayed_boss_ratio() -> float:
	return _confirmed_boss_ratio() if _snapshot.get("mode") == "demo" else _visible_boss_ratio

func _confirmed_defeat() -> bool:
	return _snapshot.get("mode") == "defeated" or (_snapshot.get("mode") in ["fighting", "paused"]
		and _snapshot.has("bossHp") and _snapshot.bossHp == 0)

func _current_death_age() -> float:
	if _death_active:
		return _death_clock
	if _snapshot.get("mode") == "demo":
		var phase := (roundi(_motion_clock * 1000000.0) % 31200000) / 1000000.0
		if phase >= SPECTATOR_BATTLE_SECONDS:
			return phase - SPECTATOR_BATTLE_SECONDS
	return -1.0

func _sync_boss_hud(delta: float = 0.0) -> void:
	if not is_instance_valid(_boss_hud):
		return
	if not is_visible_in_tree():
		_boss_hud.visible = false
		return
	var mode := _combat_mode()
	var camera := get_viewport().get_camera_3d()
	var boss_visible: bool = _actors.has("boss") and _actors.boss.root.visible and _actors.boss.safe
	var anchor := Vector2.ZERO
	if boss_visible and is_instance_valid(camera):
		var boss: Dictionary = _actors.boss
		# Anchor to the visible art, not the atlas cell's transparent headroom.
		var head_height: float = boss.heads[maxi(0, boss.frame)] + boss.sprite.position.y
		var point: Vector3 = boss.root.global_position + Vector3.UP * (head_height + 0.18)
		boss_visible = not camera.is_position_behind(point)
		anchor = camera.unproject_position(point)
	else:
		boss_visible = false
	var stale := mode != "demo" and _age_seconds() > STALE_SECONDS
	_boss_hud.present(mode, _displayed_boss_ratio(), anchor, get_viewport().get_visible_rect().size,
		boss_visible, stale, _animation_paused or _snapshot.get("mode") == "paused", delta)
	var cast := _current_cast()
	var cast_anchor := Vector2.ZERO
	var cast_exclusions: Array[Rect2] = []
	var show_cast: bool = not cast.is_empty() and is_instance_valid(camera)
	if show_cast:
		var caster: Dictionary = _actors[cast.role]
		var point: Vector3 = caster.root.global_position + caster.sprite.position + Vector3.UP * (caster.heads[maxi(0, caster.frame)] + 0.12)
		show_cast = caster.safe and caster.root.visible and not camera.is_position_behind(point)
		cast_anchor = camera.unproject_position(point)
		for role: String in _actors:
			if role != cast.role:
				var occupied := _actor_screen_rect(_actors[role], camera)
				if occupied.has_area():
					cast_exclusions.append(occupied)
	_boss_hud.present_cast(str(cast.get("title", "")), cast_anchor, get_viewport().get_visible_rect().size,
		show_cast, cast.get("role", "boss") != "boss", cast_exclusions)
	var show_damage: bool = _damage_amount > 0 and _damage_age >= 0.0 and _damage_age < 1.20 and is_instance_valid(camera)
	var damage_anchor := Vector2.ZERO
	if show_damage:
		show_damage = not camera.is_position_behind(_damage_point) and not mode in ["waiting", "unavailable"]
		damage_anchor = camera.unproject_position(_damage_point)
	_boss_hud.present_damage(_damage_amount, damage_anchor, get_viewport().get_visible_rect().size, _damage_age, _damage_heavy, show_damage)

func _actor_screen_rect(actor: Dictionary, camera: Camera3D) -> Rect2:
	if not actor.safe or not actor.root.visible:
		return Rect2()
	# Conservative current-frame body bounds, not a fixed HUD rectangle or a
	# guessed old spawn point. Full texture width includes transparent padding;
	# cached alpha-visible height keeps a tall guardian's chest/face protected.
	var sprite: Sprite3D = actor.sprite
	var right := camera.global_basis.x.normalized()
	var centre: Vector3 = actor.root.global_position + sprite.position + right * sprite.offset.x * sprite.pixel_size
	var half_width := sprite.texture.get_width() * sprite.pixel_size * 0.5
	var height: float = actor.heads[maxi(0, actor.frame)]
	var rectangle := Rect2()
	var first := true
	for side: float in [-1.0, 1.0]:
		for elevation: float in [0.0, height]:
			var point := centre + right * half_width * side + Vector3.UP * elevation
			if camera.is_position_behind(point):
				return Rect2()
			var projected := camera.unproject_position(point)
			rectangle = Rect2(projected, Vector2.ZERO) if first else rectangle.expand(projected)
			first = false
	return rectangle.grow(6.0)

func _current_cast() -> Dictionary:
	if _travel_active or not _travel_points.is_empty():
		return {}
	if not _combat_mode() in ["demo", "fighting", "paused"] or _current_death_age() >= 0.0:
		return {}
	var ultimate := CombatEffects.ultimate_state(_motion_clock)
	var role := ""
	var empowered := false
	if ultimate.reserved:
		if not ultimate.active:
			return {}
		role = ultimate.role
		empowered = true
	else:
		for candidate: String in ROLES:
			var phase_us := posmod(roundi(_motion_clock * 1000000.0) - roundi(float(OFFSETS[candidate]) * 1000000.0), 5200000)
			if phase_us < 1300000:
				role = candidate
				break
	if not _actors.has(role):
		return {}
	var names: Dictionary = ULTIMATE_CAST_NAMES if empowered else SKILL_NAMES
	var fallback := "符文天崩" if role == "boss" else "风之镇魂曲"
	return {"role": role, "title": str(names.get(_actors[role].id, fallback if empowered else "灵光一击")) + "！", "ultimate": empowered}

func _pose(role: String) -> Dictionary:
	var result := {"row": 0, "frame": int(floorf(_motion_clock * 5.0)) % 8, "travel": 0.0}
	if _travel_active or not _travel_points.is_empty():
		if role != "boss" and _actors.has(role):
			var actor: Dictionary = _actors[role]
			if actor.walk_direction.length_squared() > 0.0 and not _travel_blocked:
				result.row = 1
				result.frame = int(floorf(actor.walk_distance / WALK_STRIDE * 8.0)) % 8
		return result
	var death_age := _current_death_age()
	if death_age >= 0.0:
		if role == "boss":
			result.row = 3
			result.frame = mini(7, int(death_age * 8.0))
		elif role == "hero" and death_age < 0.35:
			result.row = 2
			result.frame = mini(7, 3 + int(death_age * 12.0))
		return result
	if not _combat_mode() in ["demo", "fighting", "paused"]:
		return result
	var ultimate := CombatEffects.ultimate_state(_motion_clock)
	if ultimate.reserved:
		if not ultimate.active:
			return result
		var phase: float = ultimate.phase
		if role == ultimate.role:
			if phase < 0.95:
				result.row = 2
				result.frame = mini(2, int(phase / 0.95 * 3.0))
				result.travel = smoothstep(0.0, 0.95, phase) * 0.35
			elif phase < 1.63:
				result.row = 2
				result.frame = mini(7, 3 + int((phase - 0.95) / 0.68 * 5.0))
				result.travel = 0.35 + smoothstep(0.95, 1.30, phase) * 0.65
			elif phase < 2.35:
				result.row = 1
				result.travel = 1.0 - smoothstep(1.63, 2.35, phase)
		elif role == ("boss" if ultimate.role == "hero" else "hero") and phase >= 1.43 and phase < 1.85:
			result.row = 3
			result.frame = mini(7, int((phase - 1.43) / 0.42 * 8.0))
		return result
	var phase := fposmod(_motion_clock - float(OFFSETS[role]), CYCLE_SECONDS)
	if phase < 0.30:
		result.row = 1
		result.travel = smoothstep(0.0, 0.30, phase)
	elif phase < 0.95:
		result.row = 2
		result.frame = mini(7, int((phase - 0.30) / 0.65 * 8.0))
		result.travel = 1.0
	elif phase < 1.35:
		result.row = 1
		result.travel = 1.0 - smoothstep(0.95, 1.35, phase)
	var impact_phase := (roundi(_motion_clock * 1000000.0) % 5200000) / 1000000.0
	var reacting := (role == "boss" and ((impact_phase >= 0.60 and impact_phase < 0.90) or (impact_phase >= 2.10 and impact_phase < 2.40))) \
		or (role == "hero" and impact_phase >= 3.60 and impact_phase < 3.90)
	if reacting and result.row == 0:
		result.row = 3
		result.frame = int(floorf(impact_phase * 20.0)) % 8
	return result

func _age_seconds() -> float:
	return maxf(0.0, (Time.get_ticks_msec() - _received_msec) / 1000.0)

func get_presentation_status() -> Dictionary:
	var elapsed: float = float(_snapshot.get("elapsed", 0.0))
	if _snapshot.get("mode") == "fighting" and not _animation_paused:
		elapsed = minf(float(_snapshot.duration), elapsed + minf(_age_seconds(), 2.0))
	return {"configured": _configured, "mode": _snapshot.get("mode", "waiting"), "status": _status,
		"missingAssets": Array(_missing), "visualElapsed": elapsed}

func _ack_rendered(generation: int, next_status: String) -> void:
	if not is_inside_tree():
		return
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
	await get_tree().process_frame
	if is_inside_tree() and generation == _generation:
		_report("stale" if _age_seconds() > STALE_SECONDS and _snapshot.mode != "demo" else next_status)

func _report(value: String) -> void:
	if _has_reported and _status == value and _reported_missing == _missing:
		return
	_status = value
	_reported_missing = _missing.duplicate()
	_has_reported = true
	presentation_status.emit(value, _missing)
	if _web != null:
		_web.report(value)

func _exit_tree() -> void:
	_generation += 1
	_configured = false
	if _web != null and _callback != null:
		_web.unbind(_callback)
	_callback = null
	_web = null
	_lighting_weather = null
