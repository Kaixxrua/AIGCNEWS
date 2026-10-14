// Linear RGB supplied by the CPU exactly once; deliberately no source_color hint.
uniform bool architecture_fog_enabled = false;
uniform float architecture_fog_density = 0.0;
uniform vec3 architecture_fog_linear_color = vec3(0.0);

vec4 architecture_fog(vec3 view_vertex, vec2 sprite_uv, float night) {
    float ground_join = smoothstep(0.72, 1.0, sprite_uv.y);
    float day_scale = mix(0.55, 1.0, ground_join);
    float density_scale = mix(day_scale, 1.0, clamp(night, 0.0, 1.0));
    float amount = 0.0;
    if (architecture_fog_enabled) {
        amount = 1.0 - exp(min(0.0, -length(view_vertex) * architecture_fog_density * density_scale));
    }
    return vec4(architecture_fog_linear_color, amount);
}
