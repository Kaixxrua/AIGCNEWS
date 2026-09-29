# Comic masthead assets

These images are brand assets: © Kaixxrua, all rights reserved, and not covered by the repository's AGPL-3.0 license. Forks and public deployments must replace them — see the root `NOTICE`.

- `aigc-news-wordmark.webp`: transparent lettering prepared from the user's approved AIGC NEWS logo close-up. Displayed at up to 420 CSS pixels; the three glitch slices share one cached resource. The image contains no UI text or controls beyond the brand name.
- `digest-robot.webp`: independently generated robot illustration, converted from 1024px RGBA PNG to 640px transparent WebP. The robot is a separate decorative layer so it can extend beyond the newsletter frame. Text, subscription control, and card border remain native HTML/CSS.

The newsletter now uses `digest-robot-integrated.webp`, an integrated ink illustration with its own drawn explosion and hatching, replacing the separate flat CSS burst. Generated through the user-authorized imagegen fallback CLI (`gpt-image-2.5`), using the supplied newsletter close-up as reference. The reproducible prompt is in `digest-robot-integrated.prompt.txt`. Its alpha channel is preserved, resized to at most 700px and compressed to WebP quality 88.

The light logo and integrated robot total approximately 163 KB. Assets are local, have transparent backgrounds, and require no remote image service at runtime. Mobile retains the original wordmark and dashboard.

`aigc-news-wordmark-night.webp` is a 55 KB night-specific derivative of the existing wordmark: its alpha edge is contracted by one source pixel at 3× working resolution and antialiased before export; lime is subdued and whites slightly softened. This removes the light extraction fringe against charcoal without changing the lettering. All three night glitch layers share the same cached image; the animation still uses their original pixels without neon tint.

The torn-paper stickers (`ComicSticker.vue`) are three layers lifted pixel for pixel out of the user's approved concept images, not redrawn: the masthead shout from the "1-burst" concept, and the top-left corner and bottom-right peel from the "prev D" concept. Each region was cropped from the concept and the page around the drawing removed by flood-filling the near-white page from seeds outside it, with ink (luminance < 215) and colour (saturation > 40) as barriers. Hand-placed polygons erased the concept's own interface (its masthead rule, date, avatar, card borders and caption), and a zone polygon keeps the peel to its curl. Pixels the fill reached were converted colour-to-alpha against the page colour and unblended. The crops were upscaled 4× (Real-ESRGAN anime6B blended 60/40 with Lanczos so the halftone and paper grain survive), alpha clamped (≥250 to 255, ≤6 to 0) and exported to WebP quality 90 (alpha quality 95):

- `tear-corner.webp` (852×345, 50 KB): the page's top-left corner torn away over lime, with "AI!", a bolt, a "BRIGHTER TOMORROW!" ribbon crossing the masthead rule and the curled paper flap.
- `tear-shout.webp` (1101×324, 88 KB): a cyan hole torn from the masthead's top edge down to its rule, black ink shards around it and "让创造更自由！" brushed in.
- `tear-shout-blank.webp` (1101×324, 87 KB): the same hole with the lettering painted out (a diffusion fill plus halftone texture sampled from the surrounding colour), so another locale's slogan can be set into it as live SVG text.
- `tear-peel.webp` (1100×713, 47 KB): the page's bottom-right corner curling up off lime, with "MORE CREATORS! / A BRIGHTER WORLD" painted in.
- `tear-shout-seal.svg`, `tear-shout-seal-mask.svg` (6 KB, 1 KB): a torn paper edge in the shout image's coordinates. Where the masthead is too narrow for the shout at full size, the shrunken hole no longer reaches the page's top edge; the mask trims the painting above the tear and the seal draws its paper fibre and ink. They were generated from a seeded jagged line kept clear of the lettering.

The paper is cream-white, so the dark theme dims the layers with a CSS filter instead of shipping night variants.

The UI library cards are drawn frames rather than CSS borders, rendered procedurally (numpy/SciPy) to match the "ui-library-C" concept measured pixel by pixel, at 3× the concept's 311×291 card so they stay sharp on high-density screens. Each is used as a 9-slice `border-image`, so the corners keep their drawing at any card width:

- `ui-card-frame-{a,b}.webp` (957×900, ~63 KB each): cream paper with a faint grain and whiter rim, a wobbling 1.4–3.2px ink line (heavier along the top, lighter down the left), and a 45° halftone screen along the bottom and right edges that thickens into the corner, with a few stray dots bottom-left. Slices 48/552/450/192 keep the halftone out of the stretched edges.
- `ui-card-shadow-{a,b}.webp` (~21 KB each): the offset dry-brush shadow, dark navy at both ends of the bottom stroke and pale blue-grey between, pale teal down the right side darkening toward the corner. It is a separate layer so hover can lift the card off it.
- `ui-card-button-{source,prompt}.webp` (414×96, ~2 KB each): the two copy buttons, white and brushed navy, with the lower and right strokes pressed harder.

`a` and `b` use different seeds and alternate between neighbouring cards so the drawing does not repeat exactly. The `-night` files are the same drawings in the dark theme's paper, grey ink and dimmer halftone.

The DSH page (`/dsh`, "dsh-C" concept) is drawn the same way, with one generator for all of its pieces: each frame is one 3× 9-slice layer with a transparent middle, laid on `::after` around an element that paints its own fill. So one frame serves any fill (and the dark theme), and hover can change the colour under the ink. Every frame was calibrated to the concept's edge pixels; halftone patches sit in the bottom-right corner slice and the screen is orthogonal throughout, as in the concept.

- `dsh-panel.webp` (intro and abilities panels): a 1.9px wobbling ink line over a slate extrusion (5px right, 6px down) outlined in black and darkened where it meets the panel, with 7.3px dots in the corner.
- `dsh-stats.webp`, `dsh-stat.webp`: the four facts' outer box (2.2px navy line, solid navy shadow) and each fact's tile (1.4px line, a lighter second line inside its top and left, a pinch of teal dots).
- `dsh-disc-{cyan,mint}.webp`: the watercolour disc behind each fact's icon, with a brush tick off its lower left.
- `dsh-tab.webp`, `dsh-tab-active.webp`: the step tabs, with a heavy black block to the lower left and a speech-bubble wedge (filled in the tab's colour) hanging from it; the page skews them.
- `dsh-quota.webp`: the amber quota bar's thin line and warm dots at its right end.
- `dsh-method.webp`, `dsh-method-idle.webp`: the picked install method (solid black shadow) and the other one (slate extrusion), both with 6.4px dots dragged into short strokes and a line overshooting the lower-left corner.
- `dsh-nav.webp`: the step bar.
- `dsh-button.webp`, `dsh-button-ink.webp`: the white button (solid shadow, black dots) and the black one (white dots).
- `dsh-tag.webp`, `dsh-bubble.webp`: the lime kicker tag and the "推荐" speech bubble.

Together they are about 300 KB. The `-night` files swap the ink for pale grey, the extrusion for dark slate and the wedge fills for the dark theme's colours, and dim the dots.

The membership page (`/membership`, "membership-C" concept) uses the same generator. Its frames differ in one way: the cards' tops are not level, so each frame paints its own fill (`border-image … fill`) and the element paints nothing. The middle band of the top slice holds a straight ramp, which stays straight however wide the card is stretched.

- `mem-card.webp`, `mem-card-b.webp` (the guest and free cards): a 2.1px ink line whose top climbs 16–17px to the right, a navy extrusion (7.5px right, 10px down) outlined in black, and 7.2px halftone patches in the top-right and bottom-left corners, the dots shrinking as they leave the corner.
- `mem-card-vip.webp`: the taller vip card, its top climbing 12px, with a 14px lime spine ruled off down its left side.
- `mem-tag.webp`: the white tier-name slip, heavier along the bottom and right, its lines running past three corners; the page shears it.
- `mem-badge.webp`: the lime "推荐" flag with notched ends and a hard navy foot.
- `mem-toggle.webp`, `mem-chip.webp`: the billing switch (a wavering top, a hard-pressed bottom) and its lime discount chip.
- `mem-savings.webp`: the pale lime "年付省" slip with ragged ends.

Together they are about 230 KB. The `-night` files swap the fills for the dark theme's paper (the lime pieces for its dimmer lime), the ink for pale grey and the extrusion for dark slate, and dim the dots.
