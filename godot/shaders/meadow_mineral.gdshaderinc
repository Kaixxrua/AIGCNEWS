// Shared, world-metric limestone pigment on real slopes and solid outcrops.
// The source contains mineral colour, not pre-lit masonry or cutout shadows.
uniform sampler2D limestone_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
vec3 meadow_mineral_sample(vec3 p, vec3 weight) {
    return texture(limestone_texture, p.zy / 8.0).rgb * weight.x
        + texture(limestone_texture, p.xz / 8.0).rgb * weight.y
        + texture(limestone_texture, p.xy / 8.0).rgb * weight.z;
}
vec3 meadow_mineral_pigment(vec3 sampled, vec3 p) {
    float weathering = meadow_noise(p.xz * 0.68 + vec2(p.y * 0.55, p.y * 0.19));
    vec3 mineral = max((sampled - vec3(0.55)) * 1.32 + vec3(0.55), vec3(0.04)) * vec3(0.62, 0.62, 0.57);
    mineral *= 0.94 + meadow_noise(p.xz * 1.1 + p.y) * 0.09;
    float lichen = smoothstep(0.54, 0.77, weathering);
    return mix(mineral, mineral * vec3(0.62, 0.76, 0.49), lichen * 0.30);
}
