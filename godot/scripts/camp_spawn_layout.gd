extends RefCounted
## Public visual layout only. No timer, Node, account or battle authority.
## All five sites were surveyed against the frozen native core AND all twelve
## detail chunks, using all thirteen display-scaled actor footprints/lunges.
## Evidence: artifacts/camp-spawn-v166/native/terrain-result-complete.json.
## The caller must still revalidate its actual terrain callbacks before choice;
## this finite terrain survey does not promise clearance from moving wildlife.
## Translate hero, pet and Boss together, retaining their local foot stations.
const CENTRES: Array[Vector2] = [
	Vector2(5.0, -12.0),
	Vector2(2.0, -15.0),
	Vector2(8.0, -15.0),
	Vector2(2.0, -9.0),
	Vector2(8.0, -9.0),
]

## Call once per new visual round, never per repeated snapshot or frame. Seed
## must be an explicit public display key, not credentials or account data.
## -1 means no alternative safe site; never silently repeat the previous site.
## Canonical order/deduplication makes equivalent eligible sets deterministic.
static func choose(valid_indices: PackedInt32Array, previous: int, seed: String) -> int:
	if seed.is_empty() or seed.length() > 128 or valid_indices.is_empty():
		return -1
	if previous < -1 or previous >= CENTRES.size():
		return -1
	for index: int in valid_indices:
		if index < 0 or index >= CENTRES.size():
			return -1
	var choices: Array[int] = []
	for index in range(CENTRES.size()):
		if index != previous and valid_indices.has(index):
			choices.append(index)
	if choices.is_empty():
		return -1
	# Local unsigned FNV-1a32: no engine/global RNG state is read or advanced.
	var value: int = 2166136261
	for byte: int in seed.to_utf8_buffer():
		value = ((value ^ byte) * 16777619) & 0xffffffff
	return choices[value % choices.size()]
