# v54 原生透明图集最终生成路线

内置 image_gen，仍为每种四并发。带旧参考图的幻想鹿/狐批次及鹿去背景批全部假透明，不采用。改为仅文字生成新的透明图集；不手工抠色，不改写输出像素。

## 鹿完整共用提示词

```text
A genuinely transparent-background PNG sprite sheet for a fantasy HD-2D game, 八方旅人2 art style. Exactly eight sequential frames of one small magical bud-antler deer WALKING to the RIGHT, arranged in a precise 4-column by 2-row grid. Same slender chestnut-brown fawn with tiny golden spots and short twig antlers with a few jade leaf buds in every frame. Hand-placed pixel clusters and richly shaded fur, natural anatomy, charming magical woodland creature, not chibi. Continuous eight-phase walk cycle: contact, down, passing, up, opposite contact, opposite down, opposite passing, opposite up. All four legs have a coherent cyclic gait. Constant size, camera and torso registration; identical antlers, markings and head. Ground baseline 90% down each cell. Full body, ears, antlers, hooves, tail inside each cell with at least 8% transparent padding. Actual RGBA alpha=0 outside the eight animals, including holes between legs. No scenery, floor, cast shadow, labels, border or watermark. Empty background, NOT a drawn checkerboard, NOT white/gray/black rectangles. Keep the PNG transparent.
```

鹿 A/B/C/D 追加：smooth leg sequencing / consistent shoulders and body size / clean delicate leaf buds and hoof edges / restrained textured pixel shading。

## 其余三组共用提示词

```text
Genuinely transparent-background PNG sprite sheet, 八方旅人2 HD-2D fantasy pixel art. Exactly EIGHT sequential animation frames of ONE magical animal in a precise FOUR-column by TWO-row grid, facing RIGHT, fixed slightly elevated side-view RPG camera. Richly shaded pixel-cluster fur, no flat cartoon icon or chibi proportions. Identical individual, torso registration, head, appendages, markings, scale and lighting in all eight cells. Full body and all parts visible with 8% clear padding in every cell, ground baseline 90% down each cell. Each pose is the next eighth of one smooth seamless gait cycle; not eight unrelated poses or duplicate idle poses. Actual RGBA alpha zero everywhere outside the animals and in gaps between limbs. Empty transparent background, no checkerboard pattern, white/black/color rectangle, scene, floor, cast shadow, grid, labels, frame numbers or watermark.
```

## fox

```text
A magical golden-tail fox: russet and amber fur with dark green-charcoal paws, cream chest, oversized single bushy tail ending in a gently curled honey-gold wisp-shaped tuft, small pale-gold swirl markings on the cheek and flank. Charming but slender and natural-bodied, not a massive mount. Restrained gold markings; NO baked outer glow or flame. Eight sequential calm walking poses: contact, down, passing, up, opposite contact, opposite down, opposite passing, opposite up. Legs smoothly alternate and the tail follows gently; same body length and tail volume in every frame.
```

## hare

```text
A magical leaf-eared woodland hare: muted moss-brown and sage fur, long leaf-shaped ears with jade-green tips, small pale-gold forehead marking, cream underside and a tiny seedpod-like tuft tail. Readably rabbit-shaped, fantasy details in silhouette but not chibi, no oversized cartoon eyes. Eight sequential low gentle hop poses: crouch/compression, hind-leg push, low flight, forepaw reach, forepaw contact, hind-leg recovery, hind contact, settle, then smoothly back to crouch. Stable body proportions, no excessive stretch; only a small purposeful vertical arc.
```

## moon-stag

```text
A magical nocturnal moon stag: silver-gray fur with slate-blue shadowed underside, ivory branching antlers with pale turquoise tips, a few tiny pale cyan markings on its flank. Elegant medium-sized quadruped, not a giant boss, not chibi. Only antler tips and tiny markings are bright; whole fur must NOT become glowing white. DO NOT draw any external aura, bloom, halo, mist or ground light; these effects will be real-time in the game engine. Eight seamless measured walking poses: contact, down, passing, up, opposite contact, opposite down, opposite passing, opposite up. Exactly identical antler topology and face in all eight frames; planted hooves remain on the shared baseline.
```

每组 A/B/C/D 追加：smooth chronological gait sequencing / consistent body and head registration / clean transparent silhouette and complete feet / restrained textured pixel shading。

## 已选结果

- 叶耳兔选原生透明批 D：`exec-c487b246-d47c-4961-9c51-9b7bb5dcfdb7.png` → `assets/creatures/leaf-hare-v54.png`。A/B/C虽透明，但完整伸腿时跨过单元格边界，均拒绝；D八帧完整且越界0，72.430%全透明。1774×887的实际单元格443.5×443.5，按浮点UV边界实测。第3帧保留约0.205m低跳，其他接触帧校正到地面；休息只停在蹲伏/落地帧0或7。
- 灵鹿选原生透明批 A：`exec-0632fe11-672b-4cea-8159-c4eeeabf15d1.png` → `assets/creatures/moon-stag-v54.png`。B跨格，拒绝；A/C/D透明通过，A躯干中段中心0.5288–0.5378U，鹿角和体型在整轮更稳定。68.159%全透明，八格越界0。角尖与小范围毛纹发光，外部软光晕由引擎叠加。

- 狐狸选原生透明批 A：`exec-90050266-ce1c-4261-af36-fac81b3dacb6.png` → `assets/creatures/gold-fox-v54.png`。四候选透明均通过；A 躯干、尾巴形状较稳定，中段中心0.5218–0.5361U。77.552%全透明，八格边缘越界0，脚锚已实测。SHA-256：`50FBF08F3B541A4B82210CBC85B0635FE45B8C76B907FE6CBFE4A93605BD6396`。

- 鹿选原生透明批 D：`exec-81d93e8a-027d-474c-ba43-7a9cbd392ae4.png` → `assets/creatures/bud-deer-v54.png`。四候选全部透明通过，D 躯干中段中心在0.4872–0.5059U，比C的0.4001–0.5394U稳定，体长和枝角也较一致。72.809%全透明，8格边缘越界0。逐帧脚锚按实测位置修正上下两排基线偏移，PNG未改写。

## 最终文件校验

所选源文件均位于 `C:/Users/李开新/.codex/generated_images/01a08118-2ebf-7d92-804d-0046cfbbb53c/`。逐字节复制到本地工程，哈希如下：

| 最终资产 | SHA-256 |
| --- | --- |
| `E:/Projects/Godot-Octopath2/godot/assets/creatures/leaf-hare-v54.png` | `F5340B31D02B4A5F0B9EA7AC85E293685D4089A258D43E8FFB6AACB7E488B1FA` |
| `E:/Projects/Godot-Octopath2/godot/assets/creatures/bud-deer-v54.png` | `0213980A5092EFC6472B7CC90E0C5EDA53D285F7A11D9E1435752AC00D562C54` |
| `E:/Projects/Godot-Octopath2/godot/assets/creatures/gold-fox-v54.png` | `50FBF08F3B541A4B82210CBC85B0635FE45B8C76B907FE6CBFE4A93605BD6396` |
| `E:/Projects/Godot-Octopath2/godot/assets/creatures/moon-stag-v54.png` | `0C0B0044F4EB5532DF1860E67AACAE297E81274FB0AE87E80275AD0AD77DA82D` |
