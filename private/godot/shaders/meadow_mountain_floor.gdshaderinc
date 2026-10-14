// Grounded forest soil occupies the same finite far-land envelope as the hills.
// No screen-space dark stripe, emission, global exposure or water changes.
float mountain_floor_cover(vec2 p) {
    float side = max(1.0 - smoothstep(-44.0, -24.0, p.x), smoothstep(166.0, 187.0, p.x));
    float front = -247.0 + 9.0 * sin(p.x * 0.055) + 5.0 * sin(p.x * 0.131 + 1.2);
    float depth = smoothstep(-327.0, -312.0, p.y) * (1.0 - smoothstep(front - 23.0, front + 15.0, p.y));
    float groves = smoothstep(0.24, 0.72, meadow_noise(p * vec2(0.053, 0.071) + vec2(5.2, 1.8)));
    return side * depth * mix(0.55, 1.0, groves);
}

vec3 mountain_forest_floor(vec3 grass, vec2 p) {
    float cover = mountain_floor_cover(p);
    // Pigment, not a shadow: the actual sloping normals still receive the sun.
    vec3 forest = grass * vec3(0.64, 0.76, 0.58);
    return mix(grass, forest, cover * 0.85);
}
