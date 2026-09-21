# UI 素材库

21st 来源扩充盘点与接入结论见 [2026-09-16 来源扩充](ui-source-expansion-2026-09-16.md)；质量、主题和分类说明见 [2026-09-11 更新](ui-quality-2026-09-11.md)，定时入库发布见 [发布记录](ui-publication-2026-09-11.md)。下方验收时间较早的段落保留作历史记录。

入口：`/ui-library`。详情：`/ui-library/:id`，筛选条件保存在查询参数中。

列表采用最小 240px 的自适应列宽：1440px 视口为 4 列、1920px 为 6 列、2474px 为 8 列；窄屏保留响应式排版。预览比例为 16:10，源码和提示词按钮保持常驻。顶部采用紧凑间距，桌面 MCP 推荐放在分类侧栏，详情仍保留推荐入口。素材页显式覆盖外层布局的 `overflow: hidden`，右侧保留 10px 可见滚动条，鼠标滚轮和滚动条拖动均使用原生滚动。

这是原版源码的精选目录。首批 30 项来自已有作者作品，包含 Shader、WebGL、Three.js、背景、文字与交互组件。没有用模型重画效果，没有镜像第三方站点的预览视频或宣传缩略图；海报由本地运行原组件后截图得到。

## 首批来源

当前扩充目录为 **3384 条、7 个来源**。Uiverse Galaxy 收录 3318 条原版 HTML/CSS，固定提交为 `adbd2adde0a299a3956ea288fb444ec01891ca41`。仓库的 LICENSE 和 README 声明组件采用 MIT；本批排除了外部媒体、独立脚本、已识别的品牌图样、重复源码、CSS/SVG 错误和空白预览。逐项保留作者署名，没有生成或重绘组件。

每个来源的固定提交目录 `assets/<provider>/evidence/<revision>/` 保存原始许可证、README/NOTICE、抓取时间、HTTP 响应元数据、来源地址、文件 SHA-256 和许可证页面截图。manifest 将源码哈希绑定到对应证据；历史版本证据保留。详情页与 MCP 的 `rights_evidence_url` 提供存档入口。网站生产构建和 MCP 启动都验证授权证据及原源码哈希；证据缺失或被修改时拒绝发布/启动。MIT、Apache-2.0 允许商业使用和再分发，但必须保留相关版权、许可和 NOTICE，不能据此声称不存在任何第三方权利风险。

列表每批显示 96 条，可加载更多。新增的纯 HTML/CSS 在可见卡片的隔离 iframe 中本地运行，支持悬停反馈；滚出可视区域立即卸载。其他复杂效果保留原组件实录视频。浏览器负责渲染，服务器发送静态文件。相同入库时间按目录顺序穿插类型，避免首屏全是按钮。

第二批新增 36 项，总计 66 项、6 个来源。HyperUI 24 项来自 `ae5038979b77320793360a46b85e7c71a73beda6`，Motion Primitives 免费开源版 12 项来自 `92586e62a951eb9b6bfd1cc7c8a4e6e2ab6ba17d`，均为 MIT。没有收录 Motion Primitives Pro、外部照片或远程字体文件。HyperUI 的编译 CSS 保留原样式及许可，只移除 Google Fonts 导入，预览用系统字体；该适配文件列在 assets 并带 SHA-256。原始 HTML/TSX/JS 文件逐字节保留，具体选项和拒绝外部资源的检查见 `scripts/expand_ui_library.py`。

“今日新增”入口为 `?rank=new`，展示最近 24 小时首次入库的素材，按 `added_at` 倒序排列。时间戳跟随目录持久保存，两个导入器均保留已有时间；不使用构建时间、上游提交时间或每天发现时间冒充新增。未来时间、无效时间与无时间的历史记录不进入新增榜。页面每分钟刷新时间窗口，支持叠加中英文检索和框架/分类筛选。

第二批重新导入：`python scripts/expand_ui_library.py --upstreams /path/to/upstreams`。该目录下需要固定版本的 `hyperui` 和 `motion-primitives` checkout。新增 HTML / Tailwind 框架筛选在网站与 MCP 同时可用。MIT 授权有署名和许可保留条件，不能将“开源”表述为绝对无版权风险，也不能推定仓库之外的 Pro 产品、媒体或商标获得了授权。

| 上游 | 数量 | 固定版本 | 许可 |
| --- | ---: | --- | --- |
| [Paper Shaders](https://github.com/paper-design/shaders) | 18 | `7002061d8389781a45e479584deeca0cf538474e` | Apache-2.0，保留 LICENSE / NOTICE |
| [ThreeUI](https://github.com/MengTo/threeui) | 6 | `68802d5428071ada5c20db8094b1649e6bb770ed` | MIT Community 源码；Fragment Mono 字体为 OFL-1.1 |
| [Inspira UI](https://github.com/unovue/inspira-ui) | 4 | `6da457c849e01c2543d5b2593651f989f9ea2b52` | MIT；Silk 中保留 Giorgi Azmaipharashvili 的 MIT 声明 |
| [UI Layouts](https://github.com/ui-layouts/uilayouts) | 2 | `88d827d7ec342917ca06f6894e5add65fabbe5d8` | MIT |

来源最初通过 AIGC Radar 项目库检索获得。具体组件、文件路径、作者、版本、依赖、SHA-256 与许可文件见 `mcp-go/internal/uicatalog/data/catalog.json`。

ThreeUI 只使用仓库中的 Community 代码和有独立许可的本地字体；不将仓库 MIT 解释为 threeui.com 远程媒体或 Pro 内容的授权。没有导入 React Bits / Vue Bits 的 Commons Clause 组件，也没有导入 21st 的作品。Inspira 的 Singularity / Stractium 引用了独立 ShaderToy 作品，未核实其独立分发许可，因此未收入本批。

## 运行与维护

前端与 Go MCP 共享 `mcp-go/internal/uicatalog/data`，没有重复维护的已发布目录数据库。Go 启动时验证嵌入的原始源码哈希，网站构建时打包同一份文件。静态目录与预览独立运行；账号点赞、复制额度和每日发现依赖后端与 PostgreSQL 迁移 `0065_ui_library.sql`。

```sh
cd frontend
npm ci
npm run dev
```

`predev` / `prebuild` 自动从原源码构建隔离预览。构建产物在 `frontend/.ui-previews`，不提交。React 仅用于隔离预览，主站仍是 Vue；预览依赖不进入主站入口脚本。

Vite 的 `/api` 默认代理到 `http://127.0.0.1:8000`，可用 `VITE_API_PROXY_TARGET` 指定开发后端；素材目录自身是静态内容。后端从仓库根运行时使用默认目录路径，Compose 已只读挂载共享目录并设置 `UI_LIBRARY_CATALOG_PATH=/src/ui-catalog/catalog.json`。

重新导入时，把四个仓库分别克隆到同一目录的 `shaders`、`threeui`、`inspira-ui`、`uilayouts` 子目录，checkout 表中的 commit，然后运行：

```sh
python scripts/import_ui_library.py --upstreams /path/to/upstreams
```

导入器拒绝未经更新清单的版本，并保留源文件字节。更新作品前逐项核查源代码和独立资源许可，再更新 `REVISIONS`、作品清单、对应测试与预览图。普通 Vue 的 Nuxt 自动导入、React 挂载与字体内联适配仅发生在预览打包层，不改写原作品文件。

在前端启动后重新截图：

```sh
cd frontend
npx playwright install chromium
UI_LIBRARY_BASE_URL=http://127.0.0.1:5173 node scripts/capture-ui-posters.mjs
```

Windows PowerShell 可设置 `$env:PLAYWRIGHT_CHANNEL='chrome'` 使用本机 Chrome，`$env:UI_LIBRARY_BASE_URL='http://127.0.0.1:5173'` 设置地址。截图脚本支持传入 id / 来源前缀仅更新相应作品。PNG 放在共享目录的 `posters`，需要与清单一起提交。查看渲染报告并人工检查截图后再构建发布。

前端 Docker 构建上下文已改为仓库根，以便读取共享目录；专用 `frontend/Dockerfile.dockerignore` 只允许前端与目录文件进入上下文，排除依赖、构建缓存和证书：

```sh
docker build -f frontend/Dockerfile -t aigcnews-frontend .
```

Compose 与 CI 已使用这个路径。

录制列表动效（只录制原组件，不使用 AI 合成）：

```sh
cd frontend
PLAYWRIGHT_CHANNEL=chrome FFMPEG_PATH=/path/to/ffmpeg node scripts/capture-ui-clips.mjs
```

该脚本最多同时录制三个原组件，排除加载阶段后保留最后六秒，使用 VP8 WebM；文件写入共享目录的 `clips`，录制原件和报告保留在忽略目录 `.ui-previews`。Windows 可使用已安装 Playwright 的 `ffmpeg-1011/ffmpeg-win64.exe`。FFmpeg 仅用于维护时生成素材，部署服务器不需要它。视频、海报和源代码应一起提交。详情实时预览、复制内容和 MCP 源代码均保持原作。

## MCP

网站复制额度限制复制按钮与对应账号 API。原作文件、详情源码阅读器与下述 MCP 原有公开读取保持兼容，因此这不是阻止用户获取开源源码的付费访问控制。

生产 Go 服务器注册两个匿名可读工具；它们沿用既有 HTTP 鉴权、限流与计数入口。没有新增写操作。普通工程搜索工具定义和调用行为保持原状。

- `search_ui_templates({q, category?, framework?, language?, limit?})`：支持中英文混合关键词和长自然语言需求；精确匹配为空时自动按最强命中词降级，显式提供 `category` 时还可降级到该分类。返回的 `search_mode` 为 `exact`、`relaxed_terms` 或 `category_fallback`。`language` 是返回语言（`zh` / `en`），`framework` 是 React / Vue / Nuxt。返回来源、许可和可打开的预览链接。
- `get_ui_template({id, language?, include_source?, file?})`：返回原版源码、依赖、资源、许可全文与接入提示。较大的条目按完整文件拆分，`omitted_files` 指出剩余文件；逐个用 `file` 精确文件名取回。不会给出被全局截断的半段代码。

示例：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_ui_templates","arguments":{"q":"液态金属","language":"zh"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_ui_template","arguments":{"id":"threeui-liquid-form","language":"zh"}}}
```

配置了 UI 工具的应用在 initialize instructions 中增加强制路由指引：只要用户要求新建或大幅重设面向用户的前端，即使没有提到模板、素材库、搜索或 MCP，也要在写实现代码前先调用 `search_ui_templates`，命中后再用 `get_ui_template` 取原源码。局部文案、小幅 CSS 调整和定位明确的 Bug 修复不触发。客户端是否主动调用仍取决于客户端指令与工具可用性，服务端不能强制客户端。

目前检索是共享双语词表、关键词匹配和权重排序，没有调用翻译模型或声称提供向量语义搜索。前端和 Go 使用同一组中英文查询契约测试。

## 预览与复制

有实录视频的素材详情默认播放静音循环视频，工具栏可切换「视频预览 / 交互预览」。交互预览继续隔离运行原组件，保留其原本的一次性入场动画和交互状态，不定时重置组件。无视频素材和主题默认使用实时预览；主题明暗、实时预览的桌面/手机切换保持可用。暂停或关闭详情时释放视频和 iframe；重播从头开始。`frontend/scripts/test-ui-preview-loop.mjs` 使用 Kokonut 流线首屏背景验证实际播放时间连续回绕两次，以及暂停、恢复和交互切换。

列表每次进入默认自动播放所有可视区域内的卡片，不限制为单个，不需要悬停。IntersectionObserver 同时考虑浏览器视口与滚动容器裁剪，只有海报进入可视区域才挂载原组件实录的静音循环视频；滚出区域立即卸载并释放解码器。列表不创建 WebGL 上下文，避免高密度页面超过浏览器上限而黑屏。打开详情或隐藏浏览器页面时暂停列表预览，返回后恢复；提供「暂停全部 / 播放全部」控制。列表默认播放不受系统动态效果偏好影响，用户可通过「暂停全部」关闭；详情仍保留减少动态效果偏好。未就绪的卡片保持静态封面，首个视频帧可显示时才切换为动画；慢速加载不会因超过 15 秒被卸载，加载完成后仍会自动播放。卡片预览用于观看动画，点击进入详情可操作组件的鼠标交互。关闭或暂停详情时也移除 iframe 释放渲染资源。预览使用 `sandbox="allow-scripts"`，无同源权限，无网络连接；预览字体内联为 data URL。Nginx 只对预览静态路径放开本站嵌入，其余页面保持原安全头；源码按纯文本返回，缺失资源返回 404，不回落到 SPA HTML。Service Worker 不预缓存效果素材，也不把预览导航替换为主站页面。

卡片常驻「复制源码」「复制提示词」按钮。卡片复制源码包含全部源文件、样式和许可，按文件名分隔；详情的复制源码则复制当前所选文件原文。复制提示词包含接入要求、所有源文件、原始资源路径和许可文件，卡片跟随界面语言，详情支持单独切换中英文。按钮提供加载、成功和失败反馈。

源码阅读器显示语言、完整文件路径、行数和行号，使用本地打包的 highlight.js 核心及 TS/JS/XML/CSS/GLSL/JSON 语言进行高亮。未知文件以纯文本显示；源码 HTML 被转义，不执行原文件。高亮不进入复制内容。支持桌面 / 手机预览、重播、WebGL 不可用提示、文件选择和错误重试。系统剪贴板可能把 LF 规范化为 CRLF；HTTP 原始文件与 MCP 内容的 SHA-256 保持原样。

## 验证

### 账号互动与复制额度

卡片和详情提供爱心与总点赞数，可查看「我的喜欢」。同一账号对同一作品只有一个有效点赞；取消再点赞保留首次点赞时间。今日热榜、周榜、月榜分别按滚动 24 小时、7 天、30 天内新增且仍有效的点赞排序，同分保持检索顺序。页面可见时每分钟刷新。

未登录访客可以浏览、预览与检索，点击爱心或复制先打开登录框。普通账号每天共 5 次复制，源码与提示词共享额度；以北京时间零点重置。VIP 使用项目既有 `member` 档位且未过期时不限次数；身份与会员有效期由每次请求的数据库校验决定。

复制前调用账号 API 申请额度，服务不可用或超额时不写剪贴板。数据库事务使用账号锁串行化扣额，收据 UUID 支持网络/剪贴板失败后在当前页面重试不重复计次。刷新页面会丢失未完成复制的客户端重试收据。已申请的额度不会因浏览器随后拒绝剪贴板而退款。

### 每日发现

项目 APScheduler 增加两项可在现有调度配置中调整、暂停的任务（北京时间）：

| 任务 | 默认时间 | 来源 |
| --- | --- | --- |
| `ui_library_discovery` | 每日 09:00 | Uiverse Galaxy、Motion Primitives、Magic UI、HyperUI、Magic Portfolio、Codrops RSS |
| `ui_library_x_discovery` | 每日 09:10 | X 的 ibelick、dillionverma、akella，滚动 24 小时完整窗口 |

首次成功抓取记为基线，以后按源码 blob 与许可证文件版本识别新增/更新；GitHub 链接固定到 commit。单一来源失败不清空旧记录，其余网站继续发现。X 必须证明整轮窗口完整，部分结果不入库。任务复用项目 GitHub / X 串行锁、超时和失败监测；仅在 `X_SOURCE_ENABLED` 开启且配置既有 X 凭据后运行 X 任务。GitHub 沿用 `GITHUB_TOKEN`，匿名访问容易耗尽限额。

发现结果保存在候选表，通过管理员 `GET /api/ops/ui-library/discovery?limit=100` 查看。部署机的 `AIGCNEWS-UI-Publication` 计划任务每天北京时间 09:20 承接候选核查、证据归档、预览构建及网站/MCP 发布；失败后重试，发布异常回滚。当前自动发布适配器支持 HyperUI 无外部素材的原版 HTML，完整许可证或配套代码变化则停在待核查。X、Codrops 及尚无适配器的来源仍需人工核查，不自动抓取或执行任意链接。每天最多发布 64 个通过核查的新素材，保留旧素材首次入库时间；每天检查不保证来源每天都有新作品。安装、恢复、审计记录和运行依赖见 [每日发布说明](../scripts/ui_publication/README.md)。

管理员可在监控页的“采集 → UI 素材来源”查看全部内置来源，并新增、编辑、停用或删除自定义来源。自定义来源支持 GitHub `owner/repository` 加文件 glob，以及公网 HTTPS RSS/Atom；保存与每次请求均执行出站目标校验，不执行网站脚本。配置通过 `/api/ops/ui-library/discovery-sources` 管理，并由每日 09:00 的 `ui_library_discovery` 任务读取。自定义来源只产生待核查候选，不自动扩大 09:20 发布器的适配范围。

部署后先按项目流程运行 `python scripts/migrate_postgres.py apply`，再启动后端；确认调度状态中有上述任务及下次执行时间。修改了后端配置、权限和迁移，应在可用的 Docker/PostgreSQL 测试环境中执行下面的真实集成测试。

```sh
python -m pytest backend/tests/test_ui_library.py backend/tests/test_postgres_ui_library_integration.py
cd frontend
node scripts/test-ui-library-account.mjs
```

PostgreSQL 测试使用项目隔离测试库保护，需由测试 harness 配置 `TEST_POSTGRES_DSN` 和运行标记；未配置时跳过，不能作为数据库并发验证通过。两个浏览器脚本的账号接口使用测试夹具；真实静态素材和预览仍由开发服务提供。

### 服务器负载

列表页不再启动组件 iframe。卡片先显示版本化 WebP 封面；调度器按卡片距视口中心的距离选择最多三个预览，优先挂载并播放 H.264 MP4。离开候选集后立即卸载视频并释放解码器，回到视口时再从浏览器缓存恢复。详情页才运行可交互 HTML/WebGL/Canvas 预览。

每日发布器会在禁止外网的一次性浏览器上下文中运行原组件，自动录制 640×400、6 秒、无音轨的 H.264 MP4，并生成 WebP 封面。空白画面、运行错误、缺失媒体或超过 3 MiB 的视频不会发布。媒体文件名绑定上游 revision，可使用一年 immutable 缓存和 Range 请求。服务器只发送静态文件，不占用服务器 GPU。

列表和详情都有中英文 MCP 推荐入口，链接到既有 `/mcp` 配置页。MCP 直接读取目录和源码，不需要启动效果预览。预览构建仅收录 `.ui-previews/previews/` 运行文件，不打包本地截图、测试报告、证书和测试夹具。

```sh
cd frontend
npm run typecheck
npx vitest run src/features/ui-library/catalog.test.ts src/features/ui-library/highlight.test.ts src/features/mcp/publicToolsModel.test.ts src/features/navigation/navigationModel.test.ts src/i18n/locale.test.ts
UI_LIBRARY_BASE_URL=http://127.0.0.1:5173 node scripts/test-ui-library.mjs
UI_LIBRARY_BASE_URL=http://127.0.0.1:5173 node scripts/test-ui-clips.mjs
npm run build
cd ../mcp-go
go test ./...
go vet ./...
```

浏览器检查覆盖真实海报、双语结果、两个复制操作、文件切换、暂停/继续、320/768/1024/1440 布局、焦点恢复、减少动态效果偏好、失败重试与详情深链接。Go 测试覆盖匿名/认证工具清单、旧工具保持不变、HTTP wire 格式、参数边界、源码哈希与大条目分文件取回。

## 本次验收记录（2026-09-10）

- 30 个原组件在浏览器隔离 iframe 内运行通过；已人工检查真实截图，列表不使用 AI 生成缩略图。
- 前端类型检查、相关 ESLint 和 66 项单元测试通过；最后调整素材后，18 项素材契约测试再次通过。
- 浏览器测试通过：中文 / 英文 / 混合检索、源码与提示词剪贴板、文件切换、移动预览、暂停 / 重播、焦点恢复、四档宽度、减少动态效果偏好和加载失败重试。
- Go 全套测试和 `go vet ./...` 通过；最后调整素材后，目录与 MCP 用例再次通过。
- 前端 Docker 镜像构建通过；实际 Nginx 验证了入口 / 详情 200、全部 30 张海报、源文件哈希、源码纯文本 MIME、缺失文件 404、主页面禁止外部嵌入和预览隔离 CSP。浏览器也在该 CSP 下成功运行原组件。
- 额外 Python 部署检查在 Windows 最初有环境失败：Conda 缺少 `fastapi_cache`，Bash 不能识别原样的 Windows 路径。改用后端 Linux 镜像和临时存储后 9 项通过；剩余 shell 语法检查受 Windows 检出的 CRLF 影响。使用 Git 中相同脚本的原始 LF 字节，在同一 Linux 镜像中单独执行 `bash -n` 通过。未修改该已有脚本或全局 Python 环境。

开发与验证在 `session/ui-library-1789021258-44196-7089` 隔离工作树完成；尚未合并、推送或发布线上。

本日第一轮交互验收（后续改为可视区域全部播放）：素材契约及源码高亮 23 项测试通过，包括所有原文件显示内容一致、HTML 不执行、完整文件包复制；浏览器检查新增悬停与键盘预览、同屏单渲染器、卡片直接复制、下载失败不覆盖剪贴板、代码高亮/行号，以及列表和详情的 MCP 跳转。已人工检查桌面、手机截图。

实时列表阶段验收（历史记录，现改为实录视频）：真实浏览器确认首屏多个可视卡片同时启动，无需鼠标悬停；滚动到底部后首屏 iframe 被卸载、底部可视项自动挂载，滚回后恢复。暂停全部/播放全部、详情覆盖时暂停列表、320/768/1024/1440 宽度下可视区域播放和减少动态效果偏好均通过。复制、检索、源码高亮、错误重试和 MCP 跳转回归通过，类型检查与相关 ESLint 通过。

默认播放进一步调整：列表始终默认播放，系统减少动态效果偏好只影响详情的初始状态。浏览器测试将首张卡片的预览资源下载阻塞 16 秒，确认它持续显示静态封面、不会被超时卸载、其他卡片继续播放；放行下载后它自动切换为播放，无需用户操作。列表暂停按钮仍可随时关闭自动播放。

高密度列表最终验收：修复素材页被父布局裁剪而无法原生滚动的问题，验证鼠标滚轮、右侧滚动条拖拽、4/6/8 列响应式布局和首屏至少两排完整素材。2474×1086 下有 16 个完整可见卡片、24 个可见预览。实际检查曾发现并发 WebGL 超限丢失上下文，因此最终列表使用 30 个原组件实录循环视频；确认 24 个视频都解码并播放，列表不再创建 WebGL 上下文，详情继续真实渲染。浏览器回归、Go 目录/MCP 测试、30 个视频原始字节和 Range/HEAD/MIME/404/416 检查通过。浏览器验证显式移除 Playwright 默认的 `--hide-scrollbars`，以检查真实滚动条。

该最终版本的类型检查、相关 ESLint、23 项素材/高亮测试和生产构建通过。隔离 Nginx 容器进一步验证了全部视频原始字节、`video/webm`、一小时缓存、206 分段响应、HEAD、404/416，以及生产 CSP 下的列表视频和详情实时预览。验证后已停止并删除临时容器，未修改现有运行服务或发布线上。

账号与每日发现增量验收：91 项后端测试及 381 个子检查通过，覆盖接口认证与额度策略、滚动窗口、来源部分失败隔离、X 完整窗口、调度配置和旧任务回归。前端类型检查、相关 ESLint、生产构建通过；账号浏览器测试覆盖登录拦截、爱心、榜单、源码/提示词共用 5 次、VIP、刷新保留额度、接口失败不复制、剪贴板失败重试。图库回归覆盖滚动条、4/6/8 列、默认自动播放、慢加载恢复、双语检索与复制。账号 API 使用浏览器测试夹具，未创建真实测试会员。

此轮运行限制：Docker Desktop 因 `dockerInference` 运行时文件异常无法启动。清理异常运行时文件并重启的命令被自动审批策略拦截，未执行。4 项 PostgreSQL 集成测试因无隔离测试 DSN 跳过，因此真实并发扣额、迁移和 Compose 出站代理尚未验收；后台与新增每日任务尚未实际启动。当前 GitHub 匿名 API 限额耗尽、未配置 GitHub token，X 来源开关关闭。恢复环境并完成迁移、凭据配置后再验收运行状态；上述历史 Nginx 验收不代表本轮新增后端已经部署。
