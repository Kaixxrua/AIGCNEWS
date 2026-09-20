# AI 运维

管理员进入 `/monitor?section=ai-ops`，点击「立即巡检」。复用后台「模型服务」当前保存的配置，运维调用单独使用 low 推理档位降低延迟；没有可用模型时运行显示失败，保留已收集证据，不伪造 AI 结果。可开启自动巡检，间隔 5–120 分钟，默认关闭。自动巡检由应用生命周期管理，关闭浏览器仍执行。

活动记录每两秒刷新，展示实际工具开始、完成、证据、模型分析轮次与最终报告，不展示模型隐式思维过程。记录保存在 PostgreSQL，保留 30 天、页面显示最近 50 次。取消会阻止后续步骤和结果覆盖；已经发出的只读查询或模型请求可能仍在收尾。单次调查总预算 300 秒，最多 4 次模型调用；过期运行 6 分钟后标记中断，跨 worker 使用数据库锁防止重复准入。

工具固定白名单：依赖健康、最近 15 条采集任务、最近 20 条错误元数据、调度状态、自动交付。健康与交付是必采证据，其他工具由模型选择查询顺序；选择格式异常时记录警告并按固定只读清单补齐，非法工具则失败。最后独立生成报告；未查询的范围不能视为正常。错误工具不发送原始日志、堆栈、用户内容或错误消息，只发送时间、级别、logger 和异常类型；采集任务不发送 error_msg。模型输出作为纯文本呈现。没有 shell、配置修改、部署或回滚工具；建议修复继续走现有 session、精确 SHA CI、串行落地和标准部署。

## 自动交付快照

控制器在宿主机，后端在容器。只读桥每 30 秒把控制器 `status.json` 的允许字段投影到已有 metrics 挂载目录，不挂载控制器数据库、凭据或 Docker socket。安装示例（实际路径按部署配置填写）：

```bash
python3 scripts/ai_ops_delivery_bridge.py --install \
  --source /home/kaixxrua/.local/state/aigcnews-local-delivery/status.json \
  --destination /home/kaixxrua/AIGCNEWS-production/storage/metrics/ai_ops/delivery.json
```

生成时间保留上游时间，超过 180 秒标记 stale；桥失败不能用复制时间冒充数据新鲜。缺失时明确 unavailable，不推断部署成功。管理员可以在 delivery 工具结果中检查 `main_sha`、`active_sha` 与任务状态。桥不改变原控制器的 CI、唤醒、合并和发布流程。

停用桥：`systemctl --user disable --now aigcnews-ai-ops-bridge.timer`。停用自动巡检在管理界面保存开关；既有运行需单独停止。

## 验证

覆盖只读工具白名单、取消、模型故障、权限、JSON 输出、独立 PostgreSQL 迁移/并发/租约/持久化、前端实时刷新与 XSS 文本显示。运行记录只是调查证据；completed 表示调查已完成，不等于服务健康或修复完成。
