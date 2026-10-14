shader_type sky;

global uniform float meadow_clock;
global uniform float meadow_night;
// Analytically integrated soft cloud volumes: no ray-step bands or jitter.
uniform vec4 cloud_centres[48];
uniform vec3 cloud_radii[48];
// These are supplied from the actual directional-light transforms. A painted
// low moon must not contradict the higher light that casts the scene shadows.
uniform vec3 sun_direction = vec3(0.70, 0.67, 0.25);
uniform vec3 moon_direction = vec3(-0.506, 0.469, -0.723);
uniform vec3 cloud_light_direction = vec3(0.70, 0.67, 0.25);

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float hash3(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}
float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float volume_noise(vec3 p) {
    vec3 i = floor(p); vec3 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    float a = mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x);
    float b = mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x);
    float c = mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x);
    float d = mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x);
    return mix(mix(a, b, f.y), mix(c, d, f.y), f.z);
}
float night_stars(vec3 ray) {
    // Angular cells cover the low, roughly 9-degree sky strip in the fixed view.
    // One sparse, inset-jittered point per cell: no aligned centres or neighbours loop.
    // Keep atan defined at cubemap poles, outside the preview's low-angle strip.
    vec2 horizontal = dot(ray.xz, ray.xz) < 0.00000001 ? vec2(0.0, -0.0001) : ray.xz;
    vec2 star_uv = vec2(atan(horizontal.x, -horizontal.y), asin(clamp(ray.y, -1.0, 1.0))) * 210.0;
    vec2 cell = floor(star_uv);
    vec2 centre = vec2(hash3(vec3(cell, 2.17)), hash3(vec3(cell, 7.91))) * 0.54 + 0.23;
    float patches = noise(cell * 0.021 + vec2(8.7, 19.3));
    float occupied = step(1.0 - mix(0.055, 0.090, patches), hash3(vec3(cell, 11.73)));
    float brilliance = hash3(vec3(cell, 23.41));
    float size_seed = hash3(vec3(cell, 41.37));
    float main_star = step(0.86, brilliance);
    // Larger anchor stars remain readable when the Web preview fits the window.
    float radius = mix(0.100, 0.140, size_seed) + main_star * 0.055;
    // Filter the continuous angular coordinates, never fract/floor discontinuities.
    // Area compensation avoids inflating subpixel stars into a bright cubemap haze.
    // Compact support stays inside the fixed inset, including low-resolution passes.
    float half_pixel = max(length(fwidth(star_uv)) * 0.5, 0.0001);
    float filtered_area = radius * radius + half_pixel * half_pixel;
    float filtered_radius = min(sqrt(filtered_area), 0.22);
    float point = 1.0 - smoothstep(0.0, filtered_radius, length(fract(star_uv) - centre));
    point *= radius * radius / filtered_area;
    // A few bright anchors stand above the fine field without dimming the scene.
    float strength = mix(0.40, 0.75, brilliance * brilliance) + main_star * 1.60;
    // Only the brightest ~14% breathe by +/-8%; positions never depend on time.
    float twinkle = 1.0 + main_star * 0.08 * sin(meadow_clock * mix(0.55, 0.90, size_seed) + size_seed * 6.2831853);
    return occupied * point * strength * twinkle;
}
vec4 cumulus(vec3 ray, vec3 light_direction) {
    float optical_depth = 0.0;
    vec3 weighted_light = vec3(0.0);
    vec3 shade = mix(vec3(0.40, 0.48, 0.60), vec3(0.19, 0.27, 0.42), meadow_night);
    vec3 lit = mix(vec3(1.02, 0.99, 0.91), vec3(0.57, 0.69, 0.88), meadow_night);
    for (int i = 0; i < 48; i++) {
        vec3 centre = cloud_centres[i].xyz;
        // Wrap outside this layer's visible frustum, including its soft edge.
        float wind_limit = abs(centre.z) * 0.80 + 48.0;
        centre.x = mod(centre.x + meadow_clock * cloud_centres[i].w + wind_limit, wind_limit * 2.0) - wind_limit;
        vec3 size = cloud_radii[i];
        vec3 direction = ray / size;
        vec3 relative = -centre / size;
        float a = dot(direction, direction);
        float closest_t = -dot(relative, direction) / a;
        vec3 closest = relative + direction * closest_t;
        float distance_squared = dot(closest, closest);
        if (closest_t < 0.0 || distance_squared > 3.8) { continue; }
        // Two cloud-local scales break the edge into billows and small wisps.
        // Both travel with their volume, so the surface cannot scroll like a
        // water ripple. The analytic integration still has no marching bands.
        vec3 local = ray * closest_t - centre;
        float erosion = volume_noise(local * vec3(0.78, 0.92, 0.70) + float(i) * 3.71);
        float fine_erosion = volume_noise(local * 1.80 + float(i) * 7.13);
        distance_squared = max(distance_squared + (erosion - 0.5) * 0.54 + (fine_erosion - 0.5) * 0.13, 0.0);
        float body = max(1.0 - distance_squared, 0.0);
        // An opaque rounded core plus a very thin soft fringe: a broad pure
        // Gaussian made the whole cloud look out of focus in the Web preview.
        float density = (body * body * 1.10 + exp(-distance_squared * 3.5) * 0.018) / sqrt(a);
        // Near isodensity surface gives a real ellipsoid normal; overlapping
        // density merges billows rather than outlining separate spheres.
        float front_t = closest_t - sqrt(max(1.0 - distance_squared, 0.08) / a);
        vec3 normal = normalize((ray * front_t - centre) / (size * size));
        float facing = max(dot(normal, light_direction), 0.0);
        float upper = smoothstep(-0.65, 0.80, normal.y);
        float billow_light = (erosion - 0.5) * 0.13 * body;
        vec3 scattering = mix(shade, lit, clamp(facing * 0.62 + upper * 0.30 + billow_light, 0.0, 1.0));
        weighted_light += scattering * density;
        optical_depth += density;
    }
    float opacity = (1.0 - exp(-optical_depth)) * smoothstep(0.006, 0.026, ray.y);
    return vec4(weighted_light / max(optical_depth, 0.0001), opacity);
}
void sky() {
    float height = max(EYEDIR.y, 0.0);
    vec3 blue = mix(vec3(0.51, 0.62, 0.70), vec3(0.20, 0.34, 0.50), smoothstep(0.0, 0.20, height));
    // Same upper-right/front source as KeyLight (-42, 70), not backlighting
    // every cloud while the meadow is lit from the opposite direction.
    float glow = pow(max(dot(EYEDIR, sun_direction), 0.0), 12.0);
    vec3 day = blue + vec3(0.21, 0.16, 0.085) * glow;
    vec3 night = mix(vec3(0.15, 0.19, 0.27), vec3(0.072, 0.105, 0.17), smoothstep(0.0, 0.20, height));
    float moon_distance = length(EYEDIR - moon_direction);
    float moon = 1.0 - smoothstep(0.0045, 0.0052, moon_distance);
    float halo = exp(-moon_distance * 25.0) * 0.065;
    // Reach full visibility near 4.9 degrees, within the visible low-angle sky.
    float stars = night_stars(EYEDIR) * smoothstep(0.010, 0.085, height);
    stars *= smoothstep(0.35, 0.90, meadow_night);
    night += vec3(0.53, 0.65, 0.88) * (stars + moon * 0.9 + halo);
    vec3 background = mix(day, night, meadow_night);
    if (height > 0.006 && !AT_CUBEMAP_PASS) {
        vec4 cloud = cumulus(EYEDIR, normalize(cloud_light_direction));
        // Extinguish point stars through visible fringes, not the sky/moon or cloud light.
        // Zero opacity keeps v83 exactly; the original cloud mix still follows.
        float star_occlusion = smoothstep(0.01, 0.12, cloud.a);
        background -= vec3(0.53, 0.65, 0.88) * stars * meadow_night * star_occlusion;
        background = mix(background, cloud.rgb, cloud.a);
    }
    COLOR = background;
}
