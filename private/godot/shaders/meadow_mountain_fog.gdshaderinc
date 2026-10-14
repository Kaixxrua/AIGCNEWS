// Actual Environment colour converted to linear exactly once by the CPU.
uniform bool mountain_fog_enabled = false;
uniform float mountain_fog_density = 0.0;
uniform vec3 mountain_fog_linear_color = vec3(0.0);

vec4 mountain_fog(vec3 view_vertex, vec2 source_uv, float night) {
    // Foreground forested slopes retain pigment; the long rear ridge stays hazier.
    // Source-aligned broad regions, not per-pixel recolouring or a new dark outline.
    float forest = native_massif ? smoothstep(0.57, 0.71, source_uv.y)
        : smoothstep(0.52, 0.72, source_uv.y);
    float rear = native_massif ? smoothstep(0.53, 0.75, source_uv.x) * (1.0 - forest)
        : smoothstep(0.35, 0.68, source_uv.x) * (1.0 - smoothstep(0.66, 0.82, source_uv.y));
    float optical_scale = mix(0.58, 0.46, forest);
    optical_scale = mix(optical_scale, 0.90, rear);
    // Narrow, soft return at the source foot rather than a broad grey horizontal band.
    float foot = native_massif ? smoothstep(0.68, 0.73, source_uv.y)
        : smoothstep(0.80, 0.88, source_uv.y);
    optical_scale = mix(optical_scale, 1.0, foot);
    optical_scale = mix(optical_scale, 1.0, clamp(night, 0.0, 1.0));
    float amount = 0.0;
    if (mountain_fog_enabled) {
        amount = 1.0 - exp(min(0.0, -length(view_vertex) * mountain_fog_density * optical_scale));
    }
    return vec4(mountain_fog_linear_color, amount);
}
