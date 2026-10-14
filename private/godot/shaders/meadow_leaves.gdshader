shader_type spatial;
render_mode cull_disabled, diffuse_burley;
global uniform float meadow_clock;
global uniform float meadow_night;
uniform bool foothill_scrub = false;
uniform bool middle_scrub = false;
uniform bool far_sward = false;
varying vec3 world_position;
varying vec3 leaf_world_normal;
#include "res://shaders/meadow_palette.gdshaderinc"
#include "res://shaders/meadow_surface.gdshaderinc"
#include "res://shaders/meadow_sunbreak.gdshaderinc"
void vertex() {
    float phase = VERTEX.x * 0.31 + VERTEX.z * 0.21;
    float breeze = (sin(phase + meadow_clock * 1.4) * 0.70
        + sin(phase * 2.7 - meadow_clock * 2.1) * 0.30) * 0.055;
    VERTEX.x += breeze * COLOR.a * COLOR.a;
    VERTEX.z += breeze * COLOR.a * 0.4;
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz;
    leaf_world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);
    sunbreak_position = world_position;
}
void fragment() {
    // Grass fans are intentionally two-sided. The renderer's back-face normal
    // flip otherwise lights half the fans from below, producing black speckles.
    // Use the authored continuous upper-surface normal on either winding.
    vec3 upper_normal = normalize(leaf_world_normal);
    upper_normal.y = abs(upper_normal.y);
    NORMAL = normalize((VIEW_MATRIX * vec4(upper_normal, 0.0)).xyz);
    vec2 p = world_position.xz;
    vec3 meadow = meadow_surface(p);
    vec3 pigment = meadow_pigment(meadow, p, UV2.x) * COLOR.rgb;
    // Modest top-leaf light separates the foliage silhouette from the soil;
    // a whole random bright triangle is no longer the unit of contrast.
    pigment *= mix(1.02, 1.19, COLOR.a);
    if (far_sward) {
        // The same dry foothill pigment as the supporting ground. Rooted,
        // folded leaf surfaces receive real light; no self-lit distant specks.
        float foothill = 1.0 - smoothstep(-195.0, -107.0, p.y);
        float scrub = smoothstep(0.31, 0.66,
            meadow_noise(p * 0.36 + meadow_noise(p * 0.09) * 3.0));
        pigment *= mix(vec3(1.0), mix(vec3(0.53, 0.64, 0.70), vec3(0.79, 0.84, 0.79), scrub), foothill * 0.84);
    }
    if (foothill_scrub) {
        // Resolve a leafy wooded mass, not bright single grass blades, this far away.
        pigment = mix(pigment, vec3(0.052, 0.082, 0.041) * COLOR.rgb, 0.48);
        pigment *= vec3(0.72, 0.85, 0.78);
    }
    if (UV.x < -900.0) { pigment = vec3(0.59, 0.58, 0.37); }
    // The new woody/herb tier has denser olive foliage than the meadow under
    // it; this is material reflectance, not a dark overlay on the terrain.
    if (middle_scrub) {
        // Broad mid-height leaves connect the turf and painted shrub islands.
        // The turf/density and vertex tone already supply the broad dark mass.
        // Avoid multiplying another deeply green filter into sheltered leaves;
        // retain an olive body that can receive the same light as nearby turf.
        // Root occlusion, real branch shadows and leaf gaps remain independent.
        float outer_leaf = smoothstep(0.10, 0.90, COLOR.a);
        pigment *= mix(vec3(0.86, 0.94, 0.78), vec3(0.93, 0.97, 0.85), outer_leaf);
    }
    if (UV.x < -1800.0) { pigment = vec3(0.105, 0.073, 0.034) * COLOR.rgb; }
    ALBEDO = pigment * mix(meadow_cloud_light(p, meadow_clock, meadow_night), 1.0,
        sunbreak_scope(world_position) * (1.0 - meadow_night));
    BACKLIGHT = pigment * 0.06;
    // Thin middle-crown leaflets receive restrained back-side illumination.
    // Wood and other vegetation keep their established response. This adds
    // no emission; the no-incident-light case is checked in the GPU probe.
    if (middle_scrub && UV.x >= -900.0) {
        BACKLIGHT = vec3(0.18);
    }
    ROUGHNESS = mix(0.95, 0.80, COLOR.a);
    SPECULAR = 0.14;
    sunbreak_specular = SPECULAR;
    AO = 0.78 + COLOR.a * 0.22;
}
