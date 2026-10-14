extends SceneTree
## Bounded native verification of only the new conform memoization branch.

func _initialize() -> void:
	_run.call_deferred()

func _sha(data: PackedByteArray) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(data)
	return hash.finish().hex_encode()

func _run() -> void:
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	assert(FileAccess.get_sha256(spec.core) == "9472167e7e416eca07e9a217eba189b1ddeecb149faa86b121f9c0a097fe3e93")
	assert(FileAccess.get_sha256(spec.overlay.path) == spec.overlay.sha256)
	assert(ProjectSettings.load_resource_pack(spec.overlay.path, true))
	assert(FileAccess.get_sha256("res://scripts/meadow_scene.gdc") == spec.baselineMainSha256)
	var packed := load(str(ProjectSettings.get_setting("application/run/main_scene"))) as PackedScene
	var scene := packed.instantiate() as Node3D
	var derived := load(str(spec.derived)) as Script
	assert(derived != null and derived.can_instantiate())
	scene.set_script(derived)
	scene.set("audit_complete", true)
	var started := Time.get_ticks_usec()
	root.add_child(scene)
	current_scene = scene
	var ready_ms := (Time.get_ticks_usec() - started) / 1000.0
	var state: Dictionary = scene.get_meta("_meadow_root_conform_cache_v135")
	var previous: Dictionary = scene.get_meta("_meadow_static_geometry_cache_v135")
	assert(state.valid and state.hits.size() == 50 and state.misses.is_empty())
	assert(previous.valid and previous.hits.size() == 17 and previous.misses.is_empty())
	var records: Array = []
	for name: String in scene.root_before:
		var node := scene.get_node(NodePath(name)) as MeshInstance3D
		var before: Dictionary = scene.root_before[name]
		assert(node.get_instance_id() == before.nodeId)
		# The helper already proved the material ID unchanged at its own call site.
		# Subsequent original Atmosphere.register_grove intentionally duplicates some
		# far materials. Verify ownership rather than rejecting that baseline behavior.
		var atmosphere_owned := false
		if node.material_override.get_instance_id() != before.materialId:
			for item: Node in scene.get_children():
				if item.get("registered") is Dictionary and item.get("materials") is Array:
					if item.get("registered").has(node.get_instance_id()) and node.material_override in item.get("materials"):
						atmosphere_owned = true
			assert(atmosphere_owned, "Changed post-hook material must belong to original grove atmosphere")
		assert(node.transform == before.transform and scene._root_metadata(node) == before.metadata and node.get_children() == before.children)
		var cached: ArrayMesh = node.mesh
		var original: ArrayMesh = scene.root_reference(node)
		var raw := var_to_bytes(cached.get("_surfaces"))
		var decoded := var_to_bytes(cached.surface_get_arrays(0))
		assert(raw == var_to_bytes(original.get("_surfaces")), "Original raw storage exact " + name)
		assert(decoded == var_to_bytes(original.surface_get_arrays(0)), "Original decoded arrays exact " + name)
		assert(cached.get_aabb() == original.get_aabb())
		assert(cached.surface_get_material(0) == original.surface_get_material(0))
		records.append({"name": name, "rawStorageSha256": _sha(raw), "arraysSha256": _sha(decoded),
			"vertices": cached.surface_get_array_len(0), "indices": cached.surface_get_array_index_len(0),
			"materialId": str(node.material_override.get_instance_id()), "nodeId": str(node.get_instance_id()),
			"contextSha256": _sha(state.records[name].context), "wholeColumn": before.whole,
			"helperMaterialIdUnchanged": true, "laterOriginalAtmosphereMaterialCopy": atmosphere_owned})
	# One deliberately mismatched input must leave its QuadMesh and material intact.
	var sample := scene.get_node(NodePath(str(scene.root_before.keys()[0]))) as MeshInstance3D
	var sample_before: Dictionary = scene.root_before[str(sample.name)]
	var saved_mesh := sample.mesh
	var saved_material_id := sample.material_override.get_instance_id()
	sample.mesh = sample_before.quad
	var helper: Script = load("res://scripts/meadow_root_conform_cache.gd")
	assert(not helper.restore(scene, sample, not sample_before.whole))
	assert(sample.mesh == sample_before.quad and sample.material_override.get_instance_id() == saved_material_id)
	sample.mesh = saved_mesh
	var inventory := {"directional": 0, "omni": 0, "spot": 0, "area": 0, "colliders": 0}
	for node: Node in scene.find_children("*", "Node", true, false):
		if node is DirectionalLight3D: inventory.directional += 1
		elif node is OmniLight3D: inventory.omni += 1
		elif node is SpotLight3D: inventory.spot += 1
		elif node.is_class("AreaLight3D") or node.is_class("RectLight3D"): inventory.area += 1
		if node is CollisionShape3D: inventory.colliders += 1
	assert(inventory == {"directional": 4, "omni": 9, "spot": 0, "area": 0, "colliders": 5})
	var report := {"status": "PASS_ROOT_CONFORM_CACHE_50_EXACT_NATIVE", "sourceCoreSha256": FileAccess.get_sha256(spec.core),
		"readyMs": ready_ms, "cacheRestoreMs": scene.cache_usec / 1000.0, "oldCacheHits": previous.hits.size(),
		"records": records, "inventory": inventory, "mismatchFallbackPreservesQuadAndMaterial": true,
		"limits": ["One native headless instance plus inherited two-line hook, not final integrated compiled main or Web first-draw timing.",
			"All 50 original functions recomputed after ready measurement; original raw surfaces/arrays/AABB equal cached results.",
			"Original packed main/controller, all 17 caches, all colliders and chunk files were not changed."]}
	var stream := FileAccess.open(spec.report, FileAccess.WRITE)
	stream.store_string(JSON.stringify(report, "\t", true, true) + "\n")
	stream.close()
	scene.free()
	quit()
