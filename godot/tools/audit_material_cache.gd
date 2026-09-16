extends SceneTree
## Read-only preflight for MaterialOnly. Never instantiate main or call restore:
## restore() is allowed to rebuild stale geometry, which this path must reject.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const EXPECTED_GROUPS := ["terrain", "detail", "foothill", "riverbank", "brush"]

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	quit(0 if _verify() else 1)

func _verify() -> bool:
	if CACHE.GROUPS.size() != EXPECTED_GROUPS.size():
		return _fail("Expected exactly five current cache groups")
	# Source files must actually exist; a remapped/exported pack cannot establish
	# the authoring signature, and missing-file hashes must never count as valid.
	for path: String in CACHE.SOURCES:
		if not FileAccess.file_exists(path) or FileAccess.get_sha256(path).length() != 64:
			return _fail("Missing or unreadable signature source: " + path)
	var expected_signature: String = CACHE.signature()
	for group: String in EXPECTED_GROUPS:
		if not CACHE.GROUPS.has(group):
			return _fail("Missing current cache group: " + group)
		var path: String = CACHE.DIRECTORY + group + ".scn"
		if not FileAccess.file_exists(path):
			return _fail("Missing current cache file: " + path)
		var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		if packed == null:
			return _fail("Unreadable current cache file: " + path)
		# PackedScene metadata is available without constructing any nodes or
		# running scene scripts, physics, procedural builders or cache fallbacks.
		var state := packed.get_state()
		if state.get_node_count() == 0:
			return _fail("Empty current cache: " + path)
		var version: Variant = null
		var source_signature: Variant = null
		for property in range(state.get_node_property_count(0)):
			match str(state.get_node_property_name(0, property)):
				"metadata/cache_version":
					version = state.get_node_property_value(0, property)
				"metadata/source_signature":
					source_signature = state.get_node_property_value(0, property)
		if version != CACHE.VERSION or source_signature != expected_signature:
			return _fail("Stale cache %s: version %s / source_signature %s; expected %s / %s" % [
				path, version, source_signature, CACHE.VERSION, expected_signature])
		print("MEADOW_MATERIAL_CACHE_FILE: %s; version %s; source_signature %s" % [group, version, source_signature])
	if CACHE.signature() != expected_signature:
		return _fail("Geometry sources changed during cache verification")
	print("MEADOW_MATERIAL_CACHE_AUDIT: PASS; 5/5 current bundles; version %s; source_signature %s; metadata only, no scene construction or bake" % [
		CACHE.VERSION, expected_signature])
	return true

func _fail(message: String) -> bool:
	push_error("MaterialOnly cache preflight failed: " + message + "; no bake/export permitted. Refresh with an explicit full build.")
	return false
