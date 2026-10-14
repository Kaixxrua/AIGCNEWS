# v37 水纹材质生成

内置 imagegen，同一材质四张候选并发，选一张用于连续河道着色，不是整景背景。

## 原始提示词

Use case: stylized-concept.
Asset type: seamless tileable opaque RGB water albedo texture for an animated Godot HD-2D river.
Style explicitly: 八方旅人2 (Octopath Traveler II), beautifully textured miniature fantasy game water, subtle painterly pixel-cluster detail rather than generic smooth shader noise.
Subject: ONLY a square uninterrupted surface of clear blue-teal flowing river water, viewed directly from above, flat orthographic material swatch. Tiny irregular cross-current ripples, soft layered eddies, dark teal troughs and small fragmented pale sky reflections. Medium blue overall, not black. Rich natural water detail with restrained contrast: brightest glints occupy under 8 percent, most surface midtone turquoise and steel blue. Glints have many different tiny broken curved shapes, not straight rows or long stripes. Subtle translucent depth variation, NO visible objects.
Composition: 2048x2048 full-bleed uniform-scale texture, no perspective foreshortening, equal lighting everywhere, no central subject. Seamlessly repeat in both axes; no vignette or image border.
Avoid: shorelines, banks, river bends, rocks, plants, trees, fish, buildings, horizon, scene background, recognizable clouds or tree reflections, long parallel white bands, uniform grid patterns, lettering, logos, transparency, baked depth of field. Only the water material.

## 四个变化

- A: fine broken silver-blue ripples, organic small eddies, balanced sunny mid-blue.
- B: intricate small angular painterly reflections, deeper teal troughs, restrained sparkle.
- C: irregular delicate cross-current wavelets, soft turquoise depth, natural low-contrast daylight.
- D: varied tiny flowing curls and chopped sky glints, textured steel-blue surface, no large highlights.

## 选择结果

选中 B：波峰更细碎、白色反光更克制，没有大片长白条。实际输出 1254×1254、不透明 RGB，水面材料本来不需要透明背景。

入库文件：`E:/Projects/Godot-Octopath2/godot/assets/materials/river-ripples-v37.png`。

四个原始候选位于 `C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`：

- A：`exec-b3eecab4-6140-4f1b-aa3f-f9a4bf6848a1.png`
- B（选中）：`exec-45521b96-e423-4bfe-a290-aed49a4d68ea.png`
- C：`exec-4fb7e9d7-7541-4815-a2ec-7d20f032ad86.png`
- D：`exec-0d9d5d3f-2306-4df1-93ce-d53d7ac16df5.png`

Godot 使用两层不同方向/速度的世界尺寸采样、微弱扭曲和波峰闪光，不把生成图当作静态河道截图。边缘窄带交错采样遮蔽潜在贴图接缝，mipmap/各向异性过滤抑制远处锯齿。
