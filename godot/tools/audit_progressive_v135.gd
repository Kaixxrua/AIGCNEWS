extends "test_lite_runtime_v128.gd"
## Reuses pinned read-only inventory/water/collider encoders, not the old runner.
## Actual progressive controller calls; never emit/fake a render or ready signal.

const AUDIT_SCOPE := "E:/Projects/Godot-Octopath2/artifacts/startup-v135/independent/"
var request: Dictionary
var controller: Node
var events: Array = []
var snapshots: Array = []
var cpu: Dictionary = {}
var born_us := 0
var deferred_roots: Array = []
var texture_aliases: Dictionary = {}
var baseline_report: Dictionary
var core_ids: Dictionary = {}
var core_orders: Dictionary = {}
var completed_ids: Dictionary = {}
var stable_references: Dictionary = {}
var mesh_reference: Dictionary = {}
var observed_draw_signals := 0
var phase := "initial"
var inflight_checks: Array = []
var negative_checks: Array = []

func _since() -> float:
	return float(Time.get_ticks_usec() - born_us) / 1000.0

func _node_event(node: Node, action: String) -> void:
	if not is_instance_valid(scene) or (node != scene and not scene.is_ancestor_of(node)):
		return
	if events.size() >= 4096:
		_check(false, "Bounded node-event inventory exceeded")
		return
	var path := "." if node == scene else str(scene.get_path_to(node))
	events.append({"action": action, "path": path, "name": str(node.name), "id": node.get_instance_id(),
		"atMs": _since(), "phase": phase})
	if action == "added" and path in deferred_roots:
		var same_name := 0
		for sibling: Node in node.get_parent().get_children():
			if sibling.name == node.name:
				same_name += 1
		_check(same_name == 1, "No duplicate live root during addition: " + path)

func _draw_observed() -> void:
	# A headless/dummy signal is logged, never accepted as rendered pixels.
	observed_draw_signals += 1

func _identity_list(values: Array) -> Array:
	var result: Array = []
	for value: Variant in values:
		result.append(value.get_instance_id() if is_instance_valid(value) else -1)
	return result

func _references() -> Dictionary:
	var materials: Array = weather.get("architecture_materials")
	var pools: Array = weather.get("source_pools")
	var result := {"weather": weather.get_instance_id(), "wildlife": wildlife.get_instance_id(),
		"groundMaterial": scene.get("ground_material").get_instance_id(),
		"focusMaterial": scene.get("focus_material").get_instance_id(),
		"probe": weather.get("probe").get_instance_id(),
		"architectureMaterials": _identity_list(materials), "sourcePools": _identity_list(pools)}
	for label: String in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		var node: MeshInstance3D = scene.get_node(NodePath(label))
		_check(node.material_override in materials, "Weather retains actual live architecture material " + label)
		_check(node.layers & 32 != 0, "Settlement light layer retained " + label)
	return result

func _water() -> Dictionary:
	var river: MeshInstance3D = scene.get_node("ContinuousRiver")
	var material: ShaderMaterial = river.material_override
	var texture: Texture2D = material.get_shader_parameter("ripple_texture")
	var canonical := str(texture_aliases.get(texture.resource_path, texture.resource_path))
	_check(canonical == "res://assets/materials/river-ripples-v37.png", "Only original or approved alias water texture")
	var imported := texture.resource_path
	if not imported.ends_with(".ctex"):
		var config := ConfigFile.new()
		_check(config.load(texture.resource_path + ".import") == OK, "Actual water import map readable")
		imported = str(config.get_value("remap", "path", ""))
	return {"path": _stable_path(river), "shader": material.shader.resource_path,
		"shaderCodeSha256": _sha(material.shader.code.to_utf8_buffer()),
		"texture": {"resource": canonical, "logicalSize": [texture.get_width(), texture.get_height()],
			"importedResource": baseline_report.water.texture.importedResource, "ctexSha256": FileAccess.get_sha256(imported)},
		"renderPriority": material.render_priority, "layers": river.layers,
		"shallowOpacity": material.get_shader_parameter("shallow_opacity"),
		"deepOpacity": material.get_shader_parameter("deep_opacity"),
		"surfaceArraysSha256": _hash(river.mesh.surface_get_arrays(0)),
		"reflectionProbeExists": scene.has_node("RiverSurroundingsReflection")}

func _state() -> Dictionary:
	var result := {}
	for key: String in ["night_blend", "night_target", "motion_enabled", "animation_clock", "transition_elapsed",
			"transition_start", "transitioning", "reduced_motion"]:
		result[key] = weather.get(key)
	result["contactShadowsSha256"] = _hash(scene.ground_material.get_shader_parameter("contact_shadows"))
	result["focusEnabled"] = scene.get("focus_enabled")
	result["focusDepth"] = scene.focus_material.get_shader_parameter("show_depth")
	result["focusExposure"] = scene.focus_material.get_shader_parameter("scene_exposure")
	return result

func _stable_value(value: Variant) -> Variant:
	if value is Texture2D:
		return ["Texture2D", texture_aliases.get(value.resource_path, value.resource_path), value.get_width(), value.get_height()]
	if value is Shader:
		return ["Shader", value.resource_path, _sha(value.code.to_utf8_buffer())]
	if value is Resource:
		return [value.get_class(), value.resource_path]
	if value is Dictionary:
		var names: Array = value.keys()
		names.sort()
		var rows: Array = []
		for key: Variant in names:
			rows.append([str(key), _stable_value(value[key])])
		return rows
	if value is Array:
		var rows: Array = []
		for item: Variant in value:
			rows.append(_stable_value(item))
		return rows
	if typeof(value) >= TYPE_PACKED_BYTE_ARRAY and typeof(value) < TYPE_MAX:
		return [type_string(typeof(value)), value.size(), _hash(value)]
	return _json(value)

func _material(material: Material) -> Variant:
	if material == null:
		return null
	if material is ShaderMaterial:
		var values := {}
		for item: Dictionary in material.shader.get_shader_uniform_list():
			values[str(item.name)] = _stable_value(material.get_shader_parameter(item.name))
		return {"class": "ShaderMaterial", "shader": _stable_value(material.shader),
			"priority": material.render_priority, "parameters": _stable_value(values)}
	var stored := {}
	for property: Dictionary in material.get_property_list():
		var key := str(property.name)
		if property.usage & PROPERTY_USAGE_STORAGE and not key.begins_with("resource_") and key != "script":
			stored[key] = _stable_value(material.get(key))
	return [material.get_class(), _stable_value(stored)]

func _geometry(node: Node, with_material: bool = true) -> Array:
	var rows: Array = []
	var stack: Array[Node] = [node]
	while not stack.is_empty():
		var child: Node = stack.pop_back()
		var row := {"path": str(node.get_path_to(child)), "class": child.get_class()}
		if child is Node3D:
			row["transform"] = _json(child.transform)
			row["visible"] = child.visible
		if child is GeometryInstance3D:
			row["layers"] = child.layers
			row["castShadow"] = child.cast_shadow
			if with_material:
				row["override"] = _material(child.material_override)
				row["overlay"] = _material(child.material_overlay)
		if child is MeshInstance3D and child.mesh != null:
			row["customAabb"] = _stable_value(child.mesh.custom_aabb)
			var surfaces: Array = []
			for index in range(child.mesh.get_surface_count()):
				var surface := {"primitive": child.mesh.surface_get_primitive_type(index),
					"arraysSha256": _hash(child.mesh.surface_get_arrays(index))}
				if child.mesh is ArrayMesh:
					var raw: Dictionary = child.mesh.get("_surfaces")[index].duplicate()
					raw.erase("material")
					surface["rawStorageSha256"] = _hash(_stable_value(raw))
				if with_material:
					surface["material"] = _material(child.mesh.surface_get_material(index))
					surface["override"] = _material(child.get_surface_override_material(index))
				surfaces.append(surface)
			row["surfaces"] = surfaces
		var metadata := {}
		for key: StringName in child.get_meta_list():
			if key not in [&"build_ms", &"progressive_placeholder"]:
				metadata[str(key)] = _stable_value(child.get_meta(key))
		row["metadata"] = _stable_value(metadata)
		rows.append(row)
		for sub: Node in child.get_children():
			stack.append(sub)
	rows.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.path < b.path)
	return rows

func _reference_geometry() -> void:
	for entry: Dictionary in request.expected.referenceScenes:
		_check(FileAccess.get_sha256(entry.file) == entry.sha256, "Exact reference scene " + str(entry.resource))
		var packed := ResourceLoader.load(entry.file, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		if not _check(packed != null, "Reference scene readable"):
			continue
		var container := packed.instantiate()
		var candidates: Array[Node] = []
		if entry.resource.ends_with("far-sward.scn"):
			candidates.append(container)
		else:
			for child: Node in container.get_children():
				candidates.append(child)
		for child: Node in candidates:
			var path := str(child.name)
			if entry.resource.ends_with("crown-edge-controller.scn"):
				path = "MeadowEdgeGrowth/" + path
			mesh_reference[path] = _geometry(child, path != "ContinuousMeadow")
		container.free()

func _check_geometry(paths: Array) -> void:
	for path: String in paths:
		if not _check(mesh_reference.has(path), "Reference exists for " + path):
			continue
		var node := scene.get_node_or_null(NodePath(path))
		if _check(node != null, "Geometry node exists " + path):
			_check(_same_json(_geometry(node, path != "ContinuousMeadow"), mesh_reference[path]),
				"Exact accepted geometry/material/metadata " + path)

func _record_snapshot(label: String) -> Dictionary:
	var inventory := _inventory()
	var water := _water()
	var expected_water: Dictionary = baseline_report.water.duplicate(true)
	if int(controller.get("applied_count")) < request.detailPacks.size():
		expected_water.texture.ctexSha256 = request.expected.coreWaterCtexSha256
	_check(_same_json(water, expected_water), "Water exact except authorized pre-final mip suffix in " + label)
	_check(inventory.colliderSetSha256 == baseline_report.inventory.colliderSetSha256, "All original colliders exact in " + label)
	_check(_references() == stable_references, "Weather/material/light object references retained in " + label)
	_record_lights(label)
	var snapshot := {"label": label, "atMs": _since(), "inventory": inventory, "water": water,
		"weather": _state(), "controller": {"applied": controller.get("applied_count"),
			"busy": controller.get("busy"), "completed": controller.get("completed"),
			"replacementCount": controller.get("replacement_count")}}
	snapshots.append(snapshot)
	return snapshot

func _exercise_phase(index: int) -> void:
	# Explicit test-only clock stepping; production scripts remain unchanged.
	_set_day(false)
	if index % 3 == 1:
		weather.call("toggle_time")
		weather.call("advance_weather", 1.6)
	elif index % 3 == 2:
		_set_day(true)
	wildlife.call("advance", float(weather.get("animation_clock")))
	await process_frame

func _inflight_probe(index: int, path: String) -> void:
	if not _check(bool(controller.get("busy")), "In-flight probe actually overlaps a yielding commit"):
		return
	var before := {"applied": controller.get("applied_count"), "replacements": controller.get("replacement_count"),
		"events": events.size(), "revision": weather.get("reflection_revision")}
	for attempt: int in [index, -1, index + 1]:
		await controller.call(request.controllerMethod, attempt, path)
		_check(bool(controller.get("busy")), "In-flight duplicate/invalid index cannot clear busy")
	var after := {"applied": controller.get("applied_count"), "replacements": controller.get("replacement_count"),
		"events": events.size(), "revision": weather.get("reflection_revision")}
	_check(before == after, "In-flight requests cannot commit or advance state")
	inflight_checks.append({"index": index, "before": before, "after": after, "unchanged": before == after})

func _negative_before_first_group() -> void:
	var first: Dictionary = request.detailPacks[0]
	var original_events := events.size()
	for attempt: Dictionary in [{"index": -1, "path": first.file, "case": "invalid-index"},
			{"index": 1, "path": first.file, "case": "out-of-order"},
			{"index": 0, "path": request.corePack.file, "case": "wrong-sha256"}]:
		await controller.call(request.controllerMethod, int(attempt.index), str(attempt.path))
		var intact: bool = not controller.get("busy") and int(controller.get("applied_count")) == 0 \
			and int(controller.get("replacement_count")) == 0 and events.size() == original_events
		_check(intact and not str(controller.get("last_error")).is_empty(), "Rejected input is inert: " + str(attempt["case"]))
		negative_checks.append({"case": attempt["case"], "inert": intact, "message": controller.get("last_error"),
			"expectedInjectedWarning": true})

func _apply_group(group: Dictionary) -> void:
	var index := int(group.index)
	phase = "chunk-%d" % index
	await _exercise_phase(index)
	var before := _state()
	var references_before := _references()
	var reflection_before := int(weather.get("reflection_revision"))
	var event_start := events.size()
	var started := Time.get_ticks_usec()
	_inflight_probe.call_deferred(index, str(group.file))
	await controller.call(request.controllerMethod, index, str(group.file))
	var elapsed := float(Time.get_ticks_usec() - started) / 1000.0
	cpu[phase] = {"applyAwaitMs": elapsed, "includesFrameWaits": true}
	_check(int(controller.get("applied_count")) == index + 1, "Actual group advanced once")
	_check(not bool(controller.get("busy")) and str(controller.get("last_error")).is_empty(), "Group finished without error")
	_check(before == _state() and references_before == _references(), "Upgrade preserves live weather/clock/material state")
	var expected_refresh := 1 if index + 1 == request.detailPacks.size() else 0
	_check(int(weather.get("reflection_revision")) == reflection_before + expected_refresh, "Single final reflection refresh only")
	for path: String in group.roots:
		var node := scene.get_node_or_null(NodePath(path))
		if not _check(node != null, "Restored root exists " + path):
			continue
		_check(node.get_instance_id() != core_ids[path], "Root really replaced " + path)
		_check(node.get_index() == core_orders[path], "Original sibling index retained " + path)
		_check(not node.get_meta("progressive_placeholder", false), "No placeholder remains " + path)
		completed_ids[path] = node.get_instance_id()
		var counts := {"added": 0, "removed": 0}
		for event: Dictionary in events.slice(event_start):
			if event.path == path:
				counts[event.action] += 1
		_check(counts == {"added": 1, "removed": 1}, "Exactly one actual remove/add event " + path)
	_check_geometry(group.roots)
	_record_snapshot(phase)
	# Public idempotence must not mutate a second time or refresh the probe again.
	var before_events := events.size()
	var count_before := int(controller.get("replacement_count"))
	var revision_before := int(weather.get("reflection_revision"))
	await controller.call(request.controllerMethod, index, str(group.file))
	_check(events.size() == before_events and int(controller.get("replacement_count")) == count_before,
		"Duplicate completed group is structurally inert")
	_check(int(weather.get("reflection_revision")) == revision_before, "Duplicate does not recapture reflection")
	for path: String in group.roots:
		_check(scene.get_node(NodePath(path)).get_instance_id() == completed_ids[path], "Duplicate retains same final instance")

func _run() -> void:
	born_us = Time.get_ticks_usec()
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		push_error("One absolute request JSON required")
		quit(2)
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	output_path = str(request.out).replace("\\", "/")
	if not output_path.simplify_path().begins_with(AUDIT_SCOPE) or FileAccess.file_exists(output_path):
		push_error("Fresh independent output only")
		quit(2)
		return
	baseline_report = JSON.parse_string(FileAccess.get_file_as_string(request.expected.report.file))
	deferred_roots = request.deferredRoots
	for group: Dictionary in request.detailPacks:
		for texture: Dictionary in group.get("textures", []):
			texture_aliases[str(texture.resource)] = str(texture.source)
	node_added.connect(func(node: Node): _node_event(node, "added"))
	node_removed.connect(func(node: Node): _node_event(node, "removed"))
	RenderingServer.frame_post_draw.connect(_draw_observed)
	var started := Time.get_ticks_usec()
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	cpu["loadMainMs"] = float(Time.get_ticks_usec() - started) / 1000.0
	if not _check(packed != null, "Actual core main scene loads"):
		_finish()
		return
	started = Time.get_ticks_usec()
	scene = packed.instantiate() as Node3D
	cpu["instantiateMs"] = float(Time.get_ticks_usec() - started) / 1000.0
	if not _check(scene.get_script() != null and scene.has_method("_build_landscape"), "Actual main script parsed and attached"):
		_finish()
		return
	# Debug-only audit work is not gameplay or a render-readiness signal.
	scene.set("audit_complete", true)
	started = Time.get_ticks_usec()
	root.add_child(scene)
	current_scene = scene
	cpu["coreReadyCallMs"] = float(Time.get_ticks_usec() - started) / 1000.0
	weather = scene.get_node("LivingWeather")
	wildlife = scene.get_node("LivingWildlife")
	camera = scene.get_node("Camera3D")
	for node: Node in scene.find_children("*", "", true, false):
		var script: Script = node.get_script()
		if script != null and script.resource_path == request.controllerScript:
			_check(controller == null, "Exactly one progressive controller")
			controller = node
	if not _check(controller != null and controller.has_method(request.controllerMethod), "Observed native controller API exists"):
		_finish()
		return
	_check(not scene.get_node("RiverSurroundingsReflection").visible, "Probe initially hidden, not deleted")
	_check(not camera.get_node("DepthAwareFocus").visible, "Focus initially hidden with live material")
	_check(bool(weather.get("motion_enabled")) and weather.is_processing() and wildlife.is_processing(), "Core animations start active")
	for path: String in REQUIRED:
		_check(scene.has_node(NodePath(path)), "Meaningful core object present " + path)
	for path: String in deferred_roots:
		var node := scene.get_node_or_null(NodePath(path))
		if _check(node != null, "Named core placeholder present " + path):
			_check(node.get_meta("progressive_placeholder", false) and node is MeshInstance3D and (node.mesh == null or node.mesh.get_surface_count() == 0),
				"Actual empty placeholder mesh " + path)
			core_ids[path] = node.get_instance_id()
			core_orders[path] = node.get_index()
	stable_references = _references()
	# Deterministic state tests: freeze autonomous clock only in this probe.
	weather.call("set_motion", false)
	weather.set_process(false)
	wildlife.set_process(false)
	_record_snapshot("core")
	_reference_geometry()
	_check_geometry(["ContinuousMeadow", "SolidLimestoneGeology", "EmbeddedRiverbankStrata"])
	await _negative_before_first_group()
	for group: Dictionary in request.detailPacks:
		await _apply_group(group)
	phase = "final"
	_check(bool(controller.get("completed")), "Controller completes only after all groups")
	_check(int(controller.get("replacement_count")) == deferred_roots.size(), "Actual replacement total equals independent root mapping")
	_check(scene.get_node("RiverSurroundingsReflection").visible and camera.get_node("DepthAwareFocus").visible,
		"Final probe and original focus restored")
	_check_geometry(deferred_roots)
	for night: bool in [false, true, false]:
		_set_day(night)
		await process_frame
		_record_snapshot("final-night" if night else "final-day")
	var final_inventory := _inventory()
	var previous_paths := {}
	for row: Dictionary in baseline_report.inventory.nodes:
		previous_paths[str(row.stablePath)] = row["class"]
	for row: Dictionary in final_inventory.nodes:
		if row.stablePath == _stable_path(controller):
			continue
		var canonical_path := str(row.stablePath)
		for alias: String in request.get("baselinePathAliases", {}):
			if canonical_path == alias or canonical_path.begins_with(alias + "/"):
				canonical_path = str(request.baselinePathAliases[alias]) + canonical_path.substr(alias.length())
		_check(previous_paths.get(canonical_path) == row["class"], "Final original node path/class " + str(row.stablePath))
		previous_paths.erase(canonical_path)
	_check(previous_paths.is_empty(), "No original nodes lost")
	_finish()

func _finish() -> void:
	var report := {"schema": "progressive-independent-native-v1",
		"status": "PASS_CPU_STRUCTURAL_ONLY" if errors.is_empty() else "FAIL",
		"captureKind": "headless_no_render", "errors": errors, "cpu": cpu,
		"events": events, "snapshots": snapshots, "deferredRoots": deferred_roots,
		"coreRootIds": core_ids, "finalRootIds": completed_ids, "lightPhases": light_phases,
		"inflightChecks": inflight_checks, "negativeChecks": negative_checks,
		"observedDummyDrawSignals": observed_draw_signals,
		"limitations": ["No browser, network, GL context or rendered-pixel evidence.",
			"Automatic debug physics audit and autonomous weather/wildlife stepping disabled only in probe.",
			"Apply await timings include explicit engine-frame waits and are not Web shader/GPU timings.",
			"Main owns actual first painted core and complete day/night/water visual acceptance."]}
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	file.close()
	if is_instance_valid(scene):
		scene.free()
	quit(0 if errors.is_empty() else 1)
