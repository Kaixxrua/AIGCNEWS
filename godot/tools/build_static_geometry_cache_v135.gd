extends SceneTree
## One original-function capture/profile under actual native07 plus offline-only hooks.

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	assert(FileAccess.get_sha256(spec.core) == "a52b946f255ab9197aee180550274ddf336bc228aca9dff1a6f9551bf08f2d50")
	assert(FileAccess.get_sha256(spec.overlay) == spec.overlaySha256)
	assert(ProjectSettings.load_resource_pack(spec.overlay, true))
	set_meta("static_cache_output", str(spec.cacheDir))
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	assert(packed != null)
	var scene := packed.instantiate() as Node3D
	scene.set("audit_complete", true)
	root.add_child(scene)
	current_scene = scene
	var recorder: Script = load("res://tools/build_static_geometry_cache_v135.capture.gd")
	assert(recorder.pending.is_empty() and recorder.records.size() == 17, "Fourteen herbs, one village, two mountains")
	var counts := {}
	for record: Dictionary in recorder.records:
		counts[record.kind] = int(counts.get(record.kind, 0)) + 1
	assert(counts == {"herb": 14, "village": 1, "mountain": 2})
	var report := {"status": "PASS_CAPTURE_EXACT_RELOAD", "records": recorder.records,
		"counts": counts, "sourceCoreSha256": FileAccess.get_sha256(spec.core),
		"limitations": ["Original-function native CPU spans, not browser timings.",
			"Resource serialization/reload happens after each recorded function span.",
			"No original script, pack, art, collider or material is saved or changed."]}
	var file := FileAccess.open(spec.report, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	file.close()
	scene.free()
	quit()
