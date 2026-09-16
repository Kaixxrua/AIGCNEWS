global uniform float meadow_clock;
global uniform float meadow_night;
#ifdef MEADOW_SUNBREAK
#include "res://shaders/meadow_sunbreak.gdshaderinc"
#endif
uniform sampler2D asset_texture : source_color, repeat_disable, filter_linear_mipmap_anisotropic;
uniform vec4 tint : source_color = vec4(1.0);
uniform float alpha_threshold = 0.16;
uniform float bottom_fade = 0.0;
uniform bool face_camera = true;
uniform float edge_inset = 0.0;
uniform bool remove_pale_matte = false;
uniform vec4 uv_region = vec4(0.0, 0.0, 1.0, 1.0);
uniform float painted_fill = 0.15;
uniform float relief_strength = 0.75;
uniform float leaf_transmission = 0.0;
uniform float art_contrast = 1.0;
uniform float art_exposure = 1.0;
// Only plant art opts into a black-preserving reflectance toe. This is not
// emissive fill: without incident light these colours still render black.
uniform bool foliage_tone = false;
uniform float wind_strength = 0.0;
uniform bool rooted_herb = false;
uniform bool lantern_flame = false;
uniform float mip_bias = 0.0;
uniform bool sprite_flip = false;
uniform float sprite_bank = 0.0;
uniform float sprite_profile = 1.0;
uniform float creature_visibility = 1.0;
uniform float creature_glow = 0.0;
uniform int window_count = 0;
// Source-image UV centres and half extents, measured on real painted openings.
uniform vec4 lit_windows[32];
uniform float window_energy = 2.0;
uniform float root_contact = 0.0;
uniform vec4 soil_bounds = vec4(0.0, 0.0, 1.0, 1.0);
uniform float soil_heights[25];
varying vec3 art_world_position;
#ifdef MEADOW_MOUNTAIN
#include "res://shaders/meadow_mountain.gdshaderinc"
#endif
#ifdef MEADOW_MOUNTAIN_DAY_FOG
#include "res://shaders/meadow_mountain_fog.gdshaderinc"
#endif
#ifdef MEADOW_GROVE_DAY_FOG
#include "res://shaders/meadow_grove_fog.gdshaderinc"
#endif
#include "res://shaders/meadow_canopy.gdshaderinc"
#ifdef MEADOW_ARCHITECTURE
#include "res://shaders/meadow_architecture.gdshaderinc"
#endif
#ifdef MEADOW_ARCHITECTURE_DAY_FOG
#include "res://shaders/meadow_architecture_fog.gdshaderinc"
#endif

float window_box_coverage(vec2 at_uv, vec2 half_pixel, vec4 opening) {
    // Analytic pixel/window overlap keeps distant subpixel panes from popping
    // off between fragment centres, without inflating the painted opening.
    vec2 overlap = max(vec2(0.0), min(at_uv + half_pixel, opening.xy + opening.zw)
        - max(at_uv - half_pixel, opening.xy - opening.zw));
    return clamp(overlap.x * overlap.y / max(4.0 * half_pixel.x * half_pixel.y, 0.000000000001), 0.0, 1.0);
}

vec3 graded_art(vec3 raw) {
    vec3 pigment = max(raw * tint.rgb, vec3(0.0));
    vec3 shoulder = (pigment - vec3(0.18)) * art_contrast + vec3(0.18);
    if (foliage_tone) {
        // GLES3 supplies sRGB-encoded source channels here; the engine converts
        // to linear after the custom fragment. The old affine contrast clips
        // below ~0.019 (1.12) or ~0.037 (1.26), before shadows contribute.
        // This rational toe is positive for every positive source channel,
        // matches value AND derivative at 0.18, and leaves the shoulder exact.
        vec3 low = pigment / max(vec3(art_contrast) + (1.0 - art_contrast)
            * clamp(pigment / 0.18, vec3(0.0), vec3(1.0)), vec3(0.001));
        return mix(low, shoulder, step(vec3(0.18), pigment)) * art_exposure;
    }
    return max(shoulder, vec3(0.0)) * art_exposure;
}

void vertex() {
    VERTEX.x *= sprite_profile;
    // Animated creatures bank about their registered body centre, not the PNG.
    VERTEX.xy = mat2(vec2(cos(sprite_bank), sin(sprite_bank)), vec2(-sin(sprite_bank), cos(sprite_bank))) * VERTEX.xy;
    // The root band never moves. Subdivided crowns bend softly, not rigid cards.
    float tip = 1.0 - UV.y;
    float weight = smoothstep(0.12, 0.46, tip) * tip * tip;
    // New herb surfaces have per-column source feet, not one horizontal UV base.
    // Their explicit vertex weight pins those measured roots during every gust.
    if (rooted_herb) { weight *= COLOR.a; }
    float phase = MODEL_MATRIX[3].x * 0.17 + MODEL_MATRIX[3].z * 0.11;
    float gust = sin(meadow_clock * 1.35 + phase) * 0.70
        + sin(meadow_clock * 2.17 + phase * 1.7 + VERTEX.x * 0.8) * 0.30;
    VERTEX.x += gust * wind_strength * weight;
    VERTEX.y += sin(meadow_clock * 1.71 + phase + UV.x * 4.0) * wind_strength * weight * 0.18;
    if (face_camera) {
        // Billboarding belongs to the material. A custom fragment shader alone
        // must not replace the built-in billboard transform.
        // Keep the artwork oriented to the MAIN camera even in the sun's shadow
        // pass. Facing the light here would produce unrelated moving shadows.
        MODELVIEW_MATRIX = VIEW_MATRIX * mat4(MAIN_CAM_INV_VIEW_MATRIX[0], MAIN_CAM_INV_VIEW_MATRIX[1], MAIN_CAM_INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
        MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);
    }
    art_world_position = (INV_VIEW_MATRIX * MODELVIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
#ifdef MEADOW_SUNBREAK
    sunbreak_position = art_world_position;
#endif
}
void fragment() {
    vec2 sprite_uv = vec2(sprite_flip ? 1.0 - UV.x : UV.x, UV.y);
#ifdef MEADOW_GROVE_DAY_FOG
    FOG = grove_fog(VERTEX, sprite_uv, meadow_night);
#endif
#ifdef MEADOW_MOUNTAIN_DAY_FOG
    FOG = mountain_fog(VERTEX, sprite_uv, meadow_night);
#endif
#ifdef MEADOW_ARCHITECTURE_DAY_FOG
    FOG = architecture_fog(VERTEX, sprite_uv, meadow_night);
#endif
    vec2 uv = uv_region.xy + sprite_uv * uv_region.zw;
    vec4 source = texture(asset_texture, uv, mip_bias);
    vec4 color = vec4(graded_art(source.rgb), source.a * tint.a);
    // Far landmark art already contains broad painted light. Restore its deep
    // forest tones before shared tone mapping/fog rather than removing atmosphere.
    float opacity = color.a * creature_visibility;
    if (edge_inset > 0.0) {
        vec2 texel = vec2(edge_inset) / vec2(textureSize(asset_texture, 0));
        float inner_alpha = min(min(texture(asset_texture, uv + vec2(texel.x, 0), mip_bias).a,
            texture(asset_texture, uv - vec2(texel.x, 0), mip_bias).a),
            min(texture(asset_texture, uv + vec2(0, texel.y), mip_bias).a,
            texture(asset_texture, uv - vec2(0, texel.y), mip_bias).a));
        opacity = min(opacity, inner_alpha);
    }
    if (remove_pale_matte) {
        float darkest = min(color.r, min(color.g, color.b));
        float saturation = max(color.r, max(color.g, color.b)) - darkest;
        float matte = smoothstep(0.38, 0.75, darkest) * (1.0 - smoothstep(0.06, 0.23, saturation));
        opacity *= 1.0 - matte;
    }
    if (bottom_fade > 0.0) {
        opacity *= smoothstep(0.0, bottom_fade, 1.0 - UV.y);
    }
    vec2 pixel = 1.0 / vec2(textureSize(asset_texture, 0));
    vec3 metric = vec3(0.30, 0.58, 0.12);
    float l = dot(color.rgb, metric);
    vec4 neighbor_x = texture(asset_texture, uv + vec2(pixel.x * 2.0, 0), mip_bias);
    vec4 neighbor_y = texture(asset_texture, uv + vec2(0, pixel.y * 2.0), mip_bias);
    // Different grading on the centre and neighbours introduced a false
    // constant slope whenever exposure/contrast changed. Alpha gutters must
    // not introduce a dark bevel around otherwise intact foliage either.
    float dx = (dot(graded_art(neighbor_x.rgb), metric) - l) * step(alpha_threshold, neighbor_x.a);
    float dy = (dot(graded_art(neighbor_y.rgb), metric) - l) * step(alpha_threshold, neighbor_y.a);
    vec3 rounded = normalize(vec3((UV.x - 0.5) * 0.95 - dx * 1.5,
        (0.60 - UV.y) * 0.8 + dy * 1.5, 1.0));
    NORMAL = normalize(mix(NORMAL, rounded, relief_strength));
    if (canopy_count > 0) {
        float leaf_orientation_mask = 0.0;
        vec3 leaf_up = vec3(0.0, 1.0, 0.0);
        if (canopy_leaf_orientation) {
            leaf_orientation_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);
            // NORMAL is in view space; use gravity's up, independent of light/time.
            leaf_up = normalize(mat3(VIEW_MATRIX) * vec3(0.0, 1.0, 0.0));
        }
        NORMAL = meadow_canopy_normal(NORMAL, sprite_uv, vec2(-dx, dy),
            leaf_orientation_mask, leaf_up);
    }
#ifdef MEADOW_ARCHITECTURE
    vec4 architecture = architecture_surface(uv);
    NORMAL = normalize(mix(NORMAL, mat3(VIEW_MATRIX) * architecture.xyz, architecture.w));
    // A bounded correction of broad painted sunlight, retaining brick/window
    // detail and occlusion. New directional lighting supplies the plane contrast.
    vec3 painted_key = normalize(vec3(0.66, 0.71, 0.25));
    float painted_irradiance = 0.64 + 0.36 * max(dot(architecture.xyz, painted_key), 0.0);
    color.rgb *= mix(1.0, clamp(0.80 / painted_irradiance, 0.84, 1.25), architecture.w * 0.55);
#endif
    float leaf_pigment_gain = 1.0;
    if (canopy_pigment_recovery && canopy_count > 0) {
        float leaf_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);
        // The source includes painted lighting, not unlit albedo. Partially
        // recover only its dark leaf pigment before real light acts on it.
        // Bounded RGB scaling retains hue/texture and exact black; high source
        // colours and wood are unchanged. This adds no incident light.
        float source_luma = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));
        float painted_shadow = 1.0 - smoothstep(0.18, 0.42, source_luma);
        leaf_pigment_gain += 0.25 * leaf_mask * painted_shadow;
    }
    if (root_contact > 0.0) {
        vec2 grid = clamp((art_world_position.xz - soil_bounds.xy) / soil_bounds.zw * 4.0, vec2(0.0), vec2(3.999));
        ivec2 cell = ivec2(floor(grid));
        vec2 f = fract(grid);
        int k = cell.y * 5 + cell.x;
        float soil_y = mix(mix(soil_heights[k], soil_heights[k + 1], f.x),
            mix(soil_heights[k + 5], soil_heights[k + 6], f.x), f.y);
        float root = 1.0 - smoothstep(0.04, 0.80, art_world_position.y - soil_y);
        color.rgb *= mix(vec3(1.0), vec3(0.69, 0.78, 0.63), root * root_contact);
    }
    ALBEDO = color.rgb * leaf_pigment_gain * (1.0 - painted_fill) * mix(vec3(1.0), vec3(0.78, 0.90, 1.0), meadow_night);
    // Painted distant light must become moonlight too, not stay daylight-white.
    EMISSION = color.rgb * painted_fill * mix(vec3(1.0), vec3(0.36, 0.43, 0.54), meadow_night);
#ifdef MEADOW_MOUNTAIN
    meadow_mountain_surface(uv, clamp(1.0 - meadow_night, 0.0, 1.0), mat3(VIEW_MATRIX), NORMAL, ALBEDO, EMISSION);
#endif
#ifdef MEADOW_ARCHITECTURE
    // Remove the uniformly glowing painted fill, not the stone's reflectance.
    // Keep actual sun/moon response, relief and windows exactly independent.
    // Sheltered masonry receives less baked fill than bright painted stone;
    // retain more at night so settlement silhouettes remain readable.
    float painted_value = dot(source.rgb, vec3(0.2126, 0.7152, 0.0722));
    float painted_highlight = smoothstep(0.08, 0.80, painted_value);
    float daylight_fill = mix(0.10, 0.50, painted_highlight);
    float moonlight_fill = mix(0.65, 0.85, painted_highlight);
    EMISSION *= mix(daylight_fill, moonlight_fill, meadow_night);
    // Day-only material separation on existing source-aligned planes. Skip the
    // operation entirely at the night endpoint; painted fill/windows stay exact.
    float architecture_day = clamp(1.0 - meadow_night, 0.0, 1.0);
    // Whole-asset pigment is independent of profile coverage/strength. Retain
    // source hue and detail, with bounded channel scaling and exact black.
    if (architecture_day > 0.0) {
        float architecture_value = dot(ALBEDO, vec3(0.2126, 0.7152, 0.0722));
        vec3 architecture_color = vec3(architecture_value)
            + (ALBEDO - vec3(architecture_value)) * 1.25;
        architecture_color = clamp(architecture_color, ALBEDO * 0.75, ALBEDO * 1.25) * 0.90;
        ALBEDO = mix(ALBEDO, architecture_color, architecture_day);
    }
    if (architecture_day > 0.0 && architecture.w > 0.0) {
        // Green/olive source pixels can sit inside the broad masonry profiles.
        float green_excess = (source.g - 0.5 * (source.r + source.b)) / max(painted_value, 0.04);
        float source_green = smoothstep(0.015, 0.09, green_excess)
            * (1.0 - smoothstep(0.02, 0.10, source.r - source.g));
        float roof = smoothstep(0.30, 0.70, architecture.y);
        float facing = smoothstep(0.08, 0.55, dot(architecture.xyz, painted_key));
        float stone = (1.0 - roof) * smoothstep(0.10, 0.50, painted_value);
        float source_warmth = mix(0.45, 1.0, smoothstep(-0.03, 0.10, source.r - source.b));
        // Local wall tint excludes roof planes. Walls exchange bounded
        // chroma while preserving ALBEDO luminance in this shader's colour space.
        float wall_weight = architecture_day * clamp(architecture.w, 0.0, 1.0)
            * stone * (1.0 - source_green);
        float wall_value = dot(ALBEDO, vec3(0.2126, 0.7152, 0.0722));
        if (wall_weight > 0.0 && wall_value > 0.000001) {
            vec3 wall_gain = mix(vec3(0.94, 1.0, 1.14), vec3(1.16, 1.0, 0.95), facing * source_warmth);
            vec3 wall_color = ALBEDO * wall_gain;
            wall_color *= wall_value / dot(wall_color, vec3(0.2126, 0.7152, 0.0722));
            ALBEDO = mix(ALBEDO, wall_color, wall_weight);
        }
    }
#endif
    // No all-body neon outline. Only pale antler cores and cool bright fur
    // markings emit; all other fur still receives the shared scene lighting.
    float pale_core = smoothstep(0.38, 0.82, max(source.r, max(source.g, source.b)));
    float antler_band = 1.0 - smoothstep(0.36, 0.48, UV.y);
    float cool_spot = smoothstep(0.025, 0.13, source.b - source.r)
        * smoothstep(0.68, 0.88, max(source.r, max(source.g, source.b)));
    EMISSION += vec3(0.50, 0.83, 1.0) * max(pale_core * antler_band, cool_spot * 0.48) * creature_glow;
    if (window_count > 0 && meadow_night > 0.01) {
        float window_glow = 0.0;
        vec2 half_pixel = max(fwidth(uv) * 0.5, pixel * 0.5);
        for (int i = 0; i < 32; i++) {
            if (i >= window_count) { break; }
            vec4 opening = lit_windows[i];
            vec2 distance_uv = abs(uv - opening.xy) / max(opening.zw, pixel * 0.5);
            float pane = window_box_coverage(uv, half_pixel, opening);
            float spill = exp(-dot(distance_uv, distance_uv) * 0.60) * 0.12;
            // Mostly steady interior lamps, with different very small changes.
            float candle = 0.96 + sin(meadow_clock * 1.1 + float(i) * 2.37) * 0.04;
            window_glow += (pane + spill) * candle;
        }
        EMISSION += vec3(1.0, 0.57, 0.24) * min(window_glow, 1.35)
            * window_energy * smoothstep(0.30, 0.90, meadow_night);
    }
    if (lantern_flame) {
        float glass = smoothstep(0.54, 0.57, UV.x) * (1.0 - smoothstep(0.72, 0.75, UV.x))
            * smoothstep(0.39, 0.41, UV.y) * (1.0 - smoothstep(0.49, 0.50, UV.y));
        float warm = smoothstep(0.10, 0.35, source.r - source.b) * smoothstep(0.35, 0.80, source.r);
        float flicker = 1.0 + sin(meadow_clock * 6.3) * 0.035 + sin(meadow_clock * 10.7) * 0.015;
        EMISSION += vec3(1.0, 0.60, 0.28) * glass * warm * meadow_night * flicker * 2.4;
    }
    ROUGHNESS = 0.91;
    SPECULAR = 0.04;
#ifdef MEADOW_SUNBREAK
    sunbreak_specular = SPECULAR;
#endif
    // Thin leaves transmit a little light; stone, buildings and lamp posts do
    // not. Broad Lambert wrapping previously lit every cutout like foliage.
    BACKLIGHT = color.rgb * leaf_transmission;
    if (canopy_backlight && canopy_count > 0) {
        float leaf_mask = meadow_canopy_leaf_mask(sprite_uv, source.rgb);
        if (leaf_mask > 0.0) {
            // Avoid multiplying leaf reflectance again; retain the existing
            // transmission amount (0.10 on these trees), with a soft mask edge.
            // A zero mask keeps the original assignment above exactly.
            BACKLIGHT = mix(BACKLIGHT, vec3(leaf_transmission), leaf_mask);
        }
    }
    ALPHA = opacity;
    // Alpha-scissor puts cutouts in the depth-writing opaque pass. Plain
    // discard + ALPHA would instead create transparency sorting regressions.
    ALPHA_SCISSOR_THRESHOLD = alpha_threshold;
    ALPHA_ANTIALIASING_EDGE = alpha_threshold * 0.65;
    ALPHA_TEXTURE_COORDINATE = uv * vec2(textureSize(asset_texture, 0));
}
