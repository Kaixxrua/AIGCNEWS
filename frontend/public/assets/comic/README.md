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

The rest of the UI library page comes from the same generator as the pages below (3× 9-slice, each with a `-night` copy):

- `ul-search.webp`: the search, a thin slate line darkening along its foot, the pen pressed hard into the lower left corner with a little dry smudge under it.
- `ul-fw.webp`: the framework picker, grey along the top and black down the left, the foot and the right, over a teal dry-brush step to the lower right, with a streak of teal inside the corner.
- `ul-btn.webp`: the plain buttons (pause all, load more, the empty state's), an ink line all round with the teal corner.
- `ul-kind.webp`: the chosen material, a navy block whose line goes black along the foot and right, with a pale glint round the inside of its top left corner.
- `ul-side.webp`: the purpose index, a pale line along the top darkening down both sides to a black foot, a faint second stroke off the upper left, teal specks in the lower left and a soft grey step under it.
- `ul-rank-on.webp`: the chosen ranking, a lime pill in heavy ink with a glint and, beside it, the spark (a black tick, a green stroke, a faint dash).
- `ul-rank-a.webp`, `ul-rank-b.webp`, `ul-rank-open.webp`: the brackets round the next rankings, no box, only a pale foot with a curl at the top left and a hook down the right (the second inked darker toward the right), and the open brackets with a spark round the likes.
- `ul-badge.webp`: the framework tag on a card's preview, a white slip whose left side leans, with a black wedge under its lower right.

The controls and the index carry the frame as their own `border-image` (the index scrolls, and the frame stays put); the navy block, the lime pill and the slip bring their fill. Together they are about 130 KB.

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

The register page (`/register`, "register-C" concept) follows the membership page: each frame paints its own fill, so the slips can lean and tip past their boxes. The inputs and the terms box are plain ruled boxes in the concept and stay CSS.

- `reg-card.webp`: the 510px form card, a 2px ink line with a solid navy block (10.5px right, 8.5px down), 7.8px dots in the top-right corner, a dry band of fine dots running down just inside the right line, and a scuff of ink in the bottom-left corner.
- `reg-label.webp`: the lime field-label slip, leaning right, with a sliver of ink under its lower-left edge.
- `reg-otp.webp`: the white "获取验证码" slip, leaning right and tipped up, with a block to its lower right.
- `reg-submit.webp`: the lime submit bar, a heavy 2.8px line and a black block (5.5px right, 6px down).
- `reg-login.webp`: the white "已有账号？登录" slip, leaning and tipped like the code slip, with a thicker block.

Together they are about 80 KB. The `-night` files swap the fills for the dark theme's paper (the lime pieces for its dimmer lime), the ink for pale grey and the blocks for black, and dim the dots.

The subscriptions page (`/subscriptions`, "subscriptions-C" concept) uses the same generator. Each panel frame is rendered at its size in the concept, so the patches along its band stay where they were drawn instead of stretching. The fields, selects, stats and the digest's result tiles are plain in the concept and stay CSS; the target, crown, bell and chevron icons are small SVGs in the stylesheet.

- `sub-panel-hero.webp`, `sub-panel-watch.webp`, `sub-panel-plan.webp`, `sub-panel-digest.webp`, `sub-panel-auto.webp`: the five panels, a 2px ink line with a 5px band of ink to the lower right that turns green in patches, and sparse halftone in some corners.
- `sub-tag.webp`: the section tag, a tilted slip washing from white to lime along its left and bottom edges on a hard ink block, with a white flap folded over the panel's corner; the page tilts it.
- `sub-tag-tab.webp`: the plan tag in the hero, the same slip with a small tab where it wraps the panel's left line.
- `sub-live.webp`: the "自动追踪中" slip beside it.
- `sub-act.webp`: the row actions, white with a thin grey line pressed dark along the bottom and right.
- `sub-chip-kind.webp`, `sub-chip.webp`, `sub-pill.webp`: the rule's kind slip (with a speech tail at the lower left), its source chip and the lime "追踪中" pill.
- `sub-unlock.webp`: the unlocked band, lime under a ruled line that falls to the right.

Together they are about 150 KB. The `-night` files swap the fills for the dark theme's paper (the lime pieces for its dimmer lime), the ink for pale grey and the blocks for black, and dim the dots and the green patches.

The monitor page (`/monitor`, "monitor-C" concept) uses the same generator. The fields in the manual-sync dialog and the table's header band are plain in the concept and stay CSS; the job icons are the app's own icons plus the Hugging Face and GitHub marks in `components/icons`.

- `mon-side.webp`: the section nav, one box on a 2px ink line that thickens along the foot, with no block, a faint scatter of dots in two corners and a dark halftone patch in the bottom-right. The nav paints it as its own border image, so the frame stays put while the list scrolls.
- `mon-panel-sch.webp`, `mon-panel-tsk.webp`: the scheduler and task panels, a 2px ink line on a solid ink block to the lower right (about 4px across, 6px down), with halftone in the corners.
- `mon-tag.webp`: the panel tag, a white slip whose top climbs to the right, with a speech tail from its bottom-left corner, pale cyan washing in along the left and the foot, on an ink block.
- `mon-count.webp`: the count slip ("22 个任务", "共 48214 条"), a white parallelogram leaning right, heavier along its foot, with a grey block just under it.
- `mon-job.webp`: a scheduled job, a navy line round a pale blue-grey card with specks of halftone in three corners.
- `mon-row.webp`: a task row, a grey-blue hairline pressed darker along the foot and right side. A table row can't carry one frame, so each cell paints its own slice of the same image: the first cell takes the left edge, the last cell the right edge, the cells between only the top and bottom lines. Together they read as one card per row.
- `mon-btn.webp`, `mon-btn-navy.webp`, `mon-btn-red.webp`: the header buttons, white, navy (the primary one) and red-lined (the danger one), each heavier along the foot and right with a thin block under it.
- `mon-pg.webp`, `mon-pg-num.webp`, `mon-pg-on.webp`, `mon-pg-off.webp`: the pager, word buttons on navy, page numbers on a lighter line that darkens toward the foot, the current page on lime, and a spent button pale.
- `mon-badge-run.webp`, `mon-badge-ok.webp`, `mon-badge-fail.webp`: the status chips, a slightly tipped cyan, lime or red slip on a 2px ink line, with a nick of a tail at the lower left and a white glint in the lower-right corner.

Together they are about 250 KB. The `-night` files swap the fills for the dark theme's paper (the navy button and the current page for its dimmer lime), the ink for pale grey and the blocks for black, and dim the dots.

The report page (`/report`, "report-C" concept) uses the same generator. The status pill, the section text and the link marks are plain in the concept and stay CSS; the icons are the app's own.

- `rep-head.webp`: the controls panel, a 2.3px ink line on a flat grey block to the lower right, pale dots round the icon at the top left and teal halftone triangles in both right corners.
- `rep-sec.webp`: a report section, the same line pressed into a dark block along the right and the foot over the grey block, with faint dots at the top left and the teal triangles on the right.
- `rep-bar.webp`: the lime rule down a section's left, thick beside the title with a grey pencil flick, then thin. Its top holds still and the thin part stretches.
- `rep-tag.webp`: a section tag ("news", "LLM"), a white slip leaning right, heavier along its foot, on a dark block just under it.
- `rep-tab.webp`, `rep-tab-on.webp`: the source tabs, a navy pill on a light grey foot, and the open one lime on a black line and a black foot.
- `rep-btn.webp`: the subscribe button, white on an ink line with a grey block to the lower right.
- `rep-bubble.webp`: the AI notice, a speech bubble whose left side leans out with a tail off its lower left, the pen pressed harder along the left and the foot.

Together they are about 100 KB. The `-night` files swap the fills for the dark theme's paper (the open tab for its dimmer lime), the ink for pale grey and the blocks for black, and dim the dots.

The recommended websites page (`/websites`, "websites-C" concept) uses the same generator. The site names are set in Kalam Bold (`/fonts/kalam-700-latin-subset.woff2`, SIL OFL 1.1, licence beside it), standing in for the concept's hand lettering; names outside Latin fall back to the page font. The magnifier and the chevron are small inline SVGs.

- `web-card-lime.webp`, `web-card-cyan.webp`, `web-card-purple.webp`, `web-card-orange.webp`: a site card, a 2.3px ink line with a faint grey line just inside the top and left, pressed into a solid ink block to the lower right, and the accent's halftone filling a triangle off the lower-right corner. The cards take the four accents in the concept's order, repeating every eight.
- `web-tile.webp`: the monogram tile, a 2.2px ink line with a soft grey step to its lower right. It has no fill: the tile's colour is the element's own background, the card's accent, or white behind a site's logo.
- `web-tag-lime.webp`, `web-tag-cyan.webp`, `web-tag-purple.webp`, `web-tag-orange.webp`: the category slip, drawn level and turned in CSS, its right end standing taller, on a solid ink block.
- `web-tab.webp`, `web-tab-on.webp`: the collection tabs, parallelograms leaning left on an ink block, white with a few grey specks off the right end, and the open one lime.
- `web-search.webp`, `web-select.webp`: the search box and the category select, a 2.4px line on an ink block, with a pale yellow corner at the top left (specked on the search box, pen-hatched on the select), faint specks at the lower left and a grey screen at the lower right. Neither has a fill: form controls can't carry a pseudo-element, so the frame is the control's own `border-image` and its background paints the paper and the icon.

Together they are about 215 KB. The `-night` files swap the fills for the dark theme's paper (the open tab and the slips for dimmer copies of their colours), the ink for pale grey and the blocks for black, and soften the dots.

The X board (`/x`, "x-C" concept) uses the same generator. The tick in the account chips and the pager's chevrons are small inline SVGs.

- `x-card.webp`: a tweet card, a 2px ink line pressed into a solid ink block to the lower right, with a triangle of small mint-teal dots off the lower-right corner and a clump of heavier black dots set into it.
- `x-panel.webp`: the followed-accounts panel, a lighter line at the top and left and a heavy ink block to the lower right with a streak of deep blue in it; orange halftone rises off the lower right (with a black clump) and runs on along the foot, and a few orange specks sit under the top right.
- `x-pager.webp`: the pager strip, and the admin bar and the empty state: a pale grey line round paper, rounded 7px.
- `x-btn.webp`, `x-btn-off.webp`: the plain buttons (refresh, the accounts switch, the panel's two), a 2px ink line on a solid block; the disabled one a grey line on a grey step.
- `x-seg.webp`: one segment of the window switch, a navy line with a soft grey step; the date segment laps over the end of the first.
- `x-pg.webp`, `x-pg-off.webp`: the pager's buttons, a navy line heavier along the foot and right end; the disabled one pale grey.
- `x-ib.webp`: a card's icon buttons, a thin navy line with a grey hairline under it.
- `x-score.webp`: the score, a lime pill in ink, heavier along its foot, with a flick off its top right corner.
- `x-chip.webp`: an account chip, a thin line with an ink bracket down its right end that runs on past its top and foot.
- `x-badge.webp`: the panel title's mark, a yellow ink blot with a pen-stroked check.

Only the card, the panel, the pager strip and the score carry a fill; the buttons, the segments and the chips paint their own face (white, lime when chosen) and take the image as their `border-image`. Together they are about 110 KB. The `-night` files swap the fills for the dark theme's paper, the ink for pale grey and the blocks for black, and soften the dots.

The project catalog (`/projects`, "projects-C" concept) uses the same generator. The brush under the title, the slash before the lead and the corner wash on each card are CSS; the icons are the page's own.

- `p-card-cool.webp`, `p-card-lime.webp`, `p-card-warm.webp`: a project card, a 2.2px ink line pressed into a solid ink block 3px right and 2px down, with a triangle of halftone off the lower-right corner, dense at the corner and thinning to its diagonal. The three columns take steel blue, lime and gold in turn; the card's paper and its tinted corner wash are the element's own background.
- `p-side.webp`: the category index, a paper box off the page's left edge whose line thickens down its right, with pencil hatching in its top right and, fainter, its lower right.
- `p-active.webp`: the current category, a 1.6px line, a touch heavier along its foot, round the lime.
- `p-field.webp`: the search field and the sort select, an even 1.7px navy line, rounded 4px.
- `p-banner.webp`, `p-chev.webp`: the MCP strip's line round the lime band, and its chevron key.
- `p-tag.webp`: a card tag, a yellow highlighter outline going olive along its top.
- `p-pg.webp`: the pager's buttons, the field's line on a hard 2px ink block.

Only the index carries a fill; the rest take the image as a frame (a pseudo-element on the cards, the element's own `border-image` on the controls and tags) and paint their own face. Together they are about 210 KB. The `-night` files swap the fills for the dark theme's paper, the ink for pale grey and the blocks for black, and keep the dots in dimmer copies of their colours.

The MCP access page (`/mcp`, "mcp-C" concept) uses the same generator. The icons in the four facts sit on watercolour discs; the step numbers, the arrows between the steps and the spark after each section label are CSS.

- `mcp-card.webp`, `mcp-card-on.webp`: a client card, a thin line going from grey down the left to black along the top, the right and the foot, on a black block with navy and teal screen off the lower right; the chosen one in a heavier line on a black and a pale teal-grey block, its screen in dark green on the lime.
- `mcp-tab.webp`, `mcp-tab-on.webp`: a wizard step, a black line that lifts off the paper halfway down the left, with a band of screen down the right end; the current step on a lime-green block.
- `mcp-stat.webp`: a fact, a black line going grey down the right and the foot, on a soft grey block, with teal specks in the upper left.
- `mcp-side.webp`: the settings panel, its top left corner cut off, the pen darkening round to a black right and foot on a black block, with screens in both right corners.
- `mcp-slip.webp`, `mcp-pill.webp`: the leaning white slips of the section labels and the heading's three tags, the tags with the printer's second pass under their lower left.
- `mcp-term.webp`, `mcp-term-on.webp`: a terminal choice (and the endpoint field), a thin navy line; the chosen one on the lime with a patch of dark-green screen.
- `mcp-prev.webp`, `mcp-next.webp`: the back and next tickets, white and navy, pointed at the left, the navy one with a pale ghost of its outline.
- `mcp-disc-{teal,lavender,sky,peach}.webp`: the watercolour discs under the facts' icons.

The slips, tags and tickets carry their fill; the rest take the image as a frame and paint their own face. Together they are about 230 KB. The `-night` files swap the fills for the dark theme's paper (the navy ticket for pale grey), the ink for pale grey and the blocks for black, and dim the screens and the discs.

The paper reader (`/papers/:id/read`, "paper-read-C" concept) uses the same generator. The lime tab at the summary card's left edge is CSS.

- `pr-head.webp`, `pr-sum.webp`: the paper's heading card and its summary card, a fine navy line (the summary's firmer) pressed into a black block about 8.5px right and down, with a triangle of sky-blue screen off the lower right. The summary card also frames the conversation when the reader is signed in.
- `pr-cta.webp`: the sign-in strip, a thin line on a black block with a band of fine cyan screen down its right end.
- `pr-btn.webp`: its button, a 2.3px line, 6px round and heavier along the foot, on a thin black block, round the lime.
- `pr-slip.webp`: the date and link slips under the heading, cream, the right end leaning in, with the printer's second pass under the lower left.
- `pr-label.webp`: the summary's label slip, cream with its foot pressed hard; the element is turned in CSS.

The slips carry their fill; the rest take the image as a frame and paint their own face. Together they are about 190 KB. The `-night` files swap the fills for the dark theme's paper, the ink for pale grey and the blocks for black, and dim the screens.
