"""Reviewed troubleshooting knowledge; matching never grants action permission."""
POLICY_VERSION = "ai-ops-v2"

# Versioned with code. Steps are guidance; there is no executable model-supplied command.
RUNBOOKS = (
    ("x-api", "X API 采集失败", {"x"}, set(),
     "同源近期仍失败，且后续没有成功；先区分 API 错误与译文任务失败。",
     ["查看 source_trends 中 X 的最近成功、失败趋势及产出。", "核对 errors 的鉴权、限流、额度、网络分类。",
      "鉴权或额度问题转管理员；限流遵守冷却；程序错误走代码修复。"],
     "后续同源任务成功且产出大于零；不得把历史错误当作持续故障。"),
    ("x-translation", "X 译文停滞", {"x"}, set(),
     "存在 retryable 任务且最近成功超过 30 分钟；陈旧租约与活跃任务分别统计。",
     ["核对 x_translations 的 pending、stale_running 和最近成功时间。",
      "仅由候选白名单提交一次译文重试；仍有有效租约时等待。", "跟踪回访中的原始任务集合，不能用其他新任务成功代替。"],
     "目标任务全部 succeeded 且译文非空；此结论仅覆盖目标集合，不代表页面已验证。"),
    ("arxiv", "arXiv 下载失败", {"arxiv"}, set(),
     "错误来自 PDF 下载；采集任务成功不等于每篇 PDF 均下载成功。",
     ["区分 429 限流、连接失败和超时。", "核对同源成功趋势；限流等待原调度退避，持续失败转代码调查。"],
     "后续下载成功证据与错误率下降同时成立；当前工具缺少单篇下载结果时明确未知。"),
    ("email", "邮件投递失败", {"email", "briefing"}, set(),
     "投递报错；简报生成与邮件投递属于不同阶段。",
     ["核对 SMTP 连接、鉴权及拒收分类。", "确认简报已生成，再检查投递回执；避免重复生成或重复发送。"],
     "以对应投递回执成功为准；简报存在只证明生成成功。"),
    ("database", "数据库查询超时或锁等待", set(), {"query_timeout", "db_lock"},
     "QueryCanceled 或锁错误仍在发生。",
     ["结合脱敏堆栈位置、database 的活动查询与锁等待计数。", "对照最近发布版本和 source_trends 判断影响范围。",
      "定位查询或事务后经契约测试和标准交付修复；不能仅凭超时推断缺索引。"],
     "同路径后续查询恢复，且超时或锁等待下降；单次 SELECT 1 不能验证。"),
    ("model", "模型调用超时", {"model", "briefing"}, {"timeout"},
     "运维或简报模型请求超时；Ollama 不可用不能证明外部聊天模型故障。",
     ["核对 investigation_history 中失败阶段与次数。", "保留固定采集证据和降级摘要；下一轮再调查，不无限重试。"],
     "后续模型请求成功并生成有效报告；程序摘要不视为 AI 报告。"),
    ("program", "程序契约异常", set(), {"program"},
     "TypeError、KeyError 等异常匹配到应用堆栈位置。",
     ["用脱敏堆栈定位模块，关联部署版本。", "复现失败并增加契约测试，走 session、精确 SHA CI 和标准部署。"],
     "复现用例通过且对应业务路径恢复；不靠重复任务修复代码异常。"),
)


def knowledge(evidence, cases):
    errors = evidence.get("errors", {}).get("result", {})
    groups = errors.get("groups", []) if isinstance(errors, dict) else []
    sources = {g["source"] for g in groups}
    categories = {g["category"] for g in groups}
    queue = evidence.get("x_translations", {}).get("result", {})
    if queue.get("retryable"):
        sources.add("x")
    history = evidence.get("investigation_history", {}).get("result", {})
    if history.get("failures"):
        sources.add("model")
    books = [{"id": id, "title": title, "version": POLICY_VERSION, "conditions": condition,
              "steps": steps, "verification": verification}
             for id, title, src, cats, condition, steps, verification in RUNBOOKS
             if sources & src or categories & cats]
    relevant = {"x_translation_retry": "x", "briefing_regenerate": "briefing", "public_feed_retry": "other",
                "ingestion_orphan_close": "other"}
    matched = [c for c in cases if relevant.get(c["action"]) in sources | {"other"}
               and c["policy_version"] == POLICY_VERSION and c["status"] in {"verified", "not_recovered"}]
    return {"runbooks": books, "cases": matched[:10], "policy_version": POLICY_VERSION,
            "usage": "历史结果仅供对照；需重新核对适用条件、当前版本和动作预算。观测恢复不证明因果。"}
