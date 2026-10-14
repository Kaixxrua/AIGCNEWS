extends SceneTree
## Single explicit offline sidecar bake. No main scene, no static-cache rebuild.
const OCCLUSION = preload("res://scripts/meadow_rock_occlusion.gd")

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	quit(1) # Runtime errors in this synchronous offline pass must not report success.
	if not OS.get_cmdline_user_args().has("--bake-rock-occlusion"):
		push_error("Explicit --bake-rock-occlusion required")
		quit(1)
		return
	var detail_path := "res://assets/baked/v77/detail.scn"
	var terrain_path := "res://assets/baked/v77/terrain.scn"
	var before := [FileAccess.get_sha256(detail_path), FileAccess.get_sha256(terrain_path)]
	var detail := (load(detail_path) as PackedScene).instantiate()
	var ground := (load(terrain_path) as PackedScene).instantiate()
	# Do not add these inert resource containers to the scene tree or call _ready.
	var rock := detail.get_node("SolidLimestoneGeology") as MeshInstance3D
	var terrain := ground.get_node("ContinuousMeadow") as MeshInstance3D
	var data: Dictionary = OCCLUSION.bake(rock, terrain)
	if data.is_empty():
		detail.free()
		ground.free()
		quit(1)
		return
	data["cache_file_sha256"] = before
	var output: String = OCCLUSION.DATA_PATH
	var directory := ProjectSettings.globalize_path(output.get_base_dir())
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		push_error("ROCK_AO_BAKE: cannot create sidecar directory")
		quit(1)
		return
	var file := FileAccess.open(output, FileAccess.WRITE)
	if file == null:
		push_error("ROCK_AO_BAKE: cannot write sidecar")
		quit(1)
		return
	file.store_var(data, false)
	var size := file.get_position()
	var error := file.get_error()
	file.close()
	var unchanged := before == [FileAccess.get_sha256(detail_path), FileAccess.get_sha256(terrain_path)]
	detail.free()
	ground.free()
	if error != OK or not unchanged:
		push_error("ROCK_AO_BAKE: write error or source caches changed during bake")
		quit(1)
		return
	print("ROCK_AO_BAKE: %s; %d bytes; %s; source cache hashes unchanged; candidate, NOT visual PASS" % [output, size, str(data.stats)])
	quit(0)
