shader_type spatial;
render_mode cull_disabled, diffuse_lambert_wrap, blend_mix;

global uniform float meadow_night;
uniform sampler2D asset_texture : source_color, repeat_disable, filter_linear_mipmap;
uniform vec2 canvas_pixels = vec2(300.0, 292.0);
uniform vec2 canvas_pivot = vec2(150.0, 178.0);
uniform vec4 uv_region;
uniform vec4 previous_region;
uniform vec2 body_pixel;
uniform vec2 previous_body_pixel;
uniform float pose_mix = 1.0;
uniform float sprite_bank = 0.0;

void vertex() {
    VERTEX.xy = mat2(vec2(cos(sprite_bank), sin(sprite_bank)), vec2(-sin(sprite_bank), cos(sprite_bank))) * VERTEX.xy;
    MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0], MAIN_CAM_INV_VIEW_MATRIX[1], MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
    MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);
}

vec4 pose(vec2 offset, vec4 region, vec2 body) {
    vec2 size = vec2(textureSize(asset_texture, 0));
    vec2 uv = (offset + body) / size;
    if (any(lessThan(uv, region.xy)) || any(greaterThanEqual(uv, region.xy + region.zw))) { return vec4(0.0); }
    return texture(asset_texture, clamp(uv, region.xy + 0.5 / size, region.xy + region.zw - 0.5 / size), -0.25);
}

void fragment() {
    vec2 offset = UV * canvas_pixels - canvas_pivot;
    vec4 a = pose(offset, previous_region, previous_body_pixel);
    vec4 b = pose(offset, uv_region, body_pixel);
    float alpha = mix(a.a, b.a, pose_mix);
    if (alpha < 0.012) { discard; }
    // Blend registered pigments once: no double-transparent overlapping cards.
    vec3 pigment = mix(a.rgb * a.a, b.rgb * b.a, pose_mix) / max(alpha, 0.001) * 0.87;
    ALBEDO = pigment * 0.82 * mix(vec3(1.0), vec3(0.78, 0.90, 1.0), meadow_night);
    EMISSION = pigment * 0.18 * mix(vec3(1.0), vec3(0.68, 0.77, 0.94), meadow_night);
    ROUGHNESS = 0.92;
    SPECULAR = 0.04;
    ALPHA = alpha;
}
