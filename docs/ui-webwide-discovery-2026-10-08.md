# 全网 UI 来源探索与 HTML 示例接入（2026-10-08）

按用户要求，从 AIGC Radar 的项目搜索开始，再检索独立作者站、模板商店、框架官方示例、中文后台项目、代码游乐场和设计社区。发现范围扩大到公开网络；收录仍要求可追溯源码、明确再分发许可、完整依赖和可运行的本地预览。没有把设计截图或“免费下载”标识当成模板源码授权，也不表示已经穷尽全网。

## 本轮接入

| 来源 | 官方地址 | 固定提交 | 许可 | 处理 |
| --- | --- | --- | --- | --- |
| Basecoat | <https://basecoatui.com/> | `6953a4adbe63cb5ba25e2bda30d7b76202d4f2b4` | MIT，Ronan Berder | 官方 MDX 中的 HTML 示例、Tailwind 4 样式和原始 JS |
| Sailboat UI | <https://sailboatui.com/> | `8d0970f39193d8e852bf338298665556aa3163c8` | MIT，lvwzhen | Hugo shortcode 中的 HTML 示例和 Tailwind 3 表单样式 |

两个上游共有 447 个文档示例。源码筛选、去重、离线渲染、非空白封面、H.264 视频与人工预览复核后，最终接收 **266 个组件和模板块**：Basecoat 161、Sailboat UI 105。目录由 2,239 增至 2,505；这些条目包括表单、卡片、布局、列表和交互组件，不全是完整网站模板。37 个候选在预览门禁中暂缓，另 3 个弹层在 390 像素视口展开后超出边界而被排除，其余因源码条件或重复而未收录。

新增 `import_batch_html_sources.py`，由每日 `ui_publication/refresh.py` 自动发现。固定 LICENSE 哈希发生变化即暂停该来源；Sailboat 的 Tailwind 配置也固定哈希，编译器只复现受审的配置，不执行上游配置或安装脚本。已有条目保留自己的提交和字节，新增条目沿用版本隔离、重复检查和撤回规则。

`example.html` 是原文档中未经改写的字节片段，方便直接复制；同条目附带完整原文档、CSS 和 JS。元数据记录文档路径、UTF-8 字节范围及片段 SHA-256。预览构建同时验证完整文档哈希、范围、片段哈希与 `example.html` 一致性。MDX/Hugo 文档外壳不执行，真实 HTML 原样挂载。许可和源码关系同时保存在证据清单中。

Basecoat 保留原生 details、选择器、菜单及 tabs 运行时；依赖文档脚本的图表、主题切换和无法直接挂载的示例暂缓。Sailboat 的 Alpine 指令示例暂缓。两个来源均不引入外部照片、字体或品牌图片，不放宽预览 CSP。字体采用系统回退。HTML 导入器拒绝内联事件、框架指令、远程/未审资源、越界路径和 Go embed 忽略的路径。

编译产物附带 Tailwind / forms 原始许可全文。内联图标另附 Lucide（包含 Feather 衍生图标的 MIT 条款）与 Heroicons 许可，不将模板根许可覆盖到图标。Lucide 1.21.0 的 LICENSE 来自 Basecoat 上游锁文件指定的 npm tarball，先核对 SHA-512 integrity，归档 SHA-256 为 `b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57`；图标版本变化暂停刷新。[Lucide 官方许可](https://lucide.dev/license)说明了 ISC / Feather MIT 的范围。Heroicons 2.2.0 的 LICENSE 来自本项目锁定依赖，SHA-256 为 `60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985`。

## 其他来源的具体结论

| 入口 | 本轮核查结果 | 后续条件 |
| --- | --- | --- |
| [Start Bootstrap](https://startbootstrap.com/licenses) | 免费主题另有 MIT；已固定 Modern Business 源码与 LICENSE，`7d297106cbda2f04db4696752fcdb5b4dc9cd936` | 完整页引用 Bootstrap CDN、图标字体和部分远程图片，需逐项制作本地依赖包 |
| [Tabler](https://tabler.io/admin-template) | 官方 HTML 后台，开源部分 MIT | 保留原 Bootstrap 布局；图表依赖单独核对，不能把根目录 MIT 推及全部插件 |
| [Bootstrap Examples](https://getbootstrap.com/) | 官方代码与文档分别标明 MIT / CC BY | 从官方代码示例提取，独立归档 Bootstrap JS/CSS 许可 |
| [Bulma Templates](https://bulmatemplates.github.io/bulma-templates/) | 官网有后台、博客、卡片、着陆页等实际预览和源码入口 | 固定各模板及 Bulma 版本，再审字体、图片与完整页依赖 |
| [Halfmoon](https://www.gethalfmoon.com/) | HTML/CSS 组件及 Bootstrap 风格示例 | 需要受审 CSS 和行为脚本适配 |
| [Pico CSS](https://picocss.com/) | 官方语义 HTML 示例；官网当前明确提示停止维护 | 可作为历史固定素材来源，不承诺持续新增 |
| [Franken UI](https://franken-ui.dev/) | HTML-first，基于 UIkit / LitElement；官网提示后续为 0build | 先核对新旧版本、模板许可和运行依赖 |
| [daisyUI](https://daisyui.com/components/) | 官方多主题 HTML 组件目录 | 独立核对免费组件与商业模板范围，编译其主题/插件 |
| [Astro Themes](https://astro.build/themes/1?price%5B%5D=free) / [astro.new](https://astro.new/latest/templates/) | 官方目录含独立作者的博客、作品集、SaaS 模板 | 每个作者分别核对源码许可；需 Astro 页面与图片构建支持 |
| [Nuxt UI Templates](https://ui.nuxt.com/templates) | 官方 SaaS、Dashboard、Chat、Docs、Portfolio 等完整应用 | Nuxt Content、认证/API 与上下文依赖须逐模板离线适配 |
| [shadcn-svelte](https://www.shadcn-svelte.com/blocks) | 官方 Sidebar、登录、注册、OTP、Calendar 等源码块 | 需要 Svelte 编译器、路由/上下文支持；不能当 React 源码导入 |
| [Flowbite Svelte](https://flowbite-svelte.com/blocks) | 官方营销、CRUD、表格等 blocks 目录 | 逐块确认许可和依赖；本次 Flowbite 主站抓取为 403，猜测的 blocks 仓库为 404，不视为已审核 |
| [Skeleton](https://www.skeleton.dev/) | 官方有布局、表单、表格及框架组件 | 需要主题样式与对应框架支持 |
| [SoybeanAdmin](https://soybeanjs.cn/) / [vue-pure-admin](https://github.com/pure-admin/vue-pure-admin) | 中文后台来源，官方源码说明 MIT | 分别依赖 Naive UI / Element Plus、路由、状态和图标系统 |
| [Themefisher License](https://themefisher.com/license) | 官方明确区分免费 MIT 与 Premium；媒体另有提示 | 仅逐项审查免费源码，图片等不能沿用代码许可结论 |
| [HTML5 UP License](https://html5up.net/license) | CC BY 3.0，可使用/修改但有署名条件 | 当前受审代码来源范围没有涵盖这类模板许可，不自动入库 |
| [CodePen Licensing](https://blog.codepen.io/docs/pens/licensing/) | 公开 Pen 默认为 MIT，私有 Pen 不适用；已找到真实价格卡代码 | 必须归档具体作者、原始代码、预处理器与资源；当前 Git 固定提交刷新器不直接接收 Pen URL |
| [CodePen 价格表实例](https://codepen.io/YOgesh31/pen/vYxZzNo) | 公开页面提供 HTML/CSS | 作为非 Git 候选保留，尚未完成快照、作者证据和完整资源验证 |
| [Behance UI Kit 实例](https://www.behance.net/gallery/48462581/Free-UI-Kit-Adobe-XD) | 作者写明个人/商业使用；交付格式为 Adobe XD | 不是可执行代码；再分发范围和转换后的独立授权仍需核实 |
| [Figma Community](https://www.figma.com/community) | 社区入口受访问限制；付费资源有独立许可 | 不将 Figma 设计稿或 Community 标签直接解释为开源代码授权 |
| [Framer Marketplace](https://www.framer.com/marketplace/templates/) | 官方提供作品集、SaaS、电商等模板目录 | 需逐作者核对再分发和可导出的源格式；不是网页截图镜像 |
| [Webflow Template Licenses](https://webflow.com/templates/template-licenses) | 免费模板也明确限制向第三方再分发模板及组件 | 不纳入源码模板库 |
| [UIdeck License](https://uideck.com/license) | 当前免费版限制个人项目；商业产品亦限制再分发 | 不按“Free”批量收入 |
| [Cruip Terms](https://cruip.com/terms/) | 下载许可限制托管、转售或再分发模板及衍生物 | 本轮不导入站点下载包；若独立仓库另有许可需逐项审查 |
| [Creative Tim License](https://www.creative-tim.com/license) | 商业 Item 不允许用来分发模板/UI Kit；并非所有独立开源库都适用该协议 | 不把商业主题作为素材复制；独立开源产品另审 |

以上“后续条件”是候选记录，不是已发布条目或全站授权结论。既有人工撤回的 HyperUI / Uiverse 等来源保持撤回。

## 验证与归档

HTML 导入器测试覆盖原文 UTF-8 范围、Hugo 外壳隔离、危险/未支持标记、CSS 闭包和文件边界。预览测试覆盖真实 Tailwind 编译、文档外壳不挂载、片段/源文件篡改拒绝以及离线 CSP。来源加入每日刷新注册表的固定提交/许可测试。

验证结果：46 项 Python 测试、3 项编译器测试、Python lint 和前端类型检查通过；完整 Go 目录校验通过。10 类实际示例在 640 / 390 像素两个视口完成 20 次检查，覆盖输入、表单提交隔离、折叠、tabs、搜索选择、菜单开合、popover、开关和原生下拉。所有通过条目的封面逐张复核。Basecoat 卡片首次挂载的 flex 包装导致挤压，已按上游 ReallySimpleDocs 1.0.12 的原容器类修正，并重新生成全部 Basecoat 媒体。

266 个条目的源文件、预览、封面和视频哈希绑定在现有 `editorial.verified` 证据格式中；预览固定存入目录，旧版本构建器无需认识新适配器也可部署这些素材。使用修改前的预览构建器和正式网站资产插件完成全目录兼容验证。新增来源将在此代码交付后进入既有每日检查；不承诺每天上游一定产生合格的新内容。

运行目录：`~/.local/state/ui-webwide-discovery-20261008-f6zaew24/`。保存固定 checkout、LICENSE 原文/哈希、候选清单、分批刷新报告、封面/视频、人工检查记录和生产写入回执。使用隔离目录运行标准刷新门禁，通过完整 Go 目录和网站契约后，再在生产发布锁下以原目录哈希为前提原子追加；不覆盖其他来源。
