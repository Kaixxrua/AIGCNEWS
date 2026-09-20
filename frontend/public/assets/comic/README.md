# Comic masthead assets

- `aigc-news-wordmark.webp`: transparent lettering prepared from the user's approved AIGC NEWS logo close-up. Displayed at up to 420 CSS pixels; the three glitch slices share one cached resource. The image contains no UI text or controls beyond the brand name.
- `digest-robot.webp`: independently generated robot illustration, converted from 1024px RGBA PNG to 640px transparent WebP. The robot is a separate decorative layer so it can extend beyond the newsletter frame. Text, subscription control, and card border remain native HTML/CSS.

The combined transfer size is approximately 102 KB. Both assets are local, have transparent backgrounds, and require no remote image service at runtime. Dark mode tones down the logo using CSS, with no duplicate image download. Mobile retains the original wordmark and dashboard.
