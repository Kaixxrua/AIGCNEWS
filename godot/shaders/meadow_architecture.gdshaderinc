// Source-aligned masonry/roof planes. No pixel displacement or alpha changes.
uniform int architecture_count = 0;
uniform vec4 architecture_ab[32];
uniform vec4 architecture_cd[32];
uniform vec4 architecture_normals[32];
uniform float architecture_strength = 1.0;

float architecture_cross(vec2 a, vec2 b) { return a.x * b.y - a.y * b.x; }
float architecture_triangle(vec2 p, vec2 a, vec2 b, vec2 c, float aa) {
    float area = architecture_cross(b - a, c - a);
    if (abs(area) < 0.0000001) { return 0.0; }
    float direction = sign(area);
    float d0 = direction * architecture_cross(b - a, p - a) / max(length(b - a), 0.00001);
    float d1 = direction * architecture_cross(c - b, p - b) / max(length(c - b), 0.00001);
    float d2 = direction * architecture_cross(a - c, p - c) / max(length(a - c), 0.00001);
    return smoothstep(-aa, aa, min(d0, min(d1, d2)));
}

vec4 architecture_surface(vec2 uv) {
    vec3 sum = vec3(0.0);
    float coverage = 0.0;
    float aa = max(length(fwidth(uv)) * 0.42, 0.00006);
    for (int i = 0; i < 32; i++) {
        if (i >= architecture_count) { break; }
        vec2 a = architecture_ab[i].xy;
        vec2 b = architecture_ab[i].zw;
        vec2 c = architecture_cd[i].xy;
        vec2 d = architecture_cd[i].zw;
        float weight = clamp(architecture_triangle(uv, a, b, c, aa)
            + architecture_triangle(uv, a, c, d, aa), 0.0, 1.0);
        vec3 facing = architecture_normals[i].xyz;
        if (architecture_normals[i].w > 0.5) {
            float left = min(min(a.x, b.x), min(c.x, d.x));
            float right = max(max(a.x, b.x), max(c.x, d.x));
            float q = clamp((uv.x - (left + right) * 0.5) / max((right - left) * 0.5, 0.00001), -0.94, 0.94);
            float front = sqrt(max(1.0 - q * q, 0.05));
            // Cylindrical tower sides versus the upward-facing conical roof.
            facing = architecture_normals[i].w < 1.5
                ? normalize(vec3(q * 0.86, 0.0, front))
                : normalize(vec3(q * 0.65, 0.80, front * 0.46));
        }
        sum += facing * weight;
        coverage += weight;
    }
    if (coverage < 0.0001) { return vec4(0.0, 0.0, 1.0, 0.0); }
    return vec4(normalize(sum / coverage), min(coverage, 1.0) * architecture_strength);
}
