shader_type spatial;
render_mode unshaded, blend_add, cull_disabled, depth_draw_never, fog_disabled;

global uniform float meadow_clock;
uniform float visibility = 0.0;
uniform float strength = 0.22;
uniform vec3 aura_color : source_color = vec3(0.29, 0.69, 0.90);

void vertex() {
    MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0],
        MAIN_CAM_INV_VIEW_MATRIX[1], MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
}

void fragment() {
    vec2 p = (UV - 0.5) * 2.0;
    float radius = length(p);
    float soft_core = exp(-dot(p, p) * 3.8);
    float edge = 1.0 - smoothstep(0.55, 1.0, radius);
    float breath = 0.94 + sin(meadow_clock * 1.7) * 0.06;
    ALBEDO = aura_color * strength;
    ALPHA = soft_core * edge * visibility * breath;
}
