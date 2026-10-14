# v54 动物八帧图集生成记录

方式：内置 image_gen；每种动物四并发生成候选，分别择优。参考图只用于身份/风格，新图集四列两行；不改写 PNG 像素，最终文件另存版本名。

## 四组共用完整提示词

```text
Use case: stylized-concept
Asset type: production Godot HD-2D animal walk-cycle sprite atlas.
Primary request: Generate a NEW exactly eight-frame seamless locomotion cycle in the visual style of 八方旅人2 (Octopath Traveler 2), matching the reference animal identity and richly shaded pixel-art palette.
Composition: exactly FOUR equal columns and TWO equal rows, eight frames in row-major order, one animal in each cell, fixed side view facing RIGHT, slight elevated RPG viewpoint. All eight cells share exactly the same scale, camera, body proportions, torso-centre registration and ground baseline at 89 percent of cell height. Complete body, feet and tail fit inside each cell with clear padding, ears/antlers do not cross cell borders.
Animation: frames are consecutive eighths of ONE complete natural gait cycle, not eight standing poses and not unrelated poses. Meaningful contact, weight-down, passing, weight-up, opposite contact, opposite down, opposite passing, opposite up. Coherent anatomy, four correctly attached legs, front and back legs alternate, foot plants travel backward relative to body, recovery feet arc forward. Frame eight leads smoothly to frame one. Torso stays stable with only subtle purposeful weight shift; same coat markings and silhouette identity throughout.
Surface: restrained hand-placed pixel clusters, textured volumetric fur, clear small-game sprite readability, no smooth photorealistic render, no flat cartoon stickers, no strong outline.
Background: genuinely transparent RGBA alpha zero in all empty space including gaps between legs. NO checkerboard, NO white/black/color backdrop, NO ground, NO oval shadow, NO floor, NO glow sheet, NO gradient. Do not draw labels, frame numbers, grid lines, text, logos or watermarks.
```

## 各组 Subject 追加词

### deer

参考：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
The reference is identity/style only. Use ONLY the middle-row natural brown doe (no antlers), slender warm tawny fur, cream belly and tail, dark small hooves. Omit rabbit and fox. Build a calm steady walking gait with subtle weight transfer, not jumping, galloping or morphing. Keep the back/shoulder height constant within two percent.
```

### fox

参考：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
The reference is identity/style only. Use ONLY the bottom-row russet fox, muted rusty ochre fur, charcoal stocking legs, cream throat and cream tail-tip, bushy horizontally trailing tail. Omit deer and hare. Build a fluid unhurried quadruped walking cycle with diagonal leg phasing and a gently following tail. Keep body length, tail length and muzzle identical throughout.
```

### hare

参考：E:/Projects/Godot-Octopath2/godot/assets/creatures/meadow-wildlife-v52.png

```text
The reference is identity/style only. Use ONLY the top-row wild brown hare with long ears, natural brown-speckled fur, cream underside and small pale tail. Omit deer and fox. For this species use eight phases of one low gentle bounding cycle: rear compression, hind-leg push, low airborne extension, forepaw reach, forepaw contact, hind legs recover, hind contact, settle. No exaggerated squash/stretch. Body moves vertically only subtly; natural low hop. Stable ears and identity.
```

### moon-stag

参考：E:/Projects/Godot-Octopath2/godot/assets/creatures/moon-stag-v53.png

```text
The reference is identity/style only: the SAME single nocturnal moon stag, silver-gray fur with dark blue-gray undersides, branching ivory antlers with pale turquoise tips, few tiny pale cyan coat markings. No redesign. Generate eight sequential measured walking phases with stable antlers, head and torso; legs smoothly alternate. Fur must remain volumetric and not self-lit white; only antler tips and a few tiny cool markings are light-colored emission sources. DO NOT bake an external glow, aura, mist or ground light into the PNG; the engine adds these separately. Include the full antlers in all eight equally scaled cells.
```

## A / B / C / D 各候选追加词

- A: Prioritize anatomical continuity and eight clearly different leg phases, with restrained texture detail.
- B: Prioritize the quiet weight-bearing cadence, registered shoulders and crisp readable feet.
- C: Prioritize smooth phase-to-phase movement while preserving the reference's shaded pixel clusters.
- D: Prioritize clean transparent margins, unchanged torso proportions and natural alternating foot plants.
