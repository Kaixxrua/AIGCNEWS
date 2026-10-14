shader_type spatial;
render_mode unshaded, cull_disabled;

uniform sampler2D sprite_texture : source_color, repeat_disable, filter_linear;
uniform vec2 texture_size = vec2(1024.0, 1024.0);
uniform float blur_radius = 0.0;

vec4 sample_sprite(vec2 uv, vec2 offset) {
	return texture(sprite_texture, clamp(uv + offset, vec2(0.0), vec2(1.0)));
}

void fragment() {
	vec2 texel = vec2(1.0) / texture_size * blur_radius;
	vec4 center = sample_sprite(UV, vec2(0.0));
	vec3 accumulated_rgb = center.rgb * center.a * 0.24;
	float accumulated_alpha = center.a * 0.24;

	vec2 offsets[8] = vec2[](
		vec2(texel.x, 0.0),
		vec2(-texel.x, 0.0),
		vec2(0.0, texel.y),
		vec2(0.0, -texel.y),
		texel * vec2(0.72, 0.72),
		texel * vec2(-0.72, 0.72),
		texel * vec2(0.72, -0.72),
		texel * vec2(-0.72, -0.72)
	);
	float weights[8] = float[](0.13, 0.13, 0.13, 0.13, 0.06, 0.06, 0.06, 0.06);
	for (int index = 0; index < 8; index++) {
		vec4 sample_color = sample_sprite(UV, offsets[index]);
		accumulated_rgb += sample_color.rgb * sample_color.a * weights[index];
		accumulated_alpha += sample_color.a * weights[index];
	}

	if (accumulated_alpha < 0.16) {
		discard;
	}
	ALBEDO = accumulated_rgb / accumulated_alpha;
	ALPHA = accumulated_alpha;
}
