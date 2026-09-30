package mcpapp

// favorites.go 移植 search_my_project_favorites 工具：
//   - backend/app/services/mcp/inbound/application.py:204-212 匿名短路
//     （未认证在 pydantic 校验之前直接报 Authentication is required）
//   - backend/app/services/mcp/contracts.py:283-308
//     SearchMyProjectFavoritesInput（pydantic v2 strict +
//     str_strip_whitespace + extra="forbid"）
//   - backend/app/services/mcp/contracts.py:52-64 _validate_repo_language
//   - backend/app/services/mcp/inbound/tools.py:337-418
//     _tool_search_my_project_favorites（scope 检查、marker 解签、
//     投影链与响应键序）
//
// 字节级行为准绳（backend/tests/parity/corpus/tools.jsonl）：
//   - 执行序：匿名 → pydantic 参数校验 → scope 检查 → marker 解码 →
//     仓储查询 → 投影 → marker 出参；
//   - 校验文案逐字复刻 pydantic v2（字段定义序 q → category →
//     subcategory → language → tag → lang → sort → limit → marker，
//     extras 按键名排序殿后，多错 "; " 连接）；
//   - marker 出参是 {"offset":N,"limit":M} 紧凑 JSON（offset 键在前）
//     经 base64 urlsafe 去 padding；
//   - 响应键序：items, total, q, tag, lang, sort, marker, attribution。
//
// 已记录的近似：
//   - Python base64.urlsafe_b64decode 在 validate=False 下会丢弃字母表
//     外字符再解码，Go base64.URLEncoding 严格拒绝；marker 是本工具自签
//     的不透明值，异常形态统一落同一错误文案；
//   - Python str.casefold() 是全 Unicode 折叠（如 ß→ss），Go 侧用
//     strings.ToLower；禁用集合仅含 ASCII/中文成员，判定结果一致；
//   - str_strip_whitespace 用 strings.TrimSpace：Python 空白表多
//     \x1c-\x1f（与 documents.go 同一近似口径）。

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
)

// ProjectCollectionFilters 是用户收藏检索的过滤面（对齐 Python
// list_user_project_collection 的关键字参数；source="github"、scope="all"、
// min_stars=PUBLIC_PROJECT_MIN_STARS、enriched_only=True 由适配器钉死）。
type ProjectCollectionFilters struct {
	UserID      int
	Category    string
	Subcategory string
	Q           string
	Language    string
	Tag         string
	Page        int
	PageSize    int
	Sort        string
	// SemanticRepoIDs 是语义通道在该用户收藏内命中的 repo_id；非空时 Q 的
	// 过滤放宽为「关键词全中 或 在此清单内」，排序与其余过滤不变。
	SemanticRepoIDs []string
}

// ProjectCollectionPage 是收藏检索的一页结果。
type ProjectCollectionPage struct {
	Items []map[string]any // 已 normalize 的行（tags 为 list、无 *_json 键）
	Total int
}

// ProjectCollectionReader 是收藏检索的存储边界（生产=Postgres，回放=
// fixture stub）。无 ctx 形参：Python 语义是 asyncio.to_thread 跑到完。
type ProjectCollectionReader interface {
	ListUserProjectCollection(filters ProjectCollectionFilters) (ProjectCollectionPage, error)
}

// FavoritesSemanticSearcher 是收藏检索的可选语义通道（projectsearch.
// FavoritesSemantic）：只在该用户的 GitHub 收藏内做向量检索，返回命中的
// repo_id。任何错误都回落纯关键词过滤。
type FavoritesSemanticSearcher interface {
	SearchFavoriteRepoIDs(userID int, query string) ([]string, error)
}

// FavoritesService 装配 search_my_project_favorites 的校验、查询与投影。
type FavoritesService struct {
	reader ProjectCollectionReader
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置（attribution._base_url：
	// 绝不从请求派生 origin），接线时已 TrimRight("/")。
	publicBaseURL string
	semantic      FavoritesSemanticSearcher
}

func NewFavoritesService(reader ProjectCollectionReader, publicBaseURL string) *FavoritesService {
	return &FavoritesService{reader: reader, publicBaseURL: publicBaseURL}
}

// WithSemantic 挂上语义通道；nil 保持纯关键词行为。
func (s *FavoritesService) WithSemantic(semantic FavoritesSemanticSearcher) *FavoritesService {
	s.semantic = semantic
	return s
}

// semanticRepoIDs 跑语义通道；关闭、空查询或失败时返回 nil（纯关键词）。
func (s *FavoritesService) semanticRepoIDs(userID int, q string) []string {
	if s.semantic == nil || strings.TrimSpace(q) == "" {
		return nil
	}
	ids, err := s.semantic.SearchFavoriteRepoIDs(userID, q)
	if err != nil {
		slog.Warn("search_my_project_favorites semantic lane failed; lexical only", "err", err)
		return nil
	}
	return ids
}

// Get 是 search_my_project_favorites 工具处理器（匹配 dispatch.go 的
// IdentityToolHandler；匿名 identity 为零值 UserID=0）。
func (s *FavoritesService) Get(identity authn.Identity, arguments map[string]any) (any, error) {
	// 匿名短路在参数校验之前（application.py:204-212）：匿名 + 非法参数
	// 也报认证错误。
	if identity.UserID <= 0 {
		return nil, ToolInputError{Message: "Authentication is required for this tool."}
	}
	input, err := validateSearchMyProjectFavoritesArgs(arguments)
	if err != nil {
		return nil, err
	}
	// scope 检查在 pydantic 校验之后（tools.py:345-346 的 handler 内分支；
	// Python 的 _validated_tool_args 先于 handler 执行）。
	if !identity.HasScope("projects:favorites:read") {
		return nil, ToolInputError{Message: "This token requires the projects:favorites:read scope."}
	}

	offset := 0
	if input.marker != "" {
		offset, err = decodeFavoritesMarker(input.marker, input.limit)
		if err != nil {
			return nil, err
		}
	}
	page := offset/input.limit + 1

	result, err := s.reader.ListUserProjectCollection(ProjectCollectionFilters{
		UserID:      identity.UserID,
		Category:    input.category,
		Subcategory: input.subcategory,
		Q:           input.q,
		Language:    input.language,
		Tag:         input.tag,
		Page:        page,
		PageSize:    input.limit,
		Sort:        input.sort,

		SemanticRepoIDs: s.semanticRepoIDs(identity.UserID, input.q),
	})
	if err != nil {
		return nil, err
	}

	base := s.attributionBase()
	items := make([]any, 0, len(result.Items))
	for _, row := range result.Items {
		items = append(items, tagProjectDataSource(
			enrichProjectDetailURL(localizeProjectItem(publicProjectItem(row), input.lang), base),
		))
	}

	// marker 出参：nextOffset < total 时签发下一页（键序 offset 先，
	// 手工紧凑 JSON 对齐 json.dumps(separators=(",", ":"))）。
	nextOffset := offset + len(items)
	var marker any
	if nextOffset < result.Total {
		markerJSON := fmt.Sprintf(`{"offset":%d,"limit":%d}`, nextOffset, input.limit)
		marker = base64.RawURLEncoding.EncodeToString([]byte(markerJSON))
	}

	return jsonx.Object{
		{Key: "items", Value: items},
		{Key: "total", Value: result.Total},
		{Key: "q", Value: input.q},
		{Key: "tag", Value: input.tag},
		{Key: "lang", Value: input.lang},
		{Key: "sort", Value: input.sort},
		{Key: "marker", Value: marker},
		{Key: "attribution", Value: "Data provided by AIGC Radar · " + base},
	}, nil
}

// attributionBase 复刻 attribution._base_url：配置为空回退品牌站点。
func (s *FavoritesService) attributionBase() string {
	if s.publicBaseURL != "" {
		return s.publicBaseURL
	}
	return "https://aigcnews.cn"
}

// decodeFavoritesMarker 复刻 tools.py:357-373 的 marker 解签：
// 补 padding 后 base64 urlsafe 解码 → UTF-8 JSON 对象 → offset/limit 经
// Python int() 强转 → 语义校验（offset>=0、limit 一致、offset 按 limit
// 对齐）。
func decodeFavoritesMarker(marker string, limit int) (int, error) {
	opaque := ToolInputError{Message: "marker must be the opaque value returned by this tool."}
	padded := marker + strings.Repeat("=", (4-len(marker)%4)%4)
	raw, err := base64.URLEncoding.DecodeString(padded)
	if err != nil {
		return 0, opaque
	}
	// Python 先 .decode("utf-8") 再 json.loads；非法 UTF-8 落同一错误。
	if !utf8.Valid(raw) {
		return 0, opaque
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var data any
	if err := decoder.Decode(&data); err != nil {
		return 0, opaque
	}
	// Python json.loads 对尾随垃圾报错；Go Decode 只读一个值，显式拒绝。
	if decoder.More() {
		return 0, opaque
	}
	object, ok := data.(map[string]any)
	if !ok {
		// 非对象 JSON：Python 下标访问抛 TypeError，落同一文案。
		return 0, opaque
	}
	offset, ok := pythonIntStrict(object["offset"])
	if !ok {
		return 0, opaque
	}
	markerLimit, ok := pythonIntStrict(object["limit"])
	if !ok {
		return 0, opaque
	}
	if offset < 0 || markerLimit != limit || offset%limit != 0 {
		return 0, ToolInputError{Message: "marker is invalid or was issued for a different limit."}
	}
	return offset, nil
}

// ── 入参校验（pydantic v2 文案逐字复刻） ────────────────────────────────

// searchMyProjectFavoritesInput 是 SearchMyProjectFavoritesInput 的验证结果
// （全部字段有默认值，缺失即默认；model_dump 后恒为完整形态）。
type searchMyProjectFavoritesInput struct {
	q           string
	category    string
	subcategory string
	language    string
	tag         string
	lang        string
	sort        string
	limit       int
	marker      string
}

// repositoryLanguageMessage 逐字复刻 _validate_repo_language 的 ValueError
// 文案；pydantic v2 把 AfterValidator 的 ValueError 包成
// "Value error, <msg>"（已对项目 venv 的 pydantic 实测确认），完整错误即
// "language: Value error, " + 本常量。
const repositoryLanguageMessage = "language must be a GitHub repository programming language filter " +
	"(e.g. Python, C++, JavaScript). Do not pass query/content-language " +
	"values such as zh, en, 中文, or 英文; use intent.language for " +
	"zh/en/mixed/und query language."

// forbiddenRepoLanguages 复刻 contracts._FORBIDDEN_REPO_LANGUAGE_VALUES。
var forbiddenRepoLanguages = map[string]bool{
	"zh": true, "en": true, "mixed": true, "und": true,
	"中文": true, "英文": true, "chinese": true, "english": true,
}

// validateRepoLanguage 复刻 _validate_repo_language：strip+casefold 后命中
// 禁用集合，或 "-" 前段是 zh/en（zh-CN、en-US 等 locale 形态），即拒绝。
func validateRepoLanguage(value string) bool {
	normalized := strings.ToLower(strings.TrimSpace(value))
	if forbiddenRepoLanguages[normalized] {
		return false
	}
	base := normalized
	if i := strings.IndexByte(base, '-'); i >= 0 {
		base = base[:i]
	}
	return base != "zh" && base != "en"
}

// validateSearchMyProjectFavoritesArgs 复刻 SearchMyProjectFavoritesInput
// 的 pydantic v2 校验。错误顺序：字段定义序（q → category → subcategory →
// language → tag → lang → sort → limit → marker），extras 殿后（键名排序）。
func validateSearchMyProjectFavoritesArgs(args map[string]any) (searchMyProjectFavoritesInput, error) {
	input := searchMyProjectFavoritesInput{lang: "zh", sort: "recent", limit: 10}
	var failures []string

	// StrictStr(default="", max_length=N) + str_strip_whitespace：
	// 非字符串（含 null）→ "Input should be a valid string"。
	input.q = favoritesStrictString(args, "q", 120, &failures)
	input.category = favoritesStrictString(args, "category", 64, &failures)
	input.subcategory = favoritesStrictString(args, "subcategory", 64, &failures)

	// language = RepositoryLanguage：StrictStr + max_length=64 +
	// AfterValidator(_validate_repo_language)（前置校验失败不再触发）。
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

	input.tag = favoritesStrictString(args, "tag", 64, &failures)

	// lang: Literal["zh","en"]，默认 "zh"；Literal 不经 strip，非枚举值
	// （含非字符串/null）报 Literal 文案。
	if raw, present := args["lang"]; present {
		value, ok := raw.(string)
		if !ok || (value != "zh" && value != "en") {
			failures = append(failures, "lang: Input should be 'zh' or 'en'")
		} else {
			input.lang = value
		}
	}

	// sort: Literal["hot","stars","updated","recent","name"]，默认 "recent"。
	if raw, present := args["sort"]; present {
		value, ok := raw.(string)
		if !ok || !contains(favoritesSortChoices, value) {
			failures = append(failures, "sort: Input should be 'hot', 'stars', 'updated', 'recent' or 'name'")
		} else {
			input.sort = value
		}
	}

	// limit: StrictInt 默认 10，ge=1，le=20（复用同包 strictInt）。
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

	input.marker = favoritesStrictString(args, "marker", 128, &failures)

	// extra="forbid"：未知键逐一报错（Python 按输入序；Go 按键名排序，
	// 与 documents.go 同一近似口径）。
	known := map[string]bool{
		"q": true, "category": true, "subcategory": true, "language": true,
		"tag": true, "lang": true, "sort": true, "limit": true, "marker": true,
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
		return searchMyProjectFavoritesInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}

var favoritesSortChoices = []string{"hot", "stars", "updated", "recent", "name"}

// favoritesStrictString 复刻 StrictStr(default="", max_length=maxLen) +
// str_strip_whitespace：缺省 ""；非字符串（含 null）与超长各记一条失败。
func favoritesStrictString(args map[string]any, key string, maxLen int, failures *[]string) string {
	raw, present := args[key]
	if !present {
		return ""
	}
	value, ok := raw.(string)
	if !ok {
		*failures = append(*failures, key+": Input should be a valid string")
		return ""
	}
	value = strings.TrimSpace(value)
	if utf8.RuneCountInString(value) > maxLen {
		*failures = append(*failures, fmt.Sprintf("%s: String should have at most %d characters", key, maxLen))
		return ""
	}
	return value
}
