package projectsearch

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// RerankerConfig 对齐 Python settings 的 PROJECT_RERANKER_* 族
// （backend/app/core/config.py:202-207）与 SILICONFLOW_API_KEY（:259）。
// 字段即环境变量语义（pydantic-settings 无前缀、大小写不敏感）：
//
//	Enabled           ← PROJECT_RERANKER_ENABLED（默认 false）
//	URL               ← PROJECT_RERANKER_URL（默认 https://api.siliconflow.cn/v1/rerank）
//	ModelName         ← PROJECT_RERANKER_MODEL_NAME（默认 Pro/BAAI/bge-reranker-v2-m3）
//	TimeoutSeconds    ← PROJECT_RERANKER_TIMEOUT_SECONDS（默认 1.0）
//	CandidateLimit    ← PROJECT_RERANKER_CANDIDATE_LIMIT（默认 20）
//	MinCandidates     ← PROJECT_RERANKER_MIN_CANDIDATES（默认 5）
//	SiliconFlowAPIKey ← SILICONFLOW_API_KEY（默认 ""）
//
// 默认值由 config 层（internal/config）按上行注释落地；本构造函数除
// max(0.1, timeout) 外不做隐式默认（与 Python 逐字一致）。
type RerankerConfig struct {
	Enabled           bool
	URL               string
	ModelName         string
	TimeoutSeconds    float64
	CandidateLimit    int
	MinCandidates     int
	SiliconFlowAPIKey string
}

// allowedRerankerHosts 逐字移植 project_reranker._ALLOWED_RERANKER_HOSTS。
var allowedRerankerHosts = map[string]struct{}{"api.siliconflow.cn": {}}

// ProjectReranker 移植 backend/app/services/project_reranker.py 的
// ProjectReranker.rerank_repo_ids：任一闸门/请求/校验不过都静默返回恒等序
// （strip 后非空的 full_name 原序），不返回 error。
//
// 与 Python 的已知差异（可观察性，不改变返回语义）：Python 在 URL 闸与请求
// 失败时 logger.warning，Go 走 logf（默认 log.Printf，测试可替换）。
type ProjectReranker struct {
	cfg       RerankerConfig
	client    *http.Client
	logf      func(format string, args ...any)
	transport http.RoundTripper // 测试注入；nil 时构造函数装 trust_env=False 传输
}

// NewProjectReranker 构造 reranker。HTTP 客户端逐字对齐 Python：
// httpx.AsyncClient(timeout=max(0.1, timeout), trust_env=False)——
// trust_env=False 在 Go 落地为 Transport.Proxy=nil（不吃 HTTP_PROXY 等
// 环境代理）；超时由 http.Client.Timeout 承载（覆盖连接+读全程，等价于
// Python 的 client timeout 再套同值 asyncio.wait_for）。
func NewProjectReranker(cfg RerankerConfig) *ProjectReranker {
	timeout := time.Duration(math.Max(0.1, cfg.TimeoutSeconds) * float64(time.Second))
	r := &ProjectReranker{cfg: cfg, logf: log.Printf}
	r.client = &http.Client{Timeout: timeout, Transport: r.roundTripper()}
	return r
}

func (r *ProjectReranker) roundTripper() http.RoundTripper {
	if r.transport != nil {
		return r.transport
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil // trust_env=False
	return transport
}

// Close 释放空闲连接（对齐 Python aclose；Go http.Client 无需显式关闭）。
func (r *ProjectReranker) Close() {
	if transport, ok := r.client.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
}

// rerankRequestBody 的字段序逐字对齐 Python dict 插入序
// {"model","query","documents","return_documents"}。
type rerankRequestBody struct {
	Model           string   `json:"model"`
	Query           string   `json:"query"`
	Documents       []string `json:"documents"`
	ReturnDocuments bool     `json:"return_documents"`
}

// RerankRepoIDs 实现 contract.Reranker。门序逐字：
//
//  1. candidates = projects[:max(1, min(candidate_limit, 24))]（Python 切片
//     自动按 len 截断，Go 显式 clamp）；fallback = strip 非空 full_name。
//  2. not enabled or not siliconflow_api_key → fallback。
//  3. len(fallback) < max(2, min_candidates) → fallback。
//  4. URL 必须 scheme=="https" 且 hostname ∈ {"api.siliconflow.cn"}。
//  5. POST（Authorization Bearer + JSON body）→ raise_for_status →
//     payload["results"] 经 validatedIndices 校验。
//  6. 全部失败路径 → fallback；成功 → [fallback[i] for i in indices]。
func (r *ProjectReranker) RerankRepoIDs(query string, projects []map[string]any) []string {
	cap_ := max(1, min(r.cfg.CandidateLimit, 24))
	if cap_ > len(projects) {
		cap_ = len(projects)
	}
	candidates := projects[:cap_]
	fallback := make([]string, 0, len(candidates))
	for _, project := range candidates {
		if repoID := pyTrim(pyStr(pyOr(project["full_name"]))); repoID != "" {
			fallback = append(fallback, repoID)
		}
	}
	if !r.cfg.Enabled || r.cfg.SiliconFlowAPIKey == "" {
		return fallback
	}
	if len(fallback) < max(2, r.cfg.MinCandidates) {
		return fallback
	}
	parsed, err := url.Parse(r.cfg.URL)
	if err != nil || strings.ToLower(parsed.Scheme) != "https" {
		r.logf("projectsearch: reranker URL is not an approved SiliconFlow endpoint")
		return fallback
	}
	if _, ok := allowedRerankerHosts[strings.ToLower(parsed.Hostname())]; !ok {
		r.logf("projectsearch: reranker URL is not an approved SiliconFlow endpoint")
		return fallback
	}

	documents := make([]string, 0, len(candidates))
	for _, project := range candidates {
		documents = append(documents, projectText(project))
	}
	body, err := json.Marshal(rerankRequestBody{
		Model:           r.cfg.ModelName,
		Query:           query,
		Documents:       documents,
		ReturnDocuments: false,
	})
	if err != nil {
		r.logf("projectsearch: reranker request failed: %v", err)
		return fallback
	}
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, r.cfg.URL, bytes.NewReader(body))
	if err != nil {
		r.logf("projectsearch: reranker request failed: %v", err)
		return fallback
	}
	req.Header.Set("Authorization", "Bearer "+r.cfg.SiliconFlowAPIKey)
	req.Header.Set("Content-Type", "application/json")
	resp, err := r.client.Do(req)
	if err != nil {
		r.logf("projectsearch: reranker request failed: %v", err)
		return fallback
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// Python response.raise_for_status() → 上层 except → fallback。
		r.logf("projectsearch: reranker request failed: HTTP %d", resp.StatusCode)
		return fallback
	}
	var payload map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		r.logf("projectsearch: reranker request failed: %v", err)
		return fallback
	}
	indices := validatedIndices(payload["results"], len(fallback))
	if indices == nil {
		return fallback
	}
	ordered := make([]string, 0, len(indices))
	for _, index := range indices {
		ordered = append(ordered, fallback[index])
	}
	return ordered
}

// projectText 逐字移植 _project_text：九字段序 full_name, title,
// description, description_zh, category_name or category_slug,
// subcategory_name or subcategory_slug, " ".join(tags), " ".join(topics),
// language；每段 " ".join(str(v or "").split())，按 Python 真值过滤后
// "\n".join，整体按字符（rune）截 maxChars，空 → "(empty)"。
//
// 注意 Python 语义细节：过滤在空白折叠之前（"   " 真值为真，折叠后贡献
// 空行）；切片按 Unicode 字符而非字节。
func projectText(project map[string]any, maxChars ...int) string {
	limit := 1200
	if len(maxChars) > 0 {
		limit = maxChars[0]
	}
	values := []any{
		project["full_name"],
		project["title"],
		project["description"],
		project["description_zh"],
		pyFirstTruthy(project["category_name"], project["category_slug"]),
		pyFirstTruthy(project["subcategory_name"], project["subcategory_slug"]),
		pyJoinValues(project["tags"]),
		pyJoinValues(project["topics"]),
		project["language"],
	}
	parts := make([]string, 0, len(values))
	for _, value := range values {
		if !pyTruthy(value) {
			continue
		}
		parts = append(parts, pyCollapse(pyStr(pyOr(value))))
	}
	text := strings.Join(parts, "\n")
	if runes := []rune(text); len(runes) > limit {
		text = string(runes[:limit])
	}
	if text == "" {
		return "(empty)"
	}
	return text
}

// validatedIndices 逐字移植 _validated_indices：results 必须是长度等于
// candidateCount 的 list；每项 dict、index 非 bool 且可 int()（float 向零
// 截断、数字字符串可解析）、relevance_score 可 float() 且有限；index 在
// [0,n) 内唯一；按 (-score, index) 排序。任何不符返回 nil（调用方回退
// 恒等序）。
type scoredIndex struct {
	score float64
	index int
}

func validatedIndices(results any, candidateCount int) []int {
	list, ok := results.([]any)
	if !ok || len(list) != candidateCount {
		return nil
	}
	ranked := make([]scoredIndex, 0, len(list))
	seen := make(map[int]struct{}, len(list))
	for _, item := range list {
		entry, ok := item.(map[string]any)
		if !ok {
			return nil
		}
		if _, isBool := entry["index"].(bool); isBool {
			return nil
		}
		index, ok := pyInt(entry["index"])
		if !ok {
			return nil
		}
		score, ok := pyFloat(entry["relevance_score"])
		if !ok {
			return nil
		}
		if index < 0 || index >= candidateCount || math.IsNaN(score) || math.IsInf(score, 0) {
			return nil
		}
		if _, dup := seen[index]; dup {
			return nil
		}
		seen[index] = struct{}{}
		ranked = append(ranked, scoredIndex{score: score, index: index})
	}
	// Python sorted 稳定且键全序（index 唯一），sort.Slice 等价。
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].score != ranked[j].score {
			return ranked[i].score > ranked[j].score
		}
		return ranked[i].index < ranked[j].index
	})
	indices := make([]int, 0, len(ranked))
	for _, item := range ranked {
		indices = append(indices, item.index)
	}
	return indices
}

// pyTruthy 复刻 Python 真值判定（覆盖 JSON 可解码类型）：nil/""/0/false/
// 空 list/空 map 为假，其余为真。
func pyTruthy(value any) bool {
	switch v := value.(type) {
	case nil:
		return false
	case bool:
		return v
	case string:
		return v != ""
	case float64:
		return v != 0
	case float32:
		return v != 0
	case int:
		return v != 0
	case int64:
		return v != 0
	case json.Number:
		return v != "0" && v != "0.0" && v != ""
	case []any:
		return len(v) > 0
	case []string:
		return len(v) > 0
	case map[string]any:
		return len(v) > 0
	default:
		return true
	}
}

// pyFirstTruthy 复刻 `a or b`。
func pyFirstTruthy(values ...any) any {
	for _, value := range values {
		if pyTruthy(value) {
			return value
		}
	}
	if len(values) == 0 {
		return nil
	}
	return values[len(values)-1]
}

// pyOr 复刻 `value or ""`（用于 str(value or "")）。
func pyOr(value any) any {
	if pyTruthy(value) {
		return value
	}
	return ""
}

// pyStr 复刻 str(value)：字符串原样；bool → "True"/"False"；float 走
// CPython repr 口径（1.0 → "1.0"）；nil → "None"；list/map 走近似
// Python 容器 repr（本 schema 下不会出现，仅防御）。
func pyStr(value any) string {
	switch v := value.(type) {
	case nil:
		return "None"
	case string:
		return v
	case bool:
		if v {
			return "True"
		}
		return "False"
	case float64:
		return pyFloatStr(v)
	case float32:
		return pyFloatStr(float64(v))
	case int:
		return strconv.Itoa(v)
	case int64:
		return strconv.FormatInt(v, 10)
	case json.Number:
		return v.String()
	default:
		return ""
	}
}

// pyFloatStr 复刻 CPython float.__repr__（str(float)）：最短往返十进制，
// 定点/科学计数切换阈值为十进制指数 -4 <= exp < 16；定点至少一位小数
// （"1.0"），科学计数省略尾 .0 且指数恒带符号至少两位（"1e+20"、"1e-05"）。
// NaN/Inf 输出 "nan"/"inf"/"-inf"（与 json.dumps 的 NaN/Infinity 不同，
// 这里是 str() 口径）。
func pyFloatStr(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	sci := strconv.FormatFloat(f, 'e', -1, 64)
	mantissa, expText, _ := strings.Cut(sci, "e")
	exp, _ := strconv.Atoi(expText)
	negative := strings.HasPrefix(mantissa, "-")
	digits := strings.ReplaceAll(strings.TrimPrefix(mantissa, "-"), ".", "")
	var out string
	if exp >= -4 && exp < 16 {
		switch {
		case exp >= 0 && len(digits) > exp+1:
			out = digits[:exp+1] + "." + digits[exp+1:]
		case exp >= 0:
			out = digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
		default:
			out = "0." + strings.Repeat("0", -exp-1) + digits
		}
	} else {
		mant := digits[:1]
		if len(digits) > 1 {
			mant += "." + digits[1:]
		}
		sign := "+"
		if exp < 0 {
			sign = "-"
			exp = -exp
		}
		out = mant + "e" + sign + pad2(exp)
	}
	if negative {
		out = "-" + out
	}
	return out
}

func pad2(n int) string {
	if n < 10 {
		return "0" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

// pyJoinValues 复刻 " ".join(str(v) for v in (value or []))：list 逐元素
// str 后 join；字符串按 Python 语义迭代字符（rune）后 join；其他假值
// （nil/空）归一为 ""。
func pyJoinValues(value any) string {
	if !pyTruthy(value) {
		return ""
	}
	switch v := value.(type) {
	case string:
		runes := []rune(v)
		parts := make([]string, 0, len(runes))
		for _, r := range runes {
			parts = append(parts, string(r))
		}
		return strings.Join(parts, " ")
	case []any:
		parts := make([]string, 0, len(v))
		for _, item := range v {
			parts = append(parts, pyStr(item))
		}
		return strings.Join(parts, " ")
	case []string:
		return strings.Join(v, " ")
	default:
		return pyStr(value)
	}
}

// pyIsSpace 复刻 Python str.isspace 单字符判定：unicode.IsSpace 之外
// 补上 Go 不算空白而 Python 算的 \x1c-\x1f（file/group/record/unit
// separator）。
func pyIsSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// pyCollapse 复刻 " ".join(str.split())：按 Python 空白表切分折叠。
func pyCollapse(s string) string {
	return strings.Join(strings.FieldsFunc(s, pyIsSpace), " ")
}

// pyTrim 复刻 str.strip()（同一 Python 空白表）。
func pyTrim(s string) string {
	return strings.TrimFunc(s, pyIsSpace)
}

// pyInt 复刻 int(value) 的校验语义：float 向零截断（NaN/Inf 拒绝）、
// 数字字符串（可选符号、前后空白）解析；其余类型拒绝。bool 由调用方
// 先行拒绝（Python isinstance bool 检查在 int() 之前）。
func pyInt(value any) (int, bool) {
	switch v := value.(type) {
	case float64:
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return 0, false
		}
		return int(math.Trunc(v)), true
	case float32:
		return pyInt(float64(v))
	case int:
		return v, true
	case int64:
		return int(v), true
	case json.Number:
		if parsed, err := v.Int64(); err == nil {
			return int(parsed), true
		}
		if parsed, err := v.Float64(); err == nil {
			return pyInt(parsed)
		}
		return 0, false
	case string:
		trimmed := pyTrim(v)
		if trimmed == "" {
			return 0, false
		}
		digits := trimmed
		if digits[0] == '+' || digits[0] == '-' {
			digits = digits[1:]
		}
		if digits == "" {
			return 0, false
		}
		for _, r := range digits {
			if r < '0' || r > '9' {
				return 0, false
			}
		}
		parsed, err := strconv.Atoi(trimmed)
		if err != nil {
			return 0, false
		}
		return parsed, true
	default:
		return 0, false
	}
}

// pyFloat 复刻 float(value)：数值原样、bool → 1.0/0.0、字符串
// ParseFloat（前后空白先按 Python 空白表剥除）；nil/容器拒绝。
// 有限性由调用方判定（math.isfinite 在 Python 校验链中是独立一步）。
func pyFloat(value any) (float64, bool) {
	switch v := value.(type) {
	case float64:
		return v, true
	case float32:
		return float64(v), true
	case int:
		return float64(v), true
	case int64:
		return float64(v), true
	case bool:
		if v {
			return 1.0, true
		}
		return 0.0, true
	case json.Number:
		parsed, err := v.Float64()
		if err != nil {
			return 0, false
		}
		return parsed, true
	case string:
		parsed, err := strconv.ParseFloat(pyTrim(v), 64)
		if err != nil {
			return 0, false
		}
		return parsed, true
	default:
		return 0, false
	}
}

// 确保 utf8 被使用（rune 遍历在 strings 上已含解码；保留 import 以显式
// 标注 [:1200] 是字符级而非字节级语义）。
var _ = utf8.RuneCountInString
