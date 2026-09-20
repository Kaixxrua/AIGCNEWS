package mcpapp

// resources.go 移植 resources/read 的全部资源路由
// （backend/app/services/mcp/inbound/application.py::_read_resource 族）。
//
// 字节级行为准绳（backend/tests/parity/corpus/resources.jsonl）：
//   - URI 解析逐字复刻 _parse_resource_uri：scheme 钉死 aigc-news，
//     netloc+path 均 unquote，query 末值生效；
//   - dashboard/summary 与 report/latest 的入参走 _clean_string/_clean_choice
//     口径（strip + 中文报错文案），而非工具的 pydantic 文案；
//   - dashboard/top、projects/library、papers/{id} 经 _validated_tool_args
//     全量 pydantic 校验，McpToolInputError 翻译为 McpResourceInputError
//     （Go 侧 ToolInputError → ResourceInputError，dispatch 映射 -32602）；
//   - 看板语义移植 dashboard/policy.py + query_service.py：未定稿快照可读、
//     radar 按 doc_weight 加权 + round() 银行家舍入（Go
//     math.RoundToEven）、github 同周期 fallback 链、HN 日榜昨日去重并
//     按 raw_score/score 降序移到榜尾；
//   - report/latest 的内容选择复刻 select_briefing_content（按 locale 前缀
//     分支，首个 strip 后非空的候选），页脚逐字复刻
//     briefing_attribution_footer。
//
// 已记录的近似：
//   - stats.source_counts 键序：Python 依赖 PG GROUP BY 返回序（生产不稳定），
//     Go 固定为六源注册序 + 额外源按名排序；回放 fixture 序与之一致。
//   - report/latest 的默认日期锚是 _date.today()（进程本地时区，与看板的
//     CST 钟不同源）；Go 用独立 today 缝复刻这一双钟结构。

import (
	"errors"
	"math"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/jsonx"
)

const maxResourceTextChars = 100_000

type ResourceInputError struct{ Message string }

func (e ResourceInputError) Error() string { return e.Message }

type ResourceReader interface{ ReadResource(uri string) (any, error) }

type DocumentStatisticsReader interface {
	GetSourceCounts() (map[string]int, error)
	GetTodayDocumentCount() (int, error)
}

type BriefingRecord struct{ ContentZH, ContentEN, Content string }
type BriefingReader interface {
	GetBriefing(key string) (*BriefingRecord, error)
}

type ResourceService struct {
	rank           RankSnapshotReader
	stats          DocumentStatisticsReader
	briefings      BriefingReader
	categories     *ProjectCategoriesService
	papers         *PaperDetailService
	top            *GetTopItemsService
	documents      DocumentsService
	now            func() time.Time
	today          func() string
	projectLibrary func(map[string]any) (any, error)
}

func NewResourceService(rank RankSnapshotReader, stats DocumentStatisticsReader, briefings BriefingReader, categories *ProjectCategoriesService, papers *PaperDetailService, publicBaseURL string) *ResourceService {
	docs := DocumentsService{publicBaseURL: publicBaseURL}
	return &ResourceService{
		rank:       rank,
		stats:      stats,
		briefings:  briefings,
		categories: categories,
		papers:     papers,
		documents:  docs,
		top:        NewGetTopItemsService(rank, publicBaseURL),
		now:        func() time.Time { return time.Now().UTC().Add(8 * time.Hour) },
		today:      func() string { return time.Now().Format("2006-01-02") },
	}
}

// SetNow 注入看板时钟（policy.datetime 的唯一入口；回放冻结在
// 2026-08-10T12:00+08:00）。top 服务共用同一钟。
func (s *ResourceService) SetNow(now func() time.Time) {
	s.now = now
	s.top.SetNow(now)
}

// SetToday 注入 report/latest 的日期锚（application._date，进程本地口径；
// 与看板 CST 钟刻意分离，镜像 recorder 的两个独立 patch 点）。
func (s *ResourceService) SetToday(today func() string) { s.today = today }

func (s *ResourceService) SetProjectLibrary(fn func(map[string]any) (any, error)) {
	s.projectLibrary = fn
}

func (s *ResourceService) ReadResource(uri string) (any, error) {
	path, query, err := parseResourceURI(uri)
	if err != nil {
		return nil, err
	}
	result, err := s.routeResource(path, query, uri)
	if err != nil {
		// _read_resource 的 except McpToolInputError → McpResourceInputError：
		// 工具校验文案原样落入 -32602。
		var inputErr ToolInputError
		if errors.As(err, &inputErr) {
			return nil, ResourceInputError{Message: inputErr.Message}
		}
		return nil, err
	}
	return result, nil
}

func (s *ResourceService) routeResource(path string, query map[string]string, uri string) (any, error) {
	switch path {
	case "dashboard/summary":
		return s.dashboardSummary(uri, query)
	case "dashboard/top":
		args, err := resourceToolArgs(query, map[string]bool{"limit": true})
		if err != nil {
			return nil, err
		}
		data, err := s.top.Get(args)
		if err != nil {
			return nil, err
		}
		return resourceContent(uri, data, "application/json"), nil
	case "projects/categories":
		if s.categories == nil {
			return nil, errors.New("project categories service unavailable")
		}
		data, err := s.categories.Get(map[string]any{})
		if err != nil {
			return nil, err
		}
		return resourceContent(uri, data, "application/json"), nil
	case "projects/library":
		if s.projectLibrary == nil {
			return nil, errors.New("project library service unavailable")
		}
		args, err := resourceToolArgs(query, map[string]bool{"page": true, "limit": true})
		if err != nil {
			return nil, err
		}
		data, err := s.projectLibrary(args)
		if err != nil {
			return nil, err
		}
		return resourceContent(uri, data, "application/json"), nil
	case "report/latest":
		return s.latestReport(uri, query)
	default:
		if strings.HasPrefix(path, "papers/") {
			if s.papers == nil {
				return nil, errors.New("paper detail service unavailable")
			}
			id := strings.TrimSpace(strings.TrimPrefix(path, "papers/"))
			data, err := s.papers.Get(map[string]any{"paper_id": id})
			if err != nil {
				return nil, err
			}
			return resourceContent(uri, data, "application/json"), nil
		}
		return nil, ResourceInputError{Message: "Unknown resource URI: " + uri}
	}
}

// parseResourceURI 复刻 _parse_resource_uri：netloc 与 path 分别 unquote 后
// 拼接并 strip "/"（Python urlparse 对 aigc-news:opaque 形态落 path；
// Go 落 Opaque，需归并）。
func parseResourceURI(raw string) (string, map[string]string, error) {
	if strings.TrimSpace(raw) == "" {
		return "", nil, ResourceInputError{Message: "resources/read params.uri is required."}
	}
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || u.Scheme != "aigc-news" {
		return "", nil, ResourceInputError{Message: "Only aigc-news:// resource URIs are supported."}
	}
	pathPart := u.Path // url.Parse 已解百分号；Opaque 形态取 Opaque
	if u.Opaque != "" {
		pathPart = u.Opaque
	}
	host := u.Host
	if unescaped, e := url.PathUnescape(host); e == nil {
		host = unescaped
	}
	path := strings.Trim(strings.TrimPrefix(host+pathPart, "/"), "/")
	if path == "" {
		return "", nil, ResourceInputError{Message: "Resource URI path is required."}
	}
	vals := u.Query()
	q := map[string]string{}
	for k, v := range vals {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	return path, q, nil
}

// resourceToolArgs 复刻 _resource_tool_args：query 透传 + 指定字段 int 化，
// 失败报 "{field} must be an integer."。int 值以 float64 承载（工具校验的
// strictInt 接受整值浮点，与 Python int 对齐）。
func resourceToolArgs(query map[string]string, ints map[string]bool) (map[string]any, error) {
	args := map[string]any{}
	for k, v := range query {
		args[k] = v
	}
	for k := range ints {
		if v, ok := query[k]; ok {
			n, e := strconv.Atoi(v)
			if e != nil {
				return nil, ResourceInputError{Message: k + " must be an integer."}
			}
			args[k] = float64(n)
		}
	}
	return args, nil
}

func resourceContent(uri string, data any, mime string) jsonx.Object {
	text := pythonDumps(data)
	if len([]rune(text)) > maxResourceTextChars {
		text = pythonDumps(jsonx.Object{{Key: "truncated", Value: true}, {Key: "reason", Value: "Resource exceeded 100000 characters."}, {Key: "preview", Value: string([]rune(text)[:maxResourceTextChars])}})
	}
	return jsonx.Object{{Key: "contents", Value: []any{jsonx.Object{{Key: "uri", Value: uri}, {Key: "mimeType", Value: mime}, {Key: "text", Value: text}}}}}
}

func resourceMarkdown(uri, text string) jsonx.Object {
	if len([]rune(text)) > maxResourceTextChars {
		text = string([]rune(text)[:maxResourceTextChars]) + "\n\n[truncated]"
	}
	return jsonx.Object{{Key: "contents", Value: []any{jsonx.Object{{Key: "uri", Value: uri}, {Key: "mimeType", Value: "text/markdown"}, {Key: "text", Value: text}}}}}
}

// ── 资源入参清洗（tools.py::_clean_string/_clean_choice 的 query 版） ──────

// cleanQueryString 复刻 _clean_string：缺省取 default、strip、超长报
// "{key} 不能超过 {max_len} 个字符。"（rune 口径）。query 值必为字符串，
// "必须是字符串" 分支不可达。
func cleanQueryString(query map[string]string, key string, maxLen int, def string) (string, error) {
	raw, present := query[key]
	if !present {
		raw = def
	}
	value := strings.TrimSpace(raw)
	if utf8.RuneCountInString(value) > maxLen {
		return "", ResourceInputError{Message: key + " 不能超过 " + strconv.Itoa(maxLen) + " 个字符。"}
	}
	return value, nil
}

// cleanQueryChoice 复刻 _clean_choice：_clean_string(max_len=64) → lower →
// 空回退 default → 枚举校验（sorted 文案）。
func cleanQueryChoice(query map[string]string, key string, choices []string, def string) (string, error) {
	value, err := cleanQueryString(query, key, 64, def)
	if err != nil {
		return "", err
	}
	value = strings.ToLower(value)
	if value == "" {
		value = def
	}
	if !contains(choices, value) {
		sorted := append([]string(nil), choices...)
		sort.Strings(sorted)
		return "", ResourceInputError{Message: key + " 必须是以下之一：" + strings.Join(sorted, ", ") + "。"}
	}
	return value, nil
}

var isoDatePattern = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// validateISODate 复刻 contracts.validate_iso_date 的两段报错。
func validateISODate(value string) error {
	if !isoDatePattern.MatchString(value) {
		return errors.New("date must use YYYY-MM-DD format")
	}
	parsed, err := time.Parse("2006-01-02", value)
	if err != nil {
		return errors.New("date must be a valid calendar date")
	}
	if parsed.Format("2006-01-02") != value {
		return errors.New("date must use YYYY-MM-DD format")
	}
	return nil
}

// ── dashboard/summary ────────────────────────────────────────────────────

func (s *ResourceService) dashboardSummary(uri string, q map[string]string) (any, error) {
	period, err := cleanQueryChoice(q, "period", rankingPeriods, "daily")
	if err != nil {
		return nil, err
	}
	dateValue, err := cleanQueryString(q, "date", 10, "")
	if err != nil {
		return nil, err
	}
	if dateValue != "" {
		if verr := validateISODate(dateValue); verr != nil {
			return nil, ResourceInputError{Message: verr.Error()}
		}
	}
	snapshotDate := dateValue
	if snapshotDate == "" {
		snapshotDate = s.now().Format("2006-01-02")
	}
	finalized, _ := boardStatus(snapshotDate, s.now())
	if s.stats == nil {
		return nil, errors.New("document statistics reader unavailable")
	}
	counts, err := s.stats.GetSourceCounts()
	if err != nil {
		return nil, err
	}
	total := 0
	for _, v := range counts {
		total += v
	}
	todayCount, err := s.stats.GetTodayDocumentCount()
	if err != nil {
		return nil, err
	}
	stats := summaryStats(counts, total, todayCount)
	docs, err := s.top.getDocs(snapshotDate, period, "all")
	if err != nil {
		return nil, err
	}
	docs = dedupeRows(docs)
	top := []any{}
	for _, r := range docs {
		if len(top) >= 10 {
			break
		}
		top = append(top, s.documents.dashboardDocument(r))
	}
	radarDocs := docs
	if len(radarDocs) > 50 {
		radarDocs = radarDocs[:50]
	}
	return resourceContent(uri, jsonx.Object{
		{Key: "top_list", Value: top},
		{Key: "radar", Value: scoreRadar(radarDocs)},
		{Key: "stats", Value: stats},
		{Key: "period", Value: period},
		{Key: "snapshot_date", Value: snapshotDate},
		{Key: "is_finalized", Value: finalized},
		{Key: "is_embargoed", Value: false},
	}, "application/json"), nil
}

// summaryStats 键序：total_documents/today_new_documents/source_counts；
// source_counts 固定六源注册序（Python 侧是 PG GROUP BY 序，生产本就不
// 稳定，回放 fixture 序与注册序一致），额外源按名序殿后。
func summaryStats(counts map[string]int, total, today int) jsonx.Object {
	sc := jsonx.Object{}
	seen := map[string]bool{}
	for _, k := range []string{"arxiv", "github", "news", "producthunt", "hackernews", "x"} {
		seen[k] = true
		sc = append(sc, jsonx.Pair{Key: k, Value: counts[k]})
	}
	var extras []string
	for k := range counts {
		if !seen[k] {
			extras = append(extras, k)
		}
	}
	sort.Strings(extras)
	for _, k := range extras {
		sc = append(sc, jsonx.Pair{Key: k, Value: counts[k]})
	}
	return jsonx.Object{
		{Key: "total_documents", Value: total},
		{Key: "today_new_documents", Value: today},
		{Key: "source_counts", Value: sc},
	}
}

// radarCategory 是 policy.RADAR_CATEGORIES 的一格（dict 序冻结）。
type radarCategory struct {
	name  string
	terms []string
}

var radarCategories = []radarCategory{
	{"大模型", []string{"llm", "foundation model", "language model", "gpt", "llama", "qwen", "mistral", "gemma", "deepseek", "moe", "transformer", "reasoning"}},
	{"智能体", []string{"agent", "agents", "multi-agent", "autonomous", "tool use", "function calling", "planning", "workflow", "orchestration"}},
	{"多模态", []string{"multimodal", "vision-language", "vlm", "image", "video", "audio", "speech", "ocr"}},
	{"数据与评测", []string{"dataset", "data curation", "synthetic data", "benchmark", "evaluation", "eval", "leaderboard", "alignment", "safety"}},
	{"系统与部署", []string{"inference", "serving", "deployment", "quantization", "distillation", "onnx", "vllm", "triton", "latency", "throughput", "edge"}},
}

// scoreRadar 复刻 policy.score_categories：词命中的类别按 doc_weight 加权
// 计数，max<=0 时全 50，否则 round(30 + count/max*70)；round() 是银行家
// 舍入 → math.RoundToEven。SOURCE_WEIGHTS 全 1.0 故 base 省略。
func scoreRadar(docs []DocumentRow) []any {
	counts := make([]float64, len(radarCategories))
	for _, d := range docs {
		text := strings.ToLower(derefString(d.Title) + " " + derefString(d.Summary))
		weight := radarDocWeight(d)
		for i, c := range radarCategories {
			for _, term := range c.terms {
				if strings.Contains(text, term) {
					counts[i] += weight
					break
				}
			}
		}
	}
	max := 0.0
	for _, v := range counts {
		if v > max {
			max = v
		}
	}
	out := []any{}
	for i, c := range radarCategories {
		v := 50
		if max > 0 {
			v = int(math.RoundToEven(30 + (counts[i]/max)*70))
		}
		out = append(out, jsonx.Object{{Key: "name", Value: c.name}, {Key: "value", Value: v}})
	}
	return out
}

// radarDocWeight 复刻 policy.doc_weight：github 按 stars（raw_score or
// score）0.8+min(0.7, x/400)；news 恒 1.0；其余按 claps（claps 列不在
// rank snapshot SELECT 中，恒落到 raw_score）1.0+min(0.3, x/200)。
// Python `or` 链的真值语义：0/None 落入下一候选。
func radarDocWeight(row DocumentRow) float64 {
	source := "arxiv"
	if s := derefString(row.Source); s != "" {
		source = strings.ToLower(s)
	}
	switch source {
	case "github":
		stars := rawScoreAsFloat(row.RawScore)
		if stars == 0 && row.Score != nil {
			stars = *row.Score
		}
		return 0.8 + math.Min(0.7, stars/400.0)
	case "news":
		return 1.0
	default:
		return 1.0 + math.Min(0.3, rawScoreAsFloat(row.RawScore)/200.0)
	}
}

// rawScoreAsFloat 把 raw_score 的 int/float 双形态（fixture 回放保留
// Python int/float 区分）统一成 float64 参与权重计算。
func rawScoreAsFloat(raw any) float64 {
	switch v := raw.(type) {
	case nil:
		return 0
	case *float64:
		if v == nil {
			return 0
		}
		return *v
	case float64:
		return v
	case int64:
		return float64(v)
	case int:
		return float64(v)
	default:
		return 0
	}
}

// ── report/latest ────────────────────────────────────────────────────────

func (s *ResourceService) latestReport(uri string, q map[string]string) (any, error) {
	source, err := cleanQueryChoice(q, "source", rankingSources, "all")
	if err != nil {
		return nil, err
	}
	dateValue, err := cleanQueryString(q, "date", 10, "")
	if err != nil {
		return nil, err
	}
	// _resolve_report_date：锚是 _date.today()（进程本地钟，独立 today 缝）。
	target := dateValue
	if target == "" {
		target = s.today()
	} else if verr := validateISODate(dateValue); verr != nil {
		return nil, ResourceInputError{Message: verr.Error()}
	}
	key := target
	if source != "all" {
		key += "_" + source
	}
	if s.briefings == nil {
		return nil, errors.New("briefing reader unavailable")
	}
	item, err := s.briefings.GetBriefing(key)
	if err != nil {
		return nil, err
	}
	if item == nil {
		return nil, ResourceInputError{Message: "Briefing " + pythonStringRepr(key) + " not found."}
	}
	// locale 清洗在简报 fetch 之后（Python 语序），同时缺失/越界时
	// not-found 优先。
	locale, err := cleanQueryString(q, "locale", 16, "zh-CN")
	if err != nil {
		return nil, err
	}
	text := selectBriefingContent(item, locale)
	base := s.documents.attributionBase()
	if strings.HasPrefix(strings.ToLower(locale), "en") {
		text += "\n\n---\n*Source: [AIGC Radar · aigcnews.cn](" + base + "/report?utm_source=mcp&utm_medium=resource) — full rankings & the AI project library.*"
	} else {
		text += "\n\n---\n*数据来源：[AIGC Radar · aigcnews.cn](" + base + "/report?utm_source=mcp&utm_medium=resource)——完整榜单与 AI 项目库。*"
	}
	return resourceMarkdown(uri, text), nil
}

// selectBriefingContent 复刻 select_briefing_content：en 前缀走
// content_en→content→content_zh，否则 content_zh→content→content_en；
// 取首个 strip 后非空的候选，返回未 strip 的原值。
func selectBriefingContent(item *BriefingRecord, locale string) string {
	candidates := []string{item.ContentZH, item.Content, item.ContentEN}
	if strings.HasPrefix(strings.ToLower(locale), "en") {
		candidates = []string{item.ContentEN, item.Content, item.ContentZH}
	}
	for _, candidate := range candidates {
		if strings.TrimSpace(candidate) != "" {
			return candidate
		}
	}
	return ""
}

// dashboardDocument 复刻 _public_doc(dashboard=True)：pdf_media_url 只认
// local_pdf_path 的媒体库路径（无 arxiv /api/papers/{id}/pdf 代理兜底），
// rank snapshot 的 SELECT 本就不含 local_pdf_path → 生产恒 null。
func (s *DocumentsService) dashboardDocument(row DocumentRow) jsonx.Object {
	doc := s.publicDocument(row)
	for i := range doc {
		if doc[i].Key == "pdf_media_url" && derefString(row.LocalPDFPath) == "" {
			doc[i].Value = nil
		}
	}
	return doc
}
