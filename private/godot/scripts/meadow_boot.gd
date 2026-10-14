extends Node
## Starts only the engine while the selected core downloads. Never reports
## meadowTimeUI.sceneReady: only the real meadow can release the loading screen.
var web: JavaScriptObject
var callback: JavaScriptObject
var entered := false

func _ready() -> void:
	if OS.has_feature("web"):
		web = JavaScriptBridge.get_interface("meadowBoot")
		callback = JavaScriptBridge.create_callback(_request)
		web.bind(callback)
		if FileAccess.file_exists("res://scripts/meadow_boot_probe.gd.remap") and JavaScriptBridge.eval("new URLSearchParams(location.search).get('root_cache_probe') === '1'"):
			var probe: Node = load("res://scripts/meadow_boot_probe.gd").new()
			get_tree().root.call_deferred("add_child", probe)
	print("MEADOW_BOOT_READY: engine only, scene not ready")

func _request(arguments: Array) -> void:
	if arguments.size() == 1 and str(arguments[0]) == "/meadow-core.pck" and not entered:
		enter.call_deferred(str(arguments[0]))

func enter(path: String) -> void:
	if entered:
		return
	entered = true
	if not ProjectSettings.load_resource_pack(path, false):
		if web != null:
			web.mounted(false, "场景资源包无法打开")
		return
	var target := FileAccess.get_file_as_string("res://progressive/boot-main-scene.txt")
	ProjectSettings.set_setting("application/run/main_scene", target)
	var error := get_tree().change_scene_to_file(target)
	if web != null:
		web.mounted(error == OK, "" if error == OK else "场景无法打开")
