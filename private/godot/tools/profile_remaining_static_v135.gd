extends SceneTree
## One instrumented inherited instance; real main GDC and controller unchanged.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	assert(FileAccess.get_sha256(spec.core) == "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93")
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	assert(packed != null)
	var scene := packed.instantiate() as Node3D
	var derived := load(str(spec.derived)) as Script
	assert(derived != null and derived.can_instantiate())
	scene.set_script(derived)
	scene.set("audit_complete", true)
	var started := Time.get_ticks_usec()
	root.add_child(scene)
	current_scene = scene
	var ready_ms := (Time.get_ticks_usec() - started) / 1000.0
	var state: Dictionary = scene.get_meta("_meadow_static_geometry_cache_v135")
	assert(state.valid and state.hits.size() == 17 and state.misses.is_empty())
	var saved := Resource.new()
	saved.set_meta("records", scene.profile_root_meshes)
	assert(ResourceSaver.save(saved, spec.rootResource, ResourceSaver.FLAG_COMPRESS) == OK)
	var loaded := ResourceLoader.load(spec.rootResource, "Resource", ResourceLoader.CACHE_MODE_IGNORE)
	assert(loaded.get_meta("records").keys() == scene.profile_root_meshes.keys())
	for key: String in scene.profile_root_meshes:
		var original: Dictionary = scene.profile_root_meshes[key]
		var restored: Dictionary = loaded.get_meta("records")[key]
		assert(original.context == restored.context and original.wholeColumn == restored.wholeColumn)
		assert(var_to_bytes(original.mesh.surface_get_arrays(0)) == var_to_bytes(restored.mesh.surface_get_arrays(0)))
	var report := {"status": "PASS_ONE_NATIVE_PROFILE", "readyMs": ready_ms, "rows": scene.profile_rows,
		"cache": state, "rootMeshCount": scene.profile_root_meshes.size(),
		"limits": "Native headless inclusive CPU spans with test-only timers; not Web time, not first-draw proof. Saving/reload of conform capture occurs after ready timing."}
	var stream := FileAccess.open(spec.report, FileAccess.WRITE)
	stream.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	stream.close()
	scene.free()
	quit()
