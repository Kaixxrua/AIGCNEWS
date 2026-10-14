// Mid-scale sward survives the grazing camera where individual leaf texels do
// not. No geometry/displacement, global grade, unfiltered texture or river edit.
uniform bool far_ground_fog_enabled = false;
uniform float far_ground_fog_density = 0.0;
uniform vec3 far_ground_fog_linear_color = vec3(0.0);

float far_ground_scope(vec3 p, float road, float bank, float cliff, float submerged, float shore) {
    float distance_band = 1.0 - smoothstep(-132.0, -88.0, p.z);
    // Dry valley grass at y=0 is still a full metre above the water surface.
    // Do not erase its material detail merely because the land is low-lying.
    float dry_sward = smoothstep(7.0, 11.0, shore) * smoothstep(-0.10, 0.05, p.y);
    return distance_band * dry_sward * (1.0 - smoothstep(0.0, 0.08, road))
        * (1.0 - bank) * (1.0 - cliff) * (1.0 - submerged);
}

float far_sward_height(vec2 p, float footprint) {
    mat2 turn = mat2(vec2(0.8, 0.6), vec2(-0.6, 0.8));
    vec2 q = turn * p;
    float clumps = meadow_noise(q * vec2(0.62, 0.45) + vec2(18.7, 5.2));
    float leaves = meadow_noise(q * vec2(1.65, 1.18) + vec2(2.8, 39.1));
    // Remove the smaller component before it aliases; retain the clump scale.
    float resolved = 1.0 - smoothstep(0.24, 0.70, footprint);
    return clumps * 0.76 + mix(0.5, leaves, resolved) * 0.24;
}

vec4 far_ground_fog(vec3 view_vertex, float scope, float night) {
    float scale = mix(1.0, 0.65, scope * (1.0 - clamp(night, 0.0, 1.0)));
    float amount = far_ground_fog_enabled
        ? 1.0 - exp(-length(view_vertex) * far_ground_fog_density * scale) : 0.0;
    return vec4(far_ground_fog_linear_color, amount);
}
