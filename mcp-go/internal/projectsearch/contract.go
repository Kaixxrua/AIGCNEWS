// Package projectsearch 移植 backend/app/services/project_discovery.py
// 的检索引擎（search_projects 全流程决策树：双模式归一化、hybrid 候选
// 召回、legacy/v2 排名、热度钉顶、reranker 挂接、基座响应装配、低相关
// 护栏、语义零结果重试、GitHub fallback 编排）与
// backend/app/services/ingestion/source_github_mcp.py 的 GitHub fallback
// 本体（LRU+TTL 缓存、查询构造、HTTP 归一化、去重排序）。
//
// 语义检索件（embedding HTTP、Milvus 向量库、reranker HTTP）由本包的
// semantic.go/milvus.go/reranker.go 实现，经本文件的接口与引擎解耦。
//
// 引擎对外边界是 mcpapp.ProjectSearchEngine（SearchProjects）；Postgres
// 适配器（internal/postgres/project_search.go）实现引擎的 CatalogReader。
package projectsearch

// SemanticHit 是语义召回的单条命中（对齐 project_semantic_search 的
// search_repo_ids 返回元素：Milvus per-repo 最大 COSINE 分过阈值、
// (-score, repo_id) 排序后的 repo_id 序列带分数）。
type SemanticHit struct {
	RepoID string
	Score  float64
}

// SemanticSearcher 对应 project_semantic_search.ProjectSemanticSearch 的
// search_repo_ids(intent)：消费 intent.semantic_queries（逐条 embed →
// Milvus 检索 → RRF k=60 融合多路 ranking），产出命中序列。
//
// 语义开关关闭（project_semantic_search_enabled=false，生产默认）时引擎
// 不调用本接口；实现内部也保留 enabled 短路返回空。超时由引擎侧以
// asyncio.wait_for 同义手段（goroutine + select，max(0.1, timeout)）
// 施加，故接口不带 ctx。错误语义对齐 Python：调用方按「任一路异常降级
// 为空」处理，实现只需如实返回 err。
type SemanticSearcher interface {
	SearchRepoIDs(semanticQueries []string) ([]SemanticHit, error)
}

// Reranker 对应 project_reranker.rerank_repo_ids(query, projects)：
// projects 是引擎水合后的候选行（normalize_project_row 形态，含
// full_name/title/description*/category*/tags/topics/language 九字段）；
// 返回 full_name 序列（本 schema 下 full_name 即候选 repo_id）。
//
// 失败/关闭/候选不足/校验不过时恒返回恒等序列（strip 后非空的
// full_name 原序），不返回 error——对齐 Python 的全路径静默回退。
// query 由引擎侧先经 _project_reranker_query 富化后再传入。
type Reranker interface {
	RerankRepoIDs(query string, projects []map[string]any) []string
}
