# v62 远城模块：内置 ImageGen 四并发

2026-09-09。使用 imagegen 技能，内置图像工具同时发出四个相同要求，不用CLI/API回退。根据已目视检查的用户晴天参考，用文字描述其密集沿坡城镇方向；本轮没有把整景图作为生成输入，不复制整景背景。

## 候选与选用

四张均有真实透明通道。只读 `audit_city_asset.gd` 扫描实际PNG，未改图。透明检查只是技术门槛，不是风格合格证明。

| 候选 | 尺寸 | 真透明像素 | 目视取舍 |
| --- | --- | ---: | --- |
| A | 2060×763 | 53.6632% | 上部围墙较大，低部密度略疏 |
| B | 2060×763 | 51.1351% | 中上部堡垒较宽，层间墙带更突出 |
| C | 2059×764 | 49.9704% | 建筑较密，但右高左低更极端、最高屋顶边距很窄 |
| D | 2060×763 | 57.8825% | 选用；小屋、拱道和植被分层更多，下部不规则缺口较自然 |

四张alpha>0.22区域的高红低绿色杂边计数均0，未据此承诺所有半透明边缘绝无杂色；还要检查实际导入后的日夜画面。

生成目录：`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。

- A：`exec-bbdd57d9-8a01-4de7-9470-5d76a7ce03ca.png`
- B：`exec-a25305bf-bbaf-4cb6-b614-8683809a09da.png`
- C：`exec-0d25f7f5-59dc-4d0e-acdd-3dcae094e6e3.png`
- D：`exec-b90f23f2-ce16-4423-a1b1-f40077e52397.png`

活动项目文件：`godot/assets/backgrounds/castle-town-v62.png`，原PNG逐字节复制，mipmaps=true、size_limit=0，旧v49源文件与v61预览保留。SHA-256：`9BFF8B629A35935D3C9308CF97767C8BE88A74B56DB231B57D9A5DA78B689C29`。

D的最高实像素峰值UV约(0.653715, 0.074803)。建筑主体恢复原图比例，只有地基带贴合真实地形。32处灯窗从新源图重新选择，局部只读明暗扫描帮助细调坐标；并检查整个窗灯矩形的1120像素均不落入透明区。算法不能判断一个暗点必然是窗户，最终仍以源图和夜景目视为准。

第一轮Web夜景中，小窗在缩小显示时过弱，因此继续改进像素覆盖取样和城镇专用的最小柔光晕尺寸，未扩大源图里的窗户矩形。源PNG始终不变，旧夜景截图与试验PCK保留用于对照。完整结果见 `verification-v62.md`。

## 完整提示词（四个并发相同）

Use case: stylized-concept.
Asset type: a single distant castle-and-hill-town cutout for a modular Godot HD-2D game; genuinely transparent RGBA PNG.
Primary request: 八方旅人2 / Octopath Traveler 2 visual feeling: a dense inhabited medieval hill-town stepping naturally up an irregular broad low hill toward a compact stone citadel. Fine hand-painted pixel clusters, coherent small architectural scale, warm aged limestone and muted slate roofs.
Composition: landscape cutout about 2.7:1, complete silhouette with slim transparent padding. A compact highest cluster slightly right of centre; many dozens of DISTINCT small overlapping houses, narrow roof groups, terraces and small towers cascade down both sides and spread widely along the base. The fortress crown occupies only about one fifth of the width; ordinary houses and irregular streets form most of the city, not a few giant towers. Asymmetrical stepped silhouette, multiple visible depths and gaps between clusters. Clear perspective from across a broad meadow, mild downward view, not top-down isometric.
Materials and lighting: olive-ochre warm-grey stone, dark desaturated brown and slate-blue tiled roofs, subtle moss at lower foundations, small recessed windows that can be lit later. Soft upper-right sun with cool restrained recesses. Readable crisp medium-scale texture clusters at game viewing distance, not photographic micro-noise, no blur, no painted fog.
Foundation: short irregular limestone feet, a few attached low shrubs and broken steps immediately beneath the lowest houses. Varied sloping lower silhouette; no straight horizontal plinth, no large vertical enclosing wall, no flat green lawn strip, no huge bare mountain underneath.
Output: true transparent alpha=0 outside the complete city silhouette, including open gaps. No backdrop at all: no sky, mountains, clouds, meadow, river, road outside town or ground rectangle. No floating island. Keep thin roof edges clean without pale fringe.
Avoid: giant central palace dominating the asset, sparse oversized towers, rows of identical houses, uniform horizontal terrace stripes, needle-spire forest, cathedral, vector outlines, white matte, black matte, checkerboard pattern, grid, text, labels, flags, logos or watermark. This is ONLY the independent city asset, not a full landscape.
