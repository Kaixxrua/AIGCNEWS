extends Node
## Ground-only day response. Native/day wrappers share one canonical include;
## both are static resources, with no runtime shader-code construction.
const ORIGINAL_SHADER = preload("res://shaders/meadow_ground.gdshader")
const FAR_SWARD = preload("res://scripts/meadow_far_sward.gd")
static var day_shader: Shader = preload("res://shaders/meadow_ground_day.gdshader")
var meadow: Node3D
var rebuilding_static := false
var previous := Vector4(-1, -1, -1, -1)
var previous_color := Color(-1, -1, -1)

static func make_day_shader() -> Shader:
	return day_shader

func setup(scene: Node3D) -> void:
	name = "GroundAtmosphere"
	process_priority = 2
	rebuilding_static = OS.get_cmdline_user_args().has("--rebuild-static")
	if rebuilding_static:
		# Cache the canonical native material, never a runtime daylight variant.
		set_process(false)
		return
	var material := scene.get("ground_material") as ShaderMaterial
	if material == null or (material.shader != ORIGINAL_SHADER and material.shader != day_shader):
		meadow = null
		push_error("GroundAtmosphere: ground shader identity is not canonical native/day; normalize or rebuild the terrain cache before running")
		return
	meadow = scene
	FAR_SWARD.build(scene)
	_process(0.0)

func _process(_delta: float) -> void:
	if rebuilding_static or not is_instance_valid(meadow):
		return
	var environment: Environment = meadow.get_node("WorldEnvironment").environment
	var night: float = meadow.get_node("LivingWeather").night_blend
	var density: float = environment.fog_density if environment != null else 0.0
	var enabled: bool = environment != null and environment.fog_enabled
	var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy if environment != null else Color.BLACK
	var state := Vector4(night, density, float(enabled), float(supports_environment(environment)))
	if state == previous and linear == previous_color:
		return
	previous = state
	previous_color = linear
	sync_material(meadow.ground_material, environment, night)

static func supports_environment(environment: Environment) -> bool:
	return environment != null and environment.fog_mode == Environment.FOG_MODE_EXPONENTIAL \
		and absf(environment.fog_height_density) < 0.0001 and environment.fog_sun_scatter == 0.0 \
		and environment.fog_aerial_perspective == 0.0

static func sync_material(material: ShaderMaterial, environment: Environment, night: float) -> void:
	if material == null or (material.shader != ORIGINAL_SHADER and material.shader != day_shader):
		return
	var target: Shader = make_day_shader() if supports_environment(environment) and night < 1.0 else ORIGINAL_SHADER
	if material.shader != target:
		var retained := {}
		for entry: Dictionary in ORIGINAL_SHADER.get_shader_uniform_list():
			var value: Variant = material.get_shader_parameter(entry.name)
			if value != null:
				retained[entry.name] = value
		material.shader = target
		for key: String in retained:
			material.set_shader_parameter(key, retained[key])
	if target == day_shader:
		var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
		material.set_shader_parameter("far_ground_fog_enabled", environment.fog_enabled)
		material.set_shader_parameter("far_ground_fog_density", environment.fog_density)
		material.set_shader_parameter("far_ground_fog_linear_color", Vector3(linear.r, linear.g, linear.b))
