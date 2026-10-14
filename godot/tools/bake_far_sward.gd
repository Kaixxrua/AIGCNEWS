extends SceneTree
## Explicitly bake only the additive distant grass mesh, never the five old caches.
const SWARD = preload("res://scripts/meadow_far_sward.gd")
func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _run() -> void:
	if not OS.get_cmdline_user_args().has("--bake-far-sward"):
		push_error("Pass -- --bake-far-sward to write the isolated grass mesh")
		quit(1)
		return
	var scene := load("res://scenes/main.tscn").instantiate() as Node3D
	root.add_child(scene)
	var mesh := scene.get_node(SWARD.LABEL) as MeshInstance3D
	var packed := PackedScene.new()
	assert(packed.pack(mesh) == OK)
	assert(DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(SWARD.CACHE_PATH.get_base_dir())) == OK)
	assert(ResourceSaver.save(packed, SWARD.CACHE_PATH, ResourceSaver.FLAG_COMPRESS) == OK)
	var saved := ResourceLoader.load(SWARD.CACHE_PATH, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE).instantiate() as MeshInstance3D
	assert(saved.mesh.surface_get_arrays(0) == mesh.mesh.surface_get_arrays(0))
	assert(saved.get_meta("ground_roots") == mesh.get_meta("ground_roots"))
	print("FAR_SWARD_BAKE: PASS exact mesh arrays and roots saved/reloaded; ", SWARD.CACHE_PATH, " sha256=", FileAccess.get_sha256(SWARD.CACHE_PATH))
	saved.free()
	quit(0)
