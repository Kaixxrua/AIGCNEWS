# v61 石灰岩底材：两轮内置生图，每轮四并发

2026-09-09。使用 imagegen 技能和内置图像工具，四个相同要求并发生成，没有CLI/API回退，也没有脚本改写PNG。提示词明确包含“八方旅人2”。生成的是不透明矿物色材质，不是整景背景或岩壁贴片。

## 第一轮：细颗粒候选，未作为最终活动底材

最初选B：颗粒较细，大片亮色纹脉和深孔相对克制。A灰色连片较大，C/D局部孔洞和纹脉更明显。实际Web中，这一批的颗粒在远距离取样后太弱，岩面显得过平。首版明度也过高；仅回调明度仍不够，因此进行了第二轮定向编辑。第一轮源图保留，未覆盖。

- 项目文件：`assets/materials/limestone-albedo-v61.png`，1254×1254，原图逐字节复制，开启mipmaps，不限制源尺寸。
- SHA-256：`A3D413825FF9460D5E7D646B4826855F81C1B87E784FC4B4523AF3E13414EFF2`。
- 生成目录：`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。
- A：`exec-5e90ec8a-abc5-4f1d-bc4d-53f5e62a239f.png`。
- B：`exec-0078f6d7-8e57-4b81-bac7-60623438bb88.png`。
- C：`exec-e7eb1c69-56e7-4d57-b76c-47a701479a25.png`。
- D：`exec-244c20ad-597d-4c0d-a59d-2c811ad3f0fa.png`。

首个试验采用4米世界取样和23%旧崖纹；Web中偏白偏平。第二个试验调低底色、使用12米取样和64%旧崖纹，仍缺少远距离可读的裂隙。两次实际截图分别为 `artifacts/v61/day-candidate.jpg` 和 `day-balanced.jpg`；没有把通过代码测试当成美术合格。

## 第一轮完整提示词（四个并发相同要求）

Use case: stylized-concept.
Asset type: opaque seamless mineral ALBEDO texture for solid 3D limestone outcrops in a modular HD-2D grassland game.
Primary request: 八方旅人2 / Octopath Traveler 2 art direction, finely painted pixel-cluster weathered limestone SURFACE, neutral material pigment only.
Composition: square full-bleed orthographic straight-on sample of a single continuous four-metre-wide limestone surface; all four edges tile. No visible silhouette, stone pile, scene, floor, grass cap, transparency or perspective.
Material: subtle irregular chalk and warm grey-beige mineral patches, thin broken mineral veins, tiny porous pits and small faded olive lichen stains. Mostly connected matte limestone planes with gently varied pigment. Restrained fine pixel clusters, not photographic noise.
Palette: muted warm limestone grey, pale taupe, dusty cream, a little subdued ochre and faded grey-green; coherent with a sunlit olive meadow. Moderate value range, no saturated orange or pure white highlights.
Lighting: even shadow-free diffuse albedo, no directional lighting, no deep black cracks, no AO shading, no cast shadows or glossy highlights. Geometry, fissures and sun/moon shadows are added by Godot, not painted into this source.
Avoid: stacked rocks, rectangular masonry blocks, dramatic relief, repeated stripes, checkerboards, speckled glitter, noisy gravel, giant cracks, borders, labels, text, logos, watermark, blur. A high-quality usable flat game material, not a rendering of a rock wall.

## 第二轮：定向编辑，选A

输入为第一轮B原PNG，四个编辑请求同时发出。保留原色系与平面色材质，针对性增加能在游戏远距离看清的矿物片与裂隙。A的裂隙方向、宽窄与板片大小较不规则；B的裂纹更细弱，C/D较多长向连片。选择仍以实际引擎画面为准，不因alpha/文件检查通过就认定风格完成。

- 活动项目文件：`assets/materials/limestone-fractured-v61.png`，1254×1254，不透明，原PNG逐字节复制；mipmaps=true，size_limit=0。
- SHA-256：`266A3216989C440896040FDC230A466000FD5B53E2B91224780FD1EFF05BE7DB`。
- 生成目录同上，A：`exec-2a4c2dc6-f84a-4e46-ae31-27ed0a4f45cc.png`；B：`exec-af77ef1c-f92e-4de3-a4f7-c8a856887f2b.png`；C：`exec-4632bc30-3ef1-4fd4-80d7-3d119d814fc7.png`；D：`exec-1af177fc-8188-4d5e-b497-44dec5f4c751.png`。
- 新底材用于裸地和实体石块的统一8米三向世界取样。四条不重复的旧崖纹按64%参与暴露岩面的细部，不再占91%；未把它们冒称纯无光照albedo。旧源文件仍保留；连续材质取样不等于复制独立道具。
- Web第二批首次三排块体试验仍偏砌墙感；最终进一步修改实际几何，取消固定层高排列、改变埋入与倾角，保留这张A作为活动底材。日夜验收与未完成差距见 `verification-v61.md`，并未继续盲目增加纹理数量。

### 第二轮完整提示词

Use case: precise-object-edit.
Input image: mineral albedo texture, edit target. Refine it for 八方旅人2 / Octopath Traveler 2 HD-2D stone outcrops viewed from a distant game camera.
Change only the scale and structure of the surface pattern. Keep an opaque square full-bleed seamless flat mineral texture with the same finely painted pixel-cluster character and warm limestone-grey, dusty cream, muted ochre and grey-green palette.
Replace the uniformly tiny faint mineral noise with 8–14 unequal connected flat limestone plates across the image, broken by thin branching irregular dark taupe fissures. Mix a few small angled fractures, broad worn mineral patches, eroded rusty-ochre joints, and sparse grey-green lichen; readable at thumbnail size. Vary directions and plate sizes naturally, not a regular grid or brick masonry. Add crisp medium-scale pixel clusters and restrained value variation so the game texture does not wash into a featureless beige surface.
Fissures are narrow mineral/grime colour, not deep black gaps or 3D cast shadows. Flat orthographic diffuse albedo, uniform shadow-free lighting, no sun highlights, no raised blocks, no rock pile, no perspective, no cliff silhouette, no grass cap, no horizon or scenery.
Keep all four edges tileable, no transparency, no text, labels, frame, logo, checkerboard or blur. Do not make photoreal kitchen marble; maintain painterly game rock detail.
