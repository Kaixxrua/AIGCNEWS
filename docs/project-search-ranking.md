# 项目语义搜索展示序：相关性 + 长期热度

适用范围：`/api/projects` 的 AI 搜索（`PROJECT_AI_SEARCH_STRATEGY=v2`）与
MCP `search_github_ai_projects`（Go 端 `internal/projectsearch`）。两侧实现逐位一致，
由镜像字面量测试钉住（`backend/tests/test_project_search_ranking.py` ↔
`mcp-go/internal/projectsearch/ranking_test.go`）。

## 为什么不再按今日热度排

旧版在 lane 融合之后直接按**当天** `hot_score` 重排候选：

- 今日暴涨但只沾边的项目压过真正对题的项目（15 条查询回放，首页平均相关性位次 45–122）；
- 每天 00:00 到首轮指标刷新完成（约 02:15）之间当天还没有指标行，排序整体退化成按星数。

## 现行规则

```
展示序 = 精确命中 → 严格钉住（strict lane 一页放得下时）→ 其余按下式降序
score  = 2 / (60 + 相关性位次) + 1 / (60 + 热度位次)        同分回落相关性位次
热度键 = (1 + 近 7 日干净星增) · (1 + 总星数)                 即 log1p 之和的整数单调等价
```

- 相关性位次：lane 融合（`rank_v2_project_candidate_ids`）给出的顺序，1 起。
- 热度位次：候选集内按热度键降序，同键回落相关性位次。
- 近 7 日干净星增：`metric_date ∈ [today-6, today]`、`daily_growth_available`，
  `growth_suspicion_score ≥ 0.5`（即 heat-v7 的降权阈值）的日子记 0。
- 相关性占 2/3：当红但只沾边的候选抬不进首页；相关且有人气的项目前移。
  同一回放下首页平均相关性位次降到 5.5–11.6。
- 7 日窗口跨过零点，不随当天首轮指标的有无翻转。

开关仍叫 `PROJECT_SEMANTIC_HEAT_FIRST`（默认开），关闭即纯相关性序。

## 今日榜跨零点

项目列表的指标 JOIN（`scope=today` 驱动表、`sort=hot`、收藏夹）与分类页"今日暴涨"计数改用**有效指标日**：

```sql
(SELECT COALESCE(MAX(metric_date), today) FROM github_repo_daily_metrics
  WHERE metric_date BETWEEN yesterday AND today)
```

当天首轮落库前沿用昨日指标，首轮落库后即切到当天；最多回退一天，
更早的断档照常显示为空。Python（`postgres_project_catalog._EFFECTIVE_METRIC_DATE_SQL`）
与 Go（`internal/postgres.effectiveMetricDateSQL`）逐字一致。
