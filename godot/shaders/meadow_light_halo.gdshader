shader_type spatial;
render_mode unshaded, blend_add, cull_disabled, depth_draw_never, fog_disabled;
global uniform float meadow_clock;
global uniform float meadow_night;
uniform float glow_strength = 0.32;
uniform vec4 glow_color : source_color = vec4(1.0, 0.62, 0.30, 1.0);

void vertex() {
    float width = length(MODEL_MATRIX[0].xyz);
    float height = length(MODEL_MATRIX[1].xyz);
    MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0] * width,
        MAIN_CAM_INV_VIEW_MATRIX[1] * height, MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
}
void fragment() {
    float radius = length((UV - 0.5) * 2.0);
    float halo = exp(-radius * radius * 7.2) * (1.0 - smoothstep(0.70, 1.0, radius));
    float flicker = 0.97 + sin(meadow_clock * 1.13) * 0.03;
    ALBEDO = glow_color.rgb * glow_strength * 0.76;
    ALPHA = halo * smoothstep(0.30, 0.90, meadow_night) * flicker;
}
