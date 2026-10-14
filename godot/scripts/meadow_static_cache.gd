extends RefCounted
## Build-time compressed geometry, not a screenshot/background. Materials keep
## their live weather uniforms; the exact meshes and collisions are serialized.
const DIRECTORY := "res://assets/baked/v77/"
const VERSION := "meadow-77-1"
const SOURCES := ["res://scripts/meadow_scene.gd", "res://scripts/meadow_detail_builder.gd", "res://scripts/meadow_middle_brush.gd", "res://scripts/meadow_herb_modules.gd", "res://scripts/meadow_scrub_modules.gd",
	"res://scripts/meadow_foothill_builder.gd", "res://scripts/meadow_branch_geometry.gd", "res://scripts/meadow_city_builder.gd", "res://scripts/meadow_riverbank_builder.gd", "res://scripts/meadow_mountain_landform.gd", "res://scripts/meadow_static_cache.gd", "res://tools/bake_static_meadow.gd"]
const GROUPS := {
	"terrain": ["ContinuousMeadow"],
	"detail": ["SolidLimestoneGeology", "LivingMeadowUnderstory", "CreepingMeadowAndLedgeGrowth", "PropGroundStitches"],
	"foothill": ["CastleFoothillWoodland"],
	"riverbank": ["EmbeddedRiverbankStrata", "RootedRiparianCover"],
	"brush": ["MiddleMeadowBrush"]}

static func signature() -> String:
	var values := VERSION
	for path: String in SOURCES:
		values += FileAccess.get_sha256(path)
	return values.sha256_text()

static func restore(scene: Node3D, group: String) -> bool:
	if OS.get_cmdline_user_args().has("--rebuild-static"):
		return false
	var path := DIRECTORY + group + ".scn"
	if not ResourceLoader.exists(path):
		return false
	var start := Time.get_ticks_msec()
	var packed: PackedScene = load(path)
	var container := packed.instantiate()
	var valid: bool = container.get_meta("cache_version", "") == VERSION
	# Authoring runs fail closed after any geometry-source edit. Exported scripts
	# are compiled/remapped, so the export pipeline rebuilds and verifies first.
	if FileAccess.file_exists(SOURCES[0]):
		valid = valid and container.get_meta("source_signature", "") == signature()
	if not valid:
		container.free()
		print("MEADOW_STATIC_CACHE_STALE: ", group, "; rebuilding source geometry")
		return false
	assert(container.get_child_count() == GROUPS[group].size())
	for label: String in GROUPS[group]:
		var child := container.get_node(label)
		_clear_owners(child)
		container.remove_child(child)
		scene.add_child(child)
	container.free()
	print("MEADOW_STATIC_CACHE: %s loaded in %d ms; original geometry/materials/collision" % [group, Time.get_ticks_msec() - start])
	return true

static func _clear_owners(node: Node) -> void:
	node.owner = null
	for child in node.get_children():
		_clear_owners(child)
