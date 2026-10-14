shader_type spatial;
// Preserve the original distant material's diffuse/alpha modes, including night.
render_mode cull_disabled, diffuse_lambert_wrap, alpha_to_coverage;
#define MEADOW_MOUNTAIN
#include "res://shaders/meadow_cutout_surface.gdshaderinc"
