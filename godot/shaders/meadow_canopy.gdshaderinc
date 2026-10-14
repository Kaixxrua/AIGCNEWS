// A bounded volume-normal approximation for specifically authored leaf crowns.
// It changes neither the PNG nor alpha, geometry, root or shadow silhouette.
uniform int canopy_count = 0;
uniform vec4 canopy_lobes[4];
uniform float canopy_strength = 0.0;
// Opt in only for the five profiled trees; other materials keep their response.
uniform bool canopy_backlight = false;
// Independent opt-in for lower leaf-cluster orientation, not added light.
uniform bool canopy_leaf_orientation = false;
// Limited de-lighting of shadow already painted into the source leaf pigment.
uniform bool canopy_pigment_recovery = false;

vec3 meadow_canopy_normal(vec3 original, vec2 local_uv, vec2 leaf_relief,
        float leaf_orientation_mask, vec3 leaf_up) {
    vec3 sum = vec3(0.0);
    float coverage = 0.0;
    for (int i = 0; i < 4; i++) {
        if (i >= canopy_count) { break; }
        vec4 lobe = canopy_lobes[i];
        vec2 q = (local_uv - lobe.xy) / max(lobe.zw, vec2(0.01));
        q.y = -q.y;
        float radius = length(q);
        float weight = 1.0 - smoothstep(0.92, 1.13, radius);
        // The painted crown is wider than it is deep; a camera-facing sphere
        // leaves almost all visible foliage turned away from the low moon.
        // Upper leaf clusters tilt upward, while lower contours stay shaded.
        float upper_tilt = 0.15 * smoothstep(-0.10, 0.60, q.y);
        vec3 n = normalize(vec3(q.x, q.y + upper_tilt,
            sqrt(max(1.0 - dot(q, q), 0.035)) * 0.60));
        if (leaf_orientation_mask > 0.0 && q.y < -0.05) {
            // Lower crown position does not make every leaf face downward.
            // Keep the shell dominant; bias only a minority toward world up.
            // Leave the upper envelope and outer crown contour unchanged.
            float lower_cluster = smoothstep(0.05, 0.65, -q.y);
            float interior = 1.0 - smoothstep(0.82, 1.02, radius);
            float orientation_blend = 0.25 * leaf_orientation_mask * lower_cluster * interior;
            if (orientation_blend > 0.0) {
                n = normalize(mix(n, leaf_up, orientation_blend));
            }
        }
        sum += n * weight;
        coverage += weight;
    }
    if (coverage < 0.001) { return original; }
    vec3 rounded = normalize(sum / coverage);
    rounded.xy += clamp(leaf_relief * 0.42, vec2(-0.08), vec2(0.08));
    return normalize(mix(original, normalize(rounded), canopy_strength * min(coverage, 1.0)));
}

float meadow_canopy_leaf_mask(vec2 local_uv, vec3 source_rgb) {
    float coverage = 0.0;
    for (int i = 0; i < 4; i++) {
        if (i >= canopy_count) { break; }
        vec4 lobe = canopy_lobes[i];
        vec2 q = (local_uv - lobe.xy) / max(lobe.zw, vec2(0.01));
        // Match the existing crown envelope and its soft edge in sprite UVs.
        coverage += 1.0 - smoothstep(0.92, 1.13, length(q));
    }
    // Use the actual, ungraded source colours. In GLES3 these are sRGB-encoded
    // here; the engine converts to linear after the custom fragment.
    // Green excess includes cool green and yellow-green leaves. Penalizing
    // red dominance rejects brown wood even when its green excess is positive.
    float green_excess = source_rgb.g - (source_rgb.r + source_rgb.b) * 0.5;
    float warm_red = max(source_rgb.r - source_rgb.g, 0.0);
    float leaf_color = smoothstep(0.006, 0.035, green_excess - warm_red);
    return min(coverage, 1.0) * leaf_color;
}
