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
