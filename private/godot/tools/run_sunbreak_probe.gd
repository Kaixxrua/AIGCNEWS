extends SceneTree
## Native GPU regression runner; the main scene is not drawn or captured.
var completed := false

func _initialize() -> void:
	_run.call_deferred()
	create_timer(150.0).timeout.connect(_timeout)

func _run() -> void:
	if DisplayServer.get_name() == "headless":
		push_error("Sunbreak probe needs a real rendering device, not headless dummy")
		quit(1)
		return
	root.disable_3d = true
	var scene: Node3D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var passed: bool = await preload("res://tools/audit_sunbreak_lighting.gd").run(scene)
	completed = true
	scene.queue_free()
	await process_frame
	quit(0 if passed else 1)

func _timeout() -> void:
	if not completed:
		push_error("Sunbreak GPU probe timed out; no pass")
		quit(1)
