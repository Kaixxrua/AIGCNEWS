# UI 素材每日发布

APScheduler 09:00 的 `ui_library_discovery` 保留发现职责。部署机上的 Windows 计划任务 `AIGCNEWS-UI-Publication` 于北京时间 09:20 消费同一张 `ui_discovery_candidates` 表，完成核查、归档、预览和生产发布。无需 Codex 会话在线。

当前自动核查适配器为 **HyperUI 的无外部素材 HTML 组件**。核对固定 commit、Git blob、已核查的完整 MIT LICENSE 和配套 JS/CSS 哈希；独立的 `.agents` 许可不覆盖导入目录，也不分发其内容。许可文件、配套代码、目录结构或已上线组件发生变化时转待人工核查。X、Codrops 和其他来源继续发现候选，不会未经对应适配器核查就发布。

每个北京时间自然日最多发布 64 个新素材，优先新发现，再处理存量。相同 ID、源码内容去重；已经发布的素材保留 `added_at`。`--force` 只允许同日再跑一批，不绕过核查。

流程：

1. OS 文件锁防重入，要求 HyperUI 最近 36 小时发现成功；失败可以重试。
2. 导出运行中的前端产物，在私有目录中组装；不重构、重建其他页面。
3. 保留原始源码、许可证、README、固定版本链接、HTTP 响应元数据和 SHA-256。许可证页面保留真实截图，历史证据不删除。
4. 仅运行固定的预览适配代码，在禁止联网的 sandbox iframe 中渲染；生成真实截图，空白、异常预览留待核查。
5. 预览可运行只是技术检查；公开收录还要求逐项视觉审核。未审核素材以 `held_quality` 保存于私有候选目录，不进入前台。审核记录位于 `local/ui-publication/quality-approvals/<id>.json`，绑定 commit、全部源码 SHA-256、预览文件与截图哈希，记录构图、字体层级、完整预览及交互检查、审核人、时间与理由。版本或画面改变即失效。审核通过后才构建 MCP 和前端镜像，再校验双边缘目录哈希和 MCP 原始源码。
6. 更新后端目录和候选状态，保存发布回执。后端按文件版本更新 ID 缓存，无需每日重启。

任何发布失败回滚本轮镜像、目录和边缘版本。中断后下次运行根据持久日志恢复；检测到第三方并发发布时停止回滚，避免覆盖其他发布。候选状态按 `candidate_id + revision` 条件更新，避免把后续发现的新版本标为已发布。

运行记录位于 `local/ui-publication/latest.json` 和 `runs/<UTC时间>/`：候选快照、逐条核查原因、渲染报告、产物哈希、旧版本、双边缘版本和生产验证结果。管理员发现接口中的 `publication` 来源行显示最近发布任务状态。`held_policy`、`held_duplicate`、`held_render` 不会进入前台。

MCP 验证遇到部署机匿名 IP 的日额度耗尽时，单独记录 RPC 未完成，保留全部配额限制；同时要求线上二进制与通过目录/MCP 契约测试的构建一致，并从两个生产节点取回原始源码核对哈希。其他 RPC、鉴权、内容或哈希错误仍阻止发布。手动撤下的 ID 可保存在 `local/ui-publication/withdrawn.json`（`version: 1`、`ids` 数组），跨上游修订持续生效；历史版权证据应留在私有归档。

部署依赖：部署账户可访问 Docker、已安装 Chrome、Python（Pillow）、Node、现有 SSH 凭据。渲染依赖使用本目录 `renderer/package-lock.json`，安装到 `local/ui-publication/renderer`，不依赖临时开发 worktree。

```powershell
npm ci --prefix local/ui-publication/renderer --ignore-scripts --no-audit --no-fund
scripts/ui_publication/install-task.ps1 -Root E:/Projects/AIGCNEWS-local -Python E:/Anaconda3/python.exe -NodeModules E:/Projects/AIGCNEWS-local/local/ui-publication/renderer/node_modules
```

任务每天 09:20 和部署账户登录时触发；当日完成后幂等退出。错过时间会补跑，失败后每 15 分钟重试，最多 3 次。与当前 Docker Desktop 部署一样，要求部署账户的交互会话和 Docker 正常运行；电脑离线时不能执行，但上线后会补跑。

首次安装前将 `renderer/package.json` 与锁文件复制到上述运行目录。本机时区必须是中国标准时间。停用：`Disable-ScheduledTask -TaskName AIGCNEWS-UI-Publication`；现有已发布素材不受影响。
