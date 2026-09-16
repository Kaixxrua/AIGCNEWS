extends "E:/Projects/Godot-Octopath2/artifacts/startup-v135/support/candidate-01/audit-integrated06.gd"
## Actual compiled cache overlay, retaining every earlier complete-scene check.
var static_rows: Array = []

func _record_snapshot(label: String) -> Dictionary:
	var snapshot: Dictionary = super._record_snapshot(label)
	var records: Array = JSON.parse_string(FileAccess.get_file_as_string(support_spec.staticCaptureReport)).records
	var state: Dictionary = scene.get_meta("_meadow_static_geometry_cache_v135", {})
	_check(state.get("valid", false) and state.get("hits", []).size() == 17 and state.get("misses", []).is_empty(),
		"All seventeen exact-context static caches used in actual compiled scene")
	var rows: Array = []
	for record: Dictionary in records:
		var node := scene.get_node(NodePath(str(record.key).trim_prefix(str(record.kind) + "-"))) as MeshInstance3D
		if not _check(node != null, "Cached original node exists"):
			continue
		var fields := {}
		var helper: Script = load("res://scripts/meadow_static_geometry_cache.gd")
		for key: String in helper.FIELDS[record.kind]:
			fields[key] = node.get_meta(key)
		_check(_sha(var_to_bytes(fields)) == record.fieldsSha256, "Exact original metadata " + str(record.key))
		_check(_sha(var_to_bytes(node.mesh.get("_surfaces"))) == record.rawStorageSha256, "Exact original raw mesh " + str(record.key))
		_check(_sha(var_to_bytes(node.mesh.surface_get_arrays(0))) == record.arraysSha256, "Exact decoded geometry " + str(record.key))
		rows.append({"key": record.key, "rawStorageSha256": _sha(var_to_bytes(node.mesh.get("_surfaces"))),
			"fieldsSha256": _sha(var_to_bytes(fields)), "meshId": str(node.mesh.get_instance_id()),
			"materialId": str(node.material_override.get_instance_id())})
	static_rows.append({"label": label, "hits": state.get("hits", []), "meshes": rows})
	return snapshot

func _finish() -> void:
	var file := FileAccess.open(output_path.get_base_dir().path_join("static-cache-observations.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"status": "PASS_EXACT_STATIC_CACHE_NATIVE" if errors.is_empty() else "FAIL",
		"errors": errors, "snapshots": static_rows, "limitations": ["Native exact-context cache evidence only; Web cache hits and CPU saving not measured."]}, "\t", true, true) + "\n")
	file.close()
	super._finish()
