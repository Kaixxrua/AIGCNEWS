# 项目语义搜索展示序：相关性 + 长期热度

适用范围：`/api/projects` 的 AI 搜索（`PROJECT_AI_SEARCH_STRATEGY=v2`）与
MCP `search_github_ai_projects`（Go 端 `internal/projectsearch`）及全站快捷搜索的项目结果。
Python REST 与 MCP 共用本地候选编排，Go 实现相同意图与排序契约，
由数据库贯通测试及镜像测试验证（`backend/tests/test_project_search_ranking.py` ↔
`mcp-go/internal/projectsearch/ranking_test.go`）。

## 为什么不再按今日热度排

旧版在 lane 融合之后直接按**当天** `hot_score` 重排候选：

- 今日暴涨但只沾边的项目压过真正对题的项目（15 条查询回放，首页平均相关性位次 45–122）；
- 每天 00:00 到首轮指标刷新完成（约 02:15）之间当天还没有指标行，排序整体退化成按星数。

## 现行规则

```
展示序 = 精确命中 → 全概念/严格词匹配 → 其余按下式降序
score  = 2 / (60 + 相关性位次) + 1 / (60 + 热度位次)        同分回落相关性位次
热度键 = (1 + 近 7 日干净星增) · (1 + 总星数)                 即 log1p 之和的整数单调等价
```

- 相关性位次：lane 融合（`rank_v2_project_candidate_ids`）给出的顺序，1 起。
- 全概念/严格词匹配始终在部分匹配之前，且在候选池截断前生效。
  此规则不依赖每页条数，热度查询失败或关闭热度融合时也保留。
- 热度位次：候选集内按热度键降序，同键回落相关性位次。
- 近 7 日干净星增：`metric_date ∈ [today-6, today]`、`daily_growth_available`，
  `growth_suspicion_score ≥ 0.5`（即 heat-v7 的降权阈值）的日子记 0。
- 相关性占 2/3：当红但只沾边的候选抬不进首页；相关且有人气的项目前移。
  同一回放下首页平均相关性位次降到 5.5–11.6。
- 7 日窗口跨过零点，不随当天首轮指标的有无翻转。

开关仍叫 `PROJECT_SEMANTIC_HEAT_FIRST`（默认开），关闭即纯相关性序。
以上为基础候选排序；启用可选模型重排器时，它仍可进一步调整前排结果。

## 概念匹配与词表维护

v2 词法召回对纯英文概念词使用字母/数字边界：`eval` 不再误匹配
`retrieval`，`rag` 不再误匹配 `storage`。标点、下划线和中文可以作为
英文词边界，保留 `RAG-eval`、`RAG_eval` 和 `RAG评测` 的召回。
常见评估复数形式（evaluations、benchmarks、evals）显式列入别名。
概念词按字面转义并作为参数绑定；中文概念词保留子串匹配。

“长期记忆”“智能体长期记忆”和英文 long-term memory 归入智能体记忆。
“代码库长期记忆”“项目长期记忆”仍归入代码库记忆，避免通用记忆需求
被扩展成编程工具。名称定位、普通字面查询、显式 stars/hot 排序、
可见性与分类过滤以及 REST/MCP 响应字段保持原有契约。

词表唯一编辑来源为 `backend/app/domain/project_search_concepts.py`；
解析器 `search_semantics.py` 只负责意图解析。修改词表后运行：

```bash
python scripts/sync_project_search_concepts.py
python scripts/sync_project_search_concepts.py --check
```

生成的 Go 词表和 JSON 对照表一并提交。后端测试自动检查生成文件，
Go 测试核对词表；两端复用 `concept_patterns.json` 的匹配案例，
PostgreSQL 集成测试另行验证真实 SQL 的边界、字面转义和名称搜索兼容性。

## 今日榜跨零点

项目列表的指标 JOIN（`scope=today` 驱动表、`sort=hot`、收藏夹）与分类页"今日暴涨"计数改用**有效指标日**：

```sql
(SELECT COALESCE(MAX(metric_date), today) FROM github_repo_daily_metrics
  WHERE metric_date BETWEEN yesterday AND today)
```

当天首轮落库前沿用昨日指标，首轮落库后即切到当天；最多回退一天，
更早的断档照常显示为空。Python（`postgres_project_catalog._EFFECTIVE_METRIC_DATE_SQL`）
与 Go（`internal/postgres.effectiveMetricDateSQL`）逐字一致。

## 搜索入口与结果契约

- 有查询且按 relevance 排序时，网页与快捷搜索复用 discovery 的概念/词法/语义候选和排序流程；HTTP 注入应用持有的语义、重排和 shadow 资源，不创建另一套运行实例。
- REST 保留完整项目行、当前用户收藏状态、24 条默认分页及最多 60 条页大小；MCP 保留精简公开投影和最多 20 条。网页只展示已入库项目，GitHub 外部回退仍由 MCP 入口处理。
- 行为变化：网页相关性搜索的 total 现在表示经过可见性/分类过滤的候选集总数（上限 200），与 MCP 的有界发现检索一致。无查询浏览和显式 stars/hot 等排序继续使用原有目录查询。
- 未收录于概念表的中文专名保留为字面条件，已验证的客户端 lexical_terms 会补入词法计划；tutorial/tutorials、workflow/workflows 等词形显式扩展，保留英文词边界。
- recommended 在词法候选截断前应用 active 推荐成员过滤。普通目录筛选与候选回填仍再次执行可见性与筛选条件。
- GitHub 返回限流/禁用等错误对象时保留已有本地结果，并通过 fallback_error 报告失败；语义补搜沿用显式排序。MCP 的 tags/topics 接受数据库规范化后的字符串数组。

## 离线质量评估

`scripts/eval_project_search_quality.py` 的 NDCG@k 分母使用查询级完整理想排序，先排序再取 k，不能只在系统已返回的前 k 条内计算理想值。例如 `[1, 0, 0, 3]` 的 NDCG@3 为约 0.131，而不是 1。

每个 case 可在输入 schema v1 中添加 `judgments: {"owner/repo": 0..3}`，纳入所有已知相关项目，包括所有系统都漏掉的答案；它与各系统 `result_ids`/`relevance` 合并成共用标注池。未提供 judgments 的旧夹具使用所有系统返回项目的标注并集，因此仍不能衡量完全未知的漏召回。相同项目的冲突标注会拒绝评估，不静默取高值。新旧指标口径不同，历史报告应使用同一夹具重新计算后比较。
