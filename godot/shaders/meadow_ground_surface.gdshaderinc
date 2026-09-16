uniform sampler2D rock_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
uniform sampler2D bank_limestone_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
uniform vec4 contact_shadows[72];
uniform vec2 road_points[12];
uniform vec2 road_fork[2];
uniform vec2 bridge_spur[2];
uniform vec2 river_bends[10];
uniform vec4 road_width = vec4(1.35, 3.10, -65.0, 10.0);
uniform vec2 foothill_origin = vec2(0.0, -255.0);
varying vec3 world_position;
varying vec3 world_normal;

#include "res://shaders/meadow_palette.gdshaderinc"
#include "res://shaders/meadow_mountain_floor.gdshaderinc"
#include "res://shaders/meadow_surface.gdshaderinc"
#include "res://shaders/meadow_mineral.gdshaderinc"
#define MEADOW_SUNBREAK_LAMBERT
#include "res://shaders/meadow_sunbreak.gdshaderinc"
#ifdef MEADOW_FAR_GROUND_DAY
#include "res://shaders/meadow_far_ground.gdshaderinc"
#endif

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float segment_distance(vec2 p, vec2 a, vec2 b) {
    vec2 v = b - a;
    return length(p - a - v * clamp(dot(p - a, v) / dot(v, v), 0.0, 1.0));
}
vec2 river_shape(vec2 p) {
    float centre = river_bends[9].y;
    for (int i = 0; i < 9; i++) {
        vec2 a = river_bends[i];
        vec2 b = river_bends[i + 1];
        if (p.y >= b.x) {
            float t = clamp((a.x - p.y) / (a.x - b.x), 0.0, 1.0);
            centre = mix(a.y, b.y, t * t * (3.0 - 2.0 * t)) + 0.65 * sin(p.y * 0.31 + 0.4);
            break;
        }
    }
    float half_width = 6.2 + 1.25 * sin(p.y * 0.054 + 0.8) + 0.50 * sin(p.y * 0.23 + 1.8);
    float side = sign(p.x - centre);
    float perturb = (sin(p.y * 0.29 + side * 1.7) * 0.38 + sin(p.y * 0.81 - side) * 0.16)
        * smoothstep(5.0, 10.0, abs(p.y + 38.0));
    float shore_strength = smoothstep(-117.0, -104.0, p.y) * (1.0 - smoothstep(-12.0, -4.0, p.y))
        * smoothstep(7.0, 11.0, abs(p.y + 38.0));
    float bank_z = p.y - (side > 0.0 ? 4.5 : 0.0);
    vec3 gully_delta = vec3((bank_z + 23.5) / 1.4, (bank_z + 79.0) / 2.8, (bank_z + 105.0) / 3.3);
    vec3 gully_field = exp(-gully_delta * gully_delta * 1.7);
    float gully = max(gully_field.x, max(gully_field.y, gully_field.z));
    perturb += (sin(p.y * 0.20 + side * 2.0) * 0.92 + sin(p.y * 0.49 - side * 0.7) * 0.30 + gully * 1.40) * shore_strength;
    return vec2(centre, half_width + perturb);
}
void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);
    sunbreak_position = world_position;
}
void fragment() {
    vec2 p = world_position.xz;
    // UV2 was sampled from the same world field that places the living grass.
    float thicket = smoothstep(0.30, 0.74, UV2.x);
    vec2 warp = vec2(noise(p * 0.23), noise(p * 0.23 + 20.0)) * 1.1;
    vec3 fine_grass = meadow_surface(p);
    vec3 ground = fine_grass;
    // The source already contains deep leaf crevices. A second strong dark
    // multiplier and unrelated high-frequency normals turned turf into gravel.
    ground = meadow_pigment(pow(max(ground, vec3(0.0)), vec3(0.98)), p, UV2.x);
    // Distant foothills share the cool, wooded palette of the mountain base;
    // they must not become a fluorescent smooth band behind the village.
    float foothill = 1.0 - smoothstep(-195.0, -107.0, p.y);
    float distant_scrub = smoothstep(0.31, 0.66, noise(p * 0.36 + noise(p * 0.09) * 3.0));
    ground *= mix(vec3(1.0), mix(vec3(0.53, 0.64, 0.70), vec3(0.79, 0.84, 0.79), distant_scrub), foothill * 0.84);
    // A broken woodland floor continues under the real foothill scrub volumes.
    // Its irregular leading edge follows the same field as the new geometry.
    float wooded_foot = meadow_foothill_cover(p, foothill_origin);
    ground *= mix(vec3(1.0), vec3(0.61, 0.73, 0.67), wooded_foot * 0.75);
    ground = mountain_forest_floor(ground, p);

    float road = segment_distance(p, road_fork[0], road_fork[1]);
    road = min(road, segment_distance(p, bridge_spur[0], bridge_spur[1]));
    for (int i = 0; i < 11; i++) {
        road = min(road, segment_distance(p, road_points[i], road_points[i + 1]));
    }
    float width = mix(road_width.x, road_width.y, smoothstep(road_width.z, road_width.w, p.y));
    width *= 0.88 + noise(p * 0.19 + vec2(13.1, 2.7)) * 0.24;
    float edge = noise(p * 2.7) * 0.30 + noise(p * 0.85) * 0.52;
    float road_mask = 1.0 - smoothstep(width - 0.45, width + 0.82, road + edge);
    vec3 grit = texture(rock_texture, p / 6.2).rgb;
    float grit_value = dot(grit, vec3(0.299, 0.587, 0.114));
    vec3 dirt = grit * vec3(0.98, 0.96, 0.80);
    dirt *= 0.88 + noise(p * 2.7) * 0.24;
    dirt *= mix(0.77, 1.08, noise(p * 0.55 + warp * 0.3));
    // The pale daytime dust should not become a self-luminous grey ribbon at
    // night. Retain texture, lower its reflectance and shift it toward moonlight.
    dirt *= mix(vec3(1.0), vec3(0.64, 0.73, 0.88), meadow_night);
    // Meadow fingers interrupt the worn edges; the middle remains legible for
    // walking. This is material weathering, not new obstacles in the route.
    float encroaching_grass = thicket * smoothstep(0.22, 0.90, road / width) * 0.62;
    ground = mix(ground, dirt, road_mask * (0.96 - encroaching_grass));

    vec2 channel = river_shape(p);
    float shore_distance = abs(p.x - channel.x) - channel.y;
    float upper_shoulder = (1.0 - smoothstep(-78.0, -52.0, p.y)) * (3.3 + sin(p.y * 0.17 + 0.4) * 0.55);
    float bank_zone = (1.0 - smoothstep(1.25 + upper_shoulder * 0.45, 3.4 + upper_shoulder, abs(shore_distance)))
        * smoothstep(-190.0, -162.0, p.y);
    vec3 n = normalize(world_normal);
    // Height-function normals are flat at both ends of each smoothstep shelf.
    // Interpolating those endpoint normals erased the actually steep rock face.
    // Restore the real triangle orientation ONLY on the sculpted river shore.
    vec3 geometric_normal = normalize(cross(dFdx(world_position), dFdy(world_position)));
    geometric_normal *= sign(dot(geometric_normal, n));
    float sculpted_shore = smoothstep(-117.0, -104.0, p.y) * (1.0 - smoothstep(-12.0, -4.0, p.y))
        * smoothstep(7.0, 11.0, abs(p.y + 38.0));
    n = normalize(mix(n, geometric_normal, bank_zone * sculpted_shore * 0.94));
    vec3 mineral_weights = pow(abs(n), vec3(4.0));
    mineral_weights /= max(dot(mineral_weights, vec3(1.0)), 0.001);
    vec3 rock = meadow_mineral_pigment(meadow_mineral_sample(world_position, mineral_weights), world_position);
    float cliff = 1.0 - smoothstep(0.64, 0.88, n.y);
    float moss = smoothstep(0.50, 0.80, noise(p * 1.3 + world_position.y * 0.27)) * smoothstep(0.58, 0.82, n.y);
    rock = mix(rock, ground, moss * 0.55);
    ground = mix(ground, rock, cliff);
    float erosion = smoothstep(0.28, 0.72, noise(p * 2.4 + world_position.y));
    // The backing bank and embedded beds share limestone pigment. Road grit
    // belongs only in broken soil pockets, not over the entire vertical face.
    vec3 bank_weights = pow(abs(n), vec3(3.0));
    bank_weights /= max(dot(bank_weights, vec3(1.0)), 0.001);
    vec3 bank_grain = texture(rock_texture, world_position.zy / 4.6).rgb * bank_weights.x
        + texture(rock_texture, world_position.xz / 4.6).rgb * bank_weights.y
        + texture(rock_texture, world_position.xy / 4.6).rgb * bank_weights.z;
    // Metre-scaled fractured limestone belongs to the real bank mesh. Its
    // pigment contains no scene lighting; relief and daylight remain dynamic.
    vec3 bank_pigment = rock;
    if (bank_zone * cliff > 0.001) {
        vec3 bed_sample = texture(bank_limestone_texture, world_position.zy / vec2(7.2, -6.0)).rgb * bank_weights.x
            + texture(bank_limestone_texture, world_position.xz / 7.2).rgb * bank_weights.y
            + texture(bank_limestone_texture, world_position.xy / vec2(7.2, -6.0)).rgb * bank_weights.z;
        bank_pigment = mix(rock, bed_sample * vec3(0.64, 0.65, 0.59), 0.92);
    }
    vec3 bank_soil = mix(bank_pigment, bank_grain * vec3(0.60, 0.60, 0.51), erosion * 0.14);
    float grass_roots = smoothstep(0.50, 0.88, n.y) * smoothstep(0.36, 0.75, noise(p * 3.7));
    bank_soil = mix(bank_soil, ground, grass_roots * 0.74);
    ground = mix(ground, bank_soil, bank_zone * cliff * 0.88);
    float wet = 1.0 - smoothstep(-1.2, -0.1, world_position.y);
    vec3 wet_ground = mix(ground, rock * vec3(0.38, 0.47, 0.46), wet * 0.65);
    vec3 wet_bank = mix(ground, ground * vec3(0.52, 0.64, 0.71), wet * 0.75);
    ground = mix(wet_ground, wet_bank, bank_zone);
    // Actual opaque channel floor, now visible through the transparent river.
    float bed_mask = (1.0 - smoothstep(-0.25, 0.6, shore_distance)) * smoothstep(-195.0, -170.0, p.y);
    float submerged = (1.0 - smoothstep(-1.65, -1.12, world_position.y)) * bed_mask;
    float grains = noise(p * 5.0) * 0.65 + noise(p * 13.0) * 0.35;
    vec3 sediment = mix(vec3(0.16, 0.15, 0.11), vec3(0.32, 0.29, 0.21), grains);
    sediment *= 0.80 + noise(p * 0.55) * 0.28;
    float light_net = pow(1.0 - abs(sin(p.x * 2.9 + noise(p * 0.7 + meadow_clock * 0.015) * 5.0)), 12.0);
    sediment += vec3(0.11, 0.13, 0.095) * light_net * (1.0 - meadow_night * 0.80);
    ground = mix(ground, sediment, submerged);

    float shadow = 1.0;
    for (int i = 0; i < 72; i++) {
        vec4 s = contact_shadows[i];
        if (s.z > 0.0) {
            float d = length((p - s.xy) / vec2(s.z, s.w));
            shadow *= mix(0.72, 1.0, smoothstep(0.0, 1.0, d));
        }
    }
    // Low frequency moving cloud shade gives one shared lighting field.
    float pigment_cloud = mix(meadow_cloud_light(p, meadow_clock, meadow_night), 1.0,
        sunbreak_scope(world_position) * (1.0 - meadow_night) * (1.0 - submerged));
#ifdef MEADOW_FAR_GROUND_DAY
    float far_scope = far_ground_scope(world_position, road_mask, bank_zone, cliff, submerged, shore_distance);
    float far_footprint = max(length(dFdx(p)), length(dFdy(p)));
    float far_resolved = 1.0 - smoothstep(1.10, 3.00, far_footprint);
    float far_response = far_scope * far_resolved * (1.0 - meadow_night) * (1.0 - wooded_foot * 0.65);
    float sward_height = far_sward_height(p, far_footprint);
    float sward_mass = smoothstep(0.22, 0.78, sward_height);
    vec3 sward_pigment = mix(vec3(0.94, 0.96, 0.93), vec3(1.035, 1.025, 0.995), sward_mass);
    ground *= mix(vec3(1.0), sward_pigment, far_response);
    if (far_response > 0.001) {
        // Preserve the existing grass artwork at a clump-sized mip footprint.
        // Its large/small leaf groups survive where individual near-field
        // blades average out. Ratio modulation retains the underlying slope,
        // woodland and road pigments; no new painted landscape is introduced.
        vec3 clump_grass = meadow_surface(p * 0.38 + vec2(7.3, 19.1));
        vec3 clump_ratio = clamp(clump_grass / max(fine_grass, vec3(0.04)), vec3(0.60), vec3(1.40));
        ground *= mix(vec3(1.0), clump_ratio, far_response * 0.86);
    }
    FOG = far_ground_fog(VERTEX, far_scope, meadow_night);
#endif
    ALBEDO = ground * shadow * pigment_cloud * 0.98;
    // The generated grass supplies both leaf color and fine relief. World-space
    // normal perturbation needs no fake grass cards and remains outside geometry.
    vec2 detail_uv = meadow_surface_uv(p);
    float center_height = dot(texture(meadow_texture, detail_uv).rgb, vec3(0.30, 0.58, 0.12));
    float hx = dot(texture(meadow_texture, detail_uv + vec2(0.003, 0)).rgb, vec3(0.30, 0.58, 0.12));
    float hz = dot(texture(meadow_texture, detail_uv + vec2(0, 0.003)).rgb, vec3(0.30, 0.58, 0.12));
    float trail_x = dot(texture(rock_texture, p / 6.2 + vec2(0.006, 0)).rgb, vec3(0.299, 0.587, 0.114));
    float trail_z = dot(texture(rock_texture, p / 6.2 + vec2(0, 0.006)).rgb, vec3(0.299, 0.587, 0.114));
    float pixel_footprint = max(length(dFdx(p)), length(dFdy(p)));
    float resolved_relief = 1.0 - smoothstep(0.06, 0.28, pixel_footprint);
    vec2 relief = mix(vec2(center_height - hx, center_height - hz) * thicket * thicket * 0.24,
        vec2(grit_value - trail_x, grit_value - trail_z) * 1.65, road_mask) * resolved_relief;
    vec3 detailed_normal = normalize(n + vec3(relief.x, 0, relief.y) * (1.0 - cliff));
    // Bounded surface-gradient micro-relief. It cannot alter silhouette or
    // substitute for the three physically sculpted rock shelves above.
    float bank_height = dot(bank_pigment, vec3(0.30, 0.58, 0.12));
    vec3 sigma_x = dFdx(world_position);
    vec3 sigma_y = dFdy(world_position);
    vec3 rx = cross(sigma_y, n);
    vec3 ry = cross(n, sigma_x);
    float determinant = dot(sigma_x, rx);
    vec3 bank_gradient = (rx * dFdx(bank_height) + ry * dFdy(bank_height))
        * sign(determinant) / max(abs(determinant), 0.00001);
#ifdef MEADOW_FAR_GROUND_DAY
    // Reuse the surface differential rather than resampling procedural noise
    // twice more. Bound the normal slope; no silhouette or hidden displacement.
    vec3 sward_gradient = (rx * dFdx(sward_height) + ry * dFdy(sward_height))
        * sign(determinant) / max(abs(determinant), 0.00001);
    sward_gradient *= min(0.22, 0.10 / max(length(sward_gradient), 0.001));
    detailed_normal = normalize(detailed_normal - sward_gradient * far_response);
#endif
    bank_gradient *= min(0.10, 0.24 / max(length(bank_gradient), 0.001));
    detailed_normal = normalize(detailed_normal - bank_gradient * bank_zone * cliff * resolved_relief);
    NORMAL = normalize((VIEW_MATRIX * vec4(detailed_normal, 0)).xyz);
    // Dry dirt scatters broadly; grass and damp soil have a modest real
    // specular response. Do not paint white highlights into every surface.
    ROUGHNESS = mix(mix(mix(0.86, 0.97, road_mask), 0.63, wet), mix(0.94, 0.67, wet), bank_zone * cliff);
    SPECULAR = mix(mix(mix(0.16, 0.07, road_mask), 0.24, wet), 0.10, bank_zone * cliff);
    sunbreak_specular = SPECULAR;
}
