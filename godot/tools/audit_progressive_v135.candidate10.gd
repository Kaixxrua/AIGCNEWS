extends "E:/Projects/Godot-Octopath2/artifacts/startup-v135/support/candidate-01/integrated10-native-01/harness/audit-context.gd"
## Actual compiled10 main, controller and twelve chunks. No script replacement.
var root_ao_rows: Array = []
var root_ids: Dictionary = {}
var ao_initial_absent := false

func _run() -> void:
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	ao_initial_absent = not FileAccess.file_exists(str(spec.deferredAo.resource))
	_check(ao_initial_absent, "AO bin absent before loading actual main")
	await super._run()

func _record_snapshot(label: String) -> Dictionary:
	var snapshot: Dictionary = super._record_snapshot(label)
	var root_state: Dictionary = scene.get_meta("_meadow_root_conform_cache_v135", {})
	_check(root_state.get("valid", false) and root_state.get("hits", []).size() == 50 and root_state.get("misses", []).is_empty(),
		"Actual compiled main uses all fifty exact root caches " + label)
	_check(FileAccess.get_sha256(support_spec.rootCacheValidation.file) == support_spec.rootCacheValidation.sha256,
		"Pinned independent original-function root proof")
	var reference: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(support_spec.rootCacheValidation.file))
	var roots: Array = []
	for record: Dictionary in reference.records:
		var node := scene.get_node(NodePath(str(record.name))) as MeshInstance3D
		if not _check(node != null, "Cached root exists " + str(record.name)):
			continue
		var ids := {"node": str(node.get_instance_id()), "material": str(node.material_override.get_instance_id())}
		if not root_ids.has(record.name):
			root_ids[record.name] = ids
		_check(ids == root_ids[record.name], "Root node/live material IDs retained through chunks/day-night " + str(record.name))
		var raw := _sha(var_to_bytes(node.mesh.get("_surfaces")))
		var arrays := _sha(var_to_bytes(node.mesh.surface_get_arrays(0)))
		_check(raw == record.rawStorageSha256 and arrays == record.arraysSha256,
			"Root exact original raw/decoded mesh remains throughout " + str(record.name))
		roots.append({"name": record.name, "ids": ids, "rawStorageSha256": raw, "arraysSha256": arrays})
	var available := FileAccess.file_exists(str(support_spec.deferredAo.resource))
	var expected := int(controller.applied_count) > int(support_spec.deferredAo.chunk)
	_check(available == expected, "AO bin only available after actual chunk10 " + label)
	var ao := {"available": available, "afterChunk10": expected}
	if available:
		var bytes := FileAccess.get_file_as_bytes(str(support_spec.deferredAo.resource))
		ao["bytes"] = bytes.size()
		ao["sha256"] = _sha(bytes)
		_check(bytes.size() == int(support_spec.deferredAo.bytes) and ao.sha256 == support_spec.deferredAo.sha256,
			"Actual mounted AO bin reads exact original bytes " + label)
	root_ao_rows.append({"label": label, "rootHits": root_state.get("hits", []).size(),
		"oldCacheHits": scene.get_meta("_meadow_static_geometry_cache_v135").hits.size(), "ao": ao, "roots": roots})
	return snapshot

func _finish() -> void:
	_check(ao_initial_absent and root_ids.size() == 50, "Actual first core has no bin and retains fifty cached roots")
	var file := FileAccess.open(output_path.get_base_dir().path_join("root-ao-observations.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"status": "PASS_ROOT50_AND_DEFERRED_AO_ACTUAL10" if errors.is_empty() else "FAIL",
		"errors": errors, "aoInitiallyAbsent": ao_initial_absent, "snapshots": root_ao_rows,
		"limits": ["Actual stock-native full workflow, not browser-rendered or performance acceptance."]}, "\t", true, true) + "\n")
	file.close()
	super._finish()
