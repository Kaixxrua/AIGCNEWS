extends SceneTree
## Offline collision-only inspector and indexed-codec benchmark. Never saves a scene.

var failures := 0
var request: Dictionary
var output: String
var serial := 0

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _ok(condition: bool, message: String) -> bool:
	if not condition:
		failures += 1
		push_error("COLLISION_V128: " + message)
	return condition

static func _sha(data: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	if not data.is_empty():
		context.update(data)
	return context.finish().hex_encode()

func _write(name: String, data: PackedByteArray) -> String:
	var path := output.path_join(name)
	if not _ok(name == name.get_file() and not FileAccess.file_exists(path), "New flat artifact required"):
		return ""
	var file := FileAccess.open(path, FileAccess.WRITE)
	if not _ok(file != null, "Open artifact"):
		return ""
	file.store_buffer(data)
	file.close()
	_ok(FileAccess.get_sha256(path) == _sha(data), "Artifact readback")
	return path

func _stable(value: Variant, depth: int = 0) -> Variant:
	if not _ok(depth < 40, "Acyclic stored graph"):
		return null
	if value is Resource:
		_ok(value.get_script() == null, "No resource script execution")
		if value is Shader or value is Texture2D:
			return [value.get_class(), value.resource_path]
		var excluded := ["resource_path", "resource_scene_unique_id"]
		if value is ConcavePolygonShape3D:
			excluded.append("data") # Every corner is separately dumped and checked.
		return [value.get_class(), _properties(value, excluded, depth + 1)]
	if value is Dictionary:
		var result := {}
		for key: Variant in value:
			result[str(key)] = _stable(value[key], depth + 1)
		return result
	if value is Array:
		var result: Array = []
		for item: Variant in value:
			result.append(_stable(item, depth + 1))
		return result
	if value is Object:
		_ok(false, "Unexpected stored object")
		return null
	return [typeof(value), _sha(var_to_bytes(value))]

func _properties(object: Object, excluded: Array, depth: int = 0) -> Dictionary:
	var result := {}
	for property: Dictionary in object.get_property_list():
		if int(property.usage) & PROPERTY_USAGE_STORAGE and str(property.name) not in excluded:
			result[str(property.name)] = _stable(object.get(property.name), depth + 1)
	return result

func _snapshot(path: String) -> Dictionary:
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
	if not _ok(packed != null, "Load cache scene"):
		return {}
	var state := packed.get_state()
	for i in range(state.get_node_count()):
		_ok(state.get_node_instance(i) == null, "No nested scene execution")
		for j in range(state.get_node_property_count(i)):
			if state.get_node_property_name(i, j) == &"script":
				_ok(state.get_node_property_value(i, j) == null, "Inert cached nodes only")
	if failures:
		return {}
	var node := packed.instantiate() # Off-tree: no main, _ready or physics step.
	var tree := {}
	var collisions := {}
	var pending: Array[Node] = [node]
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		var label := str(node.get_path_to(current))
		var groups := current.get_groups()
		groups.sort()
		tree[label] = {"class": current.get_class(), "index": current.get_index(), "groups": groups,
			"owner": str(node.get_path_to(current.owner)) if current.owner != null else "",
			"properties": _properties(current, ["scene_file_path"])}
		if current is CollisionShape3D:
			if _ok(current.shape is ConcavePolygonShape3D, "Pinned concave collision shape"):
				var faces: PackedVector3Array = current.shape.get_faces()
				var data := faces.to_byte_array()
				collisions[label] = {"corners": faces.size(), "bytes": data.size(), "sha256": _sha(data),
					"path": _write("collision-%d.bin" % serial, data),
					"properties": _properties(current.shape, ["data", "resource_path", "resource_scene_unique_id"])}
				serial += 1
		for child: Node in current.get_children():
			pending.append(child)
	var result := {"tree": tree, "bundle": _stable(packed.get("_bundled")), "collisions": collisions}
	node.free()
	return result

static func decode_indexed(blob: PackedByteArray) -> PackedVector3Array:
	# Evaluated prototype only. No existing runtime script calls this function.
	if blob.size() < 20 or blob.slice(0, 4).get_string_from_ascii() != "CLI1":
		return PackedVector3Array()
	var corners := blob.decode_u32(4)
	var unique := blob.decode_u32(8)
	var size := blob.decode_u32(12)
	if corners == 0 or corners > 1006005 or corners % 3 != 0 or unique == 0 or unique > corners or size != unique * 12 + corners * 4:
		return PackedVector3Array()
	var raw := blob.slice(16).decompress(size, FileAccess.COMPRESSION_ZSTD)
	if raw.size() != size:
		return PackedVector3Array()
	var vertices := raw.slice(0, unique * 12).to_vector3_array()
	var indices := raw.slice(unique * 12).to_int32_array()
	var faces := PackedVector3Array()
	faces.resize(corners)
	for i in range(corners):
		if indices[i] < 0 or indices[i] >= unique:
			return PackedVector3Array()
		faces[i] = vertices[indices[i]]
	return faces

func _run() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if not _ok(args.size() == 2 and args[0] == "--request", "Python request required"):
		return
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(args[1]))
	if not _ok(value is Dictionary, "Request JSON"):
		return
	request = value
	output = str(request.output).replace("\\", "/").simplify_path()
	var allowed := str(request.allowed_root).replace("\\", "/").simplify_path()
	if not _ok(allowed.ends_with("/artifacts/startup-v128/collisions") and output.begins_with(allowed + "/")
		and ProjectSettings.globalize_path("res://").replace("\\", "/").begins_with(allowed + "/"), "Isolated artifact scope"):
		return
	var version := Engine.get_version_info()
	if not _ok(version.major == 4 and version.minor == 7 and version.patch == 2, "Godot4.7.2"):
		return
	if not _ok(ProjectSettings.load_resource_pack(request.reference_pack), "Read-only v127 dependency pack"):
		return
	var report := {"engine": version.string, "scenes": {}, "codecs": []}
	for item: Dictionary in request.get("files", []):
		_ok(FileAccess.get_sha256(item.path) == item.sha256, "Pinned input")
		if failures == 0:
			report.scenes[item.resource] = _snapshot(item.path)
		print("COLLISION_DUMP: ", item.resource)
	for item: Dictionary in request.get("codecs", []):
		var blob := FileAccess.get_file_as_bytes(item.path)
		var start := Time.get_ticks_usec()
		var faces := decode_indexed(blob)
		var decoded_usec := Time.get_ticks_usec() - start
		_ok(faces.size() == int(item.corners) and _sha(faces.to_byte_array()) == item.facesSha256, "Exact indexed decode")
		var shape := ConcavePolygonShape3D.new()
		start = Time.get_ticks_usec()
		shape.set_faces(faces)
		var shape_usec := Time.get_ticks_usec() - start
		_ok(_sha(shape.get_faces().to_byte_array()) == item.facesSha256, "Exact rebuilt collision shape")
		report.codecs.append({"path": item.path, "corners": faces.size(), "decodeUsec": decoded_usec,
			"setFacesUsec": shape_usec, "allCornerBytesExact": true})
	report.failures = failures
	if failures == 0:
		_write("inspection.json", (JSON.stringify(report, "\t") + "\n").to_utf8_buffer())
	print("COLLISION_V128_OFFLINE: ", "PASS" if failures == 0 else "FAIL")
	quit(0 if failures == 0 else 1)
