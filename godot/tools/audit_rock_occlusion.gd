extends SceneTree
## Off-tree cache/apply verification only. Frozen v103 snapshots in artifacts/v104.
## No main scene, procedural rebuild, AO rays, rendering or filesystem writes.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const AO = preload("res://scripts/meadow_rock_occlusion.gd")
const MARKER := "ROCK_OCCLUSION_AUDIT"
const BASE_SHA := {"detail": "3174faf6966959737038b14ca1551dc6b2f76f3dfa488334cb711a9541d591d1",
	"terrain": "a93ee30cb01bfbd4c223e7db322bb9526f00b49ae38b25d0d01eb9ef75590018"}
var failed := false
var checks := 0
var bundles: Array[Node] = []
var files := {}
var prefix := 0
var corners := 0
var changed := 0
var stats := {}

func _initialize() -> void:
	_run.call_deferred()

func _ok(value: bool, label: String) -> bool:
	checks += 1
	if not value:
		failed = true
		push_error(MARKER + ": FAIL; " + label)
	return value

func _run() -> void:
	quit(1) # Synchronous errors must never leave the default successful exit code.
	var completed: Variant = _verify()
	for node in bundles:
		if is_instance_valid(node): node.free()
	for path: String in files:
		_ok(FileAccess.get_sha256(path) == files[path], "Unchanged file during audit: " + path)
	var passed: bool = completed == true and not failed
	print(MARKER + ": " + JSON.stringify({"pass": passed, "checks": checks,
		"prefix_corners": corners, "prefix_vertices": prefix, "changed_blue": changed,
		"distribution": stats, "file_sha256": files,
		"scope": "cached geometry/collision/attributes and real helper.apply only; no AO-ray accuracy/GPU/visual/performance acceptance"}))
	if passed: print(MARKER + ": PASS")
	else: push_error(MARKER + ": FAIL; incomplete or failed checks")
	quit(0 if passed else 1)

func _freeze(path: String) -> bool:
	if not _ok(FileAccess.file_exists(path), "Required file: " + path): return false
	files[path] = FileAccess.get_sha256(path)
	return _ok(not str(files[path]).is_empty(), "Readable hash: " + path)

func _load_bundle(path: String) -> Node:
	var packed := ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
	if not _ok(packed != null, "Packed cache: " + path): return null
	var node := packed.instantiate()
	bundles.append(node) # Never add any cache node to this SceneTree.
	return node

func _signature(mesh: Mesh) -> String:
	# Independent serialization of the documented sidecar signature, not AO generation.
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(var_to_bytes(mesh.surface_get_primitive_type(0)))
	for channel in mesh.surface_get_arrays(0): hash.update(var_to_bytes(channel))
	return hash.finish().hex_encode()

func _clear_temporary_owners(node: Node, saved: Dictionary) -> void:
	saved[node] = node.owner
	node.owner = null
	for child in node.get_children(): _clear_temporary_owners(child, saved)

func _mesh_equal(a: Mesh, b: Mesh, blue_only: bool, label: String) -> bool:
	if not _ok(a is ArrayMesh and b is ArrayMesh, "ArrayMesh: " + label): return false
	if not _ok(a.get_surface_count() == 1 and b.get_surface_count() == 1, "One surface: " + label): return false
	_ok(a.get_blend_shape_count() == 0 and b.get_blend_shape_count() == 0, "No omitted blend shapes: " + label)
	_ok(a.custom_aabb == b.custom_aabb and a.get_aabb() == b.get_aabb(), "Exact bounds: " + label)
	_ok(a.surface_get_primitive_type(0) == b.surface_get_primitive_type(0), "Exact primitive: " + label)
	var aa := a.surface_get_arrays(0)
	var bb := b.surface_get_arrays(0)
	if not _ok(aa.size() == Mesh.ARRAY_MAX and bb.size() == Mesh.ARRAY_MAX, "Complete arrays: " + label): return false
	for channel in range(Mesh.ARRAY_MAX):
		if blue_only and channel == Mesh.ARRAY_COLOR:
			var ac: PackedColorArray = aa[channel]
			var bc: PackedColorArray = bb[channel]
			if not _ok(ac.size() == bc.size() and prefix > 0 and prefix < ac.size(), "Nonempty protected suffix: " + label): return false
			for i in range(ac.size()):
				var same: bool = ac[i] == bc[i] if i >= prefix else ac[i].r == bc[i].r and ac[i].g == bc[i].g and ac[i].a == bc[i].a
				if not _ok(same, "Exact non-AO colour: " + label + "/" + str(i)): return false
		else:
			if not _ok(typeof(aa[channel]) == typeof(bb[channel]) and aa[channel] == bb[channel], "Exact channel: " + label + "/" + str(channel)): return false
	return not failed

func _tree_equal(a: Node, b: Node, allow_blue: bool = false) -> bool:
	var label := str(a.name)
	if not _ok(a.name == b.name and a.get_class() == b.get_class(), "Exact node identity: " + label): return false
	if not _ok(a.get_script() == null and b.get_script() == null, "Inert cache nodes: " + label): return false
	if a is Node3D:
		_ok(a.transform == b.transform and a.visible == b.visible, "Exact transform/visibility: " + label)
	if a is MeshInstance3D:
		_ok(a.layers == b.layers and a.cast_shadow == b.cast_shadow and a.extra_cull_margin == b.extra_cull_margin, "Render flags: " + label)
		if not _mesh_equal(a.mesh, b.mesh, allow_blue and label == "SolidLimestoneGeology", label): return false
	if a is CollisionObject3D:
		_ok(a.collision_layer == b.collision_layer and a.collision_mask == b.collision_mask and a.collision_priority == b.collision_priority, "Collision filters: " + label)
	if a is CollisionShape3D:
		if not _ok(a.shape is ConcavePolygonShape3D and b.shape is ConcavePolygonShape3D, "Known collision shape: " + label): return false
		_ok(a.disabled == b.disabled and a.shape.backface_collision == b.shape.backface_collision and a.shape.get_faces() == b.shape.get_faces(), "Exact collision faces/state: " + label)
	if not _ok(a.get_child_count() == b.get_child_count(), "Exact children: " + label): return false
	for i in range(a.get_child_count()):
		if not _tree_equal(a.get_child(i), b.get_child(i), allow_blue): return false
	return not failed

func _verify() -> bool:
	var baseline := ProjectSettings.globalize_path("res://../artifacts/v104").simplify_path()
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--baseline-dir="): baseline = arg.trim_prefix("--baseline-dir=")
	if not _ok(not OS.get_cmdline_user_args().has("--rebuild-static") and not OS.get_cmdline_user_args().has("--bake-rock-occlusion"), "No bake flags"): return false
	var signature: String = CACHE.signature()
	for group: String in CACHE.GROUPS:
		if not _freeze(CACHE.DIRECTORY + group + ".scn"): return false
	for path: String in [baseline.path_join("detail.v103-before.scn"), baseline.path_join("terrain.v103-before.scn"), AO.DATA_PATH,
		"res://scripts/meadow_rock_occlusion.gd", "res://shaders/meadow_limestone.gdshader"]:
		if not _freeze(path): return false
	var pairs := {}
	for group: String in ["detail", "terrain"]:
		var old_path := baseline.path_join(group + ".v103-before.scn")
		if not _ok(files[old_path] == BASE_SHA[group], "Frozen v103 baseline hash " + group): return false
		var before := _load_bundle(old_path)
		var current := _load_bundle(CACHE.DIRECTORY + group + ".scn")
		if before == null or current == null: return false
		if not _ok(before.get_meta("cache_version", "") == CACHE.VERSION and current.get_meta("cache_version", "") == CACHE.VERSION, "Cache version " + group): return false
		if not _ok(current.get_meta("source_signature", "") == signature, "Main must finish current-signature static rebake: " + group): return false
		if not _tree_equal(before, current): return false
		pairs[group] = [before, current]
	var detail: Node = pairs.detail[1]
	var terrain_container: Node = pairs.terrain[1]
	var rock := detail.get_node_or_null("SolidLimestoneGeology") as MeshInstance3D
	var terrain := terrain_container.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	if not _ok(rock != null and terrain != null, "Actual required cached meshes"): return false
	if not _ok(rock.find_children("*", "CollisionShape3D", true, false).size() > 0 and terrain.find_children("*", "CollisionShape3D", true, false).size() > 0, "Nonempty rock and terrain collision coverage"): return false
	var rock_order := rock.get_index()
	var terrain_order := terrain.get_index()
	var original_mesh: ArrayMesh = rock.mesh
	var original_material := rock.material_override as ShaderMaterial
	if not _ok(original_material != null and original_material.shader != null, "Actual limestone ShaderMaterial"): return false
	var original_arrays := original_mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = original_arrays[Mesh.ARRAY_VERTEX]
	var indices: PackedInt32Array = original_arrays[Mesh.ARRAY_INDEX]
	corners = int(rock.get_meta("left_terrace_face_vertices", 0))
	if not _ok(corners == int(pairs.detail[0].get_node("SolidLimestoneGeology").get_meta("left_terrace_face_vertices", 0)), "Prefix boundary retained from frozen v103"): return false
	if not _ok(not indices.is_empty() and corners > 0 and corners % 3 == 0 and corners < indices.size(), "Indexed triangle-corner prefix, not vertex count"): return false
	var touched := {}
	for i in range(indices.size()):
		if not _ok(indices[i] >= 0 and indices[i] < vertices.size(), "Valid actual index " + str(i)): return false
		if i < corners: touched[indices[i]] = true
	prefix = touched.size()
	for i in range(prefix):
		if not _ok(touched.has(i), "Contiguous VERTEX_ID prefix " + str(i)): return false
	for i in range(corners, indices.size()):
		if not _ok(indices[i] >= prefix, "No suffix triangle shares AO prefix vertex " + str(i)): return false
	var file := FileAccess.open(AO.DATA_PATH, FileAccess.READ)
	if not _ok(file != null, "Readable sidecar"): return false
	var value: Variant = file.get_var(false)
	file.close()
	if not _ok(value is Dictionary, "Safe dictionary sidecar"): return false
	var data: Dictionary = value
	if not _ok(data.get("version", 0) == AO.VERSION and typeof(data.get("visibility")) == TYPE_PACKED_BYTE_ARRAY, "Sidecar protocol"): return false
	var visibility: PackedByteArray = data.visibility
	if not _ok(visibility.size() == prefix and data.get("prefix_vertices") == prefix and data.get("prefix_corners") == corners, "Exact two prefix units"): return false
	var original_signature := _signature(original_mesh)
	var terrain_signature := _signature(terrain.mesh)
	if not _ok(data.get("mesh_signature") == original_signature and data.get("terrain_signature") == terrain_signature, "Independent current mesh signatures"): return false
	if not _ok(data.get("visibility_sha256") == visibility.hex_encode().sha256_text(), "Sidecar payload digest"): return false
	var prior_hashes := [files[baseline.path_join("detail.v103-before.scn")], files[baseline.path_join("terrain.v103-before.scn")]]
	var current_hashes := [files[CACHE.DIRECTORY + "detail.scn"], files[CACHE.DIRECTORY + "terrain.scn"]]
	if not _ok(data.get("cache_file_sha256") == prior_hashes or data.get("cache_file_sha256") == current_hashes, "AO provenance matches one intact old/current cache pair"): return false
	var parameters := {}
	for entry: Dictionary in original_material.shader.get_shader_uniform_list(): parameters[entry.name] = original_material.get_shader_parameter(entry.name)
	if not _ok(parameters.has("rock_ao_vertex_count"), "Main shader exposes VERTEX_ID gate uniform"): return false
	var source := original_material.shader.code
	var declaration := RegEx.new()
	declaration.compile("uniform\\s+int\\s+rock_ao_vertex_count\\s*=\\s*0\\s*;")
	var gate := RegEx.new()
	gate.compile("VERTEX_ID\\s*<\\s*rock_ao_vertex_count\\s*\\?\\s*COLOR\\.b\\s*:\\s*1\\.0")
	if not _ok(declaration.search(source) != null and gate.search(source) != null, "Registered zero-default vertex gate; GPU behavior remains separate"): return false
	if not _ok(parameters.rock_ao_vertex_count == null or parameters.rock_ao_vertex_count == 0, "Source material not already enabled"): return false
	var temporary := Node3D.new()
	bundles.append(temporary)
	var saved_owners := {}
	_clear_temporary_owners(rock, saved_owners)
	_clear_temporary_owners(terrain, saved_owners)
	detail.remove_child(rock)
	terrain_container.remove_child(terrain)
	temporary.add_child(terrain)
	temporary.add_child(rock)
	if not _ok(not temporary.is_inside_tree() and AO.apply(temporary), "Real helper.apply on off-tree cached scene"): return false
	if not _ok(rock.mesh != original_mesh and rock.material_override != original_material, "Copy-on-apply resources"): return false
	if not _ok(rock.mesh.surface_get_material(0) == original_mesh.surface_get_material(0), "Surface material retained"): return false
	if not _mesh_equal(original_mesh, rock.mesh, true, "applied rock"): return false
	if not _ok(_signature(original_mesh) == original_signature and _signature(terrain.mesh) == terrain_signature, "Original rock resource and terrain untouched"): return false
	var material := rock.material_override as ShaderMaterial
	if not _ok(material != null and material.shader == original_material.shader, "Shader retained"): return false
	for key: String in parameters:
		if not _ok(original_material.get_shader_parameter(key) == parameters[key], "Original material parameter intact: " + key): return false
		if not _ok(material.get_shader_parameter(key) == (prefix if key == "rock_ao_vertex_count" else parameters[key]), "Copied material parameter: " + key): return false
	var colours: PackedColorArray = rock.mesh.surface_get_arrays(0)[Mesh.ARRAY_COLOR]
	var old_colours: PackedColorArray = original_arrays[Mesh.ARRAY_COLOR]
	var minimum := 255
	var maximum := 0
	var total := 0
	var occluded := 0
	for i in range(prefix):
		var expected := float(visibility[i]) / 255.0
		if not _ok(is_finite(colours[i].b) and colours[i].b >= 0.0 and colours[i].b <= 1.0 and absf(colours[i].b - expected) <= 0.0000001, "Finite decoded AO byte: " + str(i)): return false
		minimum = mini(minimum, visibility[i])
		maximum = maxi(maximum, visibility[i])
		total += visibility[i]
		occluded += int(visibility[i] < 255)
		changed += int(old_colours[i].b != colours[i].b)
	stats = {"minimum": minimum / 255.0, "maximum": maximum / 255.0, "mean": float(total) / (255.0 * prefix), "occluded_vertices": occluded}
	if not _ok(changed > 0 and occluded > 0 and minimum < maximum, "Nonempty, nonconstant AO distribution; not a quality threshold"): return false
	var applied_mesh: Mesh = rock.mesh
	var applied_material: Material = rock.material_override
	if not _ok(AO.apply(temporary) and rock.mesh == applied_mesh and rock.material_override == applied_material, "Second apply is idempotent"): return false
	temporary.remove_child(rock)
	temporary.remove_child(terrain)
	detail.add_child(rock)
	detail.move_child(rock, rock_order)
	terrain_container.add_child(terrain)
	terrain_container.move_child(terrain, terrain_order)
	for node: Node in saved_owners: node.owner = saved_owners[node]
	if not _tree_equal(pairs.detail[0], detail, true) or not _tree_equal(pairs.terrain[0], terrain_container): return false
	return _ok(CACHE.signature() == signature, "Source signature stable during audit")
