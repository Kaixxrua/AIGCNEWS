# v47 低矮围栏四并发生成记录

2026-09-09。使用 imagegen 技能、内置 image_gen 工具；两批，每批四个并发调用，全部目视检查。所有提示词显式包含“八方旅人2”。没有使用 CLI/API fallback，没有拼用多个候选。

## 筛选证据

第一批以用户原晴天参考图为来源，只要求重建左下围栏。四张都生成了不透明棋盘格，真实透明像素 0%，全部拒绝，没有接入项目。`fence-batch1-alpha.log` 是旧统计工具的输出（退出码为 0 只表示读取完成，**不表示资产通过**）。

第二批去掉输入图，文字约束低矮、细木栏、四短柱三横杆、左近右远、真正 RGBA。

| 候选 | 尺寸 | 透明像素 | alpha>0.22 红底杂色 | 选择 |
| --- | --- | ---: | ---: | --- |
| A | 2172×724 | 77.9169% | 0 | 选用；三根横杆、灰褐旧木、轻微弯折比另外三张更贴近参考 |
| B | 2172×724 | 82.0720% | 0 | 仅两根明显横杆，未选 |
| C | 2171×724 | 79.1220% | 0 | 栏杆过直、立柱较圆整，未选 |
| D | 2172×724 | 74.6806% | 0 | 较厚重且笔直，未选 |

新增只读工具 `audit_fence_source.gd` 会对零透明/少量可见像素/高 alpha 红色底边返回失败，避免把“图读完了”误当通过。第二批四张均通过该 alpha 门槛；最终仍以造型选择 A。隐藏 RGB 可能含红色或黑色，这不是可见红边检测范围内的像素；没有修改 PNG 来掩盖。

## 选中源与接入

项目文件：`godot/assets/props/country-fence-v47.png`，从生成源逐字节复制，原像素与 alpha 不改。SHA256：`0C4AB30A6D46EC8EBF3B5C6F255B0C9F9AF39B24B0A97C26E35C27621F4FB3B7`。引擎启用 mipmaps 和正常 alpha 边缘导入处理。

四根柱中心 UV：`(0.085,0.964039)`、`(0.386,0.762102)`、`(0.642,0.582296)`、`(0.923,0.399723)`。根部行来自全分辨率 alpha>0.5 采样。素材只用一次，映射到随世界深度变化的网格，不是复制三段同一围栏。原 `foreground-fence-v2.png` 留在磁盘，不再进入当前导出。

生成源均保留在 `C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。

## 第一批：带参考图，拒绝全部

### 候选 A

源图：`exec-a0dec647-cc94-4754-a742-097426dd2bcc.png`

```text
Use case: background-extraction.
Asset type: one isolated, genuinely transparent RGBA PNG game environment prop.
Input image: the user's original meadow scene is the ONLY reference/source. Reconstruct ONLY the small weathered wooden fence in the LOWER LEFT FOREGROUND (roughly x=0.03..0.215, y=0.615..0.755 of the scene) as a detailed standalone asset. Do not redraw or include the landscape.
Primary request: faithful 八方旅人2 / Octopath Traveler II HD-2D style low country fence. Follow the reference's modest, slender, aged dark-brown timber rails and short uneven posts, NOT oversized tree-trunk gate pillars. The fence has about four short posts joined by three slim irregular horizontal rails in a shallow bending line. It stretches diagonally from the nearer LOWER LEFT towards the farther UPPER RIGHT. The right end stops before the existing lamp; do not include a lamp or sign.
Composition: one complete fence assembly, long and low, viewed slightly from above as in the reference. Preserve nearer-left / farther-right perspective and the gently rising screen-space root line. Full silhouette in frame with modest transparent padding. Landscape 3:1 image. Do not turn it into a front-elevation row or a bridge.
Materials: subtle cracked and worn chestnut/oak, compact pixel-textured chipped highlights, deep brown shaded sides, faint desaturated moss at the feet. A few tiny attached weeds are allowed, but no broad grass island, floor, soil slab or cast-shadow backdrop.
Lighting: restrained warm upper-right sunlight, not a golden glow or blown-out rim; preserve deep dark wood. Crisp asset detail, no baked blur, no artificial outline.
Mandatory alpha: all empty regions AND gaps between rails must have real zero alpha. NOT a checkerboard picture, NOT a white/gray/black or colored background. No haze, glow, floor gradient, grid, labels, text or watermark. Output only this fence, no rocks, trees, mountains, buildings, path, sky or river.
Candidate A: closest reconstruction of the reference fence; a subtle shallow curve and fine gray-brown weathered grain; keep rail thickness modest.
```

### 候选 B

源图：`exec-0644c3fe-7eb2-4634-a04e-078a43dda9e8.png`

```text
Use case: background-extraction.
Asset type: one isolated, genuinely transparent RGBA PNG game environment prop.
Input image: the user's original meadow scene is the ONLY reference/source. Reconstruct ONLY the small weathered wooden fence in the LOWER LEFT FOREGROUND (roughly x=0.03..0.215, y=0.615..0.755 of the scene) as a detailed standalone asset. Do not redraw or include the landscape.
Primary request: faithful 八方旅人2 / Octopath Traveler II HD-2D style low country fence. Follow the reference's modest, slender, aged dark-brown timber rails and short uneven posts, NOT oversized tree-trunk gate pillars. The fence has about four short posts joined by three slim irregular horizontal rails in a shallow bending line. It stretches diagonally from the nearer LOWER LEFT towards the farther UPPER RIGHT. The right end stops before the existing lamp; do not include a lamp or sign.
Composition: one complete fence assembly, long and low, viewed slightly from above as in the reference. Preserve nearer-left / farther-right perspective and the gently rising screen-space root line. Full silhouette in frame with modest transparent padding. Landscape 3:1 image. Do not turn it into a front-elevation row or a bridge.
Materials: subtle cracked and worn chestnut/oak, compact pixel-textured chipped highlights, deep brown shaded sides, faint desaturated moss at the feet. A few tiny attached weeds are allowed, but no broad grass island, floor, soil slab or cast-shadow backdrop.
Lighting: restrained warm upper-right sunlight, not a golden glow or blown-out rim; preserve deep dark wood. Crisp asset detail, no baked blur, no artificial outline.
Mandatory alpha: all empty regions AND gaps between rails must have real zero alpha. NOT a checkerboard picture, NOT a white/gray/black or colored background. No haze, glow, floor gradient, grid, labels, text or watermark. Output only this fence, no rocks, trees, mountains, buildings, path, sky or river.
Candidate B: same reference silhouette and perspective, with slightly more irregular rail edges and gentle differences in post heights, never thickening the timbers.
```

### 候选 C

源图：`exec-e5d5e104-04bc-49a4-9c5a-d1b811767c44.png`

```text
Use case: background-extraction.
Asset type: one isolated, genuinely transparent RGBA PNG game environment prop.
Input image: the user's original meadow scene is the ONLY reference/source. Reconstruct ONLY the small weathered wooden fence in the LOWER LEFT FOREGROUND (roughly x=0.03..0.215, y=0.615..0.755 of the scene) as a detailed standalone asset. Do not redraw or include the landscape.
Primary request: faithful 八方旅人2 / Octopath Traveler II HD-2D style low country fence. Follow the reference's modest, slender, aged dark-brown timber rails and short uneven posts, NOT oversized tree-trunk gate pillars. The fence has about four short posts joined by three slim irregular horizontal rails in a shallow bending line. It stretches diagonally from the nearer LOWER LEFT towards the farther UPPER RIGHT. The right end stops before the existing lamp; do not include a lamp or sign.
Composition: one complete fence assembly, long and low, viewed slightly from above as in the reference. Preserve nearer-left / farther-right perspective and the gently rising screen-space root line. Full silhouette in frame with modest transparent padding. Landscape 3:1 image. Do not turn it into a front-elevation row or a bridge.
Materials: subtle cracked and worn chestnut/oak, compact pixel-textured chipped highlights, deep brown shaded sides, faint desaturated moss at the feet. A few tiny attached weeds are allowed, but no broad grass island, floor, soil slab or cast-shadow backdrop.
Lighting: restrained warm upper-right sunlight, not a golden glow or blown-out rim; preserve deep dark wood. Crisp asset detail, no baked blur, no artificial outline.
Mandatory alpha: all empty regions AND gaps between rails must have real zero alpha. NOT a checkerboard picture, NOT a white/gray/black or colored background. No haze, glow, floor gradient, grid, labels, text or watermark. Output only this fence, no rocks, trees, mountains, buildings, path, sky or river.
Candidate C: same modest fence assembly, darker shaded wood and sparse sunlit splinters; keep the reference's unobtrusive utilitarian feel.
```

### 候选 D

源图：`exec-f0795d0d-ca3d-4c16-b74d-a45a83d1c0d3.png`

```text
Use case: background-extraction.
Asset type: one isolated, genuinely transparent RGBA PNG game environment prop.
Input image: the user's original meadow scene is the ONLY reference/source. Reconstruct ONLY the small weathered wooden fence in the LOWER LEFT FOREGROUND (roughly x=0.03..0.215, y=0.615..0.755 of the scene) as a detailed standalone asset. Do not redraw or include the landscape.
Primary request: faithful 八方旅人2 / Octopath Traveler II HD-2D style low country fence. Follow the reference's modest, slender, aged dark-brown timber rails and short uneven posts, NOT oversized tree-trunk gate pillars. The fence has about four short posts joined by three slim irregular horizontal rails in a shallow bending line. It stretches diagonally from the nearer LOWER LEFT towards the farther UPPER RIGHT. The right end stops before the existing lamp; do not include a lamp or sign.
Composition: one complete fence assembly, long and low, viewed slightly from above as in the reference. Preserve nearer-left / farther-right perspective and the gently rising screen-space root line. Full silhouette in frame with modest transparent padding. Landscape 3:1 image. Do not turn it into a front-elevation row or a bridge.
Materials: subtle cracked and worn chestnut/oak, compact pixel-textured chipped highlights, deep brown shaded sides, faint desaturated moss at the feet. A few tiny attached weeds are allowed, but no broad grass island, floor, soil slab or cast-shadow backdrop.
Lighting: restrained warm upper-right sunlight, not a golden glow or blown-out rim; preserve deep dark wood. Crisp asset detail, no baked blur, no artificial outline.
Mandatory alpha: all empty regions AND gaps between rails must have real zero alpha. NOT a checkerboard picture, NOT a white/gray/black or colored background. No haze, glow, floor gradient, grid, labels, text or watermark. Output only this fence, no rocks, trees, mountains, buildings, path, sky or river.
Candidate D: same fence silhouette, slightly more visible old joints and uneven weathering, small green-gray moss accents confined to post feet.
```

## 第二批：文字约束重新生成，选 A

### 候选 A

源图：`exec-e95a53ad-d055-4f99-bc6c-56c92215dcb7.png`

```text
Use case: stylized-concept.
Create one PNG game prop with GENUINE RGBA TRANSPARENCY. Empty background pixels and all rail gaps must be alpha=0, not a white/gray/black backdrop, NOT a checkerboard pattern.
Asset: one complete modest country fence assembly in 八方旅人2 / Octopath Traveler II HD-2D style. Four short uneven weathered dark-brown posts with THREE slender irregular timber rails connecting three bays. This is a low roadside split-rail fence, not a gate, giant log barrier, bridge or railing with a platform.
Composition: long low 3:1 landscape canvas. A very gentle bending fence line stretches diagonally from the near lower LEFT to the farther upper RIGHT. Lower-left post base around (0.10,0.90), next bases around (0.36,0.70),(0.63,0.49),(0.90,0.32). The left end is a little nearer/larger than the right. View slightly from above at about 18 degrees, matching a small-scale JRPG landscape. Full object, small transparent margins. Posts short, rails thin, the upper-right light restrained, no glowing edges.
Surface: subdued brown aged chestnut/oak with chipped square edges, a few dark joints and subtle old grain; compact pixel-textured detail and deep shade, not high-resolution photographic bark or cartoon outlines. Four posts must differ subtly; not identical repeated copies. Three rails are visibly distinguishable with transparent gaps. Only minute moss near the feet; no broad vegetation mat.
No ground plane, soil slab, floor, painted shadow, sky, landscape, fog, background pixels, white fringe, grid, text, logos or watermark. Output only the cut-out fence. Its root line can slope diagonally in image space; do not add terrain to make it stand.
Candidate A: quiet gray-brown old wood, shallow kink after the second post, finely chipped rails. Closest to a small humble fence in a sunlit meadow.
```

### 候选 B

源图：`exec-be822083-6846-4486-9115-a877798fc89f.png`

```text
Use case: stylized-concept.
Create one PNG game prop with GENUINE RGBA TRANSPARENCY. Empty background pixels and all rail gaps must be alpha=0, not a white/gray/black backdrop, NOT a checkerboard pattern.
Asset: one complete modest country fence assembly in 八方旅人2 / Octopath Traveler II HD-2D style. Four short uneven weathered dark-brown posts with THREE slender irregular timber rails connecting three bays. This is a low roadside split-rail fence, not a gate, giant log barrier, bridge or railing with a platform.
Composition: long low 3:1 landscape canvas. A very gentle bending fence line stretches diagonally from the near lower LEFT to the farther upper RIGHT. Lower-left post base around (0.10,0.90), next bases around (0.36,0.70),(0.63,0.49),(0.90,0.32). The left end is a little nearer/larger than the right. View slightly from above at about 18 degrees, matching a small-scale JRPG landscape. Full object, small transparent margins. Posts short, rails thin, the upper-right light restrained, no glowing edges.
Surface: subdued brown aged chestnut/oak with chipped square edges, a few dark joints and subtle old grain; compact pixel-textured detail and deep shade, not high-resolution photographic bark or cartoon outlines. Four posts must differ subtly; not identical repeated copies. Three rails are visibly distinguishable with transparent gaps. Only minute moss near the feet; no broad vegetation mat.
No ground plane, soil slab, floor, painted shadow, sky, landscape, fog, background pixels, white fringe, grid, text, logos or watermark. Output only the cut-out fence. Its root line can slope diagonally in image space; do not add terrain to make it stand.
Candidate B: gently sagging, slightly uneven dark rails and short posts; restrained warm top-edge highlights. Keep the fence delicate and low.
```

### 候选 C

源图：`exec-81d9cde0-c14b-429d-8541-c69d9ef71db6.png`

```text
Use case: stylized-concept.
Create one PNG game prop with GENUINE RGBA TRANSPARENCY. Empty background pixels and all rail gaps must be alpha=0, not a white/gray/black backdrop, NOT a checkerboard pattern.
Asset: one complete modest country fence assembly in 八方旅人2 / Octopath Traveler II HD-2D style. Four short uneven weathered dark-brown posts with THREE slender irregular timber rails connecting three bays. This is a low roadside split-rail fence, not a gate, giant log barrier, bridge or railing with a platform.
Composition: long low 3:1 landscape canvas. A very gentle bending fence line stretches diagonally from the near lower LEFT to the farther upper RIGHT. Lower-left post base around (0.10,0.90), next bases around (0.36,0.70),(0.63,0.49),(0.90,0.32). The left end is a little nearer/larger than the right. View slightly from above at about 18 degrees, matching a small-scale JRPG landscape. Full object, small transparent margins. Posts short, rails thin, the upper-right light restrained, no glowing edges.
Surface: subdued brown aged chestnut/oak with chipped square edges, a few dark joints and subtle old grain; compact pixel-textured detail and deep shade, not high-resolution photographic bark or cartoon outlines. Four posts must differ subtly; not identical repeated copies. Three rails are visibly distinguishable with transparent gaps. Only minute moss near the feet; no broad vegetation mat.
No ground plane, soil slab, floor, painted shadow, sky, landscape, fog, background pixels, white fringe, grid, text, logos or watermark. Output only the cut-out fence. Its root line can slope diagonally in image space; do not add terrain to make it stand.
Candidate C: deeper chestnut brown, subtle green-gray foot moss, asymmetric age wear; maintain three slim rails and four short posts.
```

### 候选 D

源图：`exec-a226001c-e388-4acc-8444-0ec1e1d0493e.png`

```text
Use case: stylized-concept.
Create one PNG game prop with GENUINE RGBA TRANSPARENCY. Empty background pixels and all rail gaps must be alpha=0, not a white/gray/black backdrop, NOT a checkerboard pattern.
Asset: one complete modest country fence assembly in 八方旅人2 / Octopath Traveler II HD-2D style. Four short uneven weathered dark-brown posts with THREE slender irregular timber rails connecting three bays. This is a low roadside split-rail fence, not a gate, giant log barrier, bridge or railing with a platform.
Composition: long low 3:1 landscape canvas. A very gentle bending fence line stretches diagonally from the near lower LEFT to the farther upper RIGHT. Lower-left post base around (0.10,0.90), next bases around (0.36,0.70),(0.63,0.49),(0.90,0.32). The left end is a little nearer/larger than the right. View slightly from above at about 18 degrees, matching a small-scale JRPG landscape. Full object, small transparent margins. Posts short, rails thin, the upper-right light restrained, no glowing edges.
Surface: subdued brown aged chestnut/oak with chipped square edges, a few dark joints and subtle old grain; compact pixel-textured detail and deep shade, not high-resolution photographic bark or cartoon outlines. Four posts must differ subtly; not identical repeated copies. Three rails are visibly distinguishable with transparent gaps. Only minute moss near the feet; no broad vegetation mat.
No ground plane, soil slab, floor, painted shadow, sky, landscape, fog, background pixels, white fringe, grid, text, logos or watermark. Output only the cut-out fence. Its root line can slope diagonally in image space; do not add terrain to make it stand.
Candidate D: irregular hand-hewn boards, subdued split grain, gently bent line and uneven post heights; nothing chunky or monumental.
```

