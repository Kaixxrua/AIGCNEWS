extends "E:/Projects/Godot-Octopath2/artifacts/startup-v135/support/candidate-01/integrated09-native-01/harness/audit-static.gd"
## Actual assembled09. No extra overlay, rebuilt main, or renderer/readiness signal.
var context_evidence: Dictionary = {}

func _record_snapshot(label: String) -> Dictionary:
	var snapshot: Dictionary = super._record_snapshot(label)
	_check(snapshot.inventory.colliderCount == 5, "Exactly five full original colliders in " + label)
	if label == "core":
		_check_proxy_context()
	return snapshot

func _check_proxy_context() -> void:
	var bounds: Array = []
	for ref: Dictionary in support_spec.proxy02References:
		_check(FileAccess.get_sha256(ref.file) == ref.sha256, "Pinned old proxy02 context reference")
		var packed := ResourceLoader.load(ref.file, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		var container := packed.instantiate()
		var previous := container.get_node(NodePath(ref.target)) as MeshInstance3D
		var actual := scene.get_node(NodePath(ref.target)) as MeshInstance3D
		bounds.append({"target": ref.target, "proxy02Aabb": _stable_value(previous.mesh.get_aabb()),
			"actual09Aabb": _stable_value(actual.mesh.get_aabb()),
			"sameAabb": previous.mesh.get_aabb() == actual.mesh.get_aabb(),
			"proxy02CustomAabb": _stable_value(previous.mesh.custom_aabb),
			"actual09CustomAabb": _stable_value(actual.mesh.custom_aabb)})
		container.free()
	# Original mountain code reads terrain.get_aabb() for ray origin/outside guards.
	# Recompute just these two originals against the actual09 proxy bounds and the
	# unchanged full support query, in the same process after the core snapshot.
	_check(FileAccess.get_sha256(support_spec.originalMountainSource.file) == support_spec.originalMountainSource.sha256,
		"Pinned optimized07 original mountain algorithm")
	var original: Script = load(str(support_spec.originalMountainSource.file))
	_check(original != null and original.can_instantiate(), "Original mountain source parses")
	var temporary := Node3D.new()
	temporary.name = "IndependentProxyBoundsQuery"
	scene.add_child(temporary)
	var mountains: Array = []
	var helper: Script = load("res://scripts/meadow_static_geometry_cache.gd")
	for label: String in ["DistantMountainRidge", "RightMountainRidge"]:
		var actual := scene.get_node(NodePath(label)) as MeshInstance3D
		var check_node := MeshInstance3D.new()
		check_node.name = label
		check_node.transform = actual.transform
		check_node.material_override = actual.material_override
		var quad := QuadMesh.new()
		quad.size = actual.get_meta("relief_base_size")
		quad.center_offset = actual.get_meta("relief_base_offset")
		check_node.mesh = quad
		temporary.add_child(check_node)
		var material_id := actual.material_override.get_instance_id()
		original.apply(scene, check_node)
		var expected_fields := {}
		var actual_fields := {}
		for field: String in helper.FIELDS.mountain:
			expected_fields[field] = actual.get_meta(field)
			actual_fields[field] = check_node.get_meta(field)
		var raw_exact := var_to_bytes(actual.mesh.get("_surfaces")) == var_to_bytes(check_node.mesh.get("_surfaces"))
		var arrays_exact := var_to_bytes(actual.mesh.surface_get_arrays(0)) == var_to_bytes(check_node.mesh.surface_get_arrays(0))
		var fields_exact := var_to_bytes(expected_fields) == var_to_bytes(actual_fields)
		_check(raw_exact and arrays_exact and fields_exact, "Cached original mountain equals actual09 original algorithm " + label)
		_check(actual.material_override.get_instance_id() == material_id, "Mountain comparison preserves live material")
		mountains.append({"name": label, "rawExact": raw_exact, "decodedArraysExact": arrays_exact,
			"allFourteenMetadataFieldsExact": fields_exact,
			"rawSha256": _sha(var_to_bytes(check_node.mesh.get("_surfaces"))),
			"fieldsSha256": _sha(var_to_bytes(actual_fields))})
		temporary.remove_child(check_node)
		check_node.free()
	scene.remove_child(temporary)
	temporary.free()
	context_evidence = {"bounds": bounds, "originalMountainRecomputations": mountains,
		"note": "Proxy mesh AABB is not in cache context. Its only direct use in these three cached algorithms is tested here; herb/village query faces stay exact full collision."}

func _finish() -> void:
	var file := FileAccess.open(output_path.get_base_dir().path_join("proxy-context-observations.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify({"status": "PASS_PROXY03_CACHE_CONTEXT" if errors.is_empty() else "FAIL",
		"errors": errors, "context": context_evidence,
		"limits": ["One headless process; no new capture, source build or browser measurement."]}, "\t", true, true) + "\n")
	file.close()
	super._finish()
