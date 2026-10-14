shader_type spatial;
uniform sampler2D wood_texture : source_color, repeat_enable, filter_linear_mipmap_anisotropic;
void fragment() {
    vec3 wood = texture(wood_texture, UV).rgb;
    ALBEDO = wood * COLOR.rgb * vec3(0.77, 0.72, 0.61);
    ROUGHNESS = 0.94;
    SPECULAR = 0.06;
}
