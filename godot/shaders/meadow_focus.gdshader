shader_type spatial;
render_mode unshaded, fog_disabled, cull_disabled, depth_test_disabled, depth_draw_never;
uniform sampler2D scene_color : hint_screen_texture, repeat_disable, filter_linear;
uniform sampler2D scene_depth : hint_depth_texture, repeat_disable, filter_nearest;
uniform bool enabled = true;
uniform bool show_depth = false;
uniform float near_start = 16.0;
uniform float near_end = 32.0;
uniform float far_start = 300.0;
uniform float far_end = 390.0;
uniform float near_radius = 1.25;
uniform float far_radius = 0.0;
uniform float scene_exposure = 2.0;

vec3 screen_to_linear(vec3 c) {
    // Match the pinned Godot 4.7 GLES output transfer, including its black floor.
    return pow((max(c, vec3(0)) + 0.055) / 1.055, vec3(2.4)) * step(vec3(0.000001), c);
}
vec3 screen_to_srgb(vec3 c) {
    // Invert GLES' cubic input transfer. The usual sRGB inverse crushes the
    // darkest samples on a second spatial pass; this retains moonlit detail.
    vec3 x = pow(max(c, vec3(0)), vec3(1.0 / 2.2));
    for (int i = 0; i < 5; i++) {
        vec3 value = x * (x * (x * 0.305306011 + 0.682171111) + 0.012522878);
        vec3 derivative = x * (x * 0.915918033 + 1.364342222) + 0.012522878;
        x = max(x - (value - c) / derivative, vec3(0));
    }
    return x;
}

float linear_depth(vec2 uv, mat4 inverse_projection) {
    float d = texture(scene_depth, uv).r;
    // Godot 4.3+ uses reversed Z. Compatibility also needs OpenGL [-1,1] NDC.
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    vec3 ndc = vec3(uv, d) * 2.0 - 1.0;
    #else
    vec3 ndc = vec3(uv * 2.0 - 1.0, d);
    #endif
    vec4 view = inverse_projection * vec4(ndc, 1.0);
    return -view.z / view.w;
}
void vertex() { POSITION = vec4(VERTEX.xy, 1.0, 1.0); }
void fragment() {
    float depth = linear_depth(SCREEN_UV, INV_PROJECTION_MATRIX);
    float near_coc = 1.0 - smoothstep(near_start, near_end, depth);
    float far_coc = smoothstep(far_start, far_end, depth);
    // Keep the angular blur consistent in the actual 16:10 render rectangle.
    // A fixed pixel radius would over-blur the user's narrow preview panel.
    float focus_scale = clamp(VIEWPORT_SIZE.y / 1080.0, 0.35, 2.0);
    // Keep distant architecture readable. Atmosphere should separate it,
    // not the old full 1.8px blur over every house and castle window.
    float radius = enabled ? max(near_coc * near_radius, far_coc * far_radius) * focus_scale : 0.0;
    vec3 color = texture(scene_color, SCREEN_UV).rgb;
    float weights = 1.0;
    // Subpixel diffusion only softened distant painted detail. Preserve its
    // original samples: colour, occlusion and depth layers supply atmosphere.
    if (radius > 0.20) {
      for (int i = 0; i < 16; i++) {
        float angle = float(i) * 2.399963;
        float ring = sqrt((float(i) + 0.5) / 16.0);
        vec2 offset = vec2(cos(angle), sin(angle)) * ring * radius / VIEWPORT_SIZE;
        vec2 sample_uv = clamp(SCREEN_UV + offset, vec2(0.001), vec2(0.999));
        float neighbor_depth = linear_depth(sample_uv, INV_PROJECTION_MATRIX);
        float weight = 1.0 - smoothstep(4.0, 12.0, abs(neighbor_depth - depth));
        color += texture(scene_color, sample_uv).rgb * weight;
        weights += weight;
      }
    }
    color /= weights;
    if (show_depth) { color = vec3(clamp(depth / 160.0, 0.0, 1.0)); }
    // In Compatibility, the opaque buffer is already exposed. A spatial
    // unshaded screen-copy receives that exposure again. Cancel only that
    // second gain in linear space; a real-GPU gray ramp guards this contract.
    // Glow/SSAO keep final tone mapping in the engine's post stage. The same
    // AgX + saturation then includes water and fading animals drawn after us.
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    color = screen_to_srgb(screen_to_linear(color) / max(scene_exposure, 0.01));
    #endif
    ALBEDO = color;
}
