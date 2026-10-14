# v79 — 干草密度染色归因实验（未采用）

仅旁路ContinuousMeadow中纯干草区域的最后thicket乘色，原mass、源纹理压缩、道路/岸/岩/沉积混合、法线、光照及其它shader保持。实验源保留在 `artifacts/v79/meadow_ground.density-test.gdshader`，修改前源在 `artifacts/v78/meadow_ground.before-density-test.gdshader`。

## 实际证据

- `20260910-134611-*` 材料流程10阶段完成，主命令22125实际exit0；五个v77几何缓存预检一致，source / foliage / lighting / export / PCK检查完成。落盘日志未匹配到ERROR / WARNING。这不是新的完整35阶段，也没有另重跑GPU离屏探针（它们不覆盖ground的材质输出）。
- 实验PCK SHA `875cc71463f9b0766af946496c9e0c22a77b6bc3527eaa231f33ee7d80d3c45b`，原始118,843,284字节，gzip114,064,373字节。
- `day-density-test-2k.png` / `night-density-test-2k.png`：真实PNG及canvas均2560×1440、DPR约1、clock0暂停、blend0/1，主代理original查看完整画幅，普通网页无warn/error。此次就绪26,594ms，场景构建2,396ms；只记录此次上下文，不声称性能退化或改善。夜截图曾遇到浏览器焦点操作超时后DPR回到1.5；该无效图已单列 `night-density-invalid-dpr-diagnostic.png`，重新校准后抓取上述有效夜PNG。无效图不参与验收。
- 独立源码审读确认：旁路在y>-.1、z>-107、n.y>.88、原道路和岸混合区域之外才可能非零，且远坡/林地字段必须为0。原法线所依赖bank_pigment在旁路前计算；湿岸/河床/道路核心不走新颜色链。此为源码边界证据，不是美术通过。

## 不采用的原因

主代理双图对照v78认为：草地主要变浅、偏黄，灰蒙感没有真正消失，干地与深色独立植丛的分离更强。说明直接撤销这层染色不能解决当前统一性问题；不因编译/空间保护通过就交付。独立图评追加在 `artifacts/v78/visual-colour-targets.md`，它不取代主代理判断。

实验的15行新增代码已通过apply_patch撤回；当前ground文件SHA再次与v78修改前逐字节一致。导出包和原生图留作诊断证据，不覆盖v78、不作为推荐预览。接下来的v80从v78地表基线继续统一日光与色彩输出，水/河床不做另一轮设计。
