extends RefCounted
## CPU-only support for the isolated progressive pack. No rendering changes.

const CACHE_KEY := &"_meadow_progressive_support_v135"
const ALPHA_MANIFEST := "res://progressive/alpha-manifest.json"
const TARGETS := {
	"ContinuousMeadow": ["GroundCollision/CollisionShape3D", 552000,
		"8fbaac0868327ec8e52613b8e47032c0c5254badde1f72a239cbdcd7ae892b60"],
	"SolidLimestoneGeology": ["SolidLimestoneGeology_col/CollisionShape3D", 425853,
		"bef13d06e9abffccb8a27457d2a3fb6cf6cee08ff05af1013c1f17ef994d0316"]
}

static func _sha(data: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(data)
	return context.finish().hex_encode()

static func _invalidate(owner_ref: WeakRef, key: int, shape_id: int) -> void:
	var owner: Node = owner_ref.get_ref()
	if owner == null or not owner.has_meta(CACHE_KEY):
		return
	var cache: Dictionary = owner.get_meta(CACHE_KEY)
	if cache.has(key) and cache[key].shape_id == shape_id:
		cache.erase(key)
		if cache.is_empty():
			owner.remove_meta(CACHE_KEY)

static func surface(node: MeshInstance3D) -> TriangleMesh:
	if node == null or node.mesh == null:
		push_error("PROGRESSIVE_SUPPORT: query requires a mesh node")
		return null
	if not node.get_meta("progressive_visual_proxy", false) or not TARGETS.has(str(node.name)):
		return node.mesh.generate_triangle_mesh()
	var spec: Array = TARGETS[str(node.name)]
	var collider := node.get_node_or_null(NodePath(spec[0])) as CollisionShape3D
	var owner := node.get_parent()
	if owner == null or collider == null or collider.disabled or not collider.shape is ConcavePolygonShape3D:
		push_error("PROGRESSIVE_SUPPORT: named full collision shape is missing or invalid")
		return null
	if not owner is Node3D or collider.global_transform != node.global_transform or node.global_transform != owner.global_transform:
		push_error("PROGRESSIVE_SUPPORT: unverified collision/query coordinate space")
		return null
	# The cache belongs to this scene parent, not a global/static dictionary.
	var cache: Dictionary = owner.get_meta(CACHE_KEY, {})
	var key := node.get_instance_id()
	if cache.has(key):
		var cached: Dictionary = cache[key]
		if cached.node.get_ref() == node and cached.shape.get_ref() == collider.shape:
			return cached.surface
	var faces: PackedVector3Array = collider.shape.get_faces()
	if faces.size() != int(spec[1]) or _sha(faces.to_byte_array()) != str(spec[2]):
		push_error("PROGRESSIVE_SUPPORT: full-collider face identity mismatch")
		return null
	var query := TriangleMesh.new()
	if not query.create_from_faces(faces):
		push_error("PROGRESSIVE_SUPPORT: full-collider query construction failed")
		return null
	cache[key] = {"node": weakref(node), "shape": weakref(collider.shape),
		"shape_id": collider.shape.get_instance_id(), "surface": query}
	owner.set_meta(CACHE_KEY, cache)
	# In-place shape edits invalidate only this owner's entry; no scene is retained.
	collider.shape.changed.connect(_invalidate.bind(weakref(owner), key, collider.shape.get_instance_id()), CONNECT_ONE_SHOT)
	return query

static func image(texture: Texture2D) -> Image:
	if texture == null:
		push_error("PROGRESSIVE_SUPPORT: image query requires a texture")
		return null
	if not FileAccess.file_exists(ALPHA_MANIFEST):
		return texture.get_image()
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(ALPHA_MANIFEST))
	if not manifest is Dictionary or not manifest.get("textures", null) is Dictionary:
		push_error("PROGRESSIVE_SUPPORT: invalid CPU alpha manifest")
		return null
	if not manifest.textures.has(texture.resource_path):
		return texture.get_image()
	var spec: Variant = manifest.textures[texture.resource_path]
	if not spec is Dictionary:
		push_error("PROGRESSIVE_SUPPORT: invalid CPU alpha mapping")
		return null
	var path := str(spec.get("resource", ""))
	if not path.begins_with("res://progressive/alpha/") or not path.ends_with(".png") or ".." in path:
		push_error("PROGRESSIVE_SUPPORT: invalid CPU alpha resource path")
		return null
	var decoded := Image.new()
	if decoded.load_png_from_buffer(FileAccess.get_file_as_bytes(path)) != OK:
		push_error("PROGRESSIVE_SUPPORT: CPU alpha PNG decode failed")
		return null
	if decoded.get_width() != int(spec.get("width", 0)) or decoded.get_height() != int(spec.get("height", 0)) or decoded.get_format() != Image.FORMAT_LA8:
		push_error("PROGRESSIVE_SUPPORT: CPU alpha dimensions/LA8 contract mismatch")
		return null
	# Full pixel-alpha SHA correspondence is verified offline against pinned v134.
	# Rechecking millions of individual alpha bytes here would duplicate that CPU work.
	return decoded
