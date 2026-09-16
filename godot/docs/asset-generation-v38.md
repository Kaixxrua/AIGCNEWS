# v38 · 可受光的立体环境材质

使用内置 imagegen；每种材质四个候选同时生成，人工对比选一。所有提示词显式包含“八方旅人2”。原始输出保留，选中材质另存入项目。

## 石灰岩表面基础提示词

Use case: stylized-concept.
Asset type: square seamless opaque albedo texture for THREE-DIMENSIONAL limestone rock meshes, NOT a picture of a cliff.
Primary request: 八方旅人2 (Octopath Traveler II) HD-2D game material, detailed warm grey-beige weathered limestone, restrained tiny painterly pixel-like mineral chips and uneven faint strata, subtle pores and hairline cracks. Natural calcareous stone for a sunny grassy plain.
Composition: perfectly flat orthographic close-up of ONE CONTINUOUS mineral surface filling the entire image. Neutral diffuse even illumination, no cast shadows, no sun direction, no AO painted around large forms. Medium value pale warm grey and muted ochre; small cool grey mineral inclusions. The game engine will provide all large-scale shape and lighting. Fine surface pattern at consistent scale; no recognizable rock silhouettes.
Constraints: tileable left-right and top-bottom, uniform detail density, full bleed. No sky, plants, moss, foliage, grass, soil, structures, masonry blocks, separated boulders, floating islands, stepped escarpment, perspective, object edges, vignette, text, grid lines or watermarks. This is only a physically plausible painted base-color map, not a scenic illustration. 2048x2048.

## 四个候选变化

- A: pale chalky grey-beige limestone with delicate fractured mineral flakes.
- B: muted honey-grey limestone, slightly larger subtle weathered flakes, very few dark cracks.
- C: fine irregular light grey sedimentary stone with thin soft ochre mineral bands.
- D: warm neutral stone with restrained small chips, balanced light/dark detail and no dominant pattern.

## 选择与保存

选择 B，实际尺寸 1254×1254。矿物色差比 A 更清楚，条纹比 C 克制。首轮用于实体岩面后仍显得过于平滑，因此最终保留给道路的砂砾颜色采样，实体岩坡改用后续四并发选出的风化 A；见 `asset-generation-v38-understory.md`。不覆盖或删除第一轮原图。

原始目录：`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。

- A：exec-086b5abf-4c87-4bdd-aee5-58b40e9a30dd.png
- B（选用）：exec-79c108e4-51aa-45fc-88eb-08f8d81a7f5a.png
- C：exec-7d5a2b4e-f1aa-4051-8b50-8718c3dcd6ea.png
- D：exec-987db233-f7a8-4c74-8fe5-afe8aedffe20.png

项目副本：`assets/materials/limestone-albedo-v38.png`。使用 mipmaps 和世界尺寸采样。
