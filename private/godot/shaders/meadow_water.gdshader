shader_type spatial;
render_mode cull_disabled, blend_mix, depth_draw_never;
global uniform float meadow_clock;
global uniform float meadow_night;
uniform sampler2D ripple_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
uniform sampler2D bed_depth : hint_depth_texture, repeat_disable, filter_nearest;
uniform float shallow_opacity = 0.18;
uniform float deep_opacity = 0.46;
uniform float flow_speed = 0.95;
varying vec3 world_position;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
void vertex() { world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
float flow_detail(vec2 p) {
    return noise(p) * 0.57 + noise(mat2(vec2(1.72, 0.93), vec2(-0.93, 1.72)) * p + 13.7) * 0.28
        + noise(p * 4.13 - 21.4) * 0.15;
}
vec3 painted_water(vec2 uv) {
    vec2 edge = min(fract(uv), 1.0 - fract(uv));
    float middle = smoothstep(0.0, 0.04, min(edge.x, edge.y));
    // A narrow offset blend also hides any imperfect AI-generated tile seam.
    return mix(texture(ripple_texture, uv + 0.5).rgb, texture(ripple_texture, uv).rgb, middle);
}
void fragment() {
    // UV.y is accumulated river-centre distance; UV2 stores half width and
    // dx/dz. Texture advection and the normal frame follow each bend together.
    vec2 p = vec2((UV.x - 0.5) * UV2.x * 2.0, UV.y);
    vec2 downstream = normalize(vec2(UV2.y, 1.0));
    vec2 across = vec2(downstream.y, -downstream.x);
    // Metres per second along the actual curved river. Previously multiplying
    // a slow clock by another tiny texture velocity made the surface near-static.
    float t = meadow_clock * flow_speed;
    vec2 flowing_p = p - vec2(0.0, t);
    vec2 flow = flowing_p * vec2(0.84, 0.38);
    vec2 warp = vec2(noise(p * 0.28 + t * 0.12), noise(p * 0.21 - t * 0.09)) * 1.7;
    float eddies = flow_detail(flow + warp);
    float bank = pow(abs(UV.x * 2.0 - 1.0), 5.0);
    vec3 first = painted_water(flowing_p / 11.5 + warp * 0.030);
    mat2 turn = mat2(vec2(0.94, 0.342), vec2(-0.342, 0.94));
    vec3 second = painted_water(turn * (p - vec2(0.0, t * 0.78)) / 15.7 - warp * 0.021 + vec2(0.31, 0.17));
    vec3 painted = mix(first, second, 0.20 + eddies * 0.20);
    float wave_value = dot(painted, vec3(0.22, 0.57, 0.21));
    vec3 water = mix(vec3(0.038, 0.085, 0.070), vec3(0.13, 0.20, 0.16), wave_value);
    // A moving, irregular normal field reflects the sky and the actual sun.
    // Two flow scales prevent a repeating row of waves or an emissive blue mat.
    float active_current = smoothstep(0.27, 0.72, noise(p * 0.16 + warp * 0.3));
    vec2 wave_p = flow * vec2(1.2, 1.5) + warp * 0.75;
    float h = flow_detail(wave_p);
    float hx = flow_detail(wave_p + vec2(0.11, 0));
    float hz = flow_detail(wave_p + vec2(0, 0.11));
    vec2 local_slope = vec2(h - hx, h - hz) * mix(1.9, 3.4, active_current);
    vec2 slope = across * local_slope.x + downstream * local_slope.y;
    vec3 wave_normal = normalize(vec3(slope.x, 1.0, slope.y));
    NORMAL = normalize((VIEW_MATRIX * vec4(wave_normal, 0.0)).xyz);
    float crest = smoothstep(0.18, 0.48, wave_value);
    float sparkle = crest * smoothstep(0.79, 0.94, noise(p * vec2(4.9, 6.8) + vec2(t * 0.23, -t * 1.1)));
    sparkle *= smoothstep(0.30, 0.72, noise(p * 0.55 + noise(p * 0.13) * 1.2));
    float footprint = max(length(dFdx(world_position.xz)), length(dFdy(world_position.xz)));
    sparkle *= 1.0 - smoothstep(0.18, 0.62, footprint);
    float foam = smoothstep(0.59, 1.0, bank) * smoothstep(0.44, 0.72, eddies) * 0.075;
    float raw_depth = texture(bed_depth, SCREEN_UV).r;
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    vec3 ndc = vec3(SCREEN_UV, raw_depth) * 2.0 - 1.0;
    #else
    vec3 ndc = vec3(SCREEN_UV * 2.0 - 1.0, raw_depth);
    #endif
    vec4 bed_view = INV_PROJECTION_MATRIX * vec4(ndc, 1.0);
    vec3 bed_world = (INV_VIEW_MATRIX * vec4(bed_view.xyz / bed_view.w, 1.0)).xyz;
    float water_depth = max(world_position.y - bed_world.y, 0.0);
    float thickness = 1.0 - exp(-water_depth * 0.72);
    float fresnel = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 4.0);
    ALBEDO = water + vec3(0.70, 0.77, 0.72) * (sparkle * 0.24 + foam);
    EMISSION = mix(vec3(0.40, 0.48, 0.40), vec3(0.18, 0.28, 0.43), meadow_night) * sparkle * 0.06;
    ROUGHNESS = mix(mix(0.18, 0.28, active_current), 0.34, bank);
    SPECULAR = 0.48;
    ALPHA = clamp(mix(shallow_opacity, deep_opacity, thickness) + fresnel * 0.22 + foam, 0.12, 0.72);
}
