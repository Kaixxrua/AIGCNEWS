extends Node
## Mountain-only optical-depth adjustment; never changes the shared Environment.

const ORIGINAL_SHADER = preload("res://shaders/meadow_mountain.gdshader")
const DAY_SHADER = preload("res://shaders/meadow_mountain_day.gdshader")
var meadow: Node3D

func setup(scene: Node3D) -> void:
	meadow = scene
	name = "MountainAtmosphere"
	# Weather runs at default priority 0. Read its current endpoint after it runs.
	process_priority = 1
	sync_scene(meadow)

func _process(_delta: float) -> void:
	if is_instance_valid(meadow):
		sync_scene(meadow)

static func sync_scene(scene: Node3D) -> void:
	var mountain := scene.get_node("DistantMountainRidge") as MeshInstance3D
	var world := scene.get_node("WorldEnvironment") as WorldEnvironment
	var weather := scene.get_node("LivingWeather")
	sync_material(mountain.material_override as ShaderMaterial, world.environment, float(weather.get("night_blend")))

static func sync_material(material: ShaderMaterial, environment: Environment, night: float) -> void:
	if material == null or (material.shader != ORIGINAL_SHADER and material.shader != DAY_SHADER):
		return
	var supported := environment != null and environment.fog_mode == Environment.FOG_MODE_EXPONENTIAL \
		and absf(environment.fog_height_density) < 0.0001 and environment.fog_sun_scatter == 0.0 \
		and environment.fog_aerial_perspective == 0.0
	# Writing FOG anywhere suppresses native fog throughout a compiled shader.
	# Switch back to the original wrapper at night, including its native fog.
	var target: Shader = DAY_SHADER if supported and night < 1.0 else ORIGINAL_SHADER
	if material.shader != target:
		var parameters := {}
		for entry: Dictionary in ORIGINAL_SHADER.get_shader_uniform_list():
			var value: Variant = material.get_shader_parameter(entry.name)
			if value != null:
				parameters[entry.name] = value
		material.shader = target
		for key: String in parameters:
			material.set_shader_parameter(key, parameters[key])
	if target == DAY_SHADER:
		var linear := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
		material.set_shader_parameter("mountain_fog_enabled", environment.fog_enabled)
		material.set_shader_parameter("mountain_fog_density", environment.fog_density)
		material.set_shader_parameter("mountain_fog_linear_color", Vector3(linear.r, linear.g, linear.b))
