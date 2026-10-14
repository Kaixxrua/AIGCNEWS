// Shared world-space sunlight occlusion. Sky fill, lamps, moonlight, albedo,
// emission and the approved river shader remain independent of this field.
// Burley/GGX equations follow Godot 4.7.2's non-metallic GLES light response.
uniform float sunbreak_strength : hint_range(0.0, 1.0) = 0.72;
varying vec3 sunbreak_position;
varying float sunbreak_specular;

float sunbreak_hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float sunbreak_noise(vec2 p) {
    vec2 cell = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(sunbreak_hash(cell), sunbreak_hash(cell + vec2(1.0, 0.0)), f.x),
        mix(sunbreak_hash(cell + vec2(0.0, 1.0)), sunbreak_hash(cell + vec2(1.0)), f.x), f.y);
}
float sunbreak_scope(vec3 world) {
    return smoothstep(-0.8, 0.1, world.y) * smoothstep(-175.0, -110.0, world.z);
}
float sunbreak_transmission(vec3 world) {
    // Project onto the same horizontal cloud layer along the daylight ray:
    // leaves, rocks and soil at one location cannot receive unrelated patches.
    vec2 p = world.xz - world.y * vec2(1.4093, 0.4581);
    p += vec2(meadow_clock * 0.065, meadow_clock * 0.018);
    // Warp the footprint before sampling: avoid equal-sized circular patches.
    vec2 warp = vec2(sunbreak_noise(p * 0.017 + vec2(2.8, 8.3)),
        sunbreak_noise(p * 0.019 + vec2(9.1, 3.2))) - vec2(0.5);
    vec2 q = p + warp * 21.0;
    float cover = sunbreak_noise(q * vec2(0.022, 0.014) + vec2(3.9, 5.7));
    cover += (sunbreak_noise(q * 0.053 + vec2(7.2, 1.9)) - 0.5) * 0.24;
    cover = smoothstep(0.24, 0.78, cover);
    // A broader broken cloud foreground keeps the sunlit path and middle
    // meadow readable as one subject. This lives on the world cloud plane:
    // tree crowns, turf and cliff faces receive the same displaced footprint.
    vec2 foreground_cloud = (q - vec2(-22.0, 23.0)) / vec2(49.0, 24.0);
    float foreground_cover = (1.0 - smoothstep(0.12, 1.20,
        dot(foreground_cloud, foreground_cloud))) * 0.82;
    cover = 1.0 - (1.0 - cover) * (1.0 - foreground_cover);
    // Broad moving gaps supply composition without painting a screen vignette.
    // Far settlement/skyline and the submerged river floor are outside this pass.
    return 1.0 - cover * sunbreak_scope(world) * sunbreak_strength * (1.0 - meadow_night);
}
float sunbreak_fresnel(float cosine) {
    float m = 1.0 - cosine;
    return m * m * m * m * m;
}
void light() {
    float transmission = 1.0;
    // The cool sky-bounce directional light is NOT a second sun. Restrict the
    // occlusion to the existing warm day key; no global exposure or ambient edit.
    vec3 day_key_view = normalize(mat3(VIEW_MATRIX) * vec3(0.788011, 0.559193, 0.256185));
    if (LIGHT_IS_DIRECTIONAL && dot(day_key_view, LIGHT) > 0.999) {
        transmission = sunbreak_transmission(sunbreak_position);
    }
    float nl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
    float nv = max(dot(NORMAL, VIEW), 0.0001);
    vec3 halfway = normalize(VIEW + LIGHT);
    float nh = clamp(dot(NORMAL, halfway), 0.0, 1.0);
    float lh = clamp(dot(LIGHT, halfway), 0.0, 1.0);
    float edge = 2.0 * lh * lh * ROUGHNESS - 0.5;
    float diffuse = (1.0 + edge * sunbreak_fresnel(nv))
        * (1.0 + edge * sunbreak_fresnel(nl)) * nl / PI;
#ifdef MEADOW_SUNBREAK_LAMBERT
    // The terrain wrapper never opted into diffuse_burley. Preserve its native
    // GLES Lambert response, including the unchanged moon/lamp endpoint.
    diffuse = nl / PI;
#endif
    vec3 incident = LIGHT_COLOR * ATTENUATION * transmission;
#ifdef MEADOW_ROCK_OCCLUSION
    // Only the tagged rock prefix carries this measured local visibility.
    // Account for small cavities unresolved by the large shadow atlas. Real
    // point lamps remain independent; night direct shelter is deliberately weak.
    if (LIGHT_IS_DIRECTIONAL) {
        incident *= 1.0 - (1.0 - clamp(rock_visibility, 0.0, 1.0))
            * mix(0.48, 0.12, meadow_night);
    }
#endif
    DIFFUSE_LIGHT += incident * (vec3(diffuse) + (vec3(1.0 / PI) - diffuse) * BACKLIGHT);
    if (ROUGHNESS > 0.0) {
        float alpha = ROUGHNESS * ROUGHNESS;
        float a = nh * alpha;
        float k = alpha / max(1.0 - nh * nh + a * a, 0.000001);
        float distribution = k * k / PI;
        float visibility = 0.5 / max(mix(2.0 * nl * nv, nl + nv, alpha), 0.000001);
        float f0 = 0.16 * sunbreak_specular * sunbreak_specular;
        float f90 = clamp(50.0 * f0, 0.0, 1.0);
        float fresnel = f0 + (f90 - f0) * sunbreak_fresnel(lh);
        SPECULAR_LIGHT += nl * distribution * visibility * fresnel * incident * SPECULAR_AMOUNT;
    }
}
