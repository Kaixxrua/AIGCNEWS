package mcpapp

// project_search.go 移植 search_github_projects 工具（PR 2.7，generic
// 模式的 handler 薄壳 + pydantic 校验镜像）：
//   - backend/app/services/mcp/contracts.py:122-157
//     SearchGitHubProjectsInput（pydantic v2 strict +
//     str_strip_whitespace + extra="forbid"）
//   - backend/app/services/mcp/contracts.py:32-33, 40-71
//     ProjectDiscoverySort / ProjectResponseLang / RepositoryLanguage
//   - backend/app/services/mcp/inbound/tools.py:266-321
//     _search_project_library 的 generic 分支（强制 category=""、
//     subcategory=""、scope="all"、client_intent=None 的防御语义）
//   - backend/app/services/mcp/inbound/tools.py:485-498
//     _validated_tool_args（ValidationError → "; ".join 折叠）
//
// 字节级行为准绳（backend/tests/parity/corpus/tools.jsonl 第 17 行）：
//   - 校验错误文案逐字复刻 pydantic v2（字段定义序 q → language → sort →
//     lang → page → limit，extras 殿后，多错 "; " 连接）；
//   - 引擎返回的 jsonx.Object 经 finalizeProjectSearchResult 做「items
//     原位覆盖/absent 追加 + lang/attribution 殿后」后即响应体；
//   - 引擎 error 原样透传普通 error（不包 ToolInputError）：dispatch 折叠
//     为 "Tool execution failed."，对齐 Python _call_tool 的 except
//     Exception 分支。
//
// 已记录的近似（语料不覆盖，与 favorites.go/adoptions.go 同口径）：
//   - extras 报错按键名排序（Python 按输入序，Go map 无法保留）；
//   - strictInt 接受 float64 整值（Go 请求解码无法区分 3 与 3.0，
//     pydantic strict 拒绝后者；documents.go:433 起的同包既有口径）；
//   - strip 用 strings.TrimSpace：venv 探针实测 pydantic-core 的
//     str_strip_whitespace 仅认 Unicode White_Space（\x1c-\x1f 不剥离，
//     q="\x1c" 合法通过），与 Go unicode.IsSpace 口径一致；spec §6.7
//     关于「Python str.strip() 多 \x1c-\x1f」的记述不适用于 pydantic
//     校验层（那是 Python 原生 str 方法语义，pydantic-core 是 Rust 实现）。
//
// 注册面：本工具不是身份感知工具——注册进 dispatch.Handlers 普通表
// （registry["search_github_projects"]），不走 RegisterIdentityTool
// （Python _TOOL_HANDLERS 普通表，匿名可调用）。

import (
	"sort"
	"strings"
	"unicode/utf8"
)

// ProjectSearchService 装配 search_github_projects 的校验、引擎调用与
// 响应后处理（薄壳；投影链唯一实现见 project_search_contract.go）。
type ProjectSearchService struct {
	engine ProjectSearchEngine
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置（attribution._base_url：
	// 绝不从请求派生 origin），接线时已 TrimRight("/")；回放传 ""（品牌
	// 兜底 https://aigcnews.cn，与录制侧未配置一致）。
	publicBaseURL string
}

func NewProjectSearchService(engine ProjectSearchEngine, publicBaseURL string) *ProjectSearchService {
	return &ProjectSearchService{engine: engine, publicBaseURL: publicBaseURL}
}

// Get 是 search_github_projects 工具处理器（匹配 dispatch.go 的
// ToolHandler；匿名可调用，无身份短路）。
func (s *ProjectSearchService) Get(arguments map[string]any) (any, error) {
	input, err := validateSearchGitHubProjectsArgs(arguments)
	if err != nil {
		return nil, err
	}
	// tools.py:275 的防御复检（`args.get("lang") if in {"zh","en"} else
	// "zh"`）：校验产物恒合法，此分支不可达，照抄钉住语义。
	lang := input.lang
	if lang != "zh" && lang != "en" {
		lang = "zh"
	}
	// generic 强制段（tools.py:271-276）：Category/Subcategory/Scope/
	// ClientIntent 无论入参如何都钉死（extra="forbid" 使这些键本就
	// 无法通过校验，此处是防御性复刻）。Sort 为 "" 即 Python None
	// （未传与显式 null 同义）。
	result, err := s.engine.SearchProjects(ProjectSearchInput{
		Query:        input.q,
		Mode:         "generic",
		Language:     input.language,
		Category:     "",
		Subcategory:  "",
		Scope:        "all",
		Sort:         input.sort,
		Page:         input.page,
		Limit:        input.limit,
		ClientIntent: nil,
	})
	if err != nil {
		return nil, err
	}
	return finalizeProjectSearchResult(result, lang, s.publicBaseURL), nil
}

// ── 入参校验（pydantic v2 文案逐字复刻） ────────────────────────────────

// searchGitHubProjectsInput 是 SearchGitHubProjectsInput 的验证结果
// （model_dump 后恒为完整形态：language=""、sort=None→""、lang="zh"、
// page=1、limit=10 为默认值填充）。
type searchGitHubProjectsInput struct {
	q        string
	language string
	sort     string // "" = Python None（未传与显式 null 同义）
	lang     string
	page     int
	limit    int
}

// projectDiscoverySortChoices 逐字复刻 ProjectDiscoverySort Literal
// （contracts.py:32；文案序即 Literal 声明序）。
var projectDiscoverySortChoices = []string{"relevance", "hot", "stars", "updated", "recent", "name"}

// validateSearchGitHubProjectsArgs 复刻 SearchGitHubProjectsInput 的
// pydantic v2 校验。错误顺序：字段定义序（q → language → sort → lang →
// page → limit），extras 殿后（键名排序）。文案已经项目 venv 的
// pydantic v2 实测逐字核对（含 language AfterValidator 长文案与 Literal
// 折叠消息）。
func validateSearchGitHubProjectsArgs(args map[string]any) (searchGitHubProjectsInput, error) {
	input := searchGitHubProjectsInput{lang: "zh", page: 1, limit: 10}
	var failures []string

	// q: StrictStr, min_length=1, max_length=120，必填；strip 后量长
	// （长度按 rune 计）。非字符串（含 null）→ "Input should be a valid
	// string"；缺键 → "Field required"。
	rawQ, present := args["q"]
	switch {
	case !present:
		failures = append(failures, "q: Field required")
	default:
		q, ok := rawQ.(string)
		if !ok {
			failures = append(failures, "q: Input should be a valid string")
			break
		}
		q = strings.TrimSpace(q)
		switch length := utf8.RuneCountInString(q); {
		case length < 1:
			failures = append(failures, "q: String should have at least 1 character")
		case length > 120:
			failures = append(failures, "q: String should have at most 120 characters")
		default:
			input.q = q
		}
	}

	// language = RepositoryLanguage：StrictStr →（model config strip）→
	// max_length=64 → AfterValidator(_validate_repo_language)；前置校验
	// 失败不再触发后续（pydantic 短路语义）。
	if raw, present := args["language"]; present {
		value, ok := raw.(string)
		switch {
		case !ok:
			failures = append(failures, "language: Input should be a valid string")
		default:
			value = strings.TrimSpace(value)
			switch {
			case utf8.RuneCountInString(value) > 64:
				failures = append(failures, "language: String should have at most 64 characters")
			case !validateRepoLanguage(value):
				failures = append(failures, "language: Value error, "+repositoryLanguageMessage)
			default:
				input.language = value
			}
		}
	}

	// sort: Literal["relevance","hot","stars","updated","recent","name"] |
	// None。null/缺省 → ""（Python None，合法）；字符串六枚举之一原样；
	// 其余（含非字符串）→ 同一条 Literal 消息（pydantic v2 把 union 折叠
	// 成单条）。Literal 不经 strip。
	if raw, present := args["sort"]; present && raw != nil {
		value, ok := raw.(string)
		if !ok || !contains(projectDiscoverySortChoices, value) {
			failures = append(failures, "sort: Input should be 'relevance', 'hot', 'stars', 'updated', 'recent' or 'name'")
		} else {
			input.sort = value
		}
	}

	// lang: Literal["zh","en"]，默认 "zh"；null/非字符串/非枚举 → 同一条
	// Literal 文案。Literal 不经 strip。
	if raw, present := args["lang"]; present {
		value, ok := raw.(string)
		if !ok || (value != "zh" && value != "en") {
			failures = append(failures, "lang: Input should be 'zh' or 'en'")
		} else {
			input.lang = value
		}
	}

	// page: StrictInt 默认 1, ge=1（复用同包 strictInt 既有口径）。
	if raw, present := args["page"]; present {
		if value, ok := strictInt(raw); !ok {
			failures = append(failures, "page: Input should be a valid integer")
		} else if value < 1 {
			failures = append(failures, "page: Input should be greater than or equal to 1")
		} else {
			input.page = value
		}
	}

	// limit: StrictInt 默认 10, ge=1, le=20。
	if raw, present := args["limit"]; present {
		if value, ok := strictInt(raw); !ok {
			failures = append(failures, "limit: Input should be a valid integer")
		} else if value < 1 {
			failures = append(failures, "limit: Input should be greater than or equal to 1")
		} else if value > 20 {
			failures = append(failures, "limit: Input should be less than or equal to 20")
		} else {
			input.limit = value
		}
	}

	// extra="forbid"：未知键逐一报错（Python 按输入序；Go 按键名排序，
	// 与 favorites.go 同一已记录近似）。
	known := map[string]bool{
		"q": true, "language": true, "sort": true,
		"lang": true, "page": true, "limit": true,
	}
	var extras []string
	for key := range args {
		if !known[key] {
			extras = append(extras, key)
		}
	}
	sort.Strings(extras)
	for _, key := range extras {
		failures = append(failures, key+": Extra inputs are not permitted")
	}

	if len(failures) > 0 {
		return searchGitHubProjectsInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}
