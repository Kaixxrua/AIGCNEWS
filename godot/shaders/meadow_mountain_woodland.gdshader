shader_type spatial;
render_mode cull_disabled, diffuse_burley;

global uniform float meadow_clock;
global uniform float meadow_night;
// Linear reflectance, independent of the bright meadow texture. No emission.
uniform vec3 canopy_pigment = vec3(0.115, 0.153, 0.080);
varying vec3 world_position;
#include "res://shaders/meadow_palette.gdshaderinc"

void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
    bool wood = UV.x < -1800.0;
    vec3 pigment = wood ? vec3(0.075, 0.054, 0.031) : canopy_pigment;
    // Real outward normals include the lower hemisphere. Do not flip them up
    // or add leaf-tip brightness: closed masses must retain their shaded body.
    ALBEDO = clamp(pigment * COLOR.rgb, vec3(0.0), vec3(0.24))
        * meadow_cloud_light(world_position.xz, meadow_clock, meadow_night);
    ROUGHNESS = 0.96;
    SPECULAR = 0.08;
    BACKLIGHT = wood ? vec3(0.0) : ALBEDO * 0.025;
    AO = wood ? 0.86 : clamp(UV2.x, 0.66, 1.0);
    AO_LIGHT_AFFECT = 0.35;
}
