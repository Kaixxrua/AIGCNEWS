extends SceneTree
## Material-only iteration must not silently move land, plants or collisions.
const CACHE = preload("res://scripts/meadow_static_cache.gd")

func _initialize() -> void:
	var checked := 0
	for group: String in CACHE.GROUPS:
		var baseline: PackedScene = load("res://assets/baked/v59/" + group + ".scn")
		var candidate: PackedScene = load("res://assets/baked/v60/" + group + ".scn")
		var a := baseline.instantiate()
		var b := candidate.instantiate()
		for label: String in CACHE.GROUPS[group]:
			var source: MeshInstance3D = a.get_node(label)
			var current: MeshInstance3D = b.get_node(label)
			assert(source.transform == current.transform)
			assert(source.mesh.get_faces() == current.mesh.get_faces(), "Material iteration changed geometry")
			var aa := source.mesh.surface_get_arrays(0)
			var bb := current.mesh.surface_get_arrays(0)
			for slot in [Mesh.ARRAY_VERTEX, Mesh.ARRAY_NORMAL, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV2, Mesh.ARRAY_INDEX]:
				assert(aa[slot] == bb[slot], "Material iteration changed source normals/colour/roots")
			checked += 1
		a.free()
		b.free()
	assert(checked == 6)
	print("MEADOW_SURFACE_GEOMETRY_AUDIT: PASS; all six v59/v60 meshes retain exact triangles, transforms, normals, colour and root fields")
	quit()
