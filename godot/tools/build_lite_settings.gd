extends SceneTree
## Run against the original PCK via --main-pack. Only save a new artifact file.
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 1 or not args[0].ends_with("project.binary") or FileAccess.file_exists(args[0]):
		push_error("Expected one NEW output project.binary path")
		quit(1)
		return
	# Scale only the 3D buffer. Canvas/UI and the original 16:10 composition stay.
	ProjectSettings.set_setting("rendering/scaling_3d/scale", 0.5)
	ProjectSettings.set_setting("rendering/scaling_3d/mode", 0)
	ProjectSettings.set_setting("rendering/lights_and_shadows/directional_shadow/size", 2048)
	ProjectSettings.set_setting("rendering/anti_aliasing/quality/msaa_3d", 1)
	var error := ProjectSettings.save_custom(args[0])
	print("LITE_SETTINGS: scale=0.5, bilinear, shadow=2048, msaa=2x, save=%d" % error)
	quit(0 if error == OK else 1)
