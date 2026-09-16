extends SceneTree
## Bounded inspection/validation only; never instantiate the scene or run _ready.
var failures := 0

func _check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error("STARTUP_SIDECAR: " + message)

func _contract(script: GDScript) -> Dictionary:
	var methods := script.get_script_method_list()
	methods.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	var properties := script.get_script_property_list()
	# Godot adds a UI category whose name/path is this scratch .gdc filename;
	# it is not a script member. Normalize ONLY that exact category identity.
	properties = properties.filter(func(p: Dictionary) -> bool:
		return not (int(p.usage) == PROPERTY_USAGE_CATEGORY and str(p.hint_string) == script.resource_path))
	properties.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	var signals := script.get_script_signal_list()
	signals.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	return {"base":script.get_instance_base_type(), "methods":methods, "properties":properties, "signals":signals}

func _exercise_function(function: String, debug_build: bool, helpers: String = "", flags: PackedStringArray = PackedStringArray(), web: bool = false, query: bool = false, reenter: bool = false) -> Dictionary:
	# Exact extracted shipping function, with only the stock build-type query
	# replaced by an injected Boolean for testing both release/debug branches.
	var harness := GDScript.new()
	harness.source_code = """extends Node3D
var audit_complete := false
var audit_count := 0
var mock_debug := false
var mock_args := PackedStringArray()
var mock_web := false
var mock_query := false
var reenter_audit := false
var guard_during_audit := false
var mock_clock := 100000
var bridge_calls := PackedStringArray()
var scale_guide := Node3D.new()
var walker := Node3D.new()
var travel := 0.0
var route_length := 10.0
const PLAYER_HEIGHT := 1.8
func _audit_walk_surface() -> void:
	audit_count += 1
	guard_during_audit = audit_complete
	if reenter_audit:
		reenter_audit = false
		_physics_process(0.0)
	mock_clock += 34125
func _mock_bridge_eval(code: String) -> Variant:
	bridge_calls.append(code)
	return mock_query if code.contains("URLSearchParams") else null
func _mock_ticks_usec() -> int:
	return mock_clock
func _point_on_route(distance: float) -> Vector2:
	return Vector2(distance, -12.0)
func terrain_height(_x: float, _z: float) -> float:
	return 0.12
""" + (function + "\n" + helpers).replace("OS.is_debug_build()", "mock_debug").replace("OS.get_cmdline_user_args()", "mock_args").replace("OS.has_feature(\"web\")", "mock_web").replace("JavaScriptBridge.eval", "_mock_bridge_eval").replace("Time.get_ticks_usec()", "_mock_ticks_usec()")
	_check(harness.reload() == OK, "Exact function harness parses")
	var subject: Node3D = harness.new()
	subject.mock_debug = debug_build
	subject.mock_args = flags
	subject.mock_web = web
	subject.mock_query = query
	subject.reenter_audit = reenter
	subject.scale_guide.visible = false
	subject._physics_process(0.25)
	_check(subject.audit_complete, "First-frame audit_complete set for every build")
	_check(subject.travel == 0.0, "Hidden scale guide retains early return")
	var first_audits: int = subject.audit_count
	subject._physics_process(0.25)
	_check(subject.audit_count == first_audits, "First-frame audit remains once-only")
	subject.scale_guide.visible = true
	subject._physics_process(0.5)
	_check(subject.travel == 0.75, "Ordinary physics travel preserved")
	_check(subject.walker.position.is_equal_approx(Vector3(0.75, 1.02, -12.0)), "Walker route/height processing preserved")
	_check(subject.audit_count == first_audits, "Visible gameplay does not rerun audit")
	var result := {"debug_build":debug_build, "audit_calls":first_audits, "audit_complete":subject.audit_complete,
		"travel":subject.travel, "walker_position":[subject.walker.position.x, subject.walker.position.y, subject.walker.position.z],
		"off_tree":not subject.is_inside_tree(), "guard_set_during_audit":subject.guard_during_audit,
		"user_args":flags,"web":web,"query_opt_in":query,"reentry_requested":reenter,"bridge_calls":subject.bridge_calls}
	subject.scale_guide.free()
	subject.walker.free()
	subject.free()
	return result

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		return
	var request: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var output: String = str(request.output).replace("\\", "/").simplify_path()
	if not output.contains("/artifacts/loading-v115/startup/") or not ProjectSettings.globalize_path("res://").replace("\\", "/").begins_with(output + "/"):
		return
	var version := Engine.get_version_info()
	if version.major != 4 or version.minor != 7 or version.patch != 2:
		return
	var report := {"engine":version.string, "mode":request.mode, "classes":{}}
	if request.mode == "probe":
		for name: String in ["GDScript", "EditorExport", "EditorExportPreset", "EditorExportPlatformWeb", "GDScriptTokenizerBuffer"]:
			var methods: Array[String] = []
			if ClassDB.class_exists(name):
				for method: Dictionary in ClassDB.class_get_method_list(name, false):
					methods.append(str(method.name))
			report.classes[name] = {"exists":ClassDB.class_exists(name), "methods":methods}
		var script := GDScript.new()
		report["saver_extensions"] = ResourceSaver.get_recognized_extensions(script)
	elif request.mode == "validate":
		_check(ProjectSettings.load_resource_pack(request.pack), "Mount original dependency PCK read-only")
		_check(FileAccess.get_sha256(request.original) == request.original_sha256, "Pinned original .gdc hash")
		_check(FileAccess.get_sha256(request.patched) == request.patched_sha256, "Candidate .gdc hash")
		var original := ResourceLoader.load(request.original, "GDScript", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as GDScript
		var patched := ResourceLoader.load(request.patched, "GDScript", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as GDScript
		_check(original != null and patched != null, "Full original and patched .gdc load")
		if original == null or patched == null:
			return
		_check(original.can_instantiate() and patched.can_instantiate(), "Complete compiled scripts parse/analyze against original PCK dependencies")
		var a := _contract(original)
		var b := _contract(patched)
		report["original_contract"] = a
		report["patched_contract"] = b
		var shared := b.duplicate(true)
		var added: Array = request.added_methods
		shared.methods = shared.methods.filter(func(m: Dictionary) -> bool: return str(m.name) not in added)
		_check(a == shared, "All existing script methods/properties/signals retain their contracts")
		_check(b.methods.size() == a.methods.size() + added.size(), "Exactly the two main-owned startup helper methods added")
		report["original_and_patched_compiled_scripts_valid"] = original.can_instantiate() and patched.can_instantiate()
		report["existing_script_contracts_equal"] = a == shared
		report["added_methods"] = added
		report["method_count"] = a.methods.size()
		report["property_count"] = a.properties.size()
		report["original_release_function"] = _exercise_function(request.original_physics, false)
		report["patched_release_function"] = _exercise_function(request.patched_physics, false, request.patched_helpers)
		report["patched_debug_function"] = _exercise_function(request.patched_physics, true, request.patched_helpers)
		_check(report.original_release_function.audit_calls == 1, "Original release path runs initial audit")
		_check(report.patched_release_function.audit_calls == 0, "Patched release path skips ONLY initial audit")
		_check(report.patched_debug_function.audit_calls == 1, "Patched debug path preserves initial audit")
		var cases := {
			"release_web_default":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(), true),
			"exact_cli_opt_in":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(["--startup-audit"])),
			"cli_lookalike":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(["--startup-audit=1"])),
			"web_query_opt_in":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(), true, true),
			"native_ignores_web_query":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(), false, true),
			"architecture_independent":_exercise_function(request.patched_physics, false, request.patched_helpers, PackedStringArray(["--architecture-audit"]), true),
			"debug_reentry_guard":_exercise_function(request.patched_physics, true, request.patched_helpers, PackedStringArray(), false, false, true)}
		for name: String in cases:
			var expected := 1 if name in ["exact_cli_opt_in","web_query_opt_in","debug_reentry_guard"] else 0
			_check(cases[name].audit_calls == expected, "Actual extracted GDScript branch " + name)
			if expected == 1:
				_check(cases[name].guard_set_during_audit, "Guard pre-set before audit " + name)
		report["branch_cases"] = cases
		report["no_main_scene_instantiation"] = true
		report["actual_engine_debug_build"] = OS.is_debug_build()
		report["test_build_flag_injected_only_in_function_harness"] = true
	else:
		_check(false, "Unknown mode")
	report["failures"] = failures
	var path := output.path_join("result.json")
	if FileAccess.file_exists(path):
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("STARTUP_SIDECAR: ", "PASS" if failures == 0 else "FAIL")
	quit(0 if failures == 0 else 1)
