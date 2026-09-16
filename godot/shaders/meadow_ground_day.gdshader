shader_type spatial;
global uniform float meadow_clock;
global uniform float meadow_night;
render_mode cull_disabled;
#define MEADOW_FAR_GROUND_DAY

#include "res://shaders/meadow_ground_surface.gdshaderinc"
