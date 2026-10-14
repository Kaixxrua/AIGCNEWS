# v49 远景城镇四并发生成记录

2026-09-09。使用 imagegen 技能和内置 image_gen 工具，不使用 CLI/API fallback。两批，每批四个并发调用；逐张目视检查，所有提示词显式含“八方旅人2”。仅选第二批 C，未拼用其它候选，也未复制原图作为整景背景。

## 筛选与原图

第一批以用户原晴天参考图为视觉输入：
`E:/home_backup/home/kaixxrua/.codex/attachments/04e849e6-5128-4e5b-bb50-5d2dfaf85afa/codex-clipboard-d551c9b7-4fbb-4e83-bd86-48fecf5b6ed8.png`。
四张均为不透明棋盘格，真实透明像素全部 0%，全部拒绝；`city-batch1-alpha.log` 退出 1。

第二批不附图，用文字保留建筑层次、视角、暖石冷顶、真正透明 PNG 要求。Alpha 检查不代表美术相似度通过。

| 候选 | 尺寸 | 透明像素 | alpha>0.22 红色杂边像素 | 选择 |
| --- | --- | ---: | ---: | --- |
| A | 2020×779 | 47.6656% | 0 | 下部城墙较规则，未选 |
| B | 2022×778 | 55.3154% | 0 | 主堡过于突出、左侧较空，未选 |
| C | 2022×778 | 52.0217% | 0 | 选用；较多密集小屋、厚重主堡和不规则石脚 |
| D | 2022×778 | 49.1267% | 0 | 大片墙体与横向层带较多，未选 |

只读脚本 `tools/audit_city_asset.gd` 扫描真实 alpha、可见红色杂边、最高实像素和七个底边列。对假透明返回失败，已用 v47 已知假棋盘格作负样本确认。它不修改 PNG；低 alpha 或透明区域隐藏 RGB 不等于可见红边。本次四张第二批图均通过门槛；仍需在 Web 检查导入和远处采样。

## 选中源与接入

生成源目录：
`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。

项目资产：`godot/assets/backgrounds/castle-town-v49.png`，来自第二批 C，逐字节复制并核验 SHA256：
`39A5477142449389509464F3C376646207E3DC840BA497EA6E391ED3EA9923B6`。
未脚本抠图、涂色、缩放或重写 PNG；引擎正常导入启用 mipmaps 和 alpha border 处理。

原 v44 城镇保留在磁盘，当前场景和显式导出清单替换为 v49，非叠加双份城镇。整体依旧 66 个不重复图像元素。
新主塔 alpha 峰值 UV 为 (0.585849,0.002574)，基脚由运行时读取导入纹理 alpha，按列对应真实地形三角面；只改变下部基脚带网格，PNG 像素不变。这依然是远景美术网格，不是可环绕的完整三维建筑。

## 完整提示词

### 第1批 A

生成源：`exec-d115d0b3-e052-480c-8247-e35e598f81e7.png`

```text
Use case: stylized-concept.
Asset type: one isolated distant castle-and-town environment asset for a modular Godot HD-2D scene, genuine RGBA PNG.
Input image 1 is the user's original sunny meadow REFERENCE. Reconstruct ONLY the distant stone castle-town in the upper right-of-center, approximately x=0.50..0.94, y=0.04..0.29. Do not reproduce the whole landscape.
Primary request: closely match this reference's 八方旅人2 / Octopath Traveler II feeling and architecture. A wide, dense, warm-stone medieval hill-town rises in irregular terraces toward a dominant substantial rectangular central keep, slightly right of the centre, with several subordinate slate-blue roofed towers. Many small masonry and timber-roofed buildings nest closely on its lower slopes. Match the reference's weight, stepped broad base, roof-size hierarchy and somewhat compact square forms; do not substitute a row of skinny fairytale spires, a Gothic cathedral or a single huge empty fortress.
View: the same distant three-quarter, mildly elevated view as the reference; broad landscape asset, about 2.7:1. The actual city silhouette should be roughly 2.6 times wider than tall. Main highest tower near u=0.54. Left shoulder rises in unequal steps; low buildings and broken wall terraces fan out to the right. Complete silhouette with small clear margins.
Surface: warm gray-ochre aged stone, cool slate roofs, tightly clustered pixel-textured architectural details, recess shadows, restrained upper-right sun. Preserve reference-style compact HD-2D detail, not clean vector outlines or photorealistic building photography. Keep source detail crisp; no baked depth-of-field, glow or atmospheric white haze.
Foundation: include only the narrow irregular rocky feet directly under city walls and a little attached dark-green scrub. No giant isolated mountain, no floating island, no wide grass base, no ground rectangle, no surrounding meadow, no distant mountains, no river, no bridge, no windmills, no sky or clouds.
Mandatory transparency: all space outside the city silhouette must be real alpha=0. Output a genuinely transparent PNG, NOT an opaque checkerboard illustration. No white/gray/black/colored background, no white fringe, no matte, no grid, no labels, no text, no logos, no watermark, no bright red flags.
Candidate A: prioritize the reference's broad irregular silhouette and substantial rectangular central keep, with very dense small homes descending on both sides. Few modest peaked roofs, no needle-like spire forest.
```

### 第1批 B

生成源：`exec-83808601-08da-465e-acfa-75ab6190152a.png`

```text
Use case: stylized-concept.
Asset type: one isolated distant castle-and-town environment asset for a modular Godot HD-2D scene, genuine RGBA PNG.
Input image 1 is the user's original sunny meadow REFERENCE. Reconstruct ONLY the distant stone castle-town in the upper right-of-center, approximately x=0.50..0.94, y=0.04..0.29. Do not reproduce the whole landscape.
Primary request: closely match this reference's 八方旅人2 / Octopath Traveler II feeling and architecture. A wide, dense, warm-stone medieval hill-town rises in irregular terraces toward a dominant substantial rectangular central keep, slightly right of the centre, with several subordinate slate-blue roofed towers. Many small masonry and timber-roofed buildings nest closely on its lower slopes. Match the reference's weight, stepped broad base, roof-size hierarchy and somewhat compact square forms; do not substitute a row of skinny fairytale spires, a Gothic cathedral or a single huge empty fortress.
View: the same distant three-quarter, mildly elevated view as the reference; broad landscape asset, about 2.7:1. The actual city silhouette should be roughly 2.6 times wider than tall. Main highest tower near u=0.54. Left shoulder rises in unequal steps; low buildings and broken wall terraces fan out to the right. Complete silhouette with small clear margins.
Surface: warm gray-ochre aged stone, cool slate roofs, tightly clustered pixel-textured architectural details, recess shadows, restrained upper-right sun. Preserve reference-style compact HD-2D detail, not clean vector outlines or photorealistic building photography. Keep source detail crisp; no baked depth-of-field, glow or atmospheric white haze.
Foundation: include only the narrow irregular rocky feet directly under city walls and a little attached dark-green scrub. No giant isolated mountain, no floating island, no wide grass base, no ground rectangle, no surrounding meadow, no distant mountains, no river, no bridge, no windmills, no sky or clouds.
Mandatory transparency: all space outside the city silhouette must be real alpha=0. Output a genuinely transparent PNG, NOT an opaque checkerboard illustration. No white/gray/black/colored background, no white fringe, no matte, no grid, no labels, no text, no logos, no watermark, no bright red flags.
Candidate B: prioritize the layered stone retaining walls and close-packed smaller warm-stone buildings at the lower slope. Keep the same broad silhouette and compact dominant keep.
```

### 第1批 C

生成源：`exec-cf5150fb-6d47-40f4-ae6c-aa2bbf08bee3.png`

```text
Use case: stylized-concept.
Asset type: one isolated distant castle-and-town environment asset for a modular Godot HD-2D scene, genuine RGBA PNG.
Input image 1 is the user's original sunny meadow REFERENCE. Reconstruct ONLY the distant stone castle-town in the upper right-of-center, approximately x=0.50..0.94, y=0.04..0.29. Do not reproduce the whole landscape.
Primary request: closely match this reference's 八方旅人2 / Octopath Traveler II feeling and architecture. A wide, dense, warm-stone medieval hill-town rises in irregular terraces toward a dominant substantial rectangular central keep, slightly right of the centre, with several subordinate slate-blue roofed towers. Many small masonry and timber-roofed buildings nest closely on its lower slopes. Match the reference's weight, stepped broad base, roof-size hierarchy and somewhat compact square forms; do not substitute a row of skinny fairytale spires, a Gothic cathedral or a single huge empty fortress.
View: the same distant three-quarter, mildly elevated view as the reference; broad landscape asset, about 2.7:1. The actual city silhouette should be roughly 2.6 times wider than tall. Main highest tower near u=0.54. Left shoulder rises in unequal steps; low buildings and broken wall terraces fan out to the right. Complete silhouette with small clear margins.
Surface: warm gray-ochre aged stone, cool slate roofs, tightly clustered pixel-textured architectural details, recess shadows, restrained upper-right sun. Preserve reference-style compact HD-2D detail, not clean vector outlines or photorealistic building photography. Keep source detail crisp; no baked depth-of-field, glow or atmospheric white haze.
Foundation: include only the narrow irregular rocky feet directly under city walls and a little attached dark-green scrub. No giant isolated mountain, no floating island, no wide grass base, no ground rectangle, no surrounding meadow, no distant mountains, no river, no bridge, no windmills, no sky or clouds.
Mandatory transparency: all space outside the city silhouette must be real alpha=0. Output a genuinely transparent PNG, NOT an opaque checkerboard illustration. No white/gray/black/colored background, no white fringe, no matte, no grid, no labels, no text, no logos, no watermark, no bright red flags.
Candidate C: prioritize subdued warm stone lit from upper right, deep cool recesses and the reference's unequal tower hierarchy; small clustered structures must outnumber tall towers.
```

### 第1批 D

生成源：`exec-8cbe0165-8caf-41c8-ae9e-dca8b21b7cda.png`

```text
Use case: stylized-concept.
Asset type: one isolated distant castle-and-town environment asset for a modular Godot HD-2D scene, genuine RGBA PNG.
Input image 1 is the user's original sunny meadow REFERENCE. Reconstruct ONLY the distant stone castle-town in the upper right-of-center, approximately x=0.50..0.94, y=0.04..0.29. Do not reproduce the whole landscape.
Primary request: closely match this reference's 八方旅人2 / Octopath Traveler II feeling and architecture. A wide, dense, warm-stone medieval hill-town rises in irregular terraces toward a dominant substantial rectangular central keep, slightly right of the centre, with several subordinate slate-blue roofed towers. Many small masonry and timber-roofed buildings nest closely on its lower slopes. Match the reference's weight, stepped broad base, roof-size hierarchy and somewhat compact square forms; do not substitute a row of skinny fairytale spires, a Gothic cathedral or a single huge empty fortress.
View: the same distant three-quarter, mildly elevated view as the reference; broad landscape asset, about 2.7:1. The actual city silhouette should be roughly 2.6 times wider than tall. Main highest tower near u=0.54. Left shoulder rises in unequal steps; low buildings and broken wall terraces fan out to the right. Complete silhouette with small clear margins.
Surface: warm gray-ochre aged stone, cool slate roofs, tightly clustered pixel-textured architectural details, recess shadows, restrained upper-right sun. Preserve reference-style compact HD-2D detail, not clean vector outlines or photorealistic building photography. Keep source detail crisp; no baked depth-of-field, glow or atmospheric white haze.
Foundation: include only the narrow irregular rocky feet directly under city walls and a little attached dark-green scrub. No giant isolated mountain, no floating island, no wide grass base, no ground rectangle, no surrounding meadow, no distant mountains, no river, no bridge, no windmills, no sky or clouds.
Mandatory transparency: all space outside the city silhouette must be real alpha=0. Output a genuinely transparent PNG, NOT an opaque checkerboard illustration. No white/gray/black/colored background, no white fringe, no matte, no grid, no labels, no text, no logos, no watermark, no bright red flags.
Candidate D: prioritize the reference's rugged stepped masonry mass, broken low outer walls and dense roof rhythm. Keep the tallest keep just right of centre and do not enlarge the rocky foundation.
```

### 第2批 A

生成源：`exec-3b728cc2-797e-443d-968e-0599a9c2aa94.png`

```text
Use case: stylized-concept.
Create ONE genuinely transparent PNG game environment cutout: a broad distant medieval castle-town in the 八方旅人2 / Octopath Traveler II HD-2D visual style.
A substantial square stone keep stands slightly right of centre above a dense town. Warm gray-ochre masonry, dark slate-blue roofs, tightly packed small houses, terraced retaining walls. Irregular silhouette with a broad stepped base; few subordinate towers, not a forest of needle spires. Three-quarter slightly elevated view. Upper-right sunshine, cool recesses, fine compact pixel-textured detail, crisp edges with no baked blur.
Wide landscape composition, city silhouette roughly 2.6:1, tallest tower near horizontal 54%, small empty margin. Only narrow irregular rocky feet and a little attached scrub beneath the walls. No mountain or floating island.
Broad irregular silhouette, a substantial rectangular keep, and many small lower homes.
Output RGBA with actual zero-alpha empty pixels surrounding the city. This is an isolated game asset, NOT a rendered preview of transparency. Do not draw checkerboard squares, grid, backdrop, white fringe, sky, clouds, surrounding landscape, river, bridge, windmill, text, logo or red flags. Preserve clear transparent openings between the towers.
```

### 第2批 B

生成源：`exec-91ae5bbd-5709-459e-bedd-db294608a530.png`

```text
Use case: stylized-concept.
Create ONE genuinely transparent PNG game environment cutout: a broad distant medieval castle-town in the 八方旅人2 / Octopath Traveler II HD-2D visual style.
A substantial square stone keep stands slightly right of centre above a dense town. Warm gray-ochre masonry, dark slate-blue roofs, tightly packed small houses, terraced retaining walls. Irregular silhouette with a broad stepped base; few subordinate towers, not a forest of needle spires. Three-quarter slightly elevated view. Upper-right sunshine, cool recesses, fine compact pixel-textured detail, crisp edges with no baked blur.
Wide landscape composition, city silhouette roughly 2.6:1, tallest tower near horizontal 54%, small empty margin. Only narrow irregular rocky feet and a little attached scrub beneath the walls. No mountain or floating island.
Layered retaining walls and dense smaller buildings surrounding the compact keep.
Output RGBA with actual zero-alpha empty pixels surrounding the city. This is an isolated game asset, NOT a rendered preview of transparency. Do not draw checkerboard squares, grid, backdrop, white fringe, sky, clouds, surrounding landscape, river, bridge, windmill, text, logo or red flags. Preserve clear transparent openings between the towers.
```

### 第2批 C

生成源：`exec-3024d3d4-3d4d-4f3e-8f3e-2f4de38159f8.png`

```text
Use case: stylized-concept.
Create ONE genuinely transparent PNG game environment cutout: a broad distant medieval castle-town in the 八方旅人2 / Octopath Traveler II HD-2D visual style.
A substantial square stone keep stands slightly right of centre above a dense town. Warm gray-ochre masonry, dark slate-blue roofs, tightly packed small houses, terraced retaining walls. Irregular silhouette with a broad stepped base; few subordinate towers, not a forest of needle spires. Three-quarter slightly elevated view. Upper-right sunshine, cool recesses, fine compact pixel-textured detail, crisp edges with no baked blur.
Wide landscape composition, city silhouette roughly 2.6:1, tallest tower near horizontal 54%, small empty margin. Only narrow irregular rocky feet and a little attached scrub beneath the walls. No mountain or floating island.
Subdued warm stone, cool recesses, small clustered structures greatly outnumber tall towers.
Output RGBA with actual zero-alpha empty pixels surrounding the city. This is an isolated game asset, NOT a rendered preview of transparency. Do not draw checkerboard squares, grid, backdrop, white fringe, sky, clouds, surrounding landscape, river, bridge, windmill, text, logo or red flags. Preserve clear transparent openings between the towers.
```

### 第2批 D

生成源：`exec-0265c280-5dad-43a2-b528-85da719092ef.png`

```text
Use case: stylized-concept.
Create ONE genuinely transparent PNG game environment cutout: a broad distant medieval castle-town in the 八方旅人2 / Octopath Traveler II HD-2D visual style.
A substantial square stone keep stands slightly right of centre above a dense town. Warm gray-ochre masonry, dark slate-blue roofs, tightly packed small houses, terraced retaining walls. Irregular silhouette with a broad stepped base; few subordinate towers, not a forest of needle spires. Three-quarter slightly elevated view. Upper-right sunshine, cool recesses, fine compact pixel-textured detail, crisp edges with no baked blur.
Wide landscape composition, city silhouette roughly 2.6:1, tallest tower near horizontal 54%, small empty margin. Only narrow irregular rocky feet and a little attached scrub beneath the walls. No mountain or floating island.
Rugged stepped masonry, broken low outer walls and dense unequal roof rhythm.
Output RGBA with actual zero-alpha empty pixels surrounding the city. This is an isolated game asset, NOT a rendered preview of transparency. Do not draw checkerboard squares, grid, backdrop, white fringe, sky, clouds, surrounding landscape, river, bridge, windmill, text, logo or red flags. Preserve clear transparent openings between the towers.
```

