// Shared optical depth for both generations of distant groves, not a global
// grade. Actual view distance orders the layers; the UV root band softens soil joins.
uniform bool grove_fog_enabled = false;
uniform float grove_fog_density = 0.0;
uniform vec3 grove_fog_linear_color = vec3(0.0);
// Existing alpha-basal column feet for v100; registered source anchor for v57.
// This only aligns the atmospheric join, never displaces a vertex or alpha edge.
uniform float grove_root_v[25];
uniform float grove_root_span = 0.0;

vec4 grove_fog(vec3 view_vertex, vec2 uv, float night) {
    float base = smoothstep(0.86, 1.0, uv.y);
    if (grove_root_span > 0.0) {
        float column = clamp(uv.x, 0.0, 1.0) * 24.0;
        int i = min(int(column), 23);
        float foot = mix(grove_root_v[i], grove_root_v[i + 1], column - float(i));
        base = smoothstep(foot - grove_root_span, foot, uv.y);
    }
    // Match the nearby dry-ground optical depth at the feet, not a grey skirt.
    float scale = mix(mix(0.50, 0.65, base), 1.0, clamp(night, 0.0, 1.0));
    float amount = grove_fog_enabled
        ? 1.0 - exp(-length(view_vertex) * grove_fog_density * scale) : 0.0;
    return vec4(grove_fog_linear_color, amount);
}
