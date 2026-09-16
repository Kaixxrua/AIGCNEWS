extends SceneTree
## Same actual shader, strength 0/1/0. No main scene or global-state changes.
const SOURCE := "res://shaders/meadow_limestone.gdshader"
const SHA := "fb26bc08f6d39ce63d80346bef6d1e14b11740954127daeb1e294b6fdba4120e"
const EPS := 2.0 / 255.0
const SIZE := Vector2i(128, 128)
var viewport: SubViewport
var card: MeshInstance3D
var camera: Camera3D
var material: ShaderMaterial
var done := false
var records: Array = []

func _initialize() -> void:
	root.disable_3d = true
	create_timer(90.0).timeout.connect(_timeout)
	_run.call_deferred()

func _timeout() -> void:
	if not done:
		push_error("ROCK_PLANES: FAIL timeout/runtime-aborted")
		quit(1)

func _check(ok: bool, message: String) -> bool:
	if not ok:
		push_error("ROCK_PLANES: FAIL " + message)
		quit(1)
	return ok

func _texture(value: float, alpha: float = 1.0) -> ImageTexture:
	var image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	image.fill(Color(value, value, value, alpha))
	return ImageTexture.create_from_image(image)

func _mesh(normal: Vector3, biased: bool, turf: float, scale_value: float) -> ArrayMesh:
	var tangent := Vector3.UP.cross(normal).normalized() if absf(normal.y) < .95 else Vector3.RIGHT
	var up := normal.cross(tangent).normalized()
	var vertices := PackedVector3Array(); var normals := PackedVector3Array()
	var corners := PackedVector2Array([Vector2(-1,-1), Vector2(1,-1), Vector2(1,1), Vector2(-1,1)])
	var biases := [.35, .70, .90, .50]
	for i in range(4):
		vertices.append((tangent * corners[i].x + up * corners[i].y) * 2.0 * scale_value)
		normals.append((normal + tangent * float(biases[i])).normalized() if biased else normal)
	var arrays := []; arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices; arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = PackedVector2Array([Vector2(0,1), Vector2(1,1), Vector2(1,0), Vector2(0,0)])
	arrays[Mesh.ARRAY_TEX_UV2] = PackedVector2Array([Vector2.ONE, Vector2.ONE, Vector2.ONE, Vector2.ONE])
	arrays[Mesh.ARRAY_COLOR] = PackedColorArray([Color(turf,.94,1,1), Color(turf,.94,1,1), Color(turf,.94,1,1), Color(turf,.94,1,1)])
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0,2,1,0,3,2])
	var mesh := ArrayMesh.new(); mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh

func _capture(strength: float) -> Image:
	material.set_shader_parameter("rock_plane_strength", strength)
	for frame in range(4): await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()

func _delta(a: Color, b: Color) -> float:
	return maxf(absf(a.r-b.r), maxf(absf(a.g-b.g), absf(a.b-b.b)))

func _compare(a: Image, b: Image) -> Dictionary:
	var mean_a := 0.0; var mean_b := 0.0; var maximum := 0.0; var mean_delta := 0.0; var peak := 0.0
	for y in range(32,96):
		for x in range(32,96):
			var ca := a.get_pixel(x,y); var cb := b.get_pixel(x,y)
			if not _check(Vector4(ca.r,ca.g,ca.b,ca.a).is_finite() and Vector4(cb.r,cb.g,cb.b,cb.a).is_finite(), "Finite RGB"):
				return {}
			mean_a += ca.get_luminance(); mean_b += cb.get_luminance()
			var difference := _delta(ca,cb); maximum = maxf(maximum,difference); mean_delta += difference
			peak = maxf(peak,maxf(_delta(ca,Color.BLACK),_delta(cb,Color.BLACK)))
	return {"before":mean_a/4096.0, "after":mean_b/4096.0, "max_delta":maximum, "mean_delta":mean_delta/4096.0, "peak":peak}

func _run() -> void:
	if not _check(DisplayServer.get_name() != "headless" and not ProjectSettings.get_setting("rendering/shading/overrides/force_vertex_shading",false), "Real fragment GPU required"): return
	if not _check(FileAccess.get_sha256(SOURCE).to_lower() == SHA, "Frozen candidate source"): return
	var fingerprints := {}
	for path: String in [SOURCE,"res://shaders/meadow_palette.gdshaderinc","res://shaders/meadow_surface.gdshaderinc","res://shaders/meadow_mineral.gdshaderinc","res://shaders/meadow_sunbreak.gdshaderinc"]:
		fingerprints[path] = FileAccess.get_sha256(path)
		if not _check(not str(fingerprints[path]).is_empty(), "Source/include exists"): return
	var code := FileAccess.get_file_as_string(SOURCE)
	for uniform: String in ["meadow_clock","meadow_night"]:
		var declaration := "global uniform float " + uniform + ";"
		if not _check(code.count(declaration) == 1, "One isolated global " + uniform): return
		code = code.replace(declaration,"uniform float " + uniform + ";")
	material = ShaderMaterial.new(); material.shader = Shader.new(); material.shader.code = code
	for uniform: String in ["limestone_texture","meadow_texture"]: material.set_shader_parameter(uniform,_texture(.65))
	material.set_shader_parameter("escarpment_texture",_texture(.04,0.0))
	material.set_shader_parameter("sunbreak_strength",0.0); material.set_shader_parameter("meadow_clock",0.0)
	viewport = SubViewport.new(); viewport.size = SIZE; viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS; root.add_child(viewport)
	var env := Environment.new(); env.background_mode = Environment.BG_COLOR; env.background_color = Color.BLACK
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR; env.ambient_light_color = Color.WHITE; env.ambient_light_energy = .2
	env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED; env.fog_enabled = false
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR; env.tonemap_exposure = 1.0
	var world := WorldEnvironment.new(); world.environment = env; viewport.add_child(world)
	card = MeshInstance3D.new(); card.position = Vector3(0,4,-40); card.material_override = material
	card.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF; viewport.add_child(card)
	camera = Camera3D.new(); camera.projection = Camera3D.PROJECTION_ORTHOGONAL; viewport.add_child(camera); camera.make_current()
	var key := DirectionalLight3D.new(); key.rotation_degrees = Vector3(-34,72,0)
	key.light_color = Color.WHITE; key.light_energy = 1.4; key.shadow_enabled = false; viewport.add_child(key)
	# name, vertex-normal bias, night, prefix, turf metadata, expected-change
	var modes := [["aligned",false,0.0,true,0.0,true],["biased",true,0.0,true,0.0,true],
		["half",true,.5,true,0.0,true],["night",true,1.0,true,0.0,false],
		["near_night",true,.999,true,0.0,false],["near_day",true,.001,true,0.0,true],
		["prefix0",true,0.0,false,0.0,false],["turf_tag",true,0.0,true,1.0,false]]
	var cases := []
	for face: Array in [["uphill",Vector3(0,.8,.6)],["front",Vector3.BACK],["side",Vector3.RIGHT]]:
		for mode: Array in modes: cases.append([face[0],face[1],mode,1.0])
	cases.append(["cap1",Vector3.UP,["aligned",false,0.0,true,1.0,false],1.0])
	cases.append(["tiny_area",Vector3.BACK,["biased",true,0.0,true,0.0,false],.001])
	var endpoints := {}
	print("ROCK_PLANES_FIXTURE: private128x128 ROI32,32,64,64; solid mineral/meadow .65; face alpha0; dry geometry, visibility1, UV2=1; same shader strength0/1/0; fixed white key+ambient for ALL night values; source-color and normals change together")
	print("ROCK_PLANES_SOURCES: " + JSON.stringify(fingerprints))
	for test: Array in cases:
		var normal: Vector3 = test[1]; var mode: Array = test[2]; var scale_value: float = test[3]
		card.mesh = _mesh(normal,mode[1],mode[4],scale_value)
		camera.size = 5.0*scale_value; camera.near = .0001; camera.far = 100
		camera.position = card.position + normal*7.0*scale_value
		camera.look_at(card.position,Vector3.UP if absf(normal.y)<.95 else Vector3.BACK)
		material.set_shader_parameter("rock_ao_vertex_count",4 if mode[3] else 0)
		material.set_shader_parameter("meadow_night",mode[2])
		var off := await _capture(0.0); var on := await _capture(1.0); var restored := await _capture(0.0)
		for sample: Image in [off,on,restored]:
			if not _check(sample != null and not sample.is_empty() and sample.get_size()==SIZE,"Valid readback"): return
		var record := _compare(off,on); var repeat := _compare(off,restored)
		if not _check(not record.is_empty() and not repeat.is_empty(),"Completed readback comparison"): return
		var response: bool = float(record.max_delta)>=EPS if mode[5] else float(record.max_delta)<=EPS
		var continuity := 0.0
		if mode[0] in ["biased","night"] and scale_value==1.0: endpoints[str(test[0])+str(mode[0])] = on
		if mode[0] in ["near_day","near_night"]:
			var reference := str(test[0]) + ("biased" if mode[0]=="near_day" else "night")
			if not _check(endpoints.has(reference),"Exact endpoint captured before continuity check"): return
			var close := _compare(on,endpoints[reference])
			if not _check(not close.is_empty(),"Endpoint comparison completed"): return
			continuity = float(close.max_delta)
		var passed := response and float(repeat.max_delta)<=EPS and continuity<=EPS and float(record.before)>.02 and float(record.after)>.02 and float(record.peak)<.98
		record.merge({"case":str(test[0])+"_"+str(mode[0]),"night":mode[2],"response_pass":response,"restored_error":repeat.max_delta,"endpoint_error":continuity,"pass":passed})
		records.append(record); print("ROCK_PLANES_CASE: "+JSON.stringify(record))
		if not _check(passed,str(record.case)): return
	for path: String in fingerprints:
		if not _check(FileAccess.get_sha256(path)==fingerprints[path],"Source/include unchanged during run"): return
	if not _check(records.size()==26,"All 26 cases completed"): return
	done=true; viewport.free(); print("ROCK_PLANES: PASS; controlled gate/response/endpoint/area-fallback tests only; NOT normal-vector proof, actual-rock seams, visual quality or full-scene night parity"); quit(0)
