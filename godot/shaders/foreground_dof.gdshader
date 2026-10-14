shader_type spatial;
render_mode unshaded, fog_disabled, cull_disabled, depth_test_disabled, depth_draw_never;

uniform sampler2D screen_texture : hint_screen_texture, repeat_disable, filter_linear;
uniform sampler2D depth_texture : hint_depth_texture, repeat_disable, filter_nearest;
uniform float focus_depth = 32.0;
uniform float focus_range = 7.0;
uniform float max_blur = 2.0;
uniform float camera_near = 0.05;
uniform float camera_far = 120.0;
uniform vec2 viewport_size = vec2(1280.0, 720.0);

float linearize_depth(float raw_depth) {
	return camera_near * camera_far / (camera_far - raw_depth * (camera_far - camera_near));
}

vec4 sample_scene(vec2 uv, vec2 offset) {
	return texture(screen_texture, uv + offset);
}

void vertex() {
	POSITION = vec4(VERTEX.xy, 0.0, 1.0);
}

void fragment() {
	float raw_depth = texture(depth_texture, SCREEN_UV).r;
	if (raw_depth <= 0.0001) {
		// Compatibility/WebGL may expose an empty depth attachment. Preserve the
		// sharp scene instead of applying a full-screen blur in that case.
		ALBEDO = sample_scene(SCREEN_UV, vec2(0.0)).rgb;
		ALPHA = 1.0;
	} else {
		float scene_depth = linearize_depth(raw_depth);
		float distance_from_focus = abs(scene_depth - focus_depth);
		float blur_factor = smoothstep(focus_range, focus_range + 8.0, distance_from_focus);
		float radius = blur_factor * max_blur;
		vec2 texel = (vec2(1.0) / viewport_size) * radius;

		vec4 color = sample_scene(SCREEN_UV, vec2(0.0)) * 0.24;
		color += sample_scene(SCREEN_UV, vec2(texel.x, 0.0)) * 0.13;
		color += sample_scene(SCREEN_UV, vec2(-texel.x, 0.0)) * 0.13;
		color += sample_scene(SCREEN_UV, vec2(0.0, texel.y)) * 0.13;
		color += sample_scene(SCREEN_UV, vec2(0.0, -texel.y)) * 0.13;
		color += sample_scene(SCREEN_UV, texel * vec2(0.72, 0.72)) * 0.06;
		color += sample_scene(SCREEN_UV, texel * vec2(-0.72, 0.72)) * 0.06;
		color += sample_scene(SCREEN_UV, texel * vec2(0.72, -0.72)) * 0.06;
		color += sample_scene(SCREEN_UV, texel * vec2(-0.72, -0.72)) * 0.06;

		ALBEDO = color.rgb;
		ALPHA = 1.0;
	}
}
