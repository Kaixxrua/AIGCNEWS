extends SceneTree
## Isolated real edge-controller lifecycle with ONLY its two support meshes.
## Main-script test subclass overrides _ready; no whole scene is built.

var failures := 0
var request: Dictionary
var meadow_harness: GDScript
var support_meshes := {}

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _check(condition: bool, message: String) -> bool:
	if not condition:
		failures += 1
		push_error("EDGE_GROWTH_V128: " + message)
	return condition

func _sha(data: PackedByteArray) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	if not data.is_empty():
		hash.update(data)
	return hash.finish().hex_encode()

func _properties(object: Object, excluded: Array = []) -> Dictionary:
	var result := {}
	for property: Dictionary in object.get_property_list():
		if int(property.usage) & PROPERTY_USAGE_STORAGE and str(property.name) not in excluded:
			result[str(property.name)] = _stable(object.get(property.name))
	return result

func _stable(value: Variant) -> Variant:
	if value is Resource:
		if value is Shader or value is Texture2D:
			return [value.get_class(), value.resource_path]
		_check(value.get_script() == null, "Generated resources have no scripts")
		return [value.get_class(), _properties(value, ["resource_path", "resource_scene_unique_id"])]
	if value is Dictionary:
		var result := {}
		for key: Variant in value:
			result[str(key)] = _stable(value[key])
		return result
	if value is Array:
		var result: Array = []
		for item: Variant in value:
			result.append(_stable(item))
		return result
	_check(not value is Object, "Only stored Variant/resource data")
	return [typeof(value), _sha(var_to_bytes(value))]

func _contract(script: GDScript) -> Dictionary:
	var methods := script.get_script_method_list()
	methods.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	var properties := script.get_script_property_list().filter(func(p: Dictionary) -> bool:
		return not (int(p.usage) == PROPERTY_USAGE_CATEGORY and str(p.hint_string) == script.resource_path))
	properties.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	var signals := script.get_script_signal_list()
	signals.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.name) < str(b.name))
	return {"base": script.get_instance_base_type(), "methods": methods, "properties": properties, "signals": signals}

func _prepare_support() -> Dictionary:
	var proof := {}
	for item: Dictionary in request.support:
		var packed := load(item.resource) as PackedScene
		_check(packed != null, "Read support resource without instantiating its nodes/colliders")
		var state := packed.get_state()
		for i in range(state.get_node_count()):
			if str(state.get_node_name(i)) != item.node:
				continue
			for j in range(state.get_node_property_count(i)):
				if state.get_node_property_name(i, j) == &"mesh":
					var mesh: ArrayMesh = state.get_node_property_value(i, j)
					support_meshes[item.node] = mesh
					var surfaces: Array = []
					for surface in range(mesh.get_surface_count()):
						var arrays := mesh.surface_get_arrays(surface)
						surfaces.append({"primitive": mesh.surface_get_primitive_type(surface),
							"vertices": _stable(arrays[Mesh.ARRAY_VERTEX]), "indices": _stable(arrays[Mesh.ARRAY_INDEX])})
					proof[item.node] = surfaces
	_check(support_meshes.size() == 2, "Exactly terrain and rock support meshes")
	meadow_harness = GDScript.new()
	meadow_harness.source_code = """extends "res://scripts/meadow_scene.gd"
var edge_probe_ready_body := false
var edge_probe_complete_inside_body := false
func _ready() -> void:
	edge_probe_ready_body = true
	var controller := get_node_or_null("NaturalCrownEdges")
	edge_probe_complete_inside_body = controller.ready_complete if controller != null else false
"""
	_check(meadow_harness.reload() == OK, "Test-only main ready override; geometry/static methods inherited unchanged")
	return proof

func _make(script: GDScript, parent_already_ready: bool = false, warm_support: bool = false) -> Dictionary:
	var meadow: Node3D = meadow_harness.new()
	meadow.name = "IsolatedEdgeGrowthSupport"
	meadow.process_mode = Node.PROCESS_MODE_DISABLED
	var camera := Camera3D.new()
	camera.name = "Camera3D"
	meadow.add_child(camera)
	for label: String in support_meshes:
		var support := MeshInstance3D.new()
		support.name = label
		# Fresh resource makes original generation pay actual query-cache creation.
		support.mesh = support_meshes[label].duplicate(false)
		meadow.add_child(support)
		if warm_support:
			support.mesh.generate_triangle_mesh() # Outside timed controller work.
	var controller: Node3D = script.new()
	controller.name = "NaturalCrownEdges"
	_check(not controller.ready_complete, "Controller begins incomplete")
	var started := Time.get_ticks_usec()
	if parent_already_ready:
		root.add_child(meadow)
		meadow.add_child(controller)
	else:
		meadow.add_child(controller)
		root.add_child(meadow)
	var elapsed := Time.get_ticks_usec() - started
	_check(meadow.edge_probe_ready_body and not meadow.edge_probe_complete_inside_body,
		"Generation remains after parent ready body, not inside sceneReady boundary")
	_check(controller.ready_complete and controller.get_child_count() == 2 and controller.land == null and controller.rocks == null,
		"Both generated meshes ready synchronously before add_child returns; query handles released")
	_check(controller.meadow == meadow and meadow.asset_paths.is_empty() and meadow.occupied_art_regions.is_empty()
		and meadow.shadow_ellipses.is_empty() and not meadow.audit_complete and meadow.render_metrics_samples == 0,
		"Main ready, unrelated art/bookkeeping, audits and physics never ran")
	return {"meadow": meadow, "controller": controller, "lifecycleUsec": elapsed}

func _extended(patched: GDScript) -> Dictionary:
	# Test subclass inherits the REAL compiled _ready/_build. Count fallback work
	# without adding instrumentation to any packed/runtime script.
	var probe := GDScript.new()
	# Inheritance resolves through the real .gd.remap path, not a scratch .gdc filename.
	probe.source_code = "extends \"res://scripts/meadow_edge_growth.gd\"\n" + """var edge_probe_surface_calls := 0
var edge_probe_branchlet_calls := 0
func _surface(p: Vector2) -> Dictionary:
	edge_probe_surface_calls += 1
	return super._surface(p)
func _build_branchlets(roots: PackedVector3Array, vertices: int) -> void:
	edge_probe_branchlet_calls += 1
	super._build_branchlets(roots, vertices)
"""
	if not _check(probe.reload() == OK, "Compiled-controller test subclass"):
		return {}
	var hit := _make(probe, false, true)
	_check(hit.controller.edge_probe_surface_calls == 0 and hit.controller.edge_probe_branchlet_calls == 0,
		"Valid cache actually avoids procedural surface/branchlet construction")
	var expected := _snapshot(hit.controller)
	var cache := load(request.cache_resource) as PackedScene
	var fallbacks := {}
	for key: String in ["edge_growth_schema", "source_sha256"]:
		var saved: Variant = cache.get_meta(key)
		cache.set_meta(key, "invalid-test-only-in-memory")
		var fallback := _make(probe, false, true)
		_check(fallback.controller.edge_probe_surface_calls > 0 and fallback.controller.edge_probe_branchlet_calls == 1,
			"Stale cache invokes exact procedural fallback")
		_check(_snapshot(fallback.controller) == expected, "Stale-cache fallback geometry/metadata exact")
		fallbacks[key] = {"surfaceCalls": fallback.controller.edge_probe_surface_calls,
			"branchletCalls": fallback.controller.edge_probe_branchlet_calls, "exact": true}
		fallback.meadow.free()
		cache.set_meta(key, saved)
	var second := _make(patched, false, true)
	var second_before := _snapshot(second.controller)
	for i in range(2):
		var a: MeshInstance3D = hit.controller.get_child(i)
		var b: MeshInstance3D = second.controller.get_child(i)
		_check(a.mesh != b.mesh and a.material_override != b.material_override, "Mutable instance resources independent")
		a.mesh.clear_surfaces()
		a.material_override.set_shader_parameter("middle_scrub", false)
	_check(_snapshot(second.controller) == second_before, "Mutation of one instance does not leak into another")
	hit.meadow.free()
	second.meadow.free()
	return {"validCacheSurfaceCalls": 0, "validCacheBranchletCalls": 0, "fallbacks": fallbacks,
		"crossInstanceMeshAndMaterialMutationIsolated": true, "testOnlyCacheMetadataRestored": true}

func _snapshot(controller: Node3D) -> Dictionary:
	var nodes: Array = []
	var vertices := 0
	for child: Node in controller.get_children():
		_check(child is MeshInstance3D and child.get_child_count() == 0 and child.get_script() == null, "Two inert mesh children only")
		_check(child.mesh is ArrayMesh and child.mesh.get_surface_count() == 1, "Exact one-surface meshes")
		_check(child.has_meta("build_ms") and typeof(child.get_meta("build_ms")) == TYPE_INT and child.get_meta("build_ms") >= 0,
			"Runtime timing key retained as actual nonnegative duration")
		vertices += child.mesh.surface_get_array_len(0)
		nodes.append({"name": str(child.name), "index": child.get_index(), "ownerNull": child.owner == null,
			"properties": _properties(child, ["scene_file_path", "metadata/build_ms"]),
			"decodedArrays": _stable(child.mesh.surface_get_arrays(0))})
	return {"nodes": nodes, "vertices": vertices, "triangles": vertices / 3, "readyComplete": controller.ready_complete,
		"controllerTransform": _stable(controller.transform), "fringeRoots": controller.get_node("CrownToTurfFringe").get_meta("roots").size(),
		"branchletRoots": controller.get_node("CrownTransitionBranchlets").get_meta("roots").size()}

func _physical(controller: Node3D) -> Dictionary:
	controller.land = controller.meadow.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
	controller.rocks = controller.meadow.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
	var roots := 0
	var max_error := 0.0
	var max_neighbor_delta := 0.0
	for child: Node in controller.get_children():
		for point: Vector3 in child.get_meta("roots"):
			var p := Vector2(point.x, point.z)
			var hit: Dictionary = controller._surface(p)
			_check(not hit.is_empty() and controller._safe(p, 0.81), "Root safe from road/Boss/river/habitats")
			if hit.is_empty():
				continue
			max_error = maxf(max_error, absf(point.y - (float(hit.position.y) + 0.006)))
			_check(hit.normal.y >= 0.82 and not controller.meadow.below_river_surface(p.x, p.y, hit.position.y), "Root slope/water support")
			for offset: Vector2 in [Vector2(0.48, 0), Vector2(-0.48, 0), Vector2(0, 0.48), Vector2(0, -0.48)]:
				var neighbor: Dictionary = controller._surface(p + offset)
				_check(not neighbor.is_empty(), "Neighbor support exists")
				if not neighbor.is_empty():
					max_neighbor_delta = maxf(max_neighbor_delta, absf(neighbor.position.y - hit.position.y))
			roots += 1
	_check(roots == 632 and max_error < 0.00001 and max_neighbor_delta <= 0.26, "Original support constraints for 605+27 roots")
	controller.land = null
	controller.rocks = null
	return {"roots": roots, "maxRootHeightError": max_error, "maxNeighborHeightDelta": max_neighbor_delta,
		"allOriginalSafetyAndSupportConstraintsPass": true}

func _bake(original: GDScript) -> Dictionary:
	var subject := _make(original)
	var controller: Node3D = subject.controller
	var before := _snapshot(controller)
	_check(before.fringeRoots == 605 and before.branchletRoots == 27, "Frozen actual fringe/branchlet count")
	var physical := _physical(controller)
	var root_node := Node3D.new()
	root_node.name = "ExactCrownEdgeCacheV128"
	for child: Node in controller.get_children():
		controller.remove_child(child)
		root_node.add_child(child)
		child.owner = root_node
	var packed := PackedScene.new()
	_check(packed.pack(root_node) == OK, "Pack ONLY generated controller children")
	packed.set_meta("edge_growth_schema", "edge-controller-v128-1")
	packed.set_meta("source_sha256", request.source_sha256)
	packed.set_meta("support_geometry", request.support_proof)
	_check(not FileAccess.file_exists(request.cache_output), "New cache artifact only")
	_check(ResourceSaver.save(packed, request.cache_output, ResourceSaver.FLAG_COMPRESS) == OK, "Save new controller cache")
	root_node.free()
	var reloaded := ResourceLoader.load(request.cache_output, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	var instance := reloaded.instantiate()
	for child: Node in instance.get_children():
		instance.remove_child(child)
		child.owner = null
		controller.add_child(child)
	_check(_snapshot(controller) == before, "Raw surfaces, decoded channels, materials and nontiming metadata exact after reload")
	instance.free()
	subject.meadow.free()
	return {"snapshot": before, "physical": physical, "originalLifecycleUsec": subject.lifecycleUsec,
		"cacheBytes": FileAccess.get_file_as_bytes(request.cache_output).size(), "nativeCacheRoundtripExact": true}

func _run() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if not _check(args.size() == 1, "One scoped request"):
		return
	request = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var output := str(request.output).replace("\\", "/").simplify_path()
	if not _check(output.contains("/artifacts/startup-v128/edge-growth/")
		and ProjectSettings.globalize_path("res://").replace("\\", "/").begins_with(output + "/"), "Isolated artifact scope"):
		return
	var version := Engine.get_version_info()
	_check(version.major == 4 and version.minor == 7 and version.patch == 2, "Pinned Godot 4.7.2")
	_check(ProjectSettings.load_resource_pack(request.pack), "Mount frozen pack read-only")
	_check(FileAccess.get_sha256(request.original_gdc) == request.original_gdc_sha256, "Pinned original controller GDC")
	var original := ResourceLoader.load(request.original_gdc, "GDScript", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as GDScript
	if not _check(original != null and original.can_instantiate(), "Original controller validates"):
		return
	request.support_proof = _prepare_support()
	var result := {"engine": version.string, "mode": request.mode, "supportGeometry": request.support_proof}
	if request.mode == "bake":
		result.bake = _bake(original)
	elif request.mode == "verify":
		if request.get("candidate_pack", "") != "":
			_check(ProjectSettings.load_resource_pack(request.candidate_pack), "Mount candidate plus exact cache")
		_check(FileAccess.get_sha256(request.patched_gdc) == request.patched_gdc_sha256, "Pinned stock-compiled controller")
		var patched := ResourceLoader.load(request.patched_gdc, "GDScript", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as GDScript
		if not _check(patched != null and patched.can_instantiate(), "Patched controller validates"):
			return
		_check(_contract(original) == _contract(patched), "All compiled method/property/signal contracts unchanged")
		result.compiledContractsEqual = true
		result.cachePresent = ResourceLoader.exists(request.cache_resource)
		result.cases = {}
		var warm_support: bool = request.get("warm_support", false)
		result.supportQueriesPrewarmedOutsideTiming = warm_support
		for ready_first: bool in [false, true]:
			var before := _make(original, ready_first, warm_support)
			var after := _make(patched, ready_first, warm_support)
			var original_snapshot := _snapshot(before.controller)
			var candidate_snapshot := _snapshot(after.controller)
			_check(original_snapshot == candidate_snapshot, "Actual compiled-controller final state exact")
			result.cases["alreadyReady" if ready_first else "parentReadySignal"] = {
				"originalUsec": before.lifecycleUsec, "candidateUsec": after.lifecycleUsec,
				"allNodeMeshMaterialMetadataExactExceptBuildMs": original_snapshot == candidate_snapshot,
				"snapshot": candidate_snapshot, "physical": _physical(after.controller)}
			before.meadow.free()
			after.meadow.free()
		if request.get("extended", false):
			_check(result.cachePresent, "Extended test needs real cached asset")
			result.extended = _extended(patched)
	else:
		_check(false, "Unknown bounded mode")
	result.failures = failures
	var path := output.path_join("result.json")
	if _check(not FileAccess.file_exists(path), "New result only"):
		var file := FileAccess.open(path, FileAccess.WRITE)
		file.store_string(JSON.stringify(result, "\t") + "\n")
		file.close()
	print("EDGE_GROWTH_V128: ", "PASS" if failures == 0 else "FAIL")
	quit(0 if failures == 0 else 1)
