# v53 月辉灵鹿：生成与选择记录

内置 image_gen，四个请求同时发出，未使用 CLI/API 后备。每个提示词显式包含“八方旅人2”。同一灵鹿的四帧图集只作为一个个体使用，PNG 原样复制，无脚本抠图/重绘/缩放。

## 共用提示词（原文）

Use case: stylized-concept.
Asset type: game-ready transparent PNG animation sprite atlas for an existing Godot HD-2D meadow.
Primary request: 八方旅人2 (Octopath Traveler 2) inspired original moonlit spirit stag, nocturnal luminous animal, FOUR distinct gait frames of the SAME individual, not four different deer.
Scene/backdrop: genuinely transparent alpha background, all empty pixels fully transparent. No painted checkerboard, no solid background, no terrain, no pedestal, no scenery, no cast ground shadow.
Style/medium: premium detailed pixel-art JRPG sprite; crisp small deliberate pixel clusters, restrained 32-color shading, natural slender deer anatomy, refined HD-2D material, NOT a photograph, NOT smooth cartoon, NOT vector sticker.
Subject: silver-grey fallow stag, subtle pale blue-green luminous branching antler tips and sparse tiny luminous flank spots, warm grey fur shadow planes. Small natural antlers, readable at small game scale. No neon outline around the whole animal, no giant bloom, no diffuse aura outside silhouette.
Layout: square canvas divided into exactly 2 by 2 equal invisible cells. Each cell contains exactly one full body frame, facing RIGHT in identical side-three-quarter view with slight 15-degree downward camera view. Head, shoulders, body length, antlers and ground baseline stay registered and same scale in all four cells. Full antlers and all hooves inside each cell with 8% transparent safety padding.
Animation: top-left calm contact/stand pose (all feet down), top-right walking passing pose, bottom-left gentle trotting stride extended, bottom-right opposite passing pose. Clearly different leg positions, natural four-legged gait. The hooves stay at the same baseline. No detached particles or light sparks.
Lighting: neutral cool moon-compatible top-right form highlights; render identifiable pale antler cores for engine emission mask but retain detail and texture; no black flat silhouette.
Constraints: all four poses fully visible, no extra animals, no captions, no text, no logo, no watermark, true alpha edges without white matte.

## 四张候选追加句（原文）

A. Variant A: pearl-silver short fur, understated teal antler tips, compact symmetrical antlers and fine dappled flank markings.

B. Variant B: soft ash-grey fur with ivory neck, narrow organic antlers whose tips glow faint silver-cyan, a restrained arc of 6 tiny luminous flank spots.

C. Variant C: slightly darker slate-silver coat, pale throat and tail, modest luminous moss-green antlers, compact clear outline and very readable hooves.

D. Variant D: cool taupe coat with silver-white top planes, elegant small branching antlers with moon-white tips, tiny blue-green fur speckles.

## 选择

- A：鹿角及体侧发光装饰较多；72.94% 全透明。
- **B：选用。** 六枚左右的体侧光斑较克制，灰毛保留明暗层次，四帧头身位置比较一致。73.57% 全透明，四格边缘均无不透明越界像素。
- C：鹿角更绿、光斑更多；71.96% 全透明。
- D：鹿角较白、体侧花纹更密；74.11% 全透明。
- 四候选均为1254×1254、2×2分格，四种腿姿。最终脚锚根据实际不透明蹄尖分别校准，不按图片底边定位。

项目资产：`godot/assets/creatures/moon-stag-v53.png`

SHA-256：`983D40F9AAD22E69B8FFD2D37909CF901EA9F73C4237DFD92014C6FB54544BF8`

生成原件目录：`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`

- A：`exec-95942702-9906-4db0-9853-035736272480.png`
- B：`exec-128faa8e-9fcd-4ef9-8fda-f34e442d51e8.png`
- C：`exec-2df4a62b-0e90-4681-af2f-7de94e3f52ef.png`
- D：`exec-a3de9b80-0f20-4e80-8efe-dd024691a0b8.png`

源图保留真正的alpha。光晕使用场景内深度测试的柔光片，草地补光来自随身体移动的 OmniLight3D，未把一大圈光晕烘焙进动物底图。
