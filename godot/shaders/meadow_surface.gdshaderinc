// One material-coordinate system for terrain, solid turf lips and real leaves.
// It changes pigment placement, never the ground geometry or plant roots.
uniform sampler2D meadow_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
// At 8.4m most broad leaves in the source became subpixel dots in this camera.
// Keep a readable HD-2D leaf scale shared by terrain, turf and real foliage.
const float MEADOW_SURFACE_METRES = 13.4;

vec2 meadow_surface_uv(vec2 p) {
    vec2 warp = vec2(meadow_noise(p * 0.083 + vec2(3.1, 17.2)),
        meadow_noise(p * 0.083 + vec2(29.4, 5.7))) - vec2(0.5);
    mat2 turn = mat2(vec2(0.8, 0.6), vec2(-0.6, 0.8));
    return turn * (p + warp * 2.4) / MEADOW_SURFACE_METRES;
}

vec3 meadow_surface(vec2 p) {
    vec2 uv = meadow_surface_uv(p);
    vec2 f = fract(uv);
    // Sample the interior of the same source at wrap seams. No extra blur,
    // downscaled texture, noise speckles or separate floating ground cards.
    vec2 w = smoothstep(vec2(0.0), vec2(0.085), min(f, 1.0 - f));
    vec3 a = texture(meadow_texture, uv).rgb;
    vec3 b = texture(meadow_texture, uv + vec2(0.5, 0.0)).rgb;
    vec3 c = texture(meadow_texture, uv + vec2(0.0, 0.5)).rgb;
    vec3 d = texture(meadow_texture, uv + vec2(0.5, 0.5)).rgb;
    return mix(mix(d, c, w.x), mix(b, a, w.x), w.y);
}
