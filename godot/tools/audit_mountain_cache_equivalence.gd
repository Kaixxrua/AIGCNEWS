extends SceneTree
## Compare serialized caches only. No main scene, procedural rebuild or writes.
const CACHE = preload("res://scripts/meadow_static_cache.gd")
const GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
	"brush": ["MiddleMeadowBrush"]}
var failed := false
var checks := 0
var meshes := 0
var shapes := 0
var channels := 0

func _initialize() -> void:
	_run.call_deferred()

func _expect(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		failed = true
		push_error("MEADOW_MOUNTAIN_CACHE_EQUIVALENCE: FAIL; " + label)

func _run() -> void:
	var baseline_dir := ProjectSettings.globalize_path("res://").path_join("../artifacts/v96/cache-v95-before").simplify_path()
	var signature: String = CACHE.signature()
	var frozen_files := {}
	# Freeze both inventories before loading: do not run alongside bake/export.
	for group: String in GROUPS:
		for path: String in [baseline_dir.path_join(group + ".scn"), CACHE.DIRECTORY + group + ".scn"]:
			_expect(FileAccess.file_exists(path), "Required bundle " + path)
			if FileAccess.file_exists(path):
				frozen_files[path] = FileAccess.get_sha256(path)
	if failed:
		quit(1)
		return
	var old_signature := ""
	for group: String in GROUPS:
		var old_path := baseline_dir.path_join(group + ".scn")
		var new_path: String = CACHE.DIRECTORY + group + ".scn"
		var old_packed := ResourceLoader.load(old_path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		var new_packed := ResourceLoader.load(new_path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		_expect(old_packed != null and new_packed != null, "Load independent old/new bundles " + group)
		if old_packed == null or new_packed == null:
			continue
		var before := old_packed.instantiate()
		var after := new_packed.instantiate()
		# Stay off-tree: no ready callbacks, physics world or main scene construction.
		var prior := str(before.get_meta("source_signature", ""))
		if old_signature.is_empty():
			old_signature = prior
		_expect(not prior.is_empty() and prior == old_signature, "Consistent frozen v95 signature " + group)
		_expect(after.get_meta("source_signature", "") == signature and prior != signature, "Actual rebake has current changed source signature " + group)
		_expect(before.get_meta("cache_version", "") == CACHE.VERSION and after.get_meta("cache_version", "") == CACHE.VERSION, "Unchanged cache format version " + group)
		_expect(before.get_child_count() == GROUPS[group].size() and after.get_child_count() == GROUPS[group].size(), "Exact expected root count " + group)
		for label: String in GROUPS[group]:
			_expect(before.has_node(NodePath(label)) and after.has_node(NodePath(label)), "Named cache member " + group + "/" + label)
		var mesh_start := meshes
		var shape_start := shapes
		_compare_node(before, after, group)
		before.free()
		after.free()
		print("MEADOW_MOUNTAIN_CACHE_PAIR: %s; compared_meshes=%d; compared_shapes=%d; old_file_sha=%s; new_file_sha=%s" % [group, meshes - mesh_start, shapes - shape_start, frozen_files[old_path], frozen_files[new_path]])
	_expect(meshes == 9, "All nine original meshes compared")
	_expect(shapes > 0, "Collision comparison is not empty")
	_expect(CACHE.signature() == signature, "Sources unchanged during comparison")
	for path: String in frozen_files:
		_expect(FileAccess.get_sha256(path) == frozen_files[path], "Bundle unchanged during comparison " + path)
	print("MEADOW_MOUNTAIN_CACHE_EQUIVALENCE_AUDIT: %s; bundles=5 meshes=%d collision_shapes=%d array_channels=%d checks=%d; old_signature=%s new_signature=%s; exact decoded arrays/topology/transforms/collisions; material/GPU/performance NOT tested" % ["FAIL" if failed else "PASS", meshes, shapes, channels, checks, old_signature, signature])
	quit(1 if failed else 0)

func _compare_node(before: Node, after: Node, label: String) -> void:
	_expect(before.get_class() == after.get_class() and before.name == after.name, "Node type/name " + label)
	_expect(before.get_script() == null and after.get_script() == null, "Cache contains no runtime scripts " + label)
	if before.get_class() != after.get_class():
		return
	if before is Node3D:
		_expect(before.transform == after.transform and before.visible == after.visible, "Exact local transform/visibility " + label)
	if before is MeshInstance3D:
		meshes += 1
		_expect(before.layers == after.layers and before.cast_shadow == after.cast_shadow and before.extra_cull_margin == after.extra_cull_margin, "Mesh render placement flags " + label)
		var a: Mesh = before.mesh
		var b: Mesh = after.mesh
		_expect(a is ArrayMesh and b is ArrayMesh, "Actual serialized ArrayMesh " + label)
		if a is ArrayMesh and b is ArrayMesh:
			_expect(a.get_surface_count() == b.get_surface_count() and a.get_surface_count() > 0, "Surface count " + label)
			_expect(a.get_blend_shape_count() == 0 and b.get_blend_shape_count() == 0, "Static cache has no omitted blend-shape geometry " + label)
			_expect(a.custom_aabb == b.custom_aabb, "Mesh custom bounds " + label)
			for surface in range(mini(a.get_surface_count(), b.get_surface_count())):
				_expect(a.surface_get_primitive_type(surface) == b.surface_get_primitive_type(surface) and a.surface_get_format(surface) == b.surface_get_format(surface), "Primitive/format " + label + "/" + str(surface))
				var old_arrays := a.surface_get_arrays(surface)
				var new_arrays := b.surface_get_arrays(surface)
				_expect(old_arrays.size() == Mesh.ARRAY_MAX and new_arrays.size() == Mesh.ARRAY_MAX, "Complete array layout " + label)
				for channel in range(mini(old_arrays.size(), new_arrays.size())):
					channels += 1
					_expect(typeof(old_arrays[channel]) == typeof(new_arrays[channel]) and old_arrays[channel] == new_arrays[channel], "Exact ALL elements " + label + "/surface=" + str(surface) + "/channel=" + str(channel))
	if before is CollisionObject3D:
		_expect(before.collision_layer == after.collision_layer and before.collision_mask == after.collision_mask and before.collision_priority == after.collision_priority, "Collision body filters " + label)
	if before is CollisionShape3D:
		shapes += 1
		_expect(before.disabled == after.disabled, "Collision enabled state " + label)
		var a: Shape3D = before.shape
		var b: Shape3D = after.shape
		_expect(a is ConcavePolygonShape3D and b is ConcavePolygonShape3D, "Expected triangle collision; unknown shape fails closed " + label)
		if a is ConcavePolygonShape3D and b is ConcavePolygonShape3D:
			_expect(a.get_faces() == b.get_faces() and a.backface_collision == b.backface_collision and a.margin == b.margin, "Exact collision faces/order/backfaces/margin " + label)
	_expect(before.get_child_count() == after.get_child_count(), "Child count " + label)
	for index in range(mini(before.get_child_count(), after.get_child_count())):
		_compare_node(before.get_child(index), after.get_child(index), label + "/" + str(before.get_child(index).name))
