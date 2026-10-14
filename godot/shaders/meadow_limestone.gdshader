shader_type spatial;
render_mode cull_disabled, diffuse_burley;
global uniform float meadow_clock;
global uniform float meadow_night;
uniform sampler2D escarpment_texture : source_color, repeat_disable, filter_linear_mipmap_anisotropic;
uniform int rock_ao_vertex_count = 0;
uniform float rock_plane_strength : hint_range(0.0, 1.0) = 1.0;
varying vec3 world_position;
varying vec3 world_normal;
varying float rock_visibility;
varying float rock_prefix;
#include "res://shaders/meadow_palette.gdshaderinc"
#include "res://shaders/meadow_surface.gdshaderinc"
#include "res://shaders/meadow_mineral.gdshaderinc"
#define MEADOW_ROCK_OCCLUSION
#include "res://shaders/meadow_sunbreak.gdshaderinc"
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1)).xyz;
    world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);
    sunbreak_position = world_position;
    rock_visibility = VERTEX_ID < rock_ao_vertex_count ? COLOR.b : 1.0;
    rock_prefix = VERTEX_ID < rock_ao_vertex_count ? 1.0 : 0.0;
}
void fragment() {
    vec3 p = world_position;
    vec3 n = normalize(world_normal);
    // Read the actual triangle plane, never a brightness-derived normal.
    // Evaluate derivatives before conditional shading; orient to the mesh normal.
    vec3 face_cross = cross(dFdx(p), dFdy(p));
    float face_area = dot(face_cross, face_cross);
    vec3 face_normal = face_cross * inversesqrt(max(face_area, 0.000000000001));
    face_normal *= dot(face_normal, n) < 0.0 ? -1.0 : 1.0;
    float plane_day = 0.0;
    if (rock_prefix > 0.5 && COLOR.r < 0.5 && meadow_night < 1.0 && face_area > 0.000000000001) {
        plane_day = clamp(rock_plane_strength, 0.0, 1.0) * clamp(1.0 - meadow_night, 0.0, 1.0);
        if (plane_day > 0.0) {
            // Preserve broad rock planes without overemphasizing each triangle.
            n = normalize(mix(n, face_normal, plane_day * 0.16));
        }
    }
    vec3 weight = pow(abs(n), vec3(4.0));
    weight /= max(dot(weight, vec3(1.0)), 0.001);
    vec3 mineral = meadow_mineral_pigment(meadow_mineral_sample(p, weight), p);
    // Broad planes are provided by solid geometry; this map is just mineral grain.
    vec4 painted_face = texture(escarpment_texture, clamp(UV, vec2(0.0), vec2(1.0)));
    // Disregard low-alpha matte RGB while retaining the untouched source PNG.
    float face_mask = step(0.0, UV.x) * smoothstep(0.22, 0.42, painted_face.a);
    // Day-only de-lighting of tagged bare cliff faces, including open/non-AO
    // faces. Turf-tagged geometry, other batches and the exact night path skip.
    // Remove only positive painted luminance relative to the mineral pigment;
    // one scalar preserves hue and existing dark cracks. Never used for normals.
    if (rock_prefix > 0.5 && COLOR.r < 0.5 && meadow_night < 1.0 && face_mask > 0.0) {
        vec3 luma_weights = vec3(0.30, 0.58, 0.12);
        float mineral_luma = dot(mineral, luma_weights);
        float painted_luma = dot(painted_face.rgb * vec3(0.76, 0.75, 0.68), luma_weights);
        if (painted_luma > mineral_luma) {
            float gain = clamp(mineral_luma / max(painted_luma, 0.000001), 0.0, 1.0);
            painted_face.rgb *= mix(1.0, gain, clamp(1.0 - meadow_night, 0.0, 1.0));
        }
    }
    // Let scene light describe the actual planes. The old 64% pre-lit strip
    // washed out the new geometry and repeated its painted bright shoulders.
    // Keep a restrained amount of unique fissure colour; no fake black outline.
    mineral = mix(mineral, painted_face.rgb * vec3(0.76, 0.75, 0.68), face_mask * mix(0.38, 0.20, plane_day));
    // Adjacent fractured pieces are one geology, not individually tinted bricks.
    // Retain measured cavity occlusion and unique grain; change only the tagged
    // daylight cliff faces, not river stones, near boulders or the night path.
    mineral *= mix(1.0, COLOR.g, mix(0.48, 0.18, plane_day));
    float cap = smoothstep(0.68, 0.92, n.y) * COLOR.r;
    // Soil continues at the rear; its exposed stone edge has broken pockets
    // of turf, not one fully green horizontal strip around the whole outcrop.
    float edge_tufts = smoothstep(0.30, 0.70, noise(p.xz * 1.65 + p.y * 0.19));
    edge_tufts *= mix(0.48, 1.0, smoothstep(0.28, 0.73, UV2.x));
    cap *= mix(edge_tufts, 1.0, smoothstep(0.06, 0.72, UV2.y));
    vec3 turf = meadow_pigment(meadow_surface(p.xz), p.xz, UV2.x);
    // The near boulders are pale worn limestone, not the ochre cliff band.
    // Vertex alpha tags that geology; it is metadata, not surface opacity.
    float pale_stone = 1.0 - smoothstep(0.45, 0.90, COLOR.a);
    float stone_value = dot(mineral, vec3(0.30, 0.58, 0.12));
    vec3 pale = mix(mineral, vec3(stone_value) * vec3(1.04, 1.02, 0.96), 0.52) * 1.03;
    mineral = mix(mineral, pale, pale_stone);
    if (plane_day > 0.0) {
        // Slope-guided weathering: grey mineral on steep faces, warmer exposed
        // shoulders. This is material variation, NOT baked sun/shadow or AO.
        // Continuous in the existing surface orientation; no courses or noise.
        float shoulder = smoothstep(0.12, 0.70, n.y);
        vec3 slope_pigment = mix(vec3(0.78, 0.83, 0.87), vec3(1.00, 0.99, 0.94), shoulder);
        mineral *= mix(vec3(1.0), slope_pigment, plane_day);
    }
    vec3 rock = mix(mineral, turf, cap * 0.94);
    float wet = 1.0 - smoothstep(-1.08, -0.40, p.y);
    ALBEDO = mix(rock, rock * vec3(0.52, 0.64, 0.71), wet * 0.75)
        * mix(meadow_cloud_light(p.xz, meadow_clock, meadow_night), 1.0,
            sunbreak_scope(world_position) * (1.0 - meadow_night));
    // Actual sun responds to fine mineral relief as well as the solid silhouette.
    vec3 metric = vec3(0.30, 0.58, 0.12);
    float h = dot(meadow_mineral_sample(p, weight), metric);
    vec3 gradient = vec3(h - dot(meadow_mineral_sample(p + vec3(0.028, 0, 0), weight), metric),
        h - dot(meadow_mineral_sample(p + vec3(0, 0.028, 0), weight), metric),
        h - dot(meadow_mineral_sample(p + vec3(0, 0, 0.028), weight), metric));
    gradient -= n * dot(gradient, n);
    float resolved_grain = 1.0 - smoothstep(0.10, 0.40, max(length(dFdx(p)), length(dFdy(p))));
    NORMAL = normalize((VIEW_MATRIX * vec4(normalize(n + gradient * mix(1.35, 0.85, face_mask) * (1.0 - cap) * resolved_grain), 0)).xyz);
    ROUGHNESS = mix(0.94, 0.67, wet);
    SPECULAR = 0.10;
    sunbreak_specular = SPECULAR;
    // Offline rays query the actual rock/soil around each approved terrace
    // vertex. Open projecting edges keep their light; sheltered joints lose
    // sky fill, not pigment. Other rock batches retain their original AO.
    float shelter = (1.0 - clamp(rock_visibility, 0.0, 1.0));
    AO = 0.93 * (1.0 - shelter * 0.82);
    // GLES 4.7.2 applies AO to sky fill but not to its final direct-light
    // sum. The explicitly gated light() branch supplies directional shelter.
    AO_LIGHT_AFFECT = 0.0;
}
