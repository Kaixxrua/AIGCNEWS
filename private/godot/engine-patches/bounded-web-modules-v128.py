"""Scene-pinned Web SCons profile; use with the existing lazy-web-variants.patch.

Upstream ed1daf0bf001b61586d9930840f2f1394092c079; this is not a universal template.
Matches v128 module-policy.json and the recorded command, without class pruning.
See bounded-web-modules-v128.md before applying to an isolated engine checkout.
"""

platform = "web"
target = "template_release"
threads = False
arch = "wasm32"
production = True
lto = "thin"
optimize = "size"
debug_symbols = False
use_closure_compiler = False
javascript_eval = True
dlink_enabled = False
wasm_simd = True
progress = False
linkflags = "-Wl,--threads=4 -Wl,--thinlto-jobs=4"
num_jobs = 4

disable_physics_2d = True
disable_navigation_2d = True
disable_xr = True
minizip = False

disable_3d = False
disable_advanced_gui = False
disable_physics_3d = False
disable_navigation_3d = False
deprecated = True
brotli = True
opengl3 = True

module_astcenc_enabled = False
module_basis_universal_enabled = False
module_bcdec_enabled = False
module_bmp_enabled = False
module_dds_enabled = False
module_etcpak_enabled = False
module_hdr_enabled = False
module_jpg_enabled = False
module_ktx_enabled = False
module_tga_enabled = False
module_tinyexr_enabled = False
module_csg_enabled = False
module_fbx_enabled = False
module_gltf_enabled = False
module_gridmap_enabled = False
module_meshoptimizer_enabled = False
module_vhacd_enabled = False
module_visual_shader_enabled = False
module_noise_enabled = False
module_interactive_music_enabled = False
module_mp3_enabled = False
module_ogg_enabled = False
module_theora_enabled = False
module_vorbis_enabled = False
module_enet_enabled = False
module_jsonrpc_enabled = False
module_multiplayer_enabled = False
module_upnp_enabled = False
module_webrtc_enabled = False
module_zip_enabled = False
module_godot_physics_2d_enabled = False
module_navigation_2d_enabled = False
module_jolt_physics_enabled = False
module_mobile_vr_enabled = False
module_webxr_enabled = False
module_regex_enabled = False

module_freetype_enabled = True
module_gdscript_enabled = True
module_godot_physics_3d_enabled = True
module_mbedtls_enabled = True
module_msdfgen_enabled = True
module_navigation_3d_enabled = True
module_svg_enabled = True
module_text_server_adv_enabled = True
module_webp_enabled = True
module_websocket_enabled = True
