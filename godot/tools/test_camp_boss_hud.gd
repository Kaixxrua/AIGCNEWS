extends SceneTree
## Only the new HUD in an isolated synthetic project; no world/art/PCK build.
var checks := 0
var failures := 0
var hud: CanvasLayer
const VIEW := Vector2(1280, 800)
const HEAD := Vector2(760, 350)
const CAST_TITLES := ["穿林风矢", "曜日斩", "炽焰弹", "弦音共鸣", "以太药瓶", "流星坠",
	"灵角辉光", "狐火", "月影突袭", "风羽齐射", "金羽疾风", "苍蓝吐息", "古印震地",
	"风之镇魂曲", "旭日十字", "凤凰星火", "群星序曲", "翠灵新生", "天星裁决", "符文天崩", "灵光一击"]

func _initialize() -> void:
	run.call_deferred()

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		print("CAMP_BOSS_HUD_FAIL: " + label)

func present(mode: String = "fighting", ratio: float = 0.7, stale: bool = false, paused: bool = false, delta: float = 0.0) -> Dictionary:
	hud.present(mode, ratio, HEAD, VIEW, true, stale, paused, delta)
	return hud.debug_state()

func run() -> void:
	var code: Script = load("res://camp_presentation/camp_boss_hud.gd")
	if code == null or not code.can_instantiate():
		check(false, "HUD compiles independently at the final pack path")
		quit(1)
		return
	hud = code.new()
	check(not hud.visible and not hud.is_node_ready(), "new HUD is hidden before entering the tree")
	check(hud.get_child_count() == 0, "draw-only child waits for ready initialization")
	hud.present_ultimate("WIND REQUIEM", "CHARGE", true, VIEW)
	check(not hud.debug_state().ultimate.visible and hud.get_child_count() == 0, "early ultimate call also waits for ready")
	hud.present_cast("穿林风矢！", HEAD, VIEW, true)
	hud.present_damage(123, HEAD, VIEW, 0.0, false, true)
	check(not hud.debug_state().cast.visible and not hud.debug_state().damage.visible and hud.get_child_count() == 0,
		"early cast/damage calls cannot allocate or flash before ready")
	present()
	check(not hud.visible and hud.debug_state().hidden_reason == "not_ready" and hud.get_child_count() == 0,
		"early present fails closed without initializing scene resources")
	var scene := Node3D.new()
	scene.add_child(hud)
	root.add_child(scene)
	check(hud.is_node_ready() and hud.debug_state().hidden_reason == "not_presented", "direct scene child initializes in ready and discards early samples")
	check(not hud.visible, "new HUD is hidden before an explicit sample")
	check(hud.get_child_count() == 3 and hud.get_children().all(func(n: Node) -> bool: return n is Control), "exactly three reusable draw-only Controls")
	var canvas: Control = hud.get_child(0)
	var bubble: Control = hud.get_node("CastBubble")
	var damage: Control = hud.get_node("DamageNumber")
	for child: Control in [bubble, damage]:
		check(not child.visible and child.mouse_filter == Control.MOUSE_FILTER_IGNORE and child.focus_mode == Control.FOCUS_NONE,
			"actor-local overlay is hidden and input-transparent")
	check(hud.debug_state().cast.font_source == "packed", "actual approved TTF is loaded at the final pack path")
	var cast_font: FontFile = bubble._font as FontFile
	check(cast_font != null and not cast_font.allow_system_fallback and cast_font.fallbacks.is_empty(),
		"CJK test cannot silently pass using machine fonts instead of packaged bytes")
	check(not canvas.visible, "ready leaves the draw Control hidden too")
	check(canvas.mouse_filter == Control.MOUSE_FILTER_IGNORE and canvas.focus_mode == Control.FOCUS_NONE,
		"HUD does not capture mouse, touch or keyboard focus")
	check(not hud.is_processing() and not hud.is_physics_processing(), "no independent clock or automatic processing")
	for mode: String in ["waiting", "unavailable", "cooldown", "daily_complete", "", "unknown"]:
		present("fighting", 0.7)
		var hidden := present(mode, 1.0, false, false, 20.0)
		check(not hidden.visible and not canvas.visible and hidden.ratio == 0 and hidden.trail_ratio == 0,
			"no misleading fresh bar in " + mode)
	present()
	hud.present("fighting", 0.7, HEAD, VIEW, false, false, false)
	check(not hud.debug_state().visible and hud.debug_state().hidden_reason == "boss_hidden", "no Boss hides HUD and clears history")
	var state := present("demo", 0.375, true, true)
	check(state.visible and state.ratio == 0.375 and state.percent == 38, "only supplied ratio; bounded ceil percentage")
	check(state.labels == PackedStringArray(["SYNC", "PAUSED"]), "explicit synchronization and pause flags can coexist")
	check(state.text == "BOSS SYNC / PAUSED" and not state.percent_drawn and not state.framed,
		"percentage remains diagnostic only; label drawing has no numeric percentage or plate")
	check(not present("demo", 0.7).text.contains("DEMO"), "observation HUD has no DEMO label")
	check(present("paused", 0.7).labels == PackedStringArray(["PAUSED"]), "server pause labels without local animation pause")
	check(present("fighting", 0.7, true).labels == PackedStringArray(["SYNC"]), "stale sample is explicitly labelled")
	check(present("fighting", -2.0).ratio == 0.0 and present("fighting", 2.0).ratio == 1.0, "finite ratio clamps to 0..1")
	check(present("fighting", 0.00001).percent == 1 and present("fighting", 0.0).percent == 0, "no premature zero or fake positive percentage")
	present("fighting", 1.0)
	present("fighting", 0.3)
	state = present("defeated", 0.0)
	check(state.visible and state.percent == 0 and state.trail_ratio == 0 and state.trail_delay == 0,
		"confirmed defeat renders zero immediately without a misleading damage buffer")
	check(state.text == "BOSS" and state.percent == 0, "death has zero fill without reintroducing visible percentages")
	check(present("defeated", 0.0, true, true, 100.0).text == "BOSS SYNC / PAUSED", "paused death does not resurrect any bar")
	check(not present("defeated", 0.2).visible, "contradictory positive-HP defeat fails closed, never invents damage")
	check(not present("cooldown").visible, "cooldown hides the completed bar")
	for ratio: float in [NAN, INF, -INF]:
		check(not present("fighting", ratio).visible, "nonfinite ratio fails closed")
	for dimensions: Vector2 in [Vector2.ZERO, Vector2(100, 100), Vector2(320, 40), Vector2(-320, 200), Vector2(INF, 800), Vector2(NAN, 800)]:
		hud.present("fighting", 1.0, HEAD, dimensions, true, false, false)
		check(not hud.debug_state().visible, "invalid or unreadably tiny viewport hidden")
	hud.present("demo", 0.8, Vector2(NAN, 100), VIEW, true, false, false)
	check(not hud.visible, "invalid projected anchor fails closed")
	for dimensions: Vector2 in [Vector2(320, 200), Vector2(320, 568), Vector2(768, 480), Vector2(768, 1024), Vector2(1024, 640), Vector2(1440, 900), Vector2(2304, 1440), Vector2(2560, 1440), Vector2(3440, 1440)]:
		var anchor := dimensions * Vector2(0.68, 0.60)
		hud.present("demo", 0.42, anchor, dimensions, true, true, true)
		state = hud.debug_state()
		check(state.visible, "HUD remains readable at " + str(dimensions))
		check(Rect2(Vector2.ZERO, dimensions).encloses(state.rect), "no overflow at " + str(dimensions))
		check(not state.rect.intersects(state.controls_rect), "right-top controls remain clear at " + str(dimensions))
		check(state.layout == "bottom_center" and absf(state.rect.get_center().x - dimensions.x * 0.5) <= 0.5,
			"fixed bottom bar is horizontally centered at " + str(dimensions))
		check(state.rect.end.y <= state.caption_rect.position.y and not state.rect.intersects(state.caption_rect),
			"reserved bottom caption area stays clear at " + str(dimensions))
		check(is_equal_approx(state.rect.end.y, dimensions.y - state.bottom_margin) and state.bottom_margin >= 48,
			"bar sits at its bounded fixed bottom inset at " + str(dimensions))
		check(state.rect.encloses(state.bar_rect) and state.rect.size.x > 120, "bounded nonzero trough at " + str(dimensions))
		check(state.track_style == "soft_line" and state.bar_rect.size.y >= 7 and state.bar_rect.size.y <= 9,
			"thin readable blood track, not a thick card frame at " + str(dimensions))
	# Long bottom bar acceptance: actual QHD canvas and its 16:10 world width.
	for dimensions: Vector2 in [Vector2(2560, 1440), Vector2(2304, 1440)]:
		for mode: String in ["fighting", "demo", "paused"]:
			var anchor := dimensions * Vector2(0.68, 0.60)
			hud.present(mode, 0.42, anchor, dimensions, true, false, false)
			state = hud.debug_state()
			var world_width := minf(dimensions.x, dimensions.y * 1.6)
			check(state.visible and state.rect.size.x >= world_width * 0.65 and state.rect.size.x <= world_width * 0.70,
				"QHD long bar spans 65..70 percent of world, excluding side letterboxes: " + str(state.rect.size))
			check(state.rect.size.y >= 60 and state.rect.size.y <= 75,
				"QHD normal/observation plate height is 60..75: " + str(state.rect.size))
			check(state.inline_status and state.font_size >= 12 and state.status_font_size >= 10,
				"normal QHD labels stay legible on one line")
			check(state.bottom_margin == 90 and state.caption_rect.size.y == 90 and dimensions.y - state.rect.end.y == 90,
				"QHD keeps the complete bottom 90px free for website caption")
			check(state.rect.position.y > dimensions.y * 0.8 and state.rect.position.y > anchor.y,
				"there is a bottom bar rather than an additional floating head plate")
			print("CAMP_BOSS_HUD_LAYOUT: %s %s plate=%s trough=%s bottom_margin=%s" % [dimensions, mode, state.rect.size, state.bar_rect.size, state.bottom_margin])
		hud.present("demo", 0.42, dimensions * Vector2(0.68, 0.60), dimensions, true, true, true)
		state = hud.debug_state()
		check(state.visible and state.inline_status and state.rect.size.y >= 60 and state.rect.size.y <= 75,
			"long QHD statuses fit beside BOSS without a percentage on one line: " + str(state.rect.size))
		check(state.font_size >= 12 and state.status_font_size >= 10, "long-bar labels retain readable font sizes")
		print("CAMP_BOSS_HUD_LAYOUT: %s long-status plate=%s" % [dimensions, state.rect.size])
	# The actual project keeps a 1280x800 logical CanvasLayer, then stretches its
	# 16:10 world to 2304x1440 at QHD. Do not multiply by DPR a second time.
	present("fighting", 0.42)
	state = hud.debug_state()
	var qhd_stretch := 1440.0 / VIEW.y
	check(is_equal_approx(state.bottom_margin * qhd_stretch, 90.0), "real project canvas stretch preserves 90px QHD caption clearance")
	check(state.rect.size.y * qhd_stretch >= 60 and state.rect.size.y * qhd_stretch <= 75,
		"real 1280x800 canvas stretches to a 60..75px QHD bar, not a double-scaled panel")
	check(state.rect.size.x / VIEW.x >= 0.65 and state.rect.size.x / VIEW.x <= 0.70, "real project canvas preserves the long width fraction")
	for dimensions: Vector2 in [Vector2(320, 200), Vector2(320, 568)]:
		for mode: String in ["fighting", "demo", "paused"]:
			for stale: bool in [false, true]:
				for paused: bool in [false, true]:
					var anchor := dimensions * Vector2(0.68, 0.60)
					hud.present(mode, 0.42, anchor, dimensions, true, stale, paused)
					state = hud.debug_state()
					check(state.visible and Rect2(Vector2.ZERO, dimensions).encloses(state.rect),
						"320px keeps every status combination visible without overflow: " + mode)
					check(not state.rect.intersects(state.controls_rect) and not state.rect.intersects(state.caption_rect) and state.bottom_margin >= 48,
						"320px retains control exclusion and bounded bottom caption clearance")
					check(state.font_size >= 12 and state.status_font_size >= 10 and state.rect.size.y <= 48,
						"320px labels stay readable without consuming the whole scene height")
	hud.present("fighting", 0.8, Vector2.ZERO, VIEW, true, false, false)
	var fixed_bottom: Rect2 = hud.debug_state().rect
	for anchor: Vector2 in [Vector2(-200, 900), Vector2(4000, 900), Vector2(1200, 80), Vector2(300, 20), Vector2(-1000, -1000)]:
		hud.present("fighting", 0.8, anchor, VIEW, true, false, false)
		state = hud.debug_state()
		check(state.visible and state.rect == fixed_bottom, "finite head movement cannot move or hide fixed bottom bar: " + str(anchor))
		check(not state.rect.intersects(state.controls_rect) and not state.rect.intersects(state.caption_rect), "edge anchor cannot override reservations: " + str(anchor))
	hud.present("demo", 0.8, Vector2(300, 20), Vector2(320, 200), true, false, false)
	check(hud.debug_state().visible and hud.debug_state().layout == "bottom_center", "a head near the top no longer hides the 320px bottom bar")
	# Damage-buffer contract: repeated pure present never advances visual state.
	present("waiting")
	present("fighting", 1.0)
	state = present("fighting", 0.6)
	check(state.ratio == 0.6 and state.trail_ratio == 1.0 and state.trail_delay > 0.0, "confirmed decrease creates brief cosmetic buffer")
	var frozen: Dictionary = state.duplicate(true)
	for index in range(20):
		check(present("fighting", 0.6) == frozen, "delta-zero refresh is idempotent: " + str(index))
	for invalid_delta: float in [-1.0, NAN, INF]:
		check(present("fighting", 0.6, false, false, invalid_delta) == frozen, "invalid delta cannot advance trail")
	for index in range(5):
		state = present("fighting", 0.6, false, true, 0.1)
		check(state.trail_ratio == frozen.trail_ratio and state.trail_delay == frozen.trail_delay, "animation pause freezes buffer")
		state = present("paused", 0.6, false, false, 0.1)
		check(state.trail_ratio == frozen.trail_ratio and state.trail_delay == frozen.trail_delay, "server pause freezes buffer")
		state = present("fighting", 0.6, true, false, 0.1)
		check(state.trail_ratio == frozen.trail_ratio and state.trail_delay == frozen.trail_delay, "SYNC freezes buffer")
	state = present("fighting", 0.6, false, false, 1000.0)
	check(state.trail_ratio == 1.0 and state.trail_delay > 0.0, "large delta is bounded, never a catch-up clock")
	for index in range(20):
		state = present("fighting", 0.6, false, false, 0.1)
		check(state.ratio == 0.6 and state.trail_ratio >= 0.6, "buffer never changes ratio or drains past confirmation")
	check(is_equal_approx(state.trail_ratio, 0.6), "buffer settles promptly with explicit unpaused deltas")
	state = present("fighting", 0.9)
	check(state.ratio == 0.9 and state.trail_ratio == 0.9 and state.trail_delay == 0, "upward correction resets old damage history")
	present("demo", 1.0)
	present("demo", 0.2)
	state = present("fighting", 0.2)
	check(state.trail_ratio == 0.2 and state.trail_delay == 0.0, "demo/live domain cannot leak a cosmetic damage buffer")
	present("waiting")
	present("demo", 1.0)
	for index in range(100):
		state = present("demo", 1.0 - (index + 1) * 0.002, false, false, 0.016)
	check(state.trail_ratio < 0.9 and is_equal_approx(state.ratio, 0.8), "continuous demo damage cannot keep restarting the delay forever")
	frozen = state.duplicate(true)
	await process_frame
	await process_frame
	check(hud.debug_state() == frozen, "drawing and idle frames never advance the trail without present(delta)")
	state.labels.append("MUTATED")
	state.ratio = 99.0
	check(hud.debug_state() == frozen, "debug_state returns an independent snapshot")
	check(hud.get_child_count() == 3 and get_nodes_in_group("camp-boss-hud").is_empty(), "no transient effects, timer nodes or global registration")
	# User replaced the percentage/center banner, not ratio authority or pause.
	present("waiting")
	hud.present_ultimate("WIND REQUIEM", "CHARGE", true, VIEW)
	check(not hud.visible and not hud.debug_state().ultimate.visible, "legacy ultimate API never draws a centered banner")
	for title: String in CAST_TITLES:
		for character: String in title + "！":
			check(cast_font != null and cast_font.has_char(character.unicode_at(0)), "packaged CJK glyph exists without system fallback: " + character)
	for dimensions: Vector2 in [Vector2(320, 200), Vector2(320, 568), VIEW, Vector2(2304, 1440), Vector2(2560, 1440)]:
		for title: String in CAST_TITLES:
			var anchor := dimensions * Vector2(0.50, 0.55)
			hud.present("fighting", 0.42, anchor, dimensions, true, true, true)
			var before: Dictionary = hud.debug_state()
			hud.present_cast(title + "！", anchor, dimensions, true)
			state = hud.debug_state()
			var cast: Dictionary = state.cast
			check(cast.visible and cast.glyphs_complete and cast.text == title + "！",
				"complete readable Chinese name and one full-width exclamation: " + title + " " + str(dimensions))
			check(cast.layout == "actor_bubble" and Rect2(Vector2.ZERO, dimensions).encloses(cast.rect), "actor-local bubble cannot overflow")
			check(not cast.rect.intersects(state.rect) and not cast.rect.intersects(cast.controls_rect)
				and not cast.rect.intersects(cast.caption_rect) and not cast.rect.intersects(cast.face_rect), "bubble clears bar, controls, caption and face")
			check(cast.pointer.size() == 3 and cast.font_size >= 13 and cast.lines.size() <= 2, "one small pointer and legible bounded text")
			check(state.ratio == before.ratio and state.trail_ratio == before.trail_ratio and state.trail_delay == before.trail_delay,
				"cast text cannot mutate health or its cosmetic trail")
			check(not state.ultimate.visible, "new cast never restores ULTIMATE top text")
	present("fighting", 0.6)
	hud.present_cast("  穿林风矢！！!  ", HEAD, VIEW, true)
	check(hud.debug_state().cast.text == "穿林风矢！", "caller-provided punctuation is normalized to exactly one full-width exclamation")
	hud.present_cast("凤凰星火！", HEAD, VIEW, true)
	var held_cast: Dictionary = hud.debug_state().cast.duplicate(true)
	hud.present_ultimate("", "", false, VIEW)
	check(hud.debug_state().cast == held_cast, "old hide calls cannot interfere with the new actor bubble")
	for index in range(10):
		hud.present_cast("凤凰星火！", HEAD, VIEW, true)
		check(hud.debug_state().cast == held_cast, "same title/anchor/viewport is idempotent")
	await process_frame
	await process_frame
	check(hud.debug_state().cast == held_cast, "paused bubble has no independent timeout or phase advancement")
	hud.present_cast("符文天崩！", HEAD + Vector2(150, 40), VIEW, true)
	check(hud.debug_state().cast.text == "符文天崩！" and hud.debug_state().cast.anchor == HEAD + Vector2(150, 40),
		"new caster replaces the sole existing bubble, never creates a stack")
	hud.present_cast("风之镇魂曲".repeat(8) + "！", Vector2(160, 130), Vector2(320, 568), true)
	state = hud.debug_state()
	check(state.cast.visible and state.cast.truncated and state.cast.lines.size() == 2
		and state.cast.text.ends_with("！"), "unexpected long name wraps/truncates visibly without overflowing 320px")
	for line: String in state.cast.lines:
		check(cast_font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, state.cast.font_size).x <= state.cast.body_rect.size.x - state.cast.padding * 2.0,
			"real subset font measurement fits every rendered line")
	hud.set_cast_font(null)
	hud.present_cast("穿林风矢！", HEAD, VIEW, true)
	check(not hud.debug_state().cast.visible and hud.debug_state().cast.hidden_reason == "missing_cast_font", "missing packaged font never produces tofu or silently borrows a system font")
	var empty_font := FontFile.new()
	empty_font.allow_system_fallback = false
	hud.set_cast_font(empty_font)
	hud.present_cast("穿林风矢！", HEAD, VIEW, true)
	check(not hud.debug_state().cast.visible and hud.debug_state().cast.hidden_reason == "missing_cast_glyph", "missing glyphs fail closed instead of drawing hexadecimal boxes")
	hud.set_cast_font(cast_font)
	hud.present_cast("穿林风矢" + String.chr(0x10ffff), HEAD, VIEW, true)
	check(not hud.debug_state().cast.visible, "unsupported new name cannot masquerade as a complete Chinese title")
	for dimensions: Vector2 in [Vector2.ZERO, Vector2(100, 100), Vector2(INF, 800), Vector2(NAN, 800)]:
		hud.present_cast("穿林风矢！", HEAD, dimensions, true)
		check(not hud.debug_state().cast.visible, "invalid bubble viewport fails closed")
	hud.present_cast("！!!", HEAD, VIEW, true)
	check(not hud.debug_state().cast.visible, "punctuation-only names cannot draw empty bubbles")
	hud.present_cast("穿林风矢！", Vector2(NAN, 200), VIEW, true)
	check(not hud.debug_state().cast.visible, "nonfinite actor projection cannot place a bubble")
	hud.present_cast("", HEAD, VIEW, false)
	check(not hud.debug_state().cast.visible and hud.debug_state().visible, "hiding the bubble preserves the confirmed bar")

	# Damage is a supplied integer and owner-controlled 1.20s age, never a
	# random roll or subtraction inferred from the ratio held by this HUD.
	present("fighting", 0.6)
	var health_before: Dictionary = hud.debug_state()
	hud.present_damage(123, HEAD, VIEW, 0.0, false, true)
	state = hud.debug_state()
	check(state.damage.visible and state.damage.text == "123" and state.damage.amount == 123, "exact supplied damage appears, without randomization or formatting loss")
	check(state.damage.lifetime == 1.20 and state.damage.age == 0.0 and state.damage.alpha == 1.0, "damage starts fully visible at supplied age zero")
	var ordinary_size: int = state.damage.font_size
	hud.present_damage(123, HEAD, VIEW, 0.0, true, true)
	check(hud.debug_state().damage.font_size > ordinary_size and hud.debug_state().damage.heavy, "owner-supplied ultimate flag only enlarges the damage presentation")
	hud.present_damage(123, HEAD, VIEW, 0.11, false, true)
	check(hud.debug_state().damage.pop > 1.10 and hud.debug_state().damage.font_size >= ordinary_size, "brief local pop, not a viewport shake")
	hud.present_damage(123, HEAD, VIEW, 0.30, false, true)
	var early_damage: Dictionary = hud.debug_state().damage.duplicate(true)
	hud.present_damage(123, HEAD, VIEW, 1.10, false, true)
	var late_damage: Dictionary = hud.debug_state().damage.duplicate(true)
	check(late_damage.visible and late_damage.rect.get_center().y < early_damage.rect.get_center().y
		and late_damage.alpha < early_damage.alpha and late_damage.rise > early_damage.rise, "number floats upward and fades before the 1.20s boundary")
	for age: float in [0.0, 0.11, 0.30, 0.68, 1.05, 1.199]:
		for heavy: bool in [false, true]:
			hud.present_damage(6000, HEAD, VIEW, age, heavy, true)
			var held: Dictionary = hud.debug_state().damage.duplicate(true)
			hud.present_damage(6000, HEAD, VIEW, age, heavy, true)
			check(hud.debug_state().damage == held and held.visible, "repeated owner age never advances or restarts a damage animation")
			check(held.alpha >= 0.0 and held.alpha <= 1.0 and held.font_size >= 18, "damage remains bounded and readable")
	await process_frame
	await process_frame
	check(hud.debug_state().damage.age == 1.199 and hud.debug_state().damage.visible, "idle drawing cannot expire the owner's held final frame")
	for age: float in [-1.0, NAN, INF, 1.20, 3.0]:
		hud.present_damage(123, HEAD, VIEW, age, false, true)
		check(not hud.debug_state().damage.visible, "invalid or complete age clears the damage number")
	for amount: int in [0, -1]:
		hud.present_damage(amount, HEAD, VIEW, 0.0, false, true)
		check(not hud.debug_state().damage.visible, "nonpositive amount is not an invented hit")
	hud.present_damage(123, Vector2(NAN, 0), VIEW, 0.0, false, true)
	check(not hud.debug_state().damage.visible, "invalid damage anchor fails closed")
	hud.present_damage(123, HEAD, Vector2.ZERO, 0.0, false, true)
	check(not hud.debug_state().damage.visible, "invalid damage viewport fails closed")
	hud.present_damage(123, HEAD, VIEW, 0.0, false, false)
	check(not hud.debug_state().damage.visible, "explicit hide removes only the damage number")
	state = hud.debug_state()
	check(state.ratio == health_before.ratio and state.trail_ratio == health_before.trail_ratio
		and state.trail_delay == health_before.trail_delay, "all damage displays leave confirmed health and trail untouched")

	# Layout collision priority is deterministic in either invocation order.
	for dimensions: Vector2 in [Vector2(320, 200), Vector2(320, 568), VIEW, Vector2(2560, 1440)]:
		for heavy: bool in [false, true]:
			for reversed: bool in [false, true]:
				var cast_anchor := dimensions * Vector2(0.50, 0.55)
				var damage_anchor := dimensions * Vector2(0.65, 0.58)
				hud.present_cast("", cast_anchor, dimensions, false)
				hud.present_damage(0, damage_anchor, dimensions, 0.0, false, false)
				hud.present("paused", 0.42, cast_anchor, dimensions, true, true, true)
				if reversed:
					hud.present_damage(158, damage_anchor, dimensions, 0.11, heavy, true)
					hud.present_cast("天星裁决！", cast_anchor, dimensions, true)
				else:
					hud.present_cast("天星裁决！", cast_anchor, dimensions, true)
					hud.present_damage(158, damage_anchor, dimensions, 0.11, heavy, true)
				state = hud.debug_state()
				check(state.cast.visible and state.damage.visible, "both actor labels stay visible at " + str(dimensions) + " heavy=" + str(heavy))
				check(not state.damage.rect.intersects(state.cast.rect) and not state.damage.rect.intersects(state.rect), "damage avoids the bubble and long health bar in either call order")
				check(Rect2(Vector2.ZERO, dimensions).encloses(state.damage.rect) and not state.damage.rect.intersects(state.damage.controls_rect)
					and not state.damage.rect.intersects(state.damage.caption_rect), "damage respects screen/control/caption bounds")
				frozen = state.duplicate(true)
				hud.present("paused", 0.42, cast_anchor, dimensions, true, true, true, 99.0)
				check(hud.debug_state() == frozen, "pause/SYNC with large delta cannot progress bubbles or damage")

	state = hud.debug_state()
	state.cast.lines.append("MUTATED")
	state.damage.amount = 999999
	check(not hud.debug_state().cast.text.contains("MUTATED") and hud.debug_state().damage.amount == 158, "nested diagnostic copies cannot mutate overlays")
	test_cast_actor_exclusions()
	for child: Control in [bubble, damage]:
		check(not child.is_processing() and not child.is_physics_processing() and child.get_child_count() == 0, "overlays have no clock, spawned child effects or input focus")
	hud.present_cast("", HEAD, VIEW, false)
	hud.present_damage(0, HEAD, VIEW, 0.0, false, false)
	present("waiting")
	check(not hud.visible and not canvas.visible and not bubble.visible and not damage.visible, "all explicit hides clear the owner layer")
	scene.remove_child(hud)
	hud.request_ready()
	scene.add_child(hud)
	check(not hud.visible and hud.get_child_count() == 3 and not hud.debug_state().cast.visible and not hud.debug_state().damage.visible,
		"re-ready retains three controls without stale bubbles or damage")
	check(present().visible, "fresh sample works after re-ready")
	scene.free()
	check(not is_instance_valid(canvas) and not is_instance_valid(bubble) and not is_instance_valid(damage), "all draw Controls are freed by their HUD owner")
	print("CAMP_BOSS_HUD_TEST: %s checks=%d failures=%d" % ["PASS" if failures == 0 else "FAIL", checks, failures])
	quit(0 if failures == 0 else 1)

func test_cast_actor_exclusions() -> void:
	# Hand-read body envelopes from the ORIGINAL 2560x1440 day-seq-007.png,
	# not an upscaled image or a live-renderer geometry claim. The captured
	# 16:10 world starts at x=128 and stretches its 1280x800 HUD by 1.8.
	# Hero is left of Boss, but both are right of the SCREEN midpoint.
	var shot_origin := Vector2(128, 0)
	var shot_scale := 1.8
	var shot_bodies: Array[Rect2] = [Rect2(1444, 808, 54, 72), Rect2(1482, 845, 36, 50), Rect2(1480, 627, 209, 232)]
	var bodies: Array[Rect2] = []
	for body: Rect2 in shot_bodies:
		bodies.append(Rect2((body.position - shot_origin) / shot_scale, body.size / shot_scale))
	var hero_anchor := Vector2(747, 444)
	var others: Array[Rect2] = [bodies[1].grow(6.0), bodies[2].grow(6.0)]
	hud.present_damage(0, HEAD, VIEW, 0.0, false, false)
	hud.present("fighting", 0.4, hero_anchor, VIEW, true, false, false)
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true)
	var legacy: Dictionary = hud.debug_state().cast
	var legacy_shot := Rect2(shot_origin + legacy.rect.position * shot_scale, legacy.rect.size * shot_scale)
	check(legacy.visible and legacy_shot.intersects(shot_bodies[2]),
		"reproduces v166: four-argument screen-right placement crosses actual QHD Boss chest when actor bounds are absent")
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, others)
	var fixed: Dictionary = hud.debug_state().cast
	var fixed_shot := Rect2(shot_origin + fixed.rect.position * shot_scale, fixed.rect.size * shot_scale)
	check(fixed.visible and fixed.prefer_left and fixed.body_rect.end.x < hero_anchor.x,
		"explicit hero side moves the real QHD case to the hero's left, not the screen's right")
	check(fixed.font_size == legacy.font_size and fixed.body_rect.size == legacy.body_rect.size and fixed.text == legacy.text,
		"overlap fix changes placement only, not accepted font, dimensions or name")
	for body: Rect2 in shot_bodies:
		check(not fixed_shot.grow(3.5).intersects(body), "QHD bubble/pointer clears all three visible body envelopes")
	check(Rect2(Vector2.ZERO, Vector2(2560, 1440)).encloses(fixed_shot), "QHD shot-space rectangle remains bounded after one coordinate conversion")
	print("CAMP_CAST_QHD_REGRESSION: old=%s fixed=%s boss=%s" % [legacy_shot, fixed_shot, shot_bodies[2]])
	# Main passes OTHER actors only. The caster keeps its existing _face
	# guard so its own registered head/quad cannot reject the small pointer.
	for setup: Array in [["hero", hero_anchor, "风之镇魂曲！", true, 0],
		["pet", Vector2(767, 463), "灵角辉光！", true, 1],
		["boss", Vector2(812, 340), "符文天崩！", false, 2]]:
		for dimensions: Vector2 in [VIEW, Vector2(320, 200), Vector2(2560, 1440)]:
			var factor := dimensions.y / VIEW.y
			var side_margin := Vector2((dimensions.x - VIEW.x * factor) * 0.5, 0.0)
			var anchor: Vector2 = side_margin + setup[1] * factor
			var exclusions: Array[Rect2] = []
			for index in range(bodies.size()):
				if index != setup[4]:
					var body := bodies[index].grow(6.0)
					exclusions.append(Rect2(side_margin + body.position * factor, body.size * factor))
			hud.present("fighting", 0.4, anchor, dimensions, true, false, false)
			hud.present_cast(setup[2], anchor, dimensions, true, setup[3], exclusions)
			var state: Dictionary = hud.debug_state()
			check(state.cast.visible, "actor-local bubble stays visible with other-body exclusions: %s %s" % [setup[0], dimensions])
			for excluded: Rect2 in exclusions:
				check(not state.cast.rect.grow(2.0).intersects(excluded), "body plus pointer/shadow avoids every supplied actor quad")
			check(not state.cast.rect.intersects(state.cast.face_rect) and not state.cast.rect.intersects(state.rect)
				and not state.cast.rect.intersects(state.cast.controls_rect) and not state.cast.rect.intersects(state.cast.caption_rect),
				"existing caster face, caption, bar and controls remain protected")
			if dimensions == VIEW:
				check(state.cast.body_rect.end.x < anchor.x if setup[3] else state.cast.body_rect.position.x > anchor.x,
					"hero/pet prefer outside left, Boss prefers outside right even in the same screen half")
	# New per-frame bounds update an existing bubble; no stale obstacle cache,
	# caller-array aliasing, extra nodes, elapsed time or authority changes.
	hud.present("paused", 0.4, hero_anchor, VIEW, true, true, true)
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, others)
	var held: Dictionary = hud.debug_state()
	others.append(Rect2(Vector2.ZERO, VIEW))
	check(hud.debug_state() == held, "caller mutating its exclusion array cannot mutate a presented frame")
	others.pop_back()
	var detached: Dictionary = hud.debug_state()
	detached.cast.actor_rects.append(Rect2(Vector2.ZERO, VIEW))
	check(hud.debug_state() == held, "debug exclusion arrays are independent copies")
	for index in range(5):
		hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, others)
		check(hud.debug_state() == held, "same paused sample and bounds are deterministic")
	var reversed_rects: Array[Rect2] = []
	for other: Rect2 in others:
		reversed_rects.append(Rect2(other.end, -other.size))
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, reversed_rects)
	check(hud.debug_state().cast.rect == held.cast.rect, "negative-size projected rectangles normalize before exclusion")
	var blocked: Array[Rect2] = [Rect2(Vector2.ZERO, VIEW)]
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, blocked)
	check(not hud.debug_state().cast.visible and hud.debug_state().cast.hidden_reason == "no_safe_actor_space",
		"fully blocked frame never falls back onto a character body or a centered banner")
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, others)
	check(hud.debug_state().cast.visible and hud.debug_state().cast.rect == held.cast.rect, "fresh safe frame restores the same local placement")
	var invalid: Array[Rect2] = [Rect2(Vector2(NAN, 0), Vector2.ONE)]
	hud.present_cast("风之镇魂曲！", hero_anchor, VIEW, true, true, invalid)
	check(not hud.debug_state().cast.visible and hud.debug_state().cast.hidden_reason == "invalid_actor_rect", "nonfinite projection fails closed")
	check(hud.debug_state().ratio == held.ratio and hud.debug_state().trail_ratio == held.trail_ratio
		and hud.debug_state().trail_delay == held.trail_delay and hud.get_child_count() == 3, "placement never changes ratio/trail or the three-control pool")
	hud.present_cast("", HEAD, VIEW, false)
