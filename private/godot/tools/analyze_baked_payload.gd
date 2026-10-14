extends SceneTree
## Offline, lossless RSCC repack. Default is dry-run; never instantiate main.
## --write-copies creates a NEW artifacts directory, never replaces source files.
## Terrain is deliberately excluded: far-sward records its whole-file SHA256.
const BLOCK_SIZE := 262144
const SOURCES := {
	"res://assets/baked/v77/detail.scn": "46b397bf8a09a712ce94f520874952ab7c048e6e7a1dc78e1c3fa6198700fff8",
	"res://assets/baked/v77/brush.scn": "b7e2627dc8bb1786530c5caf9fef99ba102d3cee4fea30e355fcb94f763befd9",
	"res://assets/baked/v77/foothill.scn": "089a44e1d190655001c796c68514460d60be87b8ffee05f7efb2f9ec11f47ff5",
	"res://assets/baked/v77/riverbank.scn": "979645039620c041e4f65a62b33eb7419811b8cfd959106ceb4da99a42994627",
	"res://assets/baked/v113/far-sward.scn": "308f3998727c0393a550f886cad691fdb761e4aad7d12cf9e2d47dcbd3091b92",
}
const TERRAIN := "res://assets/baked/v77/terrain.scn"
const TERRAIN_SHA := "b44e2c8c33fe4369d872fcb6ad3aa74180aac5463f18ae2eaadfb07ea4fc2771"

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _run() -> void:
	quit(1) # A script exception must not fall through to exit 0.
	if _execute():
		quit(0)

func _execute() -> bool:
	for argument: String in OS.get_cmdline_user_args():
		if argument not in ["--dry-run", "--write-copies"]:
			return _fail("Unknown argument: " + argument)
	var write := OS.get_cmdline_user_args().has("--write-copies")
	if write and OS.get_cmdline_user_args().has("--dry-run"):
		return _fail("Choose dry-run OR write-copies")
	if not _sources_unchanged():
		return false
	var output := ""
	if write:
		var stamp := Time.get_datetime_string_from_system().replace(":", "-")
		output = ProjectSettings.globalize_path("res://../artifacts/loading-v114/cache-repack-" + stamp + "-" + str(Time.get_ticks_usec())).simplify_path()
		if DirAccess.dir_exists_absolute(output) or FileAccess.file_exists(output):
			return _fail("Refusing existing output path: " + output)
		if DirAccess.make_dir_recursive_absolute(output) != OK:
			return _fail("Cannot create output directory: " + output)
	var rows: Array[Dictionary] = []
	var saved := 0
	for path: String in SOURCES:
		var original := FileAccess.get_file_as_bytes(path)
		if _sha(original) != SOURCES[path]:
			return _fail("Input changed while reading: " + path)
		var raw := _decode(original)
		if raw.is_empty():
			return false
		var candidate := _encode(raw)
		if candidate.is_empty() or _decode(candidate) != raw:
			return _fail("Full decompressed-byte comparison failed: " + path)
		var smaller := candidate.size() < original.size()
		# A non-beneficial compression result is copied unchanged, not published larger.
		var selected := candidate if smaller else original
		var row := {"source": path, "source_sha256": SOURCES[path], "raw_sha256": _sha(raw),
			"raw_bytes": raw.size(), "before_bytes": original.size(), "candidate_bytes": candidate.size(),
			"output_bytes": selected.size(), "saved_bytes": original.size() - selected.size(),
			"output_sha256": _sha(selected), "repacked": smaller, "raw_equal": true}
		if write:
			var target := output.path_join(path.get_file())
			if FileAccess.file_exists(target):
				return _fail("Refusing to overwrite: " + target)
			var file := FileAccess.open(target, FileAccess.WRITE)
			if file == null:
				return _fail("Cannot create copy: " + target)
			file.store_buffer(selected)
			file.flush()
			var io_error := file.get_error()
			file.close()
			if io_error != OK or FileAccess.get_sha256(target) != row.output_sha256:
				return _fail("Copy write/readback failed: " + target)
			# Inert resource load verifies Godot accepts the RSCC container. No nodes
			# are instantiated, no shader parameters changed, no ResourceSaver rewrite.
			var packed := ResourceLoader.load(target, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP) as PackedScene
			if packed == null or packed.get_state().get_node_count() == 0:
				return _fail("Godot rejected candidate copy: " + target)
			row["copy"] = target
			row["inert_load_ok"] = true
		saved += int(row.saved_bytes)
		rows.append(row)
		print("CACHE_REPACK_FILE: ", JSON.stringify(row))
	if not _sources_unchanged():
		return false
	var manifest := {"schema": "cache-repack-114-1", "mode": "copies" if write else "dry-run",
		"codec": "Godot default ZSTD", "block_size": BLOCK_SIZE, "saved_bytes": saved,
		"terrain_unchanged": true, "source_files_unchanged": true, "files": rows}
	if write:
		var file := FileAccess.open(output.path_join("manifest.json"), FileAccess.WRITE)
		if file == null:
			return _fail("Cannot create manifest; copies are NOT approved")
		file.store_string(JSON.stringify(manifest, "\t") + "\n")
		file.flush()
		var io_error := file.get_error()
		file.close()
		if io_error != OK:
			return _fail("Manifest write failed; copies are NOT approved")
	print("CACHE_REPACK: PASS mode=%s saved_bytes=%d output=%s; source/terrain untouched; no build/export/main scene" % [manifest.mode, saved, output])
	return true

func _sources_unchanged() -> bool:
	if FileAccess.get_sha256(TERRAIN) != TERRAIN_SHA:
		return _fail("Terrain differs from accepted v113; do not bypass far-sward dependency")
	for path: String in SOURCES:
		if FileAccess.get_sha256(path) != SOURCES[path]:
			return _fail("Source is not the recorded v113 baseline: " + path)
	return true

func _decode(bytes: PackedByteArray) -> PackedByteArray:
	if bytes.size() < 24 or bytes.slice(0, 4).get_string_from_ascii() != "RSCC" or bytes.slice(bytes.size() - 4).get_string_from_ascii() != "RSCC":
		_fail("Not an RSCC container")
		return PackedByteArray()
	var mode := bytes.decode_u32(4)
	var block := bytes.decode_u32(8)
	var length := bytes.decode_u32(12)
	if mode != FileAccess.COMPRESSION_ZSTD or block < 4096 or block > 1048576 or length <= 0 or length > 536870912:
		_fail("Unsupported RSCC codec/size")
		return PackedByteArray()
	var count := int(length / block) + 1
	var cursor := 16 + count * 4
	if cursor > bytes.size() - 4:
		_fail("Truncated RSCC table")
		return PackedByteArray()
	var result := PackedByteArray()
	for index in range(count):
		var size := bytes.decode_u32(16 + index * 4)
		var expected := mini(block, length - index * block)
		if cursor + size > bytes.size() - 4:
			_fail("Truncated RSCC block")
			return PackedByteArray()
		var decoded := PackedByteArray()
		if expected > 0:
			decoded = bytes.slice(cursor, cursor + size).decompress(expected, FileAccess.COMPRESSION_ZSTD)
		if decoded.size() != expected:
			_fail("RSCC block length mismatch")
			return PackedByteArray()
		result.append_array(decoded)
		cursor += size
	if cursor != bytes.size() - 4 or result.size() != length:
		_fail("RSCC payload/trailer mismatch")
		return PackedByteArray()
	return result

func _encode(raw: PackedByteArray) -> PackedByteArray:
	var count := int(raw.size() / BLOCK_SIZE) + 1
	var result := PackedByteArray()
	result.resize(16 + count * 4)
	result.encode_u32(0, 0x43435352) # Little endian ASCII RSCC.
	result.encode_u32(4, FileAccess.COMPRESSION_ZSTD)
	result.encode_u32(8, BLOCK_SIZE)
	result.encode_u32(12, raw.size())
	for index in range(count):
		var block := raw.slice(index * BLOCK_SIZE, mini(raw.size(), (index + 1) * BLOCK_SIZE))
		var compressed := block.compress(FileAccess.COMPRESSION_ZSTD)
		if not block.is_empty() and compressed.is_empty():
			_fail("ZSTD compression failed")
			return PackedByteArray()
		result.encode_u32(16 + index * 4, compressed.size())
		result.append_array(compressed)
	result.append_array("RSCC".to_ascii_buffer())
	return result

func _sha(bytes: PackedByteArray) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(bytes)
	return hash.finish().hex_encode()

func _fail(message: String) -> bool:
	push_error("CACHE_REPACK: " + message + "; original files never overwritten; incomplete copies must not be integrated")
	return false
