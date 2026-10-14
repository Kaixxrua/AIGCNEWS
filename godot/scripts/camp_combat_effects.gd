extends Node3D
## Local, deterministic combat CHOREOGRAPHY, never a damage simulation.
## Three reusable mesh surfaces; no texture download, particles spawned over
## time, timers, physics, random outcomes, world lights or reward callbacks.
## The owner provides the existing bounded/pauseable presentation clock.

const ROLES := ["hero", "pet", "boss"]
const CYCLE := 5.2
const OFFSETS := {"hero": 0.0, "pet": 1.5, "boss": 3.0}
const ACTIVE_SECONDS := 1.30
const ULTIMATE_PERIOD := CYCLE * 6.0
const ULTIMATE_SECONDS := 3.4
const ULTIMATE_NAMES := {"hero_ranger": "WIND REQUIEM", "hero_knight": "SOLAR CROSS",
	"hero_mage": "PHOENIX NOVA", "hero_bard": "CELESTIAL OVERTURE",
	"hero_alchemist": "EMERALD GENESIS", "hero_astrologer": "ASTRAL JUDGEMENT",
	"boss_ancient_guardian": "RUNIC CATACLYSM"}
const MAX_VERTICES_PER_ROLE := 6000
## Visual calibration only: softer than actor growth, never an arena/AoE scale.
const EFFECT_HEIGHT_REFERENCE := {"hero": 1.8, "pet": 1.2, "boss": 3.0}
const SKILLS := {
	"hero_ranger": ["wind_arrow", Color(0.54, 0.90, 0.65), Color(1.0, 0.87, 0.47)],
	"hero_knight": ["sun_cleave", Color(1.0, 0.75, 0.30), Color(0.72, 0.91, 1.0)],
	"hero_mage": ["ember_orb", Color(1.0, 0.34, 0.13), Color(1.0, 0.86, 0.40)],
	"hero_bard": ["resonance", Color(1.0, 0.77, 0.36), Color(0.76, 0.91, 0.83)],
	"hero_alchemist": ["aether_flask", Color(0.26, 0.88, 0.70), Color(0.94, 1.0, 0.56)],
	"hero_astrologer": ["starfall", Color(0.62, 0.54, 1.0), Color(0.88, 0.91, 1.0)],
	"pet_deer": ["antler_light", Color(0.38, 0.83, 0.84), Color(0.97, 0.88, 0.55)],
	"pet_fox": ["foxfire", Color(1.0, 0.46, 0.16), Color(1.0, 0.85, 0.50)],
	"pet_rabbit": ["moon_dash", Color(0.78, 0.90, 1.0), Color(1.0, 0.91, 0.70)],
	"pet_owl": ["feather_fan", Color(0.53, 0.76, 1.0), Color(0.92, 0.94, 1.0)],
	"pet_finch": ["golden_gale", Color(1.0, 0.81, 0.37), Color(0.68, 0.91, 0.72)],
	"pet_dragon": ["azure_breath", Color(0.24, 0.72, 1.0), Color(0.82, 0.96, 1.0)],
	"boss_ancient_guardian": ["runic_quake", Color(1.0, 0.58, 0.22), Color(0.75, 0.91, 0.93)],
}
const EFFECT_SHADER := """shader_type spatial;
render_mode unshaded, cull_disabled, depth_draw_never;
uniform float night_restraint = 1.0;
void fragment() {
    ALBEDO = COLOR.rgb * night_restraint;
    ALPHA = COLOR.a;
}
"""

var _pool: Dictionary = {}
var _material: ShaderMaterial
var _writer: ImmediateMesh
var _vertices := 0
var _counts: Dictionary = {}
var _styles: Dictionary = {}
var _right := Vector3.RIGHT
var _up := Vector3.UP
var _facing := Vector3.BACK
var _last_clock := 0.0
var _ready_once := false
var _ultimate: Dictionary = {}

static func ultimate_state(clock: float) -> Dictionary:
	var result := {"reserved": false, "active": false, "role": "", "phase": 0.0, "stage": ""}
	if not is_finite(clock) or clock < 0.0 or clock > 1.0e12:
		return result
	# Integer microseconds make the half-open boundaries stable across cycles.
	# In particular 3 * 5.2 must not postpone an event requested at 15.6.
	var within_us := roundi(clock * 1000000.0) % 31200000
	result.reserved = within_us >= 10400000 and within_us < 20800000
	for role: String in ["hero", "boss"]:
		var phase_us := within_us - (10400000 if role == "hero" else 15600000)
		if phase_us >= 0 and phase_us < 3400000:
			result.active = true
			result.role = role
			result.phase = phase_us / 1000000.0
			result.stage = "CHARGE" if phase_us < 950000 else ("UNLEASH" if phase_us < 1500000 else "AFTERGLOW")
			break
	return result

static func ultimate_name(asset_id: String, role: String) -> String:
	return ULTIMATE_NAMES.get(asset_id, "RUNIC CATACLYSM" if role == "boss" else "WIND REQUIEM")

static func skill_for(asset_id: String, role: String) -> Dictionary:
	var fallback: String = {"hero": "hero_ranger", "pet": "pet_deer", "boss": "boss_ancient_guardian"}.get(role, "hero_ranger")
	# Aliased but unknown public catalogue IDs use a safe role-native effect.
	var key := asset_id if SKILLS.has(asset_id) and asset_id.begins_with(role + "_") else fallback
	var spec: Array = SKILLS[key]
	return {"style": spec[0], "color": spec[1], "accent": spec[2]}

func configure() -> void:
	if _ready_once:
		return
	_ready_once = true
	name = "CampCombatEffects"
	set_process(false)
	var shader := Shader.new()
	shader.code = EFFECT_SHADER
	_material = ShaderMaterial.new()
	_material.shader = shader
	# The approved world composites its opaque screen copy at priority 126.
	# Transparent combat surfaces must follow that copy, with depth testing
	# still enabled, or the focus pass silently paints over every light trail.
	_material.render_priority = 127
	for role: String in ROLES:
		var mesh := MeshInstance3D.new()
		mesh.name = role.capitalize() + "Skill"
		mesh.mesh = ImmediateMesh.new()
		mesh.material_override = _material
		mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		mesh.visible = false
		# Depth testing stays enabled: a skill cannot paint through scenery.
		add_child(mesh)
		_pool[role] = mesh
		_counts[role] = 0

func hide_effects() -> void:
	for mesh: MeshInstance3D in _pool.values():
		mesh.visible = false
		(mesh.mesh as ImmediateMesh).clear_surfaces()
	for role: String in ROLES:
		_counts[role] = 0
	_styles.clear()
	_ultimate = ultimate_state(-1.0)

func present(actors: Dictionary, clock: float, mode: String, enabled: bool, camera: Camera3D, night: float) -> void:
	if not _ready_once:
		configure()
	if not enabled or not mode in ["demo", "fighting", "paused"] or not is_finite(clock) or clock < 0 or clock > 1.0e12:
		hide_effects()
		return
	_last_clock = clock
	_ultimate = ultimate_state(clock)
	if is_instance_valid(camera):
		_right = camera.global_basis.x.normalized()
		_up = camera.global_basis.y.normalized()
		_facing = camera.global_basis.z.normalized()
	_material.set_shader_parameter("night_restraint", lerpf(1.0, 0.78, clampf(night, 0.0, 1.0) if is_finite(night) else 0.0))
	for role: String in ROLES:
		var mesh: MeshInstance3D = _pool[role]
		_writer = mesh.mesh
		_writer.clear_surfaces()
		mesh.visible = false
		_counts[role] = 0
		_styles.erase(role)
		var target_role := "hero" if role == "boss" else "boss"
		if not actors.has(role) or not actors.has(target_role):
			continue
		var actor: Dictionary = actors[role]
		var opponent: Dictionary = actors[target_role]
		if not _usable(actor) or not _usable(opponent):
			continue
		# Match the owner's integer-microsecond hit markers. Float modulo can
		# turn 5.8s into phase 0.599999..., delaying an exact 0.60s impact.
		var phase := posmod(roundi(clock * 1000000.0) - roundi(float(OFFSETS[role]) * 1000000.0), 5200000) / 1000000.0
		if _ultimate.reserved:
			if not _ultimate.active or _ultimate.role != role:
				continue
		elif phase > ACTIVE_SECONDS:
			continue
		var source := _body_point(actor, 0.47)
		var target := _body_point(opponent, 0.44)
		var source_scale := _effect_scale(actor, role)
		var target_scale := _effect_scale(opponent, target_role)
		var floor_point: Vector3 = opponent.root.position + Vector3.UP * 0.055
		var skill := skill_for(str(actor.id), role)
		_styles[role] = skill.style
		_vertices = 0
		_writer.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
		if _ultimate.active:
			_styles[role] = "ultimate_" + str(skill.style)
			_draw_ultimate(skill, float(_ultimate.phase), source, target,
				actor.root.position + Vector3.UP * 0.06, floor_point, role, source_scale, target_scale)
		else:
			_draw_skill(skill, phase, source, target, floor_point, int(floorf(clock / CYCLE)), source_scale, target_scale)
		_writer.surface_end()
		_counts[role] = _vertices
		mesh.visible = _vertices > 0
	_writer = null

func present_defeat(actors: Dictionary, age: float, camera: Camera3D, night: float) -> void:
	# Only a presentation call from the owner after a confirmed zero-HP state,
	# or an unauthenticated spectator cycle. Never initiate account settlement.
	if not _ready_once:
		configure()
	hide_effects()
	if not is_finite(age) or age < 0.0 or age >= 3.20 or not actors.has("boss"):
		return
	var boss: Dictionary = actors.boss
	if not _usable(boss, false):
		return
	if is_instance_valid(camera):
		_right = camera.global_basis.x.normalized()
		_up = camera.global_basis.y.normalized()
		_facing = camera.global_basis.z.normalized()
	_material.set_shader_parameter("night_restraint", lerpf(1.0, 0.78, clampf(night, 0.0, 1.0) if is_finite(night) else 0.0))
	# Owner supplies the same frozen/pauseable 3.2s death age and actual pose.
	# Follow its local lean/squash/sink without moving the sprite or foot root.
	var foot: Vector3 = boss.root.position + Vector3.UP * 0.07
	var body_axis: Vector3 = boss.sprite.basis.y
	body_axis = body_axis.normalized() if body_axis.is_finite() and body_axis.length_squared() > 0.000001 else Vector3.UP
	# _body_height already includes positive Sprite Y scale: only rotate here.
	var center: Vector3 = boss.root.position + boss.sprite.position + body_axis * _body_height(boss) * 0.39 + Vector3.UP * 0.07
	if not center.is_finite():
		return
	_writer = _pool.boss.mesh
	_vertices = 0
	_writer.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
	var body_scale := _effect_scale(boss, "boss")
	var fade := 1.0 - smoothstep(0.35, 3.20, age)
	var color := Color(0.83, 0.65, 0.32)
	var stone := Color(0.52, 0.46, 0.34)
	# Retain the accepted terrain-centred radius; never scale up an arena ring.
	_ring(foot, 0.65 + age * 0.34, 0.11 * fade, color, fade * 0.72, true)
	if age < 0.22:
		# 0..0.22: one unmistakable LOCAL finishing blow, not a screen flash.
		var progress := age / 0.22
		var flash := 1.0 - smoothstep(0.0, 0.22, age)
		var at := center + body_axis * _body_height(boss) * 0.05 + _facing * 0.08
		var highlight := Color(1.0, 0.89, 0.62)
		if actors.has("hero") and _usable(actors.hero):
			# The owner's preceding 0.6s final release has just hit. Retain its
			# hero-coloured contact tails, not a new projectile or damage event.
			var hero: Dictionary = actors.hero
			var source := _body_point(hero, 0.47)
			var skill := skill_for(str(hero.id), "hero")
			for index in range(3):
				var contact := at + _up * float(index - 1) * 0.22 * body_scale
				var aim := source.direction_to(contact)
				var length := minf(0.95, source.distance_to(contact)) * (1.0 - progress * 0.35)
				_beam(contact - aim * length, contact, 0.105 * flash, skill.color, flash * 0.82)
				_beam(contact - aim * length * 0.65, contact, 0.035 * flash, skill.accent, flash * 0.94)
		_disc(at, (0.42 + progress * 0.45) * body_scale, color, flash * 0.38)
		_star(at, (0.68 + progress * 0.24) * body_scale, highlight, flash * 0.96, 0.25)
		_crescent(at, 0.86 * body_scale, 0.16 * flash, highlight, flash * 0.92, -0.55 + progress * 0.50)
		_crescent(at, 0.65 * body_scale, 0.11 * flash, color, flash * 0.84, 1.50 - progress * 0.40)
		_ring(foot, 0.40 + progress * 1.15, 0.065 * flash, color, flash * 0.64, true)
	elif age < 1.35:
		# 0.22..1.35: cracking runes/chips accompany the OWNER's visible kneel.
		# Keep this lightweight so it cannot obscure the actual loss of balance.
		for index in range(14):
			var angle := index * TAU / 14.0
			var outward := _right * cos(angle) + _up * sin(angle) * 0.68
			var point := center + outward * (0.30 + age * 0.65) * body_scale + Vector3.UP * (age * 0.40 - age * age * 0.32)
			_arrow(point, Vector3.DOWN, 0.19 * fade * body_scale, stone, fade * 0.94)
			_beam(point, point + Vector3.UP * 0.17, 0.045 * fade, color, fade * 0.65)
		for index in range(3):
			var at := center + _facing * 0.06 + _up * float(index - 1) * 0.28 * body_scale
			var cut := _right * 0.20 * body_scale
			_beam(at - cut + _up * 0.10, at, 0.035, color, fade * 0.78)
			_beam(at, at + cut - _up * 0.10, 0.035, color, fade * 0.78)
	else:
		var collapse := clampf((age - 1.35) / 0.95, 0.0, 1.0)
		if age < 2.30:
			# 1.35..2.30: fourteen finite stone pieces descend to grounded landings.
			# Continuous launch positions follow the last stagger layout.
			var rock_fade := 1.0 - smoothstep(2.05, 2.30, age)
			for index in range(14):
				var angle := index * TAU / 14.0
				var outward := _right * cos(angle) + _up * sin(angle) * 0.68
				var launch := center + outward * 1.1775 * body_scale - Vector3.UP * 0.0432
				var radial := Vector3(cos(angle), 0.0, sin(angle))
				var landing := foot + radial * (0.62 + float(index % 4) * 0.19) + Vector3.UP * 0.27 * body_scale
				var point := launch.lerp(landing, smoothstep(0.0, 1.0, collapse)) + Vector3.UP * sin(collapse * PI) * 0.18
				_arrow(point, Vector3.DOWN, 0.19 * body_scale * rock_fade, stone, rock_fade * 0.94)
				_beam(point, point + Vector3.UP * 0.17, 0.045 * rock_fade, color, rock_fade * 0.55)
		if age < 2.75:
			# Six soft native fans, no textures or particles. Brief dust overlap
			# into the ember phase prevents a visible phase-boundary pop.
			var dust := smoothstep(1.35, 1.55, age) * (1.0 - smoothstep(2.05, 2.75, age))
			for index in range(6):
				var angle := index * TAU / 6.0 + 0.25
				var radius := 0.20 + collapse * 0.24
				var point := foot + Vector3(cos(angle), 0.0, sin(angle)) * (0.62 + collapse * 0.75)
				point.y += radius * Vector2(_right.y, _up.y).length() + 0.02
				_disc(point, radius, stone, dust * 0.24)
			_ring(foot + Vector3.UP * 0.018, 0.85 + collapse * 0.85, 0.09 * dust, stone, dust * 0.38, true)
		if age >= 2.30:
			# 2.30..3.20: the body/rocks are gone; only small warm embers remain.
			var tail := (age - 2.30) / 0.90
			var ember_fade := 1.0 - smoothstep(0.0, 1.0, tail)
			for index in range(10):
				var angle := index * TAU / 10.0 + 0.35
				var point := foot + Vector3(cos(angle), 0.0, sin(angle)) * (0.45 + float(index % 4) * 0.19)
				point.y += 0.30 + float(index % 3) * 0.16 + tail * 0.32
				_star(point, 0.11 * body_scale * ember_fade, color, ember_fade * 0.68, angle)
				_beam(point, point - Vector3.UP * 0.12, 0.025 * ember_fade, color, ember_fade * 0.42)
	_writer.surface_end()
	_counts.boss = _vertices
	_styles.boss = "guardian_defeat"
	_pool.boss.visible = true
	_writer = null

func _usable(actor: Dictionary, require_visible: bool = true) -> bool:
	return actor.has("root") and is_instance_valid(actor.root) and (not require_visible or actor.root.visible) \
		and actor.get("safe", false) and actor.has("sprite") and is_instance_valid(actor.sprite) \
		and actor.has("height") and is_finite(float(actor.height)) and float(actor.height) > 0.0 \
		and actor.root.position.is_finite() and is_finite(actor.sprite.position.y)

func _body_height(actor: Dictionary) -> float:
	# Owner scales pixel_size/height/heads, not root.scale. Cached alpha>=32
	# head heights exclude transparent atlas padding. Sprite Y scale is normally
	# 1; the owner's death kneel may squash it. Apply it once, never to hover.
	var height := float(actor.height)
	var heads: Variant = actor.get("heads")
	var frame: Variant = actor.get("frame", -1)
	if heads is Array and frame is int and frame >= 0 and frame < heads.size():
		var head: Variant = heads[frame]
		if (head is int or head is float) and is_finite(float(head)) and head > 0.0 and head <= height:
			height = float(head)
	var sprite := actor.get("sprite") as Node3D
	var scale_y: float = sprite.scale.y if is_instance_valid(sprite) else 1.0
	var scaled := height * scale_y
	return scaled if is_finite(scale_y) and scale_y > 0.0 and is_finite(scaled) and scaled > 0.0 else height

func _body_point(actor: Dictionary, fraction: float) -> Vector3:
	return actor.root.position + Vector3.UP * (_body_height(actor) * fraction + actor.sprite.position.y)

func _effect_scale(actor: Dictionary, role: String) -> float:
	# No new input keys. Legacy/test actors keep their original effect sizes.
	if not actor.has("heads"):
		return 1.0
	return clampf(sqrt(_body_height(actor) / float(EFFECT_HEIGHT_REFERENCE[role])), 0.85, 1.30)

func _draw_skill(skill: Dictionary, phase: float, source: Vector3, target: Vector3, floor_point: Vector3, cycle_index: int,
		source_scale: float = 1.0, target_scale: float = 1.0) -> void:
	var color: Color = skill.color
	var accent: Color = skill.accent
	var style: String = skill.style
	var aim := source.direction_to(target)
	if phase < 0.30:
		var charge := smoothstep(0.0, 0.30, phase)
		_ring(source, (0.18 + charge * 0.32) * source_scale, 0.045, color, 0.35 + charge * 0.40, false, -phase * 4.0)
		_star(source, (0.10 + charge * 0.23) * source_scale, accent, 0.70, phase * 2.0)
		for index in range(4):
			var angle := index * TAU / 4.0 + phase * 4.0
			var offset := (_right * cos(angle) + _up * sin(angle)) * (0.80 - charge * 0.42) * source_scale
			_beam(source + offset, source + offset * 0.62, 0.045, color, charge * 0.75)
		if style == "runic_quake":
			_ring(floor_point, 0.90 + charge * 0.25, 0.055, color, 0.48, true)
		return
	# Arrive on the same 0.60s frame that starts the target burst below.
	var travel := clampf((phase - 0.30) / 0.30, 0.0, 1.0)
	var impact := clampf((phase - 0.60) / 0.70, 0.0, 1.0)
	var fade := 1.0 - smoothstep(0.66, 1.30, phase)
	var strike_scale := lerpf(source_scale, target_scale, travel)
	if style == "runic_quake":
		_guardian(phase, travel, impact, source, target, floor_point, color, accent, cycle_index, target_scale)
	elif phase < 0.66:
		match style:
			"wind_arrow", "feather_fan", "golden_gale":
				for index in range(3):
					var spread := float(index - 1) * 0.34
					var end := target + _up * spread
					var point := source.lerp(end, travel) + _up * sin(travel * PI) * spread
					var direction := source.direction_to(end)
					_beam(point - direction * 0.85, point, 0.12, color, 0.80)
					_arrow(point, direction, 0.25, accent, 0.96)
			"sun_cleave", "moon_dash":
				var point := source.lerp(target, travel)
				_crescent(point, (0.90 if style == "sun_cleave" else 0.62) * strike_scale, 0.16, color, 0.87, -0.60 + travel * 2.4)
				_crescent(point - aim * 0.28, 0.78 * strike_scale, 0.055, accent, 0.70, -0.75 + travel * 2.4)
			"azure_breath":
				var end := source.lerp(target, travel)
				_beam(source, end, 0.48, color, 0.24)
				_beam(source, end, 0.15, accent, 0.84)
				for index in range(5):
					var part := float(index + 1) / 6.0
					var point := source.lerp(end, part) + _up * sin(part * 12.0 - phase * 15.0) * 0.11
					_disc(point, 0.14 + part * 0.12, color, 0.45)
			"resonance", "antler_light":
				var point := source.lerp(target, travel)
				_ring(point, 0.30 + travel * 0.46, 0.08, color, 0.80, false, travel)
				_ring(point - aim * 0.42, 0.23 + travel * 0.30, 0.045, accent, 0.65, false)
				_star(point, 0.19, accent, 0.90, phase * 3.0)
			"starfall":
				for index in range(3):
					var end := target + _right * float(index - 1) * 0.36
					var start := source.lerp(target, 0.40) + Vector3.UP * (2.0 + index * 0.30)
					var point := start.lerp(end, travel)
					_beam(point - start.direction_to(end) * 0.80, point, 0.13, color, 0.68)
					_star(point, 0.30, accent, 0.94, phase * 3.0)
			"foxfire":
				for index in range(3):
					var point := source.lerp(target, travel) + _up * float(index - 1) * 0.24
					_crescent(point, 0.43, 0.09, color, 0.78, -0.6 + phase * 1.5)
					_beam(point - aim * 0.42, point, 0.09, accent, 0.84)
			_:
				var point := source.lerp(target, travel)
				if style == "aether_flask":
					point += Vector3.UP * sin(travel * PI) * 1.35
				_beam(point - aim * 0.85, point, 0.22, color, 0.48)
				_disc(point, 0.48, color, 0.50)
				_star(point, 0.27, accent, 0.95, -phase * 3.0)
	if phase >= 0.60 and style != "runic_quake":
		# A brief concentrated contact point, then readable coloured fragments.
		_disc(target, (0.26 + impact * 0.75) * target_scale, color, fade * 0.35)
		_star(target, (0.46 + impact * 0.45) * fade * target_scale, accent, fade * 0.90, 0.35)
		_ring(target, (0.26 + impact * 0.96) * target_scale, 0.10 * fade, color, fade * 0.72, false)
		if style == "sun_cleave" or style == "moon_dash":
			_crescent(target, 1.1 * target_scale, 0.14 * fade, accent, fade * 0.86, impact * 2.0)
		if style == "aether_flask":
			_ring(floor_point, 0.30 + impact * 1.05, 0.12 * fade, color, fade * 0.65, true)
		for index in range(7):
			var angle := index * TAU / 7.0 + cycle_index * 0.70
			var direction := _right * cos(angle) + _up * sin(angle)
			var point := target + direction * (0.40 + impact * 1.1) * target_scale - Vector3.UP * impact * impact * 0.30
			_beam(point - direction * 0.16, point, 0.055 * fade, accent if index % 2 == 0 else color, fade * 0.82)

func _guardian(phase: float, travel: float, impact: float, source: Vector3, target: Vector3, floor_point: Vector3, color: Color, accent: Color, cycle_index: int,
		target_scale: float = 1.0) -> void:
	var fade := 1.0 - smoothstep(0.68, 1.30, phase)
	if phase < 0.63:
		_ring(floor_point, 1.20, 0.07, color, 0.58, true)
		for index in range(3):
			var point := source.lerp(target, travel) + _up * (sin(travel * PI) * 0.7 + float(index - 1) * 0.23)
			_beam(point - source.direction_to(target) * 0.65, point, 0.17, color, 0.64)
			_star(point, 0.23, accent, 0.86, float(index) + phase)
	if phase >= 0.60:
		_ring(floor_point, 0.25 + impact * 1.85, 0.18 * fade, color, fade * 0.76, true)
		_ring(floor_point + Vector3.UP * 0.035, 0.20 + impact * 1.52, 0.055 * fade, accent, fade * 0.68, true)
		for index in range(8):
			var angle := index * TAU / 8.0 + cycle_index * 0.42
			var radial := Vector3(cos(angle), 0, sin(angle))
			var base := floor_point + radial * (0.25 + impact * 1.05)
			var peak := base + Vector3.UP * (sin(impact * PI) * (0.50 + float(index % 3) * 0.22))
			# Stone-coloured shards with an amber edge, not a full-screen flash.
			_arrow(peak, Vector3.UP, 0.18 * fade, Color(0.35, 0.31, 0.23), fade * 0.96)
			_beam(base, peak, 0.055 * fade, color, fade * 0.68)
		_star(target, 0.54 * fade * target_scale, accent, fade * 0.72, impact)

func _draw_ultimate(skill: Dictionary, phase: float, source: Vector3, target: Vector3,
		caster_floor: Vector3, target_floor: Vector3, role: String, source_scale: float = 1.0, target_scale: float = 1.0) -> void:
	var color: Color = skill.color
	var accent: Color = skill.accent
	var style: String = skill.style
	var charge := smoothstep(0.0, 0.95, phase)
	# The 1.43s marker is contact, not 20ms before projectile arrival.
	var flight := clampf((phase - 0.95) / 0.48, 0.0, 1.0)
	var release := clampf((phase - 1.43) / 1.97, 0.0, 1.0)
	var fade := 1.0 - smoothstep(1.63, 3.40, phase)
	var direction := source.direction_to(target)
	# Already-large ultimate impacts get only half the local size adjustment.
	# Every ground rune/quake retains its original terrain centre and radius.
	var impact_scale := lerpf(1.0, target_scale, 0.5)
	var strike_scale := lerpf(source_scale, target_scale, flight)
	# Keep the anticipation substantially longer than the ordinary skills.
	# Converging fragments, rotating floor runes and two thin body-level rings
	# supply scale without a solid sphere obscuring the original actor artwork.
	if phase < 1.12:
		var hold := 1.0 - smoothstep(0.95, 1.12, phase)
		_ring(caster_floor, 0.75 + charge * 0.65, 0.07, color, hold * 0.70, true)
		_ring(caster_floor + Vector3.UP * 0.025, 0.58 + charge * 0.49, 0.035, accent, hold * 0.70, true)
		for index in range(10):
			var angle := index * TAU / 10.0 + phase * 1.35
			var radial := Vector3(cos(angle), 0, sin(angle))
			var at := caster_floor + radial * (1.08 + charge * 0.65)
			_triangle(at - radial * 0.13, at + radial.cross(Vector3.UP) * 0.10,
				at - radial.cross(Vector3.UP) * 0.10, accent, hold * 0.74)
			var offset := (_right * cos(angle) + _up * sin(angle)) * (1.25 - charge * 0.67) * source_scale
			_beam(source + offset, source + offset * 0.76, 0.065, color, charge * hold * 0.75)
		_ring(source, (0.30 + charge * 0.40) * source_scale, 0.065, color, hold * 0.72, false)
		_star(source, (0.20 + charge * 0.20) * source_scale, accent, hold * 0.70, phase)
		if role == "boss":
			_ring(target_floor, 1.55, 0.075, color, 0.65 * hold, true)
			_ring(target_floor + Vector3.UP * 0.025, 1.35, 0.035, accent, 0.50 * hold, true)
	if phase >= 0.95 and phase < 1.53:
		if role == "boss":
			for index in range(5):
				var point := source.lerp(target, flight) + Vector3.UP * sin(flight * PI) * (0.75 + index * 0.20)
				point += _right * float(index - 2) * 0.22
				_beam(point - direction * 0.85, point, 0.18, color, 0.79)
				_star(point, 0.34, accent, 0.83, index * 0.5)
		else:
			match style:
				"wind_arrow":
					for index in range(5):
						var bow := float(index - 2) * 0.40
						var end := target + _up * bow * 0.40
						var point := source.lerp(end, flight) + _up * sin(flight * PI) * bow
						_beam(point - direction * 1.50, point, 0.16, color, 0.82)
						_beam(point - direction, point, 0.060, accent, 0.95)
						_arrow(point, direction, 0.34, accent, 0.94)
				"sun_cleave":
					var point := source.lerp(target, flight)
					_crescent(point, 1.55 * strike_scale, 0.26, color, 0.89, -0.50 + flight * 2.2)
					_crescent(point, 1.32 * strike_scale, 0.13, accent, 0.91, 1.70 - flight * 2.2)
				"resonance":
					for index in range(4):
						var point := source.lerp(target, clampf(flight - index * 0.12, 0.0, 1.0))
						_ring(point, 0.45 + float(4 - index) * 0.19, 0.10, color if index % 2 == 0 else accent, 0.75, false)
				"aether_flask":
					for index in range(3):
						var point := source.lerp(target + _right * float(index - 1) * 0.42, flight)
						point += Vector3.UP * sin(flight * PI) * (1.45 + index * 0.30)
						_beam(point - direction * 0.55, point, 0.16, color, 0.72)
						_star(point, 0.35, accent, 0.94, phase * 2.0)
				"starfall":
					for index in range(6):
						var angle := index * TAU / 6.0
						var radial := (_right * cos(angle) + _up * sin(angle)) * 1.10
						var start := target + Vector3.UP * 3.8 + radial
						var point := start.lerp(target + radial * 0.35, flight)
						_beam(point - Vector3.DOWN * 0.82, point, 0.16, color, 0.78)
						_star(point, 0.34, accent, 0.91, phase)
				_:
					var point := source.lerp(target, flight)
					_disc(point, 1.00, color, 0.43)
					_crescent(point, 0.60, 0.22, color, 0.91, phase * 4.0)
					_crescent(point, 0.54, 0.14, accent, 0.85, -phase * 4.0)
					_star(point, 0.41, accent, 0.89, phase * 2.0)
	if phase >= 1.43:
		if role == "boss":
			_ring(target_floor, 0.32 + release * 2.70, 0.24 * fade, color, fade * 0.86, true)
			_ring(target_floor + Vector3.UP * 0.03, 0.22 + release * 2.26, 0.07 * fade, accent, fade * 0.72, true)
			for index in range(12):
				var angle := index * TAU / 12.0
				var radial := Vector3(cos(angle), 0, sin(angle))
				var base := target_floor + radial * (0.45 + release * 1.65)
				var peak := base + Vector3.UP * sin(release * PI) * (0.80 + index % 3 * 0.23)
				_arrow(peak, Vector3.UP, 0.31 * fade, Color(0.43, 0.38, 0.26), fade * 0.98)
				_beam(base, peak, 0.085 * fade, color, fade * 0.74)
		else:
			_ring(target, (1.00 + release * 1.85) * impact_scale, 0.17 * fade, color, fade * 0.82, false)
			if style == "sun_cleave":
				_crescent(target, 1.8 * impact_scale, 0.19 * fade, accent, fade * 0.86, -0.70 + release)
				_crescent(target, 1.6 * impact_scale, 0.13 * fade, color, fade * 0.79, 1.50 - release)
			if style == "aether_flask" or style == "starfall":
				_ring(target_floor, 0.50 + release * 1.80, 0.10 * fade, color, fade * 0.64, true)
			for index in range(12):
				var angle := index * TAU / 12.0 + 0.35
				var outward := _right * cos(angle) + _up * sin(angle)
				var point := target + outward * (1.05 + release * 1.85) * impact_scale - Vector3.UP * release * release * 0.42
				_beam(point - outward * 0.28, point, 0.08 * fade, accent if index % 2 == 0 else color, fade * 0.85)
		_disc(target, (0.65 + release * 0.70) * impact_scale, color, fade * 0.24)
		_star(target, (0.72 + release * 0.40) * fade * impact_scale, accent, fade * 0.74, 0.35)

func _vertex(point: Vector3, color: Color, alpha: float) -> void:
	_writer.surface_set_color(Color(color.r, color.g, color.b, clampf(alpha, 0.0, 1.0)))
	_writer.surface_add_vertex(point)
	_vertices += 1

func _triangle(a: Vector3, b: Vector3, c: Vector3, color: Color, alpha: float) -> void:
	if _vertices + 3 > MAX_VERTICES_PER_ROLE:
		return
	_vertex(a, color, alpha)
	_vertex(b, color, alpha)
	_vertex(c, color, alpha)

func _beam(start: Vector3, finish: Vector3, width: float, color: Color, alpha: float) -> void:
	if start.distance_squared_to(finish) < 0.00001 or width <= 0.001:
		return
	var side := (finish - start).cross(_facing).normalized() * width * 0.5
	_triangle(start - side, start + side, finish + side, color, alpha)
	_triangle(start - side, finish + side, finish - side, color, alpha)

func _arrow(point: Vector3, direction: Vector3, radius: float, color: Color, alpha: float) -> void:
	var side := direction.cross(_facing).normalized()
	_triangle(point + direction * radius, point - direction * radius + side * radius * 0.58,
		point - direction * radius - side * radius * 0.58, color, alpha)

func _disc(center: Vector3, radius: float, color: Color, alpha: float) -> void:
	for index in range(16):
		if _vertices + 3 > MAX_VERTICES_PER_ROLE:
			return
		var a := float(index) * TAU / 16.0
		var b := float(index + 1) * TAU / 16.0
		_vertex(center, color, alpha)
		_vertex(center + (_right * cos(a) + _up * sin(a)) * radius, color, 0.0)
		_vertex(center + (_right * cos(b) + _up * sin(b)) * radius, color, 0.0)

func _star(center: Vector3, radius: float, color: Color, alpha: float, rotation: float = 0.0) -> void:
	for index in range(8):
		var a := float(index) * TAU / 8.0 + rotation
		var b := float(index + 1) * TAU / 8.0 + rotation
		var ra := radius if index % 2 == 0 else radius * 0.24
		var rb := radius if index % 2 == 1 else radius * 0.24
		_triangle(center, center + (_right * cos(a) + _up * sin(a)) * ra,
			center + (_right * cos(b) + _up * sin(b)) * rb, color, alpha)

func _ring(center: Vector3, radius: float, width: float, color: Color, alpha: float, ground: bool, rotation: float = 0.0) -> void:
	var x_axis := Vector3.RIGHT if ground else _right
	var y_axis := Vector3.BACK if ground else _up
	for index in range(32):
		var a := float(index) * TAU / 32.0 + rotation
		var b := float(index + 1) * TAU / 32.0 + rotation
		var u := x_axis * cos(a) + y_axis * sin(a)
		var v := x_axis * cos(b) + y_axis * sin(b)
		_triangle(center + u * radius, center + u * (radius + width), center + v * (radius + width), color, alpha)
		_triangle(center + u * radius, center + v * (radius + width), center + v * radius, color, alpha)

func _crescent(center: Vector3, radius: float, width: float, color: Color, alpha: float, rotation: float) -> void:
	for index in range(20):
		var t := float(index) / 20.0
		var next := float(index + 1) / 20.0
		var a := lerpf(-1.7, 1.7, t) + rotation
		var b := lerpf(-1.7, 1.7, next) + rotation
		var u := _right * cos(a) + _up * sin(a)
		var v := _right * cos(b) + _up * sin(b)
		var w1 := width * sin(t * PI)
		var w2 := width * sin(next * PI)
		_triangle(center + u * radius, center + u * (radius + w1), center + v * (radius + w2), color, alpha)
		_triangle(center + u * radius, center + v * (radius + w2), center + v * radius, color, alpha)

func debug_state() -> Dictionary:
	var shown: Array = []
	for role: String in _pool:
		if _pool[role].visible:
			shown.append(role)
	return {"poolSize": _pool.size(), "vertices": _counts.duplicate(), "activeRoles": shown,
		"styles": _styles.duplicate(), "clock": _last_clock, "vertexLimit": MAX_VERTICES_PER_ROLE,
		"ultimate": _ultimate.duplicate()}
