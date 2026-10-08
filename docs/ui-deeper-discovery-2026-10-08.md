# UI 来源深入探索：第二轮（2026-10-08）

在上一轮 2,152 条素材的基础上，新增 **87 条**，目录总量 **2,239 条**。四个新来源登记到现有每日刷新器；新增素材仍须通过许可、离线依赖、浏览器与目录校验，再由既有控制器自动发布。

## 检索与实际收录

先调用 AIGC Radar MCP 项目搜索，连接失败后查询官方 GitHub、作者网站和许可证。8 组仓库检索得到 55 个达到 500 stars 的不同项目，再沿官方项目目录补查。保留 12 份固定版本源码审查和 6 份跨框架许可证/依赖清单记录；既有来源、同一模板的框架副本不重复计入新增。

| 来源 | 核验 stars | 入库 | 内容与范围 | 固定版本 |
| --- | ---: | ---: | --- | --- |
| [Crafter Elements](https://github.com/crafter-station/elements) | 524 | 37 | Agent 上下文、路由、护栏、推理、token、JSON/schema、终端等组合示例；排除认证/支付后端和品牌素材 | `cb4d5283443a3b565893821257c886a0b6b6553b` |
| [RetroUI](https://github.com/neobrutalism/neobrutalism) | 1,615 | 20 | 复古图表、日历、课程卡片和空状态；没有批量重复收录基础按钮变体 | `d5fbc0e823bb66575f5372c3df03ee43be45c91b` |
| [LaunchMVPFast](https://github.com/alifarooq9/launchmvpfast) | 620 | 19 | Hero、导航与组合输入；导航内部控件只作为依赖保留 | `af5684527804826186c6eb463df673bd703dad64` |
| [Componentry](https://github.com/harshjdhv/componentry) | 579 | 11 | 定价、Hero、交互与动态背景；排除需 GSAP、外部图片或无法独立展示的示例 | `4591f4235837f1eb378cf1642ff9f63b48c7e435` |

四个来源均核对原始 MIT 许可证全文并固定 SHA-256；源码按原字节保存，没有改写第三方实现。许可证、README、固定版本链接和许可证页面截图随素材归档。刷新器继续按许可证文件哈希检查后续版本。

## 逐层验收及排除

初筛 180 个文件入口，118 个通过源码闭包、依赖及外部素材检查。实际构建/浏览器检查拦下 19 个：8 个构建失败、4 个运行失败、7 个空白或近空白封面。其余 99 个继续做视觉和最终目录核验，再排除 12 个，最终保留 87 个。

- Componentry：去除高度塌缩的渐变、对比度不足的 Matrix 效果、初始只显示操作提示的 Pixel Canvas。滚动效果和 Circuit Board 已由空白门禁拦截。
- Crafter：去除空聊天骨架、进度与任务数量不一致的示例、含第三方品牌图形的评论示例及依赖 `/api/generate-avatar` 的头像生成示例。需要 WASM 执行而被现有 CSP 拒绝的代码差异预览保持暂缓。
- LaunchMVPFast：主题按钮、搜索框、团队切换器不作为独立导航区块收录；移动导航缺必需参数已被运行门禁拦截。
- RetroUI：横向柱状图的轴标签在当前预览中被裁切，暂缓。
- Studio Admin：分析页能生成预览，但最终 Go 目录校验发现 `_components` 不会被现有嵌入规则收录。该来源暂不登记、不入库；其余后台页还有 TanStack 表格版本、图标或 Tooltip 上下文依赖问题。

本次同时修正目录导入器：将已经审核的别名映射传给预览器；对 Go 嵌入会忽略的点号/下划线路径按候选拒绝，避免一个页面拖垮整批入库。保留当前 Go 打包规则与网络/CSP 边界。新增回归测试覆盖混合目录别名、原始字节及单个不可嵌入依赖不影响其他候选。

首次包含 Studio Admin 的暂存校验失败，未写入生产；筛除后对最终 87 项重新运行前端素材契约和完整 Go 目录校验，两者通过。Python 共 **41 项测试**及 Ruff 通过。四个来源再次执行刷新均为 `fresh=0`，已验证初始候选处理完毕，已暂缓条目不会在相同源码下重复尝试。

## 进一步可接入的来源

以下仍是候选，数量没有计入本次新增。根许可证不代表所有图片、插件或示例都已审核。

| 来源 | 已确认的接入条件 |
| --- | --- |
| [Studio Admin](https://github.com/arhamkhnz/next-shadcn-admin-dashboard) | 独立处理原始 `_components` 路径、表格版本和页面 Provider；保留完整页面源码 |
| [Kiranism Dashboard](https://github.com/Kiranism/next-shadcn-dashboard-starter) | Clerk、React Query/Form、Zustand 及独立主题 CSS，需要组件级适配 |
| [TailAdmin React](https://github.com/TailAdmin/free-react-tailwind-admin-dashboard) | 仅免费 MIT 版；需处理 SVG 导入、i18n、ApexCharts 和图片的独立依赖/许可 |
| [Shadboard](https://github.com/Qualiora/shadboard) | full-kit 的主题 CSS、翻译和表单上下文不能直接省略 |
| [Admin One React](https://github.com/justboil/admin-one-react-tailwind) | Redux、Formik、MDI 图标及拆分样式需要完整接入 |
| [Animal Island UI](https://github.com/guokaigdg/animal-island-ui) | 原始设计 MIT；组件 LESS、全局 token/reset 和完整样式链需支持 |
| [Tabler](https://github.com/tabler/tabler) | Bootstrap/Sass/Astro 模板链；[官方说明](https://github.com/tabler/tabler#-license)特别区分 ApexCharts 新版的非 MIT 再分发许可 |
| [Flowbite Admin](https://github.com/themesberg/flowbite-admin-dashboard) | Hugo 模板、Tailwind、插件初始化与图像资源，需要 HTML 路径适配 |
| [Soybean Admin](https://github.com/soybeanjs/soybean-admin) | Vue、Naive UI、路由/主题 Provider 与图标资源，需要 Vue 页面级适配 |
| [AstroWind](https://github.com/arthelokyo/astrowind) | Astro 7/Tailwind 4 编译，组件 props、图片和嵌入媒体分别审核 |
| [Basecoat](https://github.com/hunvreus/basecoat) | HTML/CSS/JS 与 Astro 文档示例；先提取完整模板及其样式和行为依赖 |
| [Sailboat UI](https://github.com/sailboatui/sailboatui) | Hugo/Tailwind 3，表单插件、主题和外部图片需要独立适配 |

以下来源本轮不收录：

- [Square UI 的实际许可证](https://github.com/zerostaticthemes/square-ui/blob/8985cb634cc10d57988a187441ae9c971ed890ed/LICENSE.md)禁止独立模板、UI 库及仓库再分发，不能依据项目介绍中的 open-source 字样导入。
- [PrebuiltUI 官方模板条款](https://prebuiltui.com/policies/template-license)的免费档同样禁止作为独立模板或组件库再分发，与本项目入库用途不相容。
- [Indie UI 的 README](https://github.com/alibey-10/indie-ui/blob/4d5aafc3c09d07e83360e6a3a50d8f7795f2f5b0/README.md)在 MIT 声明之外限制教程和 demos 再分发；未将根 MIT 标签视为这些示例的充分授权。

## 本地审计记录

仓库外审计目录：`~/.local/state/ui-deeper-discovery-20261008-w1fz5hj2/`。包括原始检索结果、固定版本及许可证、依赖清单、118 项构建/录像结果、逐页视觉检查、首次失败日志、最终 `reviewed-verification.json`、独立 Go 通过记录和正式入库 `promotion.json`。最终入库过程复用 `refresh.commit` 的发布锁、目录摘要并发检查及最后原子替换，已有 2,152 项内容保持不变。
