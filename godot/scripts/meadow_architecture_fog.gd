extends RefCounted
## Per-material bridge: no environment writes or viewport-global fog uniforms.

const ORIGINAL_SHADER = preload("res://shaders/meadow_architecture.gdshader")
const DAY_SHADER = preload("res://shaders/meadow_architecture_day.gdshader")

static func sync_scene(scene: Node, night: float) -> void:
    var world := scene.get_node("WorldEnvironment") as WorldEnvironment
    for label: String in ["IndependentCastleHill", "DistantVillage"]:
        var card := scene.get_node(NodePath(label)) as MeshInstance3D
        sync_material(card.material_override as ShaderMaterial, world.environment, night)

static func sync_material(material: ShaderMaterial, environment: Environment, night: float) -> void:
    if material == null or (material.shader != ORIGINAL_SHADER and material.shader != DAY_SHADER):
        return
    # Unsupported modes must retain the engine implementation, never approximate it.
    var supported := environment != null and environment.fog_mode == Environment.FOG_MODE_EXPONENTIAL \
        and absf(environment.fog_height_density) < 0.0001 and environment.fog_sun_scatter == 0.0
    var target: Shader = DAY_SHADER if supported and night < 1.0 else ORIGINAL_SHADER
    if material.shader != target:
        # Preserve textures, profile/window arrays and all existing per-instance values.
        var parameters := {}
        for entry: Dictionary in ORIGINAL_SHADER.get_shader_uniform_list():
            var value: Variant = material.get_shader_parameter(entry.name)
            if value != null:
                parameters[entry.name] = value
        material.shader = target
        for key: String in parameters:
            material.set_shader_parameter(key, parameters[key])
    if target == DAY_SHADER:
        var linear_color := environment.fog_light_color.srgb_to_linear() * environment.fog_light_energy
        material.set_shader_parameter("architecture_fog_enabled", environment.fog_enabled)
        material.set_shader_parameter("architecture_fog_density", environment.fog_density)
        material.set_shader_parameter("architecture_fog_linear_color", Vector3(linear_color.r, linear_color.g, linear_color.b))
