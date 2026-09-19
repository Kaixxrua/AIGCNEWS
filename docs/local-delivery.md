# 本地交付控制器

用户批准后，将 GitHub 从交付关键路径移除。开发→普通 push 到本机 origin→精确 SHA 隔离 CI→串行 CAS 落地主分支→本地不可变镜像构建→迁移/健康门禁→源站与公网边缘发布。GitHub 仅异步 Git 镜像；其配额、可用性、PR 批准不再决定生产进度。

## 权威与隔离

`~/.local/state/aigcnews-local-delivery/authority.git` 为受保护的本地主仓库。共享 checkout 的 `origin` 指向这里，原 GitHub 地址保存为 `github` remote。原有 dev_session.start、origin/main 基线和 post-commit 非强制 push 继续工作；pre-receive 只接受有创建时归属、同名且快进的 session ref，拒绝直接推 main 和删除。仅安装的控制器可在门禁通过后 CAS 更新 main；候选分支不能更换本次运行的门禁脚本。

CI 使用现有独立 LXD 模板、nested Docker 和 6 CPU / 12 GiB 共享池；不挂生产目录、宿主 Docker socket、私有素材、GitHub 凭据。实际 CPU 与内存到达 90% 时不准入。完整基线检查保留。多个提交进入持久队列，先校验包含最新 main 再跑 CI；落地前再次核对 base 和 head。不满足则回原任务处理，不把旧验证套到新提交。

`queue.sqlite` 保存每个 branch+SHA 的单独交付，`runs/<id>/ci.json` 是精确 SHA 回执，日志同目录。CI、landing、release、mirror 分别有进程锁。失败、控制器中断、回执缺失均不放行；失败发布不自动无限重试。refs 差异扫描补偿 post-receive 进程故障，不自动收编未提交或未推送的改动。

部署仅选择最新已验证 local main，已开始候选不中断。复用 `deploy_production.py` 的生产主机锁、digest、迁移、探针和所有权回滚，复用固定私有 Godot 制品及前端黑边契约，复用 PR75 的公网边缘制品发布。GitHub 同步失败存为 pending；只能普通快进推送，遇外部远端分叉必须报告，不强推覆盖。

Stop hook 本地模式优先核对 localDeliveryState 的可靠交接回执，终态可读取真实生产状态，不再调用 GitHub API。`release=delivered` 包含源站与边缘发布成功。旧会话在合入新本地 main 后获得新 hook；既有 AO 显式归属继续使用，未知归属不猜测唤醒。

## 切换步骤与恢复

1. 先记录远端、工作树、运行中 job、部署锁、生产状态，创建仓库外备份；保持原流程运行到安全边界。
2. 将确认的最新 GitHub main 初始化为本地主 main。复制受审控制器到 `~/.local/lib/aigcnews-local-delivery/`，安装 hooks、用户级服务和受保护配置，尚不启用。
3. 使用本地隔离 CI 验证主线和本次控制器，保留全部实测结果。确认没有活动 GitHub worker/发布后禁用旧交付 workflows，停用旧调度/反馈与生产 runner；保留 AO 与共享池。
4. 将 origin 改为本机权威，设置 `aigcnews.localDeliveryState`，依次启用 CI/release/mirror/notify 服务，登记最新主线和本任务提交。
5. 以生产 active SHA、edge-state 和公开端点验收；看板读取本地状态，保留 GitHub 历史但不远程轮询。

切回旧体系必须先排空并停用本地控制器，再对齐两个 main（仅快进），恢复 origin 和旧工作流。两种体系不得同时获得合并/部署写权限。切换中断时保留已部署版本，不删锁、不清数据库、不强推。

配置必须是仓库外可信 JSON，包含 bare/repository/state/production/runtime/github_url、私有制品固定 ID/hash、AO 注册表位置和 local_ci 所需共享池/模板参数。不把生产配置或私有制品提交进仓库。

## 开发任务的停止边界

本地影响面验证通过后，Agent 自动提交并推送。精确 SHA 入队、创建时归属一致、通知控制器在最近 120 秒核实唤醒通道后，Stop hook 允许结束；不等待 CI、合并或发布完成，不把已交接表述为已上线。任务成功只更新看板，失败才唤醒，修复提交再次交接。推送失败、归属未知、通道未就绪或已有待修复失败均不能冒充交接成功。已上线的生产证据仍可作为终态放行依据。基础设施修复的显式全链路验收要求保持。

通知服务通过 `notifier_python` 指定包含 `websockets==15.0.1` 的独立 Python 环境。可信配置中的 `handoff_enabled=true` 启用只读通道检查，`desktop_wakeup=true` 允许没有 AO handoff 的任务使用创建时精确 Codex thread ID；存在 AO 绑定时绝不跨通道回退。新 AO 任务在 dev_session.start 时核对 provider thread ID 并自动激活自己的绑定。旧任务不能靠标题猜测绑定。发送超时保存 unconfirmed，不盲目重发；成功仅更新看板。发布失败只通知精确 release SHA 对应的承接任务。
