# UI 素材每日更新

## 现行：Linux 上游刷新器（`refresh.py`）

Windows 计划任务 `AIGCNEWS-UI-Publication` 随 2026-09-14 部署机迁到 Linux 后已停止（最后一次运行 2026-09-11），且它只适配已撤下的 HyperUI 与默认关闭的 X 静态 HTML；2026-09-16 批量导入的来源从未有更新链路。现由用户级 systemd 定时器 `aigcnews-ui-refresh.timer`（北京时间 09:30，错过补跑）运行 `refresh.py`，代码取自当前发布检出 `~/AIGCNEWS-production`。

覆盖范围：`import_batch_registry_sources`、`import_batch_json_registry_sources`、`import_batch_directory_sources`、`import_batch4_demo_sources` 四族登记的全部固定来源（8bitcn、HextaUI、Serenity、Intent UI、Shadcn Space、Eldora UI、Neobrutalism、systaliko、uitripled、Fancy、Jolly、Motion Primitives、Animata、Tailark、ThreeUI、UI Layouts、SyntaxUI、Tremor Blocks、Launch UI、visx、Base UI）。新增来源只需在对应导入脚本登记固定 commit 与许可证 SHA-256。

每轮流程：

1. `git ls-remote` 取上游 HEAD；与上次检查一致则跳过。浅克隆固定 commit，不执行任何 npm 脚本。
2. **法律闸门**：许可证文件必须与审核时逐字节一致，否则整个来源停在 `license_changed_requires_review`（文件被删除则为 `license_removed_requires_review`；例：HextaUI 2026-09 起上游已删除 LICENSE，停在审核版本）。
3. 首次运行时在已审核 revision 上重放导入器：当时能产出却不在目录里的 ID 视为曾被门禁或人工拒绝，永不自动回归；`withdrawn.json`、以及本刷新器发布后又被手动删除的 ID 同样永久屏蔽；HyperUI、Uiverse/Galaxy 整体不再自动入库。
4. 在新 HEAD 上跑同一导入器（同样的外链/离线依赖/体积门禁），只取新 ID。新文件写入 `sources/<provider>/r<rev12>/`，已发布素材的固定字节不变。每轮最多 48 个（各来源轮转），没处理完的来源下次继续。
5. 离线构建预览；在禁止联网的无头浏览器中等 `ready`，生成版本化 WebP 封面与 6 秒 H.264 MP4；异常、空白封面（灰度标准差 ≤ 3）记入 `held.json`，源码不变不再重试。
6. 权利证据取自固定 commit 的 LICENSE 与 README（缺 README 则停下），并截取 GitHub 许可证页面；已有同 revision 证据只追加、不改历史哈希。截图失败只顺延，不拉黑。
7. 按 `uiLibraryAssets.ts` 同款规则核对新素材，并用 Go 目录加载器（`TestPinnedSourcesAndLocalFileBoundary`）校验整个暂存目录。
8. 持 `build-release.lock` 写入生产目录：只新增文件、拒绝覆盖不同内容，`catalog.json` 最后原子替换；期间目录被他人改动则放弃本轮。新素材随下一次 main 发布进入网站与 MCP 镜像。

状态目录 `~/.local/state/aigcnews-ui-refresh/`：`latest.json`、`runs/<UTC>/status.json` 与 `commands.log`、`providers.json`（基线/已检查 revision/停因）、`held.json`、`published.json`、`withdrawn.json`（`version: 1`，`ids` 数组；手动撤下的 ID 写这里）。管理员发现接口的 `publication` 行显示最近一轮结果。

```sh
python3 scripts/ui_publication/refresh.py --dry-run --providers neobrutalism   # 只暂存和校验，不碰生产、不写状态
cp deploy/systemd/aigcnews-ui-refresh.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now aigcnews-ui-refresh.timer
```

依赖：Node、FFmpeg（`libx264`/`libwebp`）、Go、Playwright Chromium（无 root 主机用 `--browser-libs` 指向用户态运行库，默认 `~/.cache/ms-playwright/runtime-libs/...`）、本机出站代理访问 GitHub。预览沙箱依赖按前端锁文件安装到状态目录。

### 来源法律边界

只接收 OSI 宽松许可（MIT、Apache-2.0、ISC、BSD）且许可证文件按哈希固定的公开仓库；不接收 AGPL/GPL、Commons Clause、`NOASSERTION`/无许可证仓库、Pro/付费内容；不绕过 Cloudflare 等反爬验证，不抓取条款禁止转载的网站。已排除：coss/originui（AGPL-3.0）、react-bits（Commons Clause）、animate-ui、shadcnblocks（许可证不明）、farm-ui（无许可证）、Aceternity/Skiper（源码不公开）、inspira-ui（MIT，但大量组件是 Aceternity UI 的 Vue 移植，上游授权不及于再分发）、SyntaxUI 的 Hero Patterns 背景（CC BY 4.0 第三方图样）。`@remixicon/react` 固定 4.8.0：4.9.0 起改为非 OSI 的 Remix Icon License 1.0。Codrops 演示禁止原样转载且常含第三方图片，只以 GitHub 组织新仓库作为待核查链接，不入库。

## 历史：Windows 发布器（已退役）

以下为 `runner.py` 时代的说明，保留供审计与恢复参考。

APScheduler 09:00 的 `ui_library_discovery` 保留发现职责。部署机上的 Windows 计划任务 `AIGCNEWS-UI-Publication` 于北京时间 09:20 消费同一张 `ui_discovery_candidates` 表，完成核查、归档、预览和生产发布。无需 Codex 会话在线。

当前自动核查适配器包含 **HyperUI HTML** 与 **显式开启 `x_auto_publish` 的 GitHub 静态 HTML**。X 通道只处理推文中直接命中白名单仓库的链接，复用 09:00 任务已固定的 commit/blob，重新核对根 MIT LICENSE，并拒绝脚本、外部资源、活动属性和远程 CSS。通过隔离渲染、非空截图和哈希绑定后记为 `verified`；开关默认关闭。Codrops、普通网页、React/Three.js 工程及其他未配适来源仍只发现候选。

每个北京时间自然日最多发布 64 个新素材，优先新发现，再处理存量。相同 ID、源码内容去重；已经发布的素材保留 `added_at`。`--force` 只允许同日再跑一批，不绕过核查。

流程：

1. OS 文件锁防重入，要求 HyperUI 最近 36 小时发现成功；失败可以重试。
2. 导出运行中的前端产物，在私有目录中组装；不重构、重建其他页面。
3. 保留原始源码、许可证、README、固定版本链接、HTTP 响应元数据和 SHA-256。许可证页面保留真实截图，历史证据不删除。
4. 仅运行固定的预览适配代码，在禁止联网的隔离浏览器上下文中渲染；自动生成真实截图、版本化 WebP 封面与 6 秒 H.264 MP4。空白画面、浏览器异常、缺失素材或超过 3 MiB 的视频会被拦截。
5. 技术检查通过后写入绑定 commit、全部源码 SHA-256、预览文件、封面和视频哈希的自动验证记录并进入当日发布。X 严格静态 HTML 适配器还必须通过白名单仓库、固定 MIT 许可、无脚本和无外部资源核查。若存在 `local/ui-publication/quality-approvals/<id>.json`，则仍优先校验并保留人工视觉审核；版本或画面改变即失效。随后构建 MCP 和前端镜像，再校验双边缘目录哈希和 MCP 原始源码。
6. 更新后端目录和候选状态，保存发布回执。后端按文件版本更新 ID 缓存，无需每日重启。

任何发布失败回滚本轮镜像、目录和边缘版本。中断后下次运行根据持久日志恢复；检测到第三方并发发布时停止回滚，避免覆盖其他发布。候选状态按 `candidate_id + revision` 条件更新，避免把后续发现的新版本标为已发布。

运行记录位于 `local/ui-publication/latest.json` 和 `runs/<UTC时间>/`：候选快照、逐条核查原因、渲染报告、产物哈希、旧版本、双边缘版本和生产验证结果。管理员发现接口中的 `publication` 来源行显示最近发布任务状态。`held_policy`、`held_duplicate`、`held_render` 不会进入前台。

MCP 验证遇到部署机匿名 IP 的日额度耗尽时，单独记录 RPC 未完成，保留全部配额限制；同时要求线上二进制与通过目录/MCP 契约测试的构建一致，并从两个生产节点取回原始源码核对哈希。其他 RPC、鉴权、内容或哈希错误仍阻止发布。手动撤下的 ID 可保存在 `local/ui-publication/withdrawn.json`（`version: 1`、`ids` 数组），跨上游修订持续生效；历史版权证据应留在私有归档。

部署依赖：部署账户可访问 Docker、已安装 Chrome、FFmpeg（含 `libx264` 与 `libwebp`）、Python（Pillow）、Node、现有 SSH 凭据。渲染依赖使用本目录 `renderer/package-lock.json`，安装到 `local/ui-publication/renderer`，不依赖临时开发 worktree。FFmpeg 不在 PATH 时向任务命令传 `--ffmpeg E:/ffmpeg/bin/ffmpeg.exe`。

```powershell
npm ci --prefix local/ui-publication/renderer --ignore-scripts --no-audit --no-fund
scripts/ui_publication/install-task.ps1 -Root E:/Projects/AIGCNEWS-local -Python E:/Anaconda3/python.exe -NodeModules E:/Projects/AIGCNEWS-local/local/ui-publication/renderer/node_modules
```

任务每天 09:20 和部署账户登录时触发；当日完成后幂等退出。错过时间会补跑，失败后每 15 分钟重试，最多 3 次。与当前 Docker Desktop 部署一样，要求部署账户的交互会话和 Docker 正常运行；电脑离线时不能执行，但上线后会补跑。

首次安装前将 `renderer/package.json` 与锁文件复制到上述运行目录。本机时区必须是中国标准时间。停用：`Disable-ScheduledTask -TaskName AIGCNEWS-UI-Publication`；现有已发布素材不受影响。
