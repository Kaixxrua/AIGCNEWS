extends RefCounted
## Measured broad crown envelopes on the original cropped art, never a new PNG.
## Only five specifically inspected trees; buildings/animals/grass default off.
const PROFILES := {
	"BroadTreeAtRightFrame": [Vector4(0.51, 0.405, 0.49, 0.405)],
	"OakOnLowerOutcrop": [Vector4(0.50, 0.42, 0.49, 0.42)],
	"YoungOakByVillage": [Vector4(0.59, 0.285, 0.37, 0.285), Vector4(0.24, 0.55, 0.255, 0.23)],
	"OldOakOnShelf": [Vector4(0.49, 0.405, 0.49, 0.405)],
	"YoungHawthornInValley": [Vector4(0.74, 0.30, 0.28, 0.31), Vector4(0.40, 0.75, 0.40, 0.25)]}

static func apply_to(material: ShaderMaterial, label: String) -> void:
	if not PROFILES.has(label):
		return
	var lobes: Array = PROFILES[label]
	var values: Array[Vector4] = []
	for lobe: Vector4 in lobes:
		values.append(lobe)
	while values.size() < 4:
		values.append(Vector4.ZERO)
	material.set_shader_parameter("canopy_count", lobes.size())
	material.set_shader_parameter("canopy_lobes", values)
	material.set_shader_parameter("canopy_strength", 0.92)
	material.set_shader_parameter("canopy_backlight", true)
	material.set_shader_parameter("canopy_leaf_orientation", true)
	material.set_shader_parameter("canopy_pigment_recovery", true)
