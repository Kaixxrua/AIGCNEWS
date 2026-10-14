extends "audit_lite_runtime.gd"
## Independent actual-core observer. No capture, overlay, rebuild or ready signal.
## Run only after candidate approval, in TWO separate fresh native processes.
## Reuses only the existing hash/path/collider/route encoders; overrides its runner.

const STATIC_SCOPE := "E:/Projects/Godot-Octopath2/artifacts/startup-v135/independent/static-core/"
const CACHE_DIAGNOSTICS := ["_meadow_static_geometry_cache_v135", "_meadow_root_conform_cache_v135"]
const MAIN_FIELDS := ["camera", "ground_material", "focus_material", "focus_enabled", "shadow_ellipses",
	"asset_paths", "occupied_art_regions", "scale_guide", "walker", "travel", "route_length"]
const WEATHER_FIELDS := ["night_blend", "night_target", "motion_enabled", "reduced_motion", "animation_clock",
	"transition_elapsed", "transition_start", "transitioning", "reflection_revision", "environment",
	"key_light", "probe", "probe_origin", "lantern_light", "moon_bounce", "day_bounce", "settlement_bounce",
	"architecture_materials", "source_pools"]
const SYSTEMS := ["LivingWeather", "LivingWildlife", "MountainAtmosphere", "GroundAtmosphere"]

var request: Dictionary
var controller: Node
var timing: Dictionary = {}
var observations: Array = []
var resources: Dictionary = {}
var resource_ids: Dictionary = {}
var rid_aliases: Dictionary = {}
var texture_lifetimes: Dictionary = {}
var graph_nodes: Array = []
var pinned_live: Dictionary = {}
var startup_observed: Dictionary = {}
var chunk_steps: Array = []
var route_rows: Array = []
var process_modes: Dictionary = {}
var ready_events := 0
var functional_rows: Array = []
var entry_observed: Dictionary = {}
var thin_edge_id := 0

func _primitive(mesh: Mesh, index: int) -> int:
	# Mesh's C++ surface_get_primitive_type is only bound on ArrayMesh, not Quad/ImmediateMesh.
	return int(RenderingServer.mesh_get_surface(mesh.get_rid(), index).primitive)

func _stable_atom(value: Variant) -> Variant:
	# Keep Godot numeric types and every bit, not approximate transform JSON.
	return {"type": type_string(typeof(value)), "value": var_to_str(value), "sha256": _hash(value)}

func _value(value: Variant, anchor: String) -> Variant:
	if value == null or value is bool or value is int or value is float or value is String or value is StringName:
		return str(value) if value is StringName else value
	if value is Node:
		if not _check(value == scene or scene.is_ancestor_of(value), "Live reference stays inside scene: " + anchor):
			return {"invalidExternalNode": value.get_class()}
		return {"node": _stable_path(value)}
	if value is Resource or value is TriangleMesh:
		var id: int = value.get_instance_id()
		if not resource_ids.has(id):
			resource_ids[id] = anchor
			resources[anchor] = {} # Reserve BEFORE descending (shared/cyclic resources).
			resources[anchor] = _resource(value, anchor)
		return {"resource": resource_ids[id]}
	if value is Dictionary:
		var rows: Array = []
		var keys: Array = value.keys()
		keys.sort_custom(func(a: Variant, b: Variant) -> bool: return var_to_str(a) < var_to_str(b))
		for key: Variant in keys:
			rows.append([_stable_atom(key), _value(value[key], anchor + "/" + var_to_str(key))])
		return {"dictionary": rows}
	if value is Array:
		var rows: Array = []
		for i in range(value.size()):
			rows.append(_value(value[i], anchor + "/" + str(i)))
		return {"array": rows, "typed": value.get_typed_builtin(), "class": str(value.get_typed_class_name())}
	if typeof(value) >= TYPE_PACKED_BYTE_ARRAY and typeof(value) < TYPE_MAX:
		return {"type": type_string(typeof(value)), "count": value.size(), "sha256": _hash(value)}
	if value is Object:
		_check(false, "Unencoded object; do not silently accept: " + anchor + " " + value.get_class())
		return {"unsupported": value.get_class()}
	return _stable_atom(value)

func _stored(object: Object, anchor: String, omissions: Array = []) -> Dictionary:
	var result := {}
	var names: Array[String] = []
	for item: Dictionary in object.get_property_list():
		var key := str(item.name)
		if item.usage & PROPERTY_USAGE_STORAGE and key not in omissions and not key.begins_with("metadata/"):
			if not key.begins_with("resource_") and key != "script/source":
				names.append(key)
	names.sort()
	for key: String in names:
		result[key] = _value(object.get(key), anchor + "/" + key)
	return result

func _resource(value: Variant, anchor: String) -> Dictionary:
	var row := {"class": value.get_class()}
	if value is Shader or value is Texture2D:
		var canonical: Resource = ResourceLoader.get_cached_ref(value.resource_path)
		_check(canonical == value, "Canonical loaded resource OBJECT, not just code/data hash: " + anchor)
		var rid: RID = value.get_rid()
		row["ridObservable"] = rid.is_valid()
		if rid.is_valid():
			if not rid_aliases.has(rid):
				rid_aliases[rid] = anchor
			row["ridAlias"] = rid_aliases[rid]
			_check(canonical != null and canonical.get_rid() == rid, "Canonical RID identity: " + anchor)
	if value is Script:
		# Bytecode is pinned by the pack preflight, including the ONE allowed main change.
		row["path"] = value.resource_path
		return row
	if value is Shader:
		row["path"] = value.resource_path
		row["codeSha256"] = _sha(value.code.to_utf8_buffer())
		return row
	if value is CompressedTexture2D:
		if not texture_lifetimes.has(value.resource_path):
			texture_lifetimes[value.resource_path] = [value.get_instance_id(), value.get_rid()]
		_check(texture_lifetimes[value.resource_path] == [value.get_instance_id(), value.get_rid()], "Texture upgrade retains original object AND RID: " + value.resource_path)
		var imported: String = value.get_load_path()
		row["path"] = value.resource_path
		row["loadPath"] = imported
		row["logicalSize"] = [value.get_width(), value.get_height()]
		row["ctexSha256"] = FileAccess.get_sha256(imported)
		var file := FileAccess.open(imported, FileAccess.READ)
		if _check(file != null and file.get_buffer(4).get_string_from_ascii() == "GST2", "Live CTEX including exact alpha/mips: " + anchor):
			file.seek(40) # u32 inner encoding at 36, then physical u16 width/height.
			row["physicalSize"] = [file.get_16(), file.get_16()]
			file.close()
		return row
	if value is TriangleMesh:
		row["faces"] = _value(value.get_faces(), anchor + "/faces")
		return row
	if value is Shape3D:
		row["shape"] = _shape_record(value)
		return row
	row["stored"] = _stored(value, anchor)
	var metadata := {}
	for key: StringName in value.get_meta_list():
		metadata[str(key)] = value.get_meta(key)
	row["metadata"] = _value(metadata, anchor + "/metadata")
	if value is Mesh:
		var surfaces: Array = []
		for i in range(value.get_surface_count()):
			surfaces.append({"primitive": _primitive(value, i),
				"arraysSha256": _hash(value.surface_get_arrays(i)),
				"material": _value(value.surface_get_material(i), anchor + "/surface/" + str(i))})
		row["surfaces"] = surfaces
		row["aabb"] = _stable_atom(value.get_aabb())
	if value is ShaderMaterial:
		var uniforms := {}
		var names: Array[String] = []
		for item: Dictionary in value.shader.get_shader_uniform_list():
			names.append(str(item.name))
		names.sort()
		for key: String in names:
			uniforms[key] = _value(value.get_shader_parameter(key), anchor + "/uniform/" + key)
		row["uniforms"] = uniforms
	return row

func _fields(object: Object, keys: Array, anchor: String) -> Dictionary:
	var result := {}
	for key: String in keys:
		result[key] = _value(object.get(key), anchor + "/" + key)
	return result

func _weather_values() -> Dictionary:
	var result := {}
	# reflection_revision is index 8 and has its own exact per-chunk +0/+1 gate.
	for key: String in WEATHER_FIELDS.slice(0, 8):
		result[key] = weather.get(key)
	return result

func _freeze() -> void:
	for node: Node in [scene] + scene.find_children("*", "", true, false):
		var path := _stable_path(node)
		if not process_modes.has(path):
			process_modes[path] = [node.is_processing(), node.is_physics_processing(), node.process_mode, node.process_priority]
		node.set_process(false)
		node.set_physics_process(false)

func _sync_atmosphere() -> void:
	# Calls real scripts, not replacement shader/global setters.
	scene.get_node("MountainAtmosphere").call("_process", 0.0)
	scene.get_node("GroundAtmosphere").call("_process", 0.0)
	scene.get_node("GroveAtmosphere").call("_process", 0.0)
	scene.get_node("VillageWindmills").call("_process", 0.0)
	wildlife.call("advance", float(weather.get("animation_clock")))

func _live_cache_and_bindings() -> void:
	var village := scene.get_node("VillageWindmills")
	var rotors: Array = village.get("rotors")
	_check(rotors.size() == 2 and rotors[0] == scene.get_node("VillageRotor_0") and rotors[1] == scene.get_node("VillageRotor_1"), "Two exact live rotor NodeRefs")
	var pools: Array = get_nodes_in_group("meadow_night_sources")
	_check(pools.size() == 7 and weather.get("source_pools").size() == 7, "Seven night sources registered before weather scans group")
	for pool: Node in pools:
		_check(pool in weather.get("source_pools") and scene.is_ancestor_of(pool), "Weather holds actual live grouped source")
	var edge := scene.get_node("MeadowEdgeGrowth")
	_check(edge.get("ready_complete") == true, "EdgeGrowth ready_complete restored or rebuilt once")
	_check(edge.get_child_count() == 2 and edge.has_node("CrownToTurfFringe") and edge.has_node("CrownTransitionBranchlets"), "No duplicate edge placeholders/restored children")
	_check(not scene.ready.is_connected(Callable(edge, "_build")), "Edge parent-ready one-shot is consumed")
	var grove := scene.get_node("GroveAtmosphere")
	_check(grove.get_script() != null and grove.get("registered").size() == 12 and grove.get("materials").size() == 12
		and grove.get("day_profiles").size() == 12, "Twelve live grove bindings and day profiles")
	for id: int in grove.get("registered"):
		var target: Object = instance_from_id(id)
		_check(target is MeshInstance3D and scene.is_ancestor_of(target) and target.material_override in grove.get("materials"), "Grove registry uses current nodes/materials, not captured IDs")
	var cache: Dictionary = scene.get_meta("_meadow_progressive_support_v135", {})
	for key: Variant in cache:
		var item: Dictionary = cache[key]
		var owner_node: Node = item.node.get_ref() if item.get("node") is WeakRef else null
		var shape: Shape3D = item.shape.get_ref() if item.get("shape") is WeakRef else null
		if not _check(owner_node != null and shape != null and scene.is_ancestor_of(owner_node), "No serialized stale support WeakRef"):
			continue
		_check(key == owner_node.get_instance_id() and item.shape_id == shape.get_instance_id(), "Support keys refer to this process's live instances")
		var target: String = "ground_surface" if owner_node.name == &"ContinuousMeadow" else "rock_surface"
		if not controller.get("completed"):
			_check(item.surface == wildlife.get(target), "Actual wildlife consumes live cached TriangleMesh")
		_check(item.surface is TriangleMesh and shape is ConcavePolygonShape3D
			and _hash(item.surface.get_faces()) == _hash(shape.get_faces()), "Cached query equals live full collider, not cacheValid")

func _input_checks() -> void:
	var guide: Node3D = scene.get("scale_guide")
	var rings: Array = []
	for child: Node in guide.get_children():
		if child is MeshInstance3D and child != scene.get("walker"):
			rings.append(child)
	if _check(rings.size() == 1 and rings[0].mesh != null and rings[0].mesh.get_surface_count() == 1, "C-key Boss guide surface exists"):
		var mesh: Mesh = rings[0].mesh
		var arrays := mesh.surface_get_arrays(0)
		_check(_primitive(mesh, 0) == Mesh.PRIMITIVE_LINE_STRIP and arrays.size() == Mesh.ARRAY_MAX
			and arrays[Mesh.ARRAY_VERTEX].size() == 65, "ImmediateMesh retained/rebuilt all 65 Boss guide points")
	var event := InputEventKey.new()
	event.pressed = true
	for key: int in [KEY_D, KEY_G, KEY_C]:
		event.keycode = key
		var seeded_default := false
		if key == KEY_G and scene.focus_material.get_shader_parameter("show_depth") == null:
			# Dummy backend cannot supply unassigned shader defaults. Do not claim
			# an observed default: test the real G handler from its pinned GLSL
			# default explicitly, AFTER the untouched core snapshot and CPU span.
			var shader: Shader = scene.focus_material.shader
			if not _check(DisplayServer.get_name() == "headless" and shader.resource_path == "res://shaders/meadow_focus.gdshader"
				and shader.code.contains("uniform bool show_depth = false;"), "Only proven headless G-default test fixture"):
				return
			scene.focus_material.set_shader_parameter("show_depth", false)
			seeded_default = true
		var before: Variant = scene.get("focus_enabled") if key == KEY_D else bool(scene.focus_material.get_shader_parameter("show_depth")) if key == KEY_G else guide.visible
		scene.call("_unhandled_key_input", event)
		var after: Variant = scene.get("focus_enabled") if key == KEY_D else bool(scene.focus_material.get_shader_parameter("show_depth")) if key == KEY_G else guide.visible
		_check(after == (not bool(before)), "Actual input toggles: " + str(key))
		if key == KEY_C:
			# Suppress only the old heavy debug audit; exercise the REAL gameplay branch.
			scene.set("audit_complete", true)
			var previous: Vector3 = scene.get("walker").position
			scene.call("_physics_process", 0.125)
			_check(scene.get("walker").position != previous and scene.get("travel") > 22.0, "C guide walker advances through real physics method")
		scene.call("_unhandled_key_input", event)
		functional_rows.append({"key": key, "before": before, "after": after, "headlessDefaultExplicitlySeededNotObserved": seeded_default})

func _references_alive() -> void:
	var refs := {"weather": weather, "wildlife": wildlife, "controller": controller,
		"ground": scene.get("ground_material"), "focus": scene.get("focus_material")}
	for path: String in ["IndependentCastleHill", "DistantVillage", "VillageRotor_0", "VillageRotor_1"]:
		var material: Material = scene.get_node(NodePath(path)).material_override
		_check(material in weather.get("architecture_materials"), "Weather writes actual live material: " + path)
		refs[path] = material
	for key: String in refs:
		if not pinned_live.has(key):
			pinned_live[key] = refs[key].get_instance_id()
		_check(pinned_live[key] == refs[key].get_instance_id(), "Retain live identity: " + key)
	_check(scene.get_node("ContinuousMeadow").material_override == scene.get("ground_material"), "Ground member aliases live material")
	_check(camera.get_node("DepthAwareFocus").material_override == scene.get("focus_material"), "Focus member aliases live material")

func _snapshot(label: String) -> void:
	_freeze()
	_sync_atmosphere()
	_references_alive()
	_live_cache_and_bindings()
	resources = {}
	resource_ids = {}
	rid_aliases = {}
	graph_nodes = []
	var nodes: Array = [scene] + scene.find_children("*", "", true, false)
	nodes.sort_custom(func(a: Node, b: Node) -> bool: return _stable_path(a) < _stable_path(b))
	var lights := {"DirectionalLight3D": 0, "OmniLight3D": 0, "SpotLight3D": 0, "AreaLight3D": 0}
	var cache_notes := {}
	for node: Node in nodes:
		var path := _stable_path(node)
		var groups: Array = node.get_groups()
		groups.sort()
		var row := {"path": path, "class": node.get_class(), "order": node.get_index(), "groups": groups,
			"processBeforeFreeze": process_modes[path], "stored": _stored(node, path, ["name"])}
		if node is Node3D:
			row["globalTransform"] = _stable_atom(node.global_transform)
		var metadata := {}
		for key: StringName in node.get_meta_list():
			if key in CACHE_DIAGNOSTICS:
				var state: Dictionary = node.get_meta(key)
				cache_notes[str(key)] = {"valid": state.get("valid"), "hits": state.get("hits", []), "misses": state.get("misses", [])}
			elif key == &"build_ms" or key == &"_meadow_progressive_support_v135":
				# Wall time and instance-ID/WeakRef memo tables are not scene semantics.
				# The actual support consumers' full face hashes are included below.
				continue
			else:
				metadata[str(key)] = node.get_meta(key)
		row["metadata"] = _value(metadata, path + "/metadata")
		if node is Light3D:
			lights[node.get_class()] = int(lights.get(node.get_class(), 0)) + 1
		graph_nodes.append(row)
	_check(lights == {"DirectionalLight3D": 4, "OmniLight3D": 9, "SpotLight3D": 0, "AreaLight3D": 0}, "Actual 4+9+0+0 lights: " + label)
	var members := _fields(scene, MAIN_FIELDS, "main")
	members["weather"] = _fields(weather, WEATHER_FIELDS, "weather")
	members["windmills"] = _fields(scene.get_node("VillageWindmills"), ["rotors", "weather", "last_clock"], "windmills")
	members["edge"] = _fields(scene.get_node("MeadowEdgeGrowth"), ["ready_complete", "meadow", "land", "rocks"], "edge")
	var grove := scene.get_node("GroveAtmosphere")
	members["grove"] = _fields(grove, ["materials", "day_profiles", "previous", "previous_color"], "grove")
	var registered: Array[String] = []
	for id: int in grove.get("registered"):
		var target: Object = instance_from_id(id)
		if target is Node and scene.is_ancestor_of(target):
			registered.append(_stable_path(target))
	registered.sort()
	members.grove["registeredLivePaths"] = registered
	members["wildlife"] = _fields(wildlife, ["meadow", "weather", "animals", "obstacles", "ground_surface", "rock_surface",
		"dragon", "dragon_texture", "dragon_frames", "last_clock", "flight_points", "flight_phase", "flight_legs", "night_light", "night_halo", "night_aura"], "wildlife")
	var day_script: Script = scene.get("GROUND_ATMOSPHERE")
	members["staticGroundDayShader"] = _value(day_script.get("day_shader"), "static/day_shader")
	var globals := {}
	for key: String in ["meadow_clock", "meadow_night"]:
		globals[key] = {"projectDefault": _value(ProjectSettings.get_setting("shader_globals/" + key), "globals/" + key),
			"rendererValue": null, "observable": false, "reason": "headless dummy getter returns nil; not GPU evidence"}
	var shapes: Array = []
	for node: Node in nodes:
		if node is CollisionShape3D:
			shapes.append({"path": _stable_path(node), "shape": _shape_record(node.shape),
				"transform": _stable_atom(node.global_transform), "disabled": node.disabled})
	_check(shapes.size() == 5, "Five full original collision shapes: " + label)
	var snap := {"label": label, "nodes": graph_nodes, "resources": resources, "members": members,
		"globals": globals, "lights": lights, "colliders": shapes,
		"controller": _fields(controller, ["applied_count", "busy", "completed", "replacement_count", "mesh_replacement_count", "texture_replacement_count"], "controller")}
	observations.append({"contract": snap, "cacheDiagnosticsNotCompared": cache_notes})

func _transition_checks() -> void:
	weather.call("set_motion", true)
	weather.call("advance_weather", 0.125)
	wildlife.call("advance", float(weather.get("animation_clock")))
	_check(weather.get("animation_clock") == 0.125, "Real shared clock advances")
	var village := scene.get_node("VillageWindmills")
	var before_rotation: Vector3 = scene.get_node("VillageRotor_0").rotation
	village.call("_process", 0.0)
	_check(village.get("weather") == weather and scene.get_node("VillageRotor_0").rotation != before_rotation, "Live rotor follows actual shared clock")
	weather.call("toggle_time")
	weather.call("advance_weather", 1.6)
	_check(weather.get("night_blend") == 0.5 and weather.get("transitioning"), "Real reversible halfway lighting")
	_snapshot("transition-half")
	weather.call("set_reduced_motion", true)
	var clock_before: float = weather.get("animation_clock")
	weather.call("advance_weather", 1.0)
	wildlife.call("advance", clock_before)
	_check(weather.get("animation_clock") == clock_before and not weather.get("motion_enabled") and weather.get("night_blend") == 1.0,
		"Reduced motion finishes lighting and pauses clock")
	_snapshot("reduced-night")
	weather.call("toggle_time")
	_check(weather.get("night_blend") == 0.0 and not weather.get("transitioning"), "Reduced-motion day is immediate")
	_snapshot("reduced-day")
	weather.call("set_motion", true)
	_check(not weather.get("reduced_motion"), "Explicit Play restores full motion")
	weather.call("set_motion", false)

func _run() -> void:
	var probe_entered := Time.get_ticks_usec()
	var args := OS.get_cmdline_user_args()
	if args.size() != 1:
		quit(2)
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	output_path = str(request.out).replace("\\", "/").simplify_path()
	if request.get("schema") != "static-core-request-v1" or not output_path.begins_with(STATIC_SCOPE) or FileAccess.file_exists(output_path):
		quit(2)
		return
	pack_path = request.corePack.file
	root.size = VIEW_SIZE
	root.content_scale_size = VIEW_SIZE
	# No source/capture resource is loaded before this marker, in either process.
	var load_begin := Time.get_ticks_usec()
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	var load_end := Time.get_ticks_usec()
	if not _check(packed != null, "Actual main scene loads"):
		_finish_static()
		return
	scene = packed.instantiate() as Node3D
	var instantiate_end := Time.get_ticks_usec()
	if not _check(scene != null and scene.get_script() != null, "Actual compiled main attaches"):
		_finish_static()
		return
	entry_observed = {"nodes": 1 + scene.find_children("*", "", true, false).size(),
		"meshes": scene.find_children("*", "MeshInstance3D", true, false).size(),
		"shapes": scene.find_children("*", "CollisionShape3D", true, false).size()}
	_check(scene.name == &"MeadowPlain" and scene.transform == Transform3D.IDENTITY, "Exact source10 root name/transform")
	if request.role == "candidate":
		_check(entry_observed == {"nodes": 3, "meshes": 0, "shapes": 0} and scene.get_child_count() == 2
			and scene.get_child(0) is Camera3D and scene.get_child(0).name == &"Camera3D"
			and scene.get_child(1).name == &"MeadowEdgeGrowth", "Actual project main loads ONLY root/camera/original EdgeGrowth")
		var edge := scene.get_node("MeadowEdgeGrowth")
		_check(edge.get_script().resource_path == "res://scripts/meadow_edge_growth.gd" and edge.get_child_count() == 0
			and edge.get("ready_complete") == false, "Original EdgeGrowth starts unbuilt before child/parent-ready")
		thin_edge_id = edge.get_instance_id()
	for key: String in CACHE_DIAGNOSTICS + ["_meadow_progressive_support_v135"]:
		_check(not scene.has_meta(key), "No captured runtime cache/valid bit on instantiated main: " + key)
	scene.ready.connect(func() -> void: ready_events += 1)
	root.add_child(scene)
	current_scene = scene
	var ready_end := Time.get_ticks_usec()
	timing = {"probeEnteredUs": probe_entered, "loadBeginUs": load_begin, "loadEndUs": load_end,
		"instantiateEndUs": instantiate_end, "readyEndUs": ready_end, "firstObservationUs": Time.get_ticks_usec(),
		"loadMainMs": (load_end - load_begin) / 1000.0, "instantiateMs": (instantiate_end - load_end) / 1000.0,
		"readyCallMs": (ready_end - instantiate_end) / 1000.0, "cpuLoadThroughReadyMs": (ready_end - load_begin) / 1000.0,
		"spanDescription": "loadMainMs=actual core_resource_load; readyCallMs=complete restore+dynamic tail+ready subscribers, plus small pre-ready observer guards; never just groupAttach",
		"offlineCaptureIncluded": false, "probePreloadsWorld": false, "packMountIncluded": false, "renderReadyClaim": false}
	_check(scene.is_node_ready(), "Actual synchronous _ready completed before observation")
	_check(ready_events == 1, "One actual main ready emission")
	if request.role == "candidate":
		_check(scene.get_node("MeadowEdgeGrowth").get_instance_id() == thin_edge_id, "Preserve original thin-entry EdgeGrowth through restore and parent-ready")
	# Rehash/bind AFTER measured startup, never pre-warm resources to hide work.
	_check(FileAccess.get_sha256(pack_path) == request.corePack.sha256, "Actual core pack pin")
	_bind_pack()
	weather = scene.get_node_or_null("LivingWeather")
	wildlife = scene.get_node_or_null("LivingWildlife")
	camera = scene.get_node_or_null("Camera3D")
	if not _check(weather != null and wildlife != null and camera != null, "Actual live dynamic systems exist"):
		_finish_static()
		return
	for node: Node in scene.find_children("*", "", true, false):
		var script: Script = node.get_script()
		if script != null and script.resource_path == "res://scripts/meadow_progressive.gd":
			_check(controller == null, "One progressive controller only")
			controller = node
	if not _check(controller != null, "Actual progressive controller found"):
		_finish_static()
		return
	for name: String in SYSTEMS:
		_check(scene.has_node(NodePath(name)), "Dynamic setup once: " + name)
	for name: String in REQUIRED:
		_check(scene.has_node(NodePath(name)), "Required whole-scene object: " + name)
	startup_observed = {"weather": _weather_values(), "weatherProcessing": weather.is_processing(),
		"wildlifeProcessing": wildlife.is_processing(), "nodeCount": 1 + scene.find_children("*", "", true, false).size(),
		"viewSize": _json(root.size), "viewRect": _json(camera.get_viewport().get_visible_rect())}
	_check(weather.get("animation_clock") == 0.0 and weather.get("night_blend") == 0.0 and not weather.get("night_target")
		and weather.get("motion_enabled") and not weather.get("reduced_motion") and not weather.get("transitioning"), "Unmodified initial weather before any reset")
	_check(weather.is_processing() and wildlife.is_processing(), "Autonomous animations were really enabled")
	_freeze() # Only test scheduling changes; never save or alter shipping scripts.
	var initial: Array = []
	for animal: Dictionary in wildlife.get("animals"):
		initial.append(animal.duplicate())
	_check(initial.size() == 4 and wildlife.get("dragon_frames").size() == 32, "Four species and 32 dragon frames")
	for animal: Dictionary in initial:
		_check(animal.frames.size() == 8, "Eight-frame species atlas")
	_reset(SEEDS[0], initial) # randomize() is production behavior; compare matched seeds only AFTER observing startup.
	_snapshot("core")
	_input_checks()
	# Bounded event-loop regression: restoring already built children must not
	# schedule a second parent-ready build after the first snapshot.
	await process_frame
	await process_frame
	_live_cache_and_bindings()
	_check(ready_events == 1, "No second ready emission after deferred work")
	_transition_checks()
	_check(request.detailPacks.size() == 12, "Exactly twelve real chunks")
	for group: Dictionary in request.detailPacks:
		var before := _weather_values()
		var reflection_before: int = weather.get("reflection_revision")
		_check(FileAccess.get_sha256(group.file) == group.sha256, "Exact approved chunk bytes")
		var started := Time.get_ticks_usec()
		await controller.call("apply_chunk", int(group.index), str(group.file))
		chunk_steps.append({"index": group.index, "applyAwaitMs": (Time.get_ticks_usec() - started) / 1000.0,
			"includesFrameWaits": true, "sha256": group.sha256})
		_check(not controller.get("busy") and str(controller.get("last_error")).is_empty() and controller.get("applied_count") == int(group.index) + 1,
			"Chunk really applied once: " + str(group.index))
		_check(_same_json(before, _weather_values()), "Chunk preserves user clock/lighting/motion")
		_check(weather.get("reflection_revision") == reflection_before + (1 if group.index == 11 else 0), "Only final detail triggers reflection refresh")
		_snapshot("chunk-" + str(int(group.index)))
	_check(controller.get("completed") and controller.get("replacement_count") == 9 and controller.get("mesh_replacement_count") == 2
		and controller.get("texture_replacement_count") == 30, "12 chunks restore 9 roots, 2 meshes and 30 in-place textures")
	_check(scene.get_node("RiverSurroundingsReflection").visible and camera.get_node("DepthAwareFocus").visible, "Actual final focus/reflection restored")
	for night: bool in [true, false]:
		_set_day(night)
		_snapshot("final-night" if night else "final-day")
	for seed_value: int in SEEDS:
		route_rows.append(_sample_route(seed_value, initial))
	_check(route_rows[0].dragon.routeSha256 != route_rows[1].dragon.routeSha256, "Distinct seeds produce distinct smooth dragon routes")
	_finish_static()

func _finish_static() -> void:
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	file.store_string(JSON.stringify({"schema": "static-core-observation-v1", "status": "OBSERVED_CPU_ONLY" if errors.is_empty() else "FAIL",
		"errors": errors, "requestSha256": FileAccess.get_sha256(OS.get_cmdline_user_args()[0]), "corePack": request.corePack,
		"packBinding": pack_binding, "timing": timing, "entryBeforeReady": entry_observed, "startup": startup_observed,
		"snapshots": observations, "chunks": chunk_steps, "routes": route_rows, "inputChecks": functional_rows,
		"limits": ["Headless/native observation only; no Web/HTTP/shader/GPU/presentation or 10s conclusion.",
			"Cold OS/driver cache not controlled. Native process/PCK mount excluded from measured CPU span.",
			"Clock/RNG stepped deterministically after original startup; autonomous processing frozen only in probe.",
			"Only cache hit/miss memo tables, build_ms and inline resource provenance are excluded from semantic equality.",
			"Renderer globals are NOT observable in dummy backend; real Web day/night/water remains main's gate."]}, "\t", true, true) + "\n")
	file.close()
	if is_instance_valid(scene):
		scene.free()
	quit(0 if errors.is_empty() else 1)
