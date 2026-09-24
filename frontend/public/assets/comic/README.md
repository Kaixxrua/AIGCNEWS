# Comic masthead assets

- `aigc-news-wordmark.webp`: transparent lettering prepared from the user's approved AIGC NEWS logo close-up. Displayed at up to 420 CSS pixels; the three glitch slices share one cached resource. The image contains no UI text or controls beyond the brand name.
- `digest-robot.webp`: independently generated robot illustration, converted from 1024px RGBA PNG to 640px transparent WebP. The robot is a separate decorative layer so it can extend beyond the newsletter frame. Text, subscription control, and card border remain native HTML/CSS.

The newsletter now uses `digest-robot-integrated.webp`, an integrated ink illustration with its own drawn explosion and hatching, replacing the separate flat CSS burst. Generated through the user-authorized imagegen fallback CLI (`gpt-image-2.5`), using the supplied newsletter close-up as reference. The reproducible prompt is in `digest-robot-integrated.prompt.txt`. Its alpha channel is preserved, resized to at most 700px and compressed to WebP quality 88.

`digest-robot-cyan-burst.webp` is the version the dashboard serves. It is derived from `digest-robot-integrated.webp` without redrawing: lime-hued pixels (hue 40–110°, saturation above 0.18) are remapped along the ink-to-lime axis onto `#bfe9f7`, except inside the two eye regions, which keep their lime. This leaves lime to selected states and the subscribe button; the original file stays as the source.

The light logo and integrated robot total approximately 163 KB. Assets are local, have transparent backgrounds, and require no remote image service at runtime. Mobile retains the original wordmark and dashboard.

`aigc-news-wordmark-night.webp` is a 55 KB night-specific derivative of the existing wordmark: its alpha edge is contracted by one source pixel at 3× working resolution and antialiased before export; lime is subdued and whites slightly softened. This removes the light extraction fringe against charcoal without changing the lettering. All three night glitch layers share the same cached image; the animation still uses their original pixels without neon tint.
