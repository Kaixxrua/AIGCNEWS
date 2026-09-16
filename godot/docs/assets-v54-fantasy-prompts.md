# v54 魔幻动物八帧图集：正式提示词

用户补充“游戏世界，动物可以魔幻点”后，停止旧现实动物队列。此前已返回的普通鹿候选不采用。改用以下四组，每组四并发，内置 image_gen，透明 PNG 原样保留；各图集仅实例化一个生物。

## 共用词

```text
Use case: stylized-concept
Asset type: production Godot HD-2D animal walk-cycle sprite atlas.
Primary request: Generate a NEW exactly eight-frame seamless locomotion cycle in the visual style of 八方旅人2 (Octopath Traveler 2), using the reference ONLY for the richly shaded pixel-art palette, camera and rendering. This is a fantasy game world: whimsical magical animal designs are wanted, not literal realistic fauna. Keep the SAME fantasy individual consistent across its eight frames.
Composition: exactly FOUR equal columns and TWO equal rows, eight frames in row-major order, one animal in each cell, fixed side view facing RIGHT, slight elevated RPG viewpoint. All eight cells share exactly the same scale, camera, body proportions, torso-centre registration and ground baseline at 89 percent of cell height. Complete body, feet, magical ear/antler ornaments and tail fit inside each cell with clear padding, ears/antlers do not cross cell borders.
Animation: frames are consecutive eighths of ONE complete natural gait cycle, not eight standing poses and not unrelated poses. Meaningful contact, weight-down, passing, weight-up, opposite contact, opposite down, opposite passing, opposite up. Readable fantasy quadruped anatomy, four correctly attached legs, front and back legs alternate, foot plants travel backward relative to body, recovery feet arc forward. Frame eight leads smoothly to frame one. Torso stays stable with only subtle purposeful weight shift; same coat markings and silhouette identity throughout.
Surface: restrained hand-placed pixel clusters, textured volumetric fur, clear small-game sprite readability, no smooth photorealistic render, no flat cartoon stickers, no strong outline.
Background: genuinely transparent RGBA alpha zero in all empty space including gaps between legs. NO checkerboard, NO white/black/color backdrop, NO ground, NO oval shadow, NO floor, NO glow sheet, NO gradient. Do not draw labels, frame numbers, grid lines, text, logos or watermarks.
```

## deer

参考（仅风格和相机）：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
DAYTIME BUD-ANTLER FAWN: an original small magical meadow deer with warm chestnut-sage fur, cream underside, two short asymmetrical twig antlers bearing a few jade-green leaf buds, tiny pale-gold speckles along the shoulder, dark small hooves. Gentle enchanting wild creature, slender not chibi, not a mount or boss. Reference middle row sets only palette and rendering; ADD the twig-and-leaf fantasy design, omit rabbit and fox. Eight consecutive quiet walking phases; twig antlers and leaf buds keep identical topology and position on the skull. Body/antler dimensions constant across the cycle.
```

## fox

参考（仅风格和相机）：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
DAYTIME GOLDEN-TAIL FOX: an original magical meadow fox with muted russet-ochre fur, dark green-charcoal legs, cream-gold chest, oversized soft tail ending in a warm honey-gold wisp-shaped tuft, a few small antique-gold curved markings on the cheek and flank. Fantastical but richly shaded HD-2D rather than mascot/cartoon. No fire, no hard glow outline, no floating particles or baked aura. Same unique enchanted fox in eight consecutive walking phases, with subtle delayed tail follow-through. Reference bottom row sets only shading and camera; do not copy as a plain realistic fox.
```

## hare

参考（仅风格和相机）：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
DAYTIME LEAF-EARED HARE: an original magical woodland-meadow rabbit with moss-brown and muted sage fur, long leaf-shaped ears tipped jade-green, a small pale-gold forehead marking, soft cream chest and a tiny tufted seedpod-like tail. Enchanting woodland creature, not chibi or cartoon. Reference top row sets only rendering/camera; make it clearly a fantasy leaf-eared creature. Eight sequential phases of ONE gentle low bounding cycle: compression, push-off, low flight, forepaw reach, forepaw contact, hind recovery, hind contact, settle. No exaggerated squash/stretch; stable head/ear identity and proportions. Keep all eight poses fully inside their equal cells.
```

## moon-stag

参考（仅风格和相机）：E:/Projects/Godot-Octopath2/godot/assets/creatures/moon-stag-v53.png

```text
The reference is identity/style only: the SAME single nocturnal moon stag, silver-gray fur with dark blue-gray undersides, branching ivory antlers with pale turquoise tips, few tiny pale cyan coat markings. No redesign. Generate eight sequential measured walking phases with stable antlers, head and torso; legs smoothly alternate. Fur must remain volumetric and not self-lit white; only antler tips and a few tiny cool markings are light-colored emission sources. DO NOT bake an external glow, aura, mist or ground light into the PNG; the engine adds these separately. Include the full antlers in all eight equally scaled cells.
```

## 每组 A/B/C/D 追加词

- A: Prioritize anatomical continuity and eight clearly different leg phases, with restrained texture detail.
- B: Prioritize the quiet weight-bearing cadence, registered shoulders and crisp readable feet.
- C: Prioritize smooth phase-to-phase movement while preserving the reference's shaded pixel clusters.
- D: Prioritize clean transparent margins, unchanged torso proportions and natural alternating foot plants.
