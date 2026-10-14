extends RefCounted
## Three distinct atlas props, each placed once, paired with actual local light.

const ATLAS = preload("res://assets/props/road-lanterns-v52.png")
const LIGHTS = preload("res://scripts/meadow_settlement_lights.gd")
const CROPS := [Rect2(65, 102, 349, 1022), Rect2(509, 440, 278, 692), Rect2(908, 123, 287, 994)]
const ROOTS := [Vector2(186, 1110), Vector2(644, 1115), Vector2(1002, 1100)]
const GLASS := [Vector4(326, 449, 30, 39), Vector4(631, 605, 28, 36), Vector4(1120, 423, 38, 30)]
const FEET := [Vector2(-8.5, -16.5), Vector2(24.0, -42.5), Vector2(27.0, -72.0)]
const HEIGHTS := [2.6, 1.5, 2.8]

static func build(meadow: Node3D) -> void:
	var atlas_size := Vector2(ATLAS.get_width(), ATLAS.get_height())
	for i in range(3):
		var region := Rect2(CROPS[i].position / atlas_size, CROPS[i].size / atlas_size)
		var anchor: Vector2 = (ROOTS[i] - CROPS[i].position) / CROPS[i].size
		var width: float = HEIGHTS[i] * CROPS[i].size.x / CROPS[i].size.y
		var card: MeshInstance3D = meadow._art("RoadLamp_%d" % i, ATLAS, FEET[i], width, anchor, -0.025, Color.WHITE, true, region)
		card.material_override.set_shader_parameter("edge_inset", 0.0)
		card.material_override.set_shader_parameter("painted_fill", 0.04)
		LIGHTS._install(card, [GLASS[i]], 2.1)
		var opening: Vector4 = GLASS[i]
		var glass_uv: Vector2 = (Vector2(opening.x, opening.y) - CROPS[i].position) / CROPS[i].size
		var quad: QuadMesh = card.mesh
		var local := quad.center_offset + Vector3((glass_uv.x - 0.5) * quad.size.x, (0.5 - glass_uv.y) * quad.size.y, 0)
		var centre: Vector3 = card.position + meadow.camera.global_basis * local
		var light := LIGHTS.add_source_pool(meadow, "RoadLampPool_%d" % i, centre + meadow.camera.global_basis.z * 0.18, 3.7, 9.0)
		light.set_meta("source_anchor", centre)
		var halo := MeshInstance3D.new()
		halo.name = "RoadLampHalo_%d" % i
		var halo_quad := QuadMesh.new()
		halo_quad.size = Vector2.ONE * (0.85 if i == 1 else 1.15)
		halo.mesh = halo_quad
		halo.position = centre + meadow.camera.global_basis.z * 0.21
		halo.material_override = LIGHTS._halo_material(0.48)
		halo.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		meadow.add_child(halo)
		meadow._shadow(FEET[i], Vector2(0.48, 0.42))
	print("MEADOW_ROAD_LIGHTS_READY: 3 unique lamps + 3 depth-tested halos + 3 real light pools")

static func audit(meadow: Node3D) -> void:
	var image := ATLAS.get_image()
	if image.is_compressed():
		assert(image.decompress() == OK)
	for i in range(3):
		var card: MeshInstance3D = meadow.get_node("RoadLamp_%d" % i)
		var light: OmniLight3D = meadow.get_node("RoadLampPool_%d" % i)
		var foot: Vector2 = FEET[i]
		assert(foot.distance_to(meadow.BOSS_CENTER) > 6.2, "Lamp must not occupy the Boss clearing")
		assert(meadow.distance_to_road(foot) > meadow.road_half_width(foot.y) + 0.20,
			"Lamp must stand beyond the walkable road")
		assert(absf(foot.x - meadow.river_center(foot.y)) > meadow.river_half_width(foot.y) + 1.0)
		assert(meadow.terrain_normal(foot.x, foot.y).y > 0.88)
		assert(absf(card.position.y - meadow.terrain_height(foot.x, foot.y)) < 0.04)
		assert(image.get_pixel(int(GLASS[i].x), int(GLASS[i].y)).a > 0.95, "Light must align to opaque lantern glass")
		assert(light.position.distance_to(light.get_meta("source_anchor")) < 0.20)
	print("MEADOW_ROAD_LIGHTS_AUDIT: 3/3 unique grounded sources; road/Boss/river clear; glass-aligned light pools")
