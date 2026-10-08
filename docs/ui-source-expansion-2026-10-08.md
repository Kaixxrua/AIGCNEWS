# UI 来源扩充（2026-10-08）

先通过 AIGC Radar（aigcnews.cn）项目搜索，再以 GitHub 官方仓库和固定提交核验。补充搜索得到 114 个去重仓库；这个数量包括工具、已有来源和不适合独立预览的应用，不代表新增模板数。下载审核 12 个候选仓库的原始许可证、README 和源码，另保留此前 Mantine、Shadcn Admin、Admin One Vue 的调查记录。

## 新登记的每日来源

固定提交及许可证 SHA-256 由 `scripts/import_batch_directory_sources.py` 管理。六个仓库本次审核版本的根许可均为 MIT；每个条目仍须独立通过依赖、媒体、构建、离线浏览器和版权证据门禁。

| 来源 | 上游 | 选择范围 | 本次入库 |
| --- | --- | --- | ---: |
| Blocks.so | [ephraimduncan/blocks](https://github.com/ephraimduncan/blocks) | 官方表单、登录、统计、命令面板等组合区块 | 65 |
| beUI | [starc007/ui-components](https://github.com/starc007/ui-components) | 公共 motion/charts 目录中的官方 preview；不取 Pro/agent/block 目录 | 86 |
| Sera UI | [seraui/seraui](https://github.com/seraui/seraui) | 文档目录中带原始演示内容的 view 组件 | 25 |
| Shadcn UI Blocks | [akash3444/shadcn-ui-blocks](https://github.com/akash3444/shadcn-ui-blocks) | Radix 版本完整业务区块；不重复导入 Base UI 副本及内部辅助组件 | 62 |
| ShadcnStore | [shadcnstore/shadcn-dashboard-landing-template](https://github.com/shadcnstore/shadcn-dashboard-landing-template) | Next 版本落地页区块；不重复导入 Vite 副本 | 3 |
| ReUI | [keenthemes/reui](https://github.com/keenthemes/reui) | 时间线、步骤、排序、上传、日历等业务交互的 Radix 示例；本轮通过的是评分、滚动导航、步骤与时间线 | 13 |

Shadcn UI Blocks 的 `src/config.ts` 已人工核对：仅包含站点域名和作者 GitHub/Twitter 归属链接，本身不发起请求；其余源码继续受原有媒体闸门限制。带未单独核验品牌图形来源的 logo-cloud/logo-carousel 暂不选取。

视觉复核额外排除了 Blocks.so `ai-01`（当前预览编译器未保留带引号的 grid-area 工具类，控件重叠）、Shadcn UI Blocks `empty-state-03`（缺少上游 shadcn CSS 的方向变体，页签布局失真）、Sera UI `curved-text-view`（固定宽度文字路径截字）及 `spotlightcard-view`（内容对比度不足）、beUI `preview-rail`（独立画面仅剩边缘刻度）。这些项目即使浏览器无异常、截图非空也不会入库。Sera UI 的 `marquee-view` 还需补充内嵌品牌图形的来源证据。

## 导入与保真

- 源码逐字节保存，固定 commit、文件 SHA-256、LICENSE、README、GitHub 许可证页面截图；不执行上游安装脚本。
- 完整区块保留其原始依赖闭包，预览容器采用整块布局；不修改上游源码来伪造可运行结果。
- 多级目录生成稳定 ID，新增同名兄弟目录不会改掉已有 ID；`.preview` 后缀不进入展示 ID。
- 不可离线获取的包、新旧 API 不兼容、外部媒体、浏览器异常或空白画面均不入库。网站图片和付费文件不会被替换为虚构内容以通过验收。
- 每日刷新器自动发现登记来源，许可证变化会暂停该来源；已有 ID 不重复导入，撤下内容不会复活。入库后由现有素材发布控制器处理网站、MCP 与边缘发布。
- 素材目录与媒体存于生产私有数据卷，由现有内容发布流程分发；Git 只提交导入器、筛选规则、测试和本文档，不提交运行数据或临时克隆。

## 暂缓或排除

| 来源 | 本轮决定与依据 |
| --- | --- |
| [Page UI](https://github.com/PageAI-Pro/page-ui)、[leoMirandaa landing](https://github.com/leoMirandaa/shadcn-landing-page)、[nobruf landing](https://github.com/nobruf/shadcn-landing-page) | MIT；Tailwind 3 自定义主题需要独立适配，不能把未还原主题的预览当作成品 |
| [TailGrids](https://github.com/TailGrids/tailgrids) | MIT 公共组件；分离主题 CSS、内部图标包与图片路径还需适配；不取付费产品 |
| [Nextly](https://github.com/web3templates/nextly-template)、[Next JS Landing Starter](https://github.com/ixartz/Next-JS-Landing-Page-Starter-Template) | MIT；主题、额外包及图片依赖尚未通过现有独立预览环境 |
| [Mantine UI](https://github.com/mantinedev/ui.mantine.dev) | MIT；需补齐 Mantine provider、CSS modules 和运行依赖 |
| [Shadcn Admin](https://github.com/satnaing/shadcn-admin)、[Admin One Vue](https://github.com/justboil/admin-one-vue-tailwind) | MIT；完整后台依赖路由、状态和应用上下文，未冒充独立模板入库 |
| [Shadcn Studio](https://github.com/shadcnstudio/shadcn-studio/blob/main/LICENSE.md) | 许可证实际附加 Commons Clause 限制，不能仅凭 README 的 MIT 标识接受 |
| [Float UI](https://github.com/MarsX-dev/floatui/blob/main/LICENSE.md) | 自定义许可限制组件/模板再分发，不符合本库接收边界 |

React Bits、Origin UI、Inspira UI 等此前明确排除的来源保持排除，见刷新器 README 的法律边界。

## 验收记录

三批分别处理 128、128、16 个候选，共 272 个。11 个未通过自动门禁（5 个构建失败、5 个浏览器异常、1 个空白封面），7 个在视觉/来源复核后排除，最终新增 **254 个**。已使用刷新器的校验与原子写入函数一次性写入正式私有目录，总量 **1,898 → 2,152**；原有 1,898 个目录条目逐项保持不变。

- 导入器与每日刷新回归 **39 项通过**，覆盖固定许可、完整区块筛选、稳定 ID、排除重复框架副本、原始字节保留及撤下内容不复活；Ruff 与 diff whitespace 检查通过。
- 各批次及合并后的完整目录通过 Go `TestPinnedSourcesAndLocalFileBoundary`；254 个新增项目的正式目录源码、权利证据、预览 HTML、封面与视频在写入后再次核对完整性。
- 六个来源的当前 HEAD 已处理完毕，已发布/拦截状态写入现有每日刷新器状态文件。后续只有新的合格 ID 才会新增；许可证变化继续停审。
- 正式入库记录：`~/.local/state/aigcnews-ui-refresh/runs/20261008T103724Z/status.json`。
- 入库后目录 SHA-256：`f13a1c9ce010251ce801b6af761c80bc450ca52ae1ae20ba2a8b3af9cf63a7d8`。
- 搜索原始数据、固定提交审核、逐批浏览器报告、视觉联系表与逐项媒体哈希保存在 `~/.local/state/ui-source-expansion-20261008-vlmlfqxh/`。入库代表正式素材目录已写入，前台可见仍以自动发布完成为准。
