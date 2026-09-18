// World-space vegetation colour and cloud shade, shared by soil and real leaves.
// Do not give each triangle an unrelated bright material: foliage reads in masses.
float meadow_hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float meadow_noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(meadow_hash(i), meadow_hash(i + vec2(1, 0)), f.x),
        mix(meadow_hash(i + vec2(0, 1)), meadow_hash(i + vec2(1, 1)), f.x), f.y);
}
vec3 meadow_pigment(vec3 source, vec2 p, float density) {
    float mass = smoothstep(0.27, 0.76, meadow_noise(p * vec2(0.095, 0.065) + vec2(4.3, 8.1)));
    float thicket = smoothstep(0.30, 0.74, density);
    // Compress the source's brightest yellow leaf specks, keeping its edges,
    // dark crevices and hue. This is reflectance, not extra camera blur.
    float value = dot(source, vec3(0.30, 0.58, 0.12));
    vec3 pigment = source / (1.0 + max(value - 0.30, 0.0) * 0.72);
    pigment *= mix(vec3(0.80, 0.91, 0.80), vec3(1.04, 1.03, 0.90), mass);
    pigment *= mix(vec3(1.05, 1.02, 0.94), vec3(0.68, 0.82, 0.63), thicket);
    return pigment;
}
float meadow_cloud_light(vec2 p, float clock, float night) {
    vec2 drift = vec2(clock * 0.0015, clock * 0.00055);
    // A single axis-aligned value-noise octave exposed its lattice as a large
    // rectangular light patch on the central path. Rotate, warp and layer the
    // field so cloud shade keeps broad movement without readable grid cells.
    vec2 broad_uv = mat2(vec2(0.80, 0.60), vec2(-0.60, 0.80))
        * (p * 0.030 + vec2(2.7, 1.3) + drift);
    vec2 warp = vec2(meadow_noise(broad_uv * 0.53 + vec2(8.1, 3.7)),
        meadow_noise(broad_uv * 0.47 + vec2(-5.4, 11.2))) - vec2(0.5);
    float broad = meadow_noise(broad_uv + warp * 1.35);
    // Each finer octave uses another basis. Reusing broad_uv directly still
    // leaves long horizontal/vertical shoulders visible when the slow field
    // crosses one of value noise's cell boundaries.
    vec2 detail_uv = mat2(vec2(0.39, 0.92), vec2(-0.92, 0.39))
        * (broad_uv * 2.07 + warp * 0.72 + vec2(17.3, -9.6));
    vec2 breakup_uv = mat2(vec2(-0.71, 0.70), vec2(-0.70, -0.71))
        * (broad_uv * 4.19 - warp * 0.36 + vec2(-6.8, 21.4));
    float detail = meadow_noise(detail_uv);
    float breakup = meadow_noise(breakup_uv);
    float cloud = smoothstep(0.27, 0.73, broad * 0.66 + detail * 0.24 + breakup * 0.10);
    // Weak at night: moonlit grass must not become a globally black blanket.
    // Day shade is deliberately limited to 11%: it should suggest passing
    // cloud cover, never read as a second rectangular light source.
    return mix(mix(0.89, 1.0, cloud), mix(0.97, 1.0, cloud), night);
}
float meadow_foothill_cover(vec2 p, vec2 origin) {
    float spread = 1.0 - smoothstep(70.0, 104.0, abs(p.x - origin.x));
    float front = origin.y + 57.0 + 10.0 * sin(p.x * 0.069) + 7.0 * sin(p.x * 0.173 + 1.4);
    float depth = 1.0 - smoothstep(origin.y + 7.0, front, p.y);
    return spread * depth;
}
