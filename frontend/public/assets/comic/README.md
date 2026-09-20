# Comic masthead assets

- `aigc-news-wordmark.webp`: transparent lettering prepared from the user's approved AIGC NEWS logo close-up. Displayed at up to 420 CSS pixels; the three glitch slices share one cached resource. The image contains no UI text or controls beyond the brand name.
- `digest-robot.webp`: independently generated robot illustration, converted from 1024px RGBA PNG to 640px transparent WebP. The robot is a separate decorative layer so it can extend beyond the newsletter frame. Text, subscription control, and card border remain native HTML/CSS.

The newsletter now uses `digest-robot-integrated.webp`, an integrated ink illustration with its own drawn explosion and hatching, replacing the separate flat CSS burst. Generated through the user-authorized imagegen fallback CLI (`gpt-image-2.5`), using the supplied newsletter close-up as reference. The reproducible prompt is in `digest-robot-integrated.prompt.txt`. Its alpha channel is preserved, resized to at most 700px and compressed to WebP quality 88.

The active logo and integrated robot total approximately 163 KB. Assets are local, have transparent backgrounds, and require no remote image service at runtime. Dark mode tones down the same images using CSS, with no duplicate image download. Mobile retains the original wordmark and dashboard.
