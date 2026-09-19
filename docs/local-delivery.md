# 本地交付控制器

交付效率审查、分阶段实施方案、收益预估和故障验收见 [交付链路效率与无人值守改进方案](delivery-efficiency-plan.md)。规划中的未验收能力不能当作已上线能力；以下描述当前代码及启用条件。

用户批准后，将 GitHub 从交付关键路径移除。开发→普通 push 到本机 origin→精确 SHA 隔离 CI→串行 CAS 落地主分支→本地不可变镜像构建→迁移/健康门禁→源站与公网边缘发布。GitHub 仅异步 Git 镜像；其配额、可用性、PR 批准不再决定生产进度。

## 权威与隔离

`~/.local/state/aigcnews-local-delivery/authority.git` 为受保护的本地主仓库。共享 checkout 的 `origin` 指向这里，原 GitHub 地址保存为 `github` remote。原有 dev_session.start、origin/main 基线和 post-commit 非强制 push 继续工作；pre-receive 只接受有创建时归属、同名且快进的 session ref，拒绝直接推 main 和删除。仅安装的控制器可在门禁通过后 CAS 更新 main；候选分支不能更换本次运行的门禁脚本。

CI 使用现有独立 LXD 模板、nested Docker 和 6 CPU / 12 GiB 共享池；不挂生产目录、宿主 Docker socket、私有素材、GitHub 凭据。实际 CPU 与内存到达 90% 时不准入。完整基线检查保留。多个提交先进入持久队列。启用 `integration_enabled` 时，由唯一集成调度器从当前 main 构造固定批次，默认最多四个任务（`integration_batch_size` 可配置 1～8），对最终组合 SHA 执行一次完整 CI。落地前再次核对 main 与所有输入分支，CAS 成功后原子记录各任务落地和 validated_main。未启用时保留逐任务验证路径。

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

本地影响面验证通过后，Agent 自动提交并推送。精确 SHA 入队、创建时归属一致、通知控制器在最近 120 秒核实唤醒通道后，Stop hook 允许结束；不等待 CI、合并或发布完成，不把已交接表述为已上线。任务成功向原归属会话追加一次完成通知（不启动模型），失败才唤醒，修复提交再次交接。推送失败、归属未知、通道未就绪或已有待修复失败均不能冒充交接成功。已上线的生产证据仍可作为终态放行依据。基础设施修复的显式全链路验收要求保持。

通知服务通过 `notifier_python` 指定包含 `websockets==15.0.1` 的独立 Python 环境。可信配置中的 `handoff_enabled=true` 启用只读通道检查，`desktop_wakeup=true` 允许没有 AO handoff 的任务使用创建时精确 Codex thread ID；存在 AO 绑定时绝不跨通道回退。新 AO 任务在 dev_session.start 时核对 provider thread ID 并自动激活自己的绑定。旧任务不能靠标题猜测绑定。发送超时保存 unconfirmed，不盲目重发；成功通过 thread/inject_items 追加原会话历史，不调用 turn/start。发布失败只通知精确 release SHA 对应的承接任务。

## 下载恢复与预验证复用

执行器对依赖安装、Go tidy/build/vet、前端镜像构建中的明确网络暂态错误（EOF、连接重置、DNS 暂态、502/503/504、网络超时）最多执行三次，总计仍受原 job deadline 限制。断言失败、编译错误、校验和错误、测试、迁移不自动重放。Go 使用 `https://proxy.golang.org|https://goproxy.cn|direct`，竖线允许网络错误切换源，保留校验和验证。

可信执行器支持 `--jobs mcp-go frontend-build` 预验证指定完整检查。预验证回执不是完整交付门禁；正式 CI 仍必须产生五项成功且清理完成的精确 SHA 回执。只有同一完整 Git tree、相同工作流/控制覆盖、执行器和可信配置的成功检查可以复用，复用时保留原 SHA/run ID，最长一小时且复用不续期。失败或未完成清理不缓存，源码变化使缓存失效。

复用默认关闭，管理员必须在可信配置中设置 `verification_environment_digest`（64 位十六进制），指向已验证固定的 runner 模板/工具链环境；环境升级必须更换该值。普通宿主上的任意 pytest/npm 输出、Agent 自述测试通过均不能作为跳过 CI 的凭据。本地零散快速测试尚不等同于该隔离预验证入口。

本地发布在三个镜像构建并校验 digest 后保存 `verified-images.json`。同一源码 SHA、私有制品配置及发布脚本一致的再次执行，会先确认三个不可变镜像仍存在，再直接进入原有部署/健康门禁；不重复构建，也不重新运行 CI。该检查点不代表已部署，不绕过发布锁、生产状态、迁移或健康检查。

### 提交前快速验证

暂存本次工作后运行安装后的 `local_preflight.py --repository "$PWD" --jobs frontend-build`（也支持 `backend-tests`、`mcp-go`）。入口对暂存 tree 创建不移动分支的验证对象，随后调用可信隔离执行器。前端单测/lint/typecheck、后端 lint、Go vet/test 可按步骤复用；准备依赖、生成测试夹具及生产构建仍执行。代码、测试、依赖或控制配置变化全部失效，partial preflight 永远不能作为完整 CI 回执。零散 pytest 文件子集尚不覆盖完整后端套件，不能据此跳过该套件。

可信配置可使用 `template_snapshot` 固定停止状态的 LXD 模板快照；执行器读取该快照的实时元数据生成环境指纹，克隆同一快照。快照替换会使回执失效。预验证和正式 CI 必须共用这份配置。

发布保存 build/deploy/edge 阶段回执，最多三次尝试；build/edge 的明确暂时性网络失败按 30/60 秒退避重试当前固定候选。控制器重启只恢复无未完成生产切换的安全阶段；deploy 阶段中断、迁移和健康检查失败不盲目重放。旧版部署前 worktree 环境错误的有证据恢复仍保留。每次保留先前回执和日志。

设置 `git config aigcnews.preflightReuse true` 后，前端提交钩子自动改用安装后的隔离预验证入口，替代宿主快速类型检查/related 测试；正式 CI 执行未覆盖步骤，并明确记录 `reused_from`。后端文件子集测试不冒充全量覆盖。

## 成功通知

### 启动锁准入重试

尚未获得启动锁的检查在原 `queue_timeout` 总预算内最多尝试三次，
间隔退避并记录 `admission_attempt`、`admission_history`、`retry_at`。
只重试该检查的准入，不重新执行同一候选已经完成的其他检查。
一旦进入容器启动路径，超时不在此自动重放；必须保留清理和失败回执。
总预算耗尽仍会失败并通知原任务，不能保证资源不足时永不超时。

可信配置 `success_notifications=true` 和 `success_notifications_since`（UTC ISO 时间）开启启用时间之后的成功消息。通知仅接受控制器已标记 `delivered` 的任务，并核对创建时归属记录；使用 `thread/inject_items` 写入原会话，不新建会话、不启动模型 turn。每个交付 ID + SHA 仅一次，发送前持久化意图，超时标记 unconfirmed，禁止盲目重发。回执存于 `success_notifications` 表和 `success-notification:<id>` 元数据。不为启用前所有历史任务批量补发。接口保证历史持久化，客户端是否即时刷新由客户端决定。

### 临时执行器启动延迟

启动锁仅覆盖资源准入、容器创建配置、启动和 cgroup 归属检查。
容器内工具链检查、隔离清理与 Docker 就绪等待在释放启动锁后进行；
这些动作不访问其他工作树或执行器。资源池的 6 CPU / 12 GiB 上限、
90% 准入门槛以及启动中容器预算仍然生效。容器配置使用一次批量调用。

检查回执中的 `admission_acquired_at`、`launched_at`、`initialized_at`
分别定位排队、启动和初始化耗时，避免将全部等待误算为测试耗时。

## 固定候选、批量集成与缓存

- 发布器空闲时选择最新已验证 main；一旦选定 A，即使 B、C 合入也继续完成 A。A 完成后立即检查下一轮，选择包含 A/B/C 的最新已验证主线。不设置人为攒批窗口；空闲轮询仍有最多约 10 秒调度延迟。
- 集成期间到达的新任务属于下一批。批内失败先拆成单任务定位，不让同一失败组合无限重跑；冲突回归原任务，成功检查绝不转移给未经验证的组合。
- `integrations/<id>/ci.json` 证明的是组合 SHA，任务快照另含 `verification_sha` 与 `integration_batch`。看板必须同时核对原任务是组合提交的祖先，不能伪造原 SHA 的 CI 回执。Git 已 CAS、数据库未落账的中断，只在精确完整 CI 回执可核验时恢复记账。
- 源站已经是固定候选时，重试只进入 edge。每个已成功边缘站点仍需核对远端当前版本、制品摘要及 smoke，确认后才能跳过；源站与全部配置站点回执一致才标记 delivered。
- `prepare_dependency_seed.py` 在隔离克隆中预热已合入主线的锁文件依赖，产出停止状态模板快照；正式任务各自克隆并写私有缓存，不共享候选可写依赖目录。模板更新须验证后切换配置，不能修改运行中的 runner。
- Go/npm/pip 下载缓存落在 `/opt/aigcnews-dependencies`；生产 Docker 使用各自持久 BuildKit cache mount，生产前端宿主安装使用 state 下 npm 缓存。锁文件或平台变化仍需下载新增内容；缓存不是取消安装、编译、校验或测试。
- `install_controller_version.py` 按文件摘要建立版本目录，并拒绝复用被修改的目录。运行控制器不能在原目录覆盖升级：先备份可信配置与队列，等待旧执行收尾，再修改 runtime、systemd ExecStart 并重启；回退同样需先确认没有旧执行者和未完成生产切换。

现阶段没有宣称完成组件级测试复用、CI 生产制品统一晋升、逐服务镜像检查点、所有中断的自动恢复或永久无人干预。保留失败可见和定向归属唤醒，不用自动重试掩盖真实代码错误。
