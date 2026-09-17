# 自动提交、合并与生产部署

这条流水线把 session 分支一直交付到生产环境。任务分支和镜像构建可以并行；生产切换只有一个全局写入者，且不要求逐次人工批准。

## 流程

1. Codex 在 `session/<slug>-<id>` 分支完成实现和验证后必须自行暂存本工作单元并提交，不把正常提交或“创建 PR”按钮留给用户；tracked `post-commit` hook 随后自动执行普通 push，失败只保留本地提交，绝不强推或推送 `main`。
2. `Session PR` 为尚无 PR 的 session 分支创建 PR。
3. `Contract Baseline` 在 PR 上运行完整门禁。
4. `Auto Merge Validated Session PR` 在 CI 成功事件后立即 squash merge 与验证结果完全相同的 head SHA；分支在验证后发生变化时拒绝合并，不依赖仓库的 Auto-merge 开关。
5. 合并进入 `main` 后，`Contract Baseline` 再验证受保护主分支。
6. `Deploy Production` 在同一台生产 runner 的 Docker daemon 构建并加载 backend、MCP 和 frontend 镜像，保留本机构建缓存；包含私有 UI 素材的 MCP、frontend 构建在生产 runner 上读取稳定生产目录。frontend 构建还会从私有 Godot 发布目录注入联系页源码和 `camp-scene` 制品；repository variables 固定 release ID 与发布描述文件 SHA-256，发布描述文件再固定四个受保护源码及场景清单，复制到临时 checkout 后逐文件校验哈希与黑边修复契约，全部通过才允许构建。生产 job 使用固定 concurrency group 排队。
7. 自托管生产 runner 调用 `deploy_production.py`。控制器再次获取部署机文件锁，拒绝过期 main，按精确 digest 检查本机镜像（缺失时才从 registry 拉取）并切换 Compose。
8. Compose 健康等待及 `/api/live`、`/api/ready` 探测通过后，才原子更新 active release；失败时只有仍拥有本次 `in_progress` 的任务可以恢复上一版本。

Codex 的 `Stop` 生命周期 hook 会在 Agent 准备结束开发回合时核对工作区、同名远端分支、与 `origin/main` 的补丁等价关系以及生产状态文件。任一阶段尚未完成时，hook 阻止提前结束并要求 Agent 继续跟踪上述既定流水线，不得把“创建 PR”、合并或是否部署留给用户决定。只有生产 active release 已包含本任务，或者 Agent 已核实并报告带证据的外部阻塞，回合才允许结束。hook 只做验证和持续执行约束，不直接绕过 GitHub 门禁、手工合并或抢占其他任务的部署。

## GitHub 配置

仓库需要允许 GitHub Actions 创建 PR、写入 PR。本地镜像发布不需要 GHCR 写入权限。`production` Environment 不设置 required reviewers，从而把仓库管理员的启用行为作为持续部署授权，而不是每次发布授权。

配置 Repository variable：

- `AIGCNEWS_PRODUCTION_ROOT`：部署机稳定检出的绝对路径，例如 `/home/deploy/AIGCNEWS`。
- `AIGCNEWS_GODOT_RELEASE_ROOT`：部署机上私有 Godot 发布目录的绝对路径。目录必须包含 `frontend-current-parent-v4/frontend/src/`、`cn-current-godot-release/camp-scene/` 和 `cn-current-godot-release-source-manifest.json`，且仅允许 runner 读取，不得复制进 AIGCNEWS Git 历史。
- `AIGCNEWS_GODOT_RELEASE_ID`：当前获准上线的私有 Godot release ID，必须与场景清单及发布描述文件一致。
- `AIGCNEWS_GODOT_RELEASE_DESCRIPTOR_SHA256`：`aigcnews-private-release.json` 的小写 SHA-256；描述文件固定 release ID、场景清单 SHA-256 和四个联系页源码 SHA-256，防止部署读取到开发中的半成品。

发布描述文件采用以下结构，且必须先在私有仓库或私有制品发布流程中生成并验证，再以一次配置变更同时提升 release ID 和描述文件摘要：

```json
{
  "schema": "aigcnews.private-frontend-release.v1",
  "release_id": "20260916T065639721903Z-3e9034b45c29",
  "manifest_sha256": "<cn-current-godot-release-source-manifest.json sha256>",
  "source_files": {
    "components/contact/GodotContactScene.vue": "<sha256>",
    "components/contact/GodotContactScene.test.ts": "<sha256>",
    "views/ContactPageView.vue": "<sha256>",
    "views/ContactPageView.test.ts": "<sha256>"
  }
}
```

不得把变量指向开发中的可变目录后再通过改写描述文件“追平”内容。提升私有 release 时先在新目录完整生成源码、场景、manifest 和 descriptor，执行 staging 校验成功后再更新三个 Godot 变量；旧目录至少保留到引用它的构建全部结束。任何不匹配都 fail-closed，禁止回退到 Three.js、CSS 或公开仓库中的旧联系页。

注册一台只能由本仓库使用的自托管 runner，并添加标签：

```text
self-hosted
linux
aigcnews-production
```

runner 用户必须能够：

- 读取并更新 `AIGCNEWS_PRODUCTION_ROOT` 的 Git checkout；
- 使用 Docker，但不要求 root shell；
- 读取部署目录已有的 `.env`、证书和私有 overlay；
- 只读访问 `AIGCNEWS_GODOT_RELEASE_ROOT` 中由 release ID 和描述文件摘要固定的私有 Godot 发布源码、制品和 SHA-256 清单；
- 访问 `origin`；仅在恢复远端历史镜像时需要 GHCR；
- 在部署目录创建 `.release.env` 与 `.aigcnews-deploy/`。
- 读取生产目录中的 `mcp-go/internal/uicatalog/data/` 和 `frontend/.ui-previews/previews/`；这些私有发布素材不会提交到 Git，普通 PR CI 使用合成夹具验证同一构建契约。

生产目录必须是专用、稳定且 tracked 文件干净的 checkout，不能复用 Codex 开发 worktree。`.env`、`.release.env` 和 `.aigcnews-deploy/` 不进入 Git。私有 Godot 发布目录不能位于 AIGCNEWS checkout 内，也不能被 Git 暂存。

## 并发语义

- 三个发布镜像和部署必须使用同一台生产 runner 的 Docker daemon；只有通过主分支基线的代码进入该 runner。PR 测试继续在隔离的 `aigcnews-ci` runner 中执行。
- 构建使用持久化 `default` builder 和 `load: true`，关闭 push；镜像名称保留 GHCR 命名以兼容后续备份，但本流程不上传 GHCR。升级 Docker/Buildx 时必须验证导出的 manifest digest 可以在本机 `docker image inspect repository@sha256:...` 解析。
- 若扩为多台生产 runner，应先设计共享制品分发，不能只复用 runner 标签。
- GitHub job 级 `aigcnews-production` concurrency 只串行生产切换，不阻塞构建。
- `cancel-in-progress: false`，已经开始的生产切换不会被新提交取消。
- 控制器拿到主机锁后重新 fetch `origin/main`；候选已是最新 main 的祖先时标记 `superseded`，不触碰生产。
- 部署机 `.aigcnews-deploy/deploy.lock` 防止手工命令、其他 runner 或其他发布系统并发切换。
- 状态文件的 `in_progress` 是回滚所有权；所有权发生变化时拒绝回滚，避免旧任务覆盖新版本。

## 不可变制品

workflow 可以用 commit SHA 作为构建 tag，但生产 Compose 接收的永远是构建结果返回的：

```text
repository@sha256:<digest>
```

主 Compose 的三个应用服务通过 `.release.env` 获取 digest。后端不再把宿主机源码覆盖到 `/src/backend`，所以运行代码与已验证镜像一致。未启用自动发布时仍使用原有 Compose 本地镜像名。

## 首次启用

本变更自己的 workflow 在进入默认分支前不会运行，因此第一次合并需要沿用现有受控 landing。合并后：

1. 配置 GitHub Actions 的 PR 写权限和上述两个 repository variable。
2. 注册并锁定生产 runner。
3. 确认生产 checkout tracked 文件干净，`.env`、TLS 文件、存储目录、私有 UI overlay 和私有 Godot 发布目录已就绪。
4. 手工运行 `scripts/manage_main_stack.sh config`。
5. 触发一次 `Contract Baseline` 的 `main` push 或后续正常合并；第一次自动部署会建立生产状态文件。

第一次部署失败时，控制器会恢复启用流水线前的 checkout、删除候选 `.release.env`，并用原有本地 Compose 镜像重新协调主栈。

## 故障处理

状态文件位于：

```text
<production-root>/.aigcnews-deploy/state.json
```

`in_progress` 非空表示上一次进程在完成状态提交前异常退出。控制器会 fail-closed，不会猜测生产状态。此时应核对容器实际 digest、`.release.env`、Git HEAD 和健康端点后，再由运维人员修复状态；不要直接删除锁或状态文件后盲目重跑。
