extends "audit_progressive_v135.gd"
## Additional assertions, never a relaxed full-scene comparison or runtime patch.

var proxy_core_checked := false
var persistent_ids: Dictionary = {}
var proxy_observations: Array = []
var mesh_commits: Array = []
var raw_source_checks: Array = []

func _proxy_ids() -> Dictionary:
	var result := {}
	for path: String in request.proxyContract.meshRoots:
		var node: MeshInstance3D = scene.get_node(NodePath(path))
		result[path] = {"node": str(node.get_instance_id()), "parent": str(node.get_parent().get_instance_id()),
			"index": node.get_index(), "material": str(node.material_override.get_instance_id())}
	for node: Node in scene.find_children("*", "CollisionShape3D", true, false):
		result[_stable_path(node)] = {"node": str(node.get_instance_id()), "parent": str(node.get_parent().get_instance_id()),
			"shape": str(node.shape.get_instance_id())}
	return result

func _references() -> Dictionary:
	var result: Dictionary = super._references()
	result["proxyNodeMaterialColliderIds"] = _proxy_ids()
	return result

func _neutral_material(material: ShaderMaterial) -> Dictionary:
	var values := {}
	for uniform: Dictionary in material.shader.get_shader_uniform_list():
		if str(uniform.name) != "rock_ao_vertex_count":
			values[str(uniform.name)] = _stable_value(material.get_shader_parameter(uniform.name))
	return {"shader": _stable_value(material.shader), "priority": material.render_priority, "values": _stable_value(values)}

func _persistent_properties() -> Array:
	var result: Array = []
	for path: String in request.proxyContract.meshRoots:
		var node: MeshInstance3D = scene.get_node(NodePath(path))
		var metadata := {}
		for key: StringName in node.get_meta_list():
			if key != &"progressive_visual_proxy":
				metadata[str(key)] = _stable_value(node.get_meta(key))
		result.append({"path": path, "transform": _json(node.transform), "layers": node.layers,
			"visible": node.visible, "shadow": node.cast_shadow, "metadata": _stable_value(metadata),
			"material": _neutral_material(node.material_override), "overlay": _material(node.material_overlay)})
	return result

func _record_snapshot(label: String) -> Dictionary:
	var result: Dictionary = super._record_snapshot(label)
	var ids := _proxy_ids()
	if persistent_ids.is_empty():
		persistent_ids = ids
	_check(ids == persistent_ids, "Proxy roots, parents, materials and collision object IDs survive " + label)
	var row := {"label": label, "ids": ids, "meshes": {}, "meshReplacementCount": controller.get("mesh_replacement_count")}
	for path: String in request.proxyContract.meshRoots:
		var node: MeshInstance3D = scene.get_node(NodePath(path))
		var prefix: Variant = node.material_override.get_shader_parameter("rock_ao_vertex_count")
		row.meshes[path] = {"meshId": str(node.mesh.get_instance_id()), "proxyMarker": node.get_meta("progressive_visual_proxy", false),
			"vertexCount": node.mesh.surface_get_array_len(0), "indexCount": node.mesh.surface_get_array_index_len(0),
			"aoPrefix": prefix, "aoAppliedMarker": node.get_meta("rock_occlusion_applied", false)}
	proxy_observations.append(row)
	return result

func _reference_geometry() -> void:
	super._reference_geometry()
	# Bind the offline source-buffer proof to real original PackedScene resources.
	for proxy: Dictionary in request.proxyContract.references:
		for ref: Dictionary in request.expected.referenceScenes:
			if ref.resource != proxy.entry:
				continue
			var packed := ResourceLoader.load(ref.file, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
			var container := packed.instantiate()
			var original: MeshInstance3D = container.get_node(NodePath(proxy.target))
			var raw: Dictionary = original.mesh.get("_surfaces")[0]
			for key: String in proxy.originalBuffers:
				var info: Dictionary = proxy.originalBuffers[key]
				_check(_sha(raw[key]) == info.sha256, "Actual original raw buffer equals pinned source " + proxy.target + "/" + key)
				raw_source_checks.append({"target": proxy.target, "buffer": key, "sha256": _sha(raw[key])})
			container.free()

func _check_geometry(paths: Array) -> void:
	var ordinary: Array = []
	for path: String in paths:
		if path not in request.proxyContract.meshRoots or proxy_core_checked:
			ordinary.append(path)
	if not proxy_core_checked and "ContinuousMeadow" in paths:
		for ref: Dictionary in request.proxyContract.references:
			_check(FileAccess.get_sha256(ref.file) == ref.sha256, "Pinned independent core proxy scene")
			var packed := ResourceLoader.load(ref.file, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
			var container := packed.instantiate()
			var expected: MeshInstance3D = container.get_node(NodePath(ref.target))
			var actual: MeshInstance3D = scene.get_node(NodePath(ref.target))
			_check(actual.get_meta("progressive_visual_proxy", false), "Explicit initial visual proxy marker " + ref.target)
			_check(_same_json(_geometry(actual, ref.target != "ContinuousMeadow"), _geometry(expected, ref.target != "ContinuousMeadow")),
				"Initial proxy exact raw/decoded geometry, AO, material and colliders " + ref.target)
			container.free()
		var rock: MeshInstance3D = scene.get_node("SolidLimestoneGeology")
		_check(int(rock.material_override.get_shader_parameter("rock_ao_vertex_count")) == 70386, "Initial compact AO prefix exactly 70386")
		_check(rock.get_meta("rock_occlusion_applied", false), "Original selected AO remains preapplied, not rebaked")
		proxy_core_checked = true
	super._check_geometry(ordinary)

func _inflight_probe(index: int, path: String) -> void:
	var count: int = controller.get("mesh_replacement_count")
	var ids := _proxy_ids()
	await super._inflight_probe(index, path)
	_check(controller.get("mesh_replacement_count") == count and _proxy_ids() == ids,
		"In-flight duplicate cannot replace a proxy mesh or its node")

func _apply_group(group: Dictionary) -> void:
	if group.get("meshOnlyRoots", []).is_empty():
		var count: int = controller.get("mesh_replacement_count")
		await super._apply_group(group)
		_check(controller.get("mesh_replacement_count") == count, "Ordinary root/texture group does not count as mesh-only")
		return
	var index := int(group.index)
	phase = "chunk-%d" % index
	await _exercise_phase(index)
	var before := _state()
	var kept := _persistent_properties()
	var ids := _proxy_ids()
	var before_meshes := {}
	for path: String in group.meshOnlyRoots:
		var node: MeshInstance3D = scene.get_node(NodePath(path))
		_check(node.get_meta("progressive_visual_proxy", false), "Mesh upgrade starts from explicit proxy")
		before_meshes[path] = str(node.mesh.get_instance_id())
	var root_count: int = controller.get("replacement_count")
	var mesh_count: int = controller.get("mesh_replacement_count")
	var revision: int = weather.get("reflection_revision")
	var event_start := events.size()
	var started := Time.get_ticks_usec()
	_inflight_probe.call_deferred(index, str(group.file))
	await controller.call(request.controllerMethod, index, str(group.file))
	cpu[phase] = {"applyAwaitMs": float(Time.get_ticks_usec() - started) / 1000.0, "includesFrameWaits": true, "meshOnly": true}
	_check(controller.get("applied_count") == index + 1 and not controller.get("busy") and str(controller.get("last_error")).is_empty(), "Mesh-only group actually completes")
	_check(controller.get("replacement_count") == root_count, "Mesh-only is not a root replacement")
	_check(controller.get("mesh_replacement_count") == mesh_count + 2, "Exactly two mesh-only assignments")
	_check(ids == _proxy_ids() and _same_json(kept, _persistent_properties()), "Only mesh/AO-prefix/proxy-marker change; live state retained")
	_check(before == _state(), "Mesh-only retains live weather and contact shadows")
	_check(int(weather.get("reflection_revision")) == revision, "Non-final mesh-only group does not recapture reflection")
	var after_meshes := {}
	for path: String in group.meshOnlyRoots:
		var node: MeshInstance3D = scene.get_node(NodePath(path))
		after_meshes[path] = str(node.mesh.get_instance_id())
		_check(after_meshes[path] != before_meshes[path], "Mesh really changes while root survives " + path)
		_check(not node.has_meta("progressive_visual_proxy"), "Only proxy marker removed " + path)
		for event: Dictionary in events.slice(event_start):
			_check(event.path != path and not str(event.path).begins_with(path + "/"), "No root/child add/remove for mesh-only " + path)
	_check(int(scene.get_node("SolidLimestoneGeology").material_override.get_shader_parameter("rock_ao_vertex_count")) == 317556,
		"Full exact AO prefix restored to 317556")
	super._check_geometry(group.meshOnlyRoots)
	_record_snapshot(phase)
	var after_events := events.size()
	await controller.call(request.controllerMethod, index, str(group.file))
	_check(events.size() == after_events and controller.get("mesh_replacement_count") == mesh_count + 2,
		"Completed mesh duplicate is inert")
	for path: String in after_meshes:
		_check(str(scene.get_node(NodePath(path)).mesh.get_instance_id()) == after_meshes[path], "Duplicate retains actual restored mesh")
	mesh_commits.append({"index": index, "beforeMeshIds": before_meshes, "afterMeshIds": after_meshes,
		"rootMaterialColliderIdsRetained": ids == _proxy_ids(), "rootEventsAdded": events.size() - event_start})

func _finish() -> void:
	if is_instance_valid(controller):
		_check(proxy_core_checked, "Explicit first-core proxy branch audited")
		_check(controller.get("mesh_replacement_count") == 2, "Final mesh-only count two")
		_check(mesh_commits.size() == 1, "Exactly one observed two-mesh group")
		_check(_proxy_ids() == persistent_ids, "Final all original collision object IDs still live")
		super._check_geometry(request.proxyContract.meshRoots)
	var detail := {"schema": "progressive-independent-proxy-v1", "proxyContract": request.get("proxyContract", {}),
		"observations": proxy_observations, "meshCommits": mesh_commits, "originalRawBufferChecks": raw_source_checks,
		"status": "PASS_CPU_STRUCTURAL_ONLY" if errors.is_empty() else "FAIL", "errors": errors,
		"limitations": ["Headless native only: no initial-proxy visual or Web first-paint acceptance.",
			"Full mesh is compared exactly; proxy uses explicit separately pinned selected-AO geometry, never full-geometry signatures."]}
	var target := output_path.get_base_dir().path_join("proxy-observations.json")
	_check(not FileAccess.file_exists(target), "Fresh proxy evidence only")
	var file := FileAccess.open(target, FileAccess.WRITE)
	file.store_string(JSON.stringify(detail, "\t", true, true) + "\n")
	file.close()
	super._finish()
