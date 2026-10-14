extends Node
## Included only by the optional progressive lite pack. The original scene is frozen.
const MANIFEST := "res://progressive/manifest.json"
var meadow: Node3D
var manifest: Dictionary
var web: JavaScriptObject
var callback: JavaScriptObject
var applied_count := 0
var busy := false
var completed := false
var last_error := ""
var replacement_count := 0
var mesh_replacement_count := 0
var texture_replacement_count := 0

func setup(scene: Node3D) -> void:
	meadow = scene
	manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	assert(manifest.get("version") == 1 and manifest.get("chunks") is Array)
	meadow.get_node("RiverSurroundingsReflection").visible = false
	var focus: Node = meadow.camera.get_node_or_null("DepthAwareFocus")
	if focus != null:
		focus.visible = false
	if OS.has_feature("web"):
		web = JavaScriptBridge.get_interface("meadowStream")
		if web != null:
			callback = JavaScriptBridge.create_callback(_request)
			web.bind(JSON.stringify(manifest), callback)
	print("MEADOW_CORE_CONFIGURED: %d deferred chunks; actual world and weather active" % manifest.chunks.size())

func _request(arguments: Array) -> void:
	if arguments.size() != 2 or not (arguments[0] is float or arguments[0] is int):
		return
	var index := int(arguments[0])
	if float(arguments[0]) != float(index) or str(arguments[1]) != "/meadow-detail-%d.pck" % index:
		return
	# Leave the JavaScript -> Godot callback before mounting/uploading any resource.
	apply_chunk.call_deferred(index, str(arguments[1]))

func _reject(index: int, message: String, release_busy: bool = true) -> void:
	last_error = message
	if release_busy:
		busy = false
	push_warning("MEADOW_DETAIL_REJECTED: " + message)
	if web != null:
		web.applied(index, false, message)

func apply_chunk(index: int, path: String) -> void:
	# One live commit owns its final draw acknowledgement. A duplicate callback
	# while it yields must neither clear busy nor acknowledge that draw early.
	if busy:
		return
	if index < 0 or index >= manifest.chunks.size():
		_reject(index, "细节序号无效")
		return
	if index < applied_count:
		if web != null:
			web.applied(index, true, "")
		return
	if index != applied_count:
		_reject(index, "细节接入顺序不一致", false)
		return
	busy = true
	var chunk: Dictionary = manifest.chunks[index]
	if FileAccess.get_sha256(path) != chunk.sha256:
		_reject(index, "细节文件校验失败")
		return
	if not ProjectSettings.load_resource_pack(path, false):
		_reject(index, "细节资源包无法打开")
		return
	# Load and validate every replacement before replacing any live object.
	var staged: Array[Dictionary] = []
	for part: Dictionary in chunk.get("scenes", []):
		var parent := meadow.get_node_or_null(NodePath(part.get("parent", ".")))
		var packed := ResourceLoader.load(part.resource, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE) as PackedScene
		if parent == null or packed == null:
			_free_staged(staged)
			_reject(index, "细节场景或接入位置缺失")
			return
		var container := packed.instantiate()
		if part.get("rootScene", false):
			var wrapper := Node3D.new()
			wrapper.add_child(container)
			container = wrapper
		var roots: Array = part.roots
		if container.get_child_count() != roots.size():
			container.free()
			_free_staged(staged)
			_reject(index, "细节场景数量不一致")
			return
		for label: String in roots:
			var old := parent.get_node_or_null(NodePath(label))
			var replacement := container.get_node_or_null(NodePath(label))
			var valid := old != null and replacement != null
			if part.get("meshOnly", false):
				valid = valid and old is MeshInstance3D and replacement is MeshInstance3D
				valid = valid and old.get_meta("progressive_visual_proxy", false)
				valid = valid and replacement.mesh != null and replacement.mesh.get_surface_count() > 0
				valid = valid and old.material_override is ShaderMaterial
			else:
				valid = valid and old.get_meta("progressive_placeholder", false)
			if not valid:
				container.free()
				_free_staged(staged)
				_reject(index, "细节替换目标不是待补齐占位")
				return
		staged.append({"container": container, "parent": parent, "roots": roots, "part": part})
	var upgrades: Array[Dictionary] = []
	for texture: Dictionary in chunk.get("textures", []):
		if texture.get("inPlace", false):
			var target := load(str(texture.source)) as CompressedTexture2D
			var file := FileAccess.open(str(texture.resource), FileAccess.READ)
			if target == null or file == null or file.get_buffer(4).get_string_from_ascii() != "GST2":
				_free_staged(staged)
				_reject(index, "渐进纹理或原纹理缺失")
				return
			file.get_32() # CTEX version; the offline builder pins the full payload.
			if file.get_32() != target.get_width() or file.get_32() != target.get_height():
				_free_staged(staged)
				_reject(index, "渐进纹理不能改变图集坐标")
				return
			upgrades.append({"target": target, "resource": texture.resource})
			continue
		var replacement := load(str(texture.resource)) as Texture2D
		if replacement == null:
			_free_staged(staged)
			_reject(index, "细节纹理缺失")
			return
		upgrades.append({"source": texture.source, "texture": replacement})
	for item: Dictionary in staged:
		for label: String in item.roots:
			var parent: Node = item.parent
			var old: Node = parent.get_node(NodePath(label))
			var replacement: Node = item.container.get_node(NodePath(label))
			if item.part.get("meshOnly", false):
				# The live root, collisions, material, weather and contact-shadow
				# references survive. Carriers contain only the exact final mesh.
				old.mesh = replacement.mesh
				var parameters: Dictionary = item.part.get("restoreShaderParameters", {}).get(label, {})
				for parameter: String in parameters:
					old.material_override.set_shader_parameter(parameter, parameters[parameter])
				for key: String in item.part.get("removeMetadata", []):
					old.remove_meta(key)
				mesh_replacement_count += 1
				await get_tree().process_frame
				continue
			var order := old.get_index()
			_clear_owners(replacement)
			item.container.remove_child(replacement)
			parent.remove_child(old)
			old.free()
			parent.add_child(replacement)
			parent.move_child(replacement, order)
			replacement_count += 1
			await get_tree().process_frame
		item.container.free()
	for upgrade: Dictionary in upgrades:
		if upgrade.has("target"):
			# Public Godot API replaces the RID's contents, retaining the actual
			# texture object, atlas dimensions and every live material/script ref.
			if upgrade.target.load(str(upgrade.resource)) != OK:
				_reject(index, "纹理升级失败，原场景仍可使用")
				return
			texture_replacement_count += 1
			await get_tree().process_frame
		else:
			_replace_texture_tree(meadow, str(upgrade.source), upgrade.texture)
	applied_count += 1
	last_error = ""
	if applied_count == manifest.chunks.size():
		_finish_details()
	# Only acknowledge after the new geometry has crossed a real render boundary.
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
	await get_tree().process_frame
	busy = false
	print("MEADOW_DETAIL_APPLIED: %d/%d; roots=%d; meshes=%d" % [applied_count, manifest.chunks.size(), replacement_count, mesh_replacement_count])
	if web != null:
		web.applied(index, true, "")

func _free_staged(staged: Array[Dictionary]) -> void:
	for item: Dictionary in staged:
		item.container.free()

func _clear_owners(node: Node) -> void:
	node.owner = null
	for child: Node in node.get_children():
		_clear_owners(child)

func _replace_texture(material: Material, path: String, texture: Texture2D) -> void:
	if material is ShaderMaterial:
		for parameter: Dictionary in material.shader.get_shader_uniform_list():
			var value: Variant = material.get_shader_parameter(parameter.name)
			if value is Texture2D and value.resource_path == path:
				material.set_shader_parameter(parameter.name, texture)
	elif material is BaseMaterial3D:
		for slot in range(BaseMaterial3D.TEXTURE_MAX):
			var value: Texture2D = material.get_texture(slot)
			if value != null and value.resource_path == path:
				material.set_texture(slot, texture)

func _replace_texture_tree(node: Node, path: String, texture: Texture2D) -> void:
	if node is GeometryInstance3D:
		_replace_texture(node.material_override, path, texture)
		_replace_texture(node.material_overlay, path, texture)
		if node is MeshInstance3D and node.mesh != null:
			for index in range(node.mesh.get_surface_count()):
				_replace_texture(node.mesh.surface_get_material(index), path, texture)
				_replace_texture(node.get_surface_override_material(index), path, texture)
	if node is WorldEnvironment and node.environment.sky != null:
		_replace_texture(node.environment.sky.sky_material, path, texture)
	for child: Node in node.get_children():
		_replace_texture_tree(child, path, texture)

func _finish_details() -> void:
	var weather := meadow.get_node("LivingWeather")
	var environment: Environment = meadow.get_node("WorldEnvironment").environment
	meadow.GROUND_ATMOSPHERE.sync_material(meadow.ground_material, environment, weather.night_blend)
	if mesh_replacement_count > 0:
		# Wildlife owns cached CPU support queries, separate from physics bodies.
		# Refresh them against the restored mesh without resetting paths or time.
		var wildlife: Node = meadow.get_node("LivingWildlife")
		wildlife.ground_surface = meadow.get_node("ContinuousMeadow").mesh.generate_triangle_mesh()
		wildlife.rock_surface = meadow.get_node("SolidLimestoneGeology").mesh.generate_triangle_mesh()
		for animal: Dictionary in wildlife.animals:
			animal.node.position = wildlife.ground_point(animal.point)
	# Do not recreate weather, lights or callbacks; preserve the user's live state.
	meadow.get_node("RiverSurroundingsReflection").visible = true
	weather._refresh_reflection()
	var focus: Node = meadow.camera.get_node_or_null("DepthAwareFocus")
	if focus != null:
		focus.visible = true
	completed = true
