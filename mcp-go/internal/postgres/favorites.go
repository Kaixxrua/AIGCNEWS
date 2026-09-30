package postgres

// favorites.go 移植 backend/app/repositories/postgres_project_write_repository.py
// 的 list_user_project_collection —— 即 postgres_project_catalog.py 的
// list_projects 在 favorites 专用窄口径下的展开形态：
//
//	source="github", scope="all", min_stars=500, enriched_only=True,
//	favorites_only=True, candidate_repo_ids=None, sort 永不为 "relevance"
//
// （sort 白名单见 services/mcp/inbound/catalog.py 的 _PROJECT_SORT_CHOICES；
// 调用入口 tools.py::_tool_list_user_project_collection 固定 source/scope。
// 若将来契约放宽允许 sort="relevance"，需要回补 _resolve_order 的 relevance
// CASE 分支与 _strong_match_threshold 的 has_strong_match 列，本文件未移植。）
//
// 逐字对齐的源片段：
//   - list_projects 的 gh_filters/gh_filter_params 组装段（约 932-1002 行）
//   - _build_gh_branch（276-338）：SELECT 列序、FROM/JOIN 文本、参数序
//     [date, user_id, *filter_params]
//   - _GH_SELECT_COLUMNS / _GH_SELECT_TAIL_COLUMNS / 收藏列片段
//   - _build_union_queries（378-395，strong_threshold=0 形态）：count/rows
//     两条 CTE 查询
//   - _resolve_order（398-446，scope="all" 的 recent 锚）
//   - project_catalog_normalization.py::normalize_project_row（59-112）全量
//   - search_semantics.py::project_search_terms（766-790）与
//     escape_like_literal（1071-1072，复用 documents.go 的 escapeLikeLiteral）
//
// 已知偏差（均不可达或已注明）：
//   - normalize_project_row 的 website 分支（WEBSITE_* taxonomy）不可达——
//     窄口径 source 恒为 "github"，仅移植 github 侧 taxonomy 表。
//   - has_strong_match 列在窄口径下从不生成（threshold 恒 0），Python 的
//     row.pop("has_strong_match", None) 为防御性 no-op，Go 侧无需对应物。
//   - _json_list 对非字符串标量元素模拟 Python str()：json.Number 保留字面量
//     （等价 str(int)/简单 float），bool→"True"/"False"，nil→"None"；嵌套
//     结构的 Python repr 形态用 fmt %v 近似——tags/topics 实际均为字符串数组。
//
// 依赖并行任务：本文件引用 mcpapp.ProjectCollectionFilters /
// mcpapp.ProjectCollectionPage（由并行 agent 在 mcpapp 包定义）；在这两个
// 符号落地前 `go build ./internal/postgres/` 报未定义符号属预期。
//
// 时区：import _ "time/tzdata" 已由 statistics.go 携带（同包生效），不重复。

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/mcpapp"
)

// projectCollectionMinStars 对应窄口径固定参数 min_stars=500
// （tools.py 传入 PUBLIC_PROJECT_MIN_STARS）。
const projectCollectionMinStars = 500

// ghSelectColumns 逐字搬运 _GH_SELECT_COLUMNS（github 分支 58 列，
// 源自 _LIST_PROJECT_COLUMN_PAIRS 的 github 表达式列）。
var ghSelectColumns = []string{
	"'github:'||c.repo_id id",
	"'github' source",
	"c.repo_id",
	"NULL::bigint website_id",
	"c.full_name",
	"c.title",
	"c.url",
	"NULL::text domain",
	"NULL::text image_url",
	"c.description",
	"ge.description_zh",
	"ge.description_en",
	"ge.category_slug",
	"COALESCE(NULLIF(ge.category_name_zh,''),ge.category_name) category_name",
	"ge.category_name_zh",
	"ge.category_name_en",
	"ge.subcategory_slug",
	"COALESCE(NULLIF(ge.subcategory_name_zh,''),ge.subcategory_name) subcategory_name",
	"ge.subcategory_name_zh",
	"ge.subcategory_name_en",
	"ge.tags_json::text tags_json",
	"ge.tags_zh_json::text tags_zh_json",
	"ge.tags_en_json::text tags_en_json",
	"'system'::text tags_origin",
	"c.language",
	"c.license_spdx_id",
	"c.topics_json",
	"CASE WHEN gm.repo_id IS NOT NULL THEN gm.stars ELSE COALESCE(c.stars,0) END stars",
	"CASE WHEN gm.repo_id IS NOT NULL THEN gm.forks ELSE COALESCE(c.forks,0) END forks",
	"CASE WHEN gm.repo_id IS NOT NULL THEN gm.watchers ELSE COALESCE(c.watchers,0) END watchers",
	"CASE WHEN gm.repo_id IS NOT NULL THEN gm.open_issues ELSE 0 END open_issues",
	"c.created_at",
	"c.pushed_at",
	"c.first_seen_at",
	"c.last_seen_at",
	"c.last_snapshot_at",
	"gm.metric_date snapshot_date",
	"c.last_snapshot_at captured_at",
	"NULL::integer rank_in_period",
	"COALESCE(gm.daily_star_growth,0) raw_score",
	"COALESCE(gm.hot_score,0) score",
	"gm.metric_date daily_growth_date",
	"gm.previous_snapshot_date",
	"COALESCE(gm.daily_star_growth,0) daily_star_growth",
	"COALESCE(gm.daily_growth_available,FALSE) daily_growth_available",
	"COALESCE(gm.daily_growth_source,'unavailable') daily_growth_source",
	"gm.daily_growth_observed_at",
	"COALESCE(gm.hot_score,0) hot_score",
	"COALESCE(gm.scale_corrected_growth_score,0) scale_corrected_growth_score",
	"COALESCE(gm.growth_acceleration_score,0) growth_acceleration_score",
	"COALESCE(gm.absolute_growth_score,0) absolute_growth_score",
	"COALESCE(gm.maintenance_activity_score,0) maintenance_activity_score",
	"COALESCE(gm.community_engagement_score,0) community_engagement_score",
	"COALESCE(gm.growth_suspicion_score,0) growth_suspicion_score",
	"COALESCE(gm.growth_suspicion_signals,'[]') growth_suspicion_signals",
	"COALESCE(gm.growth_corroborated,FALSE) growth_corroborated",
	"c.availability_status",
	"ge.confidence",
}

// ghFavoriteColumns 逐字搬运 _build_gh_branch 登录用户收藏列片段
// （单字符串，内部逗号+空格与 Python 原文一致）。
const ghFavoriteColumns = "(pf.id IS NOT NULL) is_favorited, pf.created_at favorited_at," +
	" FALSE user_added, NULL::timestamptz user_added_at," +
	" pf.created_at collection_at"

// ghSelectTailColumns 逐字搬运 _GH_SELECT_TAIL_COLUMNS。
var ghSelectTailColumns = []string{
	"(gr.repo_id IS NOT NULL) is_recommended",
	"gr.recommended_at",
}

// FROM/JOIN 文本逐字搬运 _GH_SELECT_FROM 与 _build_gh_branch 的
// hot_join/user_join（scope="all"、user_id 非空形态）。
const ghSelectFrom = " FROM github_repo_candidates c" +
	" LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id" +
	" LEFT JOIN github_repo_recommendations gr ON gr.repo_id=c.repo_id AND gr.active=TRUE"
const ghMetricsJoin = "LEFT JOIN github_repo_daily_metrics gm" +
	" ON gm.repo_id = c.repo_id AND gm.metric_date = " + effectiveMetricDateSQL

// effectiveMetricDateSQL 逐字搬运 _EFFECTIVE_METRIC_DATE_SQL：当天首轮指标
// 落库前沿用昨天的收盘切片，只回退一天。参数见 effectiveMetricDateParams。
const effectiveMetricDateSQL = "(SELECT COALESCE(MAX(md.metric_date),%s) FROM github_repo_daily_metrics md" +
	" WHERE md.metric_date BETWEEN %s AND %s)"

// effectiveMetricDateParams 对齐 _effective_metric_date_params：[今天, 昨天, 今天]。
func effectiveMetricDateParams(now time.Time) []any {
	today := now.Format("2006-01-02")
	return []any{today, now.AddDate(0, 0, -1).Format("2006-01-02"), today}
}

const ghFavoritesJoin = "LEFT JOIN project_favorites pf" +
	" ON pf.user_id=%s AND pf.project_source='github' AND pf.project_id=c.repo_id"

// ghTermMatchFieldsWithI18nTags 逐字搬运 _GH_TERM_MATCH_FIELDS_WITH_I18N_TAGS。
var ghTermMatchFieldsWithI18nTags = []string{
	"c.full_name",
	"c.title",
	"c.description",
	"COALESCE(ge.description_zh, '')",
	"COALESCE(c.language, '')",
	"COALESCE(c.topics_json, '')",
	"COALESCE(ge.tags_json::text, '')",
	"COALESCE(ge.tags_zh_json::text, '')",
	"COALESCE(ge.tags_en_json::text, '')",
}

// ghTermMatchFilter 复刻 _term_match_filter(_GH_TERM_MATCH_FIELDS_WITH_I18N_TAGS)。
var ghTermMatchFilter = func() string {
	parts := make([]string, len(ghTermMatchFieldsWithI18nTags))
	for i, field := range ghTermMatchFieldsWithI18nTags {
		parts[i] = field + " ILIKE %s ESCAPE '='"
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}()

// collectionRecentAnchor 逐字搬运 _resolve_order scope="all"（非 recommended）
// 的 recent 锚表达式。
const collectionRecentAnchor = "COALESCE(collection_at,NULLIF(first_seen_at,'')::timestamptz,NULLIF(last_seen_at,'')::timestamptz)"

// collectionOrderBy 复刻 _resolve_order 的 orders 映射（窄口径：scope="all"
// 且 sort≠"relevance"）；未知 sort 走 orders.get 的默认 stars 分支。
func collectionOrderBy(sort string) string {
	switch sort {
	case "hot":
		return "hot_score DESC NULLS LAST,daily_star_growth DESC NULLS LAST,stars DESC,full_name ASC"
	case "stars":
		return "stars DESC,forks DESC,full_name ASC"
	case "updated":
		return "COALESCE(NULLIF(pushed_at,''),last_seen_at::text,first_seen_at::text) DESC NULLS LAST,stars DESC,full_name ASC"
	case "recent":
		return collectionRecentAnchor + " DESC NULLS LAST,stars DESC,full_name ASC"
	case "name":
		return "full_name ASC"
	default:
		return "stars DESC,forks DESC,full_name ASC"
	}
}

// projectTransportTerms 逐字搬运 search_semantics.py 的
// _PROJECT_TRANSPORT_TERMS（词表本身均为小写 ASCII/中文，Python 侧
// casefold 后与原文相同）。
var projectTransportTerms = map[string]bool{
	"github": true, "repo": true, "repository": true, "repositories": true,
	"project": true, "projects": true,
	"项目": true, "仓库": true, "工具": true,
}

// projectSearchMaxTerms 对应 project_search_terms 的 max_terms=8。
const projectSearchMaxTerms = 8

// projectSearchTerms 复刻 project_search_terms → search_terms：
// NFKC+空白折叠（复用 documents.go normalizeSearchQuery）→
// TECHNICAL_TOKEN_RE 分词（复用 technicalTokens）→ casefold 去重、
// 屏蔽词表过滤、丢弃单字符非数字词，上限 8。
func projectSearchTerms(value string) []string {
	normalized := normalizeSearchQuery(value)
	var terms []string
	seen := map[string]bool{}
	for _, token := range technicalTokens(normalized) {
		key := caseFolder.String(token)
		if projectTransportTerms[key] || seen[key] {
			continue
		}
		// Python: len(token) == 1 and not token.isdigit()。
		// token 单 rune 时取其首 rune 判数字；token 字符集只含
		// ASCII/字母数字词与 CJK 段，Unicode 数字不会出现在 token 中。
		if utf8.RuneCountInString(token) == 1 {
			r, _ := utf8.DecodeRuneInString(token)
			if !unicode.IsDigit(r) {
				continue
			}
		}
		seen[key] = true
		terms = append(terms, token)
		if len(terms) >= projectSearchMaxTerms {
			break
		}
	}
	return terms
}

// ── taxonomy 兜底表（github 侧）────────────────────────────────────────
// 逐字搬运 backend/app/domain/project_taxonomy.py 的 PROJECT_TAXONOMY 派生表
// 与 ENGLISH_LABEL_BY_SLUG。mcpapp 侧现有等价物仅
// project_categories.go 的 StaticProjectCategoriesRepository 演示数据
// （非全量 taxonomy），不可复用，故在此移植最小必需表。

// ghCategoryNameBySlug 对应 CATEGORY_BY_SLUG（slug → 中文名）。
var ghCategoryNameBySlug = map[string]string{
	"productivity_tools": "AI 效率工具",
	"coding_tools":       "AI 编程工具",
	"agents_automation":  "AI Agent / 自动化",
	"ai_apps":            "AI 产品 / 应用",
	"learning_resources": "AI 教程 / 学习资源",
	"rag_knowledge":      "RAG / 知识库",
	"multimodal_tools":   "多模态工具",
	"models_infra":       "模型 / 推理 / 部署",
	"data_eval_training": "数据 / 评测 / 训练",
	"security_privacy":   "安全 / 隐私",
	"other":              "其他",
}

// ghSubcategoryNameBySlug 对应 SUBCATEGORY_BY_CATEGORY_SLUG
// （category slug → subcategory slug → 中文名）。
var ghSubcategoryNameBySlug = map[string]map[string]string{
	"productivity_tools": {
		"writing_docs":         "写作 / 文档",
		"meetings_email":       "会议 / 邮件",
		"browser_search":       "浏览器 / 搜索",
		"office_automation":    "办公自动化",
		"notes_knowledge":      "笔记 / 知识管理",
		"personal_assistant":   "个人助手",
		"spreadsheet_analysis": "表格 / 数据分析",
		"productivity_other":   "其他效率工具",
	},
	"coding_tools": {
		"code_generation":   "代码生成",
		"code_review":       "代码审查",
		"ide_plugins":       "IDE / 编辑器插件",
		"testing_ci":        "测试 / CI 自动化",
		"dev_agents":        "开发智能体",
		"code_search_docs":  "代码搜索 / 文档",
		"low_code_scaffold": "低代码 / 脚手架",
		"coding_other":      "其他编程工具",
	},
	"agents_automation": {
		"agent_frameworks":    "Agent 框架",
		"multi_agent":         "多智能体协作",
		"workflow_automation": "工作流自动化",
		"mcp_tool_use":        "MCP / 工具调用",
		"browser_rpa":         "浏览器 / RPA 自动化",
		"research_agents":     "自主研究助手",
		"personal_automation": "个人自动化助手",
		"agent_other":         "其他 Agent 工具",
	},
	"ai_apps": {
		"chat_clients":        "聊天客户端",
		"ai_search_products":  "AI 搜索产品",
		"vertical_saas":       "垂直 SaaS",
		"desktop_mobile_apps": "桌面 / 移动应用",
		"marketing_sales":     "营销 / 销售",
		"education_apps":      "教育应用",
		"customer_ops":        "客服 / 运营",
		"ai_apps_other":       "其他 AI 应用",
	},
	"learning_resources": {
		"awesome_lists":       "Awesome List",
		"tutorials_courses":   "教程 / 课程",
		"prompt_collections":  "Prompt 合集",
		"papers_reading":      "论文 / 阅读",
		"examples_templates":  "示例 / 模板",
		"newsletters_news":    "Newsletter / 资讯",
		"project_collections": "项目集合",
		"learning_other":      "其他学习资源",
	},
	"rag_knowledge": {
		"vector_search":        "向量检索",
		"document_qa":          "文档问答",
		"graph_rag":            "GraphRAG",
		"enterprise_knowledge": "企业知识库",
		"retrieval_infra":      "检索基础设施",
		"ai_search_engine":     "AI 搜索引擎",
		"document_parsing":     "文档解析",
		"rag_other":            "其他知识库工具",
	},
	"multimodal_tools": {
		"image_generation": "图像生成",
		"video_generation": "视频生成",
		"speech_audio":     "语音 / 音频",
		"ocr_vision":       "OCR / 视觉理解",
		"multimodal_chat":  "多模态聊天",
		"creative_design":  "创意设计",
		"three_d_spatial":  "3D / 空间内容",
		"multimodal_other": "其他多模态工具",
	},
	"models_infra": {
		"local_llm_runtime":       "本地 LLM 运行",
		"inference_serving":       "推理服务",
		"llm_gateway":             "LLM Gateway",
		"model_deploy_mlops":      "模型部署 / MLOps",
		"model_compression_accel": "模型压缩 / 加速",
		"edge_runtime":            "边缘运行时",
		"model_management":        "模型管理",
		"models_infra_other":      "其他模型基础设施",
	},
	"data_eval_training": {
		"datasets":               "数据集",
		"benchmark_eval":         "Benchmark / Eval",
		"fine_tuning":            "微调",
		"synthetic_data":         "合成数据",
		"training_frameworks":    "训练框架",
		"observability":          "可观测性",
		"data_labeling_cleaning": "数据标注 / 清洗",
		"data_training_other":    "其他数据训练工具",
	},
	"security_privacy": {
		"prompt_security":        "Prompt 安全",
		"privacy_local_first":    "隐私 / 本地优先",
		"redteam_eval":           "红队 / 安全评测",
		"compliance_guardrails":  "合规 / Guardrails",
		"vulnerability_analysis": "漏洞分析",
		"content_safety":         "内容安全",
		"security_other":         "其他安全隐私工具",
	},
	"other": {
		"other_uncategorized": "未分类",
	},
}

// ghDefaultSubcategoryByCategory 对应 DEFAULT_SUBCATEGORY_BY_CATEGORY
// （每类的 default 子类；PROJECT_TAXONOMY 中均为带 "default": True 的末位子类）。
var ghDefaultSubcategoryByCategory = map[string]string{
	"productivity_tools": "productivity_other",
	"coding_tools":       "coding_other",
	"agents_automation":  "agent_other",
	"ai_apps":            "ai_apps_other",
	"learning_resources": "learning_other",
	"rag_knowledge":      "rag_other",
	"multimodal_tools":   "multimodal_other",
	"models_infra":       "models_infra_other",
	"data_eval_training": "data_training_other",
	"security_privacy":   "security_other",
	"other":              "other_uncategorized",
}

// englishLabelBySlug 逐字搬运 ENGLISH_LABEL_BY_SLUG（全部类目与子类目的
// 英文名；分类学确定性数据，不从存储文本推断）。
var englishLabelBySlug = map[string]string{
	"productivity_tools": "AI Productivity Tools", "writing_docs": "Writing / Documents",
	"meetings_email": "Meetings / Email", "browser_search": "Browser / Search",
	"office_automation": "Office Automation", "notes_knowledge": "Notes / Knowledge Management",
	"personal_assistant": "Personal Assistant", "spreadsheet_analysis": "Spreadsheets / Data Analysis",
	"productivity_other": "Other Productivity Tools", "coding_tools": "AI Coding Tools",
	"code_generation": "Code Generation", "code_review": "Code Review",
	"ide_plugins": "IDE / Editor Plugins", "testing_ci": "Testing / CI Automation",
	"dev_agents": "Development Agents", "code_search_docs": "Code Search / Documentation",
	"low_code_scaffold": "Low-Code / Scaffolding", "coding_other": "Other Coding Tools",
	"agents_automation": "AI Agents / Automation", "agent_frameworks": "Agent Frameworks",
	"multi_agent": "Multi-Agent Collaboration", "workflow_automation": "Workflow Automation",
	"mcp_tool_use": "MCP / Tool Use", "browser_rpa": "Browser / RPA Automation",
	"research_agents": "Research Agents", "personal_automation": "Personal Automation",
	"agent_other": "Other Agent Tools", "ai_apps": "AI Products / Applications",
	"chat_clients": "Chat Clients", "ai_search_products": "AI Search Products",
	"vertical_saas": "Vertical SaaS", "desktop_mobile_apps": "Desktop / Mobile Apps",
	"marketing_sales": "Marketing / Sales", "education_apps": "Education Apps",
	"customer_ops": "Customer Service / Operations", "ai_apps_other": "Other AI Applications",
	"learning_resources": "AI Tutorials / Learning Resources", "awesome_lists": "Awesome Lists",
	"tutorials_courses": "Tutorials / Courses", "prompt_collections": "Prompt Collections",
	"papers_reading": "Papers / Reading", "examples_templates": "Examples / Templates",
	"newsletters_news": "Newsletters / News", "project_collections": "Project Collections",
	"learning_other": "Other Learning Resources", "rag_knowledge": "RAG / Knowledge Bases",
	"vector_search": "Vector Search", "document_qa": "Document Q&A", "graph_rag": "GraphRAG",
	"enterprise_knowledge": "Enterprise Knowledge Bases", "retrieval_infra": "Retrieval Infrastructure",
	"ai_search_engine": "AI Search Engines", "document_parsing": "Document Parsing",
	"rag_other": "Other Knowledge Tools", "multimodal_tools": "Multimodal Tools",
	"image_generation": "Image Generation", "video_generation": "Video Generation",
	"speech_audio": "Speech / Audio", "ocr_vision": "OCR / Vision Understanding",
	"multimodal_chat": "Multimodal Chat", "creative_design": "Creative Design",
	"three_d_spatial": "3D / Spatial Content", "multimodal_other": "Other Multimodal Tools",
	"models_infra": "Models / Inference / Deployment", "local_llm_runtime": "Local LLM Runtimes",
	"inference_serving": "Inference Serving", "llm_gateway": "LLM Gateways",
	"model_deploy_mlops": "Model Deployment / MLOps", "model_compression_accel": "Model Compression / Acceleration",
	"edge_runtime": "Edge Runtimes", "model_management": "Model Management",
	"models_infra_other": "Other Model Infrastructure", "data_eval_training": "Data / Evaluation / Training",
	"datasets": "Datasets", "benchmark_eval": "Benchmarks / Evaluation", "fine_tuning": "Fine-Tuning",
	"synthetic_data": "Synthetic Data", "training_frameworks": "Training Frameworks",
	"observability": "Observability", "data_labeling_cleaning": "Data Labeling / Cleaning",
	"data_training_other": "Other Data and Training Tools", "security_privacy": "Security / Privacy",
	"prompt_security": "Prompt Security", "privacy_local_first": "Privacy / Local-First",
	"redteam_eval": "Red Teaming / Security Evaluation", "compliance_guardrails": "Compliance / Guardrails",
	"vulnerability_analysis": "Vulnerability Analysis", "content_safety": "Content Safety",
	"security_other": "Other Security and Privacy Tools", "other": "Other",
	"other_uncategorized": "Uncategorized",
}

// ── normalize_project_row 移植 ─────────────────────────────────────────

// jsonStringList 复刻 _json_list：JSON 文本 → 去空白非空字符串列表；
// 解析失败/非数组/空值一律回空列表（非 nil，保证 JSON 序列化为 []）。
func jsonStringList(value any) []string {
	out := []string{}
	var items []any
	switch v := value.(type) {
	case nil:
		return out
	case string:
		if v == "" {
			return out // Python `if not value: return []`
		}
		dec := json.NewDecoder(strings.NewReader(v))
		dec.UseNumber()
		var parsed any
		if err := dec.Decode(&parsed); err != nil {
			return out
		}
		// 对齐 json.loads 的 "Extra data" 报错：首个值后必须只剩空白。
		if err := dec.Decode(&struct{}{}); err != io.EOF {
			return out
		}
		list, ok := parsed.([]any)
		if !ok {
			return out
		}
		items = list
	case []any: // Python isinstance(value, list) 分支（本查询列均为 text，不可达）
		items = v
	case []string:
		for _, s := range v {
			items = append(items, s)
		}
	default:
		return out
	}
	for _, item := range items {
		s := pythonishString(item)
		if trimmed := strings.TrimSpace(s); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

// pythonishString 模拟 Python str(item)：字符串原样；json.Number 保留 JSON
// 字面量（整数与小数均与 str() 一致）；bool→"True"/"False"；nil→"None"。
// 嵌套数组/对象的 Python repr 形态以 fmt 近似（tags/topics 实际为字符串数组）。
func pythonishString(value any) string {
	switch v := value.(type) {
	case nil:
		return "None"
	case string:
		return v
	case json.Number:
		return string(v)
	case bool:
		if v {
			return "True"
		}
		return "False"
	case float64:
		return strconv.FormatFloat(v, 'g', -1, 64)
	default:
		return fmt.Sprintf("%v", v)
	}
}

// intOrZero 复刻 _integer：int(value or 0)，解析失败回 0；
// float 向零截断对齐 Python int()。
func intOrZero(value any) int {
	switch v := value.(type) {
	case nil:
		return 0
	case int:
		return v
	case int32:
		return int(v)
	case int64:
		return int(v)
	case float64:
		return int(v)
	case bool: // Python int(True) == 1
		if v {
			return 1
		}
		return 0
	case string:
		// Python int() 容忍首尾空白与 +/- 号；解析失败 ValueError → 0。
		n, err := strconv.Atoi(strings.TrimSpace(v))
		if err != nil {
			return 0
		}
		return n
	default:
		return 0
	}
}

// floatOrZero 复刻 _number：float(value or 0.0)，解析失败回 0.0。
func floatOrZero(value any) float64 {
	switch v := value.(type) {
	case nil:
		return 0.0
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int32:
		return float64(v)
	case int64:
		return float64(v)
	case bool:
		if v {
			return 1.0
		}
		return 0.0
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if err != nil {
			return 0.0
		}
		return f
	default:
		return 0.0
	}
}

// boolValue 复刻 Python bool()：nil/空串/数值零为 False，其余 True。
func boolValue(value any) bool {
	switch v := value.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return v != ""
	case int:
		return v != 0
	case int32:
		return v != 0
	case int64:
		return v != 0
	case float64:
		return v != 0
	default:
		return true
	}
}

// isoTimestamp 复刻 _iso：None/"" → nil；datetime → UTC ISO8601（微秒为 0
// 省略小数段，否则 6 位，末尾 +00:00 换 Z）；其余类型按 str(value) 原样返回。
func isoTimestamp(value any) any {
	switch v := value.(type) {
	case nil:
		return nil
	case string:
		if v == "" {
			return nil
		}
		return v
	case time.Time:
		u := v.UTC()
		micro := u.Nanosecond() / 1000 // PG timestamptz 为微秒精度
		if micro == 0 {
			return u.Format("2006-01-02T15:04:05Z")
		}
		return fmt.Sprintf("%s.%06dZ", u.Format("2006-01-02T15:04:05"), micro)
	default:
		return fmt.Sprintf("%v", v)
	}
}

// stringOrEmpty 窄化 string；非 string（含 NULL）回 ""。
// 对应 Python `item.get(key) or fallback` 链中的真值读取——本查询相关列
// 均为 text，不存在非 string 真值形态。
func stringOrEmpty(value any) string {
	if s, ok := value.(string); ok {
		return s
	}
	return ""
}

// orString 复刻 Python `a or b or fallback`：返回首个非空字符串。
func orString(values ...any) string {
	for _, value := range values {
		if s := stringOrEmpty(value); s != "" {
			return s
		}
	}
	return ""
}

// normalizeProjectRow 全量移植 normalize_project_row（github 分支；
// website 分支在窄口径不可达）。输入键为 SELECT 列名，输出键同列名——
// topics/tags/tags_zh/tags_en/tags_origin 五个 *_json 列被替换为规范化键。
func normalizeProjectRow(row map[string]any) map[string]any {
	item := make(map[string]any, len(row)+1)
	for key, value := range row {
		item[key] = value
	}
	topics := jsonStringList(item["topics_json"])
	delete(item, "topics_json")
	tags := jsonStringList(item["tags_json"])
	delete(item, "tags_json")
	tagsZh := jsonStringList(item["tags_zh_json"])
	delete(item, "tags_zh_json")
	tagsEn := jsonStringList(item["tags_en_json"])
	delete(item, "tags_en_json")
	tagsOrigin := "system"
	if item["tags_origin"] == "user" {
		tagsOrigin = "user"
	}
	delete(item, "tags_origin")
	item["topics"] = topics
	item["tags"] = tags
	if tagsOrigin == "user" {
		item["tags_zh"] = []string{}
		item["tags_en"] = []string{}
	} else {
		// Python: tags_zh or tags（空列表回退 tags）
		if len(tagsZh) > 0 {
			item["tags_zh"] = tagsZh
		} else {
			item["tags_zh"] = tags
		}
		item["tags_en"] = tagsEn
	}
	item["tags_origin"] = tagsOrigin
	for _, key := range []string{"stars", "forks", "watchers", "open_issues", "daily_star_growth"} {
		item[key] = intOrZero(item[key])
	}
	if rank := intOrZero(item["rank_in_period"]); rank != 0 {
		item["rank_in_period"] = rank
	} else {
		item["rank_in_period"] = nil // Python: _integer(...) or None
	}
	for _, key := range []string{
		"raw_score", "score", "confidence", "hot_score",
		"scale_corrected_growth_score", "growth_acceleration_score",
		"absolute_growth_score", "maintenance_activity_score",
		"community_engagement_score",
	} {
		item[key] = floatOrZero(item[key])
	}
	item["daily_growth_available"] = intOrZero(item["daily_growth_available"]) != 0
	if s := stringOrEmpty(item["daily_growth_source"]); s != "" {
		item["daily_growth_source"] = s
	} else {
		item["daily_growth_source"] = "unavailable"
	}
	if item["availability_status"] == "not_found" {
		item["availability_status"] = "not_found"
	} else {
		item["availability_status"] = "active"
	}
	for _, key := range []string{"daily_growth_observed_at", "favorited_at", "recommended_at", "user_added_at"} {
		item[key] = isoTimestamp(item[key])
	}
	for _, key := range []string{"is_favorited", "is_recommended", "user_added"} {
		item[key] = boolValue(item[key])
	}

	// taxonomy 兜底（github 侧：CATEGORY_BY_SLUG / SUBCATEGORY_BY_CATEGORY_SLUG /
	// DEFAULT_SUBCATEGORY_BY_CATEGORY）。
	categorySlug := stringOrEmpty(item["category_slug"])
	if categorySlug == "" {
		categorySlug = "other"
	}
	subcategorySlug := stringOrEmpty(item["subcategory_slug"])
	if subcategorySlug == "" {
		subcategorySlug = ghDefaultSubcategoryByCategory[categorySlug]
	}
	item["category_slug"] = categorySlug
	item["subcategory_slug"] = subcategorySlug
	// 注意：回退链读的是覆盖前的原值，先算后写，顺序不可调换。
	categoryNameZh, ok := ghCategoryNameBySlug[categorySlug]
	if !ok {
		categoryNameZh = orString(item["category_name_zh"], item["category_name"], "其他")
	}
	subcategoryNameZh, ok := ghSubcategoryNameBySlug[categorySlug][subcategorySlug]
	if !ok {
		subcategoryNameZh = orString(item["subcategory_name_zh"], item["subcategory_name"], "未分类")
	}
	categoryNameEn := orString(item["category_name_en"])
	if categoryNameEn == "" {
		if label, hit := englishLabelBySlug[categorySlug]; hit {
			categoryNameEn = label
		} else {
			categoryNameEn = "Other"
		}
	}
	subcategoryNameEn := orString(item["subcategory_name_en"])
	if subcategoryNameEn == "" {
		if label, hit := englishLabelBySlug[subcategorySlug]; hit {
			subcategoryNameEn = label
		} else {
			subcategoryNameEn = "Uncategorized"
		}
	}
	item["category_name_zh"] = categoryNameZh
	item["category_name_en"] = categoryNameEn
	item["subcategory_name_zh"] = subcategoryNameZh
	item["subcategory_name_en"] = subcategoryNameEn
	// 通用别名在消费者显式选择语言前保持中文。
	item["category_name"] = categoryNameZh
	item["subcategory_name"] = subcategoryNameZh
	return item
}

// dollarPlaceholders 把 Python 风格的 %s 占位按文本出现序改写为 pgx 的
// $N。不变量：SQL 模板文本内除占位符外不含 '%'（ILIKE 模式串是绑定参数，
// 不在文本中），故朴素扫描安全。
func dollarPlaceholders(sql string) string {
	var out strings.Builder
	out.Grow(len(sql) + 8)
	n := 0
	for i := 0; i < len(sql); i++ {
		if sql[i] == '%' && i+1 < len(sql) && sql[i+1] == 's' {
			n++
			out.WriteByte('$')
			out.WriteString(strconv.Itoa(n))
			i++
			continue
		}
		out.WriteByte(sql[i])
	}
	return out.String()
}

// ProjectCollectionsRepository 适配 project_favorites 的收藏列表读路径
// （list_user_project_collection 窄口径）。timezone 对应
// settings.scheduler_timezone（_today() 的 ZoneInfo 锚），空串兜底
// "Asia/Shanghai"。
type ProjectCollectionsRepository struct {
	pool     *pgxpool.Pool
	timezone string
}

func NewProjectCollectionsRepository(pool *pgxpool.Pool, timezone string) ProjectCollectionsRepository {
	if timezone == "" {
		timezone = "Asia/Shanghai"
	}
	return ProjectCollectionsRepository{pool: pool, timezone: timezone}
}

// ListUserProjectCollection 复刻 list_projects 窄口径调用：同一
// REPEATABLE READ READ ONLY 事务内先 count 后 rows（对齐 _begin_read +
// _transaction 的顺序双查询语义）。
//
// 参数序与占位符文本序一致：[*有效指标日参数, user_id, *filter_params]，rows 查询尾部
// 追加 [page_size, offset]。UserID 必须为正（上游 _require_owner /
// MCP 工具层已校验；<=0 时 pf  JOIN 不命中，结果为空而非报错）。
func (r ProjectCollectionsRepository) ListUserProjectCollection(f mcpapp.ProjectCollectionFilters) (mcpapp.ProjectCollectionPage, error) {
	// 逐字对齐 list_projects 的钳制：
	// page = max(1, int(page or 1))；page_size = max(1, min(int(page_size or 24), 100))。
	page := f.Page
	if page < 1 {
		page = 1
	}
	pageSize := f.PageSize
	if pageSize == 0 {
		pageSize = 24
	}
	if pageSize < 1 {
		pageSize = 1
	} else if pageSize > 100 {
		pageSize = 100
	}

	// _today()：datetime.now(ZoneInfo(zone)).date().isoformat()；
	// 时区名非法时报错返回，对齐 Python ZoneInfoNotFoundError 查询期抛出。
	zone, err := time.LoadLocation(r.timezone)
	if err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 调度时区 %q 加载失败: %w", r.timezone, err)
	}
	dateParams := effectiveMetricDateParams(time.Now().In(zone))
	countSQL, rowsSQL, params, rowsParams := projectCollectionQueries(f, dateParams, page, pageSize)

	ctx := context.Background() // 对齐 asyncio.to_thread 语义：跑完不随客户端断连取消。
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var total int64
	if err := tx.QueryRow(ctx, countSQL, params...).Scan(&total); err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表计数失败: %w", err)
	}

	rows, err := tx.Query(ctx, rowsSQL, rowsParams...)
	if err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表查询失败: %w", err)
	}
	defer rows.Close()

	fields := rows.FieldDescriptions()
	items := []map[string]any{}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表行解码失败: %w", err)
		}
		row := make(map[string]any, len(fields))
		for i := range fields {
			row[string(fields[i].Name)] = values[i]
		}
		items = append(items, normalizeProjectRow(row))
	}
	if err := rows.Err(); err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表行读取失败: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return mcpapp.ProjectCollectionPage{}, fmt.Errorf("postgres: 收藏列表事务提交失败: %w", err)
	}
	return mcpapp.ProjectCollectionPage{Items: items, Total: int(total)}, nil
}

// ListFavoriteRepoIDs 返回用户最近收藏的 GitHub repo_id（收藏语义通道的检索
// 范围）；只读，limit<=0 时返回空。
func (r ProjectCollectionsRepository) ListFavoriteRepoIDs(userID, limit int) ([]string, error) {
	if userID <= 0 || limit <= 0 {
		return []string{}, nil
	}
	ctx := context.Background()
	rows, err := r.pool.Query(ctx, listFavoriteRepoIDsSQL, userID, limit)
	if err != nil {
		return nil, fmt.Errorf("postgres: 收藏 repo_id 查询失败: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("postgres: 收藏 repo_id 读取失败: %w", err)
	}
	return ids, nil
}

const listFavoriteRepoIDsSQL = "SELECT project_id FROM project_favorites" +
	" WHERE user_id = $1 AND project_source = 'github'" +
	" ORDER BY created_at DESC, id DESC LIMIT $2"

// projectCollectionQueries 组装收藏列表的 count/rows SQL 与参数（纯函数）。
// 参数序与占位符文本序一致：[*有效指标日参数, user_id, *filter_params]，rows
// 查询尾部追加 [page_size, offset]。
func projectCollectionQueries(f mcpapp.ProjectCollectionFilters, dateParams []any, page, pageSize int) (countSQL, rowsSQL string, params, rowsParams []any) {
	// gh_filters 组装段逐字移植（窄口径下 web_filters、candidates、
	// scope today/recommended、strong match 分支均不触发）。
	filters := []string{"COALESCE(c.stars, 0) >= %s"}
	filterParams := []any{projectCollectionMinStars}
	filters = append(filters, "ge.status = 'succeeded'") // enriched_only=True
	if f.Category != "" {
		filters = append(filters, "ge.category_slug = %s")
		filterParams = append(filterParams, f.Category)
	}
	if f.Subcategory != "" {
		// `category and subcategory == DEFAULT_SUBCATEGORY_BY_CATEGORY.get(category or "")`
		if defaultSub, ok := ghDefaultSubcategoryByCategory[f.Category]; f.Category != "" && ok && f.Subcategory == defaultSub {
			filters = append(filters, "(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
		} else {
			filters = append(filters, "ge.subcategory_slug = %s")
		}
		filterParams = append(filterParams, f.Subcategory)
	}
	if f.Language != "" {
		filters = append(filters, "LOWER(COALESCE(c.language, '')) = LOWER(%s)")
		filterParams = append(filterParams, f.Language)
	}
	if f.Q != "" {
		terms := projectSearchTerms(f.Q)
		termFilters := []string{}
		termParams := []any{}
		if len(terms) == 0 {
			termFilters = append(termFilters, "FALSE")
		}
		for _, term := range terms {
			like := "%" + escapeLikeLiteral.Replace(term) + "%"
			termFilters = append(termFilters, ghTermMatchFilter)
			for range len(ghTermMatchFieldsWithI18nTags) {
				termParams = append(termParams, like)
			}
		}
		if len(f.SemanticRepoIDs) > 0 {
			// 语义通道：关键词全中，或在语义命中清单内；其余过滤照常约束。
			filters = append(filters, "(("+strings.Join(termFilters, " AND ")+") OR c.repo_id = ANY(%s))")
			filterParams = append(filterParams, termParams...)
			filterParams = append(filterParams, f.SemanticRepoIDs)
		} else {
			filters = append(filters, termFilters...)
			filterParams = append(filterParams, termParams...)
		}
	}
	// clean_tag = (tag or "").strip()；模式串不做 LIKE 转义（Python 原文如此）。
	if cleanTag := strings.TrimSpace(f.Tag); cleanTag != "" {
		filters = append(filters, "COALESCE(ge.tags_json::text, '') ILIKE %s")
		filterParams = append(filterParams, `%"`+cleanTag+`"%`)
	}
	filters = append(filters, "pf.id IS NOT NULL") // favorites_only=True

	// _build_gh_branch：SELECT 列序 = 58 静态列 + 收藏列 + 推荐尾列；
	// 参数序 = [*有效指标日参数, user_id, *filter_params]。
	selectColumns := make([]string, 0, len(ghSelectColumns)+1+len(ghSelectTailColumns))
	selectColumns = append(selectColumns, ghSelectColumns...)
	selectColumns = append(selectColumns, ghFavoriteColumns)
	selectColumns = append(selectColumns, ghSelectTailColumns...)
	selectSQL := "SELECT " + strings.Join(selectColumns, ",") +
		ghSelectFrom + " " + ghMetricsJoin + " " + ghFavoritesJoin +
		" WHERE " + strings.Join(filters, " AND ")

	// _build_union_queries（strong_threshold=0 形态）。
	countSQL = dollarPlaceholders("WITH project_rows AS (" + selectSQL + ") SELECT COUNT(*) AS cnt FROM project_rows")
	rowsSQL = dollarPlaceholders("WITH project_rows AS (" + selectSQL + ") SELECT * FROM project_rows ORDER BY " +
		collectionOrderBy(f.Sort) + " LIMIT %s OFFSET %s")

	params = make([]any, 0, len(dateParams)+1+len(filterParams)+2)
	params = append(params, dateParams...)
	params = append(params, f.UserID)
	params = append(params, filterParams...)
	rowsParams = append(append([]any{}, params...), pageSize, (page-1)*pageSize)
	return countSQL, rowsSQL, params, rowsParams
}
