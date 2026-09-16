extends Node3D
## Ambient fauna only, not future combat AI. One distinct animal of each species.
## Every frame/move reads the existing weather clock; pausing cannot cause jumps.

const CUTOUT = preload("res://shaders/meadow_cutout.gdshader")
const ANIMAL_SHADER = preload("res://shaders/meadow_animal.gdshader")
const SPIRIT_AURA = preload("res://shaders/meadow_spirit_aura.gdshader")
const ART = preload("res://scripts/meadow_fauna_art.gd")
const DRAGON_ART = preload("res://scripts/meadow_dragon_art.gd")
const DRAGON_SHADER = preload("res://shaders/meadow_dragon.gdshader")
const HABITATS := [Rect2(-8, 0, 8, 6), Rect2(-22, -20, 10, 9), Rect2(9, -10, 9, 8), Rect2(-15, -24, 13, 18)]
const SPECIES := ["MeadowHare", "MeadowDeer", "MeadowFox"]
const SPEEDS := [1.35, 1.05, 1.20, 1.10]
const STRIDE_LENGTHS := [1.0, 1.10, 1.05, 1.25]
const DRAGON_SPAN := 25.0
const DRAGON_PIXEL_SCALE := DRAGON_SPAN / 225.0
const DRAGON_SPEED := 11.0
## Open valley sky between the raised left ridge and the tallest castle towers.
## Keep room for the entire downstroke; preserve real size, depth and B-spline motion.
const FLIGHT_FRAME := Rect2(0.28, 0.059, 0.34, 0.017)
const FLIGHT_DEPTH := Vector2(-460.0, -355.0)
const HALO = preload("res://shaders/meadow_light_halo.gdshader")

var meadow: Node3D
var weather: Node
var animals: Array[Dictionary] = []
var rng := RandomNumberGenerator.new()
var ground_surface: TriangleMesh
var rock_surface: TriangleMesh
var obstacles: Array[Vector3] = []
var last_clock := 0.0
var dragon: MeshInstance3D
var dragon_texture: Texture2D
var dragon_frames: Array[Rect2] = []
var dragon_frame := 0
var dragon_view := -1
var previous_dragon_view := 0
var previous_dragon_frame := 0
var dragon_turn_mix := 1.0
var distance_travelled := 0.0
var flight_rng := RandomNumberGenerator.new()
var flight_points: Array[Vector3] = []
var flight_phase := 0.0
var flight_legs := 0
var flight_velocity := Vector3.ZERO
var dragon_bank := 0.0
var night_light: OmniLight3D
var night_halo: MeshInstance3D
var night_aura: MeshInstance3D

func setup(scene: Node3D) -> void:
	meadow = scene
	weather = scene.get_node("LivingWeather")
	last_clock = weather.animation_clock
	# Fresh paths each visit; audit can set an explicit seed before advance().
	rng.randomize()
	ground_surface = scene.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	rock_surface = scene.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	for child in scene.get_children():
		if child.has_meta("scrub_stone_obstacles"):
			for obstacle: Vector3 in child.get_meta("scrub_stone_obstacles"):
				obstacles.append(obstacle)
		if not child is MeshInstance3D or not child.has_meta("art_foot"):
			continue
		if child.has_meta("herb_roots"):
			# A short chain of disks follows the new curved low shrub footprint.
			# Readable animals route around its body instead of walking through art.
			var herb_roots: PackedVector3Array = child.get_meta("herb_roots")
			for i in range(0, herb_roots.size(), 8):
				var herb_root: Vector3 = herb_roots[i]
				obstacles.append(Vector3(herb_root.x, herb_root.z, 0.45))
			var last_root := herb_roots[herb_roots.size() - 1]
			obstacles.append(Vector3(last_root.x, last_root.z, 0.45))
		var label: String = child.name
		if label.contains("Oak") or label.contains("Hawthorn") or label.contains("Hazel") or label.contains("Boulder") or label.contains("Lamp") or label.contains("Lantern"):
			var foot: Vector2 = child.get_meta("art_foot")
			obstacles.append(Vector3(foot.x, foot.y, clampf(float(child.get_meta("art_width")) * 0.19, 0.6, 4.0)))
	for i in range(3):
		var valid := PackedVector2Array()
		var bounds: Rect2 = HABITATS[i]
		for z in range(9):
			for x in range(13):
				var point := bounds.position + bounds.size * Vector2(x / 12.0, z / 8.0)
				if safe_point(point):
					valid.append(point)
		assert(valid.size() >= 10, "Wildlife habitat needs enough safe ground")
		var start := valid[valid.size() / 2]
		var atlas: Dictionary = ART.get_animal(i)
		var texture: Texture2D = atlas.texture
		var card := make_card(SPECIES[i], texture, Rect2(Vector2.ZERO, Vector2(texture.get_width(), texture.get_height())), atlas.display, atlas.anchors[0])
		_use_animal_material(card, texture)
		card.position = ground_point(start)
		var state := {"node": card, "points": valid, "point": start, "target": start,
			"wait": 0.3 + i * 0.6, "speed": SPEEDS[i], "velocity": 0.0, "frame": 0, "stride": 0.0,
			"moving": false, "turns": 0, "row": i, "travel": 0.0,
			"texture": texture, "frames": atlas.frames, "anchors": atlas.anchors,
			"night_only": false, "base_speed": SPEEDS[i], "cycle_length": STRIDE_LENGTHS[i],
			"phase": 0.0, "settle": 0.0, "presence": 1.0, "rest_frames": [0, 7] if i == 0 else [0, 4]}
		_apply_animal_frame(state)
		animals.append(state)
		print("MEADOW_WILDLIFE_HABITAT: %s; %d safe points; root %s" % [SPECIES[i], valid.size(), start])
	_setup_nocturnal_stag()
	dragon_texture = DRAGON_ART.TEXTURE
	dragon_frames = DRAGON_ART.FRAMES
	# Actual 3D world flight through the sky, with distance-dependent size.
	dragon = make_card("CirclingCastleDragon", dragon_texture,
		Rect2(Vector2.ZERO, Vector2(dragon_texture.get_width(), dragon_texture.get_height())),
		DRAGON_ART.CANVAS * DRAGON_PIXEL_SCALE, DRAGON_ART.PIVOT / DRAGON_ART.CANVAS)
	dragon.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var flight_material := ShaderMaterial.new()
	flight_material.shader = DRAGON_SHADER
	flight_material.render_priority = 127
	flight_material.set_shader_parameter("asset_texture", dragon_texture)
	dragon.material_override = flight_material
	flight_rng.randomize()
	reset_flight(flight_rng.randi())
	_update_dragon(last_clock, 0.0)
	print("MEADOW_WILDLIFE_READY: 3 distinct eight-frame fantasy animals; one nocturnal luminous stag; random 3D sky dragon; shared pausable clock")

func _setup_nocturnal_stag() -> void:
	var valid := PackedVector2Array()
	for z in range(9):
		for x in range(13):
			var point: Vector2 = HABITATS[3].position + HABITATS[3].size * Vector2(x / 12.0, z / 8.0)
			if safe_point(point):
				valid.append(point)
	assert(valid.size() >= 10, "Nocturnal wildlife needs safe traversable habitat")
	var atlas: Dictionary = ART.get_animal(3)
	var texture: Texture2D = atlas.texture
	var size := Vector2(texture.get_width(), texture.get_height())
	var card := make_card("MoonlitStag", texture, Rect2(Vector2.ZERO, size), atlas.display, atlas.anchors[0])
	_use_animal_material(card, texture)
	# Its local pool lights grass/props, not the fur a second time. Sun, moon
	# and nearby lanterns still affect this second visual layer normally.
	card.layers = 2
	var start := valid[valid.size() / 2]
	card.position = ground_point(start)
	var state := {"node": card, "points": valid, "point": start, "target": start,
		"wait": 0.6, "speed": SPEEDS[3], "velocity": 0.0, "frame": 0, "stride": 0.0, "moving": false,
		"turns": 0, "row": 3, "travel": 0.0, "texture": texture,
		"frames": atlas.frames, "anchors": atlas.anchors, "night_only": true, "base_speed": SPEEDS[3],
		"cycle_length": STRIDE_LENGTHS[3], "phase": 0.0, "settle": 0.0, "presence": 0.0, "rest_frames": [0, 4]}
	animals.append(state)
	_apply_animal_frame(state)
	night_light = OmniLight3D.new()
	night_light.name = "MoonStagGroundLight"
	night_light.light_color = Color(0.45, 0.80, 1.0)
	night_light.light_cull_mask = 1
	night_light.omni_range = 4.0
	night_light.omni_attenuation = 1.5
	night_light.shadow_enabled = false
	add_child(night_light)
	night_halo = MeshInstance3D.new()
	night_halo.name = "MoonStagAntlerHalo"
	var glow_quad := QuadMesh.new()
	glow_quad.size = Vector2(1.65, 1.65)
	night_halo.mesh = glow_quad
	night_halo.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var glow := ShaderMaterial.new()
	glow.shader = HALO
	glow.render_priority = 127
	glow.set_shader_parameter("glow_color", Color(0.38, 0.73, 1.0))
	glow.set_shader_parameter("glow_strength", 0.40)
	night_halo.material_override = glow
	add_child(night_halo)
	night_aura = MeshInstance3D.new()
	night_aura.name = "MoonStagSoftAura"
	var aura_quad := QuadMesh.new()
	aura_quad.size = Vector2(3.35, 3.80)
	night_aura.mesh = aura_quad
	night_aura.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var aura := ShaderMaterial.new()
	aura.shader = SPIRIT_AURA
	aura.render_priority = 127
	aura.set_shader_parameter("strength", 0.25)
	night_aura.material_override = aura
	add_child(night_aura)
	_update_night_visibility()
	print("MEADOW_NOCTURNAL_READY: one unique eight-frame moon stag; %d safe points; soft body aura + antler halo + real moving local light" % valid.size())

func _use_animal_material(card: MeshInstance3D, texture: Texture2D) -> void:
	var material := ShaderMaterial.new()
	material.shader = ANIMAL_SHADER
	# The focus quad (126) reads the opaque pass. True-alpha creatures must
	# follow it, like the transparent water; keep normal scene depth testing.
	material.render_priority = 127
	material.set_shader_parameter("asset_texture", texture)
	card.material_override = material

func make_card(label: String, texture: Texture2D, reserved: Rect2, display: Vector2, anchor: Vector2) -> MeshInstance3D:
	var size := Vector2(texture.get_width(), texture.get_height())
	var reserved_uv := Rect2(reserved.position / size, reserved.size / size)
	var existing: Array = meadow.occupied_art_regions.get(texture.resource_path, [])
	for region: Rect2 in existing:
		assert(not region.intersects(reserved_uv), "An animated individual is used only once")
	existing.append(reserved_uv)
	meadow.occupied_art_regions[texture.resource_path] = existing
	meadow.asset_paths[texture.resource_path + "@" + str(reserved_uv)] = label
	var quad := QuadMesh.new()
	quad.size = display
	quad.center_offset = Vector3((0.5 - anchor.x) * display.x, (anchor.y - 0.5) * display.y, 0)
	var card := MeshInstance3D.new()
	card.name = label
	card.mesh = quad
	card.extra_cull_margin = display.length()
	var material := ShaderMaterial.new()
	material.shader = CUTOUT
	material.set_shader_parameter("asset_texture", texture)
	material.set_shader_parameter("alpha_threshold", 0.22)
	material.set_shader_parameter("edge_inset", 0.0)
	material.set_shader_parameter("painted_fill", 0.06)
	material.set_shader_parameter("relief_strength", 0.22)
	material.set_shader_parameter("mip_bias", -0.25)
	material.set_shader_parameter("art_exposure", 0.88)
	card.material_override = material
	card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_DOUBLE_SIDED
	add_child(card)
	return card

func safe_point(p: Vector2) -> bool:
	if meadow.distance_to_road(p) < meadow.road_half_width(p.y) + 0.8 or p.distance_to(meadow.BOSS_CENTER) < 6.5:
		return false
	if absf(p.x - meadow.river_center(p.y)) < meadow.river_half_width(p.y) + 2.0:
		return false
	if meadow.terrain_normal(p.x, p.y).y < 0.94:
		return false
	for obstacle: Vector3 in obstacles:
		if p.distance_to(Vector2(obstacle.x, obstacle.y)) < obstacle.z + 0.72:
			return false
	# Check a body-sized footprint against the real rock triangles, not just
	# the smooth terrain height field. Grass sprites have no collision here.
	for offset: Vector2 in [Vector2.ZERO, Vector2(0.72, 0), Vector2(-0.72, 0), Vector2(0, 0.72), Vector2(0, -0.72)]:
		var q := p + offset
		var rock := rock_surface.intersect_ray(Vector3(q.x, 75, q.y), Vector3.DOWN)
		if not rock.is_empty():
			var ground := ground_surface.intersect_ray(Vector3(q.x, 75, q.y), Vector3.DOWN)
			if ground.is_empty() or float(rock.position.y) - float(ground.position.y) > 0.065:
				return false
	return true

func safe_segment(a: Vector2, b: Vector2) -> bool:
	var steps := maxi(1, ceili(a.distance_to(b) / 0.25))
	for step in range(steps + 1):
		if not safe_point(a.lerp(b, float(step) / steps)):
			return false
	return true

func ground_point(p: Vector2) -> Vector3:
	var hit := ground_surface.intersect_ray(Vector3(p.x, 75, p.y), Vector3.DOWN)
	assert(not hit.is_empty())
	var surface_y: float = hit.position.y
	var rock := rock_surface.intersect_ray(Vector3(p.x, 75, p.y), Vector3.DOWN)
	if not rock.is_empty():
		surface_y = maxf(surface_y, float(rock.position.y))
	return Vector3(p.x, surface_y + 0.018, p.y)

func _process(_delta: float) -> void:
	if weather == null:
		return
	advance(float(weather.animation_clock))

func advance(clock: float) -> void:
	var delta := clampf(clock - last_clock, 0.0, 0.25)
	last_clock = clock
	# Day/night can change while motion is paused; appearance must still follow.
	_update_night_visibility()
	if delta <= 0.0:
		return
	for state: Dictionary in animals:
		if float(state.presence) <= 0.01:
			continue
		if not state.moving:
			_settle_gait(state, delta)
			state.wait -= delta
			if state.wait <= 0.0:
				_choose_target(state)
			continue
		var point: Vector2 = state.point
		var target: Vector2 = state.target
		var distance := point.distance_to(target)
		var desired_speed: float = float(state.speed) * smoothstep(0.0, 0.60, distance)
		state.velocity = move_toward(float(state.velocity), maxf(0.20, desired_speed), delta * 3.5)
		var next := point.move_toward(target, float(state.velocity) * delta)
		if not safe_point(next) or not _animal_space_free(state, next):
			state.moving = false
			state.wait = rng.randf_range(0.4, 0.9)
			state.velocity = 0.0
			continue
		var moved := point.distance_to(next)
		state.point = next
		state.travel += moved
		distance_travelled += moved
		state.stride += moved
		var card: MeshInstance3D = state.node
		card.position = ground_point(next)
		if absf(target.x - point.x) > 0.05:
			card.material_override.set_shader_parameter("sprite_flip", target.x < point.x)
		state.phase = fmod(float(state.phase) + moved / float(state.cycle_length) * state.frames.size(), float(state.frames.size()))
		state.frame = int(state.phase)
		_apply_animal_frame(state)
		if next.distance_to(target) < 0.015:
			state.moving = false
			state.wait = rng.randf_range(1.2, 4.0)
			state.velocity = 0.0
	_update_night_visibility()
	_update_dragon(clock, delta)

func _settle_gait(state: Dictionary, delta: float) -> void:
	# Finish the short recovery into the next planted pose; don't snap to frame 0.
	if state.frame in state.rest_frames:
		return
	state.settle += delta * 10.0
	while state.settle >= 1.0:
		state.settle -= 1.0
		state.frame = (int(state.frame) + 1) % state.frames.size()
		state.phase = float(state.frame)
		_apply_animal_frame(state)
		if state.frame in state.rest_frames:
			state.settle = 0.0
			break

func _apply_animal_frame(state: Dictionary) -> void:
	var card: MeshInstance3D = state.node
	var anchor: Vector2 = state.anchors[state.frame]
	if card.material_override.get_shader_parameter("sprite_flip") == true:
		anchor.x = 1.0 - anchor.x
	var quad: QuadMesh = card.mesh
	quad.center_offset = Vector3((0.5 - anchor.x) * quad.size.x, (anchor.y - 0.5) * quad.size.y, 0)
	_set_frame(card, state.frames[state.frame], state.texture)

func _update_night_visibility() -> void:
	if animals.size() < 4:
		return
	for animal: Dictionary in animals:
		var presence := smoothstep(0.35, 0.90, float(weather.night_blend)) if animal.night_only else 1.0 - smoothstep(0.15, 0.60, float(weather.night_blend))
		animal.presence = presence
		animal.node.visible = presence > 0.001
		animal.node.material_override.set_shader_parameter("creature_visibility", presence)
	var state: Dictionary = animals[3]
	var card: MeshInstance3D = state.node
	var visibility: float = state.presence
	card.material_override.set_shader_parameter("creature_glow", 1.65 * visibility)
	if night_light != null:
		night_light.position = card.position + Vector3.UP * 1.55
		night_light.light_energy = visibility * 1.15
		night_light.visible = card.visible
	if night_halo != null:
		var side := -1.0 if card.material_override.get_shader_parameter("sprite_flip") == true else 1.0
		night_halo.position = card.position + meadow.camera.global_basis.y * 2.30 + meadow.camera.global_basis.x * side * 0.55
		night_halo.visible = card.visible
		night_halo.material_override.set_shader_parameter("glow_strength", 0.40 * visibility)
	if night_aura != null:
		night_aura.position = card.position + meadow.camera.global_basis.y * 1.55 - meadow.camera.global_basis.z * 0.06
		night_aura.visible = card.visible
		night_aura.material_override.set_shader_parameter("visibility", visibility)

func _choose_target(state: Dictionary) -> void:
	var points: PackedVector2Array = state.points
	for attempt in range(36):
		var target := points[rng.randi_range(0, points.size() - 1)]
		var distance: float = target.distance_to(state.point)
		if distance < 1.0 or distance > 6.0 or not _animal_space_free(state, target) or not safe_segment(state.point, target):
			continue
		state.target = target
		state.moving = true
		state.settle = 0.0
		state.turns += 1
		state.speed = float(state.base_speed) * rng.randf_range(0.72, 1.26)
		return
	state.wait = 0.8

func _animal_space_free(state: Dictionary, point: Vector2) -> bool:
	for other: Dictionary in animals:
		if other.node == state.node or float(other.presence) < 0.10:
			continue
		if point.distance_to(other.point) < 1.25:
			return false
	return true

func _set_frame(card: MeshInstance3D, pixels: Rect2, texture: Texture2D) -> void:
	var size := Vector2(texture.get_width(), texture.get_height())
	card.material_override.set_shader_parameter("uv_region", Vector4(pixels.position.x / size.x,
		pixels.position.y / size.y, pixels.size.x / size.x, pixels.size.y / size.y))

func reset_flight(seed_value: int) -> void:
	flight_rng.seed = seed_value
	flight_points.clear()
	flight_phase = 0.0
	flight_legs = 0
	dragon_view = -1
	dragon_turn_mix = 1.0
	for i in range(4):
		flight_points.append(_new_flight_point())

func _new_flight_point() -> Vector3:
	var view: Camera3D = meadow.camera
	var screen := Vector2.ZERO
	for attempt in range(32):
		screen = FLIGHT_FRAME.position + FLIGHT_FRAME.size * Vector2(flight_rng.randf(), flight_rng.randf())
		if flight_points.is_empty():
			break
		var last_screen := view.unproject_position(flight_points[-1]) / get_viewport().get_visible_rect().size
		# Scale separation with the usable airspace; an absolute .22 in this
		# narrower valley forces alternating extremes and collapses spline travel.
		if absf(screen.x - last_screen.x) > FLIGHT_FRAME.size.x * 0.46:
			break
	# Frustum-bounded targets are converted once into world metres. The creature
	# is not a screen overlay, and its 25m span is never rescaled for distance.
	var half_height := tan(deg_to_rad(view.fov) * 0.5)
	var local_ray := Vector3((screen.x - 0.5) * 2.0 * half_height * 1.6,
		(0.5 - screen.y) * 2.0 * half_height, -1.0)
	var ray := view.global_basis * local_ray
	# High and well behind the meadow, with enough top margin for the entire
	# upstroke. Do not skim the projected mountain ridge with the body anchor.
	var depth := flight_rng.randf_range(FLIGHT_DEPTH.x, FLIGHT_DEPTH.y)
	return view.global_position + ray * ((depth - view.global_position.z) / ray.z)

func _flight_position(t: float) -> Vector3:
	var t2 := t * t
	var t3 := t2 * t
	return (flight_points[0] * (1.0 - 3.0 * t + 3.0 * t2 - t3)
		+ flight_points[1] * (4.0 - 6.0 * t2 + 3.0 * t3)
		+ flight_points[2] * (1.0 + 3.0 * t + 3.0 * t2 - 3.0 * t3)
		+ flight_points[3] * t3) / 6.0

func _flight_tangent(t: float) -> Vector3:
	var t2 := t * t
	return (flight_points[0] * (-3.0 + 6.0 * t - 3.0 * t2)
		+ flight_points[1] * (-12.0 * t + 9.0 * t2)
		+ flight_points[2] * (3.0 + 6.0 * t - 9.0 * t2)
		+ flight_points[3] * (3.0 * t2)) / 6.0

func _update_dragon(clock: float, delta: float) -> void:
	# Uniform cubic B-spline: each newly randomized target joins with continuous
	# position/tangent. Arc-speed compensation avoids stop-go waypoint motion.
	flight_phase += delta * DRAGON_SPEED / maxf(_flight_tangent(flight_phase).length(), 15.0)
	while flight_phase >= 1.0:
		flight_phase -= 1.0
		flight_points.pop_front()
		flight_points.append(_new_flight_point())
		flight_legs += 1
	dragon.position = _flight_position(flight_phase)
	flight_velocity = _flight_tangent(flight_phase).normalized() * DRAGON_SPEED
	var rightward := flight_velocity.dot(meadow.camera.global_basis.x)
	var toward := flight_velocity.dot(meadow.camera.global_basis.z)
	var bearing := atan2(rightward, toward)
	var desired_view := posmod(roundi(bearing / (PI * 0.25)), 8)
	if dragon_view < 0:
		dragon_view = desired_view
		previous_dragon_view = desired_view
	elif desired_view != dragon_view and absf(angle_difference(dragon_view * PI * 0.25, bearing)) > PI * 0.145 and dragon_turn_mix >= 1.0:
		previous_dragon_view = dragon_view
		dragon_view = desired_view
		dragon_turn_mix = 0.0
	dragon_turn_mix = minf(dragon_turn_mix + delta / 0.24, 1.0)
	var target_bank := clampf(flight_velocity.dot(meadow.camera.global_basis.y) * 0.045, -0.19, 0.19)
	dragon_bank = lerpf(dragon_bank, target_bank, minf(delta * 3.0, 1.0))
	dragon.material_override.set_shader_parameter("sprite_bank", dragon_bank)
	# Short flapping spells alternate with a held extended-wing glide.
	var wing: int = [0, 3, 1, 2, 1, 3][int(clock * 6.0) % 6] if fmod(clock, 8.0) < 4.8 else 1
	dragon_frame = wing * 8 + dragon_view
	previous_dragon_frame = wing * 8 + previous_dragon_view
	_set_frame(dragon, dragon_frames[dragon_frame], dragon_texture)
	var old: Rect2 = dragon_frames[previous_dragon_frame]
	var texture_size := Vector2(dragon_texture.get_width(), dragon_texture.get_height())
	dragon.material_override.set_shader_parameter("previous_region", Vector4(old.position.x / texture_size.x,
		old.position.y / texture_size.y, old.size.x / texture_size.x, old.size.y / texture_size.y))
	dragon.material_override.set_shader_parameter("body_pixel", DRAGON_ART.BODIES[dragon_frame])
	dragon.material_override.set_shader_parameter("previous_body_pixel", DRAGON_ART.BODIES[previous_dragon_frame])
	dragon.material_override.set_shader_parameter("pose_mix", smoothstep(0.0, 1.0, dragon_turn_mix))
