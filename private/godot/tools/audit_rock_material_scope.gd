extends SceneTree
## Actual cached scene material references, not a GPU/geometry equivalence test.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const LIMESTONE := "res://shaders/meadow_limestone.gdshader"
var failed := false
var checks := 0
var references := 0
var unique_materials := {}
var positive_owners := {}
var target: MeshInstance3D
var target_material: ShaderMaterial

func _initialize() -> void:
	root.disable_3d = true
	_run.call_deferred()

func _expect(ok: bool, message: String) -> bool:
	checks += 1
	if not ok:
		failed = true
		push_error("ROCK_MATERIAL_SCOPE: FAIL " + message)
	return ok

func _preflight() -> bool:
	_expect(not OS.get_cmdline_user_args().has("--rebuild-static"), "No rebake in audit")
	# A helper source edit invalidates these caches. Refuse main's expensive
	# automatic rebuild; main must bake once before running this audit.
	for group: String in CACHE.GROUPS:
		var packed := load(CACHE.DIRECTORY + group + ".scn") as PackedScene
		if not _expect(packed != null, "Existing cache " + group): return false
		var container := packed.instantiate()
		_expect(container.get_meta("cache_version", "") == CACHE.VERSION and container.get_meta("source_signature", "") == CACHE.signature(), "Current cache " + group)
		container.free()
	return not failed

func _count(material: ShaderMaterial) -> int:
	var value: Variant = material.get_shader_parameter("rock_ao_vertex_count")
	if value == null:
		_expect(FileAccess.get_file_as_string(LIMESTONE).count("uniform int rock_ao_vertex_count = 0;") == 1, "Explicit shader zero default, not int(null)")
		return 0
	if not _expect(typeof(value) == TYPE_INT and int(value) >= 0, "Nonnegative integer prefix count"):
		return -1
	return int(value)

func _limestone(material: Material) -> bool:
	var shader_material := material as ShaderMaterial
	return shader_material != null and shader_material.shader != null and shader_material.shader.resource_path == LIMESTONE

func _reference(node: Node, slot: String, material: Material) -> bool:
	var visited := {}
	while material != null:
		var id := material.get_instance_id()
		if not _expect(not visited.has(id), "No cyclic material next_pass chain"): return false
		visited[id] = true
		if _limestone(material):
			var count := _count(material as ShaderMaterial)
			references += 1; unique_materials[id] = true
			if count > 0: positive_owners[node.get_path()] = true
			print("ROCK_MATERIAL_REFERENCE: node=%s slot=%s material_id=%d count=%d target_shared=%s" % [node.get_path(),slot,id,count,str(material == target_material)])
			_expect(count >= 0 and (node == target or count == 0), "Only SolidLimestoneGeology may reference a positive prefix: " + str(node.get_path()))
			if node != target:
				_expect(material != target_material, "Non-target must not share the tagged material instance")
		material = material.next_pass
		slot += "/next_pass"
	return not failed

func _verify(scene: Node3D) -> bool:
	target = scene.get_node_or_null("SolidLimestoneGeology") as MeshInstance3D
	if not _expect(target != null and target.mesh != null, "Actual target geometry exists"): return false
	target_material = target.material_override as ShaderMaterial
	if not _expect(_limestone(target_material), "Target uses limestone override"): return false
	var target_count := _count(target_material)
	_expect(target_count > 0 and target_count <= target.mesh.surface_get_array_len(0), "Target remains tagged; shared instance was NOT globally reset")
	for name: String in ["ScrubStoneSupports", "LedgeBreakupStones"]:
		var node := scene.get_node_or_null(NodePath(name)) as MeshInstance3D
		if not _expect(node != null and node.mesh != null, "Required support batch " + name): return false
		var material := node.material_override as ShaderMaterial
		if not _expect(_limestone(material), "Support retains limestone material " + name): return false
		_expect(material != target_material and _count(material) == 0, "Independent untagged support material " + name)
		# Duplicating then clearing the one count must retain all other parameters,
		# including texture resources, plane strength, and future shared settings.
		for entry: Dictionary in target_material.shader.get_shader_uniform_list():
			if entry.name != "rock_ao_vertex_count":
				_expect(material.get_shader_parameter(entry.name) == target_material.get_shader_parameter(entry.name), name + " preserves " + str(entry.name))
	for node: GeometryInstance3D in scene.find_children("*", "GeometryInstance3D", true, false):
		if _reference(node,"override",node.material_override) != true: return false
		if _reference(node,"overlay",node.material_overlay) != true: return false
		var mesh: Mesh
		if node is MeshInstance3D: mesh = node.mesh
		elif node is MultiMeshInstance3D and node.multimesh != null: mesh = node.multimesh.mesh
		if mesh != null:
			for surface in range(mesh.get_surface_count()):
				if _reference(node,"mesh_surface" + str(surface),mesh.surface_get_material(surface)) != true: return false
				if node is MeshInstance3D:
					if _reference(node,"surface_override" + str(surface),node.get_surface_override_material(surface)) != true: return false
	_expect(references >= 3 and positive_owners.size() == 1 and positive_owners.has(target.get_path()), "Nonempty scope; exactly one positive-prefix owner")
	_expect(_count(target_material) == target_count, "Target count unchanged by inspection")
	return not failed

func _run() -> void:
	if _preflight() != true or failed:
		quit(1); return
	var packed := load("res://scenes/main.tscn") as PackedScene
	if not _expect(packed != null, "Main scene exists"): quit(1); return
	var scene := packed.instantiate() as Node3D
	if not _expect(scene != null, "Main scene root"): quit(1); return
	root.add_child(scene); scene.process_mode = Node.PROCESS_MODE_DISABLED
	var completed: bool = _verify(scene)
	scene.free()
	_expect(completed, "All reference checks completed; runtime abort cannot PASS")
	print("ROCK_MATERIAL_SCOPE: %s checks=%d references=%d unique_materials=%d; geometry override/overlay, Mesh/MultiMesh surfaces and next_pass; NOT GPU pixels or collision equivalence" % ["FAIL" if failed else "PASS",checks,references,unique_materials.size()])
	quit(1 if failed else 0)
