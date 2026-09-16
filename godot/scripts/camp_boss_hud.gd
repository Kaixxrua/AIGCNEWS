extends CanvasLayer
## Public presentation only; pack as res://camp_presentation/camp_boss_hud.gd.
## Caller supplies the confirmed remaining ratio and viewport size in the SAME
## viewport coordinate space (no extra DPR factor). The retained head anchor
## is validated for API compatibility, but never positions this bottom bar.
## No HP, damage, elapsed time, round transitions or settlement is inferred here.
## Only positive explicit delta advances the cosmetic trail; delta=0 is a pure
## presentation refresh. No _process, timer, tween, network or world dependency.

const ACTIVE_MODES := ["demo", "fighting", "paused", "defeated"]
const TRAIL_HOLD := 0.22
const TRAIL_SPEED := 1.60
const MAX_STEP := 0.10
const WORLD_ASPECT := 1.6
const BAR_WIDTH_FRACTION := 0.67
const GOLD := Color("c9b794")
const TRACK := Color("101412d1")
const TRACK_EDGE := Color("a88b6859")
const BLOOD := Color("ad3540")
const BLOOD_LIGHT := Color("d65e5c")
const TRAIL := Color("bd8958")
const TEXT := Color("f2e6ca")

var _canvas: Control
var _cast: CastBubble
var _damage: DamageNumber
var _cast_font: Font
var _font: Font
var _mode := "waiting"
var _ratio := 0.0
var _trail_ratio := 0.0
var _trail_delay := 0.0
var _has_sample := false
var _stale := false
var _paused := false
var _tags := PackedStringArray()
var _status := ""
var _reason := "not_presented"
var _anchor := Vector2.ZERO
var _viewport_size := Vector2.ZERO
var _rect := Rect2()
var _controls_rect := Rect2()
var _caption_rect := Rect2()
var _bar := Rect2()
var _ui_scale := 1.0
var _bottom_margin := 0.0
var _world_width := 0.0
var _padding := 4.0
var _gap := 2.0
var _font_size := 13
var _status_size := 10
var _line_height := 0.0
var _boss_width := 0.0
var _inline_status := true
var _paint_signature: Array = []

func _init() -> void:
	name = "CampBossHud"
	layer = 20
	follow_viewport_enabled = false
	visible = false
	set_process(false)
	set_physics_process(false)

func _ready() -> void:
	# Resolve the fallback font only once the scene has entered its viewport.
	_font = ThemeDB.fallback_font
	if not is_instance_valid(_canvas):
		_canvas = Control.new()
		_canvas.name = "BossBar"
		_canvas.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_canvas.focus_mode = Control.FOCUS_NONE
		_canvas.clip_contents = true
		_canvas.visible = false
		_canvas.draw.connect(_draw_hud)
		add_child(_canvas)
	if not is_instance_valid(_cast):
		_cast = CastBubble.new()
		add_child(_cast)
	if _cast_font != null:
		_cast.set_font(_cast_font)
	_cast.present("", Vector2.ZERO, Vector2.ZERO, false, Rect2())
	if not is_instance_valid(_damage):
		_damage = DamageNumber.new()
		add_child(_damage)
	_damage.present(0, Vector2.ZERO, Vector2.ZERO, 0.0, false, false, Rect2(), Rect2())
	_hide_bar("not_presented")

func present(mode: String, ratio: float, anchor: Vector2, viewport_size: Vector2,
		boss_visible: bool, stale: bool, animation_paused: bool, delta: float = 0.0) -> void:
	var changed_domain := (_mode == "demo") != (mode == "demo")
	_mode = mode
	_stale = stale
	_paused = animation_paused or mode == "paused"
	_anchor = anchor if anchor.is_finite() else Vector2.ZERO
	_viewport_size = viewport_size if viewport_size.is_finite() else Vector2.ZERO
	if not is_node_ready() or not is_instance_valid(_canvas):
		# Calls during scene assembly fail closed; a fresh explicit sample after
		# ready is required, so an old pre-attachment sample cannot flash on entry.
		_hide_bar("not_ready")
		return
	if not mode in ACTIVE_MODES or not boss_visible:
		_hide_bar("mode_inactive" if not mode in ACTIVE_MODES else "boss_hidden")
		return
	if not is_finite(ratio) or not anchor.is_finite() or not viewport_size.is_finite() \
			or viewport_size.x < 136.0 or viewport_size.y < 64.0 or _font == null:
		_hide_bar("invalid_or_small_viewport")
		return
	if mode == "defeated" and ratio != 0.0:
		_hide_bar("inconsistent_defeat")
		return
	_tags = PackedStringArray()
	if stale:
		_tags.append("SYNC")
	if _paused:
		_tags.append("PAUSED")
	_status = " / ".join(_tags)
	if not _layout_bar():
		_hide_bar("no_safe_bottom_space")
		return
	var next_ratio := clampf(ratio, 0.0, 1.0)
	if not _has_sample or changed_domain or next_ratio > _ratio or mode == "defeated":
		# First sample, domain switch, new round or correction: never inherit a
		# previous encounter's damaged trail. This does not infer any round ID.
		_trail_ratio = next_ratio
		_trail_delay = 0.0
	elif next_ratio < _ratio:
		# Continuous demo updates must not restart the hold on every frame.
		if _trail_ratio <= _ratio:
			_trail_delay = TRAIL_HOLD
		_trail_ratio = maxf(_trail_ratio, _ratio)
	_ratio = next_ratio
	_has_sample = true
	if not _paused and not stale and is_finite(delta) and delta > 0.0:
		var step := minf(delta, MAX_STEP)
		var draining := maxf(0.0, step - _trail_delay)
		_trail_delay = maxf(0.0, _trail_delay - step)
		_trail_ratio = move_toward(_trail_ratio, _ratio, TRAIL_SPEED * draining)
	_reason = ""
	visible = true
	_canvas.visible = true
	_canvas.position = _rect.position
	_canvas.size = _rect.size
	var signature: Array = [_rect, _bar, _ratio, _trail_ratio, _status, _font_size, _status_size, _inline_status]
	if signature != _paint_signature:
		_paint_signature = signature
		_canvas.queue_redraw()
	_sync_cast_layout()

func present_cast(title: String, anchor: Vector2, viewport_size: Vector2, show: bool,
		prefer_left: bool = false, actor_rects: Array[Rect2] = []) -> void:
	# One owner-selected caster, no local skill schedule, timeout or HP writes.
	if not is_node_ready() or not is_instance_valid(_cast):
		return
	_cast.present(title, anchor, viewport_size, show, _rect if _canvas.visible else Rect2(), prefer_left, actor_rects)
	_sync_cast_layout()

func set_cast_font(font: Font) -> void:
	# Optional explicit dependency for isolated tests/embedding. Packaged Web
	# uses the fixed subset font path in CastBubble; never a font download.
	_cast_font = font
	if is_instance_valid(_cast):
		_cast.set_font(font)
		_sync_cast_layout()

func present_damage(amount: int, anchor: Vector2, viewport_size: Vector2, age: float, heavy: bool, show: bool) -> void:
	# Main supplies an actual confirmed decrement and the complete 1.20s age.
	# This display neither derives damage from a ratio nor creates hit events.
	if not is_node_ready() or not is_instance_valid(_damage):
		return
	_damage.present(amount, anchor, viewport_size, age, heavy, show,
		_rect if _canvas.visible else Rect2(), _cast.screen_rect() if _cast.visible else Rect2())
	_sync_cast_layout()

func present_ultimate(_title: String, _stage: String, _show: bool, _viewport_size: Vector2) -> void:
	# Compatibility only. Old callers cannot resurrect a centered/top banner
	# or hide a new actor-local bubble. Migrate callers to present_cast.
	pass

func _sync_cast_layout() -> void:
	var bar_visible := is_instance_valid(_canvas) and _canvas.visible
	if is_instance_valid(_cast):
		_cast.avoid_boss(_rect if bar_visible else Rect2())
	var cast_visible := is_instance_valid(_cast) and _cast.visible
	if is_instance_valid(_damage):
		_damage.avoid(_rect if bar_visible else Rect2(), _cast.screen_rect() if cast_visible else Rect2())
	visible = bar_visible or cast_visible or (is_instance_valid(_damage) and _damage.visible)

func _hide_bar(reason: String) -> void:
	visible = false
	if is_instance_valid(_canvas):
		_canvas.visible = false
	_has_sample = false
	_ratio = 0.0
	_trail_ratio = 0.0
	_trail_delay = 0.0
	_rect = Rect2()
	_bar = Rect2()
	_controls_rect = Rect2()
	_caption_rect = Rect2()
	_bottom_margin = 0.0
	_world_width = 0.0
	_tags.clear()
	_status = ""
	_reason = reason
	_paint_signature.clear()
	_sync_cast_layout()

func _layout_bar() -> bool:
	_ui_scale = clampf(minf(_viewport_size.x / 1280.0, _viewport_size.y / 800.0), 0.8, 1.5)
	# About two thirds of the accepted 16:10 world, not the full width of any
	# side letterboxes. All measurements stay in the supplied viewport space.
	_world_width = minf(_viewport_size.x, _viewport_size.y * WORLD_ASPECT)
	var margin := ceilf(10.0 * _ui_scale)
	_padding = maxf(3.0, roundf(4.0 * _ui_scale))
	_gap = maxf(2.0, roundf(3.0 * _ui_scale))
	_font_size = maxi(12, roundi(14.0 * _ui_scale))
	_status_size = maxi(10, roundi(11.0 * _ui_scale))
	_measure_header()
	var width := floorf(minf(maxf(_world_width * BAR_WIDTH_FRACTION, 160.0), _viewport_size.x - margin * 2.0))
	var status_width := ceilf(_font.get_string_size(_status, HORIZONTAL_ALIGNMENT_LEFT, -1, _status_size).x)
	_inline_status = _status.is_empty() or width >= _padding * 2.0 + _boss_width + status_width + _gap
	var bar_height := maxf(7.0, roundf(6.0 * _ui_scale))
	if width < maxf(120.0, status_width + _padding * 2.0):
		return false
	_bar = Rect2(Vector2(_padding, _padding + _line_height + _gap), Vector2(width - _padding * 2.0, bar_height))
	var height := maxf(_bar.end.y + _padding, roundf(40.0 * _ui_scale))
	if not _inline_status:
		height += _gap + ceilf(_font.get_height(_status_size))
	# 50 logical pixels at the project's 1280x800 canvas become 90 pixels
	# in its QHD 2304x1440 world. Tiny supplied viewports retain a bounded
	# 48px caption reservation; never stretch or apply a second DPR factor.
	_bottom_margin = roundf(clampf(_viewport_size.y / 16.0, 48.0, 90.0))
	_caption_rect = Rect2(0.0, _viewport_size.y - _bottom_margin, _viewport_size.x, _bottom_margin)
	var position := Vector2((_viewport_size.x - width) * 0.5, _caption_rect.position.y - height).floor()
	if position.y < margin:
		return false
	var controls_width := minf(ceilf(320.0 * _ui_scale), _viewport_size.x - margin * 2.0)
	# Keep the existing upper-right control reservation. A valid bottom bar
	# does not follow a moving head, move above a face, or add another canvas.
	_controls_rect = Rect2(Vector2(_viewport_size.x - margin - controls_width, margin), Vector2(controls_width, ceilf(56.0 * _ui_scale)))
	_rect = Rect2(position, Vector2(width, height))
	return not _rect.intersects(_controls_rect) and not _rect.intersects(_caption_rect)

func _measure_header() -> void:
	_line_height = ceilf(_font.get_height(_font_size))
	_boss_width = ceilf(_font.get_string_size("BOSS", HORIZONTAL_ALIGNMENT_LEFT, -1, _font_size).x)

func _draw_hud() -> void:
	if not _canvas.visible or _font == null:
		return
	# No enclosing plate, corners or percentage: only a softly bedded red line.
	_canvas.draw_rect(_bar.grow(3.0), Color("080c0b12"))
	_canvas.draw_rect(_bar.grow(1.0), Color("080c0b35"))
	_canvas.draw_rect(_bar, TRACK)
	_canvas.draw_line(_bar.position, _bar.position + Vector2(_bar.size.x, 0.0), TRACK_EDGE, 1.0)
	var inside := _bar.grow(-1.0)
	if _trail_ratio > _ratio:
		_canvas.draw_rect(Rect2(inside.position, Vector2(inside.size.x * _trail_ratio, inside.size.y)), TRAIL)
	if _ratio > 0.0:
		var fill := Rect2(inside.position, Vector2(inside.size.x * _ratio, inside.size.y))
		_canvas.draw_rect(fill, BLOOD)
		_canvas.draw_rect(Rect2(fill.position, Vector2(fill.size.x, 1.0)), BLOOD_LIGHT)
	var baseline := _padding + _font.get_ascent(_font_size)
	_canvas.draw_string(_font, Vector2(_padding, baseline + 1.0), "BOSS", HORIZONTAL_ALIGNMENT_LEFT, _boss_width, _font_size, Color("080c0be0"))
	_canvas.draw_string(_font, Vector2(_padding, baseline), "BOSS", HORIZONTAL_ALIGNMENT_LEFT, _boss_width, _font_size, TEXT)
	if not _status.is_empty():
		var at := Vector2(_padding, _bar.end.y + _gap + _font.get_ascent(_status_size))
		var text_width := _bar.size.x
		if _inline_status:
			at = Vector2(_padding + _boss_width + _gap, _padding + (_line_height - _font.get_height(_status_size)) * 0.5 + _font.get_ascent(_status_size))
			text_width -= _boss_width + _gap
		_canvas.draw_string(_font, at + Vector2.DOWN, _status, HORIZONTAL_ALIGNMENT_RIGHT, text_width, _status_size, Color("080c0be0"))
		_canvas.draw_string(_font, at, _status, HORIZONTAL_ALIGNMENT_RIGHT, text_width, _status_size, GOLD)

func debug_state() -> Dictionary:
	# Fresh values only: callers cannot mutate this module by editing the result.
	var bar_visible := is_instance_valid(_canvas) and _canvas.visible
	return {"visible": bar_visible, "mode": _mode, "ratio": _ratio, "trail_ratio": _trail_ratio,
		"trail_delay": _trail_delay, "percent": ceili(_ratio * 100.0), "labels": _tags.duplicate(),
		"text": ("BOSS " + _status).strip_edges() if bar_visible else "",
		"percent_drawn": false, "framed": false, "track_style": "soft_line",
		"stale": _stale, "paused": _paused, "rect": _rect, "controls_rect": _controls_rect,
		"bar_rect": Rect2(_rect.position + _bar.position, _bar.size), "anchor": _anchor,
		"viewport_size": _viewport_size, "head_gap": 0.0, "ui_scale": _ui_scale,
		"layout": "bottom_center", "bottom_margin": _bottom_margin,
		"caption_rect": _caption_rect, "world_width": _world_width,
		"font_size": _font_size, "status_font_size": _status_size,
		"inline_status": _inline_status, "hidden_reason": _reason, "presentation_only": true,
		"ultimate": {"visible": false, "text": "", "hidden_reason": "replaced_by_cast_bubble"},
		"cast": _cast.debug_state() if is_instance_valid(_cast) else {"visible": false, "hidden_reason": "not_ready"},
		"damage": _damage.debug_state() if is_instance_valid(_damage) else {"visible": false, "hidden_reason": "not_ready"}}

class CastBubble extends Control:
	# Font bytes are bundled by the pack owner, not obtained from the network
	# or a machine's proprietary font collection. Missing glyphs fail closed.
	const FONT_PATH := "res://camp_presentation/fonts/camp_ui_zh.ttf"
	const FONT_BYTE_LIMIT := 98304
	const INK := Color("f5ecd9")
	const BED := Color("15201dc9")
	const EDGE := Color("b4aa8955")
	var _font: Font
	var _font_source := "missing"
	var _requested := false
	var _prefer_left := false
	var _actor_rects: Array[Rect2] = []
	var _title := ""
	var _lines := PackedStringArray()
	var _view := Vector2.ZERO
	var _anchor := Vector2.ZERO
	var _boss := Rect2()
	var _rect := Rect2()
	var _body := Rect2()
	var _controls := Rect2()
	var _caption := Rect2()
	var _face := Rect2()
	var _pointer := PackedVector2Array()
	var _reason := "not_presented"
	var _font_size := 14
	var _padding := 7.0
	var _line_height := 0.0
	var _truncated := false
	var _glyphs_complete := false
	var _style: StyleBoxFlat
	var _signature: Array = []

	func _init() -> void:
		name = "CastBubble"
		visible = false
		mouse_filter = Control.MOUSE_FILTER_IGNORE
		focus_mode = Control.FOCUS_NONE
		set_process(false)
		set_physics_process(false)

	func _ready() -> void:
		_style = StyleBoxFlat.new()
		_style.bg_color = BED
		_style.border_color = EDGE
		_style.set_border_width_all(1)
		_style.set_corner_radius_all(3)
		_style.shadow_color = Color("060a091c")
		_style.shadow_size = 2
		if _font == null and FileAccess.file_exists(FONT_PATH):
			var file := FileAccess.open(FONT_PATH, FileAccess.READ)
			if file != null and file.get_length() > 4 and file.get_length() <= FONT_BYTE_LIMIT:
				var bytes := FileAccess.get_file_as_bytes(FONT_PATH)
				if bytes.slice(0, 4) == PackedByteArray([0, 1, 0, 0]):
					var packed_font := FontFile.new()
					packed_font.allow_system_fallback = false
					packed_font.data = bytes
					if packed_font.has_char(0xff01):
						_font = packed_font
						_font_source = "packed"
		_hide("not_presented")

	func set_font(font: Font) -> void:
		_font = font
		_font_source = "injected" if font != null else "missing"
		_signature.clear()
		_layout()

	func present(title: String, anchor: Vector2, viewport_size: Vector2, show: bool, boss_rect: Rect2,
			prefer_left: bool = false, actor_rects: Array[Rect2] = []) -> void:
		_requested = show
		_prefer_left = prefer_left
		_actor_rects = actor_rects.duplicate()
		_title = _clean_title(title) if show else ""
		_anchor = anchor
		_view = viewport_size
		_boss = boss_rect
		_layout()

	func avoid_boss(boss_rect: Rect2) -> void:
		if _boss != boss_rect:
			_boss = boss_rect
			_layout()

	func screen_rect() -> Rect2:
		return _rect

	func _hide(reason: String) -> void:
		visible = false
		_rect = Rect2()
		_body = Rect2()
		_controls = Rect2()
		_caption = Rect2()
		_face = Rect2()
		_pointer.clear()
		_lines.clear()
		_glyphs_complete = false
		_reason = reason
		_signature.clear()

	func _clean_title(value: String) -> String:
		var result := ""
		for character: String in value.substr(0, 64):
			var code := character.unicode_at(0)
			# Plain draw text only; discard control and invisible bidi markers.
			if code >= 0x20 and not (code >= 0x7f and code <= 0x9f) \
					and not (code >= 0x200b and code <= 0x200f) \
					and not (code >= 0x202a and code <= 0x202e) \
					and not (code >= 0x2066 and code <= 0x2069):
				result += character
		result = result.strip_edges()
		while result.ends_with("!") or result.ends_with("！"):
			result = result.left(result.length() - 1).strip_edges()
		return result

	func _supports(value: String) -> bool:
		if _font == null:
			return false
		for character: String in value:
			if character != " " and not _font.has_char(character.unicode_at(0)):
				return false
		return true

	func _width(value: String) -> float:
		return _font.get_string_size(value, HORIZONTAL_ALIGNMENT_LEFT, -1, _font_size).x

	func _wrap(value: String, width: float) -> PackedStringArray:
		_truncated = false
		if _width(value) <= width:
			return PackedStringArray([value])
		var first := ""
		for character: String in value:
			if _width(first + character) > width:
				break
			first += character
		if first.is_empty():
			return PackedStringArray()
		var rest := value.substr(first.length()).strip_edges()
		if _width(rest) > width:
			_truncated = true
			var suffix := ("…" if _font.has_char(0x2026) else "...") + "！"
			while not rest.is_empty() and _width(rest + suffix) > width:
				rest = rest.left(rest.length() - 1)
			rest = rest.trim_suffix("！") + suffix
		return PackedStringArray([first.strip_edges(), rest])

	func _tail(body: Rect2, scale: float) -> PackedVector2Array:
		var inset := minf(8.0 * scale, body.size.x * 0.25)
		var attach := Vector2(clampf(_anchor.x, body.position.x + inset, body.end.x - inset), body.end.y)
		var tangent := Vector2.RIGHT * 3.0 * scale
		if _anchor.y < body.position.y:
			attach.y = body.position.y
		elif _anchor.y <= body.end.y:
			attach = Vector2(body.position.x if _anchor.x < body.position.x else body.end.x,
				clampf(_anchor.y, body.position.y + inset, body.end.y - inset))
			tangent = Vector2.DOWN * 3.0 * scale
		var tip := attach + attach.direction_to(_anchor) * minf(8.0 * scale, attach.distance_to(_anchor))
		return PackedVector2Array([attach - tangent, tip, attach + tangent])

	func _layout() -> void:
		if not _requested:
			_hide("not_requested")
			return
		if not is_node_ready() or _title.is_empty():
			_hide("not_ready_or_empty_title")
			return
		if not _view.is_finite() or not _anchor.is_finite() or _view.x < 136 or _view.y < 64:
			_hide("invalid_or_small_viewport")
			return
		for actor_rect: Rect2 in _actor_rects:
			if not actor_rect.position.is_finite() or not actor_rect.size.is_finite() or not actor_rect.end.is_finite():
				_hide("invalid_actor_rect")
				return
		if _font == null:
			_hide("missing_cast_font")
			return
		var spoken := _title + "！"
		if not _supports(spoken):
			_hide("missing_cast_glyph")
			return
		var scale := clampf(minf(_view.x / 1280.0, _view.y / 800.0), 0.8, 1.5)
		var margin := ceilf(10.0 * scale)
		_padding = maxf(6.0, roundf(7.0 * scale))
		_font_size = maxi(13, roundi(14.0 * scale))
		_line_height = ceilf(_font.get_height(_font_size))
		var max_width := minf(240.0 * scale, _view.x * 0.55)
		_lines = _wrap(spoken, max_width - _padding * 2.0)
		if _lines.is_empty() or not _supports("".join(_lines)):
			_hide("missing_cast_glyph")
			return
		var width := 0.0
		for line: String in _lines:
			width = maxf(width, ceilf(_width(line)))
		var box_size := Vector2(width + _padding * 2.0, _line_height * _lines.size() + _padding * 2.0)
		var controls_width := minf(ceilf(320.0 * scale), _view.x - margin * 2.0)
		_controls = Rect2(Vector2(_view.x - margin - controls_width, margin), Vector2(controls_width, ceilf(56.0 * scale)))
		var caption_height := roundf(clampf(_view.y / 16.0, 48.0, 90.0))
		_caption = Rect2(0.0, _view.y - caption_height, _view.x, caption_height)
		_face = Rect2(_anchor + Vector2(-16.0, 2.0) * scale, Vector2(32.0, 36.0) * scale)
		var bounds := Rect2(Vector2.ONE * margin, _view - Vector2.ONE * margin * 2.0)
		var left := _anchor.x - box_size.x - 9.0 * scale
		var right := _anchor.x + 9.0 * scale
		var above := _anchor.y - box_size.y - 9.0 * scale
		var left_side := _anchor.x - box_size.x - 26.0 * scale
		var right_side := _anchor.x + 26.0 * scale
		var outer_left := left
		var outer_right := right
		for supplied: Rect2 in _actor_rects:
			var actor_rect := supplied.abs()
			if actor_rect.has_area() and actor_rect.end.y >= above and actor_rect.position.y <= _anchor.y + box_size.y * 0.5:
				outer_left = minf(outer_left, actor_rect.position.x - box_size.x - 9.0 * scale)
				outer_right = maxf(outer_right, actor_rect.end.x + 9.0 * scale)
		# Actor side is explicit, not inferred from the screen midpoint: a hero
		# can stand left of the Boss while BOTH are in the right half of a shot.
		# Bounded outward alternatives also clear a tightly grouped hero/pet.
		var candidates: Array[Vector2] = [
			Vector2(left if _prefer_left else right, above),
			Vector2(left_side if _prefer_left else right_side, _anchor.y - box_size.y * 0.5),
			Vector2(outer_left if _prefer_left else outer_right, above),
			Vector2(outer_left if _prefer_left else outer_right, _anchor.y - box_size.y * 0.5),
			Vector2(right if _prefer_left else left, above),
			Vector2(right_side if _prefer_left else left_side, _anchor.y - box_size.y * 0.5),
			Vector2(_anchor.x - box_size.x * 0.5, above)]
		_rect = Rect2()
		for at: Vector2 in candidates:
			var body := Rect2(at.clamp(bounds.position, bounds.end - box_size).floor(), box_size)
			var pointer := _tail(body, scale)
			var full := body
			for point: Vector2 in pointer:
				full = full.expand(point)
			var nearest := _anchor.clamp(body.position, body.end)
			if bounds.encloses(full) and nearest.distance_to(_anchor) <= 96.0 * scale \
					and not full.intersects(_controls) and not full.intersects(_caption) \
					and not full.intersects(_boss) and not full.intersects(_face) and not _covers_actor(full):
				_rect = full
				_body = body
				_pointer = pointer
				break
		if not _rect.has_area():
			_hide("no_safe_actor_space")
			return
		_reason = ""
		_glyphs_complete = true
		visible = true
		position = _rect.position
		size = _rect.size
		var signature: Array = [_rect, _body, _pointer, _lines, _font_size, _font]
		if signature != _signature:
			_signature = signature.duplicate(true)
			queue_redraw()

	func _covers_actor(full: Rect2) -> bool:
		# Include the small pointer and 2px soft shadow, not just text/body fill.
		for supplied: Rect2 in _actor_rects:
			var actor_rect := supplied.abs()
			if actor_rect.has_area() and full.grow(2.0).intersects(actor_rect):
				return true
		return false

	func _draw() -> void:
		if not visible or _font == null or _style == null:
			return
		var pointer := PackedVector2Array()
		for point: Vector2 in _pointer:
			pointer.append(point - _rect.position)
		draw_colored_polygon(pointer, BED)
		draw_polyline(pointer, EDGE, 1.0, true)
		var body := Rect2(_body.position - _rect.position, _body.size)
		draw_style_box(_style, body)
		for index in range(_lines.size()):
			var at := body.position + Vector2(_padding, _padding + _font.get_ascent(_font_size) + index * _line_height)
			draw_string(_font, at + Vector2.DOWN, _lines[index], HORIZONTAL_ALIGNMENT_CENTER, body.size.x - _padding * 2.0, _font_size, Color("070d0be0"))
			draw_string(_font, at, _lines[index], HORIZONTAL_ALIGNMENT_CENTER, body.size.x - _padding * 2.0, _font_size, INK)

	func debug_state() -> Dictionary:
		return {"visible": visible, "title": _title, "text": "\n".join(_lines) if visible else "",
			"lines": _lines.duplicate(), "rect": _rect, "body_rect": _body, "anchor": _anchor,
			"pointer": _pointer.duplicate(), "controls_rect": _controls, "caption_rect": _caption,
			"face_rect": _face, "boss_rect": _boss, "font_size": _font_size, "padding": _padding, "truncated": _truncated,
			"prefer_left": _prefer_left, "actor_rects": _actor_rects.duplicate(),
			"font_source": _font_source, "glyphs_complete": _glyphs_complete,
			"layout": "actor_bubble", "hidden_reason": _reason, "presentation_only": true}

class DamageNumber extends Control:
	const DURATION := 1.20
	var _font: Font
	var _requested := false
	var _amount := 0
	var _anchor := Vector2.ZERO
	var _view := Vector2.ZERO
	var _age := 0.0
	var _heavy := false
	var _boss := Rect2()
	var _cast := Rect2()
	var _rect := Rect2()
	var _controls := Rect2()
	var _caption := Rect2()
	var _reason := "not_presented"
	var _font_size := 20
	var _alpha := 0.0
	var _rise := 0.0
	var _pop := 1.0
	var _signature: Array = []

	func _init() -> void:
		name = "DamageNumber"
		visible = false
		mouse_filter = Control.MOUSE_FILTER_IGNORE
		focus_mode = Control.FOCUS_NONE
		set_process(false)
		set_physics_process(false)

	func _ready() -> void:
		_font = ThemeDB.fallback_font

	func present(amount: int, anchor: Vector2, viewport_size: Vector2, age: float, heavy: bool, show: bool,
			boss_rect: Rect2, cast_rect: Rect2) -> void:
		_requested = show
		_amount = amount
		_anchor = anchor
		_view = viewport_size
		_age = age
		_heavy = heavy
		_boss = boss_rect
		_cast = cast_rect
		_layout()

	func avoid(boss_rect: Rect2, cast_rect: Rect2) -> void:
		if _boss != boss_rect or _cast != cast_rect:
			_boss = boss_rect
			_cast = cast_rect
			_layout()

	func _hide(reason: String) -> void:
		visible = false
		_rect = Rect2()
		_controls = Rect2()
		_caption = Rect2()
		_alpha = 0.0
		_reason = reason
		_signature.clear()

	func _layout() -> void:
		if not _requested:
			_hide("not_requested")
			return
		if not is_node_ready() or _font == null or _amount <= 0:
			_hide("not_ready_or_nonpositive_amount")
			return
		if not is_finite(_age) or _age < 0.0 or _age >= DURATION:
			_hide("expired_or_invalid_age")
			return
		if not _view.is_finite() or not _anchor.is_finite() or _view.x < 136 or _view.y < 64:
			_hide("invalid_or_small_viewport")
			return
		var scale := clampf(minf(_view.x / 1280.0, _view.y / 800.0), 0.8, 1.5)
		var margin := ceilf(10.0 * scale)
		_pop = 1.0 + (0.22 if _heavy else 0.14) * sin(clampf(_age / 0.22, 0.0, 1.0) * PI)
		_rise = (_age / DURATION) * (32.0 if _heavy else 26.0) * scale
		_alpha = 1.0 - smoothstep(0.68, DURATION, _age)
		_font_size = maxi(18, roundi((28.0 if _heavy else 21.0) * scale * _pop))
		var width := ceilf(_font.get_string_size(str(_amount), HORIZONTAL_ALIGNMENT_LEFT, -1, _font_size).x) + 8.0
		while width > _view.x - margin * 2.0 and _font_size > 18:
			_font_size -= 1
			width = ceilf(_font.get_string_size(str(_amount), HORIZONTAL_ALIGNMENT_LEFT, -1, _font_size).x) + 8.0
		var box_size := Vector2(width, ceilf(_font.get_height(_font_size)) + 8.0)
		var controls_width := minf(ceilf(320.0 * scale), _view.x - margin * 2.0)
		_controls = Rect2(Vector2(_view.x - margin - controls_width, margin), Vector2(controls_width, ceilf(56.0 * scale)))
		var caption_height := roundf(clampf(_view.y / 16.0, 48.0, 90.0))
		_caption = Rect2(0.0, _view.y - caption_height, _view.x, caption_height)
		var bounds := Rect2(Vector2.ONE * margin, _view - Vector2.ONE * margin * 2.0)
		var at := _anchor + Vector2.UP * _rise
		if box_size.x > bounds.size.x or box_size.y > bounds.size.y:
			_hide("no_safe_actor_space")
			return
		var right := at.x + 25.0 * scale
		var left := at.x - box_size.x - 25.0 * scale
		var prefer_left := _cast.has_area() and _cast.get_center().x >= at.x
		var above := at.y - box_size.y - 9.0 * scale
		var candidates: Array[Vector2] = [
			Vector2(left if prefer_left else right, above),
			Vector2(right if prefer_left else left, above),
			Vector2(left if prefer_left else right, at.y - box_size.y * 0.4),
			Vector2(right if prefer_left else left, at.y - box_size.y * 0.4)]
		if _cast.has_area():
			candidates.append(Vector2(_cast.position.x - box_size.x - 8.0 * scale, above))
			candidates.append(Vector2(_cast.end.x + 8.0 * scale, above))
			candidates.append(Vector2(at.x - box_size.x * 0.5, _cast.position.y - box_size.y - 8.0 * scale))
		_rect = Rect2()
		for candidate: Vector2 in candidates:
			var rect := Rect2(candidate.clamp(bounds.position, bounds.end - box_size).floor(), box_size)
			if bounds.encloses(rect) and not rect.intersects(_controls) and not rect.intersects(_caption) \
					and not rect.intersects(_boss) and not rect.grow(4.0).intersects(_cast) \
					and rect.get_center().distance_to(at) <= maxf(110.0 * scale, box_size.x):
				_rect = rect
				break
		if not _rect.has_area():
			_hide("no_safe_actor_space")
			return
		_reason = ""
		visible = true
		position = _rect.position
		size = _rect.size
		var signature: Array = [_rect, _amount, _font_size, _alpha, _heavy]
		if signature != _signature:
			_signature = signature
			queue_redraw()

	func _draw() -> void:
		if not visible or _font == null:
			return
		var at := Vector2(4.0, 4.0 + _font.get_ascent(_font_size))
		var color := Color("ffe0a0") if _heavy else Color("fff0d5")
		color.a = _alpha
		draw_string_outline(_font, at, str(_amount), HORIZONTAL_ALIGNMENT_CENTER, size.x - 8.0, _font_size, 2, Color(0.08, 0.07, 0.05, _alpha))
		draw_string(_font, at, str(_amount), HORIZONTAL_ALIGNMENT_CENTER, size.x - 8.0, _font_size, color)

	func debug_state() -> Dictionary:
		return {"visible": visible, "amount": _amount, "text": str(_amount) if visible else "",
			"anchor": _anchor, "age": _age, "heavy": _heavy, "rect": _rect, "cast_rect": _cast,
			"controls_rect": _controls, "caption_rect": _caption, "boss_rect": _boss,
			"font_size": _font_size, "alpha": _alpha, "rise": _rise, "pop": _pop,
			"lifetime": DURATION, "hidden_reason": _reason, "presentation_only": true}
