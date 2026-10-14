// mountain-ridge-v39.png, full source UVs. Broad painted landforms, not luminance
// gradients or procedural rock noise. World +X faces the established day key;
// +Z faces the meadow. Soft overlapping fields avoid polygon/triangle seams.
uniform float mountain_normal_strength : hint_range(0.0, 1.0) = 1.0;
uniform float mountain_day_strength : hint_range(0.0, 1.0) = 1.0;
uniform bool native_massif = false;
uniform bool wooded_foothill = false;

vec4 meadow_mountain_plane(vec2 uv, vec2 centre, vec2 radius, float lean, vec3 facing) {
    vec2 q = (uv - centre) / radius;
    q.x -= lean * q.y;
    float weight = 1.0 - smoothstep(0.12, 1.0, dot(q, q));
    return vec4(normalize(facing) * weight, weight);
}

// Call once immediately after the shared base ALBEDO/EMISSION assignments.
// Pass full source `uv`, clamp(1.0 - meadow_night, 0.0, 1.0), mat3(VIEW_MATRIX),
// NORMAL, ALBEDO, EMISSION. No alpha, fog, light, texture, or geometry changes.
void meadow_mountain_surface(vec2 source_uv, float day_weight, mat3 world_to_view,
        inout vec3 surface_normal, inout vec3 surface_albedo, inout vec3 surface_emission) {
    float day = clamp(day_weight, 0.0, 1.0) * clamp(mountain_day_strength, 0.0, 1.0);
    float night = 1.0 - clamp(day_weight, 0.0, 1.0);
    if (day <= 0.0 && night <= 0.0) { return; }

    // Main summit (~.19,.18): broad cool left flank, narrow sunny right ridge.
    vec4 planes = meadow_mountain_plane(source_uv, vec2(0.151, 0.405), vec2(0.073, 0.245),
        -0.38, vec3(-0.58, 0.22, 0.79));
    planes += meadow_mountain_plane(source_uv, vec2(0.209, 0.369), vec2(0.035, 0.205),
        0.38, vec3(0.60, 0.46, 0.65));
    // Adjacent rock shoulder (~.23,.28), then the central summit (~.31,.32).
    planes += meadow_mountain_plane(source_uv, vec2(0.247, 0.450), vec2(0.032, 0.180),
        0.30, vec3(0.43, 0.38, 0.82));
    planes += meadow_mountain_plane(source_uv, vec2(0.291, 0.460), vec2(0.047, 0.150),
        -0.30, vec3(-0.46, 0.30, 0.84));
    planes += meadow_mountain_plane(source_uv, vec2(0.330, 0.466), vec2(0.029, 0.155),
        0.30, vec3(0.51, 0.44, 0.74));
    // Receding middle/right ridge is calmer than the dominant left summit.
    planes += meadow_mountain_plane(source_uv, vec2(0.563, 0.637), vec2(0.255, 0.135),
        0.0, vec3(-0.16, 0.30, 0.94));
    // Foreground forested foothills retain broad slope volume, not leaf normals.
    planes += meadow_mountain_plane(source_uv, vec2(0.213, 0.727), vec2(0.195, 0.130),
        0.0, vec3(-0.24, 0.43, 0.87));
    planes += meadow_mountain_plane(source_uv, vec2(0.664, 0.775), vec2(0.360, 0.100),
        0.0, vec3(0.12, 0.34, 0.93));
    // v106's new broad buttresses have different source registration. Never
    // apply the old narrow-spire lighting fields to this native-aspect image.
    if (native_massif) {
        planes = meadow_mountain_plane(source_uv, vec2(0.205, 0.455), vec2(0.12, 0.20),
            -0.15, vec3(-0.42, 0.28, 0.86));
        planes += meadow_mountain_plane(source_uv, vec2(0.272, 0.410), vec2(0.066, 0.145),
            0.18, vec3(0.50, 0.36, 0.78));
        planes += meadow_mountain_plane(source_uv, vec2(0.437, 0.527), vec2(0.095, 0.14),
            -0.12, vec3(-0.32, 0.27, 0.91));
        planes += meadow_mountain_plane(source_uv, vec2(0.485, 0.505), vec2(0.045, 0.105),
            0.12, vec3(0.44, 0.34, 0.83));
        planes += meadow_mountain_plane(source_uv, vec2(0.75, 0.62), vec2(0.24, 0.09),
            0.0, vec3(-0.12, 0.26, 0.96));
    }
    float forest = native_massif ? smoothstep(0.57, 0.71, source_uv.y)
                                : smoothstep(0.54, 0.80, source_uv.y);
    if (wooded_foothill) { forest = 1.0; }
    if (night > 0.0) {
        // Decode the existing moon tint only to locate source highlights;
        // keep the actual output hue, exact black and forest-foot illumination.
        vec3 moon_mix = (1.0 - painted_fill) * mix(vec3(1.0), vec3(0.78, 0.90, 1.0), night)
            + painted_fill * mix(vec3(1.0), vec3(0.36, 0.43, 0.54), night);
        vec3 night_pigment = max(surface_albedo + surface_emission, vec3(0.0)) / max(moon_mix, vec3(0.0001));
        float night_peak = max(night_pigment.r, max(night_pigment.g, night_pigment.b));
        float rock_night = night * (1.0 - forest);
        float night_rolloff = 1.0 - 0.16 * smoothstep(0.42, 0.85, night_peak);
        surface_albedo *= mix(1.0, 1.18 * night_rolloff, rock_night);
        surface_emission *= mix(1.0, 0.92 * night_rolloff, rock_night);
        // Fixed world slopes, not a painted day-key dot product: native light
        // evaluates them against the real NIGHT_KEY(-28,-145,0) and sky bounce.
        if (planes.w > 0.00001 && rock_night > 0.0) {
            vec3 moon_plane = normalize(world_to_view * normalize(planes.xyz));
            surface_normal = normalize(mix(surface_normal, moon_plane,
                0.16 * rock_night * clamp(planes.w, 0.0, 1.0)));
        }
    }
    if (day <= 0.0) { return; } // Night treatment complete; day path below unchanged.
    float normal_weight = day * clamp(mountain_normal_strength, 0.0, 1.0);
    if (normal_weight > 0.0 && planes.w > 0.00001) {
        vec3 view_normal = normalize(world_to_view * normalize(planes.xyz));
        surface_normal = normalize(mix(surface_normal, view_normal,
            normal_weight * 0.85 * clamp(planes.w, 0.0, 1.0)));
    }

    // Broad source-aligned forest/retreat bands only; never threshold bright
    // stone pixels into new lighting patches or recolour the source uniformly.
    float far_ridge = native_massif ? smoothstep(0.53, 0.75, source_uv.x) * (1.0 - forest)
        : smoothstep(0.35, 0.65, source_uv.x) * (1.0 - smoothstep(0.66, 0.82, source_uv.y));
    // At full day, the incoming A+E reconstructs the graded source pigment.
    // C1 shoulder: preserve dark values and RGB ratios, compress bright flecks
    // without blurring texture or creating a bright-pixel lighting mask.
    vec3 pigment = max(surface_albedo + surface_emission, vec3(0.0));
    float peak = max(pigment.r, max(pigment.g, pigment.b));
    float excess = max(peak - 0.34, 0.0);
    // The old narrow shoulder was fitted to glittery spires. On the new broad
    // source it erased the difference between whole sunny planes and gullies.
    // A continuous bounded shoulder retains those planes without new blur/haze.
    float shoulder_width = native_massif && !wooded_foothill ? 0.48 : 0.24;
    float rolloff = 1.0 - (excess - excess / (1.0 + excess / shoulder_width)) / max(peak, 0.0001);
    // Keep existing geometric/source-aligned normals and native Lambert-wrap.
    // With fill=.88, pre-shoulder day A=.36..48, E=.2464..3696;
    // this is a shader-space rebalance, not a claim of linear energy equality.
    float reflectance_gain = clamp(4.00 - 0.65 * forest - 0.35 * far_ridge, 3.00, 4.00);
    float emission_gain = clamp(0.28 + 0.10 * forest + 0.04 * far_ridge, 0.28, 0.42);
    // A restrained forest-only blue reduction; no additive grey or green lift.
    vec3 pigment_gain = rolloff * mix(vec3(1.0), vec3(0.99, 1.0, 0.94), forest);
    surface_albedo *= mix(vec3(1.0), reflectance_gain * pigment_gain, day);
    surface_emission *= mix(vec3(1.0), emission_gain * pigment_gain, day);
}
