extends SceneTree
## Offline probe: select a LOD, measure geometric deviation, never publish it.
func _initialize() -> void:
	root.disable_3d = true
	run.call_deferred()
func run() -> void:
	quit(1)
	var args := OS.get_cmdline_user_args()
	if args.size()!=2 or not ProjectSettings.load_resource_pack(args[0]): return
	var rows:=[]
	for item in [["res://assets/baked/v77/terrain.scn","ContinuousMeadow"],["res://assets/baked/v77/detail.scn","SolidLimestoneGeology"]]:
		var node: Node = (load(item[0]) as PackedScene).instantiate()
		var mesh: ArrayMesh = node.get_node(NodePath(item[1])).mesh
		var arrays:=mesh.surface_get_arrays(0)
		var imported:=ImporterMesh.new()
		imported.add_surface(Mesh.PRIMITIVE_TRIANGLES,arrays)
		imported.generate_lods(30.0,0.0,[])
		var positions: PackedVector3Array=arrays[Mesh.ARRAY_VERTEX]
		var normal: PackedVector3Array=arrays[Mesh.ARRAY_NORMAL]
		var lods:=[]
		for level in range(mini(3,imported.get_surface_lod_count(0))):
			var indices:=imported.get_surface_lod_indices(0,level)
			var faces:=PackedVector3Array();faces.resize(indices.size())
			for i in range(indices.size()):faces[i]=positions[indices[i]]
			var query_arrays:=[];query_arrays.resize(Mesh.ARRAY_MAX)
			query_arrays[Mesh.ARRAY_VERTEX]=faces
			var query_mesh:=ArrayMesh.new();query_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,query_arrays)
			var query:=query_mesh.generate_triangle_mesh()
			var misses:=0;var max_offset:=0.0;var sum:=0.0;var samples:=0
			var step:=maxi(1,positions.size()/12000)
			for i in range(0,positions.size(),step):
				var axis:=normal[i].normalized()
				var hit:=query.intersect_ray(positions[i]+axis*1.0,-axis)
				if hit.is_empty():misses+=1;continue
				var distance:float=Vector3(hit.position).distance_to(positions[i])
				if distance>1.0:misses+=1;continue
				max_offset=maxf(max_offset,distance);sum+=distance;samples+=1
			lods.append({"level":level,"triangles":indices.size()/3,"sampled":samples,"misses":misses,"maxOffsetM":max_offset,"meanOffsetM":sum/maxi(1,samples)})
		rows.append({"mesh":item[1],"lods":lods,"notAcceptance":true})
		node.free()
	var path:String=args[1].replace("\\","/")
	if not path.contains("/artifacts/startup-v128/") or FileAccess.file_exists(path):return
	var file:=FileAccess.open(path,FileAccess.WRITE);file.store_string(JSON.stringify(rows,"\t"));file.close()
	print(JSON.stringify(rows));quit(0)
