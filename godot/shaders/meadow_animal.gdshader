shader_type spatial;
render_mode cull_disabled, diffuse_lambert_wrap, blend_mix, depth_prepass_alpha;

global uniform float meadow_night;
uniform sampler2D asset_texture : source_color, repeat_disable, filter_linear_mipmap;
uniform vec4 uv_region = vec4(0.0, 0.0, 1.0, 1.0);
uniform bool sprite_flip = false;
uniform float creature_visibility = 1.0;
uniform float creature_glow = 0.0;
uniform float art_exposure = 0.88;

void vertex() {
    MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0],
        MAIN_CAM_INV_VIEW_MATRIX[1], MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
    MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);
}

void fragment() {
    vec2 cell_uv = vec2(sprite_flip ? 1.0 - UV.x : UV.x, UV.y);
    vec2 uv = uv_region.xy + cell_uv * uv_region.zw;
    vec4 source = texture(asset_texture, uv, -0.25);
    if (source.a < 0.012) { discard; }
    vec3 pigment = source.rgb * art_exposure;
    NORMAL = normalize(mix(NORMAL, normalize(vec3((UV.x - 0.5) * 0.7,
        (0.60 - UV.y) * 0.6, 1.0)), 0.22));
    ALBEDO = pigment * 0.94 * mix(vec3(1.0), vec3(0.78, 0.90, 1.0), meadow_night);
    EMISSION = pigment * 0.06 * mix(vec3(1.0), vec3(0.68, 0.77, 0.94), meadow_night);
    float pale = smoothstep(0.38, 0.82, max(source.r, max(source.g, source.b)));
    float antlers = 1.0 - smoothstep(0.36, 0.48, UV.y);
    float marking = smoothstep(0.025, 0.13, source.b - source.r)
        * smoothstep(0.68, 0.88, max(source.r, max(source.g, source.b)));
    EMISSION += vec3(0.50, 0.83, 1.0) * max(pale * antlers, marking * 0.48) * creature_glow;
    ROUGHNESS = 0.91;
    SPECULAR = 0.04;
    BACKLIGHT = pigment * 0.08;
    // Real alpha blending: alpha-scissor would hold opaque, then suddenly pop.
    ALPHA = source.a * creature_visibility;
}
