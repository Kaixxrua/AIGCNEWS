extends Node
## Opt-in observer only. Bootstrap must attach this node to SceneTree.root,
## not to the boot scene that change_scene_to_file() replaces.
const STATE := &"_meadow_root_conform_cache_v135"
const CONTRACT_PATH := "res://scripts/meadow_static_geometry_cache.gd"
const MANIFEST := "res://progressive/root-conform/manifest.json"
const FIELDS := ["node.name", "node.transform", "scene.global_transform", "camera.global_transform",
	"camera.projection", "camera.size", "camera.fov", "camera.keep_aspect", "camera.near", "camera.far",
	"camera.frustum_offset", "camera.h_offset", "camera.v_offset", "viewport.visible_rect",
	"quad.size", "quad.center_offset", "texture.path", "texture.width", "texture.height", "material.uv_region", "inputs"]
var started_ms := 0
var reported := false

func _ready() -> void:
	set_process(false)
	# A second guard protects accidental unconditional bootstrap attachment.
	if not OS.has_feature("web") or not bool(JavaScriptBridge.eval("new URLSearchParams(location.search).get('root_cache_probe') === '1'")):
		queue_free()
		return
	started_ms = Time.get_ticks_msec()
	process_mode = Node.PROCESS_MODE_ALWAYS
	set_process(true)

func _process(_delta: float) -> void:
	if reported:
		return
	var scene := get_tree().current_scene as Node3D
	if scene != null and scene.has_meta(STATE):
		_finish(_inspect(scene))
	elif Time.get_ticks_msec() - started_ms >= 60000:
		_finish({"status": "timeout", "rootCache": null, "reason": "Actual scene root-cache metadata was not observed within 60 seconds."})

func _finish(report: Dictionary) -> void:
	reported = true
	set_process(false)
	report["schema"] = "meadow-root-cache-probe-v135-1"
	report["observation"] = "post-ready read-only snapshot; not a cache-call-time capture or startup benchmark"
	print("MEADOW_ROOT_CACHE_PROBE: " + JSON.stringify(report, "", true, true))
	queue_free()

func _inspect(scene: Node3D) -> Dictionary:
	var state: Variant = scene.get_meta(STATE)
	if not state is Dictionary or not state.get("hits") is Array or not state.get("misses") is Array:
		return {"status": "unavailable", "reason": "Unexpected existing cache-state schema."}
	var report := {"status": "observed", "rootCache": {"valid": state.get("valid", false),
		"hits": state.hits.size(), "misses": state.misses.size()}, "firstFailure": null}
	if state.misses.is_empty():
		return report
	var key := str(state.misses[0])
	var records: Dictionary = state.get("records", {})
	# Invalid dependency gates leave records empty. Read the pinned resource to
	# explain a miss, but NEVER call either cache's mutating _state()/restore().
	if not records.has(key):
		records = _read_records()
	var failure := {"name": key, "available": false}
	report.firstFailure = failure
	if not records.has(key) or not records[key] is Dictionary:
		failure["reason"] = "First miss has no readable pinned record; context comparison unavailable."
		return report
	var record: Dictionary = records[key]
	var encoded: Variant = record.get("context")
	if not encoded is PackedByteArray or encoded.is_empty() or encoded.size() > 65536:
		failure["reason"] = "Invalid or oversized record.context."
		return report
	var expected: Variant = bytes_to_var(encoded)
	if not expected is Array or expected.size() != FIELDS.size() or not record.get("wholeColumn") is bool:
		failure["reason"] = "Unknown context schema; no inferred comparison."
		return report
	var target := scene.get_node_or_null(NodePath(key)) as MeshInstance3D
	if target == null:
		failure["reason"] = "First missed node is absent."
		return report
	# Deliberately load only AFTER core mount and actual scene metadata exist.
	var contract := load(CONTRACT_PATH) as Script
	if contract == null or not contract.has_method("context"):
		failure["reason"] = "Actual core context implementation unavailable."
		return report
	var actual_bytes: PackedByteArray = contract.context(scene, target, [record.wholeColumn])
	failure["liveContextBytes"] = actual_bytes.size()
	failure["liveMeshClass"] = target.mesh.get_class() if target.mesh != null else "null"
	var replayed := ["inputs"] # The original call argument is not stored in the misses list.
	var derived: Array = []
	if actual_bytes.is_empty():
		var width: Variant = target.get_meta("art_width", null)
		var height: Variant = target.get_meta("art_height", null)
		var anchor: Variant = target.get_meta("art_anchor", null)
		if not (width is int or width is float) or not (height is int or height is float) or not anchor is Vector2:
			failure["reason"] = "No live QuadMesh or original art_width/art_height/art_anchor metadata."
			return report
		# The fallback has already consumed/replaced the original QuadMesh. This
		# private, detached node is NEVER added to the world or assigned to target.
		var sample := MeshInstance3D.new()
		var quad := QuadMesh.new()
		quad.size = Vector2(width, height)
		quad.center_offset = Vector3((0.5 - anchor.x) * width, (anchor.y - 0.5) * height, 0.0)
		sample.name = target.name
		sample.transform = target.transform
		sample.mesh = quad
		sample.material_override = target.material_override # Read-only shared reference.
		actual_bytes = contract.context(scene, sample, [record.wholeColumn])
		sample.free()
		derived = ["quad.size", "quad.center_offset"]
		failure["liveOriginalArtMetadata"] = {"art_width": width, "art_height": height, "art_anchor": _plain(anchor)}
	if actual_bytes.is_empty():
		failure["reason"] = "Context still unavailable with detached Quad replay."
		return report
	var actual: Variant = bytes_to_var(actual_bytes)
	if not actual is Array or actual.size() != FIELDS.size():
		failure["reason"] = "Actual core context schema changed."
		return report
	failure["available"] = true
	failure["replayedFieldsNotIndependentlyObserved"] = replayed
	failure["derivedFromLiveOriginalMetadata"] = derived
	failure["serializedContextEqual"] = encoded == actual_bytes
	failure["fields"] = _compare_fields(expected, actual, replayed, derived)
	failure["limit"] = "Post-ready observation, not the failed-call capture. Quad fields derive from live art metadata, not expected values; original inputs come from the record. No equality implies a cache hit."
	return report

func _read_records() -> Dictionary:
	if not FileAccess.file_exists(MANIFEST):
		return {}
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if not manifest is Dictionary or manifest.get("version") != 1 or manifest.get("count") != 50:
		return {}
	var path := str(manifest.get("resource", ""))
	if path != "res://progressive/root-conform/meshes.res" or FileAccess.get_sha256(path) != manifest.get("sha256"):
		return {}
	var resource := ResourceLoader.load(path, "Resource", ResourceLoader.CACHE_MODE_REUSE)
	if resource == null or not resource.get_meta("records", null) is Dictionary:
		return {}
	return resource.get_meta("records")

func _compare_fields(expected: Array, actual: Array, replayed: Array = [], derived: Array = []) -> Array:
	var rows: Array = []
	for i in range(FIELDS.size()):
		var before: Variant = _plain(expected[i])
		var after: Variant = _plain(actual[i])
		rows.append({"field": FIELDS[i], "expected": before, "actual": after,
			"expectedType": type_string(typeof(expected[i])), "actualType": type_string(typeof(actual[i])),
			"exactBytes": var_to_bytes(expected[i]) == var_to_bytes(actual[i]),
			"absoluteError": _error(before, after),
			"actualOrigin": "record-replay" if FIELDS[i] in replayed else ("derive-from-live-original-metadata" if FIELDS[i] in derived else "live-post-ready")})
	return rows

func _plain(value: Variant) -> Variant:
	match typeof(value):
		TYPE_VECTOR2, TYPE_VECTOR2I: return [value.x, value.y]
		TYPE_VECTOR3, TYPE_VECTOR3I: return [value.x, value.y, value.z]
		TYPE_VECTOR4, TYPE_VECTOR4I: return [value.x, value.y, value.z, value.w]
		TYPE_RECT2, TYPE_RECT2I: return [_plain(value.position), _plain(value.size)]
		TYPE_BASIS: return [_plain(value.x), _plain(value.y), _plain(value.z)]
		TYPE_TRANSFORM3D: return [_plain(value.basis), _plain(value.origin)]
		TYPE_ARRAY:
			var values: Array = []
			for item: Variant in value:
				values.append(_plain(item))
			return values
		TYPE_STRING_NAME: return str(value)
	return value

func _error(expected: Variant, actual: Variant) -> Variant:
	if (expected is int or expected is float) and (actual is int or actual is float):
		return absf(float(actual) - float(expected))
	if expected is Array and actual is Array and expected.size() == actual.size():
		var errors: Array = []
		for i in range(expected.size()):
			errors.append(_error(expected[i], actual[i]))
		return errors
	return null
