# 自动提交、合并与生产部署

这条流水线把 session 分支一直交付到生产环境。任务分支和镜像构建可以并行；生产切换只有一个全局写入者，且不要求逐次人工批准。

## 流程

1. Codex 在 `session/<slug>-<id>` 分支完成实现和验证后必须自行暂存本工作单元并提交，不把正常提交或“创建 PR”按钮留给用户；tracked `post-commit` hook 随后自动执行普通 push，失败只保留本地提交，绝不强推或推送 `main`。
2. `Session PR` 为尚无 PR 的 session 分支创建 PR。
3. `Contract Baseline` 在 PR 上运行完整门禁。
4. `Auto Merge Validated Session PR` 只为与成功 CI 完全相同的 head SHA 启用自动合并；分支在验证后发生变化时拒绝合并，其他远端保护条件仍由 GitHub 等待并执行。
5. 合并进入 `main` 后，`Contract Baseline` 再验证受保护主分支。
6. `Deploy Production` 构建 backend、MCP 和 frontend 镜像并推送 GHCR；包含私有 UI 素材的 MCP、frontend 构建在生产 runner 上读取稳定生产目录，生产 job 使用固定 concurrency group 排队。
7. 自托管生产 runner 调用 `deploy_production.py`。控制器再次获取部署机文件锁，拒绝过期 main，按 digest 拉取镜像并切换 Compose。
8. Compose 健康等待及 `/api/live`、`/api/ready` 探测通过后，才原子更新 active release；失败时只有仍拥有本次 `in_progress` 的任务可以恢复上一版本。

## GitHub 配置

仓库需要允许 GitHub Actions 创建 PR、写入 PR 和推送 GHCR。`production` Environment 不设置 required reviewers，从而把仓库管理员的启用行为作为持续部署授权，而不是每次发布授权。

配置 Repository variable：

- `AIGCNEWS_PRODUCTION_ROOT`：部署机稳定检出的绝对路径，例如 `/home/deploy/AIGCNEWS`。

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
- 访问 GHCR 和 `origin`；
- 在部署目录创建 `.release.env` 与 `.aigcnews-deploy/`。
- 读取生产目录中的 `mcp-go/internal/uicatalog/data/` 和 `frontend/.ui-previews/previews/`；这些私有发布素材不会提交到 Git，普通 PR CI 使用合成夹具验证同一构建契约。

生产目录必须保持 tracked 文件干净。`.env`、`.release.env` 和 `.aigcnews-deploy/` 不进入 Git。

## 并发语义

- backend 镜像可在 GitHub 托管 runner 构建；MCP 与 frontend 镜像在生产 runner 上构建，并按可用 runner 容量并行或排队。
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

1. 配置 GitHub Actions 的 PR 写权限和上述 repository variable。
2. 注册并锁定生产 runner。
3. 确认生产 checkout tracked 文件干净，`.env`、TLS 文件、存储目录和私有 overlay 已就绪。
4. 手工运行 `scripts/manage_main_stack.sh config`。
5. 触发一次 `Contract Baseline` 的 `main` push 或后续正常合并；第一次自动部署会建立生产状态文件。

第一次部署失败时，控制器会恢复启用流水线前的 checkout、删除候选 `.release.env`，并用原有本地 Compose 镜像重新协调主栈。

## 故障处理

状态文件位于：

```text
<production-root>/.aigcnews-deploy/state.json
```

`in_progress` 非空表示上一次进程在完成状态提交前异常退出。控制器会 fail-closed，不会猜测生产状态。此时应核对容器实际 digest、`.release.env`、Git HEAD 和健康端点后，再由运维人员修复状态；不要直接删除锁或状态文件后盲目重跑。
