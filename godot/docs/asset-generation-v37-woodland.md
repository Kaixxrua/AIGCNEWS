# v37 林缘图集生成

模式：内置图像生成；同一资产四个候选并发，选一张完整图集；每个 UV 区域只用一次。

## Base prompt

Use case: stylized-concept.
Asset type: true transparent RGBA atlas of EIGHT DIFFERENT small woodland-edge groups for modular Godot scenery.
Style explicitly: 八方旅人2 (Octopath Traveler II) high quality HD-2D sunny plain environment, detailed miniature trees, crisp fine clustered leaves, rich olive-green crowns, blue-green inner shadows, golden sunlight from upper right. Same 25-degree downward elevated front camera for all groups. NO baked depth blur.
Composition: square sheet, exactly 2 columns x4 rows, each cell one isolated broad tree group, groups fully separate with ample transparent margin and gutters. Full crowns, trunks, roots visible. Every individual tree differs from the others in crown shape, branching, lean and foliage density. Irregular crowns, not spheres.
Eight groups in reading order: 1 lone broad old oak with low brambles on its left; 2 three small airy elms, tallest at right; 3 two crooked riverside willows with sparse hanging foliage; 4 small round oak and two young saplings with visible trunks; 5 one gnarly field maple and low hawthorn; 6 low spreading coppice of three young oaks with uneven heights; 7 two slender deciduous trees with open gap between trunks; 8 low broad hedgerow of small leafy saplings, no tall central tree.
Each group sits on only a thin irregular sprinkling of low grass at roots, no soil island or plinth, no long external shadow. Real alpha transparency outside ALL branches/leaves and through gaps. No white matte, no checkerboard painted into pixels, no backdrop, landscape, mountains, sky, grid lines, letters or logo. Deliver one atlas; show no scene composition.

## Four concurrent variations

- 0: A: organic varied silhouettes and restrained warm highlights.
- 1: B: deeper cooler shadows, especially sculptural irregular oak canopies.
- 2: C: airier canopies with individually readable branches and rich undergrowth.
- 3: D: broad wind-shaped crowns, clear small-scale leaf clusters.

## 选择与入库

选择 A：树冠完整、透明外边距足够、颜色更克制。B/D 顶部存在裁切问题，C 偏亮。

原始文件：`C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/exec-73ff7676-0f2d-46d8-ad26-9b7fc64141fa.png`。

入库：`E:/Projects/Godot-Octopath2/godot/assets/foliage/woodland-groups-v37.png`。实际尺寸 1254×1254，保留原始 alpha。八个区域各使用一次，没有复用相同 UV。其余候选路径记录在 `asset-generation-v37.md`。
