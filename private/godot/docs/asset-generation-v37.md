# v37 · 起伏草甸、林缘与河道材质

2026-09-08，在 `E:\Projects\Godot-Octopath2` 的本地 Windows 恢复副本制作。

## 制作约束

- 使用 **内置 imagegen**，不是 CLI/API 回退。每种图集/材质均同时请求四个候选，再人工看图选一个。
- 每个提示词明确包含 **八方旅人2**。参照用户的晴天大平原画风；不生成或铺设整张完整场景背景。
- v37 新增三个图集，每张有八个不同设计，共 24 个独立小资产。每个选中 UV 区域只摆一次，代码检测重叠复用。
- 保留原始 PNG alpha，未使用涂白、颜色替换或程序重绘。三个图集实际均为 1254×1254，提示词中的尺寸要求不代表生成工具实际输出尺寸。
- 只读像素检查：所选 24 个区域分隔处 alpha 为 0；各区域 alpha > 0.22 的可见像素没有红色底污染。网页另检查透明轮廓。图集中透明像素的 RGB 可能带颜色，但并不等于可见背景。
- 新水纹是连续材质，见 `asset-generation-v37-water.md`；连续表面采样不属于重复摆放同一个独立道具。

## 已入库文件

| 图集 | 选中 | 工程路径 | 原因 |
| --- | --- | --- | --- |
| 低矮草甸/河岸植物 | A | `assets/foliage/meadow-patches-v37.png` | 绿色克制、轮廓不规则、各组完整分离 |
| 低矮石灰岩层 | C | `assets/terrain/limestone-ledges-v37.png` | 岩块风化与冷暖层次更自然，不带多余瀑布 |
| 林缘树组 | A | `assets/foliage/woodland-groups-v37.png` | 树冠完整，树形变化充足，上缘没有被裁切 |
| 河水表面材质 | B | `assets/materials/river-ripples-v37.png` | 碎波细节充分、白色高光更克制 |

图集不是把同一棵树换位置：每个区域分别绘制，8 组林缘里各棵树也具有不同轮廓。场景最终保留 44 个不重复美术元素，旧的两个宽顶台地卡片退出当前场景，但源文件未删除。

## 原始候选文件

以下文件保留在 `C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。工程消费的选中版本已复制到上面的工作区路径，不依赖此目录。

| 批次 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 草甸 | `exec-750d5c0c-f53a-4620-b77d-356c6d61164e.png` | `exec-13c08e0c-49f1-41ea-94a2-f869864c6f61.png` | `exec-4c65eaec-77e0-4d09-abda-b155ed9ec4b8.png` | `exec-64f543c7-3381-42b5-8490-c9276dc5d800.png` |
| 岩层 | `exec-ac60ad38-7107-48de-b25b-117491833042.png` | `exec-e11e8369-9995-4cdd-95a2-82a74ef82a55.png` | `exec-22761635-9732-45c7-be46-0f21c88f5f09.png` | `exec-8c518356-fc1c-4697-b939-d1e21f0612db.png` |
| 林缘 | `exec-73ff7676-0f2d-46d8-ad26-9b7fc64141fa.png` | `exec-63b974a3-c00e-43b1-b1c9-14bd3df7a879.png` | `exec-3aa08ae3-ab59-4e11-be55-81afffcda769.png` | `exec-d2ece650-71cb-45f5-911a-f1840e4b4d61.png` |

## 草甸图集提示词

Use case: stylized-concept.
Asset type: transparent RGBA game environment atlas for a modular Godot HD-2D plain.
Primary request: 八方旅人2 (Octopath Traveler II) style EIGHT DISTINCT low, WIDE wild meadow and riverbank vegetation patches. Detailed miniature environment art, crisp painterly leaf clusters with tiny square-edged texture accents, olive greens, dark blue-green contact shadows and warm golden sunlight from upper right, matching a sunny fantasy grassy plain. NOT a photograph.
Composition: square 2048x2048 sheet, EXACTLY 2 columns by 4 rows. Each of the 8 cells contains ONE different horizontally spreading cluster, around 3:1 silhouette width-to-height, completely separate, with clear fully transparent gutters and margins. Elevated front view looking down 25 degrees; full patch and its feet visible; no background scene. Patches have irregular ragged edges and many small isolated grass tufts at the edges, never an oval soil island, plinth or cut-earth slab. This is low groundcover 0.3-1m high, not potted plants and not big trees.
Eight designs, reading order: (1) long olive bramble hedge with a small chalky rock at left; (2) low white yarrow and golden meadow grasses spreading into short clover; (3) wet fern and sedge cluster curling around two dark stones; (4) young oak scrub beside a flattened limestone fragment; (5) ragged leafy bankside plants with a few slender reeds; (6) low thyme and heather around a weathered root; (7) scattered chamomile and grass hummocks with central gap; (8) long asymmetrical dry tufted grass and mossy broken rock seam.
Constraints: actual transparent alpha outside every plant, stone and tiny grass blade, including between plants. No white matte, no painted checkerboard, no colored backdrop or haze. No baked depth of field blur. No grid lines, labels, text, logo or watermark. No duplicate silhouettes. Full objects stay inside their own cell.

四个候选分别强调：A 自然克制的绿色及宽阔交叠叶片；B 更低密集植物与粗细变化岩石；C 疏松顶部、浓密地被及冷暖叶片；D 风塑轮廓与易读叶簇。

## 岩层图集提示词

Use case: stylized-concept.
Asset type: transparent PNG atlas of EIGHT UNIQUE grassy rocky bank face fragments for a modular Godot HD-2D environment.
Style explicitly: 八方旅人2 (Octopath Traveler II) quality environmental materials, sunny rolling meadow, beautifully detailed miniature diorama rock surfaces, tiny crisp leaf clusters, subtle painterly pixel texture. Warm upper-right sunlight and cool deep rock crevices.
Composition: square 2048x2048 sheet, EXACT 2 columns x4 rows, one isolated horizontally wide fragment in each cell. Clear transparent gutters 40 pixels or more and transparent outer margins. All eight separate fragments are different shapes and rock groupings.
Subject: low, WIDE natural weathered limestone escarpment faces, approximately 4:1 width to height, 0.6-1.5m tall in real-world scale. Uneven protruding broken rock columns, cracks and strata. Each has a THIN uneven grassy top lip with overhanging grass leaves, moss and a few tiny roots. Show mostly the FRONT ROCK FACE and only a tiny sliver of the grassy top; 25-degree downward elevated camera angle. Irregular curved face instead of perfectly straight masonry. The ends taper into loose small stones with no square cutoffs.
Eight different fragments: 1 sunlit honey limestone with dark recess left; 2 horizontal pale strata and low clover; 3 damp slate blue river rocks with moss; 4 crumbled limestone slope and ferns; 5 rounded limestone blocks with hanging roots; 6 jagged short ledge with tiny daisies; 7 broken layered rocks around narrow dark crack; 8 low grassy stony embankment with sparse sedge.
Constraints: real RGBA alpha transparency outside every stone and grass blade. No colored background, no checkerboard pixels, no white fringe, no external shadow matte. No floating island, no raised platform with broad top surface, no soil cross-section, no tileable entire scene, no sky, no trees, no lettering or grid lines. Crisp art; no baked blur.

四个候选分别强调：A 暖色浅灰岩与少量苔藓；B 更细碎粗糙的岩石与裂隙；C 克制金色亮面、冷阴影和圆润风化；D 侵蚀轮廓与两格少量常春藤。

林缘完整提示词及四个变化见 `asset-generation-v37-woodland.md`。水纹完整提示词及选择记录见 `asset-generation-v37-water.md`。

## 组合与视觉处理

- 台地顶部来自真实碰撞地形，不再用宽顶悬浮台地图片替代地面。岩层图片只负责局部细节。
- 草丛沿道路外缘、岩坡边缘、河岸组合；中央行走线与 Boss 空地不放树木或大岩块。
- 新宽草丛与林缘仅变形底部根带，不能把整个树冠拉成坡形。
- 重新调整草原纹理尺寸、斑块混合、叶片细节法线及接触阴影。
- 保留真实深度驱动景深；默认隐藏角色占位体，按 C 开启。它不是已实现的寻路或战斗系统。

当前仍有与参考图的差距：远景生态密度、自然侵蚀细节、统一像素颗粒与动态光影还需打磨；本轮不能视作 1:1 复刻完成。
