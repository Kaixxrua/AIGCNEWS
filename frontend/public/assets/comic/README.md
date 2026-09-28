# Comic masthead assets

- `aigc-news-wordmark.webp`: transparent lettering prepared from the user's approved AIGC NEWS logo close-up. Displayed at up to 420 CSS pixels; the three glitch slices share one cached resource. The image contains no UI text or controls beyond the brand name.
- `digest-robot.webp`: independently generated robot illustration, converted from 1024px RGBA PNG to 640px transparent WebP. The robot is a separate decorative layer so it can extend beyond the newsletter frame. Text, subscription control, and card border remain native HTML/CSS.

The newsletter now uses `digest-robot-integrated.webp`, an integrated ink illustration with its own drawn explosion and hatching, replacing the separate flat CSS burst. Generated through the user-authorized imagegen fallback CLI (`gpt-image-2.5`), using the supplied newsletter close-up as reference. The reproducible prompt is in `digest-robot-integrated.prompt.txt`. Its alpha channel is preserved, resized to at most 700px and compressed to WebP quality 88.

The light logo and integrated robot total approximately 163 KB. Assets are local, have transparent backgrounds, and require no remote image service at runtime. Mobile retains the original wordmark and dashboard.

`aigc-news-wordmark-night.webp` is a 55 KB night-specific derivative of the existing wordmark: its alpha edge is contracted by one source pixel at 3× working resolution and antialiased before export; lime is subdued and whites slightly softened. This removes the light extraction fringe against charcoal without changing the lettering. All three night glitch layers share the same cached image; the animation still uses their original pixels without neon tint.

The torn-paper stickers (`ComicSticker.vue`) are three painted layers laid over the page, each generated directly with `background=transparent` through the user-authorized image endpoint, with the user's torn-corner concept image as the style reference (the peel also took an earlier generated robot as its character reference); each prompt is next to its image (`*.prompt.txt`). Near-opaque alpha (≥245) was clamped to 255 and near-clear alpha (≤8) to 0, the canvas was trimmed to the drawing (keeping the corner that meets the viewport), resized and compressed to WebP quality 86:

- `tear-corner.webp` (720×406, 46 KB): the page's top-left corner torn away over lime, with "AI!", a bolt and a "BRIGHTER TOMORROW!" ribbon painted in.
- `tear-peel.webp` (720×720, 86 KB): the page's bottom-right corner torn diagonally, a robot punching up out of the lime with a "MORE CREATORS! / A BRIGHTER WORLD" label painted in.
- `tear-rip.webp` (900×229, 39 KB): a wide gash showing blank lime; the localized masthead slogan is live SVG text set into the opening.

The paper is painted cream-white, so the dark theme dims the layers with a CSS filter instead of shipping night variants.
