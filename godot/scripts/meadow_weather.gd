extends Node
## One reversible lighting transition and one pausable clock for the whole world.

const ARCHITECTURE_FOG = preload("res://scripts/meadow_architecture_fog.gd")

const TRANSITION_SECONDS := 3.2
const NIGHT_LAMP_ENERGY := 3.2
const DAY_SUN_ENERGY := 1.90
const NIGHT_MOON_ENERGY := 1.20
const NIGHT_BOUNCE_ENERGY := 0.32
const DAY_SKY_ENERGY := 0.18
const NIGHT_SETTLEMENT_SKY_ENERGY := 0.70
const DAY_ARCHITECTURE_PAINTED_FILL := 0.18
const NIGHT_ARCHITECTURE_PAINTED_FILL := 0.26
const SETTLEMENT_LIGHT_LAYER := 32
const DAY_KEY_ROTATION := Vector3(-34, 72, 0)
const NIGHT_KEY_ROTATION := Vector3(-28, -145, 0)

var night_blend := 0.0
var night_target := false
var motion_enabled := true
var reduced_motion := false
var animation_clock := 0.0
var transition_elapsed := 0.0
var transition_start := 0.0
var transitioning := false
var reflection_revision := 0
var environment: Environment
var key_light: DirectionalLight3D
var probe: ReflectionProbe
var probe_origin: Vector3
var lantern_light: OmniLight3D
var moon_bounce: DirectionalLight3D
var day_bounce: DirectionalLight3D
var settlement_bounce: DirectionalLight3D
var architecture_materials: Array[ShaderMaterial] = []
var source_pools: Array[OmniLight3D] = []
var web_ui: JavaScriptObject
var web_callback: JavaScriptObject
var ui_interval := 0.0

func _ready() -> void:
	var scene := get_parent()
	environment = scene.get_node("WorldEnvironment").environment
	key_light = scene.get_node("KeyLight")
	probe = scene.get_node("RiverSurroundingsReflection")
	probe_origin = probe.position
	_build_lantern(scene)
	moon_bounce = DirectionalLight3D.new()
	moon_bounce.name = "MoonSkyBounce"
	moon_bounce.rotation_degrees = Vector3(-38, 32, 0)
	moon_bounce.light_color = Color(0.52, 0.61, 0.75)
	moon_bounce.shadow_enabled = false
	scene.add_child(moon_bounce)
	day_bounce = DirectionalLight3D.new()
	day_bounce.name = "DaySkyBounce"
	day_bounce.rotation_degrees = Vector3(-58, -112, 0)
	day_bounce.light_color = Color(0.62, 0.72, 0.88)
	day_bounce.shadow_enabled = false
	scene.add_child(day_bounce)
	# Far architecture needs readable reflected sky light after its backwards
	# facade winding is corrected. Isolate this directional fill from the
	# accepted meadow/river lighting instead of raising global exposure.
	settlement_bounce = DirectionalLight3D.new()
	settlement_bounce.name = "SettlementSkyBounce"
	settlement_bounce.rotation_degrees = Vector3(-35, 24, 0)
	settlement_bounce.light_color = Color(0.53, 0.66, 0.87)
	settlement_bounce.light_cull_mask = SETTLEMENT_LIGHT_LAYER
	settlement_bounce.shadow_enabled = false
	scene.add_child(settlement_bounce)
	for label: String in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		var architecture: MeshInstance3D = scene.get_node(NodePath(label))
		architecture.layers |= SETTLEMENT_LIGHT_LAYER
		# Builders have finished; _art creates an independent material per instance.
		# Keep their window uniforms and the separate halo materials unchanged.
		var material: ShaderMaterial = architecture.material_override
		architecture_materials.append(material)
	for light in get_tree().get_nodes_in_group("meadow_night_sources"):
		source_pools.append(light as OmniLight3D)
	_apply_lighting(0.0)
	RenderingServer.global_shader_parameter_set("meadow_clock", animation_clock)
	if OS.has_feature("web"):
		web_ui = JavaScriptBridge.get_interface("meadowTimeUI")
		if web_ui != null:
			# Keep a strong reference for the lifetime of the browser callback.
			web_callback = JavaScriptBridge.create_callback(_on_web_command)
			web_ui.bind(web_callback)
			_sync_ui()
	print("MEADOW_WEATHER_READY: shared cloud/wind/water clock; reversible 3.2s day-night; N/P controls")

func _build_lantern(scene: Node3D) -> void:
	var card: MeshInstance3D = scene.get_node("TrailLantern")
	var quad: QuadMesh = card.mesh
	# Actual flame centre in the existing lantern PNG. Match the billboard basis.
	var uv := Vector2(0.643, 0.447)
	var local := quad.center_offset + Vector3((uv.x - 0.5) * quad.size.x, (0.5 - uv.y) * quad.size.y, 0)
	var view: Camera3D = scene.get_node("Camera3D")
	lantern_light = OmniLight3D.new()
	lantern_light.name = "LanternWarmPool"
	lantern_light.position = card.position + view.global_basis * local + view.global_basis.z * 0.16
	lantern_light.light_color = Color(1.0, 0.70, 0.43)
	lantern_light.omni_range = 7.2
	lantern_light.omni_attenuation = 1.35
	lantern_light.shadow_enabled = false
	# Only this nearby source casts local shadows. Distant windows keep their
	# batched halos and cheap fill lights; do not add eight shadow-map passes.
	lantern_light.shadow_bias = 0.04
	lantern_light.shadow_normal_bias = 0.55
	lantern_light.shadow_blur = 1.4
	lantern_light.shadow_opacity = 0.82
	scene.add_child(lantern_light)
	scene.SETTLEMENT_LIGHTS.add_lantern_halo(scene, lantern_light.position)
	card.material_override.set_shader_parameter("lantern_flame", true)

func _process(delta: float) -> void:
	advance_weather(delta)
	ui_interval += delta
	if ui_interval >= 0.20:
		ui_interval = 0.0
		_sync_ui()

func advance_weather(delta: float) -> void:
	# No engine TIME uniforms: pausing and resuming never jumps the wind phase.
	if motion_enabled:
		animation_clock += minf(delta, 0.25)
		RenderingServer.global_shader_parameter_set("meadow_clock", animation_clock)
	if transitioning:
		transition_elapsed += delta
		var t := clampf(transition_elapsed / TRANSITION_SECONDS, 0.0, 1.0)
		var eased := t * t * (3.0 - 2.0 * t)
		_apply_lighting(lerpf(transition_start, 1.0 if night_target else 0.0, eased))
		if t >= 1.0:
			transitioning = false
			_refresh_reflection()
			_sync_ui()
			print("MEADOW_TIME_CHANGED: %s; blend=%.3f; sun/moon=%.3f; lamp=%.3f" %
				["night" if night_target else "day", night_blend, key_light.light_energy, lantern_light.light_energy])
	var flicker := 1.0 + sin(animation_clock * 6.3) * 0.035 + sin(animation_clock * 10.7) * 0.015
	lantern_light.light_energy = NIGHT_LAMP_ENERGY * smoothstep(0.40, 0.95, night_blend) * flicker
	for light: OmniLight3D in source_pools:
		var phase: float = light.get_meta("flicker_phase")
		var energy: float = light.get_meta("night_energy")
		light.light_energy = energy * smoothstep(0.30, 0.92, night_blend) * (0.98 + sin(animation_clock * 2.2 + phase) * 0.02)
	ARCHITECTURE_FOG.sync_scene(get_parent(), night_blend)

func toggle_time() -> void:
	night_target = not night_target
	transition_start = night_blend
	transition_elapsed = 0.0
	transitioning = not reduced_motion
	if reduced_motion:
		_apply_lighting(1.0 if night_target else 0.0)
		_refresh_reflection()
	_sync_ui()

func set_motion(enabled: bool) -> void:
	motion_enabled = enabled
	# An explicit Play action opts back into the complete animated experience.
	# The system preference still controls initial load and later OS changes.
	if enabled:
		reduced_motion = false
	_sync_ui()

func set_reduced_motion(reduced: bool) -> void:
	reduced_motion = reduced
	if reduced_motion and transitioning:
		transitioning = false
		_apply_lighting(1.0 if night_target else 0.0)
		_refresh_reflection()
	set_motion(not reduced_motion)

func _apply_lighting(blend: float) -> void:
	night_blend = clampf(blend, 0.0, 1.0)
	RenderingServer.global_shader_parameter_set("meadow_night", night_blend)
	environment.ambient_light_color = Color(0.43, 0.53, 0.73).lerp(Color(0.50, 0.63, 0.83), night_blend)
	# Sky fill stays restrained: brightness comes from moon direction, reflected
	# cool fill and visible lantern/window sources, not raised global exposure.
	# Less uniform daytime fill exposes slope/leaf orientation without reducing
	# the readable night endpoint or multiplying the entire screen darker.
	environment.ambient_light_energy = lerpf(0.22, 0.32, night_blend)
	# AgX has a different exposure scale from ACES (which internally applies
	# an extra gain). Calibrate readable midtones, not an SDR brightness overlay.
	environment.tonemap_exposure = lerpf(2.0, 2.2, night_blend)
	environment.tonemap_agx_contrast = lerpf(1.45, 1.30, night_blend)
	get_parent().focus_material.set_shader_parameter("scene_exposure", environment.tonemap_exposure)
	# Final-engine grading also includes transparent water and wildlife. Do not
	# recolor only the opaque screen copy while other layers bypass that grade.
	environment.adjustment_saturation = lerpf(1.0, 0.80, night_blend)
	environment.fog_light_color = Color(0.54, 0.69, 0.82).lerp(Color(0.26, 0.34, 0.47), night_blend)
	environment.fog_density = lerpf(0.00042, 0.00048, night_blend)
	key_light.rotation_degrees = DAY_KEY_ROTATION.lerp(NIGHT_KEY_ROTATION, night_blend)
	key_light.light_color = Color(1.0, 0.84, 0.62).lerp(Color(0.65, 0.79, 1.0), night_blend)
	key_light.light_energy = lerpf(DAY_SUN_ENERGY, NIGHT_MOON_ENERGY, night_blend)
	var sky_material: ShaderMaterial = environment.sky.sky_material
	sky_material.set_shader_parameter("sun_direction", Basis.from_euler(DAY_KEY_ROTATION * PI / 180.0).z.normalized())
	sky_material.set_shader_parameter("moon_direction", Basis.from_euler(NIGHT_KEY_ROTATION * PI / 180.0).z.normalized())
	sky_material.set_shader_parameter("cloud_light_direction", key_light.basis.z.normalized())
	moon_bounce.light_energy = NIGHT_BOUNCE_ENERGY * night_blend
	day_bounce.light_energy = DAY_SKY_ENERGY * (1.0 - night_blend)
	settlement_bounce.light_energy = NIGHT_SETTLEMENT_SKY_ENERGY * night_blend
	# Absolute endpoints use the same eased, reversible blend as the real lights.
	# Do not multiply the previous material value or accumulate gain on toggles.
	var architecture_fill := lerpf(DAY_ARCHITECTURE_PAINTED_FILL, NIGHT_ARCHITECTURE_PAINTED_FILL, night_blend)
	for material: ShaderMaterial in architecture_materials:
		material.set_shader_parameter("painted_fill", architecture_fill)
	lantern_light.light_energy = NIGHT_LAMP_ENERGY * smoothstep(0.40, 0.95, night_blend)
	lantern_light.shadow_enabled = night_blend > 0.40
	for light: OmniLight3D in source_pools:
		light.light_energy = float(light.get_meta("night_energy")) * smoothstep(0.30, 0.92, night_blend)
	# Fade the old capture during a transition. Recapture once at its endpoint.
	var endpoint := 1.0 - sin(night_blend * PI) * 0.86
	probe.intensity = lerpf(0.68, 0.34, night_blend) * endpoint
	ARCHITECTURE_FOG.sync_scene(get_parent(), night_blend)

func _refresh_reflection() -> void:
	reflection_revision += 1
	# Godot's documented UPDATE_ONCE invalidation: a tiny transform change.
	# Alternate a 1 mm offset, never accumulate drift or capture six faces/frame.
	probe.position = probe_origin + Vector3(0, 0.001 * (reflection_revision % 2), 0)
	probe.force_update_transform()

func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_N:
			toggle_time()
			get_viewport().set_input_as_handled()
		elif event.keycode == KEY_P:
			set_motion(not motion_enabled)
			get_viewport().set_input_as_handled()

func _on_web_command(args: Array) -> void:
	if args.is_empty():
		return
	match str(args[0]):
		"time": toggle_time()
		"motion": set_motion(not motion_enabled)
		"reduced_motion":
			if args.size() == 2:
				set_reduced_motion(bool(args[1]))

func _sync_ui() -> void:
	if web_ui != null:
		web_ui.render(night_target, night_blend, motion_enabled, transitioning, animation_clock)

func _exit_tree() -> void:
	if web_ui != null:
		web_ui.unbind()
