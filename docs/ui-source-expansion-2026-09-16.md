# UI 素材库 21st 来源扩充（2026-09-16）

承接 [UI 素材库](ui-library.md) 与 [2026-09-11 质量更新](ui-quality-2026-09-11.md)，记录本次对 21st.dev 可商用素材来源的完整盘点与接入结论。

## 盘点口径

21st.dev 当前展示约 1,183 条候选组件（主清单 139 个库）。逐库核对官方仓库后确认 **24 个组件来源** 的许可允许商业使用与再分发（MIT / Apache-2.0 / ISC），另有 6 个可商用图标集。素材一律从官方仓库固定 commit 获取，不从 21st.dev 复制源码；每项入库素材保留原始文件字节、SHA-256、许可证据归档（LICENSE + README/NOTICE + 许可证页面截图 + manifest）与离线隔离预览，并通过真实浏览器渲染门禁（state=ready、无控制台/资源请求错误、海报非空白帧）。

## 接入结果

| 批次 | 来源 | 入库 |
| --- | --- | ---: |
| 首批 | BundUI、SmoothUI、Dice UI、Agent Elements、Vercel AI Elements、Kibo UI | 29 |
| 批次 1 | 8bitcn、hextaui、serenity、Intent UI、shadcnspace | 588 |
| 批次 2 | systaliko、ui/tripled | 155 |
| 批次 3 | Fancy、Jolly UI、Motion Primitives、Animata、Tailark、ThreeUI、UI Layouts | 587 |
| 批次 4 | visx、Base UI | 159 |
| 图标 | 6 个固定版本图标集（见 `scripts/import_icon_sets.py`） | 18,348 SVG |

目录由 203 项增至 **1,721 项组件/区块**（新增 1,518），图标 18,348 个另行索引。

## 门禁淘汰

- 批次 1：运行时不通过 34、复核淘汰 198（其中 18 项修复后重新入库）。
- 批次 2：运行时失败与空白帧共 20。
- 批次 3：运行时失败 60（含 Animata 需要 MDX 注入 props 的 36 个组件、ThreeUI 依赖 `.webp` 二进制资源的 gallery 等）、纯空白帧 72、空壳组件 5。
- 批次 4：导入时拒绝 9（2 个 geo 拓扑 JSON 超 256KB 单文件预算、7 个 Base UI demo 内嵌 unsplash/wikimedia 活媒体 `src=`）；浏览器门禁淘汰 1（visx-geo-albers-usa 渲染 `translate(null)` 错误）。
- Jolly `tree-demo`（UNSTABLE API）与 `table-sortable`（活 fetch）在复核阶段已排除。
- 少数文件含惰性署名锚点或 example.com 表单默认值，逐项人工复核后以 `reviewed-exception` 记录（visx 4、Base UI 3、UI Layouts 1 等），预览 CSP 阻止任何实际请求。
- 终审复跑全量浏览器门禁时补获 1 项首批漏网空白帧：AI Elements `shimmer` 的文字透明渐变依赖文档站 preset 中以 `@theme inline` 声明的变量映射，独立挂载不发出行内变量。已归档固定 commit 的 `geistdocs.css` 作为该项 preset，并在预览构建器的 preset 通道为 `@theme inline` 增量合成 `:root` 变量映射（保持工具类内联语义不变），修复后海报非空白；同 preset 的 435 个 Intent UI 预览重建后与已批准海报像素级一致（平均差 ≤0.01），436 项复跑门禁 0 失败。

## 跳过与暂缓（已核实结论）

- **Ant Design**：21st 展示内容为站内原创定制，与官方仓库（ant-design）组件不对应，没有可固定的上游源码，跳过。
- **Geist UI**：组件依赖 styled-jsx，隔离预览需引入 SWC 编译链，当前沙箱不承载，跳过。
- **@tsparticles 三件套**：21st 侧仅有 1 个组件（ai-button），不构成来源级接入，记录后跳过。
- **heroicons-animated、animateicons**：两个 TSX 动画图标集由 ref 驱动播放，需要专用运行时通道，`<img>` SVG 图标通道无法承载，暂缓；后续如需接入应单建动画图标预览通道。
- 此前已撤回或许可不清的来源不回流；React Bits / Vue Bits 的 Commons Clause 组件与 Pro 内容继续排除。

## 复现

导入器：`scripts/import_reviewed_ui_sources.py`（首批）、`scripts/import_batch_registry_sources.py`（批次 1）、`scripts/import_batch_json_registry_sources.py`（批次 2）、`scripts/import_batch_directory_sources.py`（批次 3）、`scripts/import_batch4_demo_sources.py`（批次 4），共享约束在 `scripts/ui_import_common.py`；门禁清理用 `scripts/gate_remove_items.py`。测试：`python3 -m unittest scripts.test_reviewed_ui_importers`。
