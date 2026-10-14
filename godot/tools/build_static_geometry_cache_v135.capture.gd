extends RefCounted
## Included only in the offline capture overlay, never in shipping entries.
const CONTRACT = preload("res://scripts/meadow_static_geometry_cache.gd")
static var pending: Dictionary = {}
static var records: Array = []

static func digest(data: PackedByteArray) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(data)
	return hash.finish().hex_encode()

static func load_cached(scene: Node3D, node: MeshInstance3D, kind: String, inputs: Array) -> Dictionary:
	var key := kind + "-" + str(node.name)
	assert(not pending.has(key))
	pending[key] = {"context": CONTRACT.context(scene, node, inputs), "started": Time.get_ticks_usec()}
	return {}

static func finish(scene: Node3D, node: MeshInstance3D, kind: String, extra: Dictionary = {}) -> void:
	var key := kind + "-" + str(node.name)
	var elapsed := Time.get_ticks_usec() - int(pending[key].started)
	var fields := {}
	for field: String in CONTRACT.FIELDS[kind]:
		assert(node.has_meta(field))
		fields[field] = node.get_meta(field)
	var data := {"kind": kind, "context": pending[key].context, "mesh": node.mesh, "fields": fields, "extra": extra}
	assert(not data.context.is_empty())
	var directory := str(Engine.get_main_loop().get_meta("static_cache_output"))
	assert(directory.begins_with("E:/Projects/Godot-Octopath2/artifacts/startup-v135/static-cache/"))
	var path := directory.path_join(key + ".res")
	assert(not FileAccess.file_exists(path))
	var resource := Resource.new()
	resource.set_meta("record", data)
	assert(ResourceSaver.save(resource, path, ResourceSaver.FLAG_COMPRESS) == OK)
	var loaded := ResourceLoader.load(path, "Resource", ResourceLoader.CACHE_MODE_IGNORE)
	var actual: Dictionary = loaded.get_meta("record")
	var raw_before := var_to_bytes(node.mesh.get("_surfaces"))
	var raw_after := var_to_bytes(actual.mesh.get("_surfaces"))
	assert(raw_before == raw_after, "Cached surface storage must reload byte-exact")
	assert(var_to_bytes(node.mesh.surface_get_arrays(0)) == var_to_bytes(actual.mesh.surface_get_arrays(0)))
	assert(var_to_bytes(fields) == var_to_bytes(actual.fields) and data.context == actual.context)
	assert(var_to_bytes(extra) == var_to_bytes(actual.extra))
	records.append({"key": key, "kind": kind, "path": path, "elapsedOriginalFunctionMs": float(elapsed) / 1000.0,
		"rawStorageSha256": digest(raw_before), "arraysSha256": digest(var_to_bytes(node.mesh.surface_get_arrays(0))),
		"fieldsSha256": digest(var_to_bytes(fields)), "contextSha256": digest(data.context),
		"extraSha256": digest(var_to_bytes(extra)), "resourceSha256": FileAccess.get_sha256(path),
		"vertices": node.mesh.surface_get_array_len(0), "indexCount": node.mesh.surface_get_array_index_len(0),
		"rawReloadExact": true})
	pending.erase(key)
