extends SceneTree
## Bounded headless probe of the actual --main-pack. Only NEW runtime artifacts.
## --script ABSOLUTE/test_lite_runtime_v126.gd -- --pack-file SAME_PCK --output NEW.json
## Optional --baseline ABSOLUTE/runtime/original.json compares structural invariants.
## No imports/exports/resource saves, screenshots, services, or broad source audits.

const OUTPUT_ROOT := "E:/Projects/Godot-Octopath2/artifacts/startup-v126/independent/runtime"
const EXPECTED_PACK_SHA := "771ef72d7011b8843d826a84d387dd8e31c2518ba105cd4ad2981471901165cf"
const EXPECTED_BASELINE_SHA := "b28ce18a8cc2256a36aa65e79b0c28da7dd4a69e51cc1467fa3b813021990294"
const VIEW_SIZE := Vector2i(1280, 800)
const SEEDS := [1150901, 1150902]
const STEPS_PER_PHASE := 128
const DELTA := 0.125
const REQUIRED := ["Camera3D", "WorldEnvironment", "ContinuousMeadow", "ContinuousRiver",
	"RiverSurroundingsReflection", "SolidLimestoneGeology", "IndependentCastleHill",
	"DistantVillage", "VillageRotor_0", "VillageRotor_1", "LivingWeather", "LivingWildlife",
	"OptionalScaleGuide/HumanScale_1_8m", "TrailLantern", "RoadLamp_0", "RoadLamp_1", "RoadLamp_2"]

var errors: Array[String] = []
var scene: Node3D
var weather: Node
var wildlife: Node3D
var camera: Camera3D
var output_path := ""
var baseline_path := ""
var pack_path := ""
var pack_sha := ""
var pack_binding := {}
var light_phases := {}
var light_set: Array = []

func _initialize() -> void:
	_run.call_deferred()

func _check(condition: bool, message: String) -> bool:
	if not condition:
		errors.append(message)
		push_error("LITE_RUNTIME: " + message)
	return condition

func _sha(bytes: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish().hex_encode()

func _hash(value: Variant) -> String:
	return _sha(var_to_bytes(value))

func _same_json(a: Variant, b: Variant) -> bool:
	# Godot parses every JSON number as float. A dictionary of native integer
	# counts is not Variant-equal to its parsed JSON even when values match;
	# serializing it again also changes integer formatting. Compare numeric
	# values exactly, recursively, without a transform tolerance.
	if (a is int or a is float) and (b is int or b is float):
		return float(a) == float(b)
	if a is Dictionary and b is Dictionary:
		if a.size() != b.size():
			return false
		for key: Variant in a:
			if not b.has(key) or not _same_json(a[key], b[key]):
				return false
		return true
	if a is Array and b is Array:
		if a.size() != b.size():
			return false
		for i in range(a.size()):
			if not _same_json(a[i], b[i]):
				return false
		return true
	return a == b

func _json(value: Variant) -> Variant:
	if value is Vector2 or value is Vector2i:
		return [value.x, value.y]
	if value is Vector3 or value is Vector3i:
		return [value.x, value.y, value.z]
	if value is Vector4 or value is Vector4i:
		return [value.x, value.y, value.z, value.w]
	if value is Color:
		return [value.r, value.g, value.b, value.a]
	if value is Rect2:
		return [value.position.x, value.position.y, value.size.x, value.size.y]
	if value is Transform3D:
		return [_json(value.basis.x), _json(value.basis.y), _json(value.basis.z), _json(value.origin)]
	if value is Dictionary:
		var result := {}
		for key: Variant in value:
			result[str(key)] = _json(value[key])
		return result
	if value is Array or value is PackedVector2Array or value is PackedVector3Array:
		var result: Array = []
		for item: Variant in value:
			result.append(_json(item))
		return result
	if value is StringName or value is NodePath:
		return str(value)
	return value

func _args() -> bool:
	var args := OS.get_cmdline_user_args()
	if not _check(args.size() == 4 or args.size() == 6, "Expected --pack-file SAME_PCK --output NEW.json [--baseline original.json]"):
		return false
	for i in range(0, args.size(), 2):
		if args[i] == "--output":
			output_path = args[i + 1].replace("\\", "/").simplify_path()
		elif args[i] == "--baseline":
			baseline_path = args[i + 1].replace("\\", "/").simplify_path()
		elif args[i] == "--pack-file":
			pack_path = args[i + 1].replace("\\", "/").simplify_path()
		else:
			return _check(false, "Unknown probe argument: " + args[i])
	if not _check(output_path.is_absolute_path() and output_path.to_lower().begins_with(OUTPUT_ROOT.to_lower() + "/")
		and output_path.ends_with(".json") and not FileAccess.file_exists(output_path), "Output must be NEW JSON inside runtime artifact directory"):
		return false
	# Godot consumes --main-pack before exposing OS.get_cmdline_args(). The
	# explicit pin below is bound to the mounted pack by every entry's digest.
	if not _check(pack_path.is_absolute_path() and FileAccess.file_exists(pack_path), "Use an existing absolute --pack-file matching --main-pack"):
		return false
	if baseline_path != "" and not _check(FileAccess.file_exists(baseline_path), "Baseline runtime report is missing"):
		return false
	pack_sha = FileAccess.get_sha256(pack_path)
	return _check(pack_sha == EXPECTED_PACK_SHA, "Final composed PCK SHA256 pin") and _check(
		baseline_path != "" and FileAccess.get_sha256(baseline_path) == EXPECTED_BASELINE_SHA, "Original baseline SHA256 pin")

func _bind_pack() -> bool:
	var file := FileAccess.open(pack_path, FileAccess.READ)
	if not _check(file != null and file.get_buffer(4).get_string_from_ascii() == "GDPC", "Standalone PCK header"):
		return false
	if not _check(file.get_32() == 4, "Observed PCK v4 directory layout"):
		return false
	file.seek(20)
	if not _check(file.get_32() == 2, "Unencrypted relative-base PCK"):
		return false
	var base := file.get_64()
	var directory := file.get_64()
	if not _check(base >= 112 and directory >= base and directory + 4 <= file.get_length(), "PCK directory bounds"):
		return false
	file.seek(directory)
	var count := file.get_32()
	if not _check(count > 0 and count <= 10000, "Bounded PCK resource count"):
		return false
	var matches := 0
	for i in range(count):
		var length := file.get_32()
		if not _check(length > 0 and length <= 32768 and file.get_position() + length + 36 <= file.get_length(), "PCK path record bounds"):
			return false
		var encoded := file.get_buffer(length)
		while not encoded.is_empty() and encoded[encoded.size() - 1] == 0:
			encoded.resize(encoded.size() - 1)
		var name := encoded.get_string_from_utf8()
		var offset := base + file.get_64()
		var size := file.get_64()
		var digest := file.get_buffer(16).hex_encode()
		var flags := file.get_32()
		if not _check(flags == 0 and offset >= base and offset + size <= directory and
			not name.begins_with("/") and not name.contains("..") and not name.contains("\\"), "Unflagged bounded PCK entry"):
			return false
		if _check(FileAccess.get_md5("res://" + name) == digest, "Mounted PCK entry matches pin: " + name):
			matches += 1
	file.close()
	pack_binding = {"entryCount": count, "matchedLoadedEntries": matches, "allLoadedEntryMd5Match": count == matches}
	return matches == count

func _stable_path(node: Node) -> String:
	if node == scene:
		return "."
	var parts: Array[String] = []
	var cursor := node
	while cursor != scene:
		var label := str(cursor.name)
		if label.begins_with("@"):
			label = cursor.get_class() + "#" + str(cursor.get_index())
		parts.push_front(label)
		cursor = cursor.get_parent()
	return "/".join(parts)

func _shape_record(shape: Shape3D) -> Dictionary:
	var names: Array[String] = []
	for property: Dictionary in shape.get_property_list():
		var name := str(property.name)
		if int(property.usage) & PROPERTY_USAGE_STORAGE and not name.begins_with("resource_") and name != "script":
			names.append(name)
	names.sort()
	var values := {}
	for name: String in names:
		values[name] = shape.get(name)
	var result := {"class": shape.get_class(), "storedPropertyNames": names,
		"shapeSha256": _hash([shape.get_class(), values])}
	if shape is ConcavePolygonShape3D:
		result["faceVertexCount"] = shape.get_faces().size()
		result["faceBytesSha256"] = _sha(shape.get_faces().to_byte_array())
	elif shape is ConvexPolygonShape3D:
		result["pointCount"] = shape.points.size()
	return result

func _inventory() -> Dictionary:
	var stack: Array[Node] = [scene]
	var nodes: Array = []
	var colliders: Array = []
	var lights := {}
	var structure: Array = []
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		var stable := _stable_path(node)
		var row := {"path": str(scene.get_path_to(node)), "stablePath": stable, "class": node.get_class()}
		structure.append([stable, node.get_class()])
		var script: Script = node.get_script()
		if script != null:
			row["script"] = script.resource_path
		if node is Node3D:
			row["transform"] = _json(node.transform)
			row["globalTransform"] = _json(node.global_transform)
			row["visible"] = node.visible
		if node is Light3D:
			lights[node.get_class()] = int(lights.get(node.get_class(), 0)) + 1
		if node is MeshInstance3D and node.mesh != null:
			row["surfaceCount"] = node.mesh.get_surface_count()
		if node is MultiMeshInstance3D and node.multimesh != null:
			row["instanceCount"] = node.multimesh.instance_count
			row["visibleInstanceCount"] = node.multimesh.visible_instance_count
		if node is CollisionShape3D and node.shape != null:
			var collider := {"path": row.path, "stablePath": stable, "transform": row.get("globalTransform"),
				"disabled": node.disabled, "shape": _shape_record(node.shape)}
			colliders.append(collider)
		nodes.append(row)
		for child: Node in node.get_children():
			stack.append(child)
	nodes.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.stablePath < b.stablePath)
	colliders.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.stablePath < b.stablePath)
	structure.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0])
	var collider_signature: Array = []
	for row: Dictionary in colliders:
		collider_signature.append([row.stablePath, row.shape.shapeSha256, row.transform, row.disabled])
	return {"nodes": nodes, "nodeCount": nodes.size(), "structureSha256": _hash(structure),
		"lightCounts": lights, "colliders": colliders, "colliderCount": colliders.size(),
		"colliderSetSha256": _hash(collider_signature)}

func _record_lights(phase: String) -> void:
	# Traverse all nodes, including invisible/zero-energy lights. Do not filter
	# the day-hidden stag light or confuse physics Area3D with an area light.
	var counts := {"DirectionalLight3D": 0, "OmniLight3D": 0, "SpotLight3D": 0, "AreaLight3D": 0, "RectLight3D": 0}
	var stack: Array[Node] = [scene]
	var rows: Array = []
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		if node is Light3D:
			var kind := node.get_class()
			counts[kind] = int(counts.get(kind, 0)) + 1
			rows.append({"stablePath": _stable_path(node), "class": kind, "visible": node.visible,
				"energy": node.light_energy, "shadowEnabled": node.shadow_enabled})
		for child: Node in node.get_children():
			stack.append(child)
	rows.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.stablePath < b.stablePath)
	var identity: Array = []
	for row: Dictionary in rows:
		identity.append([row.stablePath, row["class"]])
	if light_set.is_empty():
		light_set = identity
	_check(identity == light_set, "Light node identities unchanged in phase " + phase)
	_check(counts == {"DirectionalLight3D": 4, "OmniLight3D": 9, "SpotLight3D": 0, "AreaLight3D": 0, "RectLight3D": 0},
		"Complete light census 4 directional / 9 omni / zero spot-area in phase " + phase)
	light_phases[phase] = {"counts": counts, "lights": rows, "lightSetSha256": _hash(identity),
		"clock": weather.get("animation_clock"), "nightBlend": weather.get("night_blend"), "includesHidden": true}

func _texture_identity(texture: Texture2D) -> Dictionary:
	var result := {"resource": texture.resource_path, "logicalSize": [texture.get_width(), texture.get_height()]}
	var config := ConfigFile.new()
	if _check(config.load(texture.resource_path + ".import") == OK, "Water texture import map is readable in PCK"):
		var imported := str(config.get_value("remap", "path", ""))
		result["importedResource"] = imported
		result["ctexSha256"] = FileAccess.get_sha256(imported)
	return result

func _water() -> Dictionary:
	var river: MeshInstance3D = scene.get_node("ContinuousRiver")
	var material: ShaderMaterial = river.material_override
	var texture: Texture2D = material.get_shader_parameter("ripple_texture")
	_check(material.shader.resource_path == "res://shaders/meadow_water.gdshader", "Expected water shader attached")
	_check(texture != null and texture.resource_path == "res://assets/materials/river-ripples-v37.png", "Expected ripple texture attached")
	return {"path": _stable_path(river), "shader": material.shader.resource_path,
		"shaderCodeSha256": _sha(material.shader.code.to_utf8_buffer()), "texture": _texture_identity(texture),
		"renderPriority": material.render_priority, "layers": river.layers,
		"shallowOpacity": material.get_shader_parameter("shallow_opacity"),
		"deepOpacity": material.get_shader_parameter("deep_opacity"),
		"surfaceArraysSha256": _hash(river.mesh.surface_get_arrays(0)),
		"reflectionProbeExists": scene.has_node("RiverSurroundingsReflection")}

func _appearance() -> Dictionary:
	var rows: Array = []
	for animal: Dictionary in wildlife.get("animals"):
		rows.append({"species": str(animal.node.name), "visible": animal.node.visible, "presence": animal.presence})
	var environment: Environment = scene.get_node("WorldEnvironment").environment
	var key: DirectionalLight3D = scene.get_node("KeyLight")
	var light: OmniLight3D = wildlife.get("night_light")
	var night_sources: Array = []
	for source: Node in get_nodes_in_group("meadow_night_sources"):
		night_sources.append({"path": _stable_path(source), "energy": source.light_energy})
	return {"nightBlend": weather.get("night_blend"), "clock": weather.get("animation_clock"),
		"motionEnabled": weather.get("motion_enabled"), "animals": rows, "nightSources": night_sources,
		"keyEnergy": key.light_energy, "keyTransform": _json(key.transform), "keyColor": _json(key.light_color),
		"ambientEnergy": environment.ambient_light_energy, "exposure": environment.tonemap_exposure,
		"stagLightEnergy": light.light_energy, "stagHaloVisible": wildlife.get("night_halo").visible,
		"stagAuraVisible": wildlife.get("night_aura").visible,
		"skyShader": environment.sky.sky_material.shader.resource_path}

func _set_day(night: bool) -> void:
	weather.call("set_motion", false)
	if bool(weather.get("night_target")) != night:
		weather.call("toggle_time")
		weather.call("advance_weather", 3.2)
	wildlife.call("advance", float(weather.get("animation_clock")))
	_check(is_equal_approx(float(weather.get("night_blend")), 1.0 if night else 0.0), "Day/night transition reaches endpoint")

func _reset(seed_value: int, initial: Array) -> void:
	weather.set("night_target", false)
	weather.set("transitioning", false)
	weather.set("animation_clock", 0.0)
	weather.call("_apply_lighting", 0.0)
	weather.call("set_motion", false)
	weather.call("advance_weather", 0.0)
	RenderingServer.global_shader_parameter_set("meadow_clock", 0.0)
	var states: Array[Dictionary] = []
	for saved: Dictionary in initial:
		var state: Dictionary = saved.duplicate()
		state.node.position = wildlife.call("ground_point", state.point)
		state.node.material_override.set_shader_parameter("sprite_flip", false)
		wildlife.call("_apply_animal_frame", state)
		states.append(state)
	wildlife.set("animals", states)
	wildlife.set("last_clock", 0.0)
	wildlife.set("distance_travelled", 0.0)
	wildlife.set("dragon_bank", 0.0)
	var rng: RandomNumberGenerator = wildlife.get("rng")
	rng.seed = seed_value
	wildlife.call("reset_flight", seed_value + 100)
	wildlife.call("_update_dragon", 0.0, 0.0)
	wildlife.call("advance", 0.0)
	scene.get_node("VillageRotor_0").rotation.z = -0.65
	scene.get_node("VillageRotor_1").rotation.z = 0.22

func _sample_route(seed_value: int, initial: Array) -> Dictionary:
	_reset(seed_value, initial)
	var frame_sets: Array = [{}, {}, {}, {}]
	var paths: Array = [[], [], [], []]
	var dragon_samples: Array = []
	var dragon_frames := {}
	var max_step := 0.0
	var invalid_points := 0
	var last_dragon: Vector3 = wildlife.get("dragon").position
	for night: bool in [false, true]:
		_set_day(night)
		weather.call("set_motion", true)
		for step in range(STEPS_PER_PHASE):
			weather.call("advance_weather", DELTA)
			wildlife.call("advance", float(weather.get("animation_clock")))
			for i in range(4):
				var animal: Dictionary = wildlife.get("animals")[i]
				_check(animal.frame >= 0 and animal.frame < 8, "Animal frame index in range")
				frame_sets[i][animal.frame] = true
				if step % 8 == 0:
					paths[i].append(_json(animal.point))
					if not bool(wildlife.call("safe_point", animal.point)):
						invalid_points += 1
			var position: Vector3 = wildlife.get("dragon").position
			max_step = maxf(max_step, last_dragon.distance_to(position))
			last_dragon = position
			var frame: int = wildlife.get("dragon_frame")
			_check(frame >= 0 and frame < 32 and position.is_finite(), "Dragon pose and position valid")
			dragon_frames[frame] = true
			if step % 8 == 0:
				dragon_samples.append(_json(position))
		_record_lights("route_" + str(seed_value) + ("_night" if night else "_day"))
	weather.call("set_motion", false)
	var old_clock: float = weather.get("animation_clock")
	var old_transform: Transform3D = wildlife.get("dragon").transform
	weather.call("advance_weather", 1.0)
	wildlife.call("advance", float(weather.get("animation_clock")))
	var pause_exact: bool = old_clock == float(weather.get("animation_clock")) and old_transform == wildlife.get("dragon").transform
	_check(pause_exact, "Paused clock and dragon transform stay exact")
	_check(invalid_points == 0, "Bounded sampled animal points stay on safe routes")
	_check(max_step < 4.5, "Bounded dragon spline samples do not teleport")
	var animals: Array = []
	for i in range(4):
		var state: Dictionary = wildlife.get("animals")[i]
		var seen: Array = frame_sets[i].keys()
		seen.sort()
		_check(state.frames.size() == 8 and float(state.travel) > 0.1, "Each eight-frame species moves in its active phase")
		animals.append({"species": str(state.node.name), "configuredFrames": state.frames.size(),
			"observedFrames": seen, "safeHabitatPoints": state.points.size(), "turns": state.turns,
			"travelMetres": state.travel, "routeSamples": paths[i], "routeSha256": _hash(paths[i])})
	return {"seed": seed_value, "stepsPerPhase": STEPS_PER_PHASE, "stepSeconds": DELTA,
		"simulatedSeconds": float(weather.get("animation_clock")), "animals": animals,
		"dragon": {"configuredFrames": wildlife.get("dragon_frames").size(), "observedFrameCount": dragon_frames.size(),
			"routeSamples": dragon_samples, "routeSha256": _hash(dragon_samples),
			"splineLegs": wildlife.get("flight_legs"), "maxStepMetres": max_step},
		"invalidSampledPoints": invalid_points, "pauseExact": pause_exact}

func _compare(report: Dictionary) -> Dictionary:
	if baseline_path == "":
		return {"status": "BASELINE_CAPTURE"}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(baseline_path))
	if not _check(parsed is Dictionary and parsed.get("status") == "PASS", "Baseline is a successful runtime report"):
		return {"status": "FAIL"}
	var baseline: Dictionary = parsed
	# Apply the same JSON readback to both operands. Godot's decimal parser can
	# shift a native double by one ULP; comparing parsed baseline to unparsed
	# native values would produce false failures despite identical saved JSON.
	var candidate: Dictionary = JSON.parse_string(JSON.stringify(report, "", true, true))
	var checks := {}
	for key: String in ["structureSha256", "nodeCount", "lightCounts", "colliderSetSha256", "colliderCount"]:
		checks[key] = _same_json(baseline.inventory.get(key), candidate.inventory.get(key))
		_check(checks[key], "Baseline runtime invariant: " + key)
	# Engine-assigned @Node@ instance IDs are not persistent object names. All
	# other captured fields (including stable paths, scripts, local/global
	# transforms, visibility and instance/surface counts) must match exactly.
	var before_nodes: Array = baseline.inventory.nodes.duplicate(true)
	var after_nodes: Array = candidate.inventory.nodes.duplicate(true)
	for rows: Array in [before_nodes, after_nodes]:
		for row: Dictionary in rows:
			row.erase("path")
	checks["objectsTransformsScriptsCounts"] = _same_json(before_nodes, after_nodes)
	_check(checks.objectsTransformsScriptsCounts, "Baseline runtime invariant: objects/transforms/scripts/counts")
	for key: String in ["camera", "water", "walkingBoss", "weather", "routes"]:
		checks[key] = _same_json(baseline.get(key), candidate.get(key))
		_check(checks[key], "Baseline runtime invariant: " + key)
	# Render-mesh UVs, imported RGB/physical dimensions and project settings are
	# intentionally NOT hashed as runtime invariants. Their separate contracts
	# allow lite changes, including safely rebound AO metadata for quantized UVs.
	return {"status": "PASS" if not checks.values().has(false) else "FAIL", "baseline": baseline_path,
		"baselineSha256": FileAccess.get_sha256(baseline_path), "checks": checks,
		"renderGeometryUvHashesCompared": false}

func _run() -> void:
	if not _args():
		quit(2)
		return
	if not _bind_pack():
		quit(1)
		return
	root.size = VIEW_SIZE
	root.content_scale_size = VIEW_SIZE
	var main_path := str(ProjectSettings.get_setting("application/run/main_scene"))
	var packed: PackedScene = load(main_path)
	if not _check(packed != null, "Actual PCK main scene loads"):
		quit(1)
		return
	scene = packed.instantiate() as Node3D
	# This suppresses the main scene's automatic first-physics root/terrain audit
	# before any physics tick. _ready still constructs the actual scene normally.
	scene.process_mode = Node.PROCESS_MODE_DISABLED
	var started := Time.get_ticks_msec()
	root.add_child(scene)
	for path: String in REQUIRED:
		_check(scene.has_node(NodePath(path)), "Required object exists: " + path)
	if not errors.is_empty():
		quit(1)
		return
	weather = scene.get_node("LivingWeather")
	wildlife = scene.get_node("LivingWildlife")
	camera = scene.get_node("Camera3D")
	var initial: Array = []
	for state: Dictionary in wildlife.get("animals"):
		initial.append(state.duplicate())
	_check(initial.size() == 4 and wildlife.get("dragon_frames").size() == 32, "Four species and 32-frame dragon present")
	_reset(SEEDS[0], initial)
	var inventory := _inventory()
	var day := _appearance()
	_record_lights("day")
	_set_day(true)
	var night := _appearance()
	_record_lights("night")
	_set_day(false)
	var returned_day := _appearance()
	_record_lights("returnedDay")
	_check(day.clock == night.clock and night.clock == returned_day.clock, "Day/night switches work with motion paused")
	_check(not day.animals[3].visible and night.animals[3].visible and not returned_day.animals[3].visible,
		"Nocturnal stag visibility switches day/night/day")
	_check(day.stagLightEnergy == 0.0 and night.stagLightEnergy > 0.0 and returned_day.stagLightEnergy == 0.0,
		"Nocturnal local light switches with appearance")
	_check(JSON.stringify(day, "", true, true) == JSON.stringify(returned_day, "", true, true), "Day appearance restores exactly")
	var routes: Array = []
	for seed_value: int in SEEDS:
		routes.append(_sample_route(seed_value, initial))
	_check(routes[0].dragon.routeSha256 != routes[1].dragon.routeSha256, "Different seeds produce different dragon routes")
	for i in range(4):
		_check(routes[0].animals[i].routeSha256 != routes[1].animals[i].routeSha256, "Different seeds produce different animal routes")
	var constants: Dictionary = scene.get_script().get_script_constant_map()
	var report := {"schemaVersion": 1, "status": "PASS", "pack": pack_path, "packSha256": pack_sha, "packBinding": pack_binding,
		"probeSha256": FileAccess.get_sha256(get_script().resource_path),
		"engine": Engine.get_version_info(), "mainScene": main_path, "probeViewSize": _json(VIEW_SIZE),
		"captureKind": "headless_manual_clock_no_render", "automaticPhysicsAuditsDisabled": true,
		"inventory": inventory, "camera": {"path": _stable_path(camera), "transform": _json(camera.transform),
			"globalTransform": _json(camera.global_transform), "fov": camera.fov, "near": camera.near,
			"far": camera.far, "projection": camera.projection, "keepAspect": camera.keep_aspect},
		"weather": {"path": _stable_path(weather), "day": day, "night": night, "returnedDay": returned_day},
		"water": _water(), "routes": routes, "lightPhases": light_phases, "requiredObjectPaths": REQUIRED,
		"walkingBoss": {"routePoints": _json(constants.get("WALK_POINTS")), "routeLength": scene.get("route_length"),
			"bossCenter": _json(constants.get("BOSS_CENTER")), "bossRadius": constants.get("BOSS_ARENA_RADIUS"),
			"walkerPresent": scene.get("walker") != null, "scaleGuidePresent": scene.get("scale_guide") != null},
		"renderSettings": {}, "probeWorkMs": Time.get_ticks_msec() - started,
		"limitations": ["Headless: no pixels, GPU render dimensions, visual acceptance, or Web performance measured",
			"Manual fixed clock steps; bounded route samples are not exhaustive path/collision validation",
			"Collider hashes cover actual Shape3D data; authorized render UV/AO signature changes are reviewed separately",
			"Configured 8/32 frame counts do not imply every directional pose was visited in this short sample"]}
	for setting: String in ["rendering/scaling_3d/scale", "rendering/scaling_3d/mode",
		"rendering/lights_and_shadows/directional_shadow/size", "rendering/anti_aliasing/quality/msaa_3d"]:
		report.renderSettings[setting] = ProjectSettings.get_setting(setting)
	report["comparison"] = _compare(report)
	_check(FileAccess.get_sha256(pack_path) == pack_sha, "Original/input PCK unchanged after probe")
	report["inputPackUnchanged"] = FileAccess.get_sha256(pack_path) == pack_sha
	report["errors"] = errors
	report["status"] = "PASS" if errors.is_empty() else "FAIL"
	if DirAccess.make_dir_recursive_absolute(output_path.get_base_dir()) != OK or FileAccess.file_exists(output_path):
		push_error("LITE_RUNTIME: output directory/new-file check failed")
		quit(2)
		return
	var output := FileAccess.open(output_path, FileAccess.WRITE)
	if output == null:
		push_error("LITE_RUNTIME: cannot create output JSON")
		quit(2)
		return
	output.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	output.flush()
	var write_ok := output.get_error() == OK
	output.close()
	print("LITE_RUNTIME_REPORT: " + JSON.stringify({"status": report.status, "output": output_path,
		"packSha256": pack_sha, "nodes": inventory.nodeCount, "colliders": inventory.colliderCount,
		"lightCounts": inventory.lightCounts, "errors": errors, "written": write_ok}))
	scene.free()
	quit(0 if errors.is_empty() and write_ok else 1)
