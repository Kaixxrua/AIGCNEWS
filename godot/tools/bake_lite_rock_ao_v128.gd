extends SceneTree
## Run the existing AO application offline, then serialize its ACTUAL result.
## No shader, material values, visibility samples or ready gate are invented.

var fail := false
func check(ok: bool, reason: String) -> bool:
	if not ok:
		fail = true
		push_error("AO_PREAPPLY: " + reason)
	return ok

func _initialize() -> void:
	root.disable_3d = true
	work.call_deferred()

func raw_hash(mesh: Mesh) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes(mesh.get("_surfaces")))
	return context.finish().hex_encode()

func work() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if not check(args.size() == 1, "Request required"): return
	var req: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var target: String = str(req.output).replace("\\", "/").simplify_path()
	if not check(target.contains("/artifacts/startup-v128/ready-ao/") and not FileAccess.file_exists(target.path_join("detail.scn")), "New scoped output"): return
	if not check(FileAccess.get_sha256(req.pack) == req.sha256, "Pinned input pack"): return
	if not check(ProjectSettings.load_resource_pack(req.pack), "Mount input read-only"): return
	var packed: PackedScene = load("res://assets/baked/v77/detail.scn")
	var terrain_packed: PackedScene = load("res://assets/baked/v77/terrain.scn")
	var scene := packed.instantiate()
	var terrain_root := terrain_packed.instantiate()
	var original_terrain: MeshInstance3D = terrain_root.get_node("ContinuousMeadow")
	var terrain := MeshInstance3D.new()
	terrain.name = "ContinuousMeadow"
	terrain.mesh = original_terrain.mesh
	scene.add_child(terrain)
	var rock: MeshInstance3D = scene.get_node("SolidLimestoneGeology")
	var ao = load("res://scripts/meadow_rock_occlusion.gd")
	var started := Time.get_ticks_msec()
	if not check(ao.apply(scene), "Existing full AO validation/application succeeds"): return
	var expected_hash := raw_hash(rock.mesh)
	var expected_count: Variant = rock.material_override.get_shader_parameter("rock_ao_vertex_count")
	check(rock.get_meta("rock_occlusion_applied", false), "Actual application marker")
	var applied_ms := Time.get_ticks_msec() - started
	scene.remove_child(terrain)
	terrain.free()
	var baked := PackedScene.new()
	if not check(baked.pack(scene) == OK, "Pack real applied scene"): return
	if not check(ResourceSaver.save(baked, target.path_join("detail.scn"), ResourceSaver.FLAG_COMPRESS) == OK, "Save applied scene"): return
	var reloaded: PackedScene = ResourceLoader.load(target.path_join("detail.scn"), "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	var copy := reloaded.instantiate()
	var saved_rock: MeshInstance3D = copy.get_node("SolidLimestoneGeology")
	check(raw_hash(saved_rock.mesh) == expected_hash, "Native saved AO surface byte-exact")
	check(saved_rock.material_override.get_shader_parameter("rock_ao_vertex_count") == expected_count, "Saved actual AO count")
	check(saved_rock.get_meta("rock_occlusion_applied", false), "Saved applied marker")
	var new_terrain := MeshInstance3D.new()
	new_terrain.name = "ContinuousMeadow"
	new_terrain.mesh = original_terrain.mesh
	copy.add_child(new_terrain)
	started = Time.get_ticks_msec()
	check(ao.apply(copy), "Existing idempotent runtime path succeeds")
	var repeat_ms := Time.get_ticks_msec() - started
	check(raw_hash(saved_rock.mesh) == expected_hash, "Runtime does not change preapplied mesh")
	var result := {"passed": not fail, "rawSurfaceSha256": expected_hash, "prefixVertices": expected_count,
		"offlineApplyMs": applied_ms, "idempotentNativeApplyMs": repeat_ms,
		"sceneSha256": FileAccess.get_sha256(target.path_join("detail.scn"))}
	var file := FileAccess.open(target.path_join("native-proof.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(result, "\t") + "\n")
	file.close()
	copy.free()
	scene.free()
	terrain_root.free()
	print("AO_PREAPPLY: ", "PASS" if not fail else "FAIL")
	quit(1 if fail else 0)
