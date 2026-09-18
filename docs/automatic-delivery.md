# 自动提交、合并与生产部署

这条流水线把 session 分支一直交付到生产环境。任务分支和镜像构建可以并行；生产切换只有一个全局写入者，且不要求逐次人工批准。

## 流程

1. Codex 在 `session/<slug>-<id>` 分支完成实现和验证后必须自行暂存本工作单元并提交，不把正常提交或“创建 PR”按钮留给用户；tracked `post-commit` hook 随后自动执行普通 push，失败只保留本地提交，绝不强推或推送 `main`。
2. `Session PR` 为尚无 PR 的 session 分支创建 PR。
3. `Contract Baseline` 在 PR 上运行完整门禁。
4. `Auto Merge Validated Session PR` 在 CI 成功事件后立即 squash merge 与验证结果完全相同的 head SHA；分支在验证后发生变化时拒绝合并，不依赖仓库的 Auto-merge 开关。
5. 合并进入 `main` 后，`Contract Baseline` 再验证受保护主分支。
6. `Deploy Production` 在同一台生产 runner 的 Docker daemon 构建并加载 backend、MCP 和 frontend 镜像，保留本机构建缓存；包含私有 UI 素材的 MCP、frontend 构建在生产 runner 上读取稳定生产目录。frontend 构建还会从私有 Godot 发布目录注入联系页源码和 `camp-scene` 制品；repository variables 固定 release ID 与发布描述文件 SHA-256，发布描述文件再固定四个受保护源码及场景清单，复制到临时 checkout 后逐文件校验哈希与黑边修复契约，全部通过才允许构建。生产 workflow 使用固定 concurrency group：当前候选不中断，等待区只保留最新的已验证 `main` 候选，并在任何镜像构建开始前淘汰旧候选。
7. 自托管生产 runner 调用 `deploy_production.py`。控制器再次获取部署机文件锁，拒绝过期 main，按精确 digest 检查本机镜像（缺失时才从 registry 拉取）并切换 Compose。
8. Compose 健康等待及 `/api/live`、`/api/ready` 探测通过后，才原子更新 active release；失败时只有仍拥有本次 `in_progress` 的任务可以恢复上一版本。

Codex 的 `Stop` 生命周期 hook 会在 Agent 准备结束开发回合时核对工作区、同名远端分支、与 `origin/main` 的补丁等价关系以及生产状态文件。任一阶段尚未完成时，hook 阻止提前结束并要求 Agent 继续跟踪上述既定流水线，不得把“创建 PR”、合并或是否部署留给用户决定。只有生产 active release 已包含本任务，或者 Agent 已核实并报告带证据的外部阻塞，回合才允许结束。hook 只做验证和持续执行约束，不直接绕过 GitHub 门禁、手工合并或抢占其他任务的部署。

`Delivery Sweeper` 在 `Session PR` / `Contract Baseline` 完成后立即运行，并每 10 分钟对开放的同仓库 `session/*` PR 做一次补偿协调。它只合并当前 head SHA 在最近 12 小时内已有成功 `Contract Baseline` 的 PR，并且每轮最多执行一次批准、重试或合并，避免并行推进主分支或复活陈旧验证。若 GitHub 把同仓库机器人创建的 PR 标成 `action_required`，Sweeper 只批准当前 head SHA 对应且不超过 12 小时的门禁；若所有失败 job 都未分配 runner 且没有执行步骤，则把它识别为基础设施启动故障并最多重试到第三次。真实测试失败、fork PR、非 session 分支、旧 head 和过期结果都保持阻塞。它是事件驱动 `Auto Merge` 的受信任补偿路径，不降低任何测试或分支保护门禁。

仓库必须配置 Actions secret `AIGCNEWS_DELIVERY_TOKEN`。该凭据应属于仓库所有者，并至少具备 Actions 写入和 Pull Requests / Contents 写入权限；它只注入默认分支上的 `Delivery Sweeper` 和 `Auto Merge Validated Session PR`，不得注入 `Session PR`、`Contract Baseline` 或任何运行 PR 代码的 job。这样机器人 PR 可以自动获批，合并产生的 `main` push 也会继续触发主分支验证与部署，而待审 PR 无法读取或篡改交付凭据。

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

建 PR、自动批准、自动合并和部署元数据 job 使用常驻的轻量 `aigcnews-control` runner。PR 门禁和定时契约测评使用 `aigcnews-ci-ephemeral`：宿主机控制器根据排队 job 按需创建干净的 LXD JIT runner，每个实例只执行一个 job，结束后注销、留存诊断日志并销毁。控制任务不再被大型测试堵住，也不需要人工维护常驻 CI runner 数量。

Sweeper 可以在同一轮批准所有满足同仓库、`session/*`、机器人创建、精确 head SHA 且未过期约束的门禁，使任务并行进入临时 CI；推进 `main` 的合并仍保持每轮最多一个。若本轮已经批准或重试任何门禁，则不会再合并后续 PR，避免先启动旧基线又立刻改变合并基线。

临时 runner 控制器由 `scripts/ci/ephemeral_runner_autoscaler.py` 实现。首次启用时，以已安装完整测试工具链的 CI LXD 为来源运行 `scripts/ci/prepare_ephemeral_runner_template.sh`，脚本在模板首次启动前禁用克隆的持久 runner 身份，随后清除凭据、工作区和诊断日志。Docker 侧仅保留公共基础镜像的 pull-through registry 容器及其缓存 volume，删除其他容器、业务镜像、构建缓存、网络和 volume；每个 JIT 实例获得独立 CoW 副本，不能把写入带回模板或传给后续任务。主机 mode-0600 的 `$HOME/.config/aigcnews/ci-autoscaler.env` 至少配置 `GH_TOKEN`；建议使用仅对本仓库具有 Administration 写权限的 GitHub App installation token，并通过 `scripts/ci/install_ephemeral_runner_autoscaler.sh` 安装用户级服务。默认最多同时创建两个 4 CPU / 8 GiB 实例；这是宿主机安全上限而不是固定 runner 数量，空闲时实例数为零。

临时 runner 不挂载生产 checkout、私有 Godot 目录或宿主机 Docker socket。每个实例使用自己的 nested Docker daemon；退出后 runner 自动从 GitHub 注销，控制器把 `_diag` 保存到 `$HOME/.local/state/aigcnews-ci-runners/` 后删除 LXD。超过 5 分钟仍未领取 job 且没有 `Runner.Worker` 的实例会被回收；正在执行 job 的实例不受该阈值影响，避免取消、注册或网络故障长期占用并发名额。

只注册一台只能由本仓库使用的生产自托管 runner，并添加标签：

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

- 三个发布镜像和部署必须使用同一台生产 runner 的 Docker daemon；只有通过主分支基线的代码进入该 runner。PR 测试在按需 LXD JIT runner 中执行，交付控制任务在隔离的轻量控制 runner 中执行。
- 构建使用持久化 `default` builder 和 `load: true`，关闭 push；镜像名称保留 GHCR 命名以兼容后续备份，但本流程不上传 GHCR。升级 Docker/Buildx 时必须验证导出的 manifest digest 可以在本机 `docker image inspect repository@sha256:...` 解析。
- 若扩为多台生产 runner，应先设计共享制品分发，不能只复用 runner 标签。
- GitHub workflow 级 `aigcnews-production-latest` concurrency 覆盖元数据、镜像构建和生产切换；同一时间最多一个 active 和一个最新 pending 候选，新的 pending 候选替代旧 pending 候选，从而避免为已被后续 `main` 包含的版本重复构建。PR 等非 `main push` 事件使用按 run ID 隔离的组，不能淘汰真实生产候选。
- `cancel-in-progress: false`，已经开始构建或切换的生产候选不会被新提交取消；合并仅发生在尚未开始的等待队列。
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
