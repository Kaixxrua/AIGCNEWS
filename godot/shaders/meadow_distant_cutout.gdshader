shader_type spatial;
// Far matte art has painted volume. Keep its established broad response while
// nearby physical props use Burley; both share alpha, windows and night tint.
render_mode cull_disabled, diffuse_lambert_wrap, alpha_to_coverage;
#include "res://shaders/meadow_cutout_surface.gdshaderinc"
