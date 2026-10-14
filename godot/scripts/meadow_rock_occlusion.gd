extends RefCounted
## Candidate geometry visibility, not a visual PASS. Bake explicitly OFFLINE;
## apply() performs hashes + one mesh upload only: no BVH construction or rays.
## Shader contract (main-owned): vertex varying = VERTEX_ID <
## rock_ao_vertex_count ? COLOR.b : 1.0. Keep the uniform default at zero.
const DATA_PATH := "res://assets/baked/v110/rock-occlusion.bin"
const VERSION := 1
const SKY_RAYS := 8
const LOCAL_RAYS := 12
const SKY_REACH := 6.0
const LOCAL_REACH := 1.6
const BIAS := 0.035

static func _signature(mesh: Mesh) -> String:
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(var_to_bytes(mesh.surface_get_primitive_type(0)))
	for channel in mesh.surface_get_arrays(0):
		hash.update(var_to_bytes(channel))
	return hash.finish().hex_encode()

static func _prefix_count(rock: MeshInstance3D, arrays: Array) -> int:
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var corners: int = rock.get_meta("left_terrace_face_vertices", 0)
	var indices := PackedInt32Array()
	if arrays[Mesh.ARRAY_INDEX] != null:
		indices = arrays[Mesh.ARRAY_INDEX]
	var total := vertices.size() if indices.is_empty() else indices.size()
	if corners <= 0 or corners % 3 != 0 or corners > total:
		push_error("ROCK_AO: invalid original triangle-corner prefix")
		return 0
	if indices.is_empty():
		return corners
	var used := PackedByteArray()
	used.resize(vertices.size())
	var limit := 0
	for i in range(corners):
		var vertex := indices[i]
		if vertex < 0 or vertex >= vertices.size():
			return 0
		used[vertex] = 1
		limit = maxi(limit, vertex + 1)
	for i in range(limit):
		if used[i] != 1:
			push_error("ROCK_AO: indexed left slice is not a contiguous vertex prefix")
			return 0
	for i in range(corners, indices.size()):
		if indices[i] < limit:
			push_error("ROCK_AO: vertex shared across protected prefix boundary")
			return 0
	return limit

static func _supported(rock: MeshInstance3D, terrain: MeshInstance3D) -> bool:
	return rock != null and terrain != null and rock.mesh is ArrayMesh and terrain.mesh is ArrayMesh \
		and rock.mesh.get_surface_count() == 1 and terrain.mesh.get_surface_count() == 1 \
		and rock.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES \
		and terrain.mesh.surface_get_primitive_type(0) == Mesh.PRIMITIVE_TRIANGLES \
		and rock.transform == Transform3D.IDENTITY and terrain.transform == Transform3D.IDENTITY \
		and rock.mesh.get_blend_shape_count() == 0

static func _local_surface(mesh: Mesh, bounds: AABB) -> TriangleMesh:
	# Actual triangles only, conservatively clipped by triangle AABB, never proxies.
	var faces := mesh.get_faces()
	var selected := PackedVector3Array()
	for i in range(0, faces.size(), 3):
		var triangle := AABB(faces[i], Vector3.ZERO).expand(faces[i + 1]).expand(faces[i + 2])
		if bounds.intersects(triangle.grow(0.0001)):
			selected.append(faces[i])
			selected.append(faces[i + 1])
			selected.append(faces[i + 2])
	if selected.is_empty():
		return null
	var query := TriangleMesh.new()
	query.create_from_faces(selected)
	return query

static func _blocked(queries: Array[TriangleMesh], origin: Vector3, direction: Vector3, reach: float) -> float:
	var distance := reach
	for surface in queries:
		var hit := surface.intersect_ray(origin, direction)
		if not hit.is_empty():
			var d := origin.distance_to(Vector3(hit.position))
			if d > BIAS * 0.5:
				distance = minf(distance, d)
	return 1.0 - smoothstep(0.0, reach, distance)

static func _visibility(queries: Array[TriangleMesh], p: Vector3, n: Vector3) -> Vector2:
	var origin := p + n * BIAS
	var tangent := (Vector3.RIGHT if absf(n.y) > 0.95 else Vector3.UP).cross(n).normalized()
	var bitangent := n.cross(tangent)
	var blocked := Vector2.ZERO
	for family in range(2):
		var count := SKY_RAYS if family == 0 else LOCAL_RAYS
		for i in range(count):
			var radius := sqrt((float(i) + 0.5) / count)
			var up := sqrt(1.0 - radius * radius)
			var angle := i * 2.39996323 + (0.73 if family == 0 else 0.0)
			var x := cos(angle) * radius
			var z := sin(angle) * radius
			var direction := Vector3(x, up, z) if family == 0 else tangent * x + n * up + bitangent * z
			blocked[family] += _blocked(queries, origin, direction, SKY_REACH if family == 0 else LOCAL_REACH) / count
	return Vector2.ONE - blocked

static func bake(rock: MeshInstance3D, terrain: MeshInstance3D) -> Dictionary:
	# Only the offline tool calls this. Never fall back to bake from apply().
	if not _supported(rock, terrain):
		push_error("ROCK_AO: requires the two original single-surface identity-space meshes")
		return {}
	var started := Time.get_ticks_msec()
	var arrays := rock.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var colours: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
	var count := _prefix_count(rock, arrays)
	if count == 0 or normals.size() != vertices.size() or colours.size() != vertices.size():
		return {}
	var bounds := AABB(vertices[0], Vector3.ZERO)
	for i in range(count):
		bounds = bounds.expand(vertices[i])
	var queries: Array[TriangleMesh] = []
	for mesh: Mesh in [rock.mesh, terrain.mesh]:
		var surface := _local_surface(mesh, bounds.grow(SKY_REACH + BIAS * 2.0))
		if surface != null:
			queries.append(surface)
	if queries.is_empty():
		return {}
	var bytes := PackedByteArray()
	bytes.resize(count)
	var samples := {} # Exact same position/normal only; no coarse spatial smoothing.
	var visibility_sum := Vector2.ZERO
	var minimum := 1.0
	var changed := 0
	for i in range(count):
		if not vertices[i].is_finite() or not normals[i].is_finite() or normals[i].length_squared() < 0.25:
			push_error("ROCK_AO: invalid source vertex/normal")
			return {}
		var n := normals[i].normalized()
		var key := [vertices[i], n]
		if not samples.has(key):
			samples[key] = _visibility(queries, vertices[i], n)
		var visibility: Vector2 = samples[key]
		var combined := clampf(visibility.x * 0.65 + visibility.y * 0.35, 0.0, 1.0)
		bytes[i] = clampi(roundi(combined * 255.0), 0, 255)
		visibility_sum += visibility
		minimum = minf(minimum, combined)
		changed += int(bytes[i] < 255)
		if i % 20000 == 0:
			print("ROCK_AO_BAKE_PROGRESS: %d/%d vertices; %d unique ray origins" % [i, count, samples.size()])
	var stats := {"prefix_vertices": count, "unique_samples": samples.size(), "ray_directions": samples.size() * (SKY_RAYS + LOCAL_RAYS),
		"occluded_vertices": changed, "minimum_visibility": minimum, "mean_sky_local": visibility_sum / count, "bake_ms": Time.get_ticks_msec() - started}
	return {"version": VERSION, "mesh_signature": _signature(rock.mesh), "terrain_signature": _signature(terrain.mesh),
		"prefix_corners": int(rock.get_meta("left_terrace_face_vertices")), "prefix_vertices": count,
		"visibility": bytes, "visibility_sha256": bytes.hex_encode().sha256_text(), "bounds": bounds,
		"sky_reach": SKY_REACH, "local_reach": LOCAL_REACH, "bias": BIAS, "stats": stats}

static func apply(scene: Node3D, path: String = DATA_PATH) -> bool:
	if OS.get_cmdline_user_args().has("--rebuild-static"):
		print("ROCK_AO_APPLY: skipped source-cache bake; original blue metadata retained")
		return true
	var rock := scene.get_node_or_null("SolidLimestoneGeology") as MeshInstance3D
	var terrain := scene.get_node_or_null("ContinuousMeadow") as MeshInstance3D
	if not _supported(rock, terrain):
		push_error("ROCK_AO: unsupported scene; original resources retained")
		return false
	if rock.has_meta("rock_occlusion_applied"):
		return true
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("ROCK_AO: missing offline data; no runtime bake")
		return false
	var value: Variant = file.get_var(false)
	file.close()
	if not value is Dictionary:
		return false
	var data: Dictionary = value
	if data.get("version", 0) != VERSION or typeof(data.get("visibility")) != TYPE_PACKED_BYTE_ARRAY:
		return false
	var arrays := rock.mesh.surface_get_arrays(0)
	var count := _prefix_count(rock, arrays)
	var bytes: PackedByteArray = data.visibility
	if count == 0 or bytes.size() != count or data.get("prefix_vertices", 0) != count \
		or data.get("prefix_corners", 0) != rock.get_meta("left_terrace_face_vertices") \
		or data.get("mesh_signature", "") != _signature(rock.mesh) \
		or data.get("terrain_signature", "") != _signature(terrain.mesh) \
		or data.get("visibility_sha256", "") != bytes.hex_encode().sha256_text():
		push_error("ROCK_AO: stale/mismatched data; original resources retained")
		return false
	var original_material := rock.material_override as ShaderMaterial
	var ready := false
	if original_material != null and original_material.shader != null:
		for uniform: Dictionary in original_material.shader.get_shader_uniform_list():
			if str(uniform.name) == "rock_ao_vertex_count":
				ready = true
	if not ready:
		push_error("ROCK_AO: main-owned shader must expose rock_ao_vertex_count (default 0)")
		return false
	# Rebuilding from decoded arrays would quantize the packed normals again.
	# Copy the serialized raw surface and patch only the stored RGBA8 blue byte.
	# This is the pinned engine's ArrayMesh storage path, not a buffer-update
	# call (those are intentionally no-ops in Godot's headless dummy renderer).
	var surfaces: Array = rock.mesh.get("_surfaces")
	if surfaces.size() != 1:
		push_error("ROCK_AO: expected one serialized surface")
		return false
	var raw: Dictionary = surfaces[0].duplicate()
	var attributes: PackedByteArray = raw.attribute_data.duplicate()
	var vertex_count: int = raw.vertex_count
	var format: int = raw.format
	var stride := RenderingServer.mesh_surface_get_format_attribute_stride(format, vertex_count)
	var offset := RenderingServer.mesh_surface_get_format_offset(format, vertex_count, Mesh.ARRAY_COLOR)
	if stride < 4 or offset < 0 or (count - 1) * stride + offset + 3 >= attributes.size():
		push_error("ROCK_AO: invalid packed colour layout; original resource retained")
		return false
	for i in range(count):
		attributes[i * stride + offset + 2] = bytes[i]
	raw.attribute_data = attributes
	var derived := ArrayMesh.new()
	derived.set("_surfaces", [raw])
	derived.custom_aabb = rock.mesh.custom_aabb
	derived.shadow_mesh = rock.mesh.shadow_mesh
	derived.resource_name = "LeftRockOcclusionV104"
	derived.surface_set_material(0, rock.mesh.surface_get_material(0))
	var applied_colours: PackedColorArray = derived.surface_get_arrays(0)[Mesh.ARRAY_COLOR]
	if absf(applied_colours[0].b - float(bytes[0]) / 255.0) > 0.0000001:
		push_error("ROCK_AO: packed update did not apply: first=%.9f expected=%.9f stride=%d offset=%d" % [applied_colours[0].b, float(bytes[0]) / 255.0, stride, offset])
		return false
	var material := original_material.duplicate() as ShaderMaterial
	material.set_shader_parameter("rock_ao_vertex_count", count)
	# Atomic resource swap: original cache mesh/material and existing collision stay intact.
	rock.mesh = derived
	rock.material_override = material
	rock.set_meta("rock_occlusion_applied", true)
	rock.set_meta("rock_occlusion_source_signature", data.mesh_signature)
	rock.set_meta("rock_occlusion_stats", data.get("stats", {}))
	print("ROCK_AO_APPLY: %d prefix blue values; cached data only; positions/indices/RGA/UV/UV2/nonprefix/collisions untouched; visual acceptance pending" % count)
	return true
