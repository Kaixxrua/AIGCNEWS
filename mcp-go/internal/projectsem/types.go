// Package projectsem 移植 backend/app/domain/search_semantics.py（1072 行）
// 的检索语义件：NFKC 归一化、TECHNICAL_TOKEN_RE 手工分词、概念词表
// （_PROJECT_CONCEPT_LEXICON 115 条）、build_project_search_intent、
// build_project_lexical_retrieval_plan、project_search_terms、
// escape_like_literal 等纯函数，以及 PR 2.8 的客户端 intent 规整
// （build_client_project_search_intent / normalize_client_intent_values /
// _PROTECTED_PROJECT_TOKENS）。
//
// 本包不 import 任何 mcpapp/projectsearch/postgres 包（无环方向：
// projectsem ← mcpapp ← projectsearch）。
package projectsem

// ClientIntentFields 对应 contracts.py:ClientProjectSearchIntentInput
// 经 build_client_project_search_intent 规整后的 model_dump
// （exclude={"schema_version"}）九槽位。全部字段已按 pydantic 约束校验
// （条数/单条长度/控制字符/去重），引擎只做消费。
//
// Python 侧槽位（contracts.py:185-243 + search_semantics.py 规整逻辑）：
//
//	language zh|en|mixed|und；intent_class 七枚举；
//	lexical_terms 1-8 条（每条 ≤40 字符）；
//	semantic_queries 1-3 条（每条 ≤120 字符）；
//	topics ≤6、languages ≤3、artifact_types ≤6、must_have ≤6、
//	should_have ≤8（每条 ≤40 字符；languages 每条 ≤30）。
type ClientIntentFields struct {
	Language        string
	IntentClass     string
	LexicalTerms    []string
	SemanticQueries []string
	Topics          []string
	Languages       []string
	ArtifactTypes   []string
	MustHave        []string
	ShouldHave      []string
}
