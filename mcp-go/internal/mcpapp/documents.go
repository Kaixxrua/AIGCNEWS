package mcpapp

// documents.go 移植 search_papers / search_documents 两个工具
// （backend/app/services/mcp/inbound/tools.py::_search_indexed_documents 族）。
//
// 字节级行为准绳（backend/tests/parity/corpus/tools.jsonl）：
//   - 校验文案逐字复刻 pydantic v2（strict + str_strip_whitespace +
//     extra="forbid"）："Field required"、"Input should be a valid string"、
//     "String should have at least N character(s)"、"Input should be a valid
//     integer"、ge/le 与 Literal 枚举文案、"Extra inputs are not permitted"，
//     多错误 "; " 连接，字段顺序 q → source → page → limit → extras（排序）。
//   - 条目键序冻结：id, source, source_channel, title, url, summary,
//     published_date, tags, score, raw_score, rank_in_period, authors,
//     arxiv_id, created_at, pdf_media_url, detail_url。
//   - score/raw_score 是 Python float（jsonx.Float 标记）；raw_score 若来自
//     整数 JSON/fixture 则是 int（原生编码），与 Python 侧 int/float 区分一致。
//   - 响应键序：q, source, total, returned_count, page, page_size,
//     has_next, items, attribution。
//
// 已记录的近似（Go 请求解码丢失信息，语料未覆盖）：
//   - JSON 整数与整值浮点（1 vs 1.0）经 Unmarshal 后同为 float64，
//     StrictInt 一律按整数接受；Python strict 模式拒绝 1.0。
//   - str.strip() 的 Unicode 空白表与 Go unicode.IsSpace 在 \x1c-\x1f 上不同。
//   - extras 报错顺序按键名排序（Python 按输入序，Go map 无法保留）。

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/jsonx"
)

// 文档源枚举（contracts.py SourceChoice；注意没有 github 之外的扩展）。
var documentSourceChoices = []string{"all", "arxiv", "github", "news", "producthunt", "hackernews", "x"}

const documentSourceLiteralMessage = "Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'"

// DocumentRow 镜像 search_document_page 的 SELECT 列；指针承载 SQL NULL
// （→ JSON null）。created_at 在 DDL 中是 VARCHAR(64)，保持字符串。
// raw_score 用 any 承载：DOUBLE PRECISION 列经 pgx 得 float64（→jsonx.Float），
// 但回放 fixture 保留 Python 的 int/float 区分（int 7 原生编码，42.5 走 Float）。
type DocumentRow struct {
	ID            *string
	Source        *string
	SourceChannel *string
	Title         *string
	URL           *string
	Summary       *string
	PublishedDate *string
	Tags          *string
	Score         *float64
	RawScore      any // *float64（生产）或 int64/float64（fixture 回放）
	RankInPeriod  *int32
	LocalPDFPath  *string
	Authors       *string // DB 中是 JSON-TEXT；nil 透传 null
	ArxivID       *string
	CreatedAt     *string
}

// DocumentPage 是 search_document_page 的返回形状。
type DocumentPage struct {
	Items []DocumentRow
	Total int
}

// DocumentSearchReader 是文档检索的存储边界（生产=Postgres，回放=fixture stub）。
// 无 ctx 形参：Python 语义是 asyncio.to_thread 跑到完（客户端断连不取消），
// pg 适配器内部用 context.Background() 保持同语义。
type DocumentSearchReader interface {
	SearchDocumentPage(query, source string, page, pageSize int) (DocumentPage, error)
}

// DocumentsService 装配校验、检索与响应塑形。
type DocumentsService struct {
	documents DocumentSearchReader
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置（presentation.public_base_url：
	// 绝不从请求派生 origin，防缓存投毒），接线时已 TrimRight("/",)。
	publicBaseURL string
}

func NewDocumentsService(documents DocumentSearchReader, publicBaseURL string) *DocumentsService {
	return &DocumentsService{documents: documents, publicBaseURL: publicBaseURL}
}

// NewDocumentsHandlers 注册 search_papers / search_documents。
func NewDocumentsHandlers(documents DocumentSearchReader, publicBaseURL string) Handlers {
	service := NewDocumentsService(documents, publicBaseURL)
	return Handlers{
		"search_papers":    service.SearchPapers,
		"search_documents": service.SearchDocuments,
	}
}

// attributionBase 复刻 attribution._base_url：配置为空回退品牌站点。
func (s *DocumentsService) attributionBase() string {
	if s.publicBaseURL != "" {
		return s.publicBaseURL
	}
	return "https://aigcnews.cn"
}

// SearchPapers 是 search_papers 工具处理器（source 钉死 arxiv）。
func (s *DocumentsService) SearchPapers(arguments map[string]any) (any, error) {
	input, err := validateSearchDocumentsArgs(arguments, false)
	if err != nil {
		return nil, err
	}
	return s.searchIndexedDocuments(input, "arxiv")
}

// SearchDocuments 是 search_documents 工具处理器（"all" 归一为无源过滤）。
func (s *DocumentsService) SearchDocuments(arguments map[string]any) (any, error) {
	input, err := validateSearchDocumentsArgs(arguments, true)
	if err != nil {
		return nil, err
	}
	source := input.source
	if source == "all" {
		source = ""
	}
	return s.searchIndexedDocuments(input, source)
}

// searchIndexedDocuments 复刻 _search_indexed_documents：source 为空表示
// 不过滤，响应里回显 "all"；has_next = page*limit < total。
func (s *DocumentsService) searchIndexedDocuments(input searchDocumentsInput, source string) (jsonx.Object, error) {
	page, err := s.documents.SearchDocumentPage(input.q, source, input.page, input.limit)
	if err != nil {
		return nil, err
	}
	items := make([]any, 0, len(page.Items))
	for _, row := range page.Items {
		items = append(items, s.publicDocument(row))
	}
	responseSource := source
	if responseSource == "" {
		responseSource = "all"
	}
	return jsonx.Object{
		{Key: "q", Value: input.q},
		{Key: "source", Value: responseSource},
		{Key: "total", Value: page.Total},
		{Key: "returned_count", Value: len(items)},
		{Key: "page", Value: input.page},
		{Key: "page_size", Value: input.limit},
		{Key: "has_next", Value: input.page*input.limit < page.Total},
		{Key: "items", Value: items},
		{Key: "attribution", Value: "Data provided by AIGC Radar · " + s.attributionBase()},
	}, nil
}

// publicDocument 复刻 tools._public_doc + presentation.project_pdf_media_url
// + attribution.enrich_doc_detail_url 的合体塑形（dashboard=False 分支）。
func (s *DocumentsService) publicDocument(row DocumentRow) jsonx.Object {
	pdfMediaURL := s.projectPDFMediaURL(row)
	return jsonx.Object{
		{Key: "id", Value: stringOrNil(row.ID)},
		{Key: "source", Value: stringOrNil(row.Source)},
		{Key: "source_channel", Value: stringOrNil(row.SourceChannel)},
		{Key: "title", Value: stringOrNil(row.Title)},
		{Key: "url", Value: stringOrNil(row.URL)},
		{Key: "summary", Value: stringOrNil(row.Summary)},
		{Key: "published_date", Value: stringOrNil(row.PublishedDate)},
		{Key: "tags", Value: stringOrNil(row.Tags)},
		{Key: "score", Value: floatOrNil(row.Score)},
		{Key: "raw_score", Value: rawScoreValue(row.RawScore)},
		{Key: "rank_in_period", Value: intOrNil(row.RankInPeriod)},
		{Key: "authors", Value: parseAuthors(row.Authors)},
		{Key: "arxiv_id", Value: stringOrNil(row.ArxivID)},
		{Key: "created_at", Value: stringOrNil(row.CreatedAt)},
		{Key: "pdf_media_url", Value: pdfMediaURL},
		{Key: "detail_url", Value: s.enrichDetailURL(row)},
	}
}

// projectPDFMediaURL 复刻 project_pdf_media_url：本地文件优先（媒体库路径），
// 否则 arxiv 文档走 /api/papers/{id}/pdf 代理；base 为空时输出相对路径。
// basename 按 Python os.path.basename 语义（仅按 "/" 切，末段为空则空）。
func (s *DocumentsService) projectPDFMediaURL(row DocumentRow) any {
	if local := derefString(row.LocalPDFPath); local != "" {
		return s.publicBaseURL + "/api/media/papers/" + local[strings.LastIndex(local, "/")+1:]
	}
	if derefString(row.Source) == "arxiv" && derefString(row.ID) != "" {
		return s.publicBaseURL + "/api/papers/" + *row.ID + "/pdf"
	}
	return nil
}

// enrichDetailURL 复刻 enrich_doc_detail_url：仅 arxiv 有站内阅读页，
// id 取 strip 后值并经 urllib.parse.quote(safe=”) 百分号编码。
func (s *DocumentsService) enrichDetailURL(row DocumentRow) any {
	id := strings.TrimSpace(derefString(row.ID))
	if derefString(row.Source) == "arxiv" && id != "" {
		return s.attributionBase() + "/papers/" + pythonQuote(id) + "/read?utm_source=mcp&utm_medium=tool"
	}
	return nil
}

// parseAuthors 复刻 _public_doc 的 authors 整形：字符串按 JSON 解析
// （空串/解析失败/非列表 → []），非字符串（NULL）原样透传为 null。
// 解析用 UseNumber 保留 Python json.loads 的 int/float 区分
// （[1] → int 1 原生编码；[1.0] → float 走 jsonx.Float 输出 "1.0"）。
func parseAuthors(raw *string) any {
	if raw == nil {
		return nil
	}
	if *raw == "" {
		return []any{}
	}
	decoder := json.NewDecoder(strings.NewReader(*raw))
	decoder.UseNumber()
	var parsed any
	if err := decoder.Decode(&parsed); err != nil {
		return []any{}
	}
	list, ok := parsed.([]any)
	if !ok {
		return []any{}
	}
	for i, item := range list {
		list[i] = restoreJSONNumber(item)
	}
	return list
}

// restoreJSONNumber 把 UseNumber 解码出的 json.Number 还原为 Python 语义值：
// 整数形态保持原样（json.Number 编码为原始字面量），浮点/指数形态包
// jsonx.Float（Python float repr）。递归处理嵌套（authors 实际是平铺字符串
// 数组，此处只为 json.loads 语义完整）。
func restoreJSONNumber(value any) any {
	switch v := value.(type) {
	case json.Number:
		text := v.String()
		if strings.ContainsAny(text, ".eE") {
			if f, err := strconv.ParseFloat(text, 64); err == nil {
				return jsonx.Float(f)
			}
		}
		return v
	case []any:
		for i, item := range v {
			v[i] = restoreJSONNumber(item)
		}
		return v
	case map[string]any:
		for key, item := range v {
			v[key] = restoreJSONNumber(item)
		}
		return v
	default:
		return value
	}
}

// pythonQuote 复刻 urllib.parse.quote(s, safe=”)：保留 [A-Za-z0-9_.-~]，
// 其余按 UTF-8 字节 %XX（大写十六进制）。不能用 url.PathEscape（保留 '/'
// 语义不同）或 QueryEscape（'+' 空格、'~' 编码差异）。
func pythonQuote(s string) string {
	var buf bytes.Buffer
	for _, b := range []byte(s) {
		switch {
		case b >= 'A' && b <= 'Z' || b >= 'a' && b <= 'z' || b >= '0' && b <= '9' ||
			b == '_' || b == '.' || b == '-' || b == '~':
			buf.WriteByte(b)
		default:
			fmt.Fprintf(&buf, "%%%02X", b)
		}
	}
	return buf.String()
}

func stringOrNil(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

// floatOrNil 把生产侧的 float64 标为 Python float（jsonx.Float）。
func floatOrNil(f *float64) any {
	if f == nil {
		return nil
	}
	return jsonx.Float(*f)
}

// rawScoreValue 保留 raw_score 的 int/float 来源区分：整数值原生编码
// （Python int），浮点值包 jsonx.Float；*float64（pgx 生产路径）恒为 float。
func rawScoreValue(raw any) any {
	switch v := raw.(type) {
	case nil:
		return nil
	case *float64:
		if v == nil {
			return nil
		}
		return jsonx.Float(*v)
	case float64:
		return jsonx.Float(v)
	case int64:
		return v
	case int:
		return v
	default:
		return raw
	}
}

func intOrNil(n *int32) any {
	if n == nil {
		return nil
	}
	return int(*n)
}

func derefString(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// ── 入参校验（pydantic v2 文案逐字复刻） ────────────────────────────────

// searchDocumentsInput 是 SearchPapersInput/SearchDocumentsInput 的合体验证结果。
type searchDocumentsInput struct {
	q      string
	source string // 仅 search_documents；papers 固定 "arxiv" 不经此字段
	page   int
	limit  int
}

// validateSearchDocumentsArgs 复刻 contracts.SearchPapersInput（withSource=false）
// 与 SearchDocumentsInput（withSource=true）的 pydantic v2 校验。
// 错误顺序：字段定义序（q → source → page → limit），extras 最后（键名排序）。
func validateSearchDocumentsArgs(args map[string]any, withSource bool) (searchDocumentsInput, error) {
	input := searchDocumentsInput{source: "all", page: 1, limit: 10}
	var failures []string

	// q: StrictStr, min_length=1, max_length=200，缺失即 Field required。
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
		case length > 200:
			failures = append(failures, "q: String should have at most 200 characters")
		default:
			input.q = q
		}
	}

	// source: Literal，默认 "all"；非枚举值（含非字符串/null）报 Literal 文案。
	if withSource {
		if rawSource, present := args["source"]; present {
			source, ok := rawSource.(string)
			valid := ok
			if valid {
				valid = false
				for _, choice := range documentSourceChoices {
					if source == choice {
						valid = true
						break
					}
				}
			}
			if !valid {
				failures = append(failures, "source: "+documentSourceLiteralMessage)
			} else {
				input.source = source
			}
		}
	}

	// page / limit: StrictInt（整值 float64 近似接受，见包注释）。
	if rawPage, present := args["page"]; present {
		if page, ok := strictInt(rawPage); !ok {
			failures = append(failures, "page: Input should be a valid integer")
		} else if page < 1 {
			failures = append(failures, "page: Input should be greater than or equal to 1")
		} else {
			input.page = page
		}
	}
	if rawLimit, present := args["limit"]; present {
		if limit, ok := strictInt(rawLimit); !ok {
			failures = append(failures, "limit: Input should be a valid integer")
		} else if limit < 1 {
			failures = append(failures, "limit: Input should be greater than or equal to 1")
		} else if limit > 20 {
			failures = append(failures, "limit: Input should be less than or equal to 20")
		} else {
			input.limit = limit
		}
	}

	// extras="forbid"：未知键逐一报错（Python 按输入序；Go 按键名排序）。
	known := map[string]bool{"q": true, "page": true, "limit": true, "source": withSource}
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
		return searchDocumentsInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}

// strictInt 复刻 StrictInt：仅接受整数。Go 请求解码把一切 JSON 数字落成
// float64，无法区分 1 与 1.0（Python strict 拒绝后者）——按整数接受是
// 已记录的近似；非整值/非数字（bool/string/null）一律拒绝。
func strictInt(value any) (int, bool) {
	f, ok := value.(float64)
	if !ok || f != float64(int64(f)) {
		return 0, false
	}
	return int(int64(f)), true
}
